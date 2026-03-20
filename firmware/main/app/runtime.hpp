#pragma once

#include "app/events.hpp"
#include "app/state.hpp"

namespace fridge_ink::platform {

class Display;

}  // namespace fridge_ink::platform

namespace fridge_ink::app {

class Runtime {
 public:
  explicit Runtime(platform::Display& display);

  void boot();
  void dispatch(const Event& event);

  const AppState& state() const { return state_; }

 private:
  void render();

  platform::Display& display_;
  AppState state_{};
};

}  // namespace fridge_ink::app
