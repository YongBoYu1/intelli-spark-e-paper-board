#include "app/runtime.hpp"

#include "app/defaults.hpp"
#include "app/reducer.hpp"
#include "platform/clock.hpp"
#include "platform/display.hpp"
#include "ui/render_app.hpp"
#include "ui/screens/home_screen.hpp"

namespace fridge_ink::app {

namespace {
constexpr std::uint64_t kHomeFocusMinRenderGapMs = 120;
}

Runtime::Runtime(platform::Display& display) : display_(display) {}

void Runtime::boot() {
  const auto defaults = make_factory_defaults();
  state_ = make_state_from_defaults(defaults, platform::monotonic_ms());
  display_.init();
  render_now();
}

void Runtime::dispatch(const Event& event) {
  const ui::HomeDirtySnapshot previous_home_snapshot =
      ui::capture_home_dirty_snapshot(state_);
  const auto old_screen = state_.screen;
  const auto old_lang_idx = state_.landing.language_index;
  const auto old_rotate_seen = state_.landing.rotate_seen;
  const auto old_step = state_.onboarding.step_index;
  const auto old_start_focus = state_.onboarding.start_focus_index;
  const auto old_qr_focus = state_.onboarding.qr_focus_index;
  const auto old_prefs_focus = state_.onboarding.prefs_focus_index;
  const auto old_home_focus = state_.home.focused_index;
  const auto old_clock_bucket = state_.home.clock_minute_bucket;
  const auto old_show_focus = state_.home.show_focus;
  const auto old_inventory_completed = state_.dashboard.inventory_completed;
  const auto old_reminder_completed = state_.dashboard.reminder_completed;
  const auto old_status = state_.landing.status;
  const auto old_ob_status = state_.onboarding.status;

  reduce(state_, event);

  const bool changed =
      state_.screen != old_screen ||
      state_.landing.language_index != old_lang_idx ||
      state_.landing.rotate_seen != old_rotate_seen ||
      state_.onboarding.step_index != old_step ||
      state_.onboarding.start_focus_index != old_start_focus ||
      state_.onboarding.qr_focus_index != old_qr_focus ||
      state_.onboarding.prefs_focus_index != old_prefs_focus ||
      state_.home.focused_index != old_home_focus ||
      state_.home.clock_minute_bucket != old_clock_bucket ||
      state_.home.show_focus != old_show_focus ||
      state_.dashboard.inventory_completed != old_inventory_completed ||
      state_.dashboard.reminder_completed != old_reminder_completed ||
      state_.landing.status != old_status ||
      state_.onboarding.status != old_ob_status;

  if (!changed) {
    return;
  }

  if (should_defer_render(event, old_screen)) {
    queue_render(previous_home_snapshot);
    return;
  }

  const ui::HomeDirtySnapshot* effective_previous =
      pending_render_ ? &pending_previous_home_snapshot_ : &previous_home_snapshot;
  render_now(effective_previous);
}

void Runtime::flush_deferred(const std::uint64_t now_ms) {
  if (!pending_render_) {
    return;
  }
  if ((now_ms - last_render_ms_) < kHomeFocusMinRenderGapMs) {
    return;
  }
  render_now(&pending_previous_home_snapshot_);
}

bool Runtime::should_defer_render(const Event& event, const Screen old_screen) const {
  return event.type == EventType::Rotate &&
         old_screen == Screen::Home &&
         state_.screen == Screen::Home;
}

void Runtime::queue_render(const ui::HomeDirtySnapshot& previous_home_snapshot) {
  if (!pending_render_) {
    pending_previous_home_snapshot_ = previous_home_snapshot;
    pending_render_ = true;
  }
}

void Runtime::render_now(const ui::HomeDirtySnapshot* previous_home_snapshot) {
  pending_render_ = false;
  render(previous_home_snapshot);
  last_render_ms_ = platform::monotonic_ms();
}

void Runtime::render(const ui::HomeDirtySnapshot* previous_home_snapshot) {
  ui::render_app(state_, display_, previous_home_snapshot);
}

}  // namespace fridge_ink::app
