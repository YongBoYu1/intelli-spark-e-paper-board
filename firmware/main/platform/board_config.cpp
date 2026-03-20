#include "platform/board_config.hpp"

namespace fridge_ink::platform {
namespace {

const BoardConfig kDefaultBoardConfig{};

}  // namespace

const BoardConfig& default_board_config() {
  return kDefaultBoardConfig;
}

bool has_ready_display_pin_map(const BoardConfig& config) {
  return config.display_pin_map_ready &&
         config.display_pins.sclk >= 0 &&
         config.display_pins.mosi >= 0 &&
         config.display_pins.cs >= 0 &&
         config.display_pins.dc >= 0 &&
         config.display_pins.rst >= 0 &&
         config.display_pins.busy >= 0;
}

}  // namespace fridge_ink::platform
