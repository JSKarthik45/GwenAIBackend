import asyncio
import logging
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Make sure the mycrew package is importable when running from repo root
_CREW_SRC = Path(__file__).resolve().parent / "mycrew" / "src"
if str(_CREW_SRC) not in sys.path:
    sys.path.insert(0, str(_CREW_SRC))

from mycrew.main import run as run_generator

# Load environment variables
load_dotenv()


def _to_json_safe(value):
    """Convert nested values to JSON-safe primitives."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _to_json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_to_json_safe(v) for v in value]
    return str(value)


def _serialize_crew_output(result) -> dict:
    """Normalize CrewOutput into a JSON-safe dict for API responses."""
    tasks = []
    for task_output in getattr(result, "tasks_output", []) or []:
        tasks.append(
            {
                "name": _to_json_safe(getattr(task_output, "name", None)),
                "description": _to_json_safe(getattr(task_output, "description", None)),
                "summary": _to_json_safe(getattr(task_output, "summary", None)),
                "raw": _to_json_safe(getattr(task_output, "raw", None)),
                "agent": _to_json_safe(getattr(task_output, "agent", None)),
                "output_format": _to_json_safe(getattr(task_output, "output_format", None)),
            }
        )

    return {
        "raw": _to_json_safe(getattr(result, "raw", None)),
        "json_dict": _to_json_safe(getattr(result, "json_dict", None)),
        "pydantic": _to_json_safe(getattr(result, "pydantic", None)),
        "token_usage": _to_json_safe(getattr(result, "token_usage", None)),
        "tasks_output": tasks,
    }


# ============================================================================
# STATE SETUP
# ============================================================================

# Track usage per user: user_id -> list of datetime UTC timestamps
usage_tracker: dict[str, list[datetime]] = {}

# Store generated results: project_id -> {"data": qr_data, "created_at": datetime}
results_dict: dict[str, dict] = {}

# Lock to ensure serial processing of MVP generation tasks
generation_lock = asyncio.Lock()

# Keep strong references to all active tasks to prevent garbage collection
active_tasks: set = set()

# Configuration
RATE_LIMIT_PER_24H = 5  # Max 5 generations per user per 24 hours
TTL_HOURS = 24  # Results expire after 24 hours


# ============================================================================
# RATE LIMITER
# ============================================================================

def is_over_limit(user_id: str) -> bool:
    """
    Check if a user has exceeded the rate limit in the last 24 hours.
    Uses a sliding window with UTC timezone to avoid HF Spaces timezone issues.
    """
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=24)
    
    # Get user's usage history
    user_timestamps = usage_tracker.get(user_id, [])
    
    # Filter to keep only timestamps within the last 24 hours
    recent_timestamps = [ts for ts in user_timestamps if ts > cutoff]
    
    # Update the tracker with filtered list
    if recent_timestamps:
        usage_tracker[user_id] = recent_timestamps
    else:
        usage_tracker[user_id] = []
    
    # Return True if user has hit the limit
    return len(usage_tracker[user_id]) >= RATE_LIMIT_PER_24H


# ============================================================================
# BACKGROUND WORKER
# ============================================================================

async def generate_mvp_task(user_id: str, project_id: str, prompt: str, project_name: str) -> None:
    """
    Background task to generate MVP using CrewAI crew.
    Uses a lock to ensure serial processing without concurrent generations.
    """
    try:
        logger.info(f"[Task {project_id}] Started for user {user_id}")
        
        # Acquire the lock to ensure serial processing
        async with generation_lock:
            logger.info(f"[Task {project_id}] Acquired lock, starting crew generation")
            try:
                # Run the full generator pipeline synchronously in a thread.
                # This path performs Expo bootstrap + src cleanup + crew generation + npm sync.
                def run_crew_sync():
                    logger.info(f"[Task {project_id}] Running full generator pipeline in thread")
                    result = run_generator(content_prompt=prompt)
                    logger.info(f"[Task {project_id}] Generator pipeline completed, result type: {type(result)}")
                    return result
                
                # Execute crew in thread pool to not block event loop
                result = await asyncio.to_thread(run_crew_sync)
                logger.info(f"[Task {project_id}] Thread completed, saving result")
                
                # Save real crew result to in-memory storage
                now = datetime.now(timezone.utc)
                results_dict[project_id] = {
                    "data": {
                        "project_id": project_id,
                        "project_name": project_name,
                        "completed_at": now.isoformat(),
                        "generator_status": _to_json_safe(result),
                        "output_path": "GeneratedMVP/MyApp",
                    },
                    "created_at": now,
                }
                logger.info(f"[Task {project_id}] ✅ SAVED to results_dict. Total entries: {len(results_dict)}")
                logger.info(f"[Task {project_id}] results_dict keys: {list(results_dict.keys())}")
                
                # Update user's usage tracker
                if user_id not in usage_tracker:
                    usage_tracker[user_id] = []
                usage_tracker[user_id].append(now)
                logger.info(f"[Task {project_id}] Updated usage_tracker for user {user_id}")
                
            except Exception as e:
                # Store error in results for retrieval
                logger.error(f"[Task {project_id}] Crew generation failed: {str(e)}", exc_info=True)
                now = datetime.now(timezone.utc)
                results_dict[project_id] = {
                    "data": None,
                    "error": str(e),
                    "created_at": now,
                }
                logger.info(f"[Task {project_id}] Stored error in results_dict")
    except Exception as outer_e:
        logger.error(f"[Task {project_id}] Outer exception: {str(outer_e)}", exc_info=True)
    finally:
        logger.info(f"[Task {project_id}] Task complete (finally block), removing from active_tasks")
        # Remove from active tasks to allow garbage collection
        active_tasks.discard(asyncio.current_task())


# ============================================================================
# BACKGROUND CLEANUP TASK
# ============================================================================

async def cleanup_old_results():
    """
    Background task that periodically deletes results older than 24 hours.
    Runs every 1 hour.
    """
    while True:
        try:
            await asyncio.sleep(3600)  # Run every hour
            
            now = datetime.now(timezone.utc)
            cutoff = now - timedelta(hours=TTL_HOURS)
            
            # Find and delete expired results
            expired_keys = []
            for project_id, data in results_dict.items():
                created_at = data.get("created_at")
                if created_at and created_at < cutoff:
                    expired_keys.append(project_id)
            
            for key in expired_keys:
                del results_dict[key]
            
            if expired_keys:
                print(f"Cleaned up {len(expired_keys)} expired results")
        except Exception as e:
            print(f"Error in cleanup task: {e}")


# ============================================================================
# FASTAPI APP SETUP
# ============================================================================

app = FastAPI(title="GwenAI MVP Generator Backend")

# Configure CORS for all origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================================
# REQUEST/RESPONSE MODELS
# ============================================================================

class PromptRequest(BaseModel):
    user_id: str
    prompt: str
    project_name: str


class PromptResponse(BaseModel):
    project_id: str
    status: str


class QRRequest(BaseModel):
    project_id: str


class QRResponse(BaseModel):
    status: str
    data: Optional[dict] = None  # Changed from string to dict to handle any serializable data
    error: Optional[str] = None


# ============================================================================
# API ENDPOINTS
# ============================================================================

@app.get("/api/wakeBackend")
async def wake_backend():
    """Health check endpoint."""
    return {
        "status": "ok",
        "message": "GwenAI backend is running",
    }


@app.get("/api/debug/state")
async def debug_state():
    """Debug endpoint to check current state of results and usage tracking."""
    return {
        "results_dict_count": len(results_dict),
        "results_dict_keys": list(results_dict.keys()),
        "usage_tracker_count": len(usage_tracker),
        "usage_tracker_users": {user_id: len(timestamps) for user_id, timestamps in usage_tracker.items()},
        "active_tasks_count": len(active_tasks),
        "active_tasks_details": f"{len([t for t in active_tasks if not t.done()])} running, {len([t for t in active_tasks if t.done()])} done",
    }


@app.post("/api/prompt", response_model=PromptResponse)
async def submit_prompt(request: PromptRequest):
    """
    Submit a prompt for MVP generation.
    Returns immediately with a project_id.
    The generation happens in the background, serialized via the lock.
    """
    user_id = request.user_id.strip()
    prompt = request.prompt.strip()
    project_name = request.project_name.strip()
    
    logger.info(f"[/api/prompt] Received request from user {user_id}")
    
    # Validate inputs
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id is required")
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt is required")
    if not project_name:
        raise HTTPException(status_code=400, detail="project_name is required")
    
    # Check rate limit (sliding window, last 24 hours)
    if is_over_limit(user_id):
        logger.warning(f"[/api/prompt] Rate limit exceeded for user {user_id}")
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded. Maximum {RATE_LIMIT_PER_24H} generations per 24 hours",
        )
    
    # Generate unique project_id
    project_id = str(uuid.uuid4())
    logger.info(f"[/api/prompt] Generated project_id {project_id}")
    
    # Fire off background task without waiting (returns immediately)
    task = asyncio.create_task(generate_mvp_task(user_id, project_id, prompt, project_name))
    active_tasks.add(task)  # Keep strong reference to prevent garbage collection
    logger.info(f"[/api/prompt] Fired background task for project {project_id}, active_tasks count: {len(active_tasks)}")
    
    return PromptResponse(project_id=project_id, status="queued")


@app.post("/api/get-qr", response_model=QRResponse)
async def get_qr_data(request: QRRequest):
    """
    Retrieve the generated MVP data for a project_id.
    If completed, returns the data and deletes it from memory immediately.
    If still processing or not found, returns processing status.
    """
    project_id = request.project_id.strip()
    logger.info(f"[/api/get-qr] Checking status for project {project_id}. Total results in dict: {len(results_dict)}")
    
    if not project_id:
        raise HTTPException(status_code=400, detail="project_id is required")
    
    # Check if result exists
    if project_id in results_dict:
        logger.info(f"[/api/get-qr] Found result for project {project_id}, retrieving and deleting")
        # Pop the result and remove it from memory
        result_data = results_dict.pop(project_id)
        
        # Return the data or error
        if result_data.get("error"):
            logger.error(f"[/api/get-qr] Project {project_id} has error: {result_data['error']}")
            return QRResponse(
                status="error",
                data=None,
                error=result_data["error"],
            )
        else:
            logger.info(f"[/api/get-qr] Project {project_id} completed successfully")
            return QRResponse(
                status="completed",
                data=result_data.get("data"),
                error=None,
            )
    else:
        # Still processing or not found
        logger.info(f"[/api/get-qr] Project {project_id} not found in results_dict (still processing)")
        return QRResponse(status="processing", data=None, error=None)


# ============================================================================
# STARTUP HOOK
# ============================================================================

@app.on_event("startup")
async def startup_event():
    """Start the background cleanup task on app startup."""
    asyncio.create_task(cleanup_old_results())