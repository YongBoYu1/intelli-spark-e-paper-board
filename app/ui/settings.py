from __future__ import annotations

from datetime import datetime
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw

from app.shared.draw import draw_text_spaced, text_size, text_width_spaced, truncate_text
from app.shared.panel_font_templates import apply_panel_font_template
from app.core.settings_schema import SettingsItem, SETTINGS_GROUPS, SETTINGS_LABELS, SETTINGS_ORDER
from app.core.state import AppState


def _bool_text(value: bool) -> str:
    return "ON" if bool(value) else "OFF"


def _font_size_text(raw: str) -> str:
    value = str(raw or "medium").strip().lower()
    if value == "small":
        return "SMALL"
    if value == "large":
        return "LARGE"
    return "MEDIUM"


def _partial_refresh_text(raw: str) -> str:
    value = str(raw or "balanced").strip().lower()
    if value == "slow":
        return "SLOW"
    if value == "fast":
        return "FAST"
    return "BALANCED"


def _full_refresh_text(raw: int) -> str:
    try:
        v = max(1, int(raw))
    except Exception:
        v = 15
    return f"EVERY {v} PARTIALS"


def _rotation_text(raw: int) -> str:
    try:
        deg = int(raw or 0)
    except Exception:
        deg = 0
    deg = (((deg % 360) + 45) // 90 * 90) % 360
    return str(deg)


def _connectivity_text(state: AppState) -> str:
    return f"WIFI {_bool_text(state.ui.wifi_enabled)} / BT {_bool_text(state.ui.bluetooth_enabled)}"


def _last_sync_text(state: AppState) -> str:
    ts = float(state.ui.last_sync_at or 0.0)
    if ts <= 0:
        return "NEVER"
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return "INVALID TIME"


def _value_for_item(state: AppState, item: SettingsItem) -> str:
    if item == SettingsItem.FONT_SIZE:
        return _font_size_text(state.ui.font_size)
    if item == SettingsItem.PARTIAL_REFRESH:
        return _partial_refresh_text(state.ui.partial_refresh_mode)
    if item == SettingsItem.FULL_REFRESH:
        return _full_refresh_text(state.ui.full_refresh_every)
    if item == SettingsItem.CONNECTIVITY:
        return _connectivity_text(state)
    if item == SettingsItem.AUTO_SYNC:
        return _bool_text(state.ui.auto_sync_enabled)
    if item == SettingsItem.SYNC_NOW:
        return "PRESS ENTER"
    if item == SettingsItem.ROTATION:
        return _rotation_text(state.ui.rotation_deg)
    if item == SettingsItem.RESET_AND_WIPE:
        return "PLACEHOLDER"
    return ""


@lru_cache(maxsize=1)
def _load_home_icon_png() -> Image.Image | None:
    root = Path(__file__).resolve().parents[2]
    icon_path = root / "assets" / "icons" / "home_tabler.png"
    if not icon_path.exists():
        return None
    return Image.open(icon_path).convert("RGBA")


def _draw_home_icon(image, x: int, y: int, size: int, color) -> None:
    icon = _load_home_icon_png()
    if icon is None:
        return
    s = max(24, int(size))
    src = icon.resize((s, s), Image.Resampling.LANCZOS)
    # Use a higher alpha cutoff so the rendered outline looks thinner on e-ink.
    alpha = src.getchannel("A").point(lambda v: 255 if v >= 170 else 0, mode="1")
    image.paste(color, (x, y, x + s, y + s), alpha)


def render_settings(image, state: AppState, fonts, theme: dict) -> None:
    theme = apply_panel_font_template(theme)
    draw = ImageDraw.Draw(image)
    w, h = image.size

    if bool(theme.get("panel_mode", False)) or not bool(theme.get("panel_text_antialias", False)):
        try:
            draw.fontmode = "1"
        except Exception:
            pass

    bg = theme.get("card", 255)
    ink = theme.get("ink", 0)
    muted = theme.get("muted", ink)
    border = theme.get("border", ink)

    body_key = str(theme.get("panel_font_body_key") or "inter_medium")
    body_focus_key = str(theme.get("panel_font_body_focus_key") or "inter_bold")
    meta_key = str(theme.get("panel_font_meta_key") or "jet_bold")
    body_base = max(12, int(theme.get("panel_font_body_size", 18) or 18))
    meta_base = max(11, int(theme.get("panel_font_meta_size", 13) or 13))
    meta_spacing = int(theme.get("panel_font_meta_spacing", 0) or 0)
    meta_compact = bool(theme.get("panel_font_meta_compact", True))

    draw.rectangle((0, 0, w, h), fill=bg)

    title_font = fonts.get(body_focus_key, max(24, int(body_base * 1.65)))
    meta_font = fonts.get(meta_key, meta_base)
    label_size = max(16, int(body_base + 3))
    value_size = max(13, label_size - 3)
    row_font = fonts.get(body_key, label_size)
    row_focus_font = fonts.get(body_focus_key, label_size)
    value_font = fonts.get(meta_key, value_size)

    focused_raw = int(state.ui.settings_focused_index or 0)
    home_focused = focused_raw < 0
    focused = focused_raw if focused_raw >= 0 else -1

    title_y = 16
    title_bbox = draw.textbbox((0, 0), "SETTINGS", font=title_font)
    title_mid_y = title_y + int(round((title_bbox[1] + title_bbox[3]) / 2.0))
    title_h = max(1, int(title_bbox[3] - title_bbox[1]))
    icon_size = max(38, int(round(title_h * 0.84)))
    icon_x = 24
    icon_y = max(4, title_mid_y - (icon_size // 2) - 2)
    _draw_home_icon(image, icon_x, icon_y, icon_size, ink)
    if home_focused:
        pad = 2
        draw.rectangle(
            (icon_x - pad, icon_y - pad, icon_x + icon_size + pad, icon_y + icon_size + pad),
            outline=ink,
            width=2,
            fill=None,
        )
        draw.text((icon_x - 15, icon_y + max(2, icon_size // 4)), ">", font=value_font, fill=ink)

    title_x = icon_x + icon_size + 14
    draw.text((title_x, title_y), "SETTINGS", font=title_font, fill=ink)
    hint_text = "ROTATE TO SELECT  -  CLICK TO CHANGE"
    hint_w = text_width_spaced(draw, hint_text, meta_font, spacing=meta_spacing)
    hint_x = max(24, (w - 24) - hint_w)
    draw_text_spaced(
        draw,
        hint_text,
        hint_x,
        52,
        meta_font,
        spacing=meta_spacing,
        fill=muted,
    )
    divider_y = 68
    draw.line((24, divider_y, w - 24, divider_y), fill=border, width=int(theme.get("divider_width", 2) or 2))

    left = 24
    right = w - 24
    top = 90
    row_h = 34
    row_gap = 1
    group_h = 20
    group_gap = 7
    group_font = fonts.get(meta_key, max(10, meta_base - 1))
    group_ink = muted

    notice = str(state.ui.settings_notice or "").strip()
    footer_pad_x = 24
    footer_vpad = 6
    _, footer_text_h = text_size(draw, "A", meta_font)
    footer_h = max(28, footer_text_h + (footer_vpad * 2))
    footer_top = h - footer_h
    content_bottom = footer_top - 6

    _, label_h = text_size(draw, "A", row_focus_font)
    _, value_h = text_size(draw, "A", value_font)
    min_row_h = max(24, label_h + 8, value_h + 8)
    _, group_text_h = text_size(draw, "A", group_font)
    min_group_h = max(14, group_text_h + 4)
    group_h = max(group_h, min_group_h)

    def _content_height() -> int:
        total = 0
        for gi, (_gname, items) in enumerate(SETTINGS_GROUPS):
            total += group_h
            total += (len(items) * row_h)
            if len(items) > 1:
                total += (len(items) - 1) * row_gap
            if gi < len(SETTINGS_GROUPS) - 1:
                total += group_gap
        return total

    available_h = max(0, content_bottom - top)
    for _ in range(120):
        if _content_height() <= available_h:
            break
        if row_h > min_row_h:
            row_h -= 1
            continue
        if group_gap > 2:
            group_gap -= 1
            continue
        if group_h > min_group_h:
            group_h -= 1
            continue
        if row_gap > 0:
            row_gap -= 1
            continue
        break

    y = top
    index_map = {item: i for i, item in enumerate(SETTINGS_ORDER)}

    for group_name, group_items in SETTINGS_GROUPS:
        draw_text_spaced(draw, group_name, left + 2, y, group_font, spacing=meta_spacing, fill=group_ink)
        y += group_h

        for item in group_items:
            y0 = y
            if y0 + row_h > content_bottom:
                break
            row_index = index_map.get(item, -1)
            is_focus = (row_index == focused)
            active_row_font = row_focus_font if is_focus else row_font
            text_fill = ink if is_focus else ink
            value_fill = ink if is_focus else muted
            marker_fill = ink if is_focus else muted

            value = _value_for_item(state, item)
            if meta_compact:
                value = value.upper()

            max_value_w = max(120, int((right - left) * 0.50))
            value = truncate_text(draw, value, value_font, max_value_w)
            value_w = text_width_spaced(draw, value, value_font, spacing=meta_spacing)
            value_x = right - 12 - value_w

            label = SETTINGS_LABELS[item]
            marker = ">" if is_focus else " "
            marker_w = text_width_spaced(draw, marker, value_font, spacing=meta_spacing)
            marker_x = left + 2
            label_x = marker_x + marker_w + 8
            max_label_w = max(100, value_x - label_x - 12)
            label = truncate_text(draw, label, active_row_font, max_label_w)
            _, row_label_h = text_size(draw, "A", active_row_font)
            _, row_value_h = text_size(draw, "A", value_font)
            label_y = y0 + max(0, (row_h - row_label_h) // 2)
            value_y = y0 + max(0, (row_h - row_value_h) // 2)

            draw_text_spaced(draw, marker, marker_x, value_y, value_font, spacing=meta_spacing, fill=marker_fill)
            draw.text((label_x, label_y), label, font=active_row_font, fill=text_fill)
            draw_text_spaced(draw, value, value_x, value_y, value_font, spacing=meta_spacing, fill=value_fill)

            if is_focus:
                underline_y = y0 + row_h - 3
                draw.line((label_x, underline_y, right - 12, underline_y), fill=border, width=1)
            y += row_h + row_gap

        y += group_gap

    draw.line((footer_pad_x, footer_top - 1, w - footer_pad_x, footer_top - 1), fill=border, width=1)

    status_right = f"LAST SYNC {_last_sync_text(state)}"
    status_right = status_right.upper() if meta_compact else status_right
    right_w = text_width_spaced(draw, status_right, meta_font, spacing=meta_spacing)
    right_x = w - footer_pad_x - right_w

    status_left = notice
    if meta_compact:
        status_left = status_left.upper()
    left_max_w = max(40, right_x - footer_pad_x - 12)
    status_left = truncate_text(draw, status_left, meta_font, left_max_w)

    footer_y = footer_top + max(0, (footer_h - footer_text_h) // 2)
    if status_left:
        draw_text_spaced(draw, status_left, footer_pad_x, footer_y, meta_font, spacing=meta_spacing, fill=ink)
    draw_text_spaced(draw, status_right, right_x, footer_y, meta_font, spacing=meta_spacing, fill=muted)
