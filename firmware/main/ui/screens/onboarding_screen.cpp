#include "ui/screens/onboarding_screen.hpp"

#include "app/state.hpp"
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
    draw_text_line(image, 40, 118, "CONFIGURE WI-FI AND BASIC PREFERENCES.", 1, 52);
    draw_text_line(image, 40, 142, "CONNECT TO WI-FI TO ENABLE WEATHER AND SYNC.", 1, 56);
    constexpr std::array<const char*, 2> kOptions = {"SELECT WI-FI", "SKIP FOR NOW"};
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

  // ── Step: WiFi select (sub_step 0) ────────────────────────────────────
  // Layout (800×480): header y=0-86 | title y=98 | list y=126-420 | footer y=432-460
  if (step_key == "pair_qr" && state.onboarding.wifi_sub_step == 0) {
    draw_text_line(image, 40, 98, "SELECT WI-FI NETWORK", 2, 20);

    const auto& nets = state.onboarding.wifi_networks;
    const int list_x0 = 40;
    const int list_x1 = 760;
    const int list_top = 126;  // below title
    const int row_h    = 54;
    const int row_gap  = 6;    // row step = 60; 5 rows end at y=126+4*60+54=420
    constexpr int kVisible = 5;

    if (nets.empty()) {
      // No networks yet — show status and RESCAN button.
      draw_text_line(image, list_x0, list_top + 40, status, 1, 54);
      const int bx0 = 280, by0 = 300, bx1 = 520, by1 = 348;
      fill_black_rect(image, bx0, by0, bx1, by1);
      draw_outline_rect(image, bx0 - 3, by0 - 3, bx1 + 3, by1 + 3, 3);
      draw_text_centered_inverted(image, bx0 + 8, bx1 - 8, by0 + 14, "PRESS TO RESCAN", 1, 20);
    } else {
      const int scroll = static_cast<int>(state.onboarding.wifi_list_scroll);
      const int focus  = static_cast<int>(state.onboarding.wifi_list_focus);
      const int total  = static_cast<int>(nets.size());

      for (int i = 0; i < kVisible && (scroll + i) < total; ++i) {
        const int idx = scroll + i;
        const int y0  = list_top + i * (row_h + row_gap);
        const int y1  = y0 + row_h;
        const bool foc = (idx == focus);

        // Signal strength: 4 bar levels from RSSI.
        const int rssi = nets[static_cast<std::size_t>(idx)].rssi;
        const int bars = rssi >= -55 ? 4 : rssi >= -67 ? 3 : rssi >= -79 ? 2 : 1;
        const std::string bar_str = std::string(static_cast<std::size_t>(bars), '*') +
                                    std::string(static_cast<std::size_t>(4 - bars), '-');

        if (foc) {
          fill_black_rect(image, list_x0, y0, list_x1, y1);
          draw_outline_rect(image, list_x0 - 3, y0 - 3, list_x1 + 3, y1 + 3, 3);
          draw_text_line_inverted(image, list_x0 + 16, y0 + 16,
                                  nets[static_cast<std::size_t>(idx)].ssid, 2, 20);
          draw_text_line_inverted(image, list_x1 - 80, y0 + 16, bar_str, 1, 14);
        } else {
          draw_outline_rect(image, list_x0, y0, list_x1, y1, 1);
          draw_text_line(image, list_x0 + 16, y0 + 16,
                         nets[static_cast<std::size_t>(idx)].ssid, 2, 20);
          draw_text_line(image, list_x1 - 80, y0 + 16, bar_str, 1, 14);
        }
      }
      // Scroll counter (bottom-left, below list rows).
      if (total > kVisible) {
        const std::string ind = std::to_string(focus + 1) + "/" + std::to_string(total);
        draw_text_line(image, list_x0, 430, ind, 1, 14);
      }
    }

    // Bottom: hint (left) + SKIP button (right) — safely below list at y=432.
    draw_text_line(image, 40, 440, "ROTATE TO SCROLL  -  PRESS TO SELECT", 1, 54);
    const int sx0 = 622, sy0 = 430, sx1 = 760, sy1 = 458;
    draw_outline_rect(image, sx0, sy0, sx1, sy1, 2);
    draw_text_centered(image, sx0 + 8, sx1 - 8, sy0 + 10, "SKIP", 1, 18);
    return image;
  }

  // ── Step: Password entry / QWERTY keyboard (sub_step 1) ──────────────
  // Layout (800×480): global header y=0-86 | ssid+pwd y=98-156 | kbd y=162-456
  // Row step = kh(54)+gap(6) = 60.  5 rows: 162,222,282,342,402 → last ends 456.
  if (step_key == "pair_qr" && state.onboarding.wifi_sub_step == 1) {
    // ── SSID + password display (below global header) ────────────────────
    draw_text_line(image, 40, 98, "NETWORK: " + state.onboarding.wifi_ssid, 1, 44);
    const std::string pwd_display = state.onboarding.wifi_password + "_";
    draw_outline_rect(image, 40, 114, 760, 154, 2);
    draw_text_line(image, 56, 126, pwd_display, 2, 20);

    if (!state.onboarding.wifi_connect_error.empty()) {
      draw_text_line(image, 40, 158, state.onboarding.wifi_connect_error, 1, 44);
    }

    // ── QWERTY keyboard ───────────────────────────────────────────────────
    // row0(10)+row1(10)+row2(9)+row3(7)+row4(8) = 44 keys, kw=64 kh=54 hg=8
    // Row widths: r0/r1=10*64+9*8=712 x_start=44
    //             r2  = 9*64+8*8=640 x_start=80
    //             r3  = 7*64+6*8=496 x_start=152
    //             r4  = SFT(80)+6*64+SPC(120)+7*8=640 x_start=80
    const int kw = 64, kh = 54, hg = 8;
    const int focus = static_cast<int>(state.onboarding.kbd_focus);
    const bool shift = state.onboarding.kbd_shift;

    static constexpr const char* kRow0N = "1234567890";
    static constexpr const char* kRow0S = "!@#$%^&*()";
    static constexpr const char* kRow1  = "qwertyuiop";
    static constexpr const char* kRow2  = "asdfghjkl";
    static constexpr const char* kRow3  = "zxcvbnm";

    // Keyboard top at y=162, row step=60.
    const int ry[5] = {162, 222, 282, 342, 402};
    const int rx[5] = {44, 44, 80, 152, 80};

    auto draw_key = [&](int x0, int y0, int w, const std::string& lbl, bool foc) {
      const int x1 = x0 + w, y1 = y0 + kh;
      if (foc) {
        fill_black_rect(image, x0, y0, x1, y1);
        draw_outline_rect(image, x0 - 2, y0 - 2, x1 + 2, y1 + 2, 3);
        draw_text_centered_inverted(image, x0 + 2, x1 - 2, y0 + 18, lbl, 2, 18);
      } else {
        draw_outline_rect(image, x0, y0, x1, y1, 1);
        draw_text_centered(image, x0 + 2, x1 - 2, y0 + 18, lbl, 2, 18);
      }
    };

    // Row 0: digits (normal) / symbols (shift)
    for (int c = 0; c < 10; ++c) {
      const std::string lbl(1, shift ? kRow0S[c] : kRow0N[c]);
      draw_key(rx[0] + c * (kw + hg), ry[0], kw, lbl, focus == c);
    }
    // Row 1: qwertyuiop
    for (int c = 0; c < 10; ++c) {
      const char base = kRow1[c];
      const std::string lbl(1, shift ? static_cast<char>(base - 32) : base);
      draw_key(rx[1] + c * (kw + hg), ry[1], kw, lbl, focus == 10 + c);
    }
    // Row 2: asdfghjkl
    for (int c = 0; c < 9; ++c) {
      const char base = kRow2[c];
      const std::string lbl(1, shift ? static_cast<char>(base - 32) : base);
      draw_key(rx[2] + c * (kw + hg), ry[2], kw, lbl, focus == 20 + c);
    }
    // Row 3: zxcvbnm
    for (int c = 0; c < 7; ++c) {
      const char base = kRow3[c];
      const std::string lbl(1, shift ? static_cast<char>(base - 32) : base);
      draw_key(rx[3] + c * (kw + hg), ry[3], kw, lbl, focus == 29 + c);
    }
    // Row 4: SFT(80) - _ . @ SPACE(120) DEL OK — total 640px centred at rx[4]=80
    {
      const int y4 = ry[4], x4 = rx[4];
      draw_key(x4,             y4, 80,  shift ? "SFT*" : "SFT", focus == 36);
      draw_key(x4 + 88,        y4, kw,  "-",     focus == 37);
      draw_key(x4 + 88 + 72,   y4, kw,  "_",     focus == 38);
      draw_key(x4 + 88 + 144,  y4, kw,  ".",     focus == 39);
      draw_key(x4 + 88 + 216,  y4, kw,  "@",     focus == 40);
      draw_key(x4 + 88 + 288,  y4, 120, "SPACE", focus == 41);
      draw_key(x4 + 88 + 416,  y4, kw,  "DEL",  focus == 42);
      draw_key(x4 + 88 + 488,  y4, kw,  "OK",   focus == 43);
    }
    // (no bottom hint — keyboard row 4 ends at y=456, border at y=468)
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
  // Layout: global header y=0-86 | content y=98-460
  if (step_key == "voice_guide") {
    const bool recording = state.onboarding.voice_recording;
    const bool has_result = !state.onboarding.voice_last_result.empty();

    // ── Recording state indicator (big tap target) ──────────────────────
    const int ind_x0 = 40, ind_x1 = 760;
    const int ind_y0 = 98, ind_y1 = 158;
    if (recording) {
      fill_black_rect(image, ind_x0, ind_y0, ind_x1, ind_y1);
      draw_outline_rect(image, ind_x0 - 3, ind_y0 - 3, ind_x1 + 3, ind_y1 + 3, 3);
      draw_text_centered_inverted(image, ind_x0 + 16, ind_x1 - 16,
                                  ind_y0 + 20, "* RECORDING... SPEAK NOW *", 2, 24);
    } else {
      draw_outline_rect(image, ind_x0, ind_y0, ind_x1, ind_y1, 2);
      draw_text_centered(image, ind_x0 + 16, ind_x1 - 16,
                         ind_y0 + 20, "HOLD VOICE KEY TO RECORD", 2, 24);
    }

    // ── Example commands ────────────────────────────────────────────────
    draw_text_line(image, 40, 172, "EXAMPLE COMMANDS:", 1, 38);
    draw_text_line(image, 60, 192, "* Add milk to the shopping list", 1, 38);
    draw_text_line(image, 60, 210, "* Set a 5-minute timer", 1, 38);
    draw_text_line(image, 60, 228, "* Show the calendar", 1, 38);

    // ── Result area ──────────────────────────────────────────────────────
    fill_black_rect(image, 40, 248, 760, 250);   // divider
    draw_text_line(image, 40, 260, "RESULT:", 1, 38);
    draw_outline_rect(image, 40, 278, 760, 390, 2);

    if (!has_result && !recording) {
      // Idle state — no test done yet.
      draw_text_line(image, 56, 310, "No result yet.", 2, 32);
      draw_text_line(image, 56, 344, "Hold the voice key above to test.", 1, 38);
    } else if (recording) {
      draw_text_line(image, 56, 318, "Listening...", 2, 32);
    } else {
      // Show last result from backend.
      draw_text_wrapped(image, 56, 296, 688, state.onboarding.voice_last_result, 2, 32);
    }

    // ── Skip / Done button ───────────────────────────────────────────────
    draw_text_line(image, 40, 416, "Press to skip voice test and open Home.", 1, 38);
    const int btn_x0 = 544, btn_y0 = 406, btn_x1 = 760, btn_y1 = 446;
    fill_black_rect(image, btn_x0, btn_y0, btn_x1, btn_y1);
    draw_outline_rect(image, btn_x0 - 3, btn_y0 - 3, btn_x1 + 3, btn_y1 + 3, 3);
    draw_text_centered_inverted(image, btn_x0 + 8, btn_x1 - 8, btn_y0 + 14,
                                 has_result ? "DONE >" : "SKIP >", 2, 22);
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
