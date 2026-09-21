"""Draw the contrast circuit.  python -m snsled.contrast_figure"""
import os
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'figures')
INK, WIRE = '#111111', '#1f4e79'


# ---- schematic primitives ---------------------------------------------------
def wire(ax, pts, c=WIRE, lw=2.0):
    p = np.asarray(pts, float)
    ax.plot(p[:, 0], p[:, 1], color=c, lw=lw, solid_capstyle='round', zorder=2)


def resistor(ax, x, y, w=1.05, h=0.17, label='', horiz=True):
    """Zigzag resistor centred at (x, y)."""
    n = 6
    if horiz:
        xs = np.linspace(x - w/2, x + w/2, 2*n + 1)
        ys = np.full_like(xs, y)
        ys[1:-1:2] = y + h
        ys[2:-1:2] = y - h
    else:
        ys = np.linspace(y - w/2, y + w/2, 2*n + 1)
        xs = np.full_like(ys, x)
        xs[1:-1:2] = x + h
        xs[2:-1:2] = x - h
    ax.plot(xs, ys, color=INK, lw=2.0, solid_capstyle='round', zorder=3)
    if label:
        if horiz: ax.text(x, y + h + 0.16, label, ha='center', fontsize=10, weight='bold')
        else:     ax.text(x + h + 0.14, y, label, va='center', fontsize=10, weight='bold')


def cap_polarised(ax, x, y, label='', plate=0.34, gap=0.15):
    """Electrolytic: straight top plate (+), curved bottom plate (-)."""
    ax.plot([x-plate, x+plate], [y+gap, y+gap], color=INK, lw=2.6, zorder=3)
    th = np.linspace(np.pi*0.18, np.pi*0.82, 60)
    ax.plot(x + plate*1.05*np.cos(th), (y-gap-0.13) + 0.20*np.sin(th),
            color=INK, lw=2.6, zorder=3)
    ax.text(x - plate - 0.16, y + gap + 0.05, '+', fontsize=13,
            weight='bold', color='#c0392b', ha='center', va='center')
    if label:
        ax.text(x + plate + 0.20, y, label, va='center', fontsize=10, weight='bold')


def ground(ax, x, y):
    for i, w in enumerate((0.34, 0.22, 0.10)):
        ax.plot([x-w, x+w], [y - i*0.13, y - i*0.13], color=INK, lw=2.4, zorder=3)


def node(ax, x, y):
    ax.plot([x], [y], 'o', ms=6.5, color=WIRE, zorder=4)


def pin(ax, x, y, text, ha='right', fc='#eaf1f8', ec='#1f4e79'):
    ax.text(x, y, text, ha=ha, va='center', fontsize=10.5, weight='bold',
            bbox=dict(fc=fc, ec=ec, lw=1.6, boxstyle='round,pad=0.42'), zorder=5)


# ---- the figure -------------------------------------------------------------
def main():
    os.makedirs(OUT, exist_ok=True)
    fig = plt.figure(figsize=(12, 8.6))
    gs  = fig.add_gridspec(2, 2, height_ratios=[1.0, 1.05], hspace=0.42, wspace=0.28)

    # ===== Option A: PWM + RC =================================================
    ax = fig.add_subplot(gs[0, 0]); ax.set_xlim(0, 10); ax.set_ylim(0, 5.6); ax.axis('off')
    ax.set_title('OPTION A  —  software contrast (recommended)',
                 fontsize=11.5, weight='bold', pad=12)
    yt = 4.0
    pin(ax, 2.25, yt, 'Arduino\npin 9', ha='right')
    wire(ax, [(2.35, yt), (3.6, yt)])
    resistor(ax, 4.2, yt, label='1 kΩ')
    wire(ax, [(4.8, yt), (6.6, yt)])
    node(ax, 6.6, yt)
    wire(ax, [(6.6, yt), (7.7, yt)])
    pin(ax, 7.8, yt, 'LCD pin 3\n(V0)', ha='left', fc='#eef4ee', ec='#2d5a2d')
    wire(ax, [(6.6, yt), (6.6, 2.5)])
    cap_polarised(ax, 6.6, 2.35, label='10 µF')
    wire(ax, [(6.6, 1.95), (6.6, 1.5)])
    ground(ax, 6.6, 1.5)
    ax.text(6.6, 0.85, 'GND', ha='center', fontsize=9.5, weight='bold')
    ax.text(4.2, 4.95, '31.4 kHz PWM in', ha='center', fontsize=9,
            style='italic', color='#7f4bb5')
    ax.text(8.1, 4.95, '0.51 V DC out', ha='center', fontsize=9,
            style='italic', color='#2ca02c')
    ax.text(2.4, 2.35,
            'R and C average the\npulses into a steady\nvoltage. Change the\n'
            'duty in software and\nthe contrast changes.',
            ha='center', va='center', fontsize=8.6, color='#444', linespacing=1.5)

    # ===== Option B: fixed divider ===========================================
    ax = fig.add_subplot(gs[0, 1]); ax.set_xlim(0, 10); ax.set_ylim(0, 5.6); ax.axis('off')
    ax.set_title('OPTION B  —  fixed divider (no code, not adjustable)',
                 fontsize=11.5, weight='bold', pad=12)
    xm = 4.3
    pin(ax, xm, 5.05, 'Arduino 5V', ha='center')
    wire(ax, [(xm, 4.78), (xm, 4.35)])
    resistor(ax, xm, 3.85, w=0.95, label='10 kΩ', horiz=False)
    wire(ax, [(xm, 3.35), (xm, 2.85)])
    node(ax, xm, 2.85)
    wire(ax, [(xm, 2.85), (6.5, 2.85)])
    pin(ax, 6.6, 2.85, 'LCD pin 3\n(V0)', ha='left', fc='#eef4ee', ec='#2d5a2d')
    wire(ax, [(xm, 2.85), (xm, 2.35)])
    resistor(ax, xm, 1.85, w=0.95, label='1 kΩ', horiz=False)
    wire(ax, [(xm, 1.35), (xm, 1.0)])
    ground(ax, xm, 1.0)
    ax.text(xm, 0.4, 'GND', ha='center', fontsize=9.5, weight='bold')
    ax.text(1.75, 2.85, 'V0 = 5 V ×\n1k/(10k+1k)\n= 0.455 V', ha='center',
            fontsize=9, color='#2ca02c', weight='bold')

    # ===== waveform: what the filter actually does ============================
    f_pwm, duty, R, C = 16e6/510, 26/255, 1000.0, 10e-6
    T, tau = 1.0/f_pwm, R*C
    # Simulate 10 time constants so the capacitor is genuinely settled, then
    # measure ripple over the LAST few PWM periods only -- measuring across a
    # wider window would capture the residual exponential drift, not ripple.
    from scipy.signal import lfilter
    dt = T/400
    n  = int(10*tau/dt)
    t  = np.arange(n)*dt
    sq = 5.0*((t % T) < duty*T)
    a  = dt/tau
    y  = lfilter([a], [1.0, -(1.0-a)], sq)        # exact for y[n]=(1-a)y[n-1]+a x[n]
    last = y[-int(5*T/dt):]                       # final 5 PWM periods
    mean_v, ripple_mV = last.mean(), (last.max()-last.min())*1000
    # closed form for T << tau:  dV = Vcc * d * (1-d) * T / tau
    ripple_pred = 5.0*duty*(1-duty)*T/tau*1000

    axL = fig.add_subplot(gs[1, 0])
    axL.plot(t*1000, y, color='#2ca02c', lw=2.0)
    axL.axhspan(0.40, 0.60, color='#2ca02c', alpha=0.13, zorder=0)
    axL.axhline(5*duty, color='#2ca02c', ls='--', lw=1.0)
    for k in (1, 3, 5):
        axL.axvline(k*tau*1000, color='#bbb', ls=':', lw=1.0)
        axL.text(k*tau*1000, 0.03, f'{k}τ', fontsize=8, ha='center', color='#666')
    axL.set(xlabel='time (ms)', ylabel='V0 (volts)', xlim=(0, 6*tau*1000),
            ylim=(0, 0.62),
            title=f'Charging up: τ = RC = {tau*1000:.0f} ms,\nsettled after ~5τ = {5*tau*1000:.0f} ms')
    axL.text(3.3*tau*1000, 0.5*duty*5*0.55,
             f'settles at 5 V × {duty*100:.1f}% = {5*duty:.3f} V',
             fontsize=9, color='#2ca02c', weight='bold')

    axR = fig.add_subplot(gs[1, 1])
    i0 = n - int(4*T/dt); i1 = n
    tz = (t[i0:i1] - t[i0])*1e6
    axR.plot(tz, sq[i0:i1], color='#9467bd', lw=1.4,
             label='pin 9: 5 V pulses @ 31.4 kHz')
    axR.plot(tz, y[i0:i1], color='#2ca02c', lw=2.8, label='V0: smooth DC')
    axR.set(xlabel='time (µs)', ylabel='volts', ylim=(-0.35, 5.6),
            title=f'Zoomed in at steady state: ripple is only {ripple_mV:.2f} mV\n'
                  f'on a {mean_v:.3f} V bias — {200/ripple_mV:.0f}× inside the window')
    axR.legend(fontsize=8.5, loc='center right')
    ax2 = axR.twinx()
    ax2.plot(tz, y[i0:i1]*1000, color='#2ca02c', lw=0)
    ax2.set_ylabel('V0 (mV)', color='#2ca02c')
    ax2.set_ylim(-350, 5600)

    fig.savefig(f'{OUT}/fig13_contrast_circuit.png', dpi=140, bbox_inches='tight')
    plt.close(fig)
    print(f'wrote {OUT}/fig13_contrast_circuit.png')
    print(f'  R={R:.0f} ohm  C={C*1e6:.0f} uF  ->  tau={R*C*1000:.1f} ms  '
          f'fc={1/(2*np.pi*R*C):.2f} Hz')
    print(f'  PWM {f_pwm:.0f} Hz, duty {duty*100:.1f}%  ->  predicted mean {5*duty:.3f} V')
    print(f'  simulated steady-state mean   : {mean_v:.4f} V')
    print(f'  simulated peak-to-peak ripple : {ripple_mV:.3f} mV')
    print(f'  closed form  d(1-d)T/tau      : {ripple_pred:.3f} mV')
    print(f'  agreement                     : '
          f'{abs(ripple_mV-ripple_pred)/ripple_pred*100:.1f}%')
    print(f'  settling time (5 tau)         : {5*tau*1000:.0f} ms')


if __name__ == '__main__':
    main()
