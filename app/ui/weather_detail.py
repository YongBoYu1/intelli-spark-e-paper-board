from __future__ import annotations

import math
import time

from PIL import ImageDraw

from app.core.state import AppState
from app.shared.draw import draw_weather_icon, text_size, truncate_text


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


def _draw_hero_icon(draw, icon_name: str, x: int, y: int, size: int, ink) -> None:
    icon = str(icon_name or "sun").strip().lower().replace("-", "_").replace(" ", "_")
    stroke = max(3, int(size * 0.055))

    if icon in ("sun", "clear"):
        cx = x + size // 2
        cy = y + size // 2
        r = int(size * 0.22)
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), outline=ink, width=stroke)

        ray_in = int(size * 0.34)
        ray_out = int(size * 0.47)
        for deg in (0, 45, 90, 135, 180, 225, 270, 315):
            rad = math.radians(deg)
            x1 = int(cx + math.cos(rad) * ray_in)
            y1 = int(cy + math.sin(rad) * ray_in)
            x2 = int(cx + math.cos(rad) * ray_out)
            y2 = int(cy + math.sin(rad) * ray_out)
            draw.line((x1, y1, x2, y2), fill=ink, width=stroke)
        return

    # For non-sun states, keep the curated icon set but with heavier stroke.
    draw_weather_icon(draw, icon, x, y, size=size, ink=ink, stroke=max(3, int(size * 0.05)))


def render_weather_detail(image, state: AppState, fonts, theme: dict) -> None:
    """Render weather detail for e-paper with strict non-overlapping layout."""
    draw = ImageDraw.Draw(image)
    w, h = image.size

    if bool(theme.get("panel_mode", False)) or not bool(theme.get("panel_text_antialias", False)):
        try:
            draw.fontmode = "1"
        except Exception:
            pass

    ink = theme.get("ink", 0)
    card = theme.get("card", 255)
    muted = theme.get("muted", ink)

    body_focus_key = str(theme.get("panel_font_body_focus_key") or "inter_bold")
    meta_key = str(theme.get("panel_font_meta_key") or "jet_bold")
    body_base = max(12, int(theme.get("panel_font_body_size", 18) or 18))
    meta_base = max(10, int(theme.get("panel_font_meta_size", 13) or 13))

    draw.rectangle((0, 0, w, h), fill=card)

    pad_x = int(theme.get("weather_detail_pad_x", 22) or 22)
    pad_y = int(theme.get("weather_detail_pad_y", 16) or 16)
    cx0 = pad_x
    cy0 = pad_y
    cx1 = w - pad_x - 1
    cy1 = h - pad_y - 1

    content_h = max(120, cy1 - cy0 + 1)
    header_h = min(72, max(62, int(content_h * 0.16)))
    hero_h = min(168, max(146, int(content_h * 0.36)))
    details_h = min(86, max(76, int(content_h * 0.18)))
    footer_h = content_h - header_h - hero_h - details_h
    if footer_h < 98:
        hero_h = max(124, hero_h - (98 - footer_h))
        footer_h = content_h - header_h - hero_h - details_h
    if footer_h < 88:
        details_h = max(68, details_h - (88 - footer_h))
        footer_h = content_h - header_h - hero_h - details_h

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

    # 1) Header: location + update time + simple status.
    meta_font = fonts.get(meta_key, max(meta_base + 1, 12))
    status_font = fonts.get(meta_key, max(meta_base + 4, 15))
    update_txt = str(theme.get("weather_last_update") or time.strftime("Updated %H:%M"))

    status_txt = str(theme.get("weather_status_text") or ("ONLINE" if has_data else "OFFLINE")).upper()
    sw, _ = text_size(draw, status_txt, status_font)
    status_x = cx1 - sw - 18
    status_y = header_y0 + 8
    dot = 8
    draw.ellipse((status_x - 16, status_y + 4, status_x - 16 + dot, status_y + 4 + dot), fill=ink)
    draw.text((status_x, status_y), status_txt, font=status_font, fill=ink)

    location_txt = str(state.model.location or "Unknown").strip() or "Unknown"
    max_loc_w = max(120, status_x - cx0 - 24)
    update_h = text_size(draw, update_txt, meta_font)[1]
    loc_size = max(22, int(body_base * 1.60))
    loc_min = max(18, int(body_base * 1.25))
    location_font = fonts.get(body_focus_key, loc_size)
    loc_y = header_y0 + 2
    update_y = header_y1 - update_h - 6
    max_loc_h = max(14, update_y - loc_y - 4)
    while True:
        location_font = fonts.get(body_focus_key, loc_size)
        loc_fit = truncate_text(draw, location_txt, location_font, max_loc_w)
        _, loc_h = text_size(draw, loc_fit, location_font)
        if loc_h <= max_loc_h or loc_size <= loc_min:
            location_txt = loc_fit
            break
        loc_size -= 2

    draw.text((cx0, loc_y), location_txt, font=location_font, fill=ink)

    draw.text((cx0, update_y), update_txt, font=meta_font, fill=muted)

    # 2) Hero: icon + current temp + meta lines (fixed vertical flow, no overlap).
    hero_h = max(120, hero_y1 - hero_y0)
    icon_size = max(82, min(112, int(hero_h * 0.58)))
    icon_x = cx0 + 16
    icon_y = hero_y0 + max(8, (hero_h - icon_size) // 2)
    _draw_hero_icon(draw, icon, icon_x, icon_y, icon_size, ink)

    temp_txt = _format_temp(hi_raw)
    condition_txt = _weather_word(icon)
    feels_txt = f"Feels {_format_temp(feels_val)}  |  H {_format_temp(hi_raw)}  L {_format_temp(lo_raw)}"

    text_x = icon_x + icon_size + 34
    max_text_w = max(100, cx1 - text_x - 2)
    temp_size = max(48, int(body_base * 4.1))
    cond_size = max(16, int(body_base * 1.35))
    sub_size = max(13, int(meta_base * 1.30))

    while True:
        temp_font = fonts.get(body_focus_key, temp_size)
        hero_meta_font = fonts.get(body_focus_key, cond_size)
        hero_sub_font = fonts.get(meta_key, sub_size)
        clipped_feels = truncate_text(draw, feels_txt, hero_sub_font, max_text_w)
        _, temp_h = text_size(draw, temp_txt, temp_font)
        _, cond_h = text_size(draw, condition_txt, hero_meta_font)
        _, sub_h = text_size(draw, clipped_feels, hero_sub_font)
        total_h = temp_h + 6 + cond_h + 6 + sub_h
        if total_h <= (hero_h - 12) or temp_size <= max(42, int(body_base * 3.0)):
            feels_txt = clipped_feels
            break
        temp_size -= 2
        if cond_size > max(15, int(body_base * 1.1)):
            cond_size -= 1
        if sub_size > max(12, meta_base):
            sub_size -= 1

    _, th = text_size(draw, temp_txt, temp_font)
    temp_y = hero_y0 + max(8, (hero_h - total_h) // 2)
    draw.text((text_x, temp_y), temp_txt, font=temp_font, fill=ink)

    condition_y = temp_y + th + 12
    draw.text((text_x, condition_y), condition_txt, font=hero_meta_font, fill=ink)
    _, cond_h = text_size(draw, condition_txt, hero_meta_font)
    draw.text((text_x, condition_y + cond_h + 6), feels_txt, font=hero_sub_font, fill=muted)

    # 3) Detail strip: humidity / wind / precip.
    details = [("Humidity", humidity), ("Wind", wind), ("Precip", precip)]
    label_font = fonts.get(meta_key, max(meta_base + 1, 12))
    value_font = fonts.get(body_focus_key, max(22, int(body_base * 1.8)))
    strip_w = cx1 - cx0 + 1
    col_w = max(1, strip_w // 3)
    for i, (label, value) in enumerate(details):
        x0 = cx0 + i * col_w
        x1 = cx1 if i == 2 else (x0 + col_w)
        lw, _ = text_size(draw, label, label_font)
        vw, _ = text_size(draw, value, value_font)
        draw.text((x0 + (x1 - x0 - lw) // 2, details_y0 + 8), label, font=label_font, fill=muted)
        draw.text((x0 + (x1 - x0 - vw) // 2, details_y0 + 8 + 26), value, font=value_font, fill=ink)

    # 4) Short forecast footer: selected day + next two days.
    day_font = fonts.get(meta_key, max(meta_base + 4, 15))
    temp_font = fonts.get(body_focus_key, max(body_base + 8, 24))
    icon_size = max(24, min(38, int((footer_y1 - footer_y0) * 0.30)))
    f_w = cx1 - cx0 + 1
    f_col_w = max(1, f_w // 3)
    indices = []
    if days:
        count = min(3, len(days))
        indices = [(sel + i) % len(days) for i in range(count)]

    for col in range(3):
        x0 = cx0 + col * f_col_w
        x1 = cx1 if col == 2 else (x0 + f_col_w)

        if col >= len(indices):
            placeholder = "--"
            pw, _ = text_size(draw, placeholder, day_font)
            draw.text((x0 + (x1 - x0 - pw) // 2, footer_y0 + 20), placeholder, font=day_font, fill=muted)
            continue

        d = days[indices[col]]
        dow = str(getattr(d, "dow", "--")).upper()[:3] or "--"
        range_txt = f"{_format_temp(getattr(d, 'hi', None))} / {_format_temp(getattr(d, 'lo', None))}"

        dw, _ = text_size(draw, dow, day_font)
        day_fill = ink if col == 0 else muted
        draw.text((x0 + (x1 - x0 - dw) // 2, footer_y0 + 8), dow, font=day_font, fill=day_fill)

        icon_x = x0 + (x1 - x0 - icon_size) // 2
        icon_y = footer_y0 + 34
        draw_weather_icon(draw, getattr(d, "icon", "sun"), icon_x, icon_y, size=icon_size, ink=ink, stroke=2)

        rw, rh = text_size(draw, range_txt, temp_font)
        temp_y = footer_y1 - rh - 8
        draw.text((x0 + (x1 - x0 - rw) // 2, temp_y), range_txt, font=temp_font, fill=ink)
