from __future__ import annotations

import unittest
from unittest.mock import patch

from PIL import Image, ImageFont

from app.core.state import AppState, DashboardModel
from app.ui.app import render_app


class _DummyFonts:
    def get(self, _key, _size):
        return ImageFont.load_default()


class AppHomeVariantRotationTests(unittest.TestCase):
    def _base_state(self, rotation_deg: int) -> AppState:
        state = AppState(model=DashboardModel())
        state.ui.rotation_deg = int(rotation_deg)
        return state

    def test_kitchen_portrait_falls_back_to_kitchen_at_zero_degree(self) -> None:
        image = Image.new("RGB", (800, 480), (255, 255, 255))
        state = self._base_state(0)
        theme = {"home_variant": "kitchen_portrait"}

        with (
            patch("app.ui.app.render_home_kitchen") as render_kitchen,
            patch("app.ui.app.render_home_kitchen_portrait") as render_portrait,
            patch("app.ui.app._draw_voice_overlay"),
        ):
            render_app(image, state, _DummyFonts(), theme)

        self.assertTrue(render_kitchen.called)
        self.assertFalse(render_portrait.called)

    def test_kitchen_portrait_kept_for_ninety_degree(self) -> None:
        image = Image.new("RGB", (800, 480), (255, 255, 255))
        state = self._base_state(90)
        theme = {"home_variant": "kitchen_portrait"}

        with (
            patch("app.ui.app.render_home_kitchen") as render_kitchen,
            patch("app.ui.app.render_home_kitchen_portrait") as render_portrait,
            patch("app.ui.app._draw_voice_overlay"),
        ):
            render_app(image, state, _DummyFonts(), theme)

        self.assertFalse(render_kitchen.called)
        self.assertTrue(render_portrait.called)

    def test_kitchen_portrait_renders_navigation_overlay_on_home(self) -> None:
        image = Image.new("RGB", (800, 480), (255, 255, 255))
        state = self._base_state(90)
        state.ui.menu_overlay_active = True
        theme = {"home_variant": "kitchen_portrait"}

        with (
            patch("app.ui.app.render_home_kitchen_portrait") as render_portrait,
            patch("app.ui.app.render_menu_overlay_home") as render_overlay,
            patch("app.ui.app._draw_voice_overlay"),
        ):
            render_app(image, state, _DummyFonts(), theme)

        self.assertTrue(render_portrait.called)
        self.assertTrue(render_overlay.called)


if __name__ == "__main__":
    unittest.main()
