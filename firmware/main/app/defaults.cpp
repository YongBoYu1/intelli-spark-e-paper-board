#include "app/defaults.hpp"

#include <ctime>

namespace fridge_ink::app {
namespace {

constexpr std::time_t kValidWallClockThreshold = 1700000000;

int month_index_from_abbrev(const char* month) {
  static constexpr const char* kMonths[] = {
      "Jan", "Feb", "Mar", "Apr", "May", "Jun",
      "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"};
  for (int i = 0; i < 12; ++i) {
    if (month[0] == kMonths[i][0] &&
        month[1] == kMonths[i][1] &&
        month[2] == kMonths[i][2]) {
      return i;
    }
  }
  return 0;
}

std::uint64_t compile_time_minute_bucket() {
  std::tm tm{};
  tm.tm_mon = month_index_from_abbrev(__DATE__);
  tm.tm_mday = (__DATE__[4] == ' ' ? 0 : (__DATE__[4] - '0')) * 10 + (__DATE__[5] - '0');
  tm.tm_year = ((__DATE__[7] - '0') * 1000 + (__DATE__[8] - '0') * 100 +
                (__DATE__[9] - '0') * 10 + (__DATE__[10] - '0')) - 1900;
  tm.tm_hour = (__TIME__[0] - '0') * 10 + (__TIME__[1] - '0');
  tm.tm_min = (__TIME__[3] - '0') * 10 + (__TIME__[4] - '0');
  tm.tm_sec = (__TIME__[6] - '0') * 10 + (__TIME__[7] - '0');
  const std::time_t compiled_at = std::mktime(&tm);
  if (compiled_at <= 0) {
    return 0;
  }
  return static_cast<std::uint64_t>(compiled_at / 60);
}

std::uint64_t current_minute_bucket(bool* is_real) {
  const std::time_t wall = std::time(nullptr);
  if (wall >= kValidWallClockThreshold) {
    if (is_real != nullptr) {
      *is_real = true;
    }
    return static_cast<std::uint64_t>(wall / 60);
  }
  if (is_real != nullptr) {
    *is_real = false;
  }
  return compile_time_minute_bucket();
}

}  // namespace

ProductDefaults make_factory_defaults() {
  ProductDefaults defaults;
  // #52 is validating the post-setup Home flow before persistence lands in #53.
  defaults.setup_completed = true;
  defaults.device_language = Language::EnUs;
  defaults.voice_locale = Language::EnUs;
  defaults.dashboard.location = "Toronto";
  defaults.dashboard.battery_percent = 84;
  defaults.dashboard.reminder_count = 7;
  defaults.dashboard.weather_condition = "Rainy";
  defaults.dashboard.weather_temperature_c = 17;
  defaults.dashboard.weather_humidity_percent = 100;
  defaults.dashboard.inventory_items = {
      "Fresh Milk",
      "Leftover Pizza",
      "Marinated Chicken",
  };
  defaults.dashboard.inventory_badges = {
      "EXP 3D",
      "ADD YDAY",
      "USE TNITE",
  };
  defaults.dashboard.inventory_completed = {
      false,
      false,
      false,
  };
  defaults.dashboard.reminder_items = {
      "Doctor Appointment",
      "Yoghurt Expires",
      "Morning Yoga",
      "Buy Milk",
      "Trash Day",
      "Pay Rent",
      "Call Mom",
  };
  defaults.dashboard.reminder_completed = {
      false,
      false,
      false,
      false,
      false,
      false,
      false,
  };
  defaults.dashboard.family_memo_text.clear();
  defaults.dashboard.family_memo_author.clear();
  defaults.dashboard.family_memo_posted.clear();
  return defaults;
}

Screen resolve_boot_screen(const ProductDefaults& defaults) {
  return defaults.setup_completed ? Screen::Home : Screen::Landing;
}

AppState make_state_from_defaults(
    const ProductDefaults& defaults,
    std::uint64_t now_ms) {
  AppState state;
  state.screen = resolve_boot_screen(defaults);
  state.setup_completed = defaults.setup_completed;
  state.device_language = defaults.device_language;
  state.voice_locale = defaults.voice_locale;
  state.boot_started_ms = now_ms;
  state.last_tick_ms = now_ms;
  state.landing.rotate_seen = false;
  state.landing.language_index = language_index(state.device_language);
  state.landing.status = state.screen == Screen::Landing
                             ? "Rotate to choose language."
                             : "Opening Home from built-in defaults.";
  state.onboarding.step_index = 0;
  state.onboarding.start_focus_index = 0;
  state.onboarding.qr_focus_index = 0;
  state.onboarding.prefs_focus_index = 0;
  state.onboarding.pair_token = "A1B2-C3D4";
  state.onboarding.wifi_ssid = "";
  state.onboarding.timezone = "America/Toronto";
  state.onboarding.auto_sync_enabled = true;
  state.onboarding.status = "";
  const bool has_home_rows =
      !defaults.dashboard.inventory_items.empty() || !defaults.dashboard.reminder_items.empty();
  state.home.focused_index = has_home_rows ? 2 : 0;
  state.home.clock_minute_bucket = current_minute_bucket(&state.home.clock_is_real);
  state.home.clock_seed_monotonic_ms = now_ms;
  state.home.show_focus = true;
  state.home.last_interaction_ms = now_ms;
  state.menu.focused_index = 0;
  state.timer.running = false;
  state.timer.minutes_remaining = 12;
  state.calendar.day_of_month = 26;
  state.calendar.month_label = "March 2026";
  state.weather.temperature_c = 4;
  state.weather.condition = "Cloudy";
  state.inventory.total_items = 5;
  state.inventory.reminder_count = defaults.dashboard.reminder_count;
  state.settings.partial_refresh_enabled = true;
  state.settings.auto_sync_enabled = true;
  state.dashboard = defaults.dashboard;
  return state;
}

}  // namespace fridge_ink::app
