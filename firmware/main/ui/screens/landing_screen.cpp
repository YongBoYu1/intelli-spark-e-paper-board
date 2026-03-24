#include "ui/screens/landing_screen.hpp"

#include <string>

namespace fridge_ink::ui {

platform::ScreenFrame make_landing_screen_frame(const app::AppState& state) {
  platform::ScreenFrame frame;
  frame.title = "Fridge Ink";
  frame.subtitle = "Landing";
  frame.body_lines.push_back(std::string("Language: ") +
                             app::language_label(state.device_language) + " (" +
                             app::language_code(state.device_language) + ")");
  frame.body_lines.push_back(std::string("Setup completed: ") +
                             (state.setup_completed ? "yes" : "no"));
  frame.body_lines.push_back("Boot source: built-in firmware defaults");
  frame.body_lines.push_back(state.landing.status);
  if (state.setup_completed) {
    frame.footer = "Enter Home";
  } else if (!state.landing.rotate_seen) {
    frame.footer = "Rotate to choose language";
  } else {
    frame.footer = "Click to start onboarding";
  }
  return frame;
}

}  // namespace fridge_ink::ui
