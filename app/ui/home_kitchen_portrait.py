from __future__ import annotations

from datetime import datetime

from PIL import ImageDraw

from app.core.kitchen_queue import kitchen_queue_theme_key, kitchen_visible_task_indices
from app.core.state import AppState
from app.shared.draw import draw_text_spaced, rounded_rect, text_size, text_width_spaced, truncate_text
from app.ui.weather_detail import _draw_weather_icon_pack


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


def _font_px(v) -> int:
    return max(1, int(round(float(v))))


def _theme(theme: dict) -> dict:
    t = dict(theme or {})

    # Layout
    t.setdefault("bp_margin", 16)
    t.setdefault("bp_section_gap", 12)
    t.setdefault("bp_inner_pad", 18)
    t.setdefault("bp_header_ratio", 0.29)
    t.setdefault("bp_memo_ratio", 0.30)
    t.setdefault("bp_weather_col_w", 156)
    t.setdefault("bp_header_col_gap", 16)
    t.setdefault("bp_header_rule_w", 2)
    t.setdefault("bp_list_split_ratio", 0.42)

    # Header typography
    t.setdefault("bp_time_size", 112)
    t.setdefault("bp_time_min_size", 68)
    t.setdefault("bp_weekday_size", 15)
    t.setdefault("bp_weekday_spacing", 3)
    t.setdefault("bp_date_size", 19)
    t.setdefault("bp_temp_size", 58)
    t.setdefault("bp_weather_desc_size", 14)
    t.setdefault("bp_weather_desc_spacing", 1)
    t.setdefault("bp_weather_desc_gap", 8)
    t.setdefault("bp_weather_icon_size", 42)
    t.setdefault("bp_weather_icon_gap", 10)
    t.setdefault("bp_weather_icon_stroke", 3)
    t.setdefault("bp_weather_top", 4)
    t.setdefault("bp_weather_humidity_size", 14)
    t.setdefault("bp_weather_humidity_spacing", 1)
    t.setdefault("bp_weather_humidity_prefix", "HUM")
    t.setdefault("bp_weather_humidity_gap", 8)

    # Memo section
    t.setdefault("bp_memo_title_size", 15)
    t.setdefault("bp_memo_title_spacing", 2)
    t.setdefault("bp_family_name_size", 13)
    t.setdefault("bp_family_name_spacing", 1)
    t.setdefault("bp_family_gap", 14)
    t.setdefault("bp_family_underline_gap", 3)
    t.setdefault("bp_family_underline_w", 2)
    t.setdefault("bp_quote_size", 42)
    t.setdefault("bp_quote_min_size", 24)
    t.setdefault("bp_quote_lh", 1.18)
    t.setdefault("bp_quote_top_gap", 10)
    t.setdefault("bp_quote_bottom_gap", 8)
    t.setdefault("bp_quote_target_lines", 3)
    t.setdefault("bp_posted_size", 16)
    t.setdefault("bp_posted_prefix", "-")
    t.setdefault("bp_posted_right_inset", 4)
    t.setdefault("bp_author_max_tags", 4)
    t.setdefault("bp_log_compact_day_time", True)
    t.setdefault("bp_log_datetime_format", "%a %H:%M")

    # Lists
    t.setdefault("bp_inventory_title_size", 14)
    t.setdefault("bp_inventory_title_spacing", 2)
    t.setdefault("bp_inventory_header_gap", 24)
    t.setdefault("bp_inventory_item_size", 19)
    t.setdefault("bp_inventory_row_h", 40)
    t.setdefault("bp_badge_size", 13)
    t.setdefault("bp_badge_max_w", 134)
    t.setdefault("bp_badge_gap", 12)
    t.setdefault("bp_shopping_title_size", 14)
    t.setdefault("bp_shopping_title_spacing", 1)
    t.setdefault("bp_shopping_header_gap", 22)
    t.setdefault("bp_shopping_item_size", 18)
    t.setdefault("bp_shopping_row_h", 40)
    t.setdefault("bp_checkbox_size", 16)
    t.setdefault("bp_checkbox_radius", 3)
    t.setdefault("bp_checkbox_w", 2)

    # Keep queue defaults aligned with reducer fallback.
    t.setdefault("b_inventory_max_rows", 3)
    t.setdefault("b_shopping_max_rows", 5)

    # Focus rendering
    t.setdefault("bp_focus_pad_x", 6)
    t.setdefault("bp_focus_pad_y", 4)
    t.setdefault("bp_focus_radius", 6)
    t.setdefault("bp_focus_w", 1)

    # Palette and typography
    t.setdefault("b_muted_gray", 110)
    t.setdefault("b_date_gray", 90)
    t.setdefault("b_subtle_gray", 205)
    t.setdefault("b_text_antialias", False)
    t.setdefault("panel_font_body_key", "inter_medium")
    t.setdefault("panel_font_body_focus_key", "inter_bold")
    t.setdefault("panel_font_body_size", 18)
    t.setdefault("panel_font_meta_key", "jet_bold")
    t.setdefault("panel_font_meta_size", 13)
    t.setdefault("panel_font_meta_spacing", 0)

    # Panel-specific overrides
    t.setdefault("b_panel_inventory_item_font", "inter_medium")
    t.setdefault("b_panel_inventory_item_focus_font", "inter_bold")
    t.setdefault("b_panel_inventory_item_size", 18)
    t.setdefault("b_panel_badge_font", "jet_bold")
    t.setdefault("b_panel_badge_size", 13)
    t.setdefault("b_panel_shopping_item_font", "inter_medium")
    t.setdefault("b_panel_shopping_item_focus_font", "inter_bold")
    t.setdefault("b_panel_shopping_item_size", 18)

    return t


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
    fridge = sorted(fridge, key=lambda r: (r.completed,))
    shop = sorted(shop, key=lambda r: (r.completed,))
    return fridge, shop


def _wrap_lines(draw, text: str, quote_font, max_width: int) -> list[str]:
    words = (text or "").split(" ")
    out: list[str] = []
    cur = ""
    for wd in words:
        nxt = (cur + " " + wd).strip()
        if not cur or text_size(draw, nxt, quote_font)[0] <= max_width:
            cur = nxt
        else:
            out.append(cur)
            cur = wd
    if cur:
        out.append(cur)
    return out


def _format_memo_posted(timestamp, theme: dict) -> str:
    if timestamp is None:
        return ""
    try:
        ts = float(timestamp)
    except Exception:
        return ""
    if ts != ts or ts in (float("inf"), float("-inf")):
        return ""
    for _ in range(3):
        if abs(ts) <= 1e11:
            break
        ts /= 1000.0
    try:
        dt = datetime.fromtimestamp(ts)
    except Exception:
        return ""
    if bool(theme.get("bp_log_compact_day_time", True)):
        dow = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")[dt.weekday()]
        return f"{dow} {dt.strftime('%H:%M')}"
    fmt = str(theme.get("bp_log_datetime_format") or "%a %H:%M")
    try:
        return dt.strftime(fmt)
    except Exception:
        return dt.strftime("%a %H:%M")


def _compact_badge(text: str) -> str:
    s = (text or "").upper()
    s = s.replace("EXPIRES", "EXP")
    s = s.replace("EXPIRY", "EXP")
    s = s.replace("YESTERDAY", "YDAY")
    s = s.replace("TODAY", "TDY")
    s = s.replace("TONIGHT", "TNITE")
    s = s.replace("DAYS", "D")
    s = s.replace("DAY", "D")
    return " ".join(s.split())


def _kitchen_focus_rid(state: AppState, focused_index: int, theme: dict | None = None) -> str:
    if focused_index <= 0:
        return ""
    visible_idxs = kitchen_visible_task_indices(state, theme)
    pos = focused_index - 1
    if 0 <= pos < len(visible_idxs):
        return state.model.reminders[visible_idxs[pos]].rid
    return ""


def render_home_kitchen_portrait(image, state: AppState, fonts, theme: dict) -> None:
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

    draw.rectangle((0, 0, w, h), fill=card)

    m = int(t["bp_margin"])
    x0, y0, x1, y1 = m, m, w - m, h - m
    draw.rectangle((x0, y0, x1, y1), fill=card)

    sec_gap = int(t["bp_section_gap"])
    inner_h = max(1, y1 - y0)
    header_h = max(184, int(inner_h * float(t["bp_header_ratio"])))
    memo_h = max(188, int(inner_h * float(t["bp_memo_ratio"])))
    min_list_h = 220
    if header_h + memo_h + sec_gap * 2 + min_list_h > inner_h:
        overflow = header_h + memo_h + sec_gap * 2 + min_list_h - inner_h
        memo_h = max(150, memo_h - overflow)

    header_y0 = y0
    header_y1 = min(y1 - sec_gap * 2 - min_list_h, header_y0 + header_h)
    memo_y0 = header_y1 + sec_gap
    memo_y1 = min(y1 - sec_gap - min_list_h, memo_y0 + memo_h)
    list_y0 = memo_y1 + sec_gap
    list_y1 = y1

    section_rule_w = max(1, int(t.get("bp_header_rule_w", 1)))
    draw.line((x0, header_y1, x1, header_y1), fill=ink, width=section_rule_w)
    draw.line((x0, memo_y1, x1, memo_y1), fill=ink, width=section_rule_w)

    # Keep dynamic regions stable for MCU dirty-rect mapping:
    # header(clock/weather), memo body, and lists are fixed-height zones.

    panel_mode = bool(theme.get("panel_mode", False))
    body_key = str(t.get("panel_font_body_key") or "inter_medium")
    body_focus_key = str(t.get("panel_font_body_focus_key") or "inter_bold")
    meta_key = str(t.get("panel_font_meta_key") or "jet_bold")
    body_size = int(t.get("panel_font_body_size", 18))
    meta_size = int(t.get("panel_font_meta_size", 13))
    meta_spacing = int(t.get("panel_font_meta_spacing", 0))

    # Header
    pad = int(t["bp_inner_pad"])
    hx0, hx1 = x0 + pad, x1 - pad
    hy0 = header_y0 + pad
    weather_w = min(int(t["bp_weather_col_w"]), max(120, int((hx1 - hx0) * 0.36)))
    col_gap = int(t["bp_header_col_gap"])
    left_x0 = hx0
    left_x1 = max(left_x0 + 120, hx1 - weather_w - col_gap)
    weather_x0 = left_x1 + col_gap
    weather_x1 = hx1

    now = datetime.now()
    time_str = now.strftime("%H:%M")
    weekday = now.strftime("%A").upper()
    try:
        month_day = now.strftime("%B %-d, %Y")
    except Exception:
        month_day = now.strftime("%B %d, %Y")

    time_size = int(t["bp_time_size"])
    time_min_size = int(t["bp_time_min_size"])
    while time_size > time_min_size:
        f_probe = fonts.get("inter_black", _font_px(time_size))
        tw_probe, _ = text_size(draw, time_str, f_probe)
        if tw_probe <= max(84, left_x1 - left_x0):
            break
        time_size -= 2
    f_time = fonts.get("inter_black", _font_px(time_size))
    f_weekday = fonts.get("jet_extrabold", _font_px(t["bp_weekday_size"]))
    f_date = fonts.get("inter_bold", _font_px(t["bp_date_size"]))
    f_temp = fonts.get("inter_black", _font_px(t["bp_temp_size"]))
    f_weather_desc = fonts.get(meta_key, _font_px(t["bp_weather_desc_size"]))
    f_weather_humidity = fonts.get(meta_key, _font_px(t["bp_weather_humidity_size"]))

    draw.text((left_x0, hy0), time_str, font=f_time, fill=ink)
    _, time_h = text_size(draw, time_str, f_time)
    week_y = hy0 + time_h + 4
    draw_text_spaced(
        draw,
        weekday,
        left_x0,
        week_y,
        f_weekday,
        spacing=int(t["bp_weekday_spacing"]),
        fill=ink,
    )
    week_h = text_size(draw, "Ag", f_weekday)[1]
    date_y = week_y + week_h + 8
    draw.text((left_x0, date_y), month_day, font=f_date, fill=date_muted)

    weather_top = hy0 + int(t["bp_weather_top"])
    if state.model.weather:
        w0 = state.model.weather[0]
        temp = f"{int(w0.hi)}°"
        tw, th = text_size(draw, temp, f_temp)
        temp_x = weather_x1 - tw
        draw.text((temp_x, weather_top), temp, font=f_temp, fill=ink)

        desc = _weather_word(getattr(w0, "icon", "sun"))
        desc_w = text_width_spaced(draw, desc, f_weather_desc, spacing=int(t["bp_weather_desc_spacing"]))
        desc_h = text_size(draw, "Ag", f_weather_desc)[1]
        desc_x = weather_x1 - desc_w
        desc_y = weather_top + th + int(t["bp_weather_desc_gap"])
        draw_text_spaced(
            draw,
            desc,
            desc_x,
            desc_y,
            f_weather_desc,
            spacing=int(t["bp_weather_desc_spacing"]),
            fill=ink,
        )

        icon_size = int(t["bp_weather_icon_size"])
        icon_y = desc_y + desc_h + int(t["bp_weather_icon_gap"])
        icon_x = weather_x1 - icon_size
        icon_theme = dict(t)
        icon_theme["weather_icon_alpha_threshold"] = int(
            t.get("b_weather_icon_alpha_threshold", t.get("weather_icon_alpha_threshold", 185)) or 185
        )
        _draw_weather_icon_pack(
            image,
            draw,
            icon_theme,
            w0.icon,
            int(icon_x),
            int(icon_y),
            size=int(icon_size),
            size_h=None,
            ink=ink,
            stroke=int(t.get("bp_weather_icon_stroke", 3)),
            thicken=bool(t.get("b_weather_icon_thicken", False)),
        )

        humidity = getattr(w0, "humidity", None)
        humidity_text = ""
        if humidity is not None:
            try:
                humidity_text = f"{str(t['bp_weather_humidity_prefix']).upper()} {int(humidity)}%"
            except Exception:
                humidity_text = ""
        if humidity_text:
            hum_w = text_width_spaced(
                draw,
                humidity_text,
                f_weather_humidity,
                spacing=int(t["bp_weather_humidity_spacing"]),
            )
            hum_y = icon_y + icon_size + int(t["bp_weather_humidity_gap"])
            hum_x = weather_x1 - hum_w
            draw_text_spaced(
                draw,
                humidity_text,
                hum_x,
                hum_y,
                f_weather_humidity,
                spacing=int(t["bp_weather_humidity_spacing"]),
                fill=muted,
            )
    else:
        draw.text((weather_x1 - 92, weather_top + 8), "--°", font=f_temp, fill=ink)
        draw_text_spaced(draw, "NO DATA", weather_x0, weather_top + 86, f_weather_desc, spacing=1, fill=muted)

    # Memo section
    mx0, mx1 = x0 + pad, x1 - pad
    my0 = memo_y0 + 10
    f_memo_title = fonts.get(meta_key, _font_px(t["bp_memo_title_size"]))
    f_family_name = fonts.get(meta_key, _font_px(t["bp_family_name_size"]))
    draw_text_spaced(
        draw,
        "FAMILY BOARD",
        mx0,
        my0,
        f_memo_title,
        spacing=int(t["bp_memo_title_spacing"]),
        fill=muted,
    )

    memos = state.model.memos or []
    memo_idx = int(state.ui.memo_index or 0)
    memo = memos[memo_idx % len(memos)] if memos else None

    active_author = (memo.author if memo else "MOM").upper()
    authors = [active_author] if active_author else []
    for m_item in memos:
        a = (m_item.author or "").strip().upper()
        if not a or a in authors:
            continue
        authors.append(a)
    authors = authors[: max(1, int(t["bp_author_max_tags"]))]

    name_spacing = int(t["bp_family_name_spacing"])
    name_gap = int(t["bp_family_gap"])
    underline_gap = int(t["bp_family_underline_gap"])
    underline_w = int(t["bp_family_underline_w"])
    labels: list[tuple[str, int]] = []
    row_total = 0
    title_w = text_width_spaced(draw, "FAMILY BOARD", f_memo_title, spacing=int(t["bp_memo_title_spacing"]))
    max_row_w = max(80, mx1 - (mx0 + title_w + 20))
    for a in authors:
        tw = text_width_spaced(draw, a, f_family_name, spacing=name_spacing)
        extra = (name_gap if labels else 0) + tw
        if row_total + extra > max_row_w:
            break
        labels.append((a, tw))
        row_total += extra

    row_x = max(mx0 + title_w + 14, mx1 - row_total)
    row_y = my0 + 1
    name_h = text_size(draw, "Ag", f_family_name)[1]
    cx = row_x
    for i, (name, tw) in enumerate(labels):
        draw_text_spaced(draw, name, cx, row_y, f_family_name, spacing=name_spacing, fill=ink)
        if i == 0:
            uy = row_y + name_h + underline_gap
            draw.line((cx, uy, cx + tw, uy), fill=ink, width=underline_w)
        cx += tw + name_gap

    memo_rule_y = max(my0 + text_size(draw, "Ag", f_memo_title)[1], row_y + name_h + underline_gap + underline_w) + 8
    draw.line((mx0, memo_rule_y, mx1, memo_rule_y), fill=ink, width=section_rule_w)

    quote = (memo.text.strip() if memo and memo.text else "No messages.")
    posted = _format_memo_posted((memo.timestamp if memo else None), t)
    posted_prefix = str(t.get("bp_posted_prefix") or "-").strip() or "-"
    posted_label_raw = f"{posted_prefix} {posted}" if posted else ""
    f_posted = fonts.get(meta_key, _font_px(t["bp_posted_size"]))
    posted_h = text_size(draw, "Ag", f_posted)[1]
    posted_label = (
        truncate_text(draw, posted_label_raw, f_posted, max(40, mx1 - mx0 - 10)) if posted_label_raw else ""
    )

    quote_y0 = memo_rule_y + int(t["bp_quote_top_gap"])
    quote_y1 = memo_y1 - pad - posted_h - int(t["bp_quote_bottom_gap"])
    quote_w = max(120, mx1 - mx0)
    quote_size = int(t["bp_quote_size"])
    quote_min = int(t["bp_quote_min_size"])
    target_lines = max(1, int(t["bp_quote_target_lines"]))
    rendered_lines: list[str] = []
    quote_font = fonts.get("playfair_bold", _font_px(quote_size))
    quote_line_h = text_size(draw, "Ag", quote_font)[1]

    while quote_size >= quote_min:
        quote_font = fonts.get("playfair_bold", _font_px(quote_size))
        quote_line_h = max(1, int(text_size(draw, "Ag", quote_font)[1] * float(t["bp_quote_lh"])))
        max_lines = max(1, (quote_y1 - quote_y0) // max(1, quote_line_h))
        lines = _wrap_lines(draw, quote, quote_font, quote_w)
        if len(lines) <= max_lines:
            rendered_lines = lines
            break
        quote_size -= 1

    if not rendered_lines:
        quote_font = fonts.get("playfair_bold", _font_px(quote_min))
        quote_line_h = max(1, int(text_size(draw, "Ag", quote_font)[1] * float(t["bp_quote_lh"])))
        max_lines = max(1, (quote_y1 - quote_y0) // max(1, quote_line_h))
        rendered_lines = _wrap_lines(draw, quote, quote_font, quote_w)[:max_lines]

    if len(rendered_lines) < target_lines and len(rendered_lines) == 1:
        compact_w = max(120, int(quote_w * 0.9))
        compact_lines = _wrap_lines(draw, quote, quote_font, compact_w)
        if len(compact_lines) > len(rendered_lines):
            rendered_lines = compact_lines

    for i, ln in enumerate(rendered_lines):
        y = quote_y0 + i * quote_line_h
        if y + quote_line_h > quote_y1:
            break
        draw.text((mx0, y), ln, font=quote_font, fill=ink)

    if posted_label:
        posted_w = text_size(draw, posted_label, f_posted)[0]
        posted_x = max(mx0, mx1 - int(t["bp_posted_right_inset"]) - posted_w)
        posted_y = memo_y1 - pad - posted_h
        draw.text((posted_x, posted_y), posted_label, font=f_posted, fill=ink)

    # Lists
    lx0, lx1 = x0 + pad, x1 - pad
    ly0, ly1 = list_y0 + pad, list_y1 - pad
    list_h = max(80, ly1 - ly0)
    inv_zone_bottom = min(ly1 - 116, ly0 + max(102, int(list_h * float(t["bp_list_split_ratio"]))))

    focus_idx = int(state.ui.focused_index or 0)
    focus_rid = _kitchen_focus_rid(state, focus_idx, t)
    rendered_focus_rids: list[str] = []
    fridge, shop = _group_tasks(state)

    inv_item_key = body_key
    inv_item_focus_key = body_focus_key
    badge_key = meta_key
    shop_item_key = body_key
    shop_item_focus_key = body_focus_key
    inv_item_size = int(t["bp_inventory_item_size"])
    shop_item_size = int(t["bp_shopping_item_size"])
    badge_size = int(t["bp_badge_size"])
    if panel_mode:
        inv_item_key = str(t.get("b_panel_inventory_item_font") or inv_item_key)
        inv_item_focus_key = str(t.get("b_panel_inventory_item_focus_font") or inv_item_focus_key)
        badge_key = str(t.get("b_panel_badge_font") or badge_key)
        shop_item_key = str(t.get("b_panel_shopping_item_font") or shop_item_key)
        shop_item_focus_key = str(t.get("b_panel_shopping_item_focus_font") or shop_item_focus_key)
        inv_item_size = int(t.get("b_panel_inventory_item_size", inv_item_size))
        shop_item_size = int(t.get("b_panel_shopping_item_size", shop_item_size))
        badge_size = int(t.get("b_panel_badge_size", badge_size))

    f_inv_title = fonts.get(meta_key, _font_px(t["bp_inventory_title_size"]))
    f_inv_item = fonts.get(inv_item_key, _font_px(max(body_size, inv_item_size)))
    f_inv_item_focus = fonts.get(inv_item_focus_key, _font_px(max(body_size, inv_item_size)))
    f_badge = fonts.get(badge_key, _font_px(max(meta_size, badge_size)))
    f_shop_title = fonts.get(meta_key, _font_px(t["bp_shopping_title_size"]))
    f_shop_item = fonts.get(shop_item_key, _font_px(max(body_size, shop_item_size)))
    f_shop_item_focus = fonts.get(shop_item_focus_key, _font_px(max(body_size, shop_item_size)))

    focus_pad_x = int(t["bp_focus_pad_x"])
    focus_pad_y = int(t["bp_focus_pad_y"])
    focus_radius = int(t["bp_focus_radius"])
    focus_w = max(1, int(t["bp_focus_w"]))

    inv_title_spacing = int(t["bp_inventory_title_spacing"])
    inv_title_y = ly0
    draw_text_spaced(draw, "INVENTORY", lx0, inv_title_y, f_inv_title, spacing=inv_title_spacing, fill=ink)
    fridge_due = sum(1 for r in fridge if not r.completed)
    if fridge_due > 0:
        count = str(fridge_due)
        count_w = text_width_spaced(draw, count, f_inv_title, spacing=inv_title_spacing)
        draw_text_spaced(draw, count, lx1 - count_w, inv_title_y, f_inv_title, spacing=inv_title_spacing, fill=ink)

    inv_row_y = inv_title_y + int(t["bp_inventory_header_gap"])
    inv_row_h = int(t["bp_inventory_row_h"])
    inv_max_rows = max(1, int(t["b_inventory_max_rows"]))
    badge_gap = int(t["bp_badge_gap"])
    badge_max_w = int(t["bp_badge_max_w"])

    for item in fridge[:inv_max_rows]:
        if inv_row_y + inv_row_h > inv_zone_bottom:
            break
        is_focus = (not state.ui.idle) and (focus_rid == item.rid and not item.completed)
        if not item.completed:
            rendered_focus_rids.append(item.rid)

        if is_focus:
            fx0 = lx0 - focus_pad_x
            fx1 = lx1 + focus_pad_x
            fy0 = inv_row_y + focus_pad_y
            fy1 = inv_row_y + inv_row_h - focus_pad_y
            if fy1 > fy0:
                rounded_rect(
                    draw,
                    (fx0, fy0, fx1, fy1),
                    radius=max(0, min(focus_radius, (fy1 - fy0) // 2)),
                    outline=ink,
                    width=focus_w,
                    fill=None,
                )

        badge_text = _compact_badge(item.right or ("OUT" if item.completed else "STOCKED"))
        badge_text = truncate_text(draw, badge_text, f_badge, badge_max_w)
        badge_w = text_width_spaced(draw, badge_text, f_badge, spacing=meta_spacing)
        badge_h = text_size(draw, "Ag", f_badge)[1]
        badge_x = lx1 - badge_w
        badge_y = inv_row_y + max(0, (inv_row_h - badge_h) // 2)
        draw_text_spaced(draw, badge_text, badge_x, badge_y, f_badge, spacing=meta_spacing, fill=ink)

        title_font = f_inv_item_focus if is_focus else f_inv_item
        title_max_w = max(80, badge_x - badge_gap - lx0)
        title = truncate_text(draw, item.title, title_font, title_max_w)
        title_h = text_size(draw, "Ag", title_font)[1]
        title_y = inv_row_y + max(0, (inv_row_h - title_h) // 2)
        draw.text((lx0, title_y), title, font=title_font, fill=ink)

        if item.completed:
            tw = text_size(draw, title, title_font)[0]
            sy = title_y + title_h // 2 + 1
            draw.line((lx0, sy, lx0 + tw, sy), fill=ink, width=2)

        inv_row_y += inv_row_h

    shop_title_spacing = int(t["bp_shopping_title_spacing"])
    shop_line_y = max(inv_zone_bottom, inv_row_y + 8)
    shop_title_h = text_size(draw, "Ag", f_shop_title)[1]
    shop_title_y = max(inv_row_y + 8, shop_line_y - shop_title_h - 8)
    draw_text_spaced(draw, "SHOPPING LIST", lx0, shop_title_y, f_shop_title, spacing=shop_title_spacing, fill=ink)
    shop_count = str(len(shop))
    shop_count_w = text_width_spaced(draw, shop_count, f_shop_title, spacing=max(0, shop_title_spacing - 1))
    draw_text_spaced(
        draw,
        shop_count,
        lx1 - shop_count_w,
        shop_title_y,
        f_shop_title,
        spacing=max(0, shop_title_spacing - 1),
        fill=ink,
    )
    draw.line((lx0, shop_line_y, lx1, shop_line_y), fill=ink, width=section_rule_w)

    shop_row_y = max(shop_line_y + 10, shop_title_y + int(t["bp_shopping_header_gap"]))
    shop_row_h = int(t["bp_shopping_row_h"])
    shop_max_rows = max(1, int(t["b_shopping_max_rows"]))
    cb_size = int(t["bp_checkbox_size"])

    for item in shop[:shop_max_rows]:
        if shop_row_y + shop_row_h > ly1:
            break
        is_focus = (not state.ui.idle) and (focus_rid == item.rid and not item.completed)
        if not item.completed:
            rendered_focus_rids.append(item.rid)

        if is_focus:
            fx0 = lx0 - focus_pad_x
            fx1 = lx1 + focus_pad_x
            fy0 = shop_row_y + focus_pad_y
            fy1 = shop_row_y + shop_row_h - focus_pad_y
            if fy1 > fy0:
                rounded_rect(
                    draw,
                    (fx0, fy0, fx1, fy1),
                    radius=max(0, min(focus_radius, (fy1 - fy0) // 2)),
                    outline=ink,
                    width=focus_w,
                    fill=None,
                )

        cb_x = lx0
        cb_y = shop_row_y + max(0, (shop_row_h - cb_size) // 2)
        rounded_rect(
            draw,
            (cb_x, cb_y, cb_x + cb_size, cb_y + cb_size),
            radius=int(t["bp_checkbox_radius"]),
            outline=ink,
            width=int(t["bp_checkbox_w"]),
            fill=None,
        )
        if item.completed:
            points = [
                (cb_x + 3, cb_y + cb_size // 2),
                (cb_x + 6, cb_y + cb_size - 4),
                (cb_x + cb_size - 3, cb_y + 3),
            ]
            draw.line(points, fill=ink, width=2, joint="curve")

        title_font = f_shop_item_focus if is_focus else f_shop_item
        text_x = cb_x + cb_size + 14
        title = truncate_text(draw, item.title, title_font, max(80, lx1 - text_x - 4))
        title_h = text_size(draw, "Ag", title_font)[1]
        title_y = shop_row_y + max(0, (shop_row_h - title_h) // 2)
        draw.text((text_x, title_y), title, font=title_font, fill=ink)
        if item.completed:
            tw = text_size(draw, title, title_font)[0]
            sy = title_y + title_h // 2 + 1
            draw.line((text_x, sy, text_x + tw, sy), fill=ink, width=2)

        shop_row_y += shop_row_h

    state.ui.kitchen_visible_rids = rendered_focus_rids
    state.ui.kitchen_visible_theme_key = kitchen_queue_theme_key(t)
    state.ui.kitchen_visible_reminders_version = int(state.ui.reminders_version or 0)
