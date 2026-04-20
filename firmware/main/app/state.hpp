#pragma once

#include <array>
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
  Memo,
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

struct MemoItem {
  std::string text{};
  std::string author{};
  std::string posted{};
  bool is_new{false};
};

struct ReminderMetaItem {
  std::string rid{};
  std::string right{};
  std::string date_iso{};
};

struct CalendarEventItem {
  std::string eid{};
  std::string title{};
  std::string when{};
  std::string date_iso{};
};

struct WeatherForecastDay {
  std::string dow{"--"};
  std::string condition{};
  std::string icon{};
  int hi_c{0};
  int lo_c{0};
};

struct DashboardSummary {
  std::string location{"Kitchen"};
  int battery_percent{84};
  int reminder_count{3};
  std::string weather_condition{"Cloudy"};
  std::string weather_icon{"cloud"};
  int weather_temperature_c{4};
  int weather_humidity_percent{62};
  int weather_feels_like_c{4};
  int weather_hi_c{4};
  int weather_lo_c{2};
  int weather_wind_kmh{0};
  int weather_uv_index{0};
  std::array<WeatherForecastDay, 3> weather_forecast_days{};
  std::vector<std::string> inventory_items{};
  std::vector<std::string> inventory_badges{};
  std::vector<bool> inventory_completed{};
  std::vector<std::string> reminder_items{};
  std::vector<bool> reminder_completed{};
  std::vector<ReminderMetaItem> reminder_meta{};
  std::vector<CalendarEventItem> calendar_events{};
  std::string family_memo_text{};
  std::string family_memo_author{};
  std::string family_memo_posted{};
  std::vector<MemoItem> memos{};
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
  std::string clock_sync_state{"fallback_unsynced"};
  std::string weather_sync_state{"unsynced"};
  bool show_focus{false};
  bool menu_overlay_active{false};
  WidgetMode widget_mode{WidgetMode::Clock};
  std::vector<int> pending_hide_inventory_indices{};
  std::vector<int> hidden_inventory_indices{};
  std::vector<int> pending_hide_reminder_indices{};
  std::vector<int> hidden_reminder_indices{};
  std::uint64_t hide_due_ms{0};
  bool pending_reorder{false};
  std::uint64_t reorder_due_ms{0};
  std::uint64_t last_interaction_ms{0};
};

struct MenuState {
  std::size_t focused_index{0};
};

struct TimerState {
  bool running{false};
  int seconds_remaining{0};
  int target_seconds{0};
  bool alert_active{false};
  bool alert_blink_on{true};
  std::uint64_t alert_started_ms{0};
  std::uint64_t alert_until_ms{0};
  int last_completed_seconds{0};
  int focused_index{2};
  std::uint64_t last_tick_ms{0};
};

struct MemoState {
  int index{0};
  bool expanded{false};
};

struct CalendarState {
  int offset_days{0};
  std::string mode{"date"};
  int selected_index{0};
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
  int focused_index{0};
};

struct SettingsState {
  int focused_index{0};
  std::string font_size{"medium"};
  std::string partial_refresh_mode{"balanced"};
  bool partial_refresh_enabled{true};
  bool partial_refresh_budget_enabled{false};
  std::string refresh_mode{"balanced"};
  int full_refresh_every{30};
  bool wifi_enabled{true};
  bool bluetooth_enabled{false};
  bool auto_sync_enabled{true};
  std::uint64_t last_sync_ms{0};
  std::string sync_state{"never"};
  int rotation_deg{0};
  std::string notice{};
  std::uint64_t notice_due_ms{0};
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
  MemoState memo{};
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
