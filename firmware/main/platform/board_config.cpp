#include "platform/board_config.hpp"

namespace fridge_ink::platform {
namespace {

const BoardConfig kDefaultBoardConfig{
    .board_name = "ESP32-S3 DevKit (partner wiring v1)",
    .target = "esp32s3",
    .display_name = "Waveshare 7.5inch e-Paper HAT V2",
    .display_pin_map_ready = true,
    .display_pins =
        {
            .sclk = 12,
            .mosi = 11,
            .cs = 47,
            .dc = 21,
            .rst = 4,
            .busy = 14,
            .power_enable = 8,
        },
};

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
