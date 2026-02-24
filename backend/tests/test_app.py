from __future__ import annotations

import threading
import time
import unittest

from backend.voice_api import app as voice_app


class VoiceApiAppCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self._orig_cache = dict(voice_app._idempotency_cache)
        self._orig_inflight = dict(voice_app._inflight_requests)
        self._orig_ttl = voice_app._IDEMPOTENCY_CACHE_TTL_S
        self._orig_max = voice_app._IDEMPOTENCY_CACHE_MAX_SIZE
        self._orig_interpret = voice_app.interpret_request_with_debug
        voice_app._idempotency_cache.clear()
        voice_app._inflight_requests.clear()

    def tearDown(self) -> None:
        voice_app._idempotency_cache.clear()
        voice_app._idempotency_cache.update(self._orig_cache)
        voice_app._inflight_requests.clear()
        voice_app._inflight_requests.update(self._orig_inflight)
        voice_app._IDEMPOTENCY_CACHE_TTL_S = self._orig_ttl
        voice_app._IDEMPOTENCY_CACHE_MAX_SIZE = self._orig_max
        voice_app.interpret_request_with_debug = self._orig_interpret

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


if __name__ == "__main__":
    unittest.main()
