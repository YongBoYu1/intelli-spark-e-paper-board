# Issue 30 Progress (2026-03-04)

## Scope
This update covers Home, Timer, and Settings interaction polish requested in Issue 30.

## Completed

### Home / Kitchen UI
- Replaced weather focus indicator behavior so focus uses a boxed style consistent with other cards.
- Updated focus routing for left panel:
  - Rotate left from Weather -> Time
  - Rotate left from Time -> Date (weekday/date block)
- Updated click routing on Home left panel:
  - Click on Time enters `Timer`
  - Click on Date enters `Calendar`
- Improved right panel focus model:
  - Inventory header is always focusable and clickable.
  - Shopping section renamed to `REMINDERS`.
  - Reminders header is focusable and clickable.
  - Header click routing:
    - `INVENTORY` header -> `Screen.INVENTORY`
    - `REMINDERS` header -> `Screen.REMINDERS`
- Fixed right-panel header focus box geometry so focus border no longer crosses title text.
- Unified voice lane font usage with panel font tokens from design docs.
- Fixed large-font overlap between Family Board posted timestamp and voice lane.

### Typography
- Increased Home weekday/date sizes by +2:
  - `b_weekday_size`: 13 -> 15
  - `b_date_size`: 16 -> 18

### Timer / Settings header and hints
- Removed Home icon from Timer and Settings title rows.
- Unified hint copy on both pages:
  - `Rotate to select  -  Click to enter  -  Long press to home`
- Removed obsolete hidden Home-focus path in Settings reducer flow after icon removal.

### Timer completion alert
- Added timer completion alert state and tick-driven blinking behavior.
- At countdown completion:
  - `00:00` blinks (inverse style, not blank disappearance).
  - Status text shows English completion copy:
    - `X minute(s) countdown finished`
- Added theme knobs:
  - `timer_alert_show_s` (default 6.0)
  - `timer_alert_blink_period_s` (default 0.45)
- Added timer alert state to refresh/snapshot/signature paths so blinking continues across partial-refresh pipeline.

## Key files touched
- `app/ui/home_kitchen.py`
- `app/ui/app.py`
- `app/ui/timer.py`
- `app/ui/settings.py`
- `app/ui/placeholder.py`
- `app/core/kitchen_queue.py`
- `app/core/reducer.py`
- `app/core/state.py`
- `app/render/refresh_policy.py`
- `tools/run_epaper_console.py`
- `tests/test_home_kitchen_focus.py`
- `tests/test_timer_reducer.py`
- `tests/test_refresh_policy.py`

## Validation
- `python3 -m py_compile` on modified runtime/UI modules
- `PYTHONPATH=. python3 tests/test_home_kitchen_focus.py`
- `PYTHONPATH=. python3 tests/test_timer_reducer.py`
- `PYTHONPATH=. python3 tests/test_refresh_policy.py`
- `PYTHONPATH=. python3 tests/test_run_epaper_console_partial.py`

## Notes
- Full test discovery still reports one unrelated environment issue when `python-dotenv` is missing (`tests/test_shared_env.py`).
- Local workspace currently has untracked content inside submodule path `third_party/waveshare_ePaper`; this issue update does not modify or stage that submodule content.
