from PIL import ImageFont


class FontBook:
    def __init__(self, font_paths, default_key=None):
        self.font_paths = dict(font_paths)
        self.default_key = default_key or (next(iter(self.font_paths)) if self.font_paths else None)
        self._cache = {}

    def get(self, key, size):
        font_key = key if key in self.font_paths else self.default_key
        if font_key is None:
            raise ValueError("No font configured")
        cache_key = (font_key, size)
        font = self._cache.get(cache_key)
        if font is not None:
            return font

        # Preferred font first.
        candidates = [font_key]
        # Then try other configured keys as fallback.
        for k in self.font_paths.keys():
            if k not in candidates:
                candidates.append(k)

        for k in candidates:
            path = self.font_paths.get(k)
            if not path:
                continue
            try:
                font = ImageFont.truetype(path, size)
                # Cache under the original requested key so repeated calls stay fast.
                self._cache[cache_key] = font
                return font
            except OSError:
                continue

        # Last-resort fallback to PIL bitmap font so rendering can continue.
        font = ImageFont.load_default()
        self._cache[cache_key] = font
        return font
