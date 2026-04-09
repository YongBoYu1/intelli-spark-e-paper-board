#include "app/runtime.hpp"

#include "app/calendar_runtime.hpp"
#include "app/defaults.hpp"
#include "app/reducer.hpp"
#include "platform/clock.hpp"
#include "platform/display.hpp"
#include "platform/panel_config.hpp"
#include "ui/render_app.hpp"
#include "ui/screens/home_screen.hpp"

#include "esp_log.h"

#include <algorithm>
#include <cctype>
#include <sstream>
#include <unordered_set>
#include <utility>

namespace fridge_ink::app {
namespace {

constexpr const char* kTag = "runtime";
constexpr int kPartialPad = 2;
constexpr int kPartialMaxRects = 6;
constexpr bool kRefreshDebugLogs = true;
constexpr double kDiffFallbackMinRatio = 0.10;
constexpr int kHomeNavigationMinRefreshGapMs = 70;
constexpr int kMemoNavigationMinRefreshGapMs = 35;
constexpr double kMemoFocusMoveAreaLimitOverride = 0.75;
constexpr double kHomeFamilyAreaLimitOverride = 0.30;
constexpr double kHomeMenuOverlayAreaLimitOverride = 0.60;
constexpr double kHomeReminderReorderAreaLimitOverride = 0.30;
constexpr double kHomeReminderCompactAreaLimitOverride = 0.40;
constexpr double kHomeFocusMoveLeftTargetAreaLimitOverride = 0.35;
constexpr double kHomeFocusCrossPanelAreaLimitOverride = 0.35;
constexpr bool kReinforceHomeFocusMoveLeftTargetPass = false;

struct CalendarLandscapeRegions {
  platform::DirtyRect left_panel{};
  platform::DirtyRect left_grid{};
  platform::DirtyRect right_panel{};
  platform::DirtyRect right_header{};
  platform::DirtyRect right_agenda{};
};

struct CalendarPortraitRegions {
  platform::DirtyRect top_panel{};
  platform::DirtyRect top_grid{};
  platform::DirtyRect bottom_panel{};
  platform::DirtyRect bottom_header{};
  platform::DirtyRect bottom_agenda{};
};

int normalize_rotation_deg(const int raw) {
  const int rounded = ((raw % 360) + 360) % 360;
  if (rounded >= 315 || rounded < 45) {
    return 0;
  }
  if (rounded < 135) {
    return 90;
  }
  if (rounded < 225) {
    return 180;
  }
  return 270;
}

bool calendar_uses_landscape_layout(const AppState& state) {
  const int deg = normalize_rotation_deg(state.settings.rotation_deg);
  return !(deg == 90 || deg == 270);
}

std::string normalized_calendar_mode(const std::string& raw) {
  std::string out;
  out.reserve(raw.size());
  for (const char ch : raw) {
    out.push_back(static_cast<char>(std::tolower(static_cast<unsigned char>(ch))));
  }
  return out == "agenda" ? "agenda" : "date";
}

CalendarLandscapeRegions calendar_landscape_regions() {
  const int w = platform::kPanelWidth;
  const int h = platform::kPanelHeight;
  const int right_x = std::max(1, std::min(w - 1, static_cast<int>(w * 0.45)));
  return CalendarLandscapeRegions{
      {0, 0, right_x, h},
      {24, 120, std::max(25, right_x - 20), std::max(121, h - 46)},
      {right_x, 0, w, h},
      {right_x, 0, w, 90},
      {right_x, 90, w, h},
  };
}

platform::DirtyRect calendar_map_portrait_semantic_rect(
    const int x0,
    const int y0,
    const int x1,
    const int y1,
    const bool r90) {
  const int cx0 = std::max(0, std::min(480, x0));
  const int cy0 = std::max(0, std::min(800, y0));
  const int cx1 = std::max(0, std::min(480, x1));
  const int cy1 = std::max(0, std::min(800, y1));
  if (cx1 <= cx0 || cy1 <= cy0) {
    return platform::DirtyRect{0, 0, 0, 0};
  }
  if (r90) {
    return platform::DirtyRect{
        cy0,
        480 - cx1,
        cy1,
        480 - cx0,
    };
  }
  return platform::DirtyRect{
      800 - cy1,
      cx0,
      800 - cy0,
      cx1,
  };
}

CalendarPortraitRegions calendar_portrait_regions(const AppState& state) {
  const bool r90 = normalize_rotation_deg(state.settings.rotation_deg) == 90;
  const int split_y = std::max(260, std::min(800 - 220, 800 / 2));
  const int header_y = split_y + 12;
  const int list_top = header_y + 64;
  return CalendarPortraitRegions{
      calendar_map_portrait_semantic_rect(0, 0, 480, split_y + 4, r90),
      calendar_map_portrait_semantic_rect(20, 96, 460, std::max(97, split_y - 8), r90),
      calendar_map_portrait_semantic_rect(0, split_y, 480, 800, r90),
      calendar_map_portrait_semantic_rect(18, split_y + 6, 462, std::min(800, header_y + 58), r90),
      calendar_map_portrait_semantic_rect(12, std::max(0, list_top - 2), 468, 800, r90),
  };
}

bool memo_uses_portrait_layout(const AppState& state) {
  const int deg = normalize_rotation_deg(state.settings.rotation_deg);
  return deg == 90 || deg == 270;
}

int normalized_memo_index(const int index, const int total) {
  if (total <= 0) {
    return 0;
  }
  int normalized = index % total;
  if (normalized < 0) {
    normalized += total;
  }
  return normalized;
}

int normalized_memo_index(const AppState& state) {
  return normalized_memo_index(
      state.memo.index,
      static_cast<int>(state.dashboard.memos.size()));
}

std::uint64_t memo_digest(const AppState& state) {
  std::uint64_t hash = 1469598103934665603ULL;
  auto mix = [&](const char byte) {
    hash ^= static_cast<std::uint64_t>(static_cast<unsigned char>(byte));
    hash *= 1099511628211ULL;
  };
  auto mix_text = [&](const std::string& text) {
    for (const char ch : text) {
      mix(ch);
    }
    mix('\0');
  };
  for (const auto& memo : state.dashboard.memos) {
    mix_text(memo.text);
    mix_text(memo.author);
    mix_text(memo.posted);
    mix(memo.is_new ? '\x01' : '\x00');
  }
  return hash;
}

platform::DirtyRect memo_transform_source_rect(
    const AppState& state,
    const int x0,
    const int y0,
    const int x1,
    const int y1) {
  const bool portrait = memo_uses_portrait_layout(state);
  const int src_w = portrait ? 480 : platform::kPanelWidth;
  const int src_h = portrait ? 800 : platform::kPanelHeight;
  const int cx0 = std::max(0, std::min(src_w, x0));
  const int cy0 = std::max(0, std::min(src_h, y0));
  const int cx1 = std::max(0, std::min(src_w, x1));
  const int cy1 = std::max(0, std::min(src_h, y1));
  if (cx1 <= cx0 || cy1 <= cy0) {
    return platform::DirtyRect{0, 0, 0, 0};
  }
  if (!portrait) {
    return platform::DirtyRect{cx0, cy0, cx1, cy1};
  }
  const bool r90 = normalize_rotation_deg(state.settings.rotation_deg) == 90;
  if (r90) {
    return platform::DirtyRect{
        cy0,
        480 - cx1,
        cy1,
        480 - cx0,
    };
  }
  return platform::DirtyRect{
      800 - cy1,
      cx0,
      800 - cy0,
      cx1,
  };
}

platform::DirtyRect memo_card_rect(const AppState& state) {
  const bool portrait = memo_uses_portrait_layout(state);
  const int src_w = portrait ? 480 : platform::kPanelWidth;
  const int src_h = portrait ? 800 : platform::kPanelHeight;
  return memo_transform_source_rect(
      state,
      20,
      80,
      std::max(21, src_w - 20),
      std::max(80, src_h - 60));
}

platform::DirtyRect memo_summary_rect(const AppState& state) {
  const bool portrait = memo_uses_portrait_layout(state);
  const int src_w = portrait ? 480 : platform::kPanelWidth;
  const int src_h = portrait ? 800 : platform::kPanelHeight;
  const int outer_x0 = 24;
  const int outer_x1 = std::max(outer_x0 + 1, src_w - 24);
  const int inner_x0 = outer_x0 + 4;
  const int inner_x1 = std::max(inner_x0 + 1, outer_x1 - 4);
  const int inner_y0 = 86;
  return memo_transform_source_rect(
      state,
      inner_x0,
      std::max(0, inner_y0 - 2),
      inner_x1,
      std::min(src_h, inner_y0 + 20));
}

platform::DirtyRect memo_focus_row_rect(
    const AppState& state,
    const int memo_index,
    const int memo_total) {
  if (memo_total <= 0) {
    return platform::DirtyRect{0, 0, 0, 0};
  }
  const bool portrait = memo_uses_portrait_layout(state);
  const int src_w = portrait ? 480 : platform::kPanelWidth;
  const int src_h = portrait ? 800 : platform::kPanelHeight;
  const int outer_x0 = 24;
  const int outer_x1 = std::max(outer_x0 + 1, src_w - 24);
  const int inner_x0 = outer_x0 + 4;
  const int inner_x1 = std::max(inner_x0 + 1, outer_x1 - 4);
  const int inner_y0 = 86;
  const int inner_y1 = std::max(inner_y0 + 1, src_h - 56);
  constexpr int kListGap = 6;
  constexpr int kRowHeight = 66;
  const int list_top = inner_y0 + 22;
  const int list_h = std::max(1, inner_y1 - list_top);
  const int slots = std::max(1, (list_h + kListGap) / (kRowHeight + kListGap));
  const int selected = normalized_memo_index(memo_index, memo_total);
  const int start = std::max(0, std::min(selected - (slots / 2), memo_total - slots));
  const int visible_row = std::max(0, selected - start);
  const int row_y0 = list_top + visible_row * (kRowHeight + kListGap);
  const int row_y1 = std::min(inner_y1, row_y0 + kRowHeight);
  return memo_transform_source_rect(
      state,
      inner_x0,
      std::max(0, row_y0 - 4),
      inner_x1,
      std::min(src_h, row_y1 + 4));
}

bool rect_equal(const platform::DirtyRect& lhs, const platform::DirtyRect& rhs) {
  return lhs.x0 == rhs.x0 &&
         lhs.y0 == rhs.y0 &&
         lhs.x1 == rhs.x1 &&
         lhs.y1 == rhs.y1;
}

void add_reason_once(
    std::vector<std::string>& reasons,
    const char* reason) {
  if (reason == nullptr) {
    return;
  }
  for (const auto& item : reasons) {
    if (item == reason) {
      return;
    }
  }
  reasons.emplace_back(reason);
}

void add_rect_once(
    std::vector<platform::DirtyRect>& rects,
    const platform::DirtyRect rect) {
  if (rect.x1 <= rect.x0 || rect.y1 <= rect.y0) {
    return;
  }
  for (const auto& item : rects) {
    if (item.x0 == rect.x0 && item.y0 == rect.y0 &&
        item.x1 == rect.x1 && item.y1 == rect.y1) {
      return;
    }
  }
  rects.push_back(rect);
}

bool timer_uses_portrait_layout(const AppState& state) {
  const int deg = normalize_rotation_deg(state.settings.rotation_deg);
  return deg == 90 || deg == 270;
}

// Maps a portrait semantic rect (cx in [0,480), cy in [0,800)) to the
// physical 800×480 buffer rect used for partial-update dirty regions.
// r90:  physical x = cy range, physical y = [480-x1, 480-x0)
// r270: physical x = [800-y1, 800-y0), physical y = cx range
platform::DirtyRect timer_map_portrait_rect(
    const int x0, const int y0, const int x1, const int y1, const bool r90) {
  if (r90) {
    return platform::DirtyRect{
        y0,
        std::max(0, 480 - x1),
        std::min(platform::kPanelWidth, y1),
        std::min(platform::kPanelHeight, 480 - x0),
    };
  }
  return platform::DirtyRect{
      std::max(0, 800 - y1),
      x0,
      std::min(platform::kPanelWidth, 800 - y0),
      std::min(platform::kPanelHeight, x1),
  };
}

// Portrait dirty rect sizing rationale:
// partial_gate_area_ratio() sums individual rect areas. Timer partial limit =
// min(0.95, base+0.20) = 0.85. Landscape rects sum to ~76% — safe. Portrait
// naive mapping (full semantic width x=[0,480)) produces y=[0,480) in physical
// space (full panel height), making each rect span the full physical height and
// pushing the sum to ~92% — over the 85% gate.
//
// Fix: restrict semantic x to [kMargin=24, kPW-kMargin=456] and tighten y.
// This maps physical y to [24, 456] (not [0, 480]), reducing each rect by ~10%
// and keeping the combined ratio comfortably under 0.85.
//
// Semantic layout reference (kPW=480, kPH=800):
//   content area top : y=82  (below divider)
//   controls_y       : y=710 (= kPH - kButtonBottomGap = 800 - 90)
//   controls bottom  : y=772 (= controls_y + kButtonHeight + 2px margin = 710 + 60 + 2)
//   margin x         : [24, 456]
platform::DirtyRect timer_time_status_rect(const AppState& state) {
  if (timer_uses_portrait_layout(state)) {
    const bool r90 = normalize_rotation_deg(state.settings.rotation_deg) == 90;
    // Tight semantic rect: x=[24,456], y=[82,710] — covers time + status,
    // stops at controls_y. Physical area ratio: 632×432/384k ≈ 71%.
    return timer_map_portrait_rect(24, 82, 456, 710, r90);
  }
  return platform::DirtyRect{
      56,
      82,
      std::max(57, platform::kPanelWidth - 56),
      std::max(83, platform::kPanelHeight - 84),
  };
}

platform::DirtyRect timer_controls_rect(const AppState& state) {
  if (timer_uses_portrait_layout(state)) {
    const bool r90 = normalize_rotation_deg(state.settings.rotation_deg) == 90;
    // Tight semantic rect: x=[24,456], y=[710,772] — covers button row only.
    // Physical area ratio: 62×432/384k ≈ 0.7%.
    return timer_map_portrait_rect(24, 710, 456, 772, r90);
  }
  return platform::DirtyRect{
      24,
      std::max(0, platform::kPanelHeight - 100),
      std::max(25, platform::kPanelWidth - 24),
      platform::kPanelHeight,
  };
}

bool should_collapse_to_latest(
    const Screen screen,
    const std::vector<std::string>& reasons) {
  if (reasons.empty()) {
    return false;
  }

  if (screen == Screen::Home) {
    static const std::unordered_set<std::string> kAllowedReasons = {
        "home.focus_move_row",
        "home.focus_move_left_target",
        "home.focus_to_left_panel",
        "home.focus_from_left_panel",
        "home.focus_left_panel_only",
        "home.menu_overlay_focus",
        "home.focus_priority_drop_family",
        "diff_fallback",
    };
    bool has_focus_reason = false;
    for (const auto& reason : reasons) {
      if (reason.rfind("home.focus_", 0) == 0 || reason == "home.menu_overlay_focus") {
        has_focus_reason = true;
      }
      if (kAllowedReasons.find(reason) == kAllowedReasons.end()) {
        return false;
      }
    }
    return has_focus_reason;
  }

  if (screen == Screen::Memo) {
    static const std::unordered_set<std::string> kAllowedReasons = {
        "memo.focus_move",
        "diff_fallback",
    };
    bool has_focus_reason = false;
    for (const auto& reason : reasons) {
      if (reason == "memo.focus_move") {
        has_focus_reason = true;
      }
      if (kAllowedReasons.find(reason) == kAllowedReasons.end()) {
        return false;
      }
    }
    return has_focus_reason;
  }

  return false;
}

bool has_reason(
    const std::vector<std::string>& reasons,
    const char* reason) {
  if (reason == nullptr) {
    return false;
  }
  for (const auto& item : reasons) {
    if (item == reason) {
      return true;
    }
  }
  return false;
}

bool has_reason_prefix(
    const std::vector<std::string>& reasons,
    const char* prefix) {
  if (prefix == nullptr || prefix[0] == '\0') {
    return false;
  }
  for (const auto& item : reasons) {
    if (item.rfind(prefix, 0) == 0) {
      return true;
    }
  }
  return false;
}

bool has_any_reason(
    const std::vector<std::string>& reasons,
    std::initializer_list<const char*> needles) {
  for (const char* needle : needles) {
    if (has_reason(reasons, needle)) {
      return true;
    }
  }
  return false;
}

void reorder_home_transition_rects_for_partial(
    const std::vector<std::string>& reasons,
    std::vector<platform::DirtyRect>& rects) {
  if (rects.size() < 2U) {
    return;
  }
  if (has_reason(reasons, "home.focus_to_left_panel")) {
    // Row -> left-panel: refresh right-side old focus region first so stale row
    // frame does not linger while left panel rect is being refreshed.
    std::stable_sort(rects.begin(), rects.end(), [](const auto& a, const auto& b) {
      return a.x0 > b.x0;
    });
    return;
  }
  if (has_reason(reasons, "home.focus_from_left_panel")) {
    // Left-panel -> row: clear previous left focus first, then apply new row.
    std::stable_sort(rects.begin(), rects.end(), [](const auto& a, const auto& b) {
      return a.x0 < b.x0;
    });
  }
}

void reorder_calendar_transition_rects_for_partial(
    const std::vector<std::string>& reasons,
    std::vector<platform::DirtyRect>& rects,
    const bool landscape_layout,
    const bool r90) {
  if (rects.size() < 2U) {
    return;
  }
  if (!has_reason(reasons, "calendar.cursor_move")) {
    return;
  }

  if (landscape_layout) {
    // Landscape: calendar grid on the left, agenda on the right.
    std::stable_sort(rects.begin(), rects.end(), [](const auto& a, const auto& b) {
      return a.x0 < b.x0;
    });
    return;
  }

  // Portrait semantic mapping:
  // - r90: top panel maps to smaller physical x.
  // - r270: top panel maps to larger physical x.
  if (r90) {
    std::stable_sort(rects.begin(), rects.end(), [](const auto& a, const auto& b) {
      return a.x0 < b.x0;
    });
  } else {
    std::stable_sort(rects.begin(), rects.end(), [](const auto& a, const auto& b) {
      return a.x0 > b.x0;
    });
  }
}

int covering_rect_index(
    const std::vector<platform::DirtyRect>& rects,
    const platform::DirtyRect& target) {
  if (target.x1 <= target.x0 || target.y1 <= target.y0) {
    return -1;
  }
  for (std::size_t i = 0; i < rects.size(); ++i) {
    if (refresh_policy::rect_contains(rects[i], target, 2)) {
      return static_cast<int>(i);
    }
  }
  return -1;
}

void reorder_memo_transition_rects_for_partial(
    const std::vector<std::string>& reasons,
    std::vector<platform::DirtyRect>& rects,
    const platform::DirtyRect& previous_row,
    const platform::DirtyRect& current_row) {
  if (rects.size() < 2U || !has_reason(reasons, "memo.focus_move")) {
    return;
  }

  const int previous_index = covering_rect_index(rects, previous_row);
  if (previous_index > 0) {
    std::swap(rects[0], rects[static_cast<std::size_t>(previous_index)]);
  }

  const int current_index = covering_rect_index(rects, current_row);
  if (current_index > 1) {
    std::swap(rects[1], rects[static_cast<std::size_t>(current_index)]);
  }
}

}  // namespace

Runtime::Runtime(platform::Display& display) : display_(display) {}

void Runtime::boot() {
  const std::uint64_t now_ms = platform::monotonic_ms();
  const auto defaults = make_factory_defaults();
  state_ = make_state_from_defaults(defaults, now_ms);
  platform::apply_timezone(state_.onboarding.timezone);
  display_.init();
  stage_render();
  flush_pending(now_ms);
}

void Runtime::dispatch(const Event& event) {
  Event effective = event;
  if (effective.now_ms == 0) {
    effective.now_ms = platform::monotonic_ms();
  }
  reduce(state_, effective);
  platform::apply_timezone(state_.onboarding.timezone);
  stage_render();
  flush_pending(effective.now_ms);
}

void Runtime::flush_deferred(const std::uint64_t now_ms) {
  flush_pending(now_ms);
}

void Runtime::stage_render() {
  const ui::HomeDirtySnapshot* previous_home_snapshot = nullptr;
  if (state_.screen == Screen::Home &&
      committed_screen_ == Screen::Home &&
      committed_home_snapshot_valid_) {
    previous_home_snapshot = &committed_home_snapshot_;
  }

  ui::RenderOutput render_output = ui::render_app(state_, previous_home_snapshot);
  if (render_output.image.empty()) {
    return;
  }

  if (state_.screen == Screen::Timer &&
      committed_screen_ == Screen::Timer &&
      committed_timer_snapshot_valid_) {
    if (committed_timer_focused_index_ != state_.timer.focused_index) {
      add_rect_once(render_output.dirty_rects, timer_controls_rect(state_));
      add_reason_once(render_output.dirty_reasons, "timer.focus_move");
    }
    if (committed_timer_seconds_ != state_.timer.seconds_remaining ||
        committed_timer_running_ != state_.timer.running ||
        committed_timer_alert_active_ != state_.timer.alert_active ||
        committed_timer_alert_blink_on_ != state_.timer.alert_blink_on ||
        committed_timer_last_completed_seconds_ != state_.timer.last_completed_seconds ||
        committed_timer_widget_mode_ != state_.home.widget_mode) {
      add_rect_once(render_output.dirty_rects, timer_time_status_rect(state_));
      if (committed_timer_running_ != state_.timer.running) {
        add_rect_once(render_output.dirty_rects, timer_controls_rect(state_));
      }
      add_reason_once(render_output.dirty_reasons, "timer.time_or_state");
    }
  }

  if (state_.screen == Screen::Calendar) {
    const bool landscape_layout = calendar_uses_landscape_layout(state_);
    const CalendarLandscapeRegions landscape_regions = calendar_landscape_regions();
    const CalendarPortraitRegions portrait_regions = calendar_portrait_regions(state_);
    if (!committed_frame_valid_ || committed_screen_ != Screen::Calendar) {
      if (landscape_layout) {
        add_rect_once(render_output.dirty_rects, landscape_regions.left_panel);
        add_rect_once(render_output.dirty_rects, landscape_regions.right_panel);
      } else {
        add_rect_once(render_output.dirty_rects, portrait_regions.top_panel);
        add_rect_once(render_output.dirty_rects, portrait_regions.bottom_panel);
      }
    } else if (
        committed_calendar_snapshot_valid_ &&
        committed_calendar_landscape_ == landscape_layout) {
      const auto base_date = calendar_runtime::today_local_date(state_);
      const auto cursor = calendar_runtime::cursor_date(state_, base_date);
      const int curr_offset = state_.calendar.offset_days;
      const std::string curr_mode = normalized_calendar_mode(state_.calendar.mode);
      const int curr_selected = std::max(0, state_.calendar.selected_index);
      const std::uint64_t curr_calendar_digest = calendar_runtime::calendar_events_digest(state_);
      const std::uint64_t curr_reminders_digest = calendar_runtime::reminders_calendar_digest(state_);

      const bool offset_changed = committed_calendar_offset_days_ != curr_offset;
      const bool mode_changed = committed_calendar_mode_ != curr_mode;
      const bool data_changed =
          committed_calendar_events_digest_ != curr_calendar_digest ||
          committed_calendar_reminders_digest_ != curr_reminders_digest;

      if (offset_changed || mode_changed || data_changed) {
        if (landscape_layout) {
          if (offset_changed) {
            if (committed_calendar_cursor_year_ != cursor.year ||
                committed_calendar_cursor_month_ != cursor.month) {
              add_rect_once(render_output.dirty_rects, landscape_regions.left_panel);
            } else {
              add_rect_once(render_output.dirty_rects, landscape_regions.left_grid);
            }
            add_rect_once(render_output.dirty_rects, landscape_regions.right_header);
            add_rect_once(render_output.dirty_rects, landscape_regions.right_agenda);
          } else if (mode_changed) {
            add_rect_once(render_output.dirty_rects, landscape_regions.right_header);
            add_rect_once(render_output.dirty_rects, landscape_regions.right_agenda);
          } else {
            add_rect_once(render_output.dirty_rects, landscape_regions.left_grid);
            add_rect_once(render_output.dirty_rects, landscape_regions.right_agenda);
          }
        } else {
          if (offset_changed) {
            if (committed_calendar_cursor_year_ != cursor.year ||
                committed_calendar_cursor_month_ != cursor.month) {
              add_rect_once(render_output.dirty_rects, portrait_regions.top_panel);
            } else {
              add_rect_once(render_output.dirty_rects, portrait_regions.top_grid);
            }
            add_rect_once(render_output.dirty_rects, portrait_regions.bottom_header);
            add_rect_once(render_output.dirty_rects, portrait_regions.bottom_agenda);
          } else if (mode_changed) {
            add_rect_once(render_output.dirty_rects, portrait_regions.bottom_agenda);
          } else {
            add_rect_once(render_output.dirty_rects, portrait_regions.top_grid);
            add_rect_once(render_output.dirty_rects, portrait_regions.bottom_agenda);
          }
        }
        if (offset_changed) {
          add_reason_once(render_output.dirty_reasons, "calendar.cursor_move");
        }
        add_reason_once(render_output.dirty_reasons, "calendar.date_or_mode_or_data");
      } else if (committed_calendar_selected_index_ != curr_selected) {
        if (landscape_layout) {
          add_rect_once(render_output.dirty_rects, landscape_regions.right_agenda);
        } else {
          add_rect_once(render_output.dirty_rects, portrait_regions.bottom_agenda);
        }
        add_reason_once(render_output.dirty_reasons, "calendar.agenda_focus_move");
      }
    } else if (committed_calendar_snapshot_valid_) {
      if (landscape_layout) {
        add_rect_once(render_output.dirty_rects, landscape_regions.left_panel);
        add_rect_once(render_output.dirty_rects, landscape_regions.right_panel);
      } else {
        add_rect_once(render_output.dirty_rects, portrait_regions.top_panel);
        add_rect_once(render_output.dirty_rects, portrait_regions.bottom_panel);
      }
      add_reason_once(render_output.dirty_reasons, "calendar.layout_change");
    }
  }

  if (state_.screen == Screen::Memo) {
    const int memo_count = static_cast<int>(state_.dashboard.memos.size());
    const int memo_index = normalized_memo_index(state_);
    const bool memo_expanded = state_.memo.expanded;
    const std::uint64_t current_memo_digest = memo_digest(state_);
    const int rotation_deg = normalize_rotation_deg(state_.settings.rotation_deg);

    if (!committed_frame_valid_ || committed_screen_ != Screen::Memo) {
      add_rect_once(render_output.dirty_rects, memo_card_rect(state_));
    } else if (
        committed_memo_snapshot_valid_ &&
        committed_memo_rotation_deg_ == rotation_deg) {
      if (committed_memo_index_ != memo_index) {
        add_rect_once(render_output.dirty_rects, memo_summary_rect(state_));
        const platform::DirtyRect previous_row =
            memo_focus_row_rect(state_, committed_memo_index_, committed_memo_count_);
        const platform::DirtyRect current_row =
            memo_focus_row_rect(state_, memo_index, memo_count);
        add_rect_once(render_output.dirty_rects, previous_row);
        if (!rect_equal(current_row, previous_row)) {
          add_rect_once(render_output.dirty_rects, current_row);
        }
        if (render_output.dirty_rects.empty()) {
          add_rect_once(render_output.dirty_rects, memo_card_rect(state_));
        }
        add_reason_once(render_output.dirty_reasons, "memo.focus_move");
      } else if (committed_memo_expanded_ != memo_expanded) {
        const platform::DirtyRect focus_row =
            memo_focus_row_rect(state_, memo_index, memo_count);
        add_rect_once(render_output.dirty_rects, focus_row);
        if (render_output.dirty_rects.empty()) {
          add_rect_once(render_output.dirty_rects, memo_card_rect(state_));
        }
        add_reason_once(render_output.dirty_reasons, "memo.expand_toggle");
      } else if (committed_memo_digest_ != current_memo_digest) {
        add_rect_once(render_output.dirty_rects, memo_summary_rect(state_));
        add_rect_once(render_output.dirty_rects, memo_card_rect(state_));
        add_reason_once(render_output.dirty_reasons, "memo.data_change");
      }
    } else if (committed_memo_snapshot_valid_) {
      add_rect_once(render_output.dirty_rects, memo_card_rect(state_));
      add_reason_once(render_output.dirty_reasons, "memo.layout_change");
    }
  }

  if (committed_frame_valid_) {
    const auto [bbox, diff_ratio] = diff_stats(render_output.image);
    if (!bbox.has_value()) {
      pending_render_valid_ = false;
      pending_render_ = {};
      refresh_runtime_.clear_pending();
      mark_committed_snapshot();
      return;
    }

    if (render_output.dirty_rects.empty()) {
      render_output.dirty_rects.push_back(bbox.value());
      render_output.dirty_reasons.push_back("diff_only");
    } else {
      const auto merged = refresh_policy::merge_rects(
          render_output.dirty_rects,
          platform::kPanelWidth,
          platform::kPanelHeight);
      if (!merged.has_value() || !refresh_policy::rect_contains(merged.value(), bbox.value(), 4)) {
        if (!merged.has_value()) {
          render_output.dirty_rects.push_back(bbox.value());
          render_output.dirty_reasons.push_back("diff_fallback");
        } else if (state_.screen == committed_screen_) {
          if (diff_ratio >= kDiffFallbackMinRatio) {
            render_output.dirty_rects.push_back(bbox.value());
            render_output.dirty_reasons.push_back("diff_fallback");
          } else if (kRefreshDebugLogs) {
            ESP_LOGI(
                kTag,
                "[refresh] DIFF_FALLBACK_SKIP screen=%s diff_ratio=%.4f threshold=%.4f",
                screen_name(state_.screen),
                diff_ratio,
                kDiffFallbackMinRatio);
          }
        } else if (kRefreshDebugLogs) {
          ESP_LOGI(
              kTag,
              "[refresh] DIFF_FALLBACK_SKIP screen=%s reason=screen_changed",
              screen_name(state_.screen));
        }
      }
    }
  } else if (render_output.dirty_reasons.empty()) {
    render_output.dirty_reasons.push_back("boot.initial");
  }

  if (committed_frame_valid_ && state_.screen != committed_screen_) {
    render_output.dirty_reasons.push_back(
        std::string("screen.change_to_") + screen_name(state_.screen));
  }

  if (render_output.dirty_reasons.empty()) {
    render_output.dirty_reasons.push_back("state.change");
  }

  if (should_collapse_to_latest(state_.screen, render_output.dirty_reasons)) {
    refresh_runtime_.clear_pending();
  }
  refresh_runtime_.enqueue(render_output.dirty_rects);
  pending_render_ = std::move(render_output);
  pending_screen_ = state_.screen;
  pending_home_snapshot_ = ui::capture_home_dirty_snapshot(state_);
  pending_render_valid_ = true;
}

void Runtime::flush_pending(const std::uint64_t now_ms) {
  if (!pending_render_valid_) {
    return;
  }

  const refresh_policy::Mode mode =
      refresh_policy::parse_mode(
          state_.settings.partial_refresh_mode.empty()
              ? state_.settings.refresh_mode
              : state_.settings.partial_refresh_mode);
  const refresh_policy::ModeParams params = refresh_policy::mode_params(mode);
  const bool home_navigation_focus =
      pending_screen_ == Screen::Home &&
      has_any_reason(
          pending_render_.dirty_reasons,
          {
              "home.menu_overlay_focus",
              "home.focus_move_row",
              "home.focus_move_left_target",
              "home.focus_to_left_panel",
              "home.focus_from_left_panel",
          });
  const bool memo_navigation_focus =
      pending_screen_ == Screen::Memo &&
      has_reason(pending_render_.dirty_reasons, "memo.focus_move");
  int effective_min_gap_ms = params.min_refresh_gap_ms;
  if (home_navigation_focus) {
    effective_min_gap_ms = std::min(effective_min_gap_ms, kHomeNavigationMinRefreshGapMs);
  }
  if (memo_navigation_focus) {
    effective_min_gap_ms = std::min(effective_min_gap_ms, kMemoNavigationMinRefreshGapMs);
  }
  const int full_every = state_.settings.partial_refresh_budget_enabled
                             ? refresh_policy::effective_full_refresh_every(
                                   pending_screen_,
                                   mode,
                                   state_.settings.full_refresh_every)
                             : 0;
  const double now_s = static_cast<double>(now_ms) / 1000.0;
  const std::string full_clean_reason =
      refresh_runtime_.full_clean_reason(now_s, full_every);
  const bool force_full_clean = !full_clean_reason.empty();
  const bool screen_changed = committed_frame_valid_ && pending_screen_ != committed_screen_;
  const bool should_flush = !refresh_runtime_.should_throttle(now_s, effective_min_gap_ms) ||
                            !committed_frame_valid_ ||
                            force_full_clean ||
                            screen_changed ||
                            memo_navigation_focus;

  if (!should_flush) {
    if (kRefreshDebugLogs) {
      ESP_LOGI(
          kTag,
          "[refresh] HOLD screen=%s reason=throttle gap_ms=%d mode=%s dirty=%s",
          screen_name(pending_screen_),
          effective_min_gap_ms,
          refresh_policy::mode_name(mode),
          format_reasons(pending_render_.dirty_reasons).c_str());
    }
    return;
  }

  if (!committed_frame_valid_ || force_full_clean) {
    display_.display_full(pending_render_.image, false);
    refresh_runtime_.mark_full_clean(now_s);
    if (kRefreshDebugLogs) {
      ESP_LOGI(
          kTag,
          "[refresh] R3_FULL_CLEAN screen=%s reason=%s partial_count=%d/%d mode=%s dirty=%s",
          screen_name(pending_screen_),
          committed_frame_valid_ ? full_clean_reason.c_str() : "boot.initial",
          refresh_runtime_.partial_count,
          full_every,
          refresh_policy::mode_name(mode),
          format_reasons(pending_render_.dirty_reasons).c_str());
    }
  } else {
    const std::vector<platform::DirtyRect> pending_rects =
        refresh_runtime_.pending_dirty_rects;
    std::vector<platform::DirtyRect> aligned_rects =
        refresh_policy::prepare_partial_rects(
            pending_rects,
            platform::kPanelWidth,
            platform::kPanelHeight,
            kPartialPad,
            kPartialMaxRects,
            true);
    if (pending_screen_ == Screen::Home) {
      reorder_home_transition_rects_for_partial(
          pending_render_.dirty_reasons,
          aligned_rects);
    } else if (pending_screen_ == Screen::Calendar) {
      const bool calendar_landscape = calendar_uses_landscape_layout(state_);
      const bool r90 = normalize_rotation_deg(state_.settings.rotation_deg) == 90;
      reorder_calendar_transition_rects_for_partial(
          pending_render_.dirty_reasons,
          aligned_rects,
          calendar_landscape,
          r90);
    } else if (pending_screen_ == Screen::Memo) {
      const platform::DirtyRect previous_row =
          memo_focus_row_rect(state_, committed_memo_index_, committed_memo_count_);
      const platform::DirtyRect current_row = memo_focus_row_rect(
          state_,
          normalized_memo_index(state_),
          static_cast<int>(state_.dashboard.memos.size()));
      reorder_memo_transition_rects_for_partial(
          pending_render_.dirty_reasons,
          aligned_rects,
          previous_row,
          current_row);
    }
    const double mode_limit =
        refresh_policy::screen_partial_area_limit(pending_screen_, mode);
    double effective_mode_limit = mode_limit;
    if (pending_screen_ == Screen::Home &&
        has_reason(pending_render_.dirty_reasons, "home.family_board_update")) {
      effective_mode_limit = std::max(effective_mode_limit, kHomeFamilyAreaLimitOverride);
    }
    if (pending_screen_ == Screen::Home &&
        (has_reason(pending_render_.dirty_reasons, "home.menu_overlay_toggle") ||
         has_reason(pending_render_.dirty_reasons, "home.menu_overlay_focus"))) {
      effective_mode_limit = std::max(effective_mode_limit, kHomeMenuOverlayAreaLimitOverride);
    }
    if (pending_screen_ == Screen::Home &&
        has_reason(pending_render_.dirty_reasons, "home.reminder_reorder")) {
      effective_mode_limit = std::max(effective_mode_limit, kHomeReminderReorderAreaLimitOverride);
    }
    if (pending_screen_ == Screen::Home &&
        (has_reason(pending_render_.dirty_reasons, "home.reminder_compact") ||
         has_reason(pending_render_.dirty_reasons, "home.reminder_change_fallback"))) {
      effective_mode_limit = std::max(effective_mode_limit, kHomeReminderCompactAreaLimitOverride);
    }
    if (pending_screen_ == Screen::Home &&
        has_reason(pending_render_.dirty_reasons, "home.focus_move_left_target")) {
      effective_mode_limit = std::max(
          effective_mode_limit,
          kHomeFocusMoveLeftTargetAreaLimitOverride);
    }
    if (pending_screen_ == Screen::Home &&
        (has_reason(pending_render_.dirty_reasons, "home.focus_to_left_panel") ||
         has_reason(pending_render_.dirty_reasons, "home.focus_from_left_panel"))) {
      effective_mode_limit = std::max(
          effective_mode_limit,
          kHomeFocusCrossPanelAreaLimitOverride);
    }
    if (pending_screen_ == Screen::Memo &&
        has_reason(pending_render_.dirty_reasons, "memo.focus_move")) {
      effective_mode_limit = std::max(
          effective_mode_limit,
          kMemoFocusMoveAreaLimitOverride);
    }
    const double gate_area_ratio =
        refresh_policy::partial_gate_area_ratio(
            aligned_rects,
            platform::kPanelWidth,
            platform::kPanelHeight);
    const bool partial_enabled = state_.settings.partial_refresh_enabled;
    const bool calendar_force_partial =
        pending_screen_ == Screen::Calendar &&
        has_reason_prefix(pending_render_.dirty_reasons, "calendar.");
    const bool allow_partial =
        !screen_changed &&
        partial_enabled &&
        !aligned_rects.empty() &&
        (gate_area_ratio <= effective_mode_limit || calendar_force_partial);
    if (allow_partial) {
      const bool reinforce_home_reminder =
          pending_screen_ == Screen::Home &&
          (has_reason(pending_render_.dirty_reasons, "home.reminder_row_update") ||
           has_reason(pending_render_.dirty_reasons, "home.reminder_reorder") ||
           has_reason(pending_render_.dirty_reasons, "home.reminder_compact") ||
           has_reason(pending_render_.dirty_reasons, "home.reminder_change_fallback"));
      const bool reinforce_home_focus_left_target =
          pending_screen_ == Screen::Home &&
          kReinforceHomeFocusMoveLeftTargetPass &&
          has_reason(pending_render_.dirty_reasons, "home.focus_move_left_target");
      const bool reinforce_home_focus_cross_panel =
          pending_screen_ == Screen::Home &&
          (has_reason(pending_render_.dirty_reasons, "home.focus_to_left_panel") ||
           has_reason(pending_render_.dirty_reasons, "home.focus_from_left_panel"));

      int partial_passes = 1;
      if (reinforce_home_reminder) {
        partial_passes = std::max(partial_passes, 2);
      }
      if (reinforce_home_focus_cross_panel) {
        partial_passes = std::max(partial_passes, 2);
      }

      for (int pass = 0; pass < partial_passes; ++pass) {
        display_.display_partial(pending_render_.image, aligned_rects);
      }
      refresh_runtime_.mark_partial(now_s);
      if (kRefreshDebugLogs) {
        ESP_LOGI(
            kTag,
            "[refresh] R1_PARTIAL_RECTS screen=%s count=%u rects=%s gate_ratio=%.3f limit=%.3f "
            "partial_count=%d/%d budget=%s passes=%d reinforce_home_reminder=%s "
            "reinforce_home_focus_left_target=%s reinforce_home_focus_cross_panel=%s "
            "force_calendar_partial=%s mode=%s dirty=%s",
            screen_name(pending_screen_),
            static_cast<unsigned>(aligned_rects.size()),
            format_rects(aligned_rects).c_str(),
            gate_area_ratio,
            effective_mode_limit,
            refresh_runtime_.partial_count,
            full_every,
            state_.settings.partial_refresh_budget_enabled ? "on" : "off",
            partial_passes,
            reinforce_home_reminder ? "on" : "off",
            reinforce_home_focus_left_target ? "on" : "off",
            reinforce_home_focus_cross_panel ? "on" : "off",
            calendar_force_partial ? "on" : "off",
            refresh_policy::mode_name(mode),
            format_reasons(pending_render_.dirty_reasons).c_str());
      }
    } else {
      const char* why = "partial_unsupported";
      if (screen_changed) {
        why = "screen_changed";
      } else if (!partial_enabled) {
        why = "partial_disabled";
      } else if (aligned_rects.empty()) {
        why = "no_aligned_rect";
      } else if (gate_area_ratio > effective_mode_limit) {
        why = "area_over_limit";
      }
      display_.display_full(pending_render_.image, false);
      refresh_runtime_.mark_fast_full(now_s);
      if (kRefreshDebugLogs) {
        ESP_LOGI(
            kTag,
            "[refresh] R2_FAST_FULL screen=%s reason=%s gate_ratio=%.3f limit=%.3f rects=%s mode=%s dirty=%s",
            screen_name(pending_screen_),
            why,
            gate_area_ratio,
            effective_mode_limit,
            format_rects(aligned_rects).c_str(),
            refresh_policy::mode_name(mode),
            format_reasons(pending_render_.dirty_reasons).c_str());
      }
    }
  }

  committed_frame_ = pending_render_.image;
  committed_frame_valid_ = true;
  mark_committed_snapshot();

  pending_render_valid_ = false;
  pending_render_ = {};
  refresh_runtime_.clear_pending();
}

std::pair<std::optional<platform::DirtyRect>, double> Runtime::diff_stats(
    const std::vector<uint8_t>& image) const {
  if (!committed_frame_valid_ ||
      committed_frame_.size() != image.size() ||
      image.size() != static_cast<std::size_t>(platform::kPanelBufferSize)) {
    return {std::nullopt, 0.0};
  }

  int y0 = platform::kPanelHeight;
  int y1 = -1;
  int xb0 = platform::kPanelWidthBytes;
  int xb1 = -1;
  bool has_diff = false;
  std::size_t changed_bits = 0;
  for (int y = 0; y < platform::kPanelHeight; ++y) {
    for (int xb = 0; xb < platform::kPanelWidthBytes; ++xb) {
      const int idx = y * platform::kPanelWidthBytes + xb;
      if (image[static_cast<std::size_t>(idx)] ==
          committed_frame_[static_cast<std::size_t>(idx)]) {
        continue;
      }
      has_diff = true;
      const uint8_t delta = static_cast<uint8_t>(
          image[static_cast<std::size_t>(idx)] ^
          committed_frame_[static_cast<std::size_t>(idx)]);
      changed_bits += static_cast<std::size_t>(__builtin_popcount(
          static_cast<unsigned int>(delta)));
      y0 = std::min(y0, y);
      y1 = std::max(y1, y);
      xb0 = std::min(xb0, xb);
      xb1 = std::max(xb1, xb);
    }
  }

  if (!has_diff) {
    return {std::nullopt, 0.0};
  }
  const double diff_ratio =
      static_cast<double>(changed_bits) /
      static_cast<double>(std::max(1, platform::kPanelWidth * platform::kPanelHeight));
  return {
      platform::DirtyRect{
          xb0 * 8,
          y0,
          (xb1 + 1) * 8,
          y1 + 1,
      },
      diff_ratio,
  };
}

void Runtime::mark_committed_snapshot() {
  committed_screen_ = state_.screen;
  if (state_.screen == Screen::Home) {
    committed_home_snapshot_ = ui::capture_home_dirty_snapshot(state_);
    committed_home_snapshot_valid_ = true;
  } else {
    committed_home_snapshot_valid_ = false;
  }

  if (state_.screen == Screen::Timer) {
    committed_timer_snapshot_valid_ = true;
    committed_timer_seconds_ = state_.timer.seconds_remaining;
    committed_timer_running_ = state_.timer.running;
    committed_timer_focused_index_ = state_.timer.focused_index;
    committed_timer_alert_active_ = state_.timer.alert_active;
    committed_timer_alert_blink_on_ = state_.timer.alert_blink_on;
    committed_timer_last_completed_seconds_ = state_.timer.last_completed_seconds;
    committed_timer_widget_mode_ = state_.home.widget_mode;
  } else {
    committed_timer_snapshot_valid_ = false;
  }

  if (state_.screen == Screen::Calendar) {
    committed_calendar_snapshot_valid_ = true;
    committed_calendar_landscape_ = calendar_uses_landscape_layout(state_);
    const auto base_date = calendar_runtime::today_local_date(state_);
    const auto cursor = calendar_runtime::cursor_date(state_, base_date);
    committed_calendar_cursor_year_ = cursor.year;
    committed_calendar_cursor_month_ = cursor.month;
    committed_calendar_cursor_day_ = cursor.day;
    committed_calendar_offset_days_ = state_.calendar.offset_days;
    committed_calendar_mode_ = normalized_calendar_mode(state_.calendar.mode);
    committed_calendar_selected_index_ = std::max(0, state_.calendar.selected_index);
    committed_calendar_events_digest_ = calendar_runtime::calendar_events_digest(state_);
    committed_calendar_reminders_digest_ = calendar_runtime::reminders_calendar_digest(state_);
  } else {
    committed_calendar_snapshot_valid_ = false;
  }

  if (state_.screen == Screen::Memo) {
    committed_memo_snapshot_valid_ = true;
    committed_memo_index_ = normalized_memo_index(state_);
    committed_memo_count_ = static_cast<int>(state_.dashboard.memos.size());
    committed_memo_expanded_ = state_.memo.expanded;
    committed_memo_digest_ = memo_digest(state_);
    committed_memo_rotation_deg_ = normalize_rotation_deg(state_.settings.rotation_deg);
  } else {
    committed_memo_snapshot_valid_ = false;
  }
}

std::string Runtime::format_rects(const std::vector<platform::DirtyRect>& rects) {
  if (rects.empty()) {
    return "-";
  }
  std::ostringstream out;
  for (std::size_t i = 0; i < rects.size(); ++i) {
    const auto& rect = rects[i];
    if (i > 0) {
      out << ';';
    }
    out << rect.x0 << ',' << rect.y0 << ',' << rect.x1 << ',' << rect.y1;
  }
  return out.str();
}

std::string Runtime::format_reasons(const std::vector<std::string>& reasons) {
  if (reasons.empty()) {
    return "-";
  }
  std::ostringstream out;
  for (std::size_t i = 0; i < reasons.size(); ++i) {
    if (i > 0) {
      out << ',';
    }
    out << reasons[i];
  }
  return out.str();
}

}  // namespace fridge_ink::app
