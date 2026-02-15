from __future__ import annotations

from dataclasses import replace
import time
from typing import Optional

from app.core.kitchen_queue import kitchen_visible_task_indices
from app.core.state import AppState, Screen, Reminder, MenuItemId, WidgetMode


class Event:
    pass


class Rotate(Event):
    def __init__(self, delta: int):
        self.delta = 1 if delta >= 0 else -1


class Click(Event):
    pass


class LongPress(Event):
    pass


class Back(Event):
    """Back/menu key.

    TSX behavior:
    - From dashboard: opens MENU (unless TIMER active on CLOCK, in which case cancels TIMER)
    - From MENU or any detail view: returns to DASHBOARD
    """

    pass


class Tick(Event):
    """Periodic tick for idle detection and delayed actions."""

    def __init__(self, now: Optional[float] = None):
        self.now = now if now is not None else time.time()

class MemoDelta(Event):
    """Developer-only: scroll memos when the left panel is focused."""

    def __init__(self, delta: int):
        self.delta = 1 if delta >= 0 else -1


def _home_variant(theme: dict) -> str:
    # "kitchen" matches copy-of TSX. Anything else falls back to the classic reminders UI.
    return str(theme.get("home_variant") or "kitchen").strip().lower()


def _kitchen_visible_task_indices(state: AppState, theme: Optional[dict] = None) -> list[int]:
    return kitchen_visible_task_indices(state, theme)


def _items_per_page_for_layout(theme: dict) -> int:
    # Keep this logic dead-simple here; renderer will clamp if layout can't fit.
    val = theme.get("items_per_page")
    try:
        if val is None:
            return 5  # default: try to fit 5 on 800x480
        return max(1, int(val))
    except Exception:
        return 5


def _home_task_count(state: AppState) -> int:
    return len(state.model.reminders)


def _clamp_focus_home(state: AppState, items_per_page: int) -> None:
    total = _home_task_count(state)
    n = 2 + total  # clock + weather + tasks
    if n <= 0:
        state.ui.focused_index = 0
        state.ui.page = 1
        return

    state.ui.focused_index %= n
    if state.ui.focused_index >= 2:
        task_idx = state.ui.focused_index - 2
        state.ui.page = 1 + (task_idx // max(1, items_per_page))
    else:
        state.ui.page = 1


def _clamp_focus_kitchen(state: AppState, theme: Optional[dict] = None) -> None:
    # Focus queue: [LEFT_PANEL, TASK_0..] where tasks are visible+sorted by category.
    idxs = _kitchen_visible_task_indices(state, theme)
    n = 1 + len(idxs)
    if n <= 0:
        state.ui.focused_index = 0
        return
    state.ui.focused_index %= n
    state.ui.page = 1


def _toggle_task_completed(state: AppState, items_per_page: int) -> None:
    if state.ui.focused_index < 2:
        return
    idx = state.ui.focused_index - 2
    if idx < 0 or idx >= len(state.model.reminders):
        return

    r = state.model.reminders[idx]
    state.model.reminders[idx] = replace(r, completed=not r.completed)

    # Schedule reorder rather than doing it immediately (better UX + better for partial refresh later).
    state.ui.pending_reorder = True
    state.ui.reorder_due_at = time.time() + 2.0


def _toggle_task_completed_by_index(state: AppState, idx: int) -> None:
    if idx < 0 or idx >= len(state.model.reminders):
        return
    r = state.model.reminders[idx]
    state.model.reminders[idx] = replace(r, completed=not r.completed)

    # Keep the same UX as home: reorder later.
    state.ui.pending_reorder = True
    state.ui.reorder_due_at = time.time() + 2.0


def _apply_reorder(state: AppState) -> None:
    # Stable sort: incomplete first, then completed, preserve order within groups.
    before = list(state.model.reminders)
    state.model.reminders = sorted(before, key=lambda r: (r.completed, ))
    state.ui.pending_reorder = False


def reduce(state: AppState, event: Event, *, theme: Optional[dict] = None) -> AppState:
    theme = theme or {}
    variant = _home_variant(theme)
    items_per_page = _items_per_page_for_layout(theme)
    now = time.time()

    # Mutate in place (simple, fast); caller can copy if needed.
    state.ui.last_interaction_at = now if not isinstance(event, Tick) else state.ui.last_interaction_at

    if isinstance(event, Tick):
        now = event.now

        # Idle: hide focus ring after inactivity. Match TSX: timer running disables idle.
        idle_timeout_s = float(theme.get("idle_timeout_s", 30.0) or 30.0)
        if not state.ui.voice_active and not state.ui.timer_running:
            state.ui.idle = (now - state.ui.last_interaction_at) >= idle_timeout_s
        else:
            state.ui.idle = False

        # Timer countdown (seconds-based; driven by Tick to avoid per-frame assumptions).
        if state.ui.widget_mode == WidgetMode.TIMER and state.ui.timer_running and state.ui.timer_seconds > 0:
            last = float(state.ui.timer_last_tick_at or now)
            dt = max(0.0, now - last)
            if dt >= 1.0:
                dec = int(dt)
                state.ui.timer_seconds = max(0, int(state.ui.timer_seconds) - dec)
                state.ui.timer_last_tick_at = last + dec
                if state.ui.timer_seconds <= 0:
                    state.ui.timer_running = False
        else:
            state.ui.timer_last_tick_at = now

        # Delayed reorder
        if state.ui.pending_reorder and now >= state.ui.reorder_due_at:
            _apply_reorder(state)
            if state.ui.screen == Screen.HOME and variant == "kitchen":
                _clamp_focus_kitchen(state, theme)
            else:
                _clamp_focus_home(state, items_per_page)

        # Voice overlay timeout (stub)
        if state.ui.voice_active and now >= state.ui.voice_due_at:
            state.ui.voice_active = False
            if state.ui.screen == Screen.HOME and variant == "kitchen":
                _clamp_focus_kitchen(state, theme)
            else:
                _clamp_focus_home(state, items_per_page)

        # Mood memo auto-rotation (kitchen home only)
        if state.ui.screen == Screen.HOME and variant == "kitchen":
            interval_s = float(theme.get("memo_rotate_s", 6.0) or 6.0)
            if state.ui.focused_index != 0 and not state.ui.idle:
                if (now - float(state.ui.memo_last_rotated_at or now)) >= interval_s and state.model.memos:
                    state.ui.memo_index = (int(state.ui.memo_index or 0) + 1) % max(1, len(state.model.memos))
                    state.ui.memo_last_rotated_at = now

        return state

    # Any non-tick event wakes the UI
    state.ui.idle = False
    state.ui.last_interaction_at = now

    if isinstance(event, Rotate):
        if state.ui.screen == Screen.MENU:
            order = [
                MenuItemId.MEMO,
                MenuItemId.LIST,
                MenuItemId.TIMER,
                MenuItemId.CALENDAR,
                MenuItemId.SETTINGS,
            ]
            idx = order.index(state.ui.menu_focused) if state.ui.menu_focused in order else 1
            idx = (idx + event.delta) % len(order)
            state.ui.menu_focused = order[idx]
        elif state.ui.screen == Screen.HOME:
            state.ui.focused_index += event.delta
            if variant == "kitchen":
                _clamp_focus_kitchen(state, theme)
            else:
                _clamp_focus_home(state, items_per_page)
        elif state.ui.screen == Screen.WEATHER:
            n = max(1, min(4, len(state.model.weather)))
            state.ui.weather_day_index = (int(state.ui.weather_day_index) + event.delta) % n
        elif state.ui.screen == Screen.CALENDAR:
            if (state.ui.calendar_mode or "date") == "agenda":
                if state.ui.calendar_offset_days != 0:
                    state.ui.calendar_selected_index = 0
                else:
                    agenda_len = len(state.model.calendar) + len(state.model.reminders)
                    if agenda_len <= 0:
                        state.ui.calendar_selected_index = 0
                    else:
                        cur = int(state.ui.calendar_selected_index or 0)
                        cur = max(0, min(cur + event.delta, agenda_len - 1))
                        state.ui.calendar_selected_index = cur
            else:
                state.ui.calendar_offset_days = int(state.ui.calendar_offset_days or 0) + event.delta
        else:
            # Minimal: rotate does nothing on detail pages for now.
            pass
        return state

    if isinstance(event, MemoDelta):
        if state.ui.screen == Screen.HOME and variant == "kitchen" and state.ui.focused_index == 0 and state.model.memos:
            state.ui.memo_index = (int(state.ui.memo_index or 0) + event.delta) % max(1, len(state.model.memos))
            state.ui.memo_last_rotated_at = now
        return state

    if isinstance(event, Click):
        if state.ui.screen == Screen.MENU:
            picked = state.ui.menu_focused
            state.ui.active_menu = picked
            if picked == MenuItemId.CALENDAR:
                state.ui.screen = Screen.CALENDAR
            elif picked == MenuItemId.TIMER:
                state.ui.widget_mode = WidgetMode.TIMER
                state.ui.timer_seconds = int(theme.get("timer_default_s", 5 * 60) or 5 * 60)
                state.ui.timer_running = True
                state.ui.timer_last_tick_at = now
                state.ui.screen = Screen.HOME
                state.ui.focused_index = 0  # focus clock
                if variant == "kitchen":
                    _clamp_focus_kitchen(state, theme)
                else:
                    _clamp_focus_home(state, items_per_page)
            elif picked == MenuItemId.LIST:
                state.ui.screen = Screen.HOME
                if variant == "kitchen":
                    _clamp_focus_kitchen(state, theme)
                else:
                    _clamp_focus_home(state, items_per_page)
            else:
                state.ui.screen = Screen.PLACEHOLDER
            return state

        if state.ui.screen == Screen.HOME:
            if variant == "kitchen":
                if state.ui.focused_index == 0:
                    if state.ui.widget_mode == WidgetMode.TIMER:
                        state.ui.timer_running = not state.ui.timer_running
                        state.ui.timer_last_tick_at = now
                    else:
                        state.ui.screen = Screen.WEATHER
                        state.ui.weather_day_index = 0
                else:
                    idxs = _kitchen_visible_task_indices(state, theme)
                    pos = int(state.ui.focused_index) - 1
                    if 0 <= pos < len(idxs):
                        _toggle_task_completed_by_index(state, idxs[pos])
                        _clamp_focus_kitchen(state, theme)
                return state

            # classic home
            if state.ui.focused_index == 0:
                if state.ui.widget_mode == WidgetMode.TIMER:
                    state.ui.timer_running = not state.ui.timer_running
                    state.ui.timer_last_tick_at = now
                else:
                    state.ui.screen = Screen.CALENDAR
                    state.ui.calendar_offset_days = 0
                    state.ui.calendar_mode = "date"
                    state.ui.calendar_selected_index = 0
            elif state.ui.focused_index == 1:
                state.ui.screen = Screen.WEATHER
                state.ui.weather_day_index = 0
            else:
                _toggle_task_completed(state, items_per_page)
        elif state.ui.screen == Screen.CALENDAR:
            # Click toggles calendar mode (date <-> agenda) or toggles selected task in agenda mode.
            if (state.ui.calendar_mode or "date") == "date":
                state.ui.calendar_mode = "agenda"
                state.ui.calendar_selected_index = 0
            else:
                if state.ui.calendar_offset_days != 0:
                    # Free-day screen: click returns to date mode so user can continue navigating dates.
                    state.ui.calendar_mode = "date"
                else:
                    n_events = len(state.model.calendar)
                    idx = int(state.ui.calendar_selected_index or 0)
                    if idx >= n_events:
                        task_idx = idx - n_events
                        _toggle_task_completed_by_index(state, task_idx)
        else:
            # Detail/placeholder: click does nothing; Back is the exit (TSX).
            pass
        return state

    if isinstance(event, LongPress):
        # Voice overlay stub: show listening overlay briefly, then return.
        state.ui.voice_active = True
        state.ui.voice_due_at = now + 2.0
        return state

    if isinstance(event, Back):
        if state.ui.voice_active:
            state.ui.voice_active = False
            return state

        if state.ui.screen == Screen.HOME:
            # TSX: Back cancels timer when focused on clock, otherwise opens menu.
            if state.ui.widget_mode == WidgetMode.TIMER and state.ui.focused_index == 0:
                state.ui.timer_running = False
                state.ui.widget_mode = WidgetMode.CLOCK
                state.ui.timer_seconds = 0
                state.ui.timer_last_tick_at = now
                return state
            state.ui.screen = Screen.MENU
            return state

        if state.ui.screen != Screen.HOME:
            state.ui.screen = Screen.HOME
            if variant == "kitchen":
                _clamp_focus_kitchen(state, theme)
            else:
                _clamp_focus_home(state, items_per_page)
        return state

    return state
