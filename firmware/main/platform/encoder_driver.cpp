#include "platform/encoder_driver.hpp"

#include "platform/clock.hpp"

#include "driver/gpio.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"

namespace fridge_ink::platform {
namespace {

constexpr const char* kTag = "encoder";

// KEY: < 800 ms → Click, ≥ 800 ms → VoiceTrigger (push-to-talk).
constexpr uint64_t kLongPressMs = 800;

// Rotation debounce: ignore S1 edges for this many ms after an accepted event.
// Mechanical contacts bounce 5–20 ms; 50 ms is a comfortable margin.
// Stored as uint32_t for atomic reads/writes on 32-bit Xtensa from ISR.
constexpr uint32_t kRotateDebounceMs = 50;

// Queue depth: small — main loop coalesces rotation events.
constexpr int kQueueDepth = 4;

// ── Module-level state ────────────────────────────────────────────────────────
static EncoderPins   s_pins{};
static QueueHandle_t s_queue{nullptr};

// Written and read from the ISR.  32-bit on Xtensa is atomically read/written.
static volatile uint32_t s_last_rotate_ms{0};

// ── S1 falling-edge ISR ───────────────────────────────────────────────────────
// Runs in interrupt context (IRAM_ATTR required).
// Reads S2 to determine direction and enqueues a rotation event.
// A 50 ms debounce window suppresses contact bounce.
static void IRAM_ATTR s1_isr_handler(void* /*arg*/) {
  const uint32_t now_ms =
      static_cast<uint32_t>(esp_timer_get_time() / 1000ULL);  // safe from ISR

  if ((now_ms - s_last_rotate_ms) < kRotateDebounceMs) {
    return;  // still within debounce window — discard
  }
  s_last_rotate_ms = now_ms;

  // Sample S2 immediately: HIGH → CW, LOW → CCW.
  const int s2 = gpio_get_level(static_cast<gpio_num_t>(s_pins.s2));
  const EncoderEvent ev =
      (s2 == 1) ? EncoderEvent::RotateCW : EncoderEvent::RotateCCW;

  BaseType_t woken = pdFALSE;
  xQueueSendFromISR(s_queue, &ev, &woken);
  if (woken) portYIELD_FROM_ISR();
}

}  // namespace

// ── Public API ────────────────────────────────────────────────────────────────

bool encoder_init(const EncoderPins& pins) {
  if (pins.s1 < 0 || pins.s2 < 0 || pins.key < 0) {
    ESP_LOGW(kTag, "Encoder pins not configured — skipping init");
    return false;
  }

  s_pins  = pins;
  s_queue = xQueueCreate(kQueueDepth, sizeof(EncoderEvent));
  if (!s_queue) {
    ESP_LOGE(kTag, "xQueueCreate failed");
    return false;
  }

  // ── S2 and KEY: plain inputs with pull-up, no interrupt ──────────────────
  {
    gpio_config_t io{};
    io.pin_bit_mask  = (1ULL << pins.s2) | (1ULL << pins.key);
    io.mode          = GPIO_MODE_INPUT;
    io.pull_up_en    = GPIO_PULLUP_ENABLE;
    io.pull_down_en  = GPIO_PULLDOWN_DISABLE;
    io.intr_type     = GPIO_INTR_DISABLE;
    const esp_err_t err = gpio_config(&io);
    if (err != ESP_OK) {
      ESP_LOGE(kTag, "gpio_config (S2/KEY) failed: %s", esp_err_to_name(err));
      return false;
    }
  }

  // ── S1: input with pull-up + falling-edge interrupt ──────────────────────
  {
    gpio_config_t io{};
    io.pin_bit_mask  = (1ULL << pins.s1);
    io.mode          = GPIO_MODE_INPUT;
    io.pull_up_en    = GPIO_PULLUP_ENABLE;
    io.pull_down_en  = GPIO_PULLDOWN_DISABLE;
    io.intr_type     = GPIO_INTR_NEGEDGE;  // trigger on S1 falling edge
    const esp_err_t err = gpio_config(&io);
    if (err != ESP_OK) {
      ESP_LOGE(kTag, "gpio_config (S1) failed: %s", esp_err_to_name(err));
      return false;
    }
  }

  // Install the shared GPIO ISR service (no-op if already installed).
  gpio_install_isr_service(0);

  const esp_err_t isr_err =
      gpio_isr_handler_add(static_cast<gpio_num_t>(pins.s1),
                           s1_isr_handler, nullptr);
  if (isr_err != ESP_OK) {
    ESP_LOGE(kTag, "gpio_isr_handler_add failed: %s", esp_err_to_name(isr_err));
    return false;
  }

  ESP_LOGI(kTag, "Encoder ready (ISR): S1=GPIO%d  S2=GPIO%d  KEY=GPIO%d",
           pins.s1, pins.s2, pins.key);
  return true;
}

// encoder_poll — non-blocking, called from the main loop every ~50 ms.
//
// Rotation events are enqueued by the S1 ISR and dequeued here.
// KEY (button) is polled directly: no extra task, no IDLE starvation.
bool encoder_poll(EncoderEvent* out) {
  if (!out || s_pins.s1 < 0) return false;

  // ── Rotation (from ISR queue) ─────────────────────────────────────────────
  if (xQueueReceive(s_queue, out, 0) == pdTRUE) {
    return true;
  }

  // ── KEY button (polled inline) ────────────────────────────────────────────
  // Static state persists across calls — safe because encoder_poll is always
  // called from the single main-loop task.
  static int      prev_key          = 1;  // pull-up → idle HIGH
  static bool     key_pressed       = false;
  static uint64_t key_press_start   = 0;

  const int key = gpio_get_level(static_cast<gpio_num_t>(s_pins.key));

  if (prev_key == 1 && key == 0) {
    key_press_start = monotonic_ms();
    key_pressed     = true;
  } else if (prev_key == 0 && key == 1 && key_pressed) {
    const uint64_t held_ms = monotonic_ms() - key_press_start;
    *out       = (held_ms >= kLongPressMs)
                     ? EncoderEvent::VoiceTrigger
                     : EncoderEvent::Click;
    key_pressed = false;
    prev_key    = key;
    return true;
  }
  prev_key = key;

  return false;
}

}  // namespace fridge_ink::platform
