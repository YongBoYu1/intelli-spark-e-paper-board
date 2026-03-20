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
  display_.clear();
  render();
}

void Runtime::dispatch(const Event& event) {
  reduce(state_, event);
  render();
}

void Runtime::render() {
  ui::render_app(state_, display_);
}

}  // namespace fridge_ink::app
