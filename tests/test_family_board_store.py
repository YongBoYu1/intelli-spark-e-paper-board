from __future__ import annotations

import tempfile
import time
import unittest

from app.core.state import MemoItem
from app.data.family_board_store import (
    load_family_board,
    load_memo_items_from_rows,
    save_family_board,
)


class FamilyBoardStoreTests(unittest.TestCase):
    def test_load_rows_drops_expired_memos(self) -> None:
        now = time.time()
        rows = [
            {
                "mid": "m1",
                "text": "Dinner is ready",
                "author": "Mom",
                "timestamp": now - 20,
                "expiration_bucket": "1h",
                "expires_at": now + 3600,
            },
            {
                "mid": "m2",
                "text": "Old note",
                "author": "Dad",
                "timestamp": now - 5000,
                "expiration_bucket": "1h",
                "expires_at": now - 5,
            },
        ]

        memos = load_memo_items_from_rows(rows, timezone_name="America/Toronto")

        self.assertEqual(len(memos), 1)
        self.assertEqual(memos[0].mid, "m1")
        self.assertEqual(memos[0].expiration_bucket, "1h")

    def test_save_and_load_roundtrip(self) -> None:
        now = time.time()
        memos = [
            MemoItem(
                mid="m1",
                text="Back late tonight",
                author="Voice",
                timestamp=now,
                is_new=True,
                expiration_bucket="end_of_day",
                expires_at=now + 3600,
            )
        ]

        with tempfile.TemporaryDirectory() as td:
            save_family_board(td, memos)
            loaded = load_family_board(td, timezone_name="America/Toronto")

        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0].text, "Back late tonight")
        self.assertEqual(loaded[0].author, "Voice")
        self.assertEqual(loaded[0].expiration_bucket, "end_of_day")
        self.assertEqual(loaded[0].expires_at, memos[0].expires_at)


if __name__ == "__main__":
    unittest.main()
