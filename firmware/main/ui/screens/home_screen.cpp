#include "ui/screens/home_screen.hpp"

#include "platform/panel_config.hpp"
#include "ui/draw.hpp"
#include "ui/panel_font_assets_generated.hpp"

#include <algorithm>
#include <cmath>
#include <ctime>
#include <iomanip>
#include <sstream>
#include <string>
#include <vector>

namespace fridge_ink::ui {
namespace {

using platform::panel_font_assets::BitmapFont;
using platform::panel_font_assets::Glyph;

constexpr int kInventorySectionYOffset = 4;
constexpr int kReminderSectionYOffset = 204;
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

constexpr const char* kCloudMask32[] = {
    "................................",
    "................................",
    "................................",
    "...................#####........",
    ".................#########......",
    "........######.####.....####....",
    "......###########.........###...",
    ".....###......#............##...",
    "....##......................##..",
    "...##.......................##..",
    "...##........................##.",
    "..##.........................##.",
    "..##.........................##.",
    "..##.........................##.",
    "..##.........................##.",
    "..##.........................#..",
    "..###.......................###.",
    ".##..........................###",
    ".##...........................##",
    "##.............................#",
    "##.............................#",
    "##.............................#",
    "##.............................#",
    "##.............................#",
    ".##...........................##",
    ".##..........................###",
    "..###....#............#.....###.",
    "...#########........##########..",
    ".....####.####....####.#####....",
    "............########............",
    ".............######.............",
    "................................",
};

constexpr const char* kSunMask32[] = {
    "..............##................",
    "..............##................",
    "..............##................",
    "....#.........##................",
    "...###........##..........#.....",
    "....###.......##.........###....",
    ".....###................###.....",
    "......###..............###......",
    ".......#.....######...###.......",
    "............########...#........",
    "..........####....####..........",
    "..........##........##..........",
    ".........##..........##.........",
    "........###..........###........",
    "........##............##........",
    "######..##............##........",
    "######..##............##..######",
    "........##............##..######",
    "........###..........###........",
    ".........##..........##.........",
    "..........##........##..........",
    "..........####....####..........",
    "........#...########............",
    ".......###...######.....#.......",
    "......###..............###......",
    ".....###................###.....",
    "....###.........##.......###....",
    ".....#..........##........###...",
    "................##.........#....",
    "................##..............",
    "................##..............",
    "................##..............",
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
  int weather_left{0};
  int weather_right{0};
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
int visible_reminder_count(const app::DashboardSummary& dashboard);

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

  const int weather_top = metrics.top_y - 2;
  const int city_h = approx_font_height(13, 0.84, 10);
  const int temp_h = approx_font_height(66, 0.78, 46);
  const int desc_h = approx_font_height(15, 0.86, 12);
  const int hum_h = approx_font_height(15, 0.86, 12);
  const int icon_size = std::max(12, static_cast<int>(std::lround(34.0 * 1.35)));
  const int city_y = std::max(metrics.oy0 + 4, weather_top - city_h - 6);
  const int desc_y = weather_top + temp_h + 21;
  const int icon_y = desc_y + desc_h + 10;
  const int humidity_bottom = icon_y + icon_size + 8 + hum_h;
  const int clock_bottom = metrics.top_y + approx_font_height(70, 0.78, 54) + 13 +
                           approx_font_height(15, 0.86, 12) + 11 +
                           approx_font_height(18, 0.86, 14);
  const int weather_bottom = std::max(
      std::max(clock_bottom, city_y + city_h),
      std::max(desc_y + desc_h, humidity_bottom));

  const int header_rule_y = weather_bottom + 28;
  const int micro_h = approx_font_height(16, 0.78, 12);
  metrics.family_rule_y = header_rule_y + 8 + micro_h + 8;
  metrics.inv_y = metrics.top_y + kInventorySectionYOffset;
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
  (void)inventory_rows;
  return metrics.top_y + kReminderSectionYOffset + kSectionRowStartOffset;
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
      std::max(metrics.ox0 + 24 - metrics.header_focus_pad_x + 16, metrics.weather_left - 7),
      std::min(metrics.oy1, metrics.top_y + 142),
      true,
    };
  }
  if (kind == HomeFocusKind::Weather) {
    return {
        metrics.weather_left - metrics.header_focus_pad_x,
        std::max(metrics.oy0 + 2, metrics.top_y - 6),
        metrics.weather_right + metrics.header_focus_pad_x,
        std::min(metrics.oy1, metrics.top_y + 136),
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

ClockSnapshot resolve_clock_snapshot(const std::uint64_t minute_bucket) {
  ClockSnapshot snapshot;
  if (minute_bucket == 0) {
    return snapshot;
  }
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
  std::ostringstream date_out;
  date_out << std::put_time(&local_tm, "%B %d, %Y");

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

void draw_mask_icon_32(
    std::vector<uint8_t>& image,
    const int x,
    const int y,
    const char* const rows[32]) {
  for (int yy = 0; yy < 32; ++yy) {
    for (int xx = 0; xx < 32; ++xx) {
      if (rows[yy][xx] != '#') {
        continue;
      }
      set_black_pixel(image, x + xx, y + yy);
    }
  }
}

std::string right_fit(const std::string& value, const int scale, const int width_px) {
  return truncate_text_px(uppercase_copy(value), scale, width_px);
}

std::string location_label(const app::AppState& state, const int width_px) {
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
  return truncate_text_px(uppercase_copy(location), 1, width_px);
}

void draw_right_aligned_line(
    std::vector<uint8_t>& image,
    const int right_x,
    const int baseline_y,
    const std::string& text,
    const int scale) {
  const int width = text_width_px(text, scale);
  draw_text_line(image, right_x - width, baseline_y, text, scale, 0);
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

void draw_weather_icon(
    std::vector<uint8_t>& image,
    const int x0,
    const int y0,
    const std::string& weather_condition) {
  const std::string lower = trim_copy(weather_condition);
  if (lower.find("sun") != std::string::npos || lower.find("clear") != std::string::npos) {
    draw_mask_icon_32(image, x0, y0, kSunMask32);
    return;
  }
  draw_mask_icon_32(image, x0, y0, kCloudMask32);
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

int visible_reminder_count(const app::DashboardSummary& dashboard) {
  return std::min(static_cast<int>(dashboard.reminder_items.size()), kReminderVisibleMax);
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
  return (index >= 0 && index < visible_reminder_count(state.dashboard)) ? index : -1;
}

void draw_inventory_section(
    std::vector<uint8_t>& image,
    const int x0,
    const int x1,
    const int title_y,
    const app::AppState& state) {
  const app::DashboardSummary& dashboard = state.dashboard;
  draw_text_line(image, x0, title_y, "INVENTORY", 1, 0);
  const int count = visible_inventory_count(dashboard);
  if (count > 0) {
    draw_right_aligned_line(image, x1, title_y, std::to_string(count), 1);
  }
  draw_section_rule(image, x0, x1, title_y + 18);

  const int row_h = 40;
  const int item_text_x = x0;
  const int badge_right_x = x1;
  const int focused_row = home_focus_inventory_index(state);
  const HomeDirtySnapshot snapshot = capture_home_dirty_snapshot(state);
  for (int i = 0; i < count; ++i) {
    const int row_y = title_y + 34 + i * row_h;
    if (focused_row == i) {
      const FocusBox box = home_focus_row_box(snapshot, state.home.focused_index);
      if (box.valid) {
        draw_focus_stroke(image, box.x0, box.y0, box.x1, box.y1);
      }
    }
    const std::string title =
        truncate_text_px(dashboard.inventory_items[i], 2, x1 - x0 - 112);
    const BitmapFont& item_font =
        focused_row == i
            ? platform::panel_font_assets::kFontInterBold17
            : platform::panel_font_assets::kFontInterMedium18;
    draw_text_with_font(
        image,
        item_text_x,
        centered_sample_y_with_font(row_y, row_h, item_font),
        title,
        item_font);

    std::string badge = "STOCKED";
    const bool completed =
        i < static_cast<int>(dashboard.inventory_completed.size()) &&
        dashboard.inventory_completed[static_cast<std::size_t>(i)];
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
  const int cb_x0 = x0;
  const int cb_y0 = row_y + ((row_h - 16) / 2);
  const int cb_x1 = cb_x0 + 16;
  const int cb_y1 = cb_y0 + 16;
  if (focused) {
    draw_right_panel_focus_row(image, x0, row_right_x, row_y, row_h);
  }
  draw_rounded_rect_stroke(image, cb_x0, cb_y0, cb_x1, cb_y1, 3, 2);
  if (checked) {
    fill_black_rect(image, cb_x0 + 3, cb_y0 + 8, cb_x0 + 6, cb_y0 + 11);
    fill_black_rect(image, cb_x0 + 5, cb_y0 + 10, cb_x0 + 12, cb_y0 + 13);
  }
  const BitmapFont& text_font =
      focused ? platform::panel_font_assets::kFontInterBold17
              : platform::panel_font_assets::kFontInterMedium18;
  draw_text_with_font(
      image,
      text_x,
      centered_sample_y_with_font(row_y, row_h, text_font),
      truncate_text_px(text, 2, 236),
      text_font);
}

void draw_reminders_section(
    std::vector<uint8_t>& image,
    const int x0,
    const int x1,
    const int title_y,
    const app::AppState& state) {
  const app::DashboardSummary& dashboard = state.dashboard;
  draw_text_line(image, x0, title_y, "REMINDERS", 1, 0);
  const int count = visible_reminder_count(dashboard);
  if (count > 0) {
    draw_right_aligned_line(image, x1, title_y, std::to_string(count), 1);
  }
  draw_section_rule(image, x0, x1, title_y + 18);

  const int row_h = 40;
  const int focused_row = home_focus_reminder_index(state);
  const HomeDirtySnapshot snapshot = capture_home_dirty_snapshot(state);
  for (int i = 0; i < count; ++i) {
    const int row_y = title_y + 34 + i * row_h;
    const bool checked =
        i < static_cast<int>(dashboard.reminder_completed.size()) &&
        dashboard.reminder_completed[i];
    if (focused_row == i) {
      const FocusBox box = home_focus_row_box(snapshot, state.home.focused_index);
      if (box.valid) {
        draw_focus_stroke(image, box.x0, box.y0, box.x1, box.y1);
      }
    }
    draw_checkbox_row(
        image,
        x0 + 2,
        row_y,
        row_h,
        x1,
        x0 + 28,
        dashboard.reminder_items[i],
        checked,
        false);
  }
}

void draw_family_board(
    std::vector<uint8_t>& image,
    const int x0,
    const int x1,
    const int top_y,
    const int bottom_y,
    const app::DashboardSummary& dashboard) {
  draw_text_line(image, x0, top_y, "FAMILY BOARD", 1, 0);
  if (!dashboard.family_memo_author.empty()) {
    draw_right_aligned_line(image, x1, top_y, uppercase_copy(dashboard.family_memo_author), 1);
  }
  draw_section_rule(image, x0, x1, top_y + 18);

  const int memo_y = top_y + 34;
  const int memo_width = x1 - x0 - 8;
  if (!dashboard.family_memo_text.empty()) {
    draw_text_wrapped(image, x0, memo_y, memo_width, dashboard.family_memo_text, 2, 5);
  }

  if (!dashboard.family_memo_posted.empty()) {
    draw_right_aligned_line(
        image,
        x1,
        bottom_y - 18,
        uppercase_copy(dashboard.family_memo_posted),
        1);
  }
}

void draw_voice_lane(
    std::vector<uint8_t>& image,
    const int x0,
    const int y0,
    const int x1) {
  const int lane_h = 29;
  fill_white_rect(image, x0, y0 - 1, x1, y0 + lane_h + 1);
  draw_mic_icon(image, x0 + 2, y0 + 6);
  draw_text_with_font(
      image,
      x0 + 26,
      y0 + 8,
      "READY",
      platform::panel_font_assets::kFontJetBold13);
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

  const ClockSnapshot clock = resolve_clock_snapshot(state.home.clock_minute_bucket);
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

  const std::string weekday = uppercase_copy(clock.weekday_label);
  const std::string date = uppercase_copy(clock.date_label);
  const std::string location = location_label(state, weather_col_w);
  const std::string temp = std::to_string(state.dashboard.weather_temperature_c) + "C";
  const std::string weather = right_fit(state.dashboard.weather_condition, 1, weather_col_w);
  const std::string humidity =
      "HUM " + std::to_string(state.dashboard.weather_humidity_percent) + "%";

  draw_text_with_font(
      image,
      left_x0,
      top_y - 2,
      clock.time_label,
      platform::panel_font_assets::kFontInterBlack36);
  if (clock.valid) {
    draw_text_with_font(
        image,
        left_x0,
        top_y + 60,
        weekday,
        platform::panel_font_assets::kFontJetBold13);
    draw_text_with_font(
        image,
        left_x0,
        top_y + 86,
        date,
        platform::panel_font_assets::kFontInterBold17);
  } else {
    draw_text_with_font(
        image,
        left_x0,
        top_y + 60,
        "--",
        platform::panel_font_assets::kFontJetBold13);
  }

  if (!location.empty()) {
    draw_right_aligned_text_with_font(
        image,
        weather_right,
        top_y + 8,
        uppercase_copy(location),
        platform::panel_font_assets::kFontJetBold13);
  }
  draw_right_aligned_text_with_font(
      image,
      weather_right,
      top_y + 28,
      temp,
      platform::panel_font_assets::kFontInterBlack29);
  draw_weather_icon(image, weather_left + 46, top_y + 58, state.dashboard.weather_condition);
  draw_right_aligned_text_with_font(
      image,
      weather_right,
      top_y + 92,
      uppercase_copy(weather),
      platform::panel_font_assets::kFontJetBold13);
  draw_right_aligned_text_with_font(
      image,
      weather_right,
      top_y + 118,
      uppercase_copy(humidity),
      platform::panel_font_assets::kFontJetBold13);

  const int family_title_y = top_y + 164;
  const int voice_lane_y = outer_y1 - 42;
  draw_family_board(
      image,
      left_x0,
      left_x1,
      family_title_y,
      voice_lane_y - 4,
      state.dashboard);
  draw_voice_lane(image, outer_x0 + 14, voice_lane_y, outer_x0 + 14 + 332);

  draw_inventory_section(image, right_x0, right_x1, top_y + kInventorySectionYOffset, state);
  draw_reminders_section(image, right_x0, right_x1, top_y + kReminderSectionYOffset, state);

  return image;
}

HomeDirtySnapshot capture_home_dirty_snapshot(const app::AppState& state) {
  HomeDirtySnapshot snapshot{};
  snapshot.screen = state.screen;
  snapshot.focused_index = state.home.focused_index;
  snapshot.show_focus = state.home.show_focus;
  snapshot.inventory_count = visible_inventory_count(state.dashboard);
  snapshot.reminder_count = visible_reminder_count(state.dashboard);
  const int count = std::min(
      snapshot.inventory_count,
      static_cast<int>(snapshot.inventory_completed.size()));
  for (int i = 0; i < count; ++i) {
    snapshot.inventory_completed[static_cast<std::size_t>(i)] =
        i < static_cast<int>(state.dashboard.inventory_completed.size()) &&
        state.dashboard.inventory_completed[static_cast<std::size_t>(i)];
  }

  const int reminder_count = std::min(
      snapshot.reminder_count,
      static_cast<int>(snapshot.reminder_completed.size()));
  for (int i = 0; i < reminder_count; ++i) {
    snapshot.reminder_completed[static_cast<std::size_t>(i)] =
        i < static_cast<int>(state.dashboard.reminder_completed.size()) &&
        state.dashboard.reminder_completed[static_cast<std::size_t>(i)];
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
