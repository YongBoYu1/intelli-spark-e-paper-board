#include "ui/screens/weather_screen.hpp"

#include "app/calendar_runtime.hpp"
#include "app/state.hpp"
#include "platform/panel_config.hpp"
#include "ui/draw.hpp"
#include "ui/panel_font_assets_generated.hpp"
#include "ui/primitives.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <initializer_list>
#include <string>
#include <vector>

namespace fridge_ink::ui {
namespace {

using platform::panel_font_assets::BitmapFont;
using platform::panel_font_assets::Glyph;
using platform::kPanelWidthBytes;

constexpr int kPW = 480;
constexpr int kPH = 800;

int normalize_rotation_deg(const int raw) {
  const int rounded = ((raw % 360) + 360) % 360;
  if (rounded >= 315 || rounded < 45) return 0;
  if (rounded < 135) return 90;
  if (rounded < 225) return 180;
  return 270;
}

bool use_r90_map(const app::AppState& state) {
  return normalize_rotation_deg(state.settings.rotation_deg) == 90;
}

void wp_px(std::vector<uint8_t>& image, const int cx, const int cy, const bool r90) {
  if (cx < 0 || cx >= kPW || cy < 0 || cy >= kPH) return;
  if (r90) {
    set_black_pixel(image, cy, 479 - cx);
  } else {
    set_black_pixel(image, 799 - cy, cx);
  }
}

void wp_fill(
    std::vector<uint8_t>& image,
    const int x0,
    const int y0,
    const int x1,
    const int y1,
    const bool r90) {
  for (int y = y0; y < y1; ++y) {
    for (int x = x0; x < x1; ++x) {
      wp_px(image, x, y, r90);
    }
  }
}

void wp_line(
    std::vector<uint8_t>& image,
    int x0,
    int y0,
    int x1,
    int y1,
    const bool r90,
    const int width = 1) {
  const int steps = std::max(std::abs(x1 - x0), std::abs(y1 - y0));
  if (steps <= 0) {
    wp_px(image, x0, y0, r90);
    return;
  }
  const int half = std::max(0, width / 2);
  for (int i = 0; i <= steps; ++i) {
    const double t = static_cast<double>(i) / static_cast<double>(steps);
    const int x = static_cast<int>(std::lround(static_cast<double>(x0) + (static_cast<double>(x1 - x0) * t)));
    const int y = static_cast<int>(std::lround(static_cast<double>(y0) + (static_cast<double>(y1 - y0) * t)));
    for (int oy = -half; oy <= half; ++oy) {
      for (int ox = -half; ox <= half; ++ox) {
        wp_px(image, x + ox, y + oy, r90);
      }
    }
  }
}

std::size_t wp_gi(const char ch) {
  const unsigned char c = static_cast<unsigned char>(ch);
  if (c < 32 || c > 126) return static_cast<std::size_t>('?' - 32);
  return static_cast<std::size_t>(c - 32);
}

void wp_glyph(
    std::vector<uint8_t>& image,
    const int x,
    const int y,
    const char ch,
    const BitmapFont& font,
    const bool r90) {
  const Glyph& g = font.glyphs[wp_gi(ch)];
  if (!g.width || !g.height) return;
  const int rb = (g.width + 7) / 8;
  const std::uint8_t* bm = font.bitmap + g.bitmap_offset;
  for (int row = 0; row < g.height; ++row) {
    for (int col = 0; col < g.width; ++col) {
      if ((bm[row * rb + col / 8] & (0x80U >> (col % 8))) == 0) continue;
      wp_px(image, x + g.left + col, y + static_cast<int>(g.top) + row, r90);
    }
  }
}

int wp_adv(const char ch, const BitmapFont& font) {
  return font.glyphs[wp_gi(ch)].advance;
}

int wp_text_width(const std::string& text, const BitmapFont& font) {
  int w = 0;
  for (const char ch : text) w += wp_adv(ch, font);
  return w;
}

struct WpVB { int top{0}; int bot{0}; bool ok{false}; };

WpVB wp_vbounds(const std::string& text, const BitmapFont& font) {
  WpVB b{};
  for (const char ch : text) {
    const Glyph& g = font.glyphs[wp_gi(ch)];
    if (!g.width || !g.height) continue;
    if (!b.ok) {
      b.top = static_cast<int>(g.top);
      b.bot = static_cast<int>(g.top) + g.height;
      b.ok = true;
    } else {
      b.top = std::min(b.top, static_cast<int>(g.top));
      b.bot = std::max(b.bot, static_cast<int>(g.top) + g.height);
    }
  }
  return b;
}

int wp_y_for_top(const int top, const std::string& text, const BitmapFont& font) {
  const WpVB b = wp_vbounds(text, font);
  return b.ok ? top - b.top : top;
}

int wp_y_center(
    const int zone_y,
    const int zone_h,
    const std::string& text,
    const BitmapFont& font) {
  const WpVB b = wp_vbounds(text, font);
  if (!b.ok) return zone_y + (zone_h - static_cast<int>(font.line_height)) / 2;
  return zone_y + (zone_h - (b.bot - b.top)) / 2 - b.top;
}

void wp_text(
    std::vector<uint8_t>& image,
    int x,
    const int y,
    const std::string& text,
    const BitmapFont& font,
    const bool r90) {
  for (const char ch : text) {
    wp_glyph(image, x, y, ch, font, r90);
    x += wp_adv(ch, font);
  }
}

void wp_centered(
    std::vector<uint8_t>& image,
    const int x0,
    const int x1,
    const int y,
    const std::string& text,
    const BitmapFont& font,
    const bool r90) {
  const int w = wp_text_width(text, font);
  wp_text(image, x0 + ((x1 - x0 - w) / 2), y, text, font, r90);
}

std::string wp_upper(std::string value) {
  for (char& ch : value) {
    if (ch >= 'a' && ch <= 'z') ch = static_cast<char>(ch - 32);
  }
  return value;
}

std::string wp_trunc(const std::string& text, const BitmapFont& font, const int max_px) {
  if (max_px <= 0) return {};
  int w = 0;
  std::string out;
  for (const char ch : text) {
    const int a = wp_adv(ch, font);
    if (w + a > max_px) {
      const std::string ell = "...";
      const int ew = wp_text_width(ell, font);
      while (!out.empty() && wp_text_width(out, font) + ew > max_px) out.pop_back();
      return out + ell;
    }
    w += a;
    out += ch;
  }
  return out;
}

struct WpFit {
  const BitmapFont* font{nullptr};
  std::string text{};
};

WpFit wp_fit(
    const std::string& text,
    const int max_px,
    std::initializer_list<const BitmapFont*> fonts,
    const bool ellipsis) {
  const int safe = std::max(1, max_px);
  const BitmapFont* fallback = nullptr;
  for (const BitmapFont* font : fonts) {
    if (font == nullptr) continue;
    fallback = font;
    if (wp_text_width(text, *font) <= safe) {
      return WpFit{font, text};
    }
  }
  if (fallback == nullptr) return WpFit{nullptr, text};
  if (!ellipsis) return WpFit{fallback, text};
  return WpFit{fallback, wp_trunc(text, *fallback, safe)};
}

void wp_icon(
    std::vector<uint8_t>& image,
    const int x,
    const int y,
    const int draw_w,
    const int draw_h,
    const std::string& cond,
    const bool r90) {
  const int src_size = std::max(draw_w, draw_h);
  std::vector<uint8_t> tmp(platform::kPanelBufferSize, 0xFF);
  draw_icon(tmp, 0, 0, cond, src_size);

  const int w = std::max(1, draw_w);
  const int h = std::max(1, draw_h);
  for (int yy = 0; yy < h; ++yy) {
    const int sy = std::max(0, std::min(src_size - 1, (yy * src_size) / h));
    for (int xx = 0; xx < w; ++xx) {
      const int sx = std::max(0, std::min(src_size - 1, (xx * src_size) / w));
      const int off = (sy * kPanelWidthBytes) + (sx / 8);
      if ((tmp[static_cast<std::size_t>(off)] & (0x80U >> (sx % 8))) == 0) {
        wp_px(image, x + xx, y + yy, r90);
      }
    }
  }
}

float wp_forecast_h_scale(const std::string& icon_name) {
  const std::string k = wp_upper(icon_name);
  if (k.find("PARTLY") != std::string::npos) return 0.78f;
  if (k.find("CLOUD") != std::string::npos || k.find("OVERCAST") != std::string::npos) return 0.70f;
  return 1.0f;
}

std::array<std::string, 3> wp_day_labels(const app::AppState& state) {
  std::array<std::string, 3> out = {"TMR", "--", "--"};
  const auto today = app::calendar_runtime::today_local_date(state);
  for (int i = 1; i < 3; ++i) {
    const auto d = app::calendar_runtime::add_days(today, i + 1);
    const int wd = app::calendar_runtime::weekday_sunday0(d);
    const char* name = app::calendar_runtime::weekday_name_upper_short(wd);
    out[static_cast<std::size_t>(i)] = name == nullptr ? "--" : std::string(name);
  }
  return out;
}

}  // namespace

std::vector<uint8_t> render_weather_portrait_bitmap(const app::AppState& state) {
  using namespace platform::panel_font_assets;
  using platform::kPanelBufferSize;

  std::vector<uint8_t> image(kPanelBufferSize, 0xFF);
  const bool r90 = use_r90_map(state);

  const std::string city = state.dashboard.location.empty() ? "Unknown" : state.dashboard.location;
  const std::string condition = state.dashboard.weather_condition.empty()
                                    ? std::string("Cloud")
                                    : state.dashboard.weather_condition;
  const int temp_c = state.dashboard.weather_temperature_c;
  const int humidity = state.dashboard.weather_humidity_percent;

  const std::string feels = "Feels Like " + std::to_string(temp_c) + "C";
  const std::string temp = std::to_string(temp_c) + "C";
  const std::string range = "H: " + std::to_string(temp_c) + "  L: " + std::to_string(temp_c);
  const std::string humidity_v = std::to_string(humidity) + "%";

  const std::array<std::string, 3> day_labels = wp_day_labels(state);

  // Python parity: full-screen weather detail uses only content padding,
  // no outer rounded panel/card border.
  constexpr int cx0 = 16;
  constexpr int cx1 = kPW - 17;
  constexpr int cy0 = 14;
  constexpr int cy1 = kPH - 15;

  const int content_h = cy1 - cy0;
  const int hero_h = std::max(220, static_cast<int>(content_h * 0.39));
  const int metrics_h = std::max(112, static_cast<int>(content_h * 0.18));

  const int hero_y0 = cy0;
  const int hero_y1 = hero_y0 + hero_h;
  const int metric_y0 = hero_y1;
  const int metric_y1 = metric_y0 + metrics_h;
  const int forecast_y0 = metric_y1;
  const int forecast_y1 = cy1;

  const int content_w = cx1 - cx0;
  const int col_w = content_w / 3;
  const int col1_x = cx0 + col_w;
  const int col2_x = cx0 + col_w * 2;

  // Divider between metrics and forecast (Python semantic anchor).
  wp_fill(image, cx0, metric_y1, cx1, metric_y1 + 2, r90);

  // Hero.
  const WpFit city_fit = wp_fit(city, content_w - 20, {&kFontInterBold29, &kFontInterBold22, &kFontInterBold20, &kFontInterBold18}, true);
  const WpFit feels_fit = wp_fit(feels, content_w - 24, {&kFontInterMedium18, &kFontInterBold17, &kFontInterMedium13}, true);
  const WpFit temp_fit = wp_fit(temp, content_w - 24, {&kFontInterBlack87, &kFontInterBlack66, &kFontInterBlack36}, false);
  const WpFit range_fit = wp_fit(range, content_w - 24, {&kFontInterMedium18, &kFontInterBold17, &kFontInterMedium13}, true);

  const BitmapFont& city_font = *city_fit.font;
  const BitmapFont& feels_font = *feels_fit.font;
  const BitmapFont& temp_font = *temp_fit.font;
  const BitmapFont& range_font = *range_fit.font;

  const int city_y = wp_y_for_top(hero_y0 + 2, city_fit.text, city_font);
  wp_centered(image, cx0, cx1, city_y, city_fit.text, city_font, r90);

  const int icon_box = std::max(58, std::min(96, std::min((content_w * 26) / 100, (hero_h * 30) / 100)));
  const int icon_x = cx0 + ((content_w - icon_box) / 2);
  const int icon_y = city_y + 44;
  wp_icon(image, icon_x, icon_y, icon_box, icon_box, condition, r90);

  const int feels_y = wp_y_for_top(icon_y + icon_box + 8, feels_fit.text, feels_font);
  wp_centered(image, cx0, cx1, feels_y, feels_fit.text, feels_font, r90);

  const int range_y_top = hero_y1 - 24;
  const int range_y = wp_y_for_top(range_y_top, range_fit.text, range_font);
  wp_centered(image, cx0, cx1, range_y, range_fit.text, range_font, r90);

  const int temp_zone_top = feels_y + 26;
  const int temp_zone_h = std::max(42, range_y_top - temp_zone_top - 4);
  const int temp_y = wp_y_center(temp_zone_top, temp_zone_h, temp_fit.text, temp_font);
  wp_centered(image, cx0, cx1, temp_y, temp_fit.text, temp_font, r90);

  // Metrics.
  struct MetricRow { std::string value; std::string label; };
  const std::array<MetricRow, 3> metrics = {{
      {humidity_v, "Humidity"},
      {"-- km/h", "Wind"},
      {"--", "UV Index"},
  }};

  for (int i = 0; i < 3; ++i) {
    const int x0 = cx0 + i * col_w;
    const int x1 = (i == 2) ? cx1 : (x0 + col_w);

    const WpFit val_fit = wp_fit(metrics[static_cast<std::size_t>(i)].value, x1 - x0 - 12,
                                 {&kFontInterBlack29, &kFontInterBold29, &kFontInterBold22, &kFontInterBold18}, true);
    const WpFit lbl_fit = wp_fit(metrics[static_cast<std::size_t>(i)].label, x1 - x0 - 12,
                                 {&kFontInterMedium18, &kFontInterMedium13, &kFontInterBold13}, true);

    const BitmapFont& vf = *val_fit.font;
    const BitmapFont& lf = *lbl_fit.font;

    const int vy = wp_y_for_top(metric_y0 + 26, val_fit.text, vf);
    const int ly = wp_y_for_top(metric_y0 + 62, lbl_fit.text, lf);
    wp_centered(image, x0, x1, vy, val_fit.text, vf, r90);
    wp_centered(image, x0, x1, ly, lbl_fit.text, lf, r90);
  }

  // Forecast.
  const int forecast_top = forecast_y0 + 8;
  const int forecast_bottom = forecast_y1 - 12;
  wp_line(image, col1_x, forecast_top, col1_x, forecast_bottom, r90, 1);
  wp_line(image, col2_x, forecast_top, col2_x, forecast_bottom, r90, 1);

  for (int i = 0; i < 3; ++i) {
    const int x0 = cx0 + i * col_w;
    const int x1 = (i == 2) ? cx1 : (x0 + col_w);
    const std::string day = day_labels[static_cast<std::size_t>(i)];

    const WpFit day_fit = wp_fit(day, x1 - x0 - 8, {&kFontInterBold29, &kFontInterBold22, &kFontInterBold20}, false);
    const WpFit rng_fit = wp_fit("--/--", x1 - x0 - 8, {&kFontInterBold22, &kFontInterBold20, &kFontInterBold18}, false);

    const BitmapFont& df = *day_fit.font;
    const BitmapFont& rf = *rng_fit.font;

    const int day_y = wp_y_for_top(forecast_top + 2, day_fit.text, df);
    wp_centered(image, x0, x1, day_y, day_fit.text, df, r90);

    const int rng_y_top = forecast_bottom - 24;
    const int rng_y = wp_y_for_top(rng_y_top, rng_fit.text, rf);
    wp_centered(image, x0, x1, rng_y, rng_fit.text, rf, r90);

    const int icon_box = 56;
    const float h_scale = wp_forecast_h_scale(condition);
    const int icon_w = icon_box;
    const int icon_h = std::max(34, static_cast<int>(static_cast<float>(icon_box) * h_scale));
    const int icon_x = x0 + ((x1 - x0 - icon_w) / 2);
    const int icon_y = day_y + 66;
    wp_icon(image, icon_x, icon_y, icon_w, icon_h, condition, r90);
  }

  return image;
}

}  // namespace fridge_ink::ui
