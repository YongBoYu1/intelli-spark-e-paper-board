#include "app/refresh_policy.hpp"

#include <algorithm>
#include <cctype>
#include <cmath>

namespace fridge_ink::app::refresh_policy {
namespace {

bool rect_less_for_debug(const Rect& lhs, const Rect& rhs) {
  const int lhs_area = std::max(0, lhs.x1 - lhs.x0) * std::max(0, lhs.y1 - lhs.y0);
  const int rhs_area = std::max(0, rhs.x1 - rhs.x0) * std::max(0, rhs.y1 - rhs.y0);
  if (lhs.y0 != rhs.y0) {
    return lhs.y0 < rhs.y0;
  }
  if (lhs.x0 != rhs.x0) {
    return lhs.x0 < rhs.x0;
  }
  return lhs_area < rhs_area;
}

}  // namespace

Mode parse_mode(const std::string& raw_mode) {
  std::string normalized = raw_mode;
  std::transform(
      normalized.begin(),
      normalized.end(),
      normalized.begin(),
      [](unsigned char ch) { return static_cast<char>(std::tolower(ch)); });
  if (normalized == "slow") {
    return Mode::Slow;
  }
  if (normalized == "fast") {
    return Mode::Fast;
  }
  return Mode::Balanced;
}

const char* mode_name(const Mode mode) {
  switch (mode) {
    case Mode::Slow:
      return "slow";
    case Mode::Balanced:
      return "balanced";
    case Mode::Fast:
      return "fast";
  }
  return "balanced";
}

ModeParams mode_params(const Mode mode) {
  switch (mode) {
    case Mode::Slow:
      return ModeParams{200, 0.40, 5};
    case Mode::Fast:
      return ModeParams{80, 0.85, 15};
    case Mode::Balanced:
      break;
  }
  return ModeParams{120, 0.65, 10};
}

double screen_partial_area_limit(const Screen screen, const Mode mode) {
  const double base = mode_params(mode).partial_area_limit;
  switch (screen) {
    case Screen::Landing:
    case Screen::Onboarding:
      return std::max(0.70, std::min(base + 0.20, 0.92));
    case Screen::Timer:
      return std::min(0.95, base + 0.20);
    case Screen::Inventory:
      return std::max(0.60, std::min(base + 0.15, 0.80));
    case Screen::Menu:
    case Screen::Memo:
      return std::max(0.30, std::min(base, 0.55));
    case Screen::Calendar:
      return std::max(0.58, std::min(base + 0.15, 0.82));
    case Screen::Weather:
      return std::max(0.50, std::min(base, 0.78));
    case Screen::Home:
      return std::max(0.12, std::min(base, 0.22));
    case Screen::Settings:
      return base;
  }
  return base;
}

int effective_full_refresh_every(
    const Screen screen,
    const Mode mode,
    const int ui_full_refresh_every,
    const int timer_full_refresh_every_override) {
  int value = ui_full_refresh_every;
  if (value <= 0) {
    value = mode_params(mode).default_full_refresh_every;
  }
  if (screen == Screen::Timer && timer_full_refresh_every_override > 0) {
    value = std::max(value, timer_full_refresh_every_override);
  }
  return std::max(1, value);
}

std::optional<Rect> clip_rect(const Rect& rect, const int width, const int height) {
  Rect out{
      std::max(0, std::min(width, rect.x0)),
      std::max(0, std::min(height, rect.y0)),
      std::max(0, std::min(width, rect.x1)),
      std::max(0, std::min(height, rect.y1)),
  };
  if (out.x1 <= out.x0 || out.y1 <= out.y0) {
    return std::nullopt;
  }
  return out;
}

std::optional<Rect> align_rect_for_partial(
    const Rect& rect,
    const int width,
    const int height,
    const int pad) {
  Rect expanded{
      rect.x0 - pad,
      rect.y0 - pad,
      rect.x1 + pad,
      rect.y1 + pad,
  };
  auto clipped = clip_rect(expanded, width, height);
  if (!clipped.has_value()) {
    return std::nullopt;
  }
  Rect aligned = clipped.value();
  aligned.x0 = (aligned.x0 / 8) * 8;
  aligned.x1 = ((aligned.x1 + 7) / 8) * 8;
  aligned.x1 = std::max(aligned.x0 + 8, std::min(width, aligned.x1));
  return clip_rect(aligned, width, height);
}

std::optional<Rect> merge_rects(const std::vector<Rect>& rects, const int width, const int height) {
  std::optional<Rect> merged = std::nullopt;
  for (const Rect& rect : rects) {
    auto clipped = clip_rect(rect, width, height);
    if (!clipped.has_value()) {
      continue;
    }
    if (!merged.has_value()) {
      merged = clipped;
      continue;
    }
    merged->x0 = std::min(merged->x0, clipped->x0);
    merged->y0 = std::min(merged->y0, clipped->y0);
    merged->x1 = std::max(merged->x1, clipped->x1);
    merged->y1 = std::max(merged->y1, clipped->y1);
  }
  return merged;
}

double rect_area_ratio(const Rect& rect, const int width, const int height) {
  const int area = std::max(0, rect.x1 - rect.x0) * std::max(0, rect.y1 - rect.y0);
  const int total = std::max(1, width * height);
  return static_cast<double>(area) / static_cast<double>(total);
}

bool rect_contains(const Rect& outer, const Rect& inner, const int slack) {
  return inner.x0 >= (outer.x0 - slack) &&
         inner.y0 >= (outer.y0 - slack) &&
         inner.x1 <= (outer.x1 + slack) &&
         inner.y1 <= (outer.y1 + slack);
}

std::vector<Rect> prepare_partial_rects(
    const std::vector<Rect>& rects,
    const int width,
    const int height,
    const int pad,
    const int max_rects,
    const bool merge_overflow) {
  std::vector<Rect> aligned{};
  aligned.reserve(rects.size());
  for (const Rect& rect : rects) {
    auto maybe_rect = align_rect_for_partial(rect, width, height, pad);
    if (!maybe_rect.has_value()) {
      continue;
    }
    const Rect clipped = maybe_rect.value();
    bool covered = false;
    for (const Rect& existing : aligned) {
      if (rect_contains(existing, clipped, 0)) {
        covered = true;
        break;
      }
    }
    if (covered) {
      continue;
    }
    std::vector<Rect> next_aligned{};
    next_aligned.reserve(aligned.size() + 1);
    for (const Rect& existing : aligned) {
      if (!rect_contains(clipped, existing, 0)) {
        next_aligned.push_back(existing);
      }
    }
    next_aligned.push_back(clipped);
    aligned.swap(next_aligned);
  }

  if (aligned.empty()) {
    return {};
  }

  std::sort(aligned.begin(), aligned.end(), rect_less_for_debug);

  const int max_count = std::max(1, max_rects);
  if (static_cast<int>(aligned.size()) <= max_count) {
    return aligned;
  }

  if (!merge_overflow) {
    aligned.resize(static_cast<std::size_t>(max_count));
    return aligned;
  }

  auto merged = merge_rects(aligned, width, height);
  if (!merged.has_value()) {
    return {};
  }
  return {merged.value()};
}

double partial_gate_area_ratio(const std::vector<Rect>& rects, const int width, const int height) {
  if (rects.empty()) {
    return 1.0;
  }
  double ratio = 0.0;
  for (const Rect& rect : rects) {
    ratio += rect_area_ratio(rect, width, height);
  }
  return std::min(1.0, ratio);
}

void RefreshPolicyRuntime::enqueue(const std::vector<Rect>& rects) {
  for (const Rect& rect : rects) {
    pending_dirty_rects.push_back(rect);
  }
}

void RefreshPolicyRuntime::clear_pending() {
  pending_dirty_rects.clear();
}

void RefreshPolicyRuntime::mark_partial(const double now_s) {
  partial_count += 1;
  last_refresh_ts = now_s;
}

void RefreshPolicyRuntime::mark_fast_full(const double now_s) {
  partial_count = 0;
  last_refresh_ts = now_s;
}

void RefreshPolicyRuntime::mark_full_clean(const double now_s) {
  partial_count = 0;
  last_refresh_ts = now_s;
  last_full_refresh_ts = now_s;
}

bool RefreshPolicyRuntime::should_throttle(const double now_s, const int min_refresh_gap_ms) const {
  const int gap_ms = std::max(0, min_refresh_gap_ms);
  if (gap_ms <= 0 || last_refresh_ts <= 0.0) {
    return false;
  }
  return (now_s - last_refresh_ts) < (static_cast<double>(gap_ms) / 1000.0);
}

std::string RefreshPolicyRuntime::full_clean_reason(
    const double now_s,
    const int full_refresh_every,
    const double max_full_age_s) const {
  if (full_refresh_every > 0 && partial_count >= full_refresh_every) {
    return "partial_budget";
  }
  if (last_full_refresh_ts > 0.0 && (now_s - last_full_refresh_ts) >= max_full_age_s) {
    return "full_age";
  }
  return {};
}

}  // namespace fridge_ink::app::refresh_policy
