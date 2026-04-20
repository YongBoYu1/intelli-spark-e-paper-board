#pragma once

#include <cstdint>

namespace fridge_ink::platform {

/// Initialise the TCP/IP stack and connect to the configured WiFi network.
/// Blocks until connected or the timeout expires.
/// Returns true if an IP address was obtained, false otherwise.
bool wifi_connect(const char* ssid, const char* password,
                  uint32_t timeout_ms = 15000);

/// Returns true if the station is currently connected and has an IP.
bool wifi_is_connected();

/// Disconnect and release WiFi resources.
void wifi_disconnect();

}  // namespace fridge_ink::platform
