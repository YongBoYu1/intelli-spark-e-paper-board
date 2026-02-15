from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import time
from typing import Optional


class Screen(str, Enum):
    HOME = "home"
    MENU = "menu"
    CALENDAR = "calendar"
    WEATHER = "weather"
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


@dataclass
class CalendarEvent:
    eid: str
    title: str
    when: str


@dataclass
class MemoItem:
    mid: str
    text: str
    author: str
    timestamp: float
    is_new: bool = False


@dataclass
class DashboardModel:
    location: str = "New York"
    battery: int = 84
    reminders: list[Reminder] = field(default_factory=list)
    weather: list[WeatherDay] = field(default_factory=list)
    # Minimal calendar dataset for the detail page (mobile app will provide real data later)
    calendar: list[CalendarEvent] = field(default_factory=list)
    memos: list[MemoItem] = field(default_factory=list)


@dataclass
class UiState:
    screen: Screen = Screen.HOME
    # HOME focus queue: [CLOCK, WEATHER, TASK_0..TASK_N-1]
    focused_index: int = 2  # TSX starts focused on the first task (when present)
    idle: bool = False
    # Reminder paging (derived from focus for home, but stored so renderer can show PAGE x/y)
    page: int = 1

    # MENU state (TSX: Back from dashboard opens the menu).
    menu_focused: MenuItemId = MenuItemId.LIST
    active_menu: Optional[MenuItemId] = None

    # Widget slot state (TSX: top-left is a widget slot that can show CLOCK or TIMER).
    widget_mode: WidgetMode = WidgetMode.CLOCK
    timer_seconds: int = 0
    timer_running: bool = False
    timer_last_tick_at: float = field(default_factory=lambda: time.time())

    # Detail-page navigation (rotary-driven).
    # Calendar: rotate changes date; click toggles to agenda mode; rotate selects agenda item; click toggles task.
    calendar_offset_days: int = 0
    calendar_mode: str = "date"  # "date" | "agenda"
    calendar_selected_index: int = 0

    # Weather detail: rotate cycles days in the forecast.
    weather_day_index: int = 0

    # Mood panel memo selection + auto-rotation.
    memo_index: int = 0
    memo_last_rotated_at: float = field(default_factory=lambda: time.time())
    # Last rendered focus queue for kitchen home (left panel excluded).
    kitchen_visible_rids: list[str] = field(default_factory=list)
    # Theme key used when the kitchen visible queue cache was produced.
    kitchen_visible_theme_key: str = ""

    # Delayed reorder: after toggling completion, wait a bit before moving completed to the bottom.
    pending_reorder: bool = False
    reorder_due_at: float = 0.0

    # Voice overlay stub (TSX: long press/Space enters listening overlay on the clock panel).
    voice_active: bool = False
    voice_due_at: float = 0.0

    last_interaction_at: float = field(default_factory=lambda: time.time())


@dataclass
class AppState:
    model: DashboardModel
    ui: UiState = field(default_factory=UiState)

    def now(self) -> float:
        return time.time()
