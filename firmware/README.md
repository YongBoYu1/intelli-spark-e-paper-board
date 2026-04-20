# Firmware (C++ Runtime) Guide

This document is the source-of-truth README for the ESP32-S3 C++ firmware in `firmware/`.
It explains project structure, runtime flow, startup behavior, and product-facing configuration switches.

## 1. Build And Flash

Requires [ESP-IDF v5.3](https://docs.espressif.com/projects/esp-idf/en/v5.3/) with `IDF_PATH` configured.

```bash
cd firmware
source ~/esp/esp-idf/export.sh
idf.py set-target esp32s3   # first time only
idf.py build
idf.py -p /dev/cu.usbmodem* flash monitor
```

Serial controls in monitor:
- `a`/`d` (or `h`/`l`): rotate
- `c` (or Enter/Space): click
- `m`: long-press
- `b`: back
- `o`: trigger voice recording (tap once, speak within 5 s)
- `t<epoch><Enter>`: sync wall clock
- `v<HH>`: VCOM sweep

Reference: `firmware/main/main.cpp`

## 2. Runtime Architecture

Unidirectional runtime:

`Event -> Reducer -> AppState -> Render -> Display`

Main path:
- `firmware/main/main.cpp`: loop, serial input, Tick dispatch
- `firmware/main/app/reducer.cpp`: state transitions
- `firmware/main/app/runtime.cpp`: dirty planning, refresh decision, render staging
- `firmware/main/ui/render_app.cpp`: screen router
- `firmware/main/platform/display.cpp`: full/partial display driver

## 3. Source Tree (Firmware)

```text
firmware/
  README.md
  docs/
    display_experiments.md
  main/
    main.cpp
    CMakeLists.txt
    app/
      state.hpp/.cpp
      events.hpp
      defaults.hpp/.cpp
      reducer.hpp/.cpp
      runtime.hpp/.cpp
      refresh_policy.hpp/.cpp
      calendar_runtime.hpp/.cpp
    platform/
      board_config.hpp/.cpp
      panel_config.hpp
      display.hpp/.cpp
      clock.hpp/.cpp
      live_data_provider.hpp/.cpp
      wifi_driver.hpp/.cpp
      mic_driver.hpp/.cpp
      voice_client.hpp/.cpp
    ui/
      render_app.hpp/.cpp
      draw.hpp/.cpp
      primitives.hpp/.cpp
      screens/
        *_screen.cpp / *_screen_landscape.cpp / *_screen_portrait.cpp
```

## 4. Engineering Docs Structure

Primary docs relevant to C++ runtime:
- `firmware/README.md` (this file): runtime entry guide
- `firmware/docs/display_experiments.md`: display bring-up and driver notes
- `docs/EPD_REFRESH_STRATEGY_PLAYBOOK.md`: board-level refresh policy standard
- `docs/SETTINGS_V1.md`: settings behavior contract
- `docs/issues/*.md`: issue handoff docs and parity checkpoints

Recommended usage:
- Read `firmware/README.md` first for code map and startup behavior
- Use `docs/issues/*.md` as migration/change history
- Use refresh playbook before changing partial/full strategy

## 5. Startup Behavior (Home vs Landing)

This is the most common product confusion.

Current implementation details:
1. `Runtime::boot()` loads defaults via `make_factory_defaults()` and `make_state_from_defaults()`.
2. `resolve_boot_screen()` returns:
   - `Home` when `defaults.setup_completed == true`
   - `Landing` when `defaults.setup_completed == false`
3. In current branch, `make_factory_defaults()` sets `setup_completed = true`, so boot enters Home.

Code locations:
- `firmware/main/app/defaults.cpp`
  - `make_factory_defaults()`
  - `resolve_boot_screen()`
  - `make_state_from_defaults()`
- `firmware/main/app/runtime.cpp` (`Runtime::boot()`)

### How Product Can Switch To Landing Start

Option A (recommended for product behavior):
1. Edit `firmware/main/app/defaults.cpp`
2. In `make_factory_defaults()`, set:
   - `defaults.setup_completed = false;`
3. Rebuild and flash.

Result:
- Boot starts at `Screen::Landing`.
- Flow becomes `Landing -> Onboarding -> Home`.

Option B (debug-only force):
- Hard-force `resolve_boot_screen()` to return `Screen::Landing` regardless of defaults.
- Use only for temporary debugging; do not keep as product default.

## 6. Refresh / Waveform Current State

Display and refresh knobs are in `firmware/main/platform/display.cpp`.

Current key defaults:
- `kEnablePartialRefresh = true`
- `kUseHostLutWaveformProfile = true`
- `kUseHostLutDualPlaneRefresh = true`

Why host LUT path is enabled:
- There is a contrast regression note in code; host-LUT path is kept as current stable behavior for this panel batch.

Runtime refresh decisions are logged in `firmware/main/app/runtime.cpp`:
- `R1_PARTIAL_RECTS`
- `R2_FAST_FULL`
- `R3_FULL_CLEAN`

When tuning refresh behavior, update both:
- runtime dirty-reason/rect logic
- display driver waveform assumptions

## 7. Product-Facing Config Knobs

Common knobs and where to change them:
- Boot start screen: `app/defaults.cpp` (`setup_completed` + `resolve_boot_screen`)
- Default rotation: `app/defaults.cpp` (`state.settings.rotation_deg`)
- Timer defaults: `app/reducer.cpp` (`kTimerDefaultSeconds`, `kTimerStepSeconds`, `kTimerMaxSeconds`)
- Partial mode default: `app/defaults.cpp` (`state.settings.partial_refresh_mode`)
- Full refresh cadence: `app/defaults.cpp` (`state.settings.full_refresh_every`)
- Default timezone: `app/defaults.cpp` (`kDefaultTimezone`)

## 8. Screen Routing Notes

Screen routing is centralized in `firmware/main/ui/render_app.cpp`.
Each screen renderer is responsible for orientation-specific layout when needed.

Examples:
- Timer: `timer_screen.cpp` dispatches landscape vs portrait renderer based on rotation
- Weather: `weather_screen.cpp` dispatches landscape vs portrait renderer

## 9. Change Checklist (Before Merging)

For behavior changes, verify:
1. Reducer semantics (`rotate/click/tick/back/long-press`) remain coherent.
2. Dirty reasons and dirty rects are explainable in logs.
3. No unexpected `R2_FAST_FULL` spikes.
4. Product startup expectation (Landing vs Home) is explicitly documented in PR.

## 10. WiFi + Voice Configuration

WiFi and voice backend are configured via `firmware/sdkconfig.defaults`:

```
CONFIG_WIFI_SSID="YourNetwork"
CONFIG_WIFI_PASSWORD="YourPassword"
CONFIG_VOICE_API_URL="http://192.168.x.x:8000"
CONFIG_VOICE_API_TOKEN="your-token-here"
```

After editing `sdkconfig.defaults`, always delete `sdkconfig` before rebuilding:

```bash
rm -f sdkconfig && idf.py build
```

### Microphone Wiring (NR0562 I2S MEMS)

| Signal | GPIO |
|--------|------|
| SCK (BCLK) | 5 |
| WS (LRCLK) | 6 |
| SD (Data)  | 7 |

### Voice Action Dispatch

Voice actions returned by the backend are applied to `AppState` via
`apply_voice_actions()` in `firmware/main/app/reducer.cpp`.

Supported tools (19/19): `open_app`, `shopping_add/remove/clear_all`,
`inventory_log_event/set_expiry/clear_all`, `timer_set/add/pause/resume/stop`,
`memo_add/delete/update/clear_all`, `undo/redo_last_action_group`.

Undo/redo history is snapshot-based (up to 10 steps). `open_app` and `no_action`
are excluded from undo history.

## 11. Related Context Files

- `docs/issues/2026-04-05-issue-51-52-53-closeout-plan.md`
- `docs/issues/2026-04-08-issue-63-home-portrait-parity-handoff.md`
- `docs/issues/2026-04-09-issue-70-timer-portrait-parity-handoff.md`
