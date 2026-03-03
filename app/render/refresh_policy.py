from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from app.core.state import AppState, Screen

Rect = tuple[int, int, int, int]


@dataclass(frozen=True)
class ModeParams:
    min_refresh_gap_ms: int
    partial_area_limit: float
    default_full_refresh_every: int


def mode_params(mode: str) -> ModeParams:
    normalized = str(mode or "balanced").strip().lower()
    if normalized == "slow":
        return ModeParams(min_refresh_gap_ms=200, partial_area_limit=0.40, default_full_refresh_every=5)
    if normalized == "fast":
        return ModeParams(min_refresh_gap_ms=80, partial_area_limit=0.85, default_full_refresh_every=15)
    return ModeParams(min_refresh_gap_ms=120, partial_area_limit=0.65, default_full_refresh_every=10)


def screen_partial_area_limit(screen: Screen, mode: str) -> float:
    base = mode_params(mode).partial_area_limit
    if screen == Screen.TIMER:
        return min(0.95, base + 0.20)
    if screen == Screen.MENU:
        return max(0.30, min(base, 0.55))
    if screen == Screen.CALENDAR:
        return max(0.45, min(base, 0.72))
    if screen == Screen.WEATHER:
        return max(0.50, min(base, 0.78))
    if screen == Screen.HOME:
        # Home is artifact-prone on large partial updates; keep default conservative.
        return max(0.12, min(base, 0.22))
    return base


def effective_full_refresh_every(
    *,
    screen: Screen,
    mode: str,
    ui_full_refresh_every: int | None,
    timer_full_refresh_every_override: int | None = None,
) -> int:
    params = mode_params(mode)
    try:
        value = int(ui_full_refresh_every or 0)
    except Exception:
        value = 0
    if value <= 0:
        value = params.default_full_refresh_every

    if screen == Screen.TIMER:
        try:
            timer_override = int(timer_full_refresh_every_override or 0)
        except Exception:
            timer_override = 0
        if timer_override > 0:
            value = max(value, timer_override)

    return max(1, value)


def _clip_rect(rect: Rect, width: int, height: int) -> Rect | None:
    x0, y0, x1, y1 = rect
    x0 = max(0, min(int(width), int(x0)))
    y0 = max(0, min(int(height), int(y0)))
    x1 = max(0, min(int(width), int(x1)))
    y1 = max(0, min(int(height), int(y1)))
    if x1 <= x0 or y1 <= y0:
        return None
    return (x0, y0, x1, y1)


def align_rect_for_partial(rect: Rect, width: int, height: int, *, pad: int = 2) -> Rect | None:
    x0, y0, x1, y1 = rect
    expanded = (x0 - pad, y0 - pad, x1 + pad, y1 + pad)
    clipped = _clip_rect(expanded, width, height)
    if clipped is None:
        return None
    x0, y0, x1, y1 = clipped
    x0 = (x0 // 8) * 8
    x1 = ((x1 + 7) // 8) * 8
    x1 = max(x0 + 8, min(int(width), x1))
    aligned = (x0, y0, x1, y1)
    return _clip_rect(aligned, width, height)


def merge_rects(rects: Iterable[Rect], width: int, height: int) -> Rect | None:
    x0 = None
    y0 = None
    x1 = None
    y1 = None
    for rect in rects:
        clipped = _clip_rect(rect, width, height)
        if clipped is None:
            continue
        rx0, ry0, rx1, ry1 = clipped
        if x0 is None:
            x0, y0, x1, y1 = rx0, ry0, rx1, ry1
        else:
            x0 = min(x0, rx0)
            y0 = min(y0, ry0)
            x1 = max(x1, rx1)
            y1 = max(y1, ry1)
    if x0 is None:
        return None
    return (x0, y0, x1, y1)


def rect_area_ratio(rect: Rect, width: int, height: int) -> float:
    x0, y0, x1, y1 = rect
    area = max(0, x1 - x0) * max(0, y1 - y0)
    total = max(1, int(width) * int(height))
    return float(area) / float(total)


def rect_contains(outer: Rect, inner: Rect, *, slack: int = 0) -> bool:
    ox0, oy0, ox1, oy1 = outer
    ix0, iy0, ix1, iy1 = inner
    return (
        ix0 >= (ox0 - slack)
        and iy0 >= (oy0 - slack)
        and ix1 <= (ox1 + slack)
        and iy1 <= (oy1 + slack)
    )


@dataclass
class RefreshPolicyRuntime:
    partial_count: int = 0
    last_refresh_ts: float = 0.0
    last_full_refresh_ts: float = 0.0
    pending_dirty_rects: list[Rect] = field(default_factory=list)

    def enqueue(self, rects: Iterable[Rect]) -> None:
        for rect in rects:
            self.pending_dirty_rects.append(rect)

    def clear_pending(self) -> None:
        self.pending_dirty_rects = []

    def mark_partial(self, now: float) -> None:
        self.partial_count = int(self.partial_count) + 1
        self.last_refresh_ts = float(now)

    def mark_fast_full(self, now: float) -> None:
        self.partial_count = 0
        self.last_refresh_ts = float(now)

    def mark_full_clean(self, now: float) -> None:
        self.partial_count = 0
        self.last_refresh_ts = float(now)
        self.last_full_refresh_ts = float(now)

    def should_throttle(self, now: float, min_refresh_gap_ms: int) -> bool:
        gap_ms = max(0, int(min_refresh_gap_ms))
        if gap_ms <= 0:
            return False
        if self.last_refresh_ts <= 0:
            return False
        return (float(now) - float(self.last_refresh_ts)) < (gap_ms / 1000.0)

    def needs_full_clean(self, now: float, *, full_refresh_every: int, max_full_age_s: float = 24 * 60 * 60) -> bool:
        return bool(self.full_clean_reason(now, full_refresh_every=full_refresh_every, max_full_age_s=max_full_age_s))

    def full_clean_reason(self, now: float, *, full_refresh_every: int, max_full_age_s: float = 24 * 60 * 60) -> str:
        if int(self.partial_count) >= max(1, int(full_refresh_every)):
            return "partial_budget"
        if self.last_full_refresh_ts > 0 and (float(now) - float(self.last_full_refresh_ts)) >= float(max_full_age_s):
            return "full_age"
        return ""


@dataclass(frozen=True)
class UiSnapshot:
    screen: Screen
    rotation_deg: int
    font_size: str
    focused_index: int
    menu_focused: str
    settings_focused_index: int
    settings_notice: str
    partial_refresh_mode: str
    full_refresh_every: int
    wifi_enabled: bool
    bluetooth_enabled: bool
    auto_sync_enabled: bool
    last_sync_at: int
    timer_seconds: int
    timer_running: bool
    timer_focused_index: int
    widget_mode: str
    weather_day_index: int
    weather_digest: tuple
    calendar_offset_days: int
    calendar_mode: str
    calendar_selected_index: int
    reminders_digest: tuple
    memo_index: int
    voice_active: bool
    voice_phase: str


def build_ui_snapshot(state: AppState) -> UiSnapshot:
    return UiSnapshot(
        screen=state.ui.screen,
        rotation_deg=int(state.ui.rotation_deg or 0),
        font_size=str(state.ui.font_size or "medium"),
        focused_index=int(state.ui.focused_index or 0),
        menu_focused=str(state.ui.menu_focused.value if hasattr(state.ui.menu_focused, "value") else state.ui.menu_focused),
        settings_focused_index=int(state.ui.settings_focused_index or 0),
        settings_notice=str(state.ui.settings_notice or ""),
        partial_refresh_mode=str(state.ui.partial_refresh_mode or "balanced"),
        full_refresh_every=int(state.ui.full_refresh_every or 0),
        wifi_enabled=bool(state.ui.wifi_enabled),
        bluetooth_enabled=bool(state.ui.bluetooth_enabled),
        auto_sync_enabled=bool(state.ui.auto_sync_enabled),
        last_sync_at=int(float(state.ui.last_sync_at or 0.0)),
        timer_seconds=int(state.ui.timer_seconds or 0),
        timer_running=bool(state.ui.timer_running),
        timer_focused_index=int(state.ui.timer_focused_index or 0),
        widget_mode=str(state.ui.widget_mode.value if hasattr(state.ui.widget_mode, "value") else state.ui.widget_mode),
        weather_day_index=int(state.ui.weather_day_index or 0),
        weather_digest=tuple(
            (str(w.dow), str(w.icon), int(w.hi), int(w.lo), w.humidity, w.feels_like, w.wind_kmh, w.uv_index)
            for w in state.model.weather
        ),
        calendar_offset_days=int(state.ui.calendar_offset_days or 0),
        calendar_mode=str(state.ui.calendar_mode or "date"),
        calendar_selected_index=int(state.ui.calendar_selected_index or 0),
        reminders_digest=tuple((r.rid, bool(r.completed), str(r.title), str(r.right), str(r.category)) for r in state.model.reminders),
        memo_index=int(state.ui.memo_index or 0),
        voice_active=bool(state.ui.voice_active),
        voice_phase=str(state.ui.voice_phase or "idle"),
    )


def _screen_regions(screen: Screen, width: int, height: int) -> dict[str, Rect]:
    w = max(1, int(width))
    h = max(1, int(height))
    # Match home_kitchen.py defaults closely to reduce diff-fallback expansions.
    margin = 18
    ox0, oy0, ox1, oy1 = margin, margin, max(margin + 1, w - margin), max(margin + 1, h - margin)
    split_x = ox0 + int((ox1 - ox0) * 0.60)
    left_split = split_x
    if screen == Screen.SETTINGS:
        footer_h = 40
        return {
            "header": (24, 10, w - 24, 78),
            "rows": (24, 84, w - 24, max(84, h - footer_h - 2)),
            "footer": (24, max(0, h - footer_h - 1), w - 24, h),
        }
    if screen == Screen.TIMER:
        return {
            "header": (24, 10, w - 24, 74),
            "time_status": (64, 90, w - 64, max(90, h - 120)),
            "controls": (24, max(0, h - 100), w - 24, h),
        }
    if screen == Screen.MENU:
        cy = h // 2
        return {"pills": (40, max(0, cy - 56), w - 40, min(h, cy + 56))}
    if screen == Screen.WEATHER:
        y0 = 16
        y1 = h - 16
        total = max(100, y1 - y0)
        hero_h = int(total * 0.41)
        metric_h = int(total * 0.20)
        return {
            "hero": (20, y0, w - 20, y0 + hero_h),
            "metrics": (20, y0 + hero_h, w - 20, y0 + hero_h + metric_h),
            "forecast": (20, y0 + hero_h + metric_h, w - 20, y1),
        }
    if screen == Screen.CALENDAR:
        right_x = int(w * 0.45)
        return {
            "left_grid": (0, 82, right_x, h),
            "right_header": (right_x, 0, w, 96),
            "right_agenda": (right_x, 90, w, h),
        }
    # HOME / fallback
    return {
        "left_clock": (ox0, oy0, left_split, min(oy1, oy0 + int((oy1 - oy0) * 0.42))),
        "left_memo": (ox0, oy0 + int((oy1 - oy0) * 0.35), left_split, oy1),
        "left_weather": (ox0, oy0 + int((oy1 - oy0) * 0.22), left_split, oy0 + int((oy1 - oy0) * 0.62)),
        # Family board sits in the lower-left column; use a narrower inner rect to keep partial area small.
        "left_family_board": (
            ox0 + 20,
            oy0 + int((oy1 - oy0) * 0.52),
            max(ox0 + 28, left_split - 20),
            oy1,
        ),
        "right_list": (left_split, oy0, ox1, oy1),
    }


def _home_focus_row_rect(width: int, height: int, focus_index: int) -> Rect | None:
    # Approximate row geometry from app/ui/home_kitchen.py theme defaults.
    if int(focus_index) <= 0:
        return None

    w = max(1, int(width))
    h = max(1, int(height))
    margin = 18
    ox0, oy0, ox1, oy1 = margin, margin, max(margin + 1, w - margin), max(margin + 1, h - margin)
    split_x = ox0 + int((ox1 - ox0) * 0.60)
    right_pad = 22
    inner_x0 = split_x + 1 + right_pad
    inner_x1 = ox1 - right_pad

    if inner_x1 <= inner_x0:
        return None

    inv_start_y = oy0 + max(8, right_pad - 6) + 34
    inv_row_h = 40
    inv_max = 3
    shop_start_y = oy0 + int((oy1 - oy0) * 0.62)
    shop_row_h = 40
    row_h = 56

    pos = int(focus_index) - 1
    if pos < 0:
        return None
    if pos < inv_max:
        cy = inv_start_y + (pos * inv_row_h) + (inv_row_h // 2)
    else:
        cy = shop_start_y + ((pos - inv_max) * shop_row_h) + (shop_row_h // 2)

    y0 = max(oy0, cy - (row_h // 2))
    y1 = min(oy1, y0 + row_h)
    x0 = max(0, inner_x0 - 10)
    x1 = min(w, inner_x1 + 6)
    if x1 <= x0 or y1 <= y0:
        return None
    return (x0, y0, x1, y1)


def infer_dirty_rects(prev: UiSnapshot, curr: UiSnapshot, width: int, height: int) -> list[Rect]:
    rects, _ = infer_dirty_rects_with_reasons(prev, curr, width, height)
    return rects


def infer_dirty_rects_with_reasons(prev: UiSnapshot, curr: UiSnapshot, width: int, height: int) -> tuple[list[Rect], list[str]]:
    if prev.screen != curr.screen:
        return [], []
    if int(prev.rotation_deg) != int(curr.rotation_deg):
        return [], []

    regions = _screen_regions(curr.screen, width, height)
    rects: list[Rect] = []
    reasons: list[str] = []

    if curr.screen == Screen.SETTINGS:
        if prev.settings_focused_index != curr.settings_focused_index:
            rects.append(regions["rows"])
            reasons.append("settings.focus_move")
        if (
            prev.settings_notice != curr.settings_notice
            or prev.last_sync_at != curr.last_sync_at
        ):
            rects.append(regions["footer"])
            reasons.append("settings.footer_notice")
        if (
            prev.partial_refresh_mode != curr.partial_refresh_mode
            or prev.full_refresh_every != curr.full_refresh_every
            or prev.wifi_enabled != curr.wifi_enabled
            or prev.bluetooth_enabled != curr.bluetooth_enabled
            or prev.auto_sync_enabled != curr.auto_sync_enabled
        ):
            rects.append(regions["rows"])
            reasons.append("settings.value_change")
        return rects, reasons

    if curr.screen == Screen.TIMER:
        if prev.timer_focused_index != curr.timer_focused_index:
            rects.append(regions["controls"])
            reasons.append("timer.focus_move")
        if (
            prev.timer_seconds != curr.timer_seconds
            or prev.timer_running != curr.timer_running
            or prev.widget_mode != curr.widget_mode
        ):
            rects.append(regions["time_status"])
            reasons.append("timer.time_or_state")
        return rects, reasons

    if curr.screen == Screen.MENU:
        if prev.menu_focused != curr.menu_focused:
            rects.append(regions["pills"])
            reasons.append("menu.focus_move")
        return rects, reasons

    if curr.screen == Screen.WEATHER:
        if prev.weather_day_index != curr.weather_day_index or prev.weather_digest != curr.weather_digest:
            rects.extend([regions["hero"], regions["metrics"], regions["forecast"]])
            reasons.append("weather.day_or_data_change")
        return rects, reasons

    if curr.screen == Screen.CALENDAR:
        if (
            prev.calendar_offset_days != curr.calendar_offset_days
            or prev.calendar_mode != curr.calendar_mode
            or prev.reminders_digest != curr.reminders_digest
        ):
            rects.extend([regions["left_grid"], regions["right_header"], regions["right_agenda"]])
            reasons.append("calendar.date_or_mode_or_tasks")
            return rects, reasons
        if prev.calendar_selected_index != curr.calendar_selected_index:
            rects.append(regions["right_agenda"])
            reasons.append("calendar.agenda_focus_move")
        return rects, reasons

    # HOME and fallback.
    if prev.focused_index != curr.focused_index:
        prev_row = _home_focus_row_rect(width, height, prev.focused_index)
        curr_row = _home_focus_row_rect(width, height, curr.focused_index)
        if prev_row is not None and curr_row is not None:
            rects.append(prev_row)
            if curr_row != prev_row:
                rects.append(curr_row)
            reasons.append("home.focus_move_row")
        else:
            rects.append(regions["right_list"])
            reasons.append("home.focus_move")
        # Do not force a left-panel redraw on focus entering/leaving index 0.
        # In current kitchen renderer there is no persistent left focus ring by default.
    if prev.reminders_digest != curr.reminders_digest:
        prev_rids = tuple(str(r[0]) for r in prev.reminders_digest)
        curr_rids = tuple(str(r[0]) for r in curr.reminders_digest)
        if prev_rids == curr_rids:
            # Same row order: likely a click-toggle style change; update focused row only.
            prev_row = _home_focus_row_rect(width, height, prev.focused_index)
            curr_row = _home_focus_row_rect(width, height, curr.focused_index)
            if prev_row is not None:
                rects.append(prev_row)
            if curr_row is not None and curr_row != prev_row:
                rects.append(curr_row)
            if prev_row is None and curr_row is None:
                rects.append(regions["right_list"])
                reasons.append("home.reminder_change_fallback")
            else:
                reasons.append("home.reminder_row_update")
        else:
            # Delayed reorder moves multiple rows; refresh right panel region.
            rects.append(regions["right_list"])
            reasons.append("home.reminder_reorder")
    if prev.memo_index != curr.memo_index:
        rects.append(regions["left_family_board"])
        reasons.append("home.family_board_update")
    if prev.weather_digest != curr.weather_digest:
        rects.append(regions["left_weather"])
        reasons.append("home.weather_update")
    if (
        prev.timer_seconds != curr.timer_seconds
        or prev.timer_running != curr.timer_running
        or prev.widget_mode != curr.widget_mode
    ):
        rects.append(regions["left_clock"])
        reasons.append("home.clock_or_timer_state")
    if prev.voice_active != curr.voice_active or prev.voice_phase != curr.voice_phase:
        rects.append(regions["left_clock"])
        reasons.append("home.voice_overlay")
    return rects, reasons
