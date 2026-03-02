from __future__ import annotations

import unittest

from app.core.state import AppState, DashboardModel
from app.ui.app import _voice_summary_text


class VoiceUiCopyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.state = AppState(model=DashboardModel())

    def test_ready_copy(self) -> None:
        got = _voice_summary_text(self.state, "READY", "", active=False)
        self.assertEqual(got, "Hold to talk")

    def test_listening_copy(self) -> None:
        got = _voice_summary_text(self.state, "LISTENING", "", active=True)
        self.assertEqual(got, "Go ahead...")

    def test_processing_shows_heard_preview(self) -> None:
        msg = "Heard: add milk to shopping list"
        got = _voice_summary_text(self.state, "PROCESSING", msg, active=True)
        self.assertTrue(got.startswith("Heard: add milk"))
        self.assertTrue(got.endswith("..."))

    def test_confirm_shows_natural_action_prompt(self) -> None:
        self.state.ui.voice_confirm_tool = "shopping_clear_all"
        got = _voice_summary_text(self.state, "CONFIRM", "", active=True)
        self.assertEqual(got, "Clear shopping list? Enter")

    def test_done_result_is_humanized(self) -> None:
        msg = "Result: Added to shopping: Milk"
        got = _voice_summary_text(self.state, "DONE", msg, active=True)
        self.assertEqual(got, "Added Milk")

    def test_skipped_copy(self) -> None:
        msg = "Result: Skipped: no actionable command"
        got = _voice_summary_text(self.state, "SKIPPED", msg, active=True)
        self.assertEqual(got, "No change")

    def test_error_copy(self) -> None:
        got = _voice_summary_text(self.state, "ERROR", "Result: backend timeout", active=True)
        self.assertEqual(got, "Didn't catch that")


if __name__ == "__main__":
    unittest.main()

