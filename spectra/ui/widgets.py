"""UI 위젯 — 작은 커스텀 버튼/배지 (v2.0 분해, 동작 0 변경)."""
from PyQt5.QtWidgets import QPushButton, QLabel, QWidget
from PyQt5.QtGui import QColor, QPainter, QPainterPath, QPen, QPolygonF, QFont
from PyQt5.QtCore import Qt, QPointF, QRectF
from spectra.core.config import T
from spectra.ui.tokens import FONT_FAMILY, FS_BODY, RADIUS_SM


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
