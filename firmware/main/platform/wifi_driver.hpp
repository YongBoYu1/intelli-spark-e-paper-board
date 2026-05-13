#pragma once

#include <cstdint>
#include <string>
#include <vector>

namespace fridge_ink::platform {

/// One entry from a WiFi network scan.
struct WifiApInfo {
  std::string ssid{};
  int rssi{0};
};

/// Scan for nearby WiFi networks.  Initialises the WiFi driver in station
/// mode if it has not been started yet.  Blocks for up to timeout_ms ms.
/// Returns results sorted strongest-first (empty list on failure).
std::vector<WifiApInfo> wifi_scan_networks(uint32_t timeout_ms = 4000);

/// Connect to a specific SSID/password, even if the driver was previously
/// initialised only for scanning.  Blocks until connected or timeout.
bool wifi_connect_to(const char* ssid, const char* password,
                     uint32_t timeout_ms = 15000);

/// Initialise the TCP/IP stack and connect using compile-time credentials.
/// Returns true if an IP address was obtained, false otherwise.
bool wifi_connect(const char* ssid, const char* password,
                  uint32_t timeout_ms = 15000);

/// Returns true if the station is currently connected and has an IP.
bool wifi_is_connected();

/// Disconnect and release WiFi resources.
void wifi_disconnect();

}  // namespace fridge_ink::platform
