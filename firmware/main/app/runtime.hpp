#pragma once

#include "app/events.hpp"
#include "app/refresh_policy.hpp"
#include "app/state.hpp"
#include "ui/render_app.hpp"
#include "ui/screens/home_screen.hpp"

#include <optional>
#include <utility>
#include <string>
#include <vector>

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
  void stage_render();
  void flush_pending(std::uint64_t now_ms);
  std::pair<std::optional<platform::DirtyRect>, double> diff_stats(
      const std::vector<uint8_t>& image) const;
  void mark_committed_snapshot();
  static std::string format_rects(const std::vector<platform::DirtyRect>& rects);
  static std::string format_reasons(const std::vector<std::string>& reasons);

  platform::Display& display_;
  AppState state_{};
  refresh_policy::RefreshPolicyRuntime refresh_runtime_{};

  bool committed_frame_valid_{false};
  std::vector<uint8_t> committed_frame_{};
  Screen committed_screen_{Screen::Landing};
  ui::HomeDirtySnapshot committed_home_snapshot_{};
  bool committed_home_snapshot_valid_{false};
  bool committed_timer_snapshot_valid_{false};
  int committed_timer_seconds_{0};
  bool committed_timer_running_{false};
  int committed_timer_focused_index_{2};
  bool committed_timer_alert_active_{false};
  bool committed_timer_alert_blink_on_{true};
  int committed_timer_last_completed_seconds_{0};
  WidgetMode committed_timer_widget_mode_{WidgetMode::Clock};

  bool pending_render_valid_{false};
  ui::RenderOutput pending_render_{};
  Screen pending_screen_{Screen::Landing};
  ui::HomeDirtySnapshot pending_home_snapshot_{};
};

}  // namespace fridge_ink::app
