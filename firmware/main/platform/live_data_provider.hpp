#pragma once

#include <array>
#include <cstdint>
#include <ctime>
#include <string>

namespace fridge_ink::platform {

struct ClockSyncSample {
  bool valid{false};
  bool synced{false};
  std::time_t unix_seconds{0};
  std::string source{};
  std::string error{};
};

struct WeatherForecastDaySample {
  std::string dow{"--"};
  std::string condition{};
  std::string icon{"cloud"};
  int hi_c{0};
  int lo_c{0};
};

struct WeatherSyncSample {
  bool valid{false};
  bool synced{false};
  std::string location{};
  std::string condition{};
  std::string icon{"cloud"};
  int temperature_c{0};
  int humidity_percent{0};
  int feels_like_c{0};
  int hi_c{0};
  int lo_c{0};
  int wind_kmh{0};
  int uv_index{0};
  std::array<WeatherForecastDaySample, 3> forecast_days{};
  std::time_t observed_unix_seconds{0};
  std::string source{};
  std::string error{};
};

// Weak extension points for external Wi-Fi/API module integration.
bool live_data_bootstrap(const char* timezone_name, const char* location_hint);
bool live_data_request_sync_now();
bool live_data_weather_sync_in_progress();
bool live_data_poll_clock(ClockSyncSample* sample_out);
bool live_data_poll_weather(WeatherSyncSample* sample_out);

}  // namespace fridge_ink::platform
