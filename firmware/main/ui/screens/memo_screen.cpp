#include "ui/screens/memo_screen.hpp"

namespace fridge_ink::ui {
namespace {

bool use_memo_portrait_layout(const app::AppState& state) {
  (void)state;
  // Scaffold phase: orientation wiring lands before portrait state plumbing.
  return false;
}

}  // namespace

std::vector<uint8_t> render_memo_bitmap(const app::AppState& state) {
  if (use_memo_portrait_layout(state)) {
    return render_memo_portrait_bitmap(state);
  }
  return render_memo_landscape_bitmap(state);
}

}  // namespace fridge_ink::ui
