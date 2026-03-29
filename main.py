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
        prompt = payload.get("prompt", "")

        await websocket.send_json({
            "status": "starting",
            "message": "Starting multi-agent flow for idea-to-MVP React Native Expo app",
            "prompt": prompt,
        })

        # Placeholder: invoke CrewAI orchestration here once integrated
        # crew_result = crew_ai_run(prompt)
        crew_result = "CREW_AI_PLACEHOLDER_RESULT"

        await websocket.send_json({
            "status": "completed",
            "message": "Placeholder response after simulated multi-agent run",
            "prompt": prompt,
            "result": crew_result,
        })
    except Exception as exc:  # defensive catch to return errors over the socket
        await websocket.send_json({"status": "error", "message": str(exc)})
    finally:
        await websocket.close()