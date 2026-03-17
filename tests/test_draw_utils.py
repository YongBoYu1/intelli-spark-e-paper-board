from __future__ import annotations

import unittest

from PIL import Image, ImageDraw, ImageFont

from app.shared.draw import draw_strikethrough


class DrawUtilsTests(unittest.TestCase):
    def test_draw_strikethrough_uses_rendered_text_bbox(self) -> None:
        image = Image.new("L", (160, 48), 255)
        draw = ImageDraw.Draw(image)
        font = ImageFont.load_default()

        x = 12
        y = 10
        text = "Reminder"

        bbox = draw.textbbox((x, y), text, font=font)
        got = draw_strikethrough(draw, text, x, y, font, fill=0, width=1)

        self.assertIsNotNone(got)
        assert got is not None
        expected = round(bbox[1] + (bbox[3] - bbox[1]) * 0.56)
        expected = max(bbox[1], min(bbox[3] - 1, expected))
        self.assertEqual(got, expected)

    def test_draw_strikethrough_ignores_empty_text(self) -> None:
        image = Image.new("L", (80, 32), 255)
        draw = ImageDraw.Draw(image)
        font = ImageFont.load_default()

        self.assertIsNone(draw_strikethrough(draw, "", 4, 4, font))


if __name__ == "__main__":
    unittest.main()
