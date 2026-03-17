from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import time
from typing import Any, Optional


class Screen(str, Enum):
    LANDING = "landing"
    ONBOARDING = "onboarding"
    HOME = "home"
    MENU = "menu"
    MEMO = "memo"
    TIMER = "timer"
    CALENDAR = "calendar"
    WEATHER = "weather"
    INVENTORY = "inventory"
    REMINDERS = "reminders"
    SETTINGS = "settings"
    PLACEHOLDER = "placeholder"


class WidgetMode(str, Enum):
    CLOCK = "clock"
    TIMER = "timer"


class MenuItemId(str, Enum):
    MEMO = "MEMO"
    LIST = "LIST"
    TIMER = "TIMER"
    CALENDAR = "CALENDAR"
    SETTINGS = "SETTINGS"


@dataclass
class Reminder:
    # Stable identifier (needed so focus can follow the same item after reorder)
    rid: str
    title: str
    right: str = ""  # time or due text
    completed: bool = False
    category: str = "general"  # e.g. fridge / shopping / general
    created_at: float = 0.0  # unix ts (optional; used for relative badges)


@dataclass
class WeatherDay:
    dow: str
    icon: str
    hi: int
    lo: int
    humidity: int | None = None
    feels_like: float | None = None
    wind_kmh: float | None = None
    uv_index: float | None = None


@dataclass
class CalendarEvent:
    eid: str
    title: str
    when: str
    date_iso: str = ""


@dataclass
class MemoItem:
    mid: str
    text: str
    author: str
    timestamp: float
    is_new: bool = False
    expiration_bucket: str = "none"
    expires_at: float | None = None


@dataclass
class DashboardModel:
    location: str = "Unknown"
    battery: int = 84
    reminders: list[Reminder] = field(default_factory=list)
    weather: list[WeatherDay] = field(default_factory=list)
    # Minimal calendar dataset for the detail page (mobile app will provide real data later)
    calendar: list[CalendarEvent] = field(default_factory=list)
    memos: list[MemoItem] = field(default_factory=list)


@dataclass
class UiState:
    # Boot / first-run onboarding flow.
    boot_started_at: float = field(default_factory=lambda: time.time())
    boot_min_show_s: float = 0.0
    landing_rotate_seen: bool = False
    landing_confirm_seen: bool = False
    landing_voice_demo_index: int = 0
    landing_voice_demo_cycles: int = 0
    landing_last_demo_at: float = field(default_factory=lambda: time.time())
    landing_status: str = ""
    setup_completed: bool = False
    onboarding_step: str = "start"  # start | pair_qr | prefs | voice_guide | done
    onboarding_focus_index: int = 0
    onboarding_qr_focus_index: int = 0
    onboarding_prefs_focus_index: int = 0
    onboarding_pair_token: str = ""
    onboarding_pair_expires_at: float = 0.0
    onboarding_status: str = ""
    onboarding_wifi_ssid: str = ""
    onboarding_voice_guide_focus_index: int = 0  # single CTA on voice guide
    onboarding_voice_demo_heard: str = ""
    onboarding_voice_demo_attempted: bool = False
    onboarding_voice_demo_case_index: int = 0
    onboarding_voice_demo_pass_mask: int = 0
    onboarding_voice_demo_action: str = ""
    onboarding_voice_sample_text: str = "Add milk to inventory"
    onboarding_voice_expected_action: str = "Add inventory"
    device_language: str = "en-US"
    device_timezone: str = "UTC"
    voice_locale: str = "en-US"

    screen: Screen = Screen.HOME
    # HOME focus queue: [CLOCK, WEATHER, TASK_0..TASK_N-1]
    focused_index: int = 2  # TSX starts focused on the first task (when present)
    idle: bool = False
    # Reminder paging (derived from focus for home, but stored so renderer can show PAGE x/y)
    page: int = 1

    # MENU state (TSX: Back from dashboard opens the menu).
    menu_focused: MenuItemId = MenuItemId.LIST
    active_menu: Optional[MenuItemId] = None
    # HOME overlay navigation layer (no screen switch, partial-refresh friendly).
    menu_overlay_active: bool = False

    # Widget slot state (TSX: top-left is a widget slot that can show CLOCK or TIMER).
    widget_mode: WidgetMode = WidgetMode.CLOCK
    # Home clock render source (minute bucket, local timezone). Updated on Tick.
    clock_minute_bucket: int = field(default_factory=lambda: int(time.time() // 60))
    timer_seconds: int = 0
    timer_running: bool = False
    timer_last_tick_at: float = field(default_factory=lambda: time.time())
    # Current timer target duration (seconds) for the active run; used by completion copy.
    timer_target_seconds: int = 0
    # Countdown-done alert state (blinking zeros + completion message).
    timer_alert_active: bool = False
    timer_alert_blink_on: bool = True
    timer_alert_started_at: float = 0.0
    timer_alert_until: float = 0.0
    timer_last_completed_seconds: int = 0
    # TIMER page focus: [DECREASE, INCREASE, START_PAUSE, RESET]
    timer_focused_index: int = 2

    # Detail-page navigation (rotary-driven).
    # Calendar: rotate changes date; click toggles to agenda mode; rotate selects agenda item; click toggles task.
    calendar_offset_days: int = 0
    calendar_mode: str = "date"  # "date" | "agenda"
    calendar_selected_index: int = 0

    # Weather detail selected day (currently fixed in UI; kept for compatibility).
    weather_day_index: int = 0

    # Mood panel memo selection + auto-rotation.
    memo_index: int = 0
    memo_expanded: bool = False
    memo_last_rotated_at: float = field(default_factory=lambda: time.time())
    # Unified list page focus index (Inventory + Reminders items only; section headers are not focusable).
    list_focused_index: int = 0
    # Monotonic revision for reminder list mutations (toggle/reorder/etc.).
    reminders_version: int = 0
    # Last rendered focus queue for kitchen home (left panel excluded).
    kitchen_visible_rids: list[str] = field(default_factory=list)
    # Theme key used when the kitchen visible queue cache was produced.
    kitchen_visible_theme_key: str = ""
    # Renderer-specific layout mode for the cached kitchen queue.
    kitchen_visible_layout: str = ""
    # Reminder revision used when the kitchen visible queue cache was produced.
    kitchen_visible_reminders_version: int = -1
    # UX hold: after clicking a kitchen item, keep focus pinned on that item
    # until next explicit rotate input.
    kitchen_focus_rid_override: str = ""
    # HOME-only completed-item policy: checked rows stay visible for a grace
    # window, then disappear from HOME on a later natural refresh opportunity.
    home_pending_hide_rids: list[str] = field(default_factory=list)
    home_hidden_rids: list[str] = field(default_factory=list)
    home_hide_due_at: float = 0.0

    # Delayed reorder: after toggling completion, wait a bit before moving completed to the bottom.
    pending_reorder: bool = False
    reorder_due_at: float = 0.0

    # Voice UI zone state (used by simulator + board render paths).
    voice_active: bool = False
    voice_phase: str = "idle"  # "idle" | "recording" | "processing" | "confirm" | "done" | "error"
    voice_message: str = ""
    voice_due_at: float = 0.0
    voice_confirm_tool: str = ""
    voice_confirm_payload_json: str = ""
    voice_confirm_due_at: float = 0.0
    voice_confirm_before_snapshot: dict[str, Any] = field(default_factory=dict)
    # Recent voice action-group history for context resolution (bounded queue).
    # Each entry is a JSON-like dict:
    # {"at": <unix_ts>, "transcript": str, "actions": [{"tool": str, "args": {...}}], "status": str, "message": str}
    voice_recent_action_groups: list[dict[str, Any]] = field(default_factory=list)
    # Deterministic undo/redo stacks for voice action-groups.
    voice_done_action_groups: list[dict[str, Any]] = field(default_factory=list)
    voice_redo_action_groups: list[dict[str, Any]] = field(default_factory=list)

    # Settings page selection + values (V1).
    settings_focused_index: int = 0
    font_size: str = "medium"  # small | medium | large
    partial_refresh_mode: str = "balanced"  # slow | balanced | fast
    full_refresh_every: int = 30  # trigger a full refresh after N partial refreshes
    wifi_enabled: bool = True
    bluetooth_enabled: bool = False
    auto_sync_enabled: bool = True
    last_sync_at: float = 0.0
    sync_state: str = "never"  # never | ok | fail
    # Runtime accepts right-angle values (0/90/180/270).
    rotation_deg: int = 0
    settings_notice: str = ""
    settings_notice_due_at: float = 0.0

    last_interaction_at: float = field(default_factory=lambda: time.time())


@dataclass
class AppState:
    model: DashboardModel
    ui: UiState = field(default_factory=UiState)

    def now(self) -> float:
        return time.time()
