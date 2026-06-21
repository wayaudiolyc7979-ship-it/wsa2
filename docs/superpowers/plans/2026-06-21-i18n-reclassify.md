# i18n Policy Refinement: Main/Tool-Window UI Always English Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Unwrap `_tx(...)` to plain English strings for all persistent main-interface and tool-window display strings, keeping `_tx(...)` only for tooltips, modal dialog class bodies, popup helper arguments, and right-click context menu items.

**Architecture:** 93 `_tx(...)` call sites will be unwrapped in `wayaudo2.py`. The `_tx` function, `_TR_KO` dict, and all KEEP sites remain untouched. Work is done class-by-class in file order. Each group of edits ends with a syntax gate. Full selfcheck runs at the end.

**Tech Stack:** Python 3, PyQt5, single file `wayaudo2.py` (~18k lines), offscreen test harness via `selfcheck.py`.

## Global Constraints

- File: `/Users/yuncheollee/WSA2/wayaudo2.py` — single file, ~18k lines.
- Do NOT touch `_TR_KO` dict (lines 358–633), `def _tx` (line 650), or any log/comment lines.
- Do NOT instantiate `MainWindow` in tests (segfaults offscreen); test isolated widgets instead.
- Test isolation: always set `QT_QPA_PLATFORM=offscreen WSA2_SETTINGS_PATH=/tmp/x.json WSA2_CAPTURES_PATH=/tmp/c.json`.
- Syntax gate: `python3 -c "import ast; ast.parse(open('wayaudo2.py').read()); print('OK')"` after every task.
- UNWRAP means: `_tx('X')` → `'X'` and `_tx("X")` → `"X"` (exact English text, same as the argument).
- For f-string rewrites: `_tx('Some {x} text').format(x=x)` → `f'Some {x} text'`.

## KEEP vs UNWRAP Decision Summary

**KEEP `_tx(...)` if ANY of:**
1. Argument of `setToolTip(...)` — anywhere, direct or indirect (e.g. passed as `tip` to `_metric_card`).
2. Enclosing class is one of the 12 modal dialog classes: `LicenseDialog`, `CalibDialog`, `SplAlarmConfigDialog`, `SplLayoutDialog`, `ColorPickerDialog`, `_DelayAdvancedDialog`, `SweepConfigDialog`, `SineConfigDialog`, `DelayFinderDialog`, `AllDelayFinderDialog`, `_TFAverageDialog`, `ShortcutsDialog`.
3. Argument inside `_brand_msg(...)`, `_text_input_dialog(...)`, `_BrandBox.*()`, `QMessageBox.*()` calls — direct or on continuation lines.
4. Argument of `menu.addAction(_tx(...))` (right-click context menus in `_CaptureDrawer`).
5. `verify_license` / `_lic_check_payload` error return strings (lines 182, 185, 208, 211) — displayed in `LicenseDialog._status`.
6. Inside `_text_input_dialog`/`_brand_msg`/`_BrandBox` function/class bodies (lines 3745–3815).

**UNWRAP everything else** — persistent UI text in: tool windows (`LeqWindow`, `SplAlarmWindow`, `ShowModeWindow`, `SplMeterWindow`), device/capture panel widgets (`DeviceCardPopup`, `ChannelPopup`, `_CaptureDrawer`), canvas hints (`TFMagCanvas`), TF measurement cards (`_MeasCard`), main window classes (`TransferFunctionWindow`, `StereoLoudnessPage`, `_TFPopoutWindow`, `_SpectrumPopoutWindow`, `_StereoPopoutWindow`, `MainWindow`).

---

## File Map

- Modify: `/Users/yuncheollee/WSA2/wayaudo2.py` (all changes)
- Verify render: `/tmp/calib_ko_v2.png` (CalibDialog KO), `/tmp/leq_ko.png` (LeqWindow EN)
- Report: `/Users/yuncheollee/WSA2/.superpowers/sdd/i18n-reclassify-report.md`

---

### Task 1: Tool-Window Classes — LeqWindow, SplAlarmWindow, ShowModeWindow, SplMeterWindow

**Files:**
- Modify: `/Users/yuncheollee/WSA2/wayaudo2.py:4096,4117,4125,4130,4150,4665,4800,4959`

**UNWRAP sites (8 total):**

| Line | Class | Old | New |
|------|-------|-----|-----|
| 4096 | LeqWindow | `_tx('Time Average Level (LEQ)')` | `'Time Average Level (LEQ)'` |
| 4117 | LeqWindow | `_tx('Start')` | `'Start'` |
| 4125 | LeqWindow | `_tx('Standby')` | `'Standby'` |
| 4130 | LeqWindow | `_tx('Live LEQ')` | `'Live LEQ'` |
| 4150 | LeqWindow | `_tx('Reset')` | `'Reset'` |
| 4665 | SplAlarmWindow | `_tx('SPL Alarm')` | `'SPL Alarm'` |
| 4800 | ShowModeWindow | `_tx('SPECTRA — Show Mode')` | `'SPECTRA — Show Mode'` |
| 4959 | SplMeterWindow | `_tx('SPL Meter')` | `'SPL Meter'` |

**Note:** `setToolTip(_tx(...))` in SplAlarmWindow (lines 4681, 4683) and SplMeterWindow (lines 4987, 4990, 4993) are KEEP — do not touch them.

- [ ] **Step 1: Read lines and make edits**

Edit L4096 in `wayaudo2.py`:
```python
# Before:
self.setWindowTitle(_tx('Time Average Level (LEQ)')); _apply_dark_titlebar(self, resizable=True)
# After:
self.setWindowTitle('Time Average Level (LEQ)'); _apply_dark_titlebar(self, resizable=True)
```

Edit L4117:
```python
# Before:
self.leq_start_btn = QPushButton(_tx('Start')); _apply_txn(self.leq_start_btn, False)
# After:
self.leq_start_btn = QPushButton('Start'); _apply_txn(self.leq_start_btn, False)
```

Edit L4125:
```python
# Before:
self.progress_lbl = QLabel(_tx('Standby'))
# After:
self.progress_lbl = QLabel('Standby')
```

Edit L4130:
```python
# Before:
result_group = QGroupBox(_tx('Live LEQ'))
# After:
result_group = QGroupBox('Live LEQ')
```

Edit L4150:
```python
# Before:
rst = QPushButton('  ' + _tx('Reset')); rst.setIcon(_icon('refresh'))
# After:
rst = QPushButton('  Reset'); rst.setIcon(_icon('refresh'))
```

Edit L4665:
```python
# Before:
self.setWindowTitle(_tx('SPL Alarm'))
# After:
self.setWindowTitle('SPL Alarm')
```

Edit L4800:
```python
# Before:
self.setWindowTitle(_tx('SPECTRA — Show Mode'))
# After:
self.setWindowTitle('SPECTRA — Show Mode')
```

Edit L4959:
```python
# Before:
self.setWindowTitle(_tx('SPL Meter'))
# After:
self.setWindowTitle('SPL Meter')
```

- [ ] **Step 2: Syntax gate**

```bash
cd /Users/yuncheollee/WSA2 && python3 -c "import ast; ast.parse(open('wayaudo2.py').read()); print('syntax OK')"
```
Expected: `syntax OK`

---

### Task 2: Device/Channel Popup Widgets — DeviceCardPopup, ChannelPopup

**Files:**
- Modify: `/Users/yuncheollee/WSA2/wayaudo2.py:5483,5511,5552,5593,5742`

**UNWRAP sites (5 total):**

| Line | Class | Old | New |
|------|-------|-----|-----|
| 5483 | DeviceCardPopup | `_tx("Input Device")` | `"Input Device"` |
| 5511 | DeviceCardPopup | `_tx('Refresh Devices')` | `'Refresh Devices'` |
| 5552 | DeviceCardPopup | `_tx('✓ Refreshed')` | `'✓ Refreshed'` |
| 5593 | DeviceCardPopup | `_tx('Disconnected')` | `'Disconnected'` |
| 5742 | ChannelPopup | `_tx('Input Channels')` | `'Input Channels'` |

**Note:** `setToolTip` calls in this range (lines 5630, 5663, 5672) are KEEP — do not touch.

- [ ] **Step 1: Read lines and make edits**

Read lines 5480–5595 and 5740–5745 in `wayaudo2.py` to confirm exact context.

Edit L5483 (inside f-string):
```python
# Before:
f'&nbsp;<span style="font-size:10px;color:{T("text_dim")};">{_tx("Input Device")}</span>'
# After:
f'&nbsp;<span style="font-size:10px;color:{T("text_dim")};">Input Device</span>'
```

Edit L5511:
```python
# Before:
ref_btn = QPushButton(_tx('Refresh Devices')); ref_btn.setIcon(_icon('refresh', 13))
# After:
ref_btn = QPushButton('Refresh Devices'); ref_btn.setIcon(_icon('refresh', 13))
```

Edit L5552:
```python
# Before:
self._status_lbl.setText(_tx('✓ Refreshed'))
# After:
self._status_lbl.setText('✓ Refreshed')
```

Edit L5593:
```python
# Before:
sub = QLabel(_tx('Disconnected'))
# After:
sub = QLabel('Disconnected')
```

Edit L5742:
```python
# Before:
hdr = QLabel(_tx('Input Channels'))
# After:
hdr = QLabel('Input Channels')
```

- [ ] **Step 2: Syntax gate**

```bash
cd /Users/yuncheollee/WSA2 && python3 -c "import ast; ast.parse(open('wayaudo2.py').read()); print('syntax OK')"
```
Expected: `syntax OK`

---

### Task 3: CaptureDrawer and Canvas Hint Text

**Files:**
- Modify: `/Users/yuncheollee/WSA2/wayaudo2.py:6426,6466,6467,6777,6844,8441`

**UNWRAP sites (6 total):**

| Line | Class | Old | New |
|------|-------|-----|-----|
| 6426 | _CaptureDrawer | `_tx('Avg')` | `'Avg'` |
| 6466 | _CaptureDrawer | `_tx('Spectrum')` | `'Spectrum'` |
| 6467 | _CaptureDrawer | `_tx('Transfer Fn')` | `'Transfer Fn'` |
| 6777 | _CaptureDrawer | `_tx('empty')` | `'empty'` |
| 6844 | _CaptureDrawer | `_tx('  Next capture goes here')` | `'  Next capture goes here'` |
| 8441 | TFMagCanvas | `_tx('Play a signal to start measuring')` | `'Play a signal to start measuring'` |

**Note:** All `addAction(_tx(...))` calls in `_CaptureDrawer` (lines 6978, 6981, 6988, 6992, 6996, 7004) are right-click context menus — KEEP. The `setToolTip(_tx(...))` calls in this range are KEEP.

- [ ] **Step 1: Read lines and make edits**

Edit L6426:
```python
# Before:
self._avg_btn = QPushButton(_tx('Avg'))
# After:
self._avg_btn = QPushButton('Avg')
```

Edit L6466:
```python
# Before:
self._spec_tab_btn = QPushButton(_tx('Spectrum'))
# After:
self._spec_tab_btn = QPushButton('Spectrum')
```

Edit L6467:
```python
# Before:
self._tf_tab_btn   = QPushButton(_tx('Transfer Fn'))
# After:
self._tf_tab_btn   = QPushButton('Transfer Fn')
```

Edit L6777:
```python
# Before:
cnt_str    = _tx('empty') if is_pending else str(len(items))
# After:
cnt_str    = 'empty' if is_pending else str(len(items))
```

Edit L6844:
```python
# Before:
ph = QLabel(_tx('  Next capture goes here'))
# After:
ph = QLabel('  Next capture goes here')
```

Edit L8441:
```python
# Before:
_draw_idle_hint(p, pl, pt, uw, dh, text=_tx('Play a signal to start measuring'))
# After:
_draw_idle_hint(p, pl, pt, uw, dh, text='Play a signal to start measuring')
```

- [ ] **Step 2: Syntax gate**

```bash
cd /Users/yuncheollee/WSA2 && python3 -c "import ast; ast.parse(open('wayaudo2.py').read()); print('syntax OK')"
```
Expected: `syntax OK`

---

### Task 4: _MeasCard (TF Measurement Card) Labels

**Files:**
- Modify: `/Users/yuncheollee/WSA2/wayaudo2.py:8704,8772,8784`

**UNWRAP sites (3 total):**

| Line | Class | Old | New |
|------|-------|-----|-----|
| 8704 | _MeasCard | `_tx('Start')` | `'Start'` |
| 8772 | _MeasCard | `_tx('Meas')` | `'Meas'` |
| 8784 | _MeasCard | `_tx('Delay')` | `'Delay'` |

**Note:** `_MeasCard` starts at line ~8628. The `setToolTip(_tx(...))` at line 8690, 8699 are KEEP.

- [ ] **Step 1: Read lines and make edits**

Read lines 8700–8790 to confirm exact context.

Edit L8704:
```python
# Before:
self._start_btn = QPushButton(_tx('Start')); _apply_txn(self._start_btn, False)
# After:
self._start_btn = QPushButton('Start'); _apply_txn(self._start_btn, False)
```

Edit L8772:
```python
# Before:
lbl = QLabel(_tx('Meas')); lbl.setFixedWidth(30)
# After:
lbl = QLabel('Meas'); lbl.setFixedWidth(30)
```

Edit L8784:
```python
# Before:
d_lbl = QLabel(_tx('Delay')); d_lbl.setFixedWidth(30)
# After:
d_lbl = QLabel('Delay'); d_lbl.setFixedWidth(30)
```

- [ ] **Step 2: Syntax gate**

```bash
cd /Users/yuncheollee/WSA2 && python3 -c "import ast; ast.parse(open('wayaudo2.py').read()); print('syntax OK')"
```
Expected: `syntax OK`

---

### Task 5: TransferFunctionWindow — Persistent Display Strings

**Files:**
- Modify: `/Users/yuncheollee/WSA2/wayaudo2.py:10501,10651,10774,10782,10811,10918,10960,11133,12201,12856,12910,12913,13558,13559`

**UNWRAP sites (14 total):**

| Line | Old | New |
|------|-----|-----|
| 10501 | `_tx('SPECTRA — Transfer Function')` | `'SPECTRA — Transfer Function'` |
| 10651 | `_tx('Signal Generator')` | `'Signal Generator'` |
| 10774 | `_tx('Play  [G]')` | `'Play  [G]'` |
| 10782 | `_tx('Measurement')` | `'Measurement'` |
| 10811 | `_tx('In')` | `'In'` |
| 10918 (×2) | `_tx('Single')`, `_tx('Adaptive')` | `'Single'`, `'Adaptive'` |
| 10960 | `_tx('Capture')` | `'Capture'` |
| 11133 | `_tx('Internal (SigGen)')` | `'Internal (SigGen)'` |
| 12201 | `_tx('● Disconnected')` | `'● Disconnected'` |
| 12856 | `_tx('Low coherence — captured as-is')` | `'Low coherence — captured as-is'` |
| 12910 | `_tx('Select Export Folder')` | `'Select Export Folder'` |
| 12913 | `_tx('Export')` | `'Export'` |
| 13558 | `_tx('Select Audio File')` | `'Select Audio File'` |
| 13559 | `_tx('Audio Files (*.wav *.flac *.aiff *.aif *.ogg *.mp3 *.m4a *.caf);;All Files (*)')` | `'Audio Files (*.wav *.flac *.aiff *.aif *.ogg *.mp3 *.m4a *.caf);;All Files (*)'` |

**KEEP (do not touch):** All `setToolTip(_tx(...))` in TransferFunctionWindow (lines 10761, 10921, 10936, 10961, 10972, 10978, 10993, 11009, 10485). All `_BrandBox.*(_tx(...))` calls (lines 11444, 12190, 12585, 12717, 12890, 12907, 12949, 12950→already_inside_BrandBox, 12953, 12958, 12966, 13348, 13579, 13594, 13597, 13744, 13770, 13872). Line 12950 is inside `_BrandBox.information(...)` — KEEP.

- [ ] **Step 1: Read the exact lines**

Read lines 10498–10504, 10649–10653, 10772–10812, 10916–10922, 10958–10963, 11131–11135, 12199–12203, 12854–12858, 12908–12916, 13556–13562.

- [ ] **Step 2: Apply edits**

Edit L10501:
```python
# Before:
self.setWindowTitle(_tx('SPECTRA — Transfer Function'))
# After:
self.setWindowTitle('SPECTRA — Transfer Function')
```

Edit L10651:
```python
# Before:
sg = QGroupBox(_tx('Signal Generator'))
# After:
sg = QGroupBox('Signal Generator')
```

Edit L10774:
```python
# Before:
self.sig_on_btn = QPushButton(_tx('Play  [G]')); _apply_txn(self.sig_on_btn, False); self.sig_on_btn.setCheckable(True)
# After:
self.sig_on_btn = QPushButton('Play  [G]'); _apply_txn(self.sig_on_btn, False); self.sig_on_btn.setCheckable(True)
```

Edit L10782:
```python
# Before:
mp = QGroupBox(_tx('Measurement'))
# After:
mp = QGroupBox('Measurement')
```

Edit L10811:
```python
# Before:
_rl = QLabel(_tx('In')); _rl.setFixedWidth(14)
# After:
_rl = QLabel('In'); _rl.setFixedWidth(14)
```

Edit L10918:
```python
# Before:
self.eng_cb = RoundComboBox(); self.eng_cb.addItems([_tx('Single'), _tx('Adaptive')])
# After:
self.eng_cb = RoundComboBox(); self.eng_cb.addItems(['Single', 'Adaptive'])
```

Edit L10960:
```python
# Before:
self.tf_cap_btn = QPushButton(_tx('Capture')); self.tf_cap_btn.setFixedWidth(68); self.tf_cap_btn.setFixedHeight(30)
# After:
self.tf_cap_btn = QPushButton('Capture'); self.tf_cap_btn.setFixedWidth(68); self.tf_cap_btn.setFixedHeight(30)
```

Edit L11133:
```python
# Before:
_internal_sigg_label = _tx('Internal (SigGen)')   # evaluate before 't' is shadowed by Thread
# After:
_internal_sigg_label = 'Internal (SigGen)'   # evaluate before 't' is shadowed by Thread
```

Edit L12201:
```python
# Before:
self.status_lbl.setText(_tx('● Disconnected'))
# After:
self.status_lbl.setText('● Disconnected')
```

Edit L12856:
```python
# Before:
self.avg_lbl.setText(_tx('Low coherence — captured as-is'))
# After:
self.avg_lbl.setText('Low coherence — captured as-is')
```

Edit L12910:
```python
# Before:
dlg = QFileDialog(self, _tx('Select Export Folder'))
# After:
dlg = QFileDialog(self, 'Select Export Folder')
```

Edit L12913:
```python
# Before:
dlg.setLabelText(QFileDialog.Accept, _tx('Export'))
# After:
dlg.setLabelText(QFileDialog.Accept, 'Export')
```

Edit L13558:
```python
# Before:
self, _tx('Select Audio File'), '',
# After:
self, 'Select Audio File', '',
```

Edit L13559:
```python
# Before:
_tx('Audio Files (*.wav *.flac *.aiff *.aif *.ogg *.mp3 *.m4a *.caf);;All Files (*)'))
# After:
'Audio Files (*.wav *.flac *.aiff *.aif *.ogg *.mp3 *.m4a *.caf);;All Files (*)'))
```

- [ ] **Step 3: Syntax gate**

```bash
cd /Users/yuncheollee/WSA2 && python3 -c "import ast; ast.parse(open('wayaudo2.py').read()); print('syntax OK')"
```
Expected: `syntax OK`

---

### Task 6: StereoLoudnessPage — Hero Title Text

**Files:**
- Modify: `/Users/yuncheollee/WSA2/wayaudo2.py:15245`

**UNWRAP sites (1 total):**

| Line | Old | New |
|------|-----|-----|
| 15245 | `_tx('SHORT-TERM  (Live)')` | `'SHORT-TERM  (Live)'` |

**Note:** Lines 14907–14917 (`_tx(...)` passed as `tip` to `_metric_card`) are KEEP (used as `setToolTip`). Lines 15004, 15005, 15062 are `setToolTip` — KEEP.

- [ ] **Step 1: Read and edit L15245**

```python
# Before:
self._lbl_hero_title.setText(_tx('SHORT-TERM  (Live)') if live else 'PROGRAM LOUDNESS')
# After:
self._lbl_hero_title.setText('SHORT-TERM  (Live)' if live else 'PROGRAM LOUDNESS')
```

- [ ] **Step 2: Syntax gate**

```bash
cd /Users/yuncheollee/WSA2 && python3 -c "import ast; ast.parse(open('wayaudo2.py').read()); print('syntax OK')"
```
Expected: `syntax OK`

---

### Task 7: Popout Window Classes — WindowTitle

**Files:**
- Modify: `/Users/yuncheollee/WSA2/wayaudo2.py:15278,15294,15310`

**UNWRAP sites (3 total):**

| Line | Class | Old | New |
|------|-------|-----|-----|
| 15278 | _TFPopoutWindow | `_tx('SPECTRA — Transfer Function')` | `'SPECTRA — Transfer Function'` |
| 15294 | _SpectrumPopoutWindow | `_tx('SPECTRA — Spectrum')` | `'SPECTRA — Spectrum'` |
| 15310 | _StereoPopoutWindow | `_tx('SPECTRA — Stereo Loudness')` | `'SPECTRA — Stereo Loudness'` |

- [ ] **Step 1: Read and edit**

Read lines 15275–15315 to confirm context.

Edit L15278:
```python
# Before:
self.setWindowTitle(_tx('SPECTRA — Transfer Function'))
# After:
self.setWindowTitle('SPECTRA — Transfer Function')
```

Edit L15294:
```python
# Before:
self.setWindowTitle(_tx('SPECTRA — Spectrum'))
# After:
self.setWindowTitle('SPECTRA — Spectrum')
```

Edit L15310:
```python
# Before:
self.setWindowTitle(_tx('SPECTRA — Stereo Loudness'))
# After:
self.setWindowTitle('SPECTRA — Stereo Loudness')
```

- [ ] **Step 2: Syntax gate**

```bash
cd /Users/yuncheollee/WSA2 && python3 -c "import ast; ast.parse(open('wayaudo2.py').read()); print('syntax OK')"
```
Expected: `syntax OK`

---

### Task 8: MainWindow — Toolbar / Status / Buttons (Part A: lines 15499–16103)

**Files:**
- Modify: `/Users/yuncheollee/WSA2/wayaudo2.py:15499,15500,15503,15586,15609,15641,15648,15652,15656,15662,15671,15679,15688,15727,15735,15760,15984,16038,16059,16095,16099,16103`

**UNWRAP sites (21 total):**

| Line | Old | New |
|------|-----|-----|
| 15499 | `_tx('● Standby')` | `'● Standby'` |
| 15500 | `_tx('Light')` | `'Light'` |
| 15503 | `_tx('Calibration')` | `'Calibration'` |
| 15586 | `_tx('Select Device')` | `'Select Device'` |
| 15609 | `_tx('Start (S)')` | `'Start (S)'` |
| 15641 | `_tx('Avg')` | `'Avg'` |
| 15648 | `_tx('Peak')` | `'Peak'` |
| 15652 | `_tx('Reset')` | `'Reset'` |
| 15656 | `_tx('Capture')` | `'Capture'` |
| 15662 | `_tx('Hold')` | `'Hold'` |
| 15671 | `_tx('Range')` | `'Range'` |
| 15679 | `_tx('Speed')` | `'Speed'` |
| 15688 | `_tx('Color')` | `'Color'` |
| 15727 | `_tx('Start (S)')` | `'Start (S)'` |
| 15735 | `_tx('Input')` | `'Input'` |
| 15760 | `_tx('Target')` | `'Target'` |
| 15984 | `_tx('LEVEL')` | `'LEVEL'` |
| 16038 | `_tx('INFO')` | `'INFO'` |
| 16059 | `_tx('INPUT')` | `'INPUT'` |
| 16095 | `_tx('Help')` | `'Help'` |
| 16099 | `_tx('Log')` | `'Log'` |
| 16103 | `_tx('License')` | `'License'` |

**KEEP (do not touch):** `self.lang_btn.setToolTip(_tx(...))` (15513), `_preset_cb.setToolTip(_tx(...))` (15520), `_psave.setToolTip(_tx(...))` (15523), `_pdel.setToolTip(_tx(...))` (15525), `self.start_btn.setToolTip(_tx(...))` (15611), `self.spec_cap_btn.setToolTip(_tx(...))` (15658), `self.db_cb.setToolTip(_tx(...))` (15675), `self._spec_popout_btn.setToolTip(_tx(...))` (15702), `self._st_start_btn.setToolTip(_tx(...))` (15729), `_rst_int.setToolTip(_tx(...))` (15773), `_rst_pk.setToolTip(_tx(...))` (15778), `self._st_popout_btn.setToolTip(_tx(...))` (15791), `self._st_metricbar_btn.setToolTip(_tx(...))` (15797), `help_btn.setToolTip(_tx(...))` (16097), `log_btn.setToolTip(_tx(...))` (16101), `lic_btn.setToolTip(_tx(...))` (16105).

- [ ] **Step 1: Apply all 22 edits**

Read lines 15495–15510, 15498–15506, 15583–15592, 15607–15614, 15638–15645, 15646–15650, 15650–15657, 15659–15664, 15669–15674, 15677–15682, 15686–15692, 15725–15730, 15733–15738, 15758–15763, 15982–15986, 16036–16041, 16057–16062, 16093–16107 for exact context.

Make each replacement:
- L15499: `_tx('● Standby')` → `'● Standby'`
- L15500: `_tx('Light')` → `'Light'`
- L15503: `_tx('Calibration')` → `'Calibration'`
- L15586: `_tx('Select Device')` → `'Select Device'`
- L15609: `_tx('Start (S)')` → `'Start (S)'` (first occurrence)
- L15641: `_tx('Avg')` → `'Avg'`
- L15648: `_tx('Peak')` → `'Peak'`
- L15652: `_tx('Reset')` → `'Reset'`
- L15656: `_tx('Capture')` → `'Capture'`
- L15662: `_tx('Hold')` → `'Hold'`
- L15671: `_tx('Range')` → `'Range'`
- L15679: `_tx('Speed')` → `'Speed'`
- L15688: `_tx('Color')` → `'Color'`
- L15727: `_tx('Start (S)')` → `'Start (S)'` (second occurrence, Stereo tab)
- L15735: `_tx('Input')` → `'Input'`
- L15760: `_tx('Target')` → `'Target'`
- L15984: `_tx('LEVEL')` → `'LEVEL'`
- L16038: `_tx('INFO')` → `'INFO'`
- L16059: `_tx('INPUT')` → `'INPUT'`
- L16095: `_tx('Help')` → `'Help'`
- L16099: `_tx('Log')` → `'Log'`
- L16103: `_tx('License')` → `'License'`

- [ ] **Step 2: Syntax gate**

```bash
cd /Users/yuncheollee/WSA2 && python3 -c "import ast; ast.parse(open('wayaudo2.py').read()); print('syntax OK')"
```
Expected: `syntax OK`

---

### Task 9: MainWindow — Split View Placeholders, Status Labels, Menu Bar QActions, About/ReleaseNotes Dialogs (Part B)

**Files:**
- Modify: `/Users/yuncheollee/WSA2/wayaudo2.py:17038,17042,17128,17132,17215,17219,17292,17346,17378,17393,17684,17701,17703,17857,17859,18972,18995,18998,19001,19005,19010,19014,19016,19050,19063,19073,19076,19088,19113,19118,19120`

**UNWRAP sites (31 total):**

| Line | Old | New |
|------|-----|-----|
| 17038 | `_tx('Transfer Function is in a separate window.')` | `'Transfer Function is in a separate window.'` |
| 17042 | `_tx('  Return to Main')` | `'  Return to Main'` |
| 17128 | `_tx('Spectrum is in a separate window.')` | `'Spectrum is in a separate window.'` |
| 17132 | `_tx('  Return to Main')` | `'  Return to Main'` |
| 17215 | `_tx('Stereo Loudness is in a separate window.')` | `'Stereo Loudness is in a separate window.'` |
| 17219 | `_tx('  Return to Main')` | `'  Return to Main'` |
| 17292 | `_tx('Exit Split View')` | `'Exit Split View'` |
| 17346 | `_tx('Split View (2 panes)')` | `'Split View (2 panes)'` |
| 17378 | `_tx('Select Device')` | `'Select Device'` |
| 17393 | `_tx('Device search timed out')` | `'Device search timed out'` |
| 17684 | `_tx('Disconnected')` | `'Disconnected'` |
| 17701 | `_tx('● Error')` | `'● Error'` |
| 17703 | `_tx('Device error')` | `'Device error'` |
| 17857 | `_tx('● Disconnected')` | `'● Disconnected'` |
| 17859 | `_tx('Disconnected')` | `'Disconnected'` |
| 18972 | `_tx('Select Graph Color')` | `'Select Graph Color'` |
| 18995 | `_tx('Spectrum in Separate Window')` | `'Spectrum in Separate Window'` |
| 18998 | `_tx('Transfer Function in Separate Window')` | `'Transfer Function in Separate Window'` |
| 19001 | `_tx('Stereo Loudness in Separate Window')` | `'Stereo Loudness in Separate Window'` |
| 19005 | `_tx('Split View (2 panes)')` | `'Split View (2 panes)'` |
| 19010 | `_tx('About SPECTRA')` | `'About SPECTRA'` (menu bar QAction) |
| 19014 | `_tx('Keyboard Shortcuts')` | `'Keyboard Shortcuts'` (menu bar QAction) |
| 19016 | `_tx('Release Notes')` | `'Release Notes'` (menu bar QAction) |
| 19050 | `_tx('Release Notes')` | `'Release Notes'` (inline dialog title) |
| 19063 | `_tx('Close')` | `'Close'` |
| 19073 | `_tx('Activated')` and `_tx('Not activated')` | `'Activated'` and `'Not activated'` |
| 19076 | `_tx('About SPECTRA')` | `'About SPECTRA'` (inline dialog title) |
| 19088 | `_tx('Spectrum Analyzer')` | `'Spectrum Analyzer'` |
| 19113 | `_tx('(none)')` | `'(none)'` |
| 19118 | `_tx('Copy Machine ID')` | `'Copy Machine ID'` |
| 19120 | `_tx('Close')` | `'Close'` |

**KEEP (do not touch in this range):**
- L16142: `_tx('Send Logs')` inside `_BrandBox.information(self, _tx('Send Logs'), ...)` — KEEP (popup arg)
- L16650: `_tx('Language')`, `_tx('Cancel')` inside `_brand_msg(...)` — KEEP (popup args)
- L16662: `_tx('Restart')`, `_tx('Please restart the app manually.')` inside `_brand_msg(...)` — KEEP
- L17504–17505: `_tx('No Device')`, `_tx('Select an input device...')` inside `_BrandBox.warning(...)` — KEEP
- L17518: `_tx('Device Error')`, `_tx('Cannot read device info...')` inside `_BrandBox.warning(...)` — KEEP
- L17522: `_tx('Device Error')`, `_tx('The selected device...')` inside `_BrandBox.warning(...)` — KEEP
- L17537–17538: `_tx('Stereo Input Error')`, `_tx('Cannot open stereo...')` inside `_BrandBox.warning(...)` — KEEP
- L17706–17707: `_tx('Audio Error')`, `_tx('Microphone connection failed...')` inside `_BrandBox.warning(...)` — KEEP
- L18504: `_tx('Save Preset')`, `_tx('Name:')` inside `_text_input_dialog(...)` — KEEP
- L18509–18510: `_tx('Overwrite')`, `_tx('Overwrite preset...')`, `_tx('Cancel')` inside `_brand_msg(...)` — KEEP
- L18525–18526: `_tx('Delete')`, `_tx('Delete preset...')`, `_tx('Cancel')` inside `_brand_msg(...)` — KEEP
- L18582: `_tx('Capture')`, `_tx('Name:')` inside `_text_input_dialog(...)` — KEEP
- L18754–18755: `_tx('Delete all...')`, `_tx('Delete')`, `_tx('Cancel')` inside `_brand_msg(...)` — KEEP
- L18773: `_tx('New Group')`, `_tx('Group name:')` inside `_text_input_dialog(...)` — KEEP

- [ ] **Step 1: Apply all edits**

Work through each line. Read surrounding context for each group:
- Read 17035–17045, 17125–17135, 17212–17222 (popout placeholders)
- Read 17289–17295, 17343–17349 (split view text)
- Read 17375–17395 (device button)
- Read 17681–17706 (status labels)
- Read 17854–17862 (disconnect labels)
- Read 18969–18974 (color picker)
- Read 18992–19020 (menu bar QActions)
- Read 19048–19122 (About/Release Notes inline dialogs)

Apply replacements:
- L17038: `_tx('Transfer Function is in a separate window.')` → `'Transfer Function is in a separate window.'`
- L17042: `_tx('  Return to Main')` → `'  Return to Main'`
- L17128: `_tx('Spectrum is in a separate window.')` → `'Spectrum is in a separate window.'`
- L17132: `_tx('  Return to Main')` → `'  Return to Main'`
- L17215: `_tx('Stereo Loudness is in a separate window.')` → `'Stereo Loudness is in a separate window.'`
- L17219: `_tx('  Return to Main')` → `'  Return to Main'`
- L17292: `_tx('Exit Split View')` → `'Exit Split View'`
- L17346: `_tx('Split View (2 panes)')` → `'Split View (2 panes)'`
- L17378: `name or _tx('Select Device')` → `name or 'Select Device'`
- L17393: `_tx('Device search timed out')` → `'Device search timed out'`
- L17684: `_tx('Disconnected')` → `'Disconnected'`
- L17701: `_tx('● Error')` → `'● Error'`
- L17703: `_tx('Device error')` → `'Device error'`
- L17857: `_tx('● Disconnected')` → `'● Disconnected'`
- L17859: `_tx('Disconnected')` → `'Disconnected'`
- L18972: `_tx('Select Graph Color')` → `'Select Graph Color'`
- L18995: `_tx('Spectrum in Separate Window')` → `'Spectrum in Separate Window'`
- L18998: `_tx('Transfer Function in Separate Window')` → `'Transfer Function in Separate Window'`
- L19001: `_tx('Stereo Loudness in Separate Window')` → `'Stereo Loudness in Separate Window'`
- L19005: `_tx('Split View (2 panes)')` → `'Split View (2 panes)'`
- L19010: `_tx('About SPECTRA')` → `'About SPECTRA'`
- L19014: `_tx('Keyboard Shortcuts')` → `'Keyboard Shortcuts'`
- L19016: `_tx('Release Notes')` → `'Release Notes'`
- L19050: `_tx('Release Notes')` → `'Release Notes'`
- L19063: `_tx('Close')` → `'Close'`
- L19073: `_tx('Activated') if valid else _tx('Not activated')` → `'Activated' if valid else 'Not activated'`
- L19076: `_tx('About SPECTRA')` → `'About SPECTRA'`
- L19088: `_tx('Spectrum Analyzer')` → `'Spectrum Analyzer'`
- L19113: `_tx('(none)')` → `'(none)'`
- L19118: `_tx('Copy Machine ID')` → `'Copy Machine ID'`
- L19120: `_tx('Close')` → `'Close'`

- [ ] **Step 2: Syntax gate**

```bash
cd /Users/yuncheollee/WSA2 && python3 -c "import ast; ast.parse(open('wayaudo2.py').read()); print('syntax OK')"
```
Expected: `syntax OK`

---

### Task 10: Verify, Render, Commit, and Report

**Files:**
- Read: `/tmp/calib_ko_v2.png`, `/tmp/leq_ko.png`
- Write: `/Users/yuncheollee/WSA2/.superpowers/sdd/i18n-reclassify-report.md`
- Commit: `wayaudo2.py`

- [ ] **Step 1: Full selfcheck**

```bash
cd /Users/yuncheollee/WSA2 && QT_QPA_PLATFORM=offscreen WSA2_SETTINGS_PATH=/tmp/x.json WSA2_CAPTURES_PATH=/tmp/c.json python3 selfcheck.py
```
Expected: all 17 checks PASS.

- [ ] **Step 2: Import test**

```bash
cd /Users/yuncheollee/WSA2 && QT_QPA_PLATFORM=offscreen WSA2_SETTINGS_PATH=/tmp/x.json WSA2_CAPTURES_PATH=/tmp/c.json python3 -c "import importlib.util; spec=importlib.util.spec_from_file_location('w','wayaudo2.py'); w=importlib.util.module_from_spec(spec); spec.loader.exec_module(w); print('import OK')"
```
Expected: `import OK`

- [ ] **Step 3: Render CalibDialog in KO mode (must be Korean)**

```bash
QT_QPA_PLATFORM=offscreen WSA2_SETTINGS_PATH=/tmp/ko.json WSA2_CAPTURES_PATH=/tmp/c.json python3 -c "
import json; json.dump({'lang':'ko'}, open('/tmp/ko.json','w'))
import importlib.util; spec=importlib.util.spec_from_file_location('w','wayaudo2.py'); w=importlib.util.module_from_spec(spec); spec.loader.exec_module(w)
from PyQt5.QtWidgets import QApplication; app=QApplication([])
w._set_lang('ko')
d=w.CalibDialog('mic',1,{},0,lambda:-26.0,lambda c:None); d.resize(440,640); d.grab().save('/tmp/calib_ko_v2.png'); print('saved')
"
```
Read `/tmp/calib_ko_v2.png` and confirm Korean text is visible (e.g. "마이크 보정", "기준값:", "채널" etc.).

- [ ] **Step 4: Render LeqWindow in KO mode (display must be English)**

```bash
QT_QPA_PLATFORM=offscreen WSA2_SETTINGS_PATH=/tmp/ko.json WSA2_CAPTURES_PATH=/tmp/c.json python3 -c "
import importlib.util; spec=importlib.util.spec_from_file_location('w','wayaudo2.py'); w=importlib.util.module_from_spec(spec); spec.loader.exec_module(w)
from PyQt5.QtWidgets import QApplication; app=QApplication([])
w._set_lang('ko')
x=w.LeqWindow(); x.resize(360,320); x.grab().save('/tmp/leq_ko.png'); print('saved')
"
```
Read `/tmp/leq_ko.png` and confirm English text ("Time Average Level (LEQ)", "Start", "Standby", "Live LEQ").

- [ ] **Step 5: Write report to `/Users/yuncheollee/WSA2/.superpowers/sdd/i18n-reclassify-report.md`**

Report must include:
- Total KEEP count and UNWRAP count (target: ~186 KEEP, ~93 UNWRAP)
- Class-by-class breakdown: tool window decisions (LeqWindow 5 unwrapped, SplAlarmWindow 1, ShowModeWindow 1, SplMeterWindow 1)
- Ambiguous sites and decisions: verify_license errors (KEEP — displayed in LicenseDialog), QFileDialog args (UNWRAP — not in popup list), main menu bar QActions (UNWRAP — persistent menu bar), inline About/ReleaseNotes QDialogs (UNWRAP — enclosing class is MainWindow), metric card tooltip args (KEEP — indirectly used as setToolTip)
- Render results: calib_ko_v2.png Korean? yes/no; leq_ko.png English labels? yes/no
- selfcheck output (17/17 pass line)
- Any concerns

- [ ] **Step 6: Commit**

```bash
cd /Users/yuncheollee/WSA2
git add wayaudo2.py
git commit -m "feat(i18n): 한글모드 정책 정교화 — 메인/도구창 표시=영어, 다이얼로그·툴팁·메뉴=한글

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage check:**
1. ✅ Tool windows (LeqWindow, SplAlarmWindow, ShowModeWindow, SplMeterWindow) — Task 1 UNWRAPs their display labels; keeps their tooltips.
2. ✅ 12 modal dialog classes — not touched (remain in KEEP).
3. ✅ `setToolTip(_tx(...))` everywhere — KEEP rule applied throughout.
4. ✅ `_brand_msg`/`_text_input_dialog`/`_BrandBox.*`/`QMessageBox.*` popup args — KEEP (multi-line aware).
5. ✅ Right-click context menu `addAction(_tx(...))` — KEEP in _CaptureDrawer.
6. ✅ MainWindow persistent toolbar/tab/card/label text — UNWRAPped in Tasks 8–9.
7. ✅ TransferFunctionWindow persistent display — Task 5.
8. ✅ StereoLoudnessPage display — Task 6.
9. ✅ Popout window titles — Task 7.
10. ✅ Render verification (CalibDialog KO, LeqWindow EN) — Task 10.
11. ✅ selfcheck 17/17 — Task 10.
12. ✅ Commit with exact message — Task 10.
13. ✅ Report — Task 10.

**Ambiguous decisions documented:**
- verify_license errors (L182, L185, L208, L211): KEEP — displayed via `self._status.setText(reason)` in `LicenseDialog._activate`, which is inside the modal `LicenseDialog` class. These are functionally modal dialog text.
- QFileDialog title/label (L12910, L12913, L13558, L13559): UNWRAP — QFileDialog is not in the KEEP popup list.
- Main menu bar QActions (L18995–19016): UNWRAP — these are persistent menu bar items in MainWindow, not right-click popup menus. Rule 4 says "context-menu" specifically.
- Inline About/ReleaseNotes QDialog (L19050–19120): UNWRAP — enclosing class is MainWindow (not a listed modal dialog class).
- `_metric_card` tooltip args (L14907–14917): KEEP — the `tip` parameter is applied via `f.setToolTip(tip)` inside `_metric_card`.

**Placeholder scan:** No TBDs or placeholders found.

**Type consistency:** All edits are simple string unwraps — no type changes.
