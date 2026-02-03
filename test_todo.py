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

MAX_ITEMS = 8


def _text_size(draw, text, font):
    bbox = draw.textbbox((0, 0), text, font=font)
    return (bbox[2] - bbox[0], bbox[3] - bbox[1])


def _load_items(path):
    items = []
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                items.append(line)
                if len(items) >= MAX_ITEMS:
                    break
    if not items:
        items = [
            "[ ] Clean fridge",
            "[ ] Restock milk",
            "[x] Replace sticky note",
            "[ ] Buy fruit",
        ]
    return items


def _parse_item(line):
    line = line.strip()
    if line.startswith("[x]") or line.startswith("[X]"):
        return True, line[3:].strip()
    if line.startswith("[ ]"):
        return False, line[3:].strip()
    return False, line


def _draw_checkbox(draw, x, y, size, checked):
    draw.rectangle((x, y, x + size, y + size), outline=0, fill=255)
    if checked:
        inset = 4
        draw.rectangle((x + inset, y + inset, x + size - inset, y + size - inset), fill=0)


try:
    logging.info("epd7in5_V2 todo demo")
    epd = epd7in5_V2.EPD()

    logging.info("init and Clear")
    epd.init()
    epd.Clear()

    font_path = os.path.join(picdir, 'Font.ttc')
    font_title = ImageFont.truetype(font_path, 64)
    font_item = ImageFont.truetype(font_path, 40)

    image = Image.new('1', (epd.width, epd.height), 255)
    draw = ImageDraw.Draw(image)

    margin = 24
    title = "Todo List"
    title_w, title_h = _text_size(draw, title, font_title)
    title_x = (epd.width - title_w) // 2
    title_y = margin
    draw.text((title_x, title_y), title, font=font_title, fill=0)

    line_y = title_y + title_h + 18
    draw.line((margin, line_y, epd.width - margin, line_y), fill=0, width=2)

    items = _load_items(os.path.join(base_dir, 'todo.txt'))

    box_size = 28
    item_gap = 14
    start_y = line_y + 18
    row_h = max(box_size, _text_size(draw, "Test", font_item)[1]) + item_gap

    for idx, raw in enumerate(items):
        checked, text = _parse_item(raw)
        y = start_y + idx * row_h
        if y + row_h > epd.height - margin:
            break
        _draw_checkbox(draw, margin, y + 6, box_size, checked)
        text_x = margin + box_size + 16
        draw.text((text_x, y), text, font=font_item, fill=0)

    epd.display(epd.getbuffer(image))

    logging.info("Goto Sleep...")
    epd.sleep()

except IOError as e:
    logging.info(e)

except KeyboardInterrupt:
    logging.info("ctrl + c:")
    epd7in5_V2.epdconfig.module_exit(cleanup=True)
