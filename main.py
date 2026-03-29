from fastapi import FastAPI

app = FastAPI()

@app.get("/")
def read_root():
    return {
        "status": "GwenAI Backend is ONLINE",
        "location": "Hugging Face Spaces",
        "stage": "Production Infrastructure Check"
    }

@app.get("/health")
def health_check():
    return {"status": "healthy"}