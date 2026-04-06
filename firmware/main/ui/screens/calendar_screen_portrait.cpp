#include "ui/screens/calendar_screen.hpp"

#include "platform/panel_config.hpp"
#include "ui/draw.hpp"
#include "ui/primitives.hpp"

#include <algorithm>
#include <array>
#include <cctype>
#include <sstream>
#include <string>
#include <vector>

namespace fridge_ink::ui {
namespace {

using platform::kPanelBufferSize;
using platform::kPanelHeight;
using platform::kPanelWidth;

struct ParsedMonthLabel {
  int month{3};
  int year{2026};
  bool valid{false};
};

std::string uppercase_copy(std::string value) {
  for (char& ch : value) {
    ch = static_cast<char>(std::toupper(static_cast<unsigned char>(ch)));
  }
  return value;
}

std::string lowercase_copy(std::string value) {
  for (char& ch : value) {
    ch = static_cast<char>(std::tolower(static_cast<unsigned char>(ch)));
  }
  return value;
}

int month_from_name(const std::string& month_name) {
  static const std::array<const char*, 12> kMonths = {
      "january", "february", "march", "april", "may", "june",
      "july", "august", "september", "october", "november", "december"};
  const std::string lowered = lowercase_copy(month_name);
  for (int i = 0; i < static_cast<int>(kMonths.size()); ++i) {
    if (lowered == kMonths[static_cast<std::size_t>(i)]) {
      return i + 1;
    }
  }
  return 0;
}

ParsedMonthLabel parse_month_label(const std::string& label) {
  ParsedMonthLabel parsed;
  std::istringstream iss(label);
  std::string month_name;
  int year = 0;
  if (!(iss >> month_name >> year)) {
    return parsed;
  }
  const int month = month_from_name(month_name);
  if (month < 1 || month > 12) {
    return parsed;
  }
  parsed.month = month;
  parsed.year = year;
  parsed.valid = true;
  return parsed;
}

int days_in_month(const int year, const int month) {
  static const std::array<int, 12> kDays = {
      31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31};
  if (month == 2) {
    const bool leap = (year % 4 == 0 && year % 100 != 0) || (year % 400 == 0);
    return leap ? 29 : 28;
  }
  return kDays[static_cast<std::size_t>(month - 1)];
}

int weekday_sunday0(const int year, const int month, const int day) {
  // Sakamoto's algorithm, returning Sunday=0 for the month grid.
  static const std::array<int, 12> kOffsets = {
      0, 3, 2, 5, 0, 3, 5, 1, 4, 6, 2, 4};
  int y = year;
  if (month < 3) {
    --y;
  }
  return (y + y / 4 - y / 100 + y / 400 + kOffsets[static_cast<std::size_t>(month - 1)] +
          day) %
         7;
}

std::string month_name_upper(const int month) {
  static const std::array<const char*, 12> kMonths = {
      "JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE",
      "JULY", "AUGUST", "SEPTEMBER", "OCTOBER", "NOVEMBER", "DECEMBER"};
  if (month < 1 || month > 12) {
    return "MONTH";
  }
  return kMonths[static_cast<std::size_t>(month - 1)];
}

std::string weekday_name_upper(const int weekday) {
  static const std::array<const char*, 7> kWeekdays = {
      "SUNDAY", "MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY"};
  if (weekday < 0 || weekday >= static_cast<int>(kWeekdays.size())) {
    return "DAY";
  }
  return kWeekdays[static_cast<std::size_t>(weekday)];
}

std::string short_weekday_upper(const int weekday) {
  static const std::array<const char*, 7> kWeekdays = {
      "SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"};
  if (weekday < 0 || weekday >= static_cast<int>(kWeekdays.size())) {
    return "DAY";
  }
  return kWeekdays[static_cast<std::size_t>(weekday)];
}

int clamp_day(const int day, const int max_day) {
  return std::max(1, std::min(max_day, day));
}

}  // namespace

std::vector<uint8_t> render_calendar_portrait_bitmap(const app::AppState& state) {
  std::vector<uint8_t> image(kPanelBufferSize, 0xFF);

  const int split_y = std::max(260, std::min(kPanelHeight - 220, kPanelHeight / 2));
  const int outer_pad = 12;
  draw_outline_rect(image, outer_pad, outer_pad, kPanelWidth - outer_pad, kPanelHeight - outer_pad, 2);
  fill_black_rect(image, outer_pad, split_y, kPanelWidth - outer_pad, split_y + 2);

  const ParsedMonthLabel parsed = parse_month_label(state.calendar.month_label);
  const int month = parsed.valid ? parsed.month : 3;
  const int year = parsed.valid ? parsed.year : 2026;
  const int max_day = days_in_month(year, month);
  const int selected_day = clamp_day(state.calendar.day_of_month, max_day);
  const int selected_weekday = weekday_sunday0(year, month, selected_day);

  const std::string top_month = month_name_upper(month);
  const std::string top_year = std::to_string(year);
  const std::string date_title = top_month + " " + std::to_string(selected_day);
  const std::string weekday = weekday_name_upper(selected_weekday);

  const int top_left = 20;
  draw_text_line(image, top_left, 20, truncate_text_px(top_month, 3, 320), 3, 18);
  draw_text_line(image, top_left + 2, 62, top_year, 2, 8);

  const int grid_left = 20;
  const int grid_right = kPanelWidth - 20;
  const int week_row_y = 100;
  const int grid_top = 124;
  const int grid_bottom = split_y - 14;
  const int cell_w = std::max(24, (grid_right - grid_left) / 7);
  const int cell_h = std::max(18, (grid_bottom - grid_top) / 6);
  const int start_offset = weekday_sunday0(year, month, 1);
  const int day_font_scale = 1;
  const std::array<std::string, 7> week_labels = {
      short_weekday_upper(0), short_weekday_upper(1), short_weekday_upper(2),
      short_weekday_upper(3), short_weekday_upper(4), short_weekday_upper(5),
      short_weekday_upper(6)};

  for (int i = 0; i < 7; ++i) {
    const int cell_x0 = grid_left + i * cell_w;
    const int cell_x1 = cell_x0 + cell_w - 4;
    draw_text_centered(image, cell_x0, cell_x1, week_row_y, week_labels[static_cast<std::size_t>(i)], 1, 3);
  }

  for (int day = 1; day <= max_day; ++day) {
    const int idx = start_offset + (day - 1);
    const int row = idx / 7;
    const int col = idx % 7;
    const int cell_x0 = grid_left + col * cell_w;
    const int cell_y0 = grid_top + row * cell_h;
    const int cell_x1 = cell_x0 + cell_w - 4;
    const int cell_y1 = cell_y0 + cell_h - 4;
    const bool is_selected = (day == selected_day);

    draw_outline_rect(image, cell_x0, cell_y0, cell_x1, cell_y1, 1);
    if (is_selected) {
      fill_black_rect(image, cell_x0 + 1, cell_y0 + 1, cell_x1 - 1, cell_y1 - 1);
    }

    const std::string day_label = std::to_string(day);
    const int text_y = cell_y0 + ((cell_y1 - cell_y0) / 2) - 1;
    if (is_selected) {
      draw_text_centered_inverted(
          image, cell_x0, cell_x1, text_y, day_label, day_font_scale, 2);
    } else {
      draw_text_centered(image, cell_x0, cell_x1, text_y, day_label, day_font_scale, 2);
    }
  }

  const std::vector<std::string>& reminders = state.dashboard.reminder_items;
  const std::vector<bool>& completed = state.dashboard.reminder_completed;
  int open_count = 0;
  for (std::size_t i = 0; i < reminders.size(); ++i) {
    const bool checked = i < completed.size() && completed[i];
    if (!checked) {
      ++open_count;
    }
  }

  const int header_y = split_y + 12;
  draw_text_line(image, 20, header_y, weekday, 2, 12);
  draw_text_line(image, 20, header_y + 24, truncate_text_px(date_title, 3, 340), 3, 18);

  const std::string count_label =
      open_count > 0 ? (std::to_string(open_count) + " OPEN") : "ALL DONE";
  const int count_width = text_width_px(count_label, 1);
  draw_text_line(image, kPanelWidth - 20 - count_width, header_y + 4, count_label, 1, 24);
  fill_black_rect(image, 20, header_y + 54, kPanelWidth - 20, header_y + 56);

  const int list_x0 = 18;
  const int list_x1 = kPanelWidth - 18;
  const int list_top = header_y + 64;
  const int list_bottom = kPanelHeight - 36;
  const int row_h = 40;
  const int row_gap = 6;
  const int slots = std::max(1, (list_bottom - list_top + row_gap) / (row_h + row_gap));

  if (reminders.empty()) {
    const int empty_top = list_top + ((list_bottom - list_top) / 2) - 20;
    draw_text_centered(image, list_x0, list_x1, empty_top, "NO REMINDERS", 2, 20);
    draw_text_centered(
        image,
        list_x0,
        list_x1,
        empty_top + 22,
        "VOICE CAN ADD REMINDERS AND MEMOS",
        1,
        40);
  } else {
    int y = list_top;
    const int visible_count = std::min(slots, static_cast<int>(reminders.size()));
    for (int i = 0; i < visible_count; ++i) {
      const bool checked =
          static_cast<std::size_t>(i) < completed.size() && completed[static_cast<std::size_t>(i)];
      draw_outline_rect(image, list_x0, y, list_x1, y + row_h, 1);
      draw_checkbox(image, list_x0 + 10, y + 13, checked, false, 14);

      const int text_x = list_x0 + 38;
      const int text_y = y + 12;
      const int text_width = std::max(0, list_x1 - text_x - 10);
      const std::string clipped =
          truncate_text_px(reminders[static_cast<std::size_t>(i)], 2, text_width);
      draw_text_line(image, text_x, text_y, clipped, 2, static_cast<int>(clipped.size()));

      y += row_h + row_gap;
    }

    if (reminders.size() > static_cast<std::size_t>(visible_count)) {
      const int hidden = static_cast<int>(reminders.size()) - visible_count;
      const std::string more = "+" + std::to_string(hidden) + " MORE";
      const int more_width = text_width_px(more, 1);
      draw_text_line(image, list_x1 - more_width - 2, list_bottom - 12, more, 1, 12);
    }
  }

  std::string footer = "ROTATE=DATE  |  CLICK=AGENDA  |  HOLD=HOME";
  footer = truncate_text_px(uppercase_copy(footer), 1, kPanelWidth - 24);
  draw_text_line(image, 12, kPanelHeight - 20, footer, 1, 64);

  return image;
}

}  // namespace fridge_ink::ui
