from __future__ import annotations

import os
import unittest

from app.voice.client import _build_request_headers


class VoiceClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self._orig_voice_api_token = os.environ.get("VOICE_API_TOKEN")
        os.environ.pop("VOICE_API_TOKEN", None)

    def tearDown(self) -> None:
        if self._orig_voice_api_token is None:
            os.environ.pop("VOICE_API_TOKEN", None)
        else:
            os.environ["VOICE_API_TOKEN"] = self._orig_voice_api_token

    def test_build_request_headers_uses_explicit_auth_token(self) -> None:
        headers = _build_request_headers(auth_token="device-secret")
        self.assertEqual(headers["Authorization"], "Bearer device-secret")
        self.assertEqual(headers["Content-Type"], "application/json")

    def test_build_request_headers_falls_back_to_env_token(self) -> None:
        os.environ["VOICE_API_TOKEN"] = "env-secret"
        headers = _build_request_headers(auth_token=None)
        self.assertEqual(headers["Authorization"], "Bearer env-secret")

    def test_build_request_headers_omits_authorization_when_token_missing(self) -> None:
        headers = _build_request_headers(auth_token="")
        self.assertNotIn("Authorization", headers)


if __name__ == "__main__":
    unittest.main()
