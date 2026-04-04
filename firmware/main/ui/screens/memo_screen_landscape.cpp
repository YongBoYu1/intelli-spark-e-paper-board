#include "ui/screens/memo_screen.hpp"

#include "ui/screens/detail_screen_scaffold.hpp"

namespace fridge_ink::ui {

std::vector<uint8_t> render_memo_landscape_bitmap(const app::AppState& state) {
  (void)state;
  return render_detail_scaffold_bitmap(
      "MEMO",
      "Memo landscape renderer scaffolded.",
      "Python parity implementation will replace this in page-specific worker.",
      "Refresh/runtime policy remains centralized in Runtime.",
      "LANDSCAPE");
}

}  // namespace fridge_ink::ui
