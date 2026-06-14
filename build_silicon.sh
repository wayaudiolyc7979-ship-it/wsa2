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

# PyInstaller 빌드 (WSA2.spec = arm64)
echo "PyInstaller 빌드 시작..."
python3 -m PyInstaller WSA2.spec --clean --noconfirm

# 코드서명 (SPECTRA_SIGN_ID 설정 시) — DMG 만들기 전에 .app 서명
bash sign_app.sh dist/WSA2.app

# DMG 생성 (브랜드 — SPECTRA 배경 + 아이콘 배치)
echo "브랜드 DMG 생성 중..."
bash make_dmg.sh dist/WSA2.app "SPECTRA Installer" dist/WSA2_AppleSilicon.dmg

# 노타라이즈 + staple (SPECTRA_SIGN_ID + SPECTRA_NOTARY_PROFILE 설정 시)
bash notarize_dmg.sh dist/WSA2_AppleSilicon.dmg
# ── fallback (브랜드 실패 시 plain): ──
# DMG_DIR=/tmp/WSA2_silicon_dmg; rm -rf "$DMG_DIR"; mkdir -p "$DMG_DIR"
# cp -R dist/WSA2.app "$DMG_DIR"/; ln -sf /Applications "$DMG_DIR"/Applications
# hdiutil create -volname "SPECTRA Installer" -srcfolder "$DMG_DIR" -ov -format UDZO -fs HFS+ dist/WSA2_AppleSilicon.dmg

echo ""
echo "=== 빌드 완료 ==="
echo "Apple Silicon DMG: dist/WSA2_AppleSilicon.dmg"
echo "앱 크기: $(du -sh dist/WSA2.app | cut -f1)"
