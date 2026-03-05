from __future__ import annotations

import json
import os
from urllib.error import URLError
from urllib.request import Request, urlopen


_DEFAULT_TIMEOUT_S = 2.5


def _clean_text(value: object) -> str:
    return str(value or "").strip()


def _env_flag(name: str, default: bool) -> bool:
    raw = _clean_text(os.environ.get(name))
    if not raw:
        return bool(default)
    return raw.lower() not in ("0", "false", "off", "no")


def _timeout_s() -> float:
    raw = _clean_text(os.environ.get("LOCATION_LOOKUP_TIMEOUT_S"))
    if not raw:
        return _DEFAULT_TIMEOUT_S
    try:
        return max(0.5, min(8.0, float(raw)))
    except Exception:
        return _DEFAULT_TIMEOUT_S


def _http_json(url: str, *, timeout_s: float) -> dict | None:
    req = Request(url, headers={"User-Agent": "intelli-spark-e-paper-board/1.0"})
    try:
        with urlopen(req, timeout=timeout_s) as resp:
            body = resp.read()
    except (TimeoutError, URLError, OSError):
        return None
    except Exception:
        return None

    try:
        parsed = json.loads(body.decode("utf-8", errors="replace"))
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None


def _city_from_payload(payload: dict) -> str:
    city = _clean_text(payload.get("city"))
    if city:
        return city
    # Fallback for providers that omit city but return a region/state.
    for key in ("region", "regionName", "state", "county"):
        region = _clean_text(payload.get(key))
        if region:
            return region
    return ""


def detect_city_from_network(*, timeout_s: float | None = None) -> str:
    timeout = float(timeout_s or _timeout_s())
    sources = (
        "https://ipwho.is/?fields=success,city,region,country",
        "https://ipapi.co/json/",
        "https://ipinfo.io/json",
    )
    for url in sources:
        payload = _http_json(url, timeout_s=timeout)
        if not payload:
            continue
        if payload.get("success") is False:
            continue
        city = _city_from_payload(payload)
        if city:
            return city
    return ""


def resolve_dashboard_location(configured_location: object) -> str:
    manual = _clean_text(os.environ.get("DASHBOARD_CITY")) or _clean_text(os.environ.get("BOARD_CITY"))
    if manual:
        return manual

    # Preserve an explicitly configured city from dashboard data.
    configured = _clean_text(configured_location)
    if configured:
        return configured

    if _env_flag("LOCATION_AUTO_DETECT", True):
        city = detect_city_from_network()
        if city:
            return city

    return "Unknown"
