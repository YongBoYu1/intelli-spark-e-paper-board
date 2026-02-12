from dataclasses import dataclass


@dataclass
class Layout:
    width: int
    height: int
    margin: int
    gap: int
    left_w: int
    right_w: int
    left_x: int
    right_x: int
    top_y: int
    left_card_h: int
    weather_h: int
    right_card_h: int


def compute_layout(width, height):
    if width == 800 and height == 480:
        margin = 6
        gap = 6
        left_w = 300
    else:
        margin = 12
        gap = 12
        left_w = int(width * 0.34)
    right_w = width - margin * 2 - gap - left_w
    left_x = margin
    right_x = left_x + left_w + gap
    top_y = margin

    available_h = height - margin * 2
    if width == 800 and height == 480:
        weather_h = 130
        left_card_h = 332
    else:
        weather_h = int(available_h * 0.22)
        left_card_h = available_h - weather_h - gap
    right_card_h = available_h

    return Layout(
        width=width,
        height=height,
        margin=margin,
        gap=gap,
        left_w=left_w,
        right_w=right_w,
        left_x=left_x,
        right_x=right_x,
        top_y=top_y,
        left_card_h=left_card_h,
        weather_h=weather_h,
        right_card_h=right_card_h,
    )
