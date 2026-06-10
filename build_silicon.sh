#!/bin/bash
# WSA2 Apple Silicon (arm64) 빌드 스크립트
# Apple Silicon Mac에서 네이티브로 실행: bash build_silicon.sh
# (Intel 빌드는 build_intel.sh 사용 — Rosetta2 경유)

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== WSA2 Apple Silicon (arm64) 빌드 ==="
ARCH=$(uname -m)
echo "현재 아키텍처: $ARCH"
if [ "$ARCH" != "arm64" ]; then
    echo "ERROR: 이 스크립트는 Apple Silicon(arm64)에서 실행해야 합니다."
    echo "       Intel 빌드는 build_intel.sh 를 사용하세요."
    exit 1
fi

# 필요 패키지 설치 (arm64 Python)
echo "패키지 설치 중..."
python3 -m pip install --user PyQt5 numpy scipy sounddevice soundfile pyinstaller --quiet

# PyInstaller 빌드 (WSA2.spec = arm64, 버전 1.0)
echo "PyInstaller 빌드 시작..."
python3 -m PyInstaller WSA2.spec --clean

# DMG 생성
echo "DMG 생성 중..."
DMG_DIR=/tmp/WSA2_silicon_dmg
rm -rf "$DMG_DIR"; mkdir -p "$DMG_DIR"
cp -R dist/WSA2.app "$DMG_DIR"/
ln -sf /Applications "$DMG_DIR"/Applications
hdiutil create -volname "WSA2 Installer (Apple Silicon)" \
    -srcfolder "$DMG_DIR" \
    -ov -format UDZO -fs HFS+ \
    dist/WSA2_AppleSilicon.dmg

echo ""
echo "=== 빌드 완료 ==="
echo "Apple Silicon DMG: dist/WSA2_AppleSilicon.dmg"
echo "앱 크기: $(du -sh dist/WSA2.app | cut -f1)"
