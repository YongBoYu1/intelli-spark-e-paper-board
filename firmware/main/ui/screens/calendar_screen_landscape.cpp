#include "ui/screens/calendar_screen.hpp"

#include "platform/panel_config.hpp"
#include "ui/draw.hpp"

#include <algorithm>
#include <array>
#include <cctype>
#include <ctime>
#include <string>
#include <vector>

namespace fridge_ink::ui {

namespace {

struct ParsedMonthLabel {
  std::string month_name;
  int month{3};
  int year{2026};
};

struct AgendaItem {
  const char* time;
  const char* title;
  const char* detail;
};

constexpr std::array<const char*, 12> kMonthNames = {
    "JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE",
    "JULY", "AUGUST", "SEPTEMBER", "OCTOBER", "NOVEMBER", "DECEMBER"};

constexpr std::array<const char*, 7> kWeekdayNames = {
    "SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"};

constexpr std::array<AgendaItem, 3> kAgendaItems = {{
    {"08:30", "PLANNING WINDOW", "Review the selected day and set priorities."},
    {"12:00", "MIDDAY CHECK-IN", "Confirm notes, calls, and follow-ups."},
    {"17:30", "WRAP-UP", "Close the loop and prep the next day."},
}};

std::string to_upper_copy(const std::string& text) {
  std::string out;
  out.reserve(text.size());
  for (const char ch : text) {
    out.push_back(static_cast<char>(std::toupper(static_cast<unsigned char>(ch))));
  }
  return out;
}

std::string normalize_token(const std::string& token) {
  std::string out;
  out.reserve(token.size());
  for (const char ch : token) {
    const unsigned char c = static_cast<unsigned char>(ch);
    if (std::isalpha(c)) {
      out.push_back(static_cast<char>(std::toupper(c)));
    } else if (std::isdigit(c)) {
      out.push_back(static_cast<char>(c));
    }
  }
  return out;
}

int parse_positive_int(const std::string& token, const int fallback) {
  if (token.empty()) {
    return fallback;
  }
  int value = 0;
  for (const char ch : token) {
    const unsigned char c = static_cast<unsigned char>(ch);
    if (!std::isdigit(c)) {
      return fallback;
    }
    value = (value * 10) + (ch - '0');
  }
  return value;
}

int month_from_token(const std::string& token) {
  const std::string normalized = normalize_token(token);
  for (std::size_t i = 0; i < kMonthNames.size(); ++i) {
    const std::string full = kMonthNames[i];
    const std::string short_name = full.substr(0, 3);
    if (normalized == full || normalized == short_name) {
      return static_cast<int>(i) + 1;
    }
  }
  return 0;
}

std::vector<std::string> split_words(const std::string& text) {
  std::vector<std::string> words;
  std::string current;
  for (const char ch : text) {
    const unsigned char c = static_cast<unsigned char>(ch);
    if (std::isspace(c)) {
      if (!current.empty()) {
        words.push_back(current);
        current.clear();
      }
      continue;
    }
    current.push_back(ch);
  }
  if (!current.empty()) {
    words.push_back(current);
  }
  return words;
}

ParsedMonthLabel parse_month_label(const std::string& label) {
  ParsedMonthLabel parsed;
  const std::string trimmed = trim_copy(label);
  if (trimmed.empty()) {
    return parsed;
  }

  const std::vector<std::string> words = split_words(trimmed);
  if (!words.empty()) {
    const int month = month_from_token(words[0]);
    if (month > 0) {
      parsed.month = month;
      parsed.month_name = kMonthNames[static_cast<std::size_t>(month - 1)];
    } else {
      parsed.month_name = to_upper_copy(words[0]);
    }
  }
  if (words.size() >= 2) {
    parsed.year = parse_positive_int(words[1], parsed.year);
  }

  return parsed;
}

bool is_leap_year(const int year) {
  return ((year % 4) == 0 && (year % 100) != 0) || ((year % 400) == 0);
}

int days_in_month(const int year, const int month) {
  static constexpr std::array<int, 12> kDays = {
      31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31};
  if (month == 2 && is_leap_year(year)) {
    return 29;
  }
  return kDays[static_cast<std::size_t>(std::clamp(month, 1, 12) - 1)];
}

int weekday_index(const int year, const int month, const int day) {
  std::tm tm{};
  tm.tm_year = year - 1900;
  tm.tm_mon = month - 1;
  tm.tm_mday = day;
  tm.tm_isdst = -1;
  if (std::mktime(&tm) == static_cast<std::time_t>(-1)) {
    return 0;
  }
  return tm.tm_wday;
}

const char* weekday_name(const int index) {
  const int clamped = std::clamp(index, 0, 6);
  return kWeekdayNames[static_cast<std::size_t>(clamped)];
}

void draw_chip(std::vector<uint8_t>& image,
               const int x0, const int y0, const int x1, const int y1,
               const std::string& text) {
  fill_black_rect(image, x0, y0, x1, y1);
  draw_text_centered_inverted(image, x0 + 2, x1 - 2, y0 + 10, text, 1, 32);
}

void draw_month_grid(
    std::vector<uint8_t>& image,
    const int x0, const int y0, const int x1, const int y1,
    const int year, const int month, const int selected_day) {
  const int start_offset = weekday_index(year, month, 1);
  const int month_days = days_in_month(year, month);
  const int grid_w = x1 - x0;
  const int grid_h = y1 - y0;
  const int cell_w = std::max(34, grid_w / 7);
  const int cell_h = std::max(34, grid_h / 6);
  const int grid_draw_w = cell_w * 7;
  const int grid_draw_h = cell_h * 6;
  const int grid_x = x0 + ((grid_w - grid_draw_w) / 2);
  const int grid_y = y0 + ((grid_h - grid_draw_h) / 2);
  const int number_scale = cell_h >= 40 ? 2 : 1;

  for (int i = 0; i < 7; ++i) {
    draw_text_centered(image,
        grid_x + (i * cell_w), grid_x + ((i + 1) * cell_w),
        y0 - 22,
        kWeekdayNames[static_cast<std::size_t>(i)],
        1, 3);
  }

  for (int day = 1; day <= month_days; ++day) {
    const int index = start_offset + (day - 1);
    const int row = index / 7;
    const int col = index % 7;
    const int cx0 = grid_x + (col * cell_w);
    const int cy0 = grid_y + (row * cell_h);
    const int cx1 = cx0 + cell_w - 4;
    const int cy1 = cy0 + cell_h - 4;
    const bool is_selected = day == selected_day;

    draw_outline_rect(image, cx0, cy0, cx1, cy1, 1);
    if (is_selected) {
      fill_black_rect(image, cx0 + 1, cy0 + 1, cx1 - 1, cy1 - 1);
      draw_text_centered_inverted(
          image, cx0, cx1, cy0 + ((cy1 - cy0) / 2) - 8,
          std::to_string(day), number_scale, 2);
    } else {
      draw_text_centered(
          image, cx0, cx1, cy0 + ((cy1 - cy0) / 2) - 8,
          std::to_string(day), number_scale, 2);
    }
  }
}

void draw_agenda_card(
    std::vector<uint8_t>& image,
    const int x0, const int y0, const int x1, const int y1,
    const AgendaItem& item,
    const bool selected) {
  draw_outline_rect(image, x0, y0, x1, y1, 1);
  if (selected) {
    fill_black_rect(image, x0 + 1, y0 + 1, x1 - 1, y1 - 1);
  }

  const int text_x = x0 + 12;
  const int text_w = x1 - text_x - 14;
  const std::string time_text = truncate_text_px(item.time, 1, std::max(32, text_w / 3));
  const std::string title_text = truncate_text_px(item.title, 2, std::max(64, text_w - 48));
  const std::string detail_text = truncate_text_px(item.detail, 1, std::max(48, text_w));

  const int time_w = text_width_px(time_text, 1);
  const int title_y = y0 + 14;
  const int detail_y = y0 + 44;
  if (selected) {
    draw_text_line_inverted(image, text_x, title_y, title_text, 2, 24);
    draw_text_line_inverted(image, x1 - 12 - time_w, y0 + 12, time_text, 1, 8);
    draw_text_wrapped_inverted(image, text_x, detail_y, text_w, detail_text, 1, 2);
  } else {
    draw_text_line(image, text_x, title_y, title_text, 2, 24);
    draw_text_line(image, x1 - 12 - time_w, y0 + 12, time_text, 1, 8);
    draw_text_wrapped(image, text_x, detail_y, text_w, detail_text, 1, 2);
  }
}

}  // namespace

std::vector<uint8_t> render_calendar_landscape_bitmap(const app::AppState& state) {
  using platform::kPanelBufferSize;
  using platform::kPanelHeight;
  using platform::kPanelWidth;

  const ParsedMonthLabel month = parse_month_label(state.calendar.month_label);
  const int selected_day = std::clamp(
      state.calendar.day_of_month, 1, days_in_month(month.year, month.month));
  const int selected_weekday = weekday_index(month.year, month.month, selected_day);
  const std::string month_header = month.month_name.empty() ? "CALENDAR" : month.month_name;
  const std::string year_text = std::to_string(month.year);
  const std::string selected_label = std::string("DAY ") + std::to_string(selected_day);
  const std::string weekday_text = weekday_name(selected_weekday);
  const std::string month_line = to_upper_copy(state.calendar.month_label);

  std::vector<uint8_t> image(kPanelBufferSize, 0xFF);
  draw_outline_rect(image, 12, 12, kPanelWidth - 12, kPanelHeight - 12, 3);

  const int content_x0 = 24;
  const int content_x1 = kPanelWidth - 24;
  const int content_y0 = 24;
  const int content_y1 = kPanelHeight - 24;
  const int split_x = content_x0 + std::clamp((content_x1 - content_x0) * 44 / 100, 316, 356);

  draw_outline_rect(image, split_x, content_y0, split_x + 2, content_y1, 1);

  const int left_x0 = content_x0;
  const int left_x1 = split_x - 12;
  draw_text_line(image, left_x0, 36, month_header, 3, 16);
  draw_text_line(image, left_x0 + 2, 78, year_text, 1, 8);
  draw_text_line(image, left_x0 + 2, 100, "MONTH VIEW", 1, 16);

  const int left_grid_top = 138;
  const int left_grid_bottom = kPanelHeight - 74;
  draw_month_grid(image, left_x0, left_grid_top, left_x1, left_grid_bottom,
      month.year, month.month, selected_day);

  const int left_chip_w = std::max(88, text_width_px(selected_label, 1) + 20);
  draw_chip(
      image,
      left_x0,
      kPanelHeight - 60,
      left_x0 + left_chip_w,
      kPanelHeight - 36,
      selected_label);

  const int right_x0 = split_x + 18;
  const int right_x1 = content_x1;
  const int right_w = right_x1 - right_x0;

  draw_text_line(image, right_x0, 36, "AGENDA", 3, 12);
  draw_text_line(image, right_x0, 78, weekday_text, 1, 8);
  draw_text_line(image, right_x0, 102, month_line, 1, 24);

  const int chip_w = std::max(92, text_width_px(selected_label, 1) + 18);
  draw_chip(
      image,
      right_x1 - chip_w,
      34,
      right_x1,
      58,
      selected_label);

  fill_black_rect(image, right_x0, 118, right_x1, 120);

  const int card_top = 136;
  const int card_gap = 10;
  const int footer_y = kPanelHeight - 34;
  const int card_bottom = footer_y - 8;
  const int available_h = card_bottom - card_top;
  const int card_h = std::max(84, (available_h - (card_gap * 2)) / 3);
  int card_y = card_top;
  for (std::size_t i = 0; i < kAgendaItems.size(); ++i) {
    const bool selected = i == 0;
    draw_agenda_card(image, right_x0, card_y, right_x1, card_y + card_h, kAgendaItems[i], selected);
    card_y += card_h + card_gap;
  }

  std::string footer = "ROTATE=DATE  |  CLICK=AGENDA  |  HOLD=HOME";
  footer = truncate_text_px(footer, 1, std::max(80, right_w));
  draw_text_centered(image, content_x0, content_x1, kPanelHeight - 18, footer, 1, 64);

  return image;
}

}  // namespace fridge_ink::ui
