from __future__ import annotations

from datetime import datetime
import time

from PIL import ImageDraw

from app.core.kitchen_queue import kitchen_queue_theme_key, kitchen_visible_task_indices
from app.core.state import AppState
from app.shared.draw import draw_text_spaced, draw_weather_icon, rounded_rect, text_size, text_width_spaced, truncate_text


def _to_rgb(c):
    if isinstance(c, int):
        return (c, c, c)
    if isinstance(c, list) and len(c) == 3:
        return (int(c[0]), int(c[1]), int(c[2]))
    return c


def _gray_like(value: int, ref):
    g = max(0, min(255, int(value)))
    if isinstance(ref, tuple):
        return (g, g, g)
    return g


def _format_memo_posted(timestamp, theme: dict) -> str:
    """Format memo timestamp safely; invalid inputs should not break rendering."""
    if timestamp is None:
        return ""
    try:
        ts = float(timestamp)
    except Exception:
        return ""

    # Guard against NaN/Inf.
    if ts != ts or ts in (float("inf"), float("-inf")):
        return ""

    # Normalize common non-second epochs (ms/us/ns) to seconds.
    for _ in range(3):
        if abs(ts) <= 1e11:
            break
        ts /= 1000.0

    try:
        dt = datetime.fromtimestamp(ts)
    except Exception:
        return ""

    if bool(theme.get("b_log_compact_day_time", True)):
        # Keep weekday abbreviation stable for e-paper labels across locales.
        dow = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")[dt.weekday()]
        return f"{dow} {dt.strftime('%H:%M')}"

    fmt = str(theme.get("b_log_datetime_format") or "%a %H:%M")
    try:
        return dt.strftime(fmt)
    except Exception:
        return dt.strftime("%a %H:%M")


def _theme(theme: dict) -> dict:
    t = dict(theme or {})

    # Layout
    t.setdefault("b_margin", 18)
    t.setdefault("b_outer_radius", 12)
    t.setdefault("b_outer_border", 0)
    t.setdefault("b_show_outer_frame", False)
    t.setdefault("b_split_ratio", 0.60)
    t.setdefault("b_divider_w", 2)
    t.setdefault("b_show_focus_ring", False)

    # Left block
    t.setdefault("b_left_pad", 24)
    t.setdefault("b_time_size", 84)
    t.setdefault("b_time_min_size", 70)
    t.setdefault("b_time_display_scale", 1.30)
    t.setdefault("b_time_display_x_offset", 0)
    t.setdefault("b_time_display_y_offset", -24)
    t.setdefault("b_time_weather_gap", 14)
    t.setdefault("b_time_weekday_gap", 13)
    t.setdefault("b_weekday_size", 13)
    t.setdefault("b_weekday_spacing", 4)
    t.setdefault("b_weekday_date_gap", 11)
    t.setdefault("b_date_size", 16)
    t.setdefault("b_date_gray", 80)
    t.setdefault("b_temp_size", 66)
    t.setdefault("b_weather_desc_size", 15)
    t.setdefault("b_weather_desc_spacing", 1)
    t.setdefault("b_weather_col_w", 142)
    t.setdefault("b_weather_top", -2)
    t.setdefault("b_weather_desc_gap", 16)
    t.setdefault("b_weather_desc_offset_y", 5)
    t.setdefault("b_weather_icon_gap", 10)
    t.setdefault("b_weather_icon_size", 34)
    t.setdefault("b_weather_icon_stroke", 3)
    t.setdefault("b_weather_humidity_size", 15)
    t.setdefault("b_weather_humidity_spacing", 1)
    t.setdefault("b_weather_humidity_gap", 8)
    t.setdefault("b_weather_humidity_prefix", "HUM")
    t.setdefault("b_show_weather_humidity", True)
    t.setdefault("b_show_weather_humidity_placeholder", True)
    t.setdefault("b_header_gap", 28)
    t.setdefault("b_header_rule_w", 0)
    t.setdefault("b_left_micro_size", 16)
    t.setdefault("b_left_micro_spacing", 3)
    t.setdefault("b_family_name_size", 14)
    t.setdefault("b_family_name_spacing", 1)
    t.setdefault("b_family_name_gap", 16)
    t.setdefault("b_family_names_right_inset", 14)
    t.setdefault("b_family_row_gap", 8)
    t.setdefault("b_family_rule_gap", 8)
    t.setdefault("b_family_active_underline_gap", 3)
    t.setdefault("b_family_active_underline_w", 2)
    t.setdefault("b_quote_size", 34)
    t.setdefault("b_quote_min_size", 25)
    t.setdefault("b_quote_lh", 1.18)
    t.setdefault("b_quote_top_gap", 14)
    t.setdefault("b_quote_max_w_ratio", 0.92)
    t.setdefault("b_quote_short_wrap_factor", 0.88)
    t.setdefault("b_quote_display_wrap_factor", 0.92)
    t.setdefault("b_quote_target_lines", 2)
    t.setdefault("b_quote_balance_lines", 2)
    t.setdefault("b_quote_balance_ratio", 0.20)
    t.setdefault("b_quote_balance_max", 24)
    t.setdefault("b_quote_bottom_gap", 14)
    t.setdefault("b_posted_after_quote_gap", 10)
    t.setdefault("b_posted_max_gap_from_quote", 44)
    t.setdefault("b_posted_size", 16)
    t.setdefault("b_posted_size_panel_min", 17)
    t.setdefault("b_log_compact_day_time", True)
    t.setdefault("b_log_datetime_format", "%a %H:%M")
    t.setdefault("b_posted_prefix", "-")
    t.setdefault("b_posted_right_inset", 6)
    t.setdefault("b_left_bottom_pad", 22)
    t.setdefault("b_posted_rule_w", 0)
    t.setdefault("b_posted_rule_gap", 0)
    t.setdefault("b_author_size", 9)
    t.setdefault("b_author_row_offset_y", 1)
    t.setdefault("b_author_max_tags", 4)

    # Right block
    t.setdefault("b_right_pad", 22)
    t.setdefault("b_inventory_title_size", 13)
    t.setdefault("b_inventory_title_spacing", 2)
    t.setdefault("b_inventory_item_size", 17)
    t.setdefault("b_inventory_row_h", 36)
    t.setdefault("b_badge_size", 11)
    t.setdefault("b_badge_px", 6)
    t.setdefault("b_badge_py", 2)
    t.setdefault("b_badge_style", "text")
    t.setdefault("b_badge_text_px", 0)
    t.setdefault("b_badge_text_py", 0)
    t.setdefault("b_badge_text_spacing", 0)
    t.setdefault("b_badge_text_min_w", 20)
    t.setdefault("b_badge_focus_px", 4)
    t.setdefault("b_badge_focus_py", 1)
    t.setdefault("b_badge_focus_radius", 2)
    t.setdefault("b_badge_radius", 3)
    t.setdefault("b_badge_border_w", 1)
    t.setdefault("b_badge_max_w", 126)
    t.setdefault("b_badge_min_size", 9)
    t.setdefault("b_badge_min_w", 44)
    t.setdefault("b_inventory_title_badge_gap", 10)
    t.setdefault("b_inventory_min_title_w", 104)
    t.setdefault("b_inventory_max_rows", 3)
    t.setdefault("b_inventory_header_gap", 34)
    t.setdefault("b_mid_split_ratio", 0.50)
    t.setdefault("b_shopping_title_size", 13)
    t.setdefault("b_shopping_title_spacing", 1)
    t.setdefault("b_shopping_item_size", 17)
    t.setdefault("b_shopping_max_rows", 5)
    t.setdefault("b_shopping_row_h", 36)
    t.setdefault("b_shopping_header_gap", 24)
    t.setdefault("b_shop_section_rule_w", 1)
    t.setdefault("b_shop_section_rule_left_gap", 0)
    t.setdefault("b_shop_section_rule_right_gap", 16)
    t.setdefault("b_shop_header_rule_gap", 6)
    t.setdefault("b_shop_header_line_after_title_gap", 9)
    t.setdefault("b_inv_shop_min_gap", 14)
    t.setdefault("b_shop_text_left_pad", 2)
    t.setdefault("b_right_focus_style", "row_box")
    t.setdefault("b_right_focus_pad_x", 6)
    t.setdefault("b_right_focus_pad_y", 3)
    t.setdefault("b_right_focus_right_trim", 2)
    t.setdefault("b_right_focus_radius", 5)
    t.setdefault("b_right_focus_w", 1)
    t.setdefault("b_right_focus_rail_w", 3)
    t.setdefault("b_right_focus_rail_gap", 6)
    t.setdefault("b_right_focus_rail_vpad", 5)
    t.setdefault("b_shop_checkbox_size", 14)
    t.setdefault("b_shop_checkbox_radius", 3)
    t.setdefault("b_shop_checkbox_w", 2)
    t.setdefault("b_bottom_pad", 12)

    # Shared color tone in RGB mode (ignored in 1-bit)
    t.setdefault("b_muted_gray", 110)
    t.setdefault("b_subtle_gray", 205)
    # Render text with 1-bit font mode by default to avoid anti-aliased
    # weight wobble after panel quantization.
    t.setdefault("b_text_antialias", False)

    return t


def _font_px(v) -> int:
    return max(1, int(round(float(v))))


def _weather_word(icon_name: str) -> str:
    icon = (icon_name or "sun").strip().lower().replace("-", "_")
    mapping = {
        "sun": "SUNNY",
        "clear": "CLEAR",
        "cloud": "CLOUDY",
        "cloudy": "CLOUDY",
        "overcast": "OVERCAST",
        "rain": "RAINY",
        "drizzle": "DRIZZLE",
        "storm": "STORM",
        "thunder": "STORM",
        "snow": "SNOW",
        "mist": "MIST",
        "fog": "FOG",
        "wind": "WINDY",
    }
    if icon in mapping:
        return mapping[icon]
    if icon.startswith("partly"):
        return "PARTLY"
    parts = [p for p in icon.split("_") if p]
    if not parts:
        return "SUNNY"
    return mapping.get(parts[0], parts[0].upper())


def _group_tasks(state: AppState):
    fridge = [r for r in state.model.reminders if (r.category or "") == "fridge"]
    shop = [r for r in state.model.reminders if (r.category or "") != "fridge"]

    # Keep incomplete first, then completed (stable within each group).
    fridge = sorted(fridge, key=lambda r: (r.completed,))
    shop = sorted(shop, key=lambda r: (r.completed,))
    return fridge, shop


def _badge_variants(text: str) -> list[str]:
    raw = (text or "").strip().upper()
    if not raw:
        return [""]
    variants = [raw]

    normalized = raw.replace(":", " ").replace("-", " ")
    normalized = " ".join(normalized.split())
    if normalized and normalized != raw:
        variants.append(normalized)

    compact_words = normalized
    compact_replacements = (
        ("EXPIRES", "EXP"),
        ("EXPIRY", "EXP"),
        ("EXP", "EXP"),
        ("DAYS", "D"),
        ("DAY", "D"),
        ("ADDED", "ADDED"),
        ("YESTERDAY", "YDAY"),
        ("TONIGHT", "TNITE"),
        ("TODAY", "TDY"),
    )
    for old, new in compact_replacements:
        compact_words = compact_words.replace(old, new)
    compact_words = " ".join(compact_words.split())
    if compact_words and compact_words not in variants:
        variants.append(compact_words)

    # Aggressive short forms for very tight widths on panel.
    short = compact_words.replace("ADDED ", "ADD ").replace("ADDED", "ADD")
    short = short.replace("YESTERDAY", "YDAY")
    short = short.replace("TONIGHT", "TNITE")
    short = short.replace("TODAY", "TDY")
    short = " ".join(short.split())
    if short and short not in variants:
        variants.append(short)

    compact = raw
    replacements = (
        ("ADDED", "ADD"),
        ("YESTERDAY", "YDAY"),
        ("EXP:", "EXP"),
        (" DAYS", "D"),
        (" DAY", "D"),
        ("TODAY", "TDY"),
        ("TONIGHT", "TNITE"),
    )
    for old, new in replacements:
        compact = compact.replace(old, new)
    if compact != raw:
        variants.append(compact)

    # De-dup while preserving order.
    uniq = []
    seen = set()
    for v in variants:
        if v not in seen:
            seen.add(v)
            uniq.append(v)
    return uniq


def _fit_badge_text(draw, fonts, text: str, max_text_w: int, base_size: int, min_size: int):
    variants = _badge_variants(text)
    for size in range(base_size, min_size - 1, -1):
        f = fonts.get("inter_bold", _font_px(size))
        for candidate in variants:
            if text_size(draw, candidate, f)[0] <= max_text_w:
                return candidate, f
    f_min = fonts.get("inter_bold", _font_px(min_size))
    return truncate_text(draw, variants[-1], f_min, max_text_w), f_min


def render_home_kitchen(image, state: AppState, fonts, theme: dict) -> None:
    t = _theme(theme)
    draw = ImageDraw.Draw(image)
    if not bool(t.get("b_text_antialias", False)):
        try:
            draw.fontmode = "1"
        except Exception:
            pass
    w, h = image.size

    card = theme.get("card", (252, 252, 252))
    ink = theme.get("ink", (17, 17, 17))
    if image.mode == "RGB":
        card = _to_rgb(card)
        ink = _to_rgb(ink)
    else:
        if not isinstance(card, int):
            card = 255
        if not isinstance(ink, int):
            ink = 0

    muted = _gray_like(int(t["b_muted_gray"]), ink)
    date_muted = _gray_like(int(t["b_date_gray"]), ink)
    subtle = _gray_like(int(t["b_subtle_gray"]), ink)

    draw.rectangle((0, 0, w, h), fill=card)

    # Outer frame and split
    m = int(t["b_margin"])
    ox0, oy0, ox1, oy1 = m, m, w - m, h - m
    draw.rectangle((ox0, oy0, ox1, oy1), fill=card)
    if bool(t.get("b_show_outer_frame")) and int(t.get("b_outer_border", 0)) > 0:
        rounded_rect(
            draw,
            (ox0, oy0, ox1, oy1),
            radius=int(t["b_outer_radius"]),
            outline=ink,
            width=int(t["b_outer_border"]),
            fill=None,
        )

    split_x = ox0 + int((ox1 - ox0) * float(t["b_split_ratio"]))
    draw.line((split_x, oy0, split_x, oy1), fill=ink, width=int(t["b_divider_w"]))

    # Focus on left panel (index 0)
    focus_idx = int(state.ui.focused_index or 0)
    if bool(t.get("b_show_focus_ring")) and not state.ui.idle and focus_idx == 0:
        rounded_rect(
            draw,
            (ox0 + 2, oy0 + 2, split_x - 2, oy1 - 2),
            radius=max(2, int(t["b_outer_radius"]) - 2),
            outline=ink,
            width=3,
            fill=None,
        )

    # Fonts
    f_time = fonts.get("inter_black", _font_px(t["b_time_size"]))
    f_weekday = fonts.get("inter_semibold", _font_px(t["b_weekday_size"]))
    f_date = fonts.get("inter_bold", _font_px(t["b_date_size"]))
    f_temp = fonts.get("inter_black", _font_px(t["b_temp_size"]))
    f_weather_desc = fonts.get("jet_bold", _font_px(t["b_weather_desc_size"]))
    f_weather_humidity = fonts.get("jet_bold", _font_px(t["b_weather_humidity_size"]))
    f_micro = fonts.get("jet_extrabold", _font_px(t["b_left_micro_size"]))
    f_family_name = fonts.get("jet_bold", _font_px(t["b_family_name_size"]))
    # Use a slightly heavier serif to survive 1-bit panel quantization.
    f_quote = fonts.get("playfair_bold", _font_px(t["b_quote_size"]))
    posted_size = int(t["b_posted_size"])
    # Slightly boost the LOG stamp in panel-like (non-RGB) render paths.
    if image.mode != "RGB":
        posted_size = max(posted_size, int(t.get("b_posted_size_panel_min", 13)))
    f_posted = fonts.get("jet_extrabold", _font_px(posted_size))

    f_inv_title = fonts.get("inter_bold", _font_px(t["b_inventory_title_size"]))
    f_inv_item = fonts.get("inter_semibold", _font_px(t["b_inventory_item_size"]))
    f_inv_item_focus = fonts.get("inter_black", _font_px(t["b_inventory_item_size"]))
    f_badge = fonts.get("inter_bold", _font_px(t["b_badge_size"]))
    f_shop_title = fonts.get("inter_bold", _font_px(t["b_shopping_title_size"]))
    f_shop_item = fonts.get("inter_semibold", _font_px(t["b_shopping_item_size"]))
    f_shop_item_focus = fonts.get("inter_bold", _font_px(t["b_shopping_item_size"]))

    # ---------------- Left Panel ----------------
    lx0, lx1 = ox0 + int(t["b_left_pad"]), split_x - int(t["b_left_pad"])
    top_y = oy0 + int(t["b_left_pad"])

    now = datetime.now()
    time_str = now.strftime("%H:%M")
    weekday = now.strftime("%A").upper()
    try:
        month_day = now.strftime("%B %-d, %Y")
    except Exception:
        month_day = now.strftime("%B %d, %Y")

    weather_col_w = int(t["b_weather_col_w"])
    weather_right = lx1 - 2
    weather_left = weather_right - weather_col_w

    # Keep clock clear of the weather stack on the right.
    time_font_size = int(t["b_time_size"])
    time_min_size = int(t["b_time_min_size"])
    while time_font_size > time_min_size:
        f_probe = fonts.get("inter_black", _font_px(time_font_size))
        tw_probe, _ = text_size(draw, time_str, f_probe)
        if tw_probe <= (weather_left - lx0 - int(t["b_time_weather_gap"])):
            break
        time_font_size -= 2
    f_time = fonts.get("inter_black", _font_px(time_font_size))

    # Keep downstream text anchors stable: weekday/date continue to flow from the
    # legacy clock baseline, while the visible clock can be shifted and enlarged.
    time_flow_box = draw.textbbox((lx0, top_y), time_str, font=f_time)

    clock_x = lx0 + int(t.get("b_time_display_x_offset", -10))
    clock_y = top_y + int(t.get("b_time_display_y_offset", -12))
    display_scale = max(1.0, float(t.get("b_time_display_scale", 1.18)))
    display_size = max(time_font_size, int(round(time_font_size * display_scale)))
    display_font = fonts.get("inter_black", _font_px(display_size))
    while display_size > time_font_size:
        dw, _ = text_size(draw, time_str, display_font)
        if dw <= (weather_left - clock_x - int(t["b_time_weather_gap"])):
            break
        display_size -= 2
        display_font = fonts.get("inter_black", _font_px(display_size))

    draw.text((clock_x, clock_y), time_str, font=display_font, fill=ink)

    wy = time_flow_box[3] + int(t["b_time_weekday_gap"])
    w_spacing = int(t["b_weekday_spacing"])
    draw_text_spaced(draw, weekday, lx0, wy, f_weekday, spacing=w_spacing, fill=ink)
    ww = text_width_spaced(draw, weekday, f_weekday, spacing=w_spacing)
    wh = text_size(draw, "Ag", f_weekday)[1]

    dy = wy + wh + int(t["b_weekday_date_gap"])
    draw.text((lx0, dy), month_day, font=f_date, fill=date_muted)
    _, dh = text_size(draw, month_day, f_date)

    weather_bottom = dy + dh
    if state.model.weather:
        w0 = state.model.weather[0]
        temp_str = f"{int(w0.hi)}°"
        temp_w, temp_h = text_size(draw, temp_str, f_temp)
        icon_size = int(t["b_weather_icon_size"])

        temp_x = weather_right - temp_w
        temp_y = top_y + int(t["b_weather_top"])
        draw.text((temp_x, temp_y), temp_str, font=f_temp, fill=ink)

        desc = _weather_word(getattr(w0, "icon", "sun"))
        dsw = text_width_spaced(draw, desc, f_weather_desc, spacing=int(t["b_weather_desc_spacing"]))
        _, dh2 = text_size(draw, desc, f_weather_desc)
        desc_y = temp_y + temp_h + int(t["b_weather_desc_gap"]) + int(t.get("b_weather_desc_offset_y", 0))
        desc_x = weather_right - dsw
        draw_text_spaced(
            draw,
            desc,
            desc_x,
            desc_y,
            f_weather_desc,
            spacing=int(t["b_weather_desc_spacing"]),
            fill=ink,
        )

        icon_y = desc_y + dh2 + int(t["b_weather_icon_gap"])
        icon_center_x = desc_x + dsw // 2
        icon_x = int(icon_center_x - icon_size / 2)
        icon_x = max(weather_left, min(weather_right - icon_size, icon_x))
        draw_weather_icon(
            draw,
            w0.icon,
            icon_x,
            icon_y,
            size=icon_size,
            ink=ink,
            stroke=int(t.get("b_weather_icon_stroke", 3)),
        )

        humidity = getattr(w0, "humidity", None)
        humidity_text = ""
        show_humidity = bool(t.get("b_show_weather_humidity", False))
        if show_humidity and humidity is not None:
            try:
                humidity_text = f"{str(t['b_weather_humidity_prefix']).upper()} {int(humidity)}%"
            except Exception:
                humidity_text = ""
        elif show_humidity and bool(t.get("b_show_weather_humidity_placeholder", False)):
            humidity_text = f"{str(t['b_weather_humidity_prefix']).upper()} --%"

        humidity_bottom = icon_y + icon_size
        if humidity_text:
            humidity_y = humidity_bottom + int(t["b_weather_humidity_gap"])
            hsw = text_width_spaced(draw, humidity_text, f_weather_humidity, spacing=int(t["b_weather_humidity_spacing"]))
            _, hsh = text_size(draw, humidity_text, f_weather_humidity)
            humidity_x = weather_right - hsw
            draw_text_spaced(
                draw,
                humidity_text,
                humidity_x,
                humidity_y,
                f_weather_humidity,
                spacing=int(t["b_weather_humidity_spacing"]),
                fill=muted,
            )
            humidity_bottom = humidity_y + hsh

        weather_bottom = max(weather_bottom, desc_y + dh2, humidity_bottom)

    header_rule_y = weather_bottom + int(t["b_header_gap"])
    header_rule_w = int(t["b_header_rule_w"])
    if header_rule_w > 0:
        draw.line((lx0, header_rule_y, lx1, header_rule_y), fill=ink, width=header_rule_w)

    label_y = header_rule_y + int(t["b_family_row_gap"])
    draw_text_spaced(
        draw,
        "FAMILY BOARD",
        lx0,
        label_y,
        f_micro,
        spacing=int(t["b_left_micro_spacing"]),
        fill=muted,
    )

    memos = state.model.memos or []
    memo_idx = int(state.ui.memo_index or 0)
    memo = memos[memo_idx % len(memos)] if memos else None

    # Family members on the same row as the section title.
    active_author = (memo.author if memo else "MOM").upper()
    authors = []
    if active_author:
        authors.append(active_author)
    for m in memos:
        a = (m.author or "").strip().upper()
        if not a or a in authors:
            continue
        authors.append(a)
    max_tags = max(1, int(t["b_author_max_tags"]))
    authors = authors[:max_tags]

    row_y = label_y + int(t["b_author_row_offset_y"])
    name_spacing = int(t["b_family_name_spacing"])
    name_gap = int(t["b_family_name_gap"])
    underline_gap = int(t["b_family_active_underline_gap"])
    underline_w = int(t["b_family_active_underline_w"])

    labels = []
    row_total = 0
    family_w = text_width_spaced(draw, "FAMILY BOARD", f_micro, spacing=int(t["b_left_micro_spacing"]))
    max_row_w = max(64, lx1 - (lx0 + family_w + 22))
    for a in authors:
        tw = text_width_spaced(draw, a, f_family_name, spacing=name_spacing)
        extra = (name_gap if labels else 0) + tw
        if row_total + extra > max_row_w:
            break
        labels.append((a, tw))
        row_total += extra

    row_x = lx1 - row_total - int(t.get("b_family_names_right_inset", 0))
    min_row_x = lx0 + family_w + 14
    if row_x < min_row_x:
        row_x = min_row_x
    cx = row_x
    name_h = text_size(draw, "Ag", f_family_name)[1]
    for i, (a, tw) in enumerate(labels):
        is_active = i == 0
        name_fill = ink
        draw_text_spaced(draw, a, cx, row_y, f_family_name, spacing=name_spacing, fill=name_fill)
        if is_active:
            uy = row_y + name_h + underline_gap
            draw.line((cx, uy, cx + tw, uy), fill=ink, width=underline_w)
        cx += tw + name_gap

    posted = _format_memo_posted((memo.timestamp if memo else None), t)
    posted_h = text_size(draw, "Ag", f_posted)[1]
    posted_max_y = oy1 - int(t["b_left_bottom_pad"]) - posted_h

    meta_row_bottom = label_y + text_size(draw, "Ag", f_micro)[1]
    if labels:
        meta_row_bottom = max(meta_row_bottom, row_y + name_h + underline_gap + underline_w)
    family_rule_y = meta_row_bottom + int(t["b_family_rule_gap"])
    draw.line((lx0, family_rule_y, lx1, family_rule_y), fill=ink, width=2)

    quote_y_base = family_rule_y + int(t["b_quote_top_gap"])
    quote = (memo.text.strip() if memo and memo.text else "No messages.")

    def _wrap_lines(text: str, width: int, quote_font):
        words = text.split(" ")
        out = []
        cur = ""
        for wd in words:
            nxt = (cur + " " + wd).strip()
            if not cur or text_size(draw, nxt, quote_font)[0] <= width:
                cur = nxt
            else:
                out.append(cur)
                cur = wd
        if cur:
            out.append(cur)
        return out

    max_quote_w = max(140, int((lx1 - lx0) * float(t["b_quote_max_w_ratio"])))
    quote_bottom = posted_max_y - int(t["b_quote_bottom_gap"])

    quote_size = int(t["b_quote_size"])
    quote_min_size = int(t.get("b_quote_min_size", 20))
    target_lines = max(2, int(t.get("b_quote_target_lines", 3)))
    quote_font = f_quote
    rendered_lines = []
    qlh = 1

    while quote_size >= quote_min_size:
        quote_font = fonts.get("playfair_bold", _font_px(quote_size))
        qh = text_size(draw, "Ag", quote_font)[1]
        qlh = max(1, int(qh * float(t["b_quote_lh"])))
        max_quote_lines = max(1, (quote_bottom - quote_y_base) // max(1, qlh))

        lines = _wrap_lines(quote, max_quote_w, quote_font)
        # Short messages look too tiny/empty on panel; force a display-width wrap pass.
        if len(lines) < target_lines and len(quote) >= 14:
            lines_tight = _wrap_lines(
                quote,
                max(110, int(max_quote_w * float(t["b_quote_display_wrap_factor"]))),
                quote_font,
            )
            if len(lines_tight) > len(lines):
                lines = lines_tight
            elif len(lines) == 1:
                lines_short = _wrap_lines(
                    quote,
                    max(120, int(max_quote_w * float(t["b_quote_short_wrap_factor"]))),
                    quote_font,
                )
                if len(lines_short) > len(lines):
                    lines = lines_short

        if len(lines) <= max_quote_lines:
            rendered_lines = lines
            break
        quote_size -= 1

    if not rendered_lines:
        # Fallback to minimum readable state when text is very long.
        quote_font = fonts.get("playfair_bold", _font_px(quote_min_size))
        qh = text_size(draw, "Ag", quote_font)[1]
        qlh = max(1, int(qh * float(t["b_quote_lh"])))
        max_quote_lines = max(1, (quote_bottom - quote_y_base) // max(1, qlh))
        rendered_lines = _wrap_lines(quote, max_quote_w, quote_font)[:max_quote_lines]

    quote_h = len(rendered_lines) * qlh
    quote_y = quote_y_base
    if len(rendered_lines) <= int(t.get("b_quote_balance_lines", 2)):
        nominal_gap = int(t.get("b_posted_after_quote_gap", 10))
        spare = posted_max_y - (quote_y_base + quote_h + nominal_gap)
        if spare > 0:
            shift = int(spare * float(t.get("b_quote_balance_ratio", 0.5)))
            shift = min(int(t.get("b_quote_balance_max", 64)), shift)
            if shift > 0:
                quote_y += shift

    for i, ln in enumerate(rendered_lines):
        draw.text((lx0, quote_y + i * qlh), ln, font=quote_font, fill=ink)

    quote_end_y = quote_y + quote_h
    posted_min_y = quote_end_y + int(t.get("b_posted_after_quote_gap", 10))
    posted_cap_y = quote_end_y + int(t.get("b_posted_max_gap_from_quote", 60))
    posted_text_y = min(posted_max_y, posted_cap_y)
    if posted_text_y < posted_min_y:
        posted_text_y = min(posted_max_y, posted_min_y)
    posted_prefix = str(t.get("b_posted_prefix") or "-").strip() or "-"
    posted_label_raw = f"{posted_prefix} {posted}" if posted else ""
    posted_label = truncate_text(draw, posted_label_raw, f_posted, max(40, lx1 - lx0 - 12)) if posted_label_raw else ""
    if posted_label:
        posted_w = text_size(draw, posted_label, f_posted)[0]
        posted_x = max(lx0, lx1 - int(t.get("b_posted_right_inset", 6)) - posted_w)
        draw.text((posted_x, posted_text_y), posted_label, font=f_posted, fill=ink)

    # ---------------- Right Panel ----------------
    rx0 = split_x + 1
    rp = int(t["b_right_pad"])
    inner_x0 = rx0 + rp
    inner_x1 = ox1 - rp

    mid_y = oy0 + int((oy1 - oy0) * float(t["b_mid_split_ratio"]))

    # Focus lookup by task id (incomplete order from reducer)
    focus_rid = _kitchen_focus_rid(state, focus_idx, t)
    rendered_focus_rids: list[str] = []

    fridge, shop = _group_tasks(state)

    # [ARTISTIC POLISH] Inventory Header
    inv_y = oy0 + max(8, rp - 6)

    inv_title_spacing = int(t.get("b_inventory_title_spacing", 1))
    draw_text_spaced(draw, "INVENTORY", inner_x0, inv_y, f_inv_title, spacing=inv_title_spacing, fill=ink)

    fridge_due = sum(1 for r in fridge if not r.completed)
    if fridge_due > 0:
        cnt = str(fridge_due)
        cw = text_width_spaced(draw, cnt, f_inv_title, spacing=inv_title_spacing)
        draw_text_spaced(draw, cnt, inner_x1 - cw, inv_y, f_inv_title, spacing=inv_title_spacing, fill=ink)

    inv_row_h = int(t["b_inventory_row_h"]) + 4
    y = inv_y + int(t["b_inventory_header_gap"])
    right_focus_style = str(t.get("b_right_focus_style", "row_box")).strip().lower()
    focus_pad_x = int(t.get("b_right_focus_pad_x", 6))
    focus_pad_y = int(t.get("b_right_focus_pad_y", 3))
    focus_right_trim = int(t.get("b_right_focus_right_trim", 2))
    focus_radius = int(t.get("b_right_focus_radius", 5))
    focus_w = max(1, int(t.get("b_right_focus_w", 1)))

    inv_max_rows = max(1, int(t.get("b_inventory_max_rows", 4)))
    for item in fridge[:inv_max_rows]:
        if y + inv_row_h > mid_y - 8:
            break
        is_focus = (not state.ui.idle) and (focus_rid == item.rid and not item.completed)
        if not item.completed:
            rendered_focus_rids.append(item.rid)

        text_fill = ink 
        badge_text = ink
        badge_fill = card
        badge_outline = ink

        if is_focus:
            if right_focus_style == "rail":
                rail_w = int(t.get("b_right_focus_rail_w", 3))
                rail_gap = int(t.get("b_right_focus_rail_gap", 6))
                rail_vpad = int(t.get("b_right_focus_rail_vpad", 5))
                rx1 = inner_x0 - rail_gap
                rx0 = rx1 - rail_w
                ry0 = y + rail_vpad
                ry1 = y + inv_row_h - rail_vpad
                if ry1 > ry0:
                    draw.rectangle((rx0, ry0, rx1, ry1), fill=ink)
            else:
                fx0 = inner_x0 - focus_pad_x
                fx1 = inner_x1 + focus_pad_x - focus_right_trim
                fy0 = y + focus_pad_y
                fy1 = y + inv_row_h - focus_pad_y
                if fy1 > fy0 and fx1 > fx0:
                    rounded_rect(
                        draw,
                        (fx0, fy0, fx1, fy1),
                        radius=max(0, min(focus_radius, (fy1 - fy0) // 2)),
                        outline=ink,
                        width=focus_w,
                        fill=None,
                    )

        badge_text_raw = (item.right or ("OUT" if item.completed else "STOCKED")).upper()
        badge_style = str(t.get("b_badge_style", "text")).strip().lower()
        text_style = badge_style in ("text", "text_focus_invert")
        badge_px = int(t["b_badge_px"]) if not text_style else int(t.get("b_badge_text_px", 0))
        badge_py = int(t["b_badge_py"]) if not text_style else int(t.get("b_badge_text_py", 0))
        badge_text_spacing = int(t.get("b_badge_text_spacing", -1))
        row_w = inner_x1 - inner_x0
        title_gap = int(t.get("b_inventory_title_badge_gap", 10))
        min_title_w = int(t.get("b_inventory_min_title_w", 104))
        badge_min_w = int(t.get("b_badge_min_w", 44))
        if text_style:
            badge_min_w = int(t.get("b_badge_text_min_w", 20))
        max_badge_w = min(int(t["b_badge_max_w"]), max(badge_min_w, row_w - 72))

        # Dynamic budget: protect minimum title width first, then allocate badge.
        badge_budget_w = max(
            badge_min_w,
            min(max_badge_w, row_w - title_gap - min_title_w),
        )
        badge_text_fit, f_badge_fit = _fit_badge_text(
            draw,
            fonts,
            badge_text_raw,
            max(20, badge_budget_w - badge_px * 2),
            int(t["b_badge_size"]),
            int(t.get("b_badge_min_size", 9)),
        )
        bw = int(round(text_width_spaced(draw, badge_text_fit, f_badge_fit, spacing=badge_text_spacing)))
        bh = text_size(draw, badge_text_fit, f_badge_fit)[1]
        bx1 = inner_x1
        bx0 = bx1 - (bw + badge_px * 2)
        min_bx0 = inner_x0 + (badge_min_w if not text_style else 0)
        if bx0 < min_bx0:
            bx0 = min_bx0

        by0 = y + (inv_row_h - (bh + badge_py * 2)) // 2
        by1 = by0 + bh + badge_py * 2

        title_max_w = max(56, (bx0 - title_gap) - inner_x0)
        if title_max_w < min_title_w:
            # Re-fit badge tighter to preserve minimum title readability.
            rebudget_w = max(badge_min_w, row_w - title_gap - min_title_w)
            badge_text_fit, f_badge_fit = _fit_badge_text(
                draw,
                fonts,
                badge_text_raw,
                max(20, rebudget_w - badge_px * 2),
                int(t["b_badge_size"]),
                int(t.get("b_badge_min_size", 9)),
            )
            bw = int(round(text_width_spaced(draw, badge_text_fit, f_badge_fit, spacing=badge_text_spacing)))
            bh = text_size(draw, badge_text_fit, f_badge_fit)[1]
            bx0 = bx1 - (bw + badge_px * 2)
            if bx0 < min_bx0:
                bx0 = min_bx0
            by0 = y + (inv_row_h - (bh + badge_py * 2)) // 2
            by1 = by0 + bh + badge_py * 2
            title_max_w = max(56, (bx0 - title_gap) - inner_x0)

        title = truncate_text(draw, item.title, f_inv_item, title_max_w)
        
        title_font = f_inv_item_focus if is_focus else f_inv_item
        th = text_size(draw, "Ag", title_font)[1]
        ty = y + (inv_row_h - th) // 2
        draw.text((inner_x0, ty), title, font=title_font, fill=text_fill)

        if text_style:
            # Default e-ink style: status is plain text (no persistent box).
            # Optional focus treatment only on selected row.
            if badge_style == "text_focus_invert" and is_focus:
                fx = max(1, int(t.get("b_badge_focus_px", 4)))
                fy = max(0, int(t.get("b_badge_focus_py", 1)))
                fbx0, fby0 = bx0 - fx, by0 - fy
                fbx1, fby1 = bx1 + fx, by1 + fy
                fr = max(0, int(t.get("b_badge_focus_radius", 2)))
                fr = min(fr, max(0, (fby1 - fby0) // 2))
                rounded_rect(
                    draw,
                    (fbx0, fby0, fbx1, fby1),
                    radius=fr,
                    outline=ink,
                    width=1,
                    fill=ink,
                )
                draw_text_spaced(
                    draw,
                    badge_text_fit,
                    bx0,
                    by0,
                    f_badge_fit,
                    spacing=badge_text_spacing,
                    fill=card,
                )
            else:
                draw_text_spaced(
                    draw,
                    badge_text_fit,
                    bx0,
                    by0,
                    f_badge_fit,
                    spacing=badge_text_spacing,
                    fill=ink,
                )
        else:
            # Legacy chip styles for A/B compare.
            if badge_style == "invert":
                badge_fill = ink
                badge_text = card
                badge_outline = ink
            elif badge_style == "focus_invert" and is_focus:
                badge_fill = ink
                badge_text = card
                badge_outline = ink

            badge_radius = max(0, int(t.get("b_badge_radius", 3)))
            badge_radius = min(badge_radius, max(0, (by1 - by0) // 2))
            rounded_rect(
                draw,
                (bx0, by0, bx1, by1),
                radius=badge_radius,
                outline=badge_outline,
                width=max(1, int(t.get("b_badge_border_w", 1))),
                fill=badge_fill,
            )

            draw_text_spaced(
                draw,
                badge_text_fit,
                bx0 + badge_px,
                by0 + badge_py,
                f_badge_fit,
                spacing=badge_text_spacing,
                fill=badge_text,
            )

        if item.completed:
            # [E-INK] Strikethrough
            tw = text_size(draw, title, title_font)[0]
            sy = ty + th // 2 + 1
            draw.line((inner_x0, sy, inner_x0 + tw, sy), fill=ink, width=2) 

        y += inv_row_h

    # Shopping header
    # Keep right-lower section aligned to the left panel section rhythm.
    inv_bottom_y = y
    shop_title_spacing = int(t.get("b_shopping_title_spacing", 1))
    shop_label = "SHOPPING LIST"
    shop_rule_gap = int(t.get("b_shop_header_rule_gap", 6))
    shop_rule_w = max(1, int(t.get("b_shop_section_rule_w", 1)))
    shop_rule_right_max = inner_x1 - int(t.get("b_shop_section_rule_right_gap", 18))
    shop_rule_left = inner_x0 + int(t.get("b_shop_section_rule_left_gap", 0))
    shop_title_h = text_size(draw, "Ag", f_shop_title)[1]
    shop_line_gap = int(t.get("b_shop_header_line_after_title_gap", 9))
    shop_rule_y_target = family_rule_y
    shop_rule_y_min = inv_bottom_y + int(t.get("b_inv_shop_min_gap", 14))
    shop_rule_y = max(shop_rule_y_target, shop_rule_y_min)
    shop_title_y = shop_rule_y - shop_title_h - shop_line_gap
    shop_label_w = text_width_spaced(draw, shop_label, f_shop_title, spacing=shop_title_spacing)

    # Header: left-aligned title + right count on same baseline.
    shop_title_x = inner_x0
    draw_text_spaced(draw, shop_label, shop_title_x, shop_title_y, f_shop_title, spacing=shop_title_spacing, fill=ink)

    shop_cnt = str(len(shop))
    shop_cnt_spacing = max(0, shop_title_spacing - 1)
    shop_cnt_w = text_width_spaced(draw, shop_cnt, f_shop_title, spacing=shop_cnt_spacing)
    shop_cnt_x = inner_x1 - shop_cnt_w
    draw_text_spaced(draw, shop_cnt, shop_cnt_x, shop_title_y, f_shop_title, spacing=shop_cnt_spacing, fill=ink)

    # Support line under the header.
    shop_rule_right = min(shop_rule_right_max, shop_cnt_x - shop_rule_gap)
    if shop_rule_right > shop_rule_left:
        draw.line((shop_rule_left, shop_rule_y, shop_rule_right, shop_rule_y), fill=ink, width=shop_rule_w)
    
    shop_row_h = int(t["b_shopping_row_h"]) + 4
    y = max(shop_title_y + int(t["b_shopping_header_gap"]), shop_rule_y + 10)
    shop_bottom = oy1 - int(t["b_bottom_pad"])

    shop_max_rows = max(1, int(t.get("b_shopping_max_rows", 5)))
    for item in shop[:shop_max_rows]:
        if y + shop_row_h > shop_bottom:
            break
        is_focus = (not state.ui.idle) and (focus_rid == item.rid and not item.completed)
        if not item.completed:
            rendered_focus_rids.append(item.rid)
        
        text_fill = ink
        box_outline = ink

        if is_focus:
            if right_focus_style == "rail":
                rail_w = int(t.get("b_right_focus_rail_w", 3))
                rail_gap = int(t.get("b_right_focus_rail_gap", 6))
                rail_vpad = int(t.get("b_right_focus_rail_vpad", 5))
                rx1 = inner_x0 - rail_gap
                rx0 = rx1 - rail_w
                ry0 = y + rail_vpad
                ry1 = y + shop_row_h - rail_vpad
                if ry1 > ry0:
                    draw.rectangle((rx0, ry0, rx1, ry1), fill=ink)
            else:
                fx0 = inner_x0 - focus_pad_x
                fx1 = inner_x1 + focus_pad_x - focus_right_trim
                fy0 = y + focus_pad_y
                fy1 = y + shop_row_h - focus_pad_y
                if fy1 > fy0 and fx1 > fx0:
                    rounded_rect(
                        draw,
                        (fx0, fy0, fx1, fy1),
                        radius=max(0, min(focus_radius, (fy1 - fy0) // 2)),
                        outline=ink,
                        width=focus_w,
                        fill=None,
                    )

        # checkbox
        cb = int(t["b_shop_checkbox_size"])
        cbx = inner_x0
        cby = y + (shop_row_h - cb) // 2

        rounded_rect(
            draw,
            (cbx, cby, cbx + cb, cby + cb),
            radius=int(t["b_shop_checkbox_radius"]),
            outline=box_outline,
            width=int(t["b_shop_checkbox_w"]),
            fill=None,
        )
        
        if item.completed:
            # Checkmark
            cx, cy = cbx + cb // 2, cby + cb // 2
            points = [
                (cbx + 3, cy),
                (cbx + 5, cy + 3),
                (cbx + 10, cby + 3)
            ]
            draw.line(points, fill=box_outline, width=2, joint="curve")

        text_x = cbx + cb + 14 + int(t.get("b_shop_text_left_pad", 2))
        title = truncate_text(draw, item.title, f_shop_item, max(80, inner_x1 - text_x - 8))

        title_font = f_shop_item_focus if is_focus else f_shop_item
        th = text_size(draw, "Ag", title_font)[1]
        ty = y + (shop_row_h - th) // 2
        draw.text((text_x, ty), title, font=title_font, fill=text_fill)

        if item.completed:
            # [E-INK] Strikethrough
            tw = text_size(draw, title, title_font)[0]
            sy = ty + th // 2 + 1
            draw.line((text_x, sy, text_x + tw, sy), fill=text_fill, width=2)

        y += shop_row_h

    # Sync reducer focus/click queue with the exact rows currently rendered.
    state.ui.kitchen_visible_rids = rendered_focus_rids
    state.ui.kitchen_visible_theme_key = kitchen_queue_theme_key(t)
    state.ui.kitchen_visible_reminders_version = int(state.ui.reminders_version or 0)



def _kitchen_focus_rid(state: AppState, focused_index: int, theme: dict | None = None) -> str:
    # focused_index: 0 is left panel; 1.. maps to visible tasks list
    if focused_index <= 0:
        return ""
    visible_idxs = kitchen_visible_task_indices(state, theme)
    pos = focused_index - 1
    if 0 <= pos < len(visible_idxs):
        return state.model.reminders[visible_idxs[pos]].rid
    return ""
