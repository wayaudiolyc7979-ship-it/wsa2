# SPECTRA — 측정 알고리즘 / DSP 개요

> 이 문서는 SPECTRA(코드네임 WSA2)의 **측정·신호처리 알고리즘**을 한곳에 모은 참고서입니다.
> 아키텍처(오디오 엔진·렌더 패턴·탭 구조)는 `CLAUDE.md`에, 할일/이력은 `ISSUES.md`·`RELEASE_NOTES.md`에 있습니다.
> 전 코드는 단일 파일 `wayaudo2.py`(~21,600줄). 아래 `파일:줄` 앵커는 갱신되며 어긋날 수 있으니 **함수명으로 찾는 것**을 권장합니다.
> 표준: RTA/TF는 Smaart 계열 관행, 라우드니스는 ITU-R BS.1770-4 / EBU R128을 따릅니다.

---

## 0. 신호 취득 (공통)

- **공유 오디오 엔진** `AudioEngine`(`:1826`) — 물리 장치당 스트림 1개(`_DeviceStream`), 여러 탭이 `subscribe()`로 구독. `chunk_ready`(≈60fps, rolling `fft_size` 버퍼 — 스펙트럼용) / `raw_ready`(무스로틀 연속 프레임 — 적분·LEQ용) 두 신호를 방출.
- **Producer/Consumer 렌더** — 오디오 콜백은 **절대 페인트하지 않음**. 콜백은 결과를 `_pending`(QMutex)에 저장, 고정 **30fps QTimer**(`_render_frame` `:14103`)가 최신값만 뽑아 캔버스에 push(중간 프레임 드롭). 콜백 지터와 페인팅 분리 → 매끄러움.
- **격리 경로**(엔진 우회): 신호 발생기 출력(`_sig_stream`), TF 내부 루프백 듀플렉스(`TFDuplexThread` `:8761`).

---

## 1. 스펙트럼 분석 (Spectrum 탭)

### 1.1 파워 스펙트럼 — `power_spectrum_db(buf)` (`:838`)
단측(one-sided) 파워 스펙트럼 → 빈별 dBFS.
- **Hanning 윈도우** + 파워 보정 `Σw²`(≈0.375·n) 캐시(`_HANN_CACHE`).
- 정규화 `ps *= 2/(n·Σw²)`, DC·Nyquist는 ×2 제외. → **Parseval 정합**: 밴드 파워 합 = 실제 RMS 파워, FFT 해상도·윈도우 종류 무관.
- 기준: **풀스케일 사인 = −3 dBFS**(RMS 기준). Smaart 등 표준 RTA와 절대 레벨 일치.

### 1.2 옥타브 밴드 스무딩 — `_octave_bands(freqs, db, mode)` (`:860`)
빈별 dB → **IEC 61260 파워 합산** 옥타브 밴드.
- 모드: `oct3`(1/3), `oct12`(1/12), `oct24`(1/24). 밴드 폭 `bpo`.
- 밴드 경계 `fc·2^±(1/2·bpo)`, 그 안의 빈을 파워 합산. 빈이 없으면 인접 빈 선형보간.
- 밴드→빈 인덱스는 그리드별 캐시(`_OCT_MASK_CACHE`)로 매 프레임 마스크 재계산 회피.
- (MainWindow에는 동일 로직의 `_calc_oct`가 있고, 이 모듈판은 TF RTA용.)

### 1.3 캔버스
`FFTCanvas`(`:2123`, 선형 빈), `OctaveCanvas`(`:2588`, 밴드 바), `SpectrogramCanvas`(`:2966`, 시간-주파수 히트맵). Y축 dB 눈금은 짧은 패널에서 라벨을 최소 픽셀간격으로 솎아냄(그리드는 유지).

---

## 2. 전달함수 (Transfer Function 탭)

측정신호 M과 기준신호 R로부터 전달함수 **H = M/R**를 추정. 두 엔진 제공.

### 2.1 크로스스펙트럼 추정 (공통 수학)
프레임마다 R, M을 창가공 후 rfft → 누적 평균:
```
Sxy = M·conj(R)     (크로스 파워)
Sxx = |R|²          (기준 오토파워)
Syy = |M|²          (측정 오토파워)
H   = Sxy / Sxx                         ← 전달함수(복소: 크기·위상)
γ²  = |Sxy|² / (Sxx·Syy)   ∈ [0,1]      ← 코히런스(측정 신뢰도)
```
누적은 **지수이동평균(EMA)**: `acc = (1−α)·acc + α·new`.

### 2.2 응답(평균) 시정수 — 상승·하강 대칭 (Smaart식)
- `TF_AVG_SEC = [0.5, 1, 2, 4, 8]`초 (`:7912`) = Response 프리셋(Fast·Quick·**Normal 2초**·Smooth·Stable).
- **상승·하강 완전 대칭 EMA** — 레벨이 오를 때/내릴 때 같은 속도(비대칭 fast-release 폐지). 양 엔진 모두 `b=1−a; acc=b·acc+a·new`.
- 딜레이 변경 시 평균 재시드(`_reset_avg`)로 즉시 스냅.

### 2.3 엔진 A — Single (고정 FFT)
`_render_inner`(`:14128` 부근). 단일 FFT 크기로 R/M 크로스스펙트럼 EMA(`_cross_acc`·`_auto_acc_x`·`_auto_acc_y`). 균일 주파수 해상도.

### 2.4 엔진 B — Adaptive / MTW (멀티레이트) — `MTWEngine` (`:7992`)
Smaart식 **Multi-Time-Window** 이중 FFT. 저역 고해상도 + 고역 빠른 시간응답을 동시에.
- 스테이지 `s`는 샘플레이트 `sr/2^s`에서 동작(폴리페이즈 데시메이션 `resample_poly`). 같은 FFT 크기라도 낮은 스테이지 = 더 긴 시간창 = 저역 고해상도.
- 스테이지별 독립 `Sxy/Sxx/Syy` EMA. `α=1/n`을 `avg_target`까지 램프(~10프레임에 목표 도달).
- `result()`가 스테이지들을 **로그 그리드**(`F_MIN=10`~`f_max`, `n_out=800`)에 스티칭 — 각 대역은 담당 스테이지(저역=낮은 스테이지, 고역=높은 스테이지)에서 보간. `HI_FRAC=0.45`, `LO_FRAC=0.225`(스테이지당 1옥타브), 기본 `n_stages=8`·`n_fft=8192`.
- 순수 DSP + 누적상태(Qt 무관, 헤드리스 테스트 가능).

### 2.5 딜레이 시간영역 정렬 (Smaart식) — `_align_pair(ref, meas, D)` (`:13640` 부근)
딜레이는 **FFT 이전 시간영역에서 정렬**해야 크기·코히런스가 맞음(표시 위상만 회전하는 가짜 보정 아님).
- `D = round(delay_ms/1000·sr)` 샘플만큼 **ref를 지연**(앞에 0 채우고 길이 유지). `_on_frame`·`_extra_ffts`에서 FFT 전에 적용.
- 표시는 잔여(sub-sample) 위상만 `H·exp(j2πf·resid)` 회전(`_render_primary_H`).
- **결과**: 딜레이 넣는 순간 magnitude가 올바른 레벨로 딱 스냅(특히 MTW 고역 디코릴레이션 해소).
- ⚠️추가 측정카드는 내부 SigGen ref로는 안 돎(물리 REF 채널 필요).

### 2.6 임펄스 응답(IR) / ETC
- IR = `irfft(H)` 후 `fftshift`(또는 `np.roll(h, N//2)`)로 **0ms를 가운데로**. 딜레이 보정 시 `np.roll(h, D_al)`로 실제 도착위치 복원.
- **ETC**(에너지 타임 커브) = `_hilbert_env(x)`(`:10072`) 힐베르트 포락선 → dB.
- **Auto 딜레이 찾기** = IR/포락선 피크 위치 `argmax`(`:11194`)를 지연으로.
- 표시 모드: Lin(선형 진폭) / ETC / Log.

### 2.7 정밀 스윕 (Farina) — `farina_analyze(y, x, sr, T, f1, f2, ...)` (`:8191`)
지수 사인 스윕으로 **선형 IR과 고조파 왜곡을 분리** 측정.
- 스윕 `x(t) = sin[2π·f1·L·(e^{t/L} − 1)]`, `L = T/ln(f2/f1)` (`_gen_log_sweep` `:7969`, `:8107`).
- **역필터** = 시간역전 스윕 × +6 dB/oct 진폭 포락선(`:8121`) → `y ⊛ inv`가 선형 IR. 고조파(2~5차)는 시간축에서 앞쪽에 분리돼 나타남.
- 고정 분석창 `_FARINA_ANALYSIS_S=0.25`s·pre `0.05`s·tail `0.05`s → 스윕 길이와 무관한 IR 그리드.
- 스윕 결과를 라이브(핑크) Wiener(Meas/Ref) 레벨에 정합(`:8170`)해 겹쳐 비교 가능.

---

## 3. 스테레오 라우드니스 (Stereo Loudness 탭)

`LoudnessMeter`(`:16135`) — **ITU-R BS.1770-4 / EBU R128**.

### 3.1 K-weighting — `_KWeightFilter` (`:16109`)
2단 바이쿼드: **프리필터(고역 셸빙)** → **RLB(고역통과)**. 44.1k·48k 계수 내장(`_biquad` IIR, 상태 유지). 그 외 SR은 48k 계수 폴백.

### 3.2 라우드니스 값 — `LUFS = −0.691 + 10·log10(mean square)`
- **100ms 블록** 단위 K-weighted 평균제곱 누적. **채널 합** `z_L + z_R`(평균 아님 → BS.1770 정의, /2 안 함).
- **Momentary (M)** = 최근 4블록(400ms) 평균. **Short-term (S)** = 30블록(3s). 레이더용 fast-S = 5블록(0.5s).
- **Integrated (I)** — `_compute_I`(`:16212`): 400ms 블록에 **절대 게이트 −70 LUFS** → 그 평균 기준 **상대 게이트 −10 LU** → 게이트 통과분 평균.
- **LRA** — `_compute_LRA`(`:16223`): EBU 3342. 프로그램 전체 3s short-term 분포에 절대(−70)+상대(−20 LU) 게이트 → **P95 − P10**.
- **True Peak** — `_true_peak_db`(`:16157`): **4× 오버샘플**(`resample_poly`)로 샘플 사이(inter-sample) 피크 검출. 블록 경계 연속성 위해 직전 8샘플 테일 이어붙여 워밍업 제거. dBTP.
- 성능: I/LRA는 새 블록 완성 시(초당 ~10회)만 재계산 — raw 청크마다(초당 ~94회) 하면 장시간 구동 시 GUI가 큐를 못 따라가 멈춤.

### 3.3 표시
벡터스코프(L/R 리사주), 라우드니스 레이더(`StereoLoudnessPage` `:13653`), PLR/PSR(peak-to-loudness).

---

## 4. SPL / 캘리브레이션
- 광대역 SPL + **A/C/Z 가중**. 캘리브레이터(94/114 dBSPL) 기준으로 채널별 오프셋 산출(`Auto Offset`).
- LEQ(등가소음레벨) 적분, 알람(임계 초과), N4 리셋 등. `_SplPanel`.

---

## 5. 라이선스
- **Ed25519**가 라이브 스킴: 공개키 `_LIC_PUBKEY`(`:108`)로 검증, 개인키는 레포에 없음. `verify_license`(`:168`)가 Ed25519 → 실패 시 레거시 HMAC(`_LIC_SECRET`, 구키 3개) 폴백.
- 머신ID = 하드웨어 시리얼 SHA256[:12]. 발급: `generate_license.py`(CLI) / `wsa2_license_tool.py`(GUI).

---

## 6. 자주 쓰는 상수 / 앵커
| 항목 | 위치 |
|---|---|
| 앱 버전 `_APP_VERSION` | `:164` |
| TF 응답 시정수 `TF_AVG_SEC` | `:7912` |
| MTW 엔진 `MTWEngine` | `:7992` |
| Farina 분석 `farina_analyze` | `:8191` |
| 딜레이 정렬 `_align_pair` | `_on_frame`/`_extra_ffts` 내 |
| 파워 스펙트럼 `power_spectrum_db` | `:838` |
| 옥타브 스무딩 `_octave_bands` | `:860` |
| K-weighting `_KWeightFilter` | `:16109` |
| 라우드니스 `LoudnessMeter` | `:16135` |
| 힐베르트 포락선 `_hilbert_env` | `:10072` |

---

## 7. 검증
- 골든값 특성화 테스트: `tests/`(pytest) — 핵심 DSP 함수의 알려진 입력→출력 고정.
- 헤드리스 렌더 회귀: `python3 selfcheck.py` — 위젯 렌더 PNG + 로직 assert(`fmt_delay`·스무딩 등).
- 상세 결정·이력은 Claude 메모리 `~/.claude/projects/.../memory/`(TF 스무딩·딜레이 정렬·응답 대칭화·라우드니스 표준 등 `project_*.md`).

> 이 문서를 코드 변경과 함께 갱신하세요. 특히 §2(TF)·§3(라우드니스)는 표준 정합이 걸린 부분이라 수식/게이트 값 변경 시 반드시 반영.
