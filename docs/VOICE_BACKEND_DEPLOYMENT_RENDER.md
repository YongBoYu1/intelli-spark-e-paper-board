# Voice Backend Deployment Baseline (Render + Docker)

This document is the deployment runbook for the hosted Voice API baseline.

## Why This Baseline

Render + Docker is the current baseline because it matches the backend we already have:

- the service is a single long-running FastAPI process
- the device only needs one stable HTTPS endpoint
- Render handles HTTPS, health checks, and env var management with low ops overhead
- Docker keeps the service portable if we move away from Render later

This is intentionally a V1 baseline, not a full platform build-out.

## Deploy Artifacts In Repo

- Docker image: `backend/voice_api/Dockerfile`
- Render blueprint: `render.yaml`
- Backend entrypoint: `backend/voice_api/app.py`

## Hosted Environment Variables

Required for hosted operation:

- `GOOGLE_API_KEY`
  - Gemini API key used by the backend
- `GEMINI_MODEL`
  - default baseline: `gemini-2.5-flash`
- `VOICE_API_TOKEN`
  - shared device secret; requests to `POST /voice/interpret` are rejected unless they send `Authorization: Bearer <VOICE_API_TOKEN>`

Recommended hosted defaults:

- `VOICE_ENABLE_NO_ACTION_RETRY=0`
  - keep latency predictable on the first hosted baseline
- `VOICE_API_LOG_TRANSCRIPT=0`
  - leave transcript text out of default production logs
- `VOICE_API_VERBOSE_UPSTREAM=0`
  - keep `httpx` and `google_genai` noise down in platform logs

Optional advanced tuning:

- `VOICE_CORRECTION_KB_PATH`
  - override the default local correction KB path if needed
- `VOICE_API_IDEMPOTENCY_TTL_S`
- `VOICE_API_IDEMPOTENCY_MAX_SIZE`
- `VOICE_API_IDEMPOTENCY_WAIT_TIMEOUT_S`

Platform variable:

- `PORT`
  - Render injects this automatically; the included blueprint pins it to `10000`

## Auth Contract

- `GET /health`
  - no auth
  - used for platform uptime checks
- `POST /voice/interpret`
  - if `VOICE_API_TOKEN` is configured on the server, request must include:
    - `Authorization: Bearer <VOICE_API_TOKEN>`
  - missing or invalid token returns `401`

## Device Configuration

Hardware runner:

```bash
VOICE_API_URL="https://<your-service>.onrender.com/voice/interpret" \
VOICE_API_TOKEN="<shared-secret>" \
python3 tools/run_epaper_console.py
```

CLI equivalent:

```bash
python3 tools/run_epaper_console.py \
  --voice-api-url "https://<your-service>.onrender.com/voice/interpret" \
  --voice-api-token "<shared-secret>"
```

Simulator:

```bash
VOICE_SIM_API_URL="https://<your-service>.onrender.com/voice/interpret" \
VOICE_SIM_API_TOKEN="<shared-secret>" \
python3 tools/sim_app_tk.py
```

## Local Docker Smoke Test

Build:

```bash
docker build -f backend/voice_api/Dockerfile -t fridge-ink-voice-api .
```

Run:

```bash
docker run --rm -p 8000:8000 \
  -e GOOGLE_API_KEY="${GOOGLE_API_KEY}" \
  -e GEMINI_MODEL="${GEMINI_MODEL:-gemini-2.5-flash}" \
  -e VOICE_API_TOKEN="${VOICE_API_TOKEN}" \
  fridge-ink-voice-api
```

Health check:

```bash
curl http://127.0.0.1:8000/health
```

Interpret smoke test:

```bash
curl -X POST http://127.0.0.1:8000/voice/interpret \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer ${VOICE_API_TOKEN}" \
  -d '{
    "request_id":"smoke-local-1",
    "request_time":"2026-03-17T12:00:00-04:00",
    "timezone":"America/Toronto",
    "locale":"en-US",
    "transcript":"Add eggs to shopping"
  }'
```

## Initial Render Deploy

Option A: blueprint

1. In Render, create a new Blueprint and point it at this repo.
2. Let Render read `render.yaml`.
3. Fill in `GOOGLE_API_KEY` and `VOICE_API_TOKEN`.
4. Keep `GEMINI_MODEL=gemini-2.5-flash` unless you are actively validating another model.
5. Deploy.
6. Once the service is live, copy the service URL and set:
   - `VOICE_API_URL=https://<service>.onrender.com/voice/interpret`
   - `VOICE_API_TOKEN=<same token configured on Render>`

Option B: manual web service setup

1. Create a new Render Web Service from this repo.
2. Choose `Docker` runtime.
3. Set Dockerfile path to `backend/voice_api/Dockerfile`.
4. Set Docker build context to repo root.
5. Set health check path to `/health`.
6. Add the same env vars listed above.
7. Deploy.

## Post-Deploy Smoke Test

Run these in order:

1. `GET /health` returns `{"status":"ok"}`
2. `POST /voice/interpret` without auth returns `401` when `VOICE_API_TOKEN` is configured
3. `POST /voice/interpret` with valid auth succeeds
4. Device or simulator succeeds against hosted URL for at least:
   - shopping add
   - reminder clear confirm flow
   - inventory add/update
   - timer set
   - family board memo add

## Update Flow

1. Make and review the change on a branch.
2. Merge into the tracked deploy branch.
3. Let Render auto-deploy the new commit, or trigger a manual deploy for that commit.
4. Wait for `/health` to pass.
5. Run the post-deploy smoke test before treating the rollout as complete.

Use config-only deploys when code has not changed:

1. Update env vars in Render.
2. Trigger redeploy if the platform does not restart automatically.
3. Re-run `GET /health` and one authenticated interpret smoke test.

## Rollback Flow

Code rollback:

1. In Render, open the deploy history.
2. Roll back to the last known good deploy.
3. Confirm `/health`.
4. Re-run one authenticated interpret smoke test.

Config rollback:

1. Restore the previous env var values in Render.
2. Redeploy if needed.
3. Re-run the same smoke tests.

## Logging Baseline

Default backend logs now include enough support context for first-line debugging:

- `request_id`
- request mode (`audio` or `transcript`)
- `locale`
- `timezone`
- client host
- action summary
- request duration

Transcript logging is disabled by default and can be enabled temporarily with `VOICE_API_LOG_TRANSCRIPT=1`.
