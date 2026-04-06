#pragma once

namespace fridge_ink::platform {

struct DisplayPins {
  int sclk{-1};
  int mosi{-1};
  int cs{-1};
  int dc{-1};
  int rst{-1};
  int busy{-1};
  int power_enable{-1};
};

struct BoardConfig {
  const char* board_name{"ESP32-S3 (pending exact dev board variant)"};
  const char* target{"esp32s3"};
  const char* display_name{"Waveshare 7.5inch e-Paper HAT V2"};
  bool display_pin_map_ready{false};
  DisplayPins display_pins{};
};

const BoardConfig& default_board_config();
bool has_ready_display_pin_map(const BoardConfig& config);

}  // namespace fridge_ink::platform
