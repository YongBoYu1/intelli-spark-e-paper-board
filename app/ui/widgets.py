from app.shared.draw import rounded_rect, draw_checkbox, truncate_text, text_size


def draw_card(draw, box, radius=16, outline=0, width=2, fill=255):
    rounded_rect(draw, box, radius=radius, outline=outline, width=width, fill=fill)


def draw_section_title(draw, text, x, y, font):
    draw.text((x, y), text, font=font, fill=0)


def draw_reminder_item(
    draw,
    box,
    title,
    right_text,
    font_title,
    font_right,
    ink=0,
    fill=255,
    border_width=2,
    divider_width=2,
    checkbox_border_width=2,
    radius=12,
):
    x0, y0, x1, y1 = box
    rounded_rect(draw, (x0, y0, x1, y1), radius=radius, outline=ink, width=border_width, fill=fill)

    checkbox_size = 22
    cb_x = x0 + 14
    cb_y = y0 + (y1 - y0 - checkbox_size) // 2
    draw_checkbox(
        draw,
        cb_x,
        cb_y,
        checkbox_size,
        checked=False,
        outline=ink,
        fill=fill,
        check_fill=ink,
        width=checkbox_border_width,
    )

    divider_x = x1 - 70

    title_x = cb_x + checkbox_size + 12
    max_title_w = divider_x - title_x - 8
    title = truncate_text(draw, title, font_title, max_title_w)
    title_w, title_h = text_size(draw, title, font_title)
    title_y = y0 + (y1 - y0 - title_h) // 2
    draw.text((title_x, title_y), title, font=font_title, fill=ink)

    if right_text:
        draw.line((divider_x, y0 + 6, divider_x, y1 - 6), fill=ink, width=divider_width)
        rt_w, rt_h = text_size(draw, right_text, font_right)
        rt_x = divider_x + (x1 - divider_x - rt_w) // 2
        rt_y = y0 + (y1 - y0 - rt_h) // 2
        draw.text((rt_x, rt_y), right_text, font=font_right, fill=ink)
