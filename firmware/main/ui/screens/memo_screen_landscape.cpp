#include "ui/screens/memo_screen.hpp"

#include "platform/panel_config.hpp"
#include "ui/draw.hpp"

#include <algorithm>
#include <cctype>
#include <string>
#include <vector>

namespace fridge_ink::ui {
namespace {

std::string upper_copy(const std::string& text) {
  std::string out = text;
  for (char& ch : out) {
    ch = static_cast<char>(std::toupper(static_cast<unsigned char>(ch)));
  }
  return out;
}

std::string trim_or_default(const std::string& text, const std::string& fallback) {
  const std::string trimmed = trim_copy(text);
  return trimmed.empty() ? fallback : trimmed;
}

int window_start(const int total, const int slots, const int selected) {
  if (total <= slots) {
    return 0;
  }
  return std::max(0, std::min(selected - (slots / 2), total - slots));
}

void clamp_memo_state(const app::AppState& state, int& selected_index) {
  const int total = static_cast<int>(state.dashboard.memos.size());
  if (total <= 0) {
    selected_index = 0;
    return;
  }
  selected_index = state.memo.index;
  if (selected_index < 0) {
    selected_index = 0;
  } else if (selected_index >= total) {
    selected_index = total - 1;
  }
}

}  // namespace

std::vector<uint8_t> render_memo_landscape_bitmap(const app::AppState& state) {
  using platform::kPanelBufferSize;
  using platform::kPanelHeight;
  using platform::kPanelWidth;

  std::vector<uint8_t> image(kPanelBufferSize, 0xFF);

  const int left = 24;
  const int right = kPanelWidth - 24;
  const int content_top = 86;
  const int content_bottom = kPanelHeight - 56;

  draw_text_line(image, left, 16, "FAMILY BOARD", 3, 20);
  const std::string hint = truncate_text_px(
      "ROTATE=SELECT  |  CLICK=ENTER  |  HOLD=HOME",
      1,
      std::max(80, right - left));
  const int hint_w = text_width_px(hint, 1);
  draw_text_line(image, std::max(left, right - hint_w), 52, hint, 1, 0);
  fill_black_rect(image, left, 68, right, 70);

  const auto& memos = state.dashboard.memos;
  const int total = static_cast<int>(memos.size());
  int selected = 0;
  clamp_memo_state(state, selected);

  if (total <= 0) {
    draw_text_line(image, left + 4, content_top + 8, "NO FAMILY NOTES YET", 2, 24);
    draw_text_line(
        image,
        left + 4,
        content_top + 42,
        "TRY VOICE: LEAVE A NOTE DINNER IS READY",
        1,
        52);
  } else {
    int unread = 0;
    for (const auto& memo : memos) {
      if (memo.is_new) {
        ++unread;
      }
    }

    const std::string summary =
        "TOTAL " + std::to_string(total) +
        "   NEW " + std::to_string(unread) +
        "   FOCUS " + std::to_string(selected + 1) + "/" + std::to_string(total);
    draw_text_line(image, left + 4, content_top, truncate_text_px(summary, 1, right - left - 8), 1, 0);

    const int row_h = 66;
    const int row_gap = 6;
    const int list_top = content_top + 22;
    const int available_h = std::max(1, content_bottom - list_top);
    const int slots = std::max(1, (available_h + row_gap) / (row_h + row_gap));
    const int start = window_start(total, slots, selected);
    const bool expanded = state.memo.expanded;

    for (int i = 0; i < slots; ++i) {
      const int idx = start + i;
      if (idx >= total) {
        break;
      }
      const int y0 = list_top + i * (row_h + row_gap);
      const int y1 = std::min(content_bottom, y0 + row_h);
      if (y1 <= y0) {
        continue;
      }

      const bool is_selected = idx == selected;
      const int cx0 = left + 4;
      const int cx1 = right - 4;
      if (is_selected) {
        fill_black_rect(image, cx0, y0 + 1, cx1, y1 - 1);
      } else {
        fill_black_rect(image, cx0 + 8, y1 - 1, cx1, y1);
      }

      const auto& memo = memos[static_cast<std::size_t>(idx)];
      const std::string author = upper_copy(trim_or_default(memo.author, "UNKNOWN"));
      const std::string posted = upper_copy(trim_or_default(memo.posted, "UNKNOWN TIME"));
      const std::string body = trim_or_default(memo.text, "No content.");

      const int content_x0 = cx0 + 10;
      const int content_x1 = cx1 - 10;
      const int posted_w = text_width_px(posted, 1);
      const int posted_x = std::max(content_x0, content_x1 - posted_w);
      const int author_max_w = std::max(56, posted_x - content_x0 - 8);
      const std::string author_fit = truncate_text_px(author, 2, author_max_w);

      if (is_selected) {
        draw_text_line_inverted(image, content_x0, y0 + 6, author_fit, 2, 0);
        draw_text_line_inverted(image, posted_x, y0 + 10, posted, 1, 0);
      } else {
        draw_text_line(image, content_x0, y0 + 6, author_fit, 2, 0);
        draw_text_line(image, posted_x, y0 + 10, posted, 1, 0);
      }

      const int body_width = std::max(48, content_x1 - content_x0);
      const int max_body_lines = (is_selected && expanded) ? 2 : 1;
      const int chars_per_line = std::max(8, body_width / 10);
      const std::vector<std::string> wrapped = wrap_words(body, static_cast<std::size_t>(chars_per_line));
      const int lines = std::min(max_body_lines, static_cast<int>(wrapped.size()));
      int body_y = y0 + 34;
      for (int ln = 0; ln < lines; ++ln) {
        const std::string line = truncate_text_px(wrapped[static_cast<std::size_t>(ln)], 2, body_width);
        if (is_selected) {
          draw_text_line_inverted(image, content_x0, body_y, line, 2, 0);
        } else {
          draw_text_line(image, content_x0, body_y, line, 2, 0);
        }
        body_y += 24;
      }
      if (static_cast<int>(wrapped.size()) > lines && lines > 0) {
        if (is_selected) {
          draw_text_line_inverted(image, content_x1 - 24, body_y - 10, "...", 1, 3);
        } else {
          draw_text_line(image, content_x1 - 24, body_y - 10, "...", 1, 3);
        }
      }

      if (memo.is_new) {
        const std::string badge = "NEW";
        const int badge_w = text_width_px(badge, 1);
        const int badge_x = std::max(content_x0, content_x1 - badge_w);
        if (is_selected) {
          draw_text_line_inverted(image, badge_x, y1 - 18, badge, 1, 3);
        } else {
          draw_text_line(image, badge_x, y1 - 18, badge, 1, 3);
        }
      }
    }

    if (total > slots) {
      const std::string tail =
          "SHOWING " + std::to_string(start + 1) + "-" +
          std::to_string(std::min(total, start + slots)) +
          " OF " + std::to_string(total);
      draw_text_line(image, left + 4, content_bottom - 16, truncate_text_px(tail, 1, right - left - 8), 1, 0);
    }
  }

  draw_text_line(
      image,
      left,
      kPanelHeight - 40,
      "VOICE CMD: ADD | DELETE | CLEAR",
      1,
      40);

  return image;
}

}  // namespace fridge_ink::ui
