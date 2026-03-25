#pragma once

#include <cstdint>
#include <memory>
#include <vector>

namespace fridge_ink::platform {

class Display {
 public:
  virtual ~Display() = default;

  virtual void init() = 0;
  virtual void clear() = 0;

  /// Push a rendered framebuffer to the e-paper panel.
  /// The image must be kPanelBufferSize bytes (800×480 / 8 = 48000).
  /// Internally handles dirty-region detection and partial vs full refresh.
  virtual void display_image(const std::vector<uint8_t>& image) = 0;

  /// Diagnostic: set VCOM voltage register (0x82) and force full refresh.
  /// Used for VCOM sweep experiments. Value is the raw register byte.
  virtual void set_vcom_and_refresh(uint8_t vcom_value) = 0;
};

std::unique_ptr<Display> make_default_display();

}  // namespace fridge_ink::platform
