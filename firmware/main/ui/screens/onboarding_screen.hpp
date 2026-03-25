#pragma once

#include "app/state.hpp"

#include <cstdint>
#include <vector>

namespace fridge_ink::ui {

std::vector<uint8_t> render_onboarding_bitmap(const app::AppState& state);

}  // namespace fridge_ink::ui
