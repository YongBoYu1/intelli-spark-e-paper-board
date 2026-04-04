# Issue 52 Menu Overlay Residual / Typography Note

Date: 2026-04-03  
Branch: `codex/52-runtime-migration`

## User-reported symptoms

1. `MEMO` 等未选中按钮在 menu 打开后视觉上有时像“透明/发虚”，前后不一致。  
2. menu 关闭后区域会有残留（胶囊轮廓/发白影子）。  
3. 字体大小、粗细、黑度还需要细扣。

## Root-cause classification (code vs waveform vs alignment)

### 1) Alignment/layout mismatch

Current verdict: **not primary**.

Menu overlay geometry in C++ matches Python layout constants:

- `pill_h`: `56` (`40` compact)
- `pill_w` floor/cap: `96/116` (`56/88` compact)
- `gap`: `12` (`8` compact)
- `overlay_h`: `102` (`78` compact)

References:

- C++: `/Users/yongboyu/Desktop/intelli-spark-e-paper-board/firmware/main/ui/screens/home_screen.cpp`
- Python: `/Users/yongboyu/Desktop/intelli-spark-e-paper-board/app/ui/menu.py`

### 2) Rendering intent mismatch ("transparent vs solid")

Current verdict: **intent is solid, not transparent**.

Both Python/C++ draw non-focused pills as `fill=bg` (white), focused pill as `fill=ink` (black).  
So “transparent look” is not intended style; it is a display artifact under partial refresh.

### 3) Waveform / partial-refresh artifact

Current verdict: **primary**.

For Home menu overlay dirty region (800x480 panel):

- overlay region area ratio ≈ `0.174`
- aligned+pad partial gate ratio ≈ `0.186`
- Home menu override limit is `0.60`

So this path reliably chooses partial refresh, and single-pass partial on this large black↔white transition can leave residual/whitening artifacts.

References:

- decision path: `/Users/yongboyu/Desktop/intelli-spark-e-paper-board/firmware/main/app/runtime.cpp`
- partial driver path: `/Users/yongboyu/Desktop/intelli-spark-e-paper-board/firmware/main/platform/display.cpp`

## Python parity status

- Removed `menu overlay open -> force full` override.
- `home.menu_overlay_toggle` / `home.menu_overlay_focus` now flow through policy gating again.
- This is aligned with Python decision style (partial-first for this region when under area limit).

## Fix options (ordered)

### Option A (parity-safe, minimal risk)

Keep policy unchanged; only strengthen execution for `home.menu_overlay_toggle` partial:

- use deterministic 2-pass partial for this reason
- keep same dirty rect / same decision logs

Expected: residual probability drops without reintroducing random fast full.

### Option B (stronger cleanup, slightly more invasive)

For menu toggle only, do a local pre-clean pass (white underlay in same rect) then target pass.

Expected: best residual suppression, but this adds behavior beyond Python runtime loop and should be explicitly documented.

## Typography fine-tuning checklist

Target scope: menu overlay labels (`MEMO/LIST/TIMER/CALENDAR/SETTINGS`) and `NAVIGATION` hint.

Measurable criteria:

1. label visual center error <= 1 px (x/y) across all pills  
2. focused/non-focused stroke-weight contrast stable after 20 rotate ops  
3. no persistent whitening on unfocused labels after focus leaves

Likely adjustment points:

- item font fallback ladder in C++ menu draw path
- bbox centering baseline consistency with Python `textbbox` behavior
- (optional) per-reason partial pass reinforcement for menu focus/toggle

