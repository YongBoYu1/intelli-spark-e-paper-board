from PIL import Image, ImageDraw
try:
    from . import cloud
    from . import sun
except ImportError:
    import cloud
    import sun

def draw(draw, xy, size, color=(17, 17, 17), stroke_width=2):
    """
    Draws a Partly Cloudy icon (Sun behind Cloud).
    """
    x, y = xy
    s = size
    width = int(stroke_width)
    
    # 1. Draw Sun
    # Offset sun slightly to the top-right to be visible behind the cloud
    # The sun is normally centered at s/2, s/2.
    # We want it to peek out from top-right of cloud.
    # Cloud covers [0.2s, 0.8s] roughly.
    # Let's shift sun UP and RIGHT.
    sun_offset_x = s * 0.15
    sun_offset_y = -s * 0.15
    
    sun_xy = (x + sun_offset_x, y + sun_offset_y)
    
    # Draw sun, maybe slightly smaller? Or same size.
    # If we use same size, it might look big. Let's try same size first.
    sun.draw(draw, sun_xy, size, color, stroke_width)
    
    # 2. Draw Cloud with Mask
    # Use a fill color that matches the current image mode.
    # In "1" mode, Pillow expects an int; in RGB we can use an RGB tuple.
    filled_bg = 255 if isinstance(color, int) else (255, 255, 255)
    cloud.draw(draw, xy, size, color, stroke_width, filled_bg=filled_bg)

if __name__ == "__main__":
    print("Generating test_icon_partly_cloudy.png...")
    TEST_SIZE = 150 # Larger to see offset
    img = Image.new('RGB', (TEST_SIZE, TEST_SIZE), (255, 255, 255))
    draw_obj = ImageDraw.Draw(img)
    
    # Standard padding
    draw(draw_obj, (25, 35), 100, color=(0, 0, 0), stroke_width=3)
    
    img.save("test_icon_partly_cloudy.png")
