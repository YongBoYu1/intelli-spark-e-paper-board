#pragma once

#include <cstdint>

#include "app/state.hpp"

namespace fridge_ink::app {

struct ProductDefaults {
  bool setup_completed{false};
  Language device_language{Language::EnUs};
  Language voice_locale{Language::EnUs};
  DashboardSummary dashboard{};
};

ProductDefaults make_factory_defaults();
Screen resolve_boot_screen(const ProductDefaults& defaults);
AppState make_state_from_defaults(
    const ProductDefaults& defaults,
    std::uint64_t now_ms);

}  // namespace fridge_ink::app
