#pragma once

#include "app/state.hpp"
#include "platform/display.hpp"

#include <array>
#include <cstdint>
#include <vector>

namespace fridge_ink::ui {

struct HomeDirtySnapshot {
  app::Screen screen{app::Screen::Landing};
  int focused_index{0};
  bool show_focus{false};
  int inventory_count{0};
  int reminder_count{0};
  std::array<bool, 3> inventory_completed{};
  std::array<bool, 5> reminder_completed{};
};

std::vector<uint8_t> render_home_bitmap(const app::AppState& state);
HomeDirtySnapshot capture_home_dirty_snapshot(const app::AppState& state);
std::vector<platform::DirtyRect> home_dirty_hints(
    const HomeDirtySnapshot& previous,
    const HomeDirtySnapshot& current);

}  // namespace fridge_ink::ui
