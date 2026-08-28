"""아이콘/N2 헬퍼 — Lucide 아이콘(SVG→QPixmap) + hover/색 헬퍼.

v2.0 분해: wayaudo2.py에서 이동(동작 0 변경).
"""
from PyQt5.QtGui import QPainter, QPixmap, QColor, QPen, QRadialGradient, QIcon
from PyQt5.QtCore import Qt, QRectF, QPointF
from spectra.core.config import T, is_dark, theme
from spectra.ui.colors import _SPECTRA_GRAD_DEFS


_LUCIDE_ICONS = {
    'search':   ('<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>', False),
    'sigma':    ('<path d="M18 7V4H6l6 8-6 8h12v-3"/>', False),
    'folder':   ('<path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/>', False),
    'hourglass':('<path d="M5 22h14"/><path d="M5 2h14"/><path d="M17 22v-4.172a2 2 0 0 0-.586-1.414L12 12l-4.414 4.414A2 2 0 0 0 7 17.828V22"/><path d="M7 2v4.172a2 2 0 0 0 .586 1.414L12 12l4.414-4.414A2 2 0 0 0 17 6.172V2"/>', False),
    'download': ('<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" x2="12" y1="15" y2="3"/>', False),
    'upload':   ('<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" x2="12" y1="3" y2="15"/>', False),
    'save':     ('<path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/>', False),
    'trash':    ('<path d="M3 6h18"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><line x1="10" x2="10" y1="11" y2="17"/><line x1="14" x2="14" y1="11" y2="17"/>', False),
    'globe':    ('<circle cx="12" cy="12" r="10"/><path d="M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20"/><path d="M2 12h20"/>', False),
    'bolt':     ('<polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>', True),
    'sun':      ('<circle cx="12" cy="12" r="4"/><path d="M12 2v2"/><path d="M12 20v2"/><path d="m4.93 4.93 1.41 1.41"/><path d="m17.66 17.66 1.41 1.41"/><path d="M2 12h2"/><path d="M20 12h2"/><path d="m6.34 17.66-1.41 1.41"/><path d="m19.07 4.93-1.41 1.41"/>', False),
    'moon':     ('<path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/>', False),
    'sliders':  ('<line x1="21" x2="14" y1="4" y2="4"/><line x1="10" x2="3" y1="4" y2="4"/><line x1="21" x2="12" y1="12" y2="12"/><line x1="8" x2="3" y1="12" y2="12"/><line x1="21" x2="16" y1="20" y2="20"/><line x1="12" x2="3" y1="20" y2="20"/><line x1="14" x2="14" y1="2" y2="6"/><line x1="8" x2="8" y1="10" y2="14"/><line x1="16" x2="16" y1="18" y2="22"/>', False),
    'delta':    ('<polygon points="12 4 21 20 3 20 12 4"/>', False),
    'play':     ('<polygon points="6 3 20 12 6 21 6 3"/>', True),
    'stop':     ('<rect width="15" height="15" x="4.5" y="4.5" rx="3"/>', True),
    'mic':      ('<path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" x2="12" y1="19" y2="22"/>', False),
    'refresh':  ('<path d="M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/>', False),
    'check':    ('<path d="M20 6 9 17l-5-5"/>', False),
    'info':     ('<circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>', False),
    'audio-lines':('<path d="M2 10v3"/><path d="M6 6v11"/><path d="M10 3v18"/><path d="M14 8v7"/><path d="M18 5v13"/><path d="M22 10v3"/>', False),
    'extlink':  ('<path d="M15 3h6v6"/><path d="M10 14 21 3"/><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>', False),
    'alert-triangle':('<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><path d="M12 9v4"/><path d="M12 17h.01"/>', False),
    'help-circle':('<circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><path d="M12 17h.01"/>', False),
    # ── N2 툴바 리디자인용 (v1.9) — 각 컨트롤 직관 아이콘 ──
    'rows-2':('<rect width="18" height="18" x="3" y="3" rx="2"/><path d="M3 12h18"/>', False),                 # +Spectro (패널 2단)
    'scale-v':('<path d="M12 3v18"/><path d="M12 3h5"/><path d="M12 9h3"/><path d="M12 15h3"/><path d="M12 21h5"/>', False),  # dB 세로눈금축
    'waves':('<path d="M2 6c.6.5 1.2 1 2.5 1C7 7 7 5 9.5 5c2.6 0 2.4 2 5 2 2.5 0 2.5-2 5-2 1.3 0 1.9.5 2.5 1"/><path d="M2 12c.6.5 1.2 1 2.5 1 2.5 0 2.5-2 5-2 2.6 0 2.4 2 5 2 2.5 0 2.5-2 5-2 1.3 0 1.9.5 2.5 1"/><path d="M2 18c.6.5 1.2 1 2.5 1 2.5 0 2.5-2 5-2 2.6 0 2.4 2 5 2 2.5 0 2.5-2 5-2 1.3 0 1.9.5 2.5 1"/>', False),  # SR/Phase
    'peak-up':('<path d="M5 3h14"/><path d="m18 13-6-6-6 6"/><path d="M12 7v14"/>', False),                    # Peak (천장 화살표)
    'camera':('<path d="M14.5 4h-5L7 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-3l-2.5-3z"/><circle cx="12" cy="13" r="3"/>', False),  # Capture
    'move-vertical':('<path d="M12 2v20"/><path d="m8 6 4-4 4 4"/><path d="m8 18 4 4 4-4"/>', False),          # Range
    'gauge':('<path d="m12 14 4-4"/><path d="M3.34 19a10 10 0 1 1 17.32 0"/>', False),                         # Speed/Response
    'cpu':('<rect width="16" height="16" x="4" y="4" rx="2"/><rect width="6" height="6" x="9" y="9" rx="1"/><path d="M15 2v2"/><path d="M15 20v2"/><path d="M2 15h2"/><path d="M2 9h2"/><path d="M20 15h2"/><path d="M20 9h2"/><path d="M9 2v2"/><path d="M9 20v2"/>', False),  # TF Engine
    'spline':('<path d="M3 3v16a2 2 0 0 0 2 2h16"/><path d="M7 15c2 0 3-6 6-6s3 4 6 4"/>', False),             # TF Smooth
    'headphones':('<path d="M3 14h3a2 2 0 0 1 2 2v3a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-5a9 9 0 0 1 18 0v5a2 2 0 0 1-2 2h-1a2 2 0 0 1-2-2v-3a2 2 0 0 1 2-2h3"/>', False),  # Auralize
    'activity':('<path d="M22 12h-2.48a2 2 0 0 0-1.93 1.46l-2.35 8.36a.25.25 0 0 1-.48 0L9.24 2.18a.25.25 0 0 0-.48 0l-2.35 8.36A2 2 0 0 1 4.49 12H2"/>', False),  # IR (임펄스)
    'ruler':('<path d="M21.3 15.3a2.4 2.4 0 0 1 0 3.4l-2.6 2.6a2.4 2.4 0 0 1-3.4 0L2.7 8.7a2.41 2.41 0 0 1 0-3.4l2.6-2.6a2.41 2.41 0 0 1 3.4 0Z"/><path d="m14.5 12.5 2-2"/><path d="m11.5 9.5 2-2"/><path d="m8.5 6.5 2-2"/><path d="m17.5 15.5 2-2"/>', False),  # TF Units
    'target':('<circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/>', False),  # Stereo Target
    'panel-right':('<rect width="18" height="18" x="3" y="3" rx="2"/><path d="M15 3v18"/>', False),            # 우측 패널 토글
    # 탭 아이콘 (겹침 회피) — TF=비교(기준↔측정), Stereo=음량(스피커)
    'git-compare':('<circle cx="18" cy="18" r="3"/><circle cx="6" cy="6" r="3"/><path d="M13 6h3a2 2 0 0 1 2 2v7"/><path d="M11 18H8a2 2 0 0 1-2-2V9"/>', False),  # Transfer Function 탭
    'volume2':('<polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M15.54 8.46a5 5 0 0 1 0 7.07"/><path d="M19.07 4.93a10 10 0 0 1 0 14.14"/>', False),  # Stereo Loudness 탭
    'palette':('<path d="M12 2C6.5 2 2 6.5 2 12s4.5 10 10 10c.926 0 1.648-.746 1.648-1.688 0-.437-.18-.835-.437-1.125-.29-.289-.438-.652-.438-1.125a1.64 1.64 0 0 1 1.668-1.668h1.996c3.051 0 5.555-2.503 5.555-5.554C21.965 6.012 17.461 2 12 2z"/><circle cx="6.5" cy="11.5" r="1.1"/><circle cx="9.5" cy="7.5" r="1.1"/><circle cx="14.5" cy="7.5" r="1.1"/><circle cx="17.5" cy="11.5" r="1.1"/>', False),  # Color 버튼(누락됐던 것)
    'panel-bottom':('<rect width="18" height="18" x="3" y="3" rx="2"/><path d="M3 15h18"/>', False),  # (하단 패널)
    'panel-left':('<rect width="18" height="18" x="3" y="3" rx="2"/><path d="M9 3v18"/>', False),  # 캡쳐 드로어 토글(우측 panel-right와 짝)
    'clock':('<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>', False),  # HOLD(누락됐던 것)
}


def _icon_pm(name, size=16, color=None):
    """Lucide 아이콘 → 레티나 QPixmap (툴바 QLabel 표시용). _icon과 동일 렌더."""
    from PyQt5.QtSvg import QSvgRenderer
    from PyQt5.QtCore import QByteArray
    if color is None:
        color = '#C7CAD1' if is_dark() else '#46566e'
    entry = _LUCIDE_ICONS.get(name)
    dpr = 3
    pm = QPixmap(size * dpr, size * dpr); pm.setDevicePixelRatio(dpr); pm.fill(Qt.transparent)
    if entry is None:
        return pm
    inner, filled = entry
    if filled:
        attrs = f'fill="{color}" stroke="{color}" stroke-width="1.7" stroke-linejoin="round" stroke-linecap="round"'
    else:
        attrs = f'fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"'
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" {attrs}>{inner}</svg>'
    p = QPainter(pm); p.setRenderHint(QPainter.Antialiasing, True)
    QSvgRenderer(QByteArray(svg.encode())).render(p, QRectF(0, 0, size, size)); p.end()
    return pm

def _n2_hover_ss(obj='n2cell', radius=7):
    hov = 'rgba(255,255,255,0.07)' if is_dark() else 'rgba(0,0,0,0.06)'
    return (f'#{obj}{{background:transparent;border-radius:{radius}px;}}'
            f'#{obj}:hover{{background:{hov};}}')

def _n2_icon_color(active=False):
    if active: return T('accent')
    return '#C7CAD1' if is_dark() else '#5A6B86'

def _n2_led_color(on):
    if on: return T('accent')
    return '#3A3A42' if is_dark() else '#C7C7CC'


def _led_power_pm(live, size=20, color='#6E9BFF'):
    """카드별 Start 점(색 점 겸용) — 측정 중=카드색 채운 원+글로우 / 꺼짐=카드색 흐린 링.
    항상 카드 색으로 정체성 유지. 안티앨리어싱 페인트 픽스맵."""
    dpr = 3
    pm = QPixmap(int(size * dpr), int(size * dpr)); pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)
    p = QPainter(pm); p.setRenderHint(QPainter.Antialiasing, True)
    cx = cy = size / 2.0
    # 원 지름을 왼쪽 체크박스(13px 사각)와 맞춤 — 아이콘 캔버스 20px 기준 반지름 ~6.5px.
    r_fill = size * 0.325
    if live:
        g = QRadialGradient(QPointF(cx, cy), size * 0.50)
        c0 = QColor(color); c0.setAlpha(150); c1 = QColor(color); c1.setAlpha(0)
        g.setColorAt(0.0, c0); g.setColorAt(1.0, c1)
        p.setPen(Qt.NoPen); p.setBrush(g); p.drawEllipse(QPointF(cx, cy), size * 0.50, size * 0.50)
        p.setBrush(QColor(color)); p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(cx, cy), r_fill, r_fill)
    else:
        pen = QPen(); pen.setWidthF(size * 0.12)
        c = QColor(color); c.setAlpha(125); pen.setColor(c)
        p.setPen(pen); p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(cx, cy), r_fill - size * 0.06, r_fill - size * 0.06)
    p.end()
    return pm


# 캡쳐 일괄 표시/숨김 토글 전용 아이콘 — SPECTRA 시그니처 웨이브(캡쳐=스펙트럼 곡선 은유).
# 기존 Lucide 아이콘 재사용 금지(브랜드 정체성) → 그라디언트 마크를 미니 글리프로 자체 렌더.
_WAVE_TOGGLE_PATH = 'M2,12 C5,12 5,7 8,7 S11,17 14,12 S17,7 20,7 S22,12 22,12'
_wave_toggle_icon_cache = {}
def _wave_toggle_icon(on, size=16):
    """ON=브랜드 그라디언트 웨이브(=모두 표시), OFF=흐린 회색 웨이브+사선(=모두 숨김).
    OFF 회색은 테마 적응. 한 번 렌더 후 (on,size,theme)로 캐시."""
    from PyQt5.QtGui import QIcon
    from PyQt5.QtSvg import QSvgRenderer
    from PyQt5.QtCore import QByteArray
    key = (on, size, theme())
    ic = _wave_toggle_icon_cache.get(key)
    if ic is not None:
        return ic
    if on:
        body = (f'{_SPECTRA_GRAD_DEFS}'
                f'<path d="{_WAVE_TOGGLE_PATH}" fill="none" stroke="url(#g)" stroke-width="2.4" '
                f'stroke-linecap="round" stroke-linejoin="round"/>')
    else:
        gray  = '#6B6B70' if is_dark() else '#9AA0AA'
        slash = '#9A9AA0' if is_dark() else '#6B7280'
        body = (f'<path d="{_WAVE_TOGGLE_PATH}" fill="none" stroke="{gray}" stroke-width="2.2" '
                f'stroke-linecap="round" stroke-linejoin="round"/>'
                f'<line x1="5" y1="19" x2="19" y2="5" stroke="{slash}" stroke-width="2.2" stroke-linecap="round"/>')
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">{body}</svg>'
    dpr = 2
    pm = QPixmap(size * dpr, size * dpr); pm.setDevicePixelRatio(dpr); pm.fill(Qt.transparent)
    p = QPainter(pm); p.setRenderHint(QPainter.Antialiasing, True)
    QSvgRenderer(QByteArray(svg.encode())).render(p, QRectF(0, 0, size, size))
    p.end()
    ic = QIcon(pm); _wave_toggle_icon_cache[key] = ic
    return ic
