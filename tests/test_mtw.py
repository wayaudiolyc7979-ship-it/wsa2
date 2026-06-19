"""Headless TDD tests for the MTW (Multi-Time-Window) transfer-function engine.

Run:  python3 tests/test_mtw.py
Imports wayaudo2 offscreen with isolated settings paths (never touches user files).
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


def test_single_stage_pure_gain():
    """n_stages=1, meas = gain*ref → flat magnitude = 20log10(gain), coh = 1."""
    sr = 48000
    eng = w.MTWEngine(sample_rate=sr, n_fft=8192, n_stages=1)
    gain = 0.5  # -6.0206 dB
    rng = np.random.default_rng(0)
    master = eng.master_len
    for _ in range(20):
        ref = rng.standard_normal(master).astype(np.float32)
        meas = (gain * ref).astype(np.float32)
        eng.push(ref, meas)
    f, H, coh = eng.result()
    band = (f >= 100) & (f <= 18000)
    mag_db = 20 * np.log10(np.abs(H) + 1e-30)
    err = np.max(np.abs(mag_db[band] - 20 * np.log10(gain)))
    check("single-stage pure gain: flat magnitude within 0.1 dB", err < 0.1,
          f"max err = {err:.3f} dB")
    check("single-stage pure gain: coherence ~ 1", np.min(coh[band]) > 0.999,
          f"min coh = {np.min(coh[band]):.4f}")


def test_single_stage_known_filter():
    """n_stages=1, meas = zero-phase lowpass(ref) → recovered |H| matches theory."""
    sr = 48000
    eng = w.MTWEngine(sample_rate=sr, n_fft=8192, n_stages=1)
    fc = 2000.0
    rng = np.random.default_rng(1)
    master = eng.master_len
    freqs_axis = np.fft.rfftfreq(master, 1.0 / sr)
    Hmag = 1.0 / np.sqrt(1.0 + (freqs_axis / fc) ** 2)  # 1-pole magnitude, zero phase
    for _ in range(40):
        ref = rng.standard_normal(master).astype(np.float64)
        meas = np.fft.irfft(np.fft.rfft(ref) * Hmag, n=master)
        eng.push(ref.astype(np.float32), meas.astype(np.float32))
    f, H, coh = eng.result()
    mag_db = 20 * np.log10(np.abs(H) + 1e-30)
    worst = 0.0
    for ftest in [200, 500, 1000, 2000, 5000, 10000]:
        i = int(np.argmin(np.abs(f - ftest)))
        theory = 20 * np.log10(1.0 / np.sqrt(1.0 + (ftest / fc) ** 2))
        err = abs(mag_db[i] - theory)
        worst = max(worst, err)
    check("known filter: recovered magnitude within 0.5 dB across band", worst < 0.5,
          f"max err = {worst:.3f} dB")


def test_multistage_low_freq_resolution():
    """Multi-stage MTW resolves a sharp low-frequency feature better than a single
    same-size FFT at full rate. Put a narrow notch at 60 Hz; the low stage (lower SR,
    finer bins) must capture the dip depth a single 8192 FFT at 48k would smear out."""
    sr = 48000
    fc = 60.0
    rng = np.random.default_rng(2)

    def make_meas(ref, axis):
        # sharp notch at 60 Hz, Q-ish: depth controlled by gaussian in log-freq
        Hmag = 1.0 - 0.9 * np.exp(-((axis - fc) ** 2) / (2 * (3.0) ** 2))
        return np.fft.irfft(np.fft.rfft(ref) * Hmag, n=len(ref))

    eng = w.MTWEngine(sample_rate=sr, n_fft=8192, n_stages=8)
    master = eng.master_len
    axis = np.fft.rfftfreq(master, 1.0 / sr)
    for _ in range(40):
        ref = rng.standard_normal(master).astype(np.float64)
        meas = make_meas(ref, axis)
        eng.push(ref.astype(np.float32), meas.astype(np.float32))
    f, H, coh = eng.result()
    mag_db = 20 * np.log10(np.abs(H) + 1e-30)
    i60 = int(np.argmin(np.abs(f - fc)))
    dip = mag_db[i60]
    # true notch depth at 60 Hz is 20log10(0.1) = -20 dB; MTW low stage should get deep
    check("multistage: 60 Hz notch resolved deeper than -10 dB", dip < -10.0,
          f"dip at 60 Hz = {dip:.2f} dB (true -20)")
    # output must span the full band
    check("multistage: output covers 20 Hz..18 kHz",
          f[0] <= 20 and f[-1] >= 18000, f"f range = {f[0]:.1f}..{f[-1]:.1f}")


if __name__ == "__main__":
    print("== MTW engine tests ==")
    for fn in [test_single_stage_pure_gain, test_single_stage_known_filter,
               test_multistage_low_freq_resolution]:
        print(f"\n[{fn.__name__}]")
        fn()
    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)
