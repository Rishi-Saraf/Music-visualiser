/* =========================================================================
 * STEP 1 DIAGNOSTIC -- flash this BEFORE lcd_sink.ino
 *
 * Does three things, in the order you need them:
 *   1. Sweeps contrast slowly and prints the code on screen.  This is what
 *      a potentiometer would do, except it tells you the number.  Watch it,
 *      note the code where the text looks best, then set CONTRAST_FIXED to
 *      that number (and pass --contrast <that number> to the host later).
 *   2. Fills all four lines with a known pattern, which proves the DDRAM
 *      row offsets (0x00, 0x40, 0x14, 0x54) and every data line.
 *   3. Draws the eight CGRAM bar glyphs, which proves custom characters
 *      work before the real sketch depends on them.
 *
 * Needs only the stock LiquidCrystal library -- nothing to install.
 * ========================================================================= */

#include <LiquidCrystal.h>

#define USE_PWM_CONTRAST  1     // 1 = D9 drives V0 through 1k + 10uF
#define CONTRAST_PIN      9
#define CONTRAST_FIXED    0     // 0 = sweep and show codes; or set 21..30
                                //     to hold one value

//                RS  E  D4 D5 D6 D7
LiquidCrystal lcd(12, 13, 8, 7, 4, 2);

const uint8_t BAR[8][8] = {
  {0,0,0,0,0,0,0,31},   {0,0,0,0,0,0,31,31},
  {0,0,0,0,0,31,31,31}, {0,0,0,0,31,31,31,31},
  {0,0,0,31,31,31,31,31},{0,0,31,31,31,31,31,31},
  {0,31,31,31,31,31,31,31},{31,31,31,31,31,31,31,31}
};

void setup() {
#if USE_PWM_CONTRAST
  TCCR1B = (TCCR1B & 0b11111000) | 0x01;    // Timer1 -> 31.4 kHz, low ripple
  pinMode(CONTRAST_PIN, OUTPUT);
  analogWrite(CONTRAST_PIN, CONTRAST_FIXED ? CONTRAST_FIXED : 26);
  delay(80);
#endif
  lcd.begin(20, 4);
  for (uint8_t i = 0; i < 8; i++) lcd.createChar(i, (uint8_t*)BAR[i]);
  lcd.clear();
}

void loop() {
#if USE_PWM_CONTRAST
  if (!CONTRAST_FIXED) {
    /* ---- 1. contrast sweep: find your number ---- */
    for (int n = 16; n <= 36; n++) {
      analogWrite(CONTRAST_PIN, n);
      delay(60);
      lcd.setCursor(0, 0); lcd.print("CONTRAST CODE: ");
      if (n < 10) lcd.print(' ');
      lcd.print(n); lcd.print("  ");
      lcd.setCursor(0, 1); lcd.print("V0 = ");
      lcd.print(5.0 * n / 255.0, 3); lcd.print(" V       ");
      lcd.setCursor(0, 2); lcd.print("Readable? note it. ");
      lcd.setCursor(0, 3);
      for (uint8_t c = 0; c < 20; c++) lcd.write((uint8_t)7);   // solid bar
      delay(700);
    }
  }
#endif

  /* ---- 2. all four lines: proves the row offsets and data lines ---- */
  lcd.clear();
  lcd.setCursor(0, 0); lcd.print("LINE 1 ....|....20");
  lcd.setCursor(0, 1); lcd.print("LINE 2 abcdefghijkl");
  lcd.setCursor(0, 2); lcd.print("LINE 3 0123456789AB");
  lcd.setCursor(0, 3); lcd.print("LINE 4 ############");
  delay(2500);

  /* ---- 3. the eight bar glyphs: proves CGRAM ---- */
  lcd.clear();
  lcd.setCursor(0, 0); lcd.print("CGRAM bars 1..8:");
  for (uint8_t r = 1; r < 4; r++) {
    lcd.setCursor(0, r);
    for (uint8_t c = 0; c < 20; c++) lcd.write((uint8_t)(c % 8));
  }
  delay(2500);

  /* ---- 4. a moving bar: proves nothing is stuck ---- */
  for (uint8_t pass = 0; pass < 2; pass++) {
    for (uint8_t c = 0; c < 20; c++) {
      lcd.clear();
      lcd.setCursor(0, 0); lcd.print("sweep col ");
      lcd.print(c);
      for (uint8_t r = 1; r < 4; r++) { lcd.setCursor(c, r); lcd.write((uint8_t)7); }
      delay(45);
    }
  }
}
