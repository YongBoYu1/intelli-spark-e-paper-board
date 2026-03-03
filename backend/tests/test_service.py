from __future__ import annotations

import unittest

from backend.voice_api.service import (
    _extract_explicit_correction,
    _repair_context_reference_no_action,
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
        self.assertEqual(action["args"]["item_name"], "牛奶")

    def test_shopping_normalization(self) -> None:
        raw = {"tool": "shopping_add_item", "args": {"item_name": "鸡蛋"}}
        action = normalize_action(raw, request_time="2026-02-20T10:00:00+08:00")
        self.assertEqual(action["tool"], "shopping_add_item")
        self.assertEqual(action["args"]["item_name"], "鸡蛋")

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
        self.assertEqual(action["args"]["item_name"], "牛奶")

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
        self.assertEqual(action["args"]["item_name"], "牛奶")
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

    def test_item_name_normalization_keeps_user_wording(self) -> None:
        raw = {"tool": "shopping_add_item", "args": {"item_name": "  Xiao   Wang   BBQ  "}}
        action = normalize_action(raw, request_time="2026-02-20T10:00:00+08:00")
        self.assertEqual(action["tool"], "shopping_add_item")
        self.assertEqual(action["args"]["item_name"], "Xiao Wang BBQ")

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
        self.assertEqual(plan["actions"][0]["args"]["item_name"], "鸡蛋")
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

    def test_missing_item_name_no_action_is_preserved(self) -> None:
        raw = {
            "tool": "plan_actions",
            "args": {"actions": [{"tool": "no_action", "args": {"reason": "missing_item_name"}}]},
        }
        plan = normalize_plan(raw, request_time="2026-03-03T14:30:00-05:00")
        self.assertEqual(plan["actions"], [{"tool": "no_action", "args": {"reason": "missing_item_name"}}])

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

    def test_context_reference_redo_misfire_repaired_to_repeat_actions(self) -> None:
        plan = {
            "actions": [{"tool": "redo_last_action_group", "args": {}}],
            "needs_clarification": False,
            "clarification": "",
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
            request_time="2026-03-03T13:55:00-05:00",
        )
        self.assertEqual(repaired["actions"], board_context["recent_action_groups"][0]["actions"])

    def test_context_reference_undo_misfire_repaired_to_remove_last(self) -> None:
        plan = {
            "actions": [{"tool": "undo_last_action_group", "args": {}}],
            "needs_clarification": False,
            "clarification": "",
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
            request_time="2026-03-03T13:55:00-05:00",
        )
        self.assertEqual(repaired["actions"], [{"tool": "shopping_remove_item", "args": {"item_name": "coke"}}])

    def test_vague_undo_redo_misfire_becomes_no_action(self) -> None:
        plan = {
            "actions": [{"tool": "redo_last_action_group", "args": {}}],
            "needs_clarification": False,
            "clarification": "",
            "response_copy": "",
        }
        repaired = _repair_context_reference_no_action(
            plan,
            transcript="uhhh do the thing",
            board_context={"recent_action_groups": []},
            request_time="2026-03-03T13:55:00-05:00",
        )
        self.assertEqual(repaired["actions"], [{"tool": "no_action", "args": {"reason": "insufficient_context"}}])

    def test_explicit_undo_phrase_keeps_undo_action(self) -> None:
        plan = {
            "actions": [{"tool": "undo_last_action_group", "args": {}}],
            "needs_clarification": False,
            "clarification": "",
            "response_copy": "",
        }
        repaired = _repair_context_reference_no_action(
            plan,
            transcript="undo that",
            board_context={"recent_action_groups": []},
            request_time="2026-03-03T13:55:00-05:00",
        )
        self.assertEqual(repaired["actions"], [{"tool": "undo_last_action_group", "args": {}}])


if __name__ == "__main__":
    unittest.main()
