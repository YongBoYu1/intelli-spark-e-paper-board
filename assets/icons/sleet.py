from PIL import Image, ImageDraw
try:
    from . import cloud
    from . import snow # re-use draw_snowflake if possible, but snow.py doesn't export it easily without refactor.
    # actually snow.py defines draw_snowflake locally. I should copy it or import it if I make it importable.
    # Let's just copy the helper for simplicity to avoid circular imports or refactoring churn.
except ImportError:
    import cloud

def draw_snowflake(draw, center, size, color, width):
    """Draws a simple snowflake (asterisk style)"""
    cx, cy = center
    r = size / 2
    
    # 3 intersecting lines
    draw.line([(cx, cy-r), (cx, cy+r)], fill=color, width=width)
    dx = r * 0.866
    dy = r * 0.5
    draw.line([(cx-dx, cy-dy), (cx+dx, cy+dy)], fill=color, width=width)
    draw.line([(cx-dx, cy+dy), (cx+dx, cy-dy)], fill=color, width=width)

def draw(draw, xy, size, color=(17, 17, 17), stroke_width=2):
    """
    Draws a Sleet icon (Cloud base + diluted rain/snow mix).
    """
    x, y = xy
    s = size
    width = int(stroke_width)
    
    # 1. Draw Base Cloud
    cloud.draw(draw, xy, size, color, stroke_width)
    
    # 2. Draw Mix
    start_y = y + s * 0.90
    center_x = x + s/2
    
    # 3 items: Rain, Snow, Rain
    offsets = [-0.15, 0, 0.15]
    types = ['rain', 'snow', 'rain']
    
    drop_length = s * 0.15
    drop_slant = s * 0.1
    flake_size = s * 0.12
    
    for i, off in enumerate(offsets):
        sx = center_x + (s * off)
        sy = start_y
        
        if types[i] == 'rain':
            ex = sx - drop_slant
            ey = sy + drop_length
            draw.line([(sx, sy), (ex, ey)], fill=color, width=width)
        else:
            # Snowflake
            # Center it slightly lower so it aligns visually with drops?
            # Drops go down to sy+len. Flake is centered at fy.
            # Let's put flake center at sy + len/2
            fy = sy + (drop_length / 2)
            draw_snowflake(draw, (sx, fy), flake_size, color, width)

if __name__ == "__main__":
    print("Generating test_icon_sleet.png...")
    TEST_SIZE = 100
    img = Image.new('RGB', (TEST_SIZE, TEST_SIZE), (255, 255, 255))
    draw_obj = ImageDraw.Draw(img)
    
    draw(draw_obj, (25, 25), 50, color=(0, 0, 0), stroke_width=2)
    
    img.save("test_icon_sleet.png")
