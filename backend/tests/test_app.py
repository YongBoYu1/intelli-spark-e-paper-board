from __future__ import annotations

import os
import threading
import time
import unittest

from fastapi.testclient import TestClient

from backend.voice_api import app as voice_app


class VoiceApiAppCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self._orig_cache = dict(voice_app._idempotency_cache)
        self._orig_inflight = dict(voice_app._inflight_requests)
        self._orig_ttl = voice_app._IDEMPOTENCY_CACHE_TTL_S
        self._orig_max = voice_app._IDEMPOTENCY_CACHE_MAX_SIZE
        self._orig_wait_timeout = voice_app._IDEMPOTENCY_INFLIGHT_WAIT_TIMEOUT_S
        self._orig_interpret = voice_app.interpret_request_with_debug
        self._orig_voice_api_token = os.environ.get("VOICE_API_TOKEN")
        self._orig_log_transcript = os.environ.get("VOICE_API_LOG_TRANSCRIPT")
        voice_app._idempotency_cache.clear()
        voice_app._inflight_requests.clear()
        os.environ.pop("VOICE_API_TOKEN", None)
        os.environ.pop("VOICE_API_LOG_TRANSCRIPT", None)

    def tearDown(self) -> None:
        voice_app._idempotency_cache.clear()
        voice_app._idempotency_cache.update(self._orig_cache)
        voice_app._inflight_requests.clear()
        voice_app._inflight_requests.update(self._orig_inflight)
        voice_app._IDEMPOTENCY_CACHE_TTL_S = self._orig_ttl
        voice_app._IDEMPOTENCY_CACHE_MAX_SIZE = self._orig_max
        voice_app._IDEMPOTENCY_INFLIGHT_WAIT_TIMEOUT_S = self._orig_wait_timeout
        voice_app.interpret_request_with_debug = self._orig_interpret
        if self._orig_voice_api_token is None:
            os.environ.pop("VOICE_API_TOKEN", None)
        else:
            os.environ["VOICE_API_TOKEN"] = self._orig_voice_api_token
        if self._orig_log_transcript is None:
            os.environ.pop("VOICE_API_LOG_TRANSCRIPT", None)
        else:
            os.environ["VOICE_API_LOG_TRANSCRIPT"] = self._orig_log_transcript

    def test_prune_idempotency_cache_evicts_expired_entries(self) -> None:
        voice_app._IDEMPOTENCY_CACHE_TTL_S = 10.0
        voice_app._IDEMPOTENCY_CACHE_MAX_SIZE = 100
        voice_app._idempotency_cache.update(
            {
                "old": {"action": {}, "transcript": "", "_cached_at": 100.0},
                "new": {"action": {}, "transcript": "", "_cached_at": 205.0},
            }
        )
        voice_app._prune_idempotency_cache_locked(now_ts=210.1)
        self.assertNotIn("old", voice_app._idempotency_cache)
        self.assertIn("new", voice_app._idempotency_cache)

    def test_prune_idempotency_cache_enforces_max_size_fifo(self) -> None:
        voice_app._IDEMPOTENCY_CACHE_TTL_S = 0.0
        voice_app._IDEMPOTENCY_CACHE_MAX_SIZE = 2
        voice_app._idempotency_cache.update(
            {
                "a": {"action": {}, "transcript": "", "_cached_at": 100.0},
                "b": {"action": {}, "transcript": "", "_cached_at": 101.0},
                "c": {"action": {}, "transcript": "", "_cached_at": 102.0},
            }
        )
        voice_app._prune_idempotency_cache_locked(now_ts=200.0)
        self.assertEqual(list(voice_app._idempotency_cache.keys()), ["b", "c"])

    def test_voice_interpret_dedupes_concurrent_inflight_same_request_id(self) -> None:
        start_event = threading.Event()
        release_event = threading.Event()
        calls: list[str] = []

        def fake_interpret(req_dict):
            calls.append(str(req_dict.get("request_id") or ""))
            start_event.set()
            release_event.wait(timeout=1.0)
            return {
                "action": {"tool": "shopping_add_item", "args": {"item_name": "milk"}},
                "transcript": str(req_dict.get("transcript") or ""),
            }

        voice_app.interpret_request_with_debug = fake_interpret
        voice_app._IDEMPOTENCY_CACHE_TTL_S = 60.0
        voice_app._IDEMPOTENCY_CACHE_MAX_SIZE = 100

        req = voice_app.VoiceInterpretRequest(
            request_id="voice-same-1",
            request_time="2026-02-24T23:59:58-08:00",
            timezone="America/Los_Angeles",
            locale="en-US",
            transcript="we're out of milk",
        )

        results: list[object] = []
        errors: list[BaseException] = []

        def worker() -> None:
            try:
                results.append(voice_app.voice_interpret(req))
            except BaseException as e:  # pragma: no cover - debug aid in test
                errors.append(e)

        t1 = threading.Thread(target=worker)
        t2 = threading.Thread(target=worker)
        t1.start()
        self.assertTrue(start_event.wait(timeout=1.0))
        t2.start()
        time.sleep(0.05)  # Give follower time to reach inflight wait path.
        release_event.set()
        t1.join(timeout=1.0)
        t2.join(timeout=1.0)

        self.assertFalse(t1.is_alive())
        self.assertFalse(t2.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].action, results[1].action)
        self.assertEqual(results[0].transcript, results[1].transcript)
        self.assertIn("voice-same-1", voice_app._idempotency_cache)
        self.assertNotIn("voice-same-1", voice_app._inflight_requests)

    def test_voice_interpret_follower_wait_timeout_clears_stale_inflight(self) -> None:
        entry = {"event": threading.Event(), "action": None, "transcript": "", "error": None}
        voice_app._inflight_requests["voice-stuck-1"] = entry
        voice_app._IDEMPOTENCY_CACHE_TTL_S = 60.0
        voice_app._IDEMPOTENCY_CACHE_MAX_SIZE = 100
        voice_app._IDEMPOTENCY_INFLIGHT_WAIT_TIMEOUT_S = 0.01

        req = voice_app.VoiceInterpretRequest(
            request_id="voice-stuck-1",
            request_time="2026-02-24T12:00:00+00:00",
            timezone="UTC",
            locale="en-US",
            transcript="hello",
        )

        with self.assertRaises(TimeoutError):
            voice_app.voice_interpret(req)

        self.assertNotIn("voice-stuck-1", voice_app._inflight_requests)

    def test_request_model_default_locale_is_en_us(self) -> None:
        req = voice_app.VoiceInterpretRequest(
            request_id="voice-locale-default",
            request_time="2026-02-24T12:00:00+00:00",
            timezone="UTC",
            transcript="hello",
        )
        self.assertEqual(req.locale, "en-US")

    def test_health_endpoint_does_not_require_auth(self) -> None:
        os.environ["VOICE_API_TOKEN"] = "shared-secret"
        client = TestClient(voice_app.app)
        resp = client.get("/health")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"status": "ok"})

    def test_voice_interpret_rejects_missing_auth_when_token_is_configured(self) -> None:
        os.environ["VOICE_API_TOKEN"] = "shared-secret"
        client = TestClient(voice_app.app)
        resp = client.post(
            "/voice/interpret",
            json={
                "request_id": "voice-auth-missing",
                "request_time": "2026-02-24T12:00:00+00:00",
                "timezone": "UTC",
                "locale": "en-US",
                "transcript": "add milk",
            },
        )
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json()["detail"], "missing_or_invalid_auth_token")

    def test_voice_interpret_accepts_valid_bearer_token(self) -> None:
        os.environ["VOICE_API_TOKEN"] = "shared-secret"
        client = TestClient(voice_app.app)

        def fake_interpret(req_dict):
            return {
                "action": {"tool": "shopping_add_item", "args": {"item_name": "milk"}},
                "plan": {"actions": [{"tool": "shopping_add_item", "args": {"item_name": "milk"}}]},
                "transcript": str(req_dict.get("transcript") or ""),
            }

        voice_app.interpret_request_with_debug = fake_interpret
        resp = client.post(
            "/voice/interpret",
            headers={"Authorization": "Bearer shared-secret"},
            json={
                "request_id": "voice-auth-ok",
                "request_time": "2026-02-24T12:00:00+00:00",
                "timezone": "UTC",
                "locale": "en-US",
                "transcript": "add milk",
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["action"]["tool"], "shopping_add_item")


if __name__ == "__main__":
    unittest.main()
