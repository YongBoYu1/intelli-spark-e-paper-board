from datetime import datetime
import math
from PIL import ImageDraw

from app.shared.draw import (
    center_text,
    center_text_spaced,
    draw_text_centered,
    draw_text_centered_clamped,
    draw_battery,
    draw_text_spaced,
    draw_wifi,
    draw_weather_icon,
    text_size,
    text_width_spaced,
)
from app.ui.layout import compute_layout
from app.ui.widgets import draw_card, draw_reminder_item


def _format_date(now):
    day = str(now.day)
    return (now.strftime("%A, %b ") + day).upper()


def _mix_color(a, b, t):
    """
    Linear blend a->b by t in [0..1]. Works for int (1-bit) and RGB tuples.
    """
    t = max(0.0, min(1.0, float(t)))
    if isinstance(a, int) and isinstance(b, int):
        return int(round(a * (1.0 - t) + b * t))
    if isinstance(a, tuple) and isinstance(b, tuple) and len(a) == 3 and len(b) == 3:
        return tuple(int(round(a[i] * (1.0 - t) + b[i] * t)) for i in range(3))
    return b


def _fit_font(draw, fonts, key, max_size, max_width, min_size=10):
    size = max_size
    while size >= min_size:
        font = fonts.get(key, size)
        width = text_size(draw, "88:88", font)[0]
        if width <= max_width:
            return font
        size -= 2
    return fonts.get(key, min_size)


def _fit_text_font(draw, fonts, key, max_size, text, max_width, min_size=10):
    size = max_size
    while size >= min_size:
        font = fonts.get(key, size)
        width = text_size(draw, text, font)[0]
        if width <= max_width:
            return font
        size -= 2
    return fonts.get(key, min_size)


def render_home(image, data, fonts, theme=None, overlay=None):
    theme = theme or {}
    overlay = overlay or {}
    ink = theme.get("ink", 0)
    card = theme.get("card", 255)
    muted = theme.get("muted", ink)
    border = theme.get("border", ink)
    line_thickness = theme.get("line_thickness")
    border_width = theme.get("border_width", line_thickness if line_thickness is not None else 2)
    divider_width = theme.get("divider_width", border_width)
    weather_divider_width = theme.get("weather_divider_width", border_width)
    underline_width = theme.get("underline_width", divider_width)
    item_border_width = theme.get("item_border_width", border_width)
    checkbox_border_width = theme.get("checkbox_border_width", border_width)
    icon_stroke = theme.get("icon_stroke", border_width)
    wifi_stroke = theme.get("wifi_stroke", border_width)
    battery_stroke = theme.get("battery_stroke", border_width)
    card_radius = theme.get("card_radius", 12)
    item_radius = theme.get("item_radius", 12)
    pill_radius = theme.get("pill_radius", 11)

    if image.mode == "RGB":
        def to_rgb(c):
            if isinstance(c, int):
                return (c, c, c)
            return c

        ink = to_rgb(ink)
        card = to_rgb(card)
        muted = to_rgb(muted)
        border = to_rgb(border)

    draw = ImageDraw.Draw(image)
    layout = compute_layout(image.width, image.height)

    left_card = (
        layout.left_x,
        layout.top_y,
        layout.left_x + layout.left_w,
        layout.top_y + layout.left_card_h,
    )
    weather_card = (
        layout.left_x,
        layout.top_y + layout.left_card_h + layout.gap,
        layout.left_x + layout.left_w,
        layout.top_y + layout.left_card_h + layout.gap + layout.weather_h,
    )
    right_card = (
        layout.right_x,
        layout.top_y,
        layout.right_x + layout.right_w,
        layout.top_y + layout.right_card_h,
    )

    draw_card(draw, left_card, radius=card_radius, outline=border, width=border_width, fill=card)
    draw_card(draw, weather_card, radius=card_radius, outline=border, width=border_width, fill=card)
    draw_card(draw, right_card, radius=card_radius, outline=border, width=border_width, fill=card)

    _draw_left_panel(
        draw,
        left_card,
        weather_card,
        data,
        fonts,
        ink,
        muted,
        card,
        theme,
        border,
        border_width,
        divider_width,
        weather_divider_width,
        underline_width,
        icon_stroke,
        wifi_stroke,
        battery_stroke,
        pill_radius,
    )
    _draw_right_panel(
        draw,
        right_card,
        data,
        fonts,
        ink,
        muted,
        card,
        theme,
        border,
        divider_width,
        item_border_width,
        checkbox_border_width,
        item_radius,
        overlay,
        card_radius,
    )


def _draw_left_panel(
    draw,
    left_card,
    weather_card,
    data,
    fonts,
    ink,
    muted,
    card,
    theme,
    border,
    border_width,
    divider_width,
    weather_divider_width,
    underline_width,
    icon_stroke,
    wifi_stroke,
    battery_stroke,
    pill_radius,
):
    x0, y0, x1, y1 = left_card
    padding = 20

    # Status icons
    status_y = y0 + padding
    draw_wifi(draw, x0 + padding, status_y, size=18, ink=ink, stroke=wifi_stroke)
    battery_level = data.get("battery", 84)
    battery_x = x1 - padding - 24
    draw_battery(
        draw,
        battery_x,
        status_y + 2,
        w=24,
        h=12,
        level=battery_level,
        ink=border,
        fill=card,
        stroke=battery_stroke,
    )
    percent_text = f"{battery_level}%"
    percent_font = fonts.get("inter_regular", 12)
    pt_w, pt_h = text_size(draw, percent_text, percent_font)
    draw.text((battery_x - pt_w - 6, status_y + 2), percent_text, font=percent_font, fill=ink)

    now = datetime.now()

    # TSX parity: the clock panel is a widget slot (CLOCK or TIMER) with a voice overlay.
    voice_active = bool(data.get("voice_active"))
    widget_mode = str(data.get("widget_mode") or "clock").lower()
    timer_seconds = int(data.get("timer_seconds") or 0)
    timer_running = bool(data.get("timer_running"))

    if widget_mode == "timer":
        mm = max(0, timer_seconds) // 60
        ss = max(0, timer_seconds) % 60
        time_str = f"{mm:02d}:{ss:02d}"
        date_str = "TIMER" if timer_running else "PAUSED"
    elif voice_active:
        time_str = ""
        date_str = "LISTENING..."
    else:
        time_str = data.get("time") or now.strftime("%H:%M")
        date_str = data.get("date") or _format_date(now)

    time_font_key = theme.get("time_font", "jet_extrabold")
    date_font_key = theme.get("date_font", "inter_bold")
    loc_font_key = theme.get("loc_font", "inter_bold")
    time_size = theme.get("time_size", 112)
    time_autofit = theme.get("time_autofit", True)
    if time_autofit:
        time_font = _fit_text_font(draw, fonts, time_font_key, time_size, time_str, x1 - x0 - 36, min_size=60)
    else:
        time_font = fonts.get(time_font_key, time_size)
    date_font = fonts.get(date_font_key, 22)
    loc_font = fonts.get(loc_font_key, 12)

    clock_center_x = x0 + (x1 - x0) / 2
    clock_center_y = y0 + (y1 - y0) / 2 + theme.get("time_center_y", -20)
    if voice_active:
        # Minimal mic glyph (robust in 1-bit mode).
        mic_r = 26
        cx = int(clock_center_x)
        cy = int(clock_center_y) - 10
        draw.ellipse((cx - mic_r, cy - mic_r, cx + mic_r, cy + mic_r), outline=ink, width=3)
        draw.line((cx, cy + mic_r, cx, cy + mic_r + 18), fill=ink, width=3)
        draw.line((cx - 18, cy + mic_r + 18, cx + 18, cy + mic_r + 18), fill=ink, width=3)
        time_h = mic_r * 2
    else:
        time_w, time_h = text_size(draw, time_str, time_font)
        draw_text_centered_clamped(
            draw,
            time_str,
            clock_center_x,
            clock_center_y,
            time_font,
            xmin=x0 + 20,
            xmax=x1 - 20,
            fill=ink,
        )

    line_y = clock_center_y + time_h / 2 + theme.get("underline_offset", 8)
    if not voice_active:
        line_w = 70
        draw.line(
            (clock_center_x - line_w / 2, line_y, clock_center_x + line_w / 2, line_y),
            fill=border,
            width=underline_width,
        )

    date_w = text_width_spaced(draw, date_str, date_font, spacing=2)
    date_h = text_size(draw, date_str, date_font)[1]
    date_x = x0 + (x1 - x0 - date_w) // 2
    date_y = line_y + 12
    draw_text_spaced(draw, date_str, date_x, date_y, date_font, spacing=2, fill=ink)

    location = data.get("location", "")
    if location and not (voice_active or widget_mode == "timer"):
        pill_w = max(86, text_size(draw, location, loc_font)[0] + 18)
        pill_h = 22
        pill_x = x0 + (x1 - x0 - pill_w) // 2
        pill_y = date_y + date_h + 10
        draw.rounded_rectangle(
            (pill_x, pill_y, pill_x + pill_w, pill_y + pill_h),
            radius=pill_radius,
            outline=border,
            width=border_width,
            fill=card,
        )
        center_text_spaced(
            draw,
            location.upper(),
            loc_font,
            (pill_x, pill_y, pill_x + pill_w, pill_y + pill_h),
            spacing=1,
            fill=ink,
        )

    _draw_weather_strip(draw, weather_card, data, fonts, border, weather_divider_width, icon_stroke, ink, muted, theme)


def _draw_weather_strip(draw, weather_card, data, fonts, border, divider_width, icon_stroke, ink, muted, theme):
    x0, y0, x1, y1 = weather_card
    items = data.get("weather", [])
    if not items:
        return

    day_font = fonts.get(theme.get("weather_day_font", "inter_semibold"), theme.get("weather_day_size", 12))
    hi_font = fonts.get(theme.get("weather_hi_font", "inter_semibold"), theme.get("weather_hi_size", 12))
    lo_font = fonts.get(theme.get("weather_lo_font", "inter_regular"), theme.get("weather_lo_size", 10))
    icon_size = theme.get("weather_icon_size", 36)
    day_top = theme.get("weather_day_top", 10)
    icon_top = theme.get("weather_icon_top", 34)
    temp_bottom = theme.get("weather_temp_bottom", 10)
    temp_gap = theme.get("weather_temp_gap", 2)
    hi_off_y = theme.get("weather_hi_offset_y", 0)
    lo_off_y = theme.get("weather_lo_offset_y", 0)

    cell_w = (x1 - x0) // len(items)
    for idx, item in enumerate(items):
        cx0 = x0 + idx * cell_w
        cx1 = cx0 + cell_w
        cx = cx0 + cell_w / 2
        if idx > 0:
            draw.line((cx0, y0 + 8, cx0, y1 - 8), fill=border, width=divider_width)
        dow = item.get("dow", "")
        if dow:
            dow_w, dow_h = text_size(draw, dow, day_font)
            draw.text((cx - dow_w / 2, y0 + day_top), dow, font=day_font, fill=ink)

        icon = item.get("icon", "sun")
        icon_x = cx - icon_size / 2
        draw_weather_icon(draw, icon, icon_x, y0 + icon_top, size=icon_size, ink=ink, stroke=icon_stroke)

        hi = item.get("hi", "")
        lo = item.get("lo", "")
        temp_hi = f"{hi}°" if hi != "" and hi is not None else ""
        temp_lo = f"{lo}°" if lo != "" and lo is not None else ""

        lo_w, lo_h = text_size(draw, temp_lo, lo_font) if temp_lo else (0, 0)
        hi_w, hi_h = text_size(draw, temp_hi, hi_font) if temp_hi else (0, 0)

        base_lo_y = y1 - temp_bottom - lo_h
        base_hi_y = base_lo_y - temp_gap - hi_h
        lo_y = base_lo_y + lo_off_y
        hi_y = base_hi_y + hi_off_y
        if temp_hi:
            draw.text((cx - hi_w / 2, hi_y), temp_hi, font=hi_font, fill=ink)
        if temp_lo:
            draw.text((cx - lo_w / 2, lo_y), temp_lo, font=lo_font, fill=muted)


def _draw_right_panel(
    draw,
    right_card,
    data,
    fonts,
    ink,
    muted,
    card,
    theme,
    border,
    divider_width,
    item_border_width,
    checkbox_border_width,
    item_radius,
    overlay,
    card_radius,
):
    x0, y0, x1, y1 = right_card
    padding = 12

    title_font_key = theme.get("title_font", "inter_black")
    meta_font_key = theme.get("meta_font", "inter_regular")
    item_font_key = theme.get("item_font", "inter_semibold")
    right_font_key = theme.get("right_font", "inter_regular")

    title_font = fonts.get(title_font_key, theme.get("title_size", 24))
    meta_font = fonts.get(meta_font_key, theme.get("meta_size", 11))
    item_font = fonts.get(item_font_key, theme.get("item_size", 18))
    right_font = fonts.get(right_font_key, theme.get("right_size", 12))

    header_y = y0 + 18
    draw.text((x0 + 20, header_y), "REMINDERS", font=title_font, fill=ink)

    reminders = data.get("reminders", [])
    # If caller doesn't provide reminder_total, treat reminders list as the full dataset.
    total = int(data.get("reminder_total", len(reminders)) or 0)
    due = int(
        data.get(
            "reminder_due",
            sum(1 for r in reminders if r.get("time") or r.get("due")),
        )
        or 0
    )

    # Derive page count from the total so it follows data (1/1 when everything fits).
    items_per_page = int(theme.get("items_per_page", 4) or 4)
    items_per_page = max(1, items_per_page)
    page_count = max(1, int(math.ceil(max(0, total) / float(items_per_page))))
    page = int(data.get("page", 1) or 1)
    page = max(1, min(page, page_count))

    page_text = f"PAGE {page}/{page_count}"
    page_font = fonts.get(theme.get("page_font", "inter_semibold"), theme.get("page_size", theme.get("meta_size", 11)))
    pt_w, pt_h = text_size(draw, page_text, page_font)
    page_fill = theme.get("page_color")
    if page_fill is None:
        page_fill = ink if isinstance(ink, int) else _mix_color(muted, ink, 0.60)
    draw.text((x1 - padding - pt_w, header_y + 2), page_text, font=page_font, fill=page_fill)

    rotate_text = "ROTATE FOR MORE"
    if page_count > 1:
        rt_w, rt_h = text_size(draw, rotate_text, meta_font)
        rotate_fill = theme.get("rotate_color")
        if rotate_fill is None:
            rotate_fill = muted if isinstance(muted, int) else _mix_color(muted, card, 0.55)
        draw.text((x1 - padding - rt_w, header_y + 18), rotate_text, font=meta_font, fill=rotate_fill)

    divider_y = theme.get("divider_y", y0 + 72)
    draw.line((x0 + padding, divider_y, x1 - padding, divider_y), fill=border, width=divider_width)

    stats = f"{total} ITEMS  •  {due} DUE"
    draw.text((x0 + 20, header_y + theme.get("stats_offset", 26)), stats, font=meta_font, fill=muted)

    list_top = theme.get("list_top", divider_y + 14)
    item_h = theme.get("item_h", 72)
    gap = theme.get("item_gap", 10)
    start = (page - 1) * items_per_page
    page_items = reminders[start : start + items_per_page]

    focus = overlay.get("focus") or {}
    focus_kind = focus.get("kind")
    focus_idx = focus.get("index")
    focus_width = int(overlay.get("focus_width", 4) or 4)

    for idx, item in enumerate(page_items):
        box = (
            x0 + padding,
            list_top + idx * (item_h + gap),
            x0 + padding + 458,
            list_top + idx * (item_h + gap) + item_h,
        )

        right_text = item.get("time") or item.get("due", "")
        draw_reminder_item(
            draw,
            box,
            item.get("title", ""),
            right_text,
            item_font,
            right_font,
            ink=ink,
            fill=card,
            border_width=item_border_width,
            divider_width=divider_width,
            checkbox_border_width=checkbox_border_width,
            radius=item_radius,
        )

        if focus_kind == "task" and focus_idx == (start + idx):
            # Draw focus ring on top of the existing border.
            draw.rounded_rectangle(
                box,
                radius=item_radius,
                outline=ink,
                width=focus_width,
                fill=None,
            )

    # Focus ring for header sections (clock / weather) is drawn by caller (render_app),
    # because home.py doesn't know the global focused_index mapping.
