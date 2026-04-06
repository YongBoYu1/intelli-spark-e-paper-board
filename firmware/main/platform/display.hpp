#pragma once

#include <cstdint>
#include <memory>
#include <vector>

namespace fridge_ink::platform {

struct DirtyRect {
  int x0{0};
  int y0{0};
  int x1{0};
  int y1{0};
};

class Display {
 public:
  virtual ~Display() = default;

  virtual void init() = 0;
  virtual void clear() = 0;

  /// Execute a full-screen refresh.
  virtual void display_full(
      const std::vector<uint8_t>& image,
      bool clean_cycle = false) = 0;

  /// Execute partial refreshes for explicit dirty windows.
  virtual void display_partial(
      const std::vector<uint8_t>& image,
      const std::vector<DirtyRect>& dirty_rects) = 0;

  /// Diagnostic: set VCOM voltage register (0x82) and force full refresh.
  /// Used for VCOM sweep experiments. Value is the raw register byte.
  virtual void set_vcom_and_refresh(uint8_t vcom_value) = 0;
};

std::unique_ptr<Display> make_default_display();

}  // namespace fridge_ink::platform
