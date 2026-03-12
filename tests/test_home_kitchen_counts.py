from __future__ import annotations

import unittest

from app.core.state import Reminder
from app.ui.home_kitchen import _open_item_count


class HomeKitchenCountTests(unittest.TestCase):
    def test_open_item_count_excludes_completed_rows(self) -> None:
        rows = [
            Reminder(rid="r1", title="A", right="", category="general", completed=False),
            Reminder(rid="r2", title="B", right="", category="general", completed=True),
            Reminder(rid="r3", title="C", right="", category="fridge", completed=False),
            Reminder(rid="r4", title="D", right="", category="fridge", completed=True),
        ]
        self.assertEqual(_open_item_count(rows), 2)


if __name__ == "__main__":
    unittest.main()
