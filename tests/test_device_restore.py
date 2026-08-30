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
