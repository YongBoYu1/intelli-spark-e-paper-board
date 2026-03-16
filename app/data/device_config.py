from __future__ import annotations

import json
import os
from datetime import datetime


def detect_local_timezone() -> str:
    try:
        tzinfo = datetime.now().astimezone().tzinfo
        if tzinfo is None:
            return "UTC"
        key = getattr(tzinfo, "key", None)
        if isinstance(key, str) and key.strip():
            return key.strip()
        name = tzinfo.tzname(None)
        if isinstance(name, str) and name.strip():
            return name.strip()
    except Exception:
        pass
    return "UTC"


def default_device_config() -> dict:
    return {
        "setup_completed": False,
        "language": "en-US",
        "voice_locale": "en-US",
        "timezone": detect_local_timezone(),
        "hardware_target": "linux-rpi",
        "board_profile": "",
        "display_panel": "waveshare-7.5-v2",
        "auto_sync_enabled": True,
        "wifi_enabled": False,
        "bluetooth_enabled": False,
        "wifi_ssid": "",
    }


def device_config_path(repo_root: str) -> str:
    return os.path.join(str(repo_root), "data", "device_config.json")


def _clean_text(value: object) -> str:
    return str(value or "").strip()


def _coerce_bool(value: object, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        raw = value.strip().lower()
        if raw in ("1", "true", "on", "yes"):
            return True
        if raw in ("0", "false", "off", "no"):
            return False
    return bool(default)


def sanitize_device_config(raw: object) -> dict:
    defaults = default_device_config()
    data = raw if isinstance(raw, dict) else {}
    out = dict(defaults)

    out["setup_completed"] = _coerce_bool(data.get("setup_completed"), defaults["setup_completed"])
    lang = _clean_text(data.get("language")) or defaults["language"]
    if lang not in ("en-US", "es-ES", "fr-FR"):
        lang = defaults["language"]
    out["language"] = lang

    voice_locale = _clean_text(data.get("voice_locale")) or defaults["voice_locale"]
    if voice_locale not in ("en-US", "es-ES", "fr-FR"):
        voice_locale = defaults["voice_locale"]
    out["voice_locale"] = voice_locale

    tz_name = _clean_text(data.get("timezone")) or defaults["timezone"]
    out["timezone"] = tz_name
    hardware_target = _clean_text(data.get("hardware_target")) or defaults["hardware_target"]
    if hardware_target not in ("linux-rpi", "esp32-s3"):
        hardware_target = defaults["hardware_target"]
    out["hardware_target"] = hardware_target
    out["board_profile"] = _clean_text(data.get("board_profile"))
    display_panel = _clean_text(data.get("display_panel")) or defaults["display_panel"]
    if display_panel not in ("waveshare-7.5-v2",):
        display_panel = defaults["display_panel"]
    out["display_panel"] = display_panel
    out["auto_sync_enabled"] = _coerce_bool(data.get("auto_sync_enabled"), defaults["auto_sync_enabled"])
    out["wifi_enabled"] = _coerce_bool(data.get("wifi_enabled"), defaults["wifi_enabled"])
    out["bluetooth_enabled"] = _coerce_bool(data.get("bluetooth_enabled"), defaults["bluetooth_enabled"])
    out["wifi_ssid"] = _clean_text(data.get("wifi_ssid"))
    return out


def load_device_config(repo_root: str) -> dict:
    path = device_config_path(repo_root)
    if not os.path.exists(path):
        return default_device_config()
    try:
        with open(path, "r", encoding="utf-8") as f:
            parsed = json.load(f)
    except Exception:
        return default_device_config()
    return sanitize_device_config(parsed)


def save_device_config(repo_root: str, config: dict) -> None:
    path = device_config_path(repo_root)
    payload = sanitize_device_config(config)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)
