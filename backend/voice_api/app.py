from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel, Field

from app.shared.env import load_repo_dotenv
from backend.voice_api.service import interpret_request_with_debug

load_repo_dotenv(os.path.dirname(__file__))


class VoiceInterpretRequest(BaseModel):
    request_id: str = Field(min_length=1, max_length=128)
    request_time: str = Field(min_length=1, max_length=64)
    timezone: str = Field(min_length=1, max_length=64)
    locale: str = Field(default="en-US", min_length=2, max_length=32)
    household_id: str | None = None
    audio_base64: str | None = None
    transcript: str | None = None
    board_context: dict[str, Any] | None = None


class VoiceInterpretResponse(BaseModel):
    action: dict[str, Any]
    plan: dict[str, Any] | None = None
    transcript: str = ""


app = FastAPI(title="Voice Interpret API", version="0.1.0")
_cache_lock = threading.Lock()
_idempotency_cache: dict[str, dict[str, Any]] = {}
_inflight_requests: dict[str, dict[str, Any]] = {}
_IDEMPOTENCY_CACHE_TTL_S = float(os.environ.get("VOICE_API_IDEMPOTENCY_TTL_S", "900") or 900.0)
_IDEMPOTENCY_CACHE_MAX_SIZE = int(os.environ.get("VOICE_API_IDEMPOTENCY_MAX_SIZE", "4096") or 4096)
_IDEMPOTENCY_INFLIGHT_WAIT_TIMEOUT_S = float(os.environ.get("VOICE_API_IDEMPOTENCY_WAIT_TIMEOUT_S", "15") or 15.0)
_log = logging.getLogger("voice_api")
if not _log.handlers:
    logging.basicConfig(level=logging.INFO)

if str(os.environ.get("VOICE_API_VERBOSE_UPSTREAM", "0")).strip().lower() not in {"1", "true", "yes"}:
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("google_genai").setLevel(logging.WARNING)
    logging.getLogger("google_genai.models").setLevel(logging.WARNING)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/voice/interpret", response_model=VoiceInterpretResponse)
def voice_interpret(req: VoiceInterpretRequest) -> VoiceInterpretResponse:
    req_dict = req.model_dump()
    req_id = str(req_dict.get("request_id") or "").strip()
    inflight_entry: dict[str, Any] | None = None
    is_leader = False

    if req_id:
        with _cache_lock:
            _prune_idempotency_cache_locked(now_ts=time.time())
            cached = _idempotency_cache.get(req_id)
            if cached is None:
                inflight_entry = _inflight_requests.get(req_id)
                if inflight_entry is None:
                    inflight_entry = {"event": threading.Event(), "action": None, "plan": None, "transcript": "", "error": None}
                    _inflight_requests[req_id] = inflight_entry
                    is_leader = True
        if cached is not None:
            _log.info(
                "voice_interpret cached request_id=%s action=%s transcript=%s",
                req_id,
                _summarize_action(dict(cached.get("action") or {})),
                _clip_log_text(str(cached.get("transcript") or "")),
            )
            return VoiceInterpretResponse(
                action=dict(cached.get("action") or {}),
                plan=dict(cached.get("plan") or {}) if isinstance(cached.get("plan"), dict) else None,
                transcript=str(cached.get("transcript") or ""),
            )
        if inflight_entry is not None and not is_leader:
            _log.info("voice_interpret waiting request_id=%s inflight=true", req_id)
            wait_timeout_s = float(_IDEMPOTENCY_INFLIGHT_WAIT_TIMEOUT_S or 0.0)
            done = inflight_entry["event"].wait(timeout=wait_timeout_s if wait_timeout_s > 0 else None)
            if not done:
                # Leader appears stuck; drop stale inflight marker and fail fast so caller can retry.
                with _cache_lock:
                    current = _inflight_requests.get(req_id)
                    if current is inflight_entry:
                        _inflight_requests.pop(req_id, None)
                raise TimeoutError(f"idempotency wait timeout for request_id={req_id}")
            err = inflight_entry.get("error")
            if err is not None:
                raise err
            action = dict(inflight_entry.get("action") or {})
            plan = dict(inflight_entry.get("plan") or {}) if isinstance(inflight_entry.get("plan"), dict) else None
            transcript = str(inflight_entry.get("transcript") or "")
            _log.info(
                "voice_interpret inflight-reuse request_id=%s action=%s transcript=%s",
                req_id,
                _summarize_action(action),
                _clip_log_text(transcript),
            )
            return VoiceInterpretResponse(action=action, plan=plan, transcript=transcript)

    try:
        result = interpret_request_with_debug(req_dict)
        action = dict(result.get("action") or {})
        plan = dict(result.get("plan") or {}) if isinstance(result.get("plan"), dict) else None
        transcript = str(result.get("transcript") or "")
    except Exception as e:
        if req_id and is_leader and inflight_entry is not None:
            with _cache_lock:
                _inflight_requests.pop(req_id, None)
                inflight_entry["error"] = e
                inflight_entry["event"].set()
        raise

    if req_id:
        with _cache_lock:
            _idempotency_cache[req_id] = {"action": action, "plan": plan, "transcript": transcript, "_cached_at": time.time()}
            _prune_idempotency_cache_locked(now_ts=time.time())
            if is_leader and inflight_entry is not None:
                _inflight_requests.pop(req_id, None)
                inflight_entry["action"] = action
                inflight_entry["plan"] = plan
                inflight_entry["transcript"] = transcript
                inflight_entry["error"] = None
                inflight_entry["event"].set()

    _log.info(
        "voice_interpret request_id=%s action=%s transcript=%s",
        req_id or "<none>",
        _summarize_action(action),
        _clip_log_text(transcript),
    )

    return VoiceInterpretResponse(action=action, plan=plan, transcript=transcript)


def _prune_idempotency_cache_locked(*, now_ts: float | None = None) -> None:
    """Bound in-memory idempotency cache growth (TTL + size cap). Caller must hold _cache_lock."""
    if not _idempotency_cache:
        return

    now_v = float(time.time() if now_ts is None else now_ts)
    ttl_s = float(_IDEMPOTENCY_CACHE_TTL_S or 0.0)
    if ttl_s > 0:
        expired_keys = [
            k
            for k, v in list(_idempotency_cache.items())
            if (now_v - float((v or {}).get("_cached_at") or 0.0)) > ttl_s
        ]
        for k in expired_keys:
            _idempotency_cache.pop(k, None)

    max_size = int(_IDEMPOTENCY_CACHE_MAX_SIZE or 0)
    if max_size > 0:
        while len(_idempotency_cache) > max_size:
            oldest_key = next(iter(_idempotency_cache), None)
            if oldest_key is None:
                break
            _idempotency_cache.pop(oldest_key, None)


def _clip_log_text(text: str, max_len: int = 180) -> str:
    txt = " ".join(str(text or "").split())
    if not txt:
        return "<empty>"
    if len(txt) <= max_len:
        return txt
    return txt[: max_len - 3] + "..."


def _summarize_action(action: dict[str, Any]) -> str:
    if not isinstance(action, dict):
        return "no_action(invalid_action)"
    tool = str(action.get("tool") or "no_action").strip() or "no_action"
    args = action.get("args")
    if not isinstance(args, dict):
        args = {}
    if tool == "inventory_log_event":
        item = str(args.get("item_name") or "?").strip() or "?"
        event_type = str(args.get("event_type") or "?").strip() or "?"
        day = str(args.get("effective_date") or "").strip()
        if day:
            return f"inventory_log_event(item={item}, event={event_type}, date={day})"
        return f"inventory_log_event(item={item}, event={event_type})"
    if tool == "open_app":
        app = str(args.get("app") or "?").strip() or "?"
        return f"open_app(app={app})"
    if tool == "inventory_set_expiry":
        item = str(args.get("item_name") or "?").strip() or "?"
        day = str(args.get("expiry_date") or "?").strip() or "?"
        return f"inventory_set_expiry(item={item}, expiry={day})"
    if tool == "inventory_clear_all":
        return "inventory_clear_all"
    if tool == "shopping_add_item":
        item = str(args.get("item_name") or "?").strip() or "?"
        return f"shopping_add_item(item={item})"
    if tool == "shopping_remove_item":
        item = str(args.get("item_name") or "").strip()
        source = str(args.get("source") or "reminders").strip() or "reminders"
        if item:
            return f"shopping_remove_item(source={source}, item={item})"
        mode = str(args.get("position_mode") or "?").strip() or "?"
        count = str(args.get("count") or "1").strip() or "1"
        index = str(args.get("index") or "").strip()
        if mode == "index" and index:
            return f"shopping_remove_item(source={source}, position=index:{index}, count={count})"
        return f"shopping_remove_item(source={source}, position={mode}, count={count})"
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
            idx = str(args.get("index") or "?").strip() or "?"
            return f"memo_delete(index={idx})"
        if target == "author":
            author = str(args.get("author") or "?").strip() or "?"
            return f"memo_delete(author={author})"
        return "memo_delete(latest)"
    if tool == "memo_update":
        target = str(args.get("target") or "latest").strip() or "latest"
        txt = str(args.get("text") or "").strip()
        if len(txt) > 18:
            txt = txt[:15] + "..."
        if target == "index":
            idx = str(args.get("index") or "?").strip() or "?"
            return f"memo_update(index={idx}, text={txt or '?'})"
        if target == "author":
            author = str(args.get("author") or "?").strip() or "?"
            return f"memo_update(author={author}, text={txt or '?'})"
        return f"memo_update(latest, text={txt or '?'})"
    if tool == "memo_clear_all":
        return "memo_clear_all"
    reason = str(args.get("reason") or "no_action").strip() or "no_action"
    return f"no_action(reason={reason})"
