from PIL import Image, ImageDraw
try:
    from . import cloud
except ImportError:
    import cloud

def draw_snowflake(draw, center, size, color, width):
    """Draws a simple snowflake (asterisk style)"""
    cx, cy = center
    r = size / 2
    
    # 3 intersecting lines
    # Vertical
    draw.line([(cx, cy-r), (cx, cy+r)], fill=color, width=width)
    # Diagonals
    # cos(60) = 0.5, sin(60) = 0.866
    dx = r * 0.866
    dy = r * 0.5
    draw.line([(cx-dx, cy-dy), (cx+dx, cy+dy)], fill=color, width=width)
    draw.line([(cx-dx, cy+dy), (cx+dx, cy-dy)], fill=color, width=width)

def draw(draw, xy, size, color=(17, 17, 17), stroke_width=2, intensity='medium'):
    """
    Draws a Snow icon (Cloud base + snowflakes).
    Intensity: 'light', 'medium', 'heavy'
    """
    x, y = xy
    s = size
    width = int(stroke_width)
    
    # 1. Draw Base Cloud
    cloud.draw(draw, xy, size, color, stroke_width)
    
    # 2. Draw Snowflakes
    start_y = y + s * 0.90
    center_x = x + s/2
    
    flake_size = s * 0.12
    
    if intensity == 'light':
         # 2 flakes
         offsets = [-0.12, 0.12]
         y_offsets = [0, 0]
    elif intensity == 'heavy':
         # 5 flakes in 2 rows? or just 5 across?
         # zigzag
         offsets = [-0.2, -0.1, 0, 0.1, 0.2]
         y_offsets = [0, 0.15, 0, 0.15, 0]
    else: # medium
         offsets = [-0.15, 0, 0.15]
         y_offsets = [0, 0.1, 0] # Middle one lower? or same?
         # Let's keep them same line or slight variation
         y_offsets = [0, 0, 0]

    for i, off in enumerate(offsets):
        fx = center_x + (s * off)
        fy = start_y + (s * y_offsets[i]) + (flake_size/2)
        
        draw_snowflake(draw, (fx, fy), flake_size, color, width)

if __name__ == "__main__":
    print("Generating test_icon_snow.png...")
    TEST_SIZE = 100
    img = Image.new('RGB', (TEST_SIZE, TEST_SIZE), (255, 255, 255))
    draw_obj = ImageDraw.Draw(img)
    
    draw(draw_obj, (25, 25), 50, color=(0, 0, 0), stroke_width=2, intensity='heavy')
    
    img.save("test_icon_snow.png")
