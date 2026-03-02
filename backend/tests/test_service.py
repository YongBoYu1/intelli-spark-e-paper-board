from __future__ import annotations

import unittest

from backend.voice_api.service import (
    _align_action_with_transcript,
    _extract_explicit_correction,
    _repair_context_reference_no_action,
    _repair_missing_item_name_no_action,
    _validate_plan_against_schema,
    interpret_request,
    normalize_action,
    normalize_plan,
)


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

    def test_undo_and_redo_normalization(self) -> None:
        undo = normalize_action({"tool": "undo_last_action_group", "args": {"unexpected": True}}, request_time="2026-02-20T10:00:00+08:00")
        redo = normalize_action({"tool": "redo_last_action_group", "args": {"count": 3}}, request_time="2026-02-20T10:00:00+08:00")
        self.assertEqual(undo, {"tool": "undo_last_action_group", "args": {}})
        self.assertEqual(redo, {"tool": "redo_last_action_group", "args": {}})

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

    def test_plan_actions_normalization_keeps_order(self) -> None:
        raw = {
            "tool": "plan_actions",
            "args": {
                "actions": [
                    {"tool": "shopping_add_item", "args": {"item_name": "鸡蛋"}},
                    {"tool": "memo_add", "args": {"text": "今晚晚点回家", "author": "Alex"}},
                ],
                "response_copy": "Done",
            },
        }
        plan = normalize_plan(raw, request_time="2026-02-20T10:00:00+08:00")
        self.assertEqual(len(plan["actions"]), 2)
        self.assertEqual(plan["actions"][0]["tool"], "shopping_add_item")
        self.assertEqual(plan["actions"][0]["args"]["item_name"], "eggs")
        self.assertEqual(plan["actions"][1]["tool"], "memo_add")
        self.assertEqual(plan["response_copy"], "Done")

    def test_plan_actions_normalization_supports_undo_redo_and_schema(self) -> None:
        raw = {
            "tool": "plan_actions",
            "args": {
                "actions": [
                    {"tool": "undo_last_action_group", "args": {}},
                    {"tool": "redo_last_action_group", "args": {}},
                ]
            },
        }
        plan = normalize_plan(raw, request_time="2026-02-20T10:00:00+08:00")
        self.assertEqual(plan["actions"][0]["tool"], "undo_last_action_group")
        self.assertEqual(plan["actions"][1]["tool"], "redo_last_action_group")
        self.assertTrue(_validate_plan_against_schema(plan))

    def test_missing_item_name_no_action_can_be_repaired_from_context(self) -> None:
        plan = {
            "actions": [
                {"tool": "no_action", "args": {"reason": "missing_item_name"}},
            ],
            "needs_clarification": False,
            "clarification": "",
            "response_copy": "",
        }
        board_context = {
            "shopping": {
                "items": [
                    {"title": "Buy Milk"},
                    {"title": "Doctor Appointment"},
                ]
            }
        }
        repaired = _repair_missing_item_name_no_action(
            plan,
            transcript="They have bought milk already.",
            board_context=board_context,
            request_time="2026-03-02T13:55:00-05:00",
        )
        self.assertEqual(repaired["actions"][0]["tool"], "shopping_remove_item")
        self.assertEqual(repaired["actions"][0]["args"]["item_name"], "milk")

    def test_extract_explicit_correction_phrase(self) -> None:
        got = _extract_explicit_correction("不是酒戒，是街道的街，酒街")
        self.assertEqual(got, ("酒戒", "酒街"))

    def test_context_reference_do_that_again_replays_recent_group(self) -> None:
        plan = {
            "actions": [{"tool": "no_action", "args": {"reason": "insufficient_context"}}],
            "needs_clarification": True,
            "clarification": "Which one?",
            "response_copy": "",
        }
        board_context = {
            "recent_action_groups": [
                {
                    "actions": [
                        {"tool": "shopping_add_item", "args": {"item_name": "milk"}},
                        {"tool": "shopping_add_item", "args": {"item_name": "cookies"}},
                    ]
                }
            ]
        }
        repaired = _repair_context_reference_no_action(
            plan,
            transcript="do that again",
            board_context=board_context,
            request_time="2026-03-02T13:55:00-05:00",
        )
        self.assertEqual(repaired["actions"][0]["tool"], "shopping_add_item")
        self.assertEqual(repaired["actions"][0]["args"]["item_name"], "milk")
        self.assertEqual(repaired["actions"][1]["args"]["item_name"], "cookies")

    def test_context_reference_same_again_but_no_timer_drops_timer(self) -> None:
        plan = {
            "actions": [{"tool": "no_action", "args": {"reason": "insufficient_context"}}],
            "needs_clarification": True,
            "clarification": "Which one?",
            "response_copy": "",
        }
        board_context = {
            "recent_action_groups": [
                {
                    "actions": [
                        {"tool": "timer_set", "args": {"duration_seconds": 600}},
                        {"tool": "shopping_add_item", "args": {"item_name": "chips"}},
                    ]
                }
            ]
        }
        repaired = _repair_context_reference_no_action(
            plan,
            transcript="same again but no timer",
            board_context=board_context,
            request_time="2026-03-02T13:55:00-05:00",
        )
        self.assertEqual(len(repaired["actions"]), 1)
        self.assertEqual(repaired["actions"][0]["tool"], "shopping_add_item")
        self.assertEqual(repaired["actions"][0]["args"]["item_name"], "chips")

    def test_context_reference_same_for_item_uses_recent_template(self) -> None:
        plan = {
            "actions": [{"tool": "no_action", "args": {"reason": "insufficient_context"}}],
            "needs_clarification": True,
            "clarification": "Which one?",
            "response_copy": "",
        }
        board_context = {
            "recent_action_groups": [
                {
                    "actions": [
                        {"tool": "shopping_add_item", "args": {"item_name": "eggs"}},
                    ]
                }
            ]
        }
        repaired = _repair_context_reference_no_action(
            plan,
            transcript="and the same for milk",
            board_context=board_context,
            request_time="2026-03-02T13:55:00-05:00",
        )
        self.assertEqual(repaired["actions"], [{"tool": "shopping_add_item", "args": {"item_name": "milk"}}])

    def test_context_reference_same_for_item_strips_casual_tail_words(self) -> None:
        plan = {
            "actions": [{"tool": "no_action", "args": {"reason": "insufficient_context"}}],
            "needs_clarification": True,
            "clarification": "Which one?",
            "response_copy": "",
        }
        board_context = {
            "recent_action_groups": [
                {
                    "actions": [
                        {"tool": "shopping_add_item", "args": {"item_name": "eggs"}},
                    ]
                }
            ]
        }
        repaired = _repair_context_reference_no_action(
            plan,
            transcript="and the same for milk too please",
            board_context=board_context,
            request_time="2026-03-02T13:55:00-05:00",
        )
        self.assertEqual(repaired["actions"], [{"tool": "shopping_add_item", "args": {"item_name": "milk"}}])

    def test_context_reference_remove_last_one_inverts_recent_add(self) -> None:
        plan = {
            "actions": [{"tool": "no_action", "args": {"reason": "ambiguous_reference"}}],
            "needs_clarification": True,
            "clarification": "Which one?",
            "response_copy": "",
        }
        board_context = {
            "recent_action_groups": [
                {
                    "actions": [
                        {"tool": "shopping_add_item", "args": {"item_name": "coke"}},
                    ]
                }
            ]
        }
        repaired = _repair_context_reference_no_action(
            plan,
            transcript="actually remove that",
            board_context=board_context,
            request_time="2026-03-02T13:55:00-05:00",
        )
        self.assertEqual(repaired["actions"], [{"tool": "shopping_remove_item", "args": {"item_name": "coke"}}])

    def test_context_reference_remove_last_one_targets_latest_action(self) -> None:
        plan = {
            "actions": [{"tool": "no_action", "args": {"reason": "ambiguous_reference"}}],
            "needs_clarification": True,
            "clarification": "Which one?",
            "response_copy": "",
        }
        board_context = {
            "recent_action_groups": [
                {
                    "actions": [
                        {"tool": "shopping_add_item", "args": {"item_name": "apples"}},
                        {"tool": "shopping_add_item", "args": {"item_name": "bananas"}},
                    ]
                }
            ]
        }
        repaired = _repair_context_reference_no_action(
            plan,
            transcript="remove the last one",
            board_context=board_context,
            request_time="2026-03-02T13:55:00-05:00",
        )
        self.assertEqual(repaired["actions"], [{"tool": "shopping_remove_item", "args": {"item_name": "bananas"}}])


if __name__ == "__main__":
    unittest.main()
