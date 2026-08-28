"""앱 설정/상태 단일 소스 — 테마(THEMES·_theme) + 접근자 T()/theme()/is_dark().

v2.0 분해: wayaudo2.py에서 이동(동작 0 변경). ⭐_theme은 여기 단독 소유 —
다른 모듈은 절대 직접 참조 말고 T()/theme()/is_dark()/set_theme()/toggle_theme()로만
(직접 import는 값 복사라 토글이 안 퍼짐. 2.0_MODULE_PLAN §결합지점1). 설정 load/save는 추후 이관.
"""

import os, json, threading
import platform as _pl
from spectra.core.logging_diag import _alog

THEMES = {
    'dark': {
        'bg':        '#000000',
        'bg2':       '#1C1C1E',
        'bg3':       '#2C2C2E',
        'panel':     '#242426',
        'border':    '#38383A',
        'text':      '#FFFFFF',
        'text_dim':  '#8E8E93',
        'graph_txt': '#C8CCD4',
        'accent':    '#4E7DF0',
        'accent2':   '#FF9F0A',
        'accent3':   '#9B5DE5',
        'green':     '#33FF66',
        'yellow':    '#FFD60A',
        'red':       '#FF453A',
        'grid':      '#282828',
        'grid_ref':  '#404040',
        'spec_fill_top': (51,255,102,230),
        'spec_fill_bot': (51,255,102,180),
        'spec_line':     '#33FF66',
        'peak_line':     '#FF9F0A',
    },
    'light': {   # Crisp White — 라이트그레이 캔버스 위 흰 서피스가 '떠 보이는' 레이어드 룩 (2026-06-14 리파인 pass2)
        'bg':       '#E7EDF6',   # 캔버스: 살짝 깊은 쿨그레이 → 흰 패널/툴바가 elevation으로 떠 보임
        'bg2':      '#FFFFFF',   # 팝업/드롭다운: 깨끗한 흰 카드
        'bg3':      '#DCE4F0',
        'panel':    '#FFFFFF',
        'border':   '#CBD5E4',   # 살짝 더 또렷한 하어라인
        'text':     '#16213A',
        'text_dim': '#5A6B86',
        'graph_txt': '#46566e',
        'accent':   '#2E54C8',
        'accent2':  '#cc4c00',
        'accent3':  '#6a3fb0',
        'green':    '#0e7c30',
        'yellow':   '#8c6600',
        'red':      '#b81818',
        'grid':     '#D7DFEC',
        'grid_ref': '#BECBDD',
        'spec_fill_top': (22,112,204,120),
        'spec_fill_bot': (22,112,204,8),
        'spec_line':     '#1670cc',
        'peak_line':     '#cc4c00',
    }
}
_theme = 'dark'
def T(key): return THEMES[_theme][key]
# 테마 접근자 — 모듈 분해(v2.0) 대비 가변 전역 `_theme`을 직접 참조하지 말고 이 함수로만.
# (직접 `from ... import _theme`는 값을 복사해 토글이 안 퍼짐 → 반드시 함수 경유. 2.0_MODULE_PLAN §결합지점1)
def theme(): return _theme
def is_dark(): return _theme == 'dark'
def set_theme(v):
    global _theme
    _theme = v
def toggle_theme():
    global _theme
    _theme = 'light' if _theme == 'dark' else 'dark'
    return _theme



# ── 설정/캡처 저장 (v2.0 분해: wayaudo2.py에서 이동) ──
if _pl.system() == 'Windows':
    _APP_SUPPORT = os.path.join(os.environ.get('APPDATA', os.path.expanduser('~')), 'WSA2')
else:
    _APP_SUPPORT = os.path.expanduser('~/Library/Application Support/WSA2')
# 테스트/개발 시 실제 사용자 설정 파일 보호 — 환경변수로 경로 오버라이드 가능
_SETTINGS_PATH = os.environ.get('WSA2_SETTINGS_PATH') or os.path.join(_APP_SUPPORT, 'settings.json')
_CAPTURES_PATH = os.environ.get('WSA2_CAPTURES_PATH') or os.path.join(_APP_SUPPORT, 'captures.json')
_CAPTURES_LOCK = threading.Lock()   # captures.json 동시 읽기-수정-쓰기 보호 (백그라운드 저장용)

def _load_settings():
    try:
        with open(_SETTINGS_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}

def _save_settings(data):
    try:
        d = os.path.dirname(_SETTINGS_PATH)
        if d: os.makedirs(d, exist_ok=True)          # bare filename이면 dirname='' → makedirs 스킵
        tmp = _SETTINGS_PATH + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, _SETTINGS_PATH)              # 원자적 교체(중간 실패해도 기존 파일 보존)
    except Exception as e:
        try: _alog.warning(f'settings 저장 실패: {e}')
        except Exception: pass

def _load_captures_file():
    try:
        with open(_CAPTURES_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}

def _save_captures_file(data):
    try:
        os.makedirs(os.path.dirname(_CAPTURES_PATH), exist_ok=True)
        with open(_CAPTURES_PATH, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception as e:
        _alog.warning(f'캡처 저장 실패: {e}')


# ── 딜레이 단위 (ms ↔ 거리 m) — 표시 통합 ──────────────────────────────
# 내부 저장값은 *항상* ms. 딜레이를 화면에 글로 찍는 모든 곳(IR 마커/커서/시간축/
# 파인더/스핀박스 보조라벨)은 fmt_delay() 하나만 거친다. 나중에 토글 UI는
# _DELAY_UNIT 값만 바꾸고 캔버스.update()+스핀박스 새로고침 하면 전체가 일괄 환산됨.
_SOUND_SPEED = 343.0      # m/s (20°C). _DelayAdvancedDialog에서 조정(전역 단일 소스).
_DELAY_UNIT  = 'ms'       # 'ms' | 'm' | 'both'  — 딜레이 표시 단위 (기본=ms, 동작 변화 0)
# 접근자 — 모듈 분해(v2.0) 대비 가변 전역 직접 참조 금지, 이 함수로만.
def sound_speed(): return _SOUND_SPEED
def set_sound_speed(v):
    global _SOUND_SPEED
    _SOUND_SPEED = v
def delay_unit(): return _DELAY_UNIT
def set_delay_unit(v):
    global _DELAY_UNIT
    _DELAY_UNIT = v

def ms_to_m(ms):
    return ms * sound_speed() / 1000.0

def m_to_ms(m):
    return m * 1000.0 / sound_speed()

def fmt_delay(ms, prec=2, unit=None, compact=False, sign=False):
    """딜레이(ms 값) → 현재 표시 단위 문자열.
    unit 지정 시 강제. compact=축 눈금용(공백 없이 단일 단위). sign=델타용 +부호."""
    u = unit or delay_unit()
    s = '+' if sign else ''
    if compact:                                   # 축 눈금: 한 단위만, 공백 없이
        if u == 'm':
            return f'{ms_to_m(ms):{s}.{max(prec,1)}f}m'
        return f'{ms:{s}.{prec}f}ms'
    if u == 'm':
        return f'{ms_to_m(ms):{s}.2f} m'
    if u == 'both':
        return f'{ms:{s}.{prec}f} ms · {ms_to_m(ms):{s}.2f} m'
    return f'{ms:{s}.{prec}f} ms'


# ───────────────────────────────────────────
#  스펙트럼 상수·응답(ballistic) 튜닝  [찾기: SPEC_TUNING]
#  v2.0 분해: wayaudo2.py 상단 상수부에서 이동(동작 0 변경).
# ───────────────────────────────────────────
MAX_DB = 0
CAPTURE_COLORS = ['#69f0ae','#ffff00','#ff80ab','#ea80fc',
                  '#ff6e6e','#80d8ff','#ffd740','#ccff90']
SPEC_ATTACK  = 0.28   # 막대 상승 부드러움(값↑=즉각). 0.28=부드러움 · 0.5=빠름 · 0.7=즉각
SPEC_FALL_MS = {'Slowest': 2500, 'Slow': 1500, 'Normal': 900, 'Fast': 600, 'Fastest': 400}

def _fall_ms_to_s(ms):
    """−12dB 하강시간(ms) → 릴리즈 평활계수 s (30fps 파워도메인). SPEC_FALL_MS에서 자동 계산."""
    return 0.063 ** (33.0 / ms)        # s = 1-r,  r = 1 - 0.063**(33/ms)

# (label, 릴리즈s[자동계산], col2/col3=레거시) — 순서 = 느림→빠름
SPEED_LEVELS = [
    (_n, _fall_ms_to_s(SPEC_FALL_MS[_n]), _c2, _c3)
    for _n, _c2, _c3 in [
        ('Slowest', 0.030, 0.05), ('Slow', 0.060, 0.10), ('Normal', 0.120, 0.20),
        ('Fast', 0.200, 0.35), ('Fastest', 0.300, 0.55),
    ]
]
FREQ_MARKS = [31.5, 63, 125, 250, 500, 1000, 2000, 4000, 8000, 16000]
