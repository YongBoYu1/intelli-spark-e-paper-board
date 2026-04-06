# Firmware — ESP32-S3 C++ Runtime

ESP32-S3 firmware for the Fridge Ink smart home e-paper board.

## Hardware

| Component | Spec |
|-----------|------|
| MCU | ESP32-S3 (QFN56, N16R8 — 16MB flash, 8MB PSRAM) |
| Display | Waveshare 7.5" e-Paper V2 (UC8176, 800×480, B/W) |
| SPI | Hardware SPI, 4 MHz |
| GPIOs | RST=4, PWR=8, MOSI=11, CLK=12, BUSY=14, DC=21, CS=47 |

## Build & Flash

Requires [ESP-IDF v5.3](https://docs.espressif.com/projects/esp-idf/en/v5.3/) installed with `IDF_PATH` set.

```bash
cd firmware
source ~/esp/esp-idf/export.sh   # activate ESP-IDF toolchain
idf.py set-target esp32s3        # first time only
idf.py build
idf.py -p /dev/cu.usbmodem* flash monitor
```

Serial input during `monitor`: `a`/`d` = rotate left/right, `c` = click.

## Architecture

Unidirectional data flow: **Event → Reducer → State → Render**.

```
main.cpp (FreeRTOS loop, 50ms tick)
  → Runtime::dispatch(Event)
    → reduce(AppState&, Event)
    → render_app(AppState, Display)
```

### Directory Structure

```
main/
├── main.cpp                     Entry point, FreeRTOS loop, serial input
├── app/
│   ├── state.hpp                AppState, Screen enum, sub-state structs
│   ├── events.hpp               Event types (Rotate, Click, Tick)
│   ├── reducer.cpp              All state transitions
│   └── runtime.cpp              Runtime class (owns state + display)
├── platform/
│   ├── display.cpp              SPI driver, panel init, refresh logic (~500 lines)
│   ├── display.hpp              Display interface (display_image)
│   ├── panel_config.hpp         Panel constants (800×480)
│   └── board_config.cpp/.hpp    ESP32-S3 GPIO pin mapping
└── ui/
    ├── draw.cpp/.hpp            Drawing primitives, font engine, text layout
    ├── render_app.cpp/.hpp      Screen router → display.display_image()
    ├── panel_font_assets_generated.hpp   Generated bitmap fonts
    └── screens/
        ├── landing_screen.cpp   Landing page renderer
        ├── onboarding_screen.cpp Onboarding 4-step renderer
        └── home_screen.cpp      Home page renderer
```

### Screen State Machine

`Landing` → `Onboarding` (4 steps: Start, PairQR, Prefs, VoiceGuide) → `Home`

### Display Driver

- Panel Setting 0x00=0x1F (OTP LUT mode)
- Pixel convention: 0=black, 1=white (matches Python `getbuffer()`)
- Full refresh: DTM1 (0x10) + DTM2 (0x13) + 0x12
- Partial refresh: `init_part()` with 0xE0/0xE5, then 0x91/0x90 window

### Asset Generation

```bash
python tools/generate_firmware_font_assets.py   # → panel_font_assets_generated.hpp
python tools/generate_firmware_panel_assets.py   # → assets/*.raw (if needed)
```

## Issue Status

- **Issue #51** (runtime V0 foundation):
  - close by runtime-foundation acceptance (boot/defaults/reducer-driven runtime structure), not by full product parity.
- **Issue #52** (behavior migration + product parity):
  - active closeout track.
  - execution order: finish landscape first, then portrait.
- **Issue #53** (runtime host integration completeness):
  - starts only after `#52` closes.

Primary closeout plan:
- `docs/issues/2026-04-05-issue-51-52-53-closeout-plan.md`

Historical context docs:
- `docs/issues/2026-03-26-issue-52-assignee-context.md`
- `docs/issues/2026-03-26-issue-53-assignee-context.md`
- `docs/issues/2026-03-26-issue-51-freeze-and-issue-52-kickoff.md`
