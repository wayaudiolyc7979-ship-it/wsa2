"""TF 캔버스 — Magnitude/Phase/IR + 주파수줌 믹스인 + dB축 헬퍼.

v2.0 분해: wayaudo2.py에서 이동(동작 0 변경). _TFFreqZoomMixin 상속 클러스터.
"""
import math, time, threading
import numpy as np
from PyQt5.QtGui import (QBrush, QColor, QImage, QLinearGradient, QPainter,
                         QPainterPath, QPen, QPixmap, QPolygonF)
from PyQt5.QtCore import Qt, QPointF, QRectF, QTimer, pyqtSignal
from PyQt5.QtWidgets import (QDialog, QDoubleSpinBox, QHBoxLayout, QLabel, QMenu,
                             QPushButton, QSizePolicy, QVBoxLayout, QWidget)
from spectra.core.config import T, FREQ_MARKS, fmt_delay
from spectra.core.i18n import _tx
from spectra.dsp.tf import _hilbert_env
from spectra.ui.tokens import (CF_ANNO, CF_AXIS, CF_MODE, CF_TF_TITLE, _qfont,
                               ss_btn_neutral, ss_btn_primary, ss_spin)
from spectra.ui.draw import (freq_to_x, draw_info_box, draw_freq_minor_grid,
                             FREQ_MARKS_MINOR, _fmt_freq_tick, _paint_tf_card, _tf_gutter,
                             _draw_idle_hint, _draw_tf_sel_border, _focused_capture_visible)
from spectra.ui.widgets import _apply_dark_titlebar, _grad_topline, hsep

# TF 캔버스 클러스터 전용 상수 (클러스터 밖 미사용 — 여기 정의)
_TF_CARD_COL = {'ir': '#2DD4BF', 'phase': '#A78BFA', 'mag': '#4DA3FF'}   # 패널 정체성 색
_FZ_LO_LIMIT = 20.0
_FZ_HI_LIMIT = 20000.0
_FZ_MIN_DECADES = 0.045          # 최소 스팬(log10 hi/lo) ≈ 1/7 옥타브 — 과도 확대 방지


def _ask_db_range(parent, cur_top, cur_bot):
    """dB 축 상·하한 입력 대화상자 → (top, bottom) 반환, 취소/무효면 None.
    스펙트럼·TF 공용. 입력하면 그 범위로 '고정'하는 의미(호출측이 락 설정)."""
    from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QWidget, QLabel, QDoubleSpinBox, QPushButton)
    dlg = QDialog(parent)
    dlg.setWindowTitle(_tx('dB Axis Range'))
    _apply_dark_titlebar(dlg)                        # 앱과 동일한 다크 타이틀바(네이티브 신호등 대신)
    dlg.setStyleSheet(f'background:{T("bg2")};color:{T("text")};')
    dlg.setMinimumWidth(360)
    _dim = T('text_dim')
    outer = QVBoxLayout(dlg); outer.setSpacing(0); outer.setContentsMargins(0, 0, 0, 0)
    outer.addWidget(_grad_topline())                 # SPECTRA 브랜드 그라디언트 헤어라인(정적)
    body = QWidget(); lay = QVBoxLayout(body); lay.setSpacing(11); lay.setContentsMargins(18, 15, 18, 16)
    outer.addWidget(body)
    sub = QLabel(_tx('Enter top / bottom — the axis locks to that range.'))
    sub.setStyleSheet(f'color:{_dim};font-size:11px;background:transparent;'); sub.setWordWrap(True)
    lay.addWidget(sub)
    def _spin(v):
        s = QDoubleSpinBox(); s.setRange(-160, 160); s.setDecimals(0); s.setSingleStep(3)
        s.setValue(float(v)); s.setSuffix(' dB'); s.setButtonSymbols(QDoubleSpinBox.NoButtons)
        s.setStyleSheet(ss_spin()); s.setFixedHeight(32); s.setAlignment(Qt.AlignCenter); return s
    top_sp = _spin(cur_top); bot_sp = _spin(cur_bot)
    for lbl, sp in ((_tx('Top'), top_sp), (_tx('Bottom'), bot_sp)):
        r = QHBoxLayout(); r.setSpacing(10)
        L = QLabel(lbl); L.setStyleSheet(f'color:{T("text")};font-size:12px;font-weight:600;background:transparent;')
        L.setFixedWidth(54); r.addWidget(L); r.addWidget(sp, 1); lay.addLayout(r)
    lay.addSpacing(2); lay.addWidget(hsep())
    _res = {'v': None}
    br = QHBoxLayout(); br.setSpacing(8)
    auto = QPushButton(_tx('Auto')); auto.setStyleSheet(ss_btn_neutral())
    auto.setToolTip(_tx('Auto-fit (unlock)'))
    auto.clicked.connect(lambda: (_res.__setitem__('v', 'auto'), dlg.accept()))
    br.addWidget(auto); br.addStretch()
    cancel = QPushButton(_tx('Cancel')); cancel.setStyleSheet(ss_btn_neutral()); cancel.clicked.connect(dlg.reject)
    ok = QPushButton(_tx('Apply · Lock')); ok.setStyleSheet(ss_btn_primary()); ok.setDefault(True)
    ok.clicked.connect(lambda: (_res.__setitem__('v', 'ok'), dlg.accept()))
    br.addWidget(cancel); br.addWidget(ok); lay.addLayout(br)
    if dlg.exec_() != QDialog.Accepted:
        return None
    if _res['v'] == 'auto':
        return 'auto'                # 자동맞춤(고정 해제)
    t, b = top_sp.value(), bot_sp.value()
    if t < b: t, b = b, t            # 뒤집혀 입력되면 자동 교정
    if t - b < 3:                    # 최소 3dB 스팬 보장(축 붕괴 방지)
        return None
    return (t, b)


def _db_axis_context_menu(widget, gpos, cur_top, cur_bot, is_locked,
                          on_apply, on_autofit, on_toggle_lock, extra_toggles=None):
    """dB 축 우클릭 메뉴 (스펙트럼·TF 공용). 더블클릭 자동맞춤은 그대로 두고 여기에 수동고정 추가.
    on_apply(top,bot)=입력값으로 고정 / on_autofit()=자동맞춤+락해제 / on_toggle_lock()=현재범위 고정↔해제.
    extra_toggles=[(label, checked_bool, on_toggle), …] 지정 시 구분선 아래 체크 항목 추가
    (TF='Coherence blanking', 스펙트럼='Show THD' 등 뷰별 옵션)."""
    from PyQt5.QtWidgets import QMenu
    m = QMenu(widget)
    a_in  = m.addAction(_tx('Set dB range…'))
    a_fit = m.addAction(_tx('Auto-fit (double-click)'))
    m.addSeparator()
    a_lock = m.addAction(_tx('Unlock dB axis (back to auto)') if is_locked
                         else _tx('Lock dB axis to current range'))
    _tacts = []
    if extra_toggles:
        m.addSeparator()
        for label, checked, cb in extra_toggles:
            a = m.addAction(_tx(label)); a.setCheckable(True); a.setChecked(bool(checked))
            _tacts.append((a, cb))
    act = m.exec_(gpos)
    if act is a_in:
        r = _ask_db_range(widget, cur_top, cur_bot)
        if r == 'auto':
            on_autofit()
        elif r is not None:
            on_apply(r[0], r[1])
    elif act is a_fit:
        on_autofit()
    elif act is a_lock:
        on_toggle_lock()
    else:
        for a, cb in _tacts:
            if act is a:
                cb(); break


def _catmull_seg(px, py):
    """Catmull-Rom 스플라인 → QPainterPath.  직선 lineTo 대신 cubicTo 로 부드러운 곡선.

    [PERF] 제어점 계산을 numpy로 벡터화했다. 곡선은 픽셀당 1점(1600px면 ~1550점)으로
    다운샘플되는데, 예전엔 점마다 파이썬 루프에서 float() 8회+min/max를 돌아
    이 함수 하나가 TF 탭 최다 비용이었다(3카드 mag+phase ~17ms/frame, 경로 생성만 1.96ms).
    벡터화 후 0.39ms(5배). 기하는 완전히 동일 — cubicTo 인자만 미리 계산해 넘긴다."""
    n = len(px)
    path = QPainterPath()
    if n == 0: return path
    x = np.asarray(px, dtype=np.float64); y = np.asarray(py, dtype=np.float64)
    path.moveTo(float(x[0]), float(y[0]))
    if n < 2: return path
    i = np.arange(1, n)
    i0 = np.maximum(0, i - 2); i3 = np.minimum(n - 1, i + 1)
    x1 = x[i-1]; y1 = y[i-1]; x2 = x[i]; y2 = y[i]
    cp1x = x1 + (x2 - x[i0]) / 6.0
    cp1y = y1 + (y2 - y[i0]) / 6.0
    cp2x = x2 - (x[i3] - x1) / 6.0
    cp2y = y2 - (y[i3] - y1) / 6.0
    _cubic = path.cubicTo                      # 바인딩 조회를 루프 밖으로
    for a, b, c, d, e, f in zip(cp1x.tolist(), cp1y.tolist(), cp2x.tolist(),
                                cp2y.tolist(), x2.tolist(), y2.tolist()):
        _cubic(a, b, c, d, e, f)
    return path

# ───────────────────────────────────────────
#  오디오 스레드
# ───────────────────────────────────────────


def _fz_clamp(lo, hi):
    lo = float(min(max(lo, _FZ_LO_LIMIT), _FZ_HI_LIMIT))
    hi = float(min(max(hi, _FZ_LO_LIMIT), _FZ_HI_LIMIT))
    if hi <= lo * 1.0001: hi = min(lo * 1.05, _FZ_HI_LIMIT)
    if math.log10(hi / lo) < _FZ_MIN_DECADES:      # 너무 좁으면 중심 유지하며 넓힘
        c = math.sqrt(lo * hi); half = 10 ** (_FZ_MIN_DECADES / 2)
        lo, hi = c / half, c * half
        if lo < _FZ_LO_LIMIT: lo, hi = _FZ_LO_LIMIT, _FZ_LO_LIMIT * (hi / lo)
        if hi > _FZ_HI_LIMIT: hi, lo = _FZ_HI_LIMIT, _FZ_HI_LIMIT / (hi / lo)
    return lo, hi


class _TFFreqZoomMixin:
    def _fz_init(self):
        self.f_lo = _FZ_LO_LIMIT; self.f_hi = _FZ_HI_LIMIT
        self._fzoom_cb = None          # 창이 설정: (lo,hi) → 매그·위상 둘 다 set_freq_zoom
        self._fz_drag = None           # 'box' | 'pan' | None
        self._fz_x0 = self._fz_x1 = 0

    def is_freq_zoomed(self):
        return not (abs(self.f_lo - _FZ_LO_LIMIT) < 1e-6 and abs(self.f_hi - _FZ_HI_LIMIT) < 1e-6)

    # 좌표 매핑 — 스칼라·numpy 배열 공용 (줌 f_lo~f_hi 반영)
    def _fx(self, f, pl, uw):
        lo, hi = self.f_lo, self.f_hi
        return pl + (np.log10(np.maximum(f, 1e-9) / lo) / math.log10(hi / lo)) * uw
    def _xf(self, x, pl, uw):
        lo, hi = self.f_lo, self.f_hi
        r = np.clip((np.asarray(x, dtype=float) - pl) / max(uw, 1), 0.0, 1.0)
        return lo * (hi / lo) ** r

    def _fz_marks(self):
        """라벨 찍을 주파수 눈금. 미확대=옥타브 주눈금. 확대=ISO 보조눈금까지,
        극단 확대로 표준 눈금이 범위에 거의 없으면 선형 nice 눈금 생성(라벨 0개 방지)."""
        if not self.is_freq_zoomed():
            return list(FREQ_MARKS)
        lo, hi = self.f_lo, self.f_hi
        std = [f for f in sorted(set(FREQ_MARKS) | set(FREQ_MARKS_MINOR)) if lo <= f <= hi]
        if len(std) >= 2:
            return std
        span = hi - lo                                   # 좁은 확대 → 선형 nice 스텝
        base = 10 ** math.floor(math.log10(span / 4.0)) if span > 0 else 1.0
        step = next(s * base for s in (1, 2, 2.5, 5, 10) if s * base >= span / 4.0)
        out, v = [], math.ceil(lo / step) * step
        while v <= hi + 1e-6:
            out.append(round(v, 3)); v += step
        return out or [round(lo, 1), round(hi, 1)]

    # 줌 상태 반영 (창이 매그·위상 둘 다 호출)
    def set_freq_zoom(self, lo, hi):
        lo, hi = _fz_clamp(lo, hi)
        if abs(lo - self.f_lo) < 1e-9 and abs(hi - self.f_hi) < 1e-9: return
        self.f_lo, self.f_hi = lo, hi
        self._cache = None
        if hasattr(self, '_cap_pix'): self._cap_pix = None   # 캡처곡선도 줌 따라 재빌드
        self.update()
    def _fz_apply(self, lo, hi):
        if self._fzoom_cb: self._fzoom_cb(*_fz_clamp(lo, hi))   # 창이 연동
        else: self.set_freq_zoom(lo, hi)

    def _fz_zoom_around(self, f_center, factor):
        L, Hh = math.log10(self.f_lo), math.log10(self.f_hi)
        C = min(max(math.log10(max(f_center, 1e-9)), L), Hh)
        r = (C - L) / (Hh - L) if Hh > L else 0.5
        span = (Hh - L) * factor
        nL = C - r * span
        self._fz_apply(10 ** nL, 10 ** (nL + span))
    def _fz_pan_px(self, dx_px):
        pl, pr = self.PAD_L, self.PAD_R; uw = max(self.width() - pl - pr, 1)
        L, Hh = math.log10(self.f_lo), math.log10(self.f_hi)
        d = -(dx_px / uw) * (Hh - L)
        # 벽(20Hz/20kHz)에서는 이동만 멈추고 스팬 보존 — _fz_clamp가 lo/hi를 독립 clip해
        # 한쪽만 밀리며 조용히 줌인되던 것 방지. [PAN_WALL]
        d = max(math.log10(_FZ_LO_LIMIT) - L, min(math.log10(_FZ_HI_LIMIT) - Hh, d))
        if abs(d) < 1e-12: return
        self._fz_apply(10 ** (L + d), 10 ** (Hh + d))
    def _fz_reset(self):
        self._fz_apply(_FZ_LO_LIMIT, _FZ_HI_LIMIT)

    # 이벤트 — 각 캔버스 핸들러가 호출, 처리했으면 True
    def _fz_wheel(self, e):
        d = e.angleDelta(); dy, dx = d.y(), d.x()
        if dx != 0 and abs(dx) > abs(dy):            # 트랙패드 두 손가락 좌우 = 팬
            self._fz_pan_px(dx * 0.5); e.accept(); return True
        if dy != 0:                                  # 휠/핀치 = 커서 기준 확대·축소
            pl, pr = self.PAD_L, self.PAD_R; uw = max(self.width() - pl - pr, 1)
            fc = float(self._xf(e.x(), pl, uw))
            self._fz_zoom_around(fc, 0.85 if dy > 0 else 1 / 0.85); e.accept(); return True
        return False
    def _fz_press(self, e):
        if e.button() != Qt.LeftButton: return False
        if e.modifiers() & Qt.ShiftModifier:
            self._fz_drag = 'pan'; self._fz_x0 = e.x(); self.setCursor(Qt.ClosedHandCursor)
        else:
            self._fz_drag = 'box'; self._fz_x0 = self._fz_x1 = e.x()
        return True
    def _fz_move(self, e):
        if self._fz_drag is None: return False
        if self._fz_drag == 'pan':
            self._fz_pan_px(e.x() - self._fz_x0); self._fz_x0 = e.x()
        else:
            self._fz_x1 = e.x(); self.update()
        return True
    def _fz_release(self, e):
        if self._fz_drag is None: return False
        mode = self._fz_drag; self._fz_drag = None; self.unsetCursor()
        if mode == 'box':
            pl, pr = self.PAD_L, self.PAD_R; uw = max(self.width() - pl - pr, 1)
            x0, x1 = sorted((self._fz_x0, self._fz_x1))
            if x1 - x0 >= 8:                          # 최소 드래그 폭
                self._fz_apply(float(self._xf(x0, pl, uw)), float(self._xf(x1, pl, uw)))
            self.update()
        return True
    def _fz_key(self, e):
        if not (e.modifiers() & Qt.ControlModifier): return False    # macOS Cmd
        k = e.key(); c = math.sqrt(self.f_lo * self.f_hi)
        if k in (Qt.Key_Equal, Qt.Key_Plus):  self._fz_zoom_around(c, 0.7); return True
        if k == Qt.Key_Minus:                 self._fz_zoom_around(c, 1 / 0.7); return True
        if k == Qt.Key_0:                     self._fz_reset(); return True
        return False
    def _fz_overlay(self, p, W, H):
        if self._fz_drag == 'box' and abs(self._fz_x1 - self._fz_x0) >= 2:
            x0, x1 = sorted((self._fz_x0, self._fz_x1))
            rr = QRectF(x0, self.PAD_T, x1 - x0, H - self.PAD_T - self.PAD_B)
            p.fillRect(rr, QColor(90, 150, 230, 55))
            p.setPen(QPen(QColor(T('accent')), 1, Qt.DashLine)); p.setBrush(Qt.NoBrush); p.drawRect(rr)


#  TF Phase Canvas
# ───────────────────────────────────────────


class TFPhaseCanvas(_TFFreqZoomMixin, QWidget):
    PAD_L=40; PAD_R=15; PAD_T=16; PAD_B=28   # PAD_T/B: 맨위·맨아래 라벨이 카드 둥근 프레임에 안 겹치게(3패널 통일 28)
    cursor_x_changed = pyqtSignal(int)
    cursor_left      = pyqtSignal()
    _cap_built       = pyqtSignal()
    def __init__(self):
        super().__init__()
        self.setMinimumSize(400,110); self.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Expanding)
        self.setMouseTracking(True); self.setAttribute(Qt.WA_OpaquePaintEvent,True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setToolTip(_tx('Frequency axis:\nWheel = zoom at cursor   ·   Drag = box zoom   ·   Shift+drag = pan\nDouble-click = reset to full range   ·   ⌘ +/− = step zoom'))
        self._fz_init()   # 주파수축 줌/팬 상태(f_lo/f_hi)
        self.freqs=None; self.ph_wrap=None; self.ph_unwr=None; self.grp_ms=None
        self.coherence=None; self.mag=None; self.coh_blank=0.5
        self.phase_mode=0
        self.ph_min=-150.0; self.ph_max=150.0  # Smaart 기본값: -150~150° (중심 0°)
        self._mx=-1; self._peer_mx=-1; self._cache=None
        self._captures=[]
        self._cap_pix=None; self._cap_pix_key=None
        self._front_idx=None; self._live_on_top=False
        self._cap_building = False
        self._cap_img_pending = None; self._cap_key_pending = None
        self._cap_built.connect(self._apply_cap_built)
        self._tf_extra_phase = {}  # {ch_idx: {'color', 'f', 'ph_wrap', 'ph_unwr', 'grp_ms'}}
        self._tf_avg = None   # {'color','f','ph_wrap','ph_unwr','grp_ms'} — 라이브 멀티마이크 평균 오버레이
        self._live_color = None   # primary(1번) 곡선 사용자색. None=기본 T('green')
        self._hide_individual = False   # '평균만' — 개별 라이브 곡선 숨김(AVG는 계속 그림)
        # Reference/Delta 비교
        self._ref_f = None; self._ref_pw = None; self._ref_pu = None; self._ref_gm = None
        self._delta = False; self._abs_ph = None
        self._front_extra = None  # None/-1=primary 맨앞, int=해당 pair idx 맨앞

    def set_front_curve(self, key):
        self._front_extra = key; self.update()

    def set_reference(self, f, pw, pu, gm):
        self._ref_f  = np.asarray(f,  dtype=np.float32) if f  is not None else None
        self._ref_pw = np.asarray(pw, dtype=np.float32) if pw is not None else None
        self._ref_pu = np.asarray(pu, dtype=np.float32) if pu is not None else None
        self._ref_gm = np.asarray(gm, dtype=np.float32) if gm is not None else None
        self._cache=None; self._cap_pix=None; self.update()

    def set_delta_mode(self, on):
        on = bool(on)
        if on == self._delta: return
        self._delta = on
        if on:
            self._abs_ph = (self.ph_min, self.ph_max)
            if self.phase_mode == 2: self.ph_min, self.ph_max = -15.0, 15.0
            else:                    self.ph_min, self.ph_max = -180.0, 180.0
        elif self._abs_ph is not None:
            self.ph_min, self.ph_max = self._abs_ph; self._abs_ph = None
        self._cache=None; self._cap_pix=None; self.update()

    def set_tf_extra_phase(self, ch_idx, color, f, ph_wrap, ph_unwr, grp_ms, mag=None):
        self._tf_extra_phase[ch_idx] = {'color': color, 'f': f,
                                         'ph_wrap': ph_wrap, 'ph_unwr': ph_unwr, 'grp_ms': grp_ms,
                                         'mag': mag}   # 커서 리드아웃 dB 표시용(1번 카드와 동일)
        self.update()

    def clear_tf_extra_phase(self, ch_idx):
        self._tf_extra_phase.pop(ch_idx, None); self.update()

    def clear_all_tf_extra_phase(self):
        self._tf_extra_phase.clear(); self.update()

    def set_tf_average(self, color, f, ph_wrap, ph_unwr, grp, width=2.8):
        # grp_ms 키로 저장 — _draw_extra_phase_curve()가 참조하는 이름과 일치시켜 재사용
        self._tf_avg = {'color': color, 'f': f, 'ph_wrap': ph_wrap,
                        'ph_unwr': ph_unwr, 'grp_ms': grp, 'w': width}; self.update()

    def clear_tf_average(self):
        if getattr(self, '_tf_avg', None) is not None:
            self._tf_avg = None; self.update()

    def _apply_cap_built(self):
        img, key = self._cap_img_pending, self._cap_key_pending
        self._cap_img_pending = self._cap_key_pending = None
        if img is not None:
            self._cap_pix = QPixmap.fromImage(img)
            self._cap_pix_key = key
            self.update()

    def _trigger_cap_build(self, W, H, cap_key):
        if self._cap_building: return
        self._cap_building = True
        caps = [dict(c) for c in self._captures]
        front = self._front_idx
        threading.Thread(target=self._bg_cap_build,
                         args=(W, H, cap_key, caps, front),
                         daemon=True).start()

    def _bg_cap_build(self, W, H, cap_key, caps, front):
        try:
            img = self._build_cap_img(W, H, caps, front)
            self._cap_img_pending = img
            self._cap_key_pending = cap_key
            self._cap_built.emit()
        except Exception:
            pass
        finally:
            self._cap_building = False

    def _draw_cap_curve(self, p, cap, W, H, emph=False):
        # 단일 위상 캡쳐 곡선 — 베이스(dimmed)·front 오버레이(emph) 공용
        pl=self.PAD_L; pr=self.PAD_R; pt=self.PAD_T; pb=self.PAD_B
        dh=H-pt-pb; uw=W-pl-pr; ny=20000
        rng=self.ph_max-self.ph_min if self.ph_max!=self.ph_min else 1.0
        max_pts=max(int(uw),200)  # 픽셀 1:1
        data=[cap['ph_wrap'],cap['ph_unwr'],cap['grp_ms']][self.phase_mode]
        if data is None: return
        freqs=cap['f']
        xs=self._fx(freqs,pl,uw)
        if self.phase_mode==0:
            mid=(self.ph_min+self.ph_max)/2
            data_plot=data-360.0*np.round((data-mid)/360.0)
        else:
            data_plot=data
        ys=pt+np.clip(((self.ph_max-data_plot)/rng*dh).astype(float),0,dh)
        if len(xs)>max_pts:
            _ids=np.linspace(0,len(xs)-1,max_pts,dtype=int)
            xs=xs[_ids]; ys=ys[_ids]; data_plot=data_plot[_ids]
        is_wrap=(self.phase_mode==0)
        path=QPainterPath(); seg_x=[]; seg_y=[]
        def _flush():
            if len(seg_x)>=2: path.addPath(_catmull_seg(seg_x,seg_y))
            seg_x.clear(); seg_y.clear()
        for i in range(len(xs)):
            brk=(i>0 and is_wrap and abs(data_plot[i]-data_plot[i-1])>270.0)
            if brk:
                _flush()
            else:
                seg_x.append(float(xs[i])); seg_y.append(float(ys[i]))
        _flush()
        qc=QColor(cap['color'])
        if emph:
            p.setPen(QPen(qc,3.0))
        else:
            qc.setAlpha(140); p.setPen(QPen(qc,1.4))
        p.setBrush(Qt.NoBrush); p.drawPath(path)

    def _build_cap_img(self, W, H, caps, front):
        # 베이스 = 보이는 캡쳐 전부 dimmed. front 강조는 paintEvent 오버레이.
        from PyQt5.QtGui import QImage
        img=QImage(W,H,QImage.Format_ARGB32_Premultiplied); img.fill(0)
        p=QPainter(img); p.setRenderHint(QPainter.Antialiasing,True)
        for cap in caps:
            if not cap.get('visible', True): continue
            self._draw_cap_curve(p, cap, W, H, emph=False)
        p.end()
        return img

    def _cap_base_key(self, n=None):
        if n is None: n=len(self._captures)
        return (self.width(), self.height(), self.ph_max, self.ph_min, self.phase_mode, self.coh_blank, n)

    def _append_cap_incr(self, cap):
        # 베이스 유효 시 새 캡쳐 1개만 dimmed로 얹기(O(1)). 무효면 다음 paint에서 전체 rebuild.
        if self._cap_pix is not None and self._cap_pix_key==self._cap_base_key(len(self._captures)-1) and cap.get('visible', True):
            p=QPainter(self._cap_pix); p.setRenderHint(QPainter.Antialiasing,True)
            self._draw_cap_curve(p, cap, self._cap_pix.width(), self._cap_pix.height(), emph=False)
            p.end()
            self._cap_pix_key=self._cap_base_key()   # 새 count 반영 → 재빌드 안 함
        else:
            self._cap_pix=None

    def _build_cap_pix(self, W, H):
        img = self._build_cap_img(W, H, list(self._captures), self._front_idx)
        self._cap_pix = QPixmap.fromImage(img)
        self._cap_pix_key = self._cap_base_key()

    def add_capture(self, label, color):
        if self.freqs is None: return
        cap={
            'f': self.freqs.copy(),
            'ph_wrap': self.ph_wrap.copy() if self.ph_wrap is not None else None,
            'ph_unwr': self.ph_unwr.copy() if self.ph_unwr is not None else None,
            'grp_ms':  self.grp_ms.copy()  if self.grp_ms  is not None else None,
            'coh':     self.coherence.copy() if self.coherence is not None else None,
            'color': color, 'label': label
        }
        self._captures.append(cap)
        self._append_cap_incr(cap)
        self._last_cap_t=time.monotonic(); self.update()

    def add_capture_data(self, label, color, f, ph_wrap, ph_unwr, grp_ms, coh=None):
        """외부 데이터(extra 카드 등)로 직접 위상 캡쳐 추가."""
        if f is None: return
        cap={
            'f': np.asarray(f, dtype=np.float32).copy(),
            'ph_wrap': np.asarray(ph_wrap, dtype=np.float32).copy() if ph_wrap is not None else None,
            'ph_unwr': np.asarray(ph_unwr, dtype=np.float32).copy() if ph_unwr is not None else None,
            'grp_ms':  np.asarray(grp_ms,  dtype=np.float32).copy() if grp_ms  is not None else None,
            'coh':     np.asarray(coh,     dtype=np.float32).copy() if coh     is not None else None,
            'color': color, 'label': label
        }
        self._captures.append(cap)
        self._append_cap_incr(cap)
        self._last_cap_t=time.monotonic(); self.update()

    def recapture_live(self, idx):
        """primary 위상 캡쳐 idx 를 현재 라이브로 덮어쓰기 (색/이름 유지)."""
        if self.freqs is None or not (0 <= idx < len(self._captures)): return False
        c = self._captures[idx]
        c['f'] = self.freqs.copy()
        c['ph_wrap'] = self.ph_wrap.copy() if self.ph_wrap is not None else None
        c['ph_unwr'] = self.ph_unwr.copy() if self.ph_unwr is not None else None
        c['grp_ms']  = self.grp_ms.copy()  if self.grp_ms  is not None else None
        c['coh']     = self.coherence.copy() if self.coherence is not None else None
        self._cap_pix=None; self._last_cap_t=time.monotonic(); self.update()
        return True

    def recapture_data(self, idx, f, ph_wrap, ph_unwr, grp_ms, coh=None):
        """extra 카드 위상 캡쳐 idx 를 외부 데이터로 덮어쓰기."""
        if f is None or not (0 <= idx < len(self._captures)): return False
        c = self._captures[idx]
        c['f'] = np.asarray(f, dtype=np.float32).copy()
        c['ph_wrap'] = np.asarray(ph_wrap, dtype=np.float32).copy() if ph_wrap is not None else None
        c['ph_unwr'] = np.asarray(ph_unwr, dtype=np.float32).copy() if ph_unwr is not None else None
        c['grp_ms']  = np.asarray(grp_ms,  dtype=np.float32).copy() if grp_ms  is not None else None
        c['coh']     = np.asarray(coh,     dtype=np.float32).copy() if coh     is not None else None
        self._cap_pix=None; self._last_cap_t=time.monotonic(); self.update()
        return True

    def remove_capture(self, idx):
        if 0 <= idx < len(self._captures):
            self._captures.pop(idx)
            if self._front_idx is not None:
                if self._front_idx==idx: self._front_idx=None
                elif self._front_idx>idx: self._front_idx-=1
            self._cap_pix=None; self._last_cap_t=time.monotonic(); self.update()

    def bring_to_front(self, idx):
        if 0 <= idx < len(self._captures):
            self._front_idx=idx; self._live_on_top=False
            self.update()   # front=paintEvent 오버레이 → 베이스 재빌드 불필요

    def set_data(self,f,pw,pu,gm,coh=None,mag=None):
        self.freqs=f; self.ph_wrap=pw; self.ph_unwr=pu; self.grp_ms=gm
        self.coherence=coh; self.mag=mag
        self.update()  # 배경 캐시 유지 — 커브만 갱신

    def clear(self):
        self.freqs=self.ph_wrap=self.ph_unwr=self.grp_ms=None
        self.mag=None; self._cache=None; self.update()

    def set_mode(self,idx):
        self.phase_mode=idx
        if idx==0:   self.ph_min,self.ph_max=-150.0,150.0   # Smaart 기본: -150~150° (중심 0°)
        elif idx==1: self.ph_min,self.ph_max=-540.0,540.0
        else:        self.ph_min,self.ph_max=-5.0,30.0
        self._cache=None; self._cap_pix=None; self.update()

    def mouseMoveEvent(self,e):
        if self._fz_move(e): return          # 박스줌 러버밴드 / 팬 드래그 중
        x=e.x()
        if x!=self._mx:
            self._mx=x; self._peer_mx=-1; self.update()
            self._pending_x=x
            if not getattr(self,'_cursor_timer_active',False):
                self._cursor_timer_active=True
                QTimer.singleShot(16,self._emit_cursor)
    def _emit_cursor(self):
        self._cursor_timer_active=False
        self.cursor_x_changed.emit(self._pending_x)
    def leaveEvent(self,e):
        self._mx=-1; self.update(); self.cursor_left.emit()
    def set_peer_cursor(self,x):
        if x!=self._peer_mx: self._peer_mx=x; self.update()
    def clear_peer_cursor(self):
        if self._peer_mx!=-1: self._peer_mx=-1; self.update()
    def resizeEvent(self,e): self._cache=None; self.update()

    def mouseDoubleClickEvent(self,e):
        self._fz_reset()                     # 주파수축 전대역 리셋 (Smaart 테두리클릭 방식)
        if self.phase_mode==0:   self.ph_min,self.ph_max=-150.0,150.0
        elif self.phase_mode==1: self.ph_min,self.ph_max=-540.0,540.0
        else:                    self.ph_min,self.ph_max=-5.0,30.0
        self._cache=None; self.update()

    def wheelEvent(self, e):
        if self._fz_wheel(e): return
        e.ignore()

    def enterEvent(self, e): self.setFocus(); super().enterEvent(e)
    def mousePressEvent(self, e):
        self.setFocus()
        if self._fz_press(e): return         # 박스줌/팬 시작
        super().mousePressEvent(e)
    def mouseReleaseEvent(self, e):
        if self._fz_release(e): return
        super().mouseReleaseEvent(e)

    def keyPressEvent(self, e):
        if self._fz_key(e): return           # Cmd± 줌 / Cmd0 리셋
        key = e.key()
        if key in (Qt.Key_Up, Qt.Key_Down):
            step = 1 if key == Qt.Key_Up else -1
            if self.phase_mode == 0:
                span = self.ph_max - self.ph_min
                mid = (self.ph_min + self.ph_max) / 2 + step * 30.0
                mid = ((mid + 180.0) % 360.0) - 180.0
                self.ph_min = mid - span / 2; self.ph_max = mid + span / 2
            else:
                d = (self.ph_max - self.ph_min) * 0.05 * step
                self.ph_min += d; self.ph_max += d
                if self.phase_mode == 1:
                    span = self.ph_max - self.ph_min
                    self.ph_min = max(-3600.0, min(self.ph_min, 3600.0 - span))
                    self.ph_max = self.ph_min + span
            self._cache = None; self.update()
        else:
            super().keyPressEvent(e)

    def _build_cache(self,W,H):
        from PyQt5.QtGui import QPixmap
        dpr=self.devicePixelRatio()
        px=QPixmap(int(W*dpr),int(H*dpr)); px.setDevicePixelRatio(dpr); px.fill(_tf_gutter())
        p=QPainter(px)
        p.setRenderHint(QPainter.Antialiasing, True); p.setRenderHint(QPainter.TextAntialiasing)
        _paint_tf_card(p, W, H)
        pl=self.PAD_L; pr=self.PAD_R; pt=self.PAD_T; pb=self.PAD_B
        dh=H-pt-pb; uw=W-pl-pr; ny=20000
        rng=self.ph_max-self.ph_min if self.ph_max!=self.ph_min else 1.0
        is_grp=(self.phase_mode==2); unit=' ms' if is_grp else '°'
        p.setFont(_qfont(CF_AXIS))
        if is_grp:
            gs=[v for v in [-5,0,5,10,15,20,25,30] if self.ph_min<=v<=self.ph_max]
        else:
            rng_deg=self.ph_max-self.ph_min
            if   rng_deg<=360:   step_deg=30
            elif rng_deg<=720:   step_deg=60
            elif rng_deg<=1440:  step_deg=90
            elif rng_deg<=2880:  step_deg=180
            else:                step_deg=360
            start=int(math.ceil(self.ph_min/step_deg))*step_deg
            gs=[v for v in range(start,int(self.ph_max)+step_deg,step_deg) if self.ph_min<=v<=self.ph_max]
        _lg=p.fontMetrics().height()+2; _last_ly=None   # 짧은 패널서 라벨 겹침 방지(그리드는 유지)
        for deg in gs:
            y=int(pt+(self.ph_max-deg)/rng*dh)
            is0=(deg==0)
            p.setPen(QPen(QColor(T('grid_ref')),1.5 if is0 else 0.7,Qt.SolidLine))
            p.drawLine(pl,y,W-pr,y)
            if _last_ly is None or abs(y-_last_ly)>=_lg:
                p.setPen(QColor(T('graph_txt')))
                lbl=f'{deg}{unit}' if is_grp else f'{int(deg)}°'
                p.drawText(0,y-8,pl-2,16,Qt.AlignRight|Qt.AlignVCenter,lbl); _last_ly=y
        p.setFont(_qfont(CF_AXIS, True)); last_lx=-999
        draw_freq_minor_grid(p, pl, pr, uw, pt, pb, W, H, self.f_hi, self.f_lo)
        for f in self._fz_marks():
            if f<self.f_lo or f>self.f_hi: continue
            fx=freq_to_x(f,pl,uw,self.f_hi,self.f_lo)
            if not pl<=fx<=W-pr: continue
            p.setPen(QPen(QColor(T('grid')),1)); p.drawLine(int(fx),pt,int(fx),H-pb)
            if fx-last_lx<40: continue
            last_lx=fx
            txt=_fmt_freq_tick(f) if self.is_freq_zoomed() else (f'{int(f//1000)}k' if f>=1000 else str(int(f)))
            tw=p.fontMetrics().horizontalAdvance(txt)
            p.setPen(QColor(T('graph_txt'))); p.drawText(max(pl,min(int(fx-tw/2),W-pr-tw)),H-pb+16,txt)
        mode_lbl=['Phase  Wrapped','Phase  Unwrapped','Group Delay'][self.phase_mode]+'  ▾'
        p.setFont(_qfont(CF_TF_TITLE, True)); p.setPen(QColor(_TF_CARD_COL['phase']))
        p.drawText(pl+4,pt+15,mode_lbl)
        p.end(); self._cache=px

    def _draw_grid_lines(self, p, W, H):
        pl=self.PAD_L; pr=self.PAD_R; pt=self.PAD_T; pb=self.PAD_B
        dh=H-pt-pb; uw=W-pl-pr; ny=20000
        rng=self.ph_max-self.ph_min if self.ph_max!=self.ph_min else 1.0
        is_grp=(self.phase_mode==2)
        if is_grp:
            gs=[v for v in [-5,0,5,10,15,20,25,30] if self.ph_min<=v<=self.ph_max]
        else:
            rng_deg=self.ph_max-self.ph_min
            if   rng_deg<=360:   step_deg=30
            elif rng_deg<=720:   step_deg=60
            elif rng_deg<=1440:  step_deg=90
            elif rng_deg<=2880:  step_deg=180
            else:                step_deg=360
            start=int(math.ceil(self.ph_min/step_deg))*step_deg
            gs=[v for v in range(start,int(self.ph_max)+step_deg,step_deg) if self.ph_min<=v<=self.ph_max]
        for deg in gs:
            y=int(pt+(self.ph_max-deg)/rng*dh)
            is0=(deg==0)
            p.setPen(QPen(QColor(T('grid_ref')),1.5 if is0 else 0.7,Qt.SolidLine))
            p.drawLine(pl,y,W-pr,y)
        draw_freq_minor_grid(p, pl, pr, uw, pt, pb, W, H, self.f_hi, self.f_lo)
        for f in self._fz_marks():
            if f<self.f_lo or f>self.f_hi: continue
            fx=freq_to_x(f,pl,uw,self.f_hi,self.f_lo)
            if not pl<=fx<=W-pr: continue
            p.setPen(QPen(QColor(T('grid')),1)); p.drawLine(int(fx),pt,int(fx),H-pb)

    def _draw_curve(self, p, W, H):
        refmode = self._delta and self._ref_f is not None
        delta_no_ref = self._delta and not refmode  # 델타 모드인데 기준 없음 → 전부 숨김
        if delta_no_ref:
            return
        p.setRenderHint(QPainter.Antialiasing, False)   # [TF_LIVE_CURVE_PERF] 라이브 위상 곡선 AA off (뒤에서 복원)
        _hide = getattr(self, '_hide_individual', False)   # '평균만' — 개별 라이브 곡선 숨김(AVG는 아래서 항상 그림)
        # E 포커스: 포커스된 하나만 밝게, 나머지 라이브 곡선은 흐리게(alpha 140)
        _capf = _focused_capture_visible(self)
        _fk2 = self._front_extra
        def _is_focus(key):
            if _capf: return False
            if key is None or key == -1: return (_fk2 is None or _fk2 == -1)
            return _fk2 == key
        def _col(c, key):
            qc = QColor(c)
            if not _is_focus(key): qc.setAlpha(140)
            return qc
        # ── primary 곡선 (데이터 있을 때만; 없으면 extra만 그림 — primary 숨김 시 카드2 위상 유지) ──
        path = None
        data = None if self.freqs is None else [self.ph_wrap,self.ph_unwr,self.grp_ms][self.phase_mode]
        if data is not None:
            if refmode:
                ref_data=[self._ref_pw,self._ref_pu,self._ref_gm][self.phase_mode]
                if ref_data is None:
                    data = None
                else:
                    data = data - np.interp(self.freqs, self._ref_f, ref_data)
        if data is not None and not _hide:
            pl=self.PAD_L; pr=self.PAD_R; pt=self.PAD_T; pb=self.PAD_B
            dh=H-pt-pb; uw=W-pl-pr; ny=20000
            rng=self.ph_max-self.ph_min if self.ph_max!=self.ph_min else 1.0
            xs=self._fx(self.freqs,pl,uw)
            if self.phase_mode==0:
                mid=(self.ph_min+self.ph_max)/2
                data_plot=data-360.0*np.round((data-mid)/360.0)
            else:
                data_plot=data
            ys=pt+np.clip(((self.ph_max-data_plot)/rng*dh).astype(float),0,dh)
            # 화면 너비에 맞춰 다운샘플: Python 루프 반복 수 축소 → GIL 점유 시간 감소
            max_pts=max(int(uw),200)
            if len(xs)>max_pts:
                _ids=np.linspace(0,len(xs)-1,max_pts,dtype=int)
                xs=xs[_ids]; ys=ys[_ids]; data_plot=data_plot[_ids]
            is_wrap=(self.phase_mode==0)
            # Catmull-Rom 스플라인: 연속 구간별로 부드러운 곡선 생성
            path=QPainterPath(); seg_x=[]; seg_y=[]
            def _flush():
                if len(seg_x) >= 2:
                    path.addPath(_catmull_seg(seg_x, seg_y))
                seg_x.clear(); seg_y.clear()
            for i in range(len(xs)):
                break_here=(i>0 and is_wrap and abs(data_plot[i]-data_plot[i-1])>270.0)
                if break_here:
                    _flush()
                else:
                    seg_x.append(float(xs[i])); seg_y.append(float(ys[i]))
            _flush()
            p.setPen(QPen(_col(self._live_color or '#33FF66', None),2.0)); p.setBrush(Qt.NoBrush); p.drawPath(path)
        # ── 추가 채널 곡선 (primary 유무와 무관하게 그림; front 는 마지막에 굵게) ──
        fk=self._front_extra
        if not _hide:
            for key, ex in self._tf_extra_phase.items():
                if key==fk: continue
                self._draw_extra_phase_curve(p, W, H, ex, dim=not _is_focus(key))
        # front(포커스) 맨 앞 굵게 재드로우 — 캡쳐 포커스 시엔 생략
        if self._tf_extra_phase and not _capf and not _hide:
            if fk is None or fk==-1:
                if path is not None:
                    p.setPen(QPen(QColor(self._live_color or '#33FF66'),3.4)); p.setBrush(Qt.NoBrush); p.drawPath(path)
            elif fk in self._tf_extra_phase:
                self._draw_extra_phase_curve(p, W, H, self._tf_extra_phase[fk], width=3.4)
        # 멀티마이크 평균(AVG) — 항상 맨 위(front 재드로우 이후) 굵은 실선 오버레이 (extra 위상 곡선과 동일 좌표변환 재사용)
        if self._tf_avg is not None:
            self._draw_extra_phase_curve(p, W, H, self._tf_avg, width=self._tf_avg.get('w', 2.8))
        p.setRenderHint(QPainter.Antialiasing, True)   # 라이브 곡선 후 AA 복원 [TF_LIVE_CURVE_PERF]

    def _draw_extra_phase_curve(self, p, W, H, ex, width=1.8, dim=False):
        f_arr = ex.get('f'); data_arr = [ex.get('ph_wrap'), ex.get('ph_unwr'), ex.get('grp_ms')][self.phase_mode]
        if f_arr is None or data_arr is None: return
        refmode = self._delta and self._ref_f is not None
        if self._delta and not refmode: return
        if refmode:
            ref_data=[self._ref_pw,self._ref_pu,self._ref_gm][self.phase_mode]
            if ref_data is None: return
            data_arr = data_arr - np.interp(f_arr, self._ref_f, ref_data)
        pl=self.PAD_L; pr=self.PAD_R; pt=self.PAD_T; pb=self.PAD_B
        dh=H-pt-pb; uw=W-pl-pr; ny=20000
        rng=self.ph_max-self.ph_min if self.ph_max!=self.ph_min else 1.0
        xs=self._fx(f_arr,pl,uw)
        if self.phase_mode==0:
            mid=(self.ph_min+self.ph_max)/2
            data_plot=data_arr-360.0*np.round((data_arr-mid)/360.0)
        else:
            data_plot=data_arr
        ys=pt+np.clip(((self.ph_max-data_plot)/rng*dh).astype(float),0,dh)
        max_pts=max(int(uw),200)
        if len(xs)>max_pts:
            _ids=np.linspace(0,len(xs)-1,max_pts,dtype=int)
            xs=xs[_ids]; ys=ys[_ids]; data_plot=data_plot[_ids]
        is_wrap=(self.phase_mode==0)
        path=QPainterPath(); seg_x=[]; seg_y=[]
        def _flush2():
            if len(seg_x)>=2: path.addPath(_catmull_seg(seg_x,seg_y))
            seg_x.clear(); seg_y.clear()
        for i in range(len(xs)):
            brk=(i>0 and is_wrap and abs(data_plot[i]-data_plot[i-1])>270.0)
            if brk:
                _flush2()
            else:
                seg_x.append(float(xs[i])); seg_y.append(float(ys[i]))
        _flush2()
        p.setRenderHint(QPainter.Antialiasing, False)   # [TF_LIVE_CURVE_PERF]
        _qc=QColor(ex['color'])
        if dim: _qc.setAlpha(140)
        p.setPen(QPen(_qc,width)); p.setBrush(Qt.NoBrush); p.drawPath(path)

    def paintEvent(self,ev):
        W=self.width(); H=self.height()
        if self._cache is None or self._cache.size()!=self.size():
            self._build_cache(W,H)
        p=QPainter(self); p.drawPixmap(0,0,self._cache)

        # E 포커스: 캡쳐 선택 시 라이브(흐림) 먼저 → 포커스 캡쳐(밝음) 위. 라이브 포커스 시 반대.
        _cap_focus = _focused_capture_visible(self)
        def _draw_caps():
            if not (self._captures and not self._delta): return  # 델타 모드 절대값 캡쳐 숨김
            _cap_key=self._cap_base_key()
            if self._cap_pix is None or self._cap_pix_key!=_cap_key:
                self._trigger_cap_build(W, H, _cap_key)
            if self._cap_pix is not None:
                p.drawPixmap(0,0,self._cap_pix)
            fi=self._front_idx
            if fi is not None and 0<=fi<len(self._captures) and self._captures[fi].get('visible',True):
                self._draw_cap_curve(p, self._captures[fi], W, H, emph=True)   # 선택 캡쳐 강조(재빌드 없이)
        p.save(); p.setClipRect(QRectF(self.PAD_L, self.PAD_T, W-self.PAD_L-self.PAD_R, H-self.PAD_T-self.PAD_B))
        if _cap_focus:
            self._draw_curve(p,W,H); _draw_caps()
        else:
            _draw_caps(); self._draw_curve(p,W,H)
        p.restore()                                    # 확대 시 범위 밖 곡선이 왼쪽 여백으로 삐져나가지 않게 클립

        self._draw_grid_lines(p, W, H)

        pl=self.PAD_L; pr=self.PAD_R; pt=self.PAD_T; pb=self.PAD_B; uw=W-pl-pr; ny=20000
        dh=H-pt-pb; rng=max(self.ph_max-self.ph_min,1.0)
        _CUR  = QColor(255,220,50,210)   # 밝은 황색
        _PEER = QColor(255,220,50,100)
        # 피어 커서: 수직선 + 수평선 (자기 데이터로 y 계산)
        if pl<=self._peer_mx<=W-pr:
            p.setPen(QPen(_PEER,1,Qt.DashLine))
            p.drawLine(self._peer_mx,pt,self._peer_mx,H-pb)
            if self.freqs is not None:
                data=[self.ph_wrap,self.ph_unwr,self.grp_ms][self.phase_mode]
                if data is not None:
                    pfreq=float(self._xf(self._peer_mx,pl,uw))
                    _pi=np.searchsorted(self.freqs,pfreq)
                    if _pi>0 and (_pi>=len(self.freqs) or self.freqs[_pi]-pfreq>pfreq-self.freqs[_pi-1]): _pi-=1
                    pidx=int(np.clip(_pi,0,len(data)-1))
                    if self.phase_mode==0:
                        mid=(self.ph_min+self.ph_max)/2
                        pval=float(data[pidx])-360.0*round((float(data[pidx])-mid)/360.0)
                    else:
                        pval=float(data[pidx])
                    pcy=int(pt+np.clip((self.ph_max-pval)/rng*dh,0,dh))
                    p.drawLine(pl,pcy,W-pr,pcy)
        # 자체 커서: 십자 + info box — 선택(front) 카드 우선 → primary → 아무 extra
        _fk = self._front_extra
        _cap_col = None
        if _focused_capture_visible(self):   # 포커스된 캡쳐 값 우선
            _cap = self._captures[self._front_idx]
            _cf = _cap.get('f')
            data = [_cap.get('ph_wrap'), _cap.get('ph_unwr'), _cap.get('grp_ms')][self.phase_mode]
            _cmag = None; _cap_col = _cap.get('color')
        elif isinstance(_fk, int) and _fk != -1 and _fk in self._tf_extra_phase:
            _ex = self._tf_extra_phase[_fk]
            _cf = _ex.get('f')
            data = [_ex.get('ph_wrap'), _ex.get('ph_unwr'), _ex.get('grp_ms')][self.phase_mode]
            _cmag = _ex.get('mag')
        else:
            _cf = self.freqs
            data = None if self.freqs is None else [self.ph_wrap,self.ph_unwr,self.grp_ms][self.phase_mode]
            _cmag = self.mag
            if (_cf is None or data is None) and self._tf_extra_phase:
                _ex = next(iter(self._tf_extra_phase.values()))
                _cf = _ex.get('f')
                data = [_ex.get('ph_wrap'), _ex.get('ph_unwr'), _ex.get('grp_ms')][self.phase_mode]
                _cmag = _ex.get('mag')
        if pl<=self._mx<=W-pr and _cf is not None:
            if data is not None:
                is_grp=(self.phase_mode==2)
                cx=self._mx
                freq=float(self._xf(cx,pl,uw))
                _oi=np.searchsorted(_cf,freq)
                if _oi>0 and (_oi>=len(_cf) or _cf[_oi]-freq>freq-_cf[_oi-1]): _oi-=1
                idx=int(np.clip(_oi,0,len(data)-1))
                # 수평선 y: 실제 데이터값 위치
                if is_grp:
                    val_plot=float(data[idx])
                elif self.phase_mode==0:
                    mid=(self.ph_min+self.ph_max)/2
                    val_plot=float(data[idx])-360.0*round((float(data[idx])-mid)/360.0)
                else:
                    val_plot=float(data[idx])
                cy=int(pt+np.clip((self.ph_max-val_plot)/rng*dh,0,dh))
                p.setPen(QPen(_CUR,1,Qt.DashLine))
                p.drawLine(cx,pt,cx,H-pb)          # 수직선
                p.drawLine(pl,cy,W-pr,cy)           # 수평선
                fs=f'{freq/1000:.2f}kHz' if freq>=1000 else f'{freq:.0f}Hz'
                mag_str=''
                if _cmag is not None and len(_cmag)==len(_cf):
                    mag_str=f'{_cmag[idx]:+.1f} dB'
                if is_grp:
                    ph_str=f'  {data[idx]:.2f} ms'
                elif self.phase_mode==0:
                    ph_str=f'  {int(val_plot)}°'
                else:
                    ph_str=f'  {val_plot:+.1f}°'
                if _cap_col is not None:
                    _vcol = _cap_col
                elif isinstance(_fk, int) and _fk != -1 and _fk in self._tf_extra_phase:
                    _vcol = self._tf_extra_phase[_fk].get('color')
                else:
                    _vcol = self._live_color or T('green')
                draw_info_box(p,W,fs,f'{mag_str}{ph_str}', cx=cx, x_lo=pl, x_hi=W-pr, top=pt,
                              val_color=_vcol)
        self._fz_overlay(p, W, H)          # 박스줌 러버밴드
        _draw_tf_sel_border(self, p)
        p.end()

# ───────────────────────────────────────────
#  TF Magnitude + Coherence Canvas
# ───────────────────────────────────────────


class TFMagCanvas(_TFFreqZoomMixin, QWidget):
    PAD_L=40; PAD_R=15; PAD_T=16; PAD_B=28   # PAD_T: 맨위 라벨이 카드 상단에 안 잘리게
    _COH_COLOR=(77,163,255)   # γ² 코히런스 = 블루 채움 밴드(#4DA3FF). 기존 주황(255,107,53)은 초록 마그니튜드와 충돌
    _COH_BAND=0.5   # γ² 트레이스가 차지하는 플롯 높이 비율 (위=1.0, 아래=0) — Smaart식 디테일
    # 코히런스 블랭킹(연속 페이드) — 크기곡선을 신뢰도에 비례해 진하게/흐리게. [찾기: COH_BLANK]
    _COH_FADE_LO=0.20   # 이 이하 코히런스 = 가장 흐림(_COH_FADE_MIN 배율)
    _COH_FADE_HI=0.70   # 이 이상 코히런스 = 완전 불투명
    _COH_FADE_MIN=0.15  # 최저 알파 배율(저코히 구간도 완전히 사라지진 않게 — 연속성 유지)
    cursor_x_changed = pyqtSignal(int)
    cursor_left      = pyqtSignal()
    _cap_built       = pyqtSignal()
    def __init__(self):
        super().__init__()
        self.setMinimumSize(400,110); self.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Expanding)
        self.setMouseTracking(True); self.setAttribute(Qt.WA_OpaquePaintEvent,True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setToolTip(_tx('Frequency axis:\nWheel = zoom at cursor   ·   Drag = box zoom   ·   Shift+drag = pan\nDouble-click = reset to full range   ·   ⌘ +/− = step zoom'))
        self._fz_init()   # 주파수축 줌/팬 상태(f_lo/f_hi)
        self.freqs=None; self.mag=None; self.coh=None; self.phase=None
        self.db_min=-15.0; self.db_max=15.0
        self._db_lock=False   # dB축 수동 고정 (우클릭 메뉴로 설정, 더블클릭=자동 복귀)
        self._on_lock_change=None   # 락 변경 시 콜백(TF 창이 설정 저장에 연결)
        self.coh_blank=0.5
        self._coh_blank_on=True   # 코히런스 블랭킹(연속 페이드) ON — 신뢰도 낮은 구간 흐리게 [COH_BLANK]
        self._autofit_armed=False   # 측정 시작 후 첫 유효 데이터에 1회 자동 Y맞춤(아래로 깔리는 것 방지)
        self._mx=-1; self._peer_mx=-1; self._cache=None
        self._captures=[]
        self._cap_pix=None; self._cap_pix_key=None
        self._front_idx=None; self._live_on_top=False
        self._cap_building = False
        self._cap_img_pending = None; self._cap_key_pending = None
        self._cap_built.connect(self._apply_cap_built)
        self._tf_extra = {}  # {ch_idx: {'color', 'f', 'mag'}}
        self._tf_avg = None   # {'color','f','mag','coh'} — 라이브 멀티마이크 평균 오버레이
        self._live_color = None   # primary(1번) 곡선 사용자색. None=기본 T('green')
        self._hide_individual = False   # '평균만' — 개별 라이브 곡선 숨김(AVG는 계속 그림)
        # Reference/Delta 비교
        self._ref_f = None; self._ref_mag = None
        self._delta = False; self._abs_db = None
        self.DELTA_RANGE = 18.0
        self._front_extra = None  # None/-1=primary 맨앞, int=해당 pair idx 맨앞

    def set_front_curve(self, key):
        self._front_extra = key; self.update()

    def _draw_mag_line(self, p, W, H, f, mag, color, width):
        """단일 Mag 곡선(최종 dB값) 그리기 — front 강조 재드로우용."""
        if f is None or mag is None or len(f) < 2: return
        pl=self.PAD_L; pr=self.PAD_R; pt=self.PAD_T; pb=self.PAD_B
        dh=H-pt-pb; uw=W-pl-pr; ny=20000
        rng=self.db_max-self.db_min if self.db_max!=self.db_min else 1.0
        xs=self._fx(f,pl,uw).astype(float)
        ys=(pt+np.clip((self.db_max-mag)/rng*dh,0,dh)).astype(float)
        if len(ys)>=7:
            ys=np.convolve(np.pad(ys,3,mode='edge'),np.ones(7)/7,mode='valid').astype(float)
        _mp=max(int(uw),200)
        if len(xs)>_mp:
            ids=np.linspace(0,len(xs)-1,_mp,dtype=int); xs=xs[ids]; ys=ys[ids]
        p.setRenderHint(QPainter.Antialiasing,False)   # [TF_LIVE_CURVE_PERF] 라이브 강조 곡선도 AA off
        p.setPen(QPen(QColor(color),width)); p.setBrush(Qt.NoBrush)
        p.drawPath(_catmull_seg(xs, ys))

    def _draw_curve_coh(self, p, xs, ys, coh, color, width, base_alpha):
        """크기곡선 그리기 — 코히런스 블랭킹 ON + coh 있으면 신뢰도에 비례해 '연속 페이드'
        (고코히=불투명, 저코히=흐림). 아니면 기존 단일 catmull 실선. [COH_BLANK]
        성능: 알파를 11단계 양자화 → 같은 단계 연속 세그먼트만 폴리라인으로 배칭(펜 교체 최소).
        xs·ys·coh 는 이미 같은 인덱스로 다운샘플된 동일 길이 배열."""
        if not self._coh_blank_on or coh is None or len(coh)!=len(xs) or len(xs)<2:
            qc=QColor(color); qc.setAlpha(base_alpha)
            p.setPen(QPen(qc,width)); p.setBrush(Qt.NoBrush)
            p.drawPath(_catmull_seg(xs, ys)); return
        lo=self._COH_FADE_LO; hi=self._COH_FADE_HI; amin=self._COH_FADE_MIN
        fac=np.clip((np.asarray(coh,dtype=float)-lo)/max(hi-lo,1e-6),0.0,1.0)
        fac=amin+(1.0-amin)*fac                        # 알파 배율 amin..1.0
        seg=(fac[:-1]+fac[1:])*0.5                      # 세그먼트별(점 사이) 배율
        lvl=np.clip((seg*10.0+0.5).astype(int),0,10)    # 11단계 양자화
        p.setBrush(Qt.NoBrush); m=len(lvl); i=0
        # [PERF] xs/ys를 파이썬 list로 한 번만 변환 — 예전엔 세그먼트마다 xs[k]가 numpy 0-d
        # 스칼라 객체를 새로 만들어(프레임당 92회 실행 시 1.30ms) drawPolyline 자체보다 비쌌다.
        xl=np.asarray(xs,dtype=float).tolist(); yl=np.asarray(ys,dtype=float).tolist()
        lvll=lvl.tolist()
        while i<m:
            j=i
            while j+1<m and lvll[j+1]==lvll[i]: j+=1     # 같은 알파 단계 연속 세그먼트
            qc=QColor(color); qc.setAlpha(max(int(base_alpha*(lvll[i]/10.0)),0))
            p.setPen(QPen(qc,width))
            p.drawPolyline(QPolygonF([QPointF(a,b) for a,b in zip(xl[i:j+2], yl[i:j+2])]))
            i=j+1

    def set_reference(self, f, mag):
        self._ref_f  = np.asarray(f, dtype=np.float32)   if f   is not None else None
        self._ref_mag = np.asarray(mag, dtype=np.float32) if mag is not None else None
        self._cache=None; self._cap_pix=None; self.update()

    def set_delta_mode(self, on):
        on = bool(on)
        if on == self._delta: return
        self._delta = on
        if on:
            self._abs_db = (self.db_min, self.db_max)
            self.db_min = -self.DELTA_RANGE; self.db_max = self.DELTA_RANGE
        elif self._abs_db is not None:
            self.db_min, self.db_max = self._abs_db; self._abs_db = None
        self._cache=None; self._cap_pix=None; self.update()

    def set_tf_extra(self, ch_idx, color, f, mag, phase=None, coh=None):
        self._tf_extra[ch_idx] = {'color': color, 'f': f, 'mag': mag,
                                  'phase': phase, 'coh': coh}   # 커서 리드아웃 °/% 표시용(1번 카드와 동일)
        self.update()

    def clear_tf_extra(self, ch_idx):
        self._tf_extra.pop(ch_idx, None); self.update()

    def clear_all_tf_extra(self):
        self._tf_extra.clear(); self.update()

    def set_tf_average(self, color, f, mag, coh=None, width=2.8):
        self._tf_avg = {'color': color, 'f': f, 'mag': mag, 'coh': coh, 'w': width}; self.update()

    def clear_tf_average(self):
        if self._tf_avg is not None:
            self._tf_avg = None; self.update()

    def _apply_cap_built(self):
        img, key = self._cap_img_pending, self._cap_key_pending
        self._cap_img_pending = self._cap_key_pending = None
        if img is not None:
            self._cap_pix = QPixmap.fromImage(img)
            self._cap_pix_key = key
            self.update()

    def _trigger_cap_build(self, W, H, cap_key):
        if self._cap_building: return
        self._cap_building = True
        caps = [dict(c) for c in self._captures]
        front = self._front_idx
        threading.Thread(target=self._bg_cap_build,
                         args=(W, H, cap_key, caps, front),
                         daemon=True).start()

    def _bg_cap_build(self, W, H, cap_key, caps, front):
        try:
            img = self._build_cap_img(W, H, caps, front)
            self._cap_img_pending = img
            self._cap_key_pending = cap_key
            self._cap_built.emit()
        except Exception:
            pass
        finally:
            self._cap_building = False

    def _draw_cap_curve(self, p, cap, W, H, emph=False):
        # 단일 매그니튜드 캡쳐 곡선 — 베이스(dimmed)·front 오버레이(emph) 공용
        pl=self.PAD_L; pr=self.PAD_R; pt=self.PAD_T; pb=self.PAD_B
        dh=H-pt-pb; uw=W-pl-pr; ny=20000
        rng=max(self.db_max-self.db_min,1.0)
        max_pts=max(int(uw),200)  # 픽셀 1:1 — Python 루프 최소화
        def _vs(arr,k=7):
            if len(arr)<k: return arr
            return np.convolve(np.pad(arr,k//2,mode='edge'),np.ones(k)/k,mode='valid').astype(float)
        f_arr=cap['f']; m_arr=cap['mag']
        xs=self._fx(f_arr,pl,uw).astype(float)
        ys=(pt+np.clip((self.db_max-m_arr)/rng*dh,0,dh)).astype(float)
        ys_s=_vs(ys,7)
        if len(xs)>max_pts:
            _ids=np.linspace(0,len(xs)-1,max_pts,dtype=int)
            xs=xs[_ids]; ys_s=ys_s[_ids]
        poly=QPolygonF([QPointF(x,y) for x,y in zip(xs.tolist(),ys_s.tolist())])
        qc=QColor(cap['color'])
        if emph:
            p.setPen(QPen(qc,3.0))
        else:
            qc.setAlpha(140); p.setPen(QPen(qc,1.4))
        p.setBrush(Qt.NoBrush)
        p.drawPolyline(poly)

    def _build_cap_img(self, W, H, caps, front):
        # 베이스 = 보이는 캡쳐 전부 dimmed. front 강조는 paintEvent 오버레이.
        from PyQt5.QtGui import QImage
        img=QImage(W,H,QImage.Format_ARGB32_Premultiplied); img.fill(0)
        p=QPainter(img); p.setRenderHint(QPainter.Antialiasing,True)
        for cap in caps:
            if not cap.get('visible', True): continue
            self._draw_cap_curve(p, cap, W, H, emph=False)
        p.end()
        return img

    def _cap_base_key(self, n=None):
        if n is None: n=len(self._captures)
        return (self.width(), self.height(), self.db_max, self.db_min, n)

    def _append_cap_incr(self, cap):
        # 베이스 유효 시 새 캡쳐 1개만 dimmed로 얹기(O(1)). 무효면 다음 paint에서 전체 rebuild.
        if self._cap_pix is not None and self._cap_pix_key==self._cap_base_key(len(self._captures)-1) and cap.get('visible', True):
            p=QPainter(self._cap_pix); p.setRenderHint(QPainter.Antialiasing,True)
            self._draw_cap_curve(p, cap, self._cap_pix.width(), self._cap_pix.height(), emph=False)
            p.end()
            self._cap_pix_key=self._cap_base_key()   # 새 count 반영 → 재빌드 안 함
        else:
            self._cap_pix=None

    def _build_cap_pix(self, W, H):
        img = self._build_cap_img(W, H, list(self._captures), self._front_idx)
        self._cap_pix = QPixmap.fromImage(img)
        self._cap_pix_key = self._cap_base_key()

    def add_capture(self, label, color):
        if self.freqs is None or self.mag is None: return
        cap={
            'f': self.freqs.copy(), 'mag': self.mag.copy(),
            'coh': self.coh.copy() if self.coh is not None else None,
            'color': color, 'label': label
        }
        self._captures.append(cap)
        self._append_cap_incr(cap)
        self._last_cap_t=time.monotonic(); self.update()

    def add_capture_data(self, label, color, f, mag, coh=None):
        """외부 데이터(extra 카드 등)로 직접 캡쳐 추가."""
        if f is None or mag is None: return
        cap={
            'f': np.asarray(f, dtype=np.float32).copy(),
            'mag': np.asarray(mag, dtype=np.float32).copy(),
            'coh': np.asarray(coh, dtype=np.float32).copy() if coh is not None else None,
            'color': color, 'label': label
        }
        self._captures.append(cap)
        self._append_cap_incr(cap)
        self._last_cap_t=time.monotonic(); self.update()

    def recapture_live(self, idx):
        """primary 매그니튜드 캡쳐 idx 를 현재 라이브로 덮어쓰기 (색/이름 유지)."""
        if self.freqs is None or self.mag is None: return False
        if not (0 <= idx < len(self._captures)): return False
        c = self._captures[idx]
        c['f'] = self.freqs.copy(); c['mag'] = self.mag.copy()
        c['coh'] = self.coh.copy() if self.coh is not None else None
        self._cap_pix=None; self._last_cap_t=time.monotonic(); self.update()
        return True

    def recapture_data(self, idx, f, mag, coh=None):
        """extra 카드 매그니튜드 캡쳐 idx 를 외부 데이터로 덮어쓰기."""
        if f is None or mag is None or not (0 <= idx < len(self._captures)): return False
        c = self._captures[idx]
        c['f'] = np.asarray(f, dtype=np.float32).copy()
        c['mag'] = np.asarray(mag, dtype=np.float32).copy()
        c['coh'] = np.asarray(coh, dtype=np.float32).copy() if coh is not None else None
        self._cap_pix=None; self._last_cap_t=time.monotonic(); self.update()
        return True

    def remove_capture(self, idx):
        if 0 <= idx < len(self._captures):
            self._captures.pop(idx)
            if self._front_idx is not None:
                if self._front_idx==idx: self._front_idx=None
                elif self._front_idx>idx: self._front_idx-=1
            self._cap_pix=None; self._last_cap_t=time.monotonic(); self.update()

    def bring_to_front(self, idx):
        if 0 <= idx < len(self._captures):
            self._front_idx=idx; self._live_on_top=False
            self.update()   # front=paintEvent 오버레이 → 베이스 재빌드 불필요

    def arm_autofit(self):
        """다음 유효 데이터에 Y축 1회 자동맞춤(측정 시작 직후 호출). 매프레임 아님 → 점프 없음."""
        self._autofit_armed = True

    def set_data(self,f,m,coh=None,phase=None):
        self.freqs=f; self.mag=m; self.coh=coh; self.phase=phase
        # 측정 시작 후 첫 유효 데이터 1회만 자동 Y맞춤 → 더블클릭 없이 바로 화면에 들어옴
        if self._autofit_armed and m is not None and len(m) and np.any(np.isfinite(m)):
            self._autofit_armed = False
            self.fit_y()   # fit_y가 update() 호출
        else:
            self.update()

    def clear(self): self.freqs=self.mag=self.coh=self.phase=None; self._cache=None; self.update()
    def mouseMoveEvent(self,e):
        if self._fz_move(e): return          # 박스줌 러버밴드 / 팬 드래그 중
        x=e.x()
        if x!=self._mx:
            self._mx=x; self._peer_mx=-1; self.update()
            self._pending_x=x
            if not getattr(self,'_cursor_timer_active',False):
                self._cursor_timer_active=True
                QTimer.singleShot(16,self._emit_cursor)
    def _emit_cursor(self):
        self._cursor_timer_active=False
        self.cursor_x_changed.emit(self._pending_x)
    def leaveEvent(self,e):
        self._mx=-1; self.update(); self.cursor_left.emit()
    def set_peer_cursor(self,x):
        if x!=self._peer_mx: self._peer_mx=x; self.update()
    def clear_peer_cursor(self):
        if self._peer_mx!=-1: self._peer_mx=-1; self.update()
    def resizeEvent(self,e): self._cache=None; self.update()

    def fit_y(self):
        if self._db_lock: return   # 수동 고정 중 → 자동맞춤/자동확장 무시
        all_vals = []
        if self.mag is not None and len(self.mag) > 0:
            m = np.asarray(self.mag, dtype=float)
            if self._delta and self._ref_f is not None and self._ref_mag is not None:
                m = m - np.interp(self.freqs, self._ref_f, self._ref_mag)  # 델타 값에 맞춤
            if self.coh is not None and len(self.coh) == len(m):
                mask = np.asarray(self.coh, dtype=float) >= max(self.coh_blank, 0.3)
                m = m[mask] if np.any(mask) else m
            m = m[np.isfinite(m)]
            if len(m): all_vals.append(m)
        # extra 카드 곡선들도 포함 — 카드2만 분석 중이어도 더블클릭 Y맞춤 동작
        for ex in self._tf_extra.values():
            em = ex.get('mag')
            if em is None: continue
            em = np.asarray(em, dtype=float); em = em[np.isfinite(em)]
            if len(em): all_vals.append(em)
        if not all_vals: return
        combined = np.concatenate(all_vals)
        # 5/95 백분위 — 저코히어런스 노이즈(깊은 딥/날카로운 피크) 극단값 제외하되
        # 실제 롤오프는 보존. (2/98은 노이즈 outlier까지 잡아 -48~+27 같은 과도범위 발생)
        lo = float(np.percentile(combined, 5)); hi = float(np.percentile(combined, 95))
        pad = max((hi - lo) * 0.12, 3.0)
        dmin = lo - pad; dmax = hi + pad
        if dmax - dmin < 12.0:          # 납작한/저레벨 곡선에서 축 붕괴 방지 (최소 12dB 폭)
            mid = 0.5 * (dmin + dmax); dmin = mid - 6.0; dmax = mid + 6.0
        # 3dB 격자 스냅 + 넓은 안전한계. (기존 -36 하한이 저레벨 TF(예: 루프백 -54dB)를 잘라
        #  -33~-36 같은 붕괴 범위를 만들던 버그 → 하한 -120 으로 완화)
        self.db_min = max(int(np.floor(dmin / 3)) * 3, -120)
        self.db_max = min(int(np.ceil(dmax / 3)) * 3, 60)
        self._cache=None; self.update()

    def mouseDoubleClickEvent(self,e):
        self._fz_reset()                     # 주파수축 전대역 리셋
        self._db_lock=False                  # 더블클릭=자동 모드 복귀(고정 해제)
        self.fit_y(); self._notify_db_lock()

    def contextMenuEvent(self,e):
        _db_axis_context_menu(self, e.globalPos(), self.db_max, self.db_min, self._db_lock,
                              on_apply=self._db_apply, on_autofit=self._db_autofit,
                              on_toggle_lock=self._db_toggle,
                              extra_toggles=[('Coherence blanking', self._coh_blank_on,
                                              self._toggle_coh_blank)])

    def _toggle_coh_blank(self):
        """코히런스 블랭킹(연속 페이드) 켜기/끄기. [COH_BLANK] 상태변경 콜백으로 설정 저장."""
        self._coh_blank_on = not self._coh_blank_on
        self._cache = None; self.update()
        if callable(getattr(self, '_on_coh_blank_change', None)):
            self._on_coh_blank_change(self._coh_blank_on)

    def _notify_db_lock(self):
        if callable(self._on_lock_change):
            self._on_lock_change()

    def _db_apply(self, top, bot):
        self.db_max=float(top); self.db_min=float(bot); self._db_lock=True
        self._cache=None; self.update(); self._notify_db_lock()

    def _db_autofit(self):
        self._db_lock=False; self.fit_y(); self._notify_db_lock()

    def _db_toggle(self):
        self._db_lock=not self._db_lock
        if not self._db_lock: self.fit_y()       # 해제 → 자동맞춤 재개 (메뉴 'back to auto'와 일치)
        self._cache=None; self.update(); self._notify_db_lock()

    def enterEvent(self,e): self.setFocus(); super().enterEvent(e)
    def mousePressEvent(self,e):
        self.setFocus()
        if self._fz_press(e): return         # 박스줌/팬 시작
        super().mousePressEvent(e)
    def mouseReleaseEvent(self,e):
        if self._fz_release(e): return
        super().mouseReleaseEvent(e)

    def keyPressEvent(self,e):
        if self._fz_key(e): return           # Cmd± 줌 / Cmd0 리셋
        key=e.key()
        if key in (Qt.Key_Up, Qt.Key_Down):
            step=6.0 if key==Qt.Key_Up else -6.0
            db_span=self.db_max-self.db_min
            new_max=min(90.0, max(-90.0+db_span, self.db_max+step))
            new_min=new_max-db_span
            if new_min>=-90.0:
                self.db_max=new_max; self.db_min=new_min
                self._cache=None; self.update()
        else:
            super().keyPressEvent(e)

    def wheelEvent(self, e):
        if self._fz_wheel(e): return
        e.ignore()

    def _build_cache(self,W,H):
        from PyQt5.QtGui import QPixmap
        dpr=self.devicePixelRatio()
        px=QPixmap(int(W*dpr),int(H*dpr)); px.setDevicePixelRatio(dpr); px.fill(_tf_gutter())
        p=QPainter(px)
        p.setRenderHint(QPainter.Antialiasing, True); p.setRenderHint(QPainter.TextAntialiasing)
        _paint_tf_card(p, W, H)
        pl=self.PAD_L; pr=self.PAD_R; pt=self.PAD_T; pb=self.PAD_B
        dh=H-pt-pb; uw=W-pl-pr; ny=20000
        rng=self.db_max-self.db_min if self.db_max!=self.db_min else 1.0
        step_db=3
        p.setFont(_qfont(CF_AXIS))
        _lg=p.fontMetrics().height()+2; _last_ly=None   # 짧은 패널서 라벨 겹침 방지(그리드는 유지)
        for db in range(int(self.db_min)-step_db,int(self.db_max)+step_db+1,step_db):
            if db<self.db_min or db>self.db_max: continue
            y=int(pt+(self.db_max-db)/rng*dh)
            if not pt<=y<=H-pb: continue
            is0=(db==0)
            p.setPen(QPen(QColor(T('grid_ref')),1.5 if is0 else 0.7,Qt.SolidLine))
            p.drawLine(pl,y,W-pr,y)
            if _last_ly is None or abs(y-_last_ly)>=_lg:
                p.setPen(QColor(T('graph_txt'))); p.drawText(0,y-8,pl-2,16,Qt.AlignRight|Qt.AlignVCenter,f'{db:+d}'); _last_ly=y
        p.setFont(_qfont(CF_AXIS, True)); last_lx=-999
        draw_freq_minor_grid(p, pl, pr, uw, pt, pb, W, H, self.f_hi, self.f_lo)
        for f in self._fz_marks():
            if f<self.f_lo or f>self.f_hi: continue
            fx=freq_to_x(f,pl,uw,self.f_hi,self.f_lo)
            if not pl<=fx<=W-pr: continue
            p.setPen(QPen(QColor(T('grid')),1)); p.drawLine(int(fx),pt,int(fx),H-pb)
            if fx-last_lx<40: continue
            last_lx=fx
            txt=_fmt_freq_tick(f) if self.is_freq_zoomed() else (f'{int(f//1000)}k' if f>=1000 else str(int(f)))
            tw=p.fontMetrics().horizontalAdvance(txt)
            p.setPen(QColor(T('graph_txt'))); p.drawText(max(pl,min(int(fx-tw/2),W-pr-tw)),H-pb+18,txt)
        p.setFont(_qfont(CF_TF_TITLE, True)); p.setPen(QColor(_TF_CARD_COL['mag']))
        p.drawText(pl+4,pt+13,'Magnitude  +  Coherence  ▾')
        p.end(); self._cache=px

    def _draw_grid_lines(self, p, W, H):
        pl=self.PAD_L; pr=self.PAD_R; pt=self.PAD_T; pb=self.PAD_B
        dh=H-pt-pb; uw=W-pl-pr; ny=20000
        rng=self.db_max-self.db_min if self.db_max!=self.db_min else 1.0
        step_db=3
        for db in range(int(self.db_min)-step_db,int(self.db_max)+step_db+1,step_db):
            if db<self.db_min or db>self.db_max: continue
            y=int(pt+(self.db_max-db)/rng*dh)
            if not pt<=y<=H-pb: continue
            is0=(db==0)
            p.setPen(QPen(QColor(T('grid_ref')),1.5 if is0 else 0.7,Qt.SolidLine))
            p.drawLine(pl,y,W-pr,y)
        draw_freq_minor_grid(p, pl, pr, uw, pt, pb, W, H, self.f_hi, self.f_lo)
        for f in self._fz_marks():
            if f<self.f_lo or f>self.f_hi: continue
            fx=freq_to_x(f,pl,uw,self.f_hi,self.f_lo)
            if not pl<=fx<=W-pr: continue
            p.setPen(QPen(QColor(T('grid')),1)); p.drawLine(int(fx),pt,int(fx),H-pb)
        # 코히어런스 정적 기준선(1.0/0.5/0.0 점선)·우측 % 라벨 제거(2026-06-27) —
        # 정확한 γ² 값은 커서 리드아웃(`... 85%`)으로 읽고, 주황 곡선은 'γ²' 라벨로 식별.
        # (1.0/0.0은 +15모서리·+0dB선과 겹쳐 중복이었음. 그리드 깔끔하게.)

    def _draw_live_curve(self, p, W, H):
        pl=self.PAD_L; pr=self.PAD_R; pt=self.PAD_T; pb=self.PAD_B
        dh=H-pt-pb; uw=W-pl-pr; ny=20000
        rng=self.db_max-self.db_min if self.db_max!=self.db_min else 1.0
        refmode = self._delta and self._ref_f is not None and self._ref_mag is not None
        if self._delta and not refmode:
            return  # 델타 모드인데 기준 없음 — 절대값을 델타 축에 그리지 않음
        _hide = getattr(self, '_hide_individual', False)   # '평균만' — 개별 라이브 곡선 숨김(AVG는 아래서 항상 그림)
        # E 포커스: 포커스된 하나(라이브 카드 또는 캡쳐)만 밝게, 나머지 라이브 곡선은 흐리게.
        _capf = _focused_capture_visible(self)   # 캡쳐 포커스 → 모든 라이브 dim
        _fk = self._front_extra
        def _is_focus(key):   # key: None/-1=primary, int=extra. 이 라이브가 포커스 대상인가
            if _capf: return False
            if key is None or key == -1: return (_fk is None or _fk == -1)
            return _fk == key
        def _col(c, key):
            qc = QColor(c)
            if not _is_focus(key): qc.setAlpha(140)   # 비포커스 흐림 (너무 어둡지 않게)
            return qc
        def _vis_smooth(arr, k=7):
            if len(arr) < k: return arr
            kernel = np.ones(k, dtype=float) / k
            return np.convolve(np.pad(arr, k//2, mode='edge'), kernel, mode='valid').astype(float)
        if self.freqs is not None and self.mag is not None and len(self.freqs)>=2 and not _hide:
            f_arr=self.freqs
            m_arr=self.mag - np.interp(f_arr, self._ref_f, self._ref_mag) if refmode else self.mag
            xs=self._fx(f_arr,pl,uw).astype(float)
            ys_m=(pt+np.clip((self.db_max-m_arr)/rng*dh,0,dh)).astype(float)
            max_pts=max(int(uw),200)
            ys_ms=_vis_smooth(ys_m,7)
            if len(xs)>max_pts:
                _ids=np.linspace(0,len(xs)-1,max_pts,dtype=int)
                xs_d=xs[_ids]; ys_ms=ys_ms[_ids]
            else:
                xs_d=xs
            # [TF_LIVE_CURVE_PERF] 라이브 곡선은 AA off — 1/48 등 미세 스무딩 시 곡선이 뾰족해져
            # AA 래스터 비용이 폭증(측정 52→22ms/프레임)해 오디오 콜백을 굶겨 핑크 끊김·전체 버벅임.
            # 포인트 수·스플라인은 그대로 유지(1/48 디테일 보존). float 좌표라 계단현상 미미. 뒤에서 AA 복원.
            p.setRenderHint(QPainter.Antialiasing,False)
            _coh_d=None                                    # [COH_BLANK] 곡선 좌표와 같은 인덱스로 다운샘플
            if self.coh is not None and len(self.coh)==len(f_arr):
                _coh_d=self.coh[_ids] if len(xs)>max_pts else self.coh
            _base_a=255 if _is_focus(None) else 140
            self._draw_curve_coh(p, xs_d, ys_ms, _coh_d, self._live_color or T('green'), 2.5, _base_a)
            if self.coh is not None and len(self.coh)==len(f_arr):
                cr,cg,cb_=self._COH_COLOR
                coh_h=dh*self._COH_BAND
                ys_c_raw=(pt+np.clip((1.0-self.coh)*coh_h,0,coh_h)).astype(float)
                ys_cs=_vis_smooth(ys_c_raw,3)   # 디테일 유지 (과도한 평탄화 방지)
                if len(xs)>max_pts: ys_cs=ys_cs[_ids]
                _coha = 230 if _is_focus(None) else 140   # primary 비포커스면 코히어런스도 흐리게
                base_y = pt + coh_h                         # γ²=0 라인 = 채움 밴드 바닥
                curve = _catmull_seg(xs_d, ys_cs)
                fillp = QPainterPath(curve)                 # 곡선→바닥으로 닫아 반투명 면 채움(신뢰도 영역)
                fillp.lineTo(float(xs_d[-1]), base_y); fillp.lineTo(float(xs_d[0]), base_y); fillp.closeSubpath()
                p.setPen(Qt.NoPen); p.setBrush(QColor(cr,cg,cb_, int(_coha*0.28)))
                p.drawPath(fillp)
                p.setPen(QPen(QColor(cr,cg,cb_,_coha),1.4)); p.setBrush(Qt.NoBrush)
                p.drawPath(curve)
                p.setFont(_qfont(CF_ANNO, True)); p.setPen(QColor(cr,cg,cb_,200))
                p.drawText(pl+4,int(pt+coh_h+5),'γ²')
        # 추가 채널 magnitude 곡선
        if self._tf_extra and not _hide:
            _ex_max_pts=max(int(uw),200)
            for _exk, ex in self._tf_extra.items():
                ex_f=ex.get('f'); ex_m=ex.get('mag')
                if ex_f is None or ex_m is None or len(ex_f)<2: continue
                if refmode:
                    ex_m = ex_m - np.interp(ex_f, self._ref_f, self._ref_mag)
                ex_xs=self._fx(ex_f,pl,uw).astype(float)
                ex_ys=(pt+np.clip((self.db_max-ex_m)/rng*dh,0,dh)).astype(float)
                ex_ys_s=_vis_smooth(ex_ys,7)
                if len(ex_xs)>_ex_max_pts:
                    _ei=np.linspace(0,len(ex_xs)-1,_ex_max_pts,dtype=int)
                    ex_xs_d=ex_xs[_ei]; ex_ys_s=ex_ys_s[_ei]
                else:
                    ex_xs_d=ex_xs
                p.setRenderHint(QPainter.Antialiasing,False)   # [TF_LIVE_CURVE_PERF]
                _ex_coh=ex.get('coh'); _ex_coh_d=None          # [COH_BLANK] 코히런스 페이드
                if _ex_coh is not None and len(_ex_coh)==len(ex_f):
                    _ex_coh_d=_ex_coh[_ei] if len(ex_xs)>_ex_max_pts else _ex_coh
                self._draw_curve_coh(p, ex_xs_d, ex_ys_s, _ex_coh_d, ex['color'], 2.0,
                                     255 if _is_focus(_exk) else 140)
        # front(포커스) 라이브 곡선 맨 앞 굵게 재드로우 — 캡쳐 포커스 시엔 생략
        if self._tf_extra and not _capf and not _hide:
            fk=self._front_extra
            if fk is None or fk==-1:
                if self.freqs is not None and self.mag is not None:
                    fm=self.mag - np.interp(self.freqs,self._ref_f,self._ref_mag) if refmode else self.mag
                    self._draw_mag_line(p,W,H, self.freqs, fm, self._live_color or T('green'), 3.4)
            elif fk in self._tf_extra:
                ex=self._tf_extra[fk]; exf=ex.get('f'); exm=ex.get('mag')
                if exf is not None and exm is not None:
                    if refmode: exm=exm-np.interp(exf,self._ref_f,self._ref_mag)
                    self._draw_mag_line(p,W,H, exf, exm, ex.get('color'), 3.4)
        # 멀티마이크 평균(AVG) — 항상 맨 위(front 재드로우 이후) 굵은 실선 오버레이
        if self._tf_avg is not None:
            a = self._tf_avg
            af = a.get('f'); am = a.get('mag')
            if af is not None and am is not None and len(af) >= 2:
                if refmode:
                    am = am - np.interp(af, self._ref_f, self._ref_mag)
                a_xs = self._fx(af, pl, uw).astype(float)
                a_ys = (pt + np.clip((self.db_max - am) / rng * dh, 0, dh)).astype(float)
                a_ys = _vis_smooth(a_ys, 7)
                _ex_max_pts_a = max(int(uw), 200)
                if len(a_xs) > _ex_max_pts_a:
                    _ai = np.linspace(0, len(a_xs) - 1, _ex_max_pts_a, dtype=int)
                    a_xs = a_xs[_ai]; a_ys = a_ys[_ai]
                # AA는 켜지 않는다 — 다른 라이브 곡선과 동일 정책. 이 오버레이만 AA를 되켜고 있어
                # drawPath가 8배 비쌌다(600점 곡선 실측 1.31ms→10.43ms). [TF_LIVE_CURVE_PERF]
                p.setPen(QPen(QColor(a['color']), a.get('w', 2.8))); p.setBrush(Qt.NoBrush)
                p.drawPath(_catmull_seg(a_xs, a_ys))
        p.setRenderHint(QPainter.Antialiasing, True)   # 라이브 곡선 후 AA 복원(격자/라벨/커서 선명) [TF_LIVE_CURVE_PERF]

    def paintEvent(self,ev):
        W=self.width(); H=self.height()
        if self._cache is None or self._cache.size()!=self.size():
            self._build_cache(W,H)
        p=QPainter(self); p.drawPixmap(0,0,self._cache)

        # E 포커스: 캡쳐 선택 시 라이브(흐림) 먼저 → 포커스 캡쳐(밝음) 위. 라이브 포커스 시 반대.
        _cap_focus = _focused_capture_visible(self)
        def _draw_caps():
            if not (self._captures and not self._delta): return  # 델타 모드 절대값 캡쳐 숨김
            _cap_key=self._cap_base_key()
            if self._cap_pix is None or self._cap_pix_key!=_cap_key:
                self._trigger_cap_build(W, H, _cap_key)
            if self._cap_pix is not None:
                p.drawPixmap(0,0,self._cap_pix)
            fi=self._front_idx
            if fi is not None and 0<=fi<len(self._captures) and self._captures[fi].get('visible',True):
                self._draw_cap_curve(p, self._captures[fi], W, H, emph=True)   # 선택 캡쳐 강조(재빌드 없이)
        p.save(); p.setClipRect(QRectF(self.PAD_L, self.PAD_T, W-self.PAD_L-self.PAD_R, H-self.PAD_T-self.PAD_B))
        if _cap_focus:
            self._draw_live_curve(p,W,H); _draw_caps()
        else:
            _draw_caps(); self._draw_live_curve(p,W,H)
        p.restore()                                    # 확대 시 범위 밖 곡선이 왼쪽 여백으로 삐져나가지 않게 클립

        self._draw_grid_lines(p, W, H)

        pl=self.PAD_L; pr=self.PAD_R; pt=self.PAD_T; pb=self.PAD_B; uw=W-pl-pr; ny=20000
        dh=H-pt-pb; rng=max(self.db_max-self.db_min,1.0)
        # 무신호(측정 곡선 없음) → 브랜드 엠프티 스테이트 안내
        if self.mag is None and not self._tf_extra:
            _draw_idle_hint(p, pl, pt, uw, dh, text='Play a signal to start measuring')
        _CUR  = QColor(255,220,50,210)
        _PEER = QColor(255,220,50,100)
        # 피어 커서: 수직선 + 수평선 (자기 데이터로 y 계산)
        if pl<=self._peer_mx<=W-pr:
            p.setPen(QPen(_PEER,1,Qt.DashLine))
            p.drawLine(self._peer_mx,pt,self._peer_mx,H-pb)
            if self.freqs is not None and self.mag is not None:
                pfreq=float(self._xf(self._peer_mx,pl,uw))
                _pi=np.searchsorted(self.freqs,pfreq)
                if _pi>0 and (_pi>=len(self.freqs) or self.freqs[_pi]-pfreq>pfreq-self.freqs[_pi-1]): _pi-=1
                pidx=int(np.clip(_pi,0,len(self.mag)-1))
                pcy=int(pt+np.clip((self.db_max-float(self.mag[pidx]))/rng*dh,0,dh))
                p.drawLine(pl,pcy,W-pr,pcy)
        # 자체 커서: 십자 + info box
        # 커서 데이터 우선순위: 포커스된 캡쳐 → 선택(front) 라이브카드 → primary → 아무 extra
        _fk = self._front_extra
        _cap_col = None
        if _focused_capture_visible(self):   # 캡쳐를 클릭해 포커스 → 그 캡쳐 값을 읽음
            _cap = self._captures[self._front_idx]
            _cf = _cap.get('f'); _cm = _cap.get('mag'); _cp = None; _cc = _cap.get('coh')
            _cap_col = _cap.get('color')
        elif isinstance(_fk, int) and _fk != -1 and _fk in self._tf_extra:
            _ex = self._tf_extra[_fk]
            _cf = _ex.get('f'); _cm = _ex.get('mag'); _cp = _ex.get('phase'); _cc = _ex.get('coh')
        else:
            _cf = self.freqs; _cm = self.mag; _cp = self.phase; _cc = self.coh
            if (_cf is None or _cm is None) and self._tf_extra:
                _ex = next(iter(self._tf_extra.values()))
                _cf = _ex.get('f'); _cm = _ex.get('mag'); _cp = _ex.get('phase'); _cc = _ex.get('coh')
        if pl<=self._mx<=W-pr and _cf is not None and _cm is not None:
            cx=self._mx
            freq=float(self._xf(cx,pl,uw))
            _oi=np.searchsorted(_cf,freq)
            if _oi>0 and (_oi>=len(_cf) or _cf[_oi]-freq>freq-_cf[_oi-1]): _oi-=1
            idx=int(np.clip(_oi,0,len(_cm)-1))
            # 수평선 y: 실제 magnitude 값 위치
            cy=int(pt+np.clip((self.db_max-float(_cm[idx]))/rng*dh,0,dh))
            p.setPen(QPen(_CUR,1,Qt.DashLine))
            p.drawLine(cx,pt,cx,H-pb)          # 수직선
            p.drawLine(pl,cy,W-pr,cy)           # 수평선
            fs=f'{freq/1000:.2f}kHz' if freq>=1000 else f'{freq:.0f}Hz'
            mag_str=f'{_cm[idx]:+.1f} dB'
            ph_str=''
            if _cp is not None and len(_cp)==len(_cf):
                ph_str=f'  {int(round(float(_cp[idx])))}°'
            coh_str=''
            if _cc is not None and len(_cc)==len(_cf):
                coh_str=f'  {_cc[idx]*100:.0f}%'
            if _cap_col is not None:
                _vcol = _cap_col
            elif isinstance(_fk, int) and _fk != -1 and _fk in self._tf_extra:
                _vcol = self._tf_extra[_fk].get('color')
            else:
                _vcol = self._live_color or T('green')
            draw_info_box(p,W,fs,f'{mag_str}{ph_str}{coh_str}', cx=cx, x_lo=pl, x_hi=W-pr, top=pt,
                          val_color=_vcol)
        self._fz_overlay(p, W, H)          # 박스줌 러버밴드
        _draw_tf_sel_border(self, p)
        p.end()

# ───────────────────────────────────────────
#  장치 선택 섹션 아이콘 (단색 QPainter)
# ───────────────────────────────────────────


class TFIRCanvas(QWidget):
    """Live IR — Lin / ETC / Log 3-mode 표시."""
    PAD_L = 40; PAD_R = 15; PAD_T = 16; PAD_B = 28   # PAD_T/B: 맨위·맨아래 라벨(±1.0)+미터축이 카드 둥근 프레임에 안 겹치게(Mag과 동일 28)
    _cap_built = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setMinimumSize(400, 80)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMouseTracking(True); self.setAttribute(Qt.WA_OpaquePaintEvent, True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.t_ms = None; self.etc_db = None; self.h_raw = None
        self.peak_ms = 0.0
        self._delay_ms = 0.0   # delay_spin 설정값 — 주황 대시 라인 위치
        self.t_min = -10.0; self.t_max = 10.0   # 보정 IR: 0ms 가운데 고정
        self.db_min = -60.0; self.db_max = 0.0
        self.ir_mode = 0   # 0=Lin  1=ETC  2=Log
        self._mx = -1
        self._cache = None
        self._center_locked = False  # Find/delay 설정 후 자동 재조정 방지
        self._captures = []
        self._cap_pix = None; self._cap_pix_key = None
        self._front_idx = None; self._live_on_top = False
        self._cap_building = False
        self._cap_img_pending = None; self._cap_key_pending = None
        self._cap_built.connect(self._apply_cap_built)
        self._tf_extra = {}       # {ch_idx: {'color','t','h'}} — 카드별 라이브 IR
        self._tf_avg = None       # {'color','t','h','etc_db'} — 라이브 멀티마이크 평균 오버레이
        self._live_color = None   # primary(1번) 곡선 사용자색. None=기본 T('green')
        self._hide_individual = False   # '평균만' — 개별 라이브 IR 숨김(AVG는 계속 그림)
        self._front_extra = None  # None/-1=primary 맨앞, int=해당 pair idx 맨앞

    def _apply_cap_built(self):
        img, key = self._cap_img_pending, self._cap_key_pending
        self._cap_img_pending = self._cap_key_pending = None
        if img is not None:
            self._cap_pix = QPixmap.fromImage(img)
            self._cap_pix_key = key
            self.update()

    def _trigger_cap_build(self, W, H, cap_key):
        if self._cap_building: return
        self._cap_building = True
        caps = [dict(c) for c in self._captures]
        front = self._front_idx
        threading.Thread(target=self._bg_cap_build,
                         args=(W, H, cap_key, caps, front),
                         daemon=True).start()

    def _bg_cap_build(self, W, H, cap_key, caps, front):
        try:
            img = self._build_cap_img(W, H, caps, front)
            self._cap_img_pending = img
            self._cap_key_pending = cap_key
            self._cap_built.emit()
        except Exception:
            pass
        finally:
            self._cap_building = False

    def _draw_cap_curve(self, p, cap, W, H, emph=False):
        # 단일 IR 캡쳐 곡선 — 베이스(dimmed)·front 오버레이(emph) 공용
        pl=self.PAD_L; pr=self.PAD_R; pt=self.PAD_T; pb=self.PAD_B
        dh=H-pt-pb; uw=W-pl-pr
        t_range=max(self.t_max-self.t_min,1.0)
        MAX_PTS = max(int(uw), 200)  # 화면 픽셀 수 기준 — Python 루프 최소화
        t_arr=cap['t']; h_raw=cap['h']
        if t_arr is None or h_raw is None: return  # extra 카드 빈 IR 캡쳐 스킵
        xs_r=ys_r=None
        if self.ir_mode==0:
            peak_lin=max(float(np.max(np.abs(h_raw))),1e-10)
            h_norm=h_raw/peak_lin
            mask=(t_arr>=self.t_min)&(t_arr<=self.t_max)
            if np.any(mask):
                t_v=t_arr[mask]; h_v=h_norm[mask]
                if len(t_v)>MAX_PTS:
                    ids=np.linspace(0,len(t_v)-1,MAX_PTS,dtype=int); t_v=t_v[ids]; h_v=h_v[ids]
                xs_r=(pl+(t_v-self.t_min)/t_range*uw).astype(float)
                ys_r=(pt+np.clip((1.0-h_v)/2.0*dh,0,dh)).astype(float)
        else:
            db_arr=cap['etc_db']
            if self.ir_mode==2 and h_raw is not None:
                pk=max(float(np.max(np.abs(h_raw))),1e-10)
                db_arr=20*np.log10(np.maximum(np.abs(h_raw)/pk,1e-10))
            if db_arr is not None:
                db_range=max(self.db_max-self.db_min,1.0)
                mask=(t_arr>=self.t_min)&(t_arr<=self.t_max)
                if np.any(mask):
                    t_v=t_arr[mask]; db_v=db_arr[mask]
                    if len(t_v)>MAX_PTS:
                        ids=np.linspace(0,len(t_v)-1,MAX_PTS,dtype=int); t_v=t_v[ids]; db_v=db_v[ids]
                    xs_r=(pl+(t_v-self.t_min)/t_range*uw).astype(float)
                    ys_r=(pt+np.clip((self.db_max-db_v)/db_range*dh,0,dh)).astype(float)
        if xs_r is not None and len(xs_r)>=2:
            poly=QPolygonF([QPointF(x,y) for x,y in zip(xs_r.tolist(),ys_r.tolist())])
            qc=QColor(cap['color'])
            if emph:
                p.setPen(QPen(qc,3.0))
            else:
                qc.setAlpha(140); p.setPen(QPen(qc,1.4))
            p.setBrush(Qt.NoBrush)
            p.drawPolyline(poly)

    def _build_cap_img(self, W, H, caps, front):
        # 베이스 = 보이는 캡쳐 전부 dimmed. front 강조는 paintEvent 오버레이.
        from PyQt5.QtGui import QImage
        img=QImage(W,H,QImage.Format_ARGB32_Premultiplied); img.fill(0)
        p=QPainter(img); p.setRenderHint(QPainter.Antialiasing,True)
        for cap in caps:
            if not cap.get('visible', True): continue
            self._draw_cap_curve(p, cap, W, H, emph=False)
        p.end()
        return img

    def _cap_base_key(self, n=None):
        if n is None: n=len(self._captures)
        return (self.width(), self.height(), self.db_max, self.db_min,
                round(self.t_min,1), round(self.t_max,1), self.ir_mode, n)

    def _append_cap_incr(self, cap):
        # 베이스 유효 시 새 캡쳐 1개만 dimmed로 얹기(O(1)). 무효면 다음 paint에서 전체 rebuild.
        if self._cap_pix is not None and self._cap_pix_key==self._cap_base_key(len(self._captures)-1) and cap.get('visible', True):
            p=QPainter(self._cap_pix); p.setRenderHint(QPainter.Antialiasing,True)
            self._draw_cap_curve(p, cap, self._cap_pix.width(), self._cap_pix.height(), emph=False)
            p.end()
            self._cap_pix_key=self._cap_base_key()   # 새 count 반영 → 재빌드 안 함
        else:
            self._cap_pix=None

    def _build_cap_pix(self, W, H):
        img = self._build_cap_img(W, H, list(self._captures), self._front_idx)
        self._cap_pix = QPixmap.fromImage(img)
        self._cap_pix_key = self._cap_base_key()

    def add_capture(self, label, color, delay=0.0):
        if self.t_ms is None or self.h_raw is None: return
        cap={
            't': self.t_ms.copy(), 'h': self.h_raw.copy(),
            'etc_db': self.etc_db.copy() if self.etc_db is not None else None,
            'color': color, 'label': label, 'delay': delay
        }
        self._captures.append(cap)
        self._append_cap_incr(cap)
        self._last_cap_t=time.monotonic(); self.update()

    def add_capture_empty(self, label, color, delay=0.0):
        """extra 카드는 IR 데이터가 없음 — _tf_captures 인덱스 정합용 빈 캡쳐."""
        cap={'t': None, 'h': None, 'etc_db': None, 'color': color, 'label': label, 'delay': delay}
        self._captures.append(cap)
        self._append_cap_incr(cap)   # 빈 IR은 그려지는 게 없어 베이스 그대로 유지
        self.update()

    def add_capture_data(self, label, color, t, h, etc_db=None, delay=0.0):
        """extra 카드(멀티카드)의 live IR 캡쳐 — 카드별 _tf_extra 의 t/h 사용."""
        if t is None or h is None:
            self.add_capture_empty(label, color, delay); return
        h = np.asarray(h, dtype=np.float32)
        if etc_db is None:
            etc = _hilbert_env(h); pk = max(float(np.max(etc)), 1e-10)
            etc_db = (20 * np.log10(np.maximum(etc / pk, 1e-10))).astype(np.float32)
        cap={
            't': np.asarray(t, dtype=np.float32).copy(), 'h': h.copy(),
            'etc_db': np.asarray(etc_db, dtype=np.float32).copy(),
            'color': color, 'label': label, 'delay': delay
        }
        self._captures.append(cap)
        self._append_cap_incr(cap)
        self._last_cap_t=time.monotonic(); self.update()

    def recapture_live(self, idx, delay=0.0):
        """primary IR 캡쳐 idx 를 현재 라이브로 덮어쓰기 (색/이름 유지)."""
        if self.t_ms is None or self.h_raw is None: return False
        if not (0 <= idx < len(self._captures)): return False
        c = self._captures[idx]
        c['t'] = self.t_ms.copy(); c['h'] = self.h_raw.copy()
        c['etc_db'] = self.etc_db.copy() if self.etc_db is not None else None
        c['delay'] = delay
        self._cap_pix=None; self._last_cap_t=time.monotonic(); self.update()
        return True

    def recapture_data(self, idx, t, h, etc_db=None, delay=0.0):
        """extra 카드 IR 캡쳐 idx 를 외부 데이터로 덮어쓰기 (데이터 없으면 빈 캡쳐)."""
        if not (0 <= idx < len(self._captures)): return False
        c = self._captures[idx]
        if t is None or h is None:
            c['t'] = None; c['h'] = None; c['etc_db'] = None; c['delay'] = delay
        else:
            h = np.asarray(h, dtype=np.float32)
            if etc_db is None:
                etc = _hilbert_env(h); pk = max(float(np.max(etc)), 1e-10)
                etc_db = (20 * np.log10(np.maximum(etc / pk, 1e-10))).astype(np.float32)
            c['t'] = np.asarray(t, dtype=np.float32).copy(); c['h'] = h.copy()
            c['etc_db'] = np.asarray(etc_db, dtype=np.float32).copy(); c['delay'] = delay
        self._cap_pix=None; self._last_cap_t=time.monotonic(); self.update()
        return True

    def remove_capture(self, idx):
        if 0 <= idx < len(self._captures):
            self._captures.pop(idx)
            if self._front_idx is not None:
                if self._front_idx==idx: self._front_idx=None
                elif self._front_idx>idx: self._front_idx-=1
            self._cap_pix=None; self._last_cap_t=time.monotonic(); self.update()

    def bring_to_front(self, idx):
        if 0 <= idx < len(self._captures):
            self._front_idx=idx; self._live_on_top=False
            self.update()   # front=paintEvent 오버레이 → 베이스 재빌드 불필요

    def set_tf_extra(self, ch_idx, color, t, h, delay=0.0):
        # ETC 포락선은 한 번만 계산해 저장 (paint마다 hilbert 재계산 방지)
        etc = _hilbert_env(h); pk = max(float(np.max(etc)), 1e-10)
        etc_db = (20 * np.log10(np.maximum(etc / pk, 1e-10))).astype(np.float32)
        # delay: 카드 딜레이값 — paintEvent 에서 카드색 마커 위치로 사용
        self._tf_extra[ch_idx] = {'color': color, 't': t, 'h': h, 'etc_db': etc_db, 'delay': delay}
        self.update()

    def clear_tf_extra(self, ch_idx):
        self._tf_extra.pop(ch_idx, None); self.update()

    def clear_all_tf_extra(self):
        self._tf_extra.clear(); self.update()

    def set_tf_average(self, color, t, h, width=2.2):
        # etc_db 는 set_tf_extra 와 동일하게 계산 — Hilbert 포락선 + 피크정규화(0dB).
        # (raw |h| dB 로 하면 ETC/Log 모드서 영점교차마다 -200 으로 튀어 개별곡선과 불일치)
        if h is not None:
            etc = _hilbert_env(h); pk = max(float(np.max(etc)), 1e-10)
            etc_db = (20 * np.log10(np.maximum(etc / pk, 1e-10))).astype(np.float32)
        else:
            etc_db = None
        self._tf_avg = {'color': color, 't': t, 'h': h, 'etc_db': etc_db, 'w': width}; self.update()

    def clear_tf_average(self):
        if getattr(self, '_tf_avg', None) is not None:
            self._tf_avg = None; self.update()

    def set_front_curve(self, key):
        self._front_extra = key; self.update()

    def _draw_ir_curve(self, p, W, H, t_arr, h_raw, color, width, etc_db=None, dim=False):
        """단일 IR 곡선(line)을 현재 ir_mode에 맞춰 그림 — extra/front 공용."""
        if t_arr is None or h_raw is None or len(t_arr) < 2: return
        pl=self.PAD_L; pr=self.PAD_R; pt=self.PAD_T; pb=self.PAD_B
        dh=H-pt-pb; uw=W-pl-pr; t_range=max(self.t_max-self.t_min,1.0)
        mask=(t_arr>=self.t_min)&(t_arr<=self.t_max)
        if not np.any(mask): return
        t_v=t_arr[mask]
        if self.ir_mode==0:
            pk=max(float(np.max(np.abs(h_raw))),1e-10)
            v=(h_raw/pk)[mask]
            ys=pt+np.clip((1.0-v)/2.0*dh,0,dh)
        else:
            db_range=max(self.db_max-self.db_min,1.0)
            if self.ir_mode==1:
                db = etc_db if etc_db is not None else _hilbert_env(h_raw)
                if etc_db is None:
                    pk=max(float(np.max(db)),1e-10); db=20*np.log10(np.maximum(db/pk,1e-10))
            else:
                pk=max(float(np.max(np.abs(h_raw))),1e-10)
                db=20*np.log10(np.maximum(np.abs(h_raw)/pk,1e-10))
            v=np.asarray(db)[mask]
            ys=pt+np.clip((self.db_max-v)/db_range*dh,0,dh)
        _mp=max(int(uw),200)
        if len(t_v)>_mp:
            ids=np.linspace(0,len(t_v)-1,_mp,dtype=int); t_v=t_v[ids]; ys=ys[ids]
        xs=(pl+(t_v-self.t_min)/t_range*uw).astype(float); ys=ys.astype(float)
        p.setRenderHint(QPainter.Antialiasing,False)   # 라이브 곡선 AA OFF — Retina 전체화면 AA 래스터화 10배 비쌈
        _qc=QColor(color)
        if dim: _qc.setAlpha(140)
        p.setPen(QPen(_qc,width)); p.setBrush(Qt.NoBrush)
        p.drawPolyline(QPolygonF([QPointF(x,y) for x,y in zip(xs.tolist(),ys.tolist())]))

    def set_data(self, t_ms, h):
        self.t_ms = t_ms
        self.h_raw = h.copy()
        etc = _hilbert_env(h)
        peak_val = max(float(np.max(etc)), 1e-10)
        pk_idx = int(np.argmax(etc))
        self.peak_ms = float(t_ms[pk_idx])
        self.etc_db = 20 * np.log10(np.maximum(etc / peak_val, 1e-10))
        # 그리드 캐시는 뷰(t_min/t_max/모드)에만 의존 → 데이터 갱신 시 무효화 불필요.
        # (매 프레임 Retina 픽스맵 재할당+그리드+텍스트 재생성 방지 → IR 페인트 시간↓)
        self.update()

    def set_mode(self, idx): self.ir_mode = idx; self._cache = None; self._cap_pix = None; self.update()

    def clear(self):
        self.t_ms = self.etc_db = self.h_raw = None
        self._center_locked = False; self._cache = None; self.update()

    def mouseMoveEvent(self, e): self._mx = e.x(); self.update()
    def leaveEvent(self, e): self._mx = -1; self.update()
    def resizeEvent(self, ev): self._cache = None; self.update()
    def enterEvent(self, e): self.setFocus(); super().enterEvent(e)  # 호버 시 자동 포커스

    def wheelEvent(self, e):
        e.ignore()  # 마우스 휠 비활성화

    def mousePressEvent(self, e): self.setFocus(); super().mousePressEvent(e)

    def keyPressEvent(self, e):
        key = e.key(); mod = e.modifiers()
        if key in (Qt.Key_Up, Qt.Key_Down):
            if self.ir_mode == 0:
                # Linear 모드: Up=시간 뒤로, Down=시간 앞으로 (Left/Right와 동일 축)
                span = max(self.t_max - self.t_min, 1.0); d = span * 0.06
                if key == Qt.Key_Up:
                    self.t_min = self.t_min - d   # 보정 IR: 음수 시간(0 좌측) 허용
                else:
                    self.t_min = self.t_min + d
                self.t_max = self.t_min + span
                self._cache = None; self.update()
            else:
                # ETC/Log 모드: dB 축 위아래 이동 (범위 +90 ~ -90)
                step = 6.0 if key == Qt.Key_Up else -6.0
                db_span = self.db_max - self.db_min
                new_max = min(90.0, max(-90.0 + db_span, self.db_max + step))
                new_min = new_max - db_span
                if new_min >= -90.0:
                    self.db_max = new_max; self.db_min = new_min
                    self._cache = None; self.update()
        elif key == Qt.Key_Left:
            span = max(self.t_max - self.t_min, 1.0); d = span * 0.06
            self.t_min = self.t_min - d
            self.t_max = self.t_min + span
            self._cache = None; self.update()
        elif key == Qt.Key_Right:
            span = max(self.t_max - self.t_min, 1.0); d = span * 0.06
            self.t_min = self.t_min + d
            self.t_max = self.t_min + span
            self._cache = None; self.update()
        elif key in (Qt.Key_Equal, Qt.Key_Plus) and mod & Qt.ControlModifier:
            span = max(5.0, (self.t_max - self.t_min) * 0.88)
            mid = (self.t_max + self.t_min) / 2
            self.t_min = mid - span / 2; self.t_max = self.t_min + span
            self._cache = None; self.update()
        elif key == Qt.Key_Minus and mod & Qt.ControlModifier:
            span = max(5.0, (self.t_max - self.t_min) * 1.12)
            mid = (self.t_max + self.t_min) / 2
            self.t_min = mid - span / 2; self.t_max = self.t_min + span
            self._cache = None; self.update()
        else:
            super().keyPressEvent(e)

    def _build_cache(self, W, H):
        from PyQt5.QtGui import QPixmap
        dpr=self.devicePixelRatio()
        pix = QPixmap(int(W*dpr),int(H*dpr)); pix.setDevicePixelRatio(dpr); pix.fill(_tf_gutter())
        p = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing, True); p.setRenderHint(QPainter.TextAntialiasing)
        _paint_tf_card(p, W, H)
        pl = self.PAD_L; pr = self.PAD_R; pt = self.PAD_T; pb = self.PAD_B
        dh = H - pt - pb; uw = W - pl - pr
        t_range = max(self.t_max - self.t_min, 1.0)

        # ── 시간(수직) 그리드 공통 ──────────────────
        step_ms = (2 if t_range <= 20 else 5 if t_range <= 50 else
                   10 if t_range <= 100 else 20 if t_range <= 200 else 50)
        t = int(self.t_min / step_ms) * step_ms
        while t <= self.t_max + step_ms:
            x = int(pl + (t - self.t_min) / t_range * uw)
            if pl <= x <= W - pr:
                p.setPen(QPen(QColor(T('grid')), 1)); p.drawLine(x, pt, x, H - pb)
                p.setPen(QColor(T('graph_txt'))); p.setFont(_qfont(CF_AXIS))
                lbl = fmt_delay(t, 0, compact=True); tw = p.fontMetrics().horizontalAdvance(lbl)
                if pl <= x - tw // 2 and x + tw // 2 <= W - pr:   # 양끝 라벨은 y라벨·카드모서리와 겹쳐 생략
                    p.drawText(x - tw // 2, H - pb + 14, lbl)
            t += step_ms

        if self.ir_mode == 0:  # ── Lin ───────────────────────────────────
            p.setFont(_qfont(CF_AXIS))
            _lg=p.fontMetrics().height()+2; _last_ly=None   # 짧은 패널서 라벨 겹침 방지(그리드는 유지)
            for amp in [1.0, 0.5, 0.0, -0.5, -1.0]:
                y = int(pt + (1.0 - amp) / 2.0 * dh)
                if not pt <= y <= H - pb: continue
                is0 = (amp == 0.0)
                p.setPen(QPen(QColor(T('grid_ref')), 1.5 if is0 else 0.7,
                             Qt.SolidLine))
                p.drawLine(pl, y, W - pr, y)
                if _last_ly is None or abs(y-_last_ly)>=_lg:
                    p.setPen(QColor(T('graph_txt'))); p.drawText(0,y-8,pl-2,16,Qt.AlignRight|Qt.AlignVCenter,f'{amp:+.1f}'); _last_ly=y
            p.setFont(_qfont(CF_TF_TITLE, True)); p.setPen(QColor(_TF_CARD_COL['ir']))
            p.drawText(pl + 4, pt + 15, 'Live IR  (Linear)  ▾')
        else:  # ── ETC (1) or Log (2) ─────────────────────────────────────
            db_range = max(self.db_max - self.db_min, 1.0)
            p.setFont(_qfont(CF_AXIS))
            _lg=p.fontMetrics().height()+2; _last_ly=None   # 짧은 패널서 라벨 겹침 방지(그리드는 유지)
            for db in range(int(self.db_min), int(self.db_max) + 1, 10):
                if not self.db_min <= db <= self.db_max: continue
                y = int(pt + (self.db_max - db) / db_range * dh)
                if not pt <= y <= H - pb: continue
                is0 = (db == 0)
                p.setPen(QPen(QColor(T('grid_ref')), 1.3 if is0 else 0.6,
                             Qt.SolidLine))
                p.drawLine(pl, y, W - pr, y)
                if _last_ly is None or abs(y-_last_ly)>=_lg:
                    p.setPen(QColor(T('graph_txt'))); p.drawText(0,y-8,pl-2,16,Qt.AlignRight|Qt.AlignVCenter,f'{db:+d}'); _last_ly=y
            lbl_text = ('Live IR  (ETC)' if self.ir_mode == 1 else 'Live IR  (Log)') + '  ▾'
            p.setFont(_qfont(CF_TF_TITLE, True)); p.setPen(QColor(_TF_CARD_COL['ir']))
            p.drawText(pl + 4, pt + 15, lbl_text)
        p.end()
        self._cache = pix

    def _draw_grid_lines(self, p, W, H):
        pl = self.PAD_L; pr = self.PAD_R; pt = self.PAD_T; pb = self.PAD_B
        dh = H - pt - pb; uw = W - pl - pr
        t_range = max(self.t_max - self.t_min, 1.0)
        step_ms = (2 if t_range <= 20 else 5 if t_range <= 50 else
                   10 if t_range <= 100 else 20 if t_range <= 200 else 50)
        t = int(self.t_min / step_ms) * step_ms
        while t <= self.t_max + step_ms:
            x = int(pl + (t - self.t_min) / t_range * uw)
            if pl <= x <= W - pr:
                p.setPen(QPen(QColor(T('grid')), 1)); p.drawLine(x, pt, x, H - pb)
            t += step_ms
        if self.ir_mode == 0:
            for amp in [1.0, 0.5, 0.0, -0.5, -1.0]:
                y = int(pt + (1.0 - amp) / 2.0 * dh)
                if not pt <= y <= H - pb: continue
                is0 = (amp == 0.0)
                p.setPen(QPen(QColor(T('grid_ref')), 1.5 if is0 else 0.7,
                             Qt.SolidLine))
                p.drawLine(pl, y, W - pr, y)
        else:
            db_range = max(self.db_max - self.db_min, 1.0)
            for db in range(int(self.db_min), int(self.db_max) + 1, 10):
                if not self.db_min <= db <= self.db_max: continue
                y = int(pt + (self.db_max - db) / db_range * dh)
                if not pt <= y <= H - pb: continue
                is0 = (db == 0)
                p.setPen(QPen(QColor(T('grid_ref')), 1.3 if is0 else 0.6,
                             Qt.SolidLine))
                p.drawLine(pl, y, W - pr, y)

    def _draw_live_curve(self, p, W, H):
        pl = self.PAD_L; pr = self.PAD_R; pt = self.PAD_T; pb = self.PAD_B
        dh = H - pt - pb; uw = W - pl - pr
        t_range = max(self.t_max - self.t_min, 1.0)
        p.setRenderHint(QPainter.Antialiasing, False)   # 라이브 곡선 AA OFF — Retina 전체화면 AA 래스터화 10배 비쌈
        _hide = getattr(self, '_hide_individual', False)   # '평균만' — 개별 라이브 IR 숨김(AVG는 아래서 항상 그림)
        # E 포커스: 포커스된 하나만 밝게, 나머지 라이브는 흐리게(alpha 140)
        _capf = _focused_capture_visible(self)
        _fk = self._front_extra
        def _is_focus(key):
            if _capf: return False
            if key is None or key == -1: return (_fk is None or _fk == -1)
            return _fk == key
        _pdim = not _is_focus(None)        # primary 흐림 여부
        _LA = 140 if _pdim else 230        # primary 라이브 라인 알파
        _gc = self._live_color or T('green')   # primary(1번) IR 색 — 사용자 지정 우선
        if self.ir_mode == 0:
            if self.t_ms is not None and self.h_raw is not None and len(self.t_ms) >= 2 and not _hide:
                peak_lin = max(float(np.max(np.abs(self.h_raw))), 1e-10)
                t_arr = self.t_ms; h_norm = self.h_raw / peak_lin
                mask = (t_arr >= self.t_min) & (t_arr <= self.t_max)
                if np.any(mask):
                    t_v = t_arr[mask]; h_v = h_norm[mask]
                    _mp = max(int(uw), 200)
                    if len(t_v) > _mp:
                        ids = np.linspace(0, len(t_v) - 1, _mp, dtype=int)
                        t_v = t_v[ids]; h_v = h_v[ids]
                    xs = (pl + (t_v - self.t_min) / t_range * uw).astype(float)
                    ys = (pt + np.clip((1.0 - h_v) / 2.0 * dh, 0, dh)).astype(float)
                    lc = QColor(_gc); lc.setAlpha(_LA)
                    p.setPen(QPen(lc, 2.0)); p.setBrush(Qt.NoBrush)
                    p.drawPolyline(QPolygonF([QPointF(x,y) for x,y in zip(xs.tolist(),ys.tolist())]))
        else:
            db_range = max(self.db_max - self.db_min, 1.0)
            if self.t_ms is not None and len(self.t_ms) >= 2 and not _hide:
                if self.ir_mode == 1:
                    db_arr = self.etc_db
                else:
                    if self.h_raw is not None:
                        pk = max(float(np.max(np.abs(self.h_raw))), 1e-10)
                        db_arr = 20 * np.log10(np.maximum(np.abs(self.h_raw) / pk, 1e-10))
                    else:
                        db_arr = None
                if db_arr is not None:
                    t_arr = self.t_ms
                    mask = (t_arr >= self.t_min) & (t_arr <= self.t_max)
                    if np.any(mask):
                        t_v = t_arr[mask]; db_v = db_arr[mask]
                        _mp2 = max(int(uw), 200)
                        if len(t_v) > _mp2:
                            ids = np.linspace(0, len(t_v) - 1, _mp2, dtype=int)
                            t_v = t_v[ids]; db_v = db_v[ids]
                        xs = (pl + (t_v - self.t_min) / t_range * uw).astype(float)
                        ys = (pt + np.clip((self.db_max - db_v) / db_range * dh, 0, dh)).astype(float)
                        _poly_pts = [QPointF(x,y) for x,y in zip(xs.tolist(),ys.tolist())]
                        if self.ir_mode == 1:  # ETC — fill + line
                            fp = QPainterPath()
                            fp.moveTo(xs[0], float(H - pb)); fp.lineTo(xs[0], ys[0])
                            for pt2 in _poly_pts[1:]: fp.lineTo(pt2.x(), pt2.y())
                            fp.lineTo(xs[-1], float(H - pb)); fp.closeSubpath()
                            g = QLinearGradient(0, pt, 0, H - pb)
                            ac = QColor(_gc); ac.setAlpha(20 if _pdim else 55)
                            ac2 = QColor(_gc); ac2.setAlpha(2 if _pdim else 5)
                            g.setColorAt(0, ac); g.setColorAt(1, ac2)
                            p.setBrush(QBrush(g)); p.setPen(Qt.NoPen); p.drawPath(fp)
                            lc = QColor(_gc); lc.setAlpha(_LA)
                            p.setPen(QPen(lc, 1.6)); p.setBrush(Qt.NoBrush)
                            p.drawPolyline(QPolygonF(_poly_pts))
                        else:  # Log — line only
                            lc = QColor(_gc); lc.setAlpha(_LA)
                            p.setPen(QPen(lc, 1.2)); p.setBrush(Qt.NoBrush)
                            p.drawPolyline(QPolygonF(_poly_pts))

        # 카드별 추가 IR 곡선 + front(포커스) 맨앞 굵게 재드로우. 비포커스는 흐리게(alpha 140).
        if self._tf_extra and not _hide:
            for key, ex in self._tf_extra.items():
                if key == self._front_extra and not _capf: continue   # front는 아래서 굵게(라이브 포커스 시)
                self._draw_ir_curve(p, W, H, ex.get('t'), ex.get('h'),
                                    ex.get('color'), 1.6, ex.get('etc_db'), dim=not _is_focus(key))
            if not _capf:   # 캡쳐 포커스 시엔 라이브 front 굵게 재드로우 생략
                fk = self._front_extra
                if fk is None or fk == -1:
                    self._draw_ir_curve(p, W, H, self.t_ms, self.h_raw, _gc, 2.8, self.etc_db)
                elif fk in self._tf_extra:
                    ex = self._tf_extra[fk]
                    self._draw_ir_curve(p, W, H, ex.get('t'), ex.get('h'),
                                        ex.get('color'), 2.8, ex.get('etc_db'))
        # 멀티마이크 평균(AVG) — 개별 위 굵은 실선 오버레이 (extra IR 드로우 로직 재사용)
        if self._tf_avg is not None:
            a = self._tf_avg
            self._draw_ir_curve(p, W, H, a.get('t'), a.get('h'),
                                a.get('color'), a.get('w', 2.2), a.get('etc_db'))

    def paintEvent(self, ev):
        W = self.width(); H = self.height()
        if self._cache is None or self._cache.size() != self.size():
            self._build_cache(W, H)
        p = QPainter(self); p.drawPixmap(0, 0, self._cache)

        # E 포커스: 캡쳐 선택 시 라이브(흐림) 먼저 → 포커스 캡쳐(밝음) 위. 라이브 포커스 시 반대.
        _cap_focus = _focused_capture_visible(self)
        def _draw_caps():
            if not self._captures: return
            _cap_key=self._cap_base_key()
            if self._cap_pix is None or self._cap_pix_key!=_cap_key:
                self._trigger_cap_build(W, H, _cap_key)
            if self._cap_pix is not None:
                p.drawPixmap(0,0,self._cap_pix)
            fi=self._front_idx
            if fi is not None and 0<=fi<len(self._captures) and self._captures[fi].get('visible',True):
                self._draw_cap_curve(p, self._captures[fi], W, H, emph=True)   # 선택 캡쳐 강조(재빌드 없이)
        if _cap_focus:
            self._draw_live_curve(p, W, H); _draw_caps()
        else:
            _draw_caps(); self._draw_live_curve(p, W, H)

        self._draw_grid_lines(p, W, H)

        pl = self.PAD_L; pr = self.PAD_R; pt = self.PAD_T; pb = self.PAD_B; uw = W - pl - pr
        _tr = max(self.t_max - self.t_min, 1.0)
        # 카드별 딜레이 마커 — 각 카드 색 세로 점선. 임펄스가 실제 도착(=딜레이) 위치에
        # 그려지므로 마커가 그 카드 임펄스를 가리킨다. front 카드는 굵게 + 값 라벨.
        _fk = self._front_extra
        # 캡처가 front 면(_front_idx 설정 + 라이브가 위가 아님) 라벨은 그 캡처에, 아니면 라이브 카드에.
        _cap_front_idx = self._front_idx if (not self._live_on_top) else None
        _markers = []   # (delay_ms, color, is_front, is_capture)
        # 라이브 카드 마커 — 세로 점선 + front 값 라벨
        if self.t_ms is not None:   # primary 활성(정지 시 숨김)
            _markers.append((self._delay_ms, self._live_color or T('green'),
                             _cap_front_idx is None and (_fk is None or _fk == -1), False))
        for _key, _ex in self._tf_extra.items():
            _markers.append((_ex.get('delay', 0.0), _ex.get('color'),
                             _cap_front_idx is None and _key == _fk, False))
        # 캡처 마커 — 점선 없이 딜레이 값만 표기 (각 캡처색). 사용자 요청: 캡처는 점선 제거.
        for _ci, _cap in enumerate(self._captures):
            if not _cap.get('visible', True): continue
            if _cap.get('t') is None: continue   # 빈 IR 캡처 → 마커 없음
            _markers.append((_cap.get('delay', 0.0), _cap.get('color'),
                             _ci == _cap_front_idx, True))
        for _dms, _dcol, _is_front, _is_cap in _markers:
            if not (self.t_min <= _dms <= self.t_max): continue
            if _dms == 0.0 and not _is_cap: continue   # 라이브 0딜레이 마커 생략
            _dx = int(pl + (_dms - self.t_min) / _tr * uw)
            _c = QColor(_dcol)
            if not _is_cap:
                # 라이브: 세로 점선 (front 굵게)
                p.setPen(QPen(_c, 2.2 if _is_front else 1.2, Qt.DashLine))
                p.drawLine(_dx, pt, _dx, H - pb)
            # 값 라벨 — 선택(front)된 하나만 하단축에 표시. 캡처 클릭 → 그 캡처 값만 뜸(겹침 없음).
            if _is_front:
                _lbl = f'▷ {fmt_delay(_dms)}'
                p.setFont(_qfont(CF_MODE, True))
                _fm = p.fontMetrics(); _tw2 = _fm.horizontalAdvance(_lbl)
                _lx = _dx + 5
                if _lx + _tw2 > W - pr: _lx = _dx - 5 - _tw2   # 오른쪽 끝이면 왼쪽으로
                _ty = H - pb + 14   # 시간축 숫자와 같은 줄
                # 불투명 배경 박스 — 그 자리 축 숫자를 덮어 글자 겹침 방지
                p.setPen(Qt.NoPen); p.setBrush(QColor(T('bg')))
                p.drawRect(_lx - 3, _ty - _fm.ascent() - 1, _tw2 + 6, _fm.height() + 2)
                p.setPen(_c); p.drawText(_lx, _ty, _lbl)
        # 커서 우선순위: 포커스된 캡쳐 → 선택(front) 라이브카드 → primary → 아무 extra
        _fk = self._front_extra
        _cap_col = None
        if _focused_capture_visible(self):
            _cap = self._captures[self._front_idx]
            _ct = _cap.get('t'); _ch = _cap.get('h'); _cetc = _cap.get('etc_db')
            _cap_col = _cap.get('color')
        elif isinstance(_fk, int) and _fk != -1 and _fk in self._tf_extra:
            _ex = self._tf_extra[_fk]
            _ct = _ex.get('t'); _ch = _ex.get('h'); _cetc = _ex.get('etc_db')
        else:
            _ct = self.t_ms; _ch = self.h_raw; _cetc = self.etc_db
            if (_ct is None or _ch is None) and self._tf_extra:
                _ex = next(iter(self._tf_extra.values()))
                _ct = _ex.get('t'); _ch = _ex.get('h'); _cetc = _ex.get('etc_db')
        if pl <= self._mx <= W - pr and _ct is not None:
            cx = self._mx; t_range = max(self.t_max - self.t_min, 1.0)
            p.setPen(QPen(QColor(0, 229, 255, 60), 1, Qt.DashLine))
            p.drawLine(cx, pt, cx, H - pb)
            t_cur = self.t_min + (cx - pl) / uw * t_range
            t_arr = _ct
            if _cap_col is not None:
                _vcol = _cap_col
            elif isinstance(_fk, int) and _fk != -1 and _fk in self._tf_extra:
                _vcol = self._tf_extra[_fk].get('color')
            else:
                _vcol = self._live_color or T('green')
            if self.ir_mode == 0 and _ch is not None:
                pk = max(float(np.max(np.abs(_ch))), 1e-10)
                idx = int(np.clip(np.argmin(np.abs(t_arr - t_cur)), 0, len(_ch) - 1))
                draw_info_box(p, W, fmt_delay(t_cur, 1), f'{_ch[idx]/pk:+.3f}', cx=cx, x_lo=pl, x_hi=W-pr, top=pt, val_color=_vcol)
            elif self.ir_mode == 1 and _cetc is not None:
                idx = int(np.clip(np.argmin(np.abs(t_arr - t_cur)), 0, len(_cetc) - 1))
                draw_info_box(p, W, fmt_delay(t_cur, 1), f'{_cetc[idx]:+.1f} dB', cx=cx, x_lo=pl, x_hi=W-pr, top=pt, val_color=_vcol)
            elif self.ir_mode == 2 and _ch is not None:
                pk = max(float(np.max(np.abs(_ch))), 1e-10)
                idx = int(np.clip(np.argmin(np.abs(t_arr - t_cur)), 0, len(_ch) - 1))
                db_val = 20 * math.log10(max(abs(float(_ch[idx])) / pk, 1e-10))
                draw_info_box(p, W, fmt_delay(t_cur, 1), f'{db_val:+.1f} dB', cx=cx, x_lo=pl, x_hi=W-pr, top=pt, val_color=_vcol)
        _draw_tf_sel_border(self, p)
        p.end()


# ───────────────────────────────────────────
#  Internal Loopback 전용 Duplex 스트림 스레드
# ───────────────────────────────────────────
