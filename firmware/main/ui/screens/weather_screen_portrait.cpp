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

std::size_t wp_glyph_index(const char ch) {
  const unsigned char code = static_cast<unsigned char>(ch);
  if (code < 32 || code > 126) return static_cast<std::size_t>('?' - 32);
  return static_cast<std::size_t>(code - 32);
}

void wp_draw_glyph(
    std::vector<uint8_t>& image,
    const int x,
    const int y,
    const char ch,
    const BitmapFont& font,
    const bool black = true) {
  const Glyph& g = font.glyphs[wp_glyph_index(ch)];
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

int wp_text_width(const std::string& text, const BitmapFont& font) {
  int w = 0;
  for (const char ch : text) w += font.glyphs[wp_glyph_index(ch)].advance;
  return w;
}

struct WpVBounds { int top{0}; int bottom{0}; bool valid{false}; };

WpVBounds wp_vbounds(const std::string& text, const BitmapFont& font) {
  WpVBounds b{};
  for (const char ch : text) {
    const Glyph& g = font.glyphs[wp_glyph_index(ch)];
    if (g.width == 0 || g.height == 0) continue;
    if (!b.valid) { b.top = static_cast<int>(g.top); b.bottom = static_cast<int>(g.top) + g.height; b.valid = true; continue; }
    b.top    = std::min(b.top,    static_cast<int>(g.top));
    b.bottom = std::max(b.bottom, static_cast<int>(g.top) + g.height);
  }
  return b;
}

int wp_text_height(const std::string& text, const BitmapFont& font) {
  const WpVBounds b = wp_vbounds(text, font);
  return b.valid ? std::max(1, b.bottom - b.top) : font.line_height;
}

int wp_center_y(const int zone_top, const int zone_h, const std::string& text, const BitmapFont& font) {
  const WpVBounds b = wp_vbounds(text, font);
  if (!b.valid) return zone_top + (zone_h - font.line_height) / 2;
  return zone_top + ((zone_h - (b.bottom - b.top)) / 2) - b.top;
}

void wp_draw_text(
    std::vector<uint8_t>& image,
    const int x,
    const int y,
    const std::string& text,
    const BitmapFont& font,
    const bool black = true) {
  int cx = x;
  for (const char ch : text) {
    wp_draw_glyph(image, cx, y, ch, font, black);
    cx += font.glyphs[wp_glyph_index(ch)].advance;
  }
}

void wp_draw_centered(
    std::vector<uint8_t>& image,
    const int zone_x,
    const int zone_w,
    const int y,
    const std::string& text,
    const BitmapFont& font,
    const bool black = true) {
  const int w = wp_text_width(text, font);
  wp_draw_text(image, zone_x + (zone_w - w) / 2, y, text, font, black);
}

std::string wp_upper(const std::string& s) {
  std::string out = s;
  for (char& c : out) if (c >= 'a' && c <= 'z') c -= 32;
  return out;
}

std::string wp_trunc(const std::string& text, const BitmapFont& font, const int max_px) {
  if (max_px <= 0) return {};
  int w = 0;
  std::string out;
  for (const char ch : text) {
    const int adv = font.glyphs[wp_glyph_index(ch)].advance;
    if (w + adv > max_px) {
      const std::string ell = "...";
      const int ew = wp_text_width(ell, font);
      while (!out.empty() && wp_text_width(out, font) + ew > max_px) out.pop_back();
      return out + ell;
    }
    w += adv;
    out += ch;
  }
  return out;
}

// ── Layout constants (portrait card inside 800×480 buffer) ──────────────────
// Card is centered; when panel is rotated 90°/270° this fills the visible area.

constexpr int kP_CardX0 = 108;
constexpr int kP_CardX1 = 692;
constexpr int kP_CardY0 = 14;
constexpr int kP_CardY1 = 466;
constexpr int kP_CardW  = kP_CardX1 - kP_CardX0;  // 584
constexpr int kP_CardH  = kP_CardY1 - kP_CardY0;  // 452

// Content inside card (with padding)
constexpr int kP_Cx0 = kP_CardX0 + 16;  // 124
constexpr int kP_Cx1 = kP_CardX1 - 16;  // 676
constexpr int kP_Cy0 = kP_CardY0 + 14;  // 28
constexpr int kP_Cy1 = kP_CardY1 - 14;  // 452
constexpr int kP_CW  = kP_Cx1 - kP_Cx0;  // 552

// 3-column grid (183px each, +3 remainder)
constexpr int kP_ColW = kP_CW / 3;  // 184

// Section boundaries
constexpr int kP_HeroY0    = kP_Cy0;  // 28
constexpr int kP_HeroY1    = 248;
constexpr int kP_HeroH     = kP_HeroY1 - kP_HeroY0;  // 220

constexpr int kP_MetricY0  = 250;
constexpr int kP_MetricY1  = 362;
constexpr int kP_MetricH   = kP_MetricY1 - kP_MetricY0;  // 112

constexpr int kP_ForecastY0 = 364;
constexpr int kP_ForecastY1 = kP_Cy1;  // 452
constexpr int kP_ForecastH  = kP_ForecastY1 - kP_ForecastY0;  // 88

}  // namespace

std::vector<uint8_t> render_weather_portrait_bitmap(const app::AppState& state) {
  using namespace platform::panel_font_assets;
  using platform::kPanelBufferSize;

  std::vector<uint8_t> image(kPanelBufferSize, 0xFF);

  const std::string city      = wp_upper(state.dashboard.location.empty() ? "UNKNOWN" : state.dashboard.location);
  const std::string condition = state.dashboard.weather_condition;
  const int temp_c            = state.dashboard.weather_temperature_c;
  const int humidity          = state.dashboard.weather_humidity_percent;

  const std::string temp_str     = std::to_string(temp_c) + "C";
  const std::string humidity_str = std::to_string(humidity) + "%";

  // Card border
  draw_rounded_rect_stroke(image, kP_CardX0, kP_CardY0, kP_CardX1, kP_CardY1, 16, 2);

  const int col1_x = kP_Cx0 + kP_ColW;
  const int col2_x = kP_Cx0 + 2 * kP_ColW;

  // ── Dividers ──────────────────────────────────────────────────────────────
  fill_black_rect(image, kP_Cx0, kP_MetricY1, kP_Cx1, kP_MetricY1 + 2);
  fill_black_rect(image, col1_x, kP_ForecastY0 + 6, col1_x + 1, kP_ForecastY1 - 6);
  fill_black_rect(image, col2_x, kP_ForecastY0 + 6, col2_x + 1, kP_ForecastY1 - 6);

  // ── Hero block (stacked layout) ───────────────────────────────────────────
  {
    const BitmapFont& city_font   = kFontInterBold22;
    const BitmapFont& label_font  = kFontInterMedium18;
    const BitmapFont& temp_font   = kFontInterBlack66;

    // City name at top
    const int city_h = city_font.line_height;
    const int city_y = wp_center_y(kP_HeroY0 + 6, city_h, city, city_font);
    const std::string city_fit = wp_trunc(city, city_font, kP_CW - 16);
    wp_draw_centered(image, kP_Cx0, kP_CW, city_y, city_fit, city_font);
    const int city_bottom = kP_HeroY0 + 6 + city_h + 8;

    // Hero icon centered horizontally
    constexpr int icon_size = 66;
    const int icon_x = kP_Cx0 + (kP_CW - icon_size) / 2;
    const int icon_y = city_bottom;
    draw_icon(image, icon_x, icon_y, condition, icon_size);
    const int icon_bottom = icon_y + icon_size + 8;

    // "FEELS LIKE --" below icon
    const int feels_h = label_font.line_height;
    const int feels_y = wp_center_y(icon_bottom, feels_h, "FEELS LIKE --", label_font);
    wp_draw_centered(image, kP_Cx0, kP_CW, feels_y, "FEELS LIKE --", label_font);
    const int feels_bottom = icon_bottom + feels_h + 6;

    // "H: --  L: --" pinned to bottom of hero
    const int range_h = label_font.line_height;
    const int range_zone_top = kP_HeroY1 - range_h - 8;
    const int range_y = wp_center_y(range_zone_top, range_h, "H: --  L: --", label_font);
    wp_draw_centered(image, kP_Cx0, kP_CW, range_y, "H: --  L: --", label_font);

    // Temperature centered between feels_like and range
    const int temp_zone_h = range_zone_top - feels_bottom;
    const int temp_y = wp_center_y(feels_bottom, std::max(1, temp_zone_h), temp_str, temp_font);
    wp_draw_centered(image, kP_Cx0, kP_CW, temp_y, temp_str, temp_font);
  }

  // ── Metrics block ─────────────────────────────────────────────────────────
  {
    struct Item { std::string value; const char* label; };
    const std::array<Item, 3> items = {{
      {humidity_str, "HUMIDITY"},
      {"--",         "WIND"},
      {"--",         "UV"},
    }};

    for (int i = 0; i < 3; ++i) {
      const int col_x = kP_Cx0 + i * kP_ColW;
      const BitmapFont& vf = kFontInterBlack29;
      const BitmapFont& lf = kFontInterMedium13;
      const std::string& val = items[static_cast<std::size_t>(i)].value;
      const std::string  lbl = items[static_cast<std::size_t>(i)].label;

      const int val_h   = wp_text_height(val, vf);
      const int lbl_h   = wp_text_height(lbl, lf);
      const int block_h = val_h + 6 + lbl_h;
      const int block_top = kP_MetricY0 + (kP_MetricH - block_h) / 2;

      const int vy = wp_center_y(block_top, val_h, val, vf);
      wp_draw_centered(image, col_x, kP_ColW, vy, val, vf);

      const int lbl_top = block_top + val_h + 6;
      const int ly = wp_center_y(lbl_top, lbl_h, lbl, lf);
      wp_draw_centered(image, col_x, kP_ColW, ly, lbl, lf);
    }
  }

  // ── Forecast block ────────────────────────────────────────────────────────
  {
    constexpr std::array<const char*, 3> kDays = {"MON", "TUE", "WED"};

    for (int i = 0; i < 3; ++i) {
      const int col_x = kP_Cx0 + i * kP_ColW;
      const BitmapFont& dow_font  = kFontInterBold22;
      const BitmapFont& temp_font = kFontInterMedium13;
      const std::string dow_str   = kDays[static_cast<std::size_t>(i)];

      // DOW at top
      const int dow_h = wp_text_height(dow_str, dow_font);
      const int dow_y = wp_center_y(kP_ForecastY0 + 6, dow_h, dow_str, dow_font);
      wp_draw_centered(image, col_x, kP_ColW, dow_y, dow_str, dow_font);
      const int dow_bottom = kP_ForecastY0 + 6 + dow_h + 4;

      // Temp at bottom
      const int rng_h = wp_text_height(temp_str, temp_font);
      const int rng_top = kP_ForecastY1 - 8 - rng_h;
      const int rng_y = wp_center_y(rng_top, rng_h, temp_str, temp_font);
      wp_draw_centered(image, col_x, kP_ColW, rng_y, temp_str, temp_font);

      // Icon
      const int icon_room = rng_top - dow_bottom;
      const int icon_size = std::max(20, std::min(34, icon_room - 6));
      const int icon_x    = col_x + (kP_ColW - icon_size) / 2;
      const int icon_y    = dow_bottom + (icon_room - icon_size) / 2;
      draw_icon(image, icon_x, icon_y, condition, icon_size);
    }
  }

  return image;
}

}  // namespace fridge_ink::ui
