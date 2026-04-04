#pragma once

#include "app/state.hpp"

#include <cstdint>
#include <vector>

namespace fridge_ink::ui {

std::vector<uint8_t> render_weather_bitmap(const app::AppState& state);
std::vector<uint8_t> render_inventory_bitmap(const app::AppState& state);

}  // namespace fridge_ink::ui
