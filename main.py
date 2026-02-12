#!/usr/bin/env python3
import argparse
import os

from PIL import Image

from app.data.mock import load_dashboard
from app.render.epd import display_image, init_epd
from app.shared.fonts import FontBook
from app.shared.paths import find_repo_root, get_waveshare_paths
from app.ui.home import render_home


def _parse_size(value):
    parts = value.lower().split("x")
    if len(parts) != 2:
        raise argparse.ArgumentTypeError("size must be like 800x400")
    return int(parts[0]), int(parts[1])


def _hex_to_rgb(value):
    value = value.strip()
    if value.startswith("#"):
        value = value[1:]
    if len(value) != 6:
        return None
    return tuple(int(value[i:i+2], 16) for i in (0, 2, 4))


def _load_theme(path):
    import json
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    theme = dict(data)
    for key in ("ink", "border", "card", "muted", "bg"):
        val = theme.get(key)
        if isinstance(val, str):
            rgb = _hex_to_rgb(val)
            if rgb:
                theme[key] = rgb
        elif isinstance(val, list) and len(val) == 3:
            # JSON color arrays become Python lists; PIL expects tuples.
            theme[key] = tuple(val)
    return theme


def main():
    parser = argparse.ArgumentParser(description="Fridge Ink UI")
    parser.add_argument("--png", default="", help="Render to a PNG file instead of the e-paper display")
    parser.add_argument("--size", default="800x480", help="PNG output size, e.g. 800x480")
    parser.add_argument("--theme", default="", help="Path to ui_tuner_theme.json")
    args = parser.parse_args()

    data = load_dashboard()

    repo_root = find_repo_root(os.path.dirname(__file__))
    fonts = FontBook(
        {
            "inter_regular": os.path.join(repo_root, "assets", "fonts", "Inter-Regular.ttf"),
            "inter_medium": os.path.join(repo_root, "assets", "fonts", "Inter-Medium.ttf"),
            "inter_semibold": os.path.join(repo_root, "assets", "fonts", "Inter-SemiBold.ttf"),
            "inter_bold": os.path.join(repo_root, "assets", "fonts", "Inter-Bold.ttf"),
            "inter_black": os.path.join(repo_root, "assets", "fonts", "Inter-Black.ttf"),
            "jet_bold": os.path.join(repo_root, "assets", "fonts", "JetBrainsMono-Bold.ttf"),
            "jet_extrabold": os.path.join(repo_root, "assets", "fonts", "JetBrainsMono-ExtraBold.ttf"),
        },
        default_key="inter_regular",
    )

    theme = {}
    if args.theme:
        theme = _load_theme(args.theme)

    if args.png:
        width, height = _parse_size(args.size)
        if not theme:
            theme = {
                "ink": (17, 17, 17),
                "card": (255, 255, 255),
                "muted": (160, 160, 160),
                "border": (17, 17, 17),
            }
        bg = theme.get("bg", (229, 229, 229))
        image = Image.new("RGB", (width, height), bg)
        render_home(image, data, fonts, theme=theme)
        image.save(args.png)
        return

    epd, picdir = init_epd()
    if not theme:
        theme = {
            "ink": 0,
            "card": 255,
            "muted": 0,
            "border": 0,
        }
    else:
        # force monochrome for e-paper
        theme["ink"] = 0
        theme["border"] = 0
        theme["muted"] = 0
        theme["card"] = 255
    image = Image.new("1", (epd.width, epd.height), 255)
    render_home(image, data, fonts, theme=theme)
    display_image(epd, image)


if __name__ == "__main__":
    main()
