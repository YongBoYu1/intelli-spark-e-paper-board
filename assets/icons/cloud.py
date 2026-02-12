import math
from PIL import Image, ImageDraw

def get_circle_intersection(c1, r1, c2, r2, side='top'):
    """
    Finds the intersection points of two circles c1 and c2 with radii r1 and r2.
    Returns the point specified by 'side' ('top' or 'bottom' relative to the line connecting centers).
    """
    x1, y1 = c1
    x2, y2 = c2
    
    d2 = (x1 - x2)**2 + (y1 - y2)**2
    d = math.sqrt(d2)
    
    # Circles too far apart or contained in one another
    if d > r1 + r2 or d < abs(r1 - r2) or d == 0:
        return None
        
    # a is distance from c1 to the perpendicular line through intersections
    a = (r1**2 - r2**2 + d2) / (2 * d)
    h = math.sqrt(max(0, r1**2 - a**2))
    
    # P2 is the point on the line connecting centers
    x0 = x1 + a * (x2 - x1) / d
    y0 = y1 + a * (y2 - y1) / d
    
    # Intersection points
    rx = -(y2 - y1) * (h / d)
    ry = -(x2 - x1) * (h / d)
    
    ix1 = x0 + rx
    iy1 = y0 - ry
    ix2 = x0 - rx
    iy2 = y0 + ry
    
    # For side='top', we generally want the one with smaller Y (screen coords)
    if side == 'top':
         return (ix1, iy1) if iy1 < iy2 else (ix2, iy2)
    else:
         return (ix1, iy1) if iy1 > iy2 else (ix2, iy2)

def get_angle(center, point):
    """Returns angle in degrees from center to point (0-360), consistent with PIL."""
    cx, cy = center
    px, py = point
    rad = math.atan2(py - cy, px - cx)
    deg = math.degrees(rad)
    return deg % 360

def draw(draw, xy, size, color=(17, 17, 17), stroke_width=2, filled_bg=None):
    """
    Draws a cute, bubbly cloud icon with 5 circles and a rounded bottom.
    :param filled_bg: If set to a color (e.g. (255,255,255)), draws the cloud body filled with this color 
                      BEFORE drawing the outline. Useful for masking things behind the cloud (like sun).
    """
    x, y = xy
    s = size
    width = int(stroke_width)
    
    # Cloud consists of 5 circles:
    # Top Left (TL), Top Right (TR)
    # Bottom Left (BL), Bottom Middle (BM), Bottom Right (BR)
    
    # Config: (radius_multiplier, center_x_offset, center_y_offset)
    # Offsets are relative to the top-left corner (x,y) + size
    
    # Tuned for a "puffy" look
    circles_config = {
        'tl': {'r': 0.26, 'cx': 0.34, 'cy': 0.42},
        'tr': {'r': 0.28, 'cx': 0.66, 'cy': 0.40},
        'bl': {'r': 0.22, 'cx': 0.20, 'cy': 0.68}, 
        'bm': {'r': 0.24, 'cx': 0.50, 'cy': 0.72},
        'br': {'r': 0.22, 'cx': 0.80, 'cy': 0.68},
    }
    
    circles = {}
    for key, conf in circles_config.items():
        circles[key] = {
            'r': s * conf['r'],
            'c': (x + s * conf['cx'], y + s * conf['cy'])
        }

    # Optional: Fill the background first (Simple painter's algorithm)
    # Since circles overlap, drawing them all filled creates the union shape.
    if filled_bg:
         for key, val in circles.items():
            cx, cy = val['c']
            r = val['r']
            # Expand slightly to cover stroke artifacts if needed, but exact match is usually fine
            draw.ellipse((cx-r, cy-r, cx+r, cy+r), fill=filled_bg, outline=None)

    # Helper to get intersections
    # We need the outline path: BL -> TL -> TR -> BR -> BM -> BL
    
    def get_int(k1, k2, preference):
        c1, r1 = circles[k1]['c'], circles[k1]['r']
        c2, r2 = circles[k2]['c'], circles[k2]['r']
        
        # get_circle_intersection returns two points. 
        # We need to pick the one that is on the "outside" of the cloud.
        # This is a bit heuristic.
        
        # Re-using the logic from existing get_circle_intersection but we need both points
        # to decide.
        # Let's call the existing function, but properly
        # The existing function `get_circle_intersection` takes a `side` arg.
        
        # For BL -> TL (Left side), we want the intersection with min X?
        # Actually existing `get_circle_intersection` with `side='top'` gives smaller Y (higher).
        # We might need to be more specific.
        
        res = get_circle_intersection(c1, r1, c2, r2, side='top') # This gives smaller Y
        res_bot = get_circle_intersection(c1, r1, c2, r2, side='bottom') # This gives larger Y
        
        if not res or not res_bot: return None
        
        p1, p2 = res, res_bot
        
        if preference == 'left': # Min X
            return p1 if p1[0] < p2[0] else p2
        elif preference == 'top': # Min Y
            return p1 if p1[1] < p2[1] else p2
        elif preference == 'right': # Max X
            return p1 if p1[0] > p2[0] else p2
        elif preference == 'bottom': # Max Y
            return p1 if p1[1] > p2[1] else p2
            
        return p1

    # Calculate intersection points for the loop
    # 1. BL -> TL (intersect on the left)
    p_bl_tl = get_int('bl', 'tl', 'left')
    
    # 2. TL -> TR (intersect on top)
    p_tl_tr = get_int('tl', 'tr', 'top')
    
    # 3. TR -> BR (intersect on right)
    p_tr_br = get_int('tr', 'br', 'right')
    
    # 4. BR -> BM (intersect on bottom)
    p_br_bm = get_int('br', 'bm', 'bottom')
    
    # 5. BM -> BL (intersect on bottom)
    p_bm_bl = get_int('bm', 'bl', 'bottom')
    
    points = [p_bl_tl, p_tl_tr, p_tr_br, p_br_bm, p_bm_bl]
    
    if any(p is None for p in points):
        # Fallback
        for k, v in circles.items():
             cx, cy = v['c']
             r = v['r']
             draw.ellipse((cx-r, cy-r, cx+r, cy+r), outline=color, width=width)
        return

    # Draw Arcs
    # 1. BL Circle: from p_bm_bl to p_bl_tl
    c, r = circles['bl']['c'], circles['bl']['r']
    ang_start = get_angle(c, p_bm_bl)
    ang_end = get_angle(c, p_bl_tl)
    draw.arc((c[0]-r, c[1]-r, c[0]+r, c[1]+r), start=ang_start, end=ang_end, fill=color, width=width)
    
    # 2. TL Circle: from p_bl_tl to p_tl_tr
    c, r = circles['tl']['c'], circles['tl']['r']
    ang_start = get_angle(c, p_bl_tl)
    ang_end = get_angle(c, p_tl_tr)
    draw.arc((c[0]-r, c[1]-r, c[0]+r, c[1]+r), start=ang_start, end=ang_end, fill=color, width=width)

    # 3. TR Circle: from p_tl_tr to p_tr_br
    c, r = circles['tr']['c'], circles['tr']['r']
    ang_start = get_angle(c, p_tl_tr)
    ang_end = get_angle(c, p_tr_br)
    draw.arc((c[0]-r, c[1]-r, c[0]+r, c[1]+r), start=ang_start, end=ang_end, fill=color, width=width)

    # 4. BR Circle: from p_tr_br to p_br_bm
    c, r = circles['br']['c'], circles['br']['r']
    ang_start = get_angle(c, p_tr_br)
    ang_end = get_angle(c, p_br_bm)
    draw.arc((c[0]-r, c[1]-r, c[0]+r, c[1]+r), start=ang_start, end=ang_end, fill=color, width=width)

    # 5. BM Circle: from p_br_bm to p_bm_bl
    c, r = circles['bm']['c'], circles['bm']['r']
    ang_start = get_angle(c, p_br_bm)
    ang_end = get_angle(c, p_bm_bl)
    draw.arc((c[0]-r, c[1]-r, c[0]+r, c[1]+r), start=ang_start, end=ang_end, fill=color, width=width)

if __name__ == "__main__":
    print("Generating test_icon_cloud.png...")
    TEST_SIZE = 200
    img = Image.new('RGB', (TEST_SIZE, TEST_SIZE), (255, 255, 255))
    draw_obj = ImageDraw.Draw(img)
    
    draw(draw_obj, (50, 50), 100, color=(0, 0, 0), stroke_width=4)
    
    img.save("test_icon_cloud.png")
