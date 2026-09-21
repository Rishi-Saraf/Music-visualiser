"""LED mapping: turn DSP features into an RGB frame for the strip."""
import numpy as np
from .dsp import Config


def hsv_to_rgb(h, s, v):
    """Vectorised HSV -> RGB.  h,s,v in [0,1].  Returns (...,3) float in [0,1]."""
    h = np.asarray(h, float) % 1.0
    s = np.clip(np.asarray(s, float), 0, 1)
    v = np.clip(np.asarray(v, float), 0, 1)
    i = np.floor(h * 6.0).astype(int)
    f = h * 6.0 - i
    p, q, t = v * (1 - s), v * (1 - f * s), v * (1 - (1 - f) * s)
    i = i % 6
    r = np.select([i==0,i==1,i==2,i==3,i==4,i==5],[v,q,p,p,t,v])
    g = np.select([i==0,i==1,i==2,i==3,i==4,i==5],[t,v,v,q,p,p])
    b = np.select([i==0,i==1,i==2,i==3,i==4,i==5],[p,p,t,v,v,q])
    return np.stack([r, g, b], axis=-1)


def gamma(rgb, g=2.2):
    """Perceptual correction.  LEDs are linear in current but the eye is not;
    without this the bottom of the range looks crushed and the top flat."""
    return np.clip(rgb, 0, 1) ** g


class LedMapper:
    """All visual modes.  Every mode is driven by a named DSP feature."""

    MODES = ('bars', 'mirror', 'centroid', 'pulse', 'vu')

    def __init__(self, cfg: Config):
        self.cfg    = cfg
        self.n      = cfg.n_leds
        self.pulses = []                      # active beat pulses: [pos, life]
        self.hue_sm = 0.0

    # -- mode 1: spectrum bars -------------------------------------------------
    def bars(self, bands):
        n, k = self.n, len(bands)
        out  = np.zeros((n, 3))
        seg  = n // k
        for b in range(k):
            lo, hi = b * seg, (b + 1) * seg if b < k - 1 else n
            lvl  = bands[b]
            span = hi - lo
            lit  = int(round(lvl * span))
            hue  = 0.95 * b / max(1, k - 1) * 0.72     # red(bass) -> blue(treble)
            if lit: out[lo:lo + lit] = hsv_to_rgb(hue, 1.0, 1.0)
        return out

    # -- mode 2: mirrored bars from the centre --------------------------------
    def mirror(self, bands):
        half = self.bars(bands)[: self.n // 2]
        return np.concatenate([half[::-1], half]) if self.n % 2 == 0 else \
               np.concatenate([half[::-1], np.zeros((1, 3)), half])

    # -- mode 3: spectral centroid -> hue, energy -> brightness ---------------
    def centroid(self, centroid_norm, energy):
        self.hue_sm += 0.25 * (np.clip(centroid_norm, 0, 1) - self.hue_sm)
        hue = 0.70 * self.hue_sm                        # red -> blue
        return np.tile(hsv_to_rgb(hue, 1.0, np.clip(energy, 0, 1)), (self.n, 1))

    # -- mode 4: beat-triggered travelling pulse ------------------------------
    def pulse(self, beat, bands, speed=2.0, life=40):
        if beat:
            self.pulses.append([0.0, life])
        out = np.zeros((self.n, 3))
        keep = []
        for p in self.pulses:
            p[0] += speed; p[1] -= 1
            if p[1] > 0 and p[0] < self.n:
                i = int(p[0]); w = max(1, self.n // 20)
                lo, hi = max(0, i - w), min(self.n, i + w)
                fall = np.exp(-np.abs(np.arange(lo, hi) - i) / (w / 2.0))
                v = (p[1] / life) * fall
                out[lo:hi] = np.maximum(out[lo:hi],
                                        hsv_to_rgb(0.08, 0.9, 1.0) * v[:, None])
                keep.append(p)
        self.pulses = keep[-12:]
        glow = float(bands[0]) * 0.35
        out += hsv_to_rgb(0.0, 1.0, glow)
        return np.clip(out, 0, 1)

    # -- mode 5: VU meter ------------------------------------------------------
    def vu(self, energy):
        out = np.zeros((self.n, 3))
        lit = int(round(np.clip(energy, 0, 1) * self.n))
        if lit:
            frac = np.linspace(0, 1, self.n)[:lit]
            hue  = 0.33 * (1.0 - frac)                 # green -> amber -> red
            out[:lit] = hsv_to_rgb(hue, 1.0, 1.0)
        return out

    def render(self, mode, *, bands=None, centroid_norm=0.0,
               energy=0.0, beat=False, brightness=1.0, **_):
        if   mode == 'bars':     rgb = self.bars(bands)
        elif mode == 'mirror':   rgb = self.mirror(bands)
        elif mode == 'centroid': rgb = self.centroid(centroid_norm, energy)
        elif mode == 'pulse':    rgb = self.pulse(beat, bands)
        elif mode == 'vu':       rgb = self.vu(energy)
        else: raise ValueError(f'unknown mode {mode!r}; use one of {self.MODES}')
        return (gamma(rgb) * brightness * 255).astype(np.uint8)


def power_estimate(frame_u8, ma_per_channel=20.0):
    """Predicted strip current in amps for this frame.

    20 mA per channel at full scale (Adafruit NeoPixel Ueberguide: 60 mA per
    pixel for full white).  Use this to drive a brightness cap so the supply
    is never asked for more than it can give.
    """
    return float(frame_u8.sum()) / 255.0 * ma_per_channel / 1000.0


# ============================================================================
# Discrete PWM LEDs  --  6 channels on an Arduino Uno/Nano (pins 3,5,6,9,10,11)
# ============================================================================
# Built for the hardware you actually have: plain LEDs + resistors, powered
# from USB.  analogWrite() only writes a timer compare register, so unlike
# WS2812B there is NO interrupt blackout and no handshake is needed.

# 8-bit gamma table.  LED current is linear, perceived brightness is not;
# without this the bottom half of the range is invisible and the top is flat.
GAMMA8 = (np.round(255.0 * (np.arange(256) / 255.0) ** 2.2)).astype(np.uint8)

UNO_PWM_PINS = (3, 5, 6, 9, 10, 11)


class PwmMapper:
    """Turn DSP features into N discrete channel levels (uint8, gamma-corrected).

    Modes
      bands     channel i brightness = energy of mel band i   (the main mode)
      vu        the N LEDs act as one bar graph of broadband level
      chase     a beat EVENT launches a light travelling across the LEDs
      sweep     normalised spectral centroid selects the brightest LED
      strobe    all LEDs flash together on each beat event

    chase and strobe take a boolean beat EVENT, never the raw detection
    function -- thresholding the ODF directly fires on ~36 % of frames.
    vu and sweep take values already normalised by an AdaptiveRange, so no
    per-song tuning is needed.
    """

    MODES = ('bands', 'vu', 'chase', 'sweep', 'strobe')

    def __init__(self, n_ch: int = 6):
        self.n = n_ch
        self.pos = float(n_ch + 4)     # start past the end = dark until a beat
        self.strobe_v = 0.0

    def bands(self, b):
        return np.clip(np.asarray(b, float)[: self.n], 0, 1)

    def vu(self, energy):
        """Bar graph with a partially-lit top LED, so it reads smoothly."""
        e = np.clip(energy, 0, 1) * self.n
        return np.clip(e - np.arange(self.n), 0, 1)

    def chase(self, beat, speed=0.18, tail=0.55):
        """Head travels from LED 0; LEDs behind it glow with a decaying tail."""
        if beat: self.pos = 0.0
        else:    self.pos += speed
        d = self.pos - np.arange(self.n)          # >0 once the head has passed
        return np.where(d >= 0, np.exp(-d / tail), 0.0)

    def sweep(self, centroid_norm, energy, width=1.0):
        centre = np.clip(centroid_norm, 0, 1) * (self.n - 1)
        d = np.abs(np.arange(self.n) - centre)
        return np.clip(np.exp(-(d / width) ** 2) * np.clip(energy, 0, 1), 0, 1)

    def strobe(self, beat, decay=0.78):
        self.strobe_v = 1.0 if beat else self.strobe_v * decay
        return np.full(self.n, np.clip(self.strobe_v, 0, 1))

    def render(self, mode, *, bands=None, centroid_norm=0.0, energy=0.0,
               beat=False, **_):
        if   mode == 'bands':  lv = self.bands(bands)
        elif mode == 'vu':     lv = self.vu(energy)
        elif mode == 'chase':  lv = self.chase(beat)
        elif mode == 'sweep':  lv = self.sweep(centroid_norm, energy)
        elif mode == 'strobe': lv = self.strobe(beat)
        else: raise ValueError(f'unknown mode {mode!r}; use one of {self.MODES}')
        return GAMMA8[(np.clip(lv, 0, 1) * 255).astype(np.uint8)]


def pwm_current_ma(levels_u8, vf=1.8, vcc=5.0, r=220.0):
    """Predicted total chip current (mA) for one PWM frame.

    PWM duty scales average current linearly, so I_avg = duty * (Vcc-Vf)/R.
    """
    duty = np.asarray(levels_u8, float) / 255.0
    return float(duty.sum() * (vcc - vf) / r * 1000.0)


# ============================================================================
# HD44780 20x4 character LCD  (RG2004A / 2004A and compatibles)
# ============================================================================
# 20 columns x 4 rows, each character cell 5x8 dots.  Using the 8 CGRAM
# custom characters as partial vertical bars gives 4 x 8 = 32 levels of
# height per column -- a 20-band, 32-level spectrum analyser.
#
# The host sends 20 band levels; the Arduino turns them into characters and
# does its own differential update.  That keeps the link at 31 bytes/frame
# and lets the device skip cells that have not changed -- measured at 17.7
# changed cells per frame out of 80, a 4.5x saving.

LCD_COLS, LCD_ROWS, LCD_PX = 20, 4, 8
LCD_LEVELS = LCD_ROWS * LCD_PX                 # 32
LCD_DDRAM_OFFSETS = (0x00, 0x40, 0x14, 0x54)   # standard 20x4 row layout


class LcdMapper:
    """Map mel band energies onto 20 bar heights (0..255, scaled to 32 on device).

    Modes
      spectrum   one bar per mel band -- the main mode
      mirror     bars grow from the vertical centre outward
      wave       bars offset by a travelling phase, driven by band energy
      vu         all 20 bars follow broadband level (a wide VU meter)
    """

    MODES = ('spectrum', 'mirror', 'wave', 'vu')

    def __init__(self, n_cols: int = LCD_COLS):
        self.n = n_cols
        self.phase = 0.0

    def spectrum(self, bands):
        b = np.asarray(bands, float)
        if len(b) == self.n: return np.clip(b, 0, 1)
        idx = np.linspace(0, len(b) - 1, self.n)
        return np.clip(np.interp(idx, np.arange(len(b)), b), 0, 1)

    def mirror(self, bands):
        half = self.spectrum(bands)[: self.n // 2]
        return np.concatenate([half[::-1], half])

    def wave(self, bands, energy):
        self.phase += 0.15
        env = self.spectrum(bands)
        ripple = 0.5 + 0.5 * np.sin(np.arange(self.n) * 0.6 - self.phase)
        return np.clip(env * (0.55 + 0.45 * ripple) * (0.4 + 0.6 * energy), 0, 1)

    def vu(self, energy):
        return np.full(self.n, np.clip(energy, 0, 1))

    def render(self, mode, *, bands=None, energy=0.0, **_):
        if   mode == 'spectrum': lv = self.spectrum(bands)
        elif mode == 'mirror':   lv = self.mirror(bands)
        elif mode == 'wave':     lv = self.wave(bands, energy)
        elif mode == 'vu':       lv = self.vu(energy)
        else: raise ValueError(f'unknown mode {mode!r}; use one of {self.MODES}')
        return (np.clip(lv, 0, 1) * 255).astype(np.uint8)


def lcd_char_grid(levels_u8):
    """Reference implementation of what the firmware draws.  Used by the
    report figures and by validate.py so host and device agree exactly.

    Returns (4, 20) int16: 0x20 = space, 0..7 = CGRAM custom character.
    """
    h = np.round(np.asarray(levels_u8, float) / 255.0 * LCD_LEVELS).astype(int)
    g = np.full((LCD_ROWS, LCD_COLS), 0x20, dtype=np.int16)
    for c in range(min(LCD_COLS, len(h))):
        for r in range(LCD_ROWS):
            below = (LCD_ROWS - 1 - r) * LCD_PX
            fill = int(np.clip(h[c] - below, 0, LCD_PX))
            if fill > 0:
                g[r, c] = 7 if fill == LCD_PX else fill - 1
    return g


def lcd_update_cost(grid, prev):
    """(cells_changed, contiguous_runs) -- what one differential redraw costs."""
    d = (grid != prev)
    runs = 0
    for row in range(d.shape[0]):
        inrun = False
        for col in range(d.shape[1]):
            if d[row, col] and not inrun: runs += 1; inrun = True
            elif not d[row, col]: inrun = False
    return int(d.sum()), runs
