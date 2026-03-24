#include "app/runtime.hpp"
#include "app/events.hpp"
#include "platform/clock.hpp"
#include "platform/display.hpp"

#include "driver/usb_serial_jtag.h"
#include "esp_err.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "esp_log.h"

#include <cstdint>

namespace {

constexpr const char* kTag = "main";
constexpr TickType_t kLoopDelay = pdMS_TO_TICKS(50);
constexpr std::uint64_t kRuntimeTickMs = 1000;

bool setup_serial_input() {
  usb_serial_jtag_driver_config_t cfg{};
  cfg.rx_buffer_size = 256;
  cfg.tx_buffer_size = 256;
  const esp_err_t err = usb_serial_jtag_driver_install(&cfg);
  if (err == ESP_OK || err == ESP_ERR_INVALID_STATE) {
    return true;
  }
  ESP_LOGW(kTag, "usb_serial_jtag_driver_install failed: %s", esp_err_to_name(err));
  return false;
}

void dispatch_input_byte(fridge_ink::app::Runtime& runtime, const std::uint8_t byte) {
  switch (byte) {
    case 'a':
    case 'A':
    case 'h':
    case 'H':
      runtime.dispatch(fridge_ink::app::Event::Rotate(-1));
      break;
    case 'd':
    case 'D':
    case 'l':
    case 'L':
      runtime.dispatch(fridge_ink::app::Event::Rotate(1));
      break;
    case 'c':
    case 'C':
    case '\r':
    case '\n':
    case ' ':
      runtime.dispatch(fridge_ink::app::Event::Click());
      break;
    default:
      break;
  }
}

void poll_serial_input(fridge_ink::app::Runtime& runtime) {
  std::uint8_t buf[32];
  const int n = usb_serial_jtag_read_bytes(buf, sizeof(buf), 0);
  if (n <= 0) {
    return;
  }
  for (int i = 0; i < n; ++i) {
    dispatch_input_byte(runtime, buf[i]);
  }
}

}  // namespace

extern "C" void app_main(void) {
  ESP_LOGI(kTag, "Booting Fridge Ink firmware runtime V0");

  auto display = fridge_ink::platform::make_default_display();
  fridge_ink::app::Runtime runtime(*display);
  runtime.boot();

  const bool serial_input_ok = setup_serial_input();
  if (serial_input_ok) {
    ESP_LOGI(kTag, "Monitor controls: a/d = rotate, c = click");
  }

  std::uint64_t last_tick_ms = fridge_ink::platform::monotonic_ms();

  while (true) {
    if (serial_input_ok) {
      poll_serial_input(runtime);
    }

    const std::uint64_t now_ms = fridge_ink::platform::monotonic_ms();
    if ((now_ms - last_tick_ms) >= kRuntimeTickMs) {
      runtime.dispatch(fridge_ink::app::Event::Tick(now_ms));
      last_tick_ms = now_ms;
    }
    vTaskDelay(kLoopDelay);
  }
}
