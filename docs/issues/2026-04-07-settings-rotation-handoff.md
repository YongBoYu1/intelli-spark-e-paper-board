# Settings UI + Rotation Handoff

**Branch:** `codex/52-runtime-migration`
**Goal:** 1:1 parity with Python simulator. Read Python source first, then migrate — do not invent.

---

## Scope of This Task

1. **Settings UI** — migrate both landscape and portrait from the legacy `draw_text_line` system to the BitmapFont (`kFontInter*` / `kFontJet*`) system to match Python font sizes
2. **Font Size functionality** — `state.settings.font_size` ("small" / "medium" / "large") must actually scale fonts across screens
3. **Home Page Portrait layout** — when `rotation_deg == 90 || 270`, `render_home_bitmap` must dispatch to a portrait renderer (card layout inside 800×480 buffer)
4. **Rotation wires up Home** — all other screens already handle rotation; Home is the only one missing

---

## What Is Already Working

- `state.settings.rotation_deg` cycles 0→90→180→270 on click (reducer handles it)
- All screens except Home check `rotation_deg` and dispatch to portrait: Calendar, List, Weather, Settings, Memo, Timer
- Settings portrait/landscape structure exists in `settings_screen_portrait.cpp` and `settings_screen_landscape.cpp`
- The settings `focused_index` scroll, underline focus indicator, footer, and group layout are all correct

---

## Task 1 — Settings UI Font Alignment

### Problem
Both settings files use `draw_text_line(image, x, y, text, scale, max_w)` which is a legacy pixel-scaling system. Python uses proper BitmapFont (inter_medium, inter_bold, jet_bold).

### Python font sizing (from `app/ui/settings.py`)
```python
body_base = 18
label_size = max(16, body_base + 3)     # = 21px  → inter_medium
value_size = max(13, label_size - 3)    # = 18px  → jet_bold (use closest)
title_font  = inter_bold  ~29px         # max(24, int(18 * 1.65)) = 29
group_font  = jet_bold    ~12px         # meta_base - 1 = 12
footer_font = jet_bold    13px          # meta_base = 13
```

### C++ BitmapFont mapping
| Role         | Python size | Use in C++             |
|--------------|-------------|------------------------|
| Title        | inter_bold 29px  | `kFontInterBold29`     |
| Label (normal) | inter_medium 21px | `kFontInterMedium18`  |
| Label (focused) | inter_bold 21px | `kFontInterBold20`    |
| Value        | jet_bold 18px   | `kFontJetExtraBold16`  |
| Group header | jet_bold 12px   | `kFontJetBold13`       |
| Footer/hint  | jet_bold 13px   | `kFontJetBold13`       |

### Files to change
- `firmware/main/ui/screens/settings_screen_landscape.cpp`
- `firmware/main/ui/screens/settings_screen_portrait.cpp`

### How other screens use BitmapFont (reference pattern)
Look at `firmware/main/ui/screens/weather_screen_landscape.cpp` — it uses helpers from
`firmware/main/ui/screens/` like `wl_draw_centered`, `wl_text_width`, `wl_center_y`, etc., and directly draws via `draw_glyph` from `ui/draw.hpp`.

For settings, you can use the helpers from `ui/draw.hpp`:
```cpp
#include "ui/panel_font_assets_generated.hpp"
// Then use: kFontInterBold29, kFontInterMedium18, kFontInterBold20, kFontJetExtraBold16, kFontJetBold13
// Draw with the same wl_* helpers used in weather_screen_landscape.cpp
```

### Python layout details (landscape, `render_settings`)
```python
title at (24, 16), inter_bold ~29px
hint right-aligned at y=52, jet_bold 13px, muted
divider at y=68, left=24, right=w-24
content_top = 90
row_h = 34 (shrinks if overflow)
row_gap = 1
group_h = 20 (with group label)
group_gap = 7

# Each row:
marker ">" or " " at left+2 → value_font (jet_bold 16px)
label at label_x, y0 + (row_h - label_h)//2 → row_font (inter_medium/bold 21px)
value right-aligned at right-12 → value_font (jet_bold 16px)
underline at y0+row_h-3 when focused

footer_top = h - 30
footer divider at footer_top - 1
notice left, sync status right → jet_bold 13px
```

### Python layout details (portrait)
Portrait mode uses the same settings.py function but on a 480×800 image.
In C++, the portrait card is `x=[108..692], y=[14..466]` (584×452 inside 800×480 buffer).
Scale all Python padding/sizes proportionally (584/480 ≈ 1.22× width, 452/480 ≈ 0.94× height).

Current portrait file already has the right card border and group structure — only the font primitives need to change from `draw_text_line` to BitmapFont.

---

## Task 2 — Font Size Functionality

### Python behavior (from `app/core/state.py`, `app/shared/panel_font_templates.py`)
- `font_size` = "small" / "medium" / "large"
- Applied as multiplier on `body_base = 18`:
  - small  → `int(18 * 0.90)` = 16px body
  - medium → `int(18 * 1.00)` = 18px body  ← default
  - large  → `int(18 * 1.12)` = 20px body

### C++ approach
Add a helper to `ui/draw.hpp` or inline in each screen:
```cpp
// Returns body_base multiplied by font_size scale
inline int body_base_px(const app::AppState& state) {
  const std::string& fs = state.settings.font_size;
  if (fs == "small") return 16;
  if (fs == "large") return 20;
  return 18;  // medium default
}
```

Then, when selecting fonts for labels/values, pick the size tier closest to `body_base_px(state)`:
- 16px → use `kFontInterMedium13` / `kFontInterBold17`
- 18px → use `kFontInterMedium18` / `kFontInterBold20`
- 20px → use `kFontInterBold20` / `kFontInterBold22`

For now it's acceptable to apply font_size only to the Settings screen labels. Other screens are lower priority.

---

## Task 3 — Home Portrait Layout (MINIMUM REQUIRED)

### Problem
`firmware/main/ui/screens/home_screen.cpp::render_home_bitmap` always renders landscape.
It never checks `state.settings.rotation_deg`.

### Fix: add portrait dispatch
At the top of `render_home_bitmap` (around line 1585), add:
```cpp
std::vector<uint8_t> render_home_bitmap(const app::AppState& state) {
  const int deg = ((state.settings.rotation_deg % 360) + 360) % 360;
  if (deg == 90 || deg == 270) {
    return render_home_portrait_bitmap(state);  // NEW
  }
  // ... existing landscape code
}
```

Declare `render_home_portrait_bitmap` in `home_screen.hpp` and implement in a new file `home_screen_portrait.cpp`.

### Python source for portrait home
**File:** `app/ui/home_kitchen_portrait.py`

Key layout (portrait card = 584×452 in physical terms, rendered as card inside 800×480 buffer):
```python
# Card: x=[108..692] (584px wide), y=[14..466] (452px tall)
# Margins: bp_margin = 8
# Section ratios:
bp_header_ratio = 0.21   # top header zone (time + date + weather)
bp_memo_ratio   = 0.25   # memo/quote section below header
# Remaining: shopping list + reminders at bottom
```

### Minimum viable portrait home (what to implement)
The full portrait home (`home_kitchen_portrait.py`) is very complex (memo, lists, reminders).
For the 横评 review, **at minimum implement the header section** matching Python:

#### Python portrait header (from `home_kitchen_portrait.py`)
```python
bp_time_size    = 112  # huge clock
bp_weekday_size = 15
bp_date_size    = 19
bp_temp_size    = 58   # weather temp
bp_weather_icon_size = 34
bp_weather_col_w = 156  # weather column width on right
bp_header_ratio  = 0.21  # = 0.21 × 452 ≈ 95px header height
```

Layout of portrait header:
- **Left column** (width = card_w - weather_col_w - header_col_gap):
  - Time (huge, ~87px JetExtraBold, vertically nudged up)
  - Weekday label below time (spaced uppercase, ~15px)
  - Date below weekday (~19px)
- **Right column** (width = bp_weather_col_w = 156px, right-aligned in card):
  - Temperature large (~58px)
  - Weather icon below temp (~34px)
  - Humidity / weather description

C++ available fonts:
- Time: `kFontJetExtraBold66` or `kFontJetExtraBold84` (closest to 87px is 84px)
- Date/weekday: `kFontJetBold13` or `kFontJetBold15`
- Temp: `kFontInterBlack66` (58px is closest)
- Weather icon: use `draw_icon()` from `ui/primitives.hpp` at size 34

Card geometry in C++ (same as other portrait screens):
```cpp
constexpr int kCard_X0 = 108;
constexpr int kCard_X1 = 692;  // card_w = 584
constexpr int kCard_Y0 = 14;
constexpr int kCard_Y1 = 466;  // card_h = 452
```

Draw the card outline with `draw_rounded_rect_stroke(image, kCard_X0, kCard_Y0, kCard_X1, kCard_Y1, 16, 2)`.

#### Full portrait home (stretch goal for this session)
After the header, read `home_kitchen_portrait.py` directly and implement:
1. Memo section (quote text, big and centered)
2. Inventory list section
3. Shopping list section

Each uses the same BitmapFont primitives already established in the codebase.

---

## File Map

| File | Status | Action |
|------|--------|--------|
| `firmware/main/ui/screens/settings_screen_landscape.cpp` | ⚠ wrong fonts | Migrate from `draw_text_line` to BitmapFont |
| `firmware/main/ui/screens/settings_screen_portrait.cpp` | ⚠ wrong fonts | Same migration |
| `firmware/main/ui/screens/home_screen.cpp` | ⚠ no rotation | Add portrait dispatch at top of `render_home_bitmap` |
| `firmware/main/ui/screens/home_screen_portrait.cpp` | ❌ missing | Create new file, implement portrait home |
| `firmware/main/ui/screens/home_screen.hpp` | ⚠ update | Add `render_home_portrait_bitmap` declaration |
| `firmware/main/CMakeLists.txt` | ⚠ update | Add `"ui/screens/home_screen_portrait.cpp"` |

---

## Key Python Sources to Read

| Python file | What it defines |
|-------------|-----------------|
| `app/ui/settings.py` | Settings UI render logic (full source) |
| `app/core/settings_schema.py` | SETTINGS_GROUPS, SETTINGS_ORDER, SETTINGS_LABELS |
| `app/ui/home_kitchen_portrait.py` | Portrait home layout — read this fully before implementing |
| `app/ui/home_kitchen_geometry.py` | Portrait home header geometry helpers |
| `app/core/state.py` | `UiState` fields (font_size, rotation_deg, etc.) |

---

## Do Not

- Do not change the reducer — rotation cycling already works
- Do not change `state.hpp` — all needed fields exist
- Do not change `render_app.cpp` — it already calls `render_home_bitmap`
- Do not invent new features — copy Python 1:1
- Do not add WiFi/sync functionality — "FAKE SYNC COMPLETE" is the correct behavior for now
