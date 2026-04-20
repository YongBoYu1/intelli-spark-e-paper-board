// I2S MEMS Microphone (NR0562) diagnostic test for SANXIXING ESP32-S3
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
//   - Wiring self-check on startup (all-zero detection)
//   - Peak + RMS amplitude every 100 ms
//   - Noise floor estimation (first 2 s of silence)
//   - ASCII VU bar graph
//   - Prints "LOUD" / "SIGNAL" / "SILENCE" / "⚠ NO SIGNAL (check wiring)"

#include <Arduino.h>
#include <driver/i2s.h>
#include <math.h>

// ── Pin config ────────────────────────────────────────────────────────────────
#define PIN_SCK   5
#define PIN_WS    6
#define PIN_SD    7

// ── I2S config ────────────────────────────────────────────────────────────────
#define I2S_PORT          I2S_NUM_0
#define SAMPLE_RATE       16000        // 16 kHz
#define SAMPLE_BITS       32           // NR0562 outputs 24-bit in a 32-bit frame
#define READ_BUF_SAMPLES  256          // samples per i2s_read()
#define REPORT_INTERVAL_MS 100

// ── Thresholds (0 – 2^23 ≈ 8,388,608) ───────────────────────────────────────
#define LOUD_THRESHOLD    200000       // clearly audible speech / loud sound
#define SIGNAL_THRESHOLD  3000         // above noise floor → "SIGNAL"
// All-zero frames in a row before declaring wiring fault
#define ZERO_FAULT_FRAMES 10

// ── Noise-floor calibration ───────────────────────────────────────────────────
#define CALIBRATION_FRAMES 20          // ~2 s of silence used for noise floor

// ── Buffers ──────────────────────────────────────────────────────────────────
static int32_t  g_samples[READ_BUF_SAMPLES];
static int32_t  g_noise_floor    = 0;
static bool     g_calibrated     = false;
static int      g_calib_count    = 0;
static int64_t  g_calib_rms_sum  = 0;
static int      g_zero_frames    = 0;

// ── I2S init ─────────────────────────────────────────────────────────────────
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

// ── ASCII VU bar (0–24 chars) ─────────────────────────────────────────────────
static void print_vu(int32_t peak, int32_t rms) {
  const int32_t MAX_VAL = 8388608;   // 2^23
  int bars = (int)((float)peak / MAX_VAL * 24.0f);
  if (bars > 24) bars = 24;

  Serial.print("[");
  for (int i = 0; i < 24; i++) Serial.print(i < bars ? '#' : ' ');
  Serial.print("] ");
  Serial.printf("peak=%7ld  rms=%6ld", (long)peak, (long)rms);
}

// ── Compute peak + RMS from one DMA frame ────────────────────────────────────
static void compute_frame(int n, int32_t* out_peak, int32_t* out_rms) {
  int32_t  peak  = 0;
  int64_t  sq_sum = 0;

  for (int i = 0; i < n; i++) {
    // NR0562: left-justified 24-bit in 32-bit word → shift right 8
    int32_t s = g_samples[i] >> 8;
    int32_t a = s < 0 ? -s : s;
    if (a > peak) peak = a;
    sq_sum += (int64_t)s * s;
  }

  *out_peak = peak;
  *out_rms  = (int32_t)sqrtf((float)(sq_sum / n));
}

// ── Wiring self-check: flush DMA and read several frames ─────────────────────
static void wiring_check() {
  Serial.println("\n--- Wiring self-check (5 frames) ---");
  int zero_count = 0;
  for (int f = 0; f < 5; f++) {
    size_t bytes = 0;
    i2s_read(I2S_PORT, g_samples, sizeof(g_samples), &bytes, portMAX_DELAY);
    int n = bytes / sizeof(int32_t);

    bool all_zero = true;
    int32_t peak, rms;
    compute_frame(n, &peak, &rms);
    for (int i = 0; i < n; i++) {
      if (g_samples[i] != 0) { all_zero = false; break; }
    }

    Serial.printf("  frame %d: peak=%ld  rms=%ld  %s\n",
                  f, (long)peak, (long)rms,
                  all_zero ? "ALL ZEROS ← possible wiring issue" : "OK");
    if (all_zero) zero_count++;
  }

  if (zero_count == 5) {
    Serial.println("\n  *** ALL 5 FRAMES ZERO ***");
    Serial.println("  Check: SCK→GPIO5, WS→GPIO6, SD→GPIO7, VDD→3V3, GND→GND, L/R→GND");
  } else {
    Serial.println("  Wiring looks OK — signal present.");
  }
  Serial.println("-------------------------------------\n");
}

// ── Noise-floor calibration (silent environment) ─────────────────────────────
static void calibrate_noise(int32_t rms) {
  if (g_calibrated) return;
  g_calib_rms_sum += rms;
  g_calib_count++;
  if (g_calib_count == 1) {
    Serial.println("[Calibrating noise floor — please stay quiet...]");
  }
  if (g_calib_count >= CALIBRATION_FRAMES) {
    g_noise_floor = (int32_t)(g_calib_rms_sum / CALIBRATION_FRAMES);
    g_calibrated  = true;
    Serial.printf("[Calibration done. Noise floor RMS ≈ %ld]\n\n", (long)g_noise_floor);
  }
}

// ── Setup ─────────────────────────────────────────────────────────────────────
void setup() {
  Serial.begin(115200);
  delay(600);
  Serial.println("========================================");
  Serial.println("  I2S MEMS Mic diagnostic (NR0562)");
  Serial.println("========================================");
  Serial.printf("Pins: SCK=%d  WS=%d  SD=%d\n", PIN_SCK, PIN_WS, PIN_SD);
  Serial.printf("Sample rate: %d Hz   Buf: %d samples   Loud threshold: %d\n\n",
                SAMPLE_RATE, READ_BUF_SAMPLES, LOUD_THRESHOLD);

  i2s_init();
  Serial.println("I2S driver installed.");

  // Discard first 3 DMA buffers (hardware settling)
  for (int i = 0; i < 3; i++) {
    size_t b = 0;
    i2s_read(I2S_PORT, g_samples, sizeof(g_samples), &b, portMAX_DELAY);
  }

  wiring_check();
  Serial.println("Listening... (speak into mic)\n");
}

// ── Loop ──────────────────────────────────────────────────────────────────────
void loop() {
  size_t bytes_read = 0;
  i2s_read(I2S_PORT, g_samples, sizeof(g_samples), &bytes_read, portMAX_DELAY);

  int n = bytes_read / sizeof(int32_t);
  if (n == 0) return;

  int32_t peak, rms;
  compute_frame(n, &peak, &rms);

  // All-zero fault detection during normal operation
  bool all_zero = (peak == 0 && rms == 0);
  if (all_zero) {
    g_zero_frames++;
    if (g_zero_frames == ZERO_FAULT_FRAMES) {
      Serial.println("⚠  WARNING: " + String(ZERO_FAULT_FRAMES) +
                     " consecutive all-zero frames — check wiring!");
    }
  } else {
    g_zero_frames = 0;
  }

  // Noise-floor calibration
  calibrate_noise(rms);

  // VU + status
  print_vu(peak, rms);

  if (all_zero) {
    Serial.print("  ⚠ NO SIGNAL");
  } else if (peak > LOUD_THRESHOLD) {
    Serial.print("  ← LOUD");
  } else if (g_calibrated && rms > g_noise_floor * 3) {
    Serial.print("  ← SIGNAL");
  } else {
    Serial.print("  (silence)");
  }

  // Show noise floor margin when calibrated
  if (g_calibrated && !all_zero) {
    Serial.printf("  [floor=%ld]", (long)g_noise_floor);
  }

  Serial.println();
  delay(REPORT_INTERVAL_MS);
}
