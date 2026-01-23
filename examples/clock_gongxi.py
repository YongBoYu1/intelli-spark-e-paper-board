#!/usr/bin/python
# -*- coding:utf-8 -*-
import sys
import os
import time
import logging
from PIL import Image, ImageDraw, ImageFont

picdir = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), 'pic')
libdir = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), 'lib')
if os.path.exists(libdir):
    sys.path.append(libdir)

from waveshare_epd import epd7in5_V2

logging.basicConfig(level=logging.INFO)

def _text_size(draw, text, font):
    bbox = draw.textbbox((0, 0), text, font=font)
    return (bbox[2] - bbox[0], bbox[3] - bbox[1])

def _fit_font(draw, text, font_path, max_size, max_width, max_height):
    size = max_size
    while size > 10:
        font = ImageFont.truetype(font_path, size)
        width, height = _text_size(draw, text, font)
        if width <= max_width and height <= max_height:
            return font, width, height
        size -= 2
    font = ImageFont.truetype(font_path, 12)
    width, height = _text_size(draw, text, font)
    return font, width, height

def _draw_border(draw, width, height, thickness=3):
    for i in range(thickness):
        draw.rectangle((i, i, width - 1 - i, height - 1 - i), outline=0)

try:
    logging.info("epd7in5_V2 clock demo")
    epd = epd7in5_V2.EPD()

    logging.info("init and Clear")
    epd.init()
    epd.Clear()

    font_path = os.path.join(picdir, 'Font.ttc')

    image = Image.new('1', (epd.width, epd.height), 255)
    draw = ImageDraw.Draw(image)

    # Layout: bold time panel + banner text
    margin = 24
    gap = 26
    clock_sample = "88:88:88"
    text = u"恭喜发财"

    font_clock, clock_w, clock_h = _fit_font(
        draw,
        clock_sample,
        font_path,
        max_size=140,
        max_width=epd.width - (margin * 2 + 40),
        max_height=200,
    )
    font_text, text_w, text_h = _fit_font(
        draw,
        text,
        font_path,
        max_size=84,
        max_width=epd.width - (margin * 2 + 40),
        max_height=140,
    )

    time_pad_x = 32
    time_pad_y = 18
    time_box_w = clock_w + time_pad_x * 2
    time_box_h = clock_h + time_pad_y * 2

    banner_pad_x = 40
    banner_pad_y = 16
    banner_w = max(text_w + banner_pad_x * 2, int(epd.width * 0.7))
    banner_w = min(banner_w, epd.width - margin * 2)
    banner_h = text_h + banner_pad_y * 2

    total_h = time_box_h + gap + banner_h
    start_y = (epd.height - total_h) // 2

    time_box_x = (epd.width - time_box_w) // 2
    time_box_y = start_y
    banner_x = (epd.width - banner_w) // 2
    banner_y = start_y + time_box_h + gap

    # Frame and static elements
    _draw_border(draw, epd.width, epd.height, thickness=3)
    draw.rectangle((time_box_x, time_box_y, time_box_x + time_box_w, time_box_y + time_box_h), fill=0)
    draw.rectangle((banner_x, banner_y, banner_x + banner_w, banner_y + banner_h), fill=0)

    text_x = banner_x + (banner_w - text_w) // 2
    text_y = banner_y + (banner_h - text_h) // 2
    draw.text((text_x, text_y), text, font=font_text, fill=255)

    clock_x = time_box_x + (time_box_w - clock_w) // 2
    clock_y = time_box_y + (time_box_h - clock_h) // 2

    now = time.strftime('%H:%M:%S')
    draw.text((clock_x, clock_y), now, font=font_clock, fill=255)

    epd.display(epd.getbuffer(image))

    # Partial update loop for time
    logging.info("start partial updates")
    epd.init_part()
    time_box = (time_box_x, time_box_y, time_box_x + time_box_w, time_box_y + time_box_h)

    while True:
        now = time.strftime('%H:%M:%S')
        draw.rectangle(time_box, fill=0)
        draw.text((clock_x, clock_y), now, font=font_clock, fill=255)
        epd.display_Partial(epd.getbuffer(image), time_box_x, time_box_y, time_box_w, time_box_h)
        time.sleep(1)

except IOError as e:
    logging.info(e)

except KeyboardInterrupt:
    logging.info("ctrl + c:")
    epd7in5_V2.epdconfig.module_exit(cleanup=True)
