#include "ui/screens/settings_screen.hpp"

#include "platform/panel_config.hpp"
#include "ui/draw.hpp"
#include "ui/panel_font_assets_generated.hpp"
#include "ui/strings.hpp"

#include <algorithm>
#include <array>
#include <cstdint>
#include <string>
#include <vector>

namespace fridge_ink::ui {
namespace {

using platform::panel_font_assets::BitmapFont;
using platform::panel_font_assets::Glyph;

// ── Minimal BitmapFont helpers (same pattern as weather_screen_portrait.cpp) ──

std::size_t ssp_gi(const char ch) {
  const unsigned char c = static_cast<unsigned char>(ch);
  if (c < 32 || c > 126) return static_cast<std::size_t>('?' - 32);
  return static_cast<std::size_t>(c - 32);
}

void ssp_glyph(std::vector<uint8_t>& img, const int x, const int y,
               const char ch, const BitmapFont& f) {
  const Glyph& g = f.glyphs[ssp_gi(ch)];
  if (!g.width || !g.height) return;
  const int rb = (g.width + 7) / 8;
  const std::uint8_t* bm = f.bitmap + g.bitmap_offset;
  for (int r = 0; r < g.height; ++r)
    for (int c = 0; c < g.width; ++c)
      if ((bm[r * rb + c / 8] & (0x80U >> (c % 8))) != 0)
        set_black_pixel(img, x + g.left + c, y + static_cast<int>(g.top) + r);
}

int ssp_adv(const char ch, const BitmapFont& f) {
  return f.glyphs[ssp_gi(ch)].advance;
}

int ssp_tw(const std::string& s, const BitmapFont& f) {
  int w = 0;
  for (const char c : s) w += ssp_adv(c, f);
  return w;
}

struct SspVB { int top{0}; int bot{0}; bool ok{false}; };

SspVB ssp_vb(const std::string& s, const BitmapFont& f) {
  SspVB b{};
  for (const char c : s) {
    const Glyph& g = f.glyphs[ssp_gi(c)];
    if (!g.width || !g.height) continue;
    if (!b.ok) {
      b.top = static_cast<int>(g.top);
      b.bot = static_cast<int>(g.top) + g.height;
      b.ok  = true;
    } else {
      b.top = std::min(b.top, static_cast<int>(g.top));
      b.bot = std::max(b.bot, static_cast<int>(g.top) + g.height);
    }
  }
  return b;
}

void ssp_text(std::vector<uint8_t>& img, int x, const int y,
              const std::string& s, const BitmapFont& f) {
  for (const char c : s) {
    ssp_glyph(img, x, y, c, f);
    x += ssp_adv(c, f);
  }
}

// Returns draw-y so the visual top of the text lands at visual_top.
int ssp_ytop(const int visual_top, const std::string& s, const BitmapFont& f) {
  const SspVB b = ssp_vb(s, f);
  return b.ok ? visual_top - b.top : visual_top;
}

// Returns draw-y that vertically centres text in [zone_y, zone_y+zone_h).
int ssp_ycenter(const int zone_y, const int zone_h,
                const std::string& s, const BitmapFont& f) {
  const SspVB b = ssp_vb(s, f);
  if (!b.ok) return zone_y + (zone_h - static_cast<int>(f.line_height)) / 2;
  return zone_y + (zone_h - (b.bot - b.top)) / 2 - b.top;
}

// Draw text centred horizontally in [x0, x1].
void ssp_text_centered(std::vector<uint8_t>& img,
                       const int x0, const int x1, const int y,
                       const std::string& s, const BitmapFont& f) {
  const int w = ssp_tw(s, f);
  ssp_text(img, x0 + (x1 - x0 - w) / 2, y, s, f);
}

std::string ssp_trunc(const std::string& s, const BitmapFont& f, const int max_px) {
  if (max_px <= 0) return {};
  int w = 0;
  std::string out;
  for (const char c : s) {
    const int a = ssp_adv(c, f);
    if (w + a > max_px) {
      const std::string el = "...";
      const int ew = ssp_tw(el, f);
      while (!out.empty() && ssp_tw(out, f) + ew > max_px) out.pop_back();
      return out + el;
    }
    w += a;
    out += c;
  }
  return out;
}

// ── Settings data ─────────────────────────────────────────────────────────────

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

std::string upper_copy(const std::string& text) {
  std::string o = text;
  for (char& c : o)
    if (c >= 'a' && c <= 'z') c = static_cast<char>(c - 32);
  return o;
}

std::string bool_text(const bool v, const UiStrings& s) { return v ? s.on : s.off; }

std::string font_size_text(const std::string& raw, const UiStrings& s) {
  if (raw == "small") return s.settings_small;
  if (raw == "large") return s.settings_large;
  return s.settings_medium;
}

std::string partial_refresh_text(const std::string& raw, const UiStrings& s) {
  if (raw == "slow") return s.settings_slow;
  if (raw == "fast") return s.settings_fast;
  return s.settings_balanced;
}

int normalize_rotation_deg(const int raw) {
  const int n = ((raw % 360) + 360) % 360;
  if (n >= 315 || n < 45)  return 0;
  if (n < 135)             return 90;
  if (n < 225)             return 180;
  return 270;
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

std::string setting_value(const app::AppState& state, const SettingsItem item,
                          const UiStrings& s) {
  switch (item) {
    case SettingsItem::FontSize:
      return font_size_text(
          state.settings.font_size.empty() ? "medium" : state.settings.font_size, s);
    case SettingsItem::PartialRefresh:
      return partial_refresh_text(
          state.settings.partial_refresh_mode.empty() ? "balanced"
                                                      : state.settings.partial_refresh_mode, s);
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
    case SettingsItem::AutoSync:     return bool_text(state.settings.auto_sync_enabled, s);
    case SettingsItem::SyncNow:      return s.settings_press_enter;
    case SettingsItem::ChangeWifi:
      return state.onboarding.wifi_ssid.empty() ? s.settings_not_set
                                                : state.onboarding.wifi_ssid;
    case SettingsItem::ResetAndWipe: return s.settings_press_enter;
  }
  return {};
}

std::string sync_footer_status(const app::AppState& state, const UiStrings& s) {
  if (state.settings.sync_state == "ok")      return s.settings_sync_ok;
  if (state.settings.sync_state == "pending") return s.settings_sync_in_progress;
  if (state.settings.sync_state == "fail")    return s.settings_sync_fail;
  return s.settings_sync_never;
}

}  // namespace

std::vector<uint8_t> render_settings_portrait_bitmap(const app::AppState& state) {
  using namespace platform::panel_font_assets;
  using platform::kPanelBufferSize;
  using platform::kPanelHeight;
  using platform::kPanelWidth;

  const auto& s = get_ui_strings(state.device_language);
  std::vector<uint8_t> image(kPanelBufferSize, 0xFF);

  // Card geometry (same as all other portrait screens)
  const int card_x0 = 108;
  const int card_x1 = kPanelWidth - 108;   // 692
  const int card_y0 = 14;
  const int card_y1 = kPanelHeight - 14;   // 466
  draw_rounded_rect_stroke(image, card_x0, card_y0, card_x1, card_y1, 16, 2);

  // Font assignments – same tiers as landscape.
  const BitmapFont& title_font       = kFontInterBold29;
  const BitmapFont& hint_font        = kFontJetBold13;
  const BitmapFont& group_font       = kFontJetBold13;
  const BitmapFont& label_font       = kFontInterMedium18;
  const BitmapFont& label_focus_font = kFontInterBold20;
  const BitmapFont& value_font       = kFontJetExtraBold16;
  const BitmapFont& footer_font      = kFontJetBold13;

  const int left  = card_x0 + 20;
  const int right = card_x1 - 20;

  // ── Title (centred) ────────────────────────────────────────────────────────
  ssp_text_centered(image, card_x0, card_x1,
                    ssp_ytop(card_y0 + 16, s.settings_title, title_font),
                    s.settings_title, title_font);

  // ── Hint (centred, below title) ────────────────────────────────────────────
  {
    const std::string raw  = s.settings_hint_portrait;
    const std::string hint = ssp_trunc(raw, hint_font, card_x1 - card_x0 - 24);
    ssp_text_centered(image, card_x0, card_x1,
                      ssp_ytop(card_y0 + 50, hint, hint_font),
                      hint, hint_font);
  }

  // ── Divider ────────────────────────────────────────────────────────────────
  fill_black_rect(image, card_x0 + 16, card_y0 + 68, card_x1 - 16, card_y0 + 70);

  // ── Layout parameters ──────────────────────────────────────────────────────
  const int footer_h       = 28;
  const int footer_top     = card_y1 - footer_h;
  const int content_top    = card_y0 + 82;
  const int content_bottom = footer_top - 6;

  int row_h   = 30;
  int row_gap = 1;
  int group_h = 16;
  int group_gap = 5;
  const int min_row_h   = 22;
  const int min_group_h = 12;

  auto content_h = [&]() -> int {
    return group_h + (6 * row_h) + (5 * row_gap) + group_gap +
           group_h + (3 * row_h) + (2 * row_gap) +
           row_h;
  };
  const int avail = content_bottom - content_top;
  for (int iter = 0; iter < 120; ++iter) {
    if (content_h() <= avail) break;
    if (row_h    > min_row_h)   { --row_h;    continue; }
    if (group_gap > 2)          { --group_gap; continue; }
    if (group_h  > min_group_h) { --group_h;   continue; }
    if (row_gap  > 0)           { --row_gap;   continue; }
    break;
  }

  const int focused = std::max(
      0, std::min(state.settings.focused_index,
                  static_cast<int>(kSettingsOrder.size()) - 1));

  // ── Row renderer ───────────────────────────────────────────────────────────
  int y = content_top;

  auto draw_group = [&](const char* name, const int first, const int count) {
    if (name != nullptr && name[0] != '\0') {
      ssp_text(image, left + 2,
               ssp_ycenter(y, group_h, name, group_font),
               name, group_font);
      y += group_h;
    }

    for (int i = 0; i < count; ++i) {
      const int idx        = first + i;
      const SettingsItem item = kSettingsOrder[static_cast<std::size_t>(idx)];
      const bool is_focus  = (idx == focused);
      const BitmapFont& rf = is_focus ? label_focus_font : label_font;
      const int y0 = y;

      // Value (right side)
      const std::string val = ssp_trunc(
          setting_value(state, item, s), value_font,
          std::max(84, ((right - left) * 47) / 100));
      const int val_w = ssp_tw(val, value_font);
      const int val_x = right - 8 - val_w;

      // Marker + label (left side)
      const std::string marker = is_focus ? ">" : " ";
      const int mk_w  = ssp_tw(marker, value_font);
      const int mk_x  = left + 2;
      const int lbl_x = mk_x + mk_w + 6;
      const int lbl_max = std::max(86, val_x - lbl_x - 8);
      const std::string lbl = ssp_trunc(setting_label(item, s), rf, lbl_max);

      ssp_text(image, mk_x,  ssp_ycenter(y0, row_h, marker, value_font), marker, value_font);
      ssp_text(image, lbl_x, ssp_ycenter(y0, row_h, lbl,    rf),         lbl,    rf);
      ssp_text(image, val_x, ssp_ycenter(y0, row_h, val,    value_font), val,    value_font);

      if (is_focus)
        fill_black_rect(image, lbl_x, y0 + row_h - 3, right - 8, y0 + row_h - 2);

      y += row_h + row_gap;
    }
    y += group_gap;
  };

  draw_group(s.settings_group_display, 0, 6);
  draw_group(s.settings_group_sync,    6, 3);
  y = std::max(content_top, y - group_gap);
  draw_group("",                     9, 1);

  // ── Footer ─────────────────────────────────────────────────────────────────
  fill_black_rect(image, left, footer_top - 1, right, footer_top);

  const std::string notice = ssp_trunc(
      upper_copy(state.settings.notice), footer_font,
      std::max(40, right - left - 130));
  if (!notice.empty())
    ssp_text(image, left,
             ssp_ycenter(footer_top, footer_h, notice, footer_font),
             notice, footer_font);

  const std::string sync  = ssp_trunc(sync_footer_status(state, s), footer_font, 124);
  const int sync_w        = ssp_tw(sync, footer_font);
  ssp_text(image, std::max(left, right - sync_w),
           ssp_ycenter(footer_top, footer_h, sync, footer_font),
           sync, footer_font);

  return image;
}

}  // namespace fridge_ink::ui
