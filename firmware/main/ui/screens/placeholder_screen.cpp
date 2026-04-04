#include "ui/screens/placeholder_screen.hpp"

#include "platform/panel_config.hpp"
#include "ui/draw.hpp"

#include <string>
#include <vector>

namespace fridge_ink::ui {
namespace {

std::vector<uint8_t> render_placeholder_bitmap(
    const std::string& title,
    const std::string& line_one,
    const std::string& line_two,
    const std::string& line_three) {
  using platform::kPanelBufferSize;
  using platform::kPanelWidth;

  std::vector<uint8_t> image(kPanelBufferSize, 0xFF);
  draw_outline_rect(image, 12, 12, kPanelWidth - 12, 468, 3);
  draw_text_line(image, 40, 30, title, 3, 26);
  draw_text_line(image, 40, 72, "Issue #52 placeholder screen", 1, 36);

  draw_outline_rect(image, 40, 124, kPanelWidth - 40, 344, 2);
  draw_text_wrapped(image, 60, 152, 640, line_one, 2, 2);
  draw_text_wrapped(image, 60, 212, 640, line_two, 2, 2);
  draw_text_wrapped(image, 60, 272, 640, line_three, 2, 2);

  fill_black_rect(image, 204, 388, kPanelWidth - 204, 438);
  draw_outline_rect(image, 201, 385, kPanelWidth - 201, 441, 3);
  draw_text_centered_inverted(
      image, 220, kPanelWidth - 220, 404, "CLICK TO RETURN MENU", 1, 28);
  return image;
}

}  // namespace

std::vector<uint8_t> render_weather_bitmap(const app::AppState& state) {
  const std::string line_one =
      std::string("Condition: ") + state.weather.condition;
  const std::string line_two =
      std::string("Temperature: ") + std::to_string(state.weather.temperature_c) + " C";
  return render_placeholder_bitmap(
      "WEATHER",
      line_one,
      line_two,
      "Detailed weather layout parity is deferred until after navigation/state migration.");
}

std::vector<uint8_t> render_inventory_bitmap(const app::AppState& state) {
  const std::string line_one =
      std::string("Inventory items: ") + std::to_string(state.inventory.total_items);
  const std::string line_two =
      std::string("Reminders: ") + std::to_string(state.inventory.reminder_count);
  return render_placeholder_bitmap(
      "INVENTORY / REMINDERS",
      line_one,
      line_two,
      "This placeholder keeps the combined product area reachable on device.");
}

}  // namespace fridge_ink::ui
