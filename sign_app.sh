#!/bin/bash
# ─────────────────────────────────────────────────────────────
# .app 코드서명 (Developer ID Application + 하드런타임 + 타임스탬프)
# 사용:  bash sign_app.sh dist/WSA2.app
# 환경변수 SPECTRA_SIGN_ID 없으면 건너뜀(미서명 빌드).
#   export SPECTRA_SIGN_ID="Developer ID Application: Your Name (TEAMID)"
# ─────────────────────────────────────────────────────────────
set -e
APP="$1"; HERE="$(cd "$(dirname "$0")" && pwd)"
if [ -z "${SPECTRA_SIGN_ID:-}" ]; then
  echo "ℹ️  SPECTRA_SIGN_ID 미설정 → 미서명 빌드 (배포 시 '확인되지 않은 개발자' 경고 발생)"
  echo "    서명하려면:  export SPECTRA_SIGN_ID=\"Developer ID Application: 이름 (TEAMID)\""
  exit 0
fi
if [ ! -d "$APP" ]; then echo "ERROR: APP 없음: $APP"; exit 1; fi
echo "🔏 코드서명: $APP"
echo "   ID: $SPECTRA_SIGN_ID"
# --deep: 내부 dylib/프레임워크까지. --options runtime: 하드런타임(노타라이즈 필수).
codesign --deep --force --options runtime --timestamp \
  --entitlements "$HERE/entitlements.plist" \
  --sign "$SPECTRA_SIGN_ID" "$APP"
codesign --verify --deep --strict --verbose=2 "$APP"
echo "✅ 서명 검증 OK"
