# Voice API (Cloud Backend)

This service provides the cloud endpoint used by device/simulator:
- `POST /voice/interpret`

It uses Gemini function calling and returns:
- legacy `action` (single-action compatibility)
- optional `plan.actions[]` (multi-action execution)

Available action tools:
- `open_app`
- `inventory_log_event`
- `inventory_set_expiry`
- `inventory_clear_all`
- `shopping_add_item`
- `shopping_remove_item`
- `shopping_clear_all`
- `timer_set`
- `timer_add`
- `timer_pause`
- `timer_resume`
- `timer_stop`
- `memo_add`
- `memo_delete`
- `memo_update`
- `memo_clear_all`
- `undo_last_action_group`
- `redo_last_action_group`
- `no_action`

Pipeline:
- Step 1: ASR transcription from uploaded audio
- Step 2: Function calling on transcript -> normalized `plan.actions[]` + first `action` compatibility field

## 1) Install

```bash
cd /Users/yongboyu/Desktop/intelli-spark-e-paper-board
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/voice_api/requirements.txt
```

## 2) Environment

```bash
export GOOGLE_API_KEY="<your-key>"
export GEMINI_MODEL="gemini-2.5-flash"
# Optional: enable one extra low-risk repair pass after an initial no_action.
# Default is off to avoid extra latency on normal requests.
export VOICE_ENABLE_NO_ACTION_RETRY="1"
```

Or put variables in repo root `.env` (auto-loaded by backend and simulator).

## 3) Run

```bash
uvicorn backend.voice_api.app:app --host 0.0.0.0 --port 8000 --reload
```

## 4) Test endpoint

```bash
curl -X POST http://127.0.0.1:8000/voice/interpret \
  -H 'Content-Type: application/json' \
  -d '{
    "request_id":"demo-1",
    "request_time":"2026-02-20T10:00:00+08:00",
    "timezone":"Asia/Shanghai",
    "locale":"en-US",
    "transcript":"Please add eggs to shopping."
  }'
```

## 5) Connect simulator/device

Simulator:
```bash
VOICE_SIM_API_URL="http://127.0.0.1:8000/voice/interpret" python3 tools/sim_app_tk.py
```

Pi runner:
```bash
VOICE_API_URL="http://<server>:8000/voice/interpret" python3 tools/run_epaper_console.py
```

## Notes
- Prompt source: `docs/prompt/voice_prompt_v1.md`
- Tool schema source: `docs/prompt/voice_tools_schema_v1.json`
- `request_id` is idempotent within process memory (simple cache)
- `VOICE_ENABLE_NO_ACTION_RETRY` is off by default.
  - When enabled, the backend may do one additional low-risk retry after an initial `no_action`.
  - This improves recovery for some colloquial phrasing, but it adds latency.
  - If we surface this outside env vars later, it should be a user/operator setting rather than the default path.
- Local correction KB (voice alias memory) path:
  - default: `backend/voice_api/data/correction_kb.json`
  - override: `VOICE_CORRECTION_KB_PATH=/abs/path/to/correction_kb.json`
- Latency budget/SLO template: `docs/VOICE_LATENCY_BUDGET.md`
