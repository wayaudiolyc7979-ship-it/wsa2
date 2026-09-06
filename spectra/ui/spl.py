"""SPL 서브시스템 — LEQ/SPL 미터/알람/쇼모드 윈도우 + 패널·엔진·크롬 헬퍼.

v2.0 분해: wayaudo2.py에서 이동(동작 0 변경). 상호의존 클러스터라 통째로 이관.
"""
import sys, math, time, ctypes
from collections import deque
import numpy as np
from PyQt5.QtGui import (QBrush, QColor, QCursor, QFont, QLinearGradient, QPainter,
                         QPainterPath, QPen, QPixmap, QPolygonF, QRadialGradient)
from PyQt5.QtCore import (Qt, QMutex, QMutexLocker, QPointF, QRectF, QTimer,
                          QEasingCurve, QVariantAnimation, pyqtSignal)
from PyQt5.QtWidgets import (QDialog, QFrame, QGraphicsOpacityEffect, QGridLayout,
                             QGroupBox, QHBoxLayout, QLabel, QMenu, QPushButton, QSizePolicy,
                             QVBoxLayout, QWidget)
from spectra.core.config import T, is_dark, _save_settings
from spectra.core.i18n import _tx
from spectra.core.logging_diag import _alog, _diag
from spectra.ui.tokens import FONT_FAMILY, FONT_NUM, FONT_SANS
from spectra.ui.colors import _spectra_grad_brush, _vbar_gradient, bar_top
from spectra.ui.icons import _icon
from spectra.ui.widgets import (RoundComboBox, _GradTimeBar, _N2Button, _PinBtn,
                                _SettingsBtn, _apply_dark_titlebar)
from spectra.ui.dialogs import SplAlarmConfigDialog, SplLayoutDialog


class _RateEst:
    """실제 push 레이트(Hz) 추정기.

    [정확성] LEQ 창 길이를 상수 50Hz로 잡아왔는데 실제는 블록 크기·샘플레이트에 따라
    ~47Hz(48k)·~43Hz(44.1k)다. 50으로 나누면 창이 실제보다 **6~16% 길게** 잡혀
    LEQ가 그만큼 과적분되고 진행바도 같은 비율로 어긋났다.
    푸시 간격을 EMA로 추정해 창 길이를 실제 레이트로 계산한다(초기값은 공칭값)."""
    __slots__ = ('_nominal', '_rate', '_last_t')

    def __init__(self, nominal):
        self._nominal = float(nominal); self._rate = float(nominal); self._last_t = None

    def tick(self, now):
        if self._last_t is not None:
            dt = now - self._last_t
            if 0.002 < dt < 0.5:                     # 비정상 간격(첫 푸시·스톨)은 무시
                self._rate += (1.0 / dt - self._rate) * 0.02   # 느린 EMA(≈50샘플 시정수)
        self._last_t = now

    @property
    def hz(self):
        return self._rate if 5.0 < self._rate < 500.0 else self._nominal

    def reset(self):
        self._rate = self._nominal; self._last_t = None

    def window_n(self, secs):
        """secs초에 해당하는 표본 수(실측 레이트 기준)."""
        return max(1, int(round(secs * self.hz)))


def _db2e(db):
    """dB → 에너지. LEQ 버퍼는 dB가 아니라 '에너지'로 담는다.

    [PERF] 예전엔 dB를 담고 매 틱(초당 5회, 창 두 개) 창 전체에 10**(arr/10)을 돌렸다.
    3시간 창(54만 표본)이면 틱당 6.64ms = 초당 34ms를 GUI에서 태웠다(실측).
    적재 시점에 한 번만 지수화하면(초당 ~50회 스칼라) 읽기는 mean() 한 번으로 끝난다."""
    return 10.0 ** (db / 10.0)


def _e2leq(arr):
    """에너지 배열 → LEQ(dB)."""
    return float(10.0 * np.log10(max(float(np.mean(arr)), 1e-12)))


class _RingBuf:
    """고정 용량 float 링버퍼 — LEQ 적분용.

    [장시간] 예전엔 deque(maxlen=50*3600*3)에 파이썬 float를 담고 매 틱(200ms)마다
    `np.array(list(buf)[-n:])`로 읽었다. list(deque)가 **버퍼 전체(최대 54만 개)** 를
    먼저 복사하므로, 1분 LEQ를 보려고 3천 개만 필요해도 3시간 구동 시 한 번에 2.7ms가 들고
    미터+알람 두 창이면 GUI 스레드를 초당 ~24ms 잡아먹었다(실측).
    ndarray 링버퍼로 두면 최근 n개를 O(n) 슬라이스 복사로 바로 꺼낼 수 있어 버퍼가 아무리
    길어도 창 길이에만 비례한다."""
    __slots__ = ('_a', '_cap', '_n', '_i')

    def __init__(self, cap):
        self._cap = max(1, int(cap))
        self._a = np.empty(self._cap, dtype=np.float64)
        self._n = 0; self._i = 0

    def __len__(self): return self._n
    def __bool__(self): return self._n > 0

    def clear(self): self._n = 0; self._i = 0

    def append(self, v):
        self._a[self._i] = v
        self._i += 1
        if self._i >= self._cap: self._i = 0
        if self._n < self._cap: self._n += 1

    def last(self, k):
        """최근 k개를 ndarray로 (복사 1회, O(k)). k가 보유량보다 크면 보유량만큼."""
        k = min(int(k), self._n)
        if k <= 0: return np.empty(0, dtype=np.float64)
        start = self._i - k
        if start >= 0:
            return self._a[start:self._i].copy()
        head = -start                                  # 뒤쪽(랩어라운드) 구간 길이
        out = np.empty(k, dtype=np.float64)
        out[:head] = self._a[self._cap - head:]
        out[head:] = self._a[:self._i]
        return out


def _draw_reload_arrow(p, cx, cy, r, col, lw=2.0):
    """리셋/리로드용 둥근 화살표 — 거의 꽉 찬 원(상단 작은 틈)+깔끔한 삼각 화살촉. 공용."""
    p.setRenderHint(QPainter.Antialiasing, True)
    pen = QPen(col, lw); pen.setCapStyle(Qt.RoundCap)
    p.setPen(pen); p.setBrush(Qt.NoBrush)
    p.drawArc(QRectF(cx - r, cy - r, 2 * r, 2 * r), 110 * 16, 320 * 16)
    # 화살촉 — 원호 시작점(상단 좌측 틈)에 삼각형 (반지름 비례)
    k = r / 8.0
    a = math.radians(110)
    ax, ay = cx + r * math.cos(a), cy - r * math.sin(a)
    p.setPen(Qt.NoPen); p.setBrush(col)
    p.drawPolygon(QPolygonF([
        QPointF(ax - 2.5 * k, ay - 1.5 * k),
        QPointF(ax + 2.5 * k, ay - 2.5 * k),
        QPointF(ax + 0.5 * k, ay + 3.0 * k)]))


def _txn_style(color_key):
    """트랜스포트 버튼 틴트 스타일 — 은은한 컬러 워시 펄(브랜드)."""
    c = QColor(T(color_key)); r, g, b = c.red(), c.green(), c.blue()
    return (f'QPushButton{{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,'
            f'stop:0 rgba({r},{g},{b},46), stop:1 rgba({r},{g},{b},20));'
            f'color:{T(color_key)};border:1px solid rgba({r},{g},{b},150);'
            f'font-weight:700;padding:3px 12px;border-radius:7px;}}'
            f'QPushButton:hover{{border-color:rgba({r},{g},{b},210);}}'
            f'QPushButton:disabled{{background:{T("panel")};color:{T("text_dim")};border-color:{T("border")};}}')


def _apply_txn(btn, playing):
    """모든 트랜스포트(Start/Play/Stop) 통일 — 시작/재생=로고블루 틴트, 정지=레드 틴트 + 아이콘."""
    if isinstance(btn, _N2Button):   # N2 툴바 Start — 아이콘/색만 전환(테두리리스 유지)
        btn.set_running(playing); return
    if playing:
        btn.setStyleSheet(_txn_style('red'));    btn.setIcon(_icon('stop', 14, color=T('red')))
    else:
        btn.setStyleSheet(_txn_style('accent')); btn.setIcon(_icon('play', 14, color=T('accent')))




def _apply_on_top(win, on):
    """always-on-top 적용 — macOS는 NSWindow.setLevel로 (창 재생성 없음=깜빡임 없음).
    on=True→NSFloatingWindowLevel(3) / False→NSNormalWindowLevel(0).
    적용 성공 시 True. macOS 아니면 False(호출측이 Qt 플래그로 폴백)."""
    if sys.platform != 'darwin':
        return False
    try:
        import ctypes
        objc = ctypes.cdll.LoadLibrary('/usr/lib/libobjc.A.dylib')
        objc.sel_registerName.restype = ctypes.c_void_p
        objc.sel_registerName.argtypes = [ctypes.c_char_p]
        def sel(n): return objc.sel_registerName(n.encode())
        def msg(restype, obj, name, *args):
            f = objc.objc_msgSend; f.restype = restype
            f.argtypes = [ctypes.c_void_p, ctypes.c_void_p] + [type(a) for a in args]
            return f(obj, sel(name), *args)
        ns_view = ctypes.c_void_p(int(win.winId()))
        ns_window = msg(ctypes.c_void_p, ns_view, 'window')
        if not ns_window:
            return False
        msg(None, ns_window, 'setLevel:', ctypes.c_long(3 if on else 0))
        return True
    except Exception as e:
        try: _alog.debug(f'setLevel(on_top) 실패: {e}')
        except Exception: pass
        return False


def _glance_chrome_update(win):
    """글랜스 창(SPL 미터/알람) — 마우스가 창 밖이면 타이틀바를 부드럽게 접어 '카드만',
    창 안이면 부드럽게 펼침. 200ms 타이머에서 호출(전역 커서로 판정, 자식 enter/leave 무관).
    들어오면 즉시 펼치고, 나가면 0.35s 지난 뒤에만 접음(짧은 스침엔 안 깜빡임)."""
    from PyQt5.QtGui import QCursor
    try:
        inside = win.geometry().contains(QCursor.pos())
    except Exception:
        inside = True
    now = time.monotonic()
    if inside:
        win._chrome_outside_since = None
        _glance_set_chrome(win, True)
    else:
        ts = getattr(win, '_chrome_outside_since', None)
        if ts is None:
            win._chrome_outside_since = now
        elif now - ts >= 0.35:
            _glance_set_chrome(win, False)


def _glance_set_chrome(win, show):
    """타이틀바를 부드럽게 페이드+높이접기(0↔원래높이)로 표시/숨김.
    숨기면 카드가 빈틈없이 창을 채움(겹침·빈띠 둘 다 없음), 펼치면 타이틀바가 위에 자리.
    카드가 약간 늘고 줄지만 그게 표준(겹침/빈띠를 둘 다 피하는 유일한 방식). 부드럽게."""
    tb = getattr(win, '_dark_titlebar', None)
    if tb is None:
        return
    target = 1.0 if show else 0.0
    if getattr(win, '_chrome_target', None) == target:
        return
    win._chrome_target = target

    full_h = getattr(tb, '_full_h', None)
    if full_h is None:
        full_h = tb.height() or 34
        tb._full_h = full_h
        tb.setMinimumHeight(0)   # 0까지 접히게(원래 setFixedHeight=34라 min=max였음)

    eff = getattr(tb, '_opacity_eff', None)
    if eff is None:
        from PyQt5.QtWidgets import QGraphicsOpacityEffect
        eff = QGraphicsOpacityEffect(tb); eff.setOpacity(1.0)
        tb.setGraphicsEffect(eff); tb._opacity_eff = eff

    anim = getattr(win, '_chrome_anim', None)
    if anim is None:
        from PyQt5.QtCore import QVariantAnimation, QEasingCurve
        anim = QVariantAnimation(win); anim.setDuration(280)
        anim.setEasingCurve(QEasingCurve.InOutCubic)

        def _on_val(v):
            try:
                t = float(v)
                tb.setFixedHeight(max(0, int(round(tb._full_h * t))))
                tb._opacity_eff.setOpacity(t)
            except Exception:
                pass
        anim.valueChanged.connect(_on_val)

        def _on_fin():
            if getattr(win, '_chrome_target', 1.0) <= 0.0:
                tb.setVisible(False)   # 완전히 접힌 뒤 숨겨 잔상/클릭 방지
        anim.finished.connect(_on_fin)
        win._chrome_anim = anim

    if show:
        tb.setVisible(True)
    anim.stop()
    anim.setStartValue(float(eff.opacity()))
    anim.setEndValue(target)
    anim.start()


# UI 위젯 — v2.0 분해: spectra/ui/widgets.py 로 이동, re-import
from spectra.ui.widgets import _SettingsBtn, _PinBtn
class _ReloadBtn(QPushButton):
    """둥근 화살표 리셋 버튼(글리프 A) — 위젯 크기에 맞춰 직접 그림.
    hover 시 배경칠 없이 아이콘 색만 소프트블루로 밝아짐(요청 2026-06-28)."""
    def __init__(self, color=None):
        super().__init__()
        self._col = color
        self._hover = False
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet('QPushButton{border:none;background:transparent;}')

    def enterEvent(self, e):
        self._hover = True; self.update(); super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False; self.update(); super().leaveEvent(e)

    def paintEvent(self, e):
        super().paintEvent(e)   # 투명 배경(배경칠 안 함)
        base = QColor(self._col) if self._col else QColor('#C7CAD1' if is_dark() else '#46566e')
        col = QColor('#9DB7E0') if self._hover else base   # hover=소프트블루, 배경칠 없음
        p = QPainter(self)
        d = float(min(self.width(), self.height()))
        _draw_reload_arrow(p, self.width() / 2.0, self.height() / 2.0,
                           d * 0.34, col, max(1.3, d * 0.11))
        p.end()


# ── SPECTRA 로고 마크 (정적 그라디언트 웨이브 SVG → QPixmap 캐시; 라이브 렌더 아님 → 속도 무관)


class LeqWindow(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent, Qt.Window)
        self.setWindowTitle('Time Average Level (LEQ)'); _apply_dark_titlebar(self, resizable=True)
        self.setMinimumSize(340, 300)
        self.setStyleSheet(f'background:{T("bg2")};color:{T("text")};')

        self._leq_a_buf = _RingBuf(60 * 60 * 50)   # 최대 프리셋 60분 × 50Hz (ndarray 링버퍼)
        self._leq_c_buf = _RingBuf(60 * 60 * 50)
        self._start_time = None
        self._buf_mutex = QMutex()
        self._duration_min = 5
        self._running = False

        layout = QVBoxLayout(self)

        # 시간 설정
        top = QHBoxLayout()
        top.addWidget(QLabel('Duration:'))
        self.dur_cb = RoundComboBox()
        self.dur_cb.addItems(['5 min','10 min','15 min','30 min','45 min','60 min'])
        self.dur_cb.setStyleSheet(f'background:{T("panel")};color:{T("text")};border:1px solid {T("border")};padding:3px;min-width:70px;')
        self.dur_cb.currentIndexChanged.connect(self._dur_changed)
        top.addWidget(self.dur_cb)
        self.leq_start_btn = QPushButton('Start'); _apply_txn(self.leq_start_btn, False)
        self.leq_start_btn.setFocusPolicy(Qt.NoFocus)   # macOS 파란 포커스 링 제거
        self.leq_start_btn.setStyleSheet(f'background:rgba(78,125,240,25);color:{T("accent")};border:1px solid rgba(78,125,240,100);padding:4px 10px;border-radius:8px;')
        self.leq_start_btn.clicked.connect(self._toggle_leq)
        top.addWidget(self.leq_start_btn)
        top.addStretch()
        layout.addLayout(top)

        # 진행바
        self.progress_lbl = QLabel('Standby')
        self.progress_lbl.setStyleSheet(f'color:{T("text_dim")};font-size:10px;')
        layout.addWidget(self.progress_lbl)

        # 결과 표시
        result_group = QGroupBox('Live LEQ')
        result_group.setStyleSheet(f'QGroupBox{{border:1px solid {T("border")};border-radius:6px;margin-top:8px;color:{T("text_dim")};font-size:10px;}}')
        rg_layout = QVBoxLayout(result_group)

        def big_val_row(label, color):
            row = QHBoxLayout()
            lbl = QLabel(label); lbl.setStyleSheet(f'color:{T("text_dim")};font-size:11px;')
            val = QLabel('—'); val.setStyleSheet(f'color:{color};font-size:22px;font-weight:bold;')
            val.setAlignment(Qt.AlignRight)
            row.addWidget(lbl); row.addWidget(val)
            return row, val

        r1,self.leq_a_lbl   = big_val_row('LEQ(A)', T('accent'))
        r2,self.leq_c_lbl   = big_val_row('LEQ(C)', T('accent3'))
        r3,self.inst_a_lbl  = big_val_row('dBA', T('accent'))
        r4,self.inst_c_lbl  = big_val_row('dBC', T('accent3'))
        for r in [r1,r2,r3,r4]: rg_layout.addLayout(r)
        layout.addWidget(result_group)

        # 리셋
        rst = QPushButton('  Reset'); rst.setIcon(_icon('refresh'))
        rst.setStyleSheet(f'background:{T("panel")};color:{T("text_dim")};border:1px solid {T("border")};padding:4px;border-radius:8px;')
        rst.clicked.connect(self._reset_leq)
        layout.addWidget(rst)
        layout.addStretch()

        # 업데이트 타이머
        self._update_timer = QTimer(self)
        self._update_timer.timeout.connect(self._update_display)
        self._update_timer.start(500)

    def showEvent(self, e):
        super().showEvent(e)
        if not self._update_timer.isActive():
            self._update_timer.start(500)

    def closeEvent(self, e):
        self._update_timer.stop()
        if hasattr(self.parent(), 'leq_win'):
            self.parent().leq_win = None
        # 파이썬 참조만 지우면 C++ 객체는 부모(MainWindow) 밑에 그대로 남아, 다시 열 때마다
        # 새 인스턴스가 생기고 이전 것이 버퍼를 든 채 고아가 된다(창당 최대 44MB).
        self.deleteLater()
        e.accept()

    def _dur_changed(self,idx):
        self._duration_min=[5,10,15,30,45,60][idx]

    def _toggle_leq(self):
        self._running=not self._running
        if self._running:
            self._start_time=time.time()
            self._leq_a_buf.clear(); self._leq_c_buf.clear()
            self.leq_start_btn.setText('Stop'); _apply_txn(self.leq_start_btn, True)
            self.leq_start_btn.setStyleSheet(f'background:rgba(255,69,58,25);color:{T("red")};border:1px solid rgba(255,69,58,100);padding:4px 10px;border-radius:8px;')
        else:
            self.leq_start_btn.setText('Start'); _apply_txn(self.leq_start_btn, False)
            self.leq_start_btn.setStyleSheet(f'background:rgba(78,125,240,25);color:{T("accent")};border:1px solid rgba(78,125,240,100);padding:4px 10px;border-radius:8px;')

    def _reset_leq(self):
        self._running=False; self._leq_a_buf.clear(); self._leq_c_buf.clear()
        self._start_time=None
        for lbl in [self.leq_a_lbl,self.leq_c_lbl,self.inst_a_lbl,self.inst_c_lbl]:
            lbl.setText('—')
        self.progress_lbl.setText('Standby')
        self.leq_start_btn.setText('Start'); _apply_txn(self.leq_start_btn, False)
        self.leq_start_btn.setStyleSheet(f'background:rgba(78,125,240,25);color:{T("accent")};border:1px solid rgba(78,125,240,100);padding:4px 10px;border-radius:8px;')

    def push_sample(self, dba, dbc):
        if not self._running: return
        with QMutexLocker(self._buf_mutex):
            self._leq_a_buf.append(_db2e(dba))
            self._leq_c_buf.append(_db2e(dbc))

    def _update_display(self):
        if not self._running: return
        max_samples = self._duration_min * 60 * 50      # 창 길이만 읽는다(링버퍼는 최대치까지 보유)
        with QMutexLocker(self._buf_mutex):
            if not self._leq_a_buf: return
            a_arr=self._leq_a_buf.last(max_samples)
            c_arr=self._leq_c_buf.last(max_samples)
        if a_arr.size == 0: return
        leq_a=_e2leq(a_arr)
        leq_c=_e2leq(c_arr)
        self.leq_a_lbl.setText(f'{leq_a:.1f} dBA')
        self.leq_c_lbl.setText(f'{leq_c:.1f} dBC')
        self.inst_a_lbl.setText(f'{10*np.log10(max(a_arr[-1],1e-12)):.1f} dBA')   # 버퍼는 에너지
        self.inst_c_lbl.setText(f'{10*np.log10(max(c_arr[-1],1e-12)):.1f} dBC')
        # 진행률
        if self._start_time:
            elapsed=time.time()-self._start_time
            total=self._duration_min*60
            pct=min(100,elapsed/total*100)
            mins=int(elapsed//60); secs=int(elapsed%60)
            self.progress_lbl.setText(f'Elapsed: {mins:02d}:{secs:02d} / {self._duration_min:02d}:00  ({pct:.0f}%)')
            if elapsed>=total:
                self._running=False
                self.leq_start_btn.setText('Start'); _apply_txn(self.leq_start_btn, False)
                self.progress_lbl.setText(f'✓ Done  LEQ(A)={leq_a:.1f}  LEQ(C)={leq_c:.1f}')

# ───────────────────────────────────────────
#  SPL Meter — Smaart-style floating window
# ───────────────────────────────────────────
def _clock_colors():
    """시계 카드 색 — 제목=소프트블루 / 숫자=소프트화이트(보조 정보, 측정값과 안 싸움).
    라이트 테마에선 흰 패널 위 가독 위해 어두운 텍스트로 파생."""
    if is_dark():
        return '#9DB7E0', '#E9ECF3'
    return T('accent'), T('text')


def _spl_card_bg():
    """SPL 미터 카드 배경 — 창(bg2 회색)보다 어둡게 '반전'. 다크=검정 / 라이트=회색(bg3).
    기존(검정 창·회색 카드)에서 뒤집어 다른 탭과 통일감(회색 크롬·어두운 콘텐츠)."""
    return QColor('#000000') if is_dark() else QColor(T('bg3'))


class _SplPanel(QWidget):
    """Single measurement panel inside SplMeterWindow — Smaart-style centered layout."""
    _BASE_W = 200  # reference width for font scaling

    reset_time_requested = pyqtSignal()   # LEQ 카드(laeq/lceq)의 시간 리셋 버튼
    reset_max_requested  = pyqtSignal()   # 카드별 Max/Peak 리셋 버튼 (전역 Reset Max 대체)

    def __init__(self, title, tc, vc, bg_hex='#0d0d1a', border_hex='#2a3060', parent=None, metric_id=None):
        super().__init__(parent)
        self.metric_id = metric_id
        self._tc = tc; self._vc = vc; self._base_vc = vc
        self._warn_db = -20.0   # yellow above this
        self._peak_db = -10.0   # red above this
        if metric_id == 'fs_peak':   # dBFS 절대값 — 0=풀스케일. 클립 근접 경고
            self._warn_db = -6.0; self._peak_db = -1.0
        self._tint_val = None   # 하단 존 틴트 글로우용 현재값 (None=신호없음→틴트 없음)
        self._bg    = QColor(bg_hex)
        self._bord  = QColor(border_hex)
        self._val_fs = 46  # current font size for value label
        self._max_fs = 15  # current font size for Max/dot (리사이즈 후 재적용용)
        # 너비 기준 스케일(Smaart식) — _FIT_H 는 클리핑 직전 빠듯한 콘텐츠 높이(높이 상한 클램프용)
        self._fit_h = 116 if metric_id in ('laeq', 'lceq') else 92
        self.setAttribute(Qt.WA_OpaquePaintEvent, False)
        self.setMinimumHeight(20)   # 아주 작게까지 허용 (최소 크기 탐색용)
        layout = QVBoxLayout(self)
        # inner margins leave room for the painted border
        layout.setContentsMargins(10, 4, 10, 4); layout.setSpacing(1)

        self._title_lbl = QLabel(title)
        self._title_lbl.setAlignment(Qt.AlignCenter)
        self._title_lbl.setStyleSheet(
            f'color:{tc};font-size:18px;font-weight:bold;background:transparent;')
        layout.addWidget(self._title_lbl)

        self._sep = QFrame(); self._sep.setFrameShape(QFrame.HLine); self._sep.setFixedHeight(1)
        self._sep.setStyleSheet(f'background:{T("border")};border:none;')
        layout.addWidget(self._sep)

        layout.addStretch(1)   # value 세로 중앙 정렬 (Smaart식)
        self._val_lbl = QLabel('—')
        self._val_lbl.setAlignment(Qt.AlignCenter)
        self._val_lbl.setStyleSheet(self._val_ss(vc, 46))   # sans 숫자(FONT_NUM) — Alarm과 통일
        layout.addWidget(self._val_lbl)
        layout.addStretch(1)

        max_row = QHBoxLayout(); max_row.setContentsMargins(0, 0, 0, 0)
        max_row.addStretch()
        self._dot = QLabel('●')
        self._dot.setStyleSheet('color:#33FF66;font-size:15px;background:transparent;')
        self._max_lbl = QLabel('Max: —')
        self._max_lbl.setStyleSheet(f'color:{T("text_dim")};font-size:15px;background:transparent;')
        max_row.addWidget(self._dot); max_row.addWidget(self._max_lbl)
        max_row.addStretch()
        # ── 카드별 Max/Peak 리셋 버튼 (우측, 전역 타이틀바 Reset Max 대체).
        #    clock=리셋 개념 없음 / laeq·lceq=타이머 리셋이 대신함 → 제외.
        self._max_reset_btn = None
        if metric_id not in ('clock', 'laeq', 'lceq'):
            self._max_reset_btn = _ReloadBtn()
            self._max_reset_btn.setFixedSize(16, 16)
            self._max_reset_btn.setToolTip(_tx('Reset Max'))
            self._max_reset_btn.clicked.connect(lambda: self.reset_max_requested.emit())
            max_row.addWidget(self._max_reset_btn)
        layout.addLayout(max_row)

        # ── 시계/피크 카드: Max 행(점·라벨) 숨김 (시각 또는 피크 홀드값만 크게).
        #    피크 카드는 리셋 버튼은 유지(피크 홀드 리셋용).
        if metric_id in ('clock', 'peak', 'peak_c', 'fs_peak'):
            self._dot.hide(); self._max_lbl.hide()

        # ── LEQ 카드 전용: SPECTRA 그라디언트 시간 진행 미터 + 리셋(숫자 없음)
        self._timebar = None
        self._time_reset_btn = None
        if metric_id in ('laeq', 'lceq'):
            time_row = QHBoxLayout(); time_row.setContentsMargins(0, 0, 0, 0); time_row.setSpacing(6)
            self._timebar = _GradTimeBar()
            self._time_reset_btn = _ReloadBtn()
            self._time_reset_btn.setFixedSize(18, 18); self._time_reset_btn.setToolTip(_tx('Reset LEQ timer'))
            # 배경칠 없음 — hover 시 _ReloadBtn이 아이콘 색만 바꿈(요청 2026-06-28)
            self._time_reset_btn.setStyleSheet('QPushButton{border:none;background:transparent;padding:0;}')
            self._time_reset_btn.clicked.connect(lambda: self.reset_time_requested.emit())
            time_row.addWidget(self._timebar, 1)
            time_row.addWidget(self._time_reset_btn)
            layout.addLayout(time_row)

    def set_time_progress(self, p):
        if self._timebar is not None:
            self._timebar.set_progress(p)

    def set_clock(self, text):
        """시계 카드 — 현재 시각 문자열(HH:MM) 표시."""
        self._val_lbl.setText(text)

    def _relayout(self):
        """Smaart식 — 카드는 셀을 꽉 채우고, 숫자는 너비 기준으로 스케일(세로로 길면 가운데 정렬).
        아주 넓고 낮을 때만 높이(_fit_h)로 상한을 둬 클리핑 방지."""
        w = self.width(); h = self.height()
        if w <= 0 or h <= 0:
            return
        scale = min(w / self._BASE_W, h / self._fit_h)   # 너비 주동인 + 높이 상한 클램프
        self.set_font_scale(scale)
        self.update()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._relayout()

    def _val_ss(self, color, size):
        """값 라벨 스타일 — 숫자는 sans(FONT_NUM)로 통일(Alarm 창과 동일 언어)."""
        return (f'color:{color};font-size:{size}px;font-weight:bold;'
                f'font-family:"{FONT_NUM}";background:transparent;')

    def _zone_tint_color(self, val):
        """하단 틴트용 신호등 색 — 주의=노랑 / 위험=빨강 (안전=틴트 없음, Alarm warn 방식)."""
        if val > self._peak_db:  return QColor('#FF453A')
        return QColor('#FF9F0A')

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(2, 2, -2, -2)   # 셀 전체 채움 (여백 없음)
        rad = 12   # Alarm 창(16)과 결 맞춘 라운드 (기존 8 → 12)
        # 테마 토큰 사용 → 다크/라이트 토글 시 update()만으로 카드 배경이 따라감 (반전: 검정/회색)
        p.setPen(Qt.NoPen)
        p.setBrush(_spl_card_bg())
        p.drawRoundedRect(r, rad, rad)
        # ── 존 틴트 글로우(하단) — 주의/위험(warn/peak) 존일 때만. 안전은 깔끔한 중립(Alarm과 통일).
        #    시계·dBFS 피크 제외.
        if (self.metric_id not in ('clock', 'fs_peak') and self._tint_val is not None
                and self._tint_val > self._warn_db):
            zc = self._zone_tint_color(self._tint_val)
            clip = QPainterPath(); clip.addRoundedRect(r, rad, rad)
            p.save(); p.setClipPath(clip)
            g = QLinearGradient(0, r.bottom(), 0, r.bottom() - min(r.height() * 0.55, 90))
            g.setColorAt(0, QColor(zc.red(), zc.green(), zc.blue(), 70))
            g.setColorAt(1, QColor(zc.red(), zc.green(), zc.blue(), 0))
            p.fillRect(r, g); p.restore()
        pen = QPen(QColor(T('border')), 1.5)
        p.setPen(pen); p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(r, rad, rad)
        p.end()
        super().paintEvent(e)

    def restyle(self):
        """테마 토글 시 카드 내부 색 재적용 (분리선 + 카드 배경/테두리 repaint)."""
        self._sep.setStyleSheet(f'background:{T("border")};border:none;')
        self._max_lbl.setStyleSheet(f'color:{T("text_dim")};font-size:{self._max_fs}px;background:transparent;')
        if self.metric_id == 'clock':   # 시계 색은 테마별 → 재적용
            self._tc, self._vc = _clock_colors(); self._base_vc = self._vc
            self._relayout()
        self.update()

    def set_calib_offset(self, offset):
        if self.metric_id == 'fs_peak':
            return   # dBFS 절대값 — 캘리브 오프셋 영향 없음
        self._warn_db = -20.0 + offset
        self._peak_db = -10.0 + offset

    def _level_color(self, val):
        if val > self._peak_db:   return '#FF453A'  # red
        if val > self._warn_db:   return '#FF9F0A'  # yellow
        return self._base_vc

    def _peak_color(self, max_val):
        if max_val > self._peak_db:  return '#FF453A'
        if max_val > self._warn_db:  return '#FF9F0A'
        return '#33FF66'

    def set_font_scale(self, scale):
        # 하한을 낮춰 창을 아주 작게 줄여도 글자가 같이 작아지게
        vs = max(10, int(46 * scale))
        ts = max(8,  int(18 * scale))
        ms = max(8,  int(15 * scale))
        self._val_fs = vs
        self._max_fs = ms
        self._title_lbl.setStyleSheet(
            f'color:{self._tc};font-size:{ts}px;font-weight:bold;background:transparent;')
        self._val_lbl.setStyleSheet(self._val_ss(self._vc, vs))
        self._dot.setStyleSheet(f'color:#00e676;font-size:{ms}px;background:transparent;')
        self._max_lbl.setStyleSheet(f'color:{T("text_dim")};font-size:{ms}px;background:transparent;')

    def set_value(self, val, max_val):
        self._tint_val = val   # 하단 존 틴트 갱신 (paintEvent에서 신호등 글로우)
        self.update()
        vc = self._level_color(val)
        if vc != self._vc:
            self._vc = vc
            self._val_lbl.setStyleSheet(self._val_ss(vc, self._val_fs))
        self._val_lbl.setText(f'{val:.1f}')
        if max_val is not None:
            pc = self._peak_color(max_val)
            # font-size 를 함께 명시 — 안 그러면 리사이즈로 키운 크기가 매 갱신마다 기본값으로 되돌아감
            # [PERF] 값 라벨처럼 '바뀔 때만' 적용 — 예전엔 매 틱 무조건 재설정해 16패널×5Hz면
            # 초당 160회 스타일시트 재파싱+repolish가 돌았다(색·크기는 거의 안 변하는데도).
            _pk = (pc, self._max_fs)
            if _pk != getattr(self, '_pk_ss', None):
                self._pk_ss = _pk
                _ss = f'color:{pc};font-size:{self._max_fs}px;background:transparent;'
                self._dot.setStyleSheet(_ss)
                self._max_lbl.setStyleSheet(_ss)
            self._max_lbl.setText(f'Max: {max_val:.1f}')

    def reset(self):
        if self.metric_id == 'clock':
            return   # 시계는 Reset Max 대상 아님 (다음 틱에 시간 그대로 유지)
        self._tint_val = None; self.update()   # 신호없음 → 틴트 제거
        self._vc = self._base_vc
        self._val_lbl.setStyleSheet(self._val_ss(self._base_vc, self._val_fs))
        self._val_lbl.setText('—'); self._max_lbl.setText('Max: —')
        self._dot.setStyleSheet(f'color:#33FF66;font-size:{self._max_fs}px;background:transparent;')
        self._max_lbl.setStyleSheet(f'color:{T("text_dim")};font-size:{self._max_fs}px;background:transparent;')


# _GradTimeBar — v2.0 분해: spectra/ui/widgets.py, re-import
from spectra.ui.widgets import _GradTimeBar
class _SplMetricEngine:
    """SPL 지표 계산 엔진 — push(순간 Z/A/C calibrated + dBFS peak) → Fast/Slow EMA + LEQ + 피크홀드.
    SplAlarmWindow가 독립 소유(SPL 미터 없이도 동작). 호출은 _process_audio(GUI 스레드)에서만."""
    _RATE = 50
    _EMA_IDS = ('dba', 'dbc', 'spl_slow', 'dba_fast', 'dbc_fast', 'spl_fast')

    def __init__(self, leq_secs=900, calib=0.0):
        self._ema = {}; self._peak = {}
        self._buf_a = _RingBuf(self._RATE * 3600 * 3)   # 3시간(최대 LEQ 프리셋, 여유 있게 공칭 레이트)
        self._buf_c = _RingBuf(self._RATE * 3600 * 3)
        self._rate = _RateEst(self._RATE)   # 실제 푸시 레이트 추정(LEQ 창을 실측 기준으로)
        self._last_t = None
        self._leq_secs = max(1, int(leq_secs))
        self._calib = calib

    def set_calib(self, c): self._calib = c
    def set_leq_secs(self, s): self._leq_secs = max(1, int(s))

    def reset(self):
        self._ema.clear(); self._peak.clear()
        self._buf_a.clear(); self._buf_c.clear(); self._last_t = None

    def reset_leq(self):
        """LEQ 적분만 리셋(Fast/Slow EMA·피크는 유지) — 미터 _reset_time과 동일."""
        self._buf_a.clear(); self._buf_c.clear()

    def leq_progress(self, mid):
        """LEQ 적분 진행도 0..1 (쌓인 시간 / 설정 적분 길이)."""
        buf = self._buf_a if mid == 'laeq' else self._buf_c
        return min(1.0, (len(buf) / self._rate.hz) / max(1, self._leq_secs))

    def push(self, dbz, dba, dbc, fs_peak):
        now = time.time()
        self._rate.tick(now)      # 실제 푸시 레이트 갱신
        dt = (now - self._last_t) if self._last_t else 0.02
        self._last_t = now
        dt = min(max(dt, 0.001), 0.5)
        af = 1.0 - math.exp(-dt / 0.125); asw = 1.0 - math.exp(-dt / 1.0)

        def _e(k, x, a):
            v = self._ema.get(k); v = x if v is None else v + (x - v) * a
            self._ema[k] = v; return v
        a_s = _e('dba', dba, asw); _e('dba_fast', dba, af)
        c_s = _e('dbc', dbc, asw); _e('dbc_fast', dbc, af)
        _e('spl_slow', dbz, asw);  _e('spl_fast', dbz, af)

        decay = dt * 6.0
        def _h(k, x):
            v = self._peak.get(k)
            self._peak[k] = x if (v is None or x > v) else max(x, v - decay)
        _h('peak', fs_peak + self._calib); _h('peak_c', dbc); _h('fs_peak', fs_peak)

        if dba > -100:
            self._buf_a.append(_db2e(a_s)); self._buf_c.append(_db2e(c_s))

    def value(self, mid):
        if mid in ('laeq', 'lceq'):
            buf = self._buf_a if mid == 'laeq' else self._buf_c
            arr = buf.last(self._rate.window_n(self._leq_secs))   # 실측 레이트 기준 창(O(창 길이))
            if arr.size == 0:
                return None
            return _e2leq(arr)
        if mid in self._peak:
            return self._peak.get(mid)
        return self._ema.get(mid)


class _SplAlarmDisplay(QWidget):
    """SPL 임계 신호등 — 창 크기에 맞춰 스케일되는 큰 중앙정렬(3구 신호등+거대 숫자+상태).
    빨강(초과) 시 0.4s 깜빡임."""
    GREEN  = QColor('#34C759'); YELLOW = QColor('#FFD60A'); RED = QColor('#FF453A')
    reset_requested = pyqtSignal()   # 카드 내부 LEQ 진행 바 옆 리셋(↻) 클릭

    def __init__(self, parent=None):
        super().__init__(parent)
        # 작게 줄여도 카드가 창을 넘지 않게(타이틀바34+여백20 고려) 최소높이를 낮게 — paint가 스케일
        self.setMinimumSize(160, 80)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._label = 'LAeq'; self._unit = 'dBA'; self._value = None
        self._limit = 100.0; self._amber = 3.0; self._over_since = None; self._blink_n = 0
        self._alarm_state = 'OK'   # 3상태 전이 로그용 (OK/AMBER/OVER)
        self._show_timebar = False; self._progress = 0.0   # LEQ 적분 진행 바(카드 내부 하단)
        self._reset_hit = None; self._reset_hover = False
        self.setMouseTracking(True)

    def configure(self, label, unit, limit, amber):
        self._label = label; self._unit = unit
        self._limit = float(limit); self._amber = float(amber); self.update()

    def set_value(self, v):
        self._value = v; self._blink_n += 1
        # 3상태 판정 (OK/AMBER/OVER) — 진입 전이 시 1회만 로그
        if v is None:
            st = 'OK'
        elif v >= self._limit:
            st = 'OVER'
        elif v >= self._limit - self._amber:
            st = 'AMBER'
        else:
            st = 'OK'
        if st != self._alarm_state:
            if st == 'OVER':
                self._over_since = time.time()
            elif self._alarm_state == 'OVER':
                self._over_since = None          # OVER 이탈 → 깜빡임 해제
            self._alarm_state = st
            _diag('spl_alarm', state=st, metric=self._label,
                  val=(None if v is None else round(v, 1)), limit=round(self._limit, 1))
        self.update()

    def _state(self):
        v = self._value
        if v is None:
            return 0, self.GREEN, False
        if v >= self._limit:
            return 2, self.RED, True
        if v >= self._limit - self._amber:
            return 1, self.YELLOW, False
        return 0, self.GREEN, False

    def paintEvent(self, e):
        # ── Concept C "정제된 신호"(2026-08-30 리디자인) — 중립 다크 카드 + 상단 은은한
        #    상태 워시 + 또렷한 3분할 상태 바(글로우 제거) + sans 대형 숫자 + 세그먼트 LEQ 바.
        idx, color, over = self._state()
        dim_blink = over and ((self._blink_n // 2) % 2 == 0)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True); p.setRenderHint(QPainter.TextAntialiasing, True)
        W = self.width(); H = self.height()
        m = max(8, int(min(W, H) * 0.05))
        x, y, w, h = m, m, W - 2 * m, H - 2 * m
        cr, cg, cb = color.red(), color.green(), color.blue()
        path = QPainterPath(); path.addRoundedRect(QRectF(x, y, w, h), 16, 16)
        # 카드 바탕 = 중립 다크(살짝 떠 보이는 elevation). 초록 과다 틴트 제거.
        p.fillPath(path, QColor(T('bg3')))
        # 상단 상태 워시 — 카드 위쪽 중앙에서 옅게 퍼지는 상태색(글로우 대체, 은은).
        # _wash_mode: 'warn'=위험(AMBER/OVER)일 때만(기본, 평소 깔끔) / 'always'=항상 / 'none'=끔.
        wash_mode = getattr(self, '_wash_mode', 'warn')
        show_wash = (wash_mode == 'always') or (wash_mode == 'warn' and idx != 0)
        if show_wash:
            wash_a = 44 if not dim_blink else 14
            gw = QRadialGradient(x + w / 2, y, w * 0.78)
            gw.setColorAt(0.0, QColor(cr, cg, cb, wash_a))
            gw.setColorAt(1.0, QColor(cr, cg, cb, 0))
            p.save(); p.setClipPath(path); p.fillRect(QRectF(x, y, w, h), QBrush(gw)); p.restore()
        # 얇은 테두리 — 워시 있을 때만 상태색 옅게, 평소엔 중립 헤어라인(초록 상시노출 제거)
        if show_wash:
            bpen = QColor(cr, cg, cb, 90 if not dim_blink else 45)
        else:
            bpen = QColor(255, 255, 255, 22)
        p.setPen(QPen(bpen, 1.3)); p.setBrush(Qt.NoBrush); p.drawPath(path)

        cx = W / 2
        # LEQ 진행 바가 있으면 텍스트 영역(ch)을 상단 85%로 줄여 하단 스트립에 바+리셋을 카드 안에 넣음
        ch = h * 0.85 if self._show_timebar else h

        def pf(px, bold=True, num=False):
            f = QFont(FONT_NUM if num else FONT_SANS); f.setPixelSize(max(8, int(px))); f.setBold(bold); return f

        # ── 3분할 상태 바 — 신호등을 또렷한 pill로. 활성만 채도 有, 비활성=중립 회색(글로우 없음)
        seg_w = w * 0.20; seg_gap = w * 0.035
        seg_h = max(4.5, ch * 0.030)
        total = seg_w * 3 + seg_gap * 2
        sx0 = cx - total / 2; sy = y + ch * 0.12
        for i, c in enumerate((self.GREEN, self.YELLOW, self.RED)):
            on = (i == idx) and not dim_blink
            rx = sx0 + i * (seg_w + seg_gap)
            seg = QPainterPath(); seg.addRoundedRect(QRectF(rx, sy, seg_w, seg_h), seg_h / 2, seg_h / 2)
            if on:
                p.fillPath(seg, QBrush(c))
                p.setPen(QPen(QColor(255, 255, 255, 30), 1.0)); p.setBrush(Qt.NoBrush); p.drawPath(seg)
            else:
                p.fillPath(seg, QColor(88, 88, 92, 140))

        vstr = '—' if self._value is None else f'{self._value:.1f}'
        vpx = ch * 0.27; fv = pf(vpx, num=True); p.setFont(fv)
        while p.fontMetrics().horizontalAdvance(vstr) > w * 0.84 and vpx > 12:
            vpx *= 0.92; fv = pf(vpx, num=True); p.setFont(fv)
        p.setPen(QPen(QColor(T('text')) if idx == 0 else color))
        p.drawText(QRectF(x, y + ch * 0.20, w, ch * 0.31), Qt.AlignHCenter | Qt.AlignVCenter, vstr)

        p.setFont(pf(ch * 0.082, bold=False)); p.setPen(QPen(QColor(T('text_dim'))))
        p.drawText(QRectF(x, y + ch * 0.55, w, ch * 0.10), Qt.AlignHCenter | Qt.AlignVCenter,
                   f'/ {self._limit:.0f} {self._unit}')

        if self._value is not None:
            p.setFont(pf(ch * 0.084))
            if over:
                p.setPen(QPen(self.RED)); mtxt = f'▲ +{self._value - self._limit:.1f} dB over'
            else:
                p.setPen(QPen(color)); mtxt = f'▼ {self._limit - self._value:.1f} dB headroom'
            p.drawText(QRectF(x, y + ch * 0.67, w, ch * 0.10), Qt.AlignHCenter | Qt.AlignVCenter, mtxt)

        status = ('OK', 'AMBER', 'OVER')[idx]
        if over and self._over_since is not None:
            status += f'  ·  {int(time.time() - self._over_since)}s'
        else:
            sub = ('Safe', 'Ease off', '')[idx]
            if sub:
                status += f'  ·  {sub}'
        p.setFont(pf(ch * 0.098)); p.setPen(QPen(color))
        p.drawText(QRectF(x, y + ch * 0.80, w, ch * 0.15), Qt.AlignHCenter | Qt.AlignVCenter, status)

        # ── LEQ 적분 진행 바(세그먼트) + 리셋(↻) — 카드 내부 하단 스트립
        self._reset_hit = None
        if self._show_timebar:
            strip_top = y + ch; strip_h = (y + h) - strip_top
            bar_h = max(5.0, h * 0.020)
            rb = max(7.0, strip_h * 0.30)            # 리셋 글리프 반경
            pad = 12.0
            rcx = x + w - pad - rb; rcy = strip_top + strip_h * 0.5
            bar_x = x + pad; bar_w = (rcx - rb - 10) - bar_x; bar_y = rcy - bar_h / 2
            if bar_w > 8:
                nseg = 10; sgap = max(2.0, bar_w * 0.012)
                sw = (bar_w - sgap * (nseg - 1)) / nseg
                frac = max(0.0, min(1.0, self._progress))
                non = int(round(frac * nseg))
                grad = _spectra_grad_brush(bar_x, bar_x + bar_w, 255)  # 정적 캐시 브랜드 그라디언트
                for i in range(nseg):
                    segx = bar_x + i * (sw + sgap)
                    sp = QPainterPath(); sp.addRoundedRect(QRectF(segx, bar_y, sw, bar_h), bar_h / 2, bar_h / 2)
                    if i < non:
                        p.save(); p.setClipPath(sp)
                        p.fillRect(QRectF(bar_x, bar_y, bar_w, bar_h), grad); p.restore()
                    else:
                        p.fillPath(sp, QColor(T('bg')))   # 빈 슬롯=바탕보다 어둡게(오목)
            rcol = QColor('#9DB7E0') if self._reset_hover else QColor(T('text_dim'))
            _draw_reload_arrow(p, rcx, rcy, rb, rcol, max(1.3, rb * 0.22))
            self._reset_hit = QRectF(rcx - rb - 5, rcy - rb - 5, 2 * rb + 10, 2 * rb + 10)
        p.end()

    def set_progress(self, p):
        p = max(0.0, min(1.0, float(p)))
        if abs(p - self._progress) > 0.002:
            self._progress = p
            if self._show_timebar:
                self.update()

    def set_show_timebar(self, on):
        on = bool(on)
        if on != self._show_timebar:
            self._show_timebar = on; self.update()

    def mousePressEvent(self, e):
        if self._reset_hit is not None and self._reset_hit.contains(QPointF(e.pos())):
            self.reset_requested.emit(); return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        hov = self._reset_hit is not None and self._reset_hit.contains(QPointF(e.pos()))
        if hov != self._reset_hover:
            self._reset_hover = hov
            self.setCursor(Qt.PointingHandCursor if hov else Qt.ArrowCursor)
            self.update()
        super().mouseMoveEvent(e)


# SplAlarmConfigDialog — v2.0 분해: spectra/ui/dialogs.py, re-import
from spectra.ui.dialogs import SplAlarmConfigDialog
class SplAlarmWindow(QWidget):
    """SPL 임계 알람 — 독립 top-level 창. 메인 메뉴에서 직접 열고, SPL 미터와 무관하게
    _process_audio가 push_levels로 급전. 자체 _SplMetricEngine + 200ms 타이머."""
    _METRICS = {
        'laeq': 'dB LAeq', 'lceq': 'dB LCeq',
        'dba': 'SPL A Slow', 'dbc': 'SPL C Slow',
        'spl_slow': 'SPL Slow', 'dba_fast': 'SPL A Fast', 'dbc_fast': 'SPL C Fast',
        'spl_fast': 'SPL Fast', 'peak': 'Peak', 'peak_c': 'Peak C', 'fs_peak': 'FS Peak',
    }
    # 디스플레이 단위 — 선택한 지표대로 표기 (LEQ는 시간 분(min)을 _apply_cfg에서 덧붙임)
    _UNIT = {'laeq': 'dB LAeq', 'lceq': 'dB LCeq',
             'dba': 'dBA', 'dba_fast': 'dBA', 'dbc': 'dBC', 'dbc_fast': 'dBC',
             'spl_slow': 'dB SPL', 'spl_fast': 'dB SPL',
             'peak': 'dB Peak', 'peak_c': 'dBC Peak', 'fs_peak': 'dBFS'}
    _LEQ_PRESETS = [('1 min', 60), ('5 min', 300), ('10 min', 600),
                    ('15 min', 900), ('30 min', 1800), ('1 hr', 3600)]

    def __init__(self, main):
        self._main = main
        super().__init__(main, Qt.Window)   # 메인의 자식 창 → 풀스크린 SPECTRA 위에 따라 뜸
        self.setWindowTitle('SPL Alarm')
        self.setAttribute(Qt.WA_DeleteOnClose, False)
        self.setStyleSheet(f'background:{T("bg2")};')   # 창 배경=회색(bg2) — SPL 미터 창과 통일(카드가 떠 보이게)
        self._cfg = self._load_cfg()
        self._always_top = bool(self._cfg.get('on_top', True))
        # macOS는 showEvent에서 네이티브 setLevel로(깜빡임 없음). 그 외 OS만 Qt 플래그.
        if self._always_top and sys.platform != 'darwin':
            self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
        calib = 0.0
        try:
            calib = main._spl_source_calib(0)
        except Exception:
            pass
        self._eng = _SplMetricEngine(self._leq_secs(), calib)

        self._pin_btn = _PinBtn(); self._pin_btn.setChecked(self._always_top)
        self._pin_btn.setToolTip(_tx('Keep on top'))
        self._pin_btn.clicked.connect(self._toggle_on_top)
        self._set_btn = _SettingsBtn(); self._set_btn.setToolTip(_tx('Alarm settings'))
        self._set_btn.clicked.connect(self._open_config)

        lay = QVBoxLayout(self); lay.setContentsMargins(10, 10, 10, 10)
        self.disp = _SplAlarmDisplay()
        self.disp.reset_requested.connect(self._reset_leq)   # 카드 내부 LEQ 진행 바의 리셋(↻)
        lay.addWidget(self.disp)
        _apply_dark_titlebar(self, resizable=True, aux=[self._pin_btn, self._set_btn])
        self.setWindowState(Qt.WindowNoState)
        # 최소높이는 타이틀바34+여백20+카드최소80 = 134 이상이면 카드 안 잘림 → 여유두고 150
        # 기본 열림 크기 = 최소(컴팩트) — 사용자가 필요시 키움
        self.setMinimumSize(210, 150); self.resize(210, 150)
        self._apply_cfg()

        self._timer = QTimer(self); self._timer.timeout.connect(self._tick); self._timer.start(200)

    def _toggle_on_top(self):
        """always-on-top 켜고 끄기 — macOS는 네이티브 setLevel(깜빡임 없음), 그 외만 Qt 플래그."""
        self._always_top = not self._always_top
        self._pin_btn.setChecked(self._always_top); self._pin_btn.update()
        if not _apply_on_top(self, self._always_top):
            flags = self.windowFlags()
            flags = (flags | Qt.WindowStaysOnTopHint) if self._always_top else (flags & ~Qt.WindowStaysOnTopHint)
            self.setWindowFlags(flags); self.show()   # 폴백(비-macOS): 재생성 깜빡임 있음
        self._cfg['on_top'] = self._always_top
        self._save_cfg()

    # ── 설정 로드/저장 ──
    def _load_cfg(self):
        try:
            c = dict(self._main._settings.get('spl_alarm', {}))
        except Exception:
            c = {}
        return {
            'metric':  c.get('metric', 'laeq'),
            'limit':   float(c.get('limit', 100.0)),
            'amber':   float(c.get('amber', 3.0)),
            'leq_idx': int(c.get('leq_idx', 3)),
            'on_top':  bool(c.get('on_top', True)),
        }

    def _save_cfg(self):
        try:
            self._main._settings['spl_alarm'] = dict(self._cfg)
            _save_settings(self._main._settings)
        except Exception as e:
            _alog.warning(f'SPL 알람 설정 저장 실패: {e}')

    def _leq_secs(self):
        i = max(0, min(len(self._LEQ_PRESETS) - 1, int(self._cfg.get('leq_idx', 3))))
        return self._LEQ_PRESETS[i][1]

    def _apply_cfg(self):
        mid = self._cfg.get('metric', 'laeq')
        title = self._METRICS.get(mid, 'LAeq')
        unit = self._UNIT.get(mid, 'dB SPL')
        if mid in ('laeq', 'lceq'):           # LEQ 지표 — 적분 시간(분) 덧붙임: "dB LAeq 10min"
            unit += f' {self._leq_secs() // 60}min'
        self._eng.set_leq_secs(self._leq_secs())
        self.disp.configure(title, unit, self._cfg.get('limit', 100.0), self._cfg.get('amber', 3.0))
        self.disp.set_show_timebar(mid in ('laeq', 'lceq'))   # LEQ 지표만 카드 내부 진행 바/리셋 표시

    def _open_config(self):
        leq_labels = [lbl for lbl, _ in self._LEQ_PRESETS]
        dlg = SplAlarmConfigDialog(self._METRICS, leq_labels, self._cfg, self)
        if dlg.exec() == QDialog.Accepted:
            self._cfg = dlg.get_cfg()
            self._apply_cfg()
            self._save_cfg()

    # ── 메인 앱이 호출 ──
    def set_calib_offset(self, offset):
        self._eng.set_calib(offset)

    def push_levels(self, dbz, dba, dbc, fs_peak):
        self._eng.push(dbz, dba, dbc, fs_peak)

    def _reset_leq(self):
        """LEQ 적분 타이머 리셋 — 진행 바·LEQ를 0부터 다시 (미터 _reset_time과 동일)."""
        self._eng.reset_leq()
        self.disp.set_progress(0.0)
        _diag('spl_alarm', state='leq_reset', metric=self._cfg.get('metric', 'laeq'))

    def _tick(self):
        mid = self._cfg.get('metric', 'laeq')
        self.disp.set_value(self._eng.value(mid))
        if mid in ('laeq', 'lceq'):
            self.disp.set_progress(self._eng.leq_progress(mid))
        _glance_chrome_update(self)   # 마우스 밖이면 카드만(타이틀바 숨김)

    def restyle_theme(self):
        self.setStyleSheet(f'background:{T("bg2")};')   # 창 배경=회색(bg2) — SPL 미터 창과 통일(카드가 떠 보이게)
        b = getattr(self, '_dark_titlebar', None)
        if b is not None:
            b.setStyleSheet(f'#darkTitleBar{{background:{T("bg2")};}}')
            t = getattr(b, '_title', None)
            if t is not None:
                t.setStyleSheet(f'color:{T("text")};font-size:12px;font-weight:bold;background:transparent;')
        self.disp.update()

    def showEvent(self, e):
        super().showEvent(e)
        if not self._timer.isActive():
            self._timer.start(200)
        # 풀스크린 메인과 같은 화면일 때만 자식부착, 그 외엔 독립창 → 외부모니터 이동 가능.
        self._main._float_sync_attach(self)
        _apply_on_top(self, self._always_top)   # macOS 네이티브 레벨 적용

    def moveEvent(self, e):
        super().moveEvent(e)
        # 드래그로 화면을 넘나들면 부착/분리 재동기화(풀스크린 위 ↔ 외부 모니터)
        if self._main.isFullScreen():
            self._main._float_sync_attach(self)

    def closeEvent(self, e):
        self._timer.stop()
        if hasattr(self._main, 'spl_alarm_win'):
            self._main.spl_alarm_win = None
        self.deleteLater()          # 부모에 남는 고아 인스턴스 방지(버퍼 동반)
        e.accept()


class ShowModeWindow(QWidget):
    """FOH 글랜스 풀스크린 쇼 모드 — 거대한 SPL + 라이브 스펙트럼 + 핵심 지표.
    객석 건너편에서도 한눈에 읽히게. _process_audio가 push()로 급전(표시 전용, 측정로직 독립).
    한계 대비 초록(여유)→노랑(접근)→빨강(초과) 신호색."""
    _HEADLINE_TAU = 2.5   # 헤드라인 큰 숫자 평활 시정수(초) — 값↑=더 차분/느림, ↓=더 즉각.
                          #   프레임율 무관(시간기반). 글랜스 가독 튜닝 지점(멀리서도 안정적으로 읽히게 느리게).
    def __init__(self, main):
        super().__init__()
        self._main = main
        self.setWindowTitle('SPECTRA — Show Mode')
        self._spl = -120.0; self._unit = 'dBA'
        self._peak = -120.0; self._leq = -120.0
        self._num_pix = None; self._num_key = None   # 거대 숫자 픽스맵 캐시(문자열/색 바뀔 때만 재렌더)
        _st = getattr(main, '_settings', {}) or {}
        self._metric_mode = _st.get('show_metric', 'dba')   # 헤드라인 지표: dba/dbc/spl (드롭다운 선택)
        self._spec_mode   = _st.get('show_spec', 'oct24')   # 스펙트럼 해상도: oct3/oct12/oct24/fft
        self._leq_wt      = _st.get('show_leq_wt', 'a')     # LEQ 가중: a(LAeq)/c(LCeq) (드롭다운)
        self._leq_sec     = int(_st.get('show_leq_sec', 300))  # LEQ 시간창(초): 슬라이딩 적분
        self._leq_bins = deque()        # LEQ 에너지 빈 [t_int, e_sum, count] (초 단위, 시간창만큼 보관)
        self._leq_es = 0.0; self._leq_cn = 0   # 창 내 에너지합·샘플수(초당 1회만 정확 재계산)
        self._sm_prev = None            # 스펙트럼 막대 평활 상태(모드 바뀌면 리셋)
        self._metric_rect = None; self._spec_rect = None; self._leq_rect = None  # 드롭다운 히트영역 (x,y,w,h)
        self._last_paint = 0.0          # 리페인트 throttle (글랜스 차분하게)
        self._last_push = 0.0           # 헤드라인 시간기반 평활용 (프레임율 무관)
        self._limit = 100.0; self._amber = 3.0
        self._bands = None              # np.array octave dB
        self._bmin = -60.0; self._bmax = 0.0
        self.resize(1120, 630)
        self._clock = QTimer(self); self._clock.timeout.connect(self.update); self._clock.start(1000)

    def push(self, raw, unit, bands, bmin, bmax, dba=None, dbc=None):
        """순간 SPL(raw) + 스펙트럼 급전. 헤드라인=Slow 평활, PEAK=순간홀드.
        LEQ=선택 가중(A/C)·선택 시간창 슬라이딩 적분(dba/dbc 별도 급전). 리페인트 ~30fps."""
        self._unit = unit; self._bmin = bmin; self._bmax = bmax
        # 스펙트럼 막대 평활 — 해상도 모드가 raw(_calc_oct/FFT)로 와도 글랜스답게 차분히
        # (모드 바뀌어 길이 다르면 리셋). 채움만 평활, 스파이크는 어느정도 살림.
        if bands is not None:
            b = np.asarray(bands, dtype=float)
            if self._sm_prev is None or len(self._sm_prev) != len(b):
                self._sm_prev = b.copy()
            else:
                self._sm_prev += (b - self._sm_prev) * 0.35
            self._bands = self._sm_prev
        now = time.time()
        # 헤드라인 = Slow 평활 (raw가 60fps로 튀면 안 읽혀서). 시간기반 EMA →
        # push 호출율이 달라도 체감 속도 일정. dt 첫 프레임/큰 갭은 33ms로 클램프.
        dt = now - self._last_push if 0.0 < now - self._last_push < 0.5 else 0.033
        self._last_push = now
        a = 1.0 - math.exp(-dt / self._HEADLINE_TAU)
        self._spl = raw if self._spl <= -100 else self._spl + (raw - self._spl) * a
        self._peak = raw if raw > self._peak else self._peak - 0.04   # 진짜 순간 피크 홀드
        # LEQ — 선택 가중(A/C)·시간창 슬라이딩 적분. 초 단위 에너지 빈으로 메모리 바운드.
        _lv = dbc if self._leq_wt == 'c' else dba
        if _lv is None: _lv = raw                        # dba/dbc 미급전 폴백
        if _lv > -100:
            _ts = int(now); _le = 10.0 ** (_lv / 10.0)
            # [PERF] 예전엔 push마다(초당 ~94회) 최대 900개 빈을 두 번 합산해 초당 8.5만 반복을
            # 돌았고 pop(0)도 리스트라 O(n)이었다. 같은 초 안에서는 증분, 새 빈이 생길 때(초당 1회)
            # 만 정확 재합산 → 비용 1/94 + 부동소수 드리프트 없음. deque로 popleft는 O(1).
            if self._leq_bins and self._leq_bins[-1][0] == _ts:
                self._leq_bins[-1][1] += _le; self._leq_bins[-1][2] += 1
                self._leq_es += _le; self._leq_cn += 1
            else:
                self._leq_bins.append([_ts, _le, 1])
                _cut = _ts - self._leq_sec
                while self._leq_bins and self._leq_bins[0][0] < _cut:
                    self._leq_bins.popleft()
                self._leq_es = sum(b[1] for b in self._leq_bins)
                self._leq_cn = sum(b[2] for b in self._leq_bins)
            self._leq = 10.0 * math.log10(max(self._leq_es / max(self._leq_cn, 1), 1e-12))
        if now - self._last_paint >= 0.033:     # 리페인트 ~30fps (거대 숫자 캐시라 부담 적음)
            self._last_paint = now; self.update()

    def reset_hold(self):
        self._peak = -120.0; self._leq_bins = deque(); self._leq_es = 0.0; self._leq_cn = 0
        self._leq = -120.0; self.update()

    def set_limit(self, limit, amber):
        self._limit = float(limit); self._amber = float(amber)

    def mousePressEvent(self, e):
        """지표(dBA/dBC/dB SPL)·스펙트럼 해상도(1/3·1/12·1/24·FFT) 드롭다운 클릭."""
        x, y = e.x(), e.y()
        def _in(r): return r and r[0] <= x <= r[0]+r[2] and r[1] <= y <= r[1]+r[3]
        if _in(self._metric_rect):
            self._pick(e.globalPos(), '_metric_mode',
                       [('dba', 'dBA'), ('dbc', 'dBC'), ('spl', 'dB SPL')])
        elif _in(self._spec_rect):
            self._pick(e.globalPos(), '_spec_mode',
                       [('oct3', '1/3 oct'), ('oct12', '1/12 oct'),
                        ('oct24', '1/24 oct'), ('fft', 'FFT')], reset_bands=True)
        elif _in(self._leq_rect):
            self._leq_menu(e.globalPos())
        else:
            super().mousePressEvent(e)

    def _save_show_settings(self):
        st = getattr(self._main, '_settings', None)
        if st is not None:
            st['show_metric'] = self._metric_mode; st['show_spec'] = self._spec_mode
            st['show_leq_wt'] = self._leq_wt; st['show_leq_sec'] = self._leq_sec
            _save_settings(st)

    def _pick(self, gpos, attr, opts, reset_bands=False):
        """공용 드롭다운(QMenu) — 현재값 체크, 선택 시 저장+재렌더."""
        mnu = QMenu(self); cur = getattr(self, attr)
        acts = {}
        for key, lbl in opts:
            a = mnu.addAction(lbl); a.setCheckable(True); a.setChecked(key == cur)
            acts[a] = key
        act = mnu.exec_(gpos)
        if act in acts and acts[act] != cur:
            setattr(self, attr, acts[act])
            if reset_bands: self._sm_prev = None       # 해상도 바뀜 → 막대 평활 리셋
            self._save_show_settings(); self.update()

    def _leq_menu(self, gpos):
        """LEQ 드롭다운 — 가중(A/C) + 시간창(1/5/10/15분). 가중 바뀌면 적분 리셋."""
        mnu = QMenu(self)
        # 영어 원문을 키로 쓰는 앱 규약대로 _tx() 경유 — 예전엔 한국어가 하드코딩돼
        # 영어 모드에서도 '가중'·'분'이 그대로 나왔다.
        _wa = mnu.addAction(_tx('A-weighted (LAeq)')); _wa.setCheckable(True); _wa.setChecked(self._leq_wt == 'a')
        _wc = mnu.addAction(_tx('C-weighted (LCeq)')); _wc.setCheckable(True); _wc.setChecked(self._leq_wt == 'c')
        mnu.addSeparator()
        _tacts = {}
        for sec, lbl in [(60, _tx('1 min')), (300, _tx('5 min')),
                         (600, _tx('10 min')), (900, _tx('15 min'))]:
            a = mnu.addAction(lbl); a.setCheckable(True); a.setChecked(self._leq_sec == sec)
            _tacts[a] = sec
        act = mnu.exec_(gpos)
        if act is None: return
        if act is _wa and self._leq_wt != 'a':   self._leq_wt = 'a'; self._leq_bins = deque(); self._leq_es = 0.0; self._leq_cn = 0
        elif act is _wc and self._leq_wt != 'c': self._leq_wt = 'c'; self._leq_bins = deque(); self._leq_es = 0.0; self._leq_cn = 0
        elif act in _tacts:                       self._leq_sec = _tacts[act]   # 재윈도우(적분 유지)
        else: return
        self._save_show_settings(); self.update()

    def _state_color(self):
        if self._spl >= self._limit:            return QColor(T('red'))
        if self._spl >= self._limit - self._amber: return QColor(T('yellow'))
        return QColor(T('green'))

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Escape,) or e.text().lower() == 'f':
            self.close()
        else:
            super().keyPressEvent(e)

    def closeEvent(self, e):
        self._clock.stop()
        if hasattr(self._main, 'show_mode_win'):
            self._main.show_mode_win = None
        self.deleteLater()
        e.accept()

    def paintEvent(self, ev):
        W = self.width(); H = self.height()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing); p.setRenderHint(QPainter.TextAntialiasing)
        p.fillRect(0, 0, W, H, QColor('#07080B'))
        p.fillRect(0, 0, W, 3, _spectra_grad_brush(0, W))          # 상단 브랜드 그라디언트 라인
        m = int(min(W, H) * 0.045)
        # ── 상단: 브랜드 + 시계 ──
        bf = QFont(FONT_FAMILY, 1); bf.setPixelSize(max(16, int(H * 0.032))); bf.setBold(True)
        bf.setLetterSpacing(QFont.AbsoluteSpacing, 3)
        p.setFont(bf); p.setPen(QColor('#C9CDD7'))
        p.drawText(m, int(m * 0.6), W, int(H * 0.06), Qt.AlignLeft | Qt.AlignVCenter, 'SPECTRA')
        clk = time.strftime('%H:%M')
        cf = QFont(FONT_NUM); cf.setPixelSize(max(14, int(H * 0.028)))   # 시계=숫자 폰트 유지
        p.setFont(cf); p.setPen(QColor('#6A7180'))
        p.drawText(0, int(m * 0.6), W - m, int(H * 0.06), Qt.AlignRight | Qt.AlignVCenter, clk)
        # ── 본문 영역 ──
        top = int(H * 0.17); bot = int(H * 0.78)
        left_w = int(W * 0.40)
        col = self._state_color()
        # 왼쪽: 거대한 SPL 숫자 — 픽스맵 캐시(문자열/색/크기 바뀔 때만 재렌더).
        # 매프레임 거대 폰트 래스터라이즈가 풀스크린 버벅임의 주원인 → 대부분 프레임은 blit만.
        num = f'{self._spl:.1f}' if self._spl > -100 else '—'
        box_w = max(1, left_w - m); box_h = max(1, int((bot - top) * 0.74))
        _nkey = (num, col.name(), box_w, box_h)
        if self._num_key != _nkey or self._num_pix is None:
            self._num_key = _nkey
            pix = QPixmap(box_w, box_h); pix.fill(Qt.transparent)
            pp = QPainter(pix)
            pp.setRenderHint(QPainter.Antialiasing); pp.setRenderHint(QPainter.TextAntialiasing)
            avail_w = left_w - int(m * 1.5)
            nf = QFont(FONT_NUM); nf.setBold(True)
            size = int((bot - top) * 0.62); nf.setPixelSize(size); pp.setFont(nf)
            tw = pp.fontMetrics().horizontalAdvance(num)
            if tw > avail_w and tw > 0:                    # 3자리(100+)면 폭에 맞춰 축소
                size = max(10, int(size * avail_w / tw)); nf.setPixelSize(size); pp.setFont(nf)
            pp.setPen(col)
            pp.drawText(0, 0, box_w, box_h, Qt.AlignVCenter | Qt.AlignHCenter, num)
            pp.end()
            self._num_pix = pix
        p.drawPixmap(m, top, self._num_pix)
        uf = QFont(FONT_SANS); uf.setPixelSize(max(14, int(H * 0.040)))
        uf.setLetterSpacing(QFont.AbsoluteSpacing, 2)
        p.setFont(uf); p.setPen(QColor('#8B93A2'))
        _uy = int(bot - (bot - top) * 0.22); _uh = int((bot - top) * 0.20)
        p.drawText(m, _uy, left_w - m, _uh,
                   Qt.AlignHCenter | Qt.AlignTop, f'{self._unit}  ▾   /   {self._limit:.0f}')
        self._metric_rect = (m, _uy, left_w - m, _uh)   # 지표 드롭다운 클릭영역
        # 오른쪽: 라이브 스펙트럼 막대
        sx = left_w + m // 2; sy = top; sw = W - sx - m; sh = bot - top
        p.fillRect(sx, sy, sw, sh, QColor('#0D0F14'))
        p.setPen(QPen(QColor(255, 255, 255, 14), 1)); p.setBrush(Qt.NoBrush)
        p.drawRect(sx, sy, sw, sh)
        b = self._bands
        if b is not None and len(b):
            n = len(b); bw = sw / n; gap = max(1.0, bw * 0.12)
            rng = max(self._bmax - self._bmin, 1.0)
            usable_h = sh - max(6, int(sh * 0.07))   # 상단 여백 — 막대가 박스 천장에 안 닿게(짤림 방지)
            base = QColor(*bar_top())
            brush, capc = _vbar_gradient(base)
            for i in range(n):
                v = float(np.clip(b[i], self._bmin, self._bmax))
                bh = max(2, int((v - self._bmin) / rng * usable_h))
                bx = int(sx + i * bw + gap / 2); ww = max(1, int(bw - gap)); by = sy + sh - bh
                p.fillRect(bx, by, ww, bh, brush)
                if bh > 6: p.fillRect(bx, by, ww, 1, capc)
        # 스펙트럼 해상도 드롭다운 라벨 (박스 우상단) — 클릭 시 1/3·1/12·1/24·FFT 선택
        _rl = {'oct3': '1/3 oct', 'oct12': '1/12 oct', 'oct24': '1/24 oct',
               'fft': 'FFT'}.get(self._spec_mode, '1/24 oct') + '  ▾'
        rf = QFont(FONT_SANS); rf.setPixelSize(max(11, int(H * 0.022)))
        rf.setLetterSpacing(QFont.AbsoluteSpacing, 1)
        p.setFont(rf); _fm = p.fontMetrics()
        _rw = _fm.horizontalAdvance(_rl) + 22; _rh = _fm.height() + 10
        _rx = sx + sw - _rw - 12; _ry = sy + 12
        p.setPen(Qt.NoPen); p.setBrush(QColor(0, 0, 0, 160))
        p.drawRoundedRect(QRectF(_rx, _ry, _rw, _rh), 6, 6)
        p.setPen(QColor('#9CA3B2')); p.drawText(_rx, _ry, _rw, _rh, Qt.AlignCenter, _rl)
        self._spec_rect = (_rx, _ry, _rw, _rh)   # 해상도 드롭다운 클릭영역
        # ── 하단: 지표 칩 ──
        _leq_lab = f'L{self._leq_wt.upper()}eq · {self._leq_sec // 60}m  ▾'   # 예: LAeq · 5m ▾
        chips = [('PEAK', f'{self._peak:.0f}'), (_leq_lab, f'{self._leq:.1f}'),
                 ('HEADROOM', f'{self._limit - self._spl:+.0f} dB')]
        cy = int(H * 0.86); ch_h = int(H * 0.09)
        cw = (W - 2 * m) // len(chips); gap = int(W * 0.012)
        lf = QFont(FONT_SANS); lf.setPixelSize(max(11, int(H * 0.020)))
        lf.setLetterSpacing(QFont.AbsoluteSpacing, 2)
        vf = QFont(FONT_NUM); vf.setBold(True); vf.setPixelSize(max(18, int(H * 0.042)))
        for i, (lab, val) in enumerate(chips):
            x = m + i * cw
            p.setBrush(QColor('#101218')); p.setPen(QPen(QColor(255, 255, 255, 16), 1))
            p.drawRoundedRect(QRectF(x, cy, cw - gap, ch_h), 10, 10)
            if i == 1: self._leq_rect = (int(x), cy, int(cw - gap), ch_h)   # LEQ 드롭다운 클릭영역
            p.setFont(lf); p.setPen(QColor('#6E7585'))
            p.drawText(int(x + 18), cy, cw - gap - 18, ch_h, Qt.AlignLeft | Qt.AlignVCenter, lab)
            p.setFont(vf); p.setPen(QColor('#E6E9F0'))
            p.drawText(int(x), cy, cw - gap - 18, ch_h, Qt.AlignRight | Qt.AlignVCenter, val)
        p.end()


class SplMeterWindow(QWidget):
    """Smaart-style SPL Meter — 자유 행×열 그리드 + 칸별 지표 선택."""
    _PUSH_RATE = 50  # ~50 fps from audio thread
    _PRESETS = [
        ('1 min',   60),  ('5 min',   300), ('10 min',  600),
        ('15 min',  900), ('30 min', 1800), ('45 min', 2700),
        ('1 hr',   3600), ('1.5 hr', 5400), ('2 hr',   7200),
        ('3 hr',  10800),
    ]
    # 표시 가능한 지표:  id -> (제목, 색)  ── Smaart 스타일 확장 세트
    # 색 정책(v1.8): A가중=소프트블루 / C가중=소프트와인 / 광대역(Z)=흰색.
    #   진한 파랑#4E7DF0·보라#9B5DE5 값조합 비선호 → 소프트로 통일. 경고/피크색은 유지.
    _SOFT_A = '#9DB7E0'   # A가중 소프트블루
    _SOFT_C = '#C98B96'   # C가중 소프트와인
    _SOFT_Z = '#E6E9F0'   # 광대역(Z) 소프트화이트
    _METRICS = {
        'dba':     ('SPL A Slow', _SOFT_A),     # A가중 Slow(1s)
        'dbc':     ('SPL C Slow', _SOFT_C),     # C가중 Slow(1s)
        'spl_slow':('SPL Slow',   _SOFT_Z),     # Z(flat) Slow
        'dba_fast':('SPL A Fast', _SOFT_A),     # A가중 Fast(125ms)
        'dbc_fast':('SPL C Fast', _SOFT_C),     # C가중 Fast
        'spl_fast':('SPL Fast',   _SOFT_Z),     # Z(flat) Fast
        'peak':    ('Peak',       '#FF9F0A'),   # Z 피크 홀드(디지털 피크→SPL) — 경고색 유지
        'peak_c':  ('Peak C',     '#FF375F'),   # C가중 최대 홀드(근사) — 경고색 유지
        'fs_peak': ('FS Peak',    '#FF453A'),   # 풀스케일 디지털 피크(dBFS) — 경고색 유지
        'laeq':    ('LAeq',       _SOFT_A),     # A가중 적분
        'lceq':    ('LCeq',       _SOFT_C),     # C가중 적분
        'clock':   ('Clock',      '#5AC8FA'),   # 색은 _clock_colors()가 별도 적용
    }
    _EMA_IDS  = ('dba', 'dbc', 'spl_slow', 'dba_fast', 'dbc_fast', 'spl_fast')
    _PEAK_IDS = ('peak', 'peak_c', 'fs_peak')
    _DEFAULT_CELLS = ['dba', 'dbc', 'laeq', 'lceq']

    def __init__(self, parent=None):
        # 메인의 자식 창 → 풀스크린 SPECTRA 위에 확실히 따라 뜸(별도 Space 분리 방지).
        # 트레이드오프: 메인 최소화 시 함께 숨겨짐(사용자 선택 2026-06-17). 메인참조는 _main.
        self._main = parent
        super().__init__(parent, Qt.Window)
        try:
            self._always_top = bool(self._main._settings.get('spl_meter', {}).get('on_top', True))
        except Exception:
            self._always_top = True
        # macOS는 showEvent에서 네이티브 setLevel로(깜빡임 없음). 그 외 OS만 Qt 플래그.
        if self._always_top and sys.platform != 'darwin':
            self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
        self.setWindowTitle('SPL Meter')
        self.setAttribute(Qt.WA_DeleteOnClose, False)

        self._buf_a = _RingBuf(self._PUSH_RATE * 60 * 60 * 3)  # 3 hr max (ndarray 링버퍼)
        self._buf_c = _RingBuf(self._PUSH_RATE * 60 * 60 * 3)
        self._rate = _RateEst(self._PUSH_RATE)   # 실제 푸시 레이트 추정
        self._max_a = None; self._max_c = None
        self._max_laeq = None; self._max_lceq = None
        self._leq_secs = 60  # default 1 min
        self._mutex = QMutex()
        self._panels = []     # 현재 그리드에 배치된 _SplPanel 목록
        self._calib_offset = 0.0
        # ── Smaart식 확장 지표 상태 (push_levels에서 갱신, _update_display에서 읽음)
        self._ema = {}        # EMA 값 (Fast/Slow Z·A·C)
        self._maxv = {}       # EMA 지표별 러닝 최대 (Max 행용)
        self._peak_hold = {}  # Peak / Peak C / FS Peak 홀드값
        self._last_push_t = None

        # ── 저장된 레이아웃 복원 (없으면 4×1 기본 = 기존 모습)
        self._rows, self._cols, self._cells = self._load_layout()
        try:
            self._leq_idx = int(self._main._settings.get('spl_meter', {}).get('leq_idx', 0))
        except Exception:
            self._leq_idx = 0
        self._leq_idx = max(0, min(len(self._PRESETS) - 1, self._leq_idx))
        self._leq_secs = self._PRESETS[self._leq_idx][1]

        # ── 타이틀바(✕ 옆): 상단고정 토글 + 설정(슬라이더). Reset Max는 카드별 버튼으로 이동(2026-06-28).
        self._pin_btn = _PinBtn(); self._pin_btn.setChecked(self._always_top)
        self._pin_btn.setToolTip(_tx('Keep on top'))
        self._pin_btn.clicked.connect(self._toggle_on_top)
        self._set_btn = _SettingsBtn()
        self._set_btn.setToolTip(_tx('Settings'))
        self._set_btn.clicked.connect(self._open_layout_dialog)
        _apply_dark_titlebar(self, resizable=True, aux=[self._pin_btn, self._set_btn])

        self.setStyleSheet(f'SplMeterWindow{{background:{T("bg2")};}}')   # 반전: 창=회색(카드=검정)
        root = QVBoxLayout(self); root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)
        # 레이아웃이 콘텐츠 최소크기로 창을 강제하지 않게 → 사용자가 더 작게 드래그 가능(최소 탐색용)
        root.setSizeConstraint(QVBoxLayout.SetNoConstraint)

        # ── 패널 그리드 컨테이너 (행×열은 _rebuild_grid 에서 채움). 컨트롤은 설정창으로 이동.
        panels_w = QWidget(); panels_w.setStyleSheet(f'background:{T("bg2")};')   # 반전: 그리드 배경=회색
        self._panels_w = panels_w
        self._grid = QGridLayout(panels_w)
        self._grid.setContentsMargins(6, 6, 6, 6); self._grid.setSpacing(6)
        root.addWidget(panels_w, 1)

        self._rebuild_grid()
        self.setMinimumSize(self._min_w(), self._min_h())
        # 기본(처음 열 때) = 최소 크기로 작게 열기. 사용자가 자유롭게 늘릴 수 있음.
        self.resize(self._open_w(), self._open_h())

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._update_display)
        self._timer.start(200)

    # ── 레이아웃 로드/저장 ──────────────────────
    def _load_layout(self):
        try:
            cfg = self._main._settings.get('spl_meter', {})
            rows = int(cfg.get('rows', 4)); cols = int(cfg.get('cols', 1))
            cells = list(cfg.get('cells', self._DEFAULT_CELLS))
        except Exception:
            rows, cols, cells = 4, 1, list(self._DEFAULT_CELLS)
        rows = max(1, min(4, rows)); cols = max(1, min(4, cols))
        cells = self._normalize_cells(cells, rows, cols)
        return rows, cols, cells

    def _normalize_cells(self, cells, rows, cols):
        n = rows * cols
        cells = [(c if c in self._METRICS else None) for c in cells][:n]
        cells += [None] * (n - len(cells))   # 부족분 빈 칸 패딩
        return cells

    def _save_layout(self):
        try:
            self._main._settings['spl_meter'] = {
                'rows': self._rows, 'cols': self._cols, 'cells': self._cells,
                'leq_idx': self._leq_idx, 'on_top': self._always_top}
            _save_settings(self._main._settings)
        except Exception as e:
            _alog.warning(f'SPL 레이아웃 저장 실패: {e}')

    def _toggle_on_top(self):
        """always-on-top 켜고 끄기 — macOS는 네이티브 setLevel(깜빡임 없음), 그 외만 Qt 플래그."""
        self._always_top = not self._always_top
        self._pin_btn.setChecked(self._always_top); self._pin_btn.update()
        if not _apply_on_top(self, self._always_top):
            flags = self.windowFlags()
            flags = (flags | Qt.WindowStaysOnTopHint) if self._always_top else (flags & ~Qt.WindowStaysOnTopHint)
            self.setWindowFlags(flags); self.show()   # 폴백(비-macOS)
        self._save_layout()

    def restyle_theme(self):
        """테마 토글(다크↔라이트) 시 창/그리드 배경 + 다크타이틀바 + 패널 색 재적용."""
        self.setStyleSheet(f'SplMeterWindow{{background:{T("bg2")};}}')   # 반전: 창=회색(카드=검정)
        if hasattr(self, '_panels_w'):
            self._panels_w.setStyleSheet(f'background:{T("bg2")};')   # 반전: 그리드 배경=회색
        bar = getattr(self, '_dark_titlebar', None)
        if bar is not None:
            bar.setStyleSheet(f'#darkTitleBar{{background:{T("bg2")};}}')
            _t = getattr(bar, '_title', None)
            if _t is not None:
                _t.setStyleSheet(f'color:{T("text")};font-size:12px;font-weight:bold;background:transparent;')
        for p in self._panels:
            p.restyle()

    def _chrome_h(self):
        return 12   # 그리드 상하 여백

    def _min_w(self):
        # 최소 크기 탐색용 — 거의 풀어줌(실제 하한은 타이틀바 콘텐츠 자연 최소가 결정)
        return max(40 * self._cols, 80)

    def _min_h(self):
        # 패널 폰트가 자동 축소되므로 아주 작게까지 허용
        return self._chrome_h() + 22 * self._rows

    def _open_w(self):
        # 처음 열 때 컴팩트 너비 — Smaart식 좁고 긴 단열
        return max(150 * self._cols, 160)

    def _open_h(self):
        # 처음 열 때 높이 — 세로로 길게(숫자 큼직 + 위아래 여백)
        return self._chrome_h() + 150 * self._rows

    # ── 그리드 재구성 ───────────────────────────
    def _rebuild_grid(self):
        # 기존 패널 제거
        for p in self._panels:
            self._grid.removeWidget(p); p.setParent(None); p.deleteLater()
        self._panels = []
        for col in range(self._grid.columnCount()): self._grid.setColumnStretch(col, 0)
        for row in range(self._grid.rowCount()):    self._grid.setRowStretch(row, 0)

        self._cells = self._normalize_cells(self._cells, self._rows, self._cols)
        for idx, mid in enumerate(self._cells):
            r, c = divmod(idx, self._cols)
            if mid is None:
                continue
            title, color = self._METRICS[mid]
            if mid == 'clock':
                tc, vc = _clock_colors()
            else:
                tc = vc = color
            pnl = _SplPanel(title, tc, vc, bg_hex='#1C1C1E', border_hex='#38383A',
                            metric_id=mid)
            pnl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            pnl.set_calib_offset(self._calib_offset)
            if mid in ('laeq', 'lceq'):
                pnl.reset_time_requested.connect(self._reset_time)
            if pnl._max_reset_btn is not None:
                pnl.reset_max_requested.connect(lambda m=mid: self._reset_card_max(m))
            self._grid.addWidget(pnl, r, c)
            self._panels.append(pnl)
        for c in range(self._cols): self._grid.setColumnStretch(c, 1)
        for r in range(self._rows): self._grid.setRowStretch(r, 1)

        # 창 최소 크기 — 작게 줄일 수 있도록 (강제 확대 안 함)
        self.setMinimumSize(self._min_w(), self._min_h())
        QTimer.singleShot(0, self._scale_panels)

    def _open_layout_dialog(self):
        leq_labels = [lbl for lbl, _ in self._PRESETS]
        # 측정 소스 목록 — 메인(Spectrum) 페이지의 입력 카드들
        try:
            sources = self._main._spl_source_list()
            cur_src = getattr(self._main, '_spl_source_id', 0)
        except Exception:
            sources, cur_src = None, 0
        dlg = SplLayoutDialog(self._rows, self._cols, self._cells, self._METRICS,
                              leq_labels, self._leq_idx, self,
                              sources=sources, source_id=cur_src)
        if dlg.exec() == QDialog.Accepted:
            self._rows, self._cols, self._cells = dlg.get_layout()
            self._leq_idx = dlg.get_leq_idx()
            self._leq_secs = self._PRESETS[self._leq_idx][1]
            self._rebuild_grid()
            self._scale_panels()
            self._save_layout()
            if sources is not None:
                try: self._main._set_spl_source(dlg.get_source_id())
                except Exception as e: _alog.warning(f'SPL 소스 변경 실패: {e}')

    def push_sample(self, dba, dbc):
        # 하위호환(LEQ 적분 버퍼만). 실제 피드는 push_levels 사용.
        if dba > -100:
            with QMutexLocker(self._mutex):
                self._buf_a.append(_db2e(dba)); self._buf_c.append(_db2e(dbc))

    def push_levels(self, dbz, dba, dbc, fs_peak):
        """Smaart식 확장 지표 입력 — 순간 calibrated Z/A/C 레벨 + 풀스케일 디지털 피크(dBFS).
        Fast(125ms)/Slow(1s) EMA + 피크 홀드를 여기서 계산.
        ※ 호출은 _process_audio(=GUI 스레드, QueuedConnection 경유)에서 옴 — 오디오 콜백 스레드 아님.
          뮤텍스는 _update_display(같은 GUI 스레드)와의 일관성 보호용. 절대 오디오 콜백에서 직접 호출 금지."""
        with QMutexLocker(self._mutex):
            now = time.time()
            self._rate.tick(now)      # 실제 푸시 레이트 갱신
            dt = (now - self._last_push_t) if self._last_push_t else 0.02
            self._last_push_t = now
            dt = min(max(dt, 0.001), 0.5)
            af  = 1.0 - math.exp(-dt / 0.125)   # Fast 125ms
            asw = 1.0 - math.exp(-dt / 1.0)     # Slow 1s

            def _ema(k, x, a):
                v = self._ema.get(k)
                v = x if v is None else v + (x - v) * a
                self._ema[k] = v
                return v

            a_s = _ema('dba', dba, asw);      _ema('dba_fast', dba, af)
            c_s = _ema('dbc', dbc, asw);      _ema('dbc_fast', dbc, af)
            _ema('spl_slow', dbz, asw);       _ema('spl_fast', dbz, af)

            for k in self._EMA_IDS:                      # 러닝 최대 (Max 행)
                v = self._ema.get(k)
                if v is not None and (self._maxv.get(k) is None or v > self._maxv[k]):
                    self._maxv[k] = v

            decay = dt * 6.0                              # 피크 홀드 ~6 dB/s 하강
            def _hold(k, x):
                v = self._peak_hold.get(k)
                self._peak_hold[k] = x if (v is None or x > v) else max(x, v - decay)
            _hold('peak',    fs_peak + self._calib_offset)  # 디지털 피크 → SPL 환산
            _hold('peak_c',  dbc)                            # C가중 최대 홀드(근사)
            _hold('fs_peak', fs_peak)                        # 풀스케일 디지털 피크(dBFS)

            if dba > -100:                                # LEQ 적분 버퍼 = Slow A/C
                self._buf_a.append(_db2e(a_s)); self._buf_c.append(_db2e(c_s))

    def _update_display(self):
        _glance_chrome_update(self)   # 마우스 밖이면 카드만(타이틀바 숨김)
        # 시계 카드는 오디오 입력과 무관하게 항상 현재 시각(24h HH:MM) 갱신
        now = time.strftime('%H:%M')
        for pnl in self._panels:
            if pnl.metric_id == 'clock':
                pnl.set_clock(now)

        with QMutexLocker(self._mutex):
            _len = len(self._buf_a)
            n = min(_len, self._rate.window_n(self._leq_secs))   # 실측 레이트 기준
            # 링버퍼 — 창 길이(n)에만 비례. 예전엔 list(deque)가 버퍼 전체를 먼저 복사했다.
            arr_a = self._buf_a.last(n) if n else None
            arr_c = self._buf_c.last(n) if n else None
            ema   = dict(self._ema); maxv = dict(self._maxv); peaks = dict(self._peak_hold)
        self._update_timebar(_len)

        laeq = lceq = None
        if n:
            laeq = _e2leq(arr_a)
            lceq = _e2leq(arr_c)
            if self._max_laeq is None or laeq > self._max_laeq: self._max_laeq = laeq
            if self._max_lceq is None or lceq > self._max_lceq: self._max_lceq = lceq

        value_for = dict(ema); value_for.update(peaks)
        value_for['laeq'] = laeq; value_for['lceq'] = lceq
        max_for = dict(maxv)
        max_for['laeq'] = self._max_laeq; max_for['lceq'] = self._max_lceq

        for pnl in self._panels:
            mid = pnl.metric_id
            if mid == 'clock':
                continue   # 시계는 위에서 별도 갱신
            v = value_for.get(mid)
            if v is None:
                continue
            pnl.set_value(v, max_for.get(mid))

    def set_calib_offset(self, offset):
        self._calib_offset = offset
        for pnl in self._panels:
            pnl.set_calib_offset(offset)

    def _reset_max(self):
        with QMutexLocker(self._mutex):
            self._maxv.clear(); self._peak_hold.clear()
            self._max_a = self._max_c = self._max_laeq = self._max_lceq = None
        for pnl in self._panels:
            pnl.reset()

    def _reset_card_max(self, mid):
        """단일 카드 Max/Peak 홀드 리셋 — 카드별 리셋 버튼(전역 Reset Max 대체)."""
        with QMutexLocker(self._mutex):
            self._maxv.pop(mid, None)
            self._peak_hold.pop(mid, None)
            if mid == 'laeq': self._max_laeq = None
            if mid == 'lceq': self._max_lceq = None
        for pnl in self._panels:
            if pnl.metric_id == mid:
                pnl.reset()

    def _update_timebar(self, total_len):
        """버퍼에 쌓인 시간으로 LEQ 카드(laeq/lceq)의 진행 미터 갱신 (숫자 없음)."""
        win = max(1, self._leq_secs)
        p = (total_len / self._rate.hz) / win
        for pnl in self._panels:
            pnl.set_time_progress(p)

    def _reset_time(self):
        """LEQ 시간 리셋 — 적분 버퍼 비워 진행 미터/LEQ를 0부터 다시 시작."""
        with QMutexLocker(self._mutex):
            self._buf_a.clear(); self._buf_c.clear()
        self._max_laeq = None; self._max_lceq = None   # 적분 재시작 시 옛 Max 표시 안 남게
        self._update_timebar(0)

    def _scale_panels(self):
        # 각 카드가 종횡비를 고정한 채 회색 배경+글자를 한 비율로 스케일 (카드가 알아서 처리)
        for pnl in self._panels:
            if pnl.width() <= 0 or pnl.height() <= 0:
                continue
            pnl._relayout()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._scale_panels()

    def showEvent(self, e):
        super().showEvent(e)
        if not self._timer.isActive(): self._timer.start(200)
        self._scale_panels()
        # 풀스크린 메인과 같은 화면일 때만 자식부착, 그 외엔 독립창 → 외부모니터 이동 가능.
        self._main._float_sync_attach(self)
        _apply_on_top(self, self._always_top)   # macOS 네이티브 레벨

    def moveEvent(self, e):
        super().moveEvent(e)
        # 드래그로 화면을 넘나들면 부착/분리 재동기화(풀스크린 위 ↔ 외부 모니터)
        if self._main.isFullScreen():
            self._main._float_sync_attach(self)

    def closeEvent(self, e):
        self._timer.stop()
        if hasattr(self._main, 'spl_meter_win'):
            self._main.spl_meter_win = None
        self.deleteLater()          # 부모에 남는 고아 인스턴스 방지(버퍼 동반)
        e.accept()


