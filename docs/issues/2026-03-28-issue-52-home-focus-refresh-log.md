# Issue 52 Home Focus / Refresh Log

Date: 2026-03-28
Branch: `codex/52-runtime-migration`
Scope: Home page focus behavior, partial refresh execution, Python parity

## Goal

Bring Home focus behavior on ESP32/C++ into alignment with the Python source of truth:

- initial focus visible and correctly placed
- first rotate renders focus box immediately
- inventory/reminder focus boxes render fully
- reduce interaction lag caused by partial refresh execution

## User-visible failures under investigation

1. Initial Home focus box is misplaced or not visible.
2. First rotate to inventory/reminder/weather/clock often does not render a focus box.
3. Reminder/inventory rows can show half boxes or stale residual lines.
4. Interaction still feels laggy.

## Current root-cause split

### Primary: software / display execution layer

Main file:

- `/Users/yongboyu/Desktop/intelli-spark-e-paper-board/firmware/main/platform/display.cpp`

Why this is the primary layer:

- the failures are directional and repeatable on first interaction
- they affect both left panel and right panel
- reducer state changes are already happening, but the first partial refresh often fails to show the expected box

Current suspected areas:

- hinted partial rect preparation
- hinted partial rect execution strategy
- multi-rect partial updates vs merged transition rect
- partial/full switching cadence

### Secondary: software / Home geometry

Main file:

- `/Users/yongboyu/Desktop/intelli-spark-e-paper-board/firmware/main/ui/screens/home_screen.cpp`

Why this is secondary:

- it explains box placement accuracy problems
- it does not fully explain the “first rotate has no box” failure across both left and right panels

## Python source-of-truth references used

- Home default focus state:
  - `/Users/yongboyu/Desktop/intelli-spark-e-paper-board/app/core/state.py`
- Home focus movement semantics:
  - `/Users/yongboyu/Desktop/intelli-spark-e-paper-board/app/core/reducer.py`
- Home render geometry:
  - `/Users/yongboyu/Desktop/intelli-spark-e-paper-board/app/ui/home_kitchen.py`
  - `/Users/yongboyu/Desktop/intelli-spark-e-paper-board/app/ui/home_kitchen_geometry.py`
- Home dirty rect inference:
  - `/Users/yongboyu/Desktop/intelli-spark-e-paper-board/app/render/refresh_policy.py`
- Python partial refresh execution path:
  - `/Users/yongboyu/Desktop/intelli-spark-e-paper-board/tools/run_epaper_console.py`
- Waveshare reference panel partial routine:
  - `/Users/yongboyu/Desktop/intelli-spark-e-paper-board/third_party/waveshare_ePaper/RaspberryPi_JetsonNano/python/lib/waveshare_epd/epd7in5_V2.py`

## Changes attempted in this cycle

### Geometry / Home render

- corrected Home rotate behavior from wrap toward Python clamp behavior
- unified header focus draw geometry and header focus dirty-rect geometry
- adjusted right-panel focus box parameters closer to Python render values
- corrected inventory row focus left-edge alignment

### Display / refresh execution

- added partial rect preparation helpers to align hinted dirty rects for panel partial updates
- changed hinted updates to prefer a merged transition rect instead of many sequential partial updates

## Failed experiment

One regression was introduced and then reverted:

- partial `0x13` payload polarity was changed to non-inverted data
- result: visibly broken partial refresh output across multiple focus boxes
- conclusion: that change was wrong for the current ESP32 driver path and was reverted

Files involved:

- `/Users/yongboyu/Desktop/intelli-spark-e-paper-board/firmware/main/platform/display.cpp`

## Current conclusion

As of this log:

- the system is still not product-correct
- the dominant remaining bug is in the C++ partial refresh execution path, not Python logic and not board wiring
- hardware/LUT behavior can amplify residual artifacts, but it is not the primary explanation for “first rotate shows no box”

## Next debugging target

Continue only on:

- `/Users/yongboyu/Desktop/intelli-spark-e-paper-board/firmware/main/platform/display.cpp`

Specific next target:

- make first focus transition render deterministically on the first partial refresh
- keep the fix aligned with Python dirty-rect intent and Waveshare partial command sequence

## Additional notes from later testing

- Right-panel visual misalignment is more obvious in `INVENTORY` than in `REMINDERS`.
- This suggests two active bug classes still overlap:
  1. `display.cpp` partial refresh execution bug causing first-focus failures
  2. `home_screen.cpp` inventory content inset/box alignment bug causing visible text/badge crowding

Latest follow-up change:

- tightened inventory internal content inset so title text and right badge sit farther inside the focus box:
  - `/Users/yongboyu/Desktop/intelli-spark-e-paper-board/firmware/main/ui/screens/home_screen.cpp`

This change is expected to improve box-content alignment only.
It is not expected to fully solve the first-rotate/no-box failure, which still points at the partial refresh execution path.

## 2026-03-28 late follow-up

Observed after the inventory inset change:

- user reported no meaningful behavioral change
- inventory text/badge inset is therefore not the primary cause of:
  - first rotate showing no focus box
  - half-rendered focus boxes
  - initial focus instability

Latest display-layer change:

- in `/Users/yongboyu/Desktop/intelli-spark-e-paper-board/firmware/main/platform/display.cpp`, the hinted partial path now appends the actual framebuffer diff bbox to the provided `dirty_hints` before partial rect preparation
- intent: make first-transition partial refresh cover the real changed pixels, not only the heuristic Home focus rects

Why this change was made:

- current Home hint generation can still underspecify the real changed area during the first transition
- when that happens, the panel updates only part of the box or skips the visible box entirely
- appending the actual diff bbox keeps the update local while reducing the chance of missing changed pixels

Status:

- firmware build passed after this display-layer change
- user still flashes manually; no flash was performed from this session

## 2026-03-29 right-panel alignment follow-up

After direct comparison against Python `home_kitchen.py`, the C++ right-panel render was still not using the same focus and content parameters.

Concrete mismatch found:

- Python uses:
  - `b_right_focus_pad_y = 4`
  - `b_right_focus_right_trim = 0`
  - inventory title text starts at `inner_x0`
  - badge right edge anchors at `inner_x1`
- C++ was still using:
  - `row_focus_pad_y = 3`
  - `row_focus_right_trim = 2`
  - inventory text inset from `x0 + 8`
  - badge inset from `x1 - 8`

Change made:

- `/Users/yongboyu/Desktop/intelli-spark-e-paper-board/firmware/main/ui/screens/home_screen.cpp`
  - changed right-panel focus params toward Python values
  - moved inventory title/badge anchoring back to the row's true inner bounds

Expected effect:

- reduce the visible mismatch where inventory text/badge appears too close to or beyond the focus box boundary
- does not by itself explain the first-rotate/no-box bug, which still points mainly at `display.cpp`

## 2026-03-29 vertical text alignment follow-up

User report after the last right-panel inset change:

- visible behavior was still unchanged
- inventory row text (for example `Eggs`) still looked vertically misaligned relative to the focus box

Concrete code cause found:

- C++ row text and badge vertical placement were still using hard-coded nominal heights (`18` and `13`)
- but `draw_text_with_font(...)` renders glyphs using each glyph's actual `top` offset
- result: row text could visually sit too high or too low relative to the box even if x alignment looked correct

Change made:

- `/Users/yongboyu/Desktop/intelli-spark-e-paper-board/firmware/main/ui/screens/home_screen.cpp`
  - added glyph-bbox-based vertical centering helpers
  - inventory item text now centers using actual font bounds
  - inventory badge text now centers using actual font bounds
  - reminder row text now centers using actual font bounds

Expected effect:

- reduce the visible case where inventory text appears to drop outside the focus box
- improve vertical consistency between inventory and reminder rows

## 2026-03-29 inventory text anchor follow-up

After re-reading Python and comparing against the current screenshot, the more likely mismatch is that the focus box itself is roughly in the right place but inventory/reminder text anchoring still is not.

Concrete parity gap:

- Python inventory/reminder row text is vertically centered using a stable sample text height (`"Ag"`), not per-string glyph bounds
- C++ had been centering row text using the actual rendered string bounds
- this can still shift words like `Eggs` relative to the box, even if the box geometry itself is close

Change made:

- `/Users/yongboyu/Desktop/intelli-spark-e-paper-board/firmware/main/ui/screens/home_screen.cpp`
  - inventory row text now uses sample-based vertical centering (`Ag`)
  - reminder row text now uses sample-based vertical centering (`Ag`)
  - badge centering remains glyph-bound based for now

Reason:

- this matches Python's row text anchoring more closely than per-string centering
- it should reduce the case where item text appears to float high and clip against the box stroke

## 2026-03-29 row-origin mismatch fix

A concrete geometry bug was identified in `home_screen.cpp`.

Root cause:

- the right-panel rows were being drawn from one set of y origins
- but Home focus boxes and dirty rects were being computed from a different set of y origins
- specifically, inventory row drawing started at `top_y + 4 + 34`, while the focus/dirty metrics used `oy0 + max(8, right_pad - 6) + 34`
- this produced a 12px vertical mismatch before any partial-refresh effects, which explains cases like `Eggs` visually sitting outside the focus box

Change made:

- `/Users/yongboyu/Desktop/intelli-spark-e-paper-board/firmware/main/ui/screens/home_screen.cpp`
  - introduced shared constants for right-panel section offsets
  - aligned `metrics.inv_y` / `metrics.inv_row_y` with the actual inventory render path
  - aligned reminder row origin calculation with the actual reminder render path
  - updated render calls to use the same section offset constants

Expected effect:

- inventory and reminder focus boxes should now be computed from the same row origins used by the renderer itself
- this targets the visible text/box mismatch directly, before touching display partial execution again

## 2026-03-29 Python refresh intent follow-up

Updated baseline from user feedback:

- text/focus-box content mismatch is no longer the main issue
- remaining primary issue is focus transition behavior on first rotate / stale old focus / freeze-like partial refresh behavior

Concrete C++ deviation found:

- Python `refresh_policy.py` preserves separate rect intent for left<->row transitions (`prev_focus_rect`, `curr_focus_rect`)
- C++ `display.cpp` was still taking any prepared multi-rect hinted update and forcibly merging it into one big transition rect before partial refresh
- this destroys the original refresh intent and can leave the old focus uncleared or the new focus under-updated

Change made:

- `/Users/yongboyu/Desktop/intelli-spark-e-paper-board/firmware/main/platform/display.cpp`
  - removed the unconditional multi-rect merge in the hinted partial path
  - prepared hinted rects now execute as prepared, instead of being collapsed into a single rect

Reason:

- this is closer to Python's refresh behavior for Home focus transitions
- especially relevant for row<->left-panel transitions and first-focus updates

## 2026-03-29 conditional diff fallback

Further Python parity check found another display-layer mismatch.

Python behavior:

- in `tools/run_epaper_console.py`, `diff_box` is not always appended to structural dirty rects
- it is only used as a fallback when the inferred structural dirty regions do not already cover the actual diff bbox

C++ behavior before this change:

- `/Users/yongboyu/Desktop/intelli-spark-e-paper-board/firmware/main/platform/display.cpp`
  - always appended `diff_rect` to `dirty_hints`
- this can inflate a simple focus move into extra/larger partial updates and matches the user's reported freeze-like behavior after focus moves

Change made:

- `/Users/yongboyu/Desktop/intelli-spark-e-paper-board/firmware/main/platform/display.cpp`
  - `diff_rect` is now appended only when:
    - there are no structural hints, or
    - the merged structural hints do not already contain the actual diff bbox (with small slack)

Expected effect:

- keep Home focus transitions closer to Python refresh intent
- reduce unnecessary extra partial windows that can stall UX feedback on first rotate

## 2026-03-30 UX recovery rollback

User feedback after preserving separate hinted rect execution:

- UX regressed badly versus the previous build
- board behavior felt freeze-like
- `a/d/c` no longer gave timely visible feedback during focus moves

Interpretation:

- preserving Python's multi-rect dirty intent literally in ESP32 caused multiple blocking partial refreshes per single interaction
- each partial refresh waits for panel busy/idle, so one focus move could stall behind several serial partial updates
- this is a device-side execution problem, not a change in product semantics

Change made:

- `/Users/yongboyu/Desktop/intelli-spark-e-paper-board/firmware/main/platform/display.cpp`
  - restored single merged transition-rect execution for multi-rect hinted updates
  - keeps the conditional diff fallback logic from the previous step

Why:

- priority is to recover usable interaction feedback first
- Python remains the source of truth for which regions are dirty
- ESP32 execution is allowed to collapse those rects into one partial update when needed for acceptable UX

## 2026-03-30 deferred home-focus render

Python parity check for UX freeze found a higher-level runtime gap.

Python behavior:

- Home focus moves are staged through `RefreshPolicyRuntime`
- focus-only updates can collapse queued intermediates to the latest target state
- refresh execution is throttled by `min_refresh_gap_ms`

C++ behavior before this change:

- every `Rotate` dispatched on Home rendered immediately in the same synchronous path
- that path blocks on panel refresh completion
- result: repeated `a/d` input felt freeze-like because input handling and refresh execution were coupled tightly

Change made:

- `/Users/yongboyu/Desktop/intelli-spark-e-paper-board/firmware/main/app/runtime.hpp`
- `/Users/yongboyu/Desktop/intelli-spark-e-paper-board/firmware/main/app/runtime.cpp`
- `/Users/yongboyu/Desktop/intelli-spark-e-paper-board/firmware/main/main.cpp`

Details:

- Home `Rotate` events are now deferred instead of rendering immediately
- deferred Home focus renders collapse to the latest target state before flushing
- flush runs from the main loop with a 120ms minimum render gap, matching Python's balanced-mode rhythm more closely
- non-Home or non-rotate state changes still render immediately

Intent:

- recover visible UX feedback for focus moves
- stop blocking the main loop on every intermediate Home rotate
- move C++ closer to Python's staged refresh runtime instead of direct synchronous redraw on every encoder step

## 2026-03-30 checkpoint wrap-up

Current checkpoint assessment:

- Home visual/layout migration is mostly present in C++
- Home interaction quality is not close to done
- partial-refresh execution and focus-feedback UX remain the main blocker
- current work should be treated as a checkpoint, not as a completed Home migration

Source-of-truth clarification:

- Python remains the source of truth not only for static UI layout
- Python also remains the source of truth for:
  - focus rules
  - rotate/click/tick behavior
  - dirty-rect intent
  - refresh-policy reasoning
  - UX expectations during interactive navigation
- ESP32/C++ may adapt only panel-driver execution details that Python does not directly encode
- if firmware behavior diverges from Python without a strict driver requirement, treat that divergence as a bug

Practical handoff note:

- current interactive blocker is still centered in `firmware/main/platform/display.cpp`
- visual/layout work in `firmware/main/ui/screens/home_screen.cpp` is substantially farther along than the interaction path
- future work should resume from this checkpoint instead of continuing to improvise a second behavior model
