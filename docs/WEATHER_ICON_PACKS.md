# Weather Icon Packs (E-Paper)

This project supports selectable weather icon packs in the weather detail screen.

## 1) Theme Keys

Configure in `ui_tuner_theme.json`:

- `weather_icon_pack`: icon source
  - `native` (default built-in Python vector icons)
  - `erikflowers` (Weather Icons by Erik Flowers)
  - `kickstand` (Kickstand WeatherIcons)
- `weather_icon_variant`: style variant for `kickstand`
  - `thin`
  - `regular`
- `weather_icon_alpha_threshold`: integer threshold for PNG alpha binarization (Kickstand only)
  - Typical range: `170` to `210`
  - Higher value = cleaner/thinner strokes, less ghosting risk on e-paper

## 2) Assets

Stored under:

- `assets/weather_icon_packs/erikflowers/`
  - `weathericons-regular-webfont.ttf`
  - `README_UPSTREAM.md`
- `assets/weather_icon_packs/kickstand/`
  - `WeatherIcons.ttf`
  - `png/*.png`
  - `LICENSE.txt`
  - `README_UPSTREAM.md`

## 3) Quick Switch Examples

Use Erik Flowers:

```json
{
  "weather_icon_pack": "erikflowers"
}
```

Use Kickstand thin (recommended for current e-paper tuning):

```json
{
  "weather_icon_pack": "kickstand",
  "weather_icon_variant": "thin",
  "weather_icon_alpha_threshold": 185
}
```

## 4) Notes for E-Paper

- Kickstand icons are PNG-based and pass through alpha thresholding for crisp 1-bit-like edges.
- If panel ghosting appears, increase `weather_icon_alpha_threshold` (for example `195`).
- Forecast-row icon sizing is tuned separately from the hero icon.

## 5) License Notes

- Erik Flowers Weather Icons: icon font under SIL OFL 1.1 (see upstream README).
- Kickstand WeatherIcons: SIL OFL 1.1 (see `assets/weather_icon_packs/kickstand/LICENSE.txt`).

