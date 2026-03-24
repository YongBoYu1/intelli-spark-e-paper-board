#include "ui/screens/onboarding_screen.hpp"

#include <array>
#include <string>

namespace fridge_ink::ui {
namespace {

constexpr std::array<const char*, 4> kStepNames = {
    "Start",
    "Pair QR",
    "Prefs",
    "Voice Guide"};

const char* step_key(const std::size_t index) {
  switch (index % kStepNames.size()) {
    case 0:
      return "start";
    case 1:
      return "pair_qr";
    case 2:
      return "prefs";
    case 3:
      return "voice_guide";
  }
  return "start";
}

std::string onboarding_footer(const std::size_t step) {
  if (step == 0) {
    return "Rotate to choose  -  Press to continue";
  }
  if (step == 1) {
    return "Rotate action  -  Press to continue";
  }
  if (step == 2) {
    return "Rotate setting  -  Press to change";
  }
  return "Press to continue";
}

}  // namespace

platform::ScreenFrame make_onboarding_screen_frame(const app::AppState& state) {
  platform::ScreenFrame frame;
  frame.title = "Fridge Ink";
  frame.subtitle = "Onboarding";

  const auto step = state.onboarding.step_index % kStepNames.size();
  frame.body_lines.push_back("Step Key: " + std::string(step_key(step)));
  frame.body_lines.push_back(std::string("Step: ") + std::to_string(step + 1) +
                             "/" + std::to_string(kStepNames.size()) +
                             " - " + kStepNames[step]);
  frame.body_lines.push_back("Start Focus: " + std::to_string(state.onboarding.start_focus_index));
  frame.body_lines.push_back("QR Focus: " + std::to_string(state.onboarding.qr_focus_index));
  frame.body_lines.push_back("Prefs Focus: " + std::to_string(state.onboarding.prefs_focus_index));
  frame.body_lines.push_back("Voice Focus: 0");
  frame.body_lines.push_back("Language: " + std::string(app::language_label(state.device_language)) +
                             " (" + app::language_code(state.device_language) + ")");
  if (step == 1) {
    frame.body_lines.push_back("Pair token: " + state.onboarding.pair_token);
  }
  if (step == 2) {
    frame.body_lines.push_back("Timezone: " + state.onboarding.timezone);
    frame.body_lines.push_back(std::string("Auto Sync: ") +
                               (state.onboarding.auto_sync_enabled ? "ON" : "OFF"));
  }
  if (!state.onboarding.wifi_ssid.empty()) {
    frame.body_lines.push_back("Wi-Fi: " + state.onboarding.wifi_ssid);
  }
  frame.body_lines.push_back("Status: " + state.onboarding.status);
  frame.footer = onboarding_footer(step);
  return frame;
}

}  // namespace fridge_ink::ui
