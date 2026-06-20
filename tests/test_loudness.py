"""Headless TDD tests for LoudnessMeter DSP (EBU R128 / BS.1770-4 + EBU 3342 LRA).

Run:  python3 tests/test_loudness.py
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
    if cond: PASS += 1; print(f"  PASS  {name}")
    else: FAIL += 1; print(f"  FAIL  {name}  {detail}")

SR = 48000
def noise(amp, secs, rng):
    n = int(SR * secs)
    x = (rng.standard_normal(n) * amp).astype(np.float32)
    return x, x.copy()

def feed(meter, L, R, blk=4800):
    for i in range(0, len(L), blk):
        meter.push(L[i:i+blk], R[i:i+blk])


def test_lra_steady_near_zero():
    """Steady level → loudness range ~0 (no quiet/loud variation)."""
    m = w.LoudnessMeter(SR); m.start_integration()
    rng = np.random.default_rng(0)
    L, R = noise(0.1, 12.0, rng)
    feed(m, L, R)
    check("LRA steady ~ 0 (<1.5 LU)", m.LRA < 1.5, f"LRA={m.LRA:.2f}")


def test_lra_two_levels_ebu3342():
    """Two sustained levels 10 dB apart over the whole program → LRA ~ 10 LU.
    Current code (last-3s window only) collapses to ~0 → this drives the EBU-3342 fix."""
    m = w.LoudnessMeter(SR); m.start_integration()
    rng = np.random.default_rng(1)
    lo_L, lo_R = noise(0.03, 6.0, rng)     # quiet
    hi_L, hi_R = noise(0.03 * (10 ** (10/20)), 6.0, rng)  # +10 dB
    L = np.concatenate([lo_L, hi_L, lo_L, hi_L])
    R = np.concatenate([lo_R, hi_R, lo_R, hi_R])
    feed(m, L, R)
    check("LRA two-level ~ 10 LU (EBU3342, program-wide)", 7.0 < m.LRA < 13.0,
          f"LRA={m.LRA:.2f} (expected ~10)")


def test_lra_absolute_gate():
    """Long silence (< -70 LUFS) must not inflate LRA."""
    m = w.LoudnessMeter(SR); m.start_integration()
    rng = np.random.default_rng(2)
    sig_L, sig_R = noise(0.1, 6.0, rng)
    sil_L, sil_R = noise(1e-6, 6.0, rng)   # effectively silent (< -70)
    L = np.concatenate([sig_L, sil_L]); R = np.concatenate([sig_R, sil_R])
    feed(m, L, R)
    # absolute gate must prevent the deep silence (ST ~ -117) from exploding LRA.
    # Ungated this is ~100 LU; gated it collapses to the transition's modest range (<12).
    check("LRA absolute gate prevents explosion (<12, ungated ~100)", m.LRA < 12.0,
          f"LRA={m.LRA:.2f}")


def test_plr_psr():
    """PLR = TruePeak - Integrated, PSR = TruePeak - Short-term."""
    m = w.LoudnessMeter(SR); m.start_integration()
    rng = np.random.default_rng(3)
    L, R = noise(0.2, 8.0, rng)
    feed(m, L, R)
    check("PLR == TP - I", abs(m.PLR - (m.TP - m.I)) < 1e-6, f"PLR={m.PLR:.2f} TP-I={m.TP-m.I:.2f}")
    check("PSR == TP - S", abs(m.PSR - (m.TP - m.S)) < 1e-6, f"PSR={m.PSR:.2f} TP-S={m.TP-m.S:.2f}")
    check("PLR positive for normal signal", m.PLR > 0, f"PLR={m.PLR:.2f}")


def test_max_momentary_short():
    """Max Momentary / Max Short-term track the peak of M/S over the program."""
    m = w.LoudnessMeter(SR); m.start_integration()
    rng = np.random.default_rng(4)
    quiet_L, quiet_R = noise(0.02, 4.0, rng)
    loud_L, loud_R = noise(0.3, 4.0, rng)
    feed(m, quiet_L, quiet_R); peak_after_loud_M = None
    feed(m, loud_L, loud_R)
    feed(m, quiet_L, quiet_R)   # back to quiet — max must persist
    check("MaxM >= current M", m.MaxM >= m.M - 1e-6, f"MaxM={m.MaxM:.2f} M={m.M:.2f}")
    check("MaxS >= current S", m.MaxS >= m.S - 1e-6, f"MaxS={m.MaxS:.2f} S={m.S:.2f}")
    check("MaxM reflects the loud section (> -30)", m.MaxM > -30, f"MaxM={m.MaxM:.2f}")


if __name__ == "__main__":
    print("== LoudnessMeter tests ==")
    for fn in [test_lra_steady_near_zero, test_lra_two_levels_ebu3342, test_lra_absolute_gate,
               test_plr_psr, test_max_momentary_short]:
        print(f"\n[{fn.__name__}]")
        try: fn()
        except Exception as e:
            FAIL += 1; print(f"  FAIL  {fn.__name__} raised {e!r}")
    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)
