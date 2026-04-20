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

// I2S MEMS microphone (NR0562) pin mapping.
// Hardware wiring: SCK→GPIO5, WS→GPIO6, SD→GPIO7, L/R→GND (left ch).
struct MicPins {
  int sck{-1};  // I2S BCLK  (bit clock)
  int ws{-1};   // I2S LRCLK (word select / frame sync)
  int sd{-1};   // I2S Data In (serial data)
};

struct BoardConfig {
  const char* board_name{"ESP32-S3 (pending exact dev board variant)"};
  const char* target{"esp32s3"};
  const char* display_name{"Waveshare 7.5inch e-Paper HAT V2"};
  bool display_pin_map_ready{false};
  DisplayPins display_pins{};
  bool mic_pin_map_ready{false};
  MicPins mic_pins{};
};

const BoardConfig& default_board_config();
bool has_ready_display_pin_map(const BoardConfig& config);
bool has_ready_mic_pin_map(const BoardConfig& config);

}  // namespace fridge_ink::platform
