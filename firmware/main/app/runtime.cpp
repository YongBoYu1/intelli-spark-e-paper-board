#include "app/runtime.hpp"

#include "app/defaults.hpp"
#include "app/reducer.hpp"
#include "platform/clock.hpp"
#include "platform/display.hpp"
#include "platform/panel_config.hpp"
#include "ui/render_app.hpp"
#include "ui/screens/home_screen.hpp"

#include "esp_log.h"

#include <algorithm>
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
      "home.menu_overlay_toggle",
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
  const auto defaults = make_factory_defaults();
  state_ = make_state_from_defaults(defaults, platform::monotonic_ms());
  display_.init();
  stage_render();
  flush_pending(platform::monotonic_ms());
}

void Runtime::dispatch(const Event& event) {
  reduce(state_, event);
  stage_render();
  const std::uint64_t now_ms = event.now_ms > 0 ? event.now_ms : platform::monotonic_ms();
  flush_pending(now_ms);
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
      refresh_policy::parse_mode(state_.settings.refresh_mode);
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
        has_reason(pending_render_.dirty_reasons, "home.menu_overlay_toggle")) {
      effective_mode_limit = std::max(effective_mode_limit, kHomeMenuOverlayAreaLimitOverride);
    }
    const double gate_area_ratio =
        refresh_policy::partial_gate_area_ratio(
            aligned_rects,
            platform::kPanelWidth,
            platform::kPanelHeight);
    const bool partial_enabled = state_.settings.partial_refresh_enabled;
    const bool allow_partial =
        !screen_changed &&
        partial_enabled &&
        !aligned_rects.empty() &&
        gate_area_ratio <= effective_mode_limit;
    const bool menu_overlay_toggle_open =
        pending_screen_ == Screen::Home &&
        has_reason(pending_render_.dirty_reasons, "home.menu_overlay_toggle") &&
        pending_home_snapshot_.menu_overlay_active;

    if (menu_overlay_toggle_open) {
      // Product consistency guardrail:
      // Home menu first-open must not show "transparent/washed" pills.
      // Force a non-clean full refresh for deterministic visual result.
      display_.display_full(pending_render_.image, false);
      refresh_runtime_.mark_fast_full(now_s);
      if (kRefreshDebugLogs) {
        ESP_LOGI(
            kTag,
            "[refresh] R2_FAST_FULL screen=%s reason=home.menu_overlay_toggle_consistency "
            "gate_ratio=%.3f limit=%.3f mode=%s dirty=%s",
            screen_name(pending_screen_),
            gate_area_ratio,
            effective_mode_limit,
            refresh_policy::mode_name(mode),
            format_reasons(pending_render_.dirty_reasons).c_str());
      }
    } else if (allow_partial) {
      const bool reinforce_row_toggle =
          pending_screen_ == Screen::Home &&
          has_reason(pending_render_.dirty_reasons, "home.reminder_row_update");
      const bool reinforce_menu_overlay_toggle =
          pending_screen_ == Screen::Home &&
          has_reason(pending_render_.dirty_reasons, "home.menu_overlay_toggle");
      const bool overlay_toggle_open =
          reinforce_menu_overlay_toggle && pending_home_snapshot_.menu_overlay_active;

      int partial_passes = 1;
      if (reinforce_row_toggle) {
        partial_passes = std::max(partial_passes, 2);
      }
      if (overlay_toggle_open) {
        // Panel-side stabilization: first overlay open is the most artifact-prone
        // (white-on-old-content recovery). Drive the same rects multiple times.
        partial_passes = std::max(partial_passes, 3);
      }

      for (int pass = 0; pass < partial_passes; ++pass) {
        display_.display_partial(pending_render_.image, aligned_rects);
      }
      refresh_runtime_.mark_partial(now_s);
      if (kRefreshDebugLogs) {
        ESP_LOGI(
            kTag,
            "[refresh] R1_PARTIAL_RECTS screen=%s count=%u rects=%s gate_ratio=%.3f limit=%.3f "
            "partial_count=%d/%d budget=%s passes=%d reinforce_row=%s reinforce_menu_toggle=%s "
            "overlay_toggle_open=%s mode=%s dirty=%s",
            screen_name(pending_screen_),
            static_cast<unsigned>(aligned_rects.size()),
            format_rects(aligned_rects).c_str(),
            gate_area_ratio,
            effective_mode_limit,
            refresh_runtime_.partial_count,
            full_every,
            state_.settings.partial_refresh_budget_enabled ? "on" : "off",
            partial_passes,
            reinforce_row_toggle ? "on" : "off",
            reinforce_menu_overlay_toggle ? "on" : "off",
            overlay_toggle_open ? "on" : "off",
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
            "[refresh] R2_FAST_FULL screen=%s reason=%s gate_ratio=%.3f limit=%.3f mode=%s dirty=%s",
            screen_name(pending_screen_),
            why,
            gate_area_ratio,
            effective_mode_limit,
            refresh_policy::mode_name(mode),
            format_reasons(pending_render_.dirty_reasons).c_str());
      }
    }
  }

  committed_frame_ = pending_render_.image;
  committed_frame_valid_ = true;
  committed_screen_ = pending_screen_;
  if (pending_screen_ == Screen::Home) {
    committed_home_snapshot_ = pending_home_snapshot_;
    committed_home_snapshot_valid_ = true;
  } else {
    committed_home_snapshot_valid_ = false;
  }

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
