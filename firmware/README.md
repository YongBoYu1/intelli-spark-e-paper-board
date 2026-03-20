# Firmware V0

This directory is the first ESP32 C++ runtime skeleton for Issue `#51`.

Current assumptions:

- Target MCU: `ESP32-S3`
- Flash target: `16MB` (`N16R8` board variant)
- Display target: Waveshare `7.5" V2` e-paper
- Runtime stack: `ESP-IDF + C++`
- Boot source: built-in firmware defaults, not `device_config.json`

## Recommended Editor Setup

VS Code extensions that help here:

- `Espressif IDF`
- `clangd`

You do not need an Arduino extension for this track.

## Local Build Prerequisites

Install ESP-IDF first. On a machine with ESP-IDF available:

```bash
cd firmware
idf.py set-target esp32s3
idf.py build
idf.py flash monitor
```

## Current State

- `main.cpp` stays thin and only boots the runtime loop.
- `app/` owns the runtime state, events, defaults, and reducer.
- `ui/` owns screen routing and view-model construction.
- `platform/` owns clock and display glue.
- `platform/board_config.*` is the future home for the ESP32-S3 pin map.

The display implementation is intentionally a serial/logging stub for now in
`main/platform/display.cpp`. Replace that file with the real Waveshare panel
driver integration once the ESP32-S3 pin map and driver choice are frozen.
