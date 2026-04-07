#pragma once

#include "app/state.hpp"
#include "platform/display.hpp"

#include <array>
#include <cstdint>
#include <string>
#include <vector>

namespace fridge_ink::ui {

struct HomeDirtySnapshot {
  app::Screen screen{app::Screen::Landing};
  int focused_index{0};
  bool show_focus{false};
  bool menu_overlay_active{false};
  int menu_focused_index{0};
  std::uint64_t clock_minute_bucket{0};
  std::string clock_sync_state{};
  std::string timezone{};
  std::string weather_sync_state{};
  app::WidgetMode widget_mode{app::WidgetMode::Clock};
  int inventory_count{0};
  int reminder_count{0};
  std::array<bool, 3> inventory_completed{};
  std::array<int, 3> visible_inventory_ids{{-1, -1, -1}};
  std::array<bool, 5> reminder_completed{};
  std::array<int, 5> visible_reminder_ids{{-1, -1, -1, -1, -1}};
  std::uint64_t hidden_inventory_digest{0};
  int hidden_inventory_count{0};
  std::uint64_t hidden_reminder_digest{0};
  int hidden_reminder_count{0};
  std::string weather_condition{};
  int weather_temperature_c{0};
  int weather_humidity_percent{0};
  std::string location{};
  std::string family_memo_text{};
  std::string family_memo_author{};
  std::string family_memo_posted{};
};

struct HomeDirtyPlan {
  std::vector<platform::DirtyRect> rects{};
  std::vector<std::string> reasons{};
};

std::vector<uint8_t> render_home_bitmap(const app::AppState& state);
HomeDirtySnapshot capture_home_dirty_snapshot(const app::AppState& state);
HomeDirtyPlan home_dirty_plan(
    const HomeDirtySnapshot& previous,
    const HomeDirtySnapshot& current);
std::vector<platform::DirtyRect> home_dirty_hints(
    const HomeDirtySnapshot& previous,
    const HomeDirtySnapshot& current);

}  // namespace fridge_ink::ui
