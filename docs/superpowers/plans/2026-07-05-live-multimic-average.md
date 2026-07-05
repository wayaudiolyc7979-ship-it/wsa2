# 라이브 멀티마이크 실시간 평균 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** TF 탭에서 라이브로 돌아가는 여러 측정 카드(마이크)를 실시간으로 평균낸 한 개의 AVG 곡선을 그린다.

**Architecture:** 각 카드가 매 프레임 계산하는 복소 H(f)를 모아, 모듈 함수 `_multimic_average()`가 크기(파워RMS) 또는 복소(벡터) 평균을 산출 → 3개 TF 캔버스의 신규 `_tf_avg` 슬롯에 굵은 오버레이로 그린다. 수집 훅은 `_render_extra_pairs` 직후에서 호출되어 Single·MTW 엔진 양쪽을 커버한다.

**Tech Stack:** Python 3.9, PyQt5, numpy. 단일 파일 `wayaudo2.py`. 검증 = headless assert + offscreen 위젯 렌더→PNG→`Read` + `python3 selfcheck.py`.

## Global Constraints

- **테스트가 실사용자 파일 쓰기 금지**: 모든 headless 실행은 `QT_QPA_PLATFORM=offscreen WSA2_SETTINGS_PATH=/tmp/x.json WSA2_CAPTURES_PATH=/tmp/c.json` 로 격리. (설정/캘리브 소실 사고 재발 방지)
- **전체 MainWindow는 offscreen에서 segfault** — 개별 QWidget(캔버스/카드/패널)만 offscreen 인스턴스화·`.grab()`. 전체 창 필요한 검증은 사용자 실행 + 세션 로그 `[DIAG]` 직접 확인.
- **Python 인터프리터**: `/usr/bin/python3` (시스템 3.9.6에 PyQt5/numpy/scipy/sounddevice/soundfile 있음. Homebrew python3엔 numpy 없음).
- **캡쳐 곡선은 실선** — 점선 금지. AVG 곡선도 실선.
- **스타일은 디자인 토큰**(`T()`, `FS_*`, `_n2_group_header`, LED 토글) — 인라인 스타일 금지. 라이트/다크 양쪽 restyle 필수.
- **제품명 SPECTRA** — 사용자 노출 문자열엔 WSA/WSA2 금지.
- **커밋 트레일러**: 모든 커밋 끝에
  `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>` +
  `Claude-Session: https://claude.ai/code/session_017ApFryWrJA64wo2cfBRLcv`
- **버전/빌드 금지**: `_APP_VERSION` bump·태그·빌드 하지 않음. 사용자가 "빌드하자" 할 때까지 develop에 누적.
- 구문 게이트: `python3 -c "import ast; ast.parse(open('wayaudo2.py').read())"`.

---

### Task 1: 평균 수학 코어 함수 `_multimic_average()`

참여 카드들의 복소 H(f) 리스트를 받아 크기/복소 평균을 산출하는 순수 함수. 나머지 태스크가 의존하는 핵심 유닛.

**Files:**
- Modify: `wayaudo2.py` — `_tf_smooth`(`:8628`) 정의 바로 아래에 새 함수 추가. `_hilbert_env`(`:10775`)는 IR용이나 여기선 irfft만 쓰므로 불필요.
- Test: `/private/tmp/claude-501/-Users-yuncheollee-WSA2/fe9463a8-d47e-4f18-9942-07da6411c77f/scratchpad/test_mmavg.py` (스크래치패드)

**Interfaces:**
- Consumes: `_tf_smooth(freqs, H_complex, bpo) -> (f, mag, ph_wrap, ph_unwr, grp_ms)` (기존, `:8628`).
- Produces: `_multimic_average(H_list, gamma_list, delay_list, freqs, sr, bpo, mode='mag', align=True) -> dict | None`
  반환 dict 키: `mode`, `n`, `f`, `mag`, `coh`, `ph_wrap`, `ph_unwr`, `grp`, `h_ir`.
  크기 모드는 `ph_wrap/ph_unwr/grp/h_ir = None`. 유효 카드 < 2 → `None`.

- [ ] **Step 1: 실패하는 테스트 작성**

`test_mmavg.py`:
```python
import os, sys
sys.path.insert(0, '/Users/yuncheollee/WSA2'); os.chdir('/Users/yuncheollee/WSA2')
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['WSA2_SETTINGS_PATH'] = '/tmp/x.json'; os.environ['WSA2_CAPTURES_PATH'] = '/tmp/c.json'
import numpy as np, wayaudo2 as w

sr = 48000; fft = 8192
freqs = np.fft.rfftfreq(fft, 1.0 / sr).astype(np.float32)
bpo = 24

# 3개 카드: 평탄한 크기 |H|=1.0, 2.0, 4.0 (위상 0)
Hs = [np.full(len(freqs), a, dtype=complex) for a in (1.0, 2.0, 4.0)]
gammas = [np.ones(len(freqs), dtype=np.float32) for _ in range(3)]
delays = [0.0, 0.0, 0.0]

# 크기(파워 RMS) 모드: P=mean(1,4,16)=7 → mag_dB=10log10(7)=8.451dB
r = w._multimic_average(Hs, gammas, delays, freqs, sr, bpo, mode='mag', align=False)
assert r is not None and r['mode'] == 'mag'
mid = len(r['f']) // 2
assert abs(r['mag'][mid] - 10 * np.log10(7.0)) < 0.5, r['mag'][mid]
assert r['ph_wrap'] is None and r['h_ir'] is None

# 복소(벡터) 모드, 정렬 무관(위상 0): H_avg=mean(1,2,4)=2.333 → 20log10=7.36dB
r2 = w._multimic_average(Hs, gammas, delays, freqs, sr, bpo, mode='complex', align=False)
assert r2['mode'] == 'complex' and r2['h_ir'] is not None
assert abs(r2['mag'][len(r2['f'])//2] - 20 * np.log10(7.0/3.0)) < 0.5, r2['mag'][len(r2['f'])//2]

# 딜레이 정렬: 같은 |H|=1이지만 서로 다른 선형위상(딜레이) → 정렬 OFF면 콤필터로 |avg|<1,
# 정렬 ON이면 위상 상쇄되어 |avg|≈1 (7.36dB보다 큼)
Hd = []
for d in (0.0, 0.5, 1.0):  # ms
    Hd.append(np.exp(-1j * 2 * np.pi * freqs * (d / 1000.0)).astype(complex))
gd = [np.ones(len(freqs), dtype=np.float32) for _ in range(3)]
off = w._multimic_average(Hd, gd, [0.0, 0.5, 1.0], freqs, sr, bpo, mode='complex', align=False)
on  = w._multimic_average(Hd, gd, [0.0, 0.5, 1.0], freqs, sr, bpo, mode='complex', align=True)
# 2kHz 부근에서 정렬 ON이 OFF보다 크기 큼(콤필터 제거)
k = int(np.argmin(np.abs(off['f'] - 2000)))
assert on['mag'][k] > off['mag'][k] + 1.0, (on['mag'][k], off['mag'][k])

# 유효 카드 < 2 → None
assert w._multimic_average([Hs[0]], [gammas[0]], [0.0], freqs, sr, bpo) is None
print('PASS test_mmavg')
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

Run: `cd /Users/yuncheollee/WSA2 && /usr/bin/python3 <scratchpad>/test_mmavg.py`
Expected: FAIL — `AttributeError: module 'wayaudo2' has no attribute '_multimic_average'`

- [ ] **Step 3: 최소 구현 작성**

`wayaudo2.py`, `_tf_smooth` 함수 끝 바로 아래에 삽입:
```python
def _multimic_average(H_list, gamma_list, delay_list, freqs, sr, bpo,
                      mode='mag', align=True):
    """참여 카드들의 복소 H(f)를 라이브 평균. 유효 카드<2면 None.

    mode='mag'     : 파워 RMS 평균 → |H_avg|²=mean|H_i|². 위상/IR 없음(공간평균 표준).
    mode='complex' : (align이면 카드 딜레이 delay_ms로 위상보정 후) 벡터 평균.
                     위상·IR 포함(반복측정/정렬 시나리오).
    coherence는 카드별 γ² 산술평균(커서 리드아웃 %용).
    """
    Hs = [np.asarray(h, dtype=complex) for h in H_list if h is not None]
    gs = [np.asarray(g, dtype=float) for g in gamma_list if g is not None]
    if len(Hs) < 2:
        return None
    n = len(Hs)
    if len(gs) == n:
        coh_avg = np.mean(np.stack(gs), axis=0)
    else:
        coh_avg = np.ones(len(freqs), dtype=float)
    if mode == 'mag':
        P_avg = np.mean(np.stack([np.abs(h) ** 2 for h in Hs]), axis=0)
        H_mag = np.sqrt(np.maximum(P_avg, 1e-30)).astype(complex)   # 위상 0
        f_a, mag_a, _pw, _pu, _grp = _tf_smooth(freqs, H_mag, bpo)
        coh_a = np.interp(f_a, freqs, coh_avg).astype(np.float32)
        return {'mode': 'mag', 'n': n, 'f': f_a, 'mag': mag_a, 'coh': coh_a,
                'ph_wrap': None, 'ph_unwr': None, 'grp': None, 'h_ir': None}
    # complex (vector) 평균
    acc = np.zeros(len(freqs), dtype=complex)
    for h, d in zip(Hs, delay_list):
        if align and d:
            h = h * np.exp(1j * 2 * np.pi * freqs * (float(d) / 1000.0))
        acc = acc + h
    H_avg = acc / n
    f_a, mag_a, pw_a, pu_a, grp_a = _tf_smooth(freqs, H_avg, bpo)
    coh_a = np.interp(f_a, freqs, coh_avg).astype(np.float32)
    fft_size = (len(freqs) - 1) * 2
    h_ir = np.fft.fftshift(np.fft.irfft(H_avg, n=fft_size)).astype(np.float32)
    return {'mode': 'complex', 'n': n, 'f': f_a, 'mag': mag_a, 'coh': coh_a,
            'ph_wrap': pw_a, 'ph_unwr': pu_a, 'grp': grp_a, 'h_ir': h_ir}
```

- [ ] **Step 4: 테스트 실행 → 통과 확인**

Run: `cd /Users/yuncheollee/WSA2 && /usr/bin/python3 <scratchpad>/test_mmavg.py`
Expected: `PASS test_mmavg`
또한 구문 게이트: `/usr/bin/python3 -c "import ast; ast.parse(open('wayaudo2.py').read())"` → 무출력.

- [ ] **Step 5: 커밋**

```bash
cd /Users/yuncheollee/WSA2
git add wayaudo2.py
git commit -m "feat(tf): 라이브 멀티마이크 평균 코어 함수 _multimic_average

크기(파워RMS)/복소(벡터,딜레이정렬) 평균. 유효카드<2→None. 헤드리스 단위검증.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_017ApFryWrJA64wo2cfBRLcv"
```

---

### Task 2: 캔버스 AVG 슬롯 API (3개 캔버스)

`TFMagCanvas`/`TFPhaseCanvas`/`TFIRCanvas`에 `_tf_avg` 슬롯 + `set_tf_average`/`clear_tf_average` + 굵은 오버레이 페인트 추가. 기존 `_tf_extra`와 독립.

**Files:**
- Modify: `wayaudo2.py`
  - `TFMagCanvas` (`:9727`) — `__init__`의 `self._tf_extra = {}`(`:9754`) 옆에 `self._tf_avg = None`; `set_tf_extra`(`:9797`) 옆에 신규 메서드; extra 페인트 루프(`:10184-10201`) 끝난 직후 AVG 드로우.
  - `TFPhaseCanvas` (`:9132`) — `set_tf_extra_phase`(`:9183`) 옆에 신규 메서드 + `_tf_avg` 슬롯 + 페인트.
  - `TFIRCanvas` (`:10808`) — `_tf_extra`(`:10834`) 옆 슬롯 + `set_tf_average`(`:11014` 인접) + 페인트(`:11298` 루프 뒤).
- Test: `<scratchpad>/grab_avg_canvas.py`

**Interfaces:**
- Consumes: Task 1 dict(`f`, `mag`, `coh`, `ph_wrap`, `ph_unwr`, `grp`, `h_ir`).
- Produces:
  - `TFMagCanvas.set_tf_average(color, f, mag, coh=None)` / `.clear_tf_average()`
  - `TFPhaseCanvas.set_tf_average(color, f, ph_wrap, ph_unwr, grp)` / `.clear_tf_average()`
  - `TFIRCanvas.set_tf_average(color, t_ms, h)` / `.clear_tf_average()`
  - AVG 전용 색은 호출측(Task 5)이 테마 대응으로 전달.

- [ ] **Step 1: 실패하는 렌더 테스트 작성**

`grab_avg_canvas.py`:
```python
import os, sys
sys.path.insert(0, '/Users/yuncheollee/WSA2'); os.chdir('/Users/yuncheollee/WSA2')
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['WSA2_SETTINGS_PATH'] = '/tmp/x.json'; os.environ['WSA2_CAPTURES_PATH'] = '/tmp/c.json'
import numpy as np, wayaudo2 as w
from PyQt5.QtWidgets import QApplication
app = QApplication.instance() or QApplication([])
sr = 48000; fft = 8192
freqs = np.fft.rfftfreq(fft, 1.0/sr).astype(np.float32)
f = freqs; mag = 5*np.sin(np.log(np.maximum(f,1))/1.5).astype(np.float32)

mc = w.TFMagCanvas(); mc.resize(600, 300)
mc.set_tf_average('#FFFFFF', f, mag, coh=np.ones(len(f), np.float32))
mc.grab().save('/tmp/avg_mag.png')

pc = w.TFPhaseCanvas(); pc.resize(600, 300)
pc.set_tf_average('#FFFFFF', f, mag*10, mag*10, np.zeros(len(f), np.float32))
pc.grab().save('/tmp/avg_phase.png')

t_ms = (np.arange(fft) - fft//2)/sr*1000.0
h = np.zeros(fft, np.float32); h[fft//2] = 1.0
ic = w.TFIRCanvas(); ic.resize(600, 300)
ic.set_tf_average('#FFFFFF', t_ms.astype(np.float32), h)
ic.grab().save('/tmp/avg_ir.png')
print('saved avg_mag/avg_phase/avg_ir')
```

- [ ] **Step 2: 실행 → 실패 확인**

Run: `cd /Users/yuncheollee/WSA2 && /usr/bin/python3 <scratchpad>/grab_avg_canvas.py`
Expected: FAIL — `AttributeError: 'TFMagCanvas' object has no attribute 'set_tf_average'`

- [ ] **Step 3: 구현 — TFMagCanvas**

`__init__` (`:9754` `self._tf_extra = {}` 다음 줄):
```python
        self._tf_avg = None   # {'color','f','mag','coh'} — 라이브 멀티마이크 평균 오버레이
```
`set_tf_extra` 아래(`:9803` 인근):
```python
    def set_tf_average(self, color, f, mag, coh=None):
        self._tf_avg = {'color': color, 'f': f, 'mag': mag, 'coh': coh}; self.update()

    def clear_tf_average(self):
        if self._tf_avg is not None:
            self._tf_avg = None; self.update()
```
extra 페인트 루프 종료 직후(`:10201` `p.drawPath(_catmull_seg(...))` 다음, front 재드로우 이전)에 삽입:
```python
        # 멀티마이크 평균(AVG) — 개별 위 굵은 실선 오버레이
        if self._tf_avg is not None:
            a = self._tf_avg
            af = a.get('f'); am = a.get('mag')
            if af is not None and am is not None and len(af) >= 2:
                if refmode:
                    am = am - np.interp(af, self._ref_f, self._ref_mag)
                a_xs = self._fx(af, pl, uw).astype(float)
                a_ys = (pt + np.clip((self.db_max - am) / rng * dh, 0, dh)).astype(float)
                a_ys = _vis_smooth(a_ys, 7)
                if len(a_xs) > _ex_max_pts:
                    _ai = np.linspace(0, len(a_xs) - 1, _ex_max_pts, dtype=int)
                    a_xs = a_xs[_ai]; a_ys = a_ys[_ai]
                p.setRenderHint(QPainter.Antialiasing, True)
                p.setPen(QPen(QColor(a['color']), 2.8)); p.setBrush(Qt.NoBrush)
                p.drawPath(_catmull_seg(a_xs, a_ys))
```

- [ ] **Step 4: 구현 — TFPhaseCanvas**

`set_tf_extra_phase`(`:9183`) 아래에 슬롯+메서드. `__init__`에 `self._tf_avg = None` 추가(클래스 `__init__` 내 `_tf_extra` 초기화 옆; 없으면 `set_tf_extra_phase`가 쓰는 dict 초기화 지점 옆). 메서드:
```python
    def set_tf_average(self, color, f, ph_wrap, ph_unwr, grp):
        self._tf_avg = {'color': color, 'f': f, 'ph_wrap': ph_wrap,
                        'ph_unwr': ph_unwr, 'grp': grp}; self.update()

    def clear_tf_average(self):
        if getattr(self, '_tf_avg', None) is not None:
            self._tf_avg = None; self.update()
```
위상 extra 페인트 루프(파일에서 `self._tf_extra` 순회하며 위상 곡선 그리는 지점, `paintEvent` 내) 종료 직후, extra와 같은 좌표변환을 써서 `QPen(QColor(color), 2.8)`로 `ph_wrap`(또는 현재 위상 표시모드에 맞는 배열) 곡선 1개 오버레이. (extra 위상 드로우 코드를 그대로 복제하되 색=AVG색, 두께 2.8.)

- [ ] **Step 5: 구현 — TFIRCanvas**

`set_tf_extra`(`:11014`) 아래:
```python
    def set_tf_average(self, color, t, h):
        etc_db = 20 * np.log10(np.maximum(np.abs(h), 1e-10)) if h is not None else None
        self._tf_avg = {'color': color, 't': t, 'h': h, 'etc_db': etc_db}; self.update()

    def clear_tf_average(self):
        if getattr(self, '_tf_avg', None) is not None:
            self._tf_avg = None; self.update()
```
`__init__`의 `self._tf_extra = {}`(`:10834`) 옆에 `self._tf_avg = None`. IR extra 페인트 루프(`:11349` `for _key, _ex in self._tf_extra.items()`) 종료 직후, 같은 좌표변환으로 `self._tf_avg`의 `t/h`를 `QPen(QColor(color), 2.2)` 실선 1개 오버레이(extra IR 드로우 로직 복제).

- [ ] **Step 6: 실행 → 통과 + PNG 확인**

Run: `cd /Users/yuncheollee/WSA2 && /usr/bin/python3 <scratchpad>/grab_avg_canvas.py`
Expected: `saved avg_mag/avg_phase/avg_ir`
그 다음 `Read` `/tmp/avg_mag.png` `/tmp/avg_phase.png` `/tmp/avg_ir.png` — 각 캔버스에 굵은 흰색 곡선이 보이는지 눈으로 확인.
구문 게이트 + `python3 selfcheck.py` 회귀 통과.

- [ ] **Step 7: 커밋**

```bash
git add wayaudo2.py
git commit -m "feat(tf): 3개 TF 캔버스에 AVG 오버레이 슬롯(set_tf_average/clear)

_tf_avg 슬롯 + 굵은 실선 오버레이(mag2.8/phase2.8/ir2.2). 기존 _tf_extra와 독립.
offscreen 렌더 PNG 검증.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_017ApFryWrJA64wo2cfBRLcv"
```

---

### Task 3: 상태 필드 + AVERAGE 컨트롤 그룹 UI

TF 우측 패널에 N2 스타일 "AVERAGE" 그룹(마스터 토글·모드 세그먼트·평균만·딜레이정렬) + 상태 필드.

**Files:**
- Modify: `wayaudo2.py`
  - `TransferFunctionWindow.__init__` (`:12699` 인근, `_extra_pairs` 초기화 옆) — 상태 필드 추가.
  - `_build_ui` 우측 패널에서 SIGNAL GENERATOR 그룹(`:12749` `sg=QGroupBox()` + `_n2_group_header('SIGNAL GENERATOR')`) 구성 직후에 AVERAGE 그룹 추가.
  - `_n2_group_header`(정의 위치) · LED 토글 헬퍼 재사용.
- Test: `<scratchpad>/grab_avg_panel.py`

**Interfaces:**
- Consumes: `_n2_group_header(text)`, 기존 N2 토글/세그먼트 헬퍼.
- Produces: 상태 필드 `self._avg_on`(bool)·`self._avg_mode`('mag'|'complex')·`self._avg_only`(bool)·`self._avg_align`(bool). 위젯 참조 `self._avg_master_btn`·`self._avg_mode_seg`·`self._avg_only_btn`·`self._avg_align_btn`. 토글 시 상태만 갱신하고 `self.mag_cvs.update()` 등 재렌더 유발(실제 곡선은 Task 5 훅이 그림).

- [ ] **Step 1: 상태 필드 추가 (`__init__`)**

`_extra_pairs = []` 초기화 근처(`:12699`)에:
```python
        # 라이브 멀티마이크 평균 상태
        self._avg_on = False
        self._avg_mode = 'mag'      # 'mag'(파워RMS) | 'complex'(벡터)
        self._avg_only = False      # True면 개별 곡선 숨기고 AVG만
        self._avg_align = True      # 복소 모드 딜레이 자동정렬
```

- [ ] **Step 2: 실패하는 패널 렌더 테스트**

`grab_avg_panel.py`:
```python
import os, sys
sys.path.insert(0, '/Users/yuncheollee/WSA2'); os.chdir('/Users/yuncheollee/WSA2')
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['WSA2_SETTINGS_PATH'] = '/tmp/x.json'; os.environ['WSA2_CAPTURES_PATH'] = '/tmp/c.json'
import wayaudo2 as w
from PyQt5.QtWidgets import QApplication
app = QApplication.instance() or QApplication([])
tw = w.TransferFunctionWindow(embedded=True)
assert hasattr(tw, '_avg_master_btn'), 'AVERAGE 그룹 미생성'
grp = tw._avg_master_btn.parentWidget()
grp.grab().save('/tmp/avg_panel.png')
print('saved avg_panel; avg_on=', tw._avg_on)
```
Run → FAIL: `AssertionError: AVERAGE 그룹 미생성`.
(주의: `TransferFunctionWindow(embedded=True)`는 offscreen에서 인스턴스화 가능 — 전체 MainWindow가 아님. 실패 시 이 태스크는 위젯 단독 grab 대신 그룹 빌더 메서드 `_build_average_group()`를 만들어 그 반환 위젯만 grab.)

- [ ] **Step 3: AVERAGE 그룹 빌드**

SIGNAL GENERATOR 그룹을 우측 패널에 add한 직후 위치에 삽입:
```python
        avg_box = QGroupBox(); avg_box.setStyleSheet('QGroupBox{border:none;margin:0;padding:0;}')
        avg_l = QVBoxLayout(avg_box); avg_l.setContentsMargins(0, 8, 0, 0); avg_l.setSpacing(6)
        avg_l.addWidget(_n2_group_header('AVERAGE'))
        # 1행: 마스터 AVG 토글 + 모드 세그먼트
        row1 = QHBoxLayout(); row1.setSpacing(8)
        self._avg_master_btn = _make_n2_toggle('AVG')   # 기존 LED 토글 헬퍼 패턴 사용
        self._avg_master_btn.setChecked(False)
        self._avg_master_btn.toggled.connect(self._on_avg_master)
        self._avg_mode_seg = _make_n2_segment(['크기', '복소'])  # 기존 세그먼트 헬퍼
        self._avg_mode_seg.setCurrentIndex(0)
        self._avg_mode_seg.currentChanged.connect(self._on_avg_mode)
        row1.addWidget(self._avg_master_btn); row1.addWidget(self._avg_mode_seg, 1)
        avg_l.addLayout(row1)
        # 2행: 평균만 + 딜레이정렬
        row2 = QHBoxLayout(); row2.setSpacing(8)
        self._avg_only_btn = _make_n2_toggle('평균만')
        self._avg_only_btn.toggled.connect(self._on_avg_only)
        self._avg_align_btn = _make_n2_toggle('딜레이정렬')
        self._avg_align_btn.setChecked(True)
        self._avg_align_btn.toggled.connect(self._on_avg_align)
        row2.addWidget(self._avg_only_btn); row2.addWidget(self._avg_align_btn)
        avg_l.addLayout(row2)
        <우측_패널_레이아웃>.addWidget(avg_box)
        self._avg_group_box = avg_box
        self._update_avg_align_enabled()
```
> 실행자 주의: `_make_n2_toggle`/`_make_n2_segment`는 이 코드베이스의 실제 N2 헬퍼 이름으로 치환할 것(예: 세션에서 쓰인 `_N2Toggle`/`_N2Segmented` 생성 패턴). 해당 파일에서 SIGNAL GENERATOR 타입 세그먼트/토글이 만들어진 방식을 그대로 따를 것. 인라인 스타일 금지.

핸들러 메서드(클래스 내 추가):
```python
    def _on_avg_master(self, on):
        self._avg_on = bool(on)
        _diag('tf_avg_toggle', on=self._avg_on, mode=self._avg_mode)
        self._request_avg_render()

    def _on_avg_mode(self, idx):
        self._avg_mode = 'complex' if idx == 1 else 'mag'
        self._update_avg_align_enabled()
        self._request_avg_render()

    def _on_avg_only(self, on):
        self._avg_only = bool(on); self._request_avg_render()

    def _on_avg_align(self, on):
        self._avg_align = bool(on); self._request_avg_render()

    def _update_avg_align_enabled(self):
        # 딜레이정렬은 복소 모드에서만 의미
        if hasattr(self, '_avg_align_btn'):
            self._avg_align_btn.setEnabled(self._avg_mode == 'complex')

    def _request_avg_render(self):
        # 다음 렌더 틱에서 Task5 훅이 반영. 즉시 캔버스 갱신도 트리거.
        for cvs in (getattr(self, 'mag_cvs', None), getattr(self, 'phase_cvs', None),
                    getattr(self, 'ir_cvs', None)):
            if cvs is not None: cvs.update()
```

- [ ] **Step 4: 실행 → 통과 + PNG 확인**

Run → `saved avg_panel; avg_on= False`. `Read` `/tmp/avg_panel.png` — "AVERAGE" 헤더 + AVG/크기·복소/평균만/딜레이정렬 컨트롤이 N2 스타일로 보이는지 확인. `python3 selfcheck.py` 회귀.

- [ ] **Step 5: 커밋**

```bash
git add wayaudo2.py
git commit -m "feat(tf): AVERAGE 컨트롤 그룹 UI + 평균 상태 필드

우측 패널 N2 그룹(AVG 마스터·크기/복소 세그먼트·평균만·딜레이정렬) + _avg_* 상태.
_diag(tf_avg_toggle). offscreen 패널 렌더 검증.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_017ApFryWrJA64wo2cfBRLcv"
```

---

### Task 4: 카드별 "평균 포함" 토글 (`_MeasCard`)

각 측정 카드 헤더에 평균 참여 토글 추가.

**Files:**
- Modify: `wayaudo2.py` — `_MeasCard` 헤더(`hdr` 구성, `:10490` 인근 `hdr.addWidget(self._vis_chk); ...; hdr.addStretch()`).
- Test: `<scratchpad>/grab_meascard_avg.py`

**Interfaces:**
- Produces: `_MeasCard._avg_chk`(checkable QPushButton), `_MeasCard.in_average`(bool 프로퍼티/속성), 시그널 `avg_include_toggled = pyqtSignal(int, bool)` (card_id, included). 기본 OFF.

- [ ] **Step 1: 실패하는 카드 렌더 테스트**

`grab_meascard_avg.py`:
```python
import os, sys
sys.path.insert(0, '/Users/yuncheollee/WSA2'); os.chdir('/Users/yuncheollee/WSA2')
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['WSA2_SETTINGS_PATH'] = '/tmp/x.json'; os.environ['WSA2_CAPTURES_PATH'] = '/tmp/c.json'
import wayaudo2 as w
from PyQt5.QtWidgets import QApplication
app = QApplication.instance() or QApplication([])
c = w._MeasCard(2, w.T('green'), deletable=True)
assert hasattr(c, '_avg_chk') and hasattr(c, 'in_average')
assert c.in_average is False
c.grab().save('/tmp/meascard_avg.png'); print('saved meascard_avg')
```
Run → FAIL: `AssertionError`.

- [ ] **Step 2: 구현 — 헤더에 토글 추가**

`_MeasCard.__init__`에 클래스 시그널 선언(클래스 상단 다른 pyqtSignal 옆):
```python
    avg_include_toggled = pyqtSignal(int, bool)
```
`hdr.addWidget(num_lbl); hdr.addStretch()` 직전, `num_lbl` 다음에:
```python
        self.in_average = False
        self._avg_chk = QPushButton('avg'); self._avg_chk.setCheckable(True)
        self._avg_chk.setChecked(False); self._avg_chk.setFocusPolicy(Qt.NoFocus)
        self._avg_chk.setCursor(Qt.PointingHandCursor)
        self._avg_chk.setToolTip(_tx('Include this source in the live average'))
        self._avg_chk.setStyleSheet(self._avg_chk_ss())
        self._avg_chk.toggled.connect(self._on_avg_include)
        hdr.addWidget(self._avg_chk)
```
메서드:
```python
    def _avg_chk_ss(self):
        on = getattr(self, '_avg_chk', None) is not None and self._avg_chk.isChecked()
        acc = T('accent'); dim = T('text_dim')
        return (f'QPushButton{{font-size:{FS_SM}px;border:1px solid {T("border")};'
                f'border-radius:5px;padding:1px 6px;background:transparent;color:{dim};}}'
                f'QPushButton:checked{{border-color:{acc};color:{acc};'
                f'background:rgba(78,125,240,0.14);}}')

    def _on_avg_include(self, on):
        self.in_average = bool(on)
        self._avg_chk.setStyleSheet(self._avg_chk_ss())
        self.avg_include_toggled.emit(self._card_id, self.in_average)
```

- [ ] **Step 3: 실행 → 통과 + PNG 확인**

Run → `saved meascard_avg`. `Read` `/tmp/meascard_avg.png` — 헤더에 "avg" 토글이 보이는지. `python3 selfcheck.py` 회귀.

- [ ] **Step 4: 커밋**

```bash
git add wayaudo2.py
git commit -m "feat(tf): _MeasCard 헤더에 '평균 포함(avg)' 토글

카드별 라이브 평균 참여 선택. in_average 상태 + avg_include_toggled 시그널. 기본 OFF.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_017ApFryWrJA64wo2cfBRLcv"
```

---

### Task 5: 렌더 훅 `_render_average` (수집 + 그리기)

참여 카드들의 H·γ²·delay를 모아 Task1 호출 → Task2 API로 그림. "평균만" 모드 처리. Single·MTW 양쪽에서 실행.

**Files:**
- Modify: `wayaudo2.py`
  - `_render_extra_pairs` (`:14918`) 끝에서 `self._render_average(freqs, t_ms)` 호출. (이 메서드는 이미 Single·MTW 양쪽 경로에서 호출되므로 훅 1곳으로 커버.)
  - primary H 접근: `_render_primary_H`(`:15738`)가 계산하는 `H_raw`/`gamma2`를 프레임 간 재사용하도록 `self._last_primary_H`/`self._last_primary_coh`에 저장(계산 직후 대입). primary delay = `self.delay_ms`.
  - 신규 메서드 `_render_average` 추가.
- Test: 전체 창 필요 → offscreen segfault. 대신 (a) 구문 게이트, (b) 앱 실행 후 `_diag('tf_avg_render')` 로그를 사용자 실행으로 확보 → Claude가 직접 Read. + Task1이 수학을 이미 검증하므로 훅은 배선만.

**Interfaces:**
- Consumes: Task1 `_multimic_average(...)`, Task2 `set_tf_average/clear_tf_average`, Task3 상태(`_avg_on`/`_avg_mode`/`_avg_only`/`_avg_align`), Task4 `_MeasCard.in_average`.
- Produces: `_render_average(freqs, t_ms)` — 참여 카드 H 수집·평균·렌더. `_avg_curve_color()` 헬퍼(테마 대응 색).

- [ ] **Step 1: primary H 저장 추가**

`_render_primary_H`(`:15738`)에서 `H_raw`, `gamma2`가 확정된 직후:
```python
        self._last_primary_H = H_raw
        self._last_primary_coh = gamma2
```
primary 미활성 프레임에선 stale 방지 위해 `_on_frame`의 primary 분기 else(카드1 Stop)에서 `self._last_primary_H = None`.

- [ ] **Step 2: `_render_average` 구현**

`_render_extra_pairs` 정의 아래에:
```python
    def _avg_curve_color(self):
        # 다색 개별 곡선 위에서 도드라지는 테마 대응 고대비
        return '#FFFFFF' if _theme == 'dark' else '#1A1A1A'

    def _render_average(self, freqs, t_ms):
        if not getattr(self, '_avg_on', False):
            self.mag_cvs.clear_tf_average(); self.phase_cvs.clear_tf_average()
            self.ir_cvs.clear_tf_average()
            self._apply_avg_only(False)
            return
        H_list, g_list, d_list = [], [], []
        # primary(카드1)
        pc = self._level_cards[0] if getattr(self, '_level_cards', None) else None
        if (pc is not None and getattr(pc, 'in_average', False)
                and pc._display_on and getattr(self, '_last_primary_H', None) is not None):
            H_list.append(self._last_primary_H)
            g_list.append(getattr(self, '_last_primary_coh', None))
            d_list.append(self.delay_ms)
        # extra 카드
        for i, acc in enumerate(self._extra_pair_acc):
            if acc is None or acc['n'] < 3: continue
            pair = self._extra_pairs[i] if i < len(self._extra_pairs) else None
            if not pair or not pair.get('display', True): continue
            card = pair.get('card')
            if card is None or not getattr(card, 'in_average', False): continue
            H = acc['cross'] / np.maximum(acc['auto_x'], 1e-30)
            g = np.clip(np.abs(acc['cross'])**2 /
                        np.maximum(acc['auto_x']*acc['auto_y'], 1e-30), 0.0, 1.0)
            H_list.append(H); g_list.append(g); d_list.append(pair.get('delay_ms', 0.0))
        r = _multimic_average(H_list, g_list, d_list, freqs, self.sample_rate,
                              self.smooth_bpo, mode=self._avg_mode, align=self._avg_align)
        _diag('tf_avg_render', on=True, mode=self._avg_mode, n=(r['n'] if r else 0),
              aligned=self._avg_align, only=self._avg_only)
        if r is None:
            self.mag_cvs.clear_tf_average(); self.phase_cvs.clear_tf_average()
            self.ir_cvs.clear_tf_average(); self._apply_avg_only(False)
            return
        col = self._avg_curve_color()
        self.mag_cvs.set_tf_average(col, r['f'], r['mag'], coh=r['coh'])
        if r['mode'] == 'complex':
            self.phase_cvs.set_tf_average(col, r['f'], r['ph_wrap'], r['ph_unwr'], r['grp'])
            if r['h_ir'] is not None:
                self.ir_cvs.set_tf_average(col, t_ms, r['h_ir'])
        else:
            self.phase_cvs.clear_tf_average(); self.ir_cvs.clear_tf_average()
        self._apply_avg_only(self._avg_only)

    def _apply_avg_only(self, only):
        # '평균만' ON → 개별 라이브 곡선 숨김. 캔버스에 개별 표시 억제 플래그.
        for cvs in (self.mag_cvs, self.phase_cvs, self.ir_cvs):
            if getattr(cvs, '_hide_individual', None) != only:
                cvs._hide_individual = only; cvs.update()
```

- [ ] **Step 3: 훅 호출 + 개별 숨김 플래그 반영**

`_render_extra_pairs` 마지막 줄 다음에:
```python
        self._render_average(freqs, t_ms)
```
각 캔버스 페인트에서 개별 곡선 그리기 전에 `if getattr(self, '_hide_individual', False): (개별 스킵)` 가드 추가 — mag(`:10184` extra 루프 + `:10203` front 재드로우 + primary 곡선 드로우), phase, ir 각각. AVG 드로우는 이 가드 밖(항상 그림).

- [ ] **Step 4: 검증 — 구문 게이트 + 앱 실행 로그**

`/usr/bin/python3 -c "import ast; ast.parse(open('wayaudo2.py').read())"` → 무출력.
`python3 selfcheck.py` 회귀 통과.
사용자 실행 검증(HW 불필요, 내부 SigGen+맥 마이크로도 배선 확인 가능): 사용자가 카드 2개 이상 Start + avg 토글 체크 + AVG ON → Claude가 최신 로그(`ls -t ~/Library/Logs/WSA2/wsa2_*.log | head -1`)에서 `[DIAG] tf_avg_render n=2` 확인.

- [ ] **Step 5: 커밋**

```bash
git add wayaudo2.py
git commit -m "feat(tf): _render_average 훅 — 참여 카드 수집·평균·오버레이 렌더

_render_extra_pairs 직후 호출(Single·MTW 공통). primary+extra H 수집→_multimic_average
→ 3캔버스 AVG 슬롯. '평균만' 개별 숨김. _diag(tf_avg_render).

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_017ApFryWrJA64wo2cfBRLcv"
```

---

### Task 6: 세션 저장/복원 + 라이트/다크 restyle + selfcheck

평균 상태·카드별 참여 플래그 영속화, 테마 토글 대응, 회귀 커버.

**Files:**
- Modify: `wayaudo2.py`
  - 세션 저장 dict(`:13556` 인근 `_save_settings`/settings 직렬화) — avg 상태 키 추가.
  - `extra_pairs` 저장 구조(`:13568`)에 `in_average` 필드; 복원(`_populate_extra_pair`/`_apply_extra_pairs` `:13724/:13728`)에서 카드 토글 복원.
  - 복원 로드 지점(`:13582` `_idx(...)` 인근) — avg 상태 복원.
  - 테마 restyle: `_restyle_sig_gen_theme`(정의부)에 AVERAGE 그룹 위젯 restyle 추가 + `_avg_group_box` 내 `n2GroupHdr` 라벨.
- Modify: `selfcheck.py` — AVERAGE 그룹/`_MeasCard` avg 토글 렌더 `check()` 추가.

**Interfaces:**
- Consumes: Task3 상태·위젯, Task4 `_MeasCard.in_average`.
- Produces: settings 키 `tf_avg_on`·`tf_avg_mode`·`tf_avg_only`·`tf_avg_align`; extra_pairs 항목 `in_average`.

- [ ] **Step 1: 저장 추가**

세션 저장 dict(`:13556` 인근, `'response': ...` 옆)에:
```python
            'tf_avg_on': self._avg_on, 'tf_avg_mode': self._avg_mode,
            'tf_avg_only': self._avg_only, 'tf_avg_align': self._avg_align,
```
`extra_pairs` 직렬화(`:13568`)의 각 항목 dict에 `'in_average': (p.get('card').in_average if p.get('card') else False)` 추가.

- [ ] **Step 2: 복원 추가**

복원부(`:13582` 인근)에:
```python
        self._avg_on = bool(d.get('tf_avg_on', False))
        self._avg_mode = d.get('tf_avg_mode', 'mag')
        self._avg_only = bool(d.get('tf_avg_only', False))
        self._avg_align = bool(d.get('tf_avg_align', True))
        if hasattr(self, '_avg_master_btn'):
            self._avg_master_btn.setChecked(self._avg_on)
            self._avg_mode_seg.setCurrentIndex(1 if self._avg_mode == 'complex' else 0)
            self._avg_only_btn.setChecked(self._avg_only)
            self._avg_align_btn.setChecked(self._avg_align)
            self._update_avg_align_enabled()
```
`_populate_extra_pair`에서 카드 생성 후: `if entry.get('in_average'): card._avg_chk.setChecked(True)`.

- [ ] **Step 3: 라이트/다크 restyle**

`_restyle_sig_gen_theme`에 추가:
```python
        if hasattr(self, '_avg_group_box'):
            for _hdr in self._avg_group_box.findChildren(QLabel):
                if _hdr.objectName() == 'n2GroupHdr':
                    _hdr.setStyleSheet(_n2_group_hdr_label_ss())  # 기존 헬퍼/패턴대로
            for _b in self._avg_group_box.findChildren(QPushButton):
                if hasattr(_b, 'restyle'): _b.restyle()
        for _c in getattr(self, '_level_cards', []):
            if hasattr(_c, '_avg_chk'): _c._avg_chk.setStyleSheet(_c._avg_chk_ss())
        for _p in getattr(self, '_extra_pairs', []):
            _card = _p.get('card')
            if _card is not None and hasattr(_card, '_avg_chk'):
                _card._avg_chk.setStyleSheet(_card._avg_chk_ss())
```
> `n2GroupHdr` 라벨 재스타일은 이 세션에서 SIGNAL GENERATOR 헤더에 쓴 방식과 동일하게. 세그먼트/토글은 `restyle()` 보유 시 호출.

- [ ] **Step 4: selfcheck check() 추가**

`selfcheck.py`에 신규 check (AVERAGE 그룹 + 카드 avg 토글 렌더):
```python
@check('tf_average_group')
def _c_tf_avg(save):
    import wayaudo2 as w
    tw = w.TransferFunctionWindow(embedded=True)
    save('tf_average_group', tw._avg_group_box.grab())
    c = w._MeasCard(2, w.T('green'), deletable=True)
    save('meascard_avg_toggle', c.grab())
```
(selfcheck의 실제 `check` 데코레이터/`save` 시그니처에 맞춰 치환.)

- [ ] **Step 5: 검증**

`python3 selfcheck.py tf_average` → PASS, 생성 PNG를 `Read`로 확인.
라이트/다크 토글 검증: 앱 실행 후 라이트 전환 → 우측 패널 AVERAGE 그룹·카드 avg 토글이 보이는지 offscreen 재현(`grab_avg_panel.py`를 `w._theme='light'` 설정 후 재실행)하여 PNG `Read`.
구문 게이트 통과.

- [ ] **Step 6: 커밋**

```bash
git add wayaudo2.py selfcheck.py
git commit -m "feat(tf): 라이브 평균 세션 저장/복원 + 라이트/다크 restyle + selfcheck

avg 상태·카드별 in_average 영속화. _restyle_sig_gen_theme에 AVERAGE 그룹 포함.
selfcheck tf_average_group check 추가.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_017ApFryWrJA64wo2cfBRLcv"
```

---

## 문서 동기화 (구현 완료 후)

- `RELEASE_NOTES.md` + `RELEASE_NOTES.html` + `ISSUES.md`에 v1.9 "라이브 멀티마이크 실시간 평균" 항목 반영(버전 작업=모든 문서 즉시 기록 규칙).
- 메모리 `project_v19_response_symmetry` 인접에 신규 `project_v19_multimic_live_average` 기록(코드 위치·HW 검증 대기).

## HW 실측 (사용자, 인터페이스 필요)

- 실제 마이크 2개 이상을 서로 다른 위치에 두고 라이브 평균:
  - 크기 모드 = 위치 평균 응답으로 보이는지.
  - 복소+정렬 = 콤필터(가짜 딥) 없이 정합되는지, 정렬 OFF와 비교.
- 내부 SigGen+맥 내장마이크로는 **배선/렌더만** 확인 가능(위치 다른 실측은 불가).

## Self-Review 결과

- **Spec 커버리지**: §4 수학→Task1, §6 렌더/캔버스→Task2·5, §5 참여카드→Task4, §7 UI→Task3, §8 저장·§7 restyle→Task6, §10 검증→각 태스크 + HW 섹션. 누락 없음.
- **Placeholder 스캔**: 실행자 치환 지점(N2 헬퍼 실제 이름, selfcheck 데코레이터 시그니처)은 `>` 주석으로 명시했고 코드 본체는 완결. TODO/TBD 없음.
- **타입 일관성**: `set_tf_average`/`clear_tf_average` 시그니처가 Task2 정의와 Task5 호출에서 일치. Task1 반환 dict 키(`f/mag/coh/ph_wrap/ph_unwr/grp/h_ir`)가 Task5 소비와 일치. 상태 필드명(`_avg_on/_avg_mode/_avg_only/_avg_align`) Task3 정의 = Task5/6 사용 일치.
