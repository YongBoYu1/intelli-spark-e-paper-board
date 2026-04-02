#pragma once

#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

namespace fridge_ink::app {

enum class Screen {
  Landing,
  Onboarding,
  Home,
  Menu,
  Timer,
  Calendar,
  Weather,
  Inventory,
  Settings,
};

enum class Language {
  EnUs,
  EsEs,
  FrFr,
};

enum class WidgetMode {
  Clock,
  Timer,
};

struct DashboardSummary {
  std::string location{"Kitchen"};
  int battery_percent{84};
  int reminder_count{3};
  std::string weather_condition{"Cloudy"};
  int weather_temperature_c{4};
  int weather_humidity_percent{62};
  std::vector<std::string> inventory_items{};
  std::vector<std::string> inventory_badges{};
  std::vector<bool> inventory_completed{};
  std::vector<std::string> reminder_items{};
  std::vector<bool> reminder_completed{};
  std::string family_memo_text{};
  std::string family_memo_author{};
  std::string family_memo_posted{};
};

struct LandingState {
  bool rotate_seen{false};
  std::size_t language_index{0};
  std::string status{};
};

struct HomeState {
  int focused_index{0};
  std::uint64_t clock_minute_bucket{0};
  std::uint64_t clock_seed_monotonic_ms{0};
  bool clock_is_real{false};
  bool show_focus{false};
  WidgetMode widget_mode{WidgetMode::Clock};
  std::vector<int> pending_hide_reminder_indices{};
  std::vector<int> hidden_reminder_indices{};
  std::uint64_t hide_due_ms{0};
  std::uint64_t last_interaction_ms{0};
};

struct MenuState {
  std::size_t focused_index{0};
};

struct TimerState {
  bool running{false};
  int minutes_remaining{12};
};

struct CalendarState {
  int day_of_month{26};
  std::string month_label{"March 2026"};
};

struct WeatherState {
  int temperature_c{4};
  std::string condition{"Cloudy"};
};

struct InventoryState {
  int total_items{5};
  int reminder_count{3};
};

struct SettingsState {
  bool partial_refresh_enabled{true};
  std::string refresh_mode{"balanced"};
  int full_refresh_every{0};
  bool auto_sync_enabled{true};
};

struct OnboardingState {
  std::size_t step_index{0};
  std::size_t start_focus_index{0};
  std::size_t qr_focus_index{0};
  std::size_t prefs_focus_index{0};
  std::string pair_token{"A1B2-C3D4"};
  std::string wifi_ssid{};
  std::string timezone{"America/Toronto"};
  bool auto_sync_enabled{true};
  std::string status{};
};

struct AppState {
  Screen screen{Screen::Landing};
  bool setup_completed{false};
  Language device_language{Language::EnUs};
  Language voice_locale{Language::EnUs};
  std::uint64_t boot_started_ms{0};
  std::uint64_t last_tick_ms{0};
  LandingState landing{};
  OnboardingState onboarding{};
  HomeState home{};
  MenuState menu{};
  TimerState timer{};
  CalendarState calendar{};
  WeatherState weather{};
  InventoryState inventory{};
  SettingsState settings{};
  DashboardSummary dashboard{};
};

const char* screen_name(Screen screen);
const char* language_code(Language language);
const char* language_label(Language language);
Language language_from_index(std::size_t index);
std::size_t language_index(Language language);

}  // namespace fridge_ink::app
