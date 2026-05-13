#pragma once

#include "platform/board_config.hpp"

#include <cstdint>

namespace fridge_ink::platform {

enum class EncoderEvent : uint8_t {
  RotateCW,      // S1/S2 → clockwise one detent
  RotateCCW,     // S1/S2 → counter-clockwise one detent
  Click,         // KEY short press  (< 800 ms)
  VoiceTrigger,  // KEY long  press  (≥ 800 ms) — push-to-talk
};

// Initialise GPIO inputs and start the 2 ms polling task.
// Returns false if any pin is < 0 or GPIO init fails (non-fatal).
bool encoder_init(const EncoderPins& pins);

// Non-blocking dequeue.  Fills *out and returns true when an event is ready.
// Returns false immediately when the queue is empty.
bool encoder_poll(EncoderEvent* out);

}  // namespace fridge_ink::platform
