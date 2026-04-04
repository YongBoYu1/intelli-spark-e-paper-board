#include "ui/screens/timer_screen.hpp"

#include "platform/panel_config.hpp"
#include "ui/draw.hpp"

#include <algorithm>
#include <cstdio>
#include <string>
#include <vector>

namespace fridge_ink::ui {

namespace {

constexpr int kMarginX = 24;
constexpr int kHeaderTop = 18;
constexpr int kHintTop = 30;
constexpr int kDividerY = 72;
constexpr int kContentTop = 118;
constexpr int kControlsBottomMargin = 32;
constexpr int kControlsHeight = 56;
constexpr int kControlsGap = 12;
constexpr int kControlsRadius = 18;

std::string format_timer_value(const int minutes_remaining) {
  const int minutes = std::max(0, minutes_remaining);
  char buffer[16];
  std::snprintf(buffer, sizeof(buffer), "%d:00", minutes);
  return std::string(buffer);
}

std::string timer_status_text(const app::TimerState& timer) {
  if (timer.running) {
    return "RUNNING";
  }
  if (timer.minutes_remaining > 0) {
    return "PAUSED";
  }
  return "READY";
}

void draw_control_pill(
    std::vector<uint8_t>& image,
    const int x0,
    const int y0,
    const int x1,
    const int y1,
    const std::string& label,
    const bool active) {
  if (active) {
    fill_rounded_rect(image, x0, y0, x1, y1, kControlsRadius, true);
    draw_text_centered_inverted(image, x0, x1, y0 + 16, label, 2, 16);
    return;
  }

  draw_rounded_rect_outline(image, x0, y0, x1, y1, kControlsRadius, 2);
  draw_text_centered(image, x0, x1, y0 + 16, label, 2, 16);
}

}  // namespace

std::vector<uint8_t> render_timer_landscape_bitmap(const app::AppState& state) {
  using platform::kPanelHeight;
  using platform::kPanelWidth;

  std::vector<uint8_t> image(platform::kPanelBufferSize, 0xFF);

  const std::string title = "TIMER";
  const std::string hint = "ROTATE=SELECT  |  CLICK=ENTER  |  HOLD=HOME";
  const std::string time_text = format_timer_value(state.timer.minutes_remaining);
  const std::string status_text = timer_status_text(state.timer);

  draw_text_line(image, kMarginX, kHeaderTop, title, 2, 16);

  const int hint_max_width = (kPanelWidth - (kMarginX * 2));
  const std::string hint_text = truncate_text_px(hint, 1, hint_max_width);
  const int hint_width = text_width_px(hint_text, 1);
  const int hint_x = std::max(kMarginX, kPanelWidth - kMarginX - hint_width);
  draw_text_line(image, hint_x, kHintTop, hint_text, 1, 80);

  fill_black_rect(image, kMarginX, kDividerY, kPanelWidth - kMarginX, kDividerY + 2);

  const int time_width = text_width_px(time_text, 3);
  const int time_x = std::max(kMarginX, (kPanelWidth - time_width) / 2);
  draw_text_line(image, time_x, kContentTop, time_text, 3, 16);

  const int status_width = text_width_px(status_text, 2);
  const int status_x = std::max(kMarginX, (kPanelWidth - status_width) / 2);
  draw_text_line(image, status_x, 238, status_text, 2, 24);

  const std::string controls[] = {
      "-1M",
      "+1M",
      state.timer.running ? "PAUSE" : "START",
      "RESET",
  };

  const int controls_y = kPanelHeight - kControlsBottomMargin - kControlsHeight;
  const int available_width = kPanelWidth - (kMarginX * 2) - (kControlsGap * 3);
  const int control_width = available_width / 4;
  for (int idx = 0; idx < 4; ++idx) {
    const int x0 = kMarginX + idx * (control_width + kControlsGap);
    const int x1 = x0 + control_width;
    const bool active = idx == std::max(0, std::min(state.timer.focused_index, 3));
    draw_control_pill(image, x0, controls_y, x1, controls_y + kControlsHeight, controls[idx], active);
  }

  return image;
}

}  // namespace fridge_ink::ui
