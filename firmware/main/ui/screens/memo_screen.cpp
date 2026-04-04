#include "ui/screens/memo_screen.hpp"

namespace fridge_ink::ui {
namespace {

bool use_memo_portrait_layout(const app::AppState& state) {
  const int deg = ((state.settings.rotation_deg % 360) + 360) % 360;
  return deg == 90 || deg == 270;
}

}  // namespace

std::vector<uint8_t> render_memo_bitmap(const app::AppState& state) {
  if (use_memo_portrait_layout(state)) {
    return render_memo_portrait_bitmap(state);
  }
  return render_memo_landscape_bitmap(state);
}

}  // namespace fridge_ink::ui
