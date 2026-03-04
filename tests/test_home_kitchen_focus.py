from __future__ import annotations

import unittest

from app.core.reducer import Click, Rotate, reduce
from app.core.state import AppState, DashboardModel, Reminder, Screen


class HomeKitchenFocusTests(unittest.TestCase):
    def test_kitchen_focus_clamps_at_bottom_instead_of_wrapping(self) -> None:
        model = DashboardModel()
        model.reminders = [
            Reminder(rid="r1", title="A", category="fridge"),
            Reminder(rid="r2", title="B", category="shopping"),
        ]
        state = AppState(model=model)
        state.ui.screen = Screen.HOME
        # focus queue: [DATE, TIME, WEATHER, TASK_0, TASK_1]
        state.ui.focused_index = 4

        reduce(state, Rotate(+1), theme={"home_variant": "kitchen"})
        self.assertEqual(state.ui.focused_index, 4)

    def test_kitchen_focus_clamps_at_top_instead_of_wrapping(self) -> None:
        model = DashboardModel()
        model.reminders = [
            Reminder(rid="r1", title="A", category="fridge"),
            Reminder(rid="r2", title="B", category="shopping"),
        ]
        state = AppState(model=model)
        state.ui.screen = Screen.HOME
        state.ui.focused_index = 0

        reduce(state, Rotate(-1), theme={"home_variant": "kitchen"})
        self.assertEqual(state.ui.focused_index, 0)

    def test_click_time_focus_opens_timer_screen(self) -> None:
        state = AppState(model=DashboardModel())
        state.ui.screen = Screen.HOME
        state.ui.focused_index = 1  # TIME

        reduce(state, Click(), theme={"home_variant": "kitchen"})
        self.assertEqual(state.ui.screen, Screen.TIMER)

    def test_click_date_focus_opens_calendar_screen(self) -> None:
        state = AppState(model=DashboardModel())
        state.ui.screen = Screen.HOME
        state.ui.focused_index = 0  # DATE

        reduce(state, Click(), theme={"home_variant": "kitchen"})
        self.assertEqual(state.ui.screen, Screen.CALENDAR)


if __name__ == "__main__":
    unittest.main()
