#!/bin/bash
# ─────────────────────────────────────────────────────────────
# DMG 서명 + 노타라이즈(Apple) + staple → 첫 실행 시 경고 없이 열림
# 사용:  bash notarize_dmg.sh dist/WSA2_AppleSilicon.dmg
# 둘 다 설정돼야 동작:
#   export SPECTRA_SIGN_ID="Developer ID Application: 이름 (TEAMID)"
#   export SPECTRA_NOTARY_PROFILE="spectra-notary"   # 아래 store-credentials로 1회 생성
# 노타리 프로파일 최초 1회:
#   xcrun notarytool store-credentials "spectra-notary" \
#     --apple-id "you@mail.com" --team-id "TEAMID" --password "<앱전용비밀번호>"
# ─────────────────────────────────────────────────────────────
set -e
DMG="$1"
if [ -z "${SPECTRA_SIGN_ID:-}" ] || [ -z "${SPECTRA_NOTARY_PROFILE:-}" ]; then
  echo "ℹ️  노타라이즈 건너뜀 (SPECTRA_SIGN_ID / SPECTRA_NOTARY_PROFILE 미설정)"
  exit 0
fi
if [ ! -f "$DMG" ]; then echo "ERROR: DMG 없음: $DMG"; exit 1; fi
echo "🔏 DMG 서명: $DMG"
codesign --force --timestamp --sign "$SPECTRA_SIGN_ID" "$DMG"
echo "📤 Apple 노타라이즈 제출 (수 분 소요, --wait)..."
xcrun notarytool submit "$DMG" --keychain-profile "$SPECTRA_NOTARY_PROFILE" --wait
echo "📎 staple..."
xcrun stapler staple "$DMG"
xcrun stapler validate "$DMG"
echo "✅ 노타라이즈 + staple 완료 → 깨끗하게 열림"
