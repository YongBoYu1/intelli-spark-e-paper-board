#pragma once

#include "app/events.hpp"
#include "app/state.hpp"
#include "platform/voice_client.hpp"

#include <vector>

namespace fridge_ink::app {

void reduce(AppState& state, const Event& event);

/// Apply a list of VoiceActions to the app state (called from voice_record_task).
void apply_voice_actions(AppState& state,
                         const std::vector<fridge_ink::platform::VoiceAction>& actions);

}  // namespace fridge_ink::app
