from __future__ import annotations

from PIL import ImageDraw

from app.core.state import AppState
from app.shared.draw import draw_text_spaced, text_width_spaced, truncate_text
from app.shared.panel_font_templates import apply_panel_font_template


def _section_indices(state: AppState) -> tuple[list[int], list[int]]:
    inventory: list[int] = []
    reminders: list[int] = []
    for i, r in enumerate(state.model.reminders):
        if str(r.category or "") == "fridge":
            inventory.append(i)
        else:
            reminders.append(i)
    return inventory, reminders


def _window_start(total: int, slots: int, selected: int | None) -> int:
    if total <= slots:
        return 0
    if selected is None:
        return 0
    return max(0, min(int(selected) - (slots // 2), total - slots))


def render_unified_list(image, state: AppState, fonts, theme: dict) -> None:
    theme = apply_panel_font_template(theme)
    draw = ImageDraw.Draw(image)
    if bool(theme.get("panel_mode", False)) or not bool(theme.get("panel_text_antialias", False)):
        try:
            draw.fontmode = "1"
        except Exception:
            pass

    w, h = image.size
    bg = theme.get("card", 255)
    ink = theme.get("ink", 0)
    muted = theme.get("muted", ink)
    border = theme.get("border", ink)
    draw.rectangle((0, 0, w, h), fill=bg)

    body_key = str(theme.get("panel_font_body_key") or "inter_medium")
    body_focus_key = str(theme.get("panel_font_body_focus_key") or "inter_bold")
    meta_key = str(theme.get("panel_font_meta_key") or "jet_bold")
    body_base = max(12, int(theme.get("panel_font_body_size", 18) or 18))
    meta_base = max(11, int(theme.get("panel_font_meta_size", 13) or 13))
    meta_spacing = int(theme.get("panel_font_meta_spacing", 0) or 0)
    meta_compact = bool(theme.get("panel_font_meta_compact", True))

    title_font = fonts.get(body_focus_key, max(24, int(body_base * 1.65)))
    row_font = fonts.get(body_key, max(16, int(body_base + 1)))
    row_focus_font = fonts.get(body_focus_key, max(16, int(body_base + 1)))
    meta_font = fonts.get(meta_key, meta_base)

    left = 24
    right = w - 24

    title_text = "LIST"
    draw.text((left, 16), title_text, font=title_font, fill=ink)
    hint_text = "Rotate=Select  |  Click=Toggle  |  Hold=Home"
    if meta_compact:
        hint_text = hint_text.upper()
    hint_text = truncate_text(draw, hint_text, meta_font, max(80, right - left))
    hint_w = text_width_spaced(draw, hint_text, meta_font, spacing=meta_spacing)
    hint_x = max(left, right - hint_w)
    draw_text_spaced(draw, hint_text, hint_x, 52, meta_font, spacing=meta_spacing, fill=muted)
    draw.line((left, 68, right, 68), fill=border, width=int(theme.get("divider_width", 2) or 2))

    inventory, reminders = _section_indices(state)
    inv_count = len(inventory)
    rem_count = len(reminders)
    total_items = inv_count + rem_count

    focused_global = None
    if total_items > 0:
        focused_global = max(0, min(int(state.ui.list_focused_index or 0), total_items - 1))
    selected_inventory = focused_global if (focused_global is not None and focused_global < inv_count) else None
    selected_reminder = (
        (focused_global - inv_count)
        if (focused_global is not None and focused_global >= inv_count and rem_count > 0)
        else None
    )

    row_h = 40
    content_top = 104
    footer_y = h - 40
    content_bottom = footer_y - 6
    portrait_layout = h > w

    if portrait_layout:
        # Portrait-native layout: top 1/3 inventory, bottom 2/3 reminders.
        split_y = content_top + int((content_bottom - content_top) * (1.0 / 3.0))
        split_y = max(content_top + 72, min(content_bottom - 120, split_y))
        draw.line((left, split_y, right, split_y), fill=ink, width=2)

        inv_x0, inv_x1 = left, right
        rem_x0, rem_x1 = left, right
        inv_title = truncate_text(draw, f"INVENTORY {inv_count}", meta_font, max(60, inv_x1 - inv_x0 - 8))
        rem_title = truncate_text(draw, f"REMINDER {rem_count}", meta_font, max(60, rem_x1 - rem_x0 - 8))
        draw_text_spaced(draw, inv_title, inv_x0 + 2, content_top + 2, meta_font, spacing=meta_spacing, fill=muted)
        draw_text_spaced(draw, rem_title, rem_x0 + 2, split_y + 2, meta_font, spacing=meta_spacing, fill=muted)

        inv_list_top = content_top + 22
        inv_list_bottom = split_y - 6
        inv_slots = max(1, (inv_list_bottom - inv_list_top) // row_h)
        inv_start = _window_start(inv_count, inv_slots, selected_inventory)
        y = inv_list_top
        for local_i, model_idx in enumerate(inventory[inv_start : inv_start + inv_slots]):
            if y + row_h > inv_list_bottom:
                break
            local_idx = inv_start + local_i
            reminder = state.model.reminders[model_idx]
            is_sel = selected_inventory is not None and local_idx == selected_inventory
            ry0 = y + 1
            ry1 = y + row_h - 2
            if is_sel:
                draw.rectangle((inv_x0, ry0, inv_x1, ry1), fill=ink)
            text_fill = bg if is_sel else ink
            title_font = row_focus_font if is_sel else row_font
            prefix = "[x]" if bool(reminder.completed) else "[ ]"
            title_w = max(70, inv_x1 - inv_x0 - 20)
            title = truncate_text(draw, f"{prefix} {str(reminder.title or '').strip() or '(untitled)'}", title_font, title_w)
            draw.text((inv_x0 + 8, y + 10), title, font=title_font, fill=text_fill)
            if not is_sel:
                draw.line((inv_x0 + 6, ry1, inv_x1, ry1), fill=border, width=1)
            y += row_h
        if inv_count <= 0:
            draw_text_spaced(draw, "NO ITEMS", inv_x0 + 8, inv_list_top + 10, meta_font, spacing=meta_spacing, fill=muted)

        rem_list_top = split_y + 22
        rem_list_bottom = content_bottom
        rem_slots = max(1, (rem_list_bottom - rem_list_top) // row_h)
        rem_start = _window_start(rem_count, rem_slots, selected_reminder)
        y = rem_list_top
        for local_i, model_idx in enumerate(reminders[rem_start : rem_start + rem_slots]):
            if y + row_h > rem_list_bottom:
                break
            local_idx = rem_start + local_i
            reminder = state.model.reminders[model_idx]
            is_sel = selected_reminder is not None and local_idx == selected_reminder
            ry0 = y + 1
            ry1 = y + row_h - 2
            if is_sel:
                draw.rectangle((rem_x0, ry0, rem_x1, ry1), fill=ink)
            text_fill = bg if is_sel else ink
            meta_fill = bg if is_sel else muted
            title_font = row_focus_font if is_sel else row_font

            prefix = "[x]" if bool(reminder.completed) else "[ ]"
            right_meta = str(reminder.right or "").strip()
            if not right_meta:
                right_meta = "TODO"
            if bool(reminder.completed):
                right_meta = "DONE"
            right_meta = truncate_text(draw, right_meta.upper(), meta_font, max(52, int((rem_x1 - rem_x0) * 0.26)))
            meta_w = text_width_spaced(draw, right_meta, meta_font, spacing=meta_spacing)
            meta_x = max(rem_x0 + 8, rem_x1 - meta_w - 8)
            draw_text_spaced(draw, right_meta, meta_x, y + 11, meta_font, spacing=meta_spacing, fill=meta_fill)

            title_max_w = max(80, meta_x - rem_x0 - 14)
            title = truncate_text(draw, f"{prefix} {str(reminder.title or '').strip() or '(untitled)'}", title_font, title_max_w)
            draw.text((rem_x0 + 8, y + 10), title, font=title_font, fill=text_fill)
            if not is_sel:
                draw.line((rem_x0 + 6, ry1, rem_x1, ry1), fill=border, width=1)
            y += row_h
        if rem_count <= 0:
            draw_text_spaced(draw, "NO ITEMS", rem_x0 + 8, rem_list_top + 10, meta_font, spacing=meta_spacing, fill=muted)
    else:
        split_x = left + int((right - left) * 0.40)
        left_x0, left_x1 = left, max(left + 40, split_x - 4)
        right_x0, right_x1 = min(right - 40, split_x + 4), right
        draw.line((split_x, content_top, split_x, content_bottom), fill=ink, width=2)

        left_title = truncate_text(draw, f"INVENTORY {inv_count}", meta_font, max(60, left_x1 - left_x0 - 8))
        right_title = truncate_text(draw, f"REMINDER {rem_count}", meta_font, max(60, right_x1 - right_x0 - 8))
        draw_text_spaced(draw, left_title, left_x0 + 2, content_top + 2, meta_font, spacing=meta_spacing, fill=muted)
        draw_text_spaced(draw, right_title, right_x0 + 2, content_top + 2, meta_font, spacing=meta_spacing, fill=muted)

        list_top = content_top + 22
        slots = max(1, (content_bottom - list_top) // row_h)

        # Left column: Inventory (2/5)
        inv_start = _window_start(inv_count, slots, selected_inventory)
        y = list_top
        for local_i, model_idx in enumerate(inventory[inv_start : inv_start + slots]):
            if y + row_h > content_bottom:
                break
            local_idx = inv_start + local_i
            reminder = state.model.reminders[model_idx]
            is_sel = selected_inventory is not None and local_idx == selected_inventory
            ry0 = y + 1
            ry1 = y + row_h - 2
            if is_sel:
                draw.rectangle((left_x0, ry0, left_x1, ry1), fill=ink)
            text_fill = bg if is_sel else ink
            title_font = row_focus_font if is_sel else row_font
            prefix = "[x]" if bool(reminder.completed) else "[ ]"
            title_w = max(70, left_x1 - left_x0 - 20)
            title = truncate_text(draw, f"{prefix} {str(reminder.title or '').strip() or '(untitled)'}", title_font, title_w)
            draw.text((left_x0 + 8, y + 10), title, font=title_font, fill=text_fill)
            if not is_sel:
                draw.line((left_x0 + 6, ry1, left_x1, ry1), fill=border, width=1)
            y += row_h
        if inv_count <= 0:
            draw_text_spaced(draw, "NO ITEMS", left_x0 + 8, list_top + 10, meta_font, spacing=meta_spacing, fill=muted)

        # Right column: Reminder list (3/5)
        rem_start = _window_start(rem_count, slots, selected_reminder)
        y = list_top
        for local_i, model_idx in enumerate(reminders[rem_start : rem_start + slots]):
            if y + row_h > content_bottom:
                break
            local_idx = rem_start + local_i
            reminder = state.model.reminders[model_idx]
            is_sel = selected_reminder is not None and local_idx == selected_reminder
            ry0 = y + 1
            ry1 = y + row_h - 2
            if is_sel:
                draw.rectangle((right_x0, ry0, right_x1, ry1), fill=ink)
            text_fill = bg if is_sel else ink
            meta_fill = bg if is_sel else muted
            title_font = row_focus_font if is_sel else row_font

            prefix = "[x]" if bool(reminder.completed) else "[ ]"
            right_meta = str(reminder.right or "").strip()
            if not right_meta:
                right_meta = "TODO"
            if bool(reminder.completed):
                right_meta = "DONE"
            right_meta = truncate_text(draw, right_meta.upper(), meta_font, max(52, int((right_x1 - right_x0) * 0.26)))
            meta_w = text_width_spaced(draw, right_meta, meta_font, spacing=meta_spacing)
            meta_x = max(right_x0 + 8, right_x1 - meta_w - 8)
            draw_text_spaced(draw, right_meta, meta_x, y + 11, meta_font, spacing=meta_spacing, fill=meta_fill)

            title_max_w = max(80, meta_x - right_x0 - 14)
            title = truncate_text(draw, f"{prefix} {str(reminder.title or '').strip() or '(untitled)'}", title_font, title_max_w)
            draw.text((right_x0 + 8, y + 10), title, font=title_font, fill=text_fill)
            if not is_sel:
                draw.line((right_x0 + 6, ry1, right_x1, ry1), fill=border, width=1)
            y += row_h
        if rem_count <= 0:
            draw_text_spaced(draw, "NO ITEMS", right_x0 + 8, list_top + 10, meta_font, spacing=meta_spacing, fill=muted)

    footer_text = "VOICE CMD: DELETE | ADD | MODIFY"
    footer_text = truncate_text(draw, footer_text, meta_font, max(80, right - left))
    draw_text_spaced(draw, footer_text, left, footer_y, meta_font, spacing=meta_spacing, fill=muted)
