/* =========================================================================
 * Signals & Systems mini-project -- Audio -> LED visualiser
 * Arduino firmware: serial -> 6 PWM LEDs
 *
 * Needs only parts from a basic kit: 6 LEDs + 6 resistors. No LED strip,
 * no external power supply -- USB alone drives this.
 *
 * The Arduino does NO signal processing.  A 2048-point float FFT needs
 * ~16 kB of working RAM; an ATmega328P has 2 kB.  All DSP runs on the host
 * in Python and this sketch just sets six brightness levels.
 *
 * PROTOCOL  (see snsled/runtime.py PwmSink)
 *   host -> Arduino : 0xAA 0x55 <n> <n bytes> xor          (10 bytes for n=6)
 *
 * NO HANDSHAKE IS NEEDED HERE.  This is the key difference from the WS2812B
 * version: analogWrite() writes a timer compare register and never disables
 * interrupts, so there is no blackout window in which incoming bytes could
 * be lost.  At 115200 baud a 10-byte frame at 86.13 fps needs 8.6 kbps --
 * roughly 13x headroom against the link, and the 64-byte UART buffer holds
 * six whole frames.
 *
 * PWM FACTS (16 MHz ATmega328P, default Arduino prescalers)
 *   pins 5, 6     Timer0, fast PWM,      256 counts -> 976.56 Hz
 *   pins 9, 10    Timer1, phase-correct, 510 counts -> 490.20 Hz
 *   pins 3, 11    Timer2, phase-correct, 510 counts -> 490.20 Hz
 *   Slowest is 490 Hz, about 5.4x the ~90 Hz flicker-fusion threshold, so
 *   nothing visibly flickers.  Worst-case update lag is one period, 2.04 ms.
 *
 * WIRING  (x6, one per channel)
 *   pin ---[220 ohm]---|>|--- GND          (LED anode to resistor, cathode to GND)
 *
 *   220 ohm gives 14.5 mA for a red LED (Vf 1.8 V) and 9.1 mA for a blue
 *   (Vf 3.0 V) -- both under the 20 mA per-pin recommendation.  Six red LEDs
 *   at full brightness draw 87 mA against the 200 mA total chip limit.
 *   330 ohm also works and is dimmer but cooler; 150 ohm is the practical
 *   floor (21 mA on red, just over the recommendation).
 *
 * BAND -> PIN MAP (6-band mel bank, 20 Hz - 16 kHz)
 *   D3   band 0     20 - 1068 Hz   sub-bass / kick
 *   D5   band 1    428 - 2070 Hz   bass / low vocal
 *   D6   band 2   1068 - 3641 Hz   low mid
 *   D9   band 3   2070 - 6102 Hz   presence
 *   D10  band 4   3641 - 9958 Hz   brilliance
 *   D11  band 5   6102 - 16000 Hz  air / cymbals
 * ========================================================================= */

#include <avr/pgmspace.h>

#define N_CH           6
#define BAUD           115200UL
#define FRAME_TIMEOUT  1500        // ms with no valid frame -> all LEDs off

#define MAGIC_A 0xAA
#define MAGIC_B 0x55

const uint8_t PINS[N_CH] = {3, 5, 6, 9, 10, 11};

uint8_t  buf[N_CH];
uint32_t lastFrameMs = 0;

/* The host already applies gamma, so this table is identity by default and
 * is kept only so you can experiment on the device side without touching
 * the host.  Living in PROGMEM it costs 256 B of flash and 0 B of RAM. */
const uint8_t GAMMA[256] PROGMEM = {
    0,  1,  2,  3,  4,  5,  6,  7,  8,  9, 10, 11, 12, 13, 14, 15,
   16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31,
   32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47,
   48, 49, 50, 51, 52, 53, 54, 55, 56, 57, 58, 59, 60, 61, 62, 63,
   64, 65, 66, 67, 68, 69, 70, 71, 72, 73, 74, 75, 76, 77, 78, 79,
   80, 81, 82, 83, 84, 85, 86, 87, 88, 89, 90, 91, 92, 93, 94, 95,
   96, 97, 98, 99,100,101,102,103,104,105,106,107,108,109,110,111,
  112,113,114,115,116,117,118,119,120,121,122,123,124,125,126,127,
  128,129,130,131,132,133,134,135,136,137,138,139,140,141,142,143,
  144,145,146,147,148,149,150,151,152,153,154,155,156,157,158,159,
  160,161,162,163,164,165,166,167,168,169,170,171,172,173,174,175,
  176,177,178,179,180,181,182,183,184,185,186,187,188,189,190,191,
  192,193,194,195,196,197,198,199,200,201,202,203,204,205,206,207,
  208,209,210,211,212,213,214,215,216,217,218,219,220,221,222,223,
  224,225,226,227,228,229,230,231,232,233,234,235,236,237,238,239,
  240,241,242,243,244,245,246,247,248,249,250,251,252,253,254,255
};

static int readByteTimeout(uint16_t ms) {
  uint32_t t0 = millis();
  while ((uint32_t)(millis() - t0) < ms) {
    if (Serial.available()) return Serial.read();
  }
  return -1;
}

static void writeAll(const uint8_t *v) {
  for (uint8_t i = 0; i < N_CH; i++) {
    analogWrite(PINS[i], pgm_read_byte(&GAMMA[v[i]]));
  }
}

static void allOff() {
  uint8_t z[N_CH];
  for (uint8_t i = 0; i < N_CH; i++) z[i] = 0;
  writeAll(z);
}

void setup() {
  Serial.begin(BAUD);
  for (uint8_t i = 0; i < N_CH; i++) pinMode(PINS[i], OUTPUT);

  // startup sweep: confirms wiring and channel order at a glance.
  // If these do not light 0..5 left to right, your pin order is wrong.
  for (uint8_t i = 0; i < N_CH; i++) {
    analogWrite(PINS[i], 120); delay(110); analogWrite(PINS[i], 0);
  }
  allOff();
  lastFrameMs = millis();
}

void loop() {
  /* ---- resynchronise on the magic word ------------------------------- */
  int b = readByteTimeout(200);
  if (b < 0) {                                   // host is quiet
    if ((uint32_t)(millis() - lastFrameMs) > FRAME_TIMEOUT) {
      allOff();                                  // failsafe: never freeze lit
      lastFrameMs = millis();
    }
    return;
  }
  if (b != MAGIC_A) return;                      // not a header, keep scanning
  if (readByteTimeout(20) != MAGIC_B) return;

  /* ---- length -------------------------------------------------------- */
  int n = readByteTimeout(20);
  if (n < 1 || n > N_CH) return;

  /* ---- payload ------------------------------------------------------- */
  uint8_t got = 0;
  uint32_t t0 = millis();
  while (got < (uint8_t)n && (uint32_t)(millis() - t0) < 30) {
    if (Serial.available()) buf[got++] = (uint8_t)Serial.read();
  }
  if (got != (uint8_t)n) return;

  /* ---- checksum ------------------------------------------------------ */
  int chk = readByteTimeout(20);
  if (chk < 0) return;
  uint8_t x = 0;
  for (uint8_t i = 0; i < (uint8_t)n; i++) x ^= buf[i];
  if ((uint8_t)chk != x) return;                 // corrupt: drop this frame

  /* ---- paint --------------------------------------------------------- */
  for (uint8_t i = (uint8_t)n; i < N_CH; i++) buf[i] = 0;
  writeAll(buf);
  lastFrameMs = millis();
}
