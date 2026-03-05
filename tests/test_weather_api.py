from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from app.data.weather_api import resolve_weather_data


class _FakeResponse:
    def __init__(self, payload: dict):
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        return self._body


class WeatherApiTests(unittest.TestCase):
    @patch.dict("os.environ", {"WEATHER_API_ENABLED": "0"}, clear=True)
    def test_disabled_uses_fallback_rows(self) -> None:
        fallback = [{"dow": "MON", "icon": "sun", "hi": 20, "lo": 10}]
        city, rows = resolve_weather_data("Toronto", fallback)
        self.assertEqual(city, "Toronto")
        self.assertEqual(rows, fallback)

    @patch.dict("os.environ", {}, clear=True)
    @patch("app.data.weather_api.urlopen")
    def test_open_meteo_success_replaces_weather_rows(self, mock_urlopen) -> None:
        def fake_urlopen(req, timeout=2.0):
            url = str(getattr(req, "full_url", req))
            if "geocoding-api.open-meteo.com" in url:
                return _FakeResponse(
                    {
                        "results": [
                            {
                                "name": "Toronto",
                                "latitude": 43.7,
                                "longitude": -79.4,
                                "timezone": "America/Toronto",
                            }
                        ]
                    }
                )
            if "api.open-meteo.com/v1/forecast" in url:
                return _FakeResponse(
                    {
                        "daily": {
                            "time": ["2026-03-04", "2026-03-05"],
                            "weather_code": [0, 61],
                            "temperature_2m_max": [5.4, 7.1],
                            "temperature_2m_min": [-1.2, 0.3],
                            "apparent_temperature_max": [3.8, 5.2],
                            "wind_speed_10m_max": [12.7, 18.1],
                            "uv_index_max": [2.2, 3.4],
                            "relative_humidity_2m_max": [68, 74],
                        }
                    }
                )
            raise AssertionError(f"Unexpected URL: {url}")

        mock_urlopen.side_effect = fake_urlopen
        city, rows = resolve_weather_data("Toronto", [{"dow": "MON", "icon": "cloud", "hi": 1, "lo": -1}])

        self.assertEqual(city, "Toronto")
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["icon"], "sun")
        self.assertEqual(rows[1]["icon"], "rain")
        self.assertEqual(rows[0]["hi"], 5)
        self.assertEqual(rows[0]["lo"], -1)

    @patch.dict("os.environ", {}, clear=True)
    @patch("app.data.weather_api.urlopen")
    def test_geocode_failure_falls_back(self, mock_urlopen) -> None:
        mock_urlopen.return_value = _FakeResponse({"results": []})
        fallback = [{"dow": "MON", "icon": "sun", "hi": 20, "lo": 10}]
        city, rows = resolve_weather_data("Unknown Place", fallback)
        self.assertEqual(city, "Unknown Place")
        self.assertEqual(rows, fallback)


if __name__ == "__main__":
    unittest.main()

