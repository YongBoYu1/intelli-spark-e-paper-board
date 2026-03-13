from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from dataclasses import replace
from typing import Any
import time
import uuid
from zoneinfo import ZoneInfo

from app.core.reducer import (
    _toggle_home_kitchen_task_by_index,
    _toggle_task_completed_by_index,
    open_app_by_name,
)
from app.core.state import AppState, MemoItem, Reminder, Screen, WidgetMode
from app.voice.policy import decide_voice_policy


ALLOWED_TOOLS = {
    "open_app",
    "inventory_log_event",
    "inventory_set_expiry",
    "inventory_clear_all",
    "shopping_add_item",
    "shopping_remove_item",
    "shopping_clear_all",
    "timer_set",
    "timer_add",
    "timer_pause",
    "timer_resume",
    "timer_stop",
    "memo_add",
    "memo_delete",
    "memo_update",
    "memo_clear_all",
    "undo_last_action_group",
    "redo_last_action_group",
    "no_action",
}
ALLOWED_EVENT_TYPES = {"consumed", "used", "added", "restocked", "finished"}
CONFIRM_WINDOW_S = 4.0
VOICE_HISTORY_MAX_GROUPS = 8

_OPEN_APP_NAMES = {"home", "weather", "calendar", "timer", "memo", "reminders", "inventory", "settings"}


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
class VoicePlan:
    actions: list[VoiceAction]
    needs_clarification: bool = False
    clarification: str = ""
    response_copy: str = ""


@dataclass(frozen=True)
class VoicePlanStepResult:
    action: VoiceAction
    result: VoiceApplyResult


@dataclass(frozen=True)
class VoicePlanApplyResult:
    changed: bool
    status: str
    message: str
    executed_count: int
    total_count: int
    success_count: int
    failed_count: int
    skipped_count: int
    step_results: list[VoicePlanStepResult]


@dataclass(frozen=True)
class VoiceRequestMeta:
    request_id: str
    request_time: str
    timezone: str
    locale: str


def describe_voice_action(action: VoiceAction) -> str:
    tool = str(action.tool or "").strip() or "no_action"
    args = dict(action.args or {})
    if tool == "open_app":
        app = str(args.get("app") or "").strip() or "?"
        return f"open_app(app={app})"
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
        item = str(args.get("item_name") or "").strip()
        src = str(args.get("source") or "reminders").strip() or "reminders"
        if item:
            return f"shopping_remove_item(source={src}, item={item})"
        mode = str(args.get("position_mode") or "first").strip() or "first"
        count = int(args.get("count") or 1)
        if mode == "index":
            idx = int(args.get("index") or 0)
            return f"shopping_remove_item(source={src}, index={idx}, count={count})"
        return f"shopping_remove_item(source={src}, mode={mode}, count={count})"
    if tool == "shopping_clear_all":
        return "shopping_clear_all"
    if tool == "timer_set":
        secs = str(args.get("duration_seconds") or "?").strip() or "?"
        return f"timer_set(duration_seconds={secs})"
    if tool == "timer_add":
        secs = str(args.get("delta_seconds") or "?").strip() or "?"
        return f"timer_add(delta_seconds={secs})"
    if tool == "timer_pause":
        return "timer_pause"
    if tool == "timer_resume":
        return "timer_resume"
    if tool == "timer_stop":
        return "timer_stop"
    if tool == "memo_add":
        txt = str(args.get("text") or "").strip()
        if len(txt) > 18:
            txt = txt[:15] + "..."
        return f"memo_add(text={txt or '?'})"
    if tool == "memo_delete":
        target = str(args.get("target") or "latest").strip() or "latest"
        if target == "index":
            idx = int(args.get("index") or 0)
            return f"memo_delete(index={idx})"
        if target == "author":
            author = str(args.get("author") or "").strip() or "?"
            return f"memo_delete(author={author})"
        return "memo_delete(latest)"
    if tool == "memo_update":
        target = str(args.get("target") or "latest").strip() or "latest"
        txt = str(args.get("text") or "").strip()
        if len(txt) > 18:
            txt = txt[:15] + "..."
        if target == "index":
            idx = int(args.get("index") or 0)
            return f"memo_update(index={idx}, text={txt or '?'})"
        if target == "author":
            author = str(args.get("author") or "").strip() or "?"
            return f"memo_update(author={author}, text={txt or '?'})"
        return f"memo_update(latest, text={txt or '?'})"
    if tool == "memo_clear_all":
        return "memo_clear_all"
    if tool == "undo_last_action_group":
        return "undo_last_action_group"
    if tool == "redo_last_action_group":
        return "redo_last_action_group"
    if tool == "no_action":
        reason = str(args.get("reason") or "no_action").strip()
        return f"no_action({reason})"
    return tool


def parse_voice_plan(payload: dict[str, Any] | None) -> VoicePlan:
    if not isinstance(payload, dict):
        return VoicePlan(actions=[VoiceAction("no_action", {"reason": "invalid_payload"})])

    plan_obj = payload.get("plan") if isinstance(payload.get("plan"), dict) else payload
    needs_clarification = bool(plan_obj.get("needs_clarification") or payload.get("needs_clarification"))
    clarification = str(plan_obj.get("clarification") or payload.get("clarification") or "").strip()
    response_copy = str(plan_obj.get("response_copy") or payload.get("response_copy") or "").strip()

    raw_actions: list[dict[str, Any]] = []
    if isinstance(plan_obj.get("actions"), list):
        for row in plan_obj.get("actions") or []:
            if isinstance(row, dict):
                raw_actions.append(dict(row))
    elif isinstance(payload.get("actions"), list):
        for row in payload.get("actions") or []:
            if isinstance(row, dict):
                raw_actions.append(dict(row))
    elif isinstance(payload.get("action"), dict):
        raw_actions.append(dict(payload.get("action") or {}))
    elif isinstance(payload, dict):
        # Legacy shape: payload itself is an action object.
        raw_actions.append(dict(payload))

    actions: list[VoiceAction] = []
    for row in raw_actions:
        parsed = _parse_single_voice_action(row)
        actions.append(parsed)

    if not actions:
        reason = "needs_clarification" if needs_clarification else "missing_action"
        actions = [VoiceAction("no_action", {"reason": reason})]

    return VoicePlan(
        actions=actions,
        needs_clarification=needs_clarification,
        clarification=clarification,
        response_copy=response_copy,
    )


def parse_voice_action(payload: dict[str, Any] | None) -> VoiceAction:
    plan = parse_voice_plan(payload)
    if plan.actions:
        return plan.actions[0]
    return VoiceAction("no_action", {"reason": "missing_action"})


def _parse_single_voice_action(action: dict[str, Any] | None) -> VoiceAction:
    if not isinstance(action, dict):
        return VoiceAction("no_action", {"reason": "missing_action"})

    tool = str(action.get("tool") or action.get("name") or "").strip()
    args = action.get("args")
    if not isinstance(args, dict):
        args = action.get("arguments") if isinstance(action.get("arguments"), dict) else {}

    if tool not in ALLOWED_TOOLS:
        return VoiceAction("no_action", {"reason": "unsupported_tool"})

    if tool == "open_app":
        app_name = _canonical_open_app_name(
            str(
                args.get("app")
                or args.get("app_name")
                or args.get("screen")
                or args.get("target")
                or ""
            )
        )
        if not app_name:
            return VoiceAction("no_action", {"reason": "invalid_app_name"})
        return VoiceAction("open_app", {"app": app_name})

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
        source = _parse_remove_source(args)
        if source is None:
            return VoiceAction("no_action", {"reason": "invalid_remove_source"})
        if item_name:
            args = {"item_name": item_name}
            if source != "reminders":
                args["source"] = source
        else:
            positional = _parse_positional_remove_args(args)
            if positional is None:
                return VoiceAction("no_action", {"reason": "missing_item_or_position"})
            args = positional

    if tool == "inventory_set_expiry":
        item_name = str(args.get("item_name") or "").strip()
        expiry_date = str(args.get("expiry_date") or "").strip()
        if not item_name:
            return VoiceAction("no_action", {"reason": "missing_item_name"})
        if not expiry_date:
            return VoiceAction("no_action", {"reason": "missing_expiry_date"})

    if tool in {"inventory_clear_all", "shopping_clear_all"} and not isinstance(args, dict):
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

    if tool == "timer_add":
        raw = (
            args.get("delta_seconds")
            if "delta_seconds" in args
            else args.get("add_seconds")
            if "add_seconds" in args
            else args.get("duration_seconds")
            if "duration_seconds" in args
            else args.get("seconds")
        )
        try:
            secs = int(raw)
        except Exception:
            return VoiceAction("no_action", {"reason": "invalid_duration_seconds"})
        if secs <= 0:
            return VoiceAction("no_action", {"reason": "invalid_duration_seconds"})
        args = {"delta_seconds": secs}

    if tool in {"timer_pause", "timer_resume", "timer_stop"}:
        args = {}

    if tool == "memo_add":
        text = str(args.get("text") or "").strip()
        if not text:
            return VoiceAction("no_action", {"reason": "missing_memo_text"})
        args = dict(args)
        args["text"] = text

    if tool == "memo_delete":
        target = _parse_memo_target(args)
        if target is None:
            return VoiceAction("no_action", {"reason": "missing_memo_target"})
        args = target

    if tool == "memo_update":
        text = str(args.get("text") or args.get("new_text") or args.get("content") or "").strip()
        if not text:
            return VoiceAction("no_action", {"reason": "missing_memo_text"})
        target = _parse_memo_target(args)
        if target is None:
            return VoiceAction("no_action", {"reason": "missing_memo_target"})
        args = dict(target)
        args["text"] = text

    if tool in {"undo_last_action_group", "redo_last_action_group"}:
        args = {}

    if tool == "memo_clear_all":
        args = {}

    if tool == "no_action":
        reason = str(args.get("reason") or "").strip()
        if not reason:
            args = {"reason": "no_action"}

    return VoiceAction(tool=tool, args=args)

def build_request_meta(*, locale: str = "en-US", tz_name: str = "UTC") -> VoiceRequestMeta:
    tz_text = str(tz_name or "UTC").strip() or "UTC"
    tz_label = tz_text
    tz_obj = timezone.utc
    try:
        if tz_text.upper() == "UTC":
            tz_label = "UTC"
            tz_obj = timezone.utc
        else:
            tz_obj = ZoneInfo(tz_text)
    except Exception:
        # Fallback to UTC if caller passes an invalid/unsupported timezone name.
        tz_label = "UTC"
        tz_obj = timezone.utc

    now = datetime.now(tz_obj)
    return VoiceRequestMeta(
        request_id=f"voice-{uuid.uuid4().hex}",
        request_time=now.isoformat(),
        timezone=tz_label,
        locale=str(locale or "en-US"),
    )


def apply_voice_plan(state: AppState, plan: VoicePlan, *, transcript: str = "") -> VoicePlanApplyResult:
    if not isinstance(plan, VoicePlan):
        plan = VoicePlan(actions=[VoiceAction("no_action", {"reason": "invalid_plan"})])

    before_snapshot = _capture_undo_snapshot(state)
    step_results: list[VoicePlanStepResult] = []
    changed = False
    success_count = 0
    failed_count = 0
    skipped_count = 0
    hit_confirm = False

    for action in list(plan.actions or []):
        result = apply_voice_action(state, action)
        step_results.append(VoicePlanStepResult(action=action, result=result))
        changed = changed or bool(result.changed)

        st = str(result.status or "").strip().lower()
        if st == "confirm":
            hit_confirm = True
            break
        if st == "error":
            failed_count += 1
            continue
        if action.tool == "no_action" or not bool(result.changed):
            skipped_count += 1
        else:
            success_count += 1

    executed_count = len(step_results)
    total_count = len(list(plan.actions or []))

    status = "done"
    if hit_confirm:
        status = "confirm"
    elif failed_count > 0 and success_count <= 0 and skipped_count <= 0:
        status = "error"

    message = _compose_voice_plan_message(
        plan=plan,
        step_results=step_results,
        status=status,
        success_count=success_count,
        failed_count=failed_count,
        skipped_count=skipped_count,
    )

    is_history_control_plan = all(
        str(step.action.tool or "").strip() in {"undo_last_action_group", "redo_last_action_group"}
        for step in step_results
    ) and bool(step_results)
    if _should_record_undo_history(step_results, status=status) and not is_history_control_plan:
        after_snapshot = _capture_undo_snapshot(state)
        _push_undo_history_group(
            state,
            transcript=transcript,
            step_results=step_results,
            status=status,
            message=message,
            before_snapshot=before_snapshot,
            after_snapshot=after_snapshot,
        )

    _push_recent_voice_action_group(
        state,
        transcript=transcript,
        step_results=step_results,
        status=status,
        message=message,
    )

    return VoicePlanApplyResult(
        changed=changed,
        status=status,
        message=message,
        executed_count=executed_count,
        total_count=total_count,
        success_count=success_count,
        failed_count=failed_count,
        skipped_count=skipped_count,
        step_results=step_results,
    )


def apply_voice_action(state: AppState, action: VoiceAction) -> VoiceApplyResult:
    expire_pending_voice_confirmation(state)

    if action.tool == "no_action":
        _clear_pending_voice_confirmation(state)
        reason = str(action.args.get("reason") or "no_action")
        status, message = _format_no_action_feedback(reason)
        return VoiceApplyResult(changed=False, status=status, message=message)

    if action.tool == "undo_last_action_group":
        _clear_pending_voice_confirmation(state)
        return _undo_last_action_group(state)

    if action.tool == "redo_last_action_group":
        _clear_pending_voice_confirmation(state)
        return _redo_last_action_group(state)

    if action.tool == "open_app":
        _clear_pending_voice_confirmation(state)
        app_name = _canonical_open_app_name(str(action.args.get("app") or ""))
        if not app_name:
            return VoiceApplyResult(changed=False, status="error", message="Invalid app target")
        changed = open_app_by_name(state, app_name, now=time.time(), theme={})
        return VoiceApplyResult(changed=changed, status="done", message=f"Opened {app_name}")

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
        source = str(action.args.get("source") or "reminders").strip().lower() or "reminders"
        if source not in {"reminders", "inventory"}:
            return VoiceApplyResult(changed=False, status="error", message="Invalid remove source")
        if title:
            key = _canonical_item_key(title)
            if source == "inventory":
                idx = _find_reminder_index(state, category="fridge", item_key=key)
                if idx < 0:
                    return VoiceApplyResult(changed=False, status="done", message=f"Skipped: no matching inventory item for {title}")
                changed = _mark_voice_completed(state, idx, now_ts=time.time())
                if not changed:
                    return VoiceApplyResult(changed=False, status="done", message=f"Skipped: inventory item already completed: {state.model.reminders[idx].title}")
                return VoiceApplyResult(changed=True, status="done", message=f"Marked done in inventory: {state.model.reminders[idx].title}")

            idx = _find_shopping_item_index(state, item_key=key)
            if idx < 0:
                return VoiceApplyResult(changed=False, status="done", message=f"Skipped: no matching shopping item for {title}")
            changed = _mark_voice_completed(state, idx, now_ts=time.time())
            if not changed:
                return VoiceApplyResult(changed=False, status="done", message=f"Skipped: item already completed: {state.model.reminders[idx].title}")
            return VoiceApplyResult(changed=True, status="done", message=f"Marked done in reminders: {state.model.reminders[idx].title}")

        position_mode = str(action.args.get("position_mode") or "").strip().lower()
        count = int(action.args.get("count") or 1)
        index = int(action.args.get("index") or 0)
        if source not in {"reminders", "inventory"} or position_mode not in {"first", "last", "index"}:
            return VoiceApplyResult(changed=False, status="error", message="Invalid positional remove arguments")
        if count <= 0:
            return VoiceApplyResult(changed=False, status="error", message="Invalid positional count")
        if position_mode == "index" and index <= 0:
            return VoiceApplyResult(changed=False, status="error", message="Invalid positional index")

        candidates = _reminder_indices_for_source(state, source)
        selected = _select_indices_by_position(
            candidates,
            position_mode=position_mode,
            count=count,
            index=index,
        )
        if not selected:
            return VoiceApplyResult(changed=False, status="done", message="Skipped: no matching positional items")
        changed_count = 0
        titles: list[str] = []
        for model_idx in selected:
            row = state.model.reminders[model_idx]
            if _mark_voice_completed(state, model_idx, now_ts=time.time()):
                changed_count += 1
                titles.append(str(row.title or ""))
        if changed_count <= 0:
            return VoiceApplyResult(changed=False, status="done", message="Skipped: selected items already completed")
        if changed_count < count:
            return VoiceApplyResult(
                changed=True,
                status="done",
                message=f"Marked done ({changed_count}/{count} requested): {', '.join(titles[:3])}",
            )
        return VoiceApplyResult(
            changed=True,
            status="done",
            message=f"Marked done ({changed_count}): {', '.join(titles[:3])}",
        )

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
            changed = _mark_voice_completed(state, idx, now_ts=time.time())
            if not changed:
                return VoiceApplyResult(changed=False, status="done", message=f"Skipped: inventory item already completed: {state.model.reminders[idx].title}")
            return VoiceApplyResult(changed=True, status="done", message=f"Marked done in inventory: {state.model.reminders[idx].title}")

        if event_type in ("used", "consumed"):
            if policy.require_inventory_match and idx < 0:
                return VoiceApplyResult(changed=False, status="done", message=f"Skipped: no matching inventory item for {title}")
            changed = _mark_voice_completed(state, idx, now_ts=time.time())
            if not changed:
                return VoiceApplyResult(changed=False, status="done", message=f"Skipped: inventory item already completed: {state.model.reminders[idx].title}")
            return VoiceApplyResult(changed=True, status="done", message=f"Marked done in inventory: {state.model.reminders[idx].title}")

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
        state.ui.screen = Screen.TIMER
        state.ui.timer_seconds = secs
        state.ui.timer_running = True
        state.ui.timer_last_tick_at = time.time()
        return VoiceApplyResult(changed=True, status="done", message=f"Timer set: {secs}s")

    if action.tool == "timer_add":
        _clear_pending_voice_confirmation(state)
        delta = int(action.args.get("delta_seconds") or 0)
        if delta <= 0:
            return VoiceApplyResult(changed=False, status="error", message="Invalid timer duration")
        now_ts = time.time()
        cur = max(0, int(state.ui.timer_seconds or 0))
        next_secs = min(24 * 3600, cur + delta)
        if next_secs <= 0:
            return VoiceApplyResult(changed=False, status="done", message="Timer has no remaining time")
        prev_target = int(state.ui.timer_target_seconds or 0)
        if prev_target > 0:
            next_target = min(24 * 3600, prev_target + delta)
        else:
            next_target = next_secs
        state.ui.widget_mode = WidgetMode.TIMER
        state.ui.screen = Screen.TIMER
        state.ui.timer_seconds = next_secs
        state.ui.timer_target_seconds = next_target
        state.ui.timer_last_tick_at = now_ts
        return VoiceApplyResult(changed=True, status="done", message=f"Timer +{delta}s")

    if action.tool == "timer_pause":
        _clear_pending_voice_confirmation(state)
        now_ts = time.time()
        state.ui.widget_mode = WidgetMode.TIMER
        state.ui.screen = Screen.TIMER
        state.ui.timer_last_tick_at = now_ts
        if not bool(state.ui.timer_running):
            return VoiceApplyResult(changed=False, status="done", message="Timer already paused")
        state.ui.timer_running = False
        return VoiceApplyResult(changed=True, status="done", message="Timer paused")

    if action.tool == "timer_resume":
        _clear_pending_voice_confirmation(state)
        now_ts = time.time()
        state.ui.widget_mode = WidgetMode.TIMER
        state.ui.screen = Screen.TIMER
        secs = max(0, int(state.ui.timer_seconds or 0))
        if secs <= 0:
            state.ui.timer_running = False
            state.ui.timer_last_tick_at = now_ts
            return VoiceApplyResult(changed=False, status="done", message="Timer has no remaining time")
        if bool(state.ui.timer_running):
            state.ui.timer_last_tick_at = now_ts
            return VoiceApplyResult(changed=False, status="done", message="Timer already running")
        state.ui.timer_running = True
        if int(state.ui.timer_target_seconds or 0) <= 0:
            state.ui.timer_target_seconds = secs
        state.ui.timer_last_tick_at = now_ts
        return VoiceApplyResult(changed=True, status="done", message="Timer resumed")

    if action.tool == "timer_stop":
        _clear_pending_voice_confirmation(state)
        now_ts = time.time()
        prev_secs = max(0, int(state.ui.timer_seconds or 0))
        was_running = bool(state.ui.timer_running)
        state.ui.widget_mode = WidgetMode.TIMER
        state.ui.screen = Screen.TIMER
        state.ui.timer_seconds = 0
        state.ui.timer_target_seconds = 0
        state.ui.timer_running = False
        state.ui.timer_last_tick_at = now_ts
        changed = was_running or prev_secs > 0
        return VoiceApplyResult(changed=changed, status="done", message="Timer stopped")

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

    if action.tool == "memo_delete":
        _clear_pending_voice_confirmation(state)
        target = str(action.args.get("target") or "latest").strip().lower()
        author = str(action.args.get("author") or "").strip()
        memos = list(state.model.memos or [])
        if not memos:
            return VoiceApplyResult(changed=False, status="done", message="Skipped: no memos")
        idx = _resolve_memo_index(
            memos=memos,
            target=target,
            index=int(action.args.get("index") or 0),
            author=author,
        )
        if idx < 0 or idx >= len(memos):
            if target == "author":
                return VoiceApplyResult(changed=False, status="done", message=f"Skipped: no memo from {author or 'that author'}")
            return VoiceApplyResult(changed=False, status="done", message="Skipped: memo target out of range")
        removed = state.model.memos.pop(idx)
        if state.model.memos:
            state.ui.memo_index = min(int(state.ui.memo_index or 0), len(state.model.memos) - 1)
        else:
            state.ui.memo_index = 0
        state.ui.memo_last_rotated_at = time.time()
        return VoiceApplyResult(changed=True, status="done", message=f"Deleted memo: {str(removed.text or '')[:24]}")

    if action.tool == "memo_update":
        _clear_pending_voice_confirmation(state)
        target = str(action.args.get("target") or "latest").strip().lower()
        author = str(action.args.get("author") or "").strip()
        text = str(action.args.get("text") or "").strip()
        if not text:
            return VoiceApplyResult(changed=False, status="error", message="Missing memo text")
        memos = list(state.model.memos or [])
        if not memos:
            return VoiceApplyResult(changed=False, status="done", message="Skipped: no memos")
        idx = _resolve_memo_index(
            memos=memos,
            target=target,
            index=int(action.args.get("index") or 0),
            author=author,
        )
        if idx < 0 or idx >= len(memos):
            if target == "author":
                return VoiceApplyResult(changed=False, status="done", message=f"Skipped: no memo from {author or 'that author'}")
            return VoiceApplyResult(changed=False, status="done", message="Skipped: memo target out of range")
        cur = state.model.memos[idx]
        state.model.memos[idx] = replace(cur, text=text[:240], timestamp=time.time())
        state.ui.memo_index = idx
        state.ui.memo_last_rotated_at = time.time()
        return VoiceApplyResult(changed=True, status="done", message="Updated memo")

    if action.tool == "memo_clear_all":
        policy = decide_voice_policy(action.tool, action.args).rule
        if policy.require_confirm:
            _set_pending_voice_confirmation(state, action)
            return VoiceApplyResult(changed=False, status="confirm", message="Press click once within 4s to confirm clear family board")
        removed = _clear_memo_items(state)
        return VoiceApplyResult(changed=removed > 0, status="done", message=f"Cleared family board ({removed})")

    return VoiceApplyResult(changed=False, status="error", message="Unsupported voice action")


def _format_no_action_feedback(reason: str) -> tuple[str, str]:
    txt = str(reason or "no_action").strip()
    key = txt.lower()
    if key.startswith("gemini_error:"):
        return "error", "Voice service is unavailable. Check network and try again."
    if key in {"missing_google_api_key"}:
        return "error", "Voice AI is not configured yet."
    if key in {"missing_audio_or_transcript"}:
        return "done", "I did not catch that. Hold to talk and try again."
    if key in {"insufficient_context", "ambiguous_reference"}:
        return "done", "I need more context. Say the full command."
    if key in {"invalid_app_name"}:
        return "done", "Please say which app to open."
    if key in {"missing_item_name"}:
        return "done", "Please include the item name."
    if key in {"missing_item_or_position"}:
        return "done", "Please specify an item or positional target."
    if key in {"missing_expiry_date"}:
        return "done", "Please include the expiry date."
    if key in {"missing_memo_target"}:
        return "done", "Please specify which memo to edit."
    if key in {"invalid_duration_seconds"}:
        return "done", "Please include a timer duration, like 10 minutes."
    if key in {"no_tool_to_stop_timer", "no_tool_to_pause_timer", "no_tool_to_resume_timer"}:
        return "done", "Timer action is not available yet."
    if key in {"no_tool_to_clear_all_memos"}:
        return "done", "Clearing the family board is not available yet."
    if key in {"no_function_call", "schema_validation_failed", "invalid_response_shape"}:
        return "done", "I could not interpret that. Please rephrase."
    if key in {"invalid_payload", "invalid_plan", "missing_action", "unsupported_tool"}:
        return "error", "Voice parser error. Please try again."
    if key in {"no_action", "insufficient_intent"}:
        return "done", "No actionable command heard."
    return "done", f"No action: {txt}"


def _capture_undo_snapshot(state: AppState) -> dict[str, Any]:
    reminders = [replace(r) for r in list(getattr(state.model, "reminders", []) or [])]
    memos = [replace(m) for m in list(getattr(state.model, "memos", []) or [])]
    return {
        "model": {
            "reminders": reminders,
            "memos": memos,
        },
        "ui": {
            "screen": str(getattr(getattr(state.ui, "screen", None), "value", getattr(state.ui, "screen", Screen.HOME.value))),
            "widget_mode": str(getattr(state.ui, "widget_mode", WidgetMode.CLOCK) or WidgetMode.CLOCK.value),
            "timer_seconds": int(getattr(state.ui, "timer_seconds", 0) or 0),
            "timer_running": bool(getattr(state.ui, "timer_running", False)),
            "timer_last_tick_at": float(getattr(state.ui, "timer_last_tick_at", 0.0) or 0.0),
            "memo_index": int(getattr(state.ui, "memo_index", 0) or 0),
            "memo_last_rotated_at": float(getattr(state.ui, "memo_last_rotated_at", 0.0) or 0.0),
            "reminders_version": int(getattr(state.ui, "reminders_version", 0) or 0),
        },
    }


def _restore_undo_snapshot(state: AppState, snap: dict[str, Any] | None) -> bool:
    if not isinstance(snap, dict):
        return False
    model = snap.get("model")
    ui = snap.get("ui")
    if not isinstance(model, dict) or not isinstance(ui, dict):
        return False

    reminders_raw = model.get("reminders")
    memos_raw = model.get("memos")
    if not isinstance(reminders_raw, list) or not isinstance(memos_raw, list):
        return False

    state.model.reminders = [replace(r) for r in reminders_raw if isinstance(r, Reminder)]
    state.model.memos = [replace(m) for m in memos_raw if isinstance(m, MemoItem)]

    screen_raw = str(ui.get("screen") or Screen.HOME.value).strip().lower()
    try:
        state.ui.screen = Screen(screen_raw)
    except Exception:
        state.ui.screen = Screen.HOME

    mode_raw = str(ui.get("widget_mode") or WidgetMode.CLOCK.value).strip().lower()
    if mode_raw == WidgetMode.TIMER.value:
        state.ui.widget_mode = WidgetMode.TIMER
    else:
        state.ui.widget_mode = WidgetMode.CLOCK
    state.ui.timer_seconds = int(ui.get("timer_seconds") or 0)
    state.ui.timer_running = bool(ui.get("timer_running") or False)
    state.ui.timer_last_tick_at = float(ui.get("timer_last_tick_at") or time.time())
    state.ui.memo_index = int(ui.get("memo_index") or 0)
    state.ui.memo_last_rotated_at = float(ui.get("memo_last_rotated_at") or time.time())
    state.ui.reminders_version = int(ui.get("reminders_version") or 0)
    state.ui.pending_reorder = False
    state.ui.reorder_due_at = 0.0
    return True


def _should_record_undo_history(step_results: list[VoicePlanStepResult], *, status: str) -> bool:
    if str(status or "").strip().lower() in {"confirm", "error"}:
        return False
    for step in step_results:
        tool = str(step.action.tool or "").strip()
        if tool in {"no_action", "undo_last_action_group", "redo_last_action_group"}:
            continue
        if bool(step.result.changed):
            return True
    return False


def _push_undo_history_group(
    state: AppState,
    *,
    transcript: str,
    step_results: list[VoicePlanStepResult],
    status: str,
    message: str,
    before_snapshot: dict[str, Any],
    after_snapshot: dict[str, Any],
    max_groups: int = VOICE_HISTORY_MAX_GROUPS,
) -> None:
    actions: list[dict[str, Any]] = []
    for step in step_results:
        tool = str(step.action.tool or "").strip()
        if not tool or tool in {"no_action", "undo_last_action_group", "redo_last_action_group"}:
            continue
        actions.append({"tool": tool, "args": dict(step.action.args or {})})
    if not actions:
        return

    done_groups = list(getattr(state.ui, "voice_done_action_groups", []) or [])
    done_groups.insert(
        0,
        {
            "at": time.time(),
            "transcript": str(transcript or "")[:180],
            "actions": actions[:4],
            "status": str(status or ""),
            "message": str(message or "")[:180],
            "before_snapshot": before_snapshot,
            "after_snapshot": after_snapshot,
        },
    )
    state.ui.voice_done_action_groups = done_groups[: max(1, int(max_groups))]
    # New committed actions invalidate redo history.
    state.ui.voice_redo_action_groups = []


def _push_undo_history_from_confirm(
    state: AppState,
    *,
    action: VoiceAction,
    before_snapshot: dict[str, Any],
    message: str,
) -> None:
    if not isinstance(before_snapshot, dict) or not before_snapshot:
        return
    step = VoicePlanStepResult(action=action, result=VoiceApplyResult(changed=True, status="done", message=message))
    _push_undo_history_group(
        state,
        transcript="[physical confirm]",
        step_results=[step],
        status="done",
        message=message,
        before_snapshot=before_snapshot,
        after_snapshot=_capture_undo_snapshot(state),
    )


def _undo_last_action_group(state: AppState) -> VoiceApplyResult:
    done_groups = list(getattr(state.ui, "voice_done_action_groups", []) or [])
    if not done_groups:
        return VoiceApplyResult(changed=False, status="done", message="Nothing to undo yet. Say a command first.")

    entry = dict(done_groups.pop(0) or {})
    before_snapshot = entry.get("before_snapshot")
    if not _restore_undo_snapshot(state, before_snapshot if isinstance(before_snapshot, dict) else None):
        return VoiceApplyResult(changed=False, status="error", message="Undo failed: invalid history snapshot")

    redo_groups = list(getattr(state.ui, "voice_redo_action_groups", []) or [])
    redo_groups.insert(0, entry)
    state.ui.voice_done_action_groups = done_groups[:VOICE_HISTORY_MAX_GROUPS]
    state.ui.voice_redo_action_groups = redo_groups[:VOICE_HISTORY_MAX_GROUPS]
    return VoiceApplyResult(changed=True, status="done", message="Undid last action group")


def _redo_last_action_group(state: AppState) -> VoiceApplyResult:
    redo_groups = list(getattr(state.ui, "voice_redo_action_groups", []) or [])
    if not redo_groups:
        return VoiceApplyResult(changed=False, status="done", message="Nothing to redo. Say the command again.")

    entry = dict(redo_groups.pop(0) or {})
    after_snapshot = entry.get("after_snapshot")
    if not _restore_undo_snapshot(state, after_snapshot if isinstance(after_snapshot, dict) else None):
        return VoiceApplyResult(changed=False, status="error", message="Redo failed: invalid history snapshot")

    done_groups = list(getattr(state.ui, "voice_done_action_groups", []) or [])
    done_groups.insert(0, entry)
    state.ui.voice_redo_action_groups = redo_groups[:VOICE_HISTORY_MAX_GROUPS]
    state.ui.voice_done_action_groups = done_groups[:VOICE_HISTORY_MAX_GROUPS]
    return VoiceApplyResult(changed=True, status="done", message="Redid last action group")


def _compose_voice_plan_message(
    *,
    plan: VoicePlan,
    step_results: list[VoicePlanStepResult],
    status: str,
    success_count: int,
    failed_count: int,
    skipped_count: int,
) -> str:
    use_response_copy = bool(plan.response_copy) and (
        success_count > 0
        or str(status or "").strip().lower() == "confirm"
    )
    if use_response_copy:
        base = str(plan.response_copy).strip()
    else:
        base = ""

    if not base:
        if status == "confirm" and step_results:
            base = str(step_results[-1].result.message or "Need confirmation").strip()
        elif status == "error":
            if step_results:
                base = str(step_results[-1].result.message or "").strip() or "Voice action failed"
            else:
                base = "Voice action failed"
        elif success_count > 0 and failed_count > 0:
            base = f"Partial success: {success_count} done, {failed_count} failed"
        elif success_count > 0:
            base = f"Done: {success_count} action(s)"
        elif plan.needs_clarification:
            clar = str(plan.clarification or "").strip() or "Need clarification"
            base = f"Skipped: {clar}"
        elif skipped_count > 0:
            base = ""
            for step in reversed(step_results):
                if str(step.action.tool or "").strip() == "no_action":
                    continue
                msg = str(step.result.message or "").strip()
                if msg:
                    base = msg
                    break
            if not base:
                for step in reversed(step_results):
                    if str(step.action.tool or "").strip() != "no_action":
                        continue
                    msg = str(step.result.message or "").strip()
                    if msg:
                        base = msg
                        break
            if not base:
                base = "Skipped: no actionable command"
        elif step_results:
            base = str(step_results[-1].result.message or "").strip() or "Skipped: no actionable command"
        else:
            base = "Skipped: no actionable command"

    failed_actions: list[str] = []
    for step in step_results:
        if str(step.result.status or "").strip().lower() == "error":
            failed_actions.append(describe_voice_action(step.action))
    if failed_actions and status != "error":
        base = f"{base}; failed: {', '.join(failed_actions[:2])}"
    return base


def _push_recent_voice_action_group(
    state: AppState,
    *,
    transcript: str,
    step_results: list[VoicePlanStepResult],
    status: str,
    message: str,
    max_groups: int = VOICE_HISTORY_MAX_GROUPS,
) -> None:
    actions: list[dict[str, Any]] = []
    for step in step_results:
        tool = str(step.action.tool or "").strip()
        if not tool or tool in {"no_action", "undo_last_action_group", "redo_last_action_group"}:
            continue
        actions.append({"tool": tool, "args": dict(step.action.args or {})})
    if not actions:
        return

    groups = list(getattr(state.ui, "voice_recent_action_groups", []) or [])
    groups.insert(
        0,
        {
            "at": time.time(),
            "transcript": str(transcript or "")[:180],
            "actions": actions[:4],
            "status": str(status or ""),
            "message": str(message or "")[:180],
        },
    )
    state.ui.voice_recent_action_groups = groups[: max(1, int(max_groups))]


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
    payload_args: dict[str, Any] = {}
    try:
        raw = str(state.ui.voice_confirm_payload_json or "").strip()
        if raw:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                payload_args = dict(parsed)
    except Exception:
        payload_args = {}
    before_snapshot = state.ui.voice_confirm_before_snapshot if isinstance(state.ui.voice_confirm_before_snapshot, dict) else {}
    if tool == "shopping_clear_all":
        removed = _clear_shopping_items(state)
        _clear_pending_voice_confirmation(state)
        if removed <= 0:
            return VoiceApplyResult(changed=False, status="done", message="Shopping list already empty")
        msg = f"Cleared shopping list ({removed})"
        _push_undo_history_from_confirm(
            state,
            action=VoiceAction(tool="shopping_clear_all", args=payload_args),
            before_snapshot=before_snapshot,
            message=msg,
        )
        return VoiceApplyResult(changed=True, status="done", message=msg)
    if tool == "inventory_clear_all":
        removed = _clear_inventory_items(state)
        _clear_pending_voice_confirmation(state)
        if removed <= 0:
            return VoiceApplyResult(changed=False, status="done", message="Inventory already empty")
        msg = f"Cleared inventory ({removed})"
        _push_undo_history_from_confirm(
            state,
            action=VoiceAction(tool="inventory_clear_all", args=payload_args),
            before_snapshot=before_snapshot,
            message=msg,
        )
        return VoiceApplyResult(changed=True, status="done", message=msg)
    if tool == "memo_clear_all":
        removed = _clear_memo_items(state)
        _clear_pending_voice_confirmation(state)
        if removed <= 0:
            return VoiceApplyResult(changed=False, status="done", message="Family board already empty")
        msg = f"Cleared family board ({removed})"
        _push_undo_history_from_confirm(
            state,
            action=VoiceAction(tool="memo_clear_all", args=payload_args),
            before_snapshot=before_snapshot,
            message=msg,
        )
        return VoiceApplyResult(changed=True, status="done", message=msg)
    _clear_pending_voice_confirmation(state)
    return VoiceApplyResult(changed=False, status="error", message="Unsupported pending confirmation")


def _canonical_open_app_name(raw: str) -> str:
    txt = " ".join(str(raw or "").strip().lower().split())
    if txt in _OPEN_APP_NAMES:
        return txt
    return ""


def _coerce_positive_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)):
        try:
            return int(value)
        except Exception:
            return 0
    txt = str(value or "").strip()
    if not txt or not txt.isdigit():
        return 0
    try:
        return int(txt)
    except Exception:
        return 0


def _parse_positional_remove_args(args: dict[str, Any]) -> dict[str, Any] | None:
    source = _parse_remove_source(args)
    if source is None:
        return None

    position_mode = str(args.get("position_mode") or "").strip().lower()
    index = _coerce_positive_int(args.get("index"))
    if not position_mode:
        if index > 0:
            position_mode = "index"
        else:
            return None
    if position_mode not in {"first", "last", "index"}:
        return None
    if position_mode == "index" and index <= 0:
        return None

    count = _coerce_positive_int(args.get("count") or 1)
    if count <= 0:
        count = 1

    out = {"source": source, "position_mode": position_mode, "count": count}
    if position_mode == "index":
        out["index"] = index
    return out


def _parse_remove_source(args: dict[str, Any], *, default: str = "reminders") -> str | None:
    raw = str(args.get("source") or "").strip().lower()
    if not raw:
        return default
    if raw in {"reminders", "inventory"}:
        return raw
    return None


def _parse_memo_target(args: dict[str, Any]) -> dict[str, Any] | None:
    target = str(args.get("target") or "").strip().lower()
    index = _coerce_positive_int(args.get("index"))
    author = str(args.get("author") or args.get("memo_author") or args.get("from_author") or "").strip()
    if not target:
        if index > 0:
            return {"target": "index", "index": index}
        if author:
            return {"target": "author", "author": author[:24]}
        return {"target": "latest"}
    if target == "latest":
        return {"target": "latest"}
    if target == "index" and index > 0:
        return {"target": "index", "index": index}
    if target == "author" and author:
        return {"target": "author", "author": author[:24]}
    return None


def _normalize_author_key(value: str) -> str:
    txt = str(value or "").strip().lower()
    if not txt:
        return ""
    txt = unicodedata.normalize("NFKC", txt)
    txt = re.sub(r"[\W_]+", "", txt, flags=re.UNICODE)
    return txt


def _resolve_memo_index(*, memos: list[MemoItem], target: str, index: int, author: str) -> int:
    mode = str(target or "latest").strip().lower() or "latest"
    if mode == "latest":
        return 0
    if mode == "index":
        return max(1, int(index or 0)) - 1
    if mode == "author":
        needle = _normalize_author_key(author)
        if not needle:
            return -1
        for i, memo in enumerate(memos):
            memo_author = _normalize_author_key(str(getattr(memo, "author", "") or ""))
            if memo_author == needle:
                return i
        return -1
    return -1


def _reminder_indices_for_source(state: AppState, source: str) -> list[int]:
    src = str(source or "").strip().lower()
    out: list[int] = []
    for i, r in enumerate(state.model.reminders):
        is_inventory = str(r.category or "") == "fridge"
        if src == "inventory" and is_inventory:
            out.append(i)
        if src == "reminders" and not is_inventory:
            out.append(i)
    return out


def _select_indices_by_position(
    indices: list[int],
    *,
    position_mode: str,
    count: int,
    index: int = 0,
) -> list[int]:
    if not indices:
        return []
    c = max(1, int(count or 1))
    mode = str(position_mode or "").strip().lower()
    if mode == "first":
        return list(indices[:c])
    if mode == "last":
        selected = list(indices[-c:])
        return selected
    if mode == "index":
        start = max(0, int(index or 1) - 1)
        if start >= len(indices):
            return []
        return list(indices[start : start + c])
    return []


def _mark_voice_completed(state: AppState, model_idx: int, *, now_ts: float | None = None) -> bool:
    if model_idx < 0 or model_idx >= len(state.model.reminders):
        return False
    row = state.model.reminders[model_idx]
    if bool(row.completed):
        return False

    now_v = float(now_ts if now_ts is not None else time.time())
    if _use_home_kitchen_completion_semantics(state):
        _toggle_home_kitchen_task_by_index(state, model_idx, now_v, theme={})
        return True

    _toggle_task_completed_by_index(state, model_idx)
    return True


def _use_home_kitchen_completion_semantics(state: AppState) -> bool:
    if state.ui.screen != Screen.HOME:
        return False
    return bool(str(state.ui.kitchen_visible_layout or "").strip())


def _norm_item_name(value: str) -> str:
    txt = (value or "").strip()
    if not txt:
        return ""
    return " ".join([part for part in txt.split() if part])


def _canonical_item_key(value: str) -> str:
    txt = str(value or "").strip().lower()
    if not txt:
        return ""
    txt = unicodedata.normalize("NFKC", txt)
    txt = re.sub(r"[^\w\s]+", " ", txt, flags=re.UNICODE)
    txt = " ".join(txt.split())
    return txt


def _item_tokens(value: str) -> list[str]:
    key = _canonical_item_key(value)
    if not key:
        return []
    return [p for p in key.split(" ") if p]


def _is_item_key_match(*, candidate_key: str, needle_key: str) -> bool:
    cand = _canonical_item_key(candidate_key)
    needle = _canonical_item_key(needle_key)
    if not cand or not needle:
        return False
    if cand == needle:
        return True
    cand_tokens = [p for p in cand.split(" ") if p]
    needle_tokens = [p for p in needle.split(" ") if p]
    if cand_tokens and needle_tokens and len(needle_tokens) <= len(cand_tokens):
        span = len(needle_tokens)
        for i in range(0, len(cand_tokens) - span + 1):
            if cand_tokens[i : i + span] == needle_tokens:
                return True
    return False


def _find_reminder_index(state: AppState, *, category: str, item_key: str) -> int:
    needle = _canonical_item_key(item_key)
    if not needle:
        return -1
    for i, r in enumerate(state.model.reminders):
        if str(r.category or "") != category:
            continue
        if _is_item_key_match(candidate_key=r.title, needle_key=needle):
            return i
    return -1


def _find_shopping_item_index(state: AppState, *, item_key: str) -> int:
    needle = _canonical_item_key(item_key)
    if not needle:
        return -1
    for i, r in enumerate(state.model.reminders):
        if not _is_shopping_list_item(r):
            continue
        if _is_item_key_match(candidate_key=r.title, needle_key=needle):
            return i
    return -1


def _set_pending_voice_confirmation(state: AppState, action: VoiceAction) -> None:
    state.ui.voice_confirm_tool = str(action.tool or "")
    state.ui.voice_confirm_payload_json = json.dumps(dict(action.args or {}), ensure_ascii=False)
    state.ui.voice_confirm_due_at = time.time() + CONFIRM_WINDOW_S
    state.ui.voice_confirm_before_snapshot = _capture_undo_snapshot(state)


def _clear_pending_voice_confirmation(state: AppState) -> None:
    state.ui.voice_confirm_tool = ""
    state.ui.voice_confirm_payload_json = ""
    state.ui.voice_confirm_due_at = 0.0
    state.ui.voice_confirm_before_snapshot = {}


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


def _clear_memo_items(state: AppState) -> int:
    removed = len(list(state.model.memos or []))
    if removed <= 0:
        return 0
    state.model.memos = []
    state.ui.memo_index = 0
    state.ui.memo_last_rotated_at = time.time()
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
        if _is_item_key_match(candidate_key=r.title, needle_key=needle):
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
        if not _is_item_key_match(candidate_key=r.title, needle_key=needle):
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
        if not _is_item_key_match(candidate_key=row.title, needle_key=needle):
            continue
        if not _is_generic_inventory_row_for_key(row.title, needle):
            continue
        return state.model.reminders.pop(idx)
    return None


def _is_generic_inventory_row_for_key(title: str, item_key: str) -> bool:
    raw_title = _canonical_item_key(title)
    base = _canonical_item_key(item_key)
    if not raw_title or not base:
        return False
    # AI should resolve semantic aliases in planning. Executor only applies exact-row removal.
    return raw_title == base


def _tokenize_inventory_title(value: str) -> list[str]:
    return _item_tokens(value)


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
