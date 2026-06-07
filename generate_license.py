#!/usr/bin/env python3
"""
WSA2 라이선스 키 생성 도구 (개발자 전용)
사용법:  python3 generate_license.py
"""
import hmac, hashlib, base64, datetime

# ─── 반드시 wayaudo2.py 의 _LIC_SECRET 과 동일하게 유지 ───
_SECRET = b'W4y4ud10_WSA2_Lic_\xde\xad\xbe\xef\x01\x23\x45\x67'

def generate_key(machine_id: str, expiry_year: int = 0) -> str:
    """
    machine_id : 사용자가 앱에서 복사한 12자리 머신 ID
    expiry_year: 만료 연도 (0 = 영구)
    """
    machine_id = machine_id.upper().strip()[:12].ljust(12, '0')
    payload    = f'{machine_id}:{expiry_year:04d}'.encode()
    sig        = hmac.new(_SECRET, payload, hashlib.sha256).digest()[:10]
    combined   = sig + payload
    b32        = base64.b32encode(combined).decode().rstrip('=')
    groups     = [b32[i:i+5] for i in range(0, len(b32), 5)]
    return '-'.join(groups)

def _fmt_expiry(year: int) -> str:
    return '영구' if year == 0 else f'{year}년 12월 31일까지'

if __name__ == '__main__':
    print('=' * 55)
    print('  WSA2 라이선스 키 생성기  (개발자 전용)')
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
    print('※ 이 스크립트와 SECRET 값을 외부에 공유하지 마세요.')
