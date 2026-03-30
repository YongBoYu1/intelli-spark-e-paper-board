#include "ui/render_app.hpp"

#include "platform/display.hpp"
#include "ui/screens/home_screen.hpp"
#include "ui/screens/landing_screen.hpp"
#include "ui/screens/menu_screen.hpp"
#include "ui/screens/onboarding_screen.hpp"
#include "ui/screens/placeholder_screen.hpp"

#include "esp_log.h"

#include <vector>

namespace fridge_ink::ui {

namespace {
constexpr const char* kTag = "render";
}  // namespace

void render_app(
    const app::AppState& state,
    platform::Display& display,
    const HomeDirtySnapshot* previous_home_snapshot) {
  ESP_LOGI(kTag, "render_app: screen=%s lang=%s",
           app::screen_name(state.screen),
           app::language_code(state.device_language));

  std::vector<uint8_t> image;
  std::vector<platform::DirtyRect> dirty_hints;

  switch (state.screen) {
    case app::Screen::Landing:
      image = render_landing_bitmap(state);
      break;
    case app::Screen::Onboarding:
      image = render_onboarding_bitmap(state);
      break;
    case app::Screen::Home:
      image = render_home_bitmap(state);
      if (previous_home_snapshot != nullptr) {
        dirty_hints = home_dirty_hints(
            *previous_home_snapshot,
            capture_home_dirty_snapshot(state));
      }
      break;
    case app::Screen::Menu:
      image = render_menu_bitmap(state);
      break;
    case app::Screen::Timer:
      image = render_timer_bitmap(state);
      break;
    case app::Screen::Calendar:
      image = render_calendar_bitmap(state);
      break;
    case app::Screen::Weather:
      image = render_weather_bitmap(state);
      break;
    case app::Screen::Inventory:
      image = render_inventory_bitmap(state);
      break;
    case app::Screen::Settings:
      image = render_settings_bitmap(state);
      break;
  }

  display.display_image(image, dirty_hints);
}

}  // namespace fridge_ink::ui
