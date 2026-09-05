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
                # 워밍업: n을 avg_target//10(최소 1)씩 올려 목표 시정수로 램프업(큰 avg에서 초기
                # 몇 프레임이 똑같아 보이는 것 완화). avg_target=16이면 +1/프레임 → 16프레임에 도달.
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


def _smooth_real(arr, f_src, f_out, half):
    """벡터화된 cumsum 옥타브 스무딩 (실수 배열 전용)."""
    nearest = np.clip(np.searchsorted(f_src, f_out, 'left'), 0, len(arr) - 1)
    lo = np.searchsorted(f_src, f_out / half, 'left')
    hi = np.searchsorted(f_src, f_out * half, 'right')
    cum = np.zeros(len(arr) + 1); cum[1:] = np.cumsum(arr)
    cnt = hi - lo; val = cnt > 0
    out = arr[nearest].copy()
    out[val] = (cum[hi[val]] - cum[lo[val]]) / cnt[val]
    return out

def _tf_smooth(freqs, H_complex, bpo):
    """mag(dB) 실수 스무딩 + phase 복소 페이저 스무딩 (Smaart 방식).
    로그 등간격 f_out으로 먼저 보간 후 양 패스를 f_out 위에서 수행 →
    저주파에서도 bpo에 맞는 일정한 창 폭 보장 (FFT 선형 빈 밀도 영향 없음)."""
    mask = (freqs >= 18) & (freqs <= 22000)
    f = freqs[mask]; H = H_complex[mask]
    if len(f) < 2:
        z = np.zeros(max(len(f), 1))
        return f[:1], z[:1], z[:1], z[:1], z[:1]
    f_min = max(float(f[0]), 20.0); f_max = min(float(f[-1]), 20000.0)
    f_out = np.logspace(np.log10(f_min), np.log10(f_max), 1200)
    mag_raw = 20 * np.log10(np.maximum(np.abs(H), 1e-10))
    # 먼저 로그 등간격 그리드로 보간 (선형 보간) — 이후 두 패스 모두 f_out 위에서 수행
    mag_i = np.interp(f_out, f, mag_raw)
    H_re_i = np.interp(f_out, f, H.real)
    H_im_i = np.interp(f_out, f, H.imag)
    if bpo == 0:
        mag_db = mag_i
        H_re   = H_re_i
        H_im   = H_im_i
    else:
        # 삼각 창 = 직사각형 창 2회 통과 (각 반폭 2^(0.5/bpo)) — Smaart 동등 FWHM
        half2  = 2 ** (0.5 / bpo)
        mag_db = _smooth_real(_smooth_real(mag_i,   f_out, f_out, half2), f_out, f_out, half2)
        H_re   = _smooth_real(_smooth_real(H_re_i,  f_out, f_out, half2), f_out, f_out, half2)
        H_im   = _smooth_real(_smooth_real(H_im_i,  f_out, f_out, half2), f_out, f_out, half2)
    ph_wrap = np.arctan2(H_im, H_re) * (180.0 / np.pi)   # [-180, +180]
    ph_unwr = np.unwrap(np.arctan2(H_im, H_re)) * (180.0 / np.pi)
    # 그룹 딜레이는 항상 최소 1/3 옥타브로 스무딩 후 계산
    # (좁은 창에서 np.gradient가 위상 노이즈로 극단값 출력하는 문제 방지)
    bpo_grp = max(bpo, 3) if bpo > 0 else 3
    half2_grp = 2 ** (0.25 / bpo_grp)
    H_re_g = _smooth_real(_smooth_real(H_re_i, f_out, f_out, half2_grp), f_out, f_out, half2_grp)
    H_im_g = _smooth_real(_smooth_real(H_im_i, f_out, f_out, half2_grp), f_out, f_out, half2_grp)
    ph_rad  = np.unwrap(np.arctan2(H_im_g, H_re_g))
    grp_ms  = -np.gradient(ph_rad, 2 * np.pi * f_out) * 1000.0
    return f_out, mag_db, ph_wrap, ph_unwr, grp_ms

def _multimic_average(H_list, gamma_list, delay_list, freqs, sr, bpo,
                      mode='mag', align=True):
    """참여 카드들의 복소 H(f)를 라이브 평균. 유효 카드<2면 None.

    mode='mag'     : 파워 RMS 평균 → |H_avg|²=mean|H_i|². 위상/IR 없음(공간평균 표준).
    mode='complex' : 표시(정렬)된 복소 H를 벡터 평균. align=True는 정렬 그대로,
                     align=False는 카드 딜레이를 되살려 콤필터를 드러냄. 위상·IR 포함.
    coherence는 카드별 γ² 산술평균(커서 리드아웃 %용).
    """
    valid = [(np.asarray(h, dtype=complex),
              (np.asarray(g, dtype=float) if g is not None else None), d)
             for h, g, d in zip(H_list, gamma_list, delay_list) if h is not None]
    if len(valid) < 2:
        return None
    Hs = [v[0] for v in valid]
    delays = [v[2] for v in valid]
    n = len(Hs)
    gs = [v[1] for v in valid if v[1] is not None]
    if len(gs) == n:
        coh_avg = np.mean(np.stack(gs), axis=0)
    else:
        coh_avg = np.ones(len(freqs), dtype=float)
    if mode == 'mag':
        P_avg = np.mean(np.stack([np.abs(h) ** 2 for h in Hs]), axis=0)
        H_mag = np.sqrt(np.maximum(P_avg, 1e-30)).astype(complex)   # 위상 0
        f_a, mag_a, _pw, _pu, _grp = _tf_smooth(freqs, H_mag, bpo)
        coh_a = np.interp(f_a, freqs, coh_avg).astype(np.float32)
        return {'mode': 'mag', 'n': n, 'f': f_a, 'mag': mag_a, 'coh': coh_a,
                'ph_wrap': None, 'ph_unwr': None, 'grp': None, 'h_ir': None}
    # complex (vector) 평균.
    # 입력 H는 각 카드가 표시하는 **정렬된(딜레이 제거)** 복소값이다(캡쳐 평균과 동일 전제).
    # align=True(기본): 정렬 상태 그대로 평균 → 응답 모양만, 콤필터 없음.
    # align=False: 카드 딜레이를 되살려(exp(-jωτ)) 실제 도착차 복원 → 콤필터 그대로 보임.
    acc = np.zeros(len(freqs), dtype=complex)
    for h, d in zip(Hs, delays):
        if (not align) and d:
            h = h * np.exp(-1j * 2 * np.pi * freqs * (float(d) / 1000.0))
        acc = acc + h
    H_avg = acc / n
    f_a, mag_a, pw_a, pu_a, grp_a = _tf_smooth(freqs, H_avg, bpo)
    coh_a = np.interp(f_a, freqs, coh_avg).astype(np.float32)
    fft_size = (len(freqs) - 1) * 2
    h_ir = np.fft.fftshift(np.fft.irfft(H_avg, n=fft_size)).astype(np.float32)
    return {'mode': 'complex', 'n': n, 'f': f_a, 'mag': mag_a, 'coh': coh_a,
            'ph_wrap': pw_a, 'ph_unwr': pu_a, 'grp': grp_a, 'h_ir': h_ir}


def _hilbert_env(x):
    """FFT 기반 Hilbert 포락선 (scipy 불필요)."""
    N = len(x)
    X = np.fft.fft(x)
    h = np.zeros(N, dtype=np.float64)
    if N % 2 == 0:
        h[0] = 1; h[N // 2] = 1; h[1:N // 2] = 2
    else:
        h[0] = 1; h[1:(N + 1) // 2] = 2
    return np.abs(np.fft.ifft(X * h)).astype(np.float32)
