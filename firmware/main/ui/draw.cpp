#include "ui/draw.hpp"

#include "platform/panel_config.hpp"
#include "ui/panel_font_assets_generated.hpp"

#include <algorithm>
#include <cctype>
#include <cstdint>
#include <sstream>
#include <string>
#include <vector>

namespace fridge_ink::ui {

using platform::kPanelWidth;
using platform::kPanelHeight;
using platform::kPanelWidthBytes;
using platform::panel_font_assets::BitmapFont;
using platform::panel_font_assets::Glyph;

// ── Pixel operations ─────────────────────────────────────────────────────────

void set_black_pixel(std::vector<uint8_t>& image, const int x, const int y) {
  if (x < 0 || x >= kPanelWidth || y < 0 || y >= kPanelHeight) {
    return;
  }
  const int offset = (y * kPanelWidthBytes) + (x / 8);
  const uint8_t bit = static_cast<uint8_t>(0x80U >> (x % 8));
  image[offset] = static_cast<uint8_t>(image[offset] | bit);
}

void clear_pixel(std::vector<uint8_t>& image, const int x, const int y) {
  if (x < 0 || x >= kPanelWidth || y < 0 || y >= kPanelHeight) {
    return;
  }
  const int offset = (y * kPanelWidthBytes) + (x / 8);
  const uint8_t bit = static_cast<uint8_t>(0x80U >> (x % 8));
  image[offset] = static_cast<uint8_t>(image[offset] & static_cast<uint8_t>(~bit));
}

void fill_black_rect(
    std::vector<uint8_t>& image,
    const int x0, const int y0, const int x1, const int y1) {
  for (int y = y0; y < y1; ++y) {
    for (int x = x0; x < x1; ++x) {
      set_black_pixel(image, x, y);
    }
  }
}

void fill_white_rect(
    std::vector<uint8_t>& image,
    const int x0, const int y0, const int x1, const int y1) {
  for (int y = y0; y < y1; ++y) {
    for (int x = x0; x < x1; ++x) {
      clear_pixel(image, x, y);
    }
  }
}

// ── Rectangle drawing ────────────────────────────────────────────────────────

void draw_outline_rect(
    std::vector<uint8_t>& image,
    const int x0, const int y0, const int x1, const int y1,
    const int thickness) {
  const int t = thickness > 0 ? thickness : 1;
  fill_black_rect(image, x0, y0, x1, y0 + t);
  fill_black_rect(image, x0, y1 - t, x1, y1);
  fill_black_rect(image, x0, y0, x0 + t, y1);
  fill_black_rect(image, x1 - t, y0, x1, y1);
}

bool point_in_rounded_rect(
    const int px, const int py,
    const int x0, const int y0, const int x1, const int y1,
    const int radius) {
  if (px < x0 || px >= x1 || py < y0 || py >= y1) {
    return false;
  }
  const int w = x1 - x0;
  const int h = y1 - y0;
  const int r = std::max(0, std::min(radius, std::min(w, h) / 2));
  if (r <= 0) {
    return true;
  }
  if ((px >= x0 + r && px < x1 - r) || (py >= y0 + r && py < y1 - r)) {
    return true;
  }
  const int cx = (px < x0 + r) ? (x0 + r) : (x1 - r - 1);
  const int cy = (py < y0 + r) ? (y0 + r) : (y1 - r - 1);
  const int dx = px - cx;
  const int dy = py - cy;
  return (dx * dx + dy * dy) <= (r * r);
}

void fill_rounded_rect(
    std::vector<uint8_t>& image,
    const int x0, const int y0, const int x1, const int y1,
    const int radius, const bool black) {
  for (int y = y0; y < y1; ++y) {
    for (int x = x0; x < x1; ++x) {
      if (!point_in_rounded_rect(x, y, x0, y0, x1, y1, radius)) {
        continue;
      }
      if (black) {
        set_black_pixel(image, x, y);
      } else {
        clear_pixel(image, x, y);
      }
    }
  }
}

void draw_rounded_rect_outline(
    std::vector<uint8_t>& image,
    const int x0, const int y0, const int x1, const int y1,
    const int radius, const int thickness) {
  fill_rounded_rect(image, x0, y0, x1, y1, radius, true);
  const int t = std::max(1, thickness);
  const int inner_x0 = x0 + t;
  const int inner_y0 = y0 + t;
  const int inner_x1 = x1 - t;
  const int inner_y1 = y1 - t;
  if (inner_x1 > inner_x0 && inner_y1 > inner_y0) {
    fill_rounded_rect(
        image, inner_x0, inner_y0, inner_x1, inner_y1,
        std::max(0, radius - t), false);
  }
}

void draw_rounded_rect_stroke(
    std::vector<uint8_t>& image,
    const int x0, const int y0, const int x1, const int y1,
    const int radius, const int thickness) {
  const int t = std::max(1, thickness);
  const int inner_x0 = x0 + t;
  const int inner_y0 = y0 + t;
  const int inner_x1 = x1 - t;
  const int inner_y1 = y1 - t;
  const int inner_radius = std::max(0, radius - t);
  for (int y = y0; y < y1; ++y) {
    for (int x = x0; x < x1; ++x) {
      if (!point_in_rounded_rect(x, y, x0, y0, x1, y1, radius)) {
        continue;
      }
      if (inner_x1 > inner_x0 &&
          inner_y1 > inner_y0 &&
          point_in_rounded_rect(x, y, inner_x0, inner_y0, inner_x1, inner_y1, inner_radius)) {
        continue;
      }
      set_black_pixel(image, x, y);
    }
  }
}

// ── Font / glyph helpers (internal) ──────────────────────────────────────────

namespace {

std::size_t glyph_index(const char ch) {
  const unsigned char code = static_cast<unsigned char>(ch);
  if (code < 32 || code > 126) {
    return static_cast<std::size_t>('?' - 32);
  }
  return static_cast<std::size_t>(code - 32);
}

namespace pfa = platform::panel_font_assets;

const BitmapFont& font_for_scale(const int scale, const bool black = true) {
  if (scale <= 1) {
    return pfa::kFontJetBold13;
  }
  if (scale == 2) {
    return black ? pfa::kFontInterMedium18 : pfa::kFontInterBold17;
  }
  return pfa::kFontInterBlack29;
}

const BitmapFont& font_for_scale_normal(const int scale) {
  if (scale <= 1) {
    return pfa::kFontJetBold13;
  }
  if (scale == 2) {
    return pfa::kFontInterMedium18;
  }
  return pfa::kFontInterBlack29;
}

const BitmapFont& font_for_scale_inverted(const int scale) {
  if (scale <= 1) {
    return pfa::kFontJetBold13;
  }
  if (scale == 2) {
    return pfa::kFontInterBold17;
  }
  return pfa::kFontInterBlack29;
}

}  // namespace

// ── Font / glyph rendering ──────────────────────────────────────────────────

void draw_glyph(
    std::vector<uint8_t>& image,
    const int x, const int y,
    const char ch, const int scale, const bool black) {
  const auto& font = font_for_scale(scale, black);
  const auto& glyph = font.glyphs[glyph_index(ch)];
  if (glyph.width == 0 || glyph.height == 0) {
    return;
  }

  const int baseline_y = y + font.ascent;
  const int glyph_x0 = x + glyph.left;
  const int glyph_y0 = baseline_y + glyph.top;
  const int row_bytes = (glyph.width + 7) / 8;
  const std::uint8_t* bitmap = font.bitmap + glyph.bitmap_offset;
  for (int row = 0; row < glyph.height; ++row) {
    for (int col = 0; col < glyph.width; ++col) {
      const std::uint8_t byte = bitmap[row * row_bytes + (col / 8)];
      const bool on = (byte & (0x80U >> (col % 8))) != 0;
      if (!on) {
        continue;
      }
      const int px = glyph_x0 + col;
      const int py = glyph_y0 + row;
      if (black) {
        set_black_pixel(image, px, py);
      } else {
        clear_pixel(image, px, py);
      }
    }
  }
}

void draw_text_line(
    std::vector<uint8_t>& image,
    const int x, const int y,
    const std::string& text,
    const int scale, const int max_chars) {
  const auto& font = font_for_scale_normal(scale);
  int cx = x;
  int drawn = 0;
  for (const char ch : text) {
    if (max_chars > 0 && drawn >= max_chars) {
      break;
    }
    draw_glyph(image, cx, y, ch, scale, true);
    cx += font.glyphs[glyph_index(ch)].advance;
    ++drawn;
  }
}

void draw_text_line_inverted(
    std::vector<uint8_t>& image,
    const int x, const int y,
    const std::string& text,
    const int scale, const int max_chars) {
  const auto& font = font_for_scale_inverted(scale);
  int cx = x;
  int drawn = 0;
  for (const char ch : text) {
    if (max_chars > 0 && drawn >= max_chars) {
      break;
    }
    draw_glyph(image, cx, y, ch, scale, false);
    cx += font.glyphs[glyph_index(ch)].advance;
    ++drawn;
  }
}

void draw_text_centered(
    std::vector<uint8_t>& image,
    const int x0, const int x1, const int y,
    const std::string& text,
    const int scale, const int max_chars) {
  const std::string clipped = trunc_text(text, max_chars);
  const int w = text_width_px(clipped, scale);
  const int x = x0 + ((x1 - x0 - w) / 2);
  draw_text_line(image, x, y, clipped, scale, max_chars);
}

void draw_text_centered_inverted(
    std::vector<uint8_t>& image,
    const int x0, const int x1, const int y,
    const std::string& text,
    const int scale, const int max_chars) {
  const std::string clipped = trunc_text(text, max_chars);
  const int w = text_width_px(clipped, scale);
  const int x = x0 + ((x1 - x0 - w) / 2);
  draw_text_line_inverted(image, x, y, clipped, scale, max_chars);
}

void draw_text_wrapped(
    std::vector<uint8_t>& image,
    const int x, int y, const int width_px,
    const std::string& text,
    const int scale, const int max_lines) {
  if (max_lines <= 0 || width_px <= 0) {
    return;
  }
  const int avg_advance =
      scale <= 1 ? 8 : (scale == 2 ? 10 : (scale == 3 ? 15 : 18));
  const int chars_per_line = width_px / avg_advance > 0 ? width_px / avg_advance : 1;
  const auto wrapped = wrap_words(text, static_cast<std::size_t>(chars_per_line));
  const int line_h = scale <= 1 ? 18 : (scale == 2 ? 24 : 34);
  int drawn = 0;
  for (const auto& line : wrapped) {
    if (drawn >= max_lines) {
      break;
    }
    draw_text_line(image, x, y, line, scale, chars_per_line);
    y += line_h;
    ++drawn;
  }
}

void draw_text_wrapped_inverted(
    std::vector<uint8_t>& image,
    const int x, int y, const int width_px,
    const std::string& text,
    const int scale, const int max_lines) {
  if (max_lines <= 0 || width_px <= 0) {
    return;
  }
  const int avg_advance =
      scale <= 1 ? 8 : (scale == 2 ? 10 : (scale == 3 ? 15 : 18));
  const int chars_per_line = width_px / avg_advance > 0 ? width_px / avg_advance : 1;
  const auto wrapped = wrap_words(text, static_cast<std::size_t>(chars_per_line));
  const int line_h = scale <= 1 ? 18 : (scale == 2 ? 24 : 34);
  int drawn = 0;
  for (const auto& line : wrapped) {
    if (drawn >= max_lines) {
      break;
    }
    draw_text_line_inverted(image, x, y, line, scale, chars_per_line);
    y += line_h;
    ++drawn;
  }
}

// ── Text measurement / utilities ─────────────────────────────────────────────

int text_width_px(const std::string& text, const int scale) {
  const auto& font = font_for_scale_normal(scale);
  int width = 0;
  for (const char ch : text) {
    width += font.glyphs[glyph_index(ch)].advance;
  }
  return width;
}

std::string truncate_text_px(
    const std::string& text,
    const int scale,
    const int max_width_px) {
  if (text.empty()) {
    return "";
  }
  if (text_width_px(text, scale) <= max_width_px) {
    return text;
  }
  const std::string ellipsis = "...";
  const int ellipsis_width = text_width_px(ellipsis, scale);
  const int budget = std::max(0, max_width_px - ellipsis_width);
  std::string out;
  for (const char ch : text) {
    const std::string candidate = out + ch;
    if (text_width_px(candidate, scale) > budget) {
      break;
    }
    out = candidate;
  }
  return out.empty() ? ellipsis : (out + ellipsis);
}

std::string trunc_text(const std::string& text, const int max_chars) {
  if (max_chars <= 0) {
    return "";
  }
  if (static_cast<int>(text.size()) <= max_chars) {
    return text;
  }
  if (max_chars <= 3) {
    return text.substr(0, static_cast<size_t>(max_chars));
  }
  return text.substr(0, static_cast<size_t>(max_chars - 3)) + "...";
}

std::string trim_copy(const std::string& in) {
  std::size_t start = 0;
  while (start < in.size() &&
         std::isspace(static_cast<unsigned char>(in[start])) != 0) {
    ++start;
  }
  if (start == in.size()) {
    return "";
  }
  std::size_t end = in.size();
  while (end > start &&
         std::isspace(static_cast<unsigned char>(in[end - 1])) != 0) {
    --end;
  }
  return in.substr(start, end - start);
}

std::vector<std::string> wrap_words(const std::string& text, const std::size_t max_chars) {
  std::vector<std::string> lines;
  if (text.empty() || max_chars == 0) {
    return lines;
  }

  std::istringstream iss(text);
  std::string word;
  std::string current;

  while (iss >> word) {
    if (word.size() > max_chars) {
      if (!current.empty()) {
        lines.push_back(current);
        current.clear();
      }
      std::size_t offset = 0;
      while (offset < word.size()) {
        lines.push_back(word.substr(offset, max_chars));
        offset += max_chars;
      }
      continue;
    }

    if (current.empty()) {
      current = word;
      continue;
    }

    if ((current.size() + 1 + word.size()) <= max_chars) {
      current.push_back(' ');
      current.append(word);
      continue;
    }

    lines.push_back(current);
    current = word;
  }

  if (!current.empty()) {
    lines.push_back(current);
  }

  if (lines.empty()) {
    lines.push_back(text.substr(0, max_chars));
  }
  return lines;
}

}  // namespace fridge_ink::ui
