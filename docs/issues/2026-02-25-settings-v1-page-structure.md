# Issue Draft: Settings V1 - Grouped Structure and E-Ink Safe Rendering

## Title
Settings V1: grouped menu structure + fixed footer to avoid layout jitter on e-ink

## Summary
Implement a V1 Settings page that is readable on 7.5" e-ink, with grouped information architecture and stable rendering behavior. The page must avoid layout jitter and excessive visual churn during updates.

## Context
Current Settings work is focused on:
- Grouped menu sections (`Display`, `Sync`, `Other`)
- Text-first rows (no heavy per-row boxes)
- E-ink-friendly typography via `panel_font_template`
- Stable footer region for transient status messages

## Scope
1. Information architecture
- `Display`: Font Size, Partial Refresh, Full Refresh, Rotation, WiFi+BT
- `Sync`: Auto Sync, Sync Now
- `Other`: Reset / Web Data

2. Interaction model
- Rotate: move focus between rows
- Click: toggle/cycle selected row value
- Back: exit settings

3. E-ink rendering constraints
- Remove heavy row boxes to reduce visual redraw cost
- Keep larger label text and smaller value text
- Reserve a fixed footer area for status text so list layout does not shift

4. Sync behavior (temporary)
- `Sync Now` uses fake success flow (no backend yet)
- Last sync timestamp displayed in footer (not a dedicated selectable row)

## Acceptance Criteria
- Settings list is grouped and follows the above section model.
- Rotation appears under `Display`.
- No dedicated selectable `Last Sync` row.
- Footer region is fixed-height and does not push list content when status text appears.
- Typography uses `panel_font_*` tokens from `panel_font_template`.
- `Reset / Web Data` remains a placeholder action (not implemented).

## Notes
- Backend sync and real reset behavior are explicitly out of scope for this issue.
- WiFi/BT are represented as simple toggles for V1.

## Suggested Labels
- `ui`
- `settings`
- `e-ink`
- `enhancement`
