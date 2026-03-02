from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from backend.voice_api.correction_kb import CorrectionKB


class CorrectionKBTests(unittest.TestCase):
    def test_upsert_and_apply_with_persistence(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "kb.json"
            kb = CorrectionKB(str(path))
            changed = kb.upsert(scope_id="home-a", wrong="酒戒", correct="酒街")
            self.assertTrue(changed)

            out, hits = kb.apply("我有从酒戒打包回来的烧烤", scope_id="home-a")
            self.assertEqual(out, "我有从酒街打包回来的烧烤")
            self.assertEqual(len(hits), 1)
            self.assertEqual(hits[0]["wrong"], "酒戒")

            kb2 = CorrectionKB(str(path))
            out2, hits2 = kb2.apply("酒戒那家", scope_id="home-a")
            self.assertEqual(out2, "酒街那家")
            self.assertEqual(len(hits2), 1)

    def test_scope_isolation(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "kb.json"
            kb = CorrectionKB(str(path))
            kb.upsert(scope_id="home-a", wrong="酒戒", correct="酒街")
            out_a, _ = kb.apply("酒戒", scope_id="home-a")
            out_b, _ = kb.apply("酒戒", scope_id="home-b")
            self.assertEqual(out_a, "酒街")
            self.assertEqual(out_b, "酒戒")

    def test_ascii_alias_uses_word_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "kb.json"
            kb = CorrectionKB(str(path))
            kb.upsert(scope_id="home-a", wrong="ham", correct="spam")
            out, hits = kb.apply("champagne ham Ham hAm", scope_id="home-a")
            self.assertEqual(out, "champagne spam spam spam")
            self.assertEqual(len(hits), 1)
            self.assertEqual(hits[0]["count"], 3)

    def test_latin_alias_with_punctuation_is_case_insensitive(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "kb.json"
            kb = CorrectionKB(str(path))
            kb.upsert(scope_id="home-a", wrong="wendy's", correct="Wendy's")
            out, hits = kb.apply("leftover WENDY'S in the fridge", scope_id="home-a")
            self.assertEqual(out, "leftover Wendy's in the fridge")
            self.assertEqual(len(hits), 1)
            self.assertEqual(hits[0]["count"], 1)

            out2, hits2 = kb.apply("leftover WENDY’S in the fridge", scope_id="home-a")
            self.assertEqual(out2, "leftover Wendy's in the fridge")
            self.assertEqual(len(hits2), 1)
            self.assertEqual(hits2[0]["count"], 1)

    def test_apply_unknown_scope_does_not_create_scope(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "kb.json"
            kb = CorrectionKB(str(path))
            kb.apply("hello", scope_id="unknown")
            kb._load_if_needed()
            scopes = kb._data.get("scopes")
            self.assertIsInstance(scopes, dict)
            self.assertEqual(len(scopes), 0)

    def test_scope_and_alias_limits_are_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "kb.json"
            old_scopes = os.environ.get("VOICE_CORRECTION_KB_MAX_SCOPES")
            old_aliases = os.environ.get("VOICE_CORRECTION_KB_MAX_ALIASES_PER_SCOPE")
            try:
                os.environ["VOICE_CORRECTION_KB_MAX_SCOPES"] = "1"
                os.environ["VOICE_CORRECTION_KB_MAX_ALIASES_PER_SCOPE"] = "1"
                kb = CorrectionKB(str(path))
                self.assertTrue(kb.upsert(scope_id="home-a", wrong="a", correct="aa"))
                self.assertFalse(kb.upsert(scope_id="home-a", wrong="b", correct="bb"))
                self.assertFalse(kb.upsert(scope_id="home-b", wrong="c", correct="cc"))
            finally:
                if old_scopes is None:
                    os.environ.pop("VOICE_CORRECTION_KB_MAX_SCOPES", None)
                else:
                    os.environ["VOICE_CORRECTION_KB_MAX_SCOPES"] = old_scopes
                if old_aliases is None:
                    os.environ.pop("VOICE_CORRECTION_KB_MAX_ALIASES_PER_SCOPE", None)
                else:
                    os.environ["VOICE_CORRECTION_KB_MAX_ALIASES_PER_SCOPE"] = old_aliases

    def test_term_length_limit_is_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "kb.json"
            old_max = os.environ.get("VOICE_CORRECTION_KB_MAX_TERM_LEN")
            try:
                os.environ["VOICE_CORRECTION_KB_MAX_TERM_LEN"] = "8"
                kb = CorrectionKB(str(path))
                self.assertFalse(kb.upsert(scope_id="home-a", wrong="very-long-term", correct="short"))
                self.assertFalse(kb.upsert(scope_id="home-a", wrong="short", correct="very-long-term"))
                self.assertTrue(kb.upsert(scope_id="home-a", wrong="short", correct="fixed"))
            finally:
                if old_max is None:
                    os.environ.pop("VOICE_CORRECTION_KB_MAX_TERM_LEN", None)
                else:
                    os.environ["VOICE_CORRECTION_KB_MAX_TERM_LEN"] = old_max


if __name__ == "__main__":
    unittest.main()
