#include "ui/render_app.hpp"

#include "platform/display.hpp"
#include "ui/screens/home_screen.hpp"
#include "ui/screens/landing_screen.hpp"
#include "ui/screens/onboarding_screen.hpp"

#include "esp_log.h"

#include <vector>

namespace fridge_ink::ui {

namespace {
constexpr const char* kTag = "render";
}  // namespace

void render_app(const app::AppState& state, platform::Display& display) {
  ESP_LOGI(kTag, "render_app: screen=%s lang=%s",
           app::screen_name(state.screen),
           app::language_code(state.device_language));

  std::vector<uint8_t> image;

  switch (state.screen) {
    case app::Screen::Landing:
      image = render_landing_bitmap(state);
      break;
    case app::Screen::Onboarding:
      image = render_onboarding_bitmap(state);
      break;
    case app::Screen::Home:
      image = render_home_bitmap(state);
      break;
  }

  display.display_image(image);
}

}  // namespace fridge_ink::ui
