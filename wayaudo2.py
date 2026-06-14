11#!/usr/bin/env python3
# ═══════════════════════════════════════════════════
#  SPECTRA — Spectrum Analyzer  (by WAYAUDIO)  v1.3
#  ✅ FFT 버벅임 수정 (포인트 다운샘플링)
#  ✅ 마이크 캘리브레이션 (94/114dB @ 1kHz)
#  ✅ dBA / dBC 실시간 레벨
#  ✅ LEQ A/C 시간 평균 (5~60분)
#  ✅ 친근한 디자인 + 야외 라이트 테마
# ═══════════════════════════════════════════════════
import sys, math, time, json, os, logging, atexit, signal, threading
sys.setswitchinterval(0.001)   # GIL 스위치 간격 1ms — 오디오 콜백 최대 대기 시간 제한

def _emergency_cleanup():
    try:
        import sounddevice as _sd
        _sd.stop()
        time.sleep(0.05)
    except Exception:
        pass

atexit.register(_emergency_cleanup)
signal.signal(signal.SIGTERM, lambda *_: (_emergency_cleanup(), sys.exit(0)))
import datetime as _dt
import traceback as _tb
import hmac as _hmac, hashlib as _hs, base64 as _b64, struct as _st
import subprocess as _sp, platform as _pl
import numpy as np
import ctypes as _ctypes
_devnull_fd = os.open(os.devnull, os.O_WRONLY)
_saved_stderr_fd = os.dup(2)
os.dup2(_devnull_fd, 2); os.close(_devnull_fd)
import sounddevice as sd
os.dup2(_saved_stderr_fd, 2); os.close(_saved_stderr_fd)
from collections import deque
import contextlib as _cl

@_cl.contextmanager
def _no_stderr():
    """C 레벨 AUHAL/PortAudio 경고 메시지를 억제하는 컨텍스트 매니저."""
    _fd = os.open(os.devnull, os.O_WRONLY)
    _sv = os.dup(2); os.dup2(_fd, 2); os.close(_fd)
    try: yield
    finally: os.dup2(_sv, 2); os.close(_sv)

# ─── 세션 로그 (macOS: ~/Library/Logs/WSA2 / Windows: %LOCALAPPDATA%\WSA2\Logs) ───
if _pl.system() == 'Windows':
    _LOG_DIR = os.path.join(os.environ.get('LOCALAPPDATA', os.path.expanduser('~')), 'WSA2', 'Logs')
else:
    _LOG_DIR = os.path.expanduser('~/Library/Logs/WSA2')
os.makedirs(_LOG_DIR, exist_ok=True)
_LOG_TS   = _dt.datetime.now().strftime('%Y%m%d_%H%M%S')
_LOG_PATH = os.path.join(_LOG_DIR, f'wsa2_{_LOG_TS}.log')
_fh = logging.FileHandler(_LOG_PATH, encoding='utf-8')
_fh.setFormatter(logging.Formatter(
    '%(asctime)s.%(msecs)03d [%(levelname)s] %(message)s', datefmt='%H:%M:%S'))
_root_log = logging.getLogger()
_root_log.addHandler(_fh); _root_log.setLevel(logging.DEBUG)
_alog = logging.getLogger('wsa2')

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

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QVBoxLayout, QHBoxLayout, QComboBox,
    QPushButton, QLabel, QSizePolicy, QFrame,
    QGroupBox, QDialog, QSpinBox, QDoubleSpinBox,
    QFormLayout, QDialogButtonBox, QScrollArea,
    QSplashScreen, QSplitter, QStackedWidget, QColorDialog,
    QLineEdit, QProgressBar, QCheckBox, QGridLayout,
    QStylePainter, QStyleOptionComboBox, QStyle, QToolBar,
    QRadioButton, QButtonGroup, QSlider
)
from PyQt5.QtCore  import Qt, QTimer, pyqtSignal, QThread, QMutex, QMutexLocker, QPoint, QPointF, QRect, QRectF, QSize, QPropertyAnimation, QEasingCurve, QEvent, QObject
from PyQt5.QtWidgets import QShortcut
from PyQt5.QtGui   import (
    QPainter, QColor, QPen, QFont, QCursor,
    QLinearGradient, QConicalGradient, QBrush, QPainterPath,
    QRadialGradient, QPalette, QImage, QPixmap, QPolygon, QPolygonF, QKeySequence
)
import math as _math

# ═══════════════════════════════════════════════════════════════════
#  라이선스 관리
# ═══════════════════════════════════════════════════════════════════
_LIC_SECRET = b'W4y4ud10_WSA2_Lic_\xde\xad\xbe\xef\x01\x23\x45\x67'

if _pl.system() == 'Windows':
    _LIC_DIR = os.path.join(os.environ.get('APPDATA', os.path.expanduser('~')), 'WAYAUDIO')
else:
    _LIC_DIR = os.path.expanduser('~/Library/Application Support/WAYAUDIO')
_LIC_PATH = os.path.join(_LIC_DIR, 'wsa2.lic')

def _get_machine_id() -> str:
    """하드웨어 시리얼 번호 기반 12자리 머신 ID. 포맷 후에도 동일하게 유지됨."""
    serial = ''
    try:
        if _pl.system() == 'Windows':
            # BIOS 시리얼 번호 (포맷해도 불변)
            out = _sp.check_output(
                ['wmic', 'bios', 'get', 'SerialNumber', '/value'],
                timeout=5, text=True, stderr=_sp.DEVNULL)
            for ln in out.splitlines():
                if ln.upper().startswith('SERIALNUMBER='):
                    serial = ln.split('=', 1)[-1].strip(); break
            # wmic 결과가 비어있으면 PowerShell로 재시도 (Windows 11 대응)
            if not serial:
                out = _sp.check_output(
                    ['powershell', '-NoProfile', '-Command',
                     '(Get-CimInstance Win32_BIOS).SerialNumber'],
                    timeout=5, text=True, stderr=_sp.DEVNULL)
                serial = out.strip()
        else:
            # macOS: system_profiler
            out = _sp.check_output(
                ['system_profiler', 'SPHardwareDataType'],
                timeout=5, text=True, stderr=_sp.DEVNULL)
            for ln in out.splitlines():
                if 'Serial Number' in ln:
                    serial = ln.split(':')[-1].strip(); break
    except Exception:
        pass
    if not serial:
        serial = _pl.node()  # 최후 폴백: hostname
    raw = f'WSA2:{serial}:{_pl.machine()}'.encode()
    return _hs.sha256(raw).hexdigest()[:12].upper()

def verify_license(key: str, machine_id: str = None) -> tuple:
    """(valid:bool, reason:str) 반환."""
    if machine_id is None:
        machine_id = _get_machine_id()
    try:
        clean = key.upper().replace('-', '').replace(' ', '')
        pad = (8 - len(clean) % 8) % 8
        data = _b64.b32decode(clean + '=' * pad)
        sig      = data[:10]
        payload  = data[10:]
        expected = _hmac.new(_LIC_SECRET, payload, _hs.sha256).digest()[:10]
        if not _hmac.compare_digest(sig, expected):
            return False, '유효하지 않은 시리얼 키입니다.'
        parts = payload.decode().split(':')
        key_mid, expiry_str = parts[0], parts[1]
        if key_mid != machine_id[:12]:
            return False, '이 컴퓨터에 발급된 키가 아닙니다.'
        expiry = int(expiry_str)
        if expiry > 0 and _dt.date.today().year > expiry:
            return False, f'라이선스가 {expiry}년에 만료되었습니다.'
        return True, 'OK'
    except Exception:
        return False, '키 형식이 올바르지 않습니다.'

def load_license():
    try:
        with open(_LIC_PATH, 'r') as f: return f.read().strip()
    except Exception: return None

def save_license(key: str):
    os.makedirs(_LIC_DIR, exist_ok=True)
    with open(_LIC_PATH, 'w') as f: f.write(key.strip())

def check_license_at_startup() -> bool:
    """저장된 키 검증. True=통과, False=라이선스 없음/무효."""
    key = load_license()
    if not key: return False
    valid, _ = verify_license(key)
    return valid


# ═══════════════════════════════════════════════════════════════════
#  라이선스 입력 다이얼로그
# ═══════════════════════════════════════════════════════════════════
class LicenseDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('SPECTRA — 라이선스 활성화'); _apply_dark_titlebar(self)
        self.setFixedSize(460, 310)
        self.setWindowFlags(Qt.Dialog | Qt.MSWindowsFixedSizeDialogHint)
        self._mid = _get_machine_id()
        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self); lay.setSpacing(14); lay.setContentsMargins(24, 20, 24, 20)

        title = QLabel('SPECTRA')
        title.setStyleSheet('font-size:17px;font-weight:bold;color:#4E7DF0;letter-spacing:4px;')
        lay.addWidget(title)

        # 머신 ID 표시
        mid_box = QFrame(); mid_box.setFrameShape(QFrame.StyledPanel)
        mid_box.setStyleSheet('background:#1C1C1E;border:1px solid #38383A;border-radius:6px;')
        mid_lay = QVBoxLayout(mid_box); mid_lay.setContentsMargins(12,8,12,8); mid_lay.setSpacing(4)
        mid_lbl = QLabel('이 컴퓨터의 머신 ID (개발자에게 전달):')
        mid_lbl.setStyleSheet('font-size:11px;color:#8E8E93;')
        self._mid_val = QLabel(self._mid)
        self._mid_val.setStyleSheet('font-size:16px;font-weight:bold;color:#FFFFFF;letter-spacing:2px;font-family:"Courier New";')
        self._mid_val.setTextInteractionFlags(Qt.TextSelectableByMouse)
        copy_btn = QPushButton('머신 ID 복사')
        copy_btn.setFixedWidth(110)
        copy_btn.setStyleSheet('background:#2C2C2E;color:#4E7DF0;border:1px solid #4E7DF0;border-radius:4px;padding:3px;font-size:10px;')
        copy_btn.clicked.connect(self._copy_mid)
        mid_row = QHBoxLayout(); mid_row.addWidget(self._mid_val); mid_row.addStretch(); mid_row.addWidget(copy_btn)
        mid_lay.addWidget(mid_lbl); mid_lay.addLayout(mid_row)
        lay.addWidget(mid_box)

        # 시리얼 키 입력
        key_lbl = QLabel('시리얼 키 입력:')
        key_lbl.setStyleSheet('font-size:12px;color:#FFFFFF;')
        self._key_edit = QLineEdit()
        self._key_edit.setPlaceholderText('XXXXX-XXXXX-XXXXX-XXXXX-XXXXX-XXXXX-XXXX')
        self._key_edit.setStyleSheet('font-size:13px;font-family:"Courier New";padding:6px;border:1px solid #38383A;border-radius:6px;background:#1C1C1E;color:#FFFFFF;')
        self._key_edit.textChanged.connect(self._on_key_changed)
        lay.addWidget(key_lbl); lay.addWidget(self._key_edit)

        # 상태 메시지
        self._status = QLabel('')
        self._status.setStyleSheet('font-size:11px;color:#FF453A;')
        lay.addWidget(self._status)

        # 버튼
        btn_row = QHBoxLayout()
        quit_btn = QPushButton('종료')
        quit_btn.setFixedWidth(80)
        quit_btn.clicked.connect(self.reject)
        self._act_btn = QPushButton('활성화')
        self._act_btn.setFixedWidth(100)
        self._act_btn.setEnabled(False)
        self._act_btn.setStyleSheet('background:#4E7DF0;color:#FFFFFF;font-weight:bold;border-radius:6px;padding:6px;')
        self._act_btn.clicked.connect(self._activate)
        btn_row.addWidget(quit_btn); btn_row.addStretch(); btn_row.addWidget(self._act_btn)
        lay.addLayout(btn_row)

    def _copy_mid(self):
        QApplication.clipboard().setText(self._mid)
        self._status.setStyleSheet('font-size:11px;color:#33FF66;')
        self._status.setText('머신 ID가 클립보드에 복사되었습니다.')

    def _on_key_changed(self, text):
        self._act_btn.setEnabled(len(text.replace('-','').replace(' ','')) >= 10)
        self._status.setText('')

    def _activate(self):
        key = self._key_edit.text().strip()
        valid, reason = verify_license(key, self._mid)
        if valid:
            save_license(key)
            _alog.info(f'라이선스 활성화 성공  machine={self._mid}')
            self._status.setStyleSheet('font-size:11px;color:#33FF66;')
            self._status.setText('활성화 성공!')
            QTimer.singleShot(800, self.accept)
        else:
            _alog.warning(f'라이선스 활성화 실패  reason={reason}  machine={self._mid}')
            self._status.setStyleSheet('font-size:11px;color:#FF453A;')
            self._status.setText(reason)


# ───────────────────────────────────────────
#  상수
# ───────────────────────────────────────────
MAX_DB = 0
CAPTURE_COLORS = ['#69f0ae','#ffff00','#ff80ab','#ea80fc',
                  '#ff6e6e','#80d8ff','#ffd740','#ccff90']
SPEED_LEVELS = [
    ("Slowest", 0.950, 0.030, 0.05),
    ("Slow",    0.900, 0.060, 0.10),
    ("Normal",  0.800, 0.120, 0.20),
    ("Fast",    0.650, 0.200, 0.35),
    ("Fastest", 0.450, 0.300, 0.55),
]
THIRD_OCT = [
    20,25,31.5,40,50,63,80,100,125,160,200,250,
    315,400,500,630,800,1000,1250,1600,2000,2500,
    3150,4000,5000,6300,8000,10000,12500,16000,20000
]
def make_oct_bands(bpo):
    bands, ratio = [], 2**(1/bpo)
    fc = 1000.0
    while fc/ratio > 15: fc /= ratio
    while fc <= 22000:
        if 18 <= fc <= 20000: bands.append(round(fc,4))
        fc *= ratio
    return bands
BANDS = {'oct3':THIRD_OCT,'oct12':make_oct_bands(12),'oct24':make_oct_bands(24)}
FREQ_MARKS = [31.5, 63, 125, 250, 500, 1000, 2000, 4000, 8000, 16000]

# ───────────────────────────────────────────
#  설정 저장/불러오기
# ───────────────────────────────────────────
if _pl.system() == 'Windows':
    _APP_SUPPORT = os.path.join(os.environ.get('APPDATA', os.path.expanduser('~')), 'WSA2')
else:
    _APP_SUPPORT = os.path.expanduser('~/Library/Application Support/WSA2')
_SETTINGS_PATH = os.path.join(_APP_SUPPORT, 'settings.json')
_CAPTURES_PATH = os.path.join(_APP_SUPPORT, 'captures.json')
_CAPTURES_LOCK = threading.Lock()   # captures.json 동시 읽기-수정-쓰기 보호 (백그라운드 저장용)

def _load_settings():
    try:
        with open(_SETTINGS_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}

def _save_settings(data):
    os.makedirs(os.path.dirname(_SETTINGS_PATH), exist_ok=True)
    with open(_SETTINGS_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def _load_captures_file():
    try:
        with open(_CAPTURES_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}

def _save_captures_file(data):
    try:
        os.makedirs(os.path.dirname(_CAPTURES_PATH), exist_ok=True)
        with open(_CAPTURES_PATH, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception as e:
        _alog.warning(f'캡처 저장 실패: {e}')

# A-가중치 계수 (IEC 61672)
def a_weight_db(f):
    if f < 10: return -100
    f2 = f*f; f4 = f2*f2
    ra = (12200**2 * f4) / ((f2+20.6**2)*math.sqrt((f2+107.7**2)*(f2+737.9**2))*(f2+12200**2))
    return 20*math.log10(max(ra,1e-20)) + 2.0

# C-가중치 계수
def c_weight_db(f):
    if f < 10: return -100
    f2 = f*f
    rc = (12200**2 * f2) / ((f2+20.6**2)*(f2+12200**2))
    return 20*math.log10(max(rc,1e-20)) + 0.06

# ───────────────────────────────────────────
#  테마
# ───────────────────────────────────────────
THEMES = {
    'dark': {
        'bg':        '#000000',
        'bg2':       '#1C1C1E',
        'bg3':       '#2C2C2E',
        'panel':     '#242426',
        'border':    '#38383A',
        'text':      '#FFFFFF',
        'text_dim':  '#8E8E93',
        'graph_txt': '#9CA0A8',
        'accent':    '#4E7DF0',
        'accent2':   '#FF9F0A',
        'accent3':   '#9B5DE5',
        'green':     '#33FF66',
        'yellow':    '#FFD60A',
        'red':       '#FF453A',
        'grid':      '#282828',
        'grid_ref':  '#404040',
        'spec_fill_top': (51,255,102,230),
        'spec_fill_bot': (51,255,102,180),
        'spec_line':     '#33FF66',
        'peak_line':     '#FF9F0A',
    },
    'light': {   # Crisp White — 라이트그레이 캔버스 위 흰 서피스가 '떠 보이는' 레이어드 룩 (2026-06-14 리파인 pass2)
        'bg':       '#E7EDF6',   # 캔버스: 살짝 깊은 쿨그레이 → 흰 패널/툴바가 elevation으로 떠 보임
        'bg2':      '#FFFFFF',   # 팝업/드롭다운: 깨끗한 흰 카드
        'bg3':      '#DCE4F0',
        'panel':    '#FFFFFF',
        'border':   '#CBD5E4',   # 살짝 더 또렷한 하어라인
        'text':     '#16213A',
        'text_dim': '#5A6B86',
        'graph_txt': '#46566e',
        'accent':   '#2E54C8',
        'accent2':  '#cc4c00',
        'accent3':  '#6a3fb0',
        'green':    '#0e7c30',
        'yellow':   '#8c6600',
        'red':      '#b81818',
        'grid':     '#D7DFEC',
        'grid_ref': '#BECBDD',
        'spec_fill_top': (22,112,204,120),
        'spec_fill_bot': (22,112,204,8),
        'spec_line':     '#1670cc',
        'peak_line':     '#cc4c00',
    }
}
_theme = 'dark'
def T(key): return THEMES[_theme][key]

# ── 디자인 토큰 (UI 통일 단일 소스) ──────────────────────
# 위젯 스타일시트용 폰트 크기 (px) — 컴팩트 4단 스케일
FS_XS, FS_SM, FS_BODY, FS_LG = 9, 10, 11, 13
# 큰 수치 표시 (px) — 정보패널/라우드니스 메트릭
FS_VAL, FS_DISP = 14, 18                     # 보조 큰 값(LAeq/LCeq) / 표시 값(dBA·dBC)
FS_METRIC, FS_METRIC_BIG = 20, 27            # 라우드니스 메트릭(M/S/LRA) / 강조(I/TP)
# 캔버스 QPainter 폰트 (pt) 역할별
CF_AXIS, CF_MODE, CF_ANNO = 10, 8, 9       # TF 축 눈금 / 모드 제목 / 주석
CF_CUR_TITLE, CF_CUR_VAL  = 16, 13          # 커서 정보박스 주파수 / 값
CF_GRID, CF_BADGE, CF_TINY = 12, 20, 7      # Spectrum FFT/Oct 축 / Dominant badge / VU 초소형 타이틀
# 모서리·패딩 (2단계: 툴바 컨트롤 / 카드 내부 소형)
RADIUS_CTRL, RADIUS_SM = 7, 5               # 툴바 콤보(전역 QSS 7)와 맞춤 / 카드·소형
PAD_CTRL, PAD_SM = '2px 8px', '1px 4px'

# 앱 전체 글꼴 — 한 곳에서 교체 (캔버스 텍스트 + 위젯 공통). 후보: 'Avenir Next'(지오메트릭·세련),
# 'Helvetica Neue'(클래식), '.AppleSystemUIFont'(SF Pro 시스템), 'Arial'(구 기본)
FONT_FAMILY = 'Segoe UI' if _pl.system() == 'Windows' else 'Optima'   # Optima는 맥 전용 → Windows는 Segoe UI

def _qfont(pt, bold=False):
    f = QFont(FONT_FAMILY, pt); f.setBold(bold); return f


# Lucide(MIT) 아이콘 — 24x24 viewBox inner SVG + filled 여부. 손그림 대비 일관·세련.
_LUCIDE_ICONS = {
    'search':   ('<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>', False),
    'folder':   ('<path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/>', False),
    'hourglass':('<path d="M5 22h14"/><path d="M5 2h14"/><path d="M17 22v-4.172a2 2 0 0 0-.586-1.414L12 12l-4.414 4.414A2 2 0 0 0 7 17.828V22"/><path d="M7 2v4.172a2 2 0 0 0 .586 1.414L12 12l4.414-4.414A2 2 0 0 0 17 6.172V2"/>', False),
    'download': ('<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" x2="12" y1="15" y2="3"/>', False),
    'bolt':     ('<polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>', True),
    'sun':      ('<circle cx="12" cy="12" r="4"/><path d="M12 2v2"/><path d="M12 20v2"/><path d="m4.93 4.93 1.41 1.41"/><path d="m17.66 17.66 1.41 1.41"/><path d="M2 12h2"/><path d="M20 12h2"/><path d="m6.34 17.66-1.41 1.41"/><path d="m19.07 4.93-1.41 1.41"/>', False),
    'moon':     ('<path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/>', False),
    'sliders':  ('<line x1="21" x2="14" y1="4" y2="4"/><line x1="10" x2="3" y1="4" y2="4"/><line x1="21" x2="12" y1="12" y2="12"/><line x1="8" x2="3" y1="12" y2="12"/><line x1="21" x2="16" y1="20" y2="20"/><line x1="12" x2="3" y1="20" y2="20"/><line x1="14" x2="14" y1="2" y2="6"/><line x1="8" x2="8" y1="10" y2="14"/><line x1="16" x2="16" y1="18" y2="22"/>', False),
    'delta':    ('<polygon points="12 4 21 20 3 20 12 4"/>', False),
    'play':     ('<polygon points="6 3 20 12 6 21 6 3"/>', True),
    'stop':     ('<rect width="15" height="15" x="4.5" y="4.5" rx="3"/>', True),
    'mic':      ('<path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" x2="12" y1="19" y2="22"/>', False),
    'refresh':  ('<path d="M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/>', False),
    'check':    ('<path d="M20 6 9 17l-5-5"/>', False),
    'info':     ('<circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>', False),
    'audio-lines':('<path d="M2 10v3"/><path d="M6 6v11"/><path d="M10 3v18"/><path d="M14 8v7"/><path d="M18 5v13"/><path d="M22 10v3"/>', False),
    'extlink':  ('<path d="M15 3h6v6"/><path d="M10 14 21 3"/><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>', False),
}

def _svg_render(p, inner, color, size, filled=False):
    """Lucide inner SVG를 주어진 색으로 painter에 렌더 (size x size, 24 viewBox)."""
    from PyQt5.QtSvg import QSvgRenderer
    from PyQt5.QtCore import QByteArray
    attrs = (f'fill="{color}" stroke="none"' if filled else
             f'fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"')
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" {attrs}>{inner}</svg>'
    QSvgRenderer(QByteArray(svg.encode())).render(p, QRectF(0, 0, size, size))

def _icon(name, size=16, color=None):
    """단색 벡터 아이콘 — Lucide(MIT) SVG를 테마색으로 렌더. Retina 2x.
    color 미지정 시 테마 적응(다크=밝은 회색 / 라이트=짙은 회색). 호출부는 기존과 동일."""
    from PyQt5.QtGui import QIcon
    from PyQt5.QtSvg import QSvgRenderer
    from PyQt5.QtCore import QByteArray
    if color is None:
        color = '#C7CAD1' if _theme == 'dark' else '#46566e'
    s = size; dpr = 2
    pm = QPixmap(s * dpr, s * dpr); pm.setDevicePixelRatio(dpr); pm.fill(Qt.transparent)
    entry = _LUCIDE_ICONS.get(name)
    if entry is None:
        return QIcon(pm)
    inner, filled = entry
    if filled:
        attrs = f'fill="{color}" stroke="none"'
    else:
        attrs = f'fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"'
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" {attrs}>{inner}</svg>'
    p = QPainter(pm); p.setRenderHint(QPainter.Antialiasing, True)
    QSvgRenderer(QByteArray(svg.encode())).render(p, QRectF(0, 0, s, s))
    p.end()
    return QIcon(pm)


def _txn_icon(playing, sz=14):
    """트랜스포트 버튼 아이콘 — 재생/시작=로고블루 play, 정지=빨강 stop."""
    return _icon('stop' if playing else 'play', sz, color=T('red') if playing else T('accent'))


def _txn_style(color_key):
    """트랜스포트 버튼 틴트 스타일 — 은은한 컬러 워시 펄(브랜드)."""
    c = QColor(T(color_key)); r, g, b = c.red(), c.green(), c.blue()
    return (f'QPushButton{{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,'
            f'stop:0 rgba({r},{g},{b},46), stop:1 rgba({r},{g},{b},20));'
            f'color:{T(color_key)};border:1px solid rgba({r},{g},{b},150);'
            f'font-weight:700;padding:3px 12px;border-radius:7px;}}'
            f'QPushButton:hover{{border-color:rgba({r},{g},{b},210);}}'
            f'QPushButton:disabled{{background:{T("panel")};color:{T("text_dim")};border-color:{T("border")};}}')


def _apply_txn(btn, playing):
    """모든 트랜스포트(Start/Play/Stop) 통일 — 시작/재생=로고블루 틴트, 정지=레드 틴트 + 아이콘."""
    if playing:
        btn.setStyleSheet(_txn_style('red'));    btn.setIcon(_icon('stop', 14, color=T('red')))
    else:
        btn.setStyleSheet(_txn_style('accent')); btn.setIcon(_icon('play', 14, color=T('accent')))


class _DarkTitleBar(QWidget):
    """프레임리스 창용 다크 커스텀 타이틀바 — 제목 + 닫기(✕) + 드래그 이동.
    라이트모드에서 흰색 네이티브 타이틀바가 다크 본문과 안 어울리는 문제 해결."""
    def __init__(self, win, title='', aux=None):
        super().__init__()
        self._win = win; self._drag = None
        self.setFixedHeight(34); self.setObjectName('darkTitleBar')
        self.setStyleSheet(f'#darkTitleBar{{background:{T("bg2")};}}')
        lay = QHBoxLayout(self); lay.setContentsMargins(14, 0, 8, 0); lay.setSpacing(0)
        self._full_title = title
        self._title = QLabel(title)
        self._title.setStyleSheet(f'color:{T("text")};font-size:12px;font-weight:bold;background:transparent;')
        self._title.setMinimumWidth(0)
        lay.addWidget(self._title); lay.addStretch()
        # 창별 보조 버튼(예: SPL Meter 설정 토글) — ✕ 왼쪽에 배치
        self._aux = list(aux) if aux else []
        if aux:
            for b in aux:
                b.setParent(self); lay.addWidget(b)
            lay.addSpacing(6)
        self._x = QPushButton('✕'); self._x.setFixedSize(24, 24); self._x.setCursor(Qt.PointingHandCursor)
        self._x.setStyleSheet('QPushButton{border:none;background:transparent;color:#9A9AA0;font-size:13px;border-radius:6px;}'
                              'QPushButton:hover{background:#FF453A;color:#FFFFFF;}')
        self._x.clicked.connect(self._close)
        lay.addWidget(self._x)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._elide_title()

    def _elide_title(self):
        # 우측 고정폭(보조버튼 + spacing + ✕) 제외한 공간에 맞춰 제목 elide → 글자 중간 잘림 방지
        right = sum(b.sizeHint().width() for b in self._aux) + (6 if self._aux else 0) + 24
        avail = self.width() - 14 - 8 - right
        self._title.setText(self._title.fontMetrics().elidedText(
            self._full_title, Qt.ElideRight, max(0, avail)))

    def _close(self):
        if hasattr(self._win, 'reject'):
            self._win.reject()
        else:
            self._win.close()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag = e.globalPos() - self._win.frameGeometry().topLeft(); e.accept()

    def mouseMoveEvent(self, e):
        if self._drag is not None and (e.buttons() & Qt.LeftButton):
            self._win.move(e.globalPos() - self._drag); e.accept()

    def mouseReleaseEvent(self, e):
        self._drag = None


def _add_resize_grip(win):
    """프레임리스 창에 우하단 리사이즈 그립 — 네이티브 프레임 리사이즈 대체."""
    from PyQt5.QtWidgets import QSizeGrip
    grip = QSizeGrip(win); grip.setFixedSize(15, 15); grip.setStyleSheet('background:transparent;')
    win._dark_grip = grip
    def _pos():
        try: grip.move(win.width() - 17, win.height() - 17); grip.raise_(); grip.show()
        except Exception: pass
    class _RF(QObject):
        def eventFilter(self, o, e):
            if e.type() == QEvent.Resize: _pos()
            return False
    f = _RF(win); win._dark_grip_filter = f; win.installEventFilter(f)
    QTimer.singleShot(0, _pos)


def _apply_dark_titlebar(win, resizable=False, aux=None):
    """창을 프레임리스로 + 다크 커스텀 타이틀바 부착(레이아웃 menuBar 슬롯).
    resizable=True 면 우하단 리사이즈 그립 추가. 바 삽입은 레이아웃 준비 후로 지연.
    aux: ✕ 왼쪽에 넣을 보조 버튼 리스트(창별 토글 등)."""
    try:
        win.setWindowFlags((win.windowFlags() | Qt.FramelessWindowHint))
    except Exception:
        return
    def _ins():
        try:
            lay = win.layout()
            if lay is not None and lay.menuBar() is None:
                bar = _DarkTitleBar(win, win.windowTitle(), aux=aux)
                win._dark_titlebar = bar
                lay.setMenuBar(bar)
        except Exception:
            pass
    QTimer.singleShot(0, _ins)
    if resizable:
        _add_resize_grip(win)


class _SettingsBtn(QPushButton):
    """타이틀바용 설정 버튼 — 누르면 SPL 설정창 오픈. 슬라이더(컨트롤) 아이콘을 직접 그림."""
    def __init__(self):
        super().__init__()
        self.setFixedSize(26, 24); self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet('QPushButton{border:none;background:transparent;border-radius:6px;}'
                           'QPushButton:hover{background:rgba(255,255,255,30);}')

    def paintEvent(self, e):
        super().paintEvent(e)   # hover 배경
        col = QColor('#9A9AA0')
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        pen = QPen(col, 1.6); pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        y1, y2 = 9, 15
        p.drawLine(6, y1, 20, y1)
        p.drawLine(6, y2, 20, y2)
        p.setPen(Qt.NoPen); p.setBrush(col)
        p.drawEllipse(13, y1 - 3, 6, 6)   # 윗줄 knob (오른쪽)
        p.drawEllipse(7,  y2 - 3, 6, 6)   # 아랫줄 knob (왼쪽)
        p.end()


class _ResetMaxBtn(QPushButton):
    """타이틀바용 컴팩트 아이콘 — Max 리셋. 원형 리셋 화살표(↺)를 직접 그림."""
    def __init__(self):
        super().__init__()
        self.setFixedSize(26, 24); self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet('QPushButton{border:none;background:transparent;border-radius:6px;}'
                           'QPushButton:hover{background:rgba(255,255,255,30);}')

    def paintEvent(self, e):
        super().paintEvent(e)   # hover 배경
        col = QColor('#9A9AA0')
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        pen = QPen(col, 1.6); pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen); p.setBrush(Qt.NoBrush)
        # 원호(약 300°, 위쪽 틈) — 중심(13,12) 반지름 6
        rect = QRectF(7, 6, 12, 12)
        p.drawArc(rect, 60 * 16, 280 * 16)
        # 화살촉 — 원호 시작점(우상단 틈) 근처에 작은 삼각형
        p.setPen(Qt.NoPen); p.setBrush(col)
        ax, ay = 13 + 6 * math.cos(math.radians(60)), 12 - 6 * math.sin(math.radians(60))
        p.drawPolygon(QPolygonF([
            QPointF(ax, ay - 1), QPointF(ax + 4, ay), QPointF(ax, ay + 4)]))
        p.end()


# ── SPECTRA 로고 마크 (정적 그라디언트 웨이브 SVG → QPixmap 캐시; 라이브 렌더 아님 → 속도 무관)
_SPECTRA_MARK_SVG = (
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 110 60">'
    b'<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="0">'
    b'<stop offset="0" stop-color="#1FA2FF"/><stop offset="0.28" stop-color="#4E7DF0"/>'
    b'<stop offset="0.52" stop-color="#9B5DE5"/><stop offset="0.72" stop-color="#F15BB5"/>'
    b'<stop offset="0.86" stop-color="#FF9F0A"/><stop offset="1" stop-color="#FF453A"/>'
    b'</linearGradient></defs>'
    b'<path d="M2,42 C12,42 14,30 20,30 S26,46 31,40 S37,8 44,18 S50,52 56,34 '
    b'S62,4 70,26 S76,50 83,38 S90,22 96,30 S104,40 108,38" fill="none" '
    b'stroke="url(#g)" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/></svg>'
)
# 시그니처 그라디언트 — Qt 스타일시트용 (헤더 언더라인 등)
_SPECTRA_GRAD_QSS = ('qlineargradient(x1:0,y1:0,x2:1,y2:0,'
                     'stop:0 #1FA2FF, stop:0.28 #4E7DF0, stop:0.52 #9B5DE5,'
                     'stop:0.72 #F15BB5, stop:0.86 #FF9F0A, stop:1 #FF453A)')
_spectra_mark_cache = {}
def _spectra_mark(h=22):
    """그라디언트 웨이브 마크 QPixmap(높이 h px). 한 번만 렌더 후 캐시 (속도 영향 0)."""
    try:
        dpr = QApplication.primaryScreen().devicePixelRatio() if QApplication.instance() else 1.0
    except Exception:
        dpr = 1.0
    w = int(round(h * 110 / 60))
    key = (w, h, round(dpr, 2))
    pm = _spectra_mark_cache.get(key)
    if pm is not None:
        return pm
    try:
        from PyQt5.QtCore import QByteArray
        from PyQt5.QtSvg import QSvgRenderer
        r = QSvgRenderer(QByteArray(_SPECTRA_MARK_SVG))
        pm = QPixmap(max(1, int(w * dpr)), max(1, int(h * dpr))); pm.fill(Qt.transparent)
        p = QPainter(pm); p.setRenderHint(QPainter.Antialiasing); r.render(p); p.end()
        pm.setDevicePixelRatio(dpr)
    except Exception:
        pm = QPixmap(1, 1); pm.fill(Qt.transparent)   # QtSvg 없으면 빈 마크(워드마크만 표시)
    _spectra_mark_cache[key] = pm
    return pm


def ss_text(size=FS_BODY, color_key='text_dim', bold=False):
    """라벨/텍스트용 스타일시트 문자열. (전역 QWidget 배경 상속 방지 위해 투명 배경 명시)"""
    return f'color:{T(color_key)};background:transparent;font-size:{size}px;' + ('font-weight:bold;' if bold else '')

def ss_pill_btn(color_key='text_dim', size=FS_XS, radius=RADIUS_SM):
    """투명 배경 + 테두리 알약 버튼 스타일 (hover 시 accent)."""
    return (f'QPushButton{{background:transparent;color:{T(color_key)};border:1px solid {T("border")};'
            f'border-radius:{radius}px;font-size:{size}px;padding:{PAD_SM};}}'
            f'QPushButton:hover{{color:{T("accent")};border-color:{T("accent")};}}')

def ss_input(size=FS_SM, radius=RADIUS_SM):
    """스핀박스/입력류 스타일."""
    return (f'background:{T("panel")};color:{T("text")};border:1px solid {T("border")};'
            f'border-radius:{radius}px;padding:{PAD_SM};font-size:{size}px;')

def ss_spin(size=FS_BODY, radius=6, min_w=80):
    """다이얼로그 스핀박스 공통 스타일 — 패널 배경 + up/down 버튼 숨김."""
    return (f'QDoubleSpinBox, QSpinBox {{ background:{T("panel")}; color:{T("text")};'
            f'border:1px solid {T("border")}; padding:3px 8px; border-radius:{radius}px;'
            f'min-width:{min_w}px; font-size:{size}px; }}'
            f'QDoubleSpinBox::up-button, QSpinBox::up-button {{ width:0; border:none; }}'
            f'QDoubleSpinBox::down-button, QSpinBox::down-button {{ width:0; border:none; }}')

def ss_dialog_btns():
    """다이얼로그 OK/Cancel 버튼박스 공통 스타일 — OK(default)=로고블루 주동작, Cancel=중립."""
    a = QColor(T('accent')); ar, ag, ab = a.red(), a.green(), a.blue()
    return (
        f'QPushButton{{background:{T("panel")};color:{T("text")};'
        f'border:1px solid {T("border")};border-radius:6px;padding:5px 18px;font-size:12px;min-width:68px;}}'
        f'QPushButton:hover{{border-color:{T("accent")};}}'
        f'QPushButton:default{{background:{T("accent")};color:#FFFFFF;'
        f'border:1px solid {T("accent")};font-weight:600;}}'
        f'QPushButton:default:hover{{background:rgba({ar},{ag},{ab},210);}}')

def ss_btn_primary(size=12):
    """다이얼로그 주동작 버튼 — 로고블루 채움."""
    a = QColor(T('accent')); ar, ag, ab = a.red(), a.green(), a.blue()
    return (f'QPushButton{{background:{T("accent")};color:#FFFFFF;'
            f'border:1px solid {T("accent")};border-radius:6px;padding:5px 16px;'
            f'font-size:{size}px;font-weight:600;min-width:60px;}}'
            f'QPushButton:hover{{background:rgba({ar},{ag},{ab},210);}}'
            f'QPushButton:disabled{{background:{T("panel")};color:{T("text_dim")};border-color:{T("border")};}}')

def ss_btn_neutral(size=12):
    """다이얼로그 보조/취소 버튼 — 중립."""
    return (f'QPushButton{{background:{T("panel")};color:{T("text")};'
            f'border:1px solid {T("border")};border-radius:6px;padding:5px 16px;'
            f'font-size:{size}px;min-width:60px;}}'
            f'QPushButton:hover{{border-color:{T("accent")};}}'
            f'QPushButton:disabled{{color:{T("text_dim")};}}')

def hsep(color_key='border'):
    """1px 수평 구분선. QFrame.HLine 의 베벨/이중선 없이 깔끔한 단색 라인."""
    f = QFrame(); f.setFixedHeight(1)
    f.setStyleSheet(f'background:{T(color_key)};border:none;')
    return f


def _sep_line_color():
    return '#4A4A4A' if _theme == 'dark' else T('border')


def _splitter_qss():
    """3탭 공통 스플리터 핸들 — 얇고 차분한 하이라인 구분선(테마 적응). 분석창 구분선 통일용."""
    sep = _sep_line_color()
    return (f'QSplitter::handle{{background:{T("bg")};}}'
            f'QSplitter::handle:vertical{{border-top:1px solid {sep};}}'
            f'QSplitter::handle:horizontal{{border-left:1px solid {sep};}}'
            f'QSplitter::handle:hover{{background:{T("bg3")};}}')

# ───────────────────────────────────────────
#  Bar gradient presets
# ───────────────────────────────────────────
BAR_PRESETS = [
    ("Default",  (0,229,255,200), (0,100,200,20)),
    ("Warm",     (255,140,0,220), (255,60,0,20)),
    ("Green",    (57,255,20,220), (20,180,0,20)),
    ("Purple",   (200,80,255,220),(100,0,200,20)),
    ("Sunset",   (255,220,0,220), (255,30,80,30)),
    ("Mono",     (220,230,240,220),(100,120,140,20)),
]
_bar_preset_idx = 0  # 0 = Default (follows theme)
_custom_color = None  # (R,G,B) — macOS color picker로 선택한 색상


def bar_top():
    if _custom_color is not None:
        return (*_custom_color, 200)
    if _bar_preset_idx == 0:
        return T('spec_fill_top')
    return BAR_PRESETS[_bar_preset_idx][1]

def bar_bot():
    if _custom_color is not None:
        return (*_custom_color, 40)
    if _bar_preset_idx == 0:
        return T('spec_fill_bot')
    return BAR_PRESETS[_bar_preset_idx][2]

# ───────────────────────────────────────────
#  좌표 변환
# ───────────────────────────────────────────
def freq_to_x(f, pad_l, usable, ny=24000):
    if f <= 0: return pad_l
    return pad_l + (math.log10(max(f,1)/20) / math.log10(ny/20)) * usable

# 1/3옥타브 보조 그리드 (옥타브선 사이) — Smaart 스타일 촘촘한 로그 그리드용
FREQ_MARKS_MINOR = [20,25,40,50,80,100,160,200,315,400,630,800,
                    1250,1600,2500,3150,5000,6300,10000,12500,20000]

def draw_freq_minor_grid(p, pl, pr, uw, pt, pb, W, H, ny):
    """1/3옥타브 보조 세로 그리드선 — 옥타브선보다 '흐리게'(behind). FREQ_MARKS 주선 직전 호출.
    '흐리게'의 방향은 배경에 따라 반대: 다크=어둡게(검정쪽), 라이트=밝게(흰쪽). 안 그러면 라이트에서
    보조선이 옥타브선보다 진해져 위계가 뒤집힘."""
    minor = QColor(T('grid')).lighter(116) if _theme == 'light' else QColor(T('grid')).darker(150)
    p.setPen(QPen(minor, 1, Qt.SolidLine))
    for f in FREQ_MARKS_MINOR:
        if f < 20 or f > ny: continue
        fx = freq_to_x(f, pl, uw, ny)
        if not pl <= fx <= W - pr: continue
        p.drawLine(int(fx), pt, int(fx), H - pb)

def db_to_y(db, draw_h, db_min, db_max):
    db = max(db_min, min(db_max, db))
    rng = db_max - db_min
    return int((db_max - db) / rng * draw_h) if rng > 0 else 0

def x_to_freq(x, pad_l, usable, ny=24000):
    r = max(0.0, min(1.0, (x-pad_l)/usable))
    return 20*(ny/20)**r

def y_to_db(y, draw_h, db_min, db_max):
    return db_max - (y/max(draw_h,1))*(db_max-db_min)

# ───────────────────────────────────────────
#  커서 정보창
# ───────────────────────────────────────────
def draw_info_box(p, W, freq_str, db_str, pk_str=None):
    # 폭 계산과 실제 그리기를 같은 토큰으로 → 박스 폭/텍스트 정합
    p.setFont(_qfont(CF_CUR_TITLE, True))
    fw = p.fontMetrics().horizontalAdvance(freq_str)
    p.setFont(_qfont(CF_CUR_VAL, True))
    dw = p.fontMetrics().horizontalAdvance(db_str)
    pw = p.fontMetrics().horizontalAdvance(pk_str) if pk_str else 0
    bw = max(fw,dw,pw)+40; bh=90 if pk_str else 66
    bx = W//2-bw//2; by=14
    for off,alp in [(5,15),(3,30),(2,50)]:
        # 라이트: 흰 배경에서 카드가 떠 보이도록 은은한 뉴트럴 드롭섀도(파란 띠 X)
        ring = QColor(20,33,58, max(6, alp//2)) if _theme=='light' else QColor(78,125,240,alp)
        p.setPen(QPen(ring, off*2)); p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(bx-off,by-off,bw+off*2,bh+off*2,10,10)
    p.setPen(QPen(QColor(T('accent')),2))
    p.setBrush(QBrush(QColor(T('panel')) if _theme=='light' else QColor(0,0,0,230)))
    p.drawRoundedRect(bx,by,bw,bh,8,8)
    p.setFont(_qfont(CF_CUR_TITLE, True)); p.setPen(QColor(T('accent')))
    p.drawText(bx,by+4,bw,30,Qt.AlignHCenter|Qt.AlignVCenter,freq_str)
    p.setPen(QPen(QColor(T('border')),1))
    p.drawLine(bx+12,by+36,bx+bw-12,by+36)
    p.setFont(_qfont(CF_CUR_VAL, True)); p.setPen(QColor(T('accent2')))
    p.drawText(bx,by+36,bw,28,Qt.AlignHCenter|Qt.AlignVCenter,db_str)
    if pk_str:
        p.setPen(QPen(QColor(T('border')),1))
        p.drawLine(bx+12,by+62,bx+bw-12,by+62)
        p.setFont(_qfont(CF_CUR_VAL, True)); p.setPen(QColor('#FFB300'))
        p.drawText(bx,by+62,bw,26,Qt.AlignHCenter|Qt.AlignVCenter,pk_str)

def draw_dom_badge(p, plot_right, plot_top, dom_fs, dom_db, unit='dB'):
    """우상단 고정 배지: 가장 큰 레벨의 주파수 + dB/dBSPL."""
    txt = f'▲  {dom_fs}   {dom_db:.1f} {unit}'
    p.setFont(_qfont(CF_BADGE, True))
    tw = p.fontMetrics().horizontalAdvance(txt)
    bw = tw + 24; bh = 36
    bx = plot_right - bw - 6; by = plot_top + 5
    if _theme == 'light':
        # 라이트: 흰 카드 + 은은한 보더 (검정 박스 대신)
        p.setPen(QPen(QColor(T('border')), 1)); p.setBrush(QBrush(QColor(T('panel'))))
    else:
        p.setPen(Qt.NoPen); p.setBrush(QBrush(QColor(0, 0, 0, 220)))
    p.drawRoundedRect(bx, by, bw, bh, 4, 4)
    p.setPen(QColor(T('accent')))
    p.drawText(bx, by, bw, bh, Qt.AlignHCenter | Qt.AlignVCenter, txt)

def _auto_capture_color(n):
    """황금 비율 HSV 순환으로 구분이 잘 되는 색 자동 반환."""
    hue = (n * 0.618033988) % 1.0
    return QColor.fromHsvF(hue, 0.90, 0.98).name()

def _catmull_seg(px, py):
    """Catmull-Rom 스플라인 → QPainterPath.  직선 lineTo 대신 cubicTo 로 부드러운 곡선."""
    n = len(px)
    path = QPainterPath()
    if n == 0: return path
    path.moveTo(float(px[0]), float(py[0]))
    if n < 2: return path
    for i in range(1, n):
        i0 = max(0, i - 2); i3 = min(n - 1, i + 1)
        x0, y0 = float(px[i0]), float(py[i0])
        x1, y1 = float(px[i-1]), float(py[i-1])
        x2, y2 = float(px[i]),   float(py[i])
        x3, y3 = float(px[i3]), float(py[i3])
        cp1x = x1 + (x2 - x0) / 6
        cp1y = y1 + (y2 - y0) / 6
        cp2x = x2 - (x3 - x1) / 6
        cp2y = y2 - (y3 - y1) / 6
        path.cubicTo(cp1x, cp1y, cp2x, cp2y, x2, y2)
    return path

# ───────────────────────────────────────────
#  오디오 스레드
# ───────────────────────────────────────────
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
                                      callback=cb, latency=lat, dtype='float32')

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
_MC_COLORS = ['#00D4FF','#FF8C00','#44FF88','#FF4488','#FFDD00','#AA66FF','#FF6644','#00FFCC']


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

    def run(self):
        self.running = True
        n_ch  = max(self.channels) + 1
        bufs  = {ch: np.zeros(self.fft_size, dtype=np.float32) for ch in self.channels}
        _last_emit = [0.0]
        _last_cb   = [time.monotonic()]
        _got_cb    = [False]   # 첫 콜백 수신 여부 — 시작 지연을 끊김으로 오판 방지

        def cb(indata, frames, ti, status):
            if not self.running: return
            try:
                _last_cb[0] = time.monotonic(); _got_cb[0] = True
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
                                  callback=cb, latency=lat, dtype='float32')

        def _run(bs, lat):
            try:
                with _no_stderr(), _open(bs, lat) as _s:
                    self._active_stream = _s
                    try:
                        _alog.info(f'[DIAG] InputStream opened dev={self.device_idx} ch={n_ch} '
                                   f'req(bs={bs},lat={lat}) actual(bs={_s.blocksize},lat={_s.latency})')
                    except Exception: pass
                    _last_cb[0] = time.monotonic()
                    while self.running:
                        self.msleep(500)
                        if _got_cb[0] and time.monotonic() - _last_cb[0] > 2.0:
                            self.disconnected_signal.emit('device removed')
                            return True
                return False
            except Exception: raise
            finally:
                self._active_stream = None

        # force_latency='high': 큰 하드웨어 버퍼(제너레이터 안정) 유지 + blocksize 512(잦은 콜백)
        # → 공유 스트림을 TF와 함께 써도 Spectrum 청크당 스무딩 속도가 정상 유지됨.
        _attempts = [(512, self.force_latency), (2048, self.force_latency)] if self.force_latency else [(512,'low'),(512,'high'),(0,'high')]
        last_err = None
        for round_n in range(2):
            for (bs, lat) in _attempts:
                try:
                    if _run(bs, lat): return
                    return
                except Exception as e:
                    last_err = e; continue
            if round_n == 0:
                for _ in range(15):
                    if not self.running: return
                    self.msleep(100)
        if last_err: self.error_signal.emit(str(last_err))

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
        if self.thread is None or need != self.union or need_lat != self.force_latency:
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

    def active_devices(self):
        return list(self._streams.keys())

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


class TFSyncThread(QThread):
    """Ref와 Meas가 같은 장치의 다른 채널일 때 단일 InputStream으로 샘플 동기화.
    두 채널을 동일 콜백에서 읽어 타이밍 오프셋을 완전히 제거.
    frame_ready(ref_buf, meas_buf)로 두 버퍼를 원자적으로 전달."""
    frame_ready  = pyqtSignal(object, object)   # (ref_buf, meas_buf) — 단일 이벤트
    error_signal = pyqtSignal(str)
    disconnected_signal = pyqtSignal(str)   # 작동 중 물리적 연결 끊김

    def __init__(self, device_idx, sample_rate, fft_size, ref_ch, meas_ch):
        super().__init__()
        self.device_idx = device_idx
        self.sample_rate = sample_rate; self.fft_size = fft_size
        self.ref_ch = ref_ch; self.meas_ch = meas_ch
        self.running = False
        self._active_stream = None   # stop()에서 abort()로 즉시 장치 해제

    def run(self):
        self.running = True
        blocksize = min(self.fft_size // 4, 2048)
        n_ch = max(self.ref_ch, self.meas_ch) + 1
        ref_buf  = np.zeros(self.fft_size, dtype=np.float32)
        meas_buf = np.zeros(self.fft_size, dtype=np.float32)
        r_ch = self.ref_ch; m_ch = self.meas_ch
        _last_cb = [time.monotonic()]   # watchdog: USB 제거 감지
        _got_cb = [False]   # 첫 콜백 수신 여부 — 시작 지연을 끊김으로 오판 방지

        def cb(indata, frames, ti, status):
            try:
                if not self.running: return
                _last_cb[0] = time.monotonic(); _got_cb[0] = True   # 콜백 살아있음 갱신
                nc = indata.shape[1]
                rc = min(r_ch, nc - 1); mc = min(m_ch, nc - 1)
                ref_buf[:-frames]  = ref_buf[frames:];  ref_buf[-frames:]  = indata[:frames, rc]
                meas_buf[:-frames] = meas_buf[frames:]; meas_buf[-frames:] = indata[:frames, mc]
                self.frame_ready.emit(ref_buf.copy(), meas_buf.copy())
            except Exception: pass

        last_err = None
        for round_n in range(2):
            for bs in (blocksize, 0):
                try:
                    with _no_stderr():
                        with sd.InputStream(device=self.device_idx, samplerate=self.sample_rate,
                                            channels=n_ch, blocksize=bs,
                                            callback=cb, latency='high', dtype='float32') as _s:
                            self._active_stream = _s
                            _last_cb[0] = time.monotonic()
                            try:
                                while self.running:
                                    self.msleep(10)
                                    # macOS AUHAL은 USB 제거 후에도 active=True 유지 →
                                    # 콜백이 흐르다 2초 이상 끊기면 물리적 끊김으로 판단
                                    # (첫 콜백 받은 뒤에만 — 같은장치 in/out 시작 지연 오판 방지)
                                    if _got_cb[0] and time.monotonic() - _last_cb[0] > 2.0:
                                        self.disconnected_signal.emit('device removed')
                                        return
                            finally:
                                self._active_stream = None
                    return  # 정상 종료
                except Exception as e:
                    last_err = e
                    if not self.running: return
            if round_n == 0:
                for _ in range(15):   # AUHAL 해제 대기 (running 반응형)
                    if not self.running: return
                    self.msleep(100)
        if last_err: self.error_signal.emit(str(last_err))

    def stop(self):
        self.running = False
        s = self._active_stream
        if s is not None:
            try: s.abort(ignore_errors=True)
            except Exception:
                try: s.close(ignore_errors=True)
                except Exception: pass
        if not self.wait(3000):
            _alog.warning('TFSyncThread stop(): wait timeout — stream forced abort')



# ───────────────────────────────────────────
#  FFT 캔버스 — ★ 다운샘플링으로 포인트 수 제한
# ───────────────────────────────────────────
class FFTCanvas(QWidget):
    PAD_L=40; PAD_R=10; PAD_T=12; PAD_B=28
    MAX_POINTS=600   # primary 곡선 포인트 수
    MAX_POINTS_EXTRA=600   # 추가 곡선 포인트 수 (원복: primary 와 동일)
    _cap_built = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setMinimumSize(300,150)
        self.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Expanding)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WA_OpaquePaintEvent,True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.db_min=-96; self.db_max=MAX_DB
        self.freqs=None; self.avg=None; self.peak=None
        self.peak_hold=True; self.scale_log=True
        self.sample_rate=48000; self.fft_size=16384
        self._mx=-1; self._my=-1
        self.peak_hold_frames=30         # 기본 1초 홀드 (30fps 기준)
        self.peak_decay_rate_pk=20.0/30.0  # 20 dB/s 고정 낙하
        self._peak_age=None
        self._cache=None
        self._ds_f=None; self._ds_avg=None; self._ds_pk=None
        self._captures=[]
        self._cap_pix=None; self._cap_pix_key=None
        self._front_idx=None; self._live_on_top=False
        self.calib_offset=0.0
        self.clipping=False
        self._cap_building = False
        self._cap_img_pending = None; self._cap_key_pending = None
        self._cap_built.connect(self._apply_cap_built)
        self._ch_curves = {}   # {card_id: {'color', 'ds_f', 'ds_avg', 'visible'}}
        self._primary_visible = True
        self._front_id = 0     # 0=primary; 선택된 카드가 맨 앞

    def set_channel_data(self, ch_idx, color, freqs, avg):
        # 소스마다 장치 SR이 다를 수 있어 그 커브 자체의 최대 주파수를 Nyquist로 사용
        ny = float(freqs[-1]) if len(freqs) else self.sample_rate / 2
        mask = (freqs >= 20) & (freqs <= ny)
        f_sel = freqs[mask]; a_sel = avg[mask]
        if len(f_sel) > self.MAX_POINTS_EXTRA:   # 추가 곡선은 포인트 적게 → 멀티 마이크 부드럽게
            log_f = np.logspace(math.log10(20), math.log10(ny), self.MAX_POINTS_EXTRA)
            ds_f = log_f; ds_avg = np.interp(log_f, f_sel, a_sel)
        else:
            ds_f = f_sel; ds_avg = a_sel
        prev = self._ch_curves.get(ch_idx, {})
        self._ch_curves[ch_idx] = {'color': color, 'ds_f': ds_f, 'ds_avg': ds_avg,
                                   'visible': prev.get('visible', True)}
        self.update()

    def clear_channel(self, ch_idx):
        self._ch_curves.pop(ch_idx, None); self.update()

    def clear_all_channels(self):
        self._ch_curves.clear(); self.update()

    def _apply_cap_built(self):
        img, key = self._cap_img_pending, self._cap_key_pending
        self._cap_img_pending = self._cap_key_pending = None
        if img is not None:
            self._cap_pix = QPixmap.fromImage(img)
            self._cap_pix_key = key
            self.update()

    def _trigger_cap_build(self, W, H, cap_key):
        if self._cap_building: return
        self._cap_building = True
        caps = [dict(c) for c in self._captures]
        front = self._front_idx
        threading.Thread(target=self._bg_cap_build,
                         args=(W, H, cap_key, caps, front),
                         daemon=True).start()

    def _bg_cap_build(self, W, H, cap_key, caps, front):
        try:
            img = self._build_cap_img(W, H, caps, front)
            self._cap_img_pending = img
            self._cap_key_pending = cap_key
            self._cap_built.emit()
        except Exception:
            pass
        finally:
            self._cap_building = False

    def _build_cap_img(self, W, H, caps, front):
        from PyQt5.QtGui import QImage
        ny=min(self.sample_rate/2, 20000)
        pl=self.PAD_L; pr=self.PAD_R; pt=self.PAD_T; pb=self.PAD_B
        dh=H-pt-pb; uw=W-pl-pr
        img=QImage(W,H,QImage.Format_ARGB32_Premultiplied); img.fill(0)
        p=QPainter(img); p.setRenderHint(QPainter.Antialiasing,True)
        max_pts = max(int(uw) * 2, 512)
        def _draw_one(cap, emph=False):
            # E 스타일: 선택(front)=밝고 굵은 선, 비선택=흐린 가는 선
            cf=cap['f']; cd=cap['db']
            if self.scale_log:
                cxs=pl+(np.log10(np.maximum(cf,1)/20)/math.log10(ny/20))*uw
            else:
                cxs=pl+(cf/ny)*uw
            cys=pt+np.clip((self.db_max-cd)/max(self.db_max-self.db_min,1)*dh,0,dh)
            n=len(cxs)
            if n > max_pts:
                idx=np.linspace(0,n-1,max_pts,dtype=int)
                cxs=cxs[idx]; cys=cys[idx]
            poly=QPolygonF([QPointF(float(x),float(y)) for x,y in zip(cxs.tolist(),cys.tolist())])
            qc=QColor(cap['color'])
            if emph:
                p.setPen(QPen(qc,2.6))
            else:
                qc.setAlpha(70); p.setPen(QPen(qc,1.2))
            p.drawPolyline(poly)
        for i,cap in enumerate(caps):
            if i==front: continue
            if not cap.get('visible', True): continue
            _draw_one(cap, emph=False)
        if front is not None and 0<=front<len(caps):
            if caps[front].get('visible', True):
                _draw_one(caps[front], emph=True)   # 선택(front) 캡쳐 — 맨 위 + 밝고 굵게
        p.end()
        return img

    def _build_cap_pix(self, W, H):
        ny=min(self.sample_rate/2, 20000)
        img = self._build_cap_img(W, H, list(self._captures), self._front_idx)
        self._cap_pix = QPixmap.fromImage(img)
        self._cap_pix_key = (W, H, self.db_max, self.db_min, self.scale_log, int(ny), self._front_idx, self._live_on_top)

    def add_capture(self, label, color, group=''):
        if self._ds_f is None or self._ds_avg is None: return
        self._captures.append({
            'f': self._ds_f.copy(), 'db': self._ds_avg.copy(),
            'color': color, 'label': label, 'group': group
        })
        self._cap_pix=None; self._last_cap_t=time.monotonic(); self.update()

    def remove_capture(self, idx):
        if 0 <= idx < len(self._captures):
            self._captures.pop(idx)
            if self._front_idx is not None:
                if self._front_idx==idx: self._front_idx=None
                elif self._front_idx>idx: self._front_idx-=1
            self._cap_pix=None; self._last_cap_t=time.monotonic(); self.update()

    def bring_to_front(self, idx):
        if 0 <= idx < len(self._captures):
            self._front_idx=idx; self._live_on_top=False
            self._cap_pix=None; self.update()

    def _draw_live(self, p, W, H, dim=False):
        pl=self.PAD_L; pr=self.PAD_R; pt=self.PAD_T; pb=self.PAD_B
        dh=H-pt-pb; uw=W-pl-pr; ny=min(self.sample_rate/2, 20000)
        # ★ 라이브 곡선은 안티앨리어싱 OFF — Retina 전체화면에서 AA 래스터화가 10배 비쌈
        #   (멀티 마이크 시 FFT 버벅임의 주원인). 격자/라벨은 캐시 픽스맵이라 선명 유지.
        p.setRenderHint(QPainter.Antialiasing, False)
        def _ch_col(c):   # 캡쳐 포커스 시 라이브(채널) 흐리게 (E 스타일)
            qc=QColor(c)
            if dim: qc.setAlpha(55)
            return qc
        f_arr=self._ds_f; a_arr=self._ds_avg
        if f_arr is None or len(f_arr)<2 or a_arr is None or len(a_arr)!=len(f_arr): return
        if not self._primary_visible:
            # 추가 채널만 그리고 종료 (front 인 소스가 맨 마지막)
            for cid, ch_data in sorted(self._ch_curves.items(), key=lambda kv: kv[0]==self._front_id):
                if not ch_data.get('visible', True): continue
                f_c=ch_data['ds_f']; a_c=ch_data['ds_avg']
                if f_c is None or len(f_c)<2: continue
                xc=pl+(np.log10(np.maximum(f_c,1)/20)/math.log10(ny/20))*uw if self.scale_log else pl+(f_c/ny)*uw
                yc=pt+np.clip(((self.db_max-a_c)/(self.db_max-self.db_min)*dh).astype(int),0,dh)
                sc=QPainterPath(); sc.moveTo(float(xc[0]),float(yc[0]))
                for x,y in zip(xc[1:],yc[1:]): sc.lineTo(float(x),float(y))
                p.setPen(QPen(_ch_col(ch_data['color']),1.8)); p.drawPath(sc)
            return
        if self.scale_log:
            xs=pl+(np.log10(np.maximum(f_arr,1)/20)/math.log10(ny/20))*uw
        else:
            xs=pl+(f_arr/ny)*uw
        ys=pt+np.clip(((self.db_max-a_arr)/(self.db_max-self.db_min)*dh).astype(int),0,dh)
        if self.clipping:
            top_col=QColor(T('red')); line_col=QColor(T('red')); pk_col=QColor(T('red'))
        else:
            top_col=QColor(*bar_top()); line_col=QColor(T('spec_line')); pk_col=QColor(T('peak_line'))
        if dim:   # 캡쳐 포커스 시 라이브 채움/선 흐리게
            top_col.setAlpha(36); line_col.setAlpha(70); pk_col.setAlpha(70)
        path=QPainterPath()
        path.moveTo(float(xs[0]),float(H-pb))
        for x,y in zip(xs,ys): path.lineTo(float(x),float(y))
        path.lineTo(float(xs[-1]),float(H-pb)); path.closeSubpath()
        p.fillPath(path,QBrush(top_col))
        stroke=QPainterPath()
        stroke.moveTo(float(xs[0]),float(ys[0]))
        for x,y in zip(xs[1:],ys[1:]): stroke.lineTo(float(x),float(y))
        p.setPen(QPen(line_col,2.0)); p.drawPath(stroke)
        if self.peak_hold and self._ds_pk is not None:
            py_arr=pt+np.clip(((self.db_max-self._ds_pk)/(self.db_max-self.db_min)*dh).astype(int),0,dh)
            visible=self._ds_pk>self._ds_avg+1.5
            if visible.any():
                pk_path=QPainterPath(); in_seg=False
                for i in range(len(xs)):
                    if visible[i]:
                        if not in_seg: pk_path.moveTo(float(xs[i]),float(py_arr[i])); in_seg=True
                        else: pk_path.lineTo(float(xs[i]),float(py_arr[i]))
                    else: in_seg=False
                p.setPen(QPen(pk_col,2.0)); p.drawPath(pk_path)
        # 추가 채널 오버레이 커브 (front 인 소스가 맨 마지막)
        for cid, ch_data in sorted(self._ch_curves.items(), key=lambda kv: kv[0]==self._front_id):
            if not ch_data.get('visible', True): continue
            f_c = ch_data['ds_f']; a_c = ch_data['ds_avg']
            if f_c is None or len(f_c) < 2: continue
            if self.scale_log:
                xc = pl + (np.log10(np.maximum(f_c, 1) / 20) / math.log10(ny / 20)) * uw
            else:
                xc = pl + (f_c / ny) * uw
            yc = pt + np.clip(((self.db_max - a_c) / (self.db_max - self.db_min) * dh).astype(int), 0, dh)
            sc = QPainterPath()
            sc.moveTo(float(xc[0]), float(yc[0]))
            for x, y in zip(xc[1:], yc[1:]): sc.lineTo(float(x), float(y))
            p.setPen(QPen(_ch_col(ch_data['color']), 1.8)); p.drawPath(sc)
        # front 가 primary 면 primary 라인을 맨 위에 다시
        if self._front_id == 0:
            p.setPen(QPen(line_col, 2.4)); p.drawPath(stroke)

    def clear(self):
        self.freqs=None; self.avg=None; self.peak=None
        self._peak_age=None
        self._ds_f=None; self._ds_avg=None; self._ds_pk=None
        self._ch_curves.clear()
        self.update()

    def resizeEvent(self,e): self._cache=None; self.update()

    def _build_cache(self,W,H):
        from PyQt5.QtGui import QPixmap
        dpr=self.devicePixelRatio()
        px=QPixmap(int(W*dpr),int(H*dpr)); px.setDevicePixelRatio(dpr); px.fill(QColor(T('bg')))
        p=QPainter(px)
        p.setRenderHint(QPainter.Antialiasing); p.setRenderHint(QPainter.TextAntialiasing)
        pl=self.PAD_L; pr=self.PAD_R; pt=self.PAD_T; pb=self.PAD_B
        dh=H-pt-pb; uw=W-pl-pr; ny=min(self.sample_rate/2,20000)
        # dB 그리드
        p.setFont(_qfont(CF_GRID))
        for db in range(int(self.db_min),int(self.db_max)+1,12):
            y=pt+db_to_y(db,dh,self.db_min,self.db_max)
            if not pt<=y<=H-pb: continue
            is0=(db==0)
            p.setPen(QPen(QColor(T('grid_ref')),1.5 if is0 else 0.7,Qt.SolidLine))
            p.drawLine(pl,y,W-pr,y)
            p.setPen(QColor(T('graph_txt')))
            p.drawText(2,y-10,pl-12,20,Qt.AlignRight|Qt.AlignVCenter,str(db))
        # 주파수 수직선 + 레이블
        p.setFont(_qfont(CF_GRID, True))
        last_lx=-999
        for f in FREQ_MARKS:
            if f<20 or f>ny: continue
            fx=freq_to_x(f,pl,uw,ny) if self.scale_log else pl+(f/ny)*uw
            if not pl<=fx<=W-pr: continue
            p.setPen(QPen(QColor(T('grid')),1,Qt.SolidLine))
            p.drawLine(int(fx),pt,int(fx),H-pb)
            if fx-last_lx<36: continue
            last_lx=fx
            lf=int(f) if f==int(f) else f
            txt=f'{int(f//1000)}k' if f>=1000 else str(lf)
            tw=p.fontMetrics().horizontalAdvance(txt)
            tx=max(pl,min(int(fx-tw/2),W-pr-tw))
            p.setPen(QColor(T('graph_txt'))); p.drawText(tx,H-5,txt)
        p.end(); self._cache=px

    def _draw_grid_lines(self, p, W, H):
        pl=self.PAD_L; pr=self.PAD_R; pt=self.PAD_T; pb=self.PAD_B
        dh=H-pt-pb; uw=W-pl-pr; ny=min(self.sample_rate/2,20000)
        for db in range(int(self.db_min),int(self.db_max)+1,12):
            y=pt+db_to_y(db,dh,self.db_min,self.db_max)
            if not pt<=y<=H-pb: continue
            is0=(db==0)
            p.setPen(QPen(QColor(T('grid_ref')),1.5 if is0 else 0.7,Qt.SolidLine))
            p.drawLine(pl,y,W-pr,y)
        for f in FREQ_MARKS:
            if f<20 or f>ny: continue
            fx=freq_to_x(f,pl,uw,ny) if self.scale_log else pl+(f/ny)*uw
            if not pl<=fx<=W-pr: continue
            p.setPen(QPen(QColor(T('grid')),1,Qt.SolidLine))
            p.drawLine(int(fx),pt,int(fx),H-pb)

    def _update_peak(self, peak, age, avg):
        updated = avg >= peak
        np.maximum(peak, avg, out=peak)
        age[updated] = 0; age[~updated] += 1
        peak[age > self.peak_hold_frames] -= self.peak_decay_rate_pk
        np.maximum(peak, self.db_min, out=peak)  # 하한 클램프 (그래픽 깨짐 방지)

    def set_data(self,freqs,avg):
        self.freqs=freqs; self.avg=avg
        if self.peak_hold:
            if self.peak is None or len(self.peak)!=len(avg):
                self.peak=avg.copy(); self._peak_age=np.zeros(len(avg),dtype=np.int32)
            else:
                self._update_peak(self.peak, self._peak_age, avg)
        # ★ 다운샘플링: 로그 스케일로 균등 분포된 MAX_POINTS개 주파수만 사용
        ny=self.sample_rate/2
        mask=(freqs>=20)&(freqs<=ny)
        f_sel=freqs[mask]; a_sel=avg[mask]
        if len(f_sel)>self.MAX_POINTS:
            log_f=np.logspace(math.log10(20),math.log10(ny),self.MAX_POINTS)
            a_ds=np.interp(log_f,f_sel,a_sel)
            self._ds_f=log_f; self._ds_avg=a_ds
            if self.peak is not None:
                p_sel=self.peak[mask]
                self._ds_pk=np.interp(log_f,f_sel,p_sel)
        else:
            self._ds_f=f_sel; self._ds_avg=a_sel
            self._ds_pk=self.peak[mask] if self.peak is not None else None
        self.update()

    def reset_peak(self):
        self.peak=None; self._ds_pk=None; self._peak_age=None
    def set_peak_hold(self,v):
        self.peak_hold=v
        if not v: self.reset_peak()
    def set_peak_hold_time(self, hold_frames):
        self.peak_hold_frames = hold_frames
        self.peak_decay_rate_pk = 20.0/30.0  # 20 dB/s 고정 낙하
    def set_db_range(self,lo,hi): self._cache=None; self.db_min=lo; self.db_max=hi; self.update()
    def mouseMoveEvent(self,e): self._mx=e.x(); self._my=e.y(); self.update()
    def leaveEvent(self,e): self._mx=-1; self.update()
    def enterEvent(self,e): self.setFocus()
    def keyPressEvent(self,e):
        win=self.window()
        if e.key()==Qt.Key_Up and hasattr(win,'_db_shift'): win._db_shift(6)
        elif e.key()==Qt.Key_Down and hasattr(win,'_db_shift'): win._db_shift(-6)
        else: super().keyPressEvent(e)
    def mouseDoubleClickEvent(self,e):
        if e.x()<self.PAD_L and self._ds_avg is not None and len(self._ds_avg)>0:
            valid=self._ds_avg[self._ds_avg>-90]
            if len(valid)==0: return
            peak=float(np.max(valid)); span=self.db_max-self.db_min
            self.db_max=int(math.ceil((peak+12)/12))*12
            self.db_min=self.db_max-span; self.update()
    def wheelEvent(self,e):
        if e.modifiers() & Qt.ControlModifier:
            step=1; delta=e.angleDelta().y()
            span=self.db_max-self.db_min
            span=max(20,min(160,span+(-step if delta>0 else step)*2))
            mid=(self.db_max+self.db_min)/2
            self.db_min=mid-span/2; self.db_max=mid+span/2
            self._cache=None; self.update()

    def paintEvent(self,ev):
        W=self.width(); H=self.height()
        if self._cache is None or self._cache.size()!=self.size():
            self._build_cache(W,H)
        p=QPainter(self); p.setRenderHint(QPainter.Antialiasing,True)
        p.drawPixmap(0,0,self._cache)
        pl=self.PAD_L; pr=self.PAD_R; pt=self.PAD_T; pb=self.PAD_B
        dh=H-pt-pb; uw=W-pl-pr; ny=min(self.sample_rate/2, 20000)

        if self._ds_f is None or len(self._ds_f)<2:
            p.end(); return
        f_arr=self._ds_f; a_arr=self._ds_avg
        if a_arr is None or len(a_arr)!=len(f_arr):
            p.end(); return

        # E 포커스: 캡쳐 선택 → 라이브 흐리게 + 선택 캡쳐 밝게(위) / 라이브 포커스 → 캡쳐 흐리게 + 라이브(위)
        _cap_focus = (self._front_idx is not None)
        def _draw_caps():
            if not self._captures: return
            _cap_key=(W,H,self.db_max,self.db_min,self.scale_log,int(ny),self._front_idx,self._live_on_top)
            if self._cap_pix is None or self._cap_pix_key!=_cap_key:
                self._trigger_cap_build(W, H, _cap_key)
            if self._cap_pix is not None:
                p.drawPixmap(0,0,self._cap_pix)
        if _cap_focus:
            self._draw_live(p, W, H, dim=True)
            _draw_caps()
        else:
            _draw_caps()
            self._draw_live(p, W, H, dim=False)
        p.setRenderHint(QPainter.Antialiasing, True)   # 라이브 곡선 후 AA 복원 (격자/라벨/커서 선명)

        self._draw_grid_lines(p, W, H)

        # 우상단 고정 배지: 현재 평균 스펙트럼 최대 주파수 (40 Hz 이상만 탐색)
        valid_mask=f_arr>=40
        if np.any(valid_mask):
            sub=a_arr.copy(); sub[~valid_mask]=-np.inf
            dom_idx=int(np.argmax(sub))
        else:
            dom_idx=int(np.argmax(a_arr))
        dom_f=float(f_arr[dom_idx]); dom_db=float(a_arr[dom_idx])
        dom_fs=f'{dom_f/1000:.2f} kHz' if dom_f>=1000 else f'{dom_f:.0f} Hz'
        unit='dBSPL' if self.calib_offset else 'dB'
        draw_dom_badge(p, W-pr, pt, dom_fs, dom_db, unit)

        # 커서
        if pl<=self._mx<=W-pr:
            cx,cy=self._mx,self._my
            p.setPen(QPen(QColor(T('accent')).lighter(80) if _theme=='light' else QColor(T('accent')),
                         1,Qt.DashLine))
            p.drawLine(cx,pt,cx,H-pb); p.drawLine(pl,cy,W-pr,cy)
            freq=x_to_freq(cx,pl,uw,ny) if self.scale_log else (cx-pl)/uw*ny
            fs=f'{freq/1000:.2f} kHz' if freq>=1000 else f'{freq:.0f} Hz'
            idx=int(np.clip(np.argmin(np.abs(f_arr-freq)),0,len(a_arr)-1))
            db=float(a_arr[idx])
            draw_info_box(p,W,fs,f'{db:.1f} {unit}')
        p.end()

# ───────────────────────────────────────────
#  옥타브 캔버스
# ───────────────────────────────────────────
class OctaveCanvas(QWidget):
    PAD_L=40; PAD_R=10; PAD_T=12; PAD_B=28
    _cap_built = pyqtSignal()
    def __init__(self):
        super().__init__()
        self.setMinimumSize(300,150)
        self.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Expanding)
        self.setMouseTracking(True); self.setAttribute(Qt.WA_OpaquePaintEvent,True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.mode='oct3'
        self.smooth={k:np.full(len(v),-96.0) for k,v in BANDS.items()}
        self.peaks ={k:np.full(len(v),-96.0) for k,v in BANDS.items()}
        self.db_min=-96; self.db_max=MAX_DB
        self.peak_hold=True; self.alpha=1.0-SPEED_LEVELS[2][1]; self.decay=0.08
        self.peak_hold_frames=30           # 기본 1초 홀드 (30fps)
        self.peak_decay_rate_pk=20.0/30.0  # 20 dB/s 고정 낙하
        self._peak_age ={k:np.zeros(len(v),dtype=np.int32) for k,v in BANDS.items()}
        self._cache=None
        self._mx=-1; self._my=-1
        self._ch_oct={}   # {card_id: {'color','values'(oct band dB array),'visible'}} — 멀티-소스 막대 오버레이
        self._front_id=0  # 0=primary; 선택된 카드가 맨 앞
        self._captures=[]
        self._cap_pix=None; self._cap_pix_key=None
        self._front_idx=None; self._live_on_top=False
        self.calib_offset=0.0
        self.clipping=False
        self._cap_building = False
        self._cap_img_pending = None; self._cap_key_pending = None
        self._cap_built.connect(self._apply_cap_built)

    def _apply_cap_built(self):
        img, key = self._cap_img_pending, self._cap_key_pending
        self._cap_img_pending = self._cap_key_pending = None
        if img is not None:
            self._cap_pix = QPixmap.fromImage(img)
            self._cap_pix_key = key
            self.update()

    def _trigger_cap_build(self, W, H, cap_key):
        if self._cap_building: return
        self._cap_building = True
        caps = [dict(c) for c in self._captures]
        front = self._front_idx
        threading.Thread(target=self._bg_cap_build,
                         args=(W, H, cap_key, caps, front),
                         daemon=True).start()

    def _bg_cap_build(self, W, H, cap_key, caps, front):
        try:
            img = self._build_cap_img(W, H, caps, front)
            self._cap_img_pending = img
            self._cap_key_pending = cap_key
            self._cap_built.emit()
        except Exception:
            pass
        finally:
            self._cap_building = False

    def _build_cap_img(self, W, H, caps, front):
        from PyQt5.QtGui import QImage
        pl=self.PAD_L; pr=self.PAD_R; pt=self.PAD_T; pb=self.PAD_B
        dh=H-pt-pb; uw=W-pl-pr
        db_range=max(self.db_max-self.db_min,1)
        bands=BANDS[self.mode]; n=len(bands)
        bar_w=uw/n if n else 1
        gap_r=0.06 if self.mode=='oct24' else 0.08 if self.mode=='oct12' else 0.12
        gap=max(1.0,bar_w*gap_r)
        img=QImage(W,H,QImage.Format_ARGB32_Premultiplied); img.fill(0)
        p=QPainter(img)
        def _draw_one(cap, emph=False):
            # E 스타일: 선택(front)=솔리드 막대(라이브처럼 꽉), 비선택=아주 옅은 채움+옅은 외곽선
            if cap['mode']!=self.mode: return
            cv=cap['values']; qc=QColor(cap['color'])
            if emph:
                for i in range(n):
                    db=float(np.clip(cv[i],self.db_min,self.db_max))
                    bh=max(2,int((db-self.db_min)/db_range*dh))
                    bx=int(pl+i*bar_w+gap/2); bw=max(1,int(bar_w-gap)); by=pt+dh-bh
                    p.fillRect(bx,by,bw,bh,qc)
            else:
                qf=QColor(qc); qf.setAlpha(26); qe=QColor(qc); qe.setAlpha(110)
                for i in range(n):
                    db=float(np.clip(cv[i],self.db_min,self.db_max))
                    bh=max(2,int((db-self.db_min)/db_range*dh))
                    bx=int(pl+i*bar_w+gap/2); bw=max(1,int(bar_w-gap)); by=pt+dh-bh
                    p.fillRect(bx,by,bw,bh,qf)
                    p.setPen(QPen(qe,1)); p.drawRect(bx,by,bw-1,bh-1)
        for i,cap in enumerate(caps):
            if i==front: continue
            if not cap.get('visible', True): continue
            _draw_one(cap, emph=False)
        if front is not None and 0<=front<len(caps):
            if caps[front].get('visible', True):
                _draw_one(caps[front], emph=True)
        p.end()
        return img

    def _build_cap_pix(self, W, H):
        bands=BANDS[self.mode]; n=len(bands)
        pl=self.PAD_L; pr=self.PAD_R; uw=W-pl-pr
        bar_w=uw/n if n else 1
        gap_r=0.06 if self.mode=='oct24' else 0.08 if self.mode=='oct12' else 0.12
        gap=max(1.0,bar_w*gap_r)
        img = self._build_cap_img(W, H, list(self._captures), self._front_idx)
        self._cap_pix = QPixmap.fromImage(img)
        self._cap_pix_key = (W,H,self.db_max,self.db_min,self.mode,round(bar_w*1000),round(gap*1000),self._front_idx,self._live_on_top)

    def add_capture(self, label, color, group=''):
        self._captures.append({
            'values': self.smooth[self.mode].copy(),
            'mode': self.mode, 'color': color, 'label': label, 'group': group
        })
        self._cap_pix=None; self._last_cap_t=time.monotonic(); self.update()

    def remove_capture(self, idx):
        if 0 <= idx < len(self._captures):
            self._captures.pop(idx)
            if self._front_idx is not None:
                if self._front_idx==idx: self._front_idx=None
                elif self._front_idx>idx: self._front_idx-=1
            self._cap_pix=None; self._last_cap_t=time.monotonic(); self.update()

    def bring_to_front(self, idx):
        if 0 <= idx < len(self._captures):
            self._front_idx=idx; self._live_on_top=False
            self._cap_pix=None; self.update()

    def _draw_live(self, p, W, H, dim=False):
        pl=self.PAD_L; pr=self.PAD_R; pt=self.PAD_T; pb=self.PAD_B
        dh=H-pt-pb; uw=W-pl-pr
        db_range=self.db_max-self.db_min
        bands=BANDS[self.mode]; sm=self.smooth[self.mode]; pk=self.peaks[self.mode]
        n=len(bands)
        if n==0 or db_range<=0: return
        bar_w=uw/n
        gap_r=0.06 if self.mode=='oct24' else 0.08 if self.mode=='oct12' else 0.12
        gap=max(1.0,bar_w*gap_r)
        col=QColor(T('red')) if self.clipping else QColor(*bar_top())
        pk_col=QColor(T('red')) if self.clipping else QColor(T('peak_line'))
        if dim:   # 캡쳐 포커스 시 라이브 흐리게 (E 스타일: 선택된 것만 솔리드)
            col.setAlpha(50); pk_col.setAlpha(50)
        for i in range(n):
            db=float(np.clip(sm[i],self.db_min,self.db_max))
            lp=(db-self.db_min)/db_range; bh=max(2,int(lp*dh))
            bx=int(pl+i*bar_w+gap/2); bw=max(1,int(bar_w-gap)); by=pt+dh-bh
            p.fillRect(bx,by,bw,bh,col)
            if self.peak_hold and pk[i]>sm[i]+1.5 and pk[i]>self.db_min+2:
                lp2=float(np.clip((pk[i]-self.db_min)/db_range,0,1))
                py2=pt+dh-max(2,int(lp2*dh))
                p.fillRect(bx,py2-1,bw,2,pk_col)

    # ── 멀티-소스 라인 오버레이 (추가 장치/채널 카드) ──
    def set_channel_oct(self, cid, color, values):
        prev = self._ch_oct.get(cid, {})
        self._ch_oct[cid] = {'color': color, 'values': np.asarray(values, dtype=np.float64),
                             'visible': prev.get('visible', True)}
        self.update()
    def clear_channel(self, cid):
        self._ch_oct.pop(cid, None); self.update()
    def clear_all_channels(self):
        self._ch_oct.clear(); self.update()

    def set_mode(self,m):
        self._cache=None; self._cap_pix=None
        self.mode=m; self.peaks[m][:]=self.db_min
        self._peak_age[m][:]=0; self.update()
    def update_data(self,mode,values):
        if mode!=self.mode: return
        sm=self.smooth[mode]; pk=self.peaks[mode]
        vals=np.array(values,dtype=np.float64)
        sm+=(vals-sm)*self.alpha
        if self.peak_hold:
            age=self._peak_age[mode]
            mask=sm>pk; pk[mask]=sm[mask]; age[mask]=0; age[~mask]+=1
            pk[age>self.peak_hold_frames]-=self.peak_decay_rate_pk
            np.maximum(pk, self.db_min, out=pk)
        self.update()
    def clear(self):
        for k in self.smooth: self.smooth[k][:]=self.db_min
        for k in self.peaks:  self.peaks[k][:]=self.db_min
        self.update()

    def resizeEvent(self,e): self._cache=None; self.update()

    def _freq_to_x_oct(self, f, pl, uw):
        """옥타브 막대(밴드 인덱스 선형 배치)에 맞춘 주파수→x.
        막대는 pl+(i+0.5)*bar_w 에 그려지므로 라벨/격자도 같은 밴드 위치로 매핑해야 정렬됨."""
        bands = BANDS[self.mode]; n = len(bands)
        if n < 2: return pl
        bar_w = uw / n
        idx = float(np.interp(math.log(max(f, 1e-6)), np.log(bands), np.arange(n)))
        return pl + (idx + 0.5) * bar_w

    def _build_cache(self,W,H):
        from PyQt5.QtGui import QPixmap
        dpr=self.devicePixelRatio()
        px=QPixmap(int(W*dpr),int(H*dpr)); px.setDevicePixelRatio(dpr); px.fill(QColor(T('bg')))
        p=QPainter(px)
        p.setRenderHint(QPainter.Antialiasing); p.setRenderHint(QPainter.TextAntialiasing)
        pl=self.PAD_L; pr=self.PAD_R; pt=self.PAD_T; pb=self.PAD_B
        dh=H-pt-pb; uw=W-pl-pr; ny=20000
        p.setFont(_qfont(CF_GRID))
        for db in range(int(self.db_min),int(self.db_max)+1,12):
            y=pt+db_to_y(db,dh,self.db_min,self.db_max)
            if not pt<=y<=H-pb: continue
            is0=(db==0)
            p.setPen(QPen(QColor(T('grid_ref')),1.5 if is0 else 0.7,Qt.SolidLine))
            p.drawLine(pl,y,W-pr,y)
            p.setPen(QColor(T('graph_txt')))
            p.drawText(2,y-10,pl-12,20,Qt.AlignRight|Qt.AlignVCenter,str(db))
        p.setFont(_qfont(CF_GRID, True)); last_x=-999
        for f in FREQ_MARKS:
            if f<20 or f>ny: continue
            fx=self._freq_to_x_oct(f,pl,uw)   # 막대(밴드)와 정렬
            if not pl<=fx<=W-pr: continue
            p.setPen(QPen(QColor(T('grid')),1,Qt.SolidLine))
            p.drawLine(int(fx),pt,int(fx),H-pb)
            if fx-last_x<36: continue
            last_x=fx
            lf=int(f) if f==int(f) else f
            txt=f'{int(f//1000)}k' if f>=1000 else str(lf)
            tw=p.fontMetrics().horizontalAdvance(txt)
            tx=max(pl,min(int(fx-tw/2),W-pr-tw))
            p.setPen(QColor(T('graph_txt'))); p.drawText(tx,H-5,txt)
        p.end(); self._cache=px

    def _draw_grid_lines(self, p, W, H):
        pl=self.PAD_L; pr=self.PAD_R; pt=self.PAD_T; pb=self.PAD_B
        dh=H-pt-pb; uw=W-pl-pr; ny=20000
        for db in range(int(self.db_min),int(self.db_max)+1,12):
            y=pt+db_to_y(db,dh,self.db_min,self.db_max)
            if not pt<=y<=H-pb: continue
            is0=(db==0)
            p.setPen(QPen(QColor(T('grid_ref')),1.5 if is0 else 0.7,Qt.SolidLine))
            p.drawLine(pl,y,W-pr,y)
        for f in FREQ_MARKS:
            if f<20 or f>ny: continue
            fx=self._freq_to_x_oct(f,pl,uw)   # 막대(밴드)와 정렬
            if not pl<=fx<=W-pr: continue
            p.setPen(QPen(QColor(T('grid')),1,Qt.SolidLine))
            p.drawLine(int(fx),pt,int(fx),H-pb)

    def reset_peak(self):
        for k in self.peaks: self.peaks[k][:]=self.db_min; self._peak_age[k][:]=0
    def set_peak_hold(self,v):
        self.peak_hold=v
        if not v: self.reset_peak()
    def set_peak_hold_time(self, hold_frames):
        self.peak_hold_frames = hold_frames
        self.peak_decay_rate_pk = 20.0/30.0  # 20 dB/s 고정 낙하
    def set_db_range(self,lo,hi): self._cache=None; self.db_min=lo; self.db_max=hi; self.update()
    def set_speed(self,a,d): self.alpha=a; self.decay=d
    def mouseMoveEvent(self,e): self._mx=e.x(); self._my=e.y(); self.update()
    def leaveEvent(self,e): self._mx=-1; self.update()
    def enterEvent(self,e): self.setFocus()
    def keyPressEvent(self,e):
        win=self.window()
        if e.key()==Qt.Key_Up and hasattr(win,'_db_shift'): win._db_shift(6)
        elif e.key()==Qt.Key_Down and hasattr(win,'_db_shift'): win._db_shift(-6)
        else: super().keyPressEvent(e)
    def mouseDoubleClickEvent(self,e):
        if e.x()<self.PAD_L:
            sm=self.smooth[self.mode]; valid=sm[sm>-90]
            if len(valid)==0: return
            peak=float(np.max(valid)); span=self.db_max-self.db_min
            self.db_max=int(math.ceil((peak+12)/12))*12
            self.db_min=self.db_max-span; self.update()
    def wheelEvent(self,e):
        if e.modifiers() & Qt.ControlModifier:
            step=1; delta=e.angleDelta().y()
            span=self.db_max-self.db_min
            span=max(20,min(160,span+(-step if delta>0 else step)*2))
            mid=(self.db_max+self.db_min)/2
            self.db_min=mid-span/2; self.db_max=mid+span/2
            self.update()

    def paintEvent(self,ev):
        W=self.width(); H=self.height()
        if self._cache is None or self._cache.size()!=self.size():
            self._build_cache(W,H)
        p=QPainter(self); p.setRenderHint(QPainter.Antialiasing,True)
        p.drawPixmap(0,0,self._cache)
        pl=self.PAD_L; pr=self.PAD_R; pt=self.PAD_T; pb=self.PAD_B
        dh=H-pt-pb; uw=W-pl-pr
        db_range=self.db_max-self.db_min
        bands=BANDS[self.mode]; sm=self.smooth[self.mode]
        n=len(bands)
        if n==0 or db_range<=0: p.end(); return
        bar_w=uw/n
        gap_r=0.06 if self.mode=='oct24' else 0.08 if self.mode=='oct12' else 0.12
        gap=max(1.0,bar_w*gap_r)

        # E 포커스: 캡쳐 선택(_front_idx 있음) → 라이브 그룹 흐리게 + 선택 캡쳐 솔리드(위).
        # 라이브 포커스(_front_idx None) → 캡쳐 흐리게 + 라이브 솔리드(위).
        _cap_focus = (self._front_idx is not None)
        def _draw_src_bars(ch, dim=False):
            vals = ch['values']
            if vals is None or len(vals) != n: return
            qc = QColor(ch['color'])
            if dim: qc.setAlpha(50)
            for i in range(n):
                db = float(np.clip(vals[i], self.db_min, self.db_max))
                bh = max(2, int((db - self.db_min) / db_range * dh))
                bx = int(pl + i * bar_w + gap / 2); bw = max(1, int(bar_w - gap)); by = pt + dh - bh
                p.fillRect(bx, by, bw, bh, qc)
        def _draw_caps():
            if not self._captures: return
            _cap_key=(W,H,self.db_max,self.db_min,self.mode,round(bar_w*1000),round(gap*1000),self._front_idx,self._live_on_top)
            if self._cap_pix is None or self._cap_pix_key!=_cap_key:
                self._trigger_cap_build(W, H, _cap_key)
            if self._cap_pix is not None:
                p.drawPixmap(0,0,self._cap_pix)
        def _draw_all_live(dim):
            self._draw_live(p, W, H, dim=dim)
            if self._ch_oct:
                for cid, ch in sorted(self._ch_oct.items(), key=lambda kv: kv[0]==self._front_id):
                    if not ch.get('visible', True): continue
                    _draw_src_bars(ch, dim=dim)
            if self._front_id == 0:
                self._draw_live(p, W, H, dim=dim)
        if _cap_focus:
            _draw_all_live(dim=True)    # 라이브 흐리게(아래)
            _draw_caps()                # 선택 캡쳐 솔리드(위)
        else:
            _draw_caps()                # 캡쳐 흐리게(아래)
            _draw_all_live(dim=False)   # 라이브 솔리드(위)

        self._draw_grid_lines(p, W, H)

        # 우상단 고정 배지: 현재 평균 스펙트럼 최대 주파수 (40 Hz 이상만 탐색)
        valid_mask=[i for i,f in enumerate(bands) if f>=40]
        if valid_mask:
            sub=np.array([sm[i] for i in valid_mask])
            dom_idx=valid_mask[int(np.argmax(sub))]
        else:
            dom_idx=int(np.argmax(sm))
        dom_f=float(bands[dom_idx]); dom_db=float(sm[dom_idx])
        dom_fs=f'{dom_f/1000:.2f} kHz' if dom_f>=1000 else f'{dom_f:.0f} Hz'
        unit='dBSPL' if self.calib_offset else 'dB'
        draw_dom_badge(p, W-pr, pt, dom_fs, dom_db, unit)

        if pl<=self._mx<=W-pr:
            cx,cy=self._mx,self._my
            bi=max(0,min(int((cx-pl)/bar_w),n-1)); fc=bands[bi]
            db2=float(sm[bi])
            bx2=int(pl+bi*bar_w+gap/2); bw2=max(1,int(bar_w-gap))
            p.setPen(QPen(QColor(T('accent')),2))
            p.setBrush(QBrush(QColor(T('accent')).lighter(200) if _theme=='light' else QColor(78,125,240,12)))
            p.drawRect(bx2,pt,bw2,dh)
            fs=f'{fc/1000:.2f} kHz' if fc>=1000 else f'{fc:.0f} Hz'
            draw_info_box(p,W,fs,f'{db2:.1f} {unit}')
        p.end()

# ───────────────────────────────────────────
#  스펙트로그램 캔버스
# ───────────────────────────────────────────
class SpectrogramCanvas(QWidget):
    """Smaart-style spectrogram — pixel-perfect, dual ring buffer, crosshair cursor."""
    PAD_L=40; PAD_R=16; PAD_T=12; PAD_B=28
    MAX_HIST=1800   # 60s @ 30fps
    FPS=30

    def __init__(self):
        super().__init__()
        self.setMinimumSize(300,100)
        self.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Expanding)
        self.setAttribute(Qt.WA_OpaquePaintEvent,True)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.db_min=-96; self.db_max=MAX_DB
        self.scale_log=True
        self._cache=None
        # Dual ring buffers at canvas pixel width
        self._rgba=None      # (MAX_HIST, dw, 4) uint8  — rendered colour
        self._dbuf=None      # (MAX_HIST, dw)    float32 — raw dB for cursor
        self._rdw=0          # current buffer width
        self._wi=0           # write index (next slot)
        self._n=0            # frames stored
        self._col_lo=None; self._freqs_len=0
        self._img_bytes=None
        # Independent colour range (Smaart triangle handles)
        self._cmin=self.db_min
        self._cmax=self.db_max
        # Scroll: 0 = live, N = N frames back
        self._scroll=0
        # Mouse
        self._drag=None
        self._mx=-1; self._my=-1

    # ── Static helpers ──────────────────────────────────────────────────────
    @staticmethod
    def _gauss1d(x, sigma=1.5):
        r=max(1,int(3*sigma+0.5))
        k=np.arange(-r,r+1,dtype=np.float32)
        kern=np.exp(-k*k/(2*sigma*sigma)); kern/=kern.sum()
        # reflect-pad to avoid zero-pad edge artefacts at 20 Hz / 20 kHz boundaries
        padded=np.pad(x,r,mode='reflect')
        return np.convolve(padded,kern,mode='valid').astype(np.float32)

    @staticmethod
    def _colormap(t):
        r=np.zeros(len(t),np.float32); g=np.zeros_like(r); b=np.zeros_like(r)
        m=t<0.25;             b[m]=t[m]/0.25
        m=(t>=0.25)&(t<0.5);  g[m]=(t[m]-0.25)/0.25; b[m]=1.0
        m=(t>=0.5)&(t<0.75);  r[m]=(t[m]-0.5)/0.25; g[m]=1.0; b[m]=1.0-(t[m]-0.5)/0.25
        m=t>=0.75;             r[m]=1.0; g[m]=1.0-(t[m]-0.75)/0.25
        return (r*255).astype(np.uint8),(g*255).astype(np.uint8),(b*255).astype(np.uint8)

    # ── Ring buffer ─────────────────────────────────────────────────────────
    def _ensure(self, dw):
        if self._rgba is not None and self._rdw==dw: return
        self._rgba=np.zeros((self.MAX_HIST,dw,4),np.uint8)
        self._dbuf=np.full((self.MAX_HIST,dw),self.db_min,np.float32)
        self._rdw=dw; self._wi=0; self._n=0
        self._col_lo=None; self._freqs_len=0

    def _build_col_map(self, freqs, dw):
        if len(freqs) == 0: return
        lmin=math.log10(20.); lmax=math.log10(20000.)
        col_f=10.**np.linspace(lmin,lmax,dw)
        self._col_lo=np.searchsorted(freqs,col_f).clip(0,len(freqs)-1)
        self._freqs_len=len(freqs)

    def clear(self):
        if self._rgba is not None: self._rgba[:]=0; self._dbuf[:]=self.db_min
        self._wi=0; self._n=0; self._scroll=0; self.update()

    def resizeEvent(self,e):
        self._cache=None
        # Reset buffers — new width means old columns are invalid
        self._rgba=None; self._dbuf=None; self._rdw=0; self._col_lo=None
        super().resizeEvent(e)

    # ── Public API ───────────────────────────────────────────────────────────
    def set_db_range(self,lo,hi):
        self._cmin=lo; self._cmax=hi; self.db_min=lo; self.db_max=hi
        self._cache=None; self.update()

    def set_data(self, freqs, db_vals):
        if freqs is None or len(freqs) == 0 or db_vals is None or len(db_vals) == 0: return
        dw=self.width()-self.PAD_L-self.PAD_R
        if dw<=0: return
        self._ensure(dw)
        if self._col_lo is None or self._freqs_len!=len(freqs):
            self._build_col_map(freqs, dw)
        if self._col_lo is None: return
        # Nearest-bin lookup + Gaussian smoothing
        row_db=self._gauss1d(db_vals[self._col_lo].astype(np.float32), sigma=1.5)
        # Store raw dB for cursor
        self._dbuf[self._wi]=row_db
        # Convert to RGBA
        cr=self._cmax-self._cmin
        t=np.clip((row_db-self._cmin)/cr if cr>0 else np.zeros(dw),0.,1.)
        rv,gv,bv=self._colormap(t)
        self._rgba[self._wi]=np.stack([rv,gv,bv,np.full(dw,255,np.uint8)],axis=1)
        self._wi=(self._wi+1)%self.MAX_HIST
        self._n=min(self._n+1,self.MAX_HIST)
        if self._scroll==0: self.update()

    # ── Handle coordinates ───────────────────────────────────────────────────
    def _cdb_to_y(self,db,h):
        rng=self.db_max-self.db_min
        if rng==0: return self.PAD_T
        return int(self.PAD_T+(self.db_max-db)/rng*(h-self.PAD_T-self.PAD_B))

    def _y_to_cdb(self,y,h):
        dh=h-self.PAD_T-self.PAD_B
        if dh<=0: return self.db_max
        return self.db_max-(y-self.PAD_T)/dh*(self.db_max-self.db_min)

    def _scroll_cap(self):
        # 저장된 프레임 전체를 탐색 가능하되 마지막 1프레임은 항상 표시
        return max(0, self._n - 1)

    # ── Background cache (freq grid only — no dB axis) ────────────────────
    def _build_cache(self,W,H):
        dpr=self.devicePixelRatio()
        px=QPixmap(int(W*dpr),int(H*dpr)); px.setDevicePixelRatio(dpr); px.fill(QColor(T('bg')))
        p=QPainter(px)
        pl=self.PAD_L; pr=self.PAD_R; pt=self.PAD_T; pb=self.PAD_B
        uw=W-pl-pr; ny=20000
        p.setFont(_qfont(CF_ANNO, True)); last_lx=-999
        for f in FREQ_MARKS:
            if f<20 or f>ny: continue
            fx=freq_to_x(f,pl,uw,ny) if self.scale_log else pl+(f/ny)*uw
            if not pl<=fx<=W-pr: continue
            p.setPen(QPen(QColor(T('grid')),1,Qt.SolidLine))
            p.drawLine(int(fx),pt,int(fx),H-pb)
            if fx-last_lx<36: continue
            last_lx=fx
            txt=f'{int(f//1000)}k' if f>=1000 else str(int(f) if f==int(f) else f)
            tw=p.fontMetrics().horizontalAdvance(txt)
            tx=max(pl,min(int(fx-tw/2),W-pr-tw))
            p.setPen(QColor(T('graph_txt'))); p.drawText(tx,H-5,txt)
        p.end(); self._cache=px

    # ── Triangle handles (left edge) ─────────────────────────────────────────
    def _draw_handles(self,p,H):
        tx=self.PAD_L-2
        for db,col in [(self._cmax,'#4E7DF0'),(self._cmin,'#FF9F0A')]:
            y=self._cdb_to_y(db,H)
            pts=[QPoint(tx,y),QPoint(tx-11,y-7),QPoint(tx-11,y+7)]
            p.setBrush(QBrush(QColor(col))); p.setPen(Qt.NoPen)
            p.drawPolygon(QPolygon(pts))
            p.setPen(QColor(col)); p.setFont(_qfont(CF_TINY))
            p.drawText(0,y+4,self.PAD_L-15,12,Qt.AlignRight,f'{db:.0f}')

    # ── Input ────────────────────────────────────────────────────────────────
    def wheelEvent(self,e):
        delta=-e.angleDelta().y()//120
        self._scroll=max(0,min(self._scroll_cap(),self._scroll+delta*3))
        self.update()

    def scroll_by(self, delta):
        """delta>0: 과거로, delta<0: 미래(최신)로. scroll=0이면 live."""
        cap = self._scroll_cap()
        self._scroll = max(0, min(cap, self._scroll + delta))
        self.update()

    def keyPressEvent(self,e):
        if e.key()==Qt.Key_Down:
            self.scroll_by(30)
        elif e.key()==Qt.Key_Up:
            self.scroll_by(-30)
        else: super().keyPressEvent(e)

    def mousePressEvent(self,e):
        H=self.height()
        yt=self._cdb_to_y(self._cmax,H); yb=self._cdb_to_y(self._cmin,H)
        if e.x()<self.PAD_L:
            if abs(e.y()-yt)<12: self._drag='top'
            elif abs(e.y()-yb)<12: self._drag='bot'

    def mouseMoveEvent(self,e):
        self._mx=e.x(); self._my=e.y()
        if self._drag:
            db=max(self.db_min,min(self.db_max,self._y_to_cdb(e.y(),self.height())))
            if self._drag=='top': self._cmax=max(db,self._cmin+6)
            else:                 self._cmin=min(db,self._cmax-6)
        self.update()

    def mouseReleaseEvent(self,e): self._drag=None
    def enterEvent(self,e):        self.setFocus()
    def leaveEvent(self,e):        self._mx=-1; self.update()

    # ── Main render ───────────────────────────────────────────────────────────
    def paintEvent(self,ev):
        W,H=self.width(),self.height()
        if W<=0 or H<=0: return
        if self._cache is None or self._cache.size()!=QSize(W,H):
            self._build_cache(W,H)
        p=QPainter(self); p.drawPixmap(0,0,self._cache)
        pl=self.PAD_L; pr=self.PAD_R; pt=self.PAD_T; pb=self.PAD_B
        dw=W-pl-pr; dh=H-pt-pb
        if dw<=0 or dh<=0 or self._rgba is None or self._rdw!=dw or self._n==0:
            self._draw_handles(p,H); p.end(); return

        # ── 1. Build pixel array from ring buffer ──────────────────────────
        # Row 0 = top of display = newest visible frame (scroll frames ago)
        n_valid=max(0, min(self._n-self._scroll, dh))
        arr=np.zeros((dh,dw,4),np.uint8)
        if n_valid>0:
            start=(self._wi-1-self._scroll)%self.MAX_HIST
            ridx=(start-np.arange(n_valid,dtype=np.intp))%self.MAX_HIST
            arr[:n_valid]=self._rgba[ridx]
        self._img_bytes=arr.tobytes()
        img=QImage(self._img_bytes,dw,dh,dw*4,QImage.Format_RGBA8888)
        p.drawImage(pl,pt,img)

        # ── 2. Time grid (horizontal dotted lines + right-side labels) ────
        # Pick a step so we get 3-8 lines in view
        total_secs=dh/self.FPS
        for step_s in (1,2,5,10,20,30,60):
            if dh/(step_s*self.FPS)<=8: break
        grid_px=step_s*self.FPS
        p.setFont(_qfont(CF_ANNO))
        row=grid_px                     # first line at step_s below top
        while row<dh:
            yy=pt+row
            # actual time-ago for this row
            ago_s=(self._scroll+row)/self.FPS
            p.setPen(QPen(QColor(56,56,58,140),1,Qt.SolidLine))
            p.drawLine(pl,yy,W-pr,yy)
            lbl=f'{ago_s:.0f}s' if ago_s>=1 else f'{ago_s*1000:.0f}ms'
            p.setPen(QColor(142,142,147,200))
            tw=p.fontMetrics().horizontalAdvance(lbl)
            p.drawText(W-pr-tw-2,yy-2,lbl)
            row+=grid_px

        # ── 3. Scroll bar (right edge) ────────────────────────────────────
        if self._n > 1:
            cap = self._n - 1
            sb_h = max(14, dh * min(dh, self._n) // max(1, self._n))
            sb_y = pt + int(self._scroll / cap * (dh - sb_h)) if cap > 0 else pt
            bx = W - pr + 3
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(QColor(44,44,46,160)))
            p.drawRoundedRect(bx,pt,5,dh,2,2)
            p.setBrush(QBrush(QColor(T('accent'))))
            p.drawRoundedRect(bx,sb_y,5,sb_h,2,2)

        # ── 4. Triangle handles ────────────────────────────────────────────
        self._draw_handles(p,H)

        # ── 5. LIVE / PAUSED badge ─────────────────────────────────────────
        if self._scroll==0:
            p.setFont(_qfont(CF_ANNO, True))
            p.setPen(QColor(48,209,88,220)); p.drawText(pl+6,pt+14,'● LIVE')
        else:
            secs=self._scroll/self.FPS
            p.setFont(_qfont(CF_ANNO, True))
            p.setPen(QColor(255,159,10))
            p.drawText(pl+6,pt+15,f'▐▐  {secs:.1f}s ago')

        # ── 6. Crosshair cursor + info box ────────────────────────────────
        if pl<=self._mx<=W-pr and self._n>0:
            cx=self._mx; cy=self._my
            # vertical line (라이트=흰 그래프 → 어두운 크로스헤어)
            _xh = QColor(20,33,58,120) if _theme=='light' else QColor(255,255,255,100)
            p.setPen(QPen(_xh,1,Qt.DashLine))
            p.drawLine(cx,pt,cx,H-pb)
            # horizontal line (only inside data area)
            if pt<=cy<=H-pb:
                p.drawLine(pl,cy,W-pr,cy)

            # Frequency at cursor X
            freq=x_to_freq(cx,pl,dw,20000) if self.scale_log else (cx-pl)/dw*20000
            fs=f'{freq/1000:.2f} kHz' if freq>=1000 else f'{freq:.0f} Hz'

            # dB from the ring buffer at cursor (Y = time, X = frequency)
            col_x=cx-pl
            if pt<=cy<=H-pb:
                row_off=cy-pt                    # display row (0=top=newest visible)
                frame_ago=self._scroll+row_off   # total frames back from latest
                fi=(self._wi-1-frame_ago)%self.MAX_HIST
                if 0<=frame_ago<self._n and 0<=col_x<dw:
                    db_val=float(self._dbuf[fi,col_x])
                    t_ago=frame_ago/self.FPS
                    db_str=f'{db_val:.1f} dB'
                    t_str=f'  {t_ago:.1f}s ago' if t_ago>=0.1 else ''
                    draw_info_box(p,W,fs,db_str+t_str)
                    # small time label beside cursor Y
                    t_lbl=f'{t_ago:.1f}s'
                    p.setFont(_qfont(CF_ANNO))
                    p.setPen(QColor(20,33,58,200) if _theme=='light' else QColor(255,255,255,160))
                    p.drawText(pl+4,cy-3,t_lbl)
                else:
                    draw_info_box(p,W,fs,'')
            else:
                draw_info_box(p,W,fs,'')
        p.end()

# ───────────────────────────────────────────
#  VU 미터
# ───────────────────────────────────────────
class VUMeter(QWidget):
    """
    ★ VU 미터는 항상 raw dBFS 기준으로 표시
       캘리브레이션 오프셋은 그래프/수치에만 적용되고 VU 게인에는 영향 없음
    """
    clicked = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setFixedWidth(68); self.setAttribute(Qt.WA_OpaquePaintEvent,True)
        self.raw_spl  = -100.0   # dBFS (캘리브 오프셋 미적용)
        self.raw_peak = -100.0   # dBFS
        self.cal_spl  = -100.0   # dBSPL (캘리브 오프셋 적용, 숫자 표시용)
        self.cal_peak = -100.0

    def mousePressEvent(self, e): self.clicked.emit(); super().mousePressEvent(e)

    def update_level(self, raw_spl, raw_peak, cal_spl, cal_peak):
        self.raw_spl  = raw_spl;  self.raw_peak  = raw_peak
        self.cal_spl  = cal_spl;  self.cal_peak  = cal_peak
        self.update()

    def paintEvent(self,ev):
        p=QPainter(self); W,H=self.width(),self.height()
        p.fillRect(0,0,W,H,QColor(T('bg2')))
        DB_MIN, DB_RANGE = -60, 60

        # Title: Input / Meter (two lines)
        p.setFont(_qfont(CF_TINY, True)); p.setPen(QColor(T('text_dim')))
        p.drawText(0,6,W,12,Qt.AlignHCenter,'INPUT')
        p.drawText(0,17,W,12,Qt.AlignHCenter,'METER')

        # Bar — taller, starts lower
        bx=W//2-14; bw=28; by=32; bh=max(0, min(H-110, 220))
        p.fillRect(bx,by,bw,bh,QColor(T('bg')))
        p.setPen(QColor(T('border'))); p.drawRect(bx,by,bw,bh)
        lv=max(0.0,min(1.0,(self.raw_spl-DB_MIN)/DB_RANGE)); fh=int(lv*bh)
        if fh>0:
            base=by+bh
            gh=min(fh,int(bh*.6)); yh=min(max(0,fh-int(bh*.6)),int(bh*.2)); rh=max(0,fh-int(bh*.8))
            if gh: p.fillRect(bx+1,base-gh,bw-2,gh,QColor(T('green')))
            if yh: p.fillRect(bx+1,base-gh-yh,bw-2,yh,QColor(T('yellow')))
            if rh: p.fillRect(bx+1,base-fh,bw-2,rh,QColor(T('red')))
        pk_lv=max(0.0,min(1.0,(self.raw_peak-DB_MIN)/DB_RANGE))
        p.fillRect(bx+1,by+bh-int(pk_lv*bh)-1,bw-2,2,QColor(T('red')))

        # Values below bar
        y0=by+bh+6
        p.setFont(_qfont(CF_AXIS, True))
        c=T('red') if self.raw_spl>-6 else T('yellow') if self.raw_spl>-18 else T('accent')
        p.setPen(QColor(c)); p.drawText(0,y0,W,16,Qt.AlignHCenter,f'{self.cal_spl:.1f}')
        p.setFont(_qfont(CF_ANNO)); p.setPen(QColor(T('text_dim')))
        p.drawText(0,y0+16,W,12,Qt.AlignHCenter,'dB')
        p.setFont(_qfont(CF_ANNO, True)); p.setPen(QColor(T('text_dim')))
        p.drawText(0,y0+32,W,12,Qt.AlignHCenter,'PEAK')
        p.setFont(_qfont(CF_ANNO, True)); p.setPen(QColor(T('yellow')))
        p.drawText(0,y0+46,W,14,Qt.AlignHCenter,f'{self.cal_peak:.1f}')
        p.setFont(_qfont(CF_ANNO, True)); p.setPen(QColor(T('text_dim')))
        p.drawText(0,y0+64,W,12,Qt.AlignHCenter,'CLIP')
        p.fillRect(W//2-13,y0+78,26,12,QColor(T('red') if self.raw_spl>-3 else T('border')))
        # section border
        p.setPen(QPen(QColor(T('border')), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(1, 1, W-2, H-2, 8, 8)
        p.end()

# ───────────────────────────────────────────
#  캘리브레이션 다이얼로그
# ───────────────────────────────────────────
def _text_input_dialog(parent, title, label, default=''):
    """QInputDialog 대신 사용하는 커스텀 텍스트 입력 다이얼로그.
    입력 글씨색을 명시적으로 검정으로 지정하여 가시성 보장.
    반환: (text, ok)
    """
    dlg = QDialog(parent)
    dlg.setWindowTitle(title); _apply_dark_titlebar(dlg)
    dlg.setMinimumWidth(300)
    lay = QVBoxLayout(dlg); lay.setSpacing(10); lay.setContentsMargins(16, 16, 16, 12)
    lay.addWidget(QLabel(label))
    le = __import__('PyQt5.QtWidgets', fromlist=['QLineEdit']).QLineEdit(default)
    le.setStyleSheet('QLineEdit{background:#fff;color:#111;border:1px solid #aaa;'
                     'border-radius:4px;padding:4px 8px;font-size:13px;}')
    le.selectAll()
    lay.addWidget(le)
    btn_row = QHBoxLayout()
    cancel = QPushButton('Cancel'); ok_btn = QPushButton('OK')
    ok_btn.setDefault(True)
    cancel.setStyleSheet(ss_btn_neutral()); ok_btn.setStyleSheet(ss_btn_primary())
    cancel.clicked.connect(dlg.reject); ok_btn.clicked.connect(dlg.accept)
    btn_row.addStretch(); btn_row.addWidget(cancel); btn_row.addWidget(ok_btn)
    lay.addLayout(btn_row)
    le.returnPressed.connect(dlg.accept)
    ok = dlg.exec_() == QDialog.Accepted
    return le.text(), ok


class CalibDialog(QDialog):
    def __init__(self, device_name, n_channels, offsets, active_ch,
                 current_spl_func, set_channel_func, parent=None):
        super().__init__(parent)
        self.setWindowTitle('마이크 캘리브레이션'); _apply_dark_titlebar(self)
        self.setMinimumWidth(440)
        self.setStyleSheet(f'background:{T("bg2")};color:{T("text")};')
        self._get_spl = current_spl_func
        self._set_channel = set_channel_func
        self._n_ch = max(int(n_channels), 1)
        self._offsets = dict(offsets)         # {ch:int -> offset:float} (설정된 채널만)
        self._cur_ch = int(active_ch) if 0 <= active_ch < self._n_ch else 0
        self._rows = {}                       # ch -> {'btn':..., 'off':...}
        self._measuring = False
        self._meas_samples = []
        layout = QVBoxLayout(self); layout.setSpacing(12); layout.setContentsMargins(18,16,18,16)

        # ── 순서 안내
        steps = QLabel(
            '① 칼리브레이터를 마이크에 연결하세요\n'
            '② 아래 목록에서 캘리브할 채널을 [선택]하세요\n'
            '③ 기준값(94 or 114 dBSPL) 선택 → [레벨 측정]\n'
            '④ [오프셋 자동 계산] → 다른 채널도 반복 → [OK]'
        )
        steps.setStyleSheet(f'color:{T("text_dim")};font-size:11px;'
                            f'background:{T("panel")};border-radius:8px;padding:10px;')
        steps.setWordWrap(True); layout.addWidget(steps)

        # ── 채널 목록 테이블 (B안): 채널 / 현재 오프셋 / 선택
        if self._n_ch > 1:
            ch_hdr = QLabel(f'채널 목록  ·  {device_name}')
            ch_hdr.setStyleSheet(f'color:{T("text_dim")};font-size:10px;padding-left:2px;')
            layout.addWidget(ch_hdr)

            ch_wrap = QWidget()
            ch_col = QVBoxLayout(ch_wrap); ch_col.setSpacing(4); ch_col.setContentsMargins(2,2,2,2)
            for ch in range(self._n_ch):
                row = QHBoxLayout(); row.setSpacing(8); row.setContentsMargins(8,2,8,2)
                name_l = QLabel(f'Ch {ch+1}')
                name_l.setStyleSheet(f'color:{T("text")};font-size:12px;'); name_l.setFixedWidth(56)
                off_l = QLabel('—')
                off_l.setStyleSheet(f'color:{T("text_dim")};font-size:12px;font-weight:bold;')
                off_l.setAlignment(Qt.AlignCenter); off_l.setFixedWidth(96)
                sel = QPushButton('선택')
                sel.setFixedWidth(72); sel.setCursor(Qt.PointingHandCursor)
                sel.clicked.connect(lambda _=False, c=ch: self._select_channel(c))
                row.addWidget(name_l); row.addStretch(); row.addWidget(off_l); row.addWidget(sel)
                rw = QWidget(); rw.setLayout(row)
                ch_col.addWidget(rw)
                self._rows[ch] = {'btn': sel, 'off': off_l}
            ch_col.addStretch(1)

            scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setWidget(ch_wrap)
            scroll.setFrameShape(QFrame.NoFrame)
            scroll.setMaximumHeight(168 if self._n_ch > 4 else 16 + self._n_ch*34)
            scroll.setStyleSheet(f'QScrollArea{{background:{T("panel")};border:1px solid {T("border")};border-radius:8px;}}')
            layout.addWidget(scroll)

        # ── 기준값 선택 (가운데 정렬)
        # RoundComboBox → QComboBox: modal exec() 안에서 Popup 서브윈도우가
        # macOS에서 즉시 닫혀버리는 버그를 피하기 위해 기본 QComboBox 사용
        ref_row = QHBoxLayout(); ref_row.addStretch()
        ref_row.addWidget(QLabel('칼리브레이터 기준값:'))
        self.ref_cb = QComboBox()
        self.ref_cb.addItems(['94 dBSPL  (표준형)', '114 dBSPL  (고레벨형)'])
        self.ref_cb.setMinimumWidth(200)
        self.ref_cb.setStyleSheet(f"""
            QComboBox {{
                background:{T('panel')}; color:{T('text')};
                border:1px solid {T('border')}; border-radius:8px;
                padding:4px 10px; font-size:11px; min-height:24px;
            }}
            QComboBox::drop-down {{ width:18px; border:none; }}
            QComboBox QAbstractItemView {{
                background:{T('bg2')}; color:{T('text')};
                border:1px solid {T('accent')}; selection-background-color:rgba(78,125,240,80);
            }}
        """)
        ref_row.addWidget(self.ref_cb); ref_row.addStretch()
        layout.addLayout(ref_row)

        # ── 측정 영역
        self._meas_box = meas_box = QGroupBox(self._meas_title())
        meas_box.setStyleSheet(f'QGroupBox{{border:1px solid {T("border")};border-radius:8px;'
                                f'margin-top:8px;color:{T("text_dim")};font-size:10px;}}'
                                f'QGroupBox::title{{subcontrol-origin:margin;left:10px;}}')
        mb = QVBoxLayout(meas_box); mb.setAlignment(Qt.AlignCenter)

        self.meas_display = QLabel('— dBFS')
        self.meas_display.setStyleSheet(f'color:{T("accent")};font-size:26px;font-weight:bold;')
        self.meas_display.setAlignment(Qt.AlignCenter)
        mb.addWidget(self.meas_display)

        self.meas_btn = QPushButton('레벨 측정 시작  (3초)'); self.meas_btn.setIcon(_icon('mic', 14, color=T('accent')))
        self.meas_btn.setStyleSheet(f'background:rgba(78,125,240,25);color:{T("accent")};'
                                     f'border:1px solid {T("accent")};padding:6px;border-radius:8px;font-size:12px;')
        self.meas_btn.clicked.connect(self._start_measure)
        mb.addWidget(self.meas_btn)

        # 직접 입력 (스피너 버튼 없음, 가운데 정렬)
        manual_row = QHBoxLayout(); manual_row.addStretch()
        manual_row.addWidget(QLabel('직접 입력(dBFS):'))
        self.meas_spin = QDoubleSpinBox()
        self.meas_spin.setRange(-120, 0); self.meas_spin.setDecimals(1)
        self.meas_spin.setSingleStep(0.1); self.meas_spin.setValue(-26.0)
        self.meas_spin.setStyleSheet(ss_spin())
        manual_row.addWidget(self.meas_spin); manual_row.addStretch()
        mb.addLayout(manual_row)
        layout.addWidget(meas_box)

        # ── 오프셋 자동 계산
        calc_btn = QPushButton('오프셋 자동 계산')
        calc_btn.setStyleSheet(f'background:rgba(48,209,88,20);color:{T("green")};'
                                f'border:1px solid rgba(48,209,88,100);padding:7px;'
                                f'border-radius:8px;font-size:13px;font-weight:bold;')
        calc_btn.clicked.connect(self._auto_calc); layout.addWidget(calc_btn)

        self.result_lbl = QLabel('')
        self.result_lbl.setStyleSheet(f'color:{T("green")};font-size:13px;font-weight:bold;')
        self.result_lbl.setAlignment(Qt.AlignCenter); layout.addWidget(self.result_lbl)

        # ── 최종 오프셋 (가운데 정렬, 스피너 버튼 없음)
        off_row = QHBoxLayout(); off_row.addStretch()
        off_row.addWidget(QLabel('적용할 오프셋 (dB):'))
        self.offset_spin = QDoubleSpinBox()
        self.offset_spin.setRange(-30, 150)
        self.offset_spin.setDecimals(1); self.offset_spin.setSingleStep(0.5)
        self.offset_spin.setValue(self._offsets.get(self._cur_ch, 0.0))
        self.offset_spin.valueChanged.connect(self._on_offset_edited)
        self.offset_spin.setStyleSheet(f"""
            QDoubleSpinBox {{
                background:{T("panel")}; color:{T("accent")};
                border:1px solid {T("accent")}; padding:4px 10px;
                font-size:14px; font-weight:bold; min-width:110px; border-radius:8px;
            }}
            QDoubleSpinBox::up-button   {{ width:0; border:none; }}
            QDoubleSpinBox::down-button {{ width:0; border:none; }}
        """)
        off_row.addWidget(self.offset_spin)
        rst = QPushButton('초기화')
        rst.setStyleSheet(f'background:{T("panel")};color:{T("text_dim")};'
                          f'border:1px solid {T("border")};padding:4px 12px;border-radius:8px;')
        rst.clicked.connect(lambda: (self.offset_spin.setValue(0), self.result_lbl.setText(f'Ch {self._cur_ch+1} 초기화됨')))
        off_row.addWidget(rst); off_row.addStretch()
        layout.addLayout(off_row)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.setStyleSheet(ss_dialog_btns())
        btns.accepted.connect(self.accept); btns.rejected.connect(self.reject)
        btns.rejected.connect(lambda: self._meas_timer.stop() if hasattr(self,'_meas_timer') else None)
        layout.addWidget(btns)

        # 측정 타이머
        self._meas_timer = QTimer(self)
        self._meas_timer.timeout.connect(self._sample_level)
        self._meas_count = 0

        self._refresh_rows()   # 초기 채널 하이라이트 + 오프셋 표시

    # ── 채널 테이블 ──────────────────────────
    def _meas_title(self):
        return f'Ch {self._cur_ch+1} 레벨 측정' if self._n_ch > 1 else '현재 마이크 레벨 측정'

    def _select_channel(self, ch):
        """채널 행 [선택] → 부모 입력 채널 전환 후 그 채널을 측정 대상으로."""
        if self._measuring:
            self._meas_timer.stop(); self._measuring = False
        self._cur_ch = ch
        try: self._set_channel(ch)   # 부모 in_ch_cb 전환 → 스트림 재시작
        except Exception as e: _alog.warning(f'캘리브 채널 전환 실패 ch={ch}: {e}')
        # 이 채널의 저장된 오프셋을 스핀에 로드 (write-back 차단)
        self.offset_spin.blockSignals(True)
        self.offset_spin.setValue(self._offsets.get(ch, 0.0))
        self.offset_spin.blockSignals(False)
        # 측정 표시 초기화
        self.meas_display.setText('— dBFS')
        self.meas_display.setStyleSheet(f'color:{T("accent")};font-size:26px;font-weight:bold;')
        self._meas_box.setTitle(self._meas_title())
        self.result_lbl.setText(f'Ch {ch+1} 선택됨 — 측정하거나 오프셋을 입력하세요')
        self._refresh_rows()

    def _on_offset_edited(self, val):
        """오프셋 스핀 변경 → 현재 채널 값으로 기록."""
        self._offsets[self._cur_ch] = round(float(val), 1)
        self._refresh_rows()

    def _refresh_rows(self):
        for ch, w in self._rows.items():
            is_cur = (ch == self._cur_ch)
            if ch in self._offsets:
                w['off'].setText(f'{self._offsets[ch]:+.1f} dB')
                w['off'].setStyleSheet(f'color:{T("green")};font-size:12px;font-weight:bold;')
            else:
                w['off'].setText('—')
                w['off'].setStyleSheet(f'color:{T("text_dim")};font-size:12px;font-weight:bold;')
            if is_cur:
                w['btn'].setText('● 선택됨')
                w['btn'].setStyleSheet(f'background:rgba(78,125,240,35);color:{T("accent")};'
                                       f'border:1px solid {T("accent")};border-radius:7px;padding:3px;font-size:11px;')
            else:
                w['btn'].setText('선택')
                w['btn'].setStyleSheet(f'background:{T("bg2")};color:{T("text_dim")};'
                                       f'border:1px solid {T("border")};border-radius:7px;padding:3px;font-size:11px;')

    def _start_measure(self):
        if self._measuring: return
        self._measuring = True; self._meas_samples = []; self._meas_count = 0
        self.meas_btn.setText('측정 중... (3초)')
        self.meas_btn.setStyleSheet(f'background:rgba(255,204,0,25);color:{T("yellow")};'
                                     f'border:1px solid rgba(255,204,0,100);padding:6px;border-radius:5px;font-size:12px;')
        self._meas_timer.start(100)   # 100ms 간격으로 30회 = 3초

    def _sample_level(self):
        self._meas_count += 1
        spl = self._get_spl()   # 현재 dBFS(캘리브 전) 가져옴
        self._meas_samples.append(spl)
        self.meas_display.setText(f'{spl:.1f} dBFS')
        if self._meas_count >= 30:
            self._meas_timer.stop(); self._measuring = False
            avg = float(np.mean(self._meas_samples))
            self.meas_spin.setValue(round(avg, 1))
            self.meas_display.setText(f'{avg:.1f} dBFS  ✓')
            self.meas_display.setStyleSheet(f'color:{T("green")};font-size:26px;font-weight:bold;')
            self.meas_btn.setText('레벨 측정 시작  (3초)'); self.meas_btn.setIcon(_icon('mic', 14, color=T('accent')))
            self.meas_btn.setStyleSheet(f'background:rgba(78,125,240,25);color:{T("accent")};'
                                         f'border:1px solid {T("accent")};padding:6px;border-radius:5px;font-size:12px;')
            self._auto_calc()

    def _auto_calc(self):
        ref_val = 94.0 if self.ref_cb.currentIndex()==0 else 114.0
        meas    = self.meas_spin.value()
        offset  = ref_val - meas
        self.offset_spin.setValue(round(offset, 1))   # → _on_offset_edited 가 _offsets 기록
        self.result_lbl.setText(f'Ch {self._cur_ch+1}  오프셋 {offset:+.1f} dB  →  {meas:.1f} + {offset:.1f} = {ref_val:.0f} dBSPL ✓')

    def get_all_offsets(self):
        """{ch:int -> offset:float} — 이번 세션에서 설정/변경된 모든 채널."""
        return dict(self._offsets)

    def get_current_channel(self):
        return self._cur_ch

# ───────────────────────────────────────────
#  LEQ 팝업 창
# ───────────────────────────────────────────
class LeqWindow(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent, Qt.Window)
        self.setWindowTitle('Time Average Level (LEQ)'); _apply_dark_titlebar(self, resizable=True)
        self.setMinimumSize(340, 300)
        self.setStyleSheet(f'background:{T("bg2")};color:{T("text")};')

        self._leq_a_buf = deque()
        self._leq_c_buf = deque()
        self._start_time = None
        self._buf_mutex = QMutex()
        self._duration_min = 5
        self._running = False

        layout = QVBoxLayout(self)

        # 시간 설정
        top = QHBoxLayout()
        top.addWidget(QLabel('Duration:'))
        self.dur_cb = RoundComboBox()
        self.dur_cb.addItems(['5 min','10 min','15 min','30 min','45 min','60 min'])
        self.dur_cb.setStyleSheet(f'background:{T("panel")};color:{T("text")};border:1px solid {T("border")};padding:3px;min-width:70px;')
        self.dur_cb.currentIndexChanged.connect(self._dur_changed)
        top.addWidget(self.dur_cb)
        self.leq_start_btn = QPushButton('Start'); _apply_txn(self.leq_start_btn, False)
        self.leq_start_btn.setStyleSheet(f'background:rgba(78,125,240,25);color:{T("accent")};border:1px solid rgba(78,125,240,100);padding:4px 10px;border-radius:8px;')
        self.leq_start_btn.clicked.connect(self._toggle_leq)
        top.addWidget(self.leq_start_btn)
        top.addStretch()
        layout.addLayout(top)

        # 진행바
        self.progress_lbl = QLabel('Standby')
        self.progress_lbl.setStyleSheet(f'color:{T("text_dim")};font-size:10px;')
        layout.addWidget(self.progress_lbl)

        # 결과 표시
        result_group = QGroupBox('Live LEQ')
        result_group.setStyleSheet(f'QGroupBox{{border:1px solid {T("border")};border-radius:6px;margin-top:8px;color:{T("text_dim")};font-size:10px;}}')
        rg_layout = QVBoxLayout(result_group)

        def big_val_row(label, color):
            row = QHBoxLayout()
            lbl = QLabel(label); lbl.setStyleSheet(f'color:{T("text_dim")};font-size:11px;')
            val = QLabel('—'); val.setStyleSheet(f'color:{color};font-size:22px;font-weight:bold;')
            val.setAlignment(Qt.AlignRight)
            row.addWidget(lbl); row.addWidget(val)
            return row, val

        r1,self.leq_a_lbl   = big_val_row('LEQ(A)', T('accent'))
        r2,self.leq_c_lbl   = big_val_row('LEQ(C)', T('accent3'))
        r3,self.inst_a_lbl  = big_val_row('dBA', T('accent'))
        r4,self.inst_c_lbl  = big_val_row('dBC', T('accent3'))
        for r in [r1,r2,r3,r4]: rg_layout.addLayout(r)
        layout.addWidget(result_group)

        # 리셋
        rst = QPushButton('  Reset'); rst.setIcon(_icon('refresh'))
        rst.setStyleSheet(f'background:{T("panel")};color:{T("text_dim")};border:1px solid {T("border")};padding:4px;border-radius:8px;')
        rst.clicked.connect(self._reset_leq)
        layout.addWidget(rst)
        layout.addStretch()

        # 업데이트 타이머
        self._update_timer = QTimer(self)
        self._update_timer.timeout.connect(self._update_display)
        self._update_timer.start(500)

    def showEvent(self, e):
        super().showEvent(e)
        if not self._update_timer.isActive():
            self._update_timer.start(500)

    def closeEvent(self, e):
        self._update_timer.stop()
        if hasattr(self.parent(), 'leq_win'):
            self.parent().leq_win = None
        e.accept()

    def _dur_changed(self,idx):
        self._duration_min=[5,10,15,30,45,60][idx]

    def _toggle_leq(self):
        self._running=not self._running
        if self._running:
            self._start_time=time.time()
            self._leq_a_buf.clear(); self._leq_c_buf.clear()
            self.leq_start_btn.setText('Stop'); _apply_txn(self.leq_start_btn, True)
            self.leq_start_btn.setStyleSheet(f'background:rgba(255,69,58,25);color:{T("red")};border:1px solid rgba(255,69,58,100);padding:4px 10px;border-radius:8px;')
        else:
            self.leq_start_btn.setText('Start'); _apply_txn(self.leq_start_btn, False)
            self.leq_start_btn.setStyleSheet(f'background:rgba(78,125,240,25);color:{T("accent")};border:1px solid rgba(78,125,240,100);padding:4px 10px;border-radius:8px;')

    def _reset_leq(self):
        self._running=False; self._leq_a_buf.clear(); self._leq_c_buf.clear()
        self._start_time=None
        for lbl in [self.leq_a_lbl,self.leq_c_lbl,self.inst_a_lbl,self.inst_c_lbl]:
            lbl.setText('—')
        self.progress_lbl.setText('Standby')
        self.leq_start_btn.setText('Start'); _apply_txn(self.leq_start_btn, False)
        self.leq_start_btn.setStyleSheet(f'background:rgba(78,125,240,25);color:{T("accent")};border:1px solid rgba(78,125,240,100);padding:4px 10px;border-radius:8px;')

    def push_sample(self, dba, dbc):
        if not self._running: return
        max_samples = self._duration_min * 60 * 50
        with QMutexLocker(self._buf_mutex):
            self._leq_a_buf.append(dba)
            self._leq_c_buf.append(dbc)
            while len(self._leq_a_buf) > max_samples: self._leq_a_buf.popleft()
            while len(self._leq_c_buf) > max_samples: self._leq_c_buf.popleft()

    def _update_display(self):
        if not self._running: return
        with QMutexLocker(self._buf_mutex):
            if not self._leq_a_buf: return
            a_arr=np.array(list(self._leq_a_buf))
            c_arr=np.array(list(self._leq_c_buf))
        leq_a=10*np.log10(np.mean(10**(a_arr/10)))
        leq_c=10*np.log10(np.mean(10**(c_arr/10)))
        self.leq_a_lbl.setText(f'{leq_a:.1f} dBA')
        self.leq_c_lbl.setText(f'{leq_c:.1f} dBC')
        self.inst_a_lbl.setText(f'{a_arr[-1]:.1f} dBA')
        self.inst_c_lbl.setText(f'{c_arr[-1]:.1f} dBC')
        # 진행률
        if self._start_time:
            elapsed=time.time()-self._start_time
            total=self._duration_min*60
            pct=min(100,elapsed/total*100)
            mins=int(elapsed//60); secs=int(elapsed%60)
            self.progress_lbl.setText(f'Elapsed: {mins:02d}:{secs:02d} / {self._duration_min:02d}:00  ({pct:.0f}%)')
            if elapsed>=total:
                self._running=False
                self.leq_start_btn.setText('Start'); _apply_txn(self.leq_start_btn, False)
                self.progress_lbl.setText(f'✓ Done  LEQ(A)={leq_a:.1f}  LEQ(C)={leq_c:.1f}')

# ───────────────────────────────────────────
#  SPL Meter — Smaart-style floating window
# ───────────────────────────────────────────
class _SplPanel(QWidget):
    """Single measurement panel inside SplMeterWindow — Smaart-style centered layout."""
    _BASE_W = 200  # reference width for font scaling
    _BASE_H = 132  # reference height — scale 1 폰트가 세로로 여유있게 맞는 높이(짤림 방지)

    def __init__(self, title, tc, vc, bg_hex='#0d0d1a', border_hex='#2a3060', parent=None, metric_id=None):
        super().__init__(parent)
        self.metric_id = metric_id
        self._tc = tc; self._vc = vc; self._base_vc = vc
        self._warn_db = -20.0   # yellow above this
        self._peak_db = -10.0   # red above this
        self._bg    = QColor(bg_hex)
        self._bord  = QColor(border_hex)
        self._val_fs = 46  # current font size for value label
        self._max_fs = 15  # current font size for Max/dot (리사이즈 후 재적용용)
        self.setAttribute(Qt.WA_OpaquePaintEvent, False)
        self.setMinimumHeight(20)   # 아주 작게까지 허용 (최소 크기 탐색용)
        layout = QVBoxLayout(self)
        # inner margins leave room for the painted border
        layout.setContentsMargins(10, 4, 10, 4); layout.setSpacing(1)

        self._title_lbl = QLabel(title)
        self._title_lbl.setAlignment(Qt.AlignCenter)
        self._title_lbl.setStyleSheet(
            f'color:{tc};font-size:18px;font-weight:bold;background:transparent;')
        layout.addWidget(self._title_lbl)

        self._sep = QFrame(); self._sep.setFrameShape(QFrame.HLine); self._sep.setFixedHeight(1)
        self._sep.setStyleSheet(f'background:{T("border")};border:none;')
        layout.addWidget(self._sep)

        self._val_lbl = QLabel('—')
        self._val_lbl.setAlignment(Qt.AlignCenter)
        self._val_lbl.setStyleSheet(
            f'color:{vc};font-size:46px;font-weight:bold;'
            f'background:transparent;')
        layout.addWidget(self._val_lbl)

        max_row = QHBoxLayout(); max_row.setContentsMargins(0, 0, 0, 0)
        max_row.addStretch()
        self._dot = QLabel('●')
        self._dot.setStyleSheet('color:#33FF66;font-size:15px;background:transparent;')
        self._max_lbl = QLabel('Max: —')
        self._max_lbl.setStyleSheet('color:#8E8E93;font-size:15px;background:transparent;')
        max_row.addWidget(self._dot); max_row.addWidget(self._max_lbl)
        max_row.addStretch()
        layout.addLayout(max_row)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        # 테마 토큰 사용 → 다크/라이트 토글 시 update()만으로 카드 배경이 따라감
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(T('panel')))
        p.drawRoundedRect(r, 8, 8)
        pen = QPen(QColor(T('border')), 1.5)
        p.setPen(pen); p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(r, 8, 8)
        p.end()
        super().paintEvent(e)

    def restyle(self):
        """테마 토글 시 카드 내부 색 재적용 (분리선 + 카드 배경/테두리 repaint)."""
        self._sep.setStyleSheet(f'background:{T("border")};border:none;')
        self._max_lbl.setStyleSheet(f'color:{T("text_dim")};font-size:{self._max_fs}px;background:transparent;')
        self.update()

    def set_calib_offset(self, offset):
        self._warn_db = -20.0 + offset
        self._peak_db = -10.0 + offset

    def _level_color(self, val):
        if val > self._peak_db:   return '#FF453A'  # red
        if val > self._warn_db:   return '#FF9F0A'  # yellow
        return self._base_vc

    def _peak_color(self, max_val):
        if max_val > self._peak_db:  return '#FF453A'
        if max_val > self._warn_db:  return '#FF9F0A'
        return '#33FF66'

    def set_font_scale(self, scale):
        # 하한을 낮춰 창을 아주 작게 줄여도 글자가 같이 작아지게
        vs = max(10, int(46 * scale))
        ts = max(8,  int(18 * scale))
        ms = max(8,  int(15 * scale))
        self._val_fs = vs
        self._max_fs = ms
        self._title_lbl.setStyleSheet(
            f'color:{self._tc};font-size:{ts}px;font-weight:bold;background:transparent;')
        self._val_lbl.setStyleSheet(
            f'color:{self._vc};font-size:{vs}px;font-weight:bold;'
            f'background:transparent;')
        self._dot.setStyleSheet(f'color:#00e676;font-size:{ms}px;background:transparent;')
        self._max_lbl.setStyleSheet(f'color:#888888;font-size:{ms}px;background:transparent;')

    def set_value(self, val, max_val):
        vc = self._level_color(val)
        if vc != self._vc:
            self._vc = vc
            self._val_lbl.setStyleSheet(
                f'color:{vc};font-size:{self._val_fs}px;font-weight:bold;'
                f'background:transparent;')
        self._val_lbl.setText(f'{val:.1f}')
        if max_val is not None:
            pc = self._peak_color(max_val)
            # font-size 를 함께 명시 — 안 그러면 리사이즈로 키운 크기가 매 갱신마다 기본값으로 되돌아감
            self._dot.setStyleSheet(f'color:{pc};font-size:{self._max_fs}px;background:transparent;')
            self._max_lbl.setStyleSheet(f'color:{pc};font-size:{self._max_fs}px;background:transparent;')
            self._max_lbl.setText(f'Max: {max_val:.1f}')

    def reset(self):
        self._vc = self._base_vc
        self._val_lbl.setStyleSheet(
            f'color:{self._base_vc};font-size:{self._val_fs}px;font-weight:bold;'
            f'background:transparent;')
        self._val_lbl.setText('—'); self._max_lbl.setText('Max: —')
        self._dot.setStyleSheet(f'color:#33FF66;font-size:{self._max_fs}px;background:transparent;')
        self._max_lbl.setStyleSheet(f'color:#8E8E93;font-size:{self._max_fs}px;background:transparent;')


class SplMeterWindow(QWidget):
    """Smaart-style SPL Meter — 자유 행×열 그리드 + 칸별 지표 선택."""
    _PUSH_RATE = 50  # ~50 fps from audio thread
    _PRESETS = [
        ('1 min',   60),  ('5 min',   300), ('10 min',  600),
        ('15 min',  900), ('30 min', 1800), ('45 min', 2700),
        ('1 hr',   3600), ('1.5 hr', 5400), ('2 hr',   7200),
        ('3 hr',  10800),
    ]
    # 표시 가능한 지표:  id -> (제목, 색)
    _METRICS = {
        'dba':  ('dB SPL A Slow', '#4E7DF0'),
        'dbc':  ('dB SPL C Slow', '#9B5DE5'),
        'laeq': ('dB LAeq',       '#4E7DF0'),
        'lceq': ('dB LCeq',       '#9B5DE5'),
    }
    _DEFAULT_CELLS = ['dba', 'dbc', 'laeq', 'lceq']

    def __init__(self, parent=None):
        super().__init__(parent, Qt.Window | Qt.Tool)
        self.setWindowTitle('SPL Meter')
        self.setAttribute(Qt.WA_DeleteOnClose, False)

        self._buf_a = deque(maxlen=self._PUSH_RATE * 60 * 60 * 3)  # 3 hr max
        self._buf_c = deque(maxlen=self._PUSH_RATE * 60 * 60 * 3)
        self._max_a = None; self._max_c = None
        self._max_laeq = None; self._max_lceq = None
        self._leq_secs = 60  # default 1 min
        self._mutex = QMutex()
        self._panels = []     # 현재 그리드에 배치된 _SplPanel 목록
        self._calib_offset = 0.0

        # ── 저장된 레이아웃 복원 (없으면 4×1 기본 = 기존 모습)
        self._rows, self._cols, self._cells = self._load_layout()
        try:
            self._leq_idx = int(self.parent()._settings.get('spl_meter', {}).get('leq_idx', 0))
        except Exception:
            self._leq_idx = 0
        self._leq_idx = max(0, min(len(self._PRESETS) - 1, self._leq_idx))
        self._leq_secs = self._PRESETS[self._leq_idx][1]

        # ── 타이틀바(✕ 옆): 설정(슬라이더 아이콘) + Reset Max(아이콘)
        self._set_btn = _SettingsBtn()
        self._set_btn.setToolTip('설정')
        self._set_btn.clicked.connect(self._open_layout_dialog)
        self._reset_btn = _ResetMaxBtn()
        self._reset_btn.setToolTip('Reset Max')
        self._reset_btn.clicked.connect(self._reset_max)
        _apply_dark_titlebar(self, resizable=True, aux=[self._set_btn, self._reset_btn])

        self.setStyleSheet(f'SplMeterWindow{{background:{T("bg")};}}')
        root = QVBoxLayout(self); root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)
        # 레이아웃이 콘텐츠 최소크기로 창을 강제하지 않게 → 사용자가 더 작게 드래그 가능(최소 탐색용)
        root.setSizeConstraint(QVBoxLayout.SetNoConstraint)

        # ── 패널 그리드 컨테이너 (행×열은 _rebuild_grid 에서 채움). 컨트롤은 설정창으로 이동.
        panels_w = QWidget(); panels_w.setStyleSheet(f'background:{T("bg")};')
        self._panels_w = panels_w
        self._grid = QGridLayout(panels_w)
        self._grid.setContentsMargins(6, 6, 6, 6); self._grid.setSpacing(6)
        root.addWidget(panels_w, 1)

        self._rebuild_grid()
        self.setMinimumSize(self._min_w(), self._min_h())
        # 기본(처음 열 때) 크기 — 작고 보기 좋게. 사용자가 자유롭게 늘리거나 줄일 수 있음.
        self.resize(max(150 * self._cols, 280), self._chrome_h() + 116 * self._rows)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._update_display)
        self._timer.start(200)

    # ── 레이아웃 로드/저장 ──────────────────────
    def _load_layout(self):
        try:
            cfg = self.parent()._settings.get('spl_meter', {})
            rows = int(cfg.get('rows', 4)); cols = int(cfg.get('cols', 1))
            cells = list(cfg.get('cells', self._DEFAULT_CELLS))
        except Exception:
            rows, cols, cells = 4, 1, list(self._DEFAULT_CELLS)
        rows = max(1, min(4, rows)); cols = max(1, min(4, cols))
        cells = self._normalize_cells(cells, rows, cols)
        return rows, cols, cells

    def _normalize_cells(self, cells, rows, cols):
        n = rows * cols
        cells = [(c if c in self._METRICS else None) for c in cells][:n]
        cells += [None] * (n - len(cells))   # 부족분 빈 칸 패딩
        return cells

    def _save_layout(self):
        try:
            self.parent()._settings['spl_meter'] = {
                'rows': self._rows, 'cols': self._cols, 'cells': self._cells,
                'leq_idx': self._leq_idx}
            _save_settings(self.parent()._settings)
        except Exception as e:
            _alog.warning(f'SPL 레이아웃 저장 실패: {e}')

    def restyle_theme(self):
        """테마 토글(다크↔라이트) 시 창/그리드 배경 + 다크타이틀바 + 패널 색 재적용."""
        self.setStyleSheet(f'SplMeterWindow{{background:{T("bg")};}}')
        if hasattr(self, '_panels_w'):
            self._panels_w.setStyleSheet(f'background:{T("bg")};')
        bar = getattr(self, '_dark_titlebar', None)
        if bar is not None:
            bar.setStyleSheet(f'#darkTitleBar{{background:{T("bg2")};}}')
            _t = getattr(bar, '_title', None)
            if _t is not None:
                _t.setStyleSheet(f'color:{T("text")};font-size:12px;font-weight:bold;background:transparent;')
        for p in self._panels:
            p.restyle()

    def _chrome_h(self):
        return 12   # 컨트롤 줄 제거됨 — 그리드 여백만

    def _min_w(self):
        # 최소 크기 탐색용 — 거의 풀어줌(실제 하한은 타이틀바 콘텐츠 자연 최소가 결정)
        return max(40 * self._cols, 80)

    def _min_h(self):
        # 패널 폰트가 자동 축소되므로 아주 작게까지 허용
        return self._chrome_h() + 22 * self._rows

    # ── 그리드 재구성 ───────────────────────────
    def _rebuild_grid(self):
        # 기존 패널 제거
        for p in self._panels:
            self._grid.removeWidget(p); p.setParent(None); p.deleteLater()
        self._panels = []
        for col in range(self._grid.columnCount()): self._grid.setColumnStretch(col, 0)
        for row in range(self._grid.rowCount()):    self._grid.setRowStretch(row, 0)

        self._cells = self._normalize_cells(self._cells, self._rows, self._cols)
        for idx, mid in enumerate(self._cells):
            r, c = divmod(idx, self._cols)
            if mid is None:
                continue
            title, color = self._METRICS[mid]
            pnl = _SplPanel(title, color, color, bg_hex='#1C1C1E', border_hex='#38383A',
                            metric_id=mid)
            pnl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            pnl.set_calib_offset(self._calib_offset)
            self._grid.addWidget(pnl, r, c)
            self._panels.append(pnl)
        for c in range(self._cols): self._grid.setColumnStretch(c, 1)
        for r in range(self._rows): self._grid.setRowStretch(r, 1)

        # 창 최소 크기 — 작게 줄일 수 있도록 (강제 확대 안 함)
        self.setMinimumSize(self._min_w(), self._min_h())
        QTimer.singleShot(0, self._scale_panels)

    def _open_layout_dialog(self):
        leq_labels = [lbl for lbl, _ in self._PRESETS]
        dlg = SplLayoutDialog(self._rows, self._cols, self._cells, self._METRICS,
                              leq_labels, self._leq_idx, self)
        if dlg.exec() == QDialog.Accepted:
            self._rows, self._cols, self._cells = dlg.get_layout()
            self._leq_idx = dlg.get_leq_idx()
            self._leq_secs = self._PRESETS[self._leq_idx][1]
            self._rebuild_grid()
            self._scale_panels()
            self._save_layout()

    def push_sample(self, dba, dbc):
        if dba > -100:
            with QMutexLocker(self._mutex):
                self._buf_a.append(dba); self._buf_c.append(dbc)

    def _update_display(self):
        with QMutexLocker(self._mutex):
            if not self._buf_a: return
            n = min(len(self._buf_a), self._leq_secs * self._PUSH_RATE)
            arr_a = np.array(list(self._buf_a)[-n:])
            arr_c = np.array(list(self._buf_c)[-n:])

        dba = float(arr_a[-1]); dbc = float(arr_c[-1])
        laeq = float(10 * np.log10(np.mean(10 ** (arr_a / 10))))
        lceq = float(10 * np.log10(np.mean(10 ** (arr_c / 10))))

        if self._max_a    is None or dba  > self._max_a:   self._max_a   = dba
        if self._max_c    is None or dbc  > self._max_c:   self._max_c   = dbc
        if self._max_laeq is None or laeq > self._max_laeq: self._max_laeq = laeq
        if self._max_lceq is None or lceq > self._max_lceq: self._max_lceq = lceq

        value_for = {'dba': dba, 'dbc': dbc, 'laeq': laeq, 'lceq': lceq}
        max_for   = {'dba': self._max_a, 'dbc': self._max_c,
                     'laeq': self._max_laeq, 'lceq': self._max_lceq}
        for pnl in self._panels:
            pnl.set_value(value_for[pnl.metric_id], max_for[pnl.metric_id])

    def set_calib_offset(self, offset):
        self._calib_offset = offset
        for pnl in self._panels:
            pnl.set_calib_offset(offset)

    def _reset_max(self):
        self._max_a = self._max_c = self._max_laeq = self._max_lceq = None
        for pnl in self._panels:
            pnl.reset()

    def _scale_panels(self):
        # 가로·세로 둘 다 고려해 작은 쪽 기준 → 좁거나 낮은 패널에서 글자 짤림 방지
        for pnl in self._panels:
            w = pnl.width(); h = pnl.height()
            if w <= 0 or h <= 0:
                continue
            pnl.set_font_scale(min(w / _SplPanel._BASE_W, h / _SplPanel._BASE_H))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._scale_panels()

    def showEvent(self, e):
        super().showEvent(e)
        if not self._timer.isActive(): self._timer.start(200)
        self._scale_panels()

    def closeEvent(self, e):
        self._timer.stop()
        if hasattr(self.parent(), 'spl_meter_win'):
            self.parent().spl_meter_win = None
        e.accept()


class SplLayoutDialog(QDialog):
    """SPL Meter 레이아웃 편집 — 행/열 개수 + 칸별 지표 지정."""
    def __init__(self, rows, cols, cells, metrics, leq_labels=None, leq_idx=0, parent=None):
        super().__init__(parent)
        self.setWindowTitle('SPL 설정'); _apply_dark_titlebar(self)
        self.setMinimumWidth(360)
        self.setStyleSheet(f'background:{T("bg2")};color:{T("text")};')
        self._metrics = metrics                 # id -> (title, color)
        self._cells = list(cells)               # 현재 지정값 (재구성 시 보존)
        self._combos = []                       # 현재 그리드의 QComboBox 목록
        self._ids = [None] + list(metrics.keys())   # 콤보 인덱스 ↔ 지표 id

        root = QVBoxLayout(self); root.setSpacing(12); root.setContentsMargins(18, 16, 18, 16)

        info = QLabel('행·열 개수를 정하고, 각 칸에 표시할 지표를 고르세요.\n빈 칸은 "— 없음"으로 두면 됩니다.')
        info.setStyleSheet(f'color:{T("text_dim")};font-size:11px;'
                           f'background:{T("panel")};border-radius:8px;padding:10px;')
        info.setWordWrap(True); root.addWidget(info)

        # ── LEQ time (적분 시간) 선택
        leq_row = QHBoxLayout(); leq_row.addStretch()
        leq_row.addWidget(QLabel('LEQ time:'))
        self._leq_cb = QComboBox(); self._leq_cb.setStyleSheet(self._combo_style())
        self._leq_cb.setMinimumWidth(120)
        for lbl in (leq_labels or ['1 min']):
            self._leq_cb.addItem(lbl)
        self._leq_cb.setCurrentIndex(max(0, min(self._leq_cb.count() - 1, leq_idx)))
        leq_row.addWidget(self._leq_cb); leq_row.addStretch()
        root.addLayout(leq_row)

        # ── 행/열 스핀
        rc_row = QHBoxLayout(); rc_row.addStretch()
        rc_row.addWidget(QLabel('행(Row):'))
        self._row_sp = QSpinBox(); self._row_sp.setRange(1, 4); self._row_sp.setValue(rows)
        rc_row.addWidget(self._row_sp)
        rc_row.addSpacing(14)
        rc_row.addWidget(QLabel('열(Col):'))
        self._col_sp = QSpinBox(); self._col_sp.setRange(1, 4); self._col_sp.setValue(cols)
        rc_row.addWidget(self._col_sp)
        rc_row.addStretch()
        for sp in (self._row_sp, self._col_sp):
            sp.setStyleSheet(ss_spin(FS_LG, 6, 54))
            sp.valueChanged.connect(self._rebuild_combos)
        root.addLayout(rc_row)

        # ── 칸별 지표 콤보 그리드
        self._cells_wrap = QWidget()
        self._cells_grid = QGridLayout(self._cells_wrap)
        self._cells_grid.setSpacing(6); self._cells_grid.setContentsMargins(2, 2, 2, 2)
        root.addWidget(self._cells_wrap)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.setStyleSheet(ss_dialog_btns())
        btns.accepted.connect(self.accept); btns.rejected.connect(self.reject)
        root.addWidget(btns)

        self._rebuild_combos()

    def _combo_style(self):
        return (f"QComboBox{{background:{T('panel')};color:{T('text')};"
                f"border:1px solid {T('border')};border-radius:6px;padding:3px 8px;font-size:11px;}}"
                f"QComboBox::drop-down{{width:16px;border:none;}}"
                f"QComboBox QAbstractItemView{{background:{T('bg2')};color:{T('text')};"
                f"border:1px solid {T('accent')};selection-background-color:rgba(78,125,240,80);}}")

    def _rebuild_combos(self, *_):
        # 현재 선택값 보존 후 재생성 (최초 호출 땐 콤보가 없으니 초기 cells 유지)
        if self._combos:
            self._cells = self.get_cells_raw()
        while self._cells_grid.count():
            it = self._cells_grid.takeAt(0)
            if it.widget(): it.widget().setParent(None)
        self._combos = []
        rows = self._row_sp.value(); cols = self._col_sp.value()
        n = rows * cols
        cells = (self._cells + [None] * n)[:n]
        for idx in range(n):
            r, c = divmod(idx, cols)
            cb = QComboBox(); cb.setStyleSheet(self._combo_style())
            cb.addItem('— 없음')
            for mid in self._metrics:
                cb.addItem(self._metrics[mid][0])
            cur = cells[idx]
            cb.setCurrentIndex(self._ids.index(cur) if cur in self._ids else 0)
            self._cells_grid.addWidget(cb, r, c)
            self._combos.append(cb)

    def get_cells_raw(self):
        """현재 콤보 상태를 id 리스트로."""
        return [self._ids[cb.currentIndex()] for cb in self._combos]

    def get_layout(self):
        return self._row_sp.value(), self._col_sp.value(), self.get_cells_raw()

    def get_leq_idx(self):
        return self._leq_cb.currentIndex()


# ───────────────────────────────────────────
#  Custom floating dropdown popup
# ───────────────────────────────────────────
class DropdownPopup(QFrame):
    item_selected = pyqtSignal(int)

    def __init__(self, combo):
        super().__init__(None, Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        # Opaque background — no bleed-through from behind
        self.setAutoFillBackground(True)
        pal = self.palette()
        pal.setColor(self.backgroundRole(), QColor(T('bg2')))
        self.setPalette(pal)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(0)
        self.setStyleSheet(
            f'QFrame#popup {{ background:{T("bg2")}; border:1px solid {T("accent")}; border-radius:12px; }}'
        )
        self.setObjectName('popup')

        n = combo.count()
        for i in range(n):
            label = combo.itemText(i)
            selected = (i == combo.currentIndex())
            btn = QPushButton(label)
            btn.setFlat(True)
            btn.setStyleSheet(
                f'QPushButton {{'
                f'  background:{"rgba(78,125,240,70)" if selected else "transparent"};'
                f'  color:{T("accent") if selected else T("text")};'
                f'  border:none; border-radius:7px;'
                f'  padding:6px 16px; font-size:11px; font-weight:{"bold" if selected else "normal"};'
                f'  text-align:left; min-height:26px;'
                f'}}'
                f'QPushButton:hover {{ background:rgba(78,125,240,30); color:{T("text")}; }}'
            )
            # clicked 대신 mousePressEvent — macOS Popup이 mouseRelease 전에 닫혀
            # clicked 시그널이 도달하지 못하는 Intel Mac 버그 우회
            btn.mousePressEvent = lambda e, idx=i: self._pick(idx)
            lay.addWidget(btn)
            # Separator between items (not after the last)
            if i < n - 1:
                sep = QFrame()
                sep.setFrameShape(QFrame.HLine)
                sep.setFixedHeight(1)
                sep.setStyleSheet(f'background:{T("border")}; border:none;')
                lay.addWidget(sep)

    def _pick(self, idx):
        self.item_selected.emit(idx)
        self.close()


# ───────────────────────────────────────────
#  Device Card Popup — 오디오 입력 장치 선택 패널
# ───────────────────────────────────────────
class DeviceCardPopup(QFrame):
    device_selected = pyqtSignal(int)  # combo index
    refresh_requested = pyqtSignal()

    def __init__(self, combo, disconnected_name=''):
        super().__init__(None, Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.setAutoFillBackground(True)
        pal = self.palette()
        pal.setColor(self.backgroundRole(), QColor(T('bg2')))
        self.setPalette(pal)
        self.setObjectName('devPopup')
        self.setStyleSheet(
            f'QFrame#devPopup {{ background:{T("bg2")}; border:1px solid {T("accent")}; '
            f'border-radius:12px; }}'
        )
        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(10, 10, 10, 10)
        self._outer.setSpacing(6)

        hdr_w = QWidget(); hdr_w.setStyleSheet('background:transparent;')
        hdr_lay = QHBoxLayout(hdr_w); hdr_lay.setContentsMargins(0,2,0,2); hdr_lay.setSpacing(4)
        hdr_lay.addStretch(1)
        hdr_title = QLabel(
            f'<span style="font-size:12px;font-weight:700;'
            f'color:{T("accent")};letter-spacing:2px;">AUDIO</span>'
            f'&nbsp;<span style="font-size:10px;color:{T("text_dim")};">입력 장치</span>'
        )
        hdr_title.setStyleSheet('background:transparent; border:none;')
        hdr_lay.addWidget(hdr_title)
        hdr_lay.addStretch(1)
        self._status_lbl = QLabel()
        self._status_lbl.setStyleSheet(
            f'color:{T("green")}; font-size:9px; background:transparent; border:none;'
        )
        self._status_lbl.setVisible(False)
        hdr_lay.addWidget(self._status_lbl)
        self._outer.addWidget(hdr_w)

        sep = QFrame(); sep.setFrameShape(QFrame.HLine); sep.setFixedHeight(1)
        sep.setStyleSheet(f'background:{T("border")}; border:none;')
        self._outer.addWidget(sep)

        # 카드 전용 컨테이너 — rebuild_cards 에서 이 영역만 갱신
        self._cards_widget = QWidget(); self._cards_widget.setStyleSheet('background:transparent;')
        self._cards_layout = QVBoxLayout(self._cards_widget)
        self._cards_layout.setContentsMargins(0, 0, 0, 0); self._cards_layout.setSpacing(6)
        self._outer.addWidget(self._cards_widget)
        self._fill_cards(combo, disconnected_name)

        bot_sep = QFrame(); bot_sep.setFrameShape(QFrame.HLine); bot_sep.setFixedHeight(1)
        bot_sep.setStyleSheet(f'background:{T("border")}; border:none;')
        self._outer.addWidget(bot_sep)

        ref_btn = QPushButton('장치 새로고침'); ref_btn.setIcon(_icon('refresh', 13))
        ref_btn.setFixedHeight(28)
        ref_btn.setStyleSheet(
            f'QPushButton {{ background:transparent; color:{T("text_dim")}; border:none; '
            f'border-radius:6px; font-size:10px; padding:0px 8px; }}'
            f'QPushButton:hover {{ background:rgba(255,255,255,10); color:{T("text")}; }}'
        )
        ref_btn.mousePressEvent = lambda e: self._refresh()
        self._outer.addWidget(ref_btn)

    def _fill_cards(self, combo, disconnected_name):
        for i in range(combo.count()):
            name = combo.itemText(i)
            dev_idx = combo.itemData(i)
            selected = (i == combo.currentIndex())
            disc = bool(disconnected_name and name == disconnected_name)
            ch_count = 0
            try:
                if dev_idx is not None and dev_idx >= 0:
                    ch_count = int(sd.query_devices(dev_idx)['max_input_channels'])
            except Exception:
                pass
            self._cards_layout.addWidget(self._make_card(i, name, ch_count, selected, disc, dev_idx))

    def rebuild_cards(self, combo, disconnected_name=''):
        fixed_w = self.width()
        idx = self._outer.indexOf(self._cards_widget)
        self._outer.removeWidget(self._cards_widget)
        self._cards_widget.hide()
        self._cards_widget.deleteLater()

        self._cards_widget = QWidget()
        self._cards_widget.setStyleSheet('background:transparent;')
        self._cards_layout = QVBoxLayout(self._cards_widget)
        self._cards_layout.setContentsMargins(0, 0, 0, 0)
        self._cards_layout.setSpacing(6)
        self._outer.insertWidget(idx, self._cards_widget)

        self._fill_cards(combo, disconnected_name)
        self.adjustSize()
        self.resize(fixed_w, self.sizeHint().height())
        self._status_lbl.setText('✓ 새로고침 완료')
        self._status_lbl.setVisible(True)
        QTimer.singleShot(2000, self._clear_status)

    def _clear_status(self):
        try:
            self._status_lbl.setVisible(False)
        except RuntimeError:
            pass

    def _refresh(self):
        self.refresh_requested.emit()  # 팝업 닫지 않음 — 메인 윈도우가 갱신 후 rebuild_cards 호출

    def _make_card(self, combo_idx, name, ch_count, selected, disconnected, dev_idx):
        card = QFrame(); card.setObjectName('devCard')
        bg = 'rgba(78,125,240,40)' if selected else T('bg3')
        bd = T('accent') if selected else T('border')
        card.setStyleSheet(
            f'QFrame#devCard {{ background:{bg}; border:1px solid {bd}; border-radius:8px; }}'
        )
        lay = QHBoxLayout(card)
        lay.setContentsMargins(10, 7, 10, 7); lay.setSpacing(8)

        dot = QLabel('●')
        dot_color = T('text_dim') if (disconnected or (dev_idx is not None and dev_idx < 0)) else T('green')
        dot.setStyleSheet(f'color:{dot_color}; font-size:9px; background:transparent; border:none;')
        dot.setFixedWidth(12)
        lay.addWidget(dot)

        txt_w = QWidget(); txt_w.setStyleSheet('background:transparent; border:none;')
        txt_lay = QVBoxLayout(txt_w); txt_lay.setContentsMargins(0,0,0,0); txt_lay.setSpacing(1)

        name_color = T('text_dim') if disconnected else (T('accent') if selected else T('text'))
        name_lbl = QLabel(name)
        name_lbl.setStyleSheet(
            f'color:{name_color};  font-size:11px; '
            f'font-weight:{"bold" if selected else "normal"}; background:transparent; border:none;'
        )
        txt_lay.addWidget(name_lbl)

        if disconnected:
            sub = QLabel('연결 끊김')
            sub.setStyleSheet(f'color:{T("yellow")}; font-size:9px; background:transparent; border:none;')
            txt_lay.addWidget(sub)
        elif ch_count > 0:
            sub = QLabel(f'{ch_count}채널')
            sub.setStyleSheet(f'color:{T("text_dim")}; font-size:9px; background:transparent; border:none;')
            txt_lay.addWidget(sub)

        lay.addWidget(txt_w); lay.addStretch()

        if selected:
            chk = QLabel('✓')
            chk.setStyleSheet(
                f'color:{T("accent")}; font-size:12px; font-weight:bold; '
                f'background:transparent; border:none;'
            )
            lay.addWidget(chk)

        if not disconnected and dev_idx is not None and dev_idx >= 0:
            card.mousePressEvent = lambda e, idx=combo_idx: self._pick(idx)
            card.setCursor(Qt.PointingHandCursor)

        return card

    def _pick(self, idx):
        self.device_selected.emit(idx)
        self.close()


class _DrawerToggleBtn(QPushButton):
    """Logic X 스타일 캡처 드로어 토글 버튼.
    두 개의 수평 pill을 그려 드로어 표시/숨김을 나타낸다."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setFixedSize(38, 30)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip('Capture 패널 표시/숨김')

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        checked = self.isChecked()
        ac = QColor(T('accent'))
        if checked:
            fill = QColor(ac.red(), ac.green(), ac.blue(), 45)
            border = QColor(ac.red(), ac.green(), ac.blue(), 160)
            pill_c = QColor(ac.red(), ac.green(), ac.blue(), 230)
        else:
            fill = QColor(255, 255, 255, 18)
            border = QColor(255, 255, 255, 40)
            pill_c = QColor(T('text_dim'))
        p.setBrush(fill)
        p.setPen(QPen(border, 1.0))
        p.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), 7, 7)
        # 아이콘: 사이드 패널 토글 (오른쪽 칸 채운 패널) — 캡처 패널이 우측이라 직관적
        iw, ih = 18, 14; ix = (w - iw) // 2; iy = (h - ih) // 2
        p.setPen(QPen(pill_c, 1.3)); p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(ix, iy, iw, ih), 3, 3)
        divx = ix + iw * 0.58
        p.setPen(Qt.NoPen); p.setBrush(pill_c)
        p.drawRoundedRect(QRectF(divx, iy + 1.5, ix + iw - divx - 1.5, ih - 3), 2, 2)
        p.end()


class _RightPanelToggleBtn(_DrawerToggleBtn):
    """우측 패널(LEVEL/INFO/INPUT · TF rp) 표시/숨김 토글 — 캡처 드로어 토글과 동일 스타일."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setToolTip('우측 패널 표시/숨김')


class _ToolbarToggleBtn(QPushButton):
    """툴바(컨트롤 바) 접기/펴기 토글 — 탭바에 위치. 셰브론(표시=⌃접기 / 숨김=⌄펴기)."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True); self.setChecked(True)
        self.setFixedSize(30, 28); self.setCursor(Qt.PointingHandCursor)
        self.setToolTip('툴바 접기/펴기')
        self.setStyleSheet('QPushButton{border:none;background:transparent;border-radius:6px;}'
                           'QPushButton:hover{background:rgba(255,255,255,28);}')

    def paintEvent(self, e):
        super().paintEvent(e)   # hover 배경
        shown = self.isChecked()
        col = QColor(T('accent')) if shown else QColor(T('text_dim'))
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        pen = QPen(col, 1.8); pen.setCapStyle(Qt.RoundCap); pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen); p.setBrush(Qt.NoBrush)
        cx, cy = self.width()/2, self.height()/2; d = 4.5
        if shown:   # ⌃ 접기
            p.drawPolyline(QPolygonF([QPointF(cx-d, cy+d*0.6), QPointF(cx, cy-d*0.6), QPointF(cx+d, cy+d*0.6)]))
        else:       # ⌄ 펴기
            p.drawPolyline(QPolygonF([QPointF(cx-d, cy-d*0.6), QPointF(cx, cy+d*0.6), QPointF(cx+d, cy-d*0.6)]))
        p.end()


class _MiniMeterBar(QWidget):
    """채널 팝업 안의 미니 수평 레벨 미터."""
    def __init__(self):
        super().__init__()
        self._level = -100.0
        self._peak  = -100.0
        self.setFixedHeight(8)

    def set_level(self, db):
        self._level = db
        if db > self._peak: self._peak = db
        else: self._peak = max(self._peak - 0.8, db)
        self.update()

    def reset(self):
        self._level = -100.0; self._peak = -100.0; self.update()

    def paintEvent(self, ev):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        W = self.width(); H = self.height(); rr = H / 2.0
        # 은은한 둥근 트랙 (까만 공백 대신). 라이트(near-white)에선 밝히면 사라짐 → 어둡게 파생.
        bg = QColor(T('bg')); d = -20 if _theme == 'light' else 14
        track = QColor(max(0, min(bg.red()+d, 255)), max(0, min(bg.green()+d, 255)), max(0, min(bg.blue()+d+2, 255)))
        p.setPen(Qt.NoPen); p.setBrush(track); p.drawRoundedRect(QRectF(0, 0, W, H), rr, rr)
        DB_MIN = -60.0; DB_MAX = 0.0
        ratio = max(0.0, min(1.0, (self._level - DB_MIN) / (DB_MAX - DB_MIN)))
        bar_w = W * ratio
        if bar_w > 1.5:
            col = QColor(T('red')) if self._level > -3 else QColor(T('yellow')) if self._level > -9 else QColor(T('green'))
            p.setBrush(col); p.drawRoundedRect(QRectF(0, 0, bar_w, H), rr, rr)
        # peak tick
        if self._peak > DB_MIN:
            px = W * max(0.0, min(1.0, (self._peak - DB_MIN) / (DB_MAX - DB_MIN)))
            p.setPen(QPen(QColor(T('text_dim')), 1)); p.drawLine(int(px), 1, int(px), int(H - 1))
        p.end()


class ChannelPopup(QFrame):
    """[+] 버튼으로 열리는 멀티채널 선택 팝업.
    체크박스로 추가 채널을 활성화하고, 각 채널의 실시간 레벨을 미니 미터로 표시."""
    channels_changed = pyqtSignal(list)   # 활성 추가 채널 인덱스 리스트 (primary 제외)

    def __init__(self, parent=None):
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._primary_ch = 0
        self._active = set()
        self._rows = {}   # {ch_idx: {'check', 'meter', 'db_lbl'}}
        self._vlay = QVBoxLayout(self)
        self._vlay.setContentsMargins(10, 8, 10, 10)
        self._vlay.setSpacing(1)
        hdr = QLabel('Input Channels')
        hdr.setStyleSheet(f'color:{T("text_dim")};font-size:11px;font-weight:600;'
                          f'padding-bottom:4px;')
        self._vlay.addWidget(hdr)
        self._sep = QFrame(); self._sep.setFrameShape(QFrame.HLine)
        self._sep.setStyleSheet(f'color:{T("grid")};')
        self._vlay.addWidget(self._sep)

    def _apply_style(self):
        self.setStyleSheet(f'''
            ChannelPopup {{
                background:{T("bg2")};
                border:1px solid {T("grid")};
                border-radius:10px;
            }}
        ''')

    def showEvent(self, e):
        self._apply_style(); super().showEvent(e)

    def set_device_channels(self, n_ch, primary_ch):
        for row in self._rows.values():
            row['widget'].setParent(None)
        self._rows.clear()
        self._primary_ch = primary_ch
        self._active.clear()

        for ch in range(n_ch):
            color = _MC_COLORS[ch % len(_MC_COLORS)]
            row_w = QWidget()
            rl = QHBoxLayout(row_w); rl.setContentsMargins(0, 3, 0, 3); rl.setSpacing(5)

            chk = QCheckBox()
            chk.setFixedWidth(16)
            if ch == primary_ch:
                chk.setChecked(True); chk.setEnabled(False)
            else:
                chk.setChecked(False)
                chk.stateChanged.connect(lambda st, c=ch: self._on_check(c, st))

            dot = QLabel('●')
            main_color = T('spec_line')   # 브랜드 spec_line(라이트 #1670cc) 통일
            dot.setStyleSheet(f'color:{main_color if ch==primary_ch else color};font-size:13px;')
            dot.setFixedWidth(14)

            name_lbl = QLabel(f'Ch {ch + 1}' + (' ★' if ch == primary_ch else ''))
            name_lbl.setStyleSheet(f'color:{T("text")};font-size:11px;')
            name_lbl.setFixedWidth(52)

            meter = _MiniMeterBar(); meter.setFixedWidth(72)

            db_lbl = QLabel('  — ')
            db_lbl.setStyleSheet(f'color:{T("text_dim")};font-size:10px;')
            db_lbl.setFixedWidth(36)
            db_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

            rl.addWidget(chk); rl.addWidget(dot); rl.addWidget(name_lbl)
            rl.addWidget(meter); rl.addWidget(db_lbl)
            self._vlay.addWidget(row_w)
            self._rows[ch] = {'widget': row_w, 'check': chk, 'meter': meter, 'db_lbl': db_lbl}

        self.adjustSize()

    def _on_check(self, ch_idx, state):
        if state == Qt.Checked: self._active.add(ch_idx)
        else: self._active.discard(ch_idx)
        self.channels_changed.emit(sorted(self._active))

    def update_levels(self, levels_dict):
        for ch, db in levels_dict.items():
            if ch in self._rows:
                self._rows[ch]['meter'].set_level(db)
                self._rows[ch]['db_lbl'].setText(f'{db:.1f}')

    def reset_levels(self):
        for row in self._rows.values():
            row['meter'].reset()
            row['db_lbl'].setText('  — ')

    def get_extra_channels(self):
        return sorted(self._active)


class ChannelCard(QFrame):
    """INPUT 패널 내 채널 카드 — 체크박스(그래프 가시성) + 장치명 + 채널 번호 + 레벨 미터."""
    visibility_toggled = pyqtSignal(int, bool)   # (ch_idx, visible)
    remove_requested   = pyqtSignal(int)          # (ch_idx)  — primary는 emit 안 함
    device_clicked     = pyqtSignal()             # primary 카드 전용

    def __init__(self, ch_idx, device_name, color, is_primary=False, parent=None):
        super().__init__(parent)
        self._ch_idx    = ch_idx
        self._is_primary = is_primary
        self._color = color
        self.setObjectName('channelCard')
        lay = QVBoxLayout(self); lay.setContentsMargins(6,5,6,5); lay.setSpacing(3)

        # ── Row 1: [☑] [●] [device name] [×]
        row1 = QHBoxLayout(); row1.setSpacing(3)
        self._chk = QCheckBox(); self._chk.setChecked(True); self._chk.setFixedWidth(16)
        self._chk.setStyleSheet(f'''
            QCheckBox::indicator {{
                width:13px; height:13px;
                border:1.5px solid {color};
                border-radius:3px;
                background:transparent;
            }}
            QCheckBox::indicator:checked {{
                background:{color};
                image:none;
            }}
        ''')
        self._chk.stateChanged.connect(lambda st: self.visibility_toggled.emit(self._ch_idx, st==Qt.Checked))
        dot = QLabel('●')
        dot.setStyleSheet(f'color:{color};background:transparent;font-size:11px;'); dot.setFixedWidth(13)
        short = (device_name[:17]+'..') if len(device_name)>19 else device_name
        if is_primary:
            self._dev_btn_ref = QPushButton(short)
            self._dev_btn_ref.setFlat(True)
            self._dev_btn_ref.setStyleSheet(
                f'color:{T("text")};font-size:10px;text-align:left;padding:0 2px;border:none;'
                f'background:transparent;')
            self._dev_btn_ref.setCursor(Qt.PointingHandCursor)
            self._dev_btn_ref.clicked.connect(self.device_clicked)
            row1.addWidget(self._chk); row1.addWidget(dot); row1.addWidget(self._dev_btn_ref, 1)
        else:
            dev_lbl = QLabel(short)
            dev_lbl.setStyleSheet(f'color:{T("text")};background:transparent;font-size:10px;')
            rm = QPushButton('×'); rm.setFixedSize(16,16)
            rm.setStyleSheet(f'color:{T("text_dim")};font-size:13px;border:none;padding:0;background:transparent;')
            rm.setCursor(Qt.PointingHandCursor)
            rm.clicked.connect(lambda: self.remove_requested.emit(self._ch_idx))
            row1.addWidget(self._chk); row1.addWidget(dot); row1.addWidget(dev_lbl, 1); row1.addWidget(rm)
        lay.addLayout(row1)

        # ── Row 2: [Ch X] [meter] [dB]
        row2 = QHBoxLayout(); row2.setSpacing(3)
        ch_lbl = QLabel(f'Ch {ch_idx+1}')
        ch_lbl.setStyleSheet(f'color:{T("text_dim")};background:transparent;font-size:10px;'); ch_lbl.setFixedWidth(28)
        self._meter = _MiniMeterBar(); self._meter.setFixedHeight(7)
        self._db_lbl = QLabel(' — ')
        self._db_lbl.setStyleSheet(f'color:{T("text_dim")};background:transparent;font-size:10px;')
        self._db_lbl.setFixedWidth(34); self._db_lbl.setAlignment(Qt.AlignRight|Qt.AlignVCenter)
        row2.addWidget(ch_lbl); row2.addWidget(self._meter, 1); row2.addWidget(self._db_lbl)
        lay.addLayout(row2)
        self._apply_style()

    def _apply_style(self):
        # TF 측정 카드와 동일한 색 테두리 룩
        self.setStyleSheet(f'#channelCard{{background:{T("panel")};'
                           f'border:2px solid {self._color};border-radius:{RADIUS_SM}px;padding:1px;}}')

    def update_level(self, db):
        self._meter.set_level(db); self._db_lbl.setText(f'{db:.1f}')

    def reset(self):
        self._meter.reset(); self._db_lbl.setText(' — ')


class _DblClickLabel(QLabel):
    """더블클릭 시 doubleClicked 시그널을 내는 라벨 (카드 이름 인라인 편집용)."""
    doubleClicked = pyqtSignal()
    def mouseDoubleClickEvent(self, e):
        self.doubleClicked.emit()
        super().mouseDoubleClickEvent(e)


def begin_inline_rename(host, label, on_done):
    """label 위에 인라인 QLineEdit 를 띄워 그 자리에서 이름 편집. 확정 시 on_done(text) 호출.
    빈 문자열이면 on_done('') (기본값 복귀는 호출측에서 처리)."""
    from PyQt5.QtWidgets import QLineEdit
    edit = QLineEdit(label.text(), host)
    edit.setStyleSheet(
        f'QLineEdit{{background:{T("bg3")};color:{T("text")};border:1px solid {T("accent")};'
        f'border-radius:{RADIUS_SM}px;padding:0 4px;font-size:{FS_SM}px;}}')
    tl = label.mapTo(host, QPoint(0, 0))
    edit.setGeometry(tl.x(), tl.y() - 1, max(label.width() + 60, 100), label.height() + 2)
    edit.selectAll(); edit.setFocus()
    _done = {'v': False}
    def _finish():
        if _done['v']: return
        _done['v'] = True
        txt = edit.text().strip()
        edit.deleteLater()
        on_done(txt)
    edit.editingFinished.connect(_finish)
    edit.show(); edit.raise_()


class _SpecCard(QFrame):
    """Spectrum 추가 소스 카드 — 카드마다 장치+채널 독립 선택 (멀티-장치 오버레이).
    TF 측정 카드 룩 차용: 색 테두리 + 가시성 토글 + 장치/채널 드롭다운 + 레벨미터 + 삭제."""
    device_changed     = pyqtSignal(int)        # card_id
    channel_changed    = pyqtSignal(int)        # card_id
    visibility_toggled = pyqtSignal(int, bool)  # (card_id, visible)
    remove_requested   = pyqtSignal(int)        # card_id
    selected           = pyqtSignal(int)        # card_id — 카드 클릭 → front
    renamed            = pyqtSignal(int, str)   # (card_id, new_name)

    def __init__(self, card_id, color, dev_items, is_primary=False, parent=None):
        super().__init__(parent)
        self._card_id = card_id
        self._color = color
        self._is_primary = is_primary
        self._is_selected = False
        self._default_name = str(card_id + 1)
        self._name = ''
        self.setObjectName('specCard')
        self._apply_border()
        lay = QVBoxLayout(self); lay.setContentsMargins(6,5,6,6); lay.setSpacing(3)

        # 헤더: [가시성 체크] [●] [번호] ... [삭제]  (모든 카드 동일 레이아웃)
        hdr = QHBoxLayout(); hdr.setContentsMargins(0,0,0,0); hdr.setSpacing(3)
        self._chk = QCheckBox(); self._chk.setChecked(True); self._chk.setFixedWidth(16)
        self._chk.setStyleSheet(
            f'QCheckBox::indicator{{width:13px;height:13px;border:1.5px solid {color};'
            f'border-radius:3px;background:transparent;}}'
            f'QCheckBox::indicator:checked{{background:{color};image:none;}}')
        self._chk.stateChanged.connect(
            lambda st: self.visibility_toggled.emit(self._card_id, st == Qt.Checked))
        dot = QLabel('●'); dot.setStyleSheet(f'color:{color};background:transparent;font-size:11px;'); dot.setFixedWidth(13)
        self._num_label = QLabel(self._default_name)
        self._num_label.setStyleSheet(f'color:{color};background:transparent;font-size:11px;font-weight:bold;')
        self._num_label.setToolTip('더블클릭하여 이름 변경')
        hdr.addWidget(self._chk); hdr.addWidget(dot); hdr.addWidget(self._num_label); hdr.addStretch()
        if not is_primary:
            rm = QPushButton('×'); rm.setFixedSize(16,16)
            rm.setStyleSheet(f'QPushButton{{background:transparent;color:{T("text_dim")};border:none;'
                             f'font-size:13px;padding:0;}}'
                             f'QPushButton:hover{{color:{T("red")};}}')
            rm.clicked.connect(lambda: self.remove_requested.emit(self._card_id))
            hdr.addWidget(rm)
        lay.addLayout(hdr)

        # 미터 행: [M] [meter] [dB]
        mr = QHBoxLayout(); mr.setContentsMargins(0,0,0,0); mr.setSpacing(3)
        # 'M' 라벨 제거 → 레벨미터가 그 폭만큼 넓어짐. 미터 높이도 약간 키움(7→10).
        self._meter = _MiniMeterBar(); self._meter.setFixedHeight(10)
        self._db_lbl = QLabel('—')
        self._db_lbl.setStyleSheet(f'color:{T("text_dim")};background:transparent;font-size:10px;')
        self._db_lbl.setFixedWidth(34); self._db_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        mr.addWidget(self._meter, 1); mr.addWidget(self._db_lbl)
        lay.addLayout(mr)

        lay.addWidget(hsep())

        # 장치 + 채널 행 (장치명은 폭에 맞춰 자동 생략 …)
        _cb_ss = (
            f'QComboBox{{background:{T("bg3")};color:{T("text")};border:1px solid {T("border")};'
            f'border-radius:{RADIUS_SM}px;padding:1px 6px;font-size:{FS_SM}px;min-height:22px;}}'
            f'QComboBox:hover{{border-color:{T("accent")};}}'
            f'QComboBox::drop-down{{width:0;border:none;}}'
            f'QComboBox::down-arrow{{width:0;height:0;image:none;}}')
        row = QHBoxLayout(); row.setContentsMargins(0,0,0,0); row.setSpacing(3)
        lbl = QLabel('In'); lbl.setFixedWidth(14); lbl.setStyleSheet(ss_text(FS_XS))
        self._dev_cb = RoundComboBox(); self._dev_cb.setStyleSheet(_cb_ss)
        self._dev_cb.setMinimumWidth(40)               # stretch로 채워지고 긴 이름은 Qt가 … 로 생략
        self._dev_cb.setMinimumContentsLength(4)
        for name, idx in dev_items:
            self._dev_cb.addItem(name, idx)
        self._ch_cb = RoundComboBox(); self._ch_cb.setStyleSheet(_cb_ss)
        self._ch_cb.setFixedWidth(50); self._ch_cb._align_center = True
        row.addWidget(lbl); row.addWidget(self._dev_cb, 1); row.addWidget(self._ch_cb)
        lay.addLayout(row)
        self._dev_cb.currentIndexChanged.connect(lambda _: self.device_changed.emit(self._card_id))
        self._ch_cb.currentIndexChanged.connect(lambda _: self.channel_changed.emit(self._card_id))

    def _apply_border(self):
        # 네온 풀컬러 → 차분한 저알파 색 프레임 (정체성은 스와치·점·번호가 담당). TF _MeasCard와 통일.
        c = QColor(self._color); r, g, b = c.red(), c.green(), c.blue()
        if self._is_selected:
            self.setStyleSheet(f'#specCard{{border:2px solid rgba({r},{g},{b},230);'
                               f'border-radius:{RADIUS_SM}px;background:rgba({r},{g},{b},30);padding:1px;}}')
        else:
            self.setStyleSheet(f'#specCard{{border:1px solid rgba({r},{g},{b},110);'
                               f'border-radius:{RADIUS_SM}px;background:{T("panel")};padding:2px;}}')

    def set_selected(self, on):
        on = bool(on)
        if on == self._is_selected: return
        self._is_selected = on; self._apply_border()

    def set_name(self, name):
        self._name = name or ''
        self._num_label.setText(self._name or self._default_name)

    def set_number(self, n):
        """표시 번호(위치 기반)를 설정. 사용자 지정 이름이 없을 때만 라벨에 반영."""
        self._default_name = str(n)
        if not self._name:
            self._num_label.setText(self._default_name)

    def _begin_rename(self):
        begin_inline_rename(self, self._num_label, self._on_renamed)

    def _on_renamed(self, txt):
        self._name = txt
        self._num_label.setText(txt or self._default_name)
        self.renamed.emit(self._card_id, txt)

    def mousePressEvent(self, e):
        self.selected.emit(self._card_id)
        super().mousePressEvent(e)

    def mouseDoubleClickEvent(self, e):
        # 카드 본문 더블클릭 → 이름 편집 (자식 콤보/체크박스는 자체 처리)
        self._begin_rename()
        super().mouseDoubleClickEvent(e)

    def device_idx(self):  return self._dev_cb.currentData()
    def device_name(self): return self._dev_cb.currentText()
    def channel(self):     return self._ch_cb.currentData() or 0

    def set_device(self, idx):
        for i in range(self._dev_cb.count()):
            if self._dev_cb.itemData(i) == idx:
                self._dev_cb.setCurrentIndex(i); return

    def set_channel(self, ch):
        for i in range(self._ch_cb.count()):
            if self._ch_cb.itemData(i) == ch:
                self._ch_cb.setCurrentIndex(i); return

    def set_channel_list(self, n_ch):
        self._ch_cb.blockSignals(True)
        cur = self._ch_cb.currentData()
        self._ch_cb.clear()
        for i in range(max(n_ch, 1)):
            self._ch_cb.addItem(f'Ch {i+1}', i)
        if cur is not None:
            for i in range(self._ch_cb.count()):
                if self._ch_cb.itemData(i) == cur: self._ch_cb.setCurrentIndex(i); break
        self._ch_cb.blockSignals(False)

    def update_level(self, db):
        self._meter.set_level(db); self._db_lbl.setText(f'{db:.0f}')

    def reset(self):
        self._meter.reset(); self._db_lbl.setText('—')


class _SidebarIcon(QWidget):
    """Small monochrome icon for sidebar section headers. icon_type: 'level' or 'info'"""
    def __init__(self, icon_type, color, size=15, parent=None):
        super().__init__(parent)
        self._type = icon_type
        self._col  = QColor(color)
        self.setFixedSize(size, size)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        if self._type == 'level':
            # Three vertical equaliser bars
            p.setPen(Qt.NoPen); p.setBrush(self._col)
            bw = max(2, w // 4)
            gap = max(1, (w - 3*bw) // 2)
            x0  = (w - (3*bw + 2*gap)) // 2
            heights = [int(h*0.50), int(h*0.90), int(h*0.70)]
            for i, bh_ in enumerate(heights):
                bx = x0 + i*(bw+gap)
                p.drawRoundedRect(bx, h-bh_, bw, bh_, 1, 1)

        elif self._type == 'info':
            # Lucide info — 동그라미 + i (아웃라인)
            _svg_render(p, _LUCIDE_ICONS['info'][0], self._col.name(), w)

        elif self._type == 'input':
            # Lucide audio-lines — 오디오 입력 막대 파형
            _svg_render(p, _LUCIDE_ICONS['audio-lines'][0], self._col.name(), w)

        p.end()


class _SplMeterBtn(QPushButton):
    """Open-in-new-window icon button — two overlapping squares, state-aware color."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(28, 28)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip('Open SPL Meter')

    def enterEvent(self, e): self.update()
    def leaveEvent(self, e): self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        # State-based background
        if self.isDown():
            bg = QColor('#1e82f0')
        elif self.underMouse():
            bg = QColor('#2C2C2E')
        else:
            bg = QColor(0, 0, 0, 0)  # 완전 투명

        p.setPen(Qt.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(QRectF(self.rect()), 5, 5)

        # Icon: Lucide external-link — INFO/INPUT 섹션 아이콘과 동일 액센트색으로 통일
        w, h = self.width(), self.height()
        isz = 17; off = (w - isz) / 2
        p.translate(off, off)
        _svg_render(p, _LUCIDE_ICONS['extlink'][0], QColor(T('accent')).name(), isz)
        p.end()


class _CheckBtn(QPushButton):
    """Checkable QPushButton — CSS :checked border는 macOS에서 클리핑되므로
    paintEvent에서 QPainter로 직접 테두리를 그린다."""
    def __init__(self, text='', parent=None):
        super().__init__(text, parent)
        self.setCheckable(True)

    def paintEvent(self, e):
        super().paintEvent(e)
        if self.isChecked():
            p = QPainter(self)
            p.setRenderHint(QPainter.Antialiasing)
            ac = QColor(T('accent'))
            # 네온 글로우(밝은 테두리) → 차분한 "채워진 선택" 스타일: 채움 ↑, 테두리 톤다운·얇게
            fill = QColor(ac); fill.setAlpha(64)
            p.setBrush(fill)
            glow = QColor(ac); glow.setAlpha(135)
            p.setPen(QPen(glow, 1.0))
            p.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 6, 6)
            p.end()


class _SegBtn(QPushButton):
    """세그먼트 컨트롤 내부 버튼 — 활성 시 블루 채움(직접 페인트). 모던 툴바용."""
    def __init__(self, text='', parent=None):
        super().__init__(text, parent)
        self.setCheckable(True); self.setFlat(True)
        self.setCursor(Qt.PointingHandCursor)

    def paintEvent(self, e):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        on = self.isChecked(); en = self.isEnabled()
        if on:
            ac = QColor(T('accent')); ac.setAlpha(70)
            p.setBrush(ac); p.setPen(Qt.NoPen)
            p.drawRoundedRect(self.rect().adjusted(1, 2, -1, -2), 6, 6)
        col = (T('text') if on else T('text_dim')) if en else T('border')
        p.setPen(QColor(col))
        f = self.font(); f.setBold(on); p.setFont(f)
        p.drawText(self.rect(), Qt.AlignCenter, self.text())
        p.end()


class _SegmentedControl(QWidget):
    """모던 세그먼트 컨트롤 — 하나의 펄 안에 옵션들, 활성만 블루 강조 (iOS식)."""
    changed = pyqtSignal(str)
    def __init__(self, items, height=30, parent=None):   # items = [(key, label, width|None), ...]
        super().__init__(parent)
        self.setObjectName('segCtl'); self.setFixedHeight(height)
        lay = QHBoxLayout(self); lay.setContentsMargins(3, 0, 3, 0); lay.setSpacing(2)
        self._btns = {}
        for key, label, w in items:
            b = _SegBtn(label); b.setFixedHeight(height - 6)
            if w: b.setFixedWidth(w)
            b.clicked.connect(lambda _=False, k=key: self._on_click(k))
            lay.addWidget(b); self._btns[key] = b
        self.apply_theme()

    def _on_click(self, key):
        self.set_active(key); self.changed.emit(key)

    def set_active(self, key):
        for k, b in self._btns.items():
            b.setChecked(k == key); b.update()

    def active(self):
        for k, b in self._btns.items():
            if b.isChecked(): return k
        return None

    def apply_theme(self):
        bg = '#252527' if _theme == 'dark' else T('bg3')
        self.setStyleSheet(f'#segCtl{{background:{bg};border-radius:8px;}}')
        for b in self._btns.values(): b.update()


class _CaptureBar(QWidget):
    """캡처 트레이스 목록 수평 바.
    라벨 클릭 → selected(idx) — 해당 캡처를 맨 앞으로
    × 클릭   → delete_requested(idx)
    """
    delete_requested = pyqtSignal(int)
    selected = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(26)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 2, 6, 2)
        lay.setSpacing(2)
        self._widgets = []
        self.setVisible(False)

    def refresh(self, captures):
        lay = self.layout()
        while lay.count():
            item = lay.takeAt(0)
            w = item.widget()
            if w: w.deleteLater()
        self._widgets = []

        for i, cap in enumerate(captures):
            dot = QLabel('■')
            dot.setStyleSheet(f'color:{cap["color"]};font-size:14px;padding:0 1px;')
            lbl = QPushButton(cap['label'])
            lbl.setFlat(True)
            lbl.setStyleSheet(
                f'color:#ccc;font-size:10px;border:none;background:transparent;'
                f'padding:0 3px;font-weight:{"bold" if i==len(captures)-1 else "normal"};')
            lbl.setToolTip('클릭 → 맨 앞으로')
            lbl.clicked.connect(lambda _, idx=i: self.selected.emit(idx))
            del_btn = QPushButton('×')
            del_btn.setFixedSize(15, 15)
            del_btn.setStyleSheet('border:none;color:#666;font-size:12px;background:transparent;padding:0;')
            del_btn.clicked.connect(lambda _, idx=i: self.delete_requested.emit(idx))
            lay.addWidget(dot); lay.addWidget(lbl); lay.addWidget(del_btn)
            if i < len(captures) - 1:
                sep = QLabel('|'); sep.setStyleSheet('color:#333;font-size:10px;padding:0 2px;')
                lay.addWidget(sep)
            self._widgets.append((dot, lbl, del_btn))

        lay.addStretch()
        self.setVisible(len(captures) > 0)



class _DragGrip(QLabel):
    """캡처 행 드래그 핸들. 전역 이벤트 필터 없이 마우스 이벤트를 직접 처리."""
    def __init__(self, drawer, mode, cap_idx):
        super().__init__('⠿')
        self._d = drawer; self._m = mode; self._i = cap_idx
        self._active = False
        self.setFixedWidth(10)
        self.setCursor(Qt.SizeVerCursor)
        self.setStyleSheet('color:#48484A;font-size:10px;')

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self._active = True
            self._d._start_drag(self._m, self._i, ev.globalPos().y())
            ev.accept()
        else:
            super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev):
        if self._active and (ev.buttons() & Qt.LeftButton):
            self._d._update_drag(ev.globalPos().y())
            ev.accept()
        else:
            super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.LeftButton and self._active:
            self._active = False
            self._d._finish_drag()
            ev.accept()
        else:
            super().mouseReleaseEvent(ev)


class _CaptureDrawer(QWidget):
    """캡처 패널 — 토글 버튼으로 완전 표시/완전 숨김만 지원.
    - SPEC / TF 탭 분리
    - 그룹 폴더(▶/▼) + 그룹 삭제(×)
    - ⠿ 드래그 핸들로 순서 변경
    """
    delete_requested  = pyqtSignal(str, int)        # (mode, idx)
    rename_requested  = pyqtSignal(str, int, str)   # (mode, idx, new_name)
    new_group_req     = pyqtSignal(str)             # (mode)
    delete_group_req  = pyqtSignal(str, str)        # (mode, group_name)
    reorder_requested = pyqtSignal(str, int, int)   # (mode, src_cap_idx, tgt_cap_idx)
    capture_selected  = pyqtSignal(str, int)        # (mode, idx) — 클릭 시 맨 앞으로
    visibility_changed = pyqtSignal(str, int, bool) # (mode, idx, visible)
    average_requested  = pyqtSignal(str)            # (mode) — TF 평균
    reference_changed  = pyqtSignal(str, int)       # (mode, idx) — Δ 기준 캡쳐 (-1=해제)
    export_requested   = pyqtSignal(str)            # (mode) — 캡쳐 내보내기
    move_to_group_req  = pyqtSignal(str, int, str)  # (mode, idx, group_name) — 그룹 이동 ('' = 그룹 해제)

    PANEL_W = 220

    def __init__(self, parent=None):
        super().__init__(parent)
        self._collapsed  = {}
        self._cur_mode   = 'spec'
        self._panel_tab  = 'spec'
        self._spec_caps  = []
        self._tf_caps    = []
        self._row_registry = []
        self._group_registry = []   # [(mode, gname, header_widget)] — 드래그-투-그룹 판정용
        self._drag       = None
        self._drop_line  = None

        self.setFixedWidth(self.PANEL_W)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(4, 4, 2, 4); outer.setSpacing(0)

        # ── 패널 ──────────────────────────────
        self._panel = QWidget()
        self._panel.setObjectName('capturePanel')
        pv = QVBoxLayout(self._panel)
        pv.setContentsMargins(0, 0, 0, 0); pv.setSpacing(0)

        # 헤더
        hdr = QWidget(); hdr.setFixedHeight(30)
        hl = QHBoxLayout(hdr); hl.setContentsMargins(8, 4, 4, 4); hl.setSpacing(4)
        hl.addWidget(QLabel('CAPTURES',
            styleSheet='color:#4E7DF0;font-size:13px;font-weight:bold;'))
        hl.addStretch()
        self._avg_btn = QPushButton('Avg')
        self._avg_btn.setFixedSize(36, 20)
        self._avg_btn.setToolTip('체크된 TF 캡처들의 평균 생성')
        self._avg_btn.setStyleSheet(
            'font-size:9px;font-weight:600;border:1px solid #38383A;border-radius:5px;'
            'background:#1C1C1E;color:#4E7DF0;padding:0 2px;')
        self._avg_btn.clicked.connect(lambda: self.average_requested.emit(self._panel_tab))
        self._avg_btn.setVisible(False)
        hl.addWidget(self._avg_btn)
        self._export_btn = QPushButton(''); self._export_btn.setIcon(_icon('download',13))
        self._export_btn.setFixedSize(22, 20)
        self._export_btn.setToolTip('TF 캡처 내보내기 (CSV + PNG)')
        self._export_btn.setStyleSheet(
            'font-size:12px;font-weight:600;border:1px solid #38383A;border-radius:5px;'
            'background:#1C1C1E;color:#4E7DF0;padding:0;')
        self._export_btn.clicked.connect(lambda: self.export_requested.emit(self._panel_tab))
        self._export_btn.setVisible(False)
        hl.addWidget(self._export_btn)
        grp_btn = QPushButton('+ Grp')
        grp_btn.setFixedSize(44, 20)
        grp_btn.setToolTip('새 그룹 만들기')
        grp_btn.setStyleSheet(
            'font-size:9px;font-weight:600;border:1px solid #38383A;border-radius:5px;'
            'background:#2C2C2E;color:#8E8E93;padding:0 3px;')
        grp_btn.clicked.connect(lambda: self.new_group_req.emit(self._panel_tab))
        hl.addWidget(grp_btn)
        pv.addWidget(hdr)

        # SPEC / TF 탭 바 — Apple segmented control style
        tab_bar = QWidget(); tab_bar.setFixedHeight(40)
        tab_bar.setObjectName('segCtrlWrap')
        tbl_outer = QHBoxLayout(tab_bar)
        tbl_outer.setContentsMargins(8, 5, 8, 5); tbl_outer.setSpacing(0)

        self._seg_pill = QWidget(); self._seg_pill.setObjectName('segPill')
        self._seg_pill.setStyleSheet(
            '#segPill{background:#3A3A3C;border-radius:8px;}')
        tbl = QHBoxLayout(self._seg_pill)
        tbl.setContentsMargins(2, 2, 2, 2); tbl.setSpacing(2)

        self._spec_tab_btn = QPushButton('Spectrum')
        self._tf_tab_btn   = QPushButton('Transfer Fn')
        _tab_ss = (
            'QPushButton{font-size:11px;font-weight:600;border:none;'
            'background:transparent;color:#8E8E93;padding:0 4px;border-radius:6px;}'
            'QPushButton:checked{background:#636366;color:#FFFFFF;}'
            'QPushButton:hover:!checked{background:rgba(255,255,255,12);}')
        for btn, mode in [(self._spec_tab_btn, 'spec'), (self._tf_tab_btn, 'tf')]:
            btn.setFixedHeight(26); btn.setCheckable(True)
            btn.setStyleSheet(_tab_ss)
            btn.clicked.connect(lambda _, m=mode: self._switch_panel_tab(m))
            tbl.addWidget(btn, 1)

        tbl_outer.addWidget(self._seg_pill, 1)
        self._spec_tab_btn.setChecked(True)
        self._seg_tab_bar = tab_bar
        pv.addWidget(tab_bar)

        # 스크롤 영역
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setObjectName('capScroll')
        self._scroll.setStyleSheet(
            '#capScroll { background:#000000; border:1px solid #38383A; }'
            'QScrollBar:vertical{width:5px;background:transparent;}'
            'QScrollBar::handle:vertical{background:#38383A;border-radius:2px;}')
        self._scroll.viewport().setStyleSheet('background:#000000;')

        self._inner = QWidget()
        self._inner.setObjectName('capInner')
        self._inner.setMouseTracking(True)
        self._inner.setStyleSheet('#capInner { background:#000000; }')
        self._ilay = QVBoxLayout(self._inner)
        self._ilay.setContentsMargins(0, 0, 0, 0); self._ilay.setSpacing(0)
        self._ilay.addStretch()
        self._scroll.setWidget(self._inner)
        pv.addWidget(self._scroll, 1)

        outer.addWidget(self._panel, 1)

    # ── 공개 메서드 ─────────────────────────────────
    def _switch_panel_tab(self, mode):
        self._panel_tab = mode
        self._spec_tab_btn.setChecked(mode == 'spec')
        self._tf_tab_btn.setChecked(mode == 'tf')
        self._avg_btn.setVisible(mode == 'tf')
        self._export_btn.setVisible(mode == 'tf')
        self._redraw()

    def set_active_mode(self, mode):
        self._cur_mode = mode
        self._switch_panel_tab(mode)

    def set_pending_group(self, mode, name):
        self._pending_group = (mode, name)

    def _get_pending_group(self, mode):
        pg = getattr(self, '_pending_group', None)
        return pg[1] if pg and pg[0] == mode else None

    def toggle(self):
        self.setVisible(not self.isVisible())

    def refresh(self, spec_caps, tf_caps):
        self._spec_caps = spec_caps
        self._tf_caps   = tf_caps
        if not getattr(self, '_refresh_pending', False):
            self._refresh_pending = True
            QTimer.singleShot(16, self._deferred_redraw)

    def _deferred_redraw(self):
        self._refresh_pending = False
        self._redraw()

    # ── 드래그 로직 ─────────────────────────────────
    def _start_drag(self, mode, cap_idx, global_y):
        # 기존 드롭 라인 정리
        if self._drop_line:
            self._drop_line.deleteLater()
            self._drop_line = None
        self._drag = {'mode': mode, 'src': cap_idx, 'tgt_slot': 0}
        self._drop_line = QFrame(self._inner)
        self._drop_line.setFrameShape(QFrame.HLine)
        self._drop_line.setStyleSheet('background:#80d8ff;')
        self._drop_line.setFixedHeight(2)
        self._drop_line.raise_()
        self._drop_line.show()

    def _update_drag(self, global_y):
        if not self._drag: return
        self._drag['y'] = global_y   # 드롭 시 그룹 판정용 마지막 커서 Y
        mode = self._drag['mode']
        rows = [(ci, w) for m, ci, w in self._row_registry if m == mode]
        if not rows: return
        slot = 0
        for k, (ci, w) in enumerate(rows):
            try:
                cy = w.mapToGlobal(w.rect().center()).y()
            except RuntimeError:
                continue
            if global_y > cy:
                slot = k + 1
        slot = max(0, min(slot, len(rows)))
        self._drag['tgt_slot'] = slot
        if self._drop_line:
            n = len(rows)
            try:
                if slot < n:
                    ref_w = rows[slot][1]
                    ly = self._inner.mapFromGlobal(
                        ref_w.mapToGlobal(QPoint(0, 0))).y()
                else:
                    ref_w = rows[-1][1]
                    ly = self._inner.mapFromGlobal(
                        ref_w.mapToGlobal(QPoint(0, ref_w.height()))).y()
                self._drop_line.setGeometry(
                    0, max(0, ly - 1), max(1, self._inner.width()), 2)
                self._drop_line.raise_()
            except RuntimeError:
                pass

    def _finish_drag(self):
        if self._drop_line:
            self._drop_line.deleteLater()
            self._drop_line = None
        if not self._drag: return
        mode = self._drag['mode']
        src  = self._drag['src']
        slot = self._drag.get('tgt_slot', 0)
        drop_y = self._drag.get('y', None)
        self._drag = None
        # ① 그룹 이동 — 드롭한 위치의 그룹이 src 의 현재 그룹과 다르면 그룹만 변경
        # (빈 그룹으로도 이동 가능). 같은 그룹/영역이면 ②로 내려가 순서 변경.
        if drop_y is not None:
            caps = self._spec_caps if mode == 'spec' else self._tf_caps
            if 0 <= src < len(caps):
                cur_g = caps[src].get('group', '')
                tgt_g = self._target_group_at(mode, drop_y)
                if tgt_g != cur_g:
                    QTimer.singleShot(0, lambda: self.move_to_group_req.emit(mode, src, tgt_g))
                    return
        # ② 같은 그룹/영역 내 순서 변경 (기존 동작)
        rows = [(ci, w) for m, ci, w in self._row_registry if m == mode]
        if not rows: return
        n = len(rows)
        src_k = next((k for k, (ci, _) in enumerate(rows) if ci == src), -1)
        if src_k == -1: return
        if slot == src_k or slot == src_k + 1: return
        if slot < n:
            tgt = rows[slot][0]
        else:
            tgt = rows[-1][0] + 1
        # QTimer로 지연 발행 — mouseReleaseEvent 스택 탈출 후 실행
        QTimer.singleShot(0, lambda: self.reorder_requested.emit(mode, src, tgt))

    def _target_group_at(self, mode, global_y):
        """드롭한 전역 Y가 속한 그룹 이름 반환 — 그룹 헤더 위(ungrouped 영역)면 ''.
        각 그룹 섹션은 그 헤더부터 다음 헤더 직전까지. 빈 그룹 헤더로도 드롭 가능."""
        tops = []
        for m, g, w in self._group_registry:
            if m != mode: continue
            try: tops.append((g, w.mapToGlobal(QPoint(0, 0)).y()))
            except RuntimeError: continue
        if not tops: return ''
        if global_y < tops[0][1]: return ''   # 첫 그룹 헤더 위 → ungrouped
        cur = ''
        for g, t in tops:
            if global_y >= t: cur = g
            else: break
        return cur

    # ── 내부 렌더링 ─────────────────────────────────
    def _clear_inner(self):
        while self._ilay.count() > 1:
            item = self._ilay.takeAt(0)
            w = item.widget()
            if w: w.deleteLater()

    def _redraw(self):
        self._clear_inner()
        self._row_registry = []
        self._group_registry = []
        pos = 0
        caps = self._spec_caps if self._panel_tab == 'spec' else self._tf_caps
        pg   = self._get_pending_group(self._panel_tab)
        mode = self._panel_tab
        if not caps and not pg:
            return
        self._build_section(caps, mode, pos, pg)

    def _build_section(self, caps, mode, pos, pending_group=None):
        groups = {}; seen = []; ungrouped = []
        front_idx = len(caps) - 1 if caps else -1
        for i, cap in enumerate(caps):
            g = cap.get('group', '')
            if g:
                if g not in groups: groups[g] = []; seen.append(g)
                groups[g].append((i, cap))
            else:
                ungrouped.append((i, cap))

        if pending_group and pending_group not in seen:
            seen.append(pending_group); groups[pending_group] = []

        for i, cap in ungrouped:
            row = self._make_row(cap, i, mode, 0, i == front_idx)
            self._row_registry.append((mode, i, row))
            self._ilay.insertWidget(pos, row); pos += 1

        grp_text = T('accent')
        grp_hover = T('bg3')
        grp_bg_color = T('bg2')
        del_col = T('red')

        for gname in seen:
            items = groups[gname]
            collapsed  = self._collapsed.get((mode, gname), False)
            is_pending = (len(items) == 0)
            cnt_str    = '비어있음' if is_pending else str(len(items))

            ghdr = QWidget(); ghdr.setFixedHeight(28)
            ghl  = QHBoxLayout(ghdr)
            ghl.setContentsMargins(2, 0, 2, 0); ghl.setSpacing(0)
            gbtn = QPushButton(f'  {"▶" if collapsed else "▼"}  {gname}  ({cnt_str})')
            gbtn.setFlat(True)
            dim = T('text_dim')
            gbtn.setStyleSheet(
                f'QPushButton{{text-align:left;color:{dim};font-size:14px;font-weight:bold;'
                f'background:{grp_bg_color};border:none;border-radius:4px;padding:0 4px;}}'
                f'QPushButton:hover{{background:{grp_hover};}}')
            gbtn.clicked.connect(lambda _, m=mode, g=gname: self._toggle_group(m, g))
            ghl.addWidget(gbtn, 1)
            gdel = QPushButton('×')
            gdel.setFixedSize(22, 22)
            gdel.setToolTip(f'그룹 "{gname}" 삭제')
            gdel.setStyleSheet(
                f'border:none;color:{del_col};font-size:16px;background:transparent;padding:0;')
            gdel.clicked.connect(
                lambda _, m=mode, g=gname: self.delete_group_req.emit(m, g))
            ghl.addWidget(gdel)
            self._ilay.insertWidget(pos, ghdr); pos += 1
            self._group_registry.append((mode, gname, ghdr))   # 드래그-투-그룹 판정용

            if not collapsed and not is_pending:
                for i, cap in items:
                    row = self._make_row(cap, i, mode, 12, i == front_idx)
                    self._row_registry.append((mode, i, row))
                    self._ilay.insertWidget(pos, row); pos += 1
            elif not collapsed and is_pending:
                ph = QLabel('  다음 캡처가 여기 들어갑니다')
                ph.setStyleSheet(
                    f'color:{T("text_dim")};font-size:13px;font-style:italic;padding:2px 4px;')
                self._ilay.insertWidget(pos, ph); pos += 1

        return pos

    def _toggle_group(self, mode, gname):
        key = (mode, gname)
        self._collapsed[key] = not self._collapsed.get(key, False)
        self._redraw()

    def _make_row(self, cap, idx, mode, indent, is_front=False):
        row = QWidget()
        rl  = QHBoxLayout(row)
        rl.setContentsMargins(indent + 2, 2, 2, 2); rl.setSpacing(3)

        grip = _DragGrip(self, mode, idx)

        _vis = cap.get('visible', True)
        chk = QPushButton('✓' if _vis else '')
        chk.setCheckable(True); chk.setChecked(_vis)
        chk.setFixedSize(20, 20)
        chk.setStyleSheet(
            'QPushButton{font-size:13px;font-weight:bold;border:2px solid #48484A;'
            'border-radius:4px;background:#1C1C1E;color:#4E7DF0;padding:0;}'
            'QPushButton:checked{border:2px solid #4E7DF0;background:#1C2A3A;}')
        def _on_vis(c, b=chk, m=mode, i=idx):
            b.setText('✓' if c else '')
            self.visibility_changed.emit(m, i, c)
        chk.toggled.connect(_on_vis)

        dot = QLabel('■')
        dot.setStyleSheet(f'color:{cap["color"]};font-size:12px;')
        dot.setFixedWidth(14)

        lbl = QLabel(cap['label'])
        lbl_color = T('text') if is_front else T('text_dim')
        lbl.setStyleSheet(f'color:{lbl_color};font-size:11px;font-weight:{"bold" if is_front else "normal"};')
        lbl.setCursor(Qt.PointingHandCursor)
        lbl.setToolTip('클릭 → 맨 앞으로  |  더블클릭 → 이름 변경')
        def on_press(ev, m=mode, i=idx):
            if ev.button() == Qt.LeftButton:
                self.capture_selected.emit(m, i)
        lbl.mousePressEvent = on_press
        def on_dbl(ev, m=mode, i=idx):
            cur  = self._get_cap_label(m, i)
            name, ok = _text_input_dialog(self.window(), '이름 변경', '새 이름:', cur)
            if ok and name.strip():
                self.rename_requested.emit(m, i, name.strip())
        lbl.mouseDoubleClickEvent = on_dbl

        rl.addWidget(grip)
        rl.addWidget(chk)
        rl.addWidget(dot)
        rl.addWidget(lbl, 1)

        # TF 전용: Δ 비교 기준(Reference) 토글
        if mode == 'tf':
            ref_btn = QPushButton('R')
            ref_btn.setCheckable(True)
            ref_btn.setChecked(bool(cap.get('is_ref', False)))
            ref_btn.setFixedSize(18, 18)
            ref_btn.setToolTip('Δ 비교 기준으로 지정 (한 번에 하나)')
            ref_btn.setStyleSheet(
                'QPushButton{font-size:10px;font-weight:bold;border:1px solid #48484A;'
                'border-radius:4px;background:#1C1C1E;color:#8E8E93;padding:0;}'
                'QPushButton:checked{border:1px solid #FF9F0A;background:#3A2A10;color:#FF9F0A;}')
            def _on_ref(c, m=mode, i=idx):
                self.reference_changed.emit(m, i if c else -1)
            ref_btn.toggled.connect(_on_ref)
            rl.addWidget(ref_btn)
        badge_txt = cap.get('mode', '')
        if badge_txt and badge_txt not in ('FFT', ''):
            badge = QLabel(badge_txt)
            badge.setStyleSheet(f'color:{T("text_dim")};font-size:10px;')
            rl.addWidget(badge)

        del_btn = QPushButton('×')
        del_btn.setFixedSize(16, 16)
        del_btn.setStyleSheet(
            f'border:none;color:{T("text_dim")};font-size:14px;background:transparent;padding:0;')
        del_btn.clicked.connect(
            lambda _, m=mode, i=idx: self.delete_requested.emit(m, i))
        rl.addWidget(del_btn)

        # 우클릭 → 그룹으로 이동 메뉴 (빈 그룹으로도 이동 가능)
        row.setContextMenuPolicy(Qt.CustomContextMenu)
        row.customContextMenuRequested.connect(
            lambda pos, m=mode, i=idx, w=row: self._show_row_menu(m, i, w.mapToGlobal(pos)))

        row.setObjectName(f'capRow')
        sep_c = '#2A2A2A'
        row_bg = T('bg')
        if is_front:
            ac = QColor(T('accent')); ar2,ag2,ab2 = ac.red(),ac.green(),ac.blue()
            row.setStyleSheet(
                f'#capRow{{background:rgba({ar2},{ag2},{ab2},18);border-bottom:1px solid {sep_c};}}'
                f'#capRow:hover{{background:rgba({ar2},{ag2},{ab2},30);}}')
        else:
            row.setStyleSheet(
                f'#capRow{{background:{row_bg};border-bottom:1px solid {sep_c};}}'
                f'#capRow:hover{{background:{T("bg3")};}}')
        return row

    def _get_cap_label(self, mode, idx):
        caps = self._spec_caps if mode == 'spec' else self._tf_caps
        if 0 <= idx < len(caps): return caps[idx].get('label', '')
        return ''

    def _show_row_menu(self, mode, cap_idx, global_pos):
        """캡처 행 우클릭 → 기존/대기 그룹 목록으로 이동 + 그룹 해제."""
        from PyQt5.QtWidgets import QMenu
        caps = self._spec_caps if mode == 'spec' else self._tf_caps
        if not (0 <= cap_idx < len(caps)): return
        cur_group = caps[cap_idx].get('group', '')
        names = []
        for c in caps:
            g = c.get('group', '')
            if g and g not in names: names.append(g)
        pg = self._get_pending_group(mode)
        if pg and pg not in names: names.append(pg)

        menu = QMenu(self)
        if not names:
            act = menu.addAction('그룹 없음 — 먼저 “+ Grp” 으로 생성')
            act.setEnabled(False)
        else:
            title = menu.addAction('그룹으로 이동'); title.setEnabled(False)
            for g in names:
                act = menu.addAction(('✓ ' if g == cur_group else '    ') + g)
                act.triggered.connect(
                    lambda _=False, gg=g, m=mode, i=cap_idx: self.move_to_group_req.emit(m, i, gg))
        if cur_group:
            menu.addSeparator()
            ung = menu.addAction('그룹에서 빼기')
            ung.triggered.connect(
                lambda _=False, m=mode, i=cap_idx: self.move_to_group_req.emit(m, i, ''))
        menu.exec_(global_pos)


class RoundComboBox(QComboBox):
    _max_display_chars = None  # int으로 설정 시 해당 글자수+'..'로 표기 트런케이션
    _align_center = False      # True면 텍스트 가운데 정렬

    def paintEvent(self, event):
        if not self._align_center and self._max_display_chars is None:
            super().paintEvent(event)
            return
        painter = QStylePainter(self)
        opt = QStyleOptionComboBox()
        self.initStyleOption(opt)
        text = opt.currentText
        if self._max_display_chars is not None and len(text) > self._max_display_chars:
            text = text[:self._max_display_chars] + '..'
        painter.drawComplexControl(QStyle.CC_ComboBox, opt)
        # 커스텀 페인트라 stylesheet color가 안 먹음 → 시스템 팔레트(맥 다크모드=흰색)로
        # 그려져 라이트 테마에서 글씨가 안 보임. 테마 텍스트색을 명시한다.
        _tc = QColor(T('text'))
        if self._align_center:
            rect = self.style().subControlRect(
                QStyle.CC_ComboBox, opt, QStyle.SC_ComboBoxEditField, self)
            painter.setPen(_tc)
            painter.drawText(rect, Qt.AlignCenter, text)
        else:
            opt.currentText = text
            opt.palette.setColor(QPalette.ButtonText, _tc)
            opt.palette.setColor(QPalette.Text, _tc)
            painter.drawControl(QStyle.CE_ComboBoxLabel, opt)
        painter.end()

    def showPopup(self):
        popup = DropdownPopup(self)
        popup.item_selected.connect(self.setCurrentIndex)
        popup.adjustSize()
        w = max(self.width(), popup.sizeHint().width())
        ph = popup.sizeHint().height()
        popup.resize(w, ph)
        global_top = self.mapToGlobal(QPoint(0, 0))
        scr = (QApplication.screenAt(global_top) if hasattr(QApplication, 'screenAt') else None) \
              or QApplication.primaryScreen()
        avail = scr.availableGeometry()
        # 세로: 아래 공간 부족하면 위로, 충분하면 아래로
        if global_top.y() + self.height() + ph + 4 > avail.bottom():
            y = global_top.y() - ph - 2
        else:
            y = global_top.y() + self.height() + 2
        # 가로: 콤보 왼쪽 정렬이 기본이나, 팝업이 화면 밖으로 넘치면 안쪽으로 당겨 잘림 방지
        x = global_top.x()
        right_bound = avail.x() + avail.width()
        if x + w > right_bound:
            x = right_bound - w
        if x < avail.x():
            x = avail.x()
        popup.move(x, y)
        # macOS Qt.Popup: mousePressEvent 처리 중 show()하면 같은 클릭의 mouseRelease가
        # 팝업 외부 이벤트로 잡혀 즉시 닫힘. singleShot(0)으로 현재 이벤트 사이클 후 표시.
        self._active_popup = popup   # GC 방지용 레퍼런스 유지
        QTimer.singleShot(0, popup.show)

    def hidePopup(self):
        super().hidePopup()

# ───────────────────────────────────────────
#  Color picker dialog
# ───────────────────────────────────────────
class ColorPickerDialog(QDialog):
    preset_chosen = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Bar Color')
        # WA_TranslucentBackground 제거 — Intel Mac에서 클릭 이벤트를 삼킴
        self.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint)
        # 불투명 배경을 palette로 지정 (DropdownPopup과 동일 방식)
        self.setAutoFillBackground(True)
        pal = self.palette()
        pal.setColor(self.backgroundRole(), QColor(T('panel')))
        self.setPalette(pal)

        lay = QVBoxLayout(self); lay.setContentsMargins(8,8,8,8); lay.setSpacing(6)
        brd = T('border')
        for i, (name, top, bot) in enumerate(BAR_PRESETS):
            btn = QPushButton()
            btn.setFixedSize(180, 32)
            # clicked 대신 mousePressEvent 사용 — macOS Popup이 mouseRelease 전에 닫혀 clicked가 안 오는 문제 우회
            btn.mousePressEvent = lambda e, idx=i: self._pick(idx)
            r0,g0,b0,_ = top
            r1,g1,b1,_ = bot
            selected = (i == _bar_preset_idx)
            border_css = '2px solid #ffffff' if selected else f'1px solid {brd}'
            btn.setStyleSheet(
                f'QPushButton {{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,'
                f'stop:0 rgba({r0},{g0},{b0},220),stop:1 rgba({r1},{g1},{b1},60));'
                f'border:{border_css};'
                f'border-radius:6px;color:white;font-size:11px;font-weight:bold;'
                f'text-align:left;padding-left:8px;}}'
            )
            btn.setText(('✓ ' if selected else '  ') + name)
            lay.addWidget(btn)

    def _pick(self, idx):
        global _bar_preset_idx
        _bar_preset_idx = idx
        self.preset_chosen.emit(idx)
        self.close()

# ───────────────────────────────────────────
#  Transfer Function 상수 & 헬퍼
# ───────────────────────────────────────────
TF_SMOOTH_BPO    = [0, 48, 24, 12, 6, 3, 1]
TF_SMOOTH_LABELS = ['None', '1/48', '1/24', '1/12', '1/6', '1/3', '1/1 Oct']
TF_AVG_SEC       = [0.5, 1, 2, 4, 8, 16]
TF_FFT_SIZES     = [4096, 8192, 16384, 32768]
TF_FFT_LABELS    = ['4K', '8K', '16K', '32K']
TF_PHASE_MODES   = ['Wrapped', 'Unwrapped', 'Group Delay']
TF_IR_MODES      = ['Lin', 'ETC', 'Log']

def _smooth_real(arr, f_src, f_out, half):
    """벡터화된 cumsum 옥타브 스무딩 (실수 배열 전용)."""
    nearest = np.clip(np.searchsorted(f_src, f_out, 'left'), 0, len(arr) - 1)
    lo = np.searchsorted(f_src, f_out / half, 'left')
    hi = np.searchsorted(f_src, f_out * half, 'right')
    cum = np.zeros(len(arr) + 1); cum[1:] = np.cumsum(arr)
    cnt = hi - lo; val = cnt > 0
    out = arr[nearest].copy()
    out[val] = (cum[hi[val]] - cum[lo[val]]) / cnt[val]
    return out

def _tf_smooth(freqs, H_complex, bpo):
    """mag(dB) 실수 스무딩 + phase 복소 페이저 스무딩 (Smaart 방식).
    로그 등간격 f_out으로 먼저 보간 후 양 패스를 f_out 위에서 수행 →
    저주파에서도 bpo에 맞는 일정한 창 폭 보장 (FFT 선형 빈 밀도 영향 없음)."""
    mask = (freqs >= 18) & (freqs <= 22000)
    f = freqs[mask]; H = H_complex[mask]
    if len(f) < 2:
        z = np.zeros(max(len(f), 1))
        return f[:1], z[:1], z[:1], z[:1], z[:1]
    f_min = max(float(f[0]), 20.0); f_max = min(float(f[-1]), 20000.0)
    f_out = np.logspace(np.log10(f_min), np.log10(f_max), 1200)
    mag_raw = 20 * np.log10(np.maximum(np.abs(H), 1e-10))
    # 먼저 로그 등간격 그리드로 보간 (선형 보간) — 이후 두 패스 모두 f_out 위에서 수행
    mag_i = np.interp(f_out, f, mag_raw)
    H_re_i = np.interp(f_out, f, H.real)
    H_im_i = np.interp(f_out, f, H.imag)
    if bpo == 0:
        mag_db = mag_i
        H_re   = H_re_i
        H_im   = H_im_i
    else:
        # 삼각 창 = 직사각형 창 2회 통과 (각 반폭 2^(0.5/bpo)) — Smaart 동등 FWHM
        half2  = 2 ** (0.5 / bpo)
        mag_db = _smooth_real(_smooth_real(mag_i,   f_out, f_out, half2), f_out, f_out, half2)
        H_re   = _smooth_real(_smooth_real(H_re_i,  f_out, f_out, half2), f_out, f_out, half2)
        H_im   = _smooth_real(_smooth_real(H_im_i,  f_out, f_out, half2), f_out, f_out, half2)
    ph_wrap = np.arctan2(H_im, H_re) * (180.0 / np.pi)   # [-180, +180]
    ph_unwr = np.unwrap(np.arctan2(H_im, H_re)) * (180.0 / np.pi)
    # 그룹 딜레이는 항상 최소 1/3 옥타브로 스무딩 후 계산
    # (좁은 창에서 np.gradient가 위상 노이즈로 극단값 출력하는 문제 방지)
    bpo_grp = max(bpo, 3) if bpo > 0 else 3
    half2_grp = 2 ** (0.25 / bpo_grp)
    H_re_g = _smooth_real(_smooth_real(H_re_i, f_out, f_out, half2_grp), f_out, f_out, half2_grp)
    H_im_g = _smooth_real(_smooth_real(H_im_i, f_out, f_out, half2_grp), f_out, f_out, half2_grp)
    ph_rad  = np.unwrap(np.arctan2(H_im_g, H_re_g))
    grp_ms  = -np.gradient(ph_rad, 2 * np.pi * f_out) * 1000.0
    return f_out, mag_db, ph_wrap, ph_unwr, grp_ms

def _gen_log_sweep(n, sr, f_lo=20.0, f_hi=20000.0):
    """20Hz→20kHz 로그 사인 스윕 신호 생성 (루프 재생용)."""
    t = np.arange(n, dtype=np.float64) / sr
    T = n / sr
    k = T / np.log(f_hi / f_lo)
    sig = np.sin(2 * np.pi * f_lo * k * (np.exp(t / k) - 1.0)).astype(np.float32)
    # 시작·끝 페이드(10ms)로 루프 이음새 클릭 제거
    fade = int(sr * 0.01)
    win = np.ones(n, dtype=np.float32)
    win[:fade] = np.linspace(0, 1, fade, dtype=np.float32)
    win[-fade:] = np.linspace(1, 0, fade, dtype=np.float32)
    return sig * win

def _gen_pink_noise(n):
    """Pink noise 블록 생성 (주파수 도메인 방식)."""
    N = max(n, 2)
    fr = np.fft.rfftfreq(N); fr[0] = 1.0
    amp = 1.0 / np.sqrt(fr); amp[0] = 0.0
    phase = np.random.uniform(0, 2 * np.pi, len(fr))
    sig = np.real(np.fft.irfft(amp * np.exp(1j * phase), N))[:n].astype(np.float32)
    rms = float(np.sqrt(np.mean(sig ** 2)))
    return sig / rms if rms > 0 else sig

# ───────────────────────────────────────────
#  TF Phase Canvas
# ───────────────────────────────────────────
class TFPhaseCanvas(QWidget):
    PAD_L=40; PAD_R=15; PAD_T=10; PAD_B=24
    cursor_x_changed = pyqtSignal(int)
    cursor_left      = pyqtSignal()
    _cap_built       = pyqtSignal()
    def __init__(self):
        super().__init__()
        self.setMinimumSize(400,110); self.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Expanding)
        self.setMouseTracking(True); self.setAttribute(Qt.WA_OpaquePaintEvent,True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.freqs=None; self.ph_wrap=None; self.ph_unwr=None; self.grp_ms=None
        self.coherence=None; self.mag=None; self.coh_blank=0.5
        self.phase_mode=0
        self.ph_min=-150.0; self.ph_max=150.0  # Smaart 기본값: -150~150° (중심 0°)
        self._mx=-1; self._peer_mx=-1; self._cache=None
        self._captures=[]
        self._cap_pix=None; self._cap_pix_key=None
        self._front_idx=None; self._live_on_top=False
        self._cap_building = False
        self._cap_img_pending = None; self._cap_key_pending = None
        self._cap_built.connect(self._apply_cap_built)
        self._tf_extra_phase = {}  # {ch_idx: {'color', 'f', 'ph_wrap', 'ph_unwr', 'grp_ms'}}
        # Reference/Delta 비교
        self._ref_f = None; self._ref_pw = None; self._ref_pu = None; self._ref_gm = None
        self._delta = False; self._abs_ph = None
        self._front_extra = None  # None/-1=primary 맨앞, int=해당 pair idx 맨앞

    def set_front_curve(self, key):
        self._front_extra = key; self.update()

    def set_reference(self, f, pw, pu, gm):
        self._ref_f  = np.asarray(f,  dtype=np.float32) if f  is not None else None
        self._ref_pw = np.asarray(pw, dtype=np.float32) if pw is not None else None
        self._ref_pu = np.asarray(pu, dtype=np.float32) if pu is not None else None
        self._ref_gm = np.asarray(gm, dtype=np.float32) if gm is not None else None
        self._cache=None; self._cap_pix=None; self.update()

    def set_delta_mode(self, on):
        on = bool(on)
        if on == self._delta: return
        self._delta = on
        if on:
            self._abs_ph = (self.ph_min, self.ph_max)
            if self.phase_mode == 2: self.ph_min, self.ph_max = -15.0, 15.0
            else:                    self.ph_min, self.ph_max = -180.0, 180.0
        elif self._abs_ph is not None:
            self.ph_min, self.ph_max = self._abs_ph; self._abs_ph = None
        self._cache=None; self._cap_pix=None; self.update()

    def set_tf_extra_phase(self, ch_idx, color, f, ph_wrap, ph_unwr, grp_ms):
        self._tf_extra_phase[ch_idx] = {'color': color, 'f': f,
                                         'ph_wrap': ph_wrap, 'ph_unwr': ph_unwr, 'grp_ms': grp_ms}
        self.update()

    def clear_tf_extra_phase(self, ch_idx):
        self._tf_extra_phase.pop(ch_idx, None); self.update()

    def clear_all_tf_extra_phase(self):
        self._tf_extra_phase.clear(); self.update()

    def _apply_cap_built(self):
        img, key = self._cap_img_pending, self._cap_key_pending
        self._cap_img_pending = self._cap_key_pending = None
        if img is not None:
            self._cap_pix = QPixmap.fromImage(img)
            self._cap_pix_key = key
            self.update()

    def _trigger_cap_build(self, W, H, cap_key):
        if self._cap_building: return
        self._cap_building = True
        caps = [dict(c) for c in self._captures]
        front = self._front_idx
        threading.Thread(target=self._bg_cap_build,
                         args=(W, H, cap_key, caps, front),
                         daemon=True).start()

    def _bg_cap_build(self, W, H, cap_key, caps, front):
        try:
            img = self._build_cap_img(W, H, caps, front)
            self._cap_img_pending = img
            self._cap_key_pending = cap_key
            self._cap_built.emit()
        except Exception:
            pass
        finally:
            self._cap_building = False

    def _build_cap_img(self, W, H, caps, front):
        from PyQt5.QtGui import QImage
        pl=self.PAD_L; pr=self.PAD_R; pt=self.PAD_T; pb=self.PAD_B
        dh=H-pt-pb; uw=W-pl-pr; ny=20000
        rng=self.ph_max-self.ph_min if self.ph_max!=self.ph_min else 1.0
        img=QImage(W,H,QImage.Format_ARGB32_Premultiplied); img.fill(0)
        p=QPainter(img); p.setRenderHint(QPainter.Antialiasing,True)
        max_pts=max(int(uw),200)  # 픽셀 1:1
        def _draw_one(cap, emph=False):
            # E 포커스: 선택(front)=밝고 굵게, 비선택=흐리고 얇게
            data=[cap['ph_wrap'],cap['ph_unwr'],cap['grp_ms']][self.phase_mode]
            if data is None: return
            freqs=cap['f']
            xs=pl+(np.log10(np.maximum(freqs,1)/20)/math.log10(ny/20))*uw
            if self.phase_mode==0:
                mid=(self.ph_min+self.ph_max)/2
                data_plot=data-360.0*np.round((data-mid)/360.0)
            else:
                data_plot=data
            ys=pt+np.clip(((self.ph_max-data_plot)/rng*dh).astype(float),0,dh)
            if len(xs)>max_pts:
                _ids=np.linspace(0,len(xs)-1,max_pts,dtype=int)
                xs=xs[_ids]; ys=ys[_ids]; data_plot=data_plot[_ids]
            is_wrap=(self.phase_mode==0)
            path=QPainterPath(); seg_x=[]; seg_y=[]
            def _flush():
                if len(seg_x)>=2: path.addPath(_catmull_seg(seg_x,seg_y))
                seg_x.clear(); seg_y.clear()
            for i in range(len(xs)):
                brk=(i>0 and is_wrap and abs(data_plot[i]-data_plot[i-1])>270.0)
                if brk:
                    _flush()
                else:
                    seg_x.append(float(xs[i])); seg_y.append(float(ys[i]))
            _flush()
            qc=QColor(cap['color'])
            if emph:
                p.setPen(QPen(qc,3.0))
            else:
                qc.setAlpha(140); p.setPen(QPen(qc,1.4))
            p.setBrush(Qt.NoBrush); p.drawPath(path)
        for i,cap in enumerate(caps):
            if i==front: continue
            if not cap.get('visible', True): continue
            _draw_one(cap, emph=False)
        if front is not None and 0<=front<len(caps):
            if caps[front].get('visible', True):
                _draw_one(caps[front], emph=True)
        p.end()
        return img

    def _build_cap_pix(self, W, H):
        img = self._build_cap_img(W, H, list(self._captures), self._front_idx)
        self._cap_pix = QPixmap.fromImage(img)
        self._cap_pix_key = (W, H, self.ph_max, self.ph_min, self.phase_mode, self.coh_blank, self._front_idx, self._live_on_top)

    def add_capture(self, label, color):
        if self.freqs is None: return
        self._captures.append({
            'f': self.freqs.copy(),
            'ph_wrap': self.ph_wrap.copy() if self.ph_wrap is not None else None,
            'ph_unwr': self.ph_unwr.copy() if self.ph_unwr is not None else None,
            'grp_ms':  self.grp_ms.copy()  if self.grp_ms  is not None else None,
            'coh':     self.coherence.copy() if self.coherence is not None else None,
            'color': color, 'label': label
        })
        self._cap_pix=None; self._last_cap_t=time.monotonic(); self.update()

    def add_capture_data(self, label, color, f, ph_wrap, ph_unwr, grp_ms, coh=None):
        """외부 데이터(extra 카드 등)로 직접 위상 캡쳐 추가."""
        if f is None: return
        self._captures.append({
            'f': np.asarray(f, dtype=np.float32).copy(),
            'ph_wrap': np.asarray(ph_wrap, dtype=np.float32).copy() if ph_wrap is not None else None,
            'ph_unwr': np.asarray(ph_unwr, dtype=np.float32).copy() if ph_unwr is not None else None,
            'grp_ms':  np.asarray(grp_ms,  dtype=np.float32).copy() if grp_ms  is not None else None,
            'coh':     np.asarray(coh,     dtype=np.float32).copy() if coh     is not None else None,
            'color': color, 'label': label
        })
        self._cap_pix=None; self._last_cap_t=time.monotonic(); self.update()

    def remove_capture(self, idx):
        if 0 <= idx < len(self._captures):
            self._captures.pop(idx)
            if self._front_idx is not None:
                if self._front_idx==idx: self._front_idx=None
                elif self._front_idx>idx: self._front_idx-=1
            self._cap_pix=None; self._last_cap_t=time.monotonic(); self.update()

    def bring_to_front(self, idx):
        if 0 <= idx < len(self._captures):
            self._front_idx=idx; self._live_on_top=False
            self._cap_pix=None; self.update()

    def set_data(self,f,pw,pu,gm,coh=None,mag=None):
        self.freqs=f; self.ph_wrap=pw; self.ph_unwr=pu; self.grp_ms=gm
        self.coherence=coh; self.mag=mag
        self.update()  # 배경 캐시 유지 — 커브만 갱신

    def clear(self):
        self.freqs=self.ph_wrap=self.ph_unwr=self.grp_ms=None
        self.mag=None; self._cache=None; self.update()

    def set_mode(self,idx):
        self.phase_mode=idx
        if idx==0:   self.ph_min,self.ph_max=-150.0,150.0   # Smaart 기본: -150~150° (중심 0°)
        elif idx==1: self.ph_min,self.ph_max=-540.0,540.0
        else:        self.ph_min,self.ph_max=-2.0,30.0
        self._cache=None; self._cap_pix=None; self.update()

    def mouseMoveEvent(self,e):
        x=e.x()
        if x!=self._mx:
            self._mx=x; self._peer_mx=-1; self.update()
            self._pending_x=x
            if not getattr(self,'_cursor_timer_active',False):
                self._cursor_timer_active=True
                QTimer.singleShot(16,self._emit_cursor)
    def _emit_cursor(self):
        self._cursor_timer_active=False
        self.cursor_x_changed.emit(self._pending_x)
    def leaveEvent(self,e):
        self._mx=-1; self.update(); self.cursor_left.emit()
    def set_peer_cursor(self,x):
        if x!=self._peer_mx: self._peer_mx=x; self.update()
    def clear_peer_cursor(self):
        if self._peer_mx!=-1: self._peer_mx=-1; self.update()
    def resizeEvent(self,e): self._cache=None; self.update()

    def mouseDoubleClickEvent(self,e):
        if self.phase_mode==0:   self.ph_min,self.ph_max=-150.0,150.0
        elif self.phase_mode==1: self.ph_min,self.ph_max=-540.0,540.0
        else:                    self.ph_min,self.ph_max=-2.0,30.0
        self._cache=None; self.update()

    def wheelEvent(self, e): e.ignore()

    def enterEvent(self, e): self.setFocus(); super().enterEvent(e)
    def mousePressEvent(self, e): self.setFocus(); super().mousePressEvent(e)

    def keyPressEvent(self, e):
        key = e.key()
        if key in (Qt.Key_Up, Qt.Key_Down):
            step = 1 if key == Qt.Key_Up else -1
            if self.phase_mode == 0:
                span = self.ph_max - self.ph_min
                mid = (self.ph_min + self.ph_max) / 2 + step * 30.0
                mid = ((mid + 180.0) % 360.0) - 180.0
                self.ph_min = mid - span / 2; self.ph_max = mid + span / 2
            else:
                d = (self.ph_max - self.ph_min) * 0.05 * step
                self.ph_min += d; self.ph_max += d
                if self.phase_mode == 1:
                    span = self.ph_max - self.ph_min
                    self.ph_min = max(-3600.0, min(self.ph_min, 3600.0 - span))
                    self.ph_max = self.ph_min + span
            self._cache = None; self.update()
        else:
            super().keyPressEvent(e)

    def _build_cache(self,W,H):
        from PyQt5.QtGui import QPixmap
        dpr=self.devicePixelRatio()
        px=QPixmap(int(W*dpr),int(H*dpr)); px.setDevicePixelRatio(dpr); px.fill(QColor(T('bg')))
        p=QPainter(px)
        p.setRenderHint(QPainter.Antialiasing, True); p.setRenderHint(QPainter.TextAntialiasing)
        pl=self.PAD_L; pr=self.PAD_R; pt=self.PAD_T; pb=self.PAD_B
        dh=H-pt-pb; uw=W-pl-pr; ny=20000
        rng=self.ph_max-self.ph_min if self.ph_max!=self.ph_min else 1.0
        is_grp=(self.phase_mode==2); unit=' ms' if is_grp else '°'
        p.setFont(_qfont(CF_AXIS))
        if is_grp:
            gs=[v for v in [-2,0,2,5,10,15,20,25,30] if self.ph_min<=v<=self.ph_max]
        else:
            rng_deg=self.ph_max-self.ph_min
            if   rng_deg<=360:   step_deg=30
            elif rng_deg<=720:   step_deg=60
            elif rng_deg<=1440:  step_deg=90
            elif rng_deg<=2880:  step_deg=180
            else:                step_deg=360
            start=int(math.ceil(self.ph_min/step_deg))*step_deg
            gs=[v for v in range(start,int(self.ph_max)+step_deg,step_deg) if self.ph_min<=v<=self.ph_max]
        for deg in gs:
            y=int(pt+(self.ph_max-deg)/rng*dh)
            is0=(deg==0)
            p.setPen(QPen(QColor(T('grid_ref')),1.5 if is0 else 0.7,Qt.SolidLine))
            p.drawLine(pl,y,W-pr,y)
            p.setPen(QColor(T('graph_txt')))
            lbl=f'{deg}{unit}' if is_grp else f'{int(deg)}°'
            p.drawText(0,y-8,pl-2,16,Qt.AlignRight|Qt.AlignVCenter,lbl)
        p.setFont(_qfont(CF_AXIS, True)); last_lx=-999
        draw_freq_minor_grid(p, pl, pr, uw, pt, pb, W, H, ny)
        for f in FREQ_MARKS:
            if f<20 or f>ny: continue
            fx=freq_to_x(f,pl,uw,ny)
            if not pl<=fx<=W-pr: continue
            p.setPen(QPen(QColor(T('grid')),1)); p.drawLine(int(fx),pt,int(fx),H-pb)
            if fx-last_lx<40: continue
            last_lx=fx
            txt=f'{int(f//1000)}k' if f>=1000 else str(int(f))
            tw=p.fontMetrics().horizontalAdvance(txt)
            p.setPen(QColor(T('graph_txt'))); p.drawText(max(pl,min(int(fx-tw/2),W-pr-tw)),H-pb+16,txt)
        mode_lbl=['Phase  Wrapped','Phase  Unwrapped','Group Delay'][self.phase_mode]
        p.setFont(_qfont(CF_MODE, True)); p.setPen(QColor(T('graph_txt')))
        p.drawText(pl+4,pt+15,mode_lbl)
        p.end(); self._cache=px

    def _draw_grid_lines(self, p, W, H):
        pl=self.PAD_L; pr=self.PAD_R; pt=self.PAD_T; pb=self.PAD_B
        dh=H-pt-pb; uw=W-pl-pr; ny=20000
        rng=self.ph_max-self.ph_min if self.ph_max!=self.ph_min else 1.0
        is_grp=(self.phase_mode==2)
        if is_grp:
            gs=[v for v in [-2,0,2,5,10,15,20,25,30] if self.ph_min<=v<=self.ph_max]
        else:
            rng_deg=self.ph_max-self.ph_min
            if   rng_deg<=360:   step_deg=30
            elif rng_deg<=720:   step_deg=60
            elif rng_deg<=1440:  step_deg=90
            elif rng_deg<=2880:  step_deg=180
            else:                step_deg=360
            start=int(math.ceil(self.ph_min/step_deg))*step_deg
            gs=[v for v in range(start,int(self.ph_max)+step_deg,step_deg) if self.ph_min<=v<=self.ph_max]
        for deg in gs:
            y=int(pt+(self.ph_max-deg)/rng*dh)
            is0=(deg==0)
            p.setPen(QPen(QColor(T('grid_ref')),1.5 if is0 else 0.7,Qt.SolidLine))
            p.drawLine(pl,y,W-pr,y)
        draw_freq_minor_grid(p, pl, pr, uw, pt, pb, W, H, ny)
        for f in FREQ_MARKS:
            if f<20 or f>ny: continue
            fx=freq_to_x(f,pl,uw,ny)
            if not pl<=fx<=W-pr: continue
            p.setPen(QPen(QColor(T('grid')),1)); p.drawLine(int(fx),pt,int(fx),H-pb)

    def _draw_curve(self, p, W, H):
        refmode = self._delta and self._ref_f is not None
        delta_no_ref = self._delta and not refmode  # 델타 모드인데 기준 없음 → 전부 숨김
        if delta_no_ref:
            return
        p.setRenderHint(QPainter.Antialiasing, True)
        # E 포커스: 포커스된 하나만 밝게, 나머지 라이브 곡선은 흐리게(alpha 140)
        _capf = (self._front_idx is not None)
        _fk2 = self._front_extra
        def _is_focus(key):
            if _capf: return False
            if key is None or key == -1: return (_fk2 is None or _fk2 == -1)
            return _fk2 == key
        def _col(c, key):
            qc = QColor(c)
            if not _is_focus(key): qc.setAlpha(140)
            return qc
        # ── primary 곡선 (데이터 있을 때만; 없으면 extra만 그림 — primary 숨김 시 카드2 위상 유지) ──
        path = None
        data = None if self.freqs is None else [self.ph_wrap,self.ph_unwr,self.grp_ms][self.phase_mode]
        if data is not None:
            if refmode:
                ref_data=[self._ref_pw,self._ref_pu,self._ref_gm][self.phase_mode]
                if ref_data is None:
                    data = None
                else:
                    data = data - np.interp(self.freqs, self._ref_f, ref_data)
        if data is not None:
            pl=self.PAD_L; pr=self.PAD_R; pt=self.PAD_T; pb=self.PAD_B
            dh=H-pt-pb; uw=W-pl-pr; ny=20000
            rng=self.ph_max-self.ph_min if self.ph_max!=self.ph_min else 1.0
            xs=pl+(np.log10(np.maximum(self.freqs,1)/20)/math.log10(ny/20))*uw
            if self.phase_mode==0:
                mid=(self.ph_min+self.ph_max)/2
                data_plot=data-360.0*np.round((data-mid)/360.0)
            else:
                data_plot=data
            ys=pt+np.clip(((self.ph_max-data_plot)/rng*dh).astype(float),0,dh)
            # 화면 너비에 맞춰 다운샘플: Python 루프 반복 수 축소 → GIL 점유 시간 감소
            max_pts=max(int(uw),200)
            if len(xs)>max_pts:
                _ids=np.linspace(0,len(xs)-1,max_pts,dtype=int)
                xs=xs[_ids]; ys=ys[_ids]; data_plot=data_plot[_ids]
            is_wrap=(self.phase_mode==0)
            # Catmull-Rom 스플라인: 연속 구간별로 부드러운 곡선 생성
            path=QPainterPath(); seg_x=[]; seg_y=[]
            def _flush():
                if len(seg_x) >= 2:
                    path.addPath(_catmull_seg(seg_x, seg_y))
                seg_x.clear(); seg_y.clear()
            for i in range(len(xs)):
                break_here=(i>0 and is_wrap and abs(data_plot[i]-data_plot[i-1])>270.0)
                if break_here:
                    _flush()
                else:
                    seg_x.append(float(xs[i])); seg_y.append(float(ys[i]))
            _flush()
            p.setPen(QPen(_col('#33FF66', None),2.0)); p.setBrush(Qt.NoBrush); p.drawPath(path)
        # ── 추가 채널 곡선 (primary 유무와 무관하게 그림; front 는 마지막에 굵게) ──
        fk=self._front_extra
        for key, ex in self._tf_extra_phase.items():
            if key==fk: continue
            self._draw_extra_phase_curve(p, W, H, ex, dim=not _is_focus(key))
        # front(포커스) 맨 앞 굵게 재드로우 — 캡쳐 포커스 시엔 생략
        if self._tf_extra_phase and not _capf:
            if fk is None or fk==-1:
                if path is not None:
                    p.setPen(QPen(QColor('#33FF66'),3.4)); p.setBrush(Qt.NoBrush); p.drawPath(path)
            elif fk in self._tf_extra_phase:
                self._draw_extra_phase_curve(p, W, H, self._tf_extra_phase[fk], width=3.4)

    def _draw_extra_phase_curve(self, p, W, H, ex, width=1.8, dim=False):
        f_arr = ex.get('f'); data_arr = [ex.get('ph_wrap'), ex.get('ph_unwr'), ex.get('grp_ms')][self.phase_mode]
        if f_arr is None or data_arr is None: return
        refmode = self._delta and self._ref_f is not None
        if self._delta and not refmode: return
        if refmode:
            ref_data=[self._ref_pw,self._ref_pu,self._ref_gm][self.phase_mode]
            if ref_data is None: return
            data_arr = data_arr - np.interp(f_arr, self._ref_f, ref_data)
        pl=self.PAD_L; pr=self.PAD_R; pt=self.PAD_T; pb=self.PAD_B
        dh=H-pt-pb; uw=W-pl-pr; ny=20000
        rng=self.ph_max-self.ph_min if self.ph_max!=self.ph_min else 1.0
        xs=pl+(np.log10(np.maximum(f_arr,1)/20)/math.log10(ny/20))*uw
        if self.phase_mode==0:
            mid=(self.ph_min+self.ph_max)/2
            data_plot=data_arr-360.0*np.round((data_arr-mid)/360.0)
        else:
            data_plot=data_arr
        ys=pt+np.clip(((self.ph_max-data_plot)/rng*dh).astype(float),0,dh)
        max_pts=max(int(uw),200)
        if len(xs)>max_pts:
            _ids=np.linspace(0,len(xs)-1,max_pts,dtype=int)
            xs=xs[_ids]; ys=ys[_ids]; data_plot=data_plot[_ids]
        is_wrap=(self.phase_mode==0)
        path=QPainterPath(); seg_x=[]; seg_y=[]
        def _flush2():
            if len(seg_x)>=2: path.addPath(_catmull_seg(seg_x,seg_y))
            seg_x.clear(); seg_y.clear()
        for i in range(len(xs)):
            brk=(i>0 and is_wrap and abs(data_plot[i]-data_plot[i-1])>270.0)
            if brk:
                _flush2()
            else:
                seg_x.append(float(xs[i])); seg_y.append(float(ys[i]))
        _flush2()
        p.setRenderHint(QPainter.Antialiasing, True)
        _qc=QColor(ex['color'])
        if dim: _qc.setAlpha(140)
        p.setPen(QPen(_qc,width)); p.setBrush(Qt.NoBrush); p.drawPath(path)

    def paintEvent(self,ev):
        W=self.width(); H=self.height()
        if self._cache is None or self._cache.size()!=self.size():
            self._build_cache(W,H)
        p=QPainter(self); p.drawPixmap(0,0,self._cache)

        # E 포커스: 캡쳐 선택 시 라이브(흐림) 먼저 → 포커스 캡쳐(밝음) 위. 라이브 포커스 시 반대.
        _cap_focus = (self._front_idx is not None)
        def _draw_caps():
            if not (self._captures and not self._delta): return  # 델타 모드 절대값 캡쳐 숨김
            _cap_key=(W,H,self.ph_max,self.ph_min,self.phase_mode,self.coh_blank,self._front_idx,self._live_on_top)
            if self._cap_pix is None or self._cap_pix_key!=_cap_key:
                self._trigger_cap_build(W, H, _cap_key)
            if self._cap_pix is not None:
                p.drawPixmap(0,0,self._cap_pix)
        if _cap_focus:
            self._draw_curve(p,W,H); _draw_caps()
        else:
            _draw_caps(); self._draw_curve(p,W,H)

        self._draw_grid_lines(p, W, H)

        pl=self.PAD_L; pr=self.PAD_R; pt=self.PAD_T; pb=self.PAD_B; uw=W-pl-pr; ny=20000
        dh=H-pt-pb; rng=max(self.ph_max-self.ph_min,1.0)
        _CUR  = QColor(255,220,50,210)   # 밝은 황색
        _PEER = QColor(255,220,50,100)
        # 피어 커서: 수직선 + 수평선 (자기 데이터로 y 계산)
        if pl<=self._peer_mx<=W-pr:
            p.setPen(QPen(_PEER,1,Qt.DashLine))
            p.drawLine(self._peer_mx,pt,self._peer_mx,H-pb)
            if self.freqs is not None:
                data=[self.ph_wrap,self.ph_unwr,self.grp_ms][self.phase_mode]
                if data is not None:
                    pfreq=x_to_freq(self._peer_mx,pl,uw,ny)
                    _pi=np.searchsorted(self.freqs,pfreq)
                    if _pi>0 and (_pi>=len(self.freqs) or self.freqs[_pi]-pfreq>pfreq-self.freqs[_pi-1]): _pi-=1
                    pidx=int(np.clip(_pi,0,len(data)-1))
                    if self.phase_mode==0:
                        mid=(self.ph_min+self.ph_max)/2
                        pval=float(data[pidx])-360.0*round((float(data[pidx])-mid)/360.0)
                    else:
                        pval=float(data[pidx])
                    pcy=int(pt+np.clip((self.ph_max-pval)/rng*dh,0,dh))
                    p.drawLine(pl,pcy,W-pr,pcy)
        # 자체 커서: 십자 + info box — 선택(front) 카드 우선 → primary → 아무 extra
        _fk = self._front_extra
        if isinstance(_fk, int) and _fk != -1 and _fk in self._tf_extra_phase:
            _ex = self._tf_extra_phase[_fk]
            _cf = _ex.get('f')
            data = [_ex.get('ph_wrap'), _ex.get('ph_unwr'), _ex.get('grp_ms')][self.phase_mode]
            _cmag = None
        else:
            _cf = self.freqs
            data = None if self.freqs is None else [self.ph_wrap,self.ph_unwr,self.grp_ms][self.phase_mode]
            _cmag = self.mag
            if (_cf is None or data is None) and self._tf_extra_phase:
                _ex = next(iter(self._tf_extra_phase.values()))
                _cf = _ex.get('f')
                data = [_ex.get('ph_wrap'), _ex.get('ph_unwr'), _ex.get('grp_ms')][self.phase_mode]
                _cmag = None
        if pl<=self._mx<=W-pr and _cf is not None:
            if data is not None:
                is_grp=(self.phase_mode==2)
                cx=self._mx
                freq=x_to_freq(cx,pl,uw,ny)
                _oi=np.searchsorted(_cf,freq)
                if _oi>0 and (_oi>=len(_cf) or _cf[_oi]-freq>freq-_cf[_oi-1]): _oi-=1
                idx=int(np.clip(_oi,0,len(data)-1))
                # 수평선 y: 실제 데이터값 위치
                if is_grp:
                    val_plot=float(data[idx])
                elif self.phase_mode==0:
                    mid=(self.ph_min+self.ph_max)/2
                    val_plot=float(data[idx])-360.0*round((float(data[idx])-mid)/360.0)
                else:
                    val_plot=float(data[idx])
                cy=int(pt+np.clip((self.ph_max-val_plot)/rng*dh,0,dh))
                p.setPen(QPen(_CUR,1,Qt.DashLine))
                p.drawLine(cx,pt,cx,H-pb)          # 수직선
                p.drawLine(pl,cy,W-pr,cy)           # 수평선
                fs=f'{freq/1000:.2f}kHz' if freq>=1000 else f'{freq:.0f}Hz'
                mag_str=''
                if _cmag is not None and len(_cmag)==len(_cf):
                    mag_str=f'{_cmag[idx]:+.1f} dB'
                if is_grp:
                    ph_str=f'  {data[idx]:.2f} ms'
                elif self.phase_mode==0:
                    ph_str=f'  {int(val_plot)}°'
                else:
                    ph_str=f'  {val_plot:+.1f}°'
                draw_info_box(p,W,fs,f'{mag_str}{ph_str}')
        p.end()

# ───────────────────────────────────────────
#  TF Magnitude + Coherence Canvas
# ───────────────────────────────────────────
class TFMagCanvas(QWidget):
    PAD_L=40; PAD_R=15; PAD_T=10; PAD_B=28
    _COH_COLOR=(255,107,53)
    _COH_BAND=0.5   # γ² 트레이스가 차지하는 플롯 높이 비율 (위=1.0, 아래=0) — Smaart식 디테일
    cursor_x_changed = pyqtSignal(int)
    cursor_left      = pyqtSignal()
    _cap_built       = pyqtSignal()
    def __init__(self):
        super().__init__()
        self.setMinimumSize(400,110); self.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Expanding)
        self.setMouseTracking(True); self.setAttribute(Qt.WA_OpaquePaintEvent,True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.freqs=None; self.mag=None; self.coh=None; self.phase=None
        self.db_min=-15.0; self.db_max=15.0
        self.coh_blank=0.5
        self._mx=-1; self._peer_mx=-1; self._cache=None
        self._captures=[]
        self._cap_pix=None; self._cap_pix_key=None
        self._front_idx=None; self._live_on_top=False
        self._cap_building = False
        self._cap_img_pending = None; self._cap_key_pending = None
        self._cap_built.connect(self._apply_cap_built)
        self._tf_extra = {}  # {ch_idx: {'color', 'f', 'mag'}}
        # Reference/Delta 비교
        self._ref_f = None; self._ref_mag = None
        self._delta = False; self._abs_db = None
        self.DELTA_RANGE = 18.0
        self._front_extra = None  # None/-1=primary 맨앞, int=해당 pair idx 맨앞

    def set_front_curve(self, key):
        self._front_extra = key; self.update()

    def _draw_mag_line(self, p, W, H, f, mag, color, width):
        """단일 Mag 곡선(최종 dB값) 그리기 — front 강조 재드로우용."""
        if f is None or mag is None or len(f) < 2: return
        pl=self.PAD_L; pr=self.PAD_R; pt=self.PAD_T; pb=self.PAD_B
        dh=H-pt-pb; uw=W-pl-pr; ny=20000
        rng=self.db_max-self.db_min if self.db_max!=self.db_min else 1.0
        xs=(pl+(np.log10(np.maximum(f,1)/20)/math.log10(ny/20))*uw).astype(float)
        ys=(pt+np.clip((self.db_max-mag)/rng*dh,0,dh)).astype(float)
        if len(ys)>=7:
            ys=np.convolve(np.pad(ys,3,mode='edge'),np.ones(7)/7,mode='valid').astype(float)
        _mp=max(int(uw),200)
        if len(xs)>_mp:
            ids=np.linspace(0,len(xs)-1,_mp,dtype=int); xs=xs[ids]; ys=ys[ids]
        p.setRenderHint(QPainter.Antialiasing,True)
        p.setPen(QPen(QColor(color),width)); p.setBrush(Qt.NoBrush)
        p.drawPath(_catmull_seg(xs, ys))

    def set_reference(self, f, mag):
        self._ref_f  = np.asarray(f, dtype=np.float32)   if f   is not None else None
        self._ref_mag = np.asarray(mag, dtype=np.float32) if mag is not None else None
        self._cache=None; self._cap_pix=None; self.update()

    def set_delta_mode(self, on):
        on = bool(on)
        if on == self._delta: return
        self._delta = on
        if on:
            self._abs_db = (self.db_min, self.db_max)
            self.db_min = -self.DELTA_RANGE; self.db_max = self.DELTA_RANGE
        elif self._abs_db is not None:
            self.db_min, self.db_max = self._abs_db; self._abs_db = None
        self._cache=None; self._cap_pix=None; self.update()

    def set_tf_extra(self, ch_idx, color, f, mag):
        self._tf_extra[ch_idx] = {'color': color, 'f': f, 'mag': mag}
        self.update()

    def clear_tf_extra(self, ch_idx):
        self._tf_extra.pop(ch_idx, None); self.update()

    def clear_all_tf_extra(self):
        self._tf_extra.clear(); self.update()

    def _apply_cap_built(self):
        img, key = self._cap_img_pending, self._cap_key_pending
        self._cap_img_pending = self._cap_key_pending = None
        if img is not None:
            self._cap_pix = QPixmap.fromImage(img)
            self._cap_pix_key = key
            self.update()

    def _trigger_cap_build(self, W, H, cap_key):
        if self._cap_building: return
        self._cap_building = True
        caps = [dict(c) for c in self._captures]
        front = self._front_idx
        threading.Thread(target=self._bg_cap_build,
                         args=(W, H, cap_key, caps, front),
                         daemon=True).start()

    def _bg_cap_build(self, W, H, cap_key, caps, front):
        try:
            img = self._build_cap_img(W, H, caps, front)
            self._cap_img_pending = img
            self._cap_key_pending = cap_key
            self._cap_built.emit()
        except Exception:
            pass
        finally:
            self._cap_building = False

    def _build_cap_img(self, W, H, caps, front):
        from PyQt5.QtGui import QImage
        pl=self.PAD_L; pr=self.PAD_R; pt=self.PAD_T; pb=self.PAD_B
        dh=H-pt-pb; uw=W-pl-pr; ny=20000
        rng=max(self.db_max-self.db_min,1.0)
        img=QImage(W,H,QImage.Format_ARGB32_Premultiplied); img.fill(0)
        p=QPainter(img); p.setRenderHint(QPainter.Antialiasing,True)
        def _vs(arr,k=7):
            if len(arr)<k: return arr
            return np.convolve(np.pad(arr,k//2,mode='edge'),np.ones(k)/k,mode='valid').astype(float)
        max_pts=max(int(uw),200)  # 픽셀 1:1 — Python 루프 최소화
        def _draw_one(cap, emph=False):
            # E 포커스: 선택(front)=밝고 굵게, 비선택=흐리고 얇게
            f_arr=cap['f']; m_arr=cap['mag']
            xs=(pl+(np.log10(np.maximum(f_arr,1)/20)/math.log10(ny/20))*uw).astype(float)
            ys=(pt+np.clip((self.db_max-m_arr)/rng*dh,0,dh)).astype(float)
            ys_s=_vs(ys,7)
            if len(xs)>max_pts:
                _ids=np.linspace(0,len(xs)-1,max_pts,dtype=int)
                xs=xs[_ids]; ys_s=ys_s[_ids]
            poly=QPolygonF([QPointF(x,y) for x,y in zip(xs.tolist(),ys_s.tolist())])
            qc=QColor(cap['color'])
            if emph:
                p.setPen(QPen(qc,3.0))
            else:
                qc.setAlpha(140); p.setPen(QPen(qc,1.4))
            p.setBrush(Qt.NoBrush)
            p.drawPolyline(poly)
        for i,cap in enumerate(caps):
            if i==front: continue
            if not cap.get('visible', True): continue
            _draw_one(cap, emph=False)
        if front is not None and 0<=front<len(caps):
            if caps[front].get('visible', True):
                _draw_one(caps[front], emph=True)
        p.end()
        return img

    def _build_cap_pix(self, W, H):
        img = self._build_cap_img(W, H, list(self._captures), self._front_idx)
        self._cap_pix = QPixmap.fromImage(img)
        self._cap_pix_key = (W, H, self.db_max, self.db_min, self._front_idx, self._live_on_top)

    def add_capture(self, label, color):
        if self.freqs is None or self.mag is None: return
        self._captures.append({
            'f': self.freqs.copy(), 'mag': self.mag.copy(),
            'coh': self.coh.copy() if self.coh is not None else None,
            'color': color, 'label': label
        })
        self._cap_pix=None; self._last_cap_t=time.monotonic(); self.update()

    def add_capture_data(self, label, color, f, mag, coh=None):
        """외부 데이터(extra 카드 등)로 직접 캡쳐 추가."""
        if f is None or mag is None: return
        self._captures.append({
            'f': np.asarray(f, dtype=np.float32).copy(),
            'mag': np.asarray(mag, dtype=np.float32).copy(),
            'coh': np.asarray(coh, dtype=np.float32).copy() if coh is not None else None,
            'color': color, 'label': label
        })
        self._cap_pix=None; self._last_cap_t=time.monotonic(); self.update()

    def remove_capture(self, idx):
        if 0 <= idx < len(self._captures):
            self._captures.pop(idx)
            if self._front_idx is not None:
                if self._front_idx==idx: self._front_idx=None
                elif self._front_idx>idx: self._front_idx-=1
            self._cap_pix=None; self._last_cap_t=time.monotonic(); self.update()

    def bring_to_front(self, idx):
        if 0 <= idx < len(self._captures):
            self._front_idx=idx; self._live_on_top=False
            self._cap_pix=None; self.update()

    def set_data(self,f,m,coh=None,phase=None):
        self.freqs=f; self.mag=m; self.coh=coh; self.phase=phase; self.update()

    def clear(self): self.freqs=self.mag=self.coh=self.phase=None; self._cache=None; self.update()
    def mouseMoveEvent(self,e):
        x=e.x()
        if x!=self._mx:
            self._mx=x; self._peer_mx=-1; self.update()
            self._pending_x=x
            if not getattr(self,'_cursor_timer_active',False):
                self._cursor_timer_active=True
                QTimer.singleShot(16,self._emit_cursor)
    def _emit_cursor(self):
        self._cursor_timer_active=False
        self.cursor_x_changed.emit(self._pending_x)
    def leaveEvent(self,e):
        self._mx=-1; self.update(); self.cursor_left.emit()
    def set_peer_cursor(self,x):
        if x!=self._peer_mx: self._peer_mx=x; self.update()
    def clear_peer_cursor(self):
        if self._peer_mx!=-1: self._peer_mx=-1; self.update()
    def resizeEvent(self,e): self._cache=None; self.update()

    def fit_y(self):
        all_vals = []
        if self.mag is not None and len(self.mag) > 0:
            m = np.asarray(self.mag, dtype=float)
            if self._delta and self._ref_f is not None and self._ref_mag is not None:
                m = m - np.interp(self.freqs, self._ref_f, self._ref_mag)  # 델타 값에 맞춤
            if self.coh is not None and len(self.coh) == len(m):
                mask = np.asarray(self.coh, dtype=float) >= max(self.coh_blank, 0.3)
                m = m[mask] if np.any(mask) else m
            m = m[np.isfinite(m)]
            if len(m): all_vals.append(m)
        # extra 카드 곡선들도 포함 — 카드2만 분석 중이어도 더블클릭 Y맞춤 동작
        for ex in self._tf_extra.values():
            em = ex.get('mag')
            if em is None: continue
            em = np.asarray(em, dtype=float); em = em[np.isfinite(em)]
            if len(em): all_vals.append(em)
        if not all_vals: return
        combined = np.concatenate(all_vals)
        # 5/95 백분위 — 저코히어런스 노이즈(깊은 딥/날카로운 피크) 극단값 제외하되
        # 실제 롤오프는 보존. (2/98은 노이즈 outlier까지 잡아 -48~+27 같은 과도범위 발생)
        lo = float(np.percentile(combined, 5)); hi = float(np.percentile(combined, 95))
        pad = max((hi - lo) * 0.12, 3.0)
        # 합리적 한계로 클램프 — 비정상 데이터로 인한 극단 범위 방지
        self.db_min = max(int(np.floor((lo - pad) / 3)) * 3, -36)
        self.db_max = min(int(np.ceil((hi + pad) / 3)) * 3, 24)
        self._cache=None; self.update()

    def mouseDoubleClickEvent(self,e):
        self.fit_y()

    def enterEvent(self,e): self.setFocus(); super().enterEvent(e)
    def mousePressEvent(self,e):
        self.setFocus(); super().mousePressEvent(e)

    def keyPressEvent(self,e):
        key=e.key()
        if key in (Qt.Key_Up, Qt.Key_Down):
            step=6.0 if key==Qt.Key_Up else -6.0
            db_span=self.db_max-self.db_min
            new_max=min(90.0, max(-90.0+db_span, self.db_max+step))
            new_min=new_max-db_span
            if new_min>=-90.0:
                self.db_max=new_max; self.db_min=new_min
                self._cache=None; self.update()
        else:
            super().keyPressEvent(e)

    def wheelEvent(self, e): e.ignore()

    def _build_cache(self,W,H):
        from PyQt5.QtGui import QPixmap
        dpr=self.devicePixelRatio()
        px=QPixmap(int(W*dpr),int(H*dpr)); px.setDevicePixelRatio(dpr); px.fill(QColor(T('bg')))
        p=QPainter(px)
        p.setRenderHint(QPainter.Antialiasing, True); p.setRenderHint(QPainter.TextAntialiasing)
        pl=self.PAD_L; pr=self.PAD_R; pt=self.PAD_T; pb=self.PAD_B
        dh=H-pt-pb; uw=W-pl-pr; ny=20000
        rng=self.db_max-self.db_min if self.db_max!=self.db_min else 1.0
        step_db=3
        p.setFont(_qfont(CF_AXIS))
        for db in range(int(self.db_min)-step_db,int(self.db_max)+step_db+1,step_db):
            if db<self.db_min or db>self.db_max: continue
            y=int(pt+(self.db_max-db)/rng*dh)
            if not pt<=y<=H-pb: continue
            is0=(db==0)
            p.setPen(QPen(QColor(T('grid_ref')),1.5 if is0 else 0.7,Qt.SolidLine))
            p.drawLine(pl,y,W-pr,y)
            p.setPen(QColor(T('graph_txt'))); p.drawText(0,y-8,pl-2,16,Qt.AlignRight|Qt.AlignVCenter,f'{db:+d}')
        p.setFont(_qfont(CF_AXIS, True)); last_lx=-999
        draw_freq_minor_grid(p, pl, pr, uw, pt, pb, W, H, ny)
        for f in FREQ_MARKS:
            if f<20 or f>ny: continue
            fx=freq_to_x(f,pl,uw,ny)
            if not pl<=fx<=W-pr: continue
            p.setPen(QPen(QColor(T('grid')),1)); p.drawLine(int(fx),pt,int(fx),H-pb)
            if fx-last_lx<40: continue
            last_lx=fx
            txt=f'{int(f//1000)}k' if f>=1000 else str(int(f))
            tw=p.fontMetrics().horizontalAdvance(txt)
            p.setPen(QColor(T('graph_txt'))); p.drawText(max(pl,min(int(fx-tw/2),W-pr-tw)),H-pb+18,txt)
        p.setFont(_qfont(CF_MODE, True)); p.setPen(QColor(T('graph_txt')))
        p.drawText(pl+4,pt+13,'Magnitude  +  Coherence')
        p.end(); self._cache=px

    def _draw_grid_lines(self, p, W, H):
        pl=self.PAD_L; pr=self.PAD_R; pt=self.PAD_T; pb=self.PAD_B
        dh=H-pt-pb; uw=W-pl-pr; ny=20000
        rng=self.db_max-self.db_min if self.db_max!=self.db_min else 1.0
        step_db=3
        for db in range(int(self.db_min)-step_db,int(self.db_max)+step_db+1,step_db):
            if db<self.db_min or db>self.db_max: continue
            y=int(pt+(self.db_max-db)/rng*dh)
            if not pt<=y<=H-pb: continue
            is0=(db==0)
            p.setPen(QPen(QColor(T('grid_ref')),1.5 if is0 else 0.7,Qt.SolidLine))
            p.drawLine(pl,y,W-pr,y)
        draw_freq_minor_grid(p, pl, pr, uw, pt, pb, W, H, ny)
        for f in FREQ_MARKS:
            if f<20 or f>ny: continue
            fx=freq_to_x(f,pl,uw,ny)
            if not pl<=fx<=W-pr: continue
            p.setPen(QPen(QColor(T('grid')),1)); p.drawLine(int(fx),pt,int(fx),H-pb)
        # γ² 코히어런스 밴드 기준선 (1.0 / 0.5 / 0) — Smaart 식 전용 스케일
        cr,cg,cb_=self._COH_COLOR
        coh_h=dh*self._COH_BAND
        p.setFont(_qfont(CF_AXIS))
        for gv in (1.0, 0.5, 0.0):
            y=int(pt+(1.0-gv)*coh_h)
            p.setPen(QPen(QColor(cr,cg,cb_,70),0.8,Qt.DotLine)); p.drawLine(pl,y,W-pr,y)
            p.setPen(QColor(cr,cg,cb_,170))
            p.drawText(W-pr-26,y-7,24,14,Qt.AlignRight|Qt.AlignVCenter,f'{gv:.1f}')

    def _draw_live_curve(self, p, W, H):
        pl=self.PAD_L; pr=self.PAD_R; pt=self.PAD_T; pb=self.PAD_B
        dh=H-pt-pb; uw=W-pl-pr; ny=20000
        rng=self.db_max-self.db_min if self.db_max!=self.db_min else 1.0
        refmode = self._delta and self._ref_f is not None and self._ref_mag is not None
        if self._delta and not refmode:
            return  # 델타 모드인데 기준 없음 — 절대값을 델타 축에 그리지 않음
        # E 포커스: 포커스된 하나(라이브 카드 또는 캡쳐)만 밝게, 나머지 라이브 곡선은 흐리게.
        _capf = (self._front_idx is not None)   # 캡쳐 포커스 → 모든 라이브 dim
        _fk = self._front_extra
        def _is_focus(key):   # key: None/-1=primary, int=extra. 이 라이브가 포커스 대상인가
            if _capf: return False
            if key is None or key == -1: return (_fk is None or _fk == -1)
            return _fk == key
        def _col(c, key):
            qc = QColor(c)
            if not _is_focus(key): qc.setAlpha(140)   # 비포커스 흐림 (너무 어둡지 않게)
            return qc
        def _vis_smooth(arr, k=7):
            if len(arr) < k: return arr
            kernel = np.ones(k, dtype=float) / k
            return np.convolve(np.pad(arr, k//2, mode='edge'), kernel, mode='valid').astype(float)
        if self.freqs is not None and self.mag is not None and len(self.freqs)>=2:
            f_arr=self.freqs
            m_arr=self.mag - np.interp(f_arr, self._ref_f, self._ref_mag) if refmode else self.mag
            xs=(pl+(np.log10(np.maximum(f_arr,1)/20)/math.log10(ny/20))*uw).astype(float)
            ys_m=(pt+np.clip((self.db_max-m_arr)/rng*dh,0,dh)).astype(float)
            max_pts=max(int(uw),200)
            ys_ms=_vis_smooth(ys_m,7)
            if len(xs)>max_pts:
                _ids=np.linspace(0,len(xs)-1,max_pts,dtype=int)
                xs_d=xs[_ids]; ys_ms=ys_ms[_ids]
            else:
                xs_d=xs
            p.setRenderHint(QPainter.Antialiasing,True)
            p.setPen(QPen(_col(T('green'), None),2.5)); p.setBrush(Qt.NoBrush)
            p.drawPath(_catmull_seg(xs_d, ys_ms))
            if self.coh is not None and len(self.coh)==len(f_arr):
                cr,cg,cb_=self._COH_COLOR
                coh_h=dh*self._COH_BAND
                ys_c_raw=(pt+np.clip((1.0-self.coh)*coh_h,0,coh_h)).astype(float)
                ys_cs=_vis_smooth(ys_c_raw,3)   # 디테일 유지 (과도한 평탄화 방지)
                if len(xs)>max_pts: ys_cs=ys_cs[_ids]
                _coha = 230 if _is_focus(None) else 140   # primary 비포커스면 코히어런스도 흐리게
                p.setPen(QPen(QColor(cr,cg,cb_,_coha),1.8)); p.setBrush(Qt.NoBrush)
                p.drawPath(_catmull_seg(xs_d, ys_cs))
                p.setFont(_qfont(CF_ANNO, True)); p.setPen(QColor(cr,cg,cb_,200))
                p.drawText(pl+4,int(pt+coh_h+5),'γ²')
        # 추가 채널 magnitude 곡선
        if self._tf_extra:
            _ex_max_pts=max(int(uw),200)
            for _exk, ex in self._tf_extra.items():
                ex_f=ex.get('f'); ex_m=ex.get('mag')
                if ex_f is None or ex_m is None or len(ex_f)<2: continue
                if refmode:
                    ex_m = ex_m - np.interp(ex_f, self._ref_f, self._ref_mag)
                ex_xs=(pl+(np.log10(np.maximum(ex_f,1)/20)/math.log10(ny/20))*uw).astype(float)
                ex_ys=(pt+np.clip((self.db_max-ex_m)/rng*dh,0,dh)).astype(float)
                ex_ys_s=_vis_smooth(ex_ys,7)
                if len(ex_xs)>_ex_max_pts:
                    _ei=np.linspace(0,len(ex_xs)-1,_ex_max_pts,dtype=int)
                    ex_xs_d=ex_xs[_ei]; ex_ys_s=ex_ys_s[_ei]
                else:
                    ex_xs_d=ex_xs
                p.setRenderHint(QPainter.Antialiasing,True)
                p.setPen(QPen(_col(ex['color'], _exk),2.0)); p.setBrush(Qt.NoBrush)
                p.drawPath(_catmull_seg(ex_xs_d, ex_ys_s))
        # front(포커스) 라이브 곡선 맨 앞 굵게 재드로우 — 캡쳐 포커스 시엔 생략
        if self._tf_extra and not _capf:
            fk=self._front_extra
            if fk is None or fk==-1:
                if self.freqs is not None and self.mag is not None:
                    fm=self.mag - np.interp(self.freqs,self._ref_f,self._ref_mag) if refmode else self.mag
                    self._draw_mag_line(p,W,H, self.freqs, fm, T('green'), 3.4)
            elif fk in self._tf_extra:
                ex=self._tf_extra[fk]; exf=ex.get('f'); exm=ex.get('mag')
                if exf is not None and exm is not None:
                    if refmode: exm=exm-np.interp(exf,self._ref_f,self._ref_mag)
                    self._draw_mag_line(p,W,H, exf, exm, ex.get('color'), 3.4)

    def paintEvent(self,ev):
        W=self.width(); H=self.height()
        if self._cache is None or self._cache.size()!=self.size():
            self._build_cache(W,H)
        p=QPainter(self); p.drawPixmap(0,0,self._cache)

        # E 포커스: 캡쳐 선택 시 라이브(흐림) 먼저 → 포커스 캡쳐(밝음) 위. 라이브 포커스 시 반대.
        _cap_focus = (self._front_idx is not None)
        def _draw_caps():
            if not (self._captures and not self._delta): return  # 델타 모드 절대값 캡쳐 숨김
            _cap_key=(W,H,self.db_max,self.db_min,self._front_idx,self._live_on_top)
            if self._cap_pix is None or self._cap_pix_key!=_cap_key:
                self._trigger_cap_build(W, H, _cap_key)
            if self._cap_pix is not None:
                p.drawPixmap(0,0,self._cap_pix)
        if _cap_focus:
            self._draw_live_curve(p,W,H); _draw_caps()
        else:
            _draw_caps(); self._draw_live_curve(p,W,H)

        self._draw_grid_lines(p, W, H)

        pl=self.PAD_L; pr=self.PAD_R; pt=self.PAD_T; pb=self.PAD_B; uw=W-pl-pr; ny=20000
        dh=H-pt-pb; rng=max(self.db_max-self.db_min,1.0)
        _CUR  = QColor(255,220,50,210)
        _PEER = QColor(255,220,50,100)
        # 피어 커서: 수직선 + 수평선 (자기 데이터로 y 계산)
        if pl<=self._peer_mx<=W-pr:
            p.setPen(QPen(_PEER,1,Qt.DashLine))
            p.drawLine(self._peer_mx,pt,self._peer_mx,H-pb)
            if self.freqs is not None and self.mag is not None:
                pfreq=x_to_freq(self._peer_mx,pl,uw,ny)
                _pi=np.searchsorted(self.freqs,pfreq)
                if _pi>0 and (_pi>=len(self.freqs) or self.freqs[_pi]-pfreq>pfreq-self.freqs[_pi-1]): _pi-=1
                pidx=int(np.clip(_pi,0,len(self.mag)-1))
                pcy=int(pt+np.clip((self.db_max-float(self.mag[pidx]))/rng*dh,0,dh))
                p.drawLine(pl,pcy,W-pr,pcy)
        # 자체 커서: 십자 + info box
        # 커서 데이터: 선택(front) 카드 우선 → primary → 아무 extra (선택 카드 값이 뜨도록)
        _fk = self._front_extra
        if isinstance(_fk, int) and _fk != -1 and _fk in self._tf_extra:
            _ex = self._tf_extra[_fk]
            _cf = _ex.get('f'); _cm = _ex.get('mag'); _cp = None; _cc = None
        else:
            _cf = self.freqs; _cm = self.mag; _cp = self.phase; _cc = self.coh
            if (_cf is None or _cm is None) and self._tf_extra:
                _ex = next(iter(self._tf_extra.values()))
                _cf = _ex.get('f'); _cm = _ex.get('mag'); _cp = None; _cc = None
        if pl<=self._mx<=W-pr and _cf is not None and _cm is not None:
            cx=self._mx
            freq=x_to_freq(cx,pl,uw,ny)
            _oi=np.searchsorted(_cf,freq)
            if _oi>0 and (_oi>=len(_cf) or _cf[_oi]-freq>freq-_cf[_oi-1]): _oi-=1
            idx=int(np.clip(_oi,0,len(_cm)-1))
            # 수평선 y: 실제 magnitude 값 위치
            cy=int(pt+np.clip((self.db_max-float(_cm[idx]))/rng*dh,0,dh))
            p.setPen(QPen(_CUR,1,Qt.DashLine))
            p.drawLine(cx,pt,cx,H-pb)          # 수직선
            p.drawLine(pl,cy,W-pr,cy)           # 수평선
            fs=f'{freq/1000:.2f}kHz' if freq>=1000 else f'{freq:.0f}Hz'
            mag_str=f'{_cm[idx]:+.1f} dB'
            ph_str=''
            if _cp is not None and len(_cp)==len(_cf):
                ph_str=f'  {int(round(float(_cp[idx])))}°'
            coh_str=''
            if _cc is not None and len(_cc)==len(_cf):
                coh_str=f'  {_cc[idx]*100:.0f}%'
            draw_info_box(p,W,fs,f'{mag_str}{ph_str}{coh_str}')
        p.end()

# ───────────────────────────────────────────
#  장치 선택 섹션 아이콘 (단색 QPainter)
# ───────────────────────────────────────────
class _SignalIcon(QWidget):
    def __init__(self, kind='ref', parent=None):
        super().__init__(parent)
        self._kind = kind
        self.setFixedSize(14, 14)

    def paintEvent(self, ev):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        col = QColor(T('accent') if self._kind == 'ref' else T('accent2'))
        pen = QPen(col, 1.4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        p.setPen(pen); p.setBrush(Qt.NoBrush)
        if self._kind == 'ref':
            # ─▶| 입력 커넥터 : 화살표 → 수직 바
            p.drawLine(1, 7, 8, 7)          # 수평 라인
            p.drawLine(6, 4, 9, 7)          # 화살촉 위
            p.drawLine(6, 10, 9, 7)         # 화살촉 아래
            p.drawLine(10, 3, 10, 11)       # 수직 바 (입력 포트)
            p.drawLine(10, 7, 13, 7)        # 오른쪽 연장선
        else:
            # 파형 심벌 (measurement probe)
            path = QPainterPath()
            path.moveTo(1, 7)
            path.lineTo(3, 7)
            path.lineTo(4, 3)
            path.lineTo(6, 11)
            path.lineTo(8, 3)
            path.lineTo(10, 11)
            path.lineTo(11, 7)
            path.lineTo(13, 7)
            p.drawPath(path)
        p.end()


def _device_section_label(kind, text):
    row = QWidget(); lay = QHBoxLayout(row)
    lay.setContentsMargins(0, 2, 0, 2); lay.setSpacing(5)
    lay.addWidget(_SignalIcon(kind))
    lbl = QLabel(text)
    lbl.setStyleSheet(f'color:{T("text")};font-size:11px;font-weight:bold;')
    lay.addWidget(lbl); lay.addStretch()
    return row


# ───────────────────────────────────────────
#  소형 VU 미터 (TF 창 전용)
# ───────────────────────────────────────────
class _MiniVU(QWidget):
    clicked = pyqtSignal()

    def __init__(self):
        super().__init__(); self.setFixedSize(58, 108)
        self._db=-80.0; self._pk=-80.0; self._pk_hold=0

    def mousePressEvent(self, e): self.clicked.emit(); super().mousePressEvent(e)

    def set_rms(self,db):
        self._db=db; self._pk_hold+=1
        if db>self._pk or self._pk_hold>40: self._pk=db; self._pk_hold=0
        self.update()

    def paintEvent(self,ev):
        p=QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        W=self.width(); H=self.height()
        DB_MIN=-60.0; DB_MAX=0.0; rng=DB_MAX-DB_MIN

        # 텍스트 영역 높이 고정 (숫자 18px + dBFS 14px + 여백 4px = 36px)
        TEXT_H = 36
        bx=4; bw=W-8; by=4; bh=H-by-TEXT_H-2  # 바 영역

        # 테두리
        p.setPen(QPen(QColor(T('border')), 1)); p.setBrush(Qt.NoBrush)
        p.drawRect(bx, by, bw-1, bh-1)

        # 레벨 fill
        p.setPen(Qt.NoPen)
        fill=max(0.0,min(1.0,(self._db-DB_MIN)/rng))
        fh=int(bh*fill)
        if fh>0:
            fy=by+bh-fh
            c=T('red') if self._db>-6 else T('yellow') if self._db>-18 else T('accent')
            g=QLinearGradient(0,fy,0,by+bh)
            g.setColorAt(0,QColor(T('accent'))); g.setColorAt(1,QColor(c))
            p.setBrush(QBrush(g)); p.drawRect(bx+1,fy,bw-2,fh)

        # 피크 홀드 라인
        pk=max(0.0,min(1.0,(self._pk-DB_MIN)/rng))
        py_=int(by+bh*(1.0-pk))
        p.setPen(QPen(QColor(T('yellow')),1)); p.drawLine(bx+1,py_,bx+bw-2,py_)

        # 텍스트 (바 아래 고정 영역)
        txt_top = by + bh + 4
        c2=T('red') if self._db>-6 else T('yellow') if self._db>-18 else T('accent')
        p.setFont(_qfont(11, True)); p.setPen(QColor(c2))
        p.drawText(0, txt_top, W, 18, Qt.AlignHCenter|Qt.AlignVCenter, f'{self._db:.0f}')
        p.setFont(_qfont(CF_ANNO)); p.setPen(QColor(T('text_dim')))
        p.drawText(0, txt_top+18, W, 14, Qt.AlignHCenter|Qt.AlignVCenter, 'dBFS')
        p.end()


# ───────────────────────────────────────────
#  Smaart 방식 Input Levels 카드 위젯
# ───────────────────────────────────────────
class _HorizBarVU(QWidget):
    """Smaart 스타일 수평 레벨 바."""
    def __init__(self):
        super().__init__(); self.setFixedHeight(8)
        self._db = -80.0; self._pk = -80.0; self._pk_hold = 0

    def set_rms(self, db):
        self._db = db; self._pk_hold += 1
        if db > self._pk or self._pk_hold > 40:
            self._pk = db; self._pk_hold = 0
        self.update()

    def reset(self):
        self._db = -80.0; self._pk = -80.0; self._pk_hold = 0; self.update()

    def paintEvent(self, ev):
        # _MiniMeterBar(Spectrum 카드)와 동일한 모던 룩: 둥근 트랙 + 둥근 채움 + peak tick.
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        W = self.width(); H = self.height(); rr = H / 2.0
        DB_MIN = -60.0; DB_MAX = 0.0; rng = DB_MAX - DB_MIN
        bg = QColor(T('bg')); d = -20 if _theme == 'light' else 14   # 라이트 near-white → 어둡게
        track = QColor(max(0, min(bg.red()+d, 255)), max(0, min(bg.green()+d, 255)), max(0, min(bg.blue()+d+2, 255)))
        p.setPen(Qt.NoPen); p.setBrush(track); p.drawRoundedRect(QRectF(0, 0, W, H), rr, rr)
        ratio = max(0.0, min(1.0, (self._db - DB_MIN) / rng))
        bar_w = W * ratio
        if bar_w > 1.5:
            col = QColor(T('red')) if self._db > -3 else QColor(T('yellow')) if self._db > -9 else QColor(T('green'))
            p.setBrush(col); p.drawRoundedRect(QRectF(0, 0, bar_w, H), rr, rr)
        if self._pk > DB_MIN:
            px = W * max(0.0, min(1.0, (self._pk - DB_MIN) / rng))
            p.setPen(QPen(QColor(T('text_dim')), 1)); p.drawLine(int(px), 1, int(px), int(H - 1))
        p.end()


class _DashedAddButton(QPushButton):
    """점선 테두리 'Add' 버튼. Qt QSS의 dashed 보더는 둥근 모서리에서
    점선이 끊겨 보여서, QPainter 로 직접 균일한 점선 라운드 사각형을 그린다."""
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self._hover = False
        self.setStyleSheet('background:transparent;border:none;')

    def enterEvent(self, e):
        self._hover = True; self.update(); super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False; self.update(); super().leaveEvent(e)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        col = QColor(T('accent')) if self._hover else QColor(T('border'))
        pen = QPen(col, 1.0)
        pen.setStyle(Qt.CustomDashLine)
        pen.setDashPattern([4, 4])       # 4px 선 / 4px 간격
        pen.setCapStyle(Qt.FlatCap)
        p.setPen(pen); p.setBrush(Qt.NoBrush)
        r = float(RADIUS_SM)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.drawRoundedRect(rect, r, r)
        txt_col = QColor(T('accent')) if self._hover else QColor(T('text_dim'))
        p.setPen(txt_col)
        f = self.font(); f.setPixelSize(FS_BODY); p.setFont(f)
        p.drawText(self.rect(), Qt.AlignCenter, self.text())
        p.end()


class _MeasCard(QFrame):
    """측정 채널 카드 — 레벨 바 + Meas 장치 선택 + 딜레이 + Start/Stop."""
    start_clicked      = pyqtSignal()
    stop_clicked       = pyqtSignal()
    find_delay_clicked = pyqtSignal()
    delete_clicked     = pyqtSignal()
    selected           = pyqtSignal()   # 카드 본문 클릭 → 곡선 맨 앞으로
    renamed            = pyqtSignal(str)  # 카드 이름 변경 (새 이름)
    graph_toggled      = pyqtSignal(bool) # 그래프 표시 ON/OFF (분석은 계속)

    def __init__(self, number, color, deletable=True):
        super().__init__()
        self._color = color
        self._running = False
        self._display_on = False  # backward-compat alias
        self._is_selected = False
        self._default_name = str(number)
        self._name = ''
        self._del_btn = None; self._meas_cb = None; self._meas_ch_cb = None; self._auto_btn = None
        self.setObjectName('measCard')
        # 세로 Fixed: 컨테이너가 좁아도 카드를 자연 높이 이하로 압축하지 않음 → 행 겹침 방지
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self._apply_card_style()
        self._lay = QVBoxLayout(self); self._lay.setContentsMargins(6, 5, 6, 6); self._lay.setSpacing(3)

        # 헤더: [가시성 체크] 도트 + 번호 + dBFS + Start/Stop 버튼 + 삭제 버튼
        hdr = QHBoxLayout(); hdr.setContentsMargins(0, 0, 0, 0); hdr.setSpacing(4)
        # 그래프 표시 ON/OFF 체크박스 — 분석(Start/Stop)과 무관, 곡선만 숨김/표시
        self._vis_chk = QCheckBox(); self._vis_chk.setChecked(True); self._vis_chk.setFixedWidth(16)
        self._vis_chk.setToolTip('그래프 표시 ON/OFF (분석은 계속)')
        self._vis_chk.setStyleSheet(
            f'QCheckBox::indicator{{width:13px;height:13px;border:1.5px solid {color};'
            f'border-radius:3px;background:transparent;}}'
            f'QCheckBox::indicator:checked{{background:{color};image:none;}}')
        self._vis_chk.stateChanged.connect(lambda st: self.graph_toggled.emit(st == Qt.Checked))
        dot = QLabel('●'); dot.setStyleSheet(f'color:{color};background:transparent;font-size:{FS_BODY}px;')
        self._num_label = QLabel(self._default_name)
        self._num_label.setStyleSheet(f'color:{color};background:transparent;font-size:{FS_BODY}px;font-weight:bold;')
        self._num_label.setToolTip('더블클릭하여 이름 변경')
        num_lbl = self._num_label
        self._db_lbl = QLabel('—')
        self._db_lbl.setStyleSheet(f'color:{color};background:transparent;font-size:{FS_XS}px;font-weight:bold;')
        self._db_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._start_btn = QPushButton('Start'); _apply_txn(self._start_btn, False)
        self._start_btn.setFixedHeight(20)
        self._start_btn.setStyleSheet(self._start_btn_ss())
        self._start_btn.clicked.connect(self._on_start_stop)
        hdr.addWidget(self._vis_chk); hdr.addWidget(dot); hdr.addWidget(num_lbl); hdr.addStretch()
        hdr.addWidget(self._db_lbl); hdr.addWidget(self._start_btn)
        # 삭제 버튼은 deletable 일 때만 생성·추가. (이전엔 부모 없는 상태에서 setVisible(True) 호출 →
        # macOS에서 독립 top-level 창으로 떠 전체화면 Space 전환되는 버그. 조건부 생성으로 해결.)
        if deletable:
            del_btn = QPushButton('－'); del_btn.setFixedSize(18, 18)
            self._del_btn = del_btn
            del_btn.setStyleSheet(self._del_btn_ss())
            del_btn.clicked.connect(self.delete_clicked)
            hdr.addWidget(del_btn)
        self._lay.addLayout(hdr)

        # M (Measurement) VU 바
        mr = QHBoxLayout(); mr.setContentsMargins(0, 0, 0, 0); mr.setSpacing(4)
        self._ml = QLabel('M'); self._ml.setFixedWidth(10)
        self._ml.setStyleSheet(ss_text(FS_XS))
        self._m_bar = _HorizBarVU()
        mr.addWidget(self._ml); mr.addWidget(self._m_bar, 1)
        self._lay.addLayout(mr)

    def _del_btn_ss(self):
        return (f'QPushButton{{background:transparent;color:{T("text_dim")};border:none;'
                f'font-size:{FS_LG}px;padding:0;font-weight:bold;}}'
                f'QPushButton:hover{{color:{T("red")};}}')

    def _start_btn_ss(self):
        _g = QColor(T('accent')); _gr, _gg, _gb = _g.red(), _g.green(), _g.blue()
        return (f'QPushButton{{background:transparent;color:{T("accent")};'
                f'border:1px solid rgba({_gr},{_gg},{_gb},120);'
                f'font-size:{FS_XS}px;padding:0 5px;border-radius:{RADIUS_SM}px;font-weight:bold;}}'
                f'QPushButton:hover{{border-color:{T("accent")};}}')

    def _cb_style(self):
        return (f'QComboBox{{background:{T("bg3")};color:{T("text")};border:1px solid {T("border")};'
                f'border-radius:{RADIUS_SM}px;padding:1px 8px;font-size:{FS_SM}px;min-height:22px;}}'
                f'QComboBox:hover{{border-color:{T("accent")};}}'
                f'QComboBox::drop-down{{width:0;border:none;}}'
                f'QComboBox::down-arrow{{width:0;height:0;image:none;}}')

    def _delay_spin_ss(self):
        return (f'QDoubleSpinBox{{background:{T("bg3")};color:{T("text")};border:1px solid {T("border")};'
                f'border-radius:{RADIUS_SM}px;padding:{PAD_SM};font-size:{FS_SM}px;}}')

    def _auto_btn_ss(self):
        return (f'QPushButton{{background:transparent;color:{T("text_dim")};'
                f'border:1px solid {T("border")};font-size:{FS_XS}px;padding:0 5px;border-radius:{RADIUS_SM}px;}}'
                f'QPushButton:hover{{color:{T("text")};border-color:{T("accent")};}}')

    def restyle(self):
        """테마 토글(다크↔라이트) 시 인라인-구운 색 재적용 — 카드 프레임/콤보/딜레이/버튼."""
        self._apply_card_style()
        self._start_btn.setStyleSheet(self._start_btn_ss())
        self._ml.setStyleSheet(ss_text(FS_XS))
        if self._del_btn is not None: self._del_btn.setStyleSheet(self._del_btn_ss())
        if self._meas_cb is not None:
            _ss = self._cb_style(); self._meas_cb.setStyleSheet(_ss); self._meas_ch_cb.setStyleSheet(_ss)
        if hasattr(self, '_delay_spin'): self._delay_spin.setStyleSheet(self._delay_spin_ss())
        if self._auto_btn is not None: self._auto_btn.setStyleSheet(self._auto_btn_ss())

    def add_device_row(self, meas_cb, meas_ch_cb):
        """Meas 장치 선택 드롭다운 + 딜레이 행을 카드 내부로 임베드."""
        self._lay.addWidget(hsep())
        # Meas device row
        row = QHBoxLayout(); row.setContentsMargins(0, 0, 0, 0); row.setSpacing(3)
        lbl = QLabel('Meas'); lbl.setFixedWidth(30)
        lbl.setStyleSheet(ss_text(FS_XS))
        # 카드 내부 콤보 — 전역 QSS의 반투명 그라디언트(검정 바탕 위에서 까맣게 보임)를
        # 카드와 어울리는 불투명 배경으로 덮어쓴다. (restyle()로 테마 토글 시 재적용)
        self._meas_cb = meas_cb; self._meas_ch_cb = meas_ch_cb
        _cb_ss = self._cb_style()
        meas_cb.setStyleSheet(_cb_ss); meas_ch_cb.setStyleSheet(_cb_ss)
        meas_cb.setMinimumWidth(100); meas_ch_cb.setMinimumWidth(44)
        row.addWidget(lbl); row.addWidget(meas_cb, 1); row.addWidget(meas_ch_cb)
        self._lay.addLayout(row)
        # Delay row
        d_row = QHBoxLayout(); d_row.setContentsMargins(0, 0, 0, 0); d_row.setSpacing(3)
        d_lbl = QLabel('Delay'); d_lbl.setFixedWidth(30)
        d_lbl.setStyleSheet(ss_text(FS_XS))
        self._delay_spin = QDoubleSpinBox()
        self._delay_spin.setRange(-2000, 2000); self._delay_spin.setDecimals(2)
        self._delay_spin.setSingleStep(0.5); self._delay_spin.setValue(0.0)
        self._delay_spin.setSuffix(' ms')
        self._delay_spin.setMinimumWidth(82); self._delay_spin.setFixedHeight(22)
        self._delay_spin.setButtonSymbols(QDoubleSpinBox.NoButtons)
        self._delay_spin.setAlignment(Qt.AlignCenter)
        self._delay_spin.setStyleSheet(self._delay_spin_ss())
        auto_btn = QPushButton(' Auto'); auto_btn.setIcon(_icon('search',13)); auto_btn.setFixedHeight(22)
        self._auto_btn = auto_btn
        auto_btn.setStyleSheet(self._auto_btn_ss())
        auto_btn.clicked.connect(self.find_delay_clicked)
        d_row.addWidget(d_lbl); d_row.addWidget(self._delay_spin, 1); d_row.addWidget(auto_btn)
        self._lay.addLayout(d_row)

    def delay_ms(self):
        return self._delay_spin.value() if hasattr(self, '_delay_spin') else 0.0

    def set_delay(self, ms):
        if hasattr(self, '_delay_spin'):
            self._delay_spin.blockSignals(True)
            self._delay_spin.setValue(ms)
            self._delay_spin.blockSignals(False)

    def set_meas(self, db):
        self._m_bar.set_rms(db)
        c = T('red') if db > -6 else T('yellow') if db > -18 else self._color
        self._db_lbl.setStyleSheet(f'color:{c};background:transparent;font-size:{FS_XS}px;font-weight:bold;')
        self._db_lbl.setText(f'{db:.0f}')

    def set_ref(self, db):
        pass  # Ref is shared, shown in Ref section

    def reset(self):
        self._m_bar.reset()
        self._db_lbl.setStyleSheet(f'color:{self._color};background:transparent;font-size:{FS_XS}px;font-weight:bold;')
        self._db_lbl.setText('—')

    def _on_start_stop(self):
        if self._running:
            self.stop_clicked.emit()
        else:
            self.start_clicked.emit()

    def _apply_card_style(self):
        # 색 식별은 도트·번호·체크박스(카드색)가 담당. 테두리는 네온 프레임 대신 저알파·얇게(차분).
        _c = QColor(self._color); _r, _g, _b = _c.red(), _c.green(), _c.blue()
        if self._is_selected:
            # 선택: 카드색 은은히 채움 + 선명하지만 네온 아닌 테두리 (굵기·padding은 동일 크기 유지)
            self.setStyleSheet(
                f'QFrame#measCard{{border:2px solid rgba({_r},{_g},{_b},230);border-radius:{RADIUS_SM}px;'
                f'background:rgba({_r},{_g},{_b},32);padding:1px;}}')
        else:
            # 비선택: 차분한 저알파 색 프레임
            self.setStyleSheet(
                f'QFrame#measCard{{border:1px solid rgba({_r},{_g},{_b},120);border-radius:{RADIUS_SM}px;'
                f'background:{T("panel")};padding:2px;}}')

    def set_selected(self, on):
        on = bool(on)
        if on == self._is_selected: return
        self._is_selected = on
        self._apply_card_style()

    def set_name(self, name):
        self._name = name or ''
        self._num_label.setText(self._name or self._default_name)

    def set_number(self, n):
        self._default_name = str(n)
        if not self._name:
            self._num_label.setText(self._default_name)

    def is_graph_visible(self):
        return self._vis_chk.isChecked()

    def _begin_rename(self):
        begin_inline_rename(self, self._num_label, self._on_renamed)

    def _on_renamed(self, txt):
        self._name = txt
        self._num_label.setText(txt or self._default_name)
        self.renamed.emit(txt)

    def mousePressEvent(self, e):
        self.selected.emit()
        super().mousePressEvent(e)

    def mouseDoubleClickEvent(self, e):
        self._begin_rename()
        super().mouseDoubleClickEvent(e)

    def set_running(self, running):
        self._running = running
        self._display_on = running  # backward-compat
        if running:
            self._start_btn.setText('Stop'); _apply_txn(self._start_btn, True)
            _r = QColor(T('red')); rr, rg, rb = _r.red(), _r.green(), _r.blue()
            self._start_btn.setStyleSheet(
                f'QPushButton{{background:transparent;color:{T("red")};'
                f'border:1px solid rgba({rr},{rg},{rb},140);'
                f'font-size:{FS_XS}px;padding:0 5px;border-radius:{RADIUS_SM}px;font-weight:bold;}}'
                f'QPushButton:hover{{border-color:{T("red")};}}')
        else:
            _g = QColor(T('accent')); gr, gg, gb = _g.red(), _g.green(), _g.blue()
            self._start_btn.setText('Start'); _apply_txn(self._start_btn, False)
            self._start_btn.setStyleSheet(
                f'QPushButton{{background:transparent;color:{T("accent")};'
                f'border:1px solid rgba({gr},{gg},{gb},120);'
                f'font-size:{FS_XS}px;padding:0 5px;border-radius:{RADIUS_SM}px;font-weight:bold;}}'
                f'QPushButton:hover{{border-color:{T("accent")};}}')


# backward-compat alias
_PairLevelCard = _MeasCard


class _VUProxy:
    """_MiniVU를 대체하는 경량 프록시 — 기존 코드 변경 없이 카드로 포워딩."""
    def __init__(self):
        self._db = -80.0; self._pk = -80.0; self._pk_hold = 0
        self._card_fn = None

    class _FakeSig:
        def connect(self, *a): pass
        def disconnect(self, *a): pass

    clicked = _FakeSig()

    def set_rms(self, db):
        self._db = db; self._pk_hold += 1
        if db > self._pk or self._pk_hold > 40: self._pk = db; self._pk_hold = 0
        if self._card_fn: self._card_fn(db)

    def update(self): pass


# ───────────────────────────────────────────
#  Live IR 헬퍼 & 캔버스
# ───────────────────────────────────────────
def _hilbert_env(x):
    """FFT 기반 Hilbert 포락선 (scipy 불필요)."""
    N = len(x)
    X = np.fft.fft(x)
    h = np.zeros(N, dtype=np.float64)
    if N % 2 == 0:
        h[0] = 1; h[N // 2] = 1; h[1:N // 2] = 2
    else:
        h[0] = 1; h[1:(N + 1) // 2] = 2
    return np.abs(np.fft.ifft(X * h)).astype(np.float32)


class TFIRCanvas(QWidget):
    """Live IR — Lin / ETC / Log 3-mode 표시."""
    PAD_L = 40; PAD_R = 15; PAD_T = 10; PAD_B = 20
    _cap_built = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setMinimumSize(400, 80)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMouseTracking(True); self.setAttribute(Qt.WA_OpaquePaintEvent, True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.t_ms = None; self.etc_db = None; self.h_raw = None
        self.peak_ms = 0.0
        self._delay_ms = 0.0   # delay_spin 설정값 — 주황 대시 라인 위치
        self.t_min = -10.0; self.t_max = 10.0   # 보정 IR: 0ms 가운데 고정
        self.db_min = -60.0; self.db_max = 0.0
        self.ir_mode = 0   # 0=Lin  1=ETC  2=Log
        self._mx = -1
        self._cache = None
        self._center_locked = False  # Find/delay 설정 후 자동 재조정 방지
        self._captures = []
        self._cap_pix = None; self._cap_pix_key = None
        self._front_idx = None; self._live_on_top = False
        self._cap_building = False
        self._cap_img_pending = None; self._cap_key_pending = None
        self._cap_built.connect(self._apply_cap_built)
        self._tf_extra = {}       # {ch_idx: {'color','t','h'}} — 카드별 라이브 IR
        self._front_extra = None  # None/-1=primary 맨앞, int=해당 pair idx 맨앞

    def _apply_cap_built(self):
        img, key = self._cap_img_pending, self._cap_key_pending
        self._cap_img_pending = self._cap_key_pending = None
        if img is not None:
            self._cap_pix = QPixmap.fromImage(img)
            self._cap_pix_key = key
            self.update()

    def _trigger_cap_build(self, W, H, cap_key):
        if self._cap_building: return
        self._cap_building = True
        caps = [dict(c) for c in self._captures]
        front = self._front_idx
        threading.Thread(target=self._bg_cap_build,
                         args=(W, H, cap_key, caps, front),
                         daemon=True).start()

    def _bg_cap_build(self, W, H, cap_key, caps, front):
        try:
            img = self._build_cap_img(W, H, caps, front)
            self._cap_img_pending = img
            self._cap_key_pending = cap_key
            self._cap_built.emit()
        except Exception:
            pass
        finally:
            self._cap_building = False

    def _build_cap_img(self, W, H, caps, front):
        from PyQt5.QtGui import QImage
        pl=self.PAD_L; pr=self.PAD_R; pt=self.PAD_T; pb=self.PAD_B
        dh=H-pt-pb; uw=W-pl-pr
        t_range=max(self.t_max-self.t_min,1.0)
        MAX_PTS = max(int(uw), 200)  # 화면 픽셀 수 기준 — Python 루프 최소화
        img=QImage(W,H,QImage.Format_ARGB32_Premultiplied); img.fill(0)
        p=QPainter(img); p.setRenderHint(QPainter.Antialiasing,True)
        def _draw_one(cap, emph=False):
            t_arr=cap['t']; h_raw=cap['h']
            if t_arr is None or h_raw is None: return  # extra 카드 빈 IR 캡쳐 스킵
            xs_r=ys_r=None
            if self.ir_mode==0:
                peak_lin=max(float(np.max(np.abs(h_raw))),1e-10)
                h_norm=h_raw/peak_lin
                mask=(t_arr>=self.t_min)&(t_arr<=self.t_max)
                if np.any(mask):
                    t_v=t_arr[mask]; h_v=h_norm[mask]
                    if len(t_v)>MAX_PTS:
                        ids=np.linspace(0,len(t_v)-1,MAX_PTS,dtype=int); t_v=t_v[ids]; h_v=h_v[ids]
                    xs_r=(pl+(t_v-self.t_min)/t_range*uw).astype(float)
                    ys_r=(pt+np.clip((1.0-h_v)/2.0*dh,0,dh)).astype(float)
            else:
                db_arr=cap['etc_db']
                if self.ir_mode==2 and h_raw is not None:
                    pk=max(float(np.max(np.abs(h_raw))),1e-10)
                    db_arr=20*np.log10(np.maximum(np.abs(h_raw)/pk,1e-10))
                if db_arr is not None:
                    db_range=max(self.db_max-self.db_min,1.0)
                    mask=(t_arr>=self.t_min)&(t_arr<=self.t_max)
                    if np.any(mask):
                        t_v=t_arr[mask]; db_v=db_arr[mask]
                        if len(t_v)>MAX_PTS:
                            ids=np.linspace(0,len(t_v)-1,MAX_PTS,dtype=int); t_v=t_v[ids]; db_v=db_v[ids]
                        xs_r=(pl+(t_v-self.t_min)/t_range*uw).astype(float)
                        ys_r=(pt+np.clip((self.db_max-db_v)/db_range*dh,0,dh)).astype(float)
            if xs_r is not None and len(xs_r)>=2:
                # E 포커스: 선택(front)=밝고 굵게, 비선택=흐리고 얇게
                poly=QPolygonF([QPointF(x,y) for x,y in zip(xs_r.tolist(),ys_r.tolist())])
                qc=QColor(cap['color'])
                if emph:
                    p.setPen(QPen(qc,3.0))
                else:
                    qc.setAlpha(140); p.setPen(QPen(qc,1.4))
                p.setBrush(Qt.NoBrush)
                p.drawPolyline(poly)
        for i,cap in enumerate(caps):
            if i==front: continue
            if not cap.get('visible', True): continue
            _draw_one(cap, emph=False)
        if front is not None and 0<=front<len(caps):
            if caps[front].get('visible', True):
                _draw_one(caps[front], emph=True)
        p.end()
        return img

    def _build_cap_pix(self, W, H):
        img = self._build_cap_img(W, H, list(self._captures), self._front_idx)
        self._cap_pix = QPixmap.fromImage(img)
        self._cap_pix_key = (W, H, self.db_max, self.db_min, round(self.t_min,1), round(self.t_max,1), self.ir_mode, self._front_idx, self._live_on_top)

    def add_capture(self, label, color, delay=0.0):
        if self.t_ms is None or self.h_raw is None: return
        self._captures.append({
            't': self.t_ms.copy(), 'h': self.h_raw.copy(),
            'etc_db': self.etc_db.copy() if self.etc_db is not None else None,
            'color': color, 'label': label, 'delay': delay
        })
        self._cap_pix=None; self._last_cap_t=time.monotonic(); self.update()

    def add_capture_empty(self, label, color, delay=0.0):
        """extra 카드는 IR 데이터가 없음 — _tf_captures 인덱스 정합용 빈 캡쳐."""
        self._captures.append({
            't': None, 'h': None, 'etc_db': None, 'color': color, 'label': label, 'delay': delay
        })
        self._cap_pix=None; self.update()

    def add_capture_data(self, label, color, t, h, etc_db=None, delay=0.0):
        """extra 카드(멀티카드)의 live IR 캡쳐 — 카드별 _tf_extra 의 t/h 사용."""
        if t is None or h is None:
            self.add_capture_empty(label, color, delay); return
        h = np.asarray(h, dtype=np.float32)
        if etc_db is None:
            etc = _hilbert_env(h); pk = max(float(np.max(etc)), 1e-10)
            etc_db = (20 * np.log10(np.maximum(etc / pk, 1e-10))).astype(np.float32)
        self._captures.append({
            't': np.asarray(t, dtype=np.float32).copy(), 'h': h.copy(),
            'etc_db': np.asarray(etc_db, dtype=np.float32).copy(),
            'color': color, 'label': label, 'delay': delay
        })
        self._cap_pix=None; self._last_cap_t=time.monotonic(); self.update()

    def remove_capture(self, idx):
        if 0 <= idx < len(self._captures):
            self._captures.pop(idx)
            if self._front_idx is not None:
                if self._front_idx==idx: self._front_idx=None
                elif self._front_idx>idx: self._front_idx-=1
            self._cap_pix=None; self._last_cap_t=time.monotonic(); self.update()

    def bring_to_front(self, idx):
        if 0 <= idx < len(self._captures):
            self._front_idx=idx; self._live_on_top=False
            self._cap_pix=None; self.update()

    def set_tf_extra(self, ch_idx, color, t, h, delay=0.0):
        # ETC 포락선은 한 번만 계산해 저장 (paint마다 hilbert 재계산 방지)
        etc = _hilbert_env(h); pk = max(float(np.max(etc)), 1e-10)
        etc_db = (20 * np.log10(np.maximum(etc / pk, 1e-10))).astype(np.float32)
        # delay: 카드 딜레이값 — paintEvent 에서 카드색 마커 위치로 사용
        self._tf_extra[ch_idx] = {'color': color, 't': t, 'h': h, 'etc_db': etc_db, 'delay': delay}
        self.update()

    def clear_tf_extra(self, ch_idx):
        self._tf_extra.pop(ch_idx, None); self.update()

    def clear_all_tf_extra(self):
        self._tf_extra.clear(); self.update()

    def set_front_curve(self, key):
        self._front_extra = key; self.update()

    def _draw_ir_curve(self, p, W, H, t_arr, h_raw, color, width, etc_db=None, dim=False):
        """단일 IR 곡선(line)을 현재 ir_mode에 맞춰 그림 — extra/front 공용."""
        if t_arr is None or h_raw is None or len(t_arr) < 2: return
        pl=self.PAD_L; pr=self.PAD_R; pt=self.PAD_T; pb=self.PAD_B
        dh=H-pt-pb; uw=W-pl-pr; t_range=max(self.t_max-self.t_min,1.0)
        mask=(t_arr>=self.t_min)&(t_arr<=self.t_max)
        if not np.any(mask): return
        t_v=t_arr[mask]
        if self.ir_mode==0:
            pk=max(float(np.max(np.abs(h_raw))),1e-10)
            v=(h_raw/pk)[mask]
            ys=pt+np.clip((1.0-v)/2.0*dh,0,dh)
        else:
            db_range=max(self.db_max-self.db_min,1.0)
            if self.ir_mode==1:
                db = etc_db if etc_db is not None else _hilbert_env(h_raw)
                if etc_db is None:
                    pk=max(float(np.max(db)),1e-10); db=20*np.log10(np.maximum(db/pk,1e-10))
            else:
                pk=max(float(np.max(np.abs(h_raw))),1e-10)
                db=20*np.log10(np.maximum(np.abs(h_raw)/pk,1e-10))
            v=np.asarray(db)[mask]
            ys=pt+np.clip((self.db_max-v)/db_range*dh,0,dh)
        _mp=max(int(uw),200)
        if len(t_v)>_mp:
            ids=np.linspace(0,len(t_v)-1,_mp,dtype=int); t_v=t_v[ids]; ys=ys[ids]
        xs=(pl+(t_v-self.t_min)/t_range*uw).astype(float); ys=ys.astype(float)
        p.setRenderHint(QPainter.Antialiasing,False)   # 라이브 곡선 AA OFF — Retina 전체화면 AA 래스터화 10배 비쌈
        _qc=QColor(color)
        if dim: _qc.setAlpha(140)
        p.setPen(QPen(_qc,width)); p.setBrush(Qt.NoBrush)
        p.drawPolyline(QPolygonF([QPointF(x,y) for x,y in zip(xs.tolist(),ys.tolist())]))

    def set_data(self, t_ms, h):
        self.t_ms = t_ms
        self.h_raw = h.copy()
        etc = _hilbert_env(h)
        peak_val = max(float(np.max(etc)), 1e-10)
        pk_idx = int(np.argmax(etc))
        self.peak_ms = float(t_ms[pk_idx])
        self.etc_db = 20 * np.log10(np.maximum(etc / peak_val, 1e-10))
        # 그리드 캐시는 뷰(t_min/t_max/모드)에만 의존 → 데이터 갱신 시 무효화 불필요.
        # (매 프레임 Retina 픽스맵 재할당+그리드+텍스트 재생성 방지 → IR 페인트 시간↓)
        self.update()

    def set_mode(self, idx): self.ir_mode = idx; self._cache = None; self._cap_pix = None; self.update()

    def clear(self):
        self.t_ms = self.etc_db = self.h_raw = None
        self._center_locked = False; self._cache = None; self.update()

    def mouseMoveEvent(self, e): self._mx = e.x(); self.update()
    def leaveEvent(self, e): self._mx = -1; self.update()
    def resizeEvent(self, ev): self._cache = None; self.update()
    def enterEvent(self, e): self.setFocus(); super().enterEvent(e)  # 호버 시 자동 포커스

    def wheelEvent(self, e):
        e.ignore()  # 마우스 휠 비활성화

    def mousePressEvent(self, e): self.setFocus(); super().mousePressEvent(e)

    def keyPressEvent(self, e):
        key = e.key(); mod = e.modifiers()
        if key in (Qt.Key_Up, Qt.Key_Down):
            if self.ir_mode == 0:
                # Linear 모드: Up=시간 뒤로, Down=시간 앞으로 (Left/Right와 동일 축)
                span = max(self.t_max - self.t_min, 1.0); d = span * 0.06
                if key == Qt.Key_Up:
                    self.t_min = self.t_min - d   # 보정 IR: 음수 시간(0 좌측) 허용
                else:
                    self.t_min = self.t_min + d
                self.t_max = self.t_min + span
                self._cache = None; self.update()
            else:
                # ETC/Log 모드: dB 축 위아래 이동 (범위 +90 ~ -90)
                step = 6.0 if key == Qt.Key_Up else -6.0
                db_span = self.db_max - self.db_min
                new_max = min(90.0, max(-90.0 + db_span, self.db_max + step))
                new_min = new_max - db_span
                if new_min >= -90.0:
                    self.db_max = new_max; self.db_min = new_min
                    self._cache = None; self.update()
        elif key == Qt.Key_Left:
            span = max(self.t_max - self.t_min, 1.0); d = span * 0.06
            self.t_min = self.t_min - d
            self.t_max = self.t_min + span
            self._cache = None; self.update()
        elif key == Qt.Key_Right:
            span = max(self.t_max - self.t_min, 1.0); d = span * 0.06
            self.t_min = self.t_min + d
            self.t_max = self.t_min + span
            self._cache = None; self.update()
        elif key in (Qt.Key_Equal, Qt.Key_Plus) and mod & Qt.ControlModifier:
            span = max(5.0, (self.t_max - self.t_min) * 0.88)
            mid = (self.t_max + self.t_min) / 2
            self.t_min = mid - span / 2; self.t_max = self.t_min + span
            self._cache = None; self.update()
        elif key == Qt.Key_Minus and mod & Qt.ControlModifier:
            span = max(5.0, (self.t_max - self.t_min) * 1.12)
            mid = (self.t_max + self.t_min) / 2
            self.t_min = mid - span / 2; self.t_max = self.t_min + span
            self._cache = None; self.update()
        else:
            super().keyPressEvent(e)

    def _build_cache(self, W, H):
        from PyQt5.QtGui import QPixmap
        dpr=self.devicePixelRatio()
        pix = QPixmap(int(W*dpr),int(H*dpr)); pix.setDevicePixelRatio(dpr); pix.fill(QColor(T('bg')))
        p = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing, True); p.setRenderHint(QPainter.TextAntialiasing)
        pl = self.PAD_L; pr = self.PAD_R; pt = self.PAD_T; pb = self.PAD_B
        dh = H - pt - pb; uw = W - pl - pr
        t_range = max(self.t_max - self.t_min, 1.0)

        # ── 시간(수직) 그리드 공통 ──────────────────
        step_ms = (2 if t_range <= 20 else 5 if t_range <= 50 else
                   10 if t_range <= 100 else 20 if t_range <= 200 else 50)
        t = int(self.t_min / step_ms) * step_ms
        while t <= self.t_max + step_ms:
            x = int(pl + (t - self.t_min) / t_range * uw)
            if pl <= x <= W - pr:
                p.setPen(QPen(QColor(T('grid')), 1)); p.drawLine(x, pt, x, H - pb)
                p.setPen(QColor(T('graph_txt'))); p.setFont(_qfont(CF_AXIS))
                lbl = f'{t:.0f}ms'; tw = p.fontMetrics().horizontalAdvance(lbl)
                p.drawText(x - tw // 2, H - pb + 14, lbl)
            t += step_ms

        if self.ir_mode == 0:  # ── Lin ───────────────────────────────────
            p.setFont(_qfont(CF_AXIS))
            for amp in [1.0, 0.5, 0.0, -0.5, -1.0]:
                y = int(pt + (1.0 - amp) / 2.0 * dh)
                if not pt <= y <= H - pb: continue
                is0 = (amp == 0.0)
                p.setPen(QPen(QColor(T('grid_ref')), 1.5 if is0 else 0.7,
                             Qt.SolidLine))
                p.drawLine(pl, y, W - pr, y)
                p.setPen(QColor(T('graph_txt'))); p.drawText(0,y-8,pl-2,16,Qt.AlignRight|Qt.AlignVCenter,f'{amp:+.1f}')
            p.setFont(_qfont(CF_MODE, True)); p.setPen(QColor(T('graph_txt')))
            p.drawText(pl + 4, pt + 15, 'Live IR  (Linear)')
        else:  # ── ETC (1) or Log (2) ─────────────────────────────────────
            db_range = max(self.db_max - self.db_min, 1.0)
            p.setFont(_qfont(CF_AXIS))
            for db in range(int(self.db_min), int(self.db_max) + 1, 10):
                if not self.db_min <= db <= self.db_max: continue
                y = int(pt + (self.db_max - db) / db_range * dh)
                if not pt <= y <= H - pb: continue
                is0 = (db == 0)
                p.setPen(QPen(QColor(T('grid_ref')), 1.3 if is0 else 0.6,
                             Qt.SolidLine))
                p.drawLine(pl, y, W - pr, y)
                p.setPen(QColor(T('graph_txt'))); p.drawText(0,y-8,pl-2,16,Qt.AlignRight|Qt.AlignVCenter,f'{db:+d}')
            lbl_text = 'Live IR  (ETC)' if self.ir_mode == 1 else 'Live IR  (Log)'
            p.setFont(_qfont(CF_MODE, True)); p.setPen(QColor(T('graph_txt')))
            p.drawText(pl + 4, pt + 15, lbl_text)
        p.end()
        self._cache = pix

    def _draw_grid_lines(self, p, W, H):
        pl = self.PAD_L; pr = self.PAD_R; pt = self.PAD_T; pb = self.PAD_B
        dh = H - pt - pb; uw = W - pl - pr
        t_range = max(self.t_max - self.t_min, 1.0)
        step_ms = (2 if t_range <= 20 else 5 if t_range <= 50 else
                   10 if t_range <= 100 else 20 if t_range <= 200 else 50)
        t = int(self.t_min / step_ms) * step_ms
        while t <= self.t_max + step_ms:
            x = int(pl + (t - self.t_min) / t_range * uw)
            if pl <= x <= W - pr:
                p.setPen(QPen(QColor(T('grid')), 1)); p.drawLine(x, pt, x, H - pb)
            t += step_ms
        if self.ir_mode == 0:
            for amp in [1.0, 0.5, 0.0, -0.5, -1.0]:
                y = int(pt + (1.0 - amp) / 2.0 * dh)
                if not pt <= y <= H - pb: continue
                is0 = (amp == 0.0)
                p.setPen(QPen(QColor(T('grid_ref')), 1.5 if is0 else 0.7,
                             Qt.SolidLine))
                p.drawLine(pl, y, W - pr, y)
        else:
            db_range = max(self.db_max - self.db_min, 1.0)
            for db in range(int(self.db_min), int(self.db_max) + 1, 10):
                if not self.db_min <= db <= self.db_max: continue
                y = int(pt + (self.db_max - db) / db_range * dh)
                if not pt <= y <= H - pb: continue
                is0 = (db == 0)
                p.setPen(QPen(QColor(T('grid_ref')), 1.3 if is0 else 0.6,
                             Qt.SolidLine))
                p.drawLine(pl, y, W - pr, y)

    def _draw_live_curve(self, p, W, H):
        pl = self.PAD_L; pr = self.PAD_R; pt = self.PAD_T; pb = self.PAD_B
        dh = H - pt - pb; uw = W - pl - pr
        t_range = max(self.t_max - self.t_min, 1.0)
        p.setRenderHint(QPainter.Antialiasing, False)   # 라이브 곡선 AA OFF — Retina 전체화면 AA 래스터화 10배 비쌈
        # E 포커스: 포커스된 하나만 밝게, 나머지 라이브는 흐리게(alpha 140)
        _capf = (self._front_idx is not None)
        _fk = self._front_extra
        def _is_focus(key):
            if _capf: return False
            if key is None or key == -1: return (_fk is None or _fk == -1)
            return _fk == key
        _pdim = not _is_focus(None)        # primary 흐림 여부
        _LA = 140 if _pdim else 230        # primary 라이브 라인 알파
        if self.ir_mode == 0:
            if self.t_ms is not None and self.h_raw is not None and len(self.t_ms) >= 2:
                peak_lin = max(float(np.max(np.abs(self.h_raw))), 1e-10)
                t_arr = self.t_ms; h_norm = self.h_raw / peak_lin
                mask = (t_arr >= self.t_min) & (t_arr <= self.t_max)
                if np.any(mask):
                    t_v = t_arr[mask]; h_v = h_norm[mask]
                    _mp = max(int(uw), 200)
                    if len(t_v) > _mp:
                        ids = np.linspace(0, len(t_v) - 1, _mp, dtype=int)
                        t_v = t_v[ids]; h_v = h_v[ids]
                    xs = (pl + (t_v - self.t_min) / t_range * uw).astype(float)
                    ys = (pt + np.clip((1.0 - h_v) / 2.0 * dh, 0, dh)).astype(float)
                    lc = QColor(T('green')); lc.setAlpha(_LA)
                    p.setPen(QPen(lc, 2.0)); p.setBrush(Qt.NoBrush)
                    p.drawPolyline(QPolygonF([QPointF(x,y) for x,y in zip(xs.tolist(),ys.tolist())]))
        else:
            db_range = max(self.db_max - self.db_min, 1.0)
            if self.t_ms is not None and len(self.t_ms) >= 2:
                if self.ir_mode == 1:
                    db_arr = self.etc_db
                else:
                    if self.h_raw is not None:
                        pk = max(float(np.max(np.abs(self.h_raw))), 1e-10)
                        db_arr = 20 * np.log10(np.maximum(np.abs(self.h_raw) / pk, 1e-10))
                    else:
                        db_arr = None
                if db_arr is not None:
                    t_arr = self.t_ms
                    mask = (t_arr >= self.t_min) & (t_arr <= self.t_max)
                    if np.any(mask):
                        t_v = t_arr[mask]; db_v = db_arr[mask]
                        _mp2 = max(int(uw), 200)
                        if len(t_v) > _mp2:
                            ids = np.linspace(0, len(t_v) - 1, _mp2, dtype=int)
                            t_v = t_v[ids]; db_v = db_v[ids]
                        xs = (pl + (t_v - self.t_min) / t_range * uw).astype(float)
                        ys = (pt + np.clip((self.db_max - db_v) / db_range * dh, 0, dh)).astype(float)
                        _poly_pts = [QPointF(x,y) for x,y in zip(xs.tolist(),ys.tolist())]
                        if self.ir_mode == 1:  # ETC — fill + line
                            fp = QPainterPath()
                            fp.moveTo(xs[0], float(H - pb)); fp.lineTo(xs[0], ys[0])
                            for pt2 in _poly_pts[1:]: fp.lineTo(pt2.x(), pt2.y())
                            fp.lineTo(xs[-1], float(H - pb)); fp.closeSubpath()
                            g = QLinearGradient(0, pt, 0, H - pb)
                            ac = QColor(T('green')); ac.setAlpha(20 if _pdim else 55)
                            ac2 = QColor(T('green')); ac2.setAlpha(2 if _pdim else 5)
                            g.setColorAt(0, ac); g.setColorAt(1, ac2)
                            p.setBrush(QBrush(g)); p.setPen(Qt.NoPen); p.drawPath(fp)
                            lc = QColor(T('green')); lc.setAlpha(_LA)
                            p.setPen(QPen(lc, 1.6)); p.setBrush(Qt.NoBrush)
                            p.drawPolyline(QPolygonF(_poly_pts))
                        else:  # Log — line only
                            lc = QColor(T('green')); lc.setAlpha(_LA)
                            p.setPen(QPen(lc, 1.2)); p.setBrush(Qt.NoBrush)
                            p.drawPolyline(QPolygonF(_poly_pts))

        # 카드별 추가 IR 곡선 + front(포커스) 맨앞 굵게 재드로우. 비포커스는 흐리게(alpha 140).
        if self._tf_extra:
            for key, ex in self._tf_extra.items():
                if key == self._front_extra and not _capf: continue   # front는 아래서 굵게(라이브 포커스 시)
                self._draw_ir_curve(p, W, H, ex.get('t'), ex.get('h'),
                                    ex.get('color'), 1.6, ex.get('etc_db'), dim=not _is_focus(key))
            if not _capf:   # 캡쳐 포커스 시엔 라이브 front 굵게 재드로우 생략
                fk = self._front_extra
                if fk is None or fk == -1:
                    self._draw_ir_curve(p, W, H, self.t_ms, self.h_raw, T('green'), 2.8, self.etc_db)
                elif fk in self._tf_extra:
                    ex = self._tf_extra[fk]
                    self._draw_ir_curve(p, W, H, ex.get('t'), ex.get('h'),
                                        ex.get('color'), 2.8, ex.get('etc_db'))

    def paintEvent(self, ev):
        W = self.width(); H = self.height()
        if self._cache is None or self._cache.size() != self.size():
            self._build_cache(W, H)
        p = QPainter(self); p.drawPixmap(0, 0, self._cache)

        # E 포커스: 캡쳐 선택 시 라이브(흐림) 먼저 → 포커스 캡쳐(밝음) 위. 라이브 포커스 시 반대.
        _cap_focus = (self._front_idx is not None)
        def _draw_caps():
            if not self._captures: return
            _cap_key=(W,H,self.db_max,self.db_min,round(self.t_min,1),round(self.t_max,1),self.ir_mode,self._front_idx,self._live_on_top)
            if self._cap_pix is None or self._cap_pix_key!=_cap_key:
                self._trigger_cap_build(W, H, _cap_key)
            if self._cap_pix is not None:
                p.drawPixmap(0,0,self._cap_pix)
        if _cap_focus:
            self._draw_live_curve(p, W, H); _draw_caps()
        else:
            _draw_caps(); self._draw_live_curve(p, W, H)

        self._draw_grid_lines(p, W, H)

        pl = self.PAD_L; pr = self.PAD_R; pt = self.PAD_T; pb = self.PAD_B; uw = W - pl - pr
        _tr = max(self.t_max - self.t_min, 1.0)
        # 카드별 딜레이 마커 — 각 카드 색 세로 점선. 임펄스가 실제 도착(=딜레이) 위치에
        # 그려지므로 마커가 그 카드 임펄스를 가리킨다. front 카드는 굵게 + 값 라벨.
        _fk = self._front_extra
        # 캡처가 front 면(_front_idx 설정 + 라이브가 위가 아님) 라벨은 그 캡처에, 아니면 라이브 카드에.
        _cap_front_idx = self._front_idx if (not self._live_on_top) else None
        _markers = []   # (delay_ms, color, is_front, is_capture)
        # 라이브 카드 마커 — 세로 점선 + front 값 라벨
        if self.t_ms is not None:   # primary 활성(정지 시 숨김)
            _markers.append((self._delay_ms, T('green'),
                             _cap_front_idx is None and (_fk is None or _fk == -1), False))
        for _key, _ex in self._tf_extra.items():
            _markers.append((_ex.get('delay', 0.0), _ex.get('color'),
                             _cap_front_idx is None and _key == _fk, False))
        # 캡처 마커 — 점선 없이 딜레이 값만 표기 (각 캡처색). 사용자 요청: 캡처는 점선 제거.
        for _ci, _cap in enumerate(self._captures):
            if not _cap.get('visible', True): continue
            if _cap.get('t') is None: continue   # 빈 IR 캡처 → 마커 없음
            _markers.append((_cap.get('delay', 0.0), _cap.get('color'),
                             _ci == _cap_front_idx, True))
        for _dms, _dcol, _is_front, _is_cap in _markers:
            if not (self.t_min <= _dms <= self.t_max): continue
            if _dms == 0.0 and not _is_cap: continue   # 라이브 0딜레이 마커 생략
            _dx = int(pl + (_dms - self.t_min) / _tr * uw)
            _c = QColor(_dcol)
            if not _is_cap:
                # 라이브: 세로 점선 (front 굵게)
                p.setPen(QPen(_c, 2.2 if _is_front else 1.2, Qt.DashLine))
                p.drawLine(_dx, pt, _dx, H - pb)
            # 값 라벨 — 선택(front)된 하나만 하단축에 표시. 캡처 클릭 → 그 캡처 값만 뜸(겹침 없음).
            if _is_front:
                _lbl = f'▷ {_dms:.2f} ms'
                p.setFont(_qfont(CF_MODE, True))
                _fm = p.fontMetrics(); _tw2 = _fm.horizontalAdvance(_lbl)
                _lx = _dx + 5
                if _lx + _tw2 > W - pr: _lx = _dx - 5 - _tw2   # 오른쪽 끝이면 왼쪽으로
                _ty = H - pb + 14   # 시간축 숫자와 같은 줄
                # 불투명 배경 박스 — 그 자리 축 숫자를 덮어 글자 겹침 방지
                p.setPen(Qt.NoPen); p.setBrush(QColor(T('bg')))
                p.drawRect(_lx - 3, _ty - _fm.ascent() - 1, _tw2 + 6, _fm.height() + 2)
                p.setPen(_c); p.drawText(_lx, _ty, _lbl)
        # 커서: 선택(front) 카드 우선 → primary → 아무 extra
        _fk = self._front_extra
        if isinstance(_fk, int) and _fk != -1 and _fk in self._tf_extra:
            _ex = self._tf_extra[_fk]
            _ct = _ex.get('t'); _ch = _ex.get('h'); _cetc = _ex.get('etc_db')
        else:
            _ct = self.t_ms; _ch = self.h_raw; _cetc = self.etc_db
            if (_ct is None or _ch is None) and self._tf_extra:
                _ex = next(iter(self._tf_extra.values()))
                _ct = _ex.get('t'); _ch = _ex.get('h'); _cetc = _ex.get('etc_db')
        if pl <= self._mx <= W - pr and _ct is not None:
            cx = self._mx; t_range = max(self.t_max - self.t_min, 1.0)
            p.setPen(QPen(QColor(0, 229, 255, 60), 1, Qt.DashLine))
            p.drawLine(cx, pt, cx, H - pb)
            t_cur = self.t_min + (cx - pl) / uw * t_range
            t_arr = _ct
            if self.ir_mode == 0 and _ch is not None:
                pk = max(float(np.max(np.abs(_ch))), 1e-10)
                idx = int(np.clip(np.argmin(np.abs(t_arr - t_cur)), 0, len(_ch) - 1))
                draw_info_box(p, W, f'{t_cur:.1f} ms', f'{_ch[idx]/pk:+.3f}')
            elif self.ir_mode == 1 and _cetc is not None:
                idx = int(np.clip(np.argmin(np.abs(t_arr - t_cur)), 0, len(_cetc) - 1))
                draw_info_box(p, W, f'{t_cur:.1f} ms', f'{_cetc[idx]:+.1f} dB')
            elif self.ir_mode == 2 and _ch is not None:
                pk = max(float(np.max(np.abs(_ch))), 1e-10)
                idx = int(np.clip(np.argmin(np.abs(t_arr - t_cur)), 0, len(_ch) - 1))
                db_val = 20 * math.log10(max(abs(float(_ch[idx])) / pk, 1e-10))
                draw_info_box(p, W, f'{t_cur:.1f} ms', f'{db_val:+.1f} dB')
        p.end()


# ───────────────────────────────────────────
#  Internal Loopback 전용 Duplex 스트림 스레드
# ───────────────────────────────────────────
class TFDuplexThread(QThread):
    """출력(핑크노이즈)과 입력(마이크)을 단일 CoreAudio Duplex 스트림으로 처리.
    별도 스트림 2개로 인한 xrun/드롭아웃을 원천 제거."""
    frame_ready    = pyqtSignal(object, object)   # (ref_buf, meas_buf) — 단일 이벤트
    error_signal   = pyqtSignal(str)
    disconnected_signal = pyqtSignal(str)         # 작동 중 물리적 연결 끊김 (입력 장치)
    fade_done      = pyqtSignal()                 # 페이드인 완료 시 1회 emit → _reset_avg 트리거
    sweep_captured = pyqtSignal(object, object)   # (ref_array, meas_array) — 1-shot 캡처 완료

    def __init__(self, in_dev, out_dev, sample_rate, fft_size, pink_buf, sig_level,
                 n_out=2, out_ch=0, ref_ch=None, meas_in_ch=0, out_ch2=None):
        super().__init__()
        self.in_dev = in_dev; self.out_dev = out_dev
        self.sample_rate = sample_rate; self.fft_size = fft_size
        self._pink_buf_ref = [pink_buf]  # 리스트 참조 → 런타임 버퍼 교체 지원
        self._sig_level_ref = [sig_level]
        self._buf_changed = [False]       # 버퍼 교체 시 포지션 리셋 플래그
        self.out_ch = out_ch; self.out_ch2 = out_ch2; self.running = False
        self.n_out = max(n_out, out_ch + 1, (out_ch2 + 1) if out_ch2 is not None else 0)
        # ref_ch=None → 출력 루프백(내부); ref_ch=int → 입력 채널(외부 레퍼런스)
        self.ref_ch = ref_ch; self.meas_in_ch = meas_in_ch
        self._active_stream = None   # abort()용 스트림 레퍼런스
        self._muted = False
        # 단일 스윕 캡처 상태 (arm_sweep_capture()로 활성화)
        self._sc_armed  = [False]   # True → 페이드인 완료 후 캡처 시작
        self._sc_pos    = [0]
        self._sc_len    = 0
        self._sc_buf_ref  = None
        self._sc_buf_meas = None

    def arm_sweep_capture(self, sweep_len):
        """단일 스윕 캡처 모드 활성화 — 페이드인 완료 직후 정확히 sweep_len 샘플 캡처."""
        self._sc_buf_ref  = np.zeros(sweep_len, dtype=np.float32)
        self._sc_buf_meas = np.zeros(sweep_len, dtype=np.float32)
        self._sc_len      = sweep_len
        self._sc_pos[0]   = 0
        self._sc_armed[0] = True

    def swap_buf(self, new_buf):
        """재생 중 버퍼 교체 (신호 타입 변경 시 호출)."""
        self._pink_buf_ref[0] = new_buf
        self._buf_changed[0] = True

    def mute(self):
        self._muted = True

    def unmute(self):
        self._muted = False

    def run(self):
        self.running = True
        # 같은 장치면 작은 버퍼, 다른 장치(내부 mic+스피커 등)면 큰 버퍼로 클럭 오차 흡수
        if self.in_dev == self.out_dev:
            blocksize = min(self.fft_size // 4, 2048)
        else:
            blocksize = min(self.fft_size // 4, 4096)
        ref_buf  = np.zeros(self.fft_size, dtype=np.float32)
        meas_buf = np.zeros(self.fft_size, dtype=np.float32)
        out_blk  = np.zeros(blocksize, dtype=np.float32)   # 사전 할당 — 콜백 내 메모리 할당 금지
        _ref_blk = np.zeros(blocksize, dtype=np.float32)   # 페이드 전 신호 사전 할당
        pos_r = [0]
        pb_r = self._pink_buf_ref; lv_r = self._sig_level_ref; bc_r = self._buf_changed
        n_in = (self.meas_in_ch + 1) if self.ref_ch is None else max(self.ref_ch, self.meas_in_ch) + 1
        # 50ms 페이드인 — 스트림 첫 시작/unmute 시 클릭 방지
        _fade_frames = int(self.sample_rate * 0.05)
        _ramp = np.linspace(0.0, 1.0, _fade_frames, dtype=np.float32)
        _fade_pos = [0]        # 0 = 페이드 시작, >= _fade_frames = 풀 볼륨
        _fade_emitted = [False]  # fade_done 시그널 1회만 emit
        # 단일 스윕 캡처 — arm_sweep_capture() 호출 후 활성화됨
        _sc_armed = self._sc_armed; _sc_pos = self._sc_pos

        _xrun_cnt = [0]
        _wd_last = [time.monotonic()]   # watchdog: 입력 장치 USB 제거 감지
        _wd_got = [False]   # 첫 콜백 수신 여부 — 시작 지연을 끊김으로 오판 방지
        def cb(indata, outdata, frames, ti, status):
            try:
                _wd_last[0] = time.monotonic(); _wd_got[0] = True   # 콜백 살아있음 갱신
                if status: _xrun_cnt[0] += 1  # 콜백 내 I/O 금지 — xrun 카운트만
                if not self.running:
                    outdata[:] = 0; return
                lvl = lv_r[0]   # 매 콜백마다 최신 레벨 읽기
                if bc_r[0]: pos_r[0] = 0; bc_r[0] = False  # 버퍼 교체 → 포지션 리셋
                pb = pb_r[0]; pn = len(pb)  # 매 콜백마다 최신 버퍼 읽기
                pp = pos_r[0]; rem = frames; op = 0
                while rem > 0:
                    av = pn - pp; tk = min(rem, av)
                    out_blk[op:op+tk] = pb[pp:pp+tk] * lvl; op += tk; pp = (pp+tk) % pn; rem -= tk
                pos_r[0] = pp
                outdata[:frames, :] = 0
                if self._muted:
                    # -140 dBFS 수준의 신호로 M4 USB 장치 idle 방지 (완전히 무음)
                    outdata[:frames, self.out_ch] = out_blk[:frames] * 1e-7
                    _fade_pos[0] = 0           # unmute 시 페이드인 재시작
                    _fade_emitted[0] = False   # unmute 후 fade_done 재emit 허용
                    return
                # 페이드 전 신호를 레퍼런스용으로 먼저 복사 (루프백 모드에서 정확한 레퍼런스 확보)
                np.copyto(_ref_blk[:frames], out_blk[:frames])
                fp = _fade_pos[0]
                if fp < _fade_frames:
                    tf = min(frames, _fade_frames - fp)
                    out_blk[:tf] *= _ramp[fp:fp + tf]
                    _fade_pos[0] = fp + frames
                elif not _fade_emitted[0]:
                    # 페이드인 완료 첫 순간 → GUI 스레드에서 _reset_avg() 호출
                    _fade_emitted[0] = True
                    self.fade_done.emit()
                outdata[:frames, self.out_ch] = out_blk[:frames]
                if self.out_ch2 is not None and self.out_ch2 < outdata.shape[1]:
                    outdata[:frames, self.out_ch2] = out_blk[:frames]
                ref_buf[:-frames] = ref_buf[frames:]
                if self.ref_ch is None:
                    ref_buf[-frames:] = _ref_blk[:frames]             # 내부: 페이드 전 신호 (정확한 레퍼런스)
                else:
                    ref_buf[-frames:] = indata[:frames, self.ref_ch]  # 외부: 입력 채널
                meas_buf[:-frames] = meas_buf[frames:]; meas_buf[-frames:] = indata[:frames, self.meas_in_ch]
                self.frame_ready.emit(ref_buf.copy(), meas_buf.copy())
                # 단일 스윕 캡처: 페이드인 완료 후 sweep_len 샘플을 ref/meas 동시 캡처
                if _sc_armed[0] and _fade_pos[0] >= _fade_frames:
                    pos = _sc_pos[0]
                    rem_cap = self._sc_len - pos
                    if rem_cap > 0:
                        take = min(frames, rem_cap)
                        self._sc_buf_ref [pos:pos+take] = _ref_blk[:take]
                        self._sc_buf_meas[pos:pos+take] = indata[:take, self.meas_in_ch]
                        _sc_pos[0] = pos + take
                        if _sc_pos[0] >= self._sc_len:
                            _sc_armed[0] = False
                            self.sweep_captured.emit(
                                self._sc_buf_ref.copy(), self._sc_buf_meas.copy())
            except Exception: pass

        _alog.debug(f'TFDuplexThread.run() opening sd.Stream  in={self.in_dev} out={self.out_dev} sr={self.sample_rate} bs={blocksize} n_in={n_in} ref_ch={self.ref_ch}')
        try:
            with _no_stderr():
                with sd.Stream(device=(self.in_dev, self.out_dev),
                               samplerate=self.sample_rate,
                               channels=(n_in, self.n_out),
                               blocksize=blocksize, dtype='float32',
                               callback=cb, latency='high') as stream:
                    self._active_stream = stream
                    _alog.debug(f'TFDuplexThread sd.Stream opened OK  latency={stream.latency}')
                    _wd_last[0] = time.monotonic()
                    while self.running:
                        self.msleep(10)
                        # USB 입력 제거 시 콜백 정지 → 흐르다 2초 끊기면 끊김 판단
                        # (첫 콜백 받은 뒤에만 — 같은장치 in/out 시작 지연 오판 방지)
                        if _wd_got[0] and time.monotonic() - _wd_last[0] > 2.0:
                            self.disconnected_signal.emit('device removed')
                            break
                    self.msleep(80)
        except Exception as e:
            _alog.error(f'TFDuplexThread sd.Stream FAILED: {e}')
            self.error_signal.emit(str(e))
        finally:
            self._active_stream = None

    def stop(self):
        self.running = False
        s = self._active_stream
        if s is not None:
            try: s.abort(ignore_errors=True)   # 즉시 장치 해제
            except Exception:
                try: s.close(ignore_errors=True)
                except Exception: pass
        if not self.wait(3000):
            _alog.warning('TFDuplexThread stop(): wait timeout — stream forced abort')


# ───────────────────────────────────────────
#  Delay Finder Dialog
# ───────────────────────────────────────────
class _DelayAdvancedDialog(QDialog):
    def __init__(self, parent=None, speed_ms=343.0):
        super().__init__(parent)
        self.setWindowTitle('Advanced Settings'); _apply_dark_titlebar(self)
        self.setFixedSize(300, 140)
        self.setStyleSheet(f'background:{T("bg2")};color:{T("text")};')
        lay = QVBoxLayout(self); lay.setContentsMargins(16,16,16,16); lay.setSpacing(10)
        row = QHBoxLayout()
        row.addWidget(QLabel('Speed of Sound:'))
        self._spin = QDoubleSpinBox()
        self._spin.setRange(300.0, 400.0); self._spin.setDecimals(1)
        self._spin.setSingleStep(0.5); self._spin.setValue(speed_ms)
        self._spin.setSuffix(' m/s'); self._spin.setFixedWidth(100)
        self._spin.setStyleSheet(f'background:{T("panel")};color:{T("text")};'
                                  f'border:1px solid {T("border")};border-radius:5px;padding:2px 6px;')
        row.addWidget(self._spin); lay.addLayout(row)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept); btns.rejected.connect(self.reject)
        btns.setStyleSheet(ss_dialog_btns())
        lay.addWidget(btns)

    def speed(self):
        return self._spin.value()


class SweepConfigDialog(QDialog):
    """스윕 신호 설정 팝업 (시간·주파수 구간)."""
    def __init__(self, parent, dur=10, f_lo=20.0, f_hi=20000.0):
        super().__init__(parent)
        self.setWindowTitle('Sweep Settings'); _apply_dark_titlebar(self)
        self.setModal(True)
        self.setFixedWidth(280)
        bg = T('bg2'); bd = T('border'); tx = T('text'); td = T('text_dim'); ac = T('accent')
        self.setStyleSheet(
            f'QDialog{{background:{bg};color:{tx};border:1px solid {bd};border-radius:10px;}}'
            f'QLabel{{color:{tx};font-size:12px;}}'
            f'QDoubleSpinBox,QSpinBox{{background:{T("panel")};color:{tx};'
            f'border:1px solid {bd};border-radius:6px;padding:3px 8px;font-size:12px;}}'
            f'QDoubleSpinBox::up-button,QDoubleSpinBox::down-button,'
            f'QSpinBox::up-button,QSpinBox::down-button{{width:0;border:none;}}'
            f'QPushButton{{background:{T("panel")};color:{tx};border:1px solid {bd};'
            f'border-radius:6px;padding:5px 14px;font-size:12px;}}'
            f'QPushButton:hover{{border-color:{ac};color:{ac};}}'
            f'QRadioButton{{color:{tx};font-size:12px;spacing:6px;}}'
            f'QRadioButton::indicator{{width:14px;height:14px;border-radius:7px;'
            f'border:1px solid {bd};}}'
            f'QRadioButton::indicator:checked{{background:{ac};border-color:{ac};}}'
        )
        lay = QVBoxLayout(self); lay.setSpacing(12); lay.setContentsMargins(18, 16, 18, 16)

        # 제목
        title = QLabel('Sweep Configuration')
        title.setStyleSheet(f'color:{tx};font-size:13px;font-weight:bold;')
        lay.addWidget(title)

        def _row(label, widget):
            h = QHBoxLayout(); h.setSpacing(8)
            lbl = QLabel(label); lbl.setFixedWidth(100)
            lbl.setStyleSheet(f'color:{td};font-size:11px;')
            h.addWidget(lbl); h.addWidget(widget, 1)
            return h

        # 지속 시간
        self._dur_spin = QSpinBox()
        self._dur_spin.setRange(1, 60); self._dur_spin.setValue(int(dur))
        self._dur_spin.setSuffix('  s'); self._dur_spin.setAlignment(Qt.AlignCenter)
        lay.addLayout(_row('Duration', self._dur_spin))

        # 시작 주파수
        self._flo_spin = QDoubleSpinBox()
        self._flo_spin.setRange(10.0, 20000.0); self._flo_spin.setDecimals(0)
        self._flo_spin.setValue(f_lo); self._flo_spin.setSuffix('  Hz')
        self._flo_spin.setSingleStep(10); self._flo_spin.setAlignment(Qt.AlignCenter)
        lay.addLayout(_row('Start Freq', self._flo_spin))

        # 끝 주파수
        self._fhi_spin = QDoubleSpinBox()
        self._fhi_spin.setRange(100.0, 24000.0); self._fhi_spin.setDecimals(0)
        self._fhi_spin.setValue(f_hi); self._fhi_spin.setSuffix('  Hz')
        self._fhi_spin.setSingleStep(100); self._fhi_spin.setAlignment(Qt.AlignCenter)
        lay.addLayout(_row('End Freq', self._fhi_spin))

        # 스윕 방향
        dir_h = QHBoxLayout(); dir_h.setSpacing(12)
        dir_lbl = QLabel('Direction'); dir_lbl.setFixedWidth(100)
        dir_lbl.setStyleSheet(f'color:{td};font-size:11px;')
        self._rb_up   = QRadioButton('Low → High'); self._rb_up.setChecked(True)
        self._rb_down = QRadioButton('High → Low')
        dir_h.addWidget(dir_lbl)
        dir_h.addWidget(self._rb_up); dir_h.addWidget(self._rb_down)
        lay.addLayout(dir_h)

        # 구분선
        sep = QFrame(); sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f'color:{bd};'); lay.addWidget(sep)

        # OK / Cancel
        btn_h = QHBoxLayout(); btn_h.setSpacing(8)
        ok_btn = QPushButton('Apply')
        ok_btn.setStyleSheet(ss_btn_primary())
        cancel_btn = QPushButton('Cancel')
        cancel_btn.setStyleSheet(ss_btn_neutral())
        ok_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
        btn_h.addStretch(); btn_h.addWidget(cancel_btn); btn_h.addWidget(ok_btn)
        lay.addLayout(btn_h)

    @property
    def duration(self): return self._dur_spin.value()
    @property
    def f_lo(self): return max(10.0, min(self._flo_spin.value(), self._fhi_spin.value() - 10))
    @property
    def f_hi(self): return max(self.f_lo + 10, self._fhi_spin.value())
    @property
    def ascending(self): return self._rb_up.isChecked()


class DelayFinderDialog(QDialog):
    _result_sig = pyqtSignal(float)

    def __init__(self, tw, parent=None):
        super().__init__(parent)
        self._tw = tw
        self._speed_ms = 343.0
        self._measured_ms = None
        self._tick_count = 0
        self._prog_timer = None
        self.setWindowTitle('Delay Finder'); _apply_dark_titlebar(self)
        self.setFixedSize(460, 280)
        self.setStyleSheet(f'background:{T("bg2")};color:{T("text")};')
        self._build_ui()
        self._result_sig.connect(self._on_result)
        self._start_find()

    def _build_ui(self):
        lay = QVBoxLayout(self); lay.setContentsMargins(16,14,16,14); lay.setSpacing(8)

        # Progress bar
        self._progress = QProgressBar()
        self._progress.setRange(0, 100); self._progress.setValue(0)
        self._progress.setFixedHeight(16); self._progress.setTextVisible(False)
        self._progress.setStyleSheet(
            f'QProgressBar{{background:{T("panel")};border:1px solid {T("border")};border-radius:4px;}}'
            f'QProgressBar::chunk{{background:#4db6ff;border-radius:3px;}}')
        lay.addWidget(self._progress)

        # FFT info row + ETC checkbox
        info_row = QHBoxLayout(); info_row.setSpacing(10)
        self._fft_lbl = QLabel('FFT Size: —')
        self._fft_lbl.setStyleSheet(f'color:{T("text_dim")};font-size:11px;')
        info_row.addWidget(self._fft_lbl, 1)
        self._etc_chk = QCheckBox('ETC')
        self._etc_chk.setStyleSheet(f'color:{T("text")};font-size:11px;')
        self._etc_chk.stateChanged.connect(self._on_etc_changed)
        info_row.addWidget(self._etc_chk)
        lay.addLayout(info_row)

        # Delay readout grid
        grid = QGridLayout(); grid.setSpacing(6)
        hdr_style  = f'color:{T("text_dim")};font-size:10px;font-weight:bold;'
        val_style  = f'color:{T("text")};font-size:11px;font-weight:bold;'
        dlta_style = f'color:{T("green")};font-size:11px;font-weight:bold;'
        lbl_style  = f'color:{T("text")};font-size:11px;'
        for col, txt in enumerate(['', 'ms', 'ft', 'm']):
            lbl = QLabel(txt); lbl.setAlignment(Qt.AlignCenter); lbl.setStyleSheet(hdr_style)
            grid.addWidget(lbl, 0, col)
        rows_def = [
            ('Measured Delay',         '_meas_ms',   '_meas_ft',   '_meas_m',   False),
            ('Current Delay Setting',  '_cur_ms',    '_cur_ft',    '_cur_m',    False),
            ('Delta Delay',            '_delta_ms',  '_delta_ft',  '_delta_m',  True),
        ]
        for r, (name, ms_attr, ft_attr, m_attr, is_delta) in enumerate(rows_def, start=1):
            vstyle = dlta_style if is_delta else val_style
            nl = QLabel(name); nl.setStyleSheet(lbl_style); grid.addWidget(nl, r, 0)
            for c, attr in enumerate([ms_attr, ft_attr, m_attr], start=1):
                lbl = QLabel('—'); lbl.setAlignment(Qt.AlignCenter); lbl.setStyleSheet(vstyle)
                setattr(self, attr + '_lbl', lbl); grid.addWidget(lbl, r, c)
        sep = QFrame(); sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f'color:{T("border")};'); lay.addWidget(sep)
        lay.addLayout(grid)

        lay.addStretch()

        # Buttons
        btn_row = QHBoxLayout(); btn_row.setSpacing(6)
        btn_style = ss_btn_neutral()   # 다이얼로그 버튼 통일
        self.insert_btn   = QPushButton('Insert');     self.insert_btn.setEnabled(False)
        self.find_btn     = QPushButton('Find Delay')
        self.advanced_btn = QPushButton('Advanced')
        self.cancel_btn   = QPushButton('Cancel')
        for b in (self.insert_btn, self.find_btn, self.advanced_btn, self.cancel_btn):
            b.setStyleSheet(btn_style); btn_row.addWidget(b)
        self.find_btn.setStyleSheet(ss_btn_primary())   # 주동작 강조
        self.insert_btn.clicked.connect(self._on_insert)
        self.find_btn.clicked.connect(self._on_find_delay)
        self.advanced_btn.clicked.connect(self._on_advanced)
        self.cancel_btn.clicked.connect(self.reject)
        lay.addLayout(btn_row)

        self._refresh_fft_label()

    def _refresh_fft_label(self):
        tw = self._tw
        fs = tw.fft_size; sr = tw.sample_rate
        size_k = fs // 1024
        dur_ms = round(fs / sr * 1000.0, 1)
        n_avg = tw._n_avg
        self._fft_lbl.setText(f'FFT Size: {size_k}k / {dur_ms}ms  (Avg: {n_avg})')

    def _start_find(self):
        if not self._tw._running:
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.information(self, 'Delay Finder', '먼저 Start를 누르고 신호가 들어오면 사용하세요.')
            return
        self._tick_count = 0
        self._progress.setValue(0)
        self.find_btn.setEnabled(False)
        self.insert_btn.setEnabled(False)
        if self._prog_timer is not None:
            self._prog_timer.stop()
        self._prog_timer = QTimer(self)
        self._prog_timer.timeout.connect(self._tick)
        self._prog_timer.start(100)

    def _tick(self):
        self._tick_count += 1
        self._progress.setValue(min(self._tick_count * 5, 100))
        self._refresh_fft_label()
        if self._tick_count >= 20:
            self._prog_timer.stop()
            self._do_compute()

    def _do_compute(self):
        import threading
        from PyQt5.QtWidgets import QMessageBox
        tw = self._tw
        with QMutexLocker(tw._mutex):
            cross  = tw._cross_acc.copy()  if tw._cross_acc  is not None else None
            auto_x = tw._auto_acc_x.copy() if tw._auto_acc_x is not None else None
        if cross is None or auto_x is None:
            self.find_btn.setEnabled(True)
            sig_on = (tw._duplex_thread is not None and tw._duplex_thread.isRunning() and not tw._duplex_thread._muted) or \
                     (tw._sig_stream is not None)
            if not sig_on:
                QMessageBox.information(self, 'Delay Finder',
                    '신호가 감지되지 않았습니다.\nPlay(신호 발생기)를 켜고 다시 시도하세요.')
            else:
                QMessageBox.information(self, 'Delay Finder',
                    '아직 데이터가 쌓이지 않았습니다.\n신호가 입력되고 있는지 확인 후 다시 시도하세요.')
            return
        fft_size = tw.fft_size; sr = tw.sample_rate

        def _worker():
            H = cross / np.maximum(auto_x, 1e-30)
            h = np.fft.irfft(H, n=fft_size)
            env = _hilbert_env(h)
            peak = int(np.argmax(env))
            if 0 < peak < len(env) - 1:
                y0, y1, y2 = float(env[peak-1]), float(env[peak]), float(env[peak+1])
                denom = 2*(2*y1 - y0 - y2)
                if denom > 0: peak += (y2 - y0) / denom
            if peak > fft_size // 2: peak -= fft_size
            d_ms = round(float(peak) / sr * 1000.0, 2)
            self._result_sig.emit(d_ms)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_result(self, d_ms):
        self.find_btn.setEnabled(True)
        self._measured_ms = d_ms
        m_factor  = self._speed_ms / 1000.0
        ft_factor = m_factor * 3.28084
        cur_ms = self._tw.delay_spin.value()
        delta_ms = d_ms - cur_ms
        self._meas_ms_lbl.setText(f'{d_ms:.2f}')
        self._meas_ft_lbl.setText(f'{d_ms * ft_factor:.2f}')
        self._meas_m_lbl.setText(f'{d_ms * m_factor:.2f}')
        self._cur_ms_lbl.setText(f'{cur_ms:.2f}')
        self._cur_ft_lbl.setText(f'{cur_ms * ft_factor:.2f}')
        self._cur_m_lbl.setText(f'{cur_ms * m_factor:.2f}')
        self._delta_ms_lbl.setText(f'{delta_ms:+.2f}')
        self._delta_ft_lbl.setText(f'{delta_ms * ft_factor:+.2f}')
        self._delta_m_lbl.setText(f'{delta_ms * m_factor:+.2f}')
        self.insert_btn.setEnabled(True)
        self._refresh_fft_label()

    def _on_insert(self):
        if self._measured_ms is not None:
            d_ms = self._measured_ms
            self._tw.delay_spin.setValue(d_ms)
            self._tw.mag_cvs.fit_y()   # 보정 IR: 뷰는 건드리지 않음 (다른 카드 불변)
        self.accept()

    def _on_find_delay(self):
        self._start_find()

    def _on_advanced(self):
        dlg = _DelayAdvancedDialog(self, self._speed_ms)
        if dlg.exec_() == QDialog.Accepted:
            self._speed_ms = dlg.speed()
            if self._measured_ms is not None:
                self._on_result(self._measured_ms)

    def _on_etc_changed(self, state):
        mode = 1 if state == Qt.Checked else 0
        self._tw.ir_cvs.set_mode(mode)

    def closeEvent(self, e):
        if self._prog_timer is not None and self._prog_timer.isActive():
            self._prog_timer.stop()
        super().closeEvent(e)


# ───────────────────────────────────────────
#  전체 카드 딜레이 파인더 (L키)
# ───────────────────────────────────────────
class AllDelayFinderDialog(QDialog):
    """L키: 활성화된 모든 카드 딜레이를 동시에 찾아 표시."""
    _results_sig = pyqtSignal(list)   # [(label, pair_idx_enc, d_ms), ...]

    def __init__(self, tw, parent=None):
        super().__init__(parent)
        self._tw = tw
        self._results = []
        self._tick_count = 0
        self._prog_timer = None
        self.setWindowTitle('Delay Finder — All Channels'); _apply_dark_titlebar(self)
        self.setFixedWidth(500)
        self.setStyleSheet(f'background:{T("bg2")};color:{T("text")};')
        self._build_ui()
        self._results_sig.connect(self._on_results)
        self._start_find()

    def _build_ui(self):
        import math as _math2
        lay = QVBoxLayout(self); lay.setContentsMargins(16,14,16,14); lay.setSpacing(8)

        self._progress = QProgressBar()
        self._progress.setRange(0,100); self._progress.setValue(0)
        self._progress.setFixedHeight(14); self._progress.setTextVisible(False)
        self._progress.setStyleSheet(
            f'QProgressBar{{background:{T("panel")};border:1px solid {T("border")};border-radius:4px;}}'
            f'QProgressBar::chunk{{background:#4db6ff;border-radius:3px;}}')
        lay.addWidget(self._progress)

        # 결과 테이블 헤더
        hdr_style = f'color:{T("text_dim")};font-size:10px;font-weight:bold;'
        val_style = f'color:{T("text")};font-size:11px;'
        g = QGridLayout(); g.setSpacing(5)
        for col, txt in enumerate(['Card', 'Measured', 'Current', 'Delta']):
            l = QLabel(txt); l.setAlignment(Qt.AlignCenter); l.setStyleSheet(hdr_style)
            g.addWidget(l, 0, col)
        sep = QFrame(); sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f'color:{T("border")};')
        g.addWidget(sep, 1, 0, 1, 4)
        self._grid = g; self._grid_row_offset = 2
        self._row_widgets = []   # [(card_lbl, meas_lbl, cur_lbl, delta_lbl)]
        lay.addLayout(g)
        lay.addStretch()

        btn_row = QHBoxLayout(); btn_row.setSpacing(6)
        btn_s = ss_btn_neutral()   # 다이얼로그 버튼 통일
        self._insert_btn = QPushButton('Insert All'); self._insert_btn.setEnabled(False)
        self._find_btn   = QPushButton('Find Again')
        self._cancel_btn = QPushButton('Cancel')
        for b in (self._insert_btn, self._find_btn, self._cancel_btn):
            b.setStyleSheet(btn_s); btn_row.addWidget(b)
        self._find_btn.setStyleSheet(ss_btn_primary())   # 주동작 강조
        self._insert_btn.clicked.connect(self._on_insert_all)
        self._find_btn.clicked.connect(self._start_find)
        self._cancel_btn.clicked.connect(self.reject)
        lay.addLayout(btn_row)

    def _start_find(self):
        if not self._tw._running:
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.information(self, 'Delay Finder',
                '먼저 Start를 누르고 신호가 들어오면 사용하세요.')
            return
        self._results = []
        self._insert_btn.setEnabled(False)
        self._tick_count = 0; self._progress.setValue(0)
        # 행 초기화
        for ws in self._row_widgets:
            for w in ws: w.setText('—')
        if self._prog_timer: self._prog_timer.stop()
        self._prog_timer = QTimer(self)
        self._prog_timer.timeout.connect(self._tick)
        self._prog_timer.start(100)

    def _tick(self):
        self._tick_count += 1
        self._progress.setValue(min(self._tick_count * 5, 100))
        if self._tick_count >= 20:
            self._prog_timer.stop(); self._do_compute()

    def _do_compute(self):
        import threading, math as _m
        tw = self._tw
        # 활성화된 pair 수집
        pairs = []
        if not getattr(tw, '_primary_deleted', False):
            if tw._level_cards and tw._level_cards[0]._display_on:
                pairs.append((-1, 'Card 1', None, None))  # (enc, label, cross, auto_x)
        for i, pair in enumerate(tw._extra_pairs):
            if not pair.get('display', False): continue
            p_meas_idx = pair['meas_cb'].currentData()
            ref_idx = tw.ref_cb.currentData()
            if p_meas_idx is not None and ref_idx is not None and p_meas_idx != ref_idx:
                pairs.append((i, f'Card {i+2}', 'cross_device', None))
                continue
            cb = pair.get('meas_cb')
            dev_txt = cb.currentText() if cb else '?'
            ch_cb = pair.get('meas_ch_cb')
            ch_txt = ch_cb.currentText() if ch_cb else '?'
            pairs.append((i, f'Card {i+2}', None, None))

        # 기존 행 재사용 또는 추가
        val_style = f'color:{T("text")};font-size:11px;'
        dim_style = f'color:{T("text_dim")};font-size:11px;'
        while len(self._row_widgets) < len(pairs):
            r = self._grid_row_offset + len(self._row_widgets)
            ws = []
            for c in range(4):
                l = QLabel('—'); l.setAlignment(Qt.AlignCenter); l.setStyleSheet(val_style)
                self._grid.addWidget(l, r, c); ws.append(l)
            self._row_widgets.append(ws)

        # 라벨 설정
        for idx, (enc, label, cross_flag, _) in enumerate(pairs):
            if idx < len(self._row_widgets):
                self._row_widgets[idx][0].setText(label)

        # 누적값 수집
        tasks = []
        with QMutexLocker(tw._mutex):
            for enc, label, cross_flag, _ in pairs:
                if cross_flag == 'cross_device':
                    tasks.append((enc, label, None, None))
                    continue
                if enc == -1:
                    cross = tw._cross_acc.copy() if tw._cross_acc is not None else None
                    auto_x = tw._auto_acc_x.copy() if tw._auto_acc_x is not None else None
                else:
                    acc = tw._extra_pair_acc[enc] if enc < len(tw._extra_pair_acc) else None
                    cross = acc['cross'].copy() if acc else None
                    auto_x = acc['auto_x'].copy() if acc else None
                tasks.append((enc, label, cross, auto_x))

        fft_size = tw.fft_size; sr = tw.sample_rate

        def _worker():
            out = []
            for enc, label, cross, auto_x in tasks:
                if cross is None:
                    out.append((label, enc, None)); continue
                H = cross / np.maximum(auto_x, 1e-30)
                h = np.fft.irfft(H, n=fft_size)
                env = _hilbert_env(h)
                peak = int(np.argmax(env))
                if 0 < peak < len(env) - 1:
                    y0, y1, y2 = float(env[peak-1]), float(env[peak]), float(env[peak+1])
                    denom = 2*(2*y1 - y0 - y2)
                    if denom > 0: peak += (y2 - y0) / denom
                if peak > fft_size // 2: peak -= fft_size
                d_ms = round(float(peak) / sr * 1000.0, 2)
                out.append((label, enc, d_ms))
            self._results_sig.emit(out)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_results(self, results):
        self._results = results
        tw = self._tw
        val_s  = f'color:{T("text")};font-size:11px;'
        g_s    = f'color:{T("green")};font-size:11px;font-weight:bold;'
        dim_s  = f'color:{T("text_dim")};font-size:11px;'
        any_valid = False
        for idx, (label, enc, d_ms) in enumerate(results):
            if idx >= len(self._row_widgets): break
            ws = self._row_widgets[idx]
            if d_ms is None:
                ws[1].setText('N/A'); ws[1].setStyleSheet(dim_s)
                ws[2].setText('—');   ws[3].setText('—')
                continue
            # current delay
            if enc == -1:
                cur = tw.delay_ms
            else:
                cur = tw._extra_pairs[enc].get('delay_ms', 0.0) if enc < len(tw._extra_pairs) else 0.0
            delta = d_ms - cur
            ws[1].setText(f'{d_ms:.2f} ms'); ws[1].setStyleSheet(val_s)
            ws[2].setText(f'{cur:.2f} ms');  ws[2].setStyleSheet(val_s)
            ws[3].setText(f'{delta:+.2f} ms')
            ws[3].setStyleSheet(g_s if abs(delta) < 1.0 else val_s)
            any_valid = True
        self._insert_btn.setEnabled(any_valid)
        self.adjustSize()

    def _on_insert_all(self):
        tw = self._tw
        for label, enc, d_ms in self._results:
            if d_ms is None: continue
            if enc == -1:
                if tw._level_cards and hasattr(tw._level_cards[0], '_delay_spin'):
                    tw._level_cards[0]._delay_spin.setValue(d_ms)
            else:
                if enc < len(tw._extra_pairs):
                    card = tw._extra_pairs[enc].get('card')
                    if card and hasattr(card, 'set_delay'):
                        card.set_delay(d_ms)
                        tw._extra_pairs[enc]['delay_ms'] = d_ms
        self.accept()

    def closeEvent(self, e):
        if self._prog_timer and self._prog_timer.isActive():
            self._prog_timer.stop()
        super().closeEvent(e)


# ───────────────────────────────────────────
#  TF Average 선택 다이얼로그
# ───────────────────────────────────────────
class _TFAverageDialog(QDialog):
    def __init__(self, captures, parent=None):
        super().__init__(parent)
        self.setWindowTitle('TF Average'); _apply_dark_titlebar(self)
        self.setModal(True)
        self.setMinimumWidth(280)
        self.setWindowFlags(Qt.Dialog | Qt.WindowCloseButtonHint)

        bg = T('bg2'); fg = T('text'); accent = T('accent')
        brd = T('border')
        self.setStyleSheet(
            f'QDialog{{background:{bg};}} QLabel{{color:{fg};}} '
            f'QPushButton{{border:1px solid {brd};border-radius:5px;'
            f'background:{T("bg3")};color:{fg};font-size:12px;padding:4px 16px;}}'
            f'QPushButton:hover{{background:{accent};color:#fff;}}')

        lay = QVBoxLayout(self)
        lay.setSpacing(4); lay.setContentsMargins(12, 10, 12, 10)

        _chk_ss = (
            f'QPushButton{{font-size:13px;font-weight:bold;border:2px solid #5060a0;'
            f'border-radius:4px;background:#0c0c20;color:#4da6ff;padding:0;min-width:20px;max-width:20px;min-height:20px;max-height:20px;}}'
            f'QPushButton:checked{{border:2px solid #4da6ff;background:#0c1830;}}')
        self._checks = []
        for i, cap in enumerate(captures):
            row = QWidget()
            rl = QHBoxLayout(row); rl.setContentsMargins(4, 2, 4, 2); rl.setSpacing(8)
            chk = QPushButton('')
            chk.setCheckable(True); chk.setChecked(False)
            chk.setStyleSheet(_chk_ss)
            chk.toggled.connect(lambda c, b=chk: b.setText('✓' if c else ''))
            dot = QLabel('■')
            dot.setStyleSheet(f'color:{cap.get("color","#fff")};font-size:14px;')
            dot.setFixedWidth(18)
            name = QLabel(cap.get('label', f'Capture {i+1}'))
            name.setStyleSheet(f'color:{fg};font-size:13px;')
            rl.addWidget(chk); rl.addWidget(dot); rl.addWidget(name, 1)
            lay.addWidget(row)
            self._checks.append((i, chk))

        sep2 = QFrame(); sep2.setFrameShape(QFrame.HLine)
        sep2.setStyleSheet(f'background:{brd};max-height:1px;'); lay.addWidget(sep2)

        btn_lay = QHBoxLayout(); btn_lay.setSpacing(8)
        self._cancel_btn = QPushButton('취소'); self._cancel_btn.setStyleSheet(ss_btn_neutral())
        self._ok_btn = QPushButton('Average'); self._ok_btn.setStyleSheet(ss_btn_primary())
        self._cancel_btn.clicked.connect(self.reject)
        self._ok_btn.clicked.connect(self.accept)
        btn_lay.addStretch()
        btn_lay.addWidget(self._cancel_btn)
        btn_lay.addWidget(self._ok_btn)
        lay.addLayout(btn_lay)

    def selected_indices(self):
        return [i for i, chk in self._checks if chk.isChecked()]


# ───────────────────────────────────────────
#  TF 단축키 이벤트 필터 (G / L)
# ───────────────────────────────────────────
class _TFKeyFilter(QObject):
    """TF 패널이 화면에 보일 때(isVisible=True)만 G/L 키 처리.
    QShortcut 방식은 포커스에 의존 → 이벤트 필터로 대체."""
    def __init__(self, tf_win):
        super().__init__(tf_win)
        self._tf = tf_win

    def eventFilter(self, obj, event):
        from PyQt5.QtCore import QEvent
        if event.type() == QEvent.KeyPress and self._tf.isVisible():
            key = event.key()
            mods = event.modifiers()
            if mods == Qt.NoModifier:
                if key == Qt.Key_G:
                    self._tf.sig_on_btn.click()
                    return True
                elif key == Qt.Key_L:
                    self._tf._find_all_delays()
                    return True
        return False


# ───────────────────────────────────────────
#  Transfer Function 창
# ───────────────────────────────────────────
class TransferFunctionWindow(QWidget):
    _find_result_sig      = pyqtSignal(float)           # primary delay finder 결과
    _find_pair_result_sig = pyqtSignal(int, float)      # (pair_idx_enc, d_ms) per-card

    def __init__(self, parent=None, settings=None, embedded=False):
        self.embedded = embedded
        if embedded:
            super().__init__(parent)
        else:
            super().__init__(parent, Qt.Window)
            self.setWindowTitle('SPECTRA — Transfer Function')
            self.setMinimumSize(1020, 570)
        self._settings = settings or {}
        self._tf_primary_name = self._settings.get('tf_primary_name', '')  # primary 카드 사용자 이름
        self.sample_rate = 48000; self.fft_size = 16384
        self.smooth_bpo = 3; self.averaging_sec = 2.0
        self.delay_ms = 0.0; self.phase_mode = 0; self.coh_blank = 0.5
        self._ref_capture_idx = None; self._delta_on = False  # Δ 비교 상태
        self._stabilizing = False; self._stable_timer = None  # 안정화 캡쳐 상태
        self._mutex = QMutex()
        self._engine = None   # 공유 오디오 엔진 (MainWindow가 주입) — TF 측정입력을 장치당 단일 스트림으로
        self._ref_thread = None; self._meas_thread = None; self._sync_thread = None
        self._extra_pairs = []        # Smaart 방식: 추가 Ref+Meas 쌍 목록
        self._front_pair = None       # 분석 화면 맨 앞 곡선: None=primary, int=pair idx
        self._extra_pair_threads = [] # 쌍마다 (sync_thread, ref_thread, meas_thread)
        self._extra_pair_acc = []     # 쌍마다 {cross, auto_x, auto_y, n} or None
        self._mc_threads = {}         # {device_idx: (thread, routing_list)}
        self._last_ref_fft = None; self._last_meas_fft = None
        self._last_ref_rms = 0.0; self._last_meas_rms = 0.0
        self._cross_acc = None; self._auto_acc_x = None
        self._auto_acc_y = None; self._n_avg = 0
        self._avg_target = 23; self._running = False
        self._gen_freeze = False; self._gen_off_timer = None
        self._sig_stream = None; self._duplex_thread = None; self._sig_lvl_ref = None
        import threading as _thr
        self._int_ref_buf = np.zeros(131072, dtype=np.float32)  # 32768×4, 순환 버퍼
        self._int_ref_pos = [0]   # 뮤터블 컨테이너, SigGen 콜백과 공유
        self._int_ref_filled = False  # OutputStream 시작 후 fft_size 샘플 채워질 때까지 대기
        self._int_ref_lock = _thr.Lock()
        self._pink_buf = _gen_pink_noise(self.sample_rate * 10)
        self._audio_file_buf = None   # 사용자가 로드한 오디오 파일 버퍼
        self._sweep_dur = 10          # 스윕 설정: 지속 시간(초)
        self._sweep_f_lo = 20.0       # 스윕 시작 주파수(Hz)
        self._sweep_f_hi = 20000.0    # 스윕 끝 주파수(Hz)
        self._sweep_asc  = True       # True=Low→High, False=High→Low
        self._sig_level_lin = 10 ** (-20 / 20)
        self._tf_captures = []
        self._on_captures_changed = None
        self._current_tf_group = ''
        import threading as _thr2
        self._mon_active = False
        self._mon_ref_stream = None; self._mon_meas_stream = None
        self._mon_ref_rms = 0.0; self._mon_meas_rms = 0.0
        self._mon_lock = _thr2.Lock()
        self._monitor_threads = {}   # 입력 레벨 모니터(분석 미실행 시) dev -> MultiChannelAudioThread
        self._monitor_chmap = {}     # dev -> {ch: card}
        self._build_ui(); self._load_devices(); self._restore_tf_extra_pairs()
        self._find_result_sig.connect(self._apply_find_result)
        self._find_pair_result_sig.connect(self._apply_find_pair_result)
        self._timer = QTimer(self); self._timer.timeout.connect(self._render); self._timer.start(100)
        # G/L 단축키: QShortcut 대신 앱 레벨 이벤트 필터 사용 (포커스/상태 무관)
        self._key_filter = _TFKeyFilter(self)
        QApplication.instance().installEventFilter(self._key_filter)
        QTimer.singleShot(0, self._restore_tf_captures)

    # ── UI ──────────────────────────────────
    def _build_ui(self):
        from PyQt5.QtWidgets import QDoubleSpinBox, QSlider
        root = QVBoxLayout(self); root.setSpacing(0); root.setContentsMargins(0,0,0,0)

        # 헤더 — self._hdr로 저장해야 embedded 모드에서 GC로 인한 C++ 객체 삭제 방지
        self._hdr = QWidget(); self._hdr.setFixedHeight(40)
        self._hdr.setStyleSheet(f'background:{T("bg2")};')
        hl = QHBoxLayout(self._hdr); hl.setContentsMargins(16,0,16,0)
        logo = QLabel()
        logo.setTextFormat(Qt.RichText)
        logo.setText(f'<span style="font-size:14px;font-weight:700;color:{T("accent")};'
                     f'letter-spacing:3px;">SPECTRA</span>'
                     f'&nbsp;&nbsp;<span style="font-size:11px;color:{T("text_dim")};">'
                     f'Transfer Function</span>')
        hl.addWidget(logo); hl.addStretch()
        self.status_lbl = QLabel('● Standby')
        self.status_lbl.setStyleSheet(ss_text(FS_BODY))
        hl.addWidget(self.status_lbl)
        self.avg_lbl = QLabel('')
        self.avg_lbl.setStyleSheet(ss_text(FS_SM) + 'margin-left:14px;')
        hl.addWidget(self.avg_lbl)
        if not self.embedded:
            root.addWidget(self._hdr)

        # 바디 (캔버스 + 우측 패널)
        body = QWidget(); bl = QHBoxLayout(body); bl.setSpacing(0); bl.setContentsMargins(0,0,0,0)

        self.cvs_w = cvs_w = QSplitter(Qt.Vertical)
        cvs_w.setHandleWidth(7)                 # 3탭 스플리터 핸들 폭 통일
        cvs_w.setStyleSheet(_splitter_qss())    # 공통 구분선 스타일
        self.ir_cvs = TFIRCanvas()
        self.phase_cvs = TFPhaseCanvas(); self.mag_cvs = TFMagCanvas()
        # 커서 동기화: 한 캔버스에서 마우스 움직이면 양쪽 모두 크로스헤어 표시
        self.phase_cvs.cursor_x_changed.connect(self.mag_cvs.set_peer_cursor)
        self.mag_cvs.cursor_x_changed.connect(self.phase_cvs.set_peer_cursor)
        self.phase_cvs.cursor_left.connect(self.mag_cvs.clear_peer_cursor)
        self.mag_cvs.cursor_left.connect(self.phase_cvs.clear_peer_cursor)
        cvs_w.addWidget(self.ir_cvs)
        cvs_w.addWidget(self.phase_cvs); cvs_w.addWidget(self.mag_cvs)
        cvs_w.setCollapsible(0, False); cvs_w.setCollapsible(1, False); cvs_w.setCollapsible(2, False)
        cvs_w.setSizes([200, 400, 600])   # 기본 비율 IR:Phase:Mag ≈ 1:2:3 (사용자 선호)
        bl.addWidget(cvs_w, 1)

        # 우측 패널
        self.rp = QWidget(); self.rp.setFixedWidth(260)
        self.rp.setStyleSheet(f'background:{T("bg2")};')
        rl = QVBoxLayout(self.rp); rl.setContentsMargins(10,10,10,10); rl.setSpacing(8)

        # 신호 발생기
        sg = QGroupBox('Signal Generator')
        sgl = QVBoxLayout(sg); sgl.setSpacing(5); sgl.setContentsMargins(8,14,8,8)
        tr = QHBoxLayout(); tr.setSpacing(4); tr.setContentsMargins(2,0,0,0)
        self.sig_pink_btn  = _CheckBtn('Pink');  self.sig_pink_btn.setChecked(True)
        self.sig_white_btn = _CheckBtn('White')
        self.sig_sweep_btn = _CheckBtn('Sweep')
        def _sig_gen_active():
            """제네레이터 스트림이 열려 있으면 True (재생/뮤트 무관)."""
            return (self._duplex_thread is not None and self._duplex_thread.isRunning()) or \
                   (self._sig_stream is not None)

        def _stop_if_playing():
            """신호 타입 변경 시 스트림을 완전 종료하고 버튼을 ▶ Play로 리셋."""
            if _sig_gen_active():
                self._stop_sig_gen()
                self.sig_on_btn.setChecked(False)
                self.sig_on_btn.setText('Play'); _apply_txn(self.sig_on_btn, False)

        def _sel_pink():
            _stop_if_playing()
            self.sig_pink_btn.setChecked(True); self.sig_white_btn.setChecked(False)
            self.sig_sweep_btn.setChecked(False); self.sig_file_btn.setChecked(False)
        def _sel_white():
            _stop_if_playing()
            self.sig_white_btn.setChecked(True); self.sig_pink_btn.setChecked(False)
            self.sig_sweep_btn.setChecked(False); self.sig_file_btn.setChecked(False)
        def _sel_sweep():
            _stop_if_playing()
            dlg = SweepConfigDialog(self,
                                    dur=self._sweep_dur,
                                    f_lo=self._sweep_f_lo,
                                    f_hi=self._sweep_f_hi)
            if dlg.exec_() == QDialog.Accepted:
                self._sweep_dur  = dlg.duration
                self._sweep_f_lo = dlg.f_lo
                self._sweep_f_hi = dlg.f_hi
                self._sweep_asc  = dlg.ascending
                self.sig_sweep_btn.setChecked(True)
                self.sig_pink_btn.setChecked(False)
                self.sig_white_btn.setChecked(False)
                self.sig_file_btn.setChecked(False)
            else:
                # Cancel → 선택 상태 복원
                if not any([self.sig_pink_btn.isChecked(),
                            self.sig_white_btn.isChecked(),
                            self.sig_file_btn.isChecked()]):
                    self.sig_pink_btn.setChecked(True)
                self.sig_sweep_btn.setChecked(False)
        self.sig_pink_btn.clicked.connect(_sel_pink)
        self.sig_white_btn.clicked.connect(_sel_white)
        self.sig_sweep_btn.clicked.connect(_sel_sweep)
        tr.addWidget(self.sig_pink_btn); tr.addWidget(self.sig_white_btn)
        tr.addWidget(self.sig_sweep_btn); tr.addStretch()
        sgl.addLayout(tr)
        # 오디오 파일 재생 버튼 (클릭 → 파일 선택)
        self.sig_file_btn = _CheckBtn('File…'); self.sig_file_btn.setIcon(_icon('folder'))
        self.sig_file_btn.clicked.connect(self._pick_audio_file)
        sgl.addWidget(self.sig_file_btn)
        lr = QHBoxLayout(); lr.setSpacing(4)
        lr.addWidget(QLabel('Level:'))
        self.sig_lvl_btn_m = QPushButton('−'); self.sig_lvl_btn_m.setFixedSize(28, 28)
        self.sig_lvl_sp = QDoubleSpinBox()
        self.sig_lvl_sp.setRange(-99.0, 0.0); self.sig_lvl_sp.setSingleStep(1.0)
        self.sig_lvl_sp.setValue(-20.0); self.sig_lvl_sp.setSuffix(' dB')
        self.sig_lvl_sp.setDecimals(1); self.sig_lvl_sp.setFixedWidth(88)
        self.sig_lvl_sp.setKeyboardTracking(False)   # 타이핑 중 즉시 적용 방지
        self.sig_lvl_sp.valueChanged.connect(self._sig_level_changed)
        self.sig_lvl_btn_p = QPushButton('+'); self.sig_lvl_btn_p.setFixedSize(28, 28)
        self.sig_lvl_btn_m.clicked.connect(self.sig_lvl_sp.stepDown)
        self.sig_lvl_btn_p.clicked.connect(self.sig_lvl_sp.stepUp)
        lr.addWidget(self.sig_lvl_btn_m); lr.addWidget(self.sig_lvl_sp); lr.addWidget(self.sig_lvl_btn_p)
        sgl.addLayout(lr)
        or_ = QHBoxLayout(); or_.setSpacing(0); or_.setContentsMargins(0,0,0,0)
        _out_lbl = QLabel('Out:'); _out_lbl.setAlignment(Qt.AlignVCenter | Qt.AlignLeft); _out_lbl.setFixedWidth(28)
        or_.addWidget(_out_lbl)
        or_.addSpacing(2)
        self.sig_out_cb = RoundComboBox(); self.sig_out_cb.setFixedWidth(62); self.sig_out_cb.setFixedHeight(28)
        self.sig_out_cb._max_display_chars = 3
        self.sig_out_ch_cb  = RoundComboBox(); self.sig_out_ch_cb.setFixedWidth(52); self.sig_out_ch_cb.setFixedHeight(28)
        self.sig_out_ch2_cb = RoundComboBox(); self.sig_out_ch2_cb.setFixedWidth(52); self.sig_out_ch2_cb.setFixedHeight(28)
        self.sig_out_ch2_cb.setToolTip('두 번째 출력 채널 (Off = 단일 채널)')
        or_.addWidget(self.sig_out_cb)
        or_.addSpacing(4)
        or_.addWidget(self.sig_out_ch_cb)
        _plus_lbl = QLabel('+'); _plus_lbl.setAlignment(Qt.AlignVCenter | Qt.AlignHCenter); _plus_lbl.setFixedWidth(14)
        or_.addSpacing(2)
        or_.addWidget(_plus_lbl)
        or_.addSpacing(2)
        or_.addWidget(self.sig_out_ch2_cb)
        or_.addStretch()
        sgl.addLayout(or_)
        self.sig_out_cb.currentIndexChanged.connect(self._sig_out_device_changed)
        self.sig_out_ch2_cb.currentIndexChanged.connect(lambda _: self._save_tf_devices())
        self.sig_on_btn = QPushButton('Play  [G]'); _apply_txn(self.sig_on_btn, False); self.sig_on_btn.setCheckable(True)
        self.sig_on_btn.setStyleSheet(f'background:{T("panel")};color:{T("text_dim")};'
                                       f'border:1px solid {T("border")};padding:4px;border-radius:{RADIUS_CTRL}px;font-weight:bold;')
        self.sig_on_btn.clicked.connect(self._toggle_sig_gen); sgl.addWidget(self.sig_on_btn)
        rl.addWidget(sg)

        # 입력 장치
        # ── Measurement 패널: 공유 Ref 섹션 + N개 Meas 채널 카드 ──
        mp = QGroupBox('Measurement')
        mpl = QVBoxLayout(mp); mpl.setContentsMargins(8,14,8,8); mpl.setSpacing(6)

        self._mon_btn = None

        # ── 공유 Reference 섹션 ──
        ref_sec = QFrame()
        ref_sec.setStyleSheet(f'background:transparent;')
        ref_sl = QVBoxLayout(ref_sec); ref_sl.setContentsMargins(0,0,0,0); ref_sl.setSpacing(3)
        ref_hdr = QHBoxLayout(); ref_hdr.setSpacing(4)
        _ref_dot = QLabel('▸ Reference')
        _ref_dot.setStyleSheet(ss_text(FS_XS, bold=True))
        ref_hdr.addWidget(_ref_dot); ref_hdr.addStretch()
        self._ref_db_lbl = QLabel('—')
        self._ref_db_lbl.setStyleSheet(ss_text(FS_XS))
        ref_hdr.addWidget(self._ref_db_lbl)
        ref_sl.addLayout(ref_hdr)
        # Ref VU bar
        ref_vu_row = QHBoxLayout(); ref_vu_row.setContentsMargins(0,0,0,0); ref_vu_row.setSpacing(4)
        _r_lbl = QLabel('R'); _r_lbl.setFixedWidth(10)
        _r_lbl.setStyleSheet(ss_text(FS_XS))
        self._ref_vu_bar = _HorizBarVU()
        ref_vu_row.addWidget(_r_lbl); ref_vu_row.addWidget(self._ref_vu_bar, 1)
        ref_sl.addLayout(ref_vu_row)
        # Ref 드롭다운
        self.ref_cb = RoundComboBox(); self.ref_ch_cb = RoundComboBox()
        self.ref_cb.currentIndexChanged.connect(self._ref_device_changed)
        self.ref_ch_cb.currentIndexChanged.connect(self._on_input_setting_changed)
        ref_row = QHBoxLayout(); ref_row.setContentsMargins(0,0,0,0); ref_row.setSpacing(3)
        _rl = QLabel('In'); _rl.setFixedWidth(14)
        _rl.setStyleSheet(ss_text(FS_XS))
        self.ref_cb.setMinimumWidth(100); self.ref_ch_cb.setMinimumWidth(44)
        ref_row.addWidget(_rl); ref_row.addWidget(self.ref_cb, 1); ref_row.addWidget(self.ref_ch_cb)
        ref_sl.addLayout(ref_row)
        mpl.addWidget(ref_sec)

        mpl.addWidget(hsep())

        # ── Meas 카드 목록 ──
        self._level_cards = []
        self._cards_layout = QVBoxLayout(); self._cards_layout.setSpacing(6)
        self._cards_layout.setContentsMargins(0, 0, 0, 0)

        # 프라이머리 Meas 드롭다운
        self.meas_cb = RoundComboBox(); self.meas_ch_cb = RoundComboBox()
        self.meas_cb.currentIndexChanged.connect(self._meas_device_changed)
        self.meas_ch_cb.currentIndexChanged.connect(self._on_input_setting_changed)

        # 프라이머리 카드 생성
        primary_card = _MeasCard(1, T('green'), deletable=False)
        primary_card.add_device_row(self.meas_cb, self.meas_ch_cb)
        primary_card.start_clicked.connect(lambda: self._on_meas_start(None))
        primary_card.stop_clicked.connect(lambda: self._on_meas_stop(None))
        primary_card.find_delay_clicked.connect(lambda: self._find_delay_for_pair(None))
        primary_card.delete_clicked.connect(self._tf_delete_primary)
        primary_card.selected.connect(lambda c=primary_card: self._on_card_select(c))
        primary_card.set_name(self._tf_primary_name)
        primary_card.renamed.connect(lambda name: self._on_tf_renamed(None, name))
        primary_card.graph_toggled.connect(self._on_primary_graph_toggle)
        # backward-compat: delay spin synced to self.delay_ms
        primary_card._delay_spin.valueChanged.connect(self._on_delay_changed)
        self._level_cards.append(primary_card)
        self._cards_layout.addWidget(primary_card)
        # 끝에 stretch → 카드를 항상 위(Reference 바로 아래)로 정렬. 없으면 단일 카드가
        # QBoxLayout 기본 동작으로 세로 가운데 정렬됨. 추가 카드는 이 stretch 앞에 insert.
        self._cards_layout.addStretch(1)

        self._vu_ref = _VUProxy(); self._vu_meas = _VUProxy()
        self._vu_ref._card_fn  = self._on_ref_vu
        self._vu_meas._card_fn = primary_card.set_meas

        cards_container = QWidget()
        cards_container.setLayout(self._cards_layout)   # 이미 만들어 둔 _cards_layout 재사용
        cards_container.setStyleSheet('background:transparent;')
        self._cards_scroll = QScrollArea()
        self._cards_scroll.setWidget(cards_container)
        self._cards_scroll.setWidgetResizable(True)
        self._cards_scroll.setFrameShape(QFrame.NoFrame)
        self._cards_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._cards_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._cards_scroll.viewport().setStyleSheet('background:transparent;')
        self._cards_scroll.setStyleSheet(
            'QScrollArea{background:transparent;border:none;}'
            'QScrollBar:vertical{width:6px;background:transparent;margin:0;}'
            'QScrollBar::handle:vertical{background:#48484A;border-radius:3px;min-height:40px;}'
            'QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}')
        mpl.addWidget(self._cards_scroll, 1)   # stretch=1 → 남는 세로 공간을 카드 영역이 차지

        self._extra_pairs_w = QWidget(); self._extra_pairs_w.hide()
        self._extra_pairs_l = QVBoxLayout(self._extra_pairs_w)
        self._extra_pairs_l.setSpacing(0); self._extra_pairs_l.setContentsMargins(0,0,0,0)

        # Add Measurement Channel 버튼
        self._add_pair_btn = _DashedAddButton('＋  Add Measurement Channel')
        self._add_pair_btn.setFixedHeight(26)
        self._add_pair_btn.setCursor(Qt.PointingHandCursor)
        self._add_pair_btn.clicked.connect(self._tf_add_pair)
        mpl.addWidget(self._add_pair_btn)
        self.sig_out_ch_cb.currentIndexChanged.connect(lambda _: self._save_tf_devices())
        rl.addWidget(mp, 1)          # 그룹박스가 Signal Generator 아래 남은 세로 공간을 모두 차지
        # 그래프↔우측패널 구분선 — Spectrum infoPanel border-left와 통일(1px)
        self._rp_sep = QFrame(); self._rp_sep.setFrameShape(QFrame.VLine); self._rp_sep.setFixedWidth(1)
        self._rp_sep.setStyleSheet(f'background:{_sep_line_color()};border:none;')
        bl.addWidget(self._rp_sep)
        bl.addWidget(self.rp)
        root.addWidget(body, 1)

        # 하단 툴바
        tb = QWidget(); tb.setFixedHeight(46); tb.setObjectName('tf_tb')
        # embedded 모드에서는 toolbar_wrapper가 그라디언트 제공 → tb는 transparent
        # standalone 모드에서는 _apply_theme에서 별도 처리
        tl = QHBoxLayout(tb); tl.setContentsMargins(8,6,8,6); tl.setSpacing(4)   # 3탭 툴바 메트릭 통일(Spectrum 기준)

        def _vs():
            f=QFrame(); f.setFrameShape(QFrame.VLine); f.setFixedWidth(1); f.setFixedHeight(22)
            f.setStyleSheet(f'color:{T("border")};background:{T("border")};'); return f   # Spectrum/Stereo _vsep와 통일
        def _lb(t):
            l=QLabel(t); l.setStyleSheet(ss_text(FS_BODY))
            l.setAlignment(Qt.AlignVCenter | Qt.AlignHCenter); return l

        _g = QColor(T('accent')); _gr,_gg,_gb = _g.red(),_g.green(),_g.blue()
        self._drawer_btn = _DrawerToggleBtn()
        self._drawer_btn.setChecked(False)
        tl.addWidget(self._drawer_btn)
        tl.addSpacing(4)
        # Start 버튼 — 제너레이터 자동 연동으로 대체됨. 숨김 처리(코드 참조용으로만 존재)
        self.start_btn = QPushButton('Start'); _apply_txn(self.start_btn, False); self.start_btn.setFixedWidth(92); self.start_btn.setFixedHeight(34)
        self.start_btn.setStyleSheet(
            f'background:qlineargradient(x1:0,y1:0,x2:0,y2:1,'
            f'stop:0 rgba({_gr},{_gg},{_gb},55),stop:1 rgba({_gr},{_gg},{_gb},22));'
            f'color:{T("accent")};border:1px solid rgba({_gr},{_gg},{_gb},140);'
            f'padding:3px 12px;border-radius:{RADIUS_CTRL}px;font-weight:bold;')
        self.start_btn.clicked.connect(self._toggle)
        self.start_btn.hide()  # 제너레이터 ON/OFF가 자동으로 start/stop 제어

        tl.addWidget(_lb('FFT'))
        self.fft_cb = RoundComboBox(); self.fft_cb.addItems(TF_FFT_LABELS); self.fft_cb.setCurrentIndex(2)
        self.fft_cb._align_center = True
        self.fft_cb.setFixedWidth(58); self.fft_cb.setFixedHeight(30)
        self.fft_cb.currentIndexChanged.connect(self._fft_changed); tl.addWidget(self.fft_cb); tl.addSpacing(10)

        tl.addWidget(_lb('Avg'))
        self.avg_cb = RoundComboBox()
        self.avg_cb.addItems([f'{s}s' if s!=int(s) else f'{int(s)}s' for s in TF_AVG_SEC])
        self.avg_cb.setCurrentIndex(2)
        self.avg_cb._align_center = True
        self.avg_cb.setFixedWidth(52); self.avg_cb.setFixedHeight(30)
        self.avg_cb.currentIndexChanged.connect(self._avg_changed); tl.addWidget(self.avg_cb); tl.addSpacing(10)

        tl.addWidget(_lb('Smooth'))
        self.sm_cb = RoundComboBox(); self.sm_cb.addItems(TF_SMOOTH_LABELS); self.sm_cb.setCurrentIndex(5)
        self.sm_cb._align_center = True
        self.sm_cb.setFixedWidth(62); self.sm_cb.setFixedHeight(30)
        self.sm_cb.currentIndexChanged.connect(self._smooth_changed); tl.addWidget(self.sm_cb); tl.addSpacing(10)

        # delay_spin: primary 카드의 delay_spin과 동기화 (DelayFinderDialog 호환용)
        self.delay_spin = QDoubleSpinBox()
        self.delay_spin.setRange(-2000,2000); self.delay_spin.setDecimals(2)
        self.delay_spin.setSingleStep(0.5); self.delay_spin.setValue(0.0)
        self.delay_spin.setSuffix(' ms'); self.delay_spin.setFixedWidth(80); self.delay_spin.setFixedHeight(30)
        self.delay_spin.setButtonSymbols(QDoubleSpinBox.NoButtons)
        self.delay_spin.setAlignment(Qt.AlignCenter)
        self.delay_spin.setStyleSheet(ss_input(FS_BODY, RADIUS_CTRL))
        self.delay_spin.hide()  # 툴바 딜레이 숨김 — 카드별 딜레이 사용
        self.delay_spin.valueChanged.connect(self._on_delay_changed)
        self.find_btn = QPushButton('Find  [L]'); self.find_btn.setIcon(_icon('search')); self.find_btn.setFixedWidth(96); self.find_btn.setFixedHeight(30)
        self.find_btn.clicked.connect(self._find_all_delays); tl.addWidget(self.find_btn); tl.addSpacing(10)

        self.tf_cap_btn = QPushButton('Capture'); self.tf_cap_btn.setFixedWidth(68); self.tf_cap_btn.setFixedHeight(30)
        self.tf_cap_btn.setToolTip('현재 TF 스냅샷 캡처 (Mag + Phase + IR)')
        self.tf_cap_btn.clicked.connect(lambda: self._do_tf_capture(prompt=True)); tl.addWidget(self.tf_cap_btn)
        # 토글 버튼 전용 스타일 — ON 시 확실히 채워져 보이게 (버튼별 직접 지정 → 전역 스타일에 안 묻힘)
        _toggle_ss = (
            'QPushButton{background:#2C2C2E;color:#9A9AA0;border:1px solid #48484A;'
            'border-radius:7px;font-size:14px;font-weight:bold;}'
            'QPushButton:hover{border-color:#4E7DF0;}'
            'QPushButton:checked{background:#4E7DF0;color:#FFFFFF;border:1px solid #4E7DF0;}')
        self.delta_btn = QPushButton(''); self.delta_btn.setIcon(_icon('delta')); self.delta_btn.setFixedWidth(30); self.delta_btn.setFixedHeight(30)
        self.delta_btn.setCheckable(True)
        self.delta_btn.setStyleSheet(_toggle_ss)
        self.delta_btn.setToolTip('Delta 비교 — 기준(R로 지정한 캡쳐) 대비 차이 표시')
        self.delta_btn.toggled.connect(self._set_delta)
        tl.addWidget(self.delta_btn)
        self.tf_stable_btn = QPushButton(''); self.tf_stable_btn.setIcon(_icon('hourglass')); self.tf_stable_btn.setFixedWidth(30); self.tf_stable_btn.setFixedHeight(30)
        self.tf_stable_btn.setCheckable(True)
        self.tf_stable_btn.setStyleSheet(_toggle_ss)
        self.tf_stable_btn.setToolTip('안정화 캡쳐 — 평균 수렴 + 코히런스 안정 후 자동 캡쳐')
        tl.addWidget(self.tf_stable_btn); tl.addSpacing(10)

        tl.addWidget(_lb('IR'))
        self.ir_cb = RoundComboBox(); self.ir_cb.addItems(TF_IR_MODES); self.ir_cb.setCurrentIndex(0)
        self.ir_cb._align_center = True
        self.ir_cb.setFixedWidth(58); self.ir_cb.setFixedHeight(30)
        self.ir_cb.currentIndexChanged.connect(self._ir_mode_changed)
        tl.addWidget(self.ir_cb); tl.addSpacing(10)

        tl.addWidget(_lb('Phase'))
        self.phase_cb = RoundComboBox(); self.phase_cb.addItems(TF_PHASE_MODES)
        self.phase_cb._align_center = True
        self.phase_cb.setFixedWidth(96); self.phase_cb.setFixedHeight(30)
        self.phase_cb.currentIndexChanged.connect(self._phase_mode_changed)
        tl.addWidget(self.phase_cb)
        tl.addStretch()
        # 우측 패널(rp) 표시/숨김 토글 + 저장 상태 복원
        self._tf_panel_btn = _RightPanelToggleBtn()
        self._tf_panel_btn.clicked.connect(self._toggle_tf_panel)
        _tpv = bool(self._settings.get('tf_panel_visible', True))
        self._tf_panel_btn.setChecked(_tpv)
        self.rp.setVisible(_tpv); self._rp_sep.setVisible(_tpv)
        tl.addWidget(self._tf_panel_btn)
        self.tb = tb   # MainWindow가 embedded 시 sub_stack에 넣을 수 있도록 저장
        if not self.embedded:
            root.addWidget(tb)

    # ── 장치 로드 ────────────────────────────
    def _load_devices(self):
        import threading, queue as _q
        result = _q.Queue()
        def _q_fn():
            try: result.put(('ok', sd.query_devices()))
            except Exception as e: result.put(('err', str(e)))
        t = threading.Thread(target=_q_fn, daemon=True); t.start(); t.join(timeout=3.0)
        if result.empty(): return
        status, payload = result.get_nowait()
        if status == 'err': return
        ext = ['usb','focusrite','scarlett','steinberg','motu','behringer','yamaha','audient','apollo','zoom','tascam','rme']
        # 로드 전체를 복원 모드로 감싼다 — 기본 선택/핸들러가 _save_tf_devices() 로
        # 저장값을 덮어쓰는 것을 막아야 "마지막 사용 장치"가 보존된다 (클로버 방지).
        self._restoring_devices = True
        try:
            self.ref_cb.clear(); self.meas_cb.clear(); self.sig_out_cb.clear()
            self.ref_cb.addItem('Internal (SigGen)', None)
            for i, d in enumerate(payload):
                tag = ''
                if d['max_input_channels'] >= 1:
                    self.ref_cb.addItem(f'{tag}{d["name"]}', i)
                    self.meas_cb.addItem(f'{tag}{d["name"]}', i)
                if d['max_output_channels'] >= 1:
                    self.sig_out_cb.addItem(f'{tag}{d["name"]}', i)
            if self.meas_cb.count() > 1: self.meas_cb.setCurrentIndex(1)
            self._ref_device_changed(self.ref_cb.currentIndex())
            self._meas_device_changed(self.meas_cb.currentIndex())
            self._sig_out_device_changed()
            # 추가 Meas 채널 콤보박스 갱신 (Ref는 공유 섹션으로 이동)
            for pair in getattr(self, '_extra_pairs', []):
                meas_cb_ = pair.get('meas_cb')
                if meas_cb_ is None: continue
                cur_data = meas_cb_.currentData(); meas_cb_.blockSignals(True); meas_cb_.clear()
                for i, d in enumerate(payload):
                    if d['max_input_channels'] >= 1:
                        meas_cb_.addItem(d['name'], i)
                for j in range(meas_cb_.count()):
                    if meas_cb_.itemData(j) == cur_data:
                        meas_cb_.setCurrentIndex(j); break
                meas_cb_.blockSignals(False)
                self._update_ch_cb(pair['meas_ch_cb'], meas_cb_.currentData())
            # 마지막 사용 장치 및 채널 복원 (오염되지 않은 저장값을 읽음)
            for cb, key in [(self.ref_cb, 'tf_ref_device'), (self.meas_cb, 'tf_meas_device'), (self.sig_out_cb, 'tf_out_device')]:
                saved = self._settings.get(key, '')
                for i in range(cb.count()):
                    if self._strip_star(cb.itemText(i)) == saved:
                        cb.setCurrentIndex(i); break
            # 장치 변경 후 채널 CB가 재구성됐으므로 저장된 채널 복원
            for cb, key, default in [(self.ref_ch_cb, 'tf_ref_ch', 0), (self.meas_ch_cb, 'tf_meas_ch', 0),
                                      (self.sig_out_ch_cb, 'tf_out_ch', 0), (self.sig_out_ch2_cb, 'tf_out_ch2', None)]:
                saved_ch = self._settings.get(key, default)
                for i in range(cb.count()):
                    if cb.itemData(i) == saved_ch:
                        cb.setCurrentIndex(i); break
        finally:
            self._restoring_devices = False
        # 주의: 여기서 _save_tf_devices() 를 호출하면, 저장 장치가 미연결이라 기본값으로
        # 폴백된 경우 그 기본값을 저장해 "마지막 장치"를 잃는다 → 절대 저장하지 않음.
        # 저장은 오직 사용자가 직접 콤보를 바꿀 때만(_*_device_changed 경유) 일어난다.

    def _update_ch_cb(self, cb_widget, dev_idx):
        """장치의 최대 입력 채널 수에 맞게 채널 콤보박스 갱신."""
        cb_widget.blockSignals(True); cb_widget.clear()
        if dev_idx is None:
            cb_widget.addItem('—', 0)
        else:
            try:
                n = int(sd.query_devices(dev_idx)['max_input_channels'])
            except Exception:
                n = 1
            for i in range(max(n, 1)):
                cb_widget.addItem(f'Ch {i+1}', i)
        cb_widget.blockSignals(False)

    def _ref_device_changed(self, _=None):
        _alog.info(f'TF REF 디바이스 변경  device="{self.ref_cb.currentText()}"')
        self._update_ch_cb(self.ref_ch_cb, self.ref_cb.currentData())
        self._save_tf_devices()
        self._reconfigure_audio()

    def _meas_device_changed(self, _=None):
        _alog.info(f'TF MEAS 디바이스 변경  device="{self.meas_cb.currentText()}"')
        self._update_ch_cb(self.meas_ch_cb, self.meas_cb.currentData())
        self._save_tf_devices()
        self._reconfigure_audio()

    def _on_input_setting_changed(self, _=None):
        """ref/meas 채널 등 입력 설정 변경 — 저장 후 실행 중이면 재구성."""
        self._save_tf_devices()
        self._reconfigure_audio()

    def _reconfigure_audio(self):
        """실행 중(분석 또는 제너레이터 재생) 입력 장치/채널이 바뀌면 엔진을 안전하게
        하드 정지 후 이전 상태로 재시작. 연속 변경은 디바운스로 한 번만 적용."""
        if getattr(self, '_restoring_devices', False):
            return
        playing = bool(getattr(self, 'sig_on_btn', None) and self.sig_on_btn.isChecked())
        if not (self._running or playing):
            return   # 엔진 비활성 → 다음 Start/Play 때 새 설정으로 자연히 열림
        # 디바운스: 콤보를 빠르게 여러 번 바꿔도 마지막 한 번만 재구성
        self._reconf_pending = True
        QTimer.singleShot(180, self._do_reconfigure_audio)

    def _do_reconfigure_audio(self):
        if not getattr(self, '_reconf_pending', False):
            return
        self._reconf_pending = False
        playing = bool(getattr(self, 'sig_on_btn', None) and self.sig_on_btn.isChecked())
        analysis = self._running
        if not (analysis or playing):
            return
        _alog.info(f'TF 오디오 재구성  analysis={analysis} playing={playing}')
        # 하드 정지 — Fix A 덕분에 스트림이 확실히 닫혀 장치가 해제됨
        self._stop_analysis()
        self._stop_sig_gen()
        # 이전 상태로 복원
        if playing:
            self.sig_on_btn.blockSignals(True)
            self.sig_on_btn.setChecked(True)
            self.sig_on_btn.blockSignals(False)
            self._on_gen_started()
            self._start_sig_gen()
            QTimer.singleShot(600, self._start_active_pairs)
        elif analysis:
            QTimer.singleShot(150, self._start_active_pairs)

    def _sig_out_device_changed(self, _=None):
        sig_was_playing = getattr(self, 'sig_on_btn', None) and self.sig_on_btn.isChecked()
        if sig_was_playing:
            self._stop_sig_gen()
        dev_idx = self.sig_out_cb.currentData()
        try: n = int(sd.query_devices(dev_idx)['max_output_channels']) if dev_idx is not None else 0
        except Exception: n = 2
        for cb in (self.sig_out_ch_cb, self.sig_out_ch2_cb):
            cb.blockSignals(True); cb.clear()
            if dev_idx is None:
                cb.addItem('—', 0)
            else:
                if cb is self.sig_out_ch2_cb:
                    cb.addItem('Off', None)   # 두 번째 채널 비활성 옵션
                for i in range(max(n, 1)):
                    cb.addItem(f'Ch {i+1}', i)
            cb.blockSignals(False)
        self._save_tf_devices()
        if sig_was_playing and not getattr(self, '_restoring_devices', False):
            self._start_sig_gen()

    @staticmethod
    def _strip_star(txt):
        return txt[2:] if txt.startswith('★ ') else txt

    def _toggle_tf_panel(self):
        vis = not self.rp.isVisible()
        self.rp.setVisible(vis); self._rp_sep.setVisible(vis)
        self._tf_panel_btn.setChecked(vis); self._tf_panel_btn.update()
        self._settings['tf_panel_visible'] = vis
        _save_settings(self._settings)

    def _save_tf_devices(self):
        if getattr(self, '_restoring_devices', False): return
        self._settings.update({
            'tf_ref_device': self._strip_star(self.ref_cb.currentText()),
            'tf_meas_device': self._strip_star(self.meas_cb.currentText()),
            'tf_out_device': self._strip_star(self.sig_out_cb.currentText()),
            'tf_ref_ch': self.ref_ch_cb.currentData() or 0,
            'tf_meas_ch': self.meas_ch_cb.currentData() or 0,
            'tf_out_ch': self.sig_out_ch_cb.currentData() or 0,
            'tf_out_ch2': self.sig_out_ch2_cb.currentData(),  # None = Off
        })
        _save_settings(self._settings)

    def _save_tf_extra_pairs(self):
        """추가 Meas 카드(extra pairs)의 장치/채널/딜레이를 settings 에 저장."""
        if getattr(self, '_restoring_devices', False): return
        pairs = []
        for p in self._extra_pairs:
            mcb = p.get('meas_cb'); mch = p.get('meas_ch_cb')
            pairs.append({
                'meas_device': self._strip_star(mcb.currentText()) if mcb else '',
                'meas_ch': (mch.currentData() if (mch and mch.currentData() is not None) else 0),
                'delay_ms': float(p.get('delay_ms', 0.0)),
                'name': p.get('name', ''),
                'num': p.get('num', 2),
            })
        self._settings['tf_extra_pairs'] = pairs
        self._settings['tf_primary_name'] = getattr(self, '_tf_primary_name', '')
        _save_settings(self._settings)

    def _restore_tf_extra_pairs(self):
        """시작 시 저장된 추가 카드들을 재생성·복원 (1회). _load_devices 이후 호출."""
        saved = self._settings.get('tf_extra_pairs', [])
        if not saved: return
        self._restoring_devices = True
        try:
            for entry in saved:
                self._tf_add_pair()                 # 카드+pair 생성 (현재 장치 목록 복사)
                pair = self._extra_pairs[-1]
                mcb = pair['meas_cb']; mch = pair['meas_ch_cb']
                dev_name = entry.get('meas_device', '')
                for i in range(mcb.count()):
                    if self._strip_star(mcb.itemText(i)) == dev_name:
                        mcb.setCurrentIndex(i); break
                saved_ch = entry.get('meas_ch', 0)
                for i in range(mch.count()):
                    if mch.itemData(i) == saved_ch:
                        mch.setCurrentIndex(i); break
                dly = float(entry.get('delay_ms', 0.0))
                pair['delay_ms'] = dly
                pair['card'].set_delay(dly)
                nm = entry.get('name', '')
                pair['name'] = nm
                pair['card'].set_name(nm)
                saved_num = entry.get('num')
                if saved_num:
                    pair['num'] = saved_num
                    pair['card'].set_number(saved_num)
        finally:
            self._restoring_devices = False

    # ── 시작/정지 ────────────────────────────
    def _toggle(self):
        try:
            if self._running: self._stop()
            else: self._start()
        except Exception as e:
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.warning(self, '오류', f'오디오 시작 실패:\n{e}')

    # ── 독립 레벨 모니터링 ──────────────────────────────────────────
    def _toggle_monitor(self, checked):
        self._mon_active = checked
        if checked and not self._running:
            self._start_mon_streams()
        elif not checked:
            self._stop_mon_streams()

    def _start_mon_streams(self):
        self._stop_mon_streams()
        import threading as _t
        ref_idx  = self.ref_cb.currentData()
        meas_idx = self.meas_cb.currentData()
        ref_ch   = self.ref_ch_cb.currentData()  or 0
        meas_ch  = self.meas_ch_cb.currentData() or 0
        sr = self.sample_rate

        def _make_cb(kind, ch):
            def cb(indata, frames, time, status):
                if indata.shape[1] <= ch: return
                rms = float(np.sqrt(np.mean(indata[:, ch] ** 2)))
                with self._mon_lock:
                    if kind == 'ref': self._mon_ref_rms = rms
                    else: self._mon_meas_rms = rms
            return cb

        try:
            if ref_idx is not None:
                nch = ref_ch + 1
                with _no_stderr():
                    self._mon_ref_stream = sd.InputStream(
                        device=ref_idx, channels=nch, samplerate=sr,
                        blocksize=2048, callback=_make_cb('ref', ref_ch))
                    self._mon_ref_stream.start()
        except Exception as e:
            _alog.warning(f'Mon ref stream failed: {e}')
        try:
            if meas_idx is not None:
                nch = meas_ch + 1
                with _no_stderr():
                    self._mon_meas_stream = sd.InputStream(
                        device=meas_idx, channels=nch, samplerate=sr,
                        blocksize=2048, callback=_make_cb('meas', meas_ch))
                    self._mon_meas_stream.start()
        except Exception as e:
            _alog.warning(f'Mon meas stream failed: {e}')

    def _stop_mon_streams(self):
        for attr in ('_mon_ref_stream', '_mon_meas_stream'):
            s = getattr(self, attr, None)
            if s is not None:
                try: s.stop(); s.close()
                except Exception: pass
                setattr(self, attr, None)
        for _vu in (self._vu_ref, self._vu_meas):
            _vu._db = -80.0; _vu._pk = -80.0; _vu.update()
        # 프라이머리 카드 리셋
        if hasattr(self, '_level_cards') and self._level_cards:
            self._level_cards[0].reset()

    # ── 입력 레벨 모니터 (분석 미실행 시에도 레벨미터 표시) ─────────────
    def _stop_input_monitor(self):
        for th in list(getattr(self, '_monitor_threads', {}).values()):
            try: th.chunk_ready.disconnect(); th.error_signal.disconnect()
            except Exception: pass
            try: th.stop()
            except Exception: pass
        self._monitor_threads = {}; self._monitor_chmap = {}

    def _refresh_input_monitor(self):
        """[비활성화] 별도 모니터 입력 스트림은 같은 장치의 출력/분석 스트림과 CoreAudio 충돌
        (스트림 닫힘 3초 지연 → 카드 Start 랙, 레벨 오독)을 일으켜 사용하지 않음.
        '분석 중인 카드가 1개라도 있으면' 정지·가시 카드는 meter-only 로 레벨 표시됨.
        전부 정지 상태의 모니터링은 공유 오디오 엔진(장치당 1스트림) 도입 후 가능."""
        self._stop_input_monitor()

    def _on_monitor_chunk(self, device_idx, chunk_dict):
        chmap = self._monitor_chmap.get(device_idx)
        if not chmap: return
        for ch, card in chmap.items():
            buf = chunk_dict.get(ch)
            if buf is None: continue
            try:
                if not card.is_graph_visible(): continue
                rms = float(np.sqrt(np.mean(buf ** 2)))
                if rms > 1e-9: card.set_meas(20 * _math.log10(rms))
            except RuntimeError:
                pass  # 카드 삭제됨

    # ── 추가 측정 채널 관리 ─────────────────────
    # ── 추가 Ref+Meas 쌍 관리 (Smaart 방식) ────
    def _tf_delete_primary(self):
        """Pair 1 (프라이머리) 카드 삭제."""
        if self._running: self._stop()
        # 카드 삭제 전 콤보박스를 카드에서 분리 — Qt가 카드와 함께 자식 위젯을 삭제하므로
        # setParent(None)으로 먼저 뗀 뒤 숨겨두면 C++ 객체가 살아남음
        for w in (self.ref_cb, self.ref_ch_cb, self.meas_cb, self.meas_ch_cb):
            w.setParent(None); w.hide()
        if self._level_cards:
            card = self._level_cards[0]
            self._level_cards.remove(card)
            card.setParent(None); card.deleteLater()
        self._vu_ref._card_fn = None; self._vu_meas._card_fn = None
        self._primary_deleted = True

    def _extra_idx(self, card):
        """카드 객체로 현재 _extra_pairs 인덱스 조회. 없으면 -1.
        삭제로 인덱스가 밀려도 항상 올바른 카드를 가리키도록 호출 시점에 동적 조회."""
        for i, p in enumerate(self._extra_pairs):
            if p.get('card') is card: return i
        return -1

    def _tf_add_pair(self):
        """[+ Add Measurement Channel] 클릭: 새 Meas 채널 카드 추가."""
        used = {p.get('num') for p in self._extra_pairs}
        num = 2
        while num in used: num += 1     # 가장 작은 빈 번호 (삭제 후에도 고정)
        color = _MC_COLORS[(num - 2) % len(_MC_COLORS)]

        # Meas 드롭다운만 생성 (Ref는 공유)
        meas_cb = RoundComboBox(); meas_ch_cb = RoundComboBox()

        # 현재 장치 목록 복사
        for i in range(self.meas_cb.count()):
            txt = self.meas_cb.itemText(i); dat = self.meas_cb.itemData(i)
            meas_cb.addItem(txt, dat)
        if meas_cb.count() > 0: meas_cb.setCurrentIndex(0)

        def _meas_changed(_=None): self._update_ch_cb(meas_ch_cb, meas_cb.currentData())
        # 초기 채널 목록 먼저 채움 — 시그널 연결 *전*에 해야 채움이 _reconfigure_audio 를
        # 트리거하지 않음 (카드 추가만으로 엔진 재시작 + 전체화면 다이얼로그 Space 전환 방지)
        _meas_changed()
        def _meas_dev_user_changed(_=None):
            _meas_changed()
            self._save_tf_extra_pairs()
            self._reconfigure_audio()   # 사용자가 장치 바꿀 때만 재구성 (비활성 시 no-op)
        meas_cb.currentIndexChanged.connect(_meas_dev_user_changed)
        meas_ch_cb.currentIndexChanged.connect(
            lambda _: (self._save_tf_extra_pairs(), self._reconfigure_audio()))

        # 카드 생성
        card = _MeasCard(num, color)
        card.add_device_row(meas_cb, meas_ch_cb)
        # 핸들러는 캡처한 idx 가 아니라 카드 객체로 호출 시점에 현재 인덱스를 조회
        # (삭제로 인덱스가 밀려도 항상 올바른 카드를 대상으로 — stale-index 삭제버그 방지)
        card._delay_spin.valueChanged.connect(lambda v, c=card: self._on_extra_delay_changed(self._extra_idx(c), v))
        card.delete_clicked.connect(lambda c=card: self._tf_remove_pair(self._extra_idx(c)))
        card.start_clicked.connect(lambda c=card: self._on_meas_start(self._extra_idx(c)))
        card.stop_clicked.connect(lambda c=card: self._on_meas_stop(self._extra_idx(c)))
        card.find_delay_clicked.connect(lambda c=card: self._find_delay_for_pair(self._extra_idx(c)))
        card.selected.connect(lambda c=card: self._on_card_select(c))
        card.renamed.connect(lambda name, c=card: self._on_tf_renamed(c, name))
        card.graph_toggled.connect(lambda vis, c=card: self._on_extra_graph_toggle(c, vis))
        self._level_cards.append(card)
        # 끝의 stretch 앞에 삽입 → 카드는 위로 쌓이고 빈 공간은 항상 아래로
        self._cards_layout.insertWidget(self._cards_layout.count() - 1, card)

        pair = {'meas_cb': meas_cb, 'meas_ch_cb': meas_ch_cb, 'num': num,
                'delay_ms': 0.0, 'color': color, 'row_w': None, 'card': card,
                'display': False, 'name': ''}
        self._extra_pairs.append(pair)
        self._extra_pair_threads.append((None, None, None))
        self._extra_pair_acc.append(None)
        # 기본 Stop 상태 — 사용자가 Start 눌러야 분석 시작
        self._save_tf_extra_pairs()   # 복원 중에는 가드로 no-op

    def _on_tf_renamed(self, card, txt):
        """카드 이름 변경 — card=None 이면 primary, 아니면 해당 extra pair."""
        if card is None:
            self._tf_primary_name = txt
        else:
            for p in self._extra_pairs:
                if p.get('card') is card: p['name'] = txt; break
        self._save_tf_extra_pairs()

    def _on_primary_graph_toggle(self, visible):
        """primary 카드 그래프 표시 ON/OFF — 분석은 그대로, 곡선·레벨 숨김/표시."""
        if not visible:
            self.mag_cvs.clear(); self.phase_cvs.clear(); self.ir_cvs.clear()
            if self._level_cards: self._level_cards[0].reset()   # 체크 해제 → 레벨도 숨김
        self._refresh_input_monitor()   # 모니터 채널 갱신 (체크 ON/OFF 반영)
        # 표시 ON 이면 다음 렌더 프레임에서 다시 그려짐 (_render_inner 가 is_graph_visible 확인)

    def _on_extra_graph_toggle(self, card, visible):
        """추가 카드 그래프 표시 ON/OFF — 분석은 그대로, 곡선만 숨김/표시."""
        idx = self._extra_idx(card)
        if idx < 0: return
        if not visible:
            self.mag_cvs.clear_tf_extra(idx)
            self.phase_cvs.clear_tf_extra_phase(idx)
            self.ir_cvs.clear_tf_extra(idx)
            card.reset()   # 체크 해제 → 레벨도 숨김
        self._refresh_input_monitor()   # 모니터 채널 갱신 (체크 ON/OFF 반영)

    def restyle_theme(self):
        """테마 토글(다크↔라이트) 시 측정 카드들의 인라인-구운 색을 재적용."""
        if not hasattr(self, '_cards_layout'):
            return
        for i in range(self._cards_layout.count()):
            w = self._cards_layout.itemAt(i).widget()
            if isinstance(w, _MeasCard):
                w.restyle()

    def _on_card_select(self, card):
        """카드 본문 클릭 → 해당 카드 곡선을 Mag/Phase/IR 분석 화면 맨 앞으로."""
        key = None  # primary
        for i, pr in enumerate(getattr(self, '_extra_pairs', [])):
            if pr.get('card') is card:
                key = i; break
        self._front_pair = key
        for c in self._level_cards:
            c.set_selected(c is card)
        # 카드 클릭 → 라이브 포커스(캡쳐 선택 해제 → 캡쳐 흐리게, 그 카드 곡선 밝게 맨앞)
        for cvs in (self.mag_cvs, self.phase_cvs, self.ir_cvs):
            cvs._live_on_top = True; cvs._front_idx = None
            cvs._cap_pix = None
            cvs.set_front_curve(key)   # _front_extra 설정 + update
        # 선택한 카드의 딜레이로 IR 임펄스 센터 정렬 + ▷ 숫자 표기 (각 카드 클릭 시 그 카드 기준)
        self._sync_ir_delay_marker()

    def _tf_remove_pair(self, idx):
        if idx < 0 or idx >= len(self._extra_pairs): return
        # 스레드 정리
        self._stop_extra_pair_threads(idx)
        # 캔버스 곡선 제거
        self.mag_cvs.clear_tf_extra(idx)
        self.phase_cvs.clear_tf_extra_phase(idx)
        self.ir_cvs.clear_tf_extra(idx)
        # UI 행 제거
        pair = self._extra_pairs.pop(idx)
        self._extra_pair_threads.pop(idx)
        self._extra_pair_acc.pop(idx)
        row_w = pair.get('row_w')
        if row_w is not None: row_w.setParent(None); row_w.deleteLater()
        # 통합 카드 제거
        card = pair.get('card')
        if card and hasattr(self, '_level_cards') and card in self._level_cards:
            self._level_cards.remove(card)
            card.setParent(None); card.deleteLater()
        # 남은 쌍의 캔버스 key도 idx 재정렬이 필요하므로 전부 초기화 후 _render_inner에서 재설정
        self.mag_cvs.clear_all_tf_extra(); self.phase_cvs.clear_all_tf_extra_phase()
        self.ir_cvs.clear_all_tf_extra()
        # front 선택 초기화 (인덱스 재정렬로 stale 방지) → primary 맨앞
        self._front_pair = None
        for c in self._level_cards:
            c.set_selected(False)
        for cvs in (self.mag_cvs, self.phase_cvs, self.ir_cvs):
            cvs.set_front_curve(None)
        self._save_tf_extra_pairs()
        if self._running:
            self._stop(); self._start()

    def _stop_extra_pair_threads(self, idx):
        if idx >= len(self._extra_pair_threads): return
        sync_th, ref_th, meas_th = self._extra_pair_threads[idx]
        for th in [sync_th, ref_th, meas_th]:
            if th is None: continue
            try:
                if hasattr(th, 'frame_ready'): th.frame_ready.disconnect()
                if hasattr(th, 'chunk_ready'): th.chunk_ready.disconnect()
                if hasattr(th, 'error_signal'): th.error_signal.disconnect()
            except Exception: pass
            th.stop()
        self._extra_pair_threads[idx] = (None, None, None)

    def _start(self):
        self._stop_mon_streams()   # TF 시작 전 모니터 스트림 해제 (장치 충돌 방지)
        self._stop_input_monitor() # 분석 시작 전 입력 모니터 해제 (장치당 1스트림)
        if getattr(self, '_primary_deleted', False):
            # Primary 삭제 상태 — extra pairs만 시작 (공유 ref 사용)
            self._running = True
            self.status_lbl.setText('● Running')
            self.status_lbl.setStyleSheet(f'color:{T("green")};font-size:11px;')
            p_ref_idx = self.ref_cb.currentData()
            p_ref_ch  = self.ref_ch_cb.currentData() or 0
            same_dev = {}; diff_dev = []
            for i, pair in enumerate(self._extra_pairs):
                self._extra_pair_acc[i] = None
                if not pair.get('display', False): continue
                p_meas_idx = pair['meas_cb'].currentData()
                if p_meas_idx is None: continue
                p_meas_ch = pair['meas_ch_cb'].currentData() or 0
                if p_ref_idx is not None and p_ref_idx == p_meas_idx:
                    same_dev.setdefault(p_ref_idx, []).append((i, p_ref_ch, p_meas_ch))
                else:
                    diff_dev.append((i, p_ref_idx, p_ref_ch, p_meas_idx, p_meas_ch))
            for dev, extras in same_dev.items():
                all_chs = set()
                for _i, _rc, _mc in extras: all_chs |= {_rc, _mc}
                if len(extras) == 1:
                    _i, _rc, _mc = extras[0]
                    th = _EngineSyncSource(self._engine, dev, self.sample_rate, self.fft_size, _rc, _mc)
                    th.frame_ready.connect(lambda r, m, xi=_i: self._on_extra_frame(xi, r, m), Qt.QueuedConnection)
                    th.error_signal.connect(self._on_err, Qt.QueuedConnection)
                    th.disconnected_signal.connect(self._on_tf_disconnect, Qt.QueuedConnection)
                    th.start(); self._extra_pair_threads[_i] = (th, None, None)
                else:
                    routing = [{'ref_ch': _rc, 'meas_ch': _mc,
                                'callback': lambda r, m, xi=_i: self._on_extra_frame(xi, r, m)}
                               for _i, _rc, _mc in extras]
                    for _i, _, _ in extras: self._extra_pair_threads[_i] = (None, None, None)
                    mc_th = _EngineMultiSource(self._engine, dev, self.sample_rate, self.fft_size, list(all_chs),
                                                    force_latency=('high' if (self._sig_stream is not None
                                                                   and dev == self.sig_out_cb.currentData()) else None))
                    mc_th.chunk_ready.connect(lambda d, _dv=dev: self._on_mc_chunk(_dv, d), Qt.QueuedConnection)
                    mc_th.error_signal.connect(self._on_err, Qt.QueuedConnection)
                    mc_th.disconnected_signal.connect(self._on_tf_disconnect, Qt.QueuedConnection)
                    mc_th.start(); self._mc_threads[dev] = (mc_th, routing)
            for _i, p_ref_idx2, p_ref_ch2, p_meas_idx, p_meas_ch in diff_dev:
                if p_ref_idx2 is not None and p_ref_idx2 not in self._mc_threads:
                    r_th = _EngineChannelSource(self._engine, p_ref_idx2, self.sample_rate, self.fft_size, p_ref_ch2)
                    r_th.chunk_ready.connect(lambda buf, xi=_i: self._on_extra_ref(xi, buf), Qt.QueuedConnection)
                    r_th.error_signal.connect(self._on_err, Qt.QueuedConnection)
                    r_th.disconnected_signal.connect(self._on_tf_disconnect, Qt.QueuedConnection); r_th.start()
                    self._extra_pair_threads[_i] = (None, r_th, None)
                m_th = _EngineChannelSource(self._engine, p_meas_idx, self.sample_rate, self.fft_size, p_meas_ch)
                m_th.chunk_ready.connect(lambda buf, xi=_i: self._on_extra_meas(xi, buf), Qt.QueuedConnection)
                m_th.error_signal.connect(self._on_err, Qt.QueuedConnection)
                m_th.disconnected_signal.connect(self._on_tf_disconnect, Qt.QueuedConnection); m_th.start()
                sync_th, r_th2, _ = self._extra_pair_threads[_i]
                self._extra_pair_threads[_i] = (sync_th, r_th2, m_th)
            return
        ref_idx = self.ref_cb.currentData(); meas_idx = self.meas_cb.currentData()
        _alog.info(f'TF 측정 시작  ref="{self.ref_cb.currentText()}"  meas="{self.meas_cb.currentText()}"  sr={self.sample_rate}')
        _alog.debug(f'_start()  ref_idx={ref_idx} meas_idx={meas_idx} sig_stream={self._sig_stream}')
        if meas_idx is None: return
        if self._gen_off_timer is not None:
            self._gen_off_timer.stop(); self._gen_off_timer = None
        self._gen_freeze = False
        self._reset_avg(); self._recalc_target()
        if ref_idx is None:
            _alog.debug(f'  mode=Internal Loopback  duplex={self._duplex_thread}  sig={self._sig_stream}')
            if self._duplex_thread is not None:
                # 같은 장치 TFDuplexThread 실행 중 → 스트림 재시작 없음 (zero gap)
                if self._duplex_thread._muted:
                    self._duplex_thread.unmute()   # Stop 후 재시작 시 무음 해제
                    # Play 버튼도 함께 활성화 (muted→unmuted 시 UI 동기화)
                    self.sig_on_btn.setChecked(True); self.sig_on_btn.setText('Stop'); _apply_txn(self.sig_on_btn, True)
                _alog.debug('  TFDuplexThread running → zero gap Start')
            elif self._sig_stream is not None:
                # 다른 장치 standalone OutputStream 실행 중 → meas InputStream만 추가
                # force_latency='high': 공유 하드웨어 IO 버퍼 재설정 방지 (low latency 시도 시 OutputStream 끊김)
                _alog.debug(f'  Standalone OutputStream running → opening meas AudioThread device={meas_idx}')
                meas_ch = self.meas_ch_cb.currentData() or 0
                self._meas_thread = _EngineChannelSource(self._engine, meas_idx, self.sample_rate, self.fft_size, meas_ch, force_latency='high')
                self._meas_thread.chunk_ready.connect(self._on_meas, Qt.QueuedConnection)
                self._meas_thread.error_signal.connect(self._on_err, Qt.QueuedConnection)
                self._meas_thread.disconnected_signal.connect(self._on_tf_disconnect, Qt.QueuedConnection)
                self._meas_thread.start()
            else:
                # SigGen 꺼져 있음: Play 버튼 시 _start_sig_gen() → TFDuplexThread(단일 스트림) 오픈
                # 단일 duplex 스트림 → 하드웨어 초기화 1회만 → 띠띡 클릭 없음
                _alog.debug('  SigGen not running → TFDuplexThread deferred until Play pressed')
        else:
            ref_ch  = self.ref_ch_cb.currentData()  or 0
            meas_ch = self.meas_ch_cb.currentData() or 0

            # ── 모든 pair를 장치별로 그룹화 → 스트림을 한 번만 열기 ──
            # 모든 extra pair는 공유 ref(self.ref_cb) 사용 — 동일 장치이면 MultiChannelAudioThread
            primary_active = (self._level_cards and self._level_cards[0]._display_on)

            # 장치별 채널 수집: {dev: [(pair_id, ref_ch, meas_ch)]}
            # pair_id='primary' or int
            dev_groups = {}
            if primary_active and meas_idx is not None:
                if meas_idx == ref_idx:
                    dev_groups.setdefault(ref_idx, []).append(('primary', ref_ch, meas_ch))
                else:
                    dev_groups.setdefault(ref_idx, []).append(('primary_ref_only', ref_ch, None))
                    dev_groups.setdefault(meas_idx, []).append(('primary', None, meas_ch))

            for i, pair in enumerate(self._extra_pairs):
                self._extra_pair_acc[i] = None
                if not pair.get('display', False): continue
                p_meas_idx = pair['meas_cb'].currentData()
                if p_meas_idx is None: continue
                p_meas_ch = pair['meas_ch_cb'].currentData() or 0
                if p_meas_idx == ref_idx:
                    dev_groups.setdefault(ref_idx, []).append((i, ref_ch, p_meas_ch))
                else:
                    if ref_idx is not None:
                        dev_groups.setdefault(ref_idx, []).append((f'ref_for_{i}', ref_ch, None))
                    dev_groups.setdefault(p_meas_idx, []).append((i, None, p_meas_ch))

            # 장치별 스트림 개설
            for dev, entries in dev_groups.items():
                # 같은 장치에 ref + meas 채널이 섞여있는 경우 MultiChannelAudioThread
                all_chs = set()
                for _, rc, mc in entries:
                    if rc is not None: all_chs.add(rc)
                    if mc is not None: all_chs.add(mc)
                if not all_chs: continue

                # routing: 어떤 채널 조합이 어느 콜백으로 가는지
                routing = []
                for pair_id, rc, mc in entries:
                    if isinstance(pair_id, str) and pair_id == 'primary':
                        routing.append({'ref_ch': rc, 'meas_ch': mc,
                                        'pair_idx': 'primary', 'callback': self._on_frame})
                    elif isinstance(pair_id, str) and pair_id.startswith('ref_for_'):
                        target_i = int(pair_id.split('_')[-1])
                        routing.append({'ref_ch': rc, 'meas_ch': None, '_ref_only_pair': target_i})
                    elif isinstance(pair_id, str) and pair_id == 'primary_ref_only':
                        # primary cross-device: ref 채널을 MC에서 버퍼링 → _last_ref_fft
                        routing.append({'ref_ch': rc, '_primary_ref_only': True})
                    elif isinstance(pair_id, int):
                        if mc is not None:
                            routing.append({'ref_ch': rc, 'meas_ch': mc, 'pair_idx': pair_id,
                                            'callback': lambda r, m, xi=pair_id: self._on_extra_frame(xi, r, m)})
                        # mc=None: meas 채널 없음 (ref-only entry for this device)

                has_primary_ref_only = any(isinstance(p, str) and p == 'primary_ref_only' for p, _, _ in entries)
                has_primary = any(isinstance(p, str) and p == 'primary' for p, _, _ in entries)

                if len(all_chs) == 2 and not routing:
                    # 채널은 있지만 routing 없음 (all ref-only) → AudioThread만
                    pass
                elif len(routing) == 1 and not has_primary_ref_only and not self._extra_pairs:
                    # SyncSource(ref+meas 단일 스트림 원자 캡처)는 extra 카드가 **하나도 없을 때만**.
                    # extra 카드가 존재하면(Stop 상태여도) primary 단독 SyncSource 가 raw 를
                    # 못 받아 분석 데이터가 안 뜨는 현상이 있음 → 동일 동작의 MultiSource 경로로 통일
                    # (아래 `if routing` 블록). card2 를 Start 하면 MultiSource 라 정상 동작했던 이유.
                    r = routing[0]
                    rc2 = r.get('ref_ch'); mc2 = r.get('meas_ch')
                    pair_id2 = r.get('pair_idx')
                    if rc2 is not None and mc2 is not None:
                        th = _EngineSyncSource(self._engine, dev, self.sample_rate, self.fft_size, rc2, mc2)
                        if pair_id2 == 'primary':
                            th.frame_ready.connect(self._on_frame, Qt.QueuedConnection)
                            self._sync_thread = th
                        else:
                            th.frame_ready.connect(lambda r2, m2, xi=pair_id2: self._on_extra_frame(xi, r2, m2),
                                                   Qt.QueuedConnection)
                            self._extra_pair_threads[pair_id2] = (th, None, None)
                        th.error_signal.connect(self._on_err, Qt.QueuedConnection)
                        th.disconnected_signal.connect(self._on_tf_disconnect, Qt.QueuedConnection)
                        th.start()
                        continue  # 다음 장치 처리
                if routing or has_primary_ref_only:
                    mc_th = _EngineMultiSource(self._engine, dev, self.sample_rate, self.fft_size, list(all_chs),
                                                    force_latency=('high' if (self._sig_stream is not None
                                                                   and dev == self.sig_out_cb.currentData()) else None))
                    mc_th.chunk_ready.connect(lambda d, _dv=dev: self._on_mc_chunk(_dv, d), Qt.QueuedConnection)
                    mc_th.error_signal.connect(self._on_err, Qt.QueuedConnection)
                    mc_th.disconnected_signal.connect(self._on_tf_disconnect, Qt.QueuedConnection)
                    mc_th.start()
                    self._mc_threads[dev] = (mc_th, routing)
                    for pair_id, _, mc2 in entries:
                        if isinstance(pair_id, int) and mc2 is not None:
                            self._extra_pair_threads[pair_id] = (None, None, None)

            # primary_ref_only: ref가 별도 장치에 있고 primary meas는 다른 장치
            if primary_active and meas_idx is not None and meas_idx != ref_idx:
                if ref_idx not in self._mc_threads and ref_idx is not None:
                    r_th = _EngineChannelSource(self._engine, ref_idx, self.sample_rate, self.fft_size, ref_ch)
                    r_th.chunk_ready.connect(self._on_ref, Qt.QueuedConnection)
                    r_th.error_signal.connect(self._on_err, Qt.QueuedConnection)
                    r_th.disconnected_signal.connect(self._on_tf_disconnect, Qt.QueuedConnection)
                    r_th.start(); self._ref_thread = r_th
                if meas_idx not in self._mc_threads:
                    m_th = _EngineChannelSource(self._engine, meas_idx, self.sample_rate, self.fft_size, meas_ch)
                    m_th.chunk_ready.connect(self._on_meas, Qt.QueuedConnection)
                    m_th.error_signal.connect(self._on_err, Qt.QueuedConnection)
                    m_th.disconnected_signal.connect(self._on_tf_disconnect, Qt.QueuedConnection)
                    m_th.start(); self._meas_thread = m_th

            # extra pairs meas-only (다른 장치, MC 스레드에 없는 경우)
            for i, pair in enumerate(self._extra_pairs):
                if not pair.get('display', False): continue
                p_meas_idx = pair['meas_cb'].currentData()
                if p_meas_idx is None: continue
                p_meas_ch = pair['meas_ch_cb'].currentData() or 0
                already = (p_meas_idx in self._mc_threads or
                           self._extra_pair_threads[i] != (None, None, None))
                if already: continue
                # ref 채널이 MC 스레드에서 처리되면 ref_only 라우팅 이미 추가됨
                ref_in_mc = ref_idx is not None and ref_idx in self._mc_threads
                if not ref_in_mc and ref_idx is not None and ref_idx not in self._mc_threads:
                    self._extra_ref_fft = getattr(self, '_extra_ref_fft', {})
                    self._extra_ref_buf = getattr(self, '_extra_ref_buf', {})
                m_th = _EngineChannelSource(self._engine, p_meas_idx, self.sample_rate, self.fft_size, p_meas_ch)
                m_th.chunk_ready.connect(lambda buf, xi=i: self._on_extra_meas(xi, buf), Qt.QueuedConnection)
                m_th.error_signal.connect(self._on_err, Qt.QueuedConnection)
                m_th.disconnected_signal.connect(self._on_tf_disconnect, Qt.QueuedConnection)
                m_th.start(); self._extra_pair_threads[i] = (None, None, m_th)

        self._running = True
        _r = QColor(T('red')); _rr,_rg,_rb = _r.red(),_r.green(),_r.blue()
        self.start_btn.setText('Stop'); _apply_txn(self.start_btn, True)
        self.start_btn.setStyleSheet(
            f'background:qlineargradient(x1:0,y1:0,x2:0,y2:1,'
            f'stop:0 rgba({_rr},{_rg},{_rb},55),stop:1 rgba({_rr},{_rg},{_rb},22));'
            f'color:{T("red")};border:1px solid rgba({_rr},{_rg},{_rb},140);'
            f'padding:3px 12px;border-radius:7px;font-weight:bold;')
        self.status_lbl.setText('● Running')
        self.status_lbl.setStyleSheet(f'color:{T("green")};font-size:11px;')

    def _stop_analysis(self):
        """입력 분석 스트림만 정지 — 제너레이터(출력) 스트림은 절대 건드리지 않음."""
        if self._gen_off_timer is not None:
            self._gen_off_timer.stop(); self._gen_off_timer = None
        self._gen_freeze = False
        for dev, (mc_th, _) in list(self._mc_threads.items()):
            try: mc_th.chunk_ready.disconnect(); mc_th.error_signal.disconnect()
            except Exception: pass
            mc_th.stop()
        self._mc_threads.clear()
        for i in range(len(self._extra_pair_threads)):
            self._stop_extra_pair_threads(i)
        if self._sync_thread is not None:
            try: self._sync_thread.frame_ready.disconnect(); self._sync_thread.error_signal.disconnect()
            except Exception: pass
            self._sync_thread.stop(); self._sync_thread = None
        for th in [self._ref_thread, self._meas_thread]:
            if th:
                try: th.chunk_ready.disconnect(); th.error_signal.disconnect()
                except Exception: pass
                th.stop()
        self._ref_thread = self._meas_thread = None
        self._running = False
        # VU proxy 리셋 — set_rms 경유해야 _card_fn이 UI에 전달됨
        self._vu_ref.set_rms(-80.0); self._vu_ref._pk = -80.0
        self._vu_meas.set_rms(-80.0); self._vu_meas._pk = -80.0
        # Ref VU 바 직접 리셋 (공유 ref bar)
        if hasattr(self, '_ref_vu_bar'): self._ref_vu_bar.reset()
        if hasattr(self, '_ref_db_lbl'): self._ref_db_lbl.setText('—')
        # 모든 카드 레벨 리셋 (primary + extra)
        if hasattr(self, '_level_cards'):
            for card in self._level_cards:
                card.reset()
        self.start_btn.setText('Start'); _apply_txn(self.start_btn, False)
        _g2 = QColor(T('accent')); _g2r,_g2g,_g2b = _g2.red(),_g2.green(),_g2.blue()
        self.start_btn.setStyleSheet(
            f'background:qlineargradient(x1:0,y1:0,x2:0,y2:1,'
            f'stop:0 rgba({_g2r},{_g2g},{_g2b},55),stop:1 rgba({_g2r},{_g2g},{_g2b},22));'
            f'color:{T("accent")};border:1px solid rgba({_g2r},{_g2g},{_g2b},140);'
            f'padding:3px 12px;border-radius:7px;font-weight:bold;')
        self.status_lbl.setText('● Standby')
        self.status_lbl.setStyleSheet(f'color:{T("text_dim")};font-size:11px;')
        self._refresh_input_monitor()   # 분석 정지 → 제너레이터 재생 중이면 입력 레벨 모니터 재개

    def _stop(self):
        """분석 + 제너레이터 모두 정지 (제너레이터 Stop 버튼 전용)."""
        _alog.info('TF 측정 중지')
        self._stop_analysis()  # 분석 스트림 정지
        # 제너레이터 정지
        if self._duplex_thread and self._duplex_thread.isRunning():
            self._mute_sig_gen()
        elif self._sig_stream:
            self._mute_sig_gen()
        else:
            self._stop_sig_gen()
            if self._mon_active:
                QTimer.singleShot(0, self._start_mon_streams)

    # ── 오디오 콜백 ──────────────────────────
    def _on_ref(self, buf):
        n = len(buf)
        if not hasattr(self, '_hann_win') or self._hann_win is None or len(self._hann_win) != n:
            self._hann_win = np.hanning(n).astype(np.float32)
        win = self._hann_win
        rms = float(np.sqrt(np.mean(buf ** 2)))
        fft = np.fft.rfft(buf * win).astype(complex)
        with QMutexLocker(self._mutex):
            self._last_ref_fft = fft; self._last_ref_rms = rms

    def _on_meas(self, buf):
        if not hasattr(self, '_hann_win') or self._hann_win is None or len(self._hann_win) != len(buf):
            self._hann_win = np.hanning(len(buf)).astype(np.float32)
        win = self._hann_win
        rms = float(np.sqrt(np.mean(buf ** 2)))
        fft = np.fft.rfft(buf * win).astype(complex)
        with QMutexLocker(self._mutex):
            self._last_meas_fft = fft; self._last_meas_rms = rms
        # Primary 카드 M 레벨 즉시 업데이트 — 체크박스(가시) ON 이면 표시 (Start/Stop 무관)
        if (self._level_cards and self._level_cards[0].is_graph_visible() and rms > 1e-9):
            self._level_cards[0].set_meas(20 * _math.log10(rms))

    def _on_frame(self, ref_buf, meas_buf):
        # TFSyncThread/TFDuplexThread: 두 채널을 동일 콜백에서 수신 → ΔT=0 원자 처리
        # Hanning window 캐시 — 매 콜백마다 재생성 금지
        n = len(ref_buf)
        if not hasattr(self, '_hann_win') or self._hann_win is None or len(self._hann_win) != n:
            self._hann_win = np.hanning(n).astype(np.float32)
        win = self._hann_win
        rms_r = float(np.sqrt(np.mean(ref_buf ** 2)))
        rms_m = float(np.sqrt(np.mean(meas_buf ** 2)))
        fft_r = np.fft.rfft(ref_buf * win).astype(complex)
        fft_m = np.fft.rfft(meas_buf * win).astype(complex)
        with QMutexLocker(self._mutex):
            self._last_ref_fft = fft_r; self._last_ref_rms = rms_r
            self._last_meas_fft = fft_m; self._last_meas_rms = rms_m
        # Primary 카드 레벨 직접 업데이트 — 체크박스(가시) ON 이면 표시 (Start/Stop 무관)
        if (hasattr(self, '_level_cards') and self._level_cards and self._level_cards[0].is_graph_visible()):
            pc = self._level_cards[0]
            if rms_r > 1e-9: pc.set_ref(20 * _math.log10(rms_r))
            if rms_m > 1e-9: pc.set_meas(20 * _math.log10(rms_m))

    def _update_extra_card(self, pair_idx, ref_buf, meas_buf):
        """Extra 쌍 카드에 RMS 레벨 업데이트 (Qt 메인스레드에서 호출)."""
        pair = self._extra_pairs[pair_idx] if pair_idx < len(self._extra_pairs) else None
        card = pair.get('card') if pair else None
        if card is None or not card.is_graph_visible(): return   # 체크박스 OFF → 레벨 표시 안 함
        rms_r = float(np.sqrt(np.mean(ref_buf ** 2)))
        rms_m = float(np.sqrt(np.mean(meas_buf ** 2)))
        if rms_r > 1e-9: card.set_ref(20 * _math.log10(rms_r))
        if rms_m > 1e-9: card.set_meas(20 * _math.log10(rms_m))

    def _on_extra_frame(self, pair_idx, ref_buf, meas_buf):
        """TFSyncThread (same-device extra pair): ref+meas 원자 처리 → pair 누적."""
        self._update_extra_card(pair_idx, ref_buf, meas_buf)
        n = len(ref_buf)
        win = np.hanning(n).astype(np.float32)
        fft_r = np.fft.rfft(ref_buf * win).astype(complex)
        fft_m = np.fft.rfft(meas_buf * win).astype(complex)
        self._accumulate_extra(pair_idx, fft_r, fft_m)

    def _on_mc_chunk(self, device_idx, chunk_dict):
        """MultiChannelAudioThread → 장치별 라우팅 → 각 pair 핸들러 호출."""
        entry = self._mc_threads.get(device_idx)
        if entry is None: return
        _, routing = entry
        primary_on = bool(self._level_cards) and self._level_cards[0]._display_on
        for r in routing:
            pair_idx = r.get('pair_idx')
            # display 플래그 체크 — 비활성 pair는 완전히 건너뜀 (스트림 유지, 처리만 스킵)
            if pair_idx == 'primary' and not primary_on: continue
            if isinstance(pair_idx, int):
                if pair_idx >= len(self._extra_pairs): continue
                if not self._extra_pairs[pair_idx].get('display', False): continue

            # ref_only: diff-device pair의 ref 채널을 MC에서 버퍼링
            ref_only_idx = r.get('_ref_only_pair')
            if ref_only_idx is not None:
                if ref_only_idx < len(self._extra_pairs) and not self._extra_pairs[ref_only_idx].get('display', False):
                    continue  # 비활성 pair ref 버퍼링 스킵
                ref_buf = chunk_dict.get(r['ref_ch'])
                if ref_buf is not None:
                    if not hasattr(self, '_extra_ref_fft'): self._extra_ref_fft = {}
                    if not hasattr(self, '_extra_ref_buf'): self._extra_ref_buf = {}
                    win = np.hanning(len(ref_buf)).astype(np.float32)
                    self._extra_ref_fft[ref_only_idx] = np.fft.rfft(ref_buf * win).astype(complex)
                    self._extra_ref_buf[ref_only_idx] = ref_buf
                    pair = self._extra_pairs[ref_only_idx] if ref_only_idx < len(self._extra_pairs) else None
                    card = pair.get('card') if pair else None
                    rms_r = float(np.sqrt(np.mean(ref_buf ** 2)))
                    if card and rms_r > 1e-9: card.set_ref(20 * _math.log10(rms_r))
                continue
            # primary cross-device ref 버퍼링 → _last_ref_fft (다른 장치 meas chunk와 결합)
            if r.get('_primary_ref_only'):
                if not primary_on: continue
                ref_buf = chunk_dict.get(r['ref_ch'])
                if ref_buf is not None:
                    self._on_ref(ref_buf)
                continue
            r_ch = r.get('ref_ch'); m_ch = r.get('meas_ch')
            meas_buf = chunk_dict.get(m_ch)
            if meas_buf is None: continue
            if r_ch is not None:
                ref_buf = chunk_dict.get(r_ch)
                if ref_buf is None: continue
            else:
                # ref가 다른 장치에 있음 — _extra_ref_fft 에 버퍼링된 값 사용
                if pair_idx == 'primary':
                    # primary meas: ref는 다른 장치 MC가 _last_ref_fft 에 저장 → render가 결합
                    self._on_meas(meas_buf)
                    continue
                if not isinstance(pair_idx, int): continue
                fft_r = getattr(self, '_extra_ref_fft', {}).get(pair_idx)
                if fft_r is None: continue
                # meas FFT 계산 후 직접 누적 (_on_extra_meas 경로와 동일)
                win = np.hanning(len(meas_buf)).astype(np.float32)
                fft_m = np.fft.rfft(meas_buf * win).astype(complex)
                if len(fft_r) == len(fft_m):
                    ref_buf_cached = getattr(self, '_extra_ref_buf', {}).get(pair_idx)
                    if ref_buf_cached is not None:
                        self._update_extra_card(pair_idx, ref_buf_cached, meas_buf)
                    self._accumulate_extra(pair_idx, fft_r, fft_m)
                continue
            r['callback'](ref_buf, meas_buf)

    def _on_extra_ref(self, pair_idx, buf):
        """AudioThread ref 콜백 (diff-device extra pair)."""
        n = len(buf)
        win = np.hanning(n).astype(np.float32)
        if not hasattr(self, '_extra_ref_fft'): self._extra_ref_fft = {}
        if not hasattr(self, '_extra_ref_buf'): self._extra_ref_buf = {}
        self._extra_ref_fft[pair_idx] = np.fft.rfft(buf * win).astype(complex)
        self._extra_ref_buf[pair_idx] = buf
        # 카드 ref 레벨 업데이트
        pair = self._extra_pairs[pair_idx] if pair_idx < len(self._extra_pairs) else None
        card = pair.get('card') if pair else None
        rms_r = float(np.sqrt(np.mean(buf ** 2)))
        if card and rms_r > 1e-9: card.set_ref(20 * _math.log10(rms_r))

    def _on_extra_meas(self, pair_idx, buf):
        """AudioThread meas 콜백 (diff-device extra pair)."""
        if not hasattr(self, '_extra_ref_fft'): return
        fft_r = self._extra_ref_fft.get(pair_idx)
        if fft_r is None: return
        ref_buf = getattr(self, '_extra_ref_buf', {}).get(pair_idx)
        n = len(buf)
        win = np.hanning(n).astype(np.float32)
        fft_m = np.fft.rfft(buf * win).astype(complex)
        if len(fft_r) == len(fft_m):
            if ref_buf is not None:
                self._update_extra_card(pair_idx, ref_buf, buf)
            self._accumulate_extra(pair_idx, fft_r, fft_m)

    def _accumulate_extra(self, pair_idx, fft_r, fft_m):
        S_xy = fft_m * np.conj(fft_r)
        S_xx = np.abs(fft_r) ** 2
        S_yy = np.abs(fft_m) ** 2
        acc = self._extra_pair_acc[pair_idx] if pair_idx < len(self._extra_pair_acc) else None
        if acc is None:
            self._extra_pair_acc[pair_idx] = {'cross': S_xy.copy(), 'auto_x': S_xx.copy(),
                                               'auto_y': S_yy.copy(), 'n': 1}
        else:
            n_avg = min(acc['n'] + 1, self._avg_target)
            α = 1.0 / n_avg; β = 1.0 - α
            acc['cross']  = β * acc['cross']  + α * S_xy
            acc['auto_x'] = β * acc['auto_x'] + α * S_xx
            acc['auto_y'] = β * acc['auto_y'] + α * S_yy
            acc['n'] = n_avg


    def _on_err(self, msg):
        self._stop_analysis()  # 분석만 정지 — 제너레이터는 유지
        from PyQt5.QtWidgets import QMessageBox
        QMessageBox.warning(self, '오디오 오류', f'오디오 장치 오류:\n{msg}')

    def _on_tf_disconnect(self, msg=''):
        """입력 장치(인터페이스) USB 끊김 감지 — 분석 + 제너레이터(출력) 모두 정지.
        출력 스트림을 닫지 않으면 핑크노이즈가 macOS 기본(내장) 출력으로 새므로 함께 정지."""
        if getattr(self, '_tf_disc_handling', False): return
        self._tf_disc_handling = True
        _alog.info(f'TF 장치 연결 끊김 감지 → 정지 + 자동 새로고침  msg={msg}')
        self._stop_analysis()   # 분석 스트림 정지 (UI/카드/버튼 리셋 포함)
        self._stop_sig_gen()    # 출력 스트림도 닫음 → 핑크 내장출력 누출 방지
        try:
            self.status_lbl.setText('● 연결 끊김')
            self.status_lbl.setStyleSheet(f'color:{T("yellow")};font-size:11px;')
        except Exception: pass
        # 2초 후 장치 목록 갱신 (뽑힌 장치 제거 / 재연결 장치 등록)
        QTimer.singleShot(2000, self._after_tf_disconnect)

    def _after_tf_disconnect(self):
        # 중앙(MainWindow) 재초기화로 위임 — PortAudio는 프로세스 1회 초기화라
        # 탭별이 아닌 앱 전역에서 재초기화해야 재연결 장치가 인식됨 (모든 탭 동시 해결).
        # 주의: QStackedWidget 에 addWidget 되며 parent()는 stack 으로 재지정됨 →
        # 최상위 윈도우(MainWindow)는 self.window() 로 얻어야 함.
        mw = self.window()
        if mw is not None and hasattr(mw, 'reinit_audio_devices'):
            mw.reinit_audio_devices('USB disconnect (TF)')
            mw._begin_replug_watch()
        else:
            self._load_devices()
        self._tf_disc_handling = False

    # ── 렌더 루프 ────────────────────────────
    def _render(self):
        try:
            self._render_inner()
        except Exception as e:
            _alog.error(f'TF _render error: {e}')

    def _render_inner(self):
        # Internal Loopback: SigGen 순환 버퍼에서 Reference 프레임 추출
        if self._running and self.ref_cb.currentData() is None and self._sig_stream is not None:
            # xrun 감지: 스피커 하드웨어 글리치 → ref/meas 불일치 프레임 → EMA 리셋으로 오염 방지
            if getattr(self, '_standalone_xrun', [False])[0]:
                self._standalone_xrun[0] = False
                self._xrun_reset_count = getattr(self, '_xrun_reset_count', 0) + 1
                _alog.warning(f'[DIAG] SigGen xrun → ref/avg 리셋 (#{self._xrun_reset_count})  '
                              f'delay={getattr(self,"delay_ms",0.0):.2f}ms')
                self._int_ref_buf[:] = 0; self._int_ref_pos[0] = 0; self._int_ref_filled = False
                self._reset_avg()
                return
            # 락 없이 위치만 읽고 필요한 윈도우만 복사 (131072샘플 전체 복사 제거)
            # _ir_pos는 GIL이 단일 연산 원자성 보장. 순환 버퍼 크기≫fft_size여서 경쟁 무시 가능.
            ir_pos = self._int_ref_pos[0]
            n = len(self._int_ref_buf); fs = self.fft_size
            if not getattr(self, '_int_ref_filled', False):
                if ir_pos >= fs:
                    self._int_ref_filled = True  # 버퍼 최초 충전 완료
                # else: 아직 충전 중 — 레퍼런스 추출 건너뜀 (초기 0으로 채워진 가비지 방지)
            if getattr(self, '_int_ref_filled', False):
                if ir_pos >= fs:
                    frame = self._int_ref_buf[ir_pos - fs:ir_pos].copy()
                else:
                    frame = np.concatenate([self._int_ref_buf[n - (fs - ir_pos):], self._int_ref_buf[:ir_pos]])
                self._on_ref(frame)
        with QMutexLocker(self._mutex):
            X = self._last_ref_fft; Y = self._last_meas_fft
            rr = self._last_ref_rms; mr = self._last_meas_rms
            self._last_ref_fft = None; self._last_meas_fft = None
            self._last_ref_rms = 0.0; self._last_meas_rms = 0.0

        # VU 미터 업데이트 — 항상 (⏻ 버튼 제거됨)
        if self.ref_cb.currentData() is None:
            # Internal SigGen ref: Play 중이면 버퍼 RMS, 꺼지면 리셋
            if self._sig_stream is not None:
                pos = self._int_ref_pos[0]
                chunk = self._int_ref_buf[max(0, pos - 2048):pos].copy()
                if len(chunk) > 0:
                    sg_rms = float(np.sqrt(np.mean(chunk ** 2)))
                    if sg_rms > 0: rr = sg_rms
            elif not (self._duplex_thread and self._duplex_thread.isRunning() and not self._duplex_thread._muted):
                if self._vu_ref._db > -79.0:
                    self._vu_ref._db = -80.0; self._vu_ref._pk = -80.0
                    self._vu_ref.update()
        if self._running:
            # R 바는 공유 레퍼런스라 항상 / primary M 바는 primary 체크박스 ON 일 때만
            _pvis = (not self._level_cards) or self._level_cards[0].is_graph_visible()
            if rr > 0: self._vu_ref.set_rms(20 * math.log10(max(rr, 1e-9)))
            if mr > 0 and _pvis: self._vu_meas.set_rms(20 * math.log10(max(mr, 1e-9)))

        # 분석(카드 Start) 없이 제너레이터만 재생 중이어도 R(레퍼런스) 바 표시
        # — 출력=루프백 레퍼런스 신호(_int_ref_buf)의 레벨로 갱신 (입력 스트림 불필요 → 충돌 없음).
        if ((not self._running) and self._sig_stream is not None
                and not getattr(self, '_standalone_muted', [False])[0]):
            _pos = self._int_ref_pos[0]
            _chunk = self._int_ref_buf[max(0, _pos - 2048):_pos]
            if len(_chunk) > 0:
                _rr2 = float(np.sqrt(np.mean(_chunk ** 2)))
                if _rr2 > 1e-9: self._on_ref_vu(20 * math.log10(_rr2))
        elif not self._running:
            # 제너레이터 정지/뮤트 + 분석 없음 → R 바 비움 (마지막 값 frozen 방지)
            if hasattr(self, '_ref_vu_bar') and self._ref_vu_bar._db > -79.0:
                self._ref_vu_bar.reset()
                self._vu_ref._db = -80.0; self._vu_ref._pk = -80.0
                if hasattr(self, '_ref_db_lbl'): self._ref_db_lbl.setText('—')

        if not self._running: return
        if self._gen_freeze: return  # 제너레이터 OFF 후 동결 — 화면 유지, 누적 중단
        # 스윕 캡처 진행 중 → EMA 대신 진행률 표시만 (primary duplex 전용)
        if self._duplex_thread and self._duplex_thread._sc_armed[0]:
            sc_len = self._duplex_thread._sc_len
            if sc_len > 0:
                pct = min(int(self._duplex_thread._sc_pos[0] / sc_len * 100), 99)
                self.avg_lbl.setText(f'Sweep: {pct}%')
            return
        # 주파수/시간 축 — fft_size 기준. primary 유무와 무관하게 extra 렌더에도 필요.
        freqs = np.fft.rfftfreq(self.fft_size, 1.0 / self.sample_rate).astype(np.float32)
        # IR 시간축: 0을 가운데로 (fftshift) → 음수 시간(임펄스 도착 전 pre-ring)도 표시.
        # irfft는 순환배열(0..+T)이라 음수성분이 꼬리로 wrap됨 → fftshift로 -T/2..+T/2 매핑.
        _ir_half = self.fft_size // 2
        t_ms = (np.arange(self.fft_size, dtype=np.float32) - _ir_half) / self.sample_rate * 1000.0
        # primary 표시 여부: 분석중(_display_on)이고 그래프 표시 체크(is_graph_visible)일 때만
        _pc = self._level_cards[0] if (hasattr(self, '_level_cards') and self._level_cards) else None
        _primary_show = (_pc is None) or (_pc._display_on and _pc.is_graph_visible())

        # ── Primary 누적·렌더 (Ref/Meas 데이터 충분할 때만; 없으면 extra 카드만 렌더) ──
        H_raw = None
        primary_ok = (X is not None and Y is not None and len(X) == len(Y)
                      and rr >= 1e-6 and mr >= 1e-6)
        if primary_ok:
            S_xy = Y * np.conj(X); S_xx = np.abs(X) ** 2; S_yy = np.abs(Y) ** 2
            if self._cross_acc is None:
                self._cross_acc = S_xy.copy(); self._auto_acc_x = S_xx.copy()
                self._auto_acc_y = S_yy.copy(); self._n_avg = 1
            else:
                # 워밍업 구간: 선형 누적 (running mean) → 안정 후: EMA (리셋 없음)
                self._n_avg = min(self._n_avg + 1, self._avg_target)
                α = 1.0 / self._n_avg   # 1→1/N 으로 수렴, 이후 1/N 고정
                β = 1.0 - α
                self._cross_acc  = β * self._cross_acc  + α * S_xy
                self._auto_acc_x = β * self._auto_acc_x + α * S_xx
                self._auto_acc_y = β * self._auto_acc_y + α * S_yy
            self.avg_lbl.setText(f'Avg: {self._n_avg} / {self._avg_target}')
            if self._n_avg >= 3:   # 초기 3프레임 미만: EMA 수렴 전, 표시 생략
                H_raw = self._cross_acc / np.maximum(self._auto_acc_x, 1e-30)
                # Phase/Mag 표시용: 딜레이 위상 보정 적용
                if self.delay_ms != 0.0:
                    H_disp = H_raw * np.exp(1j * 2 * np.pi * freqs * (self.delay_ms / 1000.0))
                else:
                    H_disp = H_raw
                gamma2 = np.clip(np.abs(self._cross_acc) ** 2 /
                                 np.maximum(self._auto_acc_x * self._auto_acc_y, 1e-60), 0.0, 1.0)
                f_out, mag_out, ph_wrap, ph_unwr, grp_ms = _tf_smooth(freqs, H_disp, self.smooth_bpo)
                mask = (freqs >= 18) & (freqs <= 22000)
                f_m = freqs[mask]; g_m = gamma2[mask]
                if len(f_m) > 1:
                    # 코히런스도 1/3 oct 스무딩 적용 (주황선 노이즈 제거)
                    bpo_c = max(self.smooth_bpo, 3)
                    half_c = 2 ** (0.5 / bpo_c)
                    g_cum = np.zeros(len(g_m) + 1); g_cum[1:] = np.cumsum(g_m)
                    lo_c = np.searchsorted(f_m, f_out / half_c, 'left')
                    hi_c = np.searchsorted(f_m, f_out * half_c, 'right')
                    cnt_c = hi_c - lo_c; val_c = cnt_c > 0
                    coh_out = np.interp(f_out, f_m, g_m)
                    coh_out[val_c] = (g_cum[hi_c[val_c]] - g_cum[lo_c[val_c]]) / cnt_c[val_c]
                    coh_out = coh_out.astype(np.float32)
                else:
                    coh_out = None
                if _primary_show:
                    self.phase_cvs.set_data(f_out, ph_wrap, ph_unwr, grp_ms, coh_out, mag_out)
                    self.mag_cvs.set_data(f_out, mag_out, coh_out, ph_wrap)
        else:
            # primary 비활성(카드1 Stop 등) → avg 표시는 활성 extra 카드 기준
            _ns = [a['n'] for a in self._extra_pair_acc if a is not None]
            if _ns:
                self.avg_lbl.setText(f'Avg: {min(max(_ns), self._avg_target)} / {self._avg_target}')

        # 추가 Ref+Meas 쌍 H(f) 계산 및 캔버스 업데이트 (primary 유무와 무관)
        for i, acc in enumerate(self._extra_pair_acc):
            if acc is None or acc['n'] < 3: continue
            pair = self._extra_pairs[i] if i < len(self._extra_pairs) else None
            if pair and not pair.get('display', True):
                continue  # 분석 중지 — skip
            if pair and pair.get('card') is not None and not pair['card'].is_graph_visible():
                continue  # 그래프 표시 OFF — 분석은 계속, 곡선만 숨김
            color = _MC_COLORS[i % len(_MC_COLORS)]
            H_ex_raw = acc['cross'] / np.maximum(acc['auto_x'], 1e-30)
            # 카드별 독립 딜레이 적용
            pair_delay = 0.0
            if i < len(self._extra_pairs):
                pair_delay = self._extra_pairs[i].get('delay_ms', 0.0)
            if pair_delay != 0.0:
                H_ex_disp = H_ex_raw * np.exp(1j * 2 * np.pi * freqs * (pair_delay / 1000.0))
            else:
                H_ex_disp = H_ex_raw
            f_ex, mag_ex, ph_wrap_ex, ph_unwr_ex, grp_ms_ex = _tf_smooth(freqs, H_ex_disp, self.smooth_bpo)
            self.mag_cvs.set_tf_extra(i, color, f_ex, mag_ex)
            self.phase_cvs.set_tf_extra_phase(i, color, f_ex, ph_wrap_ex, ph_unwr_ex, grp_ms_ex)
            # 카드별 IR: 딜레이 보정 없이 raw H → 임펄스가 실제 도착(=딜레이) 위치에 표시.
            # 딜레이 값은 카드색 마커로 그려지고, front 카드면 뷰가 그 위치로 센터링된다.
            # (mag/phase 는 위 H_ex_disp 로 위상 보정 유지 — IR 만 물리 위치)
            h_ex = np.fft.fftshift(np.fft.irfft(H_ex_raw, n=self.fft_size)).astype(np.float32)
            self.ir_cvs.set_tf_extra(i, color, t_ms, h_ex, delay=pair_delay)

        # Live IR (primary): 딜레이 보정 없이 raw H → 임펄스가 실제 도착(=딜레이) 위치에.
        # 딜레이는 녹색 마커로 표시되고, primary 가 front 면 뷰가 그 위치로 센터링된다.
        if _primary_show and H_raw is not None:
            h_full = np.fft.fftshift(np.fft.irfft(H_raw, n=self.fft_size)).astype(np.float32)
            self.ir_cvs.set_data(t_ms, h_full)
            self.ir_cvs._delay_ms = self.delay_ms   # primary 딜레이 마커 위치

    # ── 딜레이 자동 탐지 (2단계: 2초 측정 후 계산) ──────────────────────
    def _on_sweep_captured(self, ref_arr, meas_arr):
        """단일 스윕 캡처 완료 → 역필터 계산 → 캔버스 업데이트 → 자동 Stop."""
        n = len(ref_arr)
        REF = np.fft.rfft(ref_arr.astype(np.float64))
        MIC = np.fft.rfft(meas_arr.astype(np.float64))
        # 정규화된 역필터 (Wiener deconvolution 간략화): H = MIC·REF* / (|REF|² + ε)
        eps = float(np.max(np.abs(REF)) ** 2) * 1e-6
        H = (MIC * np.conj(REF)) / (np.abs(REF) ** 2 + eps)
        H = H.astype(np.complex64)
        freqs = np.fft.rfftfreq(n, 1.0 / self.sample_rate).astype(np.float32)

        # 딜레이 보정 적용
        if self.delay_ms != 0.0:
            H_disp = H * np.exp(1j * 2 * np.pi * freqs * (self.delay_ms / 1000.0)).astype(np.complex64)
        else:
            H_disp = H

        f_out, mag_out, ph_wrap, ph_unwr, grp_ms = _tf_smooth(freqs, H_disp, self.smooth_bpo)
        coh_out = np.ones(len(f_out), dtype=np.float32)  # 역필터 = 코히런스 1.0

        self.phase_cvs.set_data(f_out, ph_wrap, ph_unwr, grp_ms, coh_out, mag_out)
        self.mag_cvs.set_data(f_out, mag_out, coh_out, ph_wrap)

        # IR: 역필터 결과 시간 도메인
        h_full = np.fft.fftshift(np.fft.irfft(H, n=n)).astype(np.float32)
        t_ms = (np.arange(n, dtype=np.float32) - n // 2) / self.sample_rate * 1000.0
        self.ir_cvs.set_data(t_ms, h_full)

        dur_ms = n / self.sample_rate * 1000.0
        self._fft_lbl.setText(f'Sweep 1-shot: {n} smp / {dur_ms:.0f} ms')
        self.avg_lbl.setText('Done ✓')

        # 자동 Stop
        self._stop_sig_gen()
        self.sig_on_btn.setChecked(False)
        self.sig_on_btn.setText('Play'); _apply_txn(self.sig_on_btn, False)
        _alog.debug(f'_on_sweep_captured: n={n} deconv done')

    def _find_delay(self):
        DelayFinderDialog(self, self).exec_()

    def _find_delay_compute(self):
        """2단계: 2초 누적 후 TF IR 피크로 딜레이 계산 (Smaart 방식: H=Sxy/Sxx 정규화)."""
        import threading
        with QMutexLocker(self._mutex):
            cross  = self._cross_acc.copy()  if self._cross_acc  is not None else None
            auto_x = self._auto_acc_x.copy() if self._auto_acc_x is not None else None
        if cross is None or auto_x is None:
            self.find_btn.setEnabled(True); self.find_btn.setText('Find')
            return
        fft_size = self.fft_size; sr = self.sample_rate

        def _worker():
            # Smaart 방식: H = Sxy/Sxx (TF 정규화) → IFFT → IR 피크
            # 비정규화 cross-correlation은 핑크노이즈 저주파 에너지에 편향됨 → 오차
            H = cross / np.maximum(auto_x, 1e-30)
            h = np.fft.irfft(H, n=fft_size)
            env = _hilbert_env(h)              # 힐버트 포락선으로 더 정확한 피크
            peak = int(np.argmax(env))
            # 파라볼릭 보간으로 서브샘플 정밀도 확보 (Smaart 방식)
            if 0 < peak < len(env) - 1:
                y0, y1, y2 = float(env[peak-1]), float(env[peak]), float(env[peak+1])
                denom = 2*(2*y1 - y0 - y2)
                if denom > 0: peak += (y2 - y0) / denom
            if peak > fft_size // 2: peak -= fft_size
            d_ms = round(float(peak) / sr * 1000.0, 2)
            self._find_result_sig.emit(d_ms)

        threading.Thread(target=_worker, daemon=True).start()

    def _apply_find_result(self, d_ms):
        """백그라운드 계산 완료 후 메인 스레드에서 UI 업데이트."""
        self.find_btn.setEnabled(True); self.find_btn.setText('Find')
        if 0 <= d_ms <= 500:
            self.delay_spin.setValue(d_ms)   # _on_delay_changed 경유 (self.delay_ms 갱신)
            self.mag_cvs.fit_y()             # Magnitude Y축 자동 맞춤 (뷰는 건드리지 않음)
        else:
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.information(self, 'Delay Finder', f'탐지값: {d_ms:.2f} ms\n범위 초과 — 수동으로 입력하세요.')

    # ── 캡처 ────────────────────────────────
    def _save_tf_captures(self):
        """캡쳐/삭제 시엔 dirty 표시만 — 실제 디스크 저장은 오디오 idle 일 때만 수행.
        (큰 IR 배열 .tolist()+JSON 직렬화는 단일 C 호출로 GIL을 통째로 점유 → 측정/재생 중
        파이썬 오디오 콜백이 굶어 '띡' 클릭·버벅임 발생. 캡쳐 수가 많을수록 심함.
        → 측정/재생 중에는 저장을 미루고, 정지·종료 후 idle 일 때만 저장해 글리치 원천 차단.)"""
        self._caps_dirty = True
        if getattr(self, '_save_caps_timer', None) is None:
            self._save_caps_timer = QTimer(self)
            self._save_caps_timer.timeout.connect(self._caps_idle_flush)
            self._save_caps_timer.start(2000)   # 2초마다 idle 체크

    def _audio_busy(self):
        playing = bool(getattr(self, 'sig_on_btn', None) and self.sig_on_btn.isChecked())
        return bool(getattr(self, '_running', False) or playing)

    def _caps_idle_flush(self):
        if not getattr(self, '_caps_dirty', False): return
        if self._audio_busy(): return   # 오디오 활성 → 보류 (글리치 방지)
        self._flush_tf_captures(sync=True)   # idle → 동기 저장 (오디오 없어 글리치 없음)

    def _flush_tf_captures(self, sync=True):
        if not getattr(self, '_caps_dirty', False): return
        self._caps_dirty = False
        # GUI 스레드 스냅샷 (배열은 생성 후 불변이라 안전)
        metas = list(self._tf_captures)
        mag_caps = list(self.mag_cvs._captures)
        phase_caps = list(self.phase_cvs._captures)
        ir_caps = list(self.ir_cvs._captures)
        if sync:
            self._serialize_save_tf_captures(metas, mag_caps, phase_caps, ir_caps)
        else:
            threading.Thread(target=self._serialize_save_tf_captures,
                             args=(metas, mag_caps, phase_caps, ir_caps), daemon=True).start()

    def _serialize_save_tf_captures(self, metas, mag_caps, phase_caps, ir_caps):
        try:
            tf_list = []
            for i, meta in enumerate(metas):
                entry = {'color': meta['color'], 'label': meta['label'], 'group': meta.get('group', ''),
                         'source': meta.get('source', 'primary'), 'is_ref': bool(meta.get('is_ref', False))}
                if i < len(mag_caps):
                    m = mag_caps[i]
                    entry['mag'] = {'f': m['f'].tolist(), 'mag': m['mag'].tolist(),
                                    'coh': m['coh'].tolist() if m.get('coh') is not None else None}
                if i < len(phase_caps):
                    p = phase_caps[i]
                    entry['phase'] = {
                        'f': p['f'].tolist(),
                        'ph_wrap': p['ph_wrap'].tolist() if p.get('ph_wrap') is not None else None,
                        'ph_unwr': p['ph_unwr'].tolist() if p.get('ph_unwr') is not None else None,
                        'grp_ms':  p['grp_ms'].tolist()  if p.get('grp_ms')  is not None else None,
                        'coh':     p['coh'].tolist()     if p.get('coh')     is not None else None,
                    }
                if i < len(ir_caps):
                    r = ir_caps[i]
                    if r.get('t') is None or r.get('h') is None:
                        entry['ir'] = None  # extra 카드 빈 IR 캡쳐
                    else:
                        entry['ir'] = {'t': r['t'].tolist(), 'h': r['h'].tolist(),
                                       'etc_db': r['etc_db'].tolist() if r.get('etc_db') is not None else None,
                                       'delay': float(r.get('delay', 0.0))}
                tf_list.append(entry)
            with _CAPTURES_LOCK:   # spec 캡쳐와 같은 파일 공유 → 읽기-수정-쓰기 원자화(클로버 방지)
                data = _load_captures_file()
                data['tf'] = tf_list
                _save_captures_file(data)
        except Exception as e:
            _alog.warning(f'TF 캡처 저장 실패: {e}')

    def _restore_tf_captures(self):
        data = _load_captures_file()
        for cap in data.get('tf', []):
            try:
                color = cap['color']; label = cap['label']; group = cap.get('group', '')
                source = cap.get('source', 'primary')
                if 'mag' in cap and cap['mag']:
                    m = cap['mag']
                    self.mag_cvs._captures.append({
                        'f': np.array(m['f'], dtype=np.float32),
                        'mag': np.array(m['mag'], dtype=np.float32),
                        'coh': np.array(m['coh'], dtype=np.float32) if m.get('coh') else None,
                        'color': color, 'label': label
                    })
                if 'phase' in cap and cap['phase']:
                    p = cap['phase']
                    self.phase_cvs._captures.append({
                        'f':       np.array(p['f'],       dtype=np.float32),
                        'ph_wrap': np.array(p['ph_wrap'], dtype=np.float32) if p.get('ph_wrap') else None,
                        'ph_unwr': np.array(p['ph_unwr'], dtype=np.float32) if p.get('ph_unwr') else None,
                        'grp_ms':  np.array(p['grp_ms'],  dtype=np.float32) if p.get('grp_ms')  else None,
                        'coh':     np.array(p['coh'],     dtype=np.float32) if p.get('coh')     else None,
                        'color': color, 'label': label
                    })
                if cap.get('ir'):
                    r = cap['ir']
                    self.ir_cvs._captures.append({
                        't': np.array(r['t'], dtype=np.float32),
                        'h': np.array(r['h'], dtype=np.float32),
                        'etc_db': np.array(r['etc_db'], dtype=np.float32) if r.get('etc_db') else None,
                        'color': color, 'label': label, 'delay': float(r.get('delay', 0.0))
                    })
                else:
                    # extra 카드 빈 IR — _tf_captures 인덱스 정합 유지
                    self.ir_cvs._captures.append({
                        't': None, 'h': None, 'etc_db': None, 'color': color, 'label': label
                    })
                self._tf_captures.append({'color': color, 'label': label,
                                          'group': group, 'source': source,
                                          'is_ref': bool(cap.get('is_ref', False))})
            except Exception as e:
                _alog.warning(f'TF 캡처 복원 실패 (항목 건너뜀): {e}')
        if self._tf_captures:
            for cvs in (self.mag_cvs, self.phase_cvs, self.ir_cvs):
                cvs._cap_pix = None; cvs.update()
            # 저장된 Δ 기준 캡쳐 복원
            ref_idx = next((j for j, m in enumerate(self._tf_captures) if m.get('is_ref')), None)
            if ref_idx is not None:
                self._on_set_reference(ref_idx)

    def _do_tf_capture(self, prompt=True):
        """현재 화면의 모든 활성 곡선(primary + 표시중 extra 카드)을 한 번에 캡쳐.

        prompt=True 면 이름 입력 다이얼로그를 띄우고, False 면 자동 이름으로 즉시 캡쳐.
        """
        if self.mag_cvs.freqs is None:
            return
        n = len(self._tf_captures)
        default = f'Capture {n + 1}'
        if prompt:
            base, ok = _text_input_dialog(self, '캡처', '이름:', default)
            if not ok: return
            base = (base or '').strip() or default
        else:
            base = default

        # 안정화 캡쳐 모드 — 평균 수렴 + 코히런스 안정 후 자동 스냅샷
        if (getattr(self, 'tf_stable_btn', None) and self.tf_stable_btn.isChecked()
                and self._running and not getattr(self, '_stabilizing', False)):
            self._begin_stable_capture(base)
            return
        self._capture_snapshot(base)

    def _capture_snapshot(self, base):
        """실제 캡쳐 수행 (primary + 표시중 extra 카드)."""
        group = getattr(self, '_current_tf_group', '')
        n = len(self._tf_captures)
        added = 0
        # primary — 표시 중일 때만 (꺼져 있으면 캔버스 데이터가 stale)
        primary_on = (not self._level_cards) or self._level_cards[0]._display_on
        if primary_on:
            color = _auto_capture_color(n)
            self.mag_cvs.add_capture(base, color)
            self.phase_cvs.add_capture(base, color)
            self.ir_cvs.add_capture(base, color, delay=self.delay_ms)
            self._tf_captures.append({'color': color, 'label': base,
                                      'group': group, 'source': 'primary'})
            added += 1

        # 표시 중인 extra 카드 각각 (Mag/Phase 만, IR 은 빈 캡쳐)
        for i, pair in enumerate(getattr(self, '_extra_pairs', [])):
            if not pair.get('display', False): continue
            ex_m = self.mag_cvs._tf_extra.get(i)
            if not ex_m or ex_m.get('f') is None: continue
            ex_p = self.phase_cvs._tf_extra_phase.get(i)
            card_no = i + 2  # _MeasCard(idx+2, ...) 와 동일한 번호
            ex_label = f'{base} · Card{card_no}'
            ex_color = pair.get('color') or _MC_COLORS[i % len(_MC_COLORS)]
            self.mag_cvs.add_capture_data(ex_label, ex_color, ex_m.get('f'), ex_m.get('mag'))
            self.phase_cvs.add_capture_data(
                ex_label, ex_color, (ex_p or ex_m).get('f'),
                ex_p.get('ph_wrap') if ex_p else None,
                ex_p.get('ph_unwr') if ex_p else None,
                ex_p.get('grp_ms') if ex_p else None)
            ex_ir = self.ir_cvs._tf_extra.get(i)
            ex_delay = pair.get('delay_ms', 0.0)
            if ex_ir and ex_ir.get('t') is not None and ex_ir.get('h') is not None:
                self.ir_cvs.add_capture_data(ex_label, ex_color, ex_ir.get('t'),
                                             ex_ir.get('h'), ex_ir.get('etc_db'), delay=ex_delay)
            else:
                self.ir_cvs.add_capture_empty(ex_label, ex_color, delay=ex_delay)
            self._tf_captures.append({'color': ex_color, 'label': ex_label,
                                      'group': group, 'source': f'card{i}'})
            added += 1

        if added == 0:
            return
        _alog.info(f'TF 캡처 추가  base="{base}"  +{added}  total={len(self._tf_captures)}')
        self._refresh_tf_capture_bar()
        self._save_tf_captures()

    def _refresh_tf_capture_bar(self):
        if callable(getattr(self, '_on_captures_changed', None)):
            self._on_captures_changed()

    # ── 안정화 캡쳐 ───────────────────────────────────────
    def _begin_stable_capture(self, base):
        """평균 재수렴 시작 후 폴링 → 안정되면 _capture_snapshot."""
        self._reset_avg()
        self._stabilizing = True
        self._stable_base = base
        self._stable_deadline = time.monotonic() + 5.0   # 최대 5초
        if getattr(self, '_stable_timer', None) is None:
            self._stable_timer = QTimer(self)
            self._stable_timer.timeout.connect(self._stable_poll)
        self.tf_cap_btn.setEnabled(False)
        self._stable_timer.start(150)

    def _stable_coh_ok(self):
        coh = self.mag_cvs.coh; f = self.mag_cvs.freqs
        if coh is None or f is None: return False
        f = np.asarray(f); coh = np.asarray(coh, dtype=float)
        m = (f >= 100) & (f <= 10000)
        if not np.any(m): return False
        return float(np.mean(coh[m])) >= 0.85

    def _stable_poll(self):
        converged = self._n_avg >= self._avg_target
        coh_ok = self._stable_coh_ok()
        timeout = time.monotonic() >= self._stable_deadline
        self.avg_lbl.setText(f'Stabilizing… {self._n_avg}/{self._avg_target}')
        if (converged and coh_ok) or timeout:
            self._stable_timer.stop()
            self._stabilizing = False
            self.tf_cap_btn.setEnabled(True)
            if timeout and not (converged and coh_ok):
                self.avg_lbl.setText('낮은 코히런스 — 그대로 캡쳐됨')
                _alog.warning('안정화 캡쳐 타임아웃 — 코히런스 미달 상태로 캡쳐')
            self._capture_snapshot(self._stable_base)

    # ── Reference / Delta 비교 ───────────────────────────
    def _on_set_reference(self, idx):
        """캡쳐 하나를 Δ 비교 기준으로 지정. idx<0 또는 범위밖이면 해제."""
        valid = (idx is not None and 0 <= idx < len(self._tf_captures))
        for j, m in enumerate(self._tf_captures):
            m['is_ref'] = (valid and j == idx)
        if valid:
            self._ref_capture_idx = idx
            mc = self.mag_cvs._captures[idx]   if idx < len(self.mag_cvs._captures)   else None
            pc = self.phase_cvs._captures[idx] if idx < len(self.phase_cvs._captures) else None
            if mc is not None:
                self.mag_cvs.set_reference(mc.get('f'), mc.get('mag'))
            if pc is not None:
                self.phase_cvs.set_reference(pc.get('f'), pc.get('ph_wrap'),
                                             pc.get('ph_unwr'), pc.get('grp_ms'))
            _alog.info(f'TF Reference 지정  idx={idx}  label="{self._tf_captures[idx].get("label")}"')
        else:
            self._ref_capture_idx = None
            self.mag_cvs.set_reference(None, None)
            self.phase_cvs.set_reference(None, None, None, None)
            if getattr(self, '_delta_on', False):
                self._set_delta(False)   # 기준 해제 시 델타 모드도 끔
            _alog.info('TF Reference 해제')
        self._refresh_tf_capture_bar()

    def _set_delta(self, on):
        """Δ(라이브 − 기준) 비교 뷰 토글."""
        on = bool(on)
        if on and self._ref_capture_idx is None:
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.information(self, 'Delta', '먼저 캡쳐 하나를 기준(R)으로 지정하세요.')
            if hasattr(self, 'delta_btn'):
                self.delta_btn.blockSignals(True); self.delta_btn.setChecked(False)
                self.delta_btn.blockSignals(False)
            return
        self._delta_on = on
        self.mag_cvs.set_delta_mode(on)
        self.phase_cvs.set_delta_mode(on)
        if hasattr(self, 'delta_btn') and self.delta_btn.isChecked() != on:
            self.delta_btn.blockSignals(True); self.delta_btn.setChecked(on)
            self.delta_btn.blockSignals(False)
        _alog.info(f'TF Delta 모드 {"ON" if on else "OFF"}')

    def _export_tf_captures(self):
        """TF 캡쳐 전체를 CSV(주파수/Mag/Phase/Coh) + 현재 화면 PNG 로 내보내기."""
        from PyQt5.QtWidgets import QFileDialog, QMessageBox
        if not self._tf_captures:
            QMessageBox.information(self, 'Export', 'TF 캡처가 없습니다.')
            return
        # 폴더 선택 다이얼로그 — accept 버튼을 '내보내기'로 (macOS 기본 'Open' 대신 명확하게)
        dlg = QFileDialog(self, '내보낼 폴더 선택')
        dlg.setFileMode(QFileDialog.Directory)
        dlg.setOption(QFileDialog.ShowDirsOnly, True)
        dlg.setLabelText(QFileDialog.Accept, '내보내기')
        if dlg.exec_() != QFileDialog.Accepted:
            return
        sel = dlg.selectedFiles()
        d = sel[0] if sel else ''
        if not d:
            return
        import csv, os, datetime
        stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        csv_path = os.path.join(d, f'tf_captures_{stamp}.csv')
        try:
            with open(csv_path, 'w', newline='', encoding='utf-8') as f:
                w = csv.writer(f)
                w.writerow(['capture', 'freq_hz', 'mag_db', 'phase_deg', 'coherence'])
                for i, meta in enumerate(self._tf_captures):
                    if i >= len(self.mag_cvs._captures):
                        continue
                    mc = self.mag_cvs._captures[i]
                    pc = self.phase_cvs._captures[i] if i < len(self.phase_cvs._captures) else None
                    fr = np.asarray(mc['f']); mg = np.asarray(mc['mag'])
                    coh = mc.get('coh')
                    ph = None
                    if pc is not None and pc.get('ph_wrap') is not None:
                        ph = np.asarray(pc['ph_wrap'])
                        if len(ph) != len(fr) and pc.get('f') is not None:
                            ph = np.interp(fr, np.asarray(pc['f']), ph)
                    label = meta.get('label', f'Capture{i+1}')
                    for k in range(len(fr)):
                        w.writerow([label, f'{fr[k]:.3f}', f'{mg[k]:.3f}',
                                    f'{ph[k]:.3f}' if ph is not None else '',
                                    f'{float(coh[k]):.4f}' if coh is not None and k < len(coh) else ''])
            # 현재 화면 PNG
            for name, cvs in [('magnitude', self.mag_cvs), ('phase', self.phase_cvs), ('ir', self.ir_cvs)]:
                png_path = os.path.join(d, f'tf_{name}_{stamp}.png')
                cvs.grab().save(png_path)
            _alog.info(f'TF Export 완료  dir={d}')
            QMessageBox.information(self, 'Export',
                                    f'내보내기 완료:\n{csv_path}\n+ Mag/Phase/IR PNG')
        except Exception as e:
            _alog.warning(f'TF Export 실패: {e}')
            QMessageBox.warning(self, 'Export', f'내보내기 실패:\n{e}')

    def _do_tf_average(self):
        if not self._tf_captures:
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.information(self, 'TF Average', 'TF 캡처가 없습니다.')
            return
        dlg = _TFAverageDialog(self._tf_captures, self)
        if dlg.exec_() != QDialog.Accepted:
            return
        sel_idxs = dlg.selected_indices()
        if len(sel_idxs) < 2:
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.information(self, 'TF Average', '2개 이상의 캡처를 선택해 주세요.')
            return
        mag_caps = [self.mag_cvs._captures[i] for i in sel_idxs if i < len(self.mag_cvs._captures)]
        ph_caps  = [self.phase_cvs._captures[i] for i in sel_idxs if i < len(self.phase_cvs._captures)]
        ir_caps  = [self.ir_cvs._captures[i] for i in sel_idxs if i < len(self.ir_cvs._captures)]
        if not mag_caps or not ph_caps: return
        f_ref = mag_caps[0]['f']
        H_sum = np.zeros(len(f_ref), dtype=complex)
        for mc, pc in zip(mag_caps, ph_caps):
            mag_db = mc['mag']
            ph_deg = pc.get('ph_wrap')
            if ph_deg is None: ph_deg = np.zeros_like(mag_db)
            if not np.array_equal(mc['f'], f_ref):
                mag_db = np.interp(f_ref, mc['f'], mag_db)
                ph_deg = np.interp(f_ref, pc['f'], ph_deg)
            H_sum += 10**(mag_db/20.0) * np.exp(1j * np.deg2rad(ph_deg))
        H_avg = H_sum / len(mag_caps)
        mag_avg  = 20 * np.log10(np.maximum(np.abs(H_avg), 1e-10))
        ph_wrap  = np.rad2deg(np.angle(H_avg))
        ph_unwr  = np.rad2deg(np.unwrap(np.deg2rad(ph_wrap)))
        if len(f_ref) > 1:
            df   = np.diff(f_ref)
            dphi = np.diff(np.deg2rad(ph_unwr))
            grp  = np.append(-dphi / (2*np.pi*np.maximum(df,1e-6)) * 1000, 0.0)
        else:
            grp = np.zeros(len(f_ref))
        n     = len(self._tf_captures)
        label = f'Avg({n})'
        color = _auto_capture_color(n)
        group = getattr(self, '_current_tf_group', '')
        self.mag_cvs._captures.append({
            'f': f_ref.copy(), 'mag': mag_avg, 'coh': None, 'color': color, 'label': label})
        self.phase_cvs._captures.append({
            'f': f_ref.copy(), 'ph_wrap': ph_wrap, 'ph_unwr': ph_unwr,
            'grp_ms': grp, 'coh': None, 'color': color, 'label': label})
        valid_ir = [ic for ic in ir_caps if ic.get('t') is not None and ic.get('h') is not None]
        if valid_ir:
            t_ref = valid_ir[0]['t']
            h_sum = np.zeros(len(t_ref))
            for ic in valid_ir:
                h = ic['h']
                if not np.array_equal(ic['t'], t_ref): h = np.interp(t_ref, ic['t'], h)
                h_sum += h
            h_avg = h_sum / len(valid_ir)
            self.ir_cvs._captures.append({
                't': t_ref.copy(), 'h': h_avg,
                'etc_db': 20*np.log10(np.maximum(np.abs(h_avg), 1e-10)),
                'color': color, 'label': label})
        else:
            # 유효 IR 없음 — _tf_captures 인덱스 정합 위해 빈 IR 캡쳐 추가
            self.ir_cvs._captures.append({
                't': None, 'h': None, 'etc_db': None, 'color': color, 'label': label})
        self._tf_captures.append({'color': color, 'label': label,
                                  'group': group, 'source': 'avg'})
        for cvs in (self.mag_cvs, self.phase_cvs, self.ir_cvs):
            cvs._cap_pix = None; cvs.update()
        _alog.info(f'TF Average 생성  label="{label}"  from {len(sel_idxs)} captures')
        self._refresh_tf_capture_bar()
        self._save_tf_captures()

    def _on_tf_capture_delete(self, idx):
        if 0 <= idx < len(self._tf_captures):
            label = self._tf_captures[idx].get('label', str(idx))
            was_ref = bool(self._tf_captures[idx].get('is_ref', False))
            self.mag_cvs.remove_capture(idx)
            self.phase_cvs.remove_capture(idx)
            self.ir_cvs.remove_capture(idx)
            self._tf_captures.pop(idx)
            # Δ 기준 캡쳐 정리 — 플래그 기준으로 재동기화 (재정렬에도 안전)
            if was_ref:
                self._on_set_reference(-1)   # 기준 삭제됨 → 해제 (델타도 끔)
            else:
                self._ref_capture_idx = next(
                    (j for j, m in enumerate(self._tf_captures) if m.get('is_ref')), None)
            _alog.info(f'TF 캡처 삭제  label="{label}"  remaining={len(self._tf_captures)}')
            self._refresh_tf_capture_bar()
            self._save_tf_captures()

    def _on_tf_capture_select(self, idx):
        if 0 <= idx < len(self._tf_captures):
            self.mag_cvs.bring_to_front(idx)
            self.phase_cvs.bring_to_front(idx)
            self.ir_cvs.bring_to_front(idx)
            # 선택 캡처의 임펄스 피크로 IR 센터 정렬 (라벨은 paintEvent 가 그 캡처색 마커로
            # 그림 — front 캡처라 ▷값 라벨 포함). _delay_ms 는 primary 라이브 마커 전용이라 안 건드림.
            cap = self.ir_cvs._captures[idx] if idx < len(self.ir_cvs._captures) else None
            if cap and cap.get('t') is not None and cap.get('h') is not None:
                t = np.asarray(cap['t']); h = np.asarray(cap['h'])
                if len(h) > 1 and len(t) == len(h):
                    pk = int(np.argmax(_hilbert_env(h)))
                    self._center_ir_on_delay(float(t[pk]))
            self._refresh_tf_capture_bar()

    def _on_tf_live_front(self):
        for cvs in (self.mag_cvs, self.phase_cvs, self.ir_cvs):
            cvs._live_on_top = True
            cvs._front_idx = None
            cvs._cap_pix = None; cvs.update()
        # 라이브 복귀 → 현재 front 카드 딜레이로 IR 마커/센터 복원
        self._sync_ir_delay_marker()

    # ── 컨트롤 핸들러 ────────────────────────
    def _recalc_target(self):
        self._avg_target = max(2, int(self.averaging_sec * self.sample_rate / (self.fft_size // 4)))

    def _reset_avg(self):
        with QMutexLocker(self._mutex):
            self._cross_acc = None; self._auto_acc_x = None; self._auto_acc_y = None; self._n_avg = 0
        self._extra_pair_acc = [None] * len(self._extra_pairs)

    def _delayed_restart(self):
        """분석 스트림만 재시작 — 제너레이터는 절대 건드리지 않음.
        단일 타이머: 빠른 반복 토글 시 마지막 상태로만 재시작.
        settle 구간 동안 같은 장치의 입력 스트림(이전 분석 + 모니터)을 모두 닫아
        새 입력 스트림 open 이 close 와 맞물리지 않게 한다 (CoreAudio 재구성 충돌 회피)."""
        if self._running: self._stop_analysis()  # 분석만 정지, 제너레이터 유지
        # _stop_analysis 가 입력 모니터를 재개할 수 있으므로 그 뒤에 모니터까지 확실히 닫는다.
        # → settle 동안 장치에는 제너레이터 출력만 남고 입력 스트림은 0개 (open 충돌 원천 차단).
        self._stop_mon_streams(); self._stop_input_monitor()
        if getattr(self, '_restart_timer', None) is not None:
            self._restart_timer.stop(); self._restart_timer = None
        self._restart_timer = QTimer(self)
        self._restart_timer.setSingleShot(True)
        def _do_restart():
            self._restart_timer = None
            self._start_active_pairs()
        self._restart_timer.timeout.connect(_do_restart)
        self._restart_timer.start(600)

    def _restore_gen_if_muted(self):
        """분석 재시작 후 제너레이터가 뮤트 상태면 복원."""
        if not self.sig_on_btn.isChecked(): return
        duplex_muted = (self._duplex_thread and self._duplex_thread.isRunning()
                        and getattr(self._duplex_thread, '_muted', False))
        standalone_muted = (self._sig_stream is not None and
                            getattr(self, '_standalone_muted', [False])[0])
        if duplex_muted or standalone_muted:
            self._start_sig_gen()

    def _start_active_pairs(self):
        """▶ 상태인 카드가 하나 이상 있을 때만 분석 시작."""
        primary_active = (not getattr(self, '_primary_deleted', False) and
                          bool(self._level_cards) and self._level_cards[0]._display_on)
        extra_active = any(p.get('display', False) for p in self._extra_pairs)
        if (primary_active or extra_active) and not self._running:
            self._start()

    def _on_primary_display_toggle(self, visible):
        """Primary 카드 ▶/▷ — 플래그만 변경, 스트림 절대 재시작 없음."""
        self.mag_cvs.clear(); self.phase_cvs.clear()
        if not visible:
            self._cross_acc = None; self._auto_acc_x = None; self._auto_acc_y = None; self._n_avg = 0
            self.ir_cvs.clear()   # primary 숨김 시 IR 임펄스도 지움 (extra 카드 IR은 유지)
        # 스트림은 그대로 유지 — _on_mc_chunk/_render_inner 에서 플래그 체크

    def _on_extra_display_toggle(self, idx, visible):
        """Extra 카드 ▶/▷ — 플래그만 변경, 스트림 절대 재시작 없음."""
        if idx >= len(self._extra_pairs): return
        self._extra_pairs[idx]['display'] = visible
        if not visible:
            self.mag_cvs.clear_tf_extra(idx)
            self.phase_cvs.clear_tf_extra_phase(idx)
            self.ir_cvs.clear_tf_extra(idx)
            self._extra_pair_acc[idx] = None
        # 스트림은 그대로 유지 — _on_mc_chunk/_render_inner 에서 플래그 체크

    def _on_ref_vu(self, db):
        """공유 레퍼런스 VU 바 + 레벨 레이블 업데이트."""
        if hasattr(self, '_ref_vu_bar'):
            self._ref_vu_bar.set_rms(db)
        if hasattr(self, '_ref_db_lbl'):
            c = T('red') if db > -6 else T('yellow') if db > -18 else T('text_dim')
            self._ref_db_lbl.setStyleSheet(f'color:{c};font-size:9px;')
            self._ref_db_lbl.setText(f'{db:.0f}')

    def _on_meas_start(self, pair_idx):
        """카드 Start 버튼: 분석 활성화 후 스트림 재시작."""
        if pair_idx is None:
            # Primary 카드
            if self._level_cards:
                self._level_cards[0].set_running(True)
        else:
            if 0 <= pair_idx < len(self._extra_pairs):
                self._extra_pairs[pair_idx]['display'] = True
                card = self._extra_pairs[pair_idx].get('card')
                if card: card.set_running(True)
        # 제너레이터가 켜져 있으면 분석 스트림 재시작
        if self.sig_on_btn.isChecked():
            # 외부 Ref + duplex 모드: TFDuplexThread가 M4 입력 점유 중
            # → _start()가 같은 장치에 TFSyncThread/MC 열면 CoreAudio 충돌 → standalone 전환
            ref_idx = self.ref_cb.currentData()
            if (ref_idx is not None and
                    self._duplex_thread and self._duplex_thread.isRunning()):
                self._start_sig_gen()   # duplex → standalone OutputStream으로 전환
            # 입력 분석 스트림은 즉시 열지 않고 settle 지연 후 연다 (_delayed_restart).
            # 같은 장치(M4)에서 (모니터/이전 분석) 입력 스트림 close 와 새 입력 스트림 open 이
            # 맞물리면 CoreAudio 가 장치를 재구성하며 ① 첫 스트림이 데이터를 못 주거나
            # (1카드 단독 분석 미표시) ② 라이브 제너레이터 출력에 글리치(띠띠띡) 가 낀다.
            # _reconfigure_audio(제너레이터 재생 중 600ms 지연 재시작)와 동일 패턴으로 일원화.
            self._delayed_restart()

    def _on_meas_stop(self, pair_idx):
        """카드 Stop 버튼: 분석 비활성화, 해당 채널 캔버스 지우기."""
        if pair_idx is None:
            # Primary 카드
            if self._level_cards:
                self._level_cards[0].set_running(False)
                self._level_cards[0].reset()   # 정지 → 레벨 비움
            self._cross_acc = None; self._auto_acc_x = None; self._auto_acc_y = None; self._n_avg = 0
            self.mag_cvs.clear(); self.phase_cvs.clear(); self.ir_cvs.clear()  # primary IR 임펄스도 지움
        else:
            if 0 <= pair_idx < len(self._extra_pairs):
                self._extra_pairs[pair_idx]['display'] = False
                card = self._extra_pairs[pair_idx].get('card')
                if card: card.set_running(False); card.reset()   # 정지 → 레벨 비움
                self.mag_cvs.clear_tf_extra(pair_idx)
                self.phase_cvs.clear_tf_extra_phase(pair_idx)
                self.ir_cvs.clear_tf_extra(pair_idx)
                self._extra_pair_acc[pair_idx] = None
        # 모든 카드가 Stop이면 입력 분석만 정지 — 제너레이터(출력)는 계속 재생.
        # (제너레이터는 오직 Play/Stop 버튼으로만 제어 — 카드 Stop은 분석만 중단)
        primary_active = (not getattr(self, '_primary_deleted', False) and
                          bool(self._level_cards) and self._level_cards[0]._display_on)
        extra_active = any(p.get('display', False) for p in self._extra_pairs)
        if not primary_active and not extra_active and self._running:
            self._stop_analysis()

    def _find_delay_for_pair(self, pair_idx):
        """카드별 Auto Find Delay — IR 피크로 딜레이 계산 후 해당 카드 delay_spin 업데이트."""
        import threading
        # 다른 장치 pair → 클락 비동기로 딜레이 계산 불가 → 경고
        if pair_idx is not None and pair_idx < 0:
            return   # stale/삭제된 카드 — 무시
        if pair_idx is not None and pair_idx < len(self._extra_pairs):
            p_meas_idx = self._extra_pairs[pair_idx]['meas_cb'].currentData()
            ref_idx = self.ref_cb.currentData()
            if p_meas_idx is not None and ref_idx is not None and p_meas_idx != ref_idx:
                from PyQt5.QtWidgets import QMessageBox
                QMessageBox.warning(self, 'Auto Find Delay',
                    'Ref와 Meas 장치가 다릅니다.\n\n'
                    '서로 다른 오디오 장치는 하드웨어 클럭이 다르기 때문에\n'
                    '딜레이 자동 검출이 정확하지 않을 수 있습니다.\n\n'
                    '딜레이 값은 수동으로 입력하세요.\n'
                    '(또는 Word Clock / ADAT로 클럭 동기화 후 사용)')
                return
        with QMutexLocker(self._mutex):
            if pair_idx is None:
                cross  = self._cross_acc.copy()  if self._cross_acc  is not None else None
                auto_x = self._auto_acc_x.copy() if self._auto_acc_x is not None else None
            else:
                if pair_idx >= len(self._extra_pair_acc): return
                acc = self._extra_pair_acc[pair_idx]
                if acc is None: return
                cross  = acc['cross'].copy()
                auto_x = acc['auto_x'].copy()
        if cross is None or auto_x is None: return
        fft_size = self.fft_size; sr = self.sample_rate

        def _worker():
            H = cross / np.maximum(auto_x, 1e-30)
            h = np.fft.irfft(H, n=fft_size)
            env = _hilbert_env(h)
            peak = int(np.argmax(env))
            if 0 < peak < len(env) - 1:
                y0, y1, y2 = float(env[peak-1]), float(env[peak]), float(env[peak+1])
                denom = 2*(2*y1 - y0 - y2)
                if denom > 0: peak += (y2 - y0) / denom
            if peak > fft_size // 2: peak -= fft_size
            d_ms = round(float(peak) / sr * 1000.0, 2)
            self._find_pair_result_sig.emit(pair_idx if pair_idx is not None else -1, d_ms)

        threading.Thread(target=_worker, daemon=True).start()

    def _apply_find_pair_result(self, pair_idx_enc, d_ms):
        """백그라운드 계산 완료 → 해당 카드 delay_spin 업데이트."""
        pair_idx = None if pair_idx_enc == -1 else pair_idx_enc
        if pair_idx is None:
            # Primary 카드 — 카드의 _delay_spin을 직접 설정 (툴바 hidden spin 아님)
            if self._level_cards and hasattr(self._level_cards[0], '_delay_spin'):
                self._level_cards[0]._delay_spin.setValue(d_ms)
                # _on_delay_changed가 signal로 연결되어 self.delay_ms 자동 업데이트됨
        else:
            if pair_idx < len(self._extra_pairs):
                card = self._extra_pairs[pair_idx].get('card')
                if card and hasattr(card, 'set_delay'):
                    card.set_delay(d_ms)   # 스핀 표시 갱신 (시그널 차단됨)
                    self._extra_pairs[pair_idx]['delay_ms'] = d_ms
                    self._save_tf_extra_pairs()
                    # raw H IR: 마커가 d_ms 로 이동. 이 카드가 front 면 뷰도 센터링.
                    if getattr(self, '_front_pair', None) == pair_idx:
                        self._center_ir_on_delay(d_ms)
                    else:
                        self.ir_cvs._cache = None; self.ir_cvs.update()

    def _on_extra_delay_changed(self, idx, v):
        """Extra pair delay_spin 변경 → pair dict 동기화 + 마커/센터 갱신.
        그 카드가 front 면 뷰를 그 딜레이 위치로 센터링(아니면 마커만 다음 렌더에서 갱신)."""
        if 0 <= idx < len(self._extra_pairs):
            self._extra_pairs[idx]['delay_ms'] = v
            self._save_tf_extra_pairs()
            if getattr(self, '_front_pair', None) == idx:
                self._center_ir_on_delay(v)
            else:
                self.ir_cvs._cache = None; self.ir_cvs.update()

    def _find_all_delays(self):
        """L키: 전체 카드 딜레이 파인더 팝업 (AllDelayFinderDialog)."""
        AllDelayFinderDialog(self, self).exec_()

    def _fft_changed(self, idx):
        self.fft_size = TF_FFT_SIZES[idx]; self._recalc_target(); self._reset_avg()
        self.ir_cvs.clear(); self._sync_ir_delay_marker()   # raw H IR: front 딜레이 중심 뷰
        if self._running: self._stop(); self._start()

    def _avg_changed(self, idx):
        self.averaging_sec = TF_AVG_SEC[idx]; self._recalc_target(); self._reset_avg()

    def _smooth_changed(self, idx):
        self.smooth_bpo = TF_SMOOTH_BPO[idx]; self._reset_avg()

    # IR 뷰 — front(선택) 카드의 딜레이를 가운데로. 임펄스는 raw H 라 실제 도착(=딜레이)
    # 위치에 그려지므로, front 카드 딜레이로 센터링하면 그 카드 임펄스가 화면 중앙에 온다.
    # 각 카드는 자기 딜레이에 카드색 마커를 가지며, front 전환 시 그 카드 기준으로 재센터링된다.
    _IR_VIEW_HALF = 10.0   # 센터 ±10ms

    def _set_ir_view_centered(self):
        self.ir_cvs.t_min = -self._IR_VIEW_HALF
        self.ir_cvs.t_max =  self._IR_VIEW_HALF
        self.ir_cvs._cache = None; self.ir_cvs.update()

    def _front_delay_ms(self):
        """현재 front(선택) 카드의 딜레이값 (None/-1=primary)."""
        key = getattr(self, '_front_pair', None)
        if key is None or key == -1:
            return self.delay_ms
        if 0 <= key < len(self._extra_pairs):
            return self._extra_pairs[key].get('delay_ms', 0.0)
        return 0.0

    def _on_delay_changed(self, v):
        # raw H IR: 임펄스는 실제 도착 위치. 딜레이 변경 → 마커 위치 갱신 +
        # primary 가 front 면 뷰를 그 위치로 센터링(다른 카드 front 면 뷰 불변).
        self.delay_ms = v
        self.ir_cvs._delay_ms = v
        if getattr(self, '_front_pair', None) in (None, -1):
            self._center_ir_on_delay(v)
        else:
            self.ir_cvs._cache = None; self.ir_cvs.update()

    def _center_ir_on_delay(self, center_ms):
        # 뷰를 center_ms 가운데로 ±10ms (front 카드 딜레이 / 캡처 피크 선택 시).
        half = self._IR_VIEW_HALF
        self.ir_cvs.t_min = center_ms - half
        self.ir_cvs.t_max = center_ms + half
        self.ir_cvs._cache = None; self.ir_cvs.update()

    def _sync_ir_delay_marker(self):
        """뷰를 front 카드의 딜레이 위치로 센터링 (마커는 각 카드색으로 paintEvent 가 그림).
        카드 선택/라이브 복귀/딜레이 변경 시 호출."""
        self._center_ir_on_delay(self._front_delay_ms())

    def _ir_mode_changed(self, idx):
        self.ir_cvs.set_mode(idx)

    def _phase_mode_changed(self, idx):
        self.phase_mode = idx; self.phase_cvs.set_mode(idx)

    def _sig_level_changed(self, db_val):
        self._sig_level_lin = 10 ** (db_val / 20)
        if self._sig_lvl_ref is not None: self._sig_lvl_ref[0] = self._sig_level_lin

    # ── 신호 발생기 ──────────────────────────
    def _on_gen_started(self):
        """제너레이터 ON: 동결 타이머 취소 → 분석 재개 (avg 리셋)."""
        if self._gen_off_timer is not None:
            self._gen_off_timer.stop()
            self._gen_off_timer = None
        self._gen_freeze = False
        self._reset_avg()

    def _on_gen_stopped(self):
        """제너레이터 OFF: 모든 카드 분석 즉시 정지 (화면은 마지막 TF 상태 유지)."""
        if self._gen_off_timer is not None:
            self._gen_off_timer.stop(); self._gen_off_timer = None
        if self._running:
            self._stop_analysis()

    def _auto_start(self):
        """제너레이터 ON 후 200ms 딜레이 뒤 자동 분석 시작."""
        if not self._running and self.sig_on_btn.isChecked():
            self._start()

    def _auto_stop_if_gen_off(self):
        """제너레이터 OFF 1초 후 분석 자동 정지."""
        if self._running and not self.sig_on_btn.isChecked():
            self._stop()

    def _toggle_sig_gen(self, checked):
        if checked:
            self._on_gen_started()
            self._start_sig_gen()
            # 제너레이터 ON → ▶ 활성 카드가 있으면 분석 자동 시작
            # 600ms 딜레이: macOS CoreAudio 스트림 초기화 완료 후 입력 스트림 오픈
            QTimer.singleShot(600, self._start_active_pairs)
        else:
            self._on_gen_stopped()
            # 제너레이터 OFF → 1초 후 분석 자동 정지
            if self._gen_off_timer is not None:
                self._gen_off_timer.timeout.connect(self._auto_stop_if_gen_off)
            if self._duplex_thread and self._duplex_thread.isRunning():
                self._mute_sig_gen()
            elif (self._sig_stream is not None and
                      getattr(self, '_standalone_muted', None) is not None):
                # standalone 즉시 무음화: 스트림 유지 → 재시작 시 위상/타이밍 보존 (클릭/임펄스이동 방지)
                # ref 버퍼 리셋: stale ref + ambient 마이크로 EMA 오염 방지
                self._int_ref_buf[:] = 0; self._int_ref_pos[0] = 0; self._int_ref_filled = False
                self._standalone_muted[0] = True   # 콜백이 즉시 outdata[:]=0 반환
                self.sig_on_btn.setText('Play'); _apply_txn(self.sig_on_btn, False);
                _alog.debug('_toggle_sig_gen → standalone muted instantly (streams kept alive)')
            else:
                # 스트림 없음: 완전 정지
                # OutputStream 닫힌 후 InputStream만 장기 실행 → 공유 하드웨어 idle 진입 시 노이즈
                if self._running and self.ref_cb.currentData() is None and self._meas_thread is not None:
                    try: self._meas_thread.chunk_ready.disconnect(); self._meas_thread.error_signal.disconnect()
                    except Exception: pass
                    self._meas_thread.stop(); self._meas_thread = None
                self._stop_sig_gen()
                if self._mon_active and not self._running:
                    QTimer.singleShot(0, self._start_mon_streams)

    def _pick_audio_file(self):
        """오디오 파일 선택 → 버퍼 로드 (soundfile 우선, 없으면 scipy WAV 폴백)."""
        # 스트림이 열려 있으면 완전 종료 후 버튼 리셋
        if (self._duplex_thread is not None and self._duplex_thread.isRunning()) or \
                (self._sig_stream is not None):
            self._stop_sig_gen()
            self.sig_on_btn.setChecked(False)
            self.sig_on_btn.setText('Play'); _apply_txn(self.sig_on_btn, False)
        from PyQt5.QtWidgets import QFileDialog, QMessageBox
        path, _ = QFileDialog.getOpenFileName(
            self, '오디오 파일 선택', '',
            '오디오 파일 (*.wav *.flac *.aiff *.aif *.ogg *.mp3 *.m4a *.caf);;전체 (*)')
        if not path:
            self.sig_file_btn.setChecked(False)
            if not self.sig_white_btn.isChecked() and not self.sig_sweep_btn.isChecked():
                self.sig_pink_btn.setChecked(True)
            return
        data = None; sr = None
        try:
            import soundfile as sf
            data, sr = sf.read(path, dtype='float32', always_2d=False)
        except ImportError:
            # soundfile 없음 → scipy로 WAV만 지원
            import os
            if os.path.splitext(path)[1].lower() not in ('.wav',):
                QMessageBox.warning(self, '파일 오류',
                    'WAV 이외 형식은 soundfile 패키지가 필요합니다.\n'
                    '터미널에서 설치 후 재시작:\n  pip install soundfile')
                self.sig_file_btn.setChecked(False); return
            try:
                from scipy.io import wavfile as wf
                sr, raw = wf.read(path)
                if raw.dtype == np.int16:
                    data = raw.astype(np.float32) / 32768.0
                elif raw.dtype == np.int32:
                    data = raw.astype(np.float32) / 2147483648.0
                elif raw.dtype == np.uint8:
                    data = (raw.astype(np.float32) - 128.0) / 128.0
                else:
                    data = raw.astype(np.float32)
            except Exception as e2:
                QMessageBox.warning(self, '파일 오류', f'WAV 읽기 실패:\n{e2}')
                self.sig_file_btn.setChecked(False); return
        except Exception as e:
            QMessageBox.warning(self, '파일 오류', f'파일을 읽을 수 없습니다:\n{e}')
            self.sig_file_btn.setChecked(False); return
        if data.ndim == 2:
            data = data.mean(axis=1)      # 스테레오 → 모노 믹스다운
        if sr != self.sample_rate:        # 샘플레이트 변환 (선형 보간)
            n_new = max(1, int(len(data) * self.sample_rate / sr))
            data = np.interp(np.linspace(0, len(data)-1, n_new),
                             np.arange(len(data)), data).astype(np.float32)
        pk = float(np.max(np.abs(data)))
        if pk > 1e-6: data = (data / pk * 0.9).astype(np.float32)  # 피크 정규화
        self._audio_file_buf = data
        # 버튼 텍스트에 파일명 (최대 12자) 표시
        import os; fname = os.path.basename(path)
        self.sig_file_btn.setText(f'{fname[:12]}{"…" if len(fname)>12 else ""}')  # folder 아이콘 유지
        self.sig_file_btn.setChecked(True)
        self.sig_pink_btn.setChecked(False); self.sig_white_btn.setChecked(False)
        self.sig_sweep_btn.setChecked(False)

    def _start_sig_gen(self):
        _alog.debug(f'_start_sig_gen() called  sig_stream={self._sig_stream}  duplex={self._duplex_thread}')
        self._stop_input_monitor()   # 출력 스트림 재구성 전 입력 모니터 해제 (장치 충돌 방지)
        if self.sig_file_btn.isChecked() and self._audio_file_buf is not None:
            self._pink_buf = self._audio_file_buf   # 파일 버퍼 사용 (순환 재생)
        elif self.sig_white_btn.isChecked():
            _n_white = self.sample_rate * 30
            _xfade_w = min(512, _n_white // 100)
            _raw_w = (np.random.randn(_n_white) * 0.5).astype(np.float32)
            _ramp_w = np.linspace(0.0, 1.0, _xfade_w, dtype=np.float32)
            _raw_w[:_xfade_w] *= _ramp_w          # fade-in: 루프 첫 구간 0→full
            _raw_w[-_xfade_w:] *= _ramp_w[::-1]  # fade-out: 루프 끝 full→0, wrap 클릭 제거
            self._pink_buf = _raw_w
        elif self.sig_sweep_btn.isChecked():
            n = self.sample_rate * self._sweep_dur
            buf = _gen_log_sweep(n, self.sample_rate, self._sweep_f_lo, self._sweep_f_hi)
            self._pink_buf = buf if self._sweep_asc else buf[::-1].copy()
        else:
            self._pink_buf = _gen_pink_noise(self.sample_rate*10)

        # duplex 스트림이 살아 있고 muted 상태 → 버퍼 교체 + unmute (스트림 재오픈 불필요)
        if self._duplex_thread and self._duplex_thread.isRunning() and self._duplex_thread._muted:
            self._duplex_thread.swap_buf(self._pink_buf)
            self._duplex_thread.unmute()
            _alog.debug('_start_sig_gen() → duplex unmuted (stream already alive)')
            self.sig_on_btn.setChecked(True); self.sig_on_btn.setText('Stop'); _apply_txn(self.sig_on_btn, True)
            return

        meas_idx = self.meas_cb.currentData()
        out_dev  = self.sig_out_cb.currentData()
        ref_idx  = self.ref_cb.currentData()
        mw = self.parent()
        _alog.debug(f'  main_spectrum running={getattr(mw, "_primary_sub", None) is not None}')

        # duplex는 meas_idx==out_dev (같은 장치)이고 extra pair가 없을 때만 사용.
        # extra pair가 하나라도 display=True이면 standalone으로 강제 → MultiChannelAudioThread로 묶음
        _active_extras_on_out = any(
            p.get('display', False) and p.get('meas_cb') and p['meas_cb'].currentData() == out_dev
            for p in getattr(self, '_extra_pairs', [])
        )
        # 외부 레퍼런스(입력 채널)는 standalone 출력 + 입력 스트림으로 처리 → 카드 Start/Stop 시
        # 출력 스트림을 건드리지 않아 제너레이터가 끊기지 않음 (ref+meas 는 단일 입력 스트림에서 동기 캡처).
        # duplex 는 내부 루프백 ref(출력=레퍼런스) 또는 Sweep 1-shot 캡처일 때만 필요.
        use_duplex = (meas_idx is not None and out_dev is not None and meas_idx == out_dev
                      and not _active_extras_on_out
                      and (ref_idx is None or self.sig_sweep_btn.isChecked()))

        if use_duplex:
            # 기존 측정 스레드 먼저 해제 (Start 먼저 눌렀을 때 장치 충돌 방지)
            self._stop_mon_streams()
            for th in [self._ref_thread, self._meas_thread]:
                if th:
                    try: th.chunk_ready.disconnect(); th.error_signal.disconnect()
                    except Exception: pass
                    th.stop()
            self._ref_thread = self._meas_thread = None
            if self._sync_thread:
                try: self._sync_thread.frame_ready.disconnect(); self._sync_thread.error_signal.disconnect()
                except Exception: pass
                self._sync_thread.stop(); self._sync_thread = None
            self._stop_sig_gen()

            if ref_idx is None:
                # 내부 루프백: 출력 신호를 레퍼런스로 사용 (ref_ch=None)
                ref_ch_param = None; meas_in_ch_param = self.meas_ch_cb.currentData() or 0
                _alog.debug(f'  TFDuplexThread(loopback)  in={meas_idx} out={out_dev}')
            else:
                # 외부 레퍼런스, 같은 장치 다른 채널
                ref_ch_param   = self.ref_ch_cb.currentData()  or 0
                meas_in_ch_param = self.meas_ch_cb.currentData() or 0
                _alog.debug(f'  TFDuplexThread(ext)  dev={out_dev} ref_ch={ref_ch_param} meas_ch={meas_in_ch_param}')

            if meas_idx is None or out_dev is None:
                from PyQt5.QtWidgets import QMessageBox
                QMessageBox.warning(self, 'Signal Generator', 'Measurement 장치를 먼저 선택하세요.')
                self.sig_on_btn.setChecked(False); return
            out_ch  = self.sig_out_ch_cb.currentData() or 0
            out_ch2 = self.sig_out_ch2_cb.currentData()   # None = Off
            n_out = max(out_ch + 1, (out_ch2 + 1) if out_ch2 is not None else 0)
            self._duplex_thread = TFDuplexThread(
                meas_idx, out_dev, self.sample_rate, self.fft_size,
                self._pink_buf, self._sig_level_lin, n_out, out_ch,
                ref_ch=ref_ch_param, meas_in_ch=meas_in_ch_param, out_ch2=out_ch2)
            self._duplex_thread.frame_ready.connect(self._on_frame, Qt.QueuedConnection)
            self._duplex_thread.error_signal.connect(self._on_err, Qt.QueuedConnection)
            self._duplex_thread.disconnected_signal.connect(self._on_tf_disconnect, Qt.QueuedConnection)
            self._duplex_thread.fade_done.connect(self._reset_avg, Qt.QueuedConnection)
            self._duplex_thread.sweep_captured.connect(self._on_sweep_captured, Qt.QueuedConnection)
            self._sig_lvl_ref = self._duplex_thread._sig_level_ref   # 레벨 슬라이더가 duplex에도 실시간 반영
            # 스윕 선택 시 단일-샷 캡처 모드 활성화
            if self.sig_sweep_btn.isChecked():
                self._duplex_thread.arm_sweep_capture(len(self._pink_buf))
                _alog.debug(f'  Sweep 1-shot capture armed  len={len(self._pink_buf)}')
            self._duplex_thread.start()
            _alog.debug(f'  TFDuplexThread started')
        else:
            # 다른 장치: standalone OutputStream
            # 스윕 1-shot 측정은 Duplex(입출력 같은 장치)만 지원 — 다른 장치는 클럭 미동기화
            if self.sig_sweep_btn.isChecked():
                from PyQt5.QtWidgets import QMessageBox
                QMessageBox.information(self, 'Sweep 1-shot 측정',
                    'Sweep 1-shot IR 측정은\n입력(Measurement)과 출력(Signal Out)이\n'
                    '같은 장치일 때만 지원됩니다.\n\n'
                    '외장 오디오 인터페이스를 사용하면\n입출력이 같은 장치로 설정됩니다.')
                self.sig_on_btn.setChecked(False)
                return
            # standalone 스트림 살아있고 muted 상태 → unmute만 (스트림 재오픈 없음 = 위상/타이밍 유지)
            if (self._sig_stream is not None and
                    getattr(self, '_standalone_muted', [False])[0]):
                self._standalone_muted[0] = False
                self._standalone_fade_pos[0] = 0          # fade-in 재시작
                self._standalone_buf_r[0] = self._pink_buf   # 신호 버퍼 교체
                self._int_ref_buf[:] = 0; self._int_ref_pos[0] = 0; self._int_ref_filled = False
                self._reset_avg()
                _alog.debug('_start_sig_gen() → standalone unmuted (stream kept alive)')
                self.sig_on_btn.setChecked(True); self.sig_on_btn.setText('Stop'); _apply_txn(self.sig_on_btn, True)
                return

            self._stop_sig_gen()  # 기존 sig gen만 정리
            _alog.debug(f'  DiffDevice/External → standalone OutputStream  out={out_dev}')
            if out_dev is None:
                self.sig_on_btn.setChecked(False); return

            # _int_ref_buf 초기화: 이전 실행 잔류 데이터가 첫 레퍼런스 프레임을 오염시키지 않도록
            self._int_ref_buf[:] = 0; self._int_ref_pos[0] = 0; self._int_ref_filled = False

            # standalone 무음/페이드 상태 — Stop→Play unmute 경로에서 참조 (스트림 재오픈 방지)
            self._standalone_muted      = [False]
            self._standalone_fade_pos = [0]
            self._standalone_buf_r    = [self._pink_buf]
            self._standalone_xrun     = [False]   # xrun 감지 → GUI 스레드에서 EMA 리셋

            # lvl_r: 뮤터블 컨테이너 — 레벨 변경이 실행 중 스트림에 즉시 반영됨
            lvl_r = [self._sig_level_lin]; self._sig_lvl_ref = lvl_r
            buf_r = self._standalone_buf_r; pos_r = [0]
            out_ch  = self.sig_out_ch_cb.currentData() or 0
            out_ch2 = self.sig_out_ch2_cb.currentData()   # None = Off
            n_ch = max(out_ch + 1, (out_ch2 + 1) if out_ch2 is not None else 0)
            _blk_size = 2048
            out_blk = np.zeros(_blk_size, dtype=np.float32)  # 콜백 외부에서 사전 할당
            _ir_buf = self._int_ref_buf; _ir_pos = self._int_ref_pos
            _sg_muted = self._standalone_muted
            _sg_xrun  = self._standalone_xrun
            _sg_fade_frames = int(self.sample_rate * 0.05)
            _sg_ramp = np.linspace(0.0, 1.0, _sg_fade_frames, dtype=np.float32)
            _sg_fade_pos = self._standalone_fade_pos
            def cb(outdata, frames, ti, status):
                if status:
                    _alog.warning(f'SigGen cb xrun/status: {status}')
                    _sg_xrun[0] = True   # GUI 스레드 → _render_inner()에서 EMA 리셋
                nonlocal out_blk
                if _sg_muted[0]:
                    outdata[:] = 0
                    return   # 즉시 무음: _ir_buf 업데이트 생략, 스트림 유지
                if frames > len(out_blk): out_blk = np.zeros(frames, dtype=np.float32)
                lvl=lvl_r[0]; pp=pos_r[0]; b=buf_r[0]; n=len(b); rem=frames; op=0
                if pp >= n: pp = 0   # 버퍼 교체 시 pp가 새 버퍼 범위를 벗어날 수 있음 → 리셋
                while rem>0:
                    av=n-pp; tk=min(rem,av); out_blk[op:op+tk]=b[pp:pp+tk]*lvl; op+=tk; pp=(pp+tk)%n; rem-=tk
                pos_r[0]=pp
                fp = _sg_fade_pos[0]
                if fp < _sg_fade_frames:
                    tf = min(frames, _sg_fade_frames - fp)
                    out_blk[:tf] *= _sg_ramp[fp:fp + tf]
                    _sg_fade_pos[0] = fp + frames
                outdata[:] = 0; outdata[:, out_ch] = out_blk[:frames]
                if out_ch2 is not None and out_ch2 < outdata.shape[1]:
                    outdata[:, out_ch2] = out_blk[:frames]
                # fade-in 완료 후에만 _ir_buf 업데이트: 0→1 램프 적용 구간은 레퍼런스 오염 방지를 위해 제외
                if _sg_fade_pos[0] >= _sg_fade_frames:
                    n2=len(_ir_buf); p2=_ir_pos[0]; end=p2+frames
                    if end<=n2: _ir_buf[p2:end]=out_blk[:frames]
                    else:
                        f=n2-p2; _ir_buf[p2:]=out_blk[:f]; _ir_buf[:end-n2]=out_blk[f:frames]
                    _ir_pos[0]=end%n2
            import time
            for _attempt in range(2):   # macOS AUHAL -10863 재시도 1회
                try:
                    with _no_stderr():
                        # latency='high' — 출력은 지연이 무관(노이즈 송출)하므로 큰 버퍼로 robust하게.
                        # TF탭+다카드 페인팅이 메인스레드를 길게 점유해도 큰 출력버퍼가 흡수 → click 방지.
                        # 입력은 _HI_LAT(40ms) 유지 → Spectrum 빠름(입력/출력 latency 분리 설계).
                        self._sig_stream = sd.OutputStream(device=out_dev, samplerate=self.sample_rate,
                                                            channels=n_ch, dtype='float32',
                                                            blocksize=_blk_size,
                                                            latency='high', callback=cb)
                        self._sig_stream.start()
                    try:
                        _alog.info(f'[DIAG] OutputStream started out={out_dev} ch={n_ch} '
                                   f'req(bs={_blk_size},lat=high) actual(bs={self._sig_stream.blocksize},lat={self._sig_stream.latency})')
                    except Exception:
                        _alog.debug(f'  OutputStream started  out={out_dev} sr={self.sample_rate} ch={n_ch}')
                    break
                except Exception as e:
                    _alog.warning(f'  OutputStream attempt {_attempt+1} failed: {e}')
                    if self._sig_stream:
                        try: self._sig_stream.close()
                        except Exception: pass
                        self._sig_stream = None
                    if _attempt == 0:
                        time.sleep(0.15)   # AUHAL 해제 대기 후 재시도
                    else:
                        self.sig_on_btn.setChecked(False)
                        from PyQt5.QtWidgets import QMessageBox
                        QMessageBox.warning(self, 'Signal Generator', f'출력 장치 오류:\n{e}'); return

            # OutputStream 오픈 완료 후 meas_thread 오픈:
            # OutputStream(DAC 초기화) 먼저 → InputStream 나중 = 노이즈 없는 순서
            # Start→Play / Play→Stop→Play 재시작 모두 이 경로로 통일
            if self._running and self.ref_cb.currentData() is None and self._meas_thread is None and meas_idx is not None:
                _alog.debug('  Internal ref: opening meas AudioThread AFTER OutputStream (noise-free order)')
                meas_ch = self.meas_ch_cb.currentData() or 0
                self._meas_thread = _EngineChannelSource(self._engine, meas_idx, self.sample_rate, self.fft_size, meas_ch, force_latency='high')
                self._meas_thread.chunk_ready.connect(self._on_meas, Qt.QueuedConnection)
                self._meas_thread.error_signal.connect(self._on_err, Qt.QueuedConnection)
                self._meas_thread.disconnected_signal.connect(self._on_tf_disconnect, Qt.QueuedConnection)
                self._meas_thread.start()
                self._reset_avg()

        self.sig_on_btn.setChecked(True); self.sig_on_btn.setText('Stop'); _apply_txn(self.sig_on_btn, True)
        # 제너레이터 재생 시작 → 분석 미실행이면 입력 레벨 모니터 시작 (정지 카드도 레벨 표시)
        if not self._running:
            QTimer.singleShot(150, self._refresh_input_monitor)

    def _mute_sig_gen(self):
        """TFDuplexThread는 살려둔 채 출력 무음화 — M4 idle beep 방지."""
        if self._duplex_thread and self._duplex_thread.isRunning():
            self._duplex_thread.mute()
            _alog.debug('_mute_sig_gen() → duplex muted (stream kept alive)')
        elif self._sig_stream:
            try: self._sig_stream.stop(); self._sig_stream.close()
            except Exception: pass
            self._sig_stream = None; self._sig_lvl_ref = None
        self.sig_on_btn.setText('Play'); _apply_txn(self.sig_on_btn, False); self.sig_on_btn.setChecked(False)
        self.sig_on_btn.setStyleSheet(f'background:{T("panel")};color:{T("text_dim")};'
                                       f'border:1px solid {T("border")};padding:4px;border-radius:{RADIUS_CTRL}px;font-weight:bold;')

    def _stop_sig_gen(self):
        _alog.debug(f'_stop_sig_gen() called  sig_stream={self._sig_stream}  duplex={self._duplex_thread}')
        if self._sig_stream:
            try: self._sig_stream.stop(); self._sig_stream.close()
            except Exception: pass
            self._sig_stream = None; self._sig_lvl_ref = None
            _alog.debug('  OutputStream closed')
        if self._duplex_thread:
            try:
                self._duplex_thread.frame_ready.disconnect()
                self._duplex_thread.error_signal.disconnect()
            except Exception: pass
            self._duplex_thread.stop(); self._duplex_thread = None
            _alog.debug('  TFDuplexThread closed')
        self.sig_on_btn.setText('Play'); _apply_txn(self.sig_on_btn, False); self.sig_on_btn.setChecked(False)
        self.sig_on_btn.setStyleSheet(f'background:{T("panel")};color:{T("text_dim")};'
                                       f'border:1px solid {T("border")};padding:4px;border-radius:{RADIUS_CTRL}px;font-weight:bold;')
        self._stop_input_monitor()   # 제너레이터 정지 → 입력 모니터도 정지

    def closeEvent(self, e):
        self._timer.stop(); self._stop(); self._stop_mon_streams(); self._stop_sig_gen()
        if hasattr(self, '_key_filter'):
            QApplication.instance().removeEventFilter(self._key_filter)
        e.accept()
        if hasattr(self.parent(), 'tf_win'): self.parent().tf_win = None

# ───────────────────────────────────────────
#  캔버스 키/마우스 라우터 (앱 레벨 이벤트 필터)
# ───────────────────────────────────────────
class _CanvasKeyRouter(QObject):
    """포커스와 무관하게 커서 위치 기반으로 Up/Down 키를 올바른 캔버스로 라우팅.
    QApplication.widgetAt() 을 사용해 Retina/HiDPI 스케일링 문제를 피함."""
    def __init__(self, main_win):
        super().__init__(main_win)
        self._mw = main_win

    def _canvas_at_cursor(self):
        """현재 커서 아래에 있는 위젯에서 부모 체인을 타고 올라가 캔버스를 찾는다."""
        mw = self._mw
        w = QApplication.widgetAt(QCursor.pos())
        while w is not None:
            if w is getattr(mw, 'spectro_cvs', None):
                return 'spectro'
            if w is getattr(mw, 'oct_cvs', None):
                return 'oct'
            if w is getattr(mw, 'fft_cvs', None):
                return 'fft'
            tf = getattr(mw, 'tf_win', None)
            if tf is not None:
                if w is getattr(tf, 'ir_cvs', None):   return 'tf_ir'
                if w is getattr(tf, 'phase_cvs', None): return 'tf_phase'
                if w is getattr(tf, 'mag_cvs', None):  return 'tf_mag'
            w = w.parent()
        return None

    def eventFilter(self, obj, event):
        if event.type() != QEvent.KeyPress:
            return False
        key = event.key()
        if key not in (Qt.Key_Up, Qt.Key_Down):
            return False
        mw = self._mw
        canvas = self._canvas_at_cursor()
        if canvas in ('tf_ir', 'tf_phase', 'tf_mag'):
            return False  # TF 캔버스 keyPressEvent가 직접 처리
        if canvas == 'spectro' and getattr(mw, '_spectro_on', False):
            mw.spectro_cvs.scroll_by(-30 if key == Qt.Key_Up else 30)
            return True
        if canvas in ('oct', 'fft') or canvas is None:
            mw._db_shift(6 if key == Qt.Key_Up else -6)
            return True
        return False


# ═══════════════════════════════════════════════════════════════════
#  Stereo / Loudness  — Vectorscope + ITU-R BS.1770-4 Radar
# ═══════════════════════════════════════════════════════════════════

class StereoAudioThread(QThread):
    """두 채널을 동시에 캡처 → chunk_ready(L_chunk, R_chunk) emit."""
    chunk_ready  = pyqtSignal(object, object)
    error_signal = pyqtSignal(str)

    def __init__(self, device_idx, sample_rate, l_ch=0, r_ch=1):
        super().__init__()
        self.device_idx=device_idx; self.sample_rate=sample_rate
        self.l_ch=l_ch; self.r_ch=r_ch; self.running=False
        self._active_stream=None   # stop()에서 abort()로 즉시 장치 해제

    def run(self):
        self.running=True
        nc=max(self.l_ch, self.r_ch)+1
        lc=self.l_ch; rc=self.r_ch
        def cb(indata, frames, ti, status):
            if not self.running: return
            try:
                n=indata.shape[1]
                L=indata[:frames, min(lc,n-1)].astype(np.float32).copy()
                R=indata[:frames, min(rc,n-1)].astype(np.float32).copy()
                self.chunk_ready.emit(L, R)
            except Exception: pass
        last_err=None
        for _rnd in range(2):
            for bs,lat in ((512,'low'),(512,'high'),(0,'high')):
                try:
                    with sd.InputStream(device=self.device_idx,
                                        samplerate=self.sample_rate,
                                        channels=nc, blocksize=bs,
                                        callback=cb, latency=lat,
                                        dtype='float32') as _s:
                        self._active_stream=_s
                        try:
                            while self.running: self.msleep(100)
                        finally:
                            self._active_stream=None
                    return
                except Exception as e:
                    last_err=e
                    if not self.running: return
            if _rnd==0:
                for _ in range(15):
                    if not self.running: return
                    self.msleep(100)
        if last_err: self.error_signal.emit(str(last_err))

    def stop(self):
        self.running=False
        s=self._active_stream
        if s is not None:
            try: s.abort(ignore_errors=True)
            except Exception:
                try: s.close(ignore_errors=True)
                except Exception: pass
        if not self.wait(3000):
            _alog.warning('StereoAudioThread stop(): wait timeout — stream forced abort')


def _biquad(x, b, a, z):
    """Transposed direct form II biquad — stateful via z[0..1]."""
    b0,b1,b2=b[0],b[1],b[2]; a1,a2=a[1],a[2]
    y=np.empty_like(x)
    for i in range(len(x)):
        xi=float(x[i]); yi=b0*xi+z[0]
        z[0]=b1*xi-a1*yi+z[1]; z[1]=b2*xi-a2*yi; y[i]=yi
    return y


class _KWeightFilter:
    """ITU-R BS.1770-4 K-weighting: pre-filter(high-shelf) → RLB(high-pass)."""
    _C={
        48000:{
            'pre':([1.53512485958697,-2.69169618940638,1.19839281085285],
                   [1.0,-1.69065929318241,0.73248077421585]),
            'rlb':([1.0,-2.0,1.0],[1.0,-1.99004745483398,0.99007225036621])},
        44100:{
            'pre':([1.54652578710802,-2.70711510957900,1.20243471048052],
                   [1.0,-1.66208978614539,0.71227099093282]),
            'rlb':([1.0,-2.0,1.0],[1.0,-1.98921088568659,0.98922519346844])},
    }
    def __init__(self,sr):
        c=self._C.get(sr,self._C[48000])
        self._pb=np.array(c['pre'][0],dtype=np.float64)
        self._pa=np.array(c['pre'][1],dtype=np.float64)
        self._rb=np.array(c['rlb'][0],dtype=np.float64)
        self._ra=np.array(c['rlb'][1],dtype=np.float64)
        self._pz=np.zeros(2,dtype=np.float64)
        self._rz=np.zeros(2,dtype=np.float64)
    def process(self,x):
        y=_biquad(x.astype(np.float64),self._pb,self._pa,self._pz)
        return _biquad(y,self._rb,self._ra,self._rz).astype(np.float32)
    def reset(self): self._pz[:]=0; self._rz[:]=0


class LoudnessMeter:
    """ITU-R BS.1770-4 기반 LUFS / LRA / TruePeak 미터."""
    _BLK_MS=100  # 100ms 블록

    def __init__(self,sr):
        self.sr=sr
        self._kfl=_KWeightFilter(sr); self._kfr=_KWeightFilter(sr)
        self._blk=max(1,sr*self._BLK_MS//1000)
        self._sq_hist=deque(maxlen=30)   # 3초 = 30블록 (short-term)
        self._fast_hist=deque(maxlen=5)  # 0.5초 = 5블록 (레이더용)
        self._int_sq=[]; self._int_on=False
        self._acc_l=0.0; self._acc_r=0.0; self._acc_n=0
        self._M=-100.0; self._S=-100.0; self._S_fast=-100.0
        self._I=-100.0; self._LRA=0.0; self._TP=-100.0; self._PH=-100.0

    @staticmethod
    def _lufs(ms):
        return float(-0.691+10*math.log10(max(ms,1e-12)))

    def push(self,L,R):
        pk=max(float(np.max(np.abs(L))),float(np.max(np.abs(R))))
        pk_db=20.0*math.log10(max(pk,1e-9))
        if pk_db>self._TP: self._TP=pk_db
        if pk_db>self._PH: self._PH=pk_db
        lk=self._kfl.process(L); rk=self._kfr.process(R)
        sq_l=lk.astype(np.float64)**2; sq_r=rk.astype(np.float64)**2
        i=0; n=len(L)
        while i<n:
            space=self._blk-self._acc_n; take=min(space,n-i)
            self._acc_l+=float(np.sum(sq_l[i:i+take]))
            self._acc_r+=float(np.sum(sq_r[i:i+take]))
            self._acc_n+=take; i+=take
            if self._acc_n>=self._blk:
                ms=(self._acc_l+self._acc_r)/(2*self._blk)
                self._sq_hist.append(ms)
                self._fast_hist.append(ms)
                if self._int_on: self._int_sq.append(ms)
                self._acc_l=0.0; self._acc_r=0.0; self._acc_n=0
        N=len(self._sq_hist)
        if N>=4: self._M=self._lufs(float(np.mean(list(self._sq_hist)[-4:])))
        if N>=5: self._S_fast=self._lufs(float(np.mean(self._fast_hist)))
        if N>=10: self._S=self._lufs(float(np.mean(list(self._sq_hist))))
        self._compute_I()
        if N>=10:
            vals=np.array([self._lufs(v) for v in self._sq_hist if v>1e-12])
            if len(vals)>=4:
                self._LRA=float(max(0,np.percentile(vals,95)-np.percentile(vals,10)))

    def _compute_I(self):
        if not self._int_sq or len(self._int_sq)<10: return
        arr=np.array(self._int_sq)
        abs_gate=10**((-70+0.691)/10)
        gated=arr[arr>abs_gate]
        if len(gated)==0: return
        ms_g=float(np.mean(gated))
        rel_gate=10**((self._lufs(ms_g)-10+0.691)/10)
        g2=arr[arr>rel_gate]
        if len(g2)>0: self._I=self._lufs(float(np.mean(g2)))

    def start_integration(self):
        self._int_sq=[]; self._int_on=True; self._I=-100.0

    def stop_integration(self): self._int_on=False

    def reset(self):
        self._kfl.reset(); self._kfr.reset()
        self._sq_hist.clear(); self._fast_hist.clear(); self._int_sq=[]
        self._acc_l=0.0; self._acc_r=0.0; self._acc_n=0
        self._M=-100.0; self._S=-100.0; self._S_fast=-100.0
        self._I=-100.0; self._LRA=0.0; self._TP=-100.0; self._PH=-100.0

    @property
    def M(self): return self._M
    @property
    def S(self): return self._S
    @property
    def S_fast(self): return self._S_fast
    @property
    def I(self): return self._I
    @property
    def LRA(self): return self._LRA
    @property
    def TP(self): return self._TP
    @property
    def peak_hold(self): return self._PH


def _spec_color(frac: float, lightness: int = 160, alpha: int = 255) -> 'QColor':
    """frac 0→1 을 violet(260°)→red(0°) HSL 스펙트럼 QColor로 변환.
    라이트 테마: 흰 배경 대비 위해 명도를 낮춰 진하고 채도 높은 보석톤으로 (스코프 가독성)."""
    hue = int((1.0 - max(0.0, min(1.0, frac))) * 260)
    if _theme == 'light':
        lightness = max(55, min(135, int(lightness * 0.52)))
    c = QColor.fromHsl(hue, 255, lightness)
    c.setAlpha(alpha)
    return c

def _metric_col(hue, light=160):
    """라우드니스 메트릭 값 색 (HSL). 라이트 테마: 흰 바 대비 위해 명도 낮춤."""
    if _theme == 'light':
        light = max(70, min(150, int(light * 0.6)))
    return QColor.fromHsl(hue, 255, light).name()


class VectorscopeCanvas(QWidget):
    """L/R Lissajous 벡터스코프 + 위상 상관도 미터."""
    _BUF=4096
    popout_requested = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setMinimumSize(260,260)
        self.setMouseTracking(True)
        self._L=np.zeros(self._BUF,dtype=np.float32)
        self._R=np.zeros(self._BUF,dtype=np.float32)
        self._corr=0.0
        self._popout_rect = QRect(0,0,1,1)

    def push_chunk(self,L,R):
        n=min(len(L),self._BUF)
        self._L[:-n]=self._L[n:]; self._L[-n:]=L[-n:]
        self._R[:-n]=self._R[n:]; self._R[-n:]=R[-n:]
        ls=self._L[-512:]; rs=self._R[-512:]
        denom=math.sqrt(max(float(np.mean(ls**2))*float(np.mean(rs**2)),1e-24))
        self._corr=float(np.mean(ls*rs))/denom

    def paintEvent(self, ev):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        W, H = self.width(), self.height()
        dark = (_theme != 'light')
        def ov(a): return QColor(255, 255, 255, a) if dark else QColor(26, 38, 62, a)
        p.fillRect(0, 0, W, H, QColor(2, 2, 4) if dark else QColor(T('bg')))
        sz = min(W, H) - 56; cx = W // 2; cy = (H - 24) // 2 + 14
        r = sz // 2

        # ── Background halo ───────────────────────────────────────────
        halo = QRadialGradient(cx, cy, r * 1.8)
        if dark:
            halo.setColorAt(0.0,  QColor(50, 20, 120, 45))
            halo.setColorAt(0.45, QColor(30, 10, 80, 18))
            halo.setColorAt(1.0,  QColor(0, 0, 0, 0))
        else:
            halo.setColorAt(0.0,  QColor(120, 150, 235, 30))
            halo.setColorAt(0.45, QColor(150, 175, 240, 12))
            halo.setColorAt(1.0,  QColor(255, 255, 255, 0))
        p.setPen(Qt.NoPen); p.setBrush(QBrush(halo))
        hr = int(r * 1.8)
        p.drawEllipse(cx - hr, cy - hr, 2*hr, 2*hr)

        # ── Circle background ─────────────────────────────────────────
        p.setBrush(QColor(3, 2, 10) if dark else QColor(T('panel')))
        p.drawEllipse(cx - r, cy - r, 2*r, 2*r)

        # ── Spectrum outer ring: glow pass + crisp pass ───────────────
        ring_grad = QConicalGradient(cx, cy, 90)
        for i in range(9):
            ring_grad.setColorAt(i / 8.0, _spec_color(i / 8.0, 165, 200))
        glow_grad = QConicalGradient(cx, cy, 90)
        for i in range(9):
            glow_grad.setColorAt(i / 8.0, _spec_color(i / 8.0, 140, 55))
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QBrush(glow_grad), 7.0))
        p.drawEllipse(cx - r, cy - r, 2*r, 2*r)
        p.setPen(QPen(QBrush(ring_grad), 1.8))
        p.drawEllipse(cx - r, cy - r, 2*r, 2*r)

        # ── Reference rings ───────────────────────────────────────────
        for frac in (0.33, 0.67):
            ri = int(r * frac)
            p.setPen(QPen(ov(12 if dark else 28), 0.6))
            p.drawEllipse(cx - ri, cy - ri, 2*ri, 2*ri)

        # ── Axes ──────────────────────────────────────────────────────
        d = int(r * 0.707)
        p.setPen(QPen(ov(15 if dark else 30), 0.7, Qt.DashLine))
        p.drawLine(cx-d, cy-d, cx+d, cy+d); p.drawLine(cx-d, cy+d, cx+d, cy-d)
        p.setPen(QPen(ov(20 if dark else 40), 0.8))
        p.drawLine(cx-r, cy, cx+r, cy); p.drawLine(cx, cy-r, cx, cy+r)

        # ── Lissajous: 2-pass (glow + crisp) + bright tip ────────────
        L = self._L[-2048:]; R = self._R[-2048:]
        xs = np.clip((cx + L * r).astype(np.int32), cx-r, cx+r)
        ys = np.clip((cy - R * r).astype(np.int32), cy-r, cy+r)
        mask = (xs >= cx-r) & (xs <= cx+r) & (ys >= cy-r) & (ys <= cy+r)
        xi = xs[mask]; yi = ys[mask]; N_pts = len(xi)
        N_BUCK = 12
        if N_pts > 0:
            bsz = max(1, N_pts // N_BUCK)
            # Pass 1 — glow (wide, semi-transparent)
            for b in range(N_BUCK):
                lo = b*bsz; hi = min((b+1)*bsz, N_pts)
                if lo >= hi: continue
                col = _spec_color(b / N_BUCK, 140, int(10 + b/N_BUCK * 38))
                pts = QPolygon([QPoint(int(xi[j]), int(yi[j])) for j in range(lo, hi)])
                p.setPen(QPen(col, 4.5)); p.drawPoints(pts)
            # Pass 2 — crisp
            for b in range(N_BUCK):
                lo = b*bsz; hi = min((b+1)*bsz, N_pts)
                if lo >= hi: continue
                frac = b / N_BUCK
                col = _spec_color(frac, int(155 + frac*20), int(12 + frac*228))
                pw = 2.8 if frac > 0.85 else 1.8 if frac > 0.62 else 1.2
                pts = QPolygon([QPoint(int(xi[j]), int(yi[j])) for j in range(lo, hi)])
                p.setPen(QPen(col, pw)); p.drawPoints(pts)
            # Bright tip dot (newest sample)
            tip_x, tip_y = int(xi[-1]), int(yi[-1])
            tip_g = QRadialGradient(tip_x, tip_y, 7)
            tip_g.setColorAt(0, QColor(255, 255, 255, 230) if dark else QColor(20, 30, 52, 235))
            tip_g.setColorAt(1, QColor(255, 255, 255, 0) if dark else QColor(20, 30, 52, 0))
            p.setPen(Qt.NoPen); p.setBrush(QBrush(tip_g))
            p.drawEllipse(tip_x - 7, tip_y - 7, 14, 14)

        # ── Phase correlation bar ─────────────────────────────────────
        bw = int(sz * 0.8); bh = 7
        bx = cx - bw//2; by = cy + r + 12
        p.setPen(Qt.NoPen); p.setBrush(ov(10 if dark else 22))
        p.drawRect(bx, by, bw, bh)
        corr = max(-1.0, min(1.0, self._corr))
        cx_bar = bx + bw // 2
        fw = int(abs(corr) * (bw // 2))
        if fw > 0:
            f0, f1 = 0.5, (0.72 if corr >= 0 else 0.28)
            fill_g = QLinearGradient(cx_bar, by,
                                     cx_bar + (fw if corr >= 0 else -fw), by)
            fill_g.setColorAt(0, _spec_color(f0, 165, 200))
            fill_g.setColorAt(1, _spec_color(f1, 165, 150))
            p.setBrush(QBrush(fill_g))
            if corr >= 0: p.drawRect(cx_bar, by, fw, bh)
            else:         p.drawRect(cx_bar - fw, by, fw, bh)
        p.setPen(QPen(ov(120 if dark else 150), 1.2))
        p.drawLine(cx_bar, by - 4, cx_bar, by + bh + 4)

        corr_col = _spec_color(0.72 if corr >= 0 else 0.28, 175, 230)
        p.setFont(_qfont(CF_ANNO, True)); p.setPen(corr_col)
        p.drawText(QRect(cx_bar - 25, by - 20, 50, 16), Qt.AlignHCenter, f'{corr:+.2f}')
        p.setFont(_qfont(CF_ANNO)); p.setPen(ov(50 if dark else 120))
        p.drawText(bx - 2, by + bh + 13, '-1')
        p.drawText(cx_bar - 4, by + bh + 13, '0')
        p.drawText(bx + bw - 12, by + bh + 13, '+1')

        # ── Axis labels (spectrum-colored) ────────────────────────────
        p.setFont(_qfont(CF_ANNO, True))
        for text, tx, ty, frac in [
            ('L', cx+r+5,   cy+4,    0.85),
            ('L', cx-r-14,  cy+4,    0.15),
            ('R', cx-4,     cy-r-5,  0.50),
            ('R', cx-4,     cy+r+14, 0.50),
        ]:
            p.setPen(_spec_color(frac, 170, 180)); p.drawText(tx, ty, text)

        # ── Title + popout icon ───────────────────────────────────────
        p.setFont(_qfont(CF_ANNO, True))
        p.setPen(ov(90 if dark else 130))
        lbl = 'VECTORSCOPE'
        fm_lbl = p.fontMetrics(); tw = fm_lbl.horizontalAdvance(lbl)
        p.drawText(W - tw - 8, H - 8, lbl)
        ix = W - tw - 28; iy = H - 20
        self._popout_rect = QRect(ix-2, iy-2, 18, 18)
        pen_ico = QPen(ov(80 if dark else 120), 1.0)
        p.setPen(pen_ico); p.setBrush(Qt.NoBrush)
        p.drawRect(ix+4, iy, 8, 8)
        p.fillRect(ix, iy+4, 8, 8, QColor(2, 2, 4) if dark else QColor(T('bg')))
        p.drawRect(ix, iy+4, 8, 8)

    def mouseMoveEvent(self,e):
        self.setCursor(Qt.PointingHandCursor if self._popout_rect.contains(e.pos()) else Qt.ArrowCursor)

    def mousePressEvent(self,e):
        if e.button()==Qt.LeftButton and self._popout_rect.contains(e.pos()):
            self.popout_requested.emit()


class LoudnessRadarCanvas(QWidget):
    """원형 라우드니스 레이더 디스플레이."""
    _N_SEG   = 600        # 600세그먼트 × 0.1초 = 60초 회전, 0.6°/세그먼트
    _STEP_S  = 60.0/600   # 세그먼트당 시간(초)
    _DEG_SEG = 360.0/600  # 세그먼트당 각도
    _LUFS_MIN=-60.0
    _LUFS_MAX=0.0
    popout_requested = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setMinimumSize(280,280)
        self.setMouseTracking(True)
        self._popout_rect = QRect(0,0,1,1)
        self._segs =[-100.0]*self._N_SEG
        self._peaks=[-100.0]*self._N_SEG  # 세그먼트별 순간 피크
        self._M=-100.0; self._S=-100.0; self._I=-100.0
        self._LRA=0.0; self._TP=-100.0; self._PH=-100.0
        self.target=-23.0
        self._start_t=time.monotonic()
        self._elapsed=0.0
        self._running=False
        self._timer=QTimer(self)
        self._timer.timeout.connect(self._tick)

    def start(self):
        self._start_t=time.monotonic(); self._elapsed=0.0
        self._segs =[-100.0]*self._N_SEG
        self._peaks=[-100.0]*self._N_SEG
        self._running=True; self._timer.start(50)

    def stop(self): self._running=False; self._timer.stop(); self.update()

    def reset_integration(self):
        self._segs =[-100.0]*self._N_SEG
        self._peaks=[-100.0]*self._N_SEG
        self._elapsed=0.0; self._start_t=time.monotonic()
        self._I=-100.0; self._LRA=0.0; self.update()

    def reset_peak(self): self._PH=-100.0; self._peaks=[-100.0]*self._N_SEG; self.update()

    def _tick(self):
        if self._running:
            prev = int(self._elapsed / self._STEP_S) % self._N_SEG
            self._elapsed = time.monotonic() - self._start_t
            cur  = int(self._elapsed / self._STEP_S) % self._N_SEG
            if cur != prev:
                self._segs[cur]  = -100.0
                self._peaks[cur] = -100.0
        self.update()

    def update_loudness(self, M, S, I, LRA, TP, PH):
        self._M=M; self._S=S; self._I=I; self._LRA=LRA
        self._TP=TP; self._PH=PH
        if self._running:
            cur = int(self._elapsed / self._STEP_S) % self._N_SEG
            # 0.1초 단위 → Momentary(M) 사용해 빠른 변화 포착
            val = M if M > -100 else S
            if val > -100:
                self._segs[cur] = val
                if M > -100 and M > self._peaks[cur]:
                    self._peaks[cur] = M

    def _lufs_to_r(self,lufs,R_in,R_out):
        if lufs<=-100: return R_in
        t=max(0.0,min(1.0,(lufs-self._LUFS_MIN)/(self._LUFS_MAX-self._LUFS_MIN)))
        return int(R_in+(R_out-R_in)*t)

    def _lufs_color(self, lufs):
        # -52→-34: blue, -34→-16: green, -16→-4: yellow, -4→2: red
        if lufs <= -100: return QColor(0, 0, 0, 0)
        lufs = max(-52.0, min(2.0, lufs))
        pts = [(-52, 50,  90, 230, 200), (-34, 40, 210,  60, 225),
               (-16, 255, 220,   0, 240), (-4, 255,  60,  20, 250),
               (  2, 200,  20,  20, 255)]
        for i in range(len(pts)-1):
            l0,r0,g0,b0,a0=pts[i]; l1,r1,g1,b1,a1=pts[i+1]
            if l0<=lufs<=l1:
                t=(lufs-l0)/(l1-l0)
                return QColor(int(r0+t*(r1-r0)),int(g0+t*(g1-g0)),
                              int(b0+t*(b1-b0)),int(a0+t*(a1-a0)))
        return QColor(*pts[-1][1:])

    def paintEvent(self, ev):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        W, H = self.width(), self.height()
        dark = (_theme != 'light')
        def ov(a): return QColor(255, 255, 255, a) if dark else QColor(26, 38, 62, a)
        p.fillRect(0, 0, W, H, QColor(1, 1, 3) if dark else QColor(T('bg')))

        # ── Layout ────────────────────────────────────────────────
        PAD_H = 46; PAD_T = 28; PAD_B = 54
        size = min(W - PAD_H*2, H - PAD_T - PAD_B)
        cx = W // 2; cy = PAD_T + size // 2
        R_arc = size // 2
        ARC_W = max(8, int(R_arc * 0.075))
        R_out = R_arc - ARC_W - 3
        R_in  = max(14, int(R_out * 0.12))

        # ── Warm background halo ──────────────────────────────────
        halo = QRadialGradient(cx, cy, R_arc * 1.8)
        if dark:
            halo.setColorAt(0.0,  QColor(120, 30, 8, 35))
            halo.setColorAt(0.45, QColor(60, 15, 4, 12))
            halo.setColorAt(1.0,  QColor(0, 0, 0, 0))
        else:
            halo.setColorAt(0.0,  QColor(235, 175, 120, 26))
            halo.setColorAt(0.45, QColor(240, 200, 160, 10))
            halo.setColorAt(1.0,  QColor(255, 255, 255, 0))
        p.setPen(Qt.NoPen); p.setBrush(QBrush(halo))
        hr = int(R_arc * 1.8)
        p.drawEllipse(cx - hr, cy - hr, 2*hr, 2*hr)

        # ── 로즈 배경 ─────────────────────────────────────────────
        p.setPen(Qt.NoPen); p.setBrush(QColor(2, 2, 6) if dark else QColor(T('panel')))
        p.drawEllipse(cx-R_out, cy-R_out, 2*R_out, 2*R_out)

        # ── 로즈 그리드 (방사선만) ────────────────────────────────
        p.setPen(QPen(ov(10 if dark else 26), 0.6))
        for deg in range(0, 360, 30):
            a = math.radians(90.0 - deg)
            p.drawLine(int(cx+R_in*math.cos(a)), int(cy-R_in*math.sin(a)),
                       int(cx+R_out*math.cos(a)), int(cy-R_out*math.sin(a)))

        # ── 내부 로즈 (스펙트럼 그라디언트, 2-pass bloom) ─────────────
        def _gpos(lufs):
            t = max(0.0, min(1.0, (lufs - self._LUFS_MIN) / (self._LUFS_MAX - self._LUFS_MIN)))
            return (R_in + (R_out - R_in) * t) / R_out

        def _make_rose_grad(alpha_scale):
            g = QRadialGradient(cx, cy, R_out)
            g.setColorAt(0.0,          _spec_color(0.0,  140, 0))
            g.setColorAt(_gpos(-52),   _spec_color(0.0,  148, int(190*alpha_scale)))
            g.setColorAt(_gpos(-34),   _spec_color(0.25, 150, int(195*alpha_scale)))
            g.setColorAt(_gpos(-16),   _spec_color(0.60, 152, int(205*alpha_scale)))
            g.setColorAt(_gpos( -4),   _spec_color(0.85, 155, int(210*alpha_scale)))
            g.setColorAt(1.0,          _spec_color(1.0,  150, int(200*alpha_scale)))
            return g

        grad = _make_rose_grad(1.0)  # kept for path drawing below

        # 세그먼트별 활성 반경 (None = 데이터 없음)
        ds = self._DEG_SEG
        act = []
        for i in range(self._N_SEG):
            v = self._segs[i]
            if v <= -100:
                act.append(None)
            else:
                r = self._lufs_to_r(v, R_in, R_out)
                act.append(r if r > R_in + 1 else None)

        # 연속 활성 구간 찾기
        runs = []; rs = None
        for i in range(self._N_SEG):
            if act[i] is not None:
                if rs is None: rs = i
            else:
                if rs is not None: runs.append((rs, i)); rs = None
        if rs is not None: runs.append((rs, self._N_SEG))

        # 경로 목록 먼저 수집 → 2-pass 드로우
        rose_paths = []
        for r_s, r_e in runs:
            if r_e - r_s < 1: continue
            pts_x, pts_y = [], []
            for i in range(r_s, r_e):
                a = math.radians(90.0 - i * ds)
                pts_x.append(cx + act[i] * math.cos(a))
                pts_y.append(cy - act[i] * math.sin(a))
            ang_end_q = 90.0 - r_e * ds
            ang_end_r = math.radians(ang_end_q)
            pts_x.append(cx + act[r_e-1] * math.cos(ang_end_r))
            pts_y.append(cy - act[r_e-1] * math.sin(ang_end_r))
            ang0_q = 90.0 - r_s * ds
            ang0_r = math.radians(ang0_q)
            path = QPainterPath()
            path.moveTo(cx + R_in*math.cos(ang0_r), cy - R_in*math.sin(ang0_r))
            path.lineTo(pts_x[0], pts_y[0])
            n = len(pts_x)
            for i in range(1, n):
                i0 = max(0, i-2); i3 = min(n-1, i+1)
                x0,y0 = pts_x[i0],pts_y[i0]; x1,y1 = pts_x[i-1],pts_y[i-1]
                x2,y2 = pts_x[i],  pts_y[i];  x3,y3 = pts_x[i3], pts_y[i3]
                cp1x = x1+(x2-x0)/6; cp1y = y1+(y2-y0)/6
                cp2x = x2-(x3-x1)/6; cp2y = y2-(y3-y1)/6
                path.cubicTo(cp1x, cp1y, cp2x, cp2y, x2, y2)
            path.lineTo(cx + R_in*math.cos(ang_end_r), cy - R_in*math.sin(ang_end_r))
            path.arcTo(QRectF(cx-R_in, cy-R_in, 2*R_in, 2*R_in),
                       ang_end_q, ang0_q - ang_end_q)
            path.closeSubpath()
            rose_paths.append(path)

        # Pass 1 — glow (반투명)
        glow_rose = _make_rose_grad(0.38)
        for path in rose_paths:
            p.setPen(Qt.NoPen); p.setBrush(QBrush(glow_rose)); p.drawPath(path)
        # Pass 2 — solid
        for path in rose_paths:
            p.setPen(Qt.NoPen); p.setBrush(QBrush(grad)); p.drawPath(path)
        # Edge stroke
        edge_g = QLinearGradient(cx, cy - R_out, cx, cy + R_out)
        edge_g.setColorAt(0,   _spec_color(0.3, 175, 110))
        edge_g.setColorAt(0.5, _spec_color(0.65, 175, 145))
        edge_g.setColorAt(1,   _spec_color(0.9, 175, 100))
        for path in rose_paths:
            p.setPen(QPen(QBrush(edge_g), 1.2)); p.setBrush(Qt.NoBrush); p.drawPath(path)

        # ── 중앙 구멍 + 글로우 닷 ──────────────────────────────────
        p.setPen(Qt.NoPen); p.setBrush(QColor(2, 2, 6) if dark else QColor(T('panel')))
        p.drawEllipse(cx-R_in, cy-R_in, 2*R_in, 2*R_in)
        cdot = QRadialGradient(cx, cy, R_in)
        cdot.setColorAt(0, _spec_color(0.05, 170, 150))
        cdot.setColorAt(1, _spec_color(0.05, 140, 0))
        p.setBrush(QBrush(cdot))
        p.drawEllipse(cx-R_in, cy-R_in, 2*R_in, 2*R_in)

        # ── 히스토리 위치 선 (로즈 내부) ─────────────────────────
        if self._running:
            a = math.radians(90.0 - (self._elapsed % 60.0) * (360.0/60.0))
            p.setPen(QPen(ov(90 if dark else 120), 0.9))
            p.drawLine(int(cx+R_in*math.cos(a)), int(cy-R_in*math.sin(a)),
                       int(cx+R_out*math.cos(a)), int(cy-R_out*math.sin(a)))

        # ── 외부 원형 레벨 미터 ────────────────────────────────────
        # 7:30(하-좌, 225°) → 시계방향 300° → 4:30(하-우, 285°Qt)
        # 하단 60° 공간은 통계 텍스트 갭
        M_LO = -52.0; M_HI = 2.0
        M_START_Q = 225.0   # Qt 각도: 7:30 위치 (-52 LUFS 끝)
        M_SPAN_Q  = 300.0   # 시계방향 300°
        N_TICKS   = 72      # 틱 개수 (72 × 4.17° = 300°)
        tick_deg  = M_SPAN_Q / N_TICKS
        tick_fill = tick_deg * 0.73

        m_val  = self._M  if self._M  > -100 else M_LO - 1.0
        ph_val = self._PH if self._PH > -100 else M_LO - 1.0

        ro   = QRectF(cx-R_arc, cy-R_arc, 2*R_arc, 2*R_arc)
        ri_r = R_arc - ARC_W
        ri   = QRectF(cx-ri_r, cy-ri_r, 2*ri_r, 2*ri_r)
        ro_g = QRectF(cx-R_arc-3, cy-R_arc-3, 2*(R_arc+3), 2*(R_arc+3))
        ri_g = QRectF(cx-ri_r+3,  cy-ri_r+3,  2*(ri_r-3),  2*(ri_r-3))

        for i in range(N_TICKS):
            tick_lufs = M_LO + (i + 0.5) / N_TICKS * (M_HI - M_LO)
            frac      = (tick_lufs - M_LO) / (M_HI - M_LO)
            start_q   = M_START_Q - i * tick_deg
            span_q    = -tick_fill
            is_lit    = (m_val >= tick_lufs)
            # Glow pass
            if is_lit:
                path_g = QPainterPath()
                path_g.arcMoveTo(ro_g, start_q); path_g.arcTo(ro_g, start_q, span_q*1.2)
                path_g.arcTo(ri_g, start_q+span_q*1.2, -span_q*1.2); path_g.closeSubpath()
                p.setPen(Qt.NoPen)
                p.setBrush(QBrush(_spec_color(frac, 140, 45))); p.drawPath(path_g)
            # Crisp pass
            col = _spec_color(frac, 162, 228) if is_lit else (QColor(255, 255, 255, 8) if dark else QColor(26, 38, 62, 20))
            path = QPainterPath()
            path.arcMoveTo(ro, start_q); path.arcTo(ro, start_q, span_q)
            path.arcTo(ri, start_q+span_q, -span_q); path.closeSubpath()
            p.setPen(Qt.NoPen); p.setBrush(QBrush(col)); p.drawPath(path)

        # 피크 홀드 틱 (스펙트럼 색상)
        if ph_val >= M_LO:
            ph_t = max(0.0, min(1.0, (ph_val - M_LO) / (M_HI - M_LO)))
            ph_start_q = M_START_Q - ph_t * M_SPAN_Q
            path = QPainterPath()
            path.arcMoveTo(ro, ph_start_q); path.arcTo(ro, ph_start_q, -tick_fill)
            path.arcTo(ri, ph_start_q-tick_fill, tick_fill); path.closeSubpath()
            p.setPen(Qt.NoPen); p.setBrush(QBrush(_spec_color(ph_t, 180, 255))); p.drawPath(path)

        # ── 외부 링 (스펙트럼 레인보우: glow + crisp) ────────────────
        rring_grad = QConicalGradient(cx, cy, 90)
        for i in range(9):
            rring_grad.setColorAt(i/8.0, _spec_color(i/8.0, 165, 200))
        rring_glow = QConicalGradient(cx, cy, 90)
        for i in range(9):
            rring_glow.setColorAt(i/8.0, _spec_color(i/8.0, 140, 55))
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QBrush(rring_glow), 7.0))
        p.drawEllipse(cx-R_arc, cy-R_arc, 2*R_arc, 2*R_arc)
        p.setPen(QPen(QBrush(rring_grad), 1.5))
        p.drawEllipse(cx-R_arc, cy-R_arc, 2*R_arc, 2*R_arc)

        # ── 미터 눈금 레이블 ──────────────────────────────────────────
        def _m_ang(v): return M_START_Q - (v - M_LO) / (M_HI - M_LO) * M_SPAN_Q
        lbl_vals = [-52, -46, -40, -34, -28, -22, -16, -10, -4, 2]
        p.setFont(_qfont(CF_ANNO, True))
        fm = p.fontMetrics()
        for lv in lbl_vals:
            frac = (lv - M_LO) / (M_HI - M_LO)
            ang_q = _m_ang(lv); a = math.radians(ang_q)
            lr = R_arc + 18
            lx = cx + lr*math.cos(a); ly = cy - lr*math.sin(a)
            txt = str(lv); tw = fm.horizontalAdvance(txt)
            p.setPen(_spec_color(frac, 155, 180))
            p.drawText(int(lx-tw/2), int(ly+fm.height()//3), txt)

        # ── Target 링 ─────────────────────────────────────────────────
        t_rr = self._lufs_to_r(self.target, R_in, R_out)
        if t_rr > R_in + 2:
            p.setPen(QPen(ov(155 if dark else 175), 1.5)); p.setBrush(Qt.NoBrush)
            p.drawEllipse(cx - t_rr, cy - t_rr, 2*t_rr, 2*t_rr)
            txt = f'{int(self.target)}'
            p.setFont(_qfont(CF_ANNO, True)); fm_t = p.fontMetrics()
            tw = fm_t.horizontalAdvance(txt)
            p.setPen(ov(200 if dark else 210))
            p.drawText(int(cx - tw // 2), int(cy - t_rr - 4), txt)

        # ── 기준 링 4개 (스펙트럼 색상) ──────────────────────────────
        zone_rings = [-52, -34, -16, -4]
        p.setFont(_qfont(CF_ANNO, True))
        fm_z = p.fontMetrics()
        for lufs in zone_rings:
            frac = (lufs - M_LO) / (M_HI - M_LO)
            rr = self._lufs_to_r(lufs, R_in, R_out)
            if rr <= R_in + 2: continue
            p.setPen(QPen(_spec_color(frac, 148, 75), 1.0)); p.setBrush(Qt.NoBrush)
            p.drawEllipse(cx - rr, cy - rr, 2*rr, 2*rr)
            txt = str(lufs)
            tw = fm_z.horizontalAdvance(txt); th = fm_z.height()
            lx = int(cx + rr - tw - 5)
            ly = int(cy + th // 3)
            p.setPen(_spec_color(frac, 172, 175))
            p.drawText(lx, ly, txt)

        # Title (오른쪽 하단) + 팝아웃 아이콘
        p.setFont(_qfont(CF_ANNO, True)); p.setPen(ov(90 if dark else 130))
        lbl = 'LOUDNESS RADAR'
        fm_lbl = p.fontMetrics(); tw_l = fm_lbl.horizontalAdvance(lbl)
        p.drawText(W-tw_l-8, H-8, lbl)
        ix = W-tw_l-28; iy = H-20
        self._popout_rect = QRect(ix-2, iy-2, 18, 18)
        pen_ico = QPen(ov(80 if dark else 120), 1.0); p.setPen(pen_ico); p.setBrush(Qt.NoBrush)
        p.drawRect(ix+4, iy, 8, 8)
        p.fillRect(ix, iy+4, 8, 8, QColor(1, 1, 3) if dark else QColor(T('bg')))
        p.drawRect(ix, iy+4, 8, 8)

    def mouseMoveEvent(self,e):
        self.setCursor(Qt.PointingHandCursor if self._popout_rect.contains(e.pos()) else Qt.ArrowCursor)

    def mousePressEvent(self,e):
        if e.button()==Qt.LeftButton and self._popout_rect.contains(e.pos()):
            self.popout_requested.emit()


class StereoLoudnessPage(QWidget):
    """벡터스코프 + 라우드니스 레이더를 담는 탭 페이지."""
    error_signal = pyqtSignal(str)   # MainWindow가 버튼 리셋에 사용

    def __init__(self):
        super().__init__()
        self._sub=None; self._meter=None; self._running=False
        self._l_ch=0; self._r_ch=1
        self._build_ui()

    def _build_ui(self):
        root=QVBoxLayout(self); root.setContentsMargins(0,0,0,0); root.setSpacing(0)

        # 상단 메인 영역: vectorscope | radar
        self._main_w=QWidget(); ml=QHBoxLayout(self._main_w)
        ml.setContentsMargins(0,0,0,0); ml.setSpacing(0)
        self._ml=ml
        self._vs=VectorscopeCanvas()
        self._sep=QFrame(); self._sep.setFrameShape(QFrame.VLine)
        self._sep.setStyleSheet(f'color:{T("border")};background:{T("border")};')
        self._radar=LoudnessRadarCanvas()
        ml.addWidget(self._vs,1); ml.addWidget(self._sep); ml.addWidget(self._radar,1)
        root.addWidget(self._main_w,1)
        self._vs.popout_requested.connect(self._popout_vs)
        self._radar.popout_requested.connect(self._popout_radar)
        self._vs_win=None; self._radar_win=None

        # 스펙트럼 그라디언트 구분선 (2px)
        spec_sep = QWidget(); spec_sep.setFixedHeight(2)
        spec_sep.setStyleSheet(
            'background: qlineargradient(spread:pad, x1:0, y1:0, x2:1, y2:0, '
            'stop:0 #3300cc, stop:0.18 #0066ff, stop:0.35 #00ccaa, '
            'stop:0.52 #33cc00, stop:0.68 #ccbb00, stop:0.83 #ff5500, stop:1.0 #ff1100);'
        )
        root.addWidget(spec_sep)

        # 하단 숫자 패널
        num_bar=QWidget(); num_bar.setFixedHeight(80)
        num_bar.setObjectName('stNumBar')
        self._num_bar = num_bar
        # 다크=스코프와 동일한 T('bg')(검정)로 → 바닥 전체 단색. 라이트=흰색(bg2).
        num_bar.setStyleSheet('#stNumBar{background:%s;}' % (T('bg') if _theme != 'light' else T('bg2')))
        nl=QHBoxLayout(num_bar); nl.setContentsMargins(16,4,16,4); nl.setSpacing(0)
        self._vseps = []; self._metric_meta = []

        _tooltips = {
            '_lbl_M':  ('M  Momentary', 'LUFS',
                        '약 400ms 이동 평균 라우드니스\n'
                        '지금 이 순간의 레벨로 가장 빠르게 반응합니다.'),
            '_lbl_S':  ('S  Short-term', 'LUFS',
                        '3초 이동 평균 라우드니스\n'
                        '짧은 구간의 평균 레벨을 보여줍니다.'),
            '_lbl_I':  ('Program Loudness', 'LUFS',
                        '재생 시작부터 현재까지 전체 구간의 통합 라우드니스\n'
                        '방송 납품 기준값(예: -23 LUFS, -16 LUFS)과 비교하는 핵심 수치입니다.'),
            '_lbl_TP': ('True-peak Max', 'dBTP',
                        '디지털 클리핑 이전 단계에서 측정한 실제 피크\n'
                        '0 dBFS 이상이면 클리핑 위험. 방송 규격은 보통 -1 dBTP 이하.'),
            '_lbl_LRA':('Loudness Range', 'LU',
                        '조용한 구간과 시끄러운 구간의 차이(LRA)\n'
                        '숫자가 클수록 다이나믹 레인지가 넓음.\n'
                        '음악: 5~15 LU / 드라마·광고: 더 좁게 관리.'),
        }

        def _metric(title, unit, attr, big=False, hue=0, light=160):
            # 카드 배경을 투명으로 → 전역 QWidget{bg2} 회색을 없애고 바(stNumBar) 단색이 그대로 비침.
            w=QWidget(); w.setStyleSheet('background:transparent;')
            vl=QVBoxLayout(w); vl.setContentsMargins(0,0,0,0); vl.setSpacing(1)
            t=QLabel(title)
            t.setStyleSheet(f'font-size:{FS_SM}px;color:{self._metric_lbl_col()};letter-spacing:1px;background:transparent;')
            t.setAlignment(Qt.AlignHCenter)
            row=QWidget(); row.setStyleSheet('background:transparent;')
            rl=QHBoxLayout(row); rl.setContentsMargins(0,0,0,0); rl.setSpacing(3)
            fs=FS_METRIC_BIG if big else FS_METRIC
            v=QLabel('—')
            v.setStyleSheet(f'font-size:{fs}px;font-weight:bold;color:{_metric_col(hue, light)};background:transparent;')
            v.setAlignment(Qt.AlignRight|Qt.AlignVCenter)
            u=QLabel(unit)
            u.setStyleSheet(f'font-size:{FS_SM}px;color:{self._metric_lbl_col()};background:transparent;')
            u.setAlignment(Qt.AlignLeft|Qt.AlignVCenter)
            rl.addStretch(); rl.addWidget(v); rl.addWidget(u); rl.addStretch()
            vl.addWidget(t); vl.addWidget(row)
            if attr in _tooltips:
                tip = _tooltips[attr][2]
                w.setToolTip(tip); t.setToolTip(tip); v.setToolTip(tip); u.setToolTip(tip)
            setattr(self, attr, v)
            self._metric_meta.append((attr, hue, light, big, t, u))
            return w

        def _vsep():
            f=QFrame(); f.setFrameShape(QFrame.VLine); f.setFixedWidth(1)
            _c = '#1a1a2a' if _theme != 'light' else T('border')
            f.setStyleSheet(f'color:{_c};background:{_c};')
            self._vseps.append(f); return f

        nl.addStretch()
        nl.addWidget(_metric('M  Momentary',    'LUFS', '_lbl_M',  big=False, hue=230, light=155))
        nl.addSpacing(8); nl.addWidget(_vsep()); nl.addSpacing(8)
        nl.addWidget(_metric('S  Short-term',   'LUFS', '_lbl_S',  big=False, hue=195, light=152))
        nl.addSpacing(8); nl.addWidget(_vsep()); nl.addSpacing(8)
        nl.addWidget(_metric('Program Loudness','LUFS', '_lbl_I',  big=True,  hue=140, light=165))
        nl.addSpacing(8); nl.addWidget(_vsep()); nl.addSpacing(8)
        nl.addWidget(_metric('True-peak Max',   'dBTP', '_lbl_TP', big=True,  hue=45,  light=168))
        nl.addSpacing(8); nl.addWidget(_vsep()); nl.addSpacing(8)
        nl.addWidget(_metric('Loudness Range',  'LU',   '_lbl_LRA',big=False, hue=18,  light=152))
        nl.addStretch()
        root.addWidget(num_bar)

        self._disp_timer=QTimer(self)
        self._disp_timer.timeout.connect(self._refresh_display)
        self._disp_timer.start(80)

    def _metric_lbl_col(self):
        return '#3a3a52' if _theme != 'light' else T('text_dim')

    def restyle_theme(self):
        """테마 토글(다크↔라이트) 시 하단 메트릭 바/구분선/값색 + 스코프 재적용."""
        dark = (_theme != 'light')
        if hasattr(self, '_num_bar'):
            self._num_bar.setStyleSheet('#stNumBar{background:%s;}' % (T('bg') if dark else T('bg2')))
        _sc = '#1a1a2a' if dark else T('border')
        for f in getattr(self, '_vseps', []):
            f.setStyleSheet(f'color:{_sc};background:{_sc};')
        _lc = self._metric_lbl_col()
        for attr, hue, light, big, t_lbl, u_lbl in getattr(self, '_metric_meta', []):
            v = getattr(self, attr, None)
            fs = FS_METRIC_BIG if big else FS_METRIC
            if v is not None:
                v.setStyleSheet(f'font-size:{fs}px;font-weight:bold;color:{_metric_col(hue, light)};background:transparent;')
            t_lbl.setStyleSheet(f'font-size:{FS_SM}px;color:{_lc};letter-spacing:1px;background:transparent;')
            u_lbl.setStyleSheet(f'font-size:{FS_SM}px;color:{_lc};background:transparent;')
        if hasattr(self, '_sep'):
            self._sep.setStyleSheet(f'color:{T("border")};background:{T("border")};')
        if hasattr(self, '_vs'): self._vs.update()
        if hasattr(self, '_radar'): self._radar.update()
        for wn in (getattr(self, '_vs_win', None), getattr(self, '_radar_win', None)):
            if wn is not None: wn.setStyleSheet(f'background:{T("bg")};')

    # ── 팝아웃 ────────────────────────────────────────────────────────
    def _make_popout_win(self, canvas, title):
        # Qt.Tool + 메인창 부모 → SPL 미터처럼 풀스크린 위에 떠서 정렬 가능
        # (일반 Qt.Window 는 macOS 풀스크린에서 별도 Space 로 튀어 정렬 불가)
        win = QWidget(self.window(), Qt.Window | Qt.Tool)
        win.setWindowTitle(title)
        win.setStyleSheet(f'background:{T("bg")};')
        lay = QVBoxLayout(win); lay.setContentsMargins(0,0,0,0)
        lay.addWidget(canvas)
        # 전체화면/최대화 상태 상속 방지 → 항상 기본 사이즈로
        win.setWindowState(Qt.WindowNoState)
        win.resize(560, 560)
        try:
            scr = QApplication.primaryScreen().availableGeometry()
            win.move(scr.center().x() - 280, scr.center().y() - 280)
        except Exception:
            pass
        return win

    def _show_popout_normal(self, win, sz=600):
        """팝아웃을 항상 기본 사이즈로 — 메인 전체화면 상태 상속/타이밍 무시.
        show 직후 + 지연 콜백으로 setGeometry 강제(전체로 뜨는 것 방지)."""
        win.show()
        def _fix():
            try:
                win.setWindowState(Qt.WindowNoState)
                scr = QApplication.primaryScreen().availableGeometry()
                win.setGeometry(int(scr.center().x() - sz / 2), int(scr.center().y() - sz / 2), sz, sz)
            except Exception:
                pass
        _fix()
        QTimer.singleShot(0, _fix)
        QTimer.singleShot(80, _fix)
        QTimer.singleShot(250, _fix)

    def _popout_vs(self):
        if self._vs_win and self._vs_win.isVisible(): return
        self._ml.removeWidget(self._vs)
        self._sep.setVisible(False)
        self._vs_win = self._make_popout_win(self._vs, 'Vectorscope')
        def _vs_close(e): self._return_vs(); e.accept()
        self._vs_win.closeEvent = _vs_close
        self._show_popout_normal(self._vs_win)

    def _return_vs(self):
        if self._vs_win: self._vs_win.hide()
        self._ml.insertWidget(0, self._vs, 1)
        self._sep.setVisible(True)

    def _popout_radar(self):
        if self._radar_win and self._radar_win.isVisible(): return
        self._ml.removeWidget(self._radar)
        self._sep.setVisible(False)
        self._radar_win = self._make_popout_win(self._radar, 'Loudness Radar')
        def _radar_close(e): self._return_radar(); e.accept()
        self._radar_win.closeEvent = _radar_close
        self._show_popout_normal(self._radar_win)

    def _return_radar(self):
        if self._radar_win: self._radar_win.hide()
        self._ml.addWidget(self._radar, 1)
        self._sep.setVisible(True)

    def start(self,dev_idx,sr,l_ch,r_ch,engine):
        # 공유 오디오 엔진 구독 — 장치당 단일 스트림이라 Spectrum/TF와 같은 장치 동시 사용 가능.
        # Loudness 적분은 연속 샘플이 필요하므로 롤링 버퍼(chunk_ready)가 아닌 raw_ready 사용.
        self.stop()
        self._l_ch=l_ch; self._r_ch=r_ch
        self._meter=LoudnessMeter(sr); self._meter.start_integration()
        try:
            self._sub=engine.subscribe(dev_idx,[l_ch,r_ch],sr)
        except Exception as e:
            self._sub=None
            self._on_error(str(e)); return
        self._sub.raw_ready.connect(self._on_raw,Qt.QueuedConnection)
        self._sub.error.connect(self._on_error,Qt.QueuedConnection)
        self._sub.disconnected.connect(self._on_error,Qt.QueuedConnection)
        self._radar.start(); self._running=True

    def stop(self):
        if self._sub:
            try: self._sub.raw_ready.disconnect()
            except Exception: pass
            try: self._sub.close()
            except Exception: pass
            self._sub=None
        self._radar.stop(); self._running=False

    def reset_integration(self):
        if self._meter: self._meter.start_integration()
        self._radar.reset_integration()

    def reset_peak(self):
        if self._meter: self._meter._PH=-100.0
        self._radar.reset_peak()

    def _on_raw(self,d):
        # 엔진 raw_ready: {ch: 연속 프레임} → L/R 추출 (같은 콜백에서 나와 샘플 동기)
        L=d.get(self._l_ch); R=d.get(self._r_ch)
        if L is None or R is None: return
        self._on_chunk(L,R)

    def _on_chunk(self,L,R):
        if not self._meter: return
        self._meter.push(L,R)
        self._vs.push_chunk(L,R); self._vs.update()
        m=self._meter
        self._radar.update_loudness(m.M,m.S,m.I,m.LRA,m.TP,m.peak_hold)

    def _on_error(self,msg):
        self.stop()
        _alog.warning(f'StereoAudio 오류: {msg}')
        self.error_signal.emit(msg)

    def _refresh_display(self):
        if not self._meter or not self._running: return
        m=self._meter
        def fmt(v,unit=''):
            return f'{v:.1f}{unit}' if v>-100 else '—'
        self._lbl_M.setText(fmt(m.M))
        self._lbl_S.setText(fmt(m.S))
        self._lbl_I.setText(fmt(m.I))
        self._lbl_LRA.setText(f'{m.LRA:.1f}' if m.LRA>0 else '—')
        self._lbl_TP.setText(fmt(m.peak_hold))
        # M 라벨 색상: target=-23 기준
        if m.M>-100:
            c=(T('green') if m.M<-20 else
               T('yellow') if m.M<-16 else T('red'))
            self._lbl_M.setStyleSheet(
                f'font-size:{FS_METRIC}px;font-weight:bold;color:{c};background:transparent;')


# ───────────────────────────────────────────
#  메인 윈도우
# ───────────────────────────────────────────
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('SPECTRA')
        self.setMinimumSize(1100, 660)
        self.resize(1440, 800)

        self.audio_thread=None; self.sample_rate=48000; self.fft_size=16384
        self.audio_engine = AudioEngine(fft_size=self.fft_size)  # 장치당 단일 스트림 공유 엔진
        self._primary_sub = None   # Spectrum primary 입력 구독 핸들
        self.db_max=MAX_DB; self.db_range=96; self.db_min=self.db_max-self.db_range
        self.speed_idx=2; self.smoothing=SPEED_LEVELS[2][1]
        self.peak_hold=True; self.view_mode='oct12'; self._spectro_on=False; self.avg_count=16; self._last_oct_mode='oct12'
        self.calib_offset=0.0
        self._current_spec_group=''   # 현재 캡처가 들어갈 스펙트럼 그룹

        self._mutex=QMutex()
        self._fft_smooth=None; self._pow_smooth=None; self._avg_buf=deque(maxlen=16)
        self._spl_smooth=-100.0
        self._raw_spl_smooth=-100.0; self._raw_peak_smooth=-100.0
        self._dba_smooth=-100.0; self._dbc_smooth=-100.0
        self._pending=None
        # 멀티-장치 오버레이 (카드별 장치+채널 독립 소스)
        self._ch_extra_active = set()   # (레거시, 미사용)
        self._ch_state = {}             # {card_id: {'pow_smooth','fft_smooth','avg_buf'}}
        self._ch_pending_extra = {}     # {card_id: (freqs, avg_cal, dbfs, color)}
        self._mc_popup = None
        self._spec_extra = []           # [{id,dev_idx,dev_name,ch,sr,color,visible,sub,card,state}]
        self._spec_next_id = 1          # 0 = primary
        self._spec_front_id = 0         # 선택되어 맨 앞에 그릴 카드 (0=primary)
        self._spec_primary_name = ''    # primary 카드 사용자 지정 이름
        self._primary_card = None       # primary _SpecCard
        self._ch_cards = {}             # (레거시) 미사용
        self._primary_dev_btn_ref = None  # 팝업 위치 계산용
        self._pending_auto_fit=False
        self._auto_fit_frame_count=0
        self._dba_display_t=0.0
        self._laeq_buf = deque(maxlen=300)  # ~10s at 30fps for Level panel display
        self._lceq_buf = deque(maxlen=300)

        # A/C 가중치 테이블 (시작 전 미리 계산)
        self._aw_table=None; self._cw_table=None


        # LEQ 창 / TF 창 / SPL Meter 창
        self.leq_win = None
        self.tf_win = None
        self.spl_meter_win = None

        self._disconnected_dev_name = ''   # USB 뽑힌 장치 이름 (Refresh 시 필터링용)
        self._first_device_load = True     # 시작 시 내장 마이크 폴백 여부 판단용

        # 설정 (마이크별 캘리브레이션)
        self._settings = _load_settings()

        self._build_ui()
        self._load_devices()
        self._restore_spec_sources()   # 저장된 멀티-장치 추가 소스 카드 복원
        self._apply_theme()

        _sc = QShortcut(QKeySequence(Qt.Key_Space), self)
        _sc.setContext(Qt.ApplicationShortcut)
        _sc.activated.connect(self._space_capture)

        QTimer.singleShot(0, self._setup_macos_titlebar)

        self._render_t=QTimer(self); self._render_t.timeout.connect(self._render_frame); self._render_t.start(33)

    # ─────────────────────────────────────
    def _setup_macos_titlebar(self):
        """ctypes로 NSFullSizeContentViewWindowMask + titlebarAppearsTransparent 적용.
        콘텐츠 뷰를 네이티브 타이틀바 영역까지 확장하여 hdr 위젯이 타이틀바 행에 렌더된다."""
        try:
            import ctypes, ctypes.util
            objc = ctypes.cdll.LoadLibrary('/usr/lib/libobjc.A.dylib')
            objc.sel_registerName.restype = ctypes.c_void_p
            objc.sel_registerName.argtypes = [ctypes.c_char_p]

            def sel(name): return objc.sel_registerName(name.encode())

            def msg(restype, obj, sel_name, *args):
                argtypes = [ctypes.c_void_p, ctypes.c_void_p] + list(type(a) for a in args)
                f = objc.objc_msgSend
                f.restype = restype
                f.argtypes = argtypes
                return f(obj, sel(sel_name), *args)

            ns_view = ctypes.c_void_p(int(self.winId()))
            ns_window = msg(ctypes.c_void_p, ns_view, 'window')
            if not ns_window:
                return

            # NSFullSizeContentViewWindowMask = 1 << 15
            style = msg(ctypes.c_ulong, ns_window, 'styleMask')
            style |= (1 << 15)
            objc.objc_msgSend.restype = ctypes.c_void_p
            objc.objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong]
            objc.objc_msgSend(ns_window, sel('setStyleMask:'), ctypes.c_ulong(style))

            # titlebarAppearsTransparent = YES
            objc.objc_msgSend.restype = ctypes.c_void_p
            objc.objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_bool]
            objc.objc_msgSend(ns_window, sel('setTitlebarAppearsTransparent:'), ctypes.c_bool(True))

            # NSWindowTitleHidden = 1 — 네이티브 타이틀 텍스트 숨김 (logo_lbl로 대체)
            objc.objc_msgSend.restype = ctypes.c_void_p
            objc.objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_long]
            objc.objc_msgSend(ns_window, sel('setTitleVisibility:'), ctypes.c_long(1))
        except Exception as e:
            print(f'macOS titlebar setup failed: {e}')

    # ─────────────────────────────────────
    def _build_ui(self):
        c=QWidget(); self.setCentralWidget(c)
        root=QVBoxLayout(c); root.setSpacing(0); root.setContentsMargins(0,0,0,0)

        # ── 타이틀바 오버레이 위젯 (NSFullSizeContentViewWindowMask로 네이티브 타이틀바 영역에 렌더)
        self.hdr = QWidget(); self.hdr.setFixedHeight(38)
        self.hdr.setObjectName('mainHdr')
        hl = QHBoxLayout(self.hdr); hl.setContentsMargins(80, 0, 12, 0); hl.setSpacing(0)
        # ── 브랜드 로고: 그라디언트 웨이브 마크(캐시 QPixmap) + SPECTRA 워드마크
        self.logo_mark = QLabel(); self.logo_mark.setPixmap(_spectra_mark(20))
        self.logo_mark.setStyleSheet('background:transparent;')
        self.logo_lbl = QLabel('SPECTRA'); self.logo_lbl.setTextFormat(Qt.PlainText)
        self.logo_w = QWidget()
        _lw = QHBoxLayout(self.logo_w); _lw.setContentsMargins(0, 0, 0, 0); _lw.setSpacing(9)
        _lw.addWidget(self.logo_mark); _lw.addWidget(self.logo_lbl)
        self.status_lbl = QLabel('● Standby')
        self.theme_btn = QPushButton('Light'); self.theme_btn.setIcon(_icon('sun'))
        self.theme_btn.setFixedWidth(72); self.theme_btn.setFixedHeight(28)
        self.theme_btn.clicked.connect(self._toggle_theme)
        self.calib_btn = QPushButton('Calibration'); self.calib_btn.setIcon(_icon('sliders'))
        self.calib_btn.setFixedWidth(108); self.calib_btn.setFixedHeight(28)
        self.calib_btn.clicked.connect(self._open_calib)
        _right_w = QWidget(); _right_lay = QHBoxLayout(_right_w)
        _right_lay.setContentsMargins(0, 0, 0, 0); _right_lay.setSpacing(8)
        _right_lay.addStretch()
        _right_lay.addWidget(self.status_lbl)
        _right_lay.addWidget(self.theme_btn)
        _right_lay.addWidget(self.calib_btn)
        hl.addStretch(1)
        hl.addWidget(self.logo_w)
        hl.addSpacing(120)
        hl.addWidget(_right_w, 1)
        self.hdr.installEventFilter(self)
        root.addWidget(self.hdr)
        self.hdr_sep = QFrame(); self.hdr_sep.setFrameShape(QFrame.HLine)
        self.hdr_sep.setFixedHeight(3); self.hdr_sep.setObjectName('hdrSep')   # 시그니처 그라디언트 언더라인
        root.addWidget(self.hdr_sep)

        # ── Layer 2: 40px 탭바 — Apple segmented control style
        self.tab_bar=QWidget(); self.tab_bar.setFixedHeight(40)
        self.tab_bar.setObjectName('mainTabBar')
        tbl_outer=QHBoxLayout(self.tab_bar); tbl_outer.setContentsMargins(10,5,10,5); tbl_outer.setSpacing(0)

        self._main_seg_pill = QWidget(); self._main_seg_pill.setObjectName('mainSegPill')
        self._main_seg_pill.setStyleSheet('#mainSegPill{background:#3A3A3C;border-radius:8px;}')
        tbl=QHBoxLayout(self._main_seg_pill); tbl.setContentsMargins(2,2,2,2); tbl.setSpacing(2)
        self._tab_btns={}
        _tab_ss=(
            'QPushButton{font-size:11px;font-weight:600;border:none;'
            'background:transparent;color:#8E8E93;padding:0 4px;border-radius:6px;}'
            'QPushButton:checked{background:transparent;color:#FFFFFF;}'
            'QPushButton:hover:!checked{background:rgba(255,255,255,12);}')
        _tab_defs=[('spectrum','Spectrum'),('transfer','Transfer Function'),('stereo','Stereo Loudness')]
        for idx,(key,label) in enumerate(_tab_defs):
            b=_CheckBtn(label); b.setChecked(idx==0)
            b.setFixedHeight(30); b.setStyleSheet(_tab_ss)
            b.clicked.connect(lambda _,i=idx: self._switch_tab(i))
            tbl.addWidget(b, 1); self._tab_btns[key]=b
        tbl_outer.addWidget(self._main_seg_pill, 1)
        # 툴바 접기/펴기 토글 — 탭바 우측(툴바를 숨겨도 항상 보이게)
        tbl_outer.addSpacing(8)
        self._toolbar_btn = _ToolbarToggleBtn()
        self._toolbar_btn.clicked.connect(self._toggle_toolbar)
        tbl_outer.addWidget(self._toolbar_btn)
        root.addWidget(self.tab_bar)

        # ── toolbar_wrapper: ctrl_bar + sub_stack를 하나의 그라디언트 영역으로 감쌈
        self.toolbar_wrapper = QWidget()
        self.toolbar_wrapper.setObjectName('toolbarWrapper')
        self.toolbar_wrapper.setFixedHeight(46)
        self.toolbar_wrapper.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        tw_lay = QVBoxLayout(self.toolbar_wrapper)
        tw_lay.setContentsMargins(0,0,0,0); tw_lay.setSpacing(0)

        # ctrl_bar — 빈 위젯으로 유지 (stylesheet 참조용)
        self.ctrl_bar=QWidget(); self.ctrl_bar.setFixedHeight(0)
        self.ctrl_bar.setObjectName('ctrlBar'); self.ctrl_bar.hide()

        # 위젯 미리 생성 (INFO 패널로 이동됨)
        self.dev_cb=RoundComboBox(); self.dev_cb._align_center=True
        self.dev_cb.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.dev_cb.setMinimumWidth(100); self.dev_cb.setMaximumWidth(280); self.dev_cb.setFixedHeight(26)
        self.dev_btn=QPushButton('장치 선택')
        self.dev_btn.setMinimumWidth(100); self.dev_btn.setMaximumWidth(280); self.dev_btn.setFixedHeight(26)
        self.dev_btn.clicked.connect(self._show_device_popup)
        self.in_ch_cb=RoundComboBox(); self.in_ch_cb._align_center=True
        self.in_ch_cb.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.in_ch_cb.setMinimumWidth(50); self.in_ch_cb.setFixedHeight(26)
        self.in_ch_cb.addItem('Ch 1', 0)
        self.in_ch_cb.currentIndexChanged.connect(self._on_input_ch_changed)
        self.mic_st=QLabel()  # 숨김 — 내부 상태 참조용

        # ── Sub-controls stack (46px): 탭별 전용 컨트롤
        self.sub_stack=QStackedWidget(); self.sub_stack.setFixedHeight(46)   # wrapper(46)와 일치 — 탭 전환 시 높이 점프 방지
        self.sub_stack.setObjectName('subStack')

        # Sub-page 0: Spectrum 컨트롤
        sp0=QWidget(); sl0=QHBoxLayout(sp0)
        sl0.setContentsMargins(8,6,8,6); sl0.setSpacing(4)
        # ── 드로어 토글 + Start/Stop (이전 ctrl_bar에서 이동)
        self._drawer_btn = _DrawerToggleBtn()
        self._drawer_btn.setChecked(False)
        self._drawer_btn.clicked.connect(self._toggle_capture_drawer)
        sl0.addWidget(self._drawer_btn)
        sl0.addSpacing(4)
        self.start_btn=QPushButton('Start')
        self.start_btn.setFixedWidth(92); self.start_btn.setFixedHeight(30)
        self.start_btn.clicked.connect(self._toggle)
        sl0.addWidget(self.start_btn)
        sl0.addSpacing(8)
        # View — 모던 세그먼트 컨트롤 (라벨·구분선 제거)
        self._view_seg = _SegmentedControl(
            [('fft','FFT',44),('oct3','1/3',40),('oct12','1/12',46),('oct24','1/24',46)])
        self._view_seg.set_active('oct12')
        self._view_seg.changed.connect(self._set_view)
        sl0.addWidget(self._view_seg)
        sl0.addSpacing(6)
        self.spectro_btn=_CheckBtn('+Spectro')
        self.spectro_btn.setFixedWidth(80); self.spectro_btn.setFixedHeight(30)
        self.spectro_btn.clicked.connect(self._toggle_spectro)
        sl0.addWidget(self.spectro_btn)
        sl0.addSpacing(6)
        # Scale — 세그먼트
        self._scale_seg = _SegmentedControl([('log','Log',44),('lin','Lin',44)])
        self._scale_seg.set_active('log')
        self._scale_seg.changed.connect(lambda k: self._set_scale(k=='log'))
        sl0.addWidget(self._scale_seg)
        sl0.addSpacing(8); sl0.addWidget(self._vsep()); sl0.addSpacing(8)
        sl0.addWidget(self._lbl('SR'))
        self.sr_cb=RoundComboBox(); self.sr_cb._align_center=True
        self.sr_cb.addItems(['44.1 kHz','48 kHz','88.2 kHz','96 kHz'])
        self.sr_cb.setCurrentIndex(1); self.sr_cb.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.sr_cb.setMinimumWidth(76); self.sr_cb.setFixedHeight(30)
        self.sr_cb.currentIndexChanged.connect(self._sr_changed)
        sl0.addWidget(self.sr_cb)
        sl0.addSpacing(12)
        sl0.addWidget(self._lbl('Avg'))
        self.avg_cb=RoundComboBox(); self.avg_cb._align_center=True; self.avg_cb.addItems(['None','4x','8x','16x'])
        self.avg_cb.setCurrentIndex(3); self.avg_cb.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.avg_cb.setMinimumWidth(54); self.avg_cb.setFixedHeight(30)
        self.avg_cb.currentIndexChanged.connect(self._avg_changed)
        sl0.addWidget(self.avg_cb)
        sl0.addSpacing(12)
        sl0.addWidget(self._lbl('Peak'))
        self.peak_btn=_CheckBtn('ON'); self.peak_btn.setChecked(True)
        self.peak_btn.setFixedWidth(50); self.peak_btn.setFixedHeight(30)
        self.peak_btn.clicked.connect(self._toggle_peak)
        rst=QPushButton('Reset'); rst.setFixedWidth(62); rst.setFixedHeight(30)
        rst.clicked.connect(self._reset_peak)
        sl0.addWidget(self.peak_btn); sl0.addWidget(rst)
        sl0.addSpacing(12)
        self.spec_cap_btn = QPushButton('Capture')
        self.spec_cap_btn.setFixedWidth(68); self.spec_cap_btn.setFixedHeight(30)
        self.spec_cap_btn.setToolTip('현재 스펙트럼 캡처')
        self.spec_cap_btn.clicked.connect(self._do_spec_capture)
        sl0.addWidget(self.spec_cap_btn)
        sl0.addSpacing(12)
        sl0.addWidget(self._lbl('Hold'))
        self.hold_cb=RoundComboBox(); self.hold_cb._align_center=True
        self.hold_cb.addItems(['Fast','0.3s','0.5s','1s'])
        self.hold_cb.setCurrentIndex(3)
        self.hold_cb.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.hold_cb.setMinimumWidth(54); self.hold_cb.setFixedHeight(30)
        self.hold_cb.currentIndexChanged.connect(self._set_peak_hold_time)
        sl0.addWidget(self.hold_cb)
        sl0.addSpacing(12)
        sl0.addWidget(self._lbl('Range'))
        self.db_cb=RoundComboBox(); self.db_cb._align_center=True; self.db_cb.addItems(['72 dB','96 dB','120 dB'])
        self.db_cb.setCurrentIndex(1); self.db_cb.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.db_cb.setMinimumWidth(62); self.db_cb.setFixedHeight(30)
        self.db_cb.currentIndexChanged.connect(self._db_changed)
        sl0.addWidget(self.db_cb)
        sl0.addSpacing(12)
        sl0.addWidget(self._lbl('Speed'))
        self.spd_cb=RoundComboBox(); self.spd_cb._align_center=True
        self.spd_cb.addItems([lb for lb,*_ in SPEED_LEVELS])
        self.spd_cb.setCurrentIndex(self.speed_idx)
        self.spd_cb.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.spd_cb.setMinimumWidth(74); self.spd_cb.setFixedHeight(30)
        self.spd_cb.currentIndexChanged.connect(self._set_speed)
        sl0.addWidget(self.spd_cb)
        sl0.addSpacing(12)
        self.color_btn=QPushButton('Color')
        self.color_btn.setFixedWidth(56); self.color_btn.setFixedHeight(30)
        self.color_btn.clicked.connect(self._open_color_picker)
        sl0.addWidget(self.color_btn)
        sl0.addStretch()
        # 우측 패널(LEVEL/INFO/INPUT) 표시/숨김 토글
        self._spec_panel_btn = _RightPanelToggleBtn()
        self._spec_panel_btn.setChecked(True)
        self._spec_panel_btn.clicked.connect(self._toggle_spec_panel)
        sl0.addWidget(self._spec_panel_btn)
        self.sub_stack.addWidget(self._toolbar_scroll(sp0))  # index 0

        # Sub-page 1: Transfer 컨트롤 — tf_win.tb가 생성 후 여기로 이동됨
        self._sp1=QWidget(); self._sp1_lay=QHBoxLayout(self._sp1)
        self._sp1_lay.setContentsMargins(0,0,0,0); self._sp1_lay.setSpacing(0)
        self.sub_stack.addWidget(self._sp1)  # index 1

        # Sub-page 2: Stereo & Loudness 컨트롤
        sp2=QWidget(); sl2=QHBoxLayout(sp2)
        sl2.setContentsMargins(8,6,8,6); sl2.setSpacing(4)   # 3탭 툴바 메트릭 통일(Spectrum 기준)

        # Start/Stop 버튼
        self._st_start_btn=QPushButton('Start'); _apply_txn(self._st_start_btn, False)
        self._st_start_btn.setFixedWidth(92); self._st_start_btn.setFixedHeight(30)
        self._st_start_btn.clicked.connect(self._st_toggle)
        sl2.addWidget(self._st_start_btn)
        sl2.addSpacing(10)

        # 현재 선택된 디바이스 표시
        sl2.addWidget(self._lbl('Input'))
        sl2.addSpacing(2)
        self._st_dev_lbl=QLabel('—')
        self._st_dev_lbl.setStyleSheet(self._st_dev_lbl_ss())  # 흰색 하드코드→토큰(라이트에서 안 보이던 버그)
        self._st_dev_lbl.setMaximumWidth(240)
        sl2.addWidget(self._st_dev_lbl)
        sl2.addSpacing(10)

        # L / R 채널 선택
        sl2.addWidget(self._lbl('L'))
        self._st_l_cb=RoundComboBox(); self._st_l_cb._align_center=True
        self._st_l_cb.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self._st_l_cb.setMinimumWidth(56); self._st_l_cb.setFixedHeight(30)
        self._st_l_cb.addItem('Ch 1',0)
        sl2.addWidget(self._st_l_cb)
        sl2.addSpacing(2)
        sl2.addWidget(self._lbl('R'))
        self._st_r_cb=RoundComboBox(); self._st_r_cb._align_center=True
        self._st_r_cb.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self._st_r_cb.setMinimumWidth(56); self._st_r_cb.setFixedHeight(30)
        self._st_r_cb.addItem('Ch 2',1)
        sl2.addWidget(self._st_r_cb)
        sl2.addSpacing(10)

        # Target LUFS
        sl2.addWidget(self._lbl('Target'))
        self._st_target_cb=RoundComboBox(); self._st_target_cb._align_center=True
        self._st_target_cb.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self._st_target_cb.setMinimumWidth(84); self._st_target_cb.setFixedHeight(30)
        for lbl,val in [('-23 LUFS',-23.0),('-16 LUFS',-16.0),('-14 LUFS',-14.0),
                        ('-18 LUFS',-18.0),('-24 LUFS',-24.0)]:
            self._st_target_cb.addItem(lbl,val)
        self._st_target_cb.currentIndexChanged.connect(self._on_st_target_changed)
        sl2.addWidget(self._st_target_cb)
        sl2.addSpacing(10)

        # Reset 버튼
        _rst_int=QPushButton('Reset I'); _rst_int.setFixedWidth(68); _rst_int.setFixedHeight(30)
        _rst_int.setToolTip('Integrated LUFS 리셋')
        _rst_int.clicked.connect(lambda: self.stereo_page.reset_integration())
        sl2.addWidget(_rst_int)
        sl2.addSpacing(2)
        _rst_pk=QPushButton('Reset TP'); _rst_pk.setFixedWidth(72); _rst_pk.setFixedHeight(30)
        _rst_pk.setToolTip('True Peak hold 리셋')
        _rst_pk.clicked.connect(lambda: self.stereo_page.reset_peak())
        sl2.addWidget(_rst_pk)
        sl2.addStretch()
        self.sub_stack.addWidget(self._toolbar_scroll(sp2))   # index 2

        tw_lay.addWidget(self.sub_stack)
        root.addWidget(self.toolbar_wrapper)
        # 툴바 하단 시그니처 라인(로고블루 2px) — 툴바 내용과 분리된 별도 위젯이라 3탭 모두 확실히 표시
        self.toolbar_underline = QFrame(); self.toolbar_underline.setFixedHeight(2)
        self.toolbar_underline.setObjectName('toolbarUnderline')
        root.addWidget(self.toolbar_underline)

        # ── 메인 스택: Spectrum(0) | Transfer(1) | Stereo(2)
        self.main_stack=QStackedWidget()

        # Page 0: Spectrum (캔버스 + 정보 패널)
        page0=QWidget(); pl0=QHBoxLayout(page0)
        pl0.setSpacing(0); pl0.setContentsMargins(0,0,0,0)
        self.vu_a=VUMeter(); self.vu_a.hide()   # 숨김 — 레벨 계산 코드 유지용
        self.fft_cvs=FFTCanvas(); self.fft_cvs.hide()
        self.oct_cvs=OctaveCanvas(); self.oct_cvs.set_mode('oct12')
        self.spectro_cvs=SpectrogramCanvas(); self.spectro_cvs.hide()
        self.cvs_splitter=QSplitter(Qt.Vertical)
        self.cvs_splitter.setHandleWidth(7)   # 3탭 스플리터 핸들 폭 통일
        self.cvs_splitter.setMouseTracking(True)
        self.cvs_splitter.addWidget(self.fft_cvs)
        self.cvs_splitter.addWidget(self.oct_cvs)
        self.cvs_splitter.addWidget(self.spectro_cvs)
        pl0.addWidget(self.cvs_splitter, 1)
        pl0.addWidget(self._build_info(), 0)
        self.main_stack.addWidget(page0)  # index 0

        # Page 1: Transfer Function (임베드)
        self.tf_win=TransferFunctionWindow(self, self._settings, embedded=True)
        self.tf_win._engine = self.audio_engine   # 공유 엔진 주입 (TF 입력을 Spectrum/Stereo와 같은 스트림 공유)
        self.main_stack.addWidget(self.tf_win)  # index 1
        # tf_win.tb를 sub_stack page 1로 이동 (embedded 모드에서 tf_win은 tb를 root에 추가 안 함)
        self._sp1_lay.addWidget(self._toolbar_scroll(self.tf_win.tb))

        # Page 2: Stereo & Loudness
        self.stereo_page=StereoLoudnessPage()
        self.stereo_page.error_signal.connect(self._on_stereo_error, Qt.QueuedConnection)
        self.main_stack.addWidget(self.stereo_page)  # index 2

        body_w = QWidget()
        body_lay = QHBoxLayout(body_w)
        body_lay.setContentsMargins(0, 0, 0, 0); body_lay.setSpacing(0)
        self._capture_drawer = _CaptureDrawer()
        self._capture_drawer.delete_requested.connect(self._on_drawer_delete)
        self._capture_drawer.rename_requested.connect(self._on_drawer_rename)
        self._capture_drawer.new_group_req.connect(self._on_drawer_new_group)
        self._capture_drawer.delete_group_req.connect(self._on_drawer_delete_group)
        self._capture_drawer.reorder_requested.connect(self._on_drawer_reorder)
        self._capture_drawer.move_to_group_req.connect(self._on_drawer_move_to_group)
        self._capture_drawer.capture_selected.connect(self._on_drawer_select)
        self._capture_drawer.visibility_changed.connect(self._on_drawer_visibility)
        self._capture_drawer.average_requested.connect(self._on_drawer_average)
        self._capture_drawer.reference_changed.connect(self._on_drawer_reference)
        self._capture_drawer.export_requested.connect(self._on_drawer_export)
        self._capture_drawer.setVisible(False)
        body_lay.addWidget(self._capture_drawer, 0)
        body_lay.addWidget(self.main_stack, 1)
        root.addWidget(body_w)

        # 우측 패널 표시/숨김 상태 복원
        _spv = self._settings.get('spec_panel_visible', True)
        self._info_panel.setVisible(_spv)
        self._spec_panel_btn.setChecked(_spv); self._spec_panel_btn.update()

        # 툴바 표시/숨김 상태 복원
        _tbv = bool(self._settings.get('toolbar_visible', True))
        self.toolbar_wrapper.setVisible(_tbv); self.toolbar_underline.setVisible(_tbv)
        self._toolbar_btn.setChecked(_tbv); self._toolbar_btn.update()

        # TF 캡처 변경 시 드로어도 갱신
        self.tf_win._on_captures_changed = self._refresh_capture_drawer
        # TF 드로어 토글 버튼 연결
        self.tf_win._drawer_btn.clicked.connect(self._toggle_capture_drawer)
        # 이전 세션 캡처 복원
        QTimer.singleShot(0, self._restore_spec_captures)

        # ── 푸터
        self.ft=QWidget(); self.ft.setFixedHeight(22)
        fl=QHBoxLayout(self.ft); fl.setContentsMargins(16,0,16,0)
        fl.addWidget(QLabel('SPECTRA  |  v1.3'))
        fl.addStretch()
        jordan_lbl=QLabel('Design by Jordan')
        jordan_lbl.setStyleSheet(f'color:{T("text_dim")};font-size:10px;font-style:italic;')
        fl.addWidget(jordan_lbl)
        root.addWidget(self.ft)

    def _switch_tab(self, i):
        keys=['spectrum','transfer','stereo']
        for k,b in self._tab_btns.items():
            b.setChecked(k==keys[i])
        self.sub_stack.setCurrentIndex(i)
        self.main_stack.setCurrentIndex(i)
        self.toolbar_wrapper.setFixedHeight(46)
        self._capture_drawer.set_active_mode('tf' if i==1 else 'spec')
        # Stereo 탭: 캡처 드로어 비활성화
        if i==2: self._capture_drawer.setVisible(False)
        self._apply_tab_styles()

    def _apply_tab_styles(self):
        accent=T('accent'); text=T('text'); text_dim=T('text_dim')
        ac = QColor(accent); ar, ag, ab = ac.red(), ac.green(), ac.blue()
        for b in self._tab_btns.values():
            if b.isChecked():
                b.setStyleSheet(
                    f'border: 1px solid rgba({ar},{ag},{ab},65);'
                    f'border-radius: 7px;'
                    f'background: rgba({ar},{ag},{ab},22);'
                    f'color: {text};'
                    f'font-size: 13px; font-weight: 600;'
                    f'padding: 0 16px; min-height: 26px;')
            else:
                b.setStyleSheet(
                    f'border: none;'
                    f'border-radius: 7px;'
                    f'background: transparent;'
                    f'color: {text_dim};'
                    f'font-size: 13px;'
                    f'padding: 0 16px; min-height: 26px;')

    def _sep(self):
        w = QWidget(); w.setFixedWidth(6); return w

    def _vsep(self):
        f = QFrame(); f.setFrameShape(QFrame.VLine)
        f.setFixedWidth(1); f.setFixedHeight(22)
        f.setStyleSheet(f'color:{T("border")};background:{T("border")};')
        return f

    def _lbl(self,t):
        l=QLabel(t)
        l.setStyleSheet(ss_text(FS_BODY) + 'white-space:nowrap;')
        l.setAlignment(Qt.AlignVCenter | Qt.AlignHCenter); return l

    def _toolbar_scroll(self, content):
        """툴바 content 위젯을 가로 스크롤 영역으로 감싸 창 축소 시 압축/겹침 방지."""
        from PyQt5.QtWidgets import QScrollArea
        sc = QScrollArea()
        sc.setWidget(content)
        sc.setWidgetResizable(True)                       # 넓을 땐 viewport 채움(addStretch 동작)
        sc.setFrameShape(QFrame.NoFrame)
        sc.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        sc.viewport().setStyleSheet('background:transparent;')
        sc.setStyleSheet(
            'QScrollArea{background:transparent;border:none;}'
            'QScrollBar:horizontal{height:6px;background:transparent;margin:0;}'
            'QScrollBar::handle:horizontal{background:#48484A;border-radius:3px;min-width:40px;}'
            'QScrollBar::add-line:horizontal,QScrollBar::sub-line:horizontal{width:0;}')
        # 자연 폭 미만으로 좁아지면 압축 대신 스크롤 (폴리시 후 최종 sizeHint로 재설정)
        def _set_min():
            content.setMinimumWidth(content.sizeHint().width())
        _set_min(); QTimer.singleShot(0, _set_min)
        return sc

    def _build_info(self):
        panel=QWidget(); panel.setFixedWidth(175)
        panel.setObjectName('infoPanel')
        self._info_panel = panel
        layout=QVBoxLayout(panel); layout.setContentsMargins(10,10,10,10); layout.setSpacing(8)

        # ── Level section (top) — custom header with SPL btn
        level_w = QWidget()
        level_w.setObjectName('levelBox')
        level_lay = QVBoxLayout(level_w); level_lay.setContentsMargins(8,8,8,8); level_lay.setSpacing(4)
        hdr_row = QHBoxLayout(); hdr_row.setContentsMargins(0,0,0,6); hdr_row.setSpacing(5)
        level_icon = _SidebarIcon('level', T('accent'), 15)
        level_title = QLabel('LEVEL')
        level_title.setStyleSheet(ss_text(FS_LG, 'text_dim', True))
        spl_btn = _SplMeterBtn()
        spl_btn.clicked.connect(self._open_spl_meter)
        hdr_row.addWidget(level_icon); hdr_row.addWidget(level_title)
        hdr_row.addStretch(); hdr_row.addWidget(spl_btn)
        level_lay.addLayout(hdr_row)

        refs={}; accent_color=T('accent')
        for k,init in [('SPL','—'),('Peak Hold','—'),('Dominant','—')]:
            row=QHBoxLayout()
            kl=QLabel(k); kl.setStyleSheet(ss_text(FS_SM))
            vl=QLabel(init); vl.setStyleSheet(f'font-size:{FS_BODY}px;font-weight:bold;color:{accent_color};')
            vl.setAlignment(Qt.AlignRight)
            row.addWidget(kl); row.addWidget(vl); level_lay.addLayout(row); refs[k]=vl
        dba_row=QHBoxLayout()
        dba_lbl=QLabel('dBA'); dba_lbl.setStyleSheet(ss_text(FS_SM))
        dba_val=QLabel('—'); dba_val.setStyleSheet(f'color:{T("accent")};font-size:{FS_DISP}px;font-weight:bold;')
        dba_val.setAlignment(Qt.AlignRight)
        dba_row.addWidget(dba_lbl); dba_row.addWidget(dba_val); level_lay.addLayout(dba_row)
        dbc_row=QHBoxLayout()
        dbc_lbl=QLabel('dBC'); dbc_lbl.setStyleSheet(ss_text(FS_SM))
        dbc_val=QLabel('—'); dbc_val.setStyleSheet(f'color:{T("accent3")};font-size:{FS_DISP}px;font-weight:bold;')
        dbc_val.setAlignment(Qt.AlignRight)
        dbc_row.addWidget(dbc_lbl); dbc_row.addWidget(dbc_val); level_lay.addLayout(dbc_row)
        refs['dBA']=dba_val; refs['dBC']=dbc_val
        laeq_row=QHBoxLayout()
        laeq_lbl=QLabel('LAeq'); laeq_lbl.setStyleSheet(ss_text(FS_SM))
        laeq_val=QLabel('—'); laeq_val.setStyleSheet(f'color:{T("accent")};font-size:{FS_VAL}px;font-weight:bold;')
        laeq_val.setAlignment(Qt.AlignRight)
        laeq_row.addWidget(laeq_lbl); laeq_row.addWidget(laeq_val); level_lay.addLayout(laeq_row)
        lceq_row=QHBoxLayout()
        lceq_lbl=QLabel('LCeq'); lceq_lbl.setStyleSheet(ss_text(FS_SM))
        lceq_val=QLabel('—'); lceq_val.setStyleSheet(f'color:{T("accent3")};font-size:{FS_VAL}px;font-weight:bold;')
        lceq_val.setAlignment(Qt.AlignRight)
        lceq_row.addWidget(lceq_lbl); lceq_row.addWidget(lceq_val); level_lay.addLayout(lceq_row)
        refs['LAeq']=laeq_val; refs['LCeq']=lceq_val

        self.i_spl=refs['SPL']; self.i_pk=refs['Peak Hold']
        self.i_dom=refs['Dominant']; self.i_dba=refs['dBA']; self.i_dbc=refs['dBC']
        self.i_laeq=refs['LAeq']; self.i_lceq=refs['LCeq']
        self._i_dba_base=T('accent'); self._i_dbc_base=T('accent3')
        self._i_laeq_base=T('accent'); self._i_lceq_base=T('accent3')
        self._i_warn_db = -20.0; self._i_peak_db = -10.0
        layout.addWidget(level_w)

        # ── Info section (bottom)
        info_w = QWidget()
        info_w.setObjectName('infoBox')
        info_lay = QVBoxLayout(info_w); info_lay.setContentsMargins(8,8,8,8); info_lay.setSpacing(4)
        info_hdr = QHBoxLayout(); info_hdr.setContentsMargins(0,0,0,6); info_hdr.setSpacing(5)
        info_icon = _SidebarIcon('info', T('accent'), 15)
        info_title = QLabel('INFO')
        info_title.setStyleSheet(ss_text(FS_LG, 'text_dim', True))
        info_hdr.addWidget(info_icon); info_hdr.addWidget(info_title); info_hdr.addStretch()
        info_lay.addLayout(info_hdr)
        labels={}
        for k,v in [('Sample Rate','48 kHz'),('FFT Size','16384'),
                    ('Resolution','11.7 Hz'),('Calibration','0.0 dB'),('Speed','Normal')]:
            row=QHBoxLayout()
            kl=QLabel(k); kl.setStyleSheet(ss_text(FS_SM))
            vl=QLabel(v); vl.setStyleSheet(ss_text(FS_BODY, 'accent', True))
            vl.setAlignment(Qt.AlignRight)
            row.addWidget(kl); row.addWidget(vl); info_lay.addLayout(row); labels[k]=vl
        self.i_sr=labels['Sample Rate']; self.i_fft=labels['FFT Size']
        self.i_res=labels['Resolution']; self.i_calib=labels['Calibration']; self.i_spd=labels['Speed']
        layout.addWidget(info_w)

        # ── INPUT 섹션 (카드 기반) ──
        input_w = QWidget(); input_w.setObjectName('infoBox')
        input_lay = QVBoxLayout(input_w); input_lay.setContentsMargins(8,8,8,8); input_lay.setSpacing(5)
        in_hdr = QHBoxLayout(); in_hdr.setContentsMargins(0,0,0,6); in_hdr.setSpacing(5)
        in_icon = _SidebarIcon('input', T('accent'), 15)
        in_title = QLabel('INPUT')
        in_title.setStyleSheet(ss_text(FS_LG, 'text_dim', True))
        in_hdr.addWidget(in_icon); in_hdr.addWidget(in_title); in_hdr.addStretch()
        input_lay.addLayout(in_hdr)
        # 카드 컨테이너 — TF식 스크롤 목록 (카드 많아져도 압축/겹침 없이 스크롤)
        self._ch_cards_container = QWidget()
        self._ch_cards_container.setStyleSheet('background:transparent;')
        self._ch_cards_layout = QVBoxLayout(self._ch_cards_container)
        # 카드를 좌우로 확실히 인셋 → 4면 테두리가 또렷이 보이게
        self._ch_cards_layout.setContentsMargins(2,0,4,0); self._ch_cards_layout.setSpacing(6)
        self._ch_cards_scroll = QScrollArea()
        self._ch_cards_scroll.setWidget(self._ch_cards_container)
        self._ch_cards_scroll.setWidgetResizable(True)
        self._ch_cards_scroll.setFrameShape(QFrame.NoFrame)
        self._ch_cards_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._ch_cards_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        # 뷰포트 자체를 우측 인셋 → 스크롤바 유무와 무관하게 카드 우측 테두리 확보
        self._ch_cards_scroll.setViewportMargins(0,0,6,0)
        self._ch_cards_scroll.setMinimumHeight(120)
        self._ch_cards_scroll.viewport().setStyleSheet('background:transparent;')
        self._ch_cards_scroll.setStyleSheet(
            'QScrollArea{background:transparent;border:none;}'
            'QScrollBar:vertical{width:6px;background:transparent;margin:0;}'
            'QScrollBar::handle:vertical{background:#48484A;border-radius:3px;min-height:40px;}'
            'QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}')
        input_lay.addWidget(self._ch_cards_scroll, 1)
        # TF식 '+ Add Source' 점선 버튼 — 카드마다 장치+채널 독립 (멀티-장치 오버레이)
        self._ch_add_btn = _DashedAddButton('＋  Add Source')
        self._ch_add_btn.setFixedHeight(26)
        self._ch_add_btn.setCursor(Qt.PointingHandCursor)
        self._ch_add_btn.clicked.connect(self._spec_add_source)
        input_lay.addWidget(self._ch_add_btn)
        layout.addWidget(input_w, 1)

        # ── 하단 유틸리티 버튼 ──
        util_row = QHBoxLayout(); util_row.setSpacing(4)
        log_btn = self._log_btn = QPushButton('Log')
        log_btn.setFixedHeight(22)
        log_btn.setToolTip(f'로그 폴더 열기\n{_LOG_DIR}')
        log_btn.clicked.connect(lambda: (os.startfile(_LOG_DIR) if _pl.system() == 'Windows'
                                         else _sp.Popen(['open', _LOG_DIR])))
        lic_btn = self._lic_btn = QPushButton('License')
        lic_btn.setFixedHeight(22)
        lic_btn.setToolTip('라이선스 정보')
        lic_btn.clicked.connect(self._show_license_info)
        self._restyle_util_btns()
        util_row.addWidget(log_btn); util_row.addWidget(lic_btn)
        layout.addLayout(util_row)

        layout.addStretch(); return panel

    def _restyle_util_btns(self):
        """Log/License 유틸 버튼 — 테마 적응 스타일 (다크↔라이트 토글 시 갱신)."""
        _ss = (f'font-size:{FS_XS}px;color:{T("text_dim")};background:{T("panel")};'
               f'border:1px solid {T("border")};border-radius:{RADIUS_SM}px;padding:1px 6px;')
        for _b in (getattr(self, '_log_btn', None), getattr(self, '_lic_btn', None)):
            if _b is not None: _b.setStyleSheet(_ss)

    # ─────────────────────────────────────
    def _apply_theme(self):
        if hasattr(self, '_log_btn'): self._restyle_util_btns()
        bg=T('bg'); bg2=T('bg2'); bg3=T('bg3'); border=T('border')
        text=T('text'); text_dim=T('text_dim'); accent=T('accent'); panel=T('panel')
        ac = QColor(accent); ar,ag,ab = ac.red(),ac.green(),ac.blue()
        # parse background colors for gradient computation
        bg_c  = QColor(bg);    bgR,bgG,bgB   = bg_c.red(),bg_c.green(),bg_c.blue()
        bg2_c = QColor(bg2);   b2R,b2G,b2B   = bg2_c.red(),bg2_c.green(),bg2_c.blue()
        bg3_c = QColor(bg3);   b3R,b3G,b3B   = bg3_c.red(),bg3_c.green(),bg3_c.blue()
        pn_c  = QColor(panel); pnR,pnG,pnB   = pn_c.red(),pn_c.green(),pn_c.blue()
        # glass overlay — dark: white-overlay glass; light: panel-based solid
        if _theme == 'dark':
            btn_bg0 = 'rgba(255,255,255,14)'; btn_bg1 = 'rgba(255,255,255,5)'
            btn_bd  = 'rgba(255,255,255,20)'
            cb_bg0  = 'rgba(255,255,255,12)'; cb_bg1  = 'rgba(255,255,255,4)'
            cb_bd   = 'rgba(255,255,255,18)'
            scr_hdl = 'rgba(255,255,255,22)'
            grp_bd  = 'rgba(255,255,255,12)'; grp_bg  = 'rgba(255,255,255,3)'
            dis_bg  = 'rgba(255,255,255,4)';  dis_bd  = 'rgba(255,255,255,8)'
        else:
            btn_bg0 = f'rgba({pnR},{pnG},{pnB},255)'
            btn_bg1 = f'rgba({max(0,pnR-14)},{max(0,pnG-14)},{max(0,pnB-14)},255)'
            btn_bd  = border
            cb_bg0  = f'rgba({pnR},{pnG},{pnB},255)'
            cb_bg1  = f'rgba({max(0,pnR-10)},{max(0,pnG-10)},{max(0,pnB-10)},255)'
            cb_bd   = border
            scr_hdl = f'rgba({max(0,bgR-55)},{max(0,bgG-52)},{max(0,bgB-42)},150)'  # near-white에서 핸들 가시성
            grp_bd  = border; grp_bg = bg3
            dis_bg  = bg3;    dis_bd  = border
        self.setStyleSheet(f"""
            QWidget {{
                background: {bg2};
                color: {text};
                font-size: 11px;
            }}
            QLabel {{ color: {text_dim}; font-size: 11px; }}
            QComboBox {{
                background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                    stop:0 {cb_bg0}, stop:1 {cb_bg1});
                color: {text};
                border: 1px solid {cb_bd};
                border-radius: 7px;
                padding: 2px 10px;
                font-size: 11px;
                min-height: 26px;
                combobox-popup: 0;
            }}
            QComboBox:hover {{
                border: 1px solid rgba({ar},{ag},{ab},160);
                color: {text};
            }}
            QComboBox::drop-down {{ width:0; border:none; }}
            QComboBox::down-arrow {{ width:0; height:0; image:none; }}
            QComboBox QAbstractItemView {{
                background: {bg2};
                color: {text};
                border: 1px solid rgba({ar},{ag},{ab},120);
                border-radius: 7px;
                selection-background-color: rgba({ar},{ag},{ab},55);
                selection-color: {accent};
                outline: none;
                font-size: 11px;
            }}
            QComboBox QAbstractItemView::item {{
                padding: 5px 12px;
                min-height: 28px;
                background: {bg2};
                color: {text};
                border: none;
            }}
            QComboBox QAbstractItemView::item:hover {{
                background: rgba({ar},{ag},{ab},22);
                color: {text};
            }}
            QComboBox QAbstractItemView::item:selected {{
                background: rgba({ar},{ag},{ab},55);
                color: {accent};
            }}
            QScrollBar:vertical {{
                background: transparent;
                width: 5px;
                margin: 0;
                border: none;
            }}
            QScrollBar::handle:vertical {{
                background: {scr_hdl};
                border-radius: 2px;
                min-height: 20px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: rgba({ar},{ag},{ab},100);
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
            QScrollBar:horizontal {{
                background: transparent;
                height: 5px;
                margin: 0;
                border: none;
            }}
            QScrollBar::handle:horizontal {{
                background: {scr_hdl};
                border-radius: 2px;
                min-width: 20px;
            }}
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
            QPushButton {{
                background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                    stop:0 {btn_bg0}, stop:1 {btn_bg1});
                color: {text};
                border: 1px solid {btn_bd};
                border-radius: 7px;
                padding: 3px 9px;
                font-size: 11px;
            }}
            QPushButton:hover {{
                background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                    stop:0 rgba({ar},{ag},{ab},50), stop:1 rgba({ar},{ag},{ab},22));
                border: 1px solid rgba({ar},{ag},{ab},160);
                color: {accent};
            }}
            QPushButton:pressed {{
                background: rgba({ar},{ag},{ab},38);
                border: 1px solid rgba({ar},{ag},{ab},200);
            }}
            QPushButton:checked {{
                background: rgba({ar},{ag},{ab},90);
                color: {accent};
                border: 2px solid {accent};
                font-weight: bold;
            }}
            QPushButton:disabled {{
                color: {text_dim};
                background: {dis_bg};
                border: 1px solid {dis_bd};
            }}
            QGroupBox {{
                border: none;
                margin-top: 14px;
                font-size: 10px;
                color: {text_dim};
                padding-top: 4px;
                background: transparent;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
                color: {text_dim};
            }}
            QFrame[frameShape="4"] {{ color: {border}; }}
            QToolTip {{
                background: {bg2};
                color: {text};
                border: 1px solid rgba({ar},{ag},{ab},120);
                border-radius: 5px;
                padding: 4px 8px;
                font-size: 11px;
            }}
        """)
        # 헤더 — 상단 유리 패널
        drw_alpha = 245 if _theme == 'dark' else 255
        self._capture_drawer._panel.setStyleSheet(
            f'#capturePanel {{ background: qlineargradient(x1:0,y1:0,x2:0,y2:1,'
            f'stop:0 rgba({pnR},{pnG},{pnB},{drw_alpha}), stop:1 rgba({b2R},{b2G},{b2B},{drw_alpha}));'
            f'border: 1px solid {border}; border-radius: 8px; }}')
        # update drawer segmented control for current theme
        if _theme == 'dark':
            seg_pill_bg   = '#3A3A3C'
            seg_chk_bg    = '#636366'
            seg_chk_txt   = '#FFFFFF'
            seg_unchk_txt = '#8E8E93'
            seg_hover     = 'rgba(255,255,255,12)'
        else:
            seg_pill_bg   = '#E5E5EA'
            seg_chk_bg    = '#FFFFFF'
            seg_chk_txt   = '#000000'
            seg_unchk_txt = '#666666'
            seg_hover     = 'rgba(0,0,0,8)'
        self._capture_drawer._seg_pill.setStyleSheet(
            f'#segPill{{background:{seg_pill_bg};border-radius:8px;}}')
        _dtab_ss = (
            f'QPushButton{{font-size:11px;font-weight:600;border:none;'
            f'background:transparent;color:{seg_unchk_txt};padding:0 4px;border-radius:6px;}}'
            f'QPushButton:checked{{background:{seg_chk_bg};color:{seg_chk_txt};}}'
            f'QPushButton:hover:!checked{{background:{seg_hover};}}')
        self._capture_drawer._spec_tab_btn.setStyleSheet(_dtab_ss)
        self._capture_drawer._tf_tab_btn.setStyleSheet(_dtab_ss)
        self._capture_drawer._scroll.setStyleSheet(
            f'QScrollBar:vertical{{width:5px;background:transparent;}}'
            f'QScrollBar::handle:vertical{{background:{scr_hdl};border-radius:2px;}}')
        self._capture_drawer._scroll.viewport().setStyleSheet(f'background:{bg};')
        self._capture_drawer._inner.setStyleSheet(f'#capInner {{ background:{bg}; }}')
        sep_line = '#4A4A4A' if _theme == 'dark' else border
        self.hdr.setStyleSheet(f'#mainHdr {{ background: {bg2}; border: none; }}')
        self.hdr_sep.setStyleSheet(f'#hdrSep {{ background: {_SPECTRA_GRAD_QSS}; border: none; }}')
        self.tab_bar.setStyleSheet(
            f'#mainTabBar {{ background: {bg2}; border-bottom: 1px solid {sep_line}; }}')
        self._main_seg_pill.setStyleSheet(
            f'#mainSegPill{{background:{seg_pill_bg};border-radius:8px;}}')
        for b in self._tab_btns.values():
            b.setStyleSheet(_dtab_ss)
        # toolbar_wrapper: ID selector로 cascade 방지 (자식 위젯 border 미영향)
        self.toolbar_wrapper.setStyleSheet(
            f'#toolbarWrapper {{ background: {bg2}; }}')
        # 툴바 하단 시그니처 라인 = 로고블루 2px (별도 위젯 — 3탭 공통 확실 표시, 테마 적응)
        self.toolbar_underline.setStyleSheet(
            f'#toolbarUnderline {{ background: {accent}; border: none; }}')
        if hasattr(self, '_view_seg'):
            self._view_seg.apply_theme(); self._scale_seg.apply_theme()
        if hasattr(self, '_toolbar_btn'):
            self._toolbar_btn.update()
        self.sub_stack.setStyleSheet(
            f'#subStack {{ background: transparent; border: none; }}')
        # ctrl_bar bare-property cascade로 dev_cb 테두리가 사라지는 문제 → 명시 재부여
        # 주의: 콤보에 per-widget 스타일을 주면 팝업(QAbstractItemView)이 앱 전역 QSS를
        # 잃고 '시스템 팔레트'로 폴백 → macOS 다크모드에서 라이트 테마인데도 항목 글씨가
        # 흰색이 되어 안 보임. 그래서 팝업 규칙을 _cb_ss 안에 명시한다.
        _cb_ss = (
            f'QComboBox{{background: qlineargradient(x1:0,y1:0,x2:0,y2:1,'
            f'stop:0 {cb_bg0}, stop:1 {cb_bg1});'
            f'color:{text}; border:1px solid {cb_bd};'
            f'border-radius:{RADIUS_CTRL}px; padding:2px 10px; font-size:{FS_BODY}px;'
            f'min-height:26px; max-height:26px; combobox-popup:0;}}'
            f'QComboBox::drop-down{{width:0;border:none;}}'
            f'QComboBox::down-arrow{{width:0;height:0;image:none;}}'
            f'QComboBox:hover{{border:1px solid rgba({ar},{ag},{ab},160);}}'
            f'QComboBox QAbstractItemView{{background:{bg2};color:{text};'
            f'border:1px solid {cb_bd};border-radius:7px;outline:none;font-size:11px;'
            f'selection-background-color:rgba({ar},{ag},{ab},55);selection-color:{accent};}}'
            f'QComboBox QAbstractItemView::item{{color:{text};background:{bg2};'
            f'min-height:26px;padding:4px 10px;}}'
            f'QComboBox QAbstractItemView::item:selected{{color:{accent};'
            f'background:rgba({ar},{ag},{ab},55);}}')
        self.dev_cb.setStyleSheet(_cb_ss)
        self.in_ch_cb.setStyleSheet(_cb_ss)
        self._st_l_cb.setStyleSheet(_cb_ss)
        self._st_r_cb.setStyleSheet(_cb_ss)
        self._st_target_cb.setStyleSheet(_cb_ss)
        # Spectrum 툴바 콤보도 전역 cascade 대신 _cb_ss 직접 적용 → 3탭 콤보 100% 동일 보장
        for _spc in ('sr_cb', 'avg_cb', 'hold_cb', 'db_cb', 'spd_cb'):
            _w = getattr(self, _spc, None)
            if _w is not None: _w.setStyleSheet(_cb_ss)
        # sub_stack의 bare-property cascade가 tf_win.tb 자식 버튼/콤보박스에
        # border:none을 덮어쓰는 문제 → tb에 typed selector로 명시 스타일 재부여
        if hasattr(self, 'tf_win') and self.tf_win is not None:
            self.tf_win.tb.setStyleSheet(
                f'QPushButton {{'
                f'  background: qlineargradient(x1:0,y1:0,x2:0,y2:1,'
                f'    stop:0 {btn_bg0}, stop:1 {btn_bg1});'
                f'  color:{text}; border:1px solid {btn_bd};'
                f'  border-radius:7px; padding:3px 9px; font-size:11px; }}'
                f'QComboBox {{'
                f'  background: qlineargradient(x1:0,y1:0,x2:0,y2:1,'
                f'    stop:0 {cb_bg0}, stop:1 {cb_bg1});'
                f'  color:{text}; border:1px solid {cb_bd};'
                f'  border-radius:7px; padding:2px 10px; font-size:11px;'
                f'  combobox-popup:0; }}'
                f'QComboBox::drop-down {{ width:0; border:none; }}'
                f'QComboBox::down-arrow {{ width:0; height:0; image:none; }}'
                f'QComboBox:hover {{ border:1px solid rgba({ar},{ag},{ab},160); }}'
            )
            # TF 툴바 콤보는 부모(tb) 상속만으론 drawComplexControl이 Fusion 기본 프레임
            # (두꺼운 테두리+화살표+진한 배경)을 그려 Spectrum과 달라 보임 → _cb_ss 직접 적용해 통일.
            for _cbn in ('fft_cb', 'avg_cb', 'sm_cb', 'ir_cb', 'phase_cb'):
                _cbw = getattr(self.tf_win, _cbn, None)
                if _cbw is not None: _cbw.setStyleSheet(_cb_ss)
            # Δ·stable 토글 버튼 — 테마 적응(라이트에서 다크박스 방지)
            _tgss = (
                f'QPushButton{{background:{panel};color:{text_dim};border:1px solid {border};'
                f'border-radius:7px;font-size:14px;font-weight:bold;}}'
                f'QPushButton:hover{{border-color:{accent};}}'
                f'QPushButton:checked{{background:{accent};color:#FFFFFF;border:1px solid {accent};}}')
            for _bn in ('delta_btn', 'tf_stable_btn'):
                _b = getattr(self.tf_win, _bn, None)
                if _b is not None: _b.setStyleSheet(_tgss)
            # 아이콘 테마 적응 재생성 (다크↔라이트 토글 시 보이도록)
            for _bn, _ic, _sz in [('find_btn', 'search', 16), ('delta_btn', 'delta', 16),
                                  ('tf_stable_btn', 'hourglass', 16), ('sig_file_btn', 'folder', 16),
                                  ('_export_btn', 'download', 13)]:
                _b = getattr(self.tf_win, _bn, None)
                if _b is not None and not _b.icon().isNull(): _b.setIcon(_icon(_ic, _sz))
            # TF 측정 카드 인라인색 재적용 (다크↔라이트 토글 시 카드/콤보/딜레이가 검정으로 남는 문제)
            self.tf_win.restyle_theme()
        # Spectrum 입력 카드 — 인라인-구운 색이 토글에 안 따라옴 → 통째로 재생성
        if hasattr(self, '_rebuild_ch_cards') and hasattr(self, '_ch_cards'):
            self._rebuild_ch_cards()
        self._apply_tab_styles()
        self.logo_lbl.setStyleSheet(
            f'font-size:17px;font-weight:700;letter-spacing:5px;color:{text};background:transparent;')
        self.status_lbl.setStyleSheet(
            f'color:{text_dim};font-size:11px;letter-spacing:0.5px;')
        self.mic_st.setStyleSheet(f'color:{text_dim};font-size:10px;')
        if hasattr(self, '_st_dev_lbl'): self._st_dev_lbl.setStyleSheet(self._st_dev_lbl_ss())
        # 시작 버튼
        self._go_style(self.start_btn)
        # 테마 버튼
        lbl = 'Dark' if _theme == 'light' else 'Light'
        self.theme_btn.setText(lbl)
        self.theme_btn.setIcon(_icon('moon' if _theme == 'light' else 'sun'))
        self.theme_btn.setStyleSheet(
            f'background: qlineargradient(x1:0,y1:0,x2:0,y2:1,'
            f'stop:0 rgba({ar},{ag},{ab},28), stop:1 rgba({ar},{ag},{ab},14));'
            f'color:{accent};border:1px solid rgba({ar},{ag},{ab},80);'
            f'padding:3px 10px;border-radius:7px;font-size:10px;')
        self.calib_btn.setStyleSheet(
            f'background: qlineargradient(x1:0,y1:0,x2:0,y2:1,'
            f'stop:0 {cb_bg0}, stop:1 {cb_bg1});'
            f'color:{text_dim};border:1px solid {cb_bd};'
            f'padding:3px 10px;border-radius:7px;font-size:10px;')
        self.calib_btn.setIcon(_icon('sliders'))
        # 오른쪽 사이드 패널 배경 + 왼쪽 경계선 (셀렉터 지정으로 자식 위젯 미영향)
        if hasattr(self, '_info_panel'):
            self._info_panel.setStyleSheet(
                f'#infoPanel {{ background:{panel}; border-left:1px solid {sep_line}; }}'
                f'#levelBox {{ background:transparent; border:1px solid {sep_line}; border-radius:8px; }}'
                f'#levelBox QLabel {{ background:transparent; border:none; }}'
                f'#infoBox  {{ background:transparent; border:1px solid {sep_line}; border-radius:8px; }}'
                f'#infoBox QLabel {{ background:transparent; border:none; }}')
        # 캡처 드로어 오른쪽 경계선 (셀렉터 지정으로 자식 위젯 미영향)
        self._capture_drawer._panel.setStyleSheet(
            f'#capturePanel {{ background:{bg2}; border: 1px solid {border}; border-radius: 8px; }}')
        # 스플리터 핸들 — 3탭 공통 구분선(얇은 하이라인)
        self.cvs_splitter.setStyleSheet(_splitter_qss())
        if self.tf_win is not None and hasattr(self.tf_win, 'cvs_w'):
            self.tf_win.cvs_w.setStyleSheet(_splitter_qss())
        if self.tf_win is not None and hasattr(self.tf_win, '_rp_sep'):
            self.tf_win._rp_sep.setStyleSheet(f'background:{sep_line};border:none;')
        # 푸터 경계선
        self.ft.setStyleSheet(
            f'background:{bg2};border-top:1px solid {sep_line};')
        # Level 스핀박스 + ±버튼 (tf_win 소속)
        if self.tf_win is not None:
            self.tf_win.sig_lvl_sp.setStyleSheet(f"""
                QDoubleSpinBox {{
                    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                        stop:0 rgba({ar},{ag},{ab},30), stop:1 rgba({ar},{ag},{ab},14));
                    color: {accent};
                    border: 1px solid rgba({ar},{ag},{ab},100);
                    border-radius: 7px;
                    padding: 3px 8px;
                    font-size: 12px;
                    font-weight: bold;
                    min-height: 26px;
                    selection-background-color: rgba({ar},{ag},{ab},60);
                }}
                QDoubleSpinBox::up-button   {{ width:0; border:none; }}
                QDoubleSpinBox::down-button {{ width:0; border:none; }}
            """)
            _btn_s = (
                f'background: qlineargradient(x1:0,y1:0,x2:0,y2:1,'
                f'stop:0 {btn_bg0}, stop:1 {btn_bg1});'
                f'color:{text};border:1px solid {btn_bd};'
                f'border-radius:7px;padding:0px;font-size:15px;font-weight:bold;')
            self.tf_win.sig_lvl_btn_m.setStyleSheet(_btn_s)
            self.tf_win.sig_lvl_btn_p.setStyleSheet(_btn_s)
            # TF 오른쪽 패널 배경 + 그룹박스 타이틀 색상 업데이트
            self.tf_win.rp.setStyleSheet(f'background:{bg2};')
            _bss = (f'QGroupBox{{border:1px solid {border};border-radius:6px;margin-top:14px;'
                    f'font-size:11px;color:{text_dim};padding-top:4px;}}'
                    f'QGroupBox::title{{subcontrol-origin:margin;left:6px;padding:0 4px;}}')
            for grp in self.tf_win.rp.findChildren(QGroupBox):
                grp.setStyleSheet(_bss)
            # Play 버튼 재스타일
            self.tf_win.sig_on_btn.setStyleSheet(
                f'background:{panel};color:{text_dim};'
                f'border:1px solid {border};padding:4px;border-radius:6px;font-weight:bold;')
            # VU 레이블 → 카드 방식으로 교체됨, 별도 테마 갱신 불필요
            # TF 캔버스 캐시 무효화
            for cvs in [self.tf_win.mag_cvs, self.tf_win.phase_cvs, self.tf_win.ir_cvs]:
                cvs._cache = None; cvs._cap_pix = None; cvs.update()
        # 캔버스 캐시 무효화 + 리페인트
        self.fft_cvs._cache=None; self.oct_cvs._cache=None; self.spectro_cvs._cache=None
        for w in [self.fft_cvs,self.oct_cvs,self.spectro_cvs,self.vu_a]: w.update()
        if hasattr(self, 'stereo_page'): self.stereo_page.restyle_theme()
        _spl = getattr(self, 'spl_meter_win', None)
        if _spl is not None: _spl.restyle_theme()
        # 캡처 드로어 행 재빌드 (테마 전환 시 T() 색상 갱신)
        self._refresh_capture_drawer()

    def _go_style(self, b):   _apply_txn(b, False)   # 시작=로고블루 틴트
    def _stop_style(self, b): _apply_txn(b, True)    # 정지=레드 틴트

    def _toggle_capture_drawer(self):
        visible = not self._capture_drawer.isVisible()
        self._capture_drawer.setVisible(visible)
        self._drawer_btn.setChecked(visible)
        self._drawer_btn.update()
        if hasattr(self, 'tf_win') and self.tf_win is not None:
            self.tf_win._drawer_btn.setChecked(visible)
            self.tf_win._drawer_btn.update()

    def _toggle_spec_panel(self):
        vis = not self._info_panel.isVisible()
        self._info_panel.setVisible(vis)
        self._spec_panel_btn.setChecked(vis); self._spec_panel_btn.update()
        self._settings['spec_panel_visible'] = vis
        _save_settings(self._settings)

    def _toggle_toolbar(self):
        vis = not self.toolbar_wrapper.isVisible()
        self.toolbar_wrapper.setVisible(vis); self.toolbar_underline.setVisible(vis)
        self._toolbar_btn.setChecked(vis); self._toolbar_btn.update()
        self._settings['toolbar_visible'] = vis
        _save_settings(self._settings)

    def eventFilter(self, obj, event):
        if obj is self.hdr and event.type() == QEvent.MouseButtonDblClick:
            if self.isFullScreen():
                self.showNormal()
            else:
                self.showFullScreen()
            return True
        return super().eventFilter(obj, event)

    def _st_dev_lbl_ss(self):
        # 장치명은 보조 정보 → text_dim 세미볼드. 배경은 옆 툴바 컨트롤(은은한 오버레이)과 맞춤
        # (기존 bg3 진한 회색 블록이 혼자 튀던 문제).
        bg = 'rgba(255,255,255,10)' if _theme != 'light' else T('bg2')
        return (f'font-size:{FS_BODY}px;font-weight:500;color:{T("text_dim")};'
                f'background:{bg};border:1px solid {T("border")};'
                f'border-radius:{RADIUS_SM}px;padding:2px 8px;')

    def _toggle_theme(self):
        global _theme
        _theme='light' if _theme=='dark' else 'dark'
        self._apply_theme()

    def _auto_range_for_calib(self):
        if self.calib_offset <= 5:
            self.db_max = MAX_DB
            self.db_min = self.db_max - self.db_range
            if hasattr(self, 'oct_cvs'):
                self._apply_db_range()
                self.oct_cvs.clear()
        else:
            if hasattr(self, 'oct_cvs'):
                self.oct_cvs.clear()
            self._pending_auto_fit = True
            self._auto_fit_frame_count = 0

    def _auto_fit_y_to_data(self):
        """실제 데이터 피크 기준으로 Y축 자동 조정 (메인 스레드에서 호출)."""
        peak = None
        if self.view_mode == 'fft' and self.fft_cvs._ds_avg is not None:
            valid = self.fft_cvs._ds_avg[self.fft_cvs._ds_avg > -90]
            if len(valid) > 0:
                peak = float(np.max(valid))
        else:
            sm = self.oct_cvs.smooth.get(self.oct_cvs.mode)
            if sm is not None:
                valid = sm[sm > -90]
                if len(valid) > 0:
                    peak = float(np.max(valid))
        if peak is None:
            return   # 아직 데이터 없음 → 다음 프레임에서 재시도
        self.db_max = int(math.ceil((peak + 12) / 12)) * 12
        self.db_min = self.db_max - self.db_range
        self._pending_auto_fit = False
        self._apply_db_range()

    def _open_calib(self):
        # 현재 raw SPL(캘리브 오프셋 제외) 반환 콜백
        def get_raw_spl():
            with QMutexLocker(self._mutex):
                return self._raw_spl_smooth
        device_name = self.dev_cb.currentText()
        n_ch = self._dev_input_channels(self.dev_cb.currentData())
        active_ch = self.in_ch_cb.currentData() or 0
        calibs = self._settings.get('calibrations', {})
        # 이 장치의 채널별 기존 오프셋 수집 (+ 레거시 장치단위 값은 ch0 으로)
        offsets = {}
        for ch in range(n_ch):
            key = f'{device_name}:{ch}'
            if key in calibs:
                offsets[ch] = float(calibs[key])
        if not offsets and device_name in calibs:
            offsets[0] = float(calibs[device_name])

        def set_channel(ch):
            for i in range(self.in_ch_cb.count()):
                if self.in_ch_cb.itemData(i) == ch:
                    self.in_ch_cb.setCurrentIndex(i); break   # → _on_input_ch_changed (재시작+calib로드)

        dlg = CalibDialog(device_name, n_ch, offsets, active_ch,
                          get_raw_spl, set_channel, self)
        result = dlg.exec()
        if result == QDialog.Accepted:
            all_off = dlg.get_all_offsets()
            if 'calibrations' not in self._settings:
                self._settings['calibrations'] = {}
            for ch, off in all_off.items():
                self._settings['calibrations'][f'{device_name}:{ch}'] = round(float(off), 1)
            _save_settings(self._settings)
            _alog.info(f'캘리브레이션 저장  device="{device_name}"  '
                       + ', '.join(f'ch{ch}={off:+.1f}' for ch, off in sorted(all_off.items())))
            # 현재 활성 채널 기준으로 라이브 반영 (다이얼로그가 채널을 바꿔놨을 수 있음)
            cur_ch = self.in_ch_cb.currentData() or 0
            self._load_calib_for_device(device_name, cur_ch)
        else:
            # 취소 — 다이얼로그 도중 채널이 바뀌었으면 원래 채널로 복원
            if (self.in_ch_cb.currentData() or 0) != active_ch:
                set_channel(active_ch)

    def _apply_db_range(self):
        self.fft_cvs.db_max=self.db_max; self.fft_cvs.db_min=self.db_min
        self.oct_cvs.db_max=self.db_max; self.oct_cvs.db_min=self.db_min
        self.spectro_cvs.set_db_range(self.db_min,self.db_max)
        self.fft_cvs._cache=None; self.oct_cvs._cache=None
        self.fft_cvs.update(); self.oct_cvs.update()

    def _open_leq(self):
        if self.leq_win is None:
            self.leq_win=LeqWindow(self)
            self.leq_win.setStyleSheet(f'background:{T("bg2")};color:{T("text")};')
        self.leq_win.show(); self.leq_win.raise_()

    def _open_spl_meter(self):
        if self.spl_meter_win is None:
            self.spl_meter_win = SplMeterWindow(self)
            self.spl_meter_win.set_calib_offset(self.calib_offset)
        self.spl_meter_win.show(); self.spl_meter_win.raise_()

    def _open_tf_window(self):
        self._switch_tab(1)

    # ─────────────────────────────────────
    def _show_device_popup(self):
        self._device_popup = DeviceCardPopup(self.dev_cb, getattr(self, '_disconnected_dev_name', ''))
        self._device_popup.device_selected.connect(self._on_popup_device_selected)
        self._device_popup.refresh_requested.connect(self._on_popup_refresh)
        anchor = self._primary_dev_btn_ref if self._primary_dev_btn_ref else self.dev_btn
        w = max(anchor.width(), 260)
        self._device_popup.adjustSize()
        ph = self._device_popup.sizeHint().height()
        self._device_popup.resize(w, ph)
        scr = QApplication.primaryScreen().availableGeometry()
        gp = anchor.mapToGlobal(QPoint(anchor.width() - w, anchor.height() + 2))
        if gp.x() < scr.left(): gp.setX(scr.left() + 4)
        if gp.x() + w > scr.right(): gp.setX(scr.right() - w - 4)
        if gp.y() + ph > scr.bottom(): gp.setY(anchor.mapToGlobal(QPoint(0, -ph - 2)).y())
        self._device_popup.move(gp)
        self._device_popup.show()

    def _on_popup_refresh(self):
        # 수동 새로고침도 중앙 재초기화 — 재연결 장치를 인식하려면 PortAudio 재초기화 필수
        # (단순 query_devices 는 캐시된 옛 목록만 반환 → 재연결 장치 누락/-9986)
        self.reinit_audio_devices('manual refresh')

    def _on_popup_device_selected(self, combo_idx):
        self.dev_cb.setCurrentIndex(combo_idx)

    def _update_dev_btn_text(self):
        name = self.dev_cb.currentText()
        if len(name) > 30:
            name = name[:28] + '..'
        self.dev_btn.setText(name or '장치 선택')

    # ─────────────────────────────────────
    def _load_devices(self):
        # 콤보박스 조작 중 _on_device_changed 가 반복 호출되는 것을 차단
        try: self.dev_cb.currentIndexChanged.disconnect(self._on_device_changed)
        except Exception: pass
        self.dev_cb.blockSignals(True)
        self.dev_cb.clear()
        try:
            import threading, queue as _q
            result=_q.Queue()
            def _query():
                try: result.put(('ok',sd.query_devices()))
                except Exception as e: result.put(('err',str(e)))
            t=threading.Thread(target=_query,daemon=True); t.start()
            t.join(timeout=3.0)
            if result.empty():
                self.dev_cb.addItem('장치 검색 시간 초과',-1)
                self.dev_cb.blockSignals(False); return
            status,payload=result.get_nowait()
            if status=='err':
                self.dev_cb.addItem(f'오류: {payload}',-1)
                self.dev_cb.blockSignals(False); return
            devs=payload
            _disc=getattr(self,'_disconnected_dev_name','')
            # 불필요한 장치 제외 — 내장 마이크 + 외장 인터페이스만 표시
            # Dante 장비는 'virtual' 키워드 있어도 허용
            _allow_kw   = ('dante',)
            _virtual_kw = (
                'soundflower', 'blackhole', 'loopback', 'aggregate',
                'virtual', 'zoom audio', 'teams audio', 'webex',
                'discord audio', 'obs', 'multi-output',
                'iphone', 'ipad',
            )
            for i,d in enumerate(devs):
                if d['max_input_channels']<1: continue
                name=d['name']
                name_l = name.lower()
                if not any(kw in name_l for kw in _allow_kw):
                    if any(kw in name_l for kw in _virtual_kw): continue
                if _disc and name==_disc:
                    # 뽑혔던 장치만 실제 접근 가능 여부 확인 (다른 장치는 무검증 → GIL 점유 없음)
                    try:
                        sr=int(d.get('default_samplerate',44100))
                        sd.check_input_settings(device=i,samplerate=sr,channels=1)
                        self._disconnected_dev_name=''  # 재연결 확인됨
                    except Exception:
                        continue   # 아직 뽑혀 있음, 목록에서 제외
                self.dev_cb.addItem(name,i)
            self.mic_st.setText(f'{self.dev_cb.count()}개 감지됨')
            last = self._settings.get('last_device', '')
            found_last = False
            for i in range(self.dev_cb.count()):
                if self.dev_cb.itemText(i) == last:
                    self.dev_cb.setCurrentIndex(i); found_last = True; break
            if not found_last and self._first_device_load:
                _builtin_kw = ('macbook', 'built-in', '내장', 'internal microphone')
                for i in range(self.dev_cb.count()):
                    if any(kw in self.dev_cb.itemText(i).lower() for kw in _builtin_kw):
                        self.dev_cb.setCurrentIndex(i); break
        except Exception as e:
            self.dev_cb.addItem(f'오류: {e}',-1)
        self._first_device_load = False
        self.dev_cb.blockSignals(False)
        # 채널·캘리브레이션 갱신 (시그널 없이 직접 호출)
        self._update_input_ch_cb()
        ch = self.in_ch_cb.currentData() or 0
        self._load_calib_for_device(self.dev_cb.currentText(), ch)
        # 이후 사용자가 변경할 때만 _on_device_changed 동작
        self.dev_cb.currentIndexChanged.connect(self._on_device_changed)
        self._update_dev_btn_text()
        self._st_update_dev_label()
        QTimer.singleShot(0, self._rebuild_ch_cards)

    def _update_input_ch_cb(self):
        dev_idx = self.dev_cb.currentData()
        self.in_ch_cb.blockSignals(True); self.in_ch_cb.clear()
        try:
            n = int(sd.query_devices(dev_idx)['max_input_channels']) if dev_idx is not None and dev_idx >= 0 else 1
        except Exception:
            n = 1
        for i in range(max(n, 1)):
            self.in_ch_cb.addItem(f'Ch {i+1}', i)
        # 이 장치의 저장된 채널 복원
        saved_chs = self._settings.get('input_channels', {})
        saved_ch = saved_chs.get(self.dev_cb.currentText(), 0)
        for i in range(self.in_ch_cb.count()):
            if self.in_ch_cb.itemData(i) == saved_ch:
                self.in_ch_cb.setCurrentIndex(i); break
        self.in_ch_cb.blockSignals(False)
        # Stereo 채널 콤보박스도 갱신
        self._update_stereo_ch_cbs(n)

    def _update_stereo_ch_cbs(self, n_ch=None):
        if n_ch is None:
            dev_idx=self.dev_cb.currentData()
            try: n_ch=int(sd.query_devices(dev_idx)['max_input_channels']) if dev_idx is not None and dev_idx>=0 else 2
            except Exception: n_ch=2
        for cb,default in [(self._st_l_cb,0),(self._st_r_cb,1)]:
            prev=cb.currentData()
            cb.blockSignals(True); cb.clear()
            for i in range(max(n_ch,2)):
                cb.addItem(f'Ch {i+1}',i)
            # 이전 선택 복원
            target=prev if prev is not None else default
            for i in range(cb.count()):
                if cb.itemData(i)==target: cb.setCurrentIndex(i); break
            else: cb.setCurrentIndex(min(default,cb.count()-1))
            cb.blockSignals(False)

    def _on_st_target_changed(self, _):
        val=self._st_target_cb.currentData() or -23.0
        self.stereo_page._radar.target=val

    def _st_toggle(self):
        if self.stereo_page._running:
            self.stereo_page.stop()
            self._st_start_btn.setText('Start')
            self._go_style(self._st_start_btn)
            _alog.info('Stereo & Loudness 중지')
        else:
            idx=self.dev_cb.currentData()
            if idx is None or idx<0:
                from PyQt5.QtWidgets import QMessageBox
                QMessageBox.warning(self,'장치 없음',
                    'Spectrum 탭에서 입력 장치를 먼저 선택하세요.')
                return
            # 장치 채널 수 확인 → l_ch/r_ch 범위 보정
            try:
                dev_info=sd.query_devices(idx)
                n_ch=int(dev_info['max_input_channels'])
                sr=int(dev_info['default_samplerate'])
                _SR_MAP={44100:0,48000:1,88200:2,96000:3}
                if sr not in _SR_MAP: sr=48000
                dev_name=dev_info['name']
            except Exception as e:
                _alog.warning(f'Stereo 장치 조회 실패: {e}')
                from PyQt5.QtWidgets import QMessageBox
                QMessageBox.warning(self,'장치 오류',f'장치 정보를 읽을 수 없습니다:\n{e}')
                return
            if n_ch<1:
                from PyQt5.QtWidgets import QMessageBox
                QMessageBox.warning(self,'장치 오류','선택된 장치에 입력 채널이 없습니다.')
                return
            l_ch=min(self._st_l_cb.currentData() or 0, n_ch-1)
            r_ch=min(self._st_r_cb.currentData() or 1, n_ch-1)
            _alog.info(f'Stereo 시작  device="{dev_name}"({idx})  L=ch{l_ch}  R=ch{r_ch}  sr={sr}')
            self.stereo_page.start(idx, sr, l_ch, r_ch, self.audio_engine)
            self._st_start_btn.setText('Stop')
            self._stop_style(self._st_start_btn)

    def _on_stereo_error(self, msg):
        """StereoAudioThread 오류 → 버튼 리셋 + 경고."""
        self._st_start_btn.setText('Start')
        self._go_style(self._st_start_btn)
        _alog.warning(f'Stereo 오류 → UI 리셋: {msg}')
        from PyQt5.QtWidgets import QMessageBox
        QMessageBox.warning(self,'Stereo 입력 오류',
            f'스테레오 입력 스트림을 열 수 없습니다:\n\n{msg}\n\n'
            '• Spectrum 탭에서 입력 장치를 확인하세요.\n'
            '• 다른 앱이 장치를 점유 중일 수 있습니다.')

    def _st_update_dev_label(self):
        name=self.dev_cb.currentText()
        # 이름이 너무 길면 축약
        if len(name)>28: name=name[:26]+'…'
        self._st_dev_lbl.setText(name)

    def _on_input_ch_changed(self, _):
        ch = self.in_ch_cb.currentData() or 0
        dev_name = self.dev_cb.currentText()
        if 'input_channels' not in self._settings:
            self._settings['input_channels'] = {}
        self._settings['input_channels'][dev_name] = ch
        _save_settings(self._settings)
        ch_key = f'{dev_name}:{ch}'
        calibs = self._settings.get('calibrations', {})
        offset = calibs.get(ch_key, calibs.get(dev_name, 0.0))
        self.calib_offset = offset
        self.i_calib.setText(f'{offset:+.1f} dB')
        self._apply_calib_thresholds()
        # 채널 변경 시 실행 중이면 재시작
        self._rebuild_ch_cards()
        if self._spec_running():
            self._stop(); self._start()

    def _on_device_changed(self, _):
        name = self.dev_cb.currentText()
        self._update_dev_btn_text()
        _alog.info(f'입력 디바이스 변경  device="{name}"')
        self._settings['last_device'] = name
        _save_settings(self._settings)
        self._update_input_ch_cb()
        ch = self.in_ch_cb.currentData() or 0
        self._load_calib_for_device(name, ch)
        self._rebuild_ch_cards()
        if self._spec_running():
            self._stop(); self._start()
        self._st_update_dev_label()
        if self.stereo_page._running:
            self.stereo_page.stop()
            self._st_toggle()

    def _load_calib_for_device(self, device_name, channel=0):
        calibs = self._settings.get('calibrations', {})
        ch_key = f'{device_name}:{channel}'
        offset = calibs.get(ch_key, calibs.get(device_name, 0.0))
        self.calib_offset = offset
        self.i_calib.setText(f'{offset:+.1f} dB')
        self.fft_cvs.calib_offset = offset
        self.oct_cvs.calib_offset = offset
        self.fft_cvs._cache = None; self.oct_cvs._cache = None
        self._apply_calib_thresholds()
        with QMutexLocker(self._mutex):
            self._avg_buf.clear(); self._fft_smooth=None; self._pow_smooth=None; self._pow_smooth=None
        self._auto_range_for_calib()

    def _spec_running(self):
        """Spectrum 입력(엔진 구독)이 활성인지."""
        return self._primary_sub is not None

    def _toggle(self):
        if self._spec_running(): self._stop()
        else: self._start()

    def _start(self):
        idx=self.dev_cb.currentData()
        if idx is None or idx<0: return
        # USB 재연결 후 macOS가 device index를 재할당할 수 있으므로 이름으로 재조회
        dev_name = self.dev_cb.currentText()
        try:
            for i, d in enumerate(sd.query_devices()):
                if d['name'] == dev_name and d['max_input_channels'] >= 1:
                    idx = i; break
        except Exception: pass
        # 디바이스 네이티브 샘플레이트로 자동 맞춤
        _SR_MAP={44100:0, 48000:1, 88200:2, 96000:3}
        try:
            native_sr=int(sd.query_devices(idx)['default_samplerate'])
            if native_sr in _SR_MAP and native_sr!=self.sample_rate:
                self.sample_rate=native_sr
                self.sr_cb.blockSignals(True)
                self.sr_cb.setCurrentIndex(_SR_MAP[native_sr])
                self.sr_cb.blockSignals(False)
                _alog.info(f'SR 자동 조정  device_native={native_sr}')
            elif native_sr not in _SR_MAP:
                # 176.4k/192k 등 비표준 → 가장 가까운 지원 레이트로 폴백
                fallback=48000 if native_sr>=48000 else 44100
                if fallback!=self.sample_rate:
                    self.sample_rate=fallback
                    self.sr_cb.blockSignals(True)
                    self.sr_cb.setCurrentIndex(_SR_MAP[fallback])
                    self.sr_cb.blockSignals(False)
                _alog.info(f'SR 폴백  device_native={native_sr} → app_sr={self.sample_rate}')
        except Exception: pass
        with QMutexLocker(self._mutex):
            self._avg_buf.clear(); self._fft_smooth=None; self._pow_smooth=None
            self._spl_smooth=-100.0; self._pending=None
            self._raw_spl_smooth  = -100.0
            self._raw_peak_smooth = -100.0
            self._dba_smooth      = -100.0
            self._dbc_smooth      = -100.0
        ch = self.in_ch_cb.currentData() or 0
        # AudioEngine 구독 — primary 는 단일 채널. 같은 장치의 추가 소스는 엔진이 스트림 공유.
        try:
            self._primary_sub = self.audio_engine.subscribe(idx, [ch], self.sample_rate)
        except Exception as e:
            self._primary_sub = None
            self._on_audio_error(str(e)); return
        self._primary_sub.chunk_ready.connect(self._process_audio_multi, Qt.QueuedConnection)
        self._primary_sub.error.connect(self._on_audio_error, Qt.QueuedConnection)
        self._primary_sub.disconnected.connect(self._on_device_disconnected, Qt.QueuedConnection)
        self._start_spec_extra_subs()   # 추가 장치/채널 카드들 구독 시작
        self.start_btn.setText('Stop'); self._stop_style(self.start_btn)
        self.status_lbl.setText('● Running')
        self.status_lbl.setStyleSheet(f'color:{T("green")};font-size:11px;')
        self.mic_st.setText('Connected')
        self.mic_st.setStyleSheet(f'color:{T("green")};font-size:10px;')
        self.i_sr.setText(f'{self.sample_rate/1000:.1f} kHz')
        self.i_fft.setText(str(self.fft_size))
        self.i_res.setText(f'{self.sample_rate/self.fft_size:.1f} Hz')
        freqs=np.fft.rfftfreq(self.fft_size,1.0/self.sample_rate)
        self._aw_table=np.array([a_weight_db(f) for f in freqs])
        self._cw_table=np.array([c_weight_db(f) for f in freqs])

    def _stop(self):
        if self._primary_sub is not None:
            try:
                self._primary_sub.chunk_ready.disconnect()
                self._primary_sub.error.disconnect()
                self._primary_sub.disconnected.disconnect()
            except Exception: pass
            try: self._primary_sub.close()
            except Exception: pass
            self._primary_sub = None
        self._stop_spec_extra_subs()
        with QMutexLocker(self._mutex):
            self._pending=None
            self._avg_buf.clear(); self._fft_smooth=None; self._pow_smooth=None
            self._raw_spl_smooth=-100.0; self._raw_peak_smooth=-100.0
            self._dba_smooth=-100.0; self._dbc_smooth=-100.0
        self.start_btn.setText('Start'); self._go_style(self.start_btn)
        self.status_lbl.setText('● Standby')
        self.status_lbl.setStyleSheet(f'color:{T("text_dim")};font-size:11px;')
        self.mic_st.setText('Disconnected')
        self.mic_st.setStyleSheet(f'color:{T("text_dim")};font-size:10px;')
        self.fft_cvs.clear(); self.oct_cvs.clear(); self.spectro_cvs.clear()
        self.fft_cvs.clear_all_channels(); self.oct_cvs.clear_all_channels()
        with QMutexLocker(self._mutex):
            self._ch_state.clear(); self._ch_pending_extra.clear()
        if self._primary_card is not None: self._primary_card.reset()
        self.vu_a.update_level(-100,-100,-100,-100)
        self.i_spl.setText('—'); self.i_pk.setText('—'); self.i_dom.setText('—')
        self.i_dba.setText('—'); self.i_dbc.setText('—')
        self.i_laeq.setText('—'); self.i_lceq.setText('—')
        self._laeq_buf.clear(); self._lceq_buf.clear()

    def _on_audio_error(self,msg):
        self._stop()
        self.status_lbl.setText('● 오류')
        self.status_lbl.setStyleSheet(f'color:{T("red")};font-size:11px;')
        self.mic_st.setText('장치 오류')
        self.mic_st.setStyleSheet(f'color:{T("red")};font-size:10px;')
        from PyQt5.QtWidgets import QMessageBox
        QMessageBox.warning(self,'오디오 오류',
            f'마이크 연결에 실패했습니다:\n{msg}\n\n'
            '시스템 설정 → 개인정보 보호 → 마이크에서 접근을 허용했는지 확인하세요.')

    def reinit_audio_devices(self, reason=''):
        """USB 핫플러그 중앙 처리 — 모든 탭 스트림 정지 → PortAudio 재초기화(장치목록 갱신)
        → 전 탭 콤보 재로드. PortAudio는 프로세스당 1회 초기화라 장치 추가/제거를 반영하려면
        모든 스트림을 닫은 뒤 _terminate()/_initialize() 해야 함. 탭 공통 문제이므로 중앙 1회 수행.
        (Spectrum/TF/Stereo + 공유 AudioEngine 모두 동시 해결)"""
        if getattr(self, '_reiniting_audio', False): return
        self._reiniting_audio = True
        _alog.info(f'오디오 시스템 재초기화 시작  reason={reason}')
        try:
            # 1) 전 탭 스트림 정지 (스트림이 열려 있으면 _terminate 시 -10851)
            try: self._stop()
            except Exception as e: _alog.warning(f'  spec stop 실패: {e}')
            try:
                if self.tf_win is not None:
                    self.tf_win._stop_analysis(); self.tf_win._stop_sig_gen()
            except Exception as e: _alog.warning(f'  tf stop 실패: {e}')
            try:
                if self.stereo_page is not None and getattr(self.stereo_page, '_running', False):
                    self.stereo_page.stop()
            except Exception as e: _alog.warning(f'  stereo stop 실패: {e}')
            try: self.audio_engine.stop_all()
            except Exception as e: _alog.warning(f'  engine stop 실패: {e}')
            # 2) PortAudio 재초기화 — 모든 스트림 닫힌 뒤에만 안전 (재연결 장치 인식의 핵심)
            try:
                sd._terminate(); sd._initialize()
                _alog.info('  PortAudio 재초기화 OK')
            except Exception as e:
                _alog.error(f'  PortAudio 재초기화 실패: {e}')
            # 3) 전 탭 콤보 재로드 (장치는 이름으로 복원 → 인덱스 바뀌어도 재선택됨)
            try: self._load_devices()
            except Exception as e: _alog.warning(f'  spec reload 실패: {e}')
            try:
                if self.tf_win is not None: self.tf_win._load_devices()
            except Exception as e: _alog.warning(f'  tf reload 실패: {e}')
            try:
                if getattr(self, '_device_popup', None) and self._device_popup.isVisible():
                    self._device_popup.rebuild_cards(self.dev_cb, getattr(self, '_disconnected_dev_name', ''))
            except Exception: pass
        finally:
            self._reiniting_audio = False
        _alog.info('오디오 시스템 재초기화 완료')

    def _device_count(self):
        try: return len(sd.query_devices())
        except Exception: return 0

    def _any_audio_active(self):
        """어느 탭이든 오디오 스트림이 활성인지 — 폴링 재초기화가 사용 중인 측정을 끊지 않도록 게이트."""
        if getattr(self, '_running', False): return True   # spectrum
        tw = self.tf_win
        if tw is not None and (getattr(tw, '_running', False) or
                               (getattr(tw, 'sig_on_btn', None) is not None and tw.sig_on_btn.isChecked())):
            return True
        sp = self.stereo_page
        if sp is not None and getattr(sp, '_running', False): return True
        try:
            if self.audio_engine.active_devices(): return True
        except Exception: pass
        return False

    def _begin_replug_watch(self):
        """USB 끊김 직후 호출 — 앱이 idle인 동안 2초마다 재탐색하며 장치 재연결 감지.
        PortAudio는 재초기화해야만 새 장치를 보므로, 끊김 시점의 1회 재초기화만으론
        '나중에 다시 꽂은' 장치를 못 본다 → idle 동안 짧게 폴링해 재연결을 잡는다."""
        self._replug_base = self._device_count()
        self._replug_tries = 0
        QTimer.singleShot(2000, self._replug_tick)

    def _replug_tick(self):
        # 사용자가 다른 장치로 측정을 시작했으면 폴링 중단 (재초기화가 측정을 끊지 않도록)
        if self._any_audio_active():
            _alog.info('  재연결 폴링 중단 — 오디오 활성 상태')
            return
        self._replug_tries = getattr(self, '_replug_tries', 0) + 1
        self.reinit_audio_devices(f'replug watch #{self._replug_tries}')
        if self._device_count() > getattr(self, '_replug_base', 0):
            _alog.info('  장치 재연결 감지 → 폴링 종료')
            self._disconnected_dev_name = ''
            return
        if self._replug_tries < 15:   # 최대 ~30초
            QTimer.singleShot(2000, self._replug_tick)
        else:
            _alog.info('  재연결 폴링 타임아웃(30초) — 종료')

    def _on_device_disconnected(self,msg):
        dev_name=self.dev_cb.currentText()
        if not dev_name: return   # 이미 Stop된 상태에서 중복 호출 방지
        self._disconnected_dev_name=dev_name   # Refresh 시 이 장치만 접근성 검사
        self._stop()
        self.status_lbl.setText('● 연결 끊김')
        self.status_lbl.setStyleSheet(f'color:{T("yellow")};font-size:11px;')
        self.mic_st.setText('연결 끊김')
        self.mic_st.setStyleSheet(f'color:{T("yellow")};font-size:10px;')
        # 2초 후 장치 목록 자동 갱신 — combo box에서 뽑힌 장치 제거
        QTimer.singleShot(2000, self._auto_refresh_after_disconnect)

    def _auto_refresh_after_disconnect(self):
        """USB 끊김 2초 후 중앙 재초기화 + 재연결 폴링 시작."""
        self.reinit_audio_devices('USB disconnect (spectrum)')
        self._begin_replug_watch()

    # ── 오디오 처리
    def _process_audio(self,buf):
        if not np.isfinite(buf).all(): return
        n=len(buf)
        win=np.hanning(n).astype(np.float32)
        spec=np.abs(np.fft.rfft(buf*win)); np.maximum(spec,1e-10,out=spec)
        db_raw=20*np.log10(spec/(n/2))   # ★ raw dBFS — buf 실제 크기 기준
        freqs=np.fft.rfftfreq(n,1.0/self.sample_rate).astype(np.float32)

        s=self.smoothing
        pow_raw=10**(db_raw/10)
        with QMutexLocker(self._mutex):
            if self._pow_smooth is None or len(self._pow_smooth)!=len(pow_raw):
                self._pow_smooth=pow_raw.copy()
                self._fft_smooth=db_raw.copy()
                # A/C 가중치 테이블을 실제 buf 크기에 맞게 재계산
                self._aw_table=np.array([a_weight_db(f) for f in freqs])
                self._cw_table=np.array([c_weight_db(f) for f in freqs])
            else:
                # 파워 도메인 IIR 스무딩 → dB 변환 (저역 과도현상 팽창 방지)
                self._pow_smooth*=s; self._pow_smooth+=pow_raw*(1-s)
                np.log10(np.maximum(self._pow_smooth,1e-30),out=self._fft_smooth)
                self._fft_smooth*=10.0
            self._avg_buf.append(self._fft_smooth.copy())
            avg_raw=np.mean(list(self._avg_buf),axis=0)

            # ★ 캘리브 오프셋은 그래프용 avg에만 더함 (입력 신호 불변)
            avg_cal = avg_raw + self.calib_offset

            # ★ SPL: raw dBFS로 VU 바 높이 계산, cal 값은 숫자 표시에만
            rms=float(np.sqrt(np.mean(buf**2)))
            raw_dbfs=20*math.log10(max(rms,1e-10))   # dBFS (캘리브 전)

            # SPL 스무딩 (raw 기준)
            va=0.7 if raw_dbfs>self._raw_spl_smooth else (0.03+self.speed_idx*0.04)
            self._raw_spl_smooth+=(raw_dbfs-self._raw_spl_smooth)*va
            if raw_dbfs>self._raw_peak_smooth: self._raw_peak_smooth=raw_dbfs
            else: self._raw_peak_smooth-=0.25

            # dBA / dBC — 느린 평활 (time constant ~2초)
            dba_db=dbc_db=-100.0
            if self._aw_table is not None and len(self._aw_table)==len(db_raw):
                wa=db_raw+self._aw_table+self.calib_offset
                wc=db_raw+self._cw_table+self.calib_offset
                wa=np.clip(wa,-200,100); wc=np.clip(wc,-200,100)
                raw_dba=10*math.log10(max(float(np.sum(10**(wa/10))),1e-10))
                raw_dbc=10*math.log10(max(float(np.sum(10**(wc/10))),1e-10))
                self._dba_smooth+=(raw_dba-self._dba_smooth)*0.015
                self._dbc_smooth+=(raw_dbc-self._dbc_smooth)*0.015
                dba_db=self._dba_smooth; dbc_db=self._dbc_smooth

            self._pending=(
                freqs, avg_cal,
                self._raw_spl_smooth,
                self._raw_peak_smooth,
                self._raw_spl_smooth+self.calib_offset,
                self._raw_peak_smooth+self.calib_offset,
                dba_db, dbc_db
            )

        if self.leq_win and dba_db>-100:
            self.leq_win.push_sample(dba_db,dbc_db)
        if self.spl_meter_win and dba_db>-100:
            self.spl_meter_win.push_sample(dba_db,dbc_db)

    # ── 렌더링 타이머 (30fps)
    def _render_frame(self):
        with QMutexLocker(self._mutex):
            data=self._pending; self._pending=None
            extra_data=dict(self._ch_pending_extra); self._ch_pending_extra.clear()
        # 추가 소스(멀티-장치) 커브 렌더링 — card_id 키, 소스별 색/주파수
        extra_levels={}
        for cid,(freqs_e,avg_e,dbfs_e,color_e) in extra_data.items():
            if self.view_mode=='fft':
                self.fft_cvs.set_channel_data(cid, color_e, freqs_e, avg_e)
            else:
                self.oct_cvs.set_channel_oct(cid, color_e, self._calc_oct(freqs_e, avg_e))
            extra_levels[cid]=dbfs_e
        for src in self._spec_extra:
            if src['id'] in extra_levels and src.get('card'):
                src['card'].update_level(extra_levels[src['id']])
        if data is not None and self._spec_running():
            freqs,avg_cal,raw_spl,raw_peak,cal_spl,cal_peak,dba,dbc=data
            self.vu_a.update_level(raw_spl,raw_peak,cal_spl,cal_peak)
            self.i_spl.setText(f'{cal_spl:.1f} dB')
            self.i_pk.setText(f'{cal_peak:.1f} dB')
            pi=int(np.argmax(avg_cal[1:]))+1; df=float(freqs[pi])  # DC 빈(0Hz) 제외
            self.i_dom.setText(f'{df/1000:.2f}kHz' if df>=1000 else f'{df:.0f}Hz')
            now=time.time()
            if now-self._dba_display_t>=0.5:
                def _sc(v, base): return '#FF453A' if v>self._i_peak_db else '#FF9F0A' if v>self._i_warn_db else base
                self.i_dba.setStyleSheet(f'color:{_sc(dba,self._i_dba_base)};font-size:18px;font-weight:bold;')
                self.i_dba.setText(f'{dba:.1f}')
                self.i_dbc.setStyleSheet(f'color:{_sc(dbc,self._i_dbc_base)};font-size:18px;font-weight:bold;')
                self.i_dbc.setText(f'{dbc:.1f}')
                self._laeq_buf.append(dba)
                self._lceq_buf.append(dbc)
                if len(self._laeq_buf) >= 2:
                    arr_a = np.array(self._laeq_buf)
                    arr_c = np.array(self._lceq_buf)
                    laeq_v = 10*np.log10(np.mean(10**(arr_a/10)))
                    lceq_v = 10*np.log10(np.mean(10**(arr_c/10)))
                    self.i_laeq.setStyleSheet(f'color:{_sc(laeq_v,self._i_laeq_base)};font-size:14px;font-weight:bold;')
                    self.i_laeq.setText(f'{laeq_v:.1f}')
                    self.i_lceq.setStyleSheet(f'color:{_sc(lceq_v,self._i_lceq_base)};font-size:14px;font-weight:bold;')
                    self.i_lceq.setText(f'{lceq_v:.1f}')
                self._dba_display_t=now
            _clip = self._raw_spl_smooth > -6
            self.fft_cvs.clipping = _clip
            self.oct_cvs.clipping = _clip
            _pvis = self.fft_cvs._primary_visible
            if self.view_mode=='fft':
                if _pvis: self.fft_cvs.set_data(freqs,avg_cal)
                elif self.fft_cvs._ch_curves: self.fft_cvs.update()
            else:
                if _pvis: self.oct_cvs.update_data(self.view_mode,self._calc_oct(freqs,avg_cal))
            if self._spectro_on and _pvis:
                self.spectro_cvs.set_data(freqs,avg_cal)
            if self._pending_auto_fit:
                self._auto_fit_frame_count += 1
                if self._auto_fit_frame_count >= self.avg_count:
                    self._auto_fit_y_to_data()
            # primary 카드 레벨 (raw dBFS)
            if self._primary_card is not None:
                self._primary_card.update_level(raw_spl)



    # ── 멀티채널 오디오 처리
    def _process_audio_multi(self, buf_dict):
        # primary 구독은 단일 채널 — dict 에서 primary 채널 버퍼만 처리
        primary_ch = self.in_ch_cb.currentData() or 0
        buf = buf_dict.get(primary_ch)
        if buf is None and buf_dict:
            buf = next(iter(buf_dict.values()))   # 안전망: 첫 채널
        if buf is not None:
            self._process_audio(buf)

    def _on_extra_chunk(self, card_id, buf_dict):
        """추가 소스 구독 콜백 — 해당 카드 채널 버퍼만 처리."""
        src = next((s for s in self._spec_extra if s['id'] == card_id), None)
        if src is None: return
        buf = buf_dict.get(src['ch'])
        if buf is None or not np.isfinite(buf).all(): return
        self._process_extra_source(card_id, buf, src.get('sr', self.sample_rate), src.get('color', '#00D4FF'))

    def _process_extra_source(self, card_id, buf, sr, color):
        n = len(buf)
        win = np.hanning(n).astype(np.float32)
        spec = np.abs(np.fft.rfft(buf * win)); np.maximum(spec, 1e-10, out=spec)
        db_raw = 20 * np.log10(spec / (n / 2))
        freqs = np.fft.rfftfreq(n, 1.0 / sr).astype(np.float32)   # 소스 장치 SR 기준
        s = self.smoothing
        pow_raw = 10 ** (db_raw / 10)
        rms = float(np.sqrt(np.mean(buf ** 2)))
        raw_dbfs = 20 * math.log10(max(rms, 1e-10))
        with QMutexLocker(self._mutex):
            state = self._ch_state.setdefault(card_id, {
                'pow_smooth': None, 'fft_smooth': None,
                'avg_buf': deque(maxlen=self.avg_count)
            })
            if state['pow_smooth'] is None or len(state['pow_smooth']) != len(pow_raw):
                state['pow_smooth'] = pow_raw.copy()
                state['fft_smooth'] = db_raw.copy()
            else:
                state['pow_smooth'] *= s
                state['pow_smooth'] += pow_raw * (1 - s)
                np.log10(np.maximum(state['pow_smooth'], 1e-30), out=state['fft_smooth'])
                state['fft_smooth'] *= 10.0
            state['avg_buf'].append(state['fft_smooth'].copy())
            avg_cal = np.mean(list(state['avg_buf']), axis=0) + self.calib_offset
            self._ch_pending_extra[card_id] = (freqs, avg_cal, raw_dbfs, color)

    # ── 장치/채널 유틸
    def _input_device_items(self):
        return [(self.dev_cb.itemText(i), self.dev_cb.itemData(i)) for i in range(self.dev_cb.count())]

    def _dev_input_channels(self, idx):
        try: return int(sd.query_devices(idx)['max_input_channels']) if idx is not None and idx >= 0 else 1
        except Exception: return 1

    def _device_native_sr(self, idx):
        _OK = {44100, 48000, 88200, 96000}
        try:
            ns = int(sd.query_devices(idx)['default_samplerate'])
            return ns if ns in _OK else (48000 if ns >= 48000 else 44100)
        except Exception:
            return self.sample_rate

    # ── 카드 관리 (primary ChannelCard + 멀티-장치 _SpecCard)
    def _rebuild_ch_cards(self):
        for card in self._ch_cards.values():
            card.setParent(None)
        if self._primary_card is not None:
            self._primary_card.setParent(None); self._primary_card = None
        self._ch_cards.clear()
        while self._ch_cards_layout.count():
            item = self._ch_cards_layout.takeAt(0)
            if item.widget(): item.widget().setParent(None)

        dev_items = self._input_device_items()
        primary_ch = self.in_ch_cb.currentData() or 0
        primary_color = T('spec_line')   # 브랜드 spec_line(라이트 #1670cc) 통일
        # primary 도 _SpecCard 로 통일 (장치+채널 드롭다운). 삭제버튼만 숨김.
        pc = _SpecCard(0, primary_color, dev_items, is_primary=True)
        if self.dev_cb.currentData() is not None: pc.set_device(self.dev_cb.currentData())
        pc.set_channel_list(self._dev_input_channels(self.dev_cb.currentData()))
        pc.set_channel(primary_ch)
        pc.set_selected(self._spec_front_id == 0)
        pc.set_number(1)
        pc.set_name(getattr(self, '_spec_primary_name', ''))
        pc.device_changed.connect(self._on_primary_dev_changed)
        pc.channel_changed.connect(self._on_primary_ch_changed)
        pc.visibility_toggled.connect(lambda _cid, vis: self._on_card_visibility(vis))
        pc.selected.connect(self._on_spec_card_select)
        pc.renamed.connect(self._on_spec_renamed)
        self._primary_card = pc
        self._ch_cards_layout.addWidget(pc)

        for src in self._spec_extra:
            sc = _SpecCard(src['id'], src['color'], dev_items)   # 고정 색 (num 기반)
            if src.get('dev_idx') is not None: sc.set_device(src['dev_idx'])
            sc.set_channel_list(self._dev_input_channels(src.get('dev_idx')))
            sc.set_channel(src.get('ch', 0))
            sc._chk.blockSignals(True); sc._chk.setChecked(src.get('visible', True)); sc._chk.blockSignals(False)
            sc.set_selected(self._spec_front_id == src['id'])
            sc.set_number(src.get('num', 2))                     # 고정 표시 번호
            sc.set_name(src.get('name', ''))
            sc.device_changed.connect(self._on_spec_dev_changed)
            sc.channel_changed.connect(self._on_spec_ch_changed)
            sc.visibility_toggled.connect(self._on_spec_visibility)
            sc.remove_requested.connect(self._spec_remove_source)
            sc.selected.connect(self._on_spec_card_select)
            sc.renamed.connect(self._on_spec_renamed)
            src['card'] = sc
            self._ch_cards_layout.addWidget(sc)
        self._ch_cards_layout.addStretch(1)

    def _on_spec_renamed(self, card_id, txt):
        if card_id == 0:
            self._spec_primary_name = txt
        else:
            src = next((s for s in self._spec_extra if s['id'] == card_id), None)
            if src is not None: src['name'] = txt
        self._save_spec_sources()

    def _on_card_visibility(self, visible):
        # primary 카드 가시성 (oct/spectro/SPL 전용 소스)
        self.fft_cvs._primary_visible = visible
        if not visible:
            self.oct_cvs.clear(); self.spectro_cvs.clear()
        self.fft_cvs.update()

    def _on_primary_dev_changed(self, _cid):
        if getattr(self, '_restoring_devices', False): return
        pc = self._primary_card
        if pc is None: return
        idx = pc.device_idx()
        for i in range(self.dev_cb.count()):
            if self.dev_cb.itemData(i) == idx:
                self.dev_cb.setCurrentIndex(i); break   # → _on_device_changed (재시작+calib+rebuild)

    def _on_primary_ch_changed(self, _cid):
        if getattr(self, '_restoring_devices', False): return
        pc = self._primary_card
        if pc is None: return
        ch = pc.channel()
        for i in range(self.in_ch_cb.count()):
            if self.in_ch_cb.itemData(i) == ch:
                self.in_ch_cb.setCurrentIndex(i); break   # → _on_input_ch_changed

    def _on_spec_card_select(self, card_id):
        self._spec_front_id = card_id
        if self._primary_card: self._primary_card.set_selected(card_id == 0)
        for src in self._spec_extra:
            if src.get('card'): src['card'].set_selected(src['id'] == card_id)
        # 라이브 카드 클릭 → 라이브 포커스(캡쳐 선택 해제 → 캡쳐 흐리게, 라이브 솔리드) + 그 소스 맨앞
        for cvs in (self.fft_cvs, self.oct_cvs):
            cvs._front_id = card_id
            cvs._live_on_top = True; cvs._front_idx = None
            cvs._cap_pix = None; cvs.update()

    # ── 멀티-장치 추가 소스 관리
    def _spec_smallest_unused_num(self):
        """추가카드용 가장 작은 빈 번호(≥2). 삭제 후에도 고정·빈자리 채움."""
        used = {s.get('num') for s in self._spec_extra}
        n = 2
        while n in used: n += 1
        return n

    def _spec_add_source(self):
        cid = self._spec_next_id; self._spec_next_id += 1
        num = self._spec_smallest_unused_num()
        color = _MC_COLORS[(num - 2) % len(_MC_COLORS)]
        self._spec_extra.append({
            'id': cid, 'num': num, 'dev_idx': self.dev_cb.currentData(),
            'dev_name': self.dev_cb.currentText(), 'ch': 0,
            'sr': self.sample_rate, 'color': color,
            'visible': True, 'name': '', 'sub': None, 'card': None, 'state': None})
        self._rebuild_ch_cards()
        if self._spec_running():
            self._open_spec_sub(self._spec_extra[-1])
        self._save_spec_sources()

    def _spec_remove_source(self, card_id):
        src = next((s for s in self._spec_extra if s['id'] == card_id), None)
        if src is None: return
        self._close_spec_sub(src)
        self._clear_extra_curve(card_id)
        self._spec_extra.remove(src)
        if self._spec_front_id == card_id:   # front 카드 삭제 → primary front 로
            self._spec_front_id = 0
            self.fft_cvs._front_id = 0; self.oct_cvs._front_id = 0
        self._rebuild_ch_cards()
        self._save_spec_sources()

    def _on_spec_dev_changed(self, card_id):
        src = next((s for s in self._spec_extra if s['id'] == card_id), None)
        if src is None or src.get('card') is None: return
        card = src['card']
        src['dev_idx'] = card.device_idx(); src['dev_name'] = card.device_name()
        card.set_channel_list(self._dev_input_channels(src['dev_idx']))
        src['ch'] = card.channel()
        self._clear_extra_curve(card_id)
        if self._spec_running(): self._open_spec_sub(src)
        self._save_spec_sources()

    def _on_spec_ch_changed(self, card_id):
        src = next((s for s in self._spec_extra if s['id'] == card_id), None)
        if src is None or src.get('card') is None: return
        src['ch'] = src['card'].channel()
        self._clear_extra_curve(card_id)
        if self._spec_running(): self._open_spec_sub(src)
        self._save_spec_sources()

    def _on_spec_visibility(self, card_id, visible):
        src = next((s for s in self._spec_extra if s['id'] == card_id), None)
        if src is not None: src['visible'] = visible
        if card_id in self.fft_cvs._ch_curves:
            self.fft_cvs._ch_curves[card_id]['visible'] = visible
            self.fft_cvs.update()
        if card_id in self.oct_cvs._ch_oct:
            self.oct_cvs._ch_oct[card_id]['visible'] = visible
            self.oct_cvs.update()
        self._save_spec_sources()

    def _clear_extra_curve(self, card_id):
        self.fft_cvs.clear_channel(card_id)
        self.oct_cvs.clear_channel(card_id)
        with QMutexLocker(self._mutex):
            self._ch_state.pop(card_id, None)
            self._ch_pending_extra.pop(card_id, None)

    def _open_spec_sub(self, src):
        self._close_spec_sub(src)
        dev = src.get('dev_idx')
        if dev is None or dev < 0: return
        existing = self.audio_engine._streams.get(dev)
        sr = existing.sample_rate if existing else self._device_native_sr(dev)
        src['sr'] = sr
        try:
            sub = self.audio_engine.subscribe(dev, [src['ch']], sr)
        except Exception as e:
            _alog.warning(f'spec extra sub failed dev={dev} ch={src["ch"]}: {e}'); return
        cid = src['id']
        sub.chunk_ready.connect(lambda d, _c=cid: self._on_extra_chunk(_c, d), Qt.QueuedConnection)
        src['sub'] = sub

    def _close_spec_sub(self, src):
        sub = src.get('sub')
        if sub is not None:
            try: sub.chunk_ready.disconnect()
            except Exception: pass
            try: sub.close()
            except Exception: pass
            src['sub'] = None

    def _start_spec_extra_subs(self):
        for src in self._spec_extra: self._open_spec_sub(src)

    def _stop_spec_extra_subs(self):
        for src in self._spec_extra:
            self._close_spec_sub(src)
            if src.get('card'): src['card'].reset()

    def _save_spec_sources(self):
        if getattr(self, '_restoring_spec', False): return
        self._settings['spec_sources'] = [
            {'dev_name': s.get('dev_name', ''), 'ch': s.get('ch', 0),
             'visible': s.get('visible', True), 'name': s.get('name', ''),
             'num': s.get('num', 2)}
            for s in self._spec_extra]
        self._settings['spec_primary_name'] = getattr(self, '_spec_primary_name', '')
        _save_settings(self._settings)

    def _restore_spec_sources(self):
        self._spec_primary_name = self._settings.get('spec_primary_name', '')
        saved = self._settings.get('spec_sources', [])
        if not saved: return
        self._restoring_spec = True
        try:
            for entry in saved:
                cid = self._spec_next_id; self._spec_next_id += 1
                num = entry.get('num') or self._spec_smallest_unused_num()
                color = _MC_COLORS[(num - 2) % len(_MC_COLORS)]
                dev_idx = None
                for i in range(self.dev_cb.count()):
                    if self.dev_cb.itemText(i) == entry.get('dev_name', ''):
                        dev_idx = self.dev_cb.itemData(i); break
                self._spec_extra.append({
                    'id': cid, 'num': num, 'dev_idx': dev_idx, 'dev_name': entry.get('dev_name', ''),
                    'ch': entry.get('ch', 0), 'sr': self.sample_rate, 'color': color,
                    'visible': entry.get('visible', True), 'name': entry.get('name', ''),
                    'sub': None, 'card': None, 'state': None})
        finally:
            self._restoring_spec = False
        self._rebuild_ch_cards()

    def _calc_oct(self,freqs,db_vals,mode=None):
        if mode is None: mode=self.view_mode
        bands=BANDS[mode]
        bpo=3 if mode=='oct3' else 12 if mode=='oct12' else 24
        half=1/(2*bpo)
        res=[]
        for fc in bands:
            fl,fh=fc/2**half,fc*2**half; mask=(freqs>=fl)&(freqs<=fh)
            if mask.any():
                # 밴드 내 파워 합산 → dB (IEC 61260 옥타브 밴드 분석기 표준)
                res.append(float(10*np.log10(np.sum(10**(db_vals[mask]/10)))))
            else:
                # FFT 해상도가 낮아 밴드 내 빈이 없을 때 → 인접 빈 선형 보간
                idx=int(np.argmin(np.abs(freqs-fc)))
                if 0<idx<len(freqs)-1:
                    f0,f1=float(freqs[idx-1]),float(freqs[idx])
                    t=(fc-f0)/(f1-f0) if f1>f0 else 0.5
                    t=max(0.0,min(1.0,t))
                    db_i=float(db_vals[idx-1])*(1-t)+float(db_vals[idx])*t
                else:
                    db_i=float(db_vals[idx])
                res.append(db_i)
        return res

    # ── 툴바
    def _toggle_spectro(self):
        self._spectro_on=self.spectro_btn.isChecked()
        self._apply_canvas_layout()

    def _apply_canvas_layout(self):
        m=self.view_mode; h=self.cvs_splitter.height()
        is_fft=(m=='fft')
        self.fft_cvs.setVisible(is_fft)
        self.oct_cvs.setVisible(not is_fft)
        if not is_fft: self.oct_cvs.set_mode(m)
        self.spectro_cvs.setVisible(self._spectro_on)
        if self._spectro_on:
            top=int(h*0.55); bot=int(h*0.45)
            if is_fft: self.cvs_splitter.setSizes([top,0,bot])
            else:       self.cvs_splitter.setSizes([0,top,bot])
        else:
            if is_fft: self.cvs_splitter.setSizes([h,0,0])
            else:       self.cvs_splitter.setSizes([0,h,0])

    def _set_view(self,m):
        _alog.info(f'뷰 모드 전환  mode={m}')
        self.view_mode=m
        if m in ('oct3','oct12','oct24'): self._last_oct_mode=m
        self._view_seg.set_active(m)
        self._scale_seg.setEnabled(m=='fft')
        self._apply_canvas_layout()

    def _sr_changed(self,idx):
        self.sample_rate=[44100,48000,88200,96000][idx]
        _alog.info(f'샘플레이트 변경  sr={self.sample_rate} Hz')
        self.i_sr.setText(f'{self.sample_rate/1000:.1f} kHz')
        self.i_res.setText(f'{self.sample_rate/self.fft_size:.1f} Hz')
        if self._spec_running(): self._stop(); self._start()

    def _fft_changed(self,idx):
        self.fft_size=[16384][idx]
        with QMutexLocker(self._mutex): self._fft_smooth=None; self._avg_buf.clear()
        self.i_fft.setText(str(self.fft_size))
        self.i_res.setText(f'{self.sample_rate/self.fft_size:.1f} Hz')
        self.fft_cvs.fft_size=self.fft_size
        if self._spec_running(): self._stop(); self._start()

    def _set_scale(self,log):
        self._scale_seg.set_active('log' if log else 'lin')
        self.fft_cvs.scale_log=log; self.fft_cvs._cache=None; self.fft_cvs.update()

    def _set_speed(self,idx):
        self.speed_idx=idx; s=SPEED_LEVELS[idx][1]; self.smoothing=s
        if self.spd_cb.currentIndex()!=idx: self.spd_cb.setCurrentIndex(idx)
        self.i_spd.setText(SPEED_LEVELS[idx][0])
        alpha=1.0-s
        decay=[0.05,0.10,0.20,0.35,0.55][idx]
        self.oct_cvs.set_speed(alpha,decay)
        self.fft_cvs._speed_idx=idx

    def _avg_changed(self,idx):
        self.avg_count=[1,4,8,16][idx]
        with QMutexLocker(self._mutex): self._avg_buf=deque(maxlen=self.avg_count)

    def _toggle_peak(self):
        self.peak_hold=self.peak_btn.isChecked()
        self.peak_btn.setText('ON' if self.peak_hold else 'OFF')
        self.fft_cvs.set_peak_hold(self.peak_hold)
        self.oct_cvs.set_peak_hold(self.peak_hold)

    def _reset_peak(self):
        self.fft_cvs.reset_peak(); self.oct_cvs.reset_peak()

    def _space_capture(self):
        idx = self.main_stack.currentIndex()
        if idx == 2:
            return  # Stereo Loudness 탭에서는 스페이스바 무시
        if idx == 1:
            self.tf_win._do_tf_capture(prompt=False)  # 스페이스바 = 빠른 캡쳐 (자동 이름)
        else:
            self._do_spec_capture()

    def _do_spec_capture(self):
        n = len(self.fft_cvs._captures) + len(self.oct_cvs._captures)
        default = f'Capture {n + 1}'
        label, ok = _text_input_dialog(self, '캡처', '이름:', default)
        if not ok: return
        label = label.strip() or default
        color = _auto_capture_color(n)
        group = self._current_spec_group
        m = self.view_mode
        if m == 'fft':
            self.fft_cvs.add_capture(label, color, group)
        else:
            self.oct_cvs.add_capture(label, color, group)
        _alog.info(f'스펙트럼 캡처 추가  label="{label}"  mode={m}  total={n+1}')
        self._refresh_spec_capture_bar()
        self._save_spec_captures()

    def _refresh_spec_capture_bar(self):
        self._refresh_capture_drawer()

    def _refresh_capture_drawer(self):
        spec_caps = []
        for cap in self.fft_cvs._captures:
            spec_caps.append({**cap, 'mode': 'FFT', '_src': 'fft'})
        for cap in self.oct_cvs._captures:
            spec_caps.append({**cap, '_src': 'oct'})
        tf_caps = self.tf_win._tf_captures if hasattr(self, 'tf_win') else []
        self._capture_drawer.refresh(spec_caps, tf_caps)

    def _on_drawer_delete(self, mode, idx):
        if mode == 'spec':
            self._on_spec_capture_delete(idx)
        elif mode == 'tf':
            self.tf_win._on_tf_capture_delete(idx)

    def _on_drawer_select(self, mode, idx):
        if mode == 'spec':
            self._on_spec_capture_select(idx)
        elif mode == 'tf' and hasattr(self, 'tf_win') and self.tf_win is not None:
            self.tf_win._on_tf_capture_select(idx)

    def _on_drawer_visibility(self, mode, idx, visible):
        if mode == 'spec':
            fft_n = len(self.fft_cvs._captures)
            if idx < fft_n:
                if 0 <= idx < len(self.fft_cvs._captures):
                    self.fft_cvs._captures[idx]['visible'] = visible
                    self.fft_cvs._cap_pix = None; self.fft_cvs.update()
            else:
                oi = idx - fft_n
                if 0 <= oi < len(self.oct_cvs._captures):
                    self.oct_cvs._captures[oi]['visible'] = visible
                    self.oct_cvs._cap_pix = None; self.oct_cvs.update()
        elif mode == 'tf' and hasattr(self, 'tf_win') and self.tf_win is not None:
            tf = self.tf_win
            if 0 <= idx < len(tf._tf_captures):
                tf._tf_captures[idx]['visible'] = visible
                for cvs in (tf.mag_cvs, tf.phase_cvs, tf.ir_cvs):
                    if 0 <= idx < len(cvs._captures):
                        cvs._captures[idx]['visible'] = visible
                        cvs._cap_pix = None; cvs.update()

    def _on_drawer_average(self, mode):
        if mode == 'tf' and hasattr(self, 'tf_win') and self.tf_win is not None:
            self.tf_win._do_tf_average()

    def _on_drawer_reference(self, mode, idx):
        if mode == 'tf' and hasattr(self, 'tf_win') and self.tf_win is not None:
            self.tf_win._on_set_reference(idx)

    def _on_drawer_export(self, mode):
        if mode == 'tf' and hasattr(self, 'tf_win') and self.tf_win is not None:
            self.tf_win._export_tf_captures()

    def _on_drawer_rename(self, mode, idx, name):
        if mode == 'spec':
            fft_n = len(self.fft_cvs._captures)
            if idx < fft_n:
                if 0 <= idx < len(self.fft_cvs._captures):
                    self.fft_cvs._captures[idx]['label'] = name
            else:
                oi = idx - fft_n
                if 0 <= oi < len(self.oct_cvs._captures):
                    self.oct_cvs._captures[oi]['label'] = name
            self._refresh_spec_capture_bar()
        elif mode == 'tf':
            n = idx
            if 0 <= n < len(self.tf_win._tf_captures):
                self.tf_win._tf_captures[n]['label'] = name
                for cvs in (self.tf_win.mag_cvs, self.tf_win.phase_cvs, self.tf_win.ir_cvs):
                    if 0 <= n < len(cvs._captures):
                        cvs._captures[n]['label'] = name
            self.tf_win._refresh_tf_capture_bar()

    def _on_drawer_new_group(self, mode):
        name, ok = _text_input_dialog(self, '새 그룹', '그룹 이름:')
        if not ok or not name.strip(): return
        name = name.strip()
        if mode == 'spec':
            self._current_spec_group = name
        else:
            self.tf_win._current_tf_group = name
        # 드로어에 "활성 그룹" 즉시 표시
        self._capture_drawer.set_pending_group(mode, name)
        self._refresh_capture_drawer()

    def _on_drawer_delete_group(self, mode, gname):
        if mode == 'spec':
            self.fft_cvs._captures = [c for c in self.fft_cvs._captures if c.get('group','') != gname]
            self.oct_cvs._captures = [c for c in self.oct_cvs._captures if c.get('group','') != gname]
            self.fft_cvs._cap_pix = None; self.fft_cvs.update()
            self.oct_cvs._cap_pix = None; self.oct_cvs.update()
            if getattr(self, '_current_spec_group', '') == gname:
                self._current_spec_group = ''
            pg = getattr(self._capture_drawer, '_pending_group', None)
            if pg and pg == ('spec', gname):
                self._capture_drawer._pending_group = None
            self._refresh_spec_capture_bar()
            self._save_spec_captures()
        elif mode == 'tf':
            tf = self.tf_win
            idxs = [i for i, c in enumerate(tf._tf_captures) if c.get('group','') == gname]
            for i in sorted(idxs, reverse=True):
                tf.mag_cvs.remove_capture(i)
                tf.phase_cvs.remove_capture(i)
                tf.ir_cvs.remove_capture(i)
                tf._tf_captures.pop(i)
            if getattr(tf, '_current_tf_group', '') == gname:
                tf._current_tf_group = ''
            pg = getattr(self._capture_drawer, '_pending_group', None)
            if pg and pg == ('tf', gname):
                self._capture_drawer._pending_group = None
            tf._refresh_tf_capture_bar()
            tf._save_tf_captures()

    def _on_drawer_move_to_group(self, mode, idx, group):
        """캡처를 그룹으로 이동(또는 ''로 그룹 해제). group 필드만 바꾸면
        _build_section 이 해당 그룹 섹션에 렌더 — 빈 그룹으로도 이동 가능."""
        if mode == 'tf':
            tf = self.tf_win
            if 0 <= idx < len(tf._tf_captures):
                tf._tf_captures[idx]['group'] = group
                tf._refresh_tf_capture_bar()
                tf._save_tf_captures()
        elif mode == 'spec':
            fft_n = len(self.fft_cvs._captures)
            if idx < fft_n:
                if 0 <= idx < len(self.fft_cvs._captures):
                    self.fft_cvs._captures[idx]['group'] = group
            else:
                oi = idx - fft_n
                if 0 <= oi < len(self.oct_cvs._captures):
                    self.oct_cvs._captures[oi]['group'] = group
            self.fft_cvs._cap_pix = None; self.fft_cvs.update()
            self.oct_cvs._cap_pix = None; self.oct_cvs.update()
            self._refresh_spec_capture_bar()
            self._save_spec_captures()

    def _on_drawer_reorder(self, mode, src, tgt):
        if mode == 'spec':
            combined = [{**c, '_src': 'fft'} for c in self.fft_cvs._captures]
            combined += [{**c, '_src': 'oct'} for c in self.oct_cvs._captures]
            n = len(combined)
            if not (0 <= src < n): return
            item = combined.pop(src)
            ins = tgt if tgt <= src else tgt - 1
            ins = max(0, min(ins, len(combined)))
            combined.insert(ins, item)
            strip = lambda c: {k: v for k, v in c.items() if k not in ('_src', 'mode')}
            self.fft_cvs._captures = [strip(c) for c in combined if c['_src'] == 'fft']
            self.oct_cvs._captures = [strip(c) for c in combined if c['_src'] == 'oct']
            self.fft_cvs._cap_pix = None; self.fft_cvs.update()
            self.oct_cvs._cap_pix = None; self.oct_cvs.update()
            self._refresh_capture_drawer()
            self._save_spec_captures()
        elif mode == 'tf':
            tf = self.tf_win
            n = len(tf._tf_captures)
            if not (0 <= src < n): return
            ins = tgt if tgt <= src else tgt - 1
            ins = max(0, min(ins, n - 1))
            tf._tf_captures.insert(ins, tf._tf_captures.pop(src))
            for cvs in (tf.mag_cvs, tf.phase_cvs, tf.ir_cvs):
                cvs._captures.insert(ins, cvs._captures.pop(src))
                cvs._cap_pix = None; cvs.update()
            tf._refresh_tf_capture_bar()
            tf._save_tf_captures()

    def _on_spec_capture_delete(self, idx):
        fft_n = len(self.fft_cvs._captures)
        if idx < fft_n:
            label = self.fft_cvs._captures[idx].get('label', str(idx))
            self.fft_cvs.remove_capture(idx)
        else:
            oi = idx - fft_n
            label = self.oct_cvs._captures[oi].get('label', str(idx))
            self.oct_cvs.remove_capture(oi)
        _alog.info(f'스펙트럼 캡처 삭제  label="{label}"')
        self._refresh_spec_capture_bar()
        self._save_spec_captures()

    def _on_spec_capture_select(self, idx):
        fft_n = len(self.fft_cvs._captures)
        if idx < fft_n:
            self.fft_cvs.bring_to_front(idx)
        else:
            self.oct_cvs.bring_to_front(idx - fft_n)
        self._refresh_spec_capture_bar()

    # ── 캡처 영속성 ───────────────────────────
    def _save_spec_captures(self):
        try:
            fft_list = [
                {'f': c['f'].tolist(), 'db': c['db'].tolist(),
                 'color': c['color'], 'label': c['label'], 'group': c.get('group', '')}
                for c in self.fft_cvs._captures
            ]
            oct_list = [
                {'values': c['values'].tolist(), 'mode': c.get('mode', 'oct3'),
                 'color': c['color'], 'label': c['label'], 'group': c.get('group', '')}
                for c in self.oct_cvs._captures
            ]
            with _CAPTURES_LOCK:   # TF 백그라운드 저장과 같은 파일 공유 → 클로버 방지
                data = _load_captures_file()
                data['fft'] = fft_list
                data['oct'] = oct_list
                _save_captures_file(data)
        except Exception as e:
            _alog.warning(f'스펙트럼 캡처 저장 실패: {e}')

    def _restore_spec_captures(self):
        data = _load_captures_file()
        for cap in data.get('fft', []):
            try:
                self.fft_cvs._captures.append({
                    'f':  np.array(cap['f'],  dtype=np.float32),
                    'db': np.array(cap['db'], dtype=np.float32),
                    'color': cap['color'], 'label': cap['label'],
                    'group': cap.get('group', '')
                })
            except Exception: pass
        for cap in data.get('oct', []):
            try:
                self.oct_cvs._captures.append({
                    'values': np.array(cap['values'], dtype=np.float32),
                    'mode': cap.get('mode', 'oct3'),
                    'color': cap['color'], 'label': cap['label'],
                    'group': cap.get('group', '')
                })
            except Exception: pass
        if self.fft_cvs._captures or self.oct_cvs._captures:
            self.fft_cvs._cap_pix = None; self.fft_cvs.update()
            self.oct_cvs._cap_pix = None; self.oct_cvs.update()
            self._refresh_spec_capture_bar()

    def _on_input_live_front(self):
        for cvs in (self.fft_cvs, self.oct_cvs):
            cvs._live_on_top = True
            cvs._front_idx = None
            cvs._cap_pix = None; cvs.update()

    def _set_peak_hold_time(self, idx):
        # 홀드 시간 (초) × 30fps = 홀드 프레임 수. 낙하 속도는 20dB/s 고정
        hold_frames = [3, 9, 15, 30][idx]  # Fast≈0.1s | 0.3s | 0.5s | 1s(slowest)
        self.fft_cvs.set_peak_hold_time(hold_frames)
        self.oct_cvs.set_peak_hold_time(hold_frames)

    def _db_changed(self,idx):
        self.db_range=[72,96,120][idx]; self.db_min=self.db_max-self.db_range
        self._apply_db_range()


    def _apply_calib_thresholds(self):
        offset = self.calib_offset
        if hasattr(self, 'spl_meter_win') and self.spl_meter_win:
            self.spl_meter_win.set_calib_offset(offset)
        self._i_warn_db = -20.0 + offset
        self._i_peak_db = -10.0 + offset

    def _db_shift(self, step):
        self.db_min+=step; self.db_max+=step; self._apply_db_range()

    def keyPressEvent(self, e):
        # 캔버스 위에 커서가 있으면 _CanvasKeyRouter가 이미 처리했거나 처리할 것이므로 무시
        w = QApplication.widgetAt(QCursor.pos())
        while w is not None:
            if w in (self.spectro_cvs, self.oct_cvs, self.fft_cvs):
                super().keyPressEvent(e)
                return
            w = w.parent()
        if e.key() == Qt.Key_Up:
            self._db_shift(6)
        elif e.key() == Qt.Key_Down:
            self._db_shift(-6)
        else:
            super().keyPressEvent(e)

    def _open_color_picker(self):
        global _custom_color, _bar_preset_idx
        init = QColor(*_custom_color) if _custom_color else QColor(*bar_top()[:3])
        color = QColorDialog.getColor(init, self, '그래프 색상 선택')
        if color.isValid():
            _custom_color = (color.red(), color.green(), color.blue())
            _bar_preset_idx = 0
            self.fft_cvs._cache = None; self.oct_cvs._cache = None
            self.fft_cvs.update(); self.oct_cvs.update()

    def _show_license_info(self):
        mid = _get_machine_id()
        key = load_license() or '(없음)'
        valid, reason = verify_license(key) if key != '(없음)' else (False, '')
        status = '활성화됨' if valid else '미활성화'
        from PyQt5.QtWidgets import QMessageBox
        QMessageBox.information(self, 'SPECTRA 라이선스 정보',
            f'머신 ID:  {mid}\n'
            f'시리얼 키: {key[:28]}…\n'
            f'상태:  {status}\n\n'
            f'로그 위치:\n{_LOG_DIR}')

    def closeEvent(self,e):
        self._render_t.stop()
        self.stereo_page.stop()
        self._stop()
        # 보류된 TF 캡쳐 저장 flush — 종료 시 동기 저장(앱 종료 중이라 글리치 무관)
        try:
            tw = self.tf_win
            if tw is not None:
                tw._flush_tf_captures(sync=True)
        except Exception as ex:
            _alog.warning(f'close flush 실패: {ex}')
        e.accept()


if __name__=='__main__':
    from PyQt5.QtGui import QPixmap

    # ── macOS Monterey+ Retina / High-DPI 지원
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps,   True)

    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    app.setApplicationName('SPECTRA')
    # 앱 전체 글꼴 — 가족만 교체(크기는 위젯별 stylesheet/기본 유지) → 레이아웃 영향 최소
    _appf = app.font(); _appf.setFamily(FONT_FAMILY); app.setFont(_appf)

    # ── 세션 시작 로그 헤더
    _alog.info('=' * 60)
    _alog.info(f'SPECTRA v1.3  시작  {_dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    _alog.info(f'OS: {_pl.platform()}')
    _alog.info(f'Machine: {_pl.machine()}  Processor: {_pl.processor()}')
    _alog.info(f'Python: {_pl.python_version()}')
    _alog.info(f'Log: {_LOG_PATH}')
    _alog.info('=' * 60)

    # ── PyInstaller 번들 내 리소스 경로
    def _res(name):
        base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(base, name)

    # ── 라이선스 확인
    if not check_license_at_startup():
        _alog.info('라이선스 미확인 → LicenseDialog 표시')
        dlg = LicenseDialog()
        dlg.setStyleSheet('background:#1C1C1E;color:#FFFFFF;')
        if dlg.exec() != QDialog.Accepted:
            _alog.info('라이선스 입력 취소 → 종료')
            sys.exit(0)
        _alog.info('라이선스 활성화 완료')
    else:
        _alog.info(f'라이선스 유효  머신={_get_machine_id()}')

    splash = None
    splash_img = _res('splash.png')
    if os.path.exists(splash_img):
        pix = QPixmap(splash_img)
        dpr = app.devicePixelRatio()
        if dpr > 1.0:
            pix = pix.scaled(
                int(pix.width() * dpr), int(pix.height() * dpr),
                Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            pix.setDevicePixelRatio(dpr)
        splash = QSplashScreen(pix, Qt.WindowStaysOnTopHint)
        splash.show()
        app.processEvents()

    app.aboutToQuit.connect(_emergency_cleanup)  # USB 스트림 정상 종료 보장

    win = MainWindow()
    _key_router = _CanvasKeyRouter(win)
    app.installEventFilter(_key_router)
    if splash:
        def _launch():
            win.show()
            splash.close()
        QTimer.singleShot(3000, _launch)
    else:
        win.show()
    sys.exit(app.exec())
