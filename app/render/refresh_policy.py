from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from app.core.settings_schema import SETTINGS_GROUPS, SETTINGS_ORDER
from app.core.state import AppState, Screen
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


def screen_partial_area_limit(screen: Screen, mode: str) -> float:
    base = mode_params(mode).partial_area_limit
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
    source_rect = _home_portrait_row_source_rect(
        width,
        height,
        reminders_digest=reminders_digest,
        focus_rid=focus_rid,
        hidden_rids=hidden_rids,
    )
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
        y0 = row_y + focus_pad_y
        y1 = row_y + inv_row_h - focus_pad_y
    else:
        pos -= inv_count
        if pos < 0 or pos >= rem_count:
            return None
        row_y = shop_row_y + (pos * shop_row_h)
        y0 = row_y + focus_pad_y
        y1 = row_y + shop_row_h - focus_pad_y

    y0 = max(oy0, y0)
    y1 = min(oy1, y1)
    if x1 <= x0 or y1 <= y0:
        return None
    return (x0, y0, x1, y1)


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
    metrics = _home_landscape_metrics(width, height)
    w = metrics["w"]
    h = metrics["h"]
    ox0 = metrics["ox0"]
    oy0 = metrics["oy0"]
    oy1 = metrics["oy1"]
    top_y = metrics["top_y"]
    lx0 = metrics["lx0"]
    weather_left = metrics["weather_left"]
    weather_right = metrics["weather_right"]
    weather_top = metrics["weather_top"]
    weather_bottom = metrics["weather_bottom"]
    focus_pad_x = metrics["focus_pad_x"]
    focus_pad_y = metrics["focus_pad_y"]
    focus_right_trim = metrics["focus_right_trim"]

    if kind == "clock":
        x0 = lx0 - focus_pad_x
        x1 = max(x0 + 16, weather_left - 7)
        y0 = max(oy0 + 2, top_y - 28)
        y1 = min(oy1, top_y + 142)
        return _clip_rect((x0, y0, x1, y1), w, h)

    if kind == "weather":
        x0 = weather_left - focus_pad_x
        x1 = weather_right + focus_pad_x - focus_right_trim
        y0 = max(oy0 + 2, weather_top - focus_pad_y)
        y1 = min(oy1, weather_bottom + focus_pad_y)
        return _clip_rect((x0, y0, x1, y1), w, h)

    return None


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
    reminders_digest: tuple,
    focus_rid: str,
    hidden_rids: tuple[str, ...] = (),
) -> Rect | None:
    kind = _home_focus_kind(focus_index)
    if kind == "clock":
        return home_regions["header_clock"]
    if kind == "weather":
        return home_regions["header_weather"]
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
        w = max(1, int(width))
        h = max(1, int(height))
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
        rect = home_regions["memo"] if portrait_home else regions["left_family_board"]
        if rect is not None:
            rects.append(rect)
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
