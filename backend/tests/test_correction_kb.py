from __future__ import annotations

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


if __name__ == "__main__":
    unittest.main()
