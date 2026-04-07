#include "ui/screens/settings_screen.hpp"

#include "platform/panel_config.hpp"
#include "ui/draw.hpp"

#include <algorithm>
#include <array>
#include <cstdint>
#include <string>

namespace fridge_ink::ui {
namespace {

enum class SettingsItem {
  FontSize = 0,
  PartialRefresh = 1,
  FullRefresh = 2,
  Rotation = 3,
  Connectivity = 4,
  AutoSync = 5,
  SyncNow = 6,
  ResetAndWipe = 7,
};

constexpr std::array<SettingsItem, 8> kSettingsOrder = {
    SettingsItem::FontSize,
    SettingsItem::PartialRefresh,
    SettingsItem::FullRefresh,
    SettingsItem::Rotation,
    SettingsItem::Connectivity,
    SettingsItem::AutoSync,
    SettingsItem::SyncNow,
    SettingsItem::ResetAndWipe,
};

std::string upper_copy(const std::string& text) {
  std::string out = text;
  for (char& ch : out) {
    if (ch >= 'a' && ch <= 'z') {
      ch = static_cast<char>(ch - ('a' - 'A'));
    }
  }
  return out;
}

std::string bool_text(const bool value) {
  return value ? "ON" : "OFF";
}

int normalize_rotation_deg(const int raw) {
  const int normalized = ((raw % 360) + 360) % 360;
  if (normalized >= 315 || normalized < 45) {
    return 0;
  }
  if (normalized < 135) {
    return 90;
  }
  if (normalized < 225) {
    return 180;
  }
  return 270;
}

std::string setting_label(const SettingsItem item) {
  switch (item) {
    case SettingsItem::FontSize:
      return "FONT SIZE";
    case SettingsItem::PartialRefresh:
      return "PARTIAL REFRESH";
    case SettingsItem::FullRefresh:
      return "FULL REFRESH";
    case SettingsItem::Rotation:
      return "ROTATION";
    case SettingsItem::Connectivity:
      return "WIFI + BT";
    case SettingsItem::AutoSync:
      return "AUTO SYNC";
    case SettingsItem::SyncNow:
      return "SYNC NOW";
    case SettingsItem::ResetAndWipe:
      return "RESET / WEB DATA";
  }
  return {};
}

std::string setting_value(const app::AppState& state, const SettingsItem item) {
  switch (item) {
    case SettingsItem::FontSize:
      return upper_copy(state.settings.font_size.empty() ? "medium" : state.settings.font_size);
    case SettingsItem::PartialRefresh:
      return upper_copy(
          state.settings.partial_refresh_mode.empty() ? "balanced" : state.settings.partial_refresh_mode);
    case SettingsItem::FullRefresh:
      return "EVERY " + std::to_string(std::max(1, state.settings.full_refresh_every)) + " PARTIALS";
    case SettingsItem::Rotation:
      return std::to_string(normalize_rotation_deg(state.settings.rotation_deg));
    case SettingsItem::Connectivity:
      return "WIFI " + bool_text(state.settings.wifi_enabled) +
             " / BT " + bool_text(state.settings.bluetooth_enabled);
    case SettingsItem::AutoSync:
      return bool_text(state.settings.auto_sync_enabled);
    case SettingsItem::SyncNow:
      return "PRESS ENTER";
    case SettingsItem::ResetAndWipe:
      return "PLACEHOLDER";
  }
  return {};
}

std::string sync_footer_status(const app::AppState& state) {
  if (state.settings.sync_state == "ok") {
    return "LAST SYNC OK";
  }
  if (state.settings.sync_state == "pending") {
    return "SYNC IN PROGRESS";
  }
  if (state.settings.sync_state == "fail") {
    return "LAST SYNC FAIL";
  }
  return "LAST SYNC NEVER";
}

}  // namespace

std::vector<uint8_t> render_settings_landscape_bitmap(const app::AppState& state) {
  using platform::kPanelBufferSize;
  using platform::kPanelHeight;
  using platform::kPanelWidth;

  std::vector<uint8_t> image(kPanelBufferSize, 0xFF);

  const int left = 24;
  const int right = kPanelWidth - 24;
  draw_text_line(image, left, 16, "SETTINGS", 3, 16);

  const std::string hint = truncate_text_px(
      "ROTATE TO SELECT  -  CLICK TO ENTER  -  HOLD TO HOME",
      1,
      std::max(80, right - left));
  const int hint_w = text_width_px(hint, 1);
  draw_text_line(image, std::max(left, right - hint_w), 52, hint, 1, 0);
  fill_black_rect(image, left, 68, right, 70);

  const int footer_h = 30;
  const int footer_top = kPanelHeight - footer_h;
  const int content_top = 90;
  const int content_bottom = footer_top - 6;

  int row_h = 32;
  int row_gap = 1;
  int group_h = 18;
  int group_gap = 6;
  auto content_height = [&]() {
    return group_h + (5 * row_h) + (4 * row_gap) + group_gap +
           group_h + (2 * row_h) + row_gap + group_gap +
           group_h + row_h;
  };
  while (content_height() > (content_bottom - content_top) && row_h > 24) {
    --row_h;
  }

  const int focused =
      std::max(0, std::min(state.settings.focused_index, static_cast<int>(kSettingsOrder.size() - 1)));

  int y = content_top;
  auto draw_group = [&](const char* group_name, const int first_idx, const int count) {
    draw_text_line(image, left + 2, y, group_name, 1, 16);
    y += group_h;
    for (int i = 0; i < count; ++i) {
      const int idx = first_idx + i;
      const SettingsItem item = kSettingsOrder[static_cast<std::size_t>(idx)];
      const bool is_focus = idx == focused;
      const int y0 = y;
      const int y1 = y0 + row_h;

      const std::string marker = is_focus ? ">" : " ";
      const std::string label = setting_label(item);
      const std::string value = truncate_text_px(
          setting_value(state, item),
          1,
          std::max(120, ((right - left) * 50) / 100));

      const int value_w = text_width_px(value, 1);
      const int value_x = right - 12 - value_w;
      const int marker_x = left + 2;
      const int marker_w = text_width_px(marker, 1);
      const int label_x = marker_x + marker_w + 8;
      const int label_max_w = std::max(100, value_x - label_x - 12);
      const std::string label_fit = truncate_text_px(label, 1, label_max_w);

      draw_text_line(image, marker_x, y0 + 8, marker, 1, 2);
      draw_text_line(image, label_x, y0 + 7, label_fit, 2, 32);
      draw_text_line(image, value_x, y0 + 8, value, 1, 42);
      if (is_focus) {
        fill_black_rect(image, label_x, y1 - 2, right - 12, y1 - 1);
      }
      y += row_h + row_gap;
    }
    y += group_gap;
  };

  draw_group("DISPLAY", 0, 5);
  draw_group("SYNC", 5, 2);
  draw_group("OTHER", 7, 1);

  fill_black_rect(image, left, footer_top - 1, right, footer_top);
  const std::string notice = truncate_text_px(upper_copy(state.settings.notice), 1, std::max(40, right - left - 220));
  if (!notice.empty()) {
    draw_text_line(image, left, footer_top + 8, notice, 1, 80);
  }
  const std::string sync = truncate_text_px(sync_footer_status(state), 1, 210);
  const int sync_w = text_width_px(sync, 1);
  draw_text_line(image, std::max(left, right - sync_w), footer_top + 8, sync, 1, 32);
  return image;
}

}  // namespace fridge_ink::ui
