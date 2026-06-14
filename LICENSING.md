# SPECTRA 라이선스 운영 가이드 (개발자 전용)

> 이 문서는 **라이선스를 발급·관리하는 사람(WAYAUDIO)** 을 위한 내부 문서입니다.
> 최종 사용자에게 배포하지 마세요.

## 한눈에

| | 역할 | 위치 | 비밀? |
|---|---|---|---|
| **개인키** `license_ed25519_private.key` | 키 **서명**(발급) | 개발자 PC에만 (git 제외) | 🔴 **절대 비밀** |
| **공개키** `_LIC_PUBKEY` | 키 **검증** | 앱(wayaudo2.py)에 박힘 | 공개 OK |
| **생성기** `generate_license.py` / `wsa2_license_tool.py` | 발급 도구 | git(GitHub) | 코드(공개 OK) |
| 레거시 HMAC `_LIC_SECRET` | v1.0 옛 키 검증 | 앱·생성기 | (구식, 신규 발급 X) |

보안 핵심: **개인키만 안 새면 위조 불가.** 앱·생성기 코드가 다 털려도 OK.

---

## 1. 라이선스 발급하기

### CLI (간단)
```bash
python3 generate_license.py
# → 고객 머신 ID(12자리) 입력 → 만료연도(0=영구) → 시리얼 키 출력
```

### GUI (기록 관리)
```bash
python3 wsa2_license_tool.py
# 발급 내역이 issued_keys.json 에 저장됨
```

### 흐름
1. **고객**: 앱 우측 아래 **License** → About 창의 **머신 ID** 복사해서 전달 (또는 Copy Machine ID)
2. **나**: 생성기에 그 머신 ID + 만료 입력 → 시리얼 키 발급
3. **고객**: 앱 활성화 창에 시리얼 키 붙여넣기 → 활성화 (그 컴퓨터에서만 작동)

> 만료: `0` = 영구 · `2027` = 2027년 12월 31일까지

---

## 2. ⚠️ 개인키 백업 (제일 중요)

`license_ed25519_private.key` = **라이선스 마스터 키.** 64글자 텍스트.

- ✅ **비밀번호 관리자**(1Password 등)에 "SPECTRA 라이선스 마스터키"로 저장 — 추천
- ✅ 암호화 USB / 안전한 외장 백업
- 🚫 **절대** git 커밋·이메일·클라우드 평문 저장 금지 (`.gitignore`에 등록돼 있음)

**잃어버리면**: 기존 고객은 계속 작동(공개키로 검증)하지만 **신규 키 발급 불가** → 아래 키 로테이션 필요.

---

## 3. 🔧 개인키를 잃어버렸을 때 (키 로테이션)

기존 고객을 안 끊고 복구하는 절차:

1. **새 키쌍 생성**
   ```bash
   python3 -c "import os,ed25519_min as e; s=os.urandom(32); open('license_ed25519_private.key','w').write(s.hex()); print('새 공개키:', e.public_key(s).hex())"
   ```
2. **앱에 새 공개키 추가** — `wayaudo2.py`의 `_LIC_PUBKEY`를 **리스트로** 바꿔 옛 공개키 + 새 공개키 둘 다 인정하게:
   ```python
   _LIC_PUBKEYS = [bytes.fromhex('옛공개키'), bytes.fromhex('새공개키')]
   # verify_license에서 any(_ed25519.verify(sig, payload, pk) for pk in _LIC_PUBKEYS)
   ```
   → 기존 발급 키(옛 공개키로 서명됨)는 계속 검증되고, 새 키는 새 공개키로 검증.
3. **앱 업데이트 배포** (버전 올려서). 이후 발급은 새 개인키로.

> 💡 미리 대비하려면 처음부터 `_LIC_PUBKEYS` 리스트로 설계해두면 로테이션이 더 매끈함. (지금은 단일 `_LIC_PUBKEY` — 필요 시 Claude에게 "멀티 공개키로 바꿔줘" 요청)

---

## 4. 레거시 (v1.0 HMAC 키 · 3명)

- v1.0 때 HMAC 방식으로 발급한 키 3개는 **듀얼 검증으로 계속 작동**합니다(`_LIC_SECRET`).
- **신규 발급은 전부 Ed25519** (생성기가 그렇게 동작). HMAC 키는 더 만들지 마세요.
- 언젠가 3명이 모두 갱신/이탈하면 `_LIC_SECRET`과 HMAC 폴백을 제거해도 됩니다.

---

## 5. 키 형식 (참고)

- 신규(Ed25519): `base32( 0x01 + payload + 서명(64B) )`, payload = `머신ID(12):만료(4자리)`
- 레거시(HMAC): `base32( HMAC서명(10B) + payload )`
- 검증: 앱 `verify_license()` — Ed25519 먼저 → 실패 시 HMAC. 머신 ID·만료 확인.

---

*SPECTRA · by WAYAUDIO — See your sound.*
