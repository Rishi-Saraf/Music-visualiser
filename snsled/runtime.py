"""Audio sources, LED sinks, and the real-time loop."""
import sys, time
from collections import deque
import numpy as np
from .dsp  import (Config, STFT, mel_filterbank, AsymmetricEnvelope, AGC,
                   OnsetDetector, spectral_centroid, estimate_tempo,
                   OnsetEvents, AdaptiveRange, rms_db)
from .leds import (LedMapper, power_estimate, PwmMapper, pwm_current_ma,
                   LcdMapper, GAMMA8, LCD_COLS)

# =============================== audio sources ===============================
class FileSource:
    """Mono float32 audio from a .wav file, delivered in `hop`-sized blocks.

    A stereo copy is kept on exactly the same resampled timeline for playback.
    The analysis path is unchanged -- mono, because a filter bank of a
    left/right sum is what a single row of bars can represent -- but the
    speakers get both channels.  Resampling both together, off the same index,
    is what keeps sound and light sample-aligned; resampling the playback copy
    separately at its native rate would need a second clock.
    """
    def __init__(self, path, cfg: Config):
        try:
            import soundfile as sf
            ch, fs = sf.read(path, dtype='float32', always_2d=True)
        except ImportError:
            from scipy.io import wavfile
            fs, raw = wavfile.read(path)
            ch = raw.astype(np.float32)
            if ch.ndim == 1: ch = ch[:, None]
            if np.issubdtype(raw.dtype, np.integer):
                ch /= float(np.iinfo(raw.dtype).max)
        if fs != cfg.fs:
            k   = int(round(len(ch) * cfg.fs / fs))
            src = np.arange(len(ch)); dst = np.linspace(0, len(ch) - 1, k)
            ch  = np.stack([np.interp(dst, src, c) for c in ch.T], axis=1)
        x = ch.mean(axis=1)
        m = np.max(np.abs(x))
        self.x, self.cfg, self.i = (x / m if m > 0 else x), cfg, 0
        ms = np.max(np.abs(ch))
        self.stereo = np.ascontiguousarray(ch / ms if ms > 0 else ch,
                                           dtype=np.float32)
        self.realtime = True

    def __iter__(self): return self
    def __next__(self):
        h = self.cfg.hop
        if self.i + h > len(self.x): raise StopIteration
        b = self.x[self.i:self.i + h]; self.i += h
        return b

    def playback_block(self):
        """The same hop the caller just took, but with its channels intact."""
        h = self.cfg.hop
        return self.stereo[self.i - h:self.i]

    @property
    def duration(self): return len(self.x) / self.cfg.fs


class MicSource:
    """Live microphone input via sounddevice."""
    def __init__(self, cfg: Config, device=None):
        import sounddevice as sd
        self.cfg, self.sd = cfg, sd
        self.stream = sd.InputStream(samplerate=cfg.fs, channels=1,
                                     blocksize=cfg.hop, dtype='float32',
                                     device=device)
        self.stream.start()
        self.realtime = False            # the stream already paces us
    def __iter__(self): return self
    def __next__(self):
        b, over = self.stream.read(self.cfg.hop)
        return b[:, 0]
    def close(self): self.stream.stop(); self.stream.close()


class SyntheticSource:
    """Deterministic test track -- lets the whole pipeline run with no audio
    hardware and no files.  Kick + bass + offbeat hats at a known BPM."""
    def __init__(self, cfg: Config, bpm=120.0, seconds=12.0, seed=7):
        rng  = np.random.default_rng(seed)
        fs   = cfg.fs; n = int(fs * seconds); beat = 60.0 / bpm
        x    = np.zeros(n)
        for k in range(int(seconds / beat)):                       # kick
            i = int(k * beat * fs); L = int(0.18 * fs)
            e = np.exp(-np.arange(L) / (0.045 * fs))
            x[i:i+L] += 0.9 * e * np.sin(2*np.pi*55*np.arange(L)/fs)
        for k in range(int(seconds / (beat/2))):                   # hats
            i = int((k*beat/2 + beat/2) * fs); L = int(0.05*fs)
            if i+L < n:
                e = np.exp(-np.arange(L)/(0.012*fs)); z = rng.standard_normal(L)
                z = z - np.convolve(z, np.ones(9)/9, 'same')
                x[i:i+L] += 0.30 * e * z
        for k, f0 in enumerate([110, 110, 146.83, 164.81] * 64):   # bass
            i = int(k*beat*fs); L = int(0.42*fs)
            if i+L >= n: break
            e = np.exp(-np.arange(L)/(0.25*fs))
            x[i:i+L] += 0.35 * e * np.sin(2*np.pi*f0*np.arange(L)/fs)
        x += 0.004 * rng.standard_normal(n)
        self.x, self.cfg, self.i, self.bpm = x/np.max(np.abs(x)), cfg, 0, bpm
        self.realtime = True
    def __iter__(self): return self
    def __next__(self):
        h = self.cfg.hop
        if self.i + h > len(self.x): raise StopIteration
        b = self.x[self.i:self.i+h]; self.i += h
        return b
    @property
    def duration(self): return len(self.x) / self.cfg.fs


# =============================== audio playback ==============================
class AudioPlayer:
    """Plays the track out of the sound card *and* clocks the frame loop.

    Two independent things have to be right before lights look synchronised:

    *Rate.*  ``OutputStream.write()`` blocks until the card has room for the
    next hop, so the loop runs on the sound card's crystal instead of on
    ``perf_counter()``.  Nothing trims one clock to the other, so a
    free-running sleep loop drifts: 100 ppm between the two oscillators is
    18 ms over a 3-minute track, all of it in one direction.

    *Phase.*  What the DAC is playing right now was handed to it
    ``stream.latency`` seconds ago, so lighting frame k the instant block k is
    written puts the display a whole output buffer *ahead* of the sound --
    ~90 ms with the default high-latency setting, twice the 45 ms ITU-R
    BT.1359-1 threshold and in the direction the eye catches first.  Frames
    therefore go through a FIFO ``round(latency / hop_s)`` deep and are sent
    only when their own audio reaches the speaker.

    ``offset_ms`` trims whatever is left: positive holds the lights back,
    negative pushes them forward.  ``volume`` scales the playback only -- the
    FFT always sees the peak-normalised signal, so turning it down does not
    dim the display.
    """

    def __init__(self, cfg: Config, volume=1.0, offset_ms=0.0,
                 device=None, latency='high', channels=1):
        import sounddevice as sd
        self.cfg, self.volume, self.channels = cfg, float(volume), channels
        self.stream = sd.OutputStream(samplerate=cfg.fs, channels=channels,
                                      blocksize=cfg.hop, dtype='float32',
                                      device=device, latency=latency)
        self.stream.start()
        dt             = cfg.hop / cfg.fs
        self.lag_s     = max(0.0, float(self.stream.latency) + offset_ms / 1000.0)
        self.delay     = int(round(self.lag_s / dt))     # frames held back
        self.queue     = deque()
        self.underruns = 0

    def write(self, block):
        """Hand one hop to the card.  Blocks -- this is what paces the loop.
        Returns True if the card ran dry waiting for us."""
        b = np.clip(np.asarray(block, np.float32) * self.volume, -1.0, 1.0)
        under = bool(self.stream.write(np.ascontiguousarray(b)))
        self.underruns += under
        return under

    def sync(self, frame):
        """Push frame k in; get back the frame whose audio is being heard now,
        or None while the delay line is still filling.  The blank display
        during that first fill is correct -- the speaker is silent too."""
        self.queue.append(frame)
        return self.queue.popleft() if len(self.queue) > self.delay else None

    def drain(self, sink):
        """The source is exhausted but `lag_s` of music is still inside the
        card.  Writing silence keeps the loop paced at real time while that
        tail plays out, so the closing frames still land on their own audio."""
        z = np.zeros((self.cfg.hop, self.channels), np.float32)
        while self.queue:
            self.write(z)
            sink.send(self.queue.popleft())

    def close(self):
        try: self.stream.abort()      # drain() has already played the tail
        except Exception: pass
        try: self.stream.close()
        except Exception: pass


# ================================ LED sinks ==================================
MAGIC_A, MAGIC_B, READY = 0xAA, 0x55, 0x01

class SerialSink:
    """Request/response protocol -- see firmware/led_sink/led_sink.ino.

        Arduino -> host : 0x01                       'ready for a frame'
        host -> Arduino : AA 55 len_lo len_hi data.. xor

    The handshake exists because FastLED disables interrupts for the whole
    WS2812B strobe (2.08 ms at 60 LEDs).  At 1 Mbaud that blackout would
    silently drop ~208 bytes into a 64-byte UART buffer.  By only ever
    transmitting after an explicit READY, nothing is in flight during the
    blackout and the buffer cannot overflow.
    """
    def __init__(self, port, cfg: Config, baud=1000000, timeout=1.0):
        import serial
        self.ser = serial.Serial(port, baud, timeout=timeout)
        time.sleep(2.0)                    # AVR auto-reset on port open
        self.ser.reset_input_buffer()
        self.cfg, self.dropped = cfg, 0

    def _wait_ready(self):
        b = self.ser.read(1)
        return len(b) == 1 and b[0] == READY

    def send(self, frame_u8):
        if not self._wait_ready():
            self.dropped += 1; return False
        payload = frame_u8.reshape(-1).tobytes()
        n = len(payload)
        chk = 0
        for v in payload: chk ^= v
        self.ser.write(bytes([MAGIC_A, MAGIC_B, n & 0xFF, (n >> 8) & 0xFF])
                       + payload + bytes([chk]))
        self.ser.flush()
        return True

    def close(self):
        try:
            self.send(np.zeros((self.cfg.n_leds, 3), np.uint8))
        except Exception: pass
        self.ser.close()


class VirtualSink:
    """No hardware: records every frame so it can be plotted or animated."""
    def __init__(self, cfg: Config, keep=True):
        self.cfg, self.frames, self.keep = cfg, [], keep
    def send(self, frame_u8):
        if self.keep: self.frames.append(frame_u8.copy())
        return True
    def close(self): pass
    def as_array(self): return np.array(self.frames)


class PwmSink:
    """6 discrete LEDs on the Arduino's PWM pins.

        host -> Arduino : 0xAA 0x55 <n> <n bytes> xor        (10 bytes for n=6)

    No handshake and no READY byte, unlike the WS2812B sink.  analogWrite()
    writes a timer compare register and never disables interrupts, so there
    is no blackout window in which bytes could be lost.  At 115200 baud a
    9-byte frame at 86.13 fps uses 7.8 kbps -- about 15x headroom.
    """
    def __init__(self, port, n_ch=6, baud=115200, timeout=1.0):
        import serial
        self.ser = serial.Serial(port, baud, timeout=timeout)
        time.sleep(2.0)                    # AVR auto-reset on port open
        self.ser.reset_input_buffer()
        self.n_ch = n_ch

    def send(self, levels_u8):
        pl = bytes(np.asarray(levels_u8, np.uint8)[: self.n_ch])
        chk = 0
        for v in pl: chk ^= v
        self.ser.write(bytes([MAGIC_A, MAGIC_B, len(pl)]) + pl + bytes([chk]))
        self.ser.flush()
        return True

    def close(self):
        try: self.send(np.zeros(self.n_ch, np.uint8))
        except Exception: pass
        self.ser.close()


class VirtualPwmSink:
    """No hardware: records the channel levels for plotting."""
    def __init__(self, n_ch=6, keep=True):
        self.n_ch, self.frames, self.keep = n_ch, [], keep
    def send(self, levels_u8):
        if self.keep: self.frames.append(np.asarray(levels_u8, np.uint8).copy())
        return True
    def close(self): pass
    def as_array(self): return np.array(self.frames)


class LcdSink:
    """20x4 character LCD (+ optional 6 PWM LEDs) over serial.

        host -> Arduino : 0xAA 0x55 <nLcd> <nLed> <contrast> <lcd..> <led..> xor

    31 bytes for 20 LCD bars + 5 LEDs (5 header + 20 + 5 + 1 checksum).  At
    115200 baud that is 2.69 ms per frame -> 372 fps, against the 86.13 fps
    the audio needs.  The contrast
    byte rides along every frame so it can be tuned while the display runs.

    The host sends LEVELS, not characters.  The Arduino turns them into
    characters and redraws only the cells that changed -- measured at 17.7
    of 80 cells per frame, a 4.5x saving that is what makes the LCD keep up.
    """
    def __init__(self, port, n_lcd=LCD_COLS, n_led=5, baud=115200, timeout=1.0,
                 contrast=26):
        import serial
        self.ser = serial.Serial(port, baud, timeout=timeout)
        time.sleep(2.0)
        self.ser.reset_input_buffer()
        self.n_lcd, self.n_led = n_lcd, n_led
        self.contrast = int(np.clip(contrast, 0, 255))

    def send(self, frame_u8):
        f = np.asarray(frame_u8, np.uint8)
        lcd, led = f[: self.n_lcd], f[self.n_lcd: self.n_lcd + self.n_led]
        pl = bytes(lcd) + bytes(led)
        chk = 0
        for v in pl: chk ^= v
        self.ser.write(bytes([MAGIC_A, MAGIC_B, len(lcd), len(led),
                              self.contrast]) + pl + bytes([chk]))
        self.ser.flush()
        return True

    def close(self):
        try: self.send(np.zeros(self.n_lcd + self.n_led, np.uint8))
        except Exception: pass
        self.ser.close()


class VirtualLcdSink:
    def __init__(self, n_lcd=LCD_COLS, n_led=5, keep=True):
        self.n_lcd, self.n_led, self.frames, self.keep = n_lcd, n_led, [], keep
    def send(self, frame_u8):
        if self.keep: self.frames.append(np.asarray(frame_u8, np.uint8).copy())
        return True
    def close(self): pass
    def as_array(self): return np.array(self.frames)
    def lcd_only(self): return self.as_array()[:, : self.n_lcd]


# ============================ the processing chain ===========================
class Visualiser:
    def __init__(self, cfg: Config, mode='bars', max_amps=2.4, output='strip',
                 beat_sensitivity=0.35):
        self.output   = output
        self.cfg      = cfg
        self.stft     = STFT(cfg)
        self.fb       = mel_filterbank(cfg)
        self.env      = AsymmetricEnvelope(cfg)
        self.agc      = AGC(cfg.n_bands)
        self.onset    = OnsetDetector(cfg)
        self.events   = OnsetEvents(cfg.frame_rate,
                                    rel_thresh=beat_sensitivity)
        self.lvl_rng  = AdaptiveRange(-55.0, -12.0, min_span=12.0)   # dBFS
        self.cen_rng  = AdaptiveRange(300.0, 5000.0, min_span=600.0) # Hz
        if output == 'pwm':
            self.mapper = PwmMapper(cfg.n_bands)
        elif output == 'lcd':
            self.mapper = LcdMapper(LCD_COLS)
            self.led_mapper = PwmMapper(6)
        else:
            self.mapper = LedMapper(cfg)
        self.freqs    = np.fft.rfftfreq(cfg.n_fft, 1.0 / cfg.fs)
        self.mode     = mode
        self.max_amps = max_amps
        self.odf_hist = []
        self.bpm      = (float('nan'), float('nan'))

    def step(self, block):
        """One hop of audio -> one LED frame.  Returns (frame_u8, telemetry)."""
        mag   = self.stft.push(block)
        raw   = self.fb @ mag
        sm    = self.env(raw)
        bands = self.agc(sm)
        od    = self.onset(mag)
        self.odf_hist.append(od)
        beat  = self.events(od)
        cen   = spectral_centroid(mag, self.freqs)
        cen_n = self.cen_rng(cen)
        eng   = self.lvl_rng(rms_db(block))

        if self.output == 'lcd':
            lcd = self.mapper.render(self.mode, bands=bands, energy=eng)
            # the 6 PWM LEDs get a coarse 6-group summary of the same bands
            grp = np.array_split(np.asarray(bands, float), 6)
            led6 = GAMMA8[(np.clip([g.mean() for g in grp], 0, 1)
                           * 255).astype(np.uint8)]
            frame = np.concatenate([lcd, led6]).astype(np.uint8)
            amps = pwm_current_ma(led6) / 1000.0
            return frame, dict(bands=bands, centroid=cen, centroid_norm=cen_n,
                               energy=eng, onset=od, beat=beat, amps=amps)

        frame = self.mapper.render(self.mode, bands=bands, centroid_norm=cen_n,
                                   energy=eng, beat=beat)
        if self.output == 'pwm':
            # USB-powered, worst case 87 mA against a 200 mA chip limit:
            # no cap needed, but report the current so it can be logged.
            amps = pwm_current_ma(frame) / 1000.0
        else:
            amps = power_estimate(frame)
            if amps > self.max_amps:
                frame = (frame.astype(np.float32) *
                         (self.max_amps / amps)).astype(np.uint8)
                amps = self.max_amps
        return frame, dict(bands=bands, centroid=cen, centroid_norm=cen_n,
                           energy=eng, onset=od, beat=beat, amps=amps)

    def finalize_tempo(self):
        odf = np.array(self.odf_hist)
        if odf.size: self.bpm = estimate_tempo(odf, self.cfg.frame_rate)
        return self.bpm


def run(source, sink, cfg: Config, mode='bars', max_amps=2.4,
        verbose=True, realtime=None, output='strip', beat_sensitivity=0.35,
        player=None):
    vis = Visualiser(cfg, mode=mode, max_amps=max_amps, output=output,
                     beat_sensitivity=beat_sensitivity)
    dt  = cfg.hop / cfg.fs
    if realtime is None: realtime = getattr(source, 'realtime', False)
    # A blocking write to the sound card already paces the loop, and paces it
    # against a better clock than sleep() can; doing both only adds lateness.
    if player is not None: realtime = False
    lbl  = 'under' if player is not None else 'late'
    # FileSource can hand back the same hop with its channels intact; anything
    # else just plays the mono block the analysis already has.
    play = getattr(source, 'playback_block', None)
    t0, n, late, peak, beats = time.perf_counter(), 0, 0, 0.0, 0
    try:
        for block in source:
            frame, tel = vis.step(block)
            if player is None:
                sink.send(frame)
            else:
                pb = play() if play else block
                late += int(player.write(pb))      # blocks: this is the clock
                due = player.sync(frame)
                if due is not None: sink.send(due)
            peak = max(peak, tel['amps']); n += 1
            beats += int(tel['beat'])
            if realtime:
                target = t0 + n * dt
                slack  = target - time.perf_counter()
                if slack > 0: time.sleep(slack)
                else: late += 1
            if verbose and n % 86 == 0:
                sys.stdout.write(f'\r  {n*dt:6.1f}s  bands={np.round(tel["bands"],2)}'
                                 f'  {tel["amps"]:.2f} A  {lbl}={late}   ')
                sys.stdout.flush()
        if player is not None: player.drain(sink)
    except KeyboardInterrupt:
        pass
    finally:
        if player is not None: player.close()
        sink.close()
    el = time.perf_counter() - t0
    b1, b2 = vis.finalize_tempo()
    if verbose:
        print(f'\n  frames={n}  wall={el:.2f}s  audio={n*dt:.2f}s'
              f'  {lbl}={late} ({late/max(1,n)*100:.1f}%)  peak={peak:.2f} A'
              f'  beats={beats} ({beats/max(n*dt,1e-9)*60:.0f}/min)')
        print(f'  tempo: autocorr {b1:.2f} BPM | comb {b2:.2f} BPM'
              f' | agreement {abs(b1-b2)/max(b1,1e-9)*100:.2f}%')
    return dict(frames=n, elapsed=el, late=late, peak_amps=peak,
                bpm=(b1, b2), beats=beats)
