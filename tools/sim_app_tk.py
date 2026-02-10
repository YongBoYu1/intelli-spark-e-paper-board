import os
import sys
import json
import time
import tkinter as tk
from tkinter import ttk

from PIL import Image, ImageTk

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from app.core.state import AppState, DashboardModel, Reminder, WeatherDay, CalendarEvent, MemoItem
from app.core.reducer import reduce, Rotate, Click, LongPress, Back, Tick, MemoDelta
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

        self.preview_mode = tk.StringVar(value="Panel")
        self.panel_threshold = tk.IntVar(value=int(self.theme.get("panel_threshold", 168)))
        self.panel_muted = tk.IntVar(value=int(self.theme.get("panel_muted", 150)))
        self.panel_gamma = tk.DoubleVar(value=float(self.theme.get("panel_gamma", 1.0)))
        self.panel_dither = tk.BooleanVar(value=bool(self.theme.get("panel_dither", False)))

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
        ttk.Label(self.controls, text="Threshold").grid(row=0, column=2, padx=(0, 6), sticky="w")
        ttk.Spinbox(self.controls, from_=0, to=255, textvariable=self.panel_threshold, width=6).grid(row=0, column=3, padx=(0, 10), sticky="w")
        ttk.Label(self.controls, text="Muted").grid(row=0, column=4, padx=(0, 6), sticky="w")
        ttk.Spinbox(self.controls, from_=0, to=255, textvariable=self.panel_muted, width=6).grid(row=0, column=5, padx=(0, 10), sticky="w")
        ttk.Label(self.controls, text="Gamma").grid(row=0, column=6, padx=(0, 6), sticky="w")
        ttk.Spinbox(self.controls, from_=0.1, to=4.0, increment=0.05, textvariable=self.panel_gamma, width=6).grid(row=0, column=7, padx=(0, 10), sticky="w")
        ttk.Checkbutton(self.controls, text="Dither", variable=self.panel_dither, command=self._render).grid(row=0, column=8, sticky="w")

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
            "  Space = Long press (voice overlay stub)\n"
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
        self.bind("<Return>", lambda _e: self._dispatch(Click()))
        self.bind("<space>", lambda _e: self._dispatch(LongPress()))
        self.bind("b", lambda _e: self._dispatch(Back()))
        self.bind("B", lambda _e: self._dispatch(Back()))
        self.bind("<Escape>", lambda _e: self._dispatch(Back()))
        self.bind("<BackSpace>", lambda _e: self._dispatch(Back()))
        self.bind("q", lambda _e: self.destroy())

        for v in (self.preview_mode, self.panel_threshold, self.panel_muted, self.panel_gamma):
            v.trace_add("write", lambda *_: self._render())

        self.after(100, self._tick)
        self._render()

    def _tick(self):
        self.state = reduce(self.state, Tick(), theme=self.theme)
        self._render()
        self.after(100, self._tick)

    def _dispatch(self, ev):
        self.state = reduce(self.state, ev, theme=self.theme)
        self._render()

    def _render(self):
        w, h = 800, 480

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

        mode = str(self.preview_mode.get() or "Panel")
        if mode == "Color":
            show_img = color_img
        elif mode == "Panel":
            show_img = panel_bw.convert("RGB")
        else:
            show_img = Image.new("RGB", (w * 2 + 12, h), (236, 236, 236))
            show_img.paste(color_img, (0, 0))
            show_img.paste(panel_bw.convert("RGB"), (w + 12, 0))

        self._photo = ImageTk.PhotoImage(show_img)
        self.preview.configure(image=self._photo)

        ui = self.state.ui
        font_ok = "YES" if not self.fonts.missing_font_paths() else "NO"
        self.status.configure(
            text=(
                f"screen={ui.screen.value} focus={ui.focused_index} page={ui.page} idle={ui.idle} "
                f"pending_reorder={ui.pending_reorder} mode={mode} th={threshold} muted={muted} "
                f"gamma={gamma:.2f} dither={dither} fonts_ok={font_ok}"
            )
        )


if __name__ == "__main__":
    Simulator().mainloop()
