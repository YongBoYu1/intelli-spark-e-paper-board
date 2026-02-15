#!/usr/bin/env python3
"""
Interactive runner for the e-paper on Raspberry Pi.

This is the missing piece that makes the app non-static on hardware:
- Keyboard maps to encoder-like events (rotate/click/back/long press)
- Periodic Tick drives idle + timer + delayed reorder

Note: Uses full refresh via display_image() (simple + reliable). Partial refresh can be added later.
"""

from __future__ import annotations

import argparse
import json
import os
import select
import sys
import termios
import time
import tty

from PIL import Image

# Ensure repo root is importable when running this script directly.
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from app.core.reducer import reduce, Rotate, Click, LongPress, Back, Tick
from app.core.state import AppState, DashboardModel, Reminder, WeatherDay, CalendarEvent, MemoItem
from app.render.epd import init_epd, display_image
from app.render.panel import build_panel_theme, quantize_for_panel
from app.shared.fonts import FontBook
from app.shared.paths import find_repo_root
from app.ui.app import render_app


def _hex_to_rgb(value):
    value = (value or "").strip()
    if value.startswith("#"):
        value = value[1:]
    if len(value) != 6:
        return None
    try:
        return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))
    except Exception:
        return None


def _load_theme(path: str) -> dict:
    if not path or not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    theme = dict(data)
    for key in ("ink", "border", "card", "muted", "bg"):
        val = theme.get(key)
        if isinstance(val, str):
            rgb = _hex_to_rgb(val)
            if rgb:
                theme[key] = rgb
        elif isinstance(val, list) and len(val) == 3:
            theme[key] = tuple(val)
    return theme


def _build_fonts(repo_root: str) -> FontBook:
    font_dir = os.path.join(repo_root, "assets", "fonts")
    return FontBook(
        {
            "inter_regular": os.path.join(font_dir, "Inter-Regular.ttf"),
            "inter_medium": os.path.join(font_dir, "Inter-Medium.ttf"),
            "inter_semibold": os.path.join(font_dir, "Inter-SemiBold.ttf"),
            "inter_bold": os.path.join(font_dir, "Inter-Bold.ttf"),
            "inter_black": os.path.join(font_dir, "Inter-Black.ttf"),
            "jet_bold": os.path.join(font_dir, "JetBrainsMono-Bold.ttf"),
            "jet_extrabold": os.path.join(font_dir, "JetBrainsMono-ExtraBold.ttf"),
            "playfair_regular": os.path.join(font_dir, "PlayfairDisplay-Regular.ttf"),
            "playfair_italic": os.path.join(font_dir, "PlayfairDisplay-Italic.ttf"),
            "playfair_bold": os.path.join(font_dir, "PlayfairDisplay-Bold.ttf"),
        },
        default_key="inter_regular",
    )


def _parse_optional_humidity(raw) -> int | None:
    if raw is None:
        return None
    try:
        if isinstance(raw, str):
            # Accept common API/text forms like "45%" or "45.0".
            txt = raw.strip().rstrip("%").strip()
            if not txt:
                return None
            return int(float(txt))
        return int(raw)
    except Exception:
        return None


def _load_model(repo_root: str) -> DashboardModel:
    path = os.path.join(repo_root, "data", "dashboard.json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
    else:
        d = {}

    tasks = d.get("tasks")
    reminders = []
    if isinstance(tasks, list) and tasks:
        for i, t in enumerate(tasks):
            title = (t.get("text") or t.get("title") or "").strip()
            right = t.get("time") or t.get("badge") or ""
            reminders.append(
                Reminder(
                    rid=str(t.get("id") or f"t{i}"),
                    title=title,
                    right=str(right),
                    completed=bool(t.get("completed", False)),
                    category=str(t.get("category") or "general"),
                    created_at=float(t.get("createdAt") or t.get("created_at") or 0.0),
                )
            )
    else:
        for i, r in enumerate(d.get("reminders") or []):
            title = (r.get("title") or "").strip()
            right = r.get("time") or r.get("due") or ""
            reminders.append(Reminder(rid=f"s{i}", title=title, right=str(right), category="shopping"))
        if not any(r.category == "fridge" for r in reminders):
            now = time.time()
            reminders = [
                Reminder(rid="f1", title="Fresh Milk", right="EXP: 3 DAYS", category="fridge", created_at=now),
                Reminder(rid="f2", title="Leftover Pizza", right="ADDED YESTERDAY", category="fridge", created_at=now - 86400),
                Reminder(rid="f3", title="Marinated Chicken", right="USE TONIGHT", category="fridge", created_at=now),
            ] + reminders

    weather = []
    for w in d.get("weather") or []:
        try:
            weather.append(
                WeatherDay(
                    dow=str(w.get("dow", "")),
                    icon=str(w.get("icon", "sun")),
                    hi=int(w.get("hi", 0)),
                    lo=int(w.get("lo", 0)),
                    humidity=_parse_optional_humidity(w.get("humidity")),
                )
            )
        except Exception:
            continue

    cal = [
        CalendarEvent("e0", "Dinner with Alex", "19:00"),
        CalendarEvent("e1", "Gym Session", "08:00"),
    ]

    memos = []
    for i, m in enumerate(d.get("memos") or []):
        memos.append(
            MemoItem(
                mid=str(m.get("id") or f"m{i}"),
                text=str(m.get("text") or ""),
                author=str(m.get("author") or ""),
                timestamp=float(m.get("timestamp") or time.time()),
                is_new=bool(m.get("isNew") or m.get("is_new") or False),
            )
        )
    if not memos:
        memos = [
            MemoItem("m1", "Dinner is in the oven, heat at 180°C.", "Mom", time.time(), True),
            MemoItem("m2", "Don't forget to walk the dog!", "Dad", time.time() - 3600, False),
            MemoItem("m3", "Can someone pick up packages?", "Alex", time.time() - 7200, True),
        ]

    return DashboardModel(
        location=str(d.get("location") or "New York"),
        battery=int(d.get("battery") or 84),
        reminders=reminders,
        weather=weather,
        calendar=cal,
        memos=memos,
    )


def _read_key_nonblocking() -> str:
    r, _, _ = select.select([sys.stdin], [], [], 0)
    if not r:
        return ""
    ch = sys.stdin.read(1)
    if ch != "\x1b":
        return ch
    # Arrow keys: ESC [ A/B/C/D
    if select.select([sys.stdin], [], [], 0)[0]:
        ch2 = sys.stdin.read(1)
        if ch2 == "[" and select.select([sys.stdin], [], [], 0)[0]:
            ch3 = sys.stdin.read(1)
            return f"\x1b[{ch3}"
    return "\x1b"


def _warn_missing_fonts(fonts: FontBook) -> None:
    missing = fonts.missing_font_paths()
    if not missing:
        return
    print("[warn] Missing font files. Rendering will fall back and quality may degrade:")
    for key, path in missing:
        print(f"  - {key}: {path}")


def _render_to_epd(
    epd,
    state: AppState,
    fonts: FontBook,
    theme: dict,
    *,
    panel_threshold: int,
    panel_muted: int,
    panel_gamma: float,
    panel_dither: bool,
) -> None:
    # Render in RGB first, then quantize to 1-bit. This produces less jagged text
    # than drawing directly to mode '1'.
    t = build_panel_theme(theme, muted_gray=panel_muted)
    rgb = Image.new("RGB", (epd.width, epd.height), t.get("bg", (255, 255, 255)))
    render_app(rgb, state, fonts, t)
    image = quantize_for_panel(rgb, threshold=panel_threshold, gamma=panel_gamma, dither=panel_dither)
    display_image(epd, image, sleep_after=False)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--theme", default="ui_tuner_theme.json", help="Theme JSON (optional)")
    parser.add_argument("--tick", type=float, default=0.2, help="Tick interval seconds")
    parser.add_argument("--panel-threshold", type=int, default=None, help="1-bit threshold (0-255)")
    parser.add_argument("--panel-muted", type=int, default=None, help="Muted gray before quantization (0-255)")
    parser.add_argument("--panel-gamma", type=float, default=None, help="Gamma before threshold (0.1-4.0)")
    parser.add_argument("--panel-dither", action="store_true", help="Use Floyd-Steinberg dithering before 1-bit output")
    args = parser.parse_args()

    repo_root = find_repo_root(os.path.dirname(__file__))
    theme_path = args.theme
    if theme_path and not os.path.isabs(theme_path):
        theme_path = os.path.join(repo_root, theme_path)
    theme = _load_theme(theme_path) if theme_path else {}
    panel_threshold = int(args.panel_threshold if args.panel_threshold is not None else theme.get("panel_threshold", 168))
    panel_muted = int(args.panel_muted if args.panel_muted is not None else theme.get("panel_muted", 150))
    panel_gamma = float(args.panel_gamma if args.panel_gamma is not None else theme.get("panel_gamma", 1.0))
    panel_dither = bool(args.panel_dither or theme.get("panel_dither", False))
    fonts = _build_fonts(repo_root)
    _warn_missing_fonts(fonts)
    state = AppState(model=_load_model(repo_root))

    epd, _ = init_epd()
    _render_to_epd(
        epd,
        state,
        fonts,
        theme,
        panel_threshold=panel_threshold,
        panel_muted=panel_muted,
        panel_gamma=panel_gamma,
        panel_dither=panel_dither,
    )

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    tty.setraw(fd)
    try:
        print("Controls: Left/Right rotate, Enter click, Space long press, B/Esc back, Q quit")
        last_render_sig = None
        next_tick = time.time()
        while True:
            now = time.time()
            key = _read_key_nonblocking()

            ev = None
            if key in ("\x1b[D", "h"):  # left
                ev = Rotate(-1)
            elif key in ("\x1b[C", "l"):  # right
                ev = Rotate(+1)
            elif key in ("\r", "\n"):  # enter
                ev = Click()
            elif key == " ":
                ev = LongPress()
            elif key in ("b", "B", "\x7f", "\x1b"):  # backspace / esc
                ev = Back()
            elif key in ("q", "Q"):
                return 0

            if ev is not None:
                reduce(state, ev, theme=theme)

            if now >= next_tick:
                reduce(state, Tick(now=now), theme=theme)
                next_tick = now + float(args.tick)

            # Only re-render if state that affects UI changed.
            sig = (
                state.ui.screen,
                state.ui.focused_index,
                state.ui.page,
                state.ui.idle,
                state.ui.widget_mode,
                state.ui.timer_seconds,
                state.ui.timer_running,
                state.ui.voice_active,
                state.ui.menu_focused,
                state.ui.active_menu,
                tuple((r.rid, r.completed) for r in state.model.reminders),
            )
            if sig != last_render_sig:
                _render_to_epd(
                    epd,
                    state,
                    fonts,
                    theme,
                    panel_threshold=panel_threshold,
                    panel_muted=panel_muted,
                    panel_gamma=panel_gamma,
                    panel_dither=panel_dither,
                )
                last_render_sig = sig

            time.sleep(0.01)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
        try:
            epd.sleep()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
