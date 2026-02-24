from __future__ import annotations

from PIL import ImageDraw

from app.core.state import AppState, Screen, MenuItemId, WidgetMode
from app.ui.home import render_home
from app.ui.home_kitchen import render_home_kitchen
from app.ui.calendar import render_calendar
from app.ui.weather_detail import render_weather_detail
from app.ui.menu import render_menu
from app.ui.placeholder import render_placeholder
from app.ui.layout import compute_layout


def _voice_overlay_title(phase: str) -> str:
    p = (phase or "idle").strip().lower()
    if p == "recording":
        return "RECORDING"
    if p == "processing":
        return "PROCESSING"
    if p == "confirm":
        return "CONFIRM"
    if p == "done":
        return "DONE"
    if p == "error":
        return "ERROR"
    return "VOICE"


def _voice_wrap_message(msg: str, max_chars: int = 44, max_lines: int = 3) -> list[str]:
    text = str(msg or "").strip()
    if not text:
        return []

    lines: list[str] = []
    for raw in text.splitlines():
        part = " ".join(raw.strip().split())
        if not part:
            continue
        words = part.split(" ")
        cur = ""
        for w in words:
            candidate = w if not cur else f"{cur} {w}"
            if len(candidate) <= max_chars:
                cur = candidate
                continue
            if cur:
                lines.append(cur)
            # Handle long unbroken tokens (e.g. Chinese without spaces).
            cur = w if len(w) <= max_chars else (w[: max_chars - 3] + "...")
            if len(lines) >= max_lines - 1:
                break
        if cur and len(lines) < max_lines:
            lines.append(cur)
        if len(lines) >= max_lines:
            break

    if len(lines) > max_lines:
        lines = lines[:max_lines]
    if lines and len(lines[-1]) > max_chars:
        lines[-1] = lines[-1][: max_chars - 3] + "..."
    if len(lines) == max_lines and " ".join(lines) != text:
        if len(lines[-1]) >= 3:
            lines[-1] = lines[-1][: max(0, max_chars - 3)] + "..."
    return lines


def _draw_voice_overlay(image, state: AppState, fonts, theme: dict) -> None:
    if not bool(state.ui.voice_active):
        return

    draw = ImageDraw.Draw(image)
    w, h = image.size

    ink = theme.get("ink", 0)
    card = theme.get("card", 255)
    border = theme.get("border", ink)
    muted = theme.get("muted", ink)

    box_w = min(560, max(360, int(w * 0.62)))
    box_h = min(220, max(176, int(h * 0.38)))
    x0 = (w - box_w) // 2
    y0 = (h - box_h) // 2
    x1 = x0 + box_w
    y1 = y0 + box_h

    draw.rounded_rectangle(
        (x0, y0, x1, y1),
        radius=14,
        outline=border,
        width=3,
        fill=card,
    )

    title = _voice_overlay_title(state.ui.voice_phase)
    msg = str(state.ui.voice_message or "").strip()
    title_font = fonts.get("inter_black", 32)
    msg_font = fonts.get("inter_semibold", 18)
    hint_font = fonts.get("inter_regular", 14)

    tw = draw.textlength(title, font=title_font)
    draw.text((x0 + (box_w - tw) / 2, y0 + 28), title, font=title_font, fill=ink)

    if msg:
        lines = _voice_wrap_message(msg, max_chars=44, max_lines=3)
        base_y = y0 + 82
        line_h = 24
        for i, line in enumerate(lines):
            mw = draw.textlength(line, font=msg_font)
            draw.text((x0 + (box_w - mw) / 2, base_y + i * line_h), line, font=msg_font, fill=muted)

    if state.ui.voice_phase in ("recording", "processing"):
        hint = "PLEASE WAIT"
    elif state.ui.voice_phase == "confirm":
        hint = "PRESS CLICK / ENTER"
    else:
        hint = " "
    hw = draw.textlength(hint, font=hint_font)
    draw.text((x0 + (box_w - hw) / 2, y1 - 30), hint, font=hint_font, fill=muted)


def _to_render_data(state: AppState) -> dict:
    reminders = []
    for r in state.model.reminders:
        item = {"title": r.title}
        if r.right:
            # Heuristic: treat HH:MM as time, otherwise due.
            if ":" in r.right and len(r.right) <= 5:
                item["time"] = r.right
            else:
                item["due"] = r.right
        reminders.append(item)

    weather = []
    for w in state.model.weather:
        item = {"dow": w.dow, "icon": w.icon, "hi": w.hi, "lo": w.lo}
        if getattr(w, "humidity", None) is not None:
            item["humidity"] = w.humidity
        weather.append(item)

    return {
        "location": state.model.location,
        "battery": state.model.battery,
        "page": state.ui.page,
        # totals are derived from full dataset
        "reminder_total": len(state.model.reminders),
        "reminder_due": sum(1 for r in state.model.reminders if not r.completed),
        "reminders": reminders,
        "weather": weather,
        "voice_active": bool(state.ui.voice_active),
        "widget_mode": str(state.ui.widget_mode.value if isinstance(state.ui.widget_mode, WidgetMode) else state.ui.widget_mode),
        "timer_seconds": int(state.ui.timer_seconds or 0),
        "timer_running": bool(state.ui.timer_running),
        "menu_focused": str(state.ui.menu_focused.value if isinstance(state.ui.menu_focused, MenuItemId) else state.ui.menu_focused),
        "active_menu": str(state.ui.active_menu.value if state.ui.active_menu else ""),
    }


def render_app(image, state: AppState, fonts, theme: dict) -> None:
    if state.ui.screen == Screen.MENU:
        render_menu(image, state, fonts, theme)
        _draw_voice_overlay(image, state, fonts, theme)
        return
    if state.ui.screen == Screen.PLACEHOLDER:
        render_placeholder(image, state, fonts, theme)
        _draw_voice_overlay(image, state, fonts, theme)
        return
    if state.ui.screen == Screen.CALENDAR:
        render_calendar(image, state, fonts, theme)
        _draw_voice_overlay(image, state, fonts, theme)
        return
    if state.ui.screen == Screen.WEATHER:
        render_weather_detail(image, state, fonts, theme)
        _draw_voice_overlay(image, state, fonts, theme)
        return

    # HOME: choose renderer variant based on theme (default: kitchen).
    variant = str((theme or {}).get("home_variant") or "kitchen").strip().lower()
    if variant == "kitchen":
        render_home_kitchen(image, state, fonts, theme)
        _draw_voice_overlay(image, state, fonts, theme)
        return

    data = _to_render_data(state)

    overlay = {}
    if not state.ui.idle and state.ui.screen == Screen.HOME:
        # HOME focus queue: [CLOCK, WEATHER, TASK_0..]
        if state.ui.focused_index == 0:
            overlay["focus"] = {"kind": "clock"}
        elif state.ui.focused_index == 1:
            overlay["focus"] = {"kind": "weather"}
        else:
            overlay["focus"] = {"kind": "task", "index": state.ui.focused_index - 2}
        overlay["focus_width"] = int(theme.get("focus_width", 4) or 4)

    render_home(image, data, fonts, theme=theme, overlay=overlay)

    # Draw focus for clock/weather cards here (task focus is handled in home.py).
    focus = overlay.get("focus") or {}
    if focus.get("kind") in ("clock", "weather"):
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
        box = left_card if focus.get("kind") == "clock" else weather_card
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle(
            box,
            radius=int(theme.get("card_radius", 12) or 12),
            outline=theme.get("ink", 0),
            width=int(overlay.get("focus_width", 4) or 4),
            fill=None,
        )
    _draw_voice_overlay(image, state, fonts, theme)
