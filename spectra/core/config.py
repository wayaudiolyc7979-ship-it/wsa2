"""앱 설정/상태 단일 소스 — 테마(THEMES·_theme) + 접근자 T()/theme()/is_dark().

v2.0 분해: wayaudo2.py에서 이동(동작 0 변경). ⭐_theme은 여기 단독 소유 —
다른 모듈은 절대 직접 참조 말고 T()/theme()/is_dark()/set_theme()/toggle_theme()로만
(직접 import는 값 복사라 토글이 안 퍼짐. 2.0_MODULE_PLAN §결합지점1). 설정 load/save는 추후 이관.
"""

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
