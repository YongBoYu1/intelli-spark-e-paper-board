#include "app/reducer.hpp"
#include "app/calendar_runtime.hpp"
#include "app/defaults.hpp"
#include "platform/clock.hpp"
#include "platform/live_data_provider.hpp"
#include "platform/voice_client.hpp"
#include "platform/wifi_driver.hpp"
#include "esp_log.h"

#include <algorithm>
#include <array>
#include <cctype>
#include <cinttypes>
#include <ctime>
#include <sstream>
#include <string>

namespace fridge_ink::app {
namespace {

constexpr const char* kTag = "reducer";

constexpr int kMenuItemCount = 5;
constexpr int kSettingsItemCount = 9;
constexpr int kHomeInventoryVisibleLandscapeMax = 3;
constexpr int kHomeInventoryVisiblePortraitMax = 4;
constexpr int kHomeReminderVisiblePortraitMax = 4;
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
  ChangeWifi = 7,
  ResetAndWipe = 8,
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

std::string format_index_list(const std::vector<int>& values) {
  std::ostringstream out;
  out << "[";
  for (std::size_t i = 0; i < values.size(); ++i) {
    if (i > 0) {
      out << ",";
    }
    out << values[i];
  }
  out << "]";
  return out.str();
}

std::string format_home_hide_state(const AppState& state) {
  std::ostringstream out;
  out << "pending_inv=" << format_index_list(state.home.pending_hide_inventory_indices)
      << " hidden_inv=" << format_index_list(state.home.hidden_inventory_indices)
      << " pending_rem=" << format_index_list(state.home.pending_hide_reminder_indices)
      << " hidden_rem=" << format_index_list(state.home.hidden_reminder_indices);
  return out.str();
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

bool home_uses_portrait_layout(const AppState& state) {
  const int deg = normalize_rotation_deg(state.settings.rotation_deg);
  return deg == 90 || deg == 270;
}

int home_inventory_visible_max(const AppState& state) {
  return home_uses_portrait_layout(state)
             ? kHomeInventoryVisiblePortraitMax
             : kHomeInventoryVisibleLandscapeMax;
}

int home_reminder_visible_max(const AppState& state) {
  return home_uses_portrait_layout(state)
             ? kHomeReminderVisiblePortraitMax
             : kHomeReminderVisibleMax;
}

std::vector<int> list_visible_inventory_indices(const AppState& state) {
  std::vector<int> indices{};
  const int total = static_cast<int>(state.dashboard.inventory_items.size());
  indices.reserve(total);
  if (total <= 0) {
    return indices;
  }
  if (state.home.hidden_inventory_indices.empty()) {
    for (int i = 0; i < total; ++i) {
      indices.push_back(i);
    }
    return indices;
  }
  std::vector<std::uint8_t> hidden_flags(static_cast<std::size_t>(total), 0U);
  for (const int index : state.home.hidden_inventory_indices) {
    if (index >= 0 && index < total) {
      hidden_flags[static_cast<std::size_t>(index)] = 1U;
    }
  }
  for (int i = 0; i < total; ++i) {
    if (hidden_flags[static_cast<std::size_t>(i)] != 0U) {
      continue;
    }
    indices.push_back(i);
  }
  return indices;
}

std::vector<int> list_visible_reminder_indices(const AppState& state) {
  std::vector<int> indices{};
  const int total = static_cast<int>(state.dashboard.reminder_items.size());
  indices.reserve(total);
  if (total <= 0) {
    return indices;
  }
  if (state.home.hidden_reminder_indices.empty()) {
    for (int i = 0; i < total; ++i) {
      indices.push_back(i);
    }
    return indices;
  }
  std::vector<std::uint8_t> hidden_flags(static_cast<std::size_t>(total), 0U);
  for (const int index : state.home.hidden_reminder_indices) {
    if (index >= 0 && index < total) {
      hidden_flags[static_cast<std::size_t>(index)] = 1U;
    }
  }
  for (int i = 0; i < total; ++i) {
    if (hidden_flags[static_cast<std::size_t>(i)] != 0U) {
      continue;
    }
    indices.push_back(i);
  }
  return indices;
}

int list_visible_count(
    const int total,
    const std::vector<int>& hidden_indices) {
  if (total <= 0) {
    return 0;
  }
  if (hidden_indices.empty()) {
    return total;
  }
  // Hidden lists are maintained as unique index sets by reducer helpers.
  int hidden_valid_count = 0;
  for (const int index : hidden_indices) {
    if (index >= 0 && index < total) {
      ++hidden_valid_count;
    }
  }
  hidden_valid_count = std::min(hidden_valid_count, total);
  return std::max(0, total - hidden_valid_count);
}

int list_item_count(const AppState& state) {
  const int inventory_total = static_cast<int>(state.dashboard.inventory_items.size());
  const int reminder_total = static_cast<int>(state.dashboard.reminder_items.size());
  return list_visible_count(inventory_total, state.home.hidden_inventory_indices) +
         list_visible_count(reminder_total, state.home.hidden_reminder_indices);
}

void clamp_memo_index(AppState& state) {
  const int total = static_cast<int>(state.dashboard.memos.size());
  if (total <= 0) {
    state.memo.index = 0;
    return;
  }
  int normalized = state.memo.index % total;
  if (normalized < 0) {
    normalized += total;
  }
  state.memo.index = normalized;
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

// Forward declaration — defined later in this file.
void enter_onboarding_wifi_select(AppState& state);

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
    case SettingsItem::SyncNow: {
      // If provider was never bootstrapped (WiFi not connected at boot),
      // try to bootstrap now using current WiFi connection.
      if (!platform::live_data_request_sync_now()) {
        if (platform::wifi_is_connected()) {
          ESP_LOGI(kTag, "[settings] sync_now: bootstrapping live_data first");
          platform::live_data_bootstrap(
              state.onboarding.timezone.c_str(),
              state.dashboard.location.c_str());
          platform::live_data_request_sync_now();
        }
      }
      if (platform::live_data_weather_sync_in_progress() ||
          state.settings.sync_state == "syncing") {
        // A sync is already running (possibly just triggered above).
        state.settings.sync_state = "syncing";
        state.home.weather_sync_state = "syncing";
        set_settings_notice(state, "SYNC REQUESTED", event.now_ms, 3000);
        ESP_LOGI(kTag, "[settings] sync_now=requested");
      } else if (!platform::wifi_is_connected()) {
        state.settings.sync_state = "error";
        set_settings_notice(state, "NO WI-FI — CONNECT FIRST", event.now_ms, 4000);
        ESP_LOGW(kTag, "[settings] sync_now=no_wifi");
      } else {
        // force_sync was set; task will pick it up on next poll.
        state.settings.sync_state = "syncing";
        state.home.weather_sync_state = "syncing";
        set_settings_notice(state, "SYNC REQUESTED", event.now_ms, 3000);
        ESP_LOGI(kTag, "[settings] sync_now=force_sync_set");
      }
      return;
    }
    case SettingsItem::ChangeWifi:
      enter_onboarding_wifi_select(state);
      state.onboarding.wifi_from_settings = true;
      ESP_LOGI(kTag, "[settings] change_wifi=entering wifi select");
      return;
    case SettingsItem::ResetAndWipe:
      if (state.settings.reset_pending) {
        // Second click — confirmed.  Reset all dashboard + home data to defaults.
        state.settings.reset_pending = false;
        const ProductDefaults factory = make_factory_defaults();
        state.dashboard = factory.dashboard;
        state.home.hidden_inventory_indices.clear();
        state.home.hidden_reminder_indices.clear();
        state.home.pending_hide_inventory_indices.clear();
        state.home.pending_hide_reminder_indices.clear();
        state.memo.index = 0;
        state.memo.expanded = false;
        set_settings_notice(state, "DATA RESET TO DEFAULTS", event.now_ms, 4000);
        ESP_LOGI(kTag, "[settings] reset_and_wipe=done");
      } else {
        // First click — request confirmation (expires after 5 s).
        state.settings.reset_pending = true;
        set_settings_notice(state, "CLICK AGAIN TO CONFIRM RESET", event.now_ms, 5000);
        ESP_LOGI(kTag, "[settings] reset_and_wipe=awaiting_confirm");
      }
      return;
  }
}

std::vector<int> visible_inventory_indices(const AppState& state) {
  std::vector<int> indices{};
  const int total = static_cast<int>(state.dashboard.inventory_items.size());
  const int visible_max = home_inventory_visible_max(state);
  indices.reserve(std::min(total, visible_max));
  for (int i = 0; i < total; ++i) {
    if (contains_index(state.home.hidden_inventory_indices, i)) {
      continue;
    }
    indices.push_back(i);
    if (static_cast<int>(indices.size()) >= visible_max) {
      break;
    }
  }
  return indices;
}

std::vector<int> visible_reminder_indices(const AppState& state) {
  std::vector<int> indices{};
  const int total = static_cast<int>(state.dashboard.reminder_items.size());
  const int visible_max = home_reminder_visible_max(state);
  indices.reserve(std::min(total, visible_max));
  for (int i = 0; i < total; ++i) {
    if (contains_index(state.home.hidden_reminder_indices, i)) {
      continue;
    }
    indices.push_back(i);
    if (static_cast<int>(indices.size()) >= visible_max) {
      break;
    }
  }
  return indices;
}

int home_inventory_count(const AppState& state) {
  return static_cast<int>(visible_inventory_indices(state).size());
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
  const std::vector<int> inventory_indices = visible_inventory_indices(state);
  if (pos < static_cast<int>(inventory_indices.size())) {
    return {HomeFocusTargetKind::InventoryItem, inventory_indices[static_cast<std::size_t>(pos)]};
  }
  pos -= static_cast<int>(inventory_indices.size());

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

void ensure_reminder_meta_items(
    std::vector<ReminderMetaItem>& reminder_meta,
    const std::size_t item_count) {
  if (reminder_meta.size() >= item_count) {
    return;
  }
  reminder_meta.resize(item_count, ReminderMetaItem{});
}

bool remove_inventory_visibility_tracking(
    AppState& state,
    const int item_index,
    const bool restore_visible) {
  if (item_index < 0) {
    return false;
  }
  bool changed = false;
  const auto pending_before = state.home.pending_hide_inventory_indices.size();
  remove_index(state.home.pending_hide_inventory_indices, item_index);
  if (state.home.pending_hide_inventory_indices.size() != pending_before) {
    changed = true;
  }

  if (restore_visible) {
    const auto hidden_before = state.home.hidden_inventory_indices.size();
    remove_index(state.home.hidden_inventory_indices, item_index);
    if (state.home.hidden_inventory_indices.size() != hidden_before) {
      changed = true;
    }
  }

  if (state.home.pending_hide_inventory_indices.empty() &&
      state.home.pending_hide_reminder_indices.empty()) {
    state.home.hide_due_ms = 0;
  }
  return changed;
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

  if (state.home.pending_hide_inventory_indices.empty() &&
      state.home.pending_hide_reminder_indices.empty()) {
    state.home.hide_due_ms = 0;
  }
  return changed;
}

void mark_pending_inventory_hide(
    AppState& state,
    const int item_index,
    const std::uint64_t now_ms) {
  if (item_index < 0) {
    return;
  }
  remove_index(state.home.hidden_inventory_indices, item_index);
  if (!contains_index(state.home.pending_hide_inventory_indices, item_index)) {
    state.home.pending_hide_inventory_indices.push_back(item_index);
  }
  const std::uint64_t base_ms = now_ms > 0 ? now_ms : state.last_tick_ms;
  state.home.hide_due_ms = base_ms + kHomeCompletedHideGraceMs;
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
  if (state.home.pending_hide_inventory_indices.empty() &&
      state.home.pending_hide_reminder_indices.empty()) {
    return false;
  }
  if (state.home.hide_due_ms == 0 || now_ms < state.home.hide_due_ms) {
    return false;
  }
  return (now_ms - state.home.last_interaction_ms) >= kHomeCompletedHideSettleMs;
}

bool promote_pending_reminder_hide(AppState& state) {
  if (state.home.pending_hide_inventory_indices.empty() &&
      state.home.pending_hide_reminder_indices.empty()) {
    return false;
  }
  bool changed = false;
  for (const int index : state.home.pending_hide_inventory_indices) {
    if (index < 0 ||
        index >= static_cast<int>(state.dashboard.inventory_items.size())) {
      continue;
    }
    if (!contains_index(state.home.hidden_inventory_indices, index)) {
      state.home.hidden_inventory_indices.push_back(index);
      changed = true;
    }
  }
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
  state.home.pending_hide_inventory_indices.clear();
  state.home.pending_hide_reminder_indices.clear();
  state.home.hide_due_ms = 0;
  return changed;
}

void schedule_reminder_reorder(
    AppState& state,
    const std::uint64_t now_ms,
    const char* source) {
  const std::uint64_t base_ms = now_ms > 0 ? now_ms : state.last_tick_ms;
  state.home.pending_reorder = true;
  state.home.reorder_due_ms = base_ms + kReminderReorderDelayMs;
  ESP_LOGI(
      kTag,
      "[link] reorder.schedule source=%s now_ms=%llu due_ms=%llu %s",
      source != nullptr ? source : "unknown",
      static_cast<unsigned long long>(base_ms),
      static_cast<unsigned long long>(state.home.reorder_due_ms),
      format_home_hide_state(state).c_str());
}

void cancel_reminder_reorder(
    AppState& state,
    const char* source) {
  if (!state.home.pending_reorder && state.home.reorder_due_ms == 0) {
    return;
  }
  state.home.pending_reorder = false;
  state.home.reorder_due_ms = 0;
  ESP_LOGI(
      kTag,
      "[link] reorder.cancel source=%s %s",
      source != nullptr ? source : "unknown",
      format_home_hide_state(state).c_str());
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

void apply_reminder_reorder(
    AppState& state,
    const std::uint64_t now_ms) {
  auto& reminders = state.dashboard.reminder_items;
  auto& completed = state.dashboard.reminder_completed;
  auto& reminder_meta = state.dashboard.reminder_meta;
  ensure_completion_flags(completed, reminders.size());
  ensure_reminder_meta_items(reminder_meta, reminders.size());
  const int item_count = static_cast<int>(reminders.size());
  const std::uint64_t due_ms = state.home.reorder_due_ms;
  const std::string hide_state_before = format_home_hide_state(state);

  if (item_count <= 1) {
    state.home.pending_reorder = false;
    state.home.reorder_due_ms = 0;
    ESP_LOGI(
        kTag,
        "[link] reorder.apply now_ms=%llu due_ms=%llu changed=0 reason=item_count<=1 %s",
        static_cast<unsigned long long>(now_ms),
        static_cast<unsigned long long>(due_ms),
        hide_state_before.c_str());
    return;
  }

  struct ReminderRow {
    std::string title{};
    bool done{false};
    ReminderMetaItem meta{};
    int old_index{0};
  };

  std::vector<ReminderRow> rows{};
  rows.reserve(static_cast<std::size_t>(item_count));
  for (int i = 0; i < item_count; ++i) {
    rows.push_back(ReminderRow{
        reminders[static_cast<std::size_t>(i)],
        completed[static_cast<std::size_t>(i)],
        reminder_meta[static_cast<std::size_t>(i)],
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
    ESP_LOGI(
        kTag,
        "[link] reorder.apply now_ms=%llu due_ms=%llu changed=0 reason=already_stable %s",
        static_cast<unsigned long long>(now_ms),
        static_cast<unsigned long long>(due_ms),
        hide_state_before.c_str());
    return;
  }

  for (int i = 0; i < item_count; ++i) {
    const auto& row = rows[static_cast<std::size_t>(i)];
    reminders[static_cast<std::size_t>(i)] = row.title;
    completed[static_cast<std::size_t>(i)] = row.done;
    reminder_meta[static_cast<std::size_t>(i)] = row.meta;
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
  ESP_LOGI(
      kTag,
      "[link] reorder.apply now_ms=%llu due_ms=%llu changed=1 before={%s} after={%s}",
      static_cast<unsigned long long>(now_ms),
      static_cast<unsigned long long>(due_ms),
      hide_state_before.c_str(),
      format_home_hide_state(state).c_str());
}

void enter_onboarding_start(AppState& state) {
  state.screen = Screen::Onboarding;
  state.onboarding.step_index = 0;
  state.onboarding.status.clear();
}

void enter_onboarding_wifi_select(AppState& state) {
  state.screen = Screen::Onboarding;
  state.onboarding.step_index    = 1;
  state.onboarding.wifi_sub_step = 0;
  state.onboarding.wifi_list_focus  = 0;
  state.onboarding.wifi_list_scroll = 0;
  state.onboarding.wifi_networks.clear();
  state.onboarding.status = "Scanning for networks...";

  // Scan synchronously — blocks ~2-4 s; fine for a one-time setup step.
  const auto aps = platform::wifi_scan_networks(4000);
  state.onboarding.wifi_scanning = false;
  if (aps.empty()) {
    state.onboarding.status = "No networks found. Rotate to retry or press SKIP.";
  } else {
    state.onboarding.wifi_networks.reserve(aps.size());
    for (const auto& ap : aps) {
      app::WifiScanEntry e;
      e.ssid = ap.ssid;
      e.rssi = ap.rssi;
      state.onboarding.wifi_networks.push_back(std::move(e));
    }
    state.onboarding.status = "Rotate to select network, press to confirm.";
  }
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

std::string normalized_calendar_mode(const std::string& raw_mode) {
  std::string out;
  out.reserve(raw_mode.size());
  for (const char ch : raw_mode) {
    out.push_back(static_cast<char>(std::tolower(static_cast<unsigned char>(ch))));
  }
  return out == "agenda" ? "agenda" : "date";
}

void open_calendar_from_home(AppState& state) {
  state.screen = Screen::Calendar;
  state.calendar.offset_days = 0;
  state.calendar.mode = "date";
  state.calendar.selected_index = 0;
  calendar_runtime::sync_calendar_cursor_fields(state);
}

void open_timer_from_home(AppState& state, const std::uint64_t now_ms) {
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
      open_timer_from_home(state, now_ms);
      return;
    case 3:
      open_calendar_from_home(state);
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
      if (state.onboarding.wifi_sub_step == 0)
        state.onboarding.status = "Rotate to select network, press to confirm.";
      else
        state.onboarding.status = "Rotate to select character, press to confirm.";
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
  if (platform::live_data_weather_sync_in_progress()) {
    state.home.weather_sync_state = "syncing";
    state.settings.sync_state = "syncing";
  }

  platform::WeatherSyncSample weather_sample{};
  if (platform::live_data_poll_weather(&weather_sample) && weather_sample.valid) {
    if (weather_sample.synced) {
      if (!weather_sample.location.empty()) {
        state.dashboard.location = weather_sample.location;
      }
      if (!weather_sample.condition.empty()) {
        state.dashboard.weather_condition = weather_sample.condition;
      }
      if (!weather_sample.icon.empty()) {
        state.dashboard.weather_icon = weather_sample.icon;
      }
      state.dashboard.weather_temperature_c = weather_sample.temperature_c;
      state.dashboard.weather_humidity_percent = weather_sample.humidity_percent;
      state.dashboard.weather_feels_like_c = weather_sample.feels_like_c;
      state.dashboard.weather_hi_c = weather_sample.hi_c;
      state.dashboard.weather_lo_c = weather_sample.lo_c;
      state.dashboard.weather_wind_kmh = weather_sample.wind_kmh;
      state.dashboard.weather_uv_index = weather_sample.uv_index;
      for (std::size_t i = 0; i < state.dashboard.weather_forecast_days.size(); ++i) {
        state.dashboard.weather_forecast_days[i].dow = weather_sample.forecast_days[i].dow;
        state.dashboard.weather_forecast_days[i].condition = weather_sample.forecast_days[i].condition;
        state.dashboard.weather_forecast_days[i].icon = weather_sample.forecast_days[i].icon;
        state.dashboard.weather_forecast_days[i].hi_c = weather_sample.forecast_days[i].hi_c;
        state.dashboard.weather_forecast_days[i].lo_c = weather_sample.forecast_days[i].lo_c;
      }
      state.home.weather_sync_state = "ok";
      state.settings.sync_state = "ok";
      state.settings.last_sync_ms =
          static_cast<std::uint64_t>(
              std::max<std::time_t>(0, weather_sample.observed_unix_seconds)) *
          1000ULL;
      ESP_LOGI(
          kTag,
          "[weather] sync_ok source=%s location=%s temp=%dC humidity=%d%% condition=%s",
          weather_sample.source.empty() ? "unknown" : weather_sample.source.c_str(),
          weather_sample.location.empty() ? "Unknown" : weather_sample.location.c_str(),
          weather_sample.temperature_c,
          weather_sample.humidity_percent,
          weather_sample.condition.c_str());
    } else {
      if (!state.dashboard.weather_condition.empty()) {
        state.home.weather_sync_state = "ok";
      } else {
        state.home.weather_sync_state = "unsynced";
      }
      state.settings.sync_state =
          state.home.weather_sync_state == "ok" ? "ok" : "error";
      ESP_LOGW(
          kTag,
          "[weather] sync_failed error=%s",
          weather_sample.error.empty() ? "unknown" : weather_sample.error.c_str());
    }
  }

  const std::time_t wall = platform::wall_time_seconds();
  if (platform::wall_time_is_valid()) {
    state.home.clock_minute_bucket = static_cast<std::uint64_t>(wall / 60);
    state.home.clock_is_real = true;
    state.home.clock_seed_monotonic_ms = event.now_ms;
    state.home.clock_sync_state = "real_synced";
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
    apply_reminder_reorder(state, event.now_ms);
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

  if (home_hide_ready(state, event.now_ms)) {
    const std::string hide_state_before = format_home_hide_state(state);
    if (promote_pending_reminder_hide(state)) {
      ESP_LOGI(
          kTag,
          "[link] hide.promote now_ms=%llu before={%s} after={%s}",
          static_cast<unsigned long long>(event.now_ms),
          hide_state_before.c_str(),
          format_home_hide_state(state).c_str());
      if (state.screen == Screen::Home) {
        clamp_home_focus(state);
      } else if (state.screen == Screen::Inventory) {
        clamp_list_focus(state);
      }
    }
  }

  if (!state.settings.notice.empty() &&
      state.settings.notice_due_ms > 0 &&
      event.now_ms >= state.settings.notice_due_ms) {
    state.settings.notice.clear();
    state.settings.notice_due_ms = 0;
    // If the reset confirmation notice expired, cancel the pending reset.
    state.settings.reset_pending = false;
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
      if (state.onboarding.wifi_sub_step == 0) {
        // Scroll through WiFi list.
        const int n = static_cast<int>(state.onboarding.wifi_networks.size());
        if (n > 0) {
          const int next = static_cast<int>(state.onboarding.wifi_list_focus) + delta;
          state.onboarding.wifi_list_focus =
              static_cast<std::size_t>(next < 0 ? 0 : (next >= n ? n - 1 : next));
          // Keep focused item inside the 5-row visible window.
          constexpr int kVisible = 5;
          const int focus = static_cast<int>(state.onboarding.wifi_list_focus);
          const int scroll = static_cast<int>(state.onboarding.wifi_list_scroll);
          if (focus < scroll)
            state.onboarding.wifi_list_scroll = static_cast<std::size_t>(focus);
          else if (focus >= scroll + kVisible)
            state.onboarding.wifi_list_scroll = static_cast<std::size_t>(focus - kVisible + 1);
        }
      } else {
        // Move keyboard focus (wraps around all 44 keys).
        const int n    = static_cast<int>(kOnboardingKbdKeyCount);
        const int next = (static_cast<int>(state.onboarding.kbd_focus) + delta + n) % n;
        state.onboarding.kbd_focus = static_cast<std::size_t>(next);
      }
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

  if (state.screen == Screen::Calendar) {
    const int delta = event.rotate_delta >= 0 ? 1 : -1;
    state.calendar.mode = normalized_calendar_mode(state.calendar.mode);
    if (state.calendar.mode == "agenda") {
      const auto base_date = calendar_runtime::today_local_date(state);
      const auto selection = calendar_runtime::agenda_selection_for_cursor(state, base_date);
      const int agenda_count =
          static_cast<int>(selection.event_indices.size() + selection.reminder_indices.size());
      if (agenda_count <= 0) {
        state.calendar.mode = "date";
        state.calendar.selected_index = 0;
      } else {
        const int next_index = state.calendar.selected_index + delta;
        if (next_index < 0 || next_index >= agenda_count) {
          // Product behavior: rotating past agenda bounds exits back to date mode.
          state.calendar.mode = "date";
          state.calendar.selected_index = 0;
        } else {
          state.calendar.selected_index = next_index;
        }
      }
      return;
    }

    state.calendar.offset_days += delta;
    state.calendar.selected_index = 0;
    calendar_runtime::sync_calendar_cursor_fields(state);
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
        enter_onboarding_wifi_select(state);
      } else {
        enter_onboarding_prefs(state, false);
      }
      return;
    }
    if (state.onboarding.step_index == 1) {
      if (state.onboarding.wifi_sub_step == 0) {
        // ── Select SSID ──────────────────────────────────────────────────
        if (state.onboarding.wifi_networks.empty()) {
          // No networks — re-scan.
          enter_onboarding_wifi_select(state);
        } else {
          const auto& ap =
              state.onboarding.wifi_networks[state.onboarding.wifi_list_focus];
          state.onboarding.wifi_ssid     = ap.ssid;
          state.onboarding.wifi_sub_step = 1;
          state.onboarding.wifi_password.clear();
          state.onboarding.kbd_focus = 0;
          state.onboarding.kbd_shift = false;
          state.onboarding.wifi_connect_error.clear();
          state.onboarding.status =
              "Rotate to select character, press to type.";
        }
      } else {
        // ── QWERTY keyboard ──────────────────────────────────────────────
        // Key index layout (44 total):
        //   0-9  : row0 "1234567890" (shift: "!@#$%^&*()")
        //   10-19: row1 "qwertyuiop" (shift: uppercase)
        //   20-28: row2 "asdfghjkl"  (shift: uppercase)
        //   29-35: row3 "zxcvbnm"    (shift: uppercase)
        //   36: SHIFT  37: '-'  38: '_'  39: '.'  40: '@'
        //   41: SPACE  42: DEL  43: OK
        static constexpr const char* kRow0N = "1234567890";
        static constexpr const char* kRow0S = "!@#$%^&*()";
        static constexpr const char* kRow1  = "qwertyuiop";
        static constexpr const char* kRow2  = "asdfghjkl";
        static constexpr const char* kRow3  = "zxcvbnm";

        const std::size_t k = state.onboarding.kbd_focus;
        const bool shift    = state.onboarding.kbd_shift;

        char typed = '\0';
        if (k < 10) {
          typed = shift ? kRow0S[k] : kRow0N[k];
        } else if (k < 20) {
          const char base = kRow1[k - 10];
          typed = shift ? static_cast<char>(base - 32) : base;
        } else if (k < 29) {
          const char base = kRow2[k - 20];
          typed = shift ? static_cast<char>(base - 32) : base;
        } else if (k < 36) {
          const char base = kRow3[k - 29];
          typed = shift ? static_cast<char>(base - 32) : base;
        } else if (k == 36) {
          state.onboarding.kbd_shift = !shift;  // toggle SHIFT
        } else if (k == 37) { typed = '-';
        } else if (k == 38) { typed = '_';
        } else if (k == 39) { typed = '.';
        } else if (k == 40) { typed = '@';
        } else if (k == 41) { typed = ' ';
        } else if (k == 42) {
          // DEL
          if (!state.onboarding.wifi_password.empty())
            state.onboarding.wifi_password.pop_back();
        } else if (k == 43) {
          // OK — attempt connection
          state.onboarding.wifi_connecting = true;
          state.onboarding.wifi_connect_error.clear();
          state.onboarding.status = "Connecting...";
          const bool ok = platform::wifi_connect_to(
              state.onboarding.wifi_ssid.c_str(),
              state.onboarding.wifi_password.c_str(),
              15000);
          state.onboarding.wifi_connecting = false;
          if (ok) {
            if (state.onboarding.wifi_from_settings) {
              // Return to Settings with a confirmation notice.
              state.screen = Screen::Settings;
              state.onboarding.wifi_from_settings = false;
              set_settings_notice(state,
                  "WI-FI: " + state.onboarding.wifi_ssid, event.now_ms);
              ESP_LOGI(kTag, "[settings] wifi updated to \"%s\"",
                       state.onboarding.wifi_ssid.c_str());
            } else {
              enter_onboarding_prefs(state, /*wifi_connected=*/true);
            }
          } else {
            state.onboarding.wifi_connect_error =
                "Connection failed. Check password and try again.";
            state.onboarding.status = state.onboarding.wifi_connect_error;
          }
        }

        // Append typed character and auto-clear shift after a letter.
        if (typed != '\0') {
          state.onboarding.wifi_password += typed;
          if (shift && k >= 10 && k <= 35)
            state.onboarding.kbd_shift = false;  // auto-release shift after letter
        }
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
        // prefs_focus_index == 3 → "ENTER HOME" button → finish onboarding.
        enter_home(state);
        return;
      }
      refresh_onboarding_status(state);
      return;
    }
    // step_index == 3 (voice guide, reachable only via serial 'g' shortcut):
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
          // Python parity (default kitchen_left_click_action="weather"):
          // clock click enters timer page when Home widget is in timer mode.
          open_timer_from_home(state, event.now_ms);
          return;
        }
        state.home.menu_overlay_active = false;
        open_calendar_from_home(state);
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
          const std::size_t index = static_cast<std::size_t>(target.item_index);
          const bool next_completed = !state.dashboard.inventory_completed[index];
          state.dashboard.inventory_completed[index] = next_completed;
          if (next_completed) {
            mark_pending_inventory_hide(state, target.item_index, event.now_ms);
          } else {
            remove_inventory_visibility_tracking(state, target.item_index, true);
          }
          ESP_LOGI(
              kTag,
              "[link] toggle source=home.inventory index=%d completed=%d %s",
              target.item_index,
              next_completed ? 1 : 0,
              format_home_hide_state(state).c_str());
        }
        // Python parity: Home toggle path clears delayed reminder reorder.
        cancel_reminder_reorder(state, "home.inventory");
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
          // Python parity: Home toggle path does not schedule delayed reorder.
          cancel_reminder_reorder(state, "home.reminder");
          ESP_LOGI(
              kTag,
              "[link] toggle source=home.reminder index=%d completed=%d %s",
              target.item_index,
              state.dashboard.reminder_completed[index] ? 1 : 0,
              format_home_hide_state(state).c_str());
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

  if (state.screen == Screen::Calendar) {
    state.calendar.mode = normalized_calendar_mode(state.calendar.mode);
    const auto base_date = calendar_runtime::today_local_date(state);
    const auto selection = calendar_runtime::agenda_selection_for_cursor(state, base_date);
    const int event_count = static_cast<int>(selection.event_indices.size());
    const int reminder_count = static_cast<int>(selection.reminder_indices.size());
    const int agenda_count = event_count + reminder_count;

    if (state.calendar.mode != "agenda") {
      state.calendar.mode = "agenda";
      state.calendar.selected_index = 0;
      return;
    }

    if (agenda_count <= 0) {
      state.calendar.mode = "date";
      state.calendar.selected_index = 0;
      return;
    }

    state.calendar.selected_index = clamp_int(state.calendar.selected_index, 0, agenda_count - 1);
    if (state.calendar.selected_index < event_count) {
      // Calendar events are read-only in agenda mode.
      // Python parity: click on a non-toggle agenda row exits back to date mode.
      state.calendar.mode = "date";
      state.calendar.selected_index = 0;
      return;
    }

    const int reminder_slot = state.calendar.selected_index - event_count;
    if (reminder_slot < 0 || reminder_slot >= reminder_count) {
      state.calendar.mode = "date";
      state.calendar.selected_index = 0;
      return;
    }

    const int reminder_index = selection.reminder_indices[static_cast<std::size_t>(reminder_slot)];
    ensure_completion_flags(
        state.dashboard.reminder_completed,
        state.dashboard.reminder_items.size());
    if (reminder_index < 0 ||
        reminder_index >= static_cast<int>(state.dashboard.reminder_completed.size())) {
      state.calendar.mode = "date";
      state.calendar.selected_index = 0;
      return;
    }

    const std::size_t idx = static_cast<std::size_t>(reminder_index);
    const bool next_completed = !state.dashboard.reminder_completed[idx];
    state.dashboard.reminder_completed[idx] = next_completed;
    if (next_completed) {
      mark_pending_reminder_hide(state, reminder_index, event.now_ms);
    } else {
      remove_reminder_visibility_tracking(state, reminder_index, true);
    }
    schedule_reminder_reorder(state, event.now_ms, "calendar");
    ESP_LOGI(
        kTag,
        "[link] toggle source=calendar.reminder index=%d completed=%d %s",
        reminder_index,
        next_completed ? 1 : 0,
        format_home_hide_state(state).c_str());
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
    const std::vector<int> inventory_indices = list_visible_inventory_indices(state);
    const std::vector<int> reminder_indices = list_visible_reminder_indices(state);
    const int inventory_count = static_cast<int>(inventory_indices.size());
    const int reminder_count = static_cast<int>(reminder_indices.size());
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
      const int index =
          inventory_indices[static_cast<std::size_t>(state.inventory.focused_index)];
      const bool next_completed =
          !state.dashboard.inventory_completed[static_cast<std::size_t>(index)];
      state.dashboard.inventory_completed[static_cast<std::size_t>(index)] = next_completed;
      if (next_completed) {
        mark_pending_inventory_hide(state, index, event.now_ms);
      } else {
        remove_inventory_visibility_tracking(state, index, true);
      }
      ESP_LOGI(
          kTag,
          "[link] toggle source=list.inventory index=%d completed=%d %s",
          index,
          next_completed ? 1 : 0,
          format_home_hide_state(state).c_str());
      return;
    }

    const int reminder_slot = state.inventory.focused_index - inventory_count;
    if (reminder_slot < 0 || reminder_slot >= reminder_count) {
      return;
    }
    const int reminder_index =
        reminder_indices[static_cast<std::size_t>(reminder_slot)];
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
    if (next_completed) {
      mark_pending_reminder_hide(state, reminder_index, event.now_ms);
    } else {
      remove_reminder_visibility_tracking(state, reminder_index, true);
    }
    ESP_LOGI(
        kTag,
        "[link] toggle source=list.reminder index=%d completed=%d %s",
        reminder_index,
        next_completed ? 1 : 0,
        format_home_hide_state(state).c_str());
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

  // Onboarding voice guide: long-press starts the voice test recording.
  // main.cpp also calls trigger_voice_recording() for the actual capture.
  if (state.screen == Screen::Onboarding && state.onboarding.step_index == 3) {
    if (!state.onboarding.voice_recording) {
      state.onboarding.voice_recording = true;
      state.onboarding.voice_last_result.clear();
      state.onboarding.status = "Recording...";
    }
    return;
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
    // Python parity: Back on Home cancels timer when clock is focused.
    if (state.home.widget_mode == WidgetMode::Timer &&
        state.home.focused_index == 0) {
      const std::uint64_t base_ms = event.now_ms > 0 ? event.now_ms : state.last_tick_ms;
      state.timer.running = false;
      state.home.widget_mode = WidgetMode::Clock;
      state.timer.seconds_remaining = 0;
      state.timer.target_seconds = 0;
      state.timer.last_tick_ms = base_ms;
      clear_timer_alert(state);
      return;
    }
    state.home.menu_overlay_active = true;
    return;
  }

  // Onboarding: back navigates within the wizard, never exits to Home.
  if (state.screen == Screen::Onboarding) {
    if (state.onboarding.step_index == 1 && state.onboarding.wifi_sub_step == 1) {
      // Password entry → back to WiFi list.
      state.onboarding.wifi_sub_step = 0;
      state.onboarding.wifi_password.clear();
      state.onboarding.wifi_connect_error.clear();
      state.onboarding.kbd_focus = 0;
      state.onboarding.kbd_shift = false;
    } else if (state.onboarding.wifi_from_settings) {
      // Launched from Settings → return there instead of going to step 0.
      state.screen = Screen::Settings;
      state.onboarding.wifi_from_settings = false;
    } else if (state.onboarding.step_index > 0) {
      state.onboarding.step_index -= 1;
      state.onboarding.wifi_sub_step = 0;
    }
    // step 0 (start): ignore back — nowhere to go
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

// ── Voice action dispatch ─────────────────────────────────────────────────────

namespace {

// Minimal JSON string extractor (same approach as voice_client.cpp).
static std::string va_extract_string(const std::string& json, const char* key) {
  const std::string search = std::string("\"") + key + "\":\"";
  const size_t pos = json.find(search);
  if (pos == std::string::npos) return {};
  const size_t start = pos + search.size();
  const size_t end   = json.find('"', start);
  if (end == std::string::npos) return {};
  return json.substr(start, end - start);
}

static int va_extract_int(const std::string& json, const char* key) {
  const std::string search = std::string("\"") + key + "\":";
  const size_t pos = json.find(search);
  if (pos == std::string::npos) return 0;
  size_t start = pos + search.size();
  while (start < json.size() && (json[start] == ' ' || json[start] == '\t')) start++;
  if (start >= json.size()) return 0;
  // Parse digits manually — avoids std::stoi exceptions on ESP32.
  int result = 0;
  bool found = false;
  for (size_t i = start; i < json.size(); i++) {
    if (json[i] >= '0' && json[i] <= '9') {
      result = result * 10 + (json[i] - '0');
      found = true;
    } else {
      break;
    }
  }
  return found ? result : 0;
}

// Find the first visible index whose label contains `item_name` (case-insensitive).
static int find_item_index(const std::vector<std::string>& items,
                           const std::vector<int>& hidden,
                           const std::string& item_name) {
  const std::string needle = [&] {
    std::string s = item_name;
    std::transform(s.begin(), s.end(), s.begin(), ::tolower);
    return s;
  }();
  for (int i = 0; i < static_cast<int>(items.size()); i++) {
    if (contains_index(hidden, i)) continue;
    std::string label = items[i];
    std::transform(label.begin(), label.end(), label.begin(), ::tolower);
    if (label.find(needle) != std::string::npos) return i;
  }
  return -1;
}

static void va_open_app(AppState& state, const std::string& args) {
  const std::string app = va_extract_string(args, "app");
  if      (app == "home")      { state.screen = Screen::Home;      }
  else if (app == "weather")   { state.screen = Screen::Weather;   }
  else if (app == "calendar")  { state.screen = Screen::Calendar;  }
  else if (app == "timer")     { state.screen = Screen::Timer;     }
  else if (app == "memo")      { state.screen = Screen::Memo;      }
  else if (app == "reminders") { state.screen = Screen::Inventory; }
  else if (app == "inventory") { state.screen = Screen::Inventory; }
  else if (app == "settings")  { state.screen = Screen::Settings;  }
  else {
    ESP_LOGW(kTag, "[voice] open_app: unknown app \"%s\"", app.c_str());
    return;
  }
  // Close menu overlay if open.
  state.home.menu_overlay_active = false;
  ESP_LOGI(kTag, "[voice] open_app: navigated to \"%s\"", app.c_str());
}

static void va_shopping_add_item(AppState& state, const std::string& args) {
  std::string item = va_extract_string(args, "item_name");
  if (item.empty()) item = va_extract_string(args, "item");
  if (item.empty()) {
    ESP_LOGW(kTag, "[voice] shopping_add_item: missing item_name");
    return;
  }
  // Check if item already exists but is hidden — unhide it instead of duplicating.
  for (int i = 0; i < static_cast<int>(state.dashboard.reminder_items.size()); i++) {
    std::string label = state.dashboard.reminder_items[i];
    std::string needle = item;
    std::transform(label.begin(),  label.end(),  label.begin(),  ::tolower);
    std::transform(needle.begin(), needle.end(), needle.begin(), ::tolower);
    if (label.find(needle) != std::string::npos &&
        contains_index(state.home.hidden_reminder_indices, i)) {
      remove_index(state.home.hidden_reminder_indices, i);
      remove_index(state.home.pending_hide_reminder_indices, i);
      ESP_LOGI(kTag, "[voice] shopping_add_item: unhid existing \"%s\" at [%d]", item.c_str(), i);
      return;
    }
  }
  // New item — append to reminder list.
  state.dashboard.reminder_items.push_back(item);
  state.dashboard.reminder_completed.push_back(false);
  state.dashboard.reminder_meta.push_back({});
  ESP_LOGI(kTag, "[voice] shopping_add_item: added \"%s\"", item.c_str());
}

static void va_shopping_remove_item(AppState& state, const std::string& args) {
  std::string item = va_extract_string(args, "item_name");
  if (item.empty()) item = va_extract_string(args, "item");
  if (item.empty()) {
    ESP_LOGW(kTag, "[voice] shopping_remove_item: missing item_name — ignoring");
    return;
  }
  const std::string source = va_extract_string(args, "source");

  // Helper to hide by index in reminder list.
  auto hide_reminder = [&](int idx) {
    if (!contains_index(state.home.hidden_reminder_indices, idx)) {
      state.home.hidden_reminder_indices.push_back(idx);
      ESP_LOGI(kTag, "[voice] shopping_remove_item: hid reminder[%d]", idx);
    }
  };
  // Helper to hide by index in inventory list.
  auto hide_inventory = [&](int idx) {
    if (!contains_index(state.home.hidden_inventory_indices, idx)) {
      state.home.hidden_inventory_indices.push_back(idx);
      ESP_LOGI(kTag, "[voice] shopping_remove_item: hid inventory[%d]", idx);
    }
  };

  // Search preferred source first, then fall back to the other list.
  if (source == "inventory") {
    int idx = find_item_index(state.dashboard.inventory_items,
                              state.home.hidden_inventory_indices, item);
    if (idx >= 0) { hide_inventory(idx); return; }
    // Fallback: check reminders too.
    idx = find_item_index(state.dashboard.reminder_items,
                          state.home.hidden_reminder_indices, item);
    if (idx >= 0) { hide_reminder(idx); return; }
  } else {
    // Default: reminders first, then inventory.
    int idx = find_item_index(state.dashboard.reminder_items,
                              state.home.hidden_reminder_indices, item);
    if (idx >= 0) { hide_reminder(idx); return; }
    idx = find_item_index(state.dashboard.inventory_items,
                          state.home.hidden_inventory_indices, item);
    if (idx >= 0) { hide_inventory(idx); return; }
  }
  ESP_LOGW(kTag, "[voice] shopping_remove_item: \"%s\" not found in any list", item.c_str());
}

static void va_timer_set(AppState& state, const std::string& args) {
  int secs = va_extract_int(args, "duration_seconds");
  if (secs <= 0) {
    ESP_LOGW(kTag, "[voice] timer_set: invalid duration_seconds");
    return;
  }
  constexpr int kTimerMaxSecs = 5999;  // 99:59
  if (secs > kTimerMaxSecs) secs = kTimerMaxSecs;
  state.timer.seconds_remaining = secs;
  state.timer.target_seconds    = secs;
  state.timer.running           = true;
  state.timer.alert_active      = false;
  state.screen                  = Screen::Timer;
  ESP_LOGI(kTag, "[voice] timer_set: %d s — navigating to Timer screen", secs);
}

static void va_memo_add(AppState& state, const std::string& args) {
  std::string text = va_extract_string(args, "text");
  if (text.empty()) text = va_extract_string(args, "memo_text");
  if (text.empty()) text = va_extract_string(args, "content");
  if (text.empty()) {
    ESP_LOGW(kTag, "[voice] memo_add: missing text");
    return;
  }
  std::string author = va_extract_string(args, "author");
  if (author.empty()) author = "Voice";

  MemoItem item;
  item.text    = std::move(text);
  item.author  = std::move(author);
  item.posted  = "Just now";
  item.is_new  = true;

  // Prepend so the new memo shows first.
  state.dashboard.memos.insert(state.dashboard.memos.begin(), item);
  // Keep family_memo fields in sync with the first memo.
  state.dashboard.family_memo_text   = state.dashboard.memos.front().text;
  state.dashboard.family_memo_author = state.dashboard.memos.front().author;
  state.dashboard.family_memo_posted = state.dashboard.memos.front().posted;
  // Navigate to memo screen so user sees the new note.
  state.screen = Screen::Memo;
  state.memo.index = 0;
  ESP_LOGI(kTag, "[voice] memo_add: added \"%s\" by %s",
           item.text.c_str(), item.author.c_str());
}

static void va_memo_delete(AppState& state, const std::string& args) {
  // Backend sends position: "first", "last", or index.
  const std::string position = va_extract_string(args, "position");
  if (state.dashboard.memos.empty()) {
    ESP_LOGW(kTag, "[voice] memo_delete: no memos to delete");
    return;
  }
  int idx = 0;
  if (position == "last") {
    idx = static_cast<int>(state.dashboard.memos.size()) - 1;
  } else {
    // Backend emits 1-based index; convert to 0-based.
    const int n = va_extract_int(args, "index");
    if (n >= 1 && n <= static_cast<int>(state.dashboard.memos.size())) idx = n - 1;
  }
  ESP_LOGI(kTag, "[voice] memo_delete: removed memo[%d] \"%s\"",
           idx, state.dashboard.memos[idx].text.c_str());
  state.dashboard.memos.erase(state.dashboard.memos.begin() + idx);
  if (!state.dashboard.memos.empty()) {
    state.dashboard.family_memo_text   = state.dashboard.memos.front().text;
    state.dashboard.family_memo_author = state.dashboard.memos.front().author;
    state.dashboard.family_memo_posted = state.dashboard.memos.front().posted;
  } else {
    state.dashboard.family_memo_text.clear();
    state.dashboard.family_memo_author.clear();
    state.dashboard.family_memo_posted.clear();
  }
}

static void va_memo_clear_all(AppState& state, const std::string& /*args*/) {
  state.dashboard.memos.clear();
  state.dashboard.family_memo_text.clear();
  state.dashboard.family_memo_author.clear();
  state.dashboard.family_memo_posted.clear();
  ESP_LOGI(kTag, "[voice] memo_clear_all: cleared all memos");
}

static void va_timer_add(AppState& state, const std::string& args) {
  int delta = va_extract_int(args, "delta_seconds");
  if (delta <= 0) delta = va_extract_int(args, "seconds");
  if (delta <= 0) {
    ESP_LOGW(kTag, "[voice] timer_add: missing delta_seconds");
    return;
  }
  constexpr int kTimerMaxSecs = 5999;
  state.timer.seconds_remaining =
      std::min(state.timer.seconds_remaining + delta, kTimerMaxSecs);
  state.timer.target_seconds = state.timer.seconds_remaining;
  state.screen = Screen::Timer;
  ESP_LOGI(kTag, "[voice] timer_add: +%d s → %d s remaining", delta,
           state.timer.seconds_remaining);
}

static void va_timer_pause(AppState& state, const std::string& /*args*/) {
  if (!state.timer.running) {
    ESP_LOGW(kTag, "[voice] timer_pause: timer not running");
    return;
  }
  state.timer.running = false;
  state.screen = Screen::Timer;
  ESP_LOGI(kTag, "[voice] timer_pause: paused at %d s", state.timer.seconds_remaining);
}

static void va_timer_resume(AppState& state, const std::string& /*args*/) {
  if (state.timer.running) {
    ESP_LOGW(kTag, "[voice] timer_resume: already running");
    return;
  }
  if (state.timer.seconds_remaining <= 0) {
    ESP_LOGW(kTag, "[voice] timer_resume: nothing to resume");
    return;
  }
  state.timer.running = true;
  state.timer.alert_active = false;
  state.screen = Screen::Timer;
  ESP_LOGI(kTag, "[voice] timer_resume: resumed at %d s", state.timer.seconds_remaining);
}

static void va_timer_stop(AppState& state, const std::string& /*args*/) {
  state.timer.running = false;
  state.timer.alert_active = false;
  state.timer.seconds_remaining = 0;
  state.screen = Screen::Timer;
  ESP_LOGI(kTag, "[voice] timer_stop: stopped");
}

static void va_shopping_clear_all(AppState& state, const std::string& /*args*/) {
  // Hide all visible reminder items.
  state.home.hidden_reminder_indices.clear();
  for (int i = 0; i < static_cast<int>(state.dashboard.reminder_items.size()); i++) {
    state.home.hidden_reminder_indices.push_back(i);
  }
  state.home.pending_hide_reminder_indices.clear();
  ESP_LOGI(kTag, "[voice] shopping_clear_all: hid %zu items",
           state.dashboard.reminder_items.size());
}

static void va_inventory_clear_all(AppState& state, const std::string& /*args*/) {
  state.home.hidden_inventory_indices.clear();
  for (int i = 0; i < static_cast<int>(state.dashboard.inventory_items.size()); i++) {
    state.home.hidden_inventory_indices.push_back(i);
  }
  state.home.pending_hide_inventory_indices.clear();
  ESP_LOGI(kTag, "[voice] inventory_clear_all: hid %zu items",
           state.dashboard.inventory_items.size());
}

static void va_inventory_set_expiry(AppState& state, const std::string& args) {
  std::string item = va_extract_string(args, "item_name");
  if (item.empty()) item = va_extract_string(args, "item");
  const std::string expiry = va_extract_string(args, "expiry_date");
  if (item.empty() || expiry.empty()) {
    ESP_LOGW(kTag, "[voice] inventory_set_expiry: missing item or expiry_date");
    return;
  }
  // Find item in inventory badges vector and update it.
  const int idx = find_item_index(state.dashboard.inventory_items,
                                  state.home.hidden_inventory_indices, item);
  if (idx < 0) {
    ESP_LOGW(kTag, "[voice] inventory_set_expiry: \"%s\" not found", item.c_str());
    return;
  }
  while (static_cast<int>(state.dashboard.inventory_badges.size()) <= idx) {
    state.dashboard.inventory_badges.push_back("");
  }
  state.dashboard.inventory_badges[idx] = expiry;
  ESP_LOGI(kTag, "[voice] inventory_set_expiry: \"%s\" → \"%s\"",
           item.c_str(), expiry.c_str());
}

static void va_memo_update(AppState& state, const std::string& args) {
  std::string text = va_extract_string(args, "text");
  if (text.empty()) text = va_extract_string(args, "new_text");
  if (text.empty()) text = va_extract_string(args, "content");
  if (text.empty()) {
    ESP_LOGW(kTag, "[voice] memo_update: missing text");
    return;
  }
  if (state.dashboard.memos.empty()) {
    ESP_LOGW(kTag, "[voice] memo_update: no memos");
    return;
  }
  // Default: update the first (most recent) memo.
  int idx = 0;
  const std::string position = va_extract_string(args, "position");
  if (position == "last") idx = static_cast<int>(state.dashboard.memos.size()) - 1;
  // Backend emits 1-based index; convert to 0-based.
  const int n = va_extract_int(args, "index");
  if (n >= 1 && n <= static_cast<int>(state.dashboard.memos.size())) idx = n - 1;

  state.dashboard.memos[idx].text   = text;
  state.dashboard.memos[idx].is_new = true;
  if (idx == 0) state.dashboard.family_memo_text = text;
  state.screen = Screen::Memo;
  state.memo.index = idx;
  ESP_LOGI(kTag, "[voice] memo_update: updated memo[%d] → \"%s\"", idx, text.c_str());
}

static void va_inventory_log_event(AppState& state, const std::string& args) {
  // Backend sends "item_name" or "item"; event sent as "event_type" or "event".
  std::string item = va_extract_string(args, "item_name");
  if (item.empty()) item = va_extract_string(args, "item");
  std::string event = va_extract_string(args, "event_type");
  if (event.empty()) event = va_extract_string(args, "event");
  if (item.empty()) {
    ESP_LOGW(kTag, "[voice] inventory_log_event: missing item");
    return;
  }
  if (event == "removed" || event == "used" || event == "consumed" || event == "finished") {
    // Try inventory first, then reminder list (AI sometimes conflates them).
    int idx = find_item_index(state.dashboard.inventory_items,
                              state.home.hidden_inventory_indices, item);
    if (idx >= 0) {
      state.home.hidden_inventory_indices.push_back(idx);
      ESP_LOGI(kTag, "[voice] inventory_log_event: removed \"%s\" from inventory", item.c_str());
    } else {
      idx = find_item_index(state.dashboard.reminder_items,
                            state.home.hidden_reminder_indices, item);
      if (idx >= 0) {
        state.home.hidden_reminder_indices.push_back(idx);
        ESP_LOGI(kTag, "[voice] inventory_log_event: removed \"%s\" from reminders", item.c_str());
      } else {
        ESP_LOGW(kTag, "[voice] inventory_log_event: \"%s\" not found anywhere", item.c_str());
      }
    }
  } else {
    // "added" or unknown — add to inventory list.
    state.dashboard.inventory_items.push_back(item);
    state.dashboard.inventory_completed.push_back(false);
    ESP_LOGI(kTag, "[voice] inventory_log_event: added \"%s\" to inventory (event=%s)",
             item.c_str(), event.c_str());
  }
}

// ── Undo / redo snapshot ─────────────────────────────────────────────────────

struct VoiceSnapshot {
  // Dashboard lists
  std::vector<std::string> reminder_items;
  std::vector<bool>        reminder_completed;
  std::vector<ReminderMetaItem> reminder_meta;
  std::vector<std::string> inventory_items;
  std::vector<std::string> inventory_badges;
  std::vector<bool>        inventory_completed;
  std::vector<MemoItem>    memos;
  std::string              family_memo_text;
  std::string              family_memo_author;
  std::string              family_memo_posted;
  // Home hidden indices
  std::vector<int> hidden_reminder_indices;
  std::vector<int> hidden_inventory_indices;
  std::vector<int> pending_hide_reminder_indices;
  std::vector<int> pending_hide_inventory_indices;
  // Timer
  bool running{false};
  int  seconds_remaining{0};
  int  target_seconds{0};
  bool alert_active{false};
  // Navigation
  Screen screen{Screen::Home};
  int    memo_index{0};
};

static VoiceSnapshot capture_snapshot(const AppState& s) {
  VoiceSnapshot snap;
  snap.reminder_items    = s.dashboard.reminder_items;
  snap.reminder_completed= s.dashboard.reminder_completed;
  snap.reminder_meta     = s.dashboard.reminder_meta;
  snap.inventory_items   = s.dashboard.inventory_items;
  snap.inventory_badges  = s.dashboard.inventory_badges;
  snap.inventory_completed = s.dashboard.inventory_completed;
  snap.memos             = s.dashboard.memos;
  snap.family_memo_text  = s.dashboard.family_memo_text;
  snap.family_memo_author= s.dashboard.family_memo_author;
  snap.family_memo_posted= s.dashboard.family_memo_posted;
  snap.hidden_reminder_indices        = s.home.hidden_reminder_indices;
  snap.hidden_inventory_indices       = s.home.hidden_inventory_indices;
  snap.pending_hide_reminder_indices  = s.home.pending_hide_reminder_indices;
  snap.pending_hide_inventory_indices = s.home.pending_hide_inventory_indices;
  snap.running           = s.timer.running;
  snap.seconds_remaining = s.timer.seconds_remaining;
  snap.target_seconds    = s.timer.target_seconds;
  snap.alert_active      = s.timer.alert_active;
  snap.screen            = s.screen;
  snap.memo_index        = s.memo.index;
  return snap;
}

static void restore_snapshot(AppState& s, const VoiceSnapshot& snap) {
  s.dashboard.reminder_items    = snap.reminder_items;
  s.dashboard.reminder_completed= snap.reminder_completed;
  s.dashboard.reminder_meta     = snap.reminder_meta;
  s.dashboard.inventory_items   = snap.inventory_items;
  s.dashboard.inventory_badges  = snap.inventory_badges;
  s.dashboard.inventory_completed = snap.inventory_completed;
  s.dashboard.memos             = snap.memos;
  s.dashboard.family_memo_text  = snap.family_memo_text;
  s.dashboard.family_memo_author= snap.family_memo_author;
  s.dashboard.family_memo_posted= snap.family_memo_posted;
  s.home.hidden_reminder_indices        = snap.hidden_reminder_indices;
  s.home.hidden_inventory_indices       = snap.hidden_inventory_indices;
  s.home.pending_hide_reminder_indices  = snap.pending_hide_reminder_indices;
  s.home.pending_hide_inventory_indices = snap.pending_hide_inventory_indices;
  s.timer.running           = snap.running;
  s.timer.seconds_remaining = snap.seconds_remaining;
  s.timer.target_seconds    = snap.target_seconds;
  s.timer.alert_active      = snap.alert_active;
  s.screen                  = snap.screen;
  s.memo.index              = snap.memo_index;
}

// Tools that should NOT be pushed onto the undo stack (navigation-only, no data change).
static bool is_undo_excluded_tool(const std::string& tool) {
  return tool == "no_action" ||
         tool == "open_app"  ||
         tool == "undo_last_action_group" ||
         tool == "redo_last_action_group";
}

// Keep history small: each VoiceSnapshot deep-copies several string vectors.
// On ESP32-S3 with 8 MB PSRAM allocations route there (>512 B), but we still
// cap at 5 to avoid runaway heap growth on large lists.
constexpr std::size_t kUndoStackMax = 5;
static std::vector<VoiceSnapshot> g_done_stack;  // undo history
static std::vector<VoiceSnapshot> g_redo_stack;  // redo history

}  // anonymous namespace

void apply_voice_actions(AppState& state,
                         const std::vector<fridge_ink::platform::VoiceAction>& actions) {
  // Determine if any action in this group is undoable (data-changing).
  const bool has_undoable = std::any_of(actions.begin(), actions.end(),
      [](const fridge_ink::platform::VoiceAction& a) {
        return !is_undo_excluded_tool(a.tool);
      });

  // Also check if this is purely a history-control group (undo/redo).
  const bool is_history_control = std::all_of(actions.begin(), actions.end(),
      [](const fridge_ink::platform::VoiceAction& a) {
        return a.tool == "undo_last_action_group" || a.tool == "redo_last_action_group";
      });

  // Capture pre-action snapshot for undo (non-history-control groups only).
  VoiceSnapshot before_snap;
  if (has_undoable && !is_history_control) {
    before_snap = capture_snapshot(state);
  }

  for (const auto& a : actions) {
    ESP_LOGI(kTag, "[voice] applying tool=%s args=%s",
             a.tool.c_str(), a.args_json.c_str());
    if (a.tool == "open_app") {
      va_open_app(state, a.args_json);
    } else if (a.tool == "memo_add") {
      va_memo_add(state, a.args_json);
    } else if (a.tool == "memo_delete") {
      va_memo_delete(state, a.args_json);
    } else if (a.tool == "memo_clear_all") {
      va_memo_clear_all(state, a.args_json);
    } else if (a.tool == "shopping_add_item") {
      va_shopping_add_item(state, a.args_json);
    } else if (a.tool == "shopping_remove_item") {
      va_shopping_remove_item(state, a.args_json);
    } else if (a.tool == "timer_set") {
      va_timer_set(state, a.args_json);
    } else if (a.tool == "timer_add") {
      va_timer_add(state, a.args_json);
    } else if (a.tool == "timer_pause") {
      va_timer_pause(state, a.args_json);
    } else if (a.tool == "timer_resume") {
      va_timer_resume(state, a.args_json);
    } else if (a.tool == "timer_stop") {
      va_timer_stop(state, a.args_json);
    } else if (a.tool == "shopping_clear_all") {
      va_shopping_clear_all(state, a.args_json);
    } else if (a.tool == "inventory_clear_all") {
      va_inventory_clear_all(state, a.args_json);
    } else if (a.tool == "inventory_set_expiry") {
      va_inventory_set_expiry(state, a.args_json);
    } else if (a.tool == "memo_update") {
      va_memo_update(state, a.args_json);
    } else if (a.tool == "inventory_log_event") {
      va_inventory_log_event(state, a.args_json);
    } else if (a.tool == "undo_last_action_group") {
      if (g_done_stack.empty()) {
        ESP_LOGW(kTag, "[voice] undo: nothing to undo");
      } else {
        VoiceSnapshot current = capture_snapshot(state);
        if (g_redo_stack.size() >= kUndoStackMax) g_redo_stack.erase(g_redo_stack.begin());
        g_redo_stack.push_back(std::move(current));
        restore_snapshot(state, g_done_stack.back());
        g_done_stack.pop_back();
        ESP_LOGI(kTag, "[voice] undo: restored (done=%zu redo=%zu)",
                 g_done_stack.size(), g_redo_stack.size());
      }
    } else if (a.tool == "redo_last_action_group") {
      if (g_redo_stack.empty()) {
        ESP_LOGW(kTag, "[voice] redo: nothing to redo");
      } else {
        VoiceSnapshot current = capture_snapshot(state);
        if (g_done_stack.size() >= kUndoStackMax) g_done_stack.erase(g_done_stack.begin());
        g_done_stack.push_back(std::move(current));
        restore_snapshot(state, g_redo_stack.back());
        g_redo_stack.pop_back();
        ESP_LOGI(kTag, "[voice] redo: restored (done=%zu redo=%zu)",
                 g_done_stack.size(), g_redo_stack.size());
      }
    } else if (a.tool == "no_action") {
      ESP_LOGI(kTag, "[voice] no_action (intentional no-op)");
    } else {
      ESP_LOGW(kTag, "[voice] unknown tool: %s", a.tool.c_str());
    }
  }

  // Push pre-action snapshot onto done_stack (clears redo_stack for new branch).
  if (has_undoable && !is_history_control) {
    if (g_done_stack.size() >= kUndoStackMax) g_done_stack.erase(g_done_stack.begin());
    g_done_stack.push_back(std::move(before_snap));
    g_redo_stack.clear();  // New action invalidates redo history.
    ESP_LOGI(kTag, "[voice] snapshot saved (done=%zu)", g_done_stack.size());
  }

  // If we're on the onboarding voice guide step, update the UI status/result.
  if (state.screen == Screen::Onboarding && state.onboarding.step_index == 3) {
    state.onboarding.voice_recording = false;
    if (actions.empty()) {
      state.onboarding.status = "No command detected — try again.";
      state.onboarding.voice_last_result.clear();
    } else {
      // Build a human-readable summary from tool names.
      std::string summary;
      for (const auto& a : actions) {
        if (!summary.empty()) summary += "  +  ";
        // Convert "shopping_add_item" → "SHOPPING ADD ITEM" for readability.
        std::string label = a.tool;
        for (char& c : label) {
          c = (c == '_') ? ' ' : static_cast<char>(std::toupper(static_cast<unsigned char>(c)));
        }
        summary += label;
      }
      state.onboarding.voice_last_result = summary;
      state.onboarding.status = "Done: " + summary;
    }
  }
}

}  // namespace fridge_ink::app
