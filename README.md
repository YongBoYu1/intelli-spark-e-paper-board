# Fridge Ink (Linux User-Space) — E-Paper AI Fridge Magnet Firmware

This repository contains a **Linux user-space** C application for a 7.5" e-paper fridge magnet running on **Raspberry Pi / Jetson**.  
It drives a Waveshare e-paper panel, renders a multi-screen UI navigated by a **rotary knob (rotate + press)**, supports **voice input**, and calls a backend that can route requests to **Gemini** for AI actions.

> Design goals: product-grade structure (not demo-style), modular components, testable core logic, minimal hardware-specific code, and clean separation from third-party drivers.

---

## Current Prototype (Python) Quick Start

Today this repo contains Python prototypes (for example `test_homepage.py`) that run on top of the Waveshare Python driver.

1) Initialize the Waveshare submodule:
```bash
git submodule update --init --recursive
```

2) Install Python deps:
```bash
pip install pillow
```
Optional (hardware/AI):
```bash
pip install RPi.GPIO google-genai
```

3) Run the homepage:
```bash
WAVESHARE_PYTHON_ROOT=third_party/waveshare_ePaper/RaspberryPi_JetsonNano/python \
  python test_homepage.py
```
Note: the scripts also auto-detect `third_party/waveshare_ePaper/...` without the env var.

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

## Architecture Overview

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

Third-party code (Waveshare) is kept isolated in `third_party/`.

---

## Repository Layout

```txt
fridge-ink/
  README.md
  CMakeLists.txt

  third_party/
    waveshare_epd/
      epd/        # only the exact panel driver(s) you use
      gui/        # GUI_Paint (framebuffer drawing)
      fonts/      # minimal set of fonts required by UI

  src/
    main.c

    app/
      app.c
      app_state.c
      scheduler.c

    ui/
      ui.c
      screens/
        home.c
        weather.c
        calendar.c
        todo.c
        shopping.c
        voice_overlay.c
      widgets/
        list.c
        card.c
        statusbar.c
      render/
        epd_renderer.c

    input/
      knob_linux.c
      events.c

    net/
      http_client.c
      api_client.c

    voice/
      audio_capture_alsa.c
      voice_session.c
      vad.c (optional)

    ai/
      action_router.c

    sync/
      sync.c
      oplog.c

    storage/
      kv.c
      cache.c

    hal_linux/
      spi_spidev.c
      gpio_gpiod.c
      time_linux.c

  include/        # headers mirroring src modules
  tests/
    test_action_router.c
    test_sync.c
    test_json.c
