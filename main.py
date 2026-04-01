import asyncio

from fastapi import FastAPI, WebSocket, HTTPException

app = FastAPI()


def run_prompt_flow_sync(prompt: str) -> str:
    """Placeholder for the blocking CrewAI call you will plug in later."""
    return f"crew_result for: {prompt}"


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