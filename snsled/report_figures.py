"""Generate every figure the project report needs.  Run:  python -m snsled.report_figures"""
import os
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from .dsp import (Config, STFT, mel_filterbank, band_edges, AsymmetricEnvelope,
                  OnsetDetector, estimate_tempo, AGC)
from .leds import (lcd_char_grid, lcd_update_cost, LCD_COLS, LCD_ROWS,
                   LCD_PX, LCD_LEVELS)
from .runtime import (SyntheticSource, VirtualSink, VirtualPwmSink,
                      VirtualLcdSink, run)

plt.rcParams.update({'font.size': 9, 'axes.grid': True, 'grid.alpha': .3,
                     'figure.dpi': 130, 'savefig.bbox': 'tight',
                     'axes.spines.top': False, 'axes.spines.right': False})
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'figures')
C1, C2, C3 = '#1f77b4', '#d62728', '#2ca02c'


def fig1_uncertainty(cfg):
    """Time-frequency trade-off: the course's central idea, measured."""
    Ns = np.array([256, 512, 1024, 2048, 4096, 8192])
    df = cfg.fs / Ns; dt = 1000 * Ns / cfg.fs
    f, ax = plt.subplots(1, 2, figsize=(9, 3.2))
    ax[0].loglog(dt, df, 'o-', color=C1)
    for N, x, y in zip(Ns, dt, df):
        ax[0].annotate(f'N={N}', (x, y), textcoords='offset points',
                       xytext=(5, 6), fontsize=7)
    ax[0].scatter([1000*2048/cfg.fs], [cfg.fs/2048], s=140, facecolors='none',
                  edgecolors=C2, linewidths=2, zorder=5, label='chosen')
    ax[0].set(xlabel='window length $\\Delta t$ (ms)',
              ylabel='resolution $\\Delta f$ (Hz)',
              title='Time–frequency uncertainty')
    ax[0].legend(fontsize=8)
    ax[1].semilogx(Ns, dt/1000*df, 's-', color=C3)
    ax[1].axhline(1.0, ls='--', c='k', lw=.8)
    ax[1].set(xlabel='N', ylabel='$\\Delta t \\cdot \\Delta f$', ylim=(0, 2),
              title='Product is invariant  ($=1$ exactly)')
    f.savefig(f'{OUT}/fig01_uncertainty.png'); plt.close(f)


def fig2_window(cfg):
    """Hann vs rectangular: why the treble LEDs stay dark under a loud bass."""
    N = cfg.n_fft
    M = 1 << 17                      # zero-pad length -> smooth DTFT estimate
    # bin axis in ORIGINAL N-point DFT units: m * N / M
    bins = np.arange(M // 2 + 1) * N / M
    f, ax = plt.subplots(1, 2, figsize=(9, 3.2))
    for name, w, c in (('rectangular', np.ones(N), C2), ('Hann', np.hanning(N), C1)):
        ax[0].plot(np.arange(N)/cfg.fs*1000, w, color=c, label=name)
        W = np.abs(np.fft.rfft(w, M)); W /= W.max()
        keep = bins <= 8.5
        ax[1].plot(bins[keep], 20*np.log10(W[keep] + 1e-12), color=c, label=name)
    ax[0].set(xlabel='time (ms)', ylabel='amplitude', title=f'Window, N={N}')
    ax[0].legend(fontsize=8)
    ax[1].set(xlabel='frequency (bins)', ylabel='magnitude (dB)', ylim=(-100, 5),
              xlim=(0, 8), title='Spectral leakage\nHann side lobes −31 dB, roll-off −18 dB/oct')
    ax[1].legend(fontsize=8)
    f.savefig(f'{OUT}/fig02_window_leakage.png'); plt.close(f)


def fig3_spectrogram(cfg, x):
    st = STFT(cfg); S = st.offline(x)
    t = np.arange(S.shape[0]) * cfg.hop / cfg.fs
    fr = np.fft.rfftfreq(cfg.n_fft, 1/cfg.fs)
    f, ax = plt.subplots(figsize=(9, 3.4))
    m = ax.pcolormesh(t, fr, 20*np.log10(S.T + 1e-6), shading='auto',
                      cmap='magma', vmin=-40, vmax=30)
    ax.set(ylim=(0, 8000), xlabel='time (s)', ylabel='frequency (Hz)',
           title='STFT magnitude  (N=2048, hop=512, Hann)')
    for e in band_edges(cfg)[1:-1]:
        if e < 8000: ax.axhline(e, color='w', lw=.5, alpha=.45)
    f.colorbar(m, ax=ax, label='dB'); ax.grid(False)
    f.savefig(f'{OUT}/fig03_spectrogram.png'); plt.close(f)
    return S


def fig4_filterbank(cfg):
    fb = mel_filterbank(cfg)
    fr = np.fft.rfftfreq(cfg.n_fft, 1/cfg.fs)
    f, ax = plt.subplots(1, 2, figsize=(9, 3.2))
    for b in range(cfg.n_bands):
        ax[0].plot(fr, fb[b], lw=1.1)
        ax[1].semilogx(fr[1:], fb[b][1:], lw=1.1)
    ax[0].set(xlim=(0, 8000), xlabel='frequency (Hz)', ylabel='weight',
              title=f'Mel filter bank, {cfg.n_bands} bands (linear axis)')
    ax[1].set(xlim=(20, 16000), xlabel='frequency (Hz)',
              title='Same bank on a log axis — equal width')
    f.savefig(f'{OUT}/fig04_filterbank.png'); plt.close(f)


def fig5_envelope(cfg):
    """The LTI analysis: pole, frequency response, step response, and why
    the asymmetric version wins."""
    frn = cfg.frame_rate
    f, ax = plt.subplots(1, 3, figsize=(11.5, 3.4))

    # (a) frequency response for several alpha
    w = np.logspace(-3, np.log10(np.pi), 4000)
    for a, c in zip((0.12, 0.30, 0.50), (C1, C3, C2)):
        p = 1 - a
        H = a / np.abs(1 - p * np.exp(-1j * w))
        fc = AsymmetricEnvelope.cutoff_hz(a, frn)
        ax[0].semilogx(w * frn / (2 * np.pi), 20 * np.log10(H), color=c,
                       label=f'$\\alpha$={a:.2f},  $f_c$={fc:.2f} Hz')
        ax[0].plot(fc, -3, 'o', ms=4, color=c)
    ax[0].axhline(-3, ls='--', c='k', lw=.8)
    ax[0].text(0.115, -2.3, '\u22123 dB', fontsize=7)
    ax[0].set(xlabel='frequency (Hz)', ylabel='|H| (dB)',
              ylim=(-30, 3), xlim=(0.1, frn / 2),
              title='(a) One-pole IIR\n$H(z)=\\alpha\\,/\\,(1-(1-\\alpha)z^{-1})$')
    ax[0].legend(fontsize=7, loc='lower left')

    # (b) pole locations
    th = np.linspace(0, 2 * np.pi, 400)
    ax[1].plot(np.cos(th), np.sin(th), 'k-', lw=.9)
    ax[1].axhline(0, color='k', lw=.4, alpha=.4)
    ax[1].axvline(0, color='k', lw=.4, alpha=.4)
    for a, c in zip((0.12, 0.30, 0.50), (C1, C3, C2)):
        ax[1].plot(1 - a, 0, 'x', ms=12, mew=2.4, color=c,
                   label=f'$\\alpha$={a:.2f} $\\rightarrow$ pole {1-a:.2f}')
    ax[1].annotate('slower / smoother', xy=(0.88, 0.12), xytext=(0.30, 0.55),
                   fontsize=7, arrowprops=dict(arrowstyle='->', lw=.8))
    ax[1].set(xlim=(-1.2, 1.2), ylim=(-1.2, 1.2), aspect='equal',
              xlabel='Re$\\{z\\}$', ylabel='Im$\\{z\\}$',
              title='(b) Pole at $z=1-\\alpha$\n(always inside the unit circle $\\Rightarrow$ stable)')
    ax[1].legend(fontsize=6.5, loc='lower left')
    ax[1].grid(alpha=.25)

    # (c) step + release: symmetric vs asymmetric
    n = 200
    t = np.arange(n) / frn * 1000
    x = np.zeros(n); x[20:70] = 1.0
    ax[2].plot(t, x, color='0.55', lw=3.0, alpha=.55, label='input', zorder=1)
    for lbl, a, r, c in (('symmetric  $\\alpha$=0.12', .12, .12, C2),
                         ('asymmetric 1.00 / 0.12', 1.0, .12, C1)):
        y = np.zeros(n)
        for i in range(1, n):
            co = a if x[i] > y[i - 1] else r
            y[i] = y[i - 1] + co * (x[i] - y[i - 1])
        ax[2].plot(t, y, color=c, lw=1.6, label=lbl, zorder=3)
        if a < 1.0:
            rise = t[np.argmax(y > 0.9)] - t[20]
            ax[2].annotate(f'{rise:.0f} ms late', xy=(t[20] + rise, 0.9),
                           xytext=(t[20] + rise + 90, 0.62), fontsize=7, color=c,
                           arrowprops=dict(arrowstyle='->', color=c, lw=.9))
    ax[2].axvline(t[20], color='k', ls=':', lw=.8)
    ax[2].set(xlabel='time (ms)', ylabel='level', ylim=(-0.05, 1.18), xlim=(100, 1600),
              title='(c) Asymmetric: zero attack lag,\n91 ms release')
    ax[2].legend(fontsize=7, loc='upper right')
    f.savefig(f'{OUT}/fig05_envelope_lti.png'); plt.close(f)


def fig6_onset_tempo(cfg, S, true_bpm):
    odf = OnsetDetector.offline(S)
    fr  = cfg.frame_rate
    t   = np.arange(len(odf))/fr
    b1, b2 = estimate_tempo(odf, fr)

    f, ax = plt.subplots(2, 1, figsize=(9, 5.6), constrained_layout=True)
    ax[0].plot(t, odf, color=C1, lw=.9)
    for k in np.arange(0, t[-1], 60/true_bpm):
        ax[0].axvline(k, color=C2, ls='--', lw=.7, alpha=.65)
    ax[0].set(xlim=(0, 6), xlabel='time (s)', ylabel='ODF',
              title=f'Spectral-flux onset detection function\n(dashed = true beats at {true_bpm:.0f} BPM)')

    o = odf - odf.mean(); nn = len(o)
    ac = np.correlate(o, o, 'full')[nn-1:]; ac /= ac[0]
    lag = np.arange(len(ac))/fr
    m = (lag > .2) & (lag < 1.3)
    ax[1].plot(60/lag[m], ac[m], color=C3, lw=1.0, label='autocorrelation')
    grid = np.linspace(55, 240, 1200)
    ax[1].plot(grid, np.exp(-.5*(np.log2(grid/120)/.55)**2)*ac[m].max(),
               color='gray', ls=':', lw=1.2, label='perceptual prior (120 BPM)')
    for v, c, l in ((true_bpm, 'k', 'true'), (b1, C1, f'autocorr {b1:.1f}'),
                    (b2, C2, f'comb {b2:.1f}')):
        ax[1].axvline(v, color=c, ls='--', lw=1.0, label=l)
    ax[1].set(xlabel='tempo (BPM)', ylabel='normalised score', xlim=(55, 245),
              title='Tempo: the ODF holds the whole metrical hierarchy;\nthe prior selects the beat')
    ax[1].legend(fontsize=7, ncol=2)
    f.savefig(f'{OUT}/fig06_onset_tempo.png', bbox_inches=None); plt.close(f)
    return b1, b2


def fig7_led_waterfall(cfg, mode='bars'):
    sink = VirtualSink(cfg)
    run(SyntheticSource(cfg), sink, cfg, mode=mode, verbose=False, realtime=False)
    F = sink.as_array()
    f, ax = plt.subplots(figsize=(9, 3.6))
    ax.imshow(F.transpose(1, 0, 2), aspect='auto', origin='lower',
              extent=[0, F.shape[0]/cfg.frame_rate, 0, cfg.n_leds],
              interpolation='nearest')
    ax.set(xlabel='time (s)', ylabel='LED index', xlim=(0, 6),
           title=f'What the strip actually does — mode "{mode}", '
                 f'{cfg.n_leds} LEDs @ {cfg.frame_rate:.1f} fps')
    ax.grid(False)
    f.savefig(f'{OUT}/fig07_led_waterfall_{mode}.png'); plt.close(f)


def fig8_latency(cfg):
    items = [('onset detection (2 hops)',        2 * cfg.hop / cfg.fs * 1000),
             ('FFT + mel bank + envelope',       0.12),
             ('serial: READY + 180 B @ 1 Mbaud', 181 * 10 / 1e6 * 1000),
             ('WS2812B strobe, 60 LED + reset',  60 * 24 * 1.25 / 1000 + 0.280)]
    cols = [C1, C3, '#ff7f0e', C2]
    total = sum(v for _, v in items)

    f, ax = plt.subplots(figsize=(9, 3.6))
    left = 0.0
    for (lbl, v), c in zip(items, cols):
        ax.barh(0, v, left=left, height=0.42, color=c, edgecolor='w',
                label=f'{lbl}  —  {v:.2f} ms')
        if v / total > 0.15:                       # wide enough to label inside
            ax.text(left + v / 2, 0, f'{v:.2f} ms', ha='center', va='center',
                    fontsize=8, color='w', weight='bold')
        else:                                      # leader line above the bar
            ax.annotate(f'{v:.2f}', xy=(left + v / 2, 0.21),
                        xytext=(left + v / 2, 0.42 + 0.10 * (cols.index(c) % 2)),
                        ha='center', fontsize=7.5, color=c,
                        arrowprops=dict(arrowstyle='-', color=c, lw=.8))
        left += v

    ax.axvline(45, color='k', ls='--', lw=1.5)
    ax.text(45.7, 0.66, 'ITU-R BT.1359-1\ndetectability threshold\n(audio leading vision) = 45 ms',
            fontsize=7.5, va='top')
    ax.annotate('', xy=(total, -0.30), xytext=(45, -0.30),
                arrowprops=dict(arrowstyle='<->', color='k', lw=1.0))
    ax.text((total + 45) / 2, -0.40, f'margin {45 - total:.1f} ms',
            ha='center', fontsize=8)
    ax.set(xlim=(0, 56), ylim=(-0.75, 0.95), yticks=[], xlabel='latency (ms)',
           title=f'End-to-end audio \u2192 light latency = {total:.2f} ms   (PASS)')
    ax.legend(fontsize=7.5, loc='lower left', frameon=True, ncol=2)
    ax.grid(axis='x', alpha=.3)
    f.savefig(f'{OUT}/fig08_latency.png'); plt.close(f)
    return total


def fig9_pwm_channels(bpm=120.0):
    """What the six LEDs actually do -- the deliverable, plotted."""
    cfg6 = Config(n_bands=6)
    fig, axes = plt.subplots(2, 2, figsize=(11, 5.4), constrained_layout=True)
    pins = [3, 5, 6, 9, 10, 11]
    for ax, mode in zip(axes.ravel(), ('bands', 'vu', 'chase', 'sweep')):
        sink = VirtualPwmSink(6)
        run(SyntheticSource(cfg6), sink, cfg6, mode=mode,
            verbose=False, realtime=False, output='pwm')
        F = sink.as_array()
        t = np.arange(F.shape[0]) / cfg6.frame_rate
        im = ax.imshow(F.T, aspect='auto', origin='lower', cmap='inferno',
                       vmin=0, vmax=255,
                       extent=[0, t[-1], -0.5, 5.5], interpolation='nearest')
        for k in np.arange(0, 6, 60/bpm):
            ax.axvline(k, color='c', lw=.6, alpha=.45)
        ax.set(xlim=(0, 6), yticks=range(6),
               yticklabels=[f'D{p}' for p in pins],
               xlabel='time (s)', title=f'mode "{mode}"')
        ax.grid(False)
    fig.colorbar(im, ax=axes, label='PWM duty (0–255, gamma-corrected)',
                 shrink=.8)
    fig.suptitle('Six PWM LEDs on an Arduino Uno — cyan lines = true beats '
                 f'({bpm:.0f} BPM)', fontsize=10)
    fig.savefig(f'{OUT}/fig09_pwm_channels.png', bbox_inches=None)
    plt.close(fig)


def fig10_pwm_hardware():
    """PWM timing and the resistor choice, on one page."""
    F = 16e6
    fig, ax = plt.subplots(1, 2, figsize=(10, 3.4))

    # (a) PWM waveforms at three duty cycles
    f_slow = F / (64 * 510)
    T = 1000.0 / f_slow
    t = np.linspace(0, 3 * T, 3000)
    for k, (duty, c) in enumerate(zip((0.20, 0.55, 0.90), (C1, C3, C2))):
        sq = ((t % T) < duty * T).astype(float)
        ax[0].plot(t, sq * 0.8 + k * 1.05, color=c, lw=1.2,
                   label=f'duty {duty*100:.0f}%')
    ax[0].set(xlabel='time (ms)', yticks=[], ylim=(-0.2, 3.3),
              title=f'(a) 8-bit PWM at {f_slow:.1f} Hz (pins 3,9,10,11)\n'
                    f'period {T:.2f} ms — {f_slow/90:.1f}× the flicker threshold')
    ax[0].legend(fontsize=7, loc='center right')

    # (b) current vs resistor for common LED colours
    Rs = np.array([150, 220, 330, 470, 1000])
    for (name, vf), c in zip((('red', 1.8), ('green', 2.2), ('blue', 3.0)),
                             (C2, C3, C1)):
        ax[1].plot(Rs, (5.0 - vf) / Rs * 1000, 'o-', color=c, label=f'{name} (Vf {vf} V)')
    ax[1].axhline(20, ls='--', c='k', lw=.9)
    ax[1].text(1010, 20.6, '20 mA recommended', fontsize=7, ha='right')
    ax[1].axvline(220, ls=':', c='gray', lw=1.2)
    ax[1].text(232, 2, 'use 220 Ω', fontsize=7.5, color='gray')
    ax[1].set(xlabel='series resistor (Ω)', ylabel='LED current (mA)',
              ylim=(0, 24), title='(b) Current limiting from a 5 V pin')
    ax[1].legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(f'{OUT}/fig10_pwm_hardware.png')
    plt.close(fig)


def _lcd_pixels(grid, gap_tint=0.13):
    """Render a (4,20) character grid to the glass pixels (5x8 cells).

    0.0 = unlit (pale backlight), 1.0 = lit (dark), gap_tint = the thin
    inter-cell gutter a real module shows.
    """
    CW, CH, GAP = 5, 8, 1
    H = LCD_ROWS*(CH+GAP) - GAP
    W = LCD_COLS*(CW+GAP) - GAP
    img = np.full((H, W), gap_tint)
    for r in range(LCD_ROWS):
        for c in range(LCD_COLS):
            v = int(grid[r, c])
            cell = np.zeros((CH, CW))
            if 0 <= v <= 7:
                cell[CH-(v+1):, :] = 1.0          # CGRAM bar, filled from bottom
            elif v == ord('-'):
                cell[CH//2, :] = 1.0              # peak-hold marker
            img[r*(CH+GAP):r*(CH+GAP)+CH, c*(CW+GAP):c*(CW+GAP)+CW] = cell
    return img


def fig11_lcd():
    cfg20 = Config(n_bands=LCD_COLS)
    sink  = VirtualLcdSink(LCD_COLS, 6)
    run(SyntheticSource(cfg20), sink, cfg20, mode='spectrum',
        verbose=False, realtime=False, output='lcd')
    L = sink.lcd_only()

    fig = plt.figure(figsize=(11.5, 7.0), constrained_layout=True)
    gs  = fig.add_gridspec(3, 3, height_ratios=[0.95, 1.05, 1.15])

    for k, tsec in enumerate((0.51, 1.02, 2.26)):
        i  = int(tsec * cfg20.frame_rate)
        ax = fig.add_subplot(gs[0, k])
        # 'YlGn' (NOT reversed): 0 -> pale backlight, 1 -> dark pixel
        ax.imshow(_lcd_pixels(lcd_char_grid(L[i])), cmap='YlGn',
                  vmin=0.0, vmax=1.15, interpolation='nearest', aspect='equal')
        ax.set(xticks=[], yticks=[], title=f't = {tsec:.2f} s')
        ax.grid(False)
        for sp in ax.spines.values():
            sp.set_edgecolor('#444'); sp.set_linewidth(2.0)

    prev = np.full((LCD_ROWS, LCD_COLS), -1, dtype=np.int16)
    ch, ru = [], []
    for row in L[5:]:
        g = lcd_char_grid(row); a_, b_ = lcd_update_cost(g, prev)
        ch.append(a_); ru.append(b_); prev = g
    ch, ru = np.array(ch), np.array(ru)

    axh = fig.add_subplot(gs[1, :])
    axh.hist(ch, bins=np.arange(0, 82, 2), color=C1, edgecolor='w')
    axh.axvline(ch.mean(), color=C2, lw=1.8, label=f'mean {ch.mean():.1f} cells')
    axh.axvline(np.percentile(ch, 95), color='#ff7f0e', lw=1.4, ls='-.',
                label=f'p95 {np.percentile(ch,95):.0f} cells')
    axh.axvline(80, color='k', ls='--', lw=1.4, label='full redraw = 80 cells')
    axh.set(xlabel='cells changed per frame (of 80)', ylabel='frames', xlim=(0, 82),
            title=f'Differential redraw costs {80/ch.mean():.1f}× less than a full screen')
    axh.legend(fontsize=8)

    axf = fig.add_subplot(gs[2, :])
    T = 37e-6
    cases = [('4-bit parallel\ndirect port', T),
             ('4-bit parallel\nLiquidCrystal', T*2.5),
             ('I2C backpack\n400 kHz', 135e-6),
             ('I2C backpack\n100 kHz (Wire default)', 540e-6)]
    vals = [1.0/(np.percentile(ch,95)*pc + np.percentile(ru,95)*pc) for _, pc in cases]
    cols = [C3 if v > cfg20.frame_rate else C2 for v in vals]
    bars = axf.bar([n for n, _ in cases], vals, color=cols, edgecolor='w', width=.62)
    axf.axhline(cfg20.frame_rate, color='k', ls='--', lw=1.5)
    axf.text(-0.44, cfg20.frame_rate*1.15, f'{cfg20.frame_rate:.0f} fps needed', fontsize=8)
    for b_, v in zip(bars, vals):
        axf.text(b_.get_x()+b_.get_width()/2, v*1.14, f'{v:.0f} fps',
                 ha='center', fontsize=8.5, weight='bold')
    axf.set(yscale='log', ylabel='achievable fps (p95 frame)', ylim=(12, 2200),
            title='Every interface keeps up except the default 100 kHz I2C clock — '
                  'Wire.setClock(400000) fixes it')
    fig.savefig(f'{OUT}/fig11_lcd.png', bbox_inches=None)
    plt.close(fig)


def main():
    os.makedirs(OUT, exist_ok=True)
    cfg = Config(n_leds=60)
    src = SyntheticSource(cfg)
    x   = src.x
    print('generating figures...')
    fig1_uncertainty(cfg);            print('  fig01 uncertainty')
    fig2_window(cfg);                 print('  fig02 window / leakage')
    S = fig3_spectrogram(cfg, x);     print('  fig03 spectrogram')
    fig4_filterbank(cfg);             print('  fig04 mel filter bank')
    fig5_envelope(cfg);               print('  fig05 envelope LTI analysis')
    b1, b2 = fig6_onset_tempo(cfg, S, src.bpm); print(f'  fig06 onset/tempo -> {b1:.2f}/{b2:.2f} BPM')
    for m in ('bars', 'centroid', 'pulse'):
        fig7_led_waterfall(cfg, m);   print(f'  fig07 LED waterfall ({m})')
    lat = fig8_latency(cfg);          print(f'  fig08 latency -> {lat:.2f} ms')
    fig9_pwm_channels();              print('  fig09 PWM channels (6 LEDs)')
    fig10_pwm_hardware();             print('  fig10 PWM timing + resistors')
    fig11_lcd();                      print('  fig11 LCD render + redraw cost')
    print(f'\nall figures written to {OUT}')
    return b1, b2, lat


if __name__ == '__main__':
    main()
