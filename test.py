import os
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont

# -----------------------------------------------------------------------------
# 1. CONFIGURATION (Exported from React DevTools)
# -----------------------------------------------------------------------------
THEME = {
  "clockFontSize": 7,       # 112px
  "dateFontSize": 1.4,      # 22.4px
  "clockFontWeight": 800,
  "taskFontSize": 1.15,     # 18.4px
  "taskPadding": 10,
  "taskGap": 10,
  "taskBorderWidth": 2,
  "taskItemMinHeight": 72,
  "taskItemRadius": 12,
  "taskStrokeColor": "#111111",
  "weatherIconSize": 36,
  "iconStrokeWidth": 2.5,
  "leftColumnWidth": 300,
  "weatherHeight": 130,
  "borderRadius": 12,
  "lineThickness": 6,
  "lineColor": "#e5e5e5"
}

# Canvas Dimensions (Waveshare 7.5in)
WIDTH = 800
HEIGHT = 480
BASE_FONT_SIZE = 16 # Browser default for REM conversion

# Colors
COLOR_BG = (229, 229, 229) # #e5e5e5
COLOR_WHITE = (255, 255, 255)
COLOR_INK = (17, 17, 17)   # #111111
COLOR_GRAY = (160, 160, 160)

# -----------------------------------------------------------------------------
# 2. HELPERS
# -----------------------------------------------------------------------------
def load_font(name, size_rem, bold=False):
    """
    Attempts to load a font. You should place .ttf files in the same directory.
    Falls back to default if not found.
    """
    px_size = int(size_rem * BASE_FONT_SIZE)
    
    # List of common paths to check for similar fonts
    # You should download JetBrainsMono-ExtraBold.ttf and Inter-SemiBold.ttf
    possible_fonts = []
    
    if "JetBrains" in name:
        possible_fonts = ["JetBrainsMono-ExtraBold.ttf", "JetBrainsMono-Bold.ttf", "arialbd.ttf"]
    else:
        possible_fonts = ["Inter-Bold.ttf" if bold else "Inter-Regular.ttf", "arial.ttf", "FreeSans.ttf"]
        
    for f in possible_fonts:
        try:
            return ImageFont.truetype(f, px_size)
        except OSError:
            continue
            
    print(f"Warning: Could not load specific font for {name}, using default.")
    return ImageFont.load_default()

def draw_rounded_rect(draw, xy, radius, fill=None, outline=None, width=1):
    """Custom rounded rectangle wrapper to handle corners nicely"""
    x, y, w, h = xy
    draw.rounded_rectangle([(x, y), (x+w, y+h)], radius=radius, fill=fill, outline=outline, width=width)

def get_text_center(draw, text, font):
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    return text_w, text_h

# -----------------------------------------------------------------------------
# 3. MAIN RENDERER
# -----------------------------------------------------------------------------
def render_dashboard():
    # Create Canvas
    img = Image.new('RGB', (WIDTH, HEIGHT), COLOR_BG)
    draw = ImageDraw.Draw(img)

    # --------------------------
    # Layout Calculations
    # --------------------------
    gap = THEME['lineThickness']
    radius = THEME['borderRadius']
    
    # Columns
    left_x = gap
    left_w = THEME['leftColumnWidth']
    
    right_x = left_x + left_w + gap
    right_w = WIDTH - right_x - gap
    
    total_h = HEIGHT - (gap * 2)
    
    # Left Column Segments
    weather_h = THEME['weatherHeight']
    clock_h = total_h - weather_h - gap
    
    # --------------------------
    # Draw Containers (Cards)
    # --------------------------
    
    # 1. Clock Card (Top Left)
    draw_rounded_rect(draw, (left_x, gap, left_w, clock_h), radius, fill=COLOR_WHITE)
    
    # 2. Weather Card (Bottom Left)
    weather_y = gap + clock_h + gap
    draw_rounded_rect(draw, (left_x, weather_y, left_w, weather_h), radius, fill=COLOR_WHITE)
    
    # 3. Task Card (Right)
    draw_rounded_rect(draw, (right_x, gap, right_w, total_h), radius, fill=COLOR_WHITE)

    # --------------------------
    # Content: Clock Panel
    # --------------------------
    font_clock = load_font("JetBrains", THEME['clockFontSize'])
    font_date = load_font("Inter", THEME['dateFontSize'], bold=True)
    
    now = datetime.now()
    time_str = now.strftime("%H:%M")
    date_str = now.strftime("%A, %b %d")
    
    # Center Time
    tw, th = get_text_center(draw, time_str, font_clock)
    clock_center_x = left_x + (left_w / 2)
    clock_center_y = gap + (clock_h / 2) - 20 # Offset slightly up
    
    draw.text((clock_center_x - tw/2, clock_center_y - th/2), time_str, font=font_clock, fill=COLOR_INK)
    
    # Center Date
    dw, dh = get_text_center(draw, date_str, font_date)
    draw.text((clock_center_x - dw/2, clock_center_y + th/2 + 20), date_str, font=font_date, fill=COLOR_INK)

    # Top Status Bar (Mock)
    font_small = load_font("JetBrains", 0.8)
    draw.text((left_x + 20, gap + 20), "WIFI", font=font_small, fill=COLOR_INK)
    draw.text((left_x + left_w - 50, gap + 20), "84%", font=font_small, fill=COLOR_INK)

    # --------------------------
    # Content: Weather Strip
    # --------------------------
    # 4 Columns
    col_w = left_w / 4
    font_temp = load_font("JetBrains", 1.2, bold=True)
    font_day = load_font("Inter", 0.7, bold=True)
    
    forecast = [
        ("MON", "22°"), ("TUE", "20°"), ("WED", "18°"), ("THU", "19°")
    ]
    
    for i, (day, temp) in enumerate(forecast):
        cx = left_x + (i * col_w)
        
        # Divider line
        if i > 0:
            draw.line([(cx, weather_y + 10), (cx, weather_y + weather_h - 10)], fill=COLOR_INK, width=2)
            
        # Day
        dw, dh = get_text_center(draw, day, font_day)
        draw.text((cx + col_w/2 - dw/2, weather_y + 15), day, font=font_day, fill=COLOR_INK)
        
        # Temp
        tw, th = get_text_center(draw, temp, font_temp)
        draw.text((cx + col_w/2 - tw/2, weather_y + weather_h - 35), temp, font=font_temp, fill=COLOR_INK)
        
        # Placeholder for Icon (Circle)
        icon_y = weather_y + 45
        icon_size = THEME['weatherIconSize']
        icon_x = cx + col_w/2 - icon_size/2
        draw.ellipse((icon_x, icon_y, icon_x+icon_size, icon_y+icon_size), outline=COLOR_INK, width=int(THEME['iconStrokeWidth']))

    # --------------------------
    # Content: Tasks
    # --------------------------
    header_h = 60
    font_header = load_font("Inter", 1.5, bold=True)
    font_task = load_font("Inter", THEME['taskFontSize'], bold=False)
    font_time = load_font("JetBrains", 0.9)
    
    # Header
    draw.text((right_x + 20, gap + 20), "REMINDERS", font=font_header, fill=COLOR_INK)
    draw.line([(right_x, gap + header_h), (right_x + right_w, gap + header_h)], fill=THEME['taskStrokeColor'], width=2)
    
    # List Items
    tasks = [
        ("Doctor Appointment", "14:00", True),
        ("Buy Milk", None, False),
        ("Morning Yoga", "08:00", False),
        ("Yoghurt Expires", "2 Days", True),
    ]
    
    list_start_y = gap + header_h + 14
    item_h = THEME['taskItemMinHeight']
    item_gap = THEME['taskGap']
    padding = THEME['taskPadding']
    
    for i, (text, time, urgent) in enumerate(tasks):
        item_y = list_start_y + (i * (item_h + item_gap))
        
        # Safety check for overflow
        if item_y + item_h > HEIGHT: break
        
        item_w = right_w - (padding * 2) - 4 # Adjust for container padding
        item_x = right_x + padding + 2
        
        # Draw Task Box
        draw_rounded_rect(draw, (item_x, item_y, item_w, item_h), 
                         radius=THEME['taskItemRadius'], 
                         outline=THEME['taskStrokeColor'], 
                         width=THEME['taskBorderWidth'])
        
        # Checkbox (Mock)
        check_size = 24
        check_x = item_x + 15
        check_y = item_y + (item_h - check_size) / 2
        draw.rectangle((check_x, check_y, check_x+check_size, check_y+check_size), outline=COLOR_INK, width=2)
        
        # Text
        text_x = check_x + check_size + 15
        # Rudimentary vertical centering
        draw.text((text_x, item_y + item_h/2 - 10), text, font=font_task, fill=COLOR_INK)
        
        # Time (Right aligned)
        if time:
            tw, th = get_text_center(draw, time, font_time)
            time_x = item_x + item_w - tw - 15
            
            # Vertical separator
            sep_x = time_x - 10
            draw.line([(sep_x, item_y + 15), (sep_x, item_y + item_h - 15)], fill=COLOR_INK, width=2)
            
            draw.text((time_x, item_y + item_h/2 - 8), time, font=font_time, fill=COLOR_INK)

    # --------------------------
    # Output
    # --------------------------
    # Rotate 180 if needed for display mounting
    # img = img.rotate(180) 
    
    # Save for preview or display driver
    img.save("dashboard_render.png")
    print("Dashboard rendered to dashboard_render.png")

if __name__ == "__main__":
    render_dashboard()
