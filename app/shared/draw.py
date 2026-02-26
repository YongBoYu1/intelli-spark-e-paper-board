from PIL import ImageDraw


def _snap_px(value) -> int:
    try:
        return int(round(float(value)))
    except Exception:
        return 0


def _glyph_advance(draw, ch, font) -> int:
    try:
        adv = draw.textlength(ch, font=font)
    except Exception:
        adv = text_size(draw, ch, font)[0]
    return max(0, _snap_px(adv))


def text_size(draw, text, font):
    bbox = draw.textbbox((0, 0), text, font=font)
    return (bbox[2] - bbox[0], bbox[3] - bbox[1])


def center_text(draw, text, font, box, fill=0):
    x0, y0, x1, y1 = box
    w, h = text_size(draw, text, font)
    x = x0 + (x1 - x0 - w) // 2
    y = y0 + (y1 - y0 - h) // 2
    draw.text((x, y), text, font=font, fill=fill)


def text_width_spaced(draw, text, font, spacing=1):
    if not text:
        return 0
    step = _snap_px(spacing)
    width = 0
    for idx, ch in enumerate(text):
        ch_w = _glyph_advance(draw, ch, font)
        width += ch_w
        if idx < len(text) - 1:
            width += step
    return width


def draw_text_spaced(draw, text, x, y, font, spacing=1, fill=0):
    cur_x = _snap_px(x)
    y = _snap_px(y)
    step = _snap_px(spacing)
    for idx, ch in enumerate(text):
        draw.text((cur_x, y), ch, font=font, fill=fill)
        ch_w = _glyph_advance(draw, ch, font)
        cur_x += ch_w + (step if idx < len(text) - 1 else 0)


def center_text_spaced(draw, text, font, box, spacing=1, fill=0):
    x0, y0, x1, y1 = box
    w = text_width_spaced(draw, text, font, spacing=spacing)
    h = text_size(draw, text, font)[1]
    x = _snap_px(x0 + (x1 - x0 - w) / 2)
    y = _snap_px(y0 + (y1 - y0 - h) / 2)
    draw_text_spaced(draw, text, x, y, font, spacing=spacing, fill=fill)


def draw_text_centered(draw, text, cx, cy, font, fill=0):
    bbox = draw.textbbox((0, 0), text, font=font)
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]
    x = cx - w / 2 - bbox[0]
    y = cy - h / 2 - bbox[1]
    draw.text((_snap_px(x), _snap_px(y)), text, font=font, fill=fill)


def draw_text_centered_clamped(draw, text, cx, cy, font, xmin, xmax, fill=0):
    bbox = draw.textbbox((0, 0), text, font=font)
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]
    x = cx - w / 2 - bbox[0]
    left = x + bbox[0]
    right = x + bbox[2]
    if left < xmin:
        x += xmin - left
    elif right > xmax:
        x -= right - xmax
    y = cy - h / 2 - bbox[1]
    draw.text((_snap_px(x), _snap_px(y)), text, font=font, fill=fill)


def truncate_text(draw, text, font, max_width):
    if not text:
        return text
    try:
        width = draw.textlength(text, font=font)
    except Exception:
        width = text_size(draw, text, font)[0]
    if width <= max_width:
        return text
    ellipsis = "..."
    try:
        ell_w = draw.textlength(ellipsis, font=font)
    except Exception:
        ell_w = text_size(draw, ellipsis, font)[0]
    max_width = max(0, max_width - ell_w)
    trimmed = text
    while trimmed:
        try:
            cur_w = draw.textlength(trimmed, font=font)
        except Exception:
            cur_w = text_size(draw, trimmed, font)[0]
        if cur_w <= max_width:
            break
        trimmed = trimmed[:-1]
    return (trimmed + ellipsis) if trimmed else ellipsis


def rounded_rect(draw, box, radius=16, outline=0, width=2, fill=255):
    x0, y0, x1, y1 = box
    draw.rounded_rectangle((x0, y0, x1, y1), radius=radius, outline=outline, width=width, fill=fill)


def _normalize_color(color, reference):
    if isinstance(color, int) and isinstance(reference, tuple):
        return (color, color, color)
    return color


def draw_checkbox(draw, x, y, size, checked=False, outline=0, fill=255, check_fill=0, width=2):
    outline = _normalize_color(outline, fill)
    fill = _normalize_color(fill, outline)
    check_fill = _normalize_color(check_fill, outline)
    draw.rectangle((x, y, x + size, y + size), outline=outline, fill=fill, width=width)
    if checked:
        inset = 4
        draw.rectangle((x + inset, y + inset, x + size - inset, y + size - inset), fill=check_fill)


def draw_wifi(draw, x, y, size=18, ink=0, stroke=2):
    # Prefer the curated icon module if available.
    try:
        from assets.icons import wifi as _wifi
        _wifi.draw(draw, (x, y), size, color=ink, stroke_width=stroke, bars=2)
        return
    except Exception:
        pass

    # Fallback: simple 3-arc wifi icon
    for i in range(3):
        r = size - i * 5
        bbox = (x + (size - r), y + (size - r), x + (size + r), y + (size + r))
        draw.arc(bbox, start=200, end=340, fill=ink, width=stroke)
    draw.ellipse((x + size - 2, y + size + 2, x + size + 2, y + size + 6), fill=ink)


def draw_battery(draw, x, y, w=28, h=14, level=84, ink=0, fill=255, stroke=2):
    ink = _normalize_color(ink, fill)
    fill = _normalize_color(fill, ink)
    # Prefer the curated icon module if available.
    try:
        from assets.icons import battery as _battery
        _battery.draw(
            draw,
            (x, y),
            max(w, h),
            w=w,
            h=h,
            level=max(0, min(int(level), 100)) / 100.0,
            color=ink,
            stroke_width=stroke,
            bg=fill,
            show_level=False,  # % text already conveys level in the UI
        )
        return
    except Exception:
        pass

    # Fallback battery outline + level fill
    draw.rectangle((x, y, x + w, y + h), outline=ink, width=stroke, fill=fill)
    cap_w = 4
    draw.rectangle((x + w, y + h * 0.3, x + w + cap_w, y + h * 0.7), fill=ink)
    inner_w = int((w - 4) * max(0, min(level, 100)) / 100)
    draw.rectangle((x + 2, y + 2, x + 2 + inner_w, y + h - 2), fill=ink)


def draw_weather_icon(draw, icon, x, y, size=34, ink=0, stroke=2):
    icon = (icon or "").strip().lower().replace("-", "_").replace(" ", "_")

    # Prefer the curated icon set in assets/icons if available.
    # Keep a small fallback (below) so preview/hardware render doesn't hard-fail.
    try:
        from assets.icons import cloud as _cloud
        from assets.icons import partly_cloudy as _partly_cloudy
        from assets.icons import rain as _rain
        from assets.icons import sleet as _sleet
        from assets.icons import snow as _snow
        from assets.icons import storm as _storm
        from assets.icons import sun as _sun

        icon_map = {
            "sun": _sun.draw,
            "clear": _sun.draw,
            "cloud": _cloud.draw,
            "cloudy": _cloud.draw,
            "overcast": _cloud.draw,
            "rain": _rain.draw,
            "drizzle": _rain.draw,
            "storm": _storm.draw,
            "thunder": _storm.draw,
            "thunderstorm": _storm.draw,
            "partly_cloudy": _partly_cloudy.draw,
            "partly": _partly_cloudy.draw,
            "snow": _snow.draw,
            "sleet": _sleet.draw,
            "hail": _sleet.draw,
        }

        fn = icon_map.get(icon)
        if fn is None:
            fn = _cloud.draw
        fn(draw, (x, y), size, color=ink, stroke_width=stroke)
        return
    except Exception:
        pass

    # Fallback icons (simple primitives)
    if icon == "sun":
        draw.ellipse((x, y, x + size, y + size), outline=ink, width=stroke)
        cx = x + size // 2
        cy = y + size // 2
        draw.line((cx, y - 6, cx, y + 4), fill=ink, width=stroke)
        draw.line((cx, y + size - 4, cx, y + size + 6), fill=ink, width=stroke)
        draw.line((x - 6, cy, x + 4, cy), fill=ink, width=stroke)
        draw.line((x + size - 4, cy, x + size + 6, cy), fill=ink, width=stroke)
    elif icon == "cloud":
        draw.ellipse((x, y + 8, x + size * 0.7, y + size * 0.8), outline=ink, width=stroke)
        draw.ellipse((x + size * 0.3, y, x + size, y + size * 0.7), outline=ink, width=stroke)
    elif icon == "rain":
        draw_weather_icon(draw, "cloud", x, y, size, ink=ink, stroke=stroke)
        draw.line((x + 6, y + size * 0.8, x + 6, y + size + 10), fill=ink, width=stroke)
        draw.line((x + 18, y + size * 0.8, x + 18, y + size + 10), fill=ink, width=stroke)
    elif icon == "storm":
        draw_weather_icon(draw, "cloud", x, y, size, ink=ink, stroke=stroke)
        draw.polygon(
            [
                (x + size * 0.45, y + size * 0.8),
                (x + size * 0.65, y + size * 0.8),
                (x + size * 0.5, y + size + 10),
            ],
            fill=ink,
        )
    else:
        draw.ellipse((x, y, x + size, y + size), outline=ink, width=stroke)
