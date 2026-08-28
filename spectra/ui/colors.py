"""브랜드 색상 헬퍼 — HSL 스펙트럼·브랜드 그라디언트 샘플·rgba CSS·메트릭색.

v2.0 분해: wayaudo2.py에서 이동(동작 0 변경). is_dark()로 라이트/다크 대비 조정.
"""
from PyQt5.QtGui import QColor
from spectra.core.config import is_dark

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
