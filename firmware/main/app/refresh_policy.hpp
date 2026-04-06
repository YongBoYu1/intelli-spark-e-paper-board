#pragma once

#include "app/state.hpp"
#include "platform/display.hpp"

#include <optional>
#include <string>
#include <vector>

namespace fridge_ink::app::refresh_policy {

using Rect = platform::DirtyRect;

enum class Mode {
  Slow,
  Balanced,
  Fast,
};

struct ModeParams {
  int min_refresh_gap_ms{120};
  double partial_area_limit{0.65};
  int default_full_refresh_every{10};
};

Mode parse_mode(const std::string& raw_mode);
const char* mode_name(Mode mode);
ModeParams mode_params(Mode mode);

double screen_partial_area_limit(Screen screen, Mode mode);
int effective_full_refresh_every(
    Screen screen,
    Mode mode,
    int ui_full_refresh_every,
    int timer_full_refresh_every_override = 0);

std::optional<Rect> clip_rect(const Rect& rect, int width, int height);
std::optional<Rect> align_rect_for_partial(const Rect& rect, int width, int height, int pad = 2);
std::optional<Rect> merge_rects(const std::vector<Rect>& rects, int width, int height);
double rect_area_ratio(const Rect& rect, int width, int height);
bool rect_contains(const Rect& outer, const Rect& inner, int slack = 0);

std::vector<Rect> prepare_partial_rects(
    const std::vector<Rect>& rects,
    int width,
    int height,
    int pad,
    int max_rects,
    bool merge_overflow = true);
double partial_gate_area_ratio(const std::vector<Rect>& rects, int width, int height);

struct RefreshPolicyRuntime {
  int partial_count{0};
  double last_refresh_ts{0.0};
  double last_full_refresh_ts{0.0};
  std::vector<Rect> pending_dirty_rects{};

  void enqueue(const std::vector<Rect>& rects);
  void clear_pending();
  void mark_partial(double now_s);
  void mark_fast_full(double now_s);
  void mark_full_clean(double now_s);
  bool should_throttle(double now_s, int min_refresh_gap_ms) const;
  std::string full_clean_reason(
      double now_s,
      int full_refresh_every,
      double max_full_age_s = 24.0 * 60.0 * 60.0) const;
};

}  // namespace fridge_ink::app::refresh_policy
