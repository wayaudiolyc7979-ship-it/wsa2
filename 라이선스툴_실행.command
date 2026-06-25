#!/bin/bash
# WSA2 라이선스 키 생성기 — 더블클릭 실행 런처
# 이 파일이 있는 폴더(개인키 license_ed25519_private.key 와 같은 위치)에서
# GUI 라이선스 툴을 실행한다. 빌드·서명 불필요 = Gatekeeper 차단 없음.
cd "$(dirname "$0")" || { echo "폴더 이동 실패"; read -r; exit 1; }

if [ ! -f license_ed25519_private.key ]; then
  echo "⚠️  개인키(license_ed25519_private.key)가 이 폴더에 없습니다."
  echo "    마스터 개인키 파일을 이 폴더에 두고 다시 실행하세요."
  read -r -p "엔터를 누르면 닫힙니다..."
  exit 1
fi

echo "WSA2 라이선스 툴 실행 중…"
python3 wsa2_license_tool.py
ec=$?
[ $ec -ne 0 ] && { echo "종료 코드 $ec"; read -r -p "엔터를 누르면 닫힙니다..."; }
