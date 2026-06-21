# 설정 자동기억 + 이름 프리셋 (3-탭) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** TF/Spectrum/Stereo Loudness 세 탭의 컨트롤 값을 마지막 세션 자동 복원 + 이름 프리셋으로 저장/불러오기.

**Architecture:** 각 탭이 `get_state()->dict` / `apply_state(dict)` 한 쌍을 제공. `MainWindow`가 셋을 모아
`settings['session']`(자동기억) 와 `settings['presets'][name]`(프리셋)에 저장. 컨트롤 변경 → 0.8s 디바운스 저장.
시작 시 session 복원. 상단 헤더에 Preset 드롭다운+Save+삭제 UI.

**Tech Stack:** Python 3, PyQt5, 단일 파일 `wayaudo2.py`. 기존 `_load_settings`/`_save_settings`(`:357-367`),
`RoundComboBox`/`QPushButton`/`QDoubleSpinBox`/`_SegmentedControl` 위젯, headless 검증 `selfcheck.py`.

## Global Constraints
- **단일 파일:** 앱 로직 전부 `wayaudo2.py`. 새 파일 만들지 말 것.
- **테스트 격리 필수:** 모든 headless 실행에 `QT_QPA_PLATFORM=offscreen WSA2_SETTINGS_PATH=/tmp/x.json WSA2_CAPTURES_PATH=/tmp/c.json` — 사용자 실제 settings.json 절대 안 씀.
- **전체 MainWindow 는 offscreen 에서 segfault** → 탭/위젯 단위로만 headless 테스트. 전체 흐름은 격리 실행+사용자 실측.
- **구문 게이트:** 매 변경 후 `python3 -c "import ast; ast.parse(open('wayaudo2.py').read())"`.
- **회귀:** `python3 selfcheck.py` 항상 통과 유지(현재 13/13). 새 위젯/메서드엔 `check()` 추가.
- **apply 는 키별 try/except best-effort.** 장치 부재·옛 프리셋에도 안 깨지고 가능한 것만 적용.
- **기존 settings 키 보존:** `tf_*`,`spec_*`,`last_device`,`calibrations`,캡쳐는 안 건드림. `session`/`presets` 는 별도 네임스페이스.
- 커밋 메시지 끝에 `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.

---

## File Structure
- `wayaudo2.py` — 수정만:
  - `StereoLoudnessPage`: `loud_get_state()/loud_apply_state()` (+ 토글/콤보가 MainWindow에 있어 일부는 MainWindow가 채움)
  - `TransferFunctionWindow`: `get_state()/apply_state()` + `_select_combo_by_name()` 헬퍼
  - `MainWindow`: `spec_get_state()/spec_apply_state()`, `_collect_app_state()/_apply_app_state()`,
    `_mark_session_dirty()`+디바운스 타이머+`_restoring` 가드, 시작 복원, 헤더 Preset UI 메서드들
- `selfcheck.py` — 수정만: 탭별 roundtrip `check()` 추가.

---

## Task 1: Stereo Loudness 상태 직렬화 (가장 단순 — offscreen 인스턴스화 검증됨)

**Files:**
- Modify: `wayaudo2.py` — `StereoLoudnessPage` 클래스(~`:14485`)에 메서드 2개 추가
- Test: `selfcheck.py` — roundtrip check 추가

**Interfaces:**
- Produces:
  - `StereoLoudnessPage.loud_get_state() -> dict` — 키: `lu_mode:bool`, `hero_live:bool`
  - `StereoLoudnessPage.loud_apply_state(d: dict) -> None` — 위 키를 best-effort 적용
  - (target/L/R/device 는 MainWindow 툴바 콤보 소관 → Task 4 에서 MainWindow가 채움. 여기선 page 내부 상태만.)

- [ ] **Step 1: selfcheck 에 실패 테스트 추가**

`selfcheck.py` 끝부분(다른 `check()`들 아래)에 추가:
```python
def _loud_state_roundtrip():
    """StereoLoudnessPage loud_get_state/loud_apply_state 라운드트립."""
    pg = w.StereoLoudnessPage(); pg.resize(1280, 760)
    pg._set_hero_mode(True)            # LIVE
    pg._lu_btn.setChecked(True)        # LU 모드
    st = pg.loud_get_state()
    assert st == {'lu_mode': True, 'hero_live': True}, st
    # 기본값으로 리셋 후 복원
    pg._set_hero_mode(False); pg._lu_btn.setChecked(False)
    pg.loud_apply_state(st)
    assert pg._hero_live is True and pg._lu_mode is True, (pg._hero_live, pg._lu_mode)
    return 'loud state roundtrip OK'
check('Loudness 상태 직렬화 라운드트립', _loud_state_roundtrip)
```

- [ ] **Step 2: 실패 확인**

Run: `cd /Users/yuncheollee/WSA2 && QT_QPA_PLATFORM=offscreen WSA2_SETTINGS_PATH=/tmp/x.json WSA2_CAPTURES_PATH=/tmp/c.json python3 selfcheck.py "Loudness 상태"`
Expected: FAIL — `AttributeError: 'StereoLoudnessPage' object has no attribute 'loud_get_state'`

- [ ] **Step 3: 메서드 구현**

`StereoLoudnessPage` 안(`_set_hero_mode` 근처)에 추가:
```python
    def loud_get_state(self):
        """페이지 내부 표시 상태(LU 모드 / AVG·LIVE). device·target·L/R 은 MainWindow 소관."""
        return {'lu_mode': bool(self._lu_mode), 'hero_live': bool(self._hero_live)}

    def loud_apply_state(self, d):
        try:
            if 'lu_mode' in d: self._lu_btn.setChecked(bool(d['lu_mode']))   # _on_lu_toggled 반영
        except Exception: pass
        try:
            if 'hero_live' in d: self._set_hero_mode(bool(d['hero_live']))
        except Exception: pass
```

- [ ] **Step 4: 통과 확인**

Run: `cd /Users/yuncheollee/WSA2 && python3 -c "import ast; ast.parse(open('wayaudo2.py').read())" && QT_QPA_PLATFORM=offscreen WSA2_SETTINGS_PATH=/tmp/x.json WSA2_CAPTURES_PATH=/tmp/c.json python3 selfcheck.py "Loudness 상태"`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add wayaudo2.py selfcheck.py
git commit -m "feat(presets): StereoLoudnessPage 상태 직렬화(loud_get/apply_state)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: Transfer Function 상태 직렬화

**Files:**
- Modify: `wayaudo2.py` — `TransferFunctionWindow`(~`:10186`)에 `get_state`/`apply_state`/`_select_combo_by_name`
- Test: `selfcheck.py` — TF roundtrip check (TF 창은 offscreen 인스턴스화 시도; 실패하면 위젯 단위 폴백 주석대로)

**Interfaces:**
- Consumes: `_strip_star()`(기존, 장치명에서 ★ 제거), `TF_FFT_SIZES`,`TF_AVG_SEC`(기존 상수)
- Produces:
  - `TransferFunctionWindow.get_state() -> dict` — 키:
    `engine:int`(eng_cb idx), `fft:int`(fft_cb idx), `response:int`(avg_cb idx),
    `smooth:int`(sm_cb idx), `ir:int`(ir_cb idx), `phase:int`(phase_cb idx), `units:int`(unit_cb idx),
    `gen:str`(active 제너레이터 'pink'/'white'/'sine'/'sweep'/'file'/'none'),
    `sine_freq:float`, `sweep:[lo,hi,dur,asc]`, `level:float`(sig_lvl_sp),
    `ref_dev:str`,`ref_ch:int`,`meas_dev:str`,`meas_ch:int`,`out_dev:str`,`out_ch:int`,`out_ch2:int|null`,
    `slots:list[str]`(_tf_slot_plot), `panel:bool`(tf_panel_visible)
  - `TransferFunctionWindow.apply_state(d) -> None` — best-effort
  - `TransferFunctionWindow._select_combo_by_name(cb, name) -> bool` — 항목 텍스트(★제거)==name 찾아 setCurrentIndex, 성공시 True

- [ ] **Step 1: selfcheck 에 실패 테스트 추가**

`selfcheck.py` 에 추가(전체 TF 창이 offscreen 에서 뜨는지부터 확인하는 방어적 형태):
```python
def _tf_state_roundtrip():
    """TransferFunctionWindow get_state/apply_state 라운드트립 (콤보 인덱스 위주)."""
    try:
        tf = w.TransferFunctionWindow(None, settings={}, embedded=True)
    except Exception as e:
        return f'SKIP (TF 창 offscreen 인스턴스화 불가: {type(e).__name__})'
    tf.eng_cb.setCurrentIndex(0)      # Single
    tf.avg_cb.setCurrentIndex(4)      # Stable
    tf.sm_cb.setCurrentIndex(2)
    st = tf.get_state()
    assert st['engine'] == 0 and st['response'] == 4 and st['smooth'] == 2, st
    tf.eng_cb.setCurrentIndex(1); tf.avg_cb.setCurrentIndex(2); tf.sm_cb.setCurrentIndex(5)
    tf.apply_state(st)
    assert tf.eng_cb.currentIndex() == 0 and tf.avg_cb.currentIndex() == 4 and tf.sm_cb.currentIndex() == 2
    return 'TF state roundtrip OK'
check('TF 상태 직렬화 라운드트립', _tf_state_roundtrip)
```

- [ ] **Step 2: 실패 확인**

Run: `cd /Users/yuncheollee/WSA2 && QT_QPA_PLATFORM=offscreen WSA2_SETTINGS_PATH=/tmp/x.json WSA2_CAPTURES_PATH=/tmp/c.json python3 selfcheck.py "TF 상태"`
Expected: FAIL — `AttributeError: ... 'get_state'` (또는 SKIP 메시지면 위젯 단위로 전환, 아래 Step3 구현 후 재확인)

- [ ] **Step 3: 메서드 구현**

`TransferFunctionWindow` 안(`_engine_changed` 근처)에 추가:
```python
    def _select_combo_by_name(self, cb, name):
        """장치 콤보에서 표시텍스트(★ 제거)가 name 과 같은 항목 선택. 성공 True."""
        if not name: return False
        for i in range(cb.count()):
            if self._strip_star(cb.itemText(i)) == name:
                cb.setCurrentIndex(i); return True
        return False

    def _active_gen(self):
        for key, btn in (('pink', self.sig_pink_btn), ('white', self.sig_white_btn),
                         ('sine', self.sig_sine_btn), ('sweep', self.sig_sweep_btn),
                         ('file', self.sig_file_btn)):
            if btn.isChecked(): return key
        return 'none'

    def get_state(self):
        return {
            'engine': self.eng_cb.currentIndex(), 'fft': self.fft_cb.currentIndex(),
            'response': self.avg_cb.currentIndex(), 'smooth': self.sm_cb.currentIndex(),
            'ir': self.ir_cb.currentIndex(), 'phase': self.phase_cb.currentIndex(),
            'units': self.unit_cb.currentIndex(),
            'gen': self._active_gen(), 'sine_freq': float(self._sine_freq),
            'sweep': [float(self._sweep_f_lo), float(self._sweep_f_hi),
                      float(self._sweep_dur), bool(self._sweep_asc)],
            'level': float(self.sig_lvl_sp.value()),
            'ref_dev': self._strip_star(self.ref_cb.currentText()), 'ref_ch': self.ref_ch_cb.currentData() or 0,
            'meas_dev': self._strip_star(self.meas_cb.currentText()), 'meas_ch': self.meas_ch_cb.currentData() or 0,
            'out_dev': self._strip_star(self.sig_out_cb.currentText()), 'out_ch': self.sig_out_ch_cb.currentData() or 0,
            'out_ch2': self.sig_out_ch2_cb.currentData(),
            'slots': list(self._tf_slot_plot), 'panel': bool(self.rp.isVisible()),
        }

    def apply_state(self, d):
        def _idx(key, cb):
            try:
                if key in d: cb.setCurrentIndex(int(d[key]))
            except Exception: pass
        _idx('engine', self.eng_cb); _idx('fft', self.fft_cb); _idx('response', self.avg_cb)
        _idx('smooth', self.sm_cb); _idx('ir', self.ir_cb); _idx('phase', self.phase_cb); _idx('units', self.unit_cb)
        try:
            g = d.get('gen', 'none')
            btnmap = {'pink': self.sig_pink_btn, 'white': self.sig_white_btn, 'sine': self.sig_sine_btn,
                      'sweep': self.sig_sweep_btn, 'file': self.sig_file_btn}
            if g in btnmap: btnmap[g].setChecked(True)
        except Exception: pass
        try:
            if 'sine_freq' in d: self._sine_freq = float(d['sine_freq'])
            if 'sweep' in d and len(d['sweep']) == 4:
                self._sweep_f_lo, self._sweep_f_hi, self._sweep_dur, self._sweep_asc = (
                    float(d['sweep'][0]), float(d['sweep'][1]), float(d['sweep'][2]), bool(d['sweep'][3]))
            if 'level' in d: self.sig_lvl_sp.setValue(float(d['level']))
        except Exception: pass
        # 장치/채널 — 이름 매칭되면 적용(없으면 현재 유지). 채널은 device 변경 후 데이터로 매칭.
        for dev_key, cb, ch_key, ch_cb in (
            ('ref_dev', self.ref_cb, 'ref_ch', self.ref_ch_cb),
            ('meas_dev', self.meas_cb, 'meas_ch', self.meas_ch_cb),
            ('out_dev', self.sig_out_cb, 'out_ch', self.sig_out_ch_cb)):
            try:
                if d.get(dev_key) and self._select_combo_by_name(cb, d[dev_key]):
                    for i in range(ch_cb.count()):
                        if ch_cb.itemData(i) == d.get(ch_key):
                            ch_cb.setCurrentIndex(i); break
            except Exception: pass
        try:
            if d.get('out_ch2') is not None:
                for i in range(self.sig_out_ch2_cb.count()):
                    if self.sig_out_ch2_cb.itemData(i) == d['out_ch2']:
                        self.sig_out_ch2_cb.setCurrentIndex(i); break
        except Exception: pass
        try:
            if 'slots' in d:
                for i, name in enumerate(d['slots'][:len(self._tf_slot_plot)]):
                    self._set_tf_slot(i, name) if hasattr(self, '_set_tf_slot') else None
        except Exception: pass
        try:
            if 'panel' in d and bool(d['panel']) != self.rp.isVisible(): self._toggle_tf_panel()
        except Exception: pass
```

> 참고: `_set_tf_slot` 이름이 실제와 다르면(슬롯 설정 메서드) 구현 시 grep 으로 확인해 교체. 슬롯 적용은 없어도 핵심(분석 컨트롤) 동작에 영향 없음(try/except).

- [ ] **Step 4: 통과 확인**

Run: `cd /Users/yuncheollee/WSA2 && python3 -c "import ast; ast.parse(open('wayaudo2.py').read())" && QT_QPA_PLATFORM=offscreen WSA2_SETTINGS_PATH=/tmp/x.json WSA2_CAPTURES_PATH=/tmp/c.json python3 selfcheck.py "TF 상태"`
Expected: PASS (또는 SKIP — 그 경우 격리 실행 로그로 Task 6 에서 확인)

- [ ] **Step 5: 커밋**

```bash
git add wayaudo2.py selfcheck.py
git commit -m "feat(presets): TransferFunctionWindow 상태 직렬화(get/apply_state)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: Spectrum(MainWindow) 상태 직렬화

**Files:**
- Modify: `wayaudo2.py` — `MainWindow`(~`:14925`)에 `spec_get_state`/`spec_apply_state`
- Test: 격리 실행 검증(MainWindow 는 offscreen segfault → selfcheck 불가). 구문+로직 리뷰로 대체, Task 6 통합 검증.

**Interfaces:**
- Produces:
  - `MainWindow.spec_get_state() -> dict` — 키: `view:str`(view_mode), `scale:str`('log'/'lin'),
    `sr:int`(sr_cb idx), `avg:int`(avg_cb idx), `peak:bool`(peak_btn), `hold:int`(hold_cb idx),
    `db:int`(db_cb idx), `speed:int`(spd_cb idx), `spectro:bool`(spectro_btn),
    `dev:str`(dev_cb 표시명), `ch:int`(in_ch_cb data)
  - `MainWindow.spec_apply_state(d) -> None` — best-effort

- [ ] **Step 1: 구현 (segfault 로 headless 불가 → 직접 구현 후 격리실행 검증)**

`MainWindow` 안에 추가(`_avg_changed` 근처):
```python
    def spec_get_state(self):
        try: scale = 'log' if self._scale_seg.get_active() == 'log' else 'lin'
        except Exception: scale = 'log'
        return {
            'view': getattr(self, 'view_mode', 'oct12'),
            'scale': scale,
            'sr': self.sr_cb.currentIndex(), 'avg': self.avg_cb.currentIndex(),
            'peak': self.peak_btn.isChecked(), 'hold': self.hold_cb.currentIndex(),
            'db': self.db_cb.currentIndex(), 'speed': self.spd_cb.currentIndex(),
            'spectro': self.spectro_btn.isChecked(),
            'dev': self._strip_star(self.dev_cb.currentText()) if hasattr(self, 'dev_cb') else '',
            'ch': self.in_ch_cb.currentData() if hasattr(self, 'in_ch_cb') else 0,
        }

    def spec_apply_state(self, d):
        try:
            if 'view' in d: self._view_seg.set_active({'fft':'fft','oct3':'oct3','oct12':'oct12','oct24':'oct24'}.get(d['view'], 'oct12'))
        except Exception: pass
        try:
            if 'scale' in d: self._scale_seg.set_active('log' if d['scale']=='log' else 'lin')
        except Exception: pass
        for key, cb in (('sr', self.sr_cb), ('avg', self.avg_cb), ('hold', self.hold_cb),
                        ('db', self.db_cb), ('speed', self.spd_cb)):
            try:
                if key in d: cb.setCurrentIndex(int(d[key]))
            except Exception: pass
        try:
            if 'peak' in d and bool(d['peak']) != self.peak_btn.isChecked(): self.peak_btn.click()
        except Exception: pass
        try:
            if 'spectro' in d and bool(d['spectro']) != self.spectro_btn.isChecked(): self.spectro_btn.click()
        except Exception: pass
        try:
            if d.get('dev'):
                for i in range(self.dev_cb.count()):
                    if self._strip_star(self.dev_cb.itemText(i)) == d['dev']:
                        self.dev_cb.setCurrentIndex(i); break
                if 'ch' in d:
                    for i in range(self.in_ch_cb.count()):
                        if self.in_ch_cb.itemData(i) == d['ch']:
                            self.in_ch_cb.setCurrentIndex(i); break
        except Exception: pass
```

> 구현 시 위젯 이름(`_view_seg`,`_scale_seg`,`sr_cb`,`avg_cb`,`peak_btn`,`hold_cb`,`db_cb`,`spd_cb`,
> `spectro_btn`,`dev_cb`,`in_ch_cb`)을 grep 으로 실제와 대조. 다르면 교체.

- [ ] **Step 2: 구문 + 격리 실행 무크래시 확인**

Run: `cd /Users/yuncheollee/WSA2 && python3 -c "import ast; ast.parse(open('wayaudo2.py').read())" && QT_QPA_PLATFORM=offscreen WSA2_SETTINGS_PATH=/tmp/x.json WSA2_CAPTURES_PATH=/tmp/c.json python3 -c "import wayaudo2; print('import OK')"`
Expected: `import OK` (구문/임포트 통과; 메서드 자체는 Task 6 통합에서 호출 검증)

- [ ] **Step 3: 커밋**

```bash
git add wayaudo2.py
git commit -m "feat(presets): MainWindow Spectrum 상태 직렬화(spec_get/apply_state)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: MainWindow 통합 — collect/apply + 자동기억(디바운스) + 시작 복원

**Files:**
- Modify: `wayaudo2.py` — `MainWindow`: 통합 메서드 + 디바운스 타이머 + 시작 복원 호출
- Modify: `wayaudo2.py` — Loudness target/L/R/device 는 MainWindow 툴바 콤보(`_st_target_cb`/`_st_l_cb`/`_st_r_cb`) → loud 상태에 포함

**Interfaces:**
- Consumes: `self.tf_win.get_state/apply_state`(Task2), `self.stereo_page.loud_get/apply_state`(Task1),
  `self.spec_get_state/spec_apply_state`(Task3), `_load_settings/_save_settings`
- Produces:
  - `MainWindow._collect_app_state() -> dict` = `{'tf':..., 'spec':..., 'loud':...}`
  - `MainWindow._apply_app_state(dict) -> None`
  - `MainWindow._mark_session_dirty() -> None` (디바운스 트리거)
  - `MainWindow._save_session() -> None`
  - `self._presets_restoring: bool` 가드

- [ ] **Step 1: 통합 메서드 + 디바운스 구현**

`MainWindow.__init__` 의 self._settings 로드 이후에:
```python
        self._presets_restoring = False
        self._session_timer = QTimer(self); self._session_timer.setSingleShot(True)
        self._session_timer.timeout.connect(self._save_session)
```
`MainWindow` 에 메서드 추가:
```python
    def _loud_get_full(self):
        st = self.stereo_page.loud_get_state()
        try: st['target'] = self._st_target_cb.currentIndex()
        except Exception: pass
        try: st['l'] = self._st_l_cb.currentIndex(); st['r'] = self._st_r_cb.currentIndex()
        except Exception: pass
        return st

    def _loud_apply_full(self, d):
        for key, cb in (('target', getattr(self, '_st_target_cb', None)),
                        ('l', getattr(self, '_st_l_cb', None)), ('r', getattr(self, '_st_r_cb', None))):
            try:
                if cb is not None and key in d: cb.setCurrentIndex(int(d[key]))
            except Exception: pass
        self.stereo_page.loud_apply_state(d)

    def _collect_app_state(self):
        return {'tf': self.tf_win.get_state(), 'spec': self.spec_get_state(), 'loud': self._loud_get_full()}

    def _apply_app_state(self, st):
        self._presets_restoring = True
        try:
            for key, fn in (('tf', lambda d: self.tf_win.apply_state(d)),
                            ('spec', self.spec_apply_state), ('loud', self._loud_apply_full)):
                try:
                    if isinstance(st.get(key), dict): fn(st[key])
                except Exception as e: _alog.warning(f'apply_app_state {key} 실패: {e}')
        finally:
            self._presets_restoring = False

    def _mark_session_dirty(self, *a):
        if self._presets_restoring: return
        self._session_timer.start(800)   # 0.8s 디바운스

    def _save_session(self):
        try:
            self._settings['session'] = self._collect_app_state()
            _save_settings(self._settings)
            _diag('session_saved')
        except Exception as e:
            _alog.warning(f'_save_session 실패: {e}')
```

- [ ] **Step 2: 컨트롤 시그널 → `_mark_session_dirty` 배선**

`MainWindow.__init__` 끝(탭/툴바 빌드 완료 후)에서 preset 관련 시그널을 추가 연결(기존 핸들러 유지):
```python
        for _cb in (self.sr_cb, self.avg_cb, self.hold_cb, self.db_cb, self.spd_cb,
                    self._st_target_cb, self._st_l_cb, self._st_r_cb):
            try: _cb.currentIndexChanged.connect(self._mark_session_dirty)
            except Exception: pass
        for _b in (self.peak_btn, self.spectro_btn):
            try: _b.toggled.connect(self._mark_session_dirty)
            except Exception: pass
        try: self._view_seg.changed.connect(lambda *_: self._mark_session_dirty())
        except Exception: pass
        try: self._scale_seg.changed.connect(lambda *_: self._mark_session_dirty())
        except Exception: pass
        for _cb in (self.tf_win.eng_cb, self.tf_win.fft_cb, self.tf_win.avg_cb, self.tf_win.sm_cb,
                    self.tf_win.ir_cb, self.tf_win.phase_cb, self.tf_win.unit_cb):
            try: _cb.currentIndexChanged.connect(self._mark_session_dirty)
            except Exception: pass
        try: self.stereo_page._lu_btn.toggled.connect(self._mark_session_dirty)
        except Exception: pass
```

- [ ] **Step 3: 시작 시 session 복원**

`MainWindow.__init__` 의 위 배선 직후(모든 위젯 존재 시점)에:
```python
        _sess = self._settings.get('session')
        if isinstance(_sess, dict):
            QTimer.singleShot(0, lambda: self._apply_app_state(_sess))
```

- [ ] **Step 4: 구문 + 격리 실행 무크래시 + session 기록 확인**

Run:
```bash
cd /Users/yuncheollee/WSA2 && python3 -c "import ast; ast.parse(open('wayaudo2.py').read()) and print('SYNTAX OK')"
python3 selfcheck.py | tail -1
```
Expected: 구문 OK, selfcheck 통과(Task1/2 check 포함).

- [ ] **Step 5: 커밋**

```bash
git add wayaudo2.py
git commit -m "feat(presets): 앱 상태 collect/apply + 세션 자동기억(디바운스)+시작 복원

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: 상단 헤더 Preset UI (드롭다운 + Save + 삭제)

**Files:**
- Modify: `wayaudo2.py` — 상단 헤더 빌드부(SPECTRA 로고/Standby/Light/Calibration 줄)에 Preset 컨트롤 추가 + 핸들러

**Interfaces:**
- Consumes: `_collect_app_state`/`_apply_app_state`(Task4), `_save_settings`, `RoundComboBox`, 기존 다크 입력 다이얼로그 패턴
- Produces:
  - `self._preset_cb: RoundComboBox` (목록; idx0 = '— Preset —')
  - `MainWindow._refresh_preset_cb()`, `_on_preset_selected(idx)`, `_on_preset_save()`, `_on_preset_delete()`

- [ ] **Step 1: 헤더에 위젯 추가**

헤더 레이아웃(Calibration 버튼 추가하는 곳, grep `'Calibration'`)에서 Calibration **앞**에 삽입:
```python
        self._preset_cb = RoundComboBox(); self._preset_cb._align_center = True
        self._preset_cb.setFixedHeight(30); self._preset_cb.setMinimumWidth(120)
        self._preset_cb.setToolTip('프리셋 불러오기 (현재 세 탭 설정 통째 적용)')
        self._preset_cb.currentIndexChanged.connect(self._on_preset_selected)
        _psave = QPushButton('Save'); _psave.setFixedHeight(30); _psave.clicked.connect(self._on_preset_save)
        _pdel = QPushButton('🗑'); _pdel.setFixedHeight(30); _pdel.setFixedWidth(34); _pdel.clicked.connect(self._on_preset_delete)
        # header_layout 에 addWidget (실제 레이아웃 변수명은 grep 으로 확인)
        header_layout.addWidget(self._preset_cb); header_layout.addWidget(_psave); header_layout.addWidget(_pdel)
        self._refresh_preset_cb()
```

- [ ] **Step 2: 핸들러 구현**

```python
    def _refresh_preset_cb(self):
        self._preset_cb.blockSignals(True)
        self._preset_cb.clear(); self._preset_cb.addItem('— Preset —')
        for name in sorted(self._settings.get('presets', {}).keys()):
            self._preset_cb.addItem(name)
        self._preset_cb.setCurrentIndex(0)
        self._preset_cb.blockSignals(False)

    def _on_preset_selected(self, idx):
        if idx <= 0: return
        name = self._preset_cb.currentText()
        st = self._settings.get('presets', {}).get(name)
        if isinstance(st, dict):
            self._apply_app_state(st); _diag('preset_load', name=name)

    def _on_preset_save(self):
        from PyQt5.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, '프리셋 저장', '이름:')
        name = (name or '').strip()
        if not ok or not name: return
        presets = self._settings.setdefault('presets', {})
        if name in presets:
            if _BrandBox.question(self, '덮어쓰기', f'"{name}" 프리셋을 덮어쓸까요?') != True: return
        presets[name] = self._collect_app_state()
        _save_settings(self._settings); self._refresh_preset_cb()
        idx = self._preset_cb.findText(name)
        if idx > 0: self._preset_cb.blockSignals(True); self._preset_cb.setCurrentIndex(idx); self._preset_cb.blockSignals(False)
        _diag('preset_save', name=name)

    def _on_preset_delete(self):
        name = self._preset_cb.currentText()
        presets = self._settings.get('presets', {})
        if self._preset_cb.currentIndex() <= 0 or name not in presets: return
        if _BrandBox.question(self, '삭제', f'"{name}" 프리셋을 삭제할까요?') != True: return
        presets.pop(name, None); _save_settings(self._settings); self._refresh_preset_cb()
```

> `_BrandBox.question` 시그니처는 기존 사용처(grep `_BrandBox.question` 또는 `.warning`)로 반환값 형태 확인 후 맞춤(True/QMessageBox.Yes 등). 없으면 `QMessageBox.question` 사용.

- [ ] **Step 3: 구문 + 격리 실행 무크래시 확인**

Run: `cd /Users/yuncheollee/WSA2 && python3 -c "import ast; ast.parse(open('wayaudo2.py').read())" && python3 selfcheck.py | tail -1`
Expected: 구문 OK, selfcheck 통과.

- [ ] **Step 4: 커밋**

```bash
git add wayaudo2.py
git commit -m "feat(presets): 상단 헤더 Preset UI(드롭다운+Save+삭제)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: 통합 검증 (격리 실행 + 사용자 실측)

**Files:** 없음(검증만). 필요 시 위 태스크 버그 수정.

- [ ] **Step 1: 격리 실행 — session/presets 기록 확인**

앱을 격리 settings 로 띄우고(사용자가 컨트롤 몇 개 바꾼 뒤) `/tmp/x.json` 에 키가 쓰였는지 확인:
```bash
cd /Users/yuncheollee/WSA2
QT_QPA_PLATFORM=offscreen WSA2_SETTINGS_PATH=/tmp/x.json WSA2_CAPTURES_PATH=/tmp/c.json python3 -c "
import wayaudo2 as W, json
# headless 로 MainWindow 전체는 segfault 가능 → 통합 동작은 사용자 실측. 여기선 직렬화 키 형태만 점검.
print('settings infra OK')
"
```
> 전체 MainWindow GUI 흐름(시그널→디바운스→저장, 복원, 프리셋 적용)은 offscreen segfault 로 자동화 불가 →
> **사용자 실측 + 세션 로그**로 검증(아래 Step 2,3).

- [ ] **Step 2: 사용자 실측 — 자동기억**

앱 실행 → TF Response=Stable, Spectrum view=FFT, Loudness LIVE 등 바꾼 뒤 → 앱 종료 → 재실행.
**Claude 가 확인:** 최신 세션 로그에서 `[DIAG] session_saved` 가 변경 ~0.8s 후 찍히고,
재실행 후 컨트롤이 복원됐는지 사용자 확인 + 로그.

- [ ] **Step 3: 사용자 실측 — 프리셋**

값 세팅 → Save "테스트A" → 값 바꿈 → 드롭다운에서 "테스트A" 선택 → 원복되는지.
삭제 동작. **Claude 확인:** 로그 `[DIAG] preset_save/preset_load`, `/Users/.../settings.json` 의 `presets` 키.

- [ ] **Step 4: 회귀 + 최종 커밋(있으면)**

```bash
cd /Users/yuncheollee/WSA2 && python3 selfcheck.py | tail -1   # 13/13(+추가) 유지
```

---

## Self-Review (작성자 체크)
- **Spec 커버리지:** ① 탭별 직렬화(Task1-3) ② collect/apply(Task4) ③ 자동기억 디바운스+복원(Task4)
  ④ 프리셋 UI/저장/불러오기/삭제(Task5) ⑤ best-effort try/except(전 태스크) ⑥ 장치 포함 best-effort(Task2-4)
  ⑦ 캡쳐 미포함(스냅샷에 키 없음) — 모두 태스크 존재.
- **Placeholder:** 없음(코드 전부 기재). 단 위젯/메서드 실제 이름 대조 주석은 구현 시 grep 으로 확정(코드베이스 특성).
- **타입 일관성:** get_state 키 ↔ apply_state 키 일치(engine/fft/response/smooth/ir/phase/units/gen/.../slots/panel,
  spec view/scale/sr/avg/peak/hold/db/speed/spectro/dev/ch, loud lu_mode/hero_live/target/l/r) 확인.
- **알려진 리스크:** MainWindow offscreen segfault → 통합 자동테스트 불가, 사용자 실측 의존(Task6에 명시).
  위젯/메서드 이름(`_view_seg`,`_st_target_cb`,`_set_tf_slot`,`_BrandBox.question` 등)은 구현 직전 grep 으로 확정.
