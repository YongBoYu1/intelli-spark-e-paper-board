from __future__ import annotations

import unittest

from backend.voice_api.service import normalize_action, normalize_plan


class VoiceBackendNormalizeTests(unittest.TestCase):
    def test_open_app_requires_canonical_app_name(self) -> None:
        got = normalize_action({"tool": "open_app", "args": {"app": "timer"}}, request_time="2026-03-11T10:00:00+00:00")
        self.assertEqual(got.get("tool"), "open_app")
        self.assertEqual((got.get("args") or {}).get("app"), "timer")

    def test_open_app_does_not_use_language_specific_aliases(self) -> None:
        got = normalize_action({"tool": "open_app", "args": {"app": "计时器"}}, request_time="2026-03-11T10:00:00+00:00")
        self.assertEqual(got.get("tool"), "no_action")
        self.assertEqual((got.get("args") or {}).get("reason"), "invalid_app_name")

    def test_shopping_remove_positional_canonical(self) -> None:
        got = normalize_action(
            {
                "tool": "shopping_remove_item",
                "args": {"source": "reminders", "position_mode": "first", "count": 2},
            },
            request_time="2026-03-11T10:00:00+00:00",
        )
        self.assertEqual(got.get("tool"), "shopping_remove_item")
        self.assertEqual((got.get("args") or {}).get("source"), "reminders")
        self.assertEqual((got.get("args") or {}).get("position_mode"), "first")
        self.assertEqual((got.get("args") or {}).get("count"), 2)

    def test_shopping_remove_positional_rejects_noncanonical_source(self) -> None:
        got = normalize_action(
            {
                "tool": "shopping_remove_item",
                "args": {"source": "shopping", "position_mode": "first", "count": 2},
            },
            request_time="2026-03-11T10:00:00+00:00",
        )
        self.assertEqual(got.get("tool"), "no_action")
        self.assertEqual((got.get("args") or {}).get("reason"), "invalid_remove_source")

    def test_shopping_remove_item_keeps_inventory_source(self) -> None:
        got = normalize_action(
            {
                "tool": "shopping_remove_item",
                "args": {"item_name": "milk", "source": "inventory"},
            },
            request_time="2026-03-11T10:00:00+00:00",
        )
        self.assertEqual(got.get("tool"), "shopping_remove_item")
        self.assertEqual((got.get("args") or {}).get("item_name"), "milk")
        self.assertEqual((got.get("args") or {}).get("source"), "inventory")

    def test_shopping_remove_item_rejects_invalid_source(self) -> None:
        got = normalize_action(
            {
                "tool": "shopping_remove_item",
                "args": {"item_name": "milk", "source": "shopping"},
            },
            request_time="2026-03-11T10:00:00+00:00",
        )
        self.assertEqual(got.get("tool"), "no_action")
        self.assertEqual((got.get("args") or {}).get("reason"), "invalid_remove_source")

    def test_memo_update_requires_target_and_text(self) -> None:
        got = normalize_action(
            {
                "tool": "memo_update",
                "args": {"target": "index", "index": 2, "text": "updated"},
            },
            request_time="2026-03-11T10:00:00+00:00",
        )
        self.assertEqual(got.get("tool"), "memo_update")
        self.assertEqual((got.get("args") or {}).get("target"), "index")
        self.assertEqual((got.get("args") or {}).get("index"), 2)
        self.assertEqual((got.get("args") or {}).get("text"), "updated")

    def test_timer_controls_normalize(self) -> None:
        pause = normalize_action({"tool": "timer_pause", "args": {"x": 1}}, request_time="2026-03-11T10:00:00+00:00")
        resume = normalize_action({"tool": "timer_resume", "args": {"x": 1}}, request_time="2026-03-11T10:00:00+00:00")
        stop = normalize_action({"tool": "timer_stop", "args": {"x": 1}}, request_time="2026-03-11T10:00:00+00:00")
        add = normalize_action({"tool": "timer_add", "args": {"delta_seconds": 90}}, request_time="2026-03-11T10:00:00+00:00")
        self.assertEqual((pause.get("tool"), pause.get("args")), ("timer_pause", {}))
        self.assertEqual((resume.get("tool"), resume.get("args")), ("timer_resume", {}))
        self.assertEqual((stop.get("tool"), stop.get("args")), ("timer_stop", {}))
        self.assertEqual(add.get("tool"), "timer_add")
        self.assertEqual((add.get("args") or {}).get("delta_seconds"), 90)

    def test_memo_target_author_normalize(self) -> None:
        got = normalize_action(
            {
                "tool": "memo_delete",
                "args": {"target": "author", "author": "Dad"},
            },
            request_time="2026-03-11T10:00:00+00:00",
        )
        self.assertEqual(got.get("tool"), "memo_delete")
        self.assertEqual((got.get("args") or {}).get("target"), "author")
        self.assertEqual((got.get("args") or {}).get("author"), "Dad")

    def test_memo_clear_all_normalize(self) -> None:
        got = normalize_action(
            {"tool": "memo_clear_all", "args": {}},
            request_time="2026-03-11T10:00:00+00:00",
        )
        self.assertEqual(got.get("tool"), "memo_clear_all")
        self.assertEqual(got.get("args"), {})

    def test_normalize_plan_keeps_more_than_four_actions(self) -> None:
        raw = {
            "plan": {
                "actions": [
                    {"tool": "shopping_add_item", "args": {"item_name": "item-1"}},
                    {"tool": "shopping_add_item", "args": {"item_name": "item-2"}},
                    {"tool": "shopping_add_item", "args": {"item_name": "item-3"}},
                    {"tool": "shopping_add_item", "args": {"item_name": "item-4"}},
                    {"tool": "shopping_add_item", "args": {"item_name": "item-5"}},
                    {"tool": "shopping_add_item", "args": {"item_name": "item-6"}},
                ],
            }
        }
        got = normalize_plan(raw, request_time="2026-03-11T10:00:00+00:00")
        actions = got.get("actions") if isinstance(got, dict) else []
        self.assertTrue(isinstance(actions, list))
        self.assertEqual(len(actions), 6)


if __name__ == "__main__":
    unittest.main()
