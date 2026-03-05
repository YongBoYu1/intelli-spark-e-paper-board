from __future__ import annotations

import unittest

from app.core.state import AppState, DashboardModel, MemoItem, MenuItemId, Reminder, Screen
from app.render.refresh_policy import (
    RefreshPolicyRuntime,
    align_rect_for_partial,
    build_ui_snapshot,
    effective_full_refresh_every,
    infer_dirty_rects,
    infer_dirty_rects_with_reasons,
    merge_rects,
    rect_area_ratio,
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

    def test_runtime_full_clean_budget_can_be_disabled(self) -> None:
        runtime = RefreshPolicyRuntime()
        runtime.partial_count = 999
        self.assertEqual(runtime.full_clean_reason(100.0, full_refresh_every=0), "")
        self.assertFalse(runtime.needs_full_clean(100.0, full_refresh_every=0))

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

    def test_home_focus_move_prefers_row_dirty_rect(self) -> None:
        prev = AppState(model=DashboardModel())
        prev.ui.screen = Screen.HOME
        prev.ui.focused_index = 1

        curr = AppState(model=DashboardModel())
        curr.ui.screen = Screen.HOME
        curr.ui.focused_index = 2

        rects, reasons = infer_dirty_rects_with_reasons(build_ui_snapshot(prev), build_ui_snapshot(curr), 800, 480)
        self.assertIn("home.focus_move_row", reasons)
        merged = merge_rects(rects, 800, 480)
        self.assertIsNotNone(merged)
        ratio = rect_area_ratio(merged, 800, 480)
        self.assertLess(ratio, 0.20)

    def test_home_click_toggle_prefers_row_dirty_rect(self) -> None:
        model_prev = DashboardModel()
        model_prev.reminders = []
        for i in range(5):
            model_prev.reminders.append(
                Reminder(rid=f"r{i}", title=f"Task {i}", right="", completed=False, category="fridge")
            )
        prev = AppState(model=model_prev)
        prev.ui.screen = Screen.HOME
        prev.ui.focused_index = 2

        model_curr = DashboardModel()
        model_curr.reminders = []
        for i in range(5):
            model_curr.reminders.append(
                Reminder(
                    rid=f"r{i}",
                    title=f"Task {i}",
                    right="",
                    completed=(i == 1),
                    category="fridge",
                )
            )
        curr = AppState(model=model_curr)
        curr.ui.screen = Screen.HOME
        curr.ui.focused_index = 2

        rects, reasons = infer_dirty_rects_with_reasons(build_ui_snapshot(prev), build_ui_snapshot(curr), 800, 480)
        self.assertIn("home.reminder_row_update", reasons)
        merged = merge_rects(rects, 800, 480)
        self.assertIsNotNone(merged)
        ratio = rect_area_ratio(merged, 800, 480)
        self.assertLess(ratio, 0.20)

    def test_home_family_board_update_prefers_partial_sized_rect(self) -> None:
        model = DashboardModel()
        model.memos = []
        for i in range(3):
            model.memos.append(
                MemoItem(
                    mid=f"m{i}",
                    text=f"memo {i}",
                    author="Mom" if i == 0 else "Dad",
                    timestamp=1000 + i,
                    is_new=False,
                )
            )
        prev = AppState(model=model)
        prev.ui.screen = Screen.HOME
        prev.ui.memo_index = 0

        curr = AppState(model=model)
        curr.ui.screen = Screen.HOME
        curr.ui.memo_index = 1

        rects, reasons = infer_dirty_rects_with_reasons(build_ui_snapshot(prev), build_ui_snapshot(curr), 800, 480)
        self.assertIn("home.family_board_update", reasons)
        merged = merge_rects(rects, 800, 480)
        self.assertIsNotNone(merged)
        ratio = rect_area_ratio(merged, 800, 480)
        self.assertLess(ratio, 0.24)

    def test_home_focus_to_left_panel_uses_small_regions(self) -> None:
        prev = AppState(model=DashboardModel())
        prev.ui.screen = Screen.HOME
        prev.ui.focused_index = 1

        curr = AppState(model=DashboardModel())
        curr.ui.screen = Screen.HOME
        curr.ui.focused_index = 0

        rects, reasons = infer_dirty_rects_with_reasons(build_ui_snapshot(prev), build_ui_snapshot(curr), 800, 480)
        self.assertIn("home.focus_to_left_panel", reasons)
        merged = merge_rects(rects, 800, 480)
        self.assertIsNotNone(merged)
        ratio = rect_area_ratio(merged, 800, 480)
        self.assertLess(ratio, 0.24)

    def test_home_voice_overlay_change_uses_voice_zone_rect(self) -> None:
        prev = AppState(model=DashboardModel())
        prev.ui.screen = Screen.HOME
        prev.ui.voice_active = False
        prev.ui.voice_phase = "idle"

        curr = AppState(model=DashboardModel())
        curr.ui.screen = Screen.HOME
        curr.ui.voice_active = True
        curr.ui.voice_phase = "error"

        rects, reasons = infer_dirty_rects_with_reasons(build_ui_snapshot(prev), build_ui_snapshot(curr), 800, 480)
        self.assertIn("home.voice_overlay", reasons)
        merged = merge_rects(rects, 800, 480)
        self.assertIsNotNone(merged)
        x0, y0, x1, y1 = merged or (0, 0, 0, 0)
        self.assertGreater(y0, 360)
        ratio = rect_area_ratio(merged, 800, 480)
        self.assertLess(ratio, 0.10)

    def test_home_menu_overlay_focus_change_uses_compact_rect(self) -> None:
        prev = AppState(model=DashboardModel())
        prev.ui.screen = Screen.HOME
        prev.ui.menu_overlay_active = True
        prev.ui.menu_focused = MenuItemId.LIST

        curr = AppState(model=DashboardModel())
        curr.ui.screen = Screen.HOME
        curr.ui.menu_overlay_active = True
        curr.ui.menu_focused = MenuItemId.SETTINGS

        rects, reasons = infer_dirty_rects_with_reasons(build_ui_snapshot(prev), build_ui_snapshot(curr), 800, 480)
        self.assertIn("home.menu_overlay_focus", reasons)
        merged = merge_rects(rects, 800, 480)
        self.assertIsNotNone(merged)
        ratio = rect_area_ratio(merged, 800, 480)
        self.assertLess(ratio, 0.20)

    def test_home_clock_minute_change_marks_left_clock_region(self) -> None:
        prev = AppState(model=DashboardModel())
        prev.ui.screen = Screen.HOME
        prev.ui.clock_minute_bucket = 100

        curr = AppState(model=DashboardModel())
        curr.ui.screen = Screen.HOME
        curr.ui.clock_minute_bucket = 101

        rects, reasons = infer_dirty_rects_with_reasons(build_ui_snapshot(prev), build_ui_snapshot(curr), 800, 480)
        self.assertIn("home.clock_or_timer_state", reasons)
        merged = merge_rects(rects, 800, 480)
        self.assertIsNotNone(merged)
        ratio = rect_area_ratio(merged, 800, 480)
        self.assertLess(ratio, 0.24)

    def test_timer_alert_blink_change_marks_time_status_region(self) -> None:
        prev = AppState(model=DashboardModel())
        prev.ui.screen = Screen.TIMER
        prev.ui.timer_seconds = 0
        prev.ui.timer_running = False
        prev.ui.timer_alert_active = True
        prev.ui.timer_alert_blink_on = True
        prev.ui.timer_last_completed_seconds = 300

        curr = AppState(model=DashboardModel())
        curr.ui.screen = Screen.TIMER
        curr.ui.timer_seconds = 0
        curr.ui.timer_running = False
        curr.ui.timer_alert_active = True
        curr.ui.timer_alert_blink_on = False
        curr.ui.timer_last_completed_seconds = 300

        rects, reasons = infer_dirty_rects_with_reasons(build_ui_snapshot(prev), build_ui_snapshot(curr), 800, 480)
        self.assertIn("timer.time_or_state", reasons)
        merged = merge_rects(rects, 800, 480)
        self.assertIsNotNone(merged)
        ratio = rect_area_ratio(merged, 800, 480)
        self.assertLess(ratio, 0.50)

    def test_home_focus_row_mapping_uses_real_inventory_count(self) -> None:
        model = DashboardModel()
        model.reminders = [
            Reminder(rid="f1", title="Milk", right="", completed=False, category="fridge"),
            Reminder(rid="s1", title="Eggs", right="", completed=False, category="shopping"),
        ]

        prev = AppState(model=model)
        prev.ui.screen = Screen.HOME
        prev.ui.focused_index = 3  # reminders header when fridge count is 1

        curr = AppState(model=model)
        curr.ui.screen = Screen.HOME
        curr.ui.focused_index = 4  # first reminders item

        rects, reasons = infer_dirty_rects_with_reasons(build_ui_snapshot(prev), build_ui_snapshot(curr), 800, 480)
        self.assertIn("home.focus_move_row", reasons)
        merged = merge_rects(rects, 800, 480)
        self.assertIsNotNone(merged)
        _, y0, _, _ = merged or (0, 0, 0, 0)
        # Reminders section is in the lower half; if this maps near top rows,
        # focus-row geometry is still using a fixed inventory span.
        self.assertGreater(y0, 220)

if __name__ == "__main__":
    unittest.main()
