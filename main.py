import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi import Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class UTF8JSONResponse(JSONResponse):
    """JSON response that never ASCII-escapes unicode separators like '&'."""

    def render(self, content) -> bytes:
        return json.dumps(
            content,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")

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


def _normalize_qr_url(url: str) -> str:
    """Normalize escaped separators in QR URLs (e.g. \u0026 or %5Cu0026)."""
    if not isinstance(url, str):
        return url

    normalized = url.strip()
    normalized = normalized.replace("%5Cu0026", "&")
    normalized = normalized.replace("\\u0026", "&")
    normalized = normalized.replace("u0026", "&") if "?size=" in normalized and "data=" not in normalized else normalized
    return normalized


def _build_qr_url_from_snack_url(snack_url: str) -> str:
    """Build QR URL from snack URL using a single canonical server-side format."""
    normalized_snack_url = _normalize_qr_url(snack_url)
    return f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={quote(normalized_snack_url, safe='')}"


def _deep_normalize_response_strings(value):
    """Recursively normalize escaped URL separators in nested response payloads."""
    if isinstance(value, str):
        return _normalize_qr_url(value)
    if isinstance(value, dict):
        return {k: _deep_normalize_response_strings(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_deep_normalize_response_strings(v) for v in value]
    return value


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

# Deduplicate repeated prompt submissions that arrive close together
prompt_submission_index: dict[str, dict[str, object]] = {}
prompt_submission_lock = asyncio.Lock()

# Configuration
RATE_LIMIT_PER_24H = 5  # Max 5 generations per user per 24 hours
TTL_HOURS = 24  # Results expire after 24 hours
PROMPT_DEDUPE_WINDOW_MINUTES = 15


def cleanup_generated_mvp_folder() -> None:
    """Delete GeneratedMVP folder after result persistence to free disk space."""
    output_dir = Path(__file__).resolve().parent / "GeneratedMVP"
    if not output_dir.exists():
        logger.info("[cleanup] GeneratedMVP does not exist; skipping delete")
        return

    try:
        shutil.rmtree(output_dir)
        logger.info("[cleanup] Deleted GeneratedMVP after result save")
    except Exception as e:
        logger.warning(f"[cleanup] Failed to delete GeneratedMVP: {e}")


def _generate_qr_placeholder(project_id: str, output_path: str) -> dict:
    """
    Generate real Expo Snack QR code by calling the upload-to-snack.js Node script.
    
    The script uses the Snack SDK to:
    1. Validate the generated app
    2. Resolve dependencies
    3. Upload to Expo Snack servers
    4. Return a working QR code
    
    Returns:
        dict: Contains snack_id, snack_url, qr_image_url, and other Snack metadata
    """
    logger.info(f"[QR Gen] Generating real Expo Snack QR for project {project_id}")
    
    try:
        # Build the full path to the app directory
        app_dir = Path(__file__).resolve().parent / output_path
        
        if not app_dir.exists():
            logger.error(f"[QR Gen] App directory does not exist: {app_dir}")
            raise FileNotFoundError(f"App directory not found: {app_dir}")
        
        # Call the Node upload-to-snack.js script
        script_path = Path(__file__).resolve().parent / "upload-to-snack.js"
        logger.info(f"[QR Gen] Calling Node script: {script_path} with app dir: {app_dir}")
        
        result = subprocess.run(
            ["node", str(script_path), str(app_dir)],
            capture_output=True,
            text=False,
            timeout=60  # 60 second timeout for Snack SDK operations
        )

        # Decode as UTF-8 with replacement so Windows cp1252 doesn't crash on UTF-8 symbols.
        stdout_text = (result.stdout or b"").decode("utf-8", errors="replace")
        stderr_text = (result.stderr or b"").decode("utf-8", errors="replace")
        
        if result.returncode != 0:
            error_msg = stderr_text or stdout_text or "Unknown Node script error"
            logger.error(f"[QR Gen] Node script failed: {error_msg}")
            raise RuntimeError(f"upload-to-snack.js failed: {error_msg}")
        
        logger.info(f"[QR Gen] Node script output:\n{stdout_text}")
        
        # Parse output defensively from full text.
        output_text = stdout_text.strip()
        output_lines = [line.strip() for line in output_text.splitlines() if line.strip()]

        snack_id = None
        snack_url = None
        qr_url = None

        for line in output_lines:
            if line.startswith("snackId:"):
                snack_id = line.split("snackId:", 1)[1].strip()
                continue

            if line.startswith("http") or line.startswith("exp://"):
                if "qrserver.com" in line:
                    qr_url = line
                elif "expo.dev" in line or "u.expo.dev" in line or line.startswith("exp://"):
                    snack_url = line

        # Fallback regex extraction in case line-based parsing misses format changes.
        if not snack_id:
            match = re.search(r"snackId:\s*([A-Za-z0-9_-]+)", output_text)
            if match:
                snack_id = match.group(1)

        if not snack_url:
            match = re.search(r"(exp://[^\s]+|https://(?:snack|u)\.expo\.dev/[^\s]+)", output_text)
            if match:
                snack_url = match.group(1)

        if not qr_url:
            match = re.search(r"(https://api\.qrserver\.com/[^\s]+)", output_text)
            if match:
                qr_url = match.group(1)
        
        if not snack_id or not snack_url:
            logger.error(f"[QR Gen] Could not parse Node script output. snack_id={snack_id}, snack_url={snack_url}, qr_url={qr_url}")
            raise ValueError("Failed to extract Snack data from Node script output")

        # Canonicalize server-side QR URL so API always returns one deterministic format.
        qr_url = _build_qr_url_from_snack_url(snack_url)
        
        qr_data = {
            "qr_code": _normalize_qr_url(qr_url),
            "snack_id": snack_id,
            "snack_url": _normalize_qr_url(snack_url),
            "qr_image_url": _normalize_qr_url(qr_url),
            "project_id": project_id,
        }
        
        logger.info(f"[QR Gen] ✅ Real Snack QR generated: snackId={snack_id}, qrUrl={qr_url}")
        return qr_data
        
    except subprocess.TimeoutExpired:
        logger.error(f"[QR Gen] Node script timed out after 60 seconds")
        raise RuntimeError("Snack upload timed out - bundle validation took too long")
    except Exception as e:
        logger.error(f"[QR Gen] Failed to generate Snack QR: {str(e)}", exc_info=True)
        raise RuntimeError(f"Snack QR generation failed: {str(e)}")


def _normalize_prompt_value(value: str) -> str:
    return " ".join(value.strip().lower().split())


def _build_prompt_signature(user_id: str, prompt: str, project_name: str) -> str:
    return "|".join(
        [
            _normalize_prompt_value(user_id),
            _normalize_prompt_value(prompt),
            _normalize_prompt_value(project_name),
        ]
    )


def _purge_expired_prompt_submissions(now: datetime) -> None:
    cutoff = now - timedelta(minutes=PROMPT_DEDUPE_WINDOW_MINUTES)
    expired_signatures = [
        signature
        for signature, payload in prompt_submission_index.items()
        if payload.get("created_at") and payload["created_at"] < cutoff
    ]
    for signature in expired_signatures:
        prompt_submission_index.pop(signature, None)


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
                
                # Save real crew result to in-memory storage with app_generated status
                now = datetime.now(timezone.utc)
                results_dict[project_id] = {
                    "data": {
                        "project_id": project_id,
                        "project_name": project_name,
                        "completed_at": now.isoformat(),
                        "generator_status": _to_json_safe(result),
                        "output_path": "GeneratedMVP/MyApp",
                        "status": "app_generated",  # Not yet completed, waiting for QR generation
                    },
                    "created_at": now,
                }
                logger.info(f"[Task {project_id}] ✅ SAVED to results_dict with status=app_generated. Total entries: {len(results_dict)}")
                logger.info(f"[Task {project_id}] results_dict keys: {list(results_dict.keys())}")
                
                # Generate placeholder QR code (later: replace with real Expo Snack integration)
                qr_data = _generate_qr_placeholder(project_id, "GeneratedMVP/MyApp")
                results_dict[project_id]["data"]["qr_code"] = qr_data
                # Mark as completed only after QR generation is done
                results_dict[project_id]["data"]["status"] = "completed"
                logger.info(f"[Task {project_id}] ✅ QR generated and status set to completed")
                
                cleanup_generated_mvp_folder()
                
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
                # Error state (do not set to completed)
                cleanup_generated_mvp_folder()
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

app = FastAPI(title="GwenAI MVP Generator Backend", default_response_class=UTF8JSONResponse)

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


class InitUserResponse(BaseModel):
    user_id: str
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


@app.get("/api/init-user", response_model=InitUserResponse)
async def init_user():
    """Generate and return a unique user_id for client initialization."""
    return InitUserResponse(user_id=str(uuid.uuid4()), status="ok")


@app.get("/api/debug/state")
async def debug_state():
    """Debug endpoint to check current state of results and usage tracking."""
    return {
        "results_dict_count": len(results_dict),
        "results_dict_keys": list(results_dict.keys()),
        "usage_tracker_count": len(usage_tracker),
        "usage_tracker_users": {user_id: len(timestamps) for user_id, timestamps in usage_tracker.items()},
        "active_tasks_count": len(active_tasks),
        "prompt_submission_count": len(prompt_submission_index),
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

    signature = _build_prompt_signature(user_id, prompt, project_name)
    now = datetime.now(timezone.utc)

    async with prompt_submission_lock:
        _purge_expired_prompt_submissions(now)

        existing_submission = prompt_submission_index.get(signature)
        if existing_submission:
            existing_project_id = str(existing_submission.get("project_id", "")).strip()
            existing_created_at = existing_submission.get("created_at")
            if existing_project_id and isinstance(existing_created_at, datetime):
                age = now - existing_created_at
                if age <= timedelta(minutes=PROMPT_DEDUPE_WINDOW_MINUTES):
                    logger.info(
                        f"[/api/prompt] Duplicate submission detected for user {user_id}; "
                        f"reusing project_id {existing_project_id}"
                    )
                    return PromptResponse(project_id=existing_project_id, status="queued")

        # Generate unique project_id only for new submissions
        project_id = str(uuid.uuid4())
        logger.info(f"[/api/prompt] Generated project_id {project_id}")

        prompt_submission_index[signature] = {
            "project_id": project_id,
            "created_at": now,
        }

        # Fire off background task without waiting (returns immediately)
        task = asyncio.create_task(generate_mvp_task(user_id, project_id, prompt, project_name))
        active_tasks.add(task)  # Keep strong reference to prevent garbage collection
        logger.info(f"[/api/prompt] Fired background task for project {project_id}, active_tasks count: {len(active_tasks)}")

    return PromptResponse(project_id=project_id, status="queued")


@app.post("/api/get-qr", response_model=QRResponse)
async def get_qr_data(request: QRRequest):
    """
    Read-only QR lookup for a project_id.
    This endpoint never creates a new project, never starts a new agent,
    and never calls the generation pipeline.

    If completed, returns the data and deletes it from memory immediately.
    If still processing or not found, returns processing status.
    """
    project_id = request.project_id.strip()
    logger.info(f"[/api/get-qr] Checking status for project {project_id}. Total results in dict: {len(results_dict)}")
    
    if not project_id:
        raise HTTPException(status_code=400, detail="project_id is required")
    
    # Read-only lookup only: no generation, no task creation, no agent startup.
    if project_id in results_dict:
        logger.info(f"[/api/get-qr] Found result for project {project_id}")
        result_entry = results_dict[project_id]
        result_data = result_entry.get("data")
        
        # Check for error at top level
        if result_entry.get("error"):
            logger.error(f"[/api/get-qr] Project {project_id} has error: {result_entry['error']}")
            # Pop the result and remove it from memory
            results_dict.pop(project_id)
            return QRResponse(
                status="error",
                data=None,
                error=result_entry["error"],
            )
        
        # Data exists, check internal status
        if result_data and isinstance(result_data, dict):
            internal_status = result_data.get("status", "unknown")
            if internal_status == "completed":
                logger.info(f"[/api/get-qr] Project {project_id} completed successfully (QR generated)")
                # Pop the result and remove it from memory
                popped_entry = results_dict.pop(project_id)
                popped_data = popped_entry.get("data") if isinstance(popped_entry, dict) else None
                if isinstance(popped_data, dict):
                    qr_blob = popped_data.get("qr_code")
                    if isinstance(qr_blob, dict):
                        if isinstance(qr_blob.get("qr_code"), str):
                            qr_blob["qr_code"] = _normalize_qr_url(qr_blob["qr_code"])
                        if isinstance(qr_blob.get("qr_image_url"), str):
                            qr_blob["qr_image_url"] = _normalize_qr_url(qr_blob["qr_image_url"])
                popped_data = _deep_normalize_response_strings(popped_data)
                payload = {
                    "status": "completed",
                    "data": popped_data,
                    "error": None,
                }
                raw_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
                raw_json = raw_json.replace("\\u0026", "&").replace("%5Cu0026", "&")
                return Response(content=raw_json.encode("utf-8"), media_type="application/json")
            else:
                # App generated but QR generation not yet done
                logger.info(f"[/api/get-qr] Project {project_id} app generated, waiting for QR generation (status={internal_status})")
                return QRResponse(status="processing", data=None, error=None)
        else:
            # Data is None or not a dict
            logger.warning(f"[/api/get-qr] Project {project_id} has unexpected data structure")
            return QRResponse(status="processing", data=None, error=None)
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