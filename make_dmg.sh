#!/bin/bash
# ─────────────────────────────────────────────────────────────
# 브랜드 DMG 생성 — SPECTRA 배경 + 아이콘 자동 배치 + "Applications로 드래그"
# 사용:  bash make_dmg.sh <APP경로> <볼륨명> <출력.dmg>
#   예:  bash make_dmg.sh dist/WSA2.app "SPECTRA Installer" dist/WSA2_AppleSilicon.dmg
#
# ⚠️ Finder AppleScript를 쓰므로 **로컬 macOS(데스크톱 세션)** 에서만 동작.
#    (CI/헤드리스에선 창 스타일이 안 먹음 → 그 경우 plain hdiutil fallback 사용)
# 설치 시 보이는 앱 이름은 'SPECTRA.app'(브랜딩). 내부 식별자(WSA2)·라이선스와 무관.
# ─────────────────────────────────────────────────────────────
set -e
APP="$1"; VOL="$2"; OUT="$3"
HERE="$(cd "$(dirname "$0")" && pwd)"
BG="$HERE/dmg_background.png"
APPNAME="SPECTRA.app"

if [ ! -d "$APP" ]; then echo "ERROR: APP 없음: $APP"; exit 1; fi
if [ ! -f "$BG" ]; then echo "ERROR: 배경 없음: $BG"; exit 1; fi

STAGE=$(mktemp -d)
cp -R "$APP" "$STAGE/$APPNAME"
ln -s /Applications "$STAGE/Applications"
mkdir "$STAGE/.background"; cp "$BG" "$STAGE/.background/bg.png"
# 배경(1200x800)을 Retina @2x(144 DPI)로 표시 → Finder가 600x400 포인트로 렌더.
# (DPI가 100이면 통짜로 펼쳐져 아이콘이 좌측에 몰림)
sips -s dpiWidth 144 -s dpiHeight 144 "$STAGE/.background/bg.png" >/dev/null 2>&1 || true

TMP="$(mktemp -u).dmg"
hdiutil create -volname "$VOL" -srcfolder "$STAGE" -fs HFS+ -format UDRW -ov "$TMP" >/dev/null
DEV=$(hdiutil attach -readwrite -noverify -noautoopen "$TMP" | egrep '^/dev/' | head -1 | awk '{print $1}')
sleep 2

osascript <<EOF || echo "⚠️ Finder 스타일 적용 실패(헤드리스?) — 기능엔 영향 없음, 배경/배치만 기본값"
tell application "Finder"
  tell disk "$VOL"
    open
    set current view of container window to icon view
    set toolbar visible of container window to false
    set statusbar visible of container window to false
    set the bounds of container window to {200, 120, 800, 548}
    set vo to the icon view options of container window
    set arrangement of vo to not arranged
    set icon size of vo to 104
    set background picture of vo to file ".background:bg.png"
    set position of item "$APPNAME" of container window to {148, 238}
    set position of item "Applications" of container window to {451, 238}
    update without registering applications
    delay 1
    close
  end tell
end tell
EOF

sync; sleep 1
hdiutil detach "$DEV" >/dev/null 2>&1 || hdiutil detach "$DEV" -force >/dev/null 2>&1 || true
rm -f "$OUT"
hdiutil convert "$TMP" -format UDZO -imagekey zlib-level=9 -o "$OUT" >/dev/null
rm -f "$TMP"; rm -rf "$STAGE"
echo "✅ 브랜드 DMG: $OUT"
