from __future__ import annotations

from datetime import datetime, timedelta
import unittest

from app.core.state import AppState, DashboardModel, Reminder, Screen, WidgetMode
from app.core.reducer import Back, reduce
from app.voice.actions import (
    VoiceAction,
    VoicePlan,
    apply_voice_action,
    apply_voice_plan,
    build_request_meta,
    confirm_pending_voice_action,
    parse_voice_plan,
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
        payload = {"tool": "shopping_remove_item", "args": {"item_name": "milk", "source": "inventory"}}
        action = parse_voice_action(payload)
        self.assertEqual(action.tool, "shopping_remove_item")
        self.assertEqual(action.args.get("source"), "inventory")

    def test_parse_shopping_remove_action_rejects_invalid_source(self) -> None:
        payload = {"tool": "shopping_remove_item", "args": {"item_name": "milk", "source": "shopping"}}
        action = parse_voice_action(payload)
        self.assertEqual(action.tool, "no_action")
        self.assertEqual(action.args.get("reason"), "invalid_remove_source")

    def test_parse_expiry_action(self) -> None:
        payload = {"tool": "inventory_set_expiry", "args": {"item_name": "milk", "expiry_date": "2026-03-27"}}
        action = parse_voice_action(payload)
        self.assertEqual(action.tool, "inventory_set_expiry")

    def test_parse_timer_and_memo_actions(self) -> None:
        timer = parse_voice_action({"tool": "timer_set", "args": {"duration_seconds": 1200}})
        timer_add = parse_voice_action({"tool": "timer_add", "args": {"delta_seconds": 60}})
        timer_pause = parse_voice_action({"tool": "timer_pause", "args": {"unexpected": True}})
        timer_resume = parse_voice_action({"tool": "timer_resume", "args": {"unexpected": True}})
        timer_stop = parse_voice_action({"tool": "timer_stop", "args": {"unexpected": True}})
        memo = parse_voice_action({"tool": "memo_add", "args": {"text": "晚点回家"}})
        memo_clear = parse_voice_action({"tool": "memo_clear_all", "args": {"confirm_token": "ignored"}})
        self.assertEqual(timer.tool, "timer_set")
        self.assertEqual(timer_add.tool, "timer_add")
        self.assertEqual(timer_add.args.get("delta_seconds"), 60)
        self.assertEqual(timer_pause.tool, "timer_pause")
        self.assertEqual(timer_pause.args, {})
        self.assertEqual(timer_resume.tool, "timer_resume")
        self.assertEqual(timer_resume.args, {})
        self.assertEqual(timer_stop.tool, "timer_stop")
        self.assertEqual(timer_stop.args, {})
        self.assertEqual(memo.tool, "memo_add")
        self.assertEqual(memo_clear.tool, "memo_clear_all")
        self.assertEqual(memo_clear.args, {})

    def test_parse_open_app_and_memo_crud_actions(self) -> None:
        open_app = parse_voice_action({"tool": "open_app", "args": {"app": "timer"}})
        memo_delete = parse_voice_action({"tool": "memo_delete", "args": {"target": "index", "index": 2}})
        memo_update = parse_voice_action({"tool": "memo_update", "args": {"target": "latest", "text": "new"}})
        memo_delete_author = parse_voice_action({"tool": "memo_delete", "args": {"target": "author", "author": "Dad"}})
        memo_update_author = parse_voice_action({"tool": "memo_update", "args": {"target": "author", "author": "Dad", "text": "new"}})
        self.assertEqual(open_app.tool, "open_app")
        self.assertEqual(open_app.args.get("app"), "timer")
        self.assertEqual(memo_delete.tool, "memo_delete")
        self.assertEqual(memo_update.tool, "memo_update")
        self.assertEqual(memo_delete_author.args.get("target"), "author")
        self.assertEqual(memo_delete_author.args.get("author"), "Dad")
        self.assertEqual(memo_update_author.args.get("target"), "author")
        self.assertEqual(memo_update_author.args.get("author"), "Dad")

    def test_parse_undo_redo_actions(self) -> None:
        undo = parse_voice_action({"tool": "undo_last_action_group", "args": {"unexpected": True}})
        redo = parse_voice_action({"tool": "redo_last_action_group", "args": {"count": 3}})
        self.assertEqual(undo.tool, "undo_last_action_group")
        self.assertEqual(redo.tool, "redo_last_action_group")
        self.assertEqual(undo.args, {})
        self.assertEqual(redo.args, {})

    def test_parse_voice_plan_multi_actions(self) -> None:
        payload = {
            "plan": {
                "actions": [
                    {"tool": "shopping_add_item", "args": {"item_name": "milk"}},
                    {"tool": "shopping_add_item", "args": {"item_name": "cookies"}},
                ],
                "response_copy": "Done.",
            }
        }
        plan = parse_voice_plan(payload)
        self.assertEqual(len(plan.actions), 2)
        self.assertEqual(plan.actions[0].tool, "shopping_add_item")
        self.assertEqual(plan.actions[1].args["item_name"], "cookies")
        self.assertEqual(plan.response_copy, "Done.")

    def test_apply_inventory_used_marks_existing_item_completed(self) -> None:
        action = VoiceAction(
            tool="inventory_log_event",
            args={"item_name": "milk", "event_type": "consumed", "effective_date": "2026-02-18"},
        )
        result = apply_voice_action(self.state, action)
        self.assertTrue(result.changed)
        self.assertEqual(result.status, "done")
        self.assertIn("marked done in inventory", result.message.lower())
        milk_rows = [r for r in self.state.model.reminders if r.category == "fridge" and "milk" in r.title.lower()]
        self.assertEqual(len(milk_rows), 1)
        self.assertTrue(bool(milk_rows[0].completed))
        self.assertTrue(self.state.ui.pending_reorder)

    def test_apply_inventory_finished_marks_item_completed(self) -> None:
        action = VoiceAction(
            tool="inventory_log_event",
            args={"item_name": "pizza", "event_type": "finished", "effective_date": "2026-02-18"},
        )
        result = apply_voice_action(self.state, action)
        self.assertTrue(result.changed)
        self.assertEqual(result.status, "done")
        pizza_rows = [r for r in self.state.model.reminders if r.category == "fridge" and "pizza" in r.title.lower()]
        self.assertEqual(len(pizza_rows), 1)
        self.assertTrue(bool(pizza_rows[0].completed))

    def test_apply_inventory_used_matches_marinated_chicken_from_casual_name(self) -> None:
        action = VoiceAction(
            tool="inventory_log_event",
            args={"item_name": "chicken", "event_type": "used", "effective_date": "2026-02-18"},
        )
        result = apply_voice_action(self.state, action)
        self.assertTrue(result.changed)
        self.assertIn("marked done in inventory", result.message.lower())
        rows = [r for r in self.state.model.reminders if r.category == "fridge" and "chicken" in r.title.lower()]
        self.assertEqual(len(rows), 1)
        self.assertTrue(bool(rows[0].completed))

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

    def test_strong_shortage_shopping_add_does_not_remove_non_exact_inventory_match(self) -> None:
        action = VoiceAction(
            tool="shopping_add_item",
            args={"item_name": "milk", "inventory_remove_if_generic_match": True},
        )
        result = apply_voice_action(self.state, action)
        self.assertFalse(result.changed)
        self.assertIn("already in shopping", result.message.lower())
        self.assertNotIn("removed from inventory", result.message.lower())
        fridge_titles = [r.title.lower() for r in self.state.model.reminders if r.category == "fridge"]
        self.assertIn("fresh milk", fridge_titles)

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

    def test_strong_shortage_shopping_add_removes_later_generic_inventory_match_after_specific(self) -> None:
        now = 1771616000.0
        self.state.model.reminders = [
            Reminder(rid="f1", title="Marinated Chicken", right="USE TONIGHT", category="fridge", created_at=now),
            Reminder(rid="f4", title="Chicken", right="EXP: 2 DAYS", category="fridge", created_at=now - 100),
            Reminder(rid="g1", title="Buy Milk", right="", category="general", created_at=now),
        ]
        action = VoiceAction(
            tool="shopping_add_item",
            args={"item_name": "chicken", "inventory_remove_if_generic_match": True},
        )
        result = apply_voice_action(self.state, action)
        self.assertTrue(result.changed)
        self.assertIn("removed from inventory: chicken", result.message.lower())
        fridge_titles = [r.title.lower() for r in self.state.model.reminders if r.category == "fridge"]
        self.assertIn("marinated chicken", fridge_titles)
        self.assertNotIn("chicken", fridge_titles)

    def test_apply_shopping_remove_item(self) -> None:
        result = apply_voice_action(self.state, VoiceAction(tool="shopping_remove_item", args={"item_name": "milk"}))
        self.assertTrue(result.changed)
        self.assertIn("marked done", result.message.lower())
        rows = [r for r in self.state.model.reminders if r.title.lower() == "buy milk"]
        self.assertEqual(len(rows), 1)
        self.assertTrue(bool(rows[0].completed))

    def test_apply_shopping_remove_item_inventory_source_marks_inventory(self) -> None:
        result = apply_voice_action(
            self.state,
            VoiceAction(tool="shopping_remove_item", args={"item_name": "milk", "source": "inventory"}),
        )
        self.assertTrue(result.changed)
        self.assertIn("marked done in inventory", result.message.lower())
        fridge_rows = [r for r in self.state.model.reminders if r.title.lower() == "fresh milk"]
        self.assertEqual(len(fridge_rows), 1)
        self.assertTrue(bool(fridge_rows[0].completed))
        shopping_rows = [r for r in self.state.model.reminders if r.title.lower() == "buy milk"]
        self.assertEqual(len(shopping_rows), 1)
        self.assertFalse(bool(shopping_rows[0].completed))

    def test_apply_shopping_remove_item_inventory_source_on_home_kitchen_uses_pending_hide(self) -> None:
        self.state.ui.screen = Screen.HOME
        self.state.ui.kitchen_visible_layout = "landscape"

        result = apply_voice_action(
            self.state,
            VoiceAction(tool="shopping_remove_item", args={"item_name": "milk", "source": "inventory"}),
        )

        self.assertTrue(result.changed)
        self.assertEqual(self.state.ui.home_pending_hide_rids, ["f1"])
        self.assertFalse(self.state.ui.pending_reorder)
        self.assertEqual(self.state.ui.reorder_due_at, 0.0)

    def test_apply_shopping_remove_item_inventory_source_on_home_uses_theme_semantics_when_layout_not_set(self) -> None:
        self.state.ui.screen = Screen.HOME
        self.state.ui.rotation_deg = 0
        self.state.ui.kitchen_visible_layout = ""

        result = apply_voice_action(
            self.state,
            VoiceAction(tool="shopping_remove_item", args={"item_name": "milk", "source": "inventory"}),
            theme={"home_variant": "kitchen_portrait"},
        )

        self.assertTrue(result.changed)
        self.assertEqual(self.state.ui.home_pending_hide_rids, ["f1"])
        self.assertFalse(self.state.ui.pending_reorder)
        self.assertEqual(self.state.ui.reorder_due_at, 0.0)

    def test_apply_shopping_remove_item_inventory_source_on_list_keeps_reorder_behavior(self) -> None:
        self.state.ui.screen = Screen.REMINDERS

        result = apply_voice_action(
            self.state,
            VoiceAction(tool="shopping_remove_item", args={"item_name": "milk", "source": "inventory"}),
        )

        self.assertTrue(result.changed)
        self.assertTrue(self.state.ui.pending_reorder)
        self.assertGreater(self.state.ui.reorder_due_at, 0.0)

    def test_apply_shopping_remove_positional_first_two(self) -> None:
        self.state.model.reminders.append(Reminder(rid="g2", title="Buy Bread", right="", category="general", created_at=1771616001.0))
        result = apply_voice_action(
            self.state,
            VoiceAction(
                tool="shopping_remove_item",
                args={"source": "reminders", "position_mode": "first", "count": 2},
            ),
        )
        self.assertTrue(result.changed)
        right_rows = [r for r in self.state.model.reminders if r.category != "fridge"]
        self.assertTrue(all(bool(r.completed) for r in right_rows[:2]))

    def test_apply_shopping_remove_positional_count_overflow_is_partial_success(self) -> None:
        result = apply_voice_action(
            self.state,
            VoiceAction(
                tool="shopping_remove_item",
                args={"source": "reminders", "position_mode": "first", "count": 10},
            ),
        )
        self.assertTrue(result.changed)
        self.assertIn("2/10", result.message.lower())
        right_rows = [r for r in self.state.model.reminders if r.category != "fridge"]
        self.assertTrue(all(bool(r.completed) for r in right_rows))

    def test_apply_open_app_inventory_routes_to_list_screen(self) -> None:
        self.state.ui.screen = Screen.HOME
        result = apply_voice_action(self.state, VoiceAction(tool="open_app", args={"app": "inventory"}))
        self.assertTrue(result.changed)
        self.assertEqual(self.state.ui.screen, Screen.REMINDERS)
        self.assertEqual(self.state.ui.list_focused_index, 0)

    def test_apply_memo_delete_and_update(self) -> None:
        self.state.model.memos = []
        apply_voice_action(self.state, VoiceAction(tool="memo_add", args={"text": "first memo"}))
        apply_voice_action(self.state, VoiceAction(tool="memo_add", args={"text": "second memo"}))
        upd = apply_voice_action(self.state, VoiceAction(tool="memo_update", args={"target": "index", "index": 2, "text": "edited"}))
        self.assertTrue(upd.changed)
        self.assertEqual(self.state.model.memos[1].text, "edited")
        dele = apply_voice_action(self.state, VoiceAction(tool="memo_delete", args={"target": "latest"}))
        self.assertTrue(dele.changed)

    def test_apply_memo_update_and_delete_by_author(self) -> None:
        self.state.model.memos = []
        apply_voice_action(self.state, VoiceAction(tool="memo_add", args={"text": "call Alex", "author": "Dad"}))
        apply_voice_action(self.state, VoiceAction(tool="memo_add", args={"text": "pick up milk", "author": "Mom"}))
        upd = apply_voice_action(
            self.state,
            VoiceAction(tool="memo_update", args={"target": "author", "author": "Dad", "text": "call Alex tonight"}),
        )
        self.assertTrue(upd.changed)
        self.assertTrue(any(m.author == "Dad" and m.text == "call Alex tonight" for m in self.state.model.memos))
        dele = apply_voice_action(
            self.state,
            VoiceAction(tool="memo_delete", args={"target": "author", "author": "Mom"}),
        )
        self.assertTrue(dele.changed)
        self.assertFalse(any(m.author == "Mom" for m in self.state.model.memos))

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

    def test_restocked_inventory_message_uses_correct_title_when_shopping_removed_before_fridge(self) -> None:
        now = 1771616000.0
        self.state.model.reminders = [
            Reminder(rid="g1", title="Buy Milk", right="", category="general", created_at=now),
            Reminder(rid="f1", title="Fresh Milk", right="EXP: 3 DAYS", category="fridge", created_at=now),
            Reminder(rid="f2", title="Leftover Pizza", right="ADDED YESTERDAY", category="fridge", created_at=now - 86400),
            Reminder(rid="f3", title="Marinated Chicken", right="USE TONIGHT", category="fridge", created_at=now - 43200),
        ]
        action = VoiceAction(
            tool="inventory_log_event",
            args={"item_name": "milk", "event_type": "added", "effective_date": "2026-02-20"},
        )
        result = apply_voice_action(self.state, action)
        self.assertTrue(result.changed)
        self.assertIn("updated inventory: fresh milk", result.message.lower())
        self.assertNotIn("updated inventory: leftover pizza", result.message.lower())

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

    def test_shopping_add_eggplant_does_not_dedupe_as_eggs(self) -> None:
        result = apply_voice_action(self.state, VoiceAction(tool="shopping_add_item", args={"item_name": "eggplant"}))
        self.assertTrue(result.changed)
        self.assertIn("added to shopping", result.message.lower())
        self.assertNotIn("already in shopping", result.message.lower())
        titles = [r.title.lower() for r in self.state.model.reminders if r.category != "fridge"]
        self.assertIn("eggplant", titles)
        self.assertEqual(sum(1 for t in titles if t == "eggs"), 1)

    def test_inventory_event_veggie_soup_does_not_remove_eggs_by_substring(self) -> None:
        before_titles = [r.title for r in self.state.model.reminders]
        result = apply_voice_action(
            self.state,
            VoiceAction(
                tool="inventory_log_event",
                args={"item_name": "veggie soup", "event_type": "consumed", "effective_date": "2026-02-20"},
            ),
        )
        self.assertFalse(result.changed)
        self.assertIn("skipped", result.message.lower())
        after_titles = [r.title for r in self.state.model.reminders]
        self.assertEqual(after_titles, before_titles)

    def test_apply_inventory_used_on_home_kitchen_uses_pending_hide(self) -> None:
        self.state.ui.screen = Screen.HOME
        self.state.ui.kitchen_visible_layout = "landscape"

        result = apply_voice_action(
            self.state,
            VoiceAction(
                tool="inventory_log_event",
                args={"item_name": "milk", "event_type": "consumed", "effective_date": "2026-02-20"},
            ),
        )

        self.assertTrue(result.changed)
        self.assertEqual(self.state.ui.home_pending_hide_rids, ["f1"])
        self.assertFalse(self.state.ui.pending_reorder)

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
        self.assertEqual(self.state.ui.screen, Screen.TIMER)
        self.assertEqual(self.state.ui.timer_seconds, 1200)
        before = len(self.state.model.memos)
        m = apply_voice_action(self.state, VoiceAction(tool="memo_add", args={"text": "晚点回家", "author": "Voice"}))
        self.assertTrue(m.changed)
        self.assertEqual(len(self.state.model.memos), before + 1)
        self.assertEqual(self.state.model.memos[0].text, "晚点回家")

    def test_timer_control_actions(self) -> None:
        apply_voice_action(self.state, VoiceAction(tool="timer_set", args={"duration_seconds": 120}))
        self.assertEqual(self.state.ui.timer_target_seconds, 120)
        pause = apply_voice_action(self.state, VoiceAction(tool="timer_pause", args={}))
        self.assertTrue(pause.changed)
        self.assertFalse(self.state.ui.timer_running)
        add = apply_voice_action(self.state, VoiceAction(tool="timer_add", args={"delta_seconds": 60}))
        self.assertTrue(add.changed)
        self.assertEqual(self.state.ui.timer_seconds, 180)
        self.assertEqual(self.state.ui.timer_target_seconds, 180)
        resume = apply_voice_action(self.state, VoiceAction(tool="timer_resume", args={}))
        self.assertTrue(resume.changed)
        self.assertTrue(self.state.ui.timer_running)
        stop = apply_voice_action(self.state, VoiceAction(tool="timer_stop", args={}))
        self.assertTrue(stop.changed)
        self.assertFalse(self.state.ui.timer_running)
        self.assertEqual(self.state.ui.timer_seconds, 0)

    def test_timer_add_ignores_stale_target_from_previous_session(self) -> None:
        self.state.ui.timer_target_seconds = 1800

        apply_voice_action(self.state, VoiceAction(tool="timer_set", args={"duration_seconds": 60}))
        add = apply_voice_action(self.state, VoiceAction(tool="timer_add", args={"delta_seconds": 30}))

        self.assertTrue(add.changed)
        self.assertEqual(self.state.ui.timer_seconds, 90)
        self.assertEqual(self.state.ui.timer_target_seconds, 90)

    def test_clear_memo_requires_confirm_and_then_clears(self) -> None:
        self.state.model.memos = []
        apply_voice_action(self.state, VoiceAction(tool="memo_add", args={"text": "first"}))
        apply_voice_action(self.state, VoiceAction(tool="memo_add", args={"text": "second"}))
        first = apply_voice_action(self.state, VoiceAction(tool="memo_clear_all", args={}))
        self.assertFalse(first.changed)
        self.assertEqual(first.status, "confirm")
        confirmed = confirm_pending_voice_action(self.state)
        self.assertIsNotNone(confirmed)
        self.assertTrue(bool(confirmed and confirmed.changed))
        self.assertEqual(len(self.state.model.memos), 0)

    def test_apply_no_action_changes_nothing(self) -> None:
        action = VoiceAction(tool="no_action", args={"reason": "insufficient_intent"})
        result = apply_voice_action(self.state, action)
        self.assertFalse(result.changed)
        self.assertEqual(result.status, "done")
        self.assertGreater(len(self.state.model.reminders), 0)

    def test_apply_no_action_gemini_error_returns_error_status(self) -> None:
        action = VoiceAction(tool="no_action", args={"reason": "gemini_error:timeout"})
        result = apply_voice_action(self.state, action)
        self.assertFalse(result.changed)
        self.assertEqual(result.status, "error")
        self.assertIn("service is unavailable", result.message.lower())

    def test_apply_no_action_missing_item_has_guidance(self) -> None:
        action = VoiceAction(tool="no_action", args={"reason": "missing_item_name"})
        result = apply_voice_action(self.state, action)
        self.assertFalse(result.changed)
        self.assertEqual(result.status, "done")
        self.assertIn("item name", result.message.lower())

    def test_apply_voice_plan_partial_success(self) -> None:
        plan = VoicePlan(
            actions=[
                VoiceAction(tool="shopping_add_item", args={"item_name": "bread"}),
                VoiceAction(tool="timer_set", args={"duration_seconds": -1}),
                VoiceAction(tool="memo_add", args={"text": "晚点回家"}),
            ]
        )
        result = apply_voice_plan(self.state, plan, transcript="add bread and set bad timer and memo")
        self.assertEqual(result.status, "done")
        self.assertEqual(result.success_count, 2)
        self.assertEqual(result.failed_count, 1)
        titles = [r.title.lower() for r in self.state.model.reminders if r.category != "fridge"]
        self.assertIn("bread", titles)
        self.assertTrue(any("晚点回家" == m.text for m in self.state.model.memos))

    def test_apply_voice_plan_records_recent_action_groups(self) -> None:
        plan = parse_voice_plan(
            {
                "plan": {
                    "actions": [
                        {"tool": "shopping_add_item", "args": {"item_name": "bread"}},
                        {"tool": "memo_add", "args": {"text": "call mom"}},
                    ]
                }
            }
        )
        result = apply_voice_plan(self.state, plan, transcript="add bread and leave memo")
        self.assertEqual(result.status, "done")
        groups = list(self.state.ui.voice_recent_action_groups or [])
        self.assertGreaterEqual(len(groups), 1)
        top = dict(groups[0] or {})
        self.assertIn("actions", top)
        self.assertEqual(str(top.get("transcript") or ""), "add bread and leave memo")

    def test_apply_voice_plan_records_colloquial_multilingual_transcripts(self) -> None:
        utterances = [
            "Hey, can you add olive oil to the shopping list for me?",
            "Oye, agrega huevos y aceite a la lista de compras.",
            "Ajoute des oeufs et du lait a la liste, s'il te plait.",
        ]
        for i, transcript in enumerate(utterances):
            with self.subTest(transcript=transcript):
                plan = parse_voice_plan(
                    {
                        "plan": {
                            "actions": [
                                {"tool": "shopping_add_item", "args": {"item_name": f"item-{i}"}},
                            ]
                        }
                    }
                )
                result = apply_voice_plan(self.state, plan, transcript=transcript)
                self.assertEqual(result.status, "done")
                top = dict((self.state.ui.voice_recent_action_groups or [])[0] or {})
                self.assertEqual(str(top.get("transcript") or ""), transcript)

    def test_no_action_does_not_use_action_like_response_copy(self) -> None:
        plan = parse_voice_plan(
            {
                "plan": {
                    "actions": [
                        {"tool": "no_action", "args": {"reason": "missing_item_name"}},
                    ],
                    "response_copy": "OK. Milk has been removed from the shopping list.",
                    "needs_clarification": True,
                    "clarification": "Which milk?",
                }
            }
        )
        result = apply_voice_plan(self.state, plan, transcript="They have bought milk already.")
        self.assertFalse(result.changed)
        self.assertEqual(result.status, "done")
        self.assertNotIn("removed from the shopping list", result.message.lower())
        self.assertIn("which milk", result.message.lower())

    def test_no_action_message_uses_reason_specific_guidance(self) -> None:
        plan = parse_voice_plan(
            {
                "plan": {
                    "actions": [
                        {"tool": "no_action", "args": {"reason": "insufficient_context"}},
                    ],
                }
            }
        )
        result = apply_voice_plan(self.state, plan, transcript="do that again")
        self.assertFalse(result.changed)
        self.assertEqual(result.status, "done")
        self.assertIn("more context", result.message.lower())

    def test_skipped_non_no_action_uses_step_message_instead_of_generic_copy(self) -> None:
        plan = parse_voice_plan(
            {
                "plan": {
                    "actions": [
                        {"tool": "shopping_add_item", "args": {"item_name": "eggs"}},
                    ],
                }
            }
        )
        result = apply_voice_plan(self.state, plan, transcript="add eggs again")
        self.assertFalse(result.changed)
        self.assertIn("already in shopping", result.message.lower())
        self.assertNotIn("no actionable command", result.message.lower())

    def test_undo_and_redo_last_action_group(self) -> None:
        plan = parse_voice_plan(
            {
                "plan": {
                    "actions": [
                        {"tool": "shopping_add_item", "args": {"item_name": "bread"}},
                        {"tool": "memo_add", "args": {"text": "check oven"}},
                    ]
                }
            }
        )
        apply_voice_plan(self.state, plan, transcript="add bread and memo")
        self.assertEqual(len(self.state.ui.voice_done_action_groups), 1)
        self.assertEqual(len(self.state.ui.voice_redo_action_groups), 0)
        self.assertIn("bread", [r.title.lower() for r in self.state.model.reminders if r.category != "fridge"])
        self.assertTrue(any(m.text == "check oven" for m in self.state.model.memos))

        undo_result = apply_voice_action(self.state, VoiceAction(tool="undo_last_action_group", args={}))
        self.assertTrue(undo_result.changed)
        self.assertEqual(len(self.state.ui.voice_done_action_groups), 0)
        self.assertEqual(len(self.state.ui.voice_redo_action_groups), 1)
        self.assertNotIn("bread", [r.title.lower() for r in self.state.model.reminders if r.category != "fridge"])
        self.assertFalse(any(m.text == "check oven" for m in self.state.model.memos))

        redo_result = apply_voice_action(self.state, VoiceAction(tool="redo_last_action_group", args={}))
        self.assertTrue(redo_result.changed)
        self.assertEqual(len(self.state.ui.voice_done_action_groups), 1)
        self.assertEqual(len(self.state.ui.voice_redo_action_groups), 0)
        self.assertIn("bread", [r.title.lower() for r in self.state.model.reminders if r.category != "fridge"])
        self.assertTrue(any(m.text == "check oven" for m in self.state.model.memos))

    def test_redo_stack_cleared_after_new_committed_action(self) -> None:
        apply_voice_plan(
            self.state,
            parse_voice_plan({"plan": {"actions": [{"tool": "shopping_add_item", "args": {"item_name": "bread"}}]}}),
            transcript="add bread",
        )
        apply_voice_action(self.state, VoiceAction(tool="undo_last_action_group", args={}))
        self.assertEqual(len(self.state.ui.voice_redo_action_groups), 1)

        apply_voice_plan(
            self.state,
            parse_voice_plan({"plan": {"actions": [{"tool": "shopping_add_item", "args": {"item_name": "yogurt"}}]}}),
            transcript="add yogurt",
        )
        self.assertEqual(len(self.state.ui.voice_redo_action_groups), 0)
        redo_result = apply_voice_action(self.state, VoiceAction(tool="redo_last_action_group", args={}))
        self.assertFalse(redo_result.changed)
        self.assertIn("nothing to redo", redo_result.message.lower())

    def test_confirmed_clear_is_undoable(self) -> None:
        before_right = len([r for r in self.state.model.reminders if r.category != "fridge"])
        first = apply_voice_action(self.state, VoiceAction(tool="shopping_clear_all", args={}))
        self.assertEqual(first.status, "confirm")
        confirmed = confirm_pending_voice_action(self.state)
        self.assertIsNotNone(confirmed)
        self.assertTrue(bool(confirmed and confirmed.changed))
        self.assertEqual(len([r for r in self.state.model.reminders if r.category != "fridge"]), 0)
        self.assertEqual(len(self.state.ui.voice_done_action_groups), 1)

        undo_result = apply_voice_action(self.state, VoiceAction(tool="undo_last_action_group", args={}))
        self.assertTrue(undo_result.changed)
        self.assertEqual(len([r for r in self.state.model.reminders if r.category != "fridge"]), before_right)

    def test_build_request_meta_uses_caller_timezone_for_request_time(self) -> None:
        meta = build_request_meta(locale="en-US", tz_name="Asia/Shanghai")
        self.assertEqual(meta.timezone, "Asia/Shanghai")
        dt = datetime.fromisoformat(meta.request_time)
        self.assertEqual(dt.utcoffset(), timedelta(hours=8))

    def test_build_request_meta_generates_collision_resistant_request_id(self) -> None:
        m1 = build_request_meta(locale="en-US", tz_name="UTC")
        m2 = build_request_meta(locale="en-US", tz_name="UTC")
        self.assertNotEqual(m1.request_id, m2.request_id)
        self.assertTrue(m1.request_id.startswith("voice-"))
        self.assertRegex(m1.request_id, r"^voice-[0-9a-f]{32}$")

    def test_build_request_meta_defaults_locale_to_en_us(self) -> None:
        meta = build_request_meta(tz_name="UTC")
        self.assertEqual(meta.locale, "en-US")

    def test_reducer_back_cancels_pending_voice_confirmation(self) -> None:
        self.state.ui.voice_active = True
        self.state.ui.voice_phase = "confirm"
        self.state.ui.voice_message = "Press click once within 4s..."
        self.state.ui.voice_confirm_tool = "shopping_clear_all"
        self.state.ui.voice_confirm_payload_json = "{}"
        self.state.ui.voice_confirm_due_at = 1771617000.0
        self.state.ui.voice_confirm_before_snapshot = {"ui": {"timer_seconds": 10}}

        reduce(self.state, Back())

        self.assertFalse(self.state.ui.voice_active)
        self.assertEqual(self.state.ui.voice_phase, "idle")
        self.assertEqual(self.state.ui.voice_message, "")
        self.assertEqual(self.state.ui.voice_confirm_tool, "")
        self.assertEqual(self.state.ui.voice_confirm_payload_json, "")
        self.assertEqual(self.state.ui.voice_confirm_due_at, 0.0)
        self.assertEqual(self.state.ui.voice_confirm_before_snapshot, {})

    def test_reducer_back_cancels_pending_voice_confirmation_even_when_overlay_not_active(self) -> None:
        self.state.ui.voice_active = False
        self.state.ui.voice_confirm_tool = "inventory_clear_all"
        self.state.ui.voice_confirm_payload_json = "{}"
        self.state.ui.voice_confirm_due_at = 1771617000.0
        self.state.ui.voice_confirm_before_snapshot = {"model": {"reminders": []}}

        reduce(self.state, Back())

        self.assertEqual(self.state.ui.voice_confirm_tool, "")
        self.assertEqual(self.state.ui.voice_confirm_payload_json, "")
        self.assertEqual(self.state.ui.voice_confirm_due_at, 0.0)
        self.assertEqual(self.state.ui.voice_confirm_before_snapshot, {})


if __name__ == "__main__":
    unittest.main()
