from __future__ import annotations

import unittest

from app.core.state import AppState, DashboardModel, MenuItemId, Screen
from app.render.refresh_policy import (
    RefreshPolicyRuntime,
    align_rect_for_partial,
    build_ui_snapshot,
    effective_full_refresh_every,
    infer_dirty_rects,
    infer_dirty_rects_with_reasons,
    mode_params,
)


class RefreshPolicyTests(unittest.TestCase):
    def test_mode_params_mapping(self) -> None:
        slow = mode_params("slow")
        balanced = mode_params("balanced")
        fast = mode_params("fast")
        self.assertEqual(slow.min_refresh_gap_ms, 200)
        self.assertEqual(balanced.min_refresh_gap_ms, 120)
        self.assertEqual(fast.min_refresh_gap_ms, 80)
        self.assertEqual(slow.default_full_refresh_every, 5)
        self.assertEqual(balanced.default_full_refresh_every, 10)
        self.assertEqual(fast.default_full_refresh_every, 15)

    def test_align_rect_for_partial_aligns_x_to_8px(self) -> None:
        rect = align_rect_for_partial((13, 10, 119, 50), 800, 480, pad=0)
        self.assertIsNotNone(rect)
        x0, y0, x1, y1 = rect or (0, 0, 0, 0)
        self.assertEqual(x0 % 8, 0)
        self.assertEqual(x1 % 8, 0)
        self.assertGreater(x1, x0)
        self.assertGreater(y1, y0)

    def test_effective_full_refresh_every_timer_uses_override(self) -> None:
        value = effective_full_refresh_every(
            screen=Screen.TIMER,
            mode="balanced",
            ui_full_refresh_every=10,
            timer_full_refresh_every_override=300,
        )
        self.assertEqual(value, 300)

    def test_runtime_full_clean_conditions(self) -> None:
        runtime = RefreshPolicyRuntime()
        runtime.partial_count = 10
        self.assertTrue(runtime.needs_full_clean(100.0, full_refresh_every=10))
        self.assertEqual(runtime.full_clean_reason(100.0, full_refresh_every=10), "partial_budget")

        runtime = RefreshPolicyRuntime()
        runtime.last_full_refresh_ts = 100.0
        self.assertTrue(runtime.needs_full_clean(100.0 + 24 * 60 * 60 + 1, full_refresh_every=99))
        self.assertEqual(runtime.full_clean_reason(100.0 + 24 * 60 * 60 + 1, full_refresh_every=99), "full_age")

    def test_settings_focus_change_generates_dirty_rect(self) -> None:
        prev = AppState(model=DashboardModel())
        prev.ui.screen = Screen.SETTINGS
        prev.ui.settings_focused_index = 0

        curr = AppState(model=DashboardModel())
        curr.ui.screen = Screen.SETTINGS
        curr.ui.settings_focused_index = 1

        rects = infer_dirty_rects(build_ui_snapshot(prev), build_ui_snapshot(curr), 800, 480)
        self.assertGreaterEqual(len(rects), 1)

    def test_menu_focus_change_generates_dirty_rect(self) -> None:
        prev = AppState(model=DashboardModel())
        prev.ui.screen = Screen.MENU
        prev.ui.menu_focused = MenuItemId.LIST

        curr = AppState(model=DashboardModel())
        curr.ui.screen = Screen.MENU
        curr.ui.menu_focused = MenuItemId.CALENDAR

        rects = infer_dirty_rects(build_ui_snapshot(prev), build_ui_snapshot(curr), 800, 480)
        self.assertGreaterEqual(len(rects), 1)

    def test_menu_focus_change_includes_reason(self) -> None:
        prev = AppState(model=DashboardModel())
        prev.ui.screen = Screen.MENU
        prev.ui.menu_focused = MenuItemId.LIST

        curr = AppState(model=DashboardModel())
        curr.ui.screen = Screen.MENU
        curr.ui.menu_focused = MenuItemId.SETTINGS

        _, reasons = infer_dirty_rects_with_reasons(build_ui_snapshot(prev), build_ui_snapshot(curr), 800, 480)
        self.assertIn("menu.focus_move", reasons)

if __name__ == "__main__":
    unittest.main()
