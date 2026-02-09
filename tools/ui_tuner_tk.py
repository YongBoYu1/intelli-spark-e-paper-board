import os
import sys
import json
import tkinter as tk
from tkinter import ttk, colorchooser, filedialog

from PIL import Image, ImageTk, ImageDraw

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from app.data.mock import load_dashboard
from app.shared.fonts import FontBook
from app.ui.home import render_home


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
        },
        default_key="inter_regular",
    )


def _hex_to_rgb(value):
    value = (value or "").strip()
    if value.startswith("#"):
        value = value[1:]
    if len(value) != 6:
        return (0, 0, 0)
    try:
        return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))
    except Exception:
        return (0, 0, 0)


def _rgb_to_hex(rgb):
    r, g, b = rgb
    return "#{:02X}{:02X}{:02X}".format(int(r), int(g), int(b))


class ScrollableFrame(ttk.Frame):
    def __init__(self, parent, *, width=420):
        super().__init__(parent)
        self.canvas = tk.Canvas(self, width=width, highlightthickness=0)
        self.scroll = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.scroll.set)

        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.scroll.grid(row=0, column=1, sticky="ns")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        self.inner = ttk.Frame(self.canvas)
        self.inner.columnconfigure(1, weight=1)
        self._window_id = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")

        self.inner.bind("<Configure>", self._on_inner_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)

        # Mouse wheel scrolling only when the cursor is over the scrollable area.
        self.canvas.bind("<Enter>", lambda _e: self._bind_mousewheel(True))
        self.canvas.bind("<Leave>", lambda _e: self._bind_mousewheel(False))

    def _on_inner_configure(self, _event):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        # Keep the inner frame width matched to the canvas width.
        self.canvas.itemconfigure(self._window_id, width=event.width)

    def _bind_mousewheel(self, enabled: bool):
        if enabled:
            self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)
            self.canvas.bind_all("<Button-4>", self._on_mousewheel_linux)
            self.canvas.bind_all("<Button-5>", self._on_mousewheel_linux)
        else:
            self.canvas.unbind_all("<MouseWheel>")
            self.canvas.unbind_all("<Button-4>")
            self.canvas.unbind_all("<Button-5>")

    def _on_mousewheel(self, event):
        # Windows: delta is multiple of 120; macOS: delta is small but frequent.
        if sys.platform == "darwin":
            delta = event.delta
        else:
            delta = int(event.delta / 120)
        self.canvas.yview_scroll(int(-1 * delta), "units")

    def _on_mousewheel_linux(self, event):
        if event.num == 4:
            self.canvas.yview_scroll(-1, "units")
        elif event.num == 5:
            self.canvas.yview_scroll(1, "units")


class UITuner(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("UI Tuner (Tk)")
        self.geometry("1200x820")

        self.repo_root = REPO_ROOT
        self.theme_path = os.path.join(self.repo_root, "ui_tuner_theme.json")
        self.fonts = build_fonts(self.repo_root)
        self.data = load_dashboard()
        self.data["time"] = self.data.get("time") or "18:13"
        self.data["date"] = self.data.get("date") or "FRIDAY, FEB 6"
        self.data["location"] = self.data.get("location") or "NEW YORK"

        # Left: controls. Right: preview.
        self.controls_container = ttk.Frame(self)
        self.controls_container.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        self.controls_container.rowconfigure(1, weight=1)
        self.controls_container.columnconfigure(0, weight=1)

        self.preview_label = ttk.Label(self)
        self.preview_label.grid(row=0, column=1, sticky="nsew", padx=10, pady=10)

        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        self._build_toolbar()

        self.notebook = ttk.Notebook(self.controls_container)
        self.notebook.grid(row=1, column=0, sticky="nsew")

        self.tabs = {}
        for key, title in [
            ("data", "Preview"),
            ("colors", "Colors"),
            ("borders", "Borders"),
            ("fonts", "Fonts"),
            ("layout", "Layout"),
            ("weather", "Weather"),
            ("system", "System"),
        ]:
            sf = ScrollableFrame(self.notebook, width=440)
            self.notebook.add(sf, text=title)
            self.tabs[key] = sf

        # Debounced rendering (keeps the UI responsive while dragging sliders).
        self._render_job = None

        self._build_controls()
        self._load_theme_if_present()
        self._schedule_render()

    def _build_toolbar(self):
        bar = ttk.Frame(self.controls_container)
        bar.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        bar.columnconfigure(0, weight=1)

        left = ttk.Frame(bar)
        left.grid(row=0, column=0, sticky="w")

        ttk.Button(left, text="Load Theme", command=self._load_theme_dialog).grid(row=0, column=0, padx=(0, 6))
        ttk.Button(left, text="Save Theme", command=self._save_theme).grid(row=0, column=1, padx=(0, 6))
        ttk.Button(left, text="Save PNG", command=self._save_png).grid(row=0, column=2, padx=(0, 6))
        ttk.Button(left, text="Reset", command=self._reset_defaults).grid(row=0, column=3)

    def _build_controls(self):
        # System / mode
        self.mode = tk.StringVar(value="Day")
        self.password = tk.StringVar(value="")
        self.weather_port = tk.StringVar(value="")

        # Data preview inputs
        self.time_text = tk.StringVar(value=self.data["time"])
        self.date_text = tk.StringVar(value=self.data["date"])
        self.location_text = tk.StringVar(value=self.data["location"])

        # Colors
        self.ink_color = tk.StringVar(value="#111111")
        self.border_color = tk.StringVar(value="#111111")
        self.muted_color = tk.StringVar(value="#A0A0A0")
        self.card_color = tk.StringVar(value="#FFFFFF")
        self.bg_color = tk.StringVar(value="#E5E5E5")

        self.bg_preset = tk.StringVar(value="Light Gray")
        self.bg_gray = tk.IntVar(value=229)

        # Border controls
        self.border_width = tk.IntVar(value=2)
        self.divider_width = tk.IntVar(value=2)
        self.item_border_width = tk.IntVar(value=2)
        self.checkbox_border_width = tk.IntVar(value=2)
        self.underline_width = tk.IntVar(value=2)
        self.weather_divider_width = tk.IntVar(value=2)
        self.icon_stroke = tk.IntVar(value=2)
        self.wifi_stroke = tk.IntVar(value=2)
        self.battery_stroke = tk.IntVar(value=2)

        # Offsets / sizes
        self.time_size = tk.IntVar(value=112)
        self.time_center_y = tk.IntVar(value=-20)
        self.time_autofit = tk.BooleanVar(value=True)
        self.underline_offset = tk.IntVar(value=8)
        self.stats_offset = tk.IntVar(value=30)
        self.divider_y = tk.IntVar(value=72)
        self.list_top = tk.IntVar(value=87)
        self.item_h = tk.IntVar(value=65)
        self.item_gap = tk.IntVar(value=9)
        self.items_per_page = tk.IntVar(value=5)

        # Fonts
        self.time_font = tk.StringVar(value="jet_extrabold")
        self.date_font = tk.StringVar(value="inter_bold")
        self.title_font = tk.StringVar(value="inter_black")
        self.meta_font = tk.StringVar(value="inter_regular")
        self.item_font = tk.StringVar(value="inter_semibold")
        self.right_font = tk.StringVar(value="inter_regular")

        self.meta_size = tk.IntVar(value=12)
        self.item_size = tk.IntVar(value=18)
        self.right_size = tk.IntVar(value=12)

        # Weather tuning (matches app/ui/home.py weather strip params)
        self.weather_day_top = tk.IntVar(value=10)
        self.weather_icon_top = tk.IntVar(value=34)
        self.weather_temp_bottom = tk.IntVar(value=10)
        self.weather_temp_gap = tk.IntVar(value=2)
        self.weather_icon_size = tk.IntVar(value=36)
        self.weather_day_font = tk.StringVar(value="inter_semibold")
        self.weather_hi_font = tk.StringVar(value="inter_semibold")
        self.weather_lo_font = tk.StringVar(value="inter_regular")
        self.weather_day_size = tk.IntVar(value=12)
        self.weather_hi_size = tk.IntVar(value=12)
        self.weather_lo_size = tk.IntVar(value=10)
        self.weather_hi_offset_y = tk.IntVar(value=0)
        self.weather_lo_offset_y = tk.IntVar(value=0)

        # Build each tab.
        self._build_tab_system()
        self._build_tab_data()
        self._build_tab_colors()
        self._build_tab_borders()
        self._build_tab_fonts()
        self._build_tab_layout()
        self._build_tab_weather()

        # Global traces -> schedule render
        for v in [
            self.mode,
            self.password,
            self.weather_port,
            self.time_text,
            self.date_text,
            self.location_text,
            self.ink_color,
            self.border_color,
            self.muted_color,
            self.card_color,
            self.bg_color,
            self.bg_preset,
            self.bg_gray,
            self.border_width,
            self.divider_width,
            self.item_border_width,
            self.checkbox_border_width,
            self.underline_width,
            self.weather_divider_width,
            self.icon_stroke,
            self.wifi_stroke,
            self.battery_stroke,
            self.time_size,
            self.time_center_y,
            self.time_autofit,
            self.underline_offset,
            self.stats_offset,
            self.divider_y,
            self.list_top,
            self.item_h,
            self.item_gap,
            self.items_per_page,
            self.time_font,
            self.date_font,
            self.title_font,
            self.meta_font,
            self.item_font,
            self.right_font,
            self.meta_size,
            self.item_size,
            self.right_size,
            self.weather_day_top,
            self.weather_icon_top,
            self.weather_temp_bottom,
            self.weather_temp_gap,
            self.weather_icon_size,
            self.weather_day_font,
            self.weather_hi_font,
            self.weather_lo_font,
            self.weather_day_size,
            self.weather_hi_size,
            self.weather_lo_size,
            self.weather_hi_offset_y,
            self.weather_lo_offset_y,
        ]:
            try:
                v.trace_add("write", lambda *_: self._schedule_render())
            except Exception:
                pass

    def _section_label(self, parent, text, row):
        lbl = ttk.Label(parent, text=text, font=("Arial", 12, "bold"))
        lbl.grid(row=row, column=0, columnspan=2, sticky="w", pady=(10, 4))
        return row + 1

    def _add_scale(self, parent, label, var, min_v, max_v, row):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w")
        scale = tk.Scale(
            parent,
            from_=min_v,
            to=max_v,
            orient="horizontal",
            resolution=1,
            showvalue=True,
            variable=var,
            command=lambda _v: self._schedule_render(),
        )
        scale.grid(row=row, column=1, sticky="ew")
        return row + 1

    def _add_select(self, parent, label, var, row):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w")
        options = list(self.fonts.font_paths.keys())
        menu = ttk.Combobox(parent, textvariable=var, values=options, state="readonly")
        menu.grid(row=row, column=1, sticky="ew")
        menu.bind("<<ComboboxSelected>>", lambda _e: self._schedule_render())
        return row + 1

    def _add_select_simple(self, parent, label, var, options, row, callback=None):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w")
        menu = ttk.Combobox(parent, textvariable=var, values=options, state="readonly")
        menu.grid(row=row, column=1, sticky="ew")
        if callback:
            menu.bind("<<ComboboxSelected>>", lambda _e: callback())
        return row + 1

    def _add_entry(self, parent, label, var, row, show=None):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w")
        entry = ttk.Entry(parent, textvariable=var, show=show)
        entry.grid(row=row, column=1, sticky="ew")
        return row + 1

    def _add_color(self, parent, label, var, row, presets):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w")

        frame = ttk.Frame(parent)
        frame.grid(row=row, column=1, sticky="ew")
        frame.columnconfigure(2, weight=1)

        swatch = tk.Canvas(frame, width=26, height=16, highlightthickness=1, highlightbackground="#888888")
        swatch.grid(row=0, column=0, padx=(0, 6))
        swatch_rect = swatch.create_rectangle(0, 0, 26, 16, outline="", fill=var.get())

        preset_var = tk.StringVar(value="Custom")
        preset_names = list(presets.keys()) + ["Custom"]
        combo = ttk.Combobox(frame, textvariable=preset_var, values=preset_names, state="readonly", width=14)
        combo.grid(row=0, column=1, sticky="w")

        def apply_preset():
            name = preset_var.get()
            if name != "Custom":
                var.set(presets[name])

        combo.bind("<<ComboboxSelected>>", lambda _e: apply_preset())

        ttk.Button(frame, text="Pick…", command=lambda: self._pick_color(var)).grid(row=0, column=2, sticky="e")

        def update_swatch(*_):
            val = var.get()
            swatch.itemconfigure(swatch_rect, fill=val)
            if val in presets.values():
                for k, v in presets.items():
                    if v.upper() == val.upper():
                        preset_var.set(k)
                        break
            else:
                preset_var.set("Custom")

        var.trace_add("write", update_swatch)
        update_swatch()
        return row + 1

    def _add_check(self, parent, label, var, row):
        chk = ttk.Checkbutton(parent, text=label, variable=var, command=self._schedule_render)
        chk.grid(row=row, column=0, columnspan=2, sticky="w")
        return row + 1

    def _add_font_preview(self, parent, row):
        self.font_preview_label = ttk.Label(parent)
        self.font_preview_label.grid(row=row, column=0, columnspan=2, sticky="w")
        return row + 1

    def _add_bg_controls(self, parent, row):
        ttk.Label(parent, text="BG preset").grid(row=row, column=0, sticky="w")
        presets = ["White", "Light Gray", "Medium Gray", "Dark Gray"]
        menu = ttk.Combobox(parent, textvariable=self.bg_preset, values=presets, state="readonly")
        menu.grid(row=row, column=1, sticky="ew")
        menu.bind("<<ComboboxSelected>>", lambda _e: self._apply_bg_preset())
        row += 1
        ttk.Label(parent, text="BG gray (0-255)").grid(row=row, column=0, sticky="w")
        scale = tk.Scale(
            parent,
            from_=0,
            to=255,
            orient="horizontal",
            resolution=1,
            showvalue=True,
            variable=self.bg_gray,
            command=lambda _v: self._apply_bg_gray(),
        )
        scale.grid(row=row, column=1, sticky="ew")
        return row + 1

    def _apply_bg_preset(self):
        preset = self.bg_preset.get()
        mapping = {
            "White": 255,
            "Light Gray": 229,
            "Medium Gray": 200,
            "Dark Gray": 170,
        }
        value = mapping.get(preset, 229)
        self.bg_gray.set(value)
        self.bg_color.set(_rgb_to_hex((value, value, value)))
        self._schedule_render()

    def _apply_bg_gray(self):
        value = int(self.bg_gray.get())
        self.bg_color.set(_rgb_to_hex((value, value, value)))
        self._schedule_render()

    def _apply_mode_preset(self):
        mode = self.mode.get()
        if mode == "Night":
            self.bg_color.set("#111111")
            self.card_color.set("#1F1F1F")
            self.ink_color.set("#F2F2F2")
            self.border_color.set("#F2F2F2")
            self.muted_color.set("#B0B0B0")
        else:
            self.bg_color.set("#E5E5E5")
            self.card_color.set("#FFFFFF")
            self.ink_color.set("#111111")
            self.border_color.set("#111111")
            self.muted_color.set("#A0A0A0")
        self._schedule_render()

    def _pick_color(self, var):
        color = colorchooser.askcolor(color=var.get())[1]
        if color:
            var.set(color)

    def _build_theme(self):
        return {
            "ink": _hex_to_rgb(self.ink_color.get()),
            "border": _hex_to_rgb(self.border_color.get()),
            "card": _hex_to_rgb(self.card_color.get()),
            "muted": _hex_to_rgb(self.muted_color.get()),
            "time_font": self.time_font.get(),
            "date_font": self.date_font.get(),
            "title_font": self.title_font.get(),
            "meta_font": self.meta_font.get(),
            "item_font": self.item_font.get(),
            "right_font": self.right_font.get(),
            "time_size": int(self.time_size.get()),
            "time_autofit": bool(self.time_autofit.get()),
            "time_center_y": int(self.time_center_y.get()),
            "underline_offset": int(self.underline_offset.get()),
            "stats_offset": int(self.stats_offset.get()),
            "divider_y": int(self.divider_y.get()),
            "list_top": int(self.list_top.get()),
            "item_h": int(self.item_h.get()),
            "item_gap": int(self.item_gap.get()),
            "items_per_page": int(self.items_per_page.get()),
            "meta_size": int(self.meta_size.get()),
            "item_size": int(self.item_size.get()),
            "right_size": int(self.right_size.get()),
            "border_width": int(self.border_width.get()),
            "divider_width": int(self.divider_width.get()),
            "item_border_width": int(self.item_border_width.get()),
            "checkbox_border_width": int(self.checkbox_border_width.get()),
            "underline_width": int(self.underline_width.get()),
            "weather_divider_width": int(self.weather_divider_width.get()),
            "icon_stroke": int(self.icon_stroke.get()),
            "wifi_stroke": int(self.wifi_stroke.get()),
            "battery_stroke": int(self.battery_stroke.get()),
            "bg": self.bg_color.get(),
            "system_mode": self.mode.get(),
            "system_password": self.password.get(),
            "weather_port": self.weather_port.get(),
            "data_time": self.time_text.get(),
            "data_date": self.date_text.get(),
            "data_location": self.location_text.get(),
            "weather_day_top": int(self.weather_day_top.get()),
            "weather_icon_top": int(self.weather_icon_top.get()),
            "weather_temp_bottom": int(self.weather_temp_bottom.get()),
            "weather_temp_gap": int(self.weather_temp_gap.get()),
            "weather_icon_size": int(self.weather_icon_size.get()),
            "weather_day_font": self.weather_day_font.get(),
            "weather_hi_font": self.weather_hi_font.get(),
            "weather_lo_font": self.weather_lo_font.get(),
            "weather_day_size": int(self.weather_day_size.get()),
            "weather_hi_size": int(self.weather_hi_size.get()),
            "weather_lo_size": int(self.weather_lo_size.get()),
            "weather_hi_offset_y": int(self.weather_hi_offset_y.get()),
            "weather_lo_offset_y": int(self.weather_lo_offset_y.get()),
        }

    def _schedule_render(self):
        if self._render_job is not None:
            try:
                self.after_cancel(self._render_job)
            except Exception:
                pass
        self._render_job = self.after(60, self._render)

    def _render(self):
        self._render_job = None

        # apply preview data
        t = self.time_text.get().strip()
        d = self.date_text.get().strip()
        loc = self.location_text.get().strip()
        self.data["time"] = t if t else None
        self.data["date"] = d if d else None
        self.data["location"] = loc if loc else None

        width, height = 800, 480
        bg_rgb = _hex_to_rgb(self.bg_color.get())
        image = Image.new("RGB", (width, height), bg_rgb)
        theme = self._build_theme()
        render_home(image, self.data, self.fonts, theme=theme)
        self._photo = ImageTk.PhotoImage(image)
        self.preview_label.configure(image=self._photo)
        self._render_font_preview()

    def _save_png(self):
        filename = "ui_tuner_export.png"
        width, height = 800, 480
        bg_rgb = _hex_to_rgb(self.bg_color.get())
        image = Image.new("RGB", (width, height), bg_rgb)
        theme = self._build_theme()
        render_home(image, self.data, self.fonts, theme=theme)
        image.save(filename)

    def _save_theme(self):
        theme = self._build_theme()
        with open(self.theme_path, "w", encoding="utf-8") as f:
            json.dump(theme, f, indent=2)

    def _render_font_preview(self):
        img = Image.new("RGB", (380, 150), (255, 255, 255))
        draw = ImageDraw.Draw(img)

        time_font = self.fonts.get(self.time_font.get(), 24)
        date_font = self.fonts.get(self.date_font.get(), 16)
        title_font = self.fonts.get(self.title_font.get(), 16)
        meta_font = self.fonts.get(self.meta_font.get(), 12)
        item_font = self.fonts.get(self.item_font.get(), 14)
        right_font = self.fonts.get(self.right_font.get(), 12)

        draw.text((8, 6), "Time 18:13", font=time_font, fill=(17, 17, 17))
        draw.text((8, 40), "Date FRIDAY, FEB 6", font=date_font, fill=(17, 17, 17))
        draw.text((8, 62), "Title REMINDERS", font=title_font, fill=(17, 17, 17))
        draw.text((8, 84), "Meta 7 ITEMS • 6 DUE", font=meta_font, fill=(17, 17, 17))
        draw.text((8, 106), "Item Doctor Appointment", font=item_font, fill=(17, 17, 17))
        draw.text((8, 128), "Right 14:00", font=right_font, fill=(17, 17, 17))

        self._font_photo = ImageTk.PhotoImage(img)
        self.font_preview_label.configure(image=self._font_photo)

    def _load_theme_if_present(self):
        if os.path.exists(self.theme_path):
            try:
                with open(self.theme_path, "r", encoding="utf-8") as f:
                    theme = json.load(f)
                self._load_theme_into_vars(theme)
            except Exception:
                pass

    def _load_theme_dialog(self):
        path = filedialog.askopenfilename(
            title="Load theme JSON",
            filetypes=[("Theme JSON", "*.json"), ("All files", "*.*")],
            initialdir=self.repo_root,
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                theme = json.load(f)
            self._load_theme_into_vars(theme)
            self._schedule_render()
        except Exception:
            return

    def _load_theme_into_vars(self, theme):
        # Colors: accept tuple/list or hex string.
        for key, var in [
            ("ink", self.ink_color),
            ("border", self.border_color),
            ("muted", self.muted_color),
            ("card", self.card_color),
            ("bg", self.bg_color),
        ]:
            val = theme.get(key)
            if isinstance(val, str):
                var.set(val)
            elif isinstance(val, (list, tuple)) and len(val) == 3:
                var.set(_rgb_to_hex(tuple(val)))

        self.mode.set(theme.get("system_mode", self.mode.get()))
        self.password.set(theme.get("system_password", self.password.get()))
        self.weather_port.set(theme.get("weather_port", self.weather_port.get()))

        self.time_text.set(theme.get("data_time", self.time_text.get()))
        self.date_text.set(theme.get("data_date", self.date_text.get()))
        self.location_text.set(theme.get("data_location", self.location_text.get()))

        for key, var in [
            ("border_width", self.border_width),
            ("divider_width", self.divider_width),
            ("item_border_width", self.item_border_width),
            ("checkbox_border_width", self.checkbox_border_width),
            ("underline_width", self.underline_width),
            ("weather_divider_width", self.weather_divider_width),
            ("icon_stroke", self.icon_stroke),
            ("wifi_stroke", self.wifi_stroke),
            ("battery_stroke", self.battery_stroke),
            ("time_size", self.time_size),
            ("time_center_y", self.time_center_y),
            ("time_autofit", self.time_autofit),
            ("underline_offset", self.underline_offset),
            ("stats_offset", self.stats_offset),
            ("divider_y", self.divider_y),
            ("list_top", self.list_top),
            ("item_h", self.item_h),
            ("item_gap", self.item_gap),
            ("items_per_page", self.items_per_page),
            ("meta_size", self.meta_size),
            ("item_size", self.item_size),
            ("right_size", self.right_size),
            ("weather_day_top", self.weather_day_top),
            ("weather_icon_top", self.weather_icon_top),
            ("weather_temp_bottom", self.weather_temp_bottom),
            ("weather_temp_gap", self.weather_temp_gap),
            ("weather_icon_size", self.weather_icon_size),
            ("weather_day_size", self.weather_day_size),
            ("weather_hi_size", self.weather_hi_size),
            ("weather_lo_size", self.weather_lo_size),
            ("weather_hi_offset_y", self.weather_hi_offset_y),
            ("weather_lo_offset_y", self.weather_lo_offset_y),
        ]:
            if key in theme:
                try:
                    var.set(theme[key])
                except Exception:
                    pass

        for key, var in [
            ("time_font", self.time_font),
            ("date_font", self.date_font),
            ("title_font", self.title_font),
            ("meta_font", self.meta_font),
            ("item_font", self.item_font),
            ("right_font", self.right_font),
            ("weather_day_font", self.weather_day_font),
            ("weather_hi_font", self.weather_hi_font),
            ("weather_lo_font", self.weather_lo_font),
        ]:
            if key in theme and isinstance(theme[key], str):
                var.set(theme[key])

        # Keep BG preset/slider in sync when bg is grayscale.
        bg = _hex_to_rgb(self.bg_color.get())
        if bg[0] == bg[1] == bg[2]:
            self.bg_gray.set(bg[0])

    def _reset_defaults(self):
        # Reasonable defaults (match the current reference baseline).
        self.mode.set("Day")
        self.password.set("")
        self.weather_port.set("")

        self.time_text.set("18:13")
        self.date_text.set("FRIDAY, FEB 6")
        self.location_text.set("New York")

        self.ink_color.set("#111111")
        self.border_color.set("#111111")
        self.muted_color.set("#A0A0A0")
        self.card_color.set("#FFFFFF")
        self.bg_color.set("#E5E5E5")
        self.bg_preset.set("Light Gray")
        self.bg_gray.set(229)

        self.border_width.set(2)
        self.divider_width.set(2)
        self.item_border_width.set(2)
        self.checkbox_border_width.set(2)
        self.underline_width.set(2)
        self.weather_divider_width.set(2)
        self.icon_stroke.set(2)
        self.wifi_stroke.set(2)
        self.battery_stroke.set(2)

        self.time_size.set(112)
        self.time_autofit.set(True)
        self.time_center_y.set(-20)
        self.underline_offset.set(8)
        self.stats_offset.set(30)
        self.divider_y.set(72)
        self.list_top.set(87)
        self.item_h.set(65)
        self.item_gap.set(9)
        self.items_per_page.set(5)

        self.time_font.set("jet_extrabold")
        self.date_font.set("inter_bold")
        self.title_font.set("inter_black")
        self.meta_font.set("inter_regular")
        self.item_font.set("inter_semibold")
        self.right_font.set("inter_regular")
        self.meta_size.set(12)
        self.item_size.set(18)
        self.right_size.set(12)

        self.weather_day_top.set(10)
        self.weather_icon_top.set(34)
        self.weather_temp_bottom.set(10)
        self.weather_temp_gap.set(2)
        self.weather_icon_size.set(36)
        self.weather_day_font.set("inter_semibold")
        self.weather_hi_font.set("inter_semibold")
        self.weather_lo_font.set("inter_regular")
        self.weather_day_size.set(12)
        self.weather_hi_size.set(12)
        self.weather_lo_size.set(10)
        self.weather_hi_offset_y.set(0)
        self.weather_lo_offset_y.set(0)

        self._schedule_render()

    def _build_tab_system(self):
        parent = self.tabs["system"].inner
        row = 0
        row = self._section_label(parent, "System", row)
        row = self._add_select_simple(parent, "Mode", self.mode, ["Day", "Night"], row, self._apply_mode_preset)
        row = self._add_entry(parent, "Weather port", self.weather_port, row)
        row = self._add_entry(parent, "Password", self.password, row, show="*")

    def _build_tab_data(self):
        parent = self.tabs["data"].inner
        row = 0
        row = self._section_label(parent, "Data (Preview Only)", row)
        row = self._add_entry(parent, "Time", self.time_text, row)
        row = self._add_entry(parent, "Date", self.date_text, row)
        row = self._add_entry(parent, "Location", self.location_text, row)

    def _build_tab_colors(self):
        parent = self.tabs["colors"].inner
        row = 0
        row = self._section_label(parent, "Colors", row)

        presets = {
            "Black": "#000000",
            "Dark Ink": "#111111",
            "Muted Gray": "#A0A0A0",
            "White": "#FFFFFF",
            "Light Gray": "#E5E5E5",
        }
        row = self._add_color(parent, "Ink", self.ink_color, row, presets)
        row = self._add_color(parent, "Border", self.border_color, row, presets)
        row = self._add_color(parent, "Muted", self.muted_color, row, presets)
        row = self._add_color(parent, "Card", self.card_color, row, presets)
        row = self._add_color(parent, "Background", self.bg_color, row, presets)
        row = self._add_bg_controls(parent, row)

    def _build_tab_borders(self):
        parent = self.tabs["borders"].inner
        row = 0
        row = self._section_label(parent, "Line Weights", row)
        row = self._add_scale(parent, "Border width", self.border_width, 1, 6, row)
        row = self._add_scale(parent, "Divider width", self.divider_width, 1, 6, row)
        row = self._add_scale(parent, "Item border", self.item_border_width, 1, 6, row)
        row = self._add_scale(parent, "Checkbox border", self.checkbox_border_width, 1, 6, row)
        row = self._add_scale(parent, "Underline width", self.underline_width, 1, 6, row)
        row = self._add_scale(parent, "Weather divider", self.weather_divider_width, 1, 6, row)
        row = self._add_scale(parent, "Icon stroke", self.icon_stroke, 1, 6, row)
        row = self._add_scale(parent, "WiFi stroke", self.wifi_stroke, 1, 6, row)
        row = self._add_scale(parent, "Battery stroke", self.battery_stroke, 1, 6, row)

    def _build_tab_fonts(self):
        parent = self.tabs["fonts"].inner
        row = 0
        row = self._section_label(parent, "Fonts", row)
        row = self._add_select(parent, "Time font", self.time_font, row)
        row = self._add_select(parent, "Date font", self.date_font, row)
        row = self._add_select(parent, "Title font", self.title_font, row)
        row = self._add_select(parent, "Meta font", self.meta_font, row)
        row = self._add_select(parent, "Item font", self.item_font, row)
        row = self._add_select(parent, "Right font", self.right_font, row)
        row = self._section_label(parent, "Font preview", row)
        row = self._add_font_preview(parent, row)

    def _build_tab_layout(self):
        parent = self.tabs["layout"].inner
        row = 0
        row = self._section_label(parent, "Clock", row)
        row = self._add_scale(parent, "Time size (max)", self.time_size, 80, 140, row)
        row = self._add_check(parent, "Time auto-fit", self.time_autofit, row)
        row = self._add_scale(parent, "Time center Y", self.time_center_y, -80, 80, row)
        row = self._add_scale(parent, "Underline offset", self.underline_offset, -10, 30, row)

        row = self._section_label(parent, "Right Panel Header", row)
        row = self._add_scale(parent, "Stats offset", self.stats_offset, 10, 60, row)
        row = self._add_scale(parent, "Divider Y", self.divider_y, 50, 110, row)

        row = self._section_label(parent, "Reminder List", row)
        row = self._add_scale(parent, "List top", self.list_top, 60, 160, row)
        row = self._add_scale(parent, "Item height", self.item_h, 50, 100, row)
        row = self._add_scale(parent, "Item gap", self.item_gap, 6, 20, row)
        row = self._add_scale(parent, "Items per page", self.items_per_page, 3, 6, row)

        row = self._section_label(parent, "Font sizes", row)
        row = self._add_scale(parent, "Meta size", self.meta_size, 8, 16, row)
        row = self._add_scale(parent, "Item size", self.item_size, 12, 26, row)
        row = self._add_scale(parent, "Right size", self.right_size, 8, 16, row)

    def _build_tab_weather(self):
        parent = self.tabs["weather"].inner
        row = 0
        row = self._section_label(parent, "Weather Strip", row)
        row = self._add_scale(parent, "Day top", self.weather_day_top, 0, 30, row)
        row = self._add_scale(parent, "Icon top", self.weather_icon_top, 10, 60, row)
        row = self._add_scale(parent, "Temp bottom", self.weather_temp_bottom, 0, 30, row)
        row = self._add_scale(parent, "Temp gap", self.weather_temp_gap, 0, 10, row)
        row = self._add_scale(parent, "Icon size", self.weather_icon_size, 24, 52, row)

        row = self._section_label(parent, "Weather Fonts", row)
        row = self._add_select(parent, "Day font", self.weather_day_font, row)
        row = self._add_scale(parent, "Day size", self.weather_day_size, 8, 16, row)
        row = self._add_select(parent, "High temp font", self.weather_hi_font, row)
        row = self._add_scale(parent, "High temp size", self.weather_hi_size, 8, 16, row)
        row = self._add_select(parent, "Low temp font", self.weather_lo_font, row)
        row = self._add_scale(parent, "Low temp size", self.weather_lo_size, 8, 16, row)
        row = self._section_label(parent, "Temp Offsets (px)", row)
        row = self._add_scale(parent, "High temp Y offset", self.weather_hi_offset_y, -20, 20, row)
        row = self._add_scale(parent, "Low temp Y offset", self.weather_lo_offset_y, -20, 20, row)


if __name__ == "__main__":
    app = UITuner()
    app.mainloop()
