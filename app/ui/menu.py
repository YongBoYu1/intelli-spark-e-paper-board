from __future__ import annotations

from PIL import ImageDraw

from app.core.state import AppState, MenuItemId


def render_menu(image, state: AppState, fonts, theme: dict) -> None:
    """Simple full-screen menu matching TSX behavior (rotate selects, click activates, back exits)."""
    draw = ImageDraw.Draw(image)
    w, h = image.size

    bg = theme.get("card", 255)
    ink = theme.get("ink", 0)
    border = theme.get("border", ink)
    draw.rectangle((0, 0, w, h), fill=bg)

    title_font = fonts.get(theme.get("title_font", "inter_black"), 28)
    meta_font = fonts.get(theme.get("meta_font", "inter_regular"), 12)
    item_font = fonts.get(theme.get("menu_font", "inter_black"), 16)

    # Header
    draw.text((24, 20), "MENU", font=title_font, fill=ink)
    draw.text((24, 54), "ROTATE TO SELECT  •  ENTER TO OPEN  •  B TO BACK", font=meta_font, fill=theme.get("muted", ink))
    draw.line((24, 80, w - 24, 80), fill=border, width=int(theme.get("divider_width", 2) or 2))

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

