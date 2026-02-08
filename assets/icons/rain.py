from PIL import Image, ImageDraw
try:
    from . import cloud
except ImportError:
    import cloud

def draw(draw, xy, size, color=(17, 17, 17), stroke_width=2, intensity='medium'):
    """
    Draws a Rain icon (Cloud base + rain drops).
    Intensity: 'light', 'medium', 'heavy'
    """
    x, y = xy
    s = size
    width = int(stroke_width)
    
    # 1. Draw Base Cloud
    cloud.draw(draw, xy, size, color, stroke_width)
    
    # 2. Draw Rain Drops
    start_y = y + s * 0.90 # Matches new bubbly cloud bottom (approx)
    center_x = x + s/2
    
    # Drop Config
    drop_length = s * 0.15
    drop_slant = s * 0.1
    
    if intensity == 'light':
         offsets = [-0.1, 0.1]
    elif intensity == 'heavy':
         offsets = [-0.2, -0.1, 0, 0.1, 0.2]
    else: # medium
         offsets = [-0.15, 0, 0.15]
    
    for off in offsets:
        sx = center_x + (s * off)
        sy = start_y
        
        ex = sx - drop_slant
        ey = sy + drop_length
        
        draw.line([(sx, sy), (ex, ey)], fill=color, width=width)

if __name__ == "__main__":
    print("Generating test_icon_rain.png...")
    TEST_SIZE = 100
    img = Image.new('RGB', (TEST_SIZE, TEST_SIZE), (255, 255, 255))
    draw_obj = ImageDraw.Draw(img)
    
    draw(draw_obj, (25, 25), 50, color=(0, 0, 0), stroke_width=3)
    
    img.save("test_icon_rain.png")
