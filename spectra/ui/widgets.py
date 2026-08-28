"""UI 위젯 — 작은 커스텀 버튼/배지 (v2.0 분해, 동작 0 변경)."""
import time
from PyQt5.QtWidgets import QPushButton, QLabel, QWidget
from PyQt5.QtGui import QColor, QPainter, QPainterPath, QPen, QPolygonF, QFont
from PyQt5.QtCore import Qt, QPointF, QRectF, pyqtSignal
from spectra.core.config import T, is_dark
from spectra.core.i18n import _tx
from spectra.ui.draw import (METER_DB_MIN, METER_PEAK_DECAY, METER_TAU_ATTACK, METER_TAU_RELEASE, _draw_zone_meter_h)
from spectra.ui.tokens import FONT_FAMILY, FS_BODY, RADIUS_SM, CF_ANNO, _qfont


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
