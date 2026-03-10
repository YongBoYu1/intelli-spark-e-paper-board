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
        self.init_count = 0
        self.full_display_count = 0
        self.clear_count = 0

    def init_part(self):
        self.mode = "part"

    def init_fast(self):
        self.mode = "fast"

    def init(self):
        self.mode = "full"
        self.init_count += 1

    def display_Partial(self, image, x0, y0, x1, y1):
        self.partial_call = (image, x0, y0, x1, y1)

    def getbuffer(self, image):
        return image

    def display(self, image):
        self.full_display_count += 1

    def Clear(self):
        self.clear_count += 1


class RunEpaperConsolePartialTests(unittest.TestCase):
    def test_partial_budget_default_matches_playbook(self) -> None:
        self.assertFalse(rec._partial_budget_enabled_with_theme({}))

    def test_onboarding_is_in_default_partial_whitelist(self) -> None:
        self.assertFalse(rec._screen_partial_enabled_with_theme(rec.Screen.ONBOARDING, {}))
        self.assertFalse(rec._screen_partial_enabled_with_theme(rec.Screen.LANDING, {}))

    def test_onboarding_force_full_clean_default(self) -> None:
        self.assertTrue(rec._screen_force_full_clean_with_theme(rec.Screen.ONBOARDING, {}))
        self.assertTrue(rec._screen_force_full_clean_with_theme(rec.Screen.LANDING, {}))
        self.assertFalse(rec._screen_force_full_clean_with_theme(rec.Screen.HOME, {}))

    def test_partial_gate_uses_total_area_not_single_rect_peak(self) -> None:
        rects = [
            (0, 120, 800, 360),
            (0, 350, 800, 480),
        ]
        max_ratio = max(rec.rect_area_ratio(r, 800, 480) for r in rects)
        gate_ratio = rec._partial_gate_area_ratio(rects, width=800, height=480)

        self.assertLess(max_ratio, 0.70)
        self.assertGreater(gate_ratio, 0.70)

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

    def test_blit_full_clean_reinits_driver(self) -> None:
        epd = _FakeEpd()
        frame = Image.new("1", (800, 480), 255)

        mode = rec._blit_full_clean(epd, frame)

        self.assertEqual(mode, "full")
        self.assertEqual(epd.init_count, 1)
        self.assertEqual(epd.clear_count, 1)
        self.assertEqual(epd.full_display_count, 1)

    def test_render_frame_uses_onboarding_tone_overrides(self) -> None:
        epd = _FakeEpd()
        epd.width = 800
        epd.height = 480
        state = AppState(model=DashboardModel())
        state.ui.screen = rec.Screen.ONBOARDING

        class _Fonts:
            def get(self, _k, _s):
                from PIL import ImageFont
                return ImageFont.load_default()

        with patch("tools.run_epaper_console.render_app"), patch("tools.run_epaper_console.quantize_for_panel") as qp:
            qp.return_value = Image.new("1", (800, 480), 255)
            rec._render_frame(
                epd,
                state,
                _Fonts(),
                {"panel_threshold_onboarding": 140, "panel_gamma_onboarding": 0.88},
                panel_threshold=168,
                panel_muted=150,
                panel_gamma=1.0,
                panel_dither=False,
            )

            kwargs = qp.call_args.kwargs
            self.assertEqual(kwargs.get("threshold"), 140)
            self.assertAlmostEqual(float(kwargs.get("gamma")), 0.88, places=3)

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
