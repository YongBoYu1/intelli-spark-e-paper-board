from __future__ import annotations

import unittest

from PIL import Image

import tools.run_epaper_console as rec


class _FakeEpd:
    def __init__(self):
        self.mode = "full"
        self.partial_call = None

    def init_part(self):
        self.mode = "part"

    def init_fast(self):
        self.mode = "fast"

    def init(self):
        self.mode = "full"

    def display_Partial(self, image, x0, y0, x1, y1):
        self.partial_call = (image, x0, y0, x1, y1)


class RunEpaperConsolePartialTests(unittest.TestCase):
    def test_blit_partial_uses_end_coords_and_partial_buffer(self) -> None:
        epd = _FakeEpd()
        frame = Image.new("1", (800, 480), 255)
        frame.putpixel((24, 100), 0)
        frame.putpixel((31, 100), 0)
        rect = (24, 100, 224, 160)  # width=200, height=60 => bytes=1500

        mode = rec._blit_partial(epd, frame, rect, current_mode="full")

        self.assertEqual(mode, "part")
        self.assertIsNotNone(epd.partial_call)
        payload, x0, y0, x1, y1 = epd.partial_call
        self.assertEqual((x0, y0, x1, y1), rect)

        expected_len = ((x1 - x0) // 8) * (y1 - y0)
        self.assertEqual(len(payload), expected_len)

        expected = bytearray(frame.crop(rect).convert("1").tobytes("raw"))
        self.assertEqual(payload, expected)


if __name__ == "__main__":
    unittest.main()
