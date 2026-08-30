"""device-change 자동 복구 로직 테스트 (2026-08-30).

버그: 깨어있는 중 CoreAudio가 사용 중 장치를 'removed' 보고 → reinit_audio_devices가
측정을 정지 → 장치가 돌아와도 재시작하는 코드가 없어 마이크가 조용히 죽은 채 방치.
수정: 정지 직전 실행 중이던 카드를 스냅샷(_reinit_restore_cards)하고, 장치가 돌아오면
_try_restore_measurements가 자동 재시작. 장치 미복귀 시 no-op으로 스냅샷 유지(다음 tick 재시도).

MainWindow 전체는 offscreen에서 segfault → 메서드를 스텁 인스턴스에 바인딩해 로직만 검증.
"""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('WSA2_SETTINGS_PATH', '/tmp/tr_s.json')
os.environ.setdefault('WSA2_CAPTURES_PATH', '/tmp/tr_c.json')
from spectra.ui.main_window import MainWindow


class _Stub:
    """MainWindow._try_restore_measurements가 쓰는 최소 표면만 구현한 스텁."""
    def __init__(self, running_ids, device_available):
        self._reinit_restore_cards = list(running_ids)
        self._device_available = device_available
        self._started = set()          # _card_start로 실제 시작된 카드
        self._spec_extra = [{'id': 5, 'sub': None}]

    def _primary_running(self):
        return 0 in self._started

    def _card_start(self, cid):
        # 실제 _card_start처럼: 장치 없으면 스트림 열기 실패 → 시작 안 됨(no-op)
        if not self._device_available:
            return
        self._started.add(cid)
        if cid != 0:
            for s in self._spec_extra:
                if s['id'] == cid:
                    s['sub'] = object()   # 구독 생김 = 실행 중


def test_restore_when_device_back():
    """장치가 돌아온 상태 → 스냅샷의 카드 전부 재시작 + 스냅샷 소거."""
    st = _Stub(running_ids=[0, 5], device_available=True)
    MainWindow._try_restore_measurements(st)
    assert st._primary_running(), 'primary(0) 자동 재시작 안 됨'
    assert any(s['id'] == 5 and s.get('sub') for s in st._spec_extra), '추가카드(5) 재시작 안 됨'
    assert st._reinit_restore_cards is None, '복구 완료 후 스냅샷이 안 비워짐'


def test_keep_snapshot_when_device_gone():
    """장치가 아직 안 옴 → no-op, 스냅샷 유지(다음 replug tick에서 재시도)."""
    st = _Stub(running_ids=[0, 5], device_available=False)
    MainWindow._try_restore_measurements(st)
    assert not st._primary_running(), '장치 없는데 시작됨(오작동)'
    assert st._reinit_restore_cards == [0, 5], '장치 미복귀인데 스냅샷이 사라짐 → 재시도 못 함'


def test_retry_then_recover():
    """장치 미복귀 → 유지 → 이후 복귀 → 재시작(2-tick 시나리오)."""
    st = _Stub(running_ids=[0], device_available=False)
    MainWindow._try_restore_measurements(st)      # tick1: 장치 없음
    assert st._reinit_restore_cards == [0]
    st._device_available = True                   # 장치 돌아옴
    MainWindow._try_restore_measurements(st)      # tick2: 복구
    assert st._primary_running()
    assert st._reinit_restore_cards is None


def test_noop_when_nothing_to_restore():
    """스냅샷 없음 → 아무 일도 안 함(예외 없이)."""
    st = _Stub(running_ids=[], device_available=True)
    st._reinit_restore_cards = None
    MainWindow._try_restore_measurements(st)
    assert st._reinit_restore_cards is None
    assert not st._started


# ── TF / Stereo 복구 (device-change 자동복구 3탭 확장, 2026-08-30) ──

class _Combo:
    def __init__(self, items):   # items: [(text, data)]
        self._items = items; self._idx = 0 if items else -1
    def count(self): return len(self._items)
    def itemText(self, i): return self._items[i][0]
    def currentIndex(self): return self._idx
    def setCurrentIndex(self, i): self._idx = i
    def currentData(self): return self._items[self._idx][1] if 0 <= self._idx < len(self._items) else None
    def currentText(self): return self._items[self._idx][0] if 0 <= self._idx < len(self._items) else ''


class _Btn:
    def __init__(self, on=False): self._on = on
    def isChecked(self): return self._on
    def click(self): self._on = not self._on


class _FakeTF:
    def __init__(self, meas_items, sig_out_data=1):
        self._running = False
        self.meas_cb = _Combo(meas_items)
        self.sig_on_btn = _Btn(False)
        self.sig_out_cb = _Combo([('Out A', sig_out_data)])
    def _start(self):
        self._running = True   # 실제 _start는 대화상자 없음; 장치 가드는 호출 전에 이미 통과


class _FakeStereo:
    def __init__(self): self._running = False


class _TabStub:
    """TF/Stereo 복구용 확장 스텁."""
    def __init__(self):
        self._reinit_restore_cards = None
        self._spec_extra = []
        # 정적 메서드 바인딩
        self._select_combo_by_text = MainWindow._select_combo_by_text
    def _primary_running(self): return False
    def _st_toggle(self):
        if self.dev_cb.currentData() is not None and self.dev_cb.currentData() >= 0:
            self.stereo_page._running = True


def test_restore_tf_when_original_device_back():
    """TF: 원래 meas 장치가 이름으로 다시 잡히면 재시작 + 플래그 소거."""
    st = _TabStub()
    st.tf_win = _FakeTF(meas_items=[('Built-in', 0), ('USB Mic', 2)])
    st.stereo_page = None
    st._reinit_restore_tf = True
    st._reinit_restore_tf_dev = 'USB Mic'      # 원래 이 장치로 측정 중이었음
    MainWindow._try_restore_measurements(st)
    assert st.tf_win._running, 'TF가 원래 장치 복귀에도 재시작 안 됨'
    assert st.tf_win.meas_cb.currentText() == 'USB Mic', '엉뚱한 장치로 선택됨'
    assert st._reinit_restore_tf is False


def test_tf_not_restarted_on_wrong_device():
    """TF: 원래 장치가 목록에 없으면 재시작 안 함(엉뚱한 장치 방지) → 플래그 유지."""
    st = _TabStub()
    st.tf_win = _FakeTF(meas_items=[('Built-in', 0)])   # 'USB Mic' 없음
    st.stereo_page = None
    st._reinit_restore_tf = True
    st._reinit_restore_tf_dev = 'USB Mic'
    MainWindow._try_restore_measurements(st)
    assert not st.tf_win._running, '원래 장치 없는데 재시작됨(엉뚱한 장치 위험)'
    assert st._reinit_restore_tf is True, '재시도 위해 플래그 유지돼야 함'


def test_restore_stereo_when_device_back():
    """Stereo: dev_cb 장치가 잡히면 토글로 재시작."""
    st = _TabStub()
    st.tf_win = None
    st.stereo_page = _FakeStereo()
    st.dev_cb = _Combo([('Built-in', 0)])
    st._reinit_restore_stereo = True
    MainWindow._try_restore_measurements(st)
    assert st.stereo_page._running, 'Stereo 자동복구 안 됨'
    assert st._reinit_restore_stereo is False
