from __future__ import annotations

from datetime import datetime
import time

from PIL import ImageDraw

from app.core.state import AppState
from app.shared.draw import (
    rounded_rect,
    text_size,
    truncate_text,
    draw_weather_icon,
)


def _to_rgb(c):
    if isinstance(c, int):
        return (c, c, c)
    if isinstance(c, list) and len(c) == 3:
        return (int(c[0]), int(c[1]), int(c[2]))
    return c


def _theme(theme: dict) -> dict:
    # Defaults copied from copy-of TSX ThemeContext DEFAULT_THEME.
    t = dict(theme or {})
    t.setdefault("k_border_radius", 0)
    t.setdefault("k_container_padding", 32)
    t.setdefault("k_left_column_width", 420)

    t.setdefault("k_border_thin", 2)
    t.setdefault("k_border_thick", 4)

    t.setdefault("k_icon_stroke", 2)
    t.setdefault("k_weather_icon_size", 48)

    t.setdefault("k_clock_size_rem", 10.0)
    t.setdefault("k_clock_weight", 400)
    t.setdefault("k_date_size_rem", 1.4)

    t.setdefault("k_mood_title_size_rem", 0.7)
    t.setdefault("k_mood_msg_size_rem", 2.0)
    t.setdefault("k_mood_msg_lh", 1.1)

    t.setdefault("k_mood_pad_top", 8)
    t.setdefault("k_clock_nudge_em", -0.20)
    t.setdefault("k_clock_header_pad_bottom", 24)
    t.setdefault("k_clock_header_margin_bottom", 24)
    t.setdefault("k_clock_info_gap_px", 8)
    t.setdefault("k_weekday_month_gap_px", 4)
    t.setdefault("k_header_rule_gap_px", 14)

    t.setdefault("k_fridge_card_h", 90)
    t.setdefault("k_fridge_card_gap", 12)
    t.setdefault("k_fridge_title_size_rem", 1.125)
    t.setdefault("k_fridge_badge_size_rem", 0.80)
    t.setdefault("k_fridge_badge_px", 9)
    t.setdefault("k_fridge_badge_py", 3)
    t.setdefault("k_fridge_badge_min_w", 88)

    t.setdefault("k_shop_header_size_rem", 0.92)
    t.setdefault("k_shop_item_size_rem", 1.34)
    t.setdefault("k_shop_item_h", 50)
    t.setdefault("k_shop_item_gap", 0)

    t.setdefault("k_kitchen_section_gap", 24)
    t.setdefault("k_kitchen_header_mb", 12)
    t.setdefault("k_micro_size_px", 11)
    t.setdefault("k_micro_bold_size_px", 12)
    t.setdefault("k_weather_desc_size_px", 12)
    t.setdefault("k_weather_desc_gap_px", 3)
    t.setdefault("k_inventory_header_size_px", 13)
    t.setdefault("k_inventory_header_offset_y", 2)

    return t


def _font_px(rem: float) -> int:
    return max(1, int(round(float(rem) * 16.0)))


def _visible_tasks(state: AppState):
    fridge = [r for r in state.model.reminders if (r.category or "") == "fridge" and not r.completed]
    shop = [r for r in state.model.reminders if (r.category or "") != "fridge" and not r.completed]
    return fridge, shop


def render_home_kitchen(image, state: AppState, fonts, theme: dict) -> None:
    theme = _theme(theme)

    draw = ImageDraw.Draw(image)
    w, h = image.size

    bg = theme.get("bg", (229, 229, 229))
    card = theme.get("card", (252, 252, 252))
    ink = theme.get("ink", (17, 17, 17))
    muted = theme.get("muted", (160, 160, 160))

    if image.mode == "RGB":
        bg = _to_rgb(bg)
        card = _to_rgb(card)
        ink = _to_rgb(ink)
        muted = _to_rgb(muted)
    else:
        # 1-bit mode: accept lists/tuples but collapse to ink/card integers.
        if not isinstance(card, int):
            card = 255
        if not isinstance(ink, int):
            ink = 0
        if not isinstance(muted, int):
            muted = ink

    # Base background already filled by caller; ensure the inner surface is paper-white.
    draw.rectangle((0, 0, w, h), fill=card)

    pad = int(theme["k_container_padding"])
    left_w = int(theme["k_left_column_width"])
    right_x = left_w
    left_box = (0, 0, left_w, h)
    right_box = (right_x, 0, w, h)

    # Fonts (keyed to our on-disk TTFs)
    f_serif = "playfair_regular"
    f_serif_italic = "playfair_italic"
    f_sans = "inter_regular"
    f_sans_medium = "inter_medium"
    f_sans_bold = "inter_bold"
    f_mono = "jet_bold"

    # Compute sizes
    time_font = fonts.get(f_serif, _font_px(theme["k_clock_size_rem"]))
    weekday_font = fonts.get("inter_black", _font_px(theme["k_date_size_rem"]))
    month_font = fonts.get(f_serif, _font_px(theme["k_date_size_rem"] * 0.9))
    temp_font = fonts.get(f_sans_bold, 36)
    tiny_ui = fonts.get(f_sans_medium, int(theme["k_micro_size_px"]))
    tiny_ui_bold = fonts.get(f_sans_bold, int(theme["k_micro_bold_size_px"]))
    weather_desc_font = fonts.get(f_sans_medium, int(theme["k_weather_desc_size_px"]))

    # Left panel focus ring (simple)
    focus_idx = int(state.ui.focused_index or 0)
    if not state.ui.idle and focus_idx == 0:
        rounded_rect(
            draw,
            (2, 2, left_w - 2, h - 2),
            radius=12,
            outline=ink,
            width=4,
            fill=None,
        )

    # --- MOOD PANEL ---
    now = datetime.now()
    time_str = now.strftime("%H:%M")
    weekday = now.strftime("%A").upper()
    month_day = now.strftime("%B %-d") if hasattr(now, "strftime") else now.strftime("%B %d")

    # Header divider
    header_pad_top = int(theme["k_mood_pad_top"])
    y = header_pad_top

    # Huge time
    nudge_em = float(theme["k_clock_nudge_em"])
    time_y = y + int(nudge_em * _font_px(theme["k_clock_size_rem"]))
    time_x = pad - 12
    draw.text((time_x, time_y), time_str, font=time_font, fill=ink)
    time_bbox = draw.textbbox((time_x, time_y), time_str, font=time_font)

    # Info row: date left, weather right. Use actual time bbox to avoid overlaps.
    info_y = int(time_bbox[3]) + int(theme["k_clock_info_gap_px"])

    # Weekday + month day
    weekday_w, weekday_h = text_size(draw, weekday, weekday_font)
    draw.text((pad, info_y), weekday, font=weekday_font, fill=ink)
    month_y = info_y + weekday_h + int(theme["k_weekday_month_gap_px"])
    month_w, month_h = text_size(draw, month_day, month_font)
    draw.text((pad, month_y), month_day, font=month_font, fill=ink)
    left_info_bottom = month_y + month_h

    # Weather snippet (use first day as "today")
    weather_bottom = left_info_bottom
    if state.model.weather:
        w0 = state.model.weather[0]
        temp = f"{int(w0.hi)}°"
        desc = (getattr(w0, "icon", "") or "SUNNY").upper()
        # place on right side of left panel
        temp_w, temp_h = text_size(draw, temp, temp_font)
        icon_size = int(theme["k_weather_icon_size"])
        wx = left_w - pad - icon_size - 18 - temp_w
        wy = info_y - 2
        draw.text((wx, wy), temp, font=temp_font, fill=ink)
        temp_bbox = draw.textbbox((wx, wy), temp, font=temp_font)
        # description under temp
        dword = desc.split("_")[0]
        dw, dh = text_size(draw, dword, weather_desc_font)
        desc_y = int(temp_bbox[3]) + int(theme["k_weather_desc_gap_px"])
        draw.text((wx + temp_w - dw, desc_y), dword, font=weather_desc_font, fill=ink)
        # icon
        icon_y = wy + 4
        draw_weather_icon(draw, w0.icon, left_w - pad - icon_size, icon_y, size=icon_size, ink=ink, stroke=int(theme["k_icon_stroke"]))
        weather_bottom = max(int(temp_bbox[3]), desc_y + dh, icon_y + icon_size)

    # Bottom rule
    rule_y = max(left_info_bottom, weather_bottom) + int(theme["k_header_rule_gap_px"])
    draw.line((pad, rule_y, left_w - pad, rule_y), fill=ink, width=int(theme["k_border_thick"]))

    # Memo section
    memos = state.model.memos or []
    memo_idx = int(state.ui.memo_index or 0)
    memo = memos[memo_idx % len(memos)] if memos else None

    # Label (very light)
    label = "FAMILY BOARD"
    label_w, label_h = text_size(draw, label, tiny_ui)
    draw.text((pad, rule_y + 14), label, font=tiny_ui, fill=ink)

    # Quote text
    quote_font = fonts.get(f_serif, _font_px(theme["k_mood_msg_size_rem"]))
    quote_y = rule_y + 86
    if memo:
        quote = f"\"{memo.text}\""
    else:
        quote = "\"No messages.\""

    # soft wrap: very simple (break on spaces)
    max_w = left_w - pad * 2 - 120
    words = quote.split(" ")
    lines = []
    cur = ""
    for wd in words:
        nxt = (cur + " " + wd).strip()
        if text_size(draw, nxt, quote_font)[0] <= max_w or not cur:
            cur = nxt
        else:
            lines.append(cur)
            cur = wd
    if cur:
        lines.append(cur)

    lh = int(text_size(draw, "Ag", quote_font)[1] * float(theme["k_mood_msg_lh"]))
    for i, ln in enumerate(lines[:4]):
        draw.text((pad, quote_y + i * lh), ln, font=quote_font, fill=ink)

    # Timestamp line
    if memo:
        ts = time.strftime("%I:%M %p", time.localtime(memo.timestamp)).lstrip("0")
    else:
        ts = ""
    ts_y = quote_y + min(4, len(lines)) * lh + 10
    draw.line((pad, ts_y, pad + 40, ts_y), fill=ink, width=1)
    if ts:
        draw.text((pad + 50, ts_y - 6), ts.upper(), font=tiny_ui, fill=ink)

    # Author list (right side of mood area)
    if memos:
        author_font = fonts.get(f_sans_medium, 12)
        ax0 = left_w - pad - 90
        # vertical separator
        draw.line((ax0 - 18, rule_y + 70, ax0 - 18, h - pad), fill=(230, 230, 230) if isinstance(card, tuple) else ink, width=2)
        ay = quote_y + 40
        for i, m in enumerate(memos[:6]):
            is_sel = i == memo_idx
            fill = ink if is_sel else muted
            num = f"{i+1}."
            draw.text((ax0, ay), num, font=author_font, fill=fill)
            draw.text((ax0 + 24, ay), m.author, font=author_font, fill=fill)
            if m.is_new:
                draw.ellipse((ax0 + 70, ay + 4, ax0 + 76, ay + 10), fill=ink)
            ay += 28

    # --- KITCHEN PANEL ---
    fridge, shop = _visible_tasks(state)

    # Header: Inventory & Alerts + count
    header_y = pad
    inv_label = "INVENTORY & ALERTS"
    inv_font = fonts.get("inter_semibold", int(theme["k_inventory_header_size_px"]))
    inv_y = header_y + int(theme["k_inventory_header_offset_y"])
    draw.text((right_x + pad, inv_y), inv_label, font=inv_font, fill=ink)
    cnt = str(len(fridge))
    cw, ch = text_size(draw, cnt, tiny_ui_bold)
    draw.text((w - pad - cw, inv_y), cnt, font=tiny_ui_bold, fill=ink)

    # Fridge cards grid (2 cols)
    card_gap = int(theme["k_fridge_card_gap"])
    card_h = int(theme["k_fridge_card_h"])
    grid_y = header_y + int(theme["k_kitchen_header_mb"]) + 18
    col_w = int((w - right_x - pad * 2 - card_gap) / 2)
    title_font = fonts.get(f_sans_bold, _font_px(theme["k_fridge_title_size_rem"]))
    badge_font = fonts.get(f_sans_bold, _font_px(theme["k_fridge_badge_size_rem"]))

    visible_fridge = fridge[:4]
    for i, item in enumerate(visible_fridge):
        r = i // 2
        c = i % 2
        x0 = right_x + pad + c * (col_w + card_gap)
        y0 = grid_y + r * (card_h + card_gap)
        x1 = x0 + col_w
        y1 = y0 + card_h

        is_focus = (not state.ui.idle and focus_idx > 0 and _kitchen_focus_rid(state, focus_idx) == item.rid)
        fill = (243, 244, 246) if (isinstance(card, tuple) and is_focus) else card
        rounded_rect(draw, (x0, y0, x1, y1), radius=0, outline=ink, width=int(theme["k_border_thin"]) + 1, fill=fill)

        title = truncate_text(draw, item.title, title_font, col_w - 24)
        draw.text((x0 + 12, y0 + 10), title, font=title_font, fill=ink)

        badge = (item.right or "STOCKED").upper()
        badge = truncate_text(draw, badge, badge_font, col_w - 24 - int(theme["k_fridge_badge_px"]) * 2)
        bw, bh = text_size(draw, badge, badge_font)
        bx0 = x0 + 12
        by0 = y1 - 12 - (bh + int(theme["k_fridge_badge_py"]) * 2)
        min_w = int(theme.get("k_fridge_badge_min_w", 88))
        badge_w = max(min_w, bw + int(theme["k_fridge_badge_px"]) * 2)
        bx1 = bx0 + badge_w
        by1 = by0 + bh + int(theme["k_fridge_badge_py"]) * 2
        draw.rectangle((bx0, by0, bx1, by1), fill=ink)
        draw.text((bx0 + int(theme["k_fridge_badge_px"]), by0 + int(theme["k_fridge_badge_py"])), badge, font=badge_font, fill=card)

        if is_focus:
            # small check mark
            cx = x1 - 22
            cy = y0 + 14
            draw.rectangle((cx - 2, cy - 2, cx + 12, cy + 12), outline=ink, width=2, fill=None)
            draw.line((cx, cy + 6, cx + 4, cy + 10), fill=ink, width=2)
            draw.line((cx + 4, cy + 10, cx + 12, cy), fill=ink, width=2)

    # Shopping list header
    shop_y = grid_y + (2 * (card_h + card_gap)) + int(theme["k_kitchen_section_gap"])
    # left rule
    draw.line((right_x + pad, shop_y, right_x + pad + 26, shop_y), fill=ink, width=2)
    shop_title = "SHOPPING LIST"
    shop_font = fonts.get(f_sans_bold, _font_px(theme["k_shop_header_size_rem"]))
    stw, sth = text_size(draw, shop_title, shop_font)
    draw.text((right_x + pad + 42, shop_y - sth // 2), shop_title, font=shop_font, fill=ink)
    # right thin line
    draw.line((right_x + pad + 42 + stw + 16, shop_y, w - pad, shop_y), fill=(220, 220, 220) if isinstance(card, tuple) else ink, width=1)

    # Shopping items list
    item_font = fonts.get(f_sans_medium, _font_px(theme["k_shop_item_size_rem"]))
    row_h = int(theme["k_shop_item_h"])
    y = shop_y + 18
    for item in shop[:6]:
        is_focus = (not state.ui.idle and focus_idx > 0 and _kitchen_focus_rid(state, focus_idx) == item.rid)
        if is_focus:
            draw.rectangle((right_x + 0, y, w, y + row_h), fill=ink)
            fill = card
        else:
            fill = ink
        draw.line((right_x + pad, y + row_h, w - pad, y + row_h), fill=(235, 235, 235) if isinstance(card, tuple) else ink, width=1)
        draw.text((right_x + 12, y + (row_h - text_size(draw, "Ag", item_font)[1]) // 2), item.title, font=item_font, fill=fill)
        if is_focus:
            # check on right
            cx = w - pad - 18
            cy = y + row_h // 2 - 6
            draw.rectangle((cx - 2, cy - 2, cx + 12, cy + 12), outline=card, width=2, fill=None)
            draw.line((cx, cy + 6, cx + 4, cy + 10), fill=card, width=2)
            draw.line((cx + 4, cy + 10, cx + 12, cy), fill=card, width=2)
        y += row_h + int(theme["k_shop_item_gap"])


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
