#pragma once

#include <array>
#include <cstdint>
#include <string>

namespace fridge_ink::platform {

struct WeatherResult {
  bool ok{false};
  std::string error{};

  // Current conditions
  std::string location{};       // City name from IP geolocation
  std::string condition{};      // Human-readable label, e.g. "Partly Cloudy"
  std::string icon_key{};       // Keyword for draw_icon(), e.g. "partly_cloudy"
  int temperature_c{0};
  int feels_like_c{0};
  int hi_c{0};
  int lo_c{0};
  int humidity_percent{0};
  int wind_kmh{0};
  int uv_index{0};

  // 3-day forecast (index 0 = today)
  struct ForecastDay {
    std::string dow{};        // e.g. "MON"
    std::string condition{};
    std::string icon_key{};
    int hi_c{0};
    int lo_c{0};
  };
  std::array<ForecastDay, 3> forecast{};
};

/// Fetch current weather + 3-day forecast from wttr.in (no API key needed).
/// Location is determined from the device's public IP.
/// Returns WeatherResult::ok == false on network/parse error.
WeatherResult weather_fetch(uint32_t timeout_ms = 12000);

}  // namespace fridge_ink::platform
