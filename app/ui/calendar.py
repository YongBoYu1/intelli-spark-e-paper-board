from __future__ import annotations

from datetime import date, datetime, timedelta

from PIL import ImageDraw

from app.core.calendar_utils import events_for_date, resolve_event_date
from app.core.state import AppState
from app.shared.draw import truncate_text, text_size, draw_checkbox
from app.shared.panel_font_templates import apply_panel_font_template


def render_calendar(image, state: AppState, fonts, theme: dict) -> None:
    theme = apply_panel_font_template(theme)
    draw = ImageDraw.Draw(image)
    if bool(theme.get("panel_mode", False)) or not bool(theme.get("panel_text_antialias", False)):
        try:
            draw.fontmode = "1"
        except Exception:
            pass

    w, h = image.size

    ink = theme.get("ink", 0)
    card = theme.get("card", 255)
    muted = theme.get("muted", ink)
    border = theme.get("border", ink)

    body_key = str(theme.get("panel_font_body_key") or "inter_medium")
    body_focus_key = str(theme.get("panel_font_body_focus_key") or "inter_bold")
    meta_key = str(theme.get("panel_font_meta_key") or "jet_bold")
    body_base = max(12, int(theme.get("panel_font_body_size", 18) or 18))
    meta_base = max(11, int(theme.get("panel_font_meta_size", 13) or 13))

    month_font = fonts.get(body_focus_key, max(30, int(body_base * 1.75)))
    year_font = fonts.get(meta_key, max(16, meta_base + 2))
    week_font = fonts.get(body_focus_key, max(14, int(body_base * 0.78)))

    weekday_font = fonts.get(meta_key, max(14, meta_base + 1))
    right_title_font = fonts.get(body_focus_key, max(28, int(body_base * 1.65)))
    mode_font = fonts.get(meta_key, max(12, meta_base))
    row_title_font = fonts.get(body_key, max(18, int(body_base + 1)))
    row_focus_font = fonts.get(body_focus_key, max(18, int(body_base + 1)))
    row_meta_font = fonts.get(meta_key, max(12, meta_base - 1))
    footer_font = fonts.get(meta_key, max(11, meta_base - 1))

    # Base frame
    draw.rectangle((0, 0, w, h), fill=card)
    draw.rectangle((0, 0, w - 1, h - 1), outline=ink, width=2)

    left_ratio = float(theme.get("calendar_left_ratio", 0.45) or 0.45)
    left_ratio = max(0.36, min(0.56, left_ratio))
    left_w = int(w * left_ratio)
    right_x = left_w
    draw.line((right_x, 0, right_x, h), fill=ink, width=2)

    # Date model
    now_dt = datetime.now()
    today = now_dt.date()
    off = int(state.ui.calendar_offset_days or 0)
    cursor = today + timedelta(days=off)
    year = cursor.year
    month = cursor.month
    month_name = cursor.strftime("%B").upper()

    # Left column: month grid
    left_pad = 18
    header_y = 14
    draw.text((left_pad, header_y), month_name, font=month_font, fill=ink)
    month_h = text_size(draw, month_name, month_font)[1]
    year_y = header_y + month_h + 8
    draw.text((left_pad, year_y), str(year), font=year_font, fill=muted)
    year_h = text_size(draw, str(year), year_font)[1]

    # Keep a larger vertical gap for e-ink readability and to avoid month/year overlap.
    week_row_y = year_y + year_h + 16
    grid_top = week_row_y + 30
    grid_bottom = h - 44
    grid_h = max(120, grid_bottom - grid_top)
    cell_w = max(24, int((left_w - (left_pad * 2)) / 7))
    cell_h = max(24, int(grid_h / 6))
    day_font_size = max(14, min(24, int(cell_h * 0.52)))
    day_font = fonts.get(meta_key, day_font_size)

    week = ["S", "M", "T", "W", "T", "F", "S"]
    for i, ch in enumerate(week):
        tw, th = text_size(draw, ch, week_font)
        x = left_pad + i * cell_w + (cell_w - tw) // 2
        draw.text((x, week_row_y), ch, font=week_font, fill=muted)

    # Month shape
    first = cursor.replace(day=1)
    start_offset = int(first.weekday() + 1) % 7
    next_month = (first.replace(day=28) + timedelta(days=4)).replace(day=1)
    days_in_month = (next_month - first).days

    # Day cells
    x0 = left_pad
    y0 = grid_top
    calendar_events = list(state.model.calendar or [])
    reminder_events = list(state.model.reminders or [])
    event_dates = [resolve_event_date(ev, base_date=today) for ev in calendar_events]
    task_dates = [resolve_event_date(r, base_date=today) for r in reminder_events]
    event_days: set[int] = {d.day for d in event_dates if d is not None and d.year == year and d.month == month}
    task_days: set[int] = {d.day for d in task_dates if d is not None and d.year == year and d.month == month}
    if today.year == year and today.month == month:
        if any(d is None for d in event_dates):
            event_days.add(today.day)
        if any(d is None for d in task_dates):
            task_days.add(today.day)

    for day in range(1, days_in_month + 1):
        idx = start_offset + (day - 1)
        row = idx // 7
        col = idx % 7
        cx0 = x0 + col * cell_w
        cy0 = y0 + row * cell_h
        cx1 = cx0 + cell_w
        cy1 = cy0 + cell_h
        cx = (cx0 + cx1) // 2
        cy = (cy0 + cy1) // 2 - 2

        is_selected = (day == cursor.day)
        is_today = (day == today.day and off == 0 and month == today.month and year == today.year)

        # Base cell separator
        draw.rectangle((cx0, cy0, cx1, cy1), outline=border, width=1, fill=card)

        # Selected / today emphasis
        if is_selected:
            draw.rectangle((cx0 + 1, cy0 + 1, cx1 - 1, cy1 - 1), fill=ink)
            label_fill = card
        else:
            if is_today:
                draw.rectangle((cx0 + 2, cy0 + 2, cx1 - 2, cy1 - 2), outline=ink, width=2)
            label_fill = ink

        label = str(day)
        lw, lh = text_size(draw, label, day_font)
        draw.text((cx - lw // 2, cy - lh // 2), label, font=day_font, fill=label_fill)

        # Event/task markers for the specific day.
        has_event = day in event_days
        has_task = day in task_days
        dot_y = cy1 - 8
        dot_r = 2
        dx = cx - 5
        dot_fill = card if is_selected else ink
        if has_event:
            draw.ellipse((dx - dot_r, dot_y, dx + dot_r, dot_y + dot_r * 2), fill=dot_fill)
            dx += 6
        if has_task:
            draw.ellipse((dx - dot_r, dot_y, dx + dot_r, dot_y + dot_r * 2), outline=dot_fill, width=1)

    # Right column header
    right_w = w - right_x
    header_h = 92
    header_pad = 20
    draw.line((right_x, header_h, w, header_h), fill=ink, width=2)

    weekday = cursor.strftime("%A").upper()
    try:
        date_title = cursor.strftime("%B %-d").upper()
    except Exception:
        date_title = cursor.strftime("%B %d").upper()
    draw.text((right_x + header_pad, 18), weekday, font=weekday_font, fill=muted)
    draw.text((right_x + header_pad, 38), date_title, font=right_title_font, fill=ink)

    mode = str(state.ui.calendar_mode or "date").strip().lower()

    # Right column list area
    list_x0 = right_x + 14
    list_x1 = w - 14
    list_top = header_h + 10
    list_bottom = h - 34
    row_h = 56
    row_gap = 8

    # Build agenda rows for the selected date: events first, then reminders.
    selected_events = events_for_date(calendar_events, target_date=cursor, base_date=today)
    selected_tasks = events_for_date(reminder_events, target_date=cursor, base_date=today)
    items: list[dict] = []
    for ev in selected_events:
        items.append({"kind": "event", "title": str(ev.title or ""), "when": str(ev.when or "")})
    for r in selected_tasks:
        items.append(
            {
                "kind": "task",
                "title": str(r.title or ""),
                "when": str(r.right or ""),
                "completed": bool(r.completed),
            }
        )

    if not items:
        empty_title = "NO EVENTS"
        empty_sub = "Voice can add reminders and memos"
        tw, th = text_size(draw, empty_title, right_title_font)
        sw, sh = text_size(draw, empty_sub, mode_font)
        cx = right_x + (right_w // 2)
        cy = list_top + ((list_bottom - list_top) // 2)
        draw.text((cx - (tw // 2), cy - th), empty_title, font=right_title_font, fill=muted)
        draw.text((cx - (sw // 2), cy + 8), empty_sub, font=mode_font, fill=muted)
        if mode == "agenda":
            footer = "ROTATE: ITEM  CLICK: TOGGLE TASK  BACK: HOME"
        else:
            footer = "ROTATE: DATE  CLICK: OPEN AGENDA  BACK: HOME"
        footer = truncate_text(draw, footer, footer_font, max(80, w - 24))
        draw.text((12, h - 24), footer, font=footer_font, fill=muted)
        return

    slots = max(1, (list_bottom - list_top + row_gap) // (row_h + row_gap))
    selected = int(state.ui.calendar_selected_index or 0)
    if mode == "agenda":
        selected = max(0, min(selected, len(items) - 1))
    else:
        selected = 0
    start = 0
    if len(items) > slots:
        start = max(0, min(selected - (slots // 2), len(items) - slots))
    visible_items = items[start : start + slots]

    y = list_top
    for i, item in enumerate(visible_items):
        global_idx = start + i
        is_sel = (mode == "agenda" and global_idx == selected)
        box = (list_x0, y, list_x1, y + row_h)
        if is_sel:
            draw.rectangle(box, fill=ink)
        else:
            draw.rectangle(box, outline=border, width=1, fill=card)

        text_fill = card if is_sel else ink
        meta_fill = card if is_sel else muted
        title_font = row_focus_font if is_sel else row_title_font

        if item["kind"] == "event":
            when_txt = truncate_text(draw, str(item.get("when") or "EVENT").upper(), row_meta_font, max(48, int((list_x1 - list_x0) * 0.28)))
            title = truncate_text(draw, str(item.get("title") or "(untitled)"), title_font, int((list_x1 - list_x0) * 0.72))
            draw.text((list_x0 + 10, y + 10), title, font=title_font, fill=text_fill)
            ww = text_size(draw, when_txt, row_meta_font)[0]
            draw.text((list_x1 - ww - 10, y + 12), when_txt, font=row_meta_font, fill=meta_fill)
            draw.text((list_x0 + 10, y + 33), "EVENT", font=row_meta_font, fill=meta_fill)
        else:
            cb = 18
            cb_x = list_x0 + 10
            cb_y = y + (row_h - cb) // 2
            draw_checkbox(
                draw,
                cb_x,
                cb_y,
                cb,
                checked=bool(item.get("completed", False)),
                outline=text_fill,
                fill=(ink if is_sel else card),
                check_fill=text_fill,
                width=2,
            )
            text_x = cb_x + cb + 10
            title = truncate_text(draw, str(item.get("title") or "(untitled)"), title_font, (list_x1 - text_x) - 14)
            draw.text((text_x, y + 9), title, font=title_font, fill=text_fill)
            when_txt = str(item.get("when") or "").strip()
            meta = ("DUE: " + when_txt).upper() if when_txt else ("DONE" if bool(item.get("completed")) else "TASK")
            draw.text((text_x, y + 32), truncate_text(draw, meta, row_meta_font, (list_x1 - text_x) - 14), font=row_meta_font, fill=meta_fill)

        y += row_h + row_gap

    hidden = max(0, len(items) - len(visible_items) - start)
    if hidden > 0:
        more = f"+{hidden} MORE"
        mw, mh = text_size(draw, more, row_meta_font)
        draw.text((list_x1 - mw - 4, list_bottom - mh - 2), more, font=row_meta_font, fill=muted)

    if mode == "agenda":
        footer = "ROTATE: ITEM  CLICK: TOGGLE TASK  BACK: HOME"
    else:
        footer = "ROTATE: DATE  CLICK: OPEN AGENDA  BACK: HOME"
    footer = truncate_text(draw, footer, footer_font, max(80, w - 24))
    draw.text((12, h - 24), footer, font=footer_font, fill=muted)
