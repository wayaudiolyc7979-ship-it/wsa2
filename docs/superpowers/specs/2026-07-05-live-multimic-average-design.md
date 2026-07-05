# 라이브 멀티마이크 실시간 평균 (Live Multi-Mic Real-Time Averaging)

- **버전**: v1.9
- **작성일**: 2026-07-05
- **대상 파일**: `wayaudo2.py` (TransferFunctionWindow)
- **상태**: 설계 승인됨 → 구현 계획 대기

## 1. 목적

Transfer Function 탭에서 **여러 측정 카드(마이크)가 동시에 라이브로 돌아갈 때, 그 카드들을
실시간으로 평균낸 한 개의 곡선(AVG)** 을 그려준다.

두 가지 실사용 시나리오를 하나의 기능으로 커버한다(모드 전환):

- **공간 평균 (객석 커버리지)** — 마이크를 여러 위치에 두고 그 구역의 "평균 주파수 응답"을
  본다. 위치마다 거리·딜레이가 달라 위상이 제각각 → **크기(파워) 평균**이 표준.
- **반복 측정 노이즈 저감 (같은 위치)** — 위상이 일치 → **복소(벡터) 평균**이 맞다.
  기존 캡쳐 평균(`_do_tf_average`)과 동일 수학.

현재 상태: 라이브에서 카드들은 각각 별도 곡선으로만 그려지고 서로 평균되지 않는다.
캡쳐 평균(정적, 캡쳐 후)만 존재한다. 이 기능은 그 공백을 라이브로 메운다.

## 2. 비목표 (YAGNI)

- 가중 평균(카드별 가중치 슬라이더) — 하지 않음.
- 평균 결과의 자동 캡쳐 — 기존 캡쳐 평균 흐름으로 충분, 하지 않음.
- 서로 다른 fft_size/sample_rate 카드 혼합 — 공유 엔진이라 항상 동일. 방어적 interp만 유지.

## 3. 접근법 결정

세 가지를 검토하고 **A(카드별 최종 H 평균)** 로 확정.

| | A. 카드별 최종 H 평균 ✅ | B. 원시 크로스/오토 풀링 | C. 스무딩된 표시곡선 평균 |
|---|---|---|---|
| 방식 | 각 카드 복소 H(f)를 스무딩 전에 평균 | ΣS_xy/ΣS_xx 코히런스 가중 대평균 | 화면 mag/phase 배열 평균 |
| 엔진 호환 | Single·MTW 둘 다 (공통 freqs 그리드) | MTW 멀티레이트 단일 크로스/오토 없음 → 엔진 분기 | 둘 다 |
| 복소/위상 | 정확(정렬·복소평균 가능) | 가장 엄밀 | 위상 복원 불가 |
| 캡쳐 평균 일관성 | 동일 수학 | 다름 | 다름 |
| 복잡도 | 낮음 | 높음 | 최저 |

B의 코히런스 가중 이점은 크기 모드에서 γ² 평균 표시로 근사 대체한다.

## 4. 평균 수학 (매 렌더 프레임, 공통 `freqs` 그리드)

각 참여 카드 i에서 이미 매 프레임 계산되는 값 재사용:
- `H_i` — 복소 전달함수. primary = `_render_primary_H`의 `H_raw`,
  extra = `acc['cross'] / max(acc['auto_x'], 1e-30)`.
- `γ²_i` — 코히런스. primary/extra 동일 정의(`|cross|²/(auto_x·auto_y)`).
- `delay_i` (ms) — primary=`self.delay_ms`, extra=`_extra_pairs[i]['delay_ms']`.

### 크기 모드 (파워 RMS — 공간 평균 표준)
```
P_avg   = mean_i(|H_i|²)
mag_dB  = 10 * log10(max(P_avg, 1e-20))
coh_avg = mean_i(γ²_i)
phase/IR: 무의미 → AVG는 magnitude(+coherence) 캔버스에만. phase/IR 슬롯 비움.
```

### 복소 모드 (벡터)
```
정렬 ON:  H_i' = H_i * exp(+j·2π·freqs·delay_i/1000)   # 도착 딜레이 상쇄 → 응답 모양만 평균
정렬 OFF: H_i' = H_i
H_avg   = mean_i(H_i')
mag_dB  = 20 * log10(max(|H_avg|, 1e-10))
phase   = angle(H_avg) → wrap / unwrap / group delay
IR      = fftshift(irfft(H_avg, n=fft_size))
coh_avg = mean_i(γ²_i)
```

두 모드 모두 결과를 `_tf_smooth(freqs, H, self.smooth_bpo)`로 스무딩해 AVG 곡선 산출.
크기 모드는 위상이 무의미하므로 **위상 0인 복소 배열** `H_mag = sqrt(P_avg) + 0j` 를 만들어
`_tf_smooth`에 통과시키고, 반환값 중 `mag`(dB)만 사용한다(phase/grp는 버림). 이렇게 하면
스무딩 경로가 복소 모드와 동일해 코드가 단일화된다. `_tf_smooth`가 반환하는 `f_avg` 그리드에
`coh_avg`를 `np.interp`로 맞춰 커서 리드아웃(%)에 전달한다.

## 5. 참여 카드 선택

- primary 포함 **모든 카드 헤더에 "평균 포함" 토글**(작은 LED/체크, N2 스타일). 기본 OFF.
- 유효 참여 조건: `display ON` + 워밍업 수렴(`acc['n'] ≥ 3` / primary `_n_avg ≥ 3`).
- 유효 참여 카드 **2개 미만이면 AVG 곡선 숨김**(조용히; 힌트는 선택).

## 6. 렌더 훅 / 캔버스

- 수집 지점: `_render_extra_pairs` 직후(primary·extra H가 모두 준비된 시점)에 신규
  `_render_average(freqs, t_ms)` 호출. Single·MTW 경로 양쪽에서 호출.
- 신규 캔버스 API (기존 `set_tf_extra` 패턴 재사용):
  - `mag_cvs.set_tf_average(color, f, mag, coh)`
  - `phase_cvs.set_tf_average(color, f, ph_wrap, ph_unwr, grp)`  (복소 모드에서만)
  - `ir_cvs.set_tf_average(color, t_ms, h)`  (복소 모드에서만)
  - 크기 모드: phase/ir average 슬롯을 `clear_tf_average()`로 비움.
- 표시: 개별 곡선 위에 **굵은 실선(2.5px) + 전용 색** 오버레이. 점선 금지 규칙 준수.
- AVG 전용 색: 테마 대응 고대비 — 다크=흰색(`#FFFFFF`), 라이트=근검정(`#1A1A1A`).
  다색 개별 곡선 위에서 확실히 도드라지도록.

## 7. UI 컨트롤 (N2 스타일, TF 우측 패널 신규 "AVERAGE" 그룹)

`_n2_group_header('AVERAGE')` + 아래 컨트롤:
- `[AVG]` 마스터 토글 — 평균 곡선 on/off
- 모드 세그먼트 `[크기] / [복소]`
- `[평균만]` 토글 — 개별 곡선 숨김(또는 alpha↓), AVG만 표시
- `[딜레이정렬]` 토글 — 복소 모드에서만 활성, 기본 ON
- 카드별 "평균 포함" 토글은 각 카드 헤더에 위치(위 §5).

기존 N2 토큰/헬퍼(`_n2_group_header`, LED 토글, 세그먼트) 사용. 인라인 스타일 금지.
라이트/다크 양쪽 restyle 경로(`_restyle_sig_gen_theme` 인접)에 포함.

## 8. 상태 / 세션 저장

- settings 저장/복원: `avg_on`, `avg_mode`('mag'|'complex'), `avg_only`, `avg_align` +
  카드별 `in_average` 플래그(extra_pairs 저장 구조에 필드 추가, primary는 별도 키).
- `_diag('tf_avg_render', mode=, n=, aligned=, only=)` 상태 전이 로깅.

## 9. 상태·에러 처리

- 참여 카드 < 2 → AVG 숨김.
- 워밍업 미수렴 카드(n<3) → 평균에서 제외.
- 크기 모드에서 phase/IR 탭 → AVG 없음(개별만). 자연스럽게 처리, 별도 경고 없음.
- freqs 그리드는 항상 동일(공유 엔진). 방어적 `np.interp`만 유지.
- "평균만" 모드에서 유효 AVG 없음 → 개별 곡선 원복(빈 화면 방지).

## 10. 검증

- **selfcheck**: 합성 H 3~4개 입력 → (a) 크기 모드 = RMS 파워 평균 값 일치,
  (b) 복소+정렬 = 딜레이 상쇄 후 벡터 평균 값 일치 단위검증. AVG 렌더 PNG를 `Read`로 확인.
  새 위젯(AVG 그룹) `check()` 추가.
- **_diag**: `tf_avg_render` 로그로 라이브 동작 판정(사용자 캡쳐 요청 없이 로그 직접 확인).
- **HW (사용자, 인터페이스 필요)**: 실제 마이크 여러 개로 라이브 평균 —
  복소+정렬 시 콤필터(가짜 딥) 없는지, 크기 모드가 위치 평균 응답으로 보이는지 실측.
  내부 SigGen+맥 내장마이크로는 검증 불가(별개 마이크 위치 필요).

## 11. 영향 범위 / 리스크

- `_render_extra_pairs` 직후 훅 1곳 추가 — 기존 카드 렌더에 영향 없음(추가 오버레이만).
- 캔버스 3종에 average 슬롯 API 추가 — 기존 extra 슬롯과 독립.
- 성능: 프레임당 카드 수만큼 복소 연산 1회 + 스무딩 1회. 카드 수는 소수(≤8) → 무시 가능.
- 라이트/다크 restyle 누락 시 라이트에서 AVG 컨트롤 흐림 → restyle 경로 포함 필수(최근 회귀 패턴).
