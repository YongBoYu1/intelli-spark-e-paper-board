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
constexpr int kMinRefreshGapMs = 120;
constexpr int kResetHighMs = 200;
constexpr int kResetLowUs = 2000;
constexpr int kSpiClockHz = 4 * 1000 * 1000;  // Match Python RPi driver (was 2MHz)
constexpr size_t kSpiChunkBytes = 2048;
constexpr size_t kFillChunkBytes = 256;
constexpr bool kPowerOffAfterRefresh = false;
constexpr bool kUseInvertedFirstFrame = true;
constexpr int kUiDilateRadius = 0;

gpio_num_t to_gpio_num(const int pin) {
  return static_cast<gpio_num_t>(pin);
}

DirtyRect clip_dirty_rect(const DirtyRect& rect) {
  DirtyRect clipped = rect;
  clipped.x0 = std::max(0, std::min(kPanelWidth, clipped.x0));
  clipped.y0 = std::max(0, std::min(kPanelHeight, clipped.y0));
  clipped.x1 = std::max(0, std::min(kPanelWidth, clipped.x1));
  clipped.y1 = std::max(0, std::min(kPanelHeight, clipped.y1));
  return clipped;
}

bool is_valid_dirty_rect(const DirtyRect& rect) {
  return rect.x1 > rect.x0 && rect.y1 > rect.y0;
}

void wait_for_refresh_gap(int64_t& last_refresh_end_ms) {
  if (last_refresh_end_ms <= 0) {
    return;
  }
  const int64_t now_ms = esp_timer_get_time() / 1000;
  const int64_t elapsed = now_ms - last_refresh_end_ms;
  if (elapsed >= kMinRefreshGapMs) {
    return;
  }
  vTaskDelay(pdMS_TO_TICKS(static_cast<int>(kMinRefreshGapMs - elapsed)));
}

bool rect_contains(
    const DirtyRect& outer,
    const DirtyRect& inner,
    const int slack = 0) {
  return inner.x0 >= (outer.x0 - slack) &&
         inner.y0 >= (outer.y0 - slack) &&
         inner.x1 <= (outer.x1 + slack) &&
         inner.y1 <= (outer.y1 + slack);
}

DirtyRect merge_dirty_rects(const DirtyRect& a, const DirtyRect& b) {
  return {
      std::min(a.x0, b.x0),
      std::min(a.y0, b.y0),
      std::max(a.x1, b.x1),
      std::max(a.y1, b.y1),
  };
}

DirtyRect align_rect_for_partial(
    const DirtyRect& rect,
    const int width,
    const int height,
    const int pad = 2) {
  DirtyRect expanded{
      rect.x0 - pad,
      rect.y0 - pad,
      rect.x1 + pad,
      rect.y1 + pad,
  };
  expanded = clip_dirty_rect(expanded);
  expanded.x0 = (expanded.x0 / 8) * 8;
  expanded.x1 = ((expanded.x1 + 7) / 8) * 8;
  expanded.x0 = std::max(0, std::min(width, expanded.x0));
  expanded.y0 = std::max(0, std::min(height, expanded.y0));
  expanded.x1 = std::max(0, std::min(width, expanded.x1));
  expanded.y1 = std::max(0, std::min(height, expanded.y1));
  return expanded;
}

std::vector<DirtyRect> prepare_partial_rects(
    const std::vector<DirtyRect>& rects,
    const int width,
    const int height,
    const int pad = 2,
    const int max_rects = 6,
    const bool merge_overflow = true) {
  std::vector<DirtyRect> aligned;
  aligned.reserve(rects.size());

  for (const DirtyRect& rect : rects) {
    const DirtyRect clipped = align_rect_for_partial(rect, width, height, pad);
    if (!is_valid_dirty_rect(clipped)) {
      continue;
    }
    if (std::any_of(aligned.begin(), aligned.end(), [&](const DirtyRect& existing) {
          return rect_contains(existing, clipped, 0);
        })) {
      continue;
    }
    aligned.erase(
        std::remove_if(
            aligned.begin(),
            aligned.end(),
            [&](const DirtyRect& existing) {
              return rect_contains(clipped, existing, 0);
            }),
        aligned.end());
    aligned.push_back(clipped);
  }

  if (aligned.empty()) {
    return {};
  }

  std::sort(aligned.begin(), aligned.end(), [](const DirtyRect& a, const DirtyRect& b) {
    const int area_a = (a.x1 - a.x0) * (a.y1 - a.y0);
    const int area_b = (b.x1 - b.x0) * (b.y1 - b.y0);
    if (a.y0 != b.y0) return a.y0 < b.y0;
    if (a.x0 != b.x0) return a.x0 < b.x0;
    return area_a < area_b;
  });

  const int max_n = std::max(1, max_rects);
  if (static_cast<int>(aligned.size()) <= max_n) {
    return aligned;
  }
  if (!merge_overflow) {
    aligned.resize(static_cast<std::size_t>(max_n));
    return aligned;
  }

  DirtyRect merged = aligned.front();
  for (std::size_t i = 1; i < aligned.size(); ++i) {
    merged = merge_dirty_rects(merged, aligned[i]);
  }
  return {merged};
}

// ── Image utility helpers (internal) ─────────────────────────────────────────

void set_black_pixel_raw(std::vector<uint8_t>& image, const int x, const int y) {
  if (x < 0 || x >= kPanelWidth || y < 0 || y >= kPanelHeight) {
    return;
  }
  const int offset = (y * kPanelWidthBytes) + (x / 8);
  const uint8_t bit = static_cast<uint8_t>(0x80U >> (x % 8));
  image[offset] = static_cast<uint8_t>(image[offset] | bit);
}

bool is_black_pixel(const std::vector<uint8_t>& image, const int x, const int y) {
  if (x < 0 || x >= kPanelWidth || y < 0 || y >= kPanelHeight) {
    return false;
  }
  const int offset = (y * kPanelWidthBytes) + (x / 8);
  const uint8_t bit = static_cast<uint8_t>(0x80U >> (x % 8));
  return (image[offset] & bit) != 0;
}

std::size_t count_black_bits(const std::vector<uint8_t>& image) {
  // Convention: 0=black, 1=white. Count ZERO bits.
  std::size_t count = 0;
  for (const uint8_t value : image) {
    count += static_cast<std::size_t>(__builtin_popcount(static_cast<unsigned int>(
        static_cast<uint8_t>(~value))));
  }
  return count;
}

std::vector<uint8_t> make_inverted_image(const std::vector<uint8_t>& image) {
  std::vector<uint8_t> out = image;
  for (uint8_t& value : out) {
    value = static_cast<uint8_t>(~value);
  }
  return out;
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

  void display_image(
      const std::vector<uint8_t>& image_in,
      const std::vector<DirtyRect>& dirty_hints) override {
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

    // Decide: partial or full refresh
    if (!first_present_done_ || !previous_frame_valid_) {
      if (in_partial_mode_) { restore_full_mode(); }
      // Exp #16: Python full first-frame strategy:
      // 1. Clear() → DTM1=0xFF, DTM2=0x00 → panel driven to BLACK (0x00 state)
      // 2. display() → DTM1=previous(0x00)=matches panel, DTM2=image
      // Key insight: LUT phase D starts from all-black (phase C result),
      // and DTM1=0x00 matches that state → phase D settles correctly.
      // Exp #18a: CLEAN LUT TEST — clear to WHITE + DTM1=0xFF (true match)
      // Goal: isolate whether OTP LUT waveform itself works when DTM1=actual state.
      // 1. Clear to WHITE: DTM1=0x00, DTM2=0xFF → panel driven to 0xFF (all white)
      // 2. Display: DTM1=0xFF (matches panel), DTM2=image
      //    - White pixels: (1,1) no-op → already white, stay white ✓
      //    - Black pixels: (1,0) transition → full driving to black ✓
      // If this fails → LUT waveform itself is broken, not just DTM1 mismatch.
      ESP_LOGI(kTag, "Exp #18a: clear-to-WHITE + DTM1=0xFF (true state match)");
      if (!wake_panel_if_needed()) { return; }
      // Step 1: Clear to white
      send_command(0x10);
      send_fill_buffer(0x00, kPanelBufferSize);   // DTM1 = 0x00
      send_command(0x13);
      send_fill_buffer(0xFF, kPanelBufferSize);   // DTM2 = 0xFF (white target)
      send_command(0x12);
      vTaskDelay(pdMS_TO_TICKS(100));
      (void)wait_until_idle("clear_white_0x12", kRefreshTimeoutMs);
      ESP_LOGI(kTag, "Panel cleared to WHITE. Now displaying with DTM1=0xFF...");
      // Step 2: Set previous_frame to match actual panel state (all white = 0xFF)
      previous_frame_.assign(kPanelBufferSize, 0xFF);
      previous_frame_valid_ = true;
      // Step 3: display_bitmap will use DTM1=previous(0xFF) = matches panel
      display_bitmap(image);
    } else {
      // Compute dirty region bounding box
      int dirty_y0 = kPanelHeight;
      int dirty_y1 = 0;
      int dirty_x0_byte = kPanelWidthBytes;
      int dirty_x1_byte = 0;
      for (int y = 0; y < kPanelHeight; ++y) {
        for (int xb = 0; xb < kPanelWidthBytes; ++xb) {
          const int idx = y * kPanelWidthBytes + xb;
          if (image[idx] != previous_frame_[idx]) {
            if (y < dirty_y0) dirty_y0 = y;
            if (y > dirty_y1) dirty_y1 = y;
            if (xb < dirty_x0_byte) dirty_x0_byte = xb;
            if (xb > dirty_x1_byte) dirty_x1_byte = xb;
          }
        }
      }

      if (dirty_y0 > dirty_y1) {
        ESP_LOGI(kTag, "No pixel change, skipping refresh");
      } else if (!dirty_hints.empty()) {
        std::vector<DirtyRect> clipped_hints;
        clipped_hints.reserve(dirty_hints.size());
        for (const DirtyRect& rect : dirty_hints) {
          const DirtyRect clipped = clip_dirty_rect(rect);
          if (!is_valid_dirty_rect(clipped)) {
            continue;
          }
          clipped_hints.push_back(clipped);
        }

        const DirtyRect diff_rect{
            dirty_x0_byte * 8,
            dirty_y0,
            (dirty_x1_byte + 1) * 8,
            dirty_y1 + 1,
        };
        if (is_valid_dirty_rect(diff_rect)) {
          if (clipped_hints.empty()) {
            clipped_hints.push_back(diff_rect);
          } else {
            DirtyRect merged_hints = clipped_hints.front();
            for (std::size_t i = 1; i < clipped_hints.size(); ++i) {
              merged_hints = merge_dirty_rects(merged_hints, clipped_hints[i]);
            }
            if (!rect_contains(merged_hints, diff_rect, 4)) {
              clipped_hints.push_back(diff_rect);
            }
          }
        }

        if (clipped_hints.empty()) {
          ESP_LOGI(kTag, "Dirty hints empty after clipping; skipping refresh");
        } else {
          const std::vector<DirtyRect> prepared_rects =
              prepare_partial_rects(clipped_hints, kPanelWidth, kPanelHeight, 2, 6, true);
          if (prepared_rects.empty()) {
            ESP_LOGI(kTag, "Dirty hints empty after preparation; skipping refresh");
            previous_frame_ = image;
            previous_frame_valid_ = true;
            return;
          }

          std::vector<DirtyRect> apply_rects = prepared_rects;
          if (prepared_rects.size() > 1) {
            DirtyRect merged = prepared_rects.front();
            for (std::size_t i = 1; i < prepared_rects.size(); ++i) {
              merged = merge_dirty_rects(merged, prepared_rects[i]);
            }
            apply_rects = {align_rect_for_partial(merged, kPanelWidth, kPanelHeight, 2)};
          }

          int hinted_pixels = 0;
          int largest_pixels = 0;
          for (const DirtyRect& rect : apply_rects) {
            const int rect_pixels = (rect.x1 - rect.x0) * (rect.y1 - rect.y0);
            hinted_pixels += rect_pixels;
            largest_pixels = std::max(largest_pixels, rect_pixels);
          }
          const int total_pixels = kPanelWidth * kPanelHeight;
          const float dirty_ratio =
              static_cast<float>(hinted_pixels) / static_cast<float>(total_pixels);
          const float largest_ratio =
              static_cast<float>(largest_pixels) / static_cast<float>(total_pixels);

          ESP_LOGI(
              kTag,
              "Dirty hints: raw=%u prepared=%u ratio=%.3f max_ratio=%.3f",
              static_cast<unsigned>(clipped_hints.size()),
              static_cast<unsigned>(apply_rects.size()),
              dirty_ratio,
              largest_ratio);

          constexpr float kHintedFullAreaLimit = 0.75f;
          constexpr std::size_t kMaxHintedRects = 6;
          partial_since_full_++;
          if (largest_ratio > kHintedFullAreaLimit ||
              apply_rects.size() > kMaxHintedRects ||
              partial_since_full_ >= 30) {
            ESP_LOGI(kTag, "Full refresh from hinted update (ratio=%.3f, rects=%u)",
                     dirty_ratio,
                     static_cast<unsigned>(apply_rects.size()));
            if (in_partial_mode_) {
              restore_full_mode();
            }
            display_bitmap(image);
            partial_since_full_ = 0;
          } else {
            for (const DirtyRect& rect : apply_rects) {
              ESP_LOGI(
                  kTag,
                  "Partial refresh from hinted rect (%d,%d)-(%d,%d)",
                  rect.x0,
                  rect.y0,
                  rect.x1,
                  rect.y1);
              display_bitmap_partial(image, rect.x0, rect.y0, rect.x1, rect.y1);
            }
          }
        }
      } else {
        const int dirty_x0 = dirty_x0_byte * 8;
        const int dirty_x1 = (dirty_x1_byte + 1) * 8;
        const int dirty_w = dirty_x1 - dirty_x0;
        const int dirty_h = dirty_y1 - dirty_y0 + 1;
        const int dirty_pixels = dirty_w * dirty_h;
        const int total_pixels = kPanelWidth * kPanelHeight;
        const float dirty_ratio =
            static_cast<float>(dirty_pixels) / static_cast<float>(total_pixels);

        ESP_LOGI(kTag, "Dirty region: (%d,%d)-(%d,%d) ratio=%.3f",
                 dirty_x0, dirty_y0, dirty_x1, dirty_y1 + 1, dirty_ratio);

        // Force full refresh periodically to prevent ghosting buildup
        partial_since_full_++;
        constexpr int kMaxPartialBeforeFull = 30;
        constexpr float kPartialAreaLimit = 0.40f;

        if (dirty_ratio > kPartialAreaLimit ||
            partial_since_full_ >= kMaxPartialBeforeFull) {
          ESP_LOGI(kTag, "Full refresh (ratio=%.3f, partials_since=%d)",
                   dirty_ratio, partial_since_full_);
          if (in_partial_mode_) { restore_full_mode(); }
          display_bitmap(image);
          partial_since_full_ = 0;
        } else {
          ESP_LOGI(kTag, "Partial refresh (ratio=%.3f, partials_since=%d)",
                   dirty_ratio, partial_since_full_);
          display_bitmap_partial(image, dirty_x0, dirty_y0, dirty_x1, dirty_y1 + 1);
        }
      }
    }
    first_present_done_ = true;
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
      vTaskDelay(pdMS_TO_TICKS(100));
      busy_level = gpio_get_level(to_gpio_num(board_.display_pins.busy));
    }
    vTaskDelay(pdMS_TO_TICKS(20));

    const int64_t done_ms = (esp_timer_get_time() / 1000) - start_ms;
    ESP_LOGI(kTag, "[%s] done after %lld ms BUSY=%d",
             label, static_cast<long long>(done_ms), busy_level);
    return true;
  }

  bool init_panel_registers() {
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
    // Python Clear: DTM1=0xFF, DTM2=0x00 (creates transition to drive pixels)
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
    previous_frame_.assign(kPanelBufferSize, 0x00);
    previous_frame_valid_ = true;
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
    wait_for_refresh_gap(last_refresh_end_ms_);
    send_command(0x10);
    if (previous_frame_valid_ &&
        previous_frame_.size() == static_cast<size_t>(kPanelBufferSize)) {
      send_data_buffer(previous_frame_.data(), kPanelBufferSize);
      ESP_LOGI(kTag, "Frame mode: old=previous, new=image");
    } else {
      if (kUseInvertedFirstFrame) {
        const auto inverted = make_inverted_image(image);
        send_data_buffer(inverted.data(), kPanelBufferSize);
        ESP_LOGI(kTag, "Frame mode: old=~image (first frame), new=image");
      } else {
        send_fill_buffer(0x00, kPanelBufferSize);
        ESP_LOGI(kTag, "Frame mode: old=0x00 baseline, new=image");
      }
    }
    send_command(0x13);
    send_data_buffer(image.data(), kPanelBufferSize);

    ESP_LOGI(kTag, "Refresh (0x12)...");
    send_command(0x12);
    vTaskDelay(pdMS_TO_TICKS(kPostRefreshDelayMs));
    if (!wait_until_idle("0x12", kRefreshTimeoutMs)) {
      return;
    }

    previous_frame_ = image;
    previous_frame_valid_ = true;
    last_refresh_end_ms_ = esp_timer_get_time() / 1000;
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
    wait_for_refresh_gap(last_refresh_end_ms_);

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

    // DTM2 with inverted data for partial refresh
    send_command(0x13);
    begin_data_stream();
    std::array<uint8_t, kFillChunkBytes> inv_chunk{};
    for (int row = y0; row < y1; ++row) {
      const int src_offset = row * kPanelWidthBytes + (x0 / 8);
      for (int b = 0; b < w_bytes; ++b) {
        inv_chunk[b] = static_cast<uint8_t>(~image[src_offset + b]);
      }
      spi_write_bytes(inv_chunk.data(), w_bytes);
    }
    end_data_stream();

    // Refresh
    send_command(0x12);
    vTaskDelay(pdMS_TO_TICKS(kPostRefreshDelayMs));
    (void)wait_until_idle("partial_0x12", kRefreshTimeoutMs);

    // Update stored previous frame
    previous_frame_ = image;
    previous_frame_valid_ = true;
    last_refresh_end_ms_ = esp_timer_get_time() / 1000;
  }

  // ── SPI transport ────────────────────────────────────────────────────────

  void send_command(const uint8_t command) {
    if (!spi_ready_) {
      return;
    }
    ESP_ERROR_CHECK(gpio_set_level(to_gpio_num(board_.display_pins.dc), 0));
    ESP_ERROR_CHECK(gpio_set_level(to_gpio_num(board_.display_pins.cs), 0));
    spi_write_bytes(&command, 1);
    ESP_ERROR_CHECK(gpio_set_level(to_gpio_num(board_.display_pins.cs), 1));
  }

  void send_data(const uint8_t data) {
    if (!spi_ready_) {
      return;
    }
    ESP_ERROR_CHECK(gpio_set_level(to_gpio_num(board_.display_pins.dc), 1));
    ESP_ERROR_CHECK(gpio_set_level(to_gpio_num(board_.display_pins.cs), 0));
    spi_write_bytes(&data, 1);
    ESP_ERROR_CHECK(gpio_set_level(to_gpio_num(board_.display_pins.cs), 1));
  }

  void send_data_buffer(const uint8_t* data, const size_t len) {
    if (!spi_ready_ || data == nullptr || len == 0) {
      return;
    }
    begin_data_stream();
    spi_write_bytes(data, len);
    end_data_stream();
  }

  void send_fill_buffer(const uint8_t value, const size_t len) {
    if (!spi_ready_ || len == 0) {
      return;
    }
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
  bool first_present_done_{false};
  bool previous_frame_valid_{false};
  bool in_partial_mode_{false};
  int partial_since_full_{0};
  int64_t last_refresh_end_ms_{0};
  std::vector<uint8_t> previous_frame_{};
  spi_device_handle_t spi_handle_{nullptr};
};

}  // namespace

std::unique_ptr<Display> make_default_display() {
  return std::make_unique<EpaperDisplay>();
}

}  // namespace fridge_ink::platform
