# LLM Onboarding: e-Paper Board

This file is the single handoff context for a new GPT session.
Use it as the source of truth for current scope and priorities.

## 1) Project Snapshot

- Repo: `YongBoYu1/intelli-spark-e-paper-board`
- Active branch used for current work: `codex/kitchen-ui`
- Hardware target now: Waveshare 7.5" V2 e-paper (800x480) on Raspberry Pi for development.
- Product direction later: MCU-based device (Pi is dev host, not final product).
- Current focus: complete interactive app system in Python first, then migrate architecture to MCU firmware.

## 2) Hard Constraints

- Do not edit third-party Waveshare driver files under `third_party/`.
- Keep display lifecycle correct:
  - `init` once
  - render many times
  - `sleep` only on exit/long idle
- Never call panel sleep after every frame in an interactive loop.
- Keep app code separate from driver code to make C/C++/Rust migration easier.

## 3) Main Entry Points

- Local simulator (interactive, no hardware):
  - `python tools/sim_app_tk.py`
- UI theme tuner:
  - `python tools/ui_tuner_tk.py`
- Hardware interactive runner (Pi + panel):
  - `python tools/run_epaper_console.py --theme ui_tuner_theme.json`
- One-shot render:
  - `python main.py --png out.png --size 800x480 --theme ui_tuner_theme.json`

## 4) Current Architecture (Python)

- State and events:
  - `app/core/state.py`
  - `app/core/reducer.py`
- Root renderer/router:
  - `app/ui/app.py`
- Home variants:
  - Classic home: `app/ui/home.py`
  - Kitchen home (current default): `app/ui/home_kitchen.py`
- Detail views:
  - Calendar: `app/ui/calendar.py`
  - Weather detail: `app/ui/weather_detail.py`
  - Menu: `app/ui/menu.py`
- Hardware adapter:
  - `app/render/epd.py`

## 5) Fonts and Assets

- Font files expected in `assets/fonts/`:
  - Inter family
  - JetBrains Mono
  - Playfair Display
- Font fallback logic is in `app/shared/fonts.py`.
- Missing font files will cause visual mismatch and should be treated as a blocking setup issue for hardware validation.
- Shared e-ink font template:
  - Runtime defaults: `app/shared/panel_font_templates.py`
  - JSON preset: `assets/themes/panel_font_template_eink_balanced_v1.json`
  - Build path: `app/render/panel.py` auto-applies `panel_font_template` (default `eink_balanced_v1`).

## 6) Input/Navigation Model (Current)

- Rotate left/right: focus navigation.
- Click: activate focused item (open detail or toggle task).
- Long press: voice overlay stub.
- Back: return to previous screen/menu behavior in reducer.
- Tick event drives:
  - idle state
  - delayed task reorder
  - timer updates
  - auto memo rotation

## 7) Known Gaps To Finish

- Home screen parity still needs polish in some typography/spacing details.
- Weather temperature styling:
  - high/low visual hierarchy and placement still need final matching.
- Header meta typography:
  - "PAGE x/y" style/position not fully matched to reference.
- Reminder pagination logic must always match actual dataset:
  - if all tasks fit on one page, show `1/1`.
- Final hardware parity pass is required after each layout adjustment.

## 8) What "Done" Means For This Phase

- Home + Calendar + Weather detail + Menu all navigable from one interaction model.
- Screen output on panel visually matches local output for same theme/data.
- No recurring SPI/FD runtime failures during interaction loop.
- One command can run full interaction on Pi:
  - `python tools/run_epaper_console.py --theme ui_tuner_theme.json`
- Remaining work is feature expansion, not stabilization.

## 9) Working Style For Next GPT

- Keep one master issue for this phase (no issue explosion).
- Update this file when assumptions change.
- Prefer small, testable commits.
- Validate in this order:
  - local simulator
  - PNG snapshot
  - real panel on Pi
