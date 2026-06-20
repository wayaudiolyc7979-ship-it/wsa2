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


if __name__ == "__main__":
    print("== Farina ESS engine tests ==")
    for fn in [test_ess_generation, test_identity_system_flat,
               test_known_filter_recovery, test_harmonic_separation]:
        print(f"\n[{fn.__name__}]")
        fn()
    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)
