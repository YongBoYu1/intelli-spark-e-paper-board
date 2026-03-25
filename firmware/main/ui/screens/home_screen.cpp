#include "ui/screens/home_screen.hpp"

#include "platform/panel_config.hpp"
#include "ui/draw.hpp"

#include <string>
#include <vector>

namespace fridge_ink::ui {

std::vector<uint8_t> render_home_bitmap(const app::AppState& state) {
  using platform::kPanelWidth;
  using platform::kPanelHeight;
  using platform::kPanelBufferSize;

  std::vector<uint8_t> image(kPanelBufferSize, 0xFF);  // white (1=white, 0=black)
  draw_outline_rect(image, 12, 12, kPanelWidth - 12, kPanelHeight - 12, 3);
  draw_text_line(image, 40, 30, "HOME KITCHEN", 3, 28);

  const std::string location = "Location: " + state.dashboard.location;
  const std::string battery =
      "Battery: " + std::to_string(state.dashboard.battery_percent) + "%";
  const std::string reminders =
      "Reminders: " + std::to_string(state.dashboard.reminder_count);
  const std::string focus =
      "Focus slot: " + std::to_string(state.home.focused_index);

  // Left panel
  draw_outline_rect(image, 40, 94, 386, 362, 2);
  draw_text_line(image, 56, 114, "LEFT PANEL", 2, 18);
  draw_outline_rect(image, 56, 148, 370, 216, 2);
  draw_text_wrapped(image, 68, 166, 290, location, 2, 2);
  draw_outline_rect(image, 56, 228, 370, 296, 2);
  draw_text_wrapped(image, 68, 246, 290, battery, 2, 2);

  // Right panel
  draw_outline_rect(image, 414, 94, kPanelWidth - 40, 362, 2);
  draw_text_line(image, 430, 114, "TASK PANEL", 2, 18);
  draw_outline_rect(image, 430, 148, kPanelWidth - 56, 216, 2);
  draw_text_wrapped(image, 442, 166, 290, reminders, 2, 2);
  draw_outline_rect(image, 430, 228, kPanelWidth - 56, 296, 2);
  draw_text_wrapped(image, 442, 246, 290, focus, 2, 2);

  // Footer
  draw_outline_rect(image, 40, 388, kPanelWidth - 40, 446, 3);
  const std::string foot = "State-driven boot path with no external JSON";
  draw_text_centered(image, 56, kPanelWidth - 56, 409,
                     trunc_text(foot, 52), 2, 52);

  return image;
}

}  // namespace fridge_ink::ui
