#include "ui/screens/weather_screen.hpp"

#include "app/state.hpp"
#include "platform/panel_config.hpp"
#include "ui/draw.hpp"
#include "ui/panel_font_assets_generated.hpp"
#include "ui/primitives.hpp"

#include <algorithm>
#include <array>
#include <string>
#include <vector>

namespace fridge_ink::ui {
namespace {

using platform::panel_font_assets::BitmapFont;
using platform::panel_font_assets::Glyph;

// ── Font helpers (same pattern as home_screen.cpp) ──────────────────────────

std::size_t wl_glyph_index(const char ch) {
  const unsigned char code = static_cast<unsigned char>(ch);
  if (code == 0xB0u) return 95u;  // U+00B0 DEGREE SIGN — appended at index 95
  if (code < 32u || code > 126u) return static_cast<std::size_t>('?' - 32);
  return static_cast<std::size_t>(code - 32);
}

void wl_draw_glyph(
    std::vector<uint8_t>& image,
    const int x,
    const int y,
    const char ch,
    const BitmapFont& font,
    const bool black = true) {
  const Glyph& g = font.glyphs[wl_glyph_index(ch)];
  if (g.width == 0 || g.height == 0) return;
  const int row_bytes = (g.width + 7) / 8;
  const std::uint8_t* bm = font.bitmap + g.bitmap_offset;
  for (int row = 0; row < g.height; ++row) {
    for (int col = 0; col < g.width; ++col) {
      if (!((bm[row * row_bytes + (col / 8)] & (0x80U >> (col % 8))) != 0)) continue;
      if (black) set_black_pixel(image, x + g.left + col, y + g.top + row);
      else       clear_pixel(image,     x + g.left + col, y + g.top + row);
    }
  }
}

int wl_text_width(const std::string& text, const BitmapFont& font) {
  int w = 0;
  for (const char ch : text) w += font.glyphs[wl_glyph_index(ch)].advance;
  return w;
}

struct WlVBounds { int top{0}; int bottom{0}; bool valid{false}; };

WlVBounds wl_vbounds(const std::string& text, const BitmapFont& font) {
  WlVBounds b{};
  for (const char ch : text) {
    const Glyph& g = font.glyphs[wl_glyph_index(ch)];
    if (g.width == 0 || g.height == 0) continue;
    if (!b.valid) { b.top = static_cast<int>(g.top); b.bottom = static_cast<int>(g.top) + g.height; b.valid = true; continue; }
    b.top    = std::min(b.top,    static_cast<int>(g.top));
    b.bottom = std::max(b.bottom, static_cast<int>(g.top) + g.height);
  }
  return b;
}

int wl_text_height(const std::string& text, const BitmapFont& font) {
  const WlVBounds b = wl_vbounds(text, font);
  return b.valid ? std::max(1, b.bottom - b.top) : font.line_height;
}

int wl_center_y(const int zone_top, const int zone_h, const std::string& text, const BitmapFont& font) {
  const WlVBounds b = wl_vbounds(text, font);
  if (!b.valid) return zone_top + (zone_h - font.line_height) / 2;
  return zone_top + ((zone_h - (b.bottom - b.top)) / 2) - b.top;
}

void wl_draw_text(
    std::vector<uint8_t>& image,
    const int x,
    const int y,
    const std::string& text,
    const BitmapFont& font,
    const bool black = true) {
  int cx = x;
  for (const char ch : text) {
    wl_draw_glyph(image, cx, y, ch, font, black);
    cx += font.glyphs[wl_glyph_index(ch)].advance;
  }
}

void wl_draw_centered(
    std::vector<uint8_t>& image,
    const int zone_x,
    const int zone_w,
    const int y,
    const std::string& text,
    const BitmapFont& font,
    const bool black = true) {
  const int w = wl_text_width(text, font);
  wl_draw_text(image, zone_x + (zone_w - w) / 2, y, text, font, black);
}

std::string wl_upper(const std::string& s) {
  std::string out = s;
  for (char& c : out) if (c >= 'a' && c <= 'z') c -= 32;
  return out;
}

std::string wl_trunc(const std::string& text, const BitmapFont& font, const int max_px) {
  if (max_px <= 0) return {};
  int w = 0;
  std::string out;
  for (const char ch : text) {
    const int adv = font.glyphs[wl_glyph_index(ch)].advance;
    if (w + adv > max_px) {
      const std::string ell = "...";
      const int ew = wl_text_width(ell, font);
      while (!out.empty() && wl_text_width(out, font) + ew > max_px) out.pop_back();
      return out + ell;
    }
    w += adv;
    out += ch;
  }
  return out;
}

// ── Layout constants (800×480) ───────────────────────────────────────────────

constexpr int kL_Cx0 = 22;
constexpr int kL_Cx1 = 778;
constexpr int kL_Cy0 = 16;
constexpr int kL_Cy1 = 464;
constexpr int kL_ColW = (kL_Cx1 - kL_Cx0) / 3;  // 252

constexpr int kL_HeroY0 = kL_Cy0;  // 16
constexpr int kL_HeroY1 = 200;
constexpr int kL_HeroH  = kL_HeroY1 - kL_HeroY0;  // 184

constexpr int kL_MetricY0 = 202;
constexpr int kL_MetricY1 = 290;
constexpr int kL_MetricH  = kL_MetricY1 - kL_MetricY0;  // 88

constexpr int kL_ForecastY0 = 292;
constexpr int kL_ForecastY1 = kL_Cy1;  // 464
constexpr int kL_ForecastH  = kL_ForecastY1 - kL_ForecastY0;  // 172

}  // namespace

std::vector<uint8_t> render_weather_landscape_bitmap(const app::AppState& state) {
  using namespace platform::panel_font_assets;
  using platform::kPanelBufferSize;

  std::vector<uint8_t> image(kPanelBufferSize, 0xFF);

  const bool weather_has_data = !state.dashboard.weather_condition.empty();
  const bool weather_syncing = state.home.weather_sync_state == "syncing";
  const std::string city = wl_upper(state.dashboard.location.empty() ? "UNKNOWN" : state.dashboard.location);
  const std::string condition = weather_has_data
                                    ? state.dashboard.weather_condition
                                    : std::string("Cloudy");
  const std::string icon_id = weather_has_data
                                  ? state.dashboard.weather_icon
                                  : std::string("cloud");
  const int temp_c = state.dashboard.weather_temperature_c;
  const int humidity = state.dashboard.weather_humidity_percent;
  const int feels_like_c = state.dashboard.weather_feels_like_c;
  const int hi_c = state.dashboard.weather_hi_c;
  const int lo_c = state.dashboard.weather_lo_c;
  const int wind_kmh = state.dashboard.weather_wind_kmh;
  const int uv_index = state.dashboard.weather_uv_index;

  const std::string temp_num   = weather_has_data ? std::to_string(temp_c) : "--";
  const std::string humidity_str =
      (weather_has_data && humidity > 0) ? (std::to_string(humidity) + "%") : "--";
  // No "C" suffix — degree "o" is drawn as a superscript separately.
  const std::string feels_like_str =
      weather_has_data ? ("FEELS LIKE " + std::to_string(feels_like_c))
                       : (weather_syncing ? "SYNCING..." : "FEELS LIKE --");
  const std::string range_str =
      weather_has_data
          ? ("H: " + std::to_string(hi_c) + "  L: " + std::to_string(lo_c))
          : "H: --  L: --";

  const int col0_x = kL_Cx0;
  const int col1_x = kL_Cx0 + kL_ColW;
  const int col2_x = kL_Cx0 + 2 * kL_ColW;

  // ── Dividers ──────────────────────────────────────────────────────────────
  fill_black_rect(image, kL_Cx0, kL_MetricY1, kL_Cx1, kL_MetricY1 + 2);
  fill_black_rect(image, col1_x, kL_ForecastY0 + 8, col1_x + 1, kL_ForecastY1 - 8);
  fill_black_rect(image, col2_x, kL_ForecastY0 + 8, col2_x + 1, kL_ForecastY1 - 8);

  // ── Hero: City (left col) ─────────────────────────────────────────────────
  {
    const BitmapFont& font = kFontInterBold22;
    const std::string city_fit = wl_trunc(city, font, kL_ColW - 12);
    const int y = wl_center_y(kL_HeroY0, kL_HeroH, city_fit, font);
    wl_draw_centered(image, col0_x, kL_ColW, y, city_fit, font);
  }

  // ── Hero: Weather icon (right col) ───────────────────────────────────────
  {
    constexpr int icon_size = 88;
    const int icon_x = col2_x + (kL_ColW - icon_size) / 2;
    const int icon_y = kL_HeroY0 + (kL_HeroH - icon_size) / 2;
    draw_icon(image, icon_x, icon_y, icon_id, icon_size);
  }

  // ── Hero: Temperature + labels (center col) ───────────────────────────────
  // °C is written as "\xB0" "C" — the 0xB0 byte maps to glyph index 95
  // (U+00B0 DEGREE SIGN, appended to the font charset by the generator).
  {
    const BitmapFont& temp_font  = kFontInterBlack66;
    const BitmapFont& label_font = kFontInterMedium18;  // FEELS LIKE — readable
    const BitmapFont& range_font = kFontInterMedium18;  // H / L row
    const BitmapFont& deg_font   = kFontInterBold22;    // °C superscript next to main temp

    const int inner_top    = kL_HeroY0 + 6;
    const int inner_bottom = kL_HeroY1 - 24;

    // ── "FEELS LIKE --°C" pinned to top of inner zone ────────────────────────
    // °C suffix is drawn at the same Y as the label text; the ° glyph sits in
    // the upper portion of the cap-height of label_font, which is correct for
    // a degree symbol following the number.
    static constexpr const char* kDegC = "\xB0" "C";  // real ° (0xB0) + C
    const int feels_zone_h = label_font.line_height;
    const int fl_text_w = wl_text_width(feels_like_str, label_font);
    const int fl_deg_w  = weather_has_data ? wl_text_width(kDegC, label_font) : 0;
    const int fl_pair_w = fl_text_w + fl_deg_w;
    const int fl_x      = col1_x + (kL_ColW - fl_pair_w) / 2;
    const int feels_y   = wl_center_y(inner_top, feels_zone_h, feels_like_str, label_font);
    wl_draw_text(image, fl_x, feels_y, feels_like_str, label_font, true);
    if (weather_has_data) {
      wl_draw_text(image, fl_x + fl_text_w, feels_y, kDegC, label_font, true);
    }
    const int feels_bottom = inner_top + feels_zone_h + 6;

    // ── "H: --  L: --" pinned to bottom of inner zone ────────────────────────
    const int range_zone_top = inner_bottom - static_cast<int>(range_font.line_height) - 2;
    const int range_y = wl_center_y(range_zone_top, static_cast<int>(range_font.line_height),
                                    range_str, range_font);
    wl_draw_centered(image, col1_x, kL_ColW, range_y, range_str, range_font);

    // ── Temperature centred in remaining space, with °C at upper-right ───────
    const int temp_zone_h = range_zone_top - feels_bottom;
    const int temp_y = wl_center_y(feels_bottom, std::max(1, temp_zone_h), temp_num, temp_font);

    // Compute the correct Y for the °C superscript: align its visual top with
    // the visual top of the temperature digit so it appears at the upper-right.
    const WlVBounds tmp_vb = wl_vbounds(temp_num, temp_font);
    const WlVBounds deg_vb = wl_vbounds(kDegC,    deg_font);
    const int deg_y = (tmp_vb.valid && deg_vb.valid)
                          ? temp_y + tmp_vb.top - deg_vb.top
                          : temp_y;

    const int temp_w = wl_text_width(temp_num, temp_font);
    const int deg_w  = weather_has_data ? (wl_text_width(kDegC, deg_font) + 2) : 0;
    const int pair_w = temp_w + deg_w;
    const int temp_x = col1_x + (kL_ColW - pair_w) / 2;
    wl_draw_text(image, temp_x, temp_y, temp_num, temp_font, true);
    if (weather_has_data) {
      wl_draw_text(image, temp_x + temp_w + 2, deg_y, kDegC, deg_font, true);
    }
  }

  // ── Metrics block ─────────────────────────────────────────────────────────
  {
    struct Item { std::string value; const char* label; };
    // WIND value stores the number only; "KM/H" unit is drawn separately in a
    // smaller font so it doesn't dominate the metric tile visually.
    const std::string wind_num_str = weather_has_data ? std::to_string(wind_kmh) : "--";
    const std::array<Item, 3> items = {{
      {humidity_str,  "HUMIDITY"},
      {wind_num_str,  "WIND"},
      {weather_has_data ? std::to_string(uv_index) : "--", "UV INDEX"},
    }};

    for (int i = 0; i < 3; ++i) {
      const int col_x = kL_Cx0 + i * kL_ColW;
      const BitmapFont& vf = kFontInterBlack29;
      const BitmapFont& lf = kFontInterMedium13;
      const std::string& val = items[static_cast<std::size_t>(i)].value;
      const std::string  lbl = items[static_cast<std::size_t>(i)].label;

      // For WIND (i==1): number in vf + "KM/H" in lf on same line, pair centred.
      const bool is_wind = (i == 1);
      const std::string unit_str = " KM/H";  // only used for wind

      const int val_w  = wl_text_width(val, vf);
      const int unit_w = (is_wind && weather_has_data) ? wl_text_width(unit_str, lf) : 0;
      const int pair_w = val_w + unit_w;

      const int val_h   = wl_text_height(val, vf);
      const int lbl_h   = wl_text_height(lbl, lf);
      const int block_h = val_h + 6 + lbl_h;
      const int block_top = kL_MetricY0 + (kL_MetricH - block_h) / 2;

      const int vy = wl_center_y(block_top, val_h, val, vf);

      if (is_wind && weather_has_data) {
        // Draw number + "KM/H" as a centred pair on the same baseline.
        const int pair_x = col_x + (kL_ColW - pair_w) / 2;
        wl_draw_text(image, pair_x,          vy, val,       vf, true);
        // Vertically centre the small unit label within the value's height zone.
        const int unit_h = wl_text_height(unit_str, lf);
        const int unit_y = wl_center_y(block_top, val_h, unit_str, lf);
        (void)unit_h;  // used implicitly via wl_center_y
        wl_draw_text(image, pair_x + val_w,  unit_y, unit_str, lf, true);
      } else {
        wl_draw_centered(image, col_x, kL_ColW, vy, val, vf);
      }

      const int lbl_top = block_top + val_h + 6;
      const int ly = wl_center_y(lbl_top, lbl_h, lbl, lf);
      wl_draw_centered(image, col_x, kL_ColW, ly, lbl, lf);
    }
  }

  // ── Forecast block ────────────────────────────────────────────────────────
  {
    for (int i = 0; i < 3; ++i) {
      const int col_x = kL_Cx0 + i * kL_ColW;
      const BitmapFont& dow_font  = kFontInterBold29;
      const BitmapFont& rng_font  = kFontInterBold22;
      const auto& forecast = state.dashboard.weather_forecast_days[static_cast<std::size_t>(i)];
      const std::string dow_str =
          weather_has_data && !forecast.dow.empty() ? forecast.dow : "--";
      const std::string rng_str =
          weather_has_data
              ? ("H: " + std::to_string(forecast.hi_c) + "  L: " + std::to_string(forecast.lo_c))
              : "H: --  L: --";

      // DOW at top
      const int dow_h = wl_text_height(dow_str, dow_font);
      const int dow_y = wl_center_y(kL_ForecastY0 + 8, dow_h, dow_str, dow_font);
      wl_draw_centered(image, col_x, kL_ColW, dow_y, dow_str, dow_font);
      const int dow_bottom = kL_ForecastY0 + 8 + dow_h + 6;

      // Temp range at bottom
      const int rng_h = wl_text_height(rng_str, rng_font);
      const int rng_top = kL_ForecastY1 - 10 - rng_h;
      const int rng_y = wl_center_y(rng_top, rng_h, rng_str, rng_font);
      wl_draw_centered(image, col_x, kL_ColW, rng_y, rng_str, rng_font);

      // Icon between DOW and temp range
      const int icon_room = rng_top - dow_bottom;
      const int icon_size = std::max(24, std::min(52, icon_room - 8));
      const int icon_x    = col_x + (kL_ColW - icon_size) / 2;
      const int icon_y    = dow_bottom + (icon_room - icon_size) / 2;
      draw_icon(
          image,
          icon_x,
          icon_y,
          weather_has_data && !forecast.icon.empty() ? forecast.icon : icon_id,
          icon_size);
    }
  }

  return image;
}

}  // namespace fridge_ink::ui
