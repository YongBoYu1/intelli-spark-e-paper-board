from __future__ import annotations

from enum import Enum


class SettingsItem(str, Enum):
    FONT_SIZE = "font_size"
    PARTIAL_REFRESH = "partial_refresh"
    FULL_REFRESH = "full_refresh"
    CONNECTIVITY = "connectivity"
    AUTO_SYNC = "auto_sync"
    SYNC_NOW = "sync_now"
    ROTATION = "rotation"
    BACK_HOME = "back_home"
    RESET_AND_WIPE = "reset_and_wipe"


SETTINGS_ORDER: list[SettingsItem] = [
    SettingsItem.FONT_SIZE,
    SettingsItem.PARTIAL_REFRESH,
    SettingsItem.FULL_REFRESH,
    SettingsItem.ROTATION,
    SettingsItem.CONNECTIVITY,
    SettingsItem.AUTO_SYNC,
    SettingsItem.SYNC_NOW,
    SettingsItem.BACK_HOME,
    SettingsItem.RESET_AND_WIPE,
]

SETTINGS_GROUPS: list[tuple[str, list[SettingsItem]]] = [
    (
        "DISPLAY",
        [
            SettingsItem.FONT_SIZE,
            SettingsItem.PARTIAL_REFRESH,
            SettingsItem.FULL_REFRESH,
            SettingsItem.ROTATION,
            SettingsItem.CONNECTIVITY,
        ],
    ),
    (
        "SYNC",
        [
            SettingsItem.AUTO_SYNC,
            SettingsItem.SYNC_NOW,
        ],
    ),
    (
        "OTHER",
        [
            SettingsItem.BACK_HOME,
            SettingsItem.RESET_AND_WIPE,
        ],
    ),
]


SETTINGS_LABELS: dict[SettingsItem, str] = {
    SettingsItem.FONT_SIZE: "FONT SIZE",
    SettingsItem.PARTIAL_REFRESH: "PARTIAL REFRESH",
    SettingsItem.FULL_REFRESH: "FULL REFRESH",
    SettingsItem.CONNECTIVITY: "WIFI + BT",
    SettingsItem.AUTO_SYNC: "AUTO SYNC",
    SettingsItem.SYNC_NOW: "SYNC NOW",
    SettingsItem.ROTATION: "ROTATION",
    SettingsItem.BACK_HOME: "BACK HOME",
    SettingsItem.RESET_AND_WIPE: "RESET / WEB DATA",
}
