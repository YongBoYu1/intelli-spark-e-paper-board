from __future__ import annotations

import unittest

from app.core.reducer import Back, Click, LongPress, Rotate, RotateButton, Tick, reduce
from app.core.settings_schema import SettingsItem, SETTINGS_ORDER
from app.core.state import AppState, DashboardModel, MemoItem, MenuItemId, Screen, WeatherDay, WidgetMode


class TimerReducerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.state = AppState(model=DashboardModel())

    def test_menu_timer_click_opens_timer_screen(self) -> None:
        self.state.ui.screen = Screen.MENU
        self.state.ui.menu_focused = MenuItemId.TIMER

        reduce(self.state, Click(), theme={})

        self.assertEqual(self.state.ui.screen, Screen.TIMER)
        self.assertEqual(self.state.ui.widget_mode, WidgetMode.TIMER)
        self.assertEqual(self.state.ui.timer_seconds, 300)
        self.assertFalse(self.state.ui.timer_running)
        self.assertEqual(self.state.ui.timer_focused_index, 2)

    def test_timer_rotate_cycles_focus(self) -> None:
        self.state.ui.screen = Screen.TIMER
        self.state.ui.timer_focused_index = 0

        reduce(self.state, Rotate(-1))
        self.assertEqual(self.state.ui.timer_focused_index, 3)

        reduce(self.state, Rotate(+1))
        self.assertEqual(self.state.ui.timer_focused_index, 0)

    def test_timer_click_adjusts_duration(self) -> None:
        self.state.ui.screen = Screen.TIMER
        self.state.ui.widget_mode = WidgetMode.TIMER
        self.state.ui.timer_seconds = 120

        self.state.ui.timer_focused_index = 0
        reduce(self.state, Click(), theme={"timer_step_s": 60})
        self.assertEqual(self.state.ui.timer_seconds, 60)

        reduce(self.state, Click(), theme={"timer_step_s": 60})
        self.assertEqual(self.state.ui.timer_seconds, 0)
        self.assertFalse(self.state.ui.timer_running)

        self.state.ui.timer_focused_index = 1
        reduce(self.state, Click(), theme={"timer_step_s": 60})
        self.assertEqual(self.state.ui.timer_seconds, 60)

    def test_timer_click_start_pause_reset(self) -> None:
        self.state.ui.screen = Screen.TIMER
        self.state.ui.widget_mode = WidgetMode.TIMER
        self.state.ui.timer_seconds = 0

        self.state.ui.timer_focused_index = 2
        reduce(self.state, Click(), theme={"timer_default_s": 180})
        self.assertEqual(self.state.ui.timer_seconds, 180)
        self.assertTrue(self.state.ui.timer_running)

        reduce(self.state, Click(), theme={"timer_default_s": 180})
        self.assertFalse(self.state.ui.timer_running)

        self.state.ui.timer_focused_index = 3
        reduce(self.state, Click())
        self.assertEqual(self.state.ui.timer_seconds, 0)
        self.assertFalse(self.state.ui.timer_running)

    def test_tick_counts_down_and_auto_stops_at_zero(self) -> None:
        self.state.ui.widget_mode = WidgetMode.TIMER
        self.state.ui.timer_seconds = 5
        self.state.ui.timer_running = True
        self.state.ui.timer_last_tick_at = 100.0

        reduce(self.state, Tick(now=103.4))
        self.assertEqual(self.state.ui.timer_seconds, 2)
        self.assertTrue(self.state.ui.timer_running)

        reduce(self.state, Tick(now=106.0))
        self.assertEqual(self.state.ui.timer_seconds, 0)
        self.assertFalse(self.state.ui.timer_running)

    def test_back_from_timer_returns_home(self) -> None:
        self.state.ui.screen = Screen.TIMER

        reduce(self.state, Back())

        self.assertEqual(self.state.ui.screen, Screen.HOME)

    def test_long_press_on_home_opens_menu(self) -> None:
        self.state.ui.screen = Screen.HOME

        reduce(self.state, LongPress())

        self.assertEqual(self.state.ui.screen, Screen.HOME)
        self.assertTrue(self.state.ui.menu_overlay_active)

    def test_long_press_on_home_when_overlay_active_closes_menu(self) -> None:
        self.state.ui.screen = Screen.HOME
        self.state.ui.menu_overlay_active = True

        reduce(self.state, LongPress())

        self.assertEqual(self.state.ui.screen, Screen.HOME)
        self.assertFalse(self.state.ui.menu_overlay_active)

    def test_long_press_on_detail_returns_home(self) -> None:
        self.state.ui.screen = Screen.WEATHER

        reduce(self.state, LongPress())

        self.assertEqual(self.state.ui.screen, Screen.HOME)
        self.assertFalse(self.state.ui.menu_overlay_active)

    def test_rotate_on_home_overlay_moves_menu_focus(self) -> None:
        self.state.ui.screen = Screen.HOME
        self.state.ui.menu_overlay_active = True
        self.state.ui.menu_focused = MenuItemId.LIST
        self.state.ui.focused_index = 3

        reduce(self.state, Rotate(+1))

        self.assertEqual(self.state.ui.menu_focused, MenuItemId.TIMER)
        self.assertEqual(self.state.ui.focused_index, 3)

    def test_rotate_on_weather_is_disabled(self) -> None:
        self.state.ui.screen = Screen.WEATHER
        self.state.ui.weather_day_index = 1
        self.state.model.weather = [
            WeatherDay(dow="MON", icon="sun", hi=20, lo=10),
            WeatherDay(dow="TUE", icon="cloud", hi=21, lo=11),
            WeatherDay(dow="WED", icon="rain", hi=22, lo=12),
        ]

        reduce(self.state, Rotate(+1))
        self.assertEqual(self.state.ui.weather_day_index, 1)

        reduce(self.state, Rotate(-1))
        self.assertEqual(self.state.ui.weather_day_index, 1)

    def test_tick_pauses_home_memo_rotation_while_voice_active(self) -> None:
        self.state.ui.screen = Screen.HOME
        self.state.ui.focused_index = 2
        self.state.ui.idle = False
        self.state.ui.voice_active = True
        self.state.ui.memo_last_rotated_at = 100.0
        self.state.ui.memo_index = 0
        self.state.model.memos = [
            MemoItem(mid="m1", text="A", author="Mom", timestamp=1, is_new=False),
            MemoItem(mid="m2", text="B", author="Dad", timestamp=2, is_new=False),
        ]

        reduce(self.state, Tick(now=112.0), theme={"home_variant": "kitchen", "memo_rotate_s": 8})

        self.assertEqual(self.state.ui.memo_index, 0)
        self.assertEqual(self.state.ui.memo_last_rotated_at, 112.0)

    def test_tick_updates_clock_minute_bucket(self) -> None:
        self.state.ui.clock_minute_bucket = 100

        reduce(self.state, Tick(now=(101 * 60.0) + 1.0), theme={})

        self.assertEqual(self.state.ui.clock_minute_bucket, 101)

    def test_tick_pauses_home_memo_rotation_during_interaction_window(self) -> None:
        self.state.ui.screen = Screen.HOME
        self.state.ui.focused_index = 2
        self.state.ui.idle = False
        self.state.ui.voice_active = False
        self.state.ui.menu_overlay_active = False
        self.state.ui.memo_last_rotated_at = 100.0
        self.state.ui.last_interaction_at = 111.2
        self.state.ui.memo_index = 0
        self.state.model.memos = [
            MemoItem(mid="m1", text="A", author="Mom", timestamp=1, is_new=False),
            MemoItem(mid="m2", text="B", author="Dad", timestamp=2, is_new=False),
        ]

        reduce(
            self.state,
            Tick(now=112.0),
            theme={"home_variant": "kitchen", "memo_rotate_s": 8, "memo_rotate_pause_after_interaction_s": 2.5},
        )

        self.assertEqual(self.state.ui.memo_index, 0)
        self.assertEqual(self.state.ui.memo_last_rotated_at, 112.0)

    def test_rotate_button_cycles_all_right_angles(self) -> None:
        self.state.ui.rotation_deg = 0
        reduce(self.state, RotateButton())
        self.assertEqual(self.state.ui.rotation_deg, 90)

        reduce(self.state, RotateButton())
        self.assertEqual(self.state.ui.rotation_deg, 180)

        reduce(self.state, RotateButton())
        self.assertEqual(self.state.ui.rotation_deg, 270)

        reduce(self.state, RotateButton())
        self.assertEqual(self.state.ui.rotation_deg, 0)

    def test_settings_rotation_click_cycles_all_right_angles(self) -> None:
        self.state.ui.screen = Screen.SETTINGS
        self.state.ui.settings_focused_index = SETTINGS_ORDER.index(SettingsItem.ROTATION)
        self.state.ui.rotation_deg = 0

        reduce(self.state, Click(), theme={})
        self.assertEqual(self.state.ui.rotation_deg, 90)

        reduce(self.state, Click(), theme={})
        self.assertEqual(self.state.ui.rotation_deg, 180)

    def test_settings_rotate_cycles_only_real_rows(self) -> None:
        self.state.ui.screen = Screen.SETTINGS
        self.state.ui.settings_focused_index = 0

        reduce(self.state, Rotate(-1))

        self.assertGreaterEqual(self.state.ui.settings_focused_index, 0)

    def test_settings_click_on_negative_focus_does_not_force_home(self) -> None:
        self.state.ui.screen = Screen.SETTINGS
        self.state.ui.settings_focused_index = -1

        reduce(self.state, Click())

        self.assertEqual(self.state.ui.screen, Screen.SETTINGS)
        self.assertGreaterEqual(self.state.ui.settings_focused_index, 0)

    def test_tick_reaching_zero_starts_timer_done_alert(self) -> None:
        self.state.ui.screen = Screen.TIMER
        self.state.ui.widget_mode = WidgetMode.TIMER
        self.state.ui.timer_running = True
        self.state.ui.timer_seconds = 2
        self.state.ui.timer_target_seconds = 300
        self.state.ui.timer_last_tick_at = 100.0

        reduce(self.state, Tick(now=102.1), theme={"timer_alert_show_s": 6.0, "timer_alert_blink_period_s": 0.5})

        self.assertEqual(self.state.ui.timer_seconds, 0)
        self.assertFalse(self.state.ui.timer_running)
        self.assertTrue(self.state.ui.timer_alert_active)
        self.assertTrue(self.state.ui.timer_alert_blink_on)
        self.assertEqual(self.state.ui.timer_last_completed_seconds, 300)

    def test_tick_timer_done_alert_blinks_and_expires(self) -> None:
        self.state.ui.screen = Screen.TIMER
        self.state.ui.widget_mode = WidgetMode.TIMER
        self.state.ui.timer_alert_active = True
        self.state.ui.timer_alert_blink_on = True
        self.state.ui.timer_alert_started_at = 200.0
        self.state.ui.timer_alert_until = 202.0
        self.state.ui.timer_last_completed_seconds = 180

        reduce(self.state, Tick(now=200.6), theme={"timer_alert_blink_period_s": 0.5})
        self.assertFalse(self.state.ui.timer_alert_blink_on)
        self.assertTrue(self.state.ui.timer_alert_active)

        reduce(self.state, Tick(now=201.1), theme={"timer_alert_blink_period_s": 0.5})
        self.assertTrue(self.state.ui.timer_alert_blink_on)
        self.assertTrue(self.state.ui.timer_alert_active)

        reduce(self.state, Tick(now=202.2), theme={"timer_alert_show_s": 2.0, "timer_alert_blink_period_s": 0.5})
        self.assertFalse(self.state.ui.timer_alert_active)


if __name__ == "__main__":
    unittest.main()
