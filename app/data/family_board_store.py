from __future__ import annotations

import json
import os
import time

from app.core.family_board import (
    active_memos,
    normalize_memo_author,
    normalize_memo_expiration_bucket,
    normalize_memo_text,
    resolve_memo_expires_at,
)
from app.core.state import MemoItem


def family_board_store_path(repo_root: str) -> str:
    return os.path.join(str(repo_root), "data", "family_board.json")


def serialize_memo_items(memos: list[MemoItem]) -> list[dict]:
    out: list[dict] = []
    for memo in list(memos or []):
        out.append(
            {
                "mid": str(getattr(memo, "mid", "") or ""),
                "text": str(getattr(memo, "text", "") or ""),
                "author": str(getattr(memo, "author", "") or ""),
                "timestamp": float(getattr(memo, "timestamp", 0.0) or 0.0),
                "is_new": bool(getattr(memo, "is_new", False)),
                "expiration_bucket": normalize_memo_expiration_bucket(getattr(memo, "expiration_bucket", "none")),
                "expires_at": _coerce_float_opt(getattr(memo, "expires_at", None)),
            }
        )
    return out


def family_board_store_payload(memos: list[MemoItem]) -> dict:
    return {
        "version": 1,
        "memos": serialize_memo_items(memos),
    }


def load_family_board(
    repo_root: str,
    *,
    fallback_memos: list[MemoItem] | None = None,
    timezone_name: str = "UTC",
) -> list[MemoItem]:
    path = family_board_store_path(repo_root)
    if not os.path.exists(path):
        return active_memos(list(fallback_memos or []))
    try:
        with open(path, "r", encoding="utf-8") as f:
            parsed = json.load(f)
    except (json.JSONDecodeError, OSError):
        return active_memos(list(fallback_memos or []))

    rows = parsed.get("memos") if isinstance(parsed, dict) else None
    return load_memo_items_from_rows(rows, timezone_name=timezone_name)


def save_family_board(repo_root: str, memos: list[MemoItem]) -> None:
    path = family_board_store_path(repo_root)
    payload = family_board_store_payload(memos)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def load_memo_items_from_rows(rows: object, *, timezone_name: str = "UTC") -> list[MemoItem]:
    now_ts = time.time()
    out: list[MemoItem] = []
    if not isinstance(rows, list):
        return out

    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        timestamp = _coerce_float(row.get("timestamp"), default=now_ts)
        expiration_bucket = normalize_memo_expiration_bucket(
            row.get("expiration_bucket") or row.get("expiration") or row.get("expiry_bucket")
        )
        expires_at = _coerce_float_opt(row.get("expires_at"))
        if expires_at is None and expiration_bucket != "none":
            expires_at = resolve_memo_expires_at(expiration_bucket, now=timestamp, timezone_name=timezone_name)
        out.append(
            MemoItem(
                mid=str(row.get("mid") or row.get("id") or f"m{i}"),
                text=normalize_memo_text(row.get("text")),
                author=normalize_memo_author(row.get("author"), default="Voice"),
                timestamp=timestamp,
                is_new=_coerce_bool(row.get("is_new") if "is_new" in row else row.get("isNew")),
                expiration_bucket=expiration_bucket,
                expires_at=expires_at,
            )
        )
    return active_memos(out, now=now_ts)


def _coerce_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        raw = value.strip().lower()
        if raw in ("1", "true", "yes", "on"):
            return True
        if raw in ("0", "false", "no", "off"):
            return False
    return False


def _coerce_float(value: object, *, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _coerce_float_opt(value: object) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None
