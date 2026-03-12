from __future__ import annotations

import os
import tempfile
import unittest

from app.data.device_config import (
    default_device_config,
    load_device_config,
    save_device_config,
    sanitize_device_config,
)


class DeviceConfigTests(unittest.TestCase):
    def test_sanitize_applies_defaults_and_constraints(self) -> None:
        cfg = sanitize_device_config(
            {
                "setup_completed": "true",
                "language": "invalid",
                "voice_locale": "fr-FR",
                "timezone": "America/Toronto",
                "auto_sync_enabled": 0,
                "wifi_enabled": "1",
                "bluetooth_enabled": "no",
                "wifi_ssid": " Home ",
            }
        )
        self.assertTrue(cfg["setup_completed"])
        self.assertEqual(cfg["language"], "en-US")
        self.assertEqual(cfg["voice_locale"], "fr-FR")
        self.assertEqual(cfg["timezone"], "America/Toronto")
        self.assertFalse(cfg["auto_sync_enabled"])
        self.assertTrue(cfg["wifi_enabled"])
        self.assertFalse(cfg["bluetooth_enabled"])
        self.assertEqual(cfg["wifi_ssid"], "Home")

    def test_load_missing_returns_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cfg = load_device_config(td)
            defaults = default_device_config()
            self.assertEqual(set(cfg.keys()), set(defaults.keys()))
            self.assertEqual(cfg["setup_completed"], defaults["setup_completed"])

    def test_save_and_load_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            payload = {
                "setup_completed": True,
                "language": "es-ES",
                "voice_locale": "es-ES",
                "timezone": "America/Toronto",
                "auto_sync_enabled": False,
                "wifi_enabled": True,
                "bluetooth_enabled": False,
                "wifi_ssid": "MyHome",
            }
            os.makedirs(os.path.join(td, "data"), exist_ok=True)
            save_device_config(td, payload)
            loaded = load_device_config(td)
            self.assertEqual(loaded, sanitize_device_config(payload))


if __name__ == "__main__":
    unittest.main()
