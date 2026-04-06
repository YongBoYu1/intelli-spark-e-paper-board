#!/usr/bin/env python3

from __future__ import annotations

import json
from pathlib import Path
import sys
import time

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from PIL import Image

from app.core.state import AppState, DashboardModel, Screen
from app.render.panel import build_panel_theme, quantize_for_panel
from app.shared.fonts import FontBook
from app.ui.onboarding import render_landing, render_onboarding

ASSET_DIR = REPO_ROOT / "firmware" / "main" / "assets"
THEME_PATH = REPO_ROOT / "ui_tuner_theme.json"


def load_theme() -> dict:
    if not THEME_PATH.exists():
        return {}
    with THEME_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def build_fonts() -> FontBook:
    font_dir = REPO_ROOT / "assets" / "fonts"
    return FontBook(
        {
            "inter_regular": str(font_dir / "Inter-Regular.ttf"),
            "inter_medium": str(font_dir / "Inter-Medium.ttf"),
            "inter_semibold": str(font_dir / "Inter-SemiBold.ttf"),
            "inter_bold": str(font_dir / "Inter-Bold.ttf"),
            "inter_black": str(font_dir / "Inter-Black.ttf"),
            "jet_bold": str(font_dir / "JetBrainsMono-Bold.ttf"),
            "jet_extrabold": str(font_dir / "JetBrainsMono-ExtraBold.ttf"),
            "playfair_regular": str(font_dir / "PlayfairDisplay-Regular.ttf"),
            "playfair_italic": str(font_dir / "PlayfairDisplay-Italic.ttf"),
            "playfair_bold": str(font_dir / "PlayfairDisplay-Bold.ttf"),
        },
        default_key="inter_regular",
    )


def panel_bytes_from_image(image: Image.Image) -> bytes:
    mono = image.convert("1")
    width, height = mono.size
    if width != 800 or height != 480:
        raise ValueError(f"unexpected image size {width}x{height}")

    out = bytearray((width // 8) * height)
    for y in range(height):
        row_base = y * (width // 8)
        for x in range(width):
            pixel = mono.getpixel((x, y))
            if pixel == 0:
                out[row_base + (x // 8)] |= 0x80 >> (x % 8)
    return bytes(out)


def render_landing_variant(locale: str, fonts: FontBook, theme: dict) -> Image.Image:
    state = AppState(model=DashboardModel())
    state.ui.screen = Screen.LANDING
    state.ui.device_language = locale
    state.ui.voice_locale = locale
    state.ui.setup_completed = False
    state.ui.landing_rotate_seen = False
    state.ui.landing_confirm_seen = False
    state.ui.landing_status = ""

    image = Image.new("RGB", (800, 480), (255, 255, 255))
    render_landing(image, state, fonts, theme)
    return quantize_for_panel(image, threshold=176, gamma=1.0, dither=False)


def render_onboarding_variant(step: str, locale: str, fonts: FontBook, theme: dict) -> Image.Image:
    state = AppState(model=DashboardModel())
    state.ui.screen = Screen.ONBOARDING
    state.ui.device_language = locale
    state.ui.voice_locale = locale
    state.ui.setup_completed = False
    state.ui.onboarding_step = step
    state.ui.onboarding_status = ""
    state.ui.onboarding_focus_index = 0
    state.ui.onboarding_qr_focus_index = 0
    state.ui.onboarding_prefs_focus_index = 0
    state.ui.onboarding_pair_token = "A1B2-C3D4"
    state.ui.onboarding_pair_expires_at = time.time() + 5 * 60
    state.ui.onboarding_wifi_ssid = "Home_2.4G"
    state.ui.device_timezone = "America/Toronto"
    state.ui.auto_sync_enabled = True
    state.ui.onboarding_voice_guide_focus_index = 0
    state.ui.onboarding_voice_demo_heard = ""
    state.ui.onboarding_voice_demo_attempted = False
    state.ui.onboarding_voice_demo_case_index = 0
    state.ui.onboarding_voice_demo_pass_mask = 0
    state.ui.onboarding_voice_demo_action = ""
    state.ui.onboarding_voice_sample_text = "Add milk to inventory"
    state.ui.onboarding_voice_expected_action = "Add inventory"

    if step == "pair_qr":
        state.ui.onboarding_status = "Waiting for phone callback..."
    elif step == "voice_guide":
        state.ui.onboarding_status = "Hold voice key to test current sample."

    image = Image.new("RGB", (800, 480), (255, 255, 255))
    render_onboarding(image, state, fonts, theme)
    return quantize_for_panel(image, threshold=176, gamma=1.0, dither=False)


def main() -> None:
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    fonts = build_fonts()
    theme = build_panel_theme(load_theme(), muted_gray=150)
    variants = {
        "landing_en.raw": "en-US",
        "landing_es.raw": "es-ES",
        "landing_fr.raw": "fr-FR",
    }

    for filename, locale in variants.items():
        image = render_landing_variant(locale, fonts, theme)
        raw = panel_bytes_from_image(image)
        (ASSET_DIR / filename).write_bytes(raw)
        image.save(ASSET_DIR / filename.replace(".raw", ".png"))
        print(f"generated {filename} ({len(raw)} bytes)")

    onboarding_variants = {
        "onboarding_start_en.raw": "start",
        "onboarding_pair_qr_en.raw": "pair_qr",
        "onboarding_prefs_en.raw": "prefs",
        "onboarding_voice_guide_en.raw": "voice_guide",
    }

    for filename, step in onboarding_variants.items():
        image = render_onboarding_variant(step, "en-US", fonts, theme)
        raw = panel_bytes_from_image(image)
        (ASSET_DIR / filename).write_bytes(raw)
        image.save(ASSET_DIR / filename.replace(".raw", ".png"))
        print(f"generated {filename} ({len(raw)} bytes)")


if __name__ == "__main__":
    main()
