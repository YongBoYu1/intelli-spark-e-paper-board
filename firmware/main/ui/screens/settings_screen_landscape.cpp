#include "ui/screens/settings_screen.hpp"

#include "platform/panel_config.hpp"
#include "ui/draw.hpp"

#include <algorithm>
#include <array>
#include <string>

namespace fridge_ink::ui {
namespace {

struct SettingRowView {
  std::string label;
  std::string value;
};

std::string upper_copy(const std::string& text) {
  std::string out = text;
  for (char& ch : out) {
    if (ch >= 'a' && ch <= 'z') {
      ch = static_cast<char>(ch - ('a' - 'A'));
    }
  }
  return out;
}

std::array<SettingRowView, 4> setting_rows(const app::AppState& state) {
  return {{
      {"PARTIAL REFRESH", state.settings.partial_refresh_enabled ? "ON" : "OFF"},
      {"REFRESH MODE", upper_copy(state.settings.refresh_mode)},
      {"FULL REFRESH", "EVERY " + std::to_string(std::max(1, state.settings.full_refresh_every)) + " PARTIALS"},
      {"AUTO SYNC", state.settings.auto_sync_enabled ? "ON" : "OFF"},
  }};
}

}  // namespace

std::vector<uint8_t> render_settings_landscape_bitmap(const app::AppState& state) {
  using platform::kPanelBufferSize;
  using platform::kPanelWidth;

  std::vector<uint8_t> image(kPanelBufferSize, 0xFF);
  const auto rows = setting_rows(state);

  draw_text_line(image, 24, 20, "SETTINGS", 3, 14);
  draw_text_line(image, 520, 50, "ROTATE SELECT  CLICK APPLY  HOLD HOME", 1, 40);
  draw_outline_rect(image, 24, 78, kPanelWidth - 24, 80, 1);

  const int x0 = 24;
  const int x1 = kPanelWidth - 24;
  const int top = 96;
  const int row_h = 74;
  const int row_gap = 8;
  const int radius = 12;

  for (std::size_t i = 0; i < rows.size(); ++i) {
    const int y0 = top + static_cast<int>(i) * (row_h + row_gap);
    const int y1 = y0 + row_h;
    const bool focused = i == 0;
    if (focused) {
      fill_rounded_rect(image, x0, y0, x1, y1, radius, true);
      draw_rounded_rect_stroke(image, x0, y0, x1, y1, radius, 2);
      draw_text_line_inverted(image, x0 + 20, y0 + 24, rows[i].label, 2, 22);
      draw_text_line_inverted(
          image,
          x1 - 220,
          y0 + 24,
          truncate_text_px(rows[i].value, 2, 200),
          2,
          14);
    } else {
      draw_rounded_rect_stroke(image, x0, y0, x1, y1, radius, 2);
      draw_text_line(image, x0 + 20, y0 + 24, rows[i].label, 2, 22);
      draw_text_line(
          image,
          x1 - 220,
          y0 + 24,
          truncate_text_px(rows[i].value, 2, 200),
          2,
          14);
    }
  }

  draw_outline_rect(image, 24, 444, kPanelWidth - 24, 446, 1);
  draw_text_line(image, 24, 456, "STATUS READY", 1, 24);
  draw_text_line(image, 604, 456, "LANDSCAPE", 1, 16);
  return image;
}

}  // namespace fridge_ink::ui
