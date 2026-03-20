// I2S MEMS Microphone (NR0562) test for SANXIXING ESP32-S3
//
// Wiring:
//   VDD → 3V3
//   GND → GND
//   SCK → GPIO 5  (I2S BCLK)
//   WS  → GPIO 6  (I2S LRCLK)
//   SD  → GPIO 7  (I2S Data)
//   L/R → GND     (left channel, hardwired)
//
// Output: Serial Monitor @ 115200 baud
//   - Peak amplitude every 100 ms
//   - VU bar graph (visual level meter)
//   - Prints "LOUD" when level exceeds threshold

#include <Arduino.h>
#include <driver/i2s.h>

// ── Pin config ────────────────────────────────────────────────────────────────
#define PIN_SCK   5
#define PIN_WS    6
#define PIN_SD    7

// ── I2S config ────────────────────────────────────────────────────────────────
#define I2S_PORT        I2S_NUM_0
#define SAMPLE_RATE     16000       // 16 kHz
#define SAMPLE_BITS     32          // NR0562 outputs 24-bit in a 32-bit frame
#define READ_BUF_SAMPLES 256        // samples per read

// Loud threshold (tune to your environment, 0–2^23)
#define LOUD_THRESHOLD  50000

// ── Buffers ──────────────────────────────────────────────────────────────────
static int32_t samples[READ_BUF_SAMPLES];

// ── Helpers ──────────────────────────────────────────────────────────────────
static void i2s_init() {
  i2s_config_t cfg = {
    .mode                 = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX),
    .sample_rate          = SAMPLE_RATE,
    .bits_per_sample      = (i2s_bits_per_sample_t)SAMPLE_BITS,
    .channel_format       = I2S_CHANNEL_FMT_ONLY_LEFT,   // L/R tied to GND
    .communication_format = I2S_COMM_FORMAT_STAND_I2S,
    .intr_alloc_flags     = ESP_INTR_FLAG_LEVEL1,
    .dma_buf_count        = 4,
    .dma_buf_len          = READ_BUF_SAMPLES,
    .use_apll             = false,
    .tx_desc_auto_clear   = false,
    .fixed_mclk           = 0,
  };

  i2s_pin_config_t pins = {
    .mck_io_num   = I2S_PIN_NO_CHANGE,
    .bck_io_num   = PIN_SCK,
    .ws_io_num    = PIN_WS,
    .data_out_num = I2S_PIN_NO_CHANGE,
    .data_in_num  = PIN_SD,
  };

  ESP_ERROR_CHECK(i2s_driver_install(I2S_PORT, &cfg, 0, NULL));
  ESP_ERROR_CHECK(i2s_set_pin(I2S_PORT, &pins));
  ESP_ERROR_CHECK(i2s_zero_dma_buffer(I2S_PORT));
}

// Draw a simple ASCII VU bar (0–20 chars)
static void print_vu(int32_t peak) {
  // NR0562 is 24-bit, max value ≈ 2^23 = 8,388,608
  const int32_t MAX_VAL = 8388608;
  int bars = (int)((float)peak / MAX_VAL * 20.0f);
  if (bars > 20) bars = 20;

  Serial.print("[");
  for (int i = 0; i < 20; i++) Serial.print(i < bars ? "█" : " ");
  Serial.print("] ");
  Serial.printf("%7ld", (long)peak);
  if (peak > LOUD_THRESHOLD) Serial.print("  ← LOUD");
  Serial.println();
}

// ── Setup ─────────────────────────────────────────────────────────────────────
void setup() {
  Serial.begin(115200);
  delay(500);
  Serial.println("=== I2S MEMS Mic test (NR0562) ===");
  Serial.printf("Pins: SCK=%d  WS=%d  SD=%d\n", PIN_SCK, PIN_WS, PIN_SD);
  Serial.printf("Sample rate: %d Hz   Buf: %d samples\n\n",
                SAMPLE_RATE, READ_BUF_SAMPLES);

  i2s_init();
  Serial.println("I2S ready. Listening...\n");
}

// ── Loop ──────────────────────────────────────────────────────────────────────
void loop() {
  size_t bytes_read = 0;
  i2s_read(I2S_PORT, samples, sizeof(samples), &bytes_read, portMAX_DELAY);

  int n = bytes_read / sizeof(int32_t);
  if (n == 0) return;

  // NR0562: data is left-justified in 32-bit word → shift right 8 to get 24-bit
  int32_t peak = 0;
  for (int i = 0; i < n; i++) {
    int32_t s = samples[i] >> 8;   // 24-bit signed value
    if (s < 0) s = -s;             // absolute value
    if (s > peak) peak = s;
  }

  print_vu(peak);
  delay(100);
}
