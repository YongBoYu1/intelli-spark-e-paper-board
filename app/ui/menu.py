from __future__ import annotations

from PIL import ImageDraw

from app.core.state import AppState, MenuItemId
from app.shared.draw import draw_text_spaced, text_width_spaced
from app.shared.panel_font_templates import apply_panel_font_template
from app.ui.settings import _draw_home_icon


def home_menu_overlay_rect(width: int, height: int) -> tuple[int, int, int, int]:
    w = max(1, int(width))
    h = max(1, int(height))
    gap = 12
    pill_h = 56
    pill_w = 116
    count = 5
    total_w = (count * pill_w) + ((count - 1) * gap)
    x0 = max(16, (w - total_w) // 2 - 14)
    x1 = min(w - 16, x0 + total_w + 28)
    cy = h // 2
    y0 = max(80, cy - 46)
    y1 = min(h - 80, y0 + 102)
    return (x0, y0, x1, y1)


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

    x0, y0, x1, y1 = home_menu_overlay_rect(w, h)
    radius = int(theme.get("card_radius", 12) or 12)
    bw = int(theme.get("border_width", 2) or 2)
    draw.rounded_rectangle((x0, y0, x1, y1), radius=radius, outline=border, width=bw, fill=bg)

    hint_text = "NAVIGATION"
    hint_w = text_width_spaced(draw, hint_text, hint_font, spacing=meta_spacing)
    hint_x = x0 + max(8, ((x1 - x0) - hint_w) // 2)
    draw_text_spaced(draw, hint_text, hint_x, y0 + 8, hint_font, spacing=meta_spacing, fill=muted)

    order = [MenuItemId.MEMO, MenuItemId.LIST, MenuItemId.TIMER, MenuItemId.CALENDAR, MenuItemId.SETTINGS]
    focused = state.ui.menu_focused
    gap = 12
    pill_h = 56
    pill_w = 116
    pills_y = y0 + 28
    total_w = (len(order) * pill_w) + ((len(order) - 1) * gap)
    start_x = x0 + max(8, ((x1 - x0) - total_w) // 2)

    for i, item in enumerate(order):
        px0 = start_x + i * (pill_w + gap)
        px1 = px0 + pill_w
        is_focus = item == focused
        fill = ink if is_focus else bg
        text_fill = bg if is_focus else ink
        draw.rounded_rectangle((px0, pills_y, px1, pills_y + pill_h), radius=radius, outline=ink, width=bw, fill=fill)

        label = item.value
        tw = draw.textlength(label, font=item_font)
        draw.text((px0 + (pill_w - tw) / 2, pills_y + 18), label, font=item_font, fill=text_fill)


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
