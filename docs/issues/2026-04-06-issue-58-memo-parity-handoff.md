# Issue #58 Handoff — Memo Python 1:1 Parity (Strict, No Invention)

## Issue Linkage
- Umbrella: #52 (**OPEN**, not complete)
- Execution slice: #58 (**Memo + Home Family Board linkage only**)
- Goal: Memo related behavior and UI must be **1:1 aligned** to Python source-of-truth.

## Product Status (Current)
- Memo path is still not at product-ready parity.
- This issue is not for redesign; it is for strict parity migration.

## Hard Constraints
1. Python behavior is hard metric (source-of-truth), no speculative invention.
2. Do not modify `third_party/waveshare_ePaper`.
3. Do not mix unrelated page work into this issue.
4. Keep refresh logs readable: dirty reasons / rects / mode / decision.
5. Keep all work on `codex/52-runtime-migration` unless explicitly changed by user.

## Python Source of Truth (Must Follow)
- `app/ui/memo.py`
- `app/ui/home_kitchen.py` (Family Board section)
- `app/core/reducer.py` (memo index / expand / new-badge interactions)
- `app/render/refresh_policy.py` (memo + home family-board dirty planning)

## C++ Target Files
- `firmware/main/ui/screens/memo_screen.cpp`
- `firmware/main/ui/screens/memo_screen_landscape.cpp`
- `firmware/main/ui/screens/memo_screen_portrait.cpp`
- `firmware/main/ui/screens/home_screen.cpp` (family board rendering + snapshot fields)
- `firmware/main/app/reducer.cpp` (memo interaction semantics)
- `firmware/main/app/runtime.cpp` (refresh decision path, if memo/home linkage requires)

## Required Work (In Order)
1. Build a function-level parity map (`Python -> C++`) for memo path.
2. Align memo screen rendering semantics:
   - row density, selected row style, author/time/new badge placement
   - body text wrap/ellipsis behavior
   - footer and hint text hierarchy
3. Align interaction semantics:
   - rotate selects memo index behavior
   - click toggles expand behavior
   - click clears current memo `NEW` state exactly as Python
4. Align Home Family Board linkage:
   - selected memo content/author/posted-time rendering behavior
   - when memo changes, home family-board data and dirty region update correctly
5. Align refresh behavior:
   - no stale overlay/ghost caused by missing dirty coverage
   - no random full refresh under normal memo interactions

## Validation Scenarios (On Device)
1. Memo rotate 20 steps continuously (forward/backward), verify stable parity.
2. Click selected memo expand/collapse repeatedly, verify deterministic visual updates.
3. `NEW` badge clearing on click, verify no regressions.
4. Home family-board reflects memo state changes correctly (text/author/posted).
5. No residual artifacts after repeated memo/home switching.

## Acceptance Criteria
- Memo page visual hierarchy and interaction behavior match Python.
- Home family-board linkage behavior matches Python.
- Refresh logs explain each memo/home refresh decision.
- User confirms real-device parity before closing #58.

## Out of Scope
- No calendar/weather/list/settings work in this issue.
- No architecture refactor unrelated to memo parity.
- No subjective visual redesign.
