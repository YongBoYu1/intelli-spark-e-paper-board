from __future__ import annotations

from datetime import date, datetime, timedelta

from PIL import ImageDraw

from app.core.state import AppState
from app.shared.draw import truncate_text, text_size, rounded_rect, draw_checkbox


def render_calendar(image, state: AppState, fonts, theme: dict) -> None:
    """Calendar detail view closely matching TSX CalendarView.tsx."""
    draw = ImageDraw.Draw(image)
    w, h = image.size

    ink = theme.get("ink", 0)
    card = theme.get("card", 255)
    muted = theme.get("muted", ink)

    # For RGB themes we use light grays similar to TSX; for 1-bit everything becomes white anyway.
    gray_50 = (249, 250, 251) if isinstance(card, tuple) else 255
    gray_200 = (229, 231, 235) if isinstance(card, tuple) else 255
    gray_300 = (209, 213, 219) if isinstance(card, tuple) else ink

    border_w = int(theme.get("detail_border_width", 4) or 4)
    divider_w = int(theme.get("detail_divider_width", 4) or 4)
    radius = int(theme.get("card_radius", 12) or 12) + 4

    # Outer container
    draw.rectangle((0, 0, w, h), fill=card)
    rounded_rect(draw, (0, 0, w - 1, h - 1), radius=radius, outline=ink, width=border_w, fill=card)

    left_w = int(w * 0.45)
    right_x = left_w

    # Left column background + divider
    draw.rectangle((0, 0, left_w, h), fill=gray_50)
    draw.rectangle((right_x - divider_w // 2, 0, right_x + divider_w // 2, h), fill=ink)

    pad = 24
    month_font = fonts.get("inter_black", 30)
    year_font = fonts.get("jet_bold", 18)
    week_font = fonts.get("inter_bold", 12)
    day_font = fonts.get("jet_bold", 12)

    # Date model: cursor follows rotary-driven offset.
    now_dt = datetime.now()
    today = now_dt.date()
    off = int(state.ui.calendar_offset_days or 0)
    cursor = today + timedelta(days=off)
    year = cursor.year
    month = cursor.month
    month_name = cursor.strftime("%B").upper()

    draw.text((pad, pad), month_name, font=month_font, fill=ink)
    draw.text((pad, pad + 36), str(year), font=year_font, fill=muted)

    # Calendar grid
    grid_top = pad + 76
    cell_h = 40
    cell_w = int((left_w - pad * 2) / 7)

    week = ["S", "M", "T", "W", "T", "F", "S"]
    for i, ch in enumerate(week):
        tw, th = text_size(draw, ch, week_font)
        x = pad + i * cell_w + (cell_w - tw) // 2
        draw.text((x, grid_top), ch, font=week_font, fill=muted)

    # First day of month
    first = cursor.replace(day=1)
    start_offset = int(first.weekday() + 1) % 7  # Python Mon=0, TSX Sun=0
    # Days in month
    next_month = (first.replace(day=28) + timedelta(days=4)).replace(day=1)
    days_in_month = (next_month - first).days

    def iso(d):
        return d.strftime("%Y-%m-%d")

    today_iso = iso(now_dt)
    cursor_iso = iso(datetime(cursor.year, cursor.month, cursor.day))

    # Place each day
    x0 = pad
    y0 = grid_top + 18
    for day in range(1, days_in_month + 1):
        idx = start_offset + (day - 1)
        row = idx // 7
        col = idx % 7
        cx = x0 + col * cell_w + cell_w // 2
        cy = y0 + row * cell_h + 16

        is_selected = (day == cursor.day)
        is_today = (day == today.day and off == 0 and month == today.month and year == today.year)

        # Circle chip (w-8/h-8)
        r = 16
        if is_selected:
            draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=ink, outline=ink, width=2)
            fill = card
        else:
            # hover not applicable; draw only outline ring for today
            if is_today:
                draw.ellipse((cx - r, cy - r, cx + r, cy + r), outline=ink, width=2)
            fill = ink

        label = str(day)
        lw, lh = text_size(draw, label, day_font)
        draw.text((cx - lw // 2, cy - lh // 2), label, font=day_font, fill=fill)

        # Dot indicators (events + incomplete tasks) like TSX
        # We don't have per-day dates yet in the model; approximate:
        # Only show dots for the currently-selected cursor day (we don't have real dates yet).
        has_event = (day == cursor.day and off == 0 and len(state.model.calendar) > 0)
        has_task = (day == cursor.day and off == 0 and any(not r.completed for r in state.model.reminders))
        dot_y = cy + r + 4
        dot_r = 2
        dx = cx - 4
        if has_event:
            draw.ellipse((dx - dot_r, dot_y, dx + dot_r, dot_y + dot_r * 2), fill=card if is_selected else ink)
            dx += 6
        if has_task:
            # hollow dot
            outline = card if is_selected else ink
            draw.ellipse((dx - dot_r, dot_y, dx + dot_r, dot_y + dot_r * 2), outline=outline, width=1)

    # Left footer hints are dev-only; keep them hidden on hardware by default.
    if bool(theme.get("calendar_show_hints", False)):
        footer_y = h - 92
        draw.line((pad, footer_y, left_w - pad, footer_y), fill=gray_200, width=2)
        hint_font = fonts.get("jet_bold", 10)
        kbd_font = fonts.get("jet_bold", 10)
        lines = [
            ("\u2190\u2192", "CHANGE DATE"),
            ("\u2191\u2193", "SELECT ITEM"),
            ("ENTER", "TOGGLE TASK"),
        ]
        y = footer_y + 12
        for kbd, txt in lines:
            kw, kh = text_size(draw, kbd, kbd_font)
            bx0 = pad
            by0 = y - 2
            bx1 = bx0 + kw + 10
            by1 = by0 + kh + 6
            rounded_rect(draw, (bx0, by0, bx1, by1), radius=4, outline=gray_300, width=1, fill=card)
            draw.text((bx0 + 5, y + 1), kbd, font=kbd_font, fill=ink)
            draw.text((bx1 + 10, y + 1), txt, font=hint_font, fill=muted)
            y += 22

    # Right column
    right_w = w - right_x
    header_h = 86
    header_pad = 26
    draw.rectangle((right_x, 0, w, header_h), fill=card)
    draw.line((right_x, header_h, w, header_h), fill=ink, width=2)

    weekday_font = fonts.get("jet_bold", 11)
    title_font = fonts.get("inter_black", 24)
    weekday = cursor.strftime("%A").upper()
    try:
        date_title = cursor.strftime("%B %-d").upper()
    except Exception:
        date_title = cursor.strftime("%B %d").upper()
    draw.text((right_x + header_pad, 22), weekday, font=weekday_font, fill=muted)
    draw.text((right_x + header_pad, 42), date_title, font=title_font, fill=ink)

    esc = "ESC"
    esc_w, esc_h = text_size(draw, esc, weekday_font)
    draw.text((w - header_pad - esc_w, 24), esc, font=weekday_font, fill=muted)

    # Agenda items: only show content for "today" until mobile provides real dates.
    if off != 0:
        free = "FREE DAY"
        fw, fh = text_size(draw, free, title_font)
        draw.text((right_x + (right_w - fw) / 2, header_h + 120), free, font=title_font, fill=muted)
        return

    # Agenda items: events first, then tasks (tasks are reminders here).
    list_x0 = right_x + 18
    list_x1 = w - 18
    y = header_h + 18
    gap = 12

    event_time_font = fonts.get("jet_bold", 12)
    event_tag_font = fonts.get("jet_bold", 10)
    event_title_font = fonts.get("inter_bold", 20)

    task_title_font = fonts.get("inter_medium", 18)
    task_meta_font = fonts.get("jet_bold", 10)

    selected = int(state.ui.calendar_selected_index or 0)
    mode = (state.ui.calendar_mode or "date")

    # Render events (from model)
    for i, ev in enumerate(state.model.calendar[:3]):
        # border-l highlight
        box_h = 62
        is_sel = (mode == "agenda" and selected == i)
        draw.line((list_x0, y, list_x0, y + box_h), fill=ink if is_sel else gray_300, width=4)
        if is_sel:
            draw.rectangle((list_x0 + 4, y, list_x1, y + box_h), fill=gray_50)

        # time pill
        time_txt = (ev.when or "08:00").split()[-1]
        pill_w, pill_h = text_size(draw, time_txt, event_time_font)
        pill_box = (list_x0 + 14, y + 6, list_x0 + 14 + pill_w + 10, y + 6 + pill_h + 6)
        rounded_rect(draw, pill_box, radius=4, outline=gray_300, width=1, fill=gray_200)
        draw.text((pill_box[0] + 5, pill_box[1] + 3), time_txt, font=event_time_font, fill=ink)
        draw.text((pill_box[2] + 10, pill_box[1] + 4), "EVENT", font=event_tag_font, fill=muted)
        draw.text((list_x0 + 14, y + 34), truncate_text(draw, ev.title, event_title_font, list_x1 - (list_x0 + 14)), font=event_title_font, fill=ink)

        y += box_h + gap

    # Render a few tasks (reminders)
    for ti, r in enumerate(state.model.reminders[:4]):
        box_h = 62
        box = (list_x0, y, list_x1, y + box_h)
        fill = (243, 244, 246) if (isinstance(card, tuple) and r.completed) else card
        outline = ink if not r.completed else gray_200
        is_sel = (mode == "agenda" and selected == (len(state.model.calendar) + ti))
        rounded_rect(draw, box, radius=10, outline=outline, width=2, fill=fill)
        if is_sel:
            rounded_rect(draw, box, radius=10, outline=ink, width=3, fill=fill)

        cb = 22
        cb_x = list_x0 + 14
        cb_y = y + (box_h - cb) // 2
        draw_checkbox(draw, cb_x, cb_y, cb, checked=r.completed, outline=outline, fill=fill, check_fill=outline, width=2)

        text_x = cb_x + cb + 12
        title = truncate_text(draw, r.title, task_title_font, (list_x1 - text_x) - 16)
        title_fill = muted if r.completed else ink
        draw.text((text_x, y + 14), title, font=task_title_font, fill=title_fill)

        if r.right:
            meta = f"DUE: {r.right}"
            draw.text((text_x, y + 38), meta.upper(), font=task_meta_font, fill=muted)

        y += box_h + 10
