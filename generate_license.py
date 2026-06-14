#!/usr/bin/env python3
"""
SPECTRA 라이선스 키 생성 도구 (개발자 전용)
사용법:  python3 generate_license.py

신규 키는 Ed25519 비대칭 서명 방식입니다.
  · 서명용 개인키 = license_ed25519_private.key  (이 파일 = 라이선스 마스터 키!)
  · 앱에는 공개키만 들어있어, 소스가 털려도 키 위조 불가.
  ⚠️ license_ed25519_private.key 를 안전하게 백업하고, 절대 공유·커밋하지 마세요.
     (잃어버리면 신규 키 발급 불가, 유출되면 위조 가능)
"""
import base64, datetime, os, sys
import ed25519_min as _ed

_PRIV = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'license_ed25519_private.key')

def _load_seed() -> bytes:
    if not os.path.exists(_PRIV):
        print(f'❌ 개인키 파일이 없습니다: {_PRIV}')
        print('   (마스터 키 파일. 백업본이 있으면 이 경로에 복원하세요.)')
        sys.exit(1)
    return bytes.fromhex(open(_PRIV).read().strip())

def generate_key(machine_id: str, expiry_year: int = 0) -> str:
    """machine_id: 앱에서 복사한 12자리 머신 ID · expiry_year: 만료 연도(0=영구)"""
    mid = machine_id.upper().strip()[:12].ljust(12, '0')
    payload = f'{mid}:{expiry_year:04d}'.encode()
    seed = _load_seed()
    sig = _ed.sign(payload, seed, _ed.public_key(seed))
    data = b'\x01' + payload + sig            # 0x01 = Ed25519 버전 마커
    b32 = base64.b32encode(data).decode().rstrip('=')
    return '-'.join(b32[i:i+5] for i in range(0, len(b32), 5))

def _fmt_expiry(year: int) -> str:
    return '영구' if year == 0 else f'{year}년 12월 31일까지'

if __name__ == '__main__':
    print('=' * 55)
    print('  SPECTRA 라이선스 키 생성기  (개발자 전용 · Ed25519)')
    print('=' * 55)
    print()
    mid = input('사용자 머신 ID (12자리): ').strip()
    if len(mid) < 8:
        print('머신 ID가 너무 짧습니다.'); exit(1)
    print('만료 연도 입력 (0 = 영구, 예: 2027): ', end='')
    try:    expiry = int(input().strip())
    except: expiry = 0

    key = generate_key(mid, expiry)
    print()
    print('─' * 55)
    print(f'  머신 ID   : {mid[:12]}')
    print(f'  만료      : {_fmt_expiry(expiry)}')
    print(f'  발급일    : {datetime.date.today()}')
    print()
    print(f'  시리얼 키 :')
    print(f'  {key}')
    print('─' * 55)
    print()
    print('※ 이 키는 해당 머신 ID의 컴퓨터에서만 작동합니다.')
    print('※ license_ed25519_private.key 를 외부에 공유/커밋하지 마세요.')
