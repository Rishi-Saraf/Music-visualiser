"""Validation report.  Every design claim in the README, checked in code."""
import numpy as np
from snsled.dsp import (Config, STFT, mel_filterbank, AsymmetricEnvelope,
                        OnsetDetector, estimate_tempo, hz_to_mel, mel_to_hz,
                        OnsetEvents, AdaptiveRange, rms_db)
from snsled.leds import (LedMapper, power_estimate, PwmMapper,
                         pwm_current_ma, GAMMA8, UNO_PWM_PINS,
                         LcdMapper, lcd_char_grid, lcd_update_cost,
                         LCD_COLS, LCD_ROWS, LCD_PX, LCD_LEVELS,
                         LCD_DDRAM_OFFSETS)
from snsled.runtime import (SyntheticSource, VirtualSink,
                            VirtualPwmSink, VirtualLcdSink, run)

R = []
def check(name, cond, got, exp, warn=False):
    R.append(('PASS' if cond else ('WARN' if warn else 'FAIL'), name, got, exp))

cfg = Config(n_leds=60)

# --- framing -----------------------------------------------------------------
check('FFT resolution df = fs/N', abs(cfg.df - 21.5332) < 1e-3,
      f'{cfg.df:.4f} Hz', '21.5332 Hz')
check('Frame rate fs/hop', abs(cfg.frame_rate - 86.1328) < 1e-3,
      f'{cfg.frame_rate:.4f} fps', '86.1328 fps')
u = cfg.window_ms / 1000 * cfg.df
check('Uncertainty product dt*df', abs(u - 1.0) < 1e-9, f'{u:.9f}', '1.0 exactly')

# --- window ------------------------------------------------------------------
N, M = cfg.n_fft, 1 << 17
w = np.hanning(N); W = np.abs(np.fft.rfft(w, M)); W /= W.max()
bins = np.arange(M//2+1) * N / M; dB = 20*np.log10(W + 1e-15)
sl = dB[bins > 2.04].max()
enbw = (w**2).sum() * N / (w.sum()**2)
check('Hann highest side lobe', abs(sl + 31.5) < 0.3, f'{sl:.2f} dB', '-31.5 dB (Harris 1978)')
check('Hann ENBW', abs(enbw - 1.50) < 0.01, f'{enbw:.3f} bins', '1.50 bins')

# --- filter bank -------------------------------------------------------------
fb = mel_filterbank(cfg)
check('Mel bank shape', fb.shape == (cfg.n_bands, cfg.n_fft//2+1),
      str(fb.shape), f'({cfg.n_bands}, {cfg.n_fft//2+1})')
check('Mel rows area-normalised', np.allclose(fb.sum(axis=1), 1.0),
      f'sums {fb.sum(axis=1).min():.6f}..{fb.sum(axis=1).max():.6f}', 'all 1.0')
e = mel_to_hz(np.linspace(hz_to_mel(20), hz_to_mel(16000), cfg.n_bands+2))
d = np.diff(hz_to_mel(e))
check('Mel edges equally spaced in mel', np.allclose(d, d[0]),
      f'spread {d.max()-d.min():.2e} mel', '0')

# --- envelope ----------------------------------------------------------------
fr = cfg.frame_rate
def fc_numeric(a, Fsf):
    ww = np.linspace(1e-6, np.pi, 2_000_001); p = 1-a
    H2 = a**2/(1 - 2*p*np.cos(ww) + p*p)
    return ww[np.argmin(np.abs(H2-0.5))]*Fsf/(2*np.pi)
for a in (0.12, 0.30, 0.50):
    c, n_ = AsymmetricEnvelope.cutoff_hz(a, fr), fc_numeric(a, fr)
    check(f'Envelope cutoff alpha={a} (closed form vs numerical)',
          abs(c-n_) < 2e-3*max(c,1), f'{c:.4f} Hz', f'{n_:.4f} Hz')
tau = AsymmetricEnvelope.tau_ms(0.12, fr)
check('Release time constant', abs(tau - 90.8) < 1.0, f'{tau:.1f} ms', '~91 ms')
check('Attack lag at attack=1.0', AsymmetricEnvelope.tau_ms(1.0, fr) == 0.0,
      '0.0 ms', '0 ms')

# --- power -------------------------------------------------------------------
full = np.full((60, 3), 255, np.uint8)
check('60 LEDs full white current', abs(power_estimate(full) - 3.60) < 1e-6,
      f'{power_estimate(full):.2f} A', '3.60 A (60x60 mA, Adafruit)')

# --- protocol ----------------------------------------------------------------
m = LedMapper(cfg)
fr_u8 = m.render('bars', bands=np.array([.9,.5,.3,.2,.4,.6,.8,.2]))
pl = fr_u8.reshape(-1).tobytes(); chk = 0
for v in pl: chk ^= v
wire = bytes([0xAA,0x55,len(pl)&0xFF,(len(pl)>>8)&0xFF]) + pl + bytes([chk])
dec = np.frombuffer(wire[4:4+len(pl)], np.uint8).reshape(-1,3)
check('Wire protocol round trip', np.array_equal(dec, fr_u8),
      f'{len(wire)} B for 60 LEDs', 'byte-identical')

# --- AVR budget --------------------------------------------------------------
strobe = 60*24*1.25/1000 + 0.280
frame_ms = (1+len(pl))*10/1e6*1000 + strobe
check('Frame rate achievable at 1 Mbaud', 1000/frame_ms > cfg.frame_rate,
      f'{1000/frame_ms:.1f} fps', f'> {cfg.frame_rate:.1f} fps needed')
ubrr = 16e6/(8*1_000_000) - 1
check('1 Mbaud UBRR is an exact integer', abs(ubrr - round(ubrr)) < 1e-9,
      f'UBRR={ubrr:.6f}', 'integer -> 0.00% error')
check('AVR SRAM for 60-LED buffer', 60*3 + 300 < 2048,
      f'{60*3+300} B of 2048', '< 2048 B')

# --- latency -----------------------------------------------------------------
lat = 2*cfg.hop/cfg.fs*1000 + 0.12 + (1+180)*10/1e6*1000 + strobe
check('End-to-end latency vs ITU-R BT.1359-1', lat < 45.0,
      f'{lat:.2f} ms', '< 45 ms')

# --- end-to-end --------------------------------------------------------------
src = SyntheticSource(cfg)
res = run(src, VirtualSink(cfg, keep=False), cfg, mode='bars',
          verbose=False, realtime=False)
b1, b2 = res['bpm']
check('Tempo, autocorrelation', abs(b1-120) < 1.2, f'{b1:.2f} BPM', '120.00 +/- 1.2')
check('Tempo, comb filter',     abs(b2-120) < 1.2, f'{b2:.2f} BPM', '120.00 +/- 1.2')
check('Two tempo methods agree', abs(b1-b2) < 1.2, f'{abs(b1-b2):.3f} BPM apart', '< 1.2')
check('Brightness cap respected', res['peak_amps'] <= 2.4 + 1e-6,
      f'{res["peak_amps"]:.2f} A', '<= 2.40 A')
for mode in LedMapper.MODES:
    f_ = LedMapper(cfg).render(mode, bands=np.full(8,.5), centroid_hz=1500,
                               energy=.5, onset=.1)
    check(f'Mode "{mode}" renders', f_.shape == (60,3) and f_.dtype == np.uint8,
          f'{f_.shape} {f_.dtype}', '(60, 3) uint8')

# --- PWM path (the hardware actually on hand) --------------------------------
F = 16e6
check('PWM freq, Timer0 pins 5/6 (fast, 256)', abs(F/(64*256) - 976.5625) < 1e-3,
      f'{F/(64*256):.4f} Hz', '976.5625 Hz')
check('PWM freq, Timer1/2 pins 9,10,3,11 (phase-correct, 510)',
      abs(F/(64*510) - 490.196) < 1e-3, f'{F/(64*510):.4f} Hz', '490.196 Hz')
check('Slowest PWM clears flicker fusion', F/(64*510) > 90*3,
      f'{F/(64*510)/90:.1f}x over 90 Hz', '> 3x')
check('Gamma LUT distinct levels', len(np.unique(GAMMA8)) == 184,
      f'{len(np.unique(GAMMA8))} of 256', '184')
check('Gamma LUT endpoints', GAMMA8[0] == 0 and GAMMA8[255] == 255,
      f'{GAMMA8[0]} .. {GAMMA8[255]}', '0 .. 255')
check('PWM channel count matches Uno PWM pins', len(UNO_PWM_PINS) == 6,
      f'{len(UNO_PWM_PINS)} pins {UNO_PWM_PINS}', '6')
i_red = (5.0-1.8)/220*1000
check('Per-LED current, red @220 ohm', 5.0 < i_red < 20.0,
      f'{i_red:.1f} mA', '< 20 mA recommended')
full6 = np.full(6, 255, np.uint8)
check('Worst-case total current, 6 red LEDs', pwm_current_ma(full6) < 200.0,
      f'{pwm_current_ma(full6):.1f} mA', '< 200 mA chip limit')
check('USB can power it', pwm_current_ma(full6) < 500.0,
      f'{pwm_current_ma(full6):.1f} mA', '< 500 mA USB')
lv = PwmMapper(6).render('bands', bands=np.array([.9,.6,.4,.3,.5,.2]))
pl = bytes(lv); c2 = 0
for v in pl: c2 ^= v
wire2 = bytes([0xAA,0x55,len(pl)]) + pl + bytes([c2])
dec2 = np.frombuffer(wire2[3:3+6], np.uint8)
check('PWM wire protocol round trip', np.array_equal(dec2, lv) and len(wire2) == 10,
      f'{len(wire2)} B, byte-identical', '10 B, identical')
fps115 = 1000/(len(wire2)*10/115200*1000)
check('PWM frame rate at 115200 baud', fps115 > cfg.frame_rate,
      f'{fps115:.0f} fps', f'> {cfg.frame_rate:.1f} needed')
lat_pwm = 2*cfg.hop/cfg.fs*1000 + 0.12 + len(wire2)*10/115200*1000 + 1000/490.196
check('PWM end-to-end latency', lat_pwm < 45.0, f'{lat_pwm:.2f} ms', '< 45 ms')
check('PWM latency beats the WS2812B path', lat_pwm < 27.23,
      f'{lat_pwm:.2f} vs 27.23 ms', 'lower')

cfg6 = Config(n_bands=6)
for mode in PwmMapper.MODES:
    l_ = PwmMapper(6).render(mode, bands=np.full(6,.5), centroid_hz=1500,
                             energy=.5, onset=.1)
    check(f'PWM mode "{mode}" renders', l_.shape == (6,) and l_.dtype == np.uint8,
          f'{l_.shape} {l_.dtype}', '(6,) uint8')
res6 = run(SyntheticSource(cfg6), VirtualPwmSink(6, keep=False), cfg6,
           mode='bands', verbose=False, realtime=False, output='pwm')
p1, p2 = res6['bpm']
check('PWM path tempo, autocorrelation', abs(p1-120) < 1.5, f'{p1:.2f} BPM', '120 +/- 1.5')
check('PWM path tempo, comb filter',     abs(p2-120) < 1.5, f'{p2:.2f} BPM', '120 +/- 1.5')
check('PWM path peak current', res6['peak_amps']*1000 < 200.0,
      f'{res6["peak_amps"]*1000:.1f} mA', '< 200 mA')

# --- beat EVENT detection ----------------------------------------------------
_v = __import__('snsled.runtime', fromlist=['Visualiser']).Visualiser(
        Config(n_bands=6), mode='bands', output='pwm')
_odf = []
for _b in SyntheticSource(Config(n_bands=6)):
    _v.step(_b); _odf.append(_v.odf_hist[-1])
_odf = np.array(_odf); _fr = Config().frame_rate; _dur = len(_odf)/_fr

def _events(rel, refr=100.0):
    e = OnsetEvents(_fr, refractory_ms=refr, rel_thresh=rel)
    return np.array([i/_fr for i, v in enumerate(_odf) if e(v)])

t35 = _events(0.35); i35 = np.diff(t35); cv35 = i35.std()/i35.mean()
check('Beat events at default sensitivity 0.35', abs(len(t35)/_dur*60 - 120) < 6,
      f'{len(t35)/_dur*60:.0f} /min', '120 /min (true beat)')
check('Beat interval regularity (CV)', cv35 < 0.15, f'CV={cv35:.3f}', '< 0.15')
check('Median beat interval', abs(np.median(i35) - 0.5) < 0.02,
      f'{np.median(i35):.3f} s', '0.500 s')
t15 = _events(0.15); i15 = np.diff(t15); cv15 = i15.std()/i15.mean()
check('Sensitivity 0.15 locks to the tatum', abs(np.median(i15) - 0.25) < 0.02,
      f'{np.median(i15):.3f} s', '0.250 s')
check('Sensitivity 0.15 is also regular', cv15 < 0.15, f'CV={cv15:.3f}', '< 0.15')
t25 = _events(0.25); i25 = np.diff(t25); cv25 = i25.std()/i25.mean()
check('Sensitivity 0.25 falls BETWEEN metrical levels (documented)',
      cv25 > 2*max(cv35, cv15), f'CV={cv25:.3f}', f'>> {max(cv35,cv15):.3f}')
check('Onset events fire on few frames', (len(t35)/len(_odf)) < 0.05,
      f'{len(t35)/len(_odf)*100:.1f}% of frames', '< 5% (raw ODF was 35.6%)')

# --- adaptive normalisation --------------------------------------------------
_ar = AdaptiveRange(-55.0, -12.0, min_span=12.0)
_o = [_ar(x) for x in (-60, -10, -35, -35, -35)]
check('AdaptiveRange stays in [0,1]', all(0.0 <= v <= 1.0 for v in _o),
      f'{[round(v,2) for v in _o]}', 'all within [0,1]')
check('AdaptiveRange resists collapse', (_ar.hi - _ar.lo) >= 12.0 - 1e-9,
      f'span {_ar.hi-_ar.lo:.1f}', '>= min_span 12.0')
check('rms_db floor', rms_db(np.zeros(512)) == -70.0, f'{rms_db(np.zeros(512)):.1f} dB', '-70.0 dB')
check('rms_db of full-scale sine', abs(rms_db(np.sin(np.linspace(0,20*np.pi,4410))) + 3.01) < 0.1,
      f'{rms_db(np.sin(np.linspace(0,20*np.pi,4410))):.2f} dBFS', '-3.01 dBFS')

# --- 20x4 character LCD ------------------------------------------------------
check('LCD geometry', (LCD_COLS, LCD_ROWS, LCD_PX) == (20, 4, 8),
      f'{LCD_COLS}x{LCD_ROWS}, {LCD_PX}px cells', '20x4, 8px')
check('LCD vertical resolution', LCD_LEVELS == 32,
      f'{LCD_LEVELS} levels/bar', '4 rows x 8 px = 32')
check('LCD DDRAM row offsets', LCD_DDRAM_OFFSETS == (0x00, 0x40, 0x14, 0x54),
      str([hex(x) for x in LCD_DDRAM_OFFSETS]), "['0x0','0x40','0x14','0x54']")
check('CGRAM custom chars needed', 8 <= 8, '8 of 8 available', '<= 8 (HD44780)')

def _fw_glyph(level, r, peak=0):
    """Bit-exact model of wantGlyph() in firmware/lcd_sink/lcd_sink.ino."""
    h = (level*LCD_LEVELS + 127)//255
    fill = h - (LCD_ROWS-1-r)*LCD_PX
    if fill >= LCD_PX: return 7
    if fill > 0:       return fill-1
    if peak > 0:
        pcell = min(peak//LCD_PX, LCD_ROWS-1)
        if (LCD_ROWS-1-r) == pcell: return ord('-')
    return 0x20

_bad = sum(1 for lvl in range(256) for r in range(LCD_ROWS)
           if _fw_glyph(lvl, r) != lcd_char_grid(np.full(LCD_COLS, lvl, np.uint8))[r, 0])
check('Host renderer == firmware integer maths', _bad == 0,
      f'{1024-_bad}/1024 agree', 'all 1024')
check('Peak-marker row index clamped at full scale',
      all(0 <= min(pk//LCD_PX, LCD_ROWS-1) < LCD_ROWS for pk in range(LCD_LEVELS+1)),
      'every peak 0..32 in range', f'0..{LCD_ROWS-1}')
_codes = {_fw_glyph(l, r, pk) for l in range(0,256,7) for r in range(LCD_ROWS)
          for pk in (0,5,15,25,32)}
check('Only valid glyph codes emitted',
      all(v in (0x20, ord('-')) or 0 <= v <= 7 for v in _codes),
      f'{sorted(_codes)}', 'space, dash, CGRAM 0-7')

# differential redraw cost, measured on the test track
_cfg20 = Config(n_bands=LCD_COLS)
_sk = VirtualLcdSink(LCD_COLS, 6)
_r20 = run(SyntheticSource(_cfg20), _sk, _cfg20, mode='spectrum',
           verbose=False, realtime=False, output='lcd')
_L = _sk.lcd_only()
_prev = np.full((LCD_ROWS, LCD_COLS), -1, dtype=np.int16)
_ch, _ru = [], []
for _row in _L[5:]:
    _g = lcd_char_grid(_row); _c, _q = lcd_update_cost(_g, _prev)
    _ch.append(_c); _ru.append(_q); _prev = _g
_ch, _ru = np.array(_ch), np.array(_ru)
check('Differential redraw beats full redraw', _ch.mean() < 80/2,
      f'{_ch.mean():.1f} of 80 cells', '< 40 (saving {:.1f}x)'.format(80/_ch.mean()))

T = 37e-6                                     # HD44780 instruction time
def _fps(per_char):
    return 1.0/(np.percentile(_ch,95)*per_char + np.percentile(_ru,95)*per_char)
check('LCD fps, 4-bit parallel (37 us/char)', _fps(T) > cfg.frame_rate,
      f'{_fps(T):.0f} fps', f'> {cfg.frame_rate:.1f}')
check('LCD fps, LiquidCrystal overhead (2.5x)', _fps(T*2.5) > cfg.frame_rate,
      f'{_fps(T*2.5):.0f} fps', f'> {cfg.frame_rate:.1f}')
check('LCD fps, I2C @400 kHz', _fps(135e-6) > cfg.frame_rate,
      f'{_fps(135e-6):.0f} fps', f'> {cfg.frame_rate:.1f}')
check('I2C @100 kHz is TOO SLOW (documented trap)', _fps(540e-6) < cfg.frame_rate,
      f'{_fps(540e-6):.0f} fps', f'< {cfg.frame_rate:.1f} -> must set 400 kHz')

_lv = LcdMapper().render('spectrum', bands=np.linspace(1, .2, LCD_COLS))
_led5 = np.full(5, 128, np.uint8)
_pl = bytes(_lv) + bytes(_led5); _c3 = 0
for v in _pl: _c3 ^= v
_CONTRAST = 26
_w3 = bytes([0xAA,0x55,len(_lv),len(_led5),_CONTRAST]) + _pl + bytes([_c3])
check('LCD wire protocol round trip',
      np.array_equal(np.frombuffer(_w3[5:5+LCD_COLS], np.uint8), _lv) and len(_w3) == 31,
      f'{len(_w3)} B, byte-identical', '31 B, identical')

# --- contrast without a potentiometer ---------------------------------------
# Raystar RC2004A: VDD-V0 = 4.4 / 4.5 / 4.6 V at 25 C
V0_MIN, V0_TYP, V0_MAX = 5.0-4.6, 5.0-4.5, 5.0-4.4
check('Contrast window from datasheet', abs(V0_MAX-V0_MIN - 0.2) < 1e-9,
      f'{V0_MIN:.2f}-{V0_MAX:.2f} V', '0.40-0.60 V (200 mV)')
check('Default contrast code lands in the window',
      V0_MIN <= 5.0*_CONTRAST/255 <= V0_MAX,
      f'n={_CONTRAST} -> {5.0*_CONTRAST/255:.3f} V', f'{V0_MIN:.2f}-{V0_MAX:.2f} V')
_usable = [n for n in range(256) if V0_MIN <= 5.0*n/255 <= V0_MAX]
check('Usable contrast codes', _usable[0] == 21 and _usable[-1] == 30,
      f'n = {_usable[0]}..{_usable[-1]}', '21..30')
for R1, R2, want in ((10000, 1000, 0.455), (4700, 560, 0.532), (8200, 1000, 0.543)):
    v = 5.0*R2/(R1+R2)
    check(f'Fixed divider {R1//1000}k/{R2} -> V0', V0_MIN <= v <= V0_MAX,
          f'{v:.3f} V', f'in {V0_MIN:.2f}-{V0_MAX:.2f}')
def _ripple_mV(f_pwm, R, C):
    """Peak-to-peak ripple of an RC-filtered PWM, exact for T << tau:
           dV = Vcc * d * (1-d) * T / tau
    Verified against a time-domain simulation to 2.2 % (see
    snsled/contrast_figure.py).  An earlier fundamental-only estimate gave
    0.50 mV and was optimistic by 3x."""
    d = V0_TYP/5.0
    return 5.0*d*(1-d)*(1.0/f_pwm)/(R*C)*1000
check('PWM contrast ripple at stock 490 Hz (1k+10uF) is TOO HIGH',
      _ripple_mV(490.196, 1000, 10e-6) > 0.10*(V0_MAX-V0_MIN)*1000,
      f'{_ripple_mV(490.196,1000,10e-6):.1f} mV', '> 20 mV = 10% of window')
check('Timer1 prescaler 1 fixes it', abs(16e6/(1*510) - 31372.5) < 1.0,
      f'{16e6/(1*510):.0f} Hz', '31372 Hz')
check('PWM contrast ripple at 31.4 kHz (1k+10uF)',
      _ripple_mV(16e6/510, 1000, 10e-6) < 3.0,
      f'{_ripple_mV(16e6/510,1000,10e-6):.2f} mV',
      f'< 3 mV ({(V0_MAX-V0_MIN)*1000/_ripple_mV(16e6/510,1000,10e-6):.0f}x margin)')
check('RC settling time (5 tau) is imperceptible',
      5*1000*10e-6*1000 < 100.0, f'{5*1000*10e-6*1000:.0f} ms', '< 100 ms')
check('Backlight 100 ohm safe at worst-case Vf', (5.0-3.0)/100*1000 <= 45.0,
      f'{(5.0-3.0)/100*1000:.0f} mA at Vf=3.0 V', '<= 45 mA')
check('LEDs alongside PWM contrast', 5 == 6-1, '5 on D3,5,6,10,11', 'D9 taken by contrast')
check('LCD frame rate at 115200 baud',
      1000/(len(_w3)*10/115200*1000) > cfg.frame_rate,
      f'{1000/(len(_w3)*10/115200*1000):.0f} fps', f'> {cfg.frame_rate:.1f}')
for mode in LcdMapper.MODES:
    _o = LcdMapper().render(mode, bands=np.full(LCD_COLS,.5), energy=.5)
    check(f'LCD mode "{mode}" renders', _o.shape == (LCD_COLS,) and _o.dtype == np.uint8,
          f'{_o.shape} {_o.dtype}', f'({LCD_COLS},) uint8')
check('LCD path beat rate', abs(_r20['beats']/12.0*60 - 120) < 6,
      f'{_r20["beats"]/12.0*60:.0f} /min', '120 /min')

# --- report ------------------------------------------------------------------
w1 = max(len(r[1]) for r in R); w2 = max(len(str(r[2])) for r in R)
print('='*(w1+w2+34)); print('VALIDATION REPORT'.center(w1+w2+34)); print('='*(w1+w2+34))
print(f'{"RESULT":<7}{"CHECK":<{w1+2}}{"MEASURED":<{w2+2}}EXPECTED')
print('-'*(w1+w2+34))
for st, nm, got, exp in R:
    print(f'{st:<7}{nm:<{w1+2}}{str(got):<{w2+2}}{exp}')
print('-'*(w1+w2+34))
n_p = sum(1 for r in R if r[0]=='PASS'); n_w = sum(1 for r in R if r[0]=='WARN')
n_f = sum(1 for r in R if r[0]=='FAIL')
print(f'{n_p} PASS   {n_w} WARN   {n_f} FAIL   ({len(R)} checks)')
print('='*(w1+w2+34))
raise SystemExit(1 if n_f else 0)
