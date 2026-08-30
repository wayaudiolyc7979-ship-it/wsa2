"""측정 마이크 'running-stall 자동 재오픈' 회귀 테스트 (SPECTRA v2.0).

배경(버그): 마이크를 오래 열어두면(예: 1시간+) 유휴 절전/App Nap 등으로 오디오
콜백이 잠깐 끊길 수 있는데, 예전 워치독은 이를 무조건 '물리적 장치 제거'로 단정하고
캡처 스레드를 죽였고, 아무도 재시작하지 않아 마이크가 조용히 멈췄다.

이 테스트는 하드웨어/장시간 대기 없이, sd.InputStream을 '콜백을 마음대로 멈출 수
있는' 가짜로 갈아끼워 TFSyncThread.run()의 실제 제어흐름을 그대로 실행한다.

  - test_transient_stall_recovers : 콜백이 멈췄다 다시 흐르면(절전 복귀) 같은 장치를
                                    재오픈해 되살아나고, 'device removed'는 안 나온다.
  - test_real_removal_disconnects : 콜백이 완전히 정지하면(진짜 뽑힘) 재오픈을 반복
                                    시도하다 결국 'device removed'로 정상 판정한다.

⚠️ 실제 2초 워치독 타이머를 그대로 쓰므로 ~10초 걸린다(느림). selfcheck 회귀 게이트와
   분리해 pytest로만 돌린다:  python3 -m pytest tests/test_stall_recovery.py -v

격리 필수(CLAUDE.md): 사용자 실제 settings/captures 를 절대 건드리지 않도록 임시경로 강제.
"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['WSA2_SETTINGS_PATH'] = '/tmp/wsa2_pytest_stall_settings.json'   # setdefault 아님 — 강제 격리
os.environ['WSA2_CAPTURES_PATH'] = '/tmp/wsa2_pytest_stall_captures.json'

import sys
import time
import threading

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import wayaudo2  # noqa: F401  (모듈/구조 게이트)
from spectra.ui import tf_window as TF
from PyQt5.QtCore import Qt


class _FakeStream:
    """콜백을 우리가 통제하는 가짜 sd.InputStream.
    클래스변수 FEED=True 동안만 콜백을 먹여준다(False=stall/뽑힘). instances=재오픈 횟수."""
    instances = 0
    FEED = True

    def __init__(self, **kw):
        _FakeStream.instances += 1
        self._cb = kw['callback']
        self._bs = kw.get('blocksize') or 512
        self._nch = kw.get('channels') or 2
        self.blocksize = self._bs
        self.latency = 0.04
        self._run = False
        self._t = None

    def __enter__(self):
        self._run = True
        bs = self._bs or 512

        def pump():
            while self._run:
                if _FakeStream.FEED:
                    try:
                        self._cb(np.zeros((bs, self._nch), dtype=np.float32), bs, None, None)
                    except Exception:
                        pass
                time.sleep(0.005)   # ~200 콜백/초

        self._t = threading.Thread(target=pump, daemon=True)
        self._t.start()
        return self

    def __exit__(self, *a):
        self._run = False
        return False

    def abort(self, *a, **k):
        self._run = False

    def close(self, *a, **k):
        self._run = False


@pytest.fixture
def patched_tf(monkeypatch):
    """가짜 스트림 주입 + caffeinate 무력화. 원복은 monkeypatch가 자동 처리."""
    _FakeStream.instances = 0
    _FakeStream.FEED = True
    monkeypatch.setattr(TF, 'sd', type('X', (), {'InputStream': _FakeStream})())
    monkeypatch.setattr(TF, 'begin_no_sleep', lambda: None)
    monkeypatch.setattr(TF, 'end_no_sleep', lambda: None)
    return _FakeStream


def _run_thread_with(controller):
    th = TF.TFSyncThread(device_idx=0, sample_rate=48000, fft_size=16384, ref_ch=0, meas_ch=1)
    ev = {'disconnected': 0, 'frames': 0}
    th.disconnected_signal.connect(lambda m: ev.__setitem__('disconnected', ev['disconnected'] + 1),
                                   Qt.DirectConnection)
    th.frame_ready.connect(lambda a, b: ev.__setitem__('frames', ev['frames'] + 1),
                           Qt.DirectConnection)
    c = threading.Thread(target=lambda: controller(th), daemon=True)
    c.start()
    th.run()          # 실제 로직 동기 실행(가짜 스트림 상대)
    c.join(timeout=1)
    return ev


def test_transient_stall_recovers(patched_tf):
    """콜백이 멈췄다 다시 흐르면 재오픈으로 되살아나고, 가짜 'device removed'는 없다."""
    def controller(th):
        time.sleep(0.6)                     # 정상 콜백 흐름
        patched_tf.FEED = False             # stall 시작
        time.sleep(3.0)                     # 2초+ → stall 감지 → 재오픈
        patched_tf.FEED = True              # 절전 복귀처럼 다시 흐르게
        time.sleep(1.5)                     # 재오픈 후 정상화
        th.running = False

    ev = _run_thread_with(controller)
    assert patched_tf.instances >= 2, f'재오픈 안 됨(스트림 {patched_tf.instances}회 생성)'
    assert ev['disconnected'] == 0, '가짜 device-removed 발생'
    assert ev['frames'] > 0, '프레임 수신 없음'


def test_real_removal_disconnects(patched_tf, monkeypatch):
    """콜백이 완전히 멈추면(진짜 뽑힘) 재오픈 반복 실패 후 device_removed로 판정한다."""
    # 실제 임계는 6이지만(selfcheck에서 검증) 여기선 빠르게: 2회 실패면 포기.
    monkeypatch.setattr(TF, 'classify_stall',
                        lambda n, **k: 'disconnect' if n >= 2 else 'reopen')

    def controller(th):
        time.sleep(0.6)                     # 정상 콜백 흐름
        patched_tf.FEED = False             # 완전히 멈춤(계속 유지)
        time.sleep(8.0)                     # 재오픈 반복 실패 → 포기 유도
        th.running = False

    ev = _run_thread_with(controller)
    assert ev['disconnected'] >= 1, 'device_removed 미발생(진짜 제거를 못 잡음)'
    assert patched_tf.instances >= 2, '재오픈 시도 없이 바로 포기'
