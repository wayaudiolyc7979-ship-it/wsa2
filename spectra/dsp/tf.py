"""Transfer Function DSP — 순수(Qt 무관).

v2.0 분해: wayaudo2.py에서 MTWEngine 이동(동작 0 변경).
골든: tests/test_dsp_golden.py::test_mtw_* .
"""
import numpy as np


class MTWEngine:
    """Multi-Time-Window transfer function — Smaart-style multirate dual-FFT.

    Stage s runs at sample-rate sr/2**s. Each stage keeps its own
    Sxy/Sxx/Syy EMA over a fixed-size Hann FFT, so a lower stage (lower SR,
    same FFT size) yields finer frequency resolution / longer time window at
    low frequencies, while the top stage keeps fast time response up high.
    result() stitches the per-stage transfer functions onto a log grid.

    Pure DSP + accumulator state — no Qt, fully headless-testable.
    """
    F_MIN = 10.0          # lowest output frequency
    HI_FRAC = 0.45        # usable upper edge of each stage as fraction of its SR (below anti-alias rolloff)
    LO_FRAC = 0.225       # lower edge of each stage = HI_FRAC of the next-lower stage (one octave/stage)

    def __init__(self, sample_rate, n_fft=8192, n_stages=8, avg_target=16, n_out=800):
        self.sr = float(sample_rate)
        self.n_fft = int(n_fft)
        self.n_stages = max(1, int(n_stages))
        self.avg_target = int(avg_target)
        self.n_out = int(n_out)
        # master rolling buffer must be long enough to fill the lowest stage's FFT
        self.master_len = self.n_fft * (2 ** (self.n_stages - 1))
        self._win = np.hanning(self.n_fft).astype(np.float64)
        # per-stage frequency axis (cached)
        self._stage_f = [np.fft.rfftfreq(self.n_fft, 1.0 / (self.sr / (2 ** s))).astype(np.float64)
                         for s in range(self.n_stages)]
        self.reset()

    def reset(self):
        self._sxy = [None] * self.n_stages
        self._sxx = [None] * self.n_stages
        self._syy = [None] * self.n_stages
        self._n = [0] * self.n_stages

    @property
    def f_max(self):
        return min(self.HI_FRAC * self.sr, 22000.0)

    def _decimate(self, x, factor):
        if factor == 1:
            return x
        from scipy.signal import resample_poly
        return resample_poly(x, 1, factor)

    def push(self, ref_long, meas_long):
        """Feed one master-length frame of ref & meas. Updates every stage's EMA."""
        ref = np.asarray(ref_long, dtype=np.float64)
        meas = np.asarray(meas_long, dtype=np.float64)
        for s in range(self.n_stages):
            factor = 2 ** s
            r = self._decimate(ref, factor)
            m = self._decimate(meas, factor)
            if len(r) < self.n_fft:
                continue
            r = r[-self.n_fft:] * self._win
            m = m[-self.n_fft:] * self._win
            R = np.fft.rfft(r); M = np.fft.rfft(m)
            sxy = M * np.conj(R); sxx = np.abs(R) ** 2; syy = np.abs(M) ** 2
            if self._sxy[s] is None:
                self._sxy[s] = sxy; self._sxx[s] = sxx; self._syy[s] = syy; self._n[s] = 1
            else:
                # 목표 시정수에 ~10프레임 만에 도달(1씩 올리면 큰 avg에서 한참 동일하게 보임)
                self._n[s] = min(self._n[s] + max(1, self.avg_target // 10), self.avg_target)
                a = 1.0 / self._n[s]
                # 상승·하강 완전 대칭(Smaart식) — 위/아래 같은 시정수(=Response). fast-release 없음.
                b = 1.0 - a
                self._sxy[s] = b * self._sxy[s] + a * sxy
                self._sxx[s] = b * self._sxx[s] + a * sxx
                self._syy[s] = b * self._syy[s] + a * syy

    def _stage_bounds(self, s):
        """[lo, hi] frequency band stage s is responsible for on the output grid."""
        sr_s = self.sr / (2 ** s)
        hi = self.HI_FRAC * sr_s
        lo = self.LO_FRAC * sr_s
        if s == 0:
            hi = self.f_max                 # top stage extends up to f_max
        if s == self.n_stages - 1:
            lo = self.F_MIN                 # bottom stage extends down to F_MIN
        return lo, hi

    def result(self):
        """Stitch stages → (f_out, H_complex, coh) on a log grid. None if no data."""
        if all(x is None for x in self._sxy):
            return None
        f_out = np.logspace(np.log10(self.F_MIN), np.log10(self.f_max), self.n_out)
        H = np.zeros(self.n_out, dtype=np.complex128)
        coh = np.zeros(self.n_out, dtype=np.float64)
        filled = np.zeros(self.n_out, dtype=bool)
        # assign from lowest stage (best LF resolution) upward; higher stages override their HF band
        for s in range(self.n_stages - 1, -1, -1):
            if self._sxy[s] is None:
                continue
            lo, hi = self._stage_bounds(s)
            fs = self._stage_f[s]
            Hs = self._sxy[s] / np.maximum(self._sxx[s], 1e-30)
            cohs = np.clip(np.abs(self._sxy[s]) ** 2 /
                           np.maximum(self._sxx[s] * self._syy[s], 1e-60), 0.0, 1.0)
            sel = (f_out >= lo) & (f_out <= hi)
            if not np.any(sel):
                continue
            H[sel] = (np.interp(f_out[sel], fs, Hs.real) +
                      1j * np.interp(f_out[sel], fs, Hs.imag))
            coh[sel] = np.interp(f_out[sel], fs, cohs)
            filled[sel] = True
        if not np.all(filled):  # fill any gaps from the nearest filled neighbour
            idx = np.where(filled)[0]
            if len(idx):
                H = H[idx][np.clip(np.searchsorted(idx, np.arange(self.n_out)), 0, len(idx) - 1)]
                coh = coh[idx][np.clip(np.searchsorted(idx, np.arange(self.n_out)), 0, len(idx) - 1)]
        return f_out, H, coh
