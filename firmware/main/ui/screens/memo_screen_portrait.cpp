#include "ui/screens/memo_screen.hpp"

#include "platform/panel_config.hpp"
#include "ui/draw.hpp"
#include "ui/panel_font_assets_generated.hpp"
#include "ui/strings.hpp"

#include <algorithm>
#include <cctype>
#include <cstdint>
#include <string>
#include <vector>

namespace fridge_ink::ui {
namespace {

using platform::panel_font_assets::BitmapFont;
using platform::panel_font_assets::Glyph;

constexpr int kPW = 480;
constexpr int kPH = 800;

int normalize_rotation_deg(const int raw) {
  const int rounded = ((raw % 360) + 360) % 360;
  if (rounded >= 315 || rounded < 45) {
    return 0;
  }
  if (rounded < 135) {
    return 90;
  }
  if (rounded < 225) {
    return 180;
  }
  return 270;
}

bool use_r90_map(const app::AppState& state) {
  return normalize_rotation_deg(state.settings.rotation_deg) == 90;
}

void mp_px(std::vector<uint8_t>& image, const int cx, const int cy, const bool r90) {
  if (cx < 0 || cx >= kPW || cy < 0 || cy >= kPH) {
    return;
  }
  if (r90) {
    set_black_pixel(image, cy, 479 - cx);
  } else {
    set_black_pixel(image, 799 - cy, cx);
  }
}

void mp_clr(std::vector<uint8_t>& image, const int cx, const int cy, const bool r90) {
  if (cx < 0 || cx >= kPW || cy < 0 || cy >= kPH) {
    return;
  }
  if (r90) {
    clear_pixel(image, cy, 479 - cx);
  } else {
    clear_pixel(image, 799 - cy, cx);
  }
}

void mp_fill(
    std::vector<uint8_t>& image,
    const int x0,
    const int y0,
    const int x1,
    const int y1,
    const bool r90) {
  for (int y = y0; y < y1; ++y) {
    for (int x = x0; x < x1; ++x) {
      mp_px(image, x, y, r90);
    }
  }
}

std::size_t memo_glyph_index(const char ch) {
  const unsigned char code = static_cast<unsigned char>(ch);
  if (code < 32 || code > 126) {
    return static_cast<std::size_t>('?' - 32);
  }
  return static_cast<std::size_t>(code - 32);
}

const BitmapFont& memo_font_for_scale_normal(const int scale) {
  using namespace platform::panel_font_assets;
  if (scale <= 1) {
    return kFontJetBold13;
  }
  if (scale == 2) {
    return kFontInterMedium18;
  }
  return kFontInterBlack29;
}

const BitmapFont& memo_font_for_scale_inverted(const int scale) {
  using namespace platform::panel_font_assets;
  if (scale <= 1) {
    return kFontJetBold13;
  }
  if (scale == 2) {
    return kFontInterBold17;
  }
  return kFontInterBlack29;
}

void memo_glyph(
    std::vector<uint8_t>& image,
    const int x,
    const int y,
    const char ch,
    const BitmapFont& font,
    const bool r90,
    const bool black) {
  const Glyph& glyph = font.glyphs[memo_glyph_index(ch)];
  if (!glyph.width || !glyph.height) {
    return;
  }
  const int row_bytes = (glyph.width + 7) / 8;
  const std::uint8_t* bitmap = font.bitmap + glyph.bitmap_offset;
  for (int row = 0; row < glyph.height; ++row) {
    for (int col = 0; col < glyph.width; ++col) {
      if ((bitmap[row * row_bytes + (col / 8)] & (0x80U >> (col % 8))) == 0) {
        continue;
      }
      const int px = x + glyph.left + col;
      const int py = y + static_cast<int>(glyph.top) + row;
      if (black) {
        mp_px(image, px, py, r90);
      } else {
        mp_clr(image, px, py, r90);
      }
    }
  }
}

void memo_text_line(
    std::vector<uint8_t>& image,
    const int x,
    const int y,
    const std::string& text,
    const int scale,
    const int max_chars,
    const bool r90) {
  const BitmapFont& font = memo_font_for_scale_normal(scale);
  int cx = x;
  int drawn = 0;
  for (const char ch : text) {
    if (max_chars > 0 && drawn >= max_chars) {
      break;
    }
    memo_glyph(image, cx, y, ch, font, r90, true);
    cx += font.glyphs[memo_glyph_index(ch)].advance;
    ++drawn;
  }
}

void memo_text_line_inverted(
    std::vector<uint8_t>& image,
    const int x,
    const int y,
    const std::string& text,
    const int scale,
    const int max_chars,
    const bool r90) {
  const BitmapFont& font = memo_font_for_scale_inverted(scale);
  int cx = x;
  int drawn = 0;
  for (const char ch : text) {
    if (max_chars > 0 && drawn >= max_chars) {
      break;
    }
    memo_glyph(image, cx, y, ch, font, r90, false);
    cx += font.glyphs[memo_glyph_index(ch)].advance;
    ++drawn;
  }
}

int memo_text_width(const std::string& text, const int scale) {
  const BitmapFont& font = memo_font_for_scale_normal(scale);
  int width = 0;
  for (const char ch : text) {
    width += font.glyphs[memo_glyph_index(ch)].advance;
  }
  return width;
}

std::string upper_copy(const std::string& text) {
  std::string out = text;
  for (char& ch : out) {
    ch = static_cast<char>(std::toupper(static_cast<unsigned char>(ch)));
  }
  return out;
}

std::string trim_or_default(const std::string& text, const std::string& fallback) {
  const std::string trimmed = trim_copy(text);
  return trimmed.empty() ? fallback : trimmed;
}

int window_start(const int total, const int slots, const int selected) {
  if (total <= slots) {
    return 0;
  }
  return std::max(0, std::min(selected - (slots / 2), total - slots));
}

int selected_memo_index(const app::AppState& state) {
  const int total = static_cast<int>(state.dashboard.memos.size());
  if (total <= 0) {
    return 0;
  }
  int selected = state.memo.index % total;
  if (selected < 0) {
    selected += total;
  }
  return selected;
}

}  // namespace

std::vector<uint8_t> render_memo_portrait_bitmap(const app::AppState& state) {
  using platform::kPanelBufferSize;

  const auto& s = get_ui_strings(state.device_language);
  std::vector<uint8_t> image(kPanelBufferSize, 0xFF);
  const bool r90 = use_r90_map(state);

  const int left = 24;
  const int right = kPW - 24;
  const int content_top = 86;
  const int content_bottom = kPH - 56;

  memo_text_line(image, left, 16, s.memo_title, 3, 20, r90);
  const std::string hint = truncate_text_px(
      s.memo_hint,
      1,
      std::max(80, right - left));
  const int hint_w = memo_text_width(hint, 1);
  memo_text_line(image, std::max(left, right - hint_w), 52, hint, 1, 0, r90);
  mp_fill(image, left, 68, right, 70, r90);

  const auto& memos = state.dashboard.memos;
  const int total = static_cast<int>(memos.size());
  const int selected = selected_memo_index(state);

  if (total <= 0) {
    memo_text_line(image, left + 4, content_top + 8, s.memo_empty, 2, 24, r90);
    memo_text_line(
        image,
        left + 4,
        content_top + 42,
        s.memo_empty_voice,
        1,
        52,
        r90);
  } else {
    int unread = 0;
    for (const auto& memo : memos) {
      if (memo.is_new) {
        ++unread;
      }
    }

    const std::string summary =
        std::string(s.memo_total) + " " + std::to_string(total) +
        "   " + s.memo_count_new + " " + std::to_string(unread) +
        "   " + s.memo_focus + " " + std::to_string(selected + 1) + "/" + std::to_string(total);
    memo_text_line(
        image,
        left + 4,
        content_top,
        truncate_text_px(summary, 1, right - left - 8),
        1,
        0,
        r90);

    const int row_h = 66;
    const int row_gap = 6;
    const int list_top = content_top + 22;
    const int available_h = std::max(1, content_bottom - list_top);
    const int slots = std::max(1, (available_h + row_gap) / (row_h + row_gap));
    const int start = window_start(total, slots, selected);
    const bool expanded = state.memo.expanded;

    for (int i = 0; i < slots; ++i) {
      const int idx = start + i;
      if (idx >= total) {
        break;
      }
      const int y0 = list_top + i * (row_h + row_gap);
      const int y1 = std::min(content_bottom, y0 + row_h);
      if (y1 <= y0) {
        continue;
      }

      const bool is_selected = idx == selected;
      const int cx0 = left + 4;
      const int cx1 = right - 4;
      if (is_selected) {
        mp_fill(image, cx0, y0 + 1, cx1, y1 - 1, r90);
      } else {
        mp_fill(image, cx0 + 8, y1 - 1, cx1, y1, r90);
      }

      const auto& memo = memos[static_cast<std::size_t>(idx)];
      const std::string author = upper_copy(trim_or_default(memo.author, s.memo_unknown));
      const std::string posted = upper_copy(trim_or_default(memo.posted, s.memo_unknown_time));
      const std::string body = trim_or_default(memo.text, "No content.");

      const int content_x0 = cx0 + 10;
      const int content_x1 = cx1 - 10;
      const int posted_w = memo_text_width(posted, 1);
      const int posted_x = std::max(content_x0, content_x1 - posted_w);
      const int author_max_w = std::max(56, posted_x - content_x0 - 8);
      const std::string author_fit = truncate_text_px(author, 2, author_max_w);

      if (is_selected) {
        memo_text_line_inverted(image, content_x0, y0 + 6, author_fit, 2, 0, r90);
        memo_text_line_inverted(image, posted_x, y0 + 10, posted, 1, 0, r90);
      } else {
        memo_text_line(image, content_x0, y0 + 6, author_fit, 2, 0, r90);
        memo_text_line(image, posted_x, y0 + 10, posted, 1, 0, r90);
      }

      const int body_width = std::max(48, content_x1 - content_x0);
      const int max_body_lines = (is_selected && expanded) ? 2 : 1;
      const int chars_per_line = std::max(8, body_width / 10);
      const std::vector<std::string> wrapped = wrap_words(body, static_cast<std::size_t>(chars_per_line));
      const int lines = std::min(max_body_lines, static_cast<int>(wrapped.size()));
      int body_y = y0 + 34;
      for (int ln = 0; ln < lines; ++ln) {
        const std::string line = truncate_text_px(wrapped[static_cast<std::size_t>(ln)], 2, body_width);
        if (is_selected) {
          memo_text_line_inverted(image, content_x0, body_y, line, 2, 0, r90);
        } else {
          memo_text_line(image, content_x0, body_y, line, 2, 0, r90);
        }
        body_y += 24;
      }
      if (static_cast<int>(wrapped.size()) > lines && lines > 0) {
        const int ellipsis_w = memo_text_width("...", 1);
        const int ellipsis_x = std::max(content_x0, content_x1 - ellipsis_w);
        if (is_selected) {
          memo_text_line_inverted(image, ellipsis_x, body_y - 10, "...", 1, 3, r90);
        } else {
          memo_text_line(image, ellipsis_x, body_y - 10, "...", 1, 3, r90);
        }
      }

      if (memo.is_new) {
        const std::string badge = s.memo_badge_new;
        const int badge_w = memo_text_width(badge, 1);
        const int badge_x = std::max(content_x0, content_x1 - badge_w);
        if (is_selected) {
          memo_text_line_inverted(image, badge_x, y1 - 18, badge, 1, 3, r90);
        } else {
          memo_text_line(image, badge_x, y1 - 18, badge, 1, 3, r90);
        }
      }
    }

    if (total > slots) {
      const std::string tail =
          std::string(s.memo_showing) + " " + std::to_string(start + 1) + "-" +
          std::to_string(std::min(total, start + slots)) +
          " " + s.memo_of + " " + std::to_string(total);
      memo_text_line(
          image,
          left + 4,
          content_bottom - 16,
          truncate_text_px(tail, 1, right - left - 8),
          1,
          0,
          r90);
    }
  }

  const std::string footer = truncate_text_px(
      s.memo_footer,
      1,
      std::max(80, right - left));
  memo_text_line(image, left, kPH - 40, footer, 1, 40, r90);

  return image;
}

}  // namespace fridge_ink::ui
