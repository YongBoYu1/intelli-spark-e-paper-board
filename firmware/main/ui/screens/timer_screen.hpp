#pragma once

#include "app/state.hpp"

#include <cstdint>
#include <vector>

namespace fridge_ink::ui {

std::vector<uint8_t> render_timer_bitmap(const app::AppState& state);
std::vector<uint8_t> render_timer_landscape_bitmap(const app::AppState& state);
std::vector<uint8_t> render_timer_portrait_bitmap(const app::AppState& state);

}  // namespace fridge_ink::ui
