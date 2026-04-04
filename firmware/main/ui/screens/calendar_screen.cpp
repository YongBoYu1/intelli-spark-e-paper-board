#include "ui/screens/calendar_screen.hpp"

namespace fridge_ink::ui {
namespace {

bool use_calendar_portrait_layout(const app::AppState& state) {
  (void)state;
  // Scaffold phase: orientation wiring lands before portrait state plumbing.
  return false;
}

}  // namespace

std::vector<uint8_t> render_calendar_bitmap(const app::AppState& state) {
  if (use_calendar_portrait_layout(state)) {
    return render_calendar_portrait_bitmap(state);
  }
  return render_calendar_landscape_bitmap(state);
}

}  // namespace fridge_ink::ui
