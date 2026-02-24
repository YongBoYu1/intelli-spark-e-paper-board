from __future__ import annotations

import unittest

from backend.voice_api import app as voice_app


class VoiceApiAppCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self._orig_cache = dict(voice_app._idempotency_cache)
        self._orig_ttl = voice_app._IDEMPOTENCY_CACHE_TTL_S
        self._orig_max = voice_app._IDEMPOTENCY_CACHE_MAX_SIZE
        voice_app._idempotency_cache.clear()

    def tearDown(self) -> None:
        voice_app._idempotency_cache.clear()
        voice_app._idempotency_cache.update(self._orig_cache)
        voice_app._IDEMPOTENCY_CACHE_TTL_S = self._orig_ttl
        voice_app._IDEMPOTENCY_CACHE_MAX_SIZE = self._orig_max

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


if __name__ == "__main__":
    unittest.main()
