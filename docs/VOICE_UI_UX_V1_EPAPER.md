# Voice UI/UX v1 (E-Paper, Hardware-Aware)

## What Changed

- Replaced large centered overlay with a fixed left-bottom `Mic/Voice Zone`.
- Kept the voice area single-line, bounded, and geometry-stable.
- Updated copy to a conversational sequence (less industrial status wording).
- Added state-aware mic icon behavior tuned for 1-bit readability.

## Voice Zone Pattern

- Position: fixed left-bottom lane.
- Height: single line (`voice_zone_lane_h`).
- Width: bounded (`voice_zone_width`).
- Text: one short sentence only (no multi-line expansion).
- Goal: stable region for future dirty-region/partial-refresh routing.

## Copy Flow (Current)

- `READY` -> `Hold to talk`
- `LISTENING` -> `Go ahead...`
- `PROCESSING` -> `Heard: <short>`
- `CONFIRM` -> `<action>? Enter`
- `DONE` -> short result (for example `Added Milk`)
- `SKIPPED` -> `No change`
- `ERROR` -> `Didn't catch that`

Design intent:

- Keep flow conversational and continuous (not a state-machine broadcast).
- Preserve user confidence via short transcript preview + clear outcome.
- Keep destructive confirmation explicit without modal interruption.

## Mic Icon Strategy

- Default mode: `voice_zone_mic_mode = tabler_state`
  - `READY / DONE` -> `tabler_outline`
  - `LISTENING` -> `tabler_filled`
  - `PROCESSING / CONFIRM` -> `tabler_half`
- Manual mode remains available (`voice_zone_mic_mode = manual`) via `voice_zone_mic_style`.

Available icon families in simulator gallery:

- `heroicons_solid`
- `heroicons_outline`
- `tabler_outline`
- `tabler_half`
- `tabler_filled`
- `bootstrap_outline`
- `bootstrap_fill`

Sources and licenses:

- `assets/icons/heroicons/*`
- `assets/icons/tabler/*`
- `assets/icons/bootstrap/*`
- `assets/icons/lucide/*`

## Confirm UX (Destructive Actions)

- Confirm is displayed in the fixed voice zone (no full-screen blocking popup).
- Confirm text follows product copy style: `<action>? Enter`.
- Confirm stays visible for the full pending-confirm window.
- Simulator hold duration is extended to cover pending confirm timeout.

## E-Paper Refresh Strategy (v1)

Current implementation:

- Voice zone is layout-ready for bounded refresh.
- Board path still uses full-screen refresh for reliability:
  - `tools/run_epaper_console.py` -> `display_image(...)`

Why v1 still full-screen:

- Lower risk and simpler failure modes for current hardware path.
- Prevent partial-refresh artifact regressions while UX is stabilizing.

Planned direction:

- Hybrid strategy: partial for small stable regions (voice lane/focus cues), full refresh for page-scale changes and periodic ghost cleanup.

## Simulator + Board Compatibility

- Shared renderer: `app/ui/app.py` (`render_app` and voice lane drawing).
- Simulator path: `tools/sim_app_tk.py`.
- Board path: `tools/run_epaper_console.py`.

Both paths consume `state.ui.voice_*`, so behavior is MCU-migratable at the state-contract level.
