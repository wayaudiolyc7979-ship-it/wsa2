"""세션 로깅 + 진단(_diag) + 크래시 핸들러 — v2.0 분해(동작 0 변경).

import 시점에 로그파일 생성·루트로거 핸들러·excepthook·오래된로그 정리를 수행한다
(wayaudo2가 최상단에서 import → 종전과 동일 시점). WSA2_LOG_DIR/WSA2_DEBUG 존중.
"""
import os, sys, logging
import datetime as _dt
import platform as _pl
import traceback as _tb

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
    _sh = logging.StreamHandler()
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
