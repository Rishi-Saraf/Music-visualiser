"""Generate the wiring diagram.  python -m snsled.wiring_figure"""
import os
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Rectangle

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'figures')

# (lcd_pin, lcd_label, arduino_target, wire_colour, note)
ROWS = [
    (1,  'VSS', 'GND',      '#333333', ''),
    (2,  'VDD', '5V',       '#d62728', ''),
    (3,  'V0',  'pin 9',    '#9467bd', 'via 1k, + 10uF to GND'),
    (4,  'RS',  'pin 12',   '#1f77b4', ''),
    (5,  'RW',  'GND',      '#333333', ''),
    (6,  'E',   'pin 13',   '#1f77b4', ''),
    (7,  'D0',  None,       '#bbbbbb', 'not connected'),
    (8,  'D1',  None,       '#bbbbbb', 'not connected'),
    (9,  'D2',  None,       '#bbbbbb', 'not connected'),
    (10, 'D3',  None,       '#bbbbbb', 'not connected'),
    (11, 'D4',  'pin 8',    '#2ca02c', ''),
    (12, 'D5',  'pin 7',    '#2ca02c', ''),
    (13, 'D6',  'pin 4',    '#2ca02c', ''),
    (14, 'D7',  'pin 2',    '#2ca02c', ''),
    (15, 'A',   '5V',       '#ff7f0e', 'via 100 ohm'),
    (16, 'K',   'GND',      '#333333', ''),
]

def main():
    os.makedirs(OUT, exist_ok=True)
    fig, ax = plt.subplots(figsize=(11, 7.6))
    ax.set_xlim(0, 10); ax.set_ylim(-1.1, 17.6); ax.axis('off')

    ax.add_patch(FancyBboxPatch((0.35, 0.35), 2.5, 16.4, boxstyle='round,pad=0.06',
                                fc='#eef4ee', ec='#2d5a2d', lw=2))
    ax.text(1.6, 17.1, 'RG2004A  (20x4 LCD)', ha='center', fontsize=11, weight='bold')
    ax.add_patch(FancyBboxPatch((7.1, 0.35), 2.5, 16.4, boxstyle='round,pad=0.06',
                                fc='#eaf1f8', ec='#1f4e79', lw=2))
    ax.text(8.35, 17.1, 'ARDUINO UNO', ha='center', fontsize=11, weight='bold')

    for i, (num, label, tgt, col, note) in enumerate(ROWS):
        y = 16.1 - i * 0.99
        dim = tgt is None
        ax.add_patch(Rectangle((0.5, y-0.26), 2.2, 0.52,
                               fc='#ffffff' if not dim else '#f6f6f6',
                               ec='#999' if dim else '#2d5a2d', lw=1.1))
        ax.text(0.72, y, f'{num:>2}', fontsize=9, va='center',
                color='#999' if dim else '#444', weight='bold')
        is_bus = label in ('D4', 'D5', 'D6', 'D7')
        ax.text(1.24, y, label, fontsize=10, va='center',
                color='#999' if dim else ('#c0392b' if is_bus else '#111'),
                weight='normal' if dim else 'bold')
        if is_bus:
            ax.text(2.55, y, 'LCD bus', fontsize=6.8, va='center',
                    ha='right', color='#c0392b', style='italic')

        if dim:
            ax.text(5.0, y, 'leave unconnected', ha='center', fontsize=8.5,
                    color='#999', style='italic')
            continue

        ax.plot([2.75, 7.05], [y, y], color=col, lw=2.0, solid_capstyle='round',
                zorder=1)
        ax.add_patch(Rectangle((7.05, y-0.26), 2.4, 0.52, fc='#ffffff',
                               ec='#1f4e79', lw=1.1, zorder=2))
        ax.text(7.25, y, tgt, fontsize=10, va='center', weight='bold', zorder=3)
        if note:
            ax.text(4.9, y + 0.26, note, ha='center', fontsize=7.6, color=col,
                    style='italic', zorder=3,
                    bbox=dict(fc='white', ec='none', pad=0.9))

    ax.text(5.0, -0.55,
            'LCD pins 11-14 are LABELLED D4-D7 — they are the LCD\'s data bus, '
            'NOT Arduino pins D4-D7.\n'
            'LCD "D4" goes to Arduino pin 8.   Arduino pin 4 receives LCD "D6".',
            ha='center', fontsize=9, color='#c0392b', weight='bold',
            bbox=dict(fc='#fdf0ee', ec='#c0392b', lw=1.2,
                      boxstyle='round,pad=0.5'))
    fig.savefig(f'{OUT}/fig12_wiring.png', dpi=140, bbox_inches='tight')
    plt.close(fig)
    print(f'wrote {OUT}/fig12_wiring.png')


if __name__ == '__main__':
    main()
