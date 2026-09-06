"""세션 로깅 + 진단(_diag) + 크래시 핸들러 — v2.0 분해(동작 0 변경).

import 시점에 로그파일 생성·루트로거 핸들러·excepthook·오래된로그 정리를 수행한다
(wayaudo2가 최상단에서 import → 종전과 동일 시점). WSA2_LOG_DIR/WSA2_DEBUG 존중.
"""
import os, sys, logging
import threading as _threading
import datetime as _dt
import platform as _pl
import traceback as _tb
from contextlib import contextmanager

# ─── 세션 로그 (macOS: ~/Library/Logs/WSA2 / Windows: %LOCALAPPDATA%\WSA2\Logs) ───
# WSA2_LOG_DIR 로 위치 오버라이드 가능 — Parallels 등 VM에서 공유폴더로 로그를 빼
# 호스트(맥)에서 바로 읽을 때 유용. 미설정 시 기존 플랫폼 기본 경로 그대로(동작 변화 없음).
_LOG_DIR = os.environ.get('WSA2_LOG_DIR') or (
    os.path.join(os.environ.get('LOCALAPPDATA', os.path.expanduser('~')), 'WSA2', 'Logs')
    if _pl.system() == 'Windows'
    else os.path.expanduser('~/Library/Logs/WSA2'))
os.makedirs(_LOG_DIR, exist_ok=True)
_LOG_TS   = _dt.datetime.now().strftime('%Y%m%d_%H%M%S')
_LOG_PATH = os.path.join(_LOG_DIR, f'wsa2_{_LOG_TS}.log')
_fh = logging.FileHandler(_LOG_PATH, encoding='utf-8')
_fh.setFormatter(logging.Formatter(
    '%(asctime)s.%(msecs)03d [%(levelname)s] %(message)s', datefmt='%H:%M:%S'))
_root_log = logging.getLogger()
_root_log.addHandler(_fh); _root_log.setLevel(logging.DEBUG)
_alog = logging.getLogger('wsa2')

# ── 자기검증/세션분석용 진단 로깅 ──────────────────────────────────────
# 파일엔 항상 DEBUG 전부 기록. WSA2_DEBUG=1 이면 콘솔(stderr)에도 라이브 출력(개발/검증용).
_DEBUG = bool(os.environ.get('WSA2_DEBUG'))
if _DEBUG:
    # ⚠️ 기본 StreamHandler는 sys.stderr(=fd 2)로 쓴다. 그런데 _no_stderr()가 측정 중
    #    스트림 수명 내내 fd 2를 /dev/null로 돌려두므로, 그대로 두면 **측정을 시작한
    #    순간부터 콘솔 미러가 통째로 무음**이 된다(장시간 오작동을 봐야 할 바로 그때).
    #    import 시점의 fd 2를 따로 복제해 그쪽으로 쓰면 리다이렉트와 무관하게 살아 있다.
    try:
        _stderr_stream = os.fdopen(os.dup(2), 'w', buffering=1)
    except Exception:
        _stderr_stream = None
    _sh = logging.StreamHandler(_stderr_stream) if _stderr_stream else logging.StreamHandler()
    _sh.setFormatter(logging.Formatter(
        '%(asctime)s.%(msecs)03d [%(levelname)s] %(message)s', datefmt='%H:%M:%S'))
    _root_log.addHandler(_sh)

def _diag(tag, **kv):
    """진단 스냅샷 — grep 쉬운 '[DIAG]' 프리픽스로 핵심 상태/이벤트를 세션 로그에 남김.
    Claude가 화면 캡쳐 없이 로그만으로 동작을 검증할 수 있도록. 절대 예외를 던지지 않음."""
    try:
        if kv:
            _alog.info('[DIAG] %s  %s', tag, '  '.join(f'{k}={v}' for k, v in kv.items()))
        else:
            _alog.info('[DIAG] %s', tag)
    except Exception:
        pass

def _cleanup_logs(max_keep=20):
    try:
        logs = sorted([f for f in os.listdir(_LOG_DIR)
                       if f.startswith('wsa2_') and f.endswith('.log')])
        for old in logs[:-max_keep]:
            try: os.remove(os.path.join(_LOG_DIR, old))
            except Exception: pass
    except Exception: pass
_cleanup_logs()

def _crash_handler(exc_type, exc_val, exc_tb):
    _alog.critical('=== UNCAUGHT EXCEPTION ===')
    for line in _tb.format_exception(exc_type, exc_val, exc_tb):
        _alog.critical(line.rstrip())
    _alog.critical(f'Log file: {_LOG_PATH}')
    sys.__excepthook__(exc_type, exc_val, exc_tb)
sys.excepthook = _crash_handler


_NO_STDERR_LOCK = _threading.Lock()
_no_stderr_depth = 0      # 중첩/동시 진입 수
_no_stderr_saved = None   # 최초 진입 시 저장한 원래 fd 2


@contextmanager
def _no_stderr():
    """C 레벨 AUHAL/PortAudio 경고 메시지를 억제하는 컨텍스트 매니저.
    v2.0: engine·tf_window 양쪽이 써서 저수준 공용 모듈에 배치(순환 회피).

    ⚠️ 여러 스레드가 동시에 쓴다(캡처 스레드마다 스트림 수명 전체를 감싼다).
    예전엔 각자 fd 2를 저장·복원해서, 두 스레드가 겹치면 **나중에 진입한 쪽이
    '이미 /dev/null인 fd 2'를 원본으로 저장**하고, 먼저 나간 쪽이 그걸 복원하는 바람에
    이후 프로세스 내내 stderr가 /dev/null에 고착됐다 — 장시간 오작동을 디버깅해야 할
    바로 그 순간에 `WSA2_DEBUG` 콘솔이 죽는다.
    락 + 참조카운트로 '최초 진입에서만 리다이렉트, 마지막 이탈에서만 복원'하게 한다."""
    global _no_stderr_depth, _no_stderr_saved
    with _NO_STDERR_LOCK:
        if _no_stderr_depth == 0:
            _fd = os.open(os.devnull, os.O_WRONLY)
            _no_stderr_saved = os.dup(2)
            os.dup2(_fd, 2); os.close(_fd)
        _no_stderr_depth += 1
    try:
        yield
    finally:
        with _NO_STDERR_LOCK:
            _no_stderr_depth -= 1
            if _no_stderr_depth <= 0:
                _no_stderr_depth = 0
                if _no_stderr_saved is not None:
                    os.dup2(_no_stderr_saved, 2); os.close(_no_stderr_saved)
                    _no_stderr_saved = None
