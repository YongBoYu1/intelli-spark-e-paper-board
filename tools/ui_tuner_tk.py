import json
import os
import sys
import time
import tkinter as tk
from tkinter import colorchooser, ttk

from PIL import Image, ImageTk

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from app.core.state import AppState, CalendarEvent, DashboardModel, MemoItem, Reminder, WeatherDay
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


def _rgb_to_hex(rgb):
    if isinstance(rgb, str):
        return rgb
    if isinstance(rgb, (list, tuple)) and len(rgb) == 3:
        return "#{:02X}{:02X}{:02X}".format(int(rgb[0]), int(rgb[1]), int(rgb[2]))
    return "#000000"


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


def save_theme(path, theme):
    out = dict(theme)
    for key in ("ink", "border", "card", "muted", "bg"):
        if isinstance(out.get(key), tuple):
            out[key] = list(out[key])
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)


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


def load_model(repo_root):
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
        location=str(d.get("location") or "New York"),
        battery=int(d.get("battery") or 84),
        reminders=reminders,
        weather=weather,
        calendar=cal,
        memos=memos,
    )


class ScrollableFrame(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self.canvas = tk.Canvas(self, highlightthickness=0)
        self.scroll = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.scroll.set)

        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.scroll.grid(row=0, column=1, sticky="ns")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        self.inner = ttk.Frame(self.canvas)
        self._window_id = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")

        self.inner.bind("<Configure>", self._on_inner_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)

    def _on_inner_configure(self, _event):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        self.canvas.itemconfigure(self._window_id, width=event.width)


class KitchenTuner(tk.Tk):
    FIELD_SPECS = [
        ("k_container_padding", "Container Padding", "int", 8, 64),
        ("k_left_column_width", "Left Column Width", "int", 320, 520),
        ("k_border_thin", "Border Thin", "int", 1, 4),
        ("k_border_thick", "Border Thick", "int", 2, 8),
        ("k_icon_stroke", "Icon Stroke", "int", 1, 4),
        ("k_weather_icon_size", "Weather Icon Size", "int", 30, 72),
        ("k_clock_size_rem", "Clock Size (rem)", "float", 8.0, 13.0),
        ("k_date_size_rem", "Date Size (rem)", "float", 0.8, 2.0),
        ("k_month_size_scale", "Month Size Scale", "float", 0.6, 1.1),
        ("k_clock_info_gap_px", "Clock->Info Gap", "int", 0, 24),
        ("k_weekday_month_gap_px", "Weekday->Month Gap", "int", 0, 12),
        ("k_header_rule_gap_px", "Header Rule Gap", "int", 6, 28),
        ("k_left_micro_size_px", "Left Micro Size", "int", 9, 16),
        ("k_left_micro_bold_size_px", "Left Micro Bold", "int", 10, 18),
        ("k_weather_desc_size_px", "Weather Desc Size", "int", 9, 16),
        ("k_weather_desc_gap_px", "Weather Desc Gap", "int", 0, 10),
        ("k_author_size_px", "Author Size", "int", 10, 18),
        ("k_author_inactive_gray", "Author Gray", "int", 60, 180),
        ("k_mood_quote_size_rem", "Quote Size (rem)", "float", 1.4, 2.5),
        ("k_mood_msg_size_rem", "Memo Size (rem)", "float", 1.2, 2.8),
        ("k_mood_msg_lh", "Memo Line Height", "float", 0.9, 1.6),
        ("k_mood_pad_top", "Header Top Pad", "int", 0, 24),
        ("k_clock_nudge_em", "Clock Nudge (em)", "float", -0.8, 0.4),
        ("k_clock_date_gap_rem", "Clock/Date Gap (rem)", "float", 0.0, 1.2),
        ("k_fridge_card_h", "Fridge Card Height", "int", 72, 120),
        ("k_fridge_card_gap", "Fridge Card Gap", "int", 6, 24),
        ("k_fridge_title_size_rem", "Fridge Title (rem)", "float", 0.8, 1.6),
        ("k_fridge_badge_size_rem", "Fridge Badge (rem)", "float", 0.45, 1.0),
        ("k_fridge_badge_px", "Badge Pad X", "int", 4, 14),
        ("k_fridge_badge_py", "Badge Pad Y", "int", 0, 6),
        ("k_shop_header_size_rem", "Shopping Header (rem)", "float", 0.55, 1.1),
        ("k_shop_item_size_rem", "Shopping Item (rem)", "float", 0.9, 1.8),
        ("k_shop_item_h", "Shopping Row Height", "int", 36, 68),
        ("k_shop_item_gap", "Shopping Row Gap", "int", 0, 12),
        ("k_kitchen_section_gap", "Section Gap", "int", 8, 44),
        ("k_kitchen_header_mb", "Header Bottom Gap", "int", 4, 28),
        ("k_inventory_header_size_px", "Inventory Header Size", "int", 10, 18),
        ("k_inventory_header_offset_y", "Inventory Header Y", "int", -2, 10),
    ]

    DEFAULTS = {
        "k_container_padding": 32,
        "k_left_column_width": 420,
        "k_border_thin": 2,
        "k_border_thick": 4,
        "k_icon_stroke": 2,
        "k_weather_icon_size": 48,
        "k_clock_size_rem": 10.0,
        "k_date_size_rem": 1.4,
        "k_month_size_scale": 0.82,
        "k_clock_info_gap_px": 8,
        "k_weekday_month_gap_px": 4,
        "k_header_rule_gap_px": 14,
        "k_left_micro_size_px": 12,
        "k_left_micro_bold_size_px": 13,
        "k_weather_desc_size_px": 13,
        "k_weather_desc_gap_px": 3,
        "k_author_size_px": 14,
        "k_author_inactive_gray": 88,
        "k_mood_quote_size_rem": 1.95,
        "k_mood_msg_size_rem": 2.0,
        "k_mood_msg_lh": 1.1,
        "k_mood_pad_top": 8,
        "k_clock_nudge_em": -0.2,
        "k_clock_date_gap_rem": 0.5,
        "k_fridge_card_h": 90,
        "k_fridge_card_gap": 12,
        "k_fridge_title_size_rem": 1.125,
        "k_fridge_badge_size_rem": 0.80,
        "k_fridge_badge_px": 9,
        "k_fridge_badge_py": 3,
        "k_shop_header_size_rem": 0.92,
        "k_shop_item_size_rem": 1.34,
        "k_shop_item_h": 50,
        "k_shop_item_gap": 0,
        "k_kitchen_section_gap": 24,
        "k_kitchen_header_mb": 12,
        "k_inventory_header_size_px": 13,
        "k_inventory_header_offset_y": 2,
        "panel_threshold": 168,
        "panel_muted": 150,
        "panel_gamma": 1.0,
        "panel_dither": False,
        "sim_preview_mode": "Panel",
    }

    def __init__(self):
        super().__init__()
        self.title("Kitchen UI Tuner (Current Render)")
        self.geometry("1420x900")
        self._suspend_render = True

        self.repo_root = find_repo_root(os.path.dirname(__file__))
        self.theme_path = os.path.join(self.repo_root, "ui_tuner_theme.json")
        self.base_theme = load_theme(self.theme_path)
        self.base_theme["home_variant"] = "kitchen"

        self.fonts = build_fonts(self.repo_root)
        self.state = AppState(model=load_model(self.repo_root))

        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        controls_container = ttk.Frame(self)
        controls_container.grid(row=0, column=0, sticky="nsew", padx=(10, 6), pady=10)
        controls_container.columnconfigure(0, weight=1)
        controls_container.rowconfigure(1, weight=1)

        preview_container = ttk.Frame(self)
        preview_container.grid(row=0, column=1, sticky="nsew", padx=(6, 10), pady=10)
        preview_container.columnconfigure(0, weight=1)
        preview_container.rowconfigure(0, weight=1)

        self.preview = ttk.Label(preview_container)
        self.preview.grid(row=0, column=0, sticky="nsew")
        self.preview_status = ttk.Label(preview_container, text="", anchor="w")
        self.preview_status.grid(row=1, column=0, sticky="ew", pady=(6, 0))

        toolbar = ttk.Frame(controls_container)
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ttk.Button(toolbar, text="Reload Theme", command=self._reload_theme).grid(row=0, column=0, padx=(0, 6))
        ttk.Button(toolbar, text="Save Theme", command=self._save_theme).grid(row=0, column=1, padx=(0, 6))
        ttk.Button(toolbar, text="Reset Defaults", command=self._reset_defaults).grid(row=0, column=2, padx=(0, 6))

        self.scrollable = ScrollableFrame(controls_container)
        self.scrollable.grid(row=1, column=0, sticky="nsew")

        self.vars = {}
        self.color_vars = {
            "ink": tk.StringVar(),
            "border": tk.StringVar(),
            "card": tk.StringVar(),
            "muted": tk.StringVar(),
            "bg": tk.StringVar(),
        }
        self.preview_mode_var = tk.StringVar(value=self.DEFAULTS["sim_preview_mode"])
        self.panel_threshold_var = tk.IntVar(value=int(self.DEFAULTS["panel_threshold"]))
        self.panel_muted_var = tk.IntVar(value=int(self.DEFAULTS["panel_muted"]))
        self.panel_gamma_var = tk.DoubleVar(value=float(self.DEFAULTS["panel_gamma"]))
        self.panel_dither_var = tk.BooleanVar(value=bool(self.DEFAULTS["panel_dither"]))

        self._build_controls(self.scrollable.inner)
        self._reload_theme()

    def _build_controls(self, parent):
        row = 0
        ttk.Label(parent, text="Colors", font=("TkDefaultFont", 11, "bold")).grid(row=row, column=0, sticky="w", pady=(0, 4))
        row += 1

        for k, label in [("ink", "Ink"), ("border", "Border"), ("card", "Card"), ("muted", "Muted"), ("bg", "Background")]:
            ttk.Label(parent, text=label, width=18).grid(row=row, column=0, sticky="w")
            ttk.Entry(parent, textvariable=self.color_vars[k], width=14).grid(row=row, column=1, sticky="w")
            ttk.Button(parent, text="Pick", command=lambda key=k: self._pick_color(key)).grid(row=row, column=2, sticky="w", padx=(6, 0))
            self.color_vars[k].trace_add("write", lambda *_: self._render())
            row += 1

        ttk.Separator(parent, orient="horizontal").grid(row=row, column=0, columnspan=4, sticky="ew", pady=8)
        row += 1

        ttk.Label(parent, text="View State", font=("TkDefaultFont", 11, "bold")).grid(row=row, column=0, sticky="w", pady=(0, 4))
        row += 1

        self.focus_var = tk.IntVar(value=0)
        self.idle_var = tk.BooleanVar(value=False)
        self.memo_var = tk.IntVar(value=0)

        ttk.Label(parent, text="Focus Index", width=18).grid(row=row, column=0, sticky="w")
        ttk.Scale(parent, from_=0, to=9, orient="horizontal", variable=self.focus_var, command=lambda _v: self._render()).grid(row=row, column=1, columnspan=2, sticky="ew")
        row += 1

        ttk.Checkbutton(parent, text="Idle", variable=self.idle_var, command=self._render).grid(row=row, column=0, columnspan=2, sticky="w")
        row += 1

        ttk.Label(parent, text="Memo Index", width=18).grid(row=row, column=0, sticky="w")
        ttk.Scale(parent, from_=0, to=6, orient="horizontal", variable=self.memo_var, command=lambda _v: self._render()).grid(row=row, column=1, columnspan=2, sticky="ew")
        row += 1

        ttk.Separator(parent, orient="horizontal").grid(row=row, column=0, columnspan=4, sticky="ew", pady=8)
        row += 1

        ttk.Label(parent, text="Panel Preview", font=("TkDefaultFont", 11, "bold")).grid(row=row, column=0, sticky="w", pady=(0, 4))
        row += 1

        ttk.Label(parent, text="Preview Mode", width=18).grid(row=row, column=0, sticky="w")
        ttk.Combobox(parent, textvariable=self.preview_mode_var, values=("Color", "Panel", "Split"), state="readonly", width=12).grid(row=row, column=1, sticky="w")
        self.preview_mode_var.trace_add("write", lambda *_: self._render())
        row += 1

        ttk.Label(parent, text="Panel Threshold", width=18).grid(row=row, column=0, sticky="w")
        ttk.Scale(parent, from_=0, to=255, orient="horizontal", variable=self.panel_threshold_var, command=lambda _v: self._render()).grid(row=row, column=1, sticky="ew")
        ttk.Spinbox(parent, from_=0, to=255, textvariable=self.panel_threshold_var, width=8).grid(row=row, column=2, sticky="w", padx=(6, 0))
        self.panel_threshold_var.trace_add("write", lambda *_: self._render())
        row += 1

        ttk.Label(parent, text="Panel Muted", width=18).grid(row=row, column=0, sticky="w")
        ttk.Scale(parent, from_=0, to=255, orient="horizontal", variable=self.panel_muted_var, command=lambda _v: self._render()).grid(row=row, column=1, sticky="ew")
        ttk.Spinbox(parent, from_=0, to=255, textvariable=self.panel_muted_var, width=8).grid(row=row, column=2, sticky="w", padx=(6, 0))
        self.panel_muted_var.trace_add("write", lambda *_: self._render())
        row += 1

        ttk.Label(parent, text="Panel Gamma", width=18).grid(row=row, column=0, sticky="w")
        ttk.Scale(parent, from_=0.1, to=4.0, orient="horizontal", variable=self.panel_gamma_var, command=lambda _v: self._render()).grid(row=row, column=1, sticky="ew")
        ttk.Spinbox(parent, from_=0.1, to=4.0, increment=0.05, textvariable=self.panel_gamma_var, width=8).grid(row=row, column=2, sticky="w", padx=(6, 0))
        self.panel_gamma_var.trace_add("write", lambda *_: self._render())
        row += 1

        ttk.Checkbutton(parent, text="Panel Dither", variable=self.panel_dither_var, command=self._render).grid(row=row, column=0, columnspan=2, sticky="w")
        row += 1

        ttk.Separator(parent, orient="horizontal").grid(row=row, column=0, columnspan=4, sticky="ew", pady=8)
        row += 1

        ttk.Label(parent, text="Kitchen Layout", font=("TkDefaultFont", 11, "bold")).grid(row=row, column=0, sticky="w", pady=(0, 4))
        row += 1

        for key, label, kind, lo, hi in self.FIELD_SPECS:
            ttk.Label(parent, text=label, width=18).grid(row=row, column=0, sticky="w")
            if kind == "int":
                var = tk.IntVar()
                self.vars[key] = var
                ttk.Scale(parent, from_=lo, to=hi, orient="horizontal", variable=var, command=lambda _v: self._render()).grid(row=row, column=1, sticky="ew")
                ttk.Spinbox(parent, from_=lo, to=hi, textvariable=var, width=8).grid(row=row, column=2, sticky="w", padx=(6, 0))
                var.trace_add("write", lambda *_: self._render())
            else:
                var = tk.DoubleVar()
                self.vars[key] = var
                ttk.Scale(parent, from_=lo, to=hi, orient="horizontal", variable=var, command=lambda _v: self._render()).grid(row=row, column=1, sticky="ew")
                ttk.Spinbox(parent, from_=lo, to=hi, increment=0.05, textvariable=var, width=8).grid(row=row, column=2, sticky="w", padx=(6, 0))
                var.trace_add("write", lambda *_: self._render())
            row += 1

        parent.columnconfigure(1, weight=1)

    def _pick_color(self, key):
        color = colorchooser.askcolor(color=self.color_vars[key].get())[1]
        if color:
            self.color_vars[key].set(color)

    def _reload_theme(self):
        self._suspend_render = True
        self.base_theme = load_theme(self.theme_path)
        self.base_theme["home_variant"] = "kitchen"

        for k in self.color_vars:
            self.color_vars[k].set(_rgb_to_hex(self.base_theme.get(k, (17, 17, 17))))

        for key, _label, kind, _lo, _hi in self.FIELD_SPECS:
            v = self.base_theme.get(key, self.DEFAULTS[key])
            if kind == "int":
                self.vars[key].set(int(round(float(v))))
            else:
                self.vars[key].set(float(v))

        self.preview_mode_var.set(str(self.base_theme.get("sim_preview_mode", self.DEFAULTS["sim_preview_mode"])))
        self.panel_threshold_var.set(int(self.base_theme.get("panel_threshold", self.DEFAULTS["panel_threshold"])))
        self.panel_muted_var.set(int(self.base_theme.get("panel_muted", self.DEFAULTS["panel_muted"])))
        self.panel_gamma_var.set(float(self.base_theme.get("panel_gamma", self.DEFAULTS["panel_gamma"])))
        self.panel_dither_var.set(bool(self.base_theme.get("panel_dither", self.DEFAULTS["panel_dither"])))

        self.focus_var.set(0)
        self.idle_var.set(False)
        self.memo_var.set(0)

        self._suspend_render = False
        self._render()

    def _reset_defaults(self):
        self._suspend_render = True

        self.color_vars["ink"].set("#111111")
        self.color_vars["border"].set("#111111")
        self.color_vars["card"].set("#FFFFFF")
        self.color_vars["muted"].set("#A0A0A0")
        self.color_vars["bg"].set("#E5E5E5")

        for key, _label, kind, _lo, _hi in self.FIELD_SPECS:
            if kind == "int":
                self.vars[key].set(int(self.DEFAULTS[key]))
            else:
                self.vars[key].set(float(self.DEFAULTS[key]))

        self.preview_mode_var.set(str(self.DEFAULTS["sim_preview_mode"]))
        self.panel_threshold_var.set(int(self.DEFAULTS["panel_threshold"]))
        self.panel_muted_var.set(int(self.DEFAULTS["panel_muted"]))
        self.panel_gamma_var.set(float(self.DEFAULTS["panel_gamma"]))
        self.panel_dither_var.set(bool(self.DEFAULTS["panel_dither"]))

        self._suspend_render = False
        self._render()

    def _build_theme(self):
        t = dict(self.base_theme)
        t["home_variant"] = "kitchen"

        for k, v in self.color_vars.items():
            rgb = _hex_to_rgb(v.get())
            if rgb is not None:
                t[k] = rgb

        for key, _label, kind, lo, hi in self.FIELD_SPECS:
            default = self.DEFAULTS[key]
            num = _safe_float(self.vars[key], default)
            num = max(float(lo), min(float(hi), num))
            if kind == "int":
                t[key] = int(round(num))
            else:
                t[key] = float(num)

        t["panel_threshold"] = max(0, min(255, _safe_int(self.panel_threshold_var, self.DEFAULTS["panel_threshold"])))
        t["panel_muted"] = max(0, min(255, _safe_int(self.panel_muted_var, self.DEFAULTS["panel_muted"])))
        t["panel_gamma"] = max(0.1, min(4.0, _safe_float(self.panel_gamma_var, self.DEFAULTS["panel_gamma"])))
        t["panel_dither"] = bool(self.panel_dither_var.get())
        t["sim_preview_mode"] = str(self.preview_mode_var.get() or "Split")
        return t

    def _render(self):
        if self._suspend_render:
            return

        theme = self._build_theme()

        self.state.ui.focused_index = max(0, _safe_int(self.focus_var, 0))
        self.state.ui.idle = bool(self.idle_var.get())
        memo_count = max(1, len(self.state.model.memos))
        self.state.ui.memo_index = _safe_int(self.memo_var, 0) % memo_count

        w, h = 800, 480

        bg = theme.get("bg", (229, 229, 229))
        image_color = Image.new("RGB", (w, h), bg if isinstance(bg, tuple) else (229, 229, 229))
        try:
            render_app(image_color, self.state, self.fonts, theme)
        except Exception as exc:
            print(f"[ui_tuner] color render error: {exc}", file=sys.stderr)
            return

        panel_theme = build_panel_theme(theme, muted_gray=int(theme.get("panel_muted", self.DEFAULTS["panel_muted"])))
        image_panel_rgb = Image.new("RGB", (w, h), panel_theme.get("bg", (255, 255, 255)))
        try:
            render_app(image_panel_rgb, self.state, self.fonts, panel_theme)
        except Exception as exc:
            print(f"[ui_tuner] panel render error: {exc}", file=sys.stderr)
            return

        image_panel_bw = quantize_for_panel(
            image_panel_rgb,
            threshold=int(theme.get("panel_threshold", self.DEFAULTS["panel_threshold"])),
            gamma=float(theme.get("panel_gamma", self.DEFAULTS["panel_gamma"])),
            dither=bool(theme.get("panel_dither", self.DEFAULTS["panel_dither"])),
        )

        mode = str(theme.get("sim_preview_mode") or "Panel")
        if mode == "Color":
            show_img = image_color
        elif mode == "Panel":
            show_img = image_panel_bw.convert("RGB")
        else:
            show_img = Image.new("RGB", (w * 2 + 12, h), (236, 236, 236))
            show_img.paste(image_color, (0, 0))
            show_img.paste(image_panel_bw.convert("RGB"), (w + 12, 0))

        self._photo = ImageTk.PhotoImage(show_img)
        self.preview.configure(image=self._photo)

        fonts_ok = "YES" if not self.fonts.missing_font_paths() else "NO"
        self.preview_status.configure(
            text=(
                f"mode={mode} threshold={int(theme['panel_threshold'])} muted={int(theme['panel_muted'])} "
                f"gamma={float(theme['panel_gamma']):.2f} dither={bool(theme['panel_dither'])} fonts_ok={fonts_ok}"
            )
        )

    def _save_theme(self):
        theme = self._build_theme()
        save_theme(self.theme_path, theme)


if __name__ == "__main__":
    KitchenTuner().mainloop()
