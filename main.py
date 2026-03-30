import asyncio

from fastapi import FastAPI, WebSocket

app = FastAPI()

@app.get("/")
def read_root():
    return {
        "status": "ok",
        "message": "GwenAI backend is running; connect via /ws for WebSocket",
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

        # Run the crew in a worker thread to avoid blocking the event loop
        #crew_result = await asyncio.to_thread(run_single_agent, prompt)

        await websocket.send_json({
            "status": "completed",
            "message": "CrewAI codegen finished",
            "prompt": prompt,
            "result": '''crew_result''',
        })
    except Exception as exc:  # defensive catch to return errors over the socket
        await websocket.send_json({"status": "error", "message": str(exc)})
    finally:
        await websocket.close()