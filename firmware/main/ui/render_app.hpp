#pragma once

#include "app/state.hpp"

namespace fridge_ink::platform {
class Display;
}  // namespace fridge_ink::platform

namespace fridge_ink::ui {

void render_app(const app::AppState& state, platform::Display& display);

}  // namespace fridge_ink::ui
