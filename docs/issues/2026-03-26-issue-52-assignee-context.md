# Issue 52 Assignee Context (2026-03-26)

## What `#52` Is Actually Starting From

Issue `#52` does not start from a blank firmware project.

Current C++ runtime already has:

- a working ESP32 boot path
- built-in defaults
- a reducer-driven runtime loop
- visible rendering on device
- basic serial interaction (`a` / `d` / `c`)

Current C++ runtime only covers:

- `Landing`
- `Onboarding`
- `Home`

Current C++ runtime does **not** yet cover:

- `Menu`
- `Timer`
- `Calendar`
- `Weather`
- `Inventory / Reminders`
- `Settings`
- major Python-owned product actions beyond the current demo onboarding flow

## Current C++ Source Snapshot

Important current files:

- `firmware/main/app/state.hpp`
- `firmware/main/app/reducer.cpp`
- `firmware/main/app/runtime.cpp`
- `firmware/main/ui/render_app.cpp`
- `firmware/main/ui/screens/landing_screen.cpp`
- `firmware/main/ui/screens/onboarding_screen.cpp`
- `firmware/main/ui/screens/home_screen.cpp`

Important current limitations:

- `Screen` enum only has `Landing`, `Onboarding`, `Home`.
- `AppState` is still a V0 subset, not the major product state model.
- `reducer.cpp` currently implements only the minimal landing/onboarding/home flow.
- `render_app.cpp` only routes those three screens.

## What `#52` Owns

`#52` is the behavior migration issue.

It should make C++ the main device-side source of truth for:

- screen navigation
- local state transitions
- local product actions
- major screen reachability

It should not try to solve:

- LUT / waveform / settle quality
- refresh waveform experiments
- backend service integration
- final persistence/integration plumbing

Those belong to paused `#51` and later `#53`.

## Guardrails For Assignees

During `#52`, prefer changing:

- `firmware/main/app/*`
- `firmware/main/ui/*`

Avoid changing:

- `firmware/main/platform/display.cpp`
- `firmware/main/ui/draw.cpp` pixel convention (`0=black`, `1=white`)

Exception:

- compile/integration-safe fixes are fine
- new LUT, panel-state, or waveform experiments are not
- if LUT work later needs a pixel-convention reversal, that change belongs to paused `#51`, not to `#52`

## Python Source Of Truth For `#52`

Primary behavior references:

- `app/core/state.py`
- `app/core/reducer.py`
- `app/core/settings_schema.py`
- `app/voice/actions.py`
- `app/ui/app.py`
- `app/ui/home_kitchen.py`
- `app/ui/onboarding.py`
- `app/ui/menu.py`
- `app/ui/timer.py`
- `app/ui/calendar.py`
- `app/ui/weather_detail.py`
- `app/ui/list_unified.py`
- `app/ui/settings.py`

This source-of-truth rule applies to more than static UI structure.

For `#52`, Python owns:

- screen layout and visual hierarchy
- focus order and focus visibility rules
- rotate / click / tick interaction semantics
- Home dirty-rect intent and refresh-policy reasoning
- UX behavior expectations during interactive navigation

ESP32/C++ is allowed to adapt only the final driver-side execution details that Python does not express directly
(for example: SPI writes, panel window commands, byte alignment, or panel busy waits).
It is not allowed to invent a second product behavior model.

If C++ behavior diverges from Python and the divergence is not strictly required by the panel driver,
that divergence should be treated as a bug, not as a design choice.

Important product docs to read before large changes:

- `docs/SETTINGS_V1.md`
- `docs/VOICE_INTERACTION_CONTRACT.md`
- `docs/VOICE_UI_UX_V1_EPAPER.md`

## Recommended Work Order

### Phase 1: Expand the state model

Add the missing screen/state types in C++ first.

Target outcome:

- `Screen` enum covers the major product screens
- `AppState` can represent those screens without Python-owned runtime state

### Phase 2: Port navigation and reducer semantics

Port behavior before chasing visual parity.

Target outcome:

- main screen transitions work in C++
- rotate/click/tick semantics no longer depend on Python logic
- product actions mutate C++ state directly

### Phase 3: Make all major screens reachable

Reachability matters before polish.

Target outcome:

- `Menu`, `Timer`, `Calendar`, `Weather`, `Inventory / Reminders`, and `Settings` are all reachable
- placeholder rendering is acceptable if behavior contract is correct

### Phase 4: Improve renderer parity

Only after behavior is in place:

- port layout rules
- port per-screen visual structure
- reduce the gap between Python renderer and C++ renderer
- use Python `app/ui/onboarding.py::landing_layout_metrics()` as the landing-page layout baseline instead of preserving the current hand-written approximation in `landing_screen.cpp`
- treat Python refresh/interaction behavior as part of parity, not just the static pixels

## Current checkpoint

As of the current checkpoint:

- Home visual structure is mostly migrated into C++
- Home interaction and partial-refresh UX are not close to done
- the main remaining blocker is the firmware display execution path in `firmware/main/platform/display.cpp`
- current work should be described as `Home visual migration mostly present; Home interactive refresh path still unstable`

## Suggested First Slice For Assignment

If `#52` is assigned to someone without prior context, the safest first deliverable is:

1. expand `Screen` + `AppState`
2. add placeholder C++ routes/renderers for all major screens
3. port reducer navigation so every major screen is reachable on device

This is the lowest-risk entry point because it avoids mixing:

- display-driver work
- backend integration
- fine-grained visual parity

## First Implementation Checklist

Use this as the first concrete `#52` task list.

### State model

- add major screen values to `firmware/main/app/state.hpp`
- add minimal sub-state structs for `Menu`, `Timer`, `Calendar`, `Weather`, `Inventory / Reminders`, and `Settings`
- keep the new state minimal; do not block on full feature parity
- update `screen_name(...)` and any related helpers in `firmware/main/app/state.cpp`

### Routing and rendering

- add placeholder renderers for the major new screens under `firmware/main/ui/screens/`
- keep placeholder pages simple and stable for e-paper validation
- extend `firmware/main/ui/render_app.cpp` so every new screen has a renderer path

### Reducer and navigation

- extend `firmware/main/app/reducer.cpp` so `Home` can open a `Menu`
- make `Menu` the navigation hub to `Timer`, `Calendar`, `Weather`, `Inventory / Reminders`, and `Settings`
- add a minimal return path so the user can navigate back without needing Python
- keep input semantics rotary-friendly and reducer-owned

### Validation

- build firmware successfully
- flash to ESP32
- confirm boot still works
- confirm each major screen is reachable on device
- confirm rotate/click transitions match the intended screen graph

### Non-goals for this first slice

- do not port final per-screen business logic yet
- do not chase pixel-perfect parity
- do not modify `firmware/main/platform/display.cpp` except compile-safe integration fixes
- do not mix LUT experiments into this task

### Done means

This first slice is done when:

1. the major screen enum and state scaffolding exist in C++
2. all major screens are reachable from the device runtime
3. placeholder rendering works for those screens
4. the task leaves display-driver waveform work untouched

## Validation Standard For `#52`

Because `#51` is paused on display settle quality, `#52` should be validated primarily by behavior:

- firmware builds and flashes
- device boots into runtime state on ESP32
- major screens are reachable
- reducer transitions are correct
- user input changes the expected state and screen

Display quality may still be imperfect during validation as long as the behavior is observable.

## Recommended GitHub Issue Notes

If you assign `#52`, include these clarifications:

- starts from `codex/51-pause-base`
- does not own LUT recovery
- should not turn into a `display.cpp` experiment branch
- should prioritize behavior migration over pixel-perfect parity

## Related Docs

- `docs/issues/2026-03-26-issue-51-freeze-and-issue-52-kickoff.md`
- `firmware/docs/display_experiments.md`
