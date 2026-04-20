#pragma once

#include <cstdint>
#include <string>

namespace fridge_ink::platform {

/// Synchronise the system clock via NTP (blocks up to timeout_ms).
/// Returns true if wall time is valid after the call.
bool ntp_sync_time(uint32_t timeout_ms = 12000);

/// Query ip-api.com to detect the IANA timezone from the device's public IP,
/// then call apply_timezone() internally.
/// Returns the detected IANA timezone name, or an empty string on failure.
/// Falls back to a numeric UTC-offset POSIX string when the IANA name is
/// not in the built-in table.
std::string ntp_detect_and_apply_timezone(uint32_t timeout_ms = 8000);

/// Convenience wrapper: sync time then detect timezone.
/// Splits timeout_ms as 60 % NTP + 40 % timezone.
/// Returns true if at least the time sync succeeded.
bool ntp_sync(uint32_t timeout_ms = 20000);

}  // namespace fridge_ink::platform
