#include "ui/screens/settings_screen.hpp"

#include "ui/screens/detail_screen_scaffold.hpp"

#include <string>

namespace fridge_ink::ui {

std::vector<uint8_t> render_settings_landscape_bitmap(const app::AppState& state) {
  const std::string line_one = std::string("Partial refresh: ") +
                               (state.settings.partial_refresh_enabled ? "ENABLED" : "DISABLED");
  const std::string line_two =
      std::string("Auto sync: ") + (state.settings.auto_sync_enabled ? "ON" : "OFF");
  return render_detail_scaffold_bitmap(
      "SETTINGS",
      line_one,
      line_two,
      "Landscape parity worker owns final list rows and focus behavior.",
      "LANDSCAPE");
}

}  // namespace fridge_ink::ui
