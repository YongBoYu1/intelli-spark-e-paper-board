#include "ui/screens/memo_screen.hpp"

#include "platform/panel_config.hpp"
#include "ui/draw.hpp"

#include <algorithm>
#include <string>
#include <vector>

namespace fridge_ink::ui {
namespace {

using platform::kPanelBufferSize;
using platform::kPanelHeight;
using platform::kPanelWidth;

struct MemoRow {
  std::string kind;
  std::string body;
  std::string status;
  bool selected{false};
};

std::string uppercase_copy(std::string text) {
  for (char& ch : text) {
    if (ch >= 'a' && ch <= 'z') {
      ch = static_cast<char>(ch - ('a' - 'A'));
    }
  }
  return text;
}

std::string strip_or_default(const std::string& text, const std::string& fallback) {
  const std::string trimmed = trim_copy(text);
  return trimmed.empty() ? fallback : trimmed;
}

std::string truncated_text(
    const std::string& text,
    const int scale,
    const int max_width_px) {
  return truncate_text_px(trim_copy(text), scale, std::max(0, max_width_px));
}

void draw_right_aligned_text(
    std::vector<uint8_t>& image,
    const int right_x,
    const int y,
    const std::string& text,
    const int scale,
    const int max_width_px,
    const bool inverted = false) {
  const std::string clipped = truncated_text(text, scale, max_width_px);
  const int x = std::max(0, right_x - text_width_px(clipped, scale));
  if (inverted) {
    draw_text_line_inverted(image, x, y, clipped, scale, 0);
  } else {
    draw_text_line(image, x, y, clipped, scale, 0);
  }
}

void draw_rule(std::vector<uint8_t>& image, const int x0, const int x1, const int y) {
  fill_black_rect(image, x0, y, x1, y + 1);
}

std::vector<MemoRow> build_rows(const app::AppState& state) {
  const auto& dashboard = state.dashboard;
  std::vector<MemoRow> rows;

  const std::size_t reminder_count = dashboard.reminder_items.size();
  const std::size_t reminder_flags = dashboard.reminder_completed.size();
  for (std::size_t i = 0; i < reminder_count; ++i) {
    const std::string body = strip_or_default(dashboard.reminder_items[i], "UNTITLED NOTE");
    const bool done = i < reminder_flags && dashboard.reminder_completed[i];
    rows.push_back(MemoRow{
        "REMINDER",
        body,
        done ? "DONE" : "OPEN",
        rows.empty(),
    });
  }

  const std::size_t inventory_count = dashboard.inventory_items.size();
  const std::size_t inventory_flags = dashboard.inventory_completed.size();
  const std::size_t inventory_badges = dashboard.inventory_badges.size();
  for (std::size_t i = 0; i < inventory_count; ++i) {
    const std::string body = strip_or_default(dashboard.inventory_items[i], "EMPTY SHELF");
    std::string status = "OPEN";
    if (i < inventory_badges && !trim_copy(dashboard.inventory_badges[i]).empty()) {
      status = uppercase_copy(trim_copy(dashboard.inventory_badges[i]));
    } else if (i < inventory_flags && dashboard.inventory_completed[i]) {
      status = "DONE";
    }
    rows.push_back(MemoRow{
        "PANTRY",
        body,
        status,
        rows.empty(),
    });
  }

  if (rows.empty()) {
    rows.push_back(MemoRow{"MEMO", "NO OPEN ITEMS", "READY", true});
  }

  if (!rows.empty()) {
    rows.front().selected = true;
  }

  return rows;
}

void draw_memo_card(
    std::vector<uint8_t>& image,
    const app::DashboardSummary& dashboard,
    const int x0,
    const int y0,
    const int x1,
    const int y1) {
  const int title_h = 27;
  const int inner_x0 = x0 + 16;
  const int inner_x1 = x1 - 16;
  const std::string author = uppercase_copy(strip_or_default(dashboard.family_memo_author, "FAMILY BOARD"));
  const std::string posted = uppercase_copy(trim_copy(dashboard.family_memo_posted));
  const std::string memo_text = trim_copy(dashboard.family_memo_text);

  draw_outline_rect(image, x0, y0, x1, y1, 2);
  fill_black_rect(image, x0, y0, x1, y0 + title_h);
  draw_text_line_inverted(image, inner_x0, y0 + 7, "FAMILY BOARD", 1, 32);

  const std::string top_right = posted.empty() ? author : (author + " / " + posted);
  draw_right_aligned_text(image, inner_x1, y0 + 7, top_right, 1, 260, true);

  if (!memo_text.empty()) {
    draw_text_wrapped(image, inner_x0, y0 + 42, inner_x1 - inner_x0, memo_text, 2, 2);
  } else {
    draw_text_line(image, inner_x0, y0 + 46, "NO FAMILY MEMO", 2, 28);
    draw_text_line(image, inner_x0, y0 + 78, "VOICE TO ADD A NOTE", 1, 32);
  }

  const int meta_y = y1 - 24;
  const std::string meta_left = std::string("LOCATION ") + uppercase_copy(strip_or_default(dashboard.location, "KITCHEN"));
  const std::string meta_right = std::string("BATTERY ") + std::to_string(dashboard.battery_percent) + "%";
  draw_text_line(image, inner_x0, meta_y, meta_left, 1, 36);
  draw_right_aligned_text(image, inner_x1, meta_y, meta_right, 1, 180);
}

void draw_rows_section(
    std::vector<uint8_t>& image,
    const std::vector<MemoRow>& rows,
    const int x0,
    const int y0,
    const int x1,
    const int y1) {
  const int heading_y = y0 + 2;
  draw_text_line(image, x0, heading_y, "OPEN ITEMS", 1, 24);

  const int total = static_cast<int>(rows.size());
  const int visible_slots = 3;
  const int visible_end = std::min(total, visible_slots);
  const std::string summary = std::string("SHOWING 1-") + std::to_string(visible_end) + " OF " +
                              std::to_string(total);
  draw_right_aligned_text(image, x1, heading_y, summary, 1, 220);
  draw_rule(image, x0, x1, y0 + 18);

  const int row_x0 = x0;
  const int row_x1 = x1;
  const int row_h = 42;
  const int row_gap = 6;
  const int row_top = y0 + 28;
  const int row_count = std::min(visible_slots, total);
  for (int i = 0; i < row_count; ++i) {
    const MemoRow& row = rows[static_cast<std::size_t>(i)];
    const int ry0 = row_top + i * (row_h + row_gap);
    const int ry1 = std::min(y1, ry0 + row_h);
    if (row.selected) {
      fill_black_rect(image, row_x0, ry0, row_x1, ry1);
    } else {
      draw_outline_rect(image, row_x0, ry0, row_x1, ry1, 1);
    }

    const int text_x = row_x0 + 12;
    const int content_x1 = row_x1 - 12;
    const bool inverted = row.selected;
    const int kind_y = ry0 + 6;
    const int body_y = ry0 + 18;
    const int status_y = ry0 + 6;

    const std::string kind = uppercase_copy(row.kind);
    const std::string status = uppercase_copy(row.status);
    const int status_w = text_width_px(status, 1);
    const int status_x = std::max(text_x, content_x1 - status_w);
    const int body_width = std::max(24, status_x - text_x - 10);
    const std::string body = truncated_text(row.body, 2, body_width);

    if (inverted) {
      draw_text_line_inverted(image, text_x, kind_y, kind, 1, 18);
      draw_text_line_inverted(image, text_x, body_y, body, 2, 0);
      draw_text_line_inverted(image, status_x, status_y, status, 1, 12);
    } else {
      draw_text_line(image, text_x, kind_y, kind, 1, 18);
      draw_text_line(image, text_x, body_y, body, 2, 0);
      draw_text_line(image, status_x, status_y, status, 1, 12);
    }
  }

  if (total > visible_slots) {
    const std::string tail = std::string("SHOWING 1-") + std::to_string(visible_slots) +
                             " OF " + std::to_string(total);
    draw_right_aligned_text(image, x1, y1 - 2, tail, 1, 240);
  }
}

}  // namespace

std::vector<uint8_t> render_memo_portrait_bitmap(const app::AppState& state) {
  std::vector<uint8_t> image(kPanelBufferSize, 0xFF);

  const auto& dashboard = state.dashboard;
  const std::vector<MemoRow> rows = build_rows(state);

  const int outer_x0 = 12;
  const int outer_y0 = 12;
  const int outer_x1 = kPanelWidth - 12;
  const int outer_y1 = kPanelHeight - 12;

  draw_outline_rect(image, outer_x0, outer_y0, outer_x1, outer_y1, 2);

  draw_text_line(image, 26, 18, "MEMO", 3, 20);
  const int open_count = static_cast<int>(rows.size());
  const int reminder_count = static_cast<int>(dashboard.reminder_items.size());
  const int inventory_count = static_cast<int>(dashboard.inventory_items.size());
  const std::string header_status =
      std::string("OPEN ") + std::to_string(open_count) + "  R " + std::to_string(reminder_count) +
      "  P " + std::to_string(inventory_count);
  draw_right_aligned_text(image, outer_x1 - 12, 24, header_status, 1, 260);
  draw_text_line(image, 28, 52, "PORTRAIT FAMILY BOARD", 1, 32);
  draw_rule(image, outer_x0 + 12, outer_x1 - 12, 68);

  draw_memo_card(image, dashboard, 24, 84, kPanelWidth - 24, 214);

  draw_rows_section(image, rows, 24, 228, kPanelWidth - 24, 416);

  draw_rule(image, outer_x0 + 12, outer_x1 - 12, 430);
  draw_text_line(image, 28, 442, "VOICE: ADD | DELETE | CLEAR", 1, 34);
  draw_right_aligned_text(
      image,
      outer_x1 - 12,
      442,
      "ROTATE TO BROWSE OPEN ITEMS",
      1,
      240);

  return image;
}

}  // namespace fridge_ink::ui
