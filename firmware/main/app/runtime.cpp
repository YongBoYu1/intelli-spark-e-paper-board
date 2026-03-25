#include "app/runtime.hpp"

#include "app/defaults.hpp"
#include "app/reducer.hpp"
#include "platform/clock.hpp"
#include "platform/display.hpp"
#include "ui/render_app.hpp"

namespace fridge_ink::app {

Runtime::Runtime(platform::Display& display) : display_(display) {}

void Runtime::boot() {
  const auto defaults = make_factory_defaults();
  state_ = make_state_from_defaults(defaults, platform::monotonic_ms());
  display_.init();
  render();
}

void Runtime::dispatch(const Event& event) {
  const auto old_screen = state_.screen;
  const auto old_lang_idx = state_.landing.language_index;
  const auto old_rotate_seen = state_.landing.rotate_seen;
  const auto old_step = state_.onboarding.step_index;
  const auto old_start_focus = state_.onboarding.start_focus_index;
  const auto old_qr_focus = state_.onboarding.qr_focus_index;
  const auto old_prefs_focus = state_.onboarding.prefs_focus_index;
  const auto old_home_focus = state_.home.focused_index;
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
      state_.landing.status != old_status ||
      state_.onboarding.status != old_ob_status;

  if (changed) {
    render();
  }
}

void Runtime::render() {
  ui::render_app(state_, display_);
}

}  // namespace fridge_ink::app
