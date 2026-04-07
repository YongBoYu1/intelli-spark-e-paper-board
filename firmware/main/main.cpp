#include "app/runtime.hpp"
#include "app/events.hpp"
#include "platform/board_config.hpp"
#include "platform/clock.hpp"
#include "platform/display.hpp"
#include "platform/mic_driver.hpp"
#include "platform/voice_client.hpp"
#include "platform/wifi_driver.hpp"

#include "driver/usb_serial_jtag.h"
#include "esp_err.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "esp_log.h"

#include <atomic>
#include <cinttypes>
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

// ── Voice recording ───────────────────────────────────────────────────────────
// Duration of a single push-to-talk capture (milliseconds).
// Keep ≤ 5000 ms to stay within ESP32-S3 internal SRAM limits (~512 KB).
constexpr uint32_t kRecordDurationMs = 5000;

// Voice backend configuration.
// Set VOICE_API_URL to the address of the running backend/voice_api server.
// If WiFi / backend is not configured, the recording will still complete and
// log audio stats; only the HTTP POST will fail gracefully.
static const fridge_ink::platform::VoiceClientConfig kVoiceCfg = {
    .base_url   = CONFIG_VOICE_API_URL,    // defined in sdkconfig / menuconfig
    .auth_token = (sizeof(CONFIG_VOICE_API_TOKEN) > 1)
                      ? CONFIG_VOICE_API_TOKEN
                      : nullptr,           // nullptr disables Bearer header
    .timezone   = "UTC",
    .locale     = "en-US",
    .timeout_ms = 20000,
};

// Prevent concurrent recordings.
static std::atomic<bool> g_recording{false};
static uint32_t          g_record_seq{0};

// FreeRTOS task: capture PCM → POST to backend → log result.
static void voice_record_task(void* /*arg*/) {
  const uint32_t seq = g_record_seq++;

  char req_id[32];
  snprintf(req_id, sizeof(req_id), "esp32-%04lu", static_cast<unsigned long>(seq));

  ESP_LOGI(kTag, "[voice] Recording %" PRIu32 " ms  req=%s", kRecordDurationMs, req_id);

  auto pcm = fridge_ink::platform::mic_record_pcm(kRecordDurationMs);
  if (pcm.empty()) {
    ESP_LOGE(kTag, "[voice] No audio captured — aborting");
    g_recording.store(false);
    vTaskDelete(nullptr);
    return;
  }

  ESP_LOGI(kTag, "[voice] Sending to backend…");
  const auto resp = fridge_ink::platform::voice_interpret_pcm(kVoiceCfg, pcm, req_id);

  if (!resp.ok) {
    ESP_LOGW(kTag, "[voice] Backend error: %s", resp.error.c_str());
  } else if (resp.actions.empty()) {
    ESP_LOGI(kTag, "[voice] Backend returned no actions (no_action)");
  } else {
    for (const auto& a : resp.actions) {
      ESP_LOGI(kTag, "[voice] Action → tool=%s  args=%s",
               a.tool.c_str(), a.args_json.c_str());
    }
  }

  g_recording.store(false);
  vTaskDelete(nullptr);
}

static void trigger_voice_recording() {
  if (!fridge_ink::platform::mic_driver_ready()) {
    ESP_LOGW(kTag, "[voice] Mic driver not ready — skipping");
    return;
  }
  if (g_recording.exchange(true)) {
    ESP_LOGW(kTag, "[voice] Already recording — ignoring");
    return;
  }
  // 8 KB stack is sufficient for recording + HTTP; increase if stack overflow.
  xTaskCreate(voice_record_task, "voice_rec", 8192, nullptr, 5, nullptr);
}

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
  ESP_LOGI(kTag, "R: record voice (5 s) → POST to voice backend");
  ESP_LOGI(kTag, "T<epoch> + Enter: sync wall clock");
  ESP_LOGI(kTag, "V<HH>: VCOM sweep (2 hex digits)");
  ESP_LOGI(kTag, "中文: A/D旋转, C点击, M长按, B返回, R录音");
}

void log_monitor_controls_summary() {
  ESP_LOGI(
      kTag,
      "Controls: a/d rotate, c click, m long-press, b back, "
      "r record voice, t<epoch> sync time, v<HH> vcom, ?|/|p help");
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
    case 'r':
    case 'R':
      ESP_LOGI(kTag, ">>> Voice recording triggered (r key)");
      trigger_voice_recording();
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

  // Connect to WiFi (credentials set via sdkconfig / menuconfig).
  // Non-fatal: voice HTTP POST will simply fail if not connected.
  {
    constexpr const char* kSsid     = CONFIG_WIFI_SSID;
    constexpr const char* kPassword = CONFIG_WIFI_PASSWORD;
    if (kSsid[0] != '\0') {
      fridge_ink::platform::wifi_connect(kSsid, kPassword, 15000);
    } else {
      ESP_LOGW(kTag, "CONFIG_WIFI_SSID not set — WiFi skipped");
    }
  }

  // Initialise I2S microphone driver (non-fatal if it fails).
  const auto& board = fridge_ink::platform::default_board_config();
  if (fridge_ink::platform::has_ready_mic_pin_map(board)) {
    const bool mic_ok = fridge_ink::platform::mic_driver_init(board.mic_pins);
    if (!mic_ok) {
      ESP_LOGW(kTag, "Mic driver init failed — voice recording disabled");
    }
  } else {
    ESP_LOGW(kTag, "Mic pins not configured — voice recording disabled");
  }

  const bool serial_input_ok = setup_serial_input();
  if (serial_input_ok) {
    // Flush any garbage bytes buffered during USB-JTAG/bootloader init
    // (prevents spurious 'r' keypresses triggering voice recording at boot).
    {
      std::uint8_t flush_buf[64];
      while (usb_serial_jtag_read_bytes(flush_buf, sizeof(flush_buf), 0) > 0) {}
    }
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
