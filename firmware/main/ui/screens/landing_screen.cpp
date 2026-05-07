#include "ui/screens/landing_screen.hpp"

#include "platform/panel_config.hpp"
#include "ui/draw.hpp"
#include "ui/strings.hpp"

#include <algorithm>
#include <array>
#include <string>
#include <vector>

namespace fridge_ink::ui {

std::vector<uint8_t> render_landing_bitmap(const app::AppState& state) {
  using platform::kPanelWidth;
  using platform::kPanelHeight;
  using platform::kPanelBufferSize;

  const auto& s = get_ui_strings(state.device_language);

  const std::string lang_label = app::language_label(state.device_language);
  const std::string lang_code = app::language_code(state.device_language);

  std::vector<uint8_t> image(kPanelBufferSize, 0xFF);  // white (1=white, 0=black)

  constexpr int margin = 24;
  constexpr int content_x0 = margin + 16;
  constexpr int content_x1 = kPanelWidth - margin - 16;
  constexpr int content_w = content_x1 - content_x0;
  constexpr int title_scale = 3;
  constexpr int body_scale = 2;
  constexpr int button_scale = 2;
  constexpr int meta_scale = 1;

  // ── Title ──────────────────────────────────────────────────────────────
  int y = margin + 18;
  const std::string title = truncate_text_px("INTELLI SPARK BOARD", title_scale, content_w);
  draw_text_centered(image, content_x0, content_x1, y, title, title_scale, 40);
  const int title_block_h = 36;
  y += title_block_h;

  // ── Subtitle ───────────────────────────────────────────────────────────
  const std::string subtitle = truncate_text_px(
      s.land_subtitle,
      body_scale, content_w);
  draw_text_centered(image, content_x0, content_x1, y, subtitle, body_scale, 64);
  const int subtitle_block_h = 36;

  // ── Tip cards (2×2 grid) ───────────────────────────────────────────────
  const std::array<const char*, 4> tip_title = {
      s.land_tip_rotate, s.land_tip_press, s.land_tip_long, s.land_tip_voice};
  const std::array<const char*, 4> tip_body = {
      s.land_tip_move_focus, s.land_tip_confirm, s.land_tip_back_home, s.land_tip_talk};
  const int tip_gap_x = 12;
  const int tip_gap_y = 10;
  const int tip_w = (content_w - tip_gap_x) / 2;
  const int tip_h = 60;
  const int tips_y0 = margin + 18 + title_block_h + subtitle_block_h;
  for (int i = 0; i < 4; ++i) {
    const int col = i % 2;
    const int row = i / 2;
    const int x0 = content_x0 + col * (tip_w + tip_gap_x);
    const int y0 = tips_y0 + row * (tip_h + tip_gap_y);
    const int x1 = x0 + tip_w;
    const int y1 = y0 + tip_h;
    const bool emphasis = i < 2;
    if (emphasis) {
      fill_rounded_rect(image, x0, y0, x1, y1, 10, true);
      draw_rounded_rect_stroke(image, x0, y0, x1, y1, 10, 2);
      draw_text_centered_inverted(image, x0 + 10, x1 - 10, y0 + 8, tip_title[i], button_scale, 24);
      draw_text_centered_inverted(image, x0 + 10, x1 - 10, y0 + 34, tip_body[i], meta_scale, 40);
    } else {
      draw_rounded_rect_outline(image, x0, y0, x1, y1, 10, 2);
      draw_text_centered(image, x0 + 10, x1 - 10, y0 + 8, tip_title[i], button_scale, 24);
      draw_text_centered(image, x0 + 10, x1 - 10, y0 + 34, tip_body[i], meta_scale, 40);
    }
  }

  // ── Voice hint ─────────────────────────────────────────────────────────
  const int voice_hint_y = tips_y0 + (2 * tip_h) + tip_gap_y + 12;
  draw_text_line(image, content_x0, voice_hint_y,
                 s.land_voice_unlock, meta_scale, 48);

  // ── Language selector ──────────────────────────────────────────────────
  const int language_label_y = voice_hint_y + 20;
  draw_text_line(image, content_x0, language_label_y, s.land_language, button_scale, 18);
  const int chips_y0 = language_label_y + 26;
  const int chip_gap_x = 10;
  const int chip_w = (content_w - (2 * chip_gap_x)) / 3;
  const int chip_h = 40;
  constexpr std::array<const char*, 3> chip_codes = {"en-US", "zh-CN", "fr-FR"};
  constexpr std::array<const char*, 3> chip_labels = {"ENGLISH", "CHINESE", "FRENCH"};
  for (int i = 0; i < 3; ++i) {
    const int x0 = content_x0 + i * (chip_w + chip_gap_x);
    const int x1 = x0 + chip_w;
    const int y1 = chips_y0 + chip_h;
    const bool active = (lang_code == chip_codes[i]);
    if (active) {
      fill_rounded_rect(image, x0, chips_y0, x1, y1, 10, true);
      draw_rounded_rect_stroke(image, x0 - 2, chips_y0 - 2, x1 + 2, y1 + 2, 11, 3);
    }
    if (active) {
      draw_rounded_rect_stroke(image, x0, chips_y0, x1, y1, 10, 2);
    } else {
      draw_rounded_rect_outline(image, x0, chips_y0, x1, y1, 10, 2);
    }
    if (active) {
      draw_text_centered_inverted(image, x0 + 8, x1 - 8, chips_y0 + 12, chip_labels[i], meta_scale, 20);
    } else {
      draw_text_centered(image, x0 + 8, x1 - 8, chips_y0 + 12, chip_labels[i], meta_scale, 20);
    }
  }

  // ── Status text ────────────────────────────────────────────────────────
  std::string status;
  if (state.setup_completed) {
    status = s.land_status_done;
  } else {
    status = s.land_status_choose;
  }

  // Layout from bottom — matching Python landing_layout_metrics()
  const int chips_y1 = chips_y0 + chip_h;
  const int after_chips_y = chips_y1 + 8;
  const int button_w = std::min(420, content_w);
  const int button_h = 52;
  const int button_x0 = content_x0 + (content_w - button_w) / 2;
  int button_y1 = kPanelHeight - margin - 18;
  int button_y0 = button_y1 - button_h;
  // Guard: ensure button is below chips with enough room for status text.
  if (button_y0 < after_chips_y + 44) {
    button_y0 = after_chips_y + 44;
    button_y1 = button_y0 + button_h;
  }
  const int status_y = std::max(after_chips_y + 8, button_y0 - 32);
  draw_text_line(
      image, content_x0, status_y,
      truncate_text_px(status, meta_scale, content_w),
      meta_scale, 80);

  // ── CTA button ─────────────────────────────────────────────────────────
  fill_rounded_rect(image, button_x0, button_y0, button_x0 + button_w, button_y1, 12, true);
  draw_rounded_rect_stroke(image, button_x0, button_y0, button_x0 + button_w, button_y1, 12, 2);
  draw_rounded_rect_stroke(
      image, button_x0 - 2, button_y0 - 2,
      button_x0 + button_w + 2, button_y1 + 2, 12, 3);

  std::string cta;
  if (state.setup_completed) {
    cta = s.land_cta_home;
  } else if (!state.landing.rotate_seen) {
    cta = s.land_cta_rotate;
  } else {
    cta = s.land_cta_click;
  }
  cta = truncate_text_px(cta, button_scale, button_w - 24);
  draw_text_centered_inverted(
      image,
      button_x0 + 12, button_x0 + button_w - 12,
      button_y0 + 14, cta, button_scale, 64);

  return image;
}

}  // namespace fridge_ink::ui
