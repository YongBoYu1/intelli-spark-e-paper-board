# Fridge Ink (Linux User-Space) — E-Paper AI Fridge Magnet Firmware

This repository targets a **Linux user-space C firmware** for a 7.5" e-paper fridge magnet running on **Raspberry Pi / Jetson**.
It drives a Waveshare e-paper panel, renders a multi-screen UI navigated by a **rotary knob (rotate + press)**, supports **voice input**, and calls a backend that can route requests to **Gemini** for AI actions.

> Primary language: **C** (firmware). The **Python scripts are only for hardware validation** and live under `hardware_tests/`.

---

## Status

- **C firmware**: architecture planned, implementation pending.
- **Hardware validation**: Python scripts to verify display, input, audio, and API integration.

---

## Features (Planned / In Progress)

### UI & Navigation
- Multiple screens: **Home**, **Weather**, **Calendar**, **Todo**, **Shopping**, **Voice Overlay**
- **Focus-based navigation** for knob input (rotate to move focus, press to activate, long-press for global menu/voice)
- E-paper friendly rendering:
  - Avoid frequent full refresh
  - Refresh on demand (dirty/dirty-page) where possible

### Input
- Rotary knob via:
  - **GPIO encoder** (A/B + press) using `libgpiod`, or
  - **USB HID / evdev** (optional)
- Debounce + event abstraction layer

### Voice + AI
- Audio capture via **ALSA**
- Voice session workflow:
  - Create voice session → upload audio → commit → poll result
- Backend-driven ASR + Gemini tool/actions:
  - Gemini returns **structured actions** (e.g., create todo, add shopping items)
  - Firmware applies actions via an **action_router**

### Networking & Sync
- HTTPS calls to backend (recommended: `libcurl`)
- Dashboard aggregation endpoint for efficient polling
- Incremental sync via `sync_seq` and oplog for offline actions

### Storage
- Local cache for last dashboard, lists, and device tokens
- Simple key-value file store + optional oplog persistence

### Testing
- Unit tests for:
  - `action_router` (AI actions → state changes)
  - sync/oplog behavior
  - JSON parsing/serialization for dashboard and list items

---

## Hardware Tests (Python)

See `hardware_tests/` for display, UI, weather, todo, and voice prototypes used to validate the hardware stack.

---

## Planned C Architecture

The firmware is split into clear modules:

- `ui/`
  Screen rendering + widgets + e-paper renderer integration.
- `input/`
  Knob drivers (GPIO/evdev) producing abstract events.
- `net/`
  HTTP client + backend API client.
- `voice/`
  ALSA audio capture + voice session workflow.
- `ai/`
  Action router (Gemini actions → local state updates + oplog).
- `sync/`
  Pull diffs + push local operations (offline-safe).
- `storage/`
  KV store + cache + oplog persistence.
- `hal_linux/`
  Linux HAL wrappers for SPI/GPIO/time.

Third-party code (Waveshare) should be isolated in `third_party/`.

---

## Repository Layout (Current)

```txt
intelli-spark-e-paper-board/
  README.md
  .gitignore

  hardware_tests/
    README.md
    test_clock_gongxi.py
    test_homepage.py
    test_todo.py
    test_voice_todo.py
    last_frame.png

  examples/
    clock_gongxi.py
    epd_7in5_V2_test.py
```

## Repository Layout (Target, C Firmware)

```txt
intelli-spark-e-paper-board/
  CMakeLists.txt
  third_party/
  src/
  include/
  tests/
```
