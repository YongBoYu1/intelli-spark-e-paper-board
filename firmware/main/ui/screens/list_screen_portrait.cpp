#include "ui/screens/list_screen.hpp"

#include "platform/panel_config.hpp"
#include "ui/draw.hpp"
#include "ui/panel_font_assets_generated.hpp"
#include "ui/strings.hpp"

#include <algorithm>
#include <cctype>
#include <string>
#include <vector>

namespace fridge_ink::ui {
namespace {

using platform::panel_font_assets::BitmapFont;
using platform::panel_font_assets::Glyph;

constexpr int kPW = 480;
constexpr int kPH = 800;

struct ListRow {
  std::string title;
  bool completed{false};
  std::string right{};
};

int normalize_rotation_deg(const int raw) {
  const int rounded = ((raw % 360) + 360) % 360;
  if (rounded >= 315 || rounded < 45) {
    return 0;
  }
  if (rounded < 135) {
    return 90;
  }
  if (rounded < 225) {
    return 180;
  }
  return 270;
}

bool use_r90_map(const app::AppState& state) {
  return normalize_rotation_deg(state.settings.rotation_deg) == 90;
}

void lp_px(std::vector<uint8_t>& image, const int cx, const int cy, const bool r90) {
  if (cx < 0 || cx >= kPW || cy < 0 || cy >= kPH) {
    return;
  }
  if (r90) {
    set_black_pixel(image, cy, 479 - cx);
  } else {
    set_black_pixel(image, 799 - cy, cx);
  }
}

void lp_clr(std::vector<uint8_t>& image, const int cx, const int cy, const bool r90) {
  if (cx < 0 || cx >= kPW || cy < 0 || cy >= kPH) {
    return;
  }
  if (r90) {
    clear_pixel(image, cy, 479 - cx);
  } else {
    clear_pixel(image, 799 - cy, cx);
  }
}

void lp_fill(
    std::vector<uint8_t>& image,
    const int x0,
    const int y0,
    const int x1,
    const int y1,
    const bool r90) {
  for (int y = y0; y < y1; ++y) {
    for (int x = x0; x < x1; ++x) {
      lp_px(image, x, y, r90);
    }
  }
}

std::size_t lp_gi(const char ch) {
  const unsigned char code = static_cast<unsigned char>(ch);
  if (code < 32 || code > 126) {
    return static_cast<std::size_t>('?' - 32);
  }
  return static_cast<std::size_t>(code - 32);
}

const BitmapFont& list_font_for_scale_normal(const int scale) {
  using namespace platform::panel_font_assets;
  if (scale <= 1) {
    return kFontJetBold13;
  }
  if (scale == 2) {
    return kFontInterMedium18;
  }
  return kFontInterBlack29;
}

const BitmapFont& list_font_for_scale_inverted(const int scale) {
  using namespace platform::panel_font_assets;
  if (scale <= 1) {
    return kFontJetBold13;
  }
  if (scale == 2) {
    return kFontInterBold17;
  }
  return kFontInterBlack29;
}

void lp_glyph(
    std::vector<uint8_t>& image,
    const int x,
    const int y,
    const char ch,
    const BitmapFont& font,
    const bool r90,
    const bool black) {
  const Glyph& glyph = font.glyphs[lp_gi(ch)];
  if (!glyph.width || !glyph.height) {
    return;
  }
  const int row_bytes = (glyph.width + 7) / 8;
  const std::uint8_t* bitmap = font.bitmap + glyph.bitmap_offset;
  for (int row = 0; row < glyph.height; ++row) {
    for (int col = 0; col < glyph.width; ++col) {
      if ((bitmap[row * row_bytes + (col / 8)] & (0x80U >> (col % 8))) == 0) {
        continue;
      }
      const int px = x + glyph.left + col;
      const int py = y + static_cast<int>(glyph.top) + row;
      if (black) {
        lp_px(image, px, py, r90);
      } else {
        lp_clr(image, px, py, r90);
      }
    }
  }
}

void lp_text_line(
    std::vector<uint8_t>& image,
    const int x,
    const int y,
    const std::string& text,
    const int scale,
    const int max_chars,
    const bool r90) {
  const BitmapFont& font = list_font_for_scale_normal(scale);
  int cx = x;
  int drawn = 0;
  for (const char ch : text) {
    if (max_chars > 0 && drawn >= max_chars) {
      break;
    }
    lp_glyph(image, cx, y, ch, font, r90, true);
    cx += font.glyphs[lp_gi(ch)].advance;
    ++drawn;
  }
}

void lp_text_line_inverted(
    std::vector<uint8_t>& image,
    const int x,
    const int y,
    const std::string& text,
    const int scale,
    const int max_chars,
    const bool r90) {
  const BitmapFont& font = list_font_for_scale_inverted(scale);
  int cx = x;
  int drawn = 0;
  for (const char ch : text) {
    if (max_chars > 0 && drawn >= max_chars) {
      break;
    }
    lp_glyph(image, cx, y, ch, font, r90, false);
    cx += font.glyphs[lp_gi(ch)].advance;
    ++drawn;
  }
}

int window_start(const int total, const int slots, const int selected) {
  if (total <= slots || selected < 0) {
    return 0;
  }
  return std::max(0, std::min(selected - (slots / 2), total - slots));
}

std::string normalize_row_title(const std::string& raw) {
  const std::string trimmed = trim_copy(raw);
  if (trimmed.empty()) {
    return "(untitled)";
  }
  return trimmed;
}

std::string uppercase_ascii(std::string text) {
  for (char& ch : text) {
    ch = static_cast<char>(std::toupper(static_cast<unsigned char>(ch)));
  }
  return text;
}

std::string reminder_right_meta(const ListRow& row, const UiStrings& s) {
  if (row.completed) {
    return s.list_done;
  }
  const std::string right = trim_copy(row.right);
  if (right.empty()) {
    return s.list_todo;
  }
  return uppercase_ascii(right);
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
    rows.push_back(ListRow{normalize_row_title(items[i]), done, {}});
  }
  return rows;
}

std::vector<ListRow> build_reminder_rows(const app::AppState& state) {
  std::vector<ListRow> rows;
  const auto& items = state.dashboard.reminder_items;
  const auto& completed = state.dashboard.reminder_completed;
  const auto& meta = state.dashboard.reminder_meta;
  const auto& hidden = state.home.hidden_reminder_indices;
  rows.reserve(items.size());
  for (std::size_t i = 0; i < items.size(); ++i) {
    if (std::find(hidden.begin(), hidden.end(), static_cast<int>(i)) != hidden.end()) {
      continue;
    }
    const bool done = i < completed.size() && completed[i];
    std::string right{};
    if (i < meta.size()) {
      right = meta[i].right;
    }
    rows.push_back(ListRow{normalize_row_title(items[i]), done, right});
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
    const bool show_meta,
    const bool r90,
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
    const auto& row = rows[static_cast<std::size_t>(row_index)];
    const bool selected = row_index == selected_index;
    const int ry0 = y + 1;
    const int ry1 = y + row_h - 2;
    if (selected) {
      lp_fill(image, x0, ry0, x1, ry1, r90);
    } else {
      lp_fill(image, x0 + 6, ry1, x1, ry1 + 1, r90);
    }

    const std::string prefix = row.completed ? "[x] " : "[ ] ";
    if (show_meta) {
      const std::string right_meta = reminder_right_meta(row, s);
      const std::string right_fit =
          truncate_text_px(right_meta, 1, std::max(52, ((x1 - x0) * 26) / 100));
      const int right_w = text_width_px(right_fit, 1);
      const int right_x = std::max(x0 + 8, x1 - right_w - 8);
      if (selected) {
        lp_text_line_inverted(image, right_x, y + 11, right_fit, 1, 0, r90);
      } else {
        lp_text_line(image, right_x, y + 11, right_fit, 1, 0, r90);
      }
      const int title_max_w = std::max(80, right_x - x0 - 14);
      const std::string title = truncate_text_px(prefix + row.title, 2, title_max_w);
      if (selected) {
        lp_text_line_inverted(image, x0 + 8, y + 10, title, 2, 0, r90);
      } else {
        lp_text_line(image, x0 + 8, y + 10, title, 2, 0, r90);
      }
    } else {
      const std::string line =
          truncate_text_px(prefix + row.title, 2, std::max(70, x1 - x0 - 20));
      if (selected) {
        lp_text_line_inverted(image, x0 + 8, y + 10, line, 2, 0, r90);
      } else {
        lp_text_line(image, x0 + 8, y + 10, line, 2, 0, r90);
      }
    }
    y += row_h;
  }
  if (rows.empty()) {
    lp_text_line(image, x0 + 8, y0 + 10, s.list_no_items, 1, 12, r90);
  }
}

}  // namespace

std::vector<uint8_t> render_list_portrait_bitmap(const app::AppState& state) {
  using platform::kPanelBufferSize;

  const auto& s = get_ui_strings(state.device_language);
  std::vector<uint8_t> image(kPanelBufferSize, 0xFF);
  const bool r90 = use_r90_map(state);

  const std::vector<ListRow> inventory = build_inventory_rows(state);
  const std::vector<ListRow> reminders = build_reminder_rows(state);

  const int left = 24;
  const int right = kPW - 24;
  lp_text_line(image, left, 16, s.list_title, 3, 16, r90);
  const std::string hint_fit =
      truncate_text_px(s.list_hint, 1, std::max(80, right - left));
  const int hint_w = text_width_px(hint_fit, 1);
  lp_text_line(image, std::max(left, right - hint_w), 52, hint_fit, 1, 0, r90);
  lp_fill(image, left, 68, right, 70, r90);

  const int content_top = 104;
  const int footer_y = kPH - 40;
  const int content_bottom = footer_y - 6;
  const int split_y_raw = content_top + ((content_bottom - content_top) / 3);
  const int split_y = std::max(content_top + 72, std::min(content_bottom - 120, split_y_raw));
  lp_fill(image, left, split_y, right, split_y + 2, r90);

  lp_text_line(
      image,
      left + 2,
      content_top + 2,
      truncate_text_px(std::string(s.list_inventory) + " " + std::to_string(inventory.size()), 1, std::max(60, right - left - 8)),
      1,
      0,
      r90);
  lp_text_line(
      image,
      left + 2,
      split_y + 2,
      truncate_text_px(std::string(s.list_reminder) + " " + std::to_string(reminders.size()), 1, std::max(60, right - left - 8)),
      1,
      0,
      r90);

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

  draw_rows(image, inventory, left, right, inv_list_top, inv_list_bottom, selected_inventory, false, r90, s);
  draw_rows(image, reminders, left, right, rem_list_top, rem_list_bottom, selected_reminder, true, r90, s);

  const std::string footer =
      truncate_text_px(s.list_footer, 1, std::max(80, right - left));
  lp_text_line(image, left, footer_y, footer, 1, 0, r90);
  return image;
}

}  // namespace fridge_ink::ui
