from __future__ import annotations

import unittest

from backend.voice_api.service import _align_action_with_transcript, interpret_request, normalize_action


class VoiceServiceNormalizeTests(unittest.TestCase):
    def test_inventory_normalization(self) -> None:
        raw = {
            "tool": "inventory_log_event",
            "args": {
                "item_name": "牛奶",
                "event_type": "consumed",
                "effective_date": "2026-02-19",
            },
        }
        action = normalize_action(raw, request_time="2026-02-20T10:00:00+08:00")
        self.assertEqual(action["tool"], "inventory_log_event")
        self.assertEqual(action["args"]["item_name"], "milk")

    def test_shopping_normalization(self) -> None:
        raw = {"tool": "shopping_add_item", "args": {"item_name": "鸡蛋"}}
        action = normalize_action(raw, request_time="2026-02-20T10:00:00+08:00")
        self.assertEqual(action["tool"], "shopping_add_item")
        self.assertEqual(action["args"]["item_name"], "eggs")

    def test_invalid_tool_becomes_no_action(self) -> None:
        raw = {"tool": "unknown_tool", "args": {}}
        action = normalize_action(raw, request_time="2026-02-20T10:00:00+08:00")
        self.assertEqual(action["tool"], "no_action")

    def test_clear_shopping_normalization(self) -> None:
        raw = {"tool": "shopping_clear_all", "args": {"confirm_token": "pending_physical_confirm"}}
        action = normalize_action(raw, request_time="2026-02-20T10:00:00+08:00")
        self.assertEqual(action["tool"], "shopping_clear_all")

    def test_clear_inventory_normalization(self) -> None:
        raw = {"tool": "inventory_clear_all", "args": {"confirm": "pending_physical_confirm"}}
        action = normalize_action(raw, request_time="2026-02-20T10:00:00+08:00")
        self.assertEqual(action["tool"], "inventory_clear_all")
        self.assertEqual(action["args"]["confirm_token"], "pending_physical_confirm")

    def test_shopping_remove_normalization(self) -> None:
        raw = {"tool": "shopping_remove_item", "args": {"item_name": "牛奶"}}
        action = normalize_action(raw, request_time="2026-02-20T10:00:00+08:00")
        self.assertEqual(action["tool"], "shopping_remove_item")
        self.assertEqual(action["args"]["item_name"], "milk")

    def test_finished_event_is_accepted(self) -> None:
        raw = {
            "tool": "inventory_log_event",
            "args": {
                "item_name": "pizza",
                "event_type": "finished",
            },
        }
        action = normalize_action(raw, request_time="2026-02-20T10:00:00+08:00")
        self.assertEqual(action["tool"], "inventory_log_event")
        self.assertEqual(action["args"]["event_type"], "finished")

    def test_inventory_set_expiry_normalization(self) -> None:
        raw = {
            "tool": "inventory_set_expiry",
            "args": {"item_name": "牛奶", "expiry_date": "2026-03-27"},
        }
        action = normalize_action(raw, request_time="2026-02-20T10:00:00+08:00")
        self.assertEqual(action["tool"], "inventory_set_expiry")
        self.assertEqual(action["args"]["item_name"], "milk")
        self.assertEqual(action["args"]["expiry_date"], "2026-03-27")

    def test_inventory_missing_date_falls_back_request_day(self) -> None:
        raw = {
            "tool": "inventory_log_event",
            "args": {
                "item_name": "pizza",
                "event_type": "consumed",
            },
        }
        action = normalize_action(raw, request_time="2026-02-20T10:00:00+08:00")
        self.assertEqual(action["args"]["effective_date"], "2026-02-20")

    def test_timer_set_normalization_from_text_duration(self) -> None:
        raw = {"tool": "timer_set", "args": {"duration": "20 minutes"}}
        action = normalize_action(raw, request_time="2026-02-20T10:00:00+08:00")
        self.assertEqual(action["tool"], "timer_set")
        self.assertEqual(action["args"]["duration_seconds"], 1200)

    def test_memo_add_normalization(self) -> None:
        raw = {"tool": "memo_add", "args": {"content": "晚点回家", "author": "Alex"}}
        action = normalize_action(raw, request_time="2026-02-20T10:00:00+08:00")
        self.assertEqual(action["tool"], "memo_add")
        self.assertEqual(action["args"]["text"], "晚点回家")
        self.assertEqual(action["args"]["author"], "Alex")

    def test_missing_payload_returns_no_action(self) -> None:
        action = interpret_request({"request_id": "x", "request_time": "2026-02-20T10:00:00+08:00", "timezone": "Asia/Shanghai"})
        self.assertEqual(action["tool"], "no_action")

    def test_shortage_phrase_realigns_inventory_event_to_shopping_add(self) -> None:
        action = {
            "tool": "inventory_log_event",
            "args": {"item_name": "chicken", "event_type": "restocked", "effective_date": "2026-02-20"},
        }
        aligned = _align_action_with_transcript(action, transcript="鸡肉没了，补点鸡肉")
        self.assertEqual(aligned["tool"], "shopping_add_item")
        self.assertEqual(aligned["args"]["item_name"], "chicken")

    def test_english_casual_need_phrase_realigns_to_shopping_add(self) -> None:
        action = {
            "tool": "inventory_log_event",
            "args": {"item_name": "chicken", "event_type": "added", "effective_date": "2026-02-20"},
        }
        aligned = _align_action_with_transcript(action, transcript="we are out of chicken, buy some chicken")
        self.assertEqual(aligned["tool"], "shopping_add_item")
        self.assertEqual(aligned["args"]["item_name"], "chicken")

    def test_chinese_shortage_phrase_realigns_to_shopping_add(self) -> None:
        action = {
            "tool": "inventory_log_event",
            "args": {"item_name": "milk", "event_type": "finished", "effective_date": "2026-02-20"},
        }
        aligned = _align_action_with_transcript(action, transcript="冰箱里没有牛奶了")
        self.assertEqual(aligned["tool"], "shopping_add_item")
        self.assertEqual(aligned["args"]["item_name"], "milk")
        self.assertTrue(aligned["args"]["inventory_remove_if_generic_match"])

    def test_restock_command_phrase_realigns_to_shopping_add(self) -> None:
        action = {
            "tool": "inventory_log_event",
            "args": {"item_name": "chicken", "event_type": "restocked", "effective_date": "2026-02-20"},
        }
        aligned = _align_action_with_transcript(action, transcript="restock chicken")
        self.assertEqual(aligned["tool"], "shopping_add_item")
        self.assertEqual(aligned["args"]["item_name"], "chicken")
        self.assertNotIn("inventory_remove_if_generic_match", aligned["args"])

    def test_casual_shopping_need_phrases_realign_to_shopping_add(self) -> None:
        base = {
            "tool": "inventory_log_event",
            "args": {"item_name": "eggs", "event_type": "added", "effective_date": "2026-02-20"},
        }
        phrases = [
            "need eggs",
            "buy some eggs",
            "we need eggs",
            "running low on eggs",
            "鸡蛋快没了",
            "鸡蛋不够了，买点鸡蛋",
            "shopping list 加鸡蛋吧",
        ]
        for txt in phrases:
            with self.subTest(transcript=txt):
                aligned = _align_action_with_transcript(base, transcript=txt)
                self.assertEqual(aligned["tool"], "shopping_add_item")
                self.assertEqual(aligned["args"]["item_name"], "eggs")

    def test_casual_inventory_presence_phrases_keep_inventory_action(self) -> None:
        base = {
            "tool": "inventory_log_event",
            "args": {"item_name": "salad", "event_type": "added", "effective_date": "2026-02-20"},
        }
        phrases = [
            "I have salad in the fridge",
            "there's leftover curry in the fridge",
            "冰箱里有沙拉",
            "冰箱里有个剩咖喱",
        ]
        for txt in phrases:
            with self.subTest(transcript=txt):
                aligned = _align_action_with_transcript(base, transcript=txt)
                self.assertEqual(aligned["tool"], "inventory_log_event")

    def test_bought_phrase_does_not_realign_to_shopping_add(self) -> None:
        action = {
            "tool": "inventory_log_event",
            "args": {"item_name": "milk", "event_type": "added", "effective_date": "2026-02-20"},
        }
        aligned = _align_action_with_transcript(action, transcript="I already bought milk")
        self.assertEqual(aligned["tool"], "inventory_log_event")

    def test_strong_shortage_phrase_sets_inventory_removal_hint(self) -> None:
        action = {
            "tool": "inventory_log_event",
            "args": {"item_name": "milk", "event_type": "finished", "effective_date": "2026-02-20"},
        }
        aligned = _align_action_with_transcript(action, transcript="we're out of milk")
        self.assertEqual(aligned["tool"], "shopping_add_item")
        self.assertTrue(aligned["args"].get("inventory_remove_if_generic_match"))

    def test_weak_shortage_phrase_does_not_set_inventory_removal_hint(self) -> None:
        action = {
            "tool": "inventory_log_event",
            "args": {"item_name": "milk", "event_type": "added", "effective_date": "2026-02-20"},
        }
        aligned = _align_action_with_transcript(action, transcript="running low on milk")
        self.assertEqual(aligned["tool"], "shopping_add_item")
        self.assertNotIn("inventory_remove_if_generic_match", aligned["args"])

    def test_chinese_weak_shortage_phrase_does_not_set_inventory_removal_hint(self) -> None:
        action = {
            "tool": "inventory_log_event",
            "args": {"item_name": "milk", "event_type": "restocked", "effective_date": "2026-02-20"},
        }
        aligned = _align_action_with_transcript(action, transcript="牛奶快没了，买点牛奶")
        self.assertEqual(aligned["tool"], "shopping_add_item")
        self.assertNotIn("inventory_remove_if_generic_match", aligned["args"])

    def test_direct_shopping_add_strong_shortage_phrase_sets_inventory_removal_hint(self) -> None:
        action = {"tool": "shopping_add_item", "args": {"item_name": "milk"}}
        aligned = _align_action_with_transcript(action, transcript="we're out of milk")
        self.assertEqual(aligned["tool"], "shopping_add_item")
        self.assertTrue(aligned["args"].get("inventory_remove_if_generic_match"))

    def test_direct_shopping_add_weak_shortage_phrase_does_not_set_inventory_removal_hint(self) -> None:
        action = {"tool": "shopping_add_item", "args": {"item_name": "milk"}}
        aligned = _align_action_with_transcript(action, transcript="running low on milk")
        self.assertEqual(aligned["tool"], "shopping_add_item")
        self.assertNotIn("inventory_remove_if_generic_match", aligned["args"])

    def test_inventory_presence_phrase_does_not_realign_to_shopping_add(self) -> None:
        action = {
            "tool": "inventory_log_event",
            "args": {"item_name": "salad", "event_type": "added", "effective_date": "2026-02-20"},
        }
        aligned = _align_action_with_transcript(action, transcript="I have salad in the fridge")
        self.assertEqual(aligned["tool"], "inventory_log_event")

    def test_canonicalization_supports_casual_items(self) -> None:
        raw = {"tool": "shopping_add_item", "args": {"item_name": "鸡肉"}}
        action = normalize_action(raw, request_time="2026-02-20T10:00:00+08:00")
        self.assertEqual(action["tool"], "shopping_add_item")
        self.assertEqual(action["args"]["item_name"], "chicken")


if __name__ == "__main__":
    unittest.main()
