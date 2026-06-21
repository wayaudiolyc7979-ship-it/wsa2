# KO/EN 언어 전환 (A안) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** SPECTRA UI를 한국어↔영어로 전환(헤더 토글 → 자동 재시작). 영어 원문을 키로 쓰는 `t()` + 중앙 사전 `_TR_KO`.

**Architecture:** 모든 영어 UI 문자열을 `t('English')`로 감싼다. `t()`는 `_LANG=='ko'`면 `_TR_KO`에서 쉬운 한국어를 찾고 없으면 원문, `en`이면 원문 그대로. `_LANG`은 시작 시 `settings['lang']`(없으면 OS 로케일)로 확정. 헤더 토글이 `settings['lang']` 저장 후 `os.execv`로 자동 재시작.

**Tech Stack:** Python3, PyQt5, 단일 파일 `wayaudo2.py`. 기존 `_load_settings/_save_settings`, `QLocale`, `os.execv`, headless 검증 `selfcheck.py`.

## Global Constraints
- **단일 파일:** 앱 로직 전부 `wayaudo2.py`. 새 파일 금지.
- **헤드리스 격리 필수:** 모든 python 실행에 `QT_QPA_PLATFORM=offscreen WSA2_SETTINGS_PATH=/tmp/x.json WSA2_CAPTURES_PATH=/tmp/c.json` — 사용자 실제 settings.json 보호.
- **구문 게이트:** 매 변경 후 `python3 -c "import ast; ast.parse(open('wayaudo2.py').read())"`.
- **회귀:** `python3 selfcheck.py` 항상 통과(현재 15/15). 새 함수=check() 추가.
- **MainWindow 전체는 offscreen segfault** → 위젯/함수/다이얼로그 단위로만 headless 테스트.
- **번역 대상 = "표시 문자열"만.** 로그(`_alog`/`_diag`/`print`), 주석/docstring, 로직 비교·딕셔너리 키·`currentData` userData(예: 빌트인 필터 `'내장'`)는 **건드리지 않는다.**
- **번역 누락 폴백:** `_TR_KO`에 없는 키 → 영어 원문 그대로(절대 KeyError 안 남).
- **쉬운 한국어:** 초보자 친화 일반어. 전문용어 최소화(Calibration→마이크 보정, Offset→보정값, True Peak→순간 최대 등).
- 커밋 메시지 끝에 `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.

## 번역 대상 원천(Source of truth)
직전 커밋 **ac4046c** 가 한글→영어로 바꾼 그 문자열들이 정확히 "UI 표시 문자열"이다.
`git show ac4046c` 의 diff 에서 **삭제줄(한글 원문) ↔ 추가줄(영어)** 쌍이 곧 `_TR_KO` 의 (en→ko) 후보다.
→ Task2/3 은 이 diff 를 1차 출처로 쓴다(한국어는 거기서 출발하되 **쉬운 말로 다듬는다**).

---

## File Structure
- `wayaudo2.py` 수정만:
  - 상단(예: `_load_settings` 정의 근처): `_LANG`, `_resolve_lang()`, `t()`, `_TR_KO`(dict), 시작 시 `_LANG` 확정
  - 전역: UI 표시 문자열 ~195개를 `t(...)` 래핑
  - 헤더 빌드부: `한 | EN` 토글 + `_on_lang_toggle()` + `_restart_app()`
- `selfcheck.py` 수정만: `t()` 동작 check 추가.

---

## Task 1: i18n 코어 골격 (`t()` / `_LANG` / 빈 `_TR_KO`)

**Files:**
- Modify: `wayaudo2.py` — `_load_settings()`(`:357` 부근) 위/아래에 i18n 코어 추가, 모듈 로드시 `_LANG` 확정
- Test: `selfcheck.py` — `t()` check 추가

**Interfaces:**
- Produces:
  - 전역 `_LANG: str` ('en'|'ko')
  - `t(s: str) -> str` — en=원문, ko=`_TR_KO.get(s, s)`
  - `_resolve_lang(settings: dict) -> str`
  - `_set_lang(v)` — `_LANG` 전역 갱신(테스트/토글용)
  - `_TR_KO: dict` (이 태스크에선 빈 dict)

- [ ] **Step 1: selfcheck 에 실패 테스트 추가**

`selfcheck.py` 끝에 추가:
```python
def _i18n_t():
    """t(): en=원문, ko=_TR_KO 조회(없으면 원문 폴백)."""
    w._set_lang('en')
    assert w.t('Save Preset') == 'Save Preset'
    w._TR_KO['Save Preset'] = '설정 저장'      # 임시 주입
    w._set_lang('ko')
    assert w.t('Save Preset') == '설정 저장'
    assert w.t('No Such Key') == 'No Such Key'  # 누락 폴백
    w._TR_KO.pop('Save Preset', None); w._set_lang('en')   # 원복
    return 'en passthrough / ko lookup / fallback OK'
check('i18n t() 동작', _i18n_t)
```

- [ ] **Step 2: 실패 확인**

Run: `cd /Users/yuncheollee/WSA2 && QT_QPA_PLATFORM=offscreen WSA2_SETTINGS_PATH=/tmp/x.json WSA2_CAPTURES_PATH=/tmp/c.json python3 selfcheck.py "i18n"`
Expected: FAIL — `AttributeError: module 'wayaudo2' has no attribute '_set_lang'` (또는 t/_TR_KO 없음)

- [ ] **Step 3: 코어 구현**

`wayaudo2.py` 의 `_load_settings()` 정의 **직전**(또는 `_SETTINGS_PATH` 근처)에 추가:
```python
# ── i18n: 영어 원문을 키로 쓰는 경량 번역 ──────────────────────────
_TR_KO = {}        # {english_ui_string: 쉬운_한국어}  (Task 2에서 채움)
_LANG = 'en'       # 'en' | 'ko' — 모듈 로드 끝에서 확정

def _resolve_lang(settings):
    v = settings.get('lang') if isinstance(settings, dict) else None
    if v in ('en', 'ko'):
        return v
    try:
        from PyQt5.QtCore import QLocale
        return 'ko' if QLocale.system().name().startswith('ko') else 'en'
    except Exception:
        return 'en'

def _set_lang(v):
    global _LANG
    _LANG = v if v in ('en', 'ko') else 'en'

def t(s):
    """영어 원문 s 를 현재 언어로. en=그대로, ko=_TR_KO 조회(없으면 원문 폴백)."""
    return _TR_KO.get(s, s) if _LANG == 'ko' else s
```
그리고 `_load_settings`/`_save_settings` 정의 **이후**(파일에서 settings 를 처음 읽을 수 있는 지점, 예: `_SETTINGS_PATH` 블록 끝)에서 한 번 확정:
```python
try:
    _set_lang(_resolve_lang(_load_settings()))
except Exception:
    pass
```
> 주의: `_load_settings`/`_save_settings` 가 `_TR_KO` 정의보다 **뒤**에 있으면, 위 `_set_lang(...)` 호출은 그 함수들 **정의 이후**에 두어야 한다. grep 으로 `def _load_settings` 위치 확인 후 그 아래에 호출 한 줄을 넣는다.

- [ ] **Step 4: 통과 확인**

Run: `cd /Users/yuncheollee/WSA2 && python3 -c "import ast; ast.parse(open('wayaudo2.py').read())" && QT_QPA_PLATFORM=offscreen WSA2_SETTINGS_PATH=/tmp/x.json WSA2_CAPTURES_PATH=/tmp/c.json python3 selfcheck.py "i18n"`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add wayaudo2.py selfcheck.py
git commit -m "feat(i18n): t()/_LANG/_resolve_lang 코어 + 빈 _TR_KO (영어원문 키)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: 번역 사전 `_TR_KO` 작성 (쉬운 한국어 ~195개)

**Files:**
- Modify: `wayaudo2.py` — `_TR_KO = {}` 를 실제 엔트리로 채움

**Interfaces:**
- Consumes: Task1 `_TR_KO`, `t()`
- Produces: `_TR_KO` 에 ~195 (en→ko) 엔트리

- [ ] **Step 1: 영어 UI 문자열 목록 추출**

```bash
cd /Users/yuncheollee/WSA2
git show ac4046c > /tmp/i18n_src.diff
```
`/tmp/i18n_src.diff` 에서 `-`(한글 원문) / `+`(영어) 쌍을 읽어 **영어 문자열 = 키**, 한글 원문 = 참고로 삼는다. (f-string 은 `{...}` 포함 템플릿 전체가 키)

- [ ] **Step 2: `_TR_KO` 채우기**

`wayaudo2.py` 의 `_TR_KO = {}` 를 아래 형태로 교체(모든 항목 작성). **한국어는 ac4046c 의 원문을 출발점으로 하되 초보자 친화 쉬운 말로 다듬는다.** 예시 톤:
```python
_TR_KO = {
    # 캘리브레이션
    'Mic Calibration': '마이크 보정',
    'Measure Level  (3s)': '레벨 재기  (3초)',
    'Auto Calculate Offset': '보정값 자동 계산',
    'Calibrator reference:': '보정 기준 신호:',
    'Manual (dBFS):': '직접 입력 (dBFS):',
    'Applied offset (dB):': '적용 보정값 (dB):',
    'Reset': '초기화', 'Select': '선택', '● Selected': '● 선택됨',
    # 프리셋
    'Save Preset': '설정 저장', 'Name:': '이름:',
    'Overwrite': '덮어쓰기', 'Delete preset "{name}"?': '"{name}" 설정을 지울까요?',
    # ... (ac4046c 의 전 항목을 같은 방식으로)
}
```
규칙: 동적 문구는 **포맷 템플릿째** 키로(예: `'Delete all {n} captures?': '캡쳐 {n}개를 모두 지울까요?'`). `{n}`/`{name}` 등 플레이스홀더는 **그대로** 둔다.

- [ ] **Step 3: 사전 무결성 + 폴백 확인**

`selfcheck.py` 에 검증 check 추가(키에 한글 섞임/플레이스홀더 불일치 점검):
```python
def _i18n_dict():
    import re
    bad=[]
    for en,ko in w._TR_KO.items():
        # 키(en)에 한글이 있으면 잘못 — 키는 영어 원문이어야
        if re.search(r'[가-힣]', en): bad.append(('KEY 한글', en))
        # 플레이스홀더 집합 일치
        if set(re.findall(r'\{[^}]+\}', en)) != set(re.findall(r'\{[^}]+\}', ko)):
            bad.append(('PLACEHOLDER', en))
    assert not bad, bad[:5]
    return f'{len(w._TR_KO)} entries OK'
check('i18n 사전 무결성', _i18n_dict)
```

- [ ] **Step 4: 검증**

Run: `cd /Users/yuncheollee/WSA2 && python3 -c "import ast; ast.parse(open('wayaudo2.py').read())" && QT_QPA_PLATFORM=offscreen WSA2_SETTINGS_PATH=/tmp/x.json WSA2_CAPTURES_PATH=/tmp/c.json python3 selfcheck.py "i18n"`
Expected: PASS (`i18n 사전 무결성` 포함)

- [ ] **Step 5: 커밋**

```bash
git add wayaudo2.py selfcheck.py
git commit -m "feat(i18n): _TR_KO 번역 사전 작성(쉬운 한국어 ~195) + 무결성 체크

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: UI 문자열 `t()` 래핑 (~195개)

**Files:**
- Modify: `wayaudo2.py` — UI 표시 문자열을 `t(...)` 로 감쌈

**Interfaces:**
- Consumes: Task1 `t()`, Task2 `_TR_KO`

- [ ] **Step 1: 래핑 대상 식별**

`/tmp/i18n_src.diff`(Task2) 의 영어(+)줄 각각이 코드 어디에 있는지 `grep -n` 으로 찾는다. 대상 호출 형태:
`.setText/.setWindowTitle/.setToolTip/.setPlaceholderText/.setTitle`, `QLabel/QPushButton/QCheckBox/QRadioButton/QGroupBox/QAction(...)`, `.addItem('...')`, `.addItems([...])`, `_brand_msg(...,title,text,...)`, `_text_input_dialog(...,title,label,...)`, `QMessageBox.*`, 메뉴 `addAction('...')`.

- [ ] **Step 2: 고정 문자열 래핑**

각 대상에서 `'English'` → `t('English')`. 예:
```python
# 전
self.setWindowTitle('Mic Calibration')
calc_btn = QPushButton('Auto Calculate Offset')
self.ref_cb.addItems(['94 dBSPL  (standard)', '114 dBSPL  (high-level)'])
# 후
self.setWindowTitle(t('Mic Calibration'))
calc_btn = QPushButton(t('Auto Calculate Offset'))
self.ref_cb.addItems([t('94 dBSPL  (standard)'), t('114 dBSPL  (high-level)')])
```

- [ ] **Step 3: f-string(동적) 래핑**

f-string 은 **템플릿을 키로** 바꾼다(플레이스홀더 유지):
```python
# 전
self.result_lbl.setText(f'Ch {ch+1} selected — measure or enter offset')
# 후
self.result_lbl.setText(t('Ch {n} selected — measure or enter offset').format(n=ch+1))
```
사전(`_TR_KO`)에 그 템플릿 키가 있어야 함(Task2 와 키 문자열 정확히 일치 — 없으면 영어 폴백되지만 KO 미적용이므로, **Task2 의 키와 Task3 의 t() 인자가 1:1 일치하는지** 반드시 grep 대조).

- [ ] **Step 4: 구문 + 회귀 + 양 언어 렌더 확인**

```bash
cd /Users/yuncheollee/WSA2
python3 -c "import ast; ast.parse(open('wayaudo2.py').read()) and print('SYNTAX OK')"
QT_QPA_PLATFORM=offscreen WSA2_SETTINGS_PATH=/tmp/x.json WSA2_CAPTURES_PATH=/tmp/c.json python3 selfcheck.py | tail -1
# 한국어 렌더(CalibDialog) — lang=ko 주입
QT_QPA_PLATFORM=offscreen WSA2_SETTINGS_PATH=/tmp/ko.json WSA2_CAPTURES_PATH=/tmp/c.json python3 -c "
import json; json.dump({'lang':'ko'}, open('/tmp/ko.json','w'))
import importlib.util,os
spec=importlib.util.spec_from_file_location('w','wayaudo2.py'); w=importlib.util.module_from_spec(spec); spec.loader.exec_module(w)
from PyQt5.QtWidgets import QApplication; app=QApplication([])
w._set_lang('ko')
d=w.CalibDialog('mic',1,{},0,lambda:-26.0,lambda c:None); d.resize(440,640); d.grab().save('/tmp/calib_ko.png'); print('ko saved')
"
```
Expected: SYNTAX OK, selfcheck 전체 PASS, `/tmp/calib_ko.png` 에 한국어 표시. **컨트롤러가 `/tmp/calib_ko.png` 를 Read 로 확인.**

- [ ] **Step 5: 커밋**

```bash
git add wayaudo2.py
git commit -m "feat(i18n): UI 표시 문자열 ~195개 t() 래핑(로그/주석/로직키 제외)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: 헤더 `한 | EN` 토글 + 자동 재시작

**Files:**
- Modify: `wayaudo2.py` — 상단 헤더(테마 토글 옆)에 언어 토글 + 핸들러

**Interfaces:**
- Consumes: `_LANG`, `_save_settings`, `self._settings`, `_brand_msg`
- Produces: `self._lang_btn`, `MainWindow._on_lang_toggle()`, `MainWindow._restart_app()`

- [ ] **Step 1: 헤더에 토글 추가**

테마 토글(`self.theme_btn`, grep `setIcon(_icon('sun'))` 또는 `'Light'`) 생성 부근에 추가:
```python
self.lang_btn = QPushButton('한' if _LANG == 'ko' else 'EN')
self.lang_btn.setFixedHeight(28); self.lang_btn.setFixedWidth(40)
self.lang_btn.setToolTip(t('Switch language (restarts)'))
self.lang_btn.setStyleSheet(ss_btn_neutral())
self.lang_btn.clicked.connect(self._on_lang_toggle)
# theme_btn 을 추가하는 레이아웃과 같은 곳에 addWidget (실제 레이아웃 변수명 grep 으로 확인)
```
`'Switch language (restarts)'` 는 `_TR_KO` 에도 추가(Task2 사전에 한 줄 더): `'Switch language (restarts)': '언어 바꾸기 (재시작)'`.

- [ ] **Step 2: 핸들러 + 재시작 구현**

`MainWindow` 에 추가:
```python
    def _on_lang_toggle(self):
        new = 'en' if _LANG == 'ko' else 'ko'
        msg = ('언어를 바꾸려면 앱을 다시 시작합니다. 계속할까요?'
               if new == 'ko' else 'Restart the app to change language. Continue?')
        if _brand_msg(self, t('Language'), msg, kind='question', cancel_text=t('Cancel')) is not True:
            return
        self._settings['lang'] = new
        _save_settings(self._settings)
        self._restart_app()

    def _restart_app(self):
        import os, sys
        try:
            os.execv(sys.executable, [sys.executable] + sys.argv)
        except Exception as e:
            _alog.error(f'restart failed: {e}')
            _brand_msg(self, t('Restart'), t('Please restart the app manually.'))
```
`'Language'`, `'Restart'`, `'Please restart the app manually.'`, `'Cancel'` 도 `_TR_KO` 에 추가:
`'Language':'언어'`, `'Restart':'재시작'`, `'Please restart the app manually.':'앱을 직접 다시 시작해 주세요.'`, `'Cancel':'취소'`.
> `_brand_msg` 의 반환 계약(True/False)·`kind`/`cancel_text` 인자는 grep `def _brand_msg` 로 확인 후 정확히 사용.

- [ ] **Step 3: 구문 + 회귀 + 격리 실행 무크래시**

```bash
cd /Users/yuncheollee/WSA2
python3 -c "import ast; ast.parse(open('wayaudo2.py').read())"
QT_QPA_PLATFORM=offscreen WSA2_SETTINGS_PATH=/tmp/x.json WSA2_CAPTURES_PATH=/tmp/c.json python3 -c "import wayaudo2; print('import OK')"
QT_QPA_PLATFORM=offscreen WSA2_SETTINGS_PATH=/tmp/x.json WSA2_CAPTURES_PATH=/tmp/c.json python3 selfcheck.py | tail -1
```
Expected: import OK, selfcheck PASS. (실제 토글→재시작 흐름은 GUI라 사용자 실측)

- [ ] **Step 4: 커밋**

```bash
git add wayaudo2.py
git commit -m "feat(i18n): 헤더 한|EN 토글 + 설정 저장 후 자동 재시작(os.execv)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: 마감 검증 (양 언어 + 잔여 미번역)

**Files:** 없음(검증). 발견 시 누락 키 보강.

- [ ] **Step 1: 잔여 미번역 영어 UI 점검 / 사전 미스 점검**

```bash
cd /Users/yuncheollee/WSA2
# t() 안 거친 채로 남은 UI 표시 문자열 의심줄(영어) — addItem/QLabel/QPushButton/setText 중 t( 없는 것
grep -nE "set(Text|WindowTitle|ToolTip|PlaceholderText|Title)\(|QLabel\(|QPushButton\(|addItem" wayaudo2.py | grep -v "t(" | grep -E "'[A-Za-z]" | head -40
# Task3 t() 인자 ↔ _TR_KO 키 대조: t('...') 인자 중 _TR_KO 에 없는 것(ko에서 영어로 폴백되는 것) 목록
QT_QPA_PLATFORM=offscreen WSA2_SETTINGS_PATH=/tmp/x.json python3 -c "
import re; src=open('wayaudo2.py').read()
import importlib.util; spec=importlib.util.spec_from_file_location('w','wayaudo2.py'); w=importlib.util.module_from_spec(spec); spec.loader.exec_module(w)
keys=set(re.findall(r\"t\('((?:[^'\\\\]|\\\\.)*)'\)\", src))
miss=[k for k in keys if k not in w._TR_KO]
print('t() 인자 중 사전 미등록(ko 폴백→영어):', len(miss)); [print('  ',m) for m in sorted(miss)[:40]]
"
```
- 위 첫 grep 에 **진짜 UI 표시 문자열**이 남아 있으면 Task3 방식으로 래핑 + Task2 사전에 추가.
- 두 번째 목록은 "한국어에서 영어로 보일" 문자열 → 의도된 영어(브랜드/단위 등)면 OK, 아니면 `_TR_KO` 에 추가.

- [ ] **Step 2: 양 언어 다이얼로그 렌더 비교(컨트롤러 Read)**

`/tmp/calib_ko.png`(한국어, Task3) 와 영어 버전을 각각 생성해 한/영 표시가 맞는지 PNG 로 확인:
```bash
QT_QPA_PLATFORM=offscreen WSA2_SETTINGS_PATH=/tmp/en.json WSA2_CAPTURES_PATH=/tmp/c.json python3 -c "
import importlib.util; spec=importlib.util.spec_from_file_location('w','wayaudo2.py'); w=importlib.util.module_from_spec(spec); spec.loader.exec_module(w)
from PyQt5.QtWidgets import QApplication; app=QApplication([]); w._set_lang('en')
d=w.CalibDialog('mic',1,{},0,lambda:-26.0,lambda c:None); d.resize(440,640); d.grab().save('/tmp/calib_en.png'); print('en saved')
"
```

- [ ] **Step 3: 사용자 실측 안내**

앱 실행 → 헤더 `한|EN` 토글 → 확인 → **자동 재시작 후 반대 언어로 뜨는지**. 컨트롤러가 세션 로그로 재시작/에러 확인.

- [ ] **Step 4: 회귀 최종**

`cd /Users/yuncheollee/WSA2 && python3 selfcheck.py | tail -1` → 전체 PASS 유지.

---

## Self-Review (작성자 체크)
- **Spec 커버리지:** ① t()/_LANG/_resolve_lang(Task1) ② _TR_KO 쉬운 한국어(Task2) ③ ~195 래핑+f-string템플릿(Task3) ④ 헤더 토글+자동재시작(Task4) ⑤ OS 로케일 기본(Task1 `_resolve_lang`) ⑥ 누락 폴백(Task1 t()) ⑦ 양언어 검증(Task3/5) — 모두 태스크 존재.
- **Placeholder 없음:** 코어/토글/재시작 코드 전부 기재. Task2/3 의 "전 항목 작성"은 데이터 생성 작업으로, 출처(ac4046c diff)·톤·구조·무결성 체크까지 명시(플레이스홀더 아님).
- **타입/이름 일관성:** `_LANG`/`t`/`_set_lang`/`_resolve_lang`/`_TR_KO`/`_on_lang_toggle`/`_restart_app`/`self.lang_btn` 전 태스크 일치. Task2 사전 키 == Task3 t() 인자(Step에서 grep 대조 명시).
- **리스크:** Task3 의 키 불일치 시 KO에서 영어 폴백(안 깨지지만 미번역) → Task5 Step1 이 정확히 그 미스를 잡는다. `_brand_msg`/`ss_btn_neutral`/헤더 레이아웃 변수명은 구현 직전 grep 으로 확정.
