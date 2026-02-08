from PIL import Image, ImageDraw

def draw(draw, xy, size, color=(17, 17, 17), stroke_width=2):
    """
    Draws a Bluetooth icon (Classic rune shape).
    """
    x, y = xy
    s = size
    width = int(stroke_width)

    # Simple, readable geometry tuned for small sizes (e.g. 18px).
    spine_x = x + s * 0.44
    top_y = y + s * 0.10
    mid_y = y + s * 0.50
    bot_y = y + s * 0.90

    right_x = x + s * 0.74
    up_y = y + s * 0.30
    low_y = y + s * 0.70

    top = (spine_x, top_y)
    mid = (spine_x, mid_y)
    bot = (spine_x, bot_y)
    ru = (right_x, up_y)
    rl = (right_x, low_y)

    # Spine
    draw.line([top, bot], fill=color, width=width)

    # Zig-zag outline (two triangles sharing the spine)
    draw.line([top, ru, mid, rl, bot], fill=color, width=width)

if __name__ == "__main__":
    print("Generating test_icon_bluetooth.png...")
    TEST_SIZE = 100
    img = Image.new('RGB', (TEST_SIZE, TEST_SIZE), (255, 255, 255))
    draw_obj = ImageDraw.Draw(img)
    
    draw(draw_obj, (25, 25), 50, color=(0, 0, 0), stroke_width=3)
    
    img.save("test_icon_bluetooth.png")
