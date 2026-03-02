from __future__ import annotations

from PIL import ImageDraw

from app.core.state import AppState
from app.shared.draw import draw_text_spaced, text_size, text_width_spaced
from app.shared.panel_font_templates import apply_panel_font_template
from app.ui.settings import _draw_home_icon


def _timer_step_s(theme: dict) -> int:
    try:
        value = int(theme.get("timer_step_s", 60) or 60)
    except Exception:
        value = 60
    return max(1, value)


def _format_duration_short(seconds: int) -> str:
    secs = max(1, int(seconds))
    if secs % 3600 == 0:
        return f"{secs // 3600}H"
    if secs % 60 == 0:
        return f"{secs // 60}M"
    return f"{secs}S"


def _fit_font_for_text(draw, fonts, key: str, text: str, *, max_size: int, min_size: int, max_width: int):
    size = max_size
    while size >= min_size:
        font = fonts.get(key, size)
        w, _ = text_size(draw, text, font)
        if w <= max_width:
            return font
        size -= 2
    return fonts.get(key, min_size)


def render_timer(image, state: AppState, fonts, theme: dict) -> None:
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
    radius = int(theme.get("card_radius", 12) or 12)
    border_w = int(theme.get("border_width", 2) or 2)

    body_key = str(theme.get("panel_font_body_key") or "inter_medium")
    body_focus_key = str(theme.get("panel_font_body_focus_key") or "inter_bold")
    meta_key = str(theme.get("panel_font_meta_key") or "jet_bold")
    body_base = max(12, int(theme.get("panel_font_body_size", 18) or 18))
    meta_base = max(11, int(theme.get("panel_font_meta_size", 13) or 13))
    meta_spacing = int(theme.get("panel_font_meta_spacing", 0) or 0)
    meta_compact = bool(theme.get("panel_font_meta_compact", True))

    draw.rectangle((0, 0, w, h), fill=bg)

    title_font = fonts.get(body_focus_key, max(24, int(body_base * 1.65)))
    hint_font = fonts.get(meta_key, meta_base)
    button_font = fonts.get(body_focus_key, max(18, int(body_base + 2)))
    status_font = fonts.get(body_focus_key, max(20, int(body_base + 4)))

    title_y = 16
    title_text = "TIMER"
    title_bbox = draw.textbbox((0, 0), title_text, font=title_font)
    title_mid_y = title_y + int(round((title_bbox[1] + title_bbox[3]) / 2.0))
    title_h = max(1, int(title_bbox[3] - title_bbox[1]))
    icon_size = max(38, int(round(title_h * 0.84)))
    icon_x = 24
    icon_y = max(4, title_mid_y - (icon_size // 2) - 2)
    _draw_home_icon(image, icon_x, icon_y, icon_size, ink)

    title_x = icon_x + icon_size + 14
    draw.text((title_x, title_y), title_text, font=title_font, fill=ink)
    hint_text = "ROTATE TO SELECT  -  CLICK TO CHANGE  -  B TO BACK"
    if meta_compact:
        hint_text = hint_text.upper()
    hint_w = text_width_spaced(draw, hint_text, hint_font, spacing=meta_spacing)
    hint_x = max(24, (w - 24) - hint_w)
    draw_text_spaced(draw, hint_text, hint_x, 52, hint_font, spacing=meta_spacing, fill=muted)
    draw.line((24, 68, w - 24, 68), fill=border, width=int(theme.get("divider_width", 2) or 2))

    secs = max(0, int(state.ui.timer_seconds or 0))
    mm = secs // 60
    ss = secs % 60
    time_text = f"{mm:02d}:{ss:02d}"
    time_font_key = str(theme.get("timer_time_font_key") or theme.get("time_font") or "jet_extrabold")
    time_max_size = max(120, int(theme.get("timer_time_size", 160) or 160))
    time_min_size = max(80, int(theme.get("timer_time_min_size", 96) or 96))

    if secs <= 0:
        status_text = "READY"
    elif bool(state.ui.timer_running):
        status_text = "RUNNING"
    else:
        status_text = "PAUSED"
    if meta_compact:
        status_text = status_text.upper()

    step_s = _timer_step_s(theme)
    controls = [
        f"-{_format_duration_short(step_s)}",
        f"+{_format_duration_short(step_s)}",
        "PAUSE" if bool(state.ui.timer_running) else "START",
        "RESET",
    ]

    focus = int(state.ui.timer_focused_index or 0) % len(controls)
    btn_gap = 12
    btn_h = 60
    btn_w = max(100, (w - 48 - (btn_gap * (len(controls) - 1))) // len(controls))
    row_y = h - 90
    status_gap = max(20, int(theme.get("timer_status_gap", 38) or 38))
    content_top = int(theme.get("timer_time_top", 112) or 112)
    available_bottom = row_y - 26
    status_bbox_0 = draw.textbbox((0, 0), status_text, font=status_font)
    status_h = max(1, status_bbox_0[3] - status_bbox_0[1])

    # Fit timer digits by both width and vertical available space, so status never overlaps.
    time_font = _fit_font_for_text(
        draw,
        fonts,
        time_font_key,
        time_text,
        max_size=time_max_size,
        min_size=time_min_size,
        max_width=(w - 120),
    )
    for size in range(time_max_size, time_min_size - 1, -2):
        candidate = fonts.get(time_font_key, size)
        bbox = draw.textbbox((0, 0), time_text, font=candidate)
        tw = max(1, bbox[2] - bbox[0])
        if tw > (w - 120):
            continue
        test_x = (w - tw) // 2
        test_box = draw.textbbox((test_x, content_top), time_text, font=candidate)
        test_bottom = test_box[3]
        if test_bottom + status_gap + status_h <= available_bottom:
            time_font = candidate
            break

    time_w, _ = text_size(draw, time_text, time_font)
    time_x = (w - time_w) // 2
    time_y = content_top
    draw.text((time_x, time_y), time_text, font=time_font, fill=ink)

    time_box = draw.textbbox((time_x, time_y), time_text, font=time_font)
    status_y = time_box[3] + status_gap
    if status_y + status_h > available_bottom:
        status_y = max(content_top + 8, available_bottom - status_h)
    status_w = int(draw.textlength(status_text, font=status_font))
    draw.text(((w - status_w) // 2, status_y), status_text, font=status_font, fill=muted)

    for idx, label in enumerate(controls):
        x0 = 24 + idx * (btn_w + btn_gap)
        x1 = x0 + btn_w
        is_focus = idx == focus
        fill = ink if is_focus else bg
        text_fill = bg if is_focus else ink
        draw.rounded_rectangle((x0, row_y, x1, row_y + btn_h), radius=radius, outline=ink, width=border_w, fill=fill)

        tw = int(draw.textlength(label, font=button_font))
        tx = x0 + (btn_w - tw) // 2
        ty = row_y + 16
        draw.text((tx, ty), label, font=button_font, fill=text_fill)
