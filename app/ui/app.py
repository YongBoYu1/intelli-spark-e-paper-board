from __future__ import annotations

import time

from PIL import Image, ImageDraw

from app.core.state import AppState, Screen, MenuItemId, WidgetMode
from app.ui.home import render_home
from app.ui.home_kitchen import render_home_kitchen
from app.ui.calendar import render_calendar
from app.ui.weather_detail import render_weather_detail
from app.ui.menu import render_menu
from app.ui.placeholder import render_placeholder
from app.ui.layout import compute_layout


def _voice_zone_status_label(phase: str, msg: str = "") -> str:
    p = (phase or "idle").strip().lower()
    if p == "recording":
        return "LISTENING"
    if p == "processing":
        return "PROCESSING"
    if p == "confirm":
        return "CONFIRM"
    if p == "done":
        txt = str(msg or "").strip().lower()
        if txt.startswith("skipped:") or "\nresult: skipped:" in txt:
            return "SKIPPED"
        return "DONE"
    if p == "error":
        return "ERROR"
    return "READY"


def _voice_wrap_message(msg: str, max_chars: int = 44, max_lines: int = 3) -> list[str]:
    text = str(msg or "").strip()
    if not text:
        return []

    lines: list[str] = []
    for raw in text.splitlines():
        part = " ".join(raw.strip().split())
        if not part:
            continue
        words = part.split(" ")
        cur = ""
        for w in words:
            candidate = w if not cur else f"{cur} {w}"
            if len(candidate) <= max_chars:
                cur = candidate
                continue
            if cur:
                lines.append(cur)
            # Handle long unbroken tokens (e.g. Chinese without spaces).
            cur = w if len(w) <= max_chars else (w[: max_chars - 3] + "...")
            if len(lines) >= max_lines - 1:
                break
        if cur and len(lines) < max_lines:
            lines.append(cur)
        if len(lines) >= max_lines:
            break

    if len(lines) > max_lines:
        lines = lines[:max_lines]
    if lines and len(lines[-1]) > max_chars:
        lines[-1] = lines[-1][: max_chars - 3] + "..."
    if len(lines) == max_lines and " ".join(lines) != text:
        if len(lines[-1]) >= 3:
            lines[-1] = lines[-1][: max(0, max_chars - 3)] + "..."
    return lines


def _parse_voice_message_fields(msg: str) -> dict[str, str | list[str]]:
    text = str(msg or "").strip()
    out: dict[str, str | list[str]] = {"heard": "", "action": "", "result": "", "other": []}
    if not text:
        return out

    other: list[str] = []
    for raw in text.splitlines():
        line = " ".join(str(raw or "").strip().split())
        if not line:
            continue
        head, sep, tail = line.partition(":")
        key = head.strip().lower()
        value = tail.strip()
        if sep and key in ("heard", "action", "result"):
            out[key] = value
            continue
        other.append(line)
    out["other"] = other
    return out


def _voice_zone_lines(phase_label: str, msg: str, *, max_chars: int = 36) -> list[str]:
    fields = _parse_voice_message_fields(msg)
    heard = str(fields.get("heard") or "").strip()
    result = str(fields.get("result") or "").strip()
    other = [str(x).strip() for x in (fields.get("other") or []) if str(x).strip()]

    lines: list[str] = []
    max_lines = 3

    def _append(text: str) -> None:
        if not text or len(lines) >= max_lines:
            return
        remain = max_lines - len(lines)
        for wrapped in _voice_wrap_message(text, max_chars=max_chars, max_lines=remain):
            if len(lines) >= max_lines:
                break
            lines.append(wrapped)

    if phase_label == "LISTENING":
        _append(other[0] if other else (result or "Listening for command"))
        return lines or ["Listening for command"]

    if phase_label == "PROCESSING":
        _append(other[0] if other else (result or "Interpreting command"))
        return lines or ["Interpreting command"]

    if phase_label == "CONFIRM":
        if heard:
            _append(f"Heard: {heard}")
        # Keep confirm body compact; the explicit device action/countdown lives in the hint row.
        if result:
            result_l = result.lower()
            if "confirm" in result_l or "press click" in result_l or "press" in result_l:
                _append("Result: Awaiting physical confirm")
            else:
                _append(f"Result: {result}")
        elif other:
            _append(other[0])
        if not lines:
            return ["Confirm action on device"]
        return lines

    if heard:
        _append(f"Heard: {heard}")

    if result:
        _append(f"Result: {result}")
    elif other:
        _append(other[0])
        if len(other) > 1:
            _append(other[1])
    elif msg:
        _append(msg)

    if not lines:
        if phase_label == "CONFIRM":
            return ["Confirm action on device"]
        if phase_label == "ERROR":
            return ["Voice command failed"]
        return ["Voice update"]
    return lines


def _voice_zone_hint(state: AppState, phase_label: str, *, active: bool) -> str:
    return ""


_MIC_STYLE_ALIASES: dict[str, str] = {
    "hero_solid": "heroicons_solid",
    "hero_outline": "heroicons_outline",
    "capsule_solid": "bootstrap_fill",
    "block_solid": "tabler_filled",
    "outline": "heroicons_outline",
    "lucide_outline": "heroicons_outline",
    "retro": "tabler_outline",
}

_MIC_ICON_MASKS_16: dict[str, tuple[str, ...]] = {
    # Heroicons solid (source: assets/icons/heroicons/16-solid-microphone.svg)
    # Mask extracted from vector render and tuned for 1-bit readability.
    "heroicons_solid": (
        "................",
        "......####......",
        "......####......",
        "......####......",
        "......####......",
        "......####......",
        "...#..####..#...",
        "...##.####.##...",
        "...##.####.##...",
        "...###....###...",
        "....########....",
        ".....######.....",
        ".......##.......",
        ".....######.....",
        ".....######.....",
        "................",
    ),
    # Heroicons outline (derived from heroicons solid contour for e-paper).
    "heroicons_outline": (
        "................",
        "......####......",
        "......#..#......",
        "......#..#......",
        "......#..#......",
        "......#..#......",
        "...#..#..#..#...",
        "...##.#..#.##...",
        "...##.####.##...",
        "...###....###...",
        "....########....",
        ".....######.....",
        ".......##.......",
        ".....######.....",
        ".....######.....",
        "................",
    ),
    # Tabler outline (source: assets/icons/tabler/microphone-outline.svg)
    "tabler_outline": (
        "................",
        "......####......",
        "......####......",
        ".....##..##.....",
        ".....##..##.....",
        ".....##..##.....",
        "...#.##..##.#...",
        "...#.##..##.#...",
        "...##.####.##...",
        "...##..##..##...",
        "....###..###....",
        ".....######.....",
        ".......##.......",
        ".....######.....",
        ".....######.....",
        "................",
    ),
    # Tabler filled (source: assets/icons/tabler/microphone-filled.svg)
    "tabler_filled": (
        "................",
        "......####......",
        "......####......",
        ".....######.....",
        ".....######.....",
        ".....######.....",
        "...#.######.#...",
        "...#.######.#...",
        "...##.####.##...",
        "...##..##..##...",
        "....###..###....",
        ".....######.....",
        ".......##.......",
        ".....######.....",
        ".....######.....",
        "................",
    ),
    # Tabler half-fill (mid-state between outline and filled for processing/confirm).
    "tabler_half": (
        "................",
        "......####......",
        "......####......",
        ".....##..##.....",
        ".....######.....",
        ".....######.....",
        "...#.######.#...",
        "...#.##..##.#...",
        "...##.####.##...",
        "...##..##..##...",
        "....###..###....",
        ".....######.....",
        ".......##.......",
        ".....######.....",
        ".....######.....",
        "................",
    ),
    # Bootstrap outline (source: assets/icons/bootstrap/mic.svg)
    "bootstrap_outline": (
        "................",
        "......####......",
        "......#..#......",
        ".....##..##.....",
        ".....##..##.....",
        ".....##..##.....",
        ".....##..##.....",
        "....###..###....",
        "....###..###....",
        "....#.####.#....",
        "....##.##.##....",
        ".....######.....",
        ".......##.......",
        ".......##.......",
        ".....######.....",
        "................",
    ),
    # Bootstrap fill (source: assets/icons/bootstrap/mic-fill.svg)
    "bootstrap_fill": (
        "................",
        "......####......",
        "......####......",
        ".....######.....",
        ".....######.....",
        ".....######.....",
        ".....######.....",
        "....########....",
        "....########....",
        "....#.####.#....",
        "....##.##.##....",
        ".....######.....",
        ".......##.......",
        ".......##.......",
        ".....######.....",
        "................",
    ),
}


def _draw_mask_icon(draw: ImageDraw.ImageDraw, x: int, y: int, size: int, color, rows: tuple[str, ...]) -> None:
    s = max(14, int(size))
    mask = Image.new("1", (16, 16), 0)
    pix = mask.load()
    for yy, row in enumerate(rows[:16]):
        for xx, ch in enumerate(row[:16]):
            if ch == "#":
                pix[xx, yy] = 1
    if s != 16:
        mask = mask.resize((s, s), Image.NEAREST)
    draw.bitmap((int(x), int(y)), mask, fill=color)


def _normalize_mic_style(style: str) -> str:
    key = str(style or "").strip().lower()
    key = _MIC_STYLE_ALIASES.get(key, key)
    if key not in _MIC_ICON_MASKS_16:
        return "tabler_outline"
    return key


def _resolve_voice_mic_style(theme: dict, *, phase_label: str, active: bool) -> str:
    mode = str((theme or {}).get("voice_zone_mic_mode", "tabler_state") or "tabler_state").strip().lower()
    if mode in ("tabler_state", "auto_tabler", "stateful", "auto"):
        if not active:
            return "tabler_outline"
        if phase_label == "LISTENING":
            return "tabler_filled"
        if phase_label in ("PROCESSING", "CONFIRM"):
            return "tabler_half"
        return "tabler_outline"
    raw_style = str((theme or {}).get("voice_zone_mic_style", "tabler_outline") or "tabler_outline")
    return _normalize_mic_style(raw_style)


def _draw_mic_icon(draw: ImageDraw.ImageDraw, x: int, y: int, size: int, color, *, style: str = "tabler_outline") -> None:
    """
    Draw a 1-bit-friendly microphone icon silhouette.
    Styles map to masks derived from open-source SVG icon families.
    """
    key = _normalize_mic_style(style)
    rows = _MIC_ICON_MASKS_16.get(key) or _MIC_ICON_MASKS_16["tabler_outline"]
    _draw_mask_icon(draw, x, y, size, color, rows)


def _voice_action_prompt(tool_name: str) -> str:
    tool = str(tool_name or "").strip().lower()
    if tool == "shopping_add_item":
        return "Add to shopping list"
    if tool == "shopping_remove_item":
        return "Remove from shopping list"
    if tool == "shopping_clear_all":
        return "Clear shopping list"
    if tool == "inventory_log_event":
        return "Update inventory"
    if tool == "inventory_set_expiry":
        return "Set expiry"
    if tool == "inventory_clear_all":
        return "Clear inventory"
    if tool == "timer_set":
        return "Set timer"
    if tool == "memo_add":
        return "Add memo"
    if tool == "no_action":
        return "No action"
    return "Do this"


def _voice_tool_from_action_text(action_text: str) -> str:
    txt = str(action_text or "").strip().lower()
    if not txt:
        return ""
    head = txt.split("(", 1)[0].strip()
    if not head:
        return ""
    return head.split()[0].strip()


def _voice_short_result_text(text: str) -> str:
    txt = str(text or "").strip().replace("\n", " ")
    if not txt:
        return ""
    txt = txt.split(";", 1)[0].strip()
    low = txt.lower()
    if "non-actionable" in low or low.startswith("no action:") or low.startswith("skipped:"):
        return "No change"
    if low.startswith("added to shopping:"):
        item = txt.split(":", 1)[1].strip() if ":" in txt else ""
        return f"Added {item}".strip()
    if low.startswith("removed from shopping:"):
        item = txt.split(":", 1)[1].strip() if ":" in txt else ""
        return f"Removed {item}".strip()
    if low.startswith("removed from inventory:"):
        item = txt.split(":", 1)[1].strip() if ":" in txt else ""
        return f"Removed {item}".strip()
    if low.startswith("cleared shopping list"):
        return "Shopping cleared"
    if low.startswith("cleared inventory"):
        return "Inventory cleared"
    if low.startswith("shopping list already empty"):
        return "Already empty"
    if low.startswith("inventory already empty"):
        return "Already empty"
    return _voice_preview_text(txt, max_chars=20)


def _voice_preview_text(text: str, *, max_chars: int = 22) -> str:
    txt = " ".join(str(text or "").split())
    if not txt:
        return ""
    if len(txt) <= max_chars:
        return txt
    if max_chars <= 3:
        return txt[:max_chars]
    return txt[: max_chars - 3].rstrip() + "..."


def _voice_summary_text(state: AppState, phase_label: str, msg: str, *, active: bool) -> str:
    fields = _parse_voice_message_fields(msg)
    heard = str(fields.get("heard") or "").strip()
    action_text = str(fields.get("action") or "").strip()
    result = str(fields.get("result") or "").strip()
    other = [str(x).strip() for x in (fields.get("other") or []) if str(x).strip()]

    if not active or phase_label == "READY":
        return "Hold to talk"
    if phase_label == "LISTENING":
        return "Go ahead..."
    if phase_label == "PROCESSING":
        if heard:
            return f"Heard: {_voice_preview_text(heard, max_chars=14)}"
        return "On it..."

    tool = ""
    if phase_label == "CONFIRM":
        tool = str(state.ui.voice_confirm_tool or "").strip().lower()
    if not tool:
        tool = _voice_tool_from_action_text(action_text)

    heard_preview = _voice_preview_text(heard, max_chars=14)

    if phase_label == "CONFIRM":
        return f"{_voice_action_prompt(tool)}? Enter"

    txt = result or (other[0] if other else str(msg or "").strip())
    outcome = _voice_short_result_text(txt) if txt else ""

    if phase_label == "ERROR":
        return "Didn't catch that"
    if phase_label == "SKIPPED":
        return "No change"
    if phase_label == "DONE":
        if outcome:
            return outcome
        if heard_preview:
            return f"Heard: {heard_preview}"
        return "Done"

    if outcome:
        return outcome
    if heard_preview:
        return f"Heard: {heard_preview}"
    return "Hold to talk"


def _ellipsize_text(draw: ImageDraw.ImageDraw, text: str, *, font, max_width: float) -> str:
    txt = " ".join(str(text or "").split())
    if not txt:
        return ""
    if max_width <= 0:
        return ""
    if draw.textlength(txt, font=font) <= max_width:
        return txt
    ell = "..."
    ell_w = draw.textlength(ell, font=font)
    if ell_w >= max_width:
        return ell
    lo = 0
    hi = len(txt)
    best = ""
    while lo <= hi:
        mid = (lo + hi) // 2
        cand = txt[:mid].rstrip() + ell
        if draw.textlength(cand, font=font) <= max_width:
            best = cand
            lo = mid + 1
        else:
            hi = mid - 1
    return best or ell


def _center_text_y(draw: ImageDraw.ImageDraw, text: str, *, font, top: int, height: int) -> int:
    if height <= 0:
        return int(top)
    try:
        b = draw.textbbox((0, 0), str(text or ""), font=font)
        text_h = max(1, int(b[3] - b[1]))
        return int(top + (height - text_h) // 2 - int(b[1]))
    except Exception:
        return int(top + max(0, (height - int(getattr(font, "size", 12))) // 2))


def _draw_voice_overlay(image, state: AppState, fonts, theme: dict) -> None:
    now = time.time()
    pending_confirm = bool(state.ui.voice_confirm_tool) and float(state.ui.voice_confirm_due_at or 0.0) > now
    active = bool(state.ui.voice_active) or pending_confirm

    variant = str((theme or {}).get("home_variant") or "kitchen").strip().lower()
    show_idle_home_zone = bool(theme.get("voice_zone_show_idle_home", True))
    if not active:
        if not show_idle_home_zone:
            return
        if state.ui.screen != Screen.HOME or variant != "kitchen":
            return

    phase = str(state.ui.voice_phase or "idle").strip().lower()
    msg = str(state.ui.voice_message or "").strip()
    if pending_confirm and phase != "confirm":
        phase = "confirm"
        if not msg:
            tool_name = str(state.ui.voice_confirm_tool or "").strip().replace("_", " ")
            msg = f"Press click / enter to confirm {tool_name or 'action'}"

    draw = ImageDraw.Draw(image)
    w, h = image.size

    ink = theme.get("ink", 0)
    card = theme.get("card", 255)
    muted = theme.get("muted", ink)

    margin = int(theme.get("voice_zone_margin", 14) or 14)
    zone_w = int(theme.get("voice_zone_width", min(380, max(300, int(w * 0.46)))) or 340)
    zone_w = max(220, min(zone_w, max(220, w - margin * 2)))
    lane_h = int(theme.get("voice_zone_lane_h", 29) or 29)
    icon_size = int(theme.get("voice_zone_icon_size", 18) or 18)
    icon_nudge_y = int(theme.get("voice_zone_icon_nudge_y", -1) or -1)
    text_nudge_y = int(theme.get("voice_zone_text_nudge_y", 0) or 0)

    phase_label = _voice_zone_status_label(phase, msg)
    mic_style = _resolve_voice_mic_style(theme, phase_label=phase_label, active=active)
    zone_h = lane_h

    x0 = margin
    y1 = h - margin
    y0 = max(margin, y1 - zone_h)
    x1 = x0 + zone_w

    # Single-line rail: fixed height and width keep future partial-refresh region stable.
    draw.rectangle((x0, y0 - 1, x1, y1 + 1), fill=card, outline=None)

    icon_x = x0 + 2
    icon_y = y0 + max(0, (zone_h - icon_size) // 2) + icon_nudge_y
    _draw_mic_icon(draw, icon_x, icon_y, icon_size, ink, style=mic_style)

    state_font = fonts.get("inter_bold", 13)
    tx = icon_x + icon_size + 7
    state_text = _voice_summary_text(state, phase_label, msg, active=active)
    max_text_w = max(0.0, (x1 - 2) - tx)
    state_text = _ellipsize_text(draw, state_text, font=state_font, max_width=max_text_w)
    ty = _center_text_y(draw, state_text, font=state_font, top=y0, height=zone_h) + text_nudge_y
    draw.text((tx, ty), state_text, font=state_font, fill=ink)


def _to_render_data(state: AppState) -> dict:
    reminders = []
    for r in state.model.reminders:
        item = {"title": r.title}
        if r.right:
            # Heuristic: treat HH:MM as time, otherwise due.
            if ":" in r.right and len(r.right) <= 5:
                item["time"] = r.right
            else:
                item["due"] = r.right
        reminders.append(item)

    weather = []
    for w in state.model.weather:
        item = {"dow": w.dow, "icon": w.icon, "hi": w.hi, "lo": w.lo}
        if getattr(w, "humidity", None) is not None:
            item["humidity"] = w.humidity
        weather.append(item)

    return {
        "location": state.model.location,
        "battery": state.model.battery,
        "page": state.ui.page,
        # totals are derived from full dataset
        "reminder_total": len(state.model.reminders),
        "reminder_due": sum(1 for r in state.model.reminders if not r.completed),
        "reminders": reminders,
        "weather": weather,
        "voice_active": bool(state.ui.voice_active),
        "widget_mode": str(state.ui.widget_mode.value if isinstance(state.ui.widget_mode, WidgetMode) else state.ui.widget_mode),
        "timer_seconds": int(state.ui.timer_seconds or 0),
        "timer_running": bool(state.ui.timer_running),
        "menu_focused": str(state.ui.menu_focused.value if isinstance(state.ui.menu_focused, MenuItemId) else state.ui.menu_focused),
        "active_menu": str(state.ui.active_menu.value if state.ui.active_menu else ""),
    }


def render_app(image, state: AppState, fonts, theme: dict) -> None:
    if state.ui.screen == Screen.MENU:
        render_menu(image, state, fonts, theme)
        _draw_voice_overlay(image, state, fonts, theme)
        return
    if state.ui.screen == Screen.PLACEHOLDER:
        render_placeholder(image, state, fonts, theme)
        _draw_voice_overlay(image, state, fonts, theme)
        return
    if state.ui.screen == Screen.CALENDAR:
        render_calendar(image, state, fonts, theme)
        _draw_voice_overlay(image, state, fonts, theme)
        return
    if state.ui.screen == Screen.WEATHER:
        render_weather_detail(image, state, fonts, theme)
        _draw_voice_overlay(image, state, fonts, theme)
        return

    # HOME: choose renderer variant based on theme (default: kitchen).
    variant = str((theme or {}).get("home_variant") or "kitchen").strip().lower()
    if variant == "kitchen":
        render_home_kitchen(image, state, fonts, theme)
        _draw_voice_overlay(image, state, fonts, theme)
        return

    data = _to_render_data(state)

    overlay = {}
    if not state.ui.idle and state.ui.screen == Screen.HOME:
        # HOME focus queue: [CLOCK, WEATHER, TASK_0..]
        if state.ui.focused_index == 0:
            overlay["focus"] = {"kind": "clock"}
        elif state.ui.focused_index == 1:
            overlay["focus"] = {"kind": "weather"}
        else:
            overlay["focus"] = {"kind": "task", "index": state.ui.focused_index - 2}
        overlay["focus_width"] = int(theme.get("focus_width", 4) or 4)

    render_home(image, data, fonts, theme=theme, overlay=overlay)

    # Draw focus for clock/weather cards here (task focus is handled in home.py).
    focus = overlay.get("focus") or {}
    if focus.get("kind") in ("clock", "weather"):
        layout = compute_layout(image.width, image.height)
        left_card = (
            layout.left_x,
            layout.top_y,
            layout.left_x + layout.left_w,
            layout.top_y + layout.left_card_h,
        )
        weather_card = (
            layout.left_x,
            layout.top_y + layout.left_card_h + layout.gap,
            layout.left_x + layout.left_w,
            layout.top_y + layout.left_card_h + layout.gap + layout.weather_h,
        )
        box = left_card if focus.get("kind") == "clock" else weather_card
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle(
            box,
            radius=int(theme.get("card_radius", 12) or 12),
            outline=theme.get("ink", 0),
            width=int(overlay.get("focus_width", 4) or 4),
            fill=None,
        )
    _draw_voice_overlay(image, state, fonts, theme)
