#pragma once

#include "app/state.hpp"
#include "platform/display.hpp"

namespace fridge_ink::ui {

platform::ScreenFrame make_landing_screen_frame(const app::AppState& state);

}  // namespace fridge_ink::ui
