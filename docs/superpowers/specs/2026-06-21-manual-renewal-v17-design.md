# SPECTRA 메뉴얼 리뉴얼 (v1.7 기준) — 설계 문서

작성일: 2026-06-21 · 브랜치: feature/v1.7-engines

## 목표

기능이 많아진 SPECTRA를 **하나도 빠짐없이** 담는 메뉴얼로 리뉴얼한다.
- 전 기능 + **버튼별 ①②③ 콜아웃**
- 사진(스크린샷) 중심
- v1.7 기능 반영 (TF 2-엔진, 라우드니스 시안C, SPL 알람, RTA, 팝아웃/동시보기, 재캡쳐, 딜레이 m표기 등)
- 초보자 친화 한국어 톤(기존 voice) 유지

대상 파일: `MANUAL.html` (단일 HTML, 다크 브랜드 테마). 기존 411줄 → 전면 확장.

## 전수조사 결과 (요점)

- TF 엔진 셀렉터 라벨 = **`Single / Adaptive`** (MTW 아님, IP 회피 개명 반영됨). `eng_cb`.
- 버전 상수 `_APP_VERSION='1.6.1'` (빌드 전 bump 금지 정책). 본문엔 버전 숫자 미표기(에버그린).
- **Show Mode = 메뉴 진입점 주석처리(숨김)** → 메뉴얼 제외.
- 네이티브 메뉴바: **View**(SPL Meter / SPL Alarm / Spectrum·TF·Stereo 별도 창 ⌘⇧S/T/L / Split View ⌘⇧2), **Help**(About / Manual ⌘? / Keyboard Shortcuts ? / Release Notes / Open Log Folder / Quit ⌘Q).
- TF 단위 콤보 `unit_cb` = ms / ms·m / m (음속 343).
- 라우드니스 6지표 = M / S / TP / LRA / PLR / PSR + AVG·LIVE 토글 + 거대 PROGRAM 숫자 + 컴플라이언스 뱃지(PASS/CHECK) + 히스토리 그래프 + Target·LU 토글.

## 섹션 구조 (15개)

1. SPECTRA가 뭐예요? (유지)
2. 처음 시작하기 (갱신 — 네이티브 메뉴바 포함 화면 둘러보기)
3. 알아두면 좋은 기초 (유지)
4. 공통 요소 — 메뉴바·트랜스포트·우측 패널 (신규)
5. 창 분리 & 동시 보기 (신규 — 팝아웃 ⌘⇧S/T/L, Split ⌘⇧2, 벡터스코프/레이더 팝아웃)
6. Spectrum 탭 (확장 — 툴바 버튼별 콜아웃)
7. Transfer Function 탭 (대폭 확장 — 엔진/발생기/Ref·Meas/딜레이+단위/3그래프/RTA/모드들)
8. Stereo Loudness 탭 (전면 재작성 — 시안C)
9. 마이크 캘리브레이션 (갱신)
10. SPL Meter 창 (확장 — 핀·Reset Max·소스 선택)
11. SPL 알람 창 (신규)
12. 캡쳐로 비교하기 (확장 — 재캡쳐 R·일괄토글·그룹타겟·Delta·안정화·Export·Delete All)
13. 단축키 (확장)
14. 라이선스·About·릴리즈노트·로그 (확장)
15. 문제 해결 (확장)

## 스크린샷 계획

- 그대로 활용(4): spectrum, calib, spl, spl_settings
- 재촬영(2): stereo(시안C), tf(엔진 셀렉터)
- 신규(6): tf_rta, tf_sweep(선택), spl_alarm, popout_split, capture_drawer, menubar
- 유지: tf_delta

본문엔 모든 자리를 **번호 콜아웃 포함 플레이스홀더**로 잡고, 별도 **촬영 체크리스트**(파일명·화면·▶Start 후 상태) 제공.

## 콜아웃 방식

스크린샷 아래 **번호 범례 표**(툴바 왼→오 순서)가 기본.
실제 사진 입수 후 **CSS 번호 뱃지(퍼센트 좌표) 오버레이**로 버튼=설명 시각 연결(래스터 직접 그리기 금지 → 유지보수 용이).

## 비범위 (YAGNI)

- Show Mode(숨김) 문서화 안 함.
- 자체완결 base64 인라인 사본 만들기는 사진 확정 후 별도.
- 영문판은 추후.
