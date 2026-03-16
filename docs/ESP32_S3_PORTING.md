# ESP32-S3 Porting Notes

## Current State

This repository is currently runnable as a Python prototype on Raspberry Pi / Jetson Linux.
The active runtime depends on:

- `waveshare_epd` Python driver under `third_party/waveshare_ePaper`
- `RPi.GPIO` for rotary/button input
- Linux user-space execution

That means the project is not yet directly runnable on an ESP32-S3 board.

## Target Board

- MCU board: SANXIXING ESP32-S3 development board
- Display target: Waveshare 7.5" V2 e-paper panel
- Config target key: `esp32-s3`
- Suggested board profile: `sanxixing-esp32-s3-wroom-1`

## Bring-Up Milestones

1. Freeze the hardware map.
   - Confirm actual SPI pins used for `DIN`, `CLK`, `CS`, `DC`, `RST`, `BUSY`.
   - Confirm encoder/button pins and their active levels.
   - Confirm panel power path and logic voltage.

2. Choose firmware stack.
   - Recommended: ESP-IDF.
   - Alternative: Arduino core for ESP32.

3. Replace Linux-specific dependencies.
   - `waveshare_epd` Python driver -> ESP32-compatible e-paper driver
   - `RPi.GPIO` -> ESP32 GPIO/SPI input handling
   - Python entrypoints -> embedded firmware entrypoint

4. Preserve reusable logic.
   - Keep UI/state/reducer behavior as the reference product spec.
   - Port rendering and input state machine in stages instead of rewriting behavior ad hoc.

## First Implementation Slice

The lowest-risk first slice for this board is:

1. SPI panel init on ESP32-S3
2. full-screen clear
3. full-screen image draw
4. busy-wait stability
5. rotary/button input smoke test

Only after that should partial-refresh behavior be ported.

## Wiring Capture

The repository does not yet include the final ESP32-S3 pin map because it was not present in the checked-in source.
Once the exact wiring is confirmed, add it here and mirror it into the future firmware board config.
