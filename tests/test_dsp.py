"""핵심 DSP 함수 골든값(특성화) 테스트 — 회귀 방지 + v2.0 분해 안전망.

'골든 테스트' = 지금의 올바른 계산 결과를 값으로 박제 → 앞으로 코드를 고쳐
계산이 바뀌면 즉시 실패로 알림. 순수 DSP(오디오 입력→숫자)만 대상, GUI 무관.

Run:  python3 -m pytest tests/test_dsp.py -q      (또는 python3 tests/test_dsp.py)

골든값은 2026-07-04 현재 검증된 출력에서 캡처됨. 값이 의도적으로 바뀌면
(알고리즘 개선 등) 여기 골든도 같이 갱신할 것.
"""
import os, sys, math
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("WSA2_SETTINGS_PATH", "/tmp/wsa2_test_dsp_settings.json")
os.environ.setdefault("WSA2_CAPTURES_PATH", "/tmp/wsa2_test_dsp_captures.json")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import wayaudo2 as w

SR = 48000


# ── power_spectrum_db : 소리 버퍼 → 빈별 dBFS ──────────────────────────────
def test_power_spectrum_db_fs_sine_peak():
    """풀스케일 1kHz 사인 → 피크가 1kHz 빈, 절대레벨 골든(-4.7713 dB).
    (Hanning 누설로 단일빈은 -3보다 낮음. ENBW 밴드합은 -3에 정합 = 별도 A/B 검증됨.)"""
    n = SR
    x = np.sin(2 * np.pi * 1000 * np.arange(n) / SR).astype(np.float32)
    db = w.power_spectrum_db(x)
    freqs = np.fft.rfftfreq(n, 1 / SR)
    assert len(db) == n // 2 + 1
    pk = int(np.argmax(db))
    assert freqs[pk] == 1000.0
    assert abs(db[pk] - (-4.7713)) < 0.02, db[pk]          # 골든


def test_power_spectrum_db_silence_floor():
    """무음 → 전 빈이 floor(1e-20 → -200 dB) 근처, +inf/NaN 없음."""
    db = w.power_spectrum_db(np.zeros(4096, dtype=np.float32))
    assert np.all(np.isfinite(db))
    assert db.max() <= -190.0


def test_power_spectrum_db_amplitude_scaling():
    """진폭 2배 → 모든 빈 +6.02 dB (파워 4배). 절대 정규화 불변식."""
    n = 8192
    base = np.sin(2 * np.pi * 1000 * np.arange(n) / SR).astype(np.float32)
    d1 = w.power_spectrum_db(base)
    d2 = w.power_spectrum_db(base * 2.0)
    pk = int(np.argmax(d1))
    assert abs((d2[pk] - d1[pk]) - 20 * math.log10(2)) < 0.01


# ── _octave_bands : 빈 dB → 옥타브 밴드 파워합 dB ──────────────────────────
def test_octave_bands_shape_and_golden():
    freqs = np.fft.rfftfreq(SR, 1 / SR)
    ob = np.asarray(w._octave_bands(freqs, np.zeros(len(freqs)), "oct3"))
    assert len(ob) == 31                                   # 1/3옥타브 밴드 수
    # 평탄 0dB 입력 → 파워합이라 고역일수록 빈 많아 상승(특성화 골든)
    np.testing.assert_allclose(ob[:3], [6.990, 7.782, 8.451], atol=0.02)


# ── _band_taper : 스윕 대역 경계 raised-cosine 테이퍼 ──────────────────────
def test_band_taper_passband_and_edges():
    fr = np.array([10, 20, 100, 1000, 20000, 30000.0])
    tp = np.asarray(w._band_taper(fr, 20, 20000, 1.0))
    np.testing.assert_allclose(tp, [0.0, 1.0, 1.0, 1.0, 1.0, 0.5], atol=1e-6)
    assert np.all((tp >= 0.0) & (tp <= 1.0))               # 항상 [0,1]


# ── _wiener_match_scale : 레벨매칭 스케일(무너진 HF 제외) ──────────────────
def test_wiener_match_scale_identity():
    """far==hw_on 이면 스케일≈1.0 (동일 신호는 그대로)."""
    far = np.abs(np.fft.rfft(np.random.RandomState(0).randn(2048)))
    s = w._wiener_match_scale(far, far)
    assert abs(s - 1.0) < 1e-9


def test_wiener_match_scale_ignores_crashed_hf():
    """HF가 노이즈플로어로 무너져도(피크 -30dB 이하) 스케일이 폭주 안 함."""
    rs = np.random.RandomState(1)
    far = np.abs(np.fft.rfft(rs.randn(4096))) + 1.0
    hw = far * 2.0                                          # 진짜 스케일=2
    far[-500:] *= 1e-4                                      # HF만 무너뜨림
    s = w._wiener_match_scale(far, hw)
    assert 1.5 < s < 2.5, s                                 # 무너진 HF 무시 → ~2 유지


# ── _ir_from_mag_phase : 크기+위상 → IR(역FFT) ────────────────────────────
def test_ir_from_mag_phase_preserves_delay():
    """3ms 지연 임펄스 → 복원 IR 주피크도 3ms(위상이 지연 인코딩)."""
    fs, N = 48000, 16384
    ir0 = np.zeros(N); ir0[int(0.003 * fs)] = 1.0
    H = np.fft.rfft(ir0); fu = np.fft.rfftfreq(N, 1 / fs)
    flog = np.logspace(np.log10(20), np.log10(20000), 1200)
    Hl = np.interp(flog, fu, H.real) + 1j * np.interp(flog, fu, H.imag)
    t_ms, h = w._ir_from_mag_phase(flog, 20 * np.log10(np.abs(Hl) + 1e-12),
                                   np.degrees(np.angle(Hl)))
    assert abs(t_ms[int(np.argmax(np.abs(h)))] - 3.0) < 0.05


# ── _hilbert_env : 해석신호 포락선 ────────────────────────────────────────
def test_hilbert_env_unit_sine():
    env = w._hilbert_env(np.sin(2 * np.pi * 1000 * np.arange(2048) / SR).astype(np.float32))
    assert abs(float(env.mean()) - 0.9983) < 0.01          # 단위 사인 포락선≈1


# ── farina_analyze : ESS 스윕 → 전달함수/IR ──────────────────────────────
def test_farina_unit_passthrough():
    """스윕을 그대로(단위 IR) 통과 → H 중역 ≈ 0 dB, IR 주피크 0ms 근처."""
    T, f1, f2 = 1.0, 20.0, 20000.0
    xs = w._gen_ess(T, f1, f2, SR)
    d = w.farina_analyze(xs, xs, SR, T, f1, f2)
    Hm = 20 * np.log10(np.abs(d["H"]) + 1e-12)
    mid = (d["freqs"] >= 200) & (d["freqs"] <= 2000)
    assert abs(float(Hm[mid].mean())) < 0.1                 # 골든: 완벽 통과
    ir = np.asarray(d["ir"]); t_ms = np.asarray(d["t_ms"])
    assert abs(t_ms[int(np.argmax(np.abs(ir)))]) < 0.2      # 임펄스 0ms 근처


# ── 좌표 매핑(주파수축 줌 f_lo 포함) ─────────────────────────────────────
def test_freq_to_x_roundtrip_and_golden():
    assert abs(w.freq_to_x(1000, 40, 860) - 514.51387) < 1e-3
    # 왕복
    for f in (20, 100, 1000, 10000, 20000):
        x = w.freq_to_x(f, 40, 860)
        assert abs(w.x_to_freq(x, 40, 860) - f) < 1e-6
    # 줌(f_lo=100): 100→왼쪽끝, 20000 축소범위
    assert abs(w.freq_to_x(100, 40, 860, 20000, 100) - 40.0) < 1e-6
    assert abs(w.freq_to_x(200, 40, 860, 20000, 100) - 152.50866) < 1e-3


def test_db_to_y_roundtrip():
    for db in (-60, -30, 0):
        y = w.db_to_y(db, 100, -60, 0)
        assert abs(w.y_to_db(y, 100, -60, 0) - db) < 0.6    # 정수 y 반올림 오차 내


# ── 단위 환산 / 딜레이 포맷 ──────────────────────────────────────────────
def test_distance_conversion():
    assert abs(w.ms_to_m(10) - 3.43) < 1e-9                 # 음속 343 m/s
    assert abs(w.m_to_ms(3.43) - 10.0) < 1e-9
    assert abs(w.m_to_ms(w.ms_to_m(7.25)) - 7.25) < 1e-9


def test_fmt_delay():
    assert w.fmt_delay(3.5) == "3.50 ms"


# ── _fz_clamp : 주파수축 줌 한계·최소스팬 ────────────────────────────────
def test_fz_clamp_bounds_and_minspan():
    lo, hi = w._fz_clamp(5, 50000)                          # 범위 밖 → [20,20000]
    assert lo == 20.0 and hi == 20000.0
    lo, hi = w._fz_clamp(1000, 1001)                        # 과도확대 → 최소스팬
    assert math.log10(hi / lo) >= w._FZ_MIN_DECADES - 1e-9
    assert abs(math.sqrt(lo * hi) - 1000.0) < 1.0           # 중심 유지


# ── _gen_ess : Farina 지수 사인 스윕 생성 ────────────────────────────────
def test_gen_ess_properties():
    T, f1, f2 = 1.0, 20.0, 20000.0
    x = w._gen_ess(T, f1, f2, SR)
    assert len(x) == round(T * SR)                         # 길이 = T·sr
    assert abs(np.max(np.abs(x)) - 1.0) < 1e-6             # 진폭 1
    X = np.abs(np.fft.rfft(x)); fr = np.fft.rfftfreq(len(x), 1 / SR)
    inband = X[(fr >= 30) & (fr <= 18000)].sum()
    outband = X[fr > 20500].sum()
    assert inband > 50 * outband                           # 에너지 [f1,f2]에 집중


# ── _tf_smooth : 분수옥타브 복소 스무딩(Smaart 방식) ──────────────────────
def test_tf_smooth_flat_preserved():
    """평탄 단위 전달함수(H=1) → 스무딩 후에도 0 dB / 0° (레벨·위상 보존)."""
    N = 4096
    freqs = np.fft.rfftfreq(N, 1 / SR)
    H = np.ones(len(freqs), dtype=complex)
    fo, mag, phw, phu, grp = w._tf_smooth(freqs, H, 3)
    assert len(fo) == 1200                                 # 로그 등간격 출력 그리드
    mid = (fo >= 200) & (fo <= 2000)
    assert abs(float(mag[mid].mean())) < 1e-3
    assert float(np.abs(phw[mid]).mean()) < 1e-3


# ── _octave_bands : 모드별 밴드 수 ───────────────────────────────────────
def test_octave_bands_mode_counts():
    freqs = np.fft.rfftfreq(SR, 1 / SR)
    z = np.zeros(len(freqs))
    assert len(w._octave_bands(freqs, z, "oct3")) == 31
    assert len(w._octave_bands(freqs, z, "oct12")) == 121
    assert len(w._octave_bands(freqs, z, "oct24")) == 243


# ── _fmt_freq_tick : 주파수 눈금 라벨(줌) ────────────────────────────────
def test_fmt_freq_tick():
    cases = [(1250, "1.25k"), (3150, "3.15k"), (100, "100"), (1000, "1k"),
             (20000, "20k"), (6300, "6.3k"), (12500, "12.5k"), (315, "315")]
    for f, exp in cases:
        assert w._fmt_freq_tick(f) == exp, (f, w._fmt_freq_tick(f))


def test_y_to_db_midpoint():
    assert abs(w.y_to_db(50, 100, -60, 0) - (-30.0)) < 1e-9


if __name__ == "__main__":
    # pytest 없이도 실행 가능 (standalone)
    import types
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and isinstance(v, types.FunctionType)]
    p = f = 0
    for fn in fns:
        try:
            fn(); p += 1; print(f"  PASS  {fn.__name__}")
        except Exception as e:
            f += 1; print(f"  FAIL  {fn.__name__}  {e!r}")
    print(f"\n=== {p}/{p + f} PASS ===")
    sys.exit(1 if f else 0)
