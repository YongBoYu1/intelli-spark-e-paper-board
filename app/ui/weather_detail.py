from __future__ import annotations

from PIL import ImageDraw

from app.core.state import AppState
from app.shared.draw import text_size, draw_weather_icon, rounded_rect


def render_weather_detail(image, state: AppState, fonts, theme: dict) -> None:
    """Weather detail view matching TSX WeatherDetailView.tsx."""
    draw = ImageDraw.Draw(image)
    w, h = image.size

    ink = theme.get("ink", 0)
    card = theme.get("card", 255)
    muted = theme.get("muted", ink)

    gray_50 = (249, 250, 251) if isinstance(card, tuple) else 255
    gray_200 = (229, 231, 235) if isinstance(card, tuple) else ink

    border_w = int(theme.get("detail_border_width", 4) or 4)
    radius = int(theme.get("card_radius", 12) or 12) + 4

    # Outer container
    draw.rectangle((0, 0, w, h), fill=card)
    rounded_rect(draw, (0, 0, w - 1, h - 1), radius=radius, outline=ink, width=border_w, fill=card)

    top_h = int(h * 0.60)
    bottom_y = top_h
    # Top/bottom divider
    draw.line((0, bottom_y, w, bottom_y), fill=ink, width=border_w)

    left_w = int(w * 0.40)
    # Left top panel
    draw.rectangle((0, 0, left_w, top_h), fill=gray_50)
    draw.line((left_w, 0, left_w, top_h), fill=gray_200, width=2)

    # Header row inside left top
    pad = 24
    esc_font = fonts.get("jet_bold", 11)
    pill_font = fonts.get("jet_bold", 12)

    pill_txt = "TODAY"
    pw, ph = text_size(draw, pill_txt, pill_font)
    pill_box = (pad, pad, pad + pw + 18, pad + ph + 10)
    rounded_rect(draw, pill_box, radius=6, outline=ink, width=1, fill=card)
    draw.text((pill_box[0] + 9, pill_box[1] + 4), pill_txt, font=pill_font, fill=ink)

    esc_txt = "ESC"
    ew, eh = text_size(draw, esc_txt, esc_font)
    draw.text((left_w - pad - ew, pad + 4), esc_txt, font=esc_font, fill=muted)

    # Forecast data
    days = state.model.weather[:4]
    sel = int(state.ui.weather_day_index or 0)
    if not days:
        days = []
        sel = 0

    today_hi = 22
    today_lo = 12
    icon = "sun"
    if days:
        sel = sel % len(days)
        icon = days[sel].icon
        today_hi = int(days[sel].hi)
        today_lo = int(days[sel].lo)

    # Main status
    icon_size = 80
    icon_x = left_w // 2 - icon_size // 2
    icon_y = pad + 58
    draw_weather_icon(draw, icon, icon_x, icon_y, size=icon_size, ink=ink, stroke=2)

    temp_font = fonts.get("inter_black", 60)
    temp_txt = f"{today_hi}°"
    tw, th = text_size(draw, temp_txt, temp_font)
    temp_y = icon_y + icon_size + 0
    draw.text((left_w // 2 - tw // 2, temp_y), temp_txt, font=temp_font, fill=ink)

    range_font = fonts.get("jet_bold", 18)
    range_txt = f"{today_lo}° / {today_hi}°"
    rw, rh = text_size(draw, range_txt, range_font)
    range_y = temp_y + th - 10
    draw.text((left_w // 2 - rw // 2, range_y), range_txt, font=range_font, fill=muted)

    desc_font = fonts.get("inter_bold", 14)
    desc = theme.get("weather_description") or "Clear skies throughout the day.\nPerfect for outdoor activities."
    # Simple center multi-line
    lines = [ln.strip() for ln in str(desc).splitlines() if ln.strip()]
    # Place description below temp block; avoid overlap.
    dy = max(int(range_y + rh + 16), int(top_h - 76))
    for i, ln in enumerate(lines[:2]):
        lw, lh = text_size(draw, ln, desc_font)
        draw.text((left_w // 2 - lw // 2, dy + i * (lh + 2)), ln, font=desc_font, fill=ink)

    # Right top grid
    grid_x0 = left_w
    grid_w = w - left_w
    grid_pad = 36
    cell_w = (grid_w - grid_pad * 2) // 2
    cell_h = (top_h - grid_pad * 2) // 2

    label_font = fonts.get("inter_black", 10)
    value_font = fonts.get("jet_bold", 18)

    def draw_detail(ix, iy, label, value, icon_name=None):
        x = grid_x0 + grid_pad + ix * cell_w
        y = grid_pad + iy * cell_h
        # icon box
        box = (x, y, x + 36, y + 36)
        rounded_rect(draw, box, radius=8, outline=ink, width=2, fill=card)
        # very small placeholder glyph (we don't have lucide icons; keep simple)
        cx = (box[0] + box[2]) // 2
        cy = (box[1] + box[3]) // 2
        draw.line((cx - 8, cy, cx + 8, cy), fill=ink, width=2)
        draw.line((cx, cy - 8, cx, cy + 8), fill=ink, width=2)

        draw.text((x + 48, y + 2), label.upper(), font=label_font, fill=muted)
        draw.text((x + 48, y + 18), value, font=value_font, fill=ink)

    # Use whatever we can; real values will come from mobile later.
    draw_detail(0, 0, "Humidity", "45%")
    draw_detail(1, 0, "Wind", "12 km/h")
    draw_detail(0, 1, "Precip", "10%")
    draw_detail(1, 1, "UV Index", "4 Low")

    # Bottom 4-day strip
    strip_y0 = bottom_y
    strip_h = h - bottom_y
    if not days:
        return

    col_w = w // 4
    for i, d in enumerate(days[:4]):
        cx0 = i * col_w
        cx1 = cx0 + col_w
        if i > 0:
            draw.line((cx0, strip_y0, cx0, h), fill=gray_200, width=2)

        dow_font = fonts.get("inter_black", 12)
        dow = str(d.dow).upper()
        dw, dh = text_size(draw, dow, dow_font)
        draw.text((cx0 + col_w // 2 - dw // 2, strip_y0 + 22), dow, font=dow_font, fill=muted)

        ico = 32
        draw_weather_icon(draw, d.icon, cx0 + col_w // 2 - ico // 2, strip_y0 + 54, size=ico, ink=ink, stroke=2)

        hi_font = fonts.get("inter_bold", 24)
        lo_font = fonts.get("jet_bold", 14)
        hi = f"{int(d.hi)}°"
        lo = f"{int(d.lo)}°"
        hw2, hh2 = text_size(draw, hi, hi_font)
        lw2, lh2 = text_size(draw, lo, lo_font)
        y_temp = strip_y0 + 102
        draw.text((cx0 + col_w // 2 - hw2 // 2 - 10, y_temp), hi, font=hi_font, fill=ink)
        draw.text((cx0 + col_w // 2 + hw2 // 2 - 2, y_temp + 8), lo, font=lo_font, fill=muted)

        # Selected day indicator (subtle, no extra text)
        if i == sel:
            draw.line((cx0 + 20, strip_y0 + 14, cx1 - 20, strip_y0 + 14), fill=ink, width=3)
