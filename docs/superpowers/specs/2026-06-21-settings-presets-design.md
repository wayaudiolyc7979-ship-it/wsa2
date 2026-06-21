# 설정 자동 기억 + 이름 프리셋 (3-탭 전체) — 설계

## Context

SPECTRA(`wayaudo2.py`)는 TF/Spectrum/Stereo Loudness 세 탭의 분석·표시 컨트롤(Engine, Response,
Smooth, view_mode, target 등)을 **재시작하면 전부 기본값으로 되돌립니다.** 장치/채널·일부 패널 상태만
`settings.json`에 저장될 뿐, 사용자가 맞춰둔 측정 방식은 매번 다시 설정해야 합니다.

사용자 요구:
1. **마지막 사용 값 자동 기억** — 다시 열면 지난 세션에 쓰던 모든 값이 그대로 복원.
2. **이름 프리셋** — 현재 전체 설정을 이름 붙여 저장하고, 나중에 불러오기.

확정된 범위(사용자 결정):
- **세 탭 전부** 대상
- 프리셋 = **전체 스냅샷**(한 이름 = 세 탭 설정 통째)
- 오디오 **장치/채널 포함**(불러올 때 있으면 적용, 없으면 현재 유지 = best-effort)

## Goals / Non-Goals

**Goals**
- 각 탭이 자기 컨트롤 값을 dict로 내보내고/받는 `get_state()/apply_state()` 한 쌍 제공.
- MainWindow가 세 탭 상태를 모아 `settings['session']`(자동기억) / `settings['presets'][name]`(프리셋) 저장.
- 변경 즉시(디바운스) 저장 → `os._exit` 종료에도 안전.
- 시작 시 지난 세션 자동 복원.
- 상단 헤더의 단일 Preset 컨트롤로 저장/불러오기/삭제.

**Non-Goals**
- 팝아웃 창 위치/크기, Run(실행) 상태는 스냅샷에 **미포함**(일시 상태).
- **캡쳐 곡선은 프리셋/세션 스냅샷에 미포함** — 단 이는 캡쳐를 버린다는 뜻이 아니라, 캡쳐는
  **기존 `captures.json` + `_restore_tf_captures`** 로 이미 독립 영속화되어 재시작해도 그대로 남기
  때문(이 기능이 전혀 건드리지 않음). 프리셋은 컨트롤 값만 담는다.
- 탭별 개별 프리셋(전체 스냅샷만).
- 기존 캘리브레이션(`calibrations`) 변경 없음(그대로 유지).

## Architecture

기존 인프라 재사용: `_load_settings()`/`_save_settings(data)`(`wayaudo2.py:357-367`),
`MainWindow.self._settings`(단일 진실원본), 탭들이 이를 공유.

### 1) 탭별 상태 직렬화

세 탭 각각에 순수 dict 입출력 메서드 추가. **apply는 키별 try/except** 로 best-effort(장치 부재·옛 프리셋에도 안 깨짐).

- **`TransferFunctionWindow.get_state()/apply_state(d)`**
  캡처: `eng_cb`,`fft_cb`,`avg_cb`,`sm_cb`,`ir_cb`,`phase_cb`,`unit_cb` (전부 `currentIndex`),
  제너레이터 종류(`sig_*_btn` 중 active)+`_sine_freq`/`_sweep_*`/`sig_lvl_sp.value()`,
  Ref/Meas/Out 장치+채널(`ref_cb`/`meas_cb`/`sig_out_cb` 등 — 이름 문자열로),
  `_tf_slot_plot`, `tf_panel_visible`, primary 딜레이.
  적용: 콤보는 이름/인덱스로 `setCurrentIndex`(→기존 `_*_changed` 핸들러가 상태 반영),
  장치는 이름 매칭되는 항목 있으면 선택(없으면 스킵).

- **`MainWindow.spec_get_state()/spec_apply_state(d)`** (Spectrum)
  캡처: `view_mode`(`_view_seg`), scale(`_scale_seg`), `sr_cb`, `avg_cb`, `peak_btn`/`hold_cb`,
  `db_cb`, `spd_cb`, `spectro_btn`, 입력 장치+채널(`dev_cb`/`in_ch_cb`).

- **`StereoLoudnessPage.loud_get_state()/loud_apply_state(d)` + MainWindow 토글 컨트롤**
  캡처: target(`_st_target_cb`), L/R(`_st_l_cb`/`_st_r_cb`), `_lu_btn`(LU모드), `_hero_live`(AVG/LIVE),
  입력 장치. (loudness 컨트롤은 page와 MainWindow 툴바에 분산 → MainWindow가 둘 다 모음.)

### 2) 전체 상태 (MainWindow)

```python
def _collect_app_state(self) -> dict:
    return {'tf': self.tf_win.get_state(),
            'spec': self.spec_get_state(),
            'loud': self.loud_get_state()}

def _apply_app_state(self, st: dict):
    # 각 탭 apply는 자체 try/except; 탭 단위로도 감싸 한 탭 실패가 전체를 막지 않게.
```

### 3) 마지막 값 자동 기억

- preset 관련 컨트롤들의 기존 시그널(`currentIndexChanged`/`toggled`/`valueChanged`/세그먼트 `changed`)에
  **`_mark_session_dirty` 슬롯을 추가 연결**(기존 핸들러는 유지).
- `_mark_session_dirty()` → 0.8s 단발 QTimer 재시작 → 만료 시
  `self._settings['session'] = self._collect_app_state(); _save_settings(...)`.
- **복원:** 앱 시작에서 탭 빌드 완료 후, `settings.get('session')` 있으면 `_apply_app_state(...)`.
  복원 중에는 `_restoring` 가드로 dirty 저장을 막아 피드백 루프 방지.

### 4) 이름 프리셋 + UI

- 저장소: `self._settings['presets'] = {name: app_state}`.
- **UI 위치:** 상단 헤더, Calibration 왼쪽. 컴포넌트:
  - `RoundComboBox`(프리셋 목록, 첫 항목 "—") — 선택 시 `_apply_app_state(presets[name])`.
  - **Save** 버튼 — 이름 입력(작은 입력 다이얼로그, 기존 다크 다이얼로그 패턴 재사용) →
    `presets[name]=_collect_app_state()`+저장+목록 갱신. 같은 이름이면 덮어쓰기 확인.
  - **삭제** — 목록 옆 작은 🗑(또는 "Manage…") → 선택 프리셋 제거.
- 시작 시 드롭다운을 `presets` 키로 채움.

## Data shape (settings.json 추가 키)

```jsonc
{
  "session": { "tf": {...}, "spec": {...}, "loud": {...} },     // 자동기억(지난 세션)
  "presets": { "클럽 튜닝": { "tf": {...}, "spec": {...}, "loud": {...} }, ... }
}
```
기존 키(`tf_*`, `spec_*`, `last_device`, `calibrations` 등)는 **그대로 둠**. session/presets는 별도 네임스페이스.

## Edge cases
- **os._exit 종료:** closeEvent 비신뢰 → 변경 즉시 디바운스 저장으로 커버.
- **장치 부재:** apply가 이름 매칭 실패 시 해당 콤보 스킵(현재 선택 유지).
- **옛/손상 프리셋:** 키별 try/except → 가능한 항목만 적용, 나머지 무시.
- **복원 루프:** `_restoring` 가드로 apply 중 dirty 저장 차단.
- **Run 상태/팝아웃:** 스냅샷 제외 — 불러와도 측정이 멋대로 시작/창 이동 안 함.

## Verification
1. `python3 -c "import ast; ast.parse(open('wayaudo2.py').read())"` 구문 게이트.
2. `python3 selfcheck.py` 13/13 유지 + (가능하면) `get_state→apply_state` 라운드트립 헤드리스 단언 추가:
   탭 위젯을 오프스크린 생성→값 세팅→`get_state()`→기본값으로 리셋→`apply_state()`→`get_state()`가
   동일한지 확인(전체 MainWindow는 segfault라 탭/위젯 단위로).
3. **격리 실행**으로 실제 저장 확인:
   `QT_QPA_PLATFORM=offscreen WSA2_SETTINGS_PATH=/tmp/s.json ...` 로 변경→`/tmp/s.json`에
   `session`/`presets` 키가 기록되는지 `Read`로 확인(사용자 실제 settings.json 절대 안 씀).
4. 사용자 실측: 값 바꾸고 재시작 → 복원되는지 / 프리셋 저장·불러오기·삭제 동작.

## 구현 순서(요약)
1. 탭별 `get_state/apply_state` (TF → Spectrum → Loudness).
2. MainWindow `_collect/_apply_app_state` + `_mark_session_dirty`(디바운스) + 시작 복원.
3. 헤더 Preset UI(드롭다운+Save+삭제) 배선.
4. selfcheck 라운드트립 체크 추가 + 격리 실행 검증.
