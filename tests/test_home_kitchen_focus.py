from __future__ import annotations

import os
import time
import unittest

from PIL import Image, ImageDraw

from app.core.kitchen_queue import kitchen_visible_task_indices
from app.core.reducer import Click, Rotate, reduce
from app.core.state import AppState, DashboardModel, MemoItem, Reminder, Screen, WidgetMode
from app.render.panel import build_panel_theme
from app.shared.fonts import FontBook
from app.ui.app import render_app


def _test_font_book() -> FontBook:
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    font_dir = os.path.join(repo_root, "assets", "fonts")
    return FontBook(
        {
            "inter_regular": os.path.join(font_dir, "Inter-Regular.ttf"),
            "inter_medium": os.path.join(font_dir, "Inter-Medium.ttf"),
            "inter_semibold": os.path.join(font_dir, "Inter-SemiBold.ttf"),
            "inter_bold": os.path.join(font_dir, "Inter-Bold.ttf"),
            "inter_black": os.path.join(font_dir, "Inter-Black.ttf"),
            "jet_bold": os.path.join(font_dir, "JetBrainsMono-Bold.ttf"),
            "jet_extrabold": os.path.join(font_dir, "JetBrainsMono-ExtraBold.ttf"),
            "playfair_regular": os.path.join(font_dir, "PlayfairDisplay-Regular.ttf"),
            "playfair_italic": os.path.join(font_dir, "PlayfairDisplay-Italic.ttf"),
            "playfair_bold": os.path.join(font_dir, "PlayfairDisplay-Bold.ttf"),
        },
        default_key="inter_regular",
    )


def _rects_intersect(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> bool:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    return not (ax1 <= bx0 or bx1 <= ax0 or ay1 <= by0 or by1 <= ay0)


class HomeKitchenFocusTests(unittest.TestCase):
    def test_kitchen_focus_clamps_at_bottom_instead_of_wrapping(self) -> None:
        model = DashboardModel()
        model.reminders = [
            Reminder(rid="r1", title="A", category="fridge"),
            Reminder(rid="r2", title="B", category="shopping"),
        ]
        state = AppState(model=model)
        state.ui.screen = Screen.HOME
        # focus queue: [LEFT_PANEL, INV_ITEM, REM_ITEM]
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

    def test_kitchen_landscape_click_inventory_row_toggles_item(self) -> None:
        model = DashboardModel()
        model.reminders = [Reminder(rid="r1", title="A", category="fridge")]
        state = AppState(model=model)
        state.ui.screen = Screen.HOME
        state.ui.focused_index = 1

        reduce(state, Click(), theme={"home_variant": "kitchen"})
        self.assertTrue(state.model.reminders[0].completed)
        self.assertEqual(state.ui.screen, Screen.HOME)

    def test_kitchen_landscape_click_reminder_row_toggles_item(self) -> None:
        model = DashboardModel()
        model.reminders = [
            Reminder(rid="r1", title="A", category="fridge"),
            Reminder(rid="r2", title="B", category="shopping"),
        ]
        state = AppState(model=model)
        state.ui.screen = Screen.HOME
        state.ui.focused_index = 2

        reduce(state, Click(), theme={"home_variant": "kitchen"})
        self.assertTrue(state.model.reminders[1].completed)
        self.assertEqual(state.ui.screen, Screen.HOME)

    def test_kitchen_portrait_theme_uses_landscape_row_click_routing_at_zero_deg(self) -> None:
        model = DashboardModel()
        model.reminders = [
            Reminder(rid="r1", title="A", category="fridge"),
            Reminder(rid="r2", title="B", category="shopping"),
        ]
        state = AppState(model=model)
        state.ui.screen = Screen.HOME
        state.ui.rotation_deg = 0
        state.ui.focused_index = 1

        reduce(state, Click(), theme={"home_variant": "kitchen_portrait"})
        self.assertTrue(state.model.reminders[0].completed)
        self.assertEqual(state.ui.screen, Screen.HOME)

    def test_kitchen_click_left_panel_opens_weather_even_with_timer_widget(self) -> None:
        state = AppState(model=DashboardModel())
        state.ui.screen = Screen.HOME
        state.ui.focused_index = 0
        state.ui.widget_mode = WidgetMode.TIMER
        state.ui.timer_running = False

        reduce(state, Click(), theme={"home_variant": "kitchen"})

        self.assertEqual(state.ui.screen, Screen.WEATHER)
        self.assertFalse(state.ui.timer_running)

    def test_kitchen_click_left_panel_can_toggle_timer_when_enabled_by_theme(self) -> None:
        state = AppState(model=DashboardModel())
        state.ui.screen = Screen.HOME
        state.ui.focused_index = 0
        state.ui.widget_mode = WidgetMode.TIMER
        state.ui.timer_running = False

        reduce(
            state,
            Click(),
            theme={"home_variant": "kitchen", "kitchen_left_click_action": "timer_toggle"},
        )

        self.assertEqual(state.ui.screen, Screen.HOME)
        self.assertTrue(state.ui.timer_running)

    def test_kitchen_portrait_left_focus_click_opens_weather(self) -> None:
        state = AppState(model=DashboardModel())
        state.ui.screen = Screen.HOME
        state.ui.rotation_deg = 90
        state.ui.focused_index = 0

        reduce(state, Click(), theme={"home_variant": "kitchen_portrait"})

        self.assertEqual(state.ui.screen, Screen.WEATHER)
        self.assertEqual(state.ui.weather_day_index, 0)

    def test_kitchen_portrait_click_can_restore_visible_completed_inventory_row(self) -> None:
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
        state.ui.rotation_deg = 90
        state.ui.focused_index = 2
        state.ui.reminders_version = 1

        reduce(state, Click(), theme={"home_variant": "kitchen_portrait"})

        self.assertFalse(state.model.reminders[1].completed)
        self.assertFalse(state.model.reminders[3].completed)
        self.assertFalse(state.model.reminders[4].completed)
        self.assertEqual(state.ui.kitchen_focus_rid_override, "f2")

    def test_kitchen_landscape_completed_item_can_be_undone_after_rotate(self) -> None:
        model = DashboardModel()
        model.reminders = [
            Reminder(rid="f1", title="Milk", category="fridge", completed=False),
            Reminder(rid="f2", title="Eggs", category="fridge", completed=False),
        ]
        state = AppState(model=model)
        state.ui.screen = Screen.HOME
        state.ui.focused_index = 1

        reduce(state, Click(), theme={"home_variant": "kitchen"})
        self.assertTrue(state.model.reminders[0].completed)
        self.assertEqual(state.ui.focused_index, 1)

        reduce(state, Rotate(+1), theme={"home_variant": "kitchen"})
        self.assertEqual(state.ui.focused_index, 2)

        reduce(state, Click(), theme={"home_variant": "kitchen"})
        self.assertFalse(state.model.reminders[0].completed)

    def test_kitchen_portrait_click_holds_focus_until_rotate(self) -> None:
        model = DashboardModel()
        model.reminders = [
            Reminder(rid="s1", title="A", category="shopping", completed=False),
            Reminder(rid="s2", title="B", category="shopping", completed=False),
            Reminder(rid="s3", title="C", category="shopping", completed=False),
        ]
        state = AppState(model=model)
        state.ui.screen = Screen.HOME
        state.ui.rotation_deg = 90
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
        state.ui.rotation_deg = 90
        state.ui.focused_index = 2

        reduce(state, Click(), theme={"home_variant": "kitchen_portrait"})
        self.assertTrue(state.model.reminders[1].completed)
        self.assertEqual(state.ui.kitchen_focus_rid_override, "s2")

        reduce(state, Click(), theme={"home_variant": "kitchen_portrait"})
        self.assertFalse(state.model.reminders[1].completed)
        self.assertEqual(state.ui.kitchen_focus_rid_override, "s2")

    def test_kitchen_portrait_reverse_rotate_after_click_only_releases_hold(self) -> None:
        model = DashboardModel()
        model.reminders = [
            Reminder(rid="s1", title="A", category="shopping", completed=False),
            Reminder(rid="s2", title="B", category="shopping", completed=False),
            Reminder(rid="s3", title="C", category="shopping", completed=False),
        ]
        state = AppState(model=model)
        state.ui.screen = Screen.HOME
        state.ui.rotation_deg = 90
        state.ui.focused_index = 2

        reduce(state, Click(), theme={"home_variant": "kitchen_portrait"})
        self.assertEqual(state.ui.kitchen_focus_rid_override, "s2")

        reduce(state, Rotate(-1), theme={"home_variant": "kitchen_portrait"})
        self.assertEqual(state.ui.kitchen_focus_rid_override, "")
        self.assertEqual(state.ui.focused_index, 2)

        idxs = kitchen_visible_task_indices(state, {"home_variant": "kitchen_portrait"})
        pos = int(state.ui.focused_index) - 1
        self.assertTrue(0 <= pos < len(idxs))
        self.assertEqual(state.model.reminders[idxs[pos]].rid, "s3")

    def test_kitchen_portrait_rotate_clamps_to_actionable_rows(self) -> None:
        model = DashboardModel()
        model.reminders = [
            Reminder(rid="s1", title="A", category="shopping", completed=False),
            Reminder(rid="s2", title="B", category="shopping", completed=False),
        ]
        state = AppState(model=model)
        state.ui.screen = Screen.HOME
        state.ui.rotation_deg = 90
        state.ui.focused_index = 0

        for _ in range(6):
            reduce(state, Rotate(+1), theme={"home_variant": "kitchen_portrait"})

        self.assertEqual(state.ui.focused_index, 2)

        reduce(state, Click(), theme={"home_variant": "kitchen_portrait"})
        self.assertFalse(state.model.reminders[0].completed)
        self.assertTrue(state.model.reminders[1].completed)

    def test_kitchen_portrait_queue_defaults_allow_four_inventory_rows(self) -> None:
        model = DashboardModel()
        model.reminders = [
            Reminder(rid="f1", title="Milk", category="fridge", completed=False),
            Reminder(rid="f2", title="Eggs", category="fridge", completed=False),
            Reminder(rid="f3", title="Sauce", category="fridge", completed=False),
            Reminder(rid="f4", title="Soup", category="fridge", completed=False),
            Reminder(rid="s1", title="Bread", category="shopping", completed=False),
        ]
        state = AppState(model=model)
        state.ui.screen = Screen.HOME
        state.ui.rotation_deg = 90

        idxs = kitchen_visible_task_indices(state, {"home_variant": "kitchen_portrait"})
        self.assertEqual([state.model.reminders[i].rid for i in idxs[:5]], ["f1", "f2", "f3", "f4", "s1"])

    def test_large_font_posted_timestamp_does_not_overlap_voice_lane(self) -> None:
        model = DashboardModel()
        model.memos = [MemoItem(mid="m1", text="Dinner is in the oven.", author="Mom", timestamp=time.time())]
        model.reminders = [Reminder(rid="r1", title="Milk", category="fridge")]
        state = AppState(model=model)
        state.ui.screen = Screen.HOME
        state.ui.font_size = "large"
        state.ui.voice_active = False
        state.ui.voice_phase = "idle"
        state.ui.voice_confirm_tool = ""
        state.ui.voice_confirm_due_at = 0.0

        theme = build_panel_theme({"home_variant": "kitchen", "voice_zone_show_idle_home": True})
        fonts = _test_font_book()
        image = Image.new("RGB", (800, 480), (255, 255, 255))

        posted_bbox: tuple[int, int, int, int] | None = None
        voice_bbox: tuple[int, int, int, int] | None = None
        orig_text = ImageDraw.ImageDraw.text

        def patched_text(draw_obj, xy, text, *args, **kwargs):
            nonlocal posted_bbox, voice_bbox
            label = str(text or "")
            try:
                bbox = draw_obj.textbbox(xy, label, font=kwargs.get("font"))
            except Exception:
                bbox = None
            if bbox is not None and label.startswith("- "):
                posted_bbox = bbox
            if bbox is not None and label == "Hold to talk":
                voice_bbox = bbox
            return orig_text(draw_obj, xy, text, *args, **kwargs)

        ImageDraw.ImageDraw.text = patched_text
        try:
            render_app(image, state, fonts, theme)
        finally:
            ImageDraw.ImageDraw.text = orig_text

        self.assertIsNotNone(posted_bbox)
        self.assertIsNotNone(voice_bbox)
        assert posted_bbox is not None and voice_bbox is not None
        self.assertFalse(_rects_intersect(posted_bbox, voice_bbox))
        self.assertLess(posted_bbox[3], voice_bbox[1])


if __name__ == "__main__":
    unittest.main()
