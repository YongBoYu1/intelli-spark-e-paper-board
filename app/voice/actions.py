from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from dataclasses import replace
from typing import Any
import time

from app.core.state import AppState, MemoItem, Reminder, WidgetMode
from app.voice.policy import decide_voice_policy


ALLOWED_TOOLS = {
    "inventory_log_event",
    "inventory_set_expiry",
    "inventory_clear_all",
    "shopping_add_item",
    "shopping_remove_item",
    "shopping_clear_all",
    "timer_set",
    "memo_add",
    "no_action",
}
ALLOWED_EVENT_TYPES = {"consumed", "used", "added", "restocked", "finished"}
CONFIRM_WINDOW_S = 4.0

_ITEM_CANONICAL = {
    "milk": "milk",
    "fresh milk": "milk",
    "牛奶": "milk",
    "pizza": "pizza",
    "leftover pizza": "pizza",
    "披萨": "pizza",
    "chicken": "chicken",
    "marinated chicken": "chicken",
    "鸡肉": "chicken",
    "salad": "salad",
    "沙拉": "salad",
    "curry": "leftover curry",
    "leftover curry": "leftover curry",
    "咖喱": "leftover curry",
    "剩咖喱": "leftover curry",
    "eggs": "eggs",
    "egg": "eggs",
    "鸡蛋": "eggs",
    "bread": "bread",
    "面包": "bread",
    "yoghurt": "yoghurt",
    "yogurt": "yoghurt",
    "酸奶": "yoghurt",
}
_NOISE_WORDS = {"fresh", "leftover", "the", "a", "an", "from", "fridge", "my"}
_GENERIC_INVENTORY_MODIFIERS = {"fresh", "the", "a", "an", "my"}
_SPECIFIC_INVENTORY_MARKERS = {
    "leftover",
    "marinated",
    "cooked",
    "grilled",
    "roasted",
    "fried",
    "baked",
    "seasoned",
}


@dataclass(frozen=True)
class VoiceAction:
    tool: str
    args: dict[str, Any]


@dataclass(frozen=True)
class VoiceApplyResult:
    changed: bool
    status: str
    message: str


@dataclass(frozen=True)
class VoiceRequestMeta:
    request_id: str
    request_time: str
    timezone: str
    locale: str


def describe_voice_action(action: VoiceAction) -> str:
    tool = str(action.tool or "").strip() or "no_action"
    args = dict(action.args or {})
    if tool == "inventory_log_event":
        item = str(args.get("item_name") or "").strip() or "?"
        evt = str(args.get("event_type") or "").strip() or "?"
        return f"inventory_log_event(item={item}, event={evt})"
    if tool == "inventory_set_expiry":
        item = str(args.get("item_name") or "").strip() or "?"
        day = str(args.get("expiry_date") or "").strip() or "?"
        return f"inventory_set_expiry(item={item}, expiry={day})"
    if tool == "inventory_clear_all":
        return "inventory_clear_all"
    if tool == "shopping_add_item":
        item = str(args.get("item_name") or "").strip() or "?"
        return f"shopping_add_item(item={item})"
    if tool == "shopping_remove_item":
        item = str(args.get("item_name") or "").strip() or "?"
        return f"shopping_remove_item(item={item})"
    if tool == "shopping_clear_all":
        return "shopping_clear_all"
    if tool == "timer_set":
        secs = str(args.get("duration_seconds") or "?").strip() or "?"
        return f"timer_set(duration_seconds={secs})"
    if tool == "memo_add":
        txt = str(args.get("text") or "").strip()
        if len(txt) > 18:
            txt = txt[:15] + "..."
        return f"memo_add(text={txt or '?'})"
    if tool == "no_action":
        reason = str(args.get("reason") or "no_action").strip()
        return f"no_action({reason})"
    return tool


def parse_voice_action(payload: dict[str, Any] | None) -> VoiceAction:
    if not isinstance(payload, dict):
        return VoiceAction("no_action", {"reason": "invalid_payload"})

    action: dict[str, Any] | None = None
    if isinstance(payload.get("action"), dict):
        action = payload["action"]
    elif isinstance(payload.get("actions"), list) and payload["actions"]:
        first = payload["actions"][0]
        if isinstance(first, dict):
            action = first
    else:
        action = payload

    if not isinstance(action, dict):
        return VoiceAction("no_action", {"reason": "missing_action"})

    tool = str(action.get("tool") or action.get("name") or "").strip()
    args = action.get("args")
    if not isinstance(args, dict):
        args = action.get("arguments") if isinstance(action.get("arguments"), dict) else {}

    if tool not in ALLOWED_TOOLS:
        return VoiceAction("no_action", {"reason": "unsupported_tool"})

    if tool == "inventory_log_event":
        item_name = str(args.get("item_name") or "").strip()
        event_type = str(args.get("event_type") or "").strip().lower()
        if not item_name:
            return VoiceAction("no_action", {"reason": "missing_item_name"})
        if event_type not in ALLOWED_EVENT_TYPES:
            return VoiceAction("no_action", {"reason": "invalid_event_type"})

    if tool == "shopping_add_item":
        item_name = str(args.get("item_name") or "").strip()
        if not item_name:
            return VoiceAction("no_action", {"reason": "missing_item_name"})

    if tool == "shopping_remove_item":
        item_name = str(args.get("item_name") or "").strip()
        if not item_name:
            return VoiceAction("no_action", {"reason": "missing_item_name"})

    if tool == "inventory_set_expiry":
        item_name = str(args.get("item_name") or "").strip()
        expiry_date = str(args.get("expiry_date") or "").strip()
        if not item_name:
            return VoiceAction("no_action", {"reason": "missing_item_name"})
        if not expiry_date:
            return VoiceAction("no_action", {"reason": "missing_expiry_date"})

    if tool == "inventory_clear_all":
        if not isinstance(args, dict):
            args = {}

    if tool == "shopping_clear_all":
        if not isinstance(args, dict):
            args = {}

    if tool == "timer_set":
        raw = args.get("duration_seconds")
        try:
            secs = int(raw)
        except Exception:
            return VoiceAction("no_action", {"reason": "invalid_duration_seconds"})
        if secs <= 0:
            return VoiceAction("no_action", {"reason": "invalid_duration_seconds"})
        args = dict(args)
        args["duration_seconds"] = secs

    if tool == "memo_add":
        text = str(args.get("text") or "").strip()
        if not text:
            return VoiceAction("no_action", {"reason": "missing_memo_text"})
        args = dict(args)
        args["text"] = text

    if tool == "no_action":
        reason = str(args.get("reason") or "").strip()
        if not reason:
            args = {"reason": "no_action"}

    return VoiceAction(tool=tool, args=args)


def build_request_meta(*, locale: str = "zh-CN", tz_name: str = "UTC") -> VoiceRequestMeta:
    now = datetime.now(timezone.utc)
    return VoiceRequestMeta(
        request_id=f"voice-{int(time.time() * 1000)}",
        request_time=now.isoformat(),
        timezone=str(tz_name or "UTC"),
        locale=str(locale or "zh-CN"),
    )


def apply_voice_action(state: AppState, action: VoiceAction) -> VoiceApplyResult:
    expire_pending_voice_confirmation(state)

    if action.tool == "no_action":
        _clear_pending_voice_confirmation(state)
        reason = str(action.args.get("reason") or "no_action")
        return VoiceApplyResult(changed=False, status="done", message=f"No action: {reason}")

    if action.tool == "shopping_add_item":
        _clear_pending_voice_confirmation(state)
        title = _norm_item_name(str(action.args.get("item_name") or ""))
        if not title:
            return VoiceApplyResult(changed=False, status="error", message="Invalid shopping item")
        key = _canonical_item_key(title)
        policy = decide_voice_policy(action.tool, action.args).rule
        want_inventory_remove = bool(action.args.get("inventory_remove_if_generic_match"))
        inventory_removed_title: str | None = None
        shopping_added = False
        shopping_msg: str | None = None
        if policy.dedup:
            existing_idx = _find_shopping_item_index(state, item_key=key)
            if existing_idx >= 0:
                shopping_msg = f"Already in shopping: {state.model.reminders[existing_idx].title}"
            else:
                reminder = Reminder(
                    rid=f"s-{int(time.time() * 1000)}",
                    title=title,
                    right="VOICE",
                    completed=False,
                    category="shopping",
                    created_at=time.time(),
                )
                state.model.reminders.insert(0, reminder)
                state.ui.reminders_version = int(state.ui.reminders_version or 0) + 1
                shopping_added = True
                shopping_msg = f"Added to shopping: {title}"
        else:
            reminder = Reminder(
                rid=f"s-{int(time.time() * 1000)}",
                title=title,
                right="VOICE",
                completed=False,
                category="shopping",
                created_at=time.time(),
            )
            state.model.reminders.insert(0, reminder)
            state.ui.reminders_version = int(state.ui.reminders_version or 0) + 1
            shopping_added = True
            shopping_msg = f"Added to shopping: {title}"

        if want_inventory_remove:
            removed = _remove_matching_inventory_if_generic(state, item_key=key)
            if removed is not None:
                inventory_removed_title = removed.title
                state.ui.reminders_version = int(state.ui.reminders_version or 0) + 1

        msg = shopping_msg or f"Added to shopping: {title}"
        if inventory_removed_title:
            msg = f"{msg}; removed from inventory: {inventory_removed_title}"
        changed = shopping_added or bool(inventory_removed_title)
        return VoiceApplyResult(changed=changed, status="done", message=msg)

    if action.tool == "shopping_remove_item":
        _clear_pending_voice_confirmation(state)
        title = _norm_item_name(str(action.args.get("item_name") or ""))
        if not title:
            return VoiceApplyResult(changed=False, status="error", message="Invalid shopping item")
        removed = _remove_first_shopping_item(state, item_key=_canonical_item_key(title))
        if removed is None:
            return VoiceApplyResult(changed=False, status="done", message=f"Skipped: no matching shopping item for {title}")
        state.ui.reminders_version = int(state.ui.reminders_version or 0) + 1
        return VoiceApplyResult(changed=True, status="done", message=f"Removed from shopping: {removed.title}")

    if action.tool == "shopping_clear_all":
        policy = decide_voice_policy(action.tool, action.args).rule
        # Clear is destructive, so it always requires physical confirmation.
        if policy.require_confirm:
            _set_pending_voice_confirmation(state, action)
            return VoiceApplyResult(changed=False, status="confirm", message="Press click once within 4s to confirm clear shopping list")
        removed = _clear_shopping_items(state)
        return VoiceApplyResult(changed=removed > 0, status="done", message=f"Cleared shopping list ({removed})")

    if action.tool == "inventory_clear_all":
        policy = decide_voice_policy(action.tool, action.args).rule
        if policy.require_confirm:
            _set_pending_voice_confirmation(state, action)
            return VoiceApplyResult(changed=False, status="confirm", message="Press click once within 4s to confirm clear inventory")
        removed = _clear_inventory_items(state)
        return VoiceApplyResult(changed=removed > 0, status="done", message=f"Cleared inventory ({removed})")

    if action.tool == "inventory_log_event":
        _clear_pending_voice_confirmation(state)
        title = _norm_item_name(str(action.args.get("item_name") or ""))
        if not title:
            return VoiceApplyResult(changed=False, status="error", message="Invalid inventory item")

        event_type = str(action.args.get("event_type") or "used").strip().lower()
        if event_type not in ALLOWED_EVENT_TYPES:
            return VoiceApplyResult(changed=False, status="error", message="Invalid inventory event")
        effective_date = str(action.args.get("effective_date") or "").strip()
        key = _canonical_item_key(title)
        idx = _find_reminder_index(state, category="fridge", item_key=key)
        policy = decide_voice_policy(action.tool, {"event_type": event_type}).rule

        if event_type in ("finished",):
            if policy.require_inventory_match and idx < 0:
                return VoiceApplyResult(changed=False, status="done", message=f"Skipped: no matching inventory item for {title}")
            removed = state.model.reminders.pop(idx)
            state.ui.reminders_version = int(state.ui.reminders_version or 0) + 1
            return VoiceApplyResult(changed=True, status="done", message=f"Removed from inventory: {removed.title}")

        if event_type in ("used", "consumed"):
            if policy.require_inventory_match and idx < 0:
                return VoiceApplyResult(changed=False, status="done", message=f"Skipped: no matching inventory item for {title}")
            removed = state.model.reminders.pop(idx)
            state.ui.reminders_version = int(state.ui.reminders_version or 0) + 1
            return VoiceApplyResult(changed=True, status="done", message=f"Removed from inventory: {removed.title}")

        # added/restocked: update existing row if present, otherwise create a new fridge row.
        if idx >= 0:
            right = _inventory_badge("restocked", effective_date)
            cur = state.model.reminders[idx]
            state.model.reminders[idx] = replace(
                cur,
                right=right,
                completed=False,
                created_at=time.time(),
            )
            updated_title = state.model.reminders[idx].title
            removed_titles = _remove_matching_shopping_items(state, item_key=key) if policy.remove_matching_shopping else []
            state.ui.reminders_version = int(state.ui.reminders_version or 0) + 1
            _enforce_inventory_slots(state)
            msg = f"Updated inventory: {updated_title}"
            if removed_titles:
                msg += f"; removed from shopping: {', '.join(removed_titles[:2])}"
            return VoiceApplyResult(changed=True, status="done", message=msg)

        removed_titles = _remove_matching_shopping_items(state, item_key=key) if policy.remove_matching_shopping else []
        if removed_titles:
            state.ui.reminders_version = int(state.ui.reminders_version or 0) + 1
            # If item came from shopping list, we treat it as “task done” and do NOT auto-create in inventory.
            return VoiceApplyResult(
                changed=True,
                status="done",
                message=f"Removed from shopping: {', '.join(removed_titles[:2])}; no matching inventory item",
            )

        reminder = Reminder(
            rid=f"f-{int(time.time() * 1000)}",
            title=title,
            right=_inventory_badge("restocked", effective_date),
            completed=False,
            category="fridge",
            created_at=time.time(),
        )
        state.model.reminders.insert(0, reminder)
        removed_titles = _remove_matching_shopping_items(state, item_key=key) if policy.remove_matching_shopping else []
        state.ui.reminders_version = int(state.ui.reminders_version or 0) + 1
        _enforce_inventory_slots(state)
        msg = f"Added to inventory: {title}"
        if removed_titles:
            msg += f"; removed from shopping: {', '.join(removed_titles[:2])}"
        return VoiceApplyResult(changed=True, status="done", message=msg)

    if action.tool == "inventory_set_expiry":
        _clear_pending_voice_confirmation(state)
        title = _norm_item_name(str(action.args.get("item_name") or ""))
        expiry_date = str(action.args.get("expiry_date") or "").strip()
        if not title:
            return VoiceApplyResult(changed=False, status="error", message="Invalid inventory item")
        if not expiry_date:
            return VoiceApplyResult(changed=False, status="error", message="Missing expiry date")
        key = _canonical_item_key(title)
        idx = _find_reminder_index(state, category="fridge", item_key=key)
        policy = decide_voice_policy(action.tool, action.args).rule

        # If not found, create a new entry (expires flows should surface on the board).
        if idx < 0:
            reminder = Reminder(
                rid=f"f-{int(time.time() * 1000)}",
                title=title,
                right=_expiry_badge(expiry_date),
                completed=False,
                category="fridge",
                created_at=time.time(),
            )
            state.model.reminders.insert(0, reminder)
            state.ui.reminders_version = int(state.ui.reminders_version or 0) + 1
            _enforce_inventory_slots(state)
            return VoiceApplyResult(changed=True, status="done", message=f"Added expiry: {title}")

        cur = state.model.reminders[idx]
        state.model.reminders[idx] = replace(
            cur,
            right=_expiry_badge(expiry_date),
            completed=False,
            created_at=time.time(),
        )
        state.ui.reminders_version = int(state.ui.reminders_version or 0) + 1
        return VoiceApplyResult(changed=True, status="done", message=f"Updated expiry: {state.model.reminders[idx].title}")

    if action.tool == "timer_set":
        _clear_pending_voice_confirmation(state)
        secs = int(action.args.get("duration_seconds") or 0)
        if secs <= 0:
            return VoiceApplyResult(changed=False, status="error", message="Invalid timer duration")
        state.ui.widget_mode = WidgetMode.TIMER
        state.ui.timer_seconds = secs
        state.ui.timer_running = True
        state.ui.timer_last_tick_at = time.time()
        return VoiceApplyResult(changed=True, status="done", message=f"Timer set: {secs}s")

    if action.tool == "memo_add":
        _clear_pending_voice_confirmation(state)
        txt = str(action.args.get("text") or "").strip()
        if not txt:
            return VoiceApplyResult(changed=False, status="error", message="Empty memo")
        author = str(action.args.get("author") or "Voice").strip() or "Voice"
        memo = MemoItem(
            mid=f"m-{int(time.time() * 1000)}",
            text=txt,
            author=author,
            timestamp=time.time(),
            is_new=True,
        )
        state.model.memos.insert(0, memo)
        state.ui.memo_index = 0
        state.ui.memo_last_rotated_at = time.time()
        return VoiceApplyResult(changed=True, status="done", message="Added memo")

    return VoiceApplyResult(changed=False, status="error", message="Unsupported voice action")


def expire_pending_voice_confirmation(state: AppState, now: float | None = None) -> None:
    ts = float(now if now is not None else time.time())
    due = float(state.ui.voice_confirm_due_at or 0.0)
    if due > 0.0 and ts >= due:
        _clear_pending_voice_confirmation(state)


def has_pending_voice_confirmation(state: AppState, now: float | None = None) -> bool:
    expire_pending_voice_confirmation(state, now=now)
    return bool(state.ui.voice_confirm_tool) and float(state.ui.voice_confirm_due_at or 0.0) > float(now if now is not None else time.time())


def confirm_pending_voice_action(state: AppState, now: float | None = None) -> VoiceApplyResult | None:
    expire_pending_voice_confirmation(state, now=now)
    tool = str(state.ui.voice_confirm_tool or "").strip()
    if not tool:
        return None
    if tool == "shopping_clear_all":
        removed = _clear_shopping_items(state)
        _clear_pending_voice_confirmation(state)
        if removed <= 0:
            return VoiceApplyResult(changed=False, status="done", message="Shopping list already empty")
        return VoiceApplyResult(changed=True, status="done", message=f"Cleared shopping list ({removed})")
    if tool == "inventory_clear_all":
        removed = _clear_inventory_items(state)
        _clear_pending_voice_confirmation(state)
        if removed <= 0:
            return VoiceApplyResult(changed=False, status="done", message="Inventory already empty")
        return VoiceApplyResult(changed=True, status="done", message=f"Cleared inventory ({removed})")
    _clear_pending_voice_confirmation(state)
    return VoiceApplyResult(changed=False, status="error", message="Unsupported pending confirmation")


def _norm_item_name(value: str) -> str:
    txt = (value or "").strip()
    if not txt:
        return ""
    return " ".join([part for part in txt.split() if part])


def _canonical_item_key(value: str) -> str:
    txt = str(value or "").strip().lower()
    if not txt:
        return ""
    if txt in _ITEM_CANONICAL:
        return _ITEM_CANONICAL[txt]
    txt = re.sub(r"[^a-z0-9\u4e00-\u9fff\s]+", " ", txt)
    txt = " ".join(txt.split())
    if txt in _ITEM_CANONICAL:
        return _ITEM_CANONICAL[txt]
    for raw, canonical in _ITEM_CANONICAL.items():
        if raw and raw in txt:
            return canonical
    parts = [p for p in txt.split(" ") if p and p not in _NOISE_WORDS]
    if not parts:
        return txt
    merged = " ".join(parts)
    if merged in _ITEM_CANONICAL:
        return _ITEM_CANONICAL[merged]
    return merged


def _find_reminder_index(state: AppState, *, category: str, item_key: str) -> int:
    needle = _canonical_item_key(item_key)
    if not needle:
        return -1
    for i, r in enumerate(state.model.reminders):
        if str(r.category or "") != category:
            continue
        if _canonical_item_key(r.title) == needle:
            return i
    return -1


def _find_shopping_item_index(state: AppState, *, item_key: str) -> int:
    needle = _canonical_item_key(item_key)
    if not needle:
        return -1
    for i, r in enumerate(state.model.reminders):
        if not _is_shopping_list_item(r):
            continue
        if _canonical_item_key(r.title) == needle:
            return i
    return -1


def _set_pending_voice_confirmation(state: AppState, action: VoiceAction) -> None:
    state.ui.voice_confirm_tool = str(action.tool or "")
    state.ui.voice_confirm_payload_json = json.dumps(dict(action.args or {}), ensure_ascii=False)
    state.ui.voice_confirm_due_at = time.time() + CONFIRM_WINDOW_S


def _clear_pending_voice_confirmation(state: AppState) -> None:
    state.ui.voice_confirm_tool = ""
    state.ui.voice_confirm_payload_json = ""
    state.ui.voice_confirm_due_at = 0.0


def _clear_shopping_items(state: AppState) -> int:
    before = len(state.model.reminders)
    state.model.reminders = [r for r in state.model.reminders if not _is_shopping_list_item(r)]
    removed = before - len(state.model.reminders)
    if removed > 0:
        state.ui.reminders_version = int(state.ui.reminders_version or 0) + 1
    return removed


def _clear_inventory_items(state: AppState) -> int:
    before = len(state.model.reminders)
    state.model.reminders = [r for r in state.model.reminders if str(r.category or "") != "fridge"]
    removed = before - len(state.model.reminders)
    if removed > 0:
        state.ui.reminders_version = int(state.ui.reminders_version or 0) + 1
    return removed


def _enforce_inventory_slots(state: AppState, max_slots: int = 3) -> int:
    if max_slots <= 0:
        return 0
    fridge_items: list[tuple[int, Reminder]] = []
    for i, r in enumerate(state.model.reminders):
        if str(r.category or "") != "fridge":
            continue
        fridge_items.append((i, r))
    if len(fridge_items) <= max_slots:
        return 0

    # Keep the most recently updated/created items.
    fridge_sorted = sorted(fridge_items, key=lambda t: float(getattr(t[1], "created_at", 0.0) or 0.0), reverse=True)
    keep_indices = {idx for idx, _ in fridge_sorted[:max_slots]}

    new_list: list[Reminder] = []
    removed_titles: list[str] = []
    for i, r in enumerate(state.model.reminders):
        if str(r.category or "") == "fridge" and i not in keep_indices:
            removed_titles.append(r.title)
            continue
        new_list.append(r)

    if removed_titles:
        state.model.reminders = new_list
        state.ui.reminders_version = int(state.ui.reminders_version or 0) + 1
    return len(removed_titles)


def _remove_matching_shopping_items(state: AppState, *, item_key: str) -> list[str]:
    needle = _canonical_item_key(item_key)
    if not needle:
        return []
    removed_titles: list[str] = []
    kept: list[Reminder] = []
    for r in state.model.reminders:
        if not _is_shopping_list_item(r):
            kept.append(r)
            continue
        if _canonical_item_key(r.title) == needle:
            removed_titles.append(r.title)
            continue
        kept.append(r)
    if removed_titles:
        state.model.reminders = kept
    return removed_titles


def _remove_first_shopping_item(state: AppState, *, item_key: str) -> Reminder | None:
    needle = _canonical_item_key(item_key)
    if not needle:
        return None
    for i, r in enumerate(state.model.reminders):
        if not _is_shopping_list_item(r):
            continue
        if _canonical_item_key(r.title) != needle:
            continue
        return state.model.reminders.pop(i)
    return None


def _remove_matching_inventory_if_generic(state: AppState, *, item_key: str) -> Reminder | None:
    needle = _canonical_item_key(item_key)
    if not needle:
        return None
    for idx, row in enumerate(state.model.reminders):
        if str(row.category or "") != "fridge":
            continue
        if _canonical_item_key(row.title) != needle:
            continue
        if not _is_generic_inventory_row_for_key(row.title, needle):
            continue
        return state.model.reminders.pop(idx)
    return None


def _is_generic_inventory_row_for_key(title: str, item_key: str) -> bool:
    raw_title = str(title or "").strip().lower()
    base = _canonical_item_key(item_key)
    if not raw_title or not base:
        return False
    if _canonical_item_key(raw_title) != base:
        return False

    # Treat rows with clearly specific/prepared markers as non-generic, even if they share the same base item.
    title_tokens = _tokenize_inventory_title(raw_title)
    base_tokens = _tokenize_inventory_title(base)
    extra_tokens = [t for t in title_tokens if t not in base_tokens]
    if any(t in _SPECIFIC_INVENTORY_MARKERS for t in extra_tokens):
        return False
    meaningful_extras = [t for t in extra_tokens if t not in _GENERIC_INVENTORY_MODIFIERS]
    return len(meaningful_extras) == 0


def _tokenize_inventory_title(value: str) -> list[str]:
    txt = str(value or "").strip().lower()
    if not txt:
        return []
    txt = re.sub(r"[^a-z0-9\u4e00-\u9fff\s]+", " ", txt)
    return [p for p in txt.split() if p]


def _is_shopping_list_item(r: Reminder) -> bool:
    # Kitchen UI renders all non-fridge items in the right-side shopping list section.
    return str(r.category or "") != "fridge"


def _inventory_badge(event_type: str, effective_date: str) -> str:
    event_type = str(event_type or "used").lower()
    if event_type in ("consumed", "used"):
        prefix = "USED"
    elif event_type in ("restocked",):
        prefix = "RESTOCKED"
    else:
        prefix = "ADDED"

    d = (effective_date or "").strip()
    if not d:
        return f"{prefix} TODAY"

    try:
        day = datetime.fromisoformat(d).date()
        today = datetime.now().date()
        if day == today:
            return f"{prefix} TODAY"
        if (today - day).days == 1:
            return f"{prefix} YESTERDAY"
        return f"{prefix} {day.isoformat()}"
    except Exception:
        return f"{prefix} {d[:14]}".strip()


def _expiry_badge(expiry_date: str) -> str:
    d = str(expiry_date or "").strip()
    if not d:
        return "EXP"
    try:
        day = datetime.fromisoformat(d).date()
        today = datetime.now().date()
        delta = (day - today).days
        if delta == 0:
            return "EXP: TODAY"
        if delta == 1:
            return "EXP: TOMORROW"
        if delta > 1 and delta <= 9:
            return f"EXP: {delta} DAYS"
        return f"EXP: {day.isoformat()}"
    except Exception:
        return f"EXP: {d[:10]}".strip()
