from __future__ import annotations

from datetime import date, datetime, timedelta
import re
from typing import Iterable, Any


_WEEKDAY_INDEX: dict[str, int] = {
    "mon": 0,
    "monday": 0,
    "tue": 1,
    "tues": 1,
    "tuesday": 1,
    "wed": 2,
    "wednesday": 2,
    "thu": 3,
    "thur": 3,
    "thurs": 3,
    "thursday": 3,
    "fri": 4,
    "friday": 4,
    "sat": 5,
    "saturday": 5,
    "sun": 6,
    "sunday": 6,
}

_MONTH_WORDS = (
    "JAN",
    "FEB",
    "MAR",
    "APR",
    "MAY",
    "JUN",
    "JUL",
    "AUG",
    "SEP",
    "OCT",
    "NOV",
    "DEC",
)


def _parse_iso_date(text: str) -> date | None:
    s = str(text or "").strip()
    if not s:
        return None

    m = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", s)
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except Exception:
        return None


def _parse_month_day(text: str, *, year: int) -> date | None:
    s = str(text or "").strip()
    if not s:
        return None

    tokens = re.split(r"[\s,/-]+", s)
    tokens = [t for t in tokens if t]
    if len(tokens) < 2:
        return None

    month_idx = -1
    day_value: int | None = None
    for i, tok in enumerate(tokens):
        up = tok.upper()
        for mi, short in enumerate(_MONTH_WORDS, start=1):
            if up.startswith(short):
                month_idx = mi
                # Prefer the nearest numeric token after month token.
                for nxt in tokens[i + 1 : i + 3]:
                    if nxt.isdigit():
                        day_value = int(nxt)
                        break
                break
        if month_idx > 0:
            break

    if month_idx <= 0 or day_value is None:
        return None

    try:
        return date(int(year), int(month_idx), int(day_value))
    except Exception:
        return None


def _parse_weekday(text: str, *, base_date: date) -> date | None:
    s = str(text or "").strip().lower()
    if not s:
        return None
    parts = re.split(r"[^a-z]+", s)
    parts = [p for p in parts if p]
    for part in parts:
        if part not in _WEEKDAY_INDEX:
            continue
        target = _WEEKDAY_INDEX[part]
        delta = (target - int(base_date.weekday())) % 7
        return base_date + timedelta(days=delta)
    return None


def resolve_event_date(event: Any, *, base_date: date | None = None) -> date | None:
    base = base_date if isinstance(base_date, date) else datetime.now().date()
    candidates = [
        getattr(event, "date_iso", ""),
        getattr(event, "date", ""),
        getattr(event, "when", ""),
        getattr(event, "right", ""),
        getattr(event, "due", ""),
        getattr(event, "title", ""),
    ]

    for raw in candidates:
        parsed = _parse_iso_date(str(raw or ""))
        if parsed is not None:
            return parsed

    for raw in candidates:
        parsed = _parse_month_day(str(raw or ""), year=base.year)
        if parsed is not None:
            return parsed

    for raw in candidates:
        parsed = _parse_weekday(str(raw or ""), base_date=base)
        if parsed is not None:
            return parsed

    return None


def events_for_date(events: Iterable[Any], *, target_date: date, base_date: date | None = None) -> list[Any]:
    base = base_date if isinstance(base_date, date) else datetime.now().date()
    out: list[Any] = []
    unresolved: list[Any] = []
    for ev in events or []:
        ev_day = resolve_event_date(ev, base_date=base)
        if ev_day is None:
            unresolved.append(ev)
            continue
        if ev_day == target_date:
            out.append(ev)

    # Keep unresolved legacy events visible on "today".
    if target_date == base:
        out.extend(unresolved)
    return out
