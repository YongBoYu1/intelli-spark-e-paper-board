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
#include <cstdlib>

namespace {

constexpr const char* kTag = "main";
constexpr TickType_t kLoopDelay = pdMS_TO_TICKS(50);
constexpr std::uint64_t kRuntimeTickMs = 1000;

// VCOM sweep state — 'v' key enters VCOM mode, next 2 hex chars set value
bool vcom_mode = false;
char vcom_hex[3] = {0, 0, 0};
int vcom_hex_pos = 0;

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

bool is_hex_char(uint8_t ch) {
  return (ch >= '0' && ch <= '9') || (ch >= 'a' && ch <= 'f') || (ch >= 'A' && ch <= 'F');
}

void dispatch_input_byte(fridge_ink::app::Runtime& runtime,
                         fridge_ink::platform::Display& display,
                         const std::uint8_t byte) {
  // VCOM sweep mode: waiting for 2 hex digits after 'v'
  if (vcom_mode) {
    if (is_hex_char(byte)) {
      vcom_hex[vcom_hex_pos++] = static_cast<char>(byte);
      if (vcom_hex_pos >= 2) {
        vcom_hex[2] = '\0';
        const auto value = static_cast<uint8_t>(strtol(vcom_hex, nullptr, 16));
        ESP_LOGI(kTag, ">>> VCOM sweep: v%s → 0x82 = 0x%02X", vcom_hex, value);
        display.set_vcom_and_refresh(value);
        vcom_mode = false;
        vcom_hex_pos = 0;
      }
    } else {
      ESP_LOGW(kTag, "VCOM mode cancelled (non-hex char '%c')", byte);
      vcom_mode = false;
      vcom_hex_pos = 0;
    }
    return;
  }

  switch (byte) {
    case 'v':
    case 'V':
      ESP_LOGI(kTag, "VCOM sweep mode: enter 2 hex digits (e.g. v08, v10, v20)");
      vcom_mode = true;
      vcom_hex_pos = 0;
      break;
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

void poll_serial_input(fridge_ink::app::Runtime& runtime,
                       fridge_ink::platform::Display& display) {
  std::uint8_t buf[32];
  const int n = usb_serial_jtag_read_bytes(buf, sizeof(buf), 0);
  if (n <= 0) {
    return;
  }
  for (int i = 0; i < n; ++i) {
    dispatch_input_byte(runtime, display, buf[i]);
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
    ESP_LOGI(kTag, "Monitor controls: a/d = rotate, c = click, v<HH> = VCOM sweep (e.g. v08, v10, v20)");
  }

  std::uint64_t last_tick_ms = fridge_ink::platform::monotonic_ms();

  while (true) {
    if (serial_input_ok) {
      poll_serial_input(runtime, *display);
    }

    const std::uint64_t now_ms = fridge_ink::platform::monotonic_ms();
    runtime.flush_deferred(now_ms);
    if ((now_ms - last_tick_ms) >= kRuntimeTickMs) {
      runtime.dispatch(fridge_ink::app::Event::Tick(now_ms));
      last_tick_ms = now_ms;
    }
    vTaskDelay(kLoopDelay);
  }
}
