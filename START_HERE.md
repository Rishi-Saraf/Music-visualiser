# START HERE — step by step

Each step has a **success test**. Don't move on until it passes; that way a
fault is always in the thing you just did, never three steps back.

---

## Step 0 — Software only, no hardware (15 min, do this tonight)

```bash
unzip sns_led_visualiser.zip
cd sns_led_visualiser
pip install numpy matplotlib
python validate.py
```

**Success test:** `90 PASS   0 WARN   0 FAIL`

```bash
python -m snsled.report_figures     # writes 11 PNGs to figures/
python -m snsled.main               # full pipeline, simulated display
```

**Success test:** the run ends with `tempo: autocorr 120.18 BPM | comb 119.97 BPM`.

You now have every figure your report needs and a working signal chain.
**Weeks 1–2 of the build plan are done.**

---

## Step 1 — Find your parts (10 min)

| Need | For | Have it? |
|---|---|---|
| 1 kΩ resistor | contrast (Option A) | |
| 10 µF capacitor | contrast (Option A) | |
| *or* 9:1 resistor pair (10k+1k, 4.7k+470, 2.2k+220…) | contrast (Option B) | |
| 100 Ω resistor | backlight — **not optional** | |
| Breadboard | joining resistors to pins | |
| Female-to-female jumpers ×12 | LCD male pins → Arduino female headers | |

**Check your LCD's top edge.** If it has 16 *bare holes* rather than soldered
pins, you need a 16-pin male header soldered on before anything else. That's
the one thing here that needs an iron.

---

## Step 2 — Power and contrast ONLY (the critical step)

Wire **five** things. Nothing else yet.

| LCD pin | Goes to |
|---|---|
| 1 (VSS) | GND |
| 2 (VDD) | 5 V |
| 3 (V0) | contrast circuit ↓ |
| 15 (A) | 5 V **through 100 Ω** |
| 16 (K) | GND |

Contrast, Option A (preferred): `D9 ──[1 kΩ]── pin 3`, and `10 µF` from pin 3
to GND. *(Electrolytic caps are polarised — stripe/short leg to GND.)*

Contrast, Option B: `5 V ──[10 kΩ]── pin 3 ──[1 kΩ]── GND`.

Plug the USB in.

✅ **Success test: the backlight glows.** That is the only thing you can
verify at this stage, and it proves 5 V and GND reach the module.

❌ **You will probably see NOTHING on the glass, and that is correct.**
The HD44780 datasheet's Reset Function sets `D = 0; Display off` after the
internal power-on reset, so an uninitialised module is genuinely blank. The
"row of dark blocks" people describe appears only when the internal reset
*fails* — the datasheet requires the supply to rise past 4.5 V in 0.1–10 ms,
and USB hot-plug frequently misses that window. Blocks are a symptom of a
marginal reset, not a sign of health. Either way you move on to Step 3; the
display cannot show anything meaningful until software initialises it.

| What you see | What it means |
|---|---|
| Backlight on, screen blank | Normal — go to Step 3 |
| Backlight on, row of blocks | Also fine — internal reset didn't complete, software init will fix it |
| **No backlight** | Power is not reaching the module. Check pins 1/2 and 15/16, and the 100 Ω |
| Backlight on, all 4 lines solid dark | Contrast far too high — check the divider or PWM code |

### If there's no backlight, check pin 1 first

Count the pins from the correct end. Pin 1 is marked on the PCB silkscreen —
look for `1`, `VSS`, or a **square** solder pad while every other pad is
round. Counting from the wrong end swaps VSS and VDD and puts your contrast
wire on a data line, which looks exactly like a dead module.

## Step 3 — Find your contrast number

Flash `firmware/lcd_test/lcd_test.ino` (stock **LiquidCrystal** library only —
nothing to install). Leave `CONTRAST_FIXED 0`.

Wire the six data/control lines first:

| LCD pin | Arduino | LCD pin | Arduino |
|---|---|---|---|
| 4 (RS) | D12 | 11 (D4) | D8 |
| 5 (RW) | GND | 12 (D5) | D7 |
| 6 (E) | D13 | 13 (D6) | D4 |
| | | 14 (D7) | D2 |

Pins 7–10 stay unconnected — that's 4-bit mode.

The sketch **sweeps contrast from code 16 to 36 and prints each code on
screen.** This is exactly what turning a potentiometer does, except it tells
you the number. Watch it, note the code where text looks sharpest, then set
`CONTRAST_FIXED` to that number and re-flash.

**Success test:** it then shows `LINE 1 … LINE 4` on all four lines, eight
bar glyphs, and a sweeping column. All four lines proves your DDRAM offsets
and every data wire.

Typical good codes are **23–29**. Write yours down — you'll pass it to the
host as `--contrast N`.

---

## Step 4 — Flash the real firmware

Flash `firmware/lcd_sink/lcd_sink.ino`. Set `USE_LEDS 0` if you haven't
wired LEDs.

**Success test:** on boot, one bar sweeps left to right across all 20
columns, then the screen clears and waits.

---

## Step 5 — Connect the host

```bash
pip install pyserial sounddevice soundfile
python find_port.py
```

It names your port. Then:

```bash
python -m snsled.main --port COM3 --contrast 26 --mode spectrum
```

(substitute your port and your contrast number)

**Success test:** 20 bars dancing, bass on the left. The terminal prints
`beats=... (120/min)`.

---

## Step 6 — Your own music

```bash
python -m snsled.main --source song.wav --port COM3 --mode spectrum
python -m snsled.main --source mic    --port COM3 --mode wave
```

`COM3` is a placeholder -- run `python find_port.py` and use the port it marks
as your Arduino. On Windows `COM3` is usually the *Bluetooth* serial port,
which opens without error and throws every frame away: the bars scroll, the
song plays, and the LCD stays blank with no error anywhere.

Modes: `spectrum`, `mirror`, `wave`, `vu`.

The first one **plays the song out of your speakers** while the bars move, and
the two are locked together: the sound card paces the loop, and the frames are
held back by however much output buffer the card reports (209 ms here, 93 ms
with `--audio-latency low`) so the light lands on the sound rather than a fifth
of a second ahead of it. So the display is blank for that first fraction of a
second -- nothing is wrong, the speaker has not started either.

`--no-audio` goes back to the silent behaviour, `--volume 0.4` turns the
speakers down without dimming the display, and `--av-offset MS` nudges the
alignment if your ears disagree with the card. `--source mic` never plays --
that would be a feedback loop. See README section 6 for why both the rate and
the phase have to be handled.

---

## Step 7 — The report

You already have the figures from Step 0. Add:

1. A **photo** of the real display next to `figures/fig11_lcd.png` — the
   simulation predicted it.
2. A **measured latency**: film the LCD and a speaker at 240 fps on a phone,
   count frames between the kick and the bar jumping. Compare with the
   predicted 26 ms.
3. The four documented failure modes from `README.md` §10. These are what
   separate a project report from a code listing.

---

## Diagnostic sketches — when something doesn't work

Two sketches that **measure** instead of guessing. Both print to the Serial
Monitor at **115200**, and both end in a plain-language verdict.

### `firmware/contrast_check` — is the contrast circuit right?

Extra wire: **Arduino A0 → the V0 node** (where the 1 kΩ, the capacitor's
+ leg and the wire to LCD pin 3 all meet). The LCD can stay connected or be
unplugged entirely.

It sweeps the PWM and measures the result, then reports the slope. The test
is self-calibrating: the ADC's reference and the PWM's amplitude are both
VDD, so `ADC = 1023 × n/255 = 4.012 × n` regardless of what your USB rail
actually supplies — which matches the LCD's own spec, a *ratio* of
VDD − V0 = 4.5 V rather than an absolute voltage.

| Reading | Meaning |
|---|---|
| slope ≈ 4.0 | circuit correct |
| 0 everywhere | open circuit — pin 9, the 1 kΩ, or the wire to V0 |
| 1023 everywhere | V0 tied to 5 V — probably on LCD pin 2, not pin 3 |
| slope much below 4.0 | series resistor too big (10 kΩ instead of 1 kΩ?) |

### `firmware/lcd_probe` — is the LCD alive at all?

The definitive test. Every other check writes and hopes; this one **reads the
LCD back**. It initialises the module, writes each of the four row-start
addresses into the address counter, and reads them out again. A module that
is unpowered or mis-pinned physically cannot return them.

One wiring change, temporary: **LCD pin 5 (RW) moves from GND to Arduino
pin 10.** Put it back to GND afterwards.

| Result | Meaning |
|---|---|
| 4/4 addresses returned | Power, pin 1, RS/E and all four data lines are proven correct. A blank screen can then **only** be contrast |
| status stuck at 0x00 or 0xFF | LCD isn't driving the bus — usually **pin 1 counted from the wrong end** |
| partial / mismatched | the data lines specifically — a swapped pair gives exactly this |

**Run `lcd_probe` first.** It splits the problem cleanly: either the LCD and
its wiring are proven good and you only have contrast left, or it names the
side that's wrong.

## If you get stuck

| Symptom | Most likely cause |
|---|---|
| Blank screen AFTER Step 3 | Contrast — most of the time. Redo the sweep. Blank BEFORE Step 3 is normal |
| Garbage characters | A data line loose, or RW not tied to GND |
| Only lines 1 and 3 work | D4–D7 wired to the wrong Arduino pins |
| Top two lines only | Module not initialised as 4-line; check `lcd.begin(20,4)` |
| Bars lag the music | You're on an I2C backpack at 100 kHz — you aren't, but check `USE_I2C 0` |
| `find_port.py` sees nothing | Missing CH340 driver (Windows), or `dialout` group (Linux) |
