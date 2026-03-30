#include "app/reducer.hpp"

#include <algorithm>
#include <array>
#include <ctime>
#include <string>

namespace fridge_ink::app {
namespace {

constexpr int kMenuItemCount = 6;
constexpr int kHomeInventoryVisibleMax = 3;
constexpr int kHomeReminderVisibleMax = 5;
constexpr std::size_t kOnboardingStepCount = 4;
constexpr std::time_t kValidWallClockThreshold = 1700000000;
constexpr std::array<const char*, 4> kTimezoneChoices = {
    "America/Toronto",
    "America/New_York",
    "America/Los_Angeles",
    "UTC"};

constexpr std::array<const char*, kOnboardingStepCount> kOnboardingStepTitles = {
    "Start",
    "Pair QR",
    "Prefs",
    "Voice Guide"};

enum class HomeFocusTargetKind {
  Clock,
  Weather,
  InventoryItem,
  ReminderItem,
};

struct HomeFocusTarget {
  HomeFocusTargetKind kind{HomeFocusTargetKind::Clock};
  int item_index{-1};
};

int home_inventory_count(const AppState& state) {
  return std::min(
      static_cast<int>(state.dashboard.inventory_items.size()),
      kHomeInventoryVisibleMax);
}

int home_reminder_count(const AppState& state) {
  return std::min(
      static_cast<int>(state.dashboard.reminder_items.size()),
      kHomeReminderVisibleMax);
}

int home_focus_count(const AppState& state) {
  return 2 + home_inventory_count(state) + home_reminder_count(state);
}

int first_home_focus_index(const AppState& state) {
  return home_focus_count(state) > 2 ? 2 : 0;
}

void clamp_home_focus(AppState& state) {
  const int slot_count = std::max(1, home_focus_count(state));
  if (state.home.focused_index < 0) {
    state.home.focused_index = 0;
    return;
  }
  if (state.home.focused_index >= slot_count) {
    state.home.focused_index = slot_count - 1;
  }
}

HomeFocusTarget home_focus_target(const AppState& state) {
  const int focused_index = std::max(0, state.home.focused_index);
  if (focused_index <= 0) {
    return {};
  }
  if (focused_index == 1) {
    return {HomeFocusTargetKind::Weather, -1};
  }

  int pos = focused_index - 2;
  const int inventory_count = home_inventory_count(state);
  if (pos < inventory_count) {
    return {HomeFocusTargetKind::InventoryItem, pos};
  }
  pos -= inventory_count;

  if (pos < home_reminder_count(state)) {
    return {HomeFocusTargetKind::ReminderItem, pos};
  }

  return {};
}

void enter_onboarding_start(AppState& state) {
  state.screen = Screen::Onboarding;
  state.onboarding.step_index = 0;
  state.onboarding.status.clear();
}

void enter_onboarding_pair_qr(AppState& state) {
  state.screen = Screen::Onboarding;
  state.onboarding.step_index = 1;
  state.onboarding.status = "Waiting for phone callback...";
}

void enter_onboarding_prefs(AppState& state, const bool wifi_connected) {
  state.screen = Screen::Onboarding;
  state.onboarding.step_index = 2;
  if (wifi_connected && state.onboarding.wifi_ssid.empty()) {
    state.onboarding.wifi_ssid = "Home_2.4G";
  }
  state.onboarding.status.clear();
}

void enter_onboarding_voice_guide(AppState& state) {
  state.screen = Screen::Onboarding;
  state.onboarding.step_index = 3;
  state.onboarding.status = "Hold voice key to test current sample.";
}

void cycle_timezone(AppState& state) {
  std::size_t index = 0;
  for (std::size_t i = 0; i < kTimezoneChoices.size(); ++i) {
    if (state.onboarding.timezone == kTimezoneChoices[i]) {
      index = i;
      break;
    }
  }
  state.onboarding.timezone = kTimezoneChoices[(index + 1U) % kTimezoneChoices.size()];
}

void set_language(AppState& state, Language language) {
  state.device_language = language;
  state.voice_locale = language;
  state.landing.language_index = language_index(language);
}

void enter_home(AppState& state) {
  state.setup_completed = true;
  state.screen = Screen::Home;
  state.home.focused_index = first_home_focus_index(state);
  state.home.show_focus = true;
  state.landing.status.clear();
  state.onboarding.status = "Setup complete.";
}

void enter_menu(AppState& state) {
  state.screen = Screen::Menu;
}

void open_menu_target(AppState& state) {
  switch (state.menu.focused_index % kMenuItemCount) {
    case 0:
      state.screen = Screen::Home;
      return;
    case 1:
      state.screen = Screen::Timer;
      return;
    case 2:
      state.screen = Screen::Calendar;
      return;
    case 3:
      state.screen = Screen::Weather;
      return;
    case 4:
      state.screen = Screen::Inventory;
      return;
    case 5:
      state.screen = Screen::Settings;
      return;
  }
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
                         ". Click to start onboarding.";
}

void refresh_onboarding_status(AppState& state) {
  const std::size_t step = state.onboarding.step_index % kOnboardingStepCount;
  state.onboarding.step_index = step;
  if (step == 0) {
    state.onboarding.status.clear();
    return;
  }
  if (step == 1) {
    if (state.onboarding.status.empty()) {
      state.onboarding.status = "Waiting for phone callback...";
    }
    return;
  }
  if (step == 2) {
    state.onboarding.status.clear();
    return;
  }
  state.onboarding.status = "Hold voice key to test current sample.";
}

void handle_tick(AppState& state, const Event& event) {
  const std::time_t wall = std::time(nullptr);
  if (wall >= kValidWallClockThreshold) {
    state.home.clock_minute_bucket = static_cast<std::uint64_t>(wall / 60);
    state.home.clock_is_real = true;
    state.home.clock_seed_monotonic_ms = event.now_ms;
  } else if (state.home.clock_minute_bucket > 0) {
    const std::uint64_t elapsed_ms = event.now_ms - state.home.clock_seed_monotonic_ms;
    const std::uint64_t minutes_passed = elapsed_ms / 60000ULL;
    if (minutes_passed > 0) {
      state.home.clock_minute_bucket += minutes_passed;
      state.home.clock_seed_monotonic_ms += minutes_passed * 60000ULL;
    }
  }
  state.last_tick_ms = event.now_ms;
  if (state.screen == Screen::Landing) {
    if (state.setup_completed) {
      enter_home(state);
      return;
    }
    refresh_landing_status(state);
    return;
  }

  if (state.screen == Screen::Onboarding) {
    refresh_onboarding_status(state);
  }
}

void handle_rotate(AppState& state, const Event& event) {
  if (state.screen == Screen::Landing) {
    const auto next_index =
        (state.landing.language_index + (event.rotate_delta >= 0 ? 1U : 2U)) % 3U;
    state.landing.rotate_seen = true;
    set_language(state, language_from_index(next_index));
    state.landing.status = std::string("Language set to ") +
                           language_label(state.device_language) +
                           ". Click to continue.";
    return;
  }

  if (state.screen == Screen::Onboarding) {
    const int delta = event.rotate_delta >= 0 ? 1 : -1;
    if (state.onboarding.step_index == 0) {
      const int next = static_cast<int>(state.onboarding.start_focus_index) + delta;
      state.onboarding.start_focus_index = static_cast<std::size_t>(next < 0 ? 0 : (next > 1 ? 1 : next));
      return;
    }
    if (state.onboarding.step_index == 1) {
      const int next = static_cast<int>(state.onboarding.qr_focus_index) + delta;
      state.onboarding.qr_focus_index = static_cast<std::size_t>(next < 0 ? 0 : (next > 2 ? 2 : next));
      return;
    }
    if (state.onboarding.step_index == 2) {
      const int next = static_cast<int>(state.onboarding.prefs_focus_index) + delta;
      state.onboarding.prefs_focus_index = static_cast<std::size_t>(next < 0 ? 0 : (next > 3 ? 3 : next));
      return;
    }
    refresh_onboarding_status(state);
    return;
  }

  if (state.screen == Screen::Home) {
    const int slot_count = std::max(1, home_focus_count(state));
    const int delta = event.rotate_delta >= 0 ? 1 : -1;
    state.home.focused_index =
        std::max(0, std::min(state.home.focused_index + delta, slot_count - 1));
    state.home.show_focus = true;
    return;
  }

  if (state.screen == Screen::Menu) {
    const int delta = event.rotate_delta >= 0 ? 1 : (kMenuItemCount - 1);
    state.menu.focused_index =
        (state.menu.focused_index + static_cast<std::size_t>(delta)) %
        static_cast<std::size_t>(kMenuItemCount);
  }
}

void handle_click(AppState& state) {
  if (state.screen == Screen::Landing) {
    if (state.setup_completed) {
      enter_home(state);
      return;
    }
    if (!state.setup_completed && !state.landing.rotate_seen) {
      state.landing.status = "Rotate to choose language first.";
      return;
    }
    enter_onboarding_start(state);
    refresh_onboarding_status(state);
    return;
  }

  if (state.screen == Screen::Onboarding) {
    if (state.onboarding.step_index == 0) {
      if (state.onboarding.start_focus_index == 0) {
        enter_onboarding_pair_qr(state);
      } else {
        enter_onboarding_prefs(state, false);
      }
      return;
    }
    if (state.onboarding.step_index == 1) {
      if (state.onboarding.qr_focus_index == 0) {
        state.onboarding.pair_token = "E5F6-G7H8";
        state.onboarding.status = "QR refreshed.";
      } else if (state.onboarding.qr_focus_index == 1) {
        enter_onboarding_prefs(state, true);
      } else {
        enter_onboarding_prefs(state, false);
      }
      return;
    }
    if (state.onboarding.step_index == 2) {
      if (state.onboarding.prefs_focus_index == 0) {
        set_language(state, language_from_index(language_index(state.device_language) + 1U));
      } else if (state.onboarding.prefs_focus_index == 1) {
        cycle_timezone(state);
      } else if (state.onboarding.prefs_focus_index == 2) {
        state.onboarding.auto_sync_enabled = !state.onboarding.auto_sync_enabled;
      } else {
        enter_onboarding_voice_guide(state);
      }
      refresh_onboarding_status(state);
      return;
    }
    if (state.onboarding.step_index == 3) {
      enter_home(state);
      return;
    }
  }

  if (state.screen == Screen::Home) {
    clamp_home_focus(state);
    state.home.show_focus = true;
    const HomeFocusTarget target = home_focus_target(state);
    switch (target.kind) {
      case HomeFocusTargetKind::Clock:
        state.screen = Screen::Calendar;
        return;
      case HomeFocusTargetKind::Weather:
        state.screen = Screen::Weather;
        return;
      case HomeFocusTargetKind::InventoryItem:
        if (target.item_index >= 0 &&
            target.item_index < static_cast<int>(state.dashboard.inventory_completed.size())) {
          state.dashboard.inventory_completed[static_cast<std::size_t>(target.item_index)] =
              !state.dashboard.inventory_completed[static_cast<std::size_t>(target.item_index)];
        }
        return;
      case HomeFocusTargetKind::ReminderItem:
        if (target.item_index >= 0 &&
            target.item_index < static_cast<int>(state.dashboard.reminder_completed.size())) {
          state.dashboard.reminder_completed[static_cast<std::size_t>(target.item_index)] =
              !state.dashboard.reminder_completed[static_cast<std::size_t>(target.item_index)];
        }
        return;
    }
    return;
  }

  if (state.screen == Screen::Menu) {
    open_menu_target(state);
    return;
  }

  if (state.screen == Screen::Timer ||
      state.screen == Screen::Calendar ||
      state.screen == Screen::Weather ||
      state.screen == Screen::Inventory ||
      state.screen == Screen::Settings) {
    enter_menu(state);
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
