"""UI 위젯 — 작은 커스텀 버튼/배지 (v2.0 분해, 동작 0 변경)."""
import time
from PyQt5.QtWidgets import (QPushButton, QLabel, QWidget, QSplitter, QSplitterHandle, QFrame,
    QHBoxLayout, QVBoxLayout, QApplication, QComboBox, QScrollArea, QScrollBar, QAbstractButton, QCheckBox, QGridLayout, QStyle, QStyleOptionComboBox, QStylePainter, QLineEdit, QMenu, QColorDialog, QDoubleSpinBox, QSizePolicy, QSizeGrip)
from PyQt5.QtGui import QColor, QPainter, QPainterPath, QPen, QPolygonF, QFont, QBrush, QLinearGradient, QPalette, QIcon
from PyQt5.QtCore import Qt, QPointF, QRectF, pyqtSignal, QPoint, QSize, QTimer, QEvent, QObject
from spectra.core.config import T, is_dark, theme, delay_unit, ms_to_m
from spectra.core.logging_diag import _alog, _diag
from spectra.ui.colors import _SPECTRA_GRAD_QSS, _spectra_mark
from spectra.ui.colors import _MC_COLORS
from spectra.ui.icons import _icon, _icon_pm, _led_power_pm, _n2_hover_ss, _n2_icon_color, _n2_led_color, _n2_tab_ss
from spectra.core.i18n import _tx
from spectra.ui.draw import (METER_DB_MIN, METER_YELLOW_DB, METER_RED_DB, METER_PEAK_DECAY, METER_TAU_ATTACK, METER_TAU_RELEASE, _draw_zone_meter_h)
from spectra.ui.colors import _TF_SEL_GRAD_STOPS
from spectra.ui.draw import _tf_card_palette
from spectra.ui.tokens import FONT_FAMILY, FS_BODY, FS_SM, FS_XS, FS_LG, RADIUS_SM, PAD_SM, CF_ANNO, CF_AXIS, CF_TINY, ss_text, _qfont, _n2_caps_font, _n2_mono_font, _n2_val_font


class _SettingsBtn(QPushButton):
    """타이틀바용 설정 버튼 — 누르면 설정창 오픈. 톱니바퀴(기어) 아이콘을 직접 그림(2026-06-28 정제)."""
    def __init__(self):
        super().__init__()
        self.setFixedSize(26, 24); self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet('QPushButton{border:none;background:transparent;border-radius:6px;}'
                           'QPushButton:hover{background:rgba(255,255,255,30);}')

    def paintEvent(self, e):
        super().paintEvent(e)   # hover 배경
        col = QColor('#9A9AA0')
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        p.translate(13.0, 12.0)                       # 버튼 중앙
        p.setPen(Qt.NoPen); p.setBrush(col)
        for i in range(8):                            # 톱니 8개 (꽉 찬 기어)
            p.save(); p.rotate(i * 45)
            p.drawRoundedRect(QRectF(-1.5, -8.4, 3.0, 4.4), 1.1, 1.1)
            p.restore()
        p.drawEllipse(QPointF(0, 0), 5.6, 5.6)        # 기어 몸통
        p.setBrush(QColor(T('bg2')))                  # 가운데 구멍 = 타이틀바 배경색
        p.drawEllipse(QPointF(0, 0), 2.3, 2.3)
        p.end()


class _PinBtn(QPushButton):
    """타이틀바용 always-on-top 토글 — 기울인 압정(SF pin.fill) 아이콘(2026-06-28 정제).
    ON=브랜드 액센트 채움 / OFF=회색 외곽."""
    def __init__(self):
        super().__init__()
        self.setCheckable(True)
        self.setFixedSize(26, 24); self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet('QPushButton{border:none;background:transparent;border-radius:6px;}'
                           'QPushButton:hover{background:rgba(255,255,255,30);}')

    def paintEvent(self, e):
        super().paintEvent(e)   # hover 배경
        on = self.isChecked()
        col = QColor(T('accent')) if on else QColor('#9A9AA0')
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        # 기울인 압정 — 24x24 좌표를 버튼 중앙(13,12)에 38° 회전 배치
        p.translate(13.0, 12.0); p.rotate(38); p.translate(-12.0, -12.0)
        path = QPainterPath(); path.setFillRule(Qt.WindingFill)
        path.addRoundedRect(QRectF(7.0, 3.2, 10.0, 4.6), 2.0, 2.0)   # 머리(캡)
        path.addRect(QRectF(10.3, 7.4, 3.4, 2.8))                     # 목
        path.addPolygon(QPolygonF([QPointF(8.6, 10.0), QPointF(15.4, 10.0), QPointF(12.0, 19.2)]))  # 바늘
        path.closeSubpath()
        if on:
            p.setPen(Qt.NoPen); p.setBrush(col); p.drawPath(path)
        else:
            pen = QPen(col, 1.7); pen.setJoinStyle(Qt.RoundJoin)
            p.setPen(pen); p.setBrush(Qt.NoBrush); p.drawPath(path)
        p.end()


class _CollapseBtn(QPushButton):
    """툴바(메뉴) 접기 토글 — 셰브론 직접 페인트. 펼침=▴(접기), 접힘=▾(펼치기)."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True); self.setFixedSize(30, 24)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip('Hide / show toolbar')
        self.setStyleSheet('QPushButton{background:transparent;border:none;}')
    def paintEvent(self, e):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        c = QColor(T('accent'))
        if self.underMouse(): c = c.lighter(120)
        p.setPen(QPen(c, 2.0, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        cx, cy, s = self.width()/2, self.height()/2, 5
        if self.isChecked():   # 접힌 상태 → ▾ (클릭하면 펼침)
            p.drawLine(int(cx-s), int(cy-2), int(cx), int(cy+3))
            p.drawLine(int(cx), int(cy+3), int(cx+s), int(cy-2))
        else:                  # 펼친 상태 → ▴ (클릭하면 접힘)
            p.drawLine(int(cx-s), int(cy+2), int(cx), int(cy-3))
            p.drawLine(int(cx), int(cy-3), int(cx+s), int(cy+2))
        p.end()


class _ComplianceBadge(QWidget):
    """라우드니스 COMPLIANCE 상태 원형 배지 — 안티앨리어싱 원(틴트 채움 + 컬러 링 + 글리프).
    QLabel+CSS border-radius의 테두리 계단현상을 피하려 QPainter로 직접 그림."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(68, 68)
        self._col = QColor(T('text_dim'))
        self.glyph = '—'

    def set_state(self, col, glyph='—'):
        self._col = QColor(col); self.glyph = glyph
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = self._col
        d = min(self.width(), self.height()) - 4   # 2px 링 두께 여유
        x = (self.width() - d) / 2.0; y = (self.height() - d) / 2.0
        rect = QRectF(x, y, d, d)
        fill = QColor(c); fill.setAlpha(30)
        p.setPen(Qt.NoPen); p.setBrush(fill); p.drawEllipse(rect)
        ring = QColor(c); ring.setAlpha(160)
        p.setBrush(Qt.NoBrush); p.setPen(QPen(ring, 2.0)); p.drawEllipse(rect)
        f = QFont(FONT_FAMILY); f.setPixelSize(30); f.setBold(True); p.setFont(f)
        p.setPen(c); p.drawText(self.rect(), Qt.AlignCenter, self.glyph)
        p.end()


class _DashedAddButton(QPushButton):
    """점선 테두리 'Add' 버튼. Qt QSS의 dashed 보더는 둥근 모서리에서
    점선이 끊겨 보여서, QPainter 로 직접 균일한 점선 라운드 사각형을 그린다."""
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self._hover = False
        self.setStyleSheet('background:transparent;border:none;')

    def enterEvent(self, e):
        self._hover = True; self.update(); super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False; self.update(); super().leaveEvent(e)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        col = QColor(T('accent')) if self._hover else QColor(T('border'))
        pen = QPen(col, 1.0)
        pen.setStyle(Qt.CustomDashLine)
        pen.setDashPattern([4, 4])       # 4px 선 / 4px 간격
        pen.setCapStyle(Qt.FlatCap)
        p.setPen(pen); p.setBrush(Qt.NoBrush)
        r = float(RADIUS_SM)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.drawRoundedRect(rect, r, r)
        txt_col = QColor(T('accent')) if self._hover else QColor(T('text_dim'))
        p.setPen(txt_col)
        f = self.font(); f.setPixelSize(FS_BODY); p.setFont(f)
        p.drawText(self.rect(), Qt.AlignCenter, self.text())
        p.end()


class _SplMeterBtn(QPushButton):
    """Open SPL Meter — "dB" 텍스트 아이콘(SPL=데시벨). LEVEL 섹션 막대 아이콘과 중복 회피."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(28, 28)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(_tx('Open SPL Meter'))

    def enterEvent(self, e): self.update()
    def leaveEvent(self, e): self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        # 조용한 유틸 버튼: 기본 투명 → hover/press 때만 옅은 배경
        hot = self.underMouse() or self.isDown()
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(T('bg3')) if hot else QColor(0, 0, 0, 0))
        p.drawRoundedRect(QRectF(self.rect()), 5, 5)

        # Icon: "dB" — 기본 dim 회색 → hover/press 소프트블루(값 톤과 일치)
        col = QColor('#9DB7E0') if hot else QColor(T('text_dim'))
        f = QFont(FONT_FAMILY); f.setPixelSize(13); f.setBold(True); p.setFont(f)
        p.setPen(col)
        p.drawText(self.rect(), Qt.AlignCenter, 'dB')
        p.end()


class _SplAlarmBtn(QPushButton):
    """LEVEL 패널 헤더용 — SPL 알람 창 열기. 미니 신호등(3구) 아이콘."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(28, 28)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(_tx('Open SPL Alarm'))

    def enterEvent(self, e): self.update()
    def leaveEvent(self, e): self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        # 조용한 유틸 버튼: 기본 투명 → hover/press 때만 옅은 배경
        hot = self.underMouse() or self.isDown()
        p.setPen(Qt.NoPen); p.setBrush(QColor(T('bg3')) if hot else QColor(0, 0, 0, 0))
        p.drawRoundedRect(QRectF(self.rect()), 5, 5)

        # 미니 신호등 — 기본 dim 회색(틀+점) → hover 소프트블루 틀 + 살짝 죽인 컬러 점(알람 의미)
        cx = self.width() / 2.0
        hw, hh = 11.0, 18.0
        hx = cx - hw / 2.0; hy = (self.height() - hh) / 2.0
        housing = QColor('#9DB7E0') if hot else QColor(T('text_dim'))
        p.setPen(QPen(housing, 1.4)); p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(hx, hy, hw, hh), 3.2, 3.2)
        if hot:
            cols = (QColor(52, 199, 89, 210), QColor(255, 214, 10, 210), QColor(255, 69, 58, 210))
        else:
            d = QColor(T('text_dim')); cols = (d, d, d)
        r = 2.1
        for i, c in enumerate(cols):
            dy = hy + hh * (0.24 + i * 0.26)
            p.setBrush(c); p.setPen(Qt.NoPen)
            p.drawEllipse(QPointF(cx, dy), r, r)
        p.end()


class _CheckBtn(QPushButton):
    """Checkable QPushButton — CSS :checked border는 macOS에서 클리핑되므로
    paintEvent에서 QPainter로 직접 테두리를 그린다."""
    def __init__(self, text='', parent=None):
        super().__init__(text, parent)
        self.setCheckable(True)

    # 활성 필은 스타일시트 :checked{background}로 처리(셀 폭 꽉 채움) — 네이티브 체크
    # 렌더가 텍스트를 좁게 감싸던 문제 회피. paintEvent 커스텀 드로잉 없음.


class _SegBtn(QPushButton):
    """세그먼트 컨트롤 내부 버튼 — 활성 시 블루 채움(직접 페인트). 모던 툴바용."""
    def __init__(self, text='', parent=None):
        super().__init__(text, parent)
        self.setCheckable(True); self.setFlat(True)
        self.setCursor(Qt.PointingHandCursor)

    def paintEvent(self, e):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        on = self.isChecked(); en = self.isEnabled()
        if on:
            ac = QColor(T('accent')); ac.setAlpha(70)
            p.setBrush(ac); p.setPen(Qt.NoPen)
            p.drawRoundedRect(self.rect().adjusted(1, 2, -1, -2), 6, 6)
        col = (T('text') if on else T('text_dim')) if en else T('border')
        p.setPen(QColor(col))
        f = self.font(); f.setBold(on); p.setFont(f)
        p.drawText(self.rect(), Qt.AlignCenter, self.text())
        p.end()


class _DrawerToggleBtn(QPushButton):
    """Logic X 스타일 캡처 드로어 토글 버튼.
    두 개의 수평 pill을 그려 드로어 표시/숨김을 나타낸다."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setFixedSize(38, 30)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(_tx('Show/hide Capture panel'))

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        checked = self.isChecked()
        ac = QColor(T('accent'))
        if checked:
            fill = QColor(ac.red(), ac.green(), ac.blue(), 45)
            border = QColor(ac.red(), ac.green(), ac.blue(), 160)
            pill_c = QColor(ac.red(), ac.green(), ac.blue(), 230)
        else:
            fill = QColor(255, 255, 255, 18)
            border = QColor(255, 255, 255, 40)
            pill_c = QColor(T('text_dim'))
        p.setBrush(fill)
        p.setPen(QPen(border, 1.0))
        p.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), 7, 7)
        # 아이콘: 사이드 패널 토글 (오른쪽 칸 채운 패널) — 캡처 패널이 우측이라 직관적
        iw, ih = 18, 14; ix = (w - iw) // 2; iy = (h - ih) // 2
        p.setPen(QPen(pill_c, 1.3)); p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(ix, iy, iw, ih), 3, 3)
        divx = ix + iw * 0.58
        p.setPen(Qt.NoPen); p.setBrush(pill_c)
        p.drawRoundedRect(QRectF(divx, iy + 1.5, ix + iw - divx - 1.5, ih - 3), 2, 2)
        p.end()


class _RightPanelToggleBtn(_DrawerToggleBtn):
    """우측 패널(LEVEL/INFO/INPUT · TF rp) 표시/숨김 토글 — 캡처 드로어 토글과 동일 스타일."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setToolTip(_tx('Show/hide right panel'))


class _ToolbarToggleBtn(QPushButton):
    """툴바(컨트롤 바) 접기/펴기 토글 — 탭바에 위치. 셰브론(표시=⌃접기 / 숨김=⌄펴기)."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True); self.setChecked(True)
        self.setFixedSize(30, 28); self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(_tx('Collapse/expand toolbar'))
        self.setStyleSheet('QPushButton{border:none;background:transparent;border-radius:6px;}'
                           'QPushButton:hover{background:rgba(255,255,255,28);}')

    def paintEvent(self, e):
        super().paintEvent(e)   # hover 배경
        shown = self.isChecked()
        col = QColor(T('accent')) if shown else QColor(T('text_dim'))
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        pen = QPen(col, 1.8); pen.setCapStyle(Qt.RoundCap); pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen); p.setBrush(Qt.NoBrush)
        cx, cy = self.width()/2, self.height()/2; d = 4.5
        if shown:   # ⌃ 접기
            p.drawPolyline(QPolygonF([QPointF(cx-d, cy+d*0.6), QPointF(cx, cy-d*0.6), QPointF(cx+d, cy+d*0.6)]))
        else:       # ⌄ 펴기
            p.drawPolyline(QPolygonF([QPointF(cx-d, cy-d*0.6), QPointF(cx, cy+d*0.6), QPointF(cx+d, cy-d*0.6)]))
        p.end()


class _MiniVU(QWidget):
    clicked = pyqtSignal()

    def __init__(self):
        super().__init__(); self.setFixedSize(58, 108)
        self._db=-80.0; self._pk=-80.0; self._pk_hold=0

    def mousePressEvent(self, e): self.clicked.emit(); super().mousePressEvent(e)

    def set_rms(self,db):
        self._db=db; self._pk_hold+=1
        if db>self._pk or self._pk_hold>40: self._pk=db; self._pk_hold=0
        self.update()

    def paintEvent(self,ev):
        p=QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        W=self.width(); H=self.height()
        DB_MIN=-60.0; DB_MAX=0.0; rng=DB_MAX-DB_MIN

        # 텍스트 영역 높이 고정 (숫자 18px + dBFS 14px + 여백 4px = 36px)
        TEXT_H = 36
        bx=4; bw=W-8; by=4; bh=H-by-TEXT_H-2  # 바 영역

        # 테두리
        p.setPen(QPen(QColor(T('border')), 1)); p.setBrush(Qt.NoBrush)
        p.drawRect(bx, by, bw-1, bh-1)

        # 레벨 fill
        p.setPen(Qt.NoPen)
        fill=max(0.0,min(1.0,(self._db-DB_MIN)/rng))
        fh=int(bh*fill)
        if fh>0:
            fy=by+bh-fh
            c=T('red') if self._db>-6 else T('yellow') if self._db>-18 else T('accent')
            g=QLinearGradient(0,fy,0,by+bh)
            g.setColorAt(0,QColor(T('accent'))); g.setColorAt(1,QColor(c))
            p.setBrush(QBrush(g)); p.drawRect(bx+1,fy,bw-2,fh)

        # 피크 홀드 라인
        pk=max(0.0,min(1.0,(self._pk-DB_MIN)/rng))
        py_=int(by+bh*(1.0-pk))
        p.setPen(QPen(QColor(T('yellow')),1)); p.drawLine(bx+1,py_,bx+bw-2,py_)

        # 텍스트 (바 아래 고정 영역)
        txt_top = by + bh + 4
        c2=T('red') if self._db>-6 else T('yellow') if self._db>-18 else T('accent')
        p.setFont(_qfont(11, True)); p.setPen(QColor(c2))
        p.drawText(0, txt_top, W, 18, Qt.AlignHCenter|Qt.AlignVCenter, f'{self._db:.0f}')
        p.setFont(_qfont(CF_ANNO)); p.setPen(QColor(T('text_dim')))
        p.drawText(0, txt_top+18, W, 14, Qt.AlignHCenter|Qt.AlignVCenter, 'dBFS')
        p.end()


class _HorizBarVU(QWidget):
    """Smaart 스타일 수평 레벨 바."""
    def __init__(self):
        super().__init__(); self.setFixedHeight(8)
        self._db = -80.0; self._pk = -80.0; self._pk_hold = 0; self._last_t = 0.0

    def set_rms(self, db, peak_db=None):
        # 시간 기반 탄도(빠른 어택/실시간 릴리즈) — 업데이트율 무관하게 일정한 실시간 반응
        now = time.monotonic()
        dt = (now - self._last_t) if self._last_t else 0.0
        self._last_t = now
        tau = METER_TAU_ATTACK if db > self._db else METER_TAU_RELEASE
        a = (1.0 - math.exp(-dt / tau)) if dt > 0 else 1.0
        self._db += (db - self._db) * a
        # peak tick: 실제 peak(있으면) 즉시 올리고, 시간기반 감쇠로 채움(_db)까지 매끄럽게 따라내림
        pk = peak_db if peak_db is not None else db
        if pk > self._pk: self._pk = pk
        elif dt > 0: self._pk = max(self._pk - METER_PEAK_DECAY * dt, self._db)
        self.update()

    def reset(self):
        self._db = -80.0; self._pk = -80.0; self._pk_hold = 0; self._last_t = 0.0; self.update()

    def paintEvent(self, ev):
        # _MiniMeterBar(Spectrum 카드)와 동일한 모던 룩: 둥근 트랙 + 둥근 채움 + peak tick.
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        W = self.width(); H = self.height(); rr = H / 2.0
        DB_MIN = METER_DB_MIN; DB_MAX = 0.0; rng = DB_MAX - DB_MIN
        bg = QColor(T('bg')); d = -20 if (not is_dark()) else 14   # 라이트 near-white → 어둡게
        track = QColor(max(0, min(bg.red()+d, 255)), max(0, min(bg.green()+d, 255)), max(0, min(bg.blue()+d+2, 255)))
        p.setPen(Qt.NoPen); p.setBrush(track); p.drawRoundedRect(QRectF(0, 0, W, H), rr, rr)
        # 위치 기반 green/yellow/red 구간 채움 (M4/Smaart 사다리)
        _draw_zone_meter_h(p, W, H, self._db, DB_MIN, DB_MAX)
        # peak tick(흰색 바) 제거 — TF 카드 미터는 RMS 채움만 (사용자 요청 2026-06-26)
        p.end()


class _GradSplitterHandle(QSplitterHandle):
    """카드 사이 거터 handle — 거터색 + 옅은 SPECTRA 시그니처 그라디언트 1px 라인(브랜드 속삭임).
    그라디언트는 handle 폭 바뀔 때만 재생성 캐시(매프레임 생성 금지)."""
    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), _tf_card_palette()[0])   # 거터색
        if self.orientation() == Qt.Vertical:            # 세로 스플리터 → 가로 handle
            w = self.width()
            if getattr(self, '_grad_w', None) != w or getattr(self, '_grad', None) is None:
                g = QLinearGradient(0.0, 0.0, float(w), 0.0)
                n = len(_TF_SEL_GRAD_STOPS) - 1
                for i, c in enumerate(_TF_SEL_GRAD_STOPS):
                    q = QColor(c); q.setAlpha(60); g.setColorAt(i / n, q)
                self._grad = g; self._grad_w = w
            p.setRenderHint(QPainter.Antialiasing, True)
            y = int(self.height() / 2)
            p.setPen(QPen(QBrush(self._grad), 1.0))
            p.drawLine(8, y, w - 8, y)
        p.end()

class _CardSplitter(QSplitter):
    """TF 3분석 카드 스플리터 — 거터에 옅은 그라디언트 경계선(_GradSplitterHandle)."""
    def createHandle(self):
        return _GradSplitterHandle(self.orientation(), self)


class DropdownPopup(QFrame):
    item_selected = pyqtSignal(int)

    def __init__(self, combo):
        super().__init__(None, Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.setAutoFillBackground(True)
        pal = self.palette()
        pal.setColor(self.backgroundRole(), QColor(T('bg2')))
        self.setPalette(pal)
        self.setObjectName('popup')
        self.setStyleSheet(
            f'QFrame#popup {{ background:{T("bg2")}; border:1px solid {T("accent")}; border-radius:12px; }}'
        )
        from PyQt5.QtWidgets import QScrollArea
        outer = QVBoxLayout(self); outer.setContentsMargins(6, 6, 6, 6); outer.setSpacing(0)
        self._scroll = QScrollArea(); self._scroll.setWidgetResizable(True); self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet(
            'QScrollArea{background:transparent;border:none;}'
            'QScrollBar:vertical{width:6px;background:transparent;margin:2px;}'
            f'QScrollBar::handle:vertical{{background:{T("border")};border-radius:3px;min-height:24px;}}'
            'QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}')
        inner = QWidget(); inner.setStyleSheet('background:transparent;')
        lay = QVBoxLayout(inner); lay.setContentsMargins(2, 2, 2, 2); lay.setSpacing(0)

        n = combo.count()
        for i in range(n):
            label = combo.itemText(i)
            selected = (i == combo.currentIndex())
            btn = QPushButton(label)
            btn.setFlat(True)
            btn.setStyleSheet(
                f'QPushButton {{'
                f'  background:{"rgba(78,125,240,70)" if selected else "transparent"};'
                f'  color:{T("accent") if selected else T("text")};'
                f'  border:none; border-radius:7px;'
                f'  padding:6px 16px; font-size:11px; font-weight:{"bold" if selected else "normal"};'
                f'  text-align:left; min-height:26px;'
                f'}}'
                f'QPushButton:hover {{ background:rgba(78,125,240,30); color:{T("text")}; }}'
            )
            btn.mousePressEvent = lambda e, idx=i: self._pick(idx)
            lay.addWidget(btn)
            if i < n - 1:
                sep = QFrame(); sep.setFrameShape(QFrame.HLine); sep.setFixedHeight(1)
                sep.setStyleSheet(f'background:{T("border")}; border:none;')
                lay.addWidget(sep)
        self._scroll.setWidget(inner); outer.addWidget(self._scroll)
        self._content = inner

    def sizeHint(self):
        s = self._content.sizeHint()
        from PyQt5.QtCore import QSize
        return QSize(s.width() + 20, s.height() + 14)

    def _pick(self, idx):
        self.item_selected.emit(idx)
        self.close()


class _N2Select(QFrame):
    """RoundComboBox 드롭인 대체 — [아이콘][CAPS라벨][값] 테두리리스, hover, 클릭=드롭다운.
    QComboBox 툴바 사용 API 제공: addItem/addItems/setCurrentIndex/currentIndex/currentData/
    currentText/count/itemText/itemData/clear/setCurrentText + currentIndexChanged 시그널."""
    currentIndexChanged = pyqtSignal(int)
    _align_center = False   # 호환용(무시)

    def __init__(self, icon_name=None, label='', mono=False, parent=None):
        super().__init__(parent)
        self._icon_name = icon_name; self._label_txt = label; self._mono = mono
        self._items = []          # [(text, data), ...]
        self._idx = -1
        self._active_popup = None
        self.setObjectName('n2cell'); self.setStyleSheet(_n2_hover_ss('n2cell'))
        self.setCursor(Qt.PointingHandCursor); self.setAttribute(Qt.WA_Hover, True)
        h = QHBoxLayout(self); h.setContentsMargins(10, 0, 11, 0); h.setSpacing(7)
        self._icl = None; self._lbl = None
        if icon_name:
            self._icl = QLabel(); self._icl.setFixedSize(16, 16); self._icl.setStyleSheet('background:transparent;')
            self._icl.setPixmap(_icon_pm(icon_name, 16, _n2_icon_color())); h.addWidget(self._icl)
        if label:
            self._lbl = QLabel(label); self._lbl.setFont(_n2_caps_font())
            self._lbl.setStyleSheet(f'color:{T("text_dim")};background:transparent;'); h.addWidget(self._lbl)
        self._val = QLabel('')
        self._val.setFont(_n2_mono_font() if mono else _n2_val_font())
        self._val.setStyleSheet(f'color:{T("text")};background:transparent;')
        h.addWidget(self._val)

    # --- QComboBox 호환 API ---
    def addItem(self, text, data=None):
        self._items.append((text, data))
        if self._idx < 0:
            self._idx = 0; self._val.setText(text)
    def addItems(self, texts):
        for t in texts: self.addItem(t)
    def count(self): return len(self._items)
    def itemText(self, i): return self._items[i][0] if 0 <= i < len(self._items) else ''
    def itemData(self, i): return self._items[i][1] if 0 <= i < len(self._items) else None
    def currentIndex(self): return self._idx
    def currentText(self): return self.itemText(self._idx)
    def currentData(self): return self.itemData(self._idx)
    def clear(self): self._items = []; self._idx = -1; self._val.setText('')
    def setCurrentText(self, txt):
        for i, (t, _d) in enumerate(self._items):
            if t == txt: self.setCurrentIndex(i); return
    def setCurrentIndex(self, i):
        if not (0 <= i < len(self._items)): return
        changed = (i != self._idx)
        self._idx = i; self._val.setText(self.currentText())
        if changed: self.currentIndexChanged.emit(i)
    def setSizeAdjustPolicy(self, *a):  # 호환용 no-op
        pass
    def _pick(self, i):
        if 0 <= i < len(self._items):
            changed = (i != self._idx)
            self._idx = i; self._val.setText(self.currentText())
            if changed: self.currentIndexChanged.emit(i)

    def mousePressEvent(self, e):
        if self._items: self._show_popup()
        super().mousePressEvent(e)
    def _show_popup(self):
        popup = DropdownPopup(self)   # count()/itemText()/currentIndex() 사용
        popup.item_selected.connect(self._pick)
        popup.adjustSize()
        w = max(self.width(), popup.sizeHint().width()); ph = popup.sizeHint().height()
        gt = self.mapToGlobal(QPoint(0, 0))
        scr = (QApplication.screenAt(gt) if hasattr(QApplication, 'screenAt') else None) or QApplication.primaryScreen()
        avail = scr.availableGeometry()
        y = gt.y() + self.height() + 2
        if y + ph + 4 > avail.bottom(): y = gt.y() - ph - 2
        x = gt.x()
        if x + w > avail.x() + avail.width(): x = avail.x() + avail.width() - w
        if x < avail.x(): x = avail.x()
        popup.resize(w, ph); popup.move(x, y)
        self._active_popup = popup
        QTimer.singleShot(0, popup.show)

    def restyle(self):
        self.setStyleSheet(_n2_hover_ss('n2cell'))
        if self._icl: self._icl.setPixmap(_icon_pm(self._icon_name, 16, _n2_icon_color()))
        if self._lbl: self._lbl.setStyleSheet(f'color:{T("text_dim")};background:transparent;')
        self._val.setStyleSheet(f'color:{T("text")};background:transparent;')


class _N2Button(QFrame):
    """액션 버튼(Reset/Capture/Color/Start 등) — [아이콘][라벨?][텍스트], 테두리리스+hover. clicked 시그널."""
    clicked = pyqtSignal()

    def __init__(self, icon_name=None, text='', label='', accent_icon=False, mono=False, parent=None):
        super().__init__(parent)
        self._icon_name = icon_name; self._accent_icon = accent_icon
        self.setObjectName('n2cell'); self.setStyleSheet(_n2_hover_ss('n2cell'))
        self.setCursor(Qt.PointingHandCursor); self.setAttribute(Qt.WA_Hover, True)
        h = QHBoxLayout(self); h.setContentsMargins(11, 0, 12, 0); h.setSpacing(7)
        self._icl = None
        if icon_name:
            self._icl = QLabel(); self._icl.setFixedSize(16, 16); self._icl.setStyleSheet('background:transparent;')
            self._icl.setPixmap(_icon_pm(icon_name, 16, T('accent') if accent_icon else _n2_icon_color())); h.addWidget(self._icl)
        self._lbl = None
        if label:
            self._lbl = QLabel(label); self._lbl.setFont(_n2_caps_font())
            self._lbl.setStyleSheet(f'color:{T("text_dim")};background:transparent;'); h.addWidget(self._lbl)
        self._txt = None
        if text:
            self._txt = QLabel(text); self._txt.setFont(_n2_mono_font() if mono else _n2_val_font(12, QFont.DemiBold))
            self._txt.setStyleSheet(f'color:{T("text")};background:transparent;'); h.addWidget(self._txt)
    def setText(self, t):
        if self._txt: self._txt.setText(t)
    def set_running(self, playing):
        """트랜스포트 실행상태 — 아이콘 play/stop + 색(정지=레드) 전환. 텍스트는 호출부가 지정."""
        self._running_state = bool(playing)   # restyle(테마 토글)이 red/stop 복원할 수 있게 기억
        self._icon_name = 'stop' if playing else 'play'; self._accent_icon = True
        col = T('red') if playing else T('accent')
        if self._icl: self._icl.setPixmap(_icon_pm(self._icon_name, 16, col))
        if self._txt: self._txt.setStyleSheet(f'color:{T("red") if playing else T("text")};background:transparent;')
    def set_active(self, on):
        """잠금/활성 표시 — 값·아이콘을 액센트색으로 (spec_db_btn 잠금 등)."""
        self._active = bool(on)
        col = T('accent') if on else T('text')
        if self._txt: self._txt.setStyleSheet(f'color:{col};background:transparent;')
        if self._icl and not self._accent_icon:
            self._icl.setPixmap(_icon_pm(self._icon_name, 16, T('accent') if on else _n2_icon_color()))
    def mousePressEvent(self, e):
        e.accept()   # press를 accept해야 release(클릭)가 이 위젯으로 전달됨
    def mouseReleaseEvent(self, e):
        if self.rect().contains(e.pos()): self.clicked.emit()
        super().mouseReleaseEvent(e)
    def restyle(self):
        self.setStyleSheet(_n2_hover_ss('n2cell'))
        _act = getattr(self, '_active', False)
        _run = getattr(self, '_running_state', False)   # 실행 중 트랜스포트 = red/stop 유지(테마 토글에도)
        if self._icl:
            _icol = T('red') if _run else (T('accent') if (self._accent_icon or _act) else _n2_icon_color())
            self._icl.setPixmap(_icon_pm(self._icon_name, 16, _icol))
        if self._lbl: self._lbl.setStyleSheet(f'color:{T("text_dim")};background:transparent;')
        if self._txt:
            _tcol = T('red') if _run else (T('accent') if _act else T('text'))
            self._txt.setStyleSheet(f'color:{_tcol};background:transparent;')


class _N2Toggle(QFrame):
    """토글(Peak/+Spectro 등) — [아이콘][라벨?][텍스트][LED]. checkable QPushButton 호환:
    setChecked/isChecked/clicked/toggled. LED·아이콘색이 상태 반영."""
    clicked = pyqtSignal()
    toggled = pyqtSignal(bool)

    def __init__(self, icon_name=None, text='', label='', on_text=None, off_text=None, parent=None):
        super().__init__(parent)
        self._icon_name = icon_name; self._checked = False
        self._on_text = on_text; self._off_text = off_text
        self.setObjectName('n2cell'); self.setStyleSheet(_n2_hover_ss('n2cell'))
        self.setCursor(Qt.PointingHandCursor); self.setAttribute(Qt.WA_Hover, True)
        h = QHBoxLayout(self); h.setContentsMargins(11, 0, 11, 0); h.setSpacing(7)
        self._icl = None
        if icon_name:
            self._icl = QLabel(); self._icl.setFixedSize(16, 16); self._icl.setStyleSheet('background:transparent;')
            self._icl.setPixmap(_icon_pm(icon_name, 16, _n2_icon_color())); h.addWidget(self._icl)
        self._lbl = None
        if label:
            self._lbl = QLabel(label); self._lbl.setFont(_n2_caps_font())
            self._lbl.setStyleSheet(f'color:{T("text_dim")};background:transparent;'); h.addWidget(self._lbl)
        self._txt = None
        if text or on_text or off_text:
            self._txt = QLabel(text or (off_text or '')); self._txt.setFont(_n2_val_font())
            self._txt.setStyleSheet(f'color:{T("text")};background:transparent;'); h.addWidget(self._txt)
        h.addSpacing(1)
        self._led = QLabel(); self._led.setFixedSize(7, 7)
        self._led.setStyleSheet(f'background:{_n2_led_color(False)};border-radius:3px;'); h.addWidget(self._led)
    def isChecked(self): return self._checked
    def setChecked(self, on):
        on = bool(on)
        if on == self._checked: return
        self._checked = on; self._sync()
    def setText(self, t):
        if self._txt: self._txt.setText(t)
    def click(self):
        """프로그램적 토글 (QAbstractButton.click 호환)."""
        self._checked = not self._checked; self._sync()
        self.clicked.emit(); self.toggled.emit(self._checked)
    def _sync(self):
        self._led.setStyleSheet(f'background:{_n2_led_color(self._checked)};border-radius:3px;')
        if self._icl: self._icl.setPixmap(_icon_pm(self._icon_name, 16, _n2_icon_color(self._checked)))
        if self._txt and (self._on_text or self._off_text):
            self._txt.setText(self._on_text if self._checked else self._off_text)
    def mousePressEvent(self, e):
        e.accept()
    def mouseReleaseEvent(self, e):
        if self.rect().contains(e.pos()):
            self._checked = not self._checked; self._sync()
            self.clicked.emit(); self.toggled.emit(self._checked)
        super().mouseReleaseEvent(e)
    def restyle(self):
        self.setStyleSheet(_n2_hover_ss('n2cell')); self._sync()
        if self._lbl: self._lbl.setStyleSheet(f'color:{T("text_dim")};background:transparent;')
        if self._txt: self._txt.setStyleSheet(f'color:{T("text")};background:transparent;')


class _N2IconBtn(QFrame):
    """아이콘 전용 버튼(팝아웃/패널/Δ/Stable/🎧 등) — checkable 옵션. clicked/toggled."""
    clicked = pyqtSignal()
    toggled = pyqtSignal(bool)

    def __init__(self, icon_name, checkable=False, parent=None):
        super().__init__(parent)
        self._icon_name = icon_name; self._checkable = checkable; self._checked = False
        self.setObjectName('n2cell'); self.setStyleSheet(_n2_hover_ss('n2cell'))
        self.setCursor(Qt.PointingHandCursor); self.setAttribute(Qt.WA_Hover, True)
        self.setFixedWidth(36)
        h = QHBoxLayout(self); h.setContentsMargins(0, 0, 0, 0)
        self._icl = QLabel(); self._icl.setFixedSize(17, 17); self._icl.setStyleSheet('background:transparent;')
        self._icl.setPixmap(_icon_pm(icon_name, 17, _n2_icon_color())); h.addWidget(self._icl, 0, Qt.AlignCenter)
    def setCheckable(self, v): self._checkable = v
    def setIcon(self, *a):  # QPushButton 호환 no-op (아이콘은 생성자 지정)
        pass
    def isChecked(self): return self._checked
    def setChecked(self, on):
        on = bool(on)
        if on == self._checked: return
        self._checked = on
        self._icl.setPixmap(_icon_pm(self._icon_name, 17, _n2_icon_color(on)))
    def mousePressEvent(self, e):
        e.accept()
    def mouseReleaseEvent(self, e):
        if self.rect().contains(e.pos()):
            if self._checkable:
                self._checked = not self._checked
                self._icl.setPixmap(_icon_pm(self._icon_name, 17, _n2_icon_color(self._checked)))
            self.clicked.emit(); self.toggled.emit(self._checked)
        super().mouseReleaseEvent(e)
    def restyle(self):
        self.setStyleSheet(_n2_hover_ss('n2cell'))
        self._icl.setPixmap(_icon_pm(self._icon_name, 17, _n2_icon_color(self._checked)))


class _N2SegBtn(QLabel):
    def __init__(self, text, parent=None):
        super().__init__(text, parent); self._on = False
        self.setAlignment(Qt.AlignCenter); self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(f'color:{T("text_dim")};background:transparent;border-radius:5px;')
    def set_on(self, on):
        self._on = on
        f = self.font(); f.setBold(on); self.setFont(f)
        if on: self.setStyleSheet(f'color:#fff;background:{T("accent")};border-radius:5px;')
        else:  self.setStyleSheet(f'color:{T("text_dim")};background:transparent;border-radius:5px;')


class _N2Segmented(QFrame):
    """세그먼트(View/Scale/Engine) — [아이콘?] 세그먼트들, 활성=액센트 채움.
    _SegmentedControl 호환: changed(str) 시그널, set_active(key), active()."""
    changed = pyqtSignal(str)

    def __init__(self, items, icon_name=None, height=30, seg_h=24, parent=None):
        super().__init__(parent)
        self._icon_name = icon_name; self.setFixedHeight(height)
        self.setObjectName('n2seg'); self.setStyleSheet('#n2seg{background:transparent;}')
        h = QHBoxLayout(self); h.setContentsMargins(11, 0, 6, 0); h.setSpacing(4)
        self._icl = None
        if icon_name:
            self._icl = QLabel(); self._icl.setFixedSize(16, 16); self._icl.setStyleSheet('background:transparent;')
            self._icl.setPixmap(_icon_pm(icon_name, 16, _n2_icon_color())); h.addWidget(self._icl); h.addSpacing(2)
        self._btns = {}
        for it in items:
            key, label = it[0], it[1]; w = it[2] if len(it) > 2 else None
            b = _N2SegBtn(label); b.setFixedHeight(seg_h)
            if w: b.setFixedWidth(w)
            else: b.setMinimumWidth(34)
            b.mousePressEvent = lambda e, k=key: self._on_click(k)
            f = _n2_val_font(11, QFont.Medium); b.setFont(f)
            h.addWidget(b); self._btns[key] = b
    def _on_click(self, key):
        self.set_active(key); self.changed.emit(key)
    def set_active(self, key):
        for k, b in self._btns.items(): b.set_on(k == key)
    def active(self):
        for k, b in self._btns.items():
            if b._on: return k
        return None
    def restyle(self):
        if self._icl: self._icl.setPixmap(_icon_pm(self._icon_name, 16, _n2_icon_color()))
        for b in self._btns.values(): b.set_on(b._on)
    def apply_theme(self):   # _SegmentedControl 호환
        self.restyle()


def _sec_hairline():
    """사이드 패널 섹션 헤더 아래 하어라인 구분선."""
    f = QFrame(); f.setFixedHeight(1)
    c = '#33333A' if is_dark() else '#D5DBE6'
    f.setStyleSheet(f'background:{c};border:none;')
    return f


class _N2Tab(QFrame):
    """N2 상단 탭 — [아이콘][이름], 활성=액센트 밑줄+흰글씨/액센트아이콘. 트랙 없음.
    _CheckBtn 호환: setChecked/isChecked/clicked."""
    clicked = pyqtSignal()

    def __init__(self, icon_name, label, parent=None):
        super().__init__(parent)
        self._icon_name = icon_name; self._checked = False
        self.setObjectName('n2tab'); self.setStyleSheet(_n2_tab_ss())
        self.setCursor(Qt.PointingHandCursor); self.setAttribute(Qt.WA_Hover, True)
        # 밑줄 없음 — 활성 = 아이콘 액센트 + 흰 볼드 (탭↔메뉴 구분은 하단 전체 파란 라인이 담당)
        h = QHBoxLayout(self); h.setContentsMargins(0, 0, 0, 0); h.setSpacing(8); h.addStretch()
        self._icl = QLabel(); self._icl.setFixedSize(15, 15); self._icl.setStyleSheet('background:transparent;')
        self._icl.setPixmap(_icon_pm(icon_name, 15, _n2_icon_color())); h.addWidget(self._icl)
        self._txt = QLabel(label)
        _tf = QFont(FONT_FAMILY); _tf.setPixelSize(13); _tf.setWeight(QFont.Medium); _tf.setLetterSpacing(QFont.AbsoluteSpacing, 0.6)
        self._txt.setFont(_tf); self._txt.setStyleSheet(f'color:{T("text_dim")};background:transparent;')
        h.addWidget(self._txt); h.addStretch()

    def isChecked(self): return self._checked
    def setChecked(self, on):
        self._checked = bool(on); self._sync()
    def _sync(self):
        on = self._checked
        self._icl.setPixmap(_icon_pm(self._icon_name, 15, T('accent') if on else _n2_icon_color()))
        self._txt.setStyleSheet(f'color:{T("text") if on else T("text_dim")};background:transparent;')
        f = self._txt.font(); f.setWeight(QFont.DemiBold if on else QFont.Medium); self._txt.setFont(f)
    def mousePressEvent(self, e):
        e.accept()
    def mouseReleaseEvent(self, e):
        if self.rect().contains(e.pos()): self.clicked.emit()
        super().mouseReleaseEvent(e)
    def restyle(self):
        self.setStyleSheet(_n2_tab_ss()); self._sync()


class VUMeter(QWidget):
    """
    ★ VU 미터는 항상 raw dBFS 기준으로 표시
       캘리브레이션 오프셋은 그래프/수치에만 적용되고 VU 게인에는 영향 없음
    """
    clicked = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setFixedWidth(68); self.setAttribute(Qt.WA_OpaquePaintEvent,True)
        self.raw_spl  = -100.0   # dBFS (캘리브 오프셋 미적용)
        self.raw_peak = -100.0   # dBFS
        self.cal_spl  = -100.0   # dBSPL (캘리브 오프셋 적용, 숫자 표시용)
        self.cal_peak = -100.0

    def mousePressEvent(self, e): self.clicked.emit(); super().mousePressEvent(e)

    def update_level(self, raw_spl, raw_peak, cal_spl, cal_peak):
        self.raw_spl  = raw_spl;  self.raw_peak  = raw_peak
        self.cal_spl  = cal_spl;  self.cal_peak  = cal_peak
        self.update()

    def paintEvent(self,ev):
        p=QPainter(self); W,H=self.width(),self.height()
        p.fillRect(0,0,W,H,QColor(T('bg2')))
        DB_MIN = METER_DB_MIN; DB_RANGE = -METER_DB_MIN   # 모든 미터와 동일 스케일

        # Title: Input / Meter (two lines)
        p.setFont(_qfont(CF_TINY, True)); p.setPen(QColor(T('text_dim')))
        p.drawText(0,6,W,12,Qt.AlignHCenter,'INPUT')
        p.drawText(0,17,W,12,Qt.AlignHCenter,'METER')

        # Bar — taller, starts lower
        bx=W//2-14; bw=28; by=32; bh=max(0, min(H-110, 220))
        p.fillRect(bx,by,bw,bh,QColor(T('bg')))
        p.setPen(QColor(T('border'))); p.drawRect(bx,by,bw,bh)
        lv=max(0.0,min(1.0,(self.raw_spl-DB_MIN)/DB_RANGE)); fh=int(lv*bh)
        if fh>0:
            base=by+bh
            # 구간 경계를 dBFS 기준(METER_*)으로 — 수평 미터와 동일한 분포
            y_b=int(max(0.0,min(1.0,(METER_YELLOW_DB-DB_MIN)/DB_RANGE))*bh)
            r_b=int(max(0.0,min(1.0,(METER_RED_DB-DB_MIN)/DB_RANGE))*bh)
            gh=min(fh,y_b); yh=min(max(0,fh-y_b),r_b-y_b); rh=max(0,fh-r_b)
            if gh: p.fillRect(bx+1,base-gh,bw-2,gh,QColor(T('green')))
            if yh: p.fillRect(bx+1,base-gh-yh,bw-2,yh,QColor(T('yellow')))
            if rh: p.fillRect(bx+1,base-fh,bw-2,rh,QColor(T('red')))
        pk_lv=max(0.0,min(1.0,(self.raw_peak-DB_MIN)/DB_RANGE))
        p.fillRect(bx+1,by+bh-int(pk_lv*bh)-1,bw-2,2,QColor(T('red')))

        # Values below bar
        y0=by+bh+6
        p.setFont(_qfont(CF_AXIS, True))
        c=T('red') if self.raw_spl>METER_RED_DB else T('yellow') if self.raw_spl>METER_YELLOW_DB else T('accent')
        p.setPen(QColor(c)); p.drawText(0,y0,W,16,Qt.AlignHCenter,f'{self.cal_spl:.1f}')
        p.setFont(_qfont(CF_ANNO)); p.setPen(QColor(T('text_dim')))
        p.drawText(0,y0+16,W,12,Qt.AlignHCenter,'dB')
        p.setFont(_qfont(CF_ANNO, True)); p.setPen(QColor(T('text_dim')))
        p.drawText(0,y0+32,W,12,Qt.AlignHCenter,'PEAK')
        p.setFont(_qfont(CF_ANNO, True)); p.setPen(QColor(T('yellow')))
        p.drawText(0,y0+46,W,14,Qt.AlignHCenter,f'{self.cal_peak:.1f}')
        p.setFont(_qfont(CF_ANNO, True)); p.setPen(QColor(T('text_dim')))
        p.drawText(0,y0+64,W,12,Qt.AlignHCenter,'CLIP')
        p.fillRect(W//2-13,y0+78,26,12,QColor(T('red') if self.raw_spl>-3 else T('border')))
        # section border
        p.setPen(QPen(QColor(T('border')), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(1, 1, W-2, H-2, 8, 8)
        p.end()


class _SegmentedControl(QWidget):
    """모던 세그먼트 컨트롤 — 하나의 펄 안에 옵션들, 활성만 블루 강조 (iOS식)."""
    changed = pyqtSignal(str)
    def __init__(self, items, height=30, parent=None):   # items = [(key, label, width|None), ...]
        super().__init__(parent)
        self.setObjectName('segCtl'); self.setFixedHeight(height)
        lay = QHBoxLayout(self); lay.setContentsMargins(3, 0, 3, 0); lay.setSpacing(2)
        self._btns = {}
        for key, label, w in items:
            b = _SegBtn(label); b.setFixedHeight(height - 6)
            if w: b.setFixedWidth(w)
            b.clicked.connect(lambda _=False, k=key: self._on_click(k))
            lay.addWidget(b); self._btns[key] = b
        self.apply_theme()

    def _on_click(self, key):
        self.set_active(key); self.changed.emit(key)

    def set_active(self, key):
        for k, b in self._btns.items():
            b.setChecked(k == key); b.update()

    def active(self):
        for k, b in self._btns.items():
            if b.isChecked(): return k
        return None

    def apply_theme(self):
        bg = '#252527' if is_dark() else T('bg3')
        self.setStyleSheet(f'#segCtl{{background:{bg};border-radius:8px;}}')
        for b in self._btns.values(): b.update()


class _MiniMeterBar(QWidget):
    """채널 팝업 안의 미니 수평 레벨 미터."""
    def __init__(self):
        super().__init__()
        self._level = -100.0
        self._peak  = -100.0
        self.setFixedHeight(8)

    def set_level(self, db, peak_db=None):
        self._level = db
        pk = peak_db if peak_db is not None else db   # 실제 peak(있으면) — 바=RMS·tick=true peak
        if pk > self._peak: self._peak = pk
        else: self._peak = max(self._peak - 0.8, self._level)
        self.update()

    def reset(self):
        self._level = -100.0; self._peak = -100.0; self.update()

    def paintEvent(self, ev):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        W = self.width(); H = self.height(); rr = H / 2.0
        # 은은한 둥근 트랙 (까만 공백 대신). 라이트(near-white)에선 밝히면 사라짐 → 어둡게 파생.
        bg = QColor(T('bg')); d = -20 if (not is_dark()) else 14
        track = QColor(max(0, min(bg.red()+d, 255)), max(0, min(bg.green()+d, 255)), max(0, min(bg.blue()+d+2, 255)))
        p.setPen(Qt.NoPen); p.setBrush(track); p.drawRoundedRect(QRectF(0, 0, W, H), rr, rr)
        DB_MIN = METER_DB_MIN; DB_MAX = 0.0   # 모든 미터와 동일 스케일(통일)
        # 위치 기반 green/yellow/red 구간 채움 (M4/Smaart 사다리)
        _draw_zone_meter_h(p, W, H, self._level, DB_MIN, DB_MAX)
        # peak tick
        if self._peak > DB_MIN:
            px = W * max(0.0, min(1.0, (self._peak - DB_MIN) / (DB_MAX - DB_MIN)))
            p.setPen(QPen(QColor(T('text')), 1)); p.drawLine(int(px), 1, int(px), int(H - 1))
        p.end()


class _ChannelGridPopup(QFrame):
    """채널 그리드 피커 — 긴 세로 목록 대신 번호를 격자(기본 8열)로. 항목 많은
    인터페이스(예: 64ch)도 한 화면에 보고 클릭 한 번에 선택. 스크롤/드래그 불필요."""
    item_selected = pyqtSignal(int)

    def __init__(self, combo, cols=8):
        super().__init__(None, Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.setAutoFillBackground(True)
        pal = self.palette(); pal.setColor(self.backgroundRole(), QColor(T('bg2'))); self.setPalette(pal)
        self.setObjectName('gridpop')
        self.setStyleSheet(f'QFrame#gridpop{{background:{T("bg2")};border:1px solid {T("accent")};border-radius:12px;}}')
        from PyQt5.QtWidgets import QScrollArea, QGridLayout
        outer = QVBoxLayout(self); outer.setContentsMargins(8, 7, 8, 8); outer.setSpacing(7)
        hdr = QLabel(_tx('Select channel')); hdr.setFont(_n2_caps_font(9))
        hdr.setStyleSheet(f'color:{T("text_dim")};background:transparent;'); outer.addWidget(hdr)
        self._scroll = QScrollArea(); self._scroll.setWidgetResizable(True); self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet(
            'QScrollArea{background:transparent;border:none;}'
            'QScrollBar:vertical{width:6px;background:transparent;margin:2px;}'
            f'QScrollBar::handle:vertical{{background:{T("border")};border-radius:3px;min-height:24px;}}'
            'QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}')
        inner = QWidget(); inner.setStyleSheet('background:transparent;')
        g = QGridLayout(inner); g.setContentsMargins(2, 2, 2, 2); g.setSpacing(4)
        cur = combo.currentIndex()
        _acc = QColor(T('accent')); _ar, _ag, _ab = _acc.red(), _acc.green(), _acc.blue()
        n = combo.count()
        for i in range(n):
            on = (i == cur)
            _lbl = combo.itemText(i)
            if _lbl.startswith('Ch '): _lbl = _lbl[3:]   # 격자엔 번호만(중복 'Ch' 제거)
            b = QPushButton(_lbl); b.setFlat(True); b.setFixedSize(46, 30)
            b.setFocusPolicy(Qt.NoFocus); b.setCursor(Qt.PointingHandCursor)
            b.setFont(_n2_mono_font(12, QFont.DemiBold if on else QFont.Medium))
            if on:
                b.setStyleSheet(f'QPushButton{{background:{T("accent")};color:#fff;border:none;border-radius:7px;}}')
            else:
                b.setStyleSheet(f'QPushButton{{background:transparent;color:{T("text")};border:1px solid {T("border")};border-radius:7px;}}'
                                f'QPushButton:hover{{background:rgba({_ar},{_ag},{_ab},45);border-color:{T("accent")};}}')
            b.mousePressEvent = lambda e, idx=i: self._pick(idx)
            g.addWidget(b, i // cols, i % cols)
        self._scroll.setWidget(inner); outer.addWidget(self._scroll)
        self._content = inner

    def sizeHint(self):
        s = self._content.sizeHint()
        from PyQt5.QtCore import QSize
        return QSize(s.width() + 20, s.height() + 40)

    def _pick(self, idx):
        self.item_selected.emit(idx)
        self.close()


class ChannelPopup(QFrame):
    """[+] 버튼으로 열리는 멀티채널 선택 팝업.
    체크박스로 추가 채널을 활성화하고, 각 채널의 실시간 레벨을 미니 미터로 표시."""
    channels_changed = pyqtSignal(list)   # 활성 추가 채널 인덱스 리스트 (primary 제외)

    def __init__(self, parent=None):
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._primary_ch = 0
        self._active = set()
        self._rows = {}   # {ch_idx: {'check', 'meter', 'db_lbl'}}
        self._vlay = QVBoxLayout(self)
        self._vlay.setContentsMargins(10, 8, 10, 10)
        self._vlay.setSpacing(1)
        hdr = QLabel('Input Channels')
        hdr.setStyleSheet(f'color:{T("text_dim")};font-size:11px;font-weight:600;'
                          f'padding-bottom:4px;')
        self._vlay.addWidget(hdr)
        self._sep = QFrame(); self._sep.setFrameShape(QFrame.HLine)
        self._sep.setStyleSheet(f'color:{T("grid")};')
        self._vlay.addWidget(self._sep)

    def _apply_style(self):
        self.setStyleSheet(f'''
            ChannelPopup {{
                background:{T("bg2")};
                border:1px solid {T("grid")};
                border-radius:10px;
            }}
        ''')

    def showEvent(self, e):
        self._apply_style(); super().showEvent(e)

    def set_device_channels(self, n_ch, primary_ch):
        for row in self._rows.values():
            row['widget'].setParent(None)
        self._rows.clear()
        self._primary_ch = primary_ch
        self._active.clear()

        for ch in range(n_ch):
            color = _MC_COLORS[ch % len(_MC_COLORS)]
            row_w = QWidget()
            rl = QHBoxLayout(row_w); rl.setContentsMargins(0, 3, 0, 3); rl.setSpacing(5)

            chk = QCheckBox()
            chk.setFixedWidth(20)
            if ch == primary_ch:
                chk.setChecked(True); chk.setEnabled(False)
            else:
                chk.setChecked(False)
                chk.stateChanged.connect(lambda st, c=ch: self._on_check(c, st))

            dot = QLabel('●')
            main_color = T('spec_line')   # 브랜드 spec_line(라이트 #1670cc) 통일
            dot.setStyleSheet(f'color:{main_color if ch==primary_ch else color};font-size:13px;')
            dot.setFixedWidth(14)

            name_lbl = QLabel(f'Ch {ch + 1}' + (' ★' if ch == primary_ch else ''))
            name_lbl.setStyleSheet(f'color:{T("text")};font-size:11px;')
            name_lbl.setFixedWidth(52)

            meter = _MiniMeterBar(); meter.setFixedWidth(72)

            db_lbl = QLabel('  — ')
            db_lbl.setStyleSheet(f'color:{T("text_dim")};font-size:10px;')
            db_lbl.setFixedWidth(36)
            db_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

            rl.addWidget(chk); rl.addWidget(dot); rl.addWidget(name_lbl)
            rl.addWidget(meter); rl.addWidget(db_lbl)
            self._vlay.addWidget(row_w)
            self._rows[ch] = {'widget': row_w, 'check': chk, 'meter': meter, 'db_lbl': db_lbl}

        self.adjustSize()

    def _on_check(self, ch_idx, state):
        if state == Qt.Checked: self._active.add(ch_idx)
        else: self._active.discard(ch_idx)
        self.channels_changed.emit(sorted(self._active))

    def update_levels(self, levels_dict):
        for ch, db in levels_dict.items():
            if ch in self._rows:
                self._rows[ch]['meter'].set_level(db)
                self._rows[ch]['db_lbl'].setText(f'{db:.1f}')

    def reset_levels(self):
        for row in self._rows.values():
            row['meter'].reset()
            row['db_lbl'].setText('  — ')

    def get_extra_channels(self):
        return sorted(self._active)


class RoundComboBox(QComboBox):
    _max_display_chars = None  # int으로 설정 시 해당 글자수+'..'로 표기 트런케이션
    _align_center = False      # True면 텍스트 가운데 정렬
    _elide_to_width = False    # True면 필드 폭에 맞춰 '…'로 생략 (긴 장치명 깔끔히)
    _flat_cell = False         # True면 Fusion 회색 배경 없이 투명+테두리만(N2 셀 룩)
    _flat_border = '#34343B'

    def _paint_flat(self):
        """N2 flat 셀 — Fusion 콤보 크롬(회색 채움/화살표) 대신 투명 배경+둥근 테두리+텍스트."""
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        opt = QStyleOptionComboBox(); self.initStyleOption(opt)
        text = opt.currentText
        if self._max_display_chars is not None and len(text) > self._max_display_chars:
            text = text[:self._max_display_chars] + '..'
        pen = QPen(QColor(self._flat_border)); pen.setWidthF(1.0)
        p.setPen(pen); p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
        p.setPen(QColor(T('text'))); p.setFont(self.font())
        if self._align_center:
            p.drawText(self.rect(), Qt.AlignCenter, text)
        else:
            r = self.rect().adjusted(9, 0, -9, 0)
            text = self.fontMetrics().elidedText(text, Qt.ElideRight, max(8, r.width()))
            p.drawText(r, Qt.AlignLeft | Qt.AlignVCenter, text)
        p.end()

    def paintEvent(self, event):
        if self._flat_cell:
            self._paint_flat(); return
        if not self._align_center and self._max_display_chars is None and not self._elide_to_width:
            super().paintEvent(event)
            return
        painter = QStylePainter(self)
        opt = QStyleOptionComboBox()
        self.initStyleOption(opt)
        text = opt.currentText
        if self._max_display_chars is not None and len(text) > self._max_display_chars:
            text = text[:self._max_display_chars] + '..'
        painter.drawComplexControl(QStyle.CC_ComboBox, opt)
        # 커스텀 페인트라 stylesheet color가 안 먹음 → 시스템 팔레트(맥 다크모드=흰색)로
        # 그려져 라이트 테마에서 글씨가 안 보임. 테마 텍스트색을 명시한다.
        _tc = QColor(T('text'))
        if self._align_center:
            rect = self.style().subControlRect(
                QStyle.CC_ComboBox, opt, QStyle.SC_ComboBoxEditField, self)
            painter.setPen(_tc)
            painter.drawText(rect, Qt.AlignCenter, text)
        elif self._elide_to_width:
            # 위젯 실폭 기준(좌우 8px 패딩)으로 '…' 생략 후 직접 그림 — 서브컨트롤 rect가
            # 맥 콤보 스타일에서 과도하게 좁게 잡혀 'M…'처럼 잘리던 문제 회피.
            rect = self.rect().adjusted(4, 0, -4, 0)
            text = self.fontMetrics().elidedText(text, Qt.ElideRight, max(8, rect.width()))
            painter.setPen(_tc)
            painter.drawText(rect, Qt.AlignLeft | Qt.AlignVCenter, text)
        else:
            opt.currentText = text
            opt.palette.setColor(QPalette.ButtonText, _tc)
            opt.palette.setColor(QPalette.Text, _tc)
            painter.drawControl(QStyle.CE_ComboBoxLabel, opt)
        painter.end()

    _grid_popup = False   # True면 채널 그리드 피커 사용(항목 많은 채널 선택용)

    def showPopup(self):
        global_top = self.mapToGlobal(QPoint(0, 0))
        scr = (QApplication.screenAt(global_top) if hasattr(QApplication, 'screenAt') else None) \
              or QApplication.primaryScreen()
        avail = scr.availableGeometry()
        # 채널 콤보(항목 5개 초과)면 그리드 피커, 아니면 세로 목록
        if self._grid_popup and self.count() > 5:
            popup = _ChannelGridPopup(self)
        else:
            popup = DropdownPopup(self)
        popup.item_selected.connect(self.setCurrentIndex)
        popup.adjustSize()
        w = max(self.width(), popup.sizeHint().width())
        # 세로 높이 = 내용 vs 화면 60% 중 작은 값 (넘치면 내부 스크롤)
        ph = min(popup.sizeHint().height(), int(avail.height() * 0.6))
        popup.resize(w, ph)
        # 세로: 아래 공간 부족하면 위로, 충분하면 아래로
        if global_top.y() + self.height() + ph + 4 > avail.bottom():
            y = max(avail.y() + 4, global_top.y() - ph - 2)
        else:
            y = global_top.y() + self.height() + 2
        # 가로: 콤보 왼쪽 정렬이 기본이나, 팝업이 화면 밖으로 넘치면 안쪽으로 당겨 잘림 방지
        x = global_top.x()
        right_bound = avail.x() + avail.width()
        if x + w > right_bound:
            x = right_bound - w
        if x < avail.x():
            x = avail.x()
        popup.move(x, y)
        # macOS Qt.Popup: mousePressEvent 처리 중 show()하면 같은 클릭의 mouseRelease가
        # 팝업 외부 이벤트로 잡혀 즉시 닫힘. singleShot(0)으로 현재 이벤트 사이클 후 표시.
        self._active_popup = popup   # GC 방지용 레퍼런스 유지
        QTimer.singleShot(0, popup.show)

    def hidePopup(self):
        super().hidePopup()


def hsep(color_key='border'):
    """1px 수평 구분선. QFrame.HLine 의 베벨/이중선 없이 깔끔한 단색 라인."""
    f = QFrame(); f.setFixedHeight(1)
    f.setStyleSheet(f'background:{T(color_key)};border:none;')
    return f


def begin_inline_rename(host, label, on_done):
    """label 위에 인라인 QLineEdit 를 띄워 그 자리에서 이름 편집. 확정 시 on_done(text) 호출.
    빈 문자열이면 on_done('') (기본값 복귀는 호출측에서 처리)."""
    from PyQt5.QtWidgets import QLineEdit
    edit = QLineEdit(label.text(), host)
    edit.setStyleSheet(
        f'QLineEdit{{background:{T("bg3")};color:{T("text")};border:1px solid {T("accent")};'
        f'border-radius:{RADIUS_SM}px;padding:0 4px;font-size:{FS_SM}px;}}')
    tl = label.mapTo(host, QPoint(0, 0))
    # 카드(host) 오른쪽 경계를 넘지 않게 폭 클램프 — 넘치던 버그 수정
    w = max(label.width() + 60, 100)
    w = min(w, max(40, host.width() - tl.x() - 6))
    edit.setGeometry(tl.x(), tl.y() - 1, w, label.height() + 2)
    edit.selectAll(); edit.setFocus()
    _done = {'v': False}
    _filt = {'v': None}
    def _finish():
        if _done['v']: return
        _done['v'] = True
        if _filt['v'] is not None:
            _app = QApplication.instance()
            if _app is not None: _app.removeEventFilter(_filt['v'])
            _filt['v'] = None
        txt = edit.text().strip()
        edit.deleteLater()
        on_done(txt)
    edit.editingFinished.connect(_finish)

    # 에디터 밖(다른 카드·분석화면 등 포커스 안 받는 위젯 포함) 클릭 시에도 커밋·닫힘.
    # editingFinished는 포커스 이동 시에만 발동 → NoFocus 위젯 클릭 땐 안 닫히던 버그 해결.
    from PyQt5.QtCore import QObject, QEvent
    class _OutsideClick(QObject):
        def eventFilter(self, obj, ev):
            if ev.type() == QEvent.MouseButtonPress and not _done['v']:
                w = obj
                inside = False
                while w is not None:
                    if w is edit: inside = True; break
                    w = w.parentWidget() if hasattr(w, 'parentWidget') else None
                if not inside:
                    _finish()   # 원래 클릭은 소비하지 않음(대상 카드 선택 등 정상 동작)
            return False
    _filt['v'] = _OutsideClick(edit)
    _app = QApplication.instance()
    if _app is not None: _app.installEventFilter(_filt['v'])

    edit.show(); edit.raise_()


class DeviceCardPopup(QFrame):
    device_selected = pyqtSignal(int)  # combo index
    refresh_requested = pyqtSignal()

    def __init__(self, combo, disconnected_name=''):
        super().__init__(None, Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.setAutoFillBackground(True)
        pal = self.palette()
        pal.setColor(self.backgroundRole(), QColor(T('bg2')))
        self.setPalette(pal)
        self.setObjectName('devPopup')
        self.setStyleSheet(
            f'QFrame#devPopup {{ background:{T("bg2")}; border:1px solid {T("accent")}; '
            f'border-radius:12px; }}'
        )
        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(10, 10, 10, 10)
        self._outer.setSpacing(6)

        hdr_w = QWidget(); hdr_w.setStyleSheet('background:transparent;')
        hdr_lay = QHBoxLayout(hdr_w); hdr_lay.setContentsMargins(0,2,0,2); hdr_lay.setSpacing(4)
        hdr_lay.addStretch(1)
        hdr_title = QLabel(
            f'<div style="font-family:\'{FONT_FAMILY}\';">'
            f'<span style="font-size:12px;font-weight:700;'
            f'color:{T("accent")};letter-spacing:2px;">AUDIO</span>'
            f'&nbsp;<span style="font-size:10px;color:{T("text_dim")};">Input Device</span></div>'
        )
        hdr_title.setStyleSheet('background:transparent; border:none;')
        hdr_lay.addWidget(hdr_title)
        hdr_lay.addStretch(1)
        self._status_lbl = QLabel()
        self._status_lbl.setStyleSheet(
            f'color:{T("green")}; font-size:9px; background:transparent; border:none;'
        )
        self._status_lbl.setVisible(False)
        hdr_lay.addWidget(self._status_lbl)
        self._outer.addWidget(hdr_w)

        sep = QFrame(); sep.setFrameShape(QFrame.HLine); sep.setFixedHeight(1)
        sep.setStyleSheet(f'background:{T("border")}; border:none;')
        self._outer.addWidget(sep)

        # 카드 전용 컨테이너 — rebuild_cards 에서 이 영역만 갱신
        self._cards_widget = QWidget(); self._cards_widget.setStyleSheet('background:transparent;')
        self._cards_layout = QVBoxLayout(self._cards_widget)
        self._cards_layout.setContentsMargins(0, 0, 0, 0); self._cards_layout.setSpacing(6)
        self._outer.addWidget(self._cards_widget)
        self._fill_cards(combo, disconnected_name)

        bot_sep = QFrame(); bot_sep.setFrameShape(QFrame.HLine); bot_sep.setFixedHeight(1)
        bot_sep.setStyleSheet(f'background:{T("border")}; border:none;')
        self._outer.addWidget(bot_sep)

        ref_btn = QPushButton('Refresh Devices'); ref_btn.setIcon(_icon('refresh', 13))
        ref_btn.setFixedHeight(28)
        ref_btn.setStyleSheet(
            f'QPushButton {{ background:transparent; color:{T("text_dim")}; border:none; '
            f'border-radius:6px; font-size:10px; padding:0px 8px; }}'
            f'QPushButton:hover {{ background:rgba(255,255,255,10); color:{T("text")}; }}'
        )
        ref_btn.mousePressEvent = lambda e: self._refresh()
        self._outer.addWidget(ref_btn)

    def _fill_cards(self, combo, disconnected_name):
        for i in range(combo.count()):
            name = combo.itemText(i)
            dev_idx = combo.itemData(i)
            selected = (i == combo.currentIndex())
            disc = bool(disconnected_name and name == disconnected_name)
            ch_count = 0
            try:
                if dev_idx is not None and dev_idx >= 0:
                    ch_count = int(sd.query_devices(dev_idx)['max_input_channels'])
            except Exception:
                pass
            self._cards_layout.addWidget(self._make_card(i, name, ch_count, selected, disc, dev_idx))

    def rebuild_cards(self, combo, disconnected_name=''):
        fixed_w = self.width()
        idx = self._outer.indexOf(self._cards_widget)
        self._outer.removeWidget(self._cards_widget)
        self._cards_widget.hide()
        self._cards_widget.deleteLater()

        self._cards_widget = QWidget()
        self._cards_widget.setStyleSheet('background:transparent;')
        self._cards_layout = QVBoxLayout(self._cards_widget)
        self._cards_layout.setContentsMargins(0, 0, 0, 0)
        self._cards_layout.setSpacing(6)
        self._outer.insertWidget(idx, self._cards_widget)

        self._fill_cards(combo, disconnected_name)
        self.adjustSize()
        self.resize(fixed_w, self.sizeHint().height())
        self._status_lbl.setText('✓ Refreshed')
        self._status_lbl.setVisible(True)
        QTimer.singleShot(2000, self._clear_status)

    def _clear_status(self):
        try:
            self._status_lbl.setVisible(False)
        except RuntimeError:
            pass

    def _refresh(self):
        self.refresh_requested.emit()  # 팝업 닫지 않음 — 메인 윈도우가 갱신 후 rebuild_cards 호출

    def _make_card(self, combo_idx, name, ch_count, selected, disconnected, dev_idx):
        card = QFrame(); card.setObjectName('devCard')
        bg = 'rgba(78,125,240,40)' if selected else T('bg3')
        bd = T('accent') if selected else T('border')
        card.setStyleSheet(
            f'QFrame#devCard {{ background:{bg}; border:1px solid {bd}; border-radius:8px; }}'
        )
        lay = QHBoxLayout(card)
        lay.setContentsMargins(10, 7, 10, 7); lay.setSpacing(8)

        dot = QLabel('●')
        dot_color = T('text_dim') if (disconnected or (dev_idx is not None and dev_idx < 0)) else T('green')
        dot.setStyleSheet(f'color:{dot_color}; font-size:9px; background:transparent; border:none;')
        dot.setFixedWidth(12)
        lay.addWidget(dot)

        txt_w = QWidget(); txt_w.setStyleSheet('background:transparent; border:none;')
        txt_lay = QVBoxLayout(txt_w); txt_lay.setContentsMargins(0,0,0,0); txt_lay.setSpacing(1)

        name_color = T('text_dim') if disconnected else (T('accent') if selected else T('text'))
        name_lbl = QLabel(name)
        name_lbl.setStyleSheet(
            f'color:{name_color};  font-size:11px; '
            f'font-weight:{"bold" if selected else "normal"}; background:transparent; border:none;'
        )
        txt_lay.addWidget(name_lbl)

        if disconnected:
            sub = QLabel('Disconnected')
            sub.setStyleSheet(f'color:{T("yellow")}; font-size:9px; background:transparent; border:none;')
            txt_lay.addWidget(sub)
        elif ch_count > 0:
            sub = QLabel(f'{ch_count} ch')
            sub.setStyleSheet(f'color:{T("text_dim")}; font-size:9px; background:transparent; border:none;')
            txt_lay.addWidget(sub)

        lay.addWidget(txt_w); lay.addStretch()

        if selected:
            chk = QLabel('✓')
            chk.setStyleSheet(
                f'color:{T("accent")}; font-size:12px; font-weight:bold; '
                f'background:transparent; border:none;'
            )
            lay.addWidget(chk)

        if not disconnected and dev_idx is not None and dev_idx >= 0:
            card.mousePressEvent = lambda e, idx=combo_idx: self._pick(idx)
            card.setCursor(Qt.PointingHandCursor)

        return card

    def _pick(self, idx):
        self.device_selected.emit(idx)
        self.close()


class ChannelCard(QFrame):
    """INPUT 패널 내 채널 카드 — 체크박스(그래프 가시성) + 장치명 + 채널 번호 + 레벨 미터."""
    visibility_toggled = pyqtSignal(int, bool)   # (ch_idx, visible)
    remove_requested   = pyqtSignal(int)          # (ch_idx)  — primary는 emit 안 함
    device_clicked     = pyqtSignal()             # primary 카드 전용

    def __init__(self, ch_idx, device_name, color, is_primary=False, parent=None):
        super().__init__(parent)
        self._ch_idx    = ch_idx
        self._is_primary = is_primary
        self._color = color
        self.setObjectName('channelCard')
        lay = QVBoxLayout(self); lay.setContentsMargins(6,5,6,5); lay.setSpacing(3)

        # ── Row 1: [☑] [●] [device name] [×]
        row1 = QHBoxLayout(); row1.setSpacing(3)
        self._chk = QCheckBox(); self._chk.setChecked(True); self._chk.setFixedWidth(20)
        self._chk.setFocusPolicy(Qt.NoFocus)   # macOS 파란 포커스 링 제거
        self._chk.setStyleSheet(f'''
            QCheckBox::indicator {{
                width:13px; height:13px;
                border:1.5px solid {color};
                border-radius:3px;
                background:transparent;
            }}
            QCheckBox::indicator:checked {{
                background:{color};
                image:none;
            }}
        ''')
        self._chk.stateChanged.connect(lambda st: self.visibility_toggled.emit(self._ch_idx, st==Qt.Checked))
        dot = QLabel('●')
        dot.setStyleSheet(f'color:{color};background:transparent;font-size:11px;'); dot.setFixedWidth(13)
        short = (device_name[:17]+'..') if len(device_name)>19 else device_name
        if is_primary:
            self._dev_btn_ref = QPushButton(short)
            self._dev_btn_ref.setFlat(True)
            self._dev_btn_ref.setStyleSheet(
                f'color:{T("text")};font-size:10px;text-align:left;padding:0 2px;border:none;'
                f'background:transparent;')
            self._dev_btn_ref.setCursor(Qt.PointingHandCursor)
            self._dev_btn_ref.clicked.connect(self.device_clicked)
            row1.addWidget(self._chk); row1.addWidget(dot); row1.addWidget(self._dev_btn_ref, 1)
        else:
            dev_lbl = QLabel(short)
            dev_lbl.setStyleSheet(f'color:{T("text")};background:transparent;font-size:10px;')
            rm = QPushButton('✕'); rm.setFixedSize(16,16)
            rm.setStyleSheet(f'QPushButton{{color:{T("text_dim")};font-size:12px;border:none;padding:0;background:transparent;}}'
                             f'QPushButton:hover{{color:{T("red")};}}')
            rm.setCursor(Qt.PointingHandCursor)
            rm.clicked.connect(lambda: self.remove_requested.emit(self._ch_idx))
            row1.addWidget(self._chk); row1.addWidget(dot); row1.addWidget(dev_lbl, 1); row1.addWidget(rm)
        lay.addLayout(row1)

        # ── Row 2: [Ch X] [meter] [dB]
        row2 = QHBoxLayout(); row2.setSpacing(3)
        ch_lbl = QLabel(f'Ch {ch_idx+1}')
        ch_lbl.setStyleSheet(f'color:{T("text_dim")};background:transparent;font-size:10px;'); ch_lbl.setFixedWidth(28)
        self._meter = _MiniMeterBar(); self._meter.setFixedHeight(7)
        self._db_lbl = QLabel(' — ')
        self._db_lbl.setStyleSheet(f'color:{T("text_dim")};background:transparent;font-size:10px;')
        self._db_lbl.setFixedWidth(34); self._db_lbl.setAlignment(Qt.AlignRight|Qt.AlignVCenter)
        row2.addWidget(ch_lbl); row2.addWidget(self._meter, 1); row2.addWidget(self._db_lbl)
        lay.addLayout(row2)
        self._apply_style()

    def _apply_style(self):
        # TF 측정 카드와 동일한 색 테두리 룩
        self.setStyleSheet(f'#channelCard{{background:{T("panel")};'
                           f'border:2px solid {self._color};border-radius:{RADIUS_SM}px;padding:1px;}}')

    def update_level(self, db, peak_db=None):
        self._meter.set_level(db, peak_db); self._db_lbl.setText(f'{db:.1f}')

    def reset(self):
        self._meter.reset(); self._db_lbl.setText(' — ')


class _SpecCard(QFrame):
    """Spectrum 추가 소스 카드 — 카드마다 장치+채널 독립 선택 (멀티-장치 오버레이).
    TF 측정 카드 룩 차용: 색 테두리 + 가시성 토글 + 장치/채널 드롭다운 + 레벨미터 + 삭제."""
    device_changed     = pyqtSignal(int)        # card_id
    channel_changed    = pyqtSignal(int)        # card_id
    visibility_toggled = pyqtSignal(int, bool)  # (card_id, visible)
    remove_requested   = pyqtSignal(int)        # card_id
    selected           = pyqtSignal(int)        # card_id — 카드 클릭 → front
    renamed            = pyqtSignal(int, str)   # (card_id, new_name)
    start_toggled      = pyqtSignal(int)        # card_id — 카드별 Start(측정 on/off)
    color_requested    = pyqtSignal(int)        # card_id — 우클릭 색 변경

    def __init__(self, card_id, color, dev_items, is_primary=False, parent=None):
        super().__init__(parent)
        self._card_id = card_id
        self._color = color
        self._is_primary = is_primary
        self._is_selected = False
        self._default_name = str(card_id + 1)
        self._name = ''
        self.setObjectName('specCard')
        self._apply_border()
        lay = QVBoxLayout(self); lay.setContentsMargins(9,5,6,6); lay.setSpacing(3)

        # 헤더: [가시성 체크] [●=Start] [번호] ... [삭제]  (모든 카드 동일 레이아웃)
        # 체크박스 폭 ≥ 인디케이터(13+테두리 3=16px)라야 네모가 안 잘림.
        hdr = QHBoxLayout(); hdr.setContentsMargins(0,0,0,0); hdr.setSpacing(3)
        self._chk = QCheckBox(); self._chk.setChecked(True); self._chk.setFixedWidth(17)
        self._chk.setFocusPolicy(Qt.NoFocus)   # macOS 파란 포커스 링 제거
        self._chk.setStyleSheet(
            f'QCheckBox::indicator{{width:13px;height:13px;border:1.5px solid {color};'
            f'border-radius:3px;background:transparent;}}'
            f'QCheckBox::indicator:checked{{background:{color};image:none;}}')
        self._chk.stateChanged.connect(
            lambda st: self.visibility_toggled.emit(self._card_id, st == Qt.Checked))
        # 색 점 = 카드별 Start 토글(측정 on/off) 겸 색 정체성. 측정 중=채움+글로우 / 꺼짐=흐린 링.
        self._running = False
        self._start_dot = QPushButton()
        self._start_dot.setFixedSize(18, 22)
        self._start_dot.setFocusPolicy(Qt.NoFocus)
        self._start_dot.setCursor(Qt.PointingHandCursor)
        self._start_dot.setToolTip(_tx('Start / stop measuring this source'))
        self._start_dot.setIconSize(QSize(20, 20))
        self._start_dot.setStyleSheet('QPushButton{border:none;background:transparent;padding:0;}')
        self._start_dot.setIcon(QIcon(_led_power_pm(False, 20, color)))
        self._start_dot.clicked.connect(lambda: self.start_toggled.emit(self._card_id))
        self._num_label = QLabel(self._default_name)
        self._num_label.setStyleSheet(f'color:{color};background:transparent;font-size:11px;font-weight:bold;')
        self._num_label.setToolTip(_tx('Double-click to rename'))
        hdr.addWidget(self._chk); hdr.addWidget(self._start_dot); hdr.addWidget(self._num_label); hdr.addStretch()
        # E안: dBFS 값을 헤더 우측에 크게·모노로 (라이브 레벨 강조)
        self._db_lbl = QLabel('—')
        self._db_lbl.setStyleSheet(f'color:{T("text")};background:transparent;')
        self._db_lbl.setFont(_n2_mono_font(14, QFont.Bold))
        self._db_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        hdr.addWidget(self._db_lbl)
        # 삭제는 인라인 ✕ 대신 우클릭 메뉴(contextMenuEvent)로 통일 — 모든 카드(1번·추가) 헤더가
        # 동일해지고, 되돌리기 힘든 삭제를 의도적 우클릭 뒤에 둠. TF 측정 카드와 동일 UX.
        self.setToolTip(_tx('Right-click: rename / delete'))
        lay.addLayout(hdr)

        # 미터 행: 레벨바가 카드 폭 끝까지 꽉 차게 (TF M바와 동일)
        mr = QHBoxLayout(); mr.setContentsMargins(0,0,0,0); mr.setSpacing(0)
        self._meter = _MiniMeterBar(); self._meter.setFixedHeight(12)   # E안: 미터 강조
        mr.addWidget(self._meter, 1)
        lay.addLayout(mr)

        lay.addWidget(hsep())

        # 장치 + 채널 행 (장치명은 폭에 맞춰 자동 생략 …)
        _cb_ss = (
            f'QComboBox{{background:{T("bg3")};color:{T("text")};border:1px solid {T("border")};'
            f'border-radius:{RADIUS_SM}px;padding:1px 6px;font-size:{FS_SM}px;min-height:22px;}}'
            f'QComboBox:hover{{border-color:{T("accent")};}}'
            f'QComboBox::drop-down{{width:0;border:none;}}'
            f'QComboBox::down-arrow{{width:0;height:0;image:none;}}')
        row = QHBoxLayout(); row.setContentsMargins(0,0,0,0); row.setSpacing(3)
        lbl = QLabel('In'); lbl.setFixedWidth(14); lbl.setStyleSheet(ss_text(FS_XS))
        self._dev_cb = RoundComboBox(); self._dev_cb.setStyleSheet(_cb_ss)
        self._dev_cb.setFocusPolicy(Qt.NoFocus)        # macOS 파란 포커스 링 제거
        self._dev_cb.setMinimumWidth(40)               # stretch로 채워지고 긴 이름은 폭에 맞춰 … 로 생략
        self._dev_cb.setMinimumContentsLength(4)
        self._dev_cb._elide_to_width = True            # 'MacBo' 처럼 잘리지 않고 'MacB…' 로 깔끔히
        for name, idx in dev_items:
            self._dev_cb.addItem(name, idx)
        self._ch_cb = RoundComboBox(); self._ch_cb.setStyleSheet(_cb_ss); self._ch_cb._grid_popup = True
        self._ch_cb.setFocusPolicy(Qt.NoFocus)         # macOS 파란 포커스 링 제거
        self._ch_cb.setFixedWidth(46); self._ch_cb._align_center = True
        row.addWidget(lbl); row.addWidget(self._dev_cb, 1); row.addWidget(self._ch_cb)
        lay.addLayout(row)
        self._dev_cb.currentIndexChanged.connect(lambda _: self.device_changed.emit(self._card_id))
        self._ch_cb.currentIndexChanged.connect(lambda _: self.channel_changed.emit(self._card_id))

    def _apply_border(self):
        # E안: 중립 카드(테두리 회색·배경 서브틀), 정체성은 스와치·번호·미터색. 선택 시 채널색 테두리로 front 표시.
        c = QColor(self._color); r, g, b = c.red(), c.green(), c.blue()
        _bg  = '#1E1E22' if is_dark() else '#F3F5FA'
        _bd  = '#34343B' if is_dark() else T('border')
        _bd_s = '#4A4A54' if is_dark() else T('accent')   # 선택 = 밝은 중립 테두리(채널색 대신)
        if self._is_selected:
            # front 표시 = 채널색 은은한 배경 틴트 + 밝은 중립 테두리 (테두리는 중립 유지 = E안)
            self.setStyleSheet(f'#specCard{{border:1px solid {_bd_s};'
                               f'border-radius:8px;background:rgba({r},{g},{b},20);padding:2px;}}')
        else:
            self.setStyleSheet(f'#specCard{{border:1px solid {_bd};'
                               f'border-radius:8px;background:{_bg};padding:2px;}}')

    def set_selected(self, on):
        on = bool(on)
        if on == self._is_selected: return
        self._is_selected = on; self._apply_border()

    def set_running(self, on):
        """카드별 Start 점 갱신 (측정 중=카드색 채움+글로우 / 꺼짐=카드색 흐린 링)."""
        self._running = bool(on)
        self._start_dot.setIcon(QIcon(_led_power_pm(self._running, 20, self._color)))

    def set_color(self, color):
        """카드 색 변경 — 체크박스·Start 점·번호 라벨·선택 틴트 모두 갱신 (곡선색과 동기)."""
        self._color = color
        self._chk.setStyleSheet(
            f'QCheckBox::indicator{{width:13px;height:13px;border:1.5px solid {color};'
            f'border-radius:3px;background:transparent;}}'
            f'QCheckBox::indicator:checked{{background:{color};image:none;}}')
        self._num_label.setStyleSheet(f'color:{color};background:transparent;font-size:11px;font-weight:bold;')
        self._start_dot.setIcon(QIcon(_led_power_pm(self._running, 20, color)))
        self._apply_border()

    def set_name(self, name):
        self._name = name or ''
        self._num_label.setText(self._name or self._default_name)

    def set_number(self, n):
        """표시 번호(위치 기반)를 설정. 사용자 지정 이름이 없을 때만 라벨에 반영."""
        self._default_name = str(n)
        if not self._name:
            self._num_label.setText(self._default_name)

    def _begin_rename(self):
        begin_inline_rename(self, self._num_label, self._on_renamed)

    def _on_renamed(self, txt):
        self._name = txt
        self._num_label.setText(txt or self._default_name)
        self.renamed.emit(self._card_id, txt)

    def mousePressEvent(self, e):
        self.selected.emit(self._card_id)
        super().mousePressEvent(e)

    def mouseDoubleClickEvent(self, e):
        # 카드 본문 더블클릭 → 이름 편집 (자식 콤보/체크박스는 자체 처리)
        self._begin_rename()
        super().mouseDoubleClickEvent(e)

    def contextMenuEvent(self, e):
        # 우클릭 → 카드 액션 메뉴(인라인 ✕ 대체). 이름 변경은 항상, 삭제는 primary가 아닐 때만.
        from PyQt5.QtWidgets import QMenu
        self.selected.emit(self._card_id)
        m = QMenu(self)
        a_rename = m.addAction(_tx('Rename'))
        a_rename.triggered.connect(self._begin_rename)
        a_color = m.addAction(_tx('Change color…'))
        a_color.triggered.connect(lambda: self.color_requested.emit(self._card_id))
        if not self._is_primary:
            m.addSeparator()
            a_del = m.addAction(_tx('Delete'))
            a_del.triggered.connect(lambda: self.remove_requested.emit(self._card_id))
        m.exec_(e.globalPos())

    def device_idx(self):  return self._dev_cb.currentData()
    def device_name(self): return self._dev_cb.currentText()
    def channel(self):     return self._ch_cb.currentData() or 0

    def set_device(self, idx):
        for i in range(self._dev_cb.count()):
            if self._dev_cb.itemData(i) == idx:
                self._dev_cb.setCurrentIndex(i); return

    def set_channel(self, ch):
        for i in range(self._ch_cb.count()):
            if self._ch_cb.itemData(i) == ch:
                self._ch_cb.setCurrentIndex(i); return

    def set_channel_list(self, n_ch):
        self._ch_cb.blockSignals(True)
        cur = self._ch_cb.currentData()
        self._ch_cb.clear()
        for i in range(max(n_ch, 1)):
            self._ch_cb.addItem(f'Ch {i+1}', i)
        if cur is not None:
            for i in range(self._ch_cb.count()):
                if self._ch_cb.itemData(i) == cur: self._ch_cb.setCurrentIndex(i); break
        self._ch_cb.blockSignals(False)

    def update_level(self, db, peak_db=None):
        self._meter.set_level(db, peak_db); self._db_lbl.setText(f'{db:.0f}')

    def reset(self):
        self._meter.reset(); self._db_lbl.setText('—')


class _MeasCard(QFrame):
    """측정 채널 카드 — 레벨 바 + Meas 장치 선택 + 딜레이 + Start/Stop."""
    start_clicked      = pyqtSignal()
    stop_clicked       = pyqtSignal()
    find_delay_clicked = pyqtSignal()
    delete_clicked     = pyqtSignal()
    selected           = pyqtSignal()   # 카드 본문 클릭 → 곡선 맨 앞으로
    renamed            = pyqtSignal(str)  # 카드 이름 변경 (새 이름)
    graph_toggled      = pyqtSignal(bool) # 그래프 표시 ON/OFF (분석은 계속)
    avg_include_toggled = pyqtSignal(int, bool)  # (card_id, included) — 라이브 평균 참여 토글
    color_changed      = pyqtSignal(str)  # 우클릭 → 곡선 색 변경 (새 색 hex)

    def __init__(self, number, color, deletable=True):
        super().__init__()
        self._color = color
        self._card_id = number
        self._running = False
        self._display_on = False  # backward-compat alias
        self._is_selected = False
        self._default_name = str(number)
        self._name = ''
        self._del_btn = None; self._meas_cb = None; self._meas_ch_cb = None; self._auto_btn = None
        self.setObjectName('measCard')
        # 세로 Fixed: 컨테이너가 좁아도 카드를 자연 높이 이하로 압축하지 않음 → 행 겹침 방지
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self._apply_card_style()
        self._lay = QVBoxLayout(self); self._lay.setContentsMargins(6, 5, 6, 6); self._lay.setSpacing(3)

        # 헤더(B안): [가시성 체크(색 사각)] [색점=Start LED] [번호] ... [dBFS 모노]
        hdr = QHBoxLayout(); hdr.setContentsMargins(0, 0, 0, 0); hdr.setSpacing(3)
        # 그래프 표시 ON/OFF 체크박스 — 분석(Start/Stop)과 무관, 곡선만 숨김/표시
        self._vis_chk = QCheckBox(); self._vis_chk.setChecked(True); self._vis_chk.setFixedWidth(17)
        self._vis_chk.setFocusPolicy(Qt.NoFocus)
        self._vis_chk.setToolTip(_tx('Show/hide graph (analysis continues)'))
        self._vis_chk.setStyleSheet(
            f'QCheckBox::indicator{{width:13px;height:13px;border:1.5px solid {color};'
            f'border-radius:3px;background:transparent;}}'
            f'QCheckBox::indicator:checked{{background:{color};image:none;}}')
        self._vis_chk.stateChanged.connect(lambda st: self.graph_toggled.emit(st == Qt.Checked))
        # 색점 = 측정 Start 토글(측정 중=카드색 채움+글로우 / 정지=흐린 링) — 스펙트럼 카드와 통일
        self._start_dot = QPushButton()
        self._start_dot.setFixedSize(20, 20); self._start_dot.setFocusPolicy(Qt.NoFocus)
        self._start_dot.setCursor(Qt.PointingHandCursor)
        self._start_dot.setToolTip(_tx('Start / stop measuring'))
        self._start_dot.setIconSize(QSize(18, 18))
        self._start_dot.setStyleSheet('QPushButton{border:none;background:transparent;padding:0;}')
        self._start_dot.setIcon(QIcon(_led_power_pm(False, 18, color)))
        self._start_dot.clicked.connect(self._on_start_stop)
        self._num_label = QLabel(self._default_name)
        self._num_label.setStyleSheet(f'color:{color};background:transparent;font-size:{FS_BODY}px;font-weight:bold;')
        self._num_label.setToolTip(_tx('Double-click to rename'))
        num_lbl = self._num_label
        self._db_lbl = QLabel('—')
        self._db_lbl.setFont(_n2_mono_font(13, QFont.Bold))
        self._db_lbl.setStyleSheet(f'color:{color};background:transparent;')
        self._db_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._db_lbl_color = color   # 마지막 적용 색 캐시
        # 텍스트 Start 버튼은 상태보관용 숨김(set_running 호환)
        self._start_btn = QPushButton('Start'); self._start_btn.hide()
        self._start_btn.clicked.connect(self._on_start_stop)
        # 평균 참여 토글 — 카드가 라이브 평균 계산에 포함되는지 선택 (기본 OFF)
        self.in_average = False
        self._avg_chk = QPushButton(); self._avg_chk.setCheckable(True)
        self._avg_chk.setChecked(False); self._avg_chk.setFocusPolicy(Qt.NoFocus)
        self._avg_chk.setCursor(Qt.PointingHandCursor)
        self._avg_chk.setToolTip(_tx('Include this source in the live average'))
        self._avg_chk.setFixedSize(22, 22); self._avg_chk.setIconSize(QSize(16, 16))
        self._avg_chk.setStyleSheet('QPushButton{border:none;background:transparent;padding:0;}')
        self._update_avg_chk_icon()
        self._avg_chk.toggled.connect(self._on_avg_include)
        hdr.addWidget(self._vis_chk); hdr.addWidget(self._start_dot); hdr.addWidget(num_lbl)
        hdr.addStretch()
        hdr.addWidget(self._avg_chk)   # Σ 토글 = 오른쪽 레벨(−) 바로 앞
        hdr.addWidget(self._db_lbl)
        # 삭제는 인라인 ✕ 대신 우클릭 메뉴(contextMenuEvent)로 통일 — 모든 카드(Reference·1번·
        # 추가) 헤더가 동일해지고, 되돌리기 힘든 삭제를 의도적 우클릭 뒤에 둠. deletable=삭제 항목 노출 여부.
        self._deletable = deletable
        self.setToolTip(_tx('Right-click: rename / delete'))
        self._lay.addLayout(hdr)

        # M (Measurement) VU 바
        mr = QHBoxLayout(); mr.setContentsMargins(0, 0, 0, 0); mr.setSpacing(4)
        self._ml = QLabel('M'); self._ml.setFixedWidth(10)
        self._ml.setStyleSheet(ss_text(FS_XS))
        self._m_bar = _HorizBarVU()
        mr.addWidget(self._ml); mr.addWidget(self._m_bar, 1)
        self._lay.addLayout(mr)

    def _update_avg_chk_icon(self):
        # 평균 포함=카드색 Σ, 제외=흐린 Σ
        col = self._color if self._avg_chk.isChecked() else T('text_dim')
        self._avg_chk.setIcon(QIcon(_icon_pm('sigma', 16, col)))

    def _on_avg_include(self, on):
        self.in_average = bool(on)
        self._update_avg_chk_icon()
        self.avg_include_toggled.emit(self._card_id, self.in_average)

    def _del_btn_ss(self):
        return (f'QPushButton{{background:transparent;color:{T("text_dim")};border:none;'
                f'font-size:{FS_LG}px;padding:0;font-weight:bold;}}'
                f'QPushButton:hover{{color:{T("red")};}}')

    def _start_btn_ss(self):
        _g = QColor(T('accent')); _gr, _gg, _gb = _g.red(), _g.green(), _g.blue()
        return (f'QPushButton{{background:transparent;color:{T("accent")};'
                f'border:1px solid rgba({_gr},{_gg},{_gb},120);'
                f'font-size:{FS_XS}px;padding:0 5px;border-radius:{RADIUS_SM}px;font-weight:bold;}}'
                f'QPushButton:hover{{border-color:{T("accent")};}}')

    def _cb_style(self):
        # B안 flat 셀 — Fusion 회색 배경 없이 투명+테두리(콤보 자체는 _flat_cell 페인트가 담당)
        _bd = '#34343B' if is_dark() else T('border')
        return (f'QComboBox{{background:transparent;color:{T("text")};border:1px solid {_bd};'
                f'border-radius:8px;padding:1px 8px;font-size:{FS_SM}px;min-height:22px;}}'
                f'QComboBox::drop-down{{width:0;border:none;}}'
                f'QComboBox::down-arrow{{width:0;height:0;image:none;}}')

    def _delay_spin_ss(self):
        _bd = '#34343B' if is_dark() else T('border')
        return (f'QDoubleSpinBox{{background:transparent;color:{T("text")};border:1px solid {_bd};'
                f'border-radius:8px;padding:{PAD_SM};font-family:Menlo;font-size:{FS_SM}px;}}')

    def _auto_btn_ss(self):
        _bd = '#34343B' if is_dark() else T('border')
        return (f'QPushButton{{background:transparent;color:{T("text_dim")};'
                f'border:1px solid {_bd};font-size:{FS_XS}px;padding:0 6px;border-radius:8px;}}'
                f'QPushButton:hover{{color:{T("text")};border-color:#4A4A54;}}')

    def restyle(self):
        """테마 토글(다크↔라이트) 시 인라인-구운 색 재적용 — 카드 프레임/콤보/딜레이/버튼."""
        self._apply_card_style()
        if hasattr(self, '_start_dot'):
            self._start_dot.setIcon(QIcon(_led_power_pm(self._running, 18, self._color)))
        self._ml.setStyleSheet(ss_text(FS_XS))
        if self._del_btn is not None: self._del_btn.setStyleSheet(self._del_btn_ss())
        if self._meas_cb is not None:
            _ss = self._cb_style(); self._meas_cb.setStyleSheet(_ss); self._meas_ch_cb.setStyleSheet(_ss)
        if hasattr(self, '_delay_spin'): self._delay_spin.setStyleSheet(self._delay_spin_ss())
        if self._auto_btn is not None: self._auto_btn.setStyleSheet(self._auto_btn_ss())
        if hasattr(self, '_avg_chk'): self._update_avg_chk_icon()

    def add_device_row(self, meas_cb, meas_ch_cb):
        """Meas 장치 선택 드롭다운 + 딜레이 행을 카드 내부로 임베드."""
        self._lay.addWidget(hsep())
        # Meas device row
        row = QHBoxLayout(); row.setContentsMargins(0, 0, 0, 0); row.setSpacing(3)
        lbl = QLabel('Meas'); lbl.setFixedWidth(30)
        lbl.setStyleSheet(ss_text(FS_XS))
        # 카드 내부 콤보 — 전역 QSS의 반투명 그라디언트(검정 바탕 위에서 까맣게 보임)를
        # 카드와 어울리는 불투명 배경으로 덮어쓴다. (restyle()로 테마 토글 시 재적용)
        self._meas_cb = meas_cb; self._meas_ch_cb = meas_ch_cb
        _cb_ss = self._cb_style()
        _bd = '#34343B' if is_dark() else T('border')
        for _cb in (meas_cb, meas_ch_cb):
            _cb.setStyleSheet(_cb_ss)
            if isinstance(_cb, RoundComboBox):
                _cb._flat_cell = True; _cb._flat_border = _bd   # Fusion 회색배경 제거
        meas_ch_cb._align_center = True; meas_ch_cb._grid_popup = True
        meas_cb._elide_to_width = True
        meas_cb.setMinimumWidth(100); meas_ch_cb.setMinimumWidth(44)
        row.addWidget(lbl); row.addWidget(meas_cb, 1); row.addWidget(meas_ch_cb)
        self._lay.addLayout(row)
        # Delay row
        d_row = QHBoxLayout(); d_row.setContentsMargins(0, 0, 0, 0); d_row.setSpacing(3)
        d_lbl = QLabel('Delay'); d_lbl.setFixedWidth(30)
        d_lbl.setStyleSheet(ss_text(FS_XS))
        self._delay_spin = QDoubleSpinBox()
        self._delay_spin.setRange(-2000, 2000); self._delay_spin.setDecimals(2)
        self._delay_spin.setSingleStep(0.5); self._delay_spin.setValue(0.0)
        self._delay_spin.setSuffix(' ms')
        self._delay_spin.setMinimumWidth(82); self._delay_spin.setFixedHeight(22)
        self._delay_spin.setButtonSymbols(QDoubleSpinBox.NoButtons)
        self._delay_spin.setAlignment(Qt.AlignCenter)
        self._delay_spin.setStyleSheet(self._delay_spin_ss())
        # 거리(m) 보조 라벨 — _DELAY_UNIT 이 m/both 일 때만 노출. 입력은 ms 유지.
        self._m_lbl = QLabel(''); self._m_lbl.setStyleSheet(ss_text(FS_XS))
        self._m_lbl.setAlignment(Qt.AlignVCenter)
        self._delay_spin.valueChanged.connect(self._update_m_lbl)
        auto_btn = QPushButton(' Auto'); auto_btn.setIcon(_icon('search',13)); auto_btn.setFixedHeight(22)
        self._auto_btn = auto_btn
        auto_btn.setStyleSheet(self._auto_btn_ss())
        auto_btn.clicked.connect(self.find_delay_clicked)
        d_row.addWidget(d_lbl); d_row.addWidget(self._delay_spin, 1)
        d_row.addWidget(self._m_lbl); d_row.addWidget(auto_btn)
        self._lay.addLayout(d_row)
        self._update_m_lbl()

    def _update_m_lbl(self):
        """딜레이 ms → 옆 거리(m) 라벨 갱신. _DELAY_UNIT 이 ms 면 숨김."""
        if not hasattr(self, '_m_lbl'): return
        if delay_unit() in ('m', 'both'):
            self._m_lbl.setText(f'= {ms_to_m(self._delay_spin.value()):.2f} m')
            self._m_lbl.show()
        else:
            self._m_lbl.hide()

    def delay_ms(self):
        return self._delay_spin.value() if hasattr(self, '_delay_spin') else 0.0

    def set_delay(self, ms):
        if hasattr(self, '_delay_spin'):
            self._delay_spin.blockSignals(True)
            self._delay_spin.setValue(ms)
            self._delay_spin.blockSignals(False)
            self._update_m_lbl()

    def set_meas(self, db, peak_db=None):
        self._m_bar.set_rms(db, peak_db)
        c = T('red') if db > METER_RED_DB else T('yellow') if db > METER_YELLOW_DB else self._color
        if c != self._db_lbl_color:   # 존(색) 바뀔 때만 재적용 (모노 폰트는 setFont로 유지)
            self._db_lbl.setStyleSheet(f'color:{c};background:transparent;')
            self._db_lbl_color = c
        self._db_lbl.setText(f'{db:.0f}')

    def set_ref(self, db):
        pass  # Ref is shared, shown in Ref section

    def reset(self):
        self._m_bar.reset()
        if self._db_lbl_color != self._color:
            self._db_lbl.setStyleSheet(f'color:{self._color};background:transparent;')
            self._db_lbl_color = self._color
        self._db_lbl.setText('—')

    def _on_start_stop(self):
        if self._running:
            self.stop_clicked.emit()
        else:
            self.start_clicked.emit()

    def _apply_card_style(self):
        # B안 — 중립 테두리(색 식별은 스와치·색점·번호·미터). 선택=밝은 중립+색 틴트(스펙트럼 카드와 통일).
        _c = QColor(self._color); _r, _g, _b = _c.red(), _c.green(), _c.blue()
        _bg  = '#1E1E22' if is_dark() else '#F3F5FA'
        _bd  = '#34343B' if is_dark() else T('border')
        _bd_s = '#4A4A54' if is_dark() else T('accent')
        if self._is_selected:
            self.setStyleSheet(
                f'QFrame#measCard{{border:1px solid {_bd_s};border-radius:10px;'
                f'background:rgba({_r},{_g},{_b},20);padding:2px;}}')
        else:
            self.setStyleSheet(
                f'QFrame#measCard{{border:1px solid {_bd};border-radius:10px;'
                f'background:{_bg};padding:2px;}}')

    def set_selected(self, on):
        on = bool(on)
        if on == self._is_selected: return
        self._is_selected = on
        self._apply_card_style()

    def set_name(self, name):
        self._name = name or ''
        self._num_label.setText(self._name or self._default_name)

    def set_number(self, n):
        self._default_name = str(n)
        if not self._name:
            self._num_label.setText(self._default_name)

    def is_graph_visible(self):
        return self._vis_chk.isChecked()

    def _begin_rename(self):
        begin_inline_rename(self, self._num_label, self._on_renamed)

    def _on_renamed(self, txt):
        self._name = txt
        self._num_label.setText(txt or self._default_name)
        self.renamed.emit(txt)

    def mousePressEvent(self, e):
        self.selected.emit()
        super().mousePressEvent(e)

    def mouseDoubleClickEvent(self, e):
        self._begin_rename()
        super().mouseDoubleClickEvent(e)

    def contextMenuEvent(self, e):
        # 우클릭 → 카드 액션 메뉴(인라인 ✕ 대체). 이름 변경은 항상, 삭제는 deletable일 때만.
        from PyQt5.QtWidgets import QMenu
        self.selected.emit()
        m = QMenu(self)
        a_rename = m.addAction(_tx('Rename'))
        a_rename.triggered.connect(self._begin_rename)
        a_color = m.addAction(_tx('Change color…'))
        a_color.triggered.connect(self._pick_color)
        if self._deletable:
            m.addSeparator()
            a_del = m.addAction(_tx('Delete'))
            a_del.triggered.connect(self.delete_clicked)
        m.exec_(e.globalPos())

    def _pick_color(self):
        c = QColorDialog.getColor(QColor(self._color), self, _tx('Curve color'))
        if c.isValid():
            self.set_color(c.name())
            self.color_changed.emit(c.name())

    def set_color(self, color):
        """곡선/카드 색 변경 — 헤더 요소 색 갱신 후 재스타일."""
        self._color = color
        self._num_label.setStyleSheet(f'color:{color};background:transparent;font-size:{FS_BODY}px;font-weight:bold;')
        self._vis_chk.setStyleSheet(
            f'QCheckBox::indicator{{width:13px;height:13px;border:1.5px solid {color};'
            f'border-radius:3px;background:transparent;}}'
            f'QCheckBox::indicator:checked{{background:{color};image:none;}}')
        self._db_lbl.setStyleSheet(f'color:{color};background:transparent;'); self._db_lbl_color = color
        self._start_dot.setIcon(QIcon(_led_power_pm(self._running, 18, color)))
        self._apply_card_style()

    def set_running(self, running):
        self._running = running
        self._display_on = running  # backward-compat
        # 색점 = 측정 중이면 채움+글로우 / 정지면 흐린 링
        self._start_dot.setIcon(QIcon(_led_power_pm(running, 18, self._color)))
        self._start_btn.setText('Stop' if running else 'Start')   # 숨김 상태보관


# backward-compat alias
_PairLevelCard = _MeasCard


class _DarkTitleBar(QWidget):
    """프레임리스 창용 다크 커스텀 타이틀바 — 제목 + 닫기(✕) + 드래그 이동.
    라이트모드에서 흰색 네이티브 타이틀바가 다크 본문과 안 어울리는 문제 해결."""
    def __init__(self, win, title='', aux=None):
        super().__init__()
        self._win = win; self._drag = None
        self.setFixedHeight(34); self.setObjectName('darkTitleBar')
        self.setStyleSheet(f'#darkTitleBar{{background:{T("bg2")};}}')
        lay = QHBoxLayout(self); lay.setContentsMargins(14, 0, 8, 0); lay.setSpacing(0)
        self._full_title = title
        self._title = QLabel(title)
        self._title.setStyleSheet(f'color:{T("text")};font-size:12px;font-weight:bold;background:transparent;')
        self._title.setMinimumWidth(0)
        lay.addWidget(self._title); lay.addStretch()
        # 창별 보조 버튼(예: SPL Meter 설정 토글) — ✕ 왼쪽에 배치
        self._aux = list(aux) if aux else []
        if aux:
            for b in aux:
                b.setParent(self); lay.addWidget(b)
            lay.addSpacing(6)
        self._x = QPushButton('✕'); self._x.setFixedSize(24, 24); self._x.setCursor(Qt.PointingHandCursor)
        _x_col = '#9A9AA0' if is_dark() else T('text_dim')
        self._x.setStyleSheet(f'QPushButton{{border:none;background:transparent;color:{_x_col};font-size:13px;border-radius:6px;}}'
                              'QPushButton:hover{background:#FF453A;color:#FFFFFF;}')
        self._x.clicked.connect(self._close)
        lay.addWidget(self._x)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._elide_title()

    def _elide_title(self):
        # 우측 고정폭(보조버튼 + spacing + ✕) 제외한 공간에 맞춰 제목 elide → 글자 중간 잘림 방지
        right = sum(b.sizeHint().width() for b in self._aux) + (6 if self._aux else 0) + 24
        avail = self.width() - 14 - 8 - right
        self._title.setText(self._title.fontMetrics().elidedText(
            self._full_title, Qt.ElideRight, max(0, avail)))

    def _close(self):
        if hasattr(self._win, 'reject'):
            self._win.reject()
        else:
            self._win.close()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag = e.globalPos() - self._win.frameGeometry().topLeft(); e.accept()

    def mouseMoveEvent(self, e):
        if self._drag is not None and (e.buttons() & Qt.LeftButton):
            self._win.move(e.globalPos() - self._drag); e.accept()

    def mouseReleaseEvent(self, e):
        self._drag = None


def _add_resize_grip(win):
    """프레임리스 창에 우하단 리사이즈 그립 — 네이티브 프레임 리사이즈 대체."""
    from PyQt5.QtWidgets import QSizeGrip
    grip = QSizeGrip(win); grip.setFixedSize(15, 15); grip.setStyleSheet('background:transparent;')
    win._dark_grip = grip
    def _pos():
        try: grip.move(win.width() - 17, win.height() - 17); grip.raise_(); grip.show()
        except Exception: pass
    class _RF(QObject):
        def eventFilter(self, o, e):
            if e.type() == QEvent.Resize: _pos()
            return False
    f = _RF(win); win._dark_grip_filter = f; win.installEventFilter(f)
    QTimer.singleShot(0, _pos)


def _apply_dark_titlebar(win, resizable=False, aux=None):
    """창을 프레임리스로 + 다크 커스텀 타이틀바 부착(레이아웃 menuBar 슬롯).
    resizable=True 면 우하단 리사이즈 그립 추가. 바 삽입은 레이아웃 준비 후로 지연.
    aux: ✕ 왼쪽에 넣을 보조 버튼 리스트(창별 토글 등)."""
    try:
        win.setWindowFlags((win.windowFlags() | Qt.FramelessWindowHint))
    except Exception:
        return
    def _ins():
        try:
            lay = win.layout()
            if lay is not None and lay.menuBar() is None:
                bar = _DarkTitleBar(win, win.windowTitle(), aux=aux)
                win._dark_titlebar = bar
                lay.setMenuBar(bar)
        except Exception:
            pass
    QTimer.singleShot(0, _ins)
    if resizable:
        _add_resize_grip(win)


def _apply_native_titlebar_dark(win):
    """macOS: 팝아웃 top-level 창의 네이티브 타이틀바를 메인 창과 동일하게 —
    (1) FullSizeContentView+투명 → 본문 상단 브랜드 헤더가 타이틀바 행에 렌더되고
    (2) 네이티브 제목 텍스트 숨김 (브랜드 헤더로 대체)
    (3) 테마색 appearance(다크=DarkAqua). winId() 유효해야 하므로 show() 이후 호출."""
    if _pl.system() == 'Windows':
        _apply_windows_titlebar_dark(win)   # 윈도우는 네이티브 타이틀바를 다크로
        return
    if sys.platform != 'darwin':
        return
    try:
        import ctypes
        objc = ctypes.cdll.LoadLibrary('/usr/lib/libobjc.A.dylib')
        objc.sel_registerName.restype = ctypes.c_void_p
        objc.sel_registerName.argtypes = [ctypes.c_char_p]
        objc.objc_getClass.restype = ctypes.c_void_p
        objc.objc_getClass.argtypes = [ctypes.c_char_p]
        def sel(n): return objc.sel_registerName(n.encode())
        def msg(restype, obj, sel_name, *args):
            f = objc.objc_msgSend
            f.restype = restype
            f.argtypes = [ctypes.c_void_p, ctypes.c_void_p] + [type(a) for a in args]
            return f(obj, sel(sel_name), *args)
        ns_view = ctypes.c_void_p(int(win.winId()))
        ns_window = msg(ctypes.c_void_p, ns_view, 'window')
        if not ns_window:
            return
        # (1) NSFullSizeContentViewWindowMask(1<<15) — 콘텐츠를 타이틀바 영역까지 확장
        style = msg(ctypes.c_ulong, ns_window, 'styleMask')
        msg(None, ns_window, 'setStyleMask:', ctypes.c_ulong(style | (1 << 15)))
        # (1) 타이틀바 투명 → 뒤의 브랜드 헤더(bg2)가 비쳐 다크 바가 됨
        msg(None, ns_window, 'setTitlebarAppearsTransparent:', ctypes.c_bool(True))
        # (2) 네이티브 제목 텍스트 숨김 (NSWindowTitleHidden=1)
        msg(None, ns_window, 'setTitleVisibility:', ctypes.c_long(1))
        name = b'NSAppearanceNameDarkAqua' if is_dark() else b'NSAppearanceNameAqua'
        ns_str = msg(ctypes.c_void_p, objc.objc_getClass(b'NSString'),
                     'stringWithUTF8String:', ctypes.c_char_p(name))
        appearance = msg(ctypes.c_void_p, objc.objc_getClass(b'NSAppearance'),
                         'appearanceNamed:', ctypes.c_void_p(ns_str))
        if appearance:
            msg(None, ns_window, 'setAppearance:', ctypes.c_void_p(appearance))
        new_style = msg(ctypes.c_ulong, ns_window, 'styleMask')
        _diag('popout_titlebar', win=type(win).__name__,
              style_before=int(style), style_after=int(new_style),
              fullsize=bool(int(new_style) & (1 << 15)))
    except Exception as e:
        try: _diag('popout_titlebar_fail', err=str(e))
        except Exception: pass


def _apply_app_dark_appearance():
    """macOS: NSApplication 전체 외형을 앱 테마(다크=DarkAqua)로 강제.
    창별 setAppearance(_apply_native_titlebar_dark)만으론 **별도 NSWindow로 뜨는
    컨텍스트 메뉴(QMenu)·네이티브 팝업**이 커버 안 됨 → 시스템이 라이트 모드일 때
    우클릭 메뉴가 흰색으로 떴다. NSApp.appearance를 지정하면 그 팝업들도 다크로 통일."""
    if sys.platform != 'darwin':
        return
    try:
        import ctypes
        objc = ctypes.cdll.LoadLibrary('/usr/lib/libobjc.A.dylib')
        objc.sel_registerName.restype = ctypes.c_void_p
        objc.sel_registerName.argtypes = [ctypes.c_char_p]
        objc.objc_getClass.restype = ctypes.c_void_p
        objc.objc_getClass.argtypes = [ctypes.c_char_p]
        def sel(n): return objc.sel_registerName(n.encode())
        def msg(restype, obj, sel_name, *args):
            f = objc.objc_msgSend
            f.restype = restype
            f.argtypes = [ctypes.c_void_p, ctypes.c_void_p] + [type(a) for a in args]
            return f(obj, sel(sel_name), *args)
        ns_app = msg(ctypes.c_void_p, objc.objc_getClass(b'NSApplication'), 'sharedApplication')
        if not ns_app:
            return
        name = b'NSAppearanceNameDarkAqua' if is_dark() else b'NSAppearanceNameAqua'
        ns_str = msg(ctypes.c_void_p, objc.objc_getClass(b'NSString'),
                     'stringWithUTF8String:', ctypes.c_char_p(name))
        appearance = msg(ctypes.c_void_p, objc.objc_getClass(b'NSAppearance'),
                         'appearanceNamed:', ctypes.c_void_p(ns_str))
        if appearance:
            msg(None, ns_app, 'setAppearance:', ctypes.c_void_p(appearance))
        try: _diag('app_appearance', theme=theme(), ok=bool(appearance))
        except Exception: pass
    except Exception as e:
        try: _diag('app_appearance_fail', err=str(e))
        except Exception: pass


def _apply_windows_titlebar_dark(win):
    """Windows: 네이티브 타이틀바를 앱 테마에 맞춰 다크/라이트로(DWM immersive dark mode).
    맥의 통합 타이틀바처럼 본문과 완전히 합쳐지진 않지만, 어두운 앱 위에 흰 타이틀바가
    뜨는 충돌을 없앤다. 비-Windows에선 no-op. winId() 유효해야 하므로 show() 이후 호출."""
    if _pl.system() != 'Windows':
        return
    try:
        import ctypes
        hwnd = int(win.winId())
        val = ctypes.c_int(1 if is_dark() else 0)
        dwm = ctypes.windll.dwmapi
        # DWMWA_USE_IMMERSIVE_DARK_MODE = 20 (Win10 20H1+/Win11). 구버전 빌드는 19.
        res = dwm.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(val), ctypes.sizeof(val))
        if res != 0:
            dwm.DwmSetWindowAttribute(hwnd, 19, ctypes.byref(val), ctypes.sizeof(val))
        _diag('win_titlebar_dark', dark=(is_dark()), res=int(res))
    except Exception as e:
        try: _diag('win_titlebar_dark_fail', err=str(e))
        except Exception: pass
        try: _alog.debug(f'native titlebar dark 실패: {e}')
        except Exception: pass


def _brand_logo_html(subtitle):
    """브랜드 헤더 워드마크 RichText — SPECTRA(accent) + 부제(text_dim). 테마색 반영."""
    # ⚠️ font-family는 <span>에선 무시되고 <div>(블록)에서만 상속됨(Qt 리치텍스트 특성) → div로 감싼다.
    return (f'<div style="font-family:\'{FONT_FAMILY}\';">'
            f'<span style="font-size:14px;font-weight:700;color:{T("accent")};'
            f'letter-spacing:3px;">SPECTRA</span>'
            f'&nbsp;&nbsp;<span style="font-size:11px;color:{T("text_dim")};">{subtitle}</span></div>')


# _CollapseBtn — v2.0 분해: spectra/ui/widgets.py 로 이동, re-import
from spectra.ui.widgets import _CollapseBtn
class _BrandHeaderBar(QWidget):
    """팝아웃 상단 브랜드 헤더 — 더블클릭 시 창 최대화↔복원 토글(메인 창 헤더와 동일 UX)."""
    def mouseDoubleClickEvent(self, e):
        w = self.window()
        if w is not None:
            w.showNormal() if w.isMaximized() else w.showMaximized()
        super().mouseDoubleClickEvent(e)


def _make_brand_header(subtitle):
    """팝아웃 본문 상단 브랜드 헤더 — 그라디언트 마크 + SPECTRA 워드마크 + 탭 이름(가운데),
    우측에 툴바 접기 토글(_toggle_btn). 더블클릭=최대화/복원. (TF self._hdr와 동일 높이 40)."""
    bar = _BrandHeaderBar(); bar.setFixedHeight(40); bar.setObjectName('popoutBrandHdr')
    bar.setStyleSheet(f'#popoutBrandHdr{{background:{T("bg2")};}}')
    bar._subtitle = subtitle
    hl = QHBoxLayout(bar); hl.setContentsMargins(16, 0, 16, 0); hl.setSpacing(9)
    mark = QLabel(); mark.setPixmap(_spectra_mark(20)); mark.setStyleSheet('background:transparent;')
    logo = QLabel(); logo.setTextFormat(Qt.RichText); logo.setStyleSheet('background:transparent;')
    logo.setText(_brand_logo_html(subtitle)); bar._logo = logo
    # 라벨은 마우스 투명 → 헤더가 더블클릭을 받아 최대화 토글 (토글 버튼은 그대로 동작)
    for _lb in (mark, logo):
        _lb.setAttribute(Qt.WA_TransparentForMouseEvents, True)
    toggle = _CollapseBtn(); bar._toggle_btn = toggle
    hl.addSpacing(30)          # 우측 토글 버튼 폭만큼 좌측 보정 → 로고 진짜 가운데
    hl.addStretch(1); hl.addWidget(mark); hl.addWidget(logo); hl.addStretch(1)
    hl.addWidget(toggle)
    return bar


def _restyle_brand_header(bar):
    """테마 토글 시 브랜드 헤더 배경/워드마크 색 갱신 (팝아웃 타이틀바가 라이트에서 검게 남는 문제 방지)."""
    try:
        bar.setStyleSheet(f'#popoutBrandHdr{{background:{T("bg2")};}}')
        if hasattr(bar, '_logo'):
            bar._logo.setText(_brand_logo_html(getattr(bar, '_subtitle', '')))
    except Exception:
        pass


def _dialog_brand_header(subtitle, mark_h=20):
    """다이얼로그 상단 브랜드 헤더(가운데 정렬) — 그라디언트 웨이브 마크 + SPECTRA 워드마크
    + 부제, 하단 시그니처 그라디언트 언더라인. 팝아웃 헤더와 톤 통일(라이브 렌더 아님)."""
    box = QWidget(); box.setObjectName('dlgBrandHdr')
    v = QVBoxLayout(box); v.setContentsMargins(0, 0, 0, 0); v.setSpacing(0)
    bar = QWidget(); bar.setObjectName('dlgBrandBar'); bar.setFixedHeight(46)
    bar.setStyleSheet(f'#dlgBrandBar{{background:{T("panel")};}}')
    h = QHBoxLayout(bar); h.setContentsMargins(16, 0, 16, 0); h.setSpacing(9)
    mark = QLabel(); mark.setPixmap(_spectra_mark(mark_h)); mark.setStyleSheet('background:transparent;')
    logo = QLabel(); logo.setTextFormat(Qt.RichText); logo.setStyleSheet('background:transparent;')
    logo.setText(_brand_logo_html(subtitle))
    h.addStretch(1); h.addWidget(mark); h.addWidget(logo); h.addStretch(1)
    line = QFrame(); line.setObjectName('dlgBrandLine'); line.setFixedHeight(2)
    line.setStyleSheet(f'#dlgBrandLine{{background:{_SPECTRA_GRAD_QSS};border:none;}}')
    v.addWidget(bar); v.addWidget(line)
    return box


def _grad_topline():
    """브랜드 다이얼로그 상단의 SPECTRA 그라디언트 3px 라인 QFrame."""
    f = QFrame(); f.setFixedHeight(3)
    f.setStyleSheet(f'background:{_SPECTRA_GRAD_QSS};border:none;')
    return f
