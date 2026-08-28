"""드로잉/지오메트리 — 주파수축 변환·눈금·커서 리드아웃(draw_info_box)·도미넌트 배지.

v2.0 분해: wayaudo2.py에서 이동(동작 0 변경). QPainter p를 받아 그림.
"""
import math
from PyQt5.QtGui import QColor, QPen, QBrush, QPainterPath, QPolygonF, QPainter, QFont
from PyQt5.QtCore import Qt, QPointF, QRectF
from spectra.core.config import T, is_dark
from spectra.ui.tokens import _qfont, _n2_val_font, CF_BADGE

def freq_to_x(f, pad_l, usable, ny=24000, f_lo=20):
    if f <= 0: return pad_l
    return pad_l + (math.log10(max(f,1e-9)/f_lo) / math.log10(ny/f_lo)) * usable

def _fmt_freq_tick(f):
    """주파수 눈금 라벨 — 줌 시 비정수 눈금도 정확히(1250→'1.25k', 3150→'3.15k', 100→'100')."""
    if f >= 1000:
        v = f / 1000.0
        return f'{int(round(v))}k' if abs(v - round(v)) < 1e-6 else f'{v:g}k'
    return f'{int(round(f))}' if abs(f - round(f)) < 1e-6 else f'{f:g}'

# 1/3옥타브 보조 그리드 (옥타브선 사이) — Smaart 스타일 촘촘한 로그 그리드용
FREQ_MARKS_MINOR = [20,25,40,50,80,100,160,200,315,400,630,800,
                    1250,1600,2500,3150,5000,6300,10000,12500,20000]

def draw_freq_minor_grid(p, pl, pr, uw, pt, pb, W, H, ny, f_lo=20):
    """1/3옥타브 보조 세로 그리드선 — 옥타브선보다 '흐리게'(behind). FREQ_MARKS 주선 직전 호출.
    '흐리게'의 방향은 배경에 따라 반대: 다크=어둡게(검정쪽), 라이트=밝게(흰쪽). 안 그러면 라이트에서
    보조선이 옥타브선보다 진해져 위계가 뒤집힘. f_lo=줌 좌하한(주파수축 확대 반영)."""
    minor = QColor(T('grid')).lighter(116) if (not is_dark()) else QColor(T('grid')).darker(150)
    p.setPen(QPen(minor, 1, Qt.SolidLine))
    for f in FREQ_MARKS_MINOR:
        if f < f_lo or f > ny: continue
        fx = freq_to_x(f, pl, uw, ny, f_lo)
        if not pl <= fx <= W - pr: continue
        p.drawLine(int(fx), pt, int(fx), H - pb)

def db_to_y(db, draw_h, db_min, db_max):
    db = max(db_min, min(db_max, db))
    rng = db_max - db_min
    return int((db_max - db) / rng * draw_h) if rng > 0 else 0

def x_to_freq(x, pad_l, usable, ny=24000, f_lo=20):
    r = max(0.0, min(1.0, (x-pad_l)/usable))
    return f_lo*(ny/f_lo)**r

def y_to_db(y, draw_h, db_min, db_max):
    return db_max - (y/max(draw_h,1))*(db_max-db_min)

# ───────────────────────────────────────────
#  커서 정보창
# ───────────────────────────────────────────
def draw_info_box(p, W, title_str, val_str, pk_str=None, cx=None, x_lo=0, x_hi=None,
                  top=6, val_color=None):
    # 커서 리드아웃 = 커서에 붙는 태그(H2). 위치(제목)는 흐리게 위, 값은 곡선색으로 아래.
    # cx 지정 시 커서 x 에 태그를 물리고 아래 노치(▽)로 그 지점을 가리킴(플롯 안으로 클램프);
    # cx=None 이면 상단 중앙 폴백. 글로우/굵은 테두리/주황값(구식) 폐지 → 브랜드 폰트(축 라벨과 동일)+하어라인.
    if x_hi is None: x_hi = W
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setFont(_n2_val_font(13, QFont.DemiBold));tw = p.fontMetrics().horizontalAdvance(title_str)
    p.setFont(_n2_val_font(16, QFont.Bold));     vw = p.fontMetrics().horizontalAdvance(val_str)
    pw = p.fontMetrics().horizontalAdvance(pk_str) if pk_str else 0
    bw = max(tw, vw, pw) + 22
    bh = 66 if pk_str else 44
    by = top + 6
    if cx is None:
        bx = W // 2 - bw // 2
    else:
        bx = int(min(max(cx - bw / 2, x_lo + 3), x_hi - bw - 3))
    fill = QColor(T('panel')) if (not is_dark()) else QColor(16, 16, 18, 240)
    path = QPainterPath(); path.addRoundedRect(bx, by, bw, bh, 7, 7)
    p.setPen(Qt.NoPen); p.setBrush(QBrush(fill)); p.drawPath(path)
    if cx is not None:   # 노치 — 커서 지점을 가리킴(태그 밑변 안으로 클램프)
        nx = int(min(max(cx, bx + 11), bx + bw - 11))
        p.drawPolygon(QPolygonF([QPointF(nx - 6, by + bh - 0.5),
                                 QPointF(nx + 6, by + bh - 0.5), QPointF(nx, by + bh + 8)]))
    p.setPen(QPen(QColor(T('border')), 1)); p.setBrush(Qt.NoBrush); p.drawPath(path)
    p.setFont(_n2_val_font(13, QFont.DemiBold));p.setPen(QColor(T('text_dim')))
    p.drawText(bx, by + 4, bw, 18, Qt.AlignHCenter | Qt.AlignVCenter, title_str)
    p.setFont(_n2_val_font(16, QFont.Bold)); p.setPen(QColor(val_color or T('text')))
    p.drawText(bx, by + 21, bw, 20, Qt.AlignHCenter | Qt.AlignVCenter, val_str)
    if pk_str:
        p.setPen(QColor('#FFB300'))
        p.drawText(bx, by + 42, bw, 20, Qt.AlignHCenter | Qt.AlignVCenter, pk_str)

def draw_dom_badge(p, plot_right, plot_top, dom_fs, dom_db, unit='dB'):
    """우상단 고정 배지: 가장 큰 레벨의 주파수 + dB/dBSPL."""
    txt = f'▲  {dom_fs}   {dom_db:.1f} {unit}'
    p.setFont(_qfont(CF_BADGE, True))
    tw = p.fontMetrics().horizontalAdvance(txt)
    bw = tw + 24; bh = 36
    bx = plot_right - bw - 6; by = plot_top + 5
    if (not is_dark()):
        # 라이트: 흰 카드 + 은은한 보더 (검정 박스 대신)
        p.setPen(QPen(QColor(T('border')), 1)); p.setBrush(QBrush(QColor(T('panel'))))
    else:
        p.setPen(Qt.NoPen); p.setBrush(QBrush(QColor(0, 0, 0, 220)))
    p.drawRoundedRect(bx, by, bw, bh, 4, 4)
    p.setPen(QColor(T('accent')))
    p.drawText(bx, by, bw, bh, Qt.AlignHCenter | Qt.AlignVCenter, txt)


# ── TF 카드 페인팅 ──
def _tf_card_palette():
    """(gutter, card_bg, border) QColors — 테마 적응. 거터=스플리터 handle 색과 통일.
    다크: 카드=순수 블랙(SPECTRA 정체성 유지) + 거터만 살짝 밝게 → '검은 카드가 옅은 틀에 박힘'."""
    if (not is_dark()):
        return QColor('#dcdde1'), QColor('#ffffff'), QColor(0, 0, 0, 30)
    return QColor(T('bg2')), QColor('#000000'), QColor(255, 255, 255, 30)   # 거터=우측 패널 회색(#1C1C1E)과 통일

def _tf_gutter():
    return _tf_card_palette()[0]

def _paint_tf_card(p, W, H, m=6, r=11):
    """둥근 카드 본체(살짝 밝은 bg + 하어라인 테두리). 거터는 px.fill(_tf_gutter())로 이미 채워짐.
    그리드/곡선은 PAD_*(>m)로 인셋돼 카드 안에 그려짐."""
    _g, card, border = _tf_card_palette()
    p.save(); p.setRenderHint(QPainter.Antialiasing, True)
    p.setPen(QPen(border, 1)); p.setBrush(card)
    p.drawRoundedRect(QRectF(m + 0.5, m + 0.5, W - 2*m - 1, H - 2*m - 1), r, r)
    p.restore()


# ───────────────────────────────────────────
#  레벨미터 구간(zone) — green/yellow/red 위치 기반 (M4/Smaart 하드웨어 미터식)
#  여기 두 숫자만 바꾸면 모든 레벨미터(TF R/M, Spectrum 카드, 메인 SPL)에 반영  [찾기: METER_ZONES]
#    값↑ = 그 색 구간이 더 위(0dBFS) 쪽으로 좁아짐
# ───────────────────────────────────────────
METER_DB_MIN    = -60.0   # 모든 레벨미터 바닥(dBFS) — 통일(카드/메인/TF가 같은 양으로 채워짐)
METER_YELLOW_DB = -18.0   # 이 위로 노랑 구간 시작
METER_RED_DB    = -6.0    # 이 위로 빨강 구간 시작(클립 근접)
# 레벨미터 반응 속도 — 스펙트럼 Speed와 무관(독립). 미터=항상 실시간, 그래프=Speed 따로.
METER_ATTACK    = 0.7     # (스펙트럼 메인/카드) 올라올 때 계수·즉각  — ~60fps 고정 프로듀서용
METER_RELEASE   = 0.30    # (스펙트럼 메인/카드) 내려갈 때 계수·실시간 ~150ms. 값↑=더 빨리
# TF 바(_HorizBarVU)는 업데이트율이 가변(M바 빠름/R바 10Hz)이라 시간기반 탄도(초 단위 시정수)로
# 통일 — 업데이트율과 무관하게 일정한 실시간 반응.  값↑=더 천천히
METER_TAU_ATTACK  = 0.015  # 올라올 때 시정수(초)·거의 즉각
METER_TAU_RELEASE = 0.05   # 내려갈 때 시정수(초)·실시간(~0.15s 정착)
METER_PEAK_DECAY  = 30.0   # peak tick 감쇠(dB/초) — 채움에 붙어 매끄럽게 따라내림(스펙트럼 카드 느낌)

def _draw_zone_meter_h(p, W, H, db, db_min, db_max=0.0):
    """수평 레벨바를 채움 폭 안에서 위치별 green/yellow/red 구간으로 칠한다(M4/Smaart 사다리).
    채움 폭만큼 둥근 사각형으로 clip → 구간별 단색 사각형을 그 위에 그림(라이브 그라디언트 아님)."""
    rng = db_max - db_min
    if rng <= 0: return
    def _x(v): return W * max(0.0, min(1.0, (v - db_min) / rng))
    bar_w = _x(db)
    if bar_w <= 1.5: return
    rr = H / 2.0
    p.save()
    clip = QPainterPath(); clip.addRoundedRect(QRectF(0, 0, bar_w, H), rr, rr)
    p.setClipPath(clip); p.setPen(Qt.NoPen)
    gx = min(bar_w, _x(METER_YELLOW_DB))
    yx = min(bar_w, _x(METER_RED_DB))
    p.setBrush(QColor(T('green'))); p.drawRect(QRectF(0, 0, gx, H))
    if bar_w > gx: p.setBrush(QColor(T('yellow'))); p.drawRect(QRectF(gx, 0, yx - gx, H))
    if bar_w > yx: p.setBrush(QColor(T('red')));    p.drawRect(QRectF(yx, 0, bar_w - yx, H))
    p.restore()
