/* =========================================================================
 * Signals & Systems mini-project -- Audio -> LED visualiser
 * Arduino firmware: serial -> 20x4 character LCD (+ 6 PWM LEDs)
 *
 * Target: RG2004A / 2004A and any HD44780-compatible 20x4 module.
 *
 * WHAT IT DRAWS
 *   A 20-band, 32-level spectrum analyser.  The LCD is a CHARACTER display,
 *   not graphics, but the HD44780 allows 8 user-defined 5x8 characters.
 *   Defining them as partial vertical bars (1/8 .. 8/8 filled from the
 *   bottom) turns each of the 20 columns into a bar 4 cells x 8 px = 32
 *   levels tall.
 *
 * WHY THE HOST SENDS LEVELS, NOT CHARACTERS
 *   20 level bytes instead of 80 character bytes, and -- more importantly --
 *   the device knows what is currently on screen, so it can redraw only the
 *   cells that changed.  Measured on the test track: 17.6 of 80 cells change
 *   per frame on average (p95 = 37), a 4.5x saving.  That saving is what
 *   makes the LCD keep up with 86 audio frames per second.
 *
 * >>> THE I2C TRAP <<<
 *   If your module has the PCF8574 I2C backpack, the DEFAULT Wire clock of
 *   100 kHz IS TOO SLOW.  Each character costs ~6 PCF8574 byte writes
 *   (2 nibbles x 3 transfers), about 54 bits, so:
 *       100 kHz -> 540 us/char ->  43 fps differential   FAILS (need 86)
 *       400 kHz -> 135 us/char -> 172 fps differential   PASSES
 *   Wire.setClock(400000) below is not an optimisation, it is required.
 *   In 4-bit parallel mode this does not arise: 37 us/char gives 251 fps
 *   even through the stock LiquidCrystal library.
 *
 * PROTOCOL  (see snsled/runtime.py LcdSink)
 *   host -> Arduino : 0xAA 0x55 <nLcd> <nLed> <contrast> <lcd..> <led..> xor
 *   31 bytes for 20 bars + 5 LEDs -> 2.69 ms at 115200 baud -> 372 fps.
 *   The contrast byte rides along every frame, so it is always in sync and
 *   you can tune it from the host while the display is running.
 *
 * ---- WIRING, 4-bit parallel (default) ----------------------------------
 *   LCD RS -> D12      LCD D4 -> D8       LCD VSS, RW, K -> GND
 *   LCD E  -> D13      LCD D5 -> D7       LCD VDD, A     -> 5V
 *   LCD D6 -> D4       LCD D7 -> D2
 *   These six are the Uno's only non-PWM digital pins besides 0/1, which
 *   leaves the PWM pins for contrast and LEDs.
 *
 *   CONTRAST (LCD pin 3, V0) -- needs 0.40..0.60 V, typ 0.50 V:
 *     USE_PWM_CONTRAST 1 : D9 ---[1k]--- V0,  10uF from V0 to GND
 *     USE_PWM_CONTRAST 0 : 5V ---[10k]--- V0 ---[1k]--- GND   (0.455 V)
 *                          or 4.7k/560 for 0.532 V, nearer the 0.50 typ
 *
 *   BACKLIGHT: put 100 ohm in series with pin 15 (A); pin 16 (K) to GND.
 *   Not every module has a built-in limiting resistor, and driving A
 *   straight to 5 V can destroy the backlight.  100 ohm gives 20 mA in the
 *   worst case and 8 mA if Vf is 4.2 V -- safe either way.
 *
 * ---- WIRING, I2C backpack (set USE_I2C 1) ------------------------------
 *   SDA -> A4        SCL -> A5        VCC -> 5V        GND -> GND
 *   Typical addresses are 0x27 or 0x3F; run an I2C scanner if unsure.
 *
 * ---- LEDs (optional, both modes) ---------------------------------------
 *   D3, D5, D6, D9, D10, D11  each ---[220 ohm]---|>|--- GND
 *   Six coarse band groups.  Omit them entirely and the LCD still works.
 * ========================================================================= */

#define USE_I2C          0   // 0 = 4-bit parallel, 1 = PCF8574 backpack
#define USE_PWM_CONTRAST 1   // 1 = software contrast on D9 (no potentiometer
                             //     needed); 0 = fixed resistor divider on V0
#define USE_LEDS     0       // 0 = LCD only
#define CONTRAST_DEF 26      // ← your number from the sweep

#if USE_I2C
  #include <Wire.h>
  #include <LiquidCrystal_I2C.h>
  #define I2C_ADDR 0x27
  LiquidCrystal_I2C lcd(I2C_ADDR, 20, 4);
#else
  #include <LiquidCrystal.h>
  //                RS  E  D4 D5 D6 D7
  LiquidCrystal lcd(12, 13, 8, 7, 4, 2);
#endif

#define COLS        20
#define ROWS         4
#define PX_CELL      8
#define LEVELS      (ROWS * PX_CELL)      // 32
#define CONTRAST_PIN 9       // Timer1 -- see setup() for the prescaler change
#define CONTRAST_DEF 26      // analogWrite code: 5 V * 26/255 = 0.51 V
#if USE_PWM_CONTRAST
  #define N_LED      5       // D9 is taken by contrast
#else
  #define N_LED      6
#endif
#define BAUD         115200UL
#define FRAME_TIMEOUT 1500

#define MAGIC_A 0xAA
#define MAGIC_B 0x55

#if USE_PWM_CONTRAST
const uint8_t LED_PINS[N_LED] = {3, 5, 6, 10, 11};
#else
const uint8_t LED_PINS[N_LED] = {3, 5, 6, 9, 10, 11};
#endif

/* CGRAM: 8 custom characters, level f fills the bottom f of 8 pixel rows. */
const uint8_t BAR_GLYPH[8][8] PROGMEM = {
  {0b00000,0b00000,0b00000,0b00000,0b00000,0b00000,0b00000,0b11111},  // 1
  {0b00000,0b00000,0b00000,0b00000,0b00000,0b00000,0b11111,0b11111},  // 2
  {0b00000,0b00000,0b00000,0b00000,0b00000,0b11111,0b11111,0b11111},  // 3
  {0b00000,0b00000,0b00000,0b00000,0b11111,0b11111,0b11111,0b11111},  // 4
  {0b00000,0b00000,0b00000,0b11111,0b11111,0b11111,0b11111,0b11111},  // 5
  {0b00000,0b00000,0b11111,0b11111,0b11111,0b11111,0b11111,0b11111},  // 6
  {0b00000,0b11111,0b11111,0b11111,0b11111,0b11111,0b11111,0b11111},  // 7
  {0b11111,0b11111,0b11111,0b11111,0b11111,0b11111,0b11111,0b11111}   // 8 full
};

uint8_t  levels[COLS];              // incoming bar levels, 0..255
uint8_t  leds[N_LED];
uint8_t  shadow[ROWS][COLS];        // what is currently on the glass
uint8_t  peak[COLS];                // peak-hold, in LEVELS units
uint8_t  peakAge[COLS];
uint8_t  contrast = CONTRAST_DEF;
uint32_t lastFrameMs = 0;

static int readByteTimeout(uint16_t ms) {
  uint32_t t0 = millis();
  while ((uint32_t)(millis() - t0) < ms) if (Serial.available()) return Serial.read();
  return -1;
}

/* One place that decides what a cell should show.  drawDiff() used to
 * inline this twice, which is exactly how a scan and its inner loop drift
 * apart.  Integer maths only -- no float on an AVR in the hot path. */
static inline uint8_t wantGlyph(uint8_t r, uint8_t c) {
  uint16_t h = ((uint16_t)levels[c] * LEVELS + 127) / 255;   // round half up
  uint8_t  below = (ROWS - 1 - r) * PX_CELL;
  int16_t  fill  = (int16_t)h - below;
  if (fill >= PX_CELL) return 7;                             // full block
  if (fill > 0)        return (uint8_t)(fill - 1);           // partial
  // empty cell: show the peak-hold marker if the peak lands in this row
  if (peak[c] > 0) {
    uint8_t pcell = peak[c] / PX_CELL;
    if (pcell >= ROWS) pcell = ROWS - 1;                     // clamp at full scale
    if ((ROWS - 1 - r) == pcell) return '-';
  }
  return ' ';
}

/* Differential redraw: walk each row, and for every contiguous run of
 * changed cells issue ONE setCursor then stream the characters.  A
 * setCursor costs the same 37 us as a character, so minimising the number
 * of runs matters as much as minimising the number of characters. */
static void drawDiff() {
  for (uint8_t r = 0; r < ROWS; r++) {
    uint8_t c = 0;
    while (c < COLS) {
      if (wantGlyph(r, c) == shadow[r][c]) { c++; continue; }
      lcd.setCursor(c, r);                       // start of a changed run
      while (c < COLS) {
        uint8_t w = wantGlyph(r, c);
        if (w == shadow[r][c]) break;            // run ends
        lcd.write(w);
        shadow[r][c] = w;
        c++;
      }
    }
  }
}

static void updatePeaks() {
  for (uint8_t c = 0; c < COLS; c++) {
    uint8_t h = (uint8_t)(((uint16_t)levels[c] * LEVELS + 127) / 255);
    if (h >= peak[c]) { peak[c] = h; peakAge[c] = 0; }
    else if (++peakAge[c] > 12 && peak[c] > 0) { peak[c]--; peakAge[c] = 0; }
  }
}

static void blankAll() {
  for (uint8_t c = 0; c < COLS; c++) { levels[c] = 0; peak[c] = 0; }
#if USE_LEDS
  for (uint8_t i = 0; i < N_LED; i++) analogWrite(LED_PINS[i], 0);
#endif
  drawDiff();
}

void setup() {
  Serial.begin(BAUD);

#if USE_PWM_CONTRAST
  /* Software contrast, so no potentiometer is needed.
   *
   * The RC2004A wants VDD-V0 = 4.4/4.5/4.6 V at 25 C, i.e. V0 between 0.40
   * and 0.60 V with a 5 V supply -- a 200 mV window, which is why a wrong
   * fixed resistor leaves the screen blank.
   *
   * Filtering a PWM pin gives that voltage under software control.  At the
   * stock 490 Hz, 1k + 10uF leaves 32 mV of ripple -- 16 % of the whole
   * window.  Rather than demand a bigger capacitor, raise the carrier:
   * Timer1 prescaler 1 gives 31.4 kHz and the same RC then leaves 1.5 mV,
   * a 134x margin.  Timer1 does not drive millis(), so nothing else moves.
   *
   * WIRING:  D9 ---[1k]--- V0 (LCD pin 3),  10uF from V0 to GND.
   */
  TCCR1B = (TCCR1B & 0b11111000) | 0x01;     // Timer1 prescaler 1 -> 31.4 kHz
  pinMode(CONTRAST_PIN, OUTPUT);
  analogWrite(CONTRAST_PIN, contrast);
  delay(50);                                  // let the RC settle before init
#endif
#if USE_I2C
  Wire.begin();
  Wire.setClock(400000);        // REQUIRED -- see "THE I2C TRAP" above
  lcd.init();
  lcd.backlight();
#else
  lcd.begin(COLS, ROWS);
#endif

  uint8_t g[8];
  for (uint8_t i = 0; i < 8; i++) {
    for (uint8_t j = 0; j < 8; j++) g[j] = pgm_read_byte(&BAR_GLYPH[i][j]);
    lcd.createChar(i, g);
  }
  lcd.clear();
  delay(5);                     // clear takes 1.52 ms; be generous

  for (uint8_t r = 0; r < ROWS; r++)
    for (uint8_t c = 0; c < COLS; c++) shadow[r][c] = ' ';

#if USE_LEDS
  for (uint8_t i = 0; i < N_LED; i++) pinMode(LED_PINS[i], OUTPUT);
#endif

  // startup sweep: confirms CGRAM, wiring and column order at a glance
  for (uint8_t c = 0; c < COLS; c++) {
    for (uint8_t k = 0; k < COLS; k++) levels[k] = (k == c) ? 255 : 0;
    drawDiff();
    delay(25);
  }
  blankAll();
  lastFrameMs = millis();
}

void loop() {
  int b = readByteTimeout(200);
  if (b < 0) {
    if ((uint32_t)(millis() - lastFrameMs) > FRAME_TIMEOUT) {
      blankAll();
      lastFrameMs = millis();
    }
    return;
  }
  if (b != MAGIC_A) return;
  if (readByteTimeout(20) != MAGIC_B) return;

  int nL = readByteTimeout(20);
  int nE = readByteTimeout(20);
  int ct = readByteTimeout(20);               // live contrast, 0..255
  if (nL < 1 || nL > COLS || nE < 0 || nE > N_LED || ct < 0) return;

  uint8_t tmp[COLS + N_LED];
  uint8_t got = 0, need = (uint8_t)(nL + nE);
  uint32_t t0 = millis();
  while (got < need && (uint32_t)(millis() - t0) < 40)
    if (Serial.available()) tmp[got++] = (uint8_t)Serial.read();
  if (got != need) return;

  int chk = readByteTimeout(20);
  if (chk < 0) return;
  uint8_t x = 0;
  for (uint8_t i = 0; i < need; i++) x ^= tmp[i];
  if ((uint8_t)chk != x) return;               // corrupt: drop this frame

#if USE_PWM_CONTRAST
  if ((uint8_t)ct != contrast) { contrast = (uint8_t)ct;
                                 analogWrite(CONTRAST_PIN, contrast); }
#endif
  for (uint8_t i = 0; i < (uint8_t)nL; i++) levels[i] = tmp[i];
  for (uint8_t i = (uint8_t)nL; i < COLS; i++) levels[i] = 0;
#if USE_LEDS
  for (uint8_t i = 0; i < (uint8_t)nE; i++) analogWrite(LED_PINS[i], tmp[nL + i]);
#endif

  updatePeaks();
  drawDiff();
  lastFrameMs = millis();
}
