#include "platform/board_config.hpp"
#include "platform/display.hpp"
#include "ui/panel_font_assets_generated.hpp"

#include "driver/gpio.h"
#include "driver/spi_master.h"
#include "esp_log.h"
#include "esp_rom_sys.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include <array>
#include <cctype>
#include <cstdio>
#include <cstdlib>
#include <cstdint>
#include <memory>
#include <sstream>
#include <string>
#include <vector>

namespace fridge_ink::platform {
namespace {

constexpr const char* kTag = "display";

constexpr int kPanelWidth = 800;
constexpr int kPanelHeight = 480;
constexpr int kPanelWidthBytes = kPanelWidth / 8;
constexpr int kPanelBufferSize = kPanelWidthBytes * kPanelHeight;

constexpr int kPowerOnTimeoutMs = 10000;
constexpr int kPowerOffTimeoutMs = 10000;
constexpr int kRefreshTimeoutMs = 25000;
constexpr int kPowerStabilizeMs = 50;
constexpr int kPostRefreshDelayMs = 100;
constexpr int kResetHighMs = 200;
constexpr int kResetLowUs = 2000;
constexpr int kSpiClockHz = 2 * 1000 * 1000;
constexpr size_t kSpiChunkBytes = 2048;
constexpr size_t kFillChunkBytes = 256;
constexpr bool kEnableGrayFixInit = false;
constexpr bool kPowerOffAfterRefresh = false;
constexpr bool kUsePanelDiagnosticImage = false;
constexpr bool kUseExactFullBlackTest = false;
constexpr bool kUseEmbeddedLandingReference = true;
constexpr bool kUseInvertedFirstFrame = true;
constexpr int kUiDilateRadius = 0;

constexpr int kMargin = 16;
constexpr int kTextInsetX = 24;
constexpr int kTitleScale = 4;
constexpr int kSubtitleScale = 3;
constexpr int kBodyScale = 2;
constexpr int kFooterScale = 2;

gpio_num_t to_gpio_num(const int pin) {
  return static_cast<gpio_num_t>(pin);
}

extern const uint8_t _binary_landing_en_raw_start[] asm("_binary_landing_en_raw_start");
extern const uint8_t _binary_landing_en_raw_end[] asm("_binary_landing_en_raw_end");

void set_black_pixel_raw(std::vector<uint8_t>& image, const int x, const int y) {
  if (x < 0 || x >= kPanelWidth || y < 0 || y >= kPanelHeight) {
    return;
  }
  const int offset = (y * kPanelWidthBytes) + (x / 8);
  const uint8_t bit = static_cast<uint8_t>(0x80U >> (x % 8));
  image[offset] = static_cast<uint8_t>(image[offset] | bit);
}

void clear_pixel_raw(std::vector<uint8_t>& image, const int x, const int y) {
  if (x < 0 || x >= kPanelWidth || y < 0 || y >= kPanelHeight) {
    return;
  }
  const int offset = (y * kPanelWidthBytes) + (x / 8);
  const uint8_t bit = static_cast<uint8_t>(0x80U >> (x % 8));
  image[offset] = static_cast<uint8_t>(image[offset] & static_cast<uint8_t>(~bit));
}

void fill_black_rect_raw(
    std::vector<uint8_t>& image,
    const int x0,
    const int y0,
    const int x1,
    const int y1) {
  for (int y = y0; y < y1; ++y) {
    for (int x = x0; x < x1; ++x) {
      set_black_pixel_raw(image, x, y);
    }
  }
}

void fill_white_rect_raw(
    std::vector<uint8_t>& image,
    const int x0,
    const int y0,
    const int x1,
    const int y1) {
  for (int y = y0; y < y1; ++y) {
    for (int x = x0; x < x1; ++x) {
      clear_pixel_raw(image, x, y);
    }
  }
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
  std::size_t count = 0;
  for (const uint8_t value : image) {
    count += static_cast<std::size_t>(__builtin_popcount(static_cast<unsigned int>(value)));
  }
  return count;
}

std::vector<uint8_t> load_embedded_landing_reference() {
  const auto* start = _binary_landing_en_raw_start;
  const auto* end = _binary_landing_en_raw_end;
  const auto size = static_cast<std::size_t>(end - start);
  if (size != static_cast<std::size_t>(kPanelBufferSize)) {
    ESP_LOGW(kTag, "Embedded landing asset size mismatch: %zu", size);
    return {};
  }
  return std::vector<uint8_t>(start, end);
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

std::vector<uint8_t> make_panel_diagnostic_image() {
  std::vector<uint8_t> image(kPanelBufferSize, 0x00);
  fill_black_rect_raw(image, 12, 12, 788, 22);
  fill_black_rect_raw(image, 12, 458, 788, 468);
  fill_black_rect_raw(image, 12, 12, 22, 468);
  fill_black_rect_raw(image, 778, 12, 788, 468);

  fill_black_rect_raw(image, 80, 70, 720, 125);
  fill_black_rect_raw(image, 80, 160, 720, 320);
  fill_black_rect_raw(image, 120, 350, 680, 390);
  return image;
}

std::array<uint8_t, 7> glyph_5x7(char ch) {
  const char c = static_cast<char>(std::toupper(static_cast<unsigned char>(ch)));
  switch (c) {
    case 'A':
      return {0x0E, 0x11, 0x11, 0x1F, 0x11, 0x11, 0x11};
    case 'B':
      return {0x1E, 0x11, 0x11, 0x1E, 0x11, 0x11, 0x1E};
    case 'C':
      return {0x0E, 0x11, 0x10, 0x10, 0x10, 0x11, 0x0E};
    case 'D':
      return {0x1E, 0x11, 0x11, 0x11, 0x11, 0x11, 0x1E};
    case 'E':
      return {0x1F, 0x10, 0x10, 0x1E, 0x10, 0x10, 0x1F};
    case 'F':
      return {0x1F, 0x10, 0x10, 0x1E, 0x10, 0x10, 0x10};
    case 'G':
      return {0x0E, 0x11, 0x10, 0x17, 0x11, 0x11, 0x0E};
    case 'H':
      return {0x11, 0x11, 0x11, 0x1F, 0x11, 0x11, 0x11};
    case 'I':
      return {0x1F, 0x04, 0x04, 0x04, 0x04, 0x04, 0x1F};
    case 'J':
      return {0x01, 0x01, 0x01, 0x01, 0x11, 0x11, 0x0E};
    case 'K':
      return {0x11, 0x12, 0x14, 0x18, 0x14, 0x12, 0x11};
    case 'L':
      return {0x10, 0x10, 0x10, 0x10, 0x10, 0x10, 0x1F};
    case 'M':
      return {0x11, 0x1B, 0x15, 0x15, 0x11, 0x11, 0x11};
    case 'N':
      return {0x11, 0x19, 0x15, 0x13, 0x11, 0x11, 0x11};
    case 'O':
      return {0x0E, 0x11, 0x11, 0x11, 0x11, 0x11, 0x0E};
    case 'P':
      return {0x1E, 0x11, 0x11, 0x1E, 0x10, 0x10, 0x10};
    case 'Q':
      return {0x0E, 0x11, 0x11, 0x11, 0x15, 0x12, 0x0D};
    case 'R':
      return {0x1E, 0x11, 0x11, 0x1E, 0x14, 0x12, 0x11};
    case 'S':
      return {0x0F, 0x10, 0x10, 0x0E, 0x01, 0x01, 0x1E};
    case 'T':
      return {0x1F, 0x04, 0x04, 0x04, 0x04, 0x04, 0x04};
    case 'U':
      return {0x11, 0x11, 0x11, 0x11, 0x11, 0x11, 0x0E};
    case 'V':
      return {0x11, 0x11, 0x11, 0x11, 0x11, 0x0A, 0x04};
    case 'W':
      return {0x11, 0x11, 0x11, 0x15, 0x15, 0x15, 0x0A};
    case 'X':
      return {0x11, 0x11, 0x0A, 0x04, 0x0A, 0x11, 0x11};
    case 'Y':
      return {0x11, 0x11, 0x0A, 0x04, 0x04, 0x04, 0x04};
    case 'Z':
      return {0x1F, 0x01, 0x02, 0x04, 0x08, 0x10, 0x1F};
    case '0':
      return {0x0E, 0x11, 0x13, 0x15, 0x19, 0x11, 0x0E};
    case '1':
      return {0x04, 0x0C, 0x04, 0x04, 0x04, 0x04, 0x0E};
    case '2':
      return {0x0E, 0x11, 0x01, 0x02, 0x04, 0x08, 0x1F};
    case '3':
      return {0x1E, 0x01, 0x01, 0x0E, 0x01, 0x01, 0x1E};
    case '4':
      return {0x02, 0x06, 0x0A, 0x12, 0x1F, 0x02, 0x02};
    case '5':
      return {0x1F, 0x10, 0x10, 0x1E, 0x01, 0x01, 0x1E};
    case '6':
      return {0x0E, 0x10, 0x10, 0x1E, 0x11, 0x11, 0x0E};
    case '7':
      return {0x1F, 0x01, 0x02, 0x04, 0x08, 0x08, 0x08};
    case '8':
      return {0x0E, 0x11, 0x11, 0x0E, 0x11, 0x11, 0x0E};
    case '9':
      return {0x0E, 0x11, 0x11, 0x0F, 0x01, 0x01, 0x0E};
    case ':':
      return {0x00, 0x04, 0x04, 0x00, 0x04, 0x04, 0x00};
    case '.':
      return {0x00, 0x00, 0x00, 0x00, 0x00, 0x06, 0x06};
    case ',':
      return {0x00, 0x00, 0x00, 0x00, 0x06, 0x06, 0x04};
    case '-':
      return {0x00, 0x00, 0x00, 0x1F, 0x00, 0x00, 0x00};
    case '(':
      return {0x02, 0x04, 0x08, 0x08, 0x08, 0x04, 0x02};
    case ')':
      return {0x08, 0x04, 0x02, 0x02, 0x02, 0x04, 0x08};
    case '/':
      return {0x01, 0x02, 0x02, 0x04, 0x08, 0x08, 0x10};
    case '%':
      return {0x19, 0x19, 0x02, 0x04, 0x08, 0x13, 0x13};
    case '+':
      return {0x00, 0x04, 0x04, 0x1F, 0x04, 0x04, 0x00};
    case '=':
      return {0x00, 0x1F, 0x00, 0x00, 0x1F, 0x00, 0x00};
    case '\'':
      return {0x06, 0x06, 0x04, 0x00, 0x00, 0x00, 0x00};
    case '"':
      return {0x0A, 0x0A, 0x0A, 0x00, 0x00, 0x00, 0x00};
    case '!':
      return {0x04, 0x04, 0x04, 0x04, 0x04, 0x00, 0x04};
    case '?':
      return {0x0E, 0x11, 0x01, 0x02, 0x04, 0x00, 0x04};
    case ' ':
    default:
      return {0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00};
  }
}

std::vector<std::string> wrap_words(const std::string& text, const std::size_t max_chars) {
  std::vector<std::string> lines;
  if (text.empty() || max_chars == 0) {
    return lines;
  }

  std::istringstream iss(text);
  std::string word;
  std::string current;

  while (iss >> word) {
    if (word.size() > max_chars) {
      if (!current.empty()) {
        lines.push_back(current);
        current.clear();
      }
      std::size_t offset = 0;
      while (offset < word.size()) {
        lines.push_back(word.substr(offset, max_chars));
        offset += max_chars;
      }
      continue;
    }

    if (current.empty()) {
      current = word;
      continue;
    }

    if ((current.size() + 1 + word.size()) <= max_chars) {
      current.push_back(' ');
      current.append(word);
      continue;
    }

    lines.push_back(current);
    current = word;
  }

  if (!current.empty()) {
    lines.push_back(current);
  }

  if (lines.empty()) {
    lines.push_back(text.substr(0, max_chars));
  }
  return lines;
}

class EpaperDisplay final : public Display {
 public:
  void init() override {
    board_ = default_board_config();
    ESP_LOGI(kTag, "Board target: %s", board_.target);
    ESP_LOGI(kTag, "Board name: %s", board_.board_name);
    ESP_LOGI(kTag, "Display: %s", board_.display_name);
    ESP_LOGI(kTag, "Display pin map ready: %s", has_ready_display_pin_map(board_) ? "yes" : "no");

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
    ESP_LOGI(kTag, "BUSY level after init: %d", gpio_get_level(to_gpio_num(board_.display_pins.busy)));
  }

  void clear() override {
    if (!hardware_ready_) {
      return;
    }
    (void)clear_panel_once();
  }

  void present(const ScreenFrame& frame) override {
    if (!hardware_ready_) {
      return;
    }

    const std::string signature = frame_signature(frame);
    if (!first_present_done_ && signature.empty()) {
      return;
    }
    if (first_present_done_ && signature == last_signature_) {
      return;
    }
    last_signature_ = signature;

    ESP_LOGI(kTag, "----------------");
    if (!frame.title.empty()) {
      ESP_LOGI(kTag, "TITLE: %s", frame.title.c_str());
    }
    if (!frame.subtitle.empty()) {
      ESP_LOGI(kTag, "SUBTITLE: %s", frame.subtitle.c_str());
    }
    for (const auto& line : frame.body_lines) {
      ESP_LOGI(kTag, "BODY: %s", line.c_str());
    }
    if (!frame.footer.empty()) {
      ESP_LOGI(kTag, "FOOTER: %s", frame.footer.c_str());
    }

    std::vector<uint8_t> image = render_frame_bitmap(frame);
    const std::size_t black_bits = count_black_bits(image);
    ESP_LOGI(
        kTag,
        "Rendered bitmap stats: black_bits=%zu ratio=%.4f",
        black_bits,
        static_cast<double>(black_bits) / static_cast<double>(kPanelWidth * kPanelHeight));
    if (kUiDilateRadius > 0) {
      image = dilate_black_pixels(image, kUiDilateRadius);
      ESP_LOGI(kTag, "Applied UI stroke dilation radius=%d", kUiDilateRadius);
    }
    display_bitmap(image);
    first_present_done_ = true;
  }

 private:
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
    // Match Python driver (RPi gpiozero Button pull_up=False).
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
    ESP_ERROR_CHECK(gpio_set_level(to_gpio_num(board_.display_pins.power_enable), enabled ? 1 : 0));
    power_enabled_ = enabled;
    if (enabled) {
      vTaskDelay(pdMS_TO_TICKS(kPowerStabilizeMs));
    }
  }

  void reset_panel() {
    ESP_LOGI(kTag, "BUSY before RST = %d", gpio_get_level(to_gpio_num(board_.display_pins.busy)));
    ESP_ERROR_CHECK(gpio_set_level(to_gpio_num(board_.display_pins.rst), 1));
    vTaskDelay(pdMS_TO_TICKS(kResetHighMs));
    ESP_ERROR_CHECK(gpio_set_level(to_gpio_num(board_.display_pins.rst), 0));
    esp_rom_delay_us(kResetLowUs);
    ESP_ERROR_CHECK(gpio_set_level(to_gpio_num(board_.display_pins.rst), 1));
    vTaskDelay(pdMS_TO_TICKS(kResetHighMs));
    ESP_LOGI(kTag, "BUSY after  RST = %d", gpio_get_level(to_gpio_num(board_.display_pins.busy)));
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

  bool wait_until_idle(const char* label, const int timeout_ms) {
    const int64_t start_ms = esp_timer_get_time() / 1000;
    int64_t last_log_ms = -1000;
    int busy_level = gpio_get_level(to_gpio_num(board_.display_pins.busy));
    while (busy_level == 0) {
      const int64_t now_ms = esp_timer_get_time() / 1000;
      const int64_t elapsed = now_ms - start_ms;
      if (elapsed > timeout_ms) {
        ESP_LOGE(
            kTag,
            "[%s] TIMEOUT after %lld ms (BUSY=%d)",
            label,
            static_cast<long long>(elapsed),
            busy_level);
        return false;
      }
      if ((elapsed - last_log_ms) >= 1000) {
        ESP_LOGI(
            kTag,
            "[%s] waiting... %lld ms BUSY=%d",
            label,
            static_cast<long long>(elapsed),
            busy_level);
        last_log_ms = elapsed;
      }
      vTaskDelay(pdMS_TO_TICKS(100));
      busy_level = gpio_get_level(to_gpio_num(board_.display_pins.busy));
    }
    vTaskDelay(pdMS_TO_TICKS(20));

    const int64_t done_ms = (esp_timer_get_time() / 1000) - start_ms;
    ESP_LOGI(
        kTag,
        "[%s] done after %lld ms BUSY=%d",
        label,
        static_cast<long long>(done_ms),
        busy_level);
    return true;
  }

  bool init_panel_registers() {
    ESP_LOGI(kTag, "Init commands (esp32 bring-up sequence)...");
    send_command(0x01);
    send_data(0x07);
    send_data(0x07);
    send_data(0x3F);
    send_data(0x3F);
    vTaskDelay(pdMS_TO_TICKS(10));

    ESP_LOGI(kTag, "Power ON (0x04)...");
    send_command(0x04);
    vTaskDelay(pdMS_TO_TICKS(100));
    if (!wait_until_idle("0x04", kPowerOnTimeoutMs)) {
      return false;
    }

    send_command(0x00);
    send_data(0x1F);
    vTaskDelay(pdMS_TO_TICKS(10));

    send_command(0x61);
    send_data(0x03);
    send_data(0x20);
    send_data(0x01);
    send_data(0xE0);
    vTaskDelay(pdMS_TO_TICKS(10));

    send_command(0x15);
    send_data(0x00);
    vTaskDelay(pdMS_TO_TICKS(10));

    send_command(0x50);
    send_data(0x10);
    if (kEnableGrayFixInit) {
      send_data(0x17);
      send_command(0x52);
      send_data(0x03);
    } else {
      send_data(0x07);
    }
    vTaskDelay(pdMS_TO_TICKS(10));

    send_command(0x60);
    send_data(0x22);
    vTaskDelay(pdMS_TO_TICKS(10));
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
    ESP_LOGI(kTag, "Clear panel (esp32 bring-up sequence)...");
    if (!wake_panel_if_needed()) {
      return false;
    }
    send_command(0x10);
    send_fill_buffer(0x00, kPanelBufferSize);
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

  void display_bitmap(const std::vector<uint8_t>& image) {
    if (image.size() != static_cast<size_t>(kPanelBufferSize)) {
      ESP_LOGE(
          kTag,
          "Invalid image size: %u, expected %d",
          static_cast<unsigned>(image.size()),
          kPanelBufferSize);
      return;
    }

    if (!wake_panel_if_needed()) {
      return;
    }
    if (kUseExactFullBlackTest) {
      ESP_LOGI(kTag, "Exact raw full-black test active");
      send_command(0x10);
      send_fill_buffer(0x00, kPanelBufferSize);
      send_command(0x13);
      send_fill_buffer(0xFF, kPanelBufferSize);
      ESP_LOGI(kTag, "Frame mode: raw test old=0x00, new=0xFF");
    } else {
      if (kUsePanelDiagnosticImage) {
        ESP_LOGI(kTag, "Panel diagnostic override active (structured raw runs)");
        send_command(0x10);
        send_fill_buffer(0x00, kPanelBufferSize);
        send_command(0x13);
        send_diagnostic_bars_run_image();
        ESP_LOGI(kTag, "Frame mode: raw runs old=0x00, new=diagnostic-bars");
      } else {
        send_command(0x10);
        if (previous_frame_valid_ &&
            previous_frame_.size() == static_cast<size_t>(kPanelBufferSize)) {
          send_data_buffer(previous_frame_.data(), kPanelBufferSize);
          ESP_LOGI(kTag, "Frame mode: raw image old=previous, new=image");
        } else {
          if (kUseInvertedFirstFrame) {
            const auto inverted = make_inverted_image(image);
            send_data_buffer(inverted.data(), kPanelBufferSize);
            ESP_LOGI(kTag, "Frame mode: raw image old=~image first-frame, new=image");
          } else {
            send_fill_buffer(0x00, kPanelBufferSize);
            ESP_LOGI(kTag, "Frame mode: raw image old=0x00 baseline, new=image");
          }
        }
        send_command(0x13);
        send_data_buffer(image.data(), kPanelBufferSize);
      }
    }

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

  void send_inverted_buffer(const uint8_t* data, const size_t len) {
    if (!spi_ready_ || data == nullptr || len == 0) {
      return;
    }
    std::array<uint8_t, kFillChunkBytes> inverted_chunk{};
    begin_data_stream();
    size_t sent = 0;
    while (sent < len) {
      const size_t chunk = std::min(inverted_chunk.size(), len - sent);
      for (size_t i = 0; i < chunk; ++i) {
        inverted_chunk[i] = static_cast<uint8_t>(~data[sent + i]);
      }
      spi_write_bytes(inverted_chunk.data(), chunk);
      sent += chunk;
    }
    end_data_stream();
  }

  void send_diagnostic_bars_run_image() {
    constexpr int top_y0 = 70;
    constexpr int top_y1 = 125;
    constexpr int mid_y0 = 160;
    constexpr int mid_y1 = 320;
    constexpr int bot_y0 = 350;
    constexpr int bot_y1 = 390;
    constexpr int top_x0_bytes = 80 / 8;
    constexpr int top_x1_bytes = 720 / 8;
    constexpr int bot_x0_bytes = 120 / 8;
    constexpr int bot_x1_bytes = 680 / 8;

    begin_data_stream();
    std::array<uint8_t, kPanelWidthBytes> row_buffer{};
    for (int y = 0; y < kPanelHeight; ++y) {
      int black_start = -1;
      int black_end = -1;
      if (y >= top_y0 && y < top_y1) {
        black_start = top_x0_bytes;
        black_end = top_x1_bytes;
      } else if (y >= mid_y0 && y < mid_y1) {
        black_start = top_x0_bytes;
        black_end = top_x1_bytes;
      } else if (y >= bot_y0 && y < bot_y1) {
        black_start = bot_x0_bytes;
        black_end = bot_x1_bytes;
      }

      for (int x = 0; x < kPanelWidthBytes; ++x) {
        row_buffer[static_cast<size_t>(x)] =
            (black_start >= 0 && x >= black_start && x < black_end) ? 0xFF : 0x00;
      }
      spi_write_bytes(row_buffer.data(), row_buffer.size());
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

  static void set_black_pixel(std::vector<uint8_t>& image, const int x, const int y) {
    if (x < 0 || x >= kPanelWidth || y < 0 || y >= kPanelHeight) {
      return;
    }
    const int offset = (y * kPanelWidthBytes) + (x / 8);
    const uint8_t bit = static_cast<uint8_t>(0x80U >> (x % 8));
    image[offset] = static_cast<uint8_t>(image[offset] | bit);
  }

  static void fill_black_rect(
      std::vector<uint8_t>& image,
      const int x0,
      const int y0,
      const int x1,
      const int y1) {
    for (int y = y0; y < y1; ++y) {
      for (int x = x0; x < x1; ++x) {
        set_black_pixel(image, x, y);
      }
    }
  }

  static void fill_white_rect(
      std::vector<uint8_t>& image,
      const int x0,
      const int y0,
      const int x1,
      const int y1) {
    for (int y = y0; y < y1; ++y) {
      for (int x = x0; x < x1; ++x) {
        clear_pixel_raw(image, x, y);
      }
    }
  }

  static void draw_glyph(
      std::vector<uint8_t>& image,
      const int x,
      const int y,
      const char ch,
      const int scale,
      const bool black = true) {
    (void)scale;
    using panel_font_assets::BitmapFont;
    using panel_font_assets::Glyph;

    const auto glyph_index = [](char value) -> std::size_t {
      const unsigned char code = static_cast<unsigned char>(value);
      if (code < 32 || code > 126) {
        return static_cast<std::size_t>('?' - 32);
      }
      return static_cast<std::size_t>(code - 32);
    };

    const auto font_for_scale = [black](const int requested_scale) -> const BitmapFont& {
      if (requested_scale <= 1) {
        return panel_font_assets::kFontJetBold13;
      }
      if (requested_scale == 2) {
        return black ? panel_font_assets::kFontInterMedium18 : panel_font_assets::kFontInterBold17;
      }
      if (requested_scale == 3) {
        return panel_font_assets::kFontInterBlack29;
      }
      return panel_font_assets::kFontInterBlack29;
    };

    const BitmapFont& font = font_for_scale(scale);
    const Glyph& glyph = font.glyphs[glyph_index(ch)];
    if (glyph.width == 0 || glyph.height == 0) {
      return;
    }

    const int baseline_y = y + font.ascent;
    const int glyph_x0 = x + glyph.left;
    const int glyph_y0 = baseline_y + glyph.top;
    const int row_bytes = (glyph.width + 7) / 8;
    const std::uint8_t* bitmap = font.bitmap + glyph.bitmap_offset;
    for (int row = 0; row < glyph.height; ++row) {
      for (int col = 0; col < glyph.width; ++col) {
        const std::uint8_t byte = bitmap[row * row_bytes + (col / 8)];
        const bool on = (byte & (0x80U >> (col % 8))) != 0;
        if (!on) {
          continue;
        }
        const int px = glyph_x0 + col;
        const int py = glyph_y0 + row;
        if (black) {
          set_black_pixel(image, px, py);
        } else {
          clear_pixel_raw(image, px, py);
        }
      }
    }
  }

  static void draw_text_line(
      std::vector<uint8_t>& image,
      const int x,
      const int y,
      const std::string& text,
      const int scale,
      const int max_chars) {
    using panel_font_assets::BitmapFont;

    const auto font_for_scale = [](const int requested_scale) -> const BitmapFont& {
      if (requested_scale <= 1) {
        return panel_font_assets::kFontJetBold13;
      }
      if (requested_scale == 2) {
        return panel_font_assets::kFontInterMedium18;
      }
      if (requested_scale == 3) {
        return panel_font_assets::kFontInterBlack29;
      }
      return panel_font_assets::kFontInterBlack29;
    };

    const auto glyph_index = [](char value) -> std::size_t {
      const unsigned char code = static_cast<unsigned char>(value);
      if (code < 32 || code > 126) {
        return static_cast<std::size_t>('?' - 32);
      }
      return static_cast<std::size_t>(code - 32);
    };

    const BitmapFont& font = font_for_scale(scale);
    int cx = x;
    int drawn = 0;
    for (const char ch : text) {
      if (max_chars > 0 && drawn >= max_chars) {
        break;
      }
      draw_glyph(image, cx, y, ch, scale, true);
      cx += font.glyphs[glyph_index(ch)].advance;
      ++drawn;
    }
  }

  static void draw_text_line_inverted(
      std::vector<uint8_t>& image,
      const int x,
      const int y,
      const std::string& text,
      const int scale,
      const int max_chars) {
    using panel_font_assets::BitmapFont;

    const auto font_for_scale = [](const int requested_scale) -> const BitmapFont& {
      if (requested_scale <= 1) {
        return panel_font_assets::kFontJetBold13;
      }
      if (requested_scale == 2) {
        return panel_font_assets::kFontInterBold17;
      }
      if (requested_scale == 3) {
        return panel_font_assets::kFontInterBlack29;
      }
      return panel_font_assets::kFontInterBlack29;
    };

    const auto glyph_index = [](char value) -> std::size_t {
      const unsigned char code = static_cast<unsigned char>(value);
      if (code < 32 || code > 126) {
        return static_cast<std::size_t>('?' - 32);
      }
      return static_cast<std::size_t>(code - 32);
    };

    const BitmapFont& font = font_for_scale(scale);
    int cx = x;
    int drawn = 0;
    for (const char ch : text) {
      if (max_chars > 0 && drawn >= max_chars) {
        break;
      }
      draw_glyph(image, cx, y, ch, scale, false);
      cx += font.glyphs[glyph_index(ch)].advance;
      ++drawn;
    }
  }

  static std::string trim_copy(const std::string& in) {
    std::size_t start = 0;
    while (start < in.size() &&
           std::isspace(static_cast<unsigned char>(in[start])) != 0) {
      ++start;
    }
    if (start == in.size()) {
      return "";
    }
    std::size_t end = in.size();
    while (end > start &&
           std::isspace(static_cast<unsigned char>(in[end - 1])) != 0) {
      --end;
    }
    return in.substr(start, end - start);
  }

  static std::string trunc_text(const std::string& text, const int max_chars) {
    if (max_chars <= 0) {
      return "";
    }
    if (static_cast<int>(text.size()) <= max_chars) {
      return text;
    }
    if (max_chars <= 3) {
      return text.substr(0, static_cast<size_t>(max_chars));
    }
    return text.substr(0, static_cast<size_t>(max_chars - 3)) + "...";
  }

  static int text_width_px(const std::string& text, const int scale) {
    using panel_font_assets::BitmapFont;
    const auto font_for_scale = [](const int requested_scale) -> const BitmapFont& {
      if (requested_scale <= 1) {
        return panel_font_assets::kFontJetBold13;
      }
      if (requested_scale == 2) {
        return panel_font_assets::kFontInterMedium18;
      }
      if (requested_scale == 3) {
        return panel_font_assets::kFontInterBlack29;
      }
      return panel_font_assets::kFontInterBlack29;
    };
    const auto glyph_index = [](char value) -> std::size_t {
      const unsigned char code = static_cast<unsigned char>(value);
      if (code < 32 || code > 126) {
        return static_cast<std::size_t>('?' - 32);
      }
      return static_cast<std::size_t>(code - 32);
    };

    const BitmapFont& font = font_for_scale(scale);
    int width = 0;
    for (const char ch : text) {
      width += font.glyphs[glyph_index(ch)].advance;
    }
    return width;
  }

  static std::string truncate_text_px(
      const std::string& text,
      const int scale,
      const int max_width_px) {
    if (text.empty()) {
      return "";
    }
    if (text_width_px(text, scale) <= max_width_px) {
      return text;
    }
    const std::string ellipsis = "...";
    const int ellipsis_width = text_width_px(ellipsis, scale);
    const int budget = std::max(0, max_width_px - ellipsis_width);
    std::string out;
    for (const char ch : text) {
      const std::string candidate = out + ch;
      if (text_width_px(candidate, scale) > budget) {
        break;
      }
      out = candidate;
    }
    return out.empty() ? ellipsis : (out + ellipsis);
  }

  static void draw_outline_rect(
      std::vector<uint8_t>& image,
      const int x0,
      const int y0,
      const int x1,
      const int y1,
      const int thickness) {
    const int t = thickness > 0 ? thickness : 1;
    fill_black_rect(image, x0, y0, x1, y0 + t);
    fill_black_rect(image, x0, y1 - t, x1, y1);
    fill_black_rect(image, x0, y0, x0 + t, y1);
    fill_black_rect(image, x1 - t, y0, x1, y1);
  }

  static bool point_in_rounded_rect(
      const int px,
      const int py,
      const int x0,
      const int y0,
      const int x1,
      const int y1,
      const int radius) {
    if (px < x0 || px >= x1 || py < y0 || py >= y1) {
      return false;
    }
    const int w = x1 - x0;
    const int h = y1 - y0;
    const int r = std::max(0, std::min(radius, std::min(w, h) / 2));
    if (r <= 0) {
      return true;
    }
    if ((px >= x0 + r && px < x1 - r) || (py >= y0 + r && py < y1 - r)) {
      return true;
    }
    const int cx = (px < x0 + r) ? (x0 + r) : (x1 - r - 1);
    const int cy = (py < y0 + r) ? (y0 + r) : (y1 - r - 1);
    const int dx = px - cx;
    const int dy = py - cy;
    return (dx * dx + dy * dy) <= (r * r);
  }

  static void fill_rounded_rect(
      std::vector<uint8_t>& image,
      const int x0,
      const int y0,
      const int x1,
      const int y1,
      const int radius,
      const bool black) {
    for (int y = y0; y < y1; ++y) {
      for (int x = x0; x < x1; ++x) {
        if (!point_in_rounded_rect(x, y, x0, y0, x1, y1, radius)) {
          continue;
        }
        if (black) {
          set_black_pixel(image, x, y);
        } else {
          clear_pixel_raw(image, x, y);
        }
      }
    }
  }

  static void draw_rounded_rect_outline(
      std::vector<uint8_t>& image,
      const int x0,
      const int y0,
      const int x1,
      const int y1,
      const int radius,
      const int thickness) {
    fill_rounded_rect(image, x0, y0, x1, y1, radius, true);
    const int t = std::max(1, thickness);
    const int inner_x0 = x0 + t;
    const int inner_y0 = y0 + t;
    const int inner_x1 = x1 - t;
    const int inner_y1 = y1 - t;
    if (inner_x1 > inner_x0 && inner_y1 > inner_y0) {
      fill_rounded_rect(
          image,
          inner_x0,
          inner_y0,
          inner_x1,
          inner_y1,
          std::max(0, radius - t),
          false);
    }
  }

  static void draw_rounded_rect_stroke(
      std::vector<uint8_t>& image,
      const int x0,
      const int y0,
      const int x1,
      const int y1,
      const int radius,
      const int thickness) {
    const int t = std::max(1, thickness);
    const int inner_x0 = x0 + t;
    const int inner_y0 = y0 + t;
    const int inner_x1 = x1 - t;
    const int inner_y1 = y1 - t;
    const int inner_radius = std::max(0, radius - t);
    for (int y = y0; y < y1; ++y) {
      for (int x = x0; x < x1; ++x) {
        if (!point_in_rounded_rect(x, y, x0, y0, x1, y1, radius)) {
          continue;
        }
        if (inner_x1 > inner_x0 &&
            inner_y1 > inner_y0 &&
            point_in_rounded_rect(x, y, inner_x0, inner_y0, inner_x1, inner_y1, inner_radius)) {
          continue;
        }
        set_black_pixel(image, x, y);
      }
    }
  }

  static void draw_text_centered(
      std::vector<uint8_t>& image,
      const int x0,
      const int x1,
      const int y,
      const std::string& text,
      const int scale,
      const int max_chars) {
    const std::string clipped = trunc_text(text, max_chars);
    const int w = text_width_px(clipped, scale);
    const int x = x0 + ((x1 - x0 - w) / 2);
    draw_text_line(image, x, y, clipped, scale, max_chars);
  }

  static void draw_text_centered_inverted(
      std::vector<uint8_t>& image,
      const int x0,
      const int x1,
      const int y,
      const std::string& text,
      const int scale,
      const int max_chars) {
    const std::string clipped = trunc_text(text, max_chars);
    const int w = text_width_px(clipped, scale);
    const int x = x0 + ((x1 - x0 - w) / 2);
    draw_text_line_inverted(image, x, y, clipped, scale, max_chars);
  }

  static std::string body_line_with_prefix(
      const std::vector<std::string>& lines,
      const std::string& prefix) {
    for (const auto& line : lines) {
      if (line.rfind(prefix, 0) == 0) {
        return line;
      }
    }
    return "";
  }

  static int body_line_int_with_prefix(
      const std::vector<std::string>& lines,
      const std::string& prefix,
      const int fallback) {
    const std::string line = body_line_with_prefix(lines, prefix);
    if (line.empty()) {
      return fallback;
    }
    const std::string raw = trim_copy(line.substr(prefix.size()));
    char* end = nullptr;
    const long parsed = std::strtol(raw.c_str(), &end, 10);
    if (end == raw.c_str() || (end != nullptr && *end != '\0')) {
      return fallback;
    }
    return static_cast<int>(parsed);
  }

  static bool body_line_bool_with_prefix(
      const std::vector<std::string>& lines,
      const std::string& prefix,
      const bool fallback) {
    const std::string line = body_line_with_prefix(lines, prefix);
    if (line.empty()) {
      return fallback;
    }
    const std::string raw = trim_copy(line.substr(prefix.size()));
    if (raw == "1" || raw == "true" || raw == "TRUE" || raw == "on" || raw == "ON") {
      return true;
    }
    if (raw == "0" || raw == "false" || raw == "FALSE" || raw == "off" || raw == "OFF") {
      return false;
    }
    return fallback;
  }

  static void draw_text_wrapped(
      std::vector<uint8_t>& image,
      const int x,
      int y,
      const int width_px,
      const std::string& text,
      const int scale,
      const int max_lines) {
    if (max_lines <= 0 || width_px <= 0) {
      return;
    }
    const int avg_advance =
        scale <= 1 ? 8 : (scale == 2 ? 10 : (scale == 3 ? 15 : 18));
    const int chars_per_line = width_px / avg_advance > 0 ? width_px / avg_advance : 1;
    const auto wrapped = wrap_words(text, static_cast<std::size_t>(chars_per_line));
    const int line_h = scale <= 1 ? 18 : (scale == 2 ? 24 : 34);
    int drawn = 0;
    for (const auto& line : wrapped) {
      if (drawn >= max_lines) {
        break;
      }
      draw_text_line(image, x, y, line, scale, chars_per_line);
      y += line_h;
      ++drawn;
    }
  }

  static void draw_text_wrapped_inverted(
      std::vector<uint8_t>& image,
      const int x,
      int y,
      const int width_px,
      const std::string& text,
      const int scale,
      const int max_lines) {
    if (max_lines <= 0 || width_px <= 0) {
      return;
    }
    const int avg_advance =
        scale <= 1 ? 8 : (scale == 2 ? 10 : (scale == 3 ? 15 : 18));
    const int chars_per_line = width_px / avg_advance > 0 ? width_px / avg_advance : 1;
    const auto wrapped = wrap_words(text, static_cast<std::size_t>(chars_per_line));
    const int line_h = scale <= 1 ? 18 : (scale == 2 ? 24 : 34);
    int drawn = 0;
    for (const auto& line : wrapped) {
      if (drawn >= max_lines) {
        break;
      }
      draw_text_line_inverted(image, x, y, line, scale, chars_per_line);
      y += line_h;
      ++drawn;
    }
  }

  static std::vector<uint8_t> render_landing_bitmap(const ScreenFrame& frame) {
    std::string lang_label = "English";
    std::string lang_code = "en-US";
    const std::string language_line = body_line_with_prefix(frame.body_lines, "Language:");
    if (!language_line.empty()) {
      const auto after_colon = trim_copy(language_line.substr(std::string("Language:").size()));
      const auto lpar = after_colon.find('(');
      const auto rpar = after_colon.find(')');
      if (lpar != std::string::npos && rpar != std::string::npos && rpar > lpar) {
        lang_label = trim_copy(after_colon.substr(0, lpar));
        lang_code = trim_copy(after_colon.substr(lpar + 1, rpar - lpar - 1));
      } else {
        lang_label = after_colon;
      }
    }

    std::vector<uint8_t> image(kPanelBufferSize, 0x00);  // white

    constexpr int margin = 24;
    constexpr int content_x0 = margin + 16;
    constexpr int content_x1 = kPanelWidth - margin - 16;
    constexpr int content_w = content_x1 - content_x0;
    constexpr int title_scale = 3;
    constexpr int body_scale = 2;
    constexpr int button_scale = 2;
    constexpr int meta_scale = 1;

    int y = margin + 18;
    const std::string title = truncate_text_px("INTELLI SPARK BOARD", title_scale, content_w);
    draw_text_centered(image, content_x0, content_x1, y, title, title_scale, 40);
    const int title_block_h = 36;
    y += title_block_h;

    const std::string subtitle = truncate_text_px(
        "Welcome. Learn controls before first setup.",
        body_scale,
        content_w);
    draw_text_centered(image, content_x0, content_x1, y, subtitle, body_scale, 64);
    const int subtitle_block_h = 44;

    constexpr std::array<const char*, 4> tip_title = {
        "Rotate", "Press", "Long Press", "Hold Voice Key"};
    constexpr std::array<const char*, 4> tip_body = {
        "MOVE FOCUS", "CONFIRM", "BACK TO HOME", "TALK TO ASSISTANT"};
    const int tip_gap_x = 12;
    const int tip_gap_y = 10;
    const int tip_w = (content_w - tip_gap_x) / 2;
    const int tip_h = 60;
    const int tips_y0 = margin + 18 + title_block_h + subtitle_block_h;
    for (int i = 0; i < 4; ++i) {
      const int col = i % 2;
      const int row = i / 2;
      const int x0 = content_x0 + col * (tip_w + tip_gap_x);
      const int y0 = tips_y0 + row * (tip_h + tip_gap_y);
      const int x1 = x0 + tip_w;
      const int y1 = y0 + tip_h;
      const bool emphasis = i < 2;
      if (emphasis) {
        fill_rounded_rect(image, x0, y0, x1, y1, 10, true);
        draw_rounded_rect_stroke(image, x0, y0, x1, y1, 10, 2);
        draw_text_centered_inverted(image, x0 + 10, x1 - 10, y0 + 8, tip_title[i], button_scale, 24);
        draw_text_centered_inverted(image, x0 + 10, x1 - 10, y0 + 34, tip_body[i], meta_scale, 40);
      } else {
        draw_rounded_rect_outline(image, x0, y0, x1, y1, 10, 2);
        draw_text_centered(image, x0 + 10, x1 - 10, y0 + 8, tip_title[i], button_scale, 24);
        draw_text_centered(image, x0 + 10, x1 - 10, y0 + 34, tip_body[i], meta_scale, 40);
      }
    }

    const int voice_hint_y = tips_y0 + (2 * tip_h) + tip_gap_y + 12;
    draw_text_line(image, content_x0, voice_hint_y, "VOICE KEY UNLOCKS AFTER FIRST SETUP.", meta_scale, 48);

    const int language_label_y = voice_hint_y + 20;
    draw_text_line(image, content_x0, language_label_y, "Language", button_scale, 18);
    const int chips_y0 = language_label_y + 26;
    const int chip_gap_x = 10;
    const int chip_w = (content_w - (2 * chip_gap_x)) / 3;
    const int chip_h = 40;
    constexpr std::array<const char*, 3> chip_codes = {"en-US", "es-ES", "fr-FR"};
    constexpr std::array<const char*, 3> chip_labels = {"ENGLISH", "SPANISH", "FRENCH"};
    for (int i = 0; i < 3; ++i) {
      const int x0 = content_x0 + i * (chip_w + chip_gap_x);
      const int x1 = x0 + chip_w;
      const int y1 = chips_y0 + chip_h;
      const bool active = (lang_code == chip_codes[i]);
      if (active) {
        fill_rounded_rect(image, x0, chips_y0, x1, y1, 10, true);
        draw_rounded_rect_stroke(image, x0 - 2, chips_y0 - 2, x1 + 2, y1 + 2, 11, 3);
      }
      if (active) {
        draw_rounded_rect_stroke(image, x0, chips_y0, x1, y1, 10, 2);
      } else {
        draw_rounded_rect_outline(image, x0, chips_y0, x1, y1, 10, 2);
      }
      if (active) {
        draw_text_centered_inverted(image, x0 + 8, x1 - 8, chips_y0 + 12, chip_labels[i], meta_scale, 20);
      } else {
        draw_text_centered(image, x0 + 8, x1 - 8, chips_y0 + 12, chip_labels[i], meta_scale, 20);
      }
    }

    std::string status = frame.body_lines.empty() ? "" : frame.body_lines.back();
    if (status.empty()) {
      status = "ROTATE TO CHOOSE LANGUAGE, THEN CLICK TO START SETUP.";
    } else {
      for (char& ch : status) {
        ch = static_cast<char>(std::toupper(static_cast<unsigned char>(ch)));
      }
    }
    const int button_w = std::min(420, content_w);
    const int button_h = 52;
    const int button_x0 = content_x0 + (content_w - button_w) / 2;
    const int button_y1 = kPanelHeight - margin - 18;
    const int button_y0 = button_y1 - button_h;
    const int status_y = button_y0 - 66;
    draw_text_line(
        image,
        content_x0,
        status_y,
        truncate_text_px(status, meta_scale, content_w),
        meta_scale,
        80);

    fill_rounded_rect(image, button_x0, button_y0, button_x0 + button_w, button_y1, 12, true);
    draw_rounded_rect_stroke(image, button_x0, button_y0, button_x0 + button_w, button_y1, 12, 2);
    draw_rounded_rect_stroke(
        image,
        button_x0 - 2,
        button_y0 - 2,
        button_x0 + button_w + 2,
        button_y1 + 2,
        12,
        3);
    std::string cta = frame.footer.empty() ? "Rotate to choose language" : frame.footer;
    cta = truncate_text_px(cta, button_scale, button_w - 24);
    draw_text_centered_inverted(
        image,
        button_x0 + 12,
        button_x0 + button_w - 12,
        button_y0 + 14,
        cta,
        button_scale,
        64);
    return image;
  }

  static std::vector<uint8_t> render_onboarding_bitmap(const ScreenFrame& frame) {
    std::vector<uint8_t> image(kPanelBufferSize, 0x00);  // white
    draw_outline_rect(image, 12, 12, kPanelWidth - 12, kPanelHeight - 12, 3);

    std::string step_key = "start";
    const std::string step_key_line = body_line_with_prefix(frame.body_lines, "Step Key:");
    if (!step_key_line.empty()) {
      step_key = trim_copy(step_key_line.substr(std::string("Step Key:").size()));
    }

    int step_cur = 1;
    int step_total = 4;
    std::string step_name = "Start";
    const std::string step_line = body_line_with_prefix(frame.body_lines, "Step:");
    if (!step_line.empty()) {
      char name_buf[80] = {0};
      const int parsed = std::sscanf(step_line.c_str(), "Step: %d/%d - %79[^\n]", &step_cur, &step_total, name_buf);
      if (parsed >= 2) {
        if (step_cur < 1) {
          step_cur = 1;
        }
        if (step_total < 1) {
          step_total = 1;
        }
      }
      if (parsed == 3) {
        step_name = trim_copy(name_buf);
      }
    }
    const int start_focus = body_line_int_with_prefix(frame.body_lines, "Start Focus:", 0);
    const int qr_focus = body_line_int_with_prefix(frame.body_lines, "QR Focus:", 0);
    const int prefs_focus = body_line_int_with_prefix(frame.body_lines, "Prefs Focus:", 0);
    const int voice_focus = body_line_int_with_prefix(frame.body_lines, "Voice Focus:", 0);

    const std::string language_line = body_line_with_prefix(frame.body_lines, "Language:");
    const std::string pair_token_line = body_line_with_prefix(frame.body_lines, "Pair token:");
    const std::string timezone_line = body_line_with_prefix(frame.body_lines, "Timezone:");
    const std::string autosync_line = body_line_with_prefix(frame.body_lines, "Auto Sync:");
    const std::string wifi_line = body_line_with_prefix(frame.body_lines, "Wi-Fi:");

    std::string status = body_line_with_prefix(frame.body_lines, "Status:");
    if (!status.empty()) {
      status = trim_copy(status.substr(std::string("Status:").size()));
    }
    if (status.empty()) {
      status = "Rotate to choose setting, click to continue.";
    }

    draw_text_line(image, 40, 30, "FIRST SETUP", 3, 26);
    draw_text_line(
        image,
        40,
        66,
        "STEP " + std::to_string(step_cur) + "/" + std::to_string(step_total),
        2,
        20);

    const int bar_x0 = 420;
    const int bar_y0 = 72;
    const int bar_w = 340;
    const int bar_h = 14;
    draw_outline_rect(image, bar_x0, bar_y0, bar_x0 + bar_w, bar_y0 + bar_h, 2);
    const int seg_gap = 8;
    const int seg_w = (bar_w - ((step_total + 1) * seg_gap)) / step_total;
    for (int i = 0; i < step_total; ++i) {
      const int sx0 = bar_x0 + seg_gap + i * (seg_w + seg_gap);
      const int sx1 = sx0 + seg_w;
      if (i < step_cur) {
        fill_black_rect(image, sx0, bar_y0 + 3, sx1, bar_y0 + bar_h - 3);
      } else {
        draw_outline_rect(image, sx0, bar_y0 + 3, sx1, bar_y0 + bar_h - 3, 1);
      }
    }

    if (step_key == "start") {
      draw_text_line(image, 40, 118, "CONFIGURE NETWORK AND BASIC PREFERENCES.", 1, 52);
      draw_text_line(image, 40, 142, "PHONE PAIRING IS RECOMMENDED FOR WI-FI SETUP.", 1, 56);
      constexpr std::array<const char*, 2> kOptions = {"START PHONE PAIRING", "SKIP FOR NOW"};
      const int box_x0 = 184;
      const int box_x1 = 616;
      const int first_y = 218;
      for (int i = 0; i < 2; ++i) {
        const int y0 = first_y + i * 84;
        const int y1 = y0 + 58;
        if (i == start_focus) {
          fill_black_rect(image, box_x0, y0, box_x1, y1);
          draw_outline_rect(image, box_x0 - 3, y0 - 3, box_x1 + 3, y1 + 3, 3);
          draw_text_centered_inverted(image, box_x0 + 10, box_x1 - 10, y0 + 18, kOptions[i], 2, 34);
        } else {
          draw_outline_rect(image, box_x0, y0, box_x1, y1, 2);
          draw_text_centered(image, box_x0 + 10, box_x1 - 10, y0 + 18, kOptions[i], 2, 34);
        }
      }
      draw_text_line(image, 40, 428, "ROTATE TO CHOOSE  -  PRESS TO CONTINUE", 1, 54);
      return image;
    }

    if (step_key == "pair_qr") {
      draw_text_line(image, 40, 118, "PHONE PAIRING", 3, 24);
      draw_text_line(image, 40, 150, "SCAN QR TO CONFIGURE WI-FI", 1, 42);

      draw_outline_rect(image, 52, 192, 336, 416, 2);
      draw_text_line(image, 96, 278, "QR", 4, 6);

      draw_text_line(image, 372, 202, "1) OPEN PHONE CAMERA", 1, 34);
      draw_text_line(image, 372, 226, "2) SCAN CODE AND SUBMIT WI-FI", 1, 40);
      draw_text_line(image, 372, 250, "3) RETURN HERE AND CONFIRM", 1, 38);
      if (!pair_token_line.empty()) {
        draw_text_line(image, 372, 292, pair_token_line, 1, 40);
      }
      draw_text_wrapped(image, 372, 316, 360, status, 1, 3);

      constexpr std::array<const char*, 3> kActions = {"REFRESH QR", "I AM DONE", "SKIP"};
      const int bx = 372;
      const int by = 360;
      const int gap = 10;
      const int bw = 114;
      const int bh = 48;
      for (int i = 0; i < 3; ++i) {
        const int x0 = bx + i * (bw + gap);
        const int x1 = x0 + bw;
        const int y0 = by;
        const int y1 = y0 + bh;
        if (i == qr_focus) {
          fill_black_rect(image, x0, y0, x1, y1);
          draw_outline_rect(image, x0 - 3, y0 - 3, x1 + 3, y1 + 3, 3);
          draw_text_centered_inverted(image, x0 + 6, x1 - 6, y0 + 16, kActions[i], 1, 16);
        } else {
          draw_outline_rect(image, x0, y0, x1, y1, 2);
          draw_text_centered(image, x0 + 6, x1 - 6, y0 + 16, kActions[i], 1, 16);
        }
      }
      return image;
    }

    if (step_key == "prefs") {
      draw_text_line(image, 40, 118, "QUICK PREFERENCES", 3, 30);
      draw_text_line(image, 40, 150, "YOU CAN CHANGE THESE LATER IN SETTINGS.", 1, 54);
      if (!wifi_line.empty()) {
        draw_text_line(image, 40, 176, wifi_line, 1, 54);
      }

      const int row_x0 = 42;
      const int row_x1 = 758;
      const int row_h = 48;
      const int row_gap = 10;
      const int rows_top = 206;
      std::array<std::string, 3> labels = {"LANGUAGE", "TIMEZONE", "AUTO SYNC"};
      std::array<std::string, 3> values = {
          language_line.empty() ? "Language: English (en-US)" : language_line,
          timezone_line.empty() ? "Timezone: America/Toronto" : timezone_line,
          autosync_line.empty() ? "Auto Sync: ON" : autosync_line,
      };
      for (int i = 0; i < 3; ++i) {
        const int y0 = rows_top + i * (row_h + row_gap);
        const int y1 = y0 + row_h;
        draw_outline_rect(image, row_x0, y0, row_x1, y1, 2);
        if (i == prefs_focus) {
          fill_black_rect(image, row_x0 + 10, y0 + 8, row_x0 + 18, y1 - 8);
          draw_outline_rect(image, row_x0 - 3, y0 - 3, row_x1 + 3, y1 + 3, 3);
        }
        draw_text_line(image, 64, y0 + 14, labels[i], 2, 18);
        draw_text_line(image, 360, y0 + 14, values[i], 1, 38);
      }

      const int guide_x0 = 510;
      const int guide_x1 = 758;
      const int guide_y0 = 390;
      const int guide_y1 = 438;
      draw_text_line(image, 42, 404, "NEXT STEP ->", 2, 16);
      if (prefs_focus == 3) {
        fill_black_rect(image, guide_x0, guide_y0, guide_x1, guide_y1);
        draw_outline_rect(image, guide_x0 - 3, guide_y0 - 3, guide_x1 + 3, guide_y1 + 3, 3);
        draw_text_centered_inverted(image, guide_x0 + 8, guide_x1 - 8, guide_y0 + 16, "VOICE GUIDE >", 1, 24);
      } else {
        draw_outline_rect(image, guide_x0, guide_y0, guide_x1, guide_y1, 2);
        draw_text_centered(image, guide_x0 + 8, guide_x1 - 8, guide_y0 + 16, "VOICE GUIDE >", 1, 24);
      }
      return image;
    }

    if (step_key == "voice_guide") {
      draw_text_line(image, 40, 40, "VOICE SETUP", 3, 24);
      draw_outline_rect(image, 40, 84, 240, 196, 2);
      draw_text_centered(image, 56, 224, 120, "MIC", 4, 8);
      draw_text_centered(image, 56, 224, 164, "HOLD VOICE KEY", 1, 20);

      draw_text_line(image, 270, 96, "SPEAK", 1, 12);
      draw_text_wrapped(image, 270, 128, 470, "ADD MILK TO INVENTORY", 3, 2);
      fill_black_rect(image, 40, 206, 760, 208);
      draw_outline_rect(image, 40, 228, 760, 330, 2);
      draw_text_line(image, 58, 244, "RESULT", 1, 12);
      draw_text_line(image, 58, 280, "NO RESULT YET.", 2, 40);
      draw_text_wrapped(image, 40, 350, 720, status, 1, 2);

      const bool focused = voice_focus == 0;
      const int btn_x0 = 220;
      const int btn_x1 = 580;
      const int btn_y0 = 398;
      const int btn_y1 = 438;
      if (focused) {
        fill_black_rect(image, btn_x0, btn_y0, btn_x1, btn_y1);
        draw_outline_rect(image, btn_x0 - 3, btn_y0 - 3, btn_x1 + 3, btn_y1 + 3, 3);
        draw_text_centered_inverted(image, btn_x0 + 8, btn_x1 - 8, btn_y0 + 12, "SKIP", 1, 16);
      } else {
        draw_outline_rect(image, btn_x0, btn_y0, btn_x1, btn_y1, 2);
        draw_text_centered(image, btn_x0 + 8, btn_x1 - 8, btn_y0 + 12, "SKIP", 1, 16);
      }
      return image;
    }

    draw_text_line(image, 40, 60, "SETUP COMPLETE", 3, 24);
    draw_text_line(image, 40, 102, "YOUR BOARD IS READY.", 1, 28);
    draw_text_line(image, 62, 156, language_line.empty() ? "LANGUAGE: ENGLISH" : language_line, 1, 40);
    if (!timezone_line.empty()) {
      draw_text_line(image, 62, 184, timezone_line, 1, 40);
    }
    if (!autosync_line.empty()) {
      draw_text_line(image, 62, 212, autosync_line, 1, 40);
    }
    if (!wifi_line.empty()) {
      draw_text_line(image, 62, 240, wifi_line, 1, 40);
    }
    fill_black_rect(image, 240, 380, 560, 438);
    draw_outline_rect(image, 237, 377, 563, 441, 3);
    draw_text_centered_inverted(image, 252, 548, 400, "ENTER HOME", 2, 24);
    return image;
  }

  static std::vector<uint8_t> render_home_bitmap(const ScreenFrame& frame) {
    std::vector<uint8_t> image(kPanelBufferSize, 0x00);  // white
    draw_outline_rect(image, 12, 12, kPanelWidth - 12, kPanelHeight - 12, 3);
    draw_text_line(image, 40, 30, "HOME KITCHEN", 3, 28);

    std::string location = body_line_with_prefix(frame.body_lines, "Location:");
    std::string battery = body_line_with_prefix(frame.body_lines, "Battery:");
    std::string reminders = body_line_with_prefix(frame.body_lines, "Reminders:");
    std::string focus = body_line_with_prefix(frame.body_lines, "Focus slot:");

    draw_outline_rect(image, 40, 94, 386, 362, 2);
    draw_text_line(image, 56, 114, "LEFT PANEL", 2, 18);
    draw_outline_rect(image, 56, 148, 370, 216, 2);
    draw_text_wrapped(image, 68, 166, 290, location, 2, 2);
    draw_outline_rect(image, 56, 228, 370, 296, 2);
    draw_text_wrapped(image, 68, 246, 290, battery, 2, 2);

    draw_outline_rect(image, 414, 94, kPanelWidth - 40, 362, 2);
    draw_text_line(image, 430, 114, "TASK PANEL", 2, 18);
    draw_outline_rect(image, 430, 148, kPanelWidth - 56, 216, 2);
    draw_text_wrapped(image, 442, 166, 290, reminders, 2, 2);
    draw_outline_rect(image, 430, 228, kPanelWidth - 56, 296, 2);
    draw_text_wrapped(image, 442, 246, 290, focus, 2, 2);

    draw_outline_rect(image, 40, 388, kPanelWidth - 40, 446, 3);
    std::string foot = frame.footer.empty() ? "STATE DRIVEN HOME" : frame.footer;
    draw_text_centered(image, 56, kPanelWidth - 56, 409, trunc_text(foot, 52), 2, 52);
    return image;
  }

  static std::vector<uint8_t> render_generic_bitmap(const ScreenFrame& frame) {
    std::vector<uint8_t> image(kPanelBufferSize, 0x00);  // white
    draw_outline_rect(image, kMargin, kMargin, kPanelWidth - kMargin, kPanelHeight - kMargin, 3);

    const int x = kMargin + kTextInsetX;
    const int content_width = kPanelWidth - (2 * (kMargin + kTextInsetX));

    const int title_max_chars = content_width / (6 * kTitleScale);
    const int subtitle_max_chars = content_width / (6 * kSubtitleScale);
    const int body_max_chars = content_width / (6 * kBodyScale);
    const int footer_max_chars = content_width / (6 * kFooterScale);

    int y = kMargin + 14;
    draw_text_line(image, x, y, frame.title, kTitleScale, title_max_chars);
    y += (8 * kTitleScale);
    draw_text_line(image, x, y, frame.subtitle, kSubtitleScale, subtitle_max_chars);
    y += (8 * kSubtitleScale) + 10;
    fill_black_rect(image, x, y, x + content_width, y + 2);
    y += 12;

    const int body_line_height = (8 * kBodyScale) + 6;
    const int footer_y = kPanelHeight - kMargin - 14 - (7 * kFooterScale);
    const int body_bottom_limit = footer_y - 12;
    for (const auto& raw_line : frame.body_lines) {
      const auto wrapped = wrap_words(raw_line, body_max_chars > 0 ? static_cast<size_t>(body_max_chars) : 1U);
      for (const auto& line : wrapped) {
        if (y + (7 * kBodyScale) > body_bottom_limit) {
          break;
        }
        draw_text_line(image, x, y, line, kBodyScale, body_max_chars);
        y += body_line_height;
      }
      if (y + (7 * kBodyScale) > body_bottom_limit) {
        break;
      }
    }
    fill_black_rect(image, x, footer_y - 8, x + content_width, footer_y - 6);
    draw_text_line(image, x, footer_y, frame.footer, kFooterScale, footer_max_chars);
    return image;
  }

  static std::vector<uint8_t> render_frame_bitmap(const ScreenFrame& frame) {
    if (frame.subtitle == "Landing") {
      if (kUseEmbeddedLandingReference) {
        auto image = load_embedded_landing_reference();
        if (!image.empty()) {
          ESP_LOGI(kTag, "Using embedded landing reference asset for verification");
          return image;
        }
      }
      return render_landing_bitmap(frame);
    }
    if (frame.subtitle == "Onboarding") {
      return render_onboarding_bitmap(frame);
    }
    if (frame.title == "Home") {
      return render_home_bitmap(frame);
    }
    return render_generic_bitmap(frame);
  }

  static std::string frame_signature(const ScreenFrame& frame) {
    std::string out;
    out.reserve(256);
    out.append(frame.title);
    out.push_back('|');
    out.append(frame.subtitle);
    out.push_back('|');
    for (const auto& line : frame.body_lines) {
      out.append(line);
      out.push_back('|');
    }
    out.append(frame.footer);
    return out;
  }

  BoardConfig board_{};
  bool hardware_ready_{false};
  bool power_enabled_{false};
  bool panel_awake_{false};
  bool spi_ready_{false};
  bool first_present_done_{false};
  bool previous_frame_valid_{false};
  std::string last_signature_{};
  std::vector<uint8_t> previous_frame_{};
  spi_device_handle_t spi_handle_{nullptr};
};

}  // namespace

std::unique_ptr<Display> make_default_display() {
  return std::make_unique<EpaperDisplay>();
}

}  // namespace fridge_ink::platform
