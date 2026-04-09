#include "ui/screens/calendar_screen.hpp"

#include "app/calendar_runtime.hpp"
#include "platform/panel_config.hpp"
#include "ui/draw.hpp"
#include "ui/panel_font_assets_generated.hpp"

#include <algorithm>
#include <array>
#include <cctype>
#include <cstdint>
#include <string>
#include <vector>

namespace fridge_ink::ui {
namespace {

using platform::kPanelBufferSize;
using platform::panel_font_assets::BitmapFont;
using platform::panel_font_assets::Glyph;

constexpr int kPW = 480;
constexpr int kPH = 800;

struct AgendaRow {
  bool reminder{false};
  bool completed{false};
  std::string when{};
  std::string title{};
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

void cp_px(std::vector<uint8_t>& image, const int cx, const int cy, const bool r90) {
  if (cx < 0 || cx >= kPW || cy < 0 || cy >= kPH) {
    return;
  }
  if (r90) {
    set_black_pixel(image, cy, 479 - cx);
  } else {
    set_black_pixel(image, 799 - cy, cx);
  }
}

void cp_clr(std::vector<uint8_t>& image, const int cx, const int cy, const bool r90) {
  if (cx < 0 || cx >= kPW || cy < 0 || cy >= kPH) {
    return;
  }
  if (r90) {
    clear_pixel(image, cy, 479 - cx);
  } else {
    clear_pixel(image, 799 - cy, cx);
  }
}

void cp_fill(
    std::vector<uint8_t>& image,
    const int x0,
    const int y0,
    const int x1,
    const int y1,
    const bool r90) {
  for (int y = y0; y < y1; ++y) {
    for (int x = x0; x < x1; ++x) {
      cp_px(image, x, y, r90);
    }
  }
}

void cp_fill_white(
    std::vector<uint8_t>& image,
    const int x0,
    const int y0,
    const int x1,
    const int y1,
    const bool r90) {
  for (int y = y0; y < y1; ++y) {
    for (int x = x0; x < x1; ++x) {
      cp_clr(image, x, y, r90);
    }
  }
}

void cp_outline(
    std::vector<uint8_t>& image,
    const int x0,
    const int y0,
    const int x1,
    const int y1,
    const int thickness,
    const bool r90) {
  const int t = std::max(1, thickness);
  cp_fill(image, x0, y0, x1, y0 + t, r90);
  cp_fill(image, x0, y1 - t, x1, y1, r90);
  cp_fill(image, x0, y0, x0 + t, y1, r90);
  cp_fill(image, x1 - t, y0, x1, y1, r90);
}

std::size_t cp_gi(const char ch) {
  const unsigned char code = static_cast<unsigned char>(ch);
  if (code < 32 || code > 126) {
    return static_cast<std::size_t>('?' - 32);
  }
  return static_cast<std::size_t>(code - 32);
}

const BitmapFont& cp_font_for_scale_normal(const int scale) {
  using namespace platform::panel_font_assets;
  if (scale <= 1) {
    return kFontJetBold13;
  }
  if (scale == 2) {
    return kFontInterMedium18;
  }
  return kFontInterBlack29;
}

const BitmapFont& cp_font_for_scale_inverted(const int scale) {
  using namespace platform::panel_font_assets;
  if (scale <= 1) {
    return kFontJetBold13;
  }
  if (scale == 2) {
    return kFontInterBold17;
  }
  return kFontInterBlack29;
}

int cp_adv(const char ch, const BitmapFont& font) {
  return font.glyphs[cp_gi(ch)].advance;
}

int cp_text_width(const std::string& text, const BitmapFont& font) {
  int width = 0;
  for (const char ch : text) {
    width += cp_adv(ch, font);
  }
  return width;
}

void cp_glyph(
    std::vector<uint8_t>& image,
    const int x,
    const int y,
    const char ch,
    const BitmapFont& font,
    const bool r90,
    const bool black) {
  const Glyph& glyph = font.glyphs[cp_gi(ch)];
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
        cp_px(image, px, py, r90);
      } else {
        cp_clr(image, px, py, r90);
      }
    }
  }
}

void cp_text_line(
    std::vector<uint8_t>& image,
    const int x,
    const int y,
    const std::string& text,
    const int scale,
    const int max_chars,
    const bool r90) {
  const BitmapFont& font = cp_font_for_scale_normal(scale);
  int cx = x;
  int drawn = 0;
  for (const char ch : text) {
    if (max_chars > 0 && drawn >= max_chars) {
      break;
    }
    cp_glyph(image, cx, y, ch, font, r90, true);
    cx += cp_adv(ch, font);
    ++drawn;
  }
}

void cp_text_line_inverted(
    std::vector<uint8_t>& image,
    const int x,
    const int y,
    const std::string& text,
    const int scale,
    const int max_chars,
    const bool r90) {
  const BitmapFont& font = cp_font_for_scale_inverted(scale);
  int cx = x;
  int drawn = 0;
  for (const char ch : text) {
    if (max_chars > 0 && drawn >= max_chars) {
      break;
    }
    cp_glyph(image, cx, y, ch, font, r90, false);
    cx += cp_adv(ch, font);
    ++drawn;
  }
}

void cp_centered(
    std::vector<uint8_t>& image,
    const int x0,
    const int x1,
    const int y,
    const std::string& text,
    const int scale,
    const int max_chars,
    const bool r90) {
  const BitmapFont& font = cp_font_for_scale_normal(scale);
  const int width = cp_text_width(text, font);
  const int cx = x0 + ((x1 - x0 - width) / 2);
  cp_text_line(image, cx, y, text, scale, max_chars, r90);
}

void cp_centered_inverted(
    std::vector<uint8_t>& image,
    const int x0,
    const int x1,
    const int y,
    const std::string& text,
    const int scale,
    const int max_chars,
    const bool r90) {
  const BitmapFont& font = cp_font_for_scale_inverted(scale);
  const int width = cp_text_width(text, font);
  const int cx = x0 + ((x1 - x0 - width) / 2);
  cp_text_line_inverted(image, cx, y, text, scale, max_chars, r90);
}

std::string cp_truncate(const std::string& text, const int scale, const int max_width_px) {
  const BitmapFont& font = cp_font_for_scale_normal(scale);
  const int max_px = std::max(0, max_width_px);
  if (max_px <= 0) {
    return {};
  }
  if (cp_text_width(text, font) <= max_px) {
    return text;
  }
  const std::string ellipsis = "...";
  const int ellipsis_w = cp_text_width(ellipsis, font);
  std::string out;
  int width = 0;
  for (const char ch : text) {
    const int adv = cp_adv(ch, font);
    if (width + adv + ellipsis_w > max_px) {
      break;
    }
    out.push_back(ch);
    width += adv;
  }
  if (out.empty()) {
    return cp_text_width(ellipsis, font) <= max_px ? ellipsis : std::string();
  }
  return out + ellipsis;
}

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

std::string normalized_row_title(const std::string& raw) {
  const std::string trimmed = trim_copy(raw);
  if (trimmed.empty()) {
    return "(untitled)";
  }
  return trimmed;
}

std::vector<AgendaRow> build_agenda_rows(
    const app::AppState& state,
    const app::calendar_runtime::AgendaSelection& selection) {
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
        event.when.empty() ? "EVENT" : event.when,
        normalized_row_title(event.title),
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
    rows.push_back(AgendaRow{
        true,
        completed,
        right_text,
        normalized_row_title(state.dashboard.reminder_items[static_cast<std::size_t>(reminder_index)]),
    });
  }

  return rows;
}

void draw_event_marker(
    std::vector<uint8_t>& image,
    const int x,
    const int y,
    const bool selected,
    const bool r90) {
  if (selected) {
    cp_fill_white(image, x, y, x + 4, y + 4, r90);
    return;
  }
  cp_fill(image, x, y, x + 4, y + 4, r90);
}

void draw_reminder_marker(
    std::vector<uint8_t>& image,
    const int x,
    const int y,
    const bool selected,
    const bool r90) {
  if (selected) {
    cp_fill_white(image, x, y, x + 6, y + 6, r90);
    cp_fill(image, x + 1, y + 1, x + 5, y + 5, r90);
    return;
  }
  cp_outline(image, x, y, x + 6, y + 6, 1, r90);
}

void draw_month_grid(
    std::vector<uint8_t>& image,
    const app::AppState& state,
    const app::calendar_runtime::DateValue& base_date,
    const app::calendar_runtime::DateValue& cursor,
    const int x0,
    const int y0,
    const int x1,
    const int y1,
    const int week_y,
    const bool r90) {
  static constexpr std::array<const char*, 7> kWeek = {
      "S", "M", "T", "W", "T", "F", "S"};
  const int month_days = app::calendar_runtime::days_in_month(cursor.year, cursor.month);
  const int offset = app::calendar_runtime::weekday_sunday0(
      app::calendar_runtime::DateValue{cursor.year, cursor.month, 1});
  const int grid_w = std::max(1, x1 - x0);
  const int grid_h = std::max(1, y1 - y0);
  const int cell_w = std::max(24, grid_w / 7);
  const int cell_h = std::max(24, grid_h / 6);
  const int draw_w = cell_w * 7;
  const int draw_h = cell_h * 6;
  const int gx = x0 + (grid_w - draw_w) / 2;
  const int gy = y0 + (grid_h - draw_h) / 2;

  for (int i = 0; i < 7; ++i) {
    const int wx0 = gx + i * cell_w;
    const int wx1 = wx0 + cell_w - 2;
    cp_centered(image, wx0, wx1, week_y, kWeek[static_cast<std::size_t>(i)], 2, 1, r90);
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
    const bool today = day == base_date.day &&
                       cursor.month == base_date.month &&
                       cursor.year == base_date.year;

    cp_outline(image, cx0, cy0, cx1, cy1, 1, r90);
    if (selected) {
      cp_fill(image, cx0 + 1, cy0 + 1, cx1 - 1, cy1 - 1, r90);
    } else if (today) {
      cp_outline(image, cx0 + 2, cy0 + 2, cx1 - 2, cy1 - 2, 1, r90);
    }

    const int text_y = cy0 + ((cy1 - cy0) / 2) - 6;
    if (selected) {
      cp_centered_inverted(image, cx0, cx1, text_y, std::to_string(day), 1, 2, r90);
    } else {
      cp_centered(image, cx0, cx1, text_y, std::to_string(day), 1, 2, r90);
    }

    const auto date = app::calendar_runtime::DateValue{cursor.year, cursor.month, day};
    const auto items = app::calendar_runtime::agenda_selection_for_date(state, date, base_date);
    const bool has_event = !items.event_indices.empty();
    const bool has_reminder = !items.reminder_indices.empty();
    if (!has_event && !has_reminder) {
      continue;
    }

    const int marker_y = cy1 - 8;
    const int center = cx0 + ((cx1 - cx0) / 2);
    if (has_event && has_reminder) {
      draw_event_marker(image, center - 6, marker_y, selected, r90);
      draw_reminder_marker(image, center + 2, marker_y - 1, selected, r90);
    } else if (has_event) {
      draw_event_marker(image, center - 2, marker_y, selected, r90);
    } else {
      draw_reminder_marker(image, center - 3, marker_y - 1, selected, r90);
    }
  }
}

std::string reminder_meta_label(const AgendaRow& row) {
  const std::string right = trim_copy(row.when);
  if (!right.empty()) {
    return "DUE: " + upper_copy(right);
  }
  return row.completed ? "DONE" : "TASK";
}

}  // namespace

std::vector<uint8_t> render_calendar_portrait_bitmap(const app::AppState& state) {
  std::vector<uint8_t> image(kPanelBufferSize, 0xFF);
  const bool r90 = use_r90_map(state);

  const auto base_date = app::calendar_runtime::today_local_date(state);
  const auto cursor = app::calendar_runtime::cursor_date(state, base_date);
  const std::string mode = normalized_mode(state.calendar.mode);
  const bool agenda_mode = mode == "agenda";
  const auto selection = app::calendar_runtime::agenda_selection_for_cursor(state, base_date);
  const std::vector<AgendaRow> rows = build_agenda_rows(state, selection);
  const int selected_index = agenda_mode
                                 ? std::max(
                                       0,
                                       std::min(
                                           state.calendar.selected_index,
                                           std::max(0, static_cast<int>(rows.size()) - 1)))
                                 : 0;

  const int split_y = std::max(260, std::min(kPH - 220, kPH / 2));
  // Edge-to-edge frame: keep border on the panel boundary instead of wrapping
  // the content area.
  cp_outline(image, 0, 0, kPW, kPH, 2, r90);
  cp_fill(image, 0, split_y, kPW, split_y + 2, r90);

  const std::string month_name = app::calendar_runtime::month_name_upper(cursor.month);
  const std::string weekday = app::calendar_runtime::weekday_name_upper(
      app::calendar_runtime::weekday_sunday0(cursor));
  const std::string date_title = app::calendar_runtime::date_title_for_date(cursor);

  const int top_left = 20;
  cp_text_line(image, top_left, 20, cp_truncate(month_name, 3, 360), 3, 18, r90);
  cp_text_line(image, top_left + 2, 62, std::to_string(cursor.year), 1, 8, r90);

  const int grid_left = 20;
  const int grid_right = kPW - 20;
  const int week_row_y = 100;
  const int grid_top = 124;
  const int grid_bottom = split_y - 12;
  draw_month_grid(
      image,
      state,
      base_date,
      cursor,
      grid_left,
      grid_top,
      grid_right,
      grid_bottom,
      week_row_y,
      r90);

  const int header_y = split_y + 12;
  cp_text_line(image, 20, header_y, weekday, 2, 12, r90);
  cp_text_line(image, 20, header_y + 24, cp_truncate(date_title, 3, 340), 3, 18, r90);
  cp_fill(image, 20, header_y + 54, kPW - 20, header_y + 56, r90);

  const int list_x0 = 18;
  const int list_x1 = kPW - 18;
  const int list_top = header_y + 64;
  const int footer_y = kPH - 30;
  const int list_bottom = footer_y - 6;
  const int row_h = 56;
  const int row_gap = 8;
  const int slots = std::max(1, (list_bottom - list_top + row_gap) / (row_h + row_gap));

  if (rows.empty()) {
    const int empty_top = list_top + ((list_bottom - list_top) / 2) - 20;
    cp_centered(image, list_x0, list_x1, empty_top, "NO EVENTS", 2, 18, r90);
    cp_centered(image, list_x0, list_x1, empty_top + 22, "VOICE CAN ADD REMINDERS AND MEMOS", 1, 40, r90);
  } else {
    const int start = window_start(static_cast<int>(rows.size()), slots, selected_index);
    const int visible_count = std::min(slots, static_cast<int>(rows.size()) - start);
    int y = list_top;
    for (int i = 0; i < visible_count; ++i) {
      const int row_index = start + i;
      if (row_index < 0 || row_index >= static_cast<int>(rows.size())) {
        break;
      }
      const auto& row = rows[static_cast<std::size_t>(row_index)];
      const bool selected = agenda_mode && row_index == selected_index;
      if (selected) {
        cp_fill(image, list_x0, y, list_x1, y + row_h, r90);
      } else {
        cp_outline(image, list_x0, y, list_x1, y + row_h, 1, r90);
      }

      const std::string when_base = row.when.empty() ? (row.reminder ? "REMINDER" : "EVENT") : row.when;
      const std::string when_text = cp_truncate(upper_copy(when_base), 1, std::max(44, (list_x1 - list_x0) / 3));
      const int when_width = cp_text_width(when_text, cp_font_for_scale_normal(1));
      const int when_x = list_x1 - 10 - when_width;
      if (selected) {
        cp_text_line_inverted(image, when_x, y + 10, when_text, 1, 18, r90);
      } else {
        cp_text_line(image, when_x, y + 10, when_text, 1, 18, r90);
      }

      const int title_max = std::max(96, when_x - list_x0 - 16);
      std::string title_prefix;
      std::string detail_line;
      if (row.reminder) {
        title_prefix = row.completed ? "[x] " : "[ ] ";
        detail_line = reminder_meta_label(row);
      } else {
        detail_line = "EVENT";
      }
      const std::string title = cp_truncate(title_prefix + row.title, 2, title_max);
      const std::string detail = cp_truncate(detail_line, 1, std::max(80, list_x1 - list_x0 - 20));
      if (selected) {
        cp_text_line_inverted(image, list_x0 + 10, y + 10, title, 2, 32, r90);
        cp_text_line_inverted(image, list_x0 + 10, y + 34, detail, 1, 36, r90);
      } else {
        cp_text_line(image, list_x0 + 10, y + 10, title, 2, 32, r90);
        cp_text_line(image, list_x0 + 10, y + 34, detail, 1, 36, r90);
      }

      y += row_h + row_gap;
    }

    const int hidden = std::max(0, static_cast<int>(rows.size()) - (start + visible_count));
    if (hidden > 0) {
      const std::string more = "+" + std::to_string(hidden) + " MORE";
      const int more_width = cp_text_width(more, cp_font_for_scale_normal(1));
      cp_text_line(image, list_x1 - more_width - 2, list_bottom - 12, more, 1, 12, r90);
    }
  }

  std::string footer = "ROTATE=DATE  |  CLICK=AGENDA  |  HOLD=HOME";
  if (agenda_mode) {
    footer = rows.empty()
                 ? "ROTATE=DATE  |  CLICK=DATE  |  HOLD=HOME"
                 : "ROTATE=ITEM  |  CLICK=TOGGLE  |  HOLD=HOME";
  }
  footer = cp_truncate(upper_copy(footer), 1, kPW - 24);
  cp_text_line(image, 12, footer_y, footer, 1, 64, r90);

  return image;
}

}  // namespace fridge_ink::ui
