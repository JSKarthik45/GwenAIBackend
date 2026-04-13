# FastAPI Backend Implementation for Queued MVP Generator

## Overview
This document describes the FastAPI backend implementation for a queued MVP generator using CrewAI, designed to run on Hugging Face Spaces with in-memory storage only.

---

## Architecture Components

### 1. State Setup ✅

Global variables stored in-memory:

```python
usage_tracker = {}           # Key: user_id, Value: [list of UTC datetime objects]
results_dict = {}            # Key: project_id, Value: {"data": result, "created_at": UTC datetime}
generation_lock = asyncio.Lock()  # Ensures serial processing
```

**Timezone handling**: All timestamps use `datetime.now(timezone.utc)` to avoid Hugging Face Spaces timezone issues.

---

### 2. Sliding Window Rate Limiter ✅

**Function**: `is_over_limit(user_id) -> bool`

**Logic**:
- Filters all user timestamps to keep only those within the last 24 hours
- Compares filtered count against `RATE_LIMIT_PER_24H` (default: 5)
- Uses UTC timezone exclusively to avoid server time-zone bugs
- Returns `True` if limit exceeded

**Configuration**:
```python
RATE_LIMIT_PER_24H = 5  # Max 5 generations per user per 24 hours
TTL_HOURS = 24          # Results expire after 24 hours
```

---

### 3. Background Worker Task ✅

**Function**: `async def generate_mvp_task(user_id, project_id, prompt, project_name)`

**Key Features**:
- Wrapped in `try...finally` block for robust cleanup
- Uses `async with generation_lock:` to ensure **serial processing**
  - All 10+ concurrent users are queued and processed one-by-one in order
- Runs `crew.kickoff()` in thread pool via `asyncio.to_thread()` (doesn't block event loop)
- On success: saves result to `results_dict` with UTC timestamp
- On error: stores error message in `results_dict` for client retrieval
- Updates user's `usage_tracker` with new UTC timestamp upon completion

---

### 4. Background Cleanup Task ✅

**Function**: `async def cleanup_old_results()`

**Logic**:
- Runs every 1 hour (3600 seconds)
- Deletes all `results_dict` entries older than 24 hours
- Must be running in the background, started via app startup event

---

### 5. API Endpoints

#### Endpoint: `POST /api/prompt`

**Request**:
```json
{
  "user_id": "string",
  "prompt": "string",
  "project_name": "string"
}
```

**Validations**:
- All fields required and non-empty
- Rate limit check via `is_over_limit(user_id)`
- Returns `429 Too Many Requests` if exceeded

**Response** (immediate, non-blocking):
```json
{
  "project_id": "uuid-string",
  "status": "queued"
}
```

**Behavior**:
1. Validates inputs and rate limit
2. Generates unique `project_id`
3. Fires `generate_mvp_task()` via `asyncio.create_task()` (non-blocking)
4. Returns immediately with `project_id`
5. Task runs in background, serialized via `generation_lock`

---

#### Endpoint: `POST /api/get-qr`

**Read-only behavior**:
- This endpoint does not create new projects.
- This endpoint does not start agents.
- It only looks up an existing `project_id` in memory.

**Request**:
```json
{
  "project_id": "uuid-string"
}
```

**Response** (if completed):
```json
{
  "status": "completed",
  "data": "...generation result...",
  "error": null
}
```

**Response** (if error occurred):
```json
{
  "status": "error",
  "data": null,
  "error": "...error message..."
}
```

**Response** (if still processing):
```json
{
  "status": "processing",
  "data": null,
  "error": null
}
```

**Behavior**:
1. Checks if `project_id` exists in `results_dict`
2. If found: **pops (removes) from dict** and returns data
3. If not found: returns `"processing"` status
4. Data is deleted from memory immediately upon retrieval (one-time access)

---

#### Endpoint: `GET /api/wakeBackend`

**Response**:
```json
{
  "status": "ok",
  "message": "GwenAI backend is running"
}
```

---

### 6. CORS Configuration ✅

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

Allows requests from all origins (suitable for Hugging Face Spaces).

---

## Startup Process

On app startup (via `@app.on_event("startup")`):
1. Background cleanup task is scheduled
2. Cleanup runs every hour, removing 24-hour-old results

```python
@app.on_event("startup")
async def startup_event():
    asyncio.create_task(cleanup_old_results())
```

---

## Request Flow Diagram

```
Client Request → /api/prompt
    ↓
[Validate inputs]
    ↓
[Check rate limit: is_over_limit(user_id)]
    ↓ (Limit exceeded?)
    └→ Return 429 error
    ↓ (OK, proceed)
[Generate project_id]
    ↓
[Fire background task: asyncio.create_task(generate_mvp_task(...))]
    ↓
[Return project_id immediately ← CLIENT RECEIVES THIS]
    ↓
[Background: Task acquires generation_lock (waits if another task is running)]
    ↓
[Background: Run crew.kickoff() in thread pool]
    ↓
[Background: Save result to results_dict with UTC timestamp]
    ↓
[Background: Update usage_tracker with new UTC timestamp]


Client Request → /api/get-qr
    ↓
[Check if project_id in results_dict]
    ↓ (Found?)
    ├→ Pop from dict & return data
    └→ Return "processing" status
```

---

## Concurrency Model

### Serial Generation (via Lock)

When multiple users submit prompts:

```
User A → Task A (running, has lock)
User B → Task B (queued, waiting for lock)
User C → Task C (queued, waiting for lock)
User D → Task D (queued, waiting for lock)

Tasks execute in order: A → B → C → D
```

Each task:
1. Acquires `generation_lock` via `async with`
2. Runs crew.kickoff() to completion
3. Saves result to `results_dict`
4. Releases lock (next task acquires it)

**Benefits**:
- No concurrent crew execution (avoids resource contention)
- FIFO queue semantics (fair ordering)
- Clients can poll `/api/get-qr` anytime without blocking

---

## In-Memory Storage Guarantees

### Storage Lifecycle

1. **Creation**: When task completes, result stored in `results_dict`
2. **Retrieval**: Client calls `/api/get-qr` → data returned and **deleted immediately**
3. **Expiration**: Background cleanup removes results older than 24 hours
4. **App Restart**: All data is lost (HF Spaces restarts pods)

### No Persistence

- No database
- No file storage
- No Redis cache
- Pure in-memory Python dicts

---

## Error Handling

| Scenario | Handling |
|----------|----------|
| Rate limit exceeded | 429 HTTP status |
| Invalid input | 400 HTTP status |
| Crew execution fails | Error message stored in `results_dict["error"]` |
| Client polling before completion | `status: "processing"` |
| Client polling after 24h expiration | Data gone, return `status: "processing"` |

---

## Configuration

Edit these values in `main.py`:

```python
RATE_LIMIT_PER_24H = 5  # Max generations per user per 24 hours
TTL_HOURS = 24          # Result expiration time
```

---

## Running the Backend

### Local Development

```bash
# Install dependencies
pip install -r requirements.txt

# Run backend
uvicorn main:app --reload --host 0.0.0.0 --port 7860
```

### Hugging Face Spaces

Deploy using `Dockerfile`:
```dockerfile
FROM python:3.10

WORKDIR /app
COPY . .

RUN pip install -r requirements.txt

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7860"]
```

---

## Testing the API

### Submit Prompt

```bash
curl -X POST http://localhost:7860/api/prompt \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "user123",
    "prompt": "React Todo app with dark mode",
    "project_name": "MyTodoApp"
  }'
```

Response:
```json
{
  "project_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "queued"
}
```

### Check Status

```bash
curl -X POST http://localhost:7860/api/get-qr \
  -H "Content-Type: application/json" \
  -d '{
    "project_id": "550e8400-e29b-41d4-a716-446655440000"
  }'
```

Response (while processing):
```json
{
  "status": "processing",
  "data": null,
  "error": null
}
```

Response (after completion):
```json
{
  "status": "completed",
  "data": "...",
  "error": null
}
```

---

## Summary of Implementation ✅

| Requirement | Status | Details |
|---|---|---|
| State Setup | ✅ | `usage_tracker`, `results_dict`, `generation_lock` |
| Rate Limiter | ✅ | Sliding window, UTC timezone, 5/24h default |
| Background Worker | ✅ | Async lock-based serial processing |
| `/api/prompt` endpoint | ✅ | Returns project_id immediately |
| `/api/get-qr` endpoint | ✅ | Pops/deletes data on retrieval |
| CORS middleware | ✅ | Allows all origins |
| TTL cleanup | ✅ | Background task runs every hour |
| UTC timestamps | ✅ | All times use `timezone.utc` |
| Error handling | ✅ | Proper HTTP status codes & error storage |

All requirements are implemented and ready for deployment.

