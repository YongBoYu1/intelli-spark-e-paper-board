#include "ui/screens/settings_screen.hpp"

#include "platform/panel_config.hpp"
#include "ui/draw.hpp"
#include "ui/panel_font_assets_generated.hpp"

#include <algorithm>
#include <array>
#include <cstdint>
#include <string>
#include <vector>

namespace fridge_ink::ui {
namespace {

using platform::panel_font_assets::BitmapFont;
using platform::panel_font_assets::Glyph;

// ── Minimal BitmapFont helpers (same pattern as weather_screen_landscape.cpp) ─

std::size_t ssl_gi(const char ch) {
  const unsigned char c = static_cast<unsigned char>(ch);
  if (c < 32 || c > 126) return static_cast<std::size_t>('?' - 32);
  return static_cast<std::size_t>(c - 32);
}

void ssl_glyph(std::vector<uint8_t>& img, const int x, const int y,
               const char ch, const BitmapFont& f) {
  const Glyph& g = f.glyphs[ssl_gi(ch)];
  if (!g.width || !g.height) return;
  const int rb = (g.width + 7) / 8;
  const std::uint8_t* bm = f.bitmap + g.bitmap_offset;
  for (int r = 0; r < g.height; ++r)
    for (int c = 0; c < g.width; ++c)
      if ((bm[r * rb + c / 8] & (0x80U >> (c % 8))) != 0)
        set_black_pixel(img, x + g.left + c, y + static_cast<int>(g.top) + r);
}

int ssl_adv(const char ch, const BitmapFont& f) {
  return f.glyphs[ssl_gi(ch)].advance;
}

int ssl_tw(const std::string& s, const BitmapFont& f) {
  int w = 0;
  for (const char c : s) w += ssl_adv(c, f);
  return w;
}

struct SslVB { int top{0}; int bot{0}; bool ok{false}; };

SslVB ssl_vb(const std::string& s, const BitmapFont& f) {
  SslVB b{};
  for (const char c : s) {
    const Glyph& g = f.glyphs[ssl_gi(c)];
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

void ssl_text(std::vector<uint8_t>& img, int x, const int y,
              const std::string& s, const BitmapFont& f) {
  for (const char c : s) {
    ssl_glyph(img, x, y, c, f);
    x += ssl_adv(c, f);
  }
}

// Returns draw-y so the visual top of the text lands at visual_top.
int ssl_ytop(const int visual_top, const std::string& s, const BitmapFont& f) {
  const SslVB b = ssl_vb(s, f);
  return b.ok ? visual_top - b.top : visual_top;
}

// Returns draw-y that vertically centres text in [zone_y, zone_y+zone_h).
int ssl_ycenter(const int zone_y, const int zone_h,
                const std::string& s, const BitmapFont& f) {
  const SslVB b = ssl_vb(s, f);
  if (!b.ok) return zone_y + (zone_h - static_cast<int>(f.line_height)) / 2;
  return zone_y + (zone_h - (b.bot - b.top)) / 2 - b.top;
}

std::string ssl_trunc(const std::string& s, const BitmapFont& f, const int max_px) {
  if (max_px <= 0) return {};
  int w = 0;
  std::string out;
  for (const char c : s) {
    const int a = ssl_adv(c, f);
    if (w + a > max_px) {
      const std::string el = "...";
      const int ew = ssl_tw(el, f);
      while (!out.empty() && ssl_tw(out, f) + ew > max_px) out.pop_back();
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
  Connectivity = 4,
  AutoSync = 5,
  SyncNow = 6,
  ChangeWifi = 7,
  ResetAndWipe = 8,
};

constexpr std::array<SettingsItem, 9> kSettingsOrder = {
    SettingsItem::FontSize,
    SettingsItem::PartialRefresh,
    SettingsItem::FullRefresh,
    SettingsItem::Rotation,
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

std::string bool_text(const bool v) { return v ? "ON" : "OFF"; }

int normalize_rotation_deg(const int raw) {
  const int n = ((raw % 360) + 360) % 360;
  if (n >= 315 || n < 45)  return 0;
  if (n < 135)             return 90;
  if (n < 225)             return 180;
  return 270;
}

std::string setting_label(const SettingsItem item) {
  switch (item) {
    case SettingsItem::FontSize:       return "FONT SIZE";
    case SettingsItem::PartialRefresh: return "PARTIAL REFRESH";
    case SettingsItem::FullRefresh:    return "FULL REFRESH";
    case SettingsItem::Rotation:       return "ROTATION";
    case SettingsItem::Connectivity:   return "WIFI + BT";
    case SettingsItem::AutoSync:       return "AUTO SYNC";
    case SettingsItem::SyncNow:        return "SYNC NOW";
    case SettingsItem::ChangeWifi:     return "CHANGE WI-FI";
    case SettingsItem::ResetAndWipe:   return "RESET / WEB DATA";
  }
  return {};
}

std::string setting_value(const app::AppState& state, const SettingsItem item) {
  switch (item) {
    case SettingsItem::FontSize:
      return upper_copy(state.settings.font_size.empty() ? "medium"
                                                         : state.settings.font_size);
    case SettingsItem::PartialRefresh:
      return upper_copy(state.settings.partial_refresh_mode.empty()
                            ? "balanced"
                            : state.settings.partial_refresh_mode);
    case SettingsItem::FullRefresh:
      return "EVERY " + std::to_string(std::max(1, state.settings.full_refresh_every)) +
             " PARTIALS";
    case SettingsItem::Rotation:
      return std::to_string(normalize_rotation_deg(state.settings.rotation_deg));
    case SettingsItem::Connectivity:
      return "WIFI " + bool_text(state.settings.wifi_enabled) +
             " / BT " + bool_text(state.settings.bluetooth_enabled);
    case SettingsItem::AutoSync:     return bool_text(state.settings.auto_sync_enabled);
    case SettingsItem::SyncNow:      return "PRESS ENTER";
    case SettingsItem::ChangeWifi:
      return state.onboarding.wifi_ssid.empty() ? "NOT SET" : state.onboarding.wifi_ssid;
    case SettingsItem::ResetAndWipe: return "PLACEHOLDER";
  }
  return {};
}

std::string sync_footer_status(const app::AppState& state) {
  if (state.settings.sync_state == "ok")      return "LAST SYNC OK";
  if (state.settings.sync_state == "pending") return "SYNC IN PROGRESS";
  if (state.settings.sync_state == "fail")    return "LAST SYNC FAIL";
  return "LAST SYNC NEVER";
}

}  // namespace

std::vector<uint8_t> render_settings_landscape_bitmap(const app::AppState& state) {
  using namespace platform::panel_font_assets;
  using platform::kPanelBufferSize;
  using platform::kPanelHeight;
  using platform::kPanelWidth;

  std::vector<uint8_t> image(kPanelBufferSize, 0xFF);

  // Font assignments matching Python settings.py:
  //   title_font  → inter_bold  ~29px
  //   hint_font   → jet_bold    13px  (meta)
  //   group_font  → jet_bold    12px  (meta-1, closest = 13px)
  //   label_font  → inter_medium 21px (closest = 18px)
  //   label_focus → inter_bold  21px  (closest = 20px)
  //   value_font  → jet_bold    18px  (closest jet extrabold = 16px)
  const BitmapFont& title_font       = kFontInterBold29;
  const BitmapFont& hint_font        = kFontJetBold13;
  const BitmapFont& group_font       = kFontJetBold13;
  const BitmapFont& label_font       = kFontInterMedium18;
  const BitmapFont& label_focus_font = kFontInterBold20;
  const BitmapFont& value_font       = kFontJetExtraBold16;
  const BitmapFont& footer_font      = kFontJetBold13;

  const int left  = 24;
  const int right = kPanelWidth - 24;

  // ── Title ──────────────────────────────────────────────────────────────────
  ssl_text(image, left, ssl_ytop(16, "SETTINGS", title_font), "SETTINGS", title_font);

  // ── Hint (right-aligned, y=52) ─────────────────────────────────────────────
  {
    const std::string raw = "ROTATE TO SELECT  -  CLICK TO ENTER  -  HOLD TO HOME";
    const std::string hint = ssl_trunc(raw, hint_font, std::max(80, right - left));
    const int hint_w = ssl_tw(hint, hint_font);
    const int hint_x = std::max(left, right - hint_w);
    ssl_text(image, hint_x, ssl_ytop(52, hint, hint_font), hint, hint_font);
  }

  // ── Divider ────────────────────────────────────────────────────────────────
  fill_black_rect(image, left, 68, right, 70);

  // ── Layout parameters ──────────────────────────────────────────────────────
  const int footer_h      = 30;
  const int footer_top    = kPanelHeight - footer_h;
  const int content_top   = 90;
  const int content_bottom = footer_top - 6;

  int row_h   = 34;
  int row_gap = 1;
  int group_h = 20;
  int group_gap = 7;
  const int min_row_h   = 26;
  const int min_group_h = 14;

  // Matches Python's dynamic shrink loop.
  // Groups: DISPLAY(5) + SYNC(3: AutoSync,SyncNow,ChangeWifi) + OTHER(1)
  auto content_h = [&]() -> int {
    return group_h + (5 * row_h) + (4 * row_gap) + group_gap +
           group_h + (3 * row_h) + (2 * row_gap) + group_gap +
           group_h + row_h;
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
    ssl_text(image, left + 2,
             ssl_ycenter(y, group_h, name, group_font),
             name, group_font);
    y += group_h;

    for (int i = 0; i < count; ++i) {
      const int idx = first + i;
      const SettingsItem item  = kSettingsOrder[static_cast<std::size_t>(idx)];
      const bool is_focus      = (idx == focused);
      const BitmapFont& rf     = is_focus ? label_focus_font : label_font;
      const int y0 = y;

      // Value (right side)
      const std::string val = ssl_trunc(
          setting_value(state, item), value_font,
          std::max(120, ((right - left) * 50) / 100));
      const int val_w = ssl_tw(val, value_font);
      const int val_x = right - 12 - val_w;

      // Marker + label (left side)
      const std::string marker = is_focus ? ">" : " ";
      const int mk_w  = ssl_tw(marker, value_font);
      const int mk_x  = left + 2;
      const int lbl_x = mk_x + mk_w + 8;
      const int lbl_max = std::max(100, val_x - lbl_x - 12);
      const std::string lbl = ssl_trunc(setting_label(item), rf, lbl_max);

      ssl_text(image, mk_x,  ssl_ycenter(y0, row_h, marker, value_font), marker, value_font);
      ssl_text(image, lbl_x, ssl_ycenter(y0, row_h, lbl,    rf),         lbl,    rf);
      ssl_text(image, val_x, ssl_ycenter(y0, row_h, val,    value_font), val,    value_font);

      if (is_focus)
        fill_black_rect(image, lbl_x, y0 + row_h - 3, right - 12, y0 + row_h - 2);

      y += row_h + row_gap;
    }
    y += group_gap;
  };

  draw_group("DISPLAY", 0, 5);
  draw_group("SYNC",    5, 3);  // AutoSync, SyncNow, ChangeWifi
  draw_group("OTHER",   8, 1);  // ResetAndWipe

  // ── Footer ─────────────────────────────────────────────────────────────────
  fill_black_rect(image, left, footer_top - 1, right, footer_top);

  const std::string notice = ssl_trunc(
      upper_copy(state.settings.notice), footer_font,
      std::max(40, right - left - 220));
  if (!notice.empty())
    ssl_text(image, left,
             ssl_ycenter(footer_top, footer_h, notice, footer_font),
             notice, footer_font);

  const std::string sync  = ssl_trunc(sync_footer_status(state), footer_font, 210);
  const int sync_w        = ssl_tw(sync, footer_font);
  ssl_text(image, std::max(left, right - sync_w),
           ssl_ycenter(footer_top, footer_h, sync, footer_font),
           sync, footer_font);

  return image;
}

}  // namespace fridge_ink::ui
