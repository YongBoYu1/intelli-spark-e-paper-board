#include "ui/render_app.hpp"

#include "ui/screens/calendar_screen.hpp"
#include "ui/screens/home_screen.hpp"
#include "ui/screens/landing_screen.hpp"
#include "ui/screens/list_screen.hpp"
#include "ui/screens/memo_screen.hpp"
#include "ui/screens/menu_screen.hpp"
#include "ui/screens/onboarding_screen.hpp"
#include "ui/screens/weather_screen.hpp"
#include "ui/screens/settings_screen.hpp"
#include "ui/screens/timer_screen.hpp"
#include "platform/panel_config.hpp"
#include "ui/draw.hpp"

#include "esp_log.h"

#include <cstdio>
#include <vector>

namespace fridge_ink::ui {

namespace {
constexpr const char* kTag = "render";

// ── Scheduled alarm overlay ───────────────────────────────────────────────────
// Drawn on top of whatever screen is currently active.
// Panel: 800×480 (landscape). Dialog ≈ centre 56% × 50%.
void render_alarm_overlay(
    std::vector<uint8_t>& image,
    const app::ScheduledAlarmState& alarm) {
  using platform::kPanelWidth;
  using platform::kPanelHeight;

  // Dialog box.
  constexpr int kDlgX0 = 176;   // (800 - 448) / 2
  constexpr int kDlgX1 = 624;   // kDlgX0 + 448
  constexpr int kDlgY0 = 108;   // (480 - 264) / 2
  constexpr int kDlgY1 = 372;   // kDlgY0 + 264

  fill_white_rect(image, kDlgX0, kDlgY0, kDlgX1, kDlgY1);
  draw_outline_rect(image, kDlgX0, kDlgY0, kDlgX1, kDlgY1, 3);

  // Header bar — black background, white "REMINDER" text.
  constexpr int kHdrY1 = kDlgY0 + 36;
  fill_black_rect(image, kDlgX0 + 1, kDlgY0 + 1, kDlgX1 - 1, kHdrY1);
  draw_text_centered_inverted(image, kDlgX0, kDlgX1, kDlgY0 + 10, "REMINDER", 2, 12);

  // Time + recurrence label, e.g. "14:00  DAILY".
  char time_buf[20];
  snprintf(time_buf, sizeof(time_buf), "%02d:%02d  DAILY", alarm.hour, alarm.minute);
  draw_text_centered(image, kDlgX0, kDlgX1, kHdrY1 + 10, time_buf, 1, 20);

  // Divider.
  fill_black_rect(image, kDlgX0 + 12, kHdrY1 + 28, kDlgX1 - 12, kHdrY1 + 30);

  // Reminder title (wrapped, up to 2 lines, scale-2 font).
  draw_text_wrapped(image, kDlgX0 + 16, kHdrY1 + 38, kDlgX1 - kDlgX0 - 32,
                    alarm.title, 2, 2);

  // Buttons at bottom of dialog.
  constexpr int kBtnY0 = kDlgY1 - 48;
  constexpr int kBtnY1 = kDlgY1 - 12;
  constexpr int kMidX  = (kDlgX0 + kDlgX1) / 2;
  constexpr int kGap   = 8;
  constexpr int kBtn0X0 = kDlgX0 + 14;
  constexpr int kBtn0X1 = kMidX - kGap;
  constexpr int kBtn1X0 = kMidX + kGap;
  constexpr int kBtn1X1 = kDlgX1 - 14;
  constexpr int kBtnTextY = kBtnY0 + 10;

  // "CONFIRM" — focused_index == 0 → inverted.
  if (alarm.focused_index == 0) {
    fill_black_rect(image, kBtn0X0, kBtnY0, kBtn0X1, kBtnY1);
    draw_rounded_rect_outline(image, kBtn0X0, kBtnY0, kBtn0X1, kBtnY1, 5, 2);
    draw_text_centered_inverted(image, kBtn0X0, kBtn0X1, kBtnTextY, "CONFIRM", 1, 10);
  } else {
    draw_rounded_rect_outline(image, kBtn0X0, kBtnY0, kBtn0X1, kBtnY1, 5, 2);
    draw_text_centered(image, kBtn0X0, kBtn0X1, kBtnTextY, "CONFIRM", 1, 10);
  }

  // "CANCEL" — focused_index == 1 → inverted.
  if (alarm.focused_index == 1) {
    fill_black_rect(image, kBtn1X0, kBtnY0, kBtn1X1, kBtnY1);
    draw_rounded_rect_outline(image, kBtn1X0, kBtnY0, kBtn1X1, kBtnY1, 5, 2);
    draw_text_centered_inverted(image, kBtn1X0, kBtn1X1, kBtnTextY, "CANCEL", 1, 10);
  } else {
    draw_rounded_rect_outline(image, kBtn1X0, kBtnY0, kBtn1X1, kBtnY1, 5, 2);
    draw_text_centered(image, kBtn1X0, kBtn1X1, kBtnTextY, "CANCEL", 1, 10);
  }
}

}  // namespace

RenderOutput render_app(
    const app::AppState& state,
    const HomeDirtySnapshot* previous_home_snapshot) {
  const bool alarm_active = state.scheduled_alarm.active;
  ESP_LOGI(kTag, "render_app: screen=%s lang=%s alarm=%d",
           app::screen_name(state.screen),
           app::language_code(state.device_language),
           static_cast<int>(alarm_active));

  RenderOutput output{};

  switch (state.screen) {
    case app::Screen::Landing:
      output.image = render_landing_bitmap(state);
      break;
    case app::Screen::Onboarding:
      output.image = render_onboarding_bitmap(state);
      break;
    case app::Screen::Home:
      output.image = render_home_bitmap(state);
      if (previous_home_snapshot != nullptr) {
        const HomeDirtyPlan plan = home_dirty_plan(
            *previous_home_snapshot,
            capture_home_dirty_snapshot(state));
        output.dirty_rects = plan.rects;
        output.dirty_reasons = plan.reasons;
      }
      break;
    case app::Screen::Menu:
      output.image = render_menu_bitmap(state);
      break;
    case app::Screen::Memo:
      output.image = render_memo_bitmap(state);
      break;
    case app::Screen::Timer:
      output.image = render_timer_bitmap(state);
      break;
    case app::Screen::Calendar:
      output.image = render_calendar_bitmap(state);
      break;
    case app::Screen::Weather:
      output.image = render_weather_bitmap(state);
      break;
    case app::Screen::Inventory:
      output.image = render_list_bitmap(state);
      break;
    case app::Screen::Settings:
      output.image = render_settings_bitmap(state);
      break;
  }

  // Draw the scheduled alarm overlay on top of any screen.
  if (alarm_active) {
    render_alarm_overlay(output.image, state.scheduled_alarm);
    // Alarm overlay invalidates any dirty-rect optimisation (forces full refresh).
    output.dirty_rects.clear();
    output.dirty_reasons.clear();
  }

  return output;
}

}  // namespace fridge_ink::ui
