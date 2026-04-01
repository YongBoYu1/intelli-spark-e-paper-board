#include "ui/screens/home_screen.hpp"

#include "platform/panel_config.hpp"
#include "ui/draw.hpp"
#include "ui/primitives.hpp"
#include "ui/panel_font_assets_generated.hpp"

#include <algorithm>
#include <cmath>
#include <ctime>
#include <cstdlib>
#include <iomanip>
#include <sstream>
#include <string>
#include <vector>

namespace fridge_ink::ui {
namespace {

using platform::panel_font_assets::BitmapFont;
using platform::panel_font_assets::Glyph;

constexpr int kInventorySectionYOffset = 0;
constexpr int kSectionRowStartOffset = 34;

constexpr const char* kMicMask16[] = {
    "................",
    "......####......",
    "......####......",
    ".....##..##.....",
    ".....##..##.....",
    ".....##..##.....",
    "...#.##..##.#...",
    "...#.##..##.#...",
    "...##.####.##...",
    "...##..##..##...",
    "....###..###....",
    ".....######.....",
    ".......##.......",
    ".....######.....",
    ".....######.....",
    "................",
};

struct ClockSnapshot {
  bool valid{false};
  std::string time_label{"--:--"};
  std::string weekday_label{"THURSDAY"};
  std::string date_label{"MARCH 26, 2026"};
};

constexpr int kInventoryVisibleMax = 3;
constexpr int kReminderVisibleMax = 5;

enum class HomeFocusKind {
  Clock,
  Weather,
  Row,
};

struct HomeLandscapeMetrics {
  int width{0};
  int height{0};
  int ox0{0};
  int oy0{0};
  int ox1{0};
  int oy1{0};
  int top_y{0};
  int weather_top{0};
  int weather_left{0};
  int weather_right{0};
  int weather_bottom{0};
  int weather_icon_size{0};
  int weather_desc_y{0};
  int weather_icon_y{0};
  int weather_humidity_y{0};
  int weather_city_y{0};
  int header_focus_pad_x{0};
  int header_focus_pad_y{0};
  int row_focus_pad_x{0};
  int row_focus_pad_y{0};
  int row_focus_right_trim{0};
  int family_rule_y{0};
  int inv_y{0};
  int inv_row_y{0};
  int inv_row_h{0};
  int shop_title_h{0};
  int shop_line_gap{0};
  int shop_rule_y_min_gap{0};
  int shop_header_gap{0};
  int shop_row_h{0};
  int row_x0{0};
  int row_x1{0};
};

struct FocusBox {
  int x0{0};
  int y0{0};
  int x1{0};
  int y1{0};
  bool valid{false};
};

int visible_inventory_count(const app::DashboardSummary& dashboard);
std::vector<int> visible_reminder_indices(const app::AppState& state);
int visible_reminder_count(const app::AppState& state);

platform::DirtyRect clip_rect(
    const platform::DirtyRect& rect,
    const int width,
    const int height) {
  return {
      std::max(0, std::min(width, rect.x0)),
      std::max(0, std::min(height, rect.y0)),
      std::max(0, std::min(width, rect.x1)),
      std::max(0, std::min(height, rect.y1)),
  };
}

bool is_valid_rect(const platform::DirtyRect& rect) {
  return rect.x1 > rect.x0 && rect.y1 > rect.y0;
}

platform::DirtyRect merge_rects(
    const platform::DirtyRect& a,
    const platform::DirtyRect& b) {
  return {
      std::min(a.x0, b.x0),
      std::min(a.y0, b.y0),
      std::max(a.x1, b.x1),
      std::max(a.y1, b.y1),
  };
}

int approx_font_height(const int size, const double scale, const int minimum) {
  return std::max(minimum, static_cast<int>(std::lround(std::max(1, size) * scale)));
}

HomeLandscapeMetrics home_landscape_metrics() {
  using platform::kPanelHeight;
  using platform::kPanelWidth;

  HomeLandscapeMetrics metrics{};
  metrics.width = kPanelWidth;
  metrics.height = kPanelHeight;
  const int margin = 18;
  metrics.ox0 = margin;
  metrics.oy0 = margin;
  metrics.ox1 = std::max(margin + 1, kPanelWidth - margin);
  metrics.oy1 = std::max(margin + 1, kPanelHeight - margin);
  const int split_x = metrics.ox0 + ((metrics.ox1 - metrics.ox0) * 60) / 100;
  const int left_pad = 24;
  const int right_pad = 22;
  metrics.top_y = metrics.oy0 + left_pad;
  const int lx1 = split_x - left_pad;
  const int weather_col_w = 142;
  metrics.weather_right = lx1 - 2;
  metrics.weather_left = metrics.weather_right - weather_col_w;
  metrics.header_focus_pad_x = 6;
  metrics.header_focus_pad_y = 4;
  metrics.row_focus_pad_x = 6;
  metrics.row_focus_pad_y = 4;
  metrics.row_focus_right_trim = 0;

  metrics.weather_top = metrics.top_y - 2;
  const int city_h = approx_font_height(13, 0.84, 10);
  const int temp_h = approx_font_height(66, 0.78, 46);
  const int desc_h = approx_font_height(15, 0.86, 12);
  const int hum_h = approx_font_height(15, 0.86, 12);
  metrics.weather_icon_size =
      std::max(12, static_cast<int>(std::lround(34.0 * 1.35)));
  const int city_y = std::max(metrics.oy0 + 4, metrics.weather_top - city_h - 6);
  metrics.weather_city_y = city_y;
  metrics.weather_desc_y = metrics.weather_top + temp_h + 21;
  metrics.weather_icon_y = metrics.weather_desc_y + desc_h + 10;
  metrics.weather_humidity_y = metrics.weather_icon_y + metrics.weather_icon_size + 8;
  const int humidity_bottom = metrics.weather_humidity_y + hum_h;
  const int clock_bottom = metrics.top_y + approx_font_height(70, 0.78, 54) + 13 +
                           approx_font_height(15, 0.86, 12) + 11 +
                           approx_font_height(18, 0.86, 14);
  metrics.weather_bottom = std::max(
      std::max(clock_bottom, city_y + city_h),
      std::max(metrics.weather_desc_y + desc_h, humidity_bottom));

  const int header_rule_y = metrics.weather_bottom + 28;
  const int micro_h = approx_font_height(16, 0.78, 12);
  metrics.family_rule_y = header_rule_y + 8 + micro_h + 8;
  metrics.inv_y = metrics.oy0 + std::max(8, right_pad - 6) + kInventorySectionYOffset;
  metrics.inv_row_y = metrics.inv_y + kSectionRowStartOffset;
  metrics.inv_row_h = 40;
  metrics.shop_title_h = approx_font_height(13, 0.84, 10);
  metrics.shop_line_gap = 9;
  metrics.shop_rule_y_min_gap = 14;
  metrics.shop_header_gap = 24;
  metrics.shop_row_h = 40;

  const int inner_x0 = split_x + 1 + right_pad;
  const int inner_x1 = metrics.ox1 - right_pad;
  metrics.row_x0 = std::max(0, inner_x0 - metrics.row_focus_pad_x);
  metrics.row_x1 = std::min(
      metrics.width,
      inner_x1 + metrics.row_focus_pad_x - metrics.row_focus_right_trim);
  return metrics;
}

int home_shopping_row_y(const HomeLandscapeMetrics& metrics, const int inventory_rows) {
  const int safe_inventory_rows = std::max(0, inventory_rows);
  const int inv_bottom_y = metrics.inv_row_y + (safe_inventory_rows * metrics.inv_row_h);
  const int shop_rule_y =
      std::max(metrics.family_rule_y, inv_bottom_y + metrics.shop_rule_y_min_gap);
  const int shop_title_y = shop_rule_y - metrics.shop_title_h - metrics.shop_line_gap;
  return std::max(shop_title_y + metrics.shop_header_gap, shop_rule_y + 10);
}

HomeFocusKind home_focus_kind(const int focus_index) {
  if (focus_index <= 0) {
    return HomeFocusKind::Clock;
  }
  if (focus_index == 1) {
    return HomeFocusKind::Weather;
  }
  return HomeFocusKind::Row;
}

platform::DirtyRect closed_box_to_rect(
    const int x0,
    const int y0,
    const int x1,
    const int y1,
    const int outline_width = 1,
    const int extra_pad = 0) {
  const int stroke_pad = std::max(0, outline_width - 1);
  const int pad = std::max(0, extra_pad) + stroke_pad;
  return {x0 - pad, y0 - pad, x1 + pad + 1, y1 + pad + 1};
}

FocusBox home_header_focus_box(
    const HomeLandscapeMetrics& metrics,
    const HomeFocusKind kind) {
  if (kind == HomeFocusKind::Clock) {
    return {
        metrics.ox0 + 24 - metrics.header_focus_pad_x,
        std::max(metrics.oy0 + 2, metrics.top_y - 28),
        std::max(
            metrics.ox0 + 24 - metrics.header_focus_pad_x + 16,
            metrics.weather_left - 7),
        std::min(metrics.oy1, metrics.top_y + 142),
        true,
    };
  }
  if (kind == HomeFocusKind::Weather) {
    return {
        metrics.weather_left - metrics.header_focus_pad_x,
        std::max(metrics.oy0 + 2, metrics.weather_top - metrics.header_focus_pad_y),
        metrics.weather_right + metrics.header_focus_pad_x,
        std::min(metrics.oy1, metrics.weather_bottom + metrics.header_focus_pad_y),
        true,
    };
  }
  return {};
}

FocusBox home_focus_row_box(
    const HomeDirtySnapshot& snapshot,
    const int focus_index) {
  const HomeLandscapeMetrics metrics = home_landscape_metrics();
  const int inventory_count = snapshot.inventory_count;
  const int reminder_count = snapshot.reminder_count;
  int pos = focus_index - 2;
  if (pos < 0) {
    return {};
  }

  int row_y = 0;
  int row_h = 0;
  if (pos < inventory_count) {
    row_y = metrics.inv_row_y + (pos * metrics.inv_row_h);
    row_h = metrics.inv_row_h;
  } else {
    pos -= inventory_count;
    if (pos < 0 || pos >= reminder_count) {
      return {};
    }
    row_y = home_shopping_row_y(metrics, inventory_count) + (pos * metrics.shop_row_h);
    row_h = metrics.shop_row_h;
  }

  return {
      metrics.row_x0,
      row_y + metrics.row_focus_pad_y,
      metrics.row_x1,
      row_y + row_h - metrics.row_focus_pad_y,
      true,
  };
}

platform::DirtyRect home_header_focus_rect(const HomeLandscapeMetrics& metrics, const HomeFocusKind kind) {
  const FocusBox box = home_header_focus_box(metrics, kind);
  if (!box.valid) {
    return {};
  }
  return clip_rect(
      closed_box_to_rect(
          box.x0,
          box.y0,
          box.x1,
          box.y1,
          1),
      metrics.width,
      metrics.height);
}

platform::DirtyRect home_focus_row_rect(
    const HomeDirtySnapshot& snapshot,
    const int focus_index) {
  const FocusBox box = home_focus_row_box(snapshot, focus_index);
  if (!box.valid) {
    return {};
  }
  const HomeLandscapeMetrics metrics = home_landscape_metrics();
  return clip_rect(
      closed_box_to_rect(
          box.x0,
          box.y0,
          box.x1,
          box.y1,
          1,
          7),
      metrics.width,
      metrics.height);
}

platform::DirtyRect home_focus_rect(
    const HomeDirtySnapshot& snapshot,
    const int focus_index,
    const bool show_focus) {
  if (!show_focus) {
    return {};
  }
  const HomeFocusKind kind = home_focus_kind(focus_index);
  if (kind == HomeFocusKind::Row) {
    return home_focus_row_rect(snapshot, focus_index);
  }
  return home_header_focus_rect(home_landscape_metrics(), kind);
}

ClockSnapshot resolve_clock_snapshot(
    const std::uint64_t minute_bucket,
    const std::string& timezone_name,
    const bool clock_is_real) {
  (void)clock_is_real;
  ClockSnapshot snapshot;
  if (minute_bucket == 0) {
    return snapshot;
  }
  const auto apply_posix_timezone = [&](const std::string& zone) {
    static std::string active_tz{};
    std::string posix = "UTC0";
    if (zone == "America/Toronto" || zone == "America/New_York") {
      posix = "EST5EDT,M3.2.0/2,M11.1.0/2";
    } else if (zone == "America/Los_Angeles") {
      posix = "PST8PDT,M3.2.0/2,M11.1.0/2";
    }
    if (active_tz == posix) {
      return;
    }
    setenv("TZ", posix.c_str(), 1);
    tzset();
    active_tz = posix;
  };
  apply_posix_timezone(timezone_name);
  const std::time_t now = static_cast<std::time_t>(minute_bucket * 60ULL);

  std::tm local_tm{};
#if defined(_WIN32)
  localtime_s(&local_tm, &now);
#else
  localtime_r(&now, &local_tm);
#endif

  std::ostringstream time_out;
  time_out << std::put_time(&local_tm, "%H:%M");
  std::ostringstream weekday_out;
  weekday_out << std::put_time(&local_tm, "%A");
  std::ostringstream month_out;
  month_out << std::put_time(&local_tm, "%B");
  std::ostringstream date_out;
  date_out << month_out.str() << " " << local_tm.tm_mday << ", "
           << (1900 + local_tm.tm_year);

  snapshot.valid = true;
  snapshot.time_label = time_out.str();
  snapshot.weekday_label = weekday_out.str();
  snapshot.date_label = date_out.str();
  return snapshot;
}

std::string uppercase_copy(std::string value) {
  for (char& ch : value) {
    if (ch >= 'a' && ch <= 'z') {
      ch = static_cast<char>(ch - ('a' - 'A'));
    }
  }
  return value;
}

std::size_t glyph_index(const char ch) {
  const unsigned char code = static_cast<unsigned char>(ch);
  if (code < 32 || code > 126) {
    return static_cast<std::size_t>('?' - 32);
  }
  return static_cast<std::size_t>(code - 32);
}

void draw_glyph_with_font(
    std::vector<uint8_t>& image,
    const int x,
    const int y,
    const char ch,
    const BitmapFont& font,
    const bool black = true) {
  const Glyph& glyph = font.glyphs[glyph_index(ch)];
  if (glyph.width == 0 || glyph.height == 0) {
    return;
  }

  const int glyph_x0 = x + glyph.left;
  const int glyph_y0 = y + glyph.top;
  const int row_bytes = (glyph.width + 7) / 8;
  const std::uint8_t* bitmap = font.bitmap + glyph.bitmap_offset;

  for (int row = 0; row < glyph.height; ++row) {
    for (int col = 0; col < glyph.width; ++col) {
      const std::uint8_t byte = bitmap[row * row_bytes + (col / 8)];
      const bool on = (byte & (0x80U >> (col % 8))) != 0;
      if (!on) {
        continue;
      }
      if (black) {
        set_black_pixel(image, glyph_x0 + col, glyph_y0 + row);
      } else {
        clear_pixel(image, glyph_x0 + col, glyph_y0 + row);
      }
    }
  }
}

int text_width_with_font(const std::string& text, const BitmapFont& font) {
  int width = 0;
  for (const char ch : text) {
    width += font.glyphs[glyph_index(ch)].advance;
  }
  return width;
}

int text_width_with_font_spaced(
    const std::string& text,
    const BitmapFont& font,
    const int spacing) {
  if (text.empty()) {
    return 0;
  }
  int width = 0;
  bool first = true;
  for (const char ch : text) {
    if (!first) {
      width += spacing;
    }
    width += font.glyphs[glyph_index(ch)].advance;
    first = false;
  }
  return width;
}

std::string truncate_text_with_font(
    const std::string& text,
    const BitmapFont& font,
    const int max_width_px,
    const int spacing = 0) {
  if (text.empty() || max_width_px <= 0) {
    return "";
  }
  if (text_width_with_font_spaced(text, font, spacing) <= max_width_px) {
    return text;
  }

  const std::string ellipsis = "...";
  const int ellipsis_w = text_width_with_font_spaced(ellipsis, font, spacing);
  if (ellipsis_w >= max_width_px) {
    return ellipsis;
  }
  const int budget = std::max(0, max_width_px - ellipsis_w);

  std::string out;
  int width = 0;
  for (const char ch : text) {
    const int glyph_w = font.glyphs[glyph_index(ch)].advance;
    const int extra = glyph_w + (out.empty() ? 0 : spacing);
    if (width + extra > budget) {
      break;
    }
    if (!out.empty()) {
      width += spacing;
    }
    width += glyph_w;
    out.push_back(ch);
  }
  return out.empty() ? ellipsis : (out + ellipsis);
}

struct TextVerticalBounds {
  int top{0};
  int bottom{0};
  bool valid{false};
};

TextVerticalBounds text_vertical_bounds_with_font(
    const std::string& text,
    const BitmapFont& font) {
  TextVerticalBounds bounds{};
  for (const char ch : text) {
    const Glyph& glyph = font.glyphs[glyph_index(ch)];
    if (glyph.width == 0 || glyph.height == 0) {
      continue;
    }
    const int glyph_top = glyph.top;
    const int glyph_bottom = glyph.top + glyph.height;
    if (!bounds.valid) {
      bounds.top = glyph_top;
      bounds.bottom = glyph_bottom;
      bounds.valid = true;
      continue;
    }
    bounds.top = std::min(bounds.top, glyph_top);
    bounds.bottom = std::max(bounds.bottom, glyph_bottom);
  }
  return bounds;
}

int text_height_with_font(const std::string& text, const BitmapFont& font) {
  const TextVerticalBounds bounds = text_vertical_bounds_with_font(text, font);
  if (!bounds.valid) {
    return font.line_height;
  }
  return std::max(1, bounds.bottom - bounds.top);
}

int centered_text_y_with_font(
    const int row_y,
    const int row_h,
    const std::string& text,
    const BitmapFont& font) {
  const TextVerticalBounds bounds = text_vertical_bounds_with_font(text, font);
  if (!bounds.valid) {
    return row_y + (row_h - font.line_height) / 2;
  }
  const int text_h = bounds.bottom - bounds.top;
  return row_y + ((row_h - text_h) / 2) - bounds.top;
}

int centered_sample_y_with_font(
    const int row_y,
    const int row_h,
    const BitmapFont& font,
    const std::string& sample = "Ag") {
  return centered_text_y_with_font(row_y, row_h, sample, font);
}

void draw_text_with_font(
    std::vector<uint8_t>& image,
    const int x,
    const int y,
    const std::string& text,
    const BitmapFont& font,
    const int max_chars = 0,
    const bool black = true) {
  int cx = x;
  int drawn = 0;
  for (const char ch : text) {
    if (max_chars > 0 && drawn >= max_chars) {
      break;
    }
    draw_glyph_with_font(image, cx, y, ch, font, black);
    cx += font.glyphs[glyph_index(ch)].advance;
    ++drawn;
  }
}

void draw_text_with_font_spaced(
    std::vector<uint8_t>& image,
    const int x,
    const int y,
    const std::string& text,
    const BitmapFont& font,
    const int spacing,
    const bool black = true) {
  int cx = x;
  bool first = true;
  for (const char ch : text) {
    if (!first) {
      cx += spacing;
    }
    draw_glyph_with_font(image, cx, y, ch, font, black);
    cx += font.glyphs[glyph_index(ch)].advance;
    first = false;
  }
}

void draw_mask_icon(
    std::vector<uint8_t>& image,
    const int x,
    const int y,
    const int size,
    const char* const rows[16]) {
  const int scale = std::max(1, size / 16);
  for (int yy = 0; yy < 16; ++yy) {
    for (int xx = 0; xx < 16; ++xx) {
      if (rows[yy][xx] != '#') {
        continue;
      }
      fill_black_rect(
          image,
          x + xx * scale,
          y + yy * scale,
          x + (xx + 1) * scale,
          y + (yy + 1) * scale);
    }
  }
}

std::string right_fit_with_font(
    const std::string& value,
    const BitmapFont& font,
    const int width_px,
    const int spacing = 0) {
  return truncate_text_with_font(uppercase_copy(value), font, width_px, spacing);
}

std::string location_label(
    const app::AppState& state,
    const BitmapFont& font,
    const int width_px,
    const int spacing = 0) {
  std::string location = trim_copy(state.dashboard.location);
  if (location.empty()) {
    location = trim_copy(state.onboarding.timezone);
    const std::size_t slash = location.rfind('/');
    if (slash != std::string::npos && slash + 1 < location.size()) {
      location = location.substr(slash + 1);
    }
    for (char& ch : location) {
      if (ch == '_') {
        ch = ' ';
      }
    }
  }
  if (location.empty()) {
    location = "Toronto";
  }
  return truncate_text_with_font(uppercase_copy(location), font, width_px, spacing);
}

void draw_right_aligned_text_with_font(
    std::vector<uint8_t>& image,
    const int right_x,
    const int baseline_y,
    const std::string& text,
    const BitmapFont& font) {
  const int width = text_width_with_font(text, font);
  draw_text_with_font(image, right_x - width, baseline_y, text, font);
}

void draw_right_aligned_text_with_font_spaced(
    std::vector<uint8_t>& image,
    const int right_x,
    const int y,
    const std::string& text,
    const BitmapFont& font,
    const int spacing) {
  const int width = text_width_with_font_spaced(text, font, spacing);
  draw_text_with_font_spaced(image, right_x - width, y, text, font, spacing);
}

void draw_section_rule(
    std::vector<uint8_t>& image,
    const int x0,
    const int x1,
    const int y) {
  fill_black_rect(image, x0, y, x1, y + 1);
}

void draw_focus_stroke(
    std::vector<uint8_t>& image,
    const int x0,
    const int y0,
    const int x1,
    const int y1) {
  draw_rounded_rect_stroke(image, x0, y0, x1, y1, 6, 1);
}

void draw_degree_mark(
    std::vector<uint8_t>& image,
    const int x,
    const int y,
    const int size = 7) {
  const int d = std::max(4, size);
  draw_rounded_rect_stroke(image, x, y, x + d, y + d, std::max(2, d / 2), 1);
}

void draw_text_strikethrough(
    std::vector<uint8_t>& image,
    const int x,
    const int y,
    const std::string& text,
    const BitmapFont& font) {
  const TextVerticalBounds bounds = text_vertical_bounds_with_font(text, font);
  if (!bounds.valid) {
    return;
  }
  const int strike_y = y + bounds.top + ((bounds.bottom - bounds.top) / 2);
  fill_black_rect(
      image,
      x,
      strike_y,
      x + text_width_with_font(text, font),
      strike_y + 2);
}

void draw_mic_icon(std::vector<uint8_t>& image, const int x0, const int y0) {
  draw_mask_icon(image, x0, y0, 16, kMicMask16);
}

void draw_right_panel_focus_row(
    std::vector<uint8_t>& image,
    const int x0,
    const int x1,
    const int row_y,
    const int row_h) {
  draw_focus_stroke(image, x0 - 6, row_y + 4, x1 + 6, row_y + row_h - 4);
}

int visible_inventory_count(const app::DashboardSummary& dashboard) {
  return std::min(static_cast<int>(dashboard.inventory_items.size()), kInventoryVisibleMax);
}

bool contains_index(const std::vector<int>& values, const int index) {
  return std::find(values.begin(), values.end(), index) != values.end();
}

std::vector<int> visible_reminder_indices(const app::AppState& state) {
  const app::DashboardSummary& dashboard = state.dashboard;
  std::vector<int> indices{};
  const int total = static_cast<int>(dashboard.reminder_items.size());
  indices.reserve(std::min(total, kReminderVisibleMax));
  for (int i = 0; i < total; ++i) {
    if (contains_index(state.home.hidden_reminder_indices, i)) {
      continue;
    }
    indices.push_back(i);
    if (static_cast<int>(indices.size()) >= kReminderVisibleMax) {
      break;
    }
  }
  return indices;
}

int visible_reminder_count(const app::AppState& state) {
  return static_cast<int>(visible_reminder_indices(state).size());
}

int open_item_count(const int total_items, const std::vector<bool>& completed_items) {
  int open_count = 0;
  for (int i = 0; i < total_items; ++i) {
    const bool completed =
        i < static_cast<int>(completed_items.size()) &&
        completed_items[static_cast<std::size_t>(i)];
    if (!completed) {
      ++open_count;
    }
  }
  return open_count;
}

int home_focus_inventory_index(const app::AppState& state) {
  if (!state.home.show_focus || state.home.focused_index < 2) {
    return -1;
  }
  const int index = state.home.focused_index - 2;
  return index < visible_inventory_count(state.dashboard) ? index : -1;
}

int home_focus_reminder_index(const app::AppState& state) {
  if (!state.home.show_focus) {
    return -1;
  }
  const int base = 2 + visible_inventory_count(state.dashboard);
  const int index = state.home.focused_index - base;
  return (index >= 0 && index < visible_reminder_count(state)) ? index : -1;
}

void draw_inventory_section(
    std::vector<uint8_t>& image,
    const int x0,
    const int x1,
    const int title_y,
    const app::AppState& state) {
  const app::DashboardSummary& dashboard = state.dashboard;
  const BitmapFont& title_font = platform::panel_font_assets::kFontJetBold13;
  draw_text_with_font(image, x0, title_y, "INVENTORY", title_font);
  const int visible_count = visible_inventory_count(dashboard);
  const int open_count = open_item_count(
      static_cast<int>(dashboard.inventory_items.size()),
      dashboard.inventory_completed);
  if (open_count > 0) {
    draw_right_aligned_text_with_font(image, x1, title_y, std::to_string(open_count), title_font);
  }
  draw_section_rule(image, x0, x1, title_y + 18);

  const int row_h = 40;
  const int item_text_x = x0;
  const int badge_right_x = x1;
  const int focused_row = home_focus_inventory_index(state);
  const HomeDirtySnapshot snapshot = capture_home_dirty_snapshot(state);
  for (int i = 0; i < visible_count; ++i) {
    const int row_y = title_y + 34 + i * row_h;
    const bool completed =
        i < static_cast<int>(dashboard.inventory_completed.size()) &&
        dashboard.inventory_completed[static_cast<std::size_t>(i)];
    std::string badge = "STOCKED";
    if (completed) {
      badge = "OUT";
    }
    if (i < static_cast<int>(dashboard.inventory_badges.size()) &&
        !dashboard.inventory_badges[i].empty() &&
        !completed) {
      badge = uppercase_copy(dashboard.inventory_badges[i]);
    }
    badge = truncate_text_px(badge, 1, 84);
    const BitmapFont& badge_font = platform::panel_font_assets::kFontJetBold13;
    const int badge_width = text_width_with_font(badge, badge_font);

    const int title_max_w =
        std::max(86, (badge_right_x - badge_width - 14) - item_text_x);
    const std::string title =
        truncate_text_px(dashboard.inventory_items[i], 2, title_max_w);

    if (focused_row == i) {
      const FocusBox box = home_focus_row_box(snapshot, state.home.focused_index);
      if (box.valid) {
        draw_focus_stroke(image, box.x0, box.y0, box.x1, box.y1);
      }
    }
    const BitmapFont& item_font =
        focused_row == i
            ? platform::panel_font_assets::kFontInterBold18
            : platform::panel_font_assets::kFontInterMedium18;
    draw_text_with_font(
        image,
        item_text_x,
        centered_sample_y_with_font(row_y, row_h, item_font),
        title,
        item_font);
    if (completed) {
      draw_text_strikethrough(
          image,
          item_text_x,
          centered_sample_y_with_font(row_y, row_h, item_font),
          title,
          item_font);
    }
    draw_right_aligned_text_with_font(
        image,
        badge_right_x,
        centered_text_y_with_font(row_y, row_h, badge, badge_font),
        badge,
        badge_font);
  }
}

void draw_checkbox_row(
    std::vector<uint8_t>& image,
    const int x0,
    const int row_y,
    const int row_h,
    const int row_right_x,
    const int text_x,
    const std::string& text,
    const bool checked,
    const bool focused) {
  const int checkbox_size = 14;
  const int cb_x0 = x0;
  const int cb_y0 = row_y + ((row_h - checkbox_size) / 2);
  if (focused) {
    draw_right_panel_focus_row(image, x0, row_right_x, row_y, row_h);
  }
  draw_checkbox(image, cb_x0, cb_y0, checked, false, checkbox_size);
  const BitmapFont& text_font =
      focused ? platform::panel_font_assets::kFontInterBold18
              : platform::panel_font_assets::kFontInterMedium18;
  const std::string clipped =
      truncate_text_px(text, 2, std::max(0, row_right_x - text_x - 8));
  const int text_y = centered_sample_y_with_font(row_y, row_h, text_font);
  draw_text_with_font(
      image,
      text_x,
      text_y,
      clipped,
      text_font);
  if (checked) {
    draw_text_strikethrough(image, text_x, text_y, clipped, text_font);
  }
}

void draw_reminders_section(
    std::vector<uint8_t>& image,
    const int x0,
    const int x1,
    const app::AppState& state,
    const HomeLandscapeMetrics& metrics) {
  const app::DashboardSummary& dashboard = state.dashboard;
  const int inventory_rows = visible_inventory_count(dashboard);
  const int inv_bottom_y = metrics.inv_row_y + (inventory_rows * metrics.inv_row_h);
  const int shop_rule_y =
      std::max(metrics.family_rule_y, inv_bottom_y + metrics.shop_rule_y_min_gap);
  const int title_y = shop_rule_y - metrics.shop_title_h - metrics.shop_line_gap;
  const int row_start_y = std::max(title_y + metrics.shop_header_gap, shop_rule_y + 10);
  const BitmapFont& title_font = platform::panel_font_assets::kFontJetBold13;
  draw_text_with_font(image, x0, title_y, "REMINDERS", title_font);
  const std::vector<int> reminder_indices = visible_reminder_indices(state);
  const int visible_count = static_cast<int>(reminder_indices.size());
  int open_count = 0;
  for (int index = 0; index < static_cast<int>(dashboard.reminder_items.size()); ++index) {
    if (contains_index(state.home.hidden_reminder_indices, index)) {
      continue;
    }
    const bool completed =
        index >= 0 &&
        index < static_cast<int>(dashboard.reminder_completed.size()) &&
        dashboard.reminder_completed[static_cast<std::size_t>(index)];
    if (!completed) {
      ++open_count;
    }
  }
  const std::string count_text = std::to_string(open_count);
  const int count_width = text_width_with_font(count_text, title_font);
  const int count_x = x1 - count_width;
  draw_right_aligned_text_with_font(
      image,
      x1,
      title_y,
      count_text,
      title_font);
  const int shop_rule_right = std::min(x1 - 16, count_x - 6);
  if (shop_rule_right > x0) {
    draw_section_rule(image, x0, shop_rule_right, shop_rule_y);
  }

  const int row_h = 40;
  const int focused_row = home_focus_reminder_index(state);
  for (int i = 0; i < visible_count; ++i) {
    const int row_y = row_start_y + i * row_h;
    const int item_index = reminder_indices[static_cast<std::size_t>(i)];
    const bool checked =
        item_index >= 0 &&
        item_index < static_cast<int>(dashboard.reminder_completed.size()) &&
        dashboard.reminder_completed[static_cast<std::size_t>(item_index)];
    draw_checkbox_row(
        image,
        x0,
        row_y,
        row_h,
        x1,
        x0 + 30,
        dashboard.reminder_items[static_cast<std::size_t>(item_index)],
        checked,
        focused_row == i);
  }
}

void draw_family_board(
    std::vector<uint8_t>& image,
    const int x0,
    const int x1,
    const int label_y,
    const int rule_y,
    const int bottom_y,
    const app::DashboardSummary& dashboard) {
  const BitmapFont& label_font = platform::panel_font_assets::kFontJetExtraBold16;
  const BitmapFont& meta_font = platform::panel_font_assets::kFontJetBold13;
  draw_text_with_font_spaced(image, x0, label_y, "FAMILY BOARD", label_font, 3);
  if (!dashboard.family_memo_author.empty()) {
    draw_right_aligned_text_with_font(
        image,
        x1,
        label_y,
        uppercase_copy(dashboard.family_memo_author),
        meta_font);
  }
  draw_section_rule(image, x0, x1, rule_y);

  const int memo_y = rule_y + 14;
  const int memo_width = x1 - x0 - 8;
  if (!dashboard.family_memo_text.empty()) {
    draw_text_wrapped(image, x0, memo_y, memo_width, dashboard.family_memo_text, 2, 5);
  }

  if (!dashboard.family_memo_posted.empty()) {
    draw_right_aligned_text_with_font(
        image,
        x1,
        bottom_y - 18,
        uppercase_copy(dashboard.family_memo_posted),
        meta_font);
  }
}

void draw_voice_lane(
    std::vector<uint8_t>& image,
    const int x0,
    const int y0,
    const int x1) {
  const int lane_h = 29;
  const int icon_size = 16;
  const BitmapFont& font = platform::panel_font_assets::kFontInterMedium13;
  const std::string label = "Hold to talk";
  fill_white_rect(image, x0, y0 - 1, x1, y0 + lane_h + 1);
  const int icon_x = x0 + 2;
  const int icon_y = y0 + ((lane_h - icon_size) / 2) - 1;
  draw_mic_icon(image, icon_x, icon_y);
  const int text_x = icon_x + icon_size + 7;
  const int text_y = centered_text_y_with_font(y0, lane_h, label, font);
  draw_text_with_font(
      image,
      text_x,
      text_y,
      label,
      font);
}

}  // namespace

std::vector<uint8_t> render_home_bitmap(const app::AppState& state) {
  using platform::kPanelBufferSize;
  using platform::kPanelHeight;
  using platform::kPanelWidth;

  std::vector<uint8_t> image(kPanelBufferSize, 0xFF);

  const int margin = 18;
  const int outer_x0 = margin;
  const int outer_y0 = margin;
  const int outer_x1 = kPanelWidth - margin;
  const int outer_y1 = kPanelHeight - margin;
  const int split_x = outer_x0 + ((outer_x1 - outer_x0) * 60) / 100;

  fill_black_rect(image, split_x, outer_y0, split_x + 2, outer_y1);

  const int left_x0 = outer_x0 + 24;
  const int left_x1 = split_x - 24;
  const int right_x0 = split_x + 24;
  const int right_x1 = outer_x1 - 22;
  const int top_y = outer_y0 + 24;

  const ClockSnapshot clock =
      resolve_clock_snapshot(
          state.home.clock_minute_bucket,
          state.onboarding.timezone,
          state.home.clock_is_real);
  const int weather_col_w = 142;
  const int weather_right = left_x1 - 2;
  const int weather_left = weather_right - weather_col_w;
  const HomeLandscapeMetrics metrics = home_landscape_metrics();

  if (state.home.show_focus && state.home.focused_index == 0) {
    const FocusBox box = home_header_focus_box(metrics, HomeFocusKind::Clock);
    if (box.valid) {
      draw_focus_stroke(image, box.x0, box.y0, box.x1, box.y1);
    }
  }
  if (state.home.show_focus && state.home.focused_index == 1) {
    const FocusBox box = home_header_focus_box(metrics, HomeFocusKind::Weather);
    if (box.valid) {
      draw_focus_stroke(image, box.x0, box.y0, box.x1, box.y1);
    }
  }

  const BitmapFont& time_flow_font = platform::panel_font_assets::kFontInterBlack84;
  const BitmapFont& time_display_font_large = platform::panel_font_assets::kFontInterBlack109;
  const BitmapFont& time_display_font_mid = platform::panel_font_assets::kFontInterBlack87;
  const BitmapFont& weekday_font = platform::panel_font_assets::kFontInterSemiBold15;
  const BitmapFont& date_font = platform::panel_font_assets::kFontInterBold18;
  const BitmapFont& city_font = platform::panel_font_assets::kFontInterSemiBold13;
  const BitmapFont& temp_font = platform::panel_font_assets::kFontInterBlack66;
  const BitmapFont& weather_meta_font = platform::panel_font_assets::kFontJetBold15;
  const BitmapFont& family_label_font = platform::panel_font_assets::kFontJetExtraBold16;

  const std::string weekday = uppercase_copy(clock.weekday_label);
  const std::string date = clock.date_label;
  const std::string temp = std::to_string(state.dashboard.weather_temperature_c);
  const std::string weather =
      right_fit_with_font(state.dashboard.weather_condition, weather_meta_font, weather_col_w, 1);
  const std::string humidity = right_fit_with_font(
      "HUM " + std::to_string(state.dashboard.weather_humidity_percent) + "%",
      weather_meta_font,
      weather_col_w,
      1);
  const std::string location = location_label(
      state,
      city_font,
      std::max(60, weather_col_w),
      1);

  const int clock_x = left_x0;
  const int clock_y = top_y - 24;
  const int clock_weather_gap = 14;
  const int clock_budget_w = weather_left - clock_x - clock_weather_gap;
  const BitmapFont* time_display_font = &time_display_font_large;
  if (text_width_with_font(clock.time_label, *time_display_font) > clock_budget_w) {
    time_display_font = &time_display_font_mid;
  }
  if (text_width_with_font(clock.time_label, *time_display_font) > clock_budget_w) {
    time_display_font = &time_flow_font;
  }
  draw_text_with_font(image, clock_x, clock_y, clock.time_label, *time_display_font);

  const TextVerticalBounds time_flow_bounds =
      text_vertical_bounds_with_font(clock.time_label, time_flow_font);
  const int time_flow_bottom =
      top_y + (time_flow_bounds.valid ? time_flow_bounds.bottom : time_flow_font.line_height);
  const int weekday_y = time_flow_bottom + 13;
  int weather_bottom = weekday_y;
  if (clock.valid) {
    draw_text_with_font_spaced(image, left_x0, weekday_y, weekday, weekday_font, 4);
    const int weekday_h = text_height_with_font("Ag", weekday_font);
    const int date_y = weekday_y + weekday_h + 11;
    draw_text_with_font(image, left_x0, date_y, date, date_font);
    weather_bottom = date_y + text_height_with_font(date, date_font);
  } else {
    draw_text_with_font(
        image,
        left_x0,
        weekday_y,
        "--",
        platform::panel_font_assets::kFontJetBold13);
  }

  const int temp_y = top_y - 2;
  draw_right_aligned_text_with_font(image, weather_right, temp_y, temp, temp_font);
  {
    const int temp_x = weather_right - text_width_with_font(temp, temp_font);
    draw_degree_mark(image, temp_x + text_width_with_font(temp, temp_font) + 2, top_y + 8, 6);
  }
  if (!location.empty()) {
    const int city_h = text_height_with_font(location, city_font);
    const int city_y = std::max(outer_y0 + 4, temp_y - city_h - 6);
    draw_right_aligned_text_with_font_spaced(
        image,
        weather_right,
        city_y,
        location,
        city_font,
        1);
    weather_bottom = std::max(weather_bottom, city_y + city_h);
  }

  const int desc_y = temp_y + text_height_with_font(temp, temp_font) + 16 + 5;
  const int desc_h = text_height_with_font(weather, weather_meta_font);
  draw_right_aligned_text_with_font_spaced(
      image,
      weather_right,
      desc_y,
      weather,
      weather_meta_font,
      1);
  const int weather_desc_w = text_width_with_font_spaced(weather, weather_meta_font, 1);
  const int icon_center_x = weather_right - (weather_desc_w / 2);
  const int weather_icon_y = desc_y + desc_h + 10;
  const int weather_icon_size = std::max(12, static_cast<int>(std::lround(34.0 * 1.35)));
  const int weather_icon_x = std::max(
      weather_left,
      std::min(
          weather_right - weather_icon_size,
          icon_center_x - (weather_icon_size / 2)));
  draw_icon(
      image,
      weather_icon_x,
      weather_icon_y,
      state.dashboard.weather_condition,
      weather_icon_size);

  const int humidity_y = weather_icon_y + weather_icon_size + 8;
  draw_right_aligned_text_with_font_spaced(
      image,
      weather_right,
      humidity_y,
      humidity,
      weather_meta_font,
      1);
  weather_bottom = std::max(
      weather_bottom,
      std::max(desc_y + desc_h, humidity_y + text_height_with_font(humidity, weather_meta_font)));

  const int header_rule_y = weather_bottom + 28;
  const int family_label_y = header_rule_y + 8;
  const int family_rule_y = family_label_y + text_height_with_font("Ag", family_label_font) + 8;
  HomeLandscapeMetrics render_metrics = metrics;
  render_metrics.weather_desc_y = desc_y;
  render_metrics.weather_icon_y = weather_icon_y;
  render_metrics.weather_humidity_y = humidity_y;
  render_metrics.weather_bottom = weather_bottom;
  render_metrics.family_rule_y = family_rule_y;

  const int voice_margin = 14;
  const int voice_lane_h = 29;
  const int voice_lane_y = std::max(voice_margin, kPanelHeight - voice_margin - voice_lane_h);
  draw_family_board(
      image,
      left_x0,
      left_x1,
      family_label_y,
      family_rule_y,
      voice_lane_y - 4,
      state.dashboard);
  draw_voice_lane(image, 14, voice_lane_y, 14 + 340);

  draw_inventory_section(image, right_x0, right_x1, render_metrics.inv_y, state);
  draw_reminders_section(image, right_x0, right_x1, state, render_metrics);

  return image;
}

HomeDirtySnapshot capture_home_dirty_snapshot(const app::AppState& state) {
  HomeDirtySnapshot snapshot{};
  snapshot.screen = state.screen;
  snapshot.focused_index = state.home.focused_index;
  snapshot.show_focus = state.home.show_focus;
  snapshot.inventory_count = visible_inventory_count(state.dashboard);
  snapshot.reminder_count = visible_reminder_count(state);
  const int count = std::min(
      snapshot.inventory_count,
      static_cast<int>(snapshot.inventory_completed.size()));
  for (int i = 0; i < count; ++i) {
    snapshot.inventory_completed[static_cast<std::size_t>(i)] =
        i < static_cast<int>(state.dashboard.inventory_completed.size()) &&
        state.dashboard.inventory_completed[static_cast<std::size_t>(i)];
  }

  const std::vector<int> reminder_indices = visible_reminder_indices(state);
  const int reminder_count = std::min(
      snapshot.reminder_count,
      static_cast<int>(snapshot.reminder_completed.size()));
  for (int i = 0; i < reminder_count; ++i) {
    const int item_index = reminder_indices[static_cast<std::size_t>(i)];
    snapshot.reminder_completed[static_cast<std::size_t>(i)] =
        item_index >= 0 &&
        item_index < static_cast<int>(state.dashboard.reminder_completed.size()) &&
        state.dashboard.reminder_completed[static_cast<std::size_t>(item_index)];
  }
  return snapshot;
}

std::vector<platform::DirtyRect> home_dirty_hints(
    const HomeDirtySnapshot& previous,
    const HomeDirtySnapshot& current) {
  if (previous.screen != app::Screen::Home || current.screen != app::Screen::Home) {
    return {};
  }

  std::vector<platform::DirtyRect> rects;

  if (previous.focused_index != current.focused_index ||
      previous.show_focus != current.show_focus) {
    const HomeFocusKind prev_kind = home_focus_kind(previous.focused_index);
    const HomeFocusKind curr_kind = home_focus_kind(current.focused_index);
    const platform::DirtyRect prev_rect =
        home_focus_rect(previous, previous.focused_index, previous.show_focus);
    const platform::DirtyRect curr_rect =
        home_focus_rect(current, current.focused_index, current.show_focus);

    if ((prev_kind == HomeFocusKind::Row && curr_kind == HomeFocusKind::Row) ||
        (prev_kind != HomeFocusKind::Row && curr_kind != HomeFocusKind::Row)) {
      if (is_valid_rect(prev_rect) && is_valid_rect(curr_rect)) {
        rects.push_back(merge_rects(prev_rect, curr_rect));
      } else if (is_valid_rect(prev_rect)) {
        rects.push_back(prev_rect);
      } else if (is_valid_rect(curr_rect)) {
        rects.push_back(curr_rect);
      }
      return rects;
    }

    if (is_valid_rect(prev_rect)) {
      rects.push_back(prev_rect);
    }
    if (is_valid_rect(curr_rect) &&
        (rects.empty() ||
         rects.front().x0 != curr_rect.x0 ||
         rects.front().y0 != curr_rect.y0 ||
         rects.front().x1 != curr_rect.x1 ||
         rects.front().y1 != curr_rect.y1)) {
      rects.push_back(curr_rect);
    }
    return rects;
  }

  if (previous.inventory_completed != current.inventory_completed ||
      previous.reminder_completed != current.reminder_completed) {
    const platform::DirtyRect row_rect =
        home_focus_row_rect(current, current.focused_index);
    if (is_valid_rect(row_rect)) {
      rects.push_back(row_rect);
    }
  }

  return rects;
}

}  // namespace fridge_ink::ui
