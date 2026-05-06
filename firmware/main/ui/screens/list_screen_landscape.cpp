#include "ui/screens/list_screen.hpp"

#include "platform/panel_config.hpp"
#include "ui/draw.hpp"
#include "ui/strings.hpp"

#include <algorithm>
#include <string>
#include <vector>

namespace fridge_ink::ui {
namespace {

struct ListRow {
  std::string title;
  bool completed{false};
};

int window_start(const int total, const int slots, const int selected) {
  if (total <= slots || selected < 0) {
    return 0;
  }
  return std::max(0, std::min(selected - (slots / 2), total - slots));
}

std::vector<ListRow> build_inventory_rows(const app::AppState& state) {
  std::vector<ListRow> rows;
  const auto& items = state.dashboard.inventory_items;
  const auto& completed = state.dashboard.inventory_completed;
  const auto& hidden = state.home.hidden_inventory_indices;
  rows.reserve(items.size());
  for (std::size_t i = 0; i < items.size(); ++i) {
    if (std::find(hidden.begin(), hidden.end(), static_cast<int>(i)) != hidden.end()) {
      continue;
    }
    const bool done = i < completed.size() && completed[i];
    rows.push_back(ListRow{items[i], done});
  }
  return rows;
}

std::vector<ListRow> build_reminder_rows(const app::AppState& state) {
  std::vector<ListRow> rows;
  const auto& items = state.dashboard.reminder_items;
  const auto& completed = state.dashboard.reminder_completed;
  const auto& hidden = state.home.hidden_reminder_indices;
  rows.reserve(items.size());
  for (std::size_t i = 0; i < items.size(); ++i) {
    if (std::find(hidden.begin(), hidden.end(), static_cast<int>(i)) != hidden.end()) {
      continue;
    }
    const bool done = i < completed.size() && completed[i];
    rows.push_back(ListRow{items[i], done});
  }
  return rows;
}

void draw_inventory_column(
    std::vector<uint8_t>& image,
    const std::vector<ListRow>& rows,
    const int x0,
    const int x1,
    const int y0,
    const int y1,
    const int selected_index,
    const UiStrings& s) {
  const int row_h = 40;
  const int slots = std::max(1, (y1 - y0) / row_h);
  const int start = window_start(static_cast<int>(rows.size()), slots, selected_index);
  int y = y0;
  for (int i = 0; i < slots; ++i) {
    const int row_index = start + i;
    if (row_index >= static_cast<int>(rows.size()) || y + row_h > y1) {
      break;
    }
    const bool selected = row_index == selected_index;
    const int ry0 = y + 1;
    const int ry1 = y + row_h - 2;
    if (selected) {
      fill_black_rect(image, x0, ry0, x1, ry1);
    } else {
      fill_black_rect(image, x0 + 6, ry1, x1, ry1 + 1);
    }

    const std::string prefix = rows[static_cast<std::size_t>(row_index)].completed ? "[x] " : "[ ] ";
    const std::string line_raw = prefix + rows[static_cast<std::size_t>(row_index)].title;
    const std::string line =
        truncate_text_px(line_raw, 2, std::max(70, x1 - x0 - 20));
    if (selected) {
      draw_text_line_inverted(image, x0 + 8, y + 10, line, 2, 0);
    } else {
      draw_text_line(image, x0 + 8, y + 10, line, 2, 0);
    }
    y += row_h;
  }
  if (rows.empty()) {
    draw_text_line(image, x0 + 8, y0 + 10, s.list_no_items, 1, 12);
  }
}

void draw_reminder_column(
    std::vector<uint8_t>& image,
    const std::vector<ListRow>& rows,
    const int x0,
    const int x1,
    const int y0,
    const int y1,
    const int selected_index,
    const UiStrings& s) {
  const int row_h = 40;
  const int slots = std::max(1, (y1 - y0) / row_h);
  const int start = window_start(static_cast<int>(rows.size()), slots, selected_index);
  int y = y0;
  for (int i = 0; i < slots; ++i) {
    const int row_index = start + i;
    if (row_index >= static_cast<int>(rows.size()) || y + row_h > y1) {
      break;
    }
    const bool selected = row_index == selected_index;
    const int ry0 = y + 1;
    const int ry1 = y + row_h - 2;
    if (selected) {
      fill_black_rect(image, x0, ry0, x1, ry1);
    } else {
      fill_black_rect(image, x0 + 6, ry1, x1, ry1 + 1);
    }

    const std::string prefix = rows[static_cast<std::size_t>(row_index)].completed ? "[x] " : "[ ] ";
    const std::string right_meta = rows[static_cast<std::size_t>(row_index)].completed ? s.list_done : s.list_todo;
    const std::string right_fit =
        truncate_text_px(right_meta, 1, std::max(52, ((x1 - x0) * 26) / 100));
    const int right_w = text_width_px(right_fit, 1);
    const int right_x = std::max(x0 + 8, x1 - right_w - 8);
    if (selected) {
      draw_text_line_inverted(image, right_x, y + 11, right_fit, 1, 0);
    } else {
      draw_text_line(image, right_x, y + 11, right_fit, 1, 0);
    }

    const int title_max_w = std::max(80, right_x - x0 - 14);
    const std::string title =
        truncate_text_px(prefix + rows[static_cast<std::size_t>(row_index)].title, 2, title_max_w);
    if (selected) {
      draw_text_line_inverted(image, x0 + 8, y + 10, title, 2, 0);
    } else {
      draw_text_line(image, x0 + 8, y + 10, title, 2, 0);
    }
    y += row_h;
  }
  if (rows.empty()) {
    draw_text_line(image, x0 + 8, y0 + 10, s.list_no_items, 1, 12);
  }
}

}  // namespace

std::vector<uint8_t> render_list_landscape_bitmap(const app::AppState& state) {
  using platform::kPanelBufferSize;
  using platform::kPanelHeight;
  using platform::kPanelWidth;

  const auto& s = get_ui_strings(state.device_language);
  std::vector<uint8_t> image(kPanelBufferSize, 0xFF);
  const std::vector<ListRow> inventory = build_inventory_rows(state);
  const std::vector<ListRow> reminders = build_reminder_rows(state);

  const int left = 24;
  const int right = kPanelWidth - 24;
  draw_text_line(image, left, 16, s.list_title, 3, 16);
  const std::string hint = s.list_hint;
  const std::string hint_fit = truncate_text_px(hint, 1, std::max(80, right - left));
  const int hint_w = text_width_px(hint_fit, 1);
  draw_text_line(image, std::max(left, right - hint_w), 52, hint_fit, 1, 0);
  fill_black_rect(image, left, 68, right, 70);

  const int content_top = 104;
  const int footer_y = kPanelHeight - 40;
  const int content_bottom = footer_y - 6;
  const int split_x = left + ((right - left) * 40 / 100);
  const int left_x0 = left;
  const int left_x1 = std::max(left + 40, split_x - 4);
  const int right_x0 = std::min(right - 40, split_x + 4);
  const int right_x1 = right;

  fill_black_rect(image, split_x, content_top, split_x + 2, content_bottom);
  draw_text_line(
      image,
      left_x0 + 2,
      content_top + 2,
      truncate_text_px(std::string(s.list_inventory) + " " + std::to_string(inventory.size()), 1, std::max(60, left_x1 - left_x0 - 8)),
      1,
      0);
  draw_text_line(
      image,
      right_x0 + 2,
      content_top + 2,
      truncate_text_px(std::string(s.list_reminder) + " " + std::to_string(reminders.size()), 1, std::max(60, right_x1 - right_x0 - 8)),
      1,
      0);

  const int list_top = content_top + 22;
  const int total_items = static_cast<int>(inventory.size() + reminders.size());
  int focused_global = -1;
  if (total_items > 0) {
    focused_global = std::max(0, std::min(state.inventory.focused_index, total_items - 1));
  }
  const int selected_inventory =
      (focused_global >= 0 && focused_global < static_cast<int>(inventory.size())) ? focused_global : -1;
  const int selected_reminder =
      (focused_global >= static_cast<int>(inventory.size()) && !reminders.empty())
          ? (focused_global - static_cast<int>(inventory.size()))
          : -1;

  draw_inventory_column(image, inventory, left_x0, left_x1, list_top, content_bottom, selected_inventory, s);
  draw_reminder_column(image, reminders, right_x0, right_x1, list_top, content_bottom, selected_reminder, s);

  const std::string footer =
      truncate_text_px(s.list_footer, 1, std::max(80, right - left));
  draw_text_line(image, left, footer_y, footer, 1, 0);
  return image;
}

}  // namespace fridge_ink::ui
