#pragma once

#include "app/events.hpp"
#include "app/state.hpp"

namespace fridge_ink::app {

void reduce(AppState& state, const Event& event);

}  // namespace fridge_ink::app
