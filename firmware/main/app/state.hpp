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
  ZhCn,
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

// A recurring alarm that fires every day at a fixed HH:MM.
// Created via voice command, e.g. "Remind me every day at 2pm to take medicine".
struct ScheduledReminder {
  std::string id{};                    // unique ID, e.g. "sr_0"
  std::string title{};                 // e.g. "Take medicine"
  int hour{0};                         // 0–23 (local time)
  int minute{0};                       // 0–59
  bool enabled{true};
  std::uint64_t last_fired_bucket{0};  // minute-bucket when last fired; prevents re-trigger
};

// State for the modal alarm popup shown when a ScheduledReminder fires.
struct ScheduledAlarmState {
  bool active{false};
  std::string id{};         // which ScheduledReminder triggered this
  std::string title{};      // reminder title (copy for display)
  int hour{0};
  int minute{0};
  int focused_index{0};     // 0 = Confirm ("done"), 1 = Cancel ("skip")
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
  bool reset_pending{false};  // true after first click on ResetAndWipe; second click confirms
};

struct WifiScanEntry {
  std::string ssid{};
  int rssi{0};
};

struct OnboardingState {
  std::size_t step_index{0};
  std::size_t start_focus_index{0};

  // ── Step 1: WiFi selection (sub_step 0) + password entry (sub_step 1) ──
  std::size_t wifi_sub_step{0};
  std::vector<WifiScanEntry> wifi_networks;
  std::size_t wifi_list_focus{0};
  std::size_t wifi_list_scroll{0};
  bool wifi_scanning{false};
  bool wifi_connecting{false};
  std::string wifi_connect_error{};
  std::string wifi_password{};
  std::size_t kbd_focus{0};   // 0-43, linear QWERTY key index
  bool        kbd_shift{false};

  // ── Step 2: Preferences ────────────────────────────────────────────────
  std::size_t prefs_focus_index{0};
  std::string wifi_ssid{};
  std::string timezone{"America/Toronto"};
  bool auto_sync_enabled{true};
  std::string status{};

  // ── Step 3: Voice guide ────────────────────────────────────────────────
  bool voice_recording{false};   // true while mic_record_task is running
  std::string voice_last_result{};  // summary from last voice response

  // ── Settings → Change Wi-Fi ────────────────────────────────────────────
  bool wifi_from_settings{false};  // true when wifi flow was launched from Settings
};

// Total on-screen keyboard keys: row0(10)+row1(10)+row2(9)+row3(7)+row4(8)=44
// Row 4 special indices: 36=SHIFT 37='-' 38='_' 39='.' 40='@' 41=SPACE 42=DEL 43=OK
static constexpr std::size_t kOnboardingKbdKeyCount = 44u;

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
  // Daily scheduled reminders (persistent, voice-created).
  std::vector<ScheduledReminder> scheduled_reminders{};
  // Currently active alarm popup (at most one at a time).
  ScheduledAlarmState scheduled_alarm{};
};

const char* screen_name(Screen screen);
const char* language_code(Language language);
const char* language_label(Language language);
Language language_from_index(std::size_t index);
std::size_t language_index(Language language);

}  // namespace fridge_ink::app
