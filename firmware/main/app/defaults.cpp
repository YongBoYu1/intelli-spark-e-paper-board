#include "app/defaults.hpp"

#include "platform/clock.hpp"

#include <ctime>

namespace fridge_ink::app {
namespace {

constexpr const char* kDefaultTimezone = "America/Toronto";

int month_from_abbrev(const char* text3) {
  static constexpr const char* kMonths[] = {
      "Jan", "Feb", "Mar", "Apr", "May", "Jun",
      "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"};
  for (int i = 0; i < 12; ++i) {
    if (text3[0] == kMonths[i][0] &&
        text3[1] == kMonths[i][1] &&
        text3[2] == kMonths[i][2]) {
      return i;
    }
  }
  return 0;
}

int parse_two_digits(const char a, const char b) {
  if (a < '0' || a > '9' || b < '0' || b > '9') {
    return -1;
  }
  return (a - '0') * 10 + (b - '0');
}

std::uint64_t build_minute_bucket_fallback() {
  std::tm tm{};
  tm.tm_mon = month_from_abbrev(__DATE__);
  const int day_tens = (__DATE__[4] == ' ') ? 0 : (__DATE__[4] - '0');
  const int day_ones = __DATE__[5] - '0';
  if (day_tens < 0 || day_tens > 9 || day_ones < 0 || day_ones > 9) {
    return 0;
  }
  tm.tm_mday = day_tens * 10 + day_ones;

  const int year = (__DATE__[7] - '0') * 1000 +
                   (__DATE__[8] - '0') * 100 +
                   (__DATE__[9] - '0') * 10 +
                   (__DATE__[10] - '0');
  if (year < 1970 || year > 9999) {
    return 0;
  }
  tm.tm_year = year - 1900;

  tm.tm_hour = parse_two_digits(__TIME__[0], __TIME__[1]);
  tm.tm_min = parse_two_digits(__TIME__[3], __TIME__[4]);
  tm.tm_sec = parse_two_digits(__TIME__[6], __TIME__[7]);
  if (tm.tm_hour < 0 || tm.tm_min < 0 || tm.tm_sec < 0) {
    return 0;
  }
  tm.tm_isdst = -1;

  const std::time_t compiled_local = std::mktime(&tm);
  if (compiled_local <= 0) {
    return 0;
  }
  return static_cast<std::uint64_t>(compiled_local / 60);
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
  return build_minute_bucket_fallback();
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
  defaults.dashboard.reminder_meta = {
      {"r_doctor", "Tomorrow 09:00", "2026-04-07"},
      {"r_yogurt", "Friday", ""},
      {"r_yoga", "Mon 07:00", ""},
      {"r_milk", "Apr 09", ""},
      {"r_trash", "Tue", ""},
      {"r_rent", "May 01", "2026-05-01"},
      {"r_mom", "Tonight", ""},
  };
  defaults.dashboard.calendar_events = {
      {"e_team", "Team standup", "09:30", "2026-04-06"},
      {"e_clinic", "Dental clinic", "14:00", "2026-04-07"},
      {"e_school", "Parent meeting", "18:30", "2026-04-09"},
  };
  defaults.dashboard.memos = {
      {
          "Please wipe the fridge shelf after dinner. Leftovers on top rack.",
          "Mom",
          "2H AGO",
          true,
      },
      {
          "Trash pickup is tomorrow morning. Move the blue bin outside before bed.",
          "Dad",
          "YESTERDAY",
          false,
      },
      {
          "Guest coming on Sunday. Buy fruit and sparkling water.",
          "Family",
          "MAR 31",
          false,
      },
  };
  defaults.dashboard.family_memo_text = defaults.dashboard.memos.front().text;
  defaults.dashboard.family_memo_author = defaults.dashboard.memos.front().author;
  defaults.dashboard.family_memo_posted = defaults.dashboard.memos.front().posted;
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
  state.onboarding.timezone = kDefaultTimezone;
  state.onboarding.auto_sync_enabled = true;
  state.onboarding.status = "";
  state.home.focused_index = 0;
  state.home.clock_minute_bucket = current_minute_bucket(&state.home.clock_is_real);
  state.home.clock_seed_monotonic_ms = now_ms;
  state.home.clock_sync_state = state.home.clock_is_real ? "real_synced" : "fallback_unsynced";
  state.home.weather_sync_state = "ok";
  state.home.show_focus = true;
  state.home.menu_overlay_active = false;
  state.home.pending_reorder = false;
  state.home.reorder_due_ms = 0;
  state.home.last_interaction_ms = now_ms;
  // Python parity: HOME overlay menu defaults to LIST.
  state.menu.focused_index = 1;
  state.timer.running = false;
  state.timer.seconds_remaining = 0;
  state.timer.target_seconds = 0;
  state.timer.alert_active = false;
  state.timer.alert_blink_on = true;
  state.timer.alert_started_ms = 0;
  state.timer.alert_until_ms = 0;
  state.timer.last_completed_seconds = 0;
  state.timer.focused_index = 2;
  state.timer.last_tick_ms = now_ms;
  state.memo.index = 0;
  state.memo.expanded = false;
  state.calendar.offset_days = 0;
  state.calendar.mode = "date";
  state.calendar.selected_index = 0;
  state.calendar.day_of_month = 26;
  state.calendar.month_label = "March 2026";
  state.weather.temperature_c = 4;
  state.weather.condition = "Cloudy";
  state.inventory.total_items = 5;
  state.inventory.reminder_count = defaults.dashboard.reminder_count;
  state.inventory.focused_index = 0;
  state.settings.focused_index = 0;
  state.settings.font_size = "medium";
  state.settings.partial_refresh_mode = "balanced";
  state.settings.partial_refresh_enabled = true;
  state.settings.partial_refresh_budget_enabled = false;
  state.settings.refresh_mode = "balanced";
  state.settings.full_refresh_every = 30;
  state.settings.wifi_enabled = true;
  state.settings.bluetooth_enabled = false;
  state.settings.auto_sync_enabled = true;
  state.settings.last_sync_ms = 0;
  state.settings.sync_state = "never";
  state.settings.rotation_deg = 0;
  state.settings.notice.clear();
  state.settings.notice_due_ms = 0;
  state.dashboard = defaults.dashboard;
  return state;
}

}  // namespace fridge_ink::app
