from __future__ import annotations

from datetime import datetime
import time

from PIL import ImageDraw

from app.core.state import AppState
from app.shared.draw import draw_weather_icon, rounded_rect, text_size, truncate_text


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
    t.setdefault("b_outer_border", 3)
    t.setdefault("b_split_ratio", 0.60)
    t.setdefault("b_divider_w", 2)
    t.setdefault("b_show_focus_ring", False)

    # Left block
    t.setdefault("b_left_pad", 24)
    t.setdefault("b_time_size", 92)
    t.setdefault("b_weekday_size", 18)
    t.setdefault("b_date_size", 13)
    t.setdefault("b_temp_size", 52)
    t.setdefault("b_weather_desc_size", 12)
    t.setdefault("b_weather_icon_size", 28)
    t.setdefault("b_header_gap", 16)
    t.setdefault("b_left_micro_size", 12)
    t.setdefault("b_quote_size", 23)
    t.setdefault("b_quote_lh", 1.18)
    t.setdefault("b_posted_size", 12)
    t.setdefault("b_author_size", 12)

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
    parts = icon.split("_")
    if not parts:
        return "SUN"
    if parts[0] == "partly" and len(parts) > 1:
        return "PARTLY"
    return parts[0].upper()


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
    subtle = _gray_like(int(t["b_subtle_gray"]), ink)

    draw.rectangle((0, 0, w, h), fill=card)

    # Outer frame and split
    m = int(t["b_margin"])
    ox0, oy0, ox1, oy1 = m, m, w - m, h - m
    rounded_rect(
        draw,
        (ox0, oy0, ox1, oy1),
        radius=int(t["b_outer_radius"]),
        outline=ink,
        width=int(t["b_outer_border"]),
        fill=card,
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
    f_weekday = fonts.get("inter_black", _font_px(t["b_weekday_size"]))
    f_date = fonts.get("inter_medium", _font_px(t["b_date_size"]))
    f_temp = fonts.get("inter_black", _font_px(t["b_temp_size"]))
    f_weather_desc = fonts.get("inter_semibold", _font_px(t["b_weather_desc_size"]))
    f_micro = fonts.get("inter_medium", _font_px(t["b_left_micro_size"]))
    f_quote = fonts.get("playfair_bold", _font_px(t["b_quote_size"]))
    f_posted = fonts.get("inter_semibold", _font_px(t["b_posted_size"]))
    f_author = fonts.get("inter_bold", _font_px(t["b_author_size"]))

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
    month_day = now.strftime("%B %-d") if hasattr(now, "strftime") else now.strftime("%B %d")

    draw.text((lx0, top_y), time_str, font=f_time, fill=ink)
    time_box = draw.textbbox((lx0, top_y), time_str, font=f_time)

    wy = time_box[3] + 6
    draw.text((lx0, wy), weekday, font=f_weekday, fill=ink)
    ww, wh = text_size(draw, weekday, f_weekday)

    dy = wy + wh + 2
    draw.text((lx0, dy), month_day, font=f_date, fill=ink)
    _, dh = text_size(draw, month_day, f_date)

    weather_bottom = dy + dh
    if state.model.weather:
        w0 = state.model.weather[0]
        temp_str = f"{int(w0.hi)}°"
        temp_w, temp_h = text_size(draw, temp_str, f_temp)
        icon_size = int(t["b_weather_icon_size"])

        icon_x = lx1 - icon_size
        temp_x = icon_x - 16 - temp_w
        temp_y = wy - 2
        draw.text((temp_x, temp_y), temp_str, font=f_temp, fill=ink)

        desc = _weather_word(getattr(w0, "icon", "sun"))
        dw, dh2 = text_size(draw, desc, f_weather_desc)
        desc_y = temp_y + temp_h + 2
        draw.text((temp_x + temp_w - dw, desc_y), desc, font=f_weather_desc, fill=ink)

        draw_weather_icon(draw, w0.icon, icon_x, temp_y + 4, size=icon_size, ink=ink, stroke=2)
        weather_bottom = max(weather_bottom, desc_y + dh2, temp_y + 4 + icon_size)

    header_rule_y = weather_bottom + int(t["b_header_gap"])
    draw.line((lx0, header_rule_y, lx1, header_rule_y), fill=ink, width=3)

    label_y = header_rule_y + 16
    draw.text((lx0, label_y), "FAMILY BOARD", font=f_micro, fill=muted)

    memos = state.model.memos or []
    memo_idx = int(state.ui.memo_index or 0)
    memo = memos[memo_idx % len(memos)] if memos else None

    quote_y = label_y + 46
    quote = f"\"{memo.text}\"" if memo else '"No messages."'

    quote_right_guard = 120
    max_quote_w = max(120, (lx1 - lx0) - quote_right_guard)
    words = quote.split(" ")
    lines = []
    cur = ""
    for wd in words:
        nxt = (cur + " " + wd).strip()
        if not cur or text_size(draw, nxt, f_quote)[0] <= max_quote_w:
            cur = nxt
        else:
            lines.append(cur)
            cur = wd
    if cur:
        lines.append(cur)

    qh = text_size(draw, "Ag", f_quote)[1]
    qlh = max(1, int(qh * float(t["b_quote_lh"])))
    for i, ln in enumerate(lines[:4]):
        draw.text((lx0, quote_y + i * qlh), ln, font=f_quote, fill=ink)

    posted_y = quote_y + min(4, len(lines)) * qlh + 8
    draw.line((lx0, posted_y, lx0 + 44, posted_y), fill=ink, width=1)
    posted = time.strftime("%I:%M %p", time.localtime(memo.timestamp)).lstrip("0") if memo else ""
    if posted:
        draw.text((lx0 + 54, posted_y - 7), posted.upper(), font=f_posted, fill=ink)

    # Author list
    ax = lx1 - 88
    ay = quote_y + 30
    inactive = muted
    for i, m_item in enumerate(memos[:3]):
        sel = i == memo_idx
        fill = ink if sel else inactive
        draw.text((ax, ay), f"{i+1}.", font=f_author, fill=fill)
        draw.text((ax + 22, ay), m_item.author, font=f_author, fill=fill)
        if m_item.is_new:
            draw.ellipse((ax + 84, ay + 5, ax + 92, ay + 13), fill=ink)
        ay += 28

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
