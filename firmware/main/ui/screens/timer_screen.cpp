#include "ui/screens/timer_screen.hpp"

namespace fridge_ink::ui {

std::vector<uint8_t> render_timer_bitmap(const app::AppState& state) {
  // G0/G1: Route to portrait renderer when device is rotated 90° or 270°.
  // Python parity: render_timer() uses image.size to adapt layout — portrait
  // semantic canvas is 480×800, landscape is 800×480.
  const int deg = ((state.settings.rotation_deg % 360) + 360) % 360;
  const bool is_portrait = (deg >= 45 && deg < 135) || (deg >= 225 && deg < 315);
  if (is_portrait) {
    return render_timer_portrait_bitmap(state);
  }
  return render_timer_landscape_bitmap(state);
}

}  // namespace fridge_ink::ui
