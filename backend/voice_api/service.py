from __future__ import annotations

import base64
import json
import os
import re
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.voice_api.correction_kb import get_correction_kb

_ALLOWED_TOOLS = {
    "inventory_log_event",
    "inventory_set_expiry",
    "inventory_clear_all",
    "shopping_add_item",
    "shopping_remove_item",
    "shopping_clear_all",
    "timer_set",
    "memo_add",
    "undo_last_action_group",
    "redo_last_action_group",
    "no_action",
}
_ALLOWED_EVENT_TYPES = {"consumed", "used", "added", "restocked", "finished"}
_MAX_PLAN_ACTIONS = 4

_ITEM_CANONICAL = {
    "milk": "milk",
    "牛奶": "milk",
    "pizza": "pizza",
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
    "egg": "eggs",
    "eggs": "eggs",
    "鸡蛋": "eggs",
    "bread": "bread",
    "面包": "bread",
    "yoghurt": "yoghurt",
    "yogurt": "yoghurt",
    "酸奶": "yoghurt",
}

_SHOPPING_NEED_PHRASES = (
    "没了",
    "没有了",
    "没有",
    "快没了",
    "不够了",
    "缺",
    "需要",
    "要买",
    "买点",
    "补点",
    "补上",
    "补货",
    "need ",
    "we need",
    "need more",
    "buy ",
    "buy some",
    "pick up",
    "get some",
    "restock ",
    "out of",
    "running low",
    "ran out",
    "run out",
    "low on",
)
_SHOPPING_DONE_PHRASES = (
    "买了",
    "已经买了",
    "刚买了",
    "i bought",
    "bought ",
    "already bought",
    "just bought",
    "picked up",
    "got ",
)
_STRONG_SHORTAGE_PHRASES = (
    "没了",
    "没有了",
    "没有",
    "out of",
    "no milk left",
    "no left",
    "ran out",
    "run out",
    "is gone",
)
_WEAK_SHORTAGE_PHRASES = (
    "快没了",
    "快没有了",
    "不够了",
    "running low",
    "low on",
    "almost out",
)
_INVENTORY_PRESENCE_PHRASES = (
    "冰箱里有",
    "in the fridge",
    "leftover",
    "过期",
    "expires",
    "expiring",
)

_SYSTEM_PROMPT_FALLBACK = (
    "You are a voice-command interpreter for a smart fridge magnet. "
    "Return one function call only. Prefer plan_actions with actions[1..4] for multi-intent commands. "
    "Available action tools: inventory_log_event, inventory_set_expiry, inventory_clear_all, "
    "shopping_add_item, shopping_remove_item, shopping_clear_all, timer_set, memo_add, "
    "undo_last_action_group, redo_last_action_group, no_action."
)
_CORRECTION_SCOPE_DEFAULT = "default"


def interpret_request(payload: dict[str, Any]) -> dict[str, Any]:
    result = interpret_request_with_debug(payload)
    action = result.get("action")
    if isinstance(action, dict):
        return action
    return _no_action("invalid_response_shape")


def interpret_request_with_debug(payload: dict[str, Any]) -> dict[str, Any]:
    req = dict(payload or {})
    request_time = str(req.get("request_time") or "").strip()
    timezone_name = str(req.get("timezone") or "UTC").strip() or "UTC"
    locale = str(req.get("locale") or "zh-CN").strip() or "zh-CN"
    transcript = str(req.get("transcript") or "").strip()
    audio_base64 = str(req.get("audio_base64") or "").strip()
    board_context = req.get("board_context") if isinstance(req.get("board_context"), dict) else None
    correction_scope_id = _correction_scope_from_request(req=req, board_context=board_context)
    transcript_raw = transcript

    if not transcript and not audio_base64:
        no_plan = _single_action_plan(_no_action("missing_audio_or_transcript"))
        return {"plan": no_plan, "action": _first_action_from_plan(no_plan), "transcript": ""}

    api_key = str(os.environ.get("GOOGLE_API_KEY") or "").strip()
    if not api_key:
        no_plan = _single_action_plan(_no_action("missing_google_api_key"))
        return {"plan": no_plan, "action": _first_action_from_plan(no_plan), "transcript": transcript}

    model = str(os.environ.get("GEMINI_MODEL") or "gemini-2.5-flash").strip()

    temp_audio_path = ""
    try:
        if audio_base64:
            temp_audio_path = _decode_audio_base64_to_temp(audio_base64)
        if not transcript and temp_audio_path:
            transcript = _transcribe_audio_via_gemini(
                api_key=api_key,
                model=model,
                audio_path=temp_audio_path,
                locale=locale,
            )
        transcript_raw = transcript
        correction_plan = _maybe_build_explicit_correction_plan(
            transcript=transcript,
            board_context=board_context,
            request_time=request_time,
            scope_id=correction_scope_id,
        )
        if correction_plan is not None:
            plan = normalize_plan(correction_plan, request_time=request_time)
            plan = _align_plan_with_transcript(plan, transcript=transcript)
            if not _validate_plan_against_schema(plan):
                no_plan = _single_action_plan(_no_action("schema_validation_failed"))
                return {"plan": no_plan, "action": _first_action_from_plan(no_plan), "transcript": transcript_raw}
            return {"plan": plan, "action": _first_action_from_plan(plan), "transcript": transcript_raw}
        transcript = _apply_scope_corrections(transcript=transcript, scope_id=correction_scope_id)
        if not transcript:
            # Fallback: let Gemini infer directly from audio when text transcription is empty.
            raw_plan = _call_gemini_for_action_from_audio(
                api_key=api_key,
                model=model,
                request_time=request_time,
                timezone_name=timezone_name,
                locale=locale,
                audio_path=temp_audio_path,
                board_context=board_context,
            )
            plan = normalize_plan(raw_plan, request_time=request_time)
            plan = _align_plan_with_transcript(plan, transcript=transcript)
            plan = _repair_context_reference_no_action(
                plan,
                transcript=transcript,
                board_context=board_context,
                request_time=request_time,
            )
            plan = _repair_missing_item_name_no_action(
                plan,
                transcript=transcript,
                board_context=board_context,
                request_time=request_time,
            )
            if not _validate_plan_against_schema(plan):
                no_plan = _single_action_plan(_no_action("schema_validation_failed"))
                return {"plan": no_plan, "action": _first_action_from_plan(no_plan), "transcript": ""}
            return {"plan": plan, "action": _first_action_from_plan(plan), "transcript": ""}

        raw_plan = _call_gemini_for_action(
            api_key=api_key,
            model=model,
            transcript=transcript,
            request_time=request_time,
            timezone_name=timezone_name,
            locale=locale,
            board_context=board_context,
        )

        plan = normalize_plan(raw_plan, request_time=request_time)
        plan = _align_plan_with_transcript(plan, transcript=transcript)
        plan = _repair_context_reference_no_action(
            plan,
            transcript=transcript,
            board_context=board_context,
            request_time=request_time,
        )
        plan = _repair_missing_item_name_no_action(
            plan,
            transcript=transcript,
            board_context=board_context,
            request_time=request_time,
        )
        if not _validate_plan_against_schema(plan):
            no_plan = _single_action_plan(_no_action("schema_validation_failed"))
            return {"plan": no_plan, "action": _first_action_from_plan(no_plan), "transcript": transcript_raw}
        return {"plan": plan, "action": _first_action_from_plan(plan), "transcript": transcript_raw}
    except Exception as e:
        no_plan = _single_action_plan(_no_action(f"gemini_error:{str(e)[:80]}"))
        return {"plan": no_plan, "action": _first_action_from_plan(no_plan), "transcript": transcript_raw}
    finally:
        if temp_audio_path:
            try:
                os.remove(temp_audio_path)
            except Exception:
                pass


def normalize_action(raw_action: dict[str, Any] | None, *, request_time: str) -> dict[str, Any]:
    if not isinstance(raw_action, dict):
        return _no_action("invalid_action_object")

    tool = str(raw_action.get("tool") or raw_action.get("name") or "").strip()
    args = raw_action.get("args")
    if not isinstance(args, dict):
        args = raw_action.get("arguments") if isinstance(raw_action.get("arguments"), dict) else {}

    if tool not in _ALLOWED_TOOLS:
        return _no_action("unsupported_tool")

    if tool == "shopping_add_item":
        item_raw = str(args.get("item_name") or args.get("item") or "").strip()
        item_name = _canonical_item_name(item_raw)
        if not item_name:
            return _no_action("missing_item_name")
        return {"tool": "shopping_add_item", "args": {"item_name": item_name}}

    if tool == "shopping_remove_item":
        item_raw = str(args.get("item_name") or args.get("item") or "").strip()
        item_name = _canonical_item_name(item_raw)
        if not item_name:
            return _no_action("missing_item_name")
        return {"tool": "shopping_remove_item", "args": {"item_name": item_name}}

    if tool == "shopping_clear_all":
        confirm_token = str(args.get("confirm_token") or args.get("confirm") or "").strip().lower()
        out_args: dict[str, Any] = {}
        if confirm_token:
            out_args["confirm_token"] = confirm_token
        return {"tool": "shopping_clear_all", "args": out_args}

    if tool == "inventory_clear_all":
        confirm_token = str(args.get("confirm_token") or args.get("confirm") or "").strip().lower()
        out_args: dict[str, Any] = {}
        if confirm_token:
            out_args["confirm_token"] = confirm_token
        return {"tool": "inventory_clear_all", "args": out_args}

    if tool == "inventory_set_expiry":
        item_raw = str(args.get("item_name") or args.get("item") or "").strip()
        item_name = _canonical_item_name(item_raw)
        if not item_name:
            return _no_action("missing_item_name")
        expiry_date = str(args.get("expiry_date") or args.get("date") or args.get("expires_on") or "").strip()
        if not expiry_date:
            return _no_action("missing_expiry_date")
        return {"tool": "inventory_set_expiry", "args": {"item_name": item_name, "expiry_date": expiry_date}}

    if tool == "timer_set":
        secs = _coerce_duration_seconds(args)
        if secs <= 0:
            return _no_action("invalid_duration_seconds")
        return {"tool": "timer_set", "args": {"duration_seconds": secs}}

    if tool == "memo_add":
        text = str(args.get("text") or args.get("memo_text") or args.get("content") or "").strip()
        if not text:
            return _no_action("missing_memo_text")
        author = str(args.get("author") or "Voice").strip() or "Voice"
        return {"tool": "memo_add", "args": {"text": text[:240], "author": author[:24]}}

    if tool in {"undo_last_action_group", "redo_last_action_group"}:
        return {"tool": tool, "args": {}}

    if tool == "inventory_log_event":
        item_raw = str(args.get("item_name") or args.get("item") or "").strip()
        item_name = _canonical_item_name(item_raw)
        if not item_name:
            return _no_action("missing_item_name")

        event_type = str(args.get("event_type") or args.get("event") or "").strip().lower()
        if event_type in ("consume", "drank", "ate"):
            event_type = "consumed"
        elif event_type in ("finish", "finished_up", "used_up", "done"):
            event_type = "finished"
        elif event_type in ("refill", "restock"):
            event_type = "restocked"
        if event_type not in _ALLOWED_EVENT_TYPES:
            return _no_action("invalid_event_type")

        effective_date = str(args.get("effective_date") or args.get("date") or "").strip()
        if not effective_date:
            effective_date = _default_effective_date(request_time)

        return {
            "tool": "inventory_log_event",
            "args": {
                "item_name": item_name,
                "event_type": event_type,
                "effective_date": effective_date,
            },
        }

    reason = str(args.get("reason") or "no_action").strip() or "no_action"
    return _no_action(reason)


def normalize_plan(raw_plan: dict[str, Any] | None, *, request_time: str) -> dict[str, Any]:
    if not isinstance(raw_plan, dict):
        return _single_action_plan(_no_action("invalid_plan_object"))

    source = dict(raw_plan)
    if str(source.get("tool") or "").strip() == "plan_actions":
        plan_args = source.get("args") if isinstance(source.get("args"), dict) else {}
        source = dict(plan_args)

    if isinstance(source.get("plan"), dict):
        source = dict(source.get("plan") or {})

    needs_clarification = bool(source.get("needs_clarification"))
    clarification = str(source.get("clarification") or "").strip()
    response_copy = str(source.get("response_copy") or "").strip()

    raw_actions: list[dict[str, Any]] = []
    if isinstance(source.get("actions"), list):
        for row in source.get("actions") or []:
            if isinstance(row, dict):
                raw_actions.append(dict(row))
    elif isinstance(raw_plan.get("actions"), list):
        for row in raw_plan.get("actions") or []:
            if isinstance(row, dict):
                raw_actions.append(dict(row))
    elif isinstance(raw_plan.get("action"), dict):
        raw_actions.append(dict(raw_plan.get("action") or {}))
    elif str(raw_plan.get("tool") or "").strip():
        raw_actions.append(dict(raw_plan))
    else:
        raw_actions.append(dict(source))

    actions: list[dict[str, Any]] = []
    for raw in raw_actions[: _MAX_PLAN_ACTIONS]:
        normalized = normalize_action(raw, request_time=request_time)
        if not isinstance(normalized, dict):
            continue
        actions.append(normalized)

    if len(actions) > 1:
        # Keep no_action only when it is the only fallback action.
        actions = [a for a in actions if str(a.get("tool") or "").strip() != "no_action"] or actions

    if not actions:
        reason = "needs_clarification" if needs_clarification else "missing_action"
        actions = [_no_action(reason)]

    return {
        "actions": actions[: _MAX_PLAN_ACTIONS],
        "needs_clarification": needs_clarification,
        "clarification": clarification,
        "response_copy": response_copy,
    }


def _single_action_plan(action: dict[str, Any]) -> dict[str, Any]:
    return {
        "actions": [dict(action or _no_action("no_action"))],
        "needs_clarification": False,
        "clarification": "",
        "response_copy": "",
    }


def _first_action_from_plan(plan: dict[str, Any]) -> dict[str, Any]:
    actions = plan.get("actions") if isinstance(plan, dict) else None
    if isinstance(actions, list):
        for row in actions:
            if isinstance(row, dict):
                return row
    return _no_action("missing_action")


def _align_plan_with_transcript(plan: dict[str, Any], *, transcript: str) -> dict[str, Any]:
    if not isinstance(plan, dict):
        return _single_action_plan(_no_action("invalid_plan_object"))
    actions = plan.get("actions")
    if not isinstance(actions, list):
        actions = []

    out_actions: list[dict[str, Any]] = []
    for row in actions[: _MAX_PLAN_ACTIONS]:
        if not isinstance(row, dict):
            continue
        out_actions.append(_align_action_with_transcript(dict(row), transcript=transcript))

    if not out_actions:
        out_actions = [_no_action("missing_action")]

    out = dict(plan)
    out["actions"] = out_actions[: _MAX_PLAN_ACTIONS]
    return out


def _align_action_with_transcript(action: dict[str, Any], *, transcript: str) -> dict[str, Any]:
    if not isinstance(action, dict):
        return action
    txt = str(transcript or "").strip().lower()
    if not txt:
        return action
    tool = str(action.get("tool") or "").strip()
    if tool not in {"inventory_log_event", "shopping_add_item"}:
        return action
    args = action.get("args") if isinstance(action.get("args"), dict) else {}
    item_name = _canonical_item_name(str(args.get("item_name") or "").strip())
    if not item_name:
        return action

    # If Gemini already picked shopping_add_item, still apply shortage hints so final behavior
    # does not depend on whether the model first chose shopping_add_item vs inventory_log_event.
    if tool == "shopping_add_item":
        out_args = {"item_name": item_name}
        if _looks_like_strong_shortage_phrase(txt) and not _looks_like_inventory_presence_phrase(txt):
            out_args["inventory_remove_if_generic_match"] = True
        return {"tool": "shopping_add_item", "args": out_args}

    # Shortage / procurement phrasing should prefer shopping list intent.
    if _looks_like_shopping_need_phrase(txt) and not _looks_like_inventory_presence_phrase(txt):
        out_args: dict[str, Any] = {"item_name": item_name}
        if _looks_like_strong_shortage_phrase(txt):
            # Let local policy/handler decide whether inventory can be safely removed
            # (e.g. remove generic Fresh Milk, but keep specific Marinated Chicken).
            out_args["inventory_remove_if_generic_match"] = True
        return {"tool": "shopping_add_item", "args": out_args}
    return action


def _correction_scope_from_request(*, req: dict[str, Any], board_context: dict[str, Any] | None) -> str:
    raw = str(req.get("household_id") or "").strip()
    if raw:
        return raw[:64]
    if isinstance(board_context, dict):
        for key in ("household_id", "home_id", "board_id"):
            v = str(board_context.get(key) or "").strip()
            if v:
                return v[:64]
    return _CORRECTION_SCOPE_DEFAULT


def _apply_scope_corrections(*, transcript: str, scope_id: str) -> str:
    txt = str(transcript or "").strip()
    if not txt:
        return txt
    try:
        kb = get_correction_kb()
        normalized, _hits = kb.apply(txt, scope_id=scope_id)
        return str(normalized or txt)
    except Exception:
        return txt


def _maybe_build_explicit_correction_plan(
    *,
    transcript: str,
    board_context: dict[str, Any] | None,
    request_time: str,
    scope_id: str,
) -> dict[str, Any] | None:
    correction = _extract_explicit_correction(transcript)
    if correction is None:
        return None

    wrong, correct = correction
    plan = _build_context_rename_plan(
        board_context=board_context,
        wrong=wrong,
        correct=correct,
        request_time=request_time,
    )
    if plan is None:
        return None

    if str(scope_id or "").strip() and str(scope_id or "").strip() != _CORRECTION_SCOPE_DEFAULT:
        try:
            get_correction_kb().upsert(scope_id=scope_id, wrong=wrong, correct=correct)
        except Exception:
            pass
    return plan


def _extract_explicit_correction(transcript: str) -> tuple[str, str] | None:
    txt = str(transcript or "").strip()
    if not txt:
        return None
    patterns = [
        r"不是(?P<wrong>.+?)[，,。.;；!?？ ]*(?:是|应该是)(?P<correct>.+)$",
        r"(?P<wrong>.+?)不对[，,。.;；!?？ ]*(?:是|应该是)(?P<correct>.+)$",
        r"not\s+(?P<wrong>.+?)[,; ]+(?:it(?:'s| is)|is)\s+(?P<correct>.+)$",
    ]
    for p in patterns:
        m = re.search(p, txt, flags=re.IGNORECASE)
        if not m:
            continue
        wrong = _clean_correction_term(m.group("wrong"), pick="first")
        correct = _clean_correction_term(m.group("correct"), pick="last")
        if not wrong or not correct:
            continue
        if wrong.lower() == correct.lower():
            continue
        return wrong, correct
    return None


def _clean_correction_term(value: str, *, pick: str) -> str:
    txt = str(value or "").strip()
    if not txt:
        return ""
    txt = txt.strip(" \"'“”‘’")
    parts = [p.strip() for p in re.split(r"[，,。.;；!?？]", txt) if str(p or "").strip()]
    if not parts:
        return ""
    chosen = parts[-1] if pick == "last" else parts[0]
    chosen = re.sub(r"^(这个|那个|this|that)\s*", "", chosen, flags=re.IGNORECASE).strip()
    chosen = chosen.strip(" \"'“”‘’")
    if not chosen:
        return ""
    if len(chosen) > 32:
        chosen = chosen[:32].strip()
    return chosen


def _build_context_rename_plan(
    *,
    board_context: dict[str, Any] | None,
    wrong: str,
    correct: str,
    request_time: str,
) -> dict[str, Any] | None:
    if not isinstance(board_context, dict):
        return None
    day = _default_effective_date(request_time)

    inventory_items = board_context.get("inventory")
    inventory_rows = inventory_items.get("items") if isinstance(inventory_items, dict) else []
    if isinstance(inventory_rows, list):
        for row in inventory_rows:
            if not isinstance(row, dict):
                continue
            title = str(row.get("title") or "").strip()
            if not title:
                continue
            renamed = _replace_case_insensitive_once(title, wrong, correct)
            if not renamed or renamed == title:
                continue
            return {
                "actions": [
                    {
                        "tool": "inventory_log_event",
                        "args": {
                            "item_name": title,
                            "event_type": "finished",
                            "effective_date": day,
                        },
                    },
                    {
                        "tool": "inventory_log_event",
                        "args": {
                            "item_name": renamed,
                            "event_type": "added",
                            "effective_date": day,
                        },
                    },
                ],
                "response_copy": f"Corrected item name: {title} -> {renamed}",
            }

    shopping_items = board_context.get("shopping")
    shopping_rows = shopping_items.get("items") if isinstance(shopping_items, dict) else []
    if isinstance(shopping_rows, list):
        for row in shopping_rows:
            if isinstance(row, dict):
                title = str(row.get("title") or "").strip()
            else:
                title = str(row or "").strip()
            if not title:
                continue
            renamed = _replace_case_insensitive_once(title, wrong, correct)
            if not renamed or renamed == title:
                continue
            return {
                "actions": [
                    {"tool": "shopping_remove_item", "args": {"item_name": title}},
                    {"tool": "shopping_add_item", "args": {"item_name": renamed}},
                ],
                "response_copy": f"Corrected shopping item: {title} -> {renamed}",
            }
    return None


def _replace_case_insensitive_once(text: str, old: str, new: str) -> str:
    src = str(text or "")
    needle = str(old or "").strip()
    target = str(new or "").strip()
    if not src or not needle or not target:
        return src
    idx = src.find(needle)
    if idx >= 0:
        return src[:idx] + target + src[idx + len(needle) :]
    src_low = src.lower()
    needle_low = needle.lower()
    idx = src_low.find(needle_low)
    if idx < 0:
        return src
    return src[:idx] + target + src[idx + len(needle) :]


def _repair_context_reference_no_action(
    plan: dict[str, Any],
    *,
    transcript: str,
    board_context: dict[str, Any] | None,
    request_time: str,
) -> dict[str, Any]:
    if not isinstance(plan, dict):
        return plan
    actions = plan.get("actions")
    if not isinstance(actions, list) or not actions:
        return plan
    first = actions[0]
    if not isinstance(first, dict):
        return plan
    if str(first.get("tool") or "").strip() != "no_action":
        return plan

    txt = str(transcript or "").strip()
    if not txt:
        return plan

    recent = _recent_action_group_actions(board_context)
    if not recent:
        return plan

    txt_low = txt.lower()

    if _looks_like_remove_last_phrase(txt_low):
        removal_actions = _build_remove_last_actions_from_recent(recent=recent, request_time=request_time)
        if removal_actions:
            out = dict(plan)
            out["actions"] = removal_actions[:_MAX_PLAN_ACTIONS]
            if not str(out.get("response_copy") or "").strip():
                out["response_copy"] = "Done. Removed the last one."
            out["needs_clarification"] = False
            out["clarification"] = ""
            return out

    same_for_item = _extract_same_for_item_name(txt)
    if same_for_item:
        same_actions = _build_same_for_actions_from_recent(
            recent=recent,
            item_name=same_for_item,
            request_time=request_time,
        )
        if same_actions:
            out = dict(plan)
            out["actions"] = same_actions[:_MAX_PLAN_ACTIONS]
            if not str(out.get("response_copy") or "").strip():
                out["response_copy"] = f"Done. Applied the same action for {same_for_item}."
            out["needs_clarification"] = False
            out["clarification"] = ""
            return out

    if _looks_like_repeat_last_phrase(txt_low):
        drop_timer = _looks_like_repeat_without_timer(txt_low)
        replay_actions = _build_repeat_actions_from_recent(
            recent=recent,
            drop_timer=drop_timer,
            request_time=request_time,
        )
        if replay_actions:
            out = dict(plan)
            out["actions"] = replay_actions[:_MAX_PLAN_ACTIONS]
            if not str(out.get("response_copy") or "").strip():
                out["response_copy"] = "Done. Repeated your last action."
            out["needs_clarification"] = False
            out["clarification"] = ""
            return out

    return plan


def _recent_action_group_actions(board_context: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(board_context, dict):
        return []
    groups = board_context.get("recent_action_groups")
    if not isinstance(groups, list):
        return []
    for g in groups:
        if not isinstance(g, dict):
            continue
        actions = g.get("actions")
        if not isinstance(actions, list):
            continue
        out: list[dict[str, Any]] = []
        for row in actions:
            if not isinstance(row, dict):
                continue
            tool = str(row.get("tool") or "").strip()
            args = row.get("args") if isinstance(row.get("args"), dict) else {}
            if not tool:
                continue
            out.append({"tool": tool, "args": dict(args)})
        if out:
            return out
    return []


def _looks_like_repeat_last_phrase(transcript_lower: str) -> bool:
    txt = str(transcript_lower or "").strip().lower()
    if not txt:
        return False
    patterns = (
        "do that again",
        "do it again",
        "do that one more time",
        "do that once more",
        "same again",
        "same as before",
        "do that one more",
        "再来一次",
        "再来一遍",
        "再来一回",
        "跟刚才一样",
        "照刚才",
    )
    return any(p in txt for p in patterns)


def _looks_like_repeat_without_timer(transcript_lower: str) -> bool:
    txt = str(transcript_lower or "").strip().lower()
    if not txt:
        return False
    no_timer_patterns = (
        "no timer",
        "without timer",
        "but no timer",
        "不要timer",
        "不要计时",
        "别设定时",
        "别设计时器",
    )
    return any(p in txt for p in no_timer_patterns)


def _looks_like_remove_last_phrase(transcript_lower: str) -> bool:
    txt = str(transcript_lower or "").strip().lower()
    if not txt:
        return False
    patterns = (
        "remove the last one",
        "remove that",
        "remove that one",
        "delete that",
        "delete the last one",
        "删掉刚才那个",
        "删掉那个",
        "把刚才那个删了",
    )
    return any(p in txt for p in patterns)


def _extract_same_for_item_name(transcript: str) -> str:
    txt = str(transcript or "").strip()
    if not txt:
        return ""
    patterns = [
        r"(?:and\s+)?(?:the\s+)?same(?:\s+thing)?\s+for\s+(?P<item>.+)$",
        r"same\s+for\s+(?P<item>.+)$",
    ]
    for p in patterns:
        m = re.search(p, txt, flags=re.IGNORECASE)
        if not m:
            continue
        candidate = _clean_item_candidate_for_context(m.group("item"))
        if candidate:
            return candidate
    return ""


def _clean_item_candidate_for_context(value: str) -> str:
    txt = str(value or "").strip()
    if not txt:
        return ""
    filler_tail = re.compile(
        r"(?:[\s,，;；:：-]*(?:\b(?:too|please|thanks|thank you|pls|thx)\b|吧|呀|啊|一下|谢谢|多谢))+$",
        flags=re.IGNORECASE,
    )
    while txt:
        before = txt
        txt = re.sub(r"[。．.!?？]+$", "", txt).strip()
        txt = filler_tail.sub("", txt).strip()
        txt = txt.strip(" \"'“”‘’")
        if txt == before:
            break
    if not txt:
        return ""
    return _canonical_item_name(txt)


def _build_repeat_actions_from_recent(
    *,
    recent: list[dict[str, Any]],
    drop_timer: bool,
    request_time: str,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in recent:
        tool = str(row.get("tool") or "").strip()
        args = row.get("args") if isinstance(row.get("args"), dict) else {}
        if not tool:
            continue
        if drop_timer and tool == "timer_set":
            continue
        rebuilt = _rebuild_context_action(tool=tool, args=args, request_time=request_time)
        if rebuilt:
            out.append(rebuilt)
    return out[:_MAX_PLAN_ACTIONS]


def _build_same_for_actions_from_recent(
    *,
    recent: list[dict[str, Any]],
    item_name: str,
    request_time: str,
) -> list[dict[str, Any]]:
    item = _canonical_item_name(item_name)
    if not item:
        return []
    for row in recent:
        tool = str(row.get("tool") or "").strip()
        args = row.get("args") if isinstance(row.get("args"), dict) else {}
        if tool == "shopping_add_item":
            return [{"tool": "shopping_add_item", "args": {"item_name": item}}]
        if tool == "shopping_remove_item":
            return [{"tool": "shopping_remove_item", "args": {"item_name": item}}]
        if tool == "inventory_set_expiry":
            expiry_date = str(args.get("expiry_date") or "").strip()
            if not expiry_date:
                continue
            return [{"tool": "inventory_set_expiry", "args": {"item_name": item, "expiry_date": expiry_date}}]
        if tool == "inventory_log_event":
            event_type = str(args.get("event_type") or "").strip().lower()
            if event_type not in _ALLOWED_EVENT_TYPES:
                event_type = "added"
            effective_date = str(args.get("effective_date") or "").strip() or _default_effective_date(request_time)
            return [
                {
                    "tool": "inventory_log_event",
                    "args": {
                        "item_name": item,
                        "event_type": event_type,
                        "effective_date": effective_date,
                    },
                }
            ]
    return []


def _build_remove_last_actions_from_recent(*, recent: list[dict[str, Any]], request_time: str) -> list[dict[str, Any]]:
    for row in reversed(recent):
        tool = str(row.get("tool") or "").strip()
        args = row.get("args") if isinstance(row.get("args"), dict) else {}
        item = _canonical_item_name(str(args.get("item_name") or "").strip())
        if tool == "shopping_add_item" and item:
            return [{"tool": "shopping_remove_item", "args": {"item_name": item}}]
        if tool == "shopping_remove_item" and item:
            return [{"tool": "shopping_add_item", "args": {"item_name": item}}]
        if tool == "inventory_log_event" and item:
            event_type = str(args.get("event_type") or "").strip().lower()
            if event_type in {"added", "restocked"}:
                return [
                    {
                        "tool": "inventory_log_event",
                        "args": {
                            "item_name": item,
                            "event_type": "finished",
                            "effective_date": _default_effective_date(request_time),
                        },
                    }
                ]
    return []


def _rebuild_context_action(*, tool: str, args: dict[str, Any], request_time: str) -> dict[str, Any] | None:
    t = str(tool or "").strip()
    a = dict(args or {})
    if t in {"shopping_add_item", "shopping_remove_item"}:
        item = _canonical_item_name(str(a.get("item_name") or "").strip())
        if not item:
            return None
        out_args: dict[str, Any] = {"item_name": item}
        if t == "shopping_add_item" and bool(a.get("inventory_remove_if_generic_match")):
            out_args["inventory_remove_if_generic_match"] = True
        return {"tool": t, "args": out_args}
    if t == "timer_set":
        secs = _coerce_duration_seconds(a)
        if secs <= 0:
            return None
        return {"tool": "timer_set", "args": {"duration_seconds": secs}}
    if t == "memo_add":
        text = str(a.get("text") or "").strip()
        if not text:
            return None
        out_args = {"text": text}
        author = str(a.get("author") or "").strip()
        if author:
            out_args["author"] = author
        return {"tool": "memo_add", "args": out_args}
    if t == "inventory_set_expiry":
        item = _canonical_item_name(str(a.get("item_name") or "").strip())
        expiry_date = str(a.get("expiry_date") or "").strip()
        if not item or not expiry_date:
            return None
        return {"tool": "inventory_set_expiry", "args": {"item_name": item, "expiry_date": expiry_date}}
    if t == "inventory_log_event":
        item = _canonical_item_name(str(a.get("item_name") or "").strip())
        event_type = str(a.get("event_type") or "").strip().lower()
        if not item:
            return None
        if event_type not in _ALLOWED_EVENT_TYPES:
            event_type = "added"
        effective_date = str(a.get("effective_date") or "").strip() or _default_effective_date(request_time)
        return {
            "tool": "inventory_log_event",
            "args": {
                "item_name": item,
                "event_type": event_type,
                "effective_date": effective_date,
            },
        }
    return None


def _repair_missing_item_name_no_action(
    plan: dict[str, Any],
    *,
    transcript: str,
    board_context: dict[str, Any] | None,
    request_time: str,
) -> dict[str, Any]:
    if not isinstance(plan, dict):
        return plan
    actions = plan.get("actions")
    if not isinstance(actions, list) or not actions:
        return plan
    first = actions[0]
    if not isinstance(first, dict):
        return plan
    if str(first.get("tool") or "").strip() != "no_action":
        return plan
    args = first.get("args") if isinstance(first.get("args"), dict) else {}
    if str(args.get("reason") or "").strip() != "missing_item_name":
        return plan

    txt = str(transcript or "").strip().lower()
    guessed_item = ""
    if _looks_like_shopping_done_phrase(txt):
        guessed_item = _guess_item_name_for_completed_purchase(transcript=txt, board_context=board_context)
    elif _looks_like_shopping_remove_phrase(txt):
        guessed_item = _guess_item_name_for_shopping_remove(transcript=txt, board_context=board_context)
    if not guessed_item:
        return plan

    out = dict(plan)
    out["actions"] = [{"tool": "shopping_remove_item", "args": {"item_name": guessed_item}}]
    if not str(out.get("response_copy") or "").strip():
        out["response_copy"] = f"Removed {guessed_item} from shopping list."
    return out


def _guess_item_name_for_completed_purchase(*, transcript: str, board_context: dict[str, Any] | None) -> str:
    txt = str(transcript or "").strip().lower()
    if not txt:
        return ""

    matched: list[str] = []
    seen: set[str] = set()
    for candidate in _shopping_item_candidates(board_context):
        canonical = _canonical_item_name(candidate)
        if not canonical or canonical in seen:
            continue
        if _contains_term(txt, canonical):
            matched.append(canonical)
            seen.add(canonical)

    for canonical in sorted(set(_ITEM_CANONICAL.values()), key=len, reverse=True):
        if not canonical or canonical in seen:
            continue
        if _contains_term(txt, canonical):
            matched.append(canonical)
            seen.add(canonical)

    if len(matched) == 1:
        return matched[0]
    return ""


def _looks_like_shopping_remove_phrase(transcript_lower: str) -> bool:
    txt = str(transcript_lower or "").strip().lower()
    if not txt:
        return False
    remove_markers = (
        "remove ",
        "delete ",
        "take ",
        "drop ",
        "cross off",
        "删",
        "删除",
        "去掉",
        "移除",
    )
    has_remove = any(p in txt for p in remove_markers)
    if not has_remove:
        return False
    has_list = ("shopping list" in txt) or ("shopping" in txt and "list" in txt) or ("购物清单" in txt)
    return has_list


def _guess_item_name_for_shopping_remove(*, transcript: str, board_context: dict[str, Any] | None) -> str:
    txt = str(transcript or "").strip().lower()
    if not txt:
        return ""

    extracted = _extract_shopping_remove_item_name(txt)
    if extracted:
        normalized = _canonical_item_name(extracted)
        if normalized:
            return normalized

    matched: list[str] = []
    seen: set[str] = set()
    for candidate in _shopping_item_candidates(board_context):
        canonical = _canonical_item_name(candidate)
        if not canonical or canonical in seen:
            continue
        if _contains_term(txt, canonical):
            matched.append(canonical)
            seen.add(canonical)

    if len(matched) == 1:
        return matched[0]
    return ""


def _extract_shopping_remove_item_name(transcript_lower: str) -> str:
    txt = str(transcript_lower or "").strip().lower()
    if not txt:
        return ""
    patterns = [
        r"(?:remove|delete|drop)\s+(?P<item>.+?)\s+from\s+(?:the\s+)?shopping list",
        r"(?:remove|delete|drop)\s+(?P<item>.+?)\s+off\s+(?:the\s+)?shopping list",
        r"take\s+(?P<item>.+?)\s+off\s+(?:the\s+)?shopping list",
        r"从购物清单(?:里)?(?:删掉|删除|去掉|移除)\s*(?P<item>.+)$",
        r"(?:删掉|删除|去掉|移除)\s*(?P<item>.+?)\s*(?:从)?购物清单(?:里)?",
    ]
    for p in patterns:
        m = re.search(p, txt, flags=re.IGNORECASE)
        if not m:
            continue
        candidate = _clean_item_candidate_for_context(m.group("item"))
        if not candidate:
            continue
        if candidate in {"it", "that", "this", "one", "last one", "那个", "这个"}:
            continue
        return candidate
    return ""


def _shopping_item_candidates(board_context: dict[str, Any] | None) -> list[str]:
    if not isinstance(board_context, dict):
        return []
    shopping = board_context.get("shopping")
    rows = shopping.get("items") if isinstance(shopping, dict) else []
    if not isinstance(rows, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for row in rows:
        if isinstance(row, dict):
            title = str(row.get("title") or "").strip()
        else:
            title = str(row or "").strip()
        if not title:
            continue
        variants = [title]
        title_low = title.lower()
        for prefix in ("buy ", "get ", "pick up ", "need ", "add "):
            if title_low.startswith(prefix):
                variants.append(title[len(prefix) :].strip())
        for suffix in (" expires",):
            if title_low.endswith(suffix):
                variants.append(title[: -len(suffix)].strip())
        for v in variants:
            vv = str(v or "").strip()
            if not vv:
                continue
            key = vv.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(vv)
    return out


def _contains_term(text: str, term: str) -> bool:
    hay = str(text or "").strip().lower()
    needle = str(term or "").strip().lower()
    if not hay or not needle:
        return False
    if re.fullmatch(r"[a-z0-9 ]+", needle):
        return bool(re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", hay))
    return needle in hay


def _call_gemini_for_action(
    *,
    api_key: str,
    model: str,
    transcript: str,
    request_time: str,
    timezone_name: str,
    locale: str,
    board_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)

    contents: list[Any] = []
    context_lines = [
        f"request_time: {request_time}",
        f"timezone: {timezone_name}",
        f"locale: {locale}",
        "Important: transcript below is already ASR output. Do NOT claim transcript is missing.",
        "Return one function call only.",
        "Prefer function `plan_actions` for multi-intent or context-reference utterances.",
    ]
    context_lines.append(f"transcript: {transcript}")
    if board_context:
        context_lines.append(_board_context_line(board_context))
    contents.append("\n".join(context_lines))

    response = client.models.generate_content(
        model=model,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=_load_system_prompt(),
            tools=_tool_declarations(),
            tool_config=types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(mode="ANY")
            ),
        ),
    )

    action = _extract_first_function_call(response)
    if action:
        return action

    # Fallback path: if model returned text JSON instead of a function call.
    text = str(getattr(response, "text", "") or "").strip()
    if text:
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass

    return _no_action("no_function_call")


def _call_gemini_for_action_from_audio(
    *,
    api_key: str,
    model: str,
    request_time: str,
    timezone_name: str,
    locale: str,
    audio_path: str,
    board_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    uploaded_file = client.files.upload(file=audio_path)
    uploaded_file = _wait_for_file_ready(client, uploaded_file)

    prompt = "\n".join(
        [
            f"request_time: {request_time}",
            f"timezone: {timezone_name}",
            f"locale: {locale}",
            _board_context_line(board_context),
            "Transcribe and interpret this audio.",
            "Return one function call only.",
            "Prefer function `plan_actions` for multi-intent or context-reference utterances.",
            "If not actionable, call no_action.",
        ]
    )

    response = client.models.generate_content(
        model=model,
        contents=[prompt, uploaded_file],
        config=types.GenerateContentConfig(
            system_instruction=_load_system_prompt(),
            tools=_tool_declarations(),
            tool_config=types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(mode="ANY")
            ),
        ),
    )
    action = _extract_first_function_call(response)
    if action:
        return action
    return _no_action("no_function_call")


def _transcribe_audio_via_gemini(*, api_key: str, model: str, audio_path: str, locale: str) -> str:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    uploaded_file = client.files.upload(file=audio_path)
    uploaded_file = _wait_for_file_ready(client, uploaded_file)
    prompt = (
        "Transcribe this audio into plain text. "
        f"Primary locale hint: {locale}. "
        "Output transcript only. If unclear, output the best-effort short transcript."
    )
    response = client.models.generate_content(
        model=model,
        contents=[prompt, uploaded_file],
        config=types.GenerateContentConfig(
            temperature=0.0,
        ),
    )
    txt = str(getattr(response, "text", "") or "").strip()
    return txt


def _wait_for_file_ready(client: Any, uploaded_file: Any, timeout_s: float = 8.0) -> Any:
    name = str(getattr(uploaded_file, "name", "") or "").strip()
    if not name:
        return uploaded_file

    started = time.time()
    last_file = uploaded_file
    while time.time() - started < timeout_s:
        try:
            got = client.files.get(name=name)
            last_file = got
            state_obj = getattr(got, "state", None)
            state_txt = str(getattr(state_obj, "name", state_obj) or "").upper()
            if not state_txt or "ACTIVE" in state_txt:
                return got
            if "FAILED" in state_txt:
                return got
        except Exception:
            return last_file
        time.sleep(0.25)
    return last_file


def _extract_first_function_call(response: Any) -> dict[str, Any] | None:
    cands = list(getattr(response, "candidates", None) or [])
    for cand in cands:
        content = getattr(cand, "content", None)
        parts = list(getattr(content, "parts", None) or [])
        for part in parts:
            fn = getattr(part, "function_call", None)
            if not fn:
                continue
            name = str(getattr(fn, "name", "") or "").strip()
            args_raw = getattr(fn, "args", None) or {}
            if hasattr(args_raw, "items"):
                args = dict(args_raw)
            else:
                args = {}
            if name:
                return {"tool": name, "args": args}
    return None


def _tool_declarations() -> list[dict[str, Any]]:
    return [
        {
            "functionDeclarations": [
                {
                    "name": "plan_actions",
                    "description": "Build an ordered execution plan with 1-4 actions. Use this for multi-intent and context-aware commands.",
                    "parameters": {
                        "type": "OBJECT",
                        "properties": {
                            "actions": {
                                "type": "ARRAY",
                                "minItems": 1,
                                "maxItems": _MAX_PLAN_ACTIONS,
                                "items": {
                                    "type": "OBJECT",
                                    "properties": {
                                        "tool": {
                                            "type": "STRING",
                                            "enum": [
                                                "inventory_log_event",
                                                "inventory_set_expiry",
                                                "inventory_clear_all",
                                                "shopping_add_item",
                                                "shopping_remove_item",
                                                "shopping_clear_all",
                                                "timer_set",
                                                "memo_add",
                                                "undo_last_action_group",
                                                "redo_last_action_group",
                                                "no_action",
                                            ],
                                        },
                                        "args": {"type": "OBJECT"},
                                    },
                                    "required": ["tool", "args"],
                                },
                            },
                            "needs_clarification": {"type": "BOOLEAN"},
                            "clarification": {"type": "STRING"},
                            "response_copy": {"type": "STRING"},
                        },
                        "required": ["actions"],
                    },
                },
                {
                    "name": "inventory_log_event",
                    "description": "Log an inventory event from voice",
                    "parameters": {
                        "type": "OBJECT",
                        "properties": {
                            "item_name": {"type": "STRING"},
                            "event_type": {"type": "STRING", "enum": ["consumed", "used", "added", "restocked", "finished"]},
                            "effective_date": {"type": "STRING"},
                        },
                        "required": ["item_name", "event_type"],
                    },
                },
                {
                    "name": "inventory_set_expiry",
                    "description": "Set or update expiry date for an existing inventory item",
                    "parameters": {
                        "type": "OBJECT",
                        "properties": {
                            "item_name": {"type": "STRING"},
                            "expiry_date": {"type": "STRING"},
                        },
                        "required": ["item_name", "expiry_date"],
                    },
                },
                {
                    "name": "inventory_clear_all",
                    "description": "Request clearing the whole inventory section (requires physical confirmation on device)",
                    "parameters": {
                        "type": "OBJECT",
                        "properties": {
                            "confirm_token": {"type": "STRING"},
                        },
                    },
                },
                {
                    "name": "shopping_add_item",
                    "description": "Add one shopping item from voice",
                    "parameters": {
                        "type": "OBJECT",
                        "properties": {
                            "item_name": {"type": "STRING"},
                        },
                        "required": ["item_name"],
                    },
                },
                {
                    "name": "shopping_remove_item",
                    "description": "Remove one item from shopping list",
                    "parameters": {
                        "type": "OBJECT",
                        "properties": {
                            "item_name": {"type": "STRING"},
                        },
                        "required": ["item_name"],
                    },
                },
                {
                    "name": "shopping_clear_all",
                    "description": "Request clearing the whole shopping list (requires physical confirmation on device)",
                    "parameters": {
                        "type": "OBJECT",
                        "properties": {
                            "confirm_token": {"type": "STRING"},
                        },
                    },
                },
                {
                    "name": "timer_set",
                    "description": "Set the kitchen timer using a duration in seconds",
                    "parameters": {
                        "type": "OBJECT",
                        "properties": {
                            "duration_seconds": {"type": "INTEGER"},
                        },
                        "required": ["duration_seconds"],
                    },
                },
                {
                    "name": "memo_add",
                    "description": "Add a message to the family board/memo panel",
                    "parameters": {
                        "type": "OBJECT",
                        "properties": {
                            "text": {"type": "STRING"},
                            "author": {"type": "STRING"},
                        },
                        "required": ["text"],
                    },
                },
                {
                    "name": "undo_last_action_group",
                    "description": "Undo the most recent committed voice action group",
                    "parameters": {
                        "type": "OBJECT",
                        "properties": {},
                    },
                },
                {
                    "name": "redo_last_action_group",
                    "description": "Redo the most recently undone voice action group",
                    "parameters": {
                        "type": "OBJECT",
                        "properties": {},
                    },
                },
                {
                    "name": "no_action",
                    "description": "No actionable intent in voice input",
                    "parameters": {
                        "type": "OBJECT",
                        "properties": {
                            "reason": {"type": "STRING"},
                        },
                        "required": ["reason"],
                    },
                },
            ]
        }
    ]


def _decode_audio_base64_to_temp(audio_base64: str) -> str:
    raw = base64.b64decode(audio_base64.encode("ascii"), validate=True)
    fd, path = tempfile.mkstemp(prefix="voice_api_", suffix=".wav", dir="/tmp")
    os.close(fd)
    with open(path, "wb") as f:
        f.write(raw)
    return path


def _board_context_line(board_context: dict[str, Any] | None) -> str:
    if not isinstance(board_context, dict) or not board_context:
        return "board_context: {}"
    try:
        txt = json.dumps(board_context, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        return "board_context: {}"
    if len(txt) > 1200:
        txt = txt[:1197] + "..."
    return f"board_context: {txt}"


def _coerce_duration_seconds(args: dict[str, Any]) -> int:
    raw = args.get("duration_seconds")
    if raw is None:
        raw = args.get("seconds")
    if raw is None:
        raw = args.get("duration_sec")
    if raw is None:
        raw = args.get("duration")
    if isinstance(raw, bool):
        return 0
    if isinstance(raw, (int, float)):
        try:
            v = int(raw)
            return max(0, min(v, 24 * 3600))
        except Exception:
            return 0
    txt = str(raw or "").strip().lower()
    if not txt:
        return 0
    if txt.isdigit():
        try:
            return max(0, min(int(txt), 24 * 3600))
        except Exception:
            return 0
    # Minimal fallback parser for cases where model returns text duration.
    m = re.fullmatch(r"(?:(\d+)\s*h(?:ours?)?\s*)?(?:(\d+)\s*m(?:in(?:utes?)?)?\s*)?(?:(\d+)\s*s(?:ec(?:onds?)?)?\s*)?", txt)
    if not m:
        return 0
    h = int(m.group(1) or 0)
    mins = int(m.group(2) or 0)
    secs = int(m.group(3) or 0)
    total = h * 3600 + mins * 60 + secs
    return max(0, min(total, 24 * 3600))


def _looks_like_shopping_need_phrase(transcript_lower: str) -> bool:
    txt = str(transcript_lower or "").strip().lower()
    if not txt:
        return False
    if any(p in txt for p in _SHOPPING_DONE_PHRASES):
        return False
    if ("shopping list" in txt or "购物清单" in txt) and (" add " in f" {txt} " or "加" in txt):
        return True
    return any(p in txt for p in _SHOPPING_NEED_PHRASES)


def _looks_like_shopping_done_phrase(transcript_lower: str) -> bool:
    txt = str(transcript_lower or "").strip().lower()
    if not txt:
        return False
    return any(p in txt for p in _SHOPPING_DONE_PHRASES)


def _looks_like_strong_shortage_phrase(transcript_lower: str) -> bool:
    txt = str(transcript_lower or "").strip().lower()
    if not txt:
        return False
    # Weak shortage phrases (running low / 快没了) should not be treated as strong shortage.
    if any(p in txt for p in _WEAK_SHORTAGE_PHRASES):
        return False
    return any(p in txt for p in _STRONG_SHORTAGE_PHRASES)


def _looks_like_inventory_presence_phrase(transcript_lower: str) -> bool:
    txt = str(transcript_lower or "").strip().lower()
    if not txt:
        return False
    return any(p in txt for p in _INVENTORY_PRESENCE_PHRASES)


def _canonical_item_name(item_name: str) -> str:
    raw = str(item_name or "").strip()
    if not raw:
        return ""
    key = raw.lower()
    if raw in _ITEM_CANONICAL:
        return _ITEM_CANONICAL[raw]
    if key in _ITEM_CANONICAL:
        return _ITEM_CANONICAL[key]
    return " ".join(raw.split())


def _default_effective_date(request_time: str) -> str:
    txt = str(request_time or "").strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
        return dt.date().isoformat()
    except Exception:
        return datetime.now(timezone.utc).date().isoformat()


def _no_action(reason: str) -> dict[str, Any]:
    return {"tool": "no_action", "args": {"reason": str(reason or "no_action")}}


def _load_system_prompt() -> str:
    repo_root = Path(__file__).resolve().parents[2]
    prompt_path = repo_root / "docs" / "prompt" / "voice_prompt_v1.md"
    if not prompt_path.exists():
        return _SYSTEM_PROMPT_FALLBACK

    txt = prompt_path.read_text(encoding="utf-8")
    m = re.search(r"## System Prompt\s*```text\n(.*?)\n```", txt, re.DOTALL)
    if not m:
        return _SYSTEM_PROMPT_FALLBACK
    prompt = m.group(1).strip()
    return prompt or _SYSTEM_PROMPT_FALLBACK


def _validate_against_schema(action: dict[str, Any]) -> bool:
    try:
        import jsonschema
    except Exception:
        return True

    repo_root = Path(__file__).resolve().parents[2]
    schema_path = repo_root / "docs" / "prompt" / "voice_tools_schema_v1.json"
    if not schema_path.exists():
        return True

    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        jsonschema.validate(action, schema)
        return True
    except Exception:
        return False


def _validate_plan_against_schema(plan: dict[str, Any]) -> bool:
    if not isinstance(plan, dict):
        return False
    actions = plan.get("actions")
    if not isinstance(actions, list) or not actions:
        return False
    for row in actions[: _MAX_PLAN_ACTIONS]:
        if not isinstance(row, dict):
            return False
        if not _validate_against_schema(row):
            return False
    return True
