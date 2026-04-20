#include "platform/live_data_provider.hpp"

namespace fridge_ink::platform {

bool __attribute__((weak)) live_data_bootstrap(
    const char* timezone_name,
    const char* location_hint) {
  (void)timezone_name;
  (void)location_hint;
  return false;
}

bool __attribute__((weak)) live_data_request_sync_now() {
  return false;
}

bool __attribute__((weak)) live_data_poll_clock(ClockSyncSample* sample_out) {
  (void)sample_out;
  return false;
}

bool __attribute__((weak)) live_data_poll_weather(WeatherSyncSample* sample_out) {
  (void)sample_out;
  return false;
}

}  // namespace fridge_ink::platform
