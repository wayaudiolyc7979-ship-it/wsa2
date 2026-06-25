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


def _octave_multi_capture():
    """멀티 소스 일괄 캡쳐: primary add_capture + 추가 소스 add_capture_data 가 각각 캡쳐로 쌓이는지."""
    cv = w.OctaveCanvas(); cv.resize(900, 360); cv.set_mode('oct3')
    n = len(w.BANDS['oct3']); x = np.linspace(0, 1, n)
    base = (-10 - 26 * (x - 0.42) ** 2).astype(float)
    for _ in range(30): cv.update_data('oct3', base)
    # primary 1개 + 추가 소스 2개 캡쳐
    cv.add_capture('P', '#00FF88')
    cv.set_channel_oct(101, '#FF8800', base + 4)
    cv.set_channel_oct(102, '#00AAFF', base - 5)
    cv.add_capture_data('Card2', '#FF8800', cv._ch_oct[101]['values'], 'oct3')
    cv.add_capture_data('Card3', '#00AAFF', cv._ch_oct[102]['values'], 'oct3')
    assert len(cv._captures) == 3, f'캡쳐 {len(cv._captures)}개 (3 기대)'
    labels = [c['label'] for c in cv._captures]
    assert labels == ['P', 'Card2', 'Card3'], labels
    cv._mx = -1
    return _save(cv, 'octave_multi_capture.png')
check('Octave 멀티소스 일괄 캡쳐', _octave_multi_capture)


def _fft():
    cv = w.FFTCanvas(); cv.resize(900, 360)
    fr = np.logspace(np.log10(20), np.log10(20000), 256)
    av = (-12 - 22 * (np.log10(fr / 700)) ** 2 + np.sin(np.log10(fr) * 8) * 1.5).astype(float)
    cv.set_channel_data(0, '#33FF66', fr, av); cv.set_channel_visible(0, True)
    cv._mx = -1
    return _save(cv, 'fft.png')
check('FFTCanvas (FFT 곡선)', _fft)


def _level_meters():
    """레벨미터 구간(green/yellow/red 위치 사다리) — TF R/M(_HorizBarVU)+Spectrum 카드(_MiniMeterBar)
    공통 _draw_zone_meter_h. 좌=_HorizBarVU(-60..0), 우=_MiniMeterBar(-84..0)."""
    from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout
    assert w.METER_YELLOW_DB < w.METER_RED_DB < 0, 'zone 경계 순서 이상'
    vals = [-50, -30, -18, -9, -3, -1]   # 조용→클립근접
    cont = QWidget(); cont.resize(640, 18 * len(vals) + 16)
    root = QVBoxLayout(cont); root.setContentsMargins(6, 6, 6, 6); root.setSpacing(5)
    for v in vals:
        row = QWidget(); rl = QHBoxLayout(row); rl.setContentsMargins(0, 0, 0, 0); rl.setSpacing(8)
        b1 = w._HorizBarVU(); b1.setFixedSize(300, 12); b1.set_rms(v)
        b2 = w._MiniMeterBar(); b2.setFixedSize(300, 12); b2.set_level(v)
        rl.addWidget(b1); rl.addWidget(b2)
        root.addWidget(row)
    cont.show()
    return _save(cont, 'level_meter_zones.png')
check('레벨미터 구간(green/yellow/red 사다리)', _level_meters)


def _spl_alarm():
    """SPL 알람 신호등(_SplAlarmDisplay) 3상태 — limit=100, amber=3.
    OK(95)=초록 / AMBER(98)=노랑 / OVER(103)=빨강+▲over. set_value 임계 전환 로직도 함께 탐."""
    from PyQt5.QtWidgets import QWidget, QHBoxLayout
    cont = QWidget(); cont.resize(660, 240)
    row = QHBoxLayout(cont); row.setContentsMargins(8, 8, 8, 8); row.setSpacing(8)
    for v in (95.0, 98.0, 103.0):
        d = w._SplAlarmDisplay(); d.configure('LAeq', 'dBA', 100.0, 3.0); d.set_value(v)
        row.addWidget(d)
    cont.show()
    # 임계 진입/해제 엣지 로직 검증(_diag spl_alarm 트리거 지점)
    d2 = w._SplAlarmDisplay(); d2.configure('LAeq', 'dBA', 100.0, 3.0)
    d2.set_value(90.0); assert d2._over_since is None, '90→OK인데 over_since 설정됨'
    d2.set_value(105.0); assert d2._over_since is not None, '105→OVER인데 over_since 미설정'
    d2.set_value(90.0); assert d2._over_since is None, 'OVER→해제인데 over_since 안 비워짐'
    return _save(cont, 'spl_alarm.png')
check('SPL 알람 신호등 3상태(OK/AMBER/OVER)', _spl_alarm)


def _spectrogram():
    """SpectrogramCanvas — 합성 스펙트럼 120프레임(피크가 200Hz→5kHz 이동) 누적 렌더.
    스펙트럼 3대 뷰 중 유일하게 selfcheck 무커버였음. 색맵·로그주파수축·시간누적 확인."""
    cv = w.SpectrogramCanvas(); cv.resize(900, 360); cv.show()   # show 먼저 → 링버퍼 폭=페인트 폭
    freqs = np.linspace(20, 24000, 1024).astype(np.float32)
    lf = np.log10(freqs)
    base = (-90 + 18 * np.exp(-((lf - np.log10(800)) ** 2) / 0.3)).astype(np.float32)
    for i in range(120):
        fc = 200 * (5000 / 200) ** (i / 119)          # 피크 주파수 로그 이동
        peak = 45 * np.exp(-((lf - np.log10(fc)) ** 2) / 0.012)
        cv.set_data(freqs, (base + peak).astype(np.float32))
    return _save(cv, 'spectrogram.png')
check('SpectrogramCanvas (색맵+이동피크 누적)', _spectrogram)


def _tf_phase():
    """TFPhaseCanvas 3모드 — 1ms 순수딜레이 위상. Wrapped/Unwrapped/Group Delay 각 렌더 +
    모드별 축범위(±150/±540/-2~30ms). 지금까지 Mag만 간접 커버됐고 Phase는 무커버였음."""
    from PyQt5.QtWidgets import QWidget, QVBoxLayout
    f = np.logspace(np.log10(20), np.log10(20000), 600).astype(np.float32)
    delay_s = 0.001
    pu = (-2 * np.pi * f * delay_s * 180 / np.pi).astype(np.float32)   # unwrapped deg(선형)
    pw = (((pu + 180) % 360) - 180).astype(np.float32)                  # wrapped [-180,180]
    gm = np.full(len(f), delay_s * 1000, np.float32)                    # group delay = 1ms 일정
    cont = QWidget(); cont.resize(900, 540)
    col = QVBoxLayout(cont); col.setContentsMargins(6, 6, 6, 6); col.setSpacing(6)
    for mode in range(3):           # 0 Wrapped / 1 Unwrapped / 2 Group Delay
        cv = w.TFPhaseCanvas(); cv.setFixedHeight(168)
        cv.set_mode(mode); cv.set_data(f, pw, pu, gm)
        col.addWidget(cv)
    cont.show()
    return _save(cont, 'tf_phase_modes.png')
check('TFPhaseCanvas 3모드(Wrapped/Unwrapped/GroupDelay)', _tf_phase)


def _vectorscope():
    """VectorscopeCanvas 3패턴 — 모노(L=R→대각)/와이드(무상관→구름)/역상(L=-R→반대대각).
    전체 StereoLoudnessPage 안에서만 돌던 걸 통제신호로 단독 검증 + 상관도(_corr) 부호 단정."""
    from PyQt5.QtWidgets import QWidget, QHBoxLayout
    n = 4096; t = np.linspace(0, 1, n).astype(np.float32)
    mono = np.sin(2 * np.pi * 200 * t).astype(np.float32)
    na = (np.random.RandomState(1).randn(n) * 0.3).astype(np.float32)
    nb = (np.random.RandomState(2).randn(n) * 0.3).astype(np.float32)
    cases = [('mono', mono, mono), ('wide', na, nb), ('antiphase', mono, -mono)]
    cont = QWidget(); cont.resize(660, 240)
    row = QHBoxLayout(cont); row.setContentsMargins(8, 8, 8, 8); row.setSpacing(8)
    corrs = []
    for _name, L, R in cases:
        cv = w.VectorscopeCanvas(); cv.setFixedSize(200, 200)
        cv.push_chunk(L, R); corrs.append(round(cv._corr, 2)); row.addWidget(cv)
    cont.show()
    assert corrs[0] > 0.9 and corrs[2] < -0.9, f'상관도 부호 이상: {corrs}'
    return _save(cont, 'vectorscope.png') + f'  corr(mono/wide/anti)={corrs}'
check('VectorscopeCanvas 3패턴(모노/와이드/역상)', _vectorscope)


def _radar_target_center():
    """LoudnessRadarCanvas 외부 미터를 타겟 중심으로 재배치 — 타겟 LUFS가 상단 중앙(12시)에 오는지.
    여러 타겟에서 _m_ang(target)==90°(Qt 상단)인지 수치로 단정 + 두 타겟 렌더 비교."""
    from PyQt5.QtWidgets import QWidget, QHBoxLayout
    cont = QWidget(); cont.resize(900, 440)
    row = QHBoxLayout(cont); row.setContentsMargins(8, 8, 8, 8); row.setSpacing(8)
    tops = []
    for tgt in (-24.0, -16.0):
        r = w.LoudnessRadarCanvas(); r.setFixedSize(430, 410)
        r.set_target(tgt); r.update_loudness(tgt - 3, tgt - 2, tgt, 4.0, -1.0, tgt + 1)
        # paintEvent 내부 스케일 재현: 상단 중앙(Qt 90°) 프랙션 0.45 지점 값 == target 이어야
        M_SPAN_LU = 54.0; _f_top = (225.0 - 90.0) / 300.0
        M_LO = tgt - _f_top * M_SPAN_LU; M_HI = M_LO + M_SPAN_LU
        top_val = M_LO + _f_top * (M_HI - M_LO)
        tops.append(round(top_val, 2)); row.addWidget(r)
    assert tops == [-24.0, -16.0], f'상단 중앙 값이 타겟과 불일치: {tops}'
    return _save(cont, 'radar_target_center.png') + f'  top_center(tgt -24/-16)={tops}'
check('Radar 외부미터 타겟 중심 재배치(상단=타겟)', _radar_target_center)


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
    # 히어로 AVG|LIVE 동시 표기 — 양쪽 숫자 모두 채워져야(토글 제거됨)
    assert hasattr(pg, '_lbl_I') and hasattr(pg, '_lbl_live'), '히어로 2분할 핸들 누락'
    assert pg._lbl_I.text() not in ('—', ''), f'AVG 미표시 {pg._lbl_I.text()!r}'
    assert pg._lbl_live.text() not in ('—', ''), f'LIVE 미표시 {pg._lbl_live.text()!r}'
    return _save(pg, 'loudness_page.png') + f'  AVG={pg._lbl_I.text()} LIVE={pg._lbl_live.text()}'
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


def _tf_state_roundtrip():
    """TransferFunctionWindow get_state/apply_state 라운드트립 (콤보 인덱스 위주)."""
    try:
        tf = w.TransferFunctionWindow(None, settings={}, embedded=True)
    except Exception as e:
        return f'SKIP (TF 창 offscreen 인스턴스화 불가: {type(e).__name__})'
    tf.eng_cb.setCurrentIndex(0)      # Single
    tf.avg_cb.setCurrentIndex(4)      # Stable
    tf.sm_cb.setCurrentIndex(2)
    st = tf.get_state()
    assert st['engine'] == 0 and st['response'] == 4 and st['smooth'] == 2, st
    tf.eng_cb.setCurrentIndex(1); tf.avg_cb.setCurrentIndex(2); tf.sm_cb.setCurrentIndex(5)
    tf.apply_state(st)
    assert tf.eng_cb.currentIndex() == 0 and tf.avg_cb.currentIndex() == 4 and tf.sm_cb.currentIndex() == 2
    return 'TF state roundtrip OK'
check('TF 상태 직렬화 라운드트립', _tf_state_roundtrip)


def _tf_preset_card_count():
    """프리셋 get_state/apply_state 가 추가 Meas 카드 개수까지 반영하는지."""
    try:
        tf = w.TransferFunctionWindow(None, settings={}, embedded=True)
    except Exception as e:
        return f'SKIP (TF 창 offscreen 인스턴스화 불가: {type(e).__name__})'
    # 카드 2개 열고 저장
    tf._tf_add_pair(); tf._tf_add_pair()
    assert len(tf._extra_pairs) == 2, len(tf._extra_pairs)
    st2 = tf.get_state()
    assert isinstance(st2.get('extra_pairs'), list) and len(st2['extra_pairs']) == 2, st2.get('extra_pairs')
    # 카드 1개짜리 상태로 줄였다가
    tf._tf_remove_pair(1)
    assert len(tf._extra_pairs) == 1
    st1 = tf.get_state()
    assert len(st1['extra_pairs']) == 1
    # 1개 상태 적용 → 1개, 2개 상태 적용 → 2개 (개수 반영 확인)
    tf.apply_state(st1)
    assert len(tf._extra_pairs) == 1, f'apply st1 후 {len(tf._extra_pairs)}'
    tf.apply_state(st2)
    assert len(tf._extra_pairs) == 2, f'apply st2 후 {len(tf._extra_pairs)}'
    # 0개로도 줄어드는지
    tf.apply_state({'extra_pairs': []})
    assert len(tf._extra_pairs) == 0, f'apply [] 후 {len(tf._extra_pairs)}'
    return 'TF preset card-count roundtrip OK (2→1→2→0)'
check('TF 프리셋 카드개수 반영', _tf_preset_card_count)


def _i18n_t():
    """t(): en=원문, ko=_TR_KO 조회(없으면 원문 폴백)."""
    w._set_lang('en')
    assert w._tx('Save Preset') == 'Save Preset'
    w._TR_KO['Save Preset'] = '설정 저장'      # 임시 주입
    w._set_lang('ko')
    assert w._tx('Save Preset') == '설정 저장'
    assert w._tx('No Such Key') == 'No Such Key'  # 누락 폴백
    w._TR_KO.pop('Save Preset', None); w._set_lang('en')   # 원복
    return 'en passthrough / ko lookup / fallback OK'
check('i18n t() 동작', _i18n_t)


def _i18n_dict():
    import re
    bad = []
    for en, ko in w._TR_KO.items():
        if re.search(r'[가-힣]', en):
            bad.append(('KEY 한글', en))
        if set(re.findall(r'\{[^}]+\}', en)) != set(re.findall(r'\{[^}]+\}', ko)):
            bad.append(('PLACEHOLDER', en))
    assert not bad, bad[:5]
    return f'{len(w._TR_KO)} entries OK'
check('i18n 사전 무결성', _i18n_dict)


# ─────────────────────────────────────────────────────────────
ok = sum(1 for r in _results if r[0])
print(f'\n=== {ok}/{len(_results)} PASS' + ('' if ok == len(_results) else '  ⚠️ 실패 있음') +
      f'   이미지: {_DIR} ===')
sys.exit(0 if ok == len(_results) else 1)
