#include "ui/screens/menu_screen.hpp"

#include "platform/panel_config.hpp"
#include "ui/draw.hpp"

#include <array>
#include <string>
#include <vector>

namespace fridge_ink::ui {

std::vector<uint8_t> render_menu_bitmap(const app::AppState& state) {
  using platform::kPanelBufferSize;
  using platform::kPanelWidth;

  constexpr std::array<const char*, 5> kMenuItems = {
      "MEMO",
      "LIST",
      "TIMER",
      "CALENDAR",
      "SETTINGS",
  };

  const std::size_t focus = state.menu.focused_index % kMenuItems.size();

  std::vector<uint8_t> image(kPanelBufferSize, 0xFF);
  draw_outline_rect(image, 12, 12, kPanelWidth - 12, 468, 3);
  draw_text_line(image, 40, 28, "MENU", 3, 14);
  draw_text_line(image, 40, 64, "Issue #52 placeholder navigation hub", 1, 48);

  const int item_x0 = 54;
  const int item_x1 = kPanelWidth - 54;
  const int item_h = 48;
  const int item_gap = 12;
  const int top = 112;
  for (std::size_t i = 0; i < kMenuItems.size(); ++i) {
    const int y0 = top + static_cast<int>(i) * (item_h + item_gap);
    const int y1 = y0 + item_h;
    if (i == focus) {
      fill_black_rect(image, item_x0, y0, item_x1, y1);
      draw_outline_rect(image, item_x0 - 3, y0 - 3, item_x1 + 3, y1 + 3, 3);
      draw_text_centered_inverted(image, item_x0 + 12, item_x1 - 12, y0 + 14, kMenuItems[i], 2, 24);
    } else {
      draw_outline_rect(image, item_x0, y0, item_x1, y1, 2);
      draw_text_centered(image, item_x0 + 12, item_x1 - 12, y0 + 14, kMenuItems[i], 2, 24);
    }
  }

  draw_outline_rect(image, 40, 418, kPanelWidth - 40, 456, 2);
  draw_text_centered(
      image, 56, kPanelWidth - 56, 430,
      "Rotate to browse. Click to open the selected screen.", 1, 54);
  return image;
}

}  // namespace fridge_ink::ui
