"""DSP 골든값 회귀 테스트 (SPECTRA v2.0 Phase A).

순수 DSP 함수(Qt 무관)의 입력→출력을 고정한다. v2.0 파일 분해(`spectra/dsp/`)나
반사 게이팅 등 DSP 변경 시 **측정값이 조용히 틀어지는 것**을 잡는 안전망.

값의 성격:
  - 물리 앵커: 표준으로 옳은 값(A가중 1kHz=0dB, 게인2→+6.02dB, 게인0.5→−6.02dB 등).
    분해뿐 아니라 '정확성' 자체를 검증.
  - 회귀 락: 현재 구현의 출력을 고정(노이즈 플로어·THD 등). 변경 감지용.

격리 필수(CLAUDE.md): 사용자 실제 settings/captures 를 절대 건드리지 않도록 임시경로 강제.
"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['WSA2_SETTINGS_PATH'] = '/tmp/wsa2_pytest_settings.json'   # setdefault 아님 — 강제 격리
os.environ['WSA2_CAPTURES_PATH'] = '/tmp/wsa2_pytest_captures.json'

import importlib.util
import numpy as np
import pytest
from scipy.signal import butter, lfilter, freqz

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location('wayaudo2_dsp', os.path.join(_ROOT, 'wayaudo2.py'))
w = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(w)

SR = 48000

# 알려진 시스템(모양 락용): 2차 버터워스 저역통과 2kHz
_LP_B, _LP_A = butter(2, 2000/(SR/2), 'low')
_TEST_F = np.array([200.0, 1000.0, 4000.0])
_LP_TRUTH_DB = 20*np.log10(np.abs(freqz(_LP_B, _LP_A, worN=_TEST_F*2*np.pi/SR)[1]))  # ≈[0,-0.26,-12.59]


# ── 1. A/C 가중 (IEC 61672 표준 물리 앵커) ────────────────────────────
@pytest.mark.parametrize('f,expected', [
    (31.5, -39.53), (100.0, -19.15), (1000.0, 0.0), (10000.0, -2.49),
])
def test_a_weight_db(f, expected):
    assert w.a_weight_db(f) == pytest.approx(expected, abs=0.05)


@pytest.mark.parametrize('f,expected', [
    (31.5, -3.03), (100.0, -0.30), (1000.0, 0.0), (10000.0, -4.40),
])
def test_c_weight_db(f, expected):
    assert w.c_weight_db(f) == pytest.approx(expected, abs=0.05)


# ── 2. power_spectrum_db — 1kHz 풀스케일 사인(n=4800→10Hz/bin, bin100) ─
def test_power_spectrum_db_tone():
    n = 4800
    buf = np.sin(2*np.pi*1000*np.arange(n)/SR).astype(np.float32)
    ps = w.power_spectrum_db(buf)
    assert len(ps) == 2401
    assert int(np.argmax(ps)) == 100                     # 1000Hz = bin100
    assert float(ps[100]) == pytest.approx(-4.77, abs=0.1)   # 회귀 락(단일 빈 피크)
    assert float(ps[50]) < -100.0                        # 톤 밖은 바닥


# ── 3. _octave_bands — 1kHz 톤의 1/3옥 밴드파워 = FS사인 −3dBFS ────────
def test_octave_bands_tone():
    n = 4800
    buf = np.sin(2*np.pi*1000*np.arange(n)/SR).astype(np.float32)
    ps = w.power_spectrum_db(buf)
    freqs = np.fft.rfftfreq(n, 1.0/SR)
    oc = w._octave_bands(freqs, ps, 'oct3')
    b1k = int(np.argmin(np.abs(np.array(w.BANDS['oct3'])-1000)))
    assert len(oc) == 31
    assert float(oc[b1k]) == pytest.approx(-3.01, abs=0.1)   # 밴드합=−3dBFS(물리 앵커)


# ── 4. _tf_smooth — H=2(순수 게인) → +6.02dB, 위상 0 ──────────────────
def test_tf_smooth_pure_gain():
    fz = np.linspace(20, 20000, 2000).astype(np.float64)
    H2 = np.full(len(fz), 2.0+0j)
    f_o, mag_o, pw_, pu_, grp_ = w._tf_smooth(fz, H2, 6)
    mid = int(np.argmin(np.abs(f_o-1000)))
    assert float(mag_o[mid]) == pytest.approx(6.02, abs=0.05)    # 20log10(2)
    assert float(pw_[mid]) == pytest.approx(0.0, abs=0.01)


# ── 5. MTWEngine — meas=2*ref(게인2) → +6.02dB 평탄, 코히 1.0 ─────────
def test_mtw_pure_gain():
    eng = w.MTWEngine(SR, n_fft=4096, n_stages=5)
    rng = np.random.RandomState(42)
    ml = eng.master_len
    for _ in range(30):
        ref = rng.randn(ml)
        eng.push(ref, 2.0*ref)
    f_m, H_m, coh_m = eng.result()
    assert len(f_m) == 800
    band = (f_m >= 100) & (f_m <= 10000)
    mag_db = 20*np.log10(np.abs(H_m[band]))
    assert float(np.mean(mag_db)) == pytest.approx(6.02, abs=0.05)
    assert float(np.std(mag_db)) < 0.01           # 순수 게인 → 평탄
    assert float(np.mean(coh_m[band])) > 0.999    # 완전 상관 → 코히 1


# ── 6. Farina — y=0.5*x(선형 −6dB) → −6.02dB 평탄, THD≈0 ──────────────
def test_farina_pure_gain():
    T, f1, f2 = 0.5, 20.0, 20000.0
    x = w._gen_ess(T, f1, f2, SR)
    res = w.farina_analyze(0.5*x, x, SR, T, f1, f2)
    Hf, ff = res['H'], res['freqs']
    band = (ff >= 100) & (ff <= 10000)
    mag = 20*np.log10(np.abs(Hf[band]) + 1e-12)
    assert float(np.mean(mag)) == pytest.approx(-6.02, abs=0.1)
    assert float(res['thd']) < 0.5                # 선형 → THD 거의 0 (%)
    assert float(res['snr_db']) > 40.0            # 회귀 락


# ── 7. LoudnessMeter (BS.1770) — 1kHz 스테레오 사인 A=0.5 ──────────────
def test_loudness_1khz_tone():
    m = w.LoudnessMeter(SR); m.start_integration()
    N = int(1.5*SR)
    sig = (0.5*np.sin(2*np.pi*1000*np.arange(N)/SR)).astype(np.float32)
    for i in range(0, N, 4800):
        m.push(sig[i:i+4800], sig[i:i+4800])
    assert m._M == pytest.approx(-6.01, abs=0.1)   # Momentary
    assert m._S == pytest.approx(-6.01, abs=0.1)   # Short-term
    assert m._I == pytest.approx(-6.01, abs=0.1)   # Integrated
    assert m._TP == pytest.approx(-6.02, abs=0.1)  # True Peak = 20log10(0.5)


# ── 8. MTW — 알려진 저역통과 필터를 truth 대비 0.1dB 안에서 복원(모양 락) ─
def test_mtw_recovers_lowpass():
    eng = w.MTWEngine(SR, n_fft=4096, n_stages=5)
    rng = np.random.RandomState(11); ml = eng.master_len
    for _ in range(40):
        ref = rng.randn(ml)
        eng.push(ref, lfilter(_LP_B, _LP_A, ref))
    fm, Hm, _ = eng.result()
    est = 20*np.log10(np.abs(np.interp(_TEST_F, fm, Hm)))
    assert est == pytest.approx(_LP_TRUTH_DB, abs=0.1)


# ── 9. Farina — 알려진 저역통과 필터를 truth 대비 0.1dB 안에서 복원 ─────
def test_farina_recovers_lowpass():
    T, f1, f2 = 0.5, 20.0, 20000.0
    x = w._gen_ess(T, f1, f2, SR)
    res = w.farina_analyze(lfilter(_LP_B, _LP_A, x), x, SR, T, f1, f2)
    ff, Hf = res['freqs'], res['H']
    est = 20*np.log10(np.abs(np.interp(_TEST_F, ff, Hf)) + 1e-12)
    assert est == pytest.approx(_LP_TRUTH_DB, abs=0.1)


# ── 10. _tf_smooth — 저역통과 H 모양 유지(회귀 락) ────────────────────
def test_tf_smooth_lowpass_shape():
    fz = np.linspace(20, 20000, 4000)
    _, hz = freqz(_LP_B, _LP_A, worN=fz*2*np.pi/SR)
    fo, mago, _, _, _ = w._tf_smooth(fz.astype(np.float64), hz.astype(np.complex128), 6)
    got = [float(mago[int(np.argmin(np.abs(fo-f)))]) for f in _TEST_F]
    assert got == pytest.approx([-0.0, -0.263, -12.633], abs=0.1)


# ── 11. _biquad — 알려진 계수 임펄스응답 첫 5샘플(회귀 락) ─────────────
def test_biquad_impulse():
    out = w._biquad(np.array([1.0, 0, 0, 0, 0, 0, 0, 0]), _LP_B, _LP_A, np.zeros(2))
    assert list(out[:5]) == pytest.approx(
        [0.014401, 0.05232, 0.089895, 0.110665, 0.118634], abs=1e-5)


# ── 12. _gen_ess — 스윕 길이·RMS 성질 ───────────────────────────────
def test_gen_ess_properties():
    x = w._gen_ess(0.5, 20.0, 20000.0, SR)
    assert len(x) == int(0.5*SR)                       # T*sr
    assert float(np.sqrt(np.mean(x**2))) == pytest.approx(0.70, abs=0.02)


# ── 13. _KWeightFilter — BS.1770-4 계수 상수 락(오타/변조 방지) ────────
def test_kweight_coefficients_48k():
    k = w._KWeightFilter(48000)
    assert list(k._pb) == pytest.approx([1.53512486, -2.69169619, 1.19839281], abs=1e-8)
    assert list(k._pa) == pytest.approx([1.0, -1.69065929, 0.73248077], abs=1e-8)
    assert list(k._rb) == pytest.approx([1.0, -2.0, 1.0], abs=1e-12)
    assert list(k._ra) == pytest.approx([1.0, -1.99004745, 0.99007225], abs=1e-8)
