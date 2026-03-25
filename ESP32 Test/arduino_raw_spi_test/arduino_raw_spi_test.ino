// Bit-bang SPI diagnostic — bypasses ESP32 SPI peripheral entirely.
// Wiring: VCC←3V3, 5V←5V, GND←GND,
//         DIN←GPIO11, CLK←GPIO12, CS←GPIO47,
//         DC←GPIO21, RST←GPIO4, BUSY←GPIO14, PWR←GPIO8

#include <Arduino.h>

#define PIN_SCLK  12
#define PIN_MOSI  11
#define PIN_CS    47
#define PIN_DC    21
#define PIN_RST    4
#define PIN_BUSY  14
#define PIN_PWR    8

#define EPD_W  800u
#define EPD_H  480u

// ── Bit-bang SPI (Mode 0: CPOL=0, CPHA=0, MSB first) ────────────────────────
static void bb_byte(uint8_t b) {
  for (int i = 7; i >= 0; i--) {
    digitalWrite(PIN_SCLK, LOW);
    digitalWrite(PIN_MOSI, (b >> i) & 1);
    delayMicroseconds(2);
    digitalWrite(PIN_SCLK, HIGH);
    delayMicroseconds(2);
  }
  digitalWrite(PIN_SCLK, LOW);  // CLK idle LOW
}

static void bb_cmd(uint8_t c) {
  digitalWrite(PIN_DC, LOW);
  digitalWrite(PIN_CS, LOW);
  bb_byte(c);
  digitalWrite(PIN_CS, HIGH);
}

static void bb_data(uint8_t d) {
  digitalWrite(PIN_DC, HIGH);
  digitalWrite(PIN_CS, LOW);
  bb_byte(d);
  digitalWrite(PIN_CS, HIGH);
}

static void bb_buf(uint8_t fill, uint32_t len) {
  digitalWrite(PIN_DC, HIGH);
  digitalWrite(PIN_CS, LOW);
  for (uint32_t i = 0; i < len; i++) bb_byte(fill);
  digitalWrite(PIN_CS, HIGH);
}

// ── BUSY helpers ──────────────────────────────────────────────────────────────
// For UC8176 (7.5" V2): BUSY=1 = idle/ready, BUSY=0 = busy/processing
static void wait_idle(const char* label, uint32_t timeout_ms) {
  uint32_t t0 = millis();
  while (digitalRead(PIN_BUSY) == LOW) {   // wait while BUSY=0 (processing)
    delay(100);
    Serial.printf("  [%s] waiting... %lu ms  BUSY=%d\n", label, millis()-t0, digitalRead(PIN_BUSY));
    if (millis() - t0 > timeout_ms) {
      Serial.printf("  [%s] TIMEOUT after %lu ms\n", label, millis()-t0);
      return;
    }
  }
  Serial.printf("  [%s] done after %lu ms  BUSY=%d\n", label, millis()-t0, digitalRead(PIN_BUSY));
}

// ── Setup ────────────────────────────────────────────────────────────────────
void setup() {
  Serial.begin(115200);
  delay(500);
  Serial.println("=== BIT-BANG SPI 7.5\" V2 all-black test ===");

  // ── GPIO self-test (floating state, drive HIGH, drive LOW) ──────────────
  Serial.println("--- GPIO self-test ---");
  const int spi_pins[] = {PIN_MOSI, PIN_SCLK, PIN_CS, PIN_DC};
  const char* spi_names[] = {"MOSI(11)", "SCLK(12)", "CS(47)", "DC(21)"};
  for (int i = 0; i < 4; i++) {
    int pin = spi_pins[i];
    pinMode(pin, INPUT_PULLDOWN); delay(2);
    int pd = digitalRead(pin);
    pinMode(pin, INPUT_PULLUP);   delay(2);
    int pu = digitalRead(pin);
    // Drive HIGH, verify (read the output register)
    pinMode(pin, OUTPUT); digitalWrite(pin, HIGH); delay(2);
    int hi = digitalRead(pin);
    // Drive LOW, verify
    digitalWrite(pin, LOW); delay(2);
    int lo = digitalRead(pin);
    Serial.printf("  %s: pulldown=%d pullup=%d driveHI=%d driveLO=%d%s\n",
      spi_names[i], pd, pu, hi, lo,
      (hi==1 && lo==0) ? " OK" : " *** FAIL ***");
    digitalWrite(pin, (pin == PIN_CS) ? HIGH : LOW); // restore idle state
  }
  Serial.println("--- end self-test ---");

  // All pins as OUTPUT, no SPI.begin()
  pinMode(PIN_PWR,   OUTPUT); digitalWrite(PIN_PWR,   HIGH);  // enable HAT boost converter
  pinMode(PIN_MOSI,  OUTPUT); digitalWrite(PIN_MOSI,  LOW);
  pinMode(PIN_SCLK,  OUTPUT); digitalWrite(PIN_SCLK,  LOW);
  pinMode(PIN_CS,    OUTPUT); digitalWrite(PIN_CS,    HIGH);
  pinMode(PIN_DC,    OUTPUT); digitalWrite(PIN_DC,    LOW);
  pinMode(PIN_RST,   OUTPUT); digitalWrite(PIN_RST,   HIGH);
  pinMode(PIN_BUSY,  INPUT);
  delay(50);  // allow boost converter to stabilise

  // ── Reset ──────────────────────────────────────────────────────────────
  Serial.printf("BUSY before RST = %d\n", digitalRead(PIN_BUSY));
  digitalWrite(PIN_RST, HIGH); delay(200);
  digitalWrite(PIN_RST, LOW);  delayMicroseconds(2000);
  digitalWrite(PIN_RST, HIGH); delay(200);
  Serial.printf("BUSY after  RST = %d (expect 1=idle)\n", digitalRead(PIN_BUSY));
  // After RST, panel is ready when BUSY=1 (HIGH). Already there — no wait needed.

  // ── Init ───────────────────────────────────────────────────────────────
  Serial.println("Init commands (bit-bang)...");

  bb_cmd(0x01);
  bb_data(0x07); bb_data(0x07); bb_data(0x3f); bb_data(0x3f);
  delay(10);
  // Note: 0x06 (Booster Soft Start) intentionally omitted — not in Waveshare 7.5" V2 driver

  Serial.println("Power ON (0x04) — waiting up to 10 s for BUSY=1...");
  bb_cmd(0x04);
  wait_idle("0x04", 10000);

  bb_cmd(0x00); bb_data(0x1f);   delay(10);
  bb_cmd(0x61);
  bb_data(0x03); bb_data(0x20); bb_data(0x01); bb_data(0xe0);
  delay(10);
  bb_cmd(0x15); bb_data(0x00);   delay(10);
  bb_cmd(0x50); bb_data(0x10); bb_data(0x07); delay(10);
  bb_cmd(0x60); bb_data(0x22);   delay(10);

  // ── Pixel data ─────────────────────────────────────────────────────────
  // UC8176 pixel encoding: bit=1 → black, bit=0 → white
  Serial.println("DTM1 (0x00 = white, old frame)...");
  bb_cmd(0x10); bb_buf(0x00, EPD_W * EPD_H / 8);
  Serial.println("  done.");

  Serial.println("DTM2 (0xFF = black, new frame)...");
  bb_cmd(0x13); bb_buf(0xFF, EPD_W * EPD_H / 8);
  Serial.println("  done.");

  // ── Refresh ────────────────────────────────────────────────────────────
  Serial.println("Refresh (0x12) — waiting up to 25 s for BUSY=1...");
  bb_cmd(0x12);
  wait_idle("0x12", 25000);

  bb_cmd(0x02);
  delay(300);
  digitalWrite(PIN_PWR, LOW);   // disable HAT boost converter
  Serial.println("=== Done ===");
}

void loop() {}
