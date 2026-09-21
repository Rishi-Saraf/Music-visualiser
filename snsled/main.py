"""Command-line entry point.  python -m snsled.main --help"""
import argparse, sys
import numpy as np
from .dsp import Config
from .runtime import (FileSource, MicSource, SyntheticSource, SerialSink,
                      VirtualSink, PwmSink, VirtualPwmSink,
                      LcdSink, VirtualLcdSink, AudioPlayer, run)
from .leds import LedMapper, PwmMapper, LcdMapper, UNO_PWM_PINS, LCD_COLS


def _not_a_board(port):
    """Return a description if `port` exists but does not look like an Arduino.

    Opening a Bluetooth COM port succeeds, writes to it succeed, and every
    frame is discarded -- so a blank LCD is indistinguishable from a working
    run.  No exception is ever raised, which is exactly why this has to be
    checked up front rather than handled.
    """
    try:
        from serial.tools import list_ports
    except ImportError:
        return None
    for p in list_ports.comports():
        if p.device.lower() != str(port).lower(): continue
        blob = ((p.description or '') + ' ' + (p.manufacturer or '')).lower()
        if any(k in blob for k in ('arduino', 'ch340', 'ch341',
                                   'usb-serial', 'wch', 'ftdi')):
            return None
        return p.description or p.device
    return None


def _device(s):
    """--audio-device / --audio-latency take a number or a word."""
    try: return int(s)
    except ValueError: pass
    try: return float(s)
    except ValueError: return s


def build_argparser():
    p = argparse.ArgumentParser(
        prog='snsled', description='Audio -> LED visualiser (Signals & Systems project)')
    p.add_argument('--source',  default='synthetic',
                   help="'synthetic', 'mic', or a path to a .wav file")
    p.add_argument('--port',    default=None,
                   help='Arduino serial port (e.g. COM3, /dev/ttyACM0). '
                        'Omit to run with a virtual strip.')
    p.add_argument('--output',  default='lcd', choices=('lcd', 'pwm', 'strip'),
                   help="'lcd' = 20x4 character LCD as a 20-band analyser "
                        "(default, + 6 optional PWM LEDs); 'pwm' = 6 LEDs "
                        "only; 'strip' = WS2812B")
    p.add_argument('--leds-on-lcd', type=int, default=5,
                   help='how many PWM LEDs alongside the LCD (0 = none). '
                        '5 when D9 drives software contrast, 6 without it.')
    p.add_argument('--contrast', type=int, default=26,
                   help='V0 contrast code sent every frame. 5V*n/255 must '
                        'land in 0.40-0.60 V, so use 23-30. Default 26 = '
                        '0.51 V. Ignored if you fitted a resistor divider.')
    p.add_argument('--baud',    type=int, default=None,
                   help='default 115200 for lcd/pwm, 1000000 for strip')
    p.add_argument('--leds',    type=int, default=60,
                   help='strip only: must match NUM_LEDS in the sketch')
    p.add_argument('--mode',    default=None,
                   help=f'lcd: {"/".join(LcdMapper.MODES)}  |  '
                        f'pwm: {"/".join(PwmMapper.MODES)}  |  '
                        f'strip: {"/".join(LedMapper.MODES)}')
    p.add_argument('--bands',   type=int, default=None,
                   help='default 20 for lcd (one per column), 6 for pwm, '
                        '8 for strip')
    p.add_argument('--nfft',    type=int, default=2048)
    p.add_argument('--hop',     type=int, default=512)
    p.add_argument('--attack',  type=float, default=1.00)
    p.add_argument('--release', type=float, default=0.12)
    p.add_argument('--beat-sensitivity', type=float, default=0.35,
                   help='onset event threshold as a fraction of the running '
                        'ODF peak. 0.35 locks to the beat, 0.15 to the tatum. '
                        'Values near 0.25 fall between metrical levels and '
                        'look irregular -- see OnsetEvents in dsp.py.')
    p.add_argument('--no-audio', action='store_true',
                   help='process the track without playing it. Playback is on '
                        'by default for files and the synthetic track, and '
                        'always off for --source mic (it would feed back).')
    p.add_argument('--volume',  type=float, default=1.0,
                   help='playback gain, 0-1. Affects the speakers only -- the '
                        'FFT always sees the peak-normalised signal, so '
                        'turning it down does not dim the display.')
    p.add_argument('--av-offset', type=float, default=0.0, metavar='MS',
                   help='trim the audio/video alignment by hand. The output '
                        'buffer is already compensated; positive holds the '
                        'lights back, negative pushes them forward. One frame '
                        'is 11.6 ms, so that is the resolution.')
    p.add_argument('--audio-device', type=_device, default=None,
                   help='output device index or name substring '
                        '(python -m sounddevice lists them). Default: system.')
    p.add_argument('--audio-latency', type=_device, default='high',
                   help="'high' (default, robust), 'low', or seconds. Buffer "
                        'size, not sync error -- whatever it is, the lights '
                        'are delayed to match it.')
    p.add_argument('--max-amps', type=float, default=2.4,
                   help='brightness is scaled so the strip never exceeds this')
    p.add_argument('--seconds', type=float, default=12.0,
                   help='length of the synthetic test track')
    return p


def main(argv=None):
    a = build_argparser().parse_args(argv)
    pwm, lcd = (a.output == 'pwm'), (a.output == 'lcd')
    if a.bands is None: a.bands = LCD_COLS if lcd else (6 if pwm else 8)
    if a.baud  is None: a.baud  = 1000000 if a.output == 'strip' else 115200
    if a.mode  is None: a.mode  = 'spectrum' if lcd else ('bands' if pwm else 'bars')
    valid = (LcdMapper.MODES if lcd else
             PwmMapper.MODES if pwm else LedMapper.MODES)
    if a.mode not in valid:
        print(f'  ! mode {a.mode!r} is not valid for --output {a.output}; '
              f'choose from {", ".join(valid)}', file=sys.stderr)
        return 2
    cfg = Config(n_fft=a.nfft, hop=a.hop, n_bands=a.bands, n_leds=a.leds,
                 attack=a.attack, release=a.release)

    print(f'  N={cfg.n_fft} hop={cfg.hop}  df={cfg.df:.2f} Hz  '
          f'{cfg.frame_rate:.1f} fps  bands={cfg.n_bands}  mode={a.mode}')
    if pwm:
        print(f'  output: {cfg.n_bands} PWM LEDs on pins '
              f'{", ".join("D"+str(x) for x in UNO_PWM_PINS[:cfg.n_bands])}')
    elif lcd:
        print(f'  output: 20x4 character LCD, {LCD_COLS} bars x 32 levels'
              + (f' + {a.leds_on_lcd} PWM LEDs' if a.leds_on_lcd else ''))

    if a.source == 'synthetic':
        src = SyntheticSource(cfg, seconds=a.seconds)
        print(f'  source: synthetic test track, {src.bpm:.0f} BPM, {a.seconds:.0f} s')
    elif a.source == 'mic':
        try:
            src = MicSource(cfg)
        except Exception as e:
            print(f'  ! microphone unavailable ({e}); install sounddevice', file=sys.stderr)
            return 2
        print('  source: live microphone  (Ctrl-C to stop)')
    else:
        src = FileSource(a.source, cfg)
        print(f'  source: {a.source}  ({src.duration:.1f} s)')

    def virtual():
        if lcd: return VirtualLcdSink(LCD_COLS, a.leds_on_lcd, keep=False)
        if pwm: return VirtualPwmSink(cfg.n_bands, keep=False)
        return VirtualSink(cfg, keep=False)

    if a.port:
        odd = _not_a_board(a.port)
        if odd:
            print(*[f'',
                    f'  !! {a.port} is "{odd}" -- that is not a board.',
                    f'  !! It will open, accept every frame and discard them '
                    f'all, so the',
                    f'  !! LCD stays blank while the bars and the audio look '
                    f'perfectly normal.',
                    f'  !! Run "python find_port.py" and use the port it '
                    f'marks as your Arduino.',
                    f''], sep=chr(10), file=sys.stderr)
        try:
            if lcd:
                sink = LcdSink(a.port, LCD_COLS, a.leds_on_lcd,
                               baud=a.baud, contrast=a.contrast)
            elif pwm:
                sink = PwmSink(a.port, n_ch=cfg.n_bands, baud=a.baud)
            else:
                sink = SerialSink(a.port, cfg, baud=a.baud)
            print(f'  sink:   {a.port} @ {a.baud} baud')
        except Exception as e:
            # Falling back quietly here is how a blank LCD looks exactly like
            # a working run: bands still scroll, audio still plays, and
            # nothing ever reaches the glass.  Say so loudly.
            msg = [f'',
                   f'  !! CANNOT OPEN {a.port} -- NOTHING WILL REACH THE LCD !!',
                   f'  !! {e}',
                   f'  !! usually: the Arduino IDE Serial Monitor is open on '
                   f'{a.port}, or',
                   f'  !!          another copy of this program is still running, or',
                   f'  !!          {a.port} is not the board -- run '
                   f'"python find_port.py"',
                   f'  !! continuing with virtual output so the DSP still runs.',
                   f'']
            print(*msg, sep=chr(10), file=sys.stderr)
            sink = virtual()
    else:
        sink = virtual()
        print('  sink:   virtual -- no --port given, so THE LCD GETS NOTHING. '
              'Add --port COM3 (see: python find_port.py)')

    player = None
    if a.no_audio:
        pass
    elif a.source == 'mic':
        print('  audio:  playback off -- monitoring a live mic would feed back')
    else:
        try:
            nch = getattr(src, 'stereo', np.empty((0, 1))).shape[1]
            player = AudioPlayer(cfg, volume=a.volume, offset_ms=a.av_offset,
                                 device=a.audio_device, latency=a.audio_latency,
                                 channels=nch)
            print(f'  audio:  playing out of the sound card in '
                  f'{"stereo" if nch == 2 else str(nch) + " ch"}; '
                  f'{player.lag_s*1000:.0f} ms of output buffer, so frames are '
                  f'held {player.delay} hops '
                  f'({player.delay*cfg.hop_ms:.0f} ms) to land on their own '
                  f'audio')
        except Exception as e:
            print(f'  ! no playback ({e}); pip install sounddevice. '
                  f'Running silently.', file=sys.stderr)

    run(src, sink, cfg, mode=a.mode, max_amps=a.max_amps, output=a.output,
        beat_sensitivity=a.beat_sensitivity, player=player)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
