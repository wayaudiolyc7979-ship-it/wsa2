# WSA2 / SPECTRA — 통합 할일 트래커 (★마스터, 한 곳 관리)

> 🚧 **활성 개발 버전 = v1.6** (2026-06-14~). 지금부터 들어오는 버그·새 기능은 전부 v1.6. v1.5는 태그로 보존된 체크포인트(`git checkout v1.5`). 소스 `_APP_VERSION='1.6'`로 bump 완료(미커밋).
> **모든 할일·버그·다음버전·문서·배포가 여기 한 곳에.** 떠오르면 맨 아래 `INBOX`에 막 적어두면 Claude가 분류해 위로 올림.
> 체크박스 `[ ]→[x]` 로 진행 관리. 각 항목 끝 `(상세: slug)` = Claude 메모리의 상세 문서(코드 위치/구현방법). 다음 세션 시작 시 이 파일 먼저 확인.
> 형식: `[버그]/[요청]/[검증]/[빌드]` + 한 줄 설명. 우선순위 = 위에서 아래로.

---

## 🎧 A. 내일 바로 — 하드웨어 실측 (회사 M4/외장 인터페이스 필요)

- [x] **캘리브 멀티채널 검증** — ✅✅**실측 검증완료(2026-06-16, M4 4채널)**. 채널목록 4행·채널전환·채널별 측정/오프셋 정상. **검증 중 버그 2건 발견·수정:** ①**오프셋 150 클램프** — `offset_spin.setRange(-30,150)`이 측정마이크 오프셋(보통 120~170dB)을 150에 잘라 전 채널 +150으로 표시 → `(-30,200)`로 상향(`wayaudo2.py:3150`). ②**단독 측정 시 분석창/라이브카드 같이 켜짐** — `_open_calib`이 정지상태에서 `_start()`(메인경로)를 켜 분석창·카드가 살아남 → **캘리브 전용 경량 스트림**(`_calib_start_measure/_calib_on_chunk/_calib_stop_measure`)으로 레벨만 측정, 캔버스/카드/트랜스포트 미터치. 분석 Running 중이면 기존처럼 in_ch_cb 전환(라이브 곡선도 전환). **TF 탭엔 캘리브 미적용 확인(정상)** — TF 매그니튜드=meas÷ref 상대이득(dB)이라 절대SPL 약분, 캘리브는 Spectrum/SPL미터 전용. 미빌드. *(상세: project_calib_channel_table_verify)*
- [x] **SPL Meter 실시간** — ✅기능 검증완료(2026-06-15, 내장마이크). 칸별 값 실시간 갱신·Max홀드·리셋·Fast/Slow·Clock 정상. Smaart SPL미터 A/B: **C Slow 0.9dB·1kHz톤 0.4dB 일치**. ⚠️A-가중만 별도 미결(아래 버그 항목). *(상세: project_spl_meter_layout)*
- [x] **[검토] SPL 미터 무음 시 카드 멈춤** — ✅**실측 확인: 문제 없음(2026-06-16, M4)**. 무음에서도 Z/FS Peak가 floor 정상 표시·라이브 갱신. 게이트(`dba_db>-100`)가 실사용 조건에선 안 거슬림 → 수정 불필요(현행 유지). *(코드리뷰 #2 종결)*
- [x] **[검증] 스펙트럼 절대레벨 ENBW 정규화 (Smaart A/B)** — ✅✅**실측 검증완료(2026-06-15, 내장마이크 A/B)**. `power_spectrum_db()`(`wayaudo2.py:377`, Hanning 윈도우파워 Σw²+단측×2 → 밴드 파워합=실제 RMS/Parseval). **Smaart 나란히(같은 내장마이크, 둘 다 Cal Offset 128, 1/12, 16FIFO): ①형태 — 핑크노이즈·1kHz톤 컨투어 일치 ②절대값 — SPECTRA dBA/dBC 86.0 vs Smaart SPL A/C Slow 85.6 = 0.4dB 일치(측정불확실성 내). 캘리브 조정 불필요.** RTA 커서는 Smaart 밴드센터가 ISO고정(1.03kHz)이라 톤피크 빗나가 부정확 → 안정된 SPL미터로 비교가 결정적. ENBW 정규화 Smaart 대비 실측 정합 증명.
- [x] **인풋 카드 레벨미터 외장 검증** — ✅✅**실측 검증완료(2026-06-16, M4)**. 외장 인터페이스에서도 빌트인과 동일하게 채움/색/피크 정상 표시. `_MiniMeterBar` DB_MIN −84dBFS 그대로 OK, 재조정 불필요.
- [ ] ⏭️**[다음 검증 = 여기부터]** **TF 카드 레벨바 통일** — 코드 구현완료(`_HorizBarVU`=`_MiniMeterBar`룩), **실측 검증만 남음**. TF탭 Start→ Meas 카드바 ①채움 이동 ②초록→노랑(−9)→빨강(−3) 색전환 ③peak tick + Reference VU 바(`_ref_vu_bar`) 동일 확인. *(상세: project_v1_2_verify_checklist)*
- [ ] **트랜스포트 블루/레드 틴트** — 전 탭 Start(블루)/Stop(레드) 실동작+색변화(초록 제거 확인). 카드 Start 포함.
- [x] **라이선스 활성화 UI 육안** — ✅✅검증완료(2026-06-15). 새 키 발급→앱 LicenseDialog 활성화 OK.
- [x] **레거시 HMAC 키 활성화 확인** — ✅✅검증완료(2026-06-15). 듀얼검증 OK.
- [ ] (보너스) **TF 제너레이터 채널버그 재현** — 4in4out으로 재현 + 로그의 시작 장치목록에서 그 인터페이스 `in=?` 확인(8채널 의문 해소).
- [ ] (보너스) **USB idle 핫플러그 재현** — 측정 안 한 상태로 뽑/꽂 → 로그 뽑기(재초기화 후 장치목록 이제 찍힘).

## 🖥️ B. 내일 바로 — 앱 재시작/육안/빌드 확인 (신호 불필요)

- [x] **About 화면** — ✅✅검증완료(2026-06-15). License 버튼→SPECTRA 마크+버전 1.6+머신ID, 다크/라이트 둘 다 가독성 OK, Copy Machine ID 동작 확인. *(상세: project_v1_5_verify_checklist)*
- [x] **엠프티 스테이트** — ✅✅검증완료(2026-06-15). Start 전/Stop 후 중앙 SPECTRA 웨이브 마크+"Press Start to begin". **검증 중 버그 발견·수정:** `_start()`가 `_idle_hint=False`로 끄는데 `_stop()`이 다시 안 켜서 한 번 Start하면 영영 안 뜨던 것 → `_stop()` 캔버스 clear 직후 `fft_cvs._idle_hint=True; oct_cvs._idle_hint=True` 복귀(`wayaudo2.py:14000`). 옥타브 확인, FFT 동일 메커니즘.
- [ ] **DisplayName (.app)** — 빌드된 .app이 메뉴바/Dock에 "SPECTRA"로 뜨는지(소스실행 말고 .app).
- [x] **UI 개선 #1~5 육안** — ✅✅검증완료(2026-06-15). #1 네이티브 메뉴바·#2 Stereo 하단 메트릭바 토글·#3 캡쳐 토스트·#4 단축키 툴팁·#5 TF 엠프티 전부 정상. (#6 드롭도 ✅완료)
- [x] **팝아웃 풀스크린** — ✅✅검증완료(2026-06-15). 라우드니스/벡터스코프 팝아웃→풀스크린 Space 튐 없음. *(상세: project_popout_fullscreen_fix)*
- [x] **GUI 육안 묶음** — ✅검증완료(2026-06-15). 팝아웃 아이콘 / 툴바 3탭 동일 / 축 dB라벨 / 다이얼로그 통일 / 라이트·다크 가독성 육안 OK. *(상세: project_v1_2_verify_checklist)*

## 🛠️ C. v1.6 신규 기능 (코드 작업, 하드웨어 불필요 — 아무때나)

- [x] **[기능] 캡쳐 리캡쳐(제자리 다시 캡쳐)** — ✅✅**실앱 검증완료(2026-06-16)**. 기존 캡쳐의 **색/이름/그룹/가시성 유지하고 곡선 데이터만 현재 라이브로 덮어쓰기**. **트리거 = ①행 우클릭 "다시 캡쳐 (Recapture)" ②단축키 R**(선택 캡쳐, 없으면 마지막 / Space=새 캡쳐와 짝). 구현: 각 캔버스에 `recapture()`(FFT/Oct)·`recapture_live()`/`recapture_data()`(TF mag/phase/ir) 추가 — **같은 dict 객체를 유지해 메타 자동 보존**, 데이터 키만 교체. TF는 `_recapture_tf(idx)`가 `_tf_captures[idx]['source']`(primary/cardN)에 따라 3캔버스 동시 갱신. 드로어 시그널 `recapture_requested(mode,idx)` → `_on_drawer_recapture`(spec=fft_n 분기, tf 위임)·R은 `_recapture_selected`. 오프스크린 5캔버스 검증 PASS(제자리·메타보존·데이터갱신·범위밖 False). 미빌드.

- [x] **[기능] SPL 미터 측정 소스 선택** — ✅✅**실측 검증완료(2026-06-16, M4)**. SPL 미터가 primary 채널에만 하드코딩돼 있던 것 → **SPL 설정창(⚙)에 "측정 소스" 드롭다운** 추가, 입력 카드(primary+추가 소스) 중 선택. 선택 소스만 `push_levels`로 라우팅: primary는 `_spl_source_id==0`일 때만 push, 추가 소스는 `_process_extra_source`에서 선택 시 `_spl_inputs`(A/C가중+fs_peak, 소스SR기준 캐시 가중테이블)로 계산해 push. **소스별 calib**(device:ch 조회)도 창에 반영. 카드 삭제 시 primary로 자동 복귀. 오프스크린: `_spl_inputs`=primary경로 Δ0 일치, 셀렉터 매핑 PASS. ⚠️미영속(재시작 시 primary로) — 필요 시 추후 추가. 미빌드.
- [x] **[기능] SPL 임계 알람 — 독립 창** — ✅구현완료(2026-06-16, 스크린샷 승인·실앱/하드웨어 미검증·미빌드). **SPL 미터와 무관한 완전 독립 창**(`SplAlarmWindow`, `wayaudo2.py` SplMeterWindow 위에 정의). **View 메뉴 → "SPL 알람 창"** 으로 직접 열림. 마스터 지표 1개를 한계와 비교해 **초록(여유)→노랑(한계 -N dB 접근)→빨강(초과, 0.4s 깜빡임 + "N초째")**. 창 크기에 맞춰 스케일되는 큰 중앙정렬(3구 신호등 글로우 + 거대 숫자 + /한계 + ▼여유/▲초과 + 하단 상태). **자체 오디오 엔진**(`_SplMetricEngine`: Fast/Slow EMA + LEQ적분 + 피크홀드, SplMeterWindow와 동일 계산식)을 소유해 **SPL 미터 안 열려 있어도 동작** — `_process_audio`가 spl_meter 급전과 별개로 `spl_alarm_win.push_levels(primary)` 직접 호출(다른모니터/구석 FOH 글랜스용). **자체 ⚙ 설정**(타이틀바, `SplAlarmConfigDialog`: 마스터 지표·한계·노랑 여유·LEQ time), `_settings['spl_alarm']`에 영속. 기본 LAeq/100dBA/-3dB. calib=primary(`_apply_calib_thresholds`에서 동기화), 테마 토글·앱 종료 정리 연결. 오프스크린: 엔진 laeq=98.40 정확 + 창 급전→tick→display 일치 + 3상태 렌더 PASS. **이력**: 처음엔 SPL미터 내장 바(`_SplAlarmBar`)+설정 종속 팝업으로 구현(반응형 겹침수정 포함)했으나, 사용자 요청 "아예 별도 창"으로 **독립 창 재설계**(내장 바/팝업체크박스 폐기, `git checkout 60c8321 -- wayaudo2.py`로 알람코드 리셋 후 재구현). **영어화+지표표기(2026-06-16, 사용자 요청)**: 창/메뉴/설정/상태문구 전부 영어(SPL Alarm·OK Safe·AMBER Ease off·OVER Ns·"X dB headroom"·"+X dB over"). 단위를 **선택 지표대로** 표기(`_UNIT`): laeq→"dB LAeq"·lceq→"dB LCeq"·dba→dBA·dbc→dBC·spl→dB SPL·peak/fs_peak 등, **LEQ 지표는 적분 분(min) 덧붙임**("/ 110 dB LAeq 10min"). 메뉴 "View → SPL Alarm". 3케이스 렌더 PASS. **글랜스 동작 추가(2026-06-16, 사용자 요청 — 미터·알람 둘 다)**: ①**always-on-top**(`Qt.WindowStaysOnTopHint`, 본화면 위 무조건 — 프레임리스 유지 위해 _apply_dark_titlebar 前에 OR) ②**마우스 떠나면 카드만**(`_glance_chrome_update`: 200ms 타이머에서 `geometry().contains(QCursor.pos())`로 판정해 `_dark_titlebar`/`_dark_grip` 표시·숨김 — 자식 위젯 enter/leave 영향 안 받는 전역커서 방식, 숨겨도 창 외곽크기 불변→카드만 꽉 참). 오프스크린: 플래그·호버 토글 PASS. **다음**=실앱 육안(노랑→빨강 전이·깜빡임)+소리 알람 옵션+View 메뉴 위치 확인. 더 큰 그림은 G의 SPL 컴플라이언스 로드맵. *(체크포인트 커밋 60c8321)*
- [x] **캡쳐 일괄 표시/숨김 토글** — ✅✅**실앱 검증완료(2026-06-15, A1~A4 통과)**. 전체 토글(SPECTRA 그라디언트 웨이브 아이콘, 제목 왼쪽)+그룹별 토글(× 왼쪽), 스마트 토글. 새 브랜드 아이콘 `_wave_toggle_icon`(ON=그라디언트 / OFF=회색+사선). 오프스크린 렌더+로직 테스트 통과. *(상세: project_todo_capture_bulk_visibility)*
- [x] **캡쳐 색상 구분 (라이브 회피 + 캡쳐끼리 구분)** — ✅✅**실앱 검증완료(2026-06-15)**. `_auto_capture_color`를 **farthest-point 팔레트**(`_capture_palette`)로 재작성: 라이브 8색을 시드로 색공간에서 최원점 선택 → 라이브와도(최소 RGB 76) 캡쳐끼리도(22개 최소 73, 기존 11) 최대 구분. 다크/라이트 밝기 하한. ~~hue±20만~~/~~점선~~ 폐기. ⚠️기존 캡쳐는 옛 색 유지(재캡쳐 또는 재배치 필요). *(상세: project_todo_capture_color_avoidance)*
- [x] **캡쳐 타겟 그룹 유연화** — ✅✅**실앱 검증완료(2026-06-15)**. 그룹에 갇혀 캡쳐되던 문제 해결. 그룹 헤더 **이름 클릭=새 캡쳐 타겟 지정(◉ 하이라이트)**, 재클릭=미지정 복귀, **화살표=접기 분리**, 탭바 아래 **"캡쳐 위치" 칩**(클릭 시 미지정). 새 시그널 `capture_target_changed`, 활성 타겟 `_target` dict(기존 `_pending_group` 흡수). 렌더+로직 테스트 통과. *(상세: 플랜 luminous-sauteeing-widget.md)*
- [x] **딜레이 파인더 단축키 개선** — ✅✅**실앱 검증완료(2026-06-15)**. TF 딜레이 파인더(L) 창에서 **L=다시 탐색(Find Again), Enter=딜레이 적용(Insert All)**. 버튼 autoDefault 끔 + 힌트 라벨 괄호표기 `(Enter)`/`(L)`. `AllDelayFinderDialog.keyPressEvent`. 키 라우팅 테스트 통과.
- [x] **스펙트럼 FFT 브랜딩 + 곡선 부드럽게 + 커서** — ✅구현완료(2026-06-15). FFT 곡선·채움 모두 SPECTRA 그라디언트(저역파랑→고역빨강, `_spectra_grad_pen`/`_brush`/`_SPECTRA_GRAD_STOPS`). 초록 채움 폐기→그라디언트 채움(alpha 40, dim 16). 클리핑 시 빨강 유지. **⚠️함정: `_front_id==0` front 재그리기가 초록 line_col로 덮던 것 발견→그것도 그라디언트화.** 시인성: 선 AA+float좌표(계단제거). **커서 십자선: 가로선을 마우스Y→곡선값 위치로(매그니튜드 방식, `_draw_live` 커서부).** 전체화면 버벅임: ①채널 없을 때 front 재그리기 스킵 ②**그라디언트 채움을 캐시 픽스맵+clip blit로**(픽셀별 그라디언트 계산 제거 — "소리 크면=면적 큼=더 버벅"의 근본원인, `_grad_fill_pixmap`). 전부 실렌더 검증. ③**글로우 밴드 채움**: 큰소리=채움면적이 화면 채움이 근본원인(로그상 오디오 xrun 0=순수 렌더 프레임드롭). 채움을 선 아래 고정높이(BAND 72px) 밴드로만 →면적이 음량과 무관하게 일정→전체화면/큰소리 가벼움. 사용자 선택(글로우밴드). ④글로우밴드로도 잔여 버벅임→**선 AA OFF**(float좌표라 계단현상 없음). 렌더 1.51→0.97ms(Retina선 차이 더 큼). 채움(밴드)+선 모두 AA 미사용. 잔여 시 다음=fps↓ 또는 MAX_POINTS↓.
- [x] **[성능] 첫 캡쳐 느림** — ✅✅검증완료(2026-06-15). farthest-point 색 팔레트가 첫 캡쳐 때 순수 파이썬 이중루프로 계산돼 수백ms~. numpy 벡터화(`_capture_palette`)로 **1.7ms**, 색 결과 동일(결정론).
- [x] **[UX] 캡쳐 패널 선택 표시 안 됨** — ✅✅검증완료(2026-06-15). 패널이 항상 마지막 캡쳐만 강조(`front_idx=len-1`). 드로어가 클릭한 캡쳐(`_sel`) 추적→그 행 강조(좌측 액센트 바+볼드+배경). 추가/삭제 시엔 마지막 자동. 그래프(canvas front)는 기존대로.
- [x] **[버그] 캡쳐 전체 숨김 시 라이브 곡선 흐리게 남음** — ✅수정(2026-06-15, 검증중 발견). 포커스(_front_idx)된 캡쳐가 숨겨져도 `_cap_focus=True`라 라이브가 dim 유지되던 것. `_cap_focus`를 "포커스 캡쳐가 visible일 때만"으로 가드. FFT/oct/TF(mag/phase/ir) 6곳 전부. 로직 테스트 통과.
- [x] **[버그] 스펙트럼 소스 카드 해제해도 곡선 표시됨** — ✅수정(2026-06-15). 첫 실행 시 카드 가시성 해제 상태인데 `set_channel_data`가 새 채널을 항상 visible=True로 만들어 곡선이 나타나던 것. 캔버스에 `_ch_visible` 영속 맵 추가(데이터 도착 전에도 유지), `set_channel_visible()`로 통일, 카드 빌드 시 동기화. FFT+oct 둘 다. 4케이스 테스트 통과.
- [x] **라이트 모드 캡쳐 패널 검정 잔재 수정** — ✅구현완료(2026-06-14). 라이트에서 헤더 버튼(wave토글/Avg/Export/+Grp)·행 체크박스·R버튼·구분선이 다크로 남던 것 테마화. `_CaptureDrawer._restyle_chrome()` 신설(헤더버튼) + `_make_row` 체크박스/구분선 테마분기(다크 동일) + `_apply_theme`가 토글 시 `_restyle_chrome()`+`_redraw()` 호출 + `#capScroll` 배경 테마화. 다크 회귀 없음(렌더 확인).

- [x] **[결정: 수용] 전체화면 상단 메뉴바가 헤더 가림** — macOS 전체화면 hover 시 메뉴바/타이틀바 reveal이 SPECTRA 헤더(NSFullSizeContentView) 덮음(OS 표준, 마우스 뗄 때만 잠깐). 상단 여백 시도→노치맥 검은 띠 커서 더 어색→되돌림. **사용자 결정 A: 현재대로(띠 없음, brief 표준 cover 수용)**. 추후 원하면 풀스크린 메뉴바 always-visible 네이티브 방식 재검토.
- [x] **LEQ 시간 미터 + 리셋** — ✅✅구현+실앱 검증완료(2026-06-15). SPECTRA 그라디언트 진행 바(`_GradTimeBar`, 전폭 그라디언트를 진행도만큼 노출)+리셋 버튼(↻=적분버퍼 비움)을 **LAeq/LCeq 카드 회색 바탕 안**에 배치(`_SplPanel.reset_time_requested`/`set_time_progress`). dBA/dBC 카드엔 없음. 진행도=쌓인시간/`_leq_secs`. **숫자(경과시간) 표시 제거**. 창은 컴팩트 최소 크기로 열림(`_open_w/_open_h`). 렌더 테스트 통과(laeq/lceq만 바 표시, 30s→50%). 리셋 아이콘=둥근 화살표(`_draw_reload_arrow` 공용 헬퍼, 거의 꽉 찬 원+삼각 화살촉)로 통일 — 카드 버튼은 위젯에 직접 그리는 `_ReloadBtn`(정사각 18×18, QIcon 스케일 찌그러짐 방지), 타이틀바 Reset Max(`_ResetMaxBtn`)도 동일 글리프로 일관화(2026-06-15).
- [x] **[버그] 소스 이름변경 입력칸이 카드 밖으로 넘침** — ✅수정완료(2026-06-15). `begin_inline_rename`이 폭을 `max(label_w+60,100)`로만 잡아 카드(host) 오른쪽 경계를 무시 → 파란 입력칸 삐져나옴. `w=min(w, host.width()-tl.x()-6)`로 클램프(6px 우측 여백). Spectrum/TF 인라인 리네임 공통. 오프스크린 폭 110~200 전 구간 카드 내부 유지 확인.
- [x] **[버그] 팝아웃 창 흰색 타이틀바** — ✅수정완료(2026-06-15). 벡터스코프/라우드니스 레이더 팝아웃(`_make_popout_win`)이 네이티브 흰 타이틀바였음 → `_apply_dark_titlebar(win, resizable=True)` 적용(프레임리스+다크바+✕+우하단 리사이즈 그립). 닫기=`win.close()`→기존 closeEvent로 도킹 복귀 유지. 렌더 검증(frameless·_dark_titlebar·grip·제목 'Vectorscope' 확인).
- [x] **SPL 미터 지표 확장(Smaart 세트)** — ✅✅구현+실앱 검증완료(2026-06-15). `_METRICS`에 spl_slow/dba_fast/dbc_fast/spl_fast/peak/peak_c/fs_peak 추가(+기존 dba/dbc 라벨 'SPL A/C Slow'로). 스펙트럼 처리부(`_process_audio`)가 순간 calibrated Z(=raw_dbfs+calib)/A(raw_dba)/C(raw_dbc) + 풀스케일 디지털 피크(fs_peak=20log10 max|buf|)를 `spl_meter_win.push_levels()`로 전달. SPL Meter가 dt기반 EMA로 Fast(τ125ms)/Slow(τ1s) 계산 + 피크 홀드(6dB/s 감쇠), LEQ버퍼는 Slow A/C 사용(기존 laeq/lceq 유지). peak=디지털피크+calib, peak_c=C가중 최대홀드(근사), fs_peak=dBFS(캘리브 무관, -6/-1 임계). `_SplPanel`: peak/peak_c/fs_peak는 Max행 숨김. 합성피드 검증(12지표 값·다이얼로그 12옵션·렌더 OK). 사용자선택=전체세트. ⚠️Peak/Peak C는 시간영역 가중 참피크 아닌 근사 — 하드웨어 실측 시 재확인.
- [x] **SPL 미터 시계 카드(선택형)** — ✅✅구현+실앱 검증완료(2026-06-15). `_METRICS`에 `'clock':('Clock','#5AC8FA')` 추가 → 설정 다이얼로그(`SplLayoutDialog`)가 `_METRICS` 자동 나열하므로 칸별 선택지로 바로 노출. `_SplPanel`: clock이면 Max행(dot/max_lbl) 숨김 + `set_clock(text)`로 값라벨에 시각, `reset()`은 clock 스킵. `_update_display`: 매 틱(200ms) `time.strftime('%H:%M')`(24h)로 clock 패널 갱신(오디오 없어도 동작), dB 값 루프에선 clock continue. 렌더 검증: clock 카드 '11:47' 표시·Max숨김, 다이얼로그에 'Clock' 옵션 확인.
- [x] **SPL 카드 Smaart식 스케일링** — ✅✅구현+실앱 검증완료(2026-06-15). 좁고길게/넓게 모두 카드가 폭 꽉 채움+너비 따라 숫자 커짐+세로중앙+클리핑 없음 육안확인. 리사이즈 동작을 Smaart SPL Meters처럼: **카드가 셀을 꽉 채우고(양옆 여백 0) + 숫자는 너비 기준으로 크게 스케일 + 세로 중앙 정렬**. (1차 "카드 비율 고정(레터박스)"은 양옆 검은 여백이 어색해 폐기.) `_SplPanel`: `paintEvent`는 셀 전체(`self.rect()`)에 카드 렌더, 레이아웃에 value 위·아래 `addStretch`로 세로 가운데, `_relayout`은 `scale=min(w/_BASE_W, h/_fit_h)`(너비 주동인 + 높이 상한 클램프, `_fit_h` 일반92·leq116). `_inner_rect`/`_aspect` 제거. 열림 크기 `_open_w=150*cols`/`_open_h=150*rows`(좁고 길게). 렌더 검증: 좁고길게/넓게/넓고낮게 모두 폭 꽉 채움+너비 따라 숫자 커짐, 클리핑 없음. 사용자 선택=너비 기준(Smaart식).
- [x] **릴리즈 노트 메뉴** — ✅✅**실앱 검증완료(2026-06-15)**. Help 메뉴에 "릴리즈 노트 (Release Notes)" 추가 → 클릭 시 브랜드 창(다크+그라디언트 라인+QTextBrowser)에 RELEASE_NOTES.md 렌더. 경량 md→html(`_md_to_html`: ##/-/​**​/`code`/링크정리). 빌드 3종 spec에 RELEASE_NOTES.md datas 추가. 렌더 확인.
- [x] **팝업 다이얼로그 브랜딩** — ✅✅**실앱 검증완료(2026-06-15)**. 시스템 QMessageBox(흰 타이틀바+시스템 아이콘) → SPECTRA 브랜드 다이얼로그(`_brand_msg`/`_BrandBox` 드롭인): 다크+상단 그라디언트 라인+라인 아이콘(info=파랑 / warn=주황△ / question=?)+브랜드 버튼(위험=빨강 `ss_btn_danger`). info/warning ~25곳 sed 일괄 치환 + Delete All confirm. 실렌더 확인. 사용자 선택=B(라인 아이콘).
- [x] **[버그] 다이얼로그 이중 타이틀바** — ✅✅검증완료(2026-06-15). `_TFAverageDialog`·`LicenseDialog`가 `_apply_dark_titlebar`(프레임리스) 뒤에 `setWindowFlags` 재호출→네이티브 프레임 되살아나 타이틀바 2개. setWindowFlags 제거(고정크기는 setFixedSize로). TF Average는 그라디언트 라인+힌트+테마 체크박스로 재디자인.
- [x] **[기능] 제네레이터 Sine(사인파) 추가** — ✅구현완료(2026-06-15, 실앱검증 대기). TF 제네레이터에 Pink/White/**Sine**/Sweep. Sine 버튼 클릭→`SineConfigDialog`(주파수 10~24000Hz)→Apply 시 버튼에 주파수 표기('Sine 1k'). 재생 버퍼는 **정수 사이클 사인**(`_n_sine=sr*10`, k=round(f·n/sr) 사이클 → 루프 이음새 클릭 0, 오프스크린 검증: 주파수 오차 0Hz·seam~1e-13·진폭1.0). 레벨은 기존 Level 컨트롤 공용. 버튼 상호배제·Cancel복원·File로드 동기화 전부 반영. Sweep 전용 1-shot 캡처 로직은 미접촉(Sine은 Pink/White처럼 루프 재생 경로). dBA 극저역 격리테스트(50/100Hz 톤)에도 바로 활용 가능. 상태변수 `_sine_freq`.
- [x] **캡쳐 우클릭 Delete All** — ✅✅**실앱 검증완료(2026-06-15)**. 캡쳐 패널 행/빈공간 우클릭 → **Delete All**(영어), 확인 다이얼로그 후 현재 탭 전체 삭제. 드로어 공유라 **Spectrum/TF 동일**. 시그널 `delete_all_requested`, 핸들러 `_on_drawer_delete_all`(spec=fft+oct, tf=mag/phase/ir+_tf_captures, Δ기준 해제). 드로어 emit 테스트 통과.

## 🐛 D. v1.6 버그 수정 (코드) — 🏢 내일 사무실에서 (하드웨어 검증 필요)

- [ ] **[버그] TF 제너레이터 출력 채널 변경 미반영** — 재생 중 Out채널(3+4) 바꿔도 스트림 재시작 안 함(`sig_out_ch_cb` 8217/`sig_out_ch2_cb` 8110이 save만). Ref/Meas 바꿔야 반영. **수정: 출력채널 콤보를 "저장+재생중이면 재시작" 핸들러에 연결**(장치변경 8478-8479 로직 재사용). 임시회피=채널 바꾼 뒤 Stop→Play. *(상세: project_bug_tf_sigout_channel_no_reconfig)*
- [ ] **[버그] USB idle 핫플러그 안 잡힘** — 실행 중 뽑/꽂 시 인터페이스 안 보임, Refresh 무효, 앱재시작만 됨. 근본=CoreAudio device-change 리스너 없음. **수정: 시작 시 CoreAudio 알림 리스너 등록**. ⚠️HW검증 필요. *(상세: project_bug_usb_idle_hotplug_coreaudio)*
- [x] **[해결·버그아님] dBA가 Smaart比 낮음 — SPECTRA가 정확한 쪽으로 확정** — ✅✅**단위테스트로 종결(2026-06-15)**. 실제 코드 함수(`power_spectrum_db`+`a_weight_db`+`_process_audio`의 dBA 합산 `Σ10^((db_raw+aw)/10)`)를 그대로 떼서 순수 톤 주입 → **dBA−Z가 IEC A-가중 이론값과 전 주파수 0.04dB 이내 일치**(50Hz: −30.23 vs −30.27, 100Hz: −19.13 vs −19.14, 250Hz: −8.68, 1kHz: 0.00). **SPECTRA dBA = IEC 표준 그 자체, 버그 없음.** ⇒ 내장마이크 A/B에서 LF 지배 신호일 때 Smaart가 A를 ~7dB 높게 읽은 건 SPECTRA 결함 아님(추정: Smaart 시간영역 A-가중 IIR의 극저역 오차 / 노트북 스피커 음향오염=순수톤 아님). dBC−dBA도 SPECTRA가 이론값에 더 가까움. **참고: Z 절대레벨·C가중·1kHz톤·미드지배 A는 모두 Smaart와 0~0.4dB 일치(이미 검증).** 추후 원하면 캘리브 측정마이크+기준 SPL미터로 재확인 가능하나 계산은 증명 완료. *(상세: [[project_spl_meter_layout]])* — 드라이버 보고값(`max_input_channels`) 추정. A의 재현+로그로 먼저 판별 후 결정.

## 📄 E. 문서

- [ ] **MANUAL.html 스크린샷** — 탭별 실제 캡쳐 docs/img/*.png 덮어쓰기 → 번호 콜아웃 완성. *(상세: project_todo_manual_screenshots)*
- [ ] **README.md 작성** — 깃허브 대문(소개·기능·설치·빌드·문서링크), 민감정보 주의. *(상세: project_todo_readme)*
- [ ] **LANDING.html 디테일** — 앱 미리보기 교체·다운로드/문의 링크·가격(배포방향 정해지면). *(상세: project_todo_landing_details)*
- [ ] **문서 내용/오타 검토** — MANUAL/LANDING/RELEASE_NOTES 맥 브라우저로 열어 문구·디자인·링크 확인.

## 📦 F. 배포 / 빌드 / 보안

- [ ] **윈도우 빌드 검증** — v태그 push→GitHub Actions(windows-latest) 산출물이 **SPECTRA.exe**·아이콘·속성(1.5.0.0/WAYAUDIO)인지. *(상세: project_verify_iphone_session)*
- [ ] **코드서명 + 노타라이즈** (⏸️"나중에" 보류) — Developer ID 인증서·노타리 프로필. 배포 전 처리. *(상세: project_v1_5_verify_checklist C)*
- [ ] **소스코드 보호/난독화** — Nuitka(전면 컴파일) 또는 PyArmor 택1. `_LIC_SECRET` 노출방지 중요. 빌드 3종+Actions 교체 필요. *(상세: project_todo_code_protection)*

## 💤 G. 나중에 / 우선순위 낮음

- [ ] `[차별화/v1.7+]` **SPL 컴플라이언스 풀세트** — 신호등 알람 바(✅완료, C섹션)에 이어 ①**디스크 로깅**(LAeq/LCeq/LAFmax/LCpeak 시간스탬프 CSV, 캡쳐 Export writer 재활용) ②**SPL 히스토리 그래프**(시간축 dB, 라우드니스 레이더의 분/시 스케일판) ③**리포트**(세션 요약 PDF/PNG+CSV, 한계 준수/초과횟수). 공연장 소음규제(DIN 15905-5 등) 준수 증빙 → "라이브 튜닝"에서 "컴플라이언스 측정기"로 시장 확장. 엔진(dBA/dBC/LEQ/Peak)·CSV/PNG Export·색임계는 이미 있음 → "기록·표시·출력 껍데기"만 신규. Class 1/2 법적정확도는 캘리브 마이크+검증 별도.
- [ ] `[차별화/v1.7+]` **MTW 멀티해상도 측정** — 라이브 연속측정 해상도를 Smaart급으로(저역 긴창/고역 짧은창 동시→전대역 균일 points/octave). **모드 토글로 추가**(단일FFT 폴백 유지). ⚠️측정 심장부 작업+하드웨어 A/B 검증 필수, CPU 부담 체크. **지금은 안 함**(서명·보호·버그·정확도증명이 우선). 정밀측정은 이미 스윕 모드로 풀해상도 됨. 사용자/매출 생기고 프로 라이브 정면경쟁 시점에.
- [ ] `[요청]` TF 탭에 옥타브/FFT(RTA) 뷰 추가 — Spectrum 그대로 두고 TF 위상/매그 창에서 선택 토글(Smaart식).
- [ ] `[재조정/사용자평]` **플로팅 창 풀스크린 동작** — SPL미터·벡터스코프·라우드니스 팝아웃을 독립 Qt.Window+네이티브 collectionBehavior(FullScreenAuxiliary)로 변경(2026-06-15, 풀스크린 위+최소화 생존 둘 다 OK, 사용자 승인). ⚠️메인 풀스크린일 때 팝업도 크게 뜸 → 사용자가 줄여 씀. **현재 수용, 사용자 평 듣고 방향 재조정 예정.** *(상세: [[project_popout_fullscreen_fix]])*
- [ ] `[요청]` 딜레이 m 거리환산 표기 — ms↔m(음속 343). 한번 구현했다 "나중에 통합" 이유로 제거. *(상세: project_todo_delay_unit_m)*

---

## ✅ 완료 (최근, 릴리스 노트 재활용)

- 2026-06-14: git push(84커밋+태그7), 라이선스 Ed25519 라운드트립 6/6, 개인키 백업, Help버튼·드래그드롭#6 육안, Silicon 빌드+DMG 브랜딩, 진단 로깅+로그보내기, **재초기화 후 장치목록 로깅 추가**.
- 2026-06-13: 캘리브 채널테이블 B안 구현, SPL Meter 행×열, 캡쳐 일괄토글 설계.

---

## 📥 INBOX (분류 대기 — 막 적기)

(여기에 떠오르는 거 한 줄씩. Claude가 위 카테고리로 올림.)
