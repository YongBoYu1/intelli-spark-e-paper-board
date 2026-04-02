#include "app/defaults.hpp"

#include "platform/clock.hpp"
#include "esp_app_desc.h"

#include <algorithm>
#include <cstdlib>
#include <ctime>
#include <string>

namespace fridge_ink::app {
namespace {

constexpr const char* kDefaultTimezone = "America/Toronto";
const bool kAllowBuildTimestampFallback = true;

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

int parse_two_digits(const char tens, const char ones) {
  if (tens < '0' || tens > '9' || ones < '0' || ones > '9') {
    return -1;
  }
  return ((tens - '0') * 10) + (ones - '0');
}

void apply_posix_timezone(const char* zone_name) {
  static std::string active_tz{};
  std::string posix = "UTC0";
  const std::string zone = zone_name == nullptr ? "" : std::string(zone_name);
  if (zone == "America/Toronto" || zone == "America/New_York") {
    posix = "EST5EDT,M3.2.0/2,M11.1.0/2";
  } else if (zone == "America/Los_Angeles") {
    posix = "PST8PDT,M3.2.0/2,M11.1.0/2";
  }
  if (active_tz == posix) {
    return;
  }
  setenv("TZ", posix.c_str(), 1);
  tzset();
  active_tz = posix;
}

std::uint64_t minute_bucket_from_build_stamp(
    const char* date_stamp,
    const char* time_stamp,
    const char* zone_name) {
  if (date_stamp == nullptr || time_stamp == nullptr) {
    return 0;
  }
  apply_posix_timezone(zone_name);

  std::tm tm{};
  tm.tm_mon = month_index_from_abbrev(date_stamp);
  const int day_ones = (date_stamp[5] >= '0' && date_stamp[5] <= '9')
                           ? (date_stamp[5] - '0')
                           : -1;
  const int day_tens = (date_stamp[4] == ' ')
                           ? 0
                           : ((date_stamp[4] >= '0' && date_stamp[4] <= '9')
                                  ? (date_stamp[4] - '0')
                                  : -1);
  if (day_tens < 0 || day_ones < 0) {
    return 0;
  }
  tm.tm_mday = day_tens * 10 + day_ones;

  const int year_thousands = (date_stamp[7] >= '0' && date_stamp[7] <= '9')
                                 ? (date_stamp[7] - '0')
                                 : -1;
  const int year_hundreds = (date_stamp[8] >= '0' && date_stamp[8] <= '9')
                                ? (date_stamp[8] - '0')
                                : -1;
  const int year_tens = (date_stamp[9] >= '0' && date_stamp[9] <= '9')
                            ? (date_stamp[9] - '0')
                            : -1;
  const int year_ones = (date_stamp[10] >= '0' && date_stamp[10] <= '9')
                            ? (date_stamp[10] - '0')
                            : -1;
  if (year_thousands < 0 || year_hundreds < 0 || year_tens < 0 || year_ones < 0) {
    return 0;
  }
  tm.tm_year =
      (year_thousands * 1000 + year_hundreds * 100 + year_tens * 10 + year_ones) - 1900;

  tm.tm_hour = parse_two_digits(time_stamp[0], time_stamp[1]);
  tm.tm_min = parse_two_digits(time_stamp[3], time_stamp[4]);
  tm.tm_sec = parse_two_digits(time_stamp[6], time_stamp[7]);
  if (tm.tm_hour < 0 || tm.tm_min < 0 || tm.tm_sec < 0) {
    return 0;
  }
  tm.tm_isdst = -1;

  const std::time_t compiled_at = std::mktime(&tm);
  if (compiled_at <= 0) {
    return 0;
  }
  return static_cast<std::uint64_t>(compiled_at / 60);
}

std::uint64_t app_build_minute_bucket() {
  const std::uint64_t from_translation_unit = minute_bucket_from_build_stamp(
      __DATE__,
      __TIME__,
      kDefaultTimezone);
  const esp_app_desc_t* app_desc = esp_app_get_description();
  if (app_desc == nullptr) {
    return from_translation_unit;
  }
  const std::uint64_t from_app_desc = minute_bucket_from_build_stamp(
      app_desc->date,
      app_desc->time,
      kDefaultTimezone);
  return std::max(from_translation_unit, from_app_desc);
}

std::uint64_t current_minute_bucket(bool* is_real) {
  const std::time_t wall = platform::wall_time_seconds();
  if (platform::wall_time_is_valid()) {
    if (is_real != nullptr) {
      *is_real = true;
    }
    return static_cast<std::uint64_t>(wall / 60);
  }
  if (is_real != nullptr) {
    *is_real = false;
  }
  if (kAllowBuildTimestampFallback) {
    return app_build_minute_bucket();
  }
  return 0;
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
  state.home.focused_index = 0;
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
