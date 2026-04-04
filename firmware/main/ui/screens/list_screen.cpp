#include "ui/screens/list_screen.hpp"

namespace fridge_ink::ui {
namespace {

bool use_list_portrait_layout(const app::AppState& state) {
  (void)state;
  // Orientation wiring is still shared follow-up work across all detail pages.
  return false;
}

}  // namespace

std::vector<uint8_t> render_list_bitmap(const app::AppState& state) {
  if (use_list_portrait_layout(state)) {
    return render_list_portrait_bitmap(state);
  }
  return render_list_landscape_bitmap(state);
}

}  // namespace fridge_ink::ui
