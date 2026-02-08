from PIL import Image, ImageDraw
try:
    from . import cloud
except ImportError:
    import cloud


def draw(draw, xy, size, color=(17, 17, 17), stroke_width=2):
    """
    Draws a Storm icon (Cloud + lightning bolt).
    """
    x, y = xy
    s = size
    width = int(stroke_width)

    # Base cloud
    cloud.draw(draw, xy, size, color, stroke_width)

    # Lightning bolt (polyline)
    bx = x + s * 0.52
    by = y + s * 0.90 # Matches new cloud bottom
    points = [
        (bx, by),
        (bx + s * 0.10, by + s * 0.18),
        (bx + s * 0.02, by + s * 0.18),
        (bx + s * 0.14, by + s * 0.40),
        (bx - s * 0.02, by + s * 0.26),
        (bx + s * 0.05, by + s * 0.26),
    ]
    draw.line(points, fill=color, width=width)


if __name__ == "__main__":
    print("Generating test_icon_storm.png...")
    TEST_SIZE = 100
    img = Image.new("RGB", (TEST_SIZE, TEST_SIZE), (255, 255, 255))
    draw_obj = ImageDraw.Draw(img)

    draw(draw_obj, (25, 25), 50, color=(0, 0, 0), stroke_width=3)

    img.save("test_icon_storm.png")
