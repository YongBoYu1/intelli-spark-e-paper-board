# Settings V1

## Purpose
This document defines the V1 Settings page for the e-paper board prototype.

Goals:
- Keep the page easy to scan on 1-bit e-ink.
- Keep updates stable (no layout jitter when state messages change).
- Keep interactions simple and rotary-friendly.

## Information Architecture

### Display
- `Font Size`: `Small` / `Medium` / `Large`
- `Partial Refresh`: `Slow` / `Balanced` / `Fast`
- `Full Refresh`: `Every 10` / `15` / `20` partials
- `Rotation`: `0` / `180`
- `WiFi + BT`: one combined connectivity row for V1

### Sync
- `Auto Sync`: `On` / `Off`
- `Sync Now`: action row

### Other
- `Reset / Web Data`: delete local device/dashboard data and return to first-boot flow

## Layout Rules

1. Text-first rows
- Rows are rendered as text lines (no heavy per-row container boxes).
- Focus is indicated by a lightweight marker and underline.

2. Typography hierarchy
- Left label text is larger.
- Right value text is smaller.
- Fonts use the shared panel tokens from `panel_font_template`:
  - `panel_font_body_key`
  - `panel_font_body_focus_key`
  - `panel_font_body_size`
  - `panel_font_meta_key`
  - `panel_font_meta_size`
  - `panel_font_meta_spacing`
  - `panel_font_meta_compact`

3. Fixed footer region
- Footer height is reserved at all times.
- Footer left: transient status text (for example `FAKE SYNC COMPLETE`).
- Footer right: `LAST SYNC ...` timestamp.
- Main list area must not move when footer text changes.

## Interaction Rules

- Rotate: move focus to previous/next selectable row.
- Rotate Button (global): toggle screen orientation `0 <-> 180` from any screen.
- Click on selected row:
  - `Font Size`: cycle `Small -> Medium -> Large`
  - `Partial Refresh`: cycle `Slow -> Balanced -> Fast`
  - `Full Refresh`: cycle `10 -> 15 -> 20`
  - `Rotation`: toggle `0 <-> 180`
  - `WiFi + BT`: toggle combined state for both switches
  - `Auto Sync`: toggle on/off
  - `Sync Now`: fake success, updates `last_sync_at`
  - `Reset / Web Data`: open confirm dialog, then delete local data and return to first boot

## Current Implementation Status

Implemented files:
- `app/core/state.py`
- `app/core/settings_schema.py`
- `app/core/reducer.py`
- `app/ui/settings.py`
- `app/ui/app.py`
- `tools/run_epaper_console.py`

Not implemented in V1:
- Real backend sync pipeline
- Dedicated WiFi/Bluetooth pairing/configuration flow

## Branch and Tracking

- Working branch: `codex/settings-v1-page-structure`
- GitHub issue: `#17`  
  https://github.com/YongBoYu1/intelli-spark-e-paper-board/issues/17
- Issue draft source: `docs/issues/2026-02-25-settings-v1-page-structure.md`

## How to publish the issue (requires auth)

If GitHub auth is available locally, create the issue by copying the draft body into your GitHub issue form.

API creation requires token auth. Example (replace token):

```bash
curl -X POST \
  -H "Authorization: Bearer <GITHUB_TOKEN>" \
  -H "Accept: application/vnd.github+json" \
  https://api.github.com/repos/YongBoYu1/intelli-spark-e-paper-board/issues \
  -d @issue_payload.json
```
