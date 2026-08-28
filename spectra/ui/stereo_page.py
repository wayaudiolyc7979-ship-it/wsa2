"""스테레오 라우드니스 탭 — 벡터스코프+라우드니스 레이더/히스토리 페이지 + 팝아웃.

v2.0 분해: wayaudo2.py에서 이동(동작 0 변경).
"""
import sys, ctypes
import numpy as np
import sounddevice as sd
from PyQt5.QtGui import QCursor
from PyQt5.QtCore import Qt, QEvent, QTimer, QObject, QThread, pyqtSignal
from PyQt5.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLabel, QPushButton,
                             QVBoxLayout, QWidget)
from spectra.core.config import T, is_dark
from spectra.core.i18n import _tx
from spectra.core.logging_diag import _alog
from spectra.audio.engine import _win_extra_settings
from spectra.dsp.loudness import LoudnessMeter
from spectra.ui.tokens import FS_BODY, FS_LG, FS_METRIC, FS_SM, FS_XS
from spectra.ui.colors import _metric_col
from spectra.ui.widgets import _ComplianceBadge, _apply_dark_titlebar
from spectra.ui.canvas_stereo import (VectorscopeCanvas, LoudnessRadarCanvas,
                                      LoudnessHistoryCanvas, _GradientNumber)


def _set_float_above_fullscreen(win):
    """macOS: 부모 없는 독립 창을 (1) 메인창이 풀스크린이어도 그 위에 뜨고
    (2) 모든 Space에 표시 + 메인창 최소화에도 살아남게 한다 (Smaart SPL 미터 방식).
    네이티브 NSWindow.collectionBehavior 에 FullScreenAuxiliary | CanJoinAllSpaces 추가.
    winId()가 유효해야 하므로 반드시 show() 이후 호출."""
    if sys.platform != 'darwin':
        return
    try:
        import ctypes
        objc = ctypes.cdll.LoadLibrary('/usr/lib/libobjc.A.dylib')
        objc.sel_registerName.restype = ctypes.c_void_p
        objc.sel_registerName.argtypes = [ctypes.c_char_p]
        def sel(name): return objc.sel_registerName(name.encode())
        def msg(restype, obj, sel_name, *args):
            f = objc.objc_msgSend
            f.restype = restype
            f.argtypes = [ctypes.c_void_p, ctypes.c_void_p] + [type(a) for a in args]
            return f(obj, sel(sel_name), *args)
        ns_view = ctypes.c_void_p(int(win.winId()))
        ns_window = msg(ctypes.c_void_p, ns_view, 'window')
        if not ns_window:
            return
        # NSWindowCollectionBehaviorCanJoinAllSpaces=1<<0, FullScreenAuxiliary=1<<8
        beh = msg(ctypes.c_ulong, ns_window, 'collectionBehavior')
        beh |= (1 << 0) | (1 << 8)
        msg(None, ns_window, 'setCollectionBehavior:', ctypes.c_ulong(beh))
    except Exception as e:
        try: _alog.debug(f'float-above-fullscreen 실패: {e}')
        except Exception: pass


class _CanvasKeyRouter(QObject):
    """포커스와 무관하게 커서 위치 기반으로 Up/Down 키를 올바른 캔버스로 라우팅.
    QApplication.widgetAt() 을 사용해 Retina/HiDPI 스케일링 문제를 피함."""
    def __init__(self, main_win):
        super().__init__(main_win)
        self._mw = main_win

    def _canvas_at_cursor(self):
        """현재 커서 아래에 있는 위젯에서 부모 체인을 타고 올라가 캔버스를 찾는다."""
        mw = self._mw
        w = QApplication.widgetAt(QCursor.pos())
        while w is not None:
            if w is getattr(mw, 'spectro_cvs', None):
                return 'spectro'
            if w is getattr(mw, 'oct_cvs', None):
                return 'oct'
            if w is getattr(mw, 'fft_cvs', None):
                return 'fft'
            tf = getattr(mw, 'tf_win', None)
            if tf is not None:
                if w is getattr(tf, 'ir_cvs', None):   return 'tf_ir'
                if w is getattr(tf, 'phase_cvs', None): return 'tf_phase'
                if w is getattr(tf, 'mag_cvs', None):  return 'tf_mag'
            w = w.parent()
        return None

    def eventFilter(self, obj, event):
        if event.type() != QEvent.KeyPress:
            return False
        key = event.key()
        if key not in (Qt.Key_Up, Qt.Key_Down):
            return False
        mw = self._mw
        canvas = self._canvas_at_cursor()
        if canvas in ('tf_ir', 'tf_phase', 'tf_mag'):
            return False  # TF 캔버스 keyPressEvent가 직접 처리
        if canvas == 'spectro' and getattr(mw, '_spectro_on', False):
            mw.spectro_cvs.scroll_by(-30 if key == Qt.Key_Up else 30)
            return True
        if canvas in ('oct', 'fft') or canvas is None:
            mw._db_shift(6 if key == Qt.Key_Up else -6)
            return True
        return False


# ═══════════════════════════════════════════════════════════════════
#  Stereo / Loudness  — Vectorscope + ITU-R BS.1770-4 Radar
# ═══════════════════════════════════════════════════════════════════


class StereoAudioThread(QThread):
    """두 채널을 동시에 캡처 → chunk_ready(L_chunk, R_chunk) emit."""
    chunk_ready  = pyqtSignal(object, object)
    error_signal = pyqtSignal(str)

    def __init__(self, device_idx, sample_rate, l_ch=0, r_ch=1):
        super().__init__()
        self.device_idx=device_idx; self.sample_rate=sample_rate
        self.l_ch=l_ch; self.r_ch=r_ch; self.running=False
        self._active_stream=None   # stop()에서 abort()로 즉시 장치 해제

    def run(self):
        self.running=True
        nc=max(self.l_ch, self.r_ch)+1
        lc=self.l_ch; rc=self.r_ch
        def cb(indata, frames, ti, status):
            if not self.running: return
            try:
                n=indata.shape[1]
                L=indata[:frames, min(lc,n-1)].astype(np.float32).copy()
                R=indata[:frames, min(rc,n-1)].astype(np.float32).copy()
                self.chunk_ready.emit(L, R)
            except Exception: pass
        last_err=None
        for _rnd in range(2):
            for bs,lat in ((512,'low'),(512,'high'),(0,'high')):
                try:
                    with sd.InputStream(device=self.device_idx,
                                        samplerate=self.sample_rate,
                                        channels=nc, blocksize=bs,
                                        callback=cb, latency=lat,
                                        dtype='float32',
                                        extra_settings=_win_extra_settings()) as _s:
                        self._active_stream=_s
                        try:
                            while self.running: self.msleep(100)
                        finally:
                            self._active_stream=None
                    return
                except Exception as e:
                    last_err=e
                    if not self.running: return
            if _rnd==0:
                for _ in range(15):
                    if not self.running: return
                    self.msleep(100)
        if last_err: self.error_signal.emit(str(last_err))

    def stop(self):
        self.running=False
        s=self._active_stream
        if s is not None:
            try: s.abort(ignore_errors=True)
            except Exception:
                try: s.close(ignore_errors=True)
                except Exception: pass
        if not self.wait(3000):
            _alog.warning('StereoAudioThread stop(): wait timeout — stream forced abort')




class StereoLoudnessPage(QWidget):
    """벡터스코프 + 라우드니스 레이더를 담는 탭 페이지."""
    error_signal = pyqtSignal(str)   # MainWindow가 버튼 리셋에 사용

    def __init__(self):
        super().__init__()
        self._sub=None; self._meter=None; self._running=False
        self._l_ch=0; self._r_ch=1
        self._target=-23.0; self._lu_mode=False; self._unit_lbls={}
        self._build_ui()

    def _build_ui(self):
        # 시안C 카드형 레이아웃: 모든 요소를 둥근 카드에 배치 (검정 배경 위 카드 부유)
        root=QVBoxLayout(self); root.setContentsMargins(12,12,12,12); root.setSpacing(12)
        self.setStyleSheet('StereoLoudnessPage{background:%s;}' % (T('bg') if is_dark() else T('bg')))
        self._vseps = []; self._metric_meta = []

        # ── Row 1: 벡터스코프 | 레이더 | PROGRAM 히어로 ──
        self._vs=VectorscopeCanvas(); self._radar=LoudnessRadarCanvas()
        self._vs.popout_requested.connect(self._popout_vs)
        self._radar.popout_requested.connect(self._popout_radar)
        self._vs_win=None; self._radar_win=None
        self._vs_card,  self._vs_card_l  = self._card(self._vs, pad=8)
        self._radar_card, self._radar_card_l = self._card(self._radar, pad=8)
        self._hero_card, _ = self._card(self._build_hero_panel(), pad=12)
        row1=QHBoxLayout(); row1.setSpacing(12)
        # 스코프/레이더를 자주 보므로 비중을 키움(기존 1:1:2 → 5:5:6) + 행 높이 확대
        row1.addWidget(self._vs_card,5); row1.addWidget(self._radar_card,5); row1.addWidget(self._hero_card,6)
        rw1=QWidget(); rw1.setLayout(row1); rw1.setMinimumHeight(280); rw1.setMaximumHeight(560)
        root.addWidget(rw1,3)   # 창 커지면 스코프/레이더도 커지게(최대 560까지 우선 확장)

        # ── Row 2: 메트릭 카드 6개 ──
        specs=[('M  MOMENTARY','LUFS','_lbl_M',203,158,
                _tx('Momentary loudness (~400ms moving average)\nFastest-responding level indicator — reflects right now.')),
               ('S  SHORT-TERM','LUFS','_lbl_S',224,156,
                _tx('Short-term loudness (3s moving average)\nShows average level over a short window.')),
               ('TRUE PEAK','dBTP','_lbl_TP',4,168,
                _tx('True Peak (4× oversampled — detects inter-sample peaks)\nAbove 0 dBFS risks clipping. Broadcast/streaming typically requires ≤ −1 dBTP.')),
               ('LRA','LU','_lbl_LRA',270,160,
                _tx('Loudness Range (EBU 3342) — difference between quiet and loud sections\nHigher = wider dynamic range. Music: 5–15 LU; drama/ads: narrower.')),
               ('PLR  pk/loud','LU','_lbl_PLR',326,162,
                _tx('Peak-to-Loudness Ratio = True Peak − Integrated\nOverall dynamic headroom. Higher = more dynamic; lower = heavily compressed master.')),
               ('PSR  pk/short','LU','_lbl_PSR',320,162,
                _tx('Peak-to-Short-term Ratio = True Peak − Short-term\nTransient dynamics / limiting severity. Low value = over-limiting.'))]
        row2=QHBoxLayout(); row2.setSpacing(10)
        for title,unit,attr,hue,light,tip in specs:
            row2.addWidget(self._metric_card(title,unit,attr,hue,light,tip),1)
        row2.addWidget(self._build_target_ctrl(),0)
        rw2=QWidget(); rw2.setLayout(row2); rw2.setFixedHeight(74)   # 콘텐츠에 맞춰 타이트(빈 하단 띠 제거)
        root.addWidget(rw2,0)

        # ── Row 3: 히스토리 | 컴플라이언스 ──
        self._hist=LoudnessHistoryCanvas()
        hist_card,_=self._card(self._hist, pad=8)
        row3=QHBoxLayout(); row3.setSpacing(12)
        row3.addWidget(hist_card,2); row3.addWidget(self._build_compliance_card(),1)
        rw3=QWidget(); rw3.setLayout(row3); rw3.setMinimumHeight(150)   # history 최소 보장
        root.addWidget(rw3,2)

        self._disp_timer=QTimer(self)
        self._disp_timer.timeout.connect(self._refresh_display)
        self._disp_timer.start(80)

    # ── 카드 헬퍼 ────────────────────────────────────────────────
    def _card_bg_ss(self, obj='stCard', radius=14):
        """카드 배경 스타일 — 다크 고정 hex / 라이트는 T() 토큰. 테마 토글 시 재적용용."""
        dark=(is_dark())
        return '#%s{background:%s;border:1px solid %s;border-radius:%dpx;}' % (
            obj, ('#141416' if dark else T('panel')),
            ('#2A2A2C' if dark else T('border')), radius)

    def _card(self, inner, pad=8):
        f=QFrame(); f.setObjectName('stCard')
        f.setStyleSheet(self._card_bg_ss('stCard', 14))
        getattr(self, '_card_frames', self.__dict__.setdefault('_card_frames', [])).append((f, 'stCard', 14))
        lay=QVBoxLayout(f); lay.setContentsMargins(pad,pad,pad,pad); lay.setSpacing(0); lay.addWidget(inner)
        return f, lay

    def _metric_card(self, title, unit, attr, hue, light, tip=''):
        col=_metric_col(hue,light)
        f=QFrame(); f.setObjectName('stMc')
        f.setStyleSheet(self._card_bg_ss('stMc', 12))
        getattr(self, '_card_frames', self.__dict__.setdefault('_card_frames', [])).append((f, 'stMc', 12))
        if tip: f.setToolTip(tip)
        h=QHBoxLayout(f); h.setContentsMargins(12,8,10,8); h.setSpacing(9)
        bar=QFrame(); bar.setFixedWidth(4)
        bar.setStyleSheet(f'background:{col};border:none;border-radius:2px;')
        colw=QWidget(); colw.setStyleSheet('background:transparent;')
        v=QVBoxLayout(colw); v.setContentsMargins(0,0,0,0); v.setSpacing(1)
        t=QLabel(title); t.setStyleSheet(f'font-size:{FS_SM}px;color:{self._metric_lbl_col()};letter-spacing:0.5px;background:transparent;')
        valrow=QWidget(); valrow.setStyleSheet('background:transparent;')
        vr=QHBoxLayout(valrow); vr.setContentsMargins(0,0,0,0); vr.setSpacing(3)
        val=QLabel('—'); val.setStyleSheet(f'font-size:{FS_METRIC}px;font-weight:bold;color:{col};background:transparent;')
        u=QLabel(unit); u.setStyleSheet(f'font-size:{FS_XS}px;color:{self._metric_lbl_col()};background:transparent;')
        u.setAlignment(Qt.AlignLeft|Qt.AlignBottom)
        vr.addWidget(val); vr.addWidget(u); vr.addStretch()
        v.addWidget(t); v.addWidget(valrow)
        h.addWidget(bar); h.addWidget(colw,1)
        if tip:
            for x in (colw, t, valrow, val, u, bar): x.setToolTip(tip)
        setattr(self, attr, val); self._unit_lbls[attr]=u
        self._metric_meta.append((attr,hue,light,False,t,u))
        return f

    def _build_compliance_card(self):
        f=QFrame(); f.setObjectName('stCard')
        f.setStyleSheet(self._card_bg_ss('stCard', 14))
        getattr(self, '_card_frames', self.__dict__.setdefault('_card_frames', [])).append((f, 'stCard', 14))
        self._comp_card=f
        v=QVBoxLayout(f); v.setContentsMargins(18,13,18,16); v.setSpacing(11)
        title=QLabel('COMPLIANCE'); title.setAlignment(Qt.AlignHCenter); self._compliance_title = title
        title.setStyleSheet(f'font-size:{FS_SM}px;color:{self._metric_lbl_col()};letter-spacing:1px;background:transparent;')
        v.addWidget(title)
        v.addStretch()

        # ── 상태 원형 배지 — 틴트 채움 + 컬러 링 + 글리프(거대 사각 배너 대체) ──
        self._comp_circle=_ComplianceBadge()
        cc=QHBoxLayout(); cc.addStretch(); cc.addWidget(self._comp_circle); cc.addStretch()
        v.addLayout(cc)

        # ── 상태 문구 + 설명 한 줄(정성 — 수치 아님) ──────────────────
        self._lbl_comp=QLabel('—'); self._lbl_comp.setAlignment(Qt.AlignHCenter)
        v.addWidget(self._lbl_comp)
        self._lbl_comp_sub=QLabel('—'); self._lbl_comp_sub.setAlignment(Qt.AlignHCenter)
        self._lbl_comp_sub.setStyleSheet(f'font-size:{FS_SM}px;color:{self._metric_lbl_col()};background:transparent;')
        v.addWidget(self._lbl_comp_sub)
        v.addStretch()
        self._style_comp_banner(T('text_dim'), '—')
        return f

    def _style_comp_banner(self, col, glyph='—'):
        """상태 원형 배지(틴트 채움+컬러 링+글리프) + 상태 문구 색을 상태색(col)으로 통일."""
        self._comp_circle.set_state(col, glyph)
        self._lbl_comp.setStyleSheet(
            f'font-size:{FS_LG+1}px;font-weight:bold;color:{col};'
            f'letter-spacing:1.5px;background:transparent;')

    def _metric_lbl_col(self):
        return '#E2E4E9' if is_dark() else T('text_dim')

    def _build_hero_panel(self):
        """시안C 히어로 — PROGRAM LOUDNESS. AVG(Integrated) | LIVE(Short-term) 양쪽 동시 표기."""
        w = QWidget(); w.setStyleSheet('background:transparent;')
        vl = QVBoxLayout(w); vl.setContentsMargins(16, 10, 16, 16); vl.setSpacing(4)
        self._hero_live = False   # 구버전 상태 호환(더 이상 토글 안 함 — 양쪽 동시 표시)

        self._lbl_hero_title = QLabel('PROGRAM LOUDNESS'); self._lbl_hero_title.setAlignment(Qt.AlignHCenter)
        self._lbl_hero_title.setStyleSheet(f'font-size:{FS_BODY}px;color:{self._metric_lbl_col()};'
                          f'letter-spacing:2px;background:transparent;')
        vl.addWidget(self._lbl_hero_title)
        vl.addStretch()

        # ── AVG(Integrated) | LIVE(Short-term) 2분할 ──────────────────
        row = QWidget(); row.setStyleSheet('background:transparent;')
        rl = QHBoxLayout(row); rl.setContentsMargins(0, 0, 0, 0); rl.setSpacing(0)

        def _half(cap, tip, scale, primary):
            col = QWidget(); col.setStyleSheet('background:transparent;')
            cv = QVBoxLayout(col); cv.setContentsMargins(0, 0, 0, 0); cv.setSpacing(2)
            # 위계: AVG(주)=액센트 캡션, LIVE(부)=흐린 캡션
            cap_col = T('accent') if primary else T('text_dim')
            cap_lbl = QLabel(cap); cap_lbl.setAlignment(Qt.AlignHCenter); cap_lbl.setToolTip(tip)
            cap_lbl.setStyleSheet(f'font-size:{FS_SM}px;color:{cap_col};'
                                  f'letter-spacing:2px;font-weight:bold;background:transparent;')
            num = _GradientNumber(120, scale=scale)
            sub = QLabel('—'); sub.setAlignment(Qt.AlignHCenter)
            sub.setStyleSheet(f'font-size:{FS_LG}px;color:{T("text_dim")};background:transparent;')
            cv.addWidget(cap_lbl); cv.addWidget(num, 3); cv.addWidget(sub)
            return col, cap_lbl, num, sub

        # AVG·LIVE 동일 크기(좌우 대칭) — 구분은 캡션 색으로만(AVG 액센트 / LIVE 흐림)
        avg_col, self._cap_avg, self._lbl_I, self._sub_avg = _half(
            'AVG', _tx('AVG — Integrated (cumulative average). Broadcast/streaming delivery reference'),
            scale=1.0, primary=True)
        live_col, self._cap_live, self._lbl_live, self._sub_live = _half(
            'LIVE', _tx('LIVE — Real-time (Short-term 3s). For monitoring during work'),
            scale=1.0, primary=False)

        div = QFrame(); div.setFrameShape(QFrame.VLine); div.setFixedWidth(1)
        div.setStyleSheet(f'color:{T("border")};background:transparent;')

        rl.addWidget(avg_col, 1); rl.addWidget(div); rl.addWidget(live_col, 1)
        vl.addWidget(row, 3)
        vl.addSpacing(12)
        # 하위호환: restyle/구코드가 참조하는 sub 핸들 → AVG sub로 매핑
        self._lbl_hero_sub = self._sub_avg
        return w

    def _seg_btn_ss(self, left):
        """히어로 모드 세그먼트 버튼 스타일(좌/우 라운드)."""
        rad = 'border-top-left-radius:6px;border-bottom-left-radius:6px;' if left \
              else 'border-top-right-radius:6px;border-bottom-right-radius:6px;'
        return (f"QPushButton{{background:{T('panel')};color:{T('text_dim')};"
                f"border:1px solid {T('border')};{rad}font-size:11px;font-weight:bold;}}"
                f"QPushButton:checked{{background:rgba(78,125,240,40);color:{T('accent')};"
                f"border:1px solid {T('accent')};}}")

    def _set_hero_mode(self, live):
        # 양쪽(AVG|LIVE) 동시 표기로 바뀌어 토글은 무의미 — 상태 호환만 유지.
        self._hero_live = bool(live)
        self._refresh_display(force=True)

    def loud_get_state(self):
        """페이지 내부 표시 상태(LU 모드 / AVG·LIVE). device·target·L/R 은 MainWindow 소관."""
        return {'lu_mode': bool(self._lu_mode), 'hero_live': bool(self._hero_live)}

    def loud_apply_state(self, d):
        try:
            if 'lu_mode' in d: self._lu_btn.setChecked(bool(d['lu_mode']))   # _on_lu_toggled 반영
        except Exception: pass
        try:
            if 'hero_live' in d: self._set_hero_mode(bool(d['hero_live']))
        except Exception: pass

    def _build_target_ctrl(self):
        """우측 컨트롤 — LU(타겟 상대) 표시 토글. 지표 카드들과 같은 카드 배경으로 묶어 '외톨이' 방지."""
        w = QFrame(); w.setObjectName('stMc'); w.setFixedWidth(64)
        w.setStyleSheet(self._card_bg_ss('stMc', 12))
        getattr(self, '_card_frames', self.__dict__.setdefault('_card_frames', [])).append((w, 'stMc', 12))
        vl = QVBoxLayout(w); vl.setContentsMargins(6, 8, 6, 8); vl.setSpacing(4)
        tl = QLabel('UNITS'); self._units_lbl = tl
        tl.setStyleSheet(f'font-size:{FS_SM}px;color:{self._metric_lbl_col()};'
                         f'letter-spacing:0.5px;background:transparent;')
        tl.setAlignment(Qt.AlignHCenter)
        self._lu_btn = QPushButton('LU'); self._lu_btn.setCheckable(True); self._lu_btn.setFixedSize(54, 24)
        self._lu_btn.setToolTip(_tx('LUFS ↔ LU (show relative value vs target)'))
        self._lu_btn.setStyleSheet(self._lu_btn_ss())
        self._lu_btn.setFocusPolicy(Qt.NoFocus)
        self._lu_btn.toggled.connect(self._on_lu_toggled)
        vl.addWidget(tl); vl.addWidget(self._lu_btn, 0, Qt.AlignHCenter)
        return w

    def _lu_btn_ss(self):
        # N2 — 투명+서브틀 테두리 / 활성=회색 채움(파랑 필 폐지, 세그먼트 트랙과 통일)
        _bd = '#34343B' if is_dark() else T('border')
        _fill, _fg = ('#42424A', '#FFFFFF') if is_dark() else ('#3A3A42', '#FFFFFF')
        _bd_h = '#4A4A54' if is_dark() else '#B7B7C0'
        return (f"QPushButton{{background:transparent;color:{T('text_dim')};border:1px solid {_bd};"
                f"border-radius:7px;font-size:11px;font-weight:bold;}}"
                f"QPushButton:hover{{color:{T('text')};border-color:{_bd_h};}}"
                f"QPushButton:checked{{background:{_fill};color:{_fg};border-color:{_fill};}}")

    def set_target(self, val):
        """상단 툴바 콤보가 호출 — 타겟 동기화 + 편차/표시 즉시 갱신."""
        self._target = float(val)
        self._radar.set_target(self._target)        # ★ 즉시 반영 (Start 불필요)
        if hasattr(self, '_hist'): self._hist.set_target(self._target)
        self._refresh_display(force=True)

    def _on_lu_toggled(self, on):
        self._lu_mode = bool(on)
        unit = 'LU' if on else 'LUFS'
        for attr in ('_lbl_M', '_lbl_S', '_lbl_I'):
            u = self._unit_lbls.get(attr)
            if u is not None:
                u.setText(unit)
        self._refresh_display(force=True)

    def restyle_theme(self):
        """테마 토글(다크↔라이트) 시 카드 메트릭 값색 + 스코프 재적용."""
        _lc = self._metric_lbl_col()
        for attr, hue, light, big, t_lbl, u_lbl in getattr(self, '_metric_meta', []):
            v = getattr(self, attr, None)
            if v is not None:
                v.setStyleSheet(f'font-size:{FS_METRIC}px;font-weight:bold;color:{_metric_col(hue, light)};background:transparent;')
            if t_lbl is not None:
                t_lbl.setStyleSheet(f'font-size:{FS_XS}px;color:{_lc};letter-spacing:0.5px;background:transparent;')
            if u_lbl is not None:
                u_lbl.setStyleSheet(f'font-size:{FS_XS}px;color:{_lc};background:transparent;')
        # ── 카드 배경 프레임 재적용 (PROGRAM/메트릭6/COMPLIANCE 등) — 다크 고정 hex/라이트 T()
        for f, obj, rad in getattr(self, '_card_frames', []):
            try: f.setStyleSheet(self._card_bg_ss(obj, rad))
            except Exception: pass
        # 페이지 배경 + 히어로/컴플라이언스 텍스트 + 세그/LU 버튼
        self.setStyleSheet('StereoLoudnessPage{background:%s;}' % T('bg'))
        if hasattr(self, '_lbl_hero_title'):
            self._lbl_hero_title.setStyleSheet(f'font-size:{FS_BODY}px;color:{_lc};'
                              f'letter-spacing:2px;background:transparent;')
        if hasattr(self, '_compliance_title'):
            self._compliance_title.setStyleSheet(f'font-size:{FS_SM}px;color:{_lc};letter-spacing:1px;background:transparent;')
        if hasattr(self, '_units_lbl'):
            self._units_lbl.setStyleSheet(f'font-size:{FS_SM}px;color:{_lc};letter-spacing:0.5px;background:transparent;')
        if hasattr(self, '_lu_btn'):
            self._lu_btn.setStyleSheet(self._lu_btn_ss())
        for _s in (getattr(self, '_sub_avg', None), getattr(self, '_sub_live', None)):
            if _s is not None:
                _s.setStyleSheet(f'font-size:{FS_LG}px;color:{T("text_dim")};background:transparent;')
        # 캡션 위계 유지: AVG(주)=액센트, LIVE(부)=흐림
        for _c, _col in ((getattr(self, '_cap_avg', None), T('accent')),
                         (getattr(self, '_cap_live', None), T('text_dim'))):
            if _c is not None:
                _c.setStyleSheet(f'font-size:{FS_SM}px;color:{_col};'
                                 f'letter-spacing:2px;font-weight:bold;background:transparent;')
        if hasattr(self, '_comp_circle'):
            self._style_comp_banner(T('text_dim'), self._comp_circle.glyph)
        if hasattr(self, '_lbl_comp_sub'):
            self._lbl_comp_sub.setStyleSheet(f'font-size:{FS_SM}px;color:{_lc};background:transparent;')
        self._refresh_display(force=True)
        if hasattr(self, '_hero_avg_btn'): self._hero_avg_btn.setStyleSheet(self._seg_btn_ss(left=True))
        if hasattr(self, '_hero_live_btn'): self._hero_live_btn.setStyleSheet(self._seg_btn_ss(left=False))
        if hasattr(self, '_lu_btn'):
            self._lu_btn.setStyleSheet(self._lu_btn_ss())
        if hasattr(self, '_lbl_I'): self._lbl_I.update()
        if hasattr(self, '_hist'): self._hist.update()
        if hasattr(self, '_vs'): self._vs.update()
        if hasattr(self, '_radar'): self._radar.update()
        for wn in (getattr(self, '_vs_win', None), getattr(self, '_radar_win', None)):
            if wn is not None: wn.setStyleSheet(f'background:{T("bg")};')

    # ── 팝아웃 ────────────────────────────────────────────────────────
    def _make_popout_win(self, canvas, title):
        # 부모 없는 독립 Qt.Window (Tool 제거) + 네이티브 collectionBehavior(_show_popout_normal에서 적용)
        # → 메인창 최소화에도 살아남고, 메인창 풀스크린 위에도 뜬다 (SPL 미터와 동일 방식).
        win = QWidget(None, Qt.Window)
        win.setWindowTitle(title)
        win.setStyleSheet(f'background:{T("bg")};')
        lay = QVBoxLayout(win); lay.setContentsMargins(0,0,0,0)
        lay.addWidget(canvas)
        # 흰색 네이티브 타이틀바 → 다른 팝업처럼 다크 브랜드 타이틀바(프레임리스+✕+리사이즈 그립)
        _apply_dark_titlebar(win, resizable=True)
        # 전체화면/최대화 상태 상속 방지 → 항상 기본 사이즈로
        win.setWindowState(Qt.WindowNoState)
        win.resize(560, 560)
        try:
            scr = QApplication.primaryScreen().availableGeometry()
            win.move(scr.center().x() - 280, scr.center().y() - 280)
        except Exception:
            pass
        return win

    def _show_popout_normal(self, win, sz=600):
        """팝아웃을 항상 기본 사이즈로 — 메인 전체화면 상태 상속/타이밍 무시.
        show 직후 + 지연 콜백으로 setGeometry 강제(전체로 뜨는 것 방지)."""
        win.show()
        _set_float_above_fullscreen(win)   # 풀스크린 위 + 최소화 생존 (show 이후)
        def _fix():
            try:
                win.setWindowState(Qt.WindowNoState)
                scr = QApplication.primaryScreen().availableGeometry()
                win.setGeometry(int(scr.center().x() - sz / 2), int(scr.center().y() - sz / 2), sz, sz)
            except Exception:
                pass
        _fix()
        QTimer.singleShot(0, _fix)
        QTimer.singleShot(80, _fix)
        QTimer.singleShot(250, _fix)

    def _popout_vs(self):
        if self._vs_win and self._vs_win.isVisible(): return
        self._vs_card_l.removeWidget(self._vs)
        self._vs_win = self._make_popout_win(self._vs, 'Vectorscope')
        def _vs_close(e): self._return_vs(); e.accept()
        self._vs_win.closeEvent = _vs_close
        self._show_popout_normal(self._vs_win)

    def _return_vs(self):
        if self._vs_win: self._vs_win.hide()
        self._vs_card_l.addWidget(self._vs)

    def _popout_radar(self):
        if self._radar_win and self._radar_win.isVisible(): return
        self._radar_card_l.removeWidget(self._radar)
        self._radar_win = self._make_popout_win(self._radar, 'Loudness Radar')
        def _radar_close(e): self._return_radar(); e.accept()
        self._radar_win.closeEvent = _radar_close
        self._show_popout_normal(self._radar_win)

    def _return_radar(self):
        if self._radar_win: self._radar_win.hide()
        self._radar_card_l.addWidget(self._radar)

    def start(self,dev_idx,sr,l_ch,r_ch,engine):
        # 공유 오디오 엔진 구독 — 장치당 단일 스트림이라 Spectrum/TF와 같은 장치 동시 사용 가능.
        # Loudness 적분은 연속 샘플이 필요하므로 롤링 버퍼(chunk_ready)가 아닌 raw_ready 사용.
        self.stop()
        self._l_ch=l_ch; self._r_ch=r_ch
        self._meter=LoudnessMeter(sr); self._meter.start_integration()
        try:
            self._sub=engine.subscribe(dev_idx,[l_ch,r_ch],sr)
        except Exception as e:
            self._sub=None
            self._on_error(str(e)); return
        self._sub.raw_ready.connect(self._on_raw,Qt.QueuedConnection)
        self._sub.error.connect(self._on_error,Qt.QueuedConnection)
        self._sub.disconnected.connect(self._on_error,Qt.QueuedConnection)
        self._radar.start(); self._running=True

    def stop(self):
        if self._sub:
            try: self._sub.raw_ready.disconnect()
            except Exception: pass
            try: self._sub.close()
            except Exception: pass
            self._sub=None
        self._radar.stop(); self._running=False

    def reset_integration(self):
        if self._meter: self._meter.start_integration()
        self._radar.reset_integration()
        if hasattr(self, '_hist'): self._hist.reset()

    def reset_peak(self):
        if self._meter: self._meter._PH=-100.0
        self._radar.reset_peak()

    def _on_raw(self,d):
        # 엔진 raw_ready: {ch: 연속 프레임} → L/R 추출 (같은 콜백에서 나와 샘플 동기)
        L=d.get(self._l_ch); R=d.get(self._r_ch)
        if L is None or R is None: return
        self._on_chunk(L,R)

    def _on_chunk(self,L,R):
        if not self._meter: return
        self._meter.push(L,R)
        self._vs.push_chunk(L,R); self._vs.update()
        m=self._meter
        self._radar.update_loudness(m.M,m.S,m.I,m.LRA,m.TP,m.peak_hold)
        if m.S>-100: self._hist.push(m.S)

    def _on_error(self,msg):
        self.stop()
        _alog.warning(f'StereoAudio 오류: {msg}')
        self.error_signal.emit(msg)

    def _refresh_display(self, force=False):
        m=self._meter
        if m is None: return
        if not self._running and not force: return
        if not force and not self.isVisible(): return  # 숨겨진 탭: 디스플레이 갱신 생략(보이는 탭 양보)
        def fmt(v):
            if v<=-100: return '—'
            return f'{v-self._target:+.1f}' if self._lu_mode else f'{v:.1f}'
        self._lbl_M.setText(fmt(m.M))
        self._lbl_S.setText(fmt(m.S))
        self._lbl_LRA.setText(f'{m.LRA:.1f}' if m.LRA>0 else '—')
        self._lbl_TP.setText(f'{m.peak_hold:.1f}' if m.peak_hold>-100 else '—')
        self._lbl_PLR.setText(f'{m.PLR:.1f}' if m.I>-100 else '—')
        self._lbl_PSR.setText(f'{m.PSR:.1f}' if m.S>-100 else '—')
        # True Peak: -1 dBTP 초과면 빨강 경고
        if m.peak_hold>-100:
            tpc=T('red') if m.peak_hold>-1.0 else _metric_col(4,168)
            self._lbl_TP.setStyleSheet(f'font-size:{FS_METRIC}px;font-weight:bold;color:{tpc};background:transparent;')
        # M 라벨 색상: target=-23 기준
        if m.M>-100:
            c=(T('green') if m.M<-20 else
               T('yellow') if m.M<-16 else T('red'))
            self._lbl_M.setStyleSheet(
                f'font-size:{FS_METRIC}px;font-weight:bold;color:{c};background:transparent;')
        # 히어로 — AVG(Integrated) | LIVE(Short-term) 동시 표기
        def _sub(v, tag):
            return '—' if v<=-100 else f'{tag}   ·   {v-self._target:+.1f} LU'
        self._lbl_I.setText(fmt(m.I));    self._sub_avg.setText(_sub(m.I, 'LUFS'))
        self._lbl_live.setText(fmt(m.S)); self._sub_live.setText(_sub(m.S, 'S'))
        # 컴플라이언스 카드 — 송출 기준값 = Integrated(I). 상태만 표시(수치 X)
        hv = m.I
        if hv>-100:
            dev=hv-self._target
            tp_over = (m.peak_hold>-100) and (m.peak_hold>-1.0)
            tp_ok = (not tp_over)
            if abs(dev)<=1.0 and tp_ok:
                status='PASS'; col=T('green'); glyph='✓'; sub=_tx('Meets target & true-peak')
            else:
                col=(T('yellow') if abs(dev)<=3.0 and tp_ok else T('red')); glyph='✕'
                if abs(dev)>1.0:
                    status='CHECK LOUDNESS'
                    sub=_tx('Loud — pull down') if dev>0 else _tx('Quiet — push up')
                else:
                    status='CHECK TRUE-PEAK'; sub=_tx('True peak over −1 dBTP')
            self._lbl_comp.setText(status); self._lbl_comp_sub.setText(sub)
            self._style_comp_banner(col, glyph)
        else:
            self._lbl_comp.setText('STANDBY'); self._style_comp_banner(T('text_dim'), '—')
            self._lbl_comp_sub.setText(_tx('Waiting for signal'))


class _StereoPopoutWindow(QWidget):
    """Stereo Loudness를 별도 창으로 분리(멀티모니터). 닫으면 _dock_st로 되돌림.
    부모 없는 독립 top-level(메인 안 따라감)."""
    def __init__(self, mainwin):
        super().__init__(None, Qt.Window)
        self._mainwin = mainwin
        self._docking = False
        self.setWindowTitle('SPECTRA — Stereo Loudness')
        self.setMinimumSize(900, 520)

    def closeEvent(self, e):
        if not self._docking and self._mainwin is not None:
            self._mainwin._dock_st(via_close=True)
        super().closeEvent(e)


# ───────────────────────────────────────────
#  메인 윈도우
# ───────────────────────────────────────────
