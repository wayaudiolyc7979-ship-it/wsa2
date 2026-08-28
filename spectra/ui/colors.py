"""브랜드 색상 헬퍼 — HSL 스펙트럼·브랜드 그라디언트 샘플·rgba CSS·메트릭색.

v2.0 분해: wayaudo2.py에서 이동(동작 0 변경). is_dark()로 라이트/다크 대비 조정.
"""
from PyQt5.QtGui import QColor, QLinearGradient, QPen, QBrush, QPixmap, QPainter
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication
from spectra.core.config import is_dark, T

_SPECTRA_GRAD_STOPS = [(0.0,'#1FA2FF'),(0.28,'#4E7DF0'),(0.52,'#9B5DE5'),
                       (0.72,'#F15BB5'),(0.86,'#FF9F0A'),(1.0,'#FF453A')]

def _spec_color(frac: float, lightness: int = 160, alpha: int = 255) -> 'QColor':
    """frac 0→1 을 violet(260°)→red(0°) HSL 스펙트럼 QColor로 변환.
    라이트 테마: 흰 배경 대비 위해 명도를 낮춰 진하고 채도 높은 보석톤으로 (스코프 가독성)."""
    hue = int((1.0 - max(0.0, min(1.0, frac))) * 260)
    if (not is_dark()):
        lightness = max(55, min(135, int(lightness * 0.52)))
    c = QColor.fromHsl(hue, 255, lightness)
    c.setAlpha(alpha)
    return c

def _brand_color(frac, lightness=160, alpha=255):
    """SPECTRA 브랜드 그라디언트(_SPECTRA_GRAD_STOPS) 샘플 → QColor.
    _spec_color와 동일 시그니처라 라우드니스 캔버스에서 지역 치환으로 드롭인 교체 가능.
    lightness(기본160) 비율로 명도 조절(글로우=낮음/크리스프=높음), alpha 투명도."""
    f = max(0.0, min(1.0, frac))
    stops = _SPECTRA_GRAD_STOPS
    col = QColor(stops[-1][1])
    for i in range(len(stops) - 1):
        a, ca = stops[i]; b, cb = stops[i + 1]
        if a <= f <= b:
            t = (f - a) / (b - a) if b > a else 0.0
            ca = QColor(ca); cb = QColor(cb)
            col = QColor(int(ca.red() + (cb.red() - ca.red()) * t),
                         int(ca.green() + (cb.green() - ca.green()) * t),
                         int(ca.blue() + (cb.blue() - ca.blue()) * t))
            break
    h, s, l, _ = col.getHsl()
    nl = max(0, min(255, int(l * (lightness / 160.0))))
    if (not is_dark()):
        nl = max(40, min(150, int(nl * 0.6)))
    c = QColor.fromHsl(h, s, nl); c.setAlpha(alpha)
    return c

def _rgba_css(hexcol, alpha):
    """'#RRGGBB' → 'rgba(r,g,b,a)' CSS 문자열 (틴트 배경/보더용)."""
    c = QColor(hexcol)
    return f'rgba({c.red()},{c.green()},{c.blue()},{alpha})'

def _metric_col(hue, light=160):
    """라우드니스 메트릭 값 색 (HSL). 라이트 테마: 흰 바 대비 위해 명도 낮춤."""
    if (not is_dark()):
        light = max(70, min(150, int(light * 0.6)))
    return QColor.fromHsl(hue, 255, light).name()


# ── 브랜드 마크(SVG) + 그라디언트 빌더 ──
_SPECTRA_MARK_SVG = (
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 110 60">'
    b'<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="0">'
    b'<stop offset="0" stop-color="#1FA2FF"/><stop offset="0.28" stop-color="#4E7DF0"/>'
    b'<stop offset="0.52" stop-color="#9B5DE5"/><stop offset="0.72" stop-color="#F15BB5"/>'
    b'<stop offset="0.86" stop-color="#FF9F0A"/><stop offset="1" stop-color="#FF453A"/>'
    b'</linearGradient></defs>'
    b'<path d="M2,42 C12,42 14,30 20,30 S26,46 31,40 S37,8 44,18 S50,52 56,34 '
    b'S62,4 70,26 S76,50 83,38 S90,22 96,30 S104,40 108,38" fill="none" '
    b'stroke="url(#g)" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/></svg>'
)
# 시그니처 그라디언트 — Qt 스타일시트용 (헤더 언더라인 등)
_SPECTRA_GRAD_QSS = ('qlineargradient(x1:0,y1:0,x2:1,y2:0,'
                     'stop:0 #1FA2FF, stop:0.28 #4E7DF0, stop:0.52 #9B5DE5,'
                     'stop:0.72 #F15BB5, stop:0.86 #FF9F0A, stop:1 #FF453A)')
# 시그니처 그라디언트 — SVG <defs>용 (아이콘 stroke="url(#g)")
_SPECTRA_GRAD_DEFS = (
    '<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="0">'
    '<stop offset="0" stop-color="#1FA2FF"/><stop offset="0.28" stop-color="#4E7DF0"/>'
    '<stop offset="0.52" stop-color="#9B5DE5"/><stop offset="0.72" stop-color="#F15BB5"/>'
    '<stop offset="0.86" stop-color="#FF9F0A"/><stop offset="1" stop-color="#FF453A"/>'
    '</linearGradient></defs>')

def _spectra_grad_obj(x0, x1, alpha=255):
    """가로(주파수축) SPECTRA QLinearGradient — 저역(파랑)→고역(빨강)."""
    g = QLinearGradient(float(x0), 0.0, float(x1), 0.0)
    for o, c in _SPECTRA_GRAD_STOPS:
        qc = QColor(c); qc.setAlpha(alpha); g.setColorAt(o, qc)
    return g
def _spectra_grad_pen(x0, x1, width=2.2, alpha=255):
    """가로 SPECTRA 그라디언트 펜 (선)."""
    return QPen(QBrush(_spectra_grad_obj(x0, x1, alpha)), width)
def _spectra_grad_brush(x0, x1, alpha=255):
    """가로 SPECTRA 그라디언트 브러시 (채움)."""
    return QBrush(_spectra_grad_obj(x0, x1, alpha))
_spectra_mark_cache = {}
def _spectra_mark(h=22):
    """그라디언트 웨이브 마크 QPixmap(높이 h px). 한 번만 렌더 후 캐시 (속도 영향 0)."""
    try:
        dpr = QApplication.primaryScreen().devicePixelRatio() if QApplication.instance() else 1.0
    except Exception:
        dpr = 1.0
    w = int(round(h * 110 / 60))
    key = (w, h, round(dpr, 2))
    pm = _spectra_mark_cache.get(key)
    if pm is not None:
        return pm
    try:
        from PyQt5.QtCore import QByteArray
        from PyQt5.QtSvg import QSvgRenderer
        r = QSvgRenderer(QByteArray(_SPECTRA_MARK_SVG))
        pm = QPixmap(max(1, int(w * dpr)), max(1, int(h * dpr))); pm.fill(Qt.transparent)
        p = QPainter(pm); p.setRenderHint(QPainter.Antialiasing); r.render(p); p.end()
        pm.setDevicePixelRatio(dpr)
    except Exception:
        pm = QPixmap(1, 1); pm.fill(Qt.transparent)   # QtSvg 없으면 빈 마크(워드마크만 표시)
    _spectra_mark_cache[key] = pm
    return pm

_TF_SEL_GRAD_STOPS = ('#1FA2FF', '#4E7DF0', '#9B5DE5', '#F15BB5', '#FF9F0A', '#FF453A')  # SPECTRA 시그니처

# TF 카드 색 팔레트(라이브 멀티카드)
_MC_COLORS = ['#00D4FF','#FF8C00','#44FF88','#FF4488','#FFDD00','#AA66FF','#FF6644','#00FFCC']

# 스펙트럼 바 색 프리셋
BAR_PRESETS = [
    ("Default",  (0,229,255,200), (0,100,200,20)),
    ("Warm",     (255,140,0,220), (255,60,0,20)),
    ("Green",    (57,255,20,220), (20,180,0,20)),
    ("Purple",   (200,80,255,220),(100,0,200,20)),
    ("Sunset",   (255,220,0,220), (255,30,80,30)),
    ("Mono",     (220,230,240,220),(100,120,140,20)),
]


# ── 막대 색 상태 (color picker가 뮤테이트 — 단일 경유점 set/get) ──
_bar_preset_idx = 0   # 0 = Default (follows theme)
_custom_color = None  # (R,G,B) — macOS color picker로 선택한 색상

def bar_custom_color():
    return _custom_color

def set_bar_custom_color(rgb):
    """color picker 전용: 커스텀 막대색 지정(preset=Default 리셋). 가변 전역 뮤테이션 단일 경유점."""
    global _custom_color, _bar_preset_idx
    _custom_color = rgb
    _bar_preset_idx = 0

def bar_top():
    if _custom_color is not None:
        return (*_custom_color, 200)
    if _bar_preset_idx == 0:
        return T('spec_fill_top')
    return BAR_PRESETS[_bar_preset_idx][1]

def bar_bot():
    if _custom_color is not None:
        return (*_custom_color, 40)
    if _bar_preset_idx == 0:
        return T('spec_fill_bot')
    return BAR_PRESETS[_bar_preset_idx][2]

def _vbar_gradient(col):
    """막대 세로 그라디언트 — 위=col 밝게, 아래 어둡게(입체) + 상단 sheen 색.
    ObjectBoundingMode라 브러시 1개를 높이 다른 모든 막대에 재사용(라이브 그라디언트 perf 규칙 준수)."""
    a = col.alpha()
    col_bot = QColor(int(col.red()*0.40), int(col.green()*0.40), int(col.blue()*0.40), a)
    g = QLinearGradient(0, 0, 0, 1); g.setCoordinateMode(g.ObjectBoundingMode)
    g.setColorAt(0.0, col); g.setColorAt(1.0, col_bot)
    cap = QColor(min(255, int(col.red()*1.10)+28), min(255, int(col.green()*1.10)+28),
                 min(255, int(col.blue()*1.10)+28), a)
    return QBrush(g), cap
