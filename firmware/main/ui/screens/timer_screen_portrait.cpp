#include "ui/screens/timer_screen.hpp"

#include "ui/screens/detail_screen_scaffold.hpp"

#include <string>

namespace fridge_ink::ui {

std::vector<uint8_t> render_timer_portrait_bitmap(const app::AppState& state) {
  const std::string line_one =
      std::string("Minutes remaining: ") + std::to_string(state.timer.minutes_remaining);
  const std::string line_two =
      std::string("Running: ") + (state.timer.running ? "YES" : "NO");
  return render_detail_scaffold_bitmap(
      "TIMER",
      line_one,
      line_two,
      "Portrait parity worker owns final UI and focus behavior.",
      "PORTRAIT");
}

}  // namespace fridge_ink::ui
