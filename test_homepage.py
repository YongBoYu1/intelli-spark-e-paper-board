#!/usr/bin/python
# -*- coding:utf-8 -*-
import sys
import os
import time
import logging
import glob
from PIL import Image, ImageDraw, ImageFont

base_dir = os.path.dirname(os.path.realpath(__file__))
default_root = os.path.dirname(base_dir)
picdir = os.path.join(default_root, 'pic')
libdir = os.path.join(default_root, 'lib')

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

logging.basicConfig(level=logging.INFO)


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


try:
    logging.info("epd7in5_V2 homepage demo")
    epd = epd7in5_V2.EPD()

    logging.info("init and Clear")
    epd.init()
    epd.Clear()

    font_path = os.path.join(picdir, 'Font.ttc')
    font_time = ImageFont.truetype(font_path, 108)
    font_date = ImageFont.truetype(font_path, 28)
    font_title = ImageFont.truetype(font_path, 32)
    font_big = ImageFont.truetype(font_path, 64)
    font_med = ImageFont.truetype(font_path, 30)
    font_small = ImageFont.truetype(font_path, 24)

    image = Image.new('1', (epd.width, epd.height), 255)
    draw = ImageDraw.Draw(image)

    w, h = epd.width, epd.height
    margin = 20
    header_h = int(h * 0.28)
    bottom_h = int(h * 0.12)
    mid_h = h - header_h - bottom_h

    # Outer border
    draw.rectangle((0, 0, w - 1, h - 1), outline=0, width=3)

    # Header
    time_text = time.strftime('%H:%M')
    date_text = time.strftime('%Y年%-m月%-d日 星期%w')
    # Python on some systems doesn't support %-m/-d; fallback if needed
    if '%' in date_text:
        date_text = time.strftime('%Y年%m月%d日 星期%w')

    _center_text(draw, time_text, font_time, (0, 8, w, header_h - 20))
    _center_text(draw, date_text, font_date, (0, header_h - 40, w, header_h))

    # Divider line
    draw.line((margin, header_h, w - margin, header_h), fill=0, width=2)

    # Middle section boxes
    mid_top = header_h + 16
    mid_bottom = header_h + mid_h - 16
    mid_left = margin
    mid_right = w - margin
    gap = 16
    box_w = (mid_right - mid_left - gap) // 2
    box_h = mid_bottom - mid_top

    left_box = (mid_left, mid_top, mid_left + box_w, mid_bottom)
    right_box = (mid_left + box_w + gap, mid_top, mid_right, mid_bottom)

    draw.rectangle(left_box, outline=0, width=2)
    draw.rectangle(right_box, outline=0, width=2)

    # Left box: Weather
    draw.text((left_box[0] + 18, left_box[1] + 14), u"今日天气", font=font_title, fill=0)
    _draw_weather_icon(draw, left_box[0] + 18, left_box[1] + 70)
    draw.text((left_box[0] + 120, left_box[1] + 88), u"16°C", font=font_big, fill=0)
    draw.text((left_box[0] + 120, left_box[1] + 160), u"雨天", font=font_med, fill=0)
    draw.text((left_box[0] + 120, left_box[1] + 200), u"北京", font=font_med, fill=0)

    # Right box: Todo
    draw.text((right_box[0] + 18, right_box[1] + 14), u"今日待办", font=font_title, fill=0)
    check_x = right_box[0] + 18
    item_x = check_x + 34
    row_y = right_box[1] + 70
    row_gap = 46

    _draw_checkbox(draw, check_x, row_y, 20, checked=True)
    draw.text((item_x, row_y - 6), u"买菜", font=font_med, fill=0)

    _draw_checkbox(draw, check_x, row_y + row_gap, 20, checked=False)
    draw.text((item_x, row_y + row_gap - 6), u"健身", font=font_med, fill=0)

    draw.line((right_box[0] + 12, right_box[1] + 150, right_box[2] - 12, right_box[1] + 150), fill=0, width=1)
    draw.line((right_box[0] + 12, right_box[1] + 182, right_box[2] - 12, right_box[1] + 182), fill=0, width=1)

    draw.text((right_box[0] + 18, right_box[1] + 200), u"已完成：1 / 3", font=font_small, fill=0)

    # Bottom stats bar
    bottom_top = header_h + mid_h
    draw.line((margin, bottom_top, w - margin, bottom_top), fill=0, width=2)

    col_w = (w - margin * 2) // 3
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

    epd.display(epd.getbuffer(image))

    logging.info("Goto Sleep...")
    epd.sleep()

except IOError as e:
    logging.info(e)

except KeyboardInterrupt:
    logging.info("ctrl + c:")
    epd7in5_V2.epdconfig.module_exit(cleanup=True)
