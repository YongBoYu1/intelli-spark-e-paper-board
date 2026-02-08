from PIL import Image, ImageDraw


def draw(draw, xy, size, color=(17, 17, 17), stroke_width=2):
    """
    Draws a Cloud icon.
    Geometry: Flat bottom, 3 circular bumps.
    """
    x, y = xy
    s = size
    width = int(stroke_width)

    # Bottom line Y position (70% down)
    bl_y = y + s * 0.70

    # Bottom Flat Line
    draw.line([(x + s * 0.2, bl_y), (x + s * 0.8, bl_y)], fill=color, width=width)

    # Left bump (small)
    draw.arc(
        (x + s * 0.1, y + s * 0.4, x + s * 0.45, y + bl_y),
        start=120,
        end=270,
        fill=color,
        width=width,
    )

    # Top bump (main)
    draw.arc(
        (x + s * 0.3, y + s * 0.25, x + s * 0.7, y + s * 0.65),
        start=180,
        end=0,
        fill=color,
        width=width,
    )

    # Right bump (medium)
    draw.arc(
        (x + s * 0.55, y + s * 0.4, x + s * 0.9, y + bl_y),
        start=270,
        end=60,
        fill=color,
        width=width,
    )


if __name__ == "__main__":
    print("Generating test_icon_cloud.png...")
    TEST_SIZE = 100
    img = Image.new("RGB", (TEST_SIZE, TEST_SIZE), (255, 255, 255))
    draw_obj = ImageDraw.Draw(img)

    draw(draw_obj, (25, 25), 50, color=(0, 0, 0), stroke_width=3)

    img.save("test_icon_cloud.png")
