#include "ui/screens/home_screen.hpp"

#include <string>

namespace fridge_ink::ui {

platform::ScreenFrame make_home_screen_frame(const app::AppState& state) {
  platform::ScreenFrame frame;
  frame.title = "Home";
  frame.subtitle = "C++ runtime V0";
  frame.body_lines.push_back("Location: " + state.dashboard.location);
  frame.body_lines.push_back("Battery: " +
                             std::to_string(state.dashboard.battery_percent) + "%");
  frame.body_lines.push_back("Reminders: " +
                             std::to_string(state.dashboard.reminder_count));
  frame.body_lines.push_back("Focus slot: " +
                             std::to_string(state.home.focused_index));
  frame.footer = "State-driven boot path with no external JSON";
  return frame;
}

}  // namespace fridge_ink::ui
