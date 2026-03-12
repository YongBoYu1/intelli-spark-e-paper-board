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
_ALLOWED_EVENT_TYPES = {"consumed", "used", "added", "restocked", "finished"}
_OPEN_APP_NAMES = {"home", "weather", "calendar", "timer", "memo", "reminders", "inventory", "settings"}
_NO_ACTION_RETRY_BLOCKED_REASONS = {
    "missing_audio_or_transcript",
    "missing_google_api_key",
    "schema_validation_failed",
    "invalid_response_shape",
}
_LOW_RISK_RETRY_TOOLS = {
    "open_app",
    "inventory_log_event",
    "inventory_set_expiry",
    "shopping_add_item",
    "shopping_remove_item",
    "timer_set",
    "timer_add",
    "timer_pause",
    "timer_resume",
    "timer_stop",
    "memo_add",
    "no_action",
}

_SYSTEM_PROMPT_FALLBACK = (
    "You are a voice-command interpreter for a smart fridge magnet. "
    "Return one or more function calls in order for actionable intents. "
    "Available action tools: open_app, inventory_log_event, inventory_set_expiry, inventory_clear_all, "
    "shopping_add_item, shopping_remove_item, shopping_clear_all, timer_set, timer_add, timer_pause, timer_resume, timer_stop, "
    "memo_add, memo_delete, memo_update, memo_clear_all, "
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
    locale = str(req.get("locale") or "en-US").strip() or "en-US"
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
        plan = _maybe_retry_low_risk_no_action(
            plan=plan,
            api_key=api_key,
            model=model,
            transcript=transcript,
            request_time=request_time,
            timezone_name=timezone_name,
            locale=locale,
            board_context=board_context,
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

    if tool == "open_app":
        raw_app = str(
            args.get("app")
            or args.get("app_name")
            or args.get("screen")
            or args.get("target")
            or ""
        ).strip()
        app_name = _canonical_open_app_name(raw_app)
        if not app_name:
            return _no_action("invalid_app_name")
        return {"tool": "open_app", "args": {"app": app_name}}

    if tool == "shopping_add_item":
        item_raw = str(args.get("item_name") or args.get("item") or "").strip()
        item_name = _canonical_item_name(item_raw)
        if not item_name:
            return _no_action("missing_item_name")
        return {"tool": "shopping_add_item", "args": {"item_name": item_name}}

    if tool == "shopping_remove_item":
        item_raw = str(args.get("item_name") or args.get("item") or "").strip()
        item_name = _canonical_item_name(item_raw)
        source = _normalize_remove_source(args)
        if source is None:
            return _no_action("invalid_remove_source")
        if item_name:
            out_args: dict[str, Any] = {"item_name": item_name}
            if source != "reminders":
                out_args["source"] = source
            return {"tool": "shopping_remove_item", "args": out_args}

        positional = _normalize_positional_remove_args(args)
        if positional is None:
            return _no_action("missing_item_or_position")
        return {"tool": "shopping_remove_item", "args": positional}

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

    if tool == "timer_add":
        secs = _coerce_timer_delta_seconds(args)
        if secs <= 0:
            return _no_action("invalid_duration_seconds")
        return {"tool": "timer_add", "args": {"delta_seconds": secs}}

    if tool in {"timer_pause", "timer_resume", "timer_stop"}:
        return {"tool": tool, "args": {}}

    if tool == "memo_add":
        text = str(args.get("text") or args.get("memo_text") or args.get("content") or "").strip()
        if not text:
            return _no_action("missing_memo_text")
        author = str(args.get("author") or "Voice").strip() or "Voice"
        return {"tool": "memo_add", "args": {"text": text[:240], "author": author[:24]}}

    if tool == "memo_delete":
        target = _normalize_memo_target(args)
        if target is None:
            return _no_action("missing_memo_target")
        return {"tool": "memo_delete", "args": target}

    if tool == "memo_update":
        text = str(
            args.get("text")
            or args.get("new_text")
            or args.get("content")
            or args.get("memo_text")
            or ""
        ).strip()
        if not text:
            return _no_action("missing_memo_text")
        target = _normalize_memo_target(args)
        if target is None:
            return _no_action("missing_memo_target")
        out_args = dict(target)
        out_args["text"] = text[:240]
        return {"tool": "memo_update", "args": out_args}

    if tool == "memo_clear_all":
        confirm_token = str(args.get("confirm_token") or args.get("confirm") or "").strip().lower()
        out_args: dict[str, Any] = {}
        if confirm_token:
            out_args["confirm_token"] = confirm_token
        return {"tool": "memo_clear_all", "args": out_args}

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
    for raw in raw_actions:
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
        "actions": actions,
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


def _is_no_action(action: dict[str, Any] | None) -> bool:
    if not isinstance(action, dict):
        return False
    return str(action.get("tool") or "").strip() == "no_action"


def _should_retry_no_action(plan: dict[str, Any]) -> bool:
    if not isinstance(plan, dict):
        return False
    first = _first_action_from_plan(plan)
    if not _is_no_action(first):
        return False
    reason = str((first.get("args") or {}).get("reason") or "no_action").strip().lower()
    if reason.startswith("gemini_error:"):
        return False
    if reason in _NO_ACTION_RETRY_BLOCKED_REASONS:
        return False
    return True


def _plan_is_low_risk_retry_safe(plan: dict[str, Any]) -> bool:
    if not isinstance(plan, dict):
        return False
    actions = plan.get("actions")
    if not isinstance(actions, list) or not actions:
        return False
    for row in actions:
        if not isinstance(row, dict):
            return False
        tool = str(row.get("tool") or "").strip()
        if not tool or tool not in _LOW_RISK_RETRY_TOOLS:
            return False
    return True


def _maybe_retry_low_risk_no_action(
    *,
    plan: dict[str, Any],
    api_key: str,
    model: str,
    transcript: str,
    request_time: str,
    timezone_name: str,
    locale: str,
    board_context: dict[str, Any] | None,
) -> dict[str, Any]:
    if not _should_retry_no_action(plan):
        return plan
    txt = str(transcript or "").strip()
    if not txt:
        return plan
    try:
        retry_raw = _call_gemini_for_action(
            api_key=api_key,
            model=model,
            transcript=txt,
            request_time=request_time,
            timezone_name=timezone_name,
            locale=locale,
            board_context=board_context,
            allowed_tools=_LOW_RISK_RETRY_TOOLS,
            retry_mode="no_action_low_risk",
        )
        retry_plan = normalize_plan(retry_raw, request_time=request_time)
        if not _plan_is_low_risk_retry_safe(retry_plan):
            return plan
        if _is_no_action(_first_action_from_plan(retry_plan)):
            return plan
        return retry_plan
    except Exception:
        return plan


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


def _call_gemini_for_action(
    *,
    api_key: str,
    model: str,
    transcript: str,
    request_time: str,
    timezone_name: str,
    locale: str,
    board_context: dict[str, Any] | None = None,
    allowed_tools: set[str] | None = None,
    retry_mode: str = "",
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
        "Return function calls only (no plain text).",
        "For multi-intent utterances, return all reasonable function calls in order.",
        "Use undo_last_action_group / redo_last_action_group only when user explicitly says undo/redo/revert.",
        "Phrases like 'do that again', 'same again', 'one more time' usually mean repeat recent_action_groups, not redo.",
        "For vague pronouns (it/that/one/thing) without clear referent in context, prefer no_action(reason='insufficient_context').",
        "If one sentence lists multiple shopping items, emit one shopping_add_item per item in order.",
        "Checklist intents (check/tick/cross off items) should map to shopping_remove_item by name or position; use source='reminders' or 'inventory'.",
        "Treat casual leftover-in-fridge phrasing as inventory_log_event(event_type='added').",
        "Use timer_set for new timer duration; use timer_add/timer_pause/timer_resume/timer_stop for control intents.",
        "Do not infer timer_set from bare numbers unless timer intent is explicit.",
    ]
    if retry_mode == "no_action_low_risk":
        context_lines.extend(
            [
                "Recovery pass: previous interpretation produced no_action.",
                "Only use low-risk tools from this call; do not emit clear-all or memo-delete/update actions.",
                "If still uncertain, call no_action(reason='insufficient_intent').",
            ]
        )
    context_lines.append(f"transcript: {transcript}")
    if board_context:
        context_lines.append(_board_context_line(board_context))
    contents.append("\n".join(context_lines))

    response = client.models.generate_content(
        model=model,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=_load_system_prompt(),
            tools=_tool_declarations(allowed_tools=allowed_tools),
            tool_config=types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(mode="ANY")
            ),
        ),
    )

    actions = _extract_function_call_actions(response)
    if actions:
        if len(actions) == 1:
            return actions[0]
        return {"actions": actions}

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
            "Return function calls only (no plain text).",
            "For multi-intent utterances, return all reasonable function calls in order.",
            "Use undo_last_action_group / redo_last_action_group only when user explicitly says undo/redo/revert.",
            "Phrases like 'do that again', 'same again', 'one more time' usually mean repeat recent_action_groups, not redo.",
            "For vague pronouns (it/that/one/thing) without clear referent in context, prefer no_action(reason='insufficient_context').",
            "If one sentence lists multiple shopping items, emit one shopping_add_item per item in order.",
            "Checklist intents (check/tick/cross off items) should map to shopping_remove_item by name or position; use source='reminders' or 'inventory'.",
            "Treat casual leftover-in-fridge phrasing as inventory_log_event(event_type='added').",
            "Use timer_set for new timer duration; use timer_add/timer_pause/timer_resume/timer_stop for control intents.",
            "Do not infer timer_set from bare numbers unless timer intent is explicit.",
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
    actions = _extract_function_call_actions(response)
    if actions:
        if len(actions) == 1:
            return actions[0]
        return {"actions": actions}
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


def _extract_function_call_actions(response: Any) -> list[dict[str, Any]]:
    cands = list(getattr(response, "candidates", None) or [])
    for cand in cands:
        content = getattr(cand, "content", None)
        parts = list(getattr(content, "parts", None) or [])
        out: list[dict[str, Any]] = []
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
                out.append({"tool": name, "args": args})
        if out:
            return out
    return []


def _tool_declarations(*, allowed_tools: set[str] | None = None) -> list[dict[str, Any]]:
    declarations: list[dict[str, Any]] = [
        {
            "name": "open_app",
            "description": "Open or route to an app/screen",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "app": {
                        "type": "STRING",
                        "enum": ["home", "weather", "calendar", "timer", "memo", "reminders", "inventory", "settings"],
                    },
                },
                "required": ["app"],
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
                    "description": "Remove shopping/reminder items by name or by position",
                    "parameters": {
                        "type": "OBJECT",
                        "properties": {
                            "item_name": {"type": "STRING"},
                            "source": {"type": "STRING", "enum": ["reminders", "inventory"]},
                            "position_mode": {"type": "STRING", "enum": ["first", "last", "index"]},
                            "index": {"type": "INTEGER", "minimum": 1},
                            "count": {"type": "INTEGER", "minimum": 1},
                        },
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
                    "name": "timer_add",
                    "description": "Add seconds to the current timer",
                    "parameters": {
                        "type": "OBJECT",
                        "properties": {
                            "delta_seconds": {"type": "INTEGER", "minimum": 1},
                        },
                        "required": ["delta_seconds"],
                    },
        },
        {
                    "name": "timer_pause",
                    "description": "Pause the current timer",
                    "parameters": {
                        "type": "OBJECT",
                        "properties": {},
                    },
        },
        {
                    "name": "timer_resume",
                    "description": "Resume the paused timer",
                    "parameters": {
                        "type": "OBJECT",
                        "properties": {},
                    },
        },
        {
                    "name": "timer_stop",
                    "description": "Stop and clear the timer",
                    "parameters": {
                        "type": "OBJECT",
                        "properties": {},
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
                    "name": "memo_delete",
                    "description": "Delete memo by latest, ordinal position, or author",
                    "parameters": {
                        "type": "OBJECT",
                        "properties": {
                            "target": {"type": "STRING", "enum": ["latest", "index", "author"]},
                            "index": {"type": "INTEGER", "minimum": 1},
                            "author": {"type": "STRING"},
                        },
                    },
        },
        {
                    "name": "memo_update",
                    "description": "Update memo text by latest, ordinal position, or author",
                    "parameters": {
                        "type": "OBJECT",
                        "properties": {
                            "target": {"type": "STRING", "enum": ["latest", "index", "author"]},
                            "index": {"type": "INTEGER", "minimum": 1},
                            "author": {"type": "STRING"},
                            "text": {"type": "STRING"},
                        },
                        "required": ["text"],
                    },
        },
        {
                    "name": "memo_clear_all",
                    "description": "Request clearing all family board messages (requires physical confirmation on device)",
                    "parameters": {
                        "type": "OBJECT",
                        "properties": {
                            "confirm_token": {"type": "STRING"},
                        },
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
    if allowed_tools is not None:
        allowed = {str(t or "").strip() for t in allowed_tools if str(t or "").strip()}
        declarations = [row for row in declarations if str(row.get("name") or "").strip() in allowed]
    return [{"functionDeclarations": declarations}]


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


def _normalize_remove_source(args: dict[str, Any], *, default: str = "reminders") -> str | None:
    raw = str(args.get("source") or "").strip().lower()
    if not raw:
        return default
    if raw in {"reminders", "inventory"}:
        return raw
    return None


def _normalize_positional_remove_args(args: dict[str, Any]) -> dict[str, Any] | None:
    source = _normalize_remove_source(args)
    if source is None:
        return None

    position = str(args.get("position_mode") or "").strip().lower()
    index = _coerce_positive_int(args.get("index"))
    if not position:
        if index > 0:
            position = "index"
        else:
            return None
    if position not in {"first", "last", "index"}:
        return None
    if position == "index" and index <= 0:
        return None

    count = _coerce_positive_int(args.get("count") or 1)
    if count <= 0:
        count = 1

    out: dict[str, Any] = {"source": source, "position_mode": position, "count": count}
    if position == "index":
        out["index"] = index
    return out


def _normalize_memo_target(args: dict[str, Any]) -> dict[str, Any] | None:
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


def _coerce_timer_delta_seconds(args: dict[str, Any]) -> int:
    proxy = dict(args or {})
    if "duration_seconds" not in proxy:
        for key in ("delta_seconds", "add_seconds", "seconds", "duration"):
            if key in proxy:
                proxy["duration_seconds"] = proxy.get(key)
                break
    return _coerce_duration_seconds(proxy)


def _canonical_item_name(item_name: str) -> str:
    raw = str(item_name or "").strip()
    if not raw:
        return ""
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
    for row in actions:
        if not isinstance(row, dict):
            return False
        if not _validate_against_schema(row):
            return False
    return True
