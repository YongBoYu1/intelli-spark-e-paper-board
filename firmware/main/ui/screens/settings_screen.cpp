#include "ui/screens/settings_screen.hpp"

namespace fridge_ink::ui {
namespace {

bool use_settings_portrait_layout(const app::AppState& state) {
  (void)state;
  // Scaffold phase: orientation wiring lands before portrait state plumbing.
  return false;
}

}  // namespace

std::vector<uint8_t> render_settings_bitmap(const app::AppState& state) {
  if (use_settings_portrait_layout(state)) {
    return render_settings_portrait_bitmap(state);
  }
  return render_settings_landscape_bitmap(state);
}

}  // namespace fridge_ink::ui
