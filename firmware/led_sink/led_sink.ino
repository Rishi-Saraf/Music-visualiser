/* =========================================================================
 * Signals & Systems mini-project -- Audio -> LED visualiser
 * Arduino firmware: serial -> WS2812B sink
 *
 * The Arduino does NO signal processing.  It cannot: a 2048-point float FFT
 * needs ~16 kB of RAM and an ATmega328P has 2 kB.  All DSP runs on the host
 * in Python; this sketch just paints frames.
 *
 * PROTOCOL (request/response -- see snsled/runtime.py SerialSink)
 *   Arduino -> host : 0x01                              "READY, send one frame"
 *   host -> Arduino : 0xAA 0x55 lenLo lenHi <len bytes> xor
 *
 * WHY THE HANDSHAKE:
 *   FastLED bit-bangs WS2812B with interrupts DISABLED for the entire strobe
 *   (2.08 ms at 60 LEDs).  At 1 Mbaud that blackout would drop ~208 bytes into
 *   a 64-byte UART buffer -> torn frames and colour corruption.  Transmitting
 *   only after an explicit READY guarantees nothing is ever in flight while
 *   interrupts are off.
 *
 * WHY 1 Mbaud:
 *   On a 16 MHz AVR with U2X=1, UBRR = F_CPU/(8*baud)-1 = 1 exactly, so the
 *   baud error is 0.00%.  115200 gives UBRR 16.36 -> 16, a +2.12% error.
 *   The faster rate is also the more accurate one.
 *
 * WIRING
 *   strip DIN  <- 330 ohm resistor <- Arduino D6
 *   strip 5V   <- external 5 V supply (NOT the Arduino 5V pin)
 *   strip GND  <- supply GND AND Arduino GND (common ground is mandatory)
 *   1000 uF capacitor across the strip's 5V/GND, close to the first pixel
 *
 * Arduino outputs 5 V logic, and WS2812B needs Vih >= 0.7*VDD = 3.5 V,
 * so NO level shifter is required.  (A 3.3 V board usually needs one.)
 * ========================================================================= */

#include <FastLED.h>

#define LED_PIN        6
#define NUM_LEDS       60          // must match Config.n_leds on the host
#define MAX_BYTES      (NUM_LEDS * 3)
#define BAUD           1000000UL
#define BRIGHTNESS     255         // host already caps power; keep 255 here
#define FRAME_TIMEOUT  1500        // ms with no valid frame -> blank the strip

#define MAGIC_A 0xAA
#define MAGIC_B 0x55
#define READY   0x01

CRGB leds[NUM_LEDS];
uint8_t  buf[MAX_BYTES];
uint32_t lastFrameMs = 0;

/* Blocking read of one byte with a millisecond timeout. -1 on timeout. */
static int readByteTimeout(uint16_t ms) {
  uint32_t t0 = millis();
  while ((uint32_t)(millis() - t0) < ms) {
    if (Serial.available()) return Serial.read();
  }
  return -1;
}

void setup() {
  Serial.begin(BAUD);
  FastLED.addLeds<WS2812B, LED_PIN, GRB>(leds, NUM_LEDS);
  FastLED.setBrightness(BRIGHTNESS);
  FastLED.setDither(0);            // dithering needs a fast frame rate we
                                   // are not guaranteed; it causes flicker
  fill_solid(leds, NUM_LEDS, CRGB::Black);
  FastLED.show();

  // brief startup sweep so you can see the strip is alive and correctly wired
  for (int i = 0; i < NUM_LEDS; i++) {
    leds[i] = CHSV((uint8_t)(i * 255 / NUM_LEDS), 255, 60);
    FastLED.show();
    delay(6);
  }
  fill_solid(leds, NUM_LEDS, CRGB::Black);
  FastLED.show();

  lastFrameMs = millis();
  Serial.write(READY);             // invite the first frame
}

void loop() {
  /* ---- resynchronise on the magic word ------------------------------- */
  int b = readByteTimeout(200);
  if (b < 0) {                                   // host is quiet
    if ((uint32_t)(millis() - lastFrameMs) > FRAME_TIMEOUT) {
      fill_solid(leds, NUM_LEDS, CRGB::Black);   // failsafe: do not freeze lit
      FastLED.show();
      lastFrameMs = millis();
    }
    Serial.write(READY);                         // re-invite
    return;
  }
  if (b != MAGIC_A) return;                      // not a header, keep scanning
  if (readByteTimeout(50) != MAGIC_B) return;

  /* ---- length -------------------------------------------------------- */
  int lo = readByteTimeout(50); if (lo < 0) return;
  int hi = readByteTimeout(50); if (hi < 0) return;
  uint16_t n = (uint16_t)lo | ((uint16_t)hi << 8);
  if (n == 0 || n > MAX_BYTES) { Serial.write(READY); return; }

  /* ---- payload ------------------------------------------------------- */
  uint16_t got = 0;
  uint32_t t0  = millis();
  while (got < n && (uint32_t)(millis() - t0) < 100) {
    int avail = Serial.available();
    while (avail-- > 0 && got < n) buf[got++] = (uint8_t)Serial.read();
  }
  if (got != n) { Serial.write(READY); return; }

  /* ---- checksum ------------------------------------------------------ */
  int chk = readByteTimeout(50); if (chk < 0) { Serial.write(READY); return; }
  uint8_t x = 0;
  for (uint16_t i = 0; i < n; i++) x ^= buf[i];
  if ((uint8_t)chk != x) { Serial.write(READY); return; }   // drop, ask again

  /* ---- paint --------------------------------------------------------- */
  uint16_t px = n / 3;
  for (uint16_t i = 0; i < px; i++) {
    leds[i] = CRGB(buf[i*3], buf[i*3+1], buf[i*3+2]);
  }
  for (uint16_t i = px; i < NUM_LEDS; i++) leds[i] = CRGB::Black;

  FastLED.show();            // interrupts are off for ~2.08 ms here --
                             // safe, because the host is waiting for READY
  lastFrameMs = millis();
  Serial.write(READY);
}
