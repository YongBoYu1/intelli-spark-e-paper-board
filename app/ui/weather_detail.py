from __future__ import annotations

import os
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from app.core.state import AppState
from app.shared.draw import draw_weather_icon, text_size, truncate_text

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_ERIK_FONT_PATH = os.path.join(
    _REPO_ROOT,
    "assets",
    "weather_icon_packs",
    "erikflowers",
    "weathericons-regular-webfont.ttf",
)
_KICKSTAND_PNG_DIR = os.path.join(_REPO_ROOT, "assets", "weather_icon_packs", "kickstand", "png")

_ERIK_GLYPHS = {
    "sun": "\uf00d",  # wi-day-sunny
    "clear": "\uf00d",
    "cloud": "\uf013",  # wi-cloudy
    "cloudy": "\uf013",
    "overcast": "\uf013",
    "partly_cloudy": "\uf002",  # wi-day-cloudy
    "partly": "\uf002",
    "rain": "\uf019",  # wi-rain
    "drizzle": "\uf019",
    "storm": "\uf01e",  # wi-thunderstorm
    "thunder": "\uf01e",
    "thunderstorm": "\uf01e",
    "snow": "\uf01b",  # wi-snow
    "sleet": "\uf0b5",  # wi-sleet
    "hail": "\uf015",  # wi-hail
}

_KICKSTAND_NAMES = {
    "sun": "Sun",
    "clear": "Sun",
    "cloud": "Cloud",
    "cloudy": "Cloud",
    "overcast": "Cloud",
    "partly_cloudy": "PartlySunny",
    "partly": "PartlySunny",
    "rain": "Rain",
    "drizzle": "Rain",
    "storm": "Storm",
    "thunder": "Storm",
    "thunderstorm": "Storm",
    "snow": "Snow",
    "sleet": "Hail",
    "hail": "Hail",
}


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
        return "-- km/h"
    return f"{int(round(val))} km/h"


def _format_temp_with_unit(raw, unit: str = "C") -> str:
    t = _format_temp(raw)
    if t == "--":
        return "--"
    return f"{t}{unit}"


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


def _select_days(state: AppState):
    days = list(state.model.weather[:7])
    if not days:
        return [], 0, None
    sel = int(state.ui.weather_day_index or 0) % len(days)
    return days, sel, days[sel]


def _fit_font_to_width(draw, fonts, key: str, text: str, start: int, minimum: int, max_width: int):
    size = max(minimum, start)
    font = fonts.get(key, size)
    clipped = truncate_text(draw, text, font, max_width)
    while size > minimum:
        font = fonts.get(key, size)
        clipped = truncate_text(draw, text, font, max_width)
        w, _ = text_size(draw, clipped, font)
        if w <= max_width:
            return font, clipped, size
        size -= 1
    font = fonts.get(key, minimum)
    clipped = truncate_text(draw, text, font, max_width)
    return font, clipped, minimum


def _fit_font_full_text_to_width(draw, fonts, key: str, text: str, start: int, minimum: int, max_width: int):
    """Fit full text into width by shrinking only; never apply ellipsis truncation."""
    size = max(minimum, start)
    while size >= minimum:
        font = fonts.get(key, size)
        w, _ = text_size(draw, text, font)
        if w <= max_width:
            return font, text, size
        size -= 1
    font = fonts.get(key, minimum)
    return font, text, minimum


def _draw_centered_text_clamped(draw, text: str, font, cx: int, y: int, xmin: int, xmax: int, fill) -> None:
    tw, _ = text_size(draw, text, font)
    x = cx - tw // 2
    if x < xmin:
        x = xmin
    if x + tw > xmax:
        x = xmax - tw
    draw.text((x, y), text, font=font, fill=fill)


def _normalize_icon_name(icon_name: str) -> str:
    return str(icon_name or "cloud").strip().lower().replace("-", "_").replace(" ", "_")


def _forecast_icon_visual_scale(theme: dict, icon_name: str) -> tuple[float, float]:
    pack = str(theme.get("weather_icon_pack") or "native").strip().lower()
    variant = str(theme.get("weather_icon_variant") or "").strip().lower()
    icon = _normalize_icon_name(icon_name)

    # Kickstand thin cloud icons look optically taller than rain/storm.
    # Keep width aligned, compress only height for cloud-like shapes.
    if pack in ("kickstand", "kickstandapps", "kick") and variant in ("thin", "line"):
        if icon in ("cloud", "cloudy", "overcast"):
            return (1.0, 0.70)
        if icon in ("partly", "partly_cloudy"):
            return (1.0, 0.78)
    return (1.0, 1.0)


@lru_cache(maxsize=64)
def _load_erik_font(size: int):
    if not os.path.exists(_ERIK_FONT_PATH):
        return None
    try:
        return ImageFont.truetype(_ERIK_FONT_PATH, max(8, int(size)))
    except Exception:
        return None


@lru_cache(maxsize=128)
def _load_kickstand_png(path: str):
    try:
        return Image.open(path).convert("RGBA")
    except Exception:
        return None


def _draw_erik_icon(draw, icon_name: str, x: int, y: int, size: int, ink) -> bool:
    key = _normalize_icon_name(icon_name)
    glyph = _ERIK_GLYPHS.get(key) or _ERIK_GLYPHS["cloud"]

    font_size = max(12, int(size * 0.96))
    min_size = max(8, int(size * 0.56))
    while font_size >= min_size:
        font = _load_erik_font(font_size)
        if font is None:
            return False
        bbox = draw.textbbox((0, 0), glyph, font=font)
        gw = bbox[2] - bbox[0]
        gh = bbox[3] - bbox[1]
        if gw <= size and gh <= size:
            tx = x + (size - gw) // 2 - bbox[0]
            ty = y + (size - gh) // 2 - bbox[1]
            draw.text((tx, ty), glyph, font=font, fill=ink)
            return True
        font_size -= 1
    return False


def _draw_kickstand_icon(
    image,
    icon_name: str,
    x: int,
    y: int,
    size: int,
    size_h: int | None,
    ink,
    variant: str,
    thicken: bool = False,
    alpha_threshold: int | None = None,
) -> bool:
    key = _normalize_icon_name(icon_name)
    name = _KICKSTAND_NAMES.get(key) or "Cloud"
    use_thin = str(variant or "").strip().lower() in ("thin", "line")
    filename = f"{name}{'-thin' if use_thin else ''}.png"
    path = os.path.join(_KICKSTAND_PNG_DIR, filename)
    if not os.path.exists(path) and use_thin:
        path = os.path.join(_KICKSTAND_PNG_DIR, f"{name}.png")
    src = _load_kickstand_png(path)
    if src is None:
        return False

    alpha_src = src.split()[-1]
    bbox = alpha_src.getbbox()
    if bbox:
        src = src.crop(bbox)

    try:
        resample = Image.Resampling.LANCZOS
    except Exception:
        resample = Image.LANCZOS
    target_w = max(1, int(size))
    target_h = max(1, int(size_h if size_h is not None else size))
    icon = src.resize((target_w, target_h), resample)
    alpha = icon.split()[-1]
    if thicken:
        try:
            # Add transparent padding before dilation to avoid edge clipping.
            pad = 2
            w, h = alpha.size
            padded = Image.new("L", (w + pad * 2, h + pad * 2), 0)
            padded.paste(alpha, (pad, pad))
            padded = padded.filter(ImageFilter.MaxFilter(3))
            alpha = padded.crop((pad, pad, pad + w, pad + h))
        except Exception:
            pass

    if alpha_threshold is not None:
        try:
            t = max(1, min(254, int(alpha_threshold)))
            alpha = alpha.point(lambda p: 255 if p >= t else 0)
        except Exception:
            pass

    paste_ink = ink
    if image.mode in ("1", "L") and isinstance(ink, tuple):
        paste_ink = int(round(sum(ink) / len(ink)))
    elif image.mode in ("RGB", "RGBA") and isinstance(ink, int):
        paste_ink = (ink, ink, ink) if image.mode == "RGB" else (ink, ink, ink, 255)

    # Treat only non-transparent parts as glyph strokes and tint with ink.
    image.paste(paste_ink, (x, y, x + target_w, y + target_h), alpha)
    return True


def _draw_weather_icon_pack(
    image,
    draw,
    theme: dict,
    icon_name: str,
    x: int,
    y: int,
    size: int,
    size_h: int | None,
    ink,
    stroke: int,
    thicken: bool = False,
) -> None:
    pack = str(theme.get("weather_icon_pack") or "native").strip().lower()
    if pack in ("erik", "erikflowers", "weather-icons", "weather_icons"):
        if _draw_erik_icon(draw, icon_name, x, y, size, ink):
            return
    elif pack in ("kickstand", "kickstandapps", "kick"):
        variant = str(theme.get("weather_icon_variant") or "thin")
        alpha_threshold = int(theme.get("weather_icon_alpha_threshold", 185) or 185)
        if _draw_kickstand_icon(
            image,
            icon_name,
            x,
            y,
            size,
            size_h,
            ink,
            variant,
            thicken=thicken,
            alpha_threshold=alpha_threshold,
        ):
            return

    # Fallback to current native icon implementation.
    fallback_size = max(1, min(size, size_h)) if size_h is not None else size
    draw_weather_icon(draw, icon_name, x, y, size=fallback_size, ink=ink, stroke=stroke)


def render_weather_detail(image, state: AppState, fonts, theme: dict) -> None:
    """Render weather detail in a clean 3-block layout (hero / metrics / 3-day)."""
    draw = ImageDraw.Draw(image)
    w, h = image.size

    if bool(theme.get("panel_mode", False)) or not bool(theme.get("panel_text_antialias", False)):
        try:
            draw.fontmode = "1"
        except Exception:
            pass

    ink = theme.get("ink", 0)
    card = theme.get("card", 255)
    muted = theme.get("muted", ink)  # kept for compatibility with custom themes

    body_key = str(theme.get("panel_font_body_key") or "inter_medium")
    body_focus_key = str(theme.get("panel_font_body_focus_key") or "inter_bold")
    meta_key = str(theme.get("panel_font_meta_key") or "jet_bold")
    body_base = max(12, int(theme.get("panel_font_body_size", 18) or 18))
    meta_base = max(11, int(theme.get("panel_font_meta_size", 13) or 13))

    draw.rectangle((0, 0, w, h), fill=card)

    portrait_layout = h > w
    if portrait_layout:
        pad_x = int(theme.get("weather_detail_pad_x_portrait", 16) or 16)
        pad_y = int(theme.get("weather_detail_pad_y_portrait", 14) or 14)
    else:
        pad_x = int(theme.get("weather_detail_pad_x", 22) or 22)
        pad_y = int(theme.get("weather_detail_pad_y", 16) or 16)
    cx0 = pad_x
    cy0 = pad_y
    cx1 = w - pad_x - 1
    cy1 = h - pad_y - 1

    content_h = max(120, cy1 - cy0 + 1)
    if portrait_layout:
        hero_h = max(220, int(content_h * 0.39))
        metric_h = max(112, int(content_h * 0.18))
        min_forecast_h = 184
    else:
        hero_h = max(150, int(content_h * 0.41))
        metric_h = max(88, int(content_h * 0.20))
        min_forecast_h = 96
    if hero_h + metric_h > content_h - min_forecast_h:
        overflow = hero_h + metric_h - (content_h - min_forecast_h)
        hero_h = max(142, hero_h - overflow // 2)
        metric_h = max(78, metric_h - (overflow - overflow // 2))
    forecast_h = content_h - hero_h - metric_h

    hero_y0 = cy0
    hero_y1 = hero_y0 + hero_h
    metric_y0 = hero_y1
    metric_y1 = metric_y0 + metric_h
    forecast_y0 = metric_y1
    forecast_y1 = forecast_y0 + forecast_h

    # Reuse exact forecast column centers as anchor points for top-left city
    # and top-right current-weather icon, so both align with bottom columns.
    forecast_w = cx1 - cx0 + 1
    forecast_col_w = max(1, forecast_w // 3)
    forecast_col_centers: list[int] = []
    for col in range(3):
        col_x0 = cx0 + col * forecast_col_w
        col_x1 = cx1 if col == 2 else col_x0 + forecast_col_w
        forecast_col_centers.append(col_x0 + ((col_x1 - col_x0) // 2))

    draw.line((cx0, metric_y1, cx1, metric_y1), fill=ink, width=2)

    days, sel, current = _select_days(state)
    hi_raw = _metric(current, ("hi",))
    lo_raw = _metric(current, ("lo",))
    hi_val = _parse_number(hi_raw)
    lo_val = _parse_number(lo_raw)
    current_temp_raw = _metric(current, ("temp", "temperature", "current_temp", "current", "hi"))
    icon = str(_metric(current, ("icon",)) or "sun")

    feels_raw = _metric(current, ("feels_like", "feelsLike", "feels"))
    if feels_raw is None:
        feels_raw = current_temp_raw
    feels_val = _parse_number(feels_raw)
    if feels_val is None and hi_val is not None and lo_val is not None:
        feels_val = (hi_val + lo_val) / 2.0

    humidity = _format_percent(_metric(current, ("humidity",)))
    wind = _format_wind(_metric(current, ("wind_kmh", "windKmh", "wind", "wind_speed")))
    uv_raw = _metric(current, ("uv", "uv_index", "uvi"))
    uv_val = _parse_number(uv_raw)

    # 1) Hero block: portrait uses stacked icon+text, landscape keeps split columns.
    panel_w = cx1 - cx0 + 1
    city_text = str(getattr(state.model, "location", "") or "").strip()
    show_city = bool(city_text)
    feels_txt = f"Feels Like {_format_temp_with_unit(feels_val)}"
    temp_txt = _format_temp_with_unit(current_temp_raw)
    range_txt = f"H: {_format_temp(hi_raw)}  L: {_format_temp(lo_raw)}"

    if portrait_layout:
        text_xmin = cx0 + 10
        text_xmax = cx1 - 10
        text_w = max(120, text_xmax - text_xmin)
        text_cx = (text_xmin + text_xmax) // 2

        feels_font, feels_txt, feels_size = _fit_font_to_width(
            draw,
            fonts,
            body_key,
            feels_txt,
            max(16, int(body_base * 1.40)),
            13,
            text_w,
        )
        temp_font, temp_txt, temp_size = _fit_font_to_width(
            draw,
            fonts,
            body_focus_key,
            temp_txt,
            max(44, int(body_base * 4.10)),
            30,
            text_w,
        )
        range_font, range_txt, range_size = _fit_font_to_width(
            draw,
            fonts,
            body_key,
            range_txt,
            max(15, int(body_base * 1.30)),
            12,
            text_w,
        )
        feels_font = fonts.get(body_key, feels_size)
        range_font = fonts.get(body_key, range_size)
        _, feels_h = text_size(draw, feels_txt, feels_font)
        _, range_h = text_size(draw, range_txt, range_font)

        city_y = hero_y0 + 2
        if show_city:
            city_font, city_label, _ = _fit_font_full_text_to_width(
                draw,
                fonts,
                body_focus_key,
                city_text,
                max(16, int(body_base * 1.55)),
                max(9, int(theme.get("weather_city_min_font_size", 9) or 9)),
                max(80, text_w),
            )
            city_w, city_h = text_size(draw, city_label, city_font)
            draw.text((text_cx - (city_w // 2), city_y), city_label, font=city_font, fill=ink)
        else:
            city_h = 0

        hero_icon_size = max(58, min(104, int(min(panel_w * 0.26, hero_h * 0.30))))
        hero_icon_x = cx0 + (panel_w - hero_icon_size) // 2
        hero_icon_y = city_y + city_h + (18 if show_city else 8)
        max_icon_bottom = hero_y0 + int(hero_h * 0.56)
        if hero_icon_y + hero_icon_size > max_icon_bottom:
            hero_icon_size = max(50, max_icon_bottom - hero_icon_y)
            hero_icon_x = cx0 + (panel_w - hero_icon_size) // 2

        inner_top = hero_icon_y + hero_icon_size + 8
        inner_bottom = hero_y1 - 10
        while inner_bottom - inner_top < 48 and hero_icon_size > 48:
            hero_icon_size -= 4
            hero_icon_x = cx0 + (panel_w - hero_icon_size) // 2
            inner_top = hero_icon_y + hero_icon_size + 8

        feels_y = inner_top
        range_y = inner_bottom - range_h
        temp_top = feels_y + feels_h + 4
        temp_bottom = range_y - 6
        temp_track_h = max(28, temp_bottom - temp_top)
        while True:
            temp_font = fonts.get(body_focus_key, temp_size)
            _, temp_h = text_size(draw, temp_txt, temp_font)
            if temp_h <= temp_track_h or temp_size <= 28:
                break
            temp_size -= 1
        _, temp_h = text_size(draw, temp_txt, temp_font)
        temp_y = temp_top + max(0, (temp_track_h - temp_h) // 2)

        _draw_centered_text_clamped(draw, feels_txt, feels_font, text_cx, feels_y, text_xmin, text_xmax, ink)
        _draw_centered_text_clamped(draw, temp_txt, temp_font, text_cx, temp_y, text_xmin, text_xmax, ink)
        _draw_centered_text_clamped(draw, range_txt, range_font, text_cx, range_y, text_xmin, text_xmax, ink)
        _draw_weather_icon_pack(
            image,
            draw,
            theme,
            icon,
            hero_icon_x,
            hero_icon_y,
            size=hero_icon_size,
            size_h=None,
            ink=ink,
            stroke=max(3, int(hero_icon_size * 0.06)),
        )
    else:
        icon_box_w = max(96, min(124, int(panel_w * 0.16)))
        right_anchor_cx = forecast_col_centers[2]
        icon_x0 = right_anchor_cx - (icon_box_w // 2)
        icon_x1 = icon_x0 + icon_box_w
        if icon_x1 > cx1 - 2:
            shift = icon_x1 - (cx1 - 2)
            icon_x0 -= shift
            icon_x1 -= shift
        if icon_x0 < cx0 + 2:
            shift = (cx0 + 2) - icon_x0
            icon_x0 += shift
            icon_x1 += shift

        city_box_w = icon_box_w if show_city else 0
        left_anchor_cx = forecast_col_centers[0]
        city_box_x0 = (left_anchor_cx - (city_box_w // 2)) if show_city else cx0 + 6
        city_box_x1 = city_box_x0 + city_box_w
        if show_city and city_box_x0 < cx0 + 2:
            shift = (cx0 + 2) - city_box_x0
            city_box_x0 += shift
            city_box_x1 += shift
        if show_city and city_box_x1 > cx1 - 2:
            shift = city_box_x1 - (cx1 - 2)
            city_box_x0 -= shift
            city_box_x1 -= shift
        text_xmin = city_box_x1 + 12 if show_city else cx0 + 8
        text_xmax = icon_x0 - 12
        text_w = max(100, text_xmax - text_xmin)
        text_cx = (text_xmin + text_xmax) // 2

        feels_font, feels_txt, feels_size = _fit_font_to_width(
            draw,
            fonts,
            body_key,
            feels_txt,
            max(15, int(body_base * 1.45)),
            13,
            text_w,
        )
        temp_font, temp_txt, temp_size = _fit_font_to_width(
            draw,
            fonts,
            body_focus_key,
            temp_txt,
            max(42, int(body_base * 4.45)),
            32,
            text_w,
        )
        range_font, range_txt, range_size = _fit_font_to_width(
            draw,
            fonts,
            body_key,
            range_txt,
            max(15, int(body_base * 1.45)),
            12,
            text_w,
        )

        feels_font = fonts.get(body_key, feels_size)
        range_font = fonts.get(body_key, range_size)
        _, feels_h = text_size(draw, feels_txt, feels_font)
        _, range_h = text_size(draw, range_txt, range_font)

        inner_top = hero_y0 + 6
        inner_bottom = hero_y1 - 24
        feels_y = inner_top
        range_y = inner_bottom - range_h
        temp_top = feels_y + feels_h + 4
        temp_bottom = range_y - 8
        temp_track_h = max(40, temp_bottom - temp_top)

        while True:
            temp_font = fonts.get(body_focus_key, temp_size)
            _, temp_h = text_size(draw, temp_txt, temp_font)
            if temp_h <= temp_track_h or temp_size <= 32:
                break
            temp_size -= 1

        _, temp_h = text_size(draw, temp_txt, temp_font)
        temp_y = temp_top + max(0, (temp_track_h - temp_h) // 2)
        shift_up = min(2, max(0, feels_y - hero_y0 - 1))
        feels_y -= shift_up
        temp_y -= shift_up
        range_y -= shift_up

        _draw_centered_text_clamped(draw, feels_txt, feels_font, text_cx, feels_y, text_xmin, text_xmax, ink)
        _draw_centered_text_clamped(draw, temp_txt, temp_font, text_cx, temp_y, text_xmin, text_xmax, ink)
        _draw_centered_text_clamped(draw, range_txt, range_font, text_cx, range_y, text_xmin, text_xmax, ink)

        icon_box_h = max(70, hero_h - 32)
        hero_icon_size = max(62, min(92, icon_box_w - 10, icon_box_h))
        hero_icon_x = icon_x0 + (icon_box_w - hero_icon_size) // 2
        hero_icon_y = hero_y0 + (hero_h - hero_icon_size) // 2

        if show_city:
            city_frame_size = hero_icon_size
            city_frame_x0 = city_box_x0 + max(0, (city_box_w - city_frame_size) // 2)
            city_frame_y0 = hero_icon_y

            city_font, city_label, _ = _fit_font_full_text_to_width(
                draw,
                fonts,
                body_focus_key,
                city_text,
                max(18, int(body_base * 2.15)),
                max(4, int(theme.get("weather_city_min_font_size", 4) or 4)),
                max(24, city_frame_size - 8),
            )
            city_bb = draw.textbbox((0, 0), city_label, font=city_font)
            city_w = city_bb[2] - city_bb[0]
            city_h = city_bb[3] - city_bb[1]
            city_x = city_frame_x0 + max(0, (city_frame_size - city_w) // 2) - city_bb[0]
            city_y = city_frame_y0 + max(0, (city_frame_size - city_h) // 2) - city_bb[1]
            draw.text((city_x, city_y), city_label, font=city_font, fill=ink)

        _draw_weather_icon_pack(
            image,
            draw,
            theme,
            icon,
            hero_icon_x,
            hero_icon_y,
            size=hero_icon_size,
            size_h=None,
            ink=ink,
            stroke=max(3, int(hero_icon_size * 0.06)),
        )

    # 2) Metrics row: text only (icons removed by design).
    uv_index_txt = "--" if uv_val is None else str(int(round(uv_val)))

    metric_items = [
        (humidity, "Humidity"),
        (wind, "Wind"),
        (uv_index_txt, "UV Index"),
    ]

    metric_row_w = cx1 - cx0 + 1
    metric_col_w = max(1, metric_row_w // 3)

    for idx, (value_txt, label_txt) in enumerate(metric_items):
        x0 = cx0 + idx * metric_col_w
        x1 = cx1 if idx == 2 else x0 + metric_col_w
        col_w = x1 - x0
        text_w_limit = max(48, col_w - 20)

        value_font, value_txt, _ = _fit_font_to_width(
            draw,
            fonts,
            body_focus_key,
            value_txt,
            max(18, int(body_base * 1.55)),
            11,
            text_w_limit,
        )
        label_font, label_txt, _ = _fit_font_to_width(
            draw,
            fonts,
            body_key,
            label_txt,
            max(14, int(body_base * 1.15)),
            10,
            text_w_limit,
        )

        value_w, value_h = text_size(draw, value_txt, value_font)
        label_w, label_h = text_size(draw, label_txt, label_font)
        metric_line_gap = 8
        text_block_h = value_h + metric_line_gap + label_h
        text_top = metric_y0 + max(4, (metric_h - text_block_h) // 2)
        draw.text((x0 + (col_w - value_w) // 2, text_top), value_txt, font=value_font, fill=ink)
        draw.text(
            (x0 + (col_w - label_w) // 2, text_top + value_h + metric_line_gap),
            label_txt,
            font=label_font,
            fill=ink,
        )

    # 3) Forecast row: next three days with vertical separators.
    forecast_inner_top = forecast_y0 + 8
    forecast_bottom_pad = int(theme.get("weather_forecast_bottom_pad", 12) or 12)
    forecast_inner_bottom = forecast_y1 - max(6, forecast_bottom_pad)
    for i in (1, 2):
        vx = cx0 + i * forecast_col_w
        draw.line((vx, forecast_inner_top, vx, forecast_inner_bottom), fill=ink, width=1)

    indices = []
    if days:
        n = min(3, len(days))
        for i in range(n):
            if len(days) > 1:
                indices.append((sel + 1 + i) % len(days))
            else:
                indices.append(sel)

    for col in range(3):
        x0 = cx0 + col * forecast_col_w
        x1 = cx1 if col == 2 else x0 + forecast_col_w
        col_w = x1 - x0

        if col >= len(indices):
            placeholder = "--"
            ph_font = fonts.get(meta_key, max(16, meta_base + 4))
            pw, ph = text_size(draw, placeholder, ph_font)
            draw.text((x0 + (col_w - pw) // 2, forecast_inner_top + ((forecast_inner_bottom - forecast_inner_top - ph) // 2)), placeholder, font=ph_font, fill=muted)
            continue

        day = days[indices[col]]
        if col == 0 and len(days) > 1:
            if portrait_layout:
                day_label = str(theme.get("weather_tomorrow_label_short") or "TMR").upper()
            else:
                day_label = str(theme.get("weather_tomorrow_label") or "Tomorrow")
        else:
            raw_dow = str(getattr(day, "dow", "--")).strip()
            if portrait_layout and len(raw_dow) > 3:
                day_label = raw_dow[:3].upper()
            elif len(raw_dow) <= 3:
                day_label = (raw_dow or "--").upper()
            else:
                day_label = raw_dow.title()

        day_start = max(14, int(body_base * 1.45)) if portrait_layout else max(16, int(body_base * 1.75))
        day_min = 10 if portrait_layout else 12
        day_font, day_label, _ = _fit_font_to_width(
            draw,
            fonts,
            body_focus_key,
            day_label,
            day_start,
            day_min,
            max(48, col_w - (12 if portrait_layout else 20)),
        )

        if portrait_layout:
            hi_txt = _format_temp(getattr(day, "hi", None))
            lo_txt = _format_temp(getattr(day, "lo", None))
            temp_range = f"{hi_txt}/{lo_txt}"
            temp_font, _temp_full, temp_size = _fit_font_full_text_to_width(
                draw,
                fonts,
                body_key,
                temp_range,
                max(13, int(body_base * 1.12)),
                9,
                max(44, col_w - 12),
            )
            temp_font = fonts.get(body_key, temp_size)
            tw, _ = text_size(draw, temp_range, temp_font)
            if tw > max(44, col_w - 12):
                hi_raw = str(getattr(day, "hi", "--")).strip() or "--"
                lo_raw = str(getattr(day, "lo", "--")).strip() or "--"
                temp_range = f"{hi_raw}/{lo_raw}"
                temp_font, _temp_full, temp_size = _fit_font_full_text_to_width(
                    draw,
                    fonts,
                    body_key,
                    temp_range,
                    max(12, int(body_base * 1.05)),
                    8,
                    max(40, col_w - 10),
                )
                temp_font = fonts.get(body_key, temp_size)
        else:
            temp_range = f"H: {_format_temp(getattr(day, 'hi', None))}  L: {_format_temp(getattr(day, 'lo', None))}"
            temp_font, temp_range, _ = _fit_font_to_width(
                draw,
                fonts,
                body_key,
                temp_range,
                max(14, int(body_base * 1.35)),
                11,
                max(60, col_w - 20),
            )

        day_bb = draw.textbbox((0, 0), day_label, font=day_font)
        temp_bb = draw.textbbox((0, 0), temp_range, font=temp_font)
        day_w = day_bb[2] - day_bb[0]
        day_h = day_bb[3] - day_bb[1]
        temp_w = temp_bb[2] - temp_bb[0]

        # Place labels with bbox-aware anchors so descenders never get clipped at the bottom.
        day_y = (forecast_inner_top + 2) - day_bb[1]
        temp_bottom_limit = forecast_inner_bottom - 2
        temp_y = temp_bottom_limit - temp_bb[3]
        day_bottom = day_y + day_bb[3]
        temp_top = temp_y + temp_bb[1]
        icon_room = max(24, temp_top - (day_bottom + 8))
        icon_size = min(max(24, int(icon_room * 0.98)), max(34, int((forecast_inner_bottom - forecast_inner_top) * 0.34)))
        icon_scale_w, icon_scale_h = _forecast_icon_visual_scale(theme, getattr(day, "icon", "sun"))
        draw_icon_w = max(18, int(round(icon_size * icon_scale_w)))
        draw_icon_h = max(16, int(round(icon_size * icon_scale_h)))
        icon_box_x = x0 + (col_w - icon_size) // 2
        icon_box_y = day_bottom + max(6, (icon_room - icon_size) // 2)
        icon_x = icon_box_x + (icon_size - draw_icon_w) // 2
        icon_y = icon_box_y + (icon_size - draw_icon_h) // 2

        day_x = x0 + (col_w - day_w) // 2 - day_bb[0]
        temp_x = x0 + (col_w - temp_w) // 2 - temp_bb[0]
        draw.text((day_x, day_y), day_label, font=day_font, fill=ink)
        _draw_weather_icon_pack(
            image,
            draw,
            theme,
            getattr(day, "icon", "sun"),
            icon_x,
            icon_y,
            size=draw_icon_w,
            size_h=draw_icon_h,
            ink=ink,
            stroke=max(2, int(max(draw_icon_w, draw_icon_h) * 0.10)),
            thicken=False,
        )
        draw.text((temp_x, temp_y), temp_range, font=temp_font, fill=ink)
