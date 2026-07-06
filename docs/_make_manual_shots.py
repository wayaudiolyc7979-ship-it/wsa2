#!/usr/bin/env python3
"""매뉴얼 v1.8 스크린샷 생성 — 개별 창/다이얼로그/페이지 위젯을 offscreen 렌더.

전체 MainWindow는 offscreen에서 segfault → 독립 위젯만 인스턴스화해 실제 UI를 그린다.
selfcheck.py 의 급전 패턴을 재활용. 사용자 실파일 보호 위해 격리 env 강제.

    QT_QPA_PLATFORM=offscreen 자동. 결과 PNG → /tmp/wsa2_manual_shots/<name>.png
    인자로 특정 타깃만: python3 docs/_make_manual_shots.py spl
"""
import os, sys, traceback, tempfile

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
_OUT = '/tmp/wsa2_manual_shots'
os.makedirs(_OUT, exist_ok=True)
os.environ.setdefault('WSA2_SETTINGS_PATH', os.path.join(_OUT, 'settings.json'))
os.environ.setdefault('WSA2_CAPTURES_PATH', os.path.join(_OUT, 'captures.json'))

import numpy as np
import importlib.util
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
_spec = importlib.util.spec_from_file_location('wayaudo2', os.path.join(_ROOT, 'wayaudo2.py'))
w = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(w)

from PyQt5.QtWidgets import QApplication, QWidget
_app = QApplication.instance() or QApplication(sys.argv)

_filter = sys.argv[1].lower() if len(sys.argv) > 1 else None


def shot(name, fn):
    if _filter and _filter not in name.lower():
        return
    try:
        widget = fn()
        _app.processEvents()
        pm = widget.grab()
        assert not pm.isNull(), 'null pixmap'
        path = os.path.join(_OUT, name + '.png')
        pm.save(path)
        print(f'  OK    {name:16s} {pm.width()}x{pm.height()} -> {path}')
    except Exception as e:
        print(f'  FAIL  {name:16s} {e!r}')
        traceback.print_exc()


# ── stereo.png ─ Stereo Loudness 탭 전체 ───────────────────────────────
def _stereo():
    pg = w.StereoLoudnessPage(); pg.resize(1280, 720)
    pg._meter = w.LoudnessMeter(48000); pg._meter.start_integration(); pg._running = True
    rng = np.random.default_rng(0)
    for _ in range(60):
        L = (rng.standard_normal(4800) * 0.09).astype(np.float32)
        R = (L * 0.92 + rng.standard_normal(4800) * 0.02).astype(np.float32)
        pg._on_chunk(L, R)
    pg.set_target(-23.0); pg._refresh_display(force=True)
    return pg
shot('stereo', _stereo)


# ── spl.png ─ SPL Meter 창 ─────────────────────────────────────────────
def _spl():
    m = w.SplMeterWindow(None); m.resize(940, 380)
    m.set_calib_offset(100.0)                 # warn=80 / peak=90 → 존틴트 임계
    # 카드별 다른 존이 보이도록: A=76(초록) C=88(노랑) Z=93(빨강)
    for _ in range(120):
        m.push_levels(93.0, 76.0, 88.0, -6.0)  # dbz, dba, dbc, fs_peak(dBFS)
    m._update_display()                        # 타이머 대신 수동 갱신(offscreen)
    m._update_display()
    return m
shot('spl', _spl)


# ── spl_settings.png ─ SPL 설정 다이얼로그 ─────────────────────────────
def _spl_settings():
    m = w.SplMeterWindow(None)
    leq_labels = [p[0] for p in w.SplMeterWindow._PRESETS]
    dlg = w.SplLayoutDialog(m._rows, m._cols, m._cells, w.SplMeterWindow._METRICS,
                            leq_labels, m._leq_idx, None, sources=None, source_id=0)
    dlg.resize(400, dlg.sizeHint().height())
    return dlg
shot('spl_settings', _spl_settings)


# ── spl_alarm.png ─ SPL 알람 창 (초과 상태) ───────────────────────────
def _spl_alarm():
    stub = QWidget()
    stub._settings = {}
    stub._spl_source_calib = lambda i=0: 100.0
    win = w.SplAlarmWindow(stub); win.resize(300, 340)
    # LAeq 100 한계 초과 상태로 만들기 위해 큰 값 급전 + tick
    for _ in range(40):
        win.push_levels(104.0, 103.0, 105.0, -2.0)
        win._tick()
    return win
shot('spl_alarm', _spl_alarm)


# ── calib.png ─ 마이크 캘리브레이션 창 ─────────────────────────────────
def _calib():
    dlg = w.CalibDialog('Scarlett 2i2 USB', 2, {0: 120.0, 1: 0.0}, 0,
                        lambda: -42.3, lambda ch: None, None)
    dlg.resize(460, dlg.sizeHint().height())
    return dlg
shot('calib', _calib)


# ── capture_drawer.png ─ 캡쳐 서랍(목록) 패널 ─────────────────────────
def _capture_drawer():
    d = w._CaptureDrawer(); d.resize(240, 460)
    d.set_active_mode('spec')
    caps = [
        {'label': 'Main L', 'color': '#4E7DF0', 'visible': True,  'group': ''},
        {'label': 'Main R', 'color': '#E0533B', 'visible': True,  'group': ''},
        {'label': 'Left',   'color': '#39C07A', 'visible': True,  'group': 'Zone A'},
        {'label': 'Right',  'color': '#F2B441', 'visible': False, 'group': 'Zone A'},
        {'label': 'Sub',    'color': '#9B5DE5', 'visible': True,  'group': 'Zone A'},
    ]
    # refresh()는 QTimer.singleShot 지연 그리기 → offscreen 이중렌더 유발.
    # 데이터만 직접 세팅하고 _redraw() 한 번만.
    d._spec_caps = caps
    d._tf_caps = []
    d._sel['spec'] = None
    d._redraw()
    d._panel.setVisible(True)
    return d
shot('capture_drawer', _capture_drawer)


# ── tf.png ─ Transfer Function 탭 (embedded, 3그래프 카드) ─────────────
def _tf():
    tf = w.TransferFunctionWindow(embedded=True); tf.resize(1280, 720)
    # 캔버스에 합성 TF 데이터 급전 (mag/phase/ir)
    f = np.logspace(np.log10(20), np.log10(20000), 400).astype(np.float32)
    mag = (2.5*np.sin(np.log10(f)*3.0)*np.exp(-((np.log10(f)-3.0)**2)/4) - 0.5).astype(np.float32)
    coh = np.clip(0.15 + 0.83/(1+(200.0/f)**2.2), 0.02, 0.99).astype(np.float32)
    pu = (-2*np.pi*f*0.001*180/np.pi).astype(np.float32)
    pw = (((pu+180) % 360)-180).astype(np.float32)
    gm = np.full(len(f), 1.0, np.float32)
    for cvname in ('mag_cvs',):
        cv = getattr(tf, cvname, None)
        if cv is not None:
            cv.set_data(f, mag, coh, pw)
    if getattr(tf, 'phase_cvs', None) is not None:
        tf.phase_cvs.set_data(f, pw, pu, gm)
    return tf
shot('tf', _tf)

print('\n남은 것(실앱/빌드 필요): spectrum.png(전체 탭=MainWindow), '
      'popout_split.png(두 창), menubar.png(빌드된 .app 네이티브 메뉴), tf_delta.png')
