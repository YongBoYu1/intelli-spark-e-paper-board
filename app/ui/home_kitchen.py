from __future__ import annotations

from datetime import datetime
import time

from PIL import ImageDraw

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
    t.setdefault("b_time_weather_gap", 14)
    t.setdefault("b_time_weekday_gap", 13)
    t.setdefault("b_weekday_size", 12)
    t.setdefault("b_weekday_spacing", 4)
    t.setdefault("b_weekday_date_gap", 9)
    t.setdefault("b_date_size", 13)
    t.setdefault("b_date_gray", 95)
    t.setdefault("b_temp_size", 54)
    t.setdefault("b_weather_desc_size", 12)
    t.setdefault("b_weather_desc_spacing", 1)
    t.setdefault("b_weather_col_w", 120)
    t.setdefault("b_weather_top", -2)
    t.setdefault("b_weather_desc_gap", 18)
    t.setdefault("b_weather_desc_offset_y", 5)
    t.setdefault("b_weather_icon_gap", 15)
    t.setdefault("b_weather_icon_size", 20)
    t.setdefault("b_header_gap", 28)
    t.setdefault("b_header_rule_w", 0)
    t.setdefault("b_left_micro_size", 14)
    t.setdefault("b_left_micro_spacing", 3)
    t.setdefault("b_family_name_size", 12)
    t.setdefault("b_family_name_spacing", 1)
    t.setdefault("b_family_name_gap", 15)
    t.setdefault("b_family_names_right_inset", 14)
    t.setdefault("b_family_row_gap", 7)
    t.setdefault("b_family_rule_gap", 8)
    t.setdefault("b_family_active_underline_gap", 3)
    t.setdefault("b_family_active_underline_w", 2)
    t.setdefault("b_quote_size", 27)
    t.setdefault("b_quote_min_size", 20)
    t.setdefault("b_quote_lh", 1.18)
    t.setdefault("b_quote_top_gap", 14)
    t.setdefault("b_quote_max_w_ratio", 0.76)
    t.setdefault("b_quote_short_wrap_factor", 0.74)
    t.setdefault("b_quote_display_wrap_factor", 0.84)
    t.setdefault("b_quote_target_lines", 2)
    t.setdefault("b_quote_balance_lines", 2)
    t.setdefault("b_quote_balance_ratio", 0.20)
    t.setdefault("b_quote_balance_max", 24)
    t.setdefault("b_quote_bottom_gap", 14)
    t.setdefault("b_posted_after_quote_gap", 10)
    t.setdefault("b_posted_max_gap_from_quote", 44)
    t.setdefault("b_posted_size", 12)
    t.setdefault("b_posted_size_panel_min", 13)
    t.setdefault("b_left_bottom_pad", 22)
    t.setdefault("b_posted_rule_w", 0)
    t.setdefault("b_posted_rule_gap", 3)
    t.setdefault("b_author_size", 9)
    t.setdefault("b_author_row_offset_y", 1)
    t.setdefault("b_author_max_tags", 4)

    # Right block
    t.setdefault("b_right_pad", 22)
    t.setdefault("b_inventory_title_size", 12)
    t.setdefault("b_inventory_item_size", 17)
    t.setdefault("b_inventory_row_h", 36)
    t.setdefault("b_badge_size", 10)
    t.setdefault("b_badge_px", 8)
    t.setdefault("b_badge_py", 2)
    t.setdefault("b_badge_max_w", 126)
    t.setdefault("b_mid_split_ratio", 0.53)
    t.setdefault("b_shopping_title_size", 12)
    t.setdefault("b_shopping_item_size", 17)
    t.setdefault("b_shopping_row_h", 36)
    t.setdefault("b_bottom_pad", 14)

    # Shared color tone in RGB mode (ignored in 1-bit)
    t.setdefault("b_muted_gray", 110)
    t.setdefault("b_subtle_gray", 205)

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


def render_home_kitchen(image, state: AppState, fonts, theme: dict) -> None:
    t = _theme(theme)
    draw = ImageDraw.Draw(image)
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
    f_date = fonts.get("inter_semibold", _font_px(t["b_date_size"]))
    f_temp = fonts.get("inter_black", _font_px(t["b_temp_size"]))
    f_weather_desc = fonts.get("jet_bold", _font_px(t["b_weather_desc_size"]))
    f_micro = fonts.get("jet_bold", _font_px(t["b_left_micro_size"]))
    f_family_name = fonts.get("jet_bold", _font_px(t["b_family_name_size"]))
    # Use a slightly heavier serif to survive 1-bit panel quantization.
    f_quote = fonts.get("playfair_bold", _font_px(t["b_quote_size"]))
    posted_size = int(t["b_posted_size"])
    # Slightly boost the LOG stamp in panel-like (non-RGB) render paths.
    if image.mode != "RGB":
        posted_size = max(posted_size, int(t.get("b_posted_size_panel_min", 13)))
    f_posted = fonts.get("jet_bold", _font_px(posted_size))

    f_inv_title = fonts.get("inter_semibold", _font_px(t["b_inventory_title_size"]))
    f_inv_item = fonts.get("inter_bold", _font_px(t["b_inventory_item_size"]))
    f_badge = fonts.get("inter_bold", _font_px(t["b_badge_size"]))
    f_shop_title = fonts.get("inter_semibold", _font_px(t["b_shopping_title_size"]))
    f_shop_item = fonts.get("inter_medium", _font_px(t["b_shopping_item_size"]))

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

    draw.text((lx0, top_y), time_str, font=f_time, fill=ink)
    time_box = draw.textbbox((lx0, top_y), time_str, font=f_time)

    wy = time_box[3] + int(t["b_time_weekday_gap"])
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
        draw_weather_icon(draw, w0.icon, icon_x, icon_y, size=icon_size, ink=ink, stroke=2)
        weather_bottom = max(weather_bottom, desc_y + dh2, icon_y + icon_size)

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

    posted = time.strftime("%H:%M", time.localtime(memo.timestamp)) if memo else ""
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
    posted_rule_y = posted_text_y + posted_h + int(t["b_posted_rule_gap"])

    posted_label = f"LOG: {posted}" if posted else ""
    posted_w = text_size(draw, posted_label, f_posted)[0] if posted_label else 0
    left_rule_w = int(t["b_posted_rule_w"]) if int(t["b_posted_rule_w"]) > 0 else posted_w + 12
    draw.line((lx0, posted_rule_y, lx0 + left_rule_w, posted_rule_y), fill=ink, width=1)
    if lx0 + left_rule_w + 12 < lx1:
        draw.line((lx0 + left_rule_w + 8, posted_rule_y, lx1, posted_rule_y), fill=subtle, width=1)
    if posted:
        draw.text((lx0, posted_text_y), posted_label, font=f_posted, fill=ink)

    # ---------------- Right Panel ----------------
    rx0 = split_x + 1
    rp = int(t["b_right_pad"])
    inner_x0 = rx0 + rp
    inner_x1 = ox1 - rp

    mid_y = oy0 + int((oy1 - oy0) * float(t["b_mid_split_ratio"]))
    draw.line((rx0, mid_y, ox1, mid_y), fill=ink, width=1)

    # Focus lookup by task id (incomplete order from reducer)
    focus_rid = _kitchen_focus_rid(state, focus_idx)

    fridge, shop = _group_tasks(state)

    # Inventory header
    inv_y = oy0 + rp
    draw.text((inner_x0, inv_y), "INVENTORY & ALERTS", font=f_inv_title, fill=ink)
    fridge_due = sum(1 for r in fridge if not r.completed)
    cnt = str(fridge_due)
    cw, _ = text_size(draw, cnt, f_inv_title)
    draw.text((inner_x1 - cw, inv_y), cnt, font=f_inv_title, fill=ink)

    inv_row_h = int(t["b_inventory_row_h"])
    y = inv_y + 30
    for item in fridge[:5]:
        # Keep rows strictly inside the inventory area.
        if y + inv_row_h > mid_y - 8:
            break
        is_focus = (focus_rid == item.rid and not item.completed)

        if is_focus:
            draw.rectangle((inner_x0 - 4, y - 2, inner_x1 + 2, y + inv_row_h - 2), fill=ink)
            line_fill = card
            text_fill = card
            badge_fill = card
            badge_text = ink
        else:
            line_fill = subtle
            text_fill = muted if item.completed else ink
            if item.completed:
                badge_fill = card
                badge_text = muted
            else:
                badge_fill = ink
                badge_text = card

        badge_text_raw = (item.right or ("OUT" if item.completed else "STOCKED")).upper()
        max_badge_w = min(int(t["b_badge_max_w"]), max(72, (inner_x1 - inner_x0) - 84))
        badge_text_fit = truncate_text(
            draw,
            badge_text_raw,
            f_badge,
            max(20, max_badge_w - int(t["b_badge_px"]) * 2),
        )
        bw, bh = text_size(draw, badge_text_fit, f_badge)
        bx1 = inner_x1
        bx0 = max(inner_x0 + 84, bx1 - (bw + int(t["b_badge_px"]) * 2))
        by0 = y + 6
        by1 = by0 + bh + int(t["b_badge_py"]) * 2

        title_max_w = max(40, (bx0 - 10) - inner_x0)
        title = truncate_text(draw, item.title, f_inv_item, title_max_w)
        draw.text((inner_x0, y + 5), title, font=f_inv_item, fill=text_fill)

        draw.rectangle((bx0, by0, bx1, by1), fill=badge_fill, outline=ink if item.completed and not is_focus else None, width=1)
        draw.text((bx0 + int(t["b_badge_px"]), by0 + int(t["b_badge_py"]) - 1), badge_text_fit, font=f_badge, fill=badge_text)

        if item.completed and not is_focus:
            tw = text_size(draw, title, f_inv_item)[0]
            sy = y + 16
            draw.line((inner_x0, sy, inner_x0 + tw, sy), fill=muted, width=1)

        draw.line((inner_x0, y + inv_row_h, inner_x1, y + inv_row_h), fill=line_fill, width=1)
        y += inv_row_h

    # Shopping header
    shop_title_y = mid_y + rp
    draw.line((inner_x0, shop_title_y + 9, inner_x0 + 14, shop_title_y + 9), fill=ink, width=2)
    draw.text((inner_x0 + 22, shop_title_y), "SHOPPING LIST", font=f_shop_title, fill=ink)

    shop_row_h = int(t["b_shopping_row_h"])
    y = shop_title_y + 28
    shop_bottom = oy1 - int(t["b_bottom_pad"])
    for item in shop[:6]:
        # Prevent list rows from spilling outside the outer border.
        if y + shop_row_h > shop_bottom:
            break
        is_focus = (focus_rid == item.rid and not item.completed)
        if is_focus:
            draw.rectangle((inner_x0 - 4, y - 2, inner_x1 + 2, y + shop_row_h - 2), fill=ink)
            text_fill = card
            box_outline = card
            line_fill = card
        else:
            text_fill = muted if item.completed else ink
            box_outline = muted if item.completed else ink
            line_fill = subtle

        # checkbox
        cb = 11
        cbx = inner_x0
        cby = y + (shop_row_h - cb) // 2
        draw.rectangle((cbx, cby, cbx + cb, cby + cb), outline=box_outline, width=1, fill=None)
        if item.completed:
            draw.line((cbx + 2, cby + 6, cbx + 5, cby + 9), fill=box_outline, width=1)
            draw.line((cbx + 5, cby + 9, cbx + 10, cby + 2), fill=box_outline, width=1)

        text_x = cbx + cb + 10
        title = truncate_text(draw, item.title, f_shop_item, max(80, inner_x1 - text_x - 8))
        draw.text((text_x, y + 6), title, font=f_shop_item, fill=text_fill)

        if item.completed:
            tw = text_size(draw, title, f_shop_item)[0]
            sy = y + 16
            draw.line((text_x, sy, text_x + tw, sy), fill=text_fill, width=1)

        draw.line((inner_x0, y + shop_row_h, inner_x1, y + shop_row_h), fill=line_fill, width=1)
        y += shop_row_h



def _kitchen_focus_rid(state: AppState, focused_index: int) -> str:
    # focused_index: 0 is left panel; 1.. maps to visible tasks list
    if focused_index <= 0:
        return ""
    fridge = [r for r in state.model.reminders if (r.category or "") == "fridge" and not r.completed]
    shop = [r for r in state.model.reminders if (r.category or "") != "fridge" and not r.completed]
    order = fridge + shop
    pos = focused_index - 1
    if 0 <= pos < len(order):
        return order[pos].rid
    return ""
