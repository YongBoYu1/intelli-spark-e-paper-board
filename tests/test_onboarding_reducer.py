from __future__ import annotations

import unittest

from app.core.reducer import Back, Click, Rotate, Tick, apply_onboarding_voice_demo_result, open_onboarding_voice_guide, reduce
from app.core.state import AppState, DashboardModel, Screen


class OnboardingReducerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.state = AppState(model=DashboardModel())

    def test_landing_requires_rotate_and_single_click_before_onboarding(self) -> None:
        self.state.ui.screen = Screen.LANDING
        self.state.ui.setup_completed = False
        self.state.ui.boot_started_at = 100.0
        self.state.ui.boot_min_show_s = 2.0

        # Tick alone should not enter onboarding.
        reduce(self.state, Tick(now=102.2), theme={})
        self.assertEqual(self.state.ui.screen, Screen.LANDING)

        # Rotate + first click enters onboarding.
        reduce(self.state, Rotate(+1), theme={})
        reduce(self.state, Click(), theme={})
        self.assertEqual(self.state.ui.screen, Screen.ONBOARDING)
        self.assertEqual(self.state.ui.onboarding_step, "start")

    def test_landing_click_before_rotate_stays_on_landing(self) -> None:
        self.state.ui.screen = Screen.LANDING
        self.state.ui.setup_completed = False
        self.state.ui.boot_started_at = 100.0
        self.state.ui.boot_min_show_s = 0.0

        reduce(self.state, Click(), theme={})
        self.assertEqual(self.state.ui.screen, Screen.LANDING)
        self.assertIn("Rotate to choose language", str(self.state.ui.landing_status))

    def test_landing_rotate_cycles_voice_locale(self) -> None:
        self.state.ui.screen = Screen.LANDING
        self.state.ui.setup_completed = False
        self.state.ui.boot_started_at = 100.0
        self.state.ui.boot_min_show_s = 0.0
        self.state.ui.voice_locale = "en-US"
        self.state.ui.landing_confirm_seen = False

        reduce(self.state, Rotate(+1), theme={})
        self.assertEqual(self.state.ui.voice_locale, "es-ES")

        reduce(self.state, Rotate(+1), theme={})
        self.assertEqual(self.state.ui.voice_locale, "fr-FR")

        reduce(self.state, Rotate(+1), theme={})
        self.assertEqual(self.state.ui.voice_locale, "en-US")

    def test_landing_tick_routes_to_home_when_setup_done(self) -> None:
        self.state.ui.screen = Screen.LANDING
        self.state.ui.setup_completed = True
        self.state.ui.boot_started_at = 100.0
        self.state.ui.boot_min_show_s = 2.0

        reduce(self.state, Tick(now=103.0), theme={})

        self.assertEqual(self.state.ui.screen, Screen.HOME)

    def test_onboarding_start_rotate_and_skip(self) -> None:
        self.state.ui.screen = Screen.ONBOARDING
        self.state.ui.onboarding_step = "start"
        self.state.ui.onboarding_focus_index = 0

        reduce(self.state, Rotate(+1), theme={})
        self.assertEqual(self.state.ui.onboarding_focus_index, 1)

        reduce(self.state, Click(), theme={})
        self.assertEqual(self.state.ui.onboarding_step, "prefs")

    def test_onboarding_qr_done_moves_to_prefs_and_sets_wifi(self) -> None:
        self.state.ui.screen = Screen.ONBOARDING
        self.state.ui.onboarding_step = "pair_qr"
        self.state.ui.onboarding_qr_focus_index = 1  # I am done

        reduce(self.state, Click(), theme={})

        self.assertEqual(self.state.ui.onboarding_step, "prefs")
        self.assertTrue(self.state.ui.wifi_enabled)
        self.assertNotEqual(str(self.state.ui.onboarding_wifi_ssid or "").strip(), "")

    def test_onboarding_prefs_toggle_finish_and_enter_home(self) -> None:
        self.state.ui.screen = Screen.ONBOARDING
        self.state.ui.onboarding_step = "prefs"
        self.state.ui.device_language = "en-US"
        self.state.ui.voice_locale = "en-US"
        self.state.ui.auto_sync_enabled = True

        # Toggle language
        self.state.ui.onboarding_prefs_focus_index = 0
        reduce(self.state, Click(), theme={})
        self.assertEqual(self.state.ui.device_language, "es-ES")
        self.assertEqual(self.state.ui.voice_locale, "es-ES")

        # Toggle timezone
        tz_before = str(self.state.ui.device_timezone)
        self.state.ui.onboarding_prefs_focus_index = 1
        reduce(self.state, Click(), theme={})
        self.assertNotEqual(str(self.state.ui.device_timezone), tz_before)

        # Toggle auto sync
        self.state.ui.onboarding_prefs_focus_index = 2
        reduce(self.state, Click(), theme={})
        self.assertFalse(self.state.ui.auto_sync_enabled)

        # Open voice guide from prefs
        self.state.ui.onboarding_prefs_focus_index = 3
        reduce(self.state, Click(), theme={})
        self.assertEqual(self.state.ui.onboarding_step, "voice_guide")

        # Mark all 3 samples consumed, then continue.
        self.state.ui.onboarding_voice_demo_case_index = 3
        self.state.ui.onboarding_voice_demo_pass_mask = 0b111
        self.state.ui.onboarding_voice_guide_focus_index = 0
        reduce(self.state, Click(), theme={})
        self.assertEqual(self.state.ui.onboarding_step, "done")

        # Enter home from done page
        reduce(self.state, Click(), theme={})
        self.assertTrue(self.state.ui.setup_completed)
        self.assertEqual(self.state.ui.screen, Screen.HOME)

    def test_onboarding_back_from_qr_returns_to_start(self) -> None:
        self.state.ui.screen = Screen.ONBOARDING
        self.state.ui.onboarding_step = "pair_qr"

        reduce(self.state, Back(), theme={})

        self.assertEqual(self.state.ui.onboarding_step, "start")

    def test_onboarding_back_from_voice_guide_returns_to_prefs(self) -> None:
        self.state.ui.screen = Screen.ONBOARDING
        self.state.ui.onboarding_step = "voice_guide"
        self.state.ui.onboarding_prefs_focus_index = 3

        reduce(self.state, Back(), theme={})

        self.assertEqual(self.state.ui.onboarding_step, "prefs")
        self.assertEqual(self.state.ui.onboarding_prefs_focus_index, 3)

    def test_enter_voice_guide_sets_demo_prompt(self) -> None:
        self.state.ui.screen = Screen.ONBOARDING
        self.state.ui.onboarding_step = "prefs"
        self.state.ui.onboarding_prefs_focus_index = 3

        reduce(self.state, Click(), theme={})

        self.assertEqual(self.state.ui.onboarding_step, "voice_guide")
        self.assertIn("Add milk to inventory", str(self.state.ui.onboarding_status))
        self.assertEqual(int(self.state.ui.onboarding_voice_guide_focus_index), 0)

    def test_open_voice_guide_direct_resets_demo_state(self) -> None:
        self.state.ui.screen = Screen.HOME
        self.state.ui.onboarding_voice_demo_case_index = 2
        self.state.ui.onboarding_voice_demo_pass_mask = 0b011
        self.state.ui.onboarding_voice_demo_heard = "stale"

        open_onboarding_voice_guide(self.state)

        self.assertEqual(self.state.ui.screen, Screen.ONBOARDING)
        self.assertEqual(self.state.ui.onboarding_step, "voice_guide")
        self.assertEqual(int(self.state.ui.onboarding_voice_demo_case_index), 0)
        self.assertEqual(int(self.state.ui.onboarding_voice_demo_pass_mask), 0)
        self.assertEqual(str(self.state.ui.onboarding_voice_demo_heard or ""), "")

    def test_voice_guide_click_skips_when_not_complete(self) -> None:
        self.state.ui.screen = Screen.ONBOARDING
        self.state.ui.onboarding_step = "voice_guide"
        self.state.ui.onboarding_voice_guide_focus_index = 0

        reduce(self.state, Click(), theme={})
        self.assertEqual(self.state.ui.onboarding_step, "voice_guide")
        self.assertEqual(int(self.state.ui.onboarding_voice_demo_case_index), 1)

        reduce(self.state, Click(), theme={})
        self.assertEqual(int(self.state.ui.onboarding_voice_demo_case_index), 2)

        reduce(self.state, Click(), theme={})
        self.assertEqual(int(self.state.ui.onboarding_voice_demo_case_index), 3)
        self.assertIn("completed", str(self.state.ui.onboarding_status).lower())

        reduce(self.state, Click(), theme={})
        self.assertEqual(self.state.ui.onboarding_step, "done")

    def test_voice_guide_demo_result_advances_three_samples(self) -> None:
        self.state.ui.screen = Screen.ONBOARDING
        self.state.ui.onboarding_step = "voice_guide"

        apply_onboarding_voice_demo_result(self.state, "add milk to inventory")
        self.assertEqual(int(self.state.ui.onboarding_voice_demo_case_index), 1)
        self.assertEqual(int(self.state.ui.onboarding_voice_demo_pass_mask), 0b001)

        apply_onboarding_voice_demo_result(self.state, "remind me to check fridge tonight")
        self.assertEqual(int(self.state.ui.onboarding_voice_demo_case_index), 2)
        self.assertEqual(int(self.state.ui.onboarding_voice_demo_pass_mask), 0b011)

        apply_onboarding_voice_demo_result(self.state, "set a timer for ten minutes")
        self.assertEqual(int(self.state.ui.onboarding_voice_demo_case_index), 3)
        self.assertEqual(int(self.state.ui.onboarding_voice_demo_pass_mask), 0b111)
        self.assertEqual(int(self.state.ui.onboarding_voice_guide_focus_index), 0)


if __name__ == "__main__":
    unittest.main()
