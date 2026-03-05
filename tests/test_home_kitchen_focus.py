from __future__ import annotations

import os
import time
import unittest

from PIL import Image, ImageDraw

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
