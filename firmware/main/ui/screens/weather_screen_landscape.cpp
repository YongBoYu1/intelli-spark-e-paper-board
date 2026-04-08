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
  if (code < 32 || code > 126) return static_cast<std::size_t>('?' - 32);
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

  const std::string city      = wl_upper(state.dashboard.location.empty() ? "UNKNOWN" : state.dashboard.location);
  const std::string condition = state.dashboard.weather_condition;
  const int temp_c            = state.dashboard.weather_temperature_c;
  const int humidity          = state.dashboard.weather_humidity_percent;

  const std::string temp_str     = std::to_string(temp_c) + "C";
  const std::string humidity_str = std::to_string(humidity) + "%";

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
    draw_icon(image, icon_x, icon_y, condition, icon_size);
  }

  // ── Hero: Temperature + labels (center col) ───────────────────────────────
  {
    const BitmapFont& temp_font  = kFontInterBlack66;
    const BitmapFont& label_font = kFontInterMedium18;

    const int inner_top    = kL_HeroY0 + 6;
    const int inner_bottom = kL_HeroY1 - 24;

    // "FEELS LIKE --" pinned to top of inner zone
    const int feels_zone_h = label_font.line_height;
    const int feels_y = wl_center_y(inner_top, feels_zone_h, "FEELS LIKE --", label_font);
    wl_draw_centered(image, col1_x, kL_ColW, feels_y, "FEELS LIKE --", label_font);
    const int feels_bottom = inner_top + feels_zone_h + 6;

    // "H: --  L: --" pinned to bottom of inner zone
    const int range_zone_top = inner_bottom - label_font.line_height - 2;
    const int range_y = wl_center_y(range_zone_top, label_font.line_height, "H: --  L: --", label_font);
    wl_draw_centered(image, col1_x, kL_ColW, range_y, "H: --  L: --", label_font);

    // Temperature centered in remaining space
    const int temp_zone_h = range_zone_top - feels_bottom;
    const int temp_y = wl_center_y(feels_bottom, std::max(1, temp_zone_h), temp_str, temp_font);
    wl_draw_centered(image, col1_x, kL_ColW, temp_y, temp_str, temp_font);
  }

  // ── Metrics block ─────────────────────────────────────────────────────────
  {
    struct Item { std::string value; const char* label; };
    const std::array<Item, 3> items = {{
      {humidity_str, "HUMIDITY"},
      {"--",         "WIND"},
      {"--",         "UV INDEX"},
    }};

    for (int i = 0; i < 3; ++i) {
      const int col_x = kL_Cx0 + i * kL_ColW;
      const BitmapFont& vf = kFontInterBlack29;
      const BitmapFont& lf = kFontInterMedium13;
      const std::string& val = items[static_cast<std::size_t>(i)].value;
      const std::string  lbl = items[static_cast<std::size_t>(i)].label;

      const int val_h   = wl_text_height(val, vf);
      const int lbl_h   = wl_text_height(lbl, lf);
      const int block_h = val_h + 6 + lbl_h;
      const int block_top = kL_MetricY0 + (kL_MetricH - block_h) / 2;

      const int vy = wl_center_y(block_top, val_h, val, vf);
      wl_draw_centered(image, col_x, kL_ColW, vy, val, vf);

      const int lbl_top = block_top + val_h + 6;
      const int ly = wl_center_y(lbl_top, lbl_h, lbl, lf);
      wl_draw_centered(image, col_x, kL_ColW, ly, lbl, lf);
    }
  }

  // ── Forecast block ────────────────────────────────────────────────────────
  {
    constexpr std::array<const char*, 3> kDays = {"MON", "TUE", "WED"};

    for (int i = 0; i < 3; ++i) {
      const int col_x = kL_Cx0 + i * kL_ColW;
      const BitmapFont& dow_font  = kFontInterBold29;
      const BitmapFont& rng_font  = kFontInterBold22;
      const std::string dow_str   = kDays[static_cast<std::size_t>(i)];
      const std::string rng_str   = "H: --  L: --";

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
      draw_icon(image, icon_x, icon_y, condition, icon_size);
    }
  }

  return image;
}

}  // namespace fridge_ink::ui
