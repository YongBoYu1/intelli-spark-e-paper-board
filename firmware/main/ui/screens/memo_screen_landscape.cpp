#include "ui/screens/memo_screen.hpp"

#include "platform/panel_config.hpp"
#include "ui/draw.hpp"

#include <algorithm>
#include <cctype>
#include <string>
#include <vector>

namespace {

std::string trim_copy(const std::string& value) {
  std::size_t start = 0;
  while (start < value.size() &&
         std::isspace(static_cast<unsigned char>(value[start])) != 0) {
    ++start;
  }

  std::size_t end = value.size();
  while (end > start &&
         std::isspace(static_cast<unsigned char>(value[end - 1])) != 0) {
    --end;
  }

  return value.substr(start, end - start);
}

std::string uppercase_copy(const std::string& value) {
  std::string out = trim_copy(value);
  for (char& ch : out) {
    ch = static_cast<char>(std::toupper(static_cast<unsigned char>(ch)));
  }
  return out;
}

int clamp_int(const int value, const int low, const int high) {
  return std::max(low, std::min(value, high));
}

int count_completed(const std::vector<bool>& completed, const int limit) {
  const int count = std::max(0, limit);
  int total = 0;
  for (int i = 0; i < count; ++i) {
    if (i < static_cast<int>(completed.size()) &&
        completed[static_cast<std::size_t>(i)]) {
      ++total;
    }
  }
  return total;
}

}  // namespace

namespace fridge_ink::ui {

std::vector<uint8_t> render_memo_landscape_bitmap(const app::AppState& state) {
  using platform::kPanelBufferSize;
  using platform::kPanelHeight;
  using platform::kPanelWidth;

  std::vector<uint8_t> image(kPanelBufferSize, 0xFF);
  const app::DashboardSummary& dashboard = state.dashboard;

  const std::string memo_text = trim_copy(dashboard.family_memo_text);
  const std::string memo_author = uppercase_copy(dashboard.family_memo_author);
  const std::string memo_posted = uppercase_copy(dashboard.family_memo_posted);

  const int reminder_total = static_cast<int>(dashboard.reminder_items.size());
  const int completed_total = count_completed(dashboard.reminder_completed, reminder_total);
  const int memo_count = memo_text.empty() ? 0 : 1;

  const int page_margin = 18;
  const int page_x0 = page_margin;
  const int page_y0 = page_margin;
  const int page_x1 = kPanelWidth - page_margin;
  const int page_y1 = kPanelHeight - page_margin;
  draw_outline_rect(image, page_x0, page_y0, page_x1, page_y1, 3);

  draw_text_line(image, 40, 28, "MEMO", 3, 16);
  draw_text_line(image, 40, 64, "FAMILY NOTE + REMINDERS", 1, 32);

  const std::string header_summary =
      std::to_string(memo_count) + " NOTE" + (memo_count == 1 ? "" : "S") + "  |  " +
      std::to_string(reminder_total) + " REMINDERS  |  " +
      std::to_string(completed_total) + " DONE";
  const std::string header_fit = truncate_text_px(header_summary, 1, page_x1 - 220);
  const int header_width = text_width_px(header_fit, 1);
  draw_text_line(image, page_x1 - 24 - header_width, 64, header_fit, 1, 0);

  draw_outline_rect(image, 34, 86, page_x1 - 34, 88, 2);

  const int content_y0 = 106;
  const int content_y1 = 404;
  const int gap = 14;
  const int left_x0 = 34;
  const int left_x1 = 396;
  const int right_x0 = left_x1 + gap;
  const int right_x1 = page_x1 - 34;

  const int card_border = 2;
  const int section_header_h = 32;
  const int body_left_y = content_y0 + section_header_h + 12;
  const int body_right_y = content_y0 + section_header_h + 10;

  const bool focus_visible = state.home.show_focus;
  const int focus_index = std::max(0, state.home.focused_index);
  const bool focus_on_memo = focus_visible && (focus_index < 2 || reminder_total <= 0);
  int focused_reminder = 0;
  if (focus_visible && reminder_total > 0 && focus_index >= 2) {
    focused_reminder = clamp_int(focus_index - 2, 0, reminder_total - 1);
  }

  const int memo_inner_x0 = left_x0 + 12;
  const int memo_inner_x1 = left_x1 - 12;
  const int memo_body_y = body_left_y + 26;
  const int memo_body_w = memo_inner_x1 - memo_inner_x0;

  if (focus_on_memo) {
    draw_outline_rect(image, left_x0 - 3, content_y0 - 3, left_x1 + 3, content_y1 + 3, 4);
  }
  draw_outline_rect(image, left_x0, content_y0, left_x1, content_y1, card_border);
  fill_black_rect(image, left_x0, content_y0, left_x1, content_y0 + section_header_h);
  draw_text_line_inverted(image, left_x0 + 12, content_y0 + 8, "FAMILY NOTE", 1, 20);

  if (!memo_author.empty()) {
    const std::string author_fit =
        truncate_text_px(memo_author, 1, memo_inner_x1 - memo_inner_x0 - 50);
    draw_text_line_inverted(image, memo_inner_x0, body_left_y, author_fit, 1, 0);
  }
  if (!memo_posted.empty()) {
    const std::string posted_fit =
        truncate_text_px(memo_posted, 1, memo_inner_x1 - memo_inner_x0 - 50);
    const int posted_width = text_width_px(posted_fit, 1);
    draw_text_line_inverted(image, memo_inner_x1 - posted_width, body_left_y, posted_fit, 1, 0);
  }

  if (!memo_text.empty()) {
    draw_text_wrapped(image, memo_inner_x0, memo_body_y, memo_body_w, memo_text, 2, 6);
  } else {
    draw_text_centered(
        image, memo_inner_x0, memo_inner_x1, memo_body_y + 48, "NO FAMILY MEMO SAVED", 2, 28);
  }

  draw_outline_rect(image, right_x0, content_y0, right_x1, content_y1, card_border);
  fill_black_rect(image, right_x0, content_y0, right_x1, content_y0 + section_header_h);
  draw_text_line_inverted(image, right_x0 + 12, content_y0 + 8, "REMINDERS", 1, 16);

  const std::string reminder_summary =
      std::to_string(reminder_total) + " ITEMS  |  " + std::to_string(completed_total) + " DONE";
  const std::string reminder_fit = truncate_text_px(reminder_summary, 1, right_x1 - right_x0 - 26);
  const int reminder_width = text_width_px(reminder_fit, 1);
  draw_text_line_inverted(
      image, right_x1 - 12 - reminder_width, content_y0 + 8, reminder_fit, 1, 0);

  const int rows_x0 = right_x0 + 10;
  const int rows_x1 = right_x1 - 10;
  const int rows_y0 = body_right_y;
  const int row_h = 28;
  const int row_gap = 6;
  const int row_pitch = row_h + row_gap;
  const int rows_available_h = content_y1 - 12 - rows_y0;
  const int max_visible_rows = std::max(1, (rows_available_h + row_gap) / row_pitch);
  const int visible_rows = std::min(reminder_total, max_visible_rows);

  int window_start = 0;
  if (reminder_total > visible_rows && focus_visible && focus_index >= 2) {
    window_start = clamp_int(
        focused_reminder - (visible_rows / 2), 0, reminder_total - visible_rows);
  }

  if (reminder_total <= 0) {
    draw_text_centered(image, rows_x0, rows_x1, rows_y0 + 70, "NO REMINDERS YET", 2, 20);
  } else {
    for (int i = 0; i < visible_rows; ++i) {
      const int reminder_index = window_start + i;
      const std::string reminder_text =
          trim_copy(dashboard.reminder_items[static_cast<std::size_t>(reminder_index)]);
      const bool completed =
          reminder_index < static_cast<int>(dashboard.reminder_completed.size()) &&
          dashboard.reminder_completed[static_cast<std::size_t>(reminder_index)];
      const bool row_focused = focus_visible && !focus_on_memo && reminder_index == focused_reminder;
      const int y0 = rows_y0 + (i * row_pitch);
      const int y1 = y0 + row_h;

      if (row_focused) {
        fill_black_rect(image, rows_x0, y0, rows_x1, y1);
        draw_outline_rect(image, rows_x0 - 2, y0 - 2, rows_x1 + 2, y1 + 2, 2);
      } else {
        draw_outline_rect(image, rows_x0, y0, rows_x1, y1, 1);
      }

      const char* const status = completed ? "[X]" : "[ ]";
      const int text_scale = 1;
      const int text_y = y0 + 8;
      const int status_x = rows_x0 + 10;
      const int label_x = rows_x0 + 46;
      const int label_w = rows_x1 - label_x - 10;
      const std::string label_fit = truncate_text_px(reminder_text, text_scale, label_w);

      if (row_focused) {
        draw_text_line_inverted(image, status_x, text_y, status, text_scale, 4);
        draw_text_line_inverted(image, label_x, text_y, label_fit, text_scale, 0);
      } else {
        draw_text_line(image, status_x, text_y, status, text_scale, 4);
        draw_text_line(image, label_x, text_y, label_fit, text_scale, 0);
      }
    }

    if (reminder_total > visible_rows) {
      const std::string tail =
          "SHOWING " + std::to_string(window_start + 1) + "-" +
          std::to_string(window_start + visible_rows) + " OF " + std::to_string(reminder_total);
      draw_text_line(image, rows_x0, content_y1 - 18, tail, 1, 24);
    }
  }

  const int footer_y0 = 414;
  const int footer_y1 = 456;
  draw_outline_rect(image, 34, footer_y0, page_x1 - 34, footer_y1, 2);
  const std::string focus_label = !focus_visible
                                      ? "VIEW MODE"
                                      : (focus_on_memo
                                             ? "FOCUS MEMO"
                                             : ("FOCUS REMINDER " +
                                                std::to_string(focused_reminder + 1)));
  draw_text_line(image, 50, footer_y0 + 14, focus_label, 1, 18);
  const std::string footer_hint_raw = "ROTATE TO MOVE  |  CLICK TO OPEN  |  HOLD TO HOME";
  const std::string footer_hint =
      truncate_text_px(footer_hint_raw, 1, (page_x1 - 34) - 170);
  const int footer_hint_w = text_width_px(footer_hint, 1);
  draw_text_line(image, page_x1 - 50 - footer_hint_w, footer_y0 + 14, footer_hint, 1, 0);

  return image;
}

}  // namespace fridge_ink::ui
