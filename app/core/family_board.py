from __future__ import annotations

from datetime import datetime, time as datetime_time, timedelta, timezone
import time
from zoneinfo import ZoneInfo

from app.core.state import AppState, MemoItem


MEMO_EXPIRY_BUCKETS = ("none", "1h", "3h", "6h", "12h", "24h", "end_of_day")
_EXPIRY_SECONDS_BY_BUCKET = {
    "1h": 3600,
    "3h": 3 * 3600,
    "6h": 6 * 3600,
    "12h": 12 * 3600,
    "24h": 24 * 3600,
}


def normalize_memo_text(value: object, *, max_length: int = 240) -> str:
    return str(value or "").strip()[: max(0, int(max_length))]


def normalize_memo_author(value: object, *, default: str = "Voice", max_length: int = 24) -> str:
    author = " ".join(str(value or "").split())[: max(0, int(max_length))]
    return author or str(default or "Voice")


def normalize_memo_expiration_bucket(value: object) -> str:
    bucket = str(value or "").strip().lower()
    if bucket in MEMO_EXPIRY_BUCKETS:
        return bucket
    return "none"


def coerce_memo_expires_in_seconds(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        secs = int(value)
    except (TypeError, ValueError):
        txt = str(value or "").strip()
        if not txt or not txt.isdigit():
            return None
        try:
            secs = int(txt)
        except (TypeError, ValueError):
            return None
    if secs <= 0:
        return None
    return secs


def parse_memo_expires_at_iso(value: object, *, timezone_name: str = "UTC") -> float | None:
    txt = str(value or "").strip()
    if not txt:
        return None
    normalized = txt.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_resolve_timezone(timezone_name))
    try:
        return float(dt.timestamp())
    except Exception:
        return None


def resolve_memo_expires_at(
    expiration_bucket: object,
    *,
    now: float | None = None,
    timezone_name: str = "UTC",
    expires_in_seconds: object = None,
    expires_at_iso: object = None,
) -> float | None:
    bucket = normalize_memo_expiration_bucket(expiration_bucket)

    now_ts = float(now if now is not None else time.time())
    expires_at = parse_memo_expires_at_iso(expires_at_iso, timezone_name=timezone_name)
    if expires_at is not None:
        return expires_at if expires_at > now_ts else None

    expires_in = coerce_memo_expires_in_seconds(expires_in_seconds)
    if expires_in is not None:
        return now_ts + float(expires_in)

    if bucket == "none":
        return None
    if bucket in _EXPIRY_SECONDS_BY_BUCKET:
        return now_ts + float(_EXPIRY_SECONDS_BY_BUCKET[bucket])

    tz = _resolve_timezone(timezone_name)
    local_now = datetime.fromtimestamp(now_ts, tz)
    local_next_midnight = datetime.combine(local_now.date() + timedelta(days=1), datetime_time.min, tzinfo=tz)
    return float(local_next_midnight.timestamp())


def is_memo_expired(memo: MemoItem, *, now: float | None = None) -> bool:
    expires_at = getattr(memo, "expires_at", None)
    if expires_at is None:
        return False
    try:
        expire_ts = float(expires_at)
    except (TypeError, ValueError):
        return False
    if expire_ts <= 0:
        return False
    now_ts = float(now if now is not None else time.time())
    return now_ts >= expire_ts


def active_memos(memos: list[MemoItem], *, now: float | None = None) -> list[MemoItem]:
    now_ts = float(now if now is not None else time.time())
    return [memo for memo in list(memos or []) if not is_memo_expired(memo, now=now_ts)]


def clamp_memo_state(state: AppState, *, now: float | None = None, touch_rotation: bool = False) -> None:
    total = len(list(state.model.memos or []))
    if total <= 0:
        state.ui.memo_index = 0
        state.ui.memo_expanded = False
        if touch_rotation:
            state.ui.memo_last_rotated_at = float(now if now is not None else time.time())
        return
    cur = int(state.ui.memo_index or 0)
    state.ui.memo_index = max(0, min(cur, total - 1))
    if touch_rotation:
        state.ui.memo_last_rotated_at = float(now if now is not None else time.time())


def prune_expired_memos(state: AppState, *, now: float | None = None) -> int:
    now_ts = float(now if now is not None else time.time())
    memos = list(state.model.memos or [])
    kept = active_memos(memos, now=now_ts)
    removed = len(memos) - len(kept)
    if removed <= 0:
        clamp_memo_state(state, now=now_ts)
        return 0
    state.model.memos = kept
    clamp_memo_state(state, now=now_ts, touch_rotation=True)
    return removed


def _resolve_timezone(timezone_name: str):
    key = str(timezone_name or "").strip() or "UTC"
    try:
        return ZoneInfo(key)
    except Exception:
        pass
    if len(key) == 6 and key[0] in ("+", "-") and key[1:3].isdigit() and key[4:6].isdigit() and key[3] == ":":
        sign = 1 if key[0] == "+" else -1
        hours = int(key[1:3])
        minutes = int(key[4:6])
        return timezone(sign * timedelta(hours=hours, minutes=minutes))
    return timezone.utc
