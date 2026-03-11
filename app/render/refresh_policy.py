from __future__ import annotations

from datetime import date, timedelta
from dataclasses import dataclass, field
from typing import Iterable

from app.core.settings_schema import SETTINGS_GROUPS, SETTINGS_ORDER
from app.core.state import AppState, Screen
from app.ui.home_kitchen_geometry import (
    closed_box_to_rect,
    home_landscape_header_focus_box,
    home_portrait_header_focus_source_box_for_panel,
)
from app.ui.menu import home_menu_overlay_rect

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
    kitchen_focus_rid_override: str
    home_hidden_rids: tuple[str, ...]
    kitchen_visible_rids: tuple[str, ...]
    kitchen_visible_layout: str
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
        kitchen_focus_rid_override=str(state.ui.kitchen_focus_rid_override or ""),
        home_hidden_rids=tuple(str(rid) for rid in getattr(state.ui, "home_hidden_rids", []) if str(rid or "").strip()),
        kitchen_visible_rids=tuple(str(rid) for rid in getattr(state.ui, "kitchen_visible_rids", []) if str(rid or "").strip()),
        kitchen_visible_layout=str(getattr(state.ui, "kitchen_visible_layout", "") or ""),
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


def _normalized_right_angle(raw) -> int:
    try:
        deg = int(raw or 0)
    except (TypeError, ValueError):
        deg = 0
    return (((deg % 360) + 45) // 90 * 90) % 360


def _transform_source_rect(rect: Rect, src_width: int, src_height: int, rotation_deg: int) -> Rect | None:
    clipped = _clip_rect(rect, src_width, src_height)
    if clipped is None:
        return None
    x0, y0, x1, y1 = clipped
    rot = _normalized_right_angle(rotation_deg)
    if rot == 90:
        return (y0, src_width - x1, y1, src_width - x0)
    if rot == 180:
        return (src_width - x1, src_height - y1, src_width - x0, src_height - y0)
    if rot == 270:
        return (src_height - y1, x0, src_height - y0, x1)
    return clipped


def _home_portrait_source_metrics(width: int, height: int) -> dict[str, int]:
    src_w = max(1, int(height))
    src_h = max(1, int(width))

    margin = 8
    pad = 8
    sec_gap = 4
    header_h_ratio = 0.21
    memo_h_ratio = 0.25
    min_list_h = 220
    header_col_gap = 16
    weather_col_w = 156
    list_split_ratio = 0.48
    shop_min_h = 104
    list_bottom_reserve = 20
    voice_margin = 14
    voice_lane_h = 29
    focus_pad_x = 6
    focus_pad_y = 4
    inv_header_gap = 20
    inv_row_h = 36
    shop_header_gap = 18
    shop_row_h = 36
    header_text_h = 16

    x0, y0, x1, y1 = margin, margin, src_w - margin, src_h - margin
    inner_h = max(1, y1 - y0)
    header_h = max(160, int(inner_h * header_h_ratio))
    memo_h = max(188, int(inner_h * memo_h_ratio))
    if header_h + memo_h + sec_gap * 2 + min_list_h > inner_h:
        overflow = header_h + memo_h + sec_gap * 2 + min_list_h - inner_h
        memo_h = max(150, memo_h - overflow)

    header_y0 = y0
    header_y1 = min(y1 - sec_gap * 2 - min_list_h, header_y0 + header_h)
    memo_y0 = header_y1 + sec_gap
    memo_y1 = min(y1 - sec_gap - min_list_h, memo_y0 + memo_h)
    list_y0 = memo_y1 + sec_gap
    list_y1 = y1

    hx0, hx1 = x0 + pad, x1 - pad
    hy0 = header_y0 + pad
    weather_w = min(weather_col_w, max(120, int((hx1 - hx0) * 0.36)))
    left_x0 = hx0
    left_x1 = max(left_x0 + 120, hx1 - weather_w - header_col_gap)
    weather_x0 = left_x1 + header_col_gap
    weather_x1 = hx1

    lx0, lx1 = x0 + pad, x1 - pad
    voice_guard = max(0, voice_margin + voice_lane_h - margin - pad + 4)
    ly0 = list_y0 + pad
    ly1 = list_y1 - pad - max(list_bottom_reserve, voice_guard)
    if ly1 <= ly0:
        ly1 = ly0 + 1
    list_h = max(80, ly1 - ly0)
    inv_zone_bottom = min(ly1 - max(72, shop_min_h), ly0 + max(96, int(list_h * list_split_ratio)))
    inv_header_y = ly0 + max(8, header_text_h // 2 + 2)
    inv_row_y = inv_header_y + inv_header_gap

    return {
        "src_w": src_w,
        "src_h": src_h,
        "x0": x0,
        "y0": y0,
        "x1": x1,
        "y1": y1,
        "pad": pad,
        "header_y0": header_y0,
        "header_y1": header_y1,
        "memo_y0": memo_y0,
        "memo_y1": memo_y1,
        "left_x0": left_x0,
        "left_x1": left_x1,
        "weather_x0": weather_x0,
        "weather_x1": weather_x1,
        "hy0": hy0,
        "lx0": lx0,
        "lx1": lx1,
        "ly0": ly0,
        "ly1": ly1,
        "inv_zone_bottom": inv_zone_bottom,
        "inv_header_y": inv_header_y,
        "inv_row_y": inv_row_y,
        "inv_row_h": inv_row_h,
        "shop_header_gap": shop_header_gap,
        "shop_row_h": shop_row_h,
        "focus_pad_x": focus_pad_x,
        "focus_pad_y": focus_pad_y,
    }


def _home_portrait_rendered_sections(
    reminders_digest: tuple,
    *,
    hidden_rids: tuple[str, ...] = (),
    inv_max: int = 4,
    shop_max: int = 5,
) -> tuple[tuple[tuple, ...], tuple[tuple, ...]]:
    hidden = {str(rid) for rid in hidden_rids if str(rid or "").strip()}
    fridge: list[tuple] = []
    shop: list[tuple] = []
    for item in reminders_digest or ():
        try:
            rid = str(item[0] or "")
            category = str(item[4] or "")
        except Exception:
            continue
        if rid and rid in hidden:
            continue
        if category == "fridge":
            if len(fridge) < inv_max:
                fridge.append(item)
        else:
            if len(shop) < shop_max:
                shop.append(item)
    return tuple(fridge), tuple(shop)


def _home_portrait_focus_queue_rids(
    reminders_digest: tuple,
    *,
    hidden_rids: tuple[str, ...] = (),
    inv_max: int = 4,
    shop_max: int = 5,
) -> list[str]:
    fridge_rows, shop_rows = _home_portrait_rendered_sections(
        reminders_digest,
        hidden_rids=hidden_rids,
        inv_max=inv_max,
        shop_max=shop_max,
    )
    queue: list[str] = []
    for item in fridge_rows + shop_rows:
        queue.append(str(item[0]))
    return queue


def _home_portrait_effective_focus_rid(snapshot: UiSnapshot) -> str:
    if int(snapshot.focused_index or 0) <= 1:
        return ""

    hold_rid = str(snapshot.kitchen_focus_rid_override or "").strip()
    fridge_rows, shop_rows = _home_portrait_rendered_sections(
        snapshot.reminders_digest,
        hidden_rids=snapshot.home_hidden_rids,
    )
    rendered_rids = {str(item[0]) for item in fridge_rows + shop_rows}
    if hold_rid and hold_rid in rendered_rids:
        return hold_rid

    queue = _home_portrait_focus_queue_rids(
        snapshot.reminders_digest,
        hidden_rids=snapshot.home_hidden_rids,
    )
    pos = int(snapshot.focused_index or 0) - 2
    if 0 <= pos < len(queue):
        return queue[pos]
    return ""


def _home_portrait_row_source_rect(
    width: int,
    height: int,
    *,
    reminders_digest: tuple,
    focus_rid: str,
    hidden_rids: tuple[str, ...] = (),
) -> Rect | None:
    rid = str(focus_rid or "").strip()
    if not rid:
        return None

    metrics = _home_portrait_source_metrics(width, height)
    fridge_rows, shop_rows = _home_portrait_rendered_sections(reminders_digest, hidden_rids=hidden_rids)
    fx0 = metrics["lx0"] - metrics["focus_pad_x"]
    fx1 = metrics["lx1"] + metrics["focus_pad_x"]

    for idx, item in enumerate(fridge_rows):
        if str(item[0]) != rid:
            continue
        row_y = metrics["inv_row_y"] + idx * metrics["inv_row_h"]
        return (
            fx0,
            row_y + metrics["focus_pad_y"],
            fx1,
            row_y + metrics["inv_row_h"] - metrics["focus_pad_y"],
        )

    shop_header_y = max(
        metrics["inv_zone_bottom"],
        metrics["inv_row_y"] + len(fridge_rows) * metrics["inv_row_h"] + 8,
    )
    shop_row_y = shop_header_y + metrics["shop_header_gap"]
    for idx, item in enumerate(shop_rows):
        if str(item[0]) != rid:
            continue
        row_y = shop_row_y + idx * metrics["shop_row_h"]
        return (
            fx0,
            row_y + metrics["focus_pad_y"],
            fx1,
            row_y + metrics["shop_row_h"] - metrics["focus_pad_y"],
        )
    return None


def _home_portrait_focus_row_rect(
    width: int,
    height: int,
    *,
    rotation_deg: int,
    reminders_digest: tuple,
    focus_rid: str,
    hidden_rids: tuple[str, ...] = (),
) -> Rect | None:
    metrics = _home_portrait_source_metrics(width, height)
    source_box = _home_portrait_row_source_rect(
        width,
        height,
        reminders_digest=reminders_digest,
        focus_rid=focus_rid,
        hidden_rids=hidden_rids,
    )
    if source_box is None:
        return None
    source_rect = closed_box_to_rect(source_box, outline_width=1, extra_pad=7)
    if source_rect is None:
        return None
    return _transform_source_rect(source_rect, metrics["src_w"], metrics["src_h"], rotation_deg)


def _home_portrait_header_focus_rect(
    width: int,
    height: int,
    *,
    rotation_deg: int,
    kind: str,
    weather_digest: tuple,
) -> Rect | None:
    metrics = _home_portrait_source_metrics(width, height)
    source_box = home_portrait_header_focus_source_box_for_panel(
        width,
        height,
        kind=kind,
        has_weather_data=bool(weather_digest),
        has_humidity=bool(weather_digest and weather_digest[0][4] is not None),
    )
    source_rect = closed_box_to_rect(source_box, outline_width=1)
    if source_rect is None:
        return None
    return _transform_source_rect(source_rect, metrics["src_w"], metrics["src_h"], rotation_deg)


def _home_portrait_section_rect(
    width: int,
    height: int,
    *,
    rotation_deg: int,
    section: str,
    inventory_rows: int,
    shopping_rows: int,
) -> Rect | None:
    metrics = _home_portrait_source_metrics(width, height)
    fx0 = metrics["lx0"] - metrics["focus_pad_x"]
    fx1 = metrics["lx1"] + metrics["focus_pad_x"]

    if section == "inventory":
        y0 = metrics["inv_header_y"] - 12
        y1 = metrics["inv_row_y"] + max(0, inventory_rows) * metrics["inv_row_h"]
        y1 = max(y0 + 16, min(metrics["inv_zone_bottom"], y1))
    elif section == "shopping":
        shop_header_y = max(
            metrics["inv_zone_bottom"],
            metrics["inv_row_y"] + max(0, inventory_rows) * metrics["inv_row_h"] + 8,
        )
        shop_row_y = shop_header_y + metrics["shop_header_gap"]
        y0 = shop_header_y - 12
        y1 = shop_row_y + max(0, shopping_rows) * metrics["shop_row_h"]
        y1 = max(y0 + 16, min(metrics["ly1"], y1))
    else:
        return None

    return _transform_source_rect((fx0, y0, fx1, y1), metrics["src_w"], metrics["src_h"], rotation_deg)


def _home_portrait_regions(width: int, height: int, *, rotation_deg: int) -> dict[str, Rect | None]:
    metrics = _home_portrait_source_metrics(width, height)
    header_clock = _transform_source_rect(
        (metrics["left_x0"], max(0, metrics["hy0"] - 16), metrics["left_x1"], metrics["header_y1"]),
        metrics["src_w"],
        metrics["src_h"],
        rotation_deg,
    )
    header_weather = _transform_source_rect(
        (metrics["weather_x0"], max(0, metrics["hy0"] - 16), metrics["weather_x1"], metrics["header_y1"]),
        metrics["src_w"],
        metrics["src_h"],
        rotation_deg,
    )
    memo = _transform_source_rect(
        (metrics["x0"] + metrics["pad"], metrics["memo_y0"] + metrics["pad"], metrics["x1"] - metrics["pad"], metrics["memo_y1"] - metrics["pad"]),
        metrics["src_w"],
        metrics["src_h"],
        rotation_deg,
    )
    list_all = _transform_source_rect(
        (
            metrics["lx0"] - metrics["focus_pad_x"],
            metrics["ly0"],
            metrics["lx1"] + metrics["focus_pad_x"],
            metrics["ly1"],
        ),
        metrics["src_w"],
        metrics["src_h"],
        rotation_deg,
    )
    menu_overlay_source = home_menu_overlay_rect(metrics["src_w"], metrics["src_h"])
    menu_overlay = _transform_source_rect(
        menu_overlay_source,
        metrics["src_w"],
        metrics["src_h"],
        rotation_deg,
    )
    voice_source = _voice_overlay_region(metrics["src_w"], metrics["src_h"], rotation_deg=0)
    voice_overlay = _transform_source_rect(voice_source, metrics["src_w"], metrics["src_h"], rotation_deg)
    return {
        "header_clock": header_clock,
        "header_weather": header_weather,
        "memo": memo,
        "list_all": list_all,
        "menu_overlay": menu_overlay,
        "voice_overlay": voice_overlay,
    }


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
            "panel": (18, 18, w - 18, h - 18),
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
            "panel": (18, 18, w - 18, h - 18),
            "start_choices": (max(0, (w - 430) // 2) - 8, 210, min(w, (w + 430) // 2) + 8, 386),
            "start_footer": (32, max(0, h - 76), w - 32, h),
            "qr_code": (46, 126, min(w, 342), min(h, 420)),
            "qr_info": (356, 136, w - 24, min(h, 334)),
            "qr_buttons": (356, max(0, h - 122), w - 18, h - 18),
            "prefs_meta": (38, 118, w - 38, 150),
            "prefs_rows": (38, 146, w - 38, max(146, h - 92)),
            "prefs_next": (36, max(0, h - 88), w - 36, h - 18),
            "prefs_panel": (36, 142, w - 36, h - 18),
            "voice_top": (32, 36, w - 32, 224),
            "voice_result": (32, 220, w - 32, 346),
            "voice_status": (32, 342, w - 32, max(342, h - 80)),
            "voice_action": (max(0, (w - 360) // 2) - 12, max(0, h - 74), min(w, (w + 360) // 2) + 12, h - 18),
            "voice_panel": (30, 32, w - 30, h - 14),
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
        src_w, src_h = _screen_source_size(width, height, rotation_deg)
        source_regions = {
            "header": (24, 10, max(25, src_w - 24), 74),
            # Keep generous margins so RUNNING/PAUSED baseline and timer glyph antialiasing
            # are fully covered during partial updates (including rotated layouts).
            "time_status": (56, 82, max(57, src_w - 56), max(83, src_h - 84)),
            "controls": (24, max(0, src_h - 100), max(25, src_w - 24), src_h),
        }
        if rot in (90, 180, 270):
            out: dict[str, Rect] = {}
            for key, rect in source_regions.items():
                transformed = _transform_source_rect(rect, src_w, src_h, rot)
                if transformed is not None:
                    out[key] = transformed
            return out or {"time_status": (0, 0, w, h)}
        return source_regions
    if screen == Screen.MENU:
        cy = h // 2
        return {"pills": (40, max(0, cy - 56), w - 40, min(h, cy + 56))}
    if screen == Screen.MEMO:
        src_w, src_h = _screen_source_size(width, height, rotation_deg)
        source_regions = {
            "header": (16, 10, src_w - 16, 76),
            "card": (20, 80, src_w - 20, max(80, src_h - 60)),
            "footer": (16, max(0, src_h - 58), src_w - 16, src_h),
        }
        if rot in (90, 180, 270):
            out: dict[str, Rect] = {}
            for key, rect in source_regions.items():
                transformed = _transform_source_rect(rect, src_w, src_h, rot)
                if transformed is not None:
                    out[key] = transformed
            return out or {"card": (0, 0, w, h)}
        return source_regions
    if screen in (Screen.INVENTORY, Screen.REMINDERS):
        src_w, src_h = _screen_source_size(width, height, rotation_deg)
        left = 24
        right = max(left + 1, src_w - 24)
        content_top = 104
        footer_y = max(content_top + 1, src_h - 40)
        content_bottom = max(content_top + 1, footer_y - 6)

        if src_h > src_w:
            # Portrait-native list layout: inventory top (1/3), reminders bottom (2/3).
            split_y = content_top + int((content_bottom - content_top) * (1.0 / 3.0))
            split_y = max(content_top + 72, min(content_bottom - 120, split_y))
            source_regions = {
                "header": (16, 10, max(17, src_w - 16), 76),
                "summary": (20, 76, max(21, src_w - 20), 104),
                "list_left": (left, content_top, right, max(content_top + 1, split_y - 3)),
                "list_right": (left, min(content_bottom - 1, split_y + 3), right, content_bottom),
                "divider": (left, max(content_top, split_y - 2), right, min(content_bottom, split_y + 2)),
                "footer": (16, max(0, src_h - 44), max(17, src_w - 16), src_h),
            }
        else:
            split_x = left + int((right - left) * 0.40)
            source_regions = {
                "header": (16, 10, max(17, src_w - 16), 76),
                "summary": (20, 76, max(21, src_w - 20), 104),
                "list_left": (left, content_top, max(left + 1, split_x - 3), content_bottom),
                "list_right": (min(right - 1, split_x + 3), content_top, right, content_bottom),
                "divider": (max(left, split_x - 2), content_top, min(right, split_x + 2), content_bottom),
                "footer": (16, max(0, src_h - 44), max(17, src_w - 16), src_h),
            }

        if rot in (90, 180, 270):
            out: dict[str, Rect] = {}
            for key, rect in source_regions.items():
                transformed = _transform_source_rect(rect, src_w, src_h, rot)
                if transformed is not None:
                    out[key] = transformed
            return out or {"list_right": (0, 0, w, h)}
        return source_regions
    if screen == Screen.WEATHER:
        src_w, src_h = _screen_source_size(width, height, rotation_deg)
        y0 = 16
        y1 = max(y0 + 1, src_h - 16)
        total = max(100, y1 - y0)
        if src_h > src_w:
            hero_h = int(total * 0.39)
            metric_h = int(total * 0.18)
        else:
            hero_h = int(total * 0.41)
            metric_h = int(total * 0.20)
        source_regions = {
            "hero": (20, y0, max(21, src_w - 20), y0 + hero_h),
            "metrics": (20, y0 + hero_h, max(21, src_w - 20), y0 + hero_h + metric_h),
            "forecast": (20, y0 + hero_h + metric_h, max(21, src_w - 20), y1),
        }
        if rot in (90, 180, 270):
            out: dict[str, Rect] = {}
            for key, rect in source_regions.items():
                transformed = _transform_source_rect(rect, src_w, src_h, rot)
                if transformed is not None:
                    out[key] = transformed
            return out or {"forecast": (0, 0, w, h)}
        return source_regions
    if screen == Screen.CALENDAR:
        src_w, src_h = _screen_source_size(width, height, rotation_deg)
        if src_h > src_w:
            split_y = src_h // 2
            split_y = max(260, min(src_h - 220, split_y))
            agenda_header_top = split_y + 10
            agenda_header_bottom = min(src_h - 96, agenda_header_top + 88)
            source_regions = {
                "left_panel": (0, 0, src_w, split_y),
                # Month grid body where date-cell focus/marker changes happen.
                "left_grid": (24, 120, max(25, src_w - 20), max(121, split_y - 14)),
                "right_panel": (0, split_y, src_w, src_h),
                "right_header": (0, split_y, src_w, max(split_y + 1, agenda_header_bottom)),
                "right_agenda": (0, max(split_y + 1, agenda_header_bottom), src_w, src_h),
            }
        else:
            right_x = max(1, min(src_w - 1, int(src_w * 0.45)))
            source_regions = {
                "left_panel": (0, 0, right_x, src_h),
                # Month grid body where date-cell focus/marker changes happen.
                "left_grid": (24, 120, max(25, right_x - 20), max(121, src_h - 46)),
                "right_panel": (right_x, 0, src_w, src_h),
                "right_header": (right_x, 0, src_w, 90),
                "right_agenda": (right_x, 90, src_w, src_h),
            }
        if rot in (90, 180, 270):
            out: dict[str, Rect] = {}
            for key, rect in source_regions.items():
                transformed = _transform_source_rect(rect, src_w, src_h, rot)
                if transformed is not None:
                    out[key] = transformed
            return out or {"right_panel": (0, 0, w, h)}
        return source_regions
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
        # Right-side author tags (MOM/DAD/...) sit above the quote area and can be
        # outside the compact family-board body rect during memo rotation updates.
        "left_family_names": (
            max(ox0 + 24, left_split - 196),
            oy0 + int((oy1 - oy0) * 0.44),
            max(ox0 + 30, left_split - 2),
            oy0 + int((oy1 - oy0) * 0.58),
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


def _screen_source_size(width: int, height: int, rotation_deg: int) -> tuple[int, int]:
    rot = _normalized_right_angle(rotation_deg)
    if rot in (90, 270):
        return (max(1, int(height)), max(1, int(width)))
    return (max(1, int(width)), max(1, int(height)))


def _settings_source_row_rect(width: int, height: int, row_index: int, *, rotation_deg: int = 0) -> Rect | None:
    try:
        target = int(row_index)
    except (TypeError, ValueError):
        return None
    if target < 0 or target >= len(SETTINGS_ORDER):
        return None

    src_w, src_h = _screen_source_size(width, height, rotation_deg)
    left = 24
    right = max(left + 1, src_w - 24)
    top = 90
    row_h = 34
    row_gap = 1
    group_h = 20
    group_gap = 7
    y = top

    index_map = {item: idx for idx, item in enumerate(SETTINGS_ORDER)}
    for _group_name, group_items in SETTINGS_GROUPS:
        y += group_h
        for item in group_items:
            current_idx = index_map.get(item, -1)
            rect = (left, y, right, y + row_h)
            if current_idx == target:
                return rect
            y += row_h + row_gap
        y += group_gap
    return None


def _settings_row_rect(width: int, height: int, row_index: int, *, rotation_deg: int = 0) -> Rect | None:
    src_w, src_h = _screen_source_size(width, height, rotation_deg)
    source_rect = _settings_source_row_rect(width, height, row_index, rotation_deg=rotation_deg)
    if source_rect is None:
        return None
    return _transform_source_rect(source_rect, src_w, src_h, rotation_deg)


def _settings_footer_rect(width: int, height: int, *, rotation_deg: int = 0) -> Rect | None:
    src_w, src_h = _screen_source_size(width, height, rotation_deg)
    footer_h = 28
    footer_top = max(0, src_h - footer_h)
    source_rect = (24, footer_top, max(25, src_w - 24), src_h)
    return _transform_source_rect(source_rect, src_w, src_h, rotation_deg)


def _memo_summary_rect(width: int, height: int, *, rotation_deg: int = 0) -> Rect | None:
    src_w, src_h = _screen_source_size(width, height, rotation_deg)
    outer_x0 = 24
    outer_x1 = max(outer_x0 + 1, src_w - 24)
    inner_x0 = outer_x0 + 4
    inner_x1 = max(inner_x0 + 1, outer_x1 - 4)
    inner_y0 = 86
    source_rect = (inner_x0, max(0, inner_y0 - 2), inner_x1, min(src_h, inner_y0 + 20))
    return _transform_source_rect(source_rect, src_w, src_h, rotation_deg)


def _memo_focus_row_rect(
    width: int,
    height: int,
    memo_index: int,
    memos_digest: tuple,
    *,
    rotation_deg: int = 0,
) -> Rect | None:
    total = len(memos_digest or ())
    if total <= 0:
        return None

    src_w, src_h = _screen_source_size(width, height, rotation_deg)
    outer_x0 = 24
    outer_x1 = max(outer_x0 + 1, src_w - 24)
    inner_x0 = outer_x0 + 4
    inner_x1 = max(inner_x0 + 1, outer_x1 - 4)
    inner_y0 = 86
    inner_y1 = max(inner_y0 + 1, src_h - 56)

    list_gap = 6
    row_h = 66
    list_top = inner_y0 + 22
    list_h = max(1, inner_y1 - list_top)
    slots = max(1, (list_h + list_gap) // (row_h + list_gap))

    selected = int(memo_index or 0) % total
    start = max(0, min(selected - (slots // 2), total - slots))
    visible_row = max(0, selected - start)
    ry0 = list_top + visible_row * (row_h + list_gap)
    ry1 = min(inner_y1, ry0 + row_h)

    source_rect = (inner_x0, max(0, ry0 - 2), inner_x1, min(src_h, ry1 + 2))
    return _transform_source_rect(source_rect, src_w, src_h, rotation_deg)


def _home_menu_overlay_region(width: int, height: int) -> Rect:
    return home_menu_overlay_rect(width, height)


def _home_visible_section_counts(
    reminders_digest: tuple,
    *,
    hidden_rids: tuple[str, ...] = (),
    inv_max: int = 3,
    rem_max: int = 5,
) -> tuple[int, int]:
    fridge_rows, rem_rows = _home_portrait_rendered_sections(
        reminders_digest,
        hidden_rids=hidden_rids,
        inv_max=inv_max,
        shop_max=rem_max,
    )
    return len(fridge_rows), len(rem_rows)


def _home_visible_section_rows(
    reminders_digest: tuple,
    *,
    hidden_rids: tuple[str, ...] = (),
    inv_max: int = 3,
    rem_max: int = 5,
) -> tuple[tuple[tuple, ...], tuple[tuple, ...]]:
    return _home_portrait_rendered_sections(
        reminders_digest,
        hidden_rids=hidden_rids,
        inv_max=inv_max,
        shop_max=rem_max,
    )


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


def _home_focus_row_rect(
    width: int,
    height: int,
    focus_index: int,
    reminders_digest: tuple,
    *,
    hidden_rids: tuple[str, ...] = (),
) -> Rect | None:
    if int(focus_index) <= 1:
        return None

    metrics = _home_landscape_metrics(width, height)
    oy0 = metrics["oy0"]
    oy1 = metrics["oy1"]
    x0 = metrics["row_x0"]
    x1 = metrics["row_x1"]
    if x1 <= x0:
        return None

    inv_count, rem_count = _home_visible_section_counts(
        reminders_digest,
        hidden_rids=hidden_rids,
        inv_max=3,
        rem_max=5,
    )
    inv_row_y = int(metrics["inv_row_y"])
    inv_row_h = int(metrics["inv_row_h"])
    shop_row_y = _home_landscape_shopping_row_y(metrics, inv_count)
    shop_row_h = int(metrics["shop_row_h"])
    focus_pad_y = int(metrics["focus_pad_y"])

    pos = int(focus_index) - 2
    if pos < 0:
        return None

    if pos < inv_count:
        row_y = inv_row_y + (pos * inv_row_h)
        box = (x0, row_y + focus_pad_y, x1, row_y + inv_row_h - focus_pad_y)
    else:
        pos -= inv_count
        if pos < 0 or pos >= rem_count:
            return None
        row_y = shop_row_y + (pos * shop_row_h)
        box = (x0, row_y + focus_pad_y, x1, row_y + shop_row_h - focus_pad_y)

    rect = closed_box_to_rect(box, outline_width=1, extra_pad=7)
    if rect is None:
        return None
    rx0, ry0, rx1, ry1 = rect
    ry0 = max(oy0, ry0)
    ry1 = min(oy1, ry1)
    if rx1 <= rx0 or ry1 <= ry0:
        return None
    return (rx0, ry0, rx1, ry1)


def _home_focus_kind(focus_index: int) -> str:
    idx = int(focus_index or 0)
    if idx <= 0:
        return "clock"
    if idx == 1:
        return "weather"
    return "row"


def _home_focus_transition_rect(
    prev_rect: Rect | None,
    curr_rect: Rect | None,
    *,
    width: int,
    height: int,
) -> Rect | None:
    visible = [rect for rect in (prev_rect, curr_rect) if rect is not None]
    if not visible:
        return None
    return merge_rects(visible, width, height)


def _approx_font_height(size: int, *, scale: float = 0.82, minimum: int = 8) -> int:
    return max(int(minimum), int(round(max(1, int(size)) * float(scale))))


def _home_landscape_metrics(width: int, height: int) -> dict[str, int]:
    w = max(1, int(width))
    h = max(1, int(height))
    margin = 18
    ox0, oy0, ox1, oy1 = margin, margin, max(margin + 1, w - margin), max(margin + 1, h - margin)
    split_x = ox0 + int((ox1 - ox0) * 0.60)
    left_pad = 24
    right_pad = 22
    top_y = oy0 + left_pad
    lx0 = ox0 + left_pad
    lx1 = split_x - left_pad
    weather_col_w = 142
    weather_right = lx1 - 2
    weather_left = weather_right - weather_col_w
    focus_pad_x = 6
    focus_pad_y = 4
    focus_right_trim = 0

    weather_top = top_y - 2
    city_h = _approx_font_height(13, scale=0.84, minimum=10)
    temp_h = _approx_font_height(66, scale=0.78, minimum=46)
    desc_h = _approx_font_height(15, scale=0.86, minimum=12)
    hum_h = _approx_font_height(15, scale=0.86, minimum=12)
    icon_size = max(12, int(round(34 * 1.35)))
    city_y = max(oy0 + 4, weather_top - city_h - 6)
    desc_y = weather_top + temp_h + 16 + 5
    icon_y = desc_y + desc_h + 10
    humidity_bottom = icon_y + icon_size + 8 + hum_h

    weekday_h = _approx_font_height(15, scale=0.86, minimum=12)
    date_h = _approx_font_height(18, scale=0.86, minimum=14)
    clock_bottom = top_y + _approx_font_height(70, scale=0.78, minimum=54) + 13 + weekday_h + 11 + date_h
    weather_bottom = max(clock_bottom, city_y + city_h, desc_y + desc_h, humidity_bottom)

    header_rule_y = weather_bottom + 28
    micro_h = _approx_font_height(16, scale=0.78, minimum=12)
    family_rule_y = header_rule_y + 8 + micro_h + 8

    inv_y = oy0 + max(8, right_pad - 6)
    inv_row_y = inv_y + 34
    inv_row_h = 40
    shop_title_h = _approx_font_height(13, scale=0.84, minimum=10)
    shop_line_gap = 9
    shop_rule_y_min_gap = 14
    shop_header_gap = 24
    shop_row_h = 40

    inner_x0 = split_x + 1 + right_pad
    inner_x1 = ox1 - right_pad
    return {
        "w": w,
        "h": h,
        "ox0": ox0,
        "oy0": oy0,
        "ox1": ox1,
        "oy1": oy1,
        "top_y": top_y,
        "lx0": lx0,
        "weather_left": weather_left,
        "weather_right": weather_right,
        "weather_top": weather_top,
        "weather_bottom": weather_bottom,
        "focus_pad_x": focus_pad_x,
        "focus_pad_y": focus_pad_y,
        "focus_right_trim": focus_right_trim,
        "family_rule_y": family_rule_y,
        "inv_y": inv_y,
        "inv_row_y": inv_row_y,
        "inv_row_h": inv_row_h,
        "shop_title_h": shop_title_h,
        "shop_line_gap": shop_line_gap,
        "shop_rule_y_min_gap": shop_rule_y_min_gap,
        "shop_header_gap": shop_header_gap,
        "shop_row_h": shop_row_h,
        "row_x0": max(0, inner_x0 - 10),
        "row_x1": min(w, inner_x1 + focus_pad_x - focus_right_trim),
    }


def _home_landscape_shopping_row_y(metrics: dict[str, int], inventory_rows: int) -> int:
    inv_bottom_y = int(metrics["inv_row_y"]) + max(0, int(inventory_rows)) * int(metrics["inv_row_h"])
    shop_rule_y = max(int(metrics["family_rule_y"]), inv_bottom_y + int(metrics["shop_rule_y_min_gap"]))
    shop_title_y = shop_rule_y - int(metrics["shop_title_h"]) - int(metrics["shop_line_gap"])
    return max(shop_title_y + int(metrics["shop_header_gap"]), shop_rule_y + 10) + 5


def _home_landscape_header_focus_rect(width: int, height: int, *, kind: str) -> Rect | None:
    rect = closed_box_to_rect(home_landscape_header_focus_box(width, height, kind=kind), outline_width=1)
    return _clip_rect(rect, max(1, int(width)), max(1, int(height))) if rect is not None else None


def _home_landscape_focus_rect(
    regions: dict[str, Rect],
    width: int,
    height: int,
    *,
    focus_index: int,
    reminders_digest: tuple,
    hidden_rids: tuple[str, ...] = (),
) -> Rect | None:
    kind = _home_focus_kind(focus_index)
    if kind == "clock":
        return _home_landscape_header_focus_rect(width, height, kind="clock")
    if kind == "weather":
        return _home_landscape_header_focus_rect(width, height, kind="weather")
    return _home_focus_row_rect(width, height, focus_index, reminders_digest, hidden_rids=hidden_rids)


def _home_landscape_section_rect(
    width: int,
    height: int,
    *,
    section: str,
    inventory_rows: int,
    shopping_rows: int,
) -> Rect | None:
    metrics = _home_landscape_metrics(width, height)
    oy0 = metrics["oy0"]
    oy1 = metrics["oy1"]
    x0 = metrics["row_x0"]
    x1 = metrics["row_x1"]
    inv_y = metrics["inv_y"]
    inv_row_y = metrics["inv_row_y"]
    inv_row_h = metrics["inv_row_h"]
    shop_row_y = _home_landscape_shopping_row_y(metrics, inventory_rows)
    shop_row_h = metrics["shop_row_h"]
    shop_rule_y = shop_row_y - int(metrics["shop_header_gap"])

    if section == "inventory":
        y0 = max(oy0, inv_y - 12)
        y1 = min(oy1, max(y0 + 16, inv_row_y + max(0, inventory_rows) * inv_row_h))
    elif section == "shopping":
        y0 = max(oy0, shop_rule_y - 12)
        y1 = min(oy1, max(y0 + 16, shop_row_y + max(0, shopping_rows) * shop_row_h))
    else:
        return None

    if x1 <= x0 or y1 <= y0:
        return None
    return (x0, y0, x1, y1)


def _home_portrait_focus_rect(
    home_regions: dict[str, Rect | None],
    width: int,
    height: int,
    *,
    rotation_deg: int,
    focus_index: int,
    weather_digest: tuple,
    reminders_digest: tuple,
    focus_rid: str,
    hidden_rids: tuple[str, ...] = (),
) -> Rect | None:
    kind = _home_focus_kind(focus_index)
    if kind == "clock":
        return _home_portrait_header_focus_rect(
            width,
            height,
            rotation_deg=rotation_deg,
            kind="clock",
            weather_digest=weather_digest,
        )
    if kind == "weather":
        return _home_portrait_header_focus_rect(
            width,
            height,
            rotation_deg=rotation_deg,
            kind="weather",
            weather_digest=weather_digest,
        )
    return _home_portrait_focus_row_rect(
        width,
        height,
        rotation_deg=rotation_deg,
        reminders_digest=reminders_digest,
        focus_rid=focus_rid,
        hidden_rids=hidden_rids,
    )


def infer_dirty_rects(prev: UiSnapshot, curr: UiSnapshot, width: int, height: int) -> list[Rect]:
    rects, _ = infer_dirty_rects_with_reasons(prev, curr, width, height)
    return rects


def infer_dirty_rects_with_reasons(prev: UiSnapshot, curr: UiSnapshot, width: int, height: int) -> tuple[list[Rect], list[str]]:
    if prev.screen != curr.screen:
        if curr.screen in (Screen.LANDING, Screen.ONBOARDING):
            regions = _screen_regions(curr.screen, width, height, rotation_deg=curr.rotation_deg)
            return [regions.get("panel", regions.get("full", (0, 0, max(1, int(width)), max(1, int(height)))))], [
                f"screen.change_to_{curr.screen.value}"
            ]
        w = max(1, int(width))
        h = max(1, int(height))
        if curr.screen == Screen.MEMO:
            mid = w // 2
            return [(0, 0, mid, h), (mid, 0, w, h)], ["screen.change_to_memo"]
        if curr.screen in (Screen.INVENTORY, Screen.REMINDERS):
            split = max(1, min(w - 1, int(w * 0.40)))
            return [(0, 0, split, h), (split, 0, w, h)], ["screen.change_to_list"]
        if curr.screen == Screen.CALENDAR:
            regions = _screen_regions(curr.screen, width, height, rotation_deg=curr.rotation_deg)
            left_panel = regions.get("left_panel", (0, 0, max(1, int(width)), max(1, int(height))))
            right_panel = regions.get("right_panel", left_panel)
            return [left_panel, right_panel], ["screen.change_to_calendar"]
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
            rects.append(regions.get("panel", regions["full"]))
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
                rects.append(regions["prefs_panel"])
                reasons.append("onboarding.prefs_focus")
            if (
                prev.device_language != curr.device_language
                or prev.voice_locale != curr.voice_locale
                or prev.device_timezone != curr.device_timezone
                or prev.auto_sync_enabled != curr.auto_sync_enabled
                or prev.onboarding_wifi_ssid != curr.onboarding_wifi_ssid
            ):
                rects.append(regions["prefs_panel"])
                reasons.append("onboarding.prefs_value")
            return rects, reasons
        if curr.onboarding_step == "voice_guide":
            if prev.onboarding_voice_guide_focus_index != curr.onboarding_voice_guide_focus_index:
                rects.append(regions["voice_panel"])
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
                rects.append(regions["voice_panel"])
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
            prev_row = _settings_row_rect(width, height, prev.settings_focused_index, rotation_deg=curr.rotation_deg)
            curr_row = _settings_row_rect(width, height, curr.settings_focused_index, rotation_deg=curr.rotation_deg)
            if prev_row is not None:
                rects.append(prev_row)
            if curr_row is not None and curr_row != prev_row:
                rects.append(curr_row)
            if prev_row is None and curr_row is None:
                rects.append(regions["rows"])
            reasons.append("settings.focus_move")
        if (
            prev.settings_notice != curr.settings_notice
            or prev.last_sync_at != curr.last_sync_at
        ):
            footer = _settings_footer_rect(width, height, rotation_deg=curr.rotation_deg)
            rects.append(footer if footer is not None else regions["footer"])
            reasons.append("settings.footer_notice")
        if (
            prev.partial_refresh_mode != curr.partial_refresh_mode
            or prev.full_refresh_every != curr.full_refresh_every
            or prev.wifi_enabled != curr.wifi_enabled
            or prev.bluetooth_enabled != curr.bluetooth_enabled
            or prev.auto_sync_enabled != curr.auto_sync_enabled
        ):
            curr_row = _settings_row_rect(width, height, curr.settings_focused_index, rotation_deg=curr.rotation_deg)
            rects.append(curr_row if curr_row is not None else regions["rows"])
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
            if prev.timer_running != curr.timer_running:
                # START/PAUSE label lives in controls row and changes with running state.
                rects.append(regions["controls"])
            reasons.append("timer.time_or_state")
        return rects, reasons

    if curr.screen == Screen.MENU:
        if prev.menu_focused != curr.menu_focused:
            rects.append(regions["pills"])
            reasons.append("menu.focus_move")
        return rects, reasons

    if curr.screen == Screen.MEMO:
        if prev.memo_index != curr.memo_index:
            summary = _memo_summary_rect(width, height, rotation_deg=curr.rotation_deg)
            prev_row = _memo_focus_row_rect(
                width,
                height,
                prev.memo_index,
                prev.memos_digest,
                rotation_deg=curr.rotation_deg,
            )
            curr_row = _memo_focus_row_rect(
                width,
                height,
                curr.memo_index,
                curr.memos_digest,
                rotation_deg=curr.rotation_deg,
            )
            if summary is not None:
                rects.append(summary)
            if prev_row is not None:
                rects.append(prev_row)
            if curr_row is not None and curr_row != prev_row:
                rects.append(curr_row)
            if not rects:
                rects.append(regions["card"])
            reasons.append("memo.focus_move")
            return rects, reasons
        if prev.memo_expanded != curr.memo_expanded:
            focus_row = _memo_focus_row_rect(
                width,
                height,
                curr.memo_index,
                curr.memos_digest,
                rotation_deg=curr.rotation_deg,
            )
            rects.append(focus_row if focus_row is not None else regions["card"])
            reasons.append("memo.expand_toggle")
            return rects, reasons
        if prev.memos_digest != curr.memos_digest:
            summary = _memo_summary_rect(width, height, rotation_deg=curr.rotation_deg)
            if summary is not None:
                rects.append(summary)
            rects.append(regions["card"])
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
        offset_changed = prev.calendar_offset_days != curr.calendar_offset_days
        mode_changed = prev.calendar_mode != curr.calendar_mode
        data_changed = (
            prev.reminders_digest != curr.reminders_digest
            or prev.calendar_digest != curr.calendar_digest
        )
        if (
            offset_changed
            or mode_changed
            or data_changed
        ):
            if offset_changed:
                prev_cursor = date.today() + timedelta(days=int(prev.calendar_offset_days or 0))
                curr_cursor = date.today() + timedelta(days=int(curr.calendar_offset_days or 0))
                if (prev_cursor.year, prev_cursor.month) != (curr_cursor.year, curr_cursor.month):
                    rects.append(regions["left_panel"])
                else:
                    rects.append(regions.get("left_grid", regions["left_panel"]))
                rects.append(regions.get("right_header", regions["right_panel"]))
                rects.append(regions["right_agenda"])
            elif mode_changed:
                rects.append(regions.get("right_header", regions["right_panel"]))
                rects.append(regions["right_agenda"])
            else:
                rects.append(regions.get("left_grid", regions["left_panel"]))
                rects.append(regions["right_agenda"])
            reasons.append("calendar.date_or_mode_or_data")
            return rects, reasons
        if prev.calendar_selected_index != curr.calendar_selected_index:
            rects.append(regions["right_agenda"])
            reasons.append("calendar.agenda_focus_move")
        return rects, reasons

    # HOME and fallback.
    portrait_home = str(curr.kitchen_visible_layout or prev.kitchen_visible_layout or "").strip().lower() == "portrait"
    home_regions = _home_portrait_regions(width, height, rotation_deg=curr.rotation_deg) if portrait_home else regions
    if prev.menu_overlay_active != curr.menu_overlay_active:
        rect = home_regions["menu_overlay"] if portrait_home else regions["home_menu_overlay"]
        if rect is not None:
            rects.append(rect)
        reasons.append("home.menu_overlay_toggle")
    if curr.menu_overlay_active and prev.menu_focused != curr.menu_focused:
        rect = home_regions["menu_overlay"] if portrait_home else regions["home_menu_overlay"]
        if rect is not None:
            rects.append(rect)
        reasons.append("home.menu_overlay_focus")

    if portrait_home:
        prev_focus_rid = _home_portrait_effective_focus_rid(prev)
        curr_focus_rid = _home_portrait_effective_focus_rid(curr)
        if (
            prev.focused_index != curr.focused_index
            or prev.kitchen_focus_rid_override != curr.kitchen_focus_rid_override
            or prev_focus_rid != curr_focus_rid
        ):
            prev_kind = _home_focus_kind(prev.focused_index)
            curr_kind = _home_focus_kind(curr.focused_index)
            prev_focus_rect = _home_portrait_focus_rect(
                home_regions,
                width,
                height,
                rotation_deg=prev.rotation_deg,
                focus_index=prev.focused_index,
                weather_digest=prev.weather_digest,
                reminders_digest=prev.reminders_digest,
                focus_rid=prev_focus_rid,
                hidden_rids=prev.home_hidden_rids,
            )
            curr_focus_rect = _home_portrait_focus_rect(
                home_regions,
                width,
                height,
                rotation_deg=curr.rotation_deg,
                focus_index=curr.focused_index,
                weather_digest=curr.weather_digest,
                reminders_digest=curr.reminders_digest,
                focus_rid=curr_focus_rid,
                hidden_rids=curr.home_hidden_rids,
            )
            left_targets = {"clock", "weather"}
            if prev_kind == "row" and curr_kind == "row":
                merged = _home_focus_transition_rect(prev_focus_rect, curr_focus_rect, width=width, height=height)
                if merged is not None:
                    rects.append(merged)
                elif home_regions["list_all"] is not None:
                    rects.append(home_regions["list_all"])
                reasons.append("home.focus_move_row")
            elif prev_kind in left_targets and curr_kind in left_targets:
                merged = _home_focus_transition_rect(prev_focus_rect, curr_focus_rect, width=width, height=height)
                if merged is not None:
                    rects.append(merged)
                reasons.append("home.focus_move_left_target")
            else:
                if prev_focus_rect is not None:
                    rects.append(prev_focus_rect)
                if curr_focus_rect is not None and curr_focus_rect != prev_focus_rect:
                    rects.append(curr_focus_rect)
                if curr_kind in left_targets:
                    reasons.append("home.focus_to_left_panel")
                else:
                    reasons.append("home.focus_from_left_panel")
    elif prev.focused_index != curr.focused_index:
        prev_kind = _home_focus_kind(prev.focused_index)
        curr_kind = _home_focus_kind(curr.focused_index)
        prev_focus_rect = _home_landscape_focus_rect(
            regions,
            width,
            height,
            focus_index=prev.focused_index,
            reminders_digest=prev.reminders_digest,
            hidden_rids=prev.home_hidden_rids,
        )
        curr_focus_rect = _home_landscape_focus_rect(
            regions,
            width,
            height,
            focus_index=curr.focused_index,
            reminders_digest=curr.reminders_digest,
            hidden_rids=curr.home_hidden_rids,
        )
        left_targets = {"clock", "weather"}
        if prev_kind == "row" and curr_kind == "row":
            merged = _home_focus_transition_rect(prev_focus_rect, curr_focus_rect, width=width, height=height)
            rects.append(merged if merged is not None else regions["right_list"])
            reasons.append("home.focus_move_row")
        elif prev_kind in left_targets and curr_kind in left_targets:
            merged = _home_focus_transition_rect(prev_focus_rect, curr_focus_rect, width=width, height=height)
            if merged is not None:
                rects.append(merged)
            reasons.append("home.focus_move_left_target")
        else:
            if prev_focus_rect is not None:
                rects.append(prev_focus_rect)
            if curr_focus_rect is not None and curr_focus_rect != prev_focus_rect:
                rects.append(curr_focus_rect)
            if curr_kind in left_targets:
                reasons.append("home.focus_to_left_panel")
            else:
                reasons.append("home.focus_from_left_panel")
    if prev.reminders_digest != curr.reminders_digest or prev.home_hidden_rids != curr.home_hidden_rids:
        prev_rids = tuple(str(r[0]) for r in prev.reminders_digest)
        curr_rids = tuple(str(r[0]) for r in curr.reminders_digest)
        hidden_changed = prev.home_hidden_rids != curr.home_hidden_rids
        if hidden_changed:
            if portrait_home:
                prev_inventory_rows, prev_shopping_rows = _home_portrait_rendered_sections(
                    prev.reminders_digest,
                    hidden_rids=prev.home_hidden_rids,
                )
                curr_inventory_rows, curr_shopping_rows = _home_portrait_rendered_sections(
                    curr.reminders_digest,
                    hidden_rids=curr.home_hidden_rids,
                )
            else:
                prev_inventory_rows, prev_shopping_rows = _home_visible_section_rows(
                    prev.reminders_digest,
                    hidden_rids=prev.home_hidden_rids,
                    inv_max=3,
                    rem_max=5,
                )
                curr_inventory_rows, curr_shopping_rows = _home_visible_section_rows(
                    curr.reminders_digest,
                    hidden_rids=curr.home_hidden_rids,
                    inv_max=3,
                    rem_max=5,
                )

            changed = False
            if prev_inventory_rows != curr_inventory_rows:
                if portrait_home:
                    rect = _home_portrait_section_rect(
                        width,
                        height,
                        rotation_deg=curr.rotation_deg,
                        section="inventory",
                        inventory_rows=max(len(prev_inventory_rows), len(curr_inventory_rows)),
                        shopping_rows=max(len(prev_shopping_rows), len(curr_shopping_rows)),
                    )
                else:
                    rect = _home_landscape_section_rect(
                        width,
                        height,
                        section="inventory",
                        inventory_rows=max(len(prev_inventory_rows), len(curr_inventory_rows)),
                        shopping_rows=max(len(prev_shopping_rows), len(curr_shopping_rows)),
                    )
                if rect is not None:
                    rects.append(rect)
                    changed = True
            if prev_shopping_rows != curr_shopping_rows:
                if portrait_home:
                    rect = _home_portrait_section_rect(
                        width,
                        height,
                        rotation_deg=curr.rotation_deg,
                        section="shopping",
                        inventory_rows=max(len(prev_inventory_rows), len(curr_inventory_rows)),
                        shopping_rows=max(len(prev_shopping_rows), len(curr_shopping_rows)),
                    )
                else:
                    rect = _home_landscape_section_rect(
                        width,
                        height,
                        section="shopping",
                        inventory_rows=max(len(prev_inventory_rows), len(curr_inventory_rows)),
                        shopping_rows=max(len(prev_shopping_rows), len(curr_shopping_rows)),
                    )
                if rect is not None:
                    rects.append(rect)
                    changed = True
            if not changed:
                fallback = home_regions["list_all"] if portrait_home else regions["right_list"]
                if fallback is not None:
                    rects.append(fallback)
            reasons.append("home.reminder_compact")
        elif prev_rids == curr_rids:
            # Same row order: likely a click-toggle style change; update focused row only.
            if portrait_home:
                prev_focus_rid = _home_portrait_effective_focus_rid(prev)
                curr_focus_rid = _home_portrait_effective_focus_rid(curr)
                prev_row = _home_portrait_focus_row_rect(
                    width,
                    height,
                    rotation_deg=prev.rotation_deg,
                    reminders_digest=prev.reminders_digest,
                    focus_rid=prev_focus_rid,
                    hidden_rids=prev.home_hidden_rids,
                )
                curr_row = _home_portrait_focus_row_rect(
                    width,
                    height,
                    rotation_deg=curr.rotation_deg,
                    reminders_digest=curr.reminders_digest,
                    focus_rid=curr_focus_rid,
                    hidden_rids=curr.home_hidden_rids,
                )
            else:
                prev_row = _home_focus_row_rect(
                    width,
                    height,
                    prev.focused_index,
                    prev.reminders_digest,
                    hidden_rids=prev.home_hidden_rids,
                )
                curr_row = _home_focus_row_rect(
                    width,
                    height,
                    curr.focused_index,
                    curr.reminders_digest,
                    hidden_rids=curr.home_hidden_rids,
                )
            if prev_row is not None:
                rects.append(prev_row)
            if curr_row is not None and curr_row != prev_row:
                rects.append(curr_row)
            if prev_row is None and curr_row is None:
                fallback = home_regions["list_all"] if portrait_home else regions["right_list"]
                if fallback is not None:
                    rects.append(fallback)
                reasons.append("home.reminder_change_fallback")
            else:
                reasons.append("home.reminder_row_update")
        else:
            changed = False
            prev_inventory_rows, prev_shopping_rows = _home_visible_section_rows(
                prev.reminders_digest,
                hidden_rids=prev.home_hidden_rids,
                inv_max=4 if portrait_home else 3,
                rem_max=5,
            )
            curr_inventory_rows, curr_shopping_rows = _home_visible_section_rows(
                curr.reminders_digest,
                hidden_rids=curr.home_hidden_rids,
                inv_max=4 if portrait_home else 3,
                rem_max=5,
            )
            if prev_inventory_rows != curr_inventory_rows:
                rect = _home_portrait_section_rect(
                    width,
                    height,
                    rotation_deg=curr.rotation_deg,
                    section="inventory",
                    inventory_rows=max(len(prev_inventory_rows), len(curr_inventory_rows)),
                    shopping_rows=max(len(prev_shopping_rows), len(curr_shopping_rows)),
                ) if portrait_home else _home_landscape_section_rect(
                    width,
                    height,
                    section="inventory",
                    inventory_rows=max(len(prev_inventory_rows), len(curr_inventory_rows)),
                    shopping_rows=max(len(prev_shopping_rows), len(curr_shopping_rows)),
                )
                if rect is not None:
                    rects.append(rect)
                    changed = True
            if prev_shopping_rows != curr_shopping_rows:
                rect = _home_portrait_section_rect(
                    width,
                    height,
                    rotation_deg=curr.rotation_deg,
                    section="shopping",
                    inventory_rows=max(len(prev_inventory_rows), len(curr_inventory_rows)),
                    shopping_rows=max(len(prev_shopping_rows), len(curr_shopping_rows)),
                ) if portrait_home else _home_landscape_section_rect(
                    width,
                    height,
                    section="shopping",
                    inventory_rows=max(len(prev_inventory_rows), len(curr_inventory_rows)),
                    shopping_rows=max(len(prev_shopping_rows), len(curr_shopping_rows)),
                )
                if rect is not None:
                    rects.append(rect)
                    changed = True
            if not changed:
                fallback = home_regions["list_all"] if portrait_home else regions["right_list"]
                if fallback is not None:
                    rects.append(fallback)
            reasons.append("home.reminder_reorder")
    if prev.memo_index != curr.memo_index:
        if portrait_home:
            rect = home_regions["memo"]
            if rect is not None:
                rects.append(rect)
        else:
            body_rect = regions.get("left_family_board")
            names_rect = regions.get("left_family_names")
            if body_rect is not None:
                rects.append(body_rect)
            if names_rect is not None:
                rects.append(names_rect)
        reasons.append("home.family_board_update")
    if prev.weather_digest != curr.weather_digest:
        rect = home_regions["header_weather"] if portrait_home else regions["left_weather"]
        if rect is not None:
            rects.append(rect)
        reasons.append("home.weather_update")
    if (
        prev.timer_seconds != curr.timer_seconds
        or prev.timer_running != curr.timer_running
        or prev.clock_minute_bucket != curr.clock_minute_bucket
        or prev.widget_mode != curr.widget_mode
    ):
        rect = home_regions["header_clock"] if portrait_home else regions["left_clock"]
        if rect is not None:
            rects.append(rect)
        reasons.append("home.clock_or_timer_state")
    if prev.voice_active != curr.voice_active or prev.voice_phase != curr.voice_phase:
        rect = home_regions["voice_overlay"] if portrait_home else regions["voice_overlay"]
        if rect is not None:
            rects.append(rect)
        reasons.append("home.voice_overlay")
    return rects, reasons
