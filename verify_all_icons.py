import os
from PIL import Image, ImageDraw, ImageFont

# Import all icon modules
# We need to make sure we can import them. 
# They are in assets/icons.
import sys
sys.path.append(os.path.join(os.getcwd(), 'assets', 'icons'))

try:
    import cloud
    import sun
    import rain
    import storm
    import snow
    import sleet
    import partly_cloudy
except ImportError as e:
    print(f"Error importing icons: {e}")
    # Fallback for running from root
    from assets.icons import cloud, sun, rain, storm, snow, sleet, partly_cloudy

def create_labeled_icon(title, draw_func, args, size=150, padding=40):
    container = Image.new('RGB', (size, size + 30), (255, 255, 255))
    draw_obj = ImageDraw.Draw(container)
    
    # Draw icon
    # xy offset to center in 150x150
    # Icon size 100
    icon_size = 100
    xy = ((size - icon_size)//2, (size - icon_size)//2)
    
    draw_func(draw_obj, xy, icon_size, color=(17, 17, 17), stroke_width=3, **args)
    
    # Draw Label
    # Font
    try:
        font = ImageFont.truetype("Arial", 12)
    except:
        font = ImageFont.load_default()
        
    draw_obj.text((5, size), title, fill=(0,0,0), font=font)
    
    return container

def main():
    icons_to_test = [
        ("Cloud", cloud.draw, {}),
        ("Sun", sun.draw, {}),
        ("Partly Cloudy", partly_cloudy.draw, {}),
        ("Storm", storm.draw, {}),
        ("Rain (Light)", rain.draw, {'intensity': 'light'}),
        ("Rain (Med)", rain.draw, {'intensity': 'medium'}),
        ("Rain (Heavy)", rain.draw, {'intensity': 'heavy'}),
        ("Snow (Light)", snow.draw, {'intensity': 'light'}),
        ("Snow (Med)", snow.draw, {'intensity': 'medium'}),
        ("Snow (Heavy)", snow.draw, {'intensity': 'heavy'}),
        ("Sleet", sleet.draw, {}),
    ]
    
    # Grid layout
    # 3 cols
    cols = 4
    rows = (len(icons_to_test) + cols - 1) // cols
    
    cell_w = 160
    cell_h = 190
    
    grid_w = cols * cell_w
    grid_h = rows * cell_h
    
    grid_img = Image.new('RGB', (grid_w, grid_h), (255, 255, 255))
    
    for i, (name, func, args) in enumerate(icons_to_test):
        r = i // cols
        c = i % cols
        
        img = create_labeled_icon(name, func, args)
        grid_img.paste(img, (c * cell_w, r * cell_h))
        
    grid_img.save("test_all_icons_grid.png")
    print("Generated test_all_icons_grid.png")

if __name__ == "__main__":
    main()
