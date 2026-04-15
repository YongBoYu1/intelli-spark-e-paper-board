#pragma once

#include <cstdint>
#include <ctime>

namespace fridge_ink::platform {

struct ClockSyncSample {
  bool valid{false};
  bool synced{false};
  std::time_t unix_seconds{0};
  const char* source{nullptr};
  const char* error{nullptr};
};

struct WeatherSyncSample {
  bool valid{false};
  bool synced{false};
  const char* location{nullptr};
  const char* condition{nullptr};
  int temperature_c{0};
  int humidity_percent{0};
  std::time_t observed_unix_seconds{0};
  const char* source{nullptr};
  const char* error{nullptr};
};

// Weak extension points for external Wi-Fi/API module integration.
bool live_data_bootstrap(const char* timezone_name, const char* location_hint);
bool live_data_request_sync_now();
bool live_data_poll_clock(ClockSyncSample* sample_out);
bool live_data_poll_weather(WeatherSyncSample* sample_out);

}  // namespace fridge_ink::platform
