#include "platform/clock.hpp"

#include "esp_timer.h"

namespace fridge_ink::platform {

std::uint64_t monotonic_ms() {
  return static_cast<std::uint64_t>(esp_timer_get_time() / 1000ULL);
}

}  // namespace fridge_ink::platform
