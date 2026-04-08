#include "ui/screens/weather_screen.hpp"

namespace fridge_ink::ui {
namespace {

bool use_weather_portrait_layout(const app::AppState& state) {
  const int deg = ((state.settings.rotation_deg % 360) + 360) % 360;
  return deg == 90 || deg == 270;
}

}  // namespace

std::vector<uint8_t> render_weather_bitmap(const app::AppState& state) {
  if (use_weather_portrait_layout(state)) {
    return render_weather_portrait_bitmap(state);
  }
  return render_weather_landscape_bitmap(state);
}

}  // namespace fridge_ink::ui
