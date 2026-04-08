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
constexpr double kHomeFamilyAreaLimitOverride = 0.30;
constexpr double kHomeMenuOverlayAreaLimitOverride = 0.60;
constexpr double kHomeReminderReorderAreaLimitOverride = 0.30;
constexpr double kHomeReminderCompactAreaLimitOverride = 0.40;

struct CalendarLandscapeRegions {
  platform::DirtyRect left_panel{};
  platform::DirtyRect left_grid{};
  platform::DirtyRect right_panel{};
  platform::DirtyRect right_header{};
  platform::DirtyRect right_agenda{};
};

bool calendar_uses_landscape_layout(const AppState& state) {
  const int deg = ((state.settings.rotation_deg % 360) + 360) % 360;
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

platform::DirtyRect timer_time_status_rect() {
  return platform::DirtyRect{
      56,
      82,
      std::max(57, platform::kPanelWidth - 56),
      std::max(83, platform::kPanelHeight - 84),
  };
}

platform::DirtyRect timer_controls_rect() {
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
  if (reasons.empty() || screen != Screen::Home) {
    return false;
  }

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
      add_rect_once(render_output.dirty_rects, timer_controls_rect());
      add_reason_once(render_output.dirty_reasons, "timer.focus_move");
    }
    if (committed_timer_seconds_ != state_.timer.seconds_remaining ||
        committed_timer_running_ != state_.timer.running ||
        committed_timer_alert_active_ != state_.timer.alert_active ||
        committed_timer_alert_blink_on_ != state_.timer.alert_blink_on ||
        committed_timer_last_completed_seconds_ != state_.timer.last_completed_seconds ||
        committed_timer_widget_mode_ != state_.home.widget_mode) {
      add_rect_once(render_output.dirty_rects, timer_time_status_rect());
      if (committed_timer_running_ != state_.timer.running) {
        add_rect_once(render_output.dirty_rects, timer_controls_rect());
      }
      add_reason_once(render_output.dirty_reasons, "timer.time_or_state");
    }
  }

  if (state_.screen == Screen::Calendar &&
      calendar_uses_landscape_layout(state_)) {
    const CalendarLandscapeRegions regions = calendar_landscape_regions();
    if (!committed_frame_valid_ || committed_screen_ != Screen::Calendar) {
      add_rect_once(render_output.dirty_rects, regions.left_panel);
      add_rect_once(render_output.dirty_rects, regions.right_panel);
    } else if (committed_calendar_snapshot_valid_ && committed_calendar_landscape_) {
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
        if (offset_changed) {
          if (committed_calendar_cursor_year_ != cursor.year ||
              committed_calendar_cursor_month_ != cursor.month) {
            add_rect_once(render_output.dirty_rects, regions.left_panel);
          } else {
            add_rect_once(render_output.dirty_rects, regions.left_grid);
          }
          add_rect_once(render_output.dirty_rects, regions.right_header);
          add_rect_once(render_output.dirty_rects, regions.right_agenda);
        } else if (mode_changed) {
          add_rect_once(render_output.dirty_rects, regions.right_header);
          add_rect_once(render_output.dirty_rects, regions.right_agenda);
        } else {
          add_rect_once(render_output.dirty_rects, regions.left_grid);
          add_rect_once(render_output.dirty_rects, regions.right_agenda);
        }
        add_reason_once(render_output.dirty_reasons, "calendar.date_or_mode_or_data");
      } else if (committed_calendar_selected_index_ != curr_selected) {
        add_rect_once(render_output.dirty_rects, regions.right_agenda);
        add_reason_once(render_output.dirty_reasons, "calendar.agenda_focus_move");
      }
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
  const bool should_flush = !refresh_runtime_.should_throttle(now_s, params.min_refresh_gap_ms) ||
                            !committed_frame_valid_ ||
                            force_full_clean ||
                            screen_changed;

  if (!should_flush) {
    if (kRefreshDebugLogs) {
      ESP_LOGI(
          kTag,
          "[refresh] HOLD screen=%s reason=throttle gap_ms=%d mode=%s dirty=%s",
          screen_name(pending_screen_),
          params.min_refresh_gap_ms,
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

      int partial_passes = 1;
      if (reinforce_home_reminder) {
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
