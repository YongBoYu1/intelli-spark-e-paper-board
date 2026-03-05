from __future__ import annotations

from dataclasses import replace
import time
from typing import Optional

from app.core.kitchen_queue import (
    KITCHEN_FOCUS_INVENTORY_HEADER,
    KITCHEN_FOCUS_INVENTORY_ITEM,
    KITCHEN_FOCUS_LEFT_PANEL,
    KITCHEN_FOCUS_REMINDERS_HEADER,
    KITCHEN_FOCUS_REMINDERS_ITEM,
    kitchen_focus_count,
    kitchen_focus_target,
    kitchen_visible_task_indices,
)
from app.core.settings_schema import SettingsItem, SETTINGS_ORDER
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


class RotateButton(Event):
    """Dedicated rotate button: cycles screen orientation by +90 degrees."""

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


def _is_kitchen_variant(variant: str) -> bool:
    v = str(variant or "").strip().lower()
    return v in ("kitchen", "kitchen_portrait")


def _menu_order() -> list[MenuItemId]:
    return [
        MenuItemId.MEMO,
        MenuItemId.LIST,
        MenuItemId.TIMER,
        MenuItemId.CALENDAR,
        MenuItemId.SETTINGS,
    ]


def _kitchen_visible_task_indices(state: AppState, theme: Optional[dict] = None) -> list[int]:
    return kitchen_visible_task_indices(state, theme)


def _find_reminder_index_by_rid(state: AppState, rid: str) -> int:
    key = str(rid or "").strip()
    if not key:
        return -1
    for i, r in enumerate(state.model.reminders):
        if str(r.rid or "") == key:
            return i
    return -1


def _focused_kitchen_task_index(state: AppState, theme: Optional[dict] = None) -> int:
    if int(state.ui.focused_index or 0) <= 0:
        return -1

    hold_rid = str(getattr(state.ui, "kitchen_focus_rid_override", "") or "").strip()
    if hold_rid:
        idx = _find_reminder_index_by_rid(state, hold_rid)
        if idx >= 0:
            return idx

    idxs = _kitchen_visible_task_indices(state, theme)
    pos = int(state.ui.focused_index) - 1
    if 0 <= pos < len(idxs):
        return int(idxs[pos])
    return -1


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
    # Focus queue: [LEFT_PANEL, INVENTORY_HEADER, INVENTORY_ITEMS..., REMINDERS_HEADER, REMINDERS_ITEMS...]
    n = kitchen_focus_count(state, theme)
    if n <= 0:
        state.ui.focused_index = 0
        state.ui.kitchen_focus_rid_override = ""
        return
    # Clamp instead of wrapping to avoid top<->bottom jumps that trigger large refresh regions.
    cur = int(state.ui.focused_index or 0)
    state.ui.focused_index = max(0, min(cur, n - 1))
    if int(state.ui.focused_index or 0) <= 0:
        state.ui.kitchen_focus_rid_override = ""
    state.ui.page = 1


def _toggle_task_completed(state: AppState, items_per_page: int) -> None:
    if state.ui.focused_index < 2:
        return
    idx = state.ui.focused_index - 2
    if idx < 0 or idx >= len(state.model.reminders):
        return

    r = state.model.reminders[idx]
    state.model.reminders[idx] = replace(r, completed=not r.completed)
    state.ui.reminders_version = int(state.ui.reminders_version or 0) + 1

    # Schedule reorder rather than doing it immediately (better UX + better for partial refresh later).
    state.ui.pending_reorder = True
    state.ui.reorder_due_at = time.time() + 2.0


def _toggle_task_completed_by_index(state: AppState, idx: int) -> None:
    if idx < 0 or idx >= len(state.model.reminders):
        return
    r = state.model.reminders[idx]
    state.model.reminders[idx] = replace(r, completed=not r.completed)
    state.ui.reminders_version = int(state.ui.reminders_version or 0) + 1

    # Keep the same UX as home: reorder later.
    state.ui.pending_reorder = True
    state.ui.reorder_due_at = time.time() + 2.0


def _apply_reorder(state: AppState) -> None:
    # Stable sort: incomplete first, then completed, preserve order within groups.
    before = list(state.model.reminders)
    state.model.reminders = sorted(before, key=lambda r: (r.completed, ))
    state.ui.reminders_version = int(state.ui.reminders_version or 0) + 1
    state.ui.kitchen_focus_rid_override = ""
    state.ui.pending_reorder = False


def _set_settings_notice(state: AppState, text: str, *, due_in_s: float = 2.0) -> None:
    state.ui.settings_notice = str(text or "")
    state.ui.settings_notice_due_at = time.time() + max(0.0, float(due_in_s))


def _settings_item_for_focus(state: AppState) -> SettingsItem:
    n = max(1, len(SETTINGS_ORDER))
    idx = int(state.ui.settings_focused_index or 0)
    if idx < 0:
        idx = 0
    idx = idx % n
    state.ui.settings_focused_index = idx
    return SETTINGS_ORDER[idx]


def _cycle_value(current, options: list):
    if not options:
        return current
    try:
        idx = options.index(current)
    except ValueError:
        return options[0]
    return options[(idx + 1) % len(options)]


def _handle_settings_click(state: AppState, now: float) -> None:
    item = _settings_item_for_focus(state)

    if item == SettingsItem.FONT_SIZE:
        state.ui.font_size = str(_cycle_value(str(state.ui.font_size or "medium"), ["small", "medium", "large"]))
        return

    if item == SettingsItem.PARTIAL_REFRESH:
        state.ui.partial_refresh_mode = str(
            _cycle_value(str(state.ui.partial_refresh_mode or "balanced"), ["slow", "balanced", "fast"])
        )
        return

    if item == SettingsItem.FULL_REFRESH:
        state.ui.full_refresh_every = int(_cycle_value(int(state.ui.full_refresh_every or 30), [10, 20, 30]))
        return

    if item == SettingsItem.CONNECTIVITY:
        # One switch for the combined connectivity row.
        next_on = not (bool(state.ui.wifi_enabled) and bool(state.ui.bluetooth_enabled))
        state.ui.wifi_enabled = next_on
        state.ui.bluetooth_enabled = next_on
        return

    if item == SettingsItem.AUTO_SYNC:
        state.ui.auto_sync_enabled = not bool(state.ui.auto_sync_enabled)
        return

    if item == SettingsItem.SYNC_NOW:
        # V1 placeholder: fake sync success without backend integration.
        state.ui.last_sync_at = float(now)
        state.ui.sync_state = "ok"
        _set_settings_notice(state, "FAKE SYNC COMPLETE")
        return

    if item == SettingsItem.RESET_AND_WIPE:
        _set_settings_notice(state, "NOT IMPLEMENTED")
        return

    if item == SettingsItem.ROTATION:
        _toggle_rotation(state)
        return

def _toggle_rotation(state: AppState) -> None:
    try:
        raw = int(state.ui.rotation_deg or 0)
    except Exception:
        raw = 0
    cur = (((raw % 360) + 45) // 90 * 90) % 360
    state.ui.rotation_deg = (cur + 90) % 360


def _activate_menu_pick(state: AppState, picked: MenuItemId, now: float, *, theme: dict, items_per_page: int, variant: str) -> None:
    state.ui.active_menu = picked
    state.ui.menu_overlay_active = False
    if picked == MenuItemId.CALENDAR:
        state.ui.screen = Screen.CALENDAR
        return
    if picked == MenuItemId.TIMER:
        state.ui.widget_mode = WidgetMode.TIMER
        if int(state.ui.timer_seconds or 0) <= 0:
            state.ui.timer_seconds = _timer_default_s(theme)
        state.ui.timer_target_seconds = int(state.ui.timer_seconds or 0)
        state.ui.timer_running = False
        state.ui.timer_last_tick_at = now
        state.ui.timer_focused_index = 2
        _clear_timer_alert(state)
        state.ui.screen = Screen.TIMER
        return
    if picked == MenuItemId.LIST:
        state.ui.screen = Screen.HOME
        if _is_kitchen_variant(variant):
            _clamp_focus_kitchen(state, theme)
        else:
            _clamp_focus_home(state, items_per_page)
        return
    if picked == MenuItemId.SETTINGS:
        state.ui.screen = Screen.SETTINGS
        return
    state.ui.screen = Screen.PLACEHOLDER


def _timer_default_s(theme: dict) -> int:
    try:
        value = int(theme.get("timer_default_s", 5 * 60) or (5 * 60))
    except Exception:
        value = 5 * 60
    return max(1, value)


def _timer_step_s(theme: dict) -> int:
    try:
        value = int(theme.get("timer_step_s", 60) or 60)
    except Exception:
        value = 60
    return max(1, value)


def _timer_max_s(theme: dict) -> int:
    try:
        value = int(theme.get("timer_max_s", 3 * 60 * 60) or (3 * 60 * 60))
    except Exception:
        value = 3 * 60 * 60
    return max(1, value)


def _kitchen_left_click_action(theme: dict) -> str:
    raw = str(theme.get("kitchen_left_click_action", "weather") or "weather").strip().lower()
    if raw in ("timer", "timer_toggle", "toggle_timer"):
        return "timer_toggle"
    return "weather"


def _timer_alert_show_s(theme: dict) -> float:
    try:
        value = float(theme.get("timer_alert_show_s", 6.0) or 6.0)
    except Exception:
        value = 6.0
    return max(0.6, value)


def _timer_alert_blink_period_s(theme: dict) -> float:
    try:
        value = float(theme.get("timer_alert_blink_period_s", 0.45) or 0.45)
    except Exception:
        value = 0.45
    return max(0.12, value)


def _clear_timer_alert(state: AppState) -> None:
    state.ui.timer_alert_active = False
    state.ui.timer_alert_blink_on = True
    state.ui.timer_alert_started_at = 0.0
    state.ui.timer_alert_until = 0.0


def _start_timer_alert(state: AppState, now: float, *, completed_seconds: int, theme: dict) -> None:
    done_seconds = max(1, int(completed_seconds or 0))
    state.ui.timer_last_completed_seconds = done_seconds
    state.ui.timer_alert_active = True
    state.ui.timer_alert_blink_on = True
    state.ui.timer_alert_started_at = float(now)
    state.ui.timer_alert_until = float(now) + _timer_alert_show_s(theme)


def _tick_timer_alert(state: AppState, now: float, *, theme: dict) -> None:
    if not bool(state.ui.timer_alert_active):
        return
    until = float(state.ui.timer_alert_until or 0.0)
    if until <= 0.0 or float(now) >= until:
        _clear_timer_alert(state)
        return
    started = float(state.ui.timer_alert_started_at or now)
    period = _timer_alert_blink_period_s(theme)
    phase = int(max(0.0, float(now) - started) / period)
    state.ui.timer_alert_blink_on = (phase % 2) == 0


def _clamp_timer_focus(state: AppState) -> None:
    n = 4  # [DECREASE, INCREASE, START_PAUSE, RESET]
    state.ui.timer_focused_index = int(state.ui.timer_focused_index or 0) % n


def _adjust_timer_seconds(state: AppState, delta_s: int, *, max_s: int) -> None:
    secs = int(state.ui.timer_seconds or 0) + int(delta_s)
    secs = max(0, min(int(max_s), secs))
    state.ui.timer_seconds = secs
    state.ui.timer_target_seconds = secs
    if secs <= 0:
        state.ui.timer_running = False


def _handle_timer_click(state: AppState, now: float, *, theme: dict) -> None:
    _clear_timer_alert(state)
    _clamp_timer_focus(state)
    focus = int(state.ui.timer_focused_index or 0)
    step_s = _timer_step_s(theme)
    max_s = _timer_max_s(theme)
    default_s = min(_timer_default_s(theme), max_s)

    state.ui.widget_mode = WidgetMode.TIMER

    if focus == 0:
        _adjust_timer_seconds(state, -step_s, max_s=max_s)
        state.ui.timer_last_tick_at = now
        return

    if focus == 1:
        _adjust_timer_seconds(state, +step_s, max_s=max_s)
        state.ui.timer_last_tick_at = now
        return

    if focus == 2:
        secs = int(state.ui.timer_seconds or 0)
        if bool(state.ui.timer_running):
            state.ui.timer_running = False
        else:
            if secs <= 0:
                state.ui.timer_seconds = default_s
                state.ui.timer_target_seconds = int(state.ui.timer_seconds or default_s)
            elif int(state.ui.timer_target_seconds or 0) <= 0:
                state.ui.timer_target_seconds = secs
            state.ui.timer_running = True
        state.ui.timer_last_tick_at = now
        return

    # focus == 3 => reset
    state.ui.timer_seconds = 0
    state.ui.timer_target_seconds = 0
    state.ui.timer_running = False
    state.ui.timer_last_tick_at = now


def reduce(state: AppState, event: Event, *, theme: Optional[dict] = None) -> AppState:
    theme = theme or {}
    variant = _home_variant(theme)
    items_per_page = _items_per_page_for_layout(theme)
    now = time.time()

    # Mutate in place (simple, fast); caller can copy if needed.
    state.ui.last_interaction_at = now if not isinstance(event, Tick) else state.ui.last_interaction_at

    if isinstance(event, Tick):
        now = event.now
        now_minute_bucket = int(float(now) // 60.0)
        if int(state.ui.clock_minute_bucket or 0) != now_minute_bucket:
            state.ui.clock_minute_bucket = now_minute_bucket

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
                before = int(state.ui.timer_seconds or 0)
                state.ui.timer_seconds = max(0, before - dec)
                state.ui.timer_last_tick_at = last + dec
                if state.ui.timer_seconds <= 0:
                    state.ui.timer_running = False
                    completed = int(state.ui.timer_target_seconds or 0)
                    if completed <= 0:
                        completed = before
                    _start_timer_alert(state, now, completed_seconds=completed, theme=theme)
        else:
            state.ui.timer_last_tick_at = now
        _tick_timer_alert(state, now, theme=theme)

        # Delayed reorder
        if state.ui.pending_reorder and now >= state.ui.reorder_due_at:
            _apply_reorder(state)
            if state.ui.screen == Screen.HOME and _is_kitchen_variant(variant):
                _clamp_focus_kitchen(state, theme)
            else:
                _clamp_focus_home(state, items_per_page)

        # Voice overlay timeout (stub)
        if state.ui.voice_active and float(state.ui.voice_due_at or 0.0) > 0.0 and now >= state.ui.voice_due_at:
            state.ui.voice_active = False
            state.ui.voice_phase = "idle"
            state.ui.voice_message = ""
            if state.ui.screen == Screen.HOME and _is_kitchen_variant(variant):
                _clamp_focus_kitchen(state, theme)
            else:
                _clamp_focus_home(state, items_per_page)

        # Mood memo auto-rotation (kitchen home only)
        if state.ui.screen == Screen.HOME and _is_kitchen_variant(variant):
            interval_s = float(theme.get("memo_rotate_s", 6.0) or 6.0)
            interaction_pause_s = float(theme.get("memo_rotate_pause_after_interaction_s", 2.5) or 2.5)
            in_interaction_pause = (now - float(state.ui.last_interaction_at or 0.0)) < max(0.0, interaction_pause_s)
            # While voice overlay is active, pause memo auto-rotation so it does not
            # merge with voice dirty regions and force a large full refresh.
            if state.ui.voice_active or state.ui.menu_overlay_active or in_interaction_pause:
                state.ui.memo_last_rotated_at = now
            elif state.ui.focused_index != 0 and not state.ui.idle:
                if (now - float(state.ui.memo_last_rotated_at or now)) >= interval_s and state.model.memos:
                    state.ui.memo_index = (int(state.ui.memo_index or 0) + 1) % max(1, len(state.model.memos))
                    state.ui.memo_last_rotated_at = now

        if state.ui.settings_notice and now >= float(state.ui.settings_notice_due_at or 0.0):
            state.ui.settings_notice = ""
            state.ui.settings_notice_due_at = 0.0

        return state

    # Any non-tick event wakes the UI
    state.ui.idle = False
    state.ui.last_interaction_at = now

    if isinstance(event, Rotate):
        if state.ui.screen == Screen.MENU or (state.ui.screen == Screen.HOME and state.ui.menu_overlay_active):
            order = _menu_order()
            idx = order.index(state.ui.menu_focused) if state.ui.menu_focused in order else 1
            idx = (idx + event.delta) % len(order)
            state.ui.menu_focused = order[idx]
        elif state.ui.screen == Screen.HOME:
            if _is_kitchen_variant(variant):
                # First rotate after click releases pinned-focus hold.
                if str(state.ui.kitchen_focus_rid_override or "").strip():
                    state.ui.kitchen_focus_rid_override = ""
                    if int(event.delta) < 0:
                        state.ui.focused_index -= 1
                else:
                    state.ui.focused_index += event.delta
                _clamp_focus_kitchen(state, theme)
            else:
                state.ui.focused_index += event.delta
                _clamp_focus_home(state, items_per_page)
        elif state.ui.screen == Screen.WEATHER:
            # Weather-page day rotation is intentionally disabled for now.
            pass
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
        elif state.ui.screen == Screen.SETTINGS:
            n = max(1, len(SETTINGS_ORDER))
            cur = int(state.ui.settings_focused_index or 0)
            if cur < 0:
                cur = 0
            state.ui.settings_focused_index = (cur + event.delta) % n
        elif state.ui.screen == Screen.TIMER:
            _clear_timer_alert(state)
            state.ui.timer_focused_index = int(state.ui.timer_focused_index or 0) + event.delta
            _clamp_timer_focus(state)
        else:
            # Minimal: rotate does nothing on detail pages for now.
            pass
        return state

    if isinstance(event, MemoDelta):
        if state.ui.screen == Screen.HOME and _is_kitchen_variant(variant) and state.ui.focused_index == 0 and state.model.memos:
            state.ui.memo_index = (int(state.ui.memo_index or 0) + event.delta) % max(1, len(state.model.memos))
            state.ui.memo_last_rotated_at = now
        return state

    if isinstance(event, Click):
        if state.ui.screen == Screen.MENU:
            _activate_menu_pick(state, state.ui.menu_focused, now, theme=theme, items_per_page=items_per_page, variant=variant)
            return state

        if state.ui.screen == Screen.HOME:
            if state.ui.menu_overlay_active:
                _activate_menu_pick(state, state.ui.menu_focused, now, theme=theme, items_per_page=items_per_page, variant=variant)
                return state
            if _is_kitchen_variant(variant):
                # Landscape kitchen keeps section-header actions (open inventory/reminders),
                # while portrait keeps direct list focus with click-hold behavior.
                if variant == "kitchen":
                    target_kind, target_idx = kitchen_focus_target(state, int(state.ui.focused_index or 0), theme)
                    if target_kind == KITCHEN_FOCUS_LEFT_PANEL:
                        left_click_action = _kitchen_left_click_action(theme)
                        if left_click_action == "timer_toggle" and state.ui.widget_mode == WidgetMode.TIMER:
                            state.ui.timer_running = not state.ui.timer_running
                            state.ui.timer_last_tick_at = now
                        else:
                            state.ui.screen = Screen.WEATHER
                            state.ui.weather_day_index = 0
                    elif target_kind == KITCHEN_FOCUS_INVENTORY_HEADER:
                        state.ui.screen = Screen.INVENTORY
                    elif target_kind == KITCHEN_FOCUS_REMINDERS_HEADER:
                        state.ui.screen = Screen.REMINDERS
                    elif target_kind in (KITCHEN_FOCUS_INVENTORY_ITEM, KITCHEN_FOCUS_REMINDERS_ITEM):
                        if target_idx is not None:
                            _toggle_task_completed_by_index(state, target_idx)
                            _clamp_focus_kitchen(state, theme)
                    else:
                        _clamp_focus_kitchen(state, theme)
                    return state

                # kitchen_portrait: no clickable headers, list rows map directly.
                if state.ui.focused_index == 0:
                    state.ui.kitchen_focus_rid_override = ""
                    left_click_action = _kitchen_left_click_action(theme)
                    if left_click_action == "timer_toggle" and state.ui.widget_mode == WidgetMode.TIMER:
                        state.ui.timer_running = not state.ui.timer_running
                        state.ui.timer_last_tick_at = now
                    else:
                        state.ui.screen = Screen.WEATHER
                        state.ui.weather_day_index = 0
                else:
                    task_idx = _focused_kitchen_task_index(state, theme)
                    if 0 <= task_idx < len(state.model.reminders):
                        hold_rid = str(state.model.reminders[task_idx].rid or "")
                        _toggle_task_completed_by_index(state, task_idx)
                        state.ui.kitchen_focus_rid_override = hold_rid
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
        elif state.ui.screen == Screen.TIMER:
            _handle_timer_click(state, now, theme=theme)
        elif state.ui.screen == Screen.SETTINGS:
            _handle_settings_click(state, now)
        else:
            # Detail/placeholder: click does nothing; Back is the exit (TSX).
            pass
        return state

    if isinstance(event, LongPress):
        # Single-button policy:
        # - HOME long press toggles navigation overlay
        # - Any other screen long press returns to HOME
        if state.ui.screen == Screen.HOME:
            state.ui.menu_overlay_active = not bool(state.ui.menu_overlay_active)
            if state.ui.menu_overlay_active:
                state.ui.kitchen_focus_rid_override = ""
            return state

        state.ui.screen = Screen.HOME
        state.ui.menu_overlay_active = False
        state.ui.kitchen_focus_rid_override = ""
        if _is_kitchen_variant(variant):
            _clamp_focus_kitchen(state, theme)
        else:
            _clamp_focus_home(state, items_per_page)
        return state

    if isinstance(event, RotateButton):
        _toggle_rotation(state)
        return state

    if isinstance(event, Back):
        # Back should always cancel any pending destructive voice confirmation,
        # even if the confirmation overlay has already timed out/hidden.
        state.ui.voice_confirm_tool = ""
        state.ui.voice_confirm_payload_json = ""
        state.ui.voice_confirm_due_at = 0.0
        state.ui.voice_confirm_before_snapshot = {}

        if state.ui.voice_active:
            state.ui.voice_active = False
            state.ui.voice_phase = "idle"
            state.ui.voice_message = ""
            return state

        if state.ui.screen == Screen.HOME:
            if state.ui.menu_overlay_active:
                state.ui.menu_overlay_active = False
                return state
            # TSX: Back cancels timer when focused on clock, otherwise opens menu.
            if state.ui.widget_mode == WidgetMode.TIMER and state.ui.focused_index == 0:
                state.ui.timer_running = False
                state.ui.widget_mode = WidgetMode.CLOCK
                state.ui.timer_seconds = 0
                state.ui.timer_target_seconds = 0
                state.ui.timer_last_tick_at = now
                _clear_timer_alert(state)
                return state
            state.ui.menu_overlay_active = True
            state.ui.kitchen_focus_rid_override = ""
            return state

        if state.ui.screen != Screen.HOME:
            state.ui.screen = Screen.HOME
            state.ui.menu_overlay_active = False
            state.ui.kitchen_focus_rid_override = ""
            if _is_kitchen_variant(variant):
                _clamp_focus_kitchen(state, theme)
            else:
                _clamp_focus_home(state, items_per_page)
        return state

    return state
