/* =========================================================================
 * LCD PROBE -- the definitive "is my LCD alive?" test.
 *
 * Every other test so far has been one-way: we write and hope.  The HD44780
 * can also be READ (its RW pin selects direction).  This sketch initialises
 * the display, writes a known value into the address counter, then reads it
 * back.  If the value returns intact, the module is powered, correctly
 * pinned, and both nibbles of the data bus work -- proven, not assumed.
 *
 * It also reads the BUSY FLAG, which a dead or mis-wired module cannot
 * produce: floating inputs read as noise or stick at 0x00 / 0xFF.
 *
 * ONE WIRING CHANGE, JUST FOR THIS TEST
 *   LCD pin 5 (RW) normally goes to GND.  Move it to Arduino pin 10.
 *   Everything else stays exactly as it is.  Put RW back to GND afterwards.
 *
 * Serial Monitor at 115200.
 * ========================================================================= */

#define PIN_RS 12
#define PIN_RW 10          // <-- moved off GND for this test only
#define PIN_EN 13
const uint8_t DB[4] = {8, 7, 4, 2};      // D4, D5, D6, D7

static void busOut() { for (uint8_t i=0;i<4;i++) pinMode(DB[i], OUTPUT); }
static void busIn()  { for (uint8_t i=0;i<4;i++) pinMode(DB[i], INPUT);  }

static void pulseE() {
  digitalWrite(PIN_EN, LOW);  delayMicroseconds(1);
  digitalWrite(PIN_EN, HIGH); delayMicroseconds(1);   // >450 ns
  digitalWrite(PIN_EN, LOW);  delayMicroseconds(1);
}

static void writeNibble(uint8_t v) {
  busOut();
  for (uint8_t i=0;i<4;i++) digitalWrite(DB[i], (v >> i) & 1);
  pulseE();
}

static uint8_t readNibble() {
  busIn();
  digitalWrite(PIN_EN, HIGH); delayMicroseconds(1);
  uint8_t v = 0;
  for (uint8_t i=0;i<4;i++) v |= (digitalRead(DB[i]) << i);
  digitalWrite(PIN_EN, LOW);  delayMicroseconds(1);
  return v;
}

static void cmd(uint8_t c) {
  digitalWrite(PIN_RS, LOW); digitalWrite(PIN_RW, LOW);
  writeNibble(c >> 4); writeNibble(c & 0x0F);
  delayMicroseconds(60);
}

static uint8_t readStatus() {          // busy flag (bit 7) + address counter
  digitalWrite(PIN_RS, LOW); digitalWrite(PIN_RW, HIGH);
  uint8_t hi = readNibble(), lo = readNibble();
  digitalWrite(PIN_RW, LOW);
  return (hi << 4) | lo;
}

void setup() {
  Serial.begin(115200);
  while (!Serial) { ; }
  pinMode(PIN_RS, OUTPUT); pinMode(PIN_RW, OUTPUT); pinMode(PIN_EN, OUTPUT);
  digitalWrite(PIN_RW, LOW); digitalWrite(PIN_EN, LOW);

  Serial.println();
  Serial.println(F("=== LCD PROBE ========================================"));
  Serial.println(F("LCD pin 5 (RW) must be on Arduino pin 10 for this test"));
  Serial.println();

  /* ---- the documented 4-bit init sequence ---- */
  delay(60);                                   // >40 ms after VDD rises
  digitalWrite(PIN_RS, LOW);
  writeNibble(0x03); delay(6);                 // >4.1 ms
  writeNibble(0x03); delayMicroseconds(200);   // >100 us
  writeNibble(0x03); delayMicroseconds(200);
  writeNibble(0x02);                           // now in 4-bit mode
  delayMicroseconds(100);
  cmd(0x28);                                   // 4-bit, 2-line, 5x8
  cmd(0x08);                                   // display off
  cmd(0x01); delay(3);                         // clear (1.52 ms)
  cmd(0x06);                                   // entry mode
  cmd(0x0C);                                   // display ON, cursor off

  /* ---- test 1: raw status read ---- */
  uint8_t st = readStatus();
  Serial.print(F("status byte      : 0x"));
  if (st < 16) Serial.print('0');
  Serial.print(st, HEX);
  Serial.print(F("   busy flag = ")); Serial.print((st & 0x80) ? 1 : 0);
  Serial.print(F("   address = 0x"));
  if ((st & 0x7F) < 16) Serial.print('0');
  Serial.println(st & 0x7F, HEX);

  /* ---- test 2: write a known address, read it back ---- */
  const uint8_t probes[4] = {0x00, 0x40, 0x14, 0x54};   // the four row starts
  uint8_t good = 0;
  Serial.println();
  Serial.println(F("address counter read-back (the four 20x4 row starts):"));
  for (uint8_t i=0;i<4;i++) {
    cmd(0x80 | probes[i]);                // set DDRAM address
    delayMicroseconds(60);
    uint8_t back = readStatus() & 0x7F;
    bool ok = (back == probes[i]);
    if (ok) good++;
    Serial.print(F("  wrote 0x"));
    if (probes[i] < 16) Serial.print('0');
    Serial.print(probes[i], HEX);
    Serial.print(F("  read back 0x"));
    if (back < 16) Serial.print('0');
    Serial.print(back, HEX);
    Serial.println(ok ? F("   OK") : F("   MISMATCH"));
  }

  /* ---- verdict ---- */
  Serial.println();
  Serial.println(F("--- VERDICT ------------------------------------------"));
  if (good == 4) {
    Serial.println(F("PASS: the LCD is alive and both nibbles work."));
    Serial.println(F("  Power, pin-1 orientation, RS/E and D4-D7 are ALL correct."));
    Serial.println(F("  A blank screen now can only be CONTRAST."));
    Serial.println(F("  -> run firmware/contrast_check, or temporarily jumper"));
    Serial.println(F("     LCD pin 3 straight to GND to force maximum contrast."));
  } else if (st == 0xFF || st == 0x00) {
    Serial.print(F("FAIL: status reads a stuck 0x"));
    Serial.println(st, HEX);
    Serial.println(F("  The data bus is not being driven by the LCD at all."));
    Serial.println(F("  Most likely, in order of probability:"));
    Serial.println(F("   1. PIN 1 COUNTED FROM THE WRONG END. Find the square"));
    Serial.println(F("      solder pad or the '1'/'VSS' silkscreen mark."));
    Serial.println(F("   2. No power: check LCD pin 1 -> GND, pin 2 -> 5V."));
    Serial.println(F("   3. RW still tied to GND instead of Arduino pin 10."));
    Serial.println(F("   4. E (pin 6) not on Arduino pin 13."));
  } else {
    Serial.println(F("FAIL: partial response -- the LCD answers but wrongly."));
    Serial.println(F("  That points at the DATA lines specifically:"));
    Serial.println(F("   * LCD 11,12,13,14 must go to Arduino 8,7,4,2"));
    Serial.println(F("     (LCD pin 11 is labelled D4 -- it does NOT go to"));
    Serial.println(F("      Arduino pin 4; it goes to Arduino pin 8)"));
    Serial.println(F("   * a swapped pair here gives exactly this symptom."));
  }
  Serial.println(F("------------------------------------------------------"));
  Serial.println();
  Serial.println(F("Writing 'PROBE OK' to line 1 now -- if contrast is right"));
  Serial.println(F("you will see it. Remember to put RW back to GND after."));

  cmd(0x80);
  digitalWrite(PIN_RS, HIGH); digitalWrite(PIN_RW, LOW);
  const char *msg = "PROBE OK";
  while (*msg) { writeNibble(*msg >> 4); writeNibble(*msg & 0x0F);
                 delayMicroseconds(60); msg++; }
}

void loop() { delay(1000); }
