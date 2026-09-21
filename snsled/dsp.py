"""
Signals & Systems mini-project -- Audio -> LED visualiser
=========================================================
DSP core.  Pure NumPy, no real-time dependencies, fully testable offline.

Every block here maps to a named course topic; see README.md for the table.
"""
from dataclasses import dataclass, field
import numpy as np

# ----------------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------------
@dataclass
class Config:
    fs:       int   = 44100   # sample rate (Hz)
    n_fft:    int   = 2048    # analysis window length -> df = fs/n_fft = 21.53 Hz
    hop:      int   = 512     # 75 % overlap -> 86.13 frames/s
    n_bands:  int   = 8       # mel filter bank size = number of LED groups
    fmin:     float = 20.0
    fmax:     float = 16000.0
    attack:   float = 1.00    # envelope rise coefficient (1.0 = instantaneous)
    release:  float = 0.12    # envelope fall coefficient -> tau ~ 91 ms
    n_leds:   int   = 60

    @property
    def df(self)         -> float: return self.fs / self.n_fft
    @property
    def frame_rate(self) -> float: return self.fs / self.hop
    @property
    def window_ms(self)  -> float: return 1000.0 * self.n_fft / self.fs
    @property
    def hop_ms(self)     -> float: return 1000.0 * self.hop / self.fs


# ----------------------------------------------------------------------------
# Mel scale  (O'Shaughnessy 1987):  m = 2595 log10(1 + f/700)
# ----------------------------------------------------------------------------
def hz_to_mel(f): return 2595.0 * np.log10(1.0 + np.asarray(f, float) / 700.0)
def mel_to_hz(m): return 700.0 * (10.0 ** (np.asarray(m, float) / 2595.0) - 1.0)


def mel_filterbank(cfg: Config) -> np.ndarray:
    """Triangular mel filter bank, shape (n_bands, n_fft//2 + 1).

    Rows are area-normalised so a flat spectrum gives equal energy in every
    band -- otherwise the wide high bands dominate purely by bin count.
    """
    n_bins = cfg.n_fft // 2 + 1
    freqs  = np.fft.rfftfreq(cfg.n_fft, 1.0 / cfg.fs)
    edges  = mel_to_hz(np.linspace(hz_to_mel(cfg.fmin),
                                   hz_to_mel(cfg.fmax), cfg.n_bands + 2))
    fb = np.zeros((cfg.n_bands, n_bins))
    for b in range(cfg.n_bands):
        lo, ctr, hi = edges[b], edges[b + 1], edges[b + 2]
        rise = (freqs >= lo) & (freqs <= ctr)
        fall = (freqs >  ctr) & (freqs <= hi)
        if ctr > lo:  fb[b, rise] = (freqs[rise] - lo) / (ctr - lo)
        if hi  > ctr: fb[b, fall] = (hi - freqs[fall]) / (hi - ctr)
        s = fb[b].sum()
        if s > 0: fb[b] /= s
    return fb


def band_edges(cfg: Config) -> np.ndarray:
    return mel_to_hz(np.linspace(hz_to_mel(cfg.fmin),
                                 hz_to_mel(cfg.fmax), cfg.n_bands + 2))


# ----------------------------------------------------------------------------
# STFT
# ----------------------------------------------------------------------------
class STFT:
    """Framing + Hann window + rFFT.

    Hann is used because its side lobes fall at -31 dB and roll off at
    -18 dB/octave, so a loud bass note does not leak into the treble bands
    and light up LEDs that should be dark.  Equivalent noise bandwidth is
    1.5 bins, so effective resolution is 1.5 * df.
    """
    def __init__(self, cfg: Config):
        self.cfg  = cfg
        self.win  = np.hanning(cfg.n_fft)
        self.buf  = np.zeros(cfg.n_fft)
        self.enbw = 1.5                      # bins, for Hann

    def push(self, block: np.ndarray) -> np.ndarray:
        """Shift `hop` new samples into the ring buffer, return |X[k]|."""
        h = self.cfg.hop
        self.buf = np.concatenate([self.buf[h:], block[:h]])
        return np.abs(np.fft.rfft(self.buf * self.win))

    def offline(self, x: np.ndarray) -> np.ndarray:
        """Whole-signal STFT -> (n_frames, n_bins).  Used for the report plots."""
        N, H = self.cfg.n_fft, self.cfg.hop
        nf   = 1 + max(0, (len(x) - N) // H)
        S    = np.empty((nf, N // 2 + 1))
        for i in range(nf):
            S[i] = np.abs(np.fft.rfft(x[i * H:i * H + N] * self.win))
        return S


# ----------------------------------------------------------------------------
# Asymmetric envelope follower -- the project's central LTI demonstration
# ----------------------------------------------------------------------------
class AsymmetricEnvelope:
    """y[n] = y[n-1] + c * (x[n] - y[n-1]),  c = attack if rising else release.

    For a fixed c this is the one-pole IIR low-pass
        H(z) = c / (1 - (1-c) z^-1),   pole at (1-c)
    Switching c by slope direction makes it *non-linear*, which is precisely
    why it beats the LTI version here: attack=1.0 adds ZERO latency on a
    transient, while release=0.12 still gives a 91 ms visual decay.
    A symmetric filter slow enough to look smooth costs ~33 ms of lag and
    pushes the chain past the perceptual sync threshold.
    """
    def __init__(self, cfg: Config, n: int = None):
        self.a = cfg.attack
        self.r = cfg.release
        self.y = np.zeros(cfg.n_bands if n is None else n)

    def __call__(self, x: np.ndarray) -> np.ndarray:
        c = np.where(x > self.y, self.a, self.r)
        self.y = self.y + c * (x - self.y)
        return self.y

    @staticmethod
    def tau_ms(coef: float, frame_rate: float) -> float:
        """1/e time constant in ms."""
        if coef >= 1.0: return 0.0
        return -1.0 / np.log(1.0 - coef) / frame_rate * 1000.0

    @staticmethod
    def cutoff_hz(coef: float, frame_rate: float) -> float:
        """Exact -3 dB cutoff of the one-pole section."""
        if coef >= 1.0: return frame_rate / 2.0
        p = 1.0 - coef
        c = np.clip((1.0 + p * p - 2.0 * coef * coef) / (2.0 * p), -1.0, 1.0)
        return float(np.arccos(c) * frame_rate / (2 * np.pi))


# ----------------------------------------------------------------------------
# Automatic gain control -- makes quiet and loud tracks look the same
# ----------------------------------------------------------------------------
class AGC:
    """Tracks a slow running maximum per band and normalises against it."""
    def __init__(self, n: int, decay: float = 0.9995, floor: float = 1e-4):
        self.peak  = np.full(n, floor)
        self.decay = decay
        self.floor = floor

    def __call__(self, x: np.ndarray) -> np.ndarray:
        self.peak = np.maximum(x, self.peak * self.decay)
        return np.clip(x / np.maximum(self.peak, self.floor), 0.0, 1.0)


# ----------------------------------------------------------------------------
# Onset detection -- half-wave-rectified spectral flux
# ----------------------------------------------------------------------------
class OnsetDetector:
    """Spectral flux: sum over k of max(0, |X_n[k]| - |X_{n-1}[k]|).

    Half-wave rectification keeps only ENERGY INCREASES, so a note ending
    does not register as an onset.  An adaptive median threshold then
    removes the slow loudness trend, leaving isolated transients.
    """
    def __init__(self, cfg: Config, median_len: int = 21, delta: float = 1.35):
        self.prev = None
        self.hist = []
        self.median_len = median_len
        self.delta = delta

    def __call__(self, mag: np.ndarray) -> float:
        if self.prev is None:
            self.prev = mag.copy(); return 0.0
        flux = float(np.sqrt(np.sum(np.maximum(mag - self.prev, 0.0) ** 2)))
        self.prev = mag.copy()
        self.hist.append(flux)
        if len(self.hist) > self.median_len: self.hist.pop(0)
        thr = self.delta * float(np.median(self.hist))
        return max(0.0, flux - thr)

    @staticmethod
    def offline(S: np.ndarray, median_len: int = 21, delta: float = 1.35):
        flux = np.sqrt(np.sum(np.maximum(np.diff(S, axis=0), 0.0) ** 2, axis=1))
        flux = np.concatenate([[0.0], flux])
        m = flux.max()
        if m > 0: flux = flux / m
        med = np.convolve(flux, np.ones(median_len) / median_len, 'same')
        return np.maximum(flux - delta * med, 0.0)


# ----------------------------------------------------------------------------
# Tempo estimation
# ----------------------------------------------------------------------------
def estimate_tempo(odf: np.ndarray, frame_rate: float,
                   bpm_lo: float = 55.0, bpm_hi: float = 240.0,
                   prior_bpm: float = 120.0, prior_sigma: float = 0.55):
    """Return (bpm_autocorr, bpm_comb) -- two independent estimates.

    IMPORTANT (documented failure mode): a rhythm contains a whole metrical
    HIERARCHY -- tatum, beat, bar.  Both estimators will happily lock onto
    the tatum (e.g. 240 BPM when the beat is 120).  Picking "the" beat is a
    perceptual question, not a signal-processing one, so a log-normal prior
    centred on `prior_bpm` (Moelants' resonance model) breaks the tie.

    Both estimators use the WHOLE detection function.  Inter-onset-interval
    statistics were tried and rejected: onset times are quantised to the hop
    (11.6 ms) and biased per instrument, giving >90 % error in testing.
    """
    o = odf - odf.mean()
    n = len(o)
    if n < 16 or not np.any(o): return float('nan'), float('nan')
    grid  = np.arange(bpm_lo, bpm_hi, 0.02)
    prior = np.exp(-0.5 * (np.log2(grid / prior_bpm) / prior_sigma) ** 2)

    def parabolic(y, i):
        if i <= 0 or i >= len(y) - 1: return float(i)
        a, b, c = y[i - 1], y[i], y[i + 1]
        d = a - 2 * b + c
        return i + (0.5 * (a - c) / d if d != 0 else 0.0)

    # --- method 1: autocorrelation of the detection function
    ac = np.correlate(o, o, 'full')[n - 1:]
    if ac[0] != 0: ac = ac / ac[0]
    acg = np.interp(60.0 * frame_rate / grid, np.arange(len(ac)), ac)
    s1  = acg * prior
    i1  = int(np.argmax(s1))
    bpm1 = grid[0] + parabolic(s1, i1) * (grid[1] - grid[0])

    # --- method 2: comb filter (phase-invariant pulse-train correlation)
    t  = np.arange(n) / frame_rate
    s2 = np.empty_like(grid)
    for gi, b in enumerate(grid):
        ph = (t % (60.0 / b)) / (60.0 / b)
        s2[gi] = (np.hypot(o @ np.cos(2 * np.pi * ph), o @ np.sin(2 * np.pi * ph))
                  + 0.5 * np.hypot(o @ np.cos(4 * np.pi * ph), o @ np.sin(4 * np.pi * ph)))
    s2 = s2 * prior
    i2 = int(np.argmax(s2))
    bpm2 = grid[0] + parabolic(s2, i2) * (grid[1] - grid[0])
    return float(bpm1), float(bpm2)


# ----------------------------------------------------------------------------
# Spectral centroid -- first moment of the magnitude spectrum ("brightness")
# ----------------------------------------------------------------------------
def spectral_centroid(mag: np.ndarray, freqs: np.ndarray) -> float:
    s = mag.sum()
    return float((mag @ freqs) / s) if s > 0 else 0.0


# ----------------------------------------------------------------------------
# Onset EVENTS  (distinct from the onset detection FUNCTION above)
# ----------------------------------------------------------------------------
class OnsetEvents:
    """Turn the continuous detection function into discrete beat events.

    The ODF is a continuous curve, not a flag.  Thresholding it directly
    fires on ~36 % of frames -- every frame of every note's attack -- which
    makes any beat-triggered effect stutter instead of pulse.

    Two things fix it:
      * an ADAPTIVE threshold, a fraction of the ODF's running peak, so it
        works on quiet and loud passages alike;
      * a REFRACTORY period, the minimum musically plausible gap between
        onsets.  100 ms allows up to 600 events/min, comfortably above any
        real tatum, while suppressing the multiple triggers from one attack.

    Rising-edge triggered, so it adds ZERO latency -- important, because the
    beat effects are the ones the eye checks against the ear.

    CHOOSING rel_thresh (measured on the 120 BPM test track, CV = std/mean
    of the inter-event interval; lower is more regular):

        rel_thresh   events/s   median IEI   CV      locks to
        0.15          3.92       0.255 s     0.038   tatum
        0.25          3.25       0.255 s     0.337   NOTHING -- irregular
        0.35          2.00       0.499 s     0.083   beat

    The threshold does not trade off smoothly.  Rhythm is quantised into a
    metrical hierarchy, so a threshold BETWEEN two levels catches all of one
    level and only some of the next, and the result stutters.  0.25 was the
    worst value available.  Default 0.35 locks to the beat; use 0.15 for
    double-time activity.  Anything in between will look wrong.
    """
    def __init__(self, frame_rate: float, refractory_ms: float = 100.0,
                 rel_thresh: float = 0.35, peak_decay: float = 0.999):
        self.refractory = max(1, int(refractory_ms * frame_rate / 1000.0))
        self.rel        = rel_thresh
        self.decay      = peak_decay
        self.peak       = 1e-9
        self.since      = self.refractory
        self.armed      = True

    def __call__(self, odf_value: float) -> bool:
        self.peak = max(odf_value, self.peak * self.decay)
        thr = self.rel * self.peak
        self.since += 1
        fired = False
        if odf_value < thr * 0.6:
            self.armed = True                       # hysteresis: must fall first
        if self.armed and odf_value > thr and self.since >= self.refractory:
            fired, self.since, self.armed = True, 0, False
        return fired


class AdaptiveRange:
    """Normalise a scalar against its own slowly-tracked range.

    Expands instantly when a new extreme arrives, contracts slowly, and
    never collapses below `min_span`.  Used so the VU meter and the centroid
    sweep behave the same on a quiet acoustic track and a loud mix without
    any per-song tuning.
    """
    def __init__(self, lo, hi, rate=0.0015, min_span=None):
        self.lo, self.hi = float(lo), float(hi)
        self.rate = rate
        self.min_span = (hi - lo) * 0.25 if min_span is None else min_span

    def __call__(self, x: float) -> float:
        x = float(x)
        if x < self.lo: self.lo = x
        else:           self.lo += (x - self.lo) * self.rate
        if x > self.hi: self.hi = x
        else:           self.hi += (x - self.hi) * self.rate
        span = self.hi - self.lo
        if span < self.min_span:                    # guard against collapse
            mid = 0.5 * (self.hi + self.lo)
            self.lo, self.hi = mid - self.min_span/2, mid + self.min_span/2
            span = self.min_span
        return float(np.clip((x - self.lo) / span, 0.0, 1.0))


def rms_db(block: np.ndarray, floor_db: float = -70.0) -> float:
    """Broadband level in dBFS -- the honest input to a VU meter."""
    r = float(np.sqrt(np.mean(np.asarray(block, float) ** 2)))
    return max(floor_db, 20.0 * np.log10(r + 1e-12))
