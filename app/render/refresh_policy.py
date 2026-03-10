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


def _normalized_right_angle(deg: int | float | str | None) -> int:
    try:
        value = int(deg or 0)
    except Exception:
        value = 0
    return ((value + 45) // 90 * 90) % 360


def _rotate_rect(rect: Rect, src_width: int, src_height: int, rotation_deg: int) -> Rect:
    rot = _normalized_right_angle(rotation_deg)
    if rot == 0:
        return rect

    x0, y0, x1, y1 = rect
    points = [
        (x0, y0),
        (x1, y0),
        (x1, y1),
        (x0, y1),
    ]

    rotated: list[tuple[int, int]] = []
    for x, y in points:
        if rot == 90:
            rotated.append((y, src_width - x))
        elif rot == 180:
            rotated.append((src_width - x, src_height - y))
        else:  # 270
            rotated.append((src_height - y, x))

    xs = [p[0] for p in rotated]
    ys = [p[1] for p in rotated]
    return (min(xs), min(ys), max(xs), max(ys))


def screen_partial_area_limit(screen: Screen, mode: str) -> float:
    base = mode_params(mode).partial_area_limit
    if screen in (Screen.LANDING, Screen.ONBOARDING):
        return max(0.70, min(base + 0.20, 0.92))
    if screen == Screen.TIMER:
        return min(0.95, base + 0.20)
    if screen == Screen.MEMO:
        # Memo click/expand frequently redraws a large content card.
        # Keep threshold high enough even in slow mode to avoid full-screen flashes.
        return max(0.72, min(base + 0.25, 0.88))
    if screen in (Screen.INVENTORY, Screen.REMINDERS):
        return max(0.60, min(base + 0.15, 0.80))
    if screen == Screen.MENU:
        return max(0.30, min(base, 0.55))
    if screen == Screen.CALENDAR:
        return max(0.58, min(base + 0.15, 0.82))
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
    except (TypeError, ValueError):
        value = 0
    if value <= 0:
        value = params.default_full_refresh_every

    if screen == Screen.TIMER:
        try:
            timer_override = int(timer_full_refresh_every_override or 0)
        except (TypeError, ValueError):
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
        try:
            budget = int(full_refresh_every or 0)
        except (TypeError, ValueError):
            budget = 0
        if budget > 0 and int(self.partial_count) >= budget:
            return "partial_budget"
        if self.last_full_refresh_ts > 0 and (float(now) - float(self.last_full_refresh_ts)) >= float(max_full_age_s):
            return "full_age"
        return ""


@dataclass(frozen=True)
class UiSnapshot:
    screen: Screen
    rotation_deg: int
    setup_completed: bool
    landing_rotate_seen: bool
    landing_confirm_seen: bool
    landing_voice_demo_index: int
    landing_voice_demo_cycles: int
    landing_status: str
    onboarding_step: str
    onboarding_focus_index: int
    onboarding_qr_focus_index: int
    onboarding_prefs_focus_index: int
    onboarding_voice_guide_focus_index: int
    onboarding_pair_token: str
    onboarding_pair_expires_at: int
    onboarding_status: str
    onboarding_voice_demo_heard: str
    onboarding_voice_demo_attempted: bool
    onboarding_voice_demo_case_index: int
    onboarding_voice_demo_pass_mask: int
    onboarding_voice_demo_action: str
    onboarding_voice_sample_text: str
    onboarding_voice_expected_action: str
    onboarding_wifi_ssid: str
    device_language: str
    device_timezone: str
    voice_locale: str
    font_size: str
    focused_index: int
    menu_focused: str
    menu_overlay_active: bool
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
    timer_alert_active: bool
    timer_alert_blink_on: bool
    timer_last_completed_seconds: int
    clock_minute_bucket: int
    widget_mode: str
    weather_day_index: int
    weather_digest: tuple
    calendar_digest: tuple
    calendar_offset_days: int
    calendar_mode: str
    calendar_selected_index: int
    reminders_digest: tuple
    memo_index: int
    memo_expanded: bool
    memos_digest: tuple
    list_focused_index: int
    voice_active: bool
    voice_phase: str


def build_ui_snapshot(state: AppState) -> UiSnapshot:
    return UiSnapshot(
        screen=state.ui.screen,
        rotation_deg=int(state.ui.rotation_deg or 0),
        setup_completed=bool(state.ui.setup_completed),
        landing_rotate_seen=bool(state.ui.landing_rotate_seen),
        landing_confirm_seen=bool(state.ui.landing_confirm_seen),
        landing_voice_demo_index=int(state.ui.landing_voice_demo_index or 0),
        landing_voice_demo_cycles=int(state.ui.landing_voice_demo_cycles or 0),
        landing_status=str(state.ui.landing_status or ""),
        onboarding_step=str(state.ui.onboarding_step or "start"),
        onboarding_focus_index=int(state.ui.onboarding_focus_index or 0),
        onboarding_qr_focus_index=int(state.ui.onboarding_qr_focus_index or 0),
        onboarding_prefs_focus_index=int(state.ui.onboarding_prefs_focus_index or 0),
        onboarding_voice_guide_focus_index=int(state.ui.onboarding_voice_guide_focus_index or 0),
        onboarding_pair_token=str(state.ui.onboarding_pair_token or ""),
        onboarding_pair_expires_at=int(float(state.ui.onboarding_pair_expires_at or 0.0)),
        onboarding_status=str(state.ui.onboarding_status or ""),
        onboarding_voice_demo_heard=str(state.ui.onboarding_voice_demo_heard or ""),
        onboarding_voice_demo_attempted=bool(state.ui.onboarding_voice_demo_attempted),
        onboarding_voice_demo_case_index=int(state.ui.onboarding_voice_demo_case_index or 0),
        onboarding_voice_demo_pass_mask=int(state.ui.onboarding_voice_demo_pass_mask or 0),
        onboarding_voice_demo_action=str(state.ui.onboarding_voice_demo_action or ""),
        onboarding_voice_sample_text=str(state.ui.onboarding_voice_sample_text or ""),
        onboarding_voice_expected_action=str(state.ui.onboarding_voice_expected_action or ""),
        onboarding_wifi_ssid=str(state.ui.onboarding_wifi_ssid or ""),
        device_language=str(state.ui.device_language or "en-US"),
        device_timezone=str(state.ui.device_timezone or "UTC"),
        voice_locale=str(state.ui.voice_locale or "en-US"),
        font_size=str(state.ui.font_size or "medium"),
        focused_index=int(state.ui.focused_index or 0),
        menu_focused=str(state.ui.menu_focused.value if hasattr(state.ui.menu_focused, "value") else state.ui.menu_focused),
        menu_overlay_active=bool(state.ui.menu_overlay_active),
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
        timer_alert_active=bool(state.ui.timer_alert_active),
        timer_alert_blink_on=bool(state.ui.timer_alert_blink_on),
        timer_last_completed_seconds=int(state.ui.timer_last_completed_seconds or 0),
        clock_minute_bucket=int(state.ui.clock_minute_bucket or 0),
        widget_mode=str(state.ui.widget_mode.value if hasattr(state.ui.widget_mode, "value") else state.ui.widget_mode),
        weather_day_index=int(state.ui.weather_day_index or 0),
        weather_digest=tuple(
            (str(w.dow), str(w.icon), int(w.hi), int(w.lo), w.humidity, w.feels_like, w.wind_kmh, w.uv_index)
            for w in state.model.weather
        ),
        calendar_digest=tuple(
            (
                str(c.eid),
                str(c.title),
                str(c.when),
                str(getattr(c, "date_iso", "")),
            )
            for c in state.model.calendar
        ),
        calendar_offset_days=int(state.ui.calendar_offset_days or 0),
        calendar_mode=str(state.ui.calendar_mode or "date"),
        calendar_selected_index=int(state.ui.calendar_selected_index or 0),
        reminders_digest=tuple((r.rid, bool(r.completed), str(r.title), str(r.right), str(r.category)) for r in state.model.reminders),
        memo_index=int(state.ui.memo_index or 0),
        memo_expanded=bool(state.ui.memo_expanded),
        memos_digest=tuple((m.mid, str(m.text), str(m.author), int(float(m.timestamp)), bool(m.is_new)) for m in state.model.memos),
        list_focused_index=int(state.ui.list_focused_index or 0),
        voice_active=bool(state.ui.voice_active),
        voice_phase=str(state.ui.voice_phase or "idle"),
    )


def _voice_overlay_region(width: int, height: int, *, rotation_deg: int = 0) -> Rect:
    w = max(1, int(width))
    h = max(1, int(height))
    margin = 14
    zone_w = min(380, max(300, int(w * 0.46)))
    zone_w = max(220, min(zone_w, max(220, w - margin * 2)))
    lane_h = 29

    x0 = margin
    y1 = h - margin
    y0 = max(margin, y1 - lane_h)
    x1 = x0 + zone_w
    rect = (x0, y0 - 1, x1, y1 + 1)

    if int(rotation_deg or 0) == 180:
        rx0, ry0, rx1, ry1 = rect
        rect = (w - rx1, h - ry1, w - rx0, h - ry0)
    return rect


def _screen_regions(screen: Screen, width: int, height: int, *, rotation_deg: int = 0) -> dict[str, Rect]:
    rot = _normalized_right_angle(rotation_deg)
    if screen in (Screen.LANDING, Screen.ONBOARDING) and rot in (90, 270):
        w = max(1, int(height))
        h = max(1, int(width))
    else:
        w = max(1, int(width))
        h = max(1, int(height))
    # Match home_kitchen.py defaults closely to reduce diff-fallback expansions.
    margin = 18
    ox0, oy0, ox1, oy1 = margin, margin, max(margin + 1, w - margin), max(margin + 1, h - margin)
    split_x = ox0 + int((ox1 - ox0) * 0.60)
    left_split = split_x
    if screen == Screen.LANDING:
        content_x0 = 34
        content_x1 = w - 34
        mid_y = h // 2
        regions = {
            "full": (0, 0, w, h),
            "tips": (content_x0, 96, content_x1, min(h, 260)),
            "language": (content_x0, max(0, mid_y + 12), content_x1, min(h, mid_y + 118)),
            "status_button": (content_x0, max(0, h - 122), content_x1, h - 18),
        }
        if rot in (90, 270):
            return {
                key: _rotate_rect(value, w, h, rot)
                for key, value in regions.items()
            }
        return regions
    if screen == Screen.ONBOARDING:
        regions = {
            "full": (0, 0, w, h),
            "start_choices": (max(0, (w - 430) // 2) - 8, 210, min(w, (w + 430) // 2) + 8, 386),
            "start_footer": (32, max(0, h - 76), w - 32, h),
            "qr_code": (46, 126, min(w, 342), min(h, 420)),
            "qr_info": (356, 136, w - 24, min(h, 334)),
            "qr_buttons": (356, max(0, h - 122), w - 18, h - 18),
            "prefs_rows": (38, 146, w - 38, max(146, h - 92)),
            "prefs_next": (36, max(0, h - 88), w - 36, h - 18),
            "voice_top": (32, 36, w - 32, 224),
            "voice_result": (32, 220, w - 32, 346),
            "voice_status": (32, 342, w - 32, max(342, h - 80)),
            "voice_action": (max(0, (w - 360) // 2) - 12, max(0, h - 74), min(w, (w + 360) // 2) + 12, h - 18),
            "done_summary": (36, 50, w - 36, max(50, h - 112)),
            "done_button": (max(0, (w - 320) // 2) - 12, max(0, h - 112), min(w, (w + 320) // 2) + 12, h - 34),
        }
        if rot in (90, 270):
            return {
                key: _rotate_rect(value, w, h, rot)
                for key, value in regions.items()
            }
        return regions
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
    if screen == Screen.MEMO:
        return {
            "header": (16, 10, w - 16, 76),
            "card": (20, 80, w - 20, max(80, h - 60)),
            "footer": (16, max(0, h - 58), w - 16, h),
        }
    if screen in (Screen.INVENTORY, Screen.REMINDERS):
        left = 24
        right = w - 24
        content_top = 104
        footer_y = h - 40
        content_bottom = footer_y - 6
        split_x = left + int((right - left) * 0.40)
        return {
            "header": (16, 10, w - 16, 76),
            "summary": (20, 76, w - 20, 104),
            "list_left": (left, content_top, max(left + 1, split_x - 3), content_bottom),
            "list_right": (min(right - 1, split_x + 3), content_top, right, content_bottom),
            "divider": (max(left, split_x - 2), content_top, min(right, split_x + 2), content_bottom),
            "footer": (16, max(0, h - 44), w - 16, h),
        }
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
            "left_panel": (0, 0, right_x, h),
            "right_panel": (right_x, 0, w, h),
            "right_agenda": (right_x, 90, w, h),
        }
    # HOME / fallback
    menu_x0, menu_y0, menu_x1, menu_y1 = _home_menu_overlay_region(w, h)
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
        "left_focus_indicator": (
            max(ox0, left_split - 34),
            oy0 + 4,
            max(ox0 + 1, left_split - 2),
            oy0 + 36,
        ),
        "voice_overlay": _voice_overlay_region(w, h, rotation_deg=rotation_deg),
        "home_menu_overlay": (menu_x0, menu_y0, menu_x1, menu_y1),
        "right_list": (left_split, oy0, ox1, oy1),
    }


def _home_menu_overlay_region(width: int, height: int) -> Rect:
    w = max(1, int(width))
    h = max(1, int(height))
    gap = 12
    pill_h = 56
    pill_w = 116
    count = 5
    total_w = (count * pill_w) + ((count - 1) * gap)
    x0 = max(16, (w - total_w) // 2 - 14)
    x1 = min(w - 16, x0 + total_w + 28)
    cy = h // 2
    y0 = max(80, cy - 46)
    y1 = min(h - 80, y0 + 102)
    return (x0, y0, x1, y1)


def _home_visible_section_counts(reminders_digest: tuple, *, inv_max: int = 3, rem_max: int = 5) -> tuple[int, int]:
    inv_count = 0
    rem_count = 0
    for item in reminders_digest or ():
        try:
            completed = bool(item[1])
            category = str(item[4] or "")
        except Exception:
            continue
        if completed:
            continue
        if category == "fridge":
            if inv_count < inv_max:
                inv_count += 1
        else:
            if rem_count < rem_max:
                rem_count += 1
    return inv_count, rem_count


def _list_inventory_count(reminders_digest: tuple) -> int:
    count = 0
    for item in reminders_digest or ():
        try:
            category = str(item[4] or "")
        except Exception:
            continue
        if category == "fridge":
            count += 1
    return count


def _list_focus_section(list_focused_index: int, reminders_digest: tuple) -> str:
    total = len(reminders_digest or ())
    if total <= 0:
        return "none"
    inv_count = _list_inventory_count(reminders_digest)
    idx = max(0, min(int(list_focused_index or 0), total - 1))
    return "inventory" if idx < inv_count else "reminders"


def _home_focus_row_rect(width: int, height: int, focus_index: int, reminders_digest: tuple) -> Rect | None:
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
    inv_count, _ = _home_visible_section_counts(reminders_digest, inv_max=3, rem_max=5)
    inv_header_cy = oy0 + max(8, right_pad - 6) + (inv_row_h // 2)
    shop_start_y = oy0 + int((oy1 - oy0) * 0.62)
    shop_row_h = 40
    shop_header_cy = shop_start_y - (shop_row_h // 2)
    row_h = 56

    pos = int(focus_index) - 1
    if pos < 0:
        return None

    if pos == 0:
        cy = inv_header_cy
    else:
        pos -= 1

    if pos >= 0 and pos < inv_count:
        cy = inv_start_y + (pos * inv_row_h) + (inv_row_h // 2)
    elif pos >= inv_count:
        pos -= inv_count
        if pos == 0:
            cy = shop_header_cy
        else:
            pos -= 1
            cy = shop_start_y + (max(0, pos) * shop_row_h) + (shop_row_h // 2)
    else:
        cy = inv_header_cy

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
        w = max(1, int(width))
        h = max(1, int(height))
        if curr.screen in (Screen.LANDING, Screen.ONBOARDING):
            return [(0, 0, w, h)], [f"screen.change_to_{curr.screen.value}"]
        if curr.screen == Screen.MEMO:
            mid = w // 2
            return [(0, 0, mid, h), (mid, 0, w, h)], ["screen.change_to_memo"]
        if curr.screen in (Screen.INVENTORY, Screen.REMINDERS):
            split = max(1, min(w - 1, int(w * 0.40)))
            return [(0, 0, split, h), (split, 0, w, h)], ["screen.change_to_list"]
        if curr.screen == Screen.CALENDAR:
            split = max(1, min(w - 1, int(w * 0.45)))
            return [(0, 0, split, h), (split, 0, w, h)], ["screen.change_to_calendar"]
        return [], []
    if int(prev.rotation_deg) != int(curr.rotation_deg):
        return [], []

    regions = _screen_regions(curr.screen, width, height, rotation_deg=curr.rotation_deg)
    rects: list[Rect] = []
    reasons: list[str] = []

    if curr.screen == Screen.LANDING:
        if (
            prev.setup_completed != curr.setup_completed
            or prev.screen != curr.screen
        ):
            rects.append(regions["full"])
            reasons.append("landing.state_change")
            return rects, reasons
        if (
            prev.landing_rotate_seen != curr.landing_rotate_seen
            or prev.landing_confirm_seen != curr.landing_confirm_seen
            or prev.device_language != curr.device_language
            or prev.voice_locale != curr.voice_locale
        ):
            rects.extend([regions["language"], regions["status_button"]])
            reasons.append("landing.state_change")
            return rects, reasons
        if (
            prev.landing_voice_demo_index != curr.landing_voice_demo_index
            or prev.landing_voice_demo_cycles != curr.landing_voice_demo_cycles
            or prev.landing_status != curr.landing_status
        ):
            rects.extend([regions["tips"], regions["status_button"]])
            reasons.append("landing.demo_or_status")
            return rects, reasons
        if prev.onboarding_pair_expires_at != curr.onboarding_pair_expires_at:
            rects.append(regions["status_button"])
            reasons.append("landing.footer_countdown")
        return rects, reasons

    if curr.screen == Screen.ONBOARDING:
        if prev.onboarding_step != curr.onboarding_step:
            rects.append(regions["full"])
            reasons.append("onboarding.step_change")
            return rects, reasons
        if curr.onboarding_step == "start" and prev.onboarding_focus_index != curr.onboarding_focus_index:
            rects.append(regions["start_choices"])
            reasons.append("onboarding.start_focus")
            return rects, reasons
        if curr.onboarding_step == "pair_qr":
            if prev.onboarding_qr_focus_index != curr.onboarding_qr_focus_index:
                rects.append(regions["qr_buttons"])
                reasons.append("onboarding.qr_focus")
            if (
                prev.onboarding_pair_token != curr.onboarding_pair_token
                or prev.onboarding_pair_expires_at != curr.onboarding_pair_expires_at
                or prev.onboarding_status != curr.onboarding_status
            ):
                rects.extend([regions["qr_code"], regions["qr_info"], regions["qr_buttons"]])
                reasons.append("onboarding.qr_payload")
            return rects, reasons
        if curr.onboarding_step == "prefs":
            if prev.onboarding_prefs_focus_index != curr.onboarding_prefs_focus_index:
                if 3 in (prev.onboarding_prefs_focus_index, curr.onboarding_prefs_focus_index):
                    rects.extend([regions["prefs_rows"], regions["prefs_next"]])
                else:
                    rects.append(regions["prefs_rows"])
                reasons.append("onboarding.prefs_focus")
            if (
                prev.device_language != curr.device_language
                or prev.voice_locale != curr.voice_locale
                or prev.device_timezone != curr.device_timezone
                or prev.auto_sync_enabled != curr.auto_sync_enabled
                or prev.onboarding_wifi_ssid != curr.onboarding_wifi_ssid
            ):
                rects.append(regions["prefs_rows"])
                reasons.append("onboarding.prefs_value")
            return rects, reasons
        if curr.onboarding_step == "voice_guide":
            if prev.onboarding_voice_guide_focus_index != curr.onboarding_voice_guide_focus_index:
                rects.append(regions["voice_action"])
                reasons.append("onboarding.voice_focus")
            if (
                prev.onboarding_status != curr.onboarding_status
                or prev.onboarding_voice_demo_heard != curr.onboarding_voice_demo_heard
                or prev.onboarding_voice_demo_attempted != curr.onboarding_voice_demo_attempted
                or prev.onboarding_voice_demo_case_index != curr.onboarding_voice_demo_case_index
                or prev.onboarding_voice_demo_pass_mask != curr.onboarding_voice_demo_pass_mask
                or prev.onboarding_voice_demo_action != curr.onboarding_voice_demo_action
                or prev.onboarding_voice_sample_text != curr.onboarding_voice_sample_text
                or prev.onboarding_voice_expected_action != curr.onboarding_voice_expected_action
            ):
                rects.extend(
                    [
                        regions["voice_top"],
                        regions["voice_result"],
                        regions["voice_status"],
                        regions["voice_action"],
                    ]
                )
                reasons.append("onboarding.voice_demo")
            return rects, reasons
        if (
            prev.device_language != curr.device_language
            or prev.voice_locale != curr.voice_locale
            or prev.device_timezone != curr.device_timezone
            or prev.auto_sync_enabled != curr.auto_sync_enabled
            or prev.onboarding_wifi_ssid != curr.onboarding_wifi_ssid
        ):
            rects.extend([regions["done_summary"], regions["done_button"]])
            reasons.append("onboarding.done_summary")
        return rects, reasons

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
            or prev.timer_alert_active != curr.timer_alert_active
            or prev.timer_alert_blink_on != curr.timer_alert_blink_on
            or prev.timer_last_completed_seconds != curr.timer_last_completed_seconds
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

    if curr.screen == Screen.MEMO:
        if prev.memo_index != curr.memo_index:
            rects.extend([regions["header"], regions["card"]])
            reasons.append("memo.focus_move")
            return rects, reasons
        if prev.memo_expanded != curr.memo_expanded:
            rects.extend([regions["card"], regions["footer"]])
            reasons.append("memo.expand_toggle")
            return rects, reasons
        if prev.memos_digest != curr.memos_digest:
            rects.extend([regions["header"], regions["card"]])
            reasons.append("memo.data_change")
        return rects, reasons

    if curr.screen in (Screen.INVENTORY, Screen.REMINDERS):
        if prev.list_focused_index != curr.list_focused_index:
            prev_section = _list_focus_section(prev.list_focused_index, prev.reminders_digest)
            curr_section = _list_focus_section(curr.list_focused_index, curr.reminders_digest)
            if prev_section == "inventory" and curr_section == "inventory":
                rects.append(regions["list_left"])
            elif prev_section == "reminders" and curr_section == "reminders":
                rects.append(regions["list_right"])
            else:
                rects.extend([regions["list_left"], regions["list_right"], regions["divider"]])
            reasons.append("list.focus_move")
            return rects, reasons
        if prev.reminders_digest != curr.reminders_digest:
            rects.extend([regions["summary"], regions["list_left"], regions["list_right"], regions["divider"]])
            reasons.append("list.data_change")
            return rects, reasons
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
            or prev.calendar_digest != curr.calendar_digest
        ):
            rects.extend([regions["left_panel"], regions["right_panel"]])
            reasons.append("calendar.date_or_mode_or_data")
            return rects, reasons
        if prev.calendar_selected_index != curr.calendar_selected_index:
            rects.append(regions["right_agenda"])
            reasons.append("calendar.agenda_focus_move")
        return rects, reasons

    # HOME and fallback.
    if prev.menu_overlay_active != curr.menu_overlay_active:
        rects.append(regions["home_menu_overlay"])
        reasons.append("home.menu_overlay_toggle")
    if curr.menu_overlay_active and prev.menu_focused != curr.menu_focused:
        rects.append(regions["home_menu_overlay"])
        reasons.append("home.menu_overlay_focus")

    if prev.focused_index != curr.focused_index:
        prev_row = _home_focus_row_rect(width, height, prev.focused_index, prev.reminders_digest)
        curr_row = _home_focus_row_rect(width, height, curr.focused_index, curr.reminders_digest)
        if prev_row is not None and curr_row is not None:
            rects.append(prev_row)
            if curr_row != prev_row:
                rects.append(curr_row)
            reasons.append("home.focus_move_row")
        elif prev_row is not None and curr_row is None:
            rects.append(prev_row)
            rects.append(regions["left_focus_indicator"])
            reasons.append("home.focus_to_left_panel")
        elif prev_row is None and curr_row is not None:
            rects.append(curr_row)
            rects.append(regions["left_focus_indicator"])
            reasons.append("home.focus_from_left_panel")
        else:
            rects.append(regions["left_focus_indicator"])
            reasons.append("home.focus_left_panel_only")
        # Do not force a left-panel redraw on focus entering/leaving index 0.
        # In current kitchen renderer there is no persistent left focus ring by default.
    if prev.reminders_digest != curr.reminders_digest:
        prev_rids = tuple(str(r[0]) for r in prev.reminders_digest)
        curr_rids = tuple(str(r[0]) for r in curr.reminders_digest)
        if prev_rids == curr_rids:
            # Same row order: likely a click-toggle style change; update focused row only.
            prev_row = _home_focus_row_rect(width, height, prev.focused_index, prev.reminders_digest)
            curr_row = _home_focus_row_rect(width, height, curr.focused_index, curr.reminders_digest)
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
        or prev.clock_minute_bucket != curr.clock_minute_bucket
        or prev.widget_mode != curr.widget_mode
    ):
        rects.append(regions["left_clock"])
        reasons.append("home.clock_or_timer_state")
    if prev.voice_active != curr.voice_active or prev.voice_phase != curr.voice_phase:
        rects.append(regions["voice_overlay"])
        reasons.append("home.voice_overlay")
    return rects, reasons
