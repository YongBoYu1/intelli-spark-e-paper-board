# Issue Draft: E-Paper Refresh Policy for All Screens (R0-R3 + Dirty Rect)

## Title
Unify e-paper refresh policy across all screens with R0/R1/R2/R3 and page-level dirty-rect mapping

## Summary
Implement a single refresh-policy pipeline for all UI screens, replacing mixed per-screen logic with a reusable state machine based on:
- `R0_NO_REFRESH`
- `R1_PARTIAL_RECT`
- `R2_FAST_FULL_SCREEN`
- `R3_FULL_CLEAN`

The goal is to reduce unnecessary full-screen flashing while keeping ghosting under control and preserving reliability on `epd7in5_V2`.

## Context
Current status:
- `settings` and `timer` already have partial-refresh behavior in `tools/run_epaper_console.py`.
- Other screens (`home`, `menu`, `weather`, `calendar`) still fall back to fast/full refresh.
- Refresh decision logic is embedded in the runner and not reusable.
- `docs/EPD_REFRESH_STRATEGY_PLAYBOOK.md` already defines target strategy and page-level guidance.

## Scope
1. Refresh policy core
- Add `app/render/refresh_policy.py` to host refresh state, thresholds, and decision logic.
- Include `supports_partial`, `partial_count`, `last_refresh_ts`, `last_full_refresh_ts`.
- Implement mode mapping for `slow` / `balanced` / `fast`.

2. Page-level policy coverage
- Cover `Home` (kitchen/classic), `Menu`, `Weather`, `Calendar`, `Settings`, `Timer`.
- Define per-screen event-to-dirty-region mapping.
- Support dirty-rect merge and 8px X alignment for partial refresh.

3. Runtime integration
- Refactor `tools/run_epaper_console.py` to call policy module instead of ad-hoc branching.
- Preserve safe fallback to full refresh on partial failure.
- Keep page-switch and rotation-switch behavior stable.

4. Reliability constraints
- Enforce partial-refresh budget (`full_refresh_every`) and periodic clean refresh.
- Add refresh throttling (`min_refresh_gap_ms`) for high-frequency rotary and tick events.

5. Verification
- Add/extend tests for policy decisions, rect alignment, and fallback behavior.
- Validate key interactions: focus move, timer ticks, settings value changes, screen transitions.

## Acceptance Criteria
- All screens use one refresh-policy pipeline (not screen-specific branching in runner).
- For same-screen small updates, policy chooses `R1` when safe, instead of default full refresh.
- For screen/rotation changes, policy uses stable full-path (`R2` or `R3` per rule).
- Partial rects are always 8px aligned on X and clipped to screen bounds.
- `partial_refresh_mode` and `full_refresh_every` affect real runtime behavior.
- Fallback to full refresh is automatic when partial call fails.
- Tests cover critical policy branches and pass locally.

## Out Of Scope
- Driver replacement or panel model migration.
- New business features unrelated to refresh (UI redesign, backend sync implementation).

## Suggested Labels
- `ui`
- `e-ink`
- `performance`
- `enhancement`
