from __future__ import annotations

import unittest

from app.core.reducer import Rotate, reduce
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
        # focus queue: [LEFT_PANEL, TASK_0, TASK_1]
        state.ui.focused_index = 2

        reduce(state, Rotate(+1), theme={"home_variant": "kitchen"})
        self.assertEqual(state.ui.focused_index, 2)

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


if __name__ == "__main__":
    unittest.main()
