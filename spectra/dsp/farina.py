"""Farina 지수 스윕(ESS) 측정 — 순수 DSP.

v2.0 분해: wayaudo2.py에서 이동(동작 0 변경). ESS 생성/역필터/디컨볼루션→선형 H·IR·THD·SNR.
골든: tests/test_dsp_golden.py::test_farina_* / test_gen_ess_properties.
"""
import numpy as np


def _gen_ess(T, f1, f2, sr, fade=0.01):
    """Farina exponential sine sweep.  x(t)=sin[2π·f1·L·(e^{t/L}-1)], L=T/ln(f2/f1)."""
    N = int(round(T * sr))
    t = np.arange(N, dtype=np.float64) / sr
    L = T / np.log(f2 / f1)
    x = np.sin(2 * np.pi * f1 * L * (np.exp(t / L) - 1.0))
    nf = int(fade * sr)
    if nf > 0 and N > 2 * nf:
        w_ = np.ones(N)
        w_[:nf] = np.linspace(0, 1, nf); w_[-nf:] = np.linspace(1, 0, nf)
        x = x * w_
    return x.astype(np.float64)


def _ess_inverse(x, T, f1, f2, sr):
    """Farina inverse filter: time-reversed sweep × +6 dB/oct amplitude envelope.
    Convolving the measured response with this yields an IR whose linear part is at
    the matched-filter peak and whose nth harmonic sits Δt_n = L·ln(n) earlier."""
    N = len(x)
    L = T / np.log(f2 / f1)
    k = np.arange(N, dtype=np.float64)
    finst = f1 * np.exp((k / sr) / L)        # instantaneous freq of the forward sweep
    env = finst / finst[0]                    # ∝ frequency  → +6 dB/oct
    inv = x[::-1] * env[::-1]
    # normalize so an identity system gives unit-height linear peak
    peak = np.max(np.abs(_fft_convolve(x, inv)))
    if peak > 0:
        inv = inv / peak
    return inv


def _fft_convolve(a, b):
    """Linear convolution via FFT (full), float64."""
    n = len(a) + len(b) - 1
    nfft = 1 << (int(n - 1).bit_length())
    A = np.fft.rfft(a, nfft); B = np.fft.rfft(b, nfft)
    return np.fft.irfft(A * B, nfft)[:n]


_FARINA_ANALYSIS_S = 0.25   # fixed linear-IR analysis window (seconds) → grid & IR length independent of sweep length
_FARINA_PRE_S      = 0.05   # fixed pre-peak guard (seconds) → same window offset at any sweep length (capped by 0.5·dt2)
_FARINA_TAIL_S     = 0.05   # fixed post-peak tail (seconds) → same reflections/decay captured at any sweep length


def _band_taper(freqs, f1, f2, oct_frac=1.0):
    """Raised-cosine band-edge taper (1 in-band, cosine rolloff to 0 over `oct_frac`
    octave OUTSIDE each band edge). Replaces a hard band cut to suppress Gibbs ringing in
    the IR. The swept band [f1,f2] itself stays flat (=1); only out-of-band edges roll off."""
    r = 2.0 ** oct_frac
    tap = np.ones_like(freqs, dtype=np.float64)
    lo_a, lo_b = f1 / r, f1
    hi_a, hi_b = f2, f2 * r
    tap[freqs < lo_a] = 0.0
    m = (freqs >= lo_a) & (freqs < lo_b)
    if lo_b > lo_a:
        tap[m] = 0.5 * (1.0 - np.cos(np.pi * (freqs[m] - lo_a) / (lo_b - lo_a)))
    tap[freqs > hi_b] = 0.0
    m = (freqs > hi_a) & (freqs <= hi_b)
    if hi_b > hi_a:
        tap[m] = 0.5 * (1.0 + np.cos(np.pi * (freqs[m] - hi_a) / (hi_b - hi_a)))
    return tap


def _wiener_match_scale(far, hw_on, rel_floor_db=-30.0):
    """Scale that aligns the sweep's Farina magnitude to the Wiener (Meas/Ref) level.

    Median of hw/far taken ONLY over bins where BOTH are reliable — within `rel_floor_db`
    of their band peak. The windowed Farina |H| (`far`) and the full-array Wiener |H|
    (`hw_on`) have different processing gain, so at frequencies the measurement can't resolve
    (HF noise floor) `far` collapses while `hw_on` doesn't; including those bins makes hw/far
    blow up and skews the median. A shorter (1 s) sweep collapses at a lower frequency than a
    long (2 s) one, so the skew was duration-dependent → a spurious 1 s-vs-2 s level offset.
    """
    far = np.asarray(far, dtype=np.float64); hw = np.asarray(hw_on, dtype=np.float64)
    if far.size == 0:
        return 1.0
    ff = 10.0 ** (rel_floor_db / 20.0)
    v = (far > far.max() * ff) & (hw > hw.max() * ff) & (far > 1e-12) & (hw > 1e-12)
    if not np.any(v):
        v = (far > 1e-9) & (hw > 1e-9)          # fallback: nothing passed the floor gate
        if not np.any(v):
            return 1.0
    return float(np.median(hw[v] / far[v]))


def farina_analyze(y, x, sr, T, f1, f2, harmonics=(2, 3, 4, 5)):
    """Deconvolve an ESS measurement into linear transfer function + harmonic IRs.

    y : measured response, x : reference sweep (same as played).
    Returns dict: freqs, H (linear complex TF), ir (linear IR, 0-centered t_ms),
    t_ms, harmonics {n:(t_peak_ms, mag_at_fund)}, thd (percent vs freq), snr_db.
    Pure DSP — headless-testable.
    """
    x = np.asarray(x, dtype=np.float64); y = np.asarray(y, dtype=np.float64)
    N = len(x)
    L = T / np.log(f2 / f1)
    inv = _ess_inverse(x, T, f1, f2, sr)
    g = _fft_convolve(y, inv)              # measured IR (linear peak + harmonics before it)
    g_ref = _fft_convolve(x, inv)          # identity reference (delta at n0_ref)
    n0_ref = int(np.argmax(np.abs(g_ref)))  # zero-delay reference peak
    # Measured linear peak = strongest peak at/after the reference position. This absorbs
    # the system/round-trip delay (a high-latency duplex stream can lag >100ms, far past
    # the analysis window — pinning to n0_ref would put the real peak OUTSIDE it and make
    # THD/SNR garbage). Harmonics sit BEFORE the linear peak, so we search forward only.
    _s0 = max(0, n0_ref - int(0.005 * sr))
    n0 = _s0 + int(np.argmax(np.abs(g[_s0:])))

    # harmonic peak positions: nth harmonic is Δt_n = L·ln(n) earlier
    dt = {n: L * np.log(n) for n in harmonics}
    # Fixed REAL window around the linear peak — SAME pre AND tail (in seconds) for every sweep
    # length, so 1s and 2s capture the identical impulse incl. its post-impulse tail
    # (reflections/decay). Then zero-pad to nwin for a T-independent frequency grid + IR length.
    # The pre-peak guard is a fixed duration, only shortened if a very short/narrow sweep would
    # let it reach the 2nd-harmonic arrival (0.5·dt2). (Earlier `pre` scaled with T, pushing the
    # peak late in a fixed buffer and clipping the tail for long sweeps → LF divergence.) [SWEEP_FIXED_RES]
    nwin = int(round(_FARINA_ANALYSIS_S * sr))
    pre = min(int(_FARINA_PRE_S * sr), int(0.5 * dt[2] * sr))
    pre = max(pre, int(0.002 * sr))
    tail = int(_FARINA_TAIL_S * sr)
    lo = max(0, n0 - pre); hi = min(len(g), n0 + tail)
    lin = g[lo:hi]
    # reference window taken around ITS OWN peak so the deconvolution bins line up
    lo_r = max(0, n0_ref - pre); hi_r = min(len(g_ref), n0_ref + tail)
    lin_ref = g_ref[lo_r:hi_r]
    la = min(len(lin), len(lin_ref)); lin = lin[:la]; lin_ref = lin_ref[:la]
    def _fit(a):
        if len(a) >= nwin: return a[:nwin]
        b = np.zeros(nwin, dtype=a.dtype); b[:len(a)] = a; return b
    lin = _fit(lin); lin_ref = _fit(lin_ref)
    H = np.fft.rfft(lin) / (np.fft.rfft(lin_ref) + 1e-30)
    freqs = np.fft.rfftfreq(nwin, 1.0 / sr)
    # Restrict to the swept band with a raised-cosine taper (not a hard cut) — the step
    # discontinuity of a hard band cut causes Gibbs ringing in the reconstructed IR. [SWEEP_BAND_TAPER]
    H = H * _band_taper(freqs, f1, f2)

    # 0-centered linear IR for the IR canvas
    ir = np.fft.fftshift(np.fft.irfft(H, n=nwin)).astype(np.float32)
    t_ms = (np.arange(nwin) - nwin // 2) / sr * 1000.0

    # harmonic IR peaks + magnitude
    harm = {}
    half = int(0.5 * (dt[2] * sr))
    for n in harmonics:
        center = n0 - int(round(dt[n] * sr))
        a = max(0, center - half // 2); b = min(len(g), center + half // 2)
        if b - a < 8:
            continue
        seg = g[a:b]
        harm[n] = (float((center - n0) / sr * 1000.0), float(np.max(np.abs(seg))))

    # THD(%) vs frequency: ratio of summed harmonic energy to fundamental
    lin_peak = float(np.max(np.abs(g[lo:hi])))
    if lin_peak > 0 and len(harm) > 0:
        h_sum = np.sqrt(sum(v[1] ** 2 for v in harm.values()))
        thd = 100.0 * h_sum / lin_peak
    else:
        thd = 0.0

    # crude SNR: linear-window energy vs out-of-window residual
    resid = np.concatenate([g[:lo], g[hi:]])
    noise = float(np.sqrt(np.mean(resid ** 2))) if len(resid) else 1e-9
    sig = float(np.sqrt(np.mean(g[lo:hi] ** 2)))
    snr_db = 20 * np.log10(max(sig, 1e-12) / max(noise, 1e-12))

    return {"freqs": freqs, "H": H, "ir": ir, "t_ms": t_ms,
            "harmonics": harm, "thd": thd, "snr_db": snr_db, "n0": n0, "L": L,
            "g": g}
