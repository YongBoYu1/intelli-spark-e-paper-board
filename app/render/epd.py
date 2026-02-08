import os
import sys

from app.shared.paths import find_repo_root, get_waveshare_paths


def _load_driver():
    repo_root = find_repo_root(os.path.dirname(__file__))
    _, picdir, libdir = get_waveshare_paths(repo_root)
    if os.path.isdir(libdir):
        if libdir not in sys.path:
            sys.path.append(libdir)
    else:
        raise RuntimeError("waveshare_epd lib not found. Set WAVESHARE_PYTHON_ROOT or init submodule.")

    from waveshare_epd import epd7in5_V2

    return epd7in5_V2, picdir


def init_epd():
    epd7in5_V2, picdir = _load_driver()
    epd = epd7in5_V2.EPD()
    epd.init()
    epd.Clear()
    return epd, picdir


def display_image(epd, image):
    epd.display(epd.getbuffer(image))
    epd.sleep()
