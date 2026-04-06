#include "app/reducer.hpp"
#include "platform/clock.hpp"
#include "esp_log.h"

#include <algorithm>
#include <array>
#include <ctime>
#include <string>

namespace fridge_ink::app {
namespace {

constexpr const char* kTag = "reducer";

constexpr int kMenuItemCount = 5;
constexpr int kSettingsItemCount = 8;
constexpr int kHomeInventoryVisibleMax = 3;
constexpr int kHomeReminderVisibleMax = 5;
constexpr std::uint64_t kHomeCompletedHideGraceMs = 15000;
constexpr std::uint64_t kHomeCompletedHideSettleMs = 600;
constexpr std::uint64_t kReminderReorderDelayMs = 2000;
constexpr int kTimerStepSeconds = 60;
constexpr int kTimerDefaultSeconds = 5 * 60;
constexpr int kTimerMaxSeconds = 180 * 60;
constexpr std::uint64_t kTimerAlertShowMs = 6000;
constexpr std::uint64_t kTimerAlertBlinkPeriodMs = 450;
constexpr std::size_t kOnboardingStepCount = 4;
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

enum class SettingsItem {
  FontSize = 0,
  PartialRefresh = 1,
  FullRefresh = 2,
  Rotation = 3,
  Connectivity = 4,
  AutoSync = 5,
  SyncNow = 6,
  ResetAndWipe = 7,
};

enum class HomeFocusTargetKind {
  None,
  Clock,
  Weather,
  InventoryItem,
  ReminderItem,
};

struct HomeFocusTarget {
  HomeFocusTargetKind kind{HomeFocusTargetKind::None};
  int item_index{-1};
};

bool contains_index(const std::vector<int>& values, const int index) {
  return std::find(values.begin(), values.end(), index) != values.end();
}

void remove_index(std::vector<int>& values, const int index) {
  values.erase(
      std::remove(values.begin(), values.end(), index),
      values.end());
}

int clamp_int(const int value, const int low, const int high) {
  return std::max(low, std::min(value, high));
}

int normalize_rotation_deg(const int raw) {
  const int rounded = ((raw % 360) + 360) % 360;
  if (rounded >= 315 || rounded < 45) {
    return 0;
  }
  if (rounded < 135) {
    return 90;
  }
  if (rounded < 225) {
    return 180;
  }
  return 270;
}

int list_item_count(const AppState& state) {
  return static_cast<int>(state.dashboard.inventory_items.size() +
                          state.dashboard.reminder_items.size());
}

void clamp_memo_index(AppState& state) {
  const int total = static_cast<int>(state.dashboard.memos.size());
  if (total <= 0) {
    state.memo.index = 0;
    return;
  }
  if (state.memo.index < 0) {
    state.memo.index = total - 1;
  } else if (state.memo.index >= total) {
    state.memo.index = 0;
  }
}

void clamp_list_focus(AppState& state) {
  const int total = list_item_count(state);
  if (total <= 0) {
    state.inventory.focused_index = 0;
    return;
  }
  state.inventory.focused_index = clamp_int(state.inventory.focused_index, 0, total - 1);
}

void clamp_settings_focus(AppState& state) {
  state.settings.focused_index =
      clamp_int(state.settings.focused_index, 0, kSettingsItemCount - 1);
}

SettingsItem settings_item_for_focus(AppState& state) {
  clamp_settings_focus(state);
  return static_cast<SettingsItem>(state.settings.focused_index);
}

void set_settings_notice(
    AppState& state,
    const std::string& text,
    const std::uint64_t now_ms,
    const std::uint64_t due_ms = 2000) {
  state.settings.notice = text;
  const std::uint64_t base_ms = now_ms > 0 ? now_ms : state.last_tick_ms;
  state.settings.notice_due_ms = base_ms + due_ms;
}

std::string cycle_font_size(const std::string& current) {
  if (current == "small") {
    return "medium";
  }
  if (current == "medium") {
    return "large";
  }
  return "small";
}

std::string cycle_partial_refresh_mode(const std::string& current) {
  if (current == "slow") {
    return "balanced";
  }
  if (current == "balanced") {
    return "fast";
  }
  return "slow";
}

int cycle_full_refresh_every(const int current) {
  if (current == 10) {
    return 20;
  }
  if (current == 20) {
    return 30;
  }
  return 10;
}

void clear_timer_alert(AppState& state) {
  state.timer.alert_active = false;
  state.timer.alert_blink_on = true;
  state.timer.alert_started_ms = 0;
  state.timer.alert_until_ms = 0;
}

void start_timer_alert(
    AppState& state,
    const std::uint64_t now_ms,
    const int completed_seconds) {
  const int done_seconds = std::max(1, completed_seconds);
  state.timer.last_completed_seconds = done_seconds;
  state.timer.alert_active = true;
  state.timer.alert_blink_on = true;
  state.timer.alert_started_ms = now_ms;
  state.timer.alert_until_ms = now_ms + kTimerAlertShowMs;
}

void tick_timer_alert(AppState& state, const std::uint64_t now_ms) {
  if (!state.timer.alert_active) {
    return;
  }
  if (state.timer.alert_until_ms == 0 || now_ms >= state.timer.alert_until_ms) {
    clear_timer_alert(state);
    return;
  }
  const std::uint64_t started_ms =
      state.timer.alert_started_ms > 0 ? state.timer.alert_started_ms : now_ms;
  const std::uint64_t elapsed_ms = now_ms > started_ms ? (now_ms - started_ms) : 0ULL;
  const int phase = static_cast<int>(elapsed_ms / kTimerAlertBlinkPeriodMs);
  state.timer.alert_blink_on = (phase % 2) == 0;
}

void adjust_timer_seconds(
    AppState& state,
    const int delta_seconds) {
  const int next_seconds =
      clamp_int(state.timer.seconds_remaining + delta_seconds, 0, kTimerMaxSeconds);
  state.timer.seconds_remaining = next_seconds;
  state.timer.target_seconds = next_seconds;
  if (next_seconds <= 0) {
    state.timer.running = false;
  }
}

void handle_settings_click(AppState& state, const Event& event) {
  switch (settings_item_for_focus(state)) {
    case SettingsItem::FontSize:
      state.settings.font_size = cycle_font_size(state.settings.font_size);
      ESP_LOGI(kTag, "[settings] font_size=%s", state.settings.font_size.c_str());
      return;
    case SettingsItem::PartialRefresh:
      state.settings.partial_refresh_mode =
          cycle_partial_refresh_mode(state.settings.partial_refresh_mode);
      state.settings.refresh_mode = state.settings.partial_refresh_mode;
      ESP_LOGI(
          kTag,
          "[settings] partial_refresh_mode=%s",
          state.settings.partial_refresh_mode.c_str());
      return;
    case SettingsItem::FullRefresh:
      state.settings.full_refresh_every = cycle_full_refresh_every(state.settings.full_refresh_every);
      ESP_LOGI(kTag, "[settings] full_refresh_every=%d", state.settings.full_refresh_every);
      return;
    case SettingsItem::Rotation:
      state.settings.rotation_deg =
          (normalize_rotation_deg(state.settings.rotation_deg) + 90) % 360;
      ESP_LOGI(kTag, "[settings] rotation_deg=%d", state.settings.rotation_deg);
      return;
    case SettingsItem::Connectivity: {
      const bool next_on = !(state.settings.wifi_enabled && state.settings.bluetooth_enabled);
      state.settings.wifi_enabled = next_on;
      state.settings.bluetooth_enabled = next_on;
      ESP_LOGI(
          kTag,
          "[settings] connectivity wifi=%d bt=%d",
          static_cast<int>(state.settings.wifi_enabled),
          static_cast<int>(state.settings.bluetooth_enabled));
      return;
    }
    case SettingsItem::AutoSync:
      state.settings.auto_sync_enabled = !state.settings.auto_sync_enabled;
      ESP_LOGI(kTag, "[settings] auto_sync=%d", static_cast<int>(state.settings.auto_sync_enabled));
      return;
    case SettingsItem::SyncNow:
      state.settings.last_sync_ms = event.now_ms > 0 ? event.now_ms : state.last_tick_ms;
      state.settings.sync_state = "ok";
      set_settings_notice(state, "FAKE SYNC COMPLETE", event.now_ms);
      ESP_LOGI(kTag, "[settings] sync_now=ok at=%llu",
               static_cast<unsigned long long>(state.settings.last_sync_ms));
      return;
    case SettingsItem::ResetAndWipe:
      set_settings_notice(state, "NOT IMPLEMENTED", event.now_ms);
      ESP_LOGI(kTag, "[settings] reset_and_wipe=not_implemented");
      return;
  }
}

std::vector<int> visible_reminder_indices(const AppState& state) {
  std::vector<int> indices{};
  const int total = static_cast<int>(state.dashboard.reminder_items.size());
  indices.reserve(std::min(total, kHomeReminderVisibleMax));
  for (int i = 0; i < total; ++i) {
    if (contains_index(state.home.hidden_reminder_indices, i)) {
      continue;
    }
    indices.push_back(i);
    if (static_cast<int>(indices.size()) >= kHomeReminderVisibleMax) {
      break;
    }
  }
  return indices;
}

int home_inventory_count(const AppState& state) {
  return std::min(
      static_cast<int>(state.dashboard.inventory_items.size()),
      kHomeInventoryVisibleMax);
}

int home_reminder_count(const AppState& state) {
  return static_cast<int>(visible_reminder_indices(state).size());
}

int home_focus_count(const AppState& state) {
  return 2 + home_inventory_count(state) + home_reminder_count(state);
}

int first_home_focus_index(const AppState& state) {
  (void)state;
  return 0;
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
  if (focused_index == 0) {
    return {HomeFocusTargetKind::Clock, -1};
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

  const std::vector<int> reminder_indices = visible_reminder_indices(state);
  if (pos < static_cast<int>(reminder_indices.size())) {
    return {HomeFocusTargetKind::ReminderItem, reminder_indices[static_cast<std::size_t>(pos)]};
  }

  return {HomeFocusTargetKind::None, -1};
}

void ensure_completion_flags(
    std::vector<bool>& completed,
    const std::size_t item_count) {
  if (completed.size() >= item_count) {
    return;
  }
  completed.resize(item_count, false);
}

bool remove_reminder_visibility_tracking(
    AppState& state,
    const int item_index,
    const bool restore_visible) {
  if (item_index < 0) {
    return false;
  }
  bool changed = false;
  const auto pending_before = state.home.pending_hide_reminder_indices.size();
  remove_index(state.home.pending_hide_reminder_indices, item_index);
  if (state.home.pending_hide_reminder_indices.size() != pending_before) {
    changed = true;
  }

  if (restore_visible) {
    const auto hidden_before = state.home.hidden_reminder_indices.size();
    remove_index(state.home.hidden_reminder_indices, item_index);
    if (state.home.hidden_reminder_indices.size() != hidden_before) {
      changed = true;
    }
  }

  if (state.home.pending_hide_reminder_indices.empty()) {
    state.home.hide_due_ms = 0;
  }
  return changed;
}

void mark_pending_reminder_hide(
    AppState& state,
    const int item_index,
    const std::uint64_t now_ms) {
  if (item_index < 0) {
    return;
  }
  remove_index(state.home.hidden_reminder_indices, item_index);
  if (!contains_index(state.home.pending_hide_reminder_indices, item_index)) {
    state.home.pending_hide_reminder_indices.push_back(item_index);
  }
  const std::uint64_t base_ms = now_ms > 0 ? now_ms : state.last_tick_ms;
  state.home.hide_due_ms = base_ms + kHomeCompletedHideGraceMs;
}

bool home_hide_ready(const AppState& state, const std::uint64_t now_ms) {
  if (state.home.pending_hide_reminder_indices.empty()) {
    return false;
  }
  if (state.home.hide_due_ms == 0 || now_ms < state.home.hide_due_ms) {
    return false;
  }
  return (now_ms - state.home.last_interaction_ms) >= kHomeCompletedHideSettleMs;
}

bool promote_pending_reminder_hide(AppState& state) {
  if (state.home.pending_hide_reminder_indices.empty()) {
    return false;
  }
  bool changed = false;
  for (const int index : state.home.pending_hide_reminder_indices) {
    if (index < 0 ||
        index >= static_cast<int>(state.dashboard.reminder_items.size())) {
      continue;
    }
    if (!contains_index(state.home.hidden_reminder_indices, index)) {
      state.home.hidden_reminder_indices.push_back(index);
      changed = true;
    }
  }
  state.home.pending_hide_reminder_indices.clear();
  state.home.hide_due_ms = 0;
  return changed;
}

void schedule_reminder_reorder(AppState& state, const std::uint64_t now_ms) {
  const std::uint64_t base_ms = now_ms > 0 ? now_ms : state.last_tick_ms;
  state.home.pending_reorder = true;
  state.home.reorder_due_ms = base_ms + kReminderReorderDelayMs;
}

void remap_index_list(
    std::vector<int>& values,
    const std::vector<int>& old_to_new,
    const int item_count) {
  std::vector<int> remapped{};
  remapped.reserve(values.size());
  for (const int old_index : values) {
    if (old_index < 0 || old_index >= static_cast<int>(old_to_new.size())) {
      continue;
    }
    const int mapped_index = old_to_new[static_cast<std::size_t>(old_index)];
    if (mapped_index < 0 || mapped_index >= item_count) {
      continue;
    }
    if (!contains_index(remapped, mapped_index)) {
      remapped.push_back(mapped_index);
    }
  }
  values = std::move(remapped);
}

void apply_reminder_reorder(AppState& state) {
  auto& reminders = state.dashboard.reminder_items;
  auto& completed = state.dashboard.reminder_completed;
  ensure_completion_flags(completed, reminders.size());
  const int item_count = static_cast<int>(reminders.size());

  if (item_count <= 1) {
    state.home.pending_reorder = false;
    state.home.reorder_due_ms = 0;
    return;
  }

  struct ReminderRow {
    std::string title{};
    bool done{false};
    int old_index{0};
  };

  std::vector<ReminderRow> rows{};
  rows.reserve(static_cast<std::size_t>(item_count));
  for (int i = 0; i < item_count; ++i) {
    rows.push_back(ReminderRow{
        reminders[static_cast<std::size_t>(i)],
        completed[static_cast<std::size_t>(i)],
        i,
    });
  }

  std::stable_sort(
      rows.begin(),
      rows.end(),
      [](const ReminderRow& lhs, const ReminderRow& rhs) {
        return static_cast<int>(lhs.done) < static_cast<int>(rhs.done);
      });

  bool changed = false;
  std::vector<int> old_to_new(static_cast<std::size_t>(item_count), -1);
  for (int new_index = 0; new_index < item_count; ++new_index) {
    const int old_index = rows[static_cast<std::size_t>(new_index)].old_index;
    old_to_new[static_cast<std::size_t>(old_index)] = new_index;
    if (old_index != new_index) {
      changed = true;
    }
  }

  if (!changed) {
    state.home.pending_reorder = false;
    state.home.reorder_due_ms = 0;
    return;
  }

  for (int i = 0; i < item_count; ++i) {
    const auto& row = rows[static_cast<std::size_t>(i)];
    reminders[static_cast<std::size_t>(i)] = row.title;
    completed[static_cast<std::size_t>(i)] = row.done;
  }

  remap_index_list(
      state.home.pending_hide_reminder_indices,
      old_to_new,
      item_count);
  remap_index_list(
      state.home.hidden_reminder_indices,
      old_to_new,
      item_count);

  clamp_home_focus(state);
  state.home.pending_reorder = false;
  state.home.reorder_due_ms = 0;
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
  state.home.menu_overlay_active = false;
  state.landing.status.clear();
  state.onboarding.status = "Setup complete.";
}

void open_menu_target(AppState& state, const std::uint64_t now_ms) {
  state.home.menu_overlay_active = false;
  switch (state.menu.focused_index % kMenuItemCount) {
    case 0:
      state.screen = Screen::Memo;
      clamp_memo_index(state);
      state.memo.expanded = false;
      return;
    case 1:
      state.screen = Screen::Inventory;
      clamp_list_focus(state);
      return;
    case 2:
      state.home.widget_mode = WidgetMode::Timer;
      if (state.timer.seconds_remaining <= 0 && !state.timer.alert_active) {
        state.timer.seconds_remaining = kTimerDefaultSeconds;
      }
      if (state.timer.target_seconds <= 0) {
        state.timer.target_seconds = state.timer.seconds_remaining;
      }
      state.timer.focused_index = 2;
      state.timer.last_tick_ms = now_ms > 0 ? now_ms : state.last_tick_ms;
      clear_timer_alert(state);
      state.screen = Screen::Timer;
      return;
    case 3:
      state.screen = Screen::Calendar;
      return;
    case 4:
      state.screen = Screen::Settings;
      clamp_settings_focus(state);
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
  const std::time_t wall = platform::wall_time_seconds();
  if (platform::wall_time_is_valid()) {
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

  if (state.home.widget_mode == WidgetMode::Timer &&
      state.timer.running &&
      state.timer.seconds_remaining > 0) {
    const std::uint64_t base_ms =
        state.timer.last_tick_ms > 0 ? state.timer.last_tick_ms : event.now_ms;
    if (event.now_ms > base_ms) {
      const std::uint64_t elapsed_ms = event.now_ms - base_ms;
      const int elapsed_seconds = static_cast<int>(elapsed_ms / 1000ULL);
      if (elapsed_seconds > 0) {
        const int before_seconds = state.timer.seconds_remaining;
        state.timer.seconds_remaining =
            std::max(0, state.timer.seconds_remaining - elapsed_seconds);
        state.timer.last_tick_ms = base_ms + static_cast<std::uint64_t>(elapsed_seconds) * 1000ULL;
        if (state.timer.seconds_remaining <= 0) {
          const int completed = state.timer.target_seconds > 0
                                    ? state.timer.target_seconds
                                    : std::max(1, before_seconds);
          state.timer.running = false;
          state.timer.seconds_remaining = 0;
          start_timer_alert(state, event.now_ms, completed);
        }
      }
    }
  } else {
    state.timer.last_tick_ms = event.now_ms;
  }
  tick_timer_alert(state, event.now_ms);

  if (state.home.pending_reorder &&
      state.home.reorder_due_ms > 0 &&
      event.now_ms >= state.home.reorder_due_ms) {
    apply_reminder_reorder(state);
  }

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

  if (state.screen == Screen::Home &&
      home_hide_ready(state, event.now_ms) &&
      promote_pending_reminder_hide(state)) {
    clamp_home_focus(state);
  }

  if (!state.settings.notice.empty() &&
      state.settings.notice_due_ms > 0 &&
      event.now_ms >= state.settings.notice_due_ms) {
    state.settings.notice.clear();
    state.settings.notice_due_ms = 0;
  }
}

void handle_rotate(AppState& state, const Event& event) {
  if (event.now_ms > 0) {
    state.home.last_interaction_ms = event.now_ms;
  }
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

  if (state.screen == Screen::Menu ||
      (state.screen == Screen::Home && state.home.menu_overlay_active)) {
    const int delta = event.rotate_delta >= 0 ? 1 : (kMenuItemCount - 1);
    state.menu.focused_index =
        (state.menu.focused_index + static_cast<std::size_t>(delta)) %
        static_cast<std::size_t>(kMenuItemCount);
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

  if (state.screen == Screen::Settings) {
    const int delta = event.rotate_delta >= 0 ? 1 : -1;
    state.settings.focused_index += delta;
    if (state.settings.focused_index < 0) {
      state.settings.focused_index = kSettingsItemCount - 1;
    } else if (state.settings.focused_index >= kSettingsItemCount) {
      state.settings.focused_index = 0;
    }
    return;
  }

  if (state.screen == Screen::Timer) {
    clear_timer_alert(state);
    const int delta = event.rotate_delta >= 0 ? 1 : -1;
    state.timer.focused_index = (state.timer.focused_index + delta + 4) % 4;
    return;
  }

  if (state.screen == Screen::Memo) {
    const int delta = event.rotate_delta >= 0 ? 1 : -1;
    state.memo.index += delta;
    clamp_memo_index(state);
    state.memo.expanded = false;
    return;
  }

  if (state.screen == Screen::Inventory) {
    const int delta = event.rotate_delta >= 0 ? 1 : -1;
    state.inventory.focused_index += delta;
    clamp_list_focus(state);
    return;
  }
}

void handle_click(AppState& state, const Event& event) {
  if (event.now_ms > 0) {
    state.home.last_interaction_ms = event.now_ms;
  }
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
    if (state.home.menu_overlay_active) {
      open_menu_target(state, event.now_ms);
      return;
    }
    clamp_home_focus(state);
    state.home.show_focus = true;
    const HomeFocusTarget target = home_focus_target(state);
    switch (target.kind) {
      case HomeFocusTargetKind::None:
        return;
      case HomeFocusTargetKind::Clock:
        if (state.home.widget_mode == WidgetMode::Timer) {
          const std::uint64_t base_ms = event.now_ms > 0 ? event.now_ms : state.last_tick_ms;
          state.timer.running = !state.timer.running;
          state.timer.last_tick_ms = base_ms;
          return;
        }
        state.home.menu_overlay_active = false;
        state.screen = Screen::Calendar;
        return;
      case HomeFocusTargetKind::Weather:
        state.home.menu_overlay_active = false;
        state.screen = Screen::Weather;
        return;
      case HomeFocusTargetKind::InventoryItem:
        ensure_completion_flags(
            state.dashboard.inventory_completed,
            state.dashboard.inventory_items.size());
        if (target.item_index >= 0 &&
            target.item_index < static_cast<int>(state.dashboard.inventory_completed.size())) {
          state.dashboard.inventory_completed[static_cast<std::size_t>(target.item_index)] =
              !state.dashboard.inventory_completed[static_cast<std::size_t>(target.item_index)];
        }
        return;
      case HomeFocusTargetKind::ReminderItem:
        ensure_completion_flags(
            state.dashboard.reminder_completed,
            state.dashboard.reminder_items.size());
        if (target.item_index >= 0 &&
            target.item_index < static_cast<int>(state.dashboard.reminder_completed.size())) {
          const std::size_t index = static_cast<std::size_t>(target.item_index);
          state.dashboard.reminder_completed[index] =
              !state.dashboard.reminder_completed[index];
          if (state.dashboard.reminder_completed[index]) {
            mark_pending_reminder_hide(state, target.item_index, event.now_ms);
          } else {
            remove_reminder_visibility_tracking(state, target.item_index, true);
          }
          schedule_reminder_reorder(state, event.now_ms);
        }
        return;
    }
    return;
  }

  if (state.screen == Screen::Menu) {
    open_menu_target(state, event.now_ms);
    return;
  }

  if (state.screen == Screen::Timer) {
    clear_timer_alert(state);
    int focus = state.timer.focused_index;
    if (focus < 0 || focus > 3) {
      focus = 2;
      state.timer.focused_index = focus;
    }
    const std::uint64_t base_ms = event.now_ms > 0 ? event.now_ms : state.last_tick_ms;
    switch (focus) {
      case 0:
        adjust_timer_seconds(state, -kTimerStepSeconds);
        state.timer.last_tick_ms = base_ms;
        return;
      case 1:
        adjust_timer_seconds(state, kTimerStepSeconds);
        state.timer.last_tick_ms = base_ms;
        return;
      case 2:
        if (state.timer.running) {
          state.timer.running = false;
        } else {
          if (state.timer.seconds_remaining <= 0) {
            state.timer.seconds_remaining = kTimerDefaultSeconds;
            state.timer.target_seconds = state.timer.seconds_remaining;
          } else if (state.timer.target_seconds <= 0) {
            state.timer.target_seconds = state.timer.seconds_remaining;
          }
          state.timer.running = true;
        }
        state.timer.last_tick_ms = base_ms;
        return;
      case 3:
        state.timer.running = false;
        state.timer.seconds_remaining = 0;
        state.timer.target_seconds = 0;
        state.timer.last_tick_ms = base_ms;
        return;
    }
  }

  if (state.screen == Screen::Settings) {
    handle_settings_click(state, event);
    return;
  }

  if (state.screen == Screen::Memo) {
    if (!state.dashboard.memos.empty()) {
      clamp_memo_index(state);
      state.memo.expanded = !state.memo.expanded;
      const int index = std::max(
          0,
          std::min(
              state.memo.index,
              static_cast<int>(state.dashboard.memos.size()) - 1));
      auto& memo = state.dashboard.memos[static_cast<std::size_t>(index)];
      if (memo.is_new) {
        memo.is_new = false;
      }
    }
    return;
  }

  if (state.screen == Screen::Inventory) {
    const int inventory_count = static_cast<int>(state.dashboard.inventory_items.size());
    const int reminder_count = static_cast<int>(state.dashboard.reminder_items.size());
    const int total = inventory_count + reminder_count;
    if (total <= 0) {
      state.inventory.focused_index = 0;
      return;
    }
    clamp_list_focus(state);
    if (state.inventory.focused_index < inventory_count) {
      ensure_completion_flags(
          state.dashboard.inventory_completed,
          state.dashboard.inventory_items.size());
      const int index = state.inventory.focused_index;
      state.dashboard.inventory_completed[static_cast<std::size_t>(index)] =
          !state.dashboard.inventory_completed[static_cast<std::size_t>(index)];
      return;
    }

    const int reminder_index = state.inventory.focused_index - inventory_count;
    ensure_completion_flags(
        state.dashboard.reminder_completed,
        state.dashboard.reminder_items.size());
    if (reminder_index < 0 ||
        reminder_index >= static_cast<int>(state.dashboard.reminder_completed.size())) {
      return;
    }
    const std::size_t index = static_cast<std::size_t>(reminder_index);
    const bool next_completed = !state.dashboard.reminder_completed[index];
    state.dashboard.reminder_completed[index] = next_completed;
    if (!next_completed) {
      remove_reminder_visibility_tracking(state, reminder_index, true);
    }
    schedule_reminder_reorder(state, event.now_ms);
    return;
  }

  if (state.screen == Screen::Memo ||
      state.screen == Screen::Calendar ||
      state.screen == Screen::Weather) {
    // Other detail screens rely on Back/LongPress to return home.
    return;
  }
}

void handle_long_press(AppState& state, const Event& event) {
  if (event.now_ms > 0) {
    state.home.last_interaction_ms = event.now_ms;
  }
  // Python parity:
  // - HOME long press toggles the menu overlay.
  // - Non-HOME long press returns to HOME.
  if (state.screen == Screen::Home) {
    state.home.menu_overlay_active = !state.home.menu_overlay_active;
    return;
  }

  state.screen = Screen::Home;
  state.home.menu_overlay_active = false;
  clamp_home_focus(state);
  state.home.show_focus = true;
}

void handle_back(AppState& state, const Event& event) {
  if (event.now_ms > 0) {
    state.home.last_interaction_ms = event.now_ms;
  }
  // Python parity:
  // - HOME back closes overlay if open, otherwise opens overlay.
  // - Non-HOME back returns to HOME.
  if (state.screen == Screen::Home) {
    if (state.home.menu_overlay_active) {
      state.home.menu_overlay_active = false;
      return;
    }
    state.home.menu_overlay_active = true;
    return;
  }

  state.screen = Screen::Home;
  state.home.menu_overlay_active = false;
  clamp_home_focus(state);
  state.home.show_focus = true;
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
      handle_click(state, event);
      break;
    case EventType::LongPress:
      handle_long_press(state, event);
      break;
    case EventType::Back:
      handle_back(state, event);
      break;
  }
}

}  // namespace fridge_ink::app
