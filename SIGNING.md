# SPECTRA 코드 서명 + 노타라이즈 가이드

미서명 앱은 첫 실행 시 **"확인되지 않은 개발자 / 손상되었습니다"** 경고가 떠서
브랜드 신뢰를 크게 깎습니다. Apple Developer ID로 서명+노타라이즈하면 깨끗하게 열립니다.

빌드 스크립트(`build_silicon.sh` / `build_intel.sh`)는 아래 환경변수가 있으면
**자동으로 서명·노타라이즈**하고, 없으면 조용히 건너뜁니다(미서명 빌드).

---

## 1회 준비

### ① Apple Developer 계정
- 유료 멤버십($99/년) 필요. https://developer.apple.com

### ② Developer ID Application 인증서
- Xcode → Settings → Accounts → Manage Certificates → `+` → **Developer ID Application**
- 또는 developer.apple.com 에서 발급 후 키체인에 설치
- 확인:  `security find-identity -v -p codesigning`  → "Developer ID Application: 이름 (TEAMID)" 가 보여야 함

### ③ 노타리 자격 저장 (1회)
앱 전용 비밀번호를 https://appleid.apple.com → 로그인&보안 → 앱 암호 에서 생성 후:
```bash
xcrun notarytool store-credentials "spectra-notary" \
  --apple-id "you@example.com" \
  --team-id "TEAMID" \
  --password "xxxx-xxxx-xxxx-xxxx"   # 앱 전용 비밀번호
```

---

## 빌드할 때마다

```bash
export SPECTRA_SIGN_ID="Developer ID Application: Your Name (TEAMID)"
export SPECTRA_NOTARY_PROFILE="spectra-notary"

bash build_silicon.sh     # 또는 build_intel.sh
```

스크립트가 자동으로:
1. `.app` 코드서명 (하드런타임 + `entitlements.plist`)
2. 브랜드 DMG 생성 (`make_dmg.sh`)
3. DMG 서명 → Apple 노타라이즈 제출(`--wait`) → staple

`SPECTRA_SIGN_ID`만 있고 `SPECTRA_NOTARY_PROFILE`가 없으면 **서명만** 하고 노타라이즈는 건너뜁니다.

---

## 검증
```bash
codesign --verify --deep --strict --verbose=2 dist/WSA2.app   # 서명 OK?
xcrun stapler validate dist/WSA2_AppleSilicon.dmg             # 노타라이즈 staple OK?
spctl -a -vvv -t install dist/WSA2_AppleSilicon.dmg          # Gatekeeper 통과?
```

## 관련 파일
- `sign_app.sh` — .app 서명
- `notarize_dmg.sh` — DMG 서명+노타라이즈+staple
- `entitlements.plist` — audio-input + 하드런타임 호환 entitlements
- `make_dmg.sh` — 브랜드 DMG (서명/노타라이즈와 별개)
