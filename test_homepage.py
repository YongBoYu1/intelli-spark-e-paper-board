#!/usr/bin/python
# -*- coding:utf-8 -*-
import sys
import os
import time
import logging
import glob
import json
import select
import termios
import tty
import urllib.request
import urllib.parse
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont

base_dir = os.path.dirname(os.path.realpath(__file__))
default_root = os.path.dirname(base_dir)
picdir = os.path.join(default_root, 'pic')
libdir = os.path.join(default_root, 'lib')
LOG_PATH = os.path.join(base_dir, "run.log")
LAST_FRAME_PATH = os.path.join(base_dir, "last_frame.png")

# Auto-detect Waveshare repo paths on Raspberry Pi
candidate_roots = []
env_root = os.environ.get("WAVESHARE_PYTHON_ROOT")
if env_root:
    candidate_roots.append(env_root)
candidate_roots.extend(
    [
        default_root,
        "/e-Paper/RaspberryPi_JetsonNano/python",
        "/root/e-Paper/RaspberryPi_JetsonNano/python",
        "/home/pi/e-Paper/RaspberryPi_JetsonNano/python",
        "/home/agentpi/e-Paper/RaspberryPi_JetsonNano/python",
    ]
)
candidate_roots.extend(glob.glob("/home/*/e-Paper/RaspberryPi_JetsonNano/python"))

for root in candidate_roots:
    cand_pic = os.path.join(root, 'pic')
    cand_lib = os.path.join(root, 'lib')
    if os.path.exists(cand_pic) and os.path.exists(cand_lib):
        picdir = cand_pic
        libdir = cand_lib
        break

if os.path.exists(libdir):
    sys.path.append(libdir)
else:
    logging.error("waveshare_epd lib not found. Set WAVESHARE_PYTHON_ROOT or update paths.")
    logging.error("Tried roots: %s", ", ".join(candidate_roots))

from waveshare_epd import epd7in5_V2

logging.basicConfig(
    level=logging.INFO,
    handlers=[
        logging.FileHandler(LOG_PATH, mode="a", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)

# Weather config
CITY_NAME = u"北京"
CITY_COUNTRY = "CN"
LATITUDE = 39.9042
LONGITUDE = 116.4074
USE_CITY_NAME = True  # If True, use geocoding by city name; otherwise use LAT/LON
FORECAST_DAYS = 4
WEATHER_REFRESH_SEC = 15 * 60
SELECTION_FULL_PARTIAL = True

WEATHER_CODE_TEXT = {
    0: u"晴朗",
    1: u"大部晴朗",
    2: u"多云",
    3: u"阴",
    45: u"雾",
    48: u"雾凇",
    51: u"小毛雨",
    53: u"中毛雨",
    55: u"大毛雨",
    56: u"轻冻毛雨",
    57: u"重冻毛雨",
    61: u"小雨",
    63: u"中雨",
    65: u"大雨",
    66: u"轻冻雨",
    67: u"重冻雨",
    71: u"小雪",
    73: u"中雪",
    75: u"大雪",
    77: u"冰粒",
    80: u"阵雨小",
    81: u"阵雨中",
    82: u"阵雨大",
    85: u"阵雪小",
    86: u"阵雪大",
    95: u"雷暴",
    96: u"雷暴小冰雹",
    99: u"雷暴大冰雹",
}

WEEKDAY_MAP = [u"日", u"一", u"二", u"三", u"四", u"五", u"六"]


def _text_size(draw, text, font):
    bbox = draw.textbbox((0, 0), text, font=font)
    return (bbox[2] - bbox[0], bbox[3] - bbox[1])


def _center_text(draw, text, font, box):
    x0, y0, x1, y1 = box
    w, h = _text_size(draw, text, font)
    x = x0 + (x1 - x0 - w) // 2
    y = y0 + (y1 - y0 - h) // 2
    draw.text((x, y), text, font=font, fill=0)


def _draw_checkbox(draw, x, y, size, checked=False):
    draw.rectangle((x, y, x + size, y + size), outline=0, fill=255)
    if checked:
        inset = 4
        draw.rectangle((x + inset, y + inset, x + size - inset, y + size - inset), fill=0)


def _draw_weather_icon(draw, x, y):
    # Simple cloud + rain icon
    draw.ellipse((x + 6, y + 10, x + 46, y + 50), outline=0, width=2)
    draw.ellipse((x + 30, y + 6, x + 70, y + 46), outline=0, width=2)
    draw.line((x + 14, y + 50, x + 14, y + 70), fill=0, width=2)
    draw.line((x + 32, y + 50, x + 32, y + 74), fill=0, width=2)
    draw.line((x + 50, y + 50, x + 50, y + 70), fill=0, width=2)


def _fit_font(draw, text, font_path, max_size, max_width, max_height):
    size = max_size
    while size > 10:
        font = ImageFont.truetype(font_path, size)
        w, h = _text_size(draw, text, font)
        if w <= max_width and h <= max_height:
            return font, w, h
        size -= 2
    font = ImageFont.truetype(font_path, 12)
    w, h = _text_size(draw, text, font)
    return font, w, h


def _align8_ceil(x):
    return x if x % 8 == 0 else x + (8 - (x % 8))


def _align8_floor(x):
    return x - (x % 8)


last_frame_image = None


def _save_last_frame(image):
    try:
        if image is None:
            return
        image.save(LAST_FRAME_PATH)
    except Exception as e:
        logging.error("save last_frame.png failed: %s", e)


def _display_full(epd, image):
    global last_frame_image
    last_frame_image = image
    _save_last_frame(image)
    epd.display(epd.getbuffer(image))


def _display_partial(epd, image, x, y, w, h):
    global last_frame_image
    last_frame_image = image
    _save_last_frame(image)
    epd.display_Partial(epd.getbuffer(image), x, y, w, h)


def _display_full_partial(epd, image, w, h):
    _display_partial(epd, image, 0, 0, w, h)


SELECT_MARK_SIZE = 16
SELECT_MARK_MARGIN = 12
SELECT_MARK_PAD = 6


def _http_get_json(url, timeout=8):
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode('utf-8'))


def _weather_text(code):
    if code is None:
        return u"未知"
    try:
        code = int(code)
    except (ValueError, TypeError):
        return u"未知"
    return WEATHER_CODE_TEXT.get(code, u"未知")


def _weekday_from_datestr(datestr):
    try:
        d = datetime.strptime(datestr, "%Y-%m-%d")
    except ValueError:
        try:
            d = datetime.fromisoformat(datestr)
        except ValueError:
            return u""
    return u"周" + WEEKDAY_MAP[d.weekday() + 1 if d.weekday() < 6 else 0]


def geocode_city(name, country_code=None, language="zh", count=1):
    params = {
        "name": name,
        "count": count,
        "format": "json",
        "language": language,
    }
    if country_code:
        params["countryCode"] = country_code
    url = "https://geocoding-api.open-meteo.com/v1/search?" + urllib.parse.urlencode(params)
    data = _http_get_json(url)
    results = data.get("results") or []
    if not results:
        return None
    return results[0]


def _find_hourly_index(times, target_time):
    if not times or not target_time:
        return None
    if target_time in times:
        return times.index(target_time)
    try:
        target_dt = datetime.fromisoformat(target_time)
    except ValueError:
        return None
    best_idx = None
    best_diff = None
    for i, t in enumerate(times):
        try:
            dt = datetime.fromisoformat(t)
        except ValueError:
            continue
        diff = abs((dt - target_dt).total_seconds())
        if best_diff is None or diff < best_diff:
            best_diff = diff
            best_idx = i
    return best_idx


def fetch_weather():
    lat = LATITUDE
    lon = LONGITUDE
    city_label = CITY_NAME

    if USE_CITY_NAME and CITY_NAME:
        try:
            res = geocode_city(CITY_NAME, CITY_COUNTRY, language="zh", count=1)
        except Exception:
            res = None
        if res:
            lat = res.get("latitude", lat)
            lon = res.get("longitude", lon)
            city_label = res.get("name", city_label)

    params = {
        "latitude": lat,
        "longitude": lon,
        "timezone": "auto",
        "forecast_days": FORECAST_DAYS,
        "daily": "weather_code,temperature_2m_max,temperature_2m_min",
        "hourly": "temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,wind_speed_10m",
        "current": "temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,wind_speed_10m",
    }
    url = "https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode(params)
    data = _http_get_json(url)

    current = data.get("current") or {}
    hourly = data.get("hourly") or {}
    hourly_time = hourly.get("time") or []
    idx = _find_hourly_index(hourly_time, current.get("time"))

    def hourly_val(key):
        arr = hourly.get(key)
        if arr and idx is not None and idx < len(arr):
            return arr[idx]
        return None

    current_data = {
        "temperature": current.get("temperature_2m") or current.get("temperature") or hourly_val("temperature_2m"),
        "apparent": current.get("apparent_temperature") or hourly_val("apparent_temperature"),
        "humidity": current.get("relative_humidity_2m") or hourly_val("relative_humidity_2m"),
        "wind_speed": current.get("wind_speed_10m") or current.get("windspeed") or hourly_val("wind_speed_10m"),
        "weather_code": current.get("weather_code") or current.get("weathercode") or hourly_val("weather_code"),
        "time": current.get("time"),
    }

    daily = data.get("daily") or {}
    forecast = []
    times = daily.get("time") or []
    maxs = daily.get("temperature_2m_max") or []
    mins = daily.get("temperature_2m_min") or []
    codes = daily.get("weather_code") or []
    count = min(len(times), len(maxs), len(mins), len(codes), FORECAST_DAYS)
    for i in range(count):
        forecast.append(
            {
                "date": times[i],
                "max": maxs[i],
                "min": mins[i],
                "code": codes[i],
            }
        )

    return {
        "city": city_label,
        "lat": lat,
        "lon": lon,
        "current": current_data,
        "forecast": forecast,
        "fetched_at": time.time(),
    }


try:
    logging.info("epd7in5_V2 homepage demo")
    epd = epd7in5_V2.EPD()

    logging.info("init and Clear")
    epd.init()
    epd.Clear()

    font_path = os.path.join(picdir, 'Font.ttc')
    font_title = ImageFont.truetype(font_path, 30)
    font_big = ImageFont.truetype(font_path, 56)
    font_med = ImageFont.truetype(font_path, 28)
    font_small = ImageFont.truetype(font_path, 22)
    font_title_big = ImageFont.truetype(font_path, 36)
    font_desc = ImageFont.truetype(font_path, 30)
    font_temp = ImageFont.truetype(font_path, 96)

    w, h = epd.width, epd.height
    margin = 24
    header_h = 150
    bottom_h = 70
    mid_h = h - header_h - bottom_h

    mid_top = header_h + 14
    mid_bottom = header_h + mid_h - 14
    mid_left = margin
    mid_right = w - margin
    gap = 20
    box_w = (mid_right - mid_left - gap) // 2

    left_box = (mid_left, mid_top, mid_left + box_w, mid_bottom)
    right_box = (mid_left + box_w + gap, mid_top, mid_right, mid_bottom)

    bottom_top = header_h + mid_h
    col_w = (w - margin * 2) // 3
    bottom_boxes = [
        (margin + col_w * 0, bottom_top, margin + col_w * 1, h),
        (margin + col_w * 1, bottom_top, margin + col_w * 2, h),
        (margin + col_w * 2, bottom_top, margin + col_w * 3, h),
    ]

    boxes = {
        "weather": left_box,
        "todo": right_box,
        "bottom1": bottom_boxes[0],
        "bottom2": bottom_boxes[1],
        "bottom3": bottom_boxes[2],
    }
    neighbors = {
        "weather": {"right": "todo", "down": "bottom1"},
        "todo": {"left": "weather", "down": "bottom3"},
        "bottom1": {"up": "weather", "right": "bottom2"},
        "bottom2": {"up": "weather", "left": "bottom1", "right": "bottom3"},
        "bottom3": {"up": "todo", "left": "bottom2"},
    }

    def draw_home_base():
        base = Image.new('1', (w, h), 255)
        draw = ImageDraw.Draw(base)

        draw.rectangle((0, 0, w - 1, h - 1), outline=0, width=3)

        time_sample = "88:88:88"
        font_time, time_w, time_h = _fit_font(
            draw,
            time_sample,
            font_path,
            max_size=96,
            max_width=w - margin * 2,
            max_height=90,
        )
        weekday = WEEKDAY_MAP[int(time.strftime('%w'))]
        date_text = time.strftime('%Y年%m月%d日 ') + u"星期" + weekday
        font_date, date_w, date_h = _fit_font(
            draw,
            date_text,
            font_path,
            max_size=28,
            max_width=w - margin * 2,
            max_height=36,
        )

        time_y = 10
        date_y = header_h - date_h - 8
        if time_y + time_h + 8 > date_y:
            time_y = max(6, date_y - time_h - 8)

        time_x = (w - time_w) // 2
        date_x = (w - date_w) // 2

        draw.text((date_x, date_y), date_text, font=font_date, fill=0)

        draw.line((margin, header_h, w - margin, header_h), fill=0, width=2)

        draw.rectangle(left_box, outline=0, width=2)
        draw.rectangle(right_box, outline=0, width=2)

        left_pad = 16
        draw.text((left_box[0] + left_pad, left_box[1] + 12), u"今日天气", font=font_title, fill=0)
        _draw_weather_icon(draw, left_box[0] + left_pad, left_box[1] + 64)
        draw.text((left_box[0] + left_pad + 92, left_box[1] + 78), u"16°C", font=font_big, fill=0)
        draw.text((left_box[0] + left_pad + 92, left_box[1] + 150), u"雨天", font=font_med, fill=0)
        draw.text((left_box[0] + left_pad + 92, left_box[1] + 182), u"北京", font=font_med, fill=0)

        right_pad = 16
        draw.text((right_box[0] + right_pad, right_box[1] + 12), u"今日待办", font=font_title, fill=0)
        check_x = right_box[0] + right_pad
        item_x = check_x + 32
        row_y = right_box[1] + 68
        row_gap = 42

        _draw_checkbox(draw, check_x, row_y, 18, checked=True)
        draw.text((item_x, row_y - 6), u"买菜", font=font_med, fill=0)

        _draw_checkbox(draw, check_x, row_y + row_gap, 18, checked=False)
        draw.text((item_x, row_y + row_gap - 6), u"健身", font=font_med, fill=0)

        draw.line((right_box[0] + 12, right_box[1] + 148, right_box[2] - 12, right_box[1] + 148), fill=0, width=1)
        draw.line((right_box[0] + 12, right_box[1] + 178, right_box[2] - 12, right_box[1] + 178), fill=0, width=1)

        draw.text((right_box[0] + right_pad, right_box[1] + 194), u"已完成：1 / 3", font=font_small, fill=0)

        draw.line((margin, bottom_top, w - margin, bottom_top), fill=0, width=2)
        for i in range(1, 3):
            x = margin + col_w * i
            draw.line((x, bottom_top + 10, x, h - 10), fill=0, width=2)

        labels = [u"提醒", u"温度", u"已完成"]
        values = [u"2", u"16°", u"1"]
        for i in range(3):
            x0 = margin + col_w * i
            x1 = x0 + col_w
            _center_text(draw, labels[i], font_small, (x0, bottom_top + 10, x1, bottom_top + 36))
            _center_text(draw, values[i], font_med, (x0, bottom_top + 36, x1, h - 10))

        return base, (time_x, time_y, time_w, time_h), font_time

    def draw_selection(draw, selected_key):
        if selected_key in boxes:
            x0, y0, x1, _ = boxes[selected_key]
            mx0 = x1 - SELECT_MARK_MARGIN - SELECT_MARK_SIZE
            my0 = y0 + SELECT_MARK_MARGIN
            mx1 = mx0 + SELECT_MARK_SIZE
            my1 = my0 + SELECT_MARK_SIZE
            draw.rectangle((mx0, my0, mx1, my1), fill=0)

    def selection_regions(box):
        x0, y0, x1, _ = box
        mx0 = x1 - SELECT_MARK_MARGIN - SELECT_MARK_SIZE
        my0 = y0 + SELECT_MARK_MARGIN
        mx1 = mx0 + SELECT_MARK_SIZE
        my1 = my0 + SELECT_MARK_SIZE
        p = SELECT_MARK_PAD
        return [(mx0 - p, my0 - p, mx1 + p, my1 + p)]

    def draw_weather_page(weather_data, error_msg=None):
        base = Image.new('1', (w, h), 255)
        draw = ImageDraw.Draw(base)

        draw.rectangle((0, 0, w - 1, h - 1), outline=0, width=3)
        draw.text((margin, 14), u"天气", font=font_title_big, fill=0)

        if weather_data:
            city = weather_data.get("city", CITY_NAME)
            update_text = time.strftime('%H:%M', time.localtime(weather_data.get("fetched_at", time.time())))
            header_right = city + u"  更新" + update_text
            w_header, h_header = _text_size(draw, header_right, font_small)
            draw.text((w - margin - w_header, 22), header_right, font=font_small, fill=0)

        draw.line((margin, 60, w - margin, 60), fill=0, width=2)

        if error_msg:
            draw.text((margin, 100), u"天气获取失败", font=font_title, fill=0)
            draw.text((margin, 150), error_msg, font=font_small, fill=0)
            return base

        current = weather_data.get("current", {}) if weather_data else {}
        temp = current.get("temperature")
        desc = _weather_text(current.get("weather_code"))
        feels = current.get("apparent")
        humidity = current.get("humidity")
        wind = current.get("wind_speed")

        left_x = margin
        top_y = 80
        temp_text = u"--"
        if temp is not None:
            temp_text = u"%d°C" % int(round(temp))
        draw.text((left_x, top_y), temp_text, font=font_temp, fill=0)
        draw.text((left_x, top_y + 108), desc, font=font_desc, fill=0)

        right_x = int(w * 0.55)
        line_y = top_y + 10
        draw.text((right_x, line_y), u"体感", font=font_small, fill=0)
        draw.text((right_x + 90, line_y - 6), (u"%d°C" % int(round(feels))) if feels is not None else u"--", font=font_med, fill=0)

        draw.text((right_x, line_y + 40), u"湿度", font=font_small, fill=0)
        draw.text((right_x + 90, line_y + 34), (u"%d%%" % int(round(humidity))) if humidity is not None else u"--", font=font_med, fill=0)

        draw.text((right_x, line_y + 80), u"风速", font=font_small, fill=0)
        draw.text((right_x + 90, line_y + 74), (u"%d" % int(round(wind))) if wind is not None else u"--", font=font_med, fill=0)
        draw.text((right_x + 140, line_y + 80), u"km/h", font=font_small, fill=0)

        forecast_top = h - 140
        draw.line((margin, forecast_top, w - margin, forecast_top), fill=0, width=2)

        forecast = weather_data.get("forecast", []) if weather_data else []
        if forecast:
            cols = len(forecast)
            col_w2 = (w - margin * 2) // cols
            for i, day in enumerate(forecast):
                x0 = margin + col_w2 * i
                x1 = x0 + col_w2
                if i > 0:
                    draw.line((x0, forecast_top + 10, x0, h - 10), fill=0, width=1)
                week_text = _weekday_from_datestr(day.get("date", ""))
                draw.text((x0 + 8, forecast_top + 16), week_text, font=font_small, fill=0)
                desc2 = _weather_text(day.get("code"))
                draw.text((x0 + 8, forecast_top + 44), desc2, font=font_small, fill=0)
                max_v = day.get("max")
                min_v = day.get("min")
                temp_range = u"--"
                if max_v is not None and min_v is not None:
                    temp_range = u"%d/%d°" % (int(round(max_v)), int(round(min_v)))
                draw.text((x0 + 8, forecast_top + 74), temp_range, font=font_small, fill=0)
        else:
            draw.text((margin, forecast_top + 20), u"暂无预报数据", font=font_small, fill=0)

        draw.text((margin, h - 34), u"Enter 进入 / B 返回 / R 刷新", font=font_small, fill=0)
        return base

    def draw_loading_page(text=u"正在获取天气..."):
        base = Image.new('1', (w, h), 255)
        draw = ImageDraw.Draw(base)
        draw.rectangle((0, 0, w - 1, h - 1), outline=0, width=3)
        _center_text(draw, text, font_title, (0, 0, w, h))
        return base

    selected = "weather"
    prev_selected = selected
    view = "home"
    weather_data = None
    weather_error = None
    last_fetch = 0

    base_home, time_rect, font_time = draw_home_base()
    time_x, time_y, time_w, time_h = time_rect

    frame = base_home.copy()
    frame_draw = ImageDraw.Draw(frame)
    draw_selection(frame_draw, selected)
    frame_draw.text((time_x, time_y), time.strftime('%H:%M:%S'), font=font_time, fill=0)
    _display_full(epd, frame)

    logging.info("start event loop")
    epd.init_part()
    update_h = _align8_ceil(header_h)
    if update_h > h:
        update_h = h
    time_box = (0, 0, w, update_h)
    time_box_w = w
    time_box_h = update_h

    input_stream = sys.stdin
    opened_tty = False
    if not sys.stdin.isatty():
        try:
            input_stream = open("/dev/tty", "rb", buffering=0)
            opened_tty = True
        except Exception:
            input_stream = sys.stdin

    fd = input_stream.fileno()
    old_settings = termios.tcgetattr(fd)
    tty.setcbreak(fd)

    last_sec = None
    try:
        while True:
            now = time.time()
            if view == "home":
                sec = int(now)
                if sec != last_sec:
                    last_sec = sec
                    frame = base_home.copy()
                    frame_draw = ImageDraw.Draw(frame)
                    draw_selection(frame_draw, selected)
                    frame_draw.text((time_x, time_y), time.strftime('%H:%M:%S', time.localtime(now)), font=font_time, fill=0)
                    _display_partial(epd, frame, time_box[0], time_box[1], time_box_w, time_box_h)

            # Auto refresh weather data while on weather page
            if view == "weather" and (now - last_fetch) > WEATHER_REFRESH_SEC:
                try:
                    weather_data = fetch_weather()
                    weather_error = None
                    last_fetch = time.time()
                except Exception as e:
                    weather_error = str(e)

                page = draw_weather_page(weather_data, weather_error)
                _display_full_partial(epd, page, w, h)

            timeout = 0.1 if view != "home" else max(0.01, (int(time.time()) + 1) - time.time())
            rlist, _, _ = select.select([input_stream], [], [], timeout)
            if not rlist:
                continue
            data = input_stream.read(1)
            if not data:
                continue
            if isinstance(data, bytes):
                ch = data.decode('utf-8', errors='ignore')
            else:
                ch = data
            key = None
            if ch == '\x1b':
                seq_data = input_stream.read(2)
                if isinstance(seq_data, bytes):
                    seq = seq_data.decode('utf-8', errors='ignore')
                else:
                    seq = seq_data
                if seq == '[A':
                    key = 'up'
                elif seq == '[B':
                    key = 'down'
                elif seq == '[C':
                    key = 'right'
                elif seq == '[D':
                    key = 'left'
            elif ch in ('\r', '\n', ' '):
                key = 'enter'
            elif ch in ('e', 'E'):
                key = 'enter'
            elif ch in ('b', 'B'):
                key = 'back'
            elif ch in ('r', 'R'):
                key = 'refresh'
            elif ch in ('s', 'S'):
                key = 'snapshot'

            if view == "home":
                if key and key in neighbors.get(selected, {}):
                    prev_selected = selected
                    selected = neighbors[selected][key]
                    frame = base_home.copy()
                    frame_draw = ImageDraw.Draw(frame)
                    draw_selection(frame_draw, selected)
                    frame_draw.text((time_x, time_y), time.strftime('%H:%M:%S'), font=font_time, fill=0)
                    if SELECTION_FULL_PARTIAL:
                        _display_full_partial(epd, frame, w, h)
                    else:
                        regions = selection_regions(boxes[prev_selected]) + selection_regions(boxes[selected])
                        for rx0, ry0, rx1, ry1 in regions:
                            rx0 = _align8_floor(int(max(0, rx0)))
                            ry0 = _align8_floor(int(max(0, ry0)))
                            rx1 = _align8_ceil(int(min(w, rx1)))
                            ry1 = _align8_ceil(int(min(h, ry1)))
                            if rx1 <= rx0 or ry1 <= ry0:
                                continue
                            region_w = rx1 - rx0
                            region_h = ry1 - ry0
                            _display_partial(epd, frame, rx0, ry0, region_w, region_h)
                elif key == 'enter' and selected == 'weather':
                    view = "weather"
                    _display_full_partial(epd, draw_loading_page(), w, h)
                    try:
                        weather_data = fetch_weather()
                        weather_error = None
                        last_fetch = time.time()
                    except Exception as e:
                        weather_error = str(e)
                    page = draw_weather_page(weather_data, weather_error)
                    _display_full_partial(epd, page, w, h)
                elif key == 'snapshot':
                    _save_last_frame(last_frame_image)
                    logging.info("snapshot saved to %s", LAST_FRAME_PATH)
            else:
                if key == 'back':
                    view = "home"
                    base_home, time_rect, font_time = draw_home_base()
                    time_x, time_y, time_w, time_h = time_rect
                    frame = base_home.copy()
                    frame_draw = ImageDraw.Draw(frame)
                    draw_selection(frame_draw, selected)
                    frame_draw.text((time_x, time_y), time.strftime('%H:%M:%S'), font=font_time, fill=0)
                    _display_full_partial(epd, frame, w, h)
                elif key == 'refresh':
                    try:
                        weather_data = fetch_weather()
                        weather_error = None
                        last_fetch = time.time()
                    except Exception as e:
                        weather_error = str(e)
                    page = draw_weather_page(weather_data, weather_error)
                    _display_full_partial(epd, page, w, h)
                elif key == 'snapshot':
                    _save_last_frame(last_frame_image)
                    logging.info("snapshot saved to %s", LAST_FRAME_PATH)

    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        if opened_tty:
            try:
                input_stream.close()
            except Exception:
                pass

except IOError as e:
    logging.info(e)

except KeyboardInterrupt:
    logging.info("ctrl + c:")
    epd7in5_V2.epdconfig.module_exit(cleanup=True)
