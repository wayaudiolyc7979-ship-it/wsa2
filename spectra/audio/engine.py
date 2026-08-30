"""공유 오디오 I/O 엔진 — 물리장치당 스트림 1개, 다중 구독(탭 동시측정).

v2.0 분해: wayaudo2.py에서 이동(동작 0 변경). WASAPI 헬퍼 + AudioThread/
MultiChannelAudioThread/Subscription/_DeviceStream/AudioEngine/_Engine*Source.
Qt(QThread/QObject/pyqtSignal) 사용. TFDuplexThread는 별도(추후).
"""
import sys
import time
import numpy as np
import sounddevice as sd
import platform as _pl
import ctypes
from PyQt5.QtCore import QThread, QObject, pyqtSignal, Qt
from spectra.core.logging_diag import _alog, _diag, _no_stderr
from spectra.audio.watchdog import begin_no_sleep, end_no_sleep


class _DeadCallbackError(Exception):
    """스트림은 열렸는데 AUHAL 콜백이 안 시작된 '죽은 스트림' — 같은 config로 재오픈해야 함
    (open 실패=다음 config와 구분). M4 출력+입력 경합 시 간헐 발생."""
    pass


# ── Windows 오디오 호스트 API 선택 (WASAPI 우선) ───────────────────────────
# macOS는 CoreAudio 단일이라 무관 → 아래 헬퍼들은 비-Windows에선 전부 None을 돌려
# 기존 동작을 100% 그대로 보존한다(코드 경로 변화 없음).
# Windows에선 PortAudio가 같은 USB 인터페이스를 MME/DirectSound/WASAPI/WDM-KS/ASIO 로
# '중복' 열거하고 기본값이 MME라, MME의 샘플레이트 경직·다채널 제한·31자 이름잘림 때문에
# "USB 인터페이스가 안 잡힘/안 열림"이 발생한다 → 장치 목록을 WASAPI로 통일해 해결한다.
# (ASIO는 장치당 단일 스트림만 허용 → 공유엔진 다중구독(스펙트럼+TF 동시) 구조와 충돌하므로
#  의도적으로 제외하고 WASAPI 공유모드를 택한다.)
def _win_preferred_hostapi():
    """Windows에서 입력 장치를 1개 이상 노출하는 WASAPI 호스트 API의 인덱스를 반환.
    WASAPI가 없거나 비-Windows면 None → 호출부는 필터링 없이 종전과 동일하게 동작."""
    if _pl.system() != 'Windows':
        return None
    try:
        has = sd.query_hostapis()
        wasapi = next((i for i, h in enumerate(has)
                       if 'wasapi' in str(h.get('name', '')).lower()), None)
        if wasapi is None:
            return None
        # WASAPI로 보이는 입력 장치가 하나도 없으면 필터링하지 않음(빈 목록 방지 = 안전 폴백)
        if any(d.get('hostapi') == wasapi and d.get('max_input_channels', 0) >= 1
               for d in sd.query_devices()):
            return wasapi
    except Exception:
        pass
    return None

def _dev_hostapi_ok(d, pref):
    """장치 d를 목록에 포함할지 — pref(None=전체 허용)에 지정된 호스트 API에 속할 때만 True."""
    return pref is None or d.get('hostapi') == pref

def _win_extra_settings():
    """WASAPI로 필터링 중일 때만 auto_convert ExtraSettings 반환 — 앱이 요청한 샘플레이트가
    장치 믹스포맷과 달라도 공유모드에서 자동 변환해 스트림 오픈 실패(-9997 등)를 막는다.
    그 외(비-Windows/WASAPI 미사용)엔 None → 스트림 오픈에 영향 없음(기존 기본값과 동일)."""
    if _win_preferred_hostapi() is None:
        return None
    try:
        return sd.WasapiSettings(auto_convert=True)
    except Exception:
        return None


class AudioThread(QThread):
    chunk_ready        = pyqtSignal(object)
    error_signal       = pyqtSignal(str)
    disconnected_signal= pyqtSignal(str)   # 정상 작동 중 물리적 연결 끊김
    def __init__(self, device_idx, sample_rate, fft_size, channel=0, force_latency=None):
        super().__init__()
        self.device_idx=device_idx; self.sample_rate=sample_rate
        self.fft_size=fft_size; self.running=False; self.channel=channel
        self.force_latency=force_latency
        self._active_stream=None   # stop()에서 abort()로 즉시 장치 해제
    def run(self):
        self.running=True
        buf=np.zeros(self.fft_size,dtype=np.float32)
        ch_idx=self.channel; n_ch=ch_idx+1
        _last_emit=[0.0]
        _last_cb=[time.monotonic()]   # watchdog: USB 제거 감지용
        _got_cb=[False]   # 첫 콜백 수신 여부 — 시작 지연(같은장치 in/out churn)을 끊김으로 오판 방지
        def cb(indata,frames,ti,status):
            if not self.running: return
            try:
                _last_cb[0]=time.monotonic(); _got_cb[0]=True   # 콜백 살아있음 갱신
                if indata.shape[1] == 0: return
                src_ch=min(ch_idx, indata.shape[1]-1)
                chunk=indata[:,src_ch].astype(np.float32); n=min(len(chunk),len(buf))
                buf[:-n]=buf[n:]; buf[-n:]=chunk[:n]
                now=time.monotonic()
                if now-_last_emit[0]>=0.016:
                    _last_emit[0]=now
                    self.chunk_ready.emit(buf.copy())
            except Exception: pass
        def _open(bs, lat):
            with _no_stderr():
                return sd.InputStream(device=self.device_idx, samplerate=self.sample_rate,
                                      channels=n_ch, blocksize=bs,
                                      callback=cb, latency=lat, dtype='float32',
                                      extra_settings=_win_extra_settings())

        def _run(bs, lat):
            """스트림 열기 시도. watchdog로 USB disconnect 감지.
            열기 실패 → raise / 정상 종료 → False / disconnect 감지 → True"""
            try:
                with _open(bs, lat) as _s:
                    self._active_stream=_s
                    _last_cb[0]=time.monotonic()   # 스트림 열릴 때 초기화
                    while self.running:
                        self.msleep(500)
                        # macOS AUHAL은 USB 제거 후에도 _s.active=True 유지.
                        # 콜백이 흐르다가 2초 이상 끊기면 물리적 연결 끊김으로 판단.
                        # (첫 콜백 받은 뒤에만 — 시작 지연을 끊김으로 오판하지 않도록)
                        if _got_cb[0] and time.monotonic()-_last_cb[0] > 2.0:
                            self.disconnected_signal.emit('device removed')
                            return True
                return False  # self.running=False → 정상 Stop
            except Exception:
                raise
            finally:
                self._active_stream=None

        # force_latency 지정 시 해당 latency만 시도 (공유 하드웨어 IO 버퍼 재설정 방지)
        # 미지정 시: 1차 blocksize=512/low → 2차 high → 3차 blocksize=0/high
        # USB 재연결 직후 AUHAL 초기화 지연 대응: 전체 2라운드 시도 (라운드 사이 1.5초 대기)
        # force_latency='high': 큰 하드웨어 버퍼(제너레이터 출력과 IO 안정) 유지하되, blocksize는 512로
        # 작게 — PortAudio는 콜백 청크(blocksize)와 하드웨어 버퍼(latency)를 분리 처리하므로
        # 콜백을 자주 받아(≈93/s) 공유 소비자(Spectrum)의 청크당 스무딩이 느려지지 않음.
        _attempts = [(512, self.force_latency), (2048, self.force_latency)] if self.force_latency else [(512,'low'), (512,'high'), (0,'high')]
        last_err=None
        for round_n in range(2):
            for (bs, lat) in _attempts:
                try:
                    if _run(bs, lat):
                        return   # disconnect 처리 완료
                    return       # 정상 종료
                except Exception as e:
                    last_err=e
                    continue     # 열기 실패 → 다음 설정 시도
            if round_n == 0:
                # 모든 설정 1차 실패 → USB 재연결 후 AUHAL 초기화 대기 후 재시도
                # running 에 반응하도록 분할 슬립 (stop 시 즉시 빠져나옴)
                for _ in range(15):
                    if not self.running: return
                    self.msleep(100)
        # 두 라운드 모두 실패
        if last_err:
            self.error_signal.emit(str(last_err))
    def stop(self):
        self.running=False
        s=self._active_stream
        if s is not None:
            try: s.abort(ignore_errors=True)   # 즉시 장치 해제 → with __exit__ 가 바로 풀림
            except Exception:
                try: s.close(ignore_errors=True)
                except Exception: pass
        if not self.wait(3000):
            _alog.warning('AudioThread stop(): wait timeout — stream forced abort')


# 멀티채널 오버레이 색상 팔레트 (채널 인덱스 기준 고정)


class MultiChannelAudioThread(QThread):
    """단일 InputStream으로 여러 채널을 동시에 캡처.
    chunk_ready({ch_idx: np.array}) 형태로 emit — 스트림 하나이므로 완벽 동기화."""
    chunk_ready         = pyqtSignal(object)
    raw_ready           = pyqtSignal(object)   # 원시 연속 프레임 {ch: array} — 스로틀 X (Loudness 등 샘플 적분 소비자용)
    error_signal        = pyqtSignal(str)
    disconnected_signal = pyqtSignal(str)

    def __init__(self, device_idx, sample_rate, fft_size, channels, force_latency=None):
        super().__init__()
        self.device_idx    = device_idx
        self.sample_rate   = sample_rate
        self.fft_size      = fft_size
        self.channels      = sorted(set(channels))
        self.force_latency = force_latency
        self.running       = False
        self._active_stream= None   # stop()에서 abort()로 즉시 장치 해제
        self._last_cb_mono = 0.0    # 마지막 콜백 시각(monotonic) — 외부에서 스트림 생존 판정용
        self._got_cb_flag  = False  # 첫 콜백 수신 여부(외부 노출)

    def run(self):
        self.running = True
        n_ch  = max(self.channels) + 1
        bufs  = {ch: np.zeros(self.fft_size, dtype=np.float32) for ch in self.channels}
        _last_emit = [0.0]
        _last_cb   = [time.monotonic()]
        _got_cb    = [False]   # 첫 콜백 수신 여부 — 시작 지연을 끊김으로 오판 방지
        _dead_retry = [0]      # 연속 실패 재오픈 횟수 — 콜백 재개 시 리셋(장시간 세션 소진 방지)

        def cb(indata, frames, ti, status):
            if not self.running: return
            try:
                _last_cb[0] = time.monotonic(); _got_cb[0] = True
                self._last_cb_mono = _last_cb[0]; self._got_cb_flag = True   # 외부 생존 판정용
                if indata.shape[1] == 0: return
                raw = {}
                for ch in self.channels:
                    src = min(ch, indata.shape[1] - 1)
                    chunk = indata[:, src].astype(np.float32)   # astype → 새 배열(콜백 버퍼와 분리)
                    raw[ch] = chunk
                    n = min(len(chunk), self.fft_size)
                    bufs[ch][:-n] = bufs[ch][n:]
                    bufs[ch][-n:] = chunk[:n]
                # 원시 연속 프레임 — 매 콜백 emit (샘플 손실 없이 → Loudness 적분 정확)
                self.raw_ready.emit(raw)
                now = time.monotonic()
                if now - _last_emit[0] >= 0.016:
                    _last_emit[0] = now
                    self.chunk_ready.emit({ch: bufs[ch].copy() for ch in self.channels})
            except Exception: pass

        def _open(bs, lat):
            # 객체만 생성 — start()는 _run() 내 _no_stderr() 안에서 호출됨
            return sd.InputStream(device=self.device_idx, samplerate=self.sample_rate,
                                  channels=n_ch, blocksize=bs,
                                  callback=cb, latency=lat, dtype='float32',
                                  extra_settings=_win_extra_settings())

        def _run(bs, lat):
            try:
                with _no_stderr(), _open(bs, lat) as _s:
                    self._active_stream = _s
                    try:
                        _alog.info(f'[DIAG] InputStream opened dev={self.device_idx} ch={n_ch} '
                                   f'req(bs={bs},lat={lat}) actual(bs={_s.blocksize},lat={_s.latency})')
                    except Exception: pass
                    _got_cb[0] = False   # 이 시도 기준으로 첫 콜백 판정(재시도마다 초기화)
                    _last_cb[0] = time.monotonic(); _open_t = time.monotonic()
                    while self.running:
                        self.msleep(500)
                        if _got_cb[0]:
                            _dead_retry[0] = 0   # 콜백 정상 흐름 → 재시도 예산 회복
                        # 시작 워치독: 스트림은 열렸는데 첫 콜백이 2초 내 안 오면(AUHAL 콜백 미시작
                        # — M4 출력+입력 동시 경합 시 간헐 발생) 죽은 스트림 → _DeadCallbackError 로
                        # 같은 config 재시도 유도(저지연 유지). 전 스트림(스펙트럼/TF/카드) 공통. [찾기: CB_WATCHDOG]
                        if (not _got_cb[0]) and (time.monotonic() - _open_t > 2.0):
                            _diag('eng_cb_dead', dev=self.device_idx, bs=bs, lat=str(lat))
                            raise _DeadCallbackError()
                        # 콜백이 흐르다 멈춤(running-stall) — 절전/App Nap/일시 글리치 가능. 물리적
                        # 제거로 단정하지 말고 같은 장치를 재오픈해 마이크를 되살린다(가짜 device-removed
                        # 방지). 연속 재오픈이 계속 콜백을 못 받으면 그때 진짜 제거로 판정. [찾기: CB_STALL]
                        if _got_cb[0] and time.monotonic() - _last_cb[0] > 2.0:
                            _diag('eng_cb_stall', dev=self.device_idx,
                                  age_ms=round((time.monotonic() - _last_cb[0]) * 1000))
                            raise _DeadCallbackError()
                return False
            except Exception: raise
            finally:
                self._active_stream = None

        # force_latency='high': 큰 하드웨어 버퍼(제너레이터 안정) 유지 + blocksize 512(잦은 콜백)
        # → 공유 스트림을 TF와 함께 써도 Spectrum 청크당 스무딩 속도가 정상 유지됨.
        _attempts = [(512, self.force_latency), (2048, self.force_latency)] if self.force_latency else [(512,'low'),(512,'high'),(0,'high')]
        last_err = None
        begin_no_sleep()   # 측정 중 idle 시스템 절전 차단(콜백 정지 트리거 제거)
        try:
            for round_n in range(2):
                for (bs, lat) in _attempts:
                    # 죽은 콜백(스트림 열렸으나 첫 콜백 없음)=같은 config 재시도 → 저지연 유지하며 복구.
                    # running-stall(콜백 흐르다 멈춤)도 같은 경로로 재오픈. open 실패(예외)=다음 config로.
                    _dead_retry[0] = 0
                    while True:
                        try:
                            if _run(bs, lat): return
                            return
                        except _DeadCallbackError:
                            if not self.running: return
                            last_err = 'dead AUHAL callback'; _dead_retry[0] += 1
                            if _dead_retry[0] >= 3:
                                # 3회 재오픈해도 콜백 미수신 → 콜백을 한 번이라도 받았던 스트림이면
                                # 물리적 제거로 판정(disconnected). 처음부터 죽은 스타트업이면 다음 config.
                                if getattr(self, '_got_cb_flag', False):
                                    self.disconnected_signal.emit('device removed')
                                    return
                                break                     # 같은 config 3회 죽음 → 다음 config
                            continue                      # 같은 config 재오픈
                        except Exception as e:
                            last_err = e; break           # open 실패 → 다음 config
                if round_n == 0:
                    for _ in range(15):
                        if not self.running: return
                        self.msleep(100)
            if last_err: self.error_signal.emit(str(last_err))
        finally:
            end_no_sleep()

    def stop(self):
        self.running = False
        s = self._active_stream
        if s is not None:
            try: s.abort(ignore_errors=True)
            except Exception:
                try: s.close(ignore_errors=True)
                except Exception: pass
        if not self.wait(3000):
            _alog.warning('MultiChannelAudioThread stop(): wait timeout — stream forced abort')


# ──────────────────────────────────────────────────────────────
#  공유 오디오 엔진 (옵션2 토대 — Smaart식 중앙 I/O)
#  장치당 InputStream 1개만 열고 여러 구독자에게 chunk 배포 → CoreAudio 충돌 원천 차단.
#  ※ 아직 어떤 탭에도 연결돼 있지 않음(additive). 소비자 마이그레이션은 장비 확보 후.
# ──────────────────────────────────────────────────────────────
class Subscription(QObject):
    """AudioEngine 구독 핸들 — 구독한 채널의 chunk만 수신."""
    chunk_ready  = pyqtSignal(object)   # {ch: np.array} — 롤링 fft_size 버퍼 (Spectrum용)
    raw_ready    = pyqtSignal(object)   # {ch: np.array} — 원시 연속 프레임 (Loudness 등 샘플 적분용)
    error        = pyqtSignal(str)
    disconnected = pyqtSignal(str)

    def __init__(self, engine, device_idx, channels, force_latency=None):
        super().__init__()
        self._engine = engine
        self.device_idx = device_idx
        self.channels = sorted(set(channels))
        self.force_latency = force_latency   # 'high' 요청 시 공유 스트림이 high로 (출력과 IO버퍼 일치)
        self._closed = False

    def close(self):
        if self._closed: return
        self._closed = True
        self._engine._unsubscribe(self)


# TF/제너레이터 공유 시 입력·출력 latency (초). 'high'(~88ms)는 Spectrum 지연이 과해
# 노이즈 안 나는 선에서 낮춤. 입력·출력 동일값으로 맞춰 글리치 방지. 노이즈 재발 시 ↑.
_HI_LAT = 0.040


class _DeviceStream:
    """한 물리 장치의 단일 InputStream + 구독자 목록."""
    def __init__(self, engine, device_idx, sample_rate):
        self._engine = engine
        self.device_idx = device_idx
        self.sample_rate = sample_rate
        self.subs = []          # Subscription 목록
        self.thread = None
        self.union = set()      # 현재 스트림이 캡처 중인 채널 합집합
        self.force_latency = None  # 현재 스트림 latency ('high' or None)

    def _resolve_latency(self):
        # 구독자 중 하나라도 high 요청(TF 동기 안정성)이 있으면 high.
        # → 제너레이터 출력(high)과 입력의 latency/하드웨어 버퍼가 정렬되어 띠띠띡 글리치 방지
        #   (둘 다 low는 M4 실측에서 출력 xrun 노이즈 발생 — 6/10 오후 가정 오류).
        # Spectrum/Stereo 단독(high 요청 없음)은 None(low) 유지 → 빠른 업데이트.
        # TF 가 도는 동안만 공유 스트림이 _HI_LAT(40ms) → 'high'(88ms)보다 지연↓ = Spectrum 덜 느림.
        return _HI_LAT if any(getattr(s, 'force_latency', None) for s in self.subs) else None

    def add(self, sub):
        self.subs.append(sub)
        need = self.union | set(sub.channels)
        need_lat = self._resolve_latency()
        # 채널 확장 또는 latency 상승 시 (재)오픈
        _reopen = (self.thread is None or need != self.union or need_lat != self.force_latency)
        _diag('eng_add', dev=self.device_idx, n_subs=len(self.subs),
              sub_ch=list(sub.channels), reopen=_reopen, lat=str(need_lat))
        if _reopen:
            self._open(need, need_lat)

    def remove(self, sub):
        if sub in self.subs: self.subs.remove(sub)
        if not self.subs:       # 마지막 구독 해제 → 스트림 종료 (union 축소는 v1 생략)
            self._close()

    def _open(self, channels, force_latency=None):
        self._close_thread()
        # 장치의 전체 입력 채널을 한 번에 캡처 → 이후 구독자가 채널을 추가해도 union 이 커지지
        # 않아 재오픈이 영영 불필요. close→reopen 은 같은 장치에 다른 스트림(Spectrum 라이브)·
        # 제너레이터 출력이 활성일 때 글리치(노이즈)·스트림 open 실패(에러)·콜백 정지(가짜
        # device-removed)를 유발하므로 원천 차단 → 탭 시작 순서(TF먼저/Spectrum먼저) 무관 동작.
        want = set(channels)
        try:
            _max_in = int(sd.query_devices(self.device_idx)['max_input_channels'])
        except Exception:
            _max_in = 0
        if _max_in > 0:
            want |= set(range(_max_in))
        self.union = want
        self.force_latency = force_latency
        th = self._engine._thread_factory(
            self.device_idx, self.sample_rate, self._engine._fft_size, sorted(self.union),
            force_latency=force_latency)
        th.chunk_ready.connect(self._dispatch)
        if hasattr(th, 'raw_ready'):   # 테스트 가짜 스레드는 raw_ready 없을 수 있음
            th.raw_ready.connect(self._dispatch_raw)
        th.error_signal.connect(self._on_error)
        th.disconnected_signal.connect(self._on_disc)
        self.thread = th
        th.start()
        _diag('eng_stream_open', dev=self.device_idx, ch=sorted(self.union), lat=str(force_latency))

    def _close_thread(self):
        if self.thread is not None:
            try:
                self.thread.chunk_ready.disconnect()
                if hasattr(self.thread, 'raw_ready'): self.thread.raw_ready.disconnect()
                self.thread.error_signal.disconnect()
                self.thread.disconnected_signal.disconnect()
            except Exception: pass
            try: self.thread.stop()
            except Exception: pass
            self.thread = None

    def _close(self):
        self._close_thread()
        self._engine._remove_stream(self.device_idx)

    def _dispatch(self, chunk_dict):
        for sub in list(self.subs):
            try:
                sub.chunk_ready.emit({ch: chunk_dict[ch] for ch in sub.channels if ch in chunk_dict})
            except Exception: pass

    def _dispatch_raw(self, chunk_dict):
        for sub in list(self.subs):
            try:
                sub.raw_ready.emit({ch: chunk_dict[ch] for ch in sub.channels if ch in chunk_dict})
            except Exception: pass

    def _on_error(self, msg):
        _diag('eng_stream_err', dev=self.device_idx, err=str(msg)[:80])   # 미터 안뜸=입력 열기 실패 추적
        for sub in list(self.subs): sub.error.emit(msg)

    def _on_disc(self, msg):
        for sub in list(self.subs): sub.disconnected.emit(msg)


class AudioEngine(QObject):
    """장치별 단일 InputStream을 소유하고 여러 구독자에게 chunk를 배포하는 공유 엔진.

    같은 장치를 여러 탭/분석기가 동시에 구독해도 스트림은 장치당 1개만 열려
    CoreAudio "한 장치 두 스트림" 충돌을 원천 차단한다. (옵션2 토대)
    thread_factory를 주입하면 테스트에서 가짜 스트림으로 로직 검증 가능.
    """
    def __init__(self, fft_size=16384, thread_factory=MultiChannelAudioThread):
        super().__init__()
        self._streams = {}            # device_idx -> _DeviceStream
        self._fft_size = fft_size
        self._thread_factory = thread_factory

    def subscribe(self, device_idx, channels, sample_rate, force_latency=None):
        """device_idx의 channels를 sample_rate로 구독. Subscription 반환.
        같은 장치에 다른 SR 요청 시 ValueError(장치당 SR 하나).
        force_latency='high' 요청 시 공유 스트림을 high latency로 (재)오픈 (출력 듀플렉스와 IO버퍼 일치)."""
        st = self._streams.get(device_idx)
        if st is None:
            st = _DeviceStream(self, device_idx, sample_rate)
            self._streams[device_idx] = st
        elif st.sample_rate != sample_rate:
            raise ValueError(
                f'device {device_idx} already open at {st.sample_rate}Hz; '
                f'cannot subscribe at {sample_rate}Hz (one SR per device)')
        sub = Subscription(self, device_idx, channels, force_latency)
        st.add(sub)
        return sub

    def _unsubscribe(self, sub):
        st = self._streams.get(sub.device_idx)
        if st is not None:
            st.remove(sub)

    def _remove_stream(self, device_idx):
        self._streams.pop(device_idx, None)

    def current_sr(self, device_idx):
        """이미 열려 있는 장치 스트림의 SR(없으면 None). 같은 장치를 여러 탭이 구독할 때
        SR을 합의시켜 'one SR per device' 충돌을 피하는 데 사용(먼저 연 쪽 SR을 따른다)."""
        st = self._streams.get(device_idx)
        return st.sample_rate if st is not None else None

    def active_devices(self):
        return list(self._streams.keys())

    def freshest_callback_age(self):
        """현재 열린 입력 스트림 중 '가장 최근에 콜백 받은' 스트림의 경과시간(초)을 반환.
        - None  = 콜백을 한 번이라도 받은 살아있는 스트림이 하나도 없음(스트림 미존재 or 미시작)
        - >큰값 = 모든 스트림 콜백이 멈춤(장치 제거 가능성)
        USB가 사용 중 빠지면 콜백이 끊겨 이 값이 계속 커진다 → 외부에서 끊김 백스톱 판정에 사용."""
        now = time.monotonic(); best = None
        for st in list(self._streams.values()):
            th = getattr(st, 'thread', None)
            if th is None or not getattr(th, '_got_cb_flag', False):
                continue
            age = now - getattr(th, '_last_cb_mono', 0.0)
            if best is None or age < best:
                best = age
        return best

    def stop_all(self):
        for st in list(self._streams.values()):
            st._close_thread()
        self._streams.clear()


# ──────────────────────────────────────────────────────────────
#  TF 엔진 백드 입력 소스 (옵션2 — TF 측정입력을 공유 엔진으로)
#  기존 TFSyncThread/MultiChannelAudioThread/AudioThread 와 동일한 인터페이스
#  (start/stop, frame_ready/chunk_ready/error_signal/disconnected_signal)를 제공하되
#  내부는 engine.subscribe(raw_ready)로 동작 → 장치당 단일 스트림 공유.
#  엔진은 raw(원시 연속 프레임)만 주고, 각 소스가 자기 fft_size 롤링 버퍼를 유지한다
#  (탭마다 FFT 크기가 달라도 OK — Spectrum 16384, TF 4K~32K 동시).
#  ※ 제너레이터(_sig_stream)·내부 듀플렉스(TFDuplexThread)는 격리 유지(엔진 미경유).
# ──────────────────────────────────────────────────────────────
class _EngineSyncSource(QObject):
    """TFSyncThread 대체 — ref+meas 두 채널을 단일 스트림 동일 콜백에서 받아
    각자 fft_size 롤링 버퍼 유지 후 frame_ready(ref,meas) emit (ΔT=0 원자성)."""
    frame_ready         = pyqtSignal(object, object)
    error_signal        = pyqtSignal(str)
    disconnected_signal = pyqtSignal(str)

    def __init__(self, engine, device_idx, sample_rate, fft_size, ref_ch, meas_ch, force_latency='high'):
        super().__init__()
        self._engine = engine; self.device_idx = device_idx; self.sample_rate = sample_rate
        self.fft_size = fft_size; self.ref_ch = ref_ch; self.meas_ch = meas_ch
        self.force_latency = force_latency   # TFSyncThread는 항상 high였음 (동기 안정성)
        self._sub = None; self._last_emit = 0.0
        self._ref_buf  = np.zeros(fft_size, dtype=np.float32)
        self._meas_buf = np.zeros(fft_size, dtype=np.float32)

    def start(self):
        try:
            self._sub = self._engine.subscribe(self.device_idx, [self.ref_ch, self.meas_ch],
                                               self.sample_rate, force_latency=self.force_latency)
        except Exception as e:
            self.error_signal.emit(str(e)); return
        self._sub.raw_ready.connect(self._on_raw, Qt.QueuedConnection)
        self._sub.error.connect(self.error_signal, Qt.QueuedConnection)
        self._sub.disconnected.connect(self.disconnected_signal, Qt.QueuedConnection)

    def _on_raw(self, d):
        r = d.get(self.ref_ch); m = d.get(self.meas_ch)
        if r is None or m is None: return
        nr = min(len(r), self.fft_size); nm = min(len(m), self.fft_size)
        # 버퍼 연속성: 롤링은 매 콜백 유지 (샘플 손실 방지)
        self._ref_buf[:-nr]  = self._ref_buf[nr:];  self._ref_buf[-nr:]  = r[:nr]
        self._meas_buf[:-nm] = self._meas_buf[nm:]; self._meas_buf[-nm:] = m[:nm]
        # frame_ready(→ 메인스레드 FFT)는 30fps로 스로틀 — TF 렌더는 10fps라 충분하고,
        # Spectrum과 같은 메인스레드에서 매 콜백(~90fps) FFT를 돌리면 Spectrum 페인트가 밀린다.
        now = time.monotonic()
        if now - self._last_emit >= 0.033:
            self._last_emit = now
            self.frame_ready.emit(self._ref_buf.copy(), self._meas_buf.copy())

    def isRunning(self): return self._sub is not None

    def stop(self):
        if self._sub is not None:
            try: self._sub.raw_ready.disconnect()
            except Exception: pass
            try: self._sub.close()
            except Exception: pass
            self._sub = None


class _EngineMultiSource(QObject):
    """MultiChannelAudioThread 대체 — 여러 채널을 받아 채널별 fft_size 롤링 버퍼 유지,
    chunk_ready({ch:buf}) emit (16ms 스로틀). _on_mc_chunk 형식과 동일."""
    chunk_ready         = pyqtSignal(object)
    error_signal        = pyqtSignal(str)
    disconnected_signal = pyqtSignal(str)

    def __init__(self, engine, device_idx, sample_rate, fft_size, channels, force_latency=None):
        super().__init__()
        self._engine = engine; self.device_idx = device_idx; self.sample_rate = sample_rate
        self.fft_size = fft_size; self.channels = sorted(set(channels)); self.force_latency = force_latency
        self._sub = None; self._last_emit = 0.0
        self._bufs = {ch: np.zeros(fft_size, dtype=np.float32) for ch in self.channels}

    def start(self):
        try:
            self._sub = self._engine.subscribe(self.device_idx, self.channels,
                                               self.sample_rate, force_latency=self.force_latency)
        except Exception as e:
            self.error_signal.emit(str(e)); return
        self._sub.raw_ready.connect(self._on_raw, Qt.QueuedConnection)
        self._sub.error.connect(self.error_signal, Qt.QueuedConnection)
        self._sub.disconnected.connect(self.disconnected_signal, Qt.QueuedConnection)

    def _on_raw(self, d):
        for ch in self.channels:
            frames = d.get(ch)
            if frames is None: continue
            b = self._bufs[ch]; n = min(len(frames), self.fft_size)
            b[:-n] = b[n:]; b[-n:] = frames[:n]
        # chunk_ready(→ 메인스레드 FFT/누적)는 30fps로 스로틀 — TF 렌더는 10fps라 충분.
        # 60fps면 같은 메인스레드의 Spectrum FFT/페인트와 경합해 Spectrum이 느려진다.
        now = time.monotonic()
        if now - self._last_emit >= 0.033:
            self._last_emit = now
            self.chunk_ready.emit({ch: self._bufs[ch].copy() for ch in self.channels})

    def isRunning(self): return self._sub is not None

    def stop(self):
        if self._sub is not None:
            try: self._sub.raw_ready.disconnect()
            except Exception: pass
            try: self._sub.close()
            except Exception: pass
            self._sub = None


class _EngineChannelSource(QObject):
    """AudioThread 대체 — 단일 채널 fft_size 롤링 버퍼 → chunk_ready(buf) emit (16ms 스로틀)."""
    chunk_ready         = pyqtSignal(object)
    error_signal        = pyqtSignal(str)
    disconnected_signal = pyqtSignal(str)

    def __init__(self, engine, device_idx, sample_rate, fft_size, channel=0, force_latency=None):
        super().__init__()
        self._engine = engine; self.device_idx = device_idx; self.sample_rate = sample_rate
        self.fft_size = fft_size; self.channel = channel; self.force_latency = force_latency
        self._sub = None; self._last_emit = 0.0
        self._buf = np.zeros(fft_size, dtype=np.float32)

    def start(self):
        try:
            self._sub = self._engine.subscribe(self.device_idx, [self.channel],
                                               self.sample_rate, force_latency=self.force_latency)
        except Exception as e:
            self.error_signal.emit(str(e)); return
        self._sub.raw_ready.connect(self._on_raw, Qt.QueuedConnection)
        self._sub.error.connect(self.error_signal, Qt.QueuedConnection)
        self._sub.disconnected.connect(self.disconnected_signal, Qt.QueuedConnection)

    def _on_raw(self, d):
        frames = d.get(self.channel)
        if frames is None: return
        b = self._buf; n = min(len(frames), self.fft_size)
        b[:-n] = b[n:]; b[-n:] = frames[:n]
        now = time.monotonic()
        if now - self._last_emit >= 0.016:
            self._last_emit = now
            self.chunk_ready.emit(self._buf.copy())

    def isRunning(self): return self._sub is not None

    def stop(self):
        if self._sub is not None:
            try: self._sub.raw_ready.disconnect()
            except Exception: pass
            try: self._sub.close()
            except Exception: pass
            self._sub = None


def _fourcc(s):
    """4문자 코드(b'dev#' 등) → UInt32. CoreAudio 셀렉터/스코프 상수용."""
    return int.from_bytes(s, 'big')


class _CoreAudioDeviceWatcher(QObject):
    """macOS CoreAudio 하드웨어 장치 변경 리스너 — USB 인터페이스를 idle 상태에서
    뽑/꽂아도 OS 레벨에서 즉시 감지(PortAudio 재초기화 없이는 query_devices() 개수가
    안 바뀌므로 폴링으론 못 잡는다). 변경 시 changed 시그널을 메인 스레드로 큐잉한다.
    콜백은 CoreAudio 스레드에서 호출되므로 Qt를 직접 만지지 말고 시그널만 emit."""
    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ca = None
        self._proc = None        # CFUNCTYPE 콜백 — GC 방지로 self에 보관
        self._addr = None
        self._active = False

    def start(self):
        if sys.platform != 'darwin' or self._active:
            return False
        try:
            import ctypes
            ca = ctypes.CDLL('/System/Library/Frameworks/CoreAudio.framework/CoreAudio')

            class _Addr(ctypes.Structure):
                _fields_ = [('mSelector', ctypes.c_uint32),
                            ('mScope',    ctypes.c_uint32),
                            ('mElement',  ctypes.c_uint32)]

            addr = _Addr(_fourcc(b'dev#'),   # kAudioHardwarePropertyDevices
                         _fourcc(b'glob'),   # kAudioObjectPropertyScopeGlobal
                         0)                   # kAudioObjectPropertyElementMain

            PROC = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_uint32, ctypes.c_uint32,
                                    ctypes.c_void_p, ctypes.c_void_p)

            def _cb(obj_id, n_addr, addrs, client):
                try: self.changed.emit()   # 큐잉 → 메인 스레드에서 처리
                except Exception: pass
                return 0

            proc = PROC(_cb)
            ca.AudioObjectAddPropertyListener.restype = ctypes.c_int32
            ca.AudioObjectAddPropertyListener.argtypes = [
                ctypes.c_uint32, ctypes.POINTER(_Addr), PROC, ctypes.c_void_p]
            status = ca.AudioObjectAddPropertyListener(
                1, ctypes.byref(addr), proc, None)   # 1 = kAudioObjectSystemObject
            if status != 0:
                _alog.warning(f'CoreAudio 리스너 등록 실패 status={status}')
                return False
            self._ca = ca; self._proc = proc; self._addr = addr; self._active = True
            _alog.info('CoreAudio 장치변경 리스너 등록 OK')
            return True
        except Exception as e:
            _alog.warning(f'CoreAudio 리스너 시작 예외: {e}')
            return False

    def device_count(self):
        """현재 OS(HAL)가 보는 오디오 장치 개수를 CoreAudio에 직접 질의해 반환(None=실패).
        PortAudio 캐시(query_devices)와 달리 재초기화 없이 실시간 — USB가 뽑히면 즉시 줄어든다.
        ※일부 USB 드라이버는 뽑혀도 InputStream 콜백을 무음으로 계속 흘려 '콜백 생존'으로는
        끊김을 못 잡으므로(2초 워치독·콜백age 무력), 장치 개수 감소로 제거를 확실히 감지한다."""
        if not self._active or self._ca is None or self._addr is None:
            return None
        try:
            import ctypes
            ca = self._ca
            ca.AudioObjectGetPropertyDataSize.restype = ctypes.c_int32
            ca.AudioObjectGetPropertyDataSize.argtypes = [
                ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32,
                ctypes.c_void_p, ctypes.c_void_p]
            size = ctypes.c_uint32(0)
            st = ca.AudioObjectGetPropertyDataSize(
                1, ctypes.byref(self._addr), 0, None, ctypes.byref(size))   # 1=systemObject
            if st != 0:
                return None
            return size.value // 4   # sizeof(AudioDeviceID)=UInt32=4byte
        except Exception:
            return None


# _glance_chrome_update, _glance_set_chrome, _ReloadBtn — v2.0 분해: spectra/ui/spl.py, re-import
