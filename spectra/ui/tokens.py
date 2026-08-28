"""디자인 토큰 — 폰트크기(FS_*)·캔버스폰트(CF_*)·모서리(RADIUS_*)·글꼴(FONT_*)·_qfont.

v2.0 분해: wayaudo2.py에서 이동(동작 0 변경). UI 통일 단일 소스.
"""
import platform as _pl
from PyQt5.QtGui import QFont, QColor
from spectra.core.config import T

# ── 디자인 토큰 (UI 통일 단일 소스) ──────────────────────
# 위젯 스타일시트용 폰트 크기 (px) — 컴팩트 4단 스케일
FS_XS, FS_SM, FS_BODY, FS_LG = 9, 10, 11, 13
# 큰 수치 표시 (px) — 정보패널/라우드니스 메트릭
FS_VAL, FS_DISP = 14, 18                     # 보조 큰 값(LAeq/LCeq) / 표시 값(dBA·dBC)
FS_METRIC, FS_METRIC_BIG = 20, 27            # 라우드니스 메트릭(M/S/LRA) / 강조(I/TP)
# 캔버스 QPainter 폰트 (pt) 역할별
CF_AXIS, CF_MODE, CF_ANNO = 10, 8, 9       # TF 축 눈금 / 모드 제목 / 주석
CF_TF_TITLE = CF_MODE + 3                   # TF 3패널 좌상단 제목(IR/Phase/Mag) — 모드보다 +3pt
CF_CUR_TITLE, CF_CUR_VAL  = 16, 13          # 커서 정보박스 주파수 / 값
CF_GRID, CF_BADGE, CF_TINY = 12, 20, 7      # Spectrum FFT/Oct 축 / Dominant badge / VU 초소형 타이틀
# 모서리·패딩 (2단계: 툴바 컨트롤 / 카드 내부 소형)
RADIUS_CTRL, RADIUS_SM = 7, 5               # 툴바 콤보(전역 QSS 7)와 맞춤 / 카드·소형
PAD_CTRL, PAD_SM = '2px 8px', '1px 4px'

# 앱 전체 글꼴 — 한 곳에서 교체 (캔버스 텍스트 + 위젯 공통). 후보: 'Avenir Next'(지오메트릭·세련),
# 'Helvetica Neue'(클래식), '.AppleSystemUIFont'(SF Pro 시스템), 'Arial'(구 기본)
# 폰트: 맥 전용 Optima/Helvetica/Helvetica Neue는 Windows에 없어 깨짐(시작화면 포함) → 플랫폼 대응.
# 맥에선 기존 리터럴 그대로라 시각 변화 0, Windows에선 전부 Segoe UI로 통일.
if _pl.system() == 'Windows':
    FONT_FAMILY = 'Candara'    # 브랜드/UI: Optima 근사(윈도우 기본 탑재 휴머니스트, 획 강약 有)
    FONT_NUM    = 'Segoe UI'   # 숫자/값: Helvetica Neue 근사(깔끔한 그로테스크)
    FONT_SANS   = FONT_FAMILY  # 일반 텍스트/라벨도 브랜드 폰트로 통일(숫자만 FONT_NUM)
else:
    FONT_FAMILY = 'Optima'
    FONT_NUM    = 'Helvetica Neue'
    FONT_SANS   = FONT_FAMILY  # 일반 텍스트/라벨도 브랜드 폰트로 통일(숫자만 FONT_NUM)

def _qfont(pt, bold=False):
    f = QFont(FONT_FAMILY, pt); f.setBold(bold); return f


# ── 스타일시트 헬퍼 (T() 테마 인식) ──
def ss_text(size=FS_BODY, color_key='text_dim', bold=False):
    """라벨/텍스트용 스타일시트 문자열. (전역 QWidget 배경 상속 방지 위해 투명 배경 명시)"""
    return f'color:{T(color_key)};background:transparent;font-size:{size}px;' + ('font-weight:bold;' if bold else '')

def ss_pill_btn(color_key='text_dim', size=FS_XS, radius=RADIUS_SM):
    """투명 배경 + 테두리 알약 버튼 스타일 (hover 시 accent)."""
    return (f'QPushButton{{background:transparent;color:{T(color_key)};border:1px solid {T("border")};'
            f'border-radius:{radius}px;font-size:{size}px;padding:{PAD_SM};}}'
            f'QPushButton:hover{{color:{T("accent")};border-color:{T("accent")};}}')

def ss_input(size=FS_SM, radius=RADIUS_SM):
    """스핀박스/입력류 스타일."""
    return (f'background:{T("panel")};color:{T("text")};border:1px solid {T("border")};'
            f'border-radius:{radius}px;padding:{PAD_SM};font-size:{size}px;')

def ss_spin(size=FS_BODY, radius=6, min_w=80):
    """다이얼로그 스핀박스 공통 스타일 — 패널 배경 + up/down 버튼 숨김."""
    return (f'QDoubleSpinBox, QSpinBox {{ background:{T("panel")}; color:{T("text")};'
            f'border:1px solid {T("border")}; padding:3px 8px; border-radius:{radius}px;'
            f'min-width:{min_w}px; font-size:{size}px; }}'
            f'QDoubleSpinBox::up-button, QSpinBox::up-button {{ width:0; border:none; }}'
            f'QDoubleSpinBox::down-button, QSpinBox::down-button {{ width:0; border:none; }}')

def ss_dialog_btns():
    """다이얼로그 OK/Cancel 버튼박스 공통 스타일 — OK(default)=로고블루 주동작, Cancel=중립."""
    a = QColor(T('accent')); ar, ag, ab = a.red(), a.green(), a.blue()
    return (
        f'QPushButton{{background:{T("panel")};color:{T("text")};'
        f'border:1px solid {T("border")};border-radius:6px;padding:5px 18px;font-size:12px;min-width:68px;}}'
        f'QPushButton:hover{{border-color:{T("accent")};}}'
        f'QPushButton:default{{background:{T("accent")};color:#FFFFFF;'
        f'border:1px solid {T("accent")};font-weight:600;}}'
        f'QPushButton:default:hover{{background:rgba({ar},{ag},{ab},210);}}')

def ss_btn_primary(size=12):
    """다이얼로그 주동작 버튼 — 로고블루 채움."""
    a = QColor(T('accent')); ar, ag, ab = a.red(), a.green(), a.blue()
    return (f'QPushButton{{background:{T("accent")};color:#FFFFFF;'
            f'border:1px solid {T("accent")};border-radius:6px;padding:5px 16px;'
            f'font-size:{size}px;font-weight:600;min-width:60px;}}'
            f'QPushButton:hover{{background:rgba({ar},{ag},{ab},210);}}'
            f'QPushButton:disabled{{background:{T("panel")};color:{T("text_dim")};border-color:{T("border")};}}')

def ss_btn_neutral(size=12):
    """다이얼로그 보조/취소 버튼 — 중립."""
    return (f'QPushButton{{background:{T("panel")};color:{T("text")};'
            f'border:1px solid {T("border")};border-radius:6px;padding:5px 16px;'
            f'font-size:{size}px;min-width:60px;}}'
            f'QPushButton:hover{{border-color:{T("accent")};}}'
            f'QPushButton:disabled{{color:{T("text_dim")};}}')

def ss_btn_danger(size=12):
    """다이얼로그 위험(삭제 등) 주동작 버튼 — 빨강 채움."""
    r = QColor(T('red')); rr, rg, rb = r.red(), r.green(), r.blue()
    return (f'QPushButton{{background:{T("red")};color:#FFFFFF;'
            f'border:1px solid {T("red")};border-radius:6px;padding:5px 16px;'
            f'font-size:{size}px;font-weight:600;min-width:60px;}}'
            f'QPushButton:hover{{background:rgba({rr},{rg},{rb},210);}}')


# ── N2 폰트 헬퍼 ──
def _n2_mono_font(size=12, weight=QFont.DemiBold):
    f = QFont(); f.setStyleHint(QFont.Monospace); f.setFamily('Menlo')
    f.setPixelSize(size); f.setWeight(weight); return f

def _n2_caps_font(size=9):
    # 패밀리 명시 필수 — QFont()만으론 setFont 시 앱 폰트(Optima)가 아닌 시스템 기본(SF Pro)으로
    # 떨어져 나머지 UI와 폰트가 어긋남. 앱 브랜드 폰트(FONT_FAMILY)로 통일.
    f = QFont(FONT_FAMILY); f.setPixelSize(size); f.setBold(True)
    f.setLetterSpacing(QFont.AbsoluteSpacing, 0.5); f.setCapitalization(QFont.AllUppercase); return f

def _n2_val_font(size=12, weight=QFont.DemiBold):
    f = QFont(FONT_FAMILY); f.setPixelSize(size); f.setWeight(weight); return f
