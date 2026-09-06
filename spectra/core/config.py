"""앱 설정/상태 단일 소스 — 테마(THEMES·_theme) + 접근자 T()/theme()/is_dark().

v2.0 분해: wayaudo2.py에서 이동(동작 0 변경). ⭐_theme은 여기 단독 소유 —
다른 모듈은 절대 직접 참조 말고 T()/theme()/is_dark()/set_theme()/toggle_theme()로만
(직접 import는 값 복사라 토글이 안 퍼짐. 2.0_MODULE_PLAN §결합지점1). 설정 load/save는 추후 이관.
"""

import os, json, threading
import base64 as _b64
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
    # 잘못된 값이 들어오면 T()가 매 페인트마다 KeyError를 낸다(T는 THEMES[_theme][key] 직접 접근)
    # → 알려진 테마만 허용. settings.json이 손상됐거나 손으로 편집된 경우의 안전망.
    global _theme
    _theme = v if v in THEMES else 'dark'
    return _theme
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


def _derive_tf_captures_path(spec_path):
    """TF 캡처 파일 경로 — spec 경로에서 파생(`captures.json` → `captures_tf.json`).
    테스트가 WSA2_CAPTURES_PATH만 바꿔도 TF 파일까지 자동으로 같은 임시 위치로 따라오게 한다."""
    root, ext = os.path.splitext(spec_path)
    return f'{root}_tf{ext or ".json"}'


_CAPTURES_TF_PATH = os.environ.get('WSA2_CAPTURES_TF_PATH') or _derive_tf_captures_path(_CAPTURES_PATH)

# 락을 파일별로 분리한다. 예전엔 spec/TF 캡처가 **한 파일**을 공유해 하나의 락으로 직렬화했는데,
# TF 백그라운드 세이버가 락을 쥔 동안 GUI 스레드(스펙트럼 캡처 저장)가 그대로 멈췄다
# (실측 우선순위 역전 1.44초). 이제 서로 다른 파일이라 경쟁 자체가 없다.
_CAPTURES_LOCK = threading.Lock()      # captures.json (spec: fft/oct)
_CAPTURES_TF_LOCK = threading.Lock()   # captures_tf.json (TF)

_settings_unreadable = False   # 파일은 있는데 읽기/파싱에 실패했다 → 덮어쓰기 전에 원본 보존


def _load_settings():
    """설정 로드. **반드시 dict를 돌려준다** — 예전엔 json.load 결과를 그대로 반환해서
    파일이 `null`이나 리스트로 손상돼 있으면 이후 `.get()`에서 AttributeError가 나
    **앱이 아예 안 뜨는** 상태가 됐다(그 경로는 try로 감싸여 있지도 않았다)."""
    global _settings_unreadable
    _settings_unreadable = False
    if not os.path.exists(_SETTINGS_PATH):
        return {}
    try:
        with open(_SETTINGS_PATH, 'r', encoding='utf-8') as f:
            d = json.load(f)
        if isinstance(d, dict):
            return d
        _alog.warning('settings.json 형식이 dict가 아님 — 빈 설정으로 시작')
    except Exception as e:
        _alog.warning(f'settings.json 읽기 실패: {e}')
    _settings_unreadable = True      # 아래 저장에서 원본을 백업한 뒤 쓰게 한다
    return {}


def _save_settings(data):
    global _settings_unreadable
    try:
        d = os.path.dirname(_SETTINGS_PATH)
        if d: os.makedirs(d, exist_ok=True)          # bare filename이면 dirname='' → makedirs 스킵
        # ⚠️ 읽기에 실패했었다면 그 위에 그냥 덮어쓰면 **캘리브레이션이 영구 소실**된다
        #    (2026-06-18에 실제로 겪은 사고). 일시적 점유·부분 손상일 수 있으므로
        #    원본을 .corrupt-<ts>로 남기고 나서 쓴다. 1회만 수행.
        if _settings_unreadable and os.path.exists(_SETTINGS_PATH):
            try:
                import time as _t
                bak = f'{_SETTINGS_PATH}.corrupt-{int(_t.time())}'
                os.replace(_SETTINGS_PATH, bak)
                _alog.warning(f'읽지 못한 settings.json을 보존: {os.path.basename(bak)}')
            except Exception as e:
                _alog.warning(f'settings 백업 실패(덮어쓰기 중단): {e}')
                return                                # 백업 못 하면 차라리 쓰지 않는다
            finally:
                _settings_unreadable = False
        tmp = f'{_SETTINGS_PATH}.{os.getpid()}.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, _SETTINGS_PATH)              # 원자적 교체(중간 실패해도 기존 파일 보존)
    except Exception as e:
        try: _alog.warning(f'settings 저장 실패: {e}')
        except Exception: pass

def f32_to_b64(arr):
    """float32 배열 → base64 문자열.

    [저장 성능] 곡선을 JSON 숫자 리스트로 담으면 숫자 하나가 글자 ~10칸을 먹어
    TF 캡처 1개가 1MB, 25개면 30MB가 된다. 게다가 json.dumps(숫자→글자 변환)는
    **GIL을 놓지 않아** 백그라운드 스레드로 돌려도 GUI가 통째로 멈춘다
    (실측 187ms 작업 → 다른 스레드 180ms 스톨, 25캡처면 2초마다 1.2초 프리즈).
    raw 바이트로 담으면 숫자당 4바이트(~6배 축소)이고 tobytes/b64encode는 GIL을 놓는다.
    바이트 순서는 '<f4'로 고정 — 다른 기기에서 만든 파일도 그대로 읽힌다."""
    if arr is None:
        return None
    import numpy as _np
    return _b64.b64encode(_np.asarray(arr, dtype='<f4').tobytes()).decode('ascii')


def b64_to_f32(v):
    """base64 문자열(신형식) 또는 숫자 리스트(구형식) → float32 ndarray.

    형식을 타입으로 자동 판별하므로 **예전 캡처 파일이 그대로 읽힌다**(이관 불필요)."""
    if v is None:
        return None
    import numpy as _np
    if isinstance(v, str):
        return _np.frombuffer(_b64.b64decode(v), dtype='<f4').astype(_np.float32)
    return _np.asarray(v, dtype=_np.float32)      # 구형식: JSON 숫자 리스트


def _read_json(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            d = json.load(f)
            return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _write_json_atomic(path, data, what='캡처', durable=False):
    """tmp + os.replace 원자 저장 — dump 도중 크래시/os._exit로 파일이 잘려 전체가 소실되던 것 방지.

    durable=True면 replace 전에 fsync까지 한다. 이관처럼 **'새 파일을 쓴 뒤 옛 파일을
    지우는'** 2단계에서는 fsync가 없으면 파일시스템이 rename 메타데이터만 먼저 반영하고
    데이터 블록을 뒤로 미룰 수 있어, 전원차단 시 '새 파일은 비었는데 옛 파일은 이미
    지워진' 상태가 만들어진다. 평상시 저장은 비용 때문에 기본 False.
    tmp 이름에 pid/tid를 넣어 GUI·백그라운드 세이버가 같은 tmp를 truncate하지 않게 한다."""
    tmp = f'{path}.{os.getpid()}.{threading.get_ident()}.tmp'
    try:
        d = os.path.dirname(path)
        if d: os.makedirs(d, exist_ok=True)          # bare filename이면 dirname='' → makedirs 스킵
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
            if durable:
                f.flush(); os.fsync(f.fileno())
        os.replace(tmp, path)
        return True
    except Exception as e:
        _alog.warning(f'{what} 저장 실패: {e}')
        try: os.unlink(tmp)                          # 실패한 tmp가 앱 폴더에 쌓이지 않게
        except Exception: pass
        return False


_captures_migrated = False   # 프로세스당 1회만 확인하면 되는 이관 여부


def _migrate_captures_split():
    """레거시 통합 captures.json → spec/TF 두 파일로 1회 이관 (멱등).

    v2.0.2 이전엔 fft/oct/tf가 한 파일에 있어, 스펙트럼 캡처 1개를 저장할 때도 TF 캡처
    전부를 다시 직렬화했다(실측 TF 25개=1.37초, 50개=2.72초 GUI 프리즈. 드래그 재정렬은
    드롭마다 발생). 파일을 나눠 서로를 건드리지 않게 한다.

    순서가 안전의 핵심: **TF 파일을 먼저 쓰고**, 성공했을 때만 레거시에서 'tf'를 뺀다.
    중간에 죽어도 최악이 '양쪽에 다 있음'이라 데이터가 사라지지 않는다."""
    global _captures_migrated
    if _captures_migrated:
        return
    try:
        # ⚠️ 존재 여부가 아니라 **내용**으로 판정한다. 예전엔 os.path.exists만 봐서,
        #    TF 파일이 0바이트/손상이면 '이관 완료'로 오판했다 → _save_captures_file의
        #    레거시 'tf' 보존 가드가 무력화되고, 다음 스펙트럼 저장 한 번에
        #    디스크상 마지막 TF 사본이 사라졌다(리뷰에서 재현).
        if 'tf' in _read_json(_CAPTURES_TF_PATH):    # 이미 분리 완료(읽히는 것 확인)
            _captures_migrated = True
            return
        legacy = _read_json(_CAPTURES_PATH)
        if 'tf' not in legacy:                       # 이관할 게 없음(신규 사용자 등)
            _captures_migrated = True
            return
        tf_list = legacy.get('tf') or []
        if not _write_json_atomic(_CAPTURES_TF_PATH, {'tf': tf_list}, 'TF 캡처', durable=True):
            return                                   # 실패 시 레거시 손대지 않음 → 다음 기회에 재시도
        legacy.pop('tf', None)
        _write_json_atomic(_CAPTURES_PATH, legacy, '스펙트럼 캡처', durable=True)
        _captures_migrated = True
        _alog.info(f'캡처 파일 분리 이관 완료 — TF {len(tf_list)}개 → {os.path.basename(_CAPTURES_TF_PATH)}')
    except Exception as e:
        _alog.warning(f'캡처 파일 이관 실패(기존 파일 유지): {e}')


def _load_captures_file():
    """스펙트럼(fft/oct) 캡처 파일. 이관 전 레거시 파일이면 'tf' 키가 남아 있을 수 있다."""
    _migrate_captures_split()
    return _read_json(_CAPTURES_PATH)


def _save_captures_file(data):
    """스펙트럼 캡처 파일 저장 — TF 섹션은 건드리지 않는다(별도 파일).

    ★ 저장 전에 이관을 한 번 보장한다. 이관이 (디스크 가득/권한 등으로) 실패한 상태면
      레거시 파일엔 아직 'tf'가 남아 있는데, 여기서 {'fft','oct'}만 통째로 쓰면 그 TF 캡처가
      영구 소실된다. 이관이 여전히 실패하면 레거시의 'tf'를 보존한 채 쓴다."""
    _migrate_captures_split()
    if not _captures_migrated:
        _legacy_tf = _read_json(_CAPTURES_PATH).get('tf')
        if _legacy_tf is not None and 'tf' not in data:
            data = dict(data); data['tf'] = _legacy_tf   # 이관 전까지는 레거시 TF를 지키며 저장
    _write_json_atomic(_CAPTURES_PATH, data, '스펙트럼 캡처')


def _load_tf_captures_file():
    """TF 캡처 파일. 아직 이관 전이면 레거시 통합 파일에서 승계해 읽는다(데이터 소실 방지)."""
    _migrate_captures_split()
    d = _read_json(_CAPTURES_TF_PATH)
    if 'tf' in d:
        return d
    legacy = _read_json(_CAPTURES_PATH)              # 이관이 실패했던 경우의 안전망
    return {'tf': legacy.get('tf', [])}


def _save_tf_captures_file(data):
    """TF 캡처 파일 저장 — 스펙트럼 섹션은 건드리지 않는다(별도 파일)."""
    _write_json_atomic(_CAPTURES_TF_PATH, data, 'TF 캡처')


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
