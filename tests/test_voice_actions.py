from __future__ import annotations

import unittest

from app.core.state import AppState, DashboardModel, Reminder, WidgetMode
from app.voice.actions import (
    VoiceAction,
    apply_voice_action,
    confirm_pending_voice_action,
    parse_voice_action,
)


class VoiceActionTests(unittest.TestCase):
    def setUp(self) -> None:
        now = 1771616000.0
        self.state = AppState(
            model=DashboardModel(
                reminders=[
                    Reminder(rid="f1", title="Fresh Milk", right="EXP: 3 DAYS", category="fridge", created_at=now),
                    Reminder(rid="f2", title="Leftover Pizza", right="ADDED YESTERDAY", category="fridge", created_at=now - 86400),
                    Reminder(rid="f3", title="Marinated Chicken", right="USE TONIGHT", category="fridge", created_at=now - 43200),
                    Reminder(rid="s1", title="Eggs", right="VOICE", category="shopping", created_at=now),
                    Reminder(rid="g1", title="Buy Milk", right="", category="general", created_at=now),
                ]
            )
        )

    def test_parse_inventory_action(self) -> None:
        payload = {
            "action": {
                "tool": "inventory_log_event",
                "args": {
                    "item_name": "milk",
                    "event_type": "consumed",
                    "effective_date": "2026-02-18",
                },
            }
        }
        action = parse_voice_action(payload)
        self.assertEqual(action.tool, "inventory_log_event")
        self.assertEqual(action.args["item_name"], "milk")

    def test_parse_shopping_action(self) -> None:
        payload = {
            "tool": "shopping_add_item",
            "args": {
                "item_name": "eggs",
            },
        }
        action = parse_voice_action(payload)
        self.assertEqual(action.tool, "shopping_add_item")
        self.assertEqual(action.args["item_name"], "eggs")

    def test_parse_invalid_action_falls_back_to_no_action(self) -> None:
        payload = {"tool": "shopping_add_item", "args": {}}
        action = parse_voice_action(payload)
        self.assertEqual(action.tool, "no_action")

    def test_parse_clear_action(self) -> None:
        payload = {"tool": "shopping_clear_all", "args": {}}
        action = parse_voice_action(payload)
        self.assertEqual(action.tool, "shopping_clear_all")

    def test_parse_shopping_remove_action(self) -> None:
        payload = {"tool": "shopping_remove_item", "args": {"item_name": "milk"}}
        action = parse_voice_action(payload)
        self.assertEqual(action.tool, "shopping_remove_item")

    def test_parse_expiry_action(self) -> None:
        payload = {"tool": "inventory_set_expiry", "args": {"item_name": "milk", "expiry_date": "2026-03-27"}}
        action = parse_voice_action(payload)
        self.assertEqual(action.tool, "inventory_set_expiry")

    def test_parse_timer_and_memo_actions(self) -> None:
        timer = parse_voice_action({"tool": "timer_set", "args": {"duration_seconds": 1200}})
        memo = parse_voice_action({"tool": "memo_add", "args": {"text": "晚点回家"}})
        self.assertEqual(timer.tool, "timer_set")
        self.assertEqual(memo.tool, "memo_add")

    def test_apply_inventory_used_removes_existing_item(self) -> None:
        before_fridge = len([r for r in self.state.model.reminders if r.category == "fridge"])
        action = VoiceAction(
            tool="inventory_log_event",
            args={"item_name": "milk", "event_type": "consumed", "effective_date": "2026-02-18"},
        )
        result = apply_voice_action(self.state, action)
        self.assertTrue(result.changed)
        self.assertEqual(result.status, "done")
        self.assertIn("removed from inventory", result.message.lower())
        fridge_titles = [r.title.lower() for r in self.state.model.reminders if r.category == "fridge"]
        self.assertNotIn("fresh milk", fridge_titles)
        after_fridge = len([r for r in self.state.model.reminders if r.category == "fridge"])
        self.assertEqual(after_fridge, before_fridge - 1)

    def test_apply_inventory_finished_removes_item(self) -> None:
        action = VoiceAction(
            tool="inventory_log_event",
            args={"item_name": "pizza", "event_type": "finished", "effective_date": "2026-02-18"},
        )
        result = apply_voice_action(self.state, action)
        self.assertTrue(result.changed)
        self.assertEqual(result.status, "done")
        titles = [r.title.lower() for r in self.state.model.reminders if r.category == "fridge"]
        self.assertNotIn("leftover pizza", titles)

    def test_apply_inventory_used_matches_marinated_chicken_from_casual_name(self) -> None:
        action = VoiceAction(
            tool="inventory_log_event",
            args={"item_name": "chicken", "event_type": "used", "effective_date": "2026-02-18"},
        )
        result = apply_voice_action(self.state, action)
        self.assertTrue(result.changed)
        self.assertIn("removed from inventory", result.message.lower())
        titles = [r.title.lower() for r in self.state.model.reminders if r.category == "fridge"]
        self.assertNotIn("marinated chicken", titles)

    def test_apply_inventory_set_expiry_updates_existing_item(self) -> None:
        action = VoiceAction(
            tool="inventory_set_expiry",
            args={"item_name": "milk", "expiry_date": "2026-03-27"},
        )
        result = apply_voice_action(self.state, action)
        self.assertTrue(result.changed)
        milk = [r for r in self.state.model.reminders if r.category == "fridge" and "milk" in r.title.lower()][0]
        self.assertIn("EXP:", milk.right)

    def test_apply_inventory_set_expiry_creates_salad_when_missing(self) -> None:
        action = VoiceAction(
            tool="inventory_set_expiry",
            args={"item_name": "salad", "expiry_date": "2026-02-24"},
        )
        result = apply_voice_action(self.state, action)
        self.assertTrue(result.changed)
        self.assertIn("added expiry", result.message.lower())
        fridge_titles = [r.title.lower() for r in self.state.model.reminders if r.category == "fridge"]
        self.assertIn("salad", fridge_titles)
        self.assertEqual(len(fridge_titles), 3)

    def test_apply_shopping_action_deduplicates(self) -> None:
        action = VoiceAction(tool="shopping_add_item", args={"item_name": "eggs"})
        result = apply_voice_action(self.state, action)
        self.assertFalse(result.changed)
        self.assertEqual(result.status, "done")
        shopping_titles = [r.title.lower() for r in self.state.model.reminders if r.category == "shopping"]
        self.assertEqual(shopping_titles.count("eggs"), 1)

    def test_strong_shortage_shopping_add_removes_generic_inventory_match(self) -> None:
        action = VoiceAction(
            tool="shopping_add_item",
            args={"item_name": "milk", "inventory_remove_if_generic_match": True},
        )
        result = apply_voice_action(self.state, action)
        self.assertTrue(result.changed)
        self.assertIn("already in shopping", result.message.lower())
        self.assertIn("removed from inventory", result.message.lower())
        fridge_titles = [r.title.lower() for r in self.state.model.reminders if r.category == "fridge"]
        self.assertNotIn("fresh milk", fridge_titles)

    def test_strong_shortage_shopping_add_keeps_specific_inventory_match(self) -> None:
        action = VoiceAction(
            tool="shopping_add_item",
            args={"item_name": "chicken", "inventory_remove_if_generic_match": True},
        )
        result = apply_voice_action(self.state, action)
        self.assertTrue(result.changed)
        self.assertIn("added to shopping", result.message.lower())
        self.assertNotIn("removed from inventory", result.message.lower())
        fridge_titles = [r.title.lower() for r in self.state.model.reminders if r.category == "fridge"]
        self.assertIn("marinated chicken", fridge_titles)

    def test_apply_shopping_remove_item(self) -> None:
        result = apply_voice_action(self.state, VoiceAction(tool="shopping_remove_item", args={"item_name": "milk"}))
        self.assertTrue(result.changed)
        self.assertIn("removed from shopping", result.message.lower())
        titles = [r.title.lower() for r in self.state.model.reminders]
        self.assertNotIn("buy milk", titles)

    def test_restocked_inventory_removes_matching_buy_item(self) -> None:
        action = VoiceAction(
            tool="inventory_log_event",
            args={"item_name": "milk", "event_type": "added", "effective_date": "2026-02-20"},
        )
        result = apply_voice_action(self.state, action)
        self.assertTrue(result.changed)
        self.assertIn("removed from shopping", result.message.lower())
        titles = [r.title.lower() for r in self.state.model.reminders]
        self.assertNotIn("buy milk", titles)

    def test_inventory_add_eviction_removes_oldest(self) -> None:
        action = VoiceAction(
            tool="inventory_log_event",
            args={"item_name": "bread", "event_type": "added", "effective_date": "2026-02-20"},
        )
        result = apply_voice_action(self.state, action)
        self.assertTrue(result.changed)
        self.assertIn("added to inventory", result.message.lower())
        fridge_titles = [r.title.lower() for r in self.state.model.reminders if r.category == "fridge"]
        self.assertEqual(len(fridge_titles), 3)
        self.assertIn("bread", fridge_titles)
        self.assertNotIn("leftover pizza", fridge_titles)

    def test_inventory_add_leftover_curry_uses_canonical_key(self) -> None:
        action = VoiceAction(
            tool="inventory_log_event",
            args={"item_name": "leftover curry", "event_type": "added", "effective_date": "2026-02-20"},
        )
        result = apply_voice_action(self.state, action)
        self.assertTrue(result.changed)
        self.assertIn("added to inventory", result.message.lower())
        titles = [r.title.lower() for r in self.state.model.reminders if r.category == "fridge"]
        self.assertIn("leftover curry", titles)

    def test_clear_shopping_requires_confirm_and_then_clears(self) -> None:
        first = apply_voice_action(self.state, VoiceAction(tool="shopping_clear_all", args={}))
        self.assertFalse(first.changed)
        self.assertIn("confirm", first.message.lower())
        confirmed = confirm_pending_voice_action(self.state)
        self.assertIsNotNone(confirmed)
        self.assertTrue(bool(confirmed and confirmed.changed))
        right_list_count = len([r for r in self.state.model.reminders if r.category != "fridge"])
        self.assertEqual(right_list_count, 0)

    def test_clear_inventory_requires_confirm_and_then_clears(self) -> None:
        first = apply_voice_action(self.state, VoiceAction(tool="inventory_clear_all", args={}))
        self.assertFalse(first.changed)
        self.assertIn("confirm", first.message.lower())
        confirmed = confirm_pending_voice_action(self.state)
        self.assertIsNotNone(confirmed)
        fridge_count = len([r for r in self.state.model.reminders if r.category == "fridge"])
        self.assertEqual(fridge_count, 0)

    def test_timer_set_and_memo_add(self) -> None:
        t = apply_voice_action(self.state, VoiceAction(tool="timer_set", args={"duration_seconds": 1200}))
        self.assertTrue(t.changed)
        self.assertEqual(self.state.ui.widget_mode, WidgetMode.TIMER)
        self.assertEqual(self.state.ui.timer_seconds, 1200)
        before = len(self.state.model.memos)
        m = apply_voice_action(self.state, VoiceAction(tool="memo_add", args={"text": "晚点回家", "author": "Voice"}))
        self.assertTrue(m.changed)
        self.assertEqual(len(self.state.model.memos), before + 1)
        self.assertEqual(self.state.model.memos[0].text, "晚点回家")

    def test_apply_no_action_changes_nothing(self) -> None:
        action = VoiceAction(tool="no_action", args={"reason": "insufficient_intent"})
        result = apply_voice_action(self.state, action)
        self.assertFalse(result.changed)
        self.assertEqual(result.status, "done")
        self.assertGreater(len(self.state.model.reminders), 0)


if __name__ == "__main__":
    unittest.main()
