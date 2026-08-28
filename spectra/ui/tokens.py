"""디자인 토큰 — 폰트크기(FS_*)·캔버스폰트(CF_*)·모서리(RADIUS_*)·글꼴(FONT_*)·_qfont.

v2.0 분해: wayaudo2.py에서 이동(동작 0 변경). UI 통일 단일 소스.
"""
import platform as _pl
from PyQt5.QtGui import QFont

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
