from __future__ import annotations

from PIL import ImageDraw

from app.core.state import AppState, MenuItemId
from app.shared.draw import draw_text_spaced, text_width_spaced, truncate_text
from app.shared.panel_font_templates import apply_panel_font_template
from app.ui.settings import _draw_home_icon


def home_menu_overlay_layout(width: int, height: int) -> dict[str, int | bool]:
    w = max(1, int(width))
    h = max(1, int(height))
    compact = w < 640
    outer_margin = 16 if not compact else 8
    inner_pad_x = 14 if not compact else 8
    gap = 12 if not compact else 8
    pill_h = 56 if not compact else 40
    pill_w_cap = 116 if not compact else 88
    pill_w_floor = 96 if not compact else 56
    count = 5
    available_pills_w = max(1, w - outer_margin * 2 - inner_pad_x * 2 - ((count - 1) * gap))
    pill_w = max(pill_w_floor, min(pill_w_cap, available_pills_w // count))
    total_w = (count * pill_w) + ((count - 1) * gap)
    overlay_w = total_w + (inner_pad_x * 2)
    x0 = max(outer_margin, (w - overlay_w) // 2)
    x1 = min(w - outer_margin, x0 + overlay_w)
    cy = h // 2
    overlay_h = 102 if not compact else 78
    y0 = max(80 if not compact else 96, cy - (overlay_h // 2))
    y1 = min(h - (80 if not compact else 96), y0 + overlay_h)
    pills_y = y0 + (28 if not compact else 24)
    return {
        "x0": x0,
        "y0": y0,
        "x1": x1,
        "y1": y1,
        "pill_w": pill_w,
        "pill_h": pill_h,
        "gap": gap,
        "pills_y": pills_y,
        "compact": compact,
    }


def home_menu_overlay_rect(width: int, height: int) -> tuple[int, int, int, int]:
    layout = home_menu_overlay_layout(width, height)
    return (
        int(layout["x0"]),
        int(layout["y0"]),
        int(layout["x1"]),
        int(layout["y1"]),
    )


def render_menu_overlay_home(image, state: AppState, fonts, theme: dict) -> None:
    theme = apply_panel_font_template(theme)
    draw = ImageDraw.Draw(image)
    if bool(theme.get("panel_mode", False)) or not bool(theme.get("panel_text_antialias", False)):
        try:
            draw.fontmode = "1"
        except Exception:
            pass

    w, h = image.size
    ink = theme.get("ink", 0)
    bg = theme.get("card", 255)
    border = theme.get("border", ink)
    muted = theme.get("muted", ink)

    body_focus_key = str(theme.get("panel_font_body_focus_key") or "inter_bold")
    meta_key = str(theme.get("panel_font_meta_key") or "jet_bold")
    body_base = max(12, int(theme.get("panel_font_body_size", 18) or 18))
    meta_base = max(11, int(theme.get("panel_font_meta_size", 13) or 13))
    meta_spacing = int(theme.get("panel_font_meta_spacing", 0) or 0)
    item_font = fonts.get(body_focus_key, max(16, int(body_base)))
    hint_font = fonts.get(meta_key, max(11, int(meta_base - 1)))

    layout = home_menu_overlay_layout(w, h)
    x0 = int(layout["x0"])
    y0 = int(layout["y0"])
    x1 = int(layout["x1"])
    y1 = int(layout["y1"])
    compact = bool(layout["compact"])
    radius = int(theme.get("card_radius", 12) or 12)
    if compact:
        radius = min(radius, 10)
    bw = int(theme.get("border_width", 2) or 2)
    if compact:
        bw = max(1, min(bw, 1))
    draw.rounded_rectangle((x0, y0, x1, y1), radius=radius, outline=border, width=bw, fill=bg)

    hint_text = "NAVIGATION"
    hint_w = text_width_spaced(draw, hint_text, hint_font, spacing=meta_spacing)
    hint_x = x0 + max(8, ((x1 - x0) - hint_w) // 2)
    draw_text_spaced(draw, hint_text, hint_x, y0 + (8 if not compact else 6), hint_font, spacing=meta_spacing, fill=muted)

    order = [MenuItemId.MEMO, MenuItemId.LIST, MenuItemId.TIMER, MenuItemId.CALENDAR, MenuItemId.SETTINGS]
    focused = state.ui.menu_focused
    gap = int(layout["gap"])
    pill_h = int(layout["pill_h"])
    pill_w = int(layout["pill_w"])
    pills_y = int(layout["pills_y"])
    total_w = (len(order) * pill_w) + ((len(order) - 1) * gap)
    start_x = x0 + max(8, ((x1 - x0) - total_w) // 2)

    item_px = max(12, int(body_base if not compact else max(12, body_base - 4)))
    label_budget = max(24, pill_w - (24 if not compact else 14))
    while item_px > 10:
        probe_font = fonts.get(body_focus_key, item_px)
        if max(draw.textlength(item.value, font=probe_font) for item in order) <= label_budget:
            break
        item_px -= 1
    item_font = fonts.get(body_focus_key, item_px)

    for i, item in enumerate(order):
        px0 = start_x + i * (pill_w + gap)
        px1 = px0 + pill_w
        is_focus = item == focused
        fill = ink if is_focus else bg
        text_fill = bg if is_focus else ink
        draw.rounded_rectangle((px0, pills_y, px1, pills_y + pill_h), radius=radius, outline=ink, width=bw, fill=fill)

        label = truncate_text(draw, item.value, item_font, label_budget)
        bbox = draw.textbbox((0, 0), label, font=item_font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        tx = px0 + ((pill_w - tw) / 2) - bbox[0]
        ty = pills_y + ((pill_h - th) / 2) - bbox[1]
        draw.text((tx, ty), label, font=item_font, fill=text_fill)


def render_menu(image, state: AppState, fonts, theme: dict) -> None:
    """Simple full-screen menu matching TSX behavior (rotate selects, click activates, back exits)."""
    theme = apply_panel_font_template(theme)
    draw = ImageDraw.Draw(image)
    if bool(theme.get("panel_mode", False)) or not bool(theme.get("panel_text_antialias", False)):
        try:
            draw.fontmode = "1"
        except Exception:
            pass

    w, h = image.size

    bg = theme.get("card", 255)
    ink = theme.get("ink", 0)
    muted = theme.get("muted", ink)
    border = theme.get("border", ink)
    draw.rectangle((0, 0, w, h), fill=bg)

    body_key = str(theme.get("panel_font_body_key") or "inter_medium")
    body_focus_key = str(theme.get("panel_font_body_focus_key") or "inter_bold")
    meta_key = str(theme.get("panel_font_meta_key") or "jet_bold")
    body_base = max(12, int(theme.get("panel_font_body_size", 18) or 18))
    meta_base = max(11, int(theme.get("panel_font_meta_size", 13) or 13))
    meta_spacing = int(theme.get("panel_font_meta_spacing", 0) or 0)

    title_font = fonts.get(body_focus_key, max(24, int(body_base * 1.65)))
    hint_font = fonts.get(meta_key, meta_base)
    item_font = fonts.get(body_focus_key, max(18, int(body_base + 1)))

    # Header
    title_text = "MENU"
    title_y = 16
    title_bbox = draw.textbbox((0, 0), title_text, font=title_font)
    title_mid_y = title_y + int(round((title_bbox[1] + title_bbox[3]) / 2.0))
    title_h = max(1, int(title_bbox[3] - title_bbox[1]))
    icon_size = max(38, int(round(title_h * 0.84)))
    icon_x = 24
    icon_y = max(4, title_mid_y - (icon_size // 2) - 2)
    _draw_home_icon(image, icon_x, icon_y, icon_size, ink)

    title_x = icon_x + icon_size + 14
    draw.text((title_x, title_y), title_text, font=title_font, fill=ink)
    hint_text = "ROTATE TO SELECT  -  CLICK TO OPEN"
    hint_w = text_width_spaced(draw, hint_text, hint_font, spacing=meta_spacing)
    hint_x = max(24, (w - 24) - hint_w)
    draw_text_spaced(draw, hint_text, hint_x, 52, hint_font, spacing=meta_spacing, fill=muted)
    draw.line((24, 68, w - 24, 68), fill=border, width=int(theme.get("divider_width", 2) or 2))

    order = [MenuItemId.MEMO, MenuItemId.LIST, MenuItemId.TIMER, MenuItemId.CALENDAR, MenuItemId.SETTINGS]
    focused = state.ui.menu_focused

    # Horizontal pills
    gap = 14
    pill_h = 62
    pill_y = (h // 2) - (pill_h // 2)
    total_w = (len(order) * 120) + ((len(order) - 1) * gap)
    start_x = (w - total_w) // 2

    radius = int(theme.get("card_radius", 12) or 12)
    bw = int(theme.get("border_width", 2) or 2)

    for i, item in enumerate(order):
        x0 = start_x + i * (120 + gap)
        x1 = x0 + 120

        is_focus = item == focused
        fill = ink if is_focus else bg
        outline = ink
        text_fill = bg if is_focus else ink

        draw.rounded_rectangle((x0, pill_y, x1, pill_y + pill_h), radius=radius, outline=outline, width=bw, fill=fill)

        label = item.value
        tw = draw.textlength(label, font=item_font)
        draw.text((x0 + (120 - tw) / 2, pill_y + 22), label, font=item_font, fill=text_fill)
