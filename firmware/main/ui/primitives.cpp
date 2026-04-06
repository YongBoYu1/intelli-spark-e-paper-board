#include "ui/primitives.hpp"

#include "ui/draw.hpp"
#include "ui/weather_icon_assets_generated.hpp"

#include <algorithm>
#include <cmath>
#include <string>

namespace fridge_ink::ui {
namespace {

std::string normalize_icon_key(std::string value) {
  value = trim_copy(value);
  for (char& ch : value) {
    if (ch >= 'A' && ch <= 'Z') {
      ch = static_cast<char>(ch - ('A' - 'a'));
    } else if (ch == '-' || ch == ' ') {
      ch = '_';
    }
  }
  return value;
}

void draw_mask_icon_scaled_32(
    std::vector<uint8_t>& image,
    const int x,
    const int y,
    const int size,
    const char* const* rows) {
  const int draw_size = std::max(1, size);
  // Use area-style supersampling so upscaled 1-bit icons keep smoother edges
  // than nearest-neighbor pixel replication.
  const int kSrcSize = weather_icon_assets::kKickstandThinGridSize;
  constexpr int kSamples = 3;
  const int on_threshold = draw_size >= kSrcSize ? 5 : 4;
  for (int yy = 0; yy < draw_size; ++yy) {
    for (int xx = 0; xx < draw_size; ++xx) {
      int on_count = 0;
      for (int sy = 0; sy < kSamples; ++sy) {
        const float fy = static_cast<float>(yy) +
                         (static_cast<float>(sy) + 0.5f) / static_cast<float>(kSamples);
        int src_y = static_cast<int>(fy * static_cast<float>(kSrcSize) /
                                     static_cast<float>(draw_size));
        src_y = std::max(0, std::min(kSrcSize - 1, src_y));
        for (int sx = 0; sx < kSamples; ++sx) {
          const float fx = static_cast<float>(xx) +
                           (static_cast<float>(sx) + 0.5f) / static_cast<float>(kSamples);
          int src_x = static_cast<int>(fx * static_cast<float>(kSrcSize) /
                                       static_cast<float>(draw_size));
          src_x = std::max(0, std::min(kSrcSize - 1, src_x));
          if (rows[src_y][src_x] == '#') {
            ++on_count;
          }
        }
      }
      if (on_count >= on_threshold) {
        set_black_pixel(image, x + xx, y + yy);
      }
    }
  }
}

void draw_checkbox_checkmark(
    std::vector<uint8_t>& image,
    const int x0,
    const int y0,
    const int size) {
  const int safe_size = std::max(10, size);
  const int stroke = std::max(1, safe_size / 7);
  const int brush_half = stroke / 2;

  const auto draw_brush = [&](const int px, const int py) {
    fill_black_rect(
        image,
        px - brush_half,
        py - brush_half,
        px - brush_half + stroke,
        py - brush_half + stroke);
  };

  const auto draw_segment = [&](const int ax, const int ay, const int bx, const int by) {
    const int dx = bx - ax;
    const int dy = by - ay;
    const int steps = std::max(std::abs(dx), std::abs(dy));
    if (steps <= 0) {
      draw_brush(ax, ay);
      return;
    }
    for (int i = 0; i <= steps; ++i) {
      const float t = static_cast<float>(i) / static_cast<float>(steps);
      const int px = static_cast<int>(std::lround(ax + static_cast<float>(dx) * t));
      const int py = static_cast<int>(std::lround(ay + static_cast<float>(dy) * t));
      draw_brush(px, py);
    }
  };

  // Match Python home_kitchen.py checkmark geometry:
  // [(cbx+3, cy), (cbx+5, cy+3), (cbx+10, cby+3)] for a 14px checkbox.
  const auto scale14 = [&](const int v) {
    return (safe_size * v + 7) / 14;
  };
  const int p0_x = x0 + scale14(3);
  const int p0_y = y0 + (safe_size / 2);
  const int p1_x = x0 + scale14(5);
  const int p1_y = y0 + scale14(10);
  const int p2_x = x0 + scale14(10);
  const int p2_y = y0 + scale14(3);
  draw_segment(p0_x, p0_y, p1_x, p1_y);
  draw_segment(p1_x, p1_y, p2_x, p2_y);
}

}  // namespace

std::string text_ellipsis(const std::string& text, const int scale, const int max_width_px) {
  return truncate_text_px(text, scale, std::max(0, max_width_px));
}

std::string draw_text_ellipsis(
    std::vector<uint8_t>& image,
    const int x,
    const int y,
    const int width_px,
    const std::string& text,
    const int scale,
    const bool inverted) {
  const std::string clipped = text_ellipsis(text, scale, width_px);
  if (inverted) {
    draw_text_line_inverted(image, x, y, clipped, scale, 0);
  } else {
    draw_text_line(image, x, y, clipped, scale, 0);
  }
  return clipped;
}

void draw_checkbox(
    std::vector<uint8_t>& image,
    const int x,
    const int y,
    const bool checked,
    const bool focused,
    const int size) {
  const int safe_size = std::max(10, size);
  if (focused) {
    draw_rounded_rect_stroke(
        image,
        x - 3,
        y - 3,
        x + safe_size + 4,
        y + safe_size + 4,
        4,
        1);
  }
  draw_rounded_rect_stroke(image, x, y, x + safe_size + 1, y + safe_size + 1, 3, 2);
  if (checked) {
    draw_checkbox_checkmark(image, x, y, safe_size);
  }
}

void draw_list_row(
    std::vector<uint8_t>& image,
    const int x,
    const int y,
    const int width_px,
    const int height_px,
    const std::string& text,
    const bool checked,
    const bool focused,
    const int text_scale) {
  const int row_w = std::max(1, width_px);
  const int row_h = std::max(1, height_px);
  if (focused) {
    draw_rounded_rect_stroke(image, x - 6, y + 4, x + row_w + 6, y + row_h - 4, 6, 1);
  }

  const int checkbox_size = 14;
  const int cb_x = x;
  const int cb_y = y + ((row_h - checkbox_size) / 2);
  draw_checkbox(image, cb_x, cb_y, checked, false, checkbox_size);

  const int text_x = x + 30;
  const int text_y = y + ((row_h - 18) / 2);
  draw_text_ellipsis(image, text_x, text_y, row_w - 34, text, text_scale, false);
}

void draw_icon(
    std::vector<uint8_t>& image,
    const int x,
    const int y,
    const std::string& icon_id,
    const int size) {
  using namespace weather_icon_assets;

  const std::string key = normalize_icon_key(icon_id);
  const char* const* rows = kKickstandCloudThin32;

  if (key.find("partly") != std::string::npos) {
    rows = kKickstandPartlySunnyThin32;
  } else if (key.find("clear") != std::string::npos || key.find("sun") != std::string::npos) {
    rows = kKickstandSunThin32;
  } else if (key.find("rain") != std::string::npos || key.find("drizzle") != std::string::npos) {
    rows = kKickstandRainThin32;
  } else if (key.find("snow") != std::string::npos) {
    rows = kKickstandSnowThin32;
  } else if (key.find("storm") != std::string::npos || key.find("thunder") != std::string::npos) {
    rows = kKickstandStormThin32;
  } else if (key.find("haze") != std::string::npos || key.find("fog") != std::string::npos) {
    rows = kKickstandHazeThin32;
  } else if (key.find("hail") != std::string::npos) {
    rows = kKickstandHailThin32;
  } else if (key.find("moon") != std::string::npos || key.find("night") != std::string::npos) {
    rows = kKickstandMoonThin32;
  } else if (key.find("sunrise") != std::string::npos || key.find("dawn") != std::string::npos) {
    rows = kKickstandSunriseThin32;
  } else if (key.find("tornado") != std::string::npos) {
    rows = kKickstandTornadoThin32;
  }

  draw_mask_icon_scaled_32(image, x, y, size, rows);
}

}  // namespace fridge_ink::ui
