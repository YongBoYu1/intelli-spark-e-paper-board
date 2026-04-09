#include "ui/screens/home_screen.hpp"

#include "platform/clock.hpp"
#include "platform/panel_config.hpp"
#include "ui/draw.hpp"
#include "ui/panel_font_assets_generated.hpp"
#include "ui/primitives.hpp"

#include <algorithm>
#include <cmath>
#include <ctime>
#include <iomanip>
#include <sstream>
#include <string>
#include <vector>

namespace fridge_ink::ui {
namespace {

using platform::panel_font_assets::BitmapFont;
using platform::panel_font_assets::Glyph;
using platform::kPanelWidthBytes;

// ── Portrait canvas ──────────────────────────────────────────────────────────
// The portrait canvas is 480 px wide × 800 px tall, matching the Python
// render target before its quarter-turn rotation into the 800×480 buffer.
//
// rotation=90  (90° CCW, PIL rotate(90)):
//   canvas (cx, cy) → buffer (cy,       479 - cx)
// rotation=270 (90° CW,  PIL rotate(270)):
//   canvas (cx, cy) → buffer (799 - cy, cx      )

constexpr int kPW = 480;  // portrait canvas width
constexpr int kPH = 800;  // portrait canvas height

// ── Low-level portrait pixel ops ─────────────────────────────────────────────

inline void hp_px(std::vector<uint8_t>& img, int cx, int cy, bool r90) {
  if (cx < 0 || cx >= kPW || cy < 0 || cy >= kPH) return;
  if (r90) set_black_pixel(img, cy,       479 - cx);
  else     set_black_pixel(img, 799 - cy, cx);
}

inline void hp_clr(std::vector<uint8_t>& img, int cx, int cy, bool r90) {
  if (cx < 0 || cx >= kPW || cy < 0 || cy >= kPH) return;
  if (r90) clear_pixel(img, cy,       479 - cx);
  else     clear_pixel(img, 799 - cy, cx);
}

void hp_fill(std::vector<uint8_t>& img,
             int cx0, int cy0, int cx1, int cy1, bool r90) {
  for (int cy = cy0; cy < cy1; ++cy)
    for (int cx = cx0; cx < cx1; ++cx)
      hp_px(img, cx, cy, r90);
}

void hp_clear_rect(std::vector<uint8_t>& img,
                   int cx0, int cy0, int cx1, int cy1, bool r90) {
  for (int cy = cy0; cy < cy1; ++cy)
    for (int cx = cx0; cx < cx1; ++cx)
      hp_clr(img, cx, cy, r90);
}

// ── BitmapFont helpers ───────────────────────────────────────────────────────

std::size_t hp_gi(const char ch) {
  const unsigned char c = static_cast<unsigned char>(ch);
  if (c < 32 || c > 126) return static_cast<std::size_t>('?' - 32);
  return static_cast<std::size_t>(c - 32);
}

int hp_adv(const char ch, const BitmapFont& f) {
  return f.glyphs[hp_gi(ch)].advance;
}

int hp_tw(const std::string& s, const BitmapFont& f) {
  int w = 0;
  for (const char c : s) w += hp_adv(c, f);
  return w;
}

int hp_tw_spaced(const std::string& s, const BitmapFont& f, const int spacing) {
  if (spacing <= 0 || s.size() <= 1) {
    return hp_tw(s, f);
  }
  int w = 0;
  for (std::size_t i = 0; i < s.size(); ++i) {
    w += hp_adv(s[i], f);
    if (i + 1 < s.size()) {
      w += spacing;
    }
  }
  return w;
}

struct HpVB { int top{0}; int bot{0}; bool ok{false}; };

HpVB hp_vb(const std::string& s, const BitmapFont& f) {
  HpVB b{};
  for (const char c : s) {
    const Glyph& g = f.glyphs[hp_gi(c)];
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

int hp_vis_h(const std::string& s, const BitmapFont& f) {
  const HpVB b = hp_vb(s, f);
  return b.ok ? b.bot - b.top : static_cast<int>(f.line_height);
}

void hp_glyph(std::vector<uint8_t>& img, int cx, int cy,
              char ch, const BitmapFont& f, bool r90) {
  const Glyph& g = f.glyphs[hp_gi(ch)];
  if (!g.width || !g.height) return;
  const int rb = (g.width + 7) / 8;
  const std::uint8_t* bm = f.bitmap + g.bitmap_offset;
  for (int row = 0; row < g.height; ++row)
    for (int col = 0; col < g.width; ++col)
      if ((bm[row * rb + col / 8] & (0x80U >> (col % 8))) != 0)
        hp_px(img, cx + g.left + col, cy + static_cast<int>(g.top) + row, r90);
}

void hp_text(std::vector<uint8_t>& img, int cx, int cy,
             const std::string& s, const BitmapFont& f, bool r90) {
  for (const char c : s) {
    hp_glyph(img, cx, cy, c, f, r90);
    cx += hp_adv(c, f);
  }
}

void hp_text_spaced(
    std::vector<uint8_t>& img,
    int cx,
    int cy,
    const std::string& s,
    const BitmapFont& f,
    const bool r90,
    const int spacing) {
  if (spacing <= 0) {
    hp_text(img, cx, cy, s, f, r90);
    return;
  }
  for (std::size_t i = 0; i < s.size(); ++i) {
    const char c = s[i];
    hp_glyph(img, cx, cy, c, f, r90);
    cx += hp_adv(c, f);
    if (i + 1 < s.size()) {
      cx += spacing;
    }
  }
}

// draw-y so visual top of text lands at vis_top
int hp_ytop(int vis_top, const std::string& s, const BitmapFont& f) {
  const HpVB b = hp_vb(s, f);
  return b.ok ? vis_top - b.top : vis_top;
}

std::string hp_upper(const std::string& s) {
  std::string o = s;
  for (char& c : o)
    if (c >= 'a' && c <= 'z') c = static_cast<char>(c - 32);
  return o;
}

std::string hp_trim(const std::string& s) {
  std::size_t begin = 0;
  while (begin < s.size() && static_cast<unsigned char>(s[begin]) <= ' ') {
    ++begin;
  }
  std::size_t end = s.size();
  while (end > begin && static_cast<unsigned char>(s[end - 1]) <= ' ') {
    --end;
  }
  return s.substr(begin, end - begin);
}

int hp_normalized_memo_index(const app::AppState& state) {
  const int total = static_cast<int>(state.dashboard.memos.size());
  if (total <= 0) {
    return 0;
  }
  int index = state.memo.index % total;
  if (index < 0) {
    index += total;
  }
  return index;
}

std::vector<std::string> hp_family_author_tags(const app::AppState& state) {
  std::vector<std::string> tags{};
  tags.reserve(4);

  const auto& memos = state.dashboard.memos;
  const int selected = hp_normalized_memo_index(state);
  std::string active_author{};
  if (!memos.empty() && selected >= 0 && selected < static_cast<int>(memos.size())) {
    active_author = hp_upper(hp_trim(memos[static_cast<std::size_t>(selected)].author));
  } else {
    active_author = hp_upper(hp_trim(state.dashboard.family_memo_author));
  }
  if (!active_author.empty()) {
    tags.push_back(active_author);
  }

  for (const auto& memo : memos) {
    const std::string author = hp_upper(hp_trim(memo.author));
    if (author.empty()) {
      continue;
    }
    if (std::find(tags.begin(), tags.end(), author) != tags.end()) {
      continue;
    }
    tags.push_back(author);
    if (static_cast<int>(tags.size()) >= 4) {
      break;
    }
  }

  return tags;
}

std::string hp_family_memo_text(const app::AppState& state) {
  const auto& memos = state.dashboard.memos;
  const int selected = hp_normalized_memo_index(state);
  if (!memos.empty() && selected >= 0 && selected < static_cast<int>(memos.size())) {
    const std::string text = hp_trim(memos[static_cast<std::size_t>(selected)].text);
    if (!text.empty()) {
      return text;
    }
  }
  return hp_trim(state.dashboard.family_memo_text);
}

std::string hp_trunc(const std::string& s, const BitmapFont& f, int max_px) {
  if (max_px <= 0) return {};
  int w = 0;
  std::string out;
  for (const char c : s) {
    const int a = hp_adv(c, f);
    if (w + a > max_px) {
      const std::string el = "...";
      const int ew = hp_tw(el, f);
      while (!out.empty() && hp_tw(out, f) + ew > max_px) out.pop_back();
      return out + el;
    }
    w += a;
    out += c;
  }
  return out;
}

// Word-wrap text into portrait zone; returns portrait_y after last line.
int hp_wrapped(std::vector<uint8_t>& img,
               int cx, int cy0, int max_w, int max_h,
               const std::string& text, const BitmapFont& f,
               bool r90, int gap = 4) {
  const int lh = hp_vis_h("Ag", f) + gap;
  std::string cur;
  int cy = cy0;
  auto flush = [&]() {
    if (cur.empty()) return;
    if (cy + lh <= cy0 + max_h) {
      hp_text(img, cx, hp_ytop(cy, cur, f), cur, f, r90);
      cy += lh;
    }
    cur.clear();
  };
  std::istringstream iss(text);
  std::string word;
  while (iss >> word) {
    const std::string cand = cur.empty() ? word : cur + " " + word;
    if (hp_tw(cand, f) <= max_w) {
      cur = cand;
    } else {
      flush();
      cur = hp_trunc(word, f, max_w);
    }
  }
  flush();
  return cy;
}

// ── Degree-mark circle in portrait coords ────────────────────────────────────
void hp_degree(std::vector<uint8_t>& img, int cx, int cy, int sz, bool r90) {
  const int r = std::max(1, sz / 2);
  for (int dy = -r; dy <= r; ++dy)
    for (int dx = -r; dx <= r; ++dx) {
      const int d2 = dx * dx + dy * dy;
      const int ri = r - 1;
      if (d2 >= ri * ri && d2 <= r * r + r)
        hp_px(img, cx + r + dx, cy + r + dy, r90);
    }
}

// ── Weather icon in portrait coords ──────────────────────────────────────────
void hp_icon(std::vector<uint8_t>& img, int cx, int cy,
             const std::string& cond, int sz, bool r90) {
  // Render icon into a scratch landscape buffer at origin, then copy each
  // black pixel into the final buffer through the portrait transform.
  std::vector<uint8_t> tmp(platform::kPanelBufferSize, 0xFF);
  draw_icon(tmp, 0, 0, cond, sz);
  for (int iy = 0; iy < sz; ++iy)
    for (int ix = 0; ix < sz; ++ix) {
      const int off = (iy * kPanelWidthBytes) + (ix / 8);
      if ((tmp[off] & (0x80U >> (ix % 8))) == 0)
        hp_px(img, cx + ix, cy + iy, r90);
    }
}

// ── Section-rule header ───────────────────────────────────────────────────────
// Horizontal rule at portrait_y=cy; title left-aligned, count right-aligned,
// both floating on the rule with the rule erased behind the text.
void hp_section_rule(std::vector<uint8_t>& img,
                     int x0, int x1, int cy,
                     const std::string& title, const std::string& count,
                     const BitmapFont& tf, bool r90) {
  hp_fill(img, x0, cy, x1, cy + 2, r90);

  const int vis_h   = hp_vis_h(title.empty() ? "A" : title, tf);
  const int txt_top = cy - vis_h / 2 - 1;
  const int title_w = hp_tw(title, tf);
  const int count_w = hp_tw(count, tf);
  const int count_x = x1 - count_w;

  // Erase rule behind text
  hp_clear_rect(img, x0 - 4,     cy, x0 + title_w + 4, cy + 2, r90);
  hp_clear_rect(img, count_x - 4, cy, x1 + 4,           cy + 2, r90);

  hp_text(img, x0,     hp_ytop(txt_top, title, tf), title, tf, r90);
  hp_text(img, count_x, hp_ytop(txt_top, count, tf), count, tf, r90);
}

// ── Clock data ───────────────────────────────────────────────────────────────
struct HpClock {
  bool        valid{false};
  std::string time_str;
  std::string weekday_str;
  std::string date_str;
};

HpClock resolve_clock(std::uint64_t mb, const std::string& tz) {
  HpClock out;
  if (mb == 0) return out;
  platform::apply_timezone(tz);
  const std::time_t now = static_cast<std::time_t>(mb * 60ULL);
  std::tm tm{};
#if defined(_WIN32)
  localtime_s(&tm, &now);
#else
  localtime_r(&now, &tm);
#endif
  std::ostringstream os;
  os << std::put_time(&tm, "%H:%M");
  out.time_str = os.str();
  os.str({});
  os << std::put_time(&tm, "%A");
  out.weekday_str = hp_upper(os.str());
  os.str({});
  os << std::put_time(&tm, "%B");
  out.date_str = os.str() + " " + std::to_string(tm.tm_mday)
               + ", " + std::to_string(1900 + tm.tm_year);
  out.valid = true;
  return out;
}

// "open/total"  (open = not completed)
std::string hp_progress(int total, int completed) {
  const int open = std::max(0, total - completed);
  return std::to_string(open) + "/" + std::to_string(std::max(0, total));
}

std::string hp_compact_badge(const std::string& raw) {
  std::string s = hp_upper(raw);
  struct { const char* from; const char* to; } subs[] = {
    {"EXPIRES", "EXP"}, {"EXPIRY",  "EXP"}, {"YESTERDAY","YDAY"},
    {"TODAY",   "TDY"}, {"TONIGHT", "TNITE"},
    {"DAYS",    "D"},   {"DAY",     "D"},
  };
  for (const auto& sub : subs) {
    const std::string f = sub.from;
    const std::string t = sub.to;
    std::size_t pos = 0;
    while ((pos = s.find(f, pos)) != std::string::npos) {
      s.replace(pos, f.size(), t);
      pos += t.size();
    }
  }
  return s;
}

enum class HomeFontSizeMode {
  Small,
  Medium,
  Large,
};

struct HomePortraitTypography {
  const BitmapFont* time_font_lg{nullptr};
  const BitmapFont* time_font_sm{nullptr};
  const BitmapFont* weekday_font{nullptr};
  const BitmapFont* date_font{nullptr};
  const BitmapFont* temp_font{nullptr};
  const BitmapFont* meta_font{nullptr};
  const BitmapFont* section_font{nullptr};
  const BitmapFont* family_title_font{nullptr};
  const BitmapFont* family_name_font{nullptr};
  const BitmapFont* family_quote_font{nullptr};
  const BitmapFont* item_font{nullptr};
  const BitmapFont* badge_font{nullptr};
  const BitmapFont* menu_item_font{nullptr};
  const BitmapFont* menu_hint_font{nullptr};
};

std::string hp_lower(std::string value) {
  for (char& ch : value) {
    if (ch >= 'A' && ch <= 'Z') {
      ch = static_cast<char>(ch - ('A' - 'a'));
    }
  }
  return value;
}

HomeFontSizeMode home_font_size_mode(const app::AppState& state) {
  const std::string value = hp_lower(state.settings.font_size);
  if (value == "small") {
    return HomeFontSizeMode::Small;
  }
  if (value == "large") {
    return HomeFontSizeMode::Large;
  }
  return HomeFontSizeMode::Medium;
}

HomePortraitTypography home_portrait_typography_for(const app::AppState& state) {
  using namespace platform::panel_font_assets;
  const HomeFontSizeMode mode = home_font_size_mode(state);
  if (mode == HomeFontSizeMode::Small) {
    return {
        &kFontInterBlack87,
        &kFontInterBlack84,
        &kFontJetBold15,
        &kFontInterBold17,
        &kFontInterBlack66,
        &kFontJetBold13,
        &kFontJetBold13,
        &kFontJetBold15,
        &kFontJetBold13,
        &kFontPlayfairBold28,
        &kFontInterMedium13,
        &kFontJetBold13,
        &kFontInterBold17,
        &kFontJetBold13,
    };
  }
  if (mode == HomeFontSizeMode::Large) {
    return {
        &kFontInterBlack109,
        &kFontInterBlack87,
        &kFontJetExtraBold16,
        &kFontInterBold22,
        &kFontInterBlack66,
        &kFontJetBold15,
        &kFontJetBold15,
        &kFontJetExtraBold16,
        &kFontJetBold15,
        &kFontPlayfairBold28,
        &kFontInterBold20,
        &kFontJetBold15,
        &kFontInterBold20,
        &kFontJetBold15,
    };
  }
  return {
      &kFontInterBlack109,
      &kFontInterBlack87,
      &kFontJetExtraBold16,
      &kFontInterBold20,
      &kFontInterBlack66,
      &kFontJetBold13,
      &kFontJetBold13,
      &kFontJetExtraBold16,
      &kFontJetBold15,
      &kFontPlayfairBold28,
      &kFontInterMedium18,
      &kFontJetBold13,
      &kFontInterBold20,
      &kFontJetBold13,
  };
}

int normalize_rotation_deg(const int raw) {
  const int rounded = ((raw % 360) + 360) % 360;
  if (rounded >= 315 || rounded < 45) return 0;
  if (rounded < 135) return 90;
  if (rounded < 225) return 180;
  return 270;
}

bool contains_index(const std::vector<int>& values, const int index) {
  return std::find(values.begin(), values.end(), index) != values.end();
}

int inventory_visible_max(const app::AppState& state) {
  const int deg = normalize_rotation_deg(state.settings.rotation_deg);
  return (deg == 90 || deg == 270) ? 4 : 3;
}

std::vector<int> visible_inventory_indices(const app::AppState& state) {
  std::vector<int> indices{};
  const int total = static_cast<int>(state.dashboard.inventory_items.size());
  const int visible_max = inventory_visible_max(state);
  indices.reserve(std::min(total, visible_max));
  for (int i = 0; i < total; ++i) {
    if (contains_index(state.home.hidden_inventory_indices, i)) {
      continue;
    }
    indices.push_back(i);
    if (static_cast<int>(indices.size()) >= visible_max) {
      break;
    }
  }
  return indices;
}

std::vector<int> visible_reminder_indices(const app::AppState& state) {
  std::vector<int> indices{};
  const int total = static_cast<int>(state.dashboard.reminder_items.size());
  constexpr int kReminderVisibleMax = 4;
  indices.reserve(std::min(total, kReminderVisibleMax));
  for (int i = 0; i < total; ++i) {
    if (contains_index(state.home.hidden_reminder_indices, i)) {
      continue;
    }
    indices.push_back(i);
    if (static_cast<int>(indices.size()) >= kReminderVisibleMax) {
      break;
    }
  }
  return indices;
}

void hp_stroke_rect(
    std::vector<uint8_t>& img,
    const int x0,
    const int y0,
    const int x1,
    const int y1,
    const bool r90,
    const int stroke_w = 1) {
  const int w = std::max(1, stroke_w);
  for (int t = 0; t < w; ++t) {
    for (int x = x0 + t; x < x1 - t; ++x) {
      hp_px(img, x, y0 + t, r90);
      hp_px(img, x, y1 - 1 - t, r90);
    }
    for (int y = y0 + t; y < y1 - t; ++y) {
      hp_px(img, x0 + t, y, r90);
      hp_px(img, x1 - 1 - t, y, r90);
    }
  }
}

void hp_stroke_rounded_rect(
    std::vector<uint8_t>& img,
    const int x0,
    const int y0,
    const int x1,
    const int y1,
    const bool r90,
    const int stroke_w = 1,
    const int radius = 6) {
  if (x1 <= x0 || y1 <= y0) {
    return;
  }
  const int w = std::max(1, stroke_w);
  const int max_radius = std::max(0, std::min((x1 - x0) / 2, (y1 - y0) / 2));
  const int r = std::max(0, std::min(radius, max_radius));
  if (r <= 1) {
    hp_stroke_rect(img, x0, y0, x1, y1, r90, w);
    return;
  }

  hp_stroke_rect(img, x0, y0, x1, y1, r90, w);

  hp_clear_rect(img, x0, y0, x0 + r, y0 + r, r90);
  hp_clear_rect(img, x1 - r, y0, x1, y0 + r, r90);
  hp_clear_rect(img, x0, y1 - r, x0 + r, y1, r90);
  hp_clear_rect(img, x1 - r, y1 - r, x1, y1, r90);

  const int outer = r - 1;
  const int inner = std::max(0, outer - w);
  const int cx0 = x0 + outer;
  const int cy0 = y0 + outer;
  const int cx1 = x1 - 1 - outer;
  const int cy1 = y1 - 1 - outer;
  const int outer2 = outer * outer;
  const int inner2 = inner * inner;
  for (int dy = 0; dy <= outer; ++dy) {
    for (int dx = 0; dx <= outer; ++dx) {
      const int d2 = dx * dx + dy * dy;
      if (d2 > outer2 || d2 < inner2) {
        continue;
      }
      hp_px(img, cx0 - dx, cy0 - dy, r90);  // top-left
      hp_px(img, cx1 + dx, cy0 - dy, r90);  // top-right
      hp_px(img, cx0 - dx, cy1 + dy, r90);  // bottom-left
      hp_px(img, cx1 + dx, cy1 + dy, r90);  // bottom-right
    }
  }
}

void hp_line(
    std::vector<uint8_t>& img,
    int x0,
    int y0,
    int x1,
    int y1,
    const bool r90,
    const int width = 1) {
  const int steps = std::max(std::abs(x1 - x0), std::abs(y1 - y0));
  if (steps <= 0) {
    hp_px(img, x0, y0, r90);
    return;
  }
  const int half = std::max(0, width / 2);
  for (int i = 0; i <= steps; ++i) {
    const double t = static_cast<double>(i) / static_cast<double>(steps);
    const int x = static_cast<int>(std::lround(
        static_cast<double>(x0) + (static_cast<double>(x1 - x0) * t)));
    const int y = static_cast<int>(std::lround(
        static_cast<double>(y0) + (static_cast<double>(y1 - y0) * t)));
    for (int oy = -half; oy <= half; ++oy) {
      for (int ox = -half; ox <= half; ++ox) {
        hp_px(img, x + ox, y + oy, r90);
      }
    }
  }
}

void hp_glyph_color(
    std::vector<uint8_t>& img,
    int cx,
    int cy,
    const char ch,
    const BitmapFont& f,
    const bool r90,
    const bool black) {
  const Glyph& g = f.glyphs[hp_gi(ch)];
  if (!g.width || !g.height) return;
  const int rb = (g.width + 7) / 8;
  const std::uint8_t* bm = f.bitmap + g.bitmap_offset;
  for (int row = 0; row < g.height; ++row) {
    for (int col = 0; col < g.width; ++col) {
      if ((bm[row * rb + col / 8] & (0x80U >> (col % 8))) == 0) continue;
      if (black) hp_px(img, cx + g.left + col, cy + static_cast<int>(g.top) + row, r90);
      else hp_clr(img, cx + g.left + col, cy + static_cast<int>(g.top) + row, r90);
    }
  }
}

void hp_text_color(
    std::vector<uint8_t>& img,
    int cx,
    int cy,
    const std::string& s,
    const BitmapFont& f,
    const bool r90,
    const bool black) {
  for (const char c : s) {
    hp_glyph_color(img, cx, cy, c, f, r90, black);
    cx += hp_adv(c, f);
  }
}

struct HpMenuOverlayLayout {
  int x0{0};
  int y0{0};
  int x1{0};
  int y1{0};
  int pill_w{0};
  int pill_h{0};
  int gap{0};
  int pills_y{0};
  bool compact{false};
};

HpMenuOverlayLayout hp_menu_overlay_layout(const int width, const int height) {
  HpMenuOverlayLayout layout{};
  const int w = std::max(1, width);
  const int h = std::max(1, height);
  layout.compact = w < 640;
  const int outer_margin = layout.compact ? 8 : 16;
  const int inner_pad_x = layout.compact ? 8 : 14;
  layout.gap = layout.compact ? 8 : 12;
  layout.pill_h = layout.compact ? 40 : 56;
  const int pill_w_cap = layout.compact ? 88 : 116;
  const int pill_w_floor = layout.compact ? 56 : 96;
  constexpr int kItemCount = 5;
  const int available_pills_w = std::max(
      1,
      w - (outer_margin * 2) - (inner_pad_x * 2) - ((kItemCount - 1) * layout.gap));
  layout.pill_w = std::max(
      pill_w_floor,
      std::min(pill_w_cap, available_pills_w / kItemCount));
  const int total_w = (kItemCount * layout.pill_w) + ((kItemCount - 1) * layout.gap);
  const int overlay_w = total_w + (inner_pad_x * 2);
  layout.x0 = std::max(outer_margin, (w - overlay_w) / 2);
  layout.x1 = std::min(w - outer_margin, layout.x0 + overlay_w);
  const int cy = h / 2;
  const int overlay_h = layout.compact ? 78 : 102;
  const int overlay_margin_y = layout.compact ? 96 : 80;
  layout.y0 = std::max(overlay_margin_y, cy - (overlay_h / 2));
  layout.y1 = std::min(h - overlay_margin_y, layout.y0 + overlay_h);
  layout.pills_y = layout.y0 + (layout.compact ? 24 : 28);
  return layout;
}

void hp_draw_menu_overlay(
    std::vector<uint8_t>& image,
    const app::AppState& state,
    const BitmapFont& item_font,
    const BitmapFont& hint_font,
    const bool r90) {
  const HpMenuOverlayLayout layout = hp_menu_overlay_layout(kPW, kPH);
  constexpr int border_w = 1;
  hp_clear_rect(image, layout.x0, layout.y0, layout.x1, layout.y1, r90);
  hp_stroke_rect(image, layout.x0, layout.y0, layout.x1, layout.y1, r90, border_w);

  const std::string hint = "NAVIGATION";
  const int hint_x = layout.x0 + ((layout.x1 - layout.x0) - hp_tw(hint, hint_font)) / 2;
  const int hint_y = layout.y0 + (layout.compact ? 6 : 8);
  hp_text(image, hint_x, hp_ytop(hint_y, hint, hint_font), hint, hint_font, r90);

  constexpr const char* items[] = {"MEMO", "LIST", "TIMER", "CALENDAR", "SETTINGS"};
  constexpr int item_count = 5;
  const int total_w = (item_count * layout.pill_w) + ((item_count - 1) * layout.gap);
  const int start_x = layout.x0 + ((layout.x1 - layout.x0) - total_w) / 2;
  const int focus = static_cast<int>(state.menu.focused_index % static_cast<std::size_t>(item_count));
  const int text_budget = std::max(24, layout.pill_w - (layout.compact ? 14 : 24));

  for (int i = 0; i < item_count; ++i) {
    const int px0 = start_x + i * (layout.pill_w + layout.gap);
    const int px1 = px0 + layout.pill_w;
    const bool focused = i == focus;
    if (focused) {
      hp_fill(image, px0, layout.pills_y, px1, layout.pills_y + layout.pill_h, r90);
    } else {
      hp_clear_rect(image, px0, layout.pills_y, px1, layout.pills_y + layout.pill_h, r90);
    }
    hp_stroke_rect(image, px0, layout.pills_y, px1, layout.pills_y + layout.pill_h, r90, border_w);

    const std::string label = hp_trunc(items[i], item_font, text_budget);
    const int tx = px0 + (layout.pill_w - hp_tw(label, item_font)) / 2;
    const int ty = layout.pills_y + (layout.pill_h - hp_vis_h(label, item_font)) / 2;
    hp_text_color(
        image,
        tx,
        hp_ytop(ty, label, item_font),
        label,
        item_font,
        r90,
        !focused);
  }
}

}  // namespace

// ─────────────────────────────────────────────────────────────────────────────

std::vector<uint8_t> render_home_portrait_bitmap(const app::AppState& state) {
  using namespace platform::panel_font_assets;
  using platform::kPanelBufferSize;

  std::vector<uint8_t> image(kPanelBufferSize, 0xFF);

  const int deg = normalize_rotation_deg(state.settings.rotation_deg);
  const bool r90 = (deg == 90);   // 90°CCW; false → 270°CW

  const HomePortraitTypography typography = home_portrait_typography_for(state);
  const BitmapFont& time_font_lg = *typography.time_font_lg;
  const BitmapFont& time_font_sm = *typography.time_font_sm;
  const BitmapFont& wday_font    = *typography.weekday_font;
  const BitmapFont& date_font    = *typography.date_font;
  const BitmapFont& temp_font    = *typography.temp_font;
  const BitmapFont& meta_font    = *typography.meta_font;
  const BitmapFont& section_font = *typography.section_font;
  const BitmapFont& family_title_font = *typography.family_title_font;
  const BitmapFont& family_name_font = *typography.family_name_font;
  const BitmapFont& family_quote_font = *typography.family_quote_font;
  const BitmapFont& item_font    = *typography.item_font;
  const BitmapFont& badge_font   = *typography.badge_font;

  const std::vector<int> inventory_indices = visible_inventory_indices(state);
  const std::vector<int> reminder_indices = visible_reminder_indices(state);
  const int inv_visible = static_cast<int>(inventory_indices.size());
  const int rem_visible = static_cast<int>(reminder_indices.size());
  const int focus_idx = state.home.show_focus ? std::max(0, state.home.focused_index) : -1;

  // ── Portrait canvas geometry (mirrors Python bp_* defaults) ──────────────
  constexpr int m   = 8;
  constexpr int pad = 8;
  const int lx = m + pad;        // 16  (inner left)
  const int rx = kPW - m - pad;  // 464 (inner right)
  const int content_w = rx - lx; // 448

  // Section heights replicate Python proportions on the 800 px canvas height.
  const int inner_h   = kPH - 2 * m;                                       // 784
  const int sec_gap   = 4;
  const int header_h  = std::max(160, inner_h * 21 / 100);                  // 164
  const int memo_h    = std::max(188, inner_h * 25 / 100);                  // 196
  const int min_list_h = 220;

  const int header_y0 = m;                                                    //   8
  const int header_y1 = std::min(
      kPH - m - 2 * sec_gap - min_list_h - memo_h,
      header_y0 + header_h);                                                   // 172
  const int memo_y0   = header_y1 + sec_gap;                                  // 176
  const int memo_y1   = std::min(
      kPH - m - sec_gap - min_list_h,
      memo_y0 + memo_h);                                                       // 376
  const int list_y0   = memo_y1 + sec_gap;                                    // 380
  const int list_y1   = kPH - m;                                              // 792

  // List inner (padding inset)
  constexpr int list_bottom_reserve = 20;
  constexpr int voice_margin = 14;
  constexpr int voice_lane_h = 29;
  const int voice_guard = std::max(0, voice_margin + voice_lane_h - m - pad + 4);
  const int ly0 = list_y0 + pad;
  const int ly1 = std::max(ly0 + 1, list_y1 - pad - std::max(list_bottom_reserve, voice_guard));
  const int list_h = std::max(80, ly1 - ly0);

  // ── Clock (left column) ──────────────────────────────────────────────────
  const HpClock clk =
      resolve_clock(state.home.clock_minute_bucket, state.onboarding.timezone);

  // Weather column width / inset from Python defaults
  constexpr int kWxColW  = 156;
  constexpr int kColGap  = 16;
  constexpr int kWxInset = 18;
  const int wx_right = rx - kWxInset;          // 446
  const int wx_x0    = rx - kWxColW;           // 308
  const int clk_left = lx;                     //  16
  const int clk_right = wx_x0 - kColGap;       // 292

  // Time  (bp_time_nudge_y = -22)
  const int time_vy = std::max(0, header_y0 + pad - 22);
  const std::string tstr = clk.valid ? clk.time_str : "--:--";
  const BitmapFont& tf =
      (hp_tw(tstr, time_font_lg) <= clk_right - clk_left)
      ? time_font_lg : time_font_sm;
  const HpVB tvb = hp_vb(tstr, tf);
  hp_text(image, clk_left, tvb.ok ? time_vy - tvb.top : time_vy, tstr, tf, r90);
  const int time_vbot =
      time_vy + (tvb.ok ? tvb.bot - tvb.top : static_cast<int>(tf.line_height));
  int clock_bottom_for_focus = time_vbot + hp_vis_h("UNSYNCED", meta_font) + 8;

  if (clk.valid) {
    const int wday_vy = time_vbot + 4;
    const std::string wday = hp_trunc(clk.weekday_str, wday_font, clk_right - clk_left);
    hp_text(image, clk_left, hp_ytop(wday_vy, wday, wday_font), wday, wday_font, r90);

    const int date_vy = wday_vy + hp_vis_h(wday, wday_font) + 8;
    const std::string dstr = hp_trunc(clk.date_str, date_font, clk_right - clk_left);
    hp_text(image, clk_left, hp_ytop(date_vy, dstr, date_font), dstr, date_font, r90);
    clock_bottom_for_focus = date_vy + hp_vis_h(dstr, date_font) + 8;
  } else {
    hp_text(image, clk_left,
            hp_ytop(time_vbot + 4, "UNSYNCED", meta_font),
            "UNSYNCED", meta_font, r90);
  }

  // ── Weather (right column) ────────────────────────────────────────────────
  const bool wx_ok    = (state.home.weather_sync_state == "ok");
  const int  wx_top   = std::max(4, time_vy - 4);
  int weather_bottom_for_focus = wx_top + hp_vis_h("--", temp_font);

  if (wx_ok) {
    const std::string temp_s = std::to_string(state.dashboard.weather_temperature_c);
    const int tw = hp_tw(temp_s, temp_font);
    hp_text(image, wx_right - tw,
            hp_ytop(wx_top, temp_s, temp_font),
            temp_s, temp_font, r90);
    hp_degree(image, wx_right - tw + tw + 2, wx_top + 2, 8, r90);

    const int temp_h   = hp_vis_h(temp_s, temp_font);
    const int icon_vy  = wx_top + temp_h + 13;    // bp_weather_temp_icon_gap=13
    constexpr int kIconSz = 34;
    hp_icon(image, wx_right - kIconSz, icon_vy,
            state.dashboard.weather_condition, kIconSz, r90);

    const int desc_vy = icon_vy + kIconSz + 11;
    const std::string cond_str =
        hp_upper(state.dashboard.weather_condition.empty()
                 ? "SUNNY" : state.dashboard.weather_condition);
    const std::string desc = hp_trunc(cond_str, meta_font, kWxColW);
    hp_text(image, wx_right - hp_tw(desc, meta_font),
            hp_ytop(desc_vy, desc, meta_font),
            desc, meta_font, r90);
    weather_bottom_for_focus = std::max(
        weather_bottom_for_focus,
        std::max(
            wx_top + temp_h,
            std::max(icon_vy + kIconSz, desc_vy + hp_vis_h(desc, meta_font))));

    if (state.dashboard.weather_humidity_percent > 0) {
      const int hum_vy = desc_vy + hp_vis_h(desc, meta_font) + 8;
      const std::string hum = hp_trunc(
          "HUM " + std::to_string(state.dashboard.weather_humidity_percent) + "%",
          meta_font, kWxColW);
      hp_text(image, wx_right - hp_tw(hum, meta_font),
              hp_ytop(hum_vy, hum, meta_font),
              hum, meta_font, r90);
      weather_bottom_for_focus = std::max(weather_bottom_for_focus, hum_vy + hp_vis_h(hum, meta_font));
    }
  } else {
    const std::string no_t = "--";
    hp_text(image, wx_right - hp_tw(no_t, temp_font),
            hp_ytop(wx_top, no_t, temp_font),
            no_t, temp_font, r90);
    const std::string no_d = "NO DATA";
    hp_text(image, wx_right - hp_tw(no_d, meta_font),
            hp_ytop(wx_top + 60, no_d, meta_font),
            no_d, meta_font, r90);
    weather_bottom_for_focus = std::max(weather_bottom_for_focus, wx_top + 60 + hp_vis_h(no_d, meta_font));
  }

  if (state.home.show_focus && focus_idx == 0) {
    const int fx0 = clk_left - 6;
    const int fx1 = clk_right + 6;
    const int fy0 = std::max(0, time_vy - 10);
    const int fy1 = std::min(header_y1 - 2, clock_bottom_for_focus + 2);
    hp_stroke_rounded_rect(image, fx0, fy0, fx1, fy1, r90, 1, 6);
  }
  if (state.home.show_focus && focus_idx == 1) {
    const int fx0 = wx_x0 - 6;
    const int fx1 = wx_right + 12;
    const int fy0 = std::max(0, wx_top - 4);
    const int fy1 = std::min(header_y1 - 2, weather_bottom_for_focus + 4);
    hp_stroke_rounded_rect(image, fx0, fy0, fx1, fy1, r90, 1, 6);
  }

  // ── Memo section ──────────────────────────────────────────────────────────
  {
    // Match landscape typography and author-tag row.
    constexpr int kFamilyTitleSpacing = 3;
    constexpr int kFamilyNameSpacing = 1;
    constexpr int kFamilyGap = 16;
    constexpr int kUnderlineGap = 3;
    constexpr int kUnderlineW = 2;

    const int title_vy = memo_y0 + 2;
    hp_text_spaced(
        image,
        lx,
        hp_ytop(title_vy, "FAMILY BOARD", family_title_font),
        "FAMILY BOARD",
        family_title_font,
        r90,
        kFamilyTitleSpacing);

    const std::vector<std::string> author_tags = hp_family_author_tags(state);
    const int title_w = hp_tw_spaced("FAMILY BOARD", family_title_font, kFamilyTitleSpacing);
    const int max_row_w = std::max(64, rx - (lx + title_w + 22));
    std::vector<std::pair<std::string, int>> labels{};
    labels.reserve(author_tags.size());
    int row_total = 0;
    for (const std::string& author : author_tags) {
      const int avail = max_row_w - row_total - (labels.empty() ? 0 : kFamilyGap);
      if (avail <= 0) {
        break;
      }
      const std::string shown = hp_trunc(author, family_name_font, avail);
      const int width = hp_tw_spaced(shown, family_name_font, kFamilyNameSpacing);
      const int extra = (labels.empty() ? 0 : kFamilyGap) + width;
      if (width <= 0 || row_total + extra > max_row_w) {
        break;
      }
      labels.push_back({shown, width});
      row_total += extra;
    }
    const int min_row_x = lx + title_w + 14;
    int row_x = rx - row_total - 14;
    if (row_x < min_row_x) {
      row_x = min_row_x;
    }
    const int row_y = title_vy + 1;
    const int name_h = hp_vis_h("Ag", family_name_font);
    int cx = row_x;
    for (std::size_t i = 0; i < labels.size(); ++i) {
      const auto& label = labels[i];
      hp_text_spaced(
          image,
          cx,
          hp_ytop(row_y, label.first, family_name_font),
          label.first,
          family_name_font,
          r90,
          kFamilyNameSpacing);
      if (i == 0) {
        const int uy = row_y + name_h + kUnderlineGap;
        hp_fill(image, cx, uy, cx + label.second, uy + kUnderlineW, r90);
      }
      cx += label.second + kFamilyGap;
    }

    const int title_h = hp_vis_h("FAMILY BOARD", family_title_font);
    const int rule_y = std::max(
        memo_y0 + title_h,
        row_y + name_h + kUnderlineGap + kUnderlineW) + 6;
    // Keep a single solid black divider under title.
    hp_fill(image, lx, rule_y, rx, rule_y + 2, r90);

    const int text_y0 = rule_y + 12;
    const int text_h  = memo_y1 - text_y0 - 4;
    const std::string memo = hp_family_memo_text(state);
    if (!memo.empty()) {
      hp_wrapped(image, lx, text_y0, content_w, text_h, memo, family_quote_font, r90, 4);
    }
  }

  // ── Inventory section ─────────────────────────────────────────────────────
  const auto& inv_items  = state.dashboard.inventory_items;
  const auto& inv_done   = state.dashboard.inventory_completed;
  const auto& inv_badges = state.dashboard.inventory_badges;
  const int   inv_total  = static_cast<int>(inv_items.size());
  int inv_comp = 0;
  for (std::size_t i = 0; i < inv_done.size() && i < inv_items.size(); ++i)
    if (inv_done[i]) ++inv_comp;

  const int inv_title_half = hp_vis_h("INVENTORY", section_font) / 2 + 2;
  const int inv_rule_y     = ly0 + std::max(8, inv_title_half);   // ~398
  hp_section_rule(image, lx, rx, inv_rule_y,
                  "INVENTORY", hp_progress(inv_total, inv_comp),
                  section_font, r90);

  constexpr int kInvRowH   = 36;
  constexpr int kBadgeMaxW  = 134;
  int ry = inv_rule_y + 20;
  const int inv_focus_pos =
      (focus_idx >= 2 && focus_idx < (2 + inv_visible)) ? (focus_idx - 2) : -1;

  for (int i = 0; i < inv_visible; ++i) {
    if (ry + kInvRowH > ly1) break;
    const int item_index = inventory_indices[static_cast<std::size_t>(i)];
    const bool done =
        item_index >= 0 &&
        item_index < static_cast<int>(inv_done.size()) &&
        inv_done[static_cast<std::size_t>(item_index)];
    if (i == inv_focus_pos) {
      hp_stroke_rounded_rect(image, lx - 6, ry + 4, rx + 6, ry + kInvRowH - 4, r90, 1, 6);
    }

    // Badge (right-aligned)
    const std::string raw_badge =
        (item_index >= 0 &&
         item_index < static_cast<int>(inv_badges.size()) &&
         !inv_badges[static_cast<std::size_t>(item_index)].empty())
        ? hp_compact_badge(inv_badges[static_cast<std::size_t>(item_index)])
        : (done ? "OUT" : "STOCKED");
    const std::string badge    = hp_trunc(raw_badge, badge_font, kBadgeMaxW);
    const int badge_w          = hp_tw(badge, badge_font);
    const int badge_vis_h      = hp_vis_h(badge, badge_font);
    const int badge_cy         = ry + (kInvRowH - badge_vis_h) / 2;
    hp_text(image, rx - badge_w,
            hp_ytop(badge_cy, badge, badge_font),
            badge, badge_font, r90);

    // Item title (left-aligned)
    const int title_max_w = std::max(80, rx - badge_w - 12 - lx);
    const std::string title   = hp_trunc(
        (item_index >= 0 && item_index < static_cast<int>(inv_items.size()))
            ? inv_items[static_cast<std::size_t>(item_index)]
            : std::string{},
        item_font,
        title_max_w);
    const int title_vis_h     = hp_vis_h(title, item_font);
    const int title_cy        = ry + (kInvRowH - title_vis_h) / 2;
    hp_text(image, lx, hp_ytop(title_cy, title, item_font), title, item_font, r90);

    if (done) {
      const int mid = ry + kInvRowH / 2;
      hp_fill(image, lx, mid, lx + hp_tw(title, item_font), mid + 1, r90);
    }
    ry += kInvRowH;
  }

  // ── Reminders section ─────────────────────────────────────────────────────
  const auto& rem_items = state.dashboard.reminder_items;
  const auto& rem_done  = state.dashboard.reminder_completed;
  const int   rem_total = static_cast<int>(rem_items.size());
  int rem_comp = 0;
  for (std::size_t i = 0; i < rem_done.size() && i < rem_items.size(); ++i)
    if (rem_done[i]) ++rem_comp;

  // Mirror Python: inv_zone_bottom = min(ly1-shop_min_h, ly0+max(96,list_h*48/100))
  const int shop_min_h     = 104;
  const int inv_zone_bot   = std::min(ly1 - shop_min_h,
                                      ly0 + std::max(96, list_h * 48 / 100));
  const int rem_rule_y     = std::max(inv_zone_bot, ry + 8);
  hp_section_rule(image, lx, rx, rem_rule_y,
                  "REMINDERS", hp_progress(rem_total, rem_comp),
                  section_font, r90);

  constexpr int kRemRowH   = 36;
  constexpr int kCbSize     = 16;
  ry = rem_rule_y + 20;
  const int rem_focus_base = 2 + inv_visible;
  const int rem_focus_pos =
      (focus_idx >= rem_focus_base && focus_idx < (rem_focus_base + rem_visible))
          ? (focus_idx - rem_focus_base)
          : -1;

  for (int i = 0; i < rem_visible; ++i) {
    if (ry + kRemRowH > ly1) break;
    const int item_index = reminder_indices[static_cast<std::size_t>(i)];
    const bool done =
        item_index >= 0 &&
        item_index < static_cast<int>(rem_done.size()) &&
        rem_done[static_cast<std::size_t>(item_index)];
    if (i == rem_focus_pos) {
      hp_stroke_rounded_rect(image, lx - 6, ry + 4, rx + 6, ry + kRemRowH - 4, r90, 1, 6);
    }

    // Checkbox: Python parity (rounded outline + checkmark when completed).
    const int cb_x0 = lx;
    const int cb_y0 = ry + (kRemRowH - kCbSize) / 2;
    hp_stroke_rounded_rect(
        image,
        cb_x0,
        cb_y0,
        cb_x0 + kCbSize,
        cb_y0 + kCbSize,
        r90,
        2,
        3);
    if (done) {
      hp_line(
          image,
          cb_x0 + 3,
          cb_y0 + (kCbSize / 2),
          cb_x0 + 6,
          cb_y0 + kCbSize - 4,
          r90,
          2);
      hp_line(
          image,
          cb_x0 + 6,
          cb_y0 + kCbSize - 4,
          cb_x0 + kCbSize - 3,
          cb_y0 + 3,
          r90,
          2);
    }

    // Item title
    const int tx = lx + kCbSize + 14;
    const std::string title   = hp_trunc(
        (item_index >= 0 && item_index < static_cast<int>(rem_items.size()))
            ? rem_items[static_cast<std::size_t>(item_index)]
            : std::string{},
        item_font,
        rx - tx - 4);
    const int title_vis_h     = hp_vis_h(title, item_font);
    const int title_cy        = ry + (kRemRowH - title_vis_h) / 2;
    hp_text(image, tx, hp_ytop(title_cy, title, item_font), title, item_font, r90);

    if (done) {
      const int mid = ry + kRemRowH / 2;
      hp_fill(image, tx, mid, tx + hp_tw(title, item_font), mid + 1, r90);
    }
    ry += kRemRowH;
  }

  if (state.home.menu_overlay_active) {
    hp_draw_menu_overlay(
        image,
        state,
        *typography.menu_item_font,
        *typography.menu_hint_font,
        r90);
  }

  return image;
}

}  // namespace fridge_ink::ui
