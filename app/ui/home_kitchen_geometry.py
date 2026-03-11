from __future__ import annotations

Rect = tuple[int, int, int, int]
ClosedBox = tuple[int, int, int, int]


def _approx_font_height(size: int, *, scale: float = 0.82, minimum: int = 8) -> int:
    return max(int(minimum), int(round(max(1, int(size)) * float(scale))))


def closed_box_to_rect(
    box: ClosedBox | None,
    *,
    outline_width: int = 1,
    extra_pad: int = 0,
) -> Rect | None:
    if box is None:
        return None
    x0, y0, x1, y1 = box
    stroke_pad = max(0, int(outline_width) - 1)
    pad = max(0, int(extra_pad)) + stroke_pad
    return (x0 - pad, y0 - pad, x1 + pad + 1, y1 + pad + 1)


def home_landscape_header_focus_box(width: int, height: int, *, kind: str) -> ClosedBox | None:
    w = max(1, int(width))
    h = max(1, int(height))
    margin = 18
    ox0, oy0, ox1, oy1 = margin, margin, max(margin + 1, w - margin), max(margin + 1, h - margin)
    split_x = ox0 + int((ox1 - ox0) * 0.60)
    left_pad = 24
    top_y = oy0 + left_pad
    lx0 = ox0 + left_pad
    lx1 = split_x - left_pad
    weather_col_w = 142
    weather_right = lx1 - 2
    weather_left = weather_right - weather_col_w
    focus_pad_x = 6
    focus_pad_y = 4

    weather_top = top_y - 2
    city_h = _approx_font_height(13, scale=0.84, minimum=10)
    temp_h = _approx_font_height(66, scale=0.78, minimum=46)
    desc_h = _approx_font_height(15, scale=0.86, minimum=12)
    hum_h = _approx_font_height(15, scale=0.86, minimum=12)
    icon_size = max(12, int(round(34 * 1.35)))
    city_y = max(oy0 + 4, weather_top - city_h - 6)
    desc_y = weather_top + temp_h + 16 + 5
    icon_y = desc_y + desc_h + 10
    humidity_bottom = icon_y + icon_size + 8 + hum_h

    if kind == "clock":
        x0 = lx0 - focus_pad_x
        x1 = max(x0 + 16, weather_left - 7)
        y0 = max(oy0 + 2, top_y - 28)
        y1 = min(oy1, top_y + 142)
        return (x0, y0, x1, y1)

    if kind == "weather":
        weather_bottom = max(
            top_y + _approx_font_height(70, scale=0.78, minimum=54) + 13 + _approx_font_height(15, scale=0.86, minimum=12) + 11 + _approx_font_height(18, scale=0.86, minimum=14),
            city_y + city_h,
            desc_y + desc_h,
            humidity_bottom,
        )
        x0 = weather_left - focus_pad_x
        x1 = weather_right + focus_pad_x
        y0 = max(oy0 + 2, weather_top - focus_pad_y)
        y1 = min(oy1, weather_bottom + focus_pad_y)
        return (x0, y0, x1, y1)

    return None


def _home_portrait_header_metrics(src_w: int, src_h: int) -> dict[str, int]:
    margin = 8
    pad = 8
    sec_gap = 4
    header_h_ratio = 0.21
    memo_h_ratio = 0.25
    min_list_h = 220
    header_col_gap = 16
    weather_col_w = 156

    x0, y0, x1, y1 = margin, margin, src_w - margin, src_h - margin
    inner_h = max(1, y1 - y0)
    header_h = max(160, int(inner_h * header_h_ratio))
    memo_h = max(188, int(inner_h * memo_h_ratio))
    if header_h + memo_h + sec_gap * 2 + min_list_h > inner_h:
        overflow = header_h + memo_h + sec_gap * 2 + min_list_h - inner_h
        memo_h = max(150, memo_h - overflow)

    header_y0 = y0
    header_y1 = min(y1 - sec_gap * 2 - min_list_h, header_y0 + header_h)

    hx0, hx1 = x0 + pad, x1 - pad
    hy0 = header_y0 + pad
    weather_w = min(weather_col_w, max(120, int((hx1 - hx0) * 0.36)))
    left_x0 = hx0
    left_x1 = max(left_x0 + 120, hx1 - weather_w - header_col_gap)
    weather_x0 = left_x1 + header_col_gap
    weather_x1 = hx1
    return {
        "src_w": src_w,
        "src_h": src_h,
        "pad": pad,
        "header_y0": header_y0,
        "header_y1": header_y1,
        "hy0": hy0,
        "left_x0": left_x0,
        "left_x1": left_x1,
        "weather_x0": weather_x0,
        "weather_x1": weather_x1,
    }


def home_portrait_header_focus_source_box(
    src_width: int,
    src_height: int,
    *,
    kind: str,
    has_weather_data: bool,
    has_humidity: bool,
) -> ClosedBox | None:
    metrics = _home_portrait_header_metrics(max(1, int(src_width)), max(1, int(src_height)))
    pad = metrics["pad"]
    header_y0 = metrics["header_y0"]
    header_y1 = metrics["header_y1"]
    hy0 = metrics["hy0"]
    left_x0 = metrics["left_x0"]
    left_x1 = metrics["left_x1"]
    weather_x0 = metrics["weather_x0"]
    weather_x1 = metrics["weather_x1"]

    focus_pad_x = 6
    focus_pad_y = 4
    time_y = max(-4, hy0 - 22)
    time_h = _approx_font_height(112, scale=1.0, minimum=84)
    week_y = time_y + time_h + 4
    week_h = _approx_font_height(15, scale=0.86, minimum=12)
    date_y = week_y + week_h + 8
    date_h = _approx_font_height(19, scale=0.96, minimum=18)

    if kind == "clock":
        x0 = left_x0 - focus_pad_x
        x1 = left_x1 + focus_pad_x
        y0 = max(header_y0 + pad, time_y - focus_pad_y)
        y1 = min(header_y1 - pad, date_y + date_h + focus_pad_y + 4)
        return (x0, y0, x1, y1)

    if kind != "weather":
        return None

    weather_top = max(4, time_y - 4)
    weather_right = weather_x1 - 18
    temp_h = _approx_font_height(58, scale=0.78, minimum=42)
    icon_size = 34
    desc_h = _approx_font_height(14, scale=0.86, minimum=12)
    hum_h = _approx_font_height(14, scale=0.86, minimum=12)
    icon_y = weather_top + temp_h + 13
    desc_y = icon_y + icon_size + 11

    if has_weather_data:
        weather_bottom = max(weather_top + temp_h, icon_y + icon_size, desc_y + desc_h)
        if has_humidity:
            hum_y = desc_y + desc_h + 8
            weather_bottom = max(weather_bottom, hum_y + hum_h)
    else:
        placeholder_y = weather_top + 60
        weather_bottom = max(weather_top + temp_h, placeholder_y + desc_h)

    x0 = weather_x0 - focus_pad_x
    x1 = weather_right + focus_pad_x
    y0 = max(header_y0 + pad, weather_top - focus_pad_y)
    y1 = min(header_y1 - pad, weather_bottom + focus_pad_y)
    return (x0, y0, x1, y1)


def home_portrait_header_focus_source_box_for_panel(
    width: int,
    height: int,
    *,
    kind: str,
    has_weather_data: bool,
    has_humidity: bool,
) -> ClosedBox | None:
    return home_portrait_header_focus_source_box(
        max(1, int(height)),
        max(1, int(width)),
        kind=kind,
        has_weather_data=has_weather_data,
        has_humidity=has_humidity,
    )
