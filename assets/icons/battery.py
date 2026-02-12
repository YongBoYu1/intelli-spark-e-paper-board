from PIL import Image, ImageDraw

def draw(
    draw,
    xy,
    size,
    color=(17, 17, 17),
    stroke_width=2,
    level=0.84,
    *,
    w=None,
    h=None,
    bg=None,
    show_level=False,
):
    """
    Draws a Battery icon.
    :param level: Battery level from 0.0 to 1.0 (default 84%)
    :param w/h: Optional explicit width/height (useful for status bars, e.g. 24x12).
    :param bg: Optional background fill (match the panel background to "clear" inside).
    :param show_level: If True, draw the filled level bar inside the outline.
    """
    x, y = xy
    width = int(stroke_width)

    # Clamp level to [0, 1]
    try:
        level = float(level)
    except Exception:
        level = 0.0
    level = max(0.0, min(1.0, level))

    # Default to a compact "status bar" style battery outline.
    if w is None or h is None:
        s = size
        body_h = s * 0.50
        body_w = s * 0.90
        bx = x + (s - body_w) / 2
        by = y + (s - body_h) / 2
    else:
        body_w = float(w)
        body_h = float(h)
        bx = float(x)
        by = float(y)

    nub_w = max(2.0, body_w * 0.08)
    nub_h = max(3.0, body_h * 0.45)

    # Outline body excludes nub.
    outline_w = body_w - nub_w
    r = max(1, int(body_h * 0.20))

    # Fill the interior to avoid artifacts in both RGB and 1-bit modes.
    if bg is None:
        bg = 255 if isinstance(color, int) else (255, 255, 255)

    # Main body (rounded)
    draw.rounded_rectangle(
        (bx, by, bx + outline_w, by + body_h),
        radius=r,
        outline=color,
        width=width,
        fill=bg,
    )

    # Terminal nub (small rounded rect)
    nub_x0 = bx + outline_w
    nub_y0 = by + (body_h - nub_h) / 2
    nub_r = max(1, int(nub_h * 0.25))
    draw.rounded_rectangle(
        (nub_x0, nub_y0, nub_x0 + nub_w, nub_y0 + nub_h),
        radius=nub_r,
        outline=color,
        width=width,
        fill=bg,
    )

    # Optional level fill (kept off by default since % text is usually shown)
    if show_level and level > 0:
        pad = max(1, width + 1)
        inner_w = max(0.0, outline_w - 2 * pad)
        inner_h = max(0.0, body_h - 2 * pad)
        fill_w = int(inner_w * level)
        if fill_w > 0 and inner_h > 0:
            fr = max(1, int(inner_h * 0.20))
            draw.rounded_rectangle(
                (bx + pad, by + pad, bx + pad + fill_w, by + body_h - pad),
                radius=fr,
                outline=None,
                fill=color,
            )

if __name__ == "__main__":
    print("Generating test_icon_battery.png...")
    TEST_SIZE = 100
    img = Image.new('RGB', (TEST_SIZE, TEST_SIZE), (255, 255, 255))
    draw_obj = ImageDraw.Draw(img)
    
    draw(draw_obj, (25, 25), 50, color=(0, 0, 0), stroke_width=2, level=0.6)
    
    img.save("test_icon_battery.png")
