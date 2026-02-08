import math
from PIL import Image, ImageDraw

def _round_cap(draw, x, y, radius, color):
    draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=color)


def draw(draw, xy, size, color=(17, 17, 17), stroke_width=2, bars=2):
    """
    Draws a compact Wi-Fi status icon (dot + arcs).
    Tuned to look good at small sizes (e.g. 18px).
    """
    x, y = xy
    s = size
    width = int(stroke_width)

    bars = max(1, min(int(bars), 3))

    # Center of the emitter (slightly above the bottom edge to keep arcs inside the box)
    cx = x + s * 0.5
    cy = y + s * 0.80

    # Dot
    dot_r = max(1.0, width * 0.6)
    _round_cap(draw, cx, cy, dot_r, color)

    # Arc sweep: wide enough to read at small sizes, but not so wide that it hits the box edges.
    start_angle = 220
    end_angle = 320

    # Radii tuned for s=18 (status bar): ~[5, 8, 11]
    radii = [s * 0.28, s * 0.46, s * 0.64][:bars]
    cap_r = max(1.0, width / 2)

    for r in radii:
        bbox = (cx - r, cy - r, cx + r, cy + r)
        draw.arc(bbox, start=start_angle, end=end_angle, fill=color, width=width)

        # Round the arc ends (Pillow arcs have square ends).
        for ang in (start_angle, end_angle):
            rad = math.radians(ang)
            ex = cx + math.cos(rad) * r
            ey = cy + math.sin(rad) * r
            _round_cap(draw, ex, ey, cap_r, color)

if __name__ == "__main__":
    print("Generating test_icon_wifi.png...")
    TEST_SIZE = 100
    img = Image.new('RGB', (TEST_SIZE, TEST_SIZE), (255, 255, 255))
    draw_obj = ImageDraw.Draw(img)
    
    draw(draw_obj, (25, 25), 50, color=(0, 0, 0), stroke_width=3)
    
    img.save("test_icon_wifi.png")
