from __future__ import annotations

from PIL import Image, ImageDraw

from app.core.state import AppState, Screen, MenuItemId, WidgetMode
from app.ui.home import render_home
from app.ui.home_kitchen import render_home_kitchen
from app.ui.calendar import render_calendar
from app.ui.weather_detail import render_weather_detail
from app.ui.menu import render_menu
from app.ui.settings import render_settings
from app.ui.placeholder import render_placeholder
from app.ui.layout import compute_layout


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


class _ScaledFontBook:
    def __init__(self, base, scale: float):
        self._base = base
        self._scale = max(0.6, min(1.6, float(scale)))

    def get(self, key, size):
        try:
            s = float(size)
        except Exception:
            s = 12.0
        scaled = max(1, int(round(s * self._scale)))
        return self._base.get(key, scaled)


def _font_scale(state: AppState) -> float:
    size = str(state.ui.font_size or "medium").strip().lower()
    if size == "small":
        return 0.9
    if size == "large":
        return 1.12
    return 1.0


def _mode_color(image, value):
    if image.mode == "RGB":
        if isinstance(value, tuple):
            return value
        if isinstance(value, int):
            v = max(0, min(255, int(value)))
            return (v, v, v)
        return (255, 255, 255)
    return int(value) if isinstance(value, int) else 255


def _render_no_rotation(image, state: AppState, fonts, theme: dict) -> None:
    if state.ui.screen == Screen.MENU:
        render_menu(image, state, fonts, theme)
        return
    if state.ui.screen == Screen.SETTINGS:
        render_settings(image, state, fonts, theme)
        return
    if state.ui.screen == Screen.PLACEHOLDER:
        render_placeholder(image, state, fonts, theme)
        return
    if state.ui.screen == Screen.CALENDAR:
        render_calendar(image, state, fonts, theme)
        return
    if state.ui.screen == Screen.WEATHER:
        render_weather_detail(image, state, fonts, theme)
        return

    # HOME: choose renderer variant based on theme (default: kitchen).
    variant = str((theme or {}).get("home_variant") or "kitchen").strip().lower()
    if variant == "kitchen":
        render_home_kitchen(image, state, fonts, theme)
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


def render_app(image, state: AppState, fonts, theme: dict) -> None:
    scale = _font_scale(state)
    scaled_fonts = fonts if abs(scale - 1.0) < 1e-6 else _ScaledFontBook(fonts, scale)
    rotation = 180 if int(state.ui.rotation_deg or 0) == 180 else 0

    if rotation == 0:
        _render_no_rotation(image, state, scaled_fonts, theme)
        return

    bg = _mode_color(image, (theme or {}).get("bg", (theme or {}).get("card", 255)))
    canvas = Image.new(image.mode, image.size, bg)
    _render_no_rotation(canvas, state, scaled_fonts, theme)
    image.paste(canvas.rotate(180))
