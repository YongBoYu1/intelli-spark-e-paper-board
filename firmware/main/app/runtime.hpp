#pragma once

#include "app/events.hpp"
#include "app/state.hpp"
#include "ui/screens/home_screen.hpp"

namespace fridge_ink::platform {
class Display;
}  // namespace fridge_ink::platform

namespace fridge_ink::app {

class Runtime {
 public:
  explicit Runtime(platform::Display& display);

  void boot();
  void dispatch(const Event& event);
  void flush_deferred(std::uint64_t now_ms);

  const AppState& state() const { return state_; }

 private:
  bool should_defer_render(const Event& event, Screen old_screen) const;
  void queue_render(const ui::HomeDirtySnapshot& previous_home_snapshot);
  void render_now(const ui::HomeDirtySnapshot* previous_home_snapshot = nullptr);
  void render(const ui::HomeDirtySnapshot* previous_home_snapshot = nullptr);

  platform::Display& display_;
  AppState state_{};
  bool pending_render_{false};
  ui::HomeDirtySnapshot pending_previous_home_snapshot_{};
  std::uint64_t last_render_ms_{0};
};

}  // namespace fridge_ink::app
