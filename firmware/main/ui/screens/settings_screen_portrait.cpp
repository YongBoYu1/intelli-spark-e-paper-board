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

std::vector<uint8_t> render_settings_portrait_bitmap(const app::AppState& state) {
  using platform::kPanelBufferSize;
  using platform::kPanelWidth;

  std::vector<uint8_t> image(kPanelBufferSize, 0xFF);
  const auto rows = setting_rows(state);

  const int card_x0 = 152;
  const int card_x1 = kPanelWidth - 152;
  const int card_y0 = 22;
  const int card_y1 = 458;
  draw_rounded_rect_stroke(image, card_x0, card_y0, card_x1, card_y1, 18, 2);

  draw_text_centered(image, card_x0, card_x1, 40, "SETTINGS", 3, 14);
  draw_text_centered(image, card_x0, card_x1, 76, "PORTRAIT LAYOUT PREVIEW", 1, 28);
  draw_outline_rect(image, card_x0 + 16, 98, card_x1 - 16, 100, 1);

  const int row_x0 = card_x0 + 20;
  const int row_x1 = card_x1 - 20;
  const int row_h = 66;
  const int row_gap = 14;
  const int top = 122;
  const int radius = 10;

  for (std::size_t i = 0; i < rows.size(); ++i) {
    const int y0 = top + static_cast<int>(i) * (row_h + row_gap);
    const int y1 = y0 + row_h;
    const bool focused = i == 0;
    if (focused) {
      fill_rounded_rect(image, row_x0, y0, row_x1, y1, radius, true);
      draw_rounded_rect_stroke(image, row_x0, y0, row_x1, y1, radius, 2);
      draw_text_line_inverted(image, row_x0 + 14, y0 + 18, rows[i].label, 1, 28);
      draw_text_line_inverted(
          image,
          row_x0 + 14,
          y0 + 36,
          truncate_text_px(rows[i].value, 1, (row_x1 - row_x0) - 28),
          1,
          30);
    } else {
      draw_rounded_rect_stroke(image, row_x0, y0, row_x1, y1, radius, 2);
      draw_text_line(image, row_x0 + 14, y0 + 18, rows[i].label, 1, 28);
      draw_text_line(
          image,
          row_x0 + 14,
          y0 + 36,
          truncate_text_px(rows[i].value, 1, (row_x1 - row_x0) - 28),
          1,
          30);
    }
  }

  draw_outline_rect(image, card_x0 + 16, 420, card_x1 - 16, 422, 1);
  draw_text_centered(image, card_x0, card_x1, 432, "HOLD TO RETURN HOME", 1, 28);
  return image;
}

}  // namespace fridge_ink::ui
