#include "ui/screens/onboarding_screen.hpp"

#include "platform/panel_config.hpp"
#include "ui/draw.hpp"

#include <array>
#include <string>
#include <vector>

namespace fridge_ink::ui {

std::vector<uint8_t> render_onboarding_bitmap(const app::AppState& state) {
  using platform::kPanelWidth;
  using platform::kPanelHeight;
  using platform::kPanelBufferSize;

  constexpr int kStepTotal = 4;
  constexpr std::array<const char*, 4> kStepKeys = {
      "start", "pair_qr", "prefs", "voice_guide"};

  const auto step = state.onboarding.step_index % kStepTotal;
  const int step_cur = static_cast<int>(step) + 1;
  const std::string step_key = kStepKeys[step];

  const std::string lang_line =
      std::string("Language: ") +
      app::language_label(state.device_language) +
      " (" + app::language_code(state.device_language) + ")";

  std::string status = state.onboarding.status;
  if (status.empty()) {
    status = "Rotate to choose setting, click to continue.";
  }

  std::vector<uint8_t> image(kPanelBufferSize, 0xFF);  // white (1=white, 0=black)
  draw_outline_rect(image, 12, 12, kPanelWidth - 12, kPanelHeight - 12, 3);

  // ── Header ─────────────────────────────────────────────────────────────
  draw_text_line(image, 40, 30, "FIRST SETUP", 3, 26);
  draw_text_line(
      image, 40, 66,
      "STEP " + std::to_string(step_cur) + "/" + std::to_string(kStepTotal),
      2, 20);

  // ── Progress bar ───────────────────────────────────────────────────────
  const int bar_x0 = 420;
  const int bar_y0 = 72;
  const int bar_w = 340;
  const int bar_h = 14;
  draw_outline_rect(image, bar_x0, bar_y0, bar_x0 + bar_w, bar_y0 + bar_h, 2);
  const int seg_gap = 8;
  const int seg_w = (bar_w - ((kStepTotal + 1) * seg_gap)) / kStepTotal;
  for (int i = 0; i < kStepTotal; ++i) {
    const int sx0 = bar_x0 + seg_gap + i * (seg_w + seg_gap);
    const int sx1 = sx0 + seg_w;
    if (i < step_cur) {
      fill_black_rect(image, sx0, bar_y0 + 3, sx1, bar_y0 + bar_h - 3);
    } else {
      draw_outline_rect(image, sx0, bar_y0 + 3, sx1, bar_y0 + bar_h - 3, 1);
    }
  }

  // ── Step: Start ────────────────────────────────────────────────────────
  if (step_key == "start") {
    const int start_focus = static_cast<int>(state.onboarding.start_focus_index);
    draw_text_line(image, 40, 118, "CONFIGURE NETWORK AND BASIC PREFERENCES.", 1, 52);
    draw_text_line(image, 40, 142, "PHONE PAIRING IS RECOMMENDED FOR WI-FI SETUP.", 1, 56);
    constexpr std::array<const char*, 2> kOptions = {"START PHONE PAIRING", "SKIP FOR NOW"};
    const int box_x0 = 184;
    const int box_x1 = 616;
    const int first_y = 218;
    for (int i = 0; i < 2; ++i) {
      const int y0 = first_y + i * 84;
      const int y1 = y0 + 58;
      if (i == start_focus) {
        fill_black_rect(image, box_x0, y0, box_x1, y1);
        draw_outline_rect(image, box_x0 - 3, y0 - 3, box_x1 + 3, y1 + 3, 3);
        draw_text_centered_inverted(image, box_x0 + 10, box_x1 - 10, y0 + 18, kOptions[i], 2, 34);
      } else {
        draw_outline_rect(image, box_x0, y0, box_x1, y1, 2);
        draw_text_centered(image, box_x0 + 10, box_x1 - 10, y0 + 18, kOptions[i], 2, 34);
      }
    }
    draw_text_line(image, 40, 428, "ROTATE TO CHOOSE  -  PRESS TO CONTINUE", 1, 54);
    return image;
  }

  // ── Step: Pair QR ──────────────────────────────────────────────────────
  if (step_key == "pair_qr") {
    const int qr_focus = static_cast<int>(state.onboarding.qr_focus_index);
    draw_text_line(image, 40, 118, "PHONE PAIRING", 3, 24);
    draw_text_line(image, 40, 150, "SCAN QR TO CONFIGURE WI-FI", 1, 42);

    draw_outline_rect(image, 52, 192, 336, 416, 2);
    draw_text_line(image, 96, 278, "QR", 4, 6);

    draw_text_line(image, 372, 202, "1) OPEN PHONE CAMERA", 1, 34);
    draw_text_line(image, 372, 226, "2) SCAN CODE AND SUBMIT WI-FI", 1, 40);
    draw_text_line(image, 372, 250, "3) RETURN HERE AND CONFIRM", 1, 38);
    if (!state.onboarding.pair_token.empty()) {
      draw_text_line(image, 372, 292,
                     "Pair token: " + state.onboarding.pair_token, 1, 40);
    }
    draw_text_wrapped(image, 372, 316, 360, status, 1, 3);

    constexpr std::array<const char*, 3> kActions = {"REFRESH QR", "I AM DONE", "SKIP"};
    const int bx = 372;
    const int by = 360;
    const int gap = 10;
    const int bw = 114;
    const int bh = 48;
    for (int i = 0; i < 3; ++i) {
      const int x0 = bx + i * (bw + gap);
      const int x1 = x0 + bw;
      const int y0 = by;
      const int y1 = y0 + bh;
      if (i == qr_focus) {
        fill_black_rect(image, x0, y0, x1, y1);
        draw_outline_rect(image, x0 - 3, y0 - 3, x1 + 3, y1 + 3, 3);
        draw_text_centered_inverted(image, x0 + 6, x1 - 6, y0 + 16, kActions[i], 1, 16);
      } else {
        draw_outline_rect(image, x0, y0, x1, y1, 2);
        draw_text_centered(image, x0 + 6, x1 - 6, y0 + 16, kActions[i], 1, 16);
      }
    }
    return image;
  }

  // ── Step: Prefs ────────────────────────────────────────────────────────
  if (step_key == "prefs") {
    const int prefs_focus = static_cast<int>(state.onboarding.prefs_focus_index);
    draw_text_line(image, 40, 118, "QUICK PREFERENCES", 3, 30);
    draw_text_line(image, 40, 150, "YOU CAN CHANGE THESE LATER IN SETTINGS.", 1, 54);
    if (!state.onboarding.wifi_ssid.empty()) {
      draw_text_line(image, 40, 176, "Wi-Fi: " + state.onboarding.wifi_ssid, 1, 54);
    }

    const int row_x0 = 42;
    const int row_x1 = 758;
    const int row_h = 48;
    const int row_gap = 10;
    const int rows_top = 206;
    std::array<std::string, 3> labels = {"LANGUAGE", "TIMEZONE", "AUTO SYNC"};
    std::array<std::string, 3> values = {
        lang_line,
        "Timezone: " + state.onboarding.timezone,
        std::string("Auto Sync: ") + (state.onboarding.auto_sync_enabled ? "ON" : "OFF"),
    };
    for (int i = 0; i < 3; ++i) {
      const int y0 = rows_top + i * (row_h + row_gap);
      const int y1 = y0 + row_h;
      draw_outline_rect(image, row_x0, y0, row_x1, y1, 2);
      if (i == prefs_focus) {
        fill_black_rect(image, row_x0 + 10, y0 + 8, row_x0 + 18, y1 - 8);
        draw_outline_rect(image, row_x0 - 3, y0 - 3, row_x1 + 3, y1 + 3, 3);
      }
      draw_text_line(image, 64, y0 + 14, labels[i], 2, 18);
      draw_text_line(image, 360, y0 + 14, values[i], 1, 38);
    }

    const int guide_x0 = 510;
    const int guide_x1 = 758;
    const int guide_y0 = 390;
    const int guide_y1 = 438;
    draw_text_line(image, 42, 404, "NEXT STEP ->", 2, 16);
    if (prefs_focus == 3) {
      fill_black_rect(image, guide_x0, guide_y0, guide_x1, guide_y1);
      draw_outline_rect(image, guide_x0 - 3, guide_y0 - 3, guide_x1 + 3, guide_y1 + 3, 3);
      draw_text_centered_inverted(image, guide_x0 + 8, guide_x1 - 8, guide_y0 + 16, "VOICE GUIDE >", 1, 24);
    } else {
      draw_outline_rect(image, guide_x0, guide_y0, guide_x1, guide_y1, 2);
      draw_text_centered(image, guide_x0 + 8, guide_x1 - 8, guide_y0 + 16, "VOICE GUIDE >", 1, 24);
    }
    return image;
  }

  // ── Step: Voice Guide ──────────────────────────────────────────────────
  if (step_key == "voice_guide") {
    draw_text_line(image, 40, 40, "VOICE SETUP", 3, 24);
    draw_outline_rect(image, 40, 84, 240, 196, 2);
    draw_text_centered(image, 56, 224, 120, "MIC", 4, 8);
    draw_text_centered(image, 56, 224, 164, "HOLD VOICE KEY", 1, 20);

    draw_text_line(image, 270, 96, "SPEAK", 1, 12);
    draw_text_wrapped(image, 270, 128, 470, "ADD MILK TO INVENTORY", 3, 2);
    fill_black_rect(image, 40, 206, 760, 208);
    draw_outline_rect(image, 40, 228, 760, 330, 2);
    draw_text_line(image, 58, 244, "RESULT", 1, 12);
    draw_text_line(image, 58, 280, "NO RESULT YET.", 2, 40);
    draw_text_wrapped(image, 40, 350, 720, status, 1, 2);

    const bool focused = true;  // voice_guide only has one focus element
    const int btn_x0 = 220;
    const int btn_x1 = 580;
    const int btn_y0 = 398;
    const int btn_y1 = 438;
    if (focused) {
      fill_black_rect(image, btn_x0, btn_y0, btn_x1, btn_y1);
      draw_outline_rect(image, btn_x0 - 3, btn_y0 - 3, btn_x1 + 3, btn_y1 + 3, 3);
      draw_text_centered_inverted(image, btn_x0 + 8, btn_x1 - 8, btn_y0 + 12, "SKIP", 1, 16);
    } else {
      draw_outline_rect(image, btn_x0, btn_y0, btn_x1, btn_y1, 2);
      draw_text_centered(image, btn_x0 + 8, btn_x1 - 8, btn_y0 + 12, "SKIP", 1, 16);
    }
    return image;
  }

  // ── Fallback: Setup Complete ───────────────────────────────────────────
  draw_text_line(image, 40, 60, "SETUP COMPLETE", 3, 24);
  draw_text_line(image, 40, 102, "YOUR BOARD IS READY.", 1, 28);
  draw_text_line(image, 62, 156, lang_line, 1, 40);
  draw_text_line(image, 62, 184, "Timezone: " + state.onboarding.timezone, 1, 40);
  draw_text_line(image, 62, 212,
                 std::string("Auto Sync: ") +
                     (state.onboarding.auto_sync_enabled ? "ON" : "OFF"),
                 1, 40);
  if (!state.onboarding.wifi_ssid.empty()) {
    draw_text_line(image, 62, 240, "Wi-Fi: " + state.onboarding.wifi_ssid, 1, 40);
  }
  fill_black_rect(image, 240, 380, 560, 438);
  draw_outline_rect(image, 237, 377, 563, 441, 3);
  draw_text_centered_inverted(image, 252, 548, 400, "ENTER HOME", 2, 24);
  return image;
}

}  // namespace fridge_ink::ui
