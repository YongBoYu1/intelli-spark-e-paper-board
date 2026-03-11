from __future__ import annotations

import hashlib
import time

from PIL import ImageDraw

from app.core.state import AppState
from app.shared.draw import draw_text_spaced, text_size, text_width_spaced, truncate_text
from app.shared.mic_icon import draw_mic_icon, normalize_mic_style
from app.shared.panel_font_templates import apply_panel_font_template


def _fill_and_text(fill_color, ink, bg):
    return (fill_color, bg if fill_color == ink else ink)


def _dark_muted(muted, ink):
    try:
        if isinstance(muted, tuple) and len(muted) >= 3:
            base = int(sum(int(v) for v in muted[:3]) / 3)
            v = max(70, min(120, base))
            return (v, v, v)
        base = int(muted)
        return max(70, min(120, base))
    except Exception:
        return ink


def _draw_focus(draw, box: tuple[int, int, int, int], ink, *, width: int = 3, radius: int = 12) -> None:
    draw.rounded_rectangle(box, radius=radius, outline=ink, width=width)


def _clamp_i(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, int(v)))


def _theme_fonts(theme: dict, fonts):
    body_key = str(theme.get("panel_font_body_key") or "inter_medium")
    body_focus_key = str(theme.get("panel_font_body_focus_key") or "inter_bold")
    title_key = str(theme.get("panel_font_title_key") or "inter_black")
    meta_key = str(theme.get("panel_font_meta_key") or "jet_bold")
    # Follow panel font template defaults and keep only a small safety clamp.
    body_base = _clamp_i(int(theme.get("panel_font_body_size", 18) or 18), 12, 18)
    meta_base = _clamp_i(int(theme.get("panel_font_meta_size", 13) or 13), 10, 13)
    title_size = _clamp_i(int(round(body_base * 1.6)), 21, 30)
    button_size = _clamp_i(int(round(body_base * 0.95)), 12, 18)
    return {
        "title": fonts.get(title_key, title_size),
        "body": fonts.get(body_key, body_base),
        "body_focus": fonts.get(body_focus_key, body_base),
        "button": fonts.get(body_focus_key, button_size),
        "meta": fonts.get(meta_key, meta_base),
        "meta_spacing": int(theme.get("panel_font_meta_spacing", 0) or 0),
        "meta_compact": bool(theme.get("panel_font_meta_compact", True)),
    }


def _draw_title_reinforced(draw, text: str, x: float, y: float, font, ink) -> None:
    draw.text((x, y), text, fill=ink, font=font)
    draw.text((x + 1, y), text, fill=ink, font=font)


def _voice_locale_label(locale: str) -> str:
    key = str(locale or "").strip()
    if key == "es-ES":
        return "Spanish"
    if key == "fr-FR":
        return "French"
    return "English"


def _device_lang_label(locale: str) -> str:
    key = str(locale or "").strip()
    if key == "es-ES":
        return "Spanish"
    if key == "fr-FR":
        return "French"
    return "English"


def _meta_text(raw: str, *, compact: bool) -> str:
    text = str(raw or "").strip()
    if compact:
        return text.upper()
    return text


def _wrap_text_lines(draw, text: str, font, max_width: int, *, max_lines: int = 3) -> list[str]:
    raw = " ".join(str(text or "").split())
    if not raw:
        return [""]
    if max_width <= 8:
        return [raw]

    words = raw.split(" ")
    lines: list[str] = []
    cur = ""
    for word in words:
        candidate = word if not cur else f"{cur} {word}"
        if draw.textlength(candidate, font=font) <= max_width:
            cur = candidate
            continue
        if cur:
            lines.append(cur)
        cur = word
        if len(lines) >= max_lines - 1:
            break
    if cur and len(lines) < max_lines:
        lines.append(cur)
    if not lines:
        lines = [raw]
    if len(lines) == max_lines:
        remainder = " ".join(words)
        rendered = " ".join(lines)
        if rendered != remainder:
            lines[-1] = truncate_text(draw, lines[-1], font, max_width)
    return lines[:max_lines]


def _onboarding_progress(step: str) -> tuple[int, int, str]:
    key = str(step or "").strip().lower()
    if key == "start":
        return 1, 4, "~2 min left"
    if key == "pair_qr":
        return 2, 4, "~90 sec left"
    if key == "prefs":
        return 3, 4, "~45 sec left"
    if key == "voice_guide":
        return 4, 4, "~20 sec left"
    return 4, 4, "complete"


def _draw_onboarding_progress(draw, w: int, step: str, f: dict, *, bg, ink, muted, border) -> None:
    cur, total, eta = _onboarding_progress(step)
    step_text = _meta_text(f"Step {cur}/{total}", compact=f["meta_compact"])
    eta_text = _meta_text(eta, compact=f["meta_compact"])
    step_w = text_width_spaced(draw, step_text, f["meta"], spacing=f["meta_spacing"])
    eta_w = text_width_spaced(draw, eta_text, f["meta"], spacing=f["meta_spacing"])
    x_right = w - 42
    draw_text_spaced(draw, step_text, x_right - step_w, 40, f["meta"], spacing=f["meta_spacing"], fill=ink)
    draw_text_spaced(draw, eta_text, x_right - eta_w, 60, f["meta"], spacing=f["meta_spacing"], fill=muted)

    bar_w = 148
    bar_h = 7
    gap = 6
    x1 = x_right
    x0 = x1 - bar_w
    y0 = 80
    seg_w = int((bar_w - ((total - 1) * gap)) / max(1, total))
    for i in range(total):
        sx0 = x0 + i * (seg_w + gap)
        sx1 = sx0 + seg_w
        fill = ink if i < cur else bg
        draw.rounded_rectangle((sx0, y0, sx1, y0 + bar_h), radius=3, outline=border, width=1, fill=fill)


def _qr_bits(token: str, dim: int = 25) -> list[list[int]]:
    if dim < 21:
        dim = 21
    raw = hashlib.sha256(str(token or "pair").encode("utf-8")).digest()
    bits: list[list[int]] = []
    for r in range(dim):
        row: list[int] = []
        for c in range(dim):
            idx = (r * dim + c) % len(raw)
            byte = raw[idx]
            row.append(1 if ((byte >> ((r + c) % 8)) & 1) else 0)
        bits.append(row)
    return bits


def _draw_qr_placeholder(draw, box: tuple[int, int, int, int], token: str, ink, bg) -> None:
    x0, y0, x1, y1 = box
    draw.rectangle(box, fill=bg, outline=ink, width=2)
    w = max(1, x1 - x0)
    h = max(1, y1 - y0)
    dim = 25
    cell = max(2, min(w, h) // (dim + 4))
    ox = x0 + (w - (cell * dim)) // 2
    oy = y0 + (h - (cell * dim)) // 2
    bits = _qr_bits(token, dim=dim)
    for r in range(dim):
        for c in range(dim):
            if bits[r][c]:
                xx = ox + c * cell
                yy = oy + r * cell
                draw.rectangle((xx, yy, xx + cell - 1, yy + cell - 1), fill=ink)


def render_landing(image, state: AppState, fonts, theme: dict) -> None:
    theme = apply_panel_font_template(theme)
    f = _theme_fonts(theme, fonts)
    draw = ImageDraw.Draw(image)
    if bool(theme.get("panel_mode", False)) or not bool(theme.get("panel_text_antialias", False)):
        try:
            draw.fontmode = "1"
        except Exception:
            pass
    w, h = image.size

    bg = theme.get("bg", 255)
    card = theme.get("card", 255)
    ink = theme.get("ink", 0)
    muted = _dark_muted(theme.get("muted", ink), ink)
    border = theme.get("border", ink)

    draw.rectangle((0, 0, w, h), fill=bg)
    margin = _clamp_i(int(min(w, h) * 0.05), 14, 24)
    draw.rectangle((margin, margin, w - margin, h - margin), fill=card)

    content_x0 = margin + 16
    content_x1 = w - margin - 16
    content_w = max(120, content_x1 - content_x0)

    y = margin + 18
    title = truncate_text(draw, "INTELLI SPARK BOARD", f["title"], max(120, content_w))
    tw = draw.textlength(title, font=f["title"])
    draw.text((content_x0 + (content_w - tw) / 2, y), title, fill=ink, font=f["title"])
    y += max(28, text_size(draw, title, f["title"])[1] + 8)

    subtitle = truncate_text(draw, "Welcome. Learn controls before first setup.", f["body"], max(120, content_w))
    sw = draw.textlength(subtitle, font=f["body"])
    draw.text((content_x0 + (content_w - sw) / 2, y), subtitle, fill=muted, font=f["body"])
    y += max(30, text_size(draw, subtitle, f["body"])[1] + 14)

    tips = [
        ("Rotate", "Move focus"),
        ("Press", "Confirm"),
        ("Long Press", "Back to home"),
        ("Hold Voice Key", "Talk to assistant"),
    ]
    tip_cols = 2 if content_w >= 560 else 1
    tip_gap_x = 12
    tip_gap_y = 10
    tip_w = int((content_w - ((tip_cols - 1) * tip_gap_x)) / tip_cols)
    tip_h = 60
    for i, (top, bottom) in enumerate(tips):
        col = i % tip_cols
        row = i // tip_cols
        x0 = content_x0 + col * (tip_w + tip_gap_x)
        x1 = x0 + tip_w
        y0 = y + row * (tip_h + tip_gap_y)
        y1 = y0 + tip_h
        fill_color = ink if i < 2 else bg
        draw.rounded_rectangle((x0, y0, x1, y1), radius=10, outline=border, width=2, fill=fill_color)
        top = truncate_text(draw, top, f["button"], max(60, tip_w - 20))
        top_w = draw.textlength(top, font=f["button"])
        _, top_text = _fill_and_text(fill_color, ink, bg)
        draw.text((x0 + (tip_w - top_w) / 2, y0 + 8), top, fill=top_text, font=f["button"])
        bottom = _meta_text(bottom, compact=f["meta_compact"])
        bottom = truncate_text(draw, bottom, f["meta"], max(60, tip_w - 20))
        bot_w = text_width_spaced(draw, bottom, f["meta"], spacing=f["meta_spacing"])
        draw_text_spaced(
            draw,
            bottom,
            x0 + (tip_w - bot_w) / 2,
            y0 + 34,
            f["meta"],
            spacing=f["meta_spacing"],
            fill=bg if fill_color == ink else muted,
        )
    tip_rows = (len(tips) + tip_cols - 1) // tip_cols
    y += tip_rows * tip_h + max(0, tip_rows - 1) * tip_gap_y + 12

    voice_gate_hint = _meta_text("Voice key unlocks after first setup.", compact=f["meta_compact"])
    voice_gate_hint = truncate_text(draw, voice_gate_hint, f["meta"], max(120, content_w))
    draw_text_spaced(draw, voice_gate_hint, content_x0, y, f["meta"], spacing=f["meta_spacing"], fill=muted)
    y += 20

    draw.text((content_x0, y), "Language", fill=ink, font=f["button"])
    y += 26

    choices = [("en-US", "English"), ("es-ES", "Spanish"), ("fr-FR", "French")]
    locale = str(state.ui.device_language or state.ui.voice_locale or "en-US").strip()
    chip_cols = 3 if content_w >= 520 else 1
    chip_gap_x = 10
    chip_gap_y = 8
    chip_w = int((content_w - ((chip_cols - 1) * chip_gap_x)) / chip_cols)
    chip_h = 40
    for i, (lang_key, raw_label) in enumerate(choices):
        col = i % chip_cols
        row = i // chip_cols
        x0 = content_x0 + col * (chip_w + chip_gap_x)
        x1 = x0 + chip_w
        y0 = y + row * (chip_h + chip_gap_y)
        y1 = y0 + chip_h
        active = (locale == lang_key)
        draw.rounded_rectangle((x0, y0, x1, y1), radius=10, outline=border, width=2, fill=ink if active else bg)
        if active:
            _draw_focus(draw, (x0 - 2, y0 - 2, x1 + 2, y1 + 2), ink, width=3, radius=11)
        label = _meta_text(raw_label, compact=f["meta_compact"])
        label = truncate_text(draw, label, f["meta"], max(50, chip_w - 16))
        lw = text_width_spaced(draw, label, f["meta"], spacing=f["meta_spacing"])
        draw_text_spaced(
            draw,
            label,
            x0 + (chip_w - lw) / 2,
            y0 + 12,
            f["meta"],
            spacing=f["meta_spacing"],
            fill=bg if active else (muted if chip_cols > 1 else ink),
        )
    chip_rows = (len(choices) + chip_cols - 1) // chip_cols
    y += chip_rows * chip_h + max(0, chip_rows - 1) * chip_gap_y + 8

    bottom_safe_y = h - margin - 18
    button_h = 52
    button_w = min(420, content_w)
    button_x0 = content_x0 + (content_w - button_w) // 2
    button_y1 = bottom_safe_y
    button_y0 = button_y1 - button_h
    if button_y0 < y + 54:
        button_y0 = y + 54
        button_y1 = button_y0 + button_h
    button = (button_x0, button_y0, button_x0 + button_w, button_y1)

    status = (
        str(state.ui.landing_status or "").strip()
        or "Rotate to choose language, click once to confirm, click again to start setup."
    )
    status = _meta_text(status, compact=f["meta_compact"])
    status = truncate_text(draw, status, f["meta"], max(120, content_w))
    status_y = max(y + 18, button[1] - 66)
    draw_text_spaced(draw, status, content_x0, status_y, f["meta"], spacing=f["meta_spacing"], fill=ink)

    draw.rounded_rectangle(button, radius=12, outline=border, width=2, fill=ink)
    _draw_focus(draw, (button[0] - 2, button[1] - 2, button[2] + 2, button[3] + 2), ink)
    if bool(state.ui.setup_completed):
        button_label = "Enter Home"
    elif not bool(state.ui.landing_rotate_seen):
        button_label = "Rotate to choose language"
    elif not bool(state.ui.landing_confirm_seen):
        button_label = "Click to confirm language"
    else:
        button_label = "Click to start first setup"
    button_label = truncate_text(draw, button_label, f["button"], max(80, button_w - 24))
    bw_text = draw.textlength(button_label, font=f["button"])
    draw.text((button[0] + (button_w - bw_text) / 2, button[1] + 14), button_label, fill=bg, font=f["button"])


def render_onboarding(image, state: AppState, fonts, theme: dict) -> None:
    theme = apply_panel_font_template(theme)
    f = _theme_fonts(theme, fonts)
    draw = ImageDraw.Draw(image)
    if bool(theme.get("panel_mode", False)) or not bool(theme.get("panel_text_antialias", False)):
        try:
            draw.fontmode = "1"
        except Exception:
            pass
    w, h = image.size

    bg = theme.get("bg", 255)
    card = theme.get("card", 255)
    ink = theme.get("ink", 0)
    muted = _dark_muted(theme.get("muted", ink), ink)
    border = theme.get("border", ink)

    draw.rectangle((0, 0, w, h), fill=bg)
    outer = (18, 18, w - 18, h - 18)
    draw.rectangle(outer, fill=card)

    step = str(state.ui.onboarding_step or "start").strip().lower()
    if step != "voice_guide":
        _draw_onboarding_progress(draw, w, step, f, bg=bg, ink=ink, muted=muted, border=border)

    if step == "start":
        draw.text((42, 42), "First Setup", fill=ink, font=f["title"])
        draw.text((42, 90), "Configure network and basic preferences.", fill=muted, font=f["body"])
        draw.text((42, 136), "Phone pairing is recommended for Wi-Fi setup.", fill=ink, font=f["body"])
        options = ["Start Phone Pairing", "Skip for now"]
        focused = max(0, min(1, int(state.ui.onboarding_focus_index or 0)))
        option_w = min(430, max(240, w - 84))
        option_x0 = (w - option_w) // 2
        option_x1 = option_x0 + option_w
        y0 = 220
        for i, label in enumerate(options):
            box = (option_x0, y0 + i * 82, option_x1, y0 + i * 82 + 58)
            fill_color = ink if i == focused else bg
            text_color = bg if i == focused else ink
            draw.rounded_rectangle(box, radius=12, outline=border, width=2, fill=fill_color)
            if i == focused:
                _draw_focus(draw, (box[0] - 2, box[1] - 2, box[2] + 2, box[3] + 2), ink)
            tw = draw.textlength(label, font=f["button"])
            draw.text((box[0] + (box[2] - box[0] - tw) / 2, box[1] + 18), label, fill=text_color, font=f["button"])
        hint = _meta_text("Rotate to choose  -  Press to continue", compact=f["meta_compact"])
        draw_text_spaced(draw, hint, 42, h - 56, f["meta"], spacing=f["meta_spacing"], fill=muted)
        return

    if step == "pair_qr":
        draw.text((42, 42), "Phone Pairing", fill=ink, font=f["title"])
        draw.text((42, 90), "Scan QR to configure Wi-Fi", fill=muted, font=f["body"])
        compact = w < 700
        token = str(state.ui.onboarding_pair_token or "----")
        ttl_s = max(0, int(float(state.ui.onboarding_pair_expires_at or 0.0) - time.time()))
        mm = ttl_s // 60
        ss = ttl_s % 60
        token_text = _meta_text(f"Pair Token: {token}", compact=f["meta_compact"])
        expires_text = _meta_text(f"Expires in: {mm:02d}:{ss:02d}", compact=f["meta_compact"])
        status = str(state.ui.onboarding_status or "Waiting for phone callback...")
        status = _meta_text(status, compact=f["meta_compact"])
        y_after_meta = 0

        if compact:
            qr_size = min(max(180, w - 140), 260, max(180, h - 290))
            qr_x0 = (w - qr_size) // 2
            qr_y0 = 126
            qr_box = (qr_x0, qr_y0, qr_x0 + qr_size, qr_y0 + qr_size)
            _draw_qr_placeholder(draw, qr_box, state.ui.onboarding_pair_token, ink, bg)

            y = qr_box[3] + 14
            for raw in ("1) Open phone camera", "2) Scan code and submit Wi-Fi", "3) Return here and confirm"):
                line = truncate_text(draw, raw, f["meta"], max(120, w - 84))
                lw = text_width_spaced(draw, line, f["meta"], spacing=f["meta_spacing"])
                draw_text_spaced(draw, line, (w - lw) / 2, y, f["meta"], spacing=f["meta_spacing"], fill=ink)
                y += 22
            token_line = truncate_text(draw, token_text, f["meta"], max(120, w - 84))
            exp_line = truncate_text(draw, expires_text, f["meta"], max(120, w - 84))
            status_line = truncate_text(draw, status, f["meta"], max(120, w - 84))
            draw_text_spaced(draw, token_line, 42, y + 4, f["meta"], spacing=f["meta_spacing"], fill=ink)
            draw_text_spaced(draw, exp_line, 42, y + 26, f["meta"], spacing=f["meta_spacing"], fill=muted)
            draw_text_spaced(draw, status_line, 42, y + 48, f["meta"], spacing=f["meta_spacing"], fill=muted)
            y_after_meta = y + 70
        else:
            qr_box = (52, 132, 336, 416)
            _draw_qr_placeholder(draw, qr_box, state.ui.onboarding_pair_token, ink, bg)
            info_x = 372
            draw.text((info_x, 146), "1) Open phone camera", fill=ink, font=f["body"])
            draw.text((info_x, 176), "2) Scan code and submit Wi-Fi", fill=ink, font=f["body"])
            draw.text((info_x, 206), "3) Return here and confirm", fill=ink, font=f["body"])
            status_line = truncate_text(draw, status, f["meta"], max(120, w - info_x - 24))
            draw_text_spaced(draw, token_text, info_x, 252, f["meta"], spacing=f["meta_spacing"], fill=ink)
            draw_text_spaced(draw, expires_text, info_x, 278, f["meta"], spacing=f["meta_spacing"], fill=muted)
            draw_text_spaced(draw, status_line, info_x, 304, f["meta"], spacing=f["meta_spacing"], fill=muted)

        buttons = ["Refresh QR", "I am done", "Skip"]
        focused = max(0, min(2, int(state.ui.onboarding_qr_focus_index or 0)))
        if compact:
            gap = 8
            bh = 42
            bw = max(180, w - 84)
            total_h = len(buttons) * bh + (len(buttons) - 1) * gap
            by = max(int(y_after_meta), h - 30 - total_h)
            for i, label in enumerate(buttons):
                x0 = (w - bw) // 2
                x1 = x0 + bw
                y0 = by + i * (bh + gap)
                y1 = y0 + bh
                fill_color = ink if i == focused else bg
                text_color = bg if i == focused else ink
                draw.rounded_rectangle((x0, y0, x1, y1), radius=10, outline=border, width=2, fill=fill_color)
                if i == focused:
                    _draw_focus(draw, (x0 - 2, y0 - 2, x1 + 2, y1 + 2), ink)
                label = _meta_text(label, compact=f["meta_compact"])
                tw = text_width_spaced(draw, label, f["meta"], spacing=f["meta_spacing"])
                draw_text_spaced(draw, label, x0 + (bw - tw) / 2, y0 + 13, f["meta"], spacing=f["meta_spacing"], fill=text_color)
        else:
            bx = 372
            by = max(338, h - 112)
            right_w = max(300, w - bx - 22)
            gap = 12
            bw = max(88, int((right_w - (gap * 2)) / 3))
            bh = 52
            for i, label in enumerate(buttons):
                x0 = bx + i * (bw + gap)
                x1 = x0 + bw
                y0 = by
                y1 = y0 + bh
                fill_color = ink if i == focused else bg
                text_color = bg if i == focused else ink
                draw.rounded_rectangle((x0, y0, x1, y1), radius=10, outline=border, width=2, fill=fill_color)
                if i == focused:
                    _draw_focus(draw, (x0 - 2, y0 - 2, x1 + 2, y1 + 2), ink)
                label = _meta_text(label, compact=f["meta_compact"])
                tw = text_width_spaced(draw, label, f["meta"], spacing=f["meta_spacing"])
                draw_text_spaced(draw, label, x0 + (bw - tw) / 2, y0 + 18, f["meta"], spacing=f["meta_spacing"], fill=text_color)
        return

    if step == "prefs":
        _draw_title_reinforced(draw, "Quick Preferences", 42, 42, f["title"], ink)
        draw.text((42, 90), "You can change these later in Settings.", fill=muted, font=f["body"])
        ssid = str(state.ui.onboarding_wifi_ssid or "").strip()
        wifi_text = f"Wi-Fi: {ssid}" if ssid else ("Wi-Fi: enabled" if bool(state.ui.wifi_enabled) else "Wi-Fi: skipped")
        wifi_text = _meta_text(wifi_text, compact=f["meta_compact"])
        draw_text_spaced(draw, wifi_text, 42, 124, f["meta"], spacing=f["meta_spacing"], fill=ink)

        pref_rows = [
            ("Language", _device_lang_label(state.ui.device_language)),
            ("Timezone", str(state.ui.device_timezone or "UTC")),
            ("Auto Sync", "ON" if bool(state.ui.auto_sync_enabled) else "OFF"),
        ]
        focused = max(0, min(3, int(state.ui.onboarding_prefs_focus_index or 0)))

        rows_top = 152
        next_h = 54
        next_y1 = h - 22
        next_y0 = next_y1 - next_h
        rows_bottom = next_y0 - 14
        row_gap = 10
        slot_count = len(pref_rows)
        usable_h = max(140, rows_bottom - rows_top)
        row_h = int((usable_h - (row_gap * (slot_count - 1))) / max(1, slot_count))
        row_h = _clamp_i(row_h, 40, 56)
        content_h = slot_count * row_h + (slot_count - 1) * row_gap
        if content_h > usable_h:
            overflow = content_h - usable_h
            rows_top = max(138, rows_top - overflow)

        y = rows_top
        for idx, (k, v) in enumerate(pref_rows):
            box = (42, y, w - 42, y + row_h)
            is_focused = idx == focused
            fill_color = bg
            label_color = ink
            value_color = ink if is_focused else muted
            draw.rounded_rectangle(box, radius=12, outline=border, width=2, fill=fill_color)
            if is_focused:
                _draw_focus(draw, (box[0] - 2, box[1] - 2, box[2] + 2, box[3] + 2), ink)
                rail_w = 10
                draw.rounded_rectangle(
                    (box[0] + 10, box[1] + 8, box[0] + 10 + rail_w, box[3] - 8),
                    radius=4,
                    outline=ink,
                    width=1,
                    fill=ink,
                )
            key_text = truncate_text(draw, k, f["button"], max(80, int((box[2] - box[0]) * 0.55)))
            value_max_w = max(70, int((box[2] - box[0]) * 0.42))
            v_text = truncate_text(draw, str(v), f["body"], value_max_w)
            vw = draw.textlength(v_text, font=f["body"])
            txt_y = y + max(10, int((row_h - 24) / 2))
            draw.text((64, txt_y), key_text, fill=label_color, font=f["button"])
            draw.text((box[2] - 22 - vw, txt_y + 1), v_text, fill=value_color, font=f["body"])
            y += row_h + row_gap

        # Dedicated next-step lane: text arrow + explicit Voice Guide button.
        lane_y0 = next_y0
        lane_y1 = next_y1
        lane_mid_y = int((lane_y0 + lane_y1) / 2)
        guide_w = min(248, max(190, int((w - 84) * 0.38)))
        guide_box = (w - 42 - guide_w, lane_y0 + 4, w - 42, lane_y1 - 4)
        guide_focused = focused == 3
        draw.rounded_rectangle(guide_box, radius=12, outline=border, width=2, fill=bg)
        if guide_focused:
            _draw_focus(draw, (guide_box[0] - 2, guide_box[1] - 2, guide_box[2] + 2, guide_box[3] + 2), ink)

        lead = truncate_text(draw, "Next Step", f["button"], max(80, guide_box[0] - 82))
        lead_y = lane_mid_y - 10
        draw.text((46, lead_y), lead, fill=ink, font=f["button"])
        arrow = _meta_text("->", compact=f["meta_compact"])
        draw_text_spaced(draw, arrow, 46 + draw.textlength(lead, font=f["button"]) + 10, lead_y + 2, f["meta"], spacing=f["meta_spacing"], fill=muted)

        guide_label = truncate_text(draw, "Voice Guide >", f["body_focus"], max(90, guide_w - 24))
        gw = draw.textlength(guide_label, font=f["body_focus"])
        draw.text((guide_box[0] + (guide_w - gw) / 2, guide_box[1] + 13), guide_label, fill=ink, font=f["body_focus"])
        return

    if step == "voice_guide":
        inner_x0 = 34
        inner_x1 = w - 34
        inner_w = max(120, inner_x1 - inner_x0)

        y = 40
        title = truncate_text(draw, "Voice Setup", f["title"], max(100, inner_w - 160))
        _draw_title_reinforced(draw, title, inner_x0, y, f["title"], ink)
        y += 40

        mic_w = min(210, max(150, int(inner_w * 0.28)))
        sample_x0 = inner_x0 + mic_w + 18
        sample_x1 = inner_x1 - 8
        sample_label = _meta_text("Speak", compact=f["meta_compact"])
        sample = _meta_text(str(state.ui.onboarding_voice_sample_text or "Add milk to inventory"), compact=False).upper()
        sample_lines = _wrap_text_lines(draw, sample, f["title"], max(100, sample_x1 - sample_x0), max_lines=2)
        sample_line_h = max(24, text_size(draw, "Ag", f["title"])[1] + 4)
        top_h = 122 + max(0, len(sample_lines) - 1) * sample_line_h
        top_box = (inner_x0, y, inner_x1, y + top_h)
        split_x = top_box[0] + mic_w
        icon_box = (top_box[0] + 34, top_box[1] + 8, split_x - 34, top_box[1] + 60)
        icon_size = max(30, min(icon_box[2] - icon_box[0], icon_box[3] - icon_box[1]))
        icon_x = icon_box[0] + max(0, ((icon_box[2] - icon_box[0]) - icon_size) // 2)
        icon_y = icon_box[1] + max(0, ((icon_box[3] - icon_box[1]) - icon_size) // 2)
        mic_style = normalize_mic_style(str(theme.get("voice_zone_mic_style", "tabler_outline") or "tabler_outline"))
        draw_mic_icon(draw, icon_x, icon_y, icon_size, ink, style=mic_style)
        hold = truncate_text(draw, "Hold voice key", f["button"], max(60, mic_w - 24))
        hw = draw.textlength(hold, font=f["button"])
        draw.text((top_box[0] + (mic_w - hw) / 2, top_box[1] + 74), hold, fill=ink, font=f["button"])

        draw_text_spaced(draw, sample_label, sample_x0, top_box[1] + 12, f["meta"], spacing=f["meta_spacing"], fill=muted)
        sample_y = top_box[1] + 40
        for line in sample_lines:
            draw.text((sample_x0, sample_y), line, fill=ink, font=f["title"])
            sample_y += sample_line_h

        divider_y = top_box[3] - 2
        draw.line((inner_x0, divider_y, inner_x1, divider_y), fill=border, width=2)
        y = top_box[3] + 18

        heard = str(state.ui.onboarding_voice_demo_heard or "").strip() or "No result yet."
        result_h = 102
        result_box = (inner_x0, y, inner_x1, y + result_h)
        draw.rounded_rectangle(result_box, radius=12, outline=border, width=2, fill=card)
        result_title = _meta_text("Result", compact=f["meta_compact"])
        draw_text_spaced(draw, result_title, result_box[0] + 18, result_box[1] + 12, f["meta"], spacing=f["meta_spacing"], fill=muted)
        heard_line = truncate_text(draw, heard, f["body_focus"], max(100, inner_w - 36))
        draw.text((result_box[0] + 18, result_box[1] + 46), heard_line, fill=ink, font=f["body_focus"])
        y = result_box[3] + 16

        status = truncate_text(draw, str(state.ui.onboarding_status or "Hold voice key to test current sample."), f["meta"], max(100, inner_w))

        action_label = "Continue" if int(state.ui.onboarding_voice_demo_case_index or 0) >= 3 else "Skip"
        action_h = 40
        action_w = min(360, inner_w)
        actions_y0 = h - 26 - action_h
        status_y = min(y, actions_y0 - 26)
        draw_text_spaced(draw, _meta_text(status, compact=f["meta_compact"]), inner_x0, status_y, f["meta"], spacing=f["meta_spacing"], fill=muted)

        x0 = inner_x0 + (inner_w - action_w) // 2
        x1 = x0 + action_w
        y0 = actions_y0
        y1 = y0 + action_h
        draw.rounded_rectangle((x0, y0, x1, y1), radius=10, outline=border, width=2, fill=bg)
        _draw_focus(draw, (x0 - 2, y0 - 2, x1 + 2, y1 + 2), ink)
        txt = _meta_text(action_label, compact=f["meta_compact"])
        tw = text_width_spaced(draw, txt, f["meta"], spacing=f["meta_spacing"])
        draw_text_spaced(draw, txt, x0 + (action_w - tw) / 2, y0 + 13, f["meta"], spacing=f["meta_spacing"], fill=ink)
        return

    draw.text((42, 60), "Setup Complete", fill=ink, font=f["title"])
    draw.text((42, 108), "Your board is ready.", fill=muted, font=f["body"])
    ssid = str(state.ui.onboarding_wifi_ssid or "").strip()
    lines = [
        f"Language: {_device_lang_label(state.ui.device_language)}",
        f"Timezone: {state.ui.device_timezone}",
        f"Auto Sync: {'ON' if bool(state.ui.auto_sync_enabled) else 'OFF'}",
        f"Wi-Fi: {ssid if ssid else 'Not configured'}",
    ]
    y = 160
    for line in lines:
        line = _meta_text(line, compact=f["meta_compact"])
        draw_text_spaced(draw, line, 62, y, f["meta"], spacing=f["meta_spacing"], fill=ink)
        _, lh = text_size(draw, line, f["meta"])
        y += max(30, lh + 8)

    enter_w = min(320, max(180, w - 84))
    enter = ((w - enter_w) // 2, h - 102, (w - enter_w) // 2 + enter_w, h - 44)
    draw.rounded_rectangle(enter, radius=12, outline=border, width=2, fill=ink)
    _draw_focus(draw, (enter[0] - 2, enter[1] - 2, enter[2] + 2, enter[3] + 2), ink)
    text = "Enter Home"
    tw = draw.textlength(text, font=f["button"])
    draw.text((enter[0] + (enter[2] - enter[0] - tw) / 2, enter[1] + 18), text, fill=bg, font=f["button"])
