#include "ui/screens/timer_screen.hpp"

#include "platform/panel_config.hpp"
#include "ui/draw.hpp"
#include "ui/panel_font_assets_generated.hpp"

#include <algorithm>
#include <cstdio>
#include <string>
#include <vector>

namespace fridge_ink::ui {
namespace {

using platform::panel_font_assets::BitmapFont;
using platform::panel_font_assets::Glyph;

// Portrait semantic canvas (Python parity: w=480, h=800 when rotated 90/270)
constexpr int kPW = 480;
constexpr int kPH = 800;

// Layout constants — same Python parity values as landscape since Python's
// render_timer() applies them to image.size regardless of orientation.
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

// ── Coordinate mapping ────────────────────────────────────────────────────────
// Portrait semantic (cx, cy) in [0,480)×[0,800) maps to physical 800×480 buffer.
// r90  (90°): physical = (cy, 479 - cx)
// r270 (270°): physical = (799 - cy, cx)

bool use_r90_map(const app::AppState& state) {
  const int deg = ((state.settings.rotation_deg % 360) + 360) % 360;
  // Normalise to nearest 90° step
  if (deg >= 45 && deg < 135) return true;   // 90°
  return false;                               // 270° (or anything else in portrait)
}

void mp_px(std::vector<uint8_t>& image, const int cx, const int cy, const bool r90) {
  if (cx < 0 || cx >= kPW || cy < 0 || cy >= kPH) return;
  if (r90) {
    set_black_pixel(image, cy, 479 - cx);
  } else {
    set_black_pixel(image, 799 - cy, cx);
  }
}

void mp_clr(std::vector<uint8_t>& image, const int cx, const int cy, const bool r90) {
  if (cx < 0 || cx >= kPW || cy < 0 || cy >= kPH) return;
  if (r90) {
    clear_pixel(image, cy, 479 - cx);
  } else {
    clear_pixel(image, 799 - cy, cx);
  }
}

void mp_fill_rect(
    std::vector<uint8_t>& image,
    const int x0, const int y0, const int x1, const int y1,
    const bool black, const bool r90) {
  for (int y = y0; y < y1; ++y) {
    for (int x = x0; x < x1; ++x) {
      if (black) mp_px(image, x, y, r90);
      else       mp_clr(image, x, y, r90);
    }
  }
}

// ── Rounded rect ─────────────────────────────────────────────────────────────

bool pt_in_rrect(
    const int px, const int py,
    const int x0, const int y0, const int x1, const int y1,
    const int radius) {
  if (px < x0 || px >= x1 || py < y0 || py >= y1) return false;
  const int w = x1 - x0;
  const int h = y1 - y0;
  const int r = std::max(0, std::min(radius, std::min(w, h) / 2));
  if (r <= 0) return true;
  if ((px >= x0 + r && px < x1 - r) || (py >= y0 + r && py < y1 - r)) return true;
  const int cx = (px < x0 + r) ? (x0 + r) : (x1 - r - 1);
  const int cy = (py < y0 + r) ? (y0 + r) : (y1 - r - 1);
  const int dx = px - cx;
  const int dy = py - cy;
  return (dx * dx + dy * dy) <= (r * r);
}

void mp_fill_rounded_rect(
    std::vector<uint8_t>& image,
    const int x0, const int y0, const int x1, const int y1,
    const int radius, const bool black, const bool r90) {
  for (int y = y0; y < y1; ++y) {
    for (int x = x0; x < x1; ++x) {
      if (!pt_in_rrect(x, y, x0, y0, x1, y1, radius)) continue;
      if (black) mp_px(image, x, y, r90);
      else       mp_clr(image, x, y, r90);
    }
  }
}

void mp_draw_rounded_rect_outline(
    std::vector<uint8_t>& image,
    const int x0, const int y0, const int x1, const int y1,
    const int radius, const int thickness, const bool r90) {
  const int t = std::max(1, thickness);
  const int ix0 = x0 + t;
  const int iy0 = y0 + t;
  const int ix1 = x1 - t;
  const int iy1 = y1 - t;
  const int inner_r = std::max(0, radius - t);
  for (int y = y0; y < y1; ++y) {
    for (int x = x0; x < x1; ++x) {
      if (!pt_in_rrect(x, y, x0, y0, x1, y1, radius)) continue;
      if (ix1 > ix0 && iy1 > iy0 &&
          pt_in_rrect(x, y, ix0, iy0, ix1, iy1, inner_r)) continue;
      mp_px(image, x, y, r90);
    }
  }
}

// ── Glyph / text helpers ──────────────────────────────────────────────────────

std::size_t pt_glyph_index(const char ch) {
  const unsigned char code = static_cast<unsigned char>(ch);
  if (code < 32 || code > 126) return static_cast<std::size_t>('?' - 32);
  return static_cast<std::size_t>(code - 32);
}

void mp_draw_glyph(
    std::vector<uint8_t>& image,
    const int x, const int y,
    const char ch,
    const BitmapFont& font,
    const bool black, const bool r90) {
  const Glyph& glyph = font.glyphs[pt_glyph_index(ch)];
  if (glyph.width == 0 || glyph.height == 0) return;
  const int gx = x + glyph.left;
  const int gy = y + glyph.top;
  const int row_bytes = (glyph.width + 7) / 8;
  const std::uint8_t* bitmap = font.bitmap + glyph.bitmap_offset;
  for (int row = 0; row < glyph.height; ++row) {
    for (int col = 0; col < glyph.width; ++col) {
      const std::uint8_t byte = bitmap[row * row_bytes + (col / 8)];
      if ((byte & (0x80U >> (col % 8))) == 0) continue;
      if (black) mp_px(image, gx + col, gy + row, r90);
      else       mp_clr(image, gx + col, gy + row, r90);
    }
  }
}

void mp_draw_text(
    std::vector<uint8_t>& image,
    const int x, const int y,
    const std::string& text,
    const BitmapFont& font,
    const bool black, const bool r90) {
  int cursor_x = x;
  for (const char ch : text) {
    mp_draw_glyph(image, cursor_x, y, ch, font, black, r90);
    cursor_x += font.glyphs[pt_glyph_index(ch)].advance;
  }
}

// ── Text metric helpers (pure computation, no pixel writes) ───────────────────

int pt_text_width(const std::string& text, const BitmapFont& font) {
  int width = 0;
  for (const char ch : text) width += font.glyphs[pt_glyph_index(ch)].advance;
  return width;
}

std::string pt_truncate_text(
    const std::string& text, const BitmapFont& font, const int max_w) {
  if (text.empty() || max_w <= 0) return "";
  if (pt_text_width(text, font) <= max_w) return text;
  const std::string ellipsis = "...";
  const int ew = pt_text_width(ellipsis, font);
  if (ew >= max_w) return ellipsis;
  const int budget = max_w - ew;
  std::string out;
  for (const char ch : text) {
    const std::string candidate = out + ch;
    if (pt_text_width(candidate, font) > budget) break;
    out = candidate;
  }
  return out.empty() ? ellipsis : (out + ellipsis);
}

struct PtTextBounds {
  int top{0};
  int bottom{0};
  bool valid{false};
};

PtTextBounds pt_text_bounds(const std::string& text, const BitmapFont& font) {
  PtTextBounds b{};
  for (const char ch : text) {
    const Glyph& g = font.glyphs[pt_glyph_index(ch)];
    if (g.width == 0 || g.height == 0) continue;
    const int gtop    = static_cast<int>(g.top);
    const int gbottom = gtop + static_cast<int>(g.height);
    if (!b.valid) {
      b.top = gtop; b.bottom = gbottom; b.valid = true; continue;
    }
    b.top    = std::min(b.top,    gtop);
    b.bottom = std::max(b.bottom, gbottom);
  }
  return b;
}

int pt_text_height(const std::string& text, const BitmapFont& font) {
  const PtTextBounds b = pt_text_bounds(text, font);
  if (!b.valid) return static_cast<int>(font.line_height);
  return std::max(1, b.bottom - b.top);
}

int pt_centered_text_y(
    const int row_top, const int row_h,
    const std::string& text, const BitmapFont& font) {
  const PtTextBounds b = pt_text_bounds(text, font);
  if (!b.valid) return row_top + (row_h - static_cast<int>(font.line_height)) / 2;
  const int th = b.bottom - b.top;
  return row_top + (row_h - th) / 2 - b.top;
}

// ── Timer-specific helpers ────────────────────────────────────────────────────

std::string pt_format_timer_value(const int seconds_remaining) {
  const int s = std::max(0, seconds_remaining);
  char buf[24];
  std::snprintf(buf, sizeof(buf), "%02d:%02d", s / 60, s % 60);
  return std::string(buf);
}

int pt_round_minutes(const int seconds) {
  const int q = seconds / 60;
  const int r = seconds % 60;
  if (r < 30) return q;
  if (r > 30) return q + 1;
  return (q % 2 == 0) ? q : (q + 1);  // bankers rounding for .5 ties
}

std::string pt_timer_done_message(const int done_seconds) {
  const int mins = std::max(1, pt_round_minutes(std::max(1, done_seconds)));
  if (mins == 1) return "1 MINUTE COUNTDOWN FINISHED";
  return std::to_string(mins) + " MINUTES COUNTDOWN FINISHED";
}

std::string pt_timer_status_text(const app::TimerState& timer) {
  if (timer.alert_active && timer.seconds_remaining <= 0) {
    const int done = timer.last_completed_seconds > 0
                         ? timer.last_completed_seconds
                         : timer.target_seconds;
    return pt_timer_done_message(done);
  }
  if (timer.seconds_remaining <= 0) return "READY";
  if (timer.running) return "RUNNING";
  return "PAUSED";
}

const BitmapFont& pt_pick_time_font(
    const std::string& text, const int max_w, const int max_h) {
  static constexpr const BitmapFont* kCandidates[] = {
      &platform::panel_font_assets::kFontJetExtraBold124,
      &platform::panel_font_assets::kFontJetExtraBold109,
      &platform::panel_font_assets::kFontJetExtraBold66,
  };
  for (const BitmapFont* f : kCandidates) {
    if (pt_text_width(text, *f) <= max_w && pt_text_height(text, *f) <= max_h) return *f;
  }
  return *kCandidates[2];
}

const BitmapFont& pt_pick_status_font(const std::string& text, const int max_w) {
  static constexpr const BitmapFont* kCandidates[] = {
      &platform::panel_font_assets::kFontInterBold22,
      &platform::panel_font_assets::kFontInterBold20,
      &platform::panel_font_assets::kFontInterBold18,
      &platform::panel_font_assets::kFontInterBold17,
  };
  for (const BitmapFont* f : kCandidates) {
    if (pt_text_width(text, *f) <= max_w) return *f;
  }
  return *kCandidates[3];
}

void pt_draw_control_pill(
    std::vector<uint8_t>& image,
    const int x0, const int y0, const int x1, const int y1,
    const std::string& label, const bool focused,
    const BitmapFont& font, const bool r90) {
  if (focused) {
    mp_fill_rounded_rect(image, x0, y0, x1, y1, kButtonRadius, true, r90);
  } else {
    mp_draw_rounded_rect_outline(image, x0, y0, x1, y1, kButtonRadius, 2, r90);
  }
  const int tw = pt_text_width(label, font);
  const int tx = x0 + std::max(0, ((x1 - x0) - tw) / 2);
  const int ty = pt_centered_text_y(y0, y1 - y0, label, font);
  mp_draw_text(image, tx, ty, label, font, !focused, r90);
}

}  // namespace

std::vector<uint8_t> render_timer_portrait_bitmap(const app::AppState& state) {
  const bool r90 = use_r90_map(state);
  std::vector<uint8_t> image(platform::kPanelBufferSize, 0xFF);

  const BitmapFont& title_font  = platform::panel_font_assets::kFontInterBold29;
  const BitmapFont& hint_font   = platform::panel_font_assets::kFontJetBold13;
  const BitmapFont& button_font = platform::panel_font_assets::kFontInterBold20;

  const std::string hint_raw  = "ROTATE=SELECT  |  CLICK=ENTER  |  HOLD=HOME";
  const std::string hint_text = pt_truncate_text(hint_raw, hint_font, std::max(80, kPW - 48));
  const std::string time_text = pt_format_timer_value(state.timer.seconds_remaining);
  const std::string status_text = pt_timer_status_text(state.timer);
  const BitmapFont& status_font = pt_pick_status_font(status_text, kPW - 72);

  // Title
  mp_draw_text(image, kTitleX, kTitleY, "TIMER", title_font, true, r90);

  // Hint (right-aligned)
  const int hint_w = pt_text_width(hint_text, hint_font);
  const int hint_x = std::max(kMarginX, (kPW - kMarginX) - hint_w);
  mp_draw_text(image, hint_x, kHintY, hint_text, hint_font, true, r90);

  // Divider
  mp_fill_rect(image, kMarginX, kDividerY, kPW - kMarginX, kDividerY + 2, true, r90);

  // Controls row geometry
  const int controls_y      = kPH - kButtonBottomGap;  // 710
  const int available_bottom = controls_y - 26;          // 684

  // Status font height
  const int status_h = pt_text_height(status_text, status_font);

  // Time display area: from kContentTop down to (available_bottom - gap - status_h)
  const int time_area_top    = kContentTop;
  const int time_area_bottom = std::max(time_area_top + 1,
                                         available_bottom - kStatusGap - status_h);
  const int time_area_h      = std::max(1, time_area_bottom - time_area_top);

  const BitmapFont& time_font = pt_pick_time_font(time_text, kPW - 120, time_area_h);
  const int time_w = pt_text_width(time_text, time_font);
  const int time_x = std::max(kMarginX, (kPW - time_w) / 2);
  const int time_y = pt_centered_text_y(time_area_top, time_area_h, time_text, time_font);

  // Alert blink: inverted background + white digits
  const bool alert_reverse = state.timer.alert_active &&
                             state.timer.seconds_remaining <= 0 &&
                             !state.timer.alert_blink_on;

  if (alert_reverse) {
    const PtTextBounds tb   = pt_text_bounds(time_text, time_font);
    const int time_top_px   = time_y + (tb.valid ? tb.top    : 0);
    const int time_bottom_px = time_y + (tb.valid ? tb.bottom : static_cast<int>(time_font.line_height));
    const int text_h  = std::max(1, time_bottom_px - time_top_px);
    const int pad_x   = std::max(10, (time_w * 6) / 100);
    const int pad_y   = std::max(6,  (text_h * 18) / 100);
    const int bx0     = std::max(16,         time_x - pad_x);
    const int by0     = std::max(74,          time_top_px - pad_y);
    const int bx1     = std::min(kPW - 16,   time_x + time_w + pad_x);
    const int by1     = std::min(kPH - 108,  time_bottom_px + pad_y);
    if (bx1 > bx0 && by1 > by0) {
      mp_fill_rounded_rect(
          image, bx0, by0, bx1, by1,
          std::max(8, ((by1 - by0) * 16) / 100), true, r90);
    }
    mp_draw_text(image, time_x, time_y, time_text, time_font, false, r90);
  } else {
    mp_draw_text(image, time_x, time_y, time_text, time_font, true, r90);
  }

  // Status text (centred below time display)
  const PtTextBounds tb2     = pt_text_bounds(time_text, time_font);
  const int time_bottom2      = time_y + (tb2.valid ? tb2.bottom : static_cast<int>(time_font.line_height));
  int status_y = time_bottom2 + kStatusGap;
  if (status_y + status_h > available_bottom) {
    status_y = std::max(kContentTop + 8, available_bottom - status_h);
  }
  const int status_w = pt_text_width(status_text, status_font);
  const int status_x = std::max(kMarginX, (kPW - status_w) / 2);
  mp_draw_text(image, status_x, status_y, status_text, status_font, true, r90);

  // Control buttons (4 across, Python parity: max(100, calculated_width))
  const std::string controls[] = {
      "-1M",
      "+1M",
      state.timer.running ? "PAUSE" : "START",
      "RESET",
  };
  const int focused      = ((state.timer.focused_index % 4) + 4) % 4;
  const int calc_btn_w   = (kPW - (kMarginX * 2) - (kButtonGap * 3)) / 4;
  const int button_width = std::max(100, calc_btn_w);
  for (int idx = 0; idx < 4; ++idx) {
    const int x0 = kMarginX + idx * (button_width + kButtonGap);
    const int x1 = x0 + button_width;
    pt_draw_control_pill(
        image, x0, controls_y, x1, controls_y + kButtonHeight,
        controls[idx], idx == focused, button_font, r90);
  }

  return image;
}

}  // namespace fridge_ink::ui
