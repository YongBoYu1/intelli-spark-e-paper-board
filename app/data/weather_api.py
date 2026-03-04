from __future__ import annotations

import json
import os
from datetime import datetime
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def _clean_text(value: object) -> str:
    return str(value or "").strip()


def _env_flag(name: str, default: bool) -> bool:
    raw = _clean_text(os.environ.get(name))
    if not raw:
        return bool(default)
    return raw.lower() not in ("0", "false", "off", "no")


def _env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    raw = _clean_text(os.environ.get(name))
    if not raw:
        return int(default)
    try:
        value = int(raw)
    except Exception:
        value = int(default)
    return max(minimum, min(maximum, value))


def _timeout_s() -> float:
    raw = _clean_text(os.environ.get("WEATHER_LOOKUP_TIMEOUT_S"))
    if not raw:
        return 2.0
    try:
        return max(0.5, min(8.0, float(raw)))
    except Exception:
        return 2.0


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


def _to_float(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None


def _to_int(value) -> int | None:
    f = _to_float(value)
    if f is None:
        return None
    try:
        return int(round(f))
    except Exception:
        return None


def _dow_from_iso_date(raw: str) -> str:
    txt = _clean_text(raw)
    if not txt:
        return "--"
    try:
        return datetime.strptime(txt[:10], "%Y-%m-%d").strftime("%a").upper()
    except Exception:
        return "--"


def _normalize_location_label(result: dict, fallback_city: str) -> str:
    name = _clean_text(result.get("name"))
    if name:
        return name
    return _clean_text(fallback_city)


def _wmo_code_to_icon(code: int | None) -> str:
    if code is None:
        return "cloud"
    if code == 0:
        return "sun"
    if code == 1:
        return "clear"
    if code == 2:
        return "partly_cloudy"
    if code in (3, 45, 48):
        return "cloud"
    if code in (51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82):
        return "rain"
    if code in (71, 73, 75, 77, 85, 86):
        return "snow"
    if code in (95, 96, 99):
        return "storm"
    return "cloud"


def _open_meteo_geocode(city: str, *, timeout_s: float) -> tuple[float, float, str, str] | None:
    params = {
        "name": city,
        "count": "1",
        "language": _clean_text(os.environ.get("WEATHER_OPEN_METEO_LANGUAGE")) or "en",
        "format": "json",
    }
    base = _clean_text(os.environ.get("WEATHER_OPEN_METEO_GEOCODE_URL")) or "https://geocoding-api.open-meteo.com/v1/search"
    url = f"{base}?{urlencode(params)}"
    payload = _http_json(url, timeout_s=timeout_s)
    if not payload:
        return None
    rows = payload.get("results")
    if not isinstance(rows, list) or not rows:
        return None
    first = rows[0] if isinstance(rows[0], dict) else None
    if not first:
        return None
    lat = _to_float(first.get("latitude"))
    lon = _to_float(first.get("longitude"))
    if lat is None or lon is None:
        return None
    label = _normalize_location_label(first, city)
    timezone = _clean_text(first.get("timezone")) or "auto"
    return lat, lon, label, timezone


def _open_meteo_forecast_daily(lat: float, lon: float, *, timezone: str, forecast_days: int, timeout_s: float) -> list[dict]:
    daily_fields = ",".join(
        (
            "weather_code",
            "temperature_2m_max",
            "temperature_2m_min",
            "apparent_temperature_max",
            "wind_speed_10m_max",
            "uv_index_max",
            "relative_humidity_2m_max",
        )
    )
    params = {
        "latitude": f"{lat:.5f}",
        "longitude": f"{lon:.5f}",
        "daily": daily_fields,
        "forecast_days": str(max(1, min(7, int(forecast_days)))),
        "timezone": _clean_text(timezone) or "auto",
    }
    base = _clean_text(os.environ.get("WEATHER_OPEN_METEO_FORECAST_URL")) or "https://api.open-meteo.com/v1/forecast"
    url = f"{base}?{urlencode(params)}"
    payload = _http_json(url, timeout_s=timeout_s)
    if not payload:
        return []
    daily = payload.get("daily")
    if not isinstance(daily, dict):
        return []

    times = daily.get("time") or []
    tmax = daily.get("temperature_2m_max") or []
    tmin = daily.get("temperature_2m_min") or []
    weather_code = daily.get("weather_code") or []
    n = min(len(times), len(tmax), len(tmin), len(weather_code))
    if n <= 0:
        return []

    apparent = daily.get("apparent_temperature_max") or []
    wind = daily.get("wind_speed_10m_max") or []
    uv = daily.get("uv_index_max") or []
    humidity = daily.get("relative_humidity_2m_max") or []

    out: list[dict] = []
    for i in range(n):
        hi = _to_int(tmax[i])
        lo = _to_int(tmin[i])
        if hi is None or lo is None:
            continue
        row: dict = {
            "dow": _dow_from_iso_date(times[i]),
            "icon": _wmo_code_to_icon(_to_int(weather_code[i])),
            "hi": hi,
            "lo": lo,
        }
        hum = _to_int(humidity[i] if i < len(humidity) else None)
        if hum is not None:
            row["humidity"] = hum
        feels = _to_float(apparent[i] if i < len(apparent) else None)
        if feels is not None:
            row["feels_like"] = feels
        wind_kmh = _to_float(wind[i] if i < len(wind) else None)
        if wind_kmh is not None:
            row["wind_kmh"] = wind_kmh
        uv_idx = _to_float(uv[i] if i < len(uv) else None)
        if uv_idx is not None:
            row["uv_index"] = uv_idx
        out.append(row)
    return out


def _normalized_fallback_rows(rows: object) -> list[dict]:
    if not isinstance(rows, list):
        return []
    out: list[dict] = []
    for row in rows:
        if isinstance(row, dict):
            out.append(dict(row))
    return out


def resolve_weather_data(location: object, fallback_rows: object) -> tuple[str, list[dict]]:
    """
    Resolve weather rows using Open-Meteo when enabled.
    Falls back to caller-provided rows on network/API/geocode errors.
    """
    city = _clean_text(location)
    fallback = _normalized_fallback_rows(fallback_rows)

    if not _env_flag("WEATHER_API_ENABLED", True):
        return (city or "Unknown"), fallback

    provider = _clean_text(os.environ.get("WEATHER_API_PROVIDER")).lower()
    if provider and provider not in ("open_meteo", "open-meteo", "openmeteo"):
        return (city or "Unknown"), fallback

    if not city or city.lower() == "unknown":
        return (city or "Unknown"), fallback

    timeout_s = _timeout_s()
    forecast_days = _env_int("WEATHER_FORECAST_DAYS", 4, minimum=1, maximum=7)

    geo = _open_meteo_geocode(city, timeout_s=timeout_s)
    if not geo:
        return (city or "Unknown"), fallback
    lat, lon, resolved_city, timezone = geo

    live = _open_meteo_forecast_daily(
        lat,
        lon,
        timezone=timezone,
        forecast_days=forecast_days,
        timeout_s=timeout_s,
    )
    if not live:
        return (resolved_city or city or "Unknown"), fallback
    return (resolved_city or city or "Unknown"), live

