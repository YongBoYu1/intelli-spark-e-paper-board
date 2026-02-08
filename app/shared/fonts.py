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
        path = self.font_paths[font_key]
        cache_key = (font_key, size)
        font = self._cache.get(cache_key)
        if font is None:
            font = ImageFont.truetype(path, size)
            self._cache[cache_key] = font
        return font
