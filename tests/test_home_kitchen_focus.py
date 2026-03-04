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
        # focus queue: [LEFT_PANEL, INV_HEADER, INV_ITEM, REM_HEADER, REM_ITEM]
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

    def test_kitchen_click_inventory_header_opens_inventory_screen(self) -> None:
        model = DashboardModel()
        model.reminders = [Reminder(rid="r1", title="A", category="fridge")]
        state = AppState(model=model)
        state.ui.screen = Screen.HOME
        state.ui.focused_index = 1

        reduce(state, Click(), theme={"home_variant": "kitchen"})
        self.assertEqual(state.ui.screen, Screen.INVENTORY)

    def test_kitchen_click_reminders_header_opens_reminders_screen(self) -> None:
        model = DashboardModel()
        model.reminders = [
            Reminder(rid="r1", title="A", category="fridge"),
            Reminder(rid="r2", title="B", category="shopping"),
        ]
        state = AppState(model=model)
        state.ui.screen = Screen.HOME
        state.ui.focused_index = 3

        reduce(state, Click(), theme={"home_variant": "kitchen"})
        self.assertEqual(state.ui.screen, Screen.REMINDERS)


if __name__ == "__main__":
    unittest.main()
