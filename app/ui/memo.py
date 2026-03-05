from __future__ import annotations

import time

from PIL import ImageDraw

from app.core.state import AppState
from app.shared.draw import draw_text_spaced, text_size, text_width_spaced, truncate_text
from app.shared.panel_font_templates import apply_panel_font_template


def _format_relative_time(ts: float | None, now: float | None = None) -> str:
    if ts is None:
        return "UNKNOWN TIME"
    now_ts = float(now if now is not None else time.time())
    delta = max(0.0, now_ts - float(ts))
    if delta < 60:
        return "JUST NOW"
    if delta < 3600:
        return f"{int(delta // 60)}M AGO"
    if delta < 86400:
        return f"{int(delta // 3600)}H AGO"
    if delta < 7 * 86400:
        return f"{int(delta // 86400)}D AGO"
    try:
        return time.strftime("%b %d", time.localtime(float(ts))).upper()
    except Exception:
        return "UNKNOWN TIME"


def _break_long_token(draw: ImageDraw.ImageDraw, token: str, font, max_w: int) -> tuple[str, str]:
    if not token:
        return "", ""
    if draw.textlength(token, font=font) <= max_w:
        return token, ""
    left = ""
    for idx in range(1, len(token) + 1):
        piece = token[:idx]
        if draw.textlength(piece, font=font) > max_w:
            cut = max(1, idx - 1)
            return token[:cut], token[cut:]
        left = piece
    return left, ""


def _wrap_text(draw: ImageDraw.ImageDraw, text: str, font, max_w: int, max_lines: int) -> tuple[list[str], bool]:
    if max_lines <= 0:
        return [], bool(text.strip())

    tokens = str(text or "").strip().split()
    if not tokens:
        return [], False

    lines: list[str] = []
    cur = ""
    truncated = False

    for tok in tokens:
        if len(lines) >= max_lines:
            truncated = True
            break
        candidate = tok if not cur else f"{cur} {tok}"
        if draw.textlength(candidate, font=font) <= max_w:
            cur = candidate
            continue

        if cur:
            lines.append(cur)
            cur = ""
            if len(lines) >= max_lines:
                truncated = True
                break

        remaining = tok
        while remaining:
            piece, rest = _break_long_token(draw, remaining, font, max_w)
            if not piece:
                truncated = True
                break
            if len(lines) < max_lines - 1:
                lines.append(piece)
                remaining = rest
                continue
            cur = piece
            truncated = bool(rest)
            remaining = ""
        if truncated and len(lines) >= max_lines:
            break

    if cur and len(lines) < max_lines:
        lines.append(cur)
    elif cur and len(lines) >= max_lines:
        truncated = True

    if len(lines) > max_lines:
        lines = lines[:max_lines]
        truncated = True

    return lines, truncated


def render_memo(image, state: AppState, fonts, theme: dict) -> None:
    theme = apply_panel_font_template(theme)
    draw = ImageDraw.Draw(image)
    if bool(theme.get("panel_mode", False)) or not bool(theme.get("panel_text_antialias", False)):
        try:
            draw.fontmode = "1"
        except Exception:
            pass

    w, h = image.size
    bg = theme.get("card", 255)
    ink = theme.get("ink", 0)
    muted = theme.get("muted", ink)
    border = theme.get("border", ink)
    draw.rectangle((0, 0, w, h), fill=bg)

    body_key = str(theme.get("panel_font_body_key") or "inter_medium")
    body_focus_key = str(theme.get("panel_font_body_focus_key") or "inter_bold")
    meta_key = str(theme.get("panel_font_meta_key") or "jet_bold")
    body_base = max(12, int(theme.get("panel_font_body_size", 18) or 18))
    meta_base = max(11, int(theme.get("panel_font_meta_size", 13) or 13))
    meta_spacing = int(theme.get("panel_font_meta_spacing", 0) or 0)
    meta_compact = bool(theme.get("panel_font_meta_compact", True))

    title_font = fonts.get(body_focus_key, max(24, int(body_base * 1.55)))
    author_font = fonts.get(body_focus_key, max(18, int(body_base + 4)))
    body_font = fonts.get(body_key, max(16, int(body_base + 1)))
    meta_font = fonts.get(meta_key, meta_base)

    outer_x0 = 24
    outer_x1 = w - 24

    # Header
    title = "MEMO"
    title_y = 14
    draw.text((outer_x0, title_y), title, font=title_font, fill=ink)

    memos = list(state.model.memos or [])
    total = len(memos)
    idx = 0 if total <= 0 else (int(state.ui.memo_index or 0) % total)
    unread = sum(1 for m in memos if bool(getattr(m, "is_new", False)))

    hint_text = "Rotate to select  -  Click to enter  -  Long press to home"
    if meta_compact:
        hint_text = hint_text.upper()
    hint_w = text_width_spaced(draw, hint_text, meta_font, spacing=meta_spacing)
    hint_x = max(24, (w - 24) - hint_w)
    draw_text_spaced(draw, hint_text, hint_x, 52, meta_font, spacing=meta_spacing, fill=muted)

    header_rule_y = 68
    draw.line((outer_x0, header_rule_y, outer_x1, header_rule_y), fill=border, width=2)

    # Content area (no outer card box; keep layout clean and flat).
    inner_x0 = outer_x0 + 4
    inner_x1 = outer_x1 - 4
    inner_y0 = 86
    inner_y1 = h - 56

    if total <= 0:
        draw.text((inner_x0, inner_y0 + 8), "NO MEMOS YET", font=author_font, fill=ink)
        draw_text_spaced(
            draw,
            'TRY VOICE: "ADD MEMO DINNER AT 7"',
            inner_x0,
            inner_y0 + 44,
            meta_font,
            spacing=meta_spacing,
            fill=muted,
        )
    else:
        summary_text = f"TOTAL {total}   NEW {unread}   FOCUS {idx + 1}/{total}"
        draw_text_spaced(draw, summary_text, inner_x0, inner_y0, meta_font, spacing=meta_spacing, fill=muted)

        list_gap = 6
        row_h = 66
        list_top = inner_y0 + 22
        list_h = max(1, inner_y1 - list_top)
        slots = max(1, (list_h + list_gap) // (row_h + list_gap))
        selected = idx
        start = max(0, min(selected - (slots // 2), total - slots))
        visible = memos[start : start + slots]
        line_h = max(16, int(text_size(draw, "Ag", body_font)[1] * 1.2))

        y = list_top
        for i, memo in enumerate(visible):
            memo_idx = start + i
            is_sel = memo_idx == selected
            ry0 = y
            ry1 = min(inner_y1, y + row_h)
            if is_sel:
                draw.rectangle((inner_x0, ry0 + 1, inner_x1, ry1 - 1), fill=ink)
            row_text = bg if is_sel else ink
            row_muted = bg if is_sel else muted
            content_x0 = inner_x0 + 10
            content_x1 = inner_x1 - 10
            author = str(getattr(memo, "author", "") or "UNKNOWN").strip().upper()
            posted = _format_relative_time(getattr(memo, "timestamp", None))

            posted_w = text_width_spaced(draw, posted, meta_font, spacing=meta_spacing)
            posted_x = max(content_x0, content_x1 - posted_w)
            author_max_w = max(48, posted_x - content_x0 - 8)
            author_text = truncate_text(draw, author, author_font, author_max_w)
            draw.text((content_x0, ry0 + 6), author_text, font=author_font, fill=row_text)
            draw_text_spaced(draw, posted, posted_x, ry0 + 10, meta_font, spacing=meta_spacing, fill=row_muted)

            body = str(getattr(memo, "text", "") or "").strip() or "No content."
            preview_lines = 2 if (is_sel and bool(state.ui.memo_expanded)) else 1
            lines, truncated = _wrap_text(draw, body, body_font, max(40, content_x1 - content_x0), preview_lines)
            py = ry0 + 34
            for ln in lines:
                draw.text((content_x0, py), ln, font=body_font, fill=row_text)
                py += line_h
            if truncated and lines:
                ew = draw.textlength("...", font=body_font)
                draw.text((content_x1 - ew, py - int(line_h * 0.65)), "...", font=body_font, fill=row_muted)

            if bool(getattr(memo, "is_new", False)):
                badge = "NEW"
                badge_w = text_width_spaced(draw, badge, meta_font, spacing=meta_spacing)
                bx = max(content_x0, content_x1 - badge_w)
                draw_text_spaced(draw, badge, bx, ry1 - 20, meta_font, spacing=meta_spacing, fill=row_text)

            if not is_sel:
                draw.line((inner_x0 + 8, ry1, inner_x1, ry1), fill=border, width=1)

            y += row_h + list_gap

        if total > slots:
            tail_text = f"SHOWING {start + 1}-{start + len(visible)} OF {total}"
            draw_text_spaced(draw, tail_text, inner_x0, inner_y1 - 16, meta_font, spacing=meta_spacing, fill=muted)

    # Footer
    footer_y = h - 40
    footer_text_raw = "VOICE CMD: DELETE | ADD | MODIFY"
    footer_text = truncate_text(draw, footer_text_raw, meta_font, max(80, outer_x1 - outer_x0))
    draw_text_spaced(draw, footer_text, outer_x0, footer_y, meta_font, spacing=meta_spacing, fill=muted)
