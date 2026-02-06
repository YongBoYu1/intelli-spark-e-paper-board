# Hardware Tests (Python)

These scripts are **hardware validation only**. The main firmware is planned in **C**.

## Scripts

- `test_homepage.py`
  Home UI prototype with weather, todos, reminders, text input, and voice flow.
- `test_voice_todo.py`
  Record audio and use Gemini to extract todo items.
- `test_todo.py`
  Simple todo list rendering test.
- `test_clock_gongxi.py`
  Clock display test with partial updates.

## Requirements

- Waveshare 7.5" V2 e-paper panel and Python driver (`waveshare_epd`).
- `Pillow` (PIL).
- Optional: `RPi.GPIO` for button input.
- Optional: `google-genai` and `GOOGLE_API_KEY` for Gemini parsing.

## Driver Paths

The scripts try to find the Waveshare Python driver via:

- `WAVESHARE_PYTHON_ROOT` environment variable
- Common install paths under `/e-Paper/` and `/home/*/e-Paper/`

## Runtime Files

The scripts write runtime artifacts to this folder:

- `run.log`
- `last_frame.png`
- `todo.txt`
- `reminders.json`
