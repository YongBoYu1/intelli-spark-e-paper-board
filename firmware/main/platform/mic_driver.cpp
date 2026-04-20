#include "platform/mic_driver.hpp"

#include "driver/i2s.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include <cinttypes>
#include <cstring>

namespace fridge_ink::platform {
namespace {

static const char* kTag = "mic_driver";

// I2S port — NUM_0 is free (display uses SPI, not I2S).
static constexpr i2s_port_t kPort = I2S_NUM_0;

// Audio parameters matching the voice backend expectation.
static constexpr uint32_t kSampleRateHz  = 16000;
static constexpr int      kDmaBufCount   = 4;
static constexpr int      kDmaBufSamples = 256;   // int32_t frames per DMA buf

// Number of warm-up DMA buffers to discard on init (hardware settling).
static constexpr int kWarmupBuffers = 3;

static bool g_ready = false;

}  // namespace

// ── Public API ────────────────────────────────────────────────────────────────

bool mic_driver_init(const MicPins& pins) {
  if (g_ready) {
    ESP_LOGW(kTag, "Already initialised — skipping");
    return true;
  }

  // I2S config: master RX, 32-bit frame (NR0562 is 24-bit left-justified).
  const i2s_config_t cfg = {
      .mode                 = static_cast<i2s_mode_t>(I2S_MODE_MASTER | I2S_MODE_RX),
      .sample_rate          = kSampleRateHz,
      .bits_per_sample      = I2S_BITS_PER_SAMPLE_32BIT,
      .channel_format       = I2S_CHANNEL_FMT_ONLY_LEFT,  // L/R pin → GND
      .communication_format = I2S_COMM_FORMAT_STAND_I2S,
      .intr_alloc_flags     = ESP_INTR_FLAG_LEVEL1,
      .dma_buf_count        = kDmaBufCount,
      .dma_buf_len          = kDmaBufSamples,
      .use_apll             = false,
      .tx_desc_auto_clear   = false,
      .fixed_mclk           = 0,
  };

  const i2s_pin_config_t pin_cfg = {
      .mck_io_num   = I2S_PIN_NO_CHANGE,
      .bck_io_num   = pins.sck,
      .ws_io_num    = pins.ws,
      .data_out_num = I2S_PIN_NO_CHANGE,
      .data_in_num  = pins.sd,
  };

  esp_err_t err = i2s_driver_install(kPort, &cfg, 0, nullptr);
  if (err != ESP_OK) {
    ESP_LOGE(kTag, "i2s_driver_install failed: %s", esp_err_to_name(err));
    return false;
  }

  err = i2s_set_pin(kPort, &pin_cfg);
  if (err != ESP_OK) {
    ESP_LOGE(kTag, "i2s_set_pin failed: %s", esp_err_to_name(err));
    i2s_driver_uninstall(kPort);
    return false;
  }

  i2s_zero_dma_buffer(kPort);

  // Discard warm-up buffers so the first real recording is clean.
  static int32_t discard[kDmaBufSamples];
  for (int i = 0; i < kWarmupBuffers; i++) {
    size_t dummy = 0;
    i2s_read(kPort, discard, sizeof(discard), &dummy, pdMS_TO_TICKS(200));
  }

  g_ready = true;
  ESP_LOGI(kTag, "I2S mic ready  SCK=%d WS=%d SD=%d  %" PRIu32 " Hz mono 16-bit",
           pins.sck, pins.ws, pins.sd, kSampleRateHz);
  return true;
}

bool mic_driver_ready() {
  return g_ready;
}

std::vector<int16_t> mic_record_pcm(uint32_t max_ms) {
  if (!g_ready) {
    ESP_LOGE(kTag, "mic_record_pcm: driver not initialised");
    return {};
  }

  const size_t target_samples = (static_cast<uint64_t>(kSampleRateHz) * max_ms) / 1000;

  std::vector<int16_t> pcm;
  pcm.reserve(target_samples);

  // Single DMA read buffer (int32_t, reused each iteration).
  static int32_t raw[kDmaBufSamples];

  const TickType_t deadline =
      xTaskGetTickCount() + pdMS_TO_TICKS(max_ms + 500 /*margin*/);

  ESP_LOGI(kTag, "Recording %" PRIu32 " ms  (%zu samples expected)", max_ms, target_samples);

  while (pcm.size() < target_samples) {
    if (xTaskGetTickCount() > deadline) {
      ESP_LOGW(kTag, "Recording deadline exceeded — truncating");
      break;
    }

    size_t bytes_read = 0;
    const esp_err_t err =
        i2s_read(kPort, raw, sizeof(raw), &bytes_read, pdMS_TO_TICKS(300));
    if (err != ESP_OK || bytes_read == 0) continue;

    const int n = static_cast<int>(bytes_read / sizeof(int32_t));
    for (int i = 0; i < n && pcm.size() < target_samples; i++) {
      // NR0562: 24-bit left-justified in 32-bit frame.
      // Shift right 16 to obtain a standard signed 16-bit PCM sample.
      pcm.push_back(static_cast<int16_t>(raw[i] >> 16));
    }
  }

  // Log peak amplitude for quick sanity check.
  int32_t peak = 0;
  for (int16_t s : pcm) {
    const int32_t a = s < 0 ? -static_cast<int32_t>(s) : static_cast<int32_t>(s);
    if (a > peak) peak = a;
  }
  ESP_LOGI(kTag, "Captured %zu samples (%.2f s)  peak=%ld",
           pcm.size(), pcm.size() / static_cast<float>(kSampleRateHz),
           static_cast<long>(peak));

  if (peak == 0) {
    ESP_LOGW(kTag, "Peak is zero — check wiring (SCK/WS/SD/VDD/GND)");
  }

  return pcm;
}

void mic_driver_deinit() {
  if (!g_ready) return;
  i2s_driver_uninstall(kPort);
  g_ready = false;
  ESP_LOGI(kTag, "I2S mic driver released");
}

}  // namespace fridge_ink::platform
