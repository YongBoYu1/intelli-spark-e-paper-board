#!/usr/bin/env python3
"""
Interactive runner for the e-paper on Raspberry Pi.

This is the missing piece that makes the app non-static on hardware:
- Keyboard maps to encoder-like events (rotate/click/back/long press)
- Periodic Tick drives idle + timer + delayed reorder

Note: Uses unified refresh strategy:
- All screens go through one refresh-policy pipeline.
- Policy chooses no-refresh / partial / fast full / full clean at runtime.
"""

from __future__ import annotations

import argparse
import json
import os
import select
import subprocess
import sys
import termios
import tempfile
import time
import tty

from PIL import Image, ImageChops

# Ensure repo root is importable when running this script directly.
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from app.core.reducer import reduce, Rotate, Click, LongPress, RotateButton, Back, Tick
from app.core.state import AppState, DashboardModel, Reminder, WeatherDay, CalendarEvent, MemoItem, Screen
from app.render.epd import init_epd
from app.render.panel import build_panel_theme, quantize_for_panel
from app.render.refresh_policy import (
    RefreshPolicyRuntime,
    align_rect_for_partial,
    build_ui_snapshot,
    effective_full_refresh_every,
    infer_dirty_rects_with_reasons,
    merge_rects,
    mode_params,
    rect_area_ratio,
    rect_contains,
    screen_partial_area_limit,
)
from app.shared.env import load_repo_dotenv
from app.shared.fonts import FontBook
from app.shared.paths import find_repo_root
from app.ui.app import render_app
from app.voice import (
    VoiceClientError,
    apply_voice_plan,
    build_board_context,
    build_request_meta,
    confirm_pending_voice_action,
    describe_voice_action,
    expire_pending_voice_confirmation,
    interpret_audio_via_backend,
    parse_voice_plan,
    parse_voice_action,
)

load_repo_dotenv(os.path.dirname(__file__))

try:
    import RPi.GPIO as GPIO
except Exception:
    GPIO = None

CW_SEQ = {
    (0b00, 0b01),
    (0b01, 0b11),
    (0b11, 0b10),
    (0b10, 0b00),
}
CCW_SEQ = {
    (0b00, 0b10),
    (0b10, 0b11),
    (0b11, 0b01),
    (0b01, 0b00),
}


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


def _parse_optional_number(raw) -> float | None:
    if raw is None:
        return None
    try:
        if isinstance(raw, str):
            txt = raw.strip()
            if not txt:
                return None
            cleaned = []
            for ch in txt:
                if ch.isdigit() or ch in (".", "-"):
                    cleaned.append(ch)
                else:
                    cleaned.append(" ")
            tokens = "".join(cleaned).split()
            if not tokens:
                return None
            return float(tokens[0])
        return float(raw)
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
                    feels_like=_parse_optional_number(
                        w.get("feels_like") or w.get("feelsLike") or w.get("feels") or w.get("apparent_temp")
                    ),
                    wind_kmh=_parse_optional_number(
                        w.get("wind_kmh") or w.get("windKmh") or w.get("wind_speed") or w.get("wind")
                    ),
                    uv_index=_parse_optional_number(w.get("uv_index") or w.get("uv") or w.get("uvi")),
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


def _render_frame(
    epd,
    state: AppState,
    fonts: FontBook,
    theme: dict,
    *,
    panel_threshold: int,
    panel_muted: int,
    panel_gamma: float,
    panel_dither: bool,
) -> Image.Image:
    # Render in RGB first, then quantize to 1-bit. This produces less jagged text
    # than drawing directly to mode '1'.
    t = build_panel_theme(theme, muted_gray=panel_muted)
    rgb = Image.new("RGB", (epd.width, epd.height), t.get("bg", (255, 255, 255)))
    render_app(rgb, state, fonts, t)
    return quantize_for_panel(rgb, threshold=panel_threshold, gamma=panel_gamma, dither=panel_dither)


def _state_render_sig(state: AppState):
    return (
        state.ui.screen,
        state.ui.focused_index,
        state.ui.page,
        state.ui.idle,
        state.ui.widget_mode,
        state.ui.timer_seconds,
        state.ui.timer_running,
        state.ui.timer_focused_index,
        state.ui.voice_active,
        state.ui.voice_phase,
        state.ui.voice_message,
        state.ui.menu_focused,
        state.ui.active_menu,
        state.ui.settings_focused_index,
        state.ui.font_size,
        state.ui.weather_day_index,
        state.ui.calendar_offset_days,
        state.ui.calendar_mode,
        state.ui.calendar_selected_index,
        state.ui.memo_index,
        state.ui.partial_refresh_mode,
        state.ui.full_refresh_every,
        state.ui.wifi_enabled,
        state.ui.bluetooth_enabled,
        state.ui.auto_sync_enabled,
        state.ui.last_sync_at,
        state.ui.rotation_deg,
        state.ui.settings_notice,
        tuple((r.rid, r.completed, r.title, r.right, r.category) for r in state.model.reminders),
        tuple((w.dow, w.icon, w.hi, w.lo, w.humidity, w.feels_like, w.wind_kmh, w.uv_index) for w in state.model.weather),
        tuple((c.eid, c.title, c.when) for c in state.model.calendar),
        tuple((m.mid, m.text, m.author, int(m.timestamp), m.is_new) for m in state.model.memos),
    )


def _ensure_epd_mode(epd, current_mode: str, target_mode: str) -> str:
    if current_mode == target_mode:
        return current_mode
    if target_mode == "part":
        epd.init_part()
    elif target_mode == "fast":
        epd.init_fast()
    else:
        epd.init()
    return target_mode


def _blit_full(epd, image: Image.Image, current_mode: str, *, fast: bool) -> str:
    target_mode = "fast" if fast else "full"
    current_mode = _ensure_epd_mode(epd, current_mode, target_mode)
    epd.display(epd.getbuffer(image))
    return current_mode


def _timer_partial_full_every(theme: dict) -> int:
    # Avoid forcing full refresh too frequently during active countdown ticks.
    try:
        value = int(theme.get("timer_full_refresh_every", 300) or 300)
    except Exception:
        value = 300
    return max(60, value)


def _screen_area_limit_with_theme(screen: Screen, mode: str, theme: dict) -> float:
    default_value = screen_partial_area_limit(screen, mode)
    key = f"refresh_area_limit_{str(screen.value if isinstance(screen, Screen) else screen)}"
    raw = theme.get(key, theme.get("refresh_area_limit", default_value))
    try:
        value = float(raw)
    except Exception:
        return default_value
    return max(0.05, min(0.98, value))


def _screen_mode_with_theme(screen: Screen, mode: str, theme: dict) -> str:
    screen_name = str(screen.value if isinstance(screen, Screen) else screen).strip().lower()
    key = f"refresh_mode_{screen_name}"
    override = str(theme.get(key, "") or "").strip().lower()
    if override in ("slow", "balanced", "fast"):
        return override
    base = str(mode or "balanced").strip().lower()
    if base in ("slow", "balanced", "fast"):
        return base
    return "balanced"


def _mode_gap_with_theme(mode: str, theme: dict) -> int:
    params = mode_params(mode)
    key = f"refresh_min_gap_ms_{str(mode or 'balanced').strip().lower()}"
    raw = theme.get(key, theme.get("refresh_min_gap_ms", params.min_refresh_gap_ms))
    try:
        value = int(raw)
    except Exception:
        return params.min_refresh_gap_ms
    return max(0, value)


def _home_family_area_limit_with_theme(theme: dict) -> float:
    raw = theme.get("refresh_area_limit_home_family_board", 0.30)
    try:
        value = float(raw)
    except Exception:
        value = 0.30
    return max(0.05, min(0.98, value))


def _fast_full_enabled(theme: dict) -> bool:
    return bool(theme.get("refresh_enable_fast_full", False))


def _screen_partial_enabled_with_theme(screen: Screen, theme: dict) -> bool:
    if bool(theme.get("refresh_partial_enable_all", False)):
        return True

    default_screens = "settings,timer"
    raw = theme.get("refresh_partial_screens", default_screens)
    if isinstance(raw, str):
        names = [x.strip().lower() for x in raw.split(",") if x.strip()]
    elif isinstance(raw, (list, tuple)):
        names = [str(x).strip().lower() for x in raw if str(x).strip()]
    else:
        names = [x.strip().lower() for x in default_screens.split(",") if x.strip()]

    screen_name = str(screen.value if isinstance(screen, Screen) else screen).strip().lower()
    return screen_name in set(names)


def _should_collapse_to_latest(screen: Screen, reasons: list[str]) -> bool:
    if screen != Screen.HOME or not reasons:
        return False
    allowed = {
        "home.focus_move_row",
        "home.focus_to_left_panel",
        "home.focus_from_left_panel",
        "home.focus_left_panel_only",
        "diff_fallback",
    }
    has_focus_reason = any(r.startswith("home.focus_") for r in reasons)
    return has_focus_reason and all(r in allowed for r in reasons)


def _partial_buffer_from_frame(frame: Image.Image, rect: tuple[int, int, int, int]) -> bytearray:
    x0, y0, x1, y1 = rect
    crop = frame.crop((x0, y0, x1, y1)).convert("1")
    buf = bytearray(crop.tobytes("raw"))
    # Keep polarity aligned with waveshare getbuffer(): PIL 0=black/1=white.
    for i in range(len(buf)):
        buf[i] ^= 0xFF
    return buf


def _blit_partial(epd, frame: Image.Image, rect: tuple[int, int, int, int], current_mode: str) -> str:
    x0, y0, x1, y1 = rect
    if x1 <= x0 or y1 <= y0:
        return current_mode
    current_mode = _ensure_epd_mode(epd, current_mode, "part")
    # epd7in5_V2 display_Partial expects (partial_buffer, x_start, y_start, x_end, y_end).
    part_buf = _partial_buffer_from_frame(frame, rect)
    epd.display_Partial(part_buf, x0, y0, x1, y1)
    return current_mode


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
    frame = _render_frame(
        epd,
        state,
        fonts,
        theme,
        panel_threshold=panel_threshold,
        panel_muted=panel_muted,
        panel_gamma=panel_gamma,
        panel_dither=panel_dither,
    )
    if _fast_full_enabled(theme):
        try:
            epd.init_fast()
        except Exception:
            epd.init()
    else:
        epd.init()
    epd.display(epd.getbuffer(frame))


def _set_voice_overlay(state: AppState, phase: str, message: str = "", hold_s: float = 0.0) -> None:
    p = str(phase or "idle").strip().lower()
    if p == "idle":
        state.ui.voice_active = False
        state.ui.voice_phase = "idle"
        state.ui.voice_message = ""
        state.ui.voice_due_at = 0.0
        return

    state.ui.voice_active = True
    state.ui.voice_phase = p
    state.ui.voice_message = str(message or "")
    state.ui.voice_due_at = (time.time() + float(hold_s)) if hold_s > 0 else 0.0


def _record_audio_fixed(
    *,
    audio_path: str,
    audio_device: str,
    audio_rate: int,
    audio_channels: int,
    max_sec: int,
) -> str | None:
    cmd = [
        "arecord",
        "-D",
        str(audio_device),
        "-f",
        "S16_LE",
        "-r",
        str(int(audio_rate)),
        "-c",
        str(int(audio_channels)),
        "-d",
        str(int(max_sec)),
        "-t",
        "wav",
        str(audio_path),
    ]

    try:
        proc = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    except FileNotFoundError:
        return None
    except Exception:
        return None

    if proc.returncode != 0:
        return None
    if not os.path.exists(audio_path):
        return None
    if os.path.getsize(audio_path) <= 0:
        return None
    return audio_path


def _run_voice_flow(
    *,
    state: AppState,
    epd,
    fonts: FontBook,
    theme: dict,
    panel_threshold: int,
    panel_muted: int,
    panel_gamma: float,
    panel_dither: bool,
    voice_api_url: str,
    voice_locale: str,
    voice_timezone: str,
    voice_timeout_s: float,
    voice_max_sec: int,
    voice_audio_device: str,
    voice_audio_rate: int,
    voice_audio_channels: int,
) -> None:
    state.ui.idle = False
    state.ui.last_interaction_at = time.time()

    fd, audio_path = tempfile.mkstemp(prefix="voice_", suffix=".wav", dir="/tmp")
    os.close(fd)

    try:
        _set_voice_overlay(state, "recording", f"Speak within {max(1, int(voice_max_sec))}s")
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

        audio = _record_audio_fixed(
            audio_path=audio_path,
            audio_device=voice_audio_device,
            audio_rate=voice_audio_rate,
            audio_channels=voice_audio_channels,
            max_sec=voice_max_sec,
        )
        if not audio:
            _set_voice_overlay(state, "error", "Recording failed", hold_s=2.0)
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
            return

        _set_voice_overlay(state, "processing", "Interpreting command")
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

        meta = build_request_meta(locale=voice_locale, tz_name=voice_timezone)
        payload = interpret_audio_via_backend(
            api_url=str(voice_api_url or ""),
            audio_path=audio,
            meta=meta,
            timeout_s=float(voice_timeout_s),
            board_context=build_board_context(state),
        )
        transcript = ""
        if isinstance(payload, dict):
            transcript = str(payload.get("transcript") or "").strip()
        plan = parse_voice_plan(payload)
        plan_result = apply_voice_plan(state, plan, transcript=transcript)
        action_desc = ", ".join([describe_voice_action(a) for a in list(plan.actions or [])[:4]])
        if not action_desc:
            action_desc = describe_voice_action(parse_voice_action(payload))
        heard = transcript if transcript else "-"
        shown = (
            f"Heard: {heard}\n"
            f"Action: {action_desc}\n"
            f"Result: {plan_result.message}"
        )
        hold_s = 2.2
        if str(plan_result.status or "") == "confirm":
            remaining_confirm_s = max(0.0, float(state.ui.voice_confirm_due_at or 0.0) - time.time())
            hold_s = max(hold_s, remaining_confirm_s + 0.2)
        _set_voice_overlay(state, plan_result.status, shown, hold_s=hold_s)
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
    except VoiceClientError as e:
        _set_voice_overlay(state, "error", str(e), hold_s=2.5)
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
    except Exception as e:
        _set_voice_overlay(state, "error", f"Voice failed: {e}", hold_s=2.5)
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
    finally:
        try:
            os.remove(audio_path)
        except Exception:
            pass


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--theme", default="ui_tuner_theme.json", help="Theme JSON (optional)")
    parser.add_argument("--tick", type=float, default=0.2, help="Tick interval seconds")
    parser.add_argument("--panel-threshold", type=int, default=None, help="1-bit threshold (0-255)")
    parser.add_argument("--panel-muted", type=int, default=None, help="Muted gray before quantization (0-255)")
    parser.add_argument("--panel-gamma", type=float, default=None, help="Gamma before threshold (0.1-4.0)")
    parser.add_argument("--panel-dither", action="store_true", help="Use Floyd-Steinberg dithering before 1-bit output")
    parser.add_argument(
        "--encoder-pin-s1",
        type=int,
        default=None,
        help="BCM pin for rotary S1/CLK (auto: 16 on Raspberry Pi). Use -1 to disable.",
    )
    parser.add_argument(
        "--encoder-pin-s2",
        type=int,
        default=None,
        help="BCM pin for rotary S2/DT (auto: 20 on Raspberry Pi). Use -1 to disable.",
    )
    parser.add_argument(
        "--encoder-key-pin",
        type=int,
        default=None,
        help="BCM pin for rotary KEY/SW click (auto: 21 on Raspberry Pi). Use -1 to disable.",
    )
    parser.add_argument(
        "--encoder-pull",
        choices=("up", "down"),
        default="up",
        help="GPIO pull mode for rotary inputs (default: up)",
    )
    parser.add_argument(
        "--encoder-key-active",
        choices=("low", "high"),
        default="low",
        help="Active level for encoder KEY press (default: low)",
    )
    parser.add_argument(
        "--encoder-steps-per-detent",
        type=int,
        default=4,
        help="Quadrature steps required to emit one rotate event (default: 4)",
    )
    parser.add_argument(
        "--encoder-key-debounce-ms",
        type=int,
        default=180,
        help="Debounce window for encoder KEY press in ms (default: 180)",
    )
    parser.add_argument(
        "--encoder-key-long-press-ms",
        type=int,
        default=450,
        help="Hold threshold for encoder KEY long-press event in ms (default: 450)",
    )
    parser.add_argument(
        "--encoder-flip-direction",
        action="store_true",
        help="Flip rotary direction if CW/CCW feels reversed",
    )
    parser.add_argument(
        "--rotate-pin",
        type=int,
        default=None,
        help="BCM GPIO pin for dedicated screen-rotate button (default: disabled).",
    )
    parser.add_argument(
        "--rotate-active",
        choices=("low", "high"),
        default="low",
        help="Active level for rotate button GPIO input (default: low)",
    )
    parser.add_argument(
        "--rotate-pull",
        choices=("up", "down"),
        default="up",
        help="GPIO pull mode for rotate button (default: up)",
    )
    parser.add_argument(
        "--rotate-debounce-ms",
        type=int,
        default=180,
        help="Debounce window for rotate button GPIO edge detection in ms (default: 180)",
    )
    parser.add_argument("--voice-api-url", default=os.environ.get("VOICE_API_URL", ""), help="Backend URL for POST /voice/interpret")
    parser.add_argument("--voice-locale", default=os.environ.get("VOICE_LOCALE", "zh-CN"), help="Locale sent to backend")
    parser.add_argument("--voice-timezone", default=os.environ.get("VOICE_TIMEZONE", "UTC"), help="Timezone sent to backend")
    parser.add_argument("--voice-timeout", type=float, default=float(os.environ.get("VOICE_TIMEOUT_S", "20")), help="Backend timeout seconds")
    parser.add_argument("--voice-max-sec", type=int, default=int(os.environ.get("VOICE_MAX_SEC", "6")), help="Recording duration in seconds")
    parser.add_argument("--voice-audio-device", default=os.environ.get("VOICE_AUDIO_DEVICE", "default"), help="arecord audio device")
    parser.add_argument("--voice-audio-rate", type=int, default=int(os.environ.get("VOICE_AUDIO_RATE", "16000")), help="Audio sample rate")
    parser.add_argument("--voice-audio-channels", type=int, default=int(os.environ.get("VOICE_AUDIO_CHANNELS", "1")), help="Audio channels")
    args = parser.parse_args()

    encoder_pin_s1 = args.encoder_pin_s1
    encoder_pin_s2 = args.encoder_pin_s2
    encoder_key_pin = args.encoder_key_pin
    if GPIO is not None:
        if encoder_pin_s1 is None:
            encoder_pin_s1 = 16
        if encoder_pin_s2 is None:
            encoder_pin_s2 = 20
        if encoder_key_pin is None:
            encoder_key_pin = 21
    encoder_pin_s1 = None if (encoder_pin_s1 is not None and int(encoder_pin_s1) < 0) else encoder_pin_s1
    encoder_pin_s2 = None if (encoder_pin_s2 is not None and int(encoder_pin_s2) < 0) else encoder_pin_s2
    encoder_key_pin = None if (encoder_key_pin is not None and int(encoder_key_pin) < 0) else encoder_key_pin
    if (encoder_pin_s1 is None) != (encoder_pin_s2 is None):
        print("[warn] encoder S1/S2 must be enabled together; disabling rotary turn input.")
        encoder_pin_s1 = None
        encoder_pin_s2 = None

    rotate_pin = args.rotate_pin
    if rotate_pin is not None and int(rotate_pin) < 0:
        rotate_pin = None

    repo_root = find_repo_root(os.path.dirname(__file__))
    theme_path = args.theme
    if theme_path and not os.path.isabs(theme_path):
        theme_path = os.path.join(repo_root, theme_path)
    theme = _load_theme(theme_path) if theme_path else {}
    refresh_debug = bool(theme.get("refresh_debug", False))
    panel_threshold = int(args.panel_threshold if args.panel_threshold is not None else theme.get("panel_threshold", 168))
    panel_muted = int(args.panel_muted if args.panel_muted is not None else theme.get("panel_muted", 150))
    panel_gamma = float(args.panel_gamma if args.panel_gamma is not None else theme.get("panel_gamma", 1.0))
    panel_dither = bool(args.panel_dither or theme.get("panel_dither", False))
    fonts = _build_fonts(repo_root)
    _warn_missing_fonts(fonts)
    state = AppState(model=_load_model(repo_root))
    if not str(args.voice_api_url or "").strip():
        print("[warn] VOICE_API_URL not set. Voice flow will show network error until configured.")

    epd, _ = init_epd()
    supports_partial = hasattr(epd, "init_part") and hasattr(epd, "display_Partial")
    driver_mode = "full"
    committed_frame = _render_frame(
        epd,
        state,
        fonts,
        theme,
        panel_threshold=panel_threshold,
        panel_muted=panel_muted,
        panel_gamma=panel_gamma,
        panel_dither=panel_dither,
    )
    driver_mode = _blit_full(epd, committed_frame, driver_mode, fast=False)
    committed_sig = _state_render_sig(state)
    committed_snapshot = build_ui_snapshot(state)
    pending_frame: Image.Image | None = None
    pending_sig = None
    pending_snapshot = None
    pending_reasons: list[str] = []

    refresh_runtime = RefreshPolicyRuntime()
    refresh_runtime.mark_full_clean(time.time())
    if refresh_debug:
        print(f"[refresh] debug=on supports_partial={bool(supports_partial)}")

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    tty.setraw(fd)
    encoder_ready = False
    rotate_btn_ready = False
    prev_ab = None
    encoder_accum = 0
    prev_key = None
    key_is_down = False
    key_down_at = 0.0
    key_long_sent = False
    key_last_edge_at = 0.0
    rotate_prev = None
    rotate_btn_last_press_at = 0.0
    gpio_pins_in_use = set()
    encoder_key_debounce_s = max(0.0, float(args.encoder_key_debounce_ms) / 1000.0)
    encoder_key_long_press_s = max(0.1, float(args.encoder_key_long_press_ms) / 1000.0)
    rotate_debounce_s = max(0.0, float(args.rotate_debounce_ms) / 1000.0)

    if GPIO is None:
        if encoder_pin_s1 is not None or encoder_pin_s2 is not None or encoder_key_pin is not None or rotate_pin is not None:
            print("[warn] GPIO input requested but RPi.GPIO is unavailable; keyboard input remains enabled.")
    else:
        try:
            GPIO.setmode(GPIO.BCM)
            pull_encoder = GPIO.PUD_UP if str(args.encoder_pull).lower() == "up" else GPIO.PUD_DOWN
            pull_rotate = GPIO.PUD_UP if str(args.rotate_pull).lower() == "up" else GPIO.PUD_DOWN

            if encoder_pin_s1 is not None and encoder_pin_s2 is not None:
                GPIO.setup(int(encoder_pin_s1), GPIO.IN, pull_up_down=pull_encoder)
                GPIO.setup(int(encoder_pin_s2), GPIO.IN, pull_up_down=pull_encoder)
                prev_ab = (GPIO.input(int(encoder_pin_s1)) << 1) | GPIO.input(int(encoder_pin_s2))
                gpio_pins_in_use.update({int(encoder_pin_s1), int(encoder_pin_s2)})
                encoder_ready = True

            if encoder_key_pin is not None:
                GPIO.setup(int(encoder_key_pin), GPIO.IN, pull_up_down=pull_encoder)
                prev_key = GPIO.input(int(encoder_key_pin))
                active_low = str(args.encoder_key_active).lower() == "low"
                key_is_down = bool((prev_key == GPIO.LOW) if active_low else (prev_key == GPIO.HIGH))
                if key_is_down:
                    key_down_at = time.time()
                gpio_pins_in_use.add(int(encoder_key_pin))

            if rotate_pin is not None:
                if encoder_key_pin is not None and int(rotate_pin) == int(encoder_key_pin):
                    print(f"[warn] rotate-pin {int(rotate_pin)} equals encoder-key-pin; dedicated rotate button disabled.")
                else:
                    GPIO.setup(int(rotate_pin), GPIO.IN, pull_up_down=pull_rotate)
                    rotate_prev = GPIO.input(int(rotate_pin))
                    gpio_pins_in_use.add(int(rotate_pin))
                    rotate_btn_ready = True

            if encoder_ready:
                print(
                    "[gpio] rotary enabled: "
                    f"s1={encoder_pin_s1} s2={encoder_pin_s2} key={encoder_key_pin} "
                    f"pull={args.encoder_pull} key_active={args.encoder_key_active} "
                    f"steps_per_detent={max(1, int(args.encoder_steps_per_detent))} "
                    f"flip_direction={bool(args.encoder_flip_direction)}"
                )
            if rotate_btn_ready:
                print(
                    f"[gpio] rotate button enabled: pin={int(rotate_pin)} active={args.rotate_active} "
                    f"pull={args.rotate_pull} debounce_ms={int(args.rotate_debounce_ms)}"
                )
        except Exception as e:
            print(f"[warn] failed to init GPIO inputs: {e}")
            encoder_ready = False
            rotate_btn_ready = False

    try:
        print("Controls: Left/Right rotate, Enter click, Hold encoder=long press, Space voice, R rotate screen, S settings, W weather, B/Esc back, Q quit")
        next_tick = time.time()
        while True:
            now = time.time()
            expire_pending_voice_confirmation(state, now=now)
            key = _read_key_nonblocking()

            ev = None
            voice_flow_ran = False
            if encoder_ready:
                try:
                    curr_ab = (GPIO.input(int(encoder_pin_s1)) << 1) | GPIO.input(int(encoder_pin_s2))
                    if curr_ab != prev_ab:
                        edge = (prev_ab, curr_ab)
                        if edge in CW_SEQ:
                            encoder_accum += 1
                        elif edge in CCW_SEQ:
                            encoder_accum -= 1

                        step_n = max(1, int(args.encoder_steps_per_detent))
                        flip = bool(args.encoder_flip_direction)
                        if encoder_accum >= step_n:
                            logical_cw = not flip
                            ev = Rotate(+1 if logical_cw else -1)
                            encoder_accum = 0
                        elif encoder_accum <= -step_n:
                            logical_cw = flip
                            ev = Rotate(+1 if logical_cw else -1)
                            encoder_accum = 0
                        prev_ab = curr_ab
                except Exception:
                    pass

            if encoder_key_pin is not None and ev is None:
                try:
                    curr_key = GPIO.input(int(encoder_key_pin))
                    active_low = str(args.encoder_key_active).lower() == "low"
                    prev_is_down = bool((prev_key == GPIO.LOW) if active_low else (prev_key == GPIO.HIGH))
                    curr_is_down = bool((curr_key == GPIO.LOW) if active_low else (curr_key == GPIO.HIGH))

                    if curr_is_down != prev_is_down:
                        if curr_is_down:
                            # Debounce only on press edge so short click release is not swallowed.
                            if (now - key_last_edge_at) >= encoder_key_debounce_s:
                                key_last_edge_at = now
                                key_is_down = True
                                key_down_at = now
                                key_long_sent = False
                        else:
                            if key_is_down:
                                press_dur = max(0.0, now - key_down_at)
                                if (not key_long_sent) and press_dur < encoder_key_long_press_s:
                                    ev = Click()
                            key_is_down = False
                            key_down_at = 0.0
                            key_long_sent = False
                            key_last_edge_at = now
                    prev_key = curr_key
                except Exception:
                    pass

            if encoder_key_pin is not None and ev is None and key_is_down and not key_long_sent:
                if (now - key_down_at) >= encoder_key_long_press_s:
                    ev = LongPress()
                    key_long_sent = True

            if rotate_btn_ready and ev is None:
                try:
                    curr = GPIO.input(int(rotate_pin))
                    active_low = str(args.rotate_active).lower() == "low"
                    pressed = (
                        (active_low and rotate_prev == GPIO.HIGH and curr == GPIO.LOW)
                        or ((not active_low) and rotate_prev == GPIO.LOW and curr == GPIO.HIGH)
                    )
                    rotate_prev = curr
                    if pressed and (now - rotate_btn_last_press_at) >= rotate_debounce_s:
                        ev = RotateButton()
                        rotate_btn_last_press_at = now
                except Exception:
                    pass

            if key in ("\x1b[D", "h"):  # left
                ev = Rotate(-1)
            elif key in ("\x1b[C", "l"):  # right
                ev = Rotate(+1)
            elif key in ("\r", "\n"):  # enter
                pending_tool = str(state.ui.voice_confirm_tool or "").strip()
                confirmed = confirm_pending_voice_action(state, now=now)
                if confirmed is not None:
                    _set_voice_overlay(
                        state,
                        confirmed.status,
                        "Heard: [physical confirm]\nAction: "
                        + (pending_tool or "confirm")
                        + "(confirm)\nResult: "
                        + str(confirmed.message or ""),
                        hold_s=2.4,
                    )
                    ev = None
                else:
                    ev = Click()
            elif key == " ":
                # Voice record + send flow on keyboard space.
                _run_voice_flow(
                    state=state,
                    epd=epd,
                    fonts=fonts,
                    theme=theme,
                    panel_threshold=panel_threshold,
                    panel_muted=panel_muted,
                    panel_gamma=panel_gamma,
                    panel_dither=panel_dither,
                    voice_api_url=str(args.voice_api_url or ""),
                    voice_locale=str(args.voice_locale or "zh-CN"),
                    voice_timezone=str(args.voice_timezone or "UTC"),
                    voice_timeout_s=float(args.voice_timeout),
                    voice_max_sec=max(1, int(args.voice_max_sec)),
                    voice_audio_device=str(args.voice_audio_device or "default"),
                    voice_audio_rate=max(8000, int(args.voice_audio_rate)),
                    voice_audio_channels=max(1, int(args.voice_audio_channels)),
                )
                voice_flow_ran = True
                ev = None
            elif key in ("p", "P"):
                # Keep a manual way to trigger legacy long-press behavior in console.
                ev = LongPress()
            elif key in ("r", "R"):
                ev = RotateButton()
            elif key in ("b", "B", "\x7f", "\x1b"):  # backspace / esc
                ev = Back()
            elif key in ("s", "S"):
                state.ui.screen = Screen.SETTINGS
            elif key in ("w", "W"):
                if state.ui.screen == Screen.HOME:
                    state.ui.screen = Screen.WEATHER
                    state.ui.weather_day_index = 0
            elif key in ("q", "Q"):
                return 0

            if ev is not None:
                reduce(state, ev, theme=theme)

            if now >= next_tick:
                reduce(state, Tick(now=now), theme=theme)
                next_tick = now + float(args.tick)

            # Voice flow renders directly to EPD; resync committed snapshot/frame.
            if voice_flow_ran:
                committed_frame = _render_frame(
                    epd,
                    state,
                    fonts,
                    theme,
                    panel_threshold=panel_threshold,
                    panel_muted=panel_muted,
                    panel_gamma=panel_gamma,
                    panel_dither=panel_dither,
                )
                committed_sig = _state_render_sig(state)
                committed_snapshot = build_ui_snapshot(state)
                pending_frame = None
                pending_sig = None
                pending_snapshot = None
                pending_reasons = []
                refresh_runtime.clear_pending()
                refresh_runtime.mark_fast_full(now)

            # Stage updates against the last committed frame.
            sig = _state_render_sig(state)
            if sig != committed_sig:
                frame = _render_frame(
                    epd,
                    state,
                    fonts,
                    theme,
                    panel_threshold=panel_threshold,
                    panel_muted=panel_muted,
                    panel_gamma=panel_gamma,
                    panel_dither=panel_dither,
                )
                curr_snapshot = build_ui_snapshot(state)
                diff_box = ImageChops.difference(committed_frame, frame).getbbox()
                if diff_box is None:
                    pending_frame = None
                    pending_sig = None
                    pending_snapshot = None
                    pending_reasons = []
                    refresh_runtime.clear_pending()
                    committed_sig = sig
                    committed_snapshot = curr_snapshot
                else:
                    dirty_rects, dirty_reasons = infer_dirty_rects_with_reasons(
                        committed_snapshot,
                        curr_snapshot,
                        epd.width,
                        epd.height,
                    )
                    if dirty_rects:
                        merged_dirty = merge_rects(dirty_rects, epd.width, epd.height)
                        if merged_dirty is None or not rect_contains(merged_dirty, diff_box, slack=4):
                            dirty_rects.append(diff_box)
                            dirty_reasons.append("diff_fallback")
                    else:
                        dirty_rects = [diff_box]
                        dirty_reasons = ["diff_only"]
                    if _should_collapse_to_latest(curr_snapshot.screen, dirty_reasons):
                        # Drop intermediate focus-transition frames; keep only latest target state.
                        refresh_runtime.clear_pending()
                    refresh_runtime.enqueue(dirty_rects)
                    pending_frame = frame
                    pending_sig = sig
                    pending_snapshot = curr_snapshot
                    pending_reasons = dirty_reasons

            # Flush staged updates with policy-driven refresh level.
            if pending_frame is not None and pending_snapshot is not None:
                policy_mode = _screen_mode_with_theme(
                    pending_snapshot.screen,
                    pending_snapshot.partial_refresh_mode,
                    theme,
                )
                min_gap_ms = _mode_gap_with_theme(policy_mode, theme)
                full_every = effective_full_refresh_every(
                    screen=pending_snapshot.screen,
                    mode=policy_mode,
                    ui_full_refresh_every=pending_snapshot.full_refresh_every,
                    timer_full_refresh_every_override=_timer_partial_full_every(theme),
                )
                full_clean_reason = refresh_runtime.full_clean_reason(now, full_refresh_every=full_every)
                force_full_clean = bool(full_clean_reason)
                screen_changed = pending_snapshot.screen != committed_snapshot.screen
                rotation_changed = pending_snapshot.rotation_deg != committed_snapshot.rotation_deg
                font_size_changed = pending_snapshot.font_size != committed_snapshot.font_size
                force_flush = force_full_clean or screen_changed or rotation_changed

                if not refresh_runtime.should_throttle(now, min_gap_ms) or force_flush:
                    fast_full = _fast_full_enabled(theme)
                    try:
                        if force_full_clean:
                            driver_mode = _blit_full(epd, pending_frame, driver_mode, fast=False)
                            refresh_runtime.mark_full_clean(now)
                            if refresh_debug:
                                print(
                                    f"[refresh] R3_FULL_CLEAN screen={pending_snapshot.screen.value} "
                                    f"reason={full_clean_reason} partial_count={refresh_runtime.partial_count} "
                                    f"full_every={full_every} mode={policy_mode} "
                                    f"dirty={','.join(pending_reasons) or '-'}"
                                )
                        elif screen_changed or rotation_changed:
                            driver_mode = _blit_full(epd, pending_frame, driver_mode, fast=fast_full)
                            refresh_runtime.mark_fast_full(now)
                            if refresh_debug:
                                reason = "screen_changed" if screen_changed else "rotation_changed"
                                print(
                                    f"[refresh] R2_FAST_FULL screen={pending_snapshot.screen.value} "
                                    f"reason={reason} mode={policy_mode} "
                                    f"fast={'on' if fast_full else 'off'}"
                                )
                        elif pending_snapshot.screen == Screen.SETTINGS and font_size_changed:
                            # Font-size updates often trigger full layout reflow.
                            driver_mode = _blit_full(epd, pending_frame, driver_mode, fast=False)
                            refresh_runtime.mark_full_clean(now)
                            if refresh_debug:
                                print(
                                    f"[refresh] R3_FULL_CLEAN screen={pending_snapshot.screen.value} "
                                    f"reason=settings.font_size_reflow mode={policy_mode}"
                                )
                        else:
                            merged_pending = merge_rects(refresh_runtime.pending_dirty_rects, epd.width, epd.height)
                            family_only = (
                                pending_snapshot.screen == Screen.HOME
                                and pending_reasons
                                and all(r in ("home.family_board_update", "diff_fallback") for r in pending_reasons)
                            )
                            partial_pad = 1 if family_only else 2
                            aligned = (
                                align_rect_for_partial(merged_pending, epd.width, epd.height, pad=partial_pad)
                                if merged_pending is not None
                                else None
                            )
                            partial_enabled = _screen_partial_enabled_with_theme(pending_snapshot.screen, theme)
                            mode_limit = _screen_area_limit_with_theme(
                                pending_snapshot.screen,
                                policy_mode,
                                theme,
                            )
                            if pending_snapshot.screen == Screen.HOME and "home.family_board_update" in pending_reasons:
                                mode_limit = max(mode_limit, _home_family_area_limit_with_theme(theme))
                            area_ratio = (
                                rect_area_ratio(aligned, epd.width, epd.height)
                                if aligned is not None
                                else 1.0
                            )
                            if (
                                supports_partial
                                and partial_enabled
                                and aligned is not None
                                and area_ratio <= mode_limit
                            ):
                                driver_mode = _blit_partial(epd, pending_frame, aligned, driver_mode)
                                refresh_runtime.mark_partial(now)
                                if refresh_debug:
                                    ax0, ay0, ax1, ay1 = aligned
                                    print(
                                        f"[refresh] R1_PARTIAL_RECT screen={pending_snapshot.screen.value} "
                                        f"rect=({ax0},{ay0},{ax1},{ay1}) area_ratio={area_ratio:.3f} "
                                        f"limit={mode_limit:.3f} partial_count={refresh_runtime.partial_count}/{full_every} "
                                        f"mode={policy_mode} dirty={','.join(pending_reasons) or '-'}"
                                    )
                            else:
                                driver_mode = _blit_full(epd, pending_frame, driver_mode, fast=fast_full)
                                refresh_runtime.mark_fast_full(now)
                                if refresh_debug:
                                    why = "partial_unsupported"
                                    if not partial_enabled:
                                        why = "partial_disabled_for_screen"
                                    elif aligned is None:
                                        why = "no_aligned_rect"
                                    elif area_ratio > mode_limit:
                                        why = "area_over_limit"
                                    print(
                                        f"[refresh] R2_FAST_FULL screen={pending_snapshot.screen.value} reason={why} "
                                        f"area_ratio={area_ratio:.3f} limit={mode_limit:.3f} "
                                        f"mode={policy_mode} fast={'on' if fast_full else 'off'} "
                                        f"dirty={','.join(pending_reasons) or '-'}"
                                    )
                    except Exception as e:
                        screen_name = str(
                            pending_snapshot.screen.value
                            if isinstance(pending_snapshot.screen, Screen)
                            else pending_snapshot.screen
                        )
                        print(f"[warn] {screen_name} refresh failed, fallback to full clean: {e}")
                        driver_mode = _blit_full(epd, pending_frame, driver_mode, fast=False)
                        refresh_runtime.mark_full_clean(now)
                        if refresh_debug:
                            print(
                                f"[refresh] R3_FULL_CLEAN screen={screen_name} reason=exception "
                                f"mode={policy_mode}"
                            )

                    committed_frame = pending_frame
                    committed_sig = pending_sig
                    committed_snapshot = pending_snapshot
                    pending_frame = None
                    pending_sig = None
                    pending_snapshot = None
                    pending_reasons = []
                    refresh_runtime.clear_pending()
                elif refresh_debug:
                    print(
                        f"[refresh] HOLD screen={pending_snapshot.screen.value} "
                        f"reason=throttle gap_ms={min_gap_ms} mode={policy_mode} "
                        f"dirty={','.join(pending_reasons) or '-'}"
                    )

            time.sleep(0.01)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
        if GPIO is not None and gpio_pins_in_use:
            try:
                GPIO.cleanup(list(gpio_pins_in_use))
            except Exception:
                pass
        try:
            epd.sleep()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
