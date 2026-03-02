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

_ALLOWED_TOOLS = {
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
_ALLOWED_EVENT_TYPES = {"consumed", "used", "added", "restocked", "finished"}

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
    "Use exactly one function call among inventory_log_event, inventory_set_expiry, inventory_clear_all, "
    "shopping_add_item, shopping_remove_item, shopping_clear_all, timer_set, memo_add, no_action."
)


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

    if not transcript and not audio_base64:
        return {"action": _no_action("missing_audio_or_transcript"), "transcript": ""}

    api_key = str(os.environ.get("GOOGLE_API_KEY") or "").strip()
    if not api_key:
        return {"action": _no_action("missing_google_api_key"), "transcript": transcript}

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
        if not transcript:
            # Fallback: let Gemini infer directly from audio when text transcription is empty.
            raw_action = _call_gemini_for_action_from_audio(
                api_key=api_key,
                model=model,
                request_time=request_time,
                timezone_name=timezone_name,
                locale=locale,
                audio_path=temp_audio_path,
                board_context=board_context,
            )
            action = normalize_action(raw_action, request_time=request_time)
            action = _align_action_with_transcript(action, transcript=transcript)
            if not _validate_against_schema(action):
                return {"action": _no_action("schema_validation_failed"), "transcript": ""}
            return {"action": action, "transcript": ""}

        raw_action = _call_gemini_for_action(
            api_key=api_key,
            model=model,
            transcript=transcript,
            request_time=request_time,
            timezone_name=timezone_name,
            locale=locale,
            board_context=board_context,
        )

        action = normalize_action(raw_action, request_time=request_time)
        action = _align_action_with_transcript(action, transcript=transcript)
        if not _validate_against_schema(action):
            return {"action": _no_action("schema_validation_failed"), "transcript": transcript}
        return {"action": action, "transcript": transcript}
    except Exception as e:
        return {"action": _no_action(f"gemini_error:{str(e)[:80]}"), "transcript": transcript}
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
