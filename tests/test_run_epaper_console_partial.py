from __future__ import annotations

import unittest
from unittest.mock import patch

from PIL import Image

from app.core.state import AppState, DashboardModel, WeatherDay
import tools.run_epaper_console as rec


class _FakeEpd:
    def __init__(self):
        self.mode = "full"
        self.partial_call = None

    def init_part(self):
        self.mode = "part"

    def init_fast(self):
        self.mode = "fast"

    def init(self):
        self.mode = "full"

    def display_Partial(self, image, x0, y0, x1, y1):
        self.partial_call = (image, x0, y0, x1, y1)


class RunEpaperConsolePartialTests(unittest.TestCase):
    def test_blit_partial_uses_end_coords_and_partial_buffer(self) -> None:
        epd = _FakeEpd()
        frame = Image.new("1", (800, 480), 255)
        rect = (24, 100, 224, 160)  # width=200, height=60 => bytes=1500

        mode = rec._blit_partial(epd, frame, rect, current_mode="full")

        self.assertEqual(mode, "part")
        self.assertIsNotNone(epd.partial_call)
        payload, x0, y0, x1, y1 = epd.partial_call
        self.assertEqual((x0, y0, x1, y1), rect)

        expected_len = ((x1 - x0) // 8) * (y1 - y0)
        self.assertEqual(len(payload), expected_len)

    @patch("tools.run_epaper_console.resolve_weather_data")
    @patch("tools.run_epaper_console.resolve_dashboard_location")
    def test_refresh_live_weather_updates_state(self, mock_resolve_location, mock_resolve_weather) -> None:
        state = AppState(
            model=DashboardModel(
                location="OldCity",
                weather=[WeatherDay(dow="MON", icon="sun", hi=20, lo=10)],
            )
        )
        mock_resolve_location.return_value = "Toronto"
        mock_resolve_weather.return_value = (
            "Toronto",
            [
                {"dow": "TUE", "icon": "rain", "hi": 11, "lo": 4, "humidity": 65},
                {"dow": "WED", "icon": "cloud", "hi": 9, "lo": 2},
            ],
        )

        changed = rec._refresh_live_weather(state)

        self.assertTrue(changed)
        self.assertEqual(state.model.location, "Toronto")
        self.assertEqual(len(state.model.weather), 2)
        self.assertEqual(state.model.weather[0].icon, "rain")
        self.assertEqual(state.model.weather[0].humidity, 65)

    @patch("tools.run_epaper_console.resolve_weather_data")
    @patch("tools.run_epaper_console.resolve_dashboard_location")
    def test_refresh_live_weather_keeps_state_when_rows_empty(self, mock_resolve_location, mock_resolve_weather) -> None:
        state = AppState(
            model=DashboardModel(
                location="OldCity",
                weather=[WeatherDay(dow="MON", icon="sun", hi=20, lo=10)],
            )
        )
        mock_resolve_location.return_value = "Toronto"
        mock_resolve_weather.return_value = ("Toronto", [])

        changed = rec._refresh_live_weather(state)

        self.assertFalse(changed)
        self.assertEqual(state.model.location, "OldCity")
        self.assertEqual(len(state.model.weather), 1)

    def test_state_render_sig_changes_when_location_changes(self) -> None:
        state = AppState(model=DashboardModel(location="A", weather=[WeatherDay(dow="MON", icon="sun", hi=1, lo=0)]))
        sig_a = rec._state_render_sig(state)
        state.model.location = "B"
        sig_b = rec._state_render_sig(state)
        self.assertNotEqual(sig_a, sig_b)


if __name__ == "__main__":
    unittest.main()
