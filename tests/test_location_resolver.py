from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from app.data.location import detect_city_from_network, resolve_dashboard_location


class _FakeResponse:
    def __init__(self, payload: dict):
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        return self._body


class LocationResolverTests(unittest.TestCase):
    @patch.dict("os.environ", {"DASHBOARD_CITY": "Toronto"}, clear=True)
    def test_manual_env_city_has_highest_priority(self) -> None:
        self.assertEqual(resolve_dashboard_location("New York"), "Toronto")

    @patch.dict("os.environ", {"LOCATION_AUTO_DETECT": "0"}, clear=True)
    def test_uses_configured_location_when_auto_disabled(self) -> None:
        self.assertEqual(resolve_dashboard_location("Montreal"), "Montreal")

    @patch.dict("os.environ", {"LOCATION_AUTO_DETECT": "0"}, clear=True)
    def test_unknown_when_no_auto_and_no_configured_location(self) -> None:
        self.assertEqual(resolve_dashboard_location(""), "Unknown")

    @patch.dict("os.environ", {}, clear=True)
    @patch("app.data.location.detect_city_from_network", return_value="DetectedCity")
    def test_configured_location_takes_priority_over_auto_detect(self, _mock_detect) -> None:
        self.assertEqual(resolve_dashboard_location("ConfiguredCity"), "ConfiguredCity")

    @patch("app.data.location.urlopen")
    def test_detect_city_uses_first_available_source(self, mock_urlopen) -> None:
        mock_urlopen.return_value = _FakeResponse({"success": True, "city": "Vancouver"})
        self.assertEqual(detect_city_from_network(timeout_s=0.5), "Vancouver")

    @patch("app.data.location.urlopen")
    def test_detect_city_falls_back_to_region(self, mock_urlopen) -> None:
        mock_urlopen.return_value = _FakeResponse({"success": True, "city": "", "region": "Ontario"})
        self.assertEqual(detect_city_from_network(timeout_s=0.5), "Ontario")


if __name__ == "__main__":
    unittest.main()
