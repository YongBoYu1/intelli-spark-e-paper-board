# Issue 51/52/53 Closeout Plan (2026-04-05)

## Decision Baseline

- Python is the behavior spec.
- Python simulator/host tooling is not the runtime architecture spec.
- `#52` closes only when product behavior on device is stable and explainable.
- Execution order: finish landscape first, then portrait.

## Current Track

- Single active branch: `codex/52-runtime-migration`
- `#51` and `#52` are functionally on one code line now; no parallel branch workflow is required.

## How To Close `#51`

`#51` scope is runtime V0 foundation, not full product parity.  
Close `#51` when this checklist is true:

1. ESP32 boots into visible runtime UI from firmware defaults.
2. Runtime is reducer/state driven in C++ (not static single image path).
3. Main app loop and screen routing exist in `firmware/main/app` + `firmware/main/ui`.
4. Product can proceed on top of this base without reopening architecture scaffolding.

If all 4 are true, close `#51` and explicitly move remaining parity/polish to `#52`.

## How To Close `#52`

`#52` is behavior migration + product parity stabilization.

### Stage A (Landscape closeout first)

1. Home landscape parity:
   - focus flow
   - right-list behavior
   - family board typography/layout
   - no non-expected full refresh on normal navigation
2. Timer landscape parity:
   - `05:00` typography hierarchy and layout
   - control focus/rotate/click semantics
3. Menu/List/Settings/Calendar/Memo landscape parity:
   - focus behavior
   - typography and spacing close to Python behavior contract
4. Refresh parity in landscape:
   - dirty reasons / rects / mode logs complete
   - no obvious ghost blocks or persistent residue under normal usage

### Stage B (Portrait closeout)

1. Rotation pipeline parity:
   - behavior matches Python rotation model
   - not just state value changes; rendered product behavior must change correctly
2. Home portrait parity
3. Timer portrait parity
4. Remaining pages portrait parity (memo/list/settings/calendar)
5. Portrait refresh regression pass

### `#52` final close gate

Close `#52` only when:

1. Landscape and portrait both pass core user journeys.
2. No recurring unexpected full-refresh during normal navigation.
3. Refresh decision logs are sufficient to explain each refresh action.
4. Major product behavior is C++ source-of-truth and no longer depends on Python runtime execution.

## `#53` Status and Start Rule

- `#53` stays open but blocked until `#52` passes both Stage A and Stage B.
- Start `#53` only after `#52` close gate is met.
- `#53` then focuses on runtime integration completeness (persistence/service/runtime-host responsibilities), not UI parity cleanup.

## Working Split (Codex + Device Validation)

- Codex:
  - implement parity patches in small commits
  - keep refresh logs and behavior mapping explicit
  - produce per-stage diff summary + residual risk list
- Product/device owner:
  - run board validation after each stage
  - decide pass/fail from product behavior
  - provide photos/log snippets for mismatches

