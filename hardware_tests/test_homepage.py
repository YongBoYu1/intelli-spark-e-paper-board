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
import subprocess
import signal
import threading
import re
from datetime import datetime, timedelta
from PIL import Image, ImageDraw, ImageFont

# Optional: GPIO and Gemini SDK
try:
    import RPi.GPIO as GPIO
except Exception:
    GPIO = None

try:
    from google import genai
except Exception:
    genai = None
base_dir = os.path.dirname(os.path.realpath(__file__))
default_root = os.path.dirname(base_dir)
picdir = os.path.join(default_root, 'pic')
libdir = os.path.join(default_root, 'lib')
LOG_PATH = os.path.join(base_dir, "run.log")
LAST_FRAME_PATH = os.path.join(base_dir, "last_frame.png")
local_submodule_root = os.path.join(
    base_dir,
    "third_party",
    "waveshare_ePaper",
    "RaspberryPi_JetsonNano",
    "python",
)

# Auto-detect Waveshare repo paths on Raspberry Pi
candidate_roots = []
env_root = os.environ.get("WAVESHARE_PYTHON_ROOT")
if env_root:
    candidate_roots.append(env_root)
candidate_roots.extend(
    [
        local_submodule_root,
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
CITY_NAME = "Beijing"
CITY_COUNTRY = "CN"
LATITUDE = 39.9042
LONGITUDE = 116.4074
USE_CITY_NAME = True  # If True, use geocoding by city name; otherwise use LAT/LON
FORECAST_DAYS = 4
WEATHER_REFRESH_SEC = 15 * 60
SELECTION_FULL_PARTIAL = True

# Todo / voice config
TODO_PATH = os.path.join(base_dir, "todo.txt")
REMINDER_PATH = os.path.join(base_dir, "reminders.json")
TODO_REFRESH_SEC = 10
MAX_TODO_SHOW = 2
REMINDER_REFRESH_SEC = 10

BUTTON_PIN = 5  # BCM pin for voice trigger (avoid 17 which is e-Paper RST)
BUTTON_ACTIVE_LOW = True
DEBOUNCE_MS = 200

AUDIO_DEVICE = "default"  # use `arecord -l` to find, e.g., "plughw:1,0"
AUDIO_RATE = 16000
AUDIO_CHANNELS = 1
RECORD_MAX_SEC = 8
AUDIO_PATH = "/tmp/voice_todo.wav"

GEMINI_MODEL = "gemini-2.5-flash"
API_KEY_ENV = "GOOGLE_API_KEY"

WEATHER_CODE_TEXT = {
    0: "Clear",
    1: "Mostly Clear",
    2: "Partly Cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Rime Fog",
    51: "Light Drizzle",
    53: "Moderate Drizzle",
    55: "Dense Drizzle",
    56: "Light Freezing Drizzle",
    57: "Dense Freezing Drizzle",
    61: "Light Rain",
    63: "Moderate Rain",
    65: "Heavy Rain",
    66: "Light Freezing Rain",
    67: "Heavy Freezing Rain",
    71: "Light Snow",
    73: "Moderate Snow",
    75: "Heavy Snow",
    77: "Snow Grains",
    80: "Light Rain Showers",
    81: "Moderate Rain Showers",
    82: "Heavy Rain Showers",
    85: "Light Snow Showers",
    86: "Heavy Snow Showers",
    95: "Thunderstorm",
    96: "Thunderstorm, Small Hail",
    99: "Thunderstorm, Large Hail",
}

WEEKDAY_MAP = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
MONTH_MAP = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _text_size(draw, text, font):
    bbox = draw.textbbox((0, 0), text, font=font)
    return (bbox[2] - bbox[0], bbox[3] - bbox[1])


def _center_text(draw, text, font, box):
    x0, y0, x1, y1 = box
    w, h = _text_size(draw, text, font)
    x = x0 + (x1 - x0 - w) // 2
    y = y0 + (y1 - y0 - h) // 2
    draw.text((x, y), text, font=font, fill=0)


def _truncate_text(draw, text, font, max_width):
    if not text:
        return text
    try:
        width = draw.textlength(text, font=font)
    except Exception:
        width = _text_size(draw, text, font)[0]
    if width <= max_width:
        return text
    ellipsis = u"..."
    try:
        ell_w = draw.textlength(ellipsis, font=font)
    except Exception:
        ell_w = _text_size(draw, ellipsis, font)[0]
    max_width = max(0, max_width - ell_w)
    trimmed = text
    while trimmed:
        try:
            cur_w = draw.textlength(trimmed, font=font)
        except Exception:
            cur_w = _text_size(draw, trimmed, font)[0]
        if cur_w <= max_width:
            break
        trimmed = trimmed[:-1]
    return (trimmed + ellipsis) if trimmed else ellipsis


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
current_frame = None


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
        return "Unknown"
    try:
        code = int(code)
    except (ValueError, TypeError):
        return "Unknown"
    return WEATHER_CODE_TEXT.get(code, "Unknown")


def _weekday_from_datestr(datestr):
    try:
        d = datetime.strptime(datestr, "%Y-%m-%d")
    except ValueError:
        try:
            d = datetime.fromisoformat(datestr)
        except ValueError:
            return ""
    return WEEKDAY_MAP[d.weekday() % 7]


def _format_date(ts):
    dt = datetime.fromtimestamp(ts)
    weekday = WEEKDAY_MAP[dt.weekday()]
    month = MONTH_MAP[dt.month - 1]
    return "%s, %s %d, %d" % (weekday, month, dt.day, dt.year)


def geocode_city(name, country_code=None, language="en", count=1):
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


def load_todos():
    items = []
    if os.path.exists(TODO_PATH):
        with open(TODO_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                checked = False
                text = line
                if line.startswith("[x]") or line.startswith("[X]"):
                    checked = True
                    text = line[3:].strip()
                elif line.startswith("[ ]"):
                    checked = False
                    text = line[3:].strip()
                items.append((checked, text))
    return items


def todo_stats(items):
    total = len(items)
    done = sum(1 for c, _ in items if c)
    return total, done


def append_todos(todos):
    if not todos:
        return
    existing = set()
    if os.path.exists(TODO_PATH):
        with open(TODO_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("[ ]"):
                    existing.add(line[3:].strip())
                elif line.startswith("[x]") or line.startswith("[X]"):
                    existing.add(line[3:].strip())
    with open(TODO_PATH, "a", encoding="utf-8") as f:
        for t in todos:
            t = t.strip()
            if not t or t in existing:
                continue
            f.write("[ ] %s\n" % t)


def load_reminders():
    if not os.path.exists(REMINDER_PATH):
        return []
    try:
        with open(REMINDER_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
    except Exception:
        return []
    return []


def save_reminders(reminders):
    try:
        with open(REMINDER_PATH, "w", encoding="utf-8") as f:
            json.dump(reminders, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.error("save reminders failed: %s", e)


def add_reminders(reminders):
    if not reminders:
        return
    existing = load_reminders()
    existing_text = {(r.get("text"), r.get("due_ts")) for r in existing}
    now_ts = int(time.time())
    for r in reminders:
        text = r.get("text", "").strip()
        due_ts = r.get("due_ts")
        if not text or due_ts is None:
            continue
        key = (text, due_ts)
        if key in existing_text:
            continue
        existing.append(
            {
                "text": text,
                "due_ts": int(due_ts),
                "done": False,
                "notified": False,
                "created_ts": now_ts,
            }
        )
    save_reminders(existing)


def reminder_stats(reminders):
    active = [r for r in reminders if not r.get("done")]
    return len(active)


def active_reminders(reminders):
    active = [r for r in reminders if not r.get("done")]
    active.sort(key=lambda r: r.get("due_ts") or 0)
    return active


def build_home_task_items(todo_items, reminders, max_items):
    combined = []
    for r in active_reminders(reminders):
        text = (r.get("text") or "").strip()
        if text:
            combined.append((False, "Reminder: " + text))
    combined.extend(todo_items)
    return combined[:max_items]


def build_task_lines(todo_items, reminders, max_lines=10):
    lines = []
    active = active_reminders(reminders)
    if active:
        lines.append("Reminders")
        for r in active:
            if len(lines) >= max_lines:
                return lines
            text = (r.get("text") or "").strip()
            due_ts = r.get("due_ts")
            if due_ts:
                due_text = time.strftime("%m-%d %H:%M", time.localtime(due_ts))
                lines.append(u"- %s (%s)" % (text, due_text))
            else:
                lines.append(u"- %s" % text)
            if len(lines) >= max_lines:
                return lines
    if todo_items:
        if lines:
            lines.append("Todos")
        for checked, text in todo_items:
            if len(lines) >= max_lines:
                return lines
            prefix = u"[x] " if checked else u"[ ] "
            lines.append(prefix + text)
            if len(lines) >= max_lines:
                return lines
    if not lines:
        lines.append("No todos or reminders")
    return lines


def next_due_reminder(reminders, now_ts):
    due_list = [r for r in reminders if (not r.get("done")) and (not r.get("notified")) and r.get("due_ts") is not None]
    due_list.sort(key=lambda r: r.get("due_ts"))
    for r in due_list:
        if r.get("due_ts") <= now_ts:
            return r
    return None


def _word_num_to_int(text):
    if text.isdigit():
        return int(text)
    mapping = {
        "one": 1,
        "two": 2,
        "three": 3,
        "four": 4,
        "five": 5,
        "six": 6,
        "seven": 7,
        "eight": 8,
        "nine": 9,
        "ten": 10,
    }
    return mapping.get(text.lower(), 0)


def parse_due_datetime(text, now):
    lower = text.lower()
    # Relative patterns
    if "day after tomorrow" in lower:
        return (now + timedelta(days=2)).replace(hour=9, minute=0, second=0, microsecond=0)
    if "tomorrow" in lower:
        return (now + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)

    num_pat = r"([0-9]+|one|two|three|four|five|six|seven|eight|nine|ten)"
    m = re.search(r"in\s+" + num_pat + r"\s+days?", lower)
    if m:
        days = _word_num_to_int(m.group(1))
        if days > 0:
            return (now + timedelta(days=days)).replace(hour=9, minute=0, second=0, microsecond=0)
    m = re.search(num_pat + r"\s+days?\s+(later|from\s+now|after)", lower)
    if m:
        days = _word_num_to_int(m.group(1))
        if days > 0:
            return (now + timedelta(days=days)).replace(hour=9, minute=0, second=0, microsecond=0)
    m = re.search(r"in\s+" + num_pat + r"\s+hours?", lower)
    if m:
        hours = _word_num_to_int(m.group(1))
        if hours > 0:
            return now + timedelta(hours=hours)
    m = re.search(r"in\s+" + num_pat + r"\s+minutes?", lower)
    if m:
        minutes = _word_num_to_int(m.group(1))
        if minutes > 0:
            return now + timedelta(minutes=minutes)

    # Absolute date: YYYY-MM-DD or YYYY/MM/DD
    m = re.search(r"(20\d{2})[-/](\d{1,2})[-/](\d{1,2})", text)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return datetime(y, mo, d, 9, 0, 0)
    # Absolute date: MM/DD or MM-DD (assume current year)
    m = re.search(r"(\d{1,2})[/-](\d{1,2})", text)
    if m:
        y = now.year
        mo, d = int(m.group(1)), int(m.group(2))
        return datetime(y, mo, d, 9, 0, 0)
    return None


def extract_reminder_text(text):
    t = text
    for kw in ["remind me", "please remind me", "please remind", "reminder", "remind"]:
        t = t.replace(kw, "")
    t = re.sub(r"in\s+[0-9]+\s+days?", "", t, flags=re.IGNORECASE)
    t = re.sub(r"[0-9]+\s+days?\s+(later|from\s+now|after)", "", t, flags=re.IGNORECASE)
    t = re.sub(r"in\s+[0-9]+\s+hours?", "", t, flags=re.IGNORECASE)
    t = re.sub(r"in\s+[0-9]+\s+minutes?", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\bon\s+(20\d{2})[-/](\d{1,2})[-/](\d{1,2})\b", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\bon\s+(\d{1,2})[/-](\d{1,2})\b", "", t, flags=re.IGNORECASE)
    t = t.replace("tomorrow", "")
    t = t.replace("day after tomorrow", "")
    t = t.replace(" at ", " ")
    t = t.strip()
    return t if t else text.strip()


def analyze_text(text):
    text = text.strip()
    if not text:
        return "", [], []
    api_key = os.environ.get(API_KEY_ENV)
    if api_key and genai is not None:
        try:
            client = genai.Client(api_key=api_key)
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            prompt = (
                "Parse the input into todos or reminders."
                "Return JSON:"
                "{\"transcript\":\"...\",\"todos\":[\"...\"],\"reminders\":[{\"text\":\"...\",\"due\":\"YYYY-MM-DD HH:MM\"}]}\n"
                "If a relative time is mentioned, convert it to an absolute datetime."
                "Current time: " + now
            )
            resp = client.models.generate_content(model=GEMINI_MODEL, contents=[prompt, text])
            raw = (resp.text or "").strip()
            payload = _extract_json(raw)
            if payload:
                data = json.loads(payload)
                transcript = data.get("transcript", text)
                todos = data.get("todos", []) or []
                reminders = []
                for r in data.get("reminders", []) or []:
                    due = r.get("due")
                    due_ts = None
                    try:
                        due_ts = int(datetime.fromisoformat(due).timestamp())
                    except Exception:
                        pass
                    if due_ts:
                        reminders.append({"text": r.get("text", ""), "due_ts": due_ts})
                # If model didn't return reminder but text contains time, add local reminder
                due = parse_due_datetime(text, datetime.now())
                if due and not reminders:
                    reminders.append({"text": extract_reminder_text(text), "due_ts": int(due.timestamp())})
                return transcript, todos, reminders
        except Exception:
            pass

    # Fallback: simple local parse
    now = datetime.now()
    due = parse_due_datetime(text, now)
    if due:
        return text, [], [{"text": extract_reminder_text(text), "due_ts": int(due.timestamp())}]
    return text, [text], []


def _draw_page(title, subtitle, lines, font_title, font_sub, font_body, w, h):
    image = Image.new('1', (w, h), 255)
    draw = ImageDraw.Draw(image)
    margin = 24

    draw.rectangle((0, 0, w - 1, h - 1), outline=0, width=3)
    draw.text((margin, 12), title, font=font_title, fill=0)
    if subtitle:
        draw.text((margin, 60), subtitle, font=font_sub, fill=0)

    y = 110
    for line in lines:
        draw.text((margin, y), line, font=font_body, fill=0)
        y += 40
        if y > h - 40:
            break

    return image


def _record_audio_fixed():
    if os.path.exists(AUDIO_PATH):
        try:
            os.remove(AUDIO_PATH)
        except Exception:
            pass

    cmd = [
        "arecord",
        "-D",
        AUDIO_DEVICE,
        "-f",
        "S16_LE",
        "-r",
        str(AUDIO_RATE),
        "-c",
        str(AUDIO_CHANNELS),
        "-d",
        str(RECORD_MAX_SEC),
        "-t",
        "wav",
        AUDIO_PATH,
    ]
    logging.info("recording: %s", " ".join(cmd))
    subprocess.call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    if os.path.exists(AUDIO_PATH) and os.path.getsize(AUDIO_PATH) > 0:
        return AUDIO_PATH
    return None


def _record_audio_until_release(pin):
    if os.path.exists(AUDIO_PATH):
        try:
            os.remove(AUDIO_PATH)
        except Exception:
            pass

    cmd = [
        "arecord",
        "-D",
        AUDIO_DEVICE,
        "-f",
        "S16_LE",
        "-r",
        str(AUDIO_RATE),
        "-c",
        str(AUDIO_CHANNELS),
        "-t",
        "wav",
        AUDIO_PATH,
    ]
    logging.info("recording: %s", " ".join(cmd))
    proc = subprocess.Popen(cmd, preexec_fn=os.setsid, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    start = time.time()
    while True:
        if BUTTON_ACTIVE_LOW:
            pressed = GPIO.input(pin) == GPIO.LOW
        else:
            pressed = GPIO.input(pin) == GPIO.HIGH
        if not pressed:
            break
        if time.time() - start >= RECORD_MAX_SEC:
            break
        time.sleep(0.05)

    try:
        os.killpg(proc.pid, signal.SIGINT)
        proc.wait(timeout=2)
    except Exception:
        try:
            proc.terminate()
        except Exception:
            pass

    if os.path.exists(AUDIO_PATH) and os.path.getsize(AUDIO_PATH) > 0:
        return AUDIO_PATH
    return None


def _extract_json(text):
    text = text.strip()
    if text.startswith("{") and text.endswith("}"):
        return text
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start:end + 1]
    return None


def transcribe_and_extract(audio_path):
    api_key = os.environ.get(API_KEY_ENV)
    if not api_key:
        raise RuntimeError("missing API key env: %s" % API_KEY_ENV)
    if genai is None:
        raise RuntimeError("google-genai not installed. pip install google-genai")

    client = genai.Client(api_key=api_key)
    myfile = client.files.upload(file=audio_path)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    prompt = (
        "Transcribe the audio into English text and extract todos/reminders."
        "Output JSON only, format:"
        "{\"transcript\":\"...\",\"todos\":[\"...\"],\"reminders\":[{\"text\":\"...\",\"due\":\"YYYY-MM-DD HH:MM\"}]}"
        "If a relative time is mentioned, convert it to an absolute datetime."
        "Current time: " + now
    )
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=[prompt, myfile],
    )
    text = (response.text or "").strip()
    payload = _extract_json(text)
    if payload:
        data = json.loads(payload)
        transcript = data.get("transcript", "")
        todos = data.get("todos", [])
        reminders = []
        for r in data.get("reminders", []) or []:
            due = r.get("due")
            due_ts = None
            try:
                due_ts = int(datetime.fromisoformat(due).timestamp())
            except Exception:
                pass
            if due_ts:
                reminders.append({"text": r.get("text", ""), "due_ts": due_ts})
        return transcript, [t for t in todos if isinstance(t, str) and t.strip()], reminders

    return text, [], []


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
    font_sub = ImageFont.truetype(font_path, 28)
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
        date_text = _format_date(time.time())
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
        draw.text((left_box[0] + left_pad, left_box[1] + 12), "Today's Weather", font=font_title, fill=0)
        _draw_weather_icon(draw, left_box[0] + left_pad, left_box[1] + 64)

        right_pad = 16
        draw.text((right_box[0] + right_pad, right_box[1] + 12), "Today's Tasks", font=font_title, fill=0)
        draw.line((right_box[0] + 12, right_box[1] + 148, right_box[2] - 12, right_box[1] + 148), fill=0, width=1)
        draw.line((right_box[0] + 12, right_box[1] + 178, right_box[2] - 12, right_box[1] + 178), fill=0, width=1)

        draw.line((margin, bottom_top, w - margin, bottom_top), fill=0, width=2)
        for i in range(1, 3):
            x = margin + col_w * i
            draw.line((x, bottom_top + 10, x, h - 10), fill=0, width=2)

        labels = ["Reminders", "Temp", "Done"]
        for i in range(3):
            x0 = margin + col_w * i
            x1 = x0 + col_w
            _center_text(draw, labels[i], font_small, (x0, bottom_top + 10, x1, bottom_top + 36))

        return base, (time_x, time_y, time_w, time_h), (date_x, date_y, date_w, date_h), font_time, font_date

    def draw_time(draw, now, time_info, date_info, font_time, font_date):
        time_x, time_y, _, _ = time_info
        date_x, date_y, _, _ = date_info
        date_text = _format_date(now)
        time_text = time.strftime('%H:%M:%S', time.localtime(now))
        draw.text((time_x, time_y), time_text, font=font_time, fill=0)
        draw.text((date_x, date_y), date_text, font=font_date, fill=0)

    def draw_weather_content(draw, weather):
        left_pad = 16
        temp = None
        desc = u"--"
        city = CITY_NAME
        if weather and weather.get("current"):
            temp = weather["current"].get("temperature")
            desc = _weather_text(weather["current"].get("weather_code"))
            city = weather.get("city", city)
        temp_text = u"--"
        if temp is not None:
            temp_text = u"%d°C" % int(round(temp))
        draw.text((left_box[0] + left_pad + 92, left_box[1] + 78), temp_text, font=font_big, fill=0)
        draw.text((left_box[0] + left_pad + 92, left_box[1] + 150), desc, font=font_med, fill=0)
        draw.text((left_box[0] + left_pad + 92, left_box[1] + 182), city, font=font_med, fill=0)

    def draw_todo_content(draw, items, reminders):
        right_pad = 16
        check_x = right_box[0] + right_pad
        item_x = check_x + 32
        row_y = right_box[1] + 68
        row_gap = 42
        show_items = build_home_task_items(items, reminders, MAX_TODO_SHOW)
        max_width = right_box[2] - item_x - 12
        for i in range(MAX_TODO_SHOW):
            y = row_y + i * row_gap
            checked = False
            text = u""
            if i < len(show_items):
                checked, text = show_items[i]
            _draw_checkbox(draw, check_x, y, 18, checked=checked)
            if text:
                text = _truncate_text(draw, text, font_med, max_width)
                draw.text((item_x, y - 6), text, font=font_med, fill=0)

        total, done = todo_stats(items)
        rem_count = reminder_stats(reminders)
        footer = "Done: %d/%d  Reminders: %d" % (done, total, rem_count)
        footer = _truncate_text(draw, footer, font_small, right_box[2] - right_box[0] - right_pad * 2)
        draw.text((right_box[0] + right_pad, right_box[1] + 194), footer, font=font_small, fill=0)

    def draw_bottom_stats(draw, items, weather, reminders):
        total, done = todo_stats(items)
        rem_count = reminder_stats(reminders)
        temp_text = u"--"
        if weather and weather.get("current") and weather["current"].get("temperature") is not None:
            temp_text = u"%d°" % int(round(weather["current"]["temperature"]))
        values = [str(rem_count), temp_text, str(done)]
        for i in range(3):
            x0 = margin + col_w * i
            x1 = x0 + col_w
            _center_text(draw, values[i], font_med, (x0, bottom_top + 36, x1, h - 10))

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

    def _aligned_region(box):
        x0, y0, x1, y1 = box
        x0 = _align8_floor(int(max(0, x0)))
        y0 = _align8_floor(int(max(0, y0)))
        x1 = _align8_ceil(int(min(w, x1)))
        y1 = _align8_ceil(int(min(h, y1)))
        if x1 <= x0 or y1 <= y0:
            return None
        return (x0, y0, x1 - x0, y1 - y0)

    current_frame = None

    def update_time_region(now):
        global current_frame
        region = (0, 0, w, header_h)
        current_frame.paste(base_home.crop(region), region)
        draw = ImageDraw.Draw(current_frame)
        draw_time(draw, now, time_info, date_info, font_time, font_date)
        aligned = _aligned_region(region)
        if aligned:
            _display_partial(epd, current_frame, *aligned)

    def update_weather_region():
        global current_frame
        region = left_box
        current_frame.paste(base_home.crop(region), region)
        draw = ImageDraw.Draw(current_frame)
        draw_weather_content(draw, weather_data)
        if selected == "weather":
            draw_selection(draw, selected)
        aligned = _aligned_region(region)
        if aligned:
            _display_partial(epd, current_frame, *aligned)

    def update_todo_region():
        global current_frame
        region = right_box
        current_frame.paste(base_home.crop(region), region)
        draw = ImageDraw.Draw(current_frame)
        draw_todo_content(draw, todo_items, reminders)
        if selected == "todo":
            draw_selection(draw, selected)
        aligned = _aligned_region(region)
        if aligned:
            _display_partial(epd, current_frame, *aligned)

    def update_bottom_region():
        global current_frame
        region = (margin, bottom_top, w - margin, h)
        current_frame.paste(base_home.crop(region), region)
        draw = ImageDraw.Draw(current_frame)
        draw_bottom_stats(draw, todo_items, weather_data, reminders)
        if selected in ("bottom1", "bottom2", "bottom3"):
            draw_selection(draw, selected)
        aligned = _aligned_region(region)
        if aligned:
            _display_partial(epd, current_frame, *aligned)

    def render_home_full(use_full=False):
        global current_frame
        now = time.time()
        current_frame = base_home.copy()
        draw = ImageDraw.Draw(current_frame)
        draw_time(draw, now, time_info, date_info, font_time, font_date)
        draw_weather_content(draw, weather_data)
        draw_todo_content(draw, todo_items, reminders)
        draw_bottom_stats(draw, todo_items, weather_data, reminders)
        draw_selection(draw, selected)
        if use_full:
            _display_full(epd, current_frame)
        else:
            _display_full_partial(epd, current_frame, w, h)

    def draw_weather_page(weather_data, error_msg=None):
        base = Image.new('1', (w, h), 255)
        draw = ImageDraw.Draw(base)

        draw.rectangle((0, 0, w - 1, h - 1), outline=0, width=3)
        draw.text((margin, 14), "Weather", font=font_title_big, fill=0)

        if weather_data:
            city = weather_data.get("city", CITY_NAME)
            update_text = time.strftime('%H:%M', time.localtime(weather_data.get("fetched_at", time.time())))
            header_right = city + "  Updated " + update_text
            w_header, h_header = _text_size(draw, header_right, font_small)
            draw.text((w - margin - w_header, 22), header_right, font=font_small, fill=0)

        draw.line((margin, 60, w - margin, 60), fill=0, width=2)

        if error_msg:
            draw.text((margin, 100), "Weather fetch failed", font=font_title, fill=0)
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
        draw.text((right_x, line_y), "Feels", font=font_small, fill=0)
        draw.text((right_x + 90, line_y - 6), (u"%d°C" % int(round(feels))) if feels is not None else u"--", font=font_med, fill=0)

        draw.text((right_x, line_y + 40), "Humidity", font=font_small, fill=0)
        draw.text((right_x + 90, line_y + 34), (u"%d%%" % int(round(humidity))) if humidity is not None else u"--", font=font_med, fill=0)

        draw.text((right_x, line_y + 80), "Wind", font=font_small, fill=0)
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
            draw.text((margin, forecast_top + 20), "No forecast data", font=font_small, fill=0)

        draw.text((margin, h - 34), "Enter Open / B Back / R Refresh", font=font_small, fill=0)
        return base

    def draw_todo_page(items, reminders):
        lines = build_task_lines(items, reminders, max_lines=10)
        return _draw_page("Tasks & Reminders", "V Voice / T Text / B Back", lines, font_title_big, font_sub, font_small, w, h)

    def draw_reminders_page(reminders):
        lines = []
        active = active_reminders(reminders)
        if active:
            for r in active[:9]:
                text = (r.get("text") or "").strip()
                due_ts = r.get("due_ts")
                if due_ts:
                    due_text = time.strftime("%m-%d %H:%M", time.localtime(due_ts))
                    lines.append(u"- %s (%s)" % (text, due_text))
                else:
                    lines.append(u"- %s" % text)
        else:
            lines.append("No reminders")
        return _draw_page("Reminder List", "B Back", lines, font_title_big, font_sub, font_small, w, h)

    def draw_reminder_page(reminder):
        title = "Reminder"
        if not reminder:
            return _draw_page(title, "", ["No reminders"], font_title_big, font_sub, font_small, w, h)
        text = reminder.get("text", "")
        due_ts = reminder.get("due_ts")
        due_text = u""
        if due_ts:
            due_text = time.strftime("%Y-%m-%d %H:%M", time.localtime(due_ts))
        lines = [text]
        if due_text:
            lines.append("Time: " + due_text)
        lines.append("Enter Done / B Ignore")
        return _draw_page(title, "", lines, font_title_big, font_sub, font_small, w, h)

    def draw_loading_page(text="Fetching weather..."):
        base = Image.new('1', (w, h), 255)
        draw = ImageDraw.Draw(base)
        draw.rectangle((0, 0, w - 1, h - 1), outline=0, width=3)
        _center_text(draw, text, font_title, (0, 0, w, h))
        return base

    selected = "weather"
    view = "home"
    weather_data = None
    weather_error = None
    todo_items = load_todos()
    reminders = load_reminders()
    todo_mtime = os.path.getmtime(TODO_PATH) if os.path.exists(TODO_PATH) else 0
    reminder_mtime = os.path.getmtime(REMINDER_PATH) if os.path.exists(REMINDER_PATH) else 0
    last_todo_check = 0
    last_reminder_check = 0
    current_reminder = None

    # GPIO setup (optional)
    if GPIO is not None and BUTTON_PIN is not None:
        GPIO.setmode(GPIO.BCM)
        if BUTTON_ACTIVE_LOW:
            GPIO.setup(BUTTON_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            edge = GPIO.FALLING
        else:
            GPIO.setup(BUTTON_PIN, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
            edge = GPIO.RISING
        GPIO.add_event_detect(BUTTON_PIN, edge, bouncetime=DEBOUNCE_MS)
    else:
        logging.info("GPIO button disabled (GPIO not available or BUTTON_PIN is None)")

    weather_lock = threading.Lock()
    weather_state = {"data": None, "error": None, "updated": False}

    def weather_worker():
        while True:
            try:
                data = fetch_weather()
                err = None
            except Exception as e:
                data = None
                err = str(e)
            with weather_lock:
                weather_state["data"] = data
                weather_state["error"] = err
                weather_state["updated"] = True
            time.sleep(WEATHER_REFRESH_SEC)

    threading.Thread(target=weather_worker, daemon=True).start()

    try:
        weather_data = fetch_weather()
    except Exception as e:
        weather_error = str(e)

    base_home, time_info, date_info, font_time, font_date = draw_home_base()
    current_frame = base_home.copy()
    render_home_full(use_full=True)

    logging.info("start event loop")
    epd.init_part()

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

    def read_key(timeout):
        rlist, _, _ = select.select([input_stream], [], [], timeout)
        if not rlist:
            return None
        data = input_stream.read(1)
        if not data:
            return None
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
        elif ch in ('v', 'V'):
            key = 'voice'
        elif ch in ('t', 'T'):
            key = 'text'
        return key

    def wait_for_key(valid):
        while True:
            key = read_key(None)
            if key in valid:
                return key

    def read_text_line():
        buf = []
        while True:
            data = input_stream.read(1)
            if not data:
                continue
            if isinstance(data, bytes):
                ch = data.decode('utf-8', errors='ignore')
            else:
                ch = data
            if ch in ('\r', '\n'):
                return ''.join(buf)
            if ch == '\x03':
                raise KeyboardInterrupt
            if ch in ('\x7f', '\b'):
                if buf:
                    buf.pop()
                continue
            if ch == '\x1b':
                _ = input_stream.read(2)
                continue
            if ch:
                buf.append(ch)

    def text_input_flow():
        global todo_items, todo_mtime, reminders, reminder_mtime
        page = _draw_page("Text Input", "Type then Enter", ["Example: remind me milk expires in 3 days"], font_title_big, font_sub, font_small, w, h)
        _display_full_partial(epd, page, w, h)
        line = read_text_line().strip()
        if not line:
            return
        transcript, todos, new_reminders = analyze_text(line)
        append_todos(todos)
        add_reminders(new_reminders)
        todo_items = load_todos()
        reminders = load_reminders()
        if os.path.exists(TODO_PATH):
            todo_mtime = os.path.getmtime(TODO_PATH)
        if os.path.exists(REMINDER_PATH):
            reminder_mtime = os.path.getmtime(REMINDER_PATH)
        lines = []
        if todos:
            lines.append("Added todos:")
            for t in todos[:4]:
                lines.append(u"- " + t)
        if new_reminders:
            lines.append("Added reminders:")
            for r in new_reminders[:3]:
                lines.append(u"- " + r.get("text", ""))
        if not lines:
            lines.append("No todos/reminders recognized")
        done = _draw_page("Done", "Saved", lines, font_title_big, font_sub, font_small, w, h)
        _display_full_partial(epd, done, w, h)
        time.sleep(1)

    def voice_flow(use_button=False):
        global todo_items, todo_mtime, reminders, reminder_mtime
        while True:
            subtitle = "Release button to stop" if use_button else ("Speak within %d seconds" % RECORD_MAX_SEC)
            recording = _draw_page("Recording...", subtitle, [], font_title_big, font_sub, font_small, w, h)
            _display_full_partial(epd, recording, w, h)
            if use_button and GPIO is not None:
                audio = _record_audio_until_release(BUTTON_PIN)
            else:
                audio = _record_audio_fixed()
            if not audio:
                err = _draw_page("Recording failed", "V Retry / T Text / B Back", [], font_title_big, font_sub, font_small, w, h)
                _display_full_partial(epd, err, w, h)
                k = wait_for_key({"voice", "text", "back"})
                if k == "voice":
                    continue
                if k == "text":
                    text_input_flow()
                return
            processing = _draw_page("Processing...", "Please wait", [], font_title_big, font_sub, font_small, w, h)
            _display_full_partial(epd, processing, w, h)
            try:
                transcript, todos, new_reminders = transcribe_and_extract(audio)
            except Exception as e:
                err = _draw_page("Recognition failed", str(e), ["V Retry", "T Text", "B Back"], font_title_big, font_sub, font_small, w, h)
                _display_full_partial(epd, err, w, h)
                k = wait_for_key({"voice", "text", "back"})
                if k == "voice":
                    continue
                if k == "text":
                    text_input_flow()
                return

            if transcript and not todos and not new_reminders:
                _, todos, new_reminders = analyze_text(transcript)
            if transcript and not new_reminders:
                due = parse_due_datetime(transcript, datetime.now())
                if due:
                    new_reminders = [{"text": extract_reminder_text(transcript), "due_ts": int(due.timestamp())}]

            if todos:
                append_todos(todos)
                todo_items = load_todos()
                if os.path.exists(TODO_PATH):
                    todo_mtime = os.path.getmtime(TODO_PATH)
            if new_reminders:
                add_reminders(new_reminders)
                reminders = load_reminders()
                if os.path.exists(REMINDER_PATH):
                    reminder_mtime = os.path.getmtime(REMINDER_PATH)

            lines = []
            if transcript:
                lines.append("Heard: " + transcript[:16])
                if len(transcript) > 16:
                    lines.append(transcript[16:32])
            if todos:
                lines.append("Added todos:")
                for t in todos[:5]:
                    lines.append(u"- " + t)
            if new_reminders:
                lines.append("Added reminders:")
                for r in new_reminders[:3]:
                    lines.append(u"- " + r.get("text", ""))
            if not todos and not new_reminders:
                lines.append("No todos/reminders recognized")

            done = _draw_page("Done", "Saved to todo.txt", lines, font_title_big, font_sub, font_small, w, h)
            _display_full_partial(epd, done, w, h)
            time.sleep(1.5)
            return

    last_sec = None
    try:
        while True:
            now = time.time()

            if view == "home":
                sec = int(now)
                if sec != last_sec:
                    last_sec = sec
                    update_time_region(now)

            with weather_lock:
                if weather_state["updated"]:
                    weather_state["updated"] = False
                    weather_data = weather_state["data"]
                    weather_error = weather_state["error"]
                    if view == "home":
                        update_weather_region()
                        update_bottom_region()
                    elif view == "weather":
                        page = draw_weather_page(weather_data, weather_error)
                        _display_full_partial(epd, page, w, h)

            if now - last_todo_check >= TODO_REFRESH_SEC:
                last_todo_check = now
                if os.path.exists(TODO_PATH):
                    mtime = os.path.getmtime(TODO_PATH)
                    if mtime != todo_mtime:
                        todo_mtime = mtime
                        todo_items = load_todos()
                        if view == "home":
                            update_todo_region()
                            update_bottom_region()
                        elif view == "todo":
                            _display_full_partial(epd, draw_todo_page(todo_items, reminders), w, h)

            if now - last_reminder_check >= REMINDER_REFRESH_SEC:
                last_reminder_check = now
                if os.path.exists(REMINDER_PATH):
                    mtime = os.path.getmtime(REMINDER_PATH)
                    if mtime != reminder_mtime:
                        reminder_mtime = mtime
                        reminders = load_reminders()
                        if view == "home":
                            update_todo_region()
                            update_bottom_region()
                        elif view == "todo":
                            _display_full_partial(epd, draw_todo_page(todo_items, reminders), w, h)
                        elif view == "reminders":
                            _display_full_partial(epd, draw_reminders_page(reminders), w, h)

            # Reminder due check
            if view in ("home", "todo", "weather"):
                due = next_due_reminder(reminders, int(now))
                if due is not None:
                    current_reminder = due
                    view = "reminder"
                    _display_full_partial(epd, draw_reminder_page(current_reminder), w, h)

            if GPIO is not None and BUTTON_PIN is not None and GPIO.event_detected(BUTTON_PIN):
                if view == "home" and selected == "todo":
                    view = "todo"
                    _display_full_partial(epd, draw_todo_page(todo_items, reminders), w, h)

            timeout = 0.1 if view != "home" else max(0.01, (int(time.time()) + 1) - time.time())
            key = read_key(timeout)
            if not key:
                continue

            if key == "snapshot":
                _save_last_frame(last_frame_image)
                logging.info("snapshot saved to %s", LAST_FRAME_PATH)
                continue

            if view == "home":
                if key and key in neighbors.get(selected, {}):
                    selected = neighbors[selected][key]
                    if SELECTION_FULL_PARTIAL:
                        render_home_full(use_full=False)
                    else:
                        render_home_full(use_full=False)
                elif key == "enter" and selected == "weather":
                    view = "weather"
                    if weather_data is None:
                        _display_full_partial(epd, draw_loading_page(), w, h)
                        try:
                            weather_data = fetch_weather()
                            weather_error = None
                        except Exception as e:
                            weather_error = str(e)
                    page = draw_weather_page(weather_data, weather_error)
                    _display_full_partial(epd, page, w, h)
                elif key == "enter" and selected == "todo":
                    view = "todo"
                    _display_full_partial(epd, draw_todo_page(todo_items, reminders), w, h)
                elif key == "voice" and selected == "todo":
                    view = "todo"
                    _display_full_partial(epd, draw_todo_page(todo_items, reminders), w, h)
                    voice_flow(use_button=False)
                    _display_full_partial(epd, draw_todo_page(todo_items, reminders), w, h)
                elif key == "text" and selected == "todo":
                    view = "todo"
                    _display_full_partial(epd, draw_todo_page(todo_items, reminders), w, h)
                    text_input_flow()
                    _display_full_partial(epd, draw_todo_page(todo_items, reminders), w, h)
                elif key == "enter" and selected == "bottom1":
                    view = "reminders"
                    _display_full_partial(epd, draw_reminders_page(reminders), w, h)
                elif key == "enter" and selected in ("bottom2", "bottom3"):
                    view = "todo"
                    _display_full_partial(epd, draw_todo_page(todo_items, reminders), w, h)
            elif view == "weather":
                if key == "back":
                    view = "home"
                    render_home_full(use_full=False)
                elif key == "refresh":
                    try:
                        weather_data = fetch_weather()
                        weather_error = None
                    except Exception as e:
                        weather_error = str(e)
                    page = draw_weather_page(weather_data, weather_error)
                    _display_full_partial(epd, page, w, h)
            elif view == "todo":
                if key == "back":
                    view = "home"
                    render_home_full(use_full=False)
                elif key == "voice":
                    voice_flow(use_button=False)
                    _display_full_partial(epd, draw_todo_page(todo_items, reminders), w, h)
                elif key == "text":
                    text_input_flow()
                    _display_full_partial(epd, draw_todo_page(todo_items, reminders), w, h)
            elif view == "reminders":
                if key == "back":
                    view = "home"
                    render_home_full(use_full=False)
            elif view == "reminder":
                if key in ("enter", "back"):
                    # mark reminder as done or notified
                    for r in reminders:
                        if r.get("text") == current_reminder.get("text") and r.get("due_ts") == current_reminder.get("due_ts"):
                            if key == "enter":
                                r["done"] = True
                            r["notified"] = True
                    save_reminders(reminders)
                    reminder_mtime = os.path.getmtime(REMINDER_PATH) if os.path.exists(REMINDER_PATH) else reminder_mtime
                    current_reminder = None
                    view = "home"
                    render_home_full(use_full=False)

    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        if opened_tty:
            try:
                input_stream.close()
            except Exception:
                pass
        # Skip GPIO.cleanup here to avoid conflicts with epdconfig/module_exit on ctrl+c

except IOError as e:
    logging.info(e)

except KeyboardInterrupt:
    logging.info("ctrl + c:")
    epd7in5_V2.epdconfig.module_exit(cleanup=True)
