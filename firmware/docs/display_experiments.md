# Display Experiment Log — Waveshare 7.5" V2 (UC8176) on ESP32-S3

Hardware: ESP32-S3 + Waveshare 7.5" e-Paper V2, SPI 2MHz
GPIOs: RST=4, PWR=8, MOSI=11, CLK=12, BUSY=14, DC=21, CS=47

Reference baseline: Python driver on Raspberry Pi (SPI 4MHz) displays perfectly on the same panel.

---

## Experiment #0 — Arduino bit-bang full-black test
**Date:** 2026-03-20 (approx)
**Branch:** codex/esp32-s3-board-bringup
**Setup:** Arduino sketch with bit-bang SPI (~250kHz), NOT hardware SPI
**Init sequence:** 0x01 → 0x04 → 0x00 → 0x61 → 0x15 → 0x50 → 0x60. NO 0x06 (Booster Soft Start).
**Test:** Fill entire DTM2 with 0xFF (all bits set), send 0x12 refresh
**Result:** Deep black across entire panel. Full contrast. Hardware confirmed working.
**Key findings documented in ESP32 Test/README.md:**
- Bug #5: sending 0x06 (Booster Soft Start) caused Power ON (0x04) to hang indefinitely in bit-bang mode
- BUSY polarity: HIGH=idle, LOW=busy
- Reset sequence: HIGH 20ms → LOW 2ms → HIGH 20ms
**Lesson:** 0x06 behavior depends on SPI transport — hangs with bit-bang, works with hardware SPI and with Python/RPi.

---

## Experiment #0.5 — Embedded Python asset via C++ driver
**Date:** 2026-03-22 (approx)
**Setup:** kUseEmbeddedLandingReference=true — Python-generated landing_en.raw loaded into framebuffer, sent through same C++ display_bitmap()
**Result:** Good display! Content clearly visible, proper contrast.
**Analysis:** This proves the SPI driver + init sequence can produce acceptable output. The .raw asset uses Python's getbuffer() convention (0=black, 1=white). The C++ driver sends it correctly.
**Key insight:** Same display_bitmap() function, same init, same hardware — embedded asset looks good, C++ rendered bitmap looks gray. The difference MUST be in the bitmap content/encoding, not the driver.

---

## Experiment #1 — Initial C++ dynamic rendering
**Date:** 2026-03-23
**Init sequence:** 0x06(0x17,0x17,0x28,0x17) → 0x01(0x07,0x07,0x3F,0x3F) → 0x04 → 0x00(0x1F) → 0x61 → 0x15(0x00) → 0x82(0x12) → 0x30(0x06) → 0x50(0x10,0x07) → 0x60(0x22)
**Full refresh:** DTM1=~image, DTM2=image (kUseInvertedFirstFrame=true)
**Partial refresh:** 0x50(0xA9,0x07) → 0x91 → 0x90(window) → 0x13(~data) → 0x12. No mode init.
**Result:**
- First frame: visible but gray/low contrast, especially top half
- Partial refresh: massive corruption/noise/tearing after 2-3 interactions
- Interaction (a/d/c): functional but every change triggers visible artifacts

**Analysis:**
- 0x01 bytes 3,4 = 0x3F,0x3F (max voltage) — Python uses 0x28,0x17
- 0x82 VCOM override (0x12) — Python doesn't send this, uses OTP
- 0x30 PLL override (0x06) — Python doesn't send this, uses OTP
- Partial refresh missing 0xE0/0xE5 panel mode init (Python: init_part)
- clear() sent DTM1=0x00 (no transition) — Python sends DTM1=0xFF

---

## Experiment #2 — Remove 0x06, 0x82, 0x30
**Date:** 2026-03-23
**Change:** Removed 0x06 (Booster Soft Start), 0x82 (VCOM), 0x30 (PLL) from init
**Result:** WORSE — display quality degraded further
**Analysis:** Removing 0x06 was the mistake. 0x06 (Booster Soft Start) IS needed — Python driver sends it. Should have only removed 0x82 and 0x30.
**Lesson:** Change one variable at a time!

---

## Experiment #2.5 — Added clear() before first render
**Date:** 2026-03-23
**Change:** Called display.clear() in runtime.boot() before first render()
**Result:** First frame contrast DROPPED significantly — even worse than before
**Root cause:** clear() set `previous_frame_valid_=true` with previous_frame_=all-zeros. So the first real frame used DTM1=previous_frame(all-zeros) instead of DTM1=~image. Without the inverted first frame trick, the panel had no strong transition to drive deep blacks.
**Fix:** Removed clear() call before first render.
**Lesson:** The first frame NEEDS DTM1=~image to create a maximum transition. Any operation that sets previous_frame_valid_=true before the first real render will bypass this and produce weak contrast.

---

## Experiment #3 — Match Python init + add partial mode init
**Date:** 2026-03-25
**Changes:**
1. 0x01: changed 0x3F,0x3F → 0x28,0x17 (match Python)
2. Removed 0x82 and 0x30 (use OTP, match Python)
3. Keep 0x06 (Booster Soft Start) — Python uses it
4. Added enter_partial_mode(): reset → 0x00(0x1F) → 0x04 → 0xE0(0x02) → 0xE5(0x6E) (match Python init_part)
5. Added restore_full_mode() before full refresh after partial
6. Fixed clear(): DTM1 0x00 → 0xFF (match Python)

**Result:**
- Interaction works! Successfully navigated Landing → Onboarding → Home
- Partial refresh: no more severe corruption/tearing
- Contrast: still washed out / grayish — better than #1 but NOT matching Python quality
- Overall screen appears "white-ish" — blacks are gray, not deep black

**Analysis:**
- Partial refresh fix (0xE0/0xE5) clearly worked
- Contrast issue remains — possible causes:
  - SPI speed difference? (C++ 2MHz vs Python 4MHz) — unlikely to affect contrast
  - Pixel polarity mismatch? Need to verify C++ framebuffer encoding vs Python getbuffer()
  - VCOM still wrong? OTP value may not be optimal; may need manual 0x82 tuning
  - Power timing? Python has different delays
  - Temperature / refresh LUT? Panel may need different waveform timing

---

## Experiment #4 — Pixel polarity inversion test
**Date:** 2026-03-25
**Hypothesis:** C++ framebuffer uses 1=black, 0=white. Panel expects 0=black, 1=white (Python convention). Inverting the entire image before sending DTM2 should fix contrast.
**Change:** In display_bitmap(), invert image before DTM2, swap DTM1, send partial data without inversion.
**Photo:** See photo `exp4_inverted_negative.jpg` — image is a complete negative (white text on dark background), vertical streaking artifacts on upper portion.
**Result:** WRONG — image is fully inverted (negative). Interaction stuck on landing page (likely corrupted state from bad refresh).
**Conclusion:** **C++ convention (1=black, 0=white) IS correct for this panel's DTM2.** The panel uses 1=black, NOT 0=black as Python getbuffer suggests.
**Reverted:** Yes, immediately.

**Key insight:** Python getbuffer() starts with 0xFF and clears bits for black (0=black). But the Python display() function then sends this directly to DTM2, meaning 0=black in DTM2. Our panel shows the OPPOSITE behavior — 1=black in DTM2. This means either:
1. The panel LUT (OTP) on this specific unit maps 1→black (non-standard)
2. OR the Python RPi driver has additional inversion we haven't found
3. OR the Arduino full-black test (DTM2=0xFF=all-1s → black screen) confirms: 1=black is correct for this panel

**Lesson:** The Arduino full-black test already proved: sending 0xFF to DTM2 → black pixels. So 1=black is the correct convention. The contrast issue is NOT polarity.

---

## Experiment #5 — SPI speed 2MHz → 4MHz
**Date:** 2026-03-25
**Change:** kSpiClockHz = 4,000,000 (match Python RPi driver)
**Result:** No visible difference. Still same grayish contrast.
**Conclusion:** SPI speed is not a factor in contrast.
**Status:** Kept at 4MHz (matches Python, no downside).

---

## Experiment #6 — VCOM sweep (0x82 register)
**Date:** 2026-03-25
**Setup:** Added serial command `v<HH>` to set 0x82 register at runtime + force full refresh
**Values tested:** v00, v08, v10, v12, v18, v20, v28, v30 (and random values)
**Result:** ALL values produce identical output. No contrast change whatsoever.
**Conclusion:** **Panel ignores 0x82 in OTP LUT mode (0x00=0x1F).** VCOM is embedded in the OTP waveform data and cannot be overridden via register.
**Lesson:** When Panel Setting = 0x1F (OTP mode), VCOM tuning via 0x82 is not available. Would need external LUT mode (0x00=0x3F) to control VCOM manually, but that requires providing full LUT tables.

---

## Experiment #7 — First-frame `DTM1` strategy is not the sole cause
**Date:** 2026-03-23 to 2026-03-25
**Hypothesis:** The washed-out first screen is mainly caused by the wrong `DTM1` old-buffer strategy.

**Variants tested:**
1. `DTM1 = ~image`, `DTM2 = image`
2. `DTM1 = 0x00 baseline`, `DTM2 = image`
3. Later frames using `DTM1 = previous_frame`, `DTM2 = image`

**Result:**
- Changing first-frame `DTM1` away from `~image` did change the look, but the landing page still remained gray / washed out.
- In other words, the first-frame strategy matters, but flipping this one variable does **not** fix contrast by itself.

**Conclusion:** `DTM1` first-frame policy is a contributing factor, but not the sole root cause.

---

## Experiment #8 — Current pure C++ landing renderer is still not the Python product renderer
**Date:** 2026-03-25
**Goal:** Separate "driver problem" from "bitmap content problem".

**What was confirmed:**
1. The current firmware architecture renders landing/onboarding to a framebuffer in:
   - `firmware/main/ui/screens/landing_screen.cpp`
   - `firmware/main/ui/screens/onboarding_screen.cpp`
   and sends that framebuffer via:
   - `firmware/main/platform/display.cpp::display_image()`

2. The Python product landing page is still rendered by:
   - `app/ui/onboarding.py::render_landing()`
   using:
   - `landing_layout_metrics()`
   - panel font template/theme logic
   - Pillow font metrics
   - rounded rectangles / focus rings / spacing rules

3. The current C++ landing page is **not** a direct port of that renderer.
   - It is still a hand-written approximation with fixed scales and manually compensated spacing.
   - It does not yet share the same layout/font pipeline as the Python product page.

4. The known-good Python landing asset (`landing_en.raw`) has already displayed significantly better than the current pure C++ landing page on the same ESP32 panel path.

**Conclusion:** The remaining software gap is now much more likely to be **renderer parity / bitmap content**, not SPI speed or simple polarity.

---

## Experiment #9 — Glyph baseline bug fix + first-frame pre-conditioning
**Date:** 2026-03-25
**Changes:**
1. Fixed `draw_glyph()`: removed extra `ascent` from y-calculation (`y + ascent + top` → `y + top`)
2. Adjusted landing_screen layout constants: `chips_y0 += 40` → `+26`, button guard `+60` → `+44`
3. Added first-frame pre-conditioning: clear cycle (DTM1=0xFF, DTM2=0x00) before displaying content
**Result:**
- **Layout is now CORRECT** — title, subtitle, tip cards, language chips, status text, CTA button all properly positioned and spaced
- **Contrast still washed out** — filled areas (tip cards, ENGLISH chip, CTA button) are gray, not deep black
- **Text is readable and well-positioned** — the glyph fix was confirmed correct
**Conclusion:** Glyph baseline bug was a real rendering error that affected all text positioning. Pre-conditioning didn't visibly improve contrast. The contrast issue is separate from layout.

---

## Experiment #10 — Pixel convention flip to Python 0=black + remove pre-conditioning
**Date:** 2026-03-25
**Hypothesis:** OTP LUT was designed for Python convention (0=black, 1=white). C++ uses inverted convention (1=black, 0=white). This means LUT receives wrong (old→new) transitions and applies wrong waveforms, causing the "flash of correct image then settle to gray" behavior.
**Changes:**
1. draw.cpp: framebuffer init 0x00 → 0xFF (start all-white)
2. draw.cpp: set_black_pixel: OR (set bit) → AND NOT (clear bit) — 0=black
3. draw.cpp: clear_pixel: AND NOT → OR (set bit) — 1=white
4. display.cpp: remove pre-conditioning clear cycle
5. display.cpp: keep kUseInvertedFirstFrame=true (DTM1=~image still correct for Python convention)
**Expected:** With 0=black convention, DTM1=~image gives DTM1=1 where black, DTM2=0 where black → (1→0) transition. If LUT maps (1→0) to "drive to black state", contrast should be deep black.
**Result:**
- Content IS darker — background, cards, buttons all visibly deeper than before
- BUT the black is NOT healthy — grainy, has vertical banding/stripes, textured gray-black
- White areas also not clean white — covered by a gray fog
- Vertical banding pattern suggests uneven refresh settle or DTM1/actual-state mismatch
**Conclusion:** Pixel convention change CONFIRMED effective at content layer. But the remaining problem is now clearly in the **panel drive/refresh path**:
- The panel is not settling to clean binary (pure black / pure white)
- Large solid areas show texture/grain instead of uniform black → waveform is not fully driving pixels
- Vertical banding → refresh settle is non-uniform, or DTM1 still doesn't match actual panel state
- This is NOT a renderer/color problem anymore — the renderer IS requesting black correctly now
**Key insight:** `kUseInvertedFirstFrame` sends DTM1=~image, which doesn't match the panel's ACTUAL state (unknown/residual). The LUT receives wrong (old→new) transition info and applies wrong waveforms, producing gray instead of deep black.

---

## Experiment #11 — Clear-to-white baseline + correct DTM1
**Date:** 2026-03-25
**Changes:**
1. First frame: clear panel to all-white (DTM1=0x00, DTM2=0xFF), wait 3620ms
2. Set previous_frame_=0xFF, previous_frame_valid_=true
3. Display content: DTM1=0xFF (matches actual panel state), DTM2=image
4. Black pixels: (1→0) transition, white pixels: (1→1) no change
**Log confirms:** Exactly 2 refreshes, no extra renders. Timing normal (3620ms each).
**Result:**
- Still gray with vertical banding. No significant improvement over Exp #10.
- **Critical observation by user:** "闪了一下是对的" — during the waveform execution, correct deep-black image appeared momentarily, then faded to gray during settle.
**Analysis:**
- DTM1 now matches actual panel state → transition info is correct
- But waveform STILL doesn't settle to proper binary → problem is in the **LUT waveform itself**, not the data
- "Flash correct then fade gray" = LUT has a phase that overcorrects/washes out the correct image
- The OTP LUT (selected by Panel Setting 0x00=0x1F) may not be the right LUT for our use case
**Key question:** Arduino full-black test (Exp #0) used NO 0x06 and simpler init → produced deep black. Maybe the OTP LUT selected by our current init (with 0x06 Booster Soft Start) behaves differently than the one selected without it?

---

## Remaining contrast hypotheses (ranked by likelihood)

**Ruled out:**
- ~~Pixel polarity~~ — Experiment #4 proved 1=black is correct for this panel
- ~~SPI speed~~ — Experiment #5 showed no difference at 4MHz
- ~~VCOM tuning (0x82)~~ — Experiment #6 proved panel ignores it in OTP mode

**Active hypotheses:**

1. **Pure C++ renderer is still not parity with the Python product renderer**
   - Current `landing_screen.cpp` is still a hand-written approximation, not a direct port of `app/ui/onboarding.py::render_landing()`
   - Font metrics, layout rules, and dense black regions may still differ materially

2. **VDH/VDL driving voltage (0x01 bytes 3,4)**
   - Exp #1: 0x3F,0x3F (max) — gray
   - Exp #3: 0x28,0x17 (Python) — still gray
   - ESP32 3.3V rail may need different values than RPi
   - TODO: Try intermediate values

3. **Reset timing**
   - C++: 200ms HIGH, 2ms LOW, 200ms HIGH
   - Python: 20ms, 2ms, 20ms (10x shorter!)
   - TODO: Try 20ms to match Python

4. **First-frame / previous-frame interaction**
   - Experiment #7 showed this matters, but it is not enough on its own
   - Still worth retesting once bitmap parity improves

5. **Double full refresh / conditioning cycle**
   - Panel may need multiple waveform cycles to reach final black level on the first frame
   - TODO: Test a second full cycle in isolation

---

## Known Software Bugs (not display-related)

### Font engine glyph_y0 bug
- `draw_glyph()` computes: `glyph_y0 = baseline_y + glyph.top` where `baseline_y = y + font.ascent`
- Should be: `glyph_y0 = y + glyph.top` (glyph.top is already relative to the ascender line from Pillow's getbbox)
- Effect: all text rendered ~18px (one ascent) too low
- Current workaround: spacing constants adjusted to compensate
- Proper fix needed when addressing text rendering quality

---

## Key Reference: Python Driver Init (epd7in5_V2.py)

### Full refresh init():
```
0x06: 0x17, 0x17, 0x28, 0x17  (Booster Soft Start)
0x01: 0x07, 0x07, 0x28, 0x17  (Power Setting)
0x04: Power ON + wait busy
0x00: 0x1F                     (Panel Setting)
0x61: 0x03, 0x20, 0x01, 0xE0  (Resolution 800x480)
0x15: 0x00                     (Dual SPI disabled)
0x50: 0x10, 0x07               (VCOM & Data Interval)
0x60: 0x22                     (TCON)
```

### Partial refresh init_part():
```
reset()
0x00: 0x1F                     (Panel Setting)
0x04: Power ON + wait busy
0xE0: 0x02                     (Enable partial mode)
0xE5: 0x6E                     (Partial refresh timing)
```

### Fast refresh init_fast():
```
reset()
0x00: 0x1F
0x50: 0x10, 0x07
0x04: Power ON + wait busy
0x06: 0x27, 0x27, 0x18, 0x17  (Different booster params!)
0xE0: 0x02
0xE5: 0x5A                     (Different timing: 0x5A vs 0x6E)
```

### Python display():
```
DTM1 (0x10): ~image (inverted)
DTM2 (0x13): image (direct)
0x12: Refresh + wait busy
```

### Python getbuffer() convention:
```
buf = [0xFF] * size    # all white
for black_pixel:
    buf[i] &= ~bit     # clear bit = black
→ Convention: 0=black, 1=white
```

### Python Clear():
```
DTM1 (0x10): 0xFF * all
DTM2 (0x13): 0x00 * all
0x12: Refresh
```

---

## Experiment #12 — init_fast + 0=black + clear-to-white baseline
**Date:** 2026-03-25
**Changes:** init_fast() mode (0xE0:0x02, 0xE5:0x5A) + 0=black pixel convention + pre-conditioning clear-to-white before content display
**Sequence:** Clear(DTM1=0x00, DTM2=0xFF) → 1520ms → Content(DTM1=0xFF prev, DTM2=image) → 1520ms
**Result:** ⭐ BREAKTHROUGH — Photo captured TWO moments:
- **Penultimate moment (during content refresh waveform): DEEP BLACK! Product-quality contrast!** Clean white background, solid black fills.
- **Final settled state: Washed gray with vertical banding.** Same as previous experiments.
**Analysis:** The waveform MID-CYCLE drives pixels to correct deep black, but the SETTLE/DISCHARGE phase washes it gray. This is NOT a framebuffer or polarity issue — the data is correct. It's a waveform timing problem.
**Key insight:** init_fast()'s 0xE5=0x5A timing produces a waveform whose discharge phase is too aggressive, overcorrecting the pixel state from deep black back toward gray.
**Next hypothesis:** Remove pre-conditioning (eliminate double-refresh), use single DTM1=~image. Or switch back to standard init waveform.

---

## Experiment #13 — init_fast + single refresh (no pre-conditioning)
**Date:** 2026-03-25
**Changes:** Removed clear-to-white pre-conditioning. Single refresh with DTM1=~image (kUseInvertedFirstFrame). Still using init_fast() + 0=black convention.
**Hypothesis:** Double refresh (clear + content) might cause waveform interference. Single refresh might let the mid-cycle deep black settle properly.
**Result:** Same pattern as #12:
- Photo 1 (mid-cycle): Decent contrast in lower half, top tip cards barely visible (ghosting from residual panel state)
- Photo 2 (final settle): Washed gray with vertical banding again
**Conclusion:** Pre-conditioning was NOT the cause. init_fast()'s waveform settle is the root problem — it washes out regardless of DTM1 strategy.

---

## Reproducibility Notes

**Problem:** Experiments #1-13 were done on a single dirty working tree without per-experiment commits. The exact code state for each experiment is NOT git-recoverable.

**To fix going forward:**
1. Each experiment MUST be committed with tag `exp/N-description` before flashing
2. Photos should be saved to `firmware/docs/photos/expN_*.jpg`
3. Serial logs should be saved to `firmware/docs/logs/expN.txt`
4. The experiment log entry should reference the commit SHA and photo/log files

---

## Summary of Key Findings So Far

| Finding | Confidence | Evidence |
|---|---|---|
| Hardware is fine (panel, power, ESP32) | ✅ High | Exp #0 full-black test |
| SPI speed doesn't matter | ✅ High | Exp #5 |
| VCOM (0x82) has no effect in OTP mode | ✅ High | Exp #6 |
| Pixel polarity 1=black correct for DTM2 | ✅ High | Exp #0, #4 |
| 0=black convention at renderer helps contrast | ⚠️ Medium | Exp #10 darker but still gray |
| Glyph baseline bug was real, fix correct | ✅ High | Exp #9 |
| init_fast waveform mid-cycle reaches deep black | ⭐ High | Exp #12 photo evidence |
| init_fast settle phase washes to gray | ⭐ High | Exp #12, #13 |
| Pre-conditioning is NOT the main issue | ⚠️ Medium | Exp #13 same result without it |

## Experiment #14 — Standard Python init + clear-to-white + DTM1=previous
**Date:** 2026-03-25
**Tag:** `exp/14-standard-init-dirty`
**Changes:** Switched from init_fast() back to Python's exact standard init(). Kept 0=black convention + clear-to-white baseline + DTM1=previous(0xFF).
**Log:** 2 refreshes: clear_white_0x12 (3620ms) + content 0x12 (3620ms). No extra renders.
**Result:** Same "correct mid-cycle, washed final" pattern:
- Photo 1 (white): Clear-to-white baseline
- Photo 2 (correct): Deep black, product quality! Same as Exp #12.
- Photo 3 (black): Waveform intermediate phase — all black
- Photo 4 (gray): Final settle — washed gray with vertical banding
**User observed 5 phases during single 0x12:** white → correct image → black → correct image → gray settle
**Conclusion:** Standard waveform has SAME 4-phase behavior as init_fast. The settle phase washes in both modes. This is an OTP LUT characteristic, not specific to init_fast.
**Key insight:** The OTP LUT waveform has 4 internal phases: (A)drive-white → (B)drive-target → (C)drive-black → (D)drive-target-settle. Phase B shows correct image, Phase D overcorrects to gray. DTM1 is only valid for Phase B; by Phase D the panel state has changed and DTM1 no longer matches → wrong settle.

---

## Experiment #15 — Standard init + single refresh DTM1=~image (exact Python display())
**Date:** 2026-03-25
**Tag:** `exp/15-python-exact`
**Changes:** Removed clear-to-white baseline entirely. Single refresh: DTM1=~image, DTM2=image. Exact replication of Python's `display(getbuffer(image))` call.
**Log:** 1 refresh: "Frame mode: old=~image (first frame), new=image" → 3620ms
**Result:** Same 4-phase pattern within single refresh:
- Phase A: white screen
- Phase B: correct deep black (mirrored? — may be photo angle)
- Phase C: full black
- Phase D: washed gray with vertical banding
**Conclusion:** Even without pre-conditioning, the OTP LUT 4-phase waveform still washes the settle. Removing clear didn't help. This confirms the problem is in the LUT waveform itself, not in our clear/DTM1 strategy.

---

## Experiment #16 — Clear to BLACK + DTM1=0x00 (true match)
**Date:** 2026-03-25
**Changes:** clear_panel_once() drives to BLACK (DTM1=0xFF, DTM2=0x00). Then display with DTM1=previous_frame_=0x00 (matches actual black panel state).
**Theory:** After clear-to-black, DTM1=0x00 truly matches panel. LUT Phase D starts from all-black (Phase C) → DTM1=0x00 matches → correct settle.
**Result:** SAME pattern. Flash of correct, then gray settle.
**User's analysis:** The real issue is that (DTM1=0, DTM2=0) "black stays black" gets ZERO driving — the LUT applies no waveform for no-change pixels. Black areas stay at whatever gray state the clear left them in.
**Conclusion:** DTM1 matching isn't enough when (0,0) entries get zero driving.

---

## Experiment #17 — Clear to BLACK + force DTM1=~image
**Date:** 2026-03-25
**Changes:** After clear-to-black, set `previous_frame_valid_=false` to force display_bitmap to use DTM1=~image path. Combines clean baseline with full-transition driving.
**Result:** Same pattern — correct mid-cycle, gray final settle.
**Conclusion:** Clear + ~image combination doesn't fix it either. The LUT 4-phase waveform settle is the fundamental problem.

---

## Experiment #18a — CLEAN LUT TEST: Clear to WHITE + DTM1=0xFF (true state match)
**Date:** 2026-03-25
**Goal:** Isolate whether OTP LUT waveform ITSELF is broken when DTM1 perfectly matches actual panel state.
**Setup:**
1. Clear to white: DTM1=0x00, DTM2=0xFF → panel = all white (0xFF)
2. Display: DTM1=0xFF (matches panel exactly), DTM2=image
3. White pixels: (1,1) no-op → already white. Black pixels: (1,0) → full transition.
**Log:** 2 refreshes: clear_white_0x12 (3620ms) + content 0x12 (3620ms)
**Result:** SAME — correct mid-cycle, gray final settle. No improvement.
**Conclusion:** ⭐ **LUT waveform itself is the problem.** Even with DTM1 perfectly matching actual panel state, the 4-phase OTP waveform's settle phase washes the image to gray. This is NOT a DTM1/old-frame mismatch issue.

---

## ⭐ DEFINITIVE CONCLUSION (as of Exp #18a)

**Root cause: OTP LUT waveform settle phase overcorrects.**

Evidence chain:
1. Hardware works — Exp #0 full-black test produces deep black
2. Framebuffer data is correct — Exp #12/#14 show correct deep black mid-waveform
3. SPI transmission is correct — data reaches panel intact
4. DTM1 matching doesn't help — Exp #16/#18a with perfect DTM1 match still wash out
5. No extra refreshes — log confirms only intended 0x12 commands
6. The 4-phase waveform (white→target→black→settle) shows correct image in Phase B but overcorrects in Phase D

**The problem is inside the OTP LUT — the voltage/timing sequence burned into the panel.**

**Why Python on RPi works:** Unknown. Same OTP, same panel. Possible differences:
- RPi HAT power circuitry provides different voltage/current characteristics
- RPi SPI driver timing/buffering differs subtly
- RPi GPIO drive strength or edge timing affects waveform execution
- Temperature or environmental difference during testing

**Next directions:**
1. **External LUT mode** (0x00=0x3F instead of 0x1F) — bypass OTP, provide custom waveform tables
2. **Try on RPi with same panel** — verify Python still works, then compare SPI signals with logic analyzer
3. **Accept current contrast for V0** — focus on renderer parity and UX, revisit contrast later with hardware tools

---

## Experiment #19 — Host LUT path re-open (Issue #51 follow-up)
**Date:** 2026-03-30
**Branch:** `codex/51-pause-base`
**Goal:** Compare Waveshare official C/C++ host-LUT samples against current ESP32 path, then lock a pause baseline.

### What was compared
1. Raspberry Pi C (OTP path): `EPD_7in5_V2.c`
2. Raspberry Pi C old (host LUT path): `EPD_7in5_V2_old.c`
3. Arduino C++ host LUT sample: `epd7in5_V2.cpp`
4. ESP32 driver path: `firmware/main/platform/display.cpp`

### Key implementation updates in this round
1. Added explicit host-LUT init/profile path:
   - `0x00=0x3F`, `0x20..0x24` LUT upload, optional `0x2A`, `0x52`, `0x65`
2. Added explicit framebuffer/panel polarity mapping:
   - `kFramebufferBlackBitIsZero`, `kPanelBlackBitIsZero`, byte mapping helper
3. Added host-LUT tuning switches:
   - dual-plane write mode, preclean/boost passes, data interval and EVS params
4. Added trace and busy polling parity hooks:
   - optional `0x71` polling and command/data trace logs
5. UI readability adjustments:
   - footer/status rows use black-filled containers + inverted text in current UI pages

### Repeated observed behavior (user-verified)
1. Blank lines can remain clean white.
2. Rows containing text/button content show light gray wash in nearby white background.
3. OTP fallback test (`kUseHostLutWaveformProfile=false`) in this branch run produced overall white-wash behavior (not acceptable as pause baseline).
4. Small changes in `0x50/0x52` and preclean/boost did not materially remove the line-level gray artifact.

### Current pause baseline (kept in code)
1. `kUseHostLutWaveformProfile=true`
2. `kUseHostLutDualPlaneRefresh=true`
3. `kUseHostLutWhitePrecleanPass=false`
4. `0x50: 0x10, 0x07`
5. `0x52: 0x02`

### Practical conclusion for Issue #51
1. The remaining artifact is now a **drive-path / waveform quality** issue, not a page-layout bug.
2. Current baseline is intentionally frozen for now to avoid further churn.
3. Future work should be instrumented and isolated (single-variable + photo/log pairing) before reopening aggressive waveform tuning.
