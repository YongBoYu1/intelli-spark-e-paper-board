from __future__ import annotations

import datetime
import unittest
from unittest.mock import patch

from app.core.reducer import Back, Click, LongPress, Rotate, RotateButton, Tick, reduce
from app.core.settings_schema import SettingsItem, SETTINGS_ORDER
from app.core.state import AppState, CalendarEvent, DashboardModel, MemoItem, MenuItemId, Reminder, Screen, WeatherDay, WidgetMode


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

    def test_menu_memo_click_opens_memo_screen(self) -> None:
        self.state.ui.screen = Screen.MENU
        self.state.ui.menu_focused = MenuItemId.MEMO
        self.state.ui.memo_expanded = True
        self.state.model.memos = [
            MemoItem(mid="m1", text="A", author="Mom", timestamp=1, is_new=True),
            MemoItem(mid="m2", text="B", author="Dad", timestamp=2, is_new=False),
        ]

        reduce(self.state, Click(), theme={})

        self.assertEqual(self.state.ui.screen, Screen.MEMO)
        self.assertEqual(self.state.ui.memo_index, 0)
        self.assertFalse(self.state.ui.memo_expanded)

    def test_menu_list_click_opens_unified_list_screen(self) -> None:
        self.state.ui.screen = Screen.MENU
        self.state.ui.menu_focused = MenuItemId.LIST
        self.state.model.reminders = [
            Reminder(rid="f1", title="Milk", category="fridge"),
            Reminder(rid="r1", title="Buy Eggs", category="shopping"),
        ]

        reduce(self.state, Click(), theme={})

        self.assertEqual(self.state.ui.screen, Screen.REMINDERS)
        self.assertEqual(self.state.ui.list_focused_index, 1)

    def test_rotate_on_unified_list_moves_focus(self) -> None:
        self.state.ui.screen = Screen.REMINDERS
        self.state.model.reminders = [
            Reminder(rid="f1", title="Milk", category="fridge"),
            Reminder(rid="r1", title="Buy Eggs", category="shopping"),
            Reminder(rid="r2", title="Pay Rent", category="general"),
        ]
        self.state.ui.list_focused_index = 1

        reduce(self.state, Rotate(+1), theme={})
        self.assertEqual(self.state.ui.list_focused_index, 2)

        reduce(self.state, Rotate(+1), theme={})
        self.assertEqual(self.state.ui.list_focused_index, 2)

    def test_click_on_unified_list_toggles_selected_item(self) -> None:
        self.state.ui.screen = Screen.REMINDERS
        self.state.model.reminders = [
            Reminder(rid="f1", title="Milk", category="fridge", completed=False),
            Reminder(rid="r1", title="Buy Eggs", category="shopping", completed=False),
        ]
        # Focus reminder section first item (order: inventory then reminders).
        self.state.ui.list_focused_index = 1

        reduce(self.state, Click(), theme={})
        self.assertTrue(self.state.model.reminders[1].completed)

    def test_rotate_on_memo_cycles_index_and_collapses(self) -> None:
        self.state.ui.screen = Screen.MEMO
        self.state.ui.memo_index = 0
        self.state.ui.memo_expanded = True
        self.state.model.memos = [
            MemoItem(mid="m1", text="A", author="Mom", timestamp=1, is_new=True),
            MemoItem(mid="m2", text="B", author="Dad", timestamp=2, is_new=False),
        ]

        reduce(self.state, Rotate(-1), theme={})
        self.assertEqual(self.state.ui.memo_index, 1)
        self.assertFalse(self.state.ui.memo_expanded)

        reduce(self.state, Rotate(+1), theme={})
        self.assertEqual(self.state.ui.memo_index, 0)

    def test_click_on_memo_toggles_expand_and_clears_new_flag(self) -> None:
        self.state.ui.screen = Screen.MEMO
        self.state.ui.memo_index = 0
        self.state.ui.memo_expanded = False
        self.state.model.memos = [
            MemoItem(mid="m1", text="A", author="Mom", timestamp=1, is_new=True),
            MemoItem(mid="m2", text="B", author="Dad", timestamp=2, is_new=False),
        ]

        reduce(self.state, Click(), theme={})
        self.assertTrue(self.state.ui.memo_expanded)
        self.assertFalse(self.state.model.memos[0].is_new)

        reduce(self.state, Click(), theme={})
        self.assertFalse(self.state.ui.memo_expanded)

    def test_click_on_weather_refreshes_latest_data(self) -> None:
        self.state.ui.screen = Screen.WEATHER
        self.state.model.location = "Toronto"
        self.state.model.weather = [
            WeatherDay(dow="MON", icon="cloud", hi=6, lo=0, humidity=80),
            WeatherDay(dow="TUE", icon="cloud", hi=5, lo=-1, humidity=75),
        ]
        self.state.ui.weather_day_index = 1

        refreshed = [
            {"dow": "MON", "icon": "rain", "hi": 7, "lo": 1, "humidity": 90, "feels_like": 3.5, "wind_kmh": 28, "uv_index": 1},
        ]
        with patch("app.core.reducer.resolve_weather_data", return_value=("Toronto", refreshed)) as mocked:
            reduce(self.state, Click(), theme={})

        mocked.assert_called_once()
        self.assertEqual(len(self.state.model.weather), 1)
        self.assertEqual(self.state.model.weather[0].icon, "rain")
        self.assertEqual(self.state.model.weather[0].hi, 7)
        self.assertEqual(self.state.model.weather[0].lo, 1)
        self.assertEqual(self.state.ui.weather_day_index, 0)
        self.assertEqual(self.state.ui.sync_state, "ok")
        self.assertGreater(self.state.ui.last_sync_at, 0.0)

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

    def test_calendar_agenda_rotation_uses_selected_date_items_only(self) -> None:
        today = datetime.date.today()
        tomorrow = today + datetime.timedelta(days=1)
        self.state.ui.screen = Screen.CALENDAR
        self.state.ui.calendar_mode = "agenda"
        self.state.ui.calendar_offset_days = 1
        self.state.ui.calendar_selected_index = 0
        self.state.model.calendar = [
            CalendarEvent(eid="e0", title="Today event", when="09:00", date_iso=today.isoformat()),
        ]
        self.state.model.reminders = [
            Reminder(rid="r0", title="Today task", right=today.isoformat(), completed=False, category="general"),
        ]

        reduce(self.state, Rotate(+1), theme={})

        # Offset=+1 has no items; selection must stay clamped at 0.
        self.assertEqual(self.state.ui.calendar_selected_index, 0)

    def test_calendar_agenda_click_toggles_task_for_selected_date(self) -> None:
        today = datetime.date.today()
        tomorrow = today + datetime.timedelta(days=1)
        self.state.ui.screen = Screen.CALENDAR
        self.state.ui.calendar_mode = "agenda"
        self.state.ui.calendar_offset_days = 1
        self.state.ui.calendar_selected_index = 0
        self.state.model.calendar = []
        self.state.model.reminders = [
            Reminder(rid="r0", title="Today task", right=today.isoformat(), completed=False, category="general"),
            Reminder(rid="r1", title="Tomorrow task", right=tomorrow.isoformat(), completed=False, category="general"),
        ]

        reduce(self.state, Click(), theme={})

        self.assertFalse(self.state.model.reminders[0].completed)
        self.assertTrue(self.state.model.reminders[1].completed)

    def test_calendar_agenda_click_without_reminder_returns_date_mode(self) -> None:
        today = datetime.date.today()
        self.state.ui.screen = Screen.CALENDAR
        self.state.ui.calendar_mode = "agenda"
        self.state.ui.calendar_offset_days = 0
        self.state.ui.calendar_selected_index = 0
        self.state.model.calendar = [
            CalendarEvent(eid="e0", title="Event only", when="10:00", date_iso=today.isoformat()),
        ]
        self.state.model.reminders = []

        reduce(self.state, Click(), theme={})

        self.assertEqual(self.state.ui.calendar_mode, "date")
        self.assertEqual(self.state.ui.calendar_selected_index, 0)

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

    def test_tick_prunes_expired_memos(self) -> None:
        self.state.model.memos = [
            MemoItem(mid="m1", text="fresh", author="Mom", timestamp=100.0, expires_at=120.0),
            MemoItem(mid="m2", text="expired", author="Dad", timestamp=90.0, expires_at=99.0),
        ]
        self.state.ui.memo_index = 1

        reduce(self.state, Tick(now=100.0), theme={})

        self.assertEqual(len(self.state.model.memos), 1)
        self.assertEqual(self.state.model.memos[0].mid, "m1")
        self.assertEqual(self.state.ui.memo_index, 0)

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
