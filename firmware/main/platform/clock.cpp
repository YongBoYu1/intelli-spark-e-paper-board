#include "platform/clock.hpp"

#include "esp_timer.h"

#include <sys/time.h>

namespace fridge_ink::platform {

namespace {
constexpr std::time_t kValidWallClockThreshold = 1700000000;
}  // namespace

std::uint64_t monotonic_ms() {
  return static_cast<std::uint64_t>(esp_timer_get_time() / 1000ULL);
}

std::time_t wall_time_seconds() {
  return std::time(nullptr);
}

bool wall_time_is_valid() {
  return wall_time_seconds() >= kValidWallClockThreshold;
}

bool set_wall_time_seconds(const std::time_t unix_seconds) {
  if (unix_seconds < kValidWallClockThreshold) {
    return false;
  }
  timeval tv{};
  tv.tv_sec = unix_seconds;
  tv.tv_usec = 0;
  return settimeofday(&tv, nullptr) == 0;
}

}  // namespace fridge_ink::platform
