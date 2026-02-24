from __future__ import annotations

import time

from PIL import ImageDraw

from app.core.state import AppState
from app.shared.draw import draw_weather_icon, rounded_rect, text_size, truncate_text


def _parse_number(raw) -> float | None:
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)

    txt = str(raw).strip()
    if not txt:
        return None

    cleaned = []
    for ch in txt:
        if ch.isdigit() or ch in (".", "-"):
            cleaned.append(ch)
        else:
            cleaned.append(" ")
    token = "".join(cleaned).split()
    if not token:
        return None
    try:
        return float(token[0])
    except Exception:
        return None


def _format_temp(raw) -> str:
    val = _parse_number(raw)
    if val is None:
        return "--"
    return f"{int(round(val))}°"


def _format_percent(raw) -> str:
    val = _parse_number(raw)
    if val is None:
        return "--"
    return f"{int(round(val))}%"


def _format_wind(raw) -> str:
    val = _parse_number(raw)
    if val is None:
        return "--"
    return f"{int(round(val))} km/h"


def _metric(day, names: tuple[str, ...]):
    if day is None:
        return None
    for name in names:
        value = getattr(day, name, None)
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return None


def _weather_word(icon_name: str) -> str:
    icon = str(icon_name or "sun").strip().lower().replace("-", "_").replace(" ", "_")
    mapping = {
        "sun": "Sunny",
        "clear": "Clear",
        "cloud": "Cloudy",
        "cloudy": "Cloudy",
        "overcast": "Overcast",
        "partly_cloudy": "Partly Cloudy",
        "rain": "Rain",
        "drizzle": "Drizzle",
        "storm": "Storm",
        "thunder": "Thunder",
        "thunderstorm": "Thunder",
        "snow": "Snow",
        "sleet": "Sleet",
    }
    return mapping.get(icon, "Weather")


def _select_days(state: AppState):
    days = list(state.model.weather[:7])
    if not days:
        return [], 0, None
    sel = int(state.ui.weather_day_index or 0) % len(days)
    return days, sel, days[sel]


def render_weather_detail(image, state: AppState, fonts, theme: dict) -> None:
    """Render weather detail using a 4-zone e-paper-friendly layout."""
    draw = ImageDraw.Draw(image)
    w, h = image.size

    ink = theme.get("ink", 0)
    card = theme.get("card", 255)
    muted = theme.get("muted", ink)

    border_w = int(theme.get("detail_border_width", 3) or 3)
    radius = int(theme.get("card_radius", 12) or 12)
    draw.rectangle((0, 0, w, h), fill=card)
    rounded_rect(draw, (0, 0, w - 1, h - 1), radius=radius + 4, outline=ink, width=border_w, fill=card)

    frame_pad = int(theme.get("weather_detail_pad", 16) or 16)
    ix0 = frame_pad
    iy0 = frame_pad
    ix1 = w - frame_pad - 1
    iy1 = h - frame_pad - 1
    rounded_rect(draw, (ix0, iy0, ix1, iy1), radius=radius, outline=ink, width=2, fill=card)

    inner_pad = int(theme.get("weather_detail_inner_pad", 12) or 12)
    cx0 = ix0 + inner_pad
    cy0 = iy0 + inner_pad
    cx1 = ix1 - inner_pad
    cy1 = iy1 - inner_pad

    content_h = max(120, cy1 - cy0 + 1)
    header_h = min(74, max(48, int(content_h * 0.14)))
    details_h = min(96, max(62, int(content_h * 0.18)))
    footer_h = min(150, max(96, int(content_h * 0.28)))
    hero_h = content_h - header_h - details_h - footer_h
    if hero_h < 90:
        deficit = 90 - hero_h
        cut = min(deficit, max(0, footer_h - 84))
        footer_h -= cut
        deficit -= cut
        if deficit > 0:
            cut = min(deficit, max(0, details_h - 54))
            details_h -= cut
            deficit -= cut
        if deficit > 0:
            header_h = max(40, header_h - deficit)
        hero_h = content_h - header_h - details_h - footer_h

    header_y0 = cy0
    header_y1 = header_y0 + header_h
    hero_y0 = header_y1
    hero_y1 = hero_y0 + hero_h
    details_y0 = hero_y1
    details_y1 = details_y0 + details_h
    footer_y0 = details_y1
    footer_y1 = cy1

    draw.line((cx0, header_y1, cx1, header_y1), fill=ink, width=2)
    draw.line((cx0, hero_y1, cx1, hero_y1), fill=ink, width=2)
    draw.line((cx0, details_y1, cx1, details_y1), fill=ink, width=2)

    days, sel, current = _select_days(state)
    has_data = bool(current)

    hi_raw = _metric(current, ("hi",))
    lo_raw = _metric(current, ("lo",))
    hi_val = _parse_number(hi_raw)
    lo_val = _parse_number(lo_raw)
    icon = str(_metric(current, ("icon",)) or "sun")

    feels_raw = _metric(current, ("feels_like", "feelsLike", "feels"))
    feels_val = _parse_number(feels_raw)
    if feels_val is None and hi_val is not None and lo_val is not None:
        feels_val = (hi_val + lo_val) / 2.0

    humidity = _format_percent(_metric(current, ("humidity",)))
    wind = _format_wind(_metric(current, ("wind_kmh", "windKmh", "wind", "wind_speed")))
    precip = _format_percent(
        _metric(current, ("precip", "precip_chance", "precipChance", "rain_chance", "rainChance"))
    )

    # 1) Header: location + update time + connectivity status.
    location_font = fonts.get("inter_black", max(20, int(header_h * 0.50)))
    meta_font = fonts.get("jet_bold", max(11, int(header_h * 0.24)))
    status_font = fonts.get("jet_bold", max(11, int(header_h * 0.24)))

    status_txt = str(theme.get("weather_status_text") or ("ONLINE" if has_data else "OFFLINE")).upper()
    sw, sh = text_size(draw, status_txt, status_font)
    pill_h = sh + 10
    pill_w = sw + 34
    pill_x1 = cx1
    pill_x0 = max(cx0 + 120, pill_x1 - pill_w)
    pill_y0 = header_y0 + max(4, (header_h - pill_h) // 2)
    pill_y1 = pill_y0 + pill_h
    rounded_rect(draw, (pill_x0, pill_y0, pill_x1, pill_y1), radius=8, outline=ink, width=2, fill=card)

    dot = 8
    dot_y = pill_y0 + (pill_h // 2) - (dot // 2)
    draw.ellipse((pill_x0 + 8, dot_y, pill_x0 + 8 + dot, dot_y + dot), fill=ink)
    draw.text((pill_x0 + 20, pill_y0 + 4), status_txt, font=status_font, fill=ink)

    location_txt = str(state.model.location or "Unknown").strip() or "Unknown"
    max_loc_w = max(80, pill_x0 - cx0 - 12)
    location_txt = truncate_text(draw, location_txt, location_font, max_loc_w)
    draw.text((cx0, header_y0 + 3), location_txt, font=location_font, fill=ink)

    update_txt = str(theme.get("weather_last_update") or time.strftime("Updated %H:%M"))
    _, mh = text_size(draw, update_txt, meta_font)
    update_y = min(header_y1 - mh - 4, header_y0 + max(8, int(header_h * 0.54)))
    draw.text((cx0, update_y), update_txt, font=meta_font, fill=muted)

    # 2) Hero: icon + current temp + feels-like.
    hero_h = max(80, hero_y1 - hero_y0)
    icon_size = max(56, min(int(hero_h * 0.70), int((cx1 - cx0) * 0.18)))
    icon_x = cx0 + 10
    icon_y = hero_y0 + max(4, (hero_h - icon_size) // 2)
    draw_weather_icon(draw, icon, icon_x, icon_y, size=icon_size, ink=ink, stroke=2)

    temp_font = fonts.get("inter_black", max(44, min(94, int(hero_h * 0.62))))
    hero_meta_font = fonts.get("inter_semibold", max(14, min(24, int(hero_h * 0.16))))
    hero_sub_font = fonts.get("jet_bold", max(11, min(16, int(hero_h * 0.12))))

    temp_txt = _format_temp(hi_raw)
    _, th = text_size(draw, temp_txt, temp_font)
    text_x = icon_x + icon_size + 24
    temp_y = hero_y0 + max(0, (hero_h - th) // 2 - 14)
    draw.text((text_x, temp_y), temp_txt, font=temp_font, fill=ink)

    feels_txt = f"Feels {_format_temp(feels_val)}"
    condition_txt = _weather_word(icon)
    range_txt = f"H {_format_temp(hi_raw)}  L {_format_temp(lo_raw)}"
    draw.text((text_x, temp_y + th - 2), feels_txt, font=hero_meta_font, fill=ink)
    _, ch = text_size(draw, condition_txt, hero_sub_font)
    draw.text((text_x, temp_y + th + ch + 4), condition_txt, font=hero_sub_font, fill=muted)
    draw.text((text_x + 120, temp_y + th + ch + 4), range_txt, font=hero_sub_font, fill=muted)

    # 3) Detail strip: humidity / wind / precip.
    details = [("Humidity", humidity), ("Wind", wind), ("Precip", precip)]
    label_font = fonts.get("inter_semibold", max(11, int(details_h * 0.20)))
    value_font = fonts.get("jet_bold", max(16, int(details_h * 0.33)))
    strip_w = cx1 - cx0 + 1
    col_w = max(1, strip_w // 3)
    for i, (label, value) in enumerate(details):
        x0 = cx0 + i * col_w
        x1 = cx1 if i == 2 else (x0 + col_w)
        if i > 0:
            draw.line((x0, details_y0 + 8, x0, details_y1 - 8), fill=ink, width=1)

        lw, _ = text_size(draw, label, label_font)
        vw, vh = text_size(draw, value, value_font)
        draw.text((x0 + (x1 - x0 - lw) // 2, details_y0 + 10), label, font=label_font, fill=muted)
        draw.text((x0 + (x1 - x0 - vw) // 2, details_y1 - vh - 12), value, font=value_font, fill=ink)

    # 4) Short forecast footer: selected day + next two days.
    day_font = fonts.get("inter_black", 13)
    hi_font = fonts.get("inter_bold", 22)
    lo_font = fonts.get("jet_bold", 12)
    icon_size = max(24, min(40, int((footer_y1 - footer_y0) * 0.34)))
    f_w = cx1 - cx0 + 1
    f_col_w = max(1, f_w // 3)
    indices = []
    if days:
        count = min(3, len(days))
        indices = [(sel + i) % len(days) for i in range(count)]

    for col in range(3):
        x0 = cx0 + col * f_col_w
        x1 = cx1 if col == 2 else (x0 + f_col_w)
        if col > 0:
            draw.line((x0, footer_y0 + 8, x0, footer_y1 - 8), fill=ink, width=1)

        if col >= len(indices):
            placeholder = "--"
            pw, _ = text_size(draw, placeholder, day_font)
            draw.text((x0 + (x1 - x0 - pw) // 2, footer_y0 + 18), placeholder, font=day_font, fill=muted)
            continue

        d = days[indices[col]]
        dow = str(getattr(d, "dow", "--")).upper()[:3] or "--"
        hi_txt = _format_temp(getattr(d, "hi", None))
        lo_txt = _format_temp(getattr(d, "lo", None))

        dw, _ = text_size(draw, dow, day_font)
        draw.text((x0 + (x1 - x0 - dw) // 2, footer_y0 + 10), dow, font=day_font, fill=muted)

        icon_x = x0 + (x1 - x0 - icon_size) // 2
        icon_y = footer_y0 + 30
        draw_weather_icon(draw, getattr(d, "icon", "sun"), icon_x, icon_y, size=icon_size, ink=ink, stroke=2)

        htw, hth = text_size(draw, hi_txt, hi_font)
        _, lth = text_size(draw, lo_txt, lo_font)
        temp_y = footer_y1 - max(hth, lth) - 14
        draw.text((x0 + (x1 - x0) // 2 - htw, temp_y), hi_txt, font=hi_font, fill=ink)
        draw.text((x0 + (x1 - x0) // 2 + 2, temp_y + 6), lo_txt, font=lo_font, fill=muted)

        if col == 0:
            draw.line((x0 + 16, footer_y0 + 8, x1 - 16, footer_y0 + 8), fill=ink, width=3)
