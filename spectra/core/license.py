"""라이선스 검증 (Ed25519 + 레거시 HMAC) + 머신ID — v2.0 분해(동작 0 변경).

Ed25519 공개키만 내장(개인키 부재→위조 불가). 서명 상세는 LICENSING.md.
"""
import os
import base64 as _b64
import hashlib as _hs
import hmac as _hmac
import datetime as _dt
import platform as _pl
import subprocess as _sp
from spectra.core.i18n import _tx

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

def _get_machine_id() -> str:
    """하드웨어 시리얼 번호 기반 12자리 머신 ID. 포맷 후에도 동일하게 유지됨.
    1회 계산 후 캐시 — 시작 시 여러 번 호출돼도 wmic/PowerShell 재실행(콘솔 깜빡임·지연) 방지."""
    global _MACHINE_ID_CACHE
    if _MACHINE_ID_CACHE is not None:
        return _MACHINE_ID_CACHE
    serial = ''
    try:
        if _pl.system() == 'Windows':
            # BIOS 시리얼 번호 (포맷해도 불변). creationflags=CREATE_NO_WINDOW → 콘솔 창 안 뜸.
            out = _sp.check_output(
                ['wmic', 'bios', 'get', 'SerialNumber', '/value'],
                timeout=5, text=True, stderr=_sp.DEVNULL, creationflags=_SP_NO_WINDOW)
            for ln in out.splitlines():
                if ln.upper().startswith('SERIALNUMBER='):
                    serial = ln.split('=', 1)[-1].strip(); break
            # wmic 결과가 비어있으면 PowerShell로 재시도 (Windows 11 대응)
            if not serial:
                out = _sp.check_output(
                    ['powershell', '-NoProfile', '-Command',
                     '(Get-CimInstance Win32_BIOS).SerialNumber'],
                    timeout=5, text=True, stderr=_sp.DEVNULL, creationflags=_SP_NO_WINDOW)
                serial = out.strip()
        else:
            # macOS: system_profiler
            out = _sp.check_output(
                ['system_profiler', 'SPHardwareDataType'],
                timeout=5, text=True, stderr=_sp.DEVNULL)
            for ln in out.splitlines():
                if 'Serial Number' in ln:
                    serial = ln.split(':')[-1].strip(); break
    except Exception:
        pass
    if not serial:
        serial = _pl.node()  # 최후 폴백: hostname
    raw = f'WSA2:{serial}:{_pl.machine()}'.encode()
    _MACHINE_ID_CACHE = _hs.sha256(raw).hexdigest()[:12].upper()
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
    os.makedirs(_LIC_DIR, exist_ok=True)
    with open(_LIC_PATH, 'w') as f: f.write(key.strip())

def check_license_at_startup() -> bool:
    """저장된 키 검증. True=통과, False=라이선스 없음/무효."""
    key = load_license()
    if not key: return False
    valid, _ = verify_license(key)
    return valid
