from __future__ import annotations

import base64
import json
from typing import Any
from urllib import request, error

from app.voice.actions import VoiceRequestMeta


class VoiceClientError(RuntimeError):
    pass


def interpret_audio_via_backend(
    *,
    api_url: str,
    audio_path: str,
    meta: VoiceRequestMeta,
    timeout_s: float = 20.0,
    board_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not api_url:
        raise VoiceClientError("VOICE_API_URL is not configured")

    with open(audio_path, "rb") as f:
        audio_raw = f.read()

    payload = {
        "request_id": meta.request_id,
        "request_time": meta.request_time,
        "timezone": meta.timezone,
        "locale": meta.locale,
        "audio_base64": base64.b64encode(audio_raw).decode("ascii"),
    }
    if isinstance(board_context, dict) and board_context:
        payload["board_context"] = board_context

    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        api_url,
        data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )

    try:
        with request.urlopen(req, timeout=float(timeout_s)) as resp:
            txt = resp.read().decode("utf-8", errors="replace")
            data = json.loads(txt)
            if not isinstance(data, dict):
                raise VoiceClientError("backend returned non-object JSON")
            return data
    except error.HTTPError as e:
        text = e.read().decode("utf-8", errors="replace")
        raise VoiceClientError(f"backend HTTP {e.code}: {text[:180]}") from e
    except error.URLError as e:
        raise VoiceClientError(f"network error: {e.reason}") from e
    except json.JSONDecodeError as e:
        raise VoiceClientError("backend returned invalid JSON") from e


def interpret_transcript_via_backend(
    *,
    api_url: str,
    transcript: str,
    meta: VoiceRequestMeta,
    timeout_s: float = 20.0,
    board_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not api_url:
        raise VoiceClientError("VOICE_API_URL is not configured")

    payload = {
        "request_id": meta.request_id,
        "request_time": meta.request_time,
        "timezone": meta.timezone,
        "locale": meta.locale,
        "transcript": str(transcript or ""),
    }
    if isinstance(board_context, dict) and board_context:
        payload["board_context"] = board_context

    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        api_url,
        data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )

    try:
        with request.urlopen(req, timeout=float(timeout_s)) as resp:
            txt = resp.read().decode("utf-8", errors="replace")
            data = json.loads(txt)
            if not isinstance(data, dict):
                raise VoiceClientError("backend returned non-object JSON")
            return data
    except error.HTTPError as e:
        text = e.read().decode("utf-8", errors="replace")
        raise VoiceClientError(f"backend HTTP {e.code}: {text[:180]}") from e
    except error.URLError as e:
        raise VoiceClientError(f"network error: {e.reason}") from e
    except json.JSONDecodeError as e:
        raise VoiceClientError("backend returned invalid JSON") from e
