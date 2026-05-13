#include "ui/screens/settings_screen.hpp"

#include "platform/panel_config.hpp"
#include "ui/draw.hpp"
#include "ui/panel_font_assets_generated.hpp"
#include "ui/strings.hpp"

#include <algorithm>
#include <array>
#include <ctime>
#include <cstdint>
#include <string>
#include <vector>

namespace fridge_ink::ui {
namespace {

using platform::panel_font_assets::BitmapFont;
using platform::panel_font_assets::Glyph;

enum class SettingsItem {
  FontSize = 0,
  PartialRefresh = 1,
  FullRefresh = 2,
  Rotation = 3,
  Language = 4,
  Connectivity = 5,
  AutoSync = 6,
  SyncNow = 7,
  ChangeWifi = 8,
  ResetAndWipe = 9,
};

constexpr std::array<SettingsItem, 10> kSettingsOrder = {
    SettingsItem::FontSize,
    SettingsItem::PartialRefresh,
    SettingsItem::FullRefresh,
    SettingsItem::Rotation,
    SettingsItem::Language,
    SettingsItem::Connectivity,
    SettingsItem::AutoSync,
    SettingsItem::SyncNow,
    SettingsItem::ChangeWifi,
    SettingsItem::ResetAndWipe,
};

enum class FontSizeMode {
  Small,
  Medium,
  Large,
};

int normalize_rotation_deg(const int raw) {
  const int n = ((raw % 360) + 360) % 360;
  if (n >= 315 || n < 45) {
    return 0;
  }
  if (n < 135) {
    return 90;
  }
  if (n < 225) {
    return 180;
  }
  return 270;
}

struct RotatedCanvas {
  int source_w{0};
  int source_h{0};
  int rotation_deg{0};
  std::vector<uint8_t> image{};
};

RotatedCanvas make_rotated_canvas(
    const int source_w,
    const int source_h,
    const int rotation_deg) {
  return RotatedCanvas{
      std::max(1, source_w),
      std::max(1, source_h),
      normalize_rotation_deg(rotation_deg),
      std::vector<uint8_t>(platform::kPanelBufferSize, 0xFF),
  };
}

bool map_source_to_panel(
    const RotatedCanvas& canvas,
    const int sx,
    const int sy,
    int& dx,
    int& dy) {
  if (sx < 0 || sx >= canvas.source_w || sy < 0 || sy >= canvas.source_h) {
    return false;
  }

  const int rot = canvas.rotation_deg;
  if (rot == 90) {
    dx = sy;
    dy = canvas.source_w - 1 - sx;
  } else if (rot == 180) {
    dx = canvas.source_w - 1 - sx;
    dy = canvas.source_h - 1 - sy;
  } else if (rot == 270) {
    dx = canvas.source_h - 1 - sy;
    dy = sx;
  } else {
    dx = sx;
    dy = sy;
  }

  if (dx < 0 || dx >= platform::kPanelWidth || dy < 0 || dy >= platform::kPanelHeight) {
    return false;
  }
  return true;
}

void canvas_set_black(
    RotatedCanvas& canvas,
    const int sx,
    const int sy) {
  int dx = 0;
  int dy = 0;
  if (!map_source_to_panel(canvas, sx, sy, dx, dy)) {
    return;
  }
  set_black_pixel(canvas.image, dx, dy);
}

void canvas_fill_black_rect(
    RotatedCanvas& canvas,
    const int x0,
    const int y0,
    const int x1,
    const int y1) {
  for (int y = y0; y < y1; ++y) {
    for (int x = x0; x < x1; ++x) {
      canvas_set_black(canvas, x, y);
    }
  }
}

std::size_t glyph_index(const char ch) {
  const unsigned char c = static_cast<unsigned char>(ch);
  if (c < 32 || c > 126) {
    return static_cast<std::size_t>('?' - 32);
  }
  return static_cast<std::size_t>(c - 32);
}

void draw_canvas_glyph(
    RotatedCanvas& canvas,
    const int x,
    const int y,
    const char ch,
    const BitmapFont& f) {
  const Glyph& g = f.glyphs[glyph_index(ch)];
  if (!g.width || !g.height) {
    return;
  }

  const int row_bytes = (g.width + 7) / 8;
  const std::uint8_t* bitmap = f.bitmap + g.bitmap_offset;
  for (int row = 0; row < g.height; ++row) {
    for (int col = 0; col < g.width; ++col) {
      if ((bitmap[row * row_bytes + col / 8] & (0x80U >> (col % 8))) != 0) {
        canvas_set_black(
            canvas,
            x + g.left + col,
            y + static_cast<int>(g.top) + row);
      }
    }
  }
}

int glyph_advance(const char ch, const BitmapFont& f) {
  return f.glyphs[glyph_index(ch)].advance;
}

int text_width(const std::string& text, const BitmapFont& f) {
  int width = 0;
  for (const char ch : text) {
    width += glyph_advance(ch, f);
  }
  return width;
}

struct VisualBounds {
  int top{0};
  int bottom{0};
  bool ok{false};
};

VisualBounds visual_bounds(const std::string& text, const BitmapFont& f) {
  VisualBounds bounds{};
  for (const char ch : text) {
    const Glyph& g = f.glyphs[glyph_index(ch)];
    if (!g.width || !g.height) {
      continue;
    }
    if (!bounds.ok) {
      bounds.top = static_cast<int>(g.top);
      bounds.bottom = static_cast<int>(g.top) + g.height;
      bounds.ok = true;
      continue;
    }
    bounds.top = std::min(bounds.top, static_cast<int>(g.top));
    bounds.bottom = std::max(bounds.bottom, static_cast<int>(g.top) + g.height);
  }
  return bounds;
}

int y_for_visual_top(const int visual_top, const std::string& text, const BitmapFont& f) {
  const VisualBounds bounds = visual_bounds(text, f);
  return bounds.ok ? visual_top - bounds.top : visual_top;
}

int y_for_centered_text(
    const int zone_y,
    const int zone_h,
    const std::string& text,
    const BitmapFont& f) {
  const VisualBounds bounds = visual_bounds(text, f);
  if (!bounds.ok) {
    return zone_y + (zone_h - static_cast<int>(f.line_height)) / 2;
  }
  return zone_y + (zone_h - (bounds.bottom - bounds.top)) / 2 - bounds.top;
}

void draw_canvas_text(
    RotatedCanvas& canvas,
    int x,
    const int y,
    const std::string& text,
    const BitmapFont& f) {
  for (const char ch : text) {
    draw_canvas_glyph(canvas, x, y, ch, f);
    x += glyph_advance(ch, f);
  }
}

std::string truncate_text(
    const std::string& text,
    const BitmapFont& f,
    const int max_px) {
  if (max_px <= 0) {
    return {};
  }
  int width = 0;
  std::string out;
  for (const char ch : text) {
    const int adv = glyph_advance(ch, f);
    if (width + adv > max_px) {
      const std::string ellipsis = "...";
      const int ellipsis_w = text_width(ellipsis, f);
      while (!out.empty() && text_width(out, f) + ellipsis_w > max_px) {
        out.pop_back();
      }
      return out + ellipsis;
    }
    width += adv;
    out.push_back(ch);
  }
  return out;
}

std::string upper_copy(const std::string& text) {
  std::string out = text;
  for (char& ch : out) {
    if (ch >= 'a' && ch <= 'z') {
      ch = static_cast<char>(ch - 32);
    }
  }
  return out;
}

std::string lower_copy(const std::string& text) {
  std::string out = text;
  for (char& ch : out) {
    if (ch >= 'A' && ch <= 'Z') {
      ch = static_cast<char>(ch - 'A' + 'a');
    }
  }
  return out;
}

std::string bool_text(const bool value, const UiStrings& s) {
  return value ? s.on : s.off;
}

std::string font_size_text(const std::string& raw, const UiStrings& s) {
  const std::string value = lower_copy(raw);
  if (value == "small") {
    return s.settings_small;
  }
  if (value == "large") {
    return s.settings_large;
  }
  return s.settings_medium;
}

std::string partial_refresh_text(const std::string& raw, const UiStrings& s) {
  const std::string value = lower_copy(raw);
  if (value == "slow") {
    return s.settings_slow;
  }
  if (value == "fast") {
    return s.settings_fast;
  }
  return s.settings_balanced;
}

FontSizeMode font_size_mode(const app::AppState& state) {
  const std::string value = lower_copy(state.settings.font_size);
  if (value == "small") {
    return FontSizeMode::Small;
  }
  if (value == "large") {
    return FontSizeMode::Large;
  }
  return FontSizeMode::Medium;
}

double font_scale(const FontSizeMode mode) {
  if (mode == FontSizeMode::Small) {
    return 0.9;
  }
  if (mode == FontSizeMode::Large) {
    return 1.12;
  }
  return 1.0;
}

struct SettingsTypography {
  const BitmapFont* title_font{nullptr};
  const BitmapFont* hint_font{nullptr};
  const BitmapFont* group_font{nullptr};
  const BitmapFont* label_font{nullptr};
  const BitmapFont* label_focus_font{nullptr};
  const BitmapFont* value_font{nullptr};
  const BitmapFont* footer_font{nullptr};
};

SettingsTypography settings_typography_for(const FontSizeMode mode) {
  using namespace platform::panel_font_assets;
  if (mode == FontSizeMode::Small) {
    return SettingsTypography{
        &kFontInterBold29,
        &kFontJetBold13,
        &kFontJetBold13,
        &kFontInterBold17,
        &kFontInterBold18,
        &kFontJetBold13,
        &kFontJetBold13,
    };
  }
  if (mode == FontSizeMode::Large) {
    return SettingsTypography{
        &kFontInterBlack36,
        &kFontJetBold15,
        &kFontJetBold15,
        &kFontInterBold20,
        &kFontInterBold22,
        &kFontJetExtraBold16,
        &kFontJetBold15,
    };
  }
  return SettingsTypography{
      &kFontInterBold29,
      &kFontJetBold13,
      &kFontJetBold13,
      &kFontInterMedium18,
      &kFontInterBold20,
      &kFontJetExtraBold16,
      &kFontJetBold13,
  };
}

int text_visual_height(const std::string& text, const BitmapFont& f) {
  const VisualBounds bounds = visual_bounds(text, f);
  if (!bounds.ok) {
    return static_cast<int>(f.line_height);
  }
  return bounds.bottom - bounds.top;
}

std::string last_sync_text(const app::AppState& state, const UiStrings& s) {
  if (state.settings.last_sync_ms <= 0) {
    return s.settings_never;
  }
  const std::time_t ts = static_cast<std::time_t>(state.settings.last_sync_ms / 1000ULL);
  if (ts <= 0) {
    return s.settings_never;
  }
  std::tm local_tm{};
  if (localtime_r(&ts, &local_tm) == nullptr) {
    return s.settings_invalid_time;
  }
  char buf[20] = {0};
  if (std::strftime(buf, sizeof(buf), "%Y-%m-%d %H:%M:%S", &local_tm) == 0) {
    return s.settings_invalid_time;
  }
  return std::string(buf);
}

std::string setting_label(const SettingsItem item, const UiStrings& s) {
  switch (item) {
    case SettingsItem::FontSize:       return s.settings_font_size;
    case SettingsItem::PartialRefresh: return s.settings_partial_refresh;
    case SettingsItem::FullRefresh:    return s.settings_full_refresh;
    case SettingsItem::Rotation:       return s.settings_rotation;
    case SettingsItem::Language:       return s.settings_language;
    case SettingsItem::Connectivity:   return s.settings_connectivity;
    case SettingsItem::AutoSync:       return s.settings_auto_sync;
    case SettingsItem::SyncNow:        return s.settings_sync_now;
    case SettingsItem::ChangeWifi:     return s.settings_change_wifi;
    case SettingsItem::ResetAndWipe:   return s.settings_reset;
  }
  return {};
}

std::string setting_value(const app::AppState& state, const SettingsItem item, const UiStrings& s) {
  switch (item) {
    case SettingsItem::FontSize:
      return font_size_text(state.settings.font_size, s);
    case SettingsItem::PartialRefresh:
      return partial_refresh_text(state.settings.partial_refresh_mode, s);
    case SettingsItem::FullRefresh:
      return std::string(s.settings_every) + " " +
             std::to_string(std::max(1, state.settings.full_refresh_every)) +
             " " + s.settings_partials;
    case SettingsItem::Rotation:
      return std::to_string(normalize_rotation_deg(state.settings.rotation_deg));
    case SettingsItem::Language:
      return upper_copy(app::language_label(state.device_language));
    case SettingsItem::Connectivity:
      return std::string("WIFI ") + bool_text(state.settings.wifi_enabled, s) +
             " / BT " + bool_text(state.settings.bluetooth_enabled, s);
    case SettingsItem::AutoSync:
      return bool_text(state.settings.auto_sync_enabled, s);
    case SettingsItem::SyncNow:
      return s.settings_press_enter;
    case SettingsItem::ChangeWifi:
      return state.onboarding.wifi_ssid.empty() ? s.settings_not_set
                                                : state.onboarding.wifi_ssid;
    case SettingsItem::ResetAndWipe:
      return s.settings_press_enter;
  }
  return {};
}

void render_settings_source(
    RotatedCanvas& canvas,
    const app::AppState& state) {
  const auto& s = get_ui_strings(state.device_language);
  const FontSizeMode fs_mode = font_size_mode(state);
  const double fs_scale = font_scale(fs_mode);
  const SettingsTypography typography = settings_typography_for(fs_mode);
  const BitmapFont& title_font = *typography.title_font;
  const BitmapFont& hint_font = *typography.hint_font;
  const BitmapFont& group_font = *typography.group_font;
  const BitmapFont& label_font = *typography.label_font;
  const BitmapFont& label_focus_font = *typography.label_focus_font;
  const BitmapFont& value_font = *typography.value_font;
  const BitmapFont& footer_font = *typography.footer_font;

  const int left = 24;
  const int right = canvas.source_w - 24;

  draw_canvas_text(
      canvas,
      left,
      y_for_visual_top(16, s.settings_title, title_font),
      s.settings_title,
      title_font);

  {
    const std::string raw = s.settings_hint_landscape;
    const std::string hint = truncate_text(raw, hint_font, std::max(80, right - left));
    const int hint_w = text_width(hint, hint_font);
    const int hint_x = std::max(left, right - hint_w);
    draw_canvas_text(
        canvas,
        hint_x,
        y_for_visual_top(52, hint, hint_font),
        hint,
        hint_font);
  }

  canvas_fill_black_rect(canvas, left, 68, right, 70);

  const int footer_h = std::max(28, text_visual_height("A", footer_font) + 12);
  const int footer_top = canvas.source_h - footer_h;
  const int content_top = 90;
  const int content_bottom = footer_top - 6;

  const int label_h = text_visual_height("A", label_focus_font);
  const int value_h = text_visual_height("A", value_font);
  const int group_text_h = text_visual_height("A", group_font);

  int row_h = std::max(24, static_cast<int>(34.0 * fs_scale + 0.5));
  int row_gap = std::max(0, static_cast<int>(1.0 * fs_scale + 0.5));
  int group_h = std::max(14, static_cast<int>(20.0 * fs_scale + 0.5));
  int group_gap = std::max(2, static_cast<int>(7.0 * fs_scale + 0.5));
  const int min_row_h = std::max(24, std::max(label_h + 8, value_h + 8));
  const int min_group_h = std::max(14, group_text_h + 4);

  auto content_h = [&]() -> int {
    return group_h + (6 * row_h) + (5 * row_gap) + group_gap +
           group_h + (3 * row_h) + (2 * row_gap) +
           row_h;
  };

  const int avail = std::max(0, content_bottom - content_top);
  for (int iter = 0; iter < 120; ++iter) {
    if (content_h() <= avail) {
      break;
    }
    if (row_h > min_row_h) {
      --row_h;
      continue;
    }
    if (group_gap > 2) {
      --group_gap;
      continue;
    }
    if (group_h > min_group_h) {
      --group_h;
      continue;
    }
    if (row_gap > 0) {
      --row_gap;
      continue;
    }
    break;
  }

  const int focused = std::max(
      0,
      std::min(
          state.settings.focused_index,
          static_cast<int>(kSettingsOrder.size()) - 1));

  int y = content_top;
  auto draw_group = [&](const char* name, const int first, const int count) {
    if (name != nullptr && name[0] != '\0') {
      draw_canvas_text(
          canvas,
          left + 2,
          y_for_centered_text(y, group_h, name, group_font),
          name,
          group_font);
      y += group_h;
    }

    for (int i = 0; i < count; ++i) {
      const int idx = first + i;
      const SettingsItem item = kSettingsOrder[static_cast<std::size_t>(idx)];
      const bool is_focus = idx == focused;
      const BitmapFont& row_font = is_focus ? label_focus_font : label_font;
      const int y0 = y;

      const std::string value = truncate_text(
          setting_value(state, item, s),
          value_font,
          std::max(120, ((right - left) * 50) / 100));
      const int value_w = text_width(value, value_font);
      const int value_x = right - 12 - value_w;

      const std::string marker = is_focus ? ">" : " ";
      const int marker_w = text_width(marker, value_font);
      const int marker_x = left + 2;
      const int label_x = marker_x + marker_w + 8;
      const int label_max = std::max(100, value_x - label_x - 12);
      const std::string label = truncate_text(setting_label(item, s), row_font, label_max);

      draw_canvas_text(
          canvas,
          marker_x,
          y_for_centered_text(y0, row_h, marker, value_font),
          marker,
          value_font);
      draw_canvas_text(
          canvas,
          label_x,
          y_for_centered_text(y0, row_h, label, row_font),
          label,
          row_font);
      draw_canvas_text(
          canvas,
          value_x,
          y_for_centered_text(y0, row_h, value, value_font),
          value,
          value_font);

      if (is_focus) {
        canvas_fill_black_rect(canvas, label_x, y0 + row_h - 3, right - 12, y0 + row_h - 2);
      }

      y += row_h + row_gap;
    }
    y += group_gap;
  };

  draw_group(s.settings_group_display, 0, 6);
  draw_group(s.settings_group_sync, 6, 3);
  y = std::max(content_top, y - group_gap);
  draw_group("", 9, 1);

  canvas_fill_black_rect(canvas, left, footer_top - 1, right, footer_top);

  const std::string sync_raw = std::string(s.settings_last_sync_prefix) + " " + upper_copy(last_sync_text(state, s));
  const std::string sync = truncate_text(sync_raw, footer_font, std::max(80, right - left - 40));
  const int sync_w = text_width(sync, footer_font);
  const int sync_x = std::max(left, right - sync_w);

  const std::string notice = truncate_text(
      upper_copy(state.settings.notice),
      footer_font,
      std::max(40, sync_x - left - 12));
  if (!notice.empty()) {
    draw_canvas_text(
        canvas,
        left,
        y_for_centered_text(footer_top, footer_h, notice, footer_font),
        notice,
        footer_font);
  }

  draw_canvas_text(
      canvas,
      sync_x,
      y_for_centered_text(footer_top, footer_h, sync, footer_font),
      sync,
      footer_font);
}

}  // namespace

std::vector<uint8_t> render_settings_bitmap(const app::AppState& state) {
  const int rot = normalize_rotation_deg(state.settings.rotation_deg);
  const bool swapped = rot == 90 || rot == 270;
  const int source_w = swapped ? platform::kPanelHeight : platform::kPanelWidth;
  const int source_h = swapped ? platform::kPanelWidth : platform::kPanelHeight;

  RotatedCanvas canvas = make_rotated_canvas(source_w, source_h, rot);
  render_settings_source(canvas, state);
  return canvas.image;
}

}  // namespace fridge_ink::ui
