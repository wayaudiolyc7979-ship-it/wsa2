#!/usr/bin/env python3
"""SPECTRA 자기검증 하니스 (headless self-verification harness).

목적: Claude(또는 누구든)가 **사용자 화면 캡쳐 없이** 위젯 변경을 스스로 검증.
  - 위젯을 offscreen으로 렌더 → PNG 저장 → 이미지로 눈으로 확인
  - 순수 함수 로직을 assert로 검증

사용:
    python3 selfcheck.py            # 전체 체크 → /tmp/wsa2_selfcheck/*.png + PASS/FAIL 요약
    python3 selfcheck.py octave     # 이름에 'octave' 포함된 체크만

규칙:
  - QT_QPA_PLATFORM=offscreen + 격리된 settings/captures 경로 자동 설정(사용자 실파일 보호).
  - MainWindow 전체 인스턴스화는 offscreen에서 segfault → 개별 위젯/함수만 검증.
  - 새 기능 만들면 여기에 check() 한 줄 추가해 회귀까지 같이 본다.
"""
import os, sys, tempfile, traceback

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
# 예측 가능한 경로(문서/grep 일치). posix는 /tmp, Windows만 tempfile.
_DIR = '/tmp/wsa2_selfcheck' if os.name != 'nt' else os.path.join(tempfile.gettempdir(), 'wsa2_selfcheck')
os.makedirs(_DIR, exist_ok=True)
os.environ.setdefault('WSA2_SETTINGS_PATH', os.path.join(_DIR, 'settings.json'))
os.environ.setdefault('WSA2_CAPTURES_PATH', os.path.join(_DIR, 'captures.json'))

import numpy as np
import importlib.util

_HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location('wayaudo2', os.path.join(_HERE, 'wayaudo2.py'))
w = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(w)          # 모듈 import 자체가 1차 검증(문법/구조)

from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QPixmap, QPainter, QColor
_app = QApplication.instance() or QApplication(sys.argv)

_filter = sys.argv[1].lower() if len(sys.argv) > 1 else None
_results = []


def check(name, fn):
    if _filter and _filter not in name.lower():
        return
    try:
        out = fn()
        _results.append((True, name, out)); print(f'  PASS  {name}   {out or ""}')
    except Exception as e:
        _results.append((False, name, repr(e))); print(f'  FAIL  {name}   {e}')
        traceback.print_exc()


def _save(widget, fname):
    pm = widget.grab()
    assert not pm.isNull(), 'null pixmap'
    path = os.path.join(_DIR, fname); pm.save(path)
    return f'{pm.width()}x{pm.height()}  ->  {path}'


# ─────────────────────────────────────────────────────────────
#  렌더 체크 (PNG 생성 → 이미지로 직접 확인)
# ─────────────────────────────────────────────────────────────
def _octave():
    cv = w.OctaveCanvas(); cv.resize(900, 360); cv.set_mode('oct3')
    n = len(w.BANDS['oct3']); x = np.linspace(0, 1, n)
    vals = (-10 - 26 * (x - 0.42) ** 2 + np.sin(x * 20) * 1.2).astype(float)
    for _ in range(60): cv.update_data('oct3', vals)
    cv._mx = -1
    return _save(cv, 'octave_rta.png')
check('OctaveCanvas RTA 막대(입체 그라디언트)', _octave)


def _fft():
    cv = w.FFTCanvas(); cv.resize(900, 360)
    fr = np.logspace(np.log10(20), np.log10(20000), 256)
    av = (-12 - 22 * (np.log10(fr / 700)) ** 2 + np.sin(np.log10(fr) * 8) * 1.5).astype(float)
    cv.set_channel_data(0, '#33FF66', fr, av); cv.set_channel_visible(0, True)
    cv._mx = -1
    return _save(cv, 'fft.png')
check('FFTCanvas (FFT 곡선)', _fft)


def _tf_ir():
    cv = w.TFIRCanvas(); cv.resize(900, 280)
    return _save(cv, 'tf_ir.png')          # 빈 상태(엠프티) 렌더 — 축/그리드 확인
check('TFIRCanvas (IR 캔버스)', _tf_ir)


def _showmode():
    class _Dummy: pass
    sm = w.ShowModeWindow(_Dummy()); sm.resize(1280, 720); sm.set_limit(100, 3)
    n = 120; x = np.linspace(0, 1, n)
    bands = (-6 - 28 * (x - 0.3) ** 2 + np.sin(x * 30) * 2).astype(float); bands[18:22] = 0.0
    for _ in range(40): sm.push(94.2, 'dBA', bands, -60, 0)
    return _save(sm, 'showmode.png')
check('ShowModeWindow (FOH 쇼 모드)', _showmode)


def _splash():
    return _save_pixmap(w._make_splash_pixmap(), 'splash.png')


def _save_pixmap(pm, fname):
    assert not pm.isNull(), 'null pixmap'
    path = os.path.join(_DIR, fname); pm.save(path)
    return f'{pm.width()}x{pm.height()}  ->  {path}'
check('브랜드 스플래시', _splash)


def _info_box():
    pm = QPixmap(420, 160); pm.fill(QColor('#101010'))
    p = QPainter(pm); w.draw_info_box(p, 420, '1.00 kHz', '-12.3 dB'); p.end()
    return _save_pixmap(pm, 'cursor_infobox.png')
check('커서 리드아웃 카드(draw_info_box)', _info_box)


# ─────────────────────────────────────────────────────────────
#  로직 체크 (assert)
# ─────────────────────────────────────────────────────────────
def _fmt_delay():
    g = w.fmt_delay.__globals__
    g['_DELAY_UNIT'] = 'ms'
    assert w.fmt_delay(5.0) == '5.00 ms', w.fmt_delay(5.0)
    assert w.fmt_delay(5.234, 1) == '5.2 ms'
    assert w.fmt_delay(1.5, sign=True) == '+1.50 ms'
    g['_DELAY_UNIT'] = 'm'
    assert w.fmt_delay(5.0) == '1.72 m', w.fmt_delay(5.0)
    g['_DELAY_UNIT'] = 'both'
    assert '·' in w.fmt_delay(5.0)
    g['_DELAY_UNIT'] = 'ms'                 # 원복
    return 'ms / m / both / sign OK'
check('fmt_delay 단위 변환', _fmt_delay)


def _ms_m():
    assert abs(w.ms_to_m(5.0) - 1.715) < 1e-9
    assert abs(w.m_to_ms(1.715) - 5.0) < 1e-9
    return '5ms=1.715m 왕복 OK'
check('ms↔m 환산', _ms_m)


def _showmode_smooth():
    class _Dummy: pass
    sm = w.ShowModeWindow(_Dummy())
    np.random.seed(0); bands = np.full(40, -20.0); vals = []
    for _ in range(120):
        sm.push(80 + np.random.randn() * 3, 'dBA', bands, -60, 0); vals.append(sm._spl)
    import statistics
    sd = statistics.pstdev(vals[20:])
    assert sd < 1.5, f'헤드라인 평활 부족 sd={sd}'   # 입력 sd~3 → 평활되어야
    return f'지터 sd 3→{sd:.2f} (평활 OK)'
check('ShowMode 헤드라인 Slow 평활', _showmode_smooth)


# ─────────────────────────────────────────────────────────────
#  v1.7 엔진 — MTW + Farina ESS (DSP 코어 렌더 + 정확성)
# ─────────────────────────────────────────────────────────────
def _mtw_render():
    sr = 48000; rng = np.random.default_rng(5)
    eng = w.MTWEngine(sr, 8192, 8); m = eng.master_len
    ax = np.fft.rfftfreq(m, 1.0 / sr)
    H = (1.0 / np.sqrt(1 + (ax / 2000.0) ** 2)) * (1.0 - 0.9 * np.exp(-((ax - 60.0) ** 2) / (2 * 3.0 ** 2)))
    for _ in range(40):
        ref = rng.standard_normal(m); meas = np.fft.irfft(np.fft.rfft(ref) * H, n=m)
        eng.push(ref.astype(np.float32), meas.astype(np.float32))
    f, Hc, coh = eng.result()
    mag = 20 * np.log10(np.abs(Hc) + 1e-30)
    dip = mag[np.argmin(np.abs(f - 60))]
    assert dip < -10, f'MTW 60Hz 노치 분해 실패 dip={dip:.1f}'   # 단일FFT는 -7.5, MTW는 -19.7
    cv = w.TFMagCanvas(); cv.resize(900, 360)
    cv.set_data(f.astype(np.float32), mag.astype(np.float32), coh.astype(np.float32),
                (np.angle(Hc) * 180 / np.pi).astype(np.float32))
    return _save(cv, 'mtw_mag.png') + f'  (60Hz dip {dip:.1f}dB)'
check('MTWEngine 멀티레이트 TF (60Hz 노치 분해)', _mtw_render)


def _farina_render():
    from scipy.signal import firwin
    sr = 48000; T = 4.0; f1, f2 = 20.0, 20000.0
    x = w._gen_log_sweep(int(T * sr), sr, f1, f2)
    h = firwin(257, 3000.0, fs=sr)
    ylin = w._fft_convolve(x, h)[:len(x)]
    meas = ylin + 0.12 * ylin ** 2 + 0.05 * ylin ** 3   # 12%/5% 고조파 주입
    res = w.farina_analyze(meas.astype(np.float64), x.astype(np.float64), sr, T, f1, f2)
    f_out, mag, pw, pu, grp = w._tf_smooth(res['freqs'].astype(np.float32),
                                           res['H'].astype(np.complex64), 3)
    # 선형 통과대역 평탄(왜곡 무오염) + THD 검출
    pb = mag[np.argmin(np.abs(f_out - 1000))]
    assert abs(pb) < 1.5, f'Farina 통과대역 비평탄 {pb:.1f}dB'
    assert res['thd'] > 3.0, f'Farina THD 미검출 {res["thd"]:.2f}%'
    cv = w.TFMagCanvas(); cv.resize(900, 360)
    cv.set_data(f_out, mag, np.ones(len(f_out), np.float32), pw)
    return _save(cv, 'sweep_farina_mag.png') + f'  (THD {res["thd"]:.1f}%)'
check('Farina ESS 스윕 (LP복원+THD)', _farina_render)


def _mtw_live_method():
    """MTW 라이브 렌더가 Single과 동일한 공통 테일(_render_primary_H)을 타는지 + IR 임펄스가
    주입한 딜레이 위치에 오는지(=딜레이 파인더/센터링 정상 동작의 전제) 검증."""
    from PyQt5.QtWidgets import QLabel
    sr = 48000
    class Stub: pass
    s = Stub(); s.sample_rate = sr; s.delay_ms = 0.0; s.smooth_bpo = 3
    s._mtw = w.MTWEngine(sr, 4096, 5)
    s.fft_size = s._mtw.master_len           # _render_primary_H 의 irfft n
    s.avg_lbl = QLabel(); s.mag_cvs = w.TFMagCanvas(); s.mag_cvs.resize(900, 360)
    s.phase_cvs = w.TFPhaseCanvas(); s.phase_cvs.resize(900, 360)
    s.ir_cvs = w.TFIRCanvas(); s.ir_cvs.resize(900, 280)
    s._render_primary_H = w.TransferFunctionWindow._render_primary_H.__get__(s)
    # 모션 스무딩 경로: 목표곡선 저장 + 30fps 보간 페인트 (테스트는 즉시 flush)
    s._pm_prev = None; s._pm_targ = None; s._pm_t0 = 0.0; s._pm_done = True
    s._pm_lerp = w.TransferFunctionWindow._pm_lerp
    s._pm_lerp_ang = w.TransferFunctionWindow._pm_lerp_ang
    s._pm_push_target = w.TransferFunctionWindow._pm_push_target.__get__(s)
    s._pm_smooth_paint = w.TransferFunctionWindow._pm_smooth_paint.__get__(s)
    m = s._mtw.master_len; rng = np.random.default_rng(7)
    freqs = np.fft.rfftfreq(m, 1.0 / sr).astype(np.float32)
    t_ms = (np.arange(m, dtype=np.float32) - m // 2) / sr * 1000.0
    D = 240                                  # meas 가 ref 보다 240샘플(=5.0ms) 늦음
    exp_ms = D / sr * 1000.0
    for _ in range(30):
        ref = rng.standard_normal(m); meas = np.roll(ref, D)
        w.TransferFunctionWindow._render_mtw(s, ref.astype(np.float32), meas.astype(np.float32),
                                             0.5, 0.5, freqs, t_ms, True)
    s._pm_t0 -= 1.0; s._pm_smooth_paint()    # fr≥1 강제 → 목표곡선을 캔버스로 flush
    assert s.avg_lbl.text() == 'Adaptive', f"avg_lbl={s.avg_lbl.text()!r}"
    # 핵심: IR 임펄스(포락선 피크)가 물리 도착=딜레이 위치(+5ms)에 있어야 함 (Single과 동일)
    assert abs(s.ir_cvs.peak_ms - exp_ms) < 0.3, \
        f"IR 임펄스 위치 {s.ir_cvs.peak_ms:.2f}ms ≠ 주입 딜레이 {exp_ms:.2f}ms"
    return _save(s.mag_cvs, 'mtw_live_mag.png') + f'  (IR 임펄스 {s.ir_cvs.peak_ms:.2f}ms = 주입 {exp_ms:.1f}ms)'
check('MTW 라이브 렌더 = Single 공통테일 + IR 딜레이정렬', _mtw_live_method)


def _loudness_page():
    """StereoLoudnessPage 전체 렌더 — 브랜드 그라디언트 캔버스 + 브랜드색 메트릭 + PLR/PSR."""
    pg = w.StereoLoudnessPage(); pg.resize(1280, 760)
    pg._meter = w.LoudnessMeter(48000); pg._meter.start_integration(); pg._running = True
    rng = np.random.default_rng(0)
    for _ in range(40):
        L = (rng.standard_normal(4800) * 0.08).astype(np.float32); R = L.copy()
        pg._on_chunk(L, R)
    pg.set_target(-23.0); pg._refresh_display(force=True)
    assert hasattr(pg, '_lbl_PLR') and hasattr(pg, '_lbl_PSR'), 'PLR/PSR 메트릭 누락'
    assert pg._lbl_PLR.text() not in ('—', ''), f'PLR 미표시 {pg._lbl_PLR.text()!r}'
    return _save(pg, 'loudness_page.png')
check('StereoLoudnessPage (브랜드+PLR/PSR)', _loudness_page)


def _loud_state_roundtrip():
    """StereoLoudnessPage loud_get_state/loud_apply_state 라운드트립."""
    pg = w.StereoLoudnessPage(); pg.resize(1280, 760)
    pg._set_hero_mode(True)            # LIVE
    pg._lu_btn.setChecked(True)        # LU 모드
    st = pg.loud_get_state()
    assert st == {'lu_mode': True, 'hero_live': True}, st
    # 기본값으로 리셋 후 복원
    pg._set_hero_mode(False); pg._lu_btn.setChecked(False)
    pg.loud_apply_state(st)
    assert pg._hero_live is True and pg._lu_mode is True, (pg._hero_live, pg._lu_mode)
    return 'loud state roundtrip OK'
check('Loudness 상태 직렬화 라운드트립', _loud_state_roundtrip)


# ─────────────────────────────────────────────────────────────
ok = sum(1 for r in _results if r[0])
print(f'\n=== {ok}/{len(_results)} PASS' + ('' if ok == len(_results) else '  ⚠️ 실패 있음') +
      f'   이미지: {_DIR} ===')
sys.exit(0 if ok == len(_results) else 1)
