#include "app/defaults.hpp"

namespace fridge_ink::app {

ProductDefaults make_factory_defaults() {
  ProductDefaults defaults;
  defaults.setup_completed = false;
  defaults.device_language = Language::EnUs;
  defaults.voice_locale = Language::EnUs;
  defaults.dashboard.location = "Kitchen";
  defaults.dashboard.battery_percent = 84;
  defaults.dashboard.reminder_count = 3;
  return defaults;
}

Screen resolve_boot_screen(const ProductDefaults& defaults) {
  return defaults.setup_completed ? Screen::Home : Screen::Landing;
}

AppState make_state_from_defaults(
    const ProductDefaults& defaults,
    std::uint64_t now_ms) {
  AppState state;
  state.screen = resolve_boot_screen(defaults);
  state.setup_completed = defaults.setup_completed;
  state.device_language = defaults.device_language;
  state.voice_locale = defaults.voice_locale;
  state.boot_started_ms = now_ms;
  state.last_tick_ms = now_ms;
  state.landing.rotate_seen = false;
  state.landing.language_index = language_index(state.device_language);
  state.landing.status = state.screen == Screen::Landing
                             ? "Rotate to choose language."
                             : "Opening Home from built-in defaults.";
  state.home.focused_index = 0;
  state.dashboard = defaults.dashboard;
  return state;
}

}  // namespace fridge_ink::app
