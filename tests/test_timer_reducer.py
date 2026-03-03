from __future__ import annotations

import unittest

from app.core.reducer import Back, Click, Rotate, Tick, reduce
from app.core.state import AppState, DashboardModel, MenuItemId, Screen, WidgetMode


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


if __name__ == "__main__":
    unittest.main()
