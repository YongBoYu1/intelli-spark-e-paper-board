#include "ui/screens/detail_screen_scaffold.hpp"

#include "platform/panel_config.hpp"
#include "ui/draw.hpp"

namespace fridge_ink::ui {

std::vector<uint8_t> render_detail_scaffold_bitmap(
    const std::string& title,
    const std::string& line_one,
    const std::string& line_two,
    const std::string& line_three,
    const std::string& orientation_label) {
  using platform::kPanelBufferSize;
  using platform::kPanelWidth;

  std::vector<uint8_t> image(kPanelBufferSize, 0xFF);
  draw_outline_rect(image, 12, 12, kPanelWidth - 12, 468, 3);
  draw_text_line(image, 40, 30, title, 3, 26);
  draw_text_line(image, 40, 72, "Issue #52 page migration scaffold", 1, 36);
  draw_text_line(image, kPanelWidth - 250, 30, orientation_label, 1, 24);

  draw_outline_rect(image, 40, 124, kPanelWidth - 40, 344, 2);
  draw_text_wrapped(image, 60, 152, 640, line_one, 2, 2);
  draw_text_wrapped(image, 60, 212, 640, line_two, 2, 2);
  draw_text_wrapped(image, 60, 272, 640, line_three, 2, 2);

  fill_black_rect(image, 204, 388, kPanelWidth - 204, 438);
  draw_outline_rect(image, 201, 385, kPanelWidth - 201, 441, 3);
  draw_text_centered_inverted(
      image, 220, kPanelWidth - 220, 404, "CLICK TO RETURN MENU", 1, 28);
  return image;
}

}  // namespace fridge_ink::ui
