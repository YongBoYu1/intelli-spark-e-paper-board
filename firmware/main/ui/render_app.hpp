#pragma once

#include "app/state.hpp"

namespace fridge_ink::platform {
class Display;
}  // namespace fridge_ink::platform

namespace fridge_ink::ui {

struct HomeDirtySnapshot;

void render_app(
    const app::AppState& state,
    platform::Display& display,
    const HomeDirtySnapshot* previous_home_snapshot = nullptr);

}  // namespace fridge_ink::ui
