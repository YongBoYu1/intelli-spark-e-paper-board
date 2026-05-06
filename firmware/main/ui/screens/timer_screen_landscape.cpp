#include "ui/screens/timer_screen.hpp"

#include "platform/panel_config.hpp"
#include "ui/draw.hpp"
#include "ui/panel_font_assets_generated.hpp"
#include "ui/strings.hpp"

#include <algorithm>
#include <cctype>
#include <cmath>
#include <cstdio>
#include <string>
#include <vector>

namespace fridge_ink::ui {
namespace {

using platform::panel_font_assets::BitmapFont;
using platform::panel_font_assets::Glyph;

constexpr int kMarginX = 24;
constexpr int kTitleX = 24;
constexpr int kTitleY = 16;
constexpr int kHintY = 52;
constexpr int kDividerY = 68;
constexpr int kContentTop = 112;
constexpr int kStatusGap = 38;
constexpr int kButtonGap = 12;
constexpr int kButtonHeight = 60;
constexpr int kButtonRadius = 12;
constexpr int kButtonBottomGap = 90;

std::size_t glyph_index(const char ch) {
  const unsigned char code = static_cast<unsigned char>(ch);
  if (code < 32 || code > 126) {
    return static_cast<std::size_t>('?' - 32);
  }
  return static_cast<std::size_t>(code - 32);
}

void draw_glyph_with_font(
    std::vector<uint8_t>& image,
    const int x,
    const int y,
    const char ch,
    const BitmapFont& font,
    const bool black = true) {
  const Glyph& glyph = font.glyphs[glyph_index(ch)];
  if (glyph.width == 0 || glyph.height == 0) {
    return;
  }

  const int glyph_x0 = x + glyph.left;
  const int glyph_y0 = y + glyph.top;
  const int row_bytes = (glyph.width + 7) / 8;
  const std::uint8_t* bitmap = font.bitmap + glyph.bitmap_offset;
  for (int row = 0; row < glyph.height; ++row) {
    for (int col = 0; col < glyph.width; ++col) {
      const std::uint8_t byte = bitmap[row * row_bytes + (col / 8)];
      const bool on = (byte & (0x80U >> (col % 8))) != 0;
      if (!on) {
        continue;
      }
      if (black) {
        set_black_pixel(image, glyph_x0 + col, glyph_y0 + row);
      } else {
        clear_pixel(image, glyph_x0 + col, glyph_y0 + row);
      }
    }
  }
}

void draw_text_with_font(
    std::vector<uint8_t>& image,
    const int x,
    const int y,
    const std::string& text,
    const BitmapFont& font,
    const bool black = true) {
  int cursor_x = x;
  for (const char ch : text) {
    draw_glyph_with_font(image, cursor_x, y, ch, font, black);
    cursor_x += font.glyphs[glyph_index(ch)].advance;
  }
}

int text_width_with_font(const std::string& text, const BitmapFont& font) {
  int width = 0;
  for (const char ch : text) {
    width += font.glyphs[glyph_index(ch)].advance;
  }
  return width;
}

std::string truncate_text_with_font(
    const std::string& text,
    const BitmapFont& font,
    const int max_width_px) {
  if (text.empty() || max_width_px <= 0) {
    return "";
  }
  if (text_width_with_font(text, font) <= max_width_px) {
    return text;
  }

  const std::string ellipsis = "...";
  const int ellipsis_w = text_width_with_font(ellipsis, font);
  if (ellipsis_w >= max_width_px) {
    return ellipsis;
  }
  const int budget = max_width_px - ellipsis_w;
  std::string out;
  for (const char ch : text) {
    const std::string candidate = out + ch;
    if (text_width_with_font(candidate, font) > budget) {
      break;
    }
    out = candidate;
  }
  return out.empty() ? ellipsis : (out + ellipsis);
}

struct TextVerticalBounds {
  int top{0};
  int bottom{0};
  bool valid{false};
};

TextVerticalBounds text_vertical_bounds_with_font(
    const std::string& text,
    const BitmapFont& font) {
  TextVerticalBounds bounds{};
  for (const char ch : text) {
    const Glyph& glyph = font.glyphs[glyph_index(ch)];
    if (glyph.width == 0 || glyph.height == 0) {
      continue;
    }
    const int top = glyph.top;
    const int bottom = glyph.top + glyph.height;
    if (!bounds.valid) {
      bounds.top = top;
      bounds.bottom = bottom;
      bounds.valid = true;
      continue;
    }
    bounds.top = std::min(bounds.top, top);
    bounds.bottom = std::max(bounds.bottom, bottom);
  }
  return bounds;
}

int text_height_with_font(const std::string& text, const BitmapFont& font) {
  const TextVerticalBounds bounds = text_vertical_bounds_with_font(text, font);
  if (!bounds.valid) {
    return font.line_height;
  }
  return std::max(1, bounds.bottom - bounds.top);
}

int centered_text_y_with_font(
    const int row_top,
    const int row_height,
    const std::string& text,
    const BitmapFont& font) {
  const TextVerticalBounds bounds = text_vertical_bounds_with_font(text, font);
  if (!bounds.valid) {
    return row_top + ((row_height - static_cast<int>(font.line_height)) / 2);
  }
  const int text_h = bounds.bottom - bounds.top;
  return row_top + ((row_height - text_h) / 2) - bounds.top;
}

std::string format_timer_value(const int seconds_remaining) {
  const int seconds = std::max(0, seconds_remaining);
  const int minutes = seconds / 60;
  const int remain = seconds % 60;
  char buffer[24];
  std::snprintf(buffer, sizeof(buffer), "%02d:%02d", minutes, remain);
  return std::string(buffer);
}

int round_minutes_python_style(const int seconds) {
  const int q = seconds / 60;
  const int r = seconds % 60;
  if (r < 30) {
    return q;
  }
  if (r > 30) {
    return q + 1;
  }
  // Python round() uses bankers rounding for .5 ties.
  return (q % 2 == 0) ? q : (q + 1);
}

std::string timer_done_message(const int done_seconds, const UiStrings& s) {
  const int secs = std::max(1, done_seconds);
  const int mins = std::max(1, round_minutes_python_style(secs));
  if (mins == 1) {
    return s.timer_1min_done;
  }
  return std::to_string(mins) + s.timer_mins_done;
}

std::string timer_status_text(const app::TimerState& timer, const UiStrings& s) {
  if (timer.alert_active && timer.seconds_remaining <= 0) {
    const int done = timer.last_completed_seconds > 0
                         ? timer.last_completed_seconds
                         : timer.target_seconds;
    return timer_done_message(done, s);
  }
  if (timer.seconds_remaining <= 0) {
    return s.timer_ready;
  }
  if (timer.running) {
    return s.timer_running;
  }
  return s.timer_paused;
}

const BitmapFont& pick_time_font(
    const std::string& text,
    const int max_width,
    const int max_height) {
  static constexpr const BitmapFont* kCandidates[] = {
      &platform::panel_font_assets::kFontJetExtraBold124,
      &platform::panel_font_assets::kFontJetExtraBold109,
      &platform::panel_font_assets::kFontJetExtraBold66,
  };
  for (const BitmapFont* font : kCandidates) {
    if (text_width_with_font(text, *font) <= max_width &&
        text_height_with_font(text, *font) <= max_height) {
      return *font;
    }
  }
  return *kCandidates[(sizeof(kCandidates) / sizeof(kCandidates[0])) - 1];
}

const BitmapFont& pick_status_font(
    const std::string& text,
    const int max_width) {
  static constexpr const BitmapFont* kCandidates[] = {
      &platform::panel_font_assets::kFontInterBold22,
      &platform::panel_font_assets::kFontInterBold20,
      &platform::panel_font_assets::kFontInterBold18,
      &platform::panel_font_assets::kFontInterBold17,
  };
  for (const BitmapFont* font : kCandidates) {
    if (text_width_with_font(text, *font) <= max_width) {
      return *font;
    }
  }
  return *kCandidates[(sizeof(kCandidates) / sizeof(kCandidates[0])) - 1];
}

void draw_control_pill(
    std::vector<uint8_t>& image,
    const int x0,
    const int y0,
    const int x1,
    const int y1,
    const std::string& label,
    const bool focused,
    const BitmapFont& font) {
  if (focused) {
    fill_rounded_rect(image, x0, y0, x1, y1, kButtonRadius, true);
  } else {
    draw_rounded_rect_outline(image, x0, y0, x1, y1, kButtonRadius, 2);
  }

  const int text_w = text_width_with_font(label, font);
  const int text_x = x0 + std::max(0, ((x1 - x0) - text_w) / 2);
  const int text_y = centered_text_y_with_font(y0, y1 - y0, label, font);
  draw_text_with_font(image, text_x, text_y, label, font, !focused);
}

}  // namespace

std::vector<uint8_t> render_timer_landscape_bitmap(const app::AppState& state) {
  using platform::kPanelBufferSize;
  using platform::kPanelHeight;
  using platform::kPanelWidth;

  const auto& s = get_ui_strings(state.device_language);
  std::vector<uint8_t> image(kPanelBufferSize, 0xFF);

  const BitmapFont& title_font = platform::panel_font_assets::kFontInterBold29;
  const BitmapFont& hint_font = platform::panel_font_assets::kFontJetBold13;
  const BitmapFont& button_font = platform::panel_font_assets::kFontInterBold20;

  const std::string hint_raw = s.timer_hint;
  const std::string hint_text = truncate_text_with_font(
      hint_raw,
      hint_font,
      std::max(80, kPanelWidth - 48));
  const std::string time_text = format_timer_value(state.timer.seconds_remaining);
  const std::string status_text = timer_status_text(state.timer, s);
  const BitmapFont& status_font = pick_status_font(status_text, kPanelWidth - 72);

  draw_text_with_font(image, kTitleX, kTitleY, s.timer_title, title_font);
  const int hint_w = text_width_with_font(hint_text, hint_font);
  const int hint_x = std::max(kMarginX, (kPanelWidth - kMarginX) - hint_w);
  draw_text_with_font(image, hint_x, kHintY, hint_text, hint_font);
  fill_black_rect(image, kMarginX, kDividerY, kPanelWidth - kMarginX, kDividerY + 2);

  const int controls_y = kPanelHeight - kButtonBottomGap;
  const int available_bottom = controls_y - 26;
  const int status_h = text_height_with_font(status_text, status_font);
  const int time_area_bottom = std::max(kContentTop + 1, available_bottom - kStatusGap - status_h);
  const int time_area_h = std::max(1, time_area_bottom - kContentTop);

  const BitmapFont& time_font = pick_time_font(
      time_text,
      kPanelWidth - 120,
      time_area_h);
  const int time_w = text_width_with_font(time_text, time_font);
  const int time_x = std::max(kMarginX, (kPanelWidth - time_w) / 2);
  const int time_y = centered_text_y_with_font(kContentTop, time_area_h, time_text, time_font);
  const TextVerticalBounds time_bounds = text_vertical_bounds_with_font(time_text, time_font);
  const int time_top = time_y + (time_bounds.valid ? time_bounds.top : 0);
  const int time_bottom = time_y + (time_bounds.valid ? time_bounds.bottom : time_font.line_height);
  const bool alert_reverse = state.timer.alert_active &&
                             state.timer.seconds_remaining <= 0 &&
                             !state.timer.alert_blink_on;
  if (alert_reverse) {
    const int text_h = std::max(1, time_bottom - time_top);
    const int pad_x = std::max(10, (time_w * 6) / 100);
    const int pad_y = std::max(6, (text_h * 18) / 100);
    const int bx0 = std::max(16, time_x - pad_x);
    const int by0 = std::max(74, time_top - pad_y);
    const int bx1 = std::min(kPanelWidth - 16, time_x + time_w + pad_x);
    const int by1 = std::min(kPanelHeight - 108, time_bottom + pad_y);
    if (bx1 > bx0 && by1 > by0) {
      fill_rounded_rect(
          image,
          bx0,
          by0,
          bx1,
          by1,
          std::max(8, ((by1 - by0) * 16) / 100),
          true);
    }
    draw_text_with_font(image, time_x, time_y, time_text, time_font, false);
  } else {
    draw_text_with_font(image, time_x, time_y, time_text, time_font);
  }

  int status_y = time_bottom + kStatusGap;
  if (status_y + status_h > available_bottom) {
    status_y = std::max(kContentTop + 8, available_bottom - status_h);
  }
  const int status_w = text_width_with_font(status_text, status_font);
  const int status_x = std::max(kMarginX, (kPanelWidth - status_w) / 2);
  draw_text_with_font(image, status_x, status_y, status_text, status_font);

  const std::string controls[] = {
      "-1M",
      "+1M",
      state.timer.running ? s.timer_pause_btn : s.timer_start_btn,
      s.timer_reset_btn,
  };
  const int focused = ((state.timer.focused_index % 4) + 4) % 4;
  const int button_width = (kPanelWidth - (kMarginX * 2) - (kButtonGap * 3)) / 4;
  for (int idx = 0; idx < 4; ++idx) {
    const int x0 = kMarginX + idx * (button_width + kButtonGap);
    const int x1 = x0 + button_width;
    draw_control_pill(
        image,
        x0,
        controls_y,
        x1,
        controls_y + kButtonHeight,
        controls[idx],
        idx == focused,
        button_font);
  }

  return image;
}

}  // namespace fridge_ink::ui
