import math
from PIL import Image, ImageDraw


def draw(draw, xy, size, color=(17, 17, 17), stroke_width=2):
    """
    Draws a Sun icon.
    """
    x, y = xy
    s = size
    width = int(stroke_width)
    cx, cy = x + s / 2, y + s / 2

    # Center circle
    r = s * 0.22
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), outline=color, width=width)

    # Rays
    ray_inner = r + (s * 0.12)
    ray_outer = r + (s * 0.28)

    for i in range(0, 360, 45):
        rad = math.radians(i)
        x1 = cx + math.cos(rad) * ray_inner
        y1 = cy + math.sin(rad) * ray_inner
        x2 = cx + math.cos(rad) * ray_outer
        y2 = cy + math.sin(rad) * ray_outer
        draw.line([(x1, y1), (x2, y2)], fill=color, width=width)


if __name__ == "__main__":
    print("Generating test_icon_sun.png...")
    TEST_SIZE = 100
    img = Image.new("RGB", (TEST_SIZE, TEST_SIZE), (255, 255, 255))
    draw_obj = ImageDraw.Draw(img)

    draw(draw_obj, (25, 25), 50, color=(0, 0, 0), stroke_width=3)

    img.save("test_icon_sun.png")
