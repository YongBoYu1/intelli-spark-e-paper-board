# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Fridge Ink** — a smart home management system built around a 7.5" e-paper display on ESP32-S3, with AI-powered voice control via a cloud backend. The project has three active layers:

1. **Firmware** (`firmware/`) — ESP32-S3 C++ runtime (current production target, Issue #51)
2. **Backend** (`backend/voice_api/`) — Python FastAPI service using Gemini for voice interpretation
3. **Python core** (`app/`) — logic prototyped on Raspberry Pi, being migrated to C++ firmware

The React frontend (`e-ink-smart-fridge-dashboard/`) is an AI Studio–generated simulation tool, not a production component.

---

## Build & Run Commands

### Firmware (ESP-IDF, C++17)
```bash
cd firmware
idf.py set-target esp32s3
idf.py build
idf.py flash monitor
```
Requires ESP-IDF installed and `IDF_PATH` set. The third_party/waveshare_ePaper submodule must be initialized:
```bash
git submodule update --init --recursive
```

### Backend (FastAPI)
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r backend/voice_api/requirements.txt

# Run locally
uvicorn backend.voice_api.app:app --host 0.0.0.0 --port 8000 --reload

# Docker
docker build -f backend/voice_api/Dockerfile -t fridge-ink-voice-api .
docker run --rm -p 8000:8000 -e GOOGLE_API_KEY="${GOOGLE_API_KEY}" fridge-ink-voice-api
```

### Python Tests
```bash
pytest tests/ -v
# Single test file
pytest tests/test_voice_actions.py -v
```

### Frontend (React/Vite)
```bash
cd e-ink-smart-fridge-dashboard
npm install
npm run dev
```

### Asset Generation (tools/)
```bash
python tools/generate_firmware_font_assets.py   # fonts → firmware/main/ui/panel_font_assets_generated.hpp
python tools/generate_firmware_panel_assets.py  # images → firmware/main/assets/*.raw
```

### Desktop Simulator (no hardware needed)
```bash
python tools/sim_app_tk.py   # arrow keys = rotate, space = click
```

---

## Firmware Architecture

The ESP32-S3 firmware follows a strict unidirectional data flow: **Event → Reducer → State → Render**.

### Namespaces
- `fridge_ink::app` — state, events, reducer, runtime
- `fridge_ink::platform` — display SPI driver, board config, clock
- `fridge_ink::ui` — screen routing and rendering

### Data Flow
```
main.cpp (FreeRTOS loop, 50ms tick)
  → Runtime::dispatch(Event)
    → reduce(AppState&, Event)   // pure state mutation
    → render_app(AppState, Display)  // routes to screen renderers
```

### Key Files
| File | Purpose |
|---|---|
| `firmware/main/main.cpp` | Entry point; FreeRTOS loop polling USB serial for input |
| `firmware/main/app/state.hpp` | `AppState`, `Screen` enum, all sub-state structs |
| `firmware/main/app/reducer.cpp` | All state transitions (`reduce()` function) |
| `firmware/main/app/runtime.cpp` | `Runtime` class owning display ref + state |
| `firmware/main/ui/render_app.cpp` | Screen router; dispatches to landing/onboarding/home |
| `firmware/main/platform/display.cpp` | Waveshare 7.5" V2 SPI driver, 800×480, framebuffer |
| `firmware/main/platform/board_config.cpp` | ESP32-S3 GPIO pin mapping |

### Screen State Machine
`Landing` → `Onboarding` (4 steps: Start, PairQR, Prefs, VoiceGuide) → `Home`

Rotary events (`Rotate(delta)`) drive selection; `Click()` confirms/advances. `Tick(ms)` drives periodic refresh.

### Serial Input (Development)
USB JTAG serial is used as a hardware stub during development:
- `a` / `d` → rotate left/right
- `c`, space, or enter → click

---

## Backend Architecture

`POST /voice/interpret` accepts audio (base64) or transcript text, runs Gemini ASR + function calling, and returns a normalized action.

The idempotency cache deduplicates by `request_id` (in-memory, configurable TTL). The `VOICE_ENABLE_NO_ACTION_RETRY` env var enables a low-risk repair pass when Gemini returns `no_action`.

Supported action categories: `inventory_*`, `shopping_*`, `timer_*`, `memo_*`, `open_app`, `undo`, `redo`, `no_action` (~30 tools total defined in `docs/prompt/voice_tools_schema_v1.json`).

---

## Python Core (`app/`)

The Python layer is the reference implementation of the state machine and is tested directly. `app/core/reducer.py` (~63KB) is the canonical logic for all screen transitions, voice action routing, and oplog management. When porting to C++ firmware, this file is the source of truth.

Key modules:
- `app/core/reducer.py` — state machine (all screens, voice actions, oplog)
- `app/core/state.py` — data models (dashboard, lists, timers, memos, settings)
- `app/core/family_board.py` — multi-user household model
- `app/voice/` — voice session workflow (create → upload → commit → poll)

---

## Environment

Copy `.env.example` to `.env` (or set env vars directly):
```
GOOGLE_API_KEY=...
GEMINI_MODEL=gemini-3.1-flash-lite-preview
VOICE_API_URL=https://e-board-voice-api.onrender.com/voice/interpret
VOICE_API_TOKEN=...
```

Backend is deployed to Render via `render.yaml` (auto-deploys on commit to main). Health check: `GET /health`.
