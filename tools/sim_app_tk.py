import os
import sys
import json
import time
import threading
import logging
import shutil
import subprocess
import tempfile
import signal
import tkinter as tk
from tkinter import ttk
import re
from datetime import datetime

from PIL import Image, ImageTk

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from app.core.state import AppState, DashboardModel, Reminder, WeatherDay, CalendarEvent, MemoItem, Screen, WidgetMode
from app.core.reducer import (
    reduce,
    Rotate,
    Click,
    LongPress,
    RotateButton,
    Back,
    Tick,
    MemoDelta,
    apply_onboarding_voice_demo_result,
    apply_onboarding_voice_demo_error,
    open_landing_welcome,
)
from app.data.location import resolve_dashboard_location
from app.data.weather_api import resolve_weather_data
from app.render.panel import build_panel_theme, quantize_for_panel
from app.shared.env import load_repo_dotenv
from app.shared.fonts import FontBook
from app.shared.paths import find_repo_root
from app.ui.app import render_app, _draw_mic_icon, _normalize_mic_style
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

logging.basicConfig(level=logging.INFO)
_log = logging.getLogger("sim_voice")


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


def _safe_int(var, default):
    try:
        return int(var.get())
    except Exception:
        return int(default)


def _safe_float(var, default):
    try:
        return float(var.get())
    except Exception:
        return float(default)


def _debug_now_str():
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())


def _local_timezone_name():
    tz_env = str(os.environ.get("TZ") or "").strip()
    if tz_env:
        return tz_env
    try:
        tzinfo = datetime.now().astimezone().tzinfo
        key = str(getattr(tzinfo, "key", "") or "").strip()
        if key:
            return key
    except Exception:
        pass
    return "UTC"


def _debug_action_tool_args(action):
    tool = str(getattr(action, "tool", "") or "").strip()
    args = getattr(action, "args", None)
    if not isinstance(args, dict):
        args = {}
    return tool, dict(args)


def _debug_shopping_items(state):
    items = []
    for r in list(getattr(state.model, "reminders", []) or []):
        if str(getattr(r, "category", "") or "") == "fridge":
            continue
        items.append(str(getattr(r, "title", "") or ""))
    return items


def _debug_inventory_items(state):
    items = []
    for r in list(getattr(state.model, "reminders", []) or []):
        if str(getattr(r, "category", "") or "") != "fridge":
            continue
        items.append(
            {
                "title": str(getattr(r, "title", "") or ""),
                "right": str(getattr(r, "right", "") or ""),
            }
        )
    return items


def _debug_inventory_lookup(items, item_name):
    needle = str(item_name or "").strip().lower()
    if not needle:
        return None
    for row in items:
        title = str((row or {}).get("title") or "").lower()
        if needle and needle in title:
            return dict(row)
    return None


def _debug_snapshot_for_action(state, action):
    tool, args = _debug_action_tool_args(action)
    snap = {}
    if tool in ("shopping_add_item", "shopping_remove_item", "shopping_clear_all"):
        shopping_items = _debug_shopping_items(state)
        snap["shopping_list"] = {
            "count": len(shopping_items),
            "items": shopping_items[:12],
        }
    if tool in ("inventory_log_event", "inventory_set_expiry", "inventory_clear_all"):
        inventory_items = _debug_inventory_items(state)
        snap["inventory"] = {
            "count": len(inventory_items),
            "items": inventory_items[:10],
        }
        target_item = str(args.get("item_name") or "").strip()
        if target_item:
            snap["inventory_target"] = {
                "item_name": target_item,
                "row": _debug_inventory_lookup(inventory_items, target_item),
            }
    if tool in ("timer_set", "timer_add", "timer_pause", "timer_resume", "timer_stop"):
        snap["timer"] = {
            "mode": str(getattr(state.ui, "widget_mode", "")),
            "seconds": int(getattr(state.ui, "timer_seconds", 0) or 0),
            "running": bool(getattr(state.ui, "timer_running", False)),
        }
    if tool in ("memo_add", "memo_delete", "memo_update", "memo_clear_all"):
        memos = list(getattr(state.model, "memos", []) or [])
        top = []
        for m in memos[:3]:
            top.append(
                {
                    "author": str(getattr(m, "author", "") or ""),
                    "text": str(getattr(m, "text", "") or ""),
                }
            )
        snap["memos"] = {"count": len(memos), "top": top}
    if not snap:
        # Generic fallback so debug still prints useful state for no_action/unknown.
        snap["shopping_list"] = {"count": len(_debug_shopping_items(state)), "items": _debug_shopping_items(state)[:12]}
        snap["inventory"] = {"count": len(_debug_inventory_items(state)), "items": _debug_inventory_items(state)[:10]}
    return snap


def _debug_fmt_inline_list(items):
    vals = list(items or [])
    rendered = []
    for v in vals:
        if isinstance(v, dict):
            title = str(v.get("title") or "")
            right = str(v.get("right") or "")
            rendered.append(f"{title} ({right})" if right else title)
        else:
            rendered.append(str(v))
    return "[" + ", ".join(rendered) + "]"


def _debug_snapshot_lines(label, snap):
    lines = [f"{label}:"]
    if not isinstance(snap, dict):
        lines.append("  <none>")
        return lines
    if "shopping_list" in snap:
        block = dict(snap.get("shopping_list") or {})
        lines.append(f"  shopping_list.count = {int(block.get('count', 0) or 0)}")
        lines.append(f"  shopping_list.items = {_debug_fmt_inline_list(block.get('items') or [])}")
    if "inventory" in snap:
        block = dict(snap.get("inventory") or {})
        lines.append(f"  inventory.count = {int(block.get('count', 0) or 0)}")
        lines.append(f"  inventory.items = {_debug_fmt_inline_list(block.get('items') or [])}")
    if "inventory_target" in snap:
        block = dict(snap.get("inventory_target") or {})
        target = str(block.get("item_name") or "")
        row = block.get("row")
        if isinstance(row, dict):
            lines.append(f"  inventory.target[{target}] = {row.get('title', '')} ({row.get('right', '')})")
        else:
            lines.append(f"  inventory.target[{target}] = <none>")
    if "timer" in snap:
        block = dict(snap.get("timer") or {})
        lines.append(
            "  timer = {mode="
            + str(block.get("mode") or "")
            + f", seconds={int(block.get('seconds', 0) or 0)}, running={bool(block.get('running', False))}"
            + "}"
        )
    if "memos" in snap:
        block = dict(snap.get("memos") or {})
        lines.append(f"  memos.count = {int(block.get('count', 0) or 0)}")
        lines.append(f"  memos.top = {_debug_fmt_inline_list(block.get('top') or [])}")
    return lines


def _debug_diff_lines(before, after, *, action_tool="", decision="", pending_note=""):
    if decision == "confirm_required":
        return [f"  none ({pending_note or 'pending physical confirm'})"]

    lines = []
    if "shopping_list" in before or "shopping_list" in after:
        b = dict(before.get("shopping_list") or {})
        a = dict(after.get("shopping_list") or {})
        b_items = list(b.get("items") or [])
        a_items = list(a.get("items") or [])
        removed = [x for x in b_items if x not in a_items]
        added = [x for x in a_items if x not in b_items]
        if removed:
            lines.append(f"  shopping_list.removed = {removed}")
        if added:
            lines.append(f"  shopping_list.added = {added}")
    if "inventory" in before or "inventory" in after:
        b = dict(before.get("inventory") or {})
        a = dict(after.get("inventory") or {})
        b_rows = list(b.get("items") or [])
        a_rows = list(a.get("items") or [])
        b_titles = [str((x or {}).get("title") if isinstance(x, dict) else x) for x in b_rows]
        a_titles = [str((x or {}).get("title") if isinstance(x, dict) else x) for x in a_rows]
        removed = [x for x in b_titles if x not in a_titles]
        added = [x for x in a_titles if x not in b_titles]
        if removed:
            lines.append(f"  inventory.removed = {removed}")
        if added:
            lines.append(f"  inventory.added = {added}")
        b_map = {}
        a_map = {}
        for row in b_rows:
            if isinstance(row, dict):
                b_map[str(row.get("title") or "")] = str(row.get("right") or "")
        for row in a_rows:
            if isinstance(row, dict):
                a_map[str(row.get("title") or "")] = str(row.get("right") or "")
        for title in sorted(set(b_map.keys()) & set(a_map.keys())):
            if b_map.get(title) != a_map.get(title):
                lines.append(f'  inventory.badge_changed = "{title}": "{b_map.get(title)}" -> "{a_map.get(title)}"')
    if "timer" in before or "timer" in after:
        b = dict(before.get("timer") or {})
        a = dict(after.get("timer") or {})
        if b != a:
            lines.append(f"  timer = {b} -> {a}")
    if "memos" in before or "memos" in after:
        b = dict(before.get("memos") or {})
        a = dict(after.get("memos") or {})
        if b.get("count") != a.get("count"):
            lines.append(f"  memos.count = {b.get('count', 0)} -> {a.get('count', 0)}")
        b_top = list(b.get("top") or [])
        a_top = list(a.get("top") or [])
        if b_top != a_top:
            lines.append(f"  memos.top = {b_top} -> {a_top}")
    if not lines:
        lines.append("  none")
    return lines


def _debug_decision_from_result(action_tool, result):
    status = str(getattr(result, "status", "") or "").strip().lower()
    changed = bool(getattr(result, "changed", False))
    if status == "confirm":
        return "confirm_required"
    if status == "error":
        return "error"
    if str(action_tool or "") == "no_action":
        return "no_action"
    if changed:
        return "executed"
    return "skipped"


def _debug_log_voice_apply_block(*, request_id, heard, action_text, action_tool, result, before_snap, after_snap):
    decision = _debug_decision_from_result(action_tool, result)
    lines = [
        f"[{_debug_now_str()}] VOICE_APPLY",
        f"request_id: {request_id or '<unknown>'}",
        f"heard: {heard or '-'}",
        f"action: {action_text or '-'}",
        f"decision: {decision}",
        f"result: {str(getattr(result, 'message', '') or '')}",
        "",
    ]
    lines.extend(_debug_snapshot_lines("before", before_snap))
    lines.append("")
    lines.extend(_debug_snapshot_lines("after", after_snap))
    lines.append("")
    lines.append("diff:")
    lines.extend(
        _debug_diff_lines(
            before_snap,
            after_snap,
            action_tool=action_tool,
            decision=decision,
            pending_note="pending physical confirm",
        )
    )
    _log.info("\n%s", "\n".join(lines))


def _debug_log_voice_confirm_block(*, source, pending_action, result, before_snap, after_snap):
    decision = _debug_decision_from_result("confirm", result)
    lines = [
        f"[{_debug_now_str()}] VOICE_CONFIRM",
        f"source: {source}",
        f"pending_action: {pending_action}",
        f"decision: {decision}",
        f"result: {str(getattr(result, 'message', '') or '')}",
        "",
    ]
    lines.extend(_debug_snapshot_lines("before", before_snap))
    lines.append("")
    lines.extend(_debug_snapshot_lines("after", after_snap))
    lines.append("")
    lines.append("diff:")
    lines.extend(_debug_diff_lines(before_snap, after_snap, decision=decision))
    _log.info("\n%s", "\n".join(lines))


def load_theme(path):
    if not os.path.exists(path):
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


def build_fonts(repo_root):
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


def _parse_optional_humidity(raw):
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


def _parse_optional_number(raw):
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


def load_model(repo_root):
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
        CalendarEvent("e0", "Dinner with Alex", "Fri 7:00 PM"),
        CalendarEvent("e1", "Flight to NYC", "Sat 9:20 AM"),
        CalendarEvent("e2", "Gym", "Sun 8:00 AM"),
        CalendarEvent("e3", "Team sync", "Mon 10:00 AM"),
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


class Simulator(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("E-Ink Dashboard Simulator")
        self.geometry("1420x900")

        self.repo_root = find_repo_root(os.path.dirname(__file__))
        self.theme_path = os.path.join(self.repo_root, "ui_tuner_theme.json")
        self.theme = load_theme(self.theme_path)
        self.fonts = build_fonts(self.repo_root)
        self.state = AppState(model=load_model(self.repo_root))
        self.state.ui.rotation_deg = self._rotation_value(self.theme.get("rotation_deg", 0))

        self.preview_mode = tk.StringVar(value="Panel")
        self.display_mode = tk.StringVar(value=str(self.theme.get("preview_display_mode", "Fit-Board")))
        self.panel_threshold = tk.IntVar(value=int(self.theme.get("panel_threshold", 168)))
        self.panel_muted = tk.IntVar(value=int(self.theme.get("panel_muted", 150)))
        self.panel_gamma = tk.DoubleVar(value=float(self.theme.get("panel_gamma", 1.0)))
        self.panel_dither = tk.BooleanVar(value=bool(self.theme.get("panel_dither", False)))
        self.home_variant = tk.StringVar(
            value=str(self.theme.get("home_variant", "kitchen_portrait")).strip().lower() or "kitchen_portrait"
        )
        self.badge_style = tk.StringVar(value=str(self.theme.get("b_badge_style", "text")))
        self.rotation_var = tk.StringVar(value=self._rotation_label(int(self.state.ui.rotation_deg or 0)))
        self._rotation_syncing = False
        self.voice_mic_mode = tk.StringVar(value=str(self.theme.get("voice_zone_mic_mode", "tabler_state")))
        self.voice_mic_style = tk.StringVar(value=str(self.theme.get("voice_zone_mic_style", "tabler_outline")))
        self.voice_api_url = tk.StringVar(value=os.environ.get("VOICE_SIM_API_URL", os.environ.get("VOICE_API_URL", "")))
        self.voice_locale = str(os.environ.get("VOICE_LOCALE", "en-US") or "en-US").strip() or "en-US"
        self.voice_timeout_s = tk.DoubleVar(value=float(os.environ.get("VOICE_TIMEOUT_S", "12")))
        self.voice_audio_max_sec = tk.IntVar(value=max(1, int(os.environ.get("VOICE_MAX_SEC", "6"))))
        self.voice_audio_device = tk.StringVar(value=os.environ.get("VOICE_AUDIO_DEVICE", "default"))
        self.voice_busy = False
        self.voice_recording = False
        self.voice_recording_proc = None
        self.voice_recording_path = ""
        self.voice_recording_started_at = 0.0
        self.voice_recording_auto_stop_id = None
        self.voice_request_api_url = ""
        self.voice_request_timeout_s = 12.0
        self._space_pressed = False
        self._space_release_job = None
        self.audio_recorder = self._detect_audio_recorder()
        self.ffmpeg_audio_devices = self._list_ffmpeg_audio_devices() if self.audio_recorder == "ffmpeg" else []
        ffmpeg_input_env = os.environ.get("VOICE_FFMPEG_INPUT", "").strip()
        default_ffmpeg_input = ffmpeg_input_env if ffmpeg_input_env else self._detect_ffmpeg_input_default()
        self.voice_ffmpeg_input = tk.StringVar(value=default_ffmpeg_input)
        self.voice_ffmpeg_device_label = tk.StringVar(value=self._label_for_ffmpeg_input(default_ffmpeg_input))
        self.last_heard = ""
        self.last_tool = ""

        self.controls = ttk.Frame(self)
        self.controls.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 6))
        ttk.Label(self.controls, text="Preview").grid(row=0, column=0, padx=(0, 6), sticky="w")
        ttk.Combobox(
            self.controls,
            textvariable=self.preview_mode,
            values=("Color", "Panel", "Split"),
            state="readonly",
            width=10,
        ).grid(row=0, column=1, padx=(0, 12), sticky="w")
        ttk.Label(self.controls, text="Home").grid(row=0, column=2, padx=(0, 6), sticky="w")
        ttk.Combobox(
            self.controls,
            textvariable=self.home_variant,
            values=("kitchen_portrait", "kitchen", "classic"),
            state="readonly",
            width=16,
        ).grid(row=0, column=3, padx=(0, 12), sticky="w")
        ttk.Label(self.controls, text="Rotation").grid(row=0, column=4, padx=(0, 6), sticky="w")
        ttk.Combobox(
            self.controls,
            textvariable=self.rotation_var,
            values=("0°", "90°", "180°", "270°"),
            state="readonly",
            width=7,
        ).grid(row=0, column=5, padx=(0, 6), sticky="w")
        ttk.Button(self.controls, text="Rotate", command=self._rotate_ui).grid(row=0, column=6, padx=(0, 12), sticky="w")
        ttk.Label(self.controls, text="Threshold").grid(row=0, column=7, padx=(0, 6), sticky="w")
        ttk.Spinbox(self.controls, from_=0, to=255, textvariable=self.panel_threshold, width=6).grid(row=0, column=8, padx=(0, 10), sticky="w")
        ttk.Label(self.controls, text="Muted").grid(row=0, column=9, padx=(0, 6), sticky="w")
        ttk.Spinbox(self.controls, from_=0, to=255, textvariable=self.panel_muted, width=6).grid(row=0, column=10, padx=(0, 10), sticky="w")
        ttk.Label(self.controls, text="Gamma").grid(row=0, column=11, padx=(0, 6), sticky="w")
        ttk.Spinbox(self.controls, from_=0.1, to=4.0, increment=0.05, textvariable=self.panel_gamma, width=6).grid(row=0, column=12, padx=(0, 10), sticky="w")
        ttk.Checkbutton(self.controls, text="Dither", variable=self.panel_dither, command=self._render).grid(row=0, column=13, sticky="w")
        ttk.Label(self.controls, text="Badge").grid(row=0, column=14, padx=(14, 6), sticky="w")
        ttk.Combobox(
            self.controls,
            textvariable=self.badge_style,
            values=("text", "text_focus_invert", "outline", "invert", "focus_invert"),
            state="readonly",
            width=16,
        ).grid(row=0, column=15, padx=(0, 6), sticky="w")
        ttk.Label(self.controls, text="Mic Style").grid(row=0, column=16, padx=(10, 6), sticky="w")
        ttk.Combobox(
            self.controls,
            textvariable=self.voice_mic_style,
            values=(
                "heroicons_solid",
                "heroicons_outline",
                "tabler_outline",
                "tabler_half",
                "tabler_filled",
                "bootstrap_outline",
                "bootstrap_fill",
            ),
            state="readonly",
            width=16,
        ).grid(row=0, column=17, padx=(0, 6), sticky="w")
        ttk.Label(self.controls, text="Mic Mode").grid(row=0, column=18, padx=(8, 6), sticky="w")
        ttk.Combobox(
            self.controls,
            textvariable=self.voice_mic_mode,
            values=("tabler_state", "manual"),
            state="readonly",
            width=12,
        ).grid(row=0, column=19, padx=(0, 6), sticky="w")
        ttk.Label(self.controls, text="Voice API").grid(row=1, column=0, padx=(0, 6), pady=(8, 0), sticky="w")
        ttk.Entry(self.controls, textvariable=self.voice_api_url, width=42).grid(row=1, column=1, columnspan=5, pady=(8, 0), sticky="ew")
        ttk.Label(self.controls, text="Max").grid(row=1, column=6, padx=(6, 4), pady=(8, 0), sticky="w")
        ttk.Spinbox(self.controls, from_=1, to=20, textvariable=self.voice_audio_max_sec, width=4).grid(row=1, column=7, pady=(8, 0), sticky="w")
        ttk.Label(self.controls, text="Timeout").grid(row=1, column=8, padx=(10, 6), pady=(8, 0), sticky="w")
        ttk.Spinbox(self.controls, from_=1.0, to=60.0, increment=0.5, textvariable=self.voice_timeout_s, width=6).grid(row=1, column=9, pady=(8, 0), sticky="w")
        ttk.Button(self.controls, text="Record/Stop", command=self._toggle_record_button).grid(row=1, column=10, pady=(8, 0), sticky="w")
        ttk.Label(self.controls, text="Display").grid(row=1, column=11, padx=(12, 6), pady=(8, 0), sticky="w")
        ttk.Combobox(
            self.controls,
            textvariable=self.display_mode,
            values=("Fit-Board", "1:1"),
            state="readonly",
            width=10,
        ).grid(row=1, column=12, pady=(8, 0), sticky="w")
        ttk.Button(
            self.controls,
            text="Show Landing",
            command=self._start_onboarding_from_landing,
        ).grid(row=1, column=13, padx=(10, 0), pady=(8, 0), sticky="w")
        ttk.Label(self.controls, text="Mic Input").grid(row=2, column=0, padx=(0, 6), pady=(8, 0), sticky="w")
        self.mic_combo = ttk.Combobox(
            self.controls,
            textvariable=self.voice_ffmpeg_device_label,
            values=self._ffmpeg_device_labels(),
            state="readonly",
            width=30,
        )
        self.mic_combo.grid(row=2, column=1, columnspan=3, padx=(0, 8), pady=(8, 0), sticky="w")
        self.mic_combo.bind("<<ComboboxSelected>>", self._on_mic_selected)
        ttk.Button(self.controls, text="Refresh Mic", command=self._refresh_ffmpeg_devices).grid(row=2, column=4, pady=(8, 0), sticky="w")
        ttk.Button(
            self.controls,
            text="Restart Landing",
            command=self._start_onboarding_from_landing,
        ).grid(row=2, column=5, padx=(8, 0), pady=(8, 0), sticky="w")

        self.preview = ttk.Label(self)
        self.preview.grid(row=1, column=0, sticky="nsew", padx=10, pady=10)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        self.status = ttk.Label(self, text="", anchor="w")
        self.status.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 4))

        help_text = (
            "Keys: \n"
            "  ←/→ = Rotate (move focus / auto page)\n"
            "  Enter = Click (open detail / toggle task / select menu)\n"
            "  R = Rotate screen (+90°)\n"
            "  S = Open settings\n"
            "  T = Open timer (home only)\n"
            "  O = Restart onboarding from landing\n"
            "  G = Open welcome landing\n"
            "  Hold Space = Record, Release Space = Send to Voice API\n"
            "  B / Esc / Backspace = Back (dashboard -> menu, detail/menu -> dashboard)\n"
            "  ↑/↓ = Memo (when left panel focused)\n"
            "  Q = Quit"
        )
        self.help = ttk.Label(self, text=help_text, justify="left", anchor="w")
        self.help.grid(row=3, column=0, sticky="ew", padx=10, pady=(0, 10))

        self.bind("<Left>", lambda _e: self._dispatch(Rotate(-1)))
        self.bind("<Right>", lambda _e: self._dispatch(Rotate(+1)))
        self.bind("<Up>", lambda _e: self._dispatch(MemoDelta(-1)))
        self.bind("<Down>", lambda _e: self._dispatch(MemoDelta(+1)))
        self.bind("r", lambda _e: self._dispatch(RotateButton()))
        self.bind("R", lambda _e: self._dispatch(RotateButton()))
        self.bind("s", lambda _e: self._open_settings())
        self.bind("S", lambda _e: self._open_settings())
        self.bind("t", lambda _e: self._open_timer())
        self.bind("T", lambda _e: self._open_timer())
        self.bind("o", lambda _e: self._start_onboarding_from_landing())
        self.bind("O", lambda _e: self._start_onboarding_from_landing())
        self.bind("g", lambda _e: self._start_onboarding_from_landing())
        self.bind("G", lambda _e: self._start_onboarding_from_landing())
        self.bind_all("<KeyPress-Return>", self._on_enter_press)
        self.bind_all("<KeyPress-KP_Enter>", self._on_enter_press)
        self.bind("b", lambda _e: self._dispatch(Back()))
        self.bind("B", lambda _e: self._dispatch(Back()))
        self.bind("<Escape>", lambda _e: self._dispatch(Back()))
        self.bind("<BackSpace>", lambda _e: self._dispatch(Back()))
        self.bind("q", lambda _e: self.destroy())
        # Global hotkeys so hold/release works even when focus is on control widgets.
        self.bind_all("<KeyPress-space>", self._on_space_press)
        self.bind_all("<KeyRelease-space>", self._on_space_release)

        for v in (
            self.preview_mode,
            self.display_mode,
            self.home_variant,
            self.panel_threshold,
            self.panel_muted,
            self.panel_gamma,
            self.badge_style,
            self.voice_mic_mode,
            self.voice_mic_style,
        ):
            v.trace_add("write", lambda *_: self._render())
        self.rotation_var.trace_add("write", lambda *_: self._on_rotation_selected())

        self._last_tick_render_sig = None
        self.after(100, self._tick)
        self._render()

    @staticmethod
    def _rotation_label(raw: int) -> str:
        try:
            deg = int(raw or 0)
        except Exception:
            deg = 0
        deg = (((deg % 360) + 45) // 90 * 90) % 360
        return f"{deg}\N{DEGREE SIGN}"

    @staticmethod
    def _rotation_value(raw) -> int:
        text = str(raw or "").strip().replace("°", "")
        try:
            val = int(text)
        except Exception:
            val = 0
        val = (((val % 360) + 45) // 90 * 90) % 360
        return val

    @staticmethod
    def _viewer_oriented_image(img, rotation_deg: int):
        rot = (((int(rotation_deg or 0) % 360) + 45) // 90 * 90) % 360
        transpose = getattr(Image, "Transpose", None)
        rot90 = transpose.ROTATE_90 if transpose is not None else Image.ROTATE_90
        rot270 = transpose.ROTATE_270 if transpose is not None else Image.ROTATE_270
        # Simulator ergonomics:
        # Keep portrait rotations upright so developers don't need to tilt their head.
        if rot == 90:
            return img.transpose(rot270)
        if rot == 270:
            return img.transpose(rot90)
        return img

    @staticmethod
    def _fit_to_box(img, max_w: int, max_h: int):
        if max_w <= 0 or max_h <= 0:
            return img, 1.0
        iw, ih = img.size
        if iw <= 0 or ih <= 0:
            return img, 1.0
        scale = min(float(max_w) / float(iw), float(max_h) / float(ih), 1.0)
        if scale >= 0.999:
            return img, 1.0
        new_w = max(1, int(round(iw * scale)))
        new_h = max(1, int(round(ih * scale)))
        resampling = getattr(Image, "Resampling", None)
        lanczos = resampling.LANCZOS if resampling is not None else Image.LANCZOS
        return img.resize((new_w, new_h), resample=lanczos), float(scale)

    def _sync_rotation_control(self) -> None:
        target = self._rotation_label(int(self.state.ui.rotation_deg or 0))
        if str(self.rotation_var.get() or "") == target:
            return
        self._rotation_syncing = True
        try:
            self.rotation_var.set(target)
        finally:
            self._rotation_syncing = False

    def _tick(self):
        before_sig = self._tick_render_sig()
        expire_pending_voice_confirmation(self.state)
        self.state = reduce(self.state, Tick(), theme=self.theme)
        after_sig = self._tick_render_sig()
        if after_sig != before_sig or after_sig != self._last_tick_render_sig:
            self._render()
            self._last_tick_render_sig = after_sig
        self.after(100, self._tick)

    def _tick_render_sig(self):
        ui = self.state.ui
        return (
            ui.screen.value,
            bool(ui.setup_completed),
            bool(ui.landing_rotate_seen),
            bool(ui.landing_confirm_seen),
            int(ui.landing_voice_demo_index or 0),
            int(ui.landing_voice_demo_cycles or 0),
            str(ui.landing_status or ""),
            str(ui.onboarding_step or ""),
            int(ui.onboarding_focus_index or 0),
            int(ui.onboarding_qr_focus_index or 0),
            int(ui.onboarding_prefs_focus_index or 0),
            int(ui.onboarding_voice_guide_focus_index or 0),
            str(ui.onboarding_status or ""),
            str(ui.onboarding_voice_demo_heard or ""),
            bool(ui.onboarding_voice_demo_attempted),
            str(ui.voice_locale or ""),
            int(ui.focused_index or 0),
            int(ui.page or 0),
            bool(ui.idle),
            str(getattr(ui.widget_mode, "value", ui.widget_mode)),
            int(ui.timer_seconds or 0),
            bool(ui.timer_running),
            bool(ui.voice_active),
            str(ui.voice_phase or ""),
            str(ui.voice_message or ""),
            str(ui.voice_confirm_tool or ""),
            bool(ui.pending_reorder),
            int(ui.reminders_version or 0),
            int(ui.memo_index or 0),
            int(ui.weather_day_index or 0),
            bool(self.voice_busy),
            bool(self.voice_recording),
        )

    def _dispatch(self, ev):
        if isinstance(ev, Click):
            pending_tool = str(self.state.ui.voice_confirm_tool or "").strip()
            if pending_tool:
                _log.info("voice_confirm input=click pending_tool=%s", pending_tool)
            before_snap = None
            if pending_tool:
                pending_action_for_debug = type("PendingAction", (), {"tool": pending_tool, "args": {}})()
                before_snap = _debug_snapshot_for_action(self.state, pending_action_for_debug)
            confirmed = confirm_pending_voice_action(self.state)
            if confirmed is not None:
                _log.info(
                    "voice_confirm applied tool=%s status=%s changed=%s message=%s",
                    pending_tool or "-",
                    confirmed.status,
                    bool(confirmed.changed),
                    str(confirmed.message or ""),
                )
                if before_snap is not None:
                    pending_action_for_debug = type("PendingAction", (), {"tool": pending_tool, "args": {}})()
                    after_snap = _debug_snapshot_for_action(self.state, pending_action_for_debug)
                    _debug_log_voice_confirm_block(
                        source="physical_click (simulator Enter)",
                        pending_action=f"{pending_tool or 'confirm'}(confirm)",
                        result=confirmed,
                        before_snap=before_snap,
                        after_snap=after_snap,
                    )
                msg = (
                    "Heard: [physical confirm]\n"
                    f"Action: {pending_tool or 'confirm'}(confirm)\n"
                    f"Result: {confirmed.message}"
                )
                self._set_voice_overlay(confirmed.status, msg, hold_s=4.0)
                self._render()
                return
        self.state = reduce(self.state, ev, theme=self.theme)
        self._render()

    def _rotate_ui(self):
        self._dispatch(RotateButton())
        return "break"

    def _on_rotation_selected(self):
        if self._rotation_syncing:
            return
        target = self._rotation_value(self.rotation_var.get())
        if int(self.state.ui.rotation_deg or 0) == target:
            return
        self.state.ui.rotation_deg = target
        self._render()

    def _open_settings(self):
        self.state.ui.screen = Screen.SETTINGS
        self._render()

    def _open_timer(self):
        if self.state.ui.screen != Screen.HOME:
            return
        self.state.ui.widget_mode = WidgetMode.TIMER
        if int(self.state.ui.timer_seconds or 0) <= 0:
            try:
                default_s = int(self.theme.get("timer_default_s", 5 * 60) or (5 * 60))
            except Exception:
                default_s = 5 * 60
            self.state.ui.timer_seconds = max(1, default_s)
        self.state.ui.timer_running = False
        self.state.ui.timer_last_tick_at = time.time()
        self.state.ui.timer_focused_index = 2
        self.state.ui.screen = Screen.TIMER
        self._render()

    def _start_onboarding_from_landing(self):
        open_landing_welcome(self.state)
        self._render()
        return "break"

    def _on_enter_press(self, _event=None):
        self._dispatch(Click())
        return "break"

    def _on_space_press(self, _event=None):
        if self._space_release_job is not None:
            try:
                self.after_cancel(self._space_release_job)
            except Exception:
                pass
            self._space_release_job = None
        if self._space_pressed:
            return "break"
        self._space_pressed = True
        self._start_voice_recording()
        return "break"

    def _on_space_release(self, _event=None):
        if not self._space_pressed:
            return "break"
        if self._space_release_job is not None:
            try:
                self.after_cancel(self._space_release_job)
            except Exception:
                pass
        # Debounce key-repeat synthetic release events while key is still held.
        self._space_release_job = self.after(120, self._finalize_space_release)
        return "break"

    def _finalize_space_release(self):
        self._space_release_job = None
        if not self._space_pressed:
            return
        self._space_pressed = False
        self._stop_voice_recording_and_send()

    def _toggle_record_button(self):
        if self.voice_recording:
            self._stop_voice_recording_and_send()
        else:
            self._start_voice_recording()
        return "break"

    def _detect_audio_recorder(self) -> str:
        if shutil.which("arecord"):
            return "arecord"
        if shutil.which("afrecord"):
            return "afrecord"
        if shutil.which("ffmpeg"):
            return "ffmpeg"
        return ""

    def _detect_ffmpeg_input_default(self) -> str:
        if sys.platform != "darwin":
            return "default"
        devices = self.ffmpeg_audio_devices or self._list_ffmpeg_audio_devices()
        if not devices:
            return ":0"
        # Prefer external/user microphone over built-in when available.
        for idx, name in devices:
            low = name.lower()
            if "microphone" in low and "macbook" not in low:
                return f":{idx}"
        return f":{devices[0][0]}"

    def _list_ffmpeg_audio_devices(self) -> list[tuple[int, str]]:
        if sys.platform != "darwin":
            return []
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            return []
        devices: list[tuple[int, str]] = []
        try:
            proc = subprocess.run(
                [ffmpeg, "-hide_banner", "-f", "avfoundation", "-list_devices", "true", "-i", ""],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            text = (proc.stderr or "") + "\n" + (proc.stdout or "")
            in_audio = False
            for line in text.splitlines():
                low = line.lower()
                if "avfoundation audio devices" in low:
                    in_audio = True
                    continue
                if "avfoundation video devices" in low:
                    in_audio = False
                if not in_audio:
                    continue
                m = re.search(r"\[(\d+)\]\s+(.+)$", line.strip())
                if m:
                    devices.append((int(m.group(1)), m.group(2).strip()))
        except Exception:
            return []
        return devices

    def _ffmpeg_device_labels(self) -> list[str]:
        if not self.ffmpeg_audio_devices:
            return [self.voice_ffmpeg_device_label.get() or ":0 (default)"]
        return [f":{idx} {name}" for idx, name in self.ffmpeg_audio_devices]

    def _label_for_ffmpeg_input(self, ffmpeg_input: str) -> str:
        txt = str(ffmpeg_input or "").strip()
        if not txt:
            return ":0 (default)"
        if txt.startswith(":"):
            try:
                idx = int(txt[1:])
                for d_idx, name in self.ffmpeg_audio_devices:
                    if d_idx == idx:
                        return f":{idx} {name}"
            except Exception:
                pass
        return txt

    def _on_mic_selected(self, _event=None):
        label = str(self.voice_ffmpeg_device_label.get() or "").strip()
        m = re.match(r"^:(\d+)\b", label)
        if m:
            self.voice_ffmpeg_input.set(f":{m.group(1)}")
        self._set_voice_overlay("done", f"Mic: {self.voice_ffmpeg_input.get()}", hold_s=1.6)
        self._render()

    def _refresh_ffmpeg_devices(self):
        self.ffmpeg_audio_devices = self._list_ffmpeg_audio_devices()
        self.mic_combo.configure(values=self._ffmpeg_device_labels())
        new_default = self._detect_ffmpeg_input_default()
        self.voice_ffmpeg_input.set(new_default)
        self.voice_ffmpeg_device_label.set(self._label_for_ffmpeg_input(new_default))
        self._set_voice_overlay("done", f"Mic input set to {new_default}", hold_s=1.8)
        self._render()

    def _build_record_command(self, *, audio_path: str, audio_device: str) -> list[str]:
        recorder = self.audio_recorder
        if recorder == "arecord":
            return [
                "arecord",
                "-D",
                str(audio_device or "default"),
                "-f",
                "S16_LE",
                "-r",
                "16000",
                "-c",
                "1",
                "-t",
                "wav",
                audio_path,
            ]
        if recorder == "afrecord":
            return [
                "afrecord",
                "-f",
                "WAVE",
                audio_path,
            ]
        if recorder == "ffmpeg":
            # macOS default path; VOICE_FFMPEG_INPUT can override device selector.
            if sys.platform == "darwin":
                ffmpeg_input = str(self.voice_ffmpeg_input.get() or ":0")
                return [
                    "ffmpeg",
                    "-nostdin",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-f",
                    "avfoundation",
                    "-i",
                    ffmpeg_input,
                    "-ac",
                    "1",
                    "-ar",
                    "16000",
                    "-acodec",
                    "pcm_s16le",
                    "-y",
                    audio_path,
                ]
            ffmpeg_input = str(audio_device or "default")
            return [
                "ffmpeg",
                "-nostdin",
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "alsa",
                "-i",
                ffmpeg_input,
                "-ac",
                "1",
                "-ar",
                "16000",
                "-acodec",
                "pcm_s16le",
                "-y",
                audio_path,
            ]
        return []

    def _stop_recording_process(self, proc: subprocess.Popen | None) -> bool:
        if not proc:
            return False
        if proc.poll() is not None:
            return True
        try:
            proc.send_signal(signal.SIGINT)
        except Exception:
            pass
        try:
            proc.wait(timeout=1.5)
            return True
        except Exception:
            pass
        try:
            proc.terminate()
            proc.wait(timeout=1.0)
            return True
        except Exception:
            pass
        try:
            proc.kill()
            proc.wait(timeout=0.5)
        except Exception:
            return False
        return True

    def _set_voice_overlay(self, phase: str, message: str = "", hold_s: float = 0.0) -> None:
        p = str(phase or "idle").strip().lower()
        if p == "idle":
            self.state.ui.voice_active = False
            self.state.ui.voice_phase = "idle"
            self.state.ui.voice_message = ""
            self.state.ui.voice_due_at = 0.0
            return

        self.state.ui.voice_active = True
        self.state.ui.voice_phase = p
        self.state.ui.voice_message = str(message or "")
        self.state.ui.voice_due_at = (time.time() + float(hold_s)) if hold_s > 0 else 0.0

    def _start_voice_recording(self):
        if self.voice_busy:
            return
        in_voice_guide_demo = (
            self.state.ui.screen == Screen.ONBOARDING
            and str(self.state.ui.onboarding_step or "").strip().lower() == "voice_guide"
        )
        if ((not bool(self.state.ui.setup_completed)) or self.state.ui.screen in (Screen.LANDING, Screen.ONBOARDING)) and (not in_voice_guide_demo):
            msg = "Voice is available after first setup."
            if self.state.ui.screen == Screen.LANDING:
                self.state.ui.landing_status = msg
            elif self.state.ui.screen == Screen.ONBOARDING:
                self.state.ui.onboarding_status = msg
            self._render()
            return

        api_url = str(self.voice_api_url.get() or "").strip()
        if not api_url:
            self._set_voice_overlay("error", "VOICE_API_URL is not set", hold_s=2.0)
            self._render()
            return

        if not self.audio_recorder:
            self._set_voice_overlay("error", "No recorder found (need arecord/afrecord/ffmpeg)", hold_s=2.4)
            self._render()
            return

        fd, audio_path = tempfile.mkstemp(prefix="sim_voice_", suffix=".wav", dir="/tmp")
        os.close(fd)
        audio_device = str(self.voice_audio_device.get() or "default")
        cmd = self._build_record_command(audio_path=audio_path, audio_device=audio_device)
        if not cmd:
            try:
                os.remove(audio_path)
            except Exception:
                pass
            self._set_voice_overlay("error", "Unsupported recorder config", hold_s=2.0)
            self._render()
            return

        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            try:
                os.remove(audio_path)
            except Exception:
                pass
            self._set_voice_overlay("error", f"Recorder start failed: {e}", hold_s=2.8)
            self._render()
            return

        self.voice_busy = True
        self.voice_recording = True
        self.voice_recording_proc = proc
        self.voice_recording_path = audio_path
        self.voice_recording_started_at = time.time()
        self.voice_request_api_url = api_url
        self.voice_request_timeout_s = max(1.0, float(_safe_float(self.voice_timeout_s, 12.0)))
        self.state.ui.idle = False
        self.state.ui.last_interaction_at = time.time()
        max_s = max(1, _safe_int(self.voice_audio_max_sec, 6))
        if self.voice_recording_auto_stop_id is not None:
            try:
                self.after_cancel(self.voice_recording_auto_stop_id)
            except Exception:
                pass
        self.voice_recording_auto_stop_id = self.after(max_s * 1000, self._auto_stop_recording)
        self._set_voice_overlay("recording", f"Recording... release to send (max {max_s}s)")
        self._render()

    def _auto_stop_recording(self):
        self.voice_recording_auto_stop_id = None
        if self.voice_recording:
            self._stop_voice_recording_and_send()

    def _stop_voice_recording_and_send(self):
        if not self.voice_recording:
            return

        if self.voice_recording_auto_stop_id is not None:
            try:
                self.after_cancel(self.voice_recording_auto_stop_id)
            except Exception:
                pass
            self.voice_recording_auto_stop_id = None

        proc = self.voice_recording_proc
        audio_path = str(self.voice_recording_path or "")
        elapsed_s = max(0.0, time.time() - float(self.voice_recording_started_at or 0.0))
        self.voice_recording = False
        self.voice_recording_proc = None
        self.voice_recording_path = ""
        self.voice_recording_started_at = 0.0

        stopped = self._stop_recording_process(proc)
        if not stopped:
            self._voice_error("Recording stop failed")
            self._voice_done()
            return

        if not os.path.exists(audio_path) or os.path.getsize(audio_path) <= 128:
            try:
                if audio_path and os.path.exists(audio_path):
                    os.remove(audio_path)
            except Exception:
                pass
            self._voice_error("No voice captured")
            self._voice_done()
            return

        self._set_voice_overlay("processing", f"Interpreting ({elapsed_s:.1f}s)")
        self._render()
        demo_only = (
            self.state.ui.screen == Screen.ONBOARDING
            and str(self.state.ui.onboarding_step or "").strip().lower() == "voice_guide"
        )
        threading.Thread(
            target=self._voice_worker,
            args=(self.voice_request_api_url, self.voice_request_timeout_s, audio_path, demo_only),
            daemon=True,
        ).start()

    def _trigger_voice_audio(self):
        # Keep legacy entrypoint for compatibility with older hooks.
        if self.voice_recording:
            self._stop_voice_recording_and_send()
        else:
            self._start_voice_recording()

    def _voice_worker(self, api_url: str, timeout_s: float, audio_path: str, demo_only: bool) -> None:
        try:
            locale = str(self.state.ui.voice_locale or "en-US")
            meta = build_request_meta(locale=locale, tz_name=_local_timezone_name())
            payload = interpret_audio_via_backend(
                api_url=api_url,
                audio_path=audio_path,
                meta=meta,
                timeout_s=timeout_s,
                board_context=build_board_context(self.state),
            )
            if isinstance(payload, dict):
                payload = dict(payload)
                payload["_debug_request_id"] = str(meta.request_id or "")
            if demo_only:
                self.after(0, lambda p=payload: self._apply_voice_demo_payload(p))
            else:
                self.after(0, lambda p=payload: self._apply_voice_payload(p))
        except VoiceClientError as e:
            self.after(0, lambda msg=str(e): self._voice_error(msg))
        except Exception as e:
            self.after(0, lambda msg=f"Sim voice failed: {e}": self._voice_error(msg))
        finally:
            try:
                os.remove(audio_path)
            except Exception:
                pass
            self.after(0, self._voice_done)

    def _apply_voice_demo_payload(self, payload: dict) -> None:
        transcript = ""
        if isinstance(payload, dict):
            transcript = str(payload.get("transcript") or "").strip()
        apply_onboarding_voice_demo_result(self.state, transcript)
        self.last_heard = transcript
        self.last_tool = "voice_demo"
        self._set_voice_overlay("idle")
        self._render()

    def _apply_voice_payload(self, payload: dict) -> None:
        transcript = ""
        request_id = ""
        if isinstance(payload, dict):
            transcript = str(payload.get("transcript") or "").strip()
            request_id = str(payload.get("_debug_request_id") or payload.get("request_id") or "").strip()
        plan = parse_voice_plan(payload)
        action = plan.actions[0] if list(plan.actions or []) else parse_voice_action(payload)
        before_snap = _debug_snapshot_for_action(self.state, action)
        result = apply_voice_plan(self.state, plan, transcript=transcript)
        after_snap = _debug_snapshot_for_action(self.state, action)
        self.last_heard = transcript
        self.last_tool = ",".join([str(a.tool or "") for a in list(plan.actions or [])[:3]]) or str(action.tool or "")
        heard = transcript if transcript else "-"
        action_desc = ", ".join([describe_voice_action(a) for a in list(plan.actions or [])[:4]]) or describe_voice_action(action)
        shown = (
            f"Heard: {heard}\n"
            f"Action: {action_desc}\n"
            f"Result: {result.message}"
        )
        _log.info(
            "voice_apply action=%s status=%s changed=%s result=%s transcript=%s",
            action_desc,
            result.status,
            bool(result.changed),
            str(result.message or ""),
            heard,
        )
        _debug_log_voice_apply_block(
            request_id=request_id,
            heard=heard,
            action_text=action_desc,
            action_tool=str(action.tool or ""),
            result=result,
            before_snap=before_snap,
            after_snap=after_snap,
        )
        hold_s = 4.0
        if str(result.status or "").strip().lower() == "confirm":
            remaining_confirm_s = max(0.0, float(self.state.ui.voice_confirm_due_at or 0.0) - time.time())
            hold_s = max(hold_s, remaining_confirm_s + 0.2)
        self._set_voice_overlay(result.status, shown, hold_s=hold_s)
        self._render()

    def _voice_error(self, msg: str) -> None:
        self.last_heard = ""
        self.last_tool = "error"
        in_voice_guide_demo = (
            self.state.ui.screen == Screen.ONBOARDING
            and str(self.state.ui.onboarding_step or "").strip().lower() == "voice_guide"
        )
        if in_voice_guide_demo:
            apply_onboarding_voice_demo_error(self.state, msg)
            self._set_voice_overlay("idle")
        else:
            self._set_voice_overlay("error", msg, hold_s=4.0)
        self._render()

    def _voice_done(self) -> None:
        self.voice_busy = False

    def _render(self):
        w, h = 800, 480
        self._sync_rotation_control()
        variant = str(self.home_variant.get() or "kitchen_portrait").strip().lower()
        if variant not in ("kitchen", "kitchen_portrait", "classic"):
            variant = "kitchen_portrait"
        self.theme["home_variant"] = variant
        badge_style = str(self.badge_style.get() or "text").strip().lower()
        if badge_style not in ("text", "text_focus_invert", "outline", "invert", "focus_invert"):
            badge_style = "text"
        self.theme["b_badge_style"] = badge_style
        mic_mode = str(self.voice_mic_mode.get() or "tabler_state").strip().lower()
        if mic_mode not in ("tabler_state", "manual"):
            mic_mode = "tabler_state"
        self.theme["voice_zone_mic_mode"] = mic_mode
        mic_style = _normalize_mic_style(str(self.voice_mic_style.get() or "tabler_outline"))
        self.theme["voice_zone_mic_style"] = mic_style

        bg = self.theme.get("bg", (229, 229, 229))
        color_img = Image.new("RGB", (w, h), bg if isinstance(bg, tuple) else (229, 229, 229))
        render_app(color_img, self.state, self.fonts, self.theme)

        muted = max(0, min(255, _safe_int(self.panel_muted, 150)))
        threshold = max(0, min(255, _safe_int(self.panel_threshold, 168)))
        gamma = max(0.1, min(4.0, _safe_float(self.panel_gamma, 1.0)))
        dither = bool(self.panel_dither.get())

        panel_theme = build_panel_theme(self.theme, muted_gray=muted)
        panel_rgb = Image.new("RGB", (w, h), panel_theme.get("bg", (255, 255, 255)))
        render_app(panel_rgb, self.state, self.fonts, panel_theme)
        panel_bw = quantize_for_panel(panel_rgb, threshold=threshold, gamma=gamma, dither=dither)
        sim_rot = self._rotation_value(self.state.ui.rotation_deg)

        mode = str(self.preview_mode.get() or "Panel")
        display_mode = str(self.display_mode.get() or "Fit-Board").strip()
        if display_mode not in ("Fit-Board", "1:1"):
            display_mode = "Fit-Board"
        self.theme["preview_display_mode"] = display_mode
        if mode == "Color":
            show_img = self._viewer_oriented_image(color_img, sim_rot)
        elif mode == "Panel":
            show_img = self._viewer_oriented_image(panel_bw.convert("RGB"), sim_rot)
        else:
            show_img = Image.new("RGB", (w * 2 + 12, h), (236, 236, 236))
            show_img.paste(color_img, (0, 0))
            show_img.paste(panel_bw.convert("RGB"), (w + 12, 0))

        raw_w, raw_h = show_img.size
        shown_scale = 1.0
        preview_w = int(self.preview.winfo_width() or 0)
        preview_h = int(self.preview.winfo_height() or 0)
        if display_mode == "Fit-Board" and mode in ("Color", "Panel"):
            if preview_w <= 1 or preview_h <= 1:
                self.update_idletasks()
                preview_w = int(self.preview.winfo_width() or 0)
                preview_h = int(self.preview.winfo_height() or 0)
            show_img, shown_scale = self._fit_to_box(show_img, preview_w, preview_h)

        self._photo = ImageTk.PhotoImage(show_img)
        self.preview.configure(image=self._photo)

        ui = self.state.ui
        font_ok = "YES" if not self.fonts.missing_font_paths() else "NO"
        recorder = self.audio_recorder or "none"
        voice_source = "backend" if str(self.voice_api_url.get() or "").strip() else "no_api"
        self.status.configure(
            text=(
                f"screen={ui.screen.value} focus={ui.focused_index} page={ui.page} idle={ui.idle} "
                f"pending_reorder={ui.pending_reorder} mode={mode} th={threshold} muted={muted} "
                f"gamma={gamma:.2f} dither={dither} badge_style={badge_style} "
                f"home_variant={variant} rotation={int(ui.rotation_deg or 0)} "
                f"display={display_mode} raw={raw_w}x{raw_h} shown={show_img.width}x{show_img.height} "
                f"scale={shown_scale:.3f} box={preview_w}x{preview_h} "
                f"mic_mode={mic_mode} mic_style={mic_style} "
                f"focus_style={self.theme.get('b_right_focus_style', 'row_box')} fonts_ok={font_ok} "
                f"voice={ui.voice_phase}:{voice_source} recorder={recorder} "
                f"last_tool={self.last_tool or '-'} heard={self.last_heard or '-'}"
            )
        )

if __name__ == "__main__":
    Simulator().mainloop()
