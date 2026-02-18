# Panel Font Template

To avoid re-tuning e-ink typography for each new UI, use the shared panel template:

- Template name: `eink_balanced_v1`
- Runtime module: `app/shared/panel_font_templates.py`
- JSON preset: `assets/themes/panel_font_template_eink_balanced_v1.json`

## How it works

- `build_panel_theme()` now auto-applies `panel_font_template` (default: `eink_balanced_v1`).
- If your theme already defines a key, the template will not override it.
- To disable template defaults, set:
  - `"panel_font_template": "none"`

## Recommended usage for new UI screens

1. Read generic keys from theme:
   - `panel_font_body_key`
   - `panel_font_body_focus_key`
   - `panel_font_body_size`
   - `panel_font_meta_key`
   - `panel_font_meta_size`
   - `panel_font_meta_spacing`
   - `panel_font_meta_compact`

2. Keep any screen-specific keys as overrides only when needed.

This keeps cross-screen typography consistent on 1-bit e-ink output.
