/* =========================================================================
 * CONTRAST CHECK -- measure the contrast circuit instead of guessing at a
 * blank screen.  The Arduino has a 10-bit ADC, so it is its own voltmeter.
 *
 * WHY THIS WORKS WITHOUT A MULTIMETER, AND WITHOUT KNOWING YOUR USB VOLTAGE
 *   The ADC's reference is VDD, and the PWM's amplitude is also VDD, so
 *       ADC = 1023 * V0/VDD   and   V0/VDD = n/255
 *       =>  ADC = 1023 * n/255 = 4.012 * n
 *   VDD cancels.  A sagging 4.75 V USB rail shifts both sides equally and
 *   the reading stays true.  That also matches what the LCD cares about:
 *   its spec is VDD - V0 = 4.5 V, a ratio, not an absolute voltage.
 *
 * EXTRA WIRE NEEDED: one jumper from Arduino A0 to the V0 node -- the same
 * point where the 1k, the capacitor's + leg and the wire to LCD pin 3 meet.
 * The LCD can stay connected or be unplugged entirely; either works.
 *
 * WHAT TO DO
 *   1. Flash this.
 *   2. Tools -> Serial Monitor, set the baud selector to 115200.
 *   3. Read the verdict.  It tells you the fault, not just a number.
 * ========================================================================= */

#define CONTRAST_PIN  9
#define SENSE_PIN    A0
#define N_STEPS       7

const uint8_t STEPS[N_STEPS] = {0, 13, 26, 51, 102, 179, 255};

static uint16_t readAvg(uint8_t pin, uint8_t n) {
  analogRead(pin);                       // discard the first conversion
  uint32_t s = 0;
  for (uint8_t i = 0; i < n; i++) { s += analogRead(pin); delay(2); }
  return (uint16_t)(s / n);
}

void setup() {
  Serial.begin(115200);
  while (!Serial) { ; }
  TCCR1B = (TCCR1B & 0b11111000) | 0x01;     // Timer1 -> 31.4 kHz
  pinMode(CONTRAST_PIN, OUTPUT);

  Serial.println();
  Serial.println(F("=== CONTRAST CIRCUIT CHECK ==========================="));
  Serial.println(F("wire A0 to the V0 node (1k + cap + LCD pin 3 junction)"));
  Serial.println();
  Serial.println(F(" PWM n | expected ADC | measured ADC |  V0/VDD | note"));
  Serial.println(F("-------+--------------+--------------+---------+------"));

  float sx = 0, sy = 0, sxx = 0, sxy = 0;
  bool allZero = true, allHigh = true;

  for (uint8_t i = 0; i < N_STEPS; i++) {
    uint8_t n = STEPS[i];
    analogWrite(CONTRAST_PIN, n);
    delay(300);                                // 5*tau = 50 ms; 300 is ample
    uint16_t adc = readAvg(SENSE_PIN, 32);
    float exp_adc = 1023.0f * n / 255.0f;
    float ratio   = adc / 1023.0f;

    if (adc > 12)   allZero = false;
    if (adc < 1000) allHigh = false;
    sx += n; sy += adc; sxx += (float)n*n; sxy += (float)n*adc;

    Serial.print(F("  ")); if (n < 100) Serial.print(' '); if (n < 10) Serial.print(' ');
    Serial.print(n);
    Serial.print(F("  |     "));
    if (exp_adc < 100) Serial.print(' '); if (exp_adc < 10) Serial.print(' ');
    Serial.print(exp_adc, 0);
    Serial.print(F("      |     "));
    if (adc < 100) Serial.print(' '); if (adc < 10) Serial.print(' ');
    Serial.print(adc);
    Serial.print(F("      |  "));
    Serial.print(ratio, 4);
    Serial.print(F(" | "));
    if (n == 26) Serial.print(F("<- the default setting"));
    Serial.println();
  }

  float slope = (N_STEPS*sxy - sx*sy) / (N_STEPS*sxx - sx*sx);

  analogWrite(CONTRAST_PIN, 26);
  delay(300);
  uint16_t at26 = readAvg(SENSE_PIN, 32);

  Serial.println();
  Serial.print(F("slope: measured ")); Serial.print(slope, 3);
  Serial.println(F("   expected 4.012 ADC counts per PWM step"));
  Serial.print(F("at n=26: ADC ")); Serial.print(at26);
  Serial.print(F("   in-range window is 82..123"));
  Serial.println();
  Serial.println();
  Serial.println(F("--- VERDICT ------------------------------------------"));

  if (allZero) {
    Serial.println(F("FAIL: reads 0 at every setting -- OPEN CIRCUIT."));
    Serial.println(F("  * is A0 really on the V0 node?"));
    Serial.println(F("  * is the 1k actually between pin 9 and that node?"));
    Serial.println(F("  * is the jumper from pin 9 seated in the right hole?"));
    Serial.println(F("  * on a breadboard, are both legs in the SAME row as"));
    Serial.println(F("    the thing they should connect to, not adjacent rows?"));
  } else if (allHigh) {
    Serial.println(F("FAIL: reads full scale -- V0 IS TIED TO 5V."));
    Serial.println(F("  * you are probably on LCD pin 2 (VDD), not pin 3 (V0)."));
    Serial.println(F("  * or the 1k is bridging 5V into the node."));
  } else if (slope < 2.6) {
    Serial.println(F("FAIL: slope too shallow -- TOO MUCH SERIES RESISTANCE"));
    Serial.println(F("  or a second path to ground."));
    Serial.println(F("  * check the resistor is 1k (brown-black-red-gold),"));
    Serial.println(F("    not 10k (brown-black-orange) or 100k."));
  } else if (slope > 5.2) {
    Serial.println(F("FAIL: slope too steep -- unexpected. Check A0 is not"));
    Serial.println(F("  picking up 5V directly."));
  } else if (at26 < 82 || at26 > 123) {
    Serial.print(F("WARN: circuit works (slope OK) but n=26 gives ADC "));
    Serial.println(at26);
    Serial.println(F("  Use the n that lands nearest 102 as your --contrast."));
  } else {
    Serial.println(F("PASS: the contrast circuit is correct."));
    Serial.println(F("  Keep --contrast 26. If the screen is still blank, the"));
    Serial.println(F("  fault is the data lines or the pin-1 end, NOT contrast."));
  }
  Serial.println(F("------------------------------------------------------"));
  Serial.println();
  Serial.println(F("Now holding n=26. Re-open Serial Monitor to run again."));
}

void loop() { delay(1000); }
