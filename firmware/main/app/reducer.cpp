#include "app/reducer.hpp"

#include <string>

namespace fridge_ink::app {
namespace {

constexpr int kHomeFocusSlots = 2;

void set_language(AppState& state, Language language) {
  state.device_language = language;
  state.voice_locale = language;
  state.landing.language_index = language_index(language);
}

void enter_home(AppState& state) {
  state.screen = Screen::Home;
  state.landing.status.clear();
}

void refresh_landing_status(AppState& state) {
  if (state.setup_completed) {
    state.landing.status = "Setup complete. Press click to open Home.";
    return;
  }
  if (!state.landing.rotate_seen) {
    state.landing.status = "Rotate to choose language.";
    return;
  }
  state.landing.status = std::string("Language: ") +
                         language_label(state.device_language) +
                         ". Press click to continue.";
}

void handle_tick(AppState& state, const Event& event) {
  state.last_tick_ms = event.now_ms;
  if (state.screen != Screen::Landing) {
    return;
  }
  if (state.setup_completed) {
    enter_home(state);
    return;
  }
  refresh_landing_status(state);
}

void handle_rotate(AppState& state, const Event& event) {
  if (state.screen == Screen::Landing) {
    const auto next_index =
        (state.landing.language_index + (event.rotate_delta >= 0 ? 1U : 2U)) % 3U;
    state.landing.rotate_seen = true;
    set_language(state, language_from_index(next_index));
    state.landing.status = std::string("Language set to ") +
                           language_label(state.device_language) +
                           ". Press click to continue.";
    return;
  }

  if (state.screen == Screen::Home) {
    const int delta = event.rotate_delta >= 0 ? 1 : (kHomeFocusSlots - 1);
    state.home.focused_index = (state.home.focused_index + delta) % kHomeFocusSlots;
  }
}

void handle_click(AppState& state) {
  if (state.screen == Screen::Landing) {
    if (!state.setup_completed && !state.landing.rotate_seen) {
      state.landing.status = "Rotate to choose language first.";
      return;
    }
    enter_home(state);
    return;
  }

  if (state.screen == Screen::Home) {
    state.home.focused_index = (state.home.focused_index + 1) % kHomeFocusSlots;
  }
}

}  // namespace

void reduce(AppState& state, const Event& event) {
  switch (event.type) {
    case EventType::Tick:
      handle_tick(state, event);
      break;
    case EventType::Rotate:
      handle_rotate(state, event);
      break;
    case EventType::Click:
      handle_click(state);
      break;
  }
}

}  // namespace fridge_ink::app
