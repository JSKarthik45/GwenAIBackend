# Gwen AI GitHub Integration Report

## 1. Objective
This document describes the full GitHub integration implemented for Gwen AI MVP generation.

The integration requirements are:
1. Authenticate a user with GitHub OAuth 2.0 Device Flow.
2. Store GitHub connection once per user.
3. For each MVP generation prompt, create a new private repository.
4. Commit and push generated files using GitHub REST APIs only (no local Git CLI dependency for push).
5. Return repository metadata and URL in the final generation result so the frontend can persist and display it.

## 2. High-Level Architecture
The backend integration is split into two layers:
1. Service layer in [github_integration.py](github_integration.py):
   - Encapsulates GitHub OAuth Device Flow and Git Data API operations.
2. API orchestration layer in [main.py](main.py):
   - Exposes endpoints used by the frontend.
   - Manages user/session linkage and generation workflow.
   - Injects GitHub repo payload into final QR/generation response.

### Core behavior model
1. GitHub connection is user-scoped.
2. Repository creation is generation-scoped (one fresh repo per prompt).
3. Generated app push occurs after files are produced and before cleanup.

## 3. Backend Components

### 3.1 Service: GitHubRepoService
File: [github_integration.py](github_integration.py)

Key capabilities:
1. Device Flow start:
   - `request_device_and_user_code()`
2. Device Flow polling:
   - `poll_for_access_token()`
3. Repository creation:
   - `create_repository()`
4. Git Data API commit sequence:
   - `get_latest_commit_sha()`
   - `get_base_tree_sha()`
   - `build_tree_payload()`
   - `create_git_tree()`
   - `create_commit()`
   - `update_branch_reference()`
   - `push_files_to_repo()`
5. Local directory file collection for push payload:
   - `collect_files_from_directory()`

### 3.2 API and orchestration
File: [main.py](main.py)

Important in-memory stores:
1. `github_auth_sessions`
   - Device-code keyed temporary OAuth progress.
2. `github_connected_accounts`
   - User-linked GitHub access tokens.
3. `github_user_repos`
   - User-linked repo metadata cache (if used).

Important workflow functions:
1. `_extract_github_repo_payload(repo_info)`
   - Normalizes repo metadata for frontend payload use.
2. `_ensure_user_github_repo(user_id, access_token)`
   - Creates and caches repo metadata when called.
3. `_maybe_push_generated_mvp_to_github(project_id, user_id, output_path, access_token)`
   - Performs push for generated app directory when GitHub is connected.

## 4. OAuth Device Flow Contract

### 4.1 Start authorization
Routes:
1. `POST /api/github/device-auth`
2. `POST /api/github/device`
3. `POST /api/github/device-flow`
4. `POST /api/auth/github/device`
5. `POST /api/auth/github/device-flow`

Request body:
```json
{
  "user_id": "<uuid>",
  "client_id": "Iv23lioxhi4h5AOWArq8"
}
```

Response (pending):
```json
{
  "status": "pending",
  "device_code": "...",
  "user_code": "...",
  "verification_uri": "https://github.com/login/device",
  "interval": 5,
  "message": "Open the verification URL and enter the GitHub user code to authorize Gwen AI."
}
```

### 4.2 Poll authorization status
Routes:
1. `POST /api/github/device-auth/status`
2. `POST /api/github/device-status`
3. `POST /api/github/device-flow/status`
4. `POST /api/auth/github/device/status`

Request body:
```json
{
  "device_code": "...",
  "user_id": "<uuid>"
}
```

Possible responses:
1. Success:
```json
{
  "status": "success",
  "device_code": "...",
  "access_token": "...",
  "message": "GitHub authorization succeeded."
}
```
2. Pending:
```json
{
  "status": "pending",
  "message": "Authorization is still pending."
}
```
3. Expired:
```json
{
  "status": "expired",
  "message": "GitHub device authorization expired."
}
```

On success, backend stores token in `github_connected_accounts[user_id]`.

## 5. Repository Creation and Push Contract

### 5.1 Manual create route (optional)
Routes:
1. `POST /api/github/create-repo`
2. `POST /api/github/repo/create`
3. `POST /api/github/repository/create`
4. `POST /api/github/setup-repo`
5. `POST /api/auth/github/create-repo`

Request body:
```json
{
  "user_id": "<uuid>",
  "access_token": "<optional_if_user_connected>"
}
```

Response:
```json
{
  "status": "success",
  "message": "GitHub repo created successfully.",
  "repo": {
    "owner": "...",
    "name": "...",
    "default_branch": "main",
    "html_url": "https://github.com/...",
    "full_name": "owner/repo"
  },
  "repo_url": "https://github.com/..."
}
```

### 5.2 Manual push route (optional)
Routes:
1. `POST /api/github/push`
2. `POST /api/github/repo/push`
3. `POST /api/github/repository/push`

Request body:
```json
{
  "user_id": "<uuid>",
  "owner": "<repo_owner>",
  "repo_name": "<repo_name>",
  "directory_path": "GeneratedMVP/MyApp",
  "access_token": "<optional_if_user_connected>"
}
```

Response:
```json
{
  "status": "success",
  "message": "GitHub repo push complete.",
  "push": {
    "owner": "...",
    "repo": "...",
    "branch": "main",
    "latest_commit_sha": "...",
    "base_tree_sha": "...",
    "new_tree_sha": "...",
    "new_commit_sha": "...",
    "ref_response": {}
  }
}
```

## 6. Prompt-to-Repo Lifecycle

### Expected product behavior
1. User connects GitHub once.
2. User submits prompt for MVP generation.
3. Backend generates MVP files.
4. Backend creates a fresh private repository for this prompt.
5. Backend commits and pushes generated files to that new repository.
6. Backend returns QR/generation payload including GitHub repo metadata.
7. Frontend stores payload in AsyncStorage and displays repo link.

### Important distinction
1. Connection scope: per user.
2. Repository scope: per prompt generation.

If this per-prompt repository policy is required, avoid reusing a single cached repository for all prompts.

## 7. Final Result Payload Requirements
The final completed response returned through `POST /api/get-qr` should include:

```json
{
  "status": "completed",
  "data": {
    "project_id": "...",
    "status": "completed",
    "qr_code": {
      "qr_code": "...",
      "snack_url": "...",
      "qr_image_url": "...",
      "expo_go_url": "..."
    },
    "github_repo": {
      "owner": "...",
      "name": "...",
      "full_name": "owner/repo",
      "default_branch": "main",
      "html_url": "https://github.com/owner/repo"
    },
    "github_repo_url": "https://github.com/owner/repo"
  },
  "error": null
}
```

This contract is consumed by the frontend QR/details page and stored locally.

## 8. Frontend Integration Requirements

### 8.1 Persistent user identity
1. Call `GET /api/init-user` once.
2. Store user id in AsyncStorage.
3. Reuse same user id for all GitHub and prompt requests.

### 8.2 Persistent GitHub auth state (one-time connect)
Store per user in AsyncStorage:
```json
{
  "userId": "<uuid>",
  "githubConnected": true,
  "accessToken": "...",
  "login": "...",
  "avatarUrl": "...",
  "connectedAt": "ISO_TIMESTAMP"
}
```

### 8.3 Prompt submission
Send `user_id` consistently on every `POST /api/prompt` request.

### 8.4 Project result persistence
Store each generation result separately:
1. `project_id`
2. `qr_code` metadata
3. `github_repo`
4. `github_repo_url`

## 9. Error Handling Guidance

### Backend
1. Return 400 for missing required identifiers (`user_id`, `device_code`, `owner` when needed).
2. Return 404 if generated directory is missing for push route.
3. Return clear status values for device polling (`pending`, `success`, `expired`, `error`).

### Frontend
1. Show distinct UI states: awaiting authorization, connected, expired, failed.
2. Retry polling on `pending` only.
3. Stop polling and prompt reconnection on `expired`.
4. Show repo creation/push errors without blocking QR retrieval when generation succeeds.

## 10. Security and Operational Considerations
1. Access tokens are sensitive and should not be logged in plaintext.
2. In-memory stores are ephemeral. Production should migrate to durable storage.
3. Consider encrypting stored tokens if persisted server-side.
4. Apply request throttling and per-user generation limits (already modeled in backend).
5. Consider unique repo naming per prompt to avoid GitHub name collisions.

## 11. Recommended Adjustments for Per-Prompt Repo Creation
To strictly enforce "repo per prompt":
1. Do not reuse a single user-cached repository for all prompts.
2. Generate a unique repository name per project request.
3. Create repository inside generation flow for each new `project_id`.
4. Store repo metadata alongside project result payload.

Suggested naming pattern:
1. `gwen-ai-{sanitized-project-name}-{short-project-id}`

## 12. End-to-End Test Checklist
1. Start backend and initialize user.
2. Start GitHub device flow and authorize with real GitHub account.
3. Poll status until success.
4. Submit first prompt and wait for completion.
5. Confirm:
   - Repo A exists in GitHub.
   - Generated files are committed.
   - Result payload includes `github_repo_url`.
6. Submit second prompt with same user.
7. Confirm:
   - Repo B exists and is different from Repo A.
   - Files are committed in Repo B.
   - Frontend displays and stores Repo B URL for second project.
8. Confirm AsyncStorage retains:
   - One GitHub connection record.
   - Separate per-project result records.

## 13. Implementation Files
1. [main.py](main.py)
2. [github_integration.py](github_integration.py)
3. [tests/test_github_integration.py](tests/test_github_integration.py)

## 14. Summary
The Gwen AI GitHub integration supports secure device authorization and Git Data API-based commits for generated MVPs. The intended product contract is:
1. One GitHub connection per user.
2. One new private repository per MVP prompt.
3. Repo metadata included in final generation response for frontend persistence and display.

This report can be used directly as a frontend handoff and backend validation reference.
