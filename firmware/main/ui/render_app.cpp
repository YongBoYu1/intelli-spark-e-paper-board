#include "ui/render_app.hpp"

#include "ui/screens/calendar_screen.hpp"
#include "ui/screens/home_screen.hpp"
#include "ui/screens/landing_screen.hpp"
#include "ui/screens/list_screen.hpp"
#include "ui/screens/memo_screen.hpp"
#include "ui/screens/menu_screen.hpp"
#include "ui/screens/onboarding_screen.hpp"
#include "ui/screens/weather_screen.hpp"
#include "ui/screens/settings_screen.hpp"
#include "ui/screens/timer_screen.hpp"

#include "esp_log.h"

#include <vector>

namespace fridge_ink::ui {

namespace {
constexpr const char* kTag = "render";
}  // namespace

RenderOutput render_app(
    const app::AppState& state,
    const HomeDirtySnapshot* previous_home_snapshot) {
  ESP_LOGI(kTag, "render_app: screen=%s lang=%s",
           app::screen_name(state.screen),
           app::language_code(state.device_language));

  RenderOutput output{};

  switch (state.screen) {
    case app::Screen::Landing:
      output.image = render_landing_bitmap(state);
      break;
    case app::Screen::Onboarding:
      output.image = render_onboarding_bitmap(state);
      break;
    case app::Screen::Home:
      output.image = render_home_bitmap(state);
      if (previous_home_snapshot != nullptr) {
        const HomeDirtyPlan plan = home_dirty_plan(
            *previous_home_snapshot,
            capture_home_dirty_snapshot(state));
        output.dirty_rects = plan.rects;
        output.dirty_reasons = plan.reasons;
      }
      break;
    case app::Screen::Menu:
      output.image = render_menu_bitmap(state);
      break;
    case app::Screen::Memo:
      output.image = render_memo_bitmap(state);
      break;
    case app::Screen::Timer:
      output.image = render_timer_bitmap(state);
      break;
    case app::Screen::Calendar:
      output.image = render_calendar_bitmap(state);
      break;
    case app::Screen::Weather:
      output.image = render_weather_bitmap(state);
      break;
    case app::Screen::Inventory:
      output.image = render_list_bitmap(state);
      break;
    case app::Screen::Settings:
      output.image = render_settings_bitmap(state);
      break;
  }

  return output;
}

}  // namespace fridge_ink::ui
