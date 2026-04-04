#include "ui/screens/calendar_screen.hpp"

#include "ui/screens/detail_screen_scaffold.hpp"

#include <string>

namespace fridge_ink::ui {

std::vector<uint8_t> render_calendar_portrait_bitmap(const app::AppState& state) {
  const std::string line_one = std::string("Month: ") + state.calendar.month_label;
  const std::string line_two =
      std::string("Selected day: ") + std::to_string(state.calendar.day_of_month);
  return render_detail_scaffold_bitmap(
      "CALENDAR",
      line_one,
      line_two,
      "Portrait parity worker owns final month/agenda layout.",
      "PORTRAIT");
}

}  // namespace fridge_ink::ui
