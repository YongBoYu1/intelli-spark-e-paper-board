#include "ui/screens/timer_screen.hpp"

namespace fridge_ink::ui {
namespace {

bool use_timer_portrait_layout(const app::AppState& state) {
  const int deg = ((state.settings.rotation_deg % 360) + 360) % 360;
  return deg == 90 || deg == 270;
}

}  // namespace

std::vector<uint8_t> render_timer_bitmap(const app::AppState& state) {
  if (use_timer_portrait_layout(state)) {
    return render_timer_portrait_bitmap(state);
  }
  return render_timer_landscape_bitmap(state);
}

}  // namespace fridge_ink::ui
