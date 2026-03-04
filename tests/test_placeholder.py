from __future__ import annotations

import unittest

from PIL import Image, ImageDraw, ImageFont

from app.core.state import AppState, DashboardModel, MenuItemId, Screen
from app.ui.placeholder import render_placeholder


class _DummyFonts:
    def get(self, _key, _size):
        return ImageFont.load_default()


class PlaceholderTitleTests(unittest.TestCase):
    def _first_drawn_text(self, state: AppState) -> str:
        img = Image.new("RGB", (800, 480), (255, 255, 255))
        drawn: list[str] = []
        orig = ImageDraw.ImageDraw.text

        def patched(draw_obj, xy, text, *args, **kwargs):
            drawn.append(str(text or ""))
            return orig(draw_obj, xy, text, *args, **kwargs)

        ImageDraw.ImageDraw.text = patched
        try:
            render_placeholder(img, state, _DummyFonts(), {"card": (255, 255, 255), "ink": 0, "muted": 80})
        finally:
            ImageDraw.ImageDraw.text = orig
        return drawn[0] if drawn else ""

    def test_inventory_title_not_overridden_by_stale_active_menu(self) -> None:
        state = AppState(model=DashboardModel())
        state.ui.screen = Screen.INVENTORY
        state.ui.active_menu = MenuItemId.SETTINGS
        self.assertEqual(self._first_drawn_text(state), "INVENTORY")

    def test_reminders_title_not_overridden_by_stale_active_menu(self) -> None:
        state = AppState(model=DashboardModel())
        state.ui.screen = Screen.REMINDERS
        state.ui.active_menu = MenuItemId.MEMO
        self.assertEqual(self._first_drawn_text(state), "REMINDERS")


if __name__ == "__main__":
    unittest.main()
