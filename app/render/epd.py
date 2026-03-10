import os
import sys
from types import MethodType

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
    _patch_epd7in5_v2_partial_init(epd)
    epd.init()
    epd.Clear()
    return epd, picdir


def display_image(epd, image, sleep_after=True):
    epd.display(epd.getbuffer(image))
    if sleep_after:
        epd.sleep()


def _patch_epd7in5_v2_partial_init(epd) -> None:
    original = getattr(epd, "init_part", None)
    if original is None or getattr(epd, "_codex_partial_init_patch", False):
        return

    def _init_part_stable(self):
        result = original()
        if result == -1:
            return result
        # Mirror the full-path drive settings that Waveshare notes help with
        # gray/washed output, but keep the runtime patch in the main repo so we
        # do not need to fork/push the vendor submodule.
        self.send_command(0x50)
        self.send_data(0x10)
        self.send_data(0x07)

        self.send_command(0x60)
        self.send_data(0x22)

        self.send_command(0x61)
        self.send_data(0x03)
        self.send_data(0x20)
        self.send_data(0x01)
        self.send_data(0xE0)

        self.send_command(0x15)
        self.send_data(0x00)
        return result

    epd.init_part = MethodType(_init_part_stable, epd)
    epd._codex_partial_init_patch = True
