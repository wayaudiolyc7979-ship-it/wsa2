"""오디오 캡처 스레드 공용 워치독 유틸 — v2.0.

장시간(예: 1시간+) 측정 마이크가 조용히 멈추는 증상 대응. 두 가지를 제공한다:

1) begin_no_sleep()/end_no_sleep() — 측정 중 macOS idle 시스템 절전을 막아
   (caffeinate) 콜백이 절전으로 멈추는 근본 트리거를 차단. refcount 기반이라
   여러 캡처 스레드(Spectrum/TF/Stereo)가 겹쳐도 하나라도 살아있으면 유지.
2) StreamStalled — 콜백이 한 번 이상 흐른 뒤 멈춘(running-stall) 상태 예외.
   스레드가 물리적 제거로 단정(disconnected)하지 말고 같은 장치를 재오픈하도록
   유도한다. 연속 재오픈이 계속 콜백을 못 받으면 그때 비로소 제거로 판정.
"""
import os
import sys
import threading
import subprocess

from spectra.core.logging_diag import _alog, _diag


class StreamStalled(Exception):
    """콜백이 한 번 이상 흐른 뒤 2초+ 멈춤. 물리적 제거가 아닐 수 있으므로(절전/App
    Nap/일시 글리치) 같은 config로 스트림을 재오픈해야 함. 연속 재오픈이 계속 콜백을
    못 받으면 그때 물리적 제거로 판정(disconnected_signal)."""
    pass


# 연속 재오픈이 이 횟수만큼 콜백을 못 받으면 '진짜 장치 제거'로 판정.
# 절전/App Nap 복귀는 보통 1회 재오픈에 콜백 재개 → 이 예산은 콜백 재개 시 리셋됨.
MAX_DEAD_REOPENS = 6


def classify_stall(consecutive_dead_reopens, max_dead=MAX_DEAD_REOPENS):
    """running-stall 후 연속 실패 재오픈 횟수로 다음 행동 결정.
    'reopen' = 같은 장치 재오픈 재시도, 'disconnect' = 물리적 제거로 판정."""
    return 'disconnect' if consecutive_dead_reopens >= max_dead else 'reopen'


# ── idle 시스템 절전 방지 (측정 중) ─────────────────────────────
_sleep_lock = threading.Lock()
_sleep_refcount = 0
_caffeinate_proc = None


def begin_no_sleep():
    """측정 캡처 시작 시 호출 — idle 시스템 절전을 막는다(macOS caffeinate).
    refcount 기반: 캡처 스레드가 하나라도 살아있으면 절전 차단 유지.
    macOS 외 플랫폼에서는 refcount만 유지(무동작)."""
    global _sleep_refcount, _caffeinate_proc
    with _sleep_lock:
        _sleep_refcount += 1
        if _sleep_refcount > 1 or sys.platform != 'darwin':
            return
        try:
            # -i: idle 시스템 절전 방지 / -w PID: 이 프로세스 종료 시 caffeinate 자동 종료
            _caffeinate_proc = subprocess.Popen(
                ['caffeinate', '-i', '-w', str(os.getpid())],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            _diag('no_sleep_begin', pid=_caffeinate_proc.pid)
        except Exception as e:
            _caffeinate_proc = None
            _alog.warning(f'begin_no_sleep 실패(caffeinate 미가용): {e}')


def end_no_sleep():
    """캡처 스레드 종료 시 호출 — refcount 0이 되면 절전 차단 해제."""
    global _sleep_refcount, _caffeinate_proc
    with _sleep_lock:
        if _sleep_refcount <= 0:
            return
        _sleep_refcount -= 1
        if _sleep_refcount > 0:
            return
        p = _caffeinate_proc
        _caffeinate_proc = None
    if p is not None:
        try:
            p.terminate()
        except Exception:
            pass
        _diag('no_sleep_end')
