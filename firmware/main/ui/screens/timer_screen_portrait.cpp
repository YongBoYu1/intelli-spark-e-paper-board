#include "ui/screens/timer_screen.hpp"

#include "platform/panel_config.hpp"
#include "ui/draw.hpp"

#include <algorithm>
#include <string>

namespace fridge_ink::ui {
namespace {

std::string format_timer_display(const int seconds_remaining) {
  const int seconds = std::max(0, seconds_remaining);
  const int minutes = seconds / 60;
  const int remain = seconds % 60;
  char buffer[24];
  std::snprintf(buffer, sizeof(buffer), "%02d:%02d", minutes, remain);
  return std::string(buffer);
}

void draw_timer_button(
    std::vector<uint8_t>& image,
    const int x0,
    const int y0,
    const int x1,
    const int y1,
    const std::string& label,
    const bool active) {
  if (active) {
    fill_black_rect(image, x0, y0, x1, y1);
    draw_text_centered_inverted(image, x0 + 8, x1 - 8, y0 + 16, label, 2, 16);
    return;
  }

  draw_rounded_rect_stroke(image, x0, y0, x1, y1, 14, 2);
  draw_text_centered(image, x0 + 8, x1 - 8, y0 + 16, label, 2, 16);
}

}  // namespace

std::vector<uint8_t> render_timer_portrait_bitmap(const app::AppState& state) {
  using platform::kPanelBufferSize;
  using platform::kPanelHeight;
  using platform::kPanelWidth;

  std::vector<uint8_t> image(kPanelBufferSize, 0xFF);

  const bool running = bool(state.timer.running);
  const std::string time_text = format_timer_display(state.timer.seconds_remaining);
  const std::string status_text =
      (state.timer.seconds_remaining <= 0) ? "READY" : (running ? "RUNNING" : "PAUSED");
  const std::string action_text = running ? "PAUSE" : "START";
  const int focused = std::max(0, std::min(state.timer.focused_index, 3));

  draw_outline_rect(image, 12, 12, kPanelWidth - 12, kPanelHeight - 12, 3);

  draw_text_line(image, 40, 30, "TIMER", 3, 16);
  fill_black_rect(image, 606, 26, 744, 58);
  draw_text_centered_inverted(image, 614, 736, 38, status_text, 1, 12);

  draw_rounded_rect_stroke(image, 36, 72, 764, 238, 22, 3);
  draw_text_line(image, 60, 96, "MINUTES REMAINING", 1, 22);
  draw_text_centered(image, 60, 740, 144, time_text, 3, 8);
  draw_text_centered(
      image, 60, 740, 192,
      running ? "COUNTING DOWN" : "READY TO START",
      1, 24);

  draw_rounded_rect_stroke(image, 36, 258, 764, 444, 22, 3);
  draw_text_line(image, 60, 278, "CONTROLS", 1, 16);

  const int left_x0 = 60;
  const int right_x0 = 408;
  const int button_w = 332;
  const int button_h = 52;
  const int top_row_y = 306;
  const int bottom_row_y = 372;

  draw_timer_button(image, left_x0, top_row_y, left_x0 + button_w, top_row_y + button_h, "-1M", focused == 0);
  draw_timer_button(image, right_x0, top_row_y, right_x0 + button_w, top_row_y + button_h, "+1M", focused == 1);
  draw_timer_button(
      image, left_x0, bottom_row_y, left_x0 + button_w, bottom_row_y + button_h,
      action_text, focused == 2);
  draw_timer_button(
      image, right_x0, bottom_row_y, right_x0 + button_w, bottom_row_y + button_h,
      "RESET", focused == 3);

  return image;
}

}  // namespace fridge_ink::ui
