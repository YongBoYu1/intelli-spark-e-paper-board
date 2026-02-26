from __future__ import annotations

from copy import deepcopy


# Reusable e-ink typography templates.
# Future screens can map these generic keys to their own widget typography.
PANEL_FONT_TEMPLATES: dict[str, dict] = {
    "none": {},
    "eink_balanced_v1": {
        # Generic panel typography tokens for future UI modules.
        "panel_text_antialias": False,
        "panel_font_body_key": "inter_medium",
        "panel_font_body_focus_key": "inter_bold",
        "panel_font_body_size": 18,
        "panel_font_meta_key": "jet_bold",
        "panel_font_meta_size": 13,
        "panel_font_meta_spacing": 0,
        "panel_font_meta_compact": True,
        "panel_font_double_pass": False,
        "panel_font_double_pass_shift": 1,
        # Current kitchen-home bindings.
        "b_text_antialias": False,
        "b_panel_inventory_item_font": "inter_medium",
        "b_panel_inventory_item_focus_font": "inter_bold",
        "b_panel_inventory_item_size": 18,
        "b_panel_badge_font": "jet_bold",
        "b_panel_badge_size": 13,
        "b_panel_badge_spacing": 0,
        "b_panel_badge_force_compact": True,
        "b_panel_shopping_item_font": "inter_medium",
        "b_panel_shopping_item_focus_font": "inter_bold",
        "b_panel_shopping_item_size": 18,
        "b_panel_right_item_double_pass": False,
        "b_panel_right_item_double_pass_shift": 1,
    },
}


def apply_panel_font_template(theme: dict | None, template_name: str | None = None) -> dict:
    t = dict(theme or {})
    selected = str(template_name or t.get("panel_font_template") or "eink_balanced_v1").strip().lower()
    if selected not in PANEL_FONT_TEMPLATES:
        selected = "eink_balanced_v1"
    t["panel_font_template"] = selected

    for key, value in PANEL_FONT_TEMPLATES[selected].items():
        t.setdefault(key, deepcopy(value))
    return t
