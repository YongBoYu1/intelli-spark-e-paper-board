#include "platform/board_config.hpp"
#include "platform/display.hpp"
#include "platform/panel_config.hpp"

#include "driver/gpio.h"
#include "driver/spi_master.h"
#include "esp_log.h"
#include "esp_rom_sys.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include <algorithm>
#include <array>
#include <cstdint>
#include <memory>
#include <vector>

namespace fridge_ink::platform {
namespace {

constexpr const char* kTag = "display";

constexpr int kPowerOnTimeoutMs = 10000;
constexpr int kPowerOffTimeoutMs = 10000;
constexpr int kRefreshTimeoutMs = 25000;
constexpr int kPowerStabilizeMs = 50;
constexpr int kPostRefreshDelayMs = 100;
constexpr int kResetHighMs = 20;
constexpr int kResetLowUs = 2000;
constexpr int kSpiClockHz = 4 * 1000 * 1000;  // Match Python RPi driver (was 2MHz)
constexpr size_t kSpiChunkBytes = 2048;
constexpr size_t kFillChunkBytes = 256;
constexpr bool kPowerOffAfterRefresh = false;
constexpr bool kUseInvertedOldBufferForFullRefresh = true;
constexpr int kUiDilateRadius = 0;
constexpr bool kEnablePartialRefresh = true;
// Hardware contrast regression note:
// OTP-LUT init path caused severe low-contrast/washed rendering on current panel
// batch. Keep host-LUT full-refresh profile enabled until driver parity can be
// completed without contrast loss.
constexpr bool kUseHostLutWaveformProfile = true;
// Match Waveshare epd7in5_V2_old host-LUT path by default.
constexpr bool kUseHostLutDualPlaneRefresh = true;
constexpr bool kUseHostLutEvsRegister = true;
constexpr uint8_t kHostLutDataIntervalFirstByte = 0x10;
constexpr uint8_t kHostLutDataIntervalSecondByte = 0x07;
constexpr uint8_t kHostLutEvsRegisterValue = 0x02;
constexpr uint8_t kHostLutVcomDc = 0x18;
constexpr bool kUseHostLutOptRegister = true;
constexpr uint8_t kHostLutOptXon = 0x00;
constexpr uint8_t kHostLutOptValue = 0x00;
constexpr bool kUseHostLutWhitePrecleanPass = false;
constexpr int kHostLutFullRefreshPasses = 1;
constexpr bool kUseHostLutWhiteBoostPass = false;
// Align dual-plane payload order with Waveshare EPD_7in5_V2_old.c:
//   0x10 <- image, 0x13 <- ~image
constexpr bool kUseHostLutLegacyPlaneOrder = false;
// Keep disabled in normal runtime to reduce navigation lag; enable only when
// doing low-level driver debugging.
constexpr bool kEnableDisplayTraceLogs = false;
// Python epd7in5_V2 busy-wait path polls BUSY GPIO directly (no extra 0x71).
constexpr bool kBusyPollWithStatusCommand = false;
// UI framebuffer follows Python convention: 0=black, 1=white.
constexpr bool kFramebufferBlackBitIsZero = true;
// Some panel batches behave as 1=black at transport level. Keep this explicit.
constexpr bool kPanelBlackBitIsZero = false;

gpio_num_t to_gpio_num(const int pin) {
  return static_cast<gpio_num_t>(pin);
}

constexpr uint8_t kFramebufferBlackFill = kFramebufferBlackBitIsZero ? 0x00 : 0xFF;
constexpr uint8_t kFramebufferWhiteFill = kFramebufferBlackBitIsZero ? 0xFF : 0x00;

constexpr uint8_t map_framebuffer_byte_to_panel(const uint8_t value) {
  if constexpr (kFramebufferBlackBitIsZero == kPanelBlackBitIsZero) {
    return value;
  }
  return static_cast<uint8_t>(~value);
}

constexpr uint8_t panel_black_fill_byte() {
  return map_framebuffer_byte_to_panel(kFramebufferBlackFill);
}

constexpr uint8_t panel_white_fill_byte() {
  return map_framebuffer_byte_to_panel(kFramebufferWhiteFill);
}

constexpr std::array<uint8_t, 42> kHostLutVcom{
    0x00, 0x32, 0x32, 0x00, 0x00, 0x01, 0x00, 0x0A, 0x0A, 0x00, 0x00, 0x00,
    0x00, 0x28, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
};

constexpr std::array<uint8_t, 42> kHostLutWw{
    0x60, 0x32, 0x32, 0x00, 0x00, 0x01, 0x60, 0x0A, 0x0A, 0x00, 0x00, 0x00,
    0x80, 0x28, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
};

constexpr std::array<uint8_t, 42> kHostLutBw{
    0x60, 0x32, 0x32, 0x00, 0x00, 0x01, 0x60, 0x0A, 0x0A, 0x00, 0x00, 0x00,
    0x80, 0x28, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
};

constexpr std::array<uint8_t, 42> kHostLutWb{
    0x90, 0x32, 0x32, 0x00, 0x00, 0x01, 0x60, 0x0A, 0x0A, 0x00, 0x00, 0x00,
    0x40, 0x28, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
};

constexpr std::array<uint8_t, 42> kHostLutBb{
    0x90, 0x32, 0x32, 0x00, 0x00, 0x01, 0x60, 0x0A, 0x0A, 0x00, 0x00, 0x00,
    0x40, 0x28, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
};

// ── Image utility helpers (internal) ─────────────────────────────────────────

void set_black_pixel_raw(std::vector<uint8_t>& image, const int x, const int y) {
  if (x < 0 || x >= kPanelWidth || y < 0 || y >= kPanelHeight) {
    return;
  }
  const int offset = (y * kPanelWidthBytes) + (x / 8);
  const uint8_t bit = static_cast<uint8_t>(0x80U >> (x % 8));
  if constexpr (kFramebufferBlackBitIsZero) {
    image[offset] = static_cast<uint8_t>(image[offset] & static_cast<uint8_t>(~bit));
  } else {
    image[offset] = static_cast<uint8_t>(image[offset] | bit);
  }
}

bool is_black_pixel(const std::vector<uint8_t>& image, const int x, const int y) {
  if (x < 0 || x >= kPanelWidth || y < 0 || y >= kPanelHeight) {
    return false;
  }
  const int offset = (y * kPanelWidthBytes) + (x / 8);
  const uint8_t bit = static_cast<uint8_t>(0x80U >> (x % 8));
  if constexpr (kFramebufferBlackBitIsZero) {
    return (image[offset] & bit) == 0;
  }
  return (image[offset] & bit) != 0;
}

std::size_t count_black_bits(const std::vector<uint8_t>& image) {
  // Count black bits using framebuffer convention.
  std::size_t count = 0;
  for (const uint8_t value : image) {
    if constexpr (kFramebufferBlackBitIsZero) {
      count += static_cast<std::size_t>(__builtin_popcount(static_cast<unsigned int>(
          static_cast<uint8_t>(~value))));
    } else {
      count += static_cast<std::size_t>(
          __builtin_popcount(static_cast<unsigned int>(value)));
    }
  }
  return count;
}

std::vector<uint8_t> dilate_black_pixels(const std::vector<uint8_t>& source, const int radius) {
  if (radius <= 0) {
    return source;
  }
  std::vector<uint8_t> out = source;
  for (int y = 0; y < kPanelHeight; ++y) {
    for (int x = 0; x < kPanelWidth; ++x) {
      if (!is_black_pixel(source, x, y)) {
        continue;
      }
      for (int dy = -radius; dy <= radius; ++dy) {
        for (int dx = -radius; dx <= radius; ++dx) {
          set_black_pixel_raw(out, x + dx, y + dy);
        }
      }
    }
  }
  return out;
}

DirtyRect clip_dirty_rect(const DirtyRect& rect) {
  return {
      std::max(0, std::min(kPanelWidth, rect.x0)),
      std::max(0, std::min(kPanelHeight, rect.y0)),
      std::max(0, std::min(kPanelWidth, rect.x1)),
      std::max(0, std::min(kPanelHeight, rect.y1)),
  };
}

bool is_valid_dirty_rect(const DirtyRect& rect) {
  return rect.x1 > rect.x0 && rect.y1 > rect.y0;
}

// ── EpaperDisplay — hardware SPI driver for UC8176 panel ─────────────────────

class EpaperDisplay final : public Display {
 public:
  void init() override {
    board_ = default_board_config();
    ESP_LOGI(kTag, "Board target: %s", board_.target);
    ESP_LOGI(kTag, "Board name: %s", board_.board_name);
    ESP_LOGI(kTag, "Display: %s", board_.display_name);
    ESP_LOGI(kTag, "Display pin map ready: %s",
             has_ready_display_pin_map(board_) ? "yes" : "no");

    if (!has_ready_display_pin_map(board_)) {
      ESP_LOGW(kTag, "Display pin map is not ready. Rendering will stay log-only.");
      return;
    }

    if (!init_gpio()) {
      return;
    }
    if (!init_spi()) {
      return;
    }

    reset_panel();
    if (!init_panel_registers()) {
      return;
    }
    hardware_ready_ = true;
    ESP_LOGI(
        kTag,
        "EPD ready (SCLK=%d, MOSI=%d, CS=%d, DC=%d, RST=%d, BUSY=%d, PWR=%d)",
        board_.display_pins.sclk,
        board_.display_pins.mosi,
        board_.display_pins.cs,
        board_.display_pins.dc,
        board_.display_pins.rst,
        board_.display_pins.busy,
        board_.display_pins.power_enable);
    ESP_LOGI(kTag, "BUSY level after init: %d",
             gpio_get_level(to_gpio_num(board_.display_pins.busy)));
  }

  void clear() override {
    if (!hardware_ready_) {
      return;
    }
    (void)clear_panel_once();
  }

  void display_full(
      const std::vector<uint8_t>& image_in,
      const bool clean_cycle) override {
    if (!hardware_ready_) {
      return;
    }

    auto image = image_in;

    const std::size_t black_bits = count_black_bits(image);
    ESP_LOGI(
        kTag,
        "Rendered bitmap stats: black_bits=%zu ratio=%.4f",
        black_bits,
        static_cast<double>(black_bits) /
            static_cast<double>(kPanelWidth * kPanelHeight));

    if (kUiDilateRadius > 0) {
      image = dilate_black_pixels(image, kUiDilateRadius);
      ESP_LOGI(kTag, "Applied UI stroke dilation radius=%d", kUiDilateRadius);
    }

    if (in_partial_mode_) {
      restore_full_mode();
    }
    if (clean_cycle) {
      (void)clear_panel_once();
    }
    display_bitmap(image);
  }

  void display_partial(
      const std::vector<uint8_t>& image_in,
      const std::vector<DirtyRect>& dirty_rects) override {
    if (!hardware_ready_) {
      return;
    }

    if (!kEnablePartialRefresh) {
      ESP_LOGW(kTag, "Partial refresh disabled in driver, fallback to full");
      display_full(image_in, false);
      return;
    }

    auto image = image_in;
    if (kUiDilateRadius > 0) {
      image = dilate_black_pixels(image, kUiDilateRadius);
    }

    std::vector<DirtyRect> normalized_rects{};
    normalized_rects.reserve(dirty_rects.size());
    for (const DirtyRect& rect : dirty_rects) {
      const DirtyRect clipped = clip_dirty_rect(rect);
      if (is_valid_dirty_rect(clipped)) {
        normalized_rects.push_back(clipped);
      }
    }

    if (normalized_rects.empty()) {
      ESP_LOGW(kTag, "Partial refresh requested with empty rects, fallback to full");
      display_full(image, false);
      return;
    }

    for (const DirtyRect& rect : normalized_rects) {
      display_bitmap_partial(image, rect.x0, rect.y0, rect.x1, rect.y1);
    }
    previous_frame_ = image;
    previous_frame_valid_ = true;
  }

  void set_vcom_and_refresh(uint8_t vcom_value) override {
    if (!hardware_ready_) {
      return;
    }
    ESP_LOGI(kTag, "=== VCOM SWEEP: setting 0x82 = 0x%02X ===", vcom_value);

    // Restore full mode if in partial
    if (in_partial_mode_) {
      restore_full_mode();
    }

    // Set VCOM register
    send_command(0x82);
    send_data(vcom_value);
    vTaskDelay(pdMS_TO_TICKS(10));

    // Force full refresh with current frame (invalidate previous to get max-contrast DTM1=~image)
    previous_frame_valid_ = false;
    if (!previous_frame_.empty()) {
      display_bitmap(previous_frame_);
    } else {
      ESP_LOGW(kTag, "No previous frame to refresh with VCOM change");
    }
  }

 private:
  void init_trace_epoch_if_needed() {
    if (trace_epoch_ms_ == 0) {
      trace_epoch_ms_ = esp_timer_get_time() / 1000;
    }
  }

  int64_t trace_elapsed_ms() const {
    const int64_t now_ms = esp_timer_get_time() / 1000;
    return now_ms - trace_epoch_ms_;
  }

  void trace_command(const uint8_t command) {
    if (!kEnableDisplayTraceLogs) {
      return;
    }
    init_trace_epoch_if_needed();
    ESP_LOGI(
        kTag,
        "[trace %04u +%lldms] CMD 0x%02X",
        static_cast<unsigned>(++trace_seq_),
        static_cast<long long>(trace_elapsed_ms()),
        static_cast<unsigned>(command));
  }

  void trace_data(const uint8_t data) {
    if (!kEnableDisplayTraceLogs) {
      return;
    }
    init_trace_epoch_if_needed();
    ESP_LOGI(
        kTag,
        "[trace %04u +%lldms] DAT 0x%02X <= 0x%02X",
        static_cast<unsigned>(++trace_seq_),
        static_cast<long long>(trace_elapsed_ms()),
        static_cast<unsigned>(last_command_),
        static_cast<unsigned>(data));
  }

  void trace_stream(const char* label, const size_t len) {
    if (!kEnableDisplayTraceLogs) {
      return;
    }
    init_trace_epoch_if_needed();
    ESP_LOGI(
        kTag,
        "[trace %04u +%lldms] %s 0x%02X len=%u",
        static_cast<unsigned>(++trace_seq_),
        static_cast<long long>(trace_elapsed_ms()),
        label,
        static_cast<unsigned>(last_command_),
        static_cast<unsigned>(len));
  }

  // ── GPIO / SPI initialization ────────────────────────────────────────────

  bool init_gpio() {
    uint64_t out_mask = 0;
    out_mask |= (1ULL << board_.display_pins.mosi);
    out_mask |= (1ULL << board_.display_pins.sclk);
    out_mask |= (1ULL << board_.display_pins.cs);
    out_mask |= (1ULL << board_.display_pins.dc);
    out_mask |= (1ULL << board_.display_pins.rst);
    if (board_.display_pins.power_enable >= 0) {
      out_mask |= (1ULL << board_.display_pins.power_enable);
    }

    gpio_config_t out_cfg{};
    out_cfg.pin_bit_mask = out_mask;
    out_cfg.mode = GPIO_MODE_OUTPUT;
    out_cfg.pull_up_en = GPIO_PULLUP_DISABLE;
    out_cfg.pull_down_en = GPIO_PULLDOWN_DISABLE;
    out_cfg.intr_type = GPIO_INTR_DISABLE;
    ESP_ERROR_CHECK(gpio_config(&out_cfg));

    gpio_config_t busy_cfg{};
    busy_cfg.pin_bit_mask = (1ULL << board_.display_pins.busy);
    busy_cfg.mode = GPIO_MODE_INPUT;
    busy_cfg.pull_up_en = GPIO_PULLUP_DISABLE;
    busy_cfg.pull_down_en = GPIO_PULLDOWN_DISABLE;
    busy_cfg.intr_type = GPIO_INTR_DISABLE;
    ESP_ERROR_CHECK(gpio_config(&busy_cfg));

    set_power_enabled(true);
    ESP_ERROR_CHECK(gpio_set_level(to_gpio_num(board_.display_pins.mosi), 0));
    ESP_ERROR_CHECK(gpio_set_level(to_gpio_num(board_.display_pins.sclk), 0));
    ESP_ERROR_CHECK(gpio_set_level(to_gpio_num(board_.display_pins.cs), 1));
    ESP_ERROR_CHECK(gpio_set_level(to_gpio_num(board_.display_pins.dc), 0));
    ESP_ERROR_CHECK(gpio_set_level(to_gpio_num(board_.display_pins.rst), 1));
    return true;
  }

  void set_power_enabled(const bool enabled) {
    if (board_.display_pins.power_enable < 0 || power_enabled_ == enabled) {
      return;
    }
    ESP_ERROR_CHECK(
        gpio_set_level(to_gpio_num(board_.display_pins.power_enable), enabled ? 1 : 0));
    power_enabled_ = enabled;
    if (enabled) {
      vTaskDelay(pdMS_TO_TICKS(kPowerStabilizeMs));
    }
  }

  void reset_panel() {
    ESP_LOGI(kTag, "BUSY before RST = %d",
             gpio_get_level(to_gpio_num(board_.display_pins.busy)));
    ESP_ERROR_CHECK(gpio_set_level(to_gpio_num(board_.display_pins.rst), 1));
    vTaskDelay(pdMS_TO_TICKS(kResetHighMs));
    ESP_ERROR_CHECK(gpio_set_level(to_gpio_num(board_.display_pins.rst), 0));
    esp_rom_delay_us(kResetLowUs);
    ESP_ERROR_CHECK(gpio_set_level(to_gpio_num(board_.display_pins.rst), 1));
    vTaskDelay(pdMS_TO_TICKS(kResetHighMs));
    ESP_LOGI(kTag, "BUSY after  RST = %d",
             gpio_get_level(to_gpio_num(board_.display_pins.busy)));
  }

  bool init_spi() {
    spi_bus_config_t buscfg{};
    buscfg.mosi_io_num = board_.display_pins.mosi;
    buscfg.miso_io_num = -1;
    buscfg.sclk_io_num = board_.display_pins.sclk;
    buscfg.quadwp_io_num = -1;
    buscfg.quadhd_io_num = -1;
    buscfg.max_transfer_sz = static_cast<int>(kSpiChunkBytes);

    spi_device_interface_config_t devcfg{};
    devcfg.clock_speed_hz = kSpiClockHz;
    devcfg.mode = 0;
    devcfg.spics_io_num = -1;
    devcfg.queue_size = 1;

    const esp_err_t bus_err = spi_bus_initialize(SPI2_HOST, &buscfg, SPI_DMA_CH_AUTO);
    if (bus_err != ESP_OK && bus_err != ESP_ERR_INVALID_STATE) {
      ESP_LOGE(kTag, "spi_bus_initialize failed: %s", esp_err_to_name(bus_err));
      return false;
    }

    const esp_err_t dev_err = spi_bus_add_device(SPI2_HOST, &devcfg, &spi_handle_);
    if (dev_err != ESP_OK && dev_err != ESP_ERR_INVALID_STATE) {
      ESP_LOGE(kTag, "spi_bus_add_device failed: %s", esp_err_to_name(dev_err));
      return false;
    }

    ESP_LOGI(kTag, "Display transport: hardware SPI (%d Hz)", kSpiClockHz);
    spi_ready_ = true;
    return true;
  }

  // ── Panel register / power management ────────────────────────────────────

  bool wait_until_idle(const char* label, const int timeout_ms) {
    const int64_t start_ms = esp_timer_get_time() / 1000;
    int64_t last_log_ms = -1000;
    if (kBusyPollWithStatusCommand) {
      send_command(0x71);
    }
    int busy_level = gpio_get_level(to_gpio_num(board_.display_pins.busy));
    while (busy_level == 0) {
      const int64_t now_ms = esp_timer_get_time() / 1000;
      const int64_t elapsed = now_ms - start_ms;
      if (elapsed > timeout_ms) {
        ESP_LOGE(kTag, "[%s] TIMEOUT after %lld ms (BUSY=%d)",
                 label, static_cast<long long>(elapsed), busy_level);
        return false;
      }
      if ((elapsed - last_log_ms) >= 1000) {
        ESP_LOGI(kTag, "[%s] waiting... %lld ms BUSY=%d",
                 label, static_cast<long long>(elapsed), busy_level);
        last_log_ms = elapsed;
      }
      if (kBusyPollWithStatusCommand) {
        send_command(0x71);
      }
      vTaskDelay(pdMS_TO_TICKS(20));
      busy_level = gpio_get_level(to_gpio_num(board_.display_pins.busy));
    }
    vTaskDelay(pdMS_TO_TICKS(20));

    const int64_t done_ms = (esp_timer_get_time() / 1000) - start_ms;
    ESP_LOGI(kTag, "[%s] done after %lld ms BUSY=%d",
             label, static_cast<long long>(done_ms), busy_level);
    return true;
  }

  bool init_panel_registers() {
    if (kUseHostLutWaveformProfile) {
      return init_panel_registers_host_lut();
    }

    // Exp #14: Exact Python standard init() — no init_fast, no extras
    ESP_LOGI(kTag, "Init panel (Python standard init)...");

    // 0x06: Booster Soft Start (Python: 0x17, 0x17, 0x28, 0x17)
    send_command(0x06);
    send_data(0x17);
    send_data(0x17);
    send_data(0x28);
    send_data(0x17);

    // 0x01: Power Setting (Python: 0x07, 0x07, 0x28, 0x17)
    send_command(0x01);
    send_data(0x07);
    send_data(0x07);
    send_data(0x28);
    send_data(0x17);

    // 0x04: Power ON
    ESP_LOGI(kTag, "Power ON (0x04)...");
    send_command(0x04);
    vTaskDelay(pdMS_TO_TICKS(100));
    if (!wait_until_idle("0x04", kPowerOnTimeoutMs)) {
      return false;
    }

    // 0x00: Panel Setting — LUT from OTP, B/W mode
    send_command(0x00);
    send_data(0x1F);

    // 0x61: Resolution — 800x480
    send_command(0x61);
    send_data(0x03);
    send_data(0x20);
    send_data(0x01);
    send_data(0xE0);

    // 0x15: Dual SPI — disabled
    send_command(0x15);
    send_data(0x00);

    // 0x50: VCOM and Data Interval
    send_command(0x50);
    send_data(0x10);
    send_data(0x07);

    // 0x60: TCON
    send_command(0x60);
    send_data(0x22);

    // NO 0x82 (VCOM override) — use OTP
    // NO 0x30 (PLL override) — use OTP
    // NO 0xE0/0xE5 — standard waveform, not fast

    panel_awake_ = true;
    return true;
  }

  bool init_panel_registers_host_lut() {
    // Based on Waveshare Arduino epd7in5_V2 external-LUT profile.
    ESP_LOGI(kTag, "Init panel (host LUT / external waveform profile)...");

    send_command(0x01);  // POWER SETTING
    send_data(0x17);
    send_data(0x17);  // VGH/VGL
    send_data(0x3F);  // VDH
    send_data(0x11);  // VDL/related

    send_command(0x82);  // VCOM DC
    send_data(kHostLutVcomDc);

    if (kUseHostLutOptRegister) {
      send_command(0x2A);  // LUT Option
      send_data(kHostLutOptXon);
      send_data(kHostLutOptValue);
    }

    send_command(0x06);  // Booster Soft Start
    send_data(0x27);
    send_data(0x27);
    send_data(0x2F);
    send_data(0x17);

    send_command(0x30);  // OSC
    send_data(0x06);

    send_command(0x04);  // POWER ON
    vTaskDelay(pdMS_TO_TICKS(100));
    if (!wait_until_idle("0x04_host_lut", kPowerOnTimeoutMs)) {
      return false;
    }

    send_command(0x00);  // PANEL SETTING: external LUT
    send_data(0x3F);

    send_command(0x61);  // Resolution 800x480
    send_data(0x03);
    send_data(0x20);
    send_data(0x01);
    send_data(0xE0);

    send_command(0x15);  // Dual SPI disabled
    send_data(0x00);

    send_command(0x50);  // VCOM and Data Interval
    send_data(kHostLutDataIntervalFirstByte);
    send_data(kHostLutDataIntervalSecondByte);

    if (kUseHostLutEvsRegister) {
      send_command(0x52);
      send_data(kHostLutEvsRegisterValue);
    }

    send_command(0x60);  // TCON
    send_data(0x22);

    send_command(0x65);  // Resolution setting extension
    send_data(0x00);
    send_data(0x00);
    send_data(0x00);
    send_data(0x00);

    load_host_lut();

    panel_awake_ = true;
    return true;
  }

  void load_host_lut() {
    send_command(0x20);  // LUT VCOM
    send_data_buffer(kHostLutVcom.data(), kHostLutVcom.size());
    send_command(0x21);  // LUT WW
    send_data_buffer(kHostLutWw.data(), kHostLutWw.size());
    send_command(0x22);  // LUT BW
    send_data_buffer(kHostLutBw.data(), kHostLutBw.size());
    send_command(0x23);  // LUT WB
    send_data_buffer(kHostLutWb.data(), kHostLutWb.size());
    send_command(0x24);  // LUT BB
    send_data_buffer(kHostLutBb.data(), kHostLutBb.size());
  }

  bool wake_panel_if_needed() {
    if (panel_awake_) {
      return true;
    }
    set_power_enabled(true);
    reset_panel();
    return init_panel_registers();
  }

  bool power_off_panel() {
    if (!panel_awake_) {
      return true;
    }
    send_command(0x50);
    send_data(0xF7);
    send_command(0x02);  // POWER_OFF
    if (!wait_until_idle("0x02", kPowerOffTimeoutMs)) {
      return false;
    }
    vTaskDelay(pdMS_TO_TICKS(300));
    set_power_enabled(false);
    panel_awake_ = false;
    return true;
  }

  bool clear_panel_once() {
    ESP_LOGI(kTag, "Clear panel (Waveshare reference sequence)...");
    if (!wake_panel_if_needed()) {
      return false;
    }
    // Match Waveshare Python epd7in5_V2.Clear() exactly:
    //   0x10 <- 0xFF
    //   0x13 <- 0x00
    send_command(0x10);
    send_fill_buffer(0xFF, kPanelBufferSize);
    send_command(0x13);
    send_fill_buffer(0x00, kPanelBufferSize);
    send_command(0x12);
    vTaskDelay(pdMS_TO_TICKS(100));
    const bool ok = wait_until_idle("clear_0x12", kRefreshTimeoutMs);
    if (!ok) {
      return false;
    }
    // Do not assume previous frame state after panel clear.
    previous_frame_valid_ = false;
    if (kPowerOffAfterRefresh) {
      return power_off_panel();
    }
    return true;
  }

  // ── Bitmap transfer ──────────────────────────────────────────────────────

  void display_bitmap(const std::vector<uint8_t>& image) {
    if (image.size() != static_cast<size_t>(kPanelBufferSize)) {
      ESP_LOGE(kTag, "Invalid image size: %u, expected %d",
               static_cast<unsigned>(image.size()), kPanelBufferSize);
      return;
    }

    if (!wake_panel_if_needed()) {
      return;
    }

    if (kUseHostLutWaveformProfile) {
      if (kUseHostLutWhitePrecleanPass) {
        // Pre-clean to white to remove residual tint in white background regions.
        if (kUseHostLutDualPlaneRefresh) {
          send_command(0x10);
          send_fill_buffer(panel_black_fill_byte(), kPanelBufferSize);
        }
        send_command(0x13);
        send_fill_buffer(panel_white_fill_byte(), kPanelBufferSize);
        ESP_LOGI(kTag, "Host LUT preclean pass (to white)...");
        send_command(0x12);
        vTaskDelay(pdMS_TO_TICKS(kPostRefreshDelayMs));
        if (!wait_until_idle("0x12_host_lut_preclean", kRefreshTimeoutMs)) {
          return;
        }
      }

      const int passes = std::max(1, kHostLutFullRefreshPasses);
      for (int pass = 0; pass < passes; ++pass) {
        // Host-LUT dual-plane payload order.
        // Legacy order (Waveshare old.c): 0x10=image, 0x13=~image.
        // Non-legacy order:              0x10=~image, 0x13=image.
        const bool old_plane_invert = !kUseHostLutLegacyPlaneOrder;
        const bool new_plane_invert = kUseHostLutLegacyPlaneOrder;
        if (kUseHostLutDualPlaneRefresh) {
          send_command(0x10);
          send_data_buffer_framebuffer(image.data(), kPanelBufferSize, old_plane_invert);
          ESP_LOGI(
              kTag,
              "Host LUT frame mode: old=%s, new=%s",
              old_plane_invert ? "~image" : "image",
              new_plane_invert ? "~image" : "image");
        }
        send_command(0x13);
        send_data_buffer_framebuffer(image.data(), kPanelBufferSize, new_plane_invert);

        ESP_LOGI(
            kTag,
            "Refresh (0x12, host LUT, dual_plane=%d, pass=%d/%d)...",
            static_cast<int>(kUseHostLutDualPlaneRefresh),
            pass + 1,
            passes);
        send_command(0x12);
        vTaskDelay(pdMS_TO_TICKS(kPostRefreshDelayMs));
        if (!wait_until_idle("0x12_host_lut", kRefreshTimeoutMs)) {
          return;
        }
      }

      if (kUseHostLutWhiteBoostPass) {
        // White-boost pass: force old frame to black so white pixels get stronger (black->white)
        // driving, while black pixels remain stable (black->black).
        const bool new_plane_invert = kUseHostLutLegacyPlaneOrder;
        if (kUseHostLutDualPlaneRefresh) {
          send_command(0x10);
          send_fill_buffer(panel_black_fill_byte(), kPanelBufferSize);
        }
        send_command(0x13);
        send_data_buffer_framebuffer(image.data(), kPanelBufferSize, new_plane_invert);
        ESP_LOGI(kTag, "Host LUT white-boost pass...");
        send_command(0x12);
        vTaskDelay(pdMS_TO_TICKS(kPostRefreshDelayMs));
        if (!wait_until_idle("0x12_host_lut_white_boost", kRefreshTimeoutMs)) {
          return;
        }
      }

      previous_frame_ = image;
      previous_frame_valid_ = true;
      if (kPowerOffAfterRefresh) {
        (void)power_off_panel();
      }
      return;
    }

    send_command(0x10);
    if (kUseInvertedOldBufferForFullRefresh) {
      send_data_buffer_framebuffer(image.data(), kPanelBufferSize, true);
      ESP_LOGI(kTag, "Frame mode: old=~image, new=image");
    } else if (previous_frame_valid_ &&
               previous_frame_.size() == static_cast<size_t>(kPanelBufferSize)) {
      send_data_buffer_framebuffer(previous_frame_.data(), kPanelBufferSize, false);
      ESP_LOGI(kTag, "Frame mode: old=previous, new=image");
    } else {
      send_fill_buffer(panel_black_fill_byte(), kPanelBufferSize);
      ESP_LOGI(kTag, "Frame mode: old=black baseline, new=image");
    }
    send_command(0x13);
    send_data_buffer_framebuffer(image.data(), kPanelBufferSize, false);

    ESP_LOGI(kTag, "Refresh (0x12)...");
    send_command(0x12);
    vTaskDelay(pdMS_TO_TICKS(kPostRefreshDelayMs));
    if (!wait_until_idle("0x12", kRefreshTimeoutMs)) {
      return;
    }

    previous_frame_ = image;
    previous_frame_valid_ = true;
    if (kPowerOffAfterRefresh) {
      (void)power_off_panel();
    }
  }

  // Switch panel into partial refresh mode (Python: init_part)
  // Must be called before display_bitmap_partial; restores full mode after.
  bool enter_partial_mode() {
    ESP_LOGI(kTag, "Entering partial refresh mode (reset + init_part)...");
    reset_panel();

    // 0x00: Panel Setting
    send_command(0x00);
    send_data(0x1F);

    // 0x04: Power ON
    send_command(0x04);
    vTaskDelay(pdMS_TO_TICKS(100));
    if (!wait_until_idle("part_0x04", kPowerOnTimeoutMs)) {
      return false;
    }

    // 0xE0/0xE5: Enable partial refresh timing (critical!)
    send_command(0xE0);
    send_data(0x02);
    send_command(0xE5);
    send_data(0x6E);

    in_partial_mode_ = true;
    return true;
  }

  // Restore panel to full refresh mode after partial updates
  bool restore_full_mode() {
    ESP_LOGI(kTag, "Restoring full refresh mode...");
    reset_panel();
    in_partial_mode_ = false;
    return init_panel_registers();
  }

  void display_bitmap_partial(
      const std::vector<uint8_t>& image,
      int x0, int y0, int x1, int y1) {
    if (image.size() != static_cast<size_t>(kPanelBufferSize)) {
      return;
    }

    // Switch to partial mode if not already there
    if (!in_partial_mode_) {
      if (!enter_partial_mode()) {
        ESP_LOGE(kTag, "Failed to enter partial mode, falling back to full");
        display_bitmap(image);
        return;
      }
    }

    // Align x to 8-pixel boundary
    x0 = (x0 / 8) * 8;
    x1 = ((x1 + 7) / 8) * 8;
    if (x0 < 0) x0 = 0;
    if (y0 < 0) y0 = 0;
    if (x1 > kPanelWidth) x1 = kPanelWidth;
    if (y1 > kPanelHeight) y1 = kPanelHeight;

    const int w = x1 - x0;
    const int h = y1 - y0;
    if (w <= 0 || h <= 0) {
      return;
    }
    const int w_bytes = w / 8;

    ESP_LOGI(kTag, "Partial window: (%d,%d)-(%d,%d) %dx%d", x0, y0, x1, y1, w, h);

    // VCOM setting for partial mode
    send_command(0x50);
    send_data(0xA9);
    send_data(0x07);

    // Enter partial window mode
    send_command(0x91);

    // Set partial window coordinates
    send_command(0x90);
    send_data(static_cast<uint8_t>(x0 >> 8));
    send_data(static_cast<uint8_t>(x0 & 0xFF));
    send_data(static_cast<uint8_t>((x1 - 1) >> 8));
    send_data(static_cast<uint8_t>((x1 - 1) & 0xFF));
    send_data(static_cast<uint8_t>(y0 >> 8));
    send_data(static_cast<uint8_t>(y0 & 0xFF));
    send_data(static_cast<uint8_t>((y1 - 1) >> 8));
    send_data(static_cast<uint8_t>((y1 - 1) & 0xFF));
    send_data(0x01);

    const auto send_partial_plane_13 = [&](const std::vector<uint8_t>& frame, const char* label) {
      // Python source-of-truth (epd7in5_V2.py::display_Partial):
      // after 0x13 it streams a full-frame-length payload, where only the
      // leading Width*Height bytes carry window data and the remainder stays
      // white (0xFF in framebuffer convention).
      const size_t partial_payload_len = static_cast<size_t>(w_bytes * h);
      const size_t full_payload_len = static_cast<size_t>(kPanelBufferSize);
      trace_stream(label, full_payload_len);
      begin_data_stream();
      std::array<uint8_t, kFillChunkBytes> panel_chunk{};
      for (int row = y0; row < y1; ++row) {
        const int src_offset = row * kPanelWidthBytes + (x0 / 8);
        for (int b = 0; b < w_bytes; ++b) {
          // Python epd7in5_V2.display_Partial sends:
          //   0x13 <- image1 where image1 = ~Image and Image is getbuffer(crop).
          // Our runtime frame uses pre-getbuffer polarity, so we invert once here
          // before transport mapping to match Python's 0x13 payload polarity.
          const uint8_t payload = static_cast<uint8_t>(~frame[src_offset + b]);
          panel_chunk[b] = map_framebuffer_byte_to_panel(payload);
        }
        spi_write_bytes(panel_chunk.data(), w_bytes);
      }
      if (partial_payload_len < full_payload_len) {
        const size_t tail_len = full_payload_len - partial_payload_len;
        panel_chunk.fill(panel_white_fill_byte());
        size_t sent = 0;
        while (sent < tail_len) {
          const size_t chunk = std::min(panel_chunk.size(), tail_len - sent);
          spi_write_bytes(panel_chunk.data(), chunk);
          sent += chunk;
        }
      }
      end_data_stream();
    };

    // Keep Python V2 partial path: window + single 0x13 payload + refresh.
    send_command(0x13);
    send_partial_plane_13(image, "PART_13");

    // Refresh
    send_command(0x12);
    vTaskDelay(pdMS_TO_TICKS(kPostRefreshDelayMs));
    (void)wait_until_idle("partial_0x12", kRefreshTimeoutMs);
  }

  // ── SPI transport ────────────────────────────────────────────────────────

  void send_command(const uint8_t command) {
    if (!spi_ready_) {
      return;
    }
    last_command_ = command;
    trace_command(command);
    ESP_ERROR_CHECK(gpio_set_level(to_gpio_num(board_.display_pins.dc), 0));
    ESP_ERROR_CHECK(gpio_set_level(to_gpio_num(board_.display_pins.cs), 0));
    spi_write_bytes(&command, 1);
    ESP_ERROR_CHECK(gpio_set_level(to_gpio_num(board_.display_pins.cs), 1));
  }

  void send_data(const uint8_t data) {
    if (!spi_ready_) {
      return;
    }
    trace_data(data);
    ESP_ERROR_CHECK(gpio_set_level(to_gpio_num(board_.display_pins.dc), 1));
    ESP_ERROR_CHECK(gpio_set_level(to_gpio_num(board_.display_pins.cs), 0));
    spi_write_bytes(&data, 1);
    ESP_ERROR_CHECK(gpio_set_level(to_gpio_num(board_.display_pins.cs), 1));
  }

  void send_data_buffer(const uint8_t* data, const size_t len) {
    if (!spi_ready_ || data == nullptr || len == 0) {
      return;
    }
    trace_stream("BUF", len);
    begin_data_stream();
    spi_write_bytes(data, len);
    end_data_stream();
  }

  void send_data_buffer_framebuffer(
      const uint8_t* data, const size_t len, const bool invert_framebuffer_bits) {
    if (!spi_ready_ || data == nullptr || len == 0) {
      return;
    }
    trace_stream(invert_framebuffer_bits ? "FB_INV" : "FB", len);
    std::array<uint8_t, kFillChunkBytes> converted_chunk{};
    begin_data_stream();
    size_t sent = 0;
    while (sent < len) {
      const size_t chunk = std::min(converted_chunk.size(), len - sent);
      for (size_t i = 0; i < chunk; ++i) {
        uint8_t framebuffer_value = data[sent + i];
        if (invert_framebuffer_bits) {
          framebuffer_value = static_cast<uint8_t>(~framebuffer_value);
        }
        const uint8_t panel_value = map_framebuffer_byte_to_panel(framebuffer_value);
        converted_chunk[i] = panel_value;
      }
      spi_write_bytes(converted_chunk.data(), chunk);
      sent += chunk;
    }
    end_data_stream();
  }

  void send_fill_buffer(const uint8_t value, const size_t len) {
    if (!spi_ready_ || len == 0) {
      return;
    }
    trace_stream(value == panel_white_fill_byte() ? "FILL_WHITE" : "FILL", len);
    std::array<uint8_t, kFillChunkBytes> fill_chunk{};
    fill_chunk.fill(value);
    begin_data_stream();
    size_t sent = 0;
    while (sent < len) {
      const size_t chunk = std::min(fill_chunk.size(), len - sent);
      spi_write_bytes(fill_chunk.data(), chunk);
      sent += chunk;
    }
    end_data_stream();
  }

  void begin_data_stream() {
    ESP_ERROR_CHECK(gpio_set_level(to_gpio_num(board_.display_pins.dc), 1));
    ESP_ERROR_CHECK(gpio_set_level(to_gpio_num(board_.display_pins.cs), 0));
  }

  void end_data_stream() {
    ESP_ERROR_CHECK(gpio_set_level(to_gpio_num(board_.display_pins.cs), 1));
  }

  void spi_write_bytes(const uint8_t* data, const size_t len) {
    if (spi_handle_ == nullptr || data == nullptr || len == 0) {
      return;
    }

    size_t sent = 0;
    while (sent < len) {
      const size_t chunk = std::min(kSpiChunkBytes, len - sent);
      spi_transaction_t trans{};
      trans.length = static_cast<uint32_t>(chunk * 8U);
      trans.tx_buffer = data + sent;
      ESP_ERROR_CHECK(spi_device_transmit(spi_handle_, &trans));
      sent += chunk;
    }
  }

  // ── Member state ─────────────────────────────────────────────────────────

  BoardConfig board_{};
  bool hardware_ready_{false};
  bool power_enabled_{false};
  bool panel_awake_{false};
  bool spi_ready_{false};
  bool previous_frame_valid_{false};
  bool in_partial_mode_{false};
  int64_t trace_epoch_ms_{0};
  uint32_t trace_seq_{0};
  uint8_t last_command_{0};
  std::vector<uint8_t> previous_frame_{};
  spi_device_handle_t spi_handle_{nullptr};
};

}  // namespace

std::unique_ptr<Display> make_default_display() {
  return std::make_unique<EpaperDisplay>();
}

}  // namespace fridge_ink::platform
