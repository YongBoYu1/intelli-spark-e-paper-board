# Issue 51 Freeze + Issue 52 Kickoff Plan (2026-03-26)

## Decision

Issue `#51` remains **OPEN** but is moved to **PAUSED (display-quality blocker)**.

This is not a cancellation of `#51`. It is a controlled pause so product migration work can continue in `#52` while display waveform work proceeds separately.

## Why Pause `#51` Instead of Closing It

`#51` runtime structure and boot flow are in place, but current on-device visual quality is still below acceptable product level:

- During a single `0x12` refresh, panel reaches a correct high-contrast image mid-cycle.
- In settle phase, the same image is washed to gray, often with vertical banding.
- Multiple `DTM1` strategies, init modes, and clear strategies were tested with the same final outcome.

Reference: `firmware/docs/display_experiments.md` (Experiments #12 to #18a).

## What The Experiments Actually Established

The pause is based on evidence, not on a vague "display still looks bad" judgment.

What is already strongly established from the experiments:

- Hardware path is fundamentally alive.
  - Arduino raw full-black test produced deep black (`Experiment #0`).
- Transport/SPI speed is not the main blocker.
  - 2MHz vs 4MHz did not materially change the final settled result (`Experiment #5`).
- OTP-mode VCOM override is not giving leverage.
  - `0x82` sweep had no visible effect in OTP mode (`Experiment #6`).
- The framebuffer content is at least temporarily correct.
  - Mid-refresh photos show the intended UI with strong black/white separation (`Experiments #12` to `#18a`).
- The blocker is the final settled state after full refresh.
  - Across multiple first-frame variants, final settle still washes to gray (`Experiments #14` to `#18a`).

This means the current blocker is best understood as:

- `#51` blocker = full-refresh settle / LUT-quality problem
- not a boot-flow problem
- not a basic transport problem
- not simply a "wrong single `DTM1` value" problem

## Scope Status Snapshot

### Completed in `#51`

- ESP32 C++ runtime skeleton exists (`app/`, `ui/`, `platform/`, thin `main.cpp`).
- **Code structure refactored**: `display.cpp` split from 2001-line monolith into 7 focused files:
  - `platform/display.cpp` — SPI driver + panel hardware only (~500 lines)
  - `platform/panel_config.hpp` — shared panel constants (800×480)
  - `ui/draw.hpp` + `ui/draw.cpp` — drawing primitives + font engine
  - `ui/screens/landing_screen.cpp` — Landing page renderer
  - `ui/screens/onboarding_screen.cpp` — Onboarding 4-step renderer
  - `ui/screens/home_screen.cpp` — Home page renderer
  - `ui/render_app.cpp` — screen router
- Boot uses built-in defaults and reaches visible UI.
- Basic interaction loop is running on ESP32 (serial: a/d=rotate, c=click).
- Display driver path is integrated and testable.
- **Glyph baseline bug fixed**: `draw_glyph()` corrected from `y + ascent + top` to `y + top` (Exp #9).
- **Partial refresh mode implemented**: `enter_partial_mode()` sends 0xE0/0xE5 matching Python's `init_part()` (Exp #3). No more severe corruption or tearing on interaction; remaining light ghosting is acceptable for V0.
- **Pixel convention aligned to Python**: 0=black, 1=white in framebuffer (matching `getbuffer()` convention).
- **18 display experiments documented** with reproducibility notes in `firmware/docs/display_experiments.md`.

### Not complete for `#51` closure

- Final settled e-paper contrast quality is not acceptable.
- OTP LUT settle behavior remains unresolved.
- C++ landing renderer is still a hand-written approximation, not a direct port of Python's `app/ui/onboarding.py::render_landing()`. (This is `#52` scope, not a `#51` blocker.)

### Current code state at freeze

| Setting | Value | Notes |
|---------|-------|-------|
| Pixel convention | 0=black, 1=white | Matches Python `getbuffer()` |
| Init sequence | Python standard `init()` | 0x06→0x01→0x04→0x00(0x1F)→0x61→0x15→0x50→0x60 |
| SPI clock | 4 MHz | Matches Python RPi driver |
| First frame | Clear-to-white + DTM1=previous(0xFF) | Current freeze uses Exp #18a strategy; Exp #15 (`DTM1=~image`) and Exp #16 (clear-to-black + `DTM1=0x00`) were also tested and settled to the same washed final state |
| Panel Setting (0x00) | 0x1F (OTP LUT mode) | No custom LUT loaded |
| kUseInvertedFirstFrame | true | Fallback path, not used when previous_frame_valid_ |
| Partial refresh | init_part() with 0xE0/0xE5 | Functional, no severe artifacts |

## Freeze Baseline Rules

Before branching to `#52`, create one explicit freeze checkpoint commit:

1. Include docs updates only (no new display logic experiments in same commit).
2. Record known blocker and current experimental conclusion.
3. Treat this commit as the shared base for both `#52` and continued LUT work.

Additional freeze requirements:

4. Freeze from a **clean working tree** only.
   - Do not create the freeze baseline from a dirty `display.cpp` experiment state.
5. Preserve the current experimental conclusion in docs even if the working tree is reset before freeze.
6. If needed, keep the latest LUT experiment commit reachable by branch history, but do not mix it into the docs-only freeze checkpoint.

Recommended practical interpretation:

- latest experiment conclusion commit: `bc70faf` (`exp/18a: Clean LUT test confirms OTP waveform settle is root cause`)
- freeze checkpoint: a new docs-only commit on top of a clean tree

## Branch Strategy After Freeze

Use one common base commit for both tracks:

- `codex/51-pause-base` (frozen checkpoint)
- `codex/52-runtime-migration` (feature migration work)
- `codex/51-lut-fix` (display waveform/LUT experiments)

Merge policy:

- Allow merges from `codex/51-lut-fix` -> `codex/52-runtime-migration` only when testing integration.
- Do not block `#52` functional progress on unresolved LUT quality.
- Keep LUT experiment commits isolated from unrelated feature commits.

## `#52` Kickoff Boundaries

Start `#52` immediately from freeze base with this rule:

- Functional behavior migration is in scope.
- Display final contrast quality is tracked separately by paused `#51`.

`#52` should explicitly avoid treating the following as in-scope product work:

- LUT experiments
- first-frame waveform experiments
- `display.cpp` settle-quality tuning
- "temporary acceptable screenshots" as a substitute for behavior parity

In other words:

- `#52` = migrate product behavior/state/rendering structure
- paused `#51` = recover final settled display quality

`#52` can be validated with:

- state/reducer correctness
- navigation and screen reachability
- event/action behavior parity
- renderer parity at the logical/layout level, even if final panel settle quality is still blocked

`#52` should not be blocked by current OTP settle quality unless it prevents functional verification.

Suggested engineering rule for `#52`:

- avoid changing `firmware/main/platform/display.cpp` except for integration-safe compile fixes
- keep behavior/render migration in `app/`, `ui/`, and related product-level code
- any new display waveform experiment should stay on the separate `#51` LUT branch

## Unresolved Hypotheses for `#51` LUT Track

When resuming `#51`, these directions remain untested:

1. **External LUT mode** (0x00=0x3F) — bypass OTP entirely, provide custom waveform tables with controlled settle phase. High effort but full control.
2. **RPi cross-validation** — run Python driver on RPi with the same physical panel. If Python still works, use logic analyzer to compare SPI waveforms between RPi and ESP32.
3. **Panel Setting register bits** — 0x1F may select a specific LUT bank. Other values (0x0F, 0x1B, etc.) might select different waveform behavior.
4. **Reset timing** — C++ uses 200ms HIGH/2ms LOW/200ms HIGH; Python uses 20ms/2ms/20ms. Not yet tested.
5. **Power supply differences** — RPi HAT has dedicated e-paper power circuitry; ESP32 DevKit uses GPIO-controlled power enable. May affect waveform execution voltage stability.
6. **Pixel convention cross-validation** — current firmware uses 0=black, matching Python `getbuffer()`, but Exp #0 (Arduino full-black test with DTM2=0xFF -> deep black) suggests the panel may also expose a native 1=black path. Neither convention has produced a deep-black final settled state yet, but cross-validation may still reveal OTP LUT polarity preference.

## Re-open Criteria for Active `#51` Completion

Move `#51` from PAUSED -> ACTIVE only when LUT track is resumed, and close only when:

1. Final settled frame does not wash to gray after full refresh.
2. Vertical banding is removed or reduced to acceptable product threshold.
3. Result is repeatable across at least 3 cold boots and 3 refresh cycles.
4. No major regression in interaction rendering path.

Secondary closure criterion:

5. The fix must be reproducible from committed code plus saved logs/photos, not only from an uncommitted working tree state.

## Suggested GitHub Issue Update Notes

For `#51`:

- Add status note: `OPEN + PAUSED (display-quality blocker)`.
- Link `firmware/docs/display_experiments.md`.
- Link this freeze plan doc.

For `#52`:

- Add kickoff note: starts from `codex/51-pause-base`.
- Clarify that display-LUT quality is tracked by `#51` and is not a blocker for behavior migration tasks.
- Clarify that `#52` must not absorb ad-hoc LUT experiments or panel-state hacks.
- Link `docs/issues/2026-03-26-issue-52-assignee-context.md`.

For `#53`:

- Clarify that it follows the `#52` behavior migration track, not the paused `#51` experiment head.
- Clarify that it owns runtime integration, persistence, refresh-policy integration, and service clients.
- Clarify that LUT recovery remains on the separate `#51` track unless explicitly reassigned.
- Link `docs/issues/2026-03-26-issue-53-assignee-context.md`.
