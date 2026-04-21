#include "app/runtime.hpp"
#include "app/events.hpp"
#include "app/reducer.hpp"
#include "platform/board_config.hpp"
#include "platform/clock.hpp"
#include "platform/display.hpp"
#include "platform/live_data_provider.hpp"
#include "platform/mic_driver.hpp"
#include "platform/voice_client.hpp"
#include "platform/ntp_sync.hpp"
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
#include <memory>

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
// Minimum peak amplitude to consider audio valid (prevents sending noise to backend).
// NR0562 full-scale ~32768; speech typically peaks above 2000 at ~20cm distance.
constexpr int16_t kMinPeakAmplitude = 800;

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
// Cooldown: after recording completes, ignore 'r' for 2 seconds.
static std::atomic<uint64_t> g_recording_done_ms{0};
static constexpr uint64_t kRecordCooldownMs = 2000;

// Runtime pointer set in app_main().
static fridge_ink::app::Runtime* g_runtime{nullptr};
static std::unique_ptr<fridge_ink::platform::Display> g_display{};
static std::unique_ptr<fridge_ink::app::Runtime> g_runtime_owner{};

// Pending voice actions queue — written by voice_record_task, consumed by main loop.
// Protected by g_voice_mutex so cross-task access is safe.
static SemaphoreHandle_t g_voice_mutex{nullptr};
static std::vector<fridge_ink::platform::VoiceAction> g_pending_voice_actions{};

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

  // Check peak amplitude — skip POST if audio is just noise (no speech detected).
  int16_t peak = 0;
  for (const int16_t s : pcm) {
    const int16_t a = s < 0 ? -s : s;
    if (a > peak) peak = a;
  }
  if (peak < kMinPeakAmplitude) {
    ESP_LOGW(kTag, "[voice] Audio too quiet (peak=%d < %d) — skipping POST",
             static_cast<int>(peak), static_cast<int>(kMinPeakAmplitude));
    // Flush and set cooldown so spurious 'r' won't immediately retry.
    {
      uint8_t flush_buf[64];
      while (usb_serial_jtag_read_bytes(flush_buf, sizeof(flush_buf), 0) > 0) {}
    }
    g_recording_done_ms.store(fridge_ink::platform::monotonic_ms());
    g_recording.store(false);
    vTaskDelete(nullptr);
    return;
  }

  ESP_LOGI(kTag, "[voice] Sending to backend… (peak=%d)", static_cast<int>(peak));
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
    // Enqueue for main loop to apply (display access must be on main task).
    if (g_voice_mutex) {
      xSemaphoreTake(g_voice_mutex, portMAX_DELAY);
      for (auto& a : resp.actions) {
        g_pending_voice_actions.push_back(std::move(a));
      }
      xSemaphoreGive(g_voice_mutex);
    }
  }

  // Flush any 'r' bytes that piled up in the USB-JTAG buffer during recording.
  {
    uint8_t flush_buf[64];
    while (usb_serial_jtag_read_bytes(flush_buf, sizeof(flush_buf), 0) > 0) {}
  }
  g_recording_done_ms.store(fridge_ink::platform::monotonic_ms());
  g_recording.store(false);
  vTaskDelete(nullptr);
}

static void trigger_voice_recording() {
  if (!fridge_ink::platform::mic_driver_ready()) {
    ESP_LOGW(kTag, "[voice] Mic driver not ready — skipping");
    return;
  }
  // Reject spurious triggers during cooldown period after last recording.
  const uint64_t done_ms = g_recording_done_ms.load();
  if (done_ms > 0) {
    const uint64_t now_ms = fridge_ink::platform::monotonic_ms();
    if ((now_ms - done_ms) < kRecordCooldownMs) {
      return;  // silent drop — no log spam
    }
  }
  if (g_recording.exchange(true)) {
    ESP_LOGW(kTag, "[voice] Already recording — ignoring");
    return;
  }
  // 12 KB stack: recording + HTTP response parsing + vector operations.
  xTaskCreate(voice_record_task, "voice_rec", 12288, nullptr, 5, nullptr);
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
      "o record voice, t<epoch> sync time, v<HH> vcom, ?|/|p help");
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
    case 'o':
    case 'O':
      ESP_LOGI(kTag, ">>> Voice recording triggered (o key)");
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

  g_voice_mutex = xSemaphoreCreateMutex();
  if (g_voice_mutex == nullptr) {
    ESP_LOGE(kTag, "Failed to create voice mutex — halting");
    return;
  }

  g_display = fridge_ink::platform::make_default_display();
  g_runtime_owner = std::make_unique<fridge_ink::app::Runtime>(*g_display);
  g_runtime = g_runtime_owner.get();
  g_runtime->boot();

  // Connect to WiFi then sync time + detect timezone via IP geolocation.
  // Both steps are non-fatal: the device runs offline if they fail.
  {
    constexpr const char* kSsid     = CONFIG_WIFI_SSID;
    constexpr const char* kPassword = CONFIG_WIFI_PASSWORD;
    if (kSsid[0] != '\0') {
      const bool wifi_ok =
          fridge_ink::platform::wifi_connect(kSsid, kPassword, 15000);
      if (wifi_ok) {
        // NTP time sync + IP-based timezone detection (20 s combined budget).
        fridge_ink::platform::ntp_sync(20000);
      }
    } else {
      ESP_LOGW(kTag, "CONFIG_WIFI_SSID not set — WiFi / NTP skipped");
    }
  }

  fridge_ink::platform::live_data_bootstrap(
      fridge_ink::platform::active_timezone_name().c_str(),
      g_runtime->state().dashboard.location.c_str());

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
      poll_serial_input(*g_runtime, *g_display);
    }

    // Drain pending voice actions (enqueued from voice_record_task).
    if (g_voice_mutex && xSemaphoreTake(g_voice_mutex, 0) == pdTRUE) {
      if (!g_pending_voice_actions.empty()) {
        std::vector<fridge_ink::platform::VoiceAction> actions;
        actions.swap(g_pending_voice_actions);
        xSemaphoreGive(g_voice_mutex);
        g_runtime->dispatch_voice_actions(actions);
      } else {
        xSemaphoreGive(g_voice_mutex);
      }
    }

    const std::uint64_t now_ms = fridge_ink::platform::monotonic_ms();

    g_runtime->flush_deferred(now_ms);
    if ((now_ms - last_tick_ms) >= kRuntimeTickMs) {
      g_runtime->dispatch(fridge_ink::app::Event::Tick(now_ms));
      last_tick_ms = now_ms;
    }
    vTaskDelay(kLoopDelay);
  }
}
