<div align="center">

# 〰️ SPECTRA

### *See your sound.*

**정밀 음향 측정을, 가장 세련되게.**
Spectrum Analyzer · by **WAYAUDIO**

![version](https://img.shields.io/badge/version-2.0-4E7DF0)
![platform](https://img.shields.io/badge/platform-macOS%20·%20Windows-9B5DE5)
![license](https://img.shields.io/badge/license-Proprietary-8E8E93)

</div>

---

SPECTRA는 소리를 **눈으로 보는** 음향 측정 도구입니다. 실시간 스펙트럼 분석부터 스피커·룸 전달함수(Transfer Function), 방송 라우드니스(LUFS)까지 — 프로 현장의 측정을 하나의 앱에 담았습니다.

![SPECTRA — Spectrum](docs/img/spectrum.png)

<div align="center">

| Transfer Function | Stereo Loudness |
|:---:|:---:|
| ![Transfer Function](docs/img/tf.png) | ![Stereo Loudness](docs/img/stereo.png) |

</div>

## ✨ 기능

| 탭 | 설명 |
|---|---|
| **Spectrum** | 실시간 주파수 분석 — FFT · 1/3~1/24 옥타브 · 스펙트로그램, 멀티채널 동시 오버레이, 정밀 SPL/LAeq |
| **Transfer Function** | 스피커·룸 측정 — 매그니튜드 · 위상 · 코히어런스 · 임펄스 응답, 자동 딜레이, 다지점 비교, 코히런스 블랭킹, 라이브 공간 평균 |
| **Stereo Loudness** | 방송·음원 라우드니스 — 벡터스코프 · 라우드니스 레이더 · M/S/I · True Peak · LRA |

- ⚡ 적응형 TF 엔진 (멀티레이트 라이브) + 정밀 스윕 측정 (Farina ESS · THD/SNR)
- 📐 THD 측정 (커서 총고조파왜곡 %) · 🖥️ 글랜스 쇼 모드 (FOH 풀스크린 SPL)
- 💾 이름 프리셋 — 세 탭 설정을 저장하고 한 번에 불러오기 (+ 마지막 세션 자동 복원)
- 🌐 한국어 / 영어 전환 · 🌗 다크 / 라이트 테마
- 🎚️ 마이크 캘리브레이션 (94 / 114 dBSPL 기준기)
- 📊 자유 배치 SPL 미터 · 🚦 SPL 임계 알람 창
- 🔊 신호 발생기 내장 (Pink · White · Sine · Sweep · File)
- 📸 캡쳐 & 비교 (Δ)

## 📦 설치 (사용자)

**macOS** — 받은 `.dmg`를 열고 **SPECTRA**를 **Applications**로 드래그.
처음 실행 시 보안 경고가 뜨면 아이콘 **우클릭 → 열기** 한 번.

요구사항: macOS 12+ (Apple Silicon / Intel) · Windows 10+

## 🛠️ 빌드 (개발자)

```bash
# macOS Apple Silicon (arm64)
bash build_silicon.sh

# macOS Intel (x86_64, Rosetta 자동)
bash build_intel.sh
```

- **Windows**: `v*` 태그 push 시 GitHub Actions(`.github/workflows/build-windows.yml`)가 자동 빌드 → `SPECTRA.exe` 아티팩트. 또는 Windows에서 `pyinstaller WSA2_Windows.spec`.
- **브랜드 DMG**: `make_dmg.sh` (빌드 스크립트가 자동 호출)
- **버전 올리기**: `bash bump_version.sh 1.6` (또는 `1.5.1` 패치) — 모든 버전 표기 일괄 갱신

## 🔐 코드 서명 · 노타라이즈

미서명 앱은 첫 실행 시 경고가 떠요. Apple Developer ID로 서명·노타라이즈하려면 **[`SIGNING.md`](SIGNING.md)** 참고.
(환경변수 `SPECTRA_SIGN_ID` / `SPECTRA_NOTARY_PROFILE` 설정 시 빌드가 자동 처리)

## 📖 문서

| | |
|---|---|
| 사용 설명서 | [`MANUAL.html`](MANUAL.html) — 초보자용 전기능 가이드 (앱 안 **Help** 버튼으로도 열림) |
| 릴리스 노트 | [`RELEASE_NOTES.md`](RELEASE_NOTES.md) |
| 제품 소개 | [`LANDING.html`](LANDING.html) |

## 📂 레포 구조

```
─ 앱 코드  (v2.0에서 단일 파일 → 모듈 패키지로 분해)
  wayaudo2.py              진입점 · 스플래시 · _APP_VERSION (~670줄)
  spectra/                 앱 본체 패키지
    dsp/                   측정·DSP (weighting · tf · loudness · farina) — 골든테스트 대상
    core/                  설정 · i18n · 로깅 · 라이선스
    audio/                 공유 오디오 엔진 (장치당 스트림 1개, 탭 동시측정)
    ui/                    토큰·색·아이콘·위젯·다이얼로그·캔버스·탭·MainWindow
  ed25519_min.py           순수 파이썬 Ed25519 (라이선스 검증)
  selfcheck.py             헤드리스 위젯 렌더 회귀 하네스
  tests/                   DSP 골든값 pytest

─ 빌드 / 배포 (루트 고정 — spec·스크립트가 경로로 참조)
  WSA2.spec / build_silicon.sh        macOS Apple Silicon
  WSA2_Intel.spec / build_intel.sh    macOS Intel
  WSA2_Windows.spec / build_windows.bat · version_info.txt · icon.ico   Windows
  make_dmg.sh · dmg_background.png     브랜드 DMG
  sign_app.sh · notarize_dmg.sh · entitlements.plist   서명·노타라이즈
  bump_version.sh                      버전 일괄 변경
  splash.png · icon.icns · app_icon_1024.png   브랜드 자산

─ 라이선스 도구
  generate_license.py · wsa2_license_tool.py · LicenseTool.spec
  (license_ed25519_private.key = .gitignore, 절대 커밋 금지)

─ 문서 (루트)
  README · CLAUDE · ISSUES · 남은작업 · 2.0_MODULE_PLAN · LICENSING · SIGNING (.md)
  MANUAL.html · LANDING.html · RELEASE_NOTES.md/.html   제품 문서

─ 폴더
  docs/            beta_dev_log · img/(스크린샷) · concepts/(디자인 실험본)
  tests/           테스트
  backups/ build/ dist/   (.gitignore — 생성물)
```

---

<div align="center">

© WAYAUDIO · *See your sound.*

</div>
