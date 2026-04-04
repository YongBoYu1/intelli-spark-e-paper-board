#include "ui/screens/list_screen.hpp"

#include "platform/panel_config.hpp"
#include "ui/draw.hpp"

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
  rows.reserve(state.dashboard.inventory_items.size());
  for (std::size_t i = 0; i < state.dashboard.inventory_items.size(); ++i) {
    const bool done =
        i < state.dashboard.inventory_completed.size() &&
        state.dashboard.inventory_completed[i];
    rows.push_back(ListRow{state.dashboard.inventory_items[i], done});
  }
  return rows;
}

std::vector<ListRow> build_reminder_rows(const app::AppState& state) {
  std::vector<ListRow> rows;
  rows.reserve(state.dashboard.reminder_items.size());
  for (std::size_t i = 0; i < state.dashboard.reminder_items.size(); ++i) {
    const bool done =
        i < state.dashboard.reminder_completed.size() &&
        state.dashboard.reminder_completed[i];
    rows.push_back(ListRow{state.dashboard.reminder_items[i], done});
  }
  return rows;
}

void draw_rows(
    std::vector<uint8_t>& image,
    const std::vector<ListRow>& rows,
    const int x0,
    const int x1,
    const int y0,
    const int y1,
    const int selected_index,
    const bool show_meta) {
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
    if (show_meta) {
      const std::string right_meta = rows[static_cast<std::size_t>(row_index)].completed ? "DONE" : "TODO";
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
    } else {
      const std::string line =
          truncate_text_px(prefix + rows[static_cast<std::size_t>(row_index)].title, 2, std::max(70, x1 - x0 - 20));
      if (selected) {
        draw_text_line_inverted(image, x0 + 8, y + 10, line, 2, 0);
      } else {
        draw_text_line(image, x0 + 8, y + 10, line, 2, 0);
      }
    }
    y += row_h;
  }
  if (rows.empty()) {
    draw_text_line(image, x0 + 8, y0 + 10, "NO ITEMS", 1, 12);
  }
}

}  // namespace

std::vector<uint8_t> render_list_portrait_bitmap(const app::AppState& state) {
  using platform::kPanelBufferSize;
  using platform::kPanelHeight;
  using platform::kPanelWidth;

  std::vector<uint8_t> image(kPanelBufferSize, 0xFF);
  const std::vector<ListRow> inventory = build_inventory_rows(state);
  const std::vector<ListRow> reminders = build_reminder_rows(state);

  const int left = 24;
  const int right = kPanelWidth - 24;
  draw_text_line(image, left, 16, "LIST", 3, 16);
  const std::string hint_fit =
      truncate_text_px("ROTATE=SELECT  |  CLICK=TOGGLE  |  HOLD=HOME", 1, std::max(80, right - left));
  const int hint_w = text_width_px(hint_fit, 1);
  draw_text_line(image, std::max(left, right - hint_w), 52, hint_fit, 1, 0);
  fill_black_rect(image, left, 68, right, 70);

  const int content_top = 104;
  const int footer_y = kPanelHeight - 40;
  const int content_bottom = footer_y - 6;
  const int split_y_raw = content_top + ((content_bottom - content_top) / 3);
  const int split_y = std::max(content_top + 72, std::min(content_bottom - 120, split_y_raw));
  fill_black_rect(image, left, split_y, right, split_y + 2);

  draw_text_line(
      image,
      left + 2,
      content_top + 2,
      truncate_text_px("INVENTORY " + std::to_string(inventory.size()), 1, std::max(60, right - left - 8)),
      1,
      0);
  draw_text_line(
      image,
      left + 2,
      split_y + 2,
      truncate_text_px("REMINDER " + std::to_string(reminders.size()), 1, std::max(60, right - left - 8)),
      1,
      0);

  const int inv_list_top = content_top + 22;
  const int inv_list_bottom = split_y - 6;
  const int rem_list_top = split_y + 22;
  const int rem_list_bottom = content_bottom;

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

  draw_rows(image, inventory, left, right, inv_list_top, inv_list_bottom, selected_inventory, false);
  draw_rows(image, reminders, left, right, rem_list_top, rem_list_bottom, selected_reminder, true);

  const std::string footer =
      truncate_text_px("VOICE CMD: DELETE | ADD | MODIFY", 1, std::max(80, right - left));
  draw_text_line(image, left, footer_y, footer, 1, 0);
  return image;
}

}  // namespace fridge_ink::ui
