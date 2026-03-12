from __future__ import annotations

import os
import unittest
from unittest.mock import patch

import backend.voice_api.service as voice_service

from backend.voice_api.service import (
    _validate_plan_against_schema,
    interpret_request,
    interpret_request_with_debug,
    normalize_action,
    normalize_plan,
)


class VoiceServiceNormalizeTests(unittest.TestCase):
    def test_inventory_normalization(self) -> None:
        raw = {
            "tool": "inventory_log_event",
            "args": {
                "item_name": "leche",
                "event_type": "consumed",
                "effective_date": "2026-02-19",
            },
        }
        action = normalize_action(raw, request_time="2026-02-20T10:00:00+08:00")
        self.assertEqual(action["tool"], "inventory_log_event")
        self.assertEqual(action["args"]["item_name"], "leche")

    def test_shopping_normalization(self) -> None:
        raw = {"tool": "shopping_add_item", "args": {"item_name": "oeufs"}}
        action = normalize_action(raw, request_time="2026-02-20T10:00:00+08:00")
        self.assertEqual(action["tool"], "shopping_add_item")
        self.assertEqual(action["args"]["item_name"], "oeufs")

    def test_invalid_tool_becomes_no_action(self) -> None:
        raw = {"tool": "unknown_tool", "args": {}}
        action = normalize_action(raw, request_time="2026-02-20T10:00:00+08:00")
        self.assertEqual(action["tool"], "no_action")

    def test_open_app_normalization(self) -> None:
        action = normalize_action({"tool": "open_app", "args": {"app": "timer"}}, request_time="2026-02-20T10:00:00+08:00")
        self.assertEqual(action, {"tool": "open_app", "args": {"app": "timer"}})

    def test_open_app_invalid_name(self) -> None:
        action = normalize_action({"tool": "open_app", "args": {"app": "minuterie"}}, request_time="2026-02-20T10:00:00+08:00")
        self.assertEqual(action["tool"], "no_action")
        self.assertEqual(action["args"]["reason"], "invalid_app_name")

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
        raw = {"tool": "shopping_remove_item", "args": {"item_name": "milk"}}
        action = normalize_action(raw, request_time="2026-02-20T10:00:00+08:00")
        self.assertEqual(action["tool"], "shopping_remove_item")
        self.assertEqual(action["args"]["item_name"], "milk")

    def test_shopping_remove_normalization_keeps_inventory_source_for_item_name(self) -> None:
        raw = {"tool": "shopping_remove_item", "args": {"item_name": "milk", "source": "inventory"}}
        action = normalize_action(raw, request_time="2026-02-20T10:00:00+08:00")
        self.assertEqual(action["tool"], "shopping_remove_item")
        self.assertEqual(action["args"]["item_name"], "milk")
        self.assertEqual(action["args"]["source"], "inventory")

    def test_shopping_remove_rejects_invalid_source_for_item_name(self) -> None:
        raw = {"tool": "shopping_remove_item", "args": {"item_name": "milk", "source": "shopping"}}
        action = normalize_action(raw, request_time="2026-02-20T10:00:00+08:00")
        self.assertEqual(action["tool"], "no_action")
        self.assertEqual(action["args"]["reason"], "invalid_remove_source")

    def test_shopping_remove_positional_normalization(self) -> None:
        raw = {
            "tool": "shopping_remove_item",
            "args": {"source": "inventory", "position_mode": "first", "count": 2},
        }
        action = normalize_action(raw, request_time="2026-02-20T10:00:00+08:00")
        self.assertEqual(action["tool"], "shopping_remove_item")
        self.assertEqual(action["args"]["source"], "inventory")
        self.assertEqual(action["args"]["position_mode"], "first")
        self.assertEqual(action["args"]["count"], 2)

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
            "args": {"item_name": "leche", "expiry_date": "2026-03-27"},
        }
        action = normalize_action(raw, request_time="2026-02-20T10:00:00+08:00")
        self.assertEqual(action["tool"], "inventory_set_expiry")
        self.assertEqual(action["args"]["item_name"], "leche")
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

    def test_timer_controls_normalization(self) -> None:
        pause = normalize_action({"tool": "timer_pause", "args": {"unexpected": True}}, request_time="2026-02-20T10:00:00+08:00")
        resume = normalize_action({"tool": "timer_resume", "args": {"unexpected": True}}, request_time="2026-02-20T10:00:00+08:00")
        stop = normalize_action({"tool": "timer_stop", "args": {"unexpected": True}}, request_time="2026-02-20T10:00:00+08:00")
        add = normalize_action({"tool": "timer_add", "args": {"delta_seconds": 90}}, request_time="2026-02-20T10:00:00+08:00")
        self.assertEqual((pause.get("tool"), pause.get("args")), ("timer_pause", {}))
        self.assertEqual((resume.get("tool"), resume.get("args")), ("timer_resume", {}))
        self.assertEqual((stop.get("tool"), stop.get("args")), ("timer_stop", {}))
        self.assertEqual(add.get("tool"), "timer_add")
        self.assertEqual((add.get("args") or {}).get("delta_seconds"), 90)

    def test_memo_add_normalization(self) -> None:
        raw = {"tool": "memo_add", "args": {"content": "Back late tonight", "author": "Alex"}}
        action = normalize_action(raw, request_time="2026-02-20T10:00:00+08:00")
        self.assertEqual(action["tool"], "memo_add")
        self.assertEqual(action["args"]["text"], "Back late tonight")
        self.assertEqual(action["args"]["author"], "Alex")

    def test_memo_target_author_normalization(self) -> None:
        raw = {"tool": "memo_delete", "args": {"target": "author", "author": "Dad"}}
        action = normalize_action(raw, request_time="2026-02-20T10:00:00+08:00")
        self.assertEqual(action["tool"], "memo_delete")
        self.assertEqual(action["args"]["target"], "author")
        self.assertEqual(action["args"]["author"], "Dad")

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
                    {"tool": "shopping_add_item", "args": {"item_name": "eggs"}},
                    {"tool": "memo_add", "args": {"text": "Back late tonight", "author": "Alex"}},
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

    def test_missing_item_name_no_action_is_preserved(self) -> None:
        raw = {
            "tool": "plan_actions",
            "args": {"actions": [{"tool": "no_action", "args": {"reason": "missing_item_name"}}]},
        }
        plan = normalize_plan(raw, request_time="2026-03-03T14:30:00-05:00")
        self.assertEqual(plan["actions"], [{"tool": "no_action", "args": {"reason": "missing_item_name"}}])


class VoiceServiceColloquialFlowTests(unittest.TestCase):
    def test_interpret_retries_no_action_once_with_low_risk_tools(self) -> None:
        call_log: list[tuple[str | None, str]] = []

        def fake_call(*, retry_mode: str = "", allowed_tools: set[str] | None = None, **_: object) -> dict[str, object]:
            call_log.append((retry_mode or "", "none" if allowed_tools is None else ",".join(sorted(allowed_tools))))
            if len(call_log) == 1:
                return {"tool": "no_action", "args": {"reason": "insufficient_intent"}}
            return {"tool": "shopping_remove_item", "args": {"source": "reminders", "position_mode": "first", "count": 2}}

        with patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key", "GEMINI_MODEL": "test-model"}, clear=False):
            with patch.object(
                voice_service,
                "_call_gemini_for_action",
                side_effect=fake_call,
            ):
                with patch.object(voice_service, "_apply_scope_corrections", side_effect=lambda *, transcript, scope_id: transcript):
                    got = interpret_request_with_debug(
                        {
                            "request_id": "voice-check-repair-1",
                            "request_time": "2026-03-12T10:00:00-05:00",
                            "timezone": "America/Toronto",
                            "locale": "en-US",
                            "transcript": "Check the first two items on the reminder.",
                        }
                    )

        self.assertEqual(len(call_log), 2)
        self.assertEqual(call_log[0][0], "")
        self.assertEqual(call_log[1][0], "no_action_low_risk")
        self.assertIn("shopping_remove_item", call_log[1][1])
        self.assertNotIn("shopping_clear_all", call_log[1][1])
        self.assertEqual(got["action"]["tool"], "shopping_remove_item")
        self.assertEqual(got["action"]["args"]["source"], "reminders")
        self.assertEqual(got["action"]["args"]["position_mode"], "first")
        self.assertEqual(got["action"]["args"]["count"], 2)

    def test_interpret_retry_stays_no_action_when_retry_returns_high_risk_tool(self) -> None:
        call_count = 0

        def fake_call(**_: object) -> dict[str, object]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {"tool": "no_action", "args": {"reason": "insufficient_intent"}}
            return {"tool": "memo_clear_all", "args": {}}

        with patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key", "GEMINI_MODEL": "test-model"}, clear=False):
            with patch.object(
                voice_service,
                "_call_gemini_for_action",
                side_effect=fake_call,
            ):
                with patch.object(voice_service, "_apply_scope_corrections", side_effect=lambda *, transcript, scope_id: transcript):
                    got = interpret_request_with_debug(
                        {
                            "request_id": "voice-check-repair-2",
                            "request_time": "2026-03-12T10:00:00-05:00",
                            "timezone": "America/Toronto",
                            "locale": "en-US",
                            "transcript": "Tick off the last item in inventory.",
                        }
                    )

        self.assertEqual(call_count, 2)
        self.assertEqual(got["action"]["tool"], "no_action")

    def test_interpret_does_not_retry_blocked_no_action_reason(self) -> None:
        call_count = 0

        def fake_call(**_: object) -> dict[str, object]:
            nonlocal call_count
            call_count += 1
            return {"tool": "no_action", "args": {"reason": "missing_google_api_key"}}

        with patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key", "GEMINI_MODEL": "test-model"}, clear=False):
            with patch.object(
                voice_service,
                "_call_gemini_for_action",
                side_effect=fake_call,
            ):
                with patch.object(voice_service, "_apply_scope_corrections", side_effect=lambda *, transcript, scope_id: transcript):
                    got = interpret_request_with_debug(
                        {
                            "request_id": "voice-check-repair-3",
                            "request_time": "2026-03-12T10:00:00-05:00",
                            "timezone": "America/Toronto",
                            "locale": "en-US",
                            "transcript": "Check weather for tomorrow.",
                        }
                    )

        self.assertEqual(call_count, 1)
        self.assertEqual(got["action"]["tool"], "no_action")

    def test_interpret_colloquial_transcripts_forward_runtime_locale(self) -> None:
        scenarios = [
            {
                "locale": "en-US",
                "transcript": "Hey, we're out of eggs and olive oil, can you add both to the shopping list?",
                "raw": {"actions": [{"tool": "shopping_add_item", "args": {"item_name": "eggs"}}, {"tool": "shopping_add_item", "args": {"item_name": "olive oil"}}]},
                "first_tool": "shopping_add_item",
            },
            {
                "locale": "en-US",
                "transcript": "Could you add a minute and a half to the timer?",
                "raw": {"tool": "timer_add", "args": {"add_seconds": "90"}},
                "first_tool": "timer_add",
            },
            {
                "locale": "es-ES",
                "transcript": "Oye, borra los dos primeros del inventario, por favor.",
                "raw": {"tool": "shopping_remove_item", "args": {"source": "inventory", "position_mode": "first", "count": 2}},
                "first_tool": "shopping_remove_item",
            },
            {
                "locale": "fr-CA",
                "transcript": "Je rentre tard ce soir, laisse un memo pour la famille.",
                "raw": {"tool": "memo_add", "args": {"content": "Je rentre tard ce soir", "author": "Alex"}},
                "first_tool": "memo_add",
            },
        ]

        call_log: list[tuple[str, str]] = []
        scenario_by_transcript = {s["transcript"]: s for s in scenarios}

        def fake_call(*, transcript: str, locale: str, **_: object) -> dict[str, object]:
            call_log.append((transcript, locale))
            row = scenario_by_transcript.get(transcript)
            if row is None:
                return {"tool": "no_action", "args": {"reason": "insufficient_intent"}}
            return dict(row["raw"])

        with patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key", "GEMINI_MODEL": "test-model"}, clear=False):
            with patch.object(voice_service, "_call_gemini_for_action", side_effect=fake_call):
                with patch.object(voice_service, "_apply_scope_corrections", side_effect=lambda *, transcript, scope_id: transcript):
                    for i, row in enumerate(scenarios):
                        payload = {
                            "request_id": f"voice-colloquial-{i}",
                            "request_time": "2026-03-12T10:00:00-05:00",
                            "timezone": "America/Toronto",
                            "locale": row["locale"],
                            "transcript": row["transcript"],
                        }
                        got = interpret_request_with_debug(payload)
                        self.assertEqual(got["action"]["tool"], row["first_tool"])

        self.assertEqual(len(call_log), len(scenarios))
        for row, logged in zip(scenarios, call_log):
            self.assertEqual(logged[0], row["transcript"])
            self.assertEqual(logged[1], row["locale"])

    def test_interpret_audio_path_uses_audio_interpreter_first(self) -> None:
        captured: dict[str, str] = {}

        def fake_audio_call(*, locale: str, retry_mode: str = "", allowed_tools: set[str] | None = None, **_: object) -> dict[str, object]:
            captured["audio_locale"] = locale
            captured["retry_mode"] = retry_mode
            captured["has_allowed_tools"] = "yes" if allowed_tools is not None else "no"
            return {"tool": "shopping_remove_item", "args": {"source": "inventory", "position_mode": "first", "count": 2}}

        with patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key", "GEMINI_MODEL": "test-model"}, clear=False):
            with patch.object(voice_service, "_decode_audio_base64_to_temp", return_value="/tmp/voice-audio-locale.wav"):
                with patch.object(voice_service, "_transcribe_audio_via_gemini") as transcribe_mock:
                    with patch.object(voice_service, "_call_gemini_for_action_from_audio", side_effect=fake_audio_call):
                        got = interpret_request_with_debug(
                            {
                                "request_id": "voice-audio-locale-1",
                                "request_time": "2026-03-12T10:00:00-05:00",
                                "timezone": "America/Toronto",
                                "locale": "es-ES",
                                "audio_base64": "ZmFrZQ==",
                            }
                        )

        self.assertEqual(captured.get("audio_locale"), "es-ES")
        self.assertEqual(captured.get("retry_mode"), "")
        self.assertEqual(captured.get("has_allowed_tools"), "no")
        self.assertEqual(got["action"]["tool"], "shopping_remove_item")
        transcribe_mock.assert_not_called()

    def test_interpret_audio_no_action_triggers_low_risk_audio_retry(self) -> None:
        captured: dict[str, object] = {"calls": []}

        def fake_audio_call(*, locale: str, retry_mode: str = "", allowed_tools: set[str] | None = None, **_: object) -> dict[str, object]:
            calls = captured["calls"]
            if isinstance(calls, list):
                calls.append((locale, retry_mode, None if allowed_tools is None else sorted(allowed_tools)))
                if len(calls) == 1:
                    return {"tool": "no_action", "args": {"reason": "insufficient_intent"}}
            return {"tool": "shopping_remove_item", "args": {"source": "reminders", "position_mode": "first", "count": 2}}

        with patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key", "GEMINI_MODEL": "test-model"}, clear=False):
            with patch.object(voice_service, "_decode_audio_base64_to_temp", return_value="/tmp/voice-audio-fallback.wav"):
                with patch.object(voice_service, "_call_gemini_for_action_from_audio", side_effect=fake_audio_call):
                    got = interpret_request_with_debug(
                        {
                            "request_id": "voice-audio-locale-2",
                            "request_time": "2026-03-12T10:00:00-05:00",
                            "timezone": "America/Toronto",
                            "locale": "fr-CA",
                            "audio_base64": "ZmFrZQ==",
                        }
                    )

        calls = list(captured.get("calls") or [])
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][0], "fr-CA")
        self.assertEqual(calls[0][1], "")
        self.assertIsNone(calls[0][2])
        self.assertEqual(calls[1][0], "fr-CA")
        self.assertEqual(calls[1][1], "no_action_low_risk")
        self.assertTrue(isinstance(calls[1][2], list))
        self.assertIn("shopping_remove_item", calls[1][2])
        self.assertNotIn("shopping_clear_all", calls[1][2])
        self.assertEqual(got["action"]["tool"], "shopping_remove_item")


if __name__ == "__main__":
    unittest.main()
