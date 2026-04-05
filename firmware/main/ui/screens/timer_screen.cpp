#include "ui/screens/timer_screen.hpp"

namespace fridge_ink::ui {

std::vector<uint8_t> render_timer_bitmap(const app::AppState& state) {
  // Python parity: timer.py uses one layout pipeline; do not fork into a
  // separate card-style portrait renderer.
  (void)state;
  return render_timer_landscape_bitmap(state);
}

}  // namespace fridge_ink::ui
