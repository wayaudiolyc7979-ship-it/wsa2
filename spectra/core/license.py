"""라이선스 검증 (Ed25519 + 레거시 HMAC) + 머신ID — v2.0 분해(동작 0 변경).

Ed25519 공개키만 내장(개인키 부재→위조 불가). 서명 상세는 LICENSING.md.
"""
import os
import base64 as _b64
import hashlib as _hs
import hmac as _hmac
import datetime as _dt
import time as _time
import platform as _pl
import subprocess as _sp
from spectra.core.i18n import _tx
from spectra.core.logging_diag import _diag

# ═══════════════════════════════════════════════════════════════════
#  라이선스 관리
# ═══════════════════════════════════════════════════════════════════
# 레거시 HMAC 비밀(v1.0 발급 키 3명 호환용 — 신규는 Ed25519). 추출돼도 신규 위조엔 무력.
_LIC_SECRET = b'W4y4ud10_WSA2_Lic_\xde\xad\xbe\xef\x01\x23\x45\x67'
# Ed25519 공개키 — 검증 전용. 서명용 개인키(seed)는 앱에 없음 → 추출돼도 키 위조 불가.
_LIC_PUBKEY = bytes.fromhex('f3273121a956dc22ee35e34e362203646c2f07b9607fe9b86cf650e6983a942a')
try:
    import ed25519_min as _ed25519
except Exception:
    _ed25519 = None   # 모듈 없으면 레거시 HMAC만 (안전 폴백)

if _pl.system() == 'Windows':
    _LIC_DIR = os.path.join(os.environ.get('APPDATA', os.path.expanduser('~')), 'WAYAUDIO')
else:
    _LIC_DIR = os.path.expanduser('~/Library/Application Support/WAYAUDIO')
_LIC_PATH = os.path.join(_LIC_DIR, 'wsa2.lic')

# Windows: subprocess가 콘솔 창을 깜빡이며 띄우는 것 방지(시작 시 wmic/PowerShell 등).
#   CREATE_NO_WINDOW 는 Windows 전용 → 그 외엔 0(영향 없음).
_SP_NO_WINDOW = getattr(_sp, 'CREATE_NO_WINDOW', 0) if _pl.system() == 'Windows' else 0
_MACHINE_ID_CACHE = None
# 하드웨어에서 실제로 읽어낸 머신ID를 디스크에 남겨두는 곳(_LIC_DIR 안).
_MID_CACHE_PATH = os.path.join(_LIC_DIR, 'machine_id')


def _hw_serial_sources():
    """플랫폼별 (설명, argv) 후보 목록 — 앞에서부터 시도한다.

    ⚠️ **반드시 절대경로**로 부른다. 이름으로만 부르면 PATH 앞에 동명의 가짜 실행파일을
    두는 것만으로 조회를 실패시킬 수 있고, 그러면 아래 캐시 폴백이 발동해 라이선스
    검사를 우회할 수 있다(리뷰에서 실제로 재현됨)."""
    if _pl.system() == 'Windows':
        root = os.environ.get('SystemRoot', r'C:\Windows')
        return [
            ('wmic', [os.path.join(root, 'System32', 'wbem', 'WMIC.exe'),
                      'bios', 'get', 'SerialNumber', '/value']),
            # Win11 24H2는 wmic이 기본 제거됨 → PowerShell 경로가 실질 기본이다.
            ('powershell', [os.path.join(root, 'System32', 'WindowsPowerShell', 'v1.0',
                                         'powershell.exe'),
                            '-NoProfile', '-Command',
                            '(Get-CimInstance Win32_BIOS).SerialNumber']),
        ]
    return [('system_profiler', ['/usr/sbin/system_profiler', 'SPHardwareDataType'])]


def _parse_hw_serial(kind: str, out: str) -> str:
    if kind == 'wmic':
        for ln in out.splitlines():
            if ln.upper().startswith('SERIALNUMBER='):
                return ln.split('=', 1)[-1].strip()
        return ''
    if kind == 'powershell':
        return out.strip()
    for ln in out.splitlines():            # system_profiler
        if 'Serial Number' in ln:
            return ln.split(':')[-1].strip()
    return ''


def _read_hw_serial() -> str:
    """플랫폼 하드웨어 시리얼. 못 읽으면 빈 문자열(예외 안 던짐).

    각 후보를 **독립된 try**로 감싼다 — 예전엔 wmic과 PowerShell이 한 try 안에 있어
    ①wmic이 없으면(Win11 24H2) 예외가 나서 PowerShell에 **도달조차 못 했고**
    ②wmic이 빈 SerialNumber를 주면 그대로 ''를 반환해 폴백이 죽어 있었다.
    둘 다 '시리얼을 영영 못 읽음 → 머신ID가 hostname에 묶임'으로 이어진다."""
    for kind, argv in _hw_serial_sources():
        try:
            out = _sp.check_output(argv, timeout=5, text=True, stderr=_sp.DEVNULL,
                                   creationflags=_SP_NO_WINDOW)
        except Exception:
            continue
        serial = _parse_hw_serial(kind, out)
        if serial:
            return serial
    return ''


def _mid_from_serial(serial: str) -> str:
    raw = f'WSA2:{serial}:{_pl.machine()}'.encode()
    return _hs.sha256(raw).hexdigest()[:12].upper()


# 캐시 폴백을 인정하는 기간(일). 목적은 "일시적 조회 실패로 정품이 막히는 사고" 방지이지,
# 하드웨어가 영원히 안 읽히는 기기를 무기한 통과시키는 게 아니다.
_MID_CACHE_MAX_AGE = 30 * 86400


def _mid_cache_tag(arch: str, mid: str, ts: str) -> str:
    """캐시 파일 무결성 태그. 코드 추출엔 무력하지만, '파일을 열어 원하는 ID를 적어 넣는'
    가장 쉬운 우회를 막는다(리뷰에서 이 방식으로 라이선스 복사가 통과함이 재현됐다)."""
    return _hmac.new(_LIC_SECRET, f'{arch}:{mid}:{ts}'.encode(), _hs.sha256).hexdigest()[:16]


def _load_cached_mid() -> str:
    """디스크에 남긴 '하드웨어에서 읽은' 머신ID.
    아키텍처 불일치 · 태그 불일치 · 기간 만료면 무시한다."""
    try:
        with open(_MID_CACHE_PATH, 'r') as f:
            arch, mid, ts, tag = f.read().strip().split(':', 3)
        if arch != _pl.machine() or len(mid) != 12 or not mid.isalnum():
            return ''
        if not _hmac.compare_digest(tag, _mid_cache_tag(arch, mid, ts)):
            _diag('machine_id_cache_bad_tag')
            return ''
        if _time.time() - float(ts) > _MID_CACHE_MAX_AGE:
            _diag('machine_id_cache_expired', age_days=int((_time.time() - float(ts)) / 86400))
            return ''
        return mid.upper()
    except Exception:
        return ''


def _store_cached_mid(mid: str):
    try:
        os.makedirs(_LIC_DIR, exist_ok=True)
        arch = _pl.machine(); ts = '%d' % _time.time()
        # tmp 이름에 pid — 두 인스턴스가 동시에 기동해도 서로의 임시파일을 자르지 않게.
        tmp = f'{_MID_CACHE_PATH}.{os.getpid()}.tmp'
        with open(tmp, 'w') as f:
            f.write(f'{arch}:{mid}:{ts}:{_mid_cache_tag(arch, mid, ts)}')
        os.replace(tmp, _MID_CACHE_PATH)
    except Exception as e:
        _diag('machine_id_cache_store_fail', err=type(e).__name__)   # 무음 실패 방지


def _get_machine_id() -> str:
    """하드웨어 시리얼 번호 기반 12자리 머신 ID. 포맷 후에도 동일하게 유지됨.
    1회 계산 후 캐시 — 시작 시 여러 번 호출돼도 wmic/PowerShell 재실행(콘솔 깜빡임·지연) 방지.

    ⚠️ 예전엔 시리얼을 못 읽으면 곧장 hostname으로 폴백했다. 그런데 hostname은
    사용자가 바꿀 수 있고 `system_profiler`/`wmic`은 부하가 걸리면 타임아웃할 수 있다
    → **정상 라이선스가 갑자기 "이 컴퓨터용이 아닙니다"로 막히는** 사고가 난다.
    그래서 하드웨어에서 한 번이라도 성공적으로 읽어낸 ID를 디스크에 남겨두고,
    **하드웨어 조회가 실패했을 때만** 그 값을 쓴다.

    보안 메모: 조회가 성공하면 캐시는 절대 쓰지 않는다. 따라서 다른 정상 기기로
    라이선스+캐시 파일을 복사해도 그 기기의 진짜 시리얼이 읽혀 검증에 실패한다
    (캐시가 쓰이는 건 하드웨어 조회 자체가 망가진 기기뿐)."""
    global _MACHINE_ID_CACHE
    if _MACHINE_ID_CACHE is not None:
        return _MACHINE_ID_CACHE
    serial = _read_hw_serial()
    _cached = '' if serial else _load_cached_mid()
    if not serial and not _cached:
        # 재시도는 **캐시가 없을 때만** — 캐시가 있으면 일시적 타임아웃은 이미 커버된다.
        # 무조건 재시도하면 최악 지연이 2배가 되는데, 이 호출은 스플래시보다 앞이라
        # 그만큼 창이 안 뜬 채로 멈춘다(기동 4.4→1.1초 최적화와 정면 충돌).
        serial = _read_hw_serial()
    if serial:
        _MACHINE_ID_CACHE = _mid_from_serial(serial)
        if _load_cached_mid() != _MACHINE_ID_CACHE:
            _store_cached_mid(_MACHINE_ID_CACHE)
        return _MACHINE_ID_CACHE
    cached = _cached or _load_cached_mid()
    if cached:
        # 하드웨어 조회 실패 — 예전에 성공했던 ID로 라이선스를 지켜준다.
        _diag('machine_id_cached_fallback', mid=cached)
        _MACHINE_ID_CACHE = cached
        return _MACHINE_ID_CACHE
    # 최후 폴백: hostname (캐시도 없는 첫 실행에서 하드웨어 조회가 실패한 경우)
    _diag('machine_id_hostname_fallback')
    _MACHINE_ID_CACHE = _mid_from_serial(_pl.node())
    return _MACHINE_ID_CACHE


def _lic_b32decode(key: str) -> bytes:
    clean = key.upper().replace('-', '').replace(' ', '')
    return _b64.b32decode(clean + '=' * ((8 - len(clean) % 8) % 8))

def _lic_check_payload(payload: bytes, machine_id: str) -> tuple:
    """payload(b'머신ID:만료년') 공통 검증 — 서명은 이미 통과한 뒤."""
    key_mid, expiry_str = payload.decode().split(':')[:2]
    if key_mid != machine_id[:12]:
        return False, _tx('This key was not issued for this computer.')
    expiry = int(expiry_str)
    if expiry > 0 and _dt.date.today().year > expiry:
        return False, _tx('License expired in {expiry}.').format(expiry=expiry)
    return True, 'OK'

def verify_license(key: str, machine_id: str = None) -> tuple:
    """(valid, reason). 신규 Ed25519(비대칭) 우선 → 레거시 HMAC 폴백(v1.0 발급 키 호환)."""
    if machine_id is None:
        machine_id = _get_machine_id()
    # 1) 신규 Ed25519 키: base32( 0x01 + payload + 서명64 )
    if _ed25519 is not None:
        try:
            data = _lic_b32decode(key)
            if len(data) >= 65 and data[0] == 1:
                payload, sig = data[1:-64], data[-64:]
                if _ed25519.verify(sig, payload, _LIC_PUBKEY):
                    return _lic_check_payload(payload, machine_id)  # 서명OK → 머신/만료 판정
        except Exception:
            pass
    # 2) 레거시 HMAC 키: base32( HMAC서명10 + payload )
    try:
        data = _lic_b32decode(key)
        sig, payload = data[:10], data[10:]
        expected = _hmac.new(_LIC_SECRET, payload, _hs.sha256).digest()[:10]
        if not _hmac.compare_digest(sig, expected):
            return False, _tx('Invalid serial key.')
        return _lic_check_payload(payload, machine_id)
    except Exception:
        return False, _tx('Key format is incorrect.')

def load_license():
    try:
        with open(_LIC_PATH, 'r') as f: return f.read().strip()
    except Exception: return None

def save_license(key: str):
    global _STARTUP_LICENSE_OK
    os.makedirs(_LIC_DIR, exist_ok=True)
    with open(_LIC_PATH, 'w') as f: f.write(key.strip())
    _STARTUP_LICENSE_OK = None   # 메모이즈 무효화 — 이후 재검증이 stale False를 받지 않게

_STARTUP_LICENSE_OK = None   # 검증 결과 캐시(Ed25519 순수파이썬 verify가 285ms — 2회 호출 방지)


def check_license_at_startup(force: bool = False) -> bool:
    """저장된 키 검증. True=통과, False=라이선스 없음/무효.

    [기동시간] 결과를 캐시한다. Ed25519 verify가 순수 파이썬이라 1회 285ms인데,
    기동 경로에서 두 번(진단 로그 한 줄 + 실제 게이트) 불려 570ms를 그냥 태웠다.
    활성화 직후처럼 다시 확인해야 하면 force=True."""
    global _STARTUP_LICENSE_OK
    if _STARTUP_LICENSE_OK is not None and not force:
        return _STARTUP_LICENSE_OK
    key = load_license()
    if not key:
        _STARTUP_LICENSE_OK = False
        return False
    valid, _ = verify_license(key)
    _STARTUP_LICENSE_OK = bool(valid)
    return _STARTUP_LICENSE_OK
