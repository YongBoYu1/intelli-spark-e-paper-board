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
    """Render a simplified, high-readability weather detail layout."""
    draw = ImageDraw.Draw(image)
    w, h = image.size

    if bool(theme.get("panel_mode", False)):
        try:
            draw.fontmode = "1"
        except Exception:
            pass

    ink = theme.get("ink", 0)
    card = theme.get("card", 255)
    muted = theme.get("muted", ink)

    draw.rectangle((0, 0, w, h), fill=card)
    pad = int(theme.get("weather_detail_pad", 10) or 10)
    border_w = int(theme.get("detail_border_width", 3) or 3)
    radius = int(theme.get("card_radius", 12) or 12)
    rounded_rect(draw, (pad, pad, w - pad - 1, h - pad - 1), radius=radius, outline=ink, width=border_w, fill=card)

    cx0 = pad + 14
    cy0 = pad + 12
    cx1 = w - pad - 15
    cy1 = h - pad - 13

    content_h = max(120, cy1 - cy0 + 1)
    header_h = min(68, max(56, int(content_h * 0.16)))
    hero_h = min(170, max(146, int(content_h * 0.37)))
    details_h = min(86, max(72, int(content_h * 0.18)))
    footer_h = content_h - header_h - hero_h - details_h
    if footer_h < 110:
        shrink = 110 - footer_h
        hero_h = max(128, hero_h - shrink)
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
    location_font = fonts.get("inter_black", max(20, int(header_h * 0.43)))
    meta_font = fonts.get("jet_bold", max(11, int(header_h * 0.24)))
    status_font = fonts.get("jet_bold", max(12, int(header_h * 0.28)))

    status_txt = str(theme.get("weather_status_text") or ("ONLINE" if has_data else "OFFLINE")).upper()
    sw, sh = text_size(draw, status_txt, status_font)
    status_x = cx1 - sw - 18
    status_y = header_y0 + 8
    dot = 8
    draw.ellipse((status_x - 16, status_y + 4, status_x - 16 + dot, status_y + 4 + dot), fill=ink)
    draw.text((status_x, status_y), status_txt, font=status_font, fill=ink)

    location_txt = str(state.model.location or "Unknown").strip() or "Unknown"
    max_loc_w = max(80, status_x - cx0 - 24)
    location_txt = truncate_text(draw, location_txt, location_font, max_loc_w)
    loc_y = header_y0 + 2
    draw.text((cx0, loc_y), location_txt, font=location_font, fill=ink)

    update_txt = str(theme.get("weather_last_update") or time.strftime("Updated %H:%M"))
    _, loc_h = text_size(draw, location_txt, location_font)
    _, mh = text_size(draw, update_txt, meta_font)
    update_y = min(header_y1 - mh - 6, loc_y + loc_h + 2)
    draw.text((cx0, update_y), update_txt, font=meta_font, fill=muted)

    # 2) Hero: icon + current temp + meta lines (fixed vertical flow, no overlap).
    hero_h = max(120, hero_y1 - hero_y0)
    icon_size = max(84, min(116, int(hero_h * 0.62)))
    icon_x = cx0 + 16
    icon_y = hero_y0 + max(8, (hero_h - icon_size) // 2)
    draw_weather_icon(draw, icon, icon_x, icon_y, size=icon_size, ink=ink, stroke=2)

    temp_font = fonts.get("inter_bold", max(56, min(92, int(hero_h * 0.52))))
    hero_meta_font = fonts.get("inter_semibold", max(16, min(24, int(hero_h * 0.16))))
    hero_sub_font = fonts.get("jet_bold", max(13, min(18, int(hero_h * 0.13))))

    temp_txt = _format_temp(hi_raw)
    _, th = text_size(draw, temp_txt, temp_font)
    text_x = icon_x + icon_size + 34
    temp_y = hero_y0 + 14
    draw.text((text_x, temp_y), temp_txt, font=temp_font, fill=ink)

    feels_txt = f"Feels {_format_temp(feels_val)}  |  H {_format_temp(hi_raw)}  L {_format_temp(lo_raw)}"
    condition_txt = _weather_word(icon)
    condition_y = temp_y + th + 8
    draw.text((text_x, condition_y), condition_txt, font=hero_meta_font, fill=ink)
    _, cond_h = text_size(draw, condition_txt, hero_meta_font)
    draw.text((text_x, condition_y + cond_h + 6), feels_txt, font=hero_sub_font, fill=muted)

    # 3) Detail strip: humidity / wind / precip.
    details = [("Humidity", humidity), ("Wind", wind), ("Precip", precip)]
    label_font = fonts.get("inter_semibold", max(12, int(details_h * 0.20)))
    value_font = fonts.get("jet_bold", max(20, int(details_h * 0.36)))
    strip_w = cx1 - cx0 + 1
    col_w = max(1, strip_w // 3)
    for i, (label, value) in enumerate(details):
        x0 = cx0 + i * col_w
        x1 = cx1 if i == 2 else (x0 + col_w)
        if i > 0:
            draw.line((x0, details_y0 + 8, x0, details_y1 - 8), fill=ink, width=1)

        lw, _ = text_size(draw, label, label_font)
        vw, vh = text_size(draw, value, value_font)
        draw.text((x0 + (x1 - x0 - lw) // 2, details_y0 + 8), label, font=label_font, fill=muted)
        draw.text((x0 + (x1 - x0 - vw) // 2, details_y1 - vh - 8), value, font=value_font, fill=ink)

    # 4) Short forecast footer: selected day + next two days.
    day_font = fonts.get("inter_black", 15)
    hi_font = fonts.get("inter_bold", 24)
    lo_font = fonts.get("jet_bold", 13)
    icon_size = max(28, min(42, int((footer_y1 - footer_y0) * 0.32)))
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
            draw.line((x0, footer_y0 + 6, x0, footer_y1 - 6), fill=ink, width=1)

        if col >= len(indices):
            placeholder = "--"
            pw, _ = text_size(draw, placeholder, day_font)
            draw.text((x0 + (x1 - x0 - pw) // 2, footer_y0 + 20), placeholder, font=day_font, fill=muted)
            continue

        d = days[indices[col]]
        dow = str(getattr(d, "dow", "--")).upper()[:3] or "--"
        hi_txt = _format_temp(getattr(d, "hi", None))
        lo_txt = _format_temp(getattr(d, "lo", None))

        dw, _ = text_size(draw, dow, day_font)
        draw.text((x0 + (x1 - x0 - dw) // 2, footer_y0 + 8), dow, font=day_font, fill=muted)

        icon_x = x0 + (x1 - x0 - icon_size) // 2
        icon_y = footer_y0 + 34
        draw_weather_icon(draw, getattr(d, "icon", "sun"), icon_x, icon_y, size=icon_size, ink=ink, stroke=2)

        htw, hth = text_size(draw, hi_txt, hi_font)
        _, lth = text_size(draw, lo_txt, lo_font)
        temp_y = footer_y1 - max(hth, lth) - 10
        draw.text((x0 + (x1 - x0) // 2 - htw, temp_y), hi_txt, font=hi_font, fill=ink)
        draw.text((x0 + (x1 - x0) // 2 + 4, temp_y + 7), lo_txt, font=lo_font, fill=muted)
