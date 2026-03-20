#pragma once

#include <cstdint>

namespace fridge_ink::app {

enum class EventType {
  Tick,
  Rotate,
  Click,
};

struct Event {
  EventType type{EventType::Tick};
  int rotate_delta{0};
  std::uint64_t now_ms{0};

  static Event Tick(std::uint64_t now_ms_value) {
    Event event;
    event.type = EventType::Tick;
    event.now_ms = now_ms_value;
    return event;
  }

  static Event Rotate(int delta) {
    Event event;
    event.type = EventType::Rotate;
    event.rotate_delta = delta >= 0 ? 1 : -1;
    return event;
  }

  static Event Click() {
    Event event;
    event.type = EventType::Click;
    return event;
  }
};

}  // namespace fridge_ink::app
