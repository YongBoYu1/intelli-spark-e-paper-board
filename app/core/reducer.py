from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta
import secrets
import time
from typing import Optional

from app.core.calendar_utils import event_indices_for_date
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


def _normalized_right_angle(raw) -> int:
    try:
        deg = int(raw or 0)
    except (ValueError, TypeError):
        deg = 0
    return (((deg % 360) + 45) // 90 * 90) % 360


def _resolved_home_variant(theme: dict, *, rotation_deg: int = 0) -> str:
    variant = _home_variant(theme)
    rot = _normalized_right_angle(rotation_deg)
    # Keep reducer interaction semantics aligned with renderer variant fallback.
    if variant == "kitchen_portrait" and rot in (0, 180):
        return "kitchen"
    return variant


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
    variant = _resolved_home_variant(theme or {}, rotation_deg=int(state.ui.rotation_deg or 0))
    if variant == "kitchen_portrait":
        # Portrait queue: [LEFT_PANEL, VISIBLE_TASKS...]
        n = 1 + len(_kitchen_visible_task_indices(state, theme))
    else:
        # Landscape queue: [LEFT_PANEL, INVENTORY_HEADER, INVENTORY_ITEMS..., REMINDERS_HEADER, REMINDERS_ITEMS...]
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


def _list_section_indices(state: AppState) -> tuple[list[int], list[int]]:
    inventory: list[int] = []
    reminders: list[int] = []
    for i, r in enumerate(state.model.reminders):
        if str(r.category or "") == "fridge":
            inventory.append(i)
        else:
            reminders.append(i)
    return inventory, reminders


def _list_focus_order(state: AppState) -> list[int]:
    inventory, reminders = _list_section_indices(state)
    return inventory + reminders


def _clamp_focus_list(state: AppState, *, prefer_section: str | None = None) -> None:
    inventory, reminders = _list_section_indices(state)
    order = inventory + reminders
    if not order:
        state.ui.list_focused_index = 0
        return

    prefer = str(prefer_section or "").strip().lower()
    if prefer == "inventory":
        state.ui.list_focused_index = 0
        return
    if prefer == "reminders":
        if reminders:
            state.ui.list_focused_index = len(inventory)
            return
        state.ui.list_focused_index = 0
        return

    cur = int(state.ui.list_focused_index or 0)
    state.ui.list_focused_index = max(0, min(cur, len(order) - 1))


def _selected_list_item_model_index(state: AppState) -> int | None:
    order = _list_focus_order(state)
    if not order:
        return None
    idx = max(0, min(int(state.ui.list_focused_index or 0), len(order) - 1))
    state.ui.list_focused_index = idx
    return order[idx]


def _calendar_cursor_date(state: AppState, *, base_date: date | None = None) -> date:
    base = base_date if isinstance(base_date, date) else datetime.now().date()
    offset = int(state.ui.calendar_offset_days or 0)
    return base + timedelta(days=offset)


def _calendar_selected_indices(state: AppState, *, base_date: date | None = None) -> tuple[list[int], list[int]]:
    base = base_date if isinstance(base_date, date) else datetime.now().date()
    target = _calendar_cursor_date(state, base_date=base)
    event_indices = event_indices_for_date(state.model.calendar, target_date=target, base_date=base)
    reminder_indices = event_indices_for_date(state.model.reminders, target_date=target, base_date=base)
    return event_indices, reminder_indices


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


def _onboarding_qr_ttl_s(theme: dict) -> float:
    try:
        value = float(theme.get("onboarding_qr_ttl_s", 5 * 60) or (5 * 60))
    except Exception:
        value = 5 * 60
    return max(30.0, value)


def _new_pair_token() -> str:
    return secrets.token_hex(4).upper()


def _onboarding_voice_cases() -> list[tuple[str, str]]:
    # Demo-only script shown during first-boot guide.
    return [
        ("Add milk to inventory", "Add inventory"),
        ("Remind me to check fridge tonight", "Add reminder"),
        ("Set a timer for 10 minutes", "Set timer"),
    ]


def _onboarding_voice_total() -> int:
    return len(_onboarding_voice_cases())


def _onboarding_voice_case(index: int) -> tuple[str, str]:
    cases = _onboarding_voice_cases()
    total = max(1, len(cases))
    idx = max(0, min(total - 1, int(index)))
    return cases[idx]


def _onboarding_voice_current_index(state: AppState) -> int:
    return max(0, int(state.ui.onboarding_voice_demo_case_index or 0))


def _onboarding_voice_complete(state: AppState) -> bool:
    return _onboarding_voice_current_index(state) >= _onboarding_voice_total()


def _sync_onboarding_voice_case_fields(state: AppState) -> None:
    total = _onboarding_voice_total()
    idx = max(0, min(total - 1, _onboarding_voice_current_index(state)))
    sample, action = _onboarding_voice_case(idx)
    state.ui.onboarding_voice_sample_text = sample
    state.ui.onboarding_voice_expected_action = action


def _advance_onboarding_voice_case(state: AppState) -> None:
    state.ui.onboarding_voice_demo_case_index = _onboarding_voice_current_index(state) + 1
    if not _onboarding_voice_complete(state):
        _sync_onboarding_voice_case_fields(state)


def _set_onboarding_voice_prompt(state: AppState) -> None:
    total = _onboarding_voice_total()
    if _onboarding_voice_complete(state):
        state.ui.onboarding_status = "All 3 voice samples completed. Press click to continue."
        return
    _sync_onboarding_voice_case_fields(state)
    idx = _onboarding_voice_current_index(state)
    sample = str(state.ui.onboarding_voice_sample_text or "").strip()
    state.ui.onboarding_status = f"Sample {idx + 1}/{total}: Hold voice key and say: {sample}."


def apply_onboarding_voice_demo_result(state: AppState, transcript: str) -> None:
    if str(state.ui.onboarding_step or "").strip().lower() != "voice_guide":
        return

    if _onboarding_voice_complete(state):
        state.ui.onboarding_status = "All 3 voice samples completed. Press click to continue."
        state.ui.onboarding_voice_guide_focus_index = 0
        return

    total = _onboarding_voice_total()
    state.ui.onboarding_voice_demo_attempted = True
    heard = str(transcript or "").strip()
    idx = _onboarding_voice_current_index(state)
    sample, action = _onboarding_voice_case(idx)
    state.ui.onboarding_voice_sample_text = sample
    state.ui.onboarding_voice_expected_action = action

    if not heard:
        state.ui.onboarding_voice_demo_heard = "(no speech detected)"
        state.ui.onboarding_voice_demo_action = ""
        state.ui.onboarding_status = f"No speech detected. Retry sample {idx + 1}/{total}."
        state.ui.onboarding_voice_guide_focus_index = 0
        return

    state.ui.onboarding_voice_demo_heard = heard
    state.ui.onboarding_voice_demo_action = action
    mask = int(state.ui.onboarding_voice_demo_pass_mask or 0)
    mask |= (1 << idx)
    state.ui.onboarding_voice_demo_pass_mask = mask
    _advance_onboarding_voice_case(state)

    if _onboarding_voice_complete(state):
        state.ui.onboarding_status = "All 3 voice samples completed. Press click to continue."
        state.ui.onboarding_voice_guide_focus_index = 0
        _sync_onboarding_voice_case_fields(state)
        return

    nxt = _onboarding_voice_current_index(state)
    nxt_sample = str(state.ui.onboarding_voice_sample_text or "").strip()
    state.ui.onboarding_status = f"Sample {idx + 1}/{total} complete. Next {nxt + 1}/{total}: {nxt_sample}"
    state.ui.onboarding_voice_guide_focus_index = 0


def apply_onboarding_voice_demo_error(state: AppState, reason: str) -> None:
    if str(state.ui.onboarding_step or "").strip().lower() != "voice_guide":
        return
    state.ui.onboarding_voice_demo_attempted = True
    state.ui.onboarding_voice_demo_heard = ""
    state.ui.onboarding_voice_demo_action = ""
    idx = min(_onboarding_voice_current_index(state), max(0, _onboarding_voice_total() - 1))
    total = _onboarding_voice_total()
    msg = str(reason or "").strip()
    if msg:
        state.ui.onboarding_status = f"Voice demo failed: {msg}. Retry sample {idx + 1}/{total}."
    else:
        state.ui.onboarding_status = f"Voice demo failed. Retry sample {idx + 1}/{total}."
    state.ui.onboarding_voice_guide_focus_index = 0


def _enter_onboarding_start(state: AppState) -> None:
    state.ui.screen = Screen.ONBOARDING
    state.ui.onboarding_step = "start"
    state.ui.onboarding_focus_index = max(0, min(1, int(state.ui.onboarding_focus_index or 0)))
    state.ui.onboarding_status = ""
    state.ui.onboarding_voice_guide_focus_index = 0
    state.ui.onboarding_voice_demo_heard = ""
    state.ui.onboarding_voice_demo_attempted = False
    state.ui.onboarding_voice_demo_case_index = 0
    state.ui.onboarding_voice_demo_pass_mask = 0
    state.ui.onboarding_voice_demo_action = ""
    sample, action = _onboarding_voice_case(0)
    state.ui.onboarding_voice_sample_text = sample
    state.ui.onboarding_voice_expected_action = action
    state.ui.landing_status = ""


def _enter_onboarding_pair_qr(state: AppState, now: float, *, theme: dict) -> None:
    state.ui.screen = Screen.ONBOARDING
    state.ui.onboarding_step = "pair_qr"
    state.ui.onboarding_qr_focus_index = max(0, min(2, int(state.ui.onboarding_qr_focus_index or 0)))
    state.ui.onboarding_pair_token = _new_pair_token()
    state.ui.onboarding_pair_expires_at = float(now) + _onboarding_qr_ttl_s(theme)
    state.ui.onboarding_status = "Waiting for phone callback..."
    state.ui.onboarding_voice_guide_focus_index = 0


def _onboarding_timezone_choices(current: str) -> list[str]:
    base = [
        "America/Toronto",
        "America/New_York",
        "America/Los_Angeles",
        "UTC",
    ]
    cur = str(current or "").strip()
    if cur and cur not in base:
        return [cur] + base
    return base


def _onboarding_device_language_choices(_current: str) -> list[str]:
    # V1 placeholder options only. UI copy/i18n translation is not wired yet.
    return ["en-US", "es-ES", "fr-FR"]


def _sync_single_language(state: AppState) -> None:
    choices = _onboarding_device_language_choices(str(state.ui.device_language or "en-US"))
    dev = str(state.ui.device_language or "").strip()
    voc = str(state.ui.voice_locale or "").strip()
    if dev in choices:
        chosen = dev
    elif voc in choices:
        chosen = voc
    else:
        chosen = "en-US"
    state.ui.device_language = chosen
    state.ui.voice_locale = chosen


def _enter_onboarding_prefs(state: AppState, *, wifi_connected: bool) -> None:
    state.ui.screen = Screen.ONBOARDING
    state.ui.onboarding_step = "prefs"
    state.ui.onboarding_prefs_focus_index = max(0, min(3, int(state.ui.onboarding_prefs_focus_index or 0)))
    if wifi_connected:
        if not str(state.ui.onboarding_wifi_ssid or "").strip():
            state.ui.onboarding_wifi_ssid = "Home_2.4G"
        state.ui.wifi_enabled = True
    _sync_single_language(state)
    state.ui.onboarding_status = ""
    state.ui.onboarding_voice_guide_focus_index = 0


def _enter_onboarding_done(state: AppState) -> None:
    state.ui.screen = Screen.ONBOARDING
    state.ui.onboarding_step = "done"
    state.ui.onboarding_status = ""
    state.ui.onboarding_voice_guide_focus_index = 0


def _enter_onboarding_voice_guide(state: AppState) -> None:
    state.ui.screen = Screen.ONBOARDING
    state.ui.onboarding_step = "voice_guide"
    _sync_onboarding_voice_case_fields(state)
    state.ui.onboarding_voice_guide_focus_index = 0
    if not bool(state.ui.onboarding_voice_demo_attempted):
        _set_onboarding_voice_prompt(state)


def open_onboarding_voice_guide(state: AppState) -> None:
    # Debug/test entrypoint: jump straight into the voice guide without replaying first boot.
    state.ui.screen = Screen.ONBOARDING
    state.ui.onboarding_step = "voice_guide"
    state.ui.onboarding_focus_index = 0
    state.ui.onboarding_qr_focus_index = 0
    state.ui.onboarding_prefs_focus_index = 0
    state.ui.onboarding_voice_guide_focus_index = 0
    state.ui.onboarding_pair_token = ""
    state.ui.onboarding_pair_expires_at = 0.0
    state.ui.onboarding_voice_demo_heard = ""
    state.ui.onboarding_voice_demo_attempted = False
    state.ui.onboarding_voice_demo_case_index = 0
    state.ui.onboarding_voice_demo_pass_mask = 0
    state.ui.onboarding_voice_demo_action = ""
    state.ui.onboarding_voice_sample_text = "Add milk to inventory"
    state.ui.onboarding_voice_expected_action = "Add inventory"
    _set_onboarding_voice_prompt(state)


def _enter_home_after_boot(state: AppState, *, variant: str, theme: dict, items_per_page: int) -> None:
    state.ui.screen = Screen.HOME
    state.ui.menu_overlay_active = False
    state.ui.landing_status = ""
    if _is_kitchen_variant(variant):
        _clamp_focus_kitchen(state, theme)
    else:
        _clamp_focus_home(state, items_per_page)


def _landing_ready_for_onboarding(state: AppState, now: float) -> bool:
    _ = now
    if not bool(state.ui.landing_rotate_seen):
        return False
    if not bool(state.ui.landing_confirm_seen):
        return False
    return True


def _handle_landing_tick(state: AppState, now: float, *, theme: dict, variant: str, items_per_page: int) -> None:
    _ = now
    _landing_sync_voice_locale(state)
    if bool(state.ui.setup_completed):
        _enter_home_after_boot(state, variant=variant, theme=theme, items_per_page=items_per_page)
        return
    if not bool(state.ui.landing_rotate_seen):
        state.ui.landing_status = "Rotate knob to choose language."
    elif not bool(state.ui.landing_confirm_seen):
        lang = _voice_locale_label(state.ui.device_language)
        state.ui.landing_status = f"Language: {lang}. Press click to confirm."
    else:
        lang = _voice_locale_label(state.ui.device_language)
        state.ui.landing_status = f"Language: {lang}. Press click to start first setup."


def _handle_onboarding_tick(state: AppState, now: float, *, theme: dict) -> None:
    if str(state.ui.onboarding_step or "") != "pair_qr":
        return
    expire_at = float(state.ui.onboarding_pair_expires_at or 0.0)
    if expire_at <= 0.0 or now < expire_at:
        return
    state.ui.onboarding_pair_token = _new_pair_token()
    state.ui.onboarding_pair_expires_at = now + _onboarding_qr_ttl_s(theme)
    state.ui.onboarding_status = "QR refreshed automatically (token expired)."


def _voice_locale_label(locale: str) -> str:
    key = str(locale or "").strip()
    if key == "es-ES":
        return "Spanish"
    if key == "fr-FR":
        return "French"
    return "English"


def _landing_voice_locale_choices() -> list[str]:
    return ["en-US", "es-ES", "fr-FR"]


def _landing_sync_voice_locale(state: AppState) -> None:
    choices = _landing_voice_locale_choices()
    cur = str(state.ui.device_language or state.ui.voice_locale or "en-US")
    try:
        idx = choices.index(cur)
    except ValueError:
        idx = 0
        cur = choices[idx]
    state.ui.voice_locale = cur
    state.ui.device_language = cur
    state.ui.landing_voice_demo_index = idx


def _landing_rotate_select_voice(state: AppState, delta: int) -> None:
    choices = _landing_voice_locale_choices()
    cur_idx = int(state.ui.landing_voice_demo_index or 0)
    if cur_idx < 0 or cur_idx >= len(choices):
        _landing_sync_voice_locale(state)
        cur_idx = int(state.ui.landing_voice_demo_index or 0)
    nxt = (cur_idx + (1 if delta >= 0 else -1)) % len(choices)
    state.ui.landing_voice_demo_index = nxt
    chosen = str(choices[nxt])
    state.ui.voice_locale = chosen
    state.ui.device_language = chosen


def _handle_onboarding_rotate(state: AppState, delta: int) -> None:
    step = str(state.ui.onboarding_step or "start").strip().lower()
    d = 1 if delta >= 0 else -1
    if step == "start":
        idx = int(state.ui.onboarding_focus_index or 0)
        state.ui.onboarding_focus_index = (idx + d) % 2
        return
    if step == "pair_qr":
        idx = int(state.ui.onboarding_qr_focus_index or 0)
        state.ui.onboarding_qr_focus_index = (idx + d) % 3
        return
    if step == "prefs":
        idx = int(state.ui.onboarding_prefs_focus_index or 0)
        state.ui.onboarding_prefs_focus_index = (idx + d) % 4
        return
    if step == "voice_guide":
        return


def _handle_onboarding_click(state: AppState, now: float, *, theme: dict, variant: str, items_per_page: int) -> None:
    step = str(state.ui.onboarding_step or "start").strip().lower()
    if step == "start":
        if int(state.ui.onboarding_focus_index or 0) == 0:
            _enter_onboarding_pair_qr(state, now, theme=theme)
        else:
            _enter_onboarding_prefs(state, wifi_connected=False)
        return

    if step == "pair_qr":
        idx = int(state.ui.onboarding_qr_focus_index or 0)
        if idx == 0:
            state.ui.onboarding_pair_token = _new_pair_token()
            state.ui.onboarding_pair_expires_at = now + _onboarding_qr_ttl_s(theme)
            state.ui.onboarding_status = "QR refreshed."
        elif idx == 1:
            _enter_onboarding_prefs(state, wifi_connected=True)
        else:
            _enter_onboarding_prefs(state, wifi_connected=False)
        return

    if step == "prefs":
        idx = int(state.ui.onboarding_prefs_focus_index or 0)
        if idx == 0:
            choices = _onboarding_device_language_choices(str(state.ui.device_language or "en-US"))
            cur = str(state.ui.device_language or "en-US")
            try:
                pos = choices.index(cur)
            except ValueError:
                pos = 0
            chosen = str(choices[(pos + 1) % len(choices)])
            state.ui.device_language = chosen
            state.ui.voice_locale = chosen
            return
        if idx == 1:
            choices = _onboarding_timezone_choices(str(state.ui.device_timezone or "UTC"))
            cur = str(state.ui.device_timezone or "UTC")
            try:
                pos = choices.index(cur)
            except ValueError:
                pos = 0
            state.ui.device_timezone = str(choices[(pos + 1) % len(choices)])
            return
        if idx == 2:
            state.ui.auto_sync_enabled = not bool(state.ui.auto_sync_enabled)
            return
        _enter_onboarding_voice_guide(state)
        return

    if step == "voice_guide":
        if not _onboarding_voice_complete(state):
            idx = _onboarding_voice_current_index(state)
            total = _onboarding_voice_total()
            _advance_onboarding_voice_case(state)
            state.ui.onboarding_voice_demo_heard = ""
            state.ui.onboarding_voice_demo_action = ""
            if _onboarding_voice_complete(state):
                state.ui.onboarding_status = "All 3 voice samples completed. Press click to continue."
            else:
                nxt = _onboarding_voice_current_index(state)
                nxt_sample = str(state.ui.onboarding_voice_sample_text or "").strip()
                state.ui.onboarding_status = f"Sample {idx + 1}/{total} skipped. Next {nxt + 1}/{total}: {nxt_sample}"
            state.ui.onboarding_voice_guide_focus_index = 0
            return
        _enter_onboarding_done(state)
        return

    # done
    state.ui.setup_completed = True
    _enter_home_after_boot(state, variant=variant, theme=theme, items_per_page=items_per_page)


def _handle_onboarding_back(state: AppState) -> None:
    step = str(state.ui.onboarding_step or "start").strip().lower()
    if step == "pair_qr":
        _enter_onboarding_start(state)
        return
    if step == "prefs":
        _enter_onboarding_start(state)
        return
    if step == "voice_guide":
        state.ui.onboarding_step = "prefs"
        state.ui.onboarding_prefs_focus_index = max(0, min(3, int(state.ui.onboarding_prefs_focus_index or 0)))
        return
    if step == "done":
        state.ui.onboarding_step = "prefs"
        state.ui.onboarding_prefs_focus_index = max(0, min(3, int(state.ui.onboarding_prefs_focus_index or 0)))


def _activate_menu_pick(state: AppState, picked: MenuItemId, now: float, *, theme: dict, items_per_page: int, variant: str) -> None:
    state.ui.active_menu = picked
    state.ui.menu_overlay_active = False
    if picked == MenuItemId.MEMO:
        state.ui.screen = Screen.MEMO
        count = len(state.model.memos)
        state.ui.memo_index = (int(state.ui.memo_index or 0) % max(1, count)) if count > 0 else 0
        state.ui.memo_expanded = False
        return
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
        state.ui.screen = Screen.REMINDERS
        _clamp_focus_list(state, prefer_section="reminders")
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
    variant = _resolved_home_variant(theme, rotation_deg=int(state.ui.rotation_deg or 0))
    items_per_page = _items_per_page_for_layout(theme)
    now = time.time()

    # Mutate in place (simple, fast); caller can copy if needed.
    state.ui.last_interaction_at = now if not isinstance(event, Tick) else state.ui.last_interaction_at

    if isinstance(event, Tick):
        now = event.now
        now_minute_bucket = int(float(now) // 60.0)
        if int(state.ui.clock_minute_bucket or 0) != now_minute_bucket:
            state.ui.clock_minute_bucket = now_minute_bucket

        if state.ui.screen == Screen.LANDING:
            _handle_landing_tick(state, now, theme=theme, variant=variant, items_per_page=items_per_page)
            return state
        if state.ui.screen == Screen.ONBOARDING:
            _handle_onboarding_tick(state, now, theme=theme)
            state.ui.idle = False
            return state

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
            elif state.ui.screen in (Screen.INVENTORY, Screen.REMINDERS):
                _clamp_focus_list(state)
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

    if state.ui.screen == Screen.LANDING:
        if isinstance(event, Rotate):
            state.ui.landing_rotate_seen = True
            _landing_rotate_select_voice(state, event.delta)
            # If language changes after confirm, require one more confirm click.
            if bool(state.ui.landing_confirm_seen):
                state.ui.landing_confirm_seen = False
            if bool(state.ui.setup_completed):
                return state
            if _landing_ready_for_onboarding(state, now):
                # Keep landing on-screen; setup starts only on explicit click.
                pass
            lang = _voice_locale_label(state.ui.device_language)
            state.ui.landing_status = f"Language set to {lang}. Press click to confirm."
            return state
        if isinstance(event, Click):
            if bool(state.ui.setup_completed):
                _enter_home_after_boot(state, variant=variant, theme=theme, items_per_page=items_per_page)
            else:
                if not bool(state.ui.landing_rotate_seen):
                    state.ui.landing_status = "Rotate to choose language first, then press click."
                elif not bool(state.ui.landing_confirm_seen):
                    state.ui.landing_confirm_seen = True
                    lang = _voice_locale_label(state.ui.device_language)
                    state.ui.landing_status = f"Language confirmed: {lang}. Press click again to start setup."
                elif _landing_ready_for_onboarding(state, now):
                    _enter_onboarding_start(state)
                else:
                    state.ui.landing_status = "Press click again to start setup."
            return state
        if isinstance(event, RotateButton):
            _toggle_rotation(state)
            return state
        return state

    if state.ui.screen == Screen.ONBOARDING:
        if isinstance(event, Rotate):
            _handle_onboarding_rotate(state, event.delta)
            return state
        if isinstance(event, Click):
            _handle_onboarding_click(
                state,
                now,
                theme=theme,
                variant=variant,
                items_per_page=items_per_page,
            )
            return state
        if isinstance(event, Back) or isinstance(event, LongPress):
            _handle_onboarding_back(state)
            return state
        if isinstance(event, RotateButton):
            _toggle_rotation(state)
            return state
        return state

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
                event_indices, reminder_indices = _calendar_selected_indices(state)
                agenda_len = len(event_indices) + len(reminder_indices)
                if agenda_len <= 0:
                    state.ui.calendar_selected_index = 0
                else:
                    cur = int(state.ui.calendar_selected_index or 0)
                    cur = max(0, min(cur + event.delta, agenda_len - 1))
                    state.ui.calendar_selected_index = cur
            else:
                state.ui.calendar_offset_days = int(state.ui.calendar_offset_days or 0) + event.delta
        elif state.ui.screen == Screen.MEMO:
            memo_count = len(state.model.memos)
            if memo_count > 0:
                cur = int(state.ui.memo_index or 0)
                state.ui.memo_index = (cur + event.delta) % memo_count
                state.ui.memo_expanded = False
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
        elif state.ui.screen in (Screen.INVENTORY, Screen.REMINDERS):
            order = _list_focus_order(state)
            if order:
                cur = int(state.ui.list_focused_index or 0)
                cur = max(0, min(cur + event.delta, len(order) - 1))
                state.ui.list_focused_index = cur
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
            # Click enters agenda mode from date mode; in agenda mode it toggles selected task.
            if (state.ui.calendar_mode or "date") == "date":
                state.ui.calendar_mode = "agenda"
                state.ui.calendar_selected_index = 0
            else:
                event_indices, reminder_indices = _calendar_selected_indices(state)
                idx = int(state.ui.calendar_selected_index or 0)
                toggled = False
                if idx >= len(event_indices):
                    reminder_pos = idx - len(event_indices)
                    if 0 <= reminder_pos < len(reminder_indices):
                        _toggle_task_completed_by_index(state, reminder_indices[reminder_pos])
                        toggled = True
                # Preserve an explicit path back to date mode when agenda has no selectable reminder.
                if not toggled:
                    state.ui.calendar_mode = "date"
                    state.ui.calendar_selected_index = 0
        elif state.ui.screen == Screen.TIMER:
            _handle_timer_click(state, now, theme=theme)
        elif state.ui.screen == Screen.MEMO:
            if state.model.memos:
                state.ui.memo_expanded = not bool(state.ui.memo_expanded)
                idx = int(state.ui.memo_index or 0) % len(state.model.memos)
                current = state.model.memos[idx]
                if bool(current.is_new):
                    state.model.memos[idx] = replace(current, is_new=False)
        elif state.ui.screen == Screen.SETTINGS:
            _handle_settings_click(state, now)
        elif state.ui.screen in (Screen.INVENTORY, Screen.REMINDERS):
            selected_idx = _selected_list_item_model_index(state)
            if selected_idx is not None:
                _toggle_task_completed_by_index(state, selected_idx)
                _clamp_focus_list(state)
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
