"""Headless TDD tests for the Farina exponential-sine-sweep (ESS) engine.

Run:  python3 tests/test_farina.py
"""
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("WSA2_SETTINGS_PATH", "/tmp/wsa2_test_settings.json")
os.environ.setdefault("WSA2_CAPTURES_PATH", "/tmp/wsa2_test_captures.json")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import wayaudo2 as w

PASS, FAIL = 0, 0
def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1; print(f"  PASS  {name}")
    else:
        FAIL += 1; print(f"  FAIL  {name}  {detail}")


SR = 48000
T = 2.0
F1, F2 = 20.0, 20000.0


def test_ess_generation():
    x = w._gen_ess(T, F1, F2, SR)
    check("ESS length = T*sr", len(x) == int(round(T * SR)), f"len={len(x)}")
    check("ESS amplitude bounded |x|<=1", np.max(np.abs(x)) <= 1.0 + 1e-6,
          f"max={np.max(np.abs(x)):.3f}")
    # instantaneous frequency at start ~ F1, near end ~ F2 (check via zero-crossing density)
    head = x[:SR // 10]; tail = x[-SR // 10:]
    zc_head = np.sum(np.abs(np.diff(np.sign(head)))) / 2
    zc_tail = np.sum(np.abs(np.diff(np.sign(tail)))) / 2
    check("ESS sweeps low→high (tail has more zero-crossings)", zc_tail > zc_head * 5,
          f"zc_head={zc_head:.0f} zc_tail={zc_tail:.0f}")


def test_identity_system_flat():
    """y = x (perfect identity) → recovered linear magnitude flat ~0 dB across band."""
    x = w._gen_ess(T, F1, F2, SR)
    y = x.copy()
    res = w.farina_analyze(y, x, SR, T, F1, F2)
    f = res["freqs"]; H = res["H"]
    mag = 20 * np.log10(np.abs(H) + 1e-30)
    band = (f >= 100) & (f <= 10000)
    err = np.max(np.abs(mag[band]))
    check("identity system: flat magnitude within 0.5 dB", err < 0.5,
          f"max |mag| = {err:.3f} dB")


def test_known_filter_recovery():
    """y = lowpass(ref) → recovered |H| matches scipy freqz theory within tolerance."""
    from scipy.signal import firwin, freqz
    x = w._gen_ess(T, F1, F2, SR)
    h_known = firwin(257, 2000.0, fs=SR)          # linear-phase LP @ 2 kHz
    y = w._fft_convolve(x, h_known)
    res = w.farina_analyze(y, x, SR, T, F1, F2)
    f = res["freqs"]; H = res["H"]
    mag = 20 * np.log10(np.abs(H) + 1e-30)
    wfr, hfr = freqz(h_known, worN=4096, fs=SR)
    worst = 0.0
    for ftest in [200, 500, 1000, 1500, 2000, 3000]:
        i = int(np.argmin(np.abs(f - ftest)))
        j = int(np.argmin(np.abs(wfr - ftest)))
        theory = 20 * np.log10(np.abs(hfr[j]) + 1e-30)
        worst = max(worst, abs(mag[i] - theory))
    check("known LP filter: recovered magnitude within 1.5 dB", worst < 1.5,
          f"max err = {worst:.3f} dB")


def test_harmonic_separation():
    """Memoryless nonlinearity y=x+a2·x²+a3·x³ → 2nd/3rd harmonic IRs appear at
    Δt_n=L·ln(n) before the linear peak, and THD rises vs the clean case."""
    x = w._gen_ess(T, F1, F2, SR)
    res_lin = w.farina_analyze(x.copy(), x, SR, T, F1, F2)
    a2, a3 = 0.1, 0.05
    y = x + a2 * x ** 2 + a3 * x ** 3
    res = w.farina_analyze(y, x, SR, T, F1, F2)

    g = res["g"]; n0 = res["n0"]; L = res["L"]
    # scan for the strongest peaks strictly before the linear peak
    region = np.abs(g[:n0 - int(0.001 * SR)])
    # expected positions
    dt2 = L * np.log(2); dt3 = L * np.log(3)
    i2 = n0 - int(round(dt2 * SR)); i3 = n0 - int(round(dt3 * SR))
    win = int(0.01 * SR)
    p2 = np.max(region[max(0, i2 - win):i2 + win])
    p3 = np.max(region[max(0, i3 - win):i3 + win])
    floor = np.median(region)
    check("2nd harmonic peak present at L·ln(2) before linear", p2 > 8 * floor,
          f"p2={p2:.3e} floor={floor:.3e}")
    check("3rd harmonic peak present at L·ln(3) before linear", p3 > 8 * floor,
          f"p3={p3:.3e} floor={floor:.3e}")
    check("THD rises with injected distortion (>5× clean)",
          res["thd"] > 5 * max(res_lin["thd"], 1e-6),
          f"thd_dist={res['thd']:.3f}% thd_clean={res_lin['thd']:.4f}%")


def test_fixed_resolution_across_sweep_length():
    """v1.8 ①: the same system measured with 1s/2s/4s sweeps must yield an
    IDENTICAL analysis frequency grid and IR length, so overlaid captures line up
    regardless of sweep duration. (Was T-dependent: nwin ∝ sweep length.)"""
    grids = []; irlens = []
    for T in (1.0, 2.0, 4.0):
        x = w._gen_ess(T, F1, F2, SR)
        res = w.farina_analyze(x.copy(), x, SR, T, F1, F2)
        grids.append(res["freqs"]); irlens.append(len(res["ir"]))
    n0 = len(grids[0])
    check("analysis grid length identical across 1s/2s/4s",
          all(len(g) == n0 for g in grids), f"lens={[len(g) for g in grids]}")
    check("frequency grid values identical across 1s/2s/4s",
          all(len(g) == n0 and np.allclose(g, grids[0]) for g in grids),
          f"Δf={[round(float(g[1]-g[0]),2) for g in grids]}")
    check("IR length identical across 1s/2s/4s",
          len(set(irlens)) == 1, f"irlens={irlens}")


def test_band_edge_taper_reduces_ringing():
    """v1.8 ②: hard-zeroing H outside the swept band causes Gibbs ringing in the IR tail.
    A band-edge taper must keep the tail (beyond the ±3 ms main lobe) low (< -45 dB rel
    peak). Band-limited identity: hard cut rings at ~-38 dB, taper reaches ~-47 dB."""
    f1, f2, T = 100.0, 8000.0, 2.0
    x = w._gen_ess(T, f1, f2, SR)
    res = w.farina_analyze(x.copy(), x, SR, T, f1, f2)
    ir = np.abs(res["ir"]); pk = int(np.argmax(ir)); peak = ir[pk]
    n = int(0.003 * SR)   # exclude the ±3 ms main lobe → measure the tail ringing only
    far = ir.copy(); far[max(0, pk - n):pk + n] = 0
    ring_db = 20 * np.log10(far.max() / peak + 1e-30)
    check("band-limited IR tail ring below -45 dB rel peak", ring_db < -45.0,
          f"ring={ring_db:.1f} dB")


def test_duration_independent_response():
    """v1.8 ① (regression): the SAME system measured at 1s vs 2s must give the SAME
    response — not just the same grid. A system with post-impulse tail (reflection/decay)
    must not be truncated differently by sweep length. (Bug: the pre-peak guard scaled
    with T, so a 2s window pushed the peak late and clipped the tail → LF divergence.)"""
    f1, f2 = 50.0, 1000.0                       # narrow band → long window (truncation-prone)
    def system(x):                              # direct + 30 ms echo (energy in the tail)
        y = x.copy(); d = int(0.030 * SR); y[d:] += 0.6 * x[:-d]; return y
    def analyze(T):
        n = int(T * SR); x = w._gen_ess(T, f1, f2, SR)
        res = w.farina_analyze(system(x), x, SR, T, f1, f2)
        f = res["freqs"]; mag = 20 * np.log10(np.abs(res["H"]) + 1e-30)
        return f, mag
    f, m1 = analyze(1.0); _, m2 = analyze(2.0)
    band = (f > 100) & (f < 800)
    d = m1[band] - m2[band]
    check("1s vs 2s same response within 1 dB (echo system, narrow band)",
          np.max(np.abs(d)) < 1.0, f"max|Δ|={np.max(np.abs(d)):.2f} dB  mean={d.mean():+.2f}")


def test_level_match_robust_to_hf_crash():
    """v1.8 (root cause of the 1s-vs-2s level offset): the sweep level-match scale must be
    unaffected by a crashed/noise-floor region where the windowed Farina |H| collapses but the
    full-array Wiener |H| stays intact. Otherwise hw/far blows up there and skews the scale —
    and since a 1s sweep collapses at a lower frequency than a 2s sweep, the offset is
    duration-dependent (measured ~5 dB on hardware)."""
    fr = np.fft.rfftfreq(4096, 1.0 / SR)
    trueH = 10 ** ((-20 - 0.0008 * fr) / 20.0)   # gentle HF rolloff, same "system"
    hw = trueH.copy()
    far_clean = trueH.copy()
    far_crash = trueH.copy()
    crash = (fr >= 4000) & (fr <= 8000)          # windowed Farina collapses here (1s-style)
    far_crash[crash] = 10 ** (-65 / 20.0)
    s_clean = w._wiener_match_scale(far_clean, hw)
    s_crash = w._wiener_match_scale(far_crash, hw)
    off = 20 * np.log10(s_crash / s_clean)
    check("level-match scale unchanged by crashed HF region (< 0.5 dB)", abs(off) < 0.5,
          f"offset={off:+.2f} dB (clean vs crashed)")


if __name__ == "__main__":
    print("== Farina ESS engine tests ==")
    for fn in [test_ess_generation, test_identity_system_flat,
               test_known_filter_recovery, test_harmonic_separation,
               test_fixed_resolution_across_sweep_length,
               test_band_edge_taper_reduces_ringing,
               test_duration_independent_response,
               test_level_match_robust_to_hf_crash]:
        print(f"\n[{fn.__name__}]")
        fn()
    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)
