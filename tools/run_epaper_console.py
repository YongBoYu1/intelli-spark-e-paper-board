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
import datetime
import json
import os
import select
import subprocess
import sys
import termios
import tempfile
import time
import tty
from zoneinfo import ZoneInfo

from PIL import Image, ImageChops

# Ensure repo root is importable when running this script directly.
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from app.core.reducer import (
    reduce,
    Rotate,
    Click,
    LongPress,
    RotateButton,
    Back,
    Tick,
    apply_onboarding_voice_demo_result,
    apply_onboarding_voice_demo_error,
    open_onboarding_voice_guide,
)
from app.core.state import AppState, DashboardModel, Reminder, WeatherDay, CalendarEvent, MemoItem, Screen
from app.data.location import resolve_dashboard_location
from app.data.device_config import (
    default_device_config,
    detect_local_timezone,
    load_device_config,
    sanitize_device_config,
    save_device_config,
)
from app.data.weather_api import resolve_weather_data
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


def _first_present_value(*values):
    for v in values:
        if v is None:
            continue
        if isinstance(v, str) and not v.strip():
            continue
        return v
    return None


def _weather_rows_from_model(state: AppState) -> list[dict]:
    rows: list[dict] = []
    for w in list(getattr(state.model, "weather", []) or []):
        row = {
            "dow": str(getattr(w, "dow", "") or ""),
            "icon": str(getattr(w, "icon", "sun") or "sun"),
            "hi": int(getattr(w, "hi", 0) or 0),
            "lo": int(getattr(w, "lo", 0) or 0),
        }
        if getattr(w, "humidity", None) is not None:
            row["humidity"] = int(getattr(w, "humidity"))
        if getattr(w, "feels_like", None) is not None:
            row["feels_like"] = float(getattr(w, "feels_like"))
        if getattr(w, "wind_kmh", None) is not None:
            row["wind_kmh"] = float(getattr(w, "wind_kmh"))
        if getattr(w, "uv_index", None) is not None:
            row["uv_index"] = float(getattr(w, "uv_index"))
        rows.append(row)
    return rows


def _weather_days_from_rows(rows: object) -> list[WeatherDay]:
    days: list[WeatherDay] = []
    if not isinstance(rows, list):
        return days
    for w in rows:
        if not isinstance(w, dict):
            continue
        try:
            days.append(
                WeatherDay(
                    dow=str(w.get("dow", "")),
                    icon=str(w.get("icon", "sun")),
                    hi=int(w.get("hi", 0)),
                    lo=int(w.get("lo", 0)),
                    humidity=_parse_optional_humidity(w.get("humidity")),
                    feels_like=_parse_optional_number(
                        _first_present_value(
                            w.get("feels_like"),
                            w.get("feelsLike"),
                            w.get("feels"),
                            w.get("apparent_temp"),
                        )
                    ),
                    wind_kmh=_parse_optional_number(
                        _first_present_value(
                            w.get("wind_kmh"),
                            w.get("windKmh"),
                            w.get("wind_speed"),
                            w.get("wind"),
                        )
                    ),
                    uv_index=_parse_optional_number(
                        _first_present_value(
                            w.get("uv_index"),
                            w.get("uv"),
                            w.get("uvi"),
                        )
                    ),
                )
            )
        except Exception:
            continue
    return days


def _weather_digest(days: list[WeatherDay]) -> tuple:
    return tuple((d.dow, d.icon, d.hi, d.lo, d.humidity, d.feels_like, d.wind_kmh, d.uv_index) for d in days)


def _refresh_live_weather(state: AppState) -> bool:
    base_location = resolve_dashboard_location(getattr(state.model, "location", ""))
    fallback_rows = _weather_rows_from_model(state)
    next_location, rows = resolve_weather_data(base_location, fallback_rows)
    next_days = _weather_days_from_rows(rows)
    if not next_days:
        return False

    prev_location = str(getattr(state.model, "location", "") or "")
    prev_digest = _weather_digest(list(getattr(state.model, "weather", []) or []))
    next_digest = _weather_digest(next_days)

    state.model.location = str(next_location or prev_location or "Unknown")
    state.model.weather = next_days

    # Keep selected index in bounds if day count changes.
    if state.model.weather:
        state.ui.weather_day_index = int(state.ui.weather_day_index or 0) % len(state.model.weather)
    else:
        state.ui.weather_day_index = 0

    return (state.model.location != prev_location) or (next_digest != prev_digest)


def _next_weather_refresh_at(now_ts: float, refresh_hours: float, *, tz_name: str = "") -> float:
    hours = max(0.0, float(refresh_hours or 0.0))
    if hours <= 0:
        return 0.0

    # For the default 12h schedule, align to local wall-clock boundaries:
    # noon and midnight (00:00 / 12:00), instead of startup+12h drift.
    if abs(hours - 12.0) < 1e-6:
        tz = None
        tz_key = str(tz_name or "").strip()
        if tz_key:
            try:
                tz = ZoneInfo(tz_key)
            except Exception:
                tz = None
        now_local = datetime.datetime.fromtimestamp(now_ts, tz=tz) if tz is not None else datetime.datetime.fromtimestamp(now_ts)
        today_noon = now_local.replace(hour=12, minute=0, second=0, microsecond=0)
        if now_local < today_noon:
            return today_noon.timestamp()
        tomorrow_midnight = (now_local + datetime.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        return tomorrow_midnight.timestamp()

    return now_ts + (hours * 3600.0)


def _load_model(repo_root: str) -> DashboardModel:
    path = os.path.join(repo_root, "data", "dashboard.json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
    else:
        d = {}

    location = resolve_dashboard_location(d.get("location"))
    location, weather_rows = resolve_weather_data(location, d.get("weather"))

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
    for w in weather_rows:
        try:
            weather.append(
                WeatherDay(
                    dow=str(w.get("dow", "")),
                    icon=str(w.get("icon", "sun")),
                    hi=int(w.get("hi", 0)),
                    lo=int(w.get("lo", 0)),
                    humidity=_parse_optional_humidity(w.get("humidity")),
                    feels_like=_parse_optional_number(
                        _first_present_value(
                            w.get("feels_like"),
                            w.get("feelsLike"),
                            w.get("feels"),
                            w.get("apparent_temp"),
                        )
                    ),
                    wind_kmh=_parse_optional_number(
                        _first_present_value(
                            w.get("wind_kmh"),
                            w.get("windKmh"),
                            w.get("wind_speed"),
                            w.get("wind"),
                        )
                    ),
                    uv_index=_parse_optional_number(
                        _first_present_value(
                            w.get("uv_index"),
                            w.get("uv"),
                            w.get("uvi"),
                        )
                    ),
                )
            )
        except Exception:
            continue

    cal: list[CalendarEvent] = []
    rows = d.get("calendar")
    if isinstance(rows, list) and rows:
        for i, item in enumerate(rows):
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or item.get("text") or "").strip()
            when = str(item.get("when") or item.get("time") or "").strip()
            date_iso = str(item.get("date_iso") or item.get("date") or "").strip()
            cal.append(
                CalendarEvent(
                    eid=str(item.get("id") or item.get("eid") or f"e{i}"),
                    title=title,
                    when=when,
                    date_iso=date_iso,
                )
            )
    if not cal:
        today_iso = datetime.date.today().isoformat()
        tomorrow_iso = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
        cal = [
            CalendarEvent("e0", "Dinner with Alex", "19:00", date_iso=today_iso),
            CalendarEvent("e1", "Gym Session", "08:00", date_iso=tomorrow_iso),
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
        location=location,
        battery=int(d.get("battery") or 84),
        reminders=reminders,
        weather=weather,
        calendar=cal,
        memos=memos,
    )


def _dashboard_data_path(repo_root: str) -> str:
    return os.path.join(repo_root, "data", "dashboard.json")


def _read_key_nonblocking(escape_sequence_timeout_s: float = 0.06) -> str:
    r, _, _ = select.select([sys.stdin], [], [], 0)
    if not r:
        return ""
    ch = sys.stdin.read(1)
    if ch != "\x1b":
        return ch
    # Arrow keys can arrive split over multiple reads on Pi/SSH terminals.
    # Collect a short ESC tail so cursor-key sequences are not mistaken for Back.
    tail = ""
    deadline = time.monotonic() + max(0.0, float(escape_sequence_timeout_s))
    while time.monotonic() < deadline and len(tail) < 8:
        remaining = max(0.0, deadline - time.monotonic())
        tail_ready, _, _ = select.select([sys.stdin], [], [], remaining)
        if not tail_ready:
            break
        nxt = sys.stdin.read(1)
        if not nxt:
            break
        tail += nxt
        if tail in ("[A", "[B", "[C", "[D", "OA", "OB", "OC", "OD"):
            return f"\x1b[{tail[-1]}"
        if len(tail) >= 2 and tail[0] == "[" and tail[-1] in "ABCD":
            return f"\x1b[{tail[-1]}"
    return "\x1b"


def _drain_stdin_nonblocking(*, max_chars: int = 256) -> str:
    drained: list[str] = []
    remaining = max(0, int(max_chars))
    while remaining > 0:
        r, _, _ = select.select([sys.stdin], [], [], 0)
        if not r:
            break
        ch = sys.stdin.read(1)
        if not ch:
            break
        drained.append(ch)
        remaining -= 1
    return "".join(drained)


def _warn_missing_fonts(fonts: FontBook) -> None:
    missing = fonts.missing_font_paths()
    if not missing:
        return
    print("[warn] Missing font files. Rendering will fall back and quality may degrade:")
    for key, path in missing:
        print(f"  - {key}: {path}")


def _device_config_from_state(state: AppState) -> dict:
    return sanitize_device_config(
        {
            "setup_completed": bool(state.ui.setup_completed),
            "language": str(state.ui.device_language or "en-US"),
            "voice_locale": str(state.ui.voice_locale or "en-US"),
            "timezone": str(state.ui.device_timezone or "UTC"),
            "auto_sync_enabled": bool(state.ui.auto_sync_enabled),
            "wifi_enabled": bool(state.ui.wifi_enabled),
            "bluetooth_enabled": bool(state.ui.bluetooth_enabled),
            "wifi_ssid": str(state.ui.onboarding_wifi_ssid or ""),
        }
    )


def _landing_voice_demo_index(locale: str) -> int:
    norm = str(locale or "en-US").strip()
    if norm == "es-ES":
        return 1
    if norm == "fr-FR":
        return 2
    return 0


def _apply_device_config_to_state(state: AppState, config: dict) -> None:
    cfg = sanitize_device_config(config)
    state.ui.setup_completed = bool(cfg.get("setup_completed", False))
    state.ui.device_language = str(cfg.get("language") or "en-US")
    state.ui.voice_locale = str(cfg.get("voice_locale") or "en-US")
    state.ui.device_timezone = str(cfg.get("timezone") or detect_local_timezone())
    state.ui.auto_sync_enabled = bool(cfg.get("auto_sync_enabled", True))
    state.ui.wifi_enabled = bool(cfg.get("wifi_enabled", False))
    state.ui.bluetooth_enabled = bool(cfg.get("bluetooth_enabled", False))
    state.ui.onboarding_wifi_ssid = str(cfg.get("wifi_ssid") or "")


def _initialize_boot_flow_state(state: AppState, theme: dict, *, now: float | None = None) -> None:
    started_at = time.time() if now is None else float(now)
    state.ui.boot_started_at = started_at
    state.ui.boot_min_show_s = 0.0
    state.ui.landing_rotate_seen = False
    state.ui.landing_confirm_seen = False
    state.ui.landing_voice_demo_index = _landing_voice_demo_index(state.ui.voice_locale)
    state.ui.landing_voice_demo_cycles = 0
    state.ui.landing_last_demo_at = started_at
    # Seed the same copy that landing Tick would compute, so boot/reset does not
    # immediately trigger a large landing partial update on the next frame.
    state.ui.landing_status = "Rotate knob to choose language."
    state.ui.onboarding_focus_index = 0
    state.ui.onboarding_qr_focus_index = 0
    state.ui.onboarding_prefs_focus_index = 0
    state.ui.onboarding_voice_guide_focus_index = 0
    state.ui.onboarding_voice_demo_heard = ""
    state.ui.onboarding_voice_demo_attempted = False
    state.ui.onboarding_voice_demo_case_index = 0
    state.ui.onboarding_voice_demo_pass_mask = 0
    state.ui.onboarding_voice_demo_action = ""
    state.ui.onboarding_voice_sample_text = "Add milk to inventory"
    state.ui.onboarding_voice_expected_action = "Add inventory"
    if bool(state.ui.setup_completed):
        state.ui.screen = Screen.HOME
    elif bool(theme.get("boot_landing_enabled", True)):
        state.ui.screen = Screen.LANDING
    else:
        state.ui.screen = Screen.ONBOARDING
        state.ui.onboarding_step = "start"


def _apply_factory_reset(state: AppState, repo_root: str, theme: dict, *, now: float | None = None) -> dict:
    config = sanitize_device_config(default_device_config())
    dashboard_path = _dashboard_data_path(repo_root)
    try:
        if os.path.exists(dashboard_path):
            os.remove(dashboard_path)
    except FileNotFoundError:
        pass
    save_device_config(repo_root, config)
    state.model = _load_model(repo_root)
    state.ui = AppState(model=state.model).ui
    _apply_device_config_to_state(state, config)
    _initialize_boot_flow_state(state, theme, now=now)
    state.ui.settings_reset_dialog_open = False
    state.ui.settings_reset_dialog_confirm = False
    state.ui.factory_reset_requested = False
    return config


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
    out = quantize_for_panel(
        rgb,
        threshold=int(panel_threshold),
        gamma=float(panel_gamma),
        dither=panel_dither,
    )
    return out


def _state_render_sig(state: AppState):
    return (
        state.model.location,
        state.ui.screen,
        state.ui.setup_completed,
        state.ui.landing_rotate_seen,
        state.ui.landing_confirm_seen,
        state.ui.landing_voice_demo_index,
        state.ui.landing_voice_demo_cycles,
        state.ui.landing_status,
        state.ui.onboarding_step,
        state.ui.onboarding_focus_index,
        state.ui.onboarding_qr_focus_index,
        state.ui.onboarding_prefs_focus_index,
        state.ui.onboarding_voice_guide_focus_index,
        state.ui.onboarding_pair_token,
        int(state.ui.onboarding_pair_expires_at or 0),
        state.ui.onboarding_status,
        state.ui.onboarding_voice_demo_heard,
        state.ui.onboarding_voice_demo_attempted,
        state.ui.onboarding_wifi_ssid,
        state.ui.device_language,
        state.ui.device_timezone,
        state.ui.voice_locale,
        state.ui.focused_index,
        state.ui.kitchen_focus_rid_override,
        tuple(str(rid) for rid in getattr(state.ui, "home_hidden_rids", []) if str(rid or "").strip()),
        state.ui.page,
        state.ui.idle,
        state.ui.widget_mode,
        state.ui.clock_minute_bucket,
        state.ui.timer_seconds,
        state.ui.timer_running,
        state.ui.timer_focused_index,
        state.ui.timer_target_seconds,
        state.ui.timer_alert_active,
        state.ui.timer_alert_blink_on,
        state.ui.timer_alert_until,
        state.ui.timer_last_completed_seconds,
        state.ui.voice_active,
        state.ui.voice_phase,
        state.ui.voice_message,
        state.ui.menu_focused,
        state.ui.menu_overlay_active,
        state.ui.active_menu,
        state.ui.settings_focused_index,
        state.ui.settings_reset_dialog_open,
        state.ui.settings_reset_dialog_confirm,
        state.ui.font_size,
        state.ui.weather_day_index,
        state.ui.calendar_offset_days,
        state.ui.calendar_mode,
        state.ui.calendar_selected_index,
        state.ui.memo_index,
        state.ui.memo_expanded,
        state.ui.list_focused_index,
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
        tuple((c.eid, c.title, c.when, c.date_iso) for c in state.model.calendar),
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


def _blit_full_clean(epd, image: Image.Image) -> str:
    # Force a clean full refresh cycle regardless of current driver mode.
    epd.init()
    clear_fn = getattr(epd, "Clear", None)
    if callable(clear_fn):
        clear_fn()
    epd.display(epd.getbuffer(image))
    return "full"


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


def _home_menu_overlay_area_limit_with_theme(theme: dict) -> float:
    raw = theme.get("refresh_area_limit_home_menu_overlay", 0.60)
    try:
        value = float(raw)
    except Exception:
        value = 0.60
    return max(0.05, min(0.98, value))


def _fast_full_enabled(theme: dict) -> bool:
    return bool(theme.get("refresh_enable_fast_full", False))


def _partial_budget_enabled_with_theme(theme: dict) -> bool:
    return bool(theme.get("refresh_partial_budget_enabled", False))


def _screen_partial_enabled_with_theme(screen: Screen, theme: dict) -> bool:
    if bool(theme.get("refresh_partial_enable_all", False)):
        return True

    # Keep first-boot flows on partial-first path (same as other interactive screens).
    default_screens = "timer,home,menu,landing,onboarding"
    default_names = [x.strip().lower() for x in default_screens.split(",") if x.strip()]
    raw = theme.get("refresh_partial_screens", default_screens)
    if isinstance(raw, str):
        names = [x.strip().lower() for x in raw.split(",") if x.strip()]
    elif isinstance(raw, (list, tuple)):
        names = [str(x).strip().lower() for x in raw if str(x).strip()]
    else:
        names = list(default_names)

    # Backward-compatible default: keep core partial screens enabled even when
    # an older theme string only lists a subset (unless strict mode is requested).
    if not bool(theme.get("refresh_partial_screens_strict", False)):
        names = sorted(set(default_names) | set(names))

    screen_name = str(screen.value if isinstance(screen, Screen) else screen).strip().lower()
    return screen_name in set(names)


def _screen_force_full_clean_with_theme(screen: Screen, theme: dict) -> bool:
    # Full-clean should be opt-in only. For onboarding/landing we prefer normal
    # full refresh path unless explicitly configured, to avoid repeated Clear().
    default_screens = ""
    raw = theme.get("refresh_force_full_clean_screens", default_screens)
    if isinstance(raw, str):
        names = [x.strip().lower() for x in raw.split(",") if x.strip()]
    elif isinstance(raw, (list, tuple)):
        names = [str(x).strip().lower() for x in raw if str(x).strip()]
    else:
        names = [x.strip().lower() for x in default_screens.split(",") if x.strip()]
    screen_name = str(screen.value if isinstance(screen, Screen) else screen).strip().lower()
    return screen_name in set(names)


def _partial_gate_area_ratio(
    rects: list[tuple[int, int, int, int]],
    *,
    width: int,
    height: int,
) -> float:
    if not rects:
        return 1.0
    return min(1.0, sum(rect_area_ratio(r, width, height) for r in rects))


def _screen_change_partial_enabled_with_theme(prev_screen: Screen, curr_screen: Screen, theme: dict) -> bool:
    if bool(theme.get("refresh_force_full_on_screen_change", False)):
        return False

    default_screens = "timer,memo,calendar,inventory,reminders,landing,onboarding"
    raw = theme.get("refresh_partial_screen_change_screens", default_screens)
    if isinstance(raw, str):
        names = [x.strip().lower() for x in raw.split(",") if x.strip()]
    elif isinstance(raw, (list, tuple)):
        names = [str(x).strip().lower() for x in raw if str(x).strip()]
    else:
        names = [x.strip().lower() for x in default_screens.split(",") if x.strip()]

    curr_name = str(curr_screen.value if isinstance(curr_screen, Screen) else curr_screen).strip().lower()
    if curr_name not in set(names):
        return False

    # Respect per-screen partial switch as well.
    return _screen_partial_enabled_with_theme(curr_screen, theme)


def _screen_change_force_partial_with_theme(screen: Screen, theme: dict) -> bool:
    if not bool(theme.get("refresh_force_partial_on_screen_change", True)):
        return False

    # Settings entry often covers most of the panel; forcing partial there can
    # produce near-full partial refreshes that leave visible artifacts on e-paper.
    default_screens = "timer,memo,calendar,inventory,reminders"
    raw = theme.get("refresh_force_partial_on_screen_change_screens", default_screens)
    if isinstance(raw, str):
        names = [x.strip().lower() for x in raw.split(",") if x.strip()]
    elif isinstance(raw, (list, tuple)):
        names = [str(x).strip().lower() for x in raw if str(x).strip()]
    else:
        names = [x.strip().lower() for x in default_screens.split(",") if x.strip()]
    screen_name = str(screen.value if isinstance(screen, Screen) else screen).strip().lower()
    return screen_name in set(names)


def _calendar_force_partial_with_theme(theme: dict) -> bool:
    return bool(theme.get("refresh_calendar_force_partial", True))


def _prepare_partial_rects(
    rects: list[tuple[int, int, int, int]],
    *,
    width: int,
    height: int,
    pad: int,
    max_rects: int,
    merge_overflow: bool = True,
) -> list[tuple[int, int, int, int]]:
    aligned: list[tuple[int, int, int, int]] = []
    for rect in rects:
        clipped = align_rect_for_partial(rect, width, height, pad=pad)
        if clipped is None:
            continue
        # Skip duplicates/fully-contained rects.
        if any(rect_contains(existing, clipped, slack=0) for existing in aligned):
            continue
        aligned = [r for r in aligned if not rect_contains(clipped, r, slack=0)]
        aligned.append(clipped)

    if not aligned:
        return []

    # Keep predictable order for debug/readability.
    aligned.sort(key=lambda r: (r[1], r[0], (r[2] - r[0]) * (r[3] - r[1])))

    max_n = max(1, int(max_rects))
    if len(aligned) <= max_n:
        return aligned

    if not bool(merge_overflow):
        return aligned[:max_n]

    merged = merge_rects(aligned, width, height)
    return [merged] if merged is not None else []


def _diff_bbox_and_ratio(prev_frame: Image.Image, curr_frame: Image.Image) -> tuple[tuple[int, int, int, int] | None, float]:
    diff = ImageChops.difference(prev_frame, curr_frame).convert("L")
    bbox = diff.getbbox()
    if bbox is None:
        return None, 0.0

    hist = diff.histogram()
    nonzero = int(sum(hist[1:])) if hist else 0
    total = max(1, int(diff.width) * int(diff.height))
    return bbox, (float(nonzero) / float(total))


def _should_collapse_to_latest(screen: Screen, reasons: list[str]) -> bool:
    if not reasons:
        return False
    if screen == Screen.ONBOARDING:
        # For compact onboarding interactions, always keep latest target state and
        # drop queued intermediates to avoid accumulated large dirty unions.
        return any(r.startswith("onboarding.prefs_") or r.startswith("onboarding.voice_") for r in reasons)
    if screen != Screen.HOME:
        return False
    allowed = {
        "home.focus_move_row",
        "home.focus_move_left_target",
        "home.focus_to_left_panel",
        "home.focus_from_left_panel",
        "home.focus_left_panel_only",
        "home.menu_overlay_focus",
        "home.focus_priority_drop_family",
        "diff_fallback",
    }
    has_focus_reason = any(r.startswith("home.focus_") or r == "home.menu_overlay_focus" for r in reasons)
    return has_focus_reason and all(r in allowed for r in reasons)


def _is_onboarding_compact_step(snapshot) -> bool:
    if snapshot.screen != Screen.ONBOARDING:
        return False
    step = str(snapshot.onboarding_step or "").strip().lower()
    return step == "voice_guide"


def _prioritize_home_focus_dirty(
    screen: Screen,
    rects: list[tuple[int, int, int, int]],
    reasons: list[str],
    *,
    width: int,
) -> tuple[list[tuple[int, int, int, int]], list[str]]:
    if screen != Screen.HOME:
        return rects, reasons
    if "home.focus_move_row" not in reasons or "home.family_board_update" not in reasons:
        return rects, reasons

    right_threshold = max(0, int(width * 0.45))
    focus_rects = [r for r in rects if int(r[0]) >= right_threshold]
    if not focus_rects:
        return rects, reasons

    next_reasons = [r for r in reasons if r != "home.family_board_update"]
    if "home.focus_priority_drop_family" not in next_reasons:
        next_reasons.append("home.focus_priority_drop_family")
    return focus_rects, next_reasons


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


def _voice_overlay_rect_for_partial(width: int, height: int, theme: dict, *, rotation_deg: int = 0) -> tuple[int, int, int, int]:
    w = max(1, int(width))
    h = max(1, int(height))
    margin = int(theme.get("voice_zone_margin", 14) or 14)
    zone_w = int(theme.get("voice_zone_width", min(380, max(300, int(w * 0.46)))) or 340)
    zone_w = max(220, min(zone_w, max(220, w - margin * 2)))
    lane_h = int(theme.get("voice_zone_lane_h", 29) or 29)

    x0 = margin
    y1 = h - margin
    y0 = max(margin, y1 - lane_h)
    x1 = x0 + zone_w
    rect = (x0, y0 - 1, x1, y1 + 1)

    if int(rotation_deg or 0) == 180:
        rx0, ry0, rx1, ry1 = rect
        rect = (w - rx1, h - ry1, w - rx0, h - ry0)
    return rect


def _render_voice_overlay_step(
    *,
    epd,
    state: AppState,
    fonts: FontBook,
    theme: dict,
    panel_threshold: int,
    panel_muted: int,
    panel_gamma: float,
    panel_dither: bool,
    current_mode: str,
    supports_partial: bool,
    refresh_debug: bool,
) -> tuple[str, bool]:
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

    voice_partial_enabled = bool(theme.get("refresh_voice_partial", True))
    if supports_partial and voice_partial_enabled:
        rect = _voice_overlay_rect_for_partial(
            epd.width,
            epd.height,
            theme,
            rotation_deg=int(state.ui.rotation_deg or 0),
        )
        aligned = align_rect_for_partial(rect, epd.width, epd.height, pad=2)
        if aligned is not None:
            try:
                next_mode = _blit_partial(epd, frame, aligned, current_mode)
                if refresh_debug:
                    x0, y0, x1, y1 = aligned
                    print(f"[refresh] VOICE_PARTIAL_RECT rect=({x0},{y0},{x1},{y1})")
                return next_mode, False
            except Exception as e:
                if refresh_debug:
                    print(f"[refresh] VOICE_PARTIAL_FAIL reason={e}")

    next_mode = _blit_full(epd, frame, current_mode, fast=_fast_full_enabled(theme))
    if refresh_debug:
        print("[refresh] VOICE_FULL_FALLBACK")
    return next_mode, True


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
    current_mode: str,
    supports_partial: bool,
    refresh_debug: bool,
    demo_only: bool = False,
) -> tuple[str, bool]:
    state.ui.idle = False
    state.ui.last_interaction_at = time.time()
    did_render_step = False
    driver_mode = current_mode

    fd, audio_path = tempfile.mkstemp(prefix="voice_", suffix=".wav", dir="/tmp")
    os.close(fd)

    try:
        _set_voice_overlay(state, "recording", f"Speak within {max(1, int(voice_max_sec))}s")
        driver_mode, _ = _render_voice_overlay_step(
            epd=epd,
            state=state,
            fonts=fonts,
            theme=theme,
            panel_threshold=panel_threshold,
            panel_muted=panel_muted,
            panel_gamma=panel_gamma,
            panel_dither=panel_dither,
            current_mode=driver_mode,
            supports_partial=supports_partial,
            refresh_debug=refresh_debug,
        )
        did_render_step = True

        audio = _record_audio_fixed(
            audio_path=audio_path,
            audio_device=voice_audio_device,
            audio_rate=voice_audio_rate,
            audio_channels=voice_audio_channels,
            max_sec=voice_max_sec,
        )
        if not audio:
            _set_voice_overlay(state, "error", "Recording failed", hold_s=2.0)
            driver_mode, _ = _render_voice_overlay_step(
                epd=epd,
                state=state,
                fonts=fonts,
                theme=theme,
                panel_threshold=panel_threshold,
                panel_muted=panel_muted,
                panel_gamma=panel_gamma,
                panel_dither=panel_dither,
                current_mode=driver_mode,
                supports_partial=supports_partial,
                refresh_debug=refresh_debug,
            )
            did_render_step = True
            return driver_mode, did_render_step

        _set_voice_overlay(state, "processing", "Interpreting command")
        driver_mode, _ = _render_voice_overlay_step(
            epd=epd,
            state=state,
            fonts=fonts,
            theme=theme,
            panel_threshold=panel_threshold,
            panel_muted=panel_muted,
            panel_gamma=panel_gamma,
            panel_dither=panel_dither,
            current_mode=driver_mode,
            supports_partial=supports_partial,
            refresh_debug=refresh_debug,
        )
        did_render_step = True

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
        if demo_only:
            apply_onboarding_voice_demo_result(state, transcript)
            _set_voice_overlay(state, "idle")
        else:
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
        driver_mode, _ = _render_voice_overlay_step(
            epd=epd,
            state=state,
            fonts=fonts,
            theme=theme,
            panel_threshold=panel_threshold,
            panel_muted=panel_muted,
            panel_gamma=panel_gamma,
            panel_dither=panel_dither,
            current_mode=driver_mode,
            supports_partial=supports_partial,
            refresh_debug=refresh_debug,
        )
        did_render_step = True
    except VoiceClientError as e:
        if demo_only:
            apply_onboarding_voice_demo_error(state, str(e))
            _set_voice_overlay(state, "idle")
        else:
            _set_voice_overlay(state, "error", str(e), hold_s=2.5)
        driver_mode, _ = _render_voice_overlay_step(
            epd=epd,
            state=state,
            fonts=fonts,
            theme=theme,
            panel_threshold=panel_threshold,
            panel_muted=panel_muted,
            panel_gamma=panel_gamma,
            panel_dither=panel_dither,
            current_mode=driver_mode,
            supports_partial=supports_partial,
            refresh_debug=refresh_debug,
        )
        did_render_step = True
    except Exception as e:
        if demo_only:
            apply_onboarding_voice_demo_error(state, str(e))
            _set_voice_overlay(state, "idle")
        else:
            _set_voice_overlay(state, "error", f"Voice failed: {e}", hold_s=2.5)
        driver_mode, _ = _render_voice_overlay_step(
            epd=epd,
            state=state,
            fonts=fonts,
            theme=theme,
            panel_threshold=panel_threshold,
            panel_muted=panel_muted,
            panel_gamma=panel_gamma,
            panel_dither=panel_dither,
            current_mode=driver_mode,
            supports_partial=supports_partial,
            refresh_debug=refresh_debug,
        )
        did_render_step = True
    finally:
        try:
            os.remove(audio_path)
        except Exception:
            pass
    return driver_mode, did_render_step


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
        "--encoder-key-min-press-ms",
        type=int,
        default=None,
        help="Minimum stable KEY press duration required to emit a click (default: theme or 35ms)",
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
    parser.add_argument(
        "--weather-refresh-hours",
        type=float,
        default=float(os.environ.get("WEATHER_REFRESH_HOURS", "12")),
        help="Live weather refresh interval in hours (default: 12; at 12h it aligns to local 00:00/12:00; <=0 disables periodic refresh)",
    )
    parser.add_argument("--voice-api-url", default=os.environ.get("VOICE_API_URL", ""), help="Backend URL for POST /voice/interpret")
    parser.add_argument("--voice-locale", default=os.environ.get("VOICE_LOCALE", "en-US"), help="Locale sent to backend")
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
    weather_refresh_hours = max(0.0, float(args.weather_refresh_hours or 0.0))
    weather_refresh_s = weather_refresh_hours * 3600.0
    fonts = _build_fonts(repo_root)
    _warn_missing_fonts(fonts)
    state = AppState(model=_load_model(repo_root))
    device_config = load_device_config(repo_root)
    _apply_device_config_to_state(state, device_config)
    _initialize_boot_flow_state(state, theme)
    persisted_device_config = _device_config_from_state(state)
    save_device_config(repo_root, persisted_device_config)
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
    space_last_trigger_at = 0.0
    gpio_pins_in_use = set()
    encoder_key_debounce_s = max(0.0, float(args.encoder_key_debounce_ms) / 1000.0)
    encoder_key_min_press_ms = args.encoder_key_min_press_ms
    if encoder_key_min_press_ms is None:
        encoder_key_min_press_ms = theme.get("encoder_key_min_press_ms", 35)
    encoder_key_min_press_s = max(0.0, float(encoder_key_min_press_ms) / 1000.0)
    encoder_key_long_press_s = max(0.1, float(args.encoder_key_long_press_ms) / 1000.0)
    rotate_debounce_s = max(0.0, float(args.rotate_debounce_ms) / 1000.0)
    voice_space_cooldown_s = max(0.2, float(theme.get("voice_space_cooldown_s", 1.2) or 1.2))

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
        print("Controls: Left/Right rotate, Enter click, Hold encoder=long press, Space voice (or voice-demo in guide), R rotate screen (+90°), S settings, G voice guide, W weather, B/Esc back, Q quit")
        next_tick = time.time()
        weather_refresh_tz = str(state.ui.device_timezone or "")
        next_weather_refresh_at = _next_weather_refresh_at(next_tick, weather_refresh_hours, tz_name=weather_refresh_tz)
        if weather_refresh_s > 0:
            print(
                f"[weather] periodic refresh enabled: every {weather_refresh_hours:g}h"
                + (f" timezone={weather_refresh_tz}" if weather_refresh_tz else "")
            )
        while True:
            now = time.time()
            expire_pending_voice_confirmation(state, now=now)
            if weather_refresh_s > 0 and now >= next_weather_refresh_at:
                try:
                    changed = _refresh_live_weather(state)
                    if refresh_debug:
                        print(
                            f"[weather] periodic_refresh changed={bool(changed)} "
                            f"city={state.model.location} days={len(state.model.weather)}"
                        )
                except Exception as e:
                    print(f"[warn] periodic weather refresh failed: {e}")
                weather_refresh_tz = str(state.ui.device_timezone or "")
                next_weather_refresh_at = _next_weather_refresh_at(now, weather_refresh_hours, tz_name=weather_refresh_tz)
            key = _read_key_nonblocking()

            ev = None
            voice_flow_ran = False
            voice_flow_demo_only = False
            key_phys_down = bool(key_is_down)
            if encoder_key_pin is not None:
                try:
                    curr_key_sample = GPIO.input(int(encoder_key_pin))
                    active_low = str(args.encoder_key_active).lower() == "low"
                    key_phys_down = bool((curr_key_sample == GPIO.LOW) if active_low else (curr_key_sample == GPIO.HIGH))
                except Exception:
                    key_phys_down = bool(key_is_down)

            if encoder_ready:
                try:
                    curr_ab = (GPIO.input(int(encoder_pin_s1)) << 1) | GPIO.input(int(encoder_pin_s2))
                    if curr_ab != prev_ab:
                        # Ignore quadrature jitter while KEY is held down. Pressing the knob can
                        # produce tiny AB edges that otherwise swallow/shift the click target.
                        if key_phys_down:
                            encoder_accum = 0
                        else:
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

            if encoder_key_pin is not None:
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
                                if (
                                    (not key_long_sent)
                                    and press_dur >= encoder_key_min_press_s
                                    and press_dur < encoder_key_long_press_s
                                ):
                                    ev = Click()
                            key_is_down = False
                            key_down_at = 0.0
                            key_long_sent = False
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
            elif key == "\x03":  # Ctrl+C in raw mode
                return 0
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
                in_voice_guide_demo = (
                    state.ui.screen == Screen.ONBOARDING
                    and str(state.ui.onboarding_step or "").strip().lower() == "voice_guide"
                )
                if ((not bool(state.ui.setup_completed)) or state.ui.screen in (Screen.LANDING, Screen.ONBOARDING)) and (not in_voice_guide_demo):
                    msg = "Voice is available after first setup."
                    if state.ui.screen == Screen.LANDING:
                        state.ui.landing_status = msg
                    elif state.ui.screen == Screen.ONBOARDING:
                        state.ui.onboarding_status = msg
                    if refresh_debug:
                        print("[voice] ignore space trigger reason=onboarding_locked")
                    ev = None
                elif (
                    state.ui.voice_active
                    or (now - float(space_last_trigger_at)) < voice_space_cooldown_s
                ):
                    ev = None
                    if refresh_debug:
                        why = "voice_active" if state.ui.voice_active else "space_cooldown"
                        print(f"[voice] ignore space trigger reason={why}")
                    continue
                else:
                    # Voice record + send flow on keyboard space.
                    voice_flow_demo_only = bool(in_voice_guide_demo)
                    driver_mode, voice_flow_ran = _run_voice_flow(
                        state=state,
                        epd=epd,
                        fonts=fonts,
                        theme=theme,
                        panel_threshold=panel_threshold,
                        panel_muted=panel_muted,
                        panel_gamma=panel_gamma,
                        panel_dither=panel_dither,
                        voice_api_url=str(args.voice_api_url or ""),
                        voice_locale=str(state.ui.voice_locale or args.voice_locale or "en-US"),
                        voice_timezone=str(state.ui.device_timezone or args.voice_timezone or "UTC"),
                        voice_timeout_s=float(args.voice_timeout),
                        voice_max_sec=max(1, int(args.voice_max_sec)),
                        voice_audio_device=str(args.voice_audio_device or "default"),
                        voice_audio_rate=max(8000, int(args.voice_audio_rate)),
                        voice_audio_channels=max(1, int(args.voice_audio_channels)),
                        current_mode=driver_mode,
                        supports_partial=bool(supports_partial),
                        refresh_debug=bool(refresh_debug),
                        demo_only=voice_flow_demo_only,
                    )
                    if voice_flow_demo_only:
                        # Let the normal frame pipeline render the updated onboarding demo panel.
                        voice_flow_ran = False
                    space_last_trigger_at = time.time()
                    buffered = _drain_stdin_nonblocking(max_chars=512)
                    if "\x03" in buffered or "q" in buffered.lower():
                        return 0
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
            elif key in ("g", "G"):
                open_onboarding_voice_guide(state)
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

            if bool(state.ui.factory_reset_requested):
                try:
                    persisted_device_config = _apply_factory_reset(state, repo_root, theme, now=now)
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
                    driver_mode = _blit_full_clean(epd, committed_frame)
                    committed_sig = _state_render_sig(state)
                    committed_snapshot = build_ui_snapshot(state)
                    pending_frame = None
                    pending_sig = None
                    pending_snapshot = None
                    pending_reasons = []
                    refresh_runtime.clear_pending()
                    refresh_runtime.mark_full_clean(now)
                    if refresh_debug:
                        print("[refresh] RESET_TO_LANDING_FULL_CLEAN")
                    weather_refresh_tz = str(state.ui.device_timezone or "")
                    next_weather_refresh_at = _next_weather_refresh_at(now, weather_refresh_hours, tz_name=weather_refresh_tz)
                    continue
                except Exception as e:
                    state.ui.factory_reset_requested = False
                    state.ui.settings_reset_dialog_open = False
                    state.ui.settings_reset_dialog_confirm = False
                    state.ui.settings_notice = "RESET FAILED"
                    state.ui.settings_notice_due_at = time.time() + 3.0
                    print(f"[warn] failed to factory reset device config: {e}")

            current_device_config = _device_config_from_state(state)
            if current_device_config != persisted_device_config:
                try:
                    save_device_config(repo_root, current_device_config)
                    persisted_device_config = dict(current_device_config)
                    if refresh_debug:
                        print("[onboarding] device_config persisted")
                except Exception as e:
                    print(f"[warn] failed to persist device config: {e}")

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
                diff_box, diff_ratio = _diff_bbox_and_ratio(committed_frame, frame)
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
                        if merged_dirty is None:
                            dirty_rects.append(diff_box)
                            dirty_reasons.append("diff_fallback")
                        elif not rect_contains(merged_dirty, diff_box, slack=4):
                            if committed_snapshot.screen != curr_snapshot.screen:
                                # For cross-screen transitions we use structural dirty regions on purpose.
                                # Avoid inflating to a massive bbox fallback, which would force full refresh.
                                if refresh_debug:
                                    print(
                                        f"[refresh] DIFF_FALLBACK_SKIP screen={curr_snapshot.screen.value} "
                                        "reason=screen_changed"
                                    )
                                pass
                            else:
                                # BBox can be overly large when a few distant pixels change.
                                # Only trust bbox fallback when changed-pixel ratio is meaningful.
                                skip_onboarding_diff_fallback = (
                                    curr_snapshot.screen == Screen.ONBOARDING
                                    and str(curr_snapshot.onboarding_step or "").strip().lower() in ("prefs", "voice_guide")
                                )
                                fallback_ratio_min = float(theme.get("refresh_diff_fallback_min_ratio", 0.10) or 0.10)
                                if skip_onboarding_diff_fallback:
                                    if refresh_debug:
                                        print(
                                            f"[refresh] DIFF_FALLBACK_SKIP screen={curr_snapshot.screen.value} "
                                            f"step={curr_snapshot.onboarding_step} reason=onboarding_compact_policy"
                                        )
                                elif diff_ratio >= fallback_ratio_min:
                                    dirty_rects.append(diff_box)
                                    dirty_reasons.append("diff_fallback")
                                elif refresh_debug:
                                    print(
                                        f"[refresh] DIFF_FALLBACK_SKIP screen={curr_snapshot.screen.value} "
                                        f"diff_ratio={diff_ratio:.4f} threshold={fallback_ratio_min:.4f}"
                                    )
                    else:
                        dirty_rects = [diff_box]
                        dirty_reasons = ["diff_only"]
                    dirty_rects, dirty_reasons = _prioritize_home_focus_dirty(
                        curr_snapshot.screen,
                        dirty_rects,
                        dirty_reasons,
                        width=epd.width,
                    )
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
                if not _partial_budget_enabled_with_theme(theme):
                    full_every = 0
                full_every_text = str(full_every) if int(full_every) > 0 else "off"
                full_clean_reason = refresh_runtime.full_clean_reason(now, full_refresh_every=full_every)
                force_full_clean = bool(full_clean_reason)
                screen_changed = pending_snapshot.screen != committed_snapshot.screen
                rotation_changed = pending_snapshot.rotation_deg != committed_snapshot.rotation_deg
                screen_force_clean = _screen_force_full_clean_with_theme(pending_snapshot.screen, theme)
                screen_change_partial = (
                    screen_changed
                    and _screen_change_partial_enabled_with_theme(
                        committed_snapshot.screen,
                        pending_snapshot.screen,
                        theme,
                    )
                )
                screen_change_force_partial = (
                    screen_changed
                    and screen_change_partial
                    and _screen_change_force_partial_with_theme(pending_snapshot.screen, theme)
                )
                font_size_changed = pending_snapshot.font_size != committed_snapshot.font_size
                force_flush = force_full_clean or screen_changed or rotation_changed or screen_force_clean

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
                                    f"full_every={full_every_text} mode={policy_mode} "
                                    f"dirty={','.join(pending_reasons) or '-'}"
                                )
                        elif screen_force_clean:
                            driver_mode = _blit_full_clean(epd, pending_frame)
                            refresh_runtime.mark_full_clean(now)
                            if refresh_debug:
                                print(
                                    f"[refresh] R3_FULL_CLEAN screen={pending_snapshot.screen.value} "
                                    f"reason=screen_policy_full_clean mode={policy_mode} "
                                    f"dirty={','.join(pending_reasons) or '-'}"
                                )
                        elif rotation_changed:
                            driver_mode = _blit_full(epd, pending_frame, driver_mode, fast=fast_full)
                            refresh_runtime.mark_fast_full(now)
                            if refresh_debug:
                                print(
                                    f"[refresh] R2_FAST_FULL screen={pending_snapshot.screen.value} "
                                    f"reason=rotation_changed mode={policy_mode} "
                                    f"fast={'on' if fast_full else 'off'}"
                                )
                        elif screen_changed and not screen_change_partial:
                            driver_mode = _blit_full(epd, pending_frame, driver_mode, fast=fast_full)
                            refresh_runtime.mark_fast_full(now)
                            if refresh_debug:
                                print(
                                    f"[refresh] R2_FAST_FULL screen={pending_snapshot.screen.value} "
                                    f"reason=screen_changed mode={policy_mode} "
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
                            pending_rects = list(refresh_runtime.pending_dirty_rects)
                            family_only = (
                                pending_snapshot.screen == Screen.HOME
                                and pending_reasons
                                and all(r in ("home.family_board_update", "diff_fallback") for r in pending_reasons)
                            )
                            compact_onboarding = _is_onboarding_compact_step(pending_snapshot)
                            partial_pad = 1 if (family_only or compact_onboarding) else 2
                            partial_max_rects = max(
                                1,
                                int(theme.get("refresh_partial_max_rects", 6) or 6),
                            )
                            if compact_onboarding:
                                partial_max_rects = max(
                                    partial_max_rects,
                                    int(theme.get("refresh_partial_max_rects_onboarding", 16) or 16),
                                )
                            aligned_rects = _prepare_partial_rects(
                                pending_rects,
                                width=epd.width,
                                height=epd.height,
                                pad=partial_pad,
                                max_rects=partial_max_rects,
                                merge_overflow=not compact_onboarding,
                            )
                            if compact_onboarding and len(aligned_rects) > 1:
                                merged_compact = merge_rects(aligned_rects, epd.width, epd.height)
                                if merged_compact is not None:
                                    aligned_rects = [merged_compact]
                            partial_enabled = _screen_partial_enabled_with_theme(pending_snapshot.screen, theme)
                            mode_limit = _screen_area_limit_with_theme(
                                pending_snapshot.screen,
                                policy_mode,
                                theme,
                            )
                            if pending_snapshot.screen == Screen.HOME and "home.family_board_update" in pending_reasons:
                                mode_limit = max(mode_limit, _home_family_area_limit_with_theme(theme))
                            if pending_snapshot.screen == Screen.HOME and any(
                                r in ("home.menu_overlay_focus", "home.menu_overlay_toggle") for r in pending_reasons
                            ):
                                mode_limit = max(mode_limit, _home_menu_overlay_area_limit_with_theme(theme))
                            max_area_ratio = (
                                max(rect_area_ratio(r, epd.width, epd.height) for r in aligned_rects)
                                if aligned_rects
                                else 1.0
                            )
                            total_area_ratio = (
                                min(
                                    1.0,
                                    sum(rect_area_ratio(r, epd.width, epd.height) for r in aligned_rects),
                                )
                                if aligned_rects
                                else 1.0
                            )
                            gate_area_ratio = _partial_gate_area_ratio(
                                aligned_rects,
                                width=epd.width,
                                height=epd.height,
                            )
                            allow_over_limit_partial = (
                                compact_onboarding
                                and bool(theme.get("refresh_onboarding_compact_force_partial", True))
                            )
                            calendar_force_partial = (
                                pending_snapshot.screen == Screen.CALENDAR
                                and any(r.startswith("calendar.") for r in pending_reasons)
                                and _calendar_force_partial_with_theme(theme)
                            )
                            allow_over_limit_partial = bool(allow_over_limit_partial or screen_change_force_partial)
                            allow_over_limit_partial = bool(allow_over_limit_partial or calendar_force_partial)
                            if (
                                supports_partial
                                and partial_enabled
                                and aligned_rects
                                and (gate_area_ratio <= mode_limit or allow_over_limit_partial)
                            ):
                                for rect in aligned_rects:
                                    driver_mode = _blit_partial(epd, pending_frame, rect, driver_mode)
                                refresh_runtime.mark_partial(now)
                                if refresh_debug:
                                    rect_text = ";".join(f"{x0},{y0},{x1},{y1}" for (x0, y0, x1, y1) in aligned_rects)
                                    print(
                                        f"[refresh] R1_PARTIAL_RECTS screen={pending_snapshot.screen.value} "
                                        f"count={len(aligned_rects)} rects={rect_text} "
                                        f"max_ratio={max_area_ratio:.3f} total_ratio={total_area_ratio:.3f} "
                                        f"gate_ratio={gate_area_ratio:.3f} "
                                        f"limit={mode_limit:.3f} partial_count={refresh_runtime.partial_count}/{full_every_text} "
                                        f"mode={policy_mode} force_compact_partial={allow_over_limit_partial} "
                                        f"dirty={','.join(pending_reasons) or '-'}"
                                    )
                            else:
                                driver_mode = _blit_full(epd, pending_frame, driver_mode, fast=fast_full)
                                refresh_runtime.mark_fast_full(now)
                                if refresh_debug:
                                    why = "partial_unsupported"
                                    if not partial_enabled:
                                        why = "partial_disabled_for_screen"
                                    elif not aligned_rects:
                                        why = "no_aligned_rect"
                                    elif gate_area_ratio > mode_limit:
                                        why = "area_over_limit"
                                    print(
                                        f"[refresh] R2_FAST_FULL screen={pending_snapshot.screen.value} reason={why} "
                                        f"max_ratio={max_area_ratio:.3f} total_ratio={total_area_ratio:.3f} "
                                        f"gate_ratio={gate_area_ratio:.3f} "
                                        f"limit={mode_limit:.3f} "
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
