#include "platform/clock.hpp"

#include "esp_timer.h"

#include <cstdlib>
#include <string>
#include <sys/time.h>

namespace fridge_ink::platform {

namespace {
constexpr std::time_t kValidWallClockThreshold = 1700000000;
std::string g_active_timezone_iana = "UTC";
std::string g_active_timezone_posix = "UTC0";

std::string normalize_timezone_name(const std::string& zone_name) {
  if (zone_name == "America/New_York") {
    return "America/Toronto";
  }
  if (zone_name.empty()) {
    return "UTC";
  }
  return zone_name;
}

std::string iana_to_posix_tz(const std::string& zone_name) {
  const std::string normalized = normalize_timezone_name(zone_name);
  if (normalized == "America/Toronto") {
    return "EST5EDT,M3.2.0/2,M11.1.0/2";
  }
  if (normalized == "America/Los_Angeles") {
    return "PST8PDT,M3.2.0/2,M11.1.0/2";
  }
  return "UTC0";
}
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

bool apply_timezone(const std::string& zone_name) {
  const std::string normalized = normalize_timezone_name(zone_name);
  const std::string posix = iana_to_posix_tz(normalized);
  if (normalized == g_active_timezone_iana && posix == g_active_timezone_posix) {
    return true;
  }
  if (setenv("TZ", posix.c_str(), 1) != 0) {
    return false;
  }
  tzset();
  g_active_timezone_iana = normalized;
  g_active_timezone_posix = posix;
  return true;
}

const std::string& active_timezone_name() {
  return g_active_timezone_iana;
}

const std::string& active_posix_timezone() {
  return g_active_timezone_posix;
}

}  // namespace fridge_ink::platform
