from __future__ import annotations

from PIL import ImageDraw

from app.core.state import AppState, MenuItemId


def render_placeholder(image, state: AppState, fonts, theme: dict) -> None:
    draw = ImageDraw.Draw(image)
    w, h = image.size

    bg = theme.get("card", 255)
    ink = theme.get("ink", 0)
    muted = theme.get("muted", ink)

    draw.rectangle((0, 0, w, h), fill=bg)

    title = "DETAIL"
    if state.ui.active_menu == MenuItemId.SETTINGS:
        title = "SETTINGS"
    elif state.ui.active_menu == MenuItemId.MEMO:
        title = "MEMO"

    title_font = fonts.get(theme.get("title_font", "inter_black"), 36)
    meta_font = fonts.get(theme.get("meta_font", "inter_regular"), 14)

    tw = draw.textlength(title, font=title_font)
    draw.text(((w - tw) / 2, h * 0.35), title, font=title_font, fill=ink)

    msg = "B / ESC / BACKSPACE TO GO BACK"
    mw = draw.textlength(msg, font=meta_font)
    draw.text(((w - mw) / 2, h * 0.35 + 60), msg, font=meta_font, fill=muted)

