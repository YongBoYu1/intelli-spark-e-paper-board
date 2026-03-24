#include "ui/render_app.hpp"

#include "platform/display.hpp"
#include "ui/screens/home_screen.hpp"
#include "ui/screens/landing_screen.hpp"
#include "ui/screens/onboarding_screen.hpp"

namespace fridge_ink::ui {

void render_app(const app::AppState& state, platform::Display& display) {
  switch (state.screen) {
    case app::Screen::Landing:
      display.present(make_landing_screen_frame(state));
      return;
    case app::Screen::Onboarding:
      display.present(make_onboarding_screen_frame(state));
      return;
    case app::Screen::Home:
      display.present(make_home_screen_frame(state));
      return;
  }
}

}  // namespace fridge_ink::ui
