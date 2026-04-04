#pragma once

#include "app/state.hpp"

#include <cstdint>
#include <vector>

namespace fridge_ink::ui {

std::vector<uint8_t> render_memo_bitmap(const app::AppState& state);
std::vector<uint8_t> render_memo_landscape_bitmap(const app::AppState& state);
std::vector<uint8_t> render_memo_portrait_bitmap(const app::AppState& state);

}  // namespace fridge_ink::ui
