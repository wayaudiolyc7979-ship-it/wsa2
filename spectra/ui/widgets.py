"""UI 위젯 — 작은 커스텀 버튼/배지 (v2.0 분해, 동작 0 변경)."""
from PyQt5.QtWidgets import QPushButton
from PyQt5.QtGui import QColor, QPainter, QPainterPath, QPen, QPolygonF
from PyQt5.QtCore import Qt, QPointF, QRectF
from spectra.core.config import T


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
