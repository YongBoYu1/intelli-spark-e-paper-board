#include "ui/screens/calendar_screen.hpp"

#include "app/calendar_runtime.hpp"
#include "platform/panel_config.hpp"
#include "ui/draw.hpp"
#include "ui/strings.hpp"

#include <algorithm>
#include <array>
#include <cctype>
#include <string>
#include <vector>

namespace fridge_ink::ui {
namespace {

struct AgendaRow {
  bool reminder{false};
  bool completed{false};
  int reminder_index{-1};
  std::string when{};
  std::string title{};
};

std::string upper_copy(const std::string& text) {
  std::string out;
  out.reserve(text.size());
  for (const char ch : text) {
    out.push_back(static_cast<char>(std::toupper(static_cast<unsigned char>(ch))));
  }
  return out;
}

std::string normalized_mode(const std::string& raw) {
  std::string out;
  out.reserve(raw.size());
  for (const char ch : raw) {
    out.push_back(static_cast<char>(std::tolower(static_cast<unsigned char>(ch))));
  }
  return out == "agenda" ? "agenda" : "date";
}

int window_start(const int total, const int slots, const int selected) {
  if (total <= slots || selected < 0) {
    return 0;
  }
  return std::max(0, std::min(selected - (slots / 2), total - slots));
}

int days_in_month(int year, int month) {
  return app::calendar_runtime::days_in_month(year, month);
}

int start_weekday_sunday0(int year, int month) {
  return app::calendar_runtime::weekday_sunday0(app::calendar_runtime::DateValue{year, month, 1});
}

std::vector<AgendaRow> build_agenda_rows(
    const app::AppState& state,
    const app::calendar_runtime::AgendaSelection& selection,
    const UiStrings& s) {
  std::vector<AgendaRow> rows;
  rows.reserve(selection.event_indices.size() + selection.reminder_indices.size());

  for (const int event_index : selection.event_indices) {
    if (event_index < 0 || event_index >= static_cast<int>(state.dashboard.calendar_events.size())) {
      continue;
    }
    const auto& event = state.dashboard.calendar_events[static_cast<std::size_t>(event_index)];
    rows.push_back(AgendaRow{
        false,
        false,
        -1,
        event.when.empty() ? s.cal_event : event.when,
        event.title,
    });
  }

  for (const int reminder_index : selection.reminder_indices) {
    if (reminder_index < 0 || reminder_index >= static_cast<int>(state.dashboard.reminder_items.size())) {
      continue;
    }
    bool completed = false;
    if (reminder_index < static_cast<int>(state.dashboard.reminder_completed.size())) {
      completed = state.dashboard.reminder_completed[static_cast<std::size_t>(reminder_index)];
    }

    std::string right_text;
    if (reminder_index < static_cast<int>(state.dashboard.reminder_meta.size())) {
      right_text = state.dashboard.reminder_meta[static_cast<std::size_t>(reminder_index)].right;
    }
    if (right_text.empty()) {
      right_text = s.cal_reminder;
    }

    rows.push_back(AgendaRow{
        true,
        completed,
        reminder_index,
        right_text,
        state.dashboard.reminder_items[static_cast<std::size_t>(reminder_index)],
    });
  }

  return rows;
}

void draw_month_grid(
    std::vector<uint8_t>& image,
    const app::AppState& state,
    const app::calendar_runtime::DateValue& base_date,
    const app::calendar_runtime::DateValue& cursor,
    int x0,
    int y0,
    int x1,
    int y1,
    const UiStrings& s) {
  const std::array<const char*, 7> kWeek = {
      s.cal_sun, s.cal_mon, s.cal_tue, s.cal_wed, s.cal_thu, s.cal_fri, s.cal_sat};

  const int month_days = days_in_month(cursor.year, cursor.month);
  const int offset = start_weekday_sunday0(cursor.year, cursor.month);
  const int grid_w = std::max(1, x1 - x0);
  const int grid_h = std::max(1, y1 - y0);
  const int cell_w = std::max(28, grid_w / 7);
  const int cell_h = std::max(28, grid_h / 6);
  const int draw_w = cell_w * 7;
  const int draw_h = cell_h * 6;
  const int gx = x0 + (grid_w - draw_w) / 2;
  const int gy = y0 + (grid_h - draw_h) / 2;

  for (int i = 0; i < 7; ++i) {
    const int wx0 = gx + i * cell_w;
    const int wx1 = wx0 + cell_w - 2;
    draw_text_centered(image, wx0, wx1, y0 - 20, kWeek[static_cast<std::size_t>(i)], 1, 3);
  }

  for (int day = 1; day <= month_days; ++day) {
    const int index = offset + (day - 1);
    const int row = index / 7;
    const int col = index % 7;
    const int cx0 = gx + col * cell_w;
    const int cy0 = gy + row * cell_h;
    const int cx1 = cx0 + cell_w - 4;
    const int cy1 = cy0 + cell_h - 4;
    const bool selected = day == cursor.day;

    draw_outline_rect(image, cx0, cy0, cx1, cy1, 1);

    const auto date = app::calendar_runtime::DateValue{cursor.year, cursor.month, day};
    const auto day_items = app::calendar_runtime::agenda_selection_for_date(state, date, base_date);
    const bool has_items =
        !day_items.event_indices.empty() || !day_items.reminder_indices.empty();

    if (selected) {
      fill_black_rect(image, cx0 + 1, cy0 + 1, cx1 - 1, cy1 - 1);
      draw_text_centered_inverted(
          image,
          cx0,
          cx1,
          cy0 + ((cy1 - cy0) / 2) - 12,
          std::to_string(day),
          2,
          2);
    } else {
      draw_text_centered(
          image,
          cx0,
          cx1,
          cy0 + ((cy1 - cy0) / 2) - 12,
          std::to_string(day),
          2,
          2);
    }

    if (has_items) {
      const int dot_x0 = cx0 + (cell_w / 2) - 2;
      const int dot_y0 = cy1 - 6;
      fill_black_rect(image, dot_x0, dot_y0, dot_x0 + 4, dot_y0 + 3);
    }

    if (day == base_date.day && cursor.month == base_date.month && cursor.year == base_date.year) {
      draw_outline_rect(image, cx0 + 3, cy0 + 3, cx0 + 10, cy0 + 10, 1);
    }
  }
}

void draw_agenda_rows(
    std::vector<uint8_t>& image,
    int x0,
    int y0,
    int x1,
    int y1,
    const std::vector<AgendaRow>& rows,
    int selected_index,
    bool agenda_mode,
    const UiStrings& s) {
  const int available_h = std::max(1, y1 - y0);
  const int gap = 8;
  const int row_h = 56;
  const int slots = std::max(1, (available_h + gap) / (row_h + gap));
  const int start = window_start(static_cast<int>(rows.size()), slots, selected_index);
  const int visible = std::min(slots, static_cast<int>(rows.size()) - start);
  int yy = y0;
  for (int i = 0; i < visible; ++i) {
    const int global_index = start + i;
    if (global_index < 0 || global_index >= static_cast<int>(rows.size())) {
      break;
    }
    const auto& row = rows[static_cast<std::size_t>(global_index)];
    const bool selected = agenda_mode && global_index == selected_index;

    draw_outline_rect(image, x0, yy, x1, yy + row_h, 1);
    if (selected) {
      fill_black_rect(image, x0 + 1, yy + 1, x1 - 1, yy + row_h - 1);
    }

    const std::string type_prefix = row.reminder ? (row.completed ? "[x] " : "[ ] ") : "[E] ";
    const std::string title = truncate_text_px(type_prefix + upper_copy(row.title), 1, std::max(80, x1 - x0 - 24));
    const std::string when_text = truncate_text_px(upper_copy(row.when), 1, std::max(40, (x1 - x0) / 3));

    const int when_w = text_width_px(when_text, 1);
    if (selected) {
      draw_text_line_inverted(image, x0 + 10, yy + 10, title, 1, 42);
      draw_text_line_inverted(image, x1 - 10 - when_w, yy + 10, when_text, 1, 20);
      draw_text_line_inverted(
          image,
          x0 + 10,
          yy + 34,
          row.reminder ? s.cal_click_toggle : s.cal_event_readonly,
          1,
          28);
    } else {
      draw_text_line(image, x0 + 10, yy + 10, title, 1, 42);
      draw_text_line(image, x1 - 10 - when_w, yy + 10, when_text, 1, 20);
      draw_text_line(
          image,
          x0 + 10,
          yy + 34,
          row.reminder ? s.cal_reminder : s.cal_event,
          1,
          16);
    }

    yy += row_h + gap;
  }

  const int hidden = std::max(0, static_cast<int>(rows.size()) - (start + visible));
  if (hidden > 0) {
    const std::string more = "+" + std::to_string(hidden) + " " + s.cal_more;
    const int more_w = text_width_px(more, 1);
    draw_text_line(image, x1 - more_w - 4, std::max(y0 + 2, y1 - 14), more, 1, 16);
  }
}

}  // namespace

std::vector<uint8_t> render_calendar_landscape_bitmap(const app::AppState& state) {
  using platform::kPanelBufferSize;
  using platform::kPanelHeight;
  using platform::kPanelWidth;

  const auto& s = get_ui_strings(state.device_language);
  std::vector<uint8_t> image(kPanelBufferSize, 0xFF);

  const auto base_date = app::calendar_runtime::today_local_date(state);
  const auto cursor = app::calendar_runtime::cursor_date(state, base_date);
  const std::string mode = normalized_mode(state.calendar.mode);
  const bool agenda_mode = mode == "agenda";

  const auto selection = app::calendar_runtime::agenda_selection_for_cursor(state, base_date);
  const auto rows = build_agenda_rows(state, selection, s);
  const int selected_index = std::max(
      0,
      std::min(state.calendar.selected_index, std::max(0, static_cast<int>(rows.size()) - 1)));

  const int frame_pad = 12;
  const int content_x0 = 24;
  const int content_x1 = kPanelWidth - 24;
  const int content_y0 = 24;
  const int content_y1 = kPanelHeight - 24;
  const int right_x0 = std::max(1, std::min(kPanelWidth - 1, static_cast<int>(kPanelWidth * 0.45)));
  const int left_x0 = content_x0;
  const int left_x1 = right_x0 - 14;
  const int right_x1 = content_x1;

  draw_outline_rect(image, frame_pad, frame_pad, kPanelWidth - frame_pad, kPanelHeight - frame_pad, 2);
  fill_black_rect(image, right_x0, content_y0, right_x0 + 2, content_y1);

  const std::string month_name = app::calendar_runtime::month_name_upper(cursor.month);
  draw_text_line(image, left_x0, 34, month_name, 3, 18);
  draw_text_line(image, left_x0 + 2, 74, std::to_string(cursor.year), 1, 8);
  draw_text_line(image, left_x0 + 2, 96, s.cal_month_view, 1, 16);

  draw_month_grid(
      image,
      state,
      base_date,
      cursor,
      left_x0,
      134,
      left_x1,
      kPanelHeight - 52,
      s);

  const std::string day_chip = std::string(s.cal_day) + " " + std::to_string(cursor.day);
  const int chip_w = std::max(84, text_width_px(day_chip, 1) + 18);
  fill_black_rect(image, left_x0, kPanelHeight - 42, left_x0 + chip_w, kPanelHeight - 18);
  draw_text_centered_inverted(image, left_x0 + 2, left_x0 + chip_w - 2, kPanelHeight - 34, day_chip, 1, 20);

  draw_text_line(image, right_x0 + 14, 34, s.cal_agenda, 3, 12);
  const int weekday = app::calendar_runtime::weekday_sunday0(cursor);
  const std::string weekday_label = app::calendar_runtime::weekday_name_upper(weekday);
  draw_text_line(image, right_x0 + 14, 74, weekday_label, 1, 12);

  const std::string date_label =
      std::string(app::calendar_runtime::month_name_upper(cursor.month)) + " " + std::to_string(cursor.day);
  draw_text_line(image, right_x0 + 14, 96, date_label, 1, 22);

  const std::string mode_text = agenda_mode ? s.cal_mode_agenda : s.cal_mode_date;
  const int mode_w = text_width_px(mode_text, 1);
  draw_text_line(image, right_x1 - mode_w - 2, 34, mode_text, 1, 20);
  fill_black_rect(image, right_x0 + 14, 114, right_x1, 116);

  if (rows.empty()) {
    draw_text_line(image, right_x0 + 14, 154, s.cal_no_events, 2, 14);
    draw_text_wrapped(
        image,
        right_x0 + 14,
        186,
        std::max(80, right_x1 - right_x0 - 20),
        s.cal_voice_hint,
        1,
        3);
  } else {
    draw_agenda_rows(
        image,
        right_x0 + 14,
        126,
        right_x1,
        kPanelHeight - 22,
        rows,
        selected_index,
        agenda_mode,
        s);
  }

  return image;
}

}  // namespace fridge_ink::ui
