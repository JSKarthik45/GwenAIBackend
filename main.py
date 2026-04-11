import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, HTTPException

# Make sure the mycrew package is importable when running from repo root
_CREW_SRC = Path(__file__).resolve().parent / "mycrew" / "src"
if str(_CREW_SRC) not in sys.path:
    sys.path.insert(0, str(_CREW_SRC))

from mycrew.main import run as run_generator

app = FastAPI()


def _validate_llm_env() -> None:
    required = [
        "PLANNER_LLM",
        "ARCHITECT_LLM",
        "FEATURE_BUILDER_LLM",
        "GROQ_API_KEY",
    ]
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        raise ValueError(f"Missing required environment variable(s): {', '.join(missing)}")


def run_prompt_flow_sync(prompt: str) -> str:
    """Run the multi-agent crew with the provided prompt and return status text."""
    if not prompt.strip():
        raise ValueError("prompt is empty")

    repo_root = Path(__file__).resolve().parent
    load_dotenv(dotenv_path=repo_root / ".env", override=True)
    _validate_llm_env()

    # Delegate to the generator entry point so the same bootstrap/run flow is used everywhere.
    return run_generator(content_prompt=prompt)


async def run_prompt_flow(prompt: str) -> str:
    # Offload blocking work to a worker thread so the event loop stays responsive
    return await asyncio.to_thread(run_prompt_flow_sync, prompt)

@app.get("/api/wakeBackend")
def read_root():
    return {
        "status": "ok",
        "message": "GwenAI backend is running",
    }

@app.websocket("/ws")
async def handle_prompt(websocket: WebSocket):
    await websocket.accept()

    try:
        payload = await websocket.receive_json()
        prompt = payload.get("prompt", "").strip()

        if not prompt:
            await websocket.send_json({"status": "error", "message": "prompt is required"})
            return

        await websocket.send_json({
            "status": "starting",
            "message": "Starting multi-agent flow for idea-to-MVP React Native Expo app",
            "prompt": prompt,
        })

        crew_result = await run_prompt_flow(prompt)

        await websocket.send_json({
            "status": "completed",
            "message": "CrewAI codegen finished",
            "prompt": prompt,
            "result": crew_result,
        })
    except Exception as exc:  # defensive catch to return errors over the socket
        await websocket.send_json({"status": "error", "message": str(exc)})
    finally:
        await websocket.close()


@app.post("/api/prompt")
async def handle_prompt_api(body: dict):
    prompt = body.get("prompt", "").strip()

    if not prompt:
        raise HTTPException(status_code=400, detail="prompt is required")

    crew_result = await run_prompt_flow(prompt)

    return {
        "status": "completed",
        "message": "CrewAI codegen finished",
        "prompt": prompt,
        "result": crew_result,
    }