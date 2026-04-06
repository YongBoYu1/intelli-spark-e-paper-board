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
#include <ctime>

namespace {

constexpr const char* kTag = "main";
constexpr TickType_t kLoopDelay = pdMS_TO_TICKS(50);
constexpr std::uint64_t kRuntimeTickMs = 1000;

// VCOM sweep state — 'v' key enters VCOM mode, next 2 hex chars set value
bool vcom_mode = false;
char vcom_hex[3] = {0, 0, 0};
int vcom_hex_pos = 0;
bool time_sync_mode = false;
char time_epoch_digits[21] = {0};
int time_epoch_pos = 0;

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

bool is_digit_char(uint8_t ch) {
  return ch >= '0' && ch <= '9';
}

void log_monitor_controls() {
  ESP_LOGI(kTag, "Controls (? to print again)");
  ESP_LOGI(kTag, "A/D or H/L: rotate");
  ESP_LOGI(kTag, "C or Enter/Space: click");
  ESP_LOGI(kTag, "M: long-press (toggle Home nav overlay)");
  ESP_LOGI(kTag, "B: back (toggle/close menu, or return Home)");
  ESP_LOGI(kTag, "T<epoch> + Enter: sync wall clock");
  ESP_LOGI(kTag, "V<HH>: VCOM sweep (2 hex digits)");
  ESP_LOGI(kTag, "中文: A/D旋转, C点击, M长按, B返回");
}

void log_monitor_controls_summary() {
  ESP_LOGI(
      kTag,
      "Controls: a/d rotate, c click, m long-press, b back, "
      "t<epoch> sync time, v<HH> vcom, ?|/|p help");
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

  // Time sync mode: waiting for unix epoch seconds after 't'
  if (time_sync_mode) {
    if (byte == '\r' || byte == '\n') {
      if (time_epoch_pos <= 0) {
        ESP_LOGW(kTag, "Time sync ignored: empty epoch payload");
      } else {
        time_epoch_digits[time_epoch_pos] = '\0';
        const auto epoch_seconds = static_cast<std::time_t>(
            strtoull(time_epoch_digits, nullptr, 10));
        if (fridge_ink::platform::set_wall_time_seconds(epoch_seconds)) {
          ESP_LOGI(kTag, "Wall clock synced via serial: epoch=%llu",
                   static_cast<unsigned long long>(epoch_seconds));
          runtime.dispatch(fridge_ink::app::Event::Tick(fridge_ink::platform::monotonic_ms()));
        } else {
          ESP_LOGW(kTag, "Time sync rejected: invalid epoch=%s", time_epoch_digits);
        }
      }
      time_sync_mode = false;
      time_epoch_pos = 0;
    } else if (is_digit_char(byte) &&
               time_epoch_pos < static_cast<int>(sizeof(time_epoch_digits) - 1)) {
      time_epoch_digits[time_epoch_pos++] = static_cast<char>(byte);
    } else {
      ESP_LOGW(kTag, "Time sync cancelled (unexpected char '%c')", byte);
      time_sync_mode = false;
      time_epoch_pos = 0;
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
    case '?':
    case '/':
    case 'p':
    case 'P':
      log_monitor_controls_summary();
      log_monitor_controls();
      break;
    case 't':
    case 'T':
      ESP_LOGI(kTag, "Time sync mode: enter unix epoch seconds, then press Enter (e.g. t1743621000)");
      time_sync_mode = true;
      time_epoch_pos = 0;
      break;
    case 'a':
    case 'A':
    case 'h':
    case 'H':
      runtime.dispatch(fridge_ink::app::Event::Rotate(-1, fridge_ink::platform::monotonic_ms()));
      break;
    case 'd':
    case 'D':
    case 'l':
    case 'L':
      runtime.dispatch(fridge_ink::app::Event::Rotate(1, fridge_ink::platform::monotonic_ms()));
      break;
    case 'c':
    case 'C':
    case '\r':
    case '\n':
    case ' ':
      runtime.dispatch(fridge_ink::app::Event::Click(fridge_ink::platform::monotonic_ms()));
      break;
    case 'm':
    case 'M':
      runtime.dispatch(fridge_ink::app::Event::LongPress(fridge_ink::platform::monotonic_ms()));
      break;
    case 'b':
    case 'B':
      runtime.dispatch(fridge_ink::app::Event::Back(fridge_ink::platform::monotonic_ms()));
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
    // Keep startup print compact and robust after heavy panel-init logs.
    log_monitor_controls_summary();
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
