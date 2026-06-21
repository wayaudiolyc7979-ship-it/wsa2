# 다국어(KO/EN) 언어 전환 — 설계 (A안: 중앙 사전 + 재시작)

## Context
SPECTRA(`wayaudo2.py`, 단일 ~18k줄)의 UI 문자열은 방금 전부 **영어로 하드코딩**되었다(커밋 ac4046c, ~195개).
국내 사용자를 위해 **한국어 ↔ 영어 전환**이 필요하다. 단, 앱이 문자열을 여러 곳에서 즉석 `setText` 하는
구조라 **실시간 전환(모든 위젯 retranslate)** 은 비현실적 → **재시작 기반 전환(A안)** 으로 간다.

사용자 결정:
- 기본 언어 = **OS 로케일 따름**(맥이 한국어면 KO, 아니면 EN), 이후 수동 전환.
- 전환 = **자동 재시작**(짧은 확인 후).
- 한국어는 **초보자 친화적 쉬운 단어**(전문용어 최소화).

## Goals / Non-Goals
**Goals**
- 화면에 보이는 모든 영어 UI 문자열을 `t(...)`로 감싸 KO/EN 양쪽 표시.
- `_TR_KO` 중앙 사전(영어 원문 → 쉬운 한국어).
- 헤더에 `한 | EN` 토글 → settings 저장 → 자동 재시작.
- 첫 실행 시 OS 언어로 기본 결정.

**Non-Goals**
- 실시간(무재시작) 전환.
- 로그/주석/docstring 번역(영어/한글 그대로 — UI 아님).
- 영어 외 제3언어, Qt .ts/.qm 툴체인.

## Architecture

### 1) 언어 상태 + 조회 함수 (파일 상단, settings 로드 직후)
```python
_LANG = 'en'   # 'en' | 'ko' — 시작 시 settings/OS 로 확정
def _resolve_lang(settings):
    v = settings.get('lang')
    if v in ('en', 'ko'): return v
    try:
        from PyQt5.QtCore import QLocale
        return 'ko' if QLocale.system().name().startswith('ko') else 'en'
    except Exception:
        return 'en'
def t(s):
    """영어 원문 s 를 현재 언어로. en=그대로, ko=_TR_KO 조회(없으면 원문)."""
    return _TR_KO.get(s, s) if _LANG == 'ko' else s
```
- `_LANG` 은 앱 시작에서 `_resolve_lang(_load_settings())` 로 1회 설정(전역).
- **영어 원문을 키로 사용** → 호출부는 `QLabel(t('Save Preset'))` 처럼 감싸기만. 키 작명 불필요.

### 2) 번역 사전 `_TR_KO` (파일 상단, dict)
- 영어 UI 문자열 → **쉬운 한국어** ~195개. 전문용어는 일반어로:
  - Calibration→마이크 보정, Offset→보정값, Auto Calculate Offset→보정값 자동 계산,
    Reference→기준 신호, True Peak→순간 최대, Save Preset→설정 저장,
    Measure Level→레벨 재기, Reset→초기화 등.
- ac4046c 의 KO→EN 매핑(git 히스토리)을 출발점으로 하되 **초보자 톤으로 다듬는다**.

### 3) UI 문자열 `t()` 래핑 (~195개)
- 대상: `.setText/.setWindowTitle/.setToolTip/.setPlaceholderText/.setTitle`, `QLabel/QPushButton/QCheckBox/QGroupBox/QAction(...)`, `.addItem(s)`(표시용), `_brand_msg`/`_text_input_dialog` 의 title/text/label, `QMessageBox`, 메뉴 텍스트.
- f-string 은 영어 부분만 키로 감싸기 어려우므로: 고정 문자열은 `t('...')`, 동적 f-string 은 **포맷 템플릿을 키로** (예: `t('Delete all {n} captures?').format(n=n)`) — 사전에 템플릿째 등록.
- **제외**: 로그(`_alog`/`_diag`/`print`), 주석, 로직 비교/딕셔너리 키/`currentData` userData(예: 빌트인 필터 `'내장'`은 이미 한글 로직키 → 유지).

### 4) 헤더 언어 토글
- 위치: 상단 헤더 테마(Light) 토글 옆. `한 | EN` 세그먼트(테마 토글과 동일 룩).
- 동작: 클릭 → `settings['lang']=새값` + `_save_settings` → `_brand_msg`("언어를 바꾸려면 재시작합니다 / Restart to apply language", ok/cancel) → OK면 **자동 재시작**.
- 재시작: 오디오/스트림 정리 후 `os.execv(sys.executable, [sys.executable]+sys.argv)`. (앱은 종료에 `os._exit` 사용 — execv 도 Python finalize 우회라 동일 패턴, SIGSEGV 회피)

## Data (settings.json)
```jsonc
{ "lang": "ko" }   // 'en' | 'ko'. 없으면 OS 로케일로 결정(저장은 토글 시).
```
기존 키 전부 보존.

## Edge cases
- settings 에 lang 없음 → OS 로케일. OS 가 ko 아니면 en.
- `_TR_KO` 에 없는 영어 문자열(번역 누락) → 원문(영어) 그대로 표시(안 깨짐).
- 재시작 실패(execv 예외) → 경고 로그 + "수동 재시작 필요" 메시지, 앱은 계속 동작(설정은 이미 저장됨).
- 토글이 settings 저장만 하고 재시작 취소 → 다음 실행에 적용.

## Verification
1. `python3 -c "import ast; ast.parse(...)"` 구문 게이트.
2. `python3 selfcheck.py` 15/15 유지. **추가 check**: `t()` 동작(en=원문, ko=_TR_KO 조회), `_TR_KO` 키 누락 시 원문 폴백.
3. 격리 실행으로 양 언어 렌더: `WSA2_SETTINGS_PATH=/tmp/ko.json`(lang=ko)·`/tmp/en.json`(lang=en) 로 CalibDialog 등 오프스크린 렌더 → PNG 로 한/영 확인.
4. 사전 커버리지: `grep` 으로 `t(` 안 감싼 잔여 영어 UI 문자열 점검, `_TR_KO` 키 ↔ 코드 사용 문자열 일치 확인.
5. 사용자 실측: 헤더 토글 → 자동 재시작 → 반대 언어로 뜨는지.

## 구현 순서(요약)
1. `t()`/`_LANG`/`_resolve_lang` + 빈 `_TR_KO` 골격 + 시작 시 `_LANG` 확정 + selfcheck `t()` 테스트.
2. `_TR_KO` 사전 작성(쉬운 한국어 ~195개).
3. UI 문자열 `t()` 래핑(영역별: 다이얼로그/툴바/메뉴/카드/SPL/Loudness…).
4. 헤더 토글 + 자동 재시작.
5. 양 언어 렌더 검증 + 잔여 미번역 점검.
