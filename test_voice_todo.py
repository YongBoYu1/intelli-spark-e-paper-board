#!/usr/bin/python
# -*- coding:utf-8 -*-
import sys
import os
import time
import json
import logging
import glob
import subprocess
import signal
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont

# Optional: GPIO for button
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
TODO_PATH = os.path.join(base_dir, "todo.txt")

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

# ====== Config ======
BUTTON_PIN = 17  # BCM pin
BUTTON_ACTIVE_LOW = True
DEBOUNCE_MS = 200

AUDIO_DEVICE = "default"  # use `arecord -l` to find, e.g., "plughw:1,0"
AUDIO_RATE = 16000
AUDIO_CHANNELS = 1
RECORD_MAX_SEC = 8
AUDIO_PATH = "/tmp/voice_todo.wav"

GEMINI_MODEL = "gemini-2.5-flash"
API_KEY_ENV = "GOOGLE_API_KEY"

MAX_TODOS = 6

# ====== Helpers ======
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


def _text_size(draw, text, font):
    bbox = draw.textbbox((0, 0), text, font=font)
    return (bbox[2] - bbox[0], bbox[3] - bbox[1])


def _center_text(draw, text, font, box):
    x0, y0, x1, y1 = box
    w, h = _text_size(draw, text, font)
    x = x0 + (x1 - x0 - w) // 2
    y = y0 + (y1 - y0 - h) // 2
    draw.text((x, y), text, font=font, fill=0)


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

    prompt = (
        "请把音频内容转写成中文文本，并提取待办事项。"
        "只输出 JSON，格式："
        "{\"transcript\":\"...\",\"todos\":[\"...\",\"...\"]}"
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
        return transcript, [t for t in todos if isinstance(t, str) and t.strip()]

    return text, []


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


def main():
    logging.info("voice todo demo start")

    if GPIO is None:
        logging.error("RPi.GPIO not available. Please install or run on Raspberry Pi.")
        return

    epd = epd7in5_V2.EPD()
    epd.init()
    epd.Clear()

    font_path = os.path.join(picdir, 'Font.ttc')
    font_title = ImageFont.truetype(font_path, 36)
    font_sub = ImageFont.truetype(font_path, 28)
    font_body = ImageFont.truetype(font_path, 26)

    w, h = epd.width, epd.height

    GPIO.setmode(GPIO.BCM)
    if BUTTON_ACTIVE_LOW:
        GPIO.setup(BUTTON_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    else:
        GPIO.setup(BUTTON_PIN, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)

    idle = _draw_page(u"语音待办", u"按下按钮开始说话", [u"建议语速清晰", u"最多 %d 秒" % RECORD_MAX_SEC], font_title, font_sub, font_body, w, h)
    _display_full(epd, idle)

    try:
        while True:
            GPIO.wait_for_edge(BUTTON_PIN, GPIO.FALLING if BUTTON_ACTIVE_LOW else GPIO.RISING, bouncetime=DEBOUNCE_MS)

            recording = _draw_page(u"正在录音...", u"松开按钮结束", [], font_title, font_sub, font_body, w, h)
            _display_full(epd, recording)
            audio = _record_audio_until_release(BUTTON_PIN)
            if not audio:
                error = _draw_page(u"录音失败", u"请重试", [], font_title, font_sub, font_body, w, h)
                _display_full(epd, error)
                time.sleep(1)
                _display_full(epd, idle)
                continue

            processing = _draw_page(u"识别中...", u"请稍候", [], font_title, font_sub, font_body, w, h)
            _display_full(epd, processing)
            try:
                transcript, todos = transcribe_and_extract(audio)
            except Exception as e:
                err = _draw_page(u"识别失败", str(e), [], font_title, font_sub, font_body, w, h)
                _display_full(epd, err)
                time.sleep(2)
                _display_full(epd, idle)
                continue

            if todos:
                append_todos(todos)

            lines = []
            if transcript:
                lines.append(u"听到：" + transcript[:18])
                if len(transcript) > 18:
                    lines.append(transcript[18:36])
            if todos:
                lines.append(u"新增待办：")
                for t in todos[:MAX_TODOS]:
                    lines.append(u"- " + t)
            else:
                lines.append(u"未识别到待办")

            done = _draw_page(u"完成", u"已保存到 todo.txt", lines, font_title, font_sub, font_body, w, h)
            _display_full(epd, done)
            time.sleep(2)
            _display_full(epd, idle)

    finally:
        GPIO.cleanup()


if __name__ == "__main__":
    main()
