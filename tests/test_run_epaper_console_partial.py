from __future__ import annotations

import datetime
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
    def test_read_key_nonblocking_waits_for_split_left_arrow_sequence(self) -> None:
        stdin_mock = type("FakeStdin", (), {})()
        reads = iter(["\x1b", "[", "D"])

        def fake_read(_n: int) -> str:
            return next(reads)

        select_results = iter([
            ([stdin_mock], [], []),
            ([stdin_mock], [], []),
            ([stdin_mock], [], []),
        ])

        with (
            patch.object(rec.sys, "stdin", stdin_mock),
            patch.object(stdin_mock, "read", side_effect=fake_read, create=True),
            patch.object(rec.select, "select", side_effect=lambda *_args, **_kwargs: next(select_results)),
        ):
            key = rec._read_key_nonblocking()

        self.assertEqual(key, "\x1b[D")

    def test_read_key_nonblocking_keeps_bare_escape_as_back(self) -> None:
        stdin_mock = type("FakeStdin", (), {})()

        with (
            patch.object(rec.sys, "stdin", stdin_mock),
            patch.object(stdin_mock, "read", return_value="\x1b", create=True),
            patch.object(rec.select, "select", side_effect=[([stdin_mock], [], []), ([], [], [])]),
        ):
            key = rec._read_key_nonblocking()

        self.assertEqual(key, "\x1b")

    def test_read_key_nonblocking_accepts_longer_csi_arrow_sequence(self) -> None:
        stdin_mock = type("FakeStdin", (), {})()
        reads = iter(["\x1b", "[", "1", ";", "5", "D"])

        def fake_read(_n: int) -> str:
            return next(reads)

        select_results = iter([
            ([stdin_mock], [], []),
            ([stdin_mock], [], []),
            ([stdin_mock], [], []),
            ([stdin_mock], [], []),
            ([stdin_mock], [], []),
            ([stdin_mock], [], []),
            ([], [], []),
        ])

        with (
            patch.object(rec.sys, "stdin", stdin_mock),
            patch.object(stdin_mock, "read", side_effect=fake_read, create=True),
            patch.object(rec.select, "select", side_effect=lambda *_args, **_kwargs: next(select_results)),
        ):
            key = rec._read_key_nonblocking()

        self.assertEqual(key, "\x1b[D")

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

    def test_next_weather_refresh_at_12h_aligns_to_noon(self) -> None:
        now = datetime.datetime(2026, 1, 15, 11, 59, 30).timestamp()
        nxt = rec._next_weather_refresh_at(now, 12.0)
        expected = datetime.datetime(2026, 1, 15, 12, 0, 0).timestamp()
        self.assertAlmostEqual(nxt, expected, delta=1.0)

    def test_next_weather_refresh_at_12h_aligns_to_next_midnight(self) -> None:
        now = datetime.datetime(2026, 1, 15, 12, 1, 0).timestamp()
        nxt = rec._next_weather_refresh_at(now, 12.0)
        expected = datetime.datetime(2026, 1, 16, 0, 0, 0).timestamp()
        self.assertAlmostEqual(nxt, expected, delta=1.0)

    def test_next_weather_refresh_at_non_12h_keeps_interval(self) -> None:
        now = datetime.datetime(2026, 1, 15, 7, 0, 0).timestamp()
        nxt = rec._next_weather_refresh_at(now, 6.0)
        self.assertAlmostEqual(nxt, now + 6 * 3600, delta=0.1)

    def test_weather_days_from_rows_preserves_zero_metric_values(self) -> None:
        rows = [
            {
                "dow": "MON",
                "icon": "sun",
                "hi": 10,
                "lo": 1,
                "wind_kmh": 0,
                "uv_index": 0,
                "feels_like": 0,
            }
        ]

        days = rec._weather_days_from_rows(rows)

        self.assertEqual(len(days), 1)
        self.assertEqual(days[0].wind_kmh, 0.0)
        self.assertEqual(days[0].uv_index, 0.0)
        self.assertEqual(days[0].feels_like, 0.0)


if __name__ == "__main__":
    unittest.main()
