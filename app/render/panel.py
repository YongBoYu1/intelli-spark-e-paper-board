from __future__ import annotations

from PIL import Image


def _clamp_u8(v) -> int:
    try:
        iv = int(round(float(v)))
    except Exception:
        return 0
    return max(0, min(255, iv))


def _to_gray(v, default: int) -> int:
    if isinstance(v, int):
        return _clamp_u8(v)
    if isinstance(v, str):
        s = v.strip()
        if s.startswith("#") and len(s) == 7:
            try:
                r = int(s[1:3], 16)
                g = int(s[3:5], 16)
                b = int(s[5:7], 16)
                return _clamp_u8(0.299 * r + 0.587 * g + 0.114 * b)
            except Exception:
                return _clamp_u8(default)
        try:
            return _clamp_u8(float(s))
        except Exception:
            return _clamp_u8(default)
    if isinstance(v, (list, tuple)) and len(v) >= 3:
        try:
            r = float(v[0])
            g = float(v[1])
            b = float(v[2])
            return _clamp_u8(0.299 * r + 0.587 * g + 0.114 * b)
        except Exception:
            return _clamp_u8(default)
    return _clamp_u8(default)


def build_panel_theme(theme: dict | None, *, muted_gray: int = 150) -> dict:
    """
    Build a deterministic grayscale theme for e-paper preview/hardware rendering.

    We intentionally render to RGB/L first, then quantize to 1-bit to avoid the
    very jagged direct draw artifacts from rendering primitives directly on mode '1'.
    """
    t = dict(theme or {})
    muted = _to_gray(t.get("panel_muted", t.get("muted")), muted_gray)
    t["ink"] = (0, 0, 0)
    t["border"] = (0, 0, 0)
    t["card"] = (255, 255, 255)
    t["bg"] = (255, 255, 255)
    t["muted"] = (muted, muted, muted)
    return t


def quantize_for_panel(
    image: Image.Image,
    *,
    threshold: int = 176,
    gamma: float = 1.0,
    dither: bool = False,
) -> Image.Image:
    """
    Convert rendered image to 1-bit panel-ready output.

    - gamma: tone mapping before threshold.
    - dither=True: use Floyd-Steinberg dithering to preserve perceived detail.
    """
    gray = image.convert("L")

    g = float(gamma or 1.0)
    if abs(g - 1.0) > 1e-6:
        g = max(0.1, min(4.0, g))
        gray = gray.point(lambda p: _clamp_u8(((float(p) / 255.0) ** g) * 255.0))

    if dither:
        return gray.convert("1", dither=Image.FLOYDSTEINBERG)

    cut = _clamp_u8(threshold)
    return gray.point(lambda p: 255 if p >= cut else 0, mode="1")
