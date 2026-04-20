#pragma once

#include <ctime>
#include <cstdint>
#include <string>

namespace fridge_ink::platform {

std::uint64_t monotonic_ms();
std::time_t wall_time_seconds();
bool wall_time_is_valid();
bool set_wall_time_seconds(std::time_t unix_seconds);
bool apply_timezone(const std::string& zone_name);
const std::string& active_timezone_name();
const std::string& active_posix_timezone();

}  // namespace fridge_ink::platform
