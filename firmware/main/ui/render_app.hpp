#pragma once

#include "app/state.hpp"
#include "platform/display.hpp"

#include <string>
#include <vector>

namespace fridge_ink::ui {

struct HomeDirtySnapshot;

struct RenderOutput {
  std::vector<uint8_t> image{};
  std::vector<platform::DirtyRect> dirty_rects{};
  std::vector<std::string> dirty_reasons{};
};

RenderOutput render_app(
    const app::AppState& state,
    const HomeDirtySnapshot* previous_home_snapshot = nullptr);

}  // namespace fridge_ink::ui
