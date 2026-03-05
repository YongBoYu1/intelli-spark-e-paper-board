from __future__ import annotations

import unittest

from app.core.reducer import Click, Rotate, reduce
from app.core.kitchen_queue import kitchen_visible_task_indices
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

    def test_kitchen_portrait_click_uses_kitchen_visible_queue(self) -> None:
        model = DashboardModel()
        model.reminders = [
            Reminder(rid="f1", title="Fresh Milk", category="fridge", completed=True),
            Reminder(rid="f2", title="Leftover Pizza", category="fridge", completed=True),
            Reminder(rid="f3", title="Marinated Chicken", category="fridge", completed=True),
            Reminder(rid="s1", title="Doctor Appointment", category="shopping", completed=False),
            Reminder(rid="s2", title="Yoghurt Expires", category="shopping", completed=False),
        ]
        state = AppState(model=model)
        state.ui.screen = Screen.HOME
        state.ui.focused_index = 2
        state.ui.reminders_version = 1

        reduce(state, Click(), theme={"home_variant": "kitchen_portrait"})

        self.assertTrue(state.model.reminders[0].completed)
        self.assertFalse(state.model.reminders[3].completed)
        self.assertTrue(state.model.reminders[4].completed)

    def test_kitchen_portrait_click_holds_focus_until_rotate(self) -> None:
        model = DashboardModel()
        model.reminders = [
            Reminder(rid="s1", title="A", category="shopping", completed=False),
            Reminder(rid="s2", title="B", category="shopping", completed=False),
            Reminder(rid="s3", title="C", category="shopping", completed=False),
        ]
        state = AppState(model=model)
        state.ui.screen = Screen.HOME
        # focus queue: [LEFT, s1, s2, s3]
        state.ui.focused_index = 2

        reduce(state, Click(), theme={"home_variant": "kitchen_portrait"})
        self.assertTrue(state.model.reminders[1].completed)
        self.assertEqual(state.ui.kitchen_focus_rid_override, "s2")

        # Rotate releases hold and resumes normal actionable queue navigation.
        reduce(state, Rotate(+1), theme={"home_variant": "kitchen_portrait"})
        self.assertEqual(state.ui.kitchen_focus_rid_override, "")
        idxs = kitchen_visible_task_indices(state, {"home_variant": "kitchen_portrait"})
        pos = int(state.ui.focused_index) - 1
        self.assertTrue(0 <= pos < len(idxs))
        self.assertEqual(state.model.reminders[idxs[pos]].rid, "s3")

    def test_kitchen_portrait_second_click_before_rotate_hits_held_item(self) -> None:
        model = DashboardModel()
        model.reminders = [
            Reminder(rid="s1", title="A", category="shopping", completed=False),
            Reminder(rid="s2", title="B", category="shopping", completed=False),
            Reminder(rid="s3", title="C", category="shopping", completed=False),
        ]
        state = AppState(model=model)
        state.ui.screen = Screen.HOME
        state.ui.focused_index = 2

        reduce(state, Click(), theme={"home_variant": "kitchen_portrait"})
        self.assertTrue(state.model.reminders[1].completed)
        self.assertEqual(state.ui.kitchen_focus_rid_override, "s2")

        reduce(state, Click(), theme={"home_variant": "kitchen_portrait"})
        self.assertFalse(state.model.reminders[1].completed)
        self.assertEqual(state.ui.kitchen_focus_rid_override, "s2")


if __name__ == "__main__":
    unittest.main()
