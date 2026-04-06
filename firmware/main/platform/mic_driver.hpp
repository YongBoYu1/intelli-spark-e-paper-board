#pragma once

// I2S microphone driver for NR0562 MEMS mic on ESP32-S3.
//
// Usage:
//   mic_driver_init(pins)      — install I2S driver (once at startup)
//   mic_record_pcm(max_ms)     — blocking capture; returns 16-bit PCM samples
//   mic_driver_deinit()        — release I2S peripheral
//
// Audio format: 16 kHz, mono, signed 16-bit little-endian (S16_LE).
// The NR0562 outputs 24-bit data left-justified in a 32-bit I2S frame;
// we shift right 16 bits to produce standard 16-bit PCM.

#include "platform/board_config.hpp"

#include <cstdint>
#include <vector>

namespace fridge_ink::platform {

// Initialise the I2S peripheral for the NR0562 microphone.
// Returns true on success. Safe to call again after deinit.
bool mic_driver_init(const MicPins& pins);

// True if the driver is installed and ready to record.
bool mic_driver_ready();

// Record up to max_ms milliseconds of audio.
// Blocks until the requested duration has been captured (or an error occurs).
// Returns signed 16-bit PCM at 16 kHz mono, or an empty vector on failure.
std::vector<int16_t> mic_record_pcm(uint32_t max_ms);

// Uninstall the I2S driver and free resources.
// Safe to call even if init was never called or already deinit'd.
void mic_driver_deinit();

}  // namespace fridge_ink::platform
