11#!/usr/bin/env python3
# ═══════════════════════════════════════════════════
#  SPECTRA — Spectrum Analyzer  (by WAYAUDIO)  v1.9
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

# 로깅/진단/크래시 — v2.0 분해: spectra/core/logging_diag.py 로 이동, re-import(동작 불변)
# (import 시 로그셋업·excepthook·로그정리 실행 — 종전과 동일 시점)
from spectra.core.logging_diag import _alog, _diag, _LOG_PATH, _LOG_DIR

# 오디오 엔진 — v2.0 분해: spectra/audio/engine.py 로 이동, 일괄 re-import(동작 불변)
# (WASAPI 헬퍼 + AudioThread/MultiChannel/Subscription/_DeviceStream/AudioEngine/어댑터3종)
from spectra.audio.engine import (
    _win_preferred_hostapi, _dev_hostapi_ok, _win_extra_settings, _HI_LAT,
    AudioThread, MultiChannelAudioThread, Subscription, _DeviceStream, AudioEngine,
    _EngineSyncSource, _EngineMultiSource, _EngineChannelSource)
# _MC_COLORS(TF카드색) — v2.0: spectra/ui/colors.py 로 이전, re-import
from spectra.ui.colors import _MC_COLORS


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
    QRadialGradient, QPalette, QImage, QPixmap, QPolygon, QPolygonF, QKeySequence, QIcon, QFontMetrics
)
import math as _math

# ── 앱 버전 (단일 소스) ── 버전 올릴 땐 `bash bump_version.sh 1.6` 한 줄로 전부 갱신.
#   (이 상수 + 상단 주석 + WSA2.spec/build_intel.sh/version_info.txt 까지 스크립트가 처리)
_APP_VERSION = '1.9'

# 라이선스 — v2.0 분해: spectra/core/license.py 로 이동, re-import(동작 불변)
from spectra.core.license import (verify_license, load_license, save_license,
                                  check_license_at_startup, _get_machine_id)


# ═══════════════════════════════════════════════════════════════════
#  라이선스 입력 다이얼로그
# ═══════════════════════════════════════════════════════════════════
# LicenseDialog — v2.0 분해: spectra/ui/dialogs.py, re-import
from spectra.ui.dialogs import LicenseDialog
# ───────────────────────────────────────────
#  상수
# ───────────────────────────────────────────
# 스펙트럼 상수·밸리스틱 — v2.0 분해: spectra/core/config.py, re-import
from spectra.core.config import (MAX_DB, CAPTURE_COLORS, SPEC_ATTACK, SPEC_FALL_MS,
                                 _fall_ms_to_s, SPEED_LEVELS, FREQ_MARKS)
# 옥타브 밴드 정의 — v2.0 분해: spectra/dsp/weighting.py 로 이동, re-import(동작 불변)
from spectra.dsp.weighting import THIRD_OCT, make_oct_bands, BANDS
# FREQ_MARKS — v2.0 분해: spectra/core/config.py (위 re-import에 포함)

# ───────────────────────────────────────────
#  설정 저장/불러오기
# ───────────────────────────────────────────
# 설정 저장/불러오기 — v2.0 분해: spectra/core/config.py 로 이동, re-import(동작 불변)
from spectra.core.config import (_APP_SUPPORT, _SETTINGS_PATH, _CAPTURES_PATH, _CAPTURES_LOCK,
                                 _load_settings, _save_settings, _load_captures_file, _save_captures_file)

# ── i18n: 영어 원문을 키로 쓰는 경량 번역 ──────────────────────────
# i18n — v2.0 분해: spectra/core/i18n.py 로 이동, re-import(동작 불변)
from spectra.core.i18n import _TR_KO, _resolve_lang, _set_lang, cur_lang, _tx


# 모듈 로드 시점에 _LANG 확정
try:
    _set_lang(_resolve_lang(_load_settings()))
except Exception:
    pass


# A/C 가중(IEC 61672) — v2.0 분해: spectra/dsp/weighting.py 로 이동, 여기로 re-import(동작 불변)
from spectra.dsp.weighting import a_weight_db, c_weight_db

# 주파수 → 음이름 (커서 리드아웃용). A4=440Hz 기준 12평균율. (센트 단위는 사용자 요청으로 제거)
# 음이름 테이블 — v2.0 분해: spectra/ui/draw.py (freq_to_note와 함께)
# freq_to_note — v2.0 분해: spectra/ui/draw.py, re-import
from spectra.ui.draw import freq_to_note
from spectra.core.config import (sound_speed, set_sound_speed, delay_unit, set_delay_unit, ms_to_m, m_to_ms, fmt_delay)

# power_spectrum_db — v2.0 분해: spectra/dsp/weighting.py 로 이동, re-import(동작 불변)
from spectra.dsp.weighting import power_spectrum_db


# _octave_bands — v2.0 분해: spectra/dsp/weighting.py 로 이동, re-import(동작 불변)
from spectra.dsp.weighting import _octave_bands

# ───────────────────────────────────────────
#  테마
# ───────────────────────────────────────────
# 테마/설정 — v2.0 분해: spectra/core/config.py 로 이동, 함수만 re-import(_theme은 config 단독소유)
from spectra.core.config import THEMES, T, theme, is_dark, set_theme, toggle_theme

def _popout_toggle_ss():
    """팝아웃/툴바 토글 버튼 공용 스타일시트 (테마 인식). 다크는 기존 하드코딩과 바이트 동일."""
    # text_dim 다크값(#8E8E93)·border 다크값(#38383A)이 기존 하드코딩(#9A9AA0/#48484A)과 달라 다크는 옛 hex 유지
    bg3 = T('bg3'); accent = T('accent')
    txt = '#9A9AA0' if is_dark() else T('text_dim')
    bd  = '#48484A' if is_dark() else T('border')
    return (f'QPushButton{{background:{bg3};color:{txt};border:1px solid {bd};'
            'border-radius:7px;font-size:14px;font-weight:bold;}'
            f'QPushButton:hover{{border-color:{accent};}}'
            f'QPushButton:checked{{background:{accent};color:#FFFFFF;border:1px solid {accent};}}')

# 디자인 토큰 — v2.0 분해: spectra/ui/tokens.py 로 이동, re-import(동작 불변)
from spectra.ui.tokens import (FS_XS, FS_SM, FS_BODY, FS_LG, FS_VAL, FS_DISP, FS_METRIC, FS_METRIC_BIG, CF_AXIS, CF_MODE, CF_ANNO, CF_TF_TITLE, CF_CUR_TITLE, CF_CUR_VAL, CF_GRID, CF_BADGE, CF_TINY, RADIUS_CTRL, RADIUS_SM, PAD_CTRL, PAD_SM, FONT_FAMILY, FONT_NUM, FONT_SANS, _qfont)


# Lucide(MIT) 아이콘 — 24x24 viewBox inner SVG + filled 여부. 손그림 대비 일관·세련.
# Lucide 아이콘 데이터 — v2.0 분해: spectra/ui/icons.py 로 이동, re-import
from spectra.ui.icons import _LUCIDE_ICONS

def _svg_render(p, inner, color, size, filled=False):
    """Lucide inner SVG를 주어진 색으로 painter에 렌더 (size x size, 24 viewBox)."""
    from PyQt5.QtSvg import QSvgRenderer
    from PyQt5.QtCore import QByteArray
    attrs = (f'fill="{color}" stroke="none"' if filled else
             f'fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"')
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" {attrs}>{inner}</svg>'
    QSvgRenderer(QByteArray(svg.encode())).render(p, QRectF(0, 0, size, size))

# _icon — v2.0 분해: spectra/ui/icons.py, re-import
from spectra.ui.icons import _icon
# _draw_reload_arrow — v2.0 분해: spectra/ui/spl.py, re-import
from spectra.ui.spl import (_draw_reload_arrow)
def _txn_icon(playing, sz=14):
    """트랜스포트 버튼 아이콘 — 재생/시작=로고블루 play, 정지=빨강 stop."""
    return _icon('stop' if playing else 'play', sz, color=T('red') if playing else T('accent'))


# _txn_style, _apply_txn — v2.0 분해: spectra/ui/spl.py, re-import
from spectra.ui.spl import (_txn_style, _apply_txn)
from spectra.ui.widgets import (_DarkTitleBar, _add_resize_grip, _apply_dark_titlebar, _apply_native_titlebar_dark, _apply_app_dark_appearance, _apply_windows_titlebar_dark, _brand_logo_html, _BrandHeaderBar, _restyle_brand_header, _dialog_brand_header, _grad_topline, _make_brand_header, _CollapseBtn)
def _set_float_above_fullscreen(win):
    """macOS: 부모 없는 독립 창을 (1) 메인창이 풀스크린이어도 그 위에 뜨고
    (2) 모든 Space에 표시 + 메인창 최소화에도 살아남게 한다 (Smaart SPL 미터 방식).
    네이티브 NSWindow.collectionBehavior 에 FullScreenAuxiliary | CanJoinAllSpaces 추가.
    winId()가 유효해야 하므로 반드시 show() 이후 호출."""
    if sys.platform != 'darwin':
        return
    try:
        import ctypes
        objc = ctypes.cdll.LoadLibrary('/usr/lib/libobjc.A.dylib')
        objc.sel_registerName.restype = ctypes.c_void_p
        objc.sel_registerName.argtypes = [ctypes.c_char_p]
        def sel(name): return objc.sel_registerName(name.encode())
        def msg(restype, obj, sel_name, *args):
            f = objc.objc_msgSend
            f.restype = restype
            f.argtypes = [ctypes.c_void_p, ctypes.c_void_p] + [type(a) for a in args]
            return f(obj, sel(sel_name), *args)
        ns_view = ctypes.c_void_p(int(win.winId()))
        ns_window = msg(ctypes.c_void_p, ns_view, 'window')
        if not ns_window:
            return
        # NSWindowCollectionBehaviorCanJoinAllSpaces=1<<0, FullScreenAuxiliary=1<<8
        beh = msg(ctypes.c_ulong, ns_window, 'collectionBehavior')
        beh |= (1 << 0) | (1 << 8)
        msg(None, ns_window, 'setCollectionBehavior:', ctypes.c_ulong(beh))
    except Exception as e:
        try: _alog.debug(f'float-above-fullscreen 실패: {e}')
        except Exception: pass


def _set_fullscreen_auxiliary(win):
    """창을 '풀스크린 보조창'으로 지정 — 부모 풀스크린 위에 정상 크기로 뜨고 자기는 풀스크린 안 됨.
    ⚠️show 전에 호출해야 함(show 시점 macOS 자동 풀스크린화를 막아야 검은 풀스크린 방지).
    호출 전 win.winId()로 NSWindow 실체화 필요."""
    if sys.platform != 'darwin':
        return False
    try:
        import ctypes
        objc = ctypes.cdll.LoadLibrary('/usr/lib/libobjc.A.dylib')
        objc.sel_registerName.restype = ctypes.c_void_p
        objc.sel_registerName.argtypes = [ctypes.c_char_p]
        def sel(n): return objc.sel_registerName(n.encode())
        def msg(restype, obj, name, *args):
            f = objc.objc_msgSend; f.restype = restype
            f.argtypes = [ctypes.c_void_p, ctypes.c_void_p] + [type(a) for a in args]
            return f(obj, sel(name), *args)
        nsw = msg(ctypes.c_void_p, ctypes.c_void_p(int(win.winId())), 'window')
        if not nsw:
            return False
        beh = msg(ctypes.c_ulong, nsw, 'collectionBehavior')
        beh &= ~(1 << 7)   # FullScreenPrimary 제거
        beh |= (1 << 8)    # FullScreenAuxiliary 추가
        msg(None, nsw, 'setCollectionBehavior:', ctypes.c_ulong(beh))
        return True
    except Exception as e:
        try: _alog.debug(f'fullscreen-auxiliary 실패: {e}')
        except Exception: pass
        return False


def _attach_as_child(child, parent):
    """macOS 네이티브 addChildWindow — child NSWindow를 parent NSWindow의 진짜 자식으로.
    → 부모가 풀스크린이어도 같은 Space에 따라붙어 그 위에 뜸(Qt transient parent로는 안 됨).
    성공 시 True. NSWindowAbove=1."""
    if sys.platform != 'darwin':
        return False
    try:
        import ctypes
        objc = ctypes.cdll.LoadLibrary('/usr/lib/libobjc.A.dylib')
        objc.sel_registerName.restype = ctypes.c_void_p
        objc.sel_registerName.argtypes = [ctypes.c_char_p]
        def sel(n): return objc.sel_registerName(n.encode())
        def msg(restype, obj, name, *args):
            f = objc.objc_msgSend; f.restype = restype
            f.argtypes = [ctypes.c_void_p, ctypes.c_void_p] + [type(a) for a in args]
            return f(obj, sel(name), *args)
        def nswin(w):
            return msg(ctypes.c_void_p, ctypes.c_void_p(int(w.winId())), 'window')
        cw = nswin(child); pw = nswin(parent)
        if not cw or not pw:
            return False
        # ① 자식 창 collectionBehavior: FullScreenPrimary(자동 풀스크린) 제거 + FullScreenAuxiliary 추가
        #    → 부모 풀스크린 위에 '정상 크기'로 떠 있고, 자기가 풀스크린이 되지 않음(검은 풀스크린 방지)
        beh = msg(ctypes.c_ulong, cw, 'collectionBehavior')
        beh &= ~(1 << 7)          # NSWindowCollectionBehaviorFullScreenPrimary
        beh |= (1 << 8)           # NSWindowCollectionBehaviorFullScreenAuxiliary
        msg(None, cw, 'setCollectionBehavior:', ctypes.c_ulong(beh))
        # ② 부모의 진짜 자식으로 부착 → 같은 Space(풀스크린 포함) 추종
        msg(None, pw, 'addChildWindow:ordered:', ctypes.c_void_p(cw), ctypes.c_long(1))
        return True
    except Exception as e:
        try: _alog.debug(f'addChildWindow/aux 실패: {e}')
        except Exception: pass
        return False


def _detach_as_child(child, parent):
    """addChildWindow 해제 — child를 다시 독립 top-level NSWindow로(외부 모니터로 자유 이동 가능).
    부모가 풀스크린이 아닐 때 호출(풀스크린 위 부착은 같은 Space에 묶여 다른 화면으로 못 옮김)."""
    if sys.platform != 'darwin':
        return False
    try:
        import ctypes
        objc = ctypes.cdll.LoadLibrary('/usr/lib/libobjc.A.dylib')
        objc.sel_registerName.restype = ctypes.c_void_p
        objc.sel_registerName.argtypes = [ctypes.c_char_p]
        def sel(n): return objc.sel_registerName(n.encode())
        def msg(restype, obj, name, *args):
            f = objc.objc_msgSend; f.restype = restype
            f.argtypes = [ctypes.c_void_p, ctypes.c_void_p] + [type(a) for a in args]
            return f(obj, sel(name), *args)
        def nswin(w):
            return msg(ctypes.c_void_p, ctypes.c_void_p(int(w.winId())), 'window')
        cw = nswin(child); pw = nswin(parent)
        if not cw or not pw:
            return False
        msg(None, pw, 'removeChildWindow:', ctypes.c_void_p(cw))
        return True
    except Exception as e:
        try: _alog.debug(f'removeChildWindow 실패: {e}')
        except Exception: pass
        return False


# _apply_on_top — v2.0 분해: spectra/ui/spl.py, re-import
from spectra.ui.spl import (_apply_on_top)
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
from spectra.ui.spl import (_glance_chrome_update, _glance_set_chrome, _ReloadBtn)
from spectra.ui.colors import _SPECTRA_MARK_SVG, _SPECTRA_GRAD_DEFS, _SPECTRA_GRAD_QSS
# 시그니처 그라디언트 stops — QLinearGradient용 (스펙트럼 곡선 등 라이브 렌더; 브러시라 부담 0)
# 브랜드 그라디언트 상수 — v2.0 분해: spectra/ui/colors.py 로 이동, re-import
from spectra.ui.colors import _SPECTRA_GRAD_STOPS
# 브랜드 그라디언트/마크 빌더 — v2.0 분해: spectra/ui/colors.py 로 이동, re-import
from spectra.ui.colors import _spectra_grad_obj, _spectra_grad_pen, _spectra_grad_brush, _spectra_mark


def _make_splash_pixmap(w=520, h=300):
    """렌더형 브랜드 스플래시 QPixmap — splash.png 없어도 항상 SPECTRA 브랜드 모먼트.
    그라디언트 웨이브 마크 + 워드마크 + 시그니처 라인 + 버전. 정적 1회 렌더(부담 0)."""
    try:
        dpr = QApplication.primaryScreen().devicePixelRatio() if QApplication.instance() else 1.0
    except Exception:
        dpr = 1.0
    pm = QPixmap(int(w * dpr), int(h * dpr)); pm.setDevicePixelRatio(dpr)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing); p.setRenderHint(QPainter.TextAntialiasing)
    # 배경: 수직 다크 그라디언트 (위 살짝 밝게 → elevation)
    bg = QLinearGradient(0, 0, 0, h)
    bg.setColorAt(0.0, QColor('#16171C')); bg.setColorAt(1.0, QColor('#09090C'))
    p.fillRect(0, 0, w, h, QBrush(bg))
    p.setPen(QPen(QColor(255, 255, 255, 18), 1)); p.setBrush(Qt.NoBrush)
    p.drawRect(0, 0, w - 1, h - 1)
    # 그라디언트 웨이브 마크 (중앙 상단)
    mark = _spectra_mark(h=66)
    mw = mark.width() / mark.devicePixelRatio()
    p.drawPixmap(int((w - mw) / 2), 70, mark)
    # 워드마크 SPECTRA
    fw = QFont(FONT_FAMILY, 30); fw.setBold(True); fw.setLetterSpacing(QFont.AbsoluteSpacing, 11)
    p.setFont(fw); p.setPen(QColor('#F1F4F9'))
    p.drawText(0, 150, w, 48, Qt.AlignHCenter | Qt.AlignVCenter, 'SPECTRA')
    # 시그니처 그라디언트 라인
    lw = 168; lx = (w - lw) / 2.0; ly = 200
    p.setPen(Qt.NoPen); p.setBrush(_spectra_grad_brush(lx, lx + lw))
    p.drawRoundedRect(QRectF(lx, ly, lw, 3.0), 1.5, 1.5)
    # 서브타이틀
    fs = QFont(FONT_SANS, 9); fs.setLetterSpacing(QFont.AbsoluteSpacing, 4)
    p.setFont(fs); p.setPen(QColor('#828A98'))
    p.drawText(0, 214, w, 20, Qt.AlignHCenter, 'AUDIO MEASUREMENT')
    # 하단: 버전 · by WAYAUDIO
    fv = QFont(FONT_SANS, 9); p.setFont(fv); p.setPen(QColor('#5C6373'))
    p.drawText(0, h - 36, w, 18, Qt.AlignHCenter, f'v{_APP_VERSION}    ·    by WAYAUDIO')
    p.end()
    return pm


# 웨이브 토글 아이콘 — v2.0 분해: spectra/ui/icons.py 로 이동, re-import
from spectra.ui.icons import _wave_toggle_icon, _WAVE_TOGGLE_PATH


# ss_* 스타일시트 헬퍼 — v2.0 분해: spectra/ui/tokens.py 로 이동, re-import(동작 불변)
from spectra.ui.tokens import (ss_text, ss_pill_btn, ss_input, ss_spin,
                               ss_dialog_btns, ss_btn_primary, ss_btn_neutral, ss_btn_danger)

# hsep — v2.0 분해: spectra/ui/widgets.py, re-import
from spectra.ui.widgets import hsep
def _db_ctrl_btn_style(locked):
    """툴바 dB 범위 버튼 스타일 — 고정=로고블루 테두리·틴트 / 자동=중립 pill (Engine/FFT 컨트롤과 톤 맞춤)."""
    if locked:
        a = QColor(T('accent')); ar, ag, ab = a.red(), a.green(), a.blue()
        return (f'QPushButton{{background:rgba({ar},{ag},{ab},34);color:#9DB7E0;'
                f'border:1.4px solid {T("accent")};border-radius:{RADIUS_CTRL}px;'
                f'padding:2px 12px;font-size:12px;font-weight:600;}}'
                f'QPushButton:hover{{background:rgba({ar},{ag},{ab},60);}}')
    return (f'QPushButton{{background:{T("panel")};color:{T("text")};'
            f'border:1px solid {T("border")};border-radius:{RADIUS_CTRL}px;'
            f'padding:2px 12px;font-size:12px;}}'
            f'QPushButton:hover{{border-color:{T("accent")};}}')

# _ask_db_range — v2.0 분해: spectra/ui/canvas_tf.py, re-import
from spectra.ui.canvas_tf import _ask_db_range
# _db_axis_context_menu — v2.0 분해: spectra/ui/canvas_tf.py, re-import
from spectra.ui.canvas_tf import _db_axis_context_menu
def _draw_lock_badge(p, x, y, color, open_=False, op=1.0):
    """작은 자물쇠 아이콘 (dB축 고정 상태·클릭 타겟). (x,y)=좌상단, 약 12×13px. QPainter 직접.
    open_=True → 열린 자물쇠(해제 상태, 보통 흐리게 op<1). op=투명도."""
    from PyQt5.QtGui import QPen, QBrush
    from PyQt5.QtCore import QRectF
    p.save()
    p.setOpacity(op)
    p.setRenderHint(QPainter.Antialiasing, True)
    bw, bh = 11.0, 8.0
    bx, by = x + 0.5, y + 5.0
    r = bw * 0.34
    # 고리(shackle) — 잠김=중앙 닫힘 / 해제=왼쪽으로 열림
    pen = QPen(QColor(color), 1.6); pen.setCapStyle(Qt.RoundCap)
    p.setPen(pen); p.setBrush(Qt.NoBrush)
    if open_:
        p.drawArc(QRectF(x - 1.5, by - r*1.85, 2*r, 2*r*1.6), 55*16, 155*16)
    else:
        p.drawArc(QRectF(x + bw/2 - r + 0.5, by - r*1.7, 2*r, 2*r*1.6), 20*16, 140*16)
    # 몸통
    p.setPen(Qt.NoPen); p.setBrush(QBrush(QColor(color)))
    path = QPainterPath(); path.addRoundedRect(QRectF(bx, by, bw, bh), 2.0, 2.0)
    p.fillPath(path, QBrush(QColor(color)))
    p.restore()


def _sep_line_color():
    return '#4A4A4A' if is_dark() else T('border')


def _splitter_qss():
    """3탭 공통 스플리터 핸들 — 얇고 차분한 하이라인 구분선(테마 적응). 분석창 구분선 통일용."""
    sep = _sep_line_color()
    return (f'QSplitter::handle{{background:{T("bg")};}}'
            f'QSplitter::handle:vertical{{border-top:1px solid {sep};}}'
            f'QSplitter::handle:horizontal{{border-left:1px solid {sep};}}'
            f'QSplitter::handle:hover{{background:{T("bg3")};}}')


# ── TF 3분석 패널 카드(영역 분리) — 떠 있는 둥근 카드 + 거터 + 패널별 컬러 제목 ──
# TF 카드 정체성 색 — v2.0 분해: spectra/ui/canvas_tf.py 내부 상수

# TF 카드 페인팅 — v2.0 분해: spectra/ui/draw.py 로 이동, re-import
from spectra.ui.draw import _tf_card_palette, _tf_gutter, _paint_tf_card


from PyQt5.QtWidgets import QSplitterHandle

# 스플리터 — v2.0 분해: spectra/ui/widgets.py, re-import
from spectra.ui.widgets import _GradSplitterHandle, _CardSplitter
class _VScrollArea(QScrollArea):
    """세로 전용 스크롤 영역 — 내부 위젯 폭을 뷰포트 폭에 고정.
    setWidgetResizable+ScrollBarAlwaysOff만으론 콘텐츠 최소폭이 뷰포트보다 넓을 때
    트랙패드 가로 스와이프로 내용이 좌우로 밀리고(카드 이동) 오른쪽 테두리가 잘림.
    내부 위젯 maxWidth를 뷰포트 폭으로 캡 → 가로 오버플로우/스크롤 원천 차단
    (카드가 Reference처럼 패널 폭에 맞춰 자식이 축소됨)."""
    def resizeEvent(self, e):
        super().resizeEvent(e)
        w = self.widget()
        if w is not None:
            w.setMaximumWidth(self.viewport().width())


# ───────────────────────────────────────────
#  Bar gradient presets
# ───────────────────────────────────────────
# BAR_PRESETS/bar 색 — v2.0 분해: spectra/ui/colors.py, re-import
from spectra.ui.colors import (BAR_PRESETS, bar_top, bar_bot, _vbar_gradient,
                               bar_custom_color, set_bar_custom_color)

# ───────────────────────────────────────────
#  좌표 변환
# ───────────────────────────────────────────
# 드로잉/지오메트리 — v2.0 분해: spectra/ui/draw.py 로 이동, re-import(동작 불변)
from spectra.ui.draw import (freq_to_x, _fmt_freq_tick, draw_freq_minor_grid, db_to_y,
                             x_to_freq, y_to_db, draw_info_box, draw_dom_badge, FREQ_MARKS_MINOR)

# _focused_capture_visible — v2.0 분해: spectra/ui/draw.py, re-import
from spectra.ui.draw import _focused_capture_visible
from spectra.ui.widgets import _grad_topline
# _draw_idle_hint — v2.0 분해: spectra/ui/draw.py, re-import
from spectra.ui.draw import _draw_idle_hint
_capture_palette_cache = None
def _capture_palette(count=48):
    """캡쳐 색 팔레트 — 라이브 카드 색(_MC_COLORS)과도, 서로와도 최대한 멀리 떨어지게.
    최원점(farthest-point) 선택: 색공간(hue+채도+밝기) 후보 중 '이미 뽑힌 색 + 라이브 색'과
    RGB 거리가 가장 먼 색을 차례로 고른다. 라이브 색을 시드로 넣어 캡쳐가 라이브를 회피.
    채도/밝기 하한을 둬 다크·라이트 양 테마에서 모두 잘 보이게. 1회 계산 후 캐시(결정론적).
    color 그룹만으론 hue 공간이 부족해 22개+에서 비슷해지던 문제 해결."""
    global _capture_palette_cache
    if _capture_palette_cache is not None and len(_capture_palette_cache) >= count:
        return _capture_palette_cache
    # 후보 색공간 (hue×채도×밝기) 생성
    cand_rgb = []; cand_name = []
    H = 120
    for i in range(H):
        h = i / H
        for s in (0.65, 0.85, 1.0):
            for v in (0.82, 0.93, 1.0):
                c = QColor.fromHsvF(h, s, v)
                cand_rgb.append((c.red(), c.green(), c.blue())); cand_name.append(c.name())
    cand = np.asarray(cand_rgb, dtype=np.float64)
    live = np.asarray([[QColor(c).red(), QColor(c).green(), QColor(c).blue()]
                       for c in _MC_COLORS], dtype=np.float64)
    # 벡터화 farthest-point: 라이브 시드까지 최소거리²에서 시작 → 매 단계 argmax 선택 후 선택색 거리로 갱신
    min_d = ((cand[:, None, :] - live[None, :, :]) ** 2).sum(-1).min(axis=1)
    out = []
    for _ in range(count):
        i = int(np.argmax(min_d))
        out.append(cand_name[i])
        min_d = np.minimum(min_d, ((cand - cand[i]) ** 2).sum(-1))
    _capture_palette_cache = out
    return out

def _auto_capture_color(n):
    """캡쳐 색 — 라이브 카드·다른 캡쳐와 최대한 구분되는 팔레트의 n번째(초과 시 순환)."""
    pal = _capture_palette()
    return pal[n % len(pal)]

# _catmull_seg — v2.0 분해: spectra/ui/canvas_tf.py, re-import
from spectra.ui.canvas_tf import _catmull_seg
class _DeadCallbackError(Exception):
    """스트림은 열렸는데 AUHAL 콜백이 안 시작된 '죽은 스트림' — 같은 config로 재오픈해야 함
    (open 실패=다음 config와 구분). M4 출력+입력 경합 시 간헐 발생."""
    pass


# (오디오 엔진 클래스는 위에서 spectra.audio.engine 로 일괄 re-import됨)


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
                frames = min(frames, self.fft_size)   # 큰 호스트버퍼(bs=0 폴백)에서 frames>fft_size 시 ValueError 방지
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
                                            callback=cb, latency='high', dtype='float32',
                                            extra_settings=_win_extra_settings()) as _s:
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
# FFTCanvas — v2.0 분해: spectra/ui/canvas_spectrum.py, re-import
from spectra.ui.canvas_spectrum import FFTCanvas
# OctaveCanvas — v2.0 분해: spectra/ui/canvas_spectrum.py, re-import
from spectra.ui.canvas_spectrum import OctaveCanvas
# SpectrogramCanvas — v2.0 분해: spectra/ui/canvas_spectrum.py, re-import
from spectra.ui.canvas_spectrum import SpectrogramCanvas
from spectra.ui.draw import (METER_DB_MIN, METER_YELLOW_DB, METER_RED_DB, METER_ATTACK,
                             METER_RELEASE, METER_TAU_ATTACK, METER_TAU_RELEASE,
                             METER_PEAK_DECAY, _draw_zone_meter_h)


# ───────────────────────────────────────────
#  VU 미터
# ───────────────────────────────────────────
# VUMeter — v2.0 분해: spectra/ui/widgets.py, re-import
from spectra.ui.widgets import VUMeter
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
    cancel = QPushButton(_tx('Cancel')); ok_btn = QPushButton('OK')
    ok_btn.setDefault(True)
    cancel.setStyleSheet(ss_btn_neutral()); ok_btn.setStyleSheet(ss_btn_primary())
    cancel.clicked.connect(dlg.reject); ok_btn.clicked.connect(dlg.accept)
    btn_row.addStretch(); btn_row.addWidget(cancel); btn_row.addWidget(ok_btn)
    lay.addLayout(btn_row)
    le.returnPressed.connect(dlg.accept)
    # NOTE: 한글 첫 글자가 분리되는 현상은 PyQt5 5.15 + macOS 자체 버그(순수 Qt 다이얼로그에서도
    # 재현, 우리 코드 무관). 새 창의 첫 키가 IME 조합 세션을 못 띄움 — 입력칸을 한 번 클릭하면 정상.
    # 프로그램적 우회(포커스/Cocoa makeFirstResponder/inputContext activate/합성클릭) 모두 무효라 보류.
    ok = dlg.exec_() == QDialog.Accepted
    return le.text(), ok


# _brand_msg/_BrandBox — v2.0 분해: spectra/ui/dialogs.py, re-import
from spectra.ui.dialogs import _brand_msg, _BrandBox
def _md_to_html(md):
    """릴리즈 노트용 경량 마크다운→HTML (##/###, - 불릿, **굵게**, `코드`, > 인용, ---).
    외부 라이브러리 없이 우리 노트 형식만 처리."""
    import html as _h, re
    acc = T('accent'); dim = T('text_dim'); txt = T('text')
    def inline(s):
        s = _h.escape(s)
        s = re.sub(r'\[([^\]]+)\]\([^)]+\)', rf'<span style="color:{acc}">\1</span>', s)  # [text](url) → text
        s = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', s)
        s = re.sub(r'`(.+?)`', rf'<code style="color:{acc}">\1</code>', s)
        s = re.sub(r'\*(.+?)\*', r'<i>\1</i>', s)
        return s
    out = []; in_ul = False
    for ln in md.split('\n'):
        st = ln.strip()
        if st.startswith('- '):
            if not in_ul: out.append('<ul style="margin:4px 0 10px 0;">'); in_ul = True
            out.append(f'<li style="margin:3px 0;">{inline(st[2:])}</li>'); continue
        if in_ul: out.append('</ul>'); in_ul = False
        if   st.startswith('### '): out.append(f'<h3 style="color:{txt};margin:10px 0 4px;">{inline(st[4:])}</h3>')
        elif st.startswith('## '):  out.append(f'<h2 style="color:{acc};margin:16px 0 6px;">{inline(st[3:])}</h2>')
        elif st.startswith('# '):   out.append(f'<h1 style="color:{txt};margin:4px 0 10px;">{inline(st[2:])}</h1>')
        elif st.startswith('> '):   out.append(f'<p style="color:{dim};margin:2px 0;">{inline(st[2:])}</p>')
        elif st == '---':           out.append(f'<hr style="border:none;border-top:1px solid {T("border")};margin:12px 0;"/>')
        elif st == '':              out.append('')
        else:                       out.append(f'<p style="color:{txt};margin:3px 0;">{inline(st)}</p>')
    if in_ul: out.append('</ul>')
    return f'<div style="font-family:{FONT_FAMILY};">' + ''.join(out) + '</div>'


# CalibDialog — v2.0 분해: spectra/ui/dialogs.py, re-import
from spectra.ui.dialogs import CalibDialog
# ───────────────────────────────────────────
#  LEQ 팝업 창
# ───────────────────────────────────────────
# LeqWindow, _clock_colors, _spl_card_bg, _SplPanel, _SplMetricEngine, _SplAlarmDisplay, SplAlarmWindow, ShowModeWindow, SplMeterWindow — v2.0 분해: spectra/ui/spl.py, re-import
from spectra.ui.spl import (
    LeqWindow, _clock_colors, _spl_card_bg, _SplPanel, _SplMetricEngine, _SplAlarmDisplay, SplAlarmWindow, ShowModeWindow, SplMeterWindow)
from spectra.ui.dialogs import SplLayoutDialog
# ───────────────────────────────────────────
#  Custom floating dropdown popup
# ───────────────────────────────────────────
def _global_popup_qss():
    """앱 전역(모든 top-level 창) 스타일. ① 브랜드 폰트를 전 위젯에 강제 —
    QSS에 font-size만 있고 font-family가 없는 위젯은 Qt가 기본 sans(Helvetica)로 리셋하는데,
    `*{font-family}`로 브랜드 폰트를 깔아 라벨 전체를 통일한다(측정 숫자는 QPainter로 FONT_NUM을
    직접 setFont하므로 QSS 영향 없음 → 그대로 유지). ② QMenu·QToolTip 다크 스타일 통일."""
    a = QColor(T('accent')); ar, ag, ab = a.red(), a.green(), a.blue()
    bg2, txt, dim, bd = T('bg2'), T('text'), T('text_dim'), T('border')
    return (
        f'*{{font-family:"{FONT_FAMILY}";}}'
        f'QMenu{{background:{bg2};color:{txt};border:1px solid {bd};border-radius:8px;padding:4px;}}'
        f'QMenu::item{{background:transparent;color:{txt};padding:5px 20px 5px 14px;border-radius:5px;}}'
        f'QMenu::item:selected{{background:rgba({ar},{ag},{ab},55);color:{txt};}}'
        f'QMenu::item:disabled{{color:{dim};}}'
        f'QMenu::separator{{height:1px;background:{bd};margin:4px 8px;}}'
        f'QMenu::icon{{padding-left:6px;}}'
        f'QToolTip{{background:{bg2};color:{txt};border:1px solid rgba({ar},{ag},{ab},120);'
        f'border-radius:5px;padding:4px 8px;font-size:11px;}}'
    )


# DropdownPopup — v2.0 분해: spectra/ui/widgets.py, re-import
from spectra.ui.widgets import DropdownPopup
# _ChannelGridPopup — v2.0 분해: spectra/ui/widgets.py, re-import
from spectra.ui.widgets import _ChannelGridPopup
# ───────────────────────────────────────────
#  Device Card Popup — 오디오 입력 장치 선택 패널
# ───────────────────────────────────────────
# DeviceCardPopup — v2.0 분해: spectra/ui/widgets.py, re-import
from spectra.ui.widgets import DeviceCardPopup
# _DrawerToggleBtn — v2.0 분해: spectra/ui/widgets.py, re-import
from spectra.ui.widgets import _DrawerToggleBtn
# _RightPanelToggleBtn — v2.0 분해: spectra/ui/widgets.py, re-import
from spectra.ui.widgets import _RightPanelToggleBtn
# _ToolbarToggleBtn — v2.0 분해: spectra/ui/widgets.py, re-import
from spectra.ui.widgets import _ToolbarToggleBtn
# _MiniMeterBar — v2.0 분해: spectra/ui/widgets.py, re-import
from spectra.ui.widgets import _MiniMeterBar
# ChannelPopup — v2.0 분해: spectra/ui/widgets.py, re-import
from spectra.ui.widgets import ChannelPopup
# ChannelCard — v2.0 분해: spectra/ui/widgets.py, re-import
from spectra.ui.widgets import ChannelCard
class _DblClickLabel(QLabel):
    """더블클릭 시 doubleClicked 시그널을 내는 라벨 (카드 이름 인라인 편집용)."""
    doubleClicked = pyqtSignal()
    def mouseDoubleClickEvent(self, e):
        self.doubleClicked.emit()
        super().mouseDoubleClickEvent(e)


# begin_inline_rename — v2.0 분해: spectra/ui/widgets.py, re-import
from spectra.ui.widgets import begin_inline_rename
# _SpecCard — v2.0 분해: spectra/ui/widgets.py, re-import
from spectra.ui.widgets import _SpecCard
# _SidebarIcon — v2.0 분해: spectra/ui/widgets.py, re-import
from spectra.ui.widgets import _SidebarIcon
# _SplMeterBtn — v2.0 분해: spectra/ui/widgets.py, re-import
from spectra.ui.widgets import _SplMeterBtn
# _SplAlarmBtn — v2.0 분해: spectra/ui/widgets.py, re-import
from spectra.ui.widgets import _SplAlarmBtn
# _ComplianceBadge — v2.0 분해: spectra/ui/widgets.py 로 이동, re-import
from spectra.ui.widgets import _ComplianceBadge
# _CheckBtn — v2.0 분해: spectra/ui/widgets.py, re-import
from spectra.ui.widgets import _CheckBtn
# _SegBtn — v2.0 분해: spectra/ui/widgets.py, re-import
from spectra.ui.widgets import _SegBtn
# _SegmentedControl — v2.0 분해: spectra/ui/widgets.py, re-import
from spectra.ui.widgets import _SegmentedControl
# _CaptureBar — v2.0 분해: spectra/ui/widgets.py, re-import
from spectra.ui.widgets import _CaptureBar
def _cap_dot_pm(color, filled, size=11):
    """캡쳐 표시 점 — 항상 채운 안티앨리어싱 원. 표시=진한 색 / 숨김=같은 원을 흐리게
    (빈 원/링 폐지 — 파란 캡처에서 링이 도드라져 오해를 부름, 이름 딤과 톤 일치).
    CSS border-radius의 레티나 계단현상 회피용 페인트 픽스맵."""
    dpr = 3
    pm = QPixmap(int(size * dpr), int(size * dpr)); pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)
    p = QPainter(pm); p.setRenderHint(QPainter.Antialiasing, True)
    c = QColor(color)
    if not filled:
        c.setAlphaF(0.35)   # 숨김 = 채운 원 흐리게 (이름 40% 딤과 통일)
    p.setPen(Qt.NoPen); p.setBrush(c)
    p.drawEllipse(QRectF(0.6, 0.6, size - 1.2, size - 1.2))
    p.end()
    return pm


# 파워 LED 아이콘 — v2.0 분해: spectra/ui/icons.py 로 이동, re-import
from spectra.ui.icons import _led_power_pm
class _DragGrip(QLabel):
    """캡처 행 드래그 핸들. 전역 이벤트 필터 없이 마우스 이벤트를 직접 처리."""
    def __init__(self, drawer, mode, cap_idx):
        super().__init__('⠿')
        self._d = drawer; self._m = mode; self._i = cap_idx
        self._active = False
        self.setFixedWidth(10)
        self.setCursor(Qt.SizeVerCursor)
        self.setStyleSheet(f'color:{T("text_dim")};font-size:10px;')

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
    import_requested   = pyqtSignal(str)            # (mode) — 캡쳐 불러오기(CSV)
    move_to_group_req  = pyqtSignal(str, int, str)  # (mode, idx, group_name) — 그룹 이동 ('' = 그룹 해제)
    visibility_all_changed   = pyqtSignal(str, bool)       # (mode, visible) — 현재 탭 전체 일괄 표시/숨김
    group_visibility_changed = pyqtSignal(str, str, bool)  # (mode, group_name, visible) — 그룹 일괄
    capture_target_changed   = pyqtSignal(str, str)        # (mode, group_name) — 새 캡쳐가 들어갈 타겟 ('' = 미지정)
    delete_all_requested     = pyqtSignal(str)             # (mode) — 우클릭 전체삭제(Delete All)
    recapture_requested      = pyqtSignal(str, int)        # (mode, idx) — 제자리 다시 캡쳐(Recapture)

    PANEL_W = 220

    def __init__(self, parent=None):
        super().__init__(parent)
        self._collapsed  = {}
        self._cur_mode   = 'spec'
        self._panel_tab  = 'spec'
        self._spec_caps  = []
        self._tf_caps    = []
        self._target     = {'spec': '', 'tf': ''}   # 새 캡쳐가 들어갈 활성 타겟 그룹 ('' = 미지정)
        self._sel        = {'spec': None, 'tf': None}  # 패널에서 클릭(선택)한 캡쳐 idx (None=마지막 자동)
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
        hl = QHBoxLayout(hdr); hl.setContentsMargins(4, 4, 3, 4); hl.setSpacing(1)
        # 전체 표시/숨김 토글 — SPECTRA 그라디언트 웨이브 아이콘 (제목 왼쪽)
        self._vis_all_btn = QPushButton()
        self._vis_all_btn.setFixedSize(22, 20)
        self._vis_all_btn.setCursor(Qt.PointingHandCursor)
        self._vis_all_btn.setToolTip(_tx('Show all / Hide all (current tab)'))
        self._vis_all_btn.setIcon(_wave_toggle_icon(True, 16))
        self._vis_all_btn.setIconSize(QSize(16, 16))
        self._vis_all_btn.setStyleSheet(
            'QPushButton{border:1px solid #38383A;border-radius:5px;background:#1C1C1E;padding:0;}'
            'QPushButton:hover{border-color:#4E7DF0;}'
            'QPushButton:disabled{border-color:#2A2A2C;background:#161618;}')
        self._vis_all_btn.clicked.connect(self._on_vis_all_clicked)
        hl.addWidget(self._vis_all_btn)
        self._hdr_lbl = QLabel('CAPTURES',
            styleSheet=f'color:{T("accent")};font-size:11px;font-weight:bold;')
        self._hdr_lbl.setMinimumWidth(64)   # 버튼이 다 떠도 제목 안 잘리게 최소폭 보장
        hl.addWidget(self._hdr_lbl)
        hl.addStretch()
        self._avg_btn = QPushButton('Avg')
        self._avg_btn.setFixedSize(32, 20)
        self._avg_btn.setToolTip(_tx('Average checked TF captures'))
        self._avg_btn.setStyleSheet(
            'font-size:9px;font-weight:600;border:1px solid #38383A;border-radius:5px;'
            'background:#1C1C1E;color:#4E7DF0;padding:0 2px;')
        self._avg_btn.clicked.connect(lambda: self.average_requested.emit(self._panel_tab))
        self._avg_btn.setVisible(False)
        hl.addWidget(self._avg_btn)
        self._export_btn = QPushButton(''); self._export_btn.setIcon(_icon('download',13))
        self._export_btn.setFixedSize(20, 20)
        self._export_btn.setToolTip(_tx('Export TF captures (CSV + PNG)'))
        self._export_btn.setStyleSheet(
            'font-size:12px;font-weight:600;border:1px solid #38383A;border-radius:5px;'
            'background:#1C1C1E;color:#4E7DF0;padding:0;')
        self._export_btn.clicked.connect(lambda: self.export_requested.emit(self._panel_tab))
        self._export_btn.setVisible(False)
        hl.addWidget(self._export_btn)
        self._import_btn = QPushButton(''); self._import_btn.setIcon(_icon('upload',13))
        self._import_btn.setFixedSize(20, 20)
        self._import_btn.setToolTip(_tx('Import TF captures (CSV)'))
        self._import_btn.setStyleSheet(
            'font-size:12px;font-weight:600;border:1px solid #38383A;border-radius:5px;'
            'background:#1C1C1E;color:#4E7DF0;padding:0;')
        self._import_btn.clicked.connect(lambda: self.import_requested.emit(self._panel_tab))
        self._import_btn.setVisible(False)
        hl.addWidget(self._import_btn)
        self._grp_btn = grp_btn = QPushButton('+ Grp')
        grp_btn.setFixedSize(40, 20)
        grp_btn.setToolTip(_tx('New Group'))
        grp_btn.setStyleSheet(
            'QPushButton{font-size:9px;font-weight:600;border:none;border-radius:6px;'
            'background:transparent;color:#C8C8CE;padding:0 5px;}'
            'QPushButton:hover{background:#2A2A30;color:#FFFFFF;}')
        grp_btn.clicked.connect(lambda: self.new_group_req.emit(self._panel_tab))
        hl.addWidget(grp_btn)
        pv.addWidget(hdr)

        # SPEC / TF 탭 바 — Apple segmented control style
        tab_bar = QWidget(); tab_bar.setFixedHeight(40)
        tab_bar.setObjectName('segCtrlWrap')
        tbl_outer = QHBoxLayout(tab_bar)
        tbl_outer.setContentsMargins(8, 5, 8, 5); tbl_outer.setSpacing(0)

        self._seg_pill = QWidget(); self._seg_pill.setObjectName('segPill')
        self._seg_pill.setStyleSheet('#segPill{background:transparent;}')   # 언더라인 탭 — 트랙 없음
        tbl = QHBoxLayout(self._seg_pill)
        tbl.setContentsMargins(2, 2, 2, 2); tbl.setSpacing(2)

        self._spec_tab_btn = QPushButton('Spectrum')
        self._tf_tab_btn   = QPushButton('Transfer Fn')
        _tab_ss = (
            'QPushButton{font-size:12px;font-weight:600;border:none;'
            'background:transparent;color:#8E8E93;padding:2px 6px 2px 6px;}'
            'QPushButton:checked{color:#FFFFFF;}'
            'QPushButton:hover:!checked{color:#B0B0B8;}')
        # 글자 폭만큼의 일자 밑줄(2px) — border-bottom의 곡선 렌더 회피
        _uw_font = QFont(FONT_FAMILY); _uw_font.setPixelSize(12); _uw_font.setWeight(QFont.DemiBold)
        _uw_fm = QFontMetrics(_uw_font)
        self._dtab_uls = {}
        for btn, mode, txt in [(self._spec_tab_btn, 'spec', 'Spectrum'),
                               (self._tf_tab_btn, 'tf', 'Transfer Fn')]:
            btn.setFixedHeight(24); btn.setCheckable(True)
            btn.setStyleSheet(_tab_ss)
            btn.clicked.connect(lambda _, m=mode: self._switch_panel_tab(m))
            cell = QWidget()
            cv = QVBoxLayout(cell); cv.setContentsMargins(0, 0, 0, 0); cv.setSpacing(3)
            cv.addWidget(btn)
            ur = QHBoxLayout(); ur.setContentsMargins(0, 0, 0, 0); ur.setSpacing(0)
            ul = QFrame(); ul.setFixedSize(max(28, _uw_fm.horizontalAdvance(txt) + 8), 2)
            ul.setStyleSheet('background:#4E7DF0;border:none;border-radius:1px;')
            ur.addStretch(); ur.addWidget(ul); ur.addStretch()
            cv.addLayout(ur)
            self._dtab_uls[mode] = ul
            tbl.addWidget(cell, 1)

        tbl_outer.addWidget(self._seg_pill, 1)
        self._spec_tab_btn.setChecked(True)
        self._dtab_uls['tf'].setVisible(False)
        self._seg_tab_bar = tab_bar
        pv.addWidget(tab_bar)

        # 캡쳐 타겟 칩 — 새 캡쳐가 들어갈 위치 표시 + 클릭 시 미지정으로 복귀
        self._target_chip = QPushButton()
        self._target_chip.setFixedHeight(22)
        self._target_chip.setCursor(Qt.PointingHandCursor)
        self._target_chip.setToolTip(_tx('Target group for new captures — click to clear'))
        self._target_chip.clicked.connect(
            lambda: self.capture_target_changed.emit(self._panel_tab, ''))
        _chip_wrap = QWidget()
        _cw = QHBoxLayout(_chip_wrap); _cw.setContentsMargins(8, 0, 8, 4); _cw.setSpacing(0)
        _cw.addWidget(self._target_chip)
        pv.addWidget(_chip_wrap)

        # 스크롤 영역
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFocusPolicy(Qt.NoFocus)   # macOS 파란 포커스 링(둥근 "(") 제거
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setObjectName('capScroll')
        self._scroll.setStyleSheet(
            f'#capScroll {{ background:{T("bg2")}; border:1px solid #2E2E34; border-radius:10px; }}'
            f'QScrollBar:vertical{{width:5px;background:transparent;}}'
            f'QScrollBar::handle:vertical{{background:{T("border")};border-radius:2px;}}')
        self._scroll.viewport().setStyleSheet('background:transparent;border-radius:10px;')

        self._inner = QWidget()
        self._inner.setObjectName('capInner')
        self._inner.setFocusPolicy(Qt.NoFocus)   # macOS 파란 포커스 링 제거
        self._inner.setMouseTracking(True)
        self._inner.setStyleSheet('#capInner { background:transparent; }')
        # 빈 공간 우클릭 → 전체삭제 메뉴
        self._inner.setContextMenuPolicy(Qt.CustomContextMenu)
        self._inner.customContextMenuRequested.connect(
            lambda pos: self._show_panel_menu(self._inner.mapToGlobal(pos)))
        self._ilay = QVBoxLayout(self._inner)
        self._ilay.setContentsMargins(0, 0, 0, 0); self._ilay.setSpacing(0)
        self._ilay.addStretch()
        self._scroll.setWidget(self._inner)
        # 리스트를 패널 안쪽으로 인셋 → 패널 외곽 둥근모서리 + 리스트 카드 4모서리 둥근 둘 다 보이게
        _scroll_wrap = QWidget(); _sw = QVBoxLayout(_scroll_wrap)
        _sw.setContentsMargins(8, 2, 8, 8); _sw.setSpacing(0)
        _sw.addWidget(self._scroll)
        pv.addWidget(_scroll_wrap, 1)

        outer.addWidget(self._panel, 1)
        self._restyle_chrome()   # 헤더 버튼 테마색 적용(다크/라이트)

    def _restyle_chrome(self):
        """헤더 버튼(전체토글·Avg·Export·+Grp) 테마색 적용 — 라이트에서 검정 배경 방지.
        스크롤/이너/탭/패널은 MainWindow._apply_theme가 담당. 토글 시 거기서 이 메서드도 호출."""
        acc = T('accent'); bd = T('border')
        if hasattr(self, '_hdr_lbl'):
            self._hdr_lbl.setStyleSheet(f'color:{acc};font-size:11px;font-weight:bold;')
        if is_dark():
            btn_bg, grp_bg, grp_fg, dis_bg = '#1C1C1E', '#2C2C2E', '#8E8E93', '#161618'
        else:
            btn_bg, grp_bg, grp_fg, dis_bg = T('panel'), T('bg3'), T('text_dim'), T('bg2')
        self._vis_all_btn.setStyleSheet(
            f'QPushButton{{border:1px solid {bd};border-radius:5px;background:{btn_bg};padding:0;}}'
            f'QPushButton:hover{{border-color:{acc};}}'
            f'QPushButton:disabled{{border-color:{bd};background:{dis_bg};}}')
        self._avg_btn.setStyleSheet(
            f'font-size:9px;font-weight:600;border:1px solid {bd};border-radius:5px;'
            f'background:{btn_bg};color:{acc};padding:0 2px;')
        self._export_btn.setStyleSheet(
            f'font-size:12px;font-weight:600;border:1px solid {bd};border-radius:5px;'
            f'background:{btn_bg};color:{acc};padding:0;')
        self._import_btn.setStyleSheet(
            f'font-size:12px;font-weight:600;border:1px solid {bd};border-radius:5px;'
            f'background:{btn_bg};color:{acc};padding:0;')
        if is_dark():
            self._grp_btn.setStyleSheet(
                'QPushButton{font-size:9px;font-weight:600;border:none;border-radius:6px;'
                'background:transparent;color:#C8C8CE;padding:0 5px;}'
                'QPushButton:hover{background:#2A2A30;color:#FFFFFF;}')
        else:
            self._grp_btn.setStyleSheet(
                f'QPushButton{{font-size:9px;font-weight:600;border:none;border-radius:6px;'
                f'background:transparent;color:{T("text_dim")};padding:0 5px;}}'
                f'QPushButton:hover{{background:{T("bg3")};color:{T("text")};}}')

    # ── 공개 메서드 ─────────────────────────────────
    def _switch_panel_tab(self, mode):
        self._panel_tab = mode
        self._spec_tab_btn.setChecked(mode == 'spec')
        self._tf_tab_btn.setChecked(mode == 'tf')
        if hasattr(self, '_dtab_uls'):
            self._dtab_uls['spec'].setVisible(mode == 'spec')
            self._dtab_uls['tf'].setVisible(mode == 'tf')
        self._avg_btn.setVisible(mode == 'tf')
        self._export_btn.setVisible(mode == 'tf')
        self._import_btn.setVisible(mode == 'tf')
        self._redraw()

    def set_active_mode(self, mode):
        self._cur_mode = mode
        self._switch_panel_tab(mode)

    # ── 일괄 표시/숨김 (전체 / 그룹) ─────────────────
    def _cur_caps(self):
        return self._tf_caps if self._panel_tab == 'tf' else self._spec_caps

    def _on_vis_all_clicked(self):
        """스마트 토글 — 하나라도 보이면 전부 끄고, 다 꺼져 있으면 전부 켠다."""
        caps = self._cur_caps()
        if not caps:
            return
        any_vis = any(c.get('visible', True) for c in caps)
        self.visibility_all_changed.emit(self._panel_tab, not any_vis)

    def _update_vis_all_btn(self):
        """전체 토글 버튼 아이콘을 현재 탭의 가시성 상태로 갱신 (캡쳐 없으면 비활성)."""
        btn = getattr(self, '_vis_all_btn', None)
        if btn is None:
            return
        caps = self._cur_caps()
        any_vis = bool(caps) and any(c.get('visible', True) for c in caps)
        btn.setIcon(_wave_toggle_icon(any_vis, 16))
        btn.setEnabled(bool(caps))

    def set_capture_target(self, mode, name):
        """새 캡쳐가 들어갈 타겟 그룹 설정 ('' = 미지정). MainWindow의 _current_*_group과 동기화."""
        self._target[mode] = name or ''

    def _get_pending_group(self, mode):
        # 활성 타겟 그룹(빈 그룹이어도 헤더 표시 + 이동메뉴 노출용)
        return self._target.get(mode, '') or None

    def _update_target_chip(self):
        """타겟 칩 텍스트/스타일을 현재 탭의 활성 타겟으로 갱신."""
        chip = getattr(self, '_target_chip', None)
        if chip is None:
            return
        tgt = self._target.get(self._panel_tab, '')
        if tgt:
            chip.setText(f'  ▸  Capture Target   {tgt}     ✕')
            chip.setEnabled(True)
            _tint = ('rgba(78,125,240,28)' if is_dark() else T("bg3"))
            _tint_h = ('rgba(78,125,240,52)' if is_dark() else T("bg2"))
            chip.setStyleSheet(
                f'QPushButton{{text-align:left;font-size:11px;font-weight:600;'
                f'color:{T("accent")};background:{_tint};'
                f'border:1px solid rgba(78,125,240,120);border-radius:6px;padding:0 8px;}}'
                f'QPushButton:hover{{background:{_tint_h};border-color:{T("accent")};}}')
        else:
            chip.setText('  ▸  Capture Target   None')
            chip.setEnabled(False)   # 이미 미지정 → 클릭 불필요(상태 표시)
            chip.setStyleSheet(
                f'QPushButton{{text-align:left;font-size:11px;'
                f'color:{T("text_dim")};background:transparent;'
                f'border:1px solid {T("border")};border-radius:6px;padding:0 8px;}}')

    def toggle(self):
        self.setVisible(not self.isVisible())

    def refresh(self, spec_caps, tf_caps):
        # 캡쳐 수가 바뀌면(추가/삭제) 선택 초기화 → 기본(마지막=새 캡쳐) 강조
        if len(spec_caps) != len(self._spec_caps): self._sel['spec'] = None
        if len(tf_caps)   != len(self._tf_caps):   self._sel['tf']   = None
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
        self._update_vis_all_btn()   # 전체 토글 아이콘을 현재 탭 상태로 동기화
        self._update_target_chip()   # 캡쳐 타겟 칩 동기화
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
        _fi = self._sel.get(mode)   # 클릭 선택 우선, 없으면 마지막
        front_idx = _fi if (_fi is not None and 0 <= _fi < len(caps)) else (len(caps) - 1 if caps else -1)
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
            cnt_str    = 'empty' if is_pending else str(len(items))

            is_target = (self._target.get(mode, '') == gname)   # 새 캡쳐가 들어갈 활성 타겟?
            ghdr = QWidget(); ghdr.setFixedHeight(28)
            ghl  = QHBoxLayout(ghdr)
            ghl.setContentsMargins(2, 0, 2, 0); ghl.setSpacing(0)
            # 접기/펼치기 화살표 (타겟 지정과 분리)
            arrow_btn = QPushButton('▶' if collapsed else '▼')
            arrow_btn.setFlat(True); arrow_btn.setFixedSize(20, 26)
            arrow_btn.setCursor(Qt.PointingHandCursor)
            arrow_btn.setToolTip(_tx('Collapse / Expand'))
            arrow_btn.setStyleSheet(
                f'QPushButton{{color:{T("text_dim")};font-size:11px;border:none;'
                f'background:{grp_bg_color};border-radius:4px;}}'
                f'QPushButton:hover{{background:{grp_hover};}}')
            arrow_btn.clicked.connect(lambda _, m=mode, g=gname: self._toggle_group(m, g))
            ghl.addWidget(arrow_btn)
            # 그룹명 = 캡쳐 타겟 토글 (클릭: 이 그룹으로 / 활성이면 미지정으로). 활성 시 하이라이트
            name_btn = QPushButton(f' {"◉ " if is_target else ""}{gname}  ({cnt_str})')
            name_btn.setFlat(True); name_btn.setCursor(Qt.PointingHandCursor)
            name_btn.setToolTip(_tx('Click → add new captures to this group (click again to deselect)'))
            _ac = QColor(T('accent'))
            _nm_col = T('accent') if is_target else T('text_dim')
            _nm_bg  = (f'rgba({_ac.red()},{_ac.green()},{_ac.blue()},30)' if is_target else grp_bg_color)
            name_btn.setStyleSheet(
                f'QPushButton{{text-align:left;color:{_nm_col};font-size:14px;font-weight:bold;'
                f'background:{_nm_bg};border:none;border-radius:4px;padding:0 4px;}}'
                f'QPushButton:hover{{background:{grp_hover};}}')
            name_btn.clicked.connect(
                lambda _, m=mode, g=gname:
                    self.capture_target_changed.emit(m, '' if self._target.get(m, '') == g else g))
            ghl.addWidget(name_btn, 1)
            # 그룹 일괄 표시/숨김 토글 (비어있지 않은 그룹만) — × 삭제 왼쪽
            if not is_pending:
                _g_any_vis = any(c.get('visible', True) for _, c in items)
                gvis = QPushButton()
                gvis.setFixedSize(22, 22)
                gvis.setCursor(Qt.PointingHandCursor)
                gvis.setToolTip(_tx('Show / Hide group "{gname}"').format(gname=gname))
                gvis.setIcon(_wave_toggle_icon(_g_any_vis, 14))
                gvis.setIconSize(QSize(14, 14))
                gvis.setStyleSheet(
                    'QPushButton{border:none;background:transparent;padding:0;border-radius:4px;}'
                    f'QPushButton:hover{{background:{grp_hover};}}')
                gvis.clicked.connect(
                    lambda _, m=mode, g=gname, it=items:
                        self.group_visibility_changed.emit(
                            m, g, not any(c.get('visible', True) for _, c in it)))
                ghl.addWidget(gvis)
            gdel = QPushButton('✕')
            gdel.setFixedSize(22, 22)
            gdel.setToolTip(_tx('Delete group "{gname}"').format(gname=gname))
            gdel.setStyleSheet(
                f'QPushButton{{border:none;color:{T("text_dim")};font-size:14px;background:transparent;padding:0;}}'
                f'QPushButton:hover{{color:{T("red")};}}')
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
                ph = QLabel('  Next capture goes here')
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
        rl.setContentsMargins(indent + 4, 5, 6, 5); rl.setSpacing(3)

        grip = _DragGrip(self, mode, idx)

        _vis = cap.get('visible', True)
        _cc = QColor(cap["color"]); _c_rgb = f'{_cc.red()},{_cc.green()},{_cc.blue()}'
        # 이름 글씨색 — 선택행=흰색, 표시=곡선색 85%, 숨김=곡선색 40% (C안: 배경 위 글씨)
        def _lbl_col(vis):
            if is_front: return T('text')
            return f'rgba({_c_rgb},{217 if vis else 102})'
        _lbl_wt = 'bold' if is_front else 'normal'

        # 색 점 = 표시/숨김 토글 (채움=표시, 빈 원=숨김) — 박스형 체크박스 폐지.
        # 점은 안티앨리어싱 페인트 원(외곽 매끈, 완전 칠해짐).
        chk = QPushButton()
        chk.setCheckable(True); chk.setChecked(_vis)
        chk.setFixedSize(16, 16)
        chk.setFocusPolicy(Qt.NoFocus)   # macOS 파란 포커스 링 제거
        chk.setCursor(Qt.PointingHandCursor)
        chk.setToolTip(_tx('Show / hide this capture'))
        chk.setIconSize(QSize(12, 12))
        chk.setStyleSheet('QPushButton{border:none;background:transparent;padding:0;}')
        chk.setIcon(QIcon(_cap_dot_pm(cap["color"], _vis, 12)))

        lbl = QLabel(cap['label'])
        lbl.setStyleSheet(f'color:{_lbl_col(_vis)};font-size:12px;font-weight:{_lbl_wt};background:transparent;')
        def _on_vis(c, b=chk, m=mode, i=idx, _l=lbl, _col=cap["color"]):
            b.setIcon(QIcon(_cap_dot_pm(_col, c, 12)))
            _l.setStyleSheet(f'color:{_lbl_col(c)};font-size:12px;font-weight:{_lbl_wt};background:transparent;')
            self.visibility_changed.emit(m, i, c)
        chk.toggled.connect(_on_vis)
        lbl.setCursor(Qt.PointingHandCursor)
        lbl.setToolTip(_tx('Click → bring to front  |  Double-click → rename'))
        def on_press(ev, m=mode, i=idx):
            if ev.button() == Qt.LeftButton:
                self._sel[m] = i   # 패널에서 클릭한 캡쳐를 활성으로 표시
                self.capture_selected.emit(m, i)
        lbl.mousePressEvent = on_press
        def on_dbl(ev, m=mode, i=idx):
            cur  = self._get_cap_label(m, i)
            name, ok = _text_input_dialog(self.window(), _tx('Rename'), _tx('New name:'), cur)
            if ok and name.strip():
                self.rename_requested.emit(m, i, name.strip())
        lbl.mouseDoubleClickEvent = on_dbl

        rl.setSpacing(8)
        rl.addWidget(grip)
        rl.addWidget(chk)
        rl.addSpacing(2)
        rl.addWidget(lbl, 1)

        # TF 전용: Δ 비교 기준(Reference) 토글
        if mode == 'tf':
            ref_btn = QPushButton('R')
            ref_btn.setCheckable(True)
            ref_btn.setChecked(bool(cap.get('is_ref', False)))
            ref_btn.setFixedSize(18, 18)
            ref_btn.setFocusPolicy(Qt.NoFocus)   # macOS 파란 포커스 링 제거
            ref_btn.setToolTip(_tx('Set as Δ reference (one at a time)'))
            _rb_bg, _rb_bd = (('#1C1C1E', '#48484A') if is_dark() else (T('panel'), '#C4CCD8'))
            ref_btn.setStyleSheet(
                f'QPushButton{{font-size:10px;font-weight:bold;border:1px solid {_rb_bd};'
                f'border-radius:4px;background:{_rb_bg};color:{T("text_dim")};padding:0;}}'
                f'QPushButton:checked{{border:1px solid #FF9F0A;background:#3A2A10;color:#FF9F0A;}}')
            def _on_ref(c, m=mode, i=idx):
                self.reference_changed.emit(m, i if c else -1)
            ref_btn.toggled.connect(_on_ref)
            rl.addWidget(ref_btn)
        badge_txt = cap.get('mode', '')
        if badge_txt and badge_txt not in ('FFT', ''):
            badge = QLabel(badge_txt)
            badge.setFont(_n2_mono_font(9))
            badge.setStyleSheet(f'color:{T("text_dim")};background:transparent;')
            rl.addWidget(badge)

        del_btn = QPushButton('×')
        del_btn.setFixedSize(16, 16)
        del_btn.setFocusPolicy(Qt.NoFocus)   # macOS 파란 포커스 링 제거
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
        # C안 — 완전 플랫: 행 테두리/구분선 없이 배경 위 글씨.
        # 선택행 = 폭 전체 틴트 + 흰 볼드 이름으로 표시. (좌측 액센트 바는 둥근 리스트 카드
        # 모서리를 따라 "(" 곡선처럼 휘어 보여 제거 — border-left는 투명으로 남겨 정렬만 유지.)
        if is_front:
            _sel_bg = 'rgba(78,125,240,34)' if is_dark() else 'rgba(78,125,240,26)'
            _sel_hv = 'rgba(78,125,240,48)' if is_dark() else 'rgba(78,125,240,38)'
            row.setStyleSheet(
                f'#capRow{{background:{_sel_bg};border-left:2px solid transparent;}}'
                f'#capRow:hover{{background:{_sel_hv};}}')
        else:
            row.setStyleSheet(
                f'#capRow{{background:transparent;border-left:2px solid transparent;}}'
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
            act = menu.addAction(_tx('No groups — create one with “+ Grp”'))
            act.setEnabled(False)
        else:
            title = menu.addAction(_tx('Move to Group')); title.setEnabled(False)
            for g in names:
                act = menu.addAction(('✓ ' if g == cur_group else '    ') + g)
                act.triggered.connect(
                    lambda _=False, gg=g, m=mode, i=cap_idx: self.move_to_group_req.emit(m, i, gg))
        if cur_group:
            menu.addSeparator()
            ung = menu.addAction(_tx('Remove from Group'))
            ung.triggered.connect(
                lambda _=False, m=mode, i=cap_idx: self.move_to_group_req.emit(m, i, ''))
        menu.addSeparator()
        rc = menu.addAction(_tx('Recapture'))
        rc.triggered.connect(
            lambda _=False, m=mode, i=cap_idx: self.recapture_requested.emit(m, i))
        menu.addSeparator()
        da = menu.addAction(_tx('Delete All'))
        da.triggered.connect(lambda _=False, m=mode: self.delete_all_requested.emit(m))
        menu.exec_(global_pos)

    def _show_panel_menu(self, global_pos):
        """캡쳐 패널 빈 공간 우클릭 → Delete All (현재 탭 기준 — Spectrum/TF 동일)."""
        from PyQt5.QtWidgets import QMenu
        menu = QMenu(self)
        da = menu.addAction(_tx('Delete All'))
        da.setEnabled(bool(self._cur_caps()))
        da.triggered.connect(lambda _=False: self.delete_all_requested.emit(self._panel_tab))
        menu.exec_(global_pos)


# RoundComboBox — v2.0 분해: spectra/ui/widgets.py, re-import
from spectra.ui.widgets import RoundComboBox
# ───────────────────────────────────────────
#  N2 툴바 프리미티브 (v1.9 리디자인)
#  — 테두리리스 + hover 배경 + Lucide 아이콘 + 캡스라벨 + 모노 값 + LED 토글
#  기존 위젯의 시그널/핸들러를 그대로 쓰도록 QComboBox/QPushButton 호환 API 제공.
# ───────────────────────────────────────────
# 아이콘/N2 헬퍼 — v2.0 분해: spectra/ui/icons.py 로 이동, re-import
from spectra.ui.icons import _icon_pm, _n2_hover_ss, _n2_icon_color, _n2_led_color

# N2 폰트 헬퍼 — v2.0 분해: spectra/ui/tokens.py 로 이동, re-import(동작 불변)
from spectra.ui.tokens import _n2_mono_font, _n2_caps_font, _n2_val_font


# N2 UI 빌더 — v2.0 분해: spectra/ui/icons.py 로 이동, re-import
from spectra.ui.icons import _n2_group_header, _n2_divider, _n2_tab_ss
# N2 위젯군 — v2.0 분해: spectra/ui/widgets.py, re-import
from spectra.ui.widgets import (_N2Select, _N2Button, _N2Toggle, _N2IconBtn, _N2SegBtn, _N2Segmented, _N2Tab, _sec_hairline)
# ───────────────────────────────────────────
#  Color picker dialog
# ───────────────────────────────────────────
# ColorPickerDialog — v2.0 분해: spectra/ui/dialogs.py, re-import
from spectra.ui.dialogs import ColorPickerDialog
# ───────────────────────────────────────────
#  Transfer Function 상수 & 헬퍼
# ───────────────────────────────────────────
TF_SMOOTH_BPO    = [0, 48, 24, 12, 6, 3, 1]
TF_SMOOTH_LABELS = ['None', '1/48', '1/24', '1/12', '1/6', '1/3', '1/1 Oct']
TF_AVG_SEC       = [0.5, 1, 2, 4, 8]   # 상승·하강 대칭 시정수(초). Smaart 라이브 튜닝식 짧은 범위. Normal=2초
TF_AVG_LABELS    = ['Fast', 'Quick', 'Normal', 'Smooth', 'Stable']   # 응답 속도(빠름→안정)
TF_FFT_SIZES     = [4096, 8192, 16384, 32768]
TF_FFT_LABELS    = ['4K', '8K', '16K', '32K']
TF_RENDER_MS     = 100   # TF 렌더/누적 주기(=기존 10fps 유지). 평균시정수도 이 주기 기준.
TF_PHASE_MODES   = ['Wrapped', 'Unwrapped', 'Group Delay']
TF_IR_MODES      = ['Lin', 'ETC', 'Log']

# TF 스무딩/멀티마이크 평균 — v2.0 분해: spectra/dsp/tf.py 로 이동, re-import(동작 불변)
from spectra.dsp.tf import _smooth_real, _tf_smooth, _multimic_average

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

# MTWEngine — v2.0 분해: spectra/dsp/tf.py 로 이동, 여기로 re-import(동작 불변)
from spectra.dsp.tf import MTWEngine


# Farina ESS DSP — v2.0 분해: spectra/dsp/farina.py 로 이동, 여기로 re-import(동작 불변)
from spectra.dsp.farina import (_gen_ess, _ess_inverse, _fft_convolve,
                                _band_taper, _wiener_match_scale, farina_analyze)


# _TF_SEL_GRAD_STOPS — v2.0 분해: spectra/ui/colors.py, re-import
from spectra.ui.colors import _TF_SEL_GRAD_STOPS

# _draw_tf_sel_border — v2.0 분해: spectra/ui/draw.py, re-import
from spectra.ui.draw import _draw_tf_sel_border
# TF 주파수줌 한계 상수 — v2.0 분해: spectra/ui/canvas_tf.py 내부

# _fz_clamp — v2.0 분해: spectra/ui/canvas_tf.py, re-import
from spectra.ui.canvas_tf import _fz_clamp
# _TFFreqZoomMixin — v2.0 분해: spectra/ui/canvas_tf.py, re-import
from spectra.ui.canvas_tf import _TFFreqZoomMixin
# TFPhaseCanvas — v2.0 분해: spectra/ui/canvas_tf.py, re-import
from spectra.ui.canvas_tf import TFPhaseCanvas
# TFMagCanvas — v2.0 분해: spectra/ui/canvas_tf.py, re-import
from spectra.ui.canvas_tf import TFMagCanvas
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
# _MiniVU — v2.0 분해: spectra/ui/widgets.py, re-import
from spectra.ui.widgets import _MiniVU
# ───────────────────────────────────────────
#  Smaart 방식 Input Levels 카드 위젯
# ───────────────────────────────────────────
# _HorizBarVU — v2.0 분해: spectra/ui/widgets.py, re-import
from spectra.ui.widgets import _HorizBarVU
# _DashedAddButton — v2.0 분해: spectra/ui/widgets.py 로 이동, re-import
from spectra.ui.widgets import _DashedAddButton
class _ColorSwatch(QWidget):
    """작은 원형 색 스와치 — 좌클릭 시 on_click 콜백(색상 선택창). 안티앨리어싱 원
    (QLabel border-radius 계단현상 회피, [[project_v18_compliance_badge_aa]] 방식)."""
    def __init__(self, diameter=13, parent=None):
        super().__init__(parent)
        self._sw_color = '#FFFFFF'
        self._d = int(diameter)
        self.setFixedSize(self._d + 4, self._d + 4)
        self.setCursor(Qt.PointingHandCursor)
        self.on_click = None

    def set_color(self, c):
        self._sw_color = c or '#FFFFFF'
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and callable(self.on_click):
            self.on_click(); e.accept()
        else:
            super().mousePressEvent(e)

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setPen(QPen(QColor(0, 0, 0, 70), 1))   # 옅은 테두리 → 흰 스와치도 밝은 배경서 보임
        p.setBrush(QColor(self._sw_color))
        p.drawEllipse(2, 2, self._d, self._d)


# _MeasCard — v2.0 분해: spectra/ui/widgets.py, re-import
from spectra.ui.widgets import _MeasCard, _PairLevelCard
# _VUProxy — v2.0 분해: spectra/ui/widgets.py, re-import
from spectra.ui.widgets import _VUProxy
# ───────────────────────────────────────────
#  Live IR 헬퍼 & 캔버스
# ───────────────────────────────────────────
# _hilbert_env — v2.0 분해: spectra/dsp/tf.py, re-import
from spectra.dsp.tf import _hilbert_env
def _ir_from_mag_phase(f_hz, mag_db, phase_deg, fs=48000, N=16384):
    """크기(dB)+위상(deg)에서 IR을 역FFT로 복원 (임포트용).

    CSV의 mag/phase는 로그격자라 균일 rfft 격자로 복소 보간 후 irfft.
    위상 래핑은 exp()가 주기적이라 무관하고, real/imag 따로 보간해 위상점프 안전.
    반환: (t_ms, h) — 시간축 중앙(0ms)을 임펄스 근처로 맞춤. 검증: 지연 정확·형상 상관 0.9.
    """
    f_hz = np.asarray(f_hz, dtype=np.float64)
    mag_lin = 10.0 ** (np.asarray(mag_db, dtype=np.float64) / 20.0)
    ph = np.radians(np.asarray(phase_deg, dtype=np.float64))
    Hc = mag_lin * np.exp(1j * ph)
    f_uni = np.fft.rfftfreq(N, 1.0 / fs)
    re = np.interp(f_uni, f_hz, Hc.real, left=0.0, right=0.0)
    im = np.interp(f_uni, f_hz, Hc.imag, left=0.0, right=0.0)
    h = np.fft.irfft(re + 1j * im, n=N).astype(np.float32)
    # 시간축: irfft는 0..N. 임펄스가 0ms 근처(지연보정 데이터)라 음/양 대칭 창으로 재배치.
    t_ms = (np.arange(N) - N // 2) / fs * 1000.0
    h = np.roll(h, N // 2).astype(np.float32)   # 0ms를 가운데로
    return t_ms.astype(np.float32), h


# TFIRCanvas — v2.0 분해: spectra/ui/canvas_tf.py, re-import
from spectra.ui.canvas_tf import TFIRCanvas
class TFDuplexThread(QThread):
    """출력(핑크노이즈)과 입력(마이크)을 단일 CoreAudio Duplex 스트림으로 처리.
    별도 스트림 2개로 인한 xrun/드롭아웃을 원천 제거."""
    frame_ready    = pyqtSignal(object, object)   # (ref_buf, meas_buf) — 단일 이벤트
    error_signal   = pyqtSignal(str)
    disconnected_signal = pyqtSignal(str)         # 작동 중 물리적 연결 끊김 (입력 장치)
    fade_done      = pyqtSignal()                 # 페이드인 완료 시 1회 emit → _reset_avg 트리거
    sweep_captured = pyqtSignal(object, object, int)   # (ref_array, meas_array, start_pos) — 1-shot 캡처 완료

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
        self._sc_start_pos = [0]    # 캡처 첫 샘플의 재생버퍼 인덱스(루프 위상) — Farina de-rotate용
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
                pp = pos_r[0]; _blk_pos0 = pp; rem = frames; op = 0   # _blk_pos0=이 블록 첫 출력샘플의 버퍼 인덱스
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
                        if pos == 0:
                            # 캡처 첫 샘플(_ref_blk[0]=out_blk[0])이 가리키는 재생버퍼 위상 기록
                            self._sc_start_pos[0] = _blk_pos0
                        self._sc_buf_ref [pos:pos+take] = _ref_blk[:take]
                        self._sc_buf_meas[pos:pos+take] = indata[:take, self.meas_in_ch]
                        _sc_pos[0] = pos + take
                        if _sc_pos[0] >= self._sc_len:
                            _sc_armed[0] = False
                            self.sweep_captured.emit(
                                self._sc_buf_ref.copy(), self._sc_buf_meas.copy(),
                                int(self._sc_start_pos[0]))
            except Exception: pass

        _alog.debug(f'TFDuplexThread.run() opening sd.Stream  in={self.in_dev} out={self.out_dev} sr={self.sample_rate} bs={blocksize} n_in={n_in} ref_ch={self.ref_ch}')
        try:
            with _no_stderr():
                with sd.Stream(device=(self.in_dev, self.out_dev),
                               samplerate=self.sample_rate,
                               channels=(n_in, self.n_out),
                               blocksize=blocksize, dtype='float32',
                               callback=cb, latency='high',
                               extra_settings=_win_extra_settings()) as stream:
                    self._active_stream = stream
                    _alog.debug(f'TFDuplexThread sd.Stream opened OK  latency={stream.latency}')
                    _wd_last[0] = time.monotonic()
                    _open_t = time.monotonic()          # [DIAG] 오픈 시각 — 첫 콜백 지연/미시작 계측
                    _first_logged = False; _dead_logged = False
                    while self.running:
                        self.msleep(10)
                        # [DIAG] AUHAL 콜백 시작 진단: 인터페이스 콜드오픈 시 스트림은 열려도 콜백이
                        # 스케줄 안 되는 레이스(하드웨어 미터도 무음) 추적. 재현 로그로 재오픈 워치독 위치 확정.
                        if _wd_got[0] and not _first_logged:
                            _first_logged = True
                            _diag('tf_duplex_first_cb', dev=self.out_dev,
                                  dt_ms=round((time.monotonic() - _open_t) * 1000))
                        if (not _wd_got[0]) and (not _dead_logged) and time.monotonic() - _open_t > 2.0:
                            _dead_logged = True
                            _diag('tf_duplex_cb_dead', dev=self.out_dev, in_dev=self.in_dev,
                                  bs=blocksize)   # ⚠️콜백 2초간 미시작 = 무음 원인 후보
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
# 설정 다이얼로그 — v2.0 분해: spectra/ui/dialogs.py, re-import
from spectra.ui.dialogs import _DelayAdvancedDialog, SweepConfigDialog, SineConfigDialog
# DelayFinderDialog — v2.0 분해: spectra/ui/dialogs.py, re-import
from spectra.ui.dialogs import DelayFinderDialog
# ───────────────────────────────────────────
#  전체 카드 딜레이 파인더 (L키)
# ───────────────────────────────────────────
# AllDelayFinderDialog — v2.0 분해: spectra/ui/dialogs.py, re-import
from spectra.ui.dialogs import AllDelayFinderDialog
# ───────────────────────────────────────────
#  TF Average 선택 다이얼로그
# ───────────────────────────────────────────
# _TFAverageDialog — v2.0 분해: spectra/ui/dialogs.py, re-import
from spectra.ui.dialogs import _TFAverageDialog
# ShortcutsDialog — v2.0 분해: spectra/ui/dialogs.py, re-import
from spectra.ui.dialogs import ShortcutsDialog
# ───────────────────────────────────────────
#  TF 단축키 이벤트 필터 (G / L)
# ───────────────────────────────────────────
def _shortcut_should_yield():
    """전역 단일키 단축키(G/L/S/R 등)가 가로채면 안 되는 상황:
    모달 다이얼로그(캡처/세이브 이름 입력 등)가 떠 있거나, 텍스트 입력칸/콤보/리스트에 포커스.
    → 입력 중인 글자(영문 l/s, 한글 조합 등)를 단축키가 삼키지 않게."""
    from PyQt5.QtWidgets import (QApplication, QLineEdit, QAbstractSpinBox, QTextEdit,
                                 QPlainTextEdit, QComboBox, QAbstractItemView)
    if QApplication.activeModalWidget() is not None:
        return True
    fw = QApplication.focusWidget()
    return isinstance(fw, (QLineEdit, QAbstractSpinBox, QTextEdit,
                          QPlainTextEdit, QComboBox, QAbstractItemView))


class _TFKeyFilter(QObject):
    """TF 패널이 화면에 보일 때(isVisible=True)만 G/L 키 처리.
    QShortcut 방식은 포커스에 의존 → 이벤트 필터로 대체."""
    def __init__(self, tf_win):
        super().__init__(tf_win)
        self._tf = tf_win

    def eventFilter(self, obj, event):
        from PyQt5.QtCore import QEvent
        if event.type() == QEvent.KeyPress and self._tf.isVisible():
            if _shortcut_should_yield():     # 입력칸/다이얼로그에선 키를 그대로 통과
                return False
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


class _MainKeyFilter(QObject):
    """S 키 = Spectrum/Stereo 탭 Start·Stop 토글 (앱 레벨, 포커스 무관).
    단, 텍스트 입력 중이거나 메인창이 비활성(팝업 포커스)이면 무시."""
    def __init__(self, mw):
        super().__init__(mw)
        self._mw = mw

    def eventFilter(self, obj, event):
        if event.type() != QEvent.KeyPress:
            return False
        if not self._mw.isActiveWindow():
            return False
        # 텍스트 입력칸·콤보·리스트·모달 다이얼로그에선 가로채지 않음(입력 글자 보호)
        if _shortcut_should_yield():
            return False
        key = event.key()
        if key == Qt.Key_Question:          # ? = 단축키 치트시트 (Shift+/)
            self._mw._show_shortcuts(); return True
        if key in (Qt.Key_S, Qt.Key_R) and event.modifiers() == Qt.NoModifier:
            if key == Qt.Key_R:             # R = 선택 캡쳐 제자리 다시 캡쳐
                self._mw._recapture_selected(); return True
            tab = self._mw.main_stack.currentIndex()
            if tab == 0:      # Spectrum
                self._mw._toggle(); return True
            elif tab == 2:    # Stereo Loudness
                self._mw._st_toggle(); return True
        return False


# ───────────────────────────────────────────
#  Transfer Function 창
# ───────────────────────────────────────────
class _TFTitleHotspot(QWidget):
    """플롯 좌상단 제목 글씨 위의 투명 클릭영역 — 누르면 콜백(전역좌표)으로 콘텐츠 선택 메뉴.
    별도 헤더줄 없이 제목만 눌러 칸 내용을 바꾸기 위함(그래프 높이 보존)."""
    def __init__(self, parent, on_click):
        super().__init__(parent)
        self._on_click = on_click
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet('background:transparent;')
        self.setToolTip(_tx('Click → select plot'))

    def mousePressEvent(self, e):
        self._on_click(e.globalPos())


# _ConvWorker — v2.0 분해: spectra/ui/dialogs.py, re-import
from spectra.ui.dialogs import _ConvWorker
# _AuralizeDialog — v2.0 분해: spectra/ui/dialogs.py, re-import
from spectra.ui.dialogs import _AuralizeDialog
class TransferFunctionWindow(QWidget):
    _find_result_sig      = pyqtSignal(float)           # primary delay finder 결과
    _find_pair_result_sig = pyqtSignal(int, float)      # (pair_idx_enc, d_ms) per-card

    def __init__(self, parent=None, settings=None, embedded=False):
        self.embedded = embedded
        self._mw = parent   # 생성 시점 MainWindow 안정 참조(팝아웃 reparent 후에도 불변) — 프리 모니터 활성탭 판정용
        if embedded:
            super().__init__(parent)
        else:
            super().__init__(parent, Qt.Window)
            self.setWindowTitle('SPECTRA — Transfer Function')
            self.setMinimumSize(1020, 570)
        self._settings = settings or {}
        self._tf_primary_name = self._settings.get('tf_primary_name', '')  # primary 카드 사용자 이름
        self._tf_primary_color = self._settings.get('tf_primary_color', '') or ''  # primary(1번) 곡선 사용자색. ''=기본 green
        self.sample_rate = 48000; self.fft_size = 16384
        self.smooth_bpo = 3; self.averaging_sec = 2.0   # 기본 Normal(2초, 대칭)
        self.delay_ms = 0.0; self.phase_mode = 0; self.coh_blank = 0.5
        self._ref_capture_idx = None; self._delta_on = False  # Δ 비교 상태
        self._stabilizing = False; self._stable_timer = None  # 안정화 캡쳐 상태
        self._mutex = QMutex()
        self._engine = None   # 공유 오디오 엔진 (MainWindow가 주입) — TF 측정입력을 장치당 단일 스트림으로
        self._ref_thread = None; self._meas_thread = None; self._sync_thread = None
        # primary 프레임이 콜백에서 이미 시간영역 정렬됐는지(_on_frame 경로=True). 분리 콜백
        # 경로(_on_ref+_on_meas: Internal SigGen / 다른장치 ref)는 False → 렌더에서 정렬 필요.
        self._primary_upstream_aligned = False
        # 라이브 멀티마이크 평균 상태
        self._avg_on = False
        self._avg_mode = 'mag'      # 'mag'(파워RMS) | 'complex'(벡터)
        self._avg_align = True      # 복소 모드 딜레이 자동정렬(코어용, UI 미노출)
        self._avg_show = True       # AVG 카드 ✓ = 평균 곡선 표시/숨김
        self._avg_color = None      # 평균 곡선/카드 색(None=테마 기본 흰/근검정, 우클릭 변경)
        self._avg_card_selected = False   # AVG 카드 선택(틴트+맨앞 굵게)
        self._last_avg_diag = None  # tf_avg_render 로그 스팸 방지용 마지막 상태 시그니처
        self._extra_pairs = []        # Smaart 방식: 추가 Ref+Meas 쌍 목록
        self._front_pair = None       # 분석 화면 맨 앞 곡선: None=primary, int=pair idx
        self._extra_pair_threads = [] # 쌍마다 (sync_thread, ref_thread, meas_thread)
        self._extra_pair_acc = []     # 쌍마다 {cross, auto_x, auto_y, n} or None
        self._last_primary_H = None; self._last_primary_coh = None  # 라이브 평균 수집용(프레임별 갱신)
        self._last_avg_freqs = None; self._last_avg_t_ms = None      # 정지 시 AVG 재계산용 마지막 그리드
        self._mc_threads = {}         # {device_idx: (thread, routing_list)}
        self._last_ref_fft = None; self._last_meas_fft = None
        self._last_ref_rms = 0.0; self._last_meas_rms = 0.0
        # v1.7 라이브 엔진: Single FFT(기본) ↔ MTW. MTW는 시간영역 버퍼를 보관.
        self._tf_engine_mtw = False; self._mtw = None
        # MTW 무거운 멀티레이트 FFT를 GUI 스레드 밖(단일 워커)에서 계산 → Spectrum과 병렬.
        # 워커가 _mtw를 전담 사용, GUI는 결과(_dsp_out)만 그림. 드문 reset/engine변경은 _dsp_sync로 직렬화.
        self._dsp_exec = None       # ThreadPoolExecutor(max_workers=1) — MTW 렌더 시 지연생성
        self._dsp_future = None     # 진행 중 계산 future
        self._dsp_out = None        # 워커가 적재한 최신 (f_m, H_m, coh_m)
        self._dsp_gen = 0           # 리셋 세대 토큰 — 리셋 이후 진행 중 워커 결과 폐기(비차단)
        self._mtw_reset_pending = False  # xrun 등 비차단 리셋 예약 → 워커 idle 시 안전하게 _mtw.reset()
        self._last_ref_buf = None; self._last_meas_buf = None
        self._mtw_H_lin = None      # MTW 최신 선형그리드 H (영속) — 딜레이 파인더용
        self._rta_sub = None        # RTA 전용 엔진 구독(제너레이터/Start 없이 마이크 스펙트럼)
        self._rta_ch = 0
        self._rta_avg_buf = deque(maxlen=16)   # RTA FIFO 평균(스펙트럼 Avg와 동일 처리)
        self._rta_last = 0.0   # RTA 컴퓨트 스로틀(엔진 60fps → ~30fps로 FFT 부하 절감)
        self._rta_last_chunk = 0.0   # 마지막 청크 도착 시각 — liveness watchdog(구독 죽으면 재구독)
        self._rta_pow_smooth = None  # 파워도메인 IIR 누적(스펙트럼 _process_audio와 동일 1단 스무딩)
        self._rta_pending = None   # 최신 옥타브값 (producer=_on_rta_chunk / consumer=_rta_render_frame)
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
        self._sine_freq  = 1000.0     # 사인파 주파수(Hz)
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
        if self._tf_primary_color:   # 저장된 primary(1번) 사용자색 복원
            self._apply_primary_color(self._tf_primary_color, save=False)
        self.setAcceptDrops(True)   # 오디오 파일 드래그&드롭 → File 측정 신호 로드
        self._find_result_sig.connect(self._apply_find_result)
        self._find_pair_result_sig.connect(self._apply_find_pair_result)
        self._timer = QTimer(self); self._timer.timeout.connect(self._render); self._timer.start(TF_RENDER_MS)
        # primary 곡선 모션 스무딩: 10fps 누적 사이를 30fps로 보간 페인트 (데이터/평균 불변)
        self._pm_prev = None; self._pm_targ = None; self._pm_t0 = 0.0; self._pm_done = True
        self._pm_smooth_t = QTimer(self)
        self._pm_smooth_t.timeout.connect(self._pm_smooth_paint); self._pm_smooth_t.start(33)
        # RTA 소비자 — 스펙트럼 _render_frame과 동일하게 30fps 고정 타이머가 페인트 구동
        # (콜백 지터와 분리 → 버벅임 제거). 구독 없으면 즉시 반환하므로 idle 비용 0.
        self._rta_render_t = QTimer(self); self._rta_render_t.timeout.connect(self._rta_render_frame); self._rta_render_t.start(33)
        # G/L 단축키: QShortcut 대신 앱 레벨 이벤트 필터 사용 (포커스/상태 무관)
        self._key_filter = _TFKeyFilter(self)
        QApplication.instance().installEventFilter(self._key_filter)
        # 기본 엔진 = Adaptive (멀티레이트). UI/엔진 셋업은 _engine_changed 가 처리.
        self.eng_cb.setCurrentIndex(1)
        QTimer.singleShot(0, self._restore_tf_captures)

    # ── UI ──────────────────────────────────
    def _build_ui(self):
        from PyQt5.QtWidgets import QDoubleSpinBox, QSlider
        root = QVBoxLayout(self); root.setSpacing(0); root.setContentsMargins(0,0,0,0)

        # 헤더 — self._hdr로 저장해야 embedded 모드에서 GC로 인한 C++ 객체 삭제 방지
        self._hdr = _BrandHeaderBar(); self._hdr.setFixedHeight(40); self._hdr.setObjectName('tfBrandHdr')
        self._hdr.setStyleSheet(f'#tfBrandHdr{{background:{T("bg2")};}}')
        hl = QHBoxLayout(self._hdr); hl.setContentsMargins(16,0,16,0); hl.setSpacing(9)
        _mark = QLabel(); _mark.setPixmap(_spectra_mark(20)); _mark.setStyleSheet('background:transparent;')
        self._hdr_logo = QLabel()
        self._hdr_logo.setTextFormat(Qt.RichText); self._hdr_logo.setStyleSheet('background:transparent;')
        self._hdr_logo.setText(_brand_logo_html('Transfer Function'))
        # 라벨 마우스 투명 → 헤더 더블클릭으로 창 최대화/복원 (메인 헤더와 동일)
        for _lb in (_mark, self._hdr_logo):
            _lb.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        hl.addSpacing(30)   # 우측 토글 버튼 폭 보정(팝아웃 시 추가) → 로고 가운데
        hl.addStretch(1); hl.addWidget(_mark); hl.addWidget(self._hdr_logo); hl.addStretch(1)
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

        self.cvs_w = cvs_w = _CardSplitter(Qt.Vertical)   # 거터에 옅은 그라디언트 경계선
        cvs_w.setHandleWidth(7)                 # 3탭 스플리터 핸들 폭 통일
        # 카드형: handle(=카드 사이 거터)은 _GradSplitterHandle가 직접 그림(거터색 + 옅은 그라디언트 라인)
        self.ir_cvs = TFIRCanvas()
        self.phase_cvs = TFPhaseCanvas(); self.mag_cvs = TFMagCanvas()
        self.mag_cvs._on_lock_change = self._on_tf_db_change   # dB축 고정 → 저장 + 툴바 버튼 갱신
        if self._settings.get('tf_db_lock'):                 # 재시작 복원
            self.mag_cvs._db_lock = True
            self.mag_cvs.db_max = float(self._settings.get('tf_db_top', self.mag_cvs.db_max))
            self.mag_cvs.db_min = float(self._settings.get('tf_db_bot', self.mag_cvs.db_min))
            self.mag_cvs._cache = None
        # 주파수축 줌/팬 연동: 한쪽에서 줌 → 매그·위상 둘 다 같은 f_lo/f_hi (같은 주파수축)
        self.mag_cvs._fzoom_cb = self.phase_cvs._fzoom_cb = self._sync_freq_zoom
        # 분석창 클릭 → 그 창 외곽 하이라이트 (이벤트필터로 감지, 기존 마우스 동작 유지)
        self._tf_cvs_list = [self.ir_cvs, self.phase_cvs, self.mag_cvs]
        for _c in self._tf_cvs_list:
            _c._tf_selected = False
            _c.installEventFilter(self)
        # 커서 동기화: 한 캔버스에서 마우스 움직이면 양쪽 모두 크로스헤어 표시
        self.phase_cvs.cursor_x_changed.connect(self.mag_cvs.set_peer_cursor)
        self.mag_cvs.cursor_x_changed.connect(self.phase_cvs.set_peer_cursor)
        self.phase_cvs.cursor_left.connect(self.mag_cvs.clear_peer_cursor)
        self.mag_cvs.cursor_left.connect(self.phase_cvs.clear_peer_cursor)
        # RTA 칸용 옥타브 캔버스 — MainWindow가 Spectrum 데이터로 급전(스펙트럼 탭 상태 그대로)
        self.rta_cvs = OctaveCanvas(); self.rta_cvs.set_mode('oct12')
        self.rta_cvs.title_text = 'RTA  (1/12 oct)  ▾'
        self.rta_cvs._rta_range_init = False   # RTA 켤 때 1회 스펙트럼 dB범위 받기(이후 독립)
        self.rta_cvs.installEventFilter(self); self.rta_cvs._tf_selected = False
        self._tf_cvs_list.append(self.rta_cvs)
        # ── Smaart식: 칸마다 '제목 글씨'를 누르면 콘텐츠 선택 메뉴 (별도 헤더줄 없음 → 그래프 높이 보존) ──
        self._tf_plots = {'Magnitude': self.mag_cvs, 'Phase': self.phase_cvs,
                          'Live IR': self.ir_cvs, 'RTA': self.rta_cvs}
        self._tf_plot_order = ['Magnitude', 'Phase', 'Live IR', 'RTA']   # 메뉴 항목
        self._tf_slot_w = []; self._tf_slot_box = []; self._tf_slot_hot = []
        self._tf_slot_plot = [None, None, None]
        for i in range(3):
            slot = QWidget(); sv = QVBoxLayout(slot); sv.setContentsMargins(0, 0, 0, 0); sv.setSpacing(0)
            slot_body = QWidget(); bx = QVBoxLayout(slot_body); bx.setContentsMargins(0, 0, 0, 0); bx.setSpacing(0)
            sv.addWidget(slot_body, 1)
            cvs_w.addWidget(slot); cvs_w.setCollapsible(i, False)
            # 좌상단 제목 위 투명 클릭영역 — 제목 글씨를 누르면 _tf_slot_menu
            hot = _TFTitleHotspot(slot, lambda gp, si=i: self._tf_slot_menu(si, gp))
            hot.setGeometry(0, 0, 285, 34)   # 제목 baseline=pt+13=29, 최장 제목(Magnitude…▾ ≈265px)+여백 폭 285 · 높이 34로 글씨 완전 덮음(PAD_T=16 반영)
            self._tf_slot_w.append(slot); self._tf_slot_box.append(bx); self._tf_slot_hot.append(hot)
        cvs_w.setSizes([200, 400, 600])
        bl.addWidget(cvs_w, 1)

        # 우측 패널
        self.rp = QWidget(); self.rp.setFixedWidth(260)
        self.rp.setStyleSheet(f'background:{T("bg2")};')
        rl = QVBoxLayout(self.rp); rl.setContentsMargins(10,10,10,10); rl.setSpacing(8)

        # 신호 발생기
        sg = QGroupBox(); sg.setObjectName('sigGenGrp')
        sgl = QVBoxLayout(sg); sgl.setSpacing(7); sgl.setContentsMargins(3,3,3,5)
        sgl.addWidget(_n2_group_header('SIGNAL GENERATOR'))
        # 신호 타입 = 드롭다운으로 통합. 아래 버튼들은 상태 보관용(숨김) — 다운스트림
        # isChecked() 로직(어느 타입인지 판별)을 그대로 보존.
        _tk_bg, _tk_bd = ('#141416', '#34343B') if is_dark() else (T('bg3'), T('border'))
        self.sig_pink_btn  = _CheckBtn('Pink');  self.sig_pink_btn.setChecked(True)
        self.sig_white_btn = _CheckBtn('White')
        self.sig_sine_btn  = _CheckBtn('Sine')
        self.sig_sweep_btn = _CheckBtn('Sweep')
        for _b in (self.sig_pink_btn, self.sig_white_btn, self.sig_sine_btn, self.sig_sweep_btn):
            _b.hide()
        def _sig_gen_active():
            """제네레이터 스트림이 열려 있으면 True (재생/뮤트 무관)."""
            return (self._duplex_thread is not None and self._duplex_thread.isRunning()) or \
                   (self._sig_stream is not None)

        def _stop_if_playing():
            """신호 타입 변경 시 스트림을 완전 종료하고 버튼을 ▶ Play로 리셋."""
            if _sig_gen_active():
                self._stop_sig_gen()
                self.sig_on_btn.setChecked(False)
                self.sig_on_btn.setText('Play'); self._style_sig_play(False)

        def _sel_pink():
            _stop_if_playing()
            self.sig_pink_btn.setChecked(True); self.sig_white_btn.setChecked(False)
            self.sig_sine_btn.setChecked(False)
            self.sig_sweep_btn.setChecked(False); self.sig_file_btn.setChecked(False)
        def _sel_white():
            _stop_if_playing()
            self.sig_white_btn.setChecked(True); self.sig_pink_btn.setChecked(False)
            self.sig_sine_btn.setChecked(False)
            self.sig_sweep_btn.setChecked(False); self.sig_file_btn.setChecked(False)
        def _sel_sine():
            _stop_if_playing()
            dlg = SineConfigDialog(self, freq=self._sine_freq)
            if dlg.exec_() == QDialog.Accepted:
                self._sine_freq = dlg.freq
                _f = self._sine_freq
                if _f >= 1000:
                    _ft = f'{_f/1000:.0f}k' if abs(_f/1000-round(_f/1000))<0.05 else f'{_f/1000:.1f}k'
                else:
                    _ft = f'{_f:.0f}' if abs(_f-round(_f))<0.05 else f'{_f:.1f}'
                self.sig_sine_btn.setText(f'Sine {_ft}')
                self.sig_sine_btn.setChecked(True)
                self.sig_pink_btn.setChecked(False)
                self.sig_white_btn.setChecked(False)
                self.sig_sweep_btn.setChecked(False)
                self.sig_file_btn.setChecked(False)
            else:
                # Cancel → 선택 상태 복원
                if not any([self.sig_pink_btn.isChecked(),
                            self.sig_white_btn.isChecked(),
                            self.sig_sweep_btn.isChecked(),
                            self.sig_file_btn.isChecked()]):
                    self.sig_pink_btn.setChecked(True)
                self.sig_sine_btn.setChecked(False)
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
                self.sig_sine_btn.setChecked(False)
                self.sig_file_btn.setChecked(False)
            else:
                # Cancel → 선택 상태 복원
                if not any([self.sig_pink_btn.isChecked(),
                            self.sig_white_btn.isChecked(),
                            self.sig_sine_btn.isChecked(),
                            self.sig_file_btn.isChecked()]):
                    self.sig_pink_btn.setChecked(True)
                self.sig_sweep_btn.setChecked(False)
        self.sig_pink_btn.clicked.connect(_sel_pink)
        self.sig_white_btn.clicked.connect(_sel_white)
        self.sig_sine_btn.clicked.connect(_sel_sine)
        self.sig_sweep_btn.clicked.connect(_sel_sweep)
        # direction C 컨트롤 셀 스타일 (서브틀 보더)
        _c_cell = (f'border:1px solid {_tk_bd};background:transparent;color:{T("text")};border-radius:8px;')
        _c_hover = f'QPushButton:hover{{color:{T("text")};border-color:#4A4A54;}}'
        # File 버튼 — 드롭다운 항목으로 통합, 상태 보관용(숨김)
        self.sig_file_btn = _CheckBtn('File…'); self.sig_file_btn.hide()
        self.sig_file_btn.clicked.connect(self._pick_audio_file)
        # ── 통합 행: [타입 드롭다운]  [− 값 +] (LEVEL) ──
        row1 = QHBoxLayout(); row1.setSpacing(4)
        _tcell = QFrame(); _tcell.setObjectName('sigTypeCell'); _tcell.setFixedHeight(30); _tcell.setMinimumWidth(70)
        _tcell.setStyleSheet(f'#sigTypeCell{{border:1px solid {_tk_bd};background:transparent;border-radius:8px;}}'
                             f'#sigTypeCell:hover{{border-color:#4A4A54;}}')
        _tcell.setCursor(Qt.PointingHandCursor)
        _th = QHBoxLayout(_tcell); _th.setContentsMargins(9,0,8,0); _th.setSpacing(6)
        self._sig_type_ic = QLabel(); self._sig_type_ic.setFixedSize(15,15); self._sig_type_ic.setStyleSheet('background:transparent;')
        self._sig_type_txt = QLabel('Pink'); self._sig_type_txt.setFont(_n2_val_font(12, QFont.DemiBold)); self._sig_type_txt.setStyleSheet(f'color:{T("text")};background:transparent;')
        _tchev = QLabel('▾'); _tchev.setStyleSheet(f'color:{T("text_dim")};background:transparent;')
        _th.addWidget(self._sig_type_ic); _th.addWidget(self._sig_type_txt); _th.addStretch(); _th.addWidget(_tchev)
        from PyQt5.QtWidgets import QMenu as _QMenu
        _tmenu = _QMenu(_tcell)
        _tmenu.addAction(_icon('waves',15,_n2_icon_color()),    'Pink',   lambda: (_sel_pink(),  self._update_sig_type_label()))
        _tmenu.addAction(_icon('waves',15,_n2_icon_color()),    'White',  lambda: (_sel_white(), self._update_sig_type_label()))
        _tmenu.addAction(_icon('activity',15,_n2_icon_color()), 'Sine…',  lambda: (_sel_sine(),  self._update_sig_type_label()))
        _tmenu.addAction(_icon('spline',15,_n2_icon_color()),   'Sweep…', lambda: (_sel_sweep(), self._update_sig_type_label()))
        _tmenu.addAction(_icon('folder',15,_n2_icon_color()),   'File…',  lambda: (self._pick_audio_file(), self._update_sig_type_label()))
        self._sig_type_menu = _tmenu
        _tcell.mousePressEvent = lambda e: self._sig_type_menu.exec_(_tcell.mapToGlobal(QPoint(0, _tcell.height()+2)))
        self._sig_type_cell = _tcell; self._sig_type_chev = _tchev   # 테마 재스타일용 참조
        row1.addWidget(_tcell, 5)
        _step_ss = (f'QPushButton{{{_c_cell}font-size:16px;font-weight:600;color:{T("text_dim")};}}' + _c_hover)
        self.sig_lvl_btn_m = QPushButton('−'); self.sig_lvl_btn_m.setFixedSize(28, 30); self.sig_lvl_btn_m.setFocusPolicy(Qt.NoFocus); self.sig_lvl_btn_m.setStyleSheet(_step_ss)
        self.sig_lvl_sp = QDoubleSpinBox()
        self.sig_lvl_sp.setRange(-99.0, 0.0); self.sig_lvl_sp.setSingleStep(1.0)
        self.sig_lvl_sp.setValue(-20.0); self.sig_lvl_sp.setSuffix(' dB')
        self.sig_lvl_sp.setDecimals(1); self.sig_lvl_sp.setFixedHeight(30); self.sig_lvl_sp.setMinimumWidth(60)
        self.sig_lvl_sp.setAlignment(Qt.AlignCenter); self.sig_lvl_sp.setButtonSymbols(QDoubleSpinBox.NoButtons)
        self.sig_lvl_sp.setKeyboardTracking(False)   # 타이핑 중 즉시 적용 방지
        self.sig_lvl_sp.setStyleSheet(
            f'QDoubleSpinBox{{{_c_cell}padding:2px 4px;font-family:Menlo;font-size:12px;font-weight:600;}}')
        self.sig_lvl_sp.valueChanged.connect(self._sig_level_changed)
        self.sig_lvl_btn_p = QPushButton('+'); self.sig_lvl_btn_p.setFixedSize(28, 30); self.sig_lvl_btn_p.setFocusPolicy(Qt.NoFocus); self.sig_lvl_btn_p.setStyleSheet(_step_ss)
        self.sig_lvl_btn_m.clicked.connect(self.sig_lvl_sp.stepDown)
        self.sig_lvl_btn_p.clicked.connect(self.sig_lvl_sp.stepUp)
        row1.addWidget(self.sig_lvl_btn_m); row1.addWidget(self.sig_lvl_sp, 4); row1.addWidget(self.sig_lvl_btn_p)
        sgl.addLayout(row1)
        self._update_sig_type_label()
        or_ = QHBoxLayout(); or_.setSpacing(5); or_.setContentsMargins(0,0,0,0)
        _out_lbl = QLabel('OUT'); _out_lbl.setFont(_n2_caps_font()); _out_lbl.setStyleSheet(f'color:{T("text_dim")};background:transparent;'); _out_lbl.setFixedWidth(40)
        or_.addWidget(_out_lbl)
        _c_combo = (f'QComboBox{{{_c_cell}padding:2px 8px;font-size:12px;}}'
                    f'QComboBox:hover{{border-color:#4A4A54;}}'
                    f'QComboBox::drop-down{{width:0;border:none;}}'
                    f'QComboBox::down-arrow{{width:0;height:0;image:none;}}')
        self.sig_out_cb = RoundComboBox(); self.sig_out_cb.setFixedHeight(30)
        self.sig_out_cb._max_display_chars = 3; self.sig_out_cb.setFocusPolicy(Qt.NoFocus)
        self.sig_out_cb._flat_cell = True; self.sig_out_cb._flat_border = _tk_bd
        self.sig_out_ch_cb  = RoundComboBox(); self.sig_out_ch_cb.setFixedWidth(56); self.sig_out_ch_cb.setFixedHeight(30); self.sig_out_ch_cb.setFocusPolicy(Qt.NoFocus); self.sig_out_ch_cb._align_center = True
        self.sig_out_ch_cb._flat_cell = True; self.sig_out_ch_cb._flat_border = _tk_bd; self.sig_out_ch_cb._grid_popup = True
        self.sig_out_ch2_cb = RoundComboBox(); self.sig_out_ch2_cb.setFixedWidth(56); self.sig_out_ch2_cb.setFixedHeight(30); self.sig_out_ch2_cb.setFocusPolicy(Qt.NoFocus); self.sig_out_ch2_cb._align_center = True
        self.sig_out_ch2_cb._flat_cell = True; self.sig_out_ch2_cb._flat_border = _tk_bd; self.sig_out_ch2_cb._grid_popup = True
        self.sig_out_ch2_cb.setToolTip(_tx('Second output channel (Off = single channel)'))
        or_.addWidget(self.sig_out_cb, 2)
        or_.addWidget(self.sig_out_ch_cb, 1)
        _plus_lbl = QLabel('+'); _plus_lbl.setAlignment(Qt.AlignVCenter | Qt.AlignHCenter); _plus_lbl.setFixedWidth(12); _plus_lbl.setStyleSheet(f'color:{T("text_dim")};background:transparent;')
        or_.addWidget(_plus_lbl)
        or_.addWidget(self.sig_out_ch2_cb, 1)
        sgl.addLayout(or_)
        self.sig_out_cb.currentIndexChanged.connect(self._sig_out_device_changed)
        self.sig_out_ch2_cb.currentIndexChanged.connect(self._sig_out_ch_changed)
        # Play — direction C: 회색 채움 필 + 재생/정지 아이콘(전용 스타일러, _apply_txn 대체)
        self.sig_on_btn = QPushButton('Play  [G]'); self.sig_on_btn.setCheckable(True)
        self.sig_on_btn.setFixedHeight(34); self.sig_on_btn.setFocusPolicy(Qt.NoFocus); self.sig_on_btn.setCursor(Qt.PointingHandCursor)
        self._style_sig_play(False)
        self.sig_on_btn.clicked.connect(self._toggle_sig_gen); sgl.addWidget(self.sig_on_btn)
        rl.addWidget(sg)

        # 라이브 멀티마이크 평균(크기/공간 평균) — 툴바 Σ 버튼으로 여는 플로팅 팝업
        pop = QFrame(); pop.setObjectName('avgPop')
        pop.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint)
        avg_l = QVBoxLayout(pop); avg_l.setContentsMargins(12, 10, 12, 12); avg_l.setSpacing(8)
        avg_l.addWidget(_n2_group_header('AVERAGE'))
        # 마이크 체크리스트만 (Σ 버튼이 on/off, 여기선 평균 대상 선택; 열 때 현재 카드로 재구성)
        self._avg_mic_box = QWidget()
        self._avg_mic_lay = QVBoxLayout(self._avg_mic_box)
        self._avg_mic_lay.setContentsMargins(0, 2, 0, 0); self._avg_mic_lay.setSpacing(5)
        avg_l.addWidget(self._avg_mic_box)
        self._avg_popup = pop
        self._style_avg_popup()

        # 입력 장치
        # ── Measurement 패널: 공유 Ref 섹션 + N개 Meas 채널 카드 ──
        mp = QGroupBox(); mp.setObjectName('measGrp')
        mpl = QVBoxLayout(mp); mpl.setContentsMargins(3,3,3,8); mpl.setSpacing(7)
        mpl.addWidget(_n2_group_header('MEASUREMENT'))

        self._mon_btn = None

        # ── 공유 Reference 섹션 ──
        # Reference도 측정 카드와 동일한 카드 박스로 — R/M 레벨 바가 동일 컨테이너·
        # 동일 내부여백에 놓여 구조적으로 좌우 정렬됨(가로폭·세로 위치 통일, v1.9 #4).
        ref_sec = QFrame(); ref_sec.setObjectName('refCard'); self._ref_sec = ref_sec
        _ref_bd = '#34343B' if is_dark() else T('border')
        _ref_bg = '#1E1E22' if is_dark() else '#F3F5FA'
        ref_sec.setStyleSheet(f'QFrame#refCard{{border:1px solid {_ref_bd};border-radius:10px;background:{_ref_bg};padding:2px;}}')
        ref_sl = QVBoxLayout(ref_sec); ref_sl.setContentsMargins(6,5,6,6); ref_sl.setSpacing(3)
        ref_hdr = QHBoxLayout(); ref_hdr.setContentsMargins(0,0,0,0); ref_hdr.setSpacing(4)
        _ref_dot = QLabel('●')
        _ref_dot.setStyleSheet(f'color:{T("accent")};background:transparent;font-size:{FS_BODY}px;')
        _ref_name = QLabel('Reference')
        _ref_name.setStyleSheet(f'color:{T("accent")};background:transparent;font-size:{FS_BODY}px;font-weight:bold;')
        ref_hdr.addWidget(_ref_dot); ref_hdr.addWidget(_ref_name); ref_hdr.addStretch()
        self._ref_db_lbl = QLabel('—')
        self._ref_db_lbl.setFont(_n2_mono_font(13, QFont.Bold))
        self._ref_db_lbl.setStyleSheet(f'color:{T("accent")};background:transparent;')
        self._ref_db_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
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
        _ref_flat = (f'QComboBox{{background:transparent;color:{T("text")};border:1px solid {_ref_bd};'
                     f'border-radius:8px;padding:1px 8px;font-size:{FS_SM}px;min-height:22px;}}'
                     f'QComboBox::drop-down{{width:0;border:none;}}QComboBox::down-arrow{{width:0;height:0;image:none;}}')
        for _cb in (self.ref_cb, self.ref_ch_cb):
            _cb.setStyleSheet(_ref_flat); _cb.setFocusPolicy(Qt.NoFocus)
            _cb._flat_cell = True; _cb._flat_border = _ref_bd
        self.ref_cb._elide_to_width = True; self.ref_ch_cb._align_center = True; self.ref_ch_cb.setFixedWidth(48); self.ref_ch_cb._grid_popup = True
        self.ref_cb.currentIndexChanged.connect(self._ref_device_changed)
        self.ref_ch_cb.currentIndexChanged.connect(self._on_input_setting_changed)
        ref_row = QHBoxLayout(); ref_row.setContentsMargins(0,0,0,0); ref_row.setSpacing(3)
        _rl = QLabel('In'); _rl.setFixedWidth(14)
        _rl.setStyleSheet(ss_text(FS_XS))
        self.ref_cb.setMinimumWidth(100)
        ref_row.addWidget(_rl); ref_row.addWidget(self.ref_cb, 1); ref_row.addWidget(self.ref_ch_cb)
        ref_sl.addLayout(ref_row)
        mpl.addWidget(ref_sec)

        mpl.addWidget(hsep())

        # ── Meas 카드 목록 ──
        self._level_cards = []
        self._cards_layout = QVBoxLayout(); self._cards_layout.setSpacing(6)
        # 마진 0 = Reference 카드와 동일 폭·정렬. 가로 스크롤(카드 밀림·테두리 잘림)은
        # _VScrollArea가 위젯 폭을 뷰포트에 고정해 원천 차단.
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
        primary_card.avg_include_toggled.connect(self._on_card_avg_include)
        primary_card.color_changed.connect(self._on_primary_color_changed)
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
        self._cards_scroll = _VScrollArea()   # 내부폭 뷰포트 고정 → 가로 스와이프로 카드 밀림 방지
        self._cards_scroll.setWidget(cards_container)
        self._cards_scroll.setWidgetResizable(True)
        self._cards_scroll.setFrameShape(QFrame.NoFrame)
        self._cards_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._cards_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._cards_scroll.viewport().setStyleSheet('background:transparent;')
        self._cards_scroll.setStyleSheet(
            f'QScrollArea{{background:transparent;border:none;}}'
            f'QScrollBar:vertical{{width:6px;background:transparent;margin:0;}}'
            f'QScrollBar::handle:vertical{{background:{T("border")};border-radius:3px;min-height:40px;}}'
            f'QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{{height:0;}}')
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
        # 평균(AVG) 카드 — Σ로 평균 켜면 카드 목록 아래 등장. 흰 스와치 + AVG(n) + 표시토글
        self._avg_card = QFrame(); self._avg_card.setObjectName('measCard')
        _ac = QHBoxLayout(self._avg_card); _ac.setContentsMargins(10, 7, 10, 7); _ac.setSpacing(8)
        self._avg_card_chk = QCheckBox(); self._avg_card_chk.setChecked(True); self._avg_card_chk.setFixedWidth(17)
        self._avg_card_chk.setFocusPolicy(Qt.NoFocus)
        self._avg_card_chk.setToolTip(_tx('Show / hide the average curve'))
        self._avg_card_chk.toggled.connect(self._on_avg_show_toggle)
        # 색은 체크박스가 담당(측정 카드와 동일). 색 변경 = 카드 우클릭.
        self._avg_card_name = QLabel('AVG')
        self._avg_card_cnt = QLabel('')
        _ac.addWidget(self._avg_card_chk)
        _ac.addWidget(self._avg_card_name); _ac.addWidget(self._avg_card_cnt); _ac.addStretch()
        self._avg_card.hide()
        self._avg_card.setCursor(Qt.PointingHandCursor)
        self._avg_card.setToolTip(_tx('Click: select (bring to front) · Right-click: change color'))
        self._avg_card.mousePressEvent = self._avg_card_mouse_press
        self._avg_card.contextMenuEvent = self._avg_card_context
        self._style_avg_card()
        mpl.addWidget(self._avg_card)
        self.sig_out_ch_cb.currentIndexChanged.connect(self._sig_out_ch_changed)
        rl.addWidget(mp, 1)          # 그룹박스가 Signal Generator 아래 남은 세로 공간을 모두 차지
        # 그래프↔우측패널 구분선 — Spectrum infoPanel border-left와 통일(1px)
        self._rp_sep = QFrame(); self._rp_sep.setFrameShape(QFrame.VLine); self._rp_sep.setFixedWidth(1)
        self._rp_sep.setStyleSheet(f'background:{_sep_line_color()};border:none;')
        bl.addWidget(self._rp_sep)
        bl.addWidget(self.rp)
        root.addWidget(body, 1)

        # 하단 툴바
        tb = QWidget(); tb.setFixedHeight(46); tb.setObjectName('tf_tb')
        # N2 리디자인 (Spectrum과 동일 언어) — 테두리리스 + 아이콘 + 모노값 + LED
        tl = QHBoxLayout(tb); tl.setContentsMargins(10,0,10,0); tl.setSpacing(0)
        _H = 34
        def _dv1():
            tl.addSpacing(4); tl.addWidget(_n2_divider()); tl.addSpacing(4)
        _g = QColor(T('accent')); _gr,_gg,_gb = _g.red(),_g.green(),_g.blue()
        self._drawer_btn = _N2IconBtn('panel-left', checkable=True); self._drawer_btn.setFixedHeight(34)
        self._drawer_btn.setChecked(False)
        self._drawer_btn.setToolTip(_tx('Capture drawer'))
        tl.addWidget(self._drawer_btn); tl.addSpacing(4)
        # Start 버튼 — 제너레이터 자동 연동으로 대체(숨김, 코드 참조용). 레이아웃엔 미추가.
        self.start_btn = QPushButton('Start'); _apply_txn(self.start_btn, False)
        self.start_btn.setFixedWidth(92); self.start_btn.setFixedHeight(34)
        self.start_btn.setFocusPolicy(Qt.NoFocus)
        self.start_btn.clicked.connect(self._toggle)
        self.start_btn.hide()
        # ── 측정: ENG(엔진) · FFT · RESP(응답/평균) · SMTH(스무딩) ──
        self.eng_cb = _N2Select('cpu','ENG'); self.eng_cb.setFixedHeight(_H)
        self.eng_cb.addItems(['Single', 'Adaptive'])
        self.eng_cb.setToolTip(_tx('Single = fixed FFT  ·  Adaptive = multi-rate (high-res low end, adaptive resolution per frequency)'))
        self.eng_cb.currentIndexChanged.connect(self._engine_changed); tl.addWidget(self.eng_cb)
        # FFT
        self.fft_cb = _N2Select('audio-lines','FFT',mono=True); self.fft_cb.setFixedHeight(_H)
        self.fft_cb.addItems(TF_FFT_LABELS); self.fft_cb.setCurrentIndex(2)
        self.fft_cb.currentIndexChanged.connect(self._fft_changed); tl.addWidget(self.fft_cb)
        # Response
        self.avg_cb = _N2Select('gauge','RESP'); self.avg_cb.setFixedHeight(_H)
        for _lbl, _sec in zip(TF_AVG_LABELS, TF_AVG_SEC):
            self.avg_cb.addItem(_lbl)
        self.avg_cb.setCurrentIndex(TF_AVG_SEC.index(2))   # 기본 Normal(2s, 대칭)
        self.avg_cb.setToolTip(_tx('Response speed — Fast (quick, sensitive) … Stable (slow, steady).\nHigher values average longer, producing a smoother curve.'))
        self.avg_cb.currentIndexChanged.connect(self._avg_changed); tl.addWidget(self.avg_cb)
        # Smooth
        self.sm_cb = _N2Select('spline','SMTH'); self.sm_cb.setFixedHeight(_H)
        self.sm_cb.addItems(TF_SMOOTH_LABELS); self.sm_cb.setCurrentIndex(5)
        self.sm_cb.currentIndexChanged.connect(self._smooth_changed); tl.addWidget(self.sm_cb)
        _dv1()
        # ── 레벨축: dB (Auto ↔ 수동 고정) ──
        self.db_btn = _N2Button('scale-v','Auto',label='dB'); self.db_btn.setFixedHeight(_H)
        self.db_btn.setToolTip(_tx('dB axis range (click to fix top/bottom)'))
        self.db_btn.clicked.connect(self._tf_db_control)
        tl.addWidget(self.db_btn); self._update_tf_db_btn()
        _dv1()
        # ── 뷰: IR · UNIT(딜레이 단위) · PHASE ──
        self.ir_cb = _N2Select('activity','IR'); self.ir_cb.setFixedHeight(_H)
        self.ir_cb.addItems(TF_IR_MODES); self.ir_cb.setCurrentIndex(0)
        self.ir_cb.currentIndexChanged.connect(self._ir_mode_changed)
        tl.addWidget(self.ir_cb)
        # Units
        self.unit_cb = _N2Select('ruler','UNIT',mono=True); self.unit_cb.setFixedHeight(_H)
        self.unit_cb.addItems(['ms', 'ms·m', 'm'])
        self.unit_cb.setCurrentIndex(('ms', 'both', 'm').index(delay_unit()))
        self.unit_cb.setToolTip(_tx('Delay display units — ms / distance (m) / both (speed of sound 343 m/s, adjustable in Delay Finder advanced settings)'))
        self.unit_cb.currentIndexChanged.connect(self._unit_changed)
        tl.addWidget(self.unit_cb)
        # Phase
        self.phase_cb = _N2Select('waves','PHASE'); self.phase_cb.setFixedHeight(_H)
        self.phase_cb.addItems(TF_PHASE_MODES)
        self.phase_cb.currentIndexChanged.connect(self._phase_mode_changed)
        tl.addWidget(self.phase_cb)
        _dv1()
        # delay_spin: primary 카드의 delay_spin과 동기화 (DelayFinderDialog 호환용, 숨김·레이아웃 미추가)
        self.delay_spin = QDoubleSpinBox()
        self.delay_spin.setRange(-2000,2000); self.delay_spin.setDecimals(2)
        self.delay_spin.setSingleStep(0.5); self.delay_spin.setValue(0.0)
        self.delay_spin.setSuffix(' ms'); self.delay_spin.setFixedWidth(80); self.delay_spin.setFixedHeight(30)
        self.delay_spin.setButtonSymbols(QDoubleSpinBox.NoButtons)
        self.delay_spin.setAlignment(Qt.AlignCenter)
        self.delay_spin.setStyleSheet(ss_input(FS_BODY, RADIUS_CTRL))
        self.delay_spin.hide()
        self.delay_spin.valueChanged.connect(self._on_delay_changed)
        # ── 동작: Find · Capture · Δ · Stable · 🎧 (한 묶음, 파라미터 밖) ──
        self.find_btn = _N2Button('search','Find'); self.find_btn.setFixedHeight(_H)
        self.find_btn.setToolTip(_tx('Find delay for all measurement channels  ·  L'))
        self.find_btn.clicked.connect(self._find_all_delays); tl.addWidget(self.find_btn)
        # Capture
        self.tf_cap_btn = _N2Button('camera','Capture'); self.tf_cap_btn.setFixedHeight(_H)
        self.tf_cap_btn.setToolTip(_tx('Capture current TF snapshot (Mag + Phase + IR)   ·   Shortcut: Space'))
        self.tf_cap_btn.clicked.connect(lambda: self._do_tf_capture(prompt=True)); tl.addWidget(self.tf_cap_btn)
        # Δ / Stable / 🎧 (아이콘 토글/액션)
        self.delta_btn = _N2IconBtn('delta', checkable=True); self.delta_btn.setFixedHeight(_H)
        self.delta_btn.setToolTip(_tx('Delta compare — show difference vs reference capture (set with R)'))
        self.delta_btn.toggled.connect(self._set_delta)
        tl.addWidget(self.delta_btn)
        self.tf_stable_btn = _N2IconBtn('hourglass', checkable=True); self.tf_stable_btn.setFixedHeight(_H)
        self.tf_stable_btn.setToolTip(_tx('Stable capture — auto-capture after average converges + coherence stabilizes'))
        tl.addWidget(self.tf_stable_btn)
        self.auralize_btn = _N2IconBtn('headphones'); self.auralize_btn.setFixedHeight(_H)
        self.auralize_btn.setToolTip(_tx('Auralization — hear music through the measured space (headphones)'))
        self.auralize_btn.clicked.connect(self._open_auralize)
        tl.addWidget(self.auralize_btn)
        # 라이브 멀티마이크 평균 — 클릭 시 팝업(크기/복소·평균만·딜레이정렬). LED=on/off
        self._avg_tb_btn = _N2IconBtn('sigma', checkable=True); self._avg_tb_btn.setFixedHeight(_H)
        self._avg_tb_btn.setToolTip(_tx('Live multi-mic average — combine running mics into one averaged curve'))
        self._avg_tb_btn.toggled.connect(self._on_avg_tb_toggled)
        tl.addWidget(self._avg_tb_btn)
        tl.addStretch()
        # 별도 창 팝아웃 토글 (멀티모니터) — 클릭 연결은 MainWindow가 함
        self._popout_btn = _N2IconBtn('extlink', checkable=True); self._popout_btn.setFixedHeight(_H)
        self._popout_btn.setToolTip(_tx('Pop out to separate window (multi-monitor)'))
        tl.addWidget(self._popout_btn); tl.addSpacing(4)
        # 우측 패널(rp) 표시/숨김 토글 + 저장 상태 복원
        self._tf_panel_btn = _N2IconBtn('panel-right', checkable=True); self._tf_panel_btn.setFixedHeight(_H)
        self._tf_panel_btn.clicked.connect(self._toggle_tf_panel)
        _tpv = bool(self._settings.get('tf_panel_visible', True))
        self._tf_panel_btn.setChecked(_tpv)
        self.rp.setVisible(_tpv); self._rp_sep.setVisible(_tpv)
        tl.addWidget(self._tf_panel_btn)
        self.tb = tb   # MainWindow가 embedded 시 sub_stack에 넣을 수 있도록 저장
        if not self.embedded:
            root.addWidget(tb)
        self._restore_tf_slots()   # 저장된 슬롯 구성 복원(없으면 IR/Phase/Mag 기본)

    # ── TF 플롯 슬롯 (제목 글씨 클릭 → 메뉴) ──────────────────────
    def _tf_slot_menu(self, idx, global_pos):
        from PyQt5.QtWidgets import QMenu
        m = QMenu(self)
        cur = self._tf_slot_plot[idx]
        # 1) 이 칸 내용 바꾸기
        for opt in self._tf_plot_order:
            a = m.addAction(('✓  ' if opt == cur else '     ') + opt)
            a.triggered.connect(lambda _=False, o=opt: self._tf_set_slot(idx, o))
        # 2) 숨겨진(어느 칸에도 없는) 플롯 → 새 칸 추가
        shown = set(p for p in self._tf_slot_plot if p not in (None, 'Off'))
        hidden = [p for p in self._tf_plot_order if p not in shown]
        has_off = any(p == 'Off' for p in self._tf_slot_plot)
        if hidden and has_off:
            m.addSeparator()
            for p in hidden:
                a = m.addAction('＋  Add ' + p)
                a.triggered.connect(lambda _=False, pp=p: self._tf_add_pane(pp))
        # 3) 이 칸 닫기 (최소 1개 유지)
        if len([p for p in self._tf_slot_plot if p not in (None, 'Off')]) > 1:
            m.addSeparator()
            a = m.addAction('✕  Close this pane')
            a.triggered.connect(lambda _=False: self._tf_set_slot(idx, 'Off'))
        m.exec_(global_pos)

    def _tf_add_pane(self, plot):
        """숨겨진 플롯을 비어있는(Off) 칸에 켜서 칸을 늘림."""
        if plot in [p for p in self._tf_slot_plot if p not in (None, 'Off')]:
            return   # 이미 표시 중이면 무시(중복 방지)
        j = next((k for k in range(3) if self._tf_slot_plot[k] == 'Off'), None)
        if j is None:
            return
        self._tf_mount(j, plot)
        self._save_tf_slots()

    def _tf_detach(self, name):
        if name in (None, 'Off'):
            return
        c = self._tf_plots.get(name)
        if c is not None:
            c.setParent(None); c.hide()
        if name == 'RTA':
            self.rta_cvs._rta_range_init = False   # 다시 켤 때 스펙트럼 dB범위 재동기화

    def _tf_mount(self, idx, name):
        c = self._tf_plots[name]
        self._tf_slot_box[idx].addWidget(c); c.setVisible(True)
        self._tf_slot_plot[idx] = name
        self._tf_slot_w[idx].setVisible(True)
        self._tf_slot_hot[idx].raise_()   # 클릭영역을 캔버스 위로

    def _tf_set_slot(self, idx, name):
        """칸 idx의 콘텐츠를 name으로. 다른 칸이 갖고 있으면 스왑. 'Off'면 칸 숨김(최소 1개 유지)."""
        cur = self._tf_slot_plot[idx]
        if name == cur:
            return
        real_on = [p for p in self._tf_slot_plot if p not in (None, 'Off')]
        if name == 'Off':
            if len(real_on) <= 1:                      # 최소 1개 유지
                return
            self._tf_detach(cur)
            self._tf_slot_plot[idx] = 'Off'; self._tf_slot_w[idx].setVisible(False)
            self._save_tf_slots(); return
        other = next((j for j in range(3) if j != idx and self._tf_slot_plot[j] == name), None)
        self._tf_detach(cur)
        if other is not None:
            self._tf_detach(name)
            if cur in (None, 'Off'):                   # 줄 게 없으면 상대 칸은 Off
                self._tf_slot_plot[other] = 'Off'; self._tf_slot_w[other].setVisible(False)
            else:                                       # 스왑: 상대 칸이 cur를 받음
                self._tf_mount(other, cur)
        self._tf_mount(idx, name)
        self._save_tf_slots()

    def _save_tf_slots(self):
        self._settings['tf_slots'] = list(self._tf_slot_plot)
        _save_settings(self._settings)

    def _restore_tf_slots(self):
        slots = self._settings.get('tf_slots')
        if not (isinstance(slots, list) and len(slots) == 3
                and any(p in self._tf_plots for p in slots)):
            slots = ['Live IR', 'Phase', 'Magnitude']   # 기본(현행)
        # 중복 플롯은 첫 칸만 인정, 나머지는 Off
        seen = set()
        for i, p in enumerate(slots):
            if p in self._tf_plots and p not in seen:
                seen.add(p); self._tf_mount(i, p)
            else:
                self._tf_slot_plot[i] = 'Off'; self._tf_slot_w[i].setVisible(False)

    def eventFilter(self, obj, event):
        # TF 분석창(IR/Phase/Mag) 클릭 → 그 창 선택 하이라이트
        if event.type() == QEvent.MouseButtonPress and obj in getattr(self, '_tf_cvs_list', ()):
            self._select_tf_cvs(obj)
        return super().eventFilter(obj, event)

    def _select_tf_cvs(self, cvs):
        for c in self._tf_cvs_list:
            sel = (c is cvs)
            if getattr(c, '_tf_selected', False) != sel:
                c._tf_selected = sel; c.update()

    # ── 장치 로드 ────────────────────────────
    def _load_devices(self):
        import threading, queue as _q
        result = _q.Queue()
        def _q_fn():
            try: result.put(('ok', sd.query_devices()))
            except Exception as e: result.put(('err', str(e)))
        _internal_sigg_label = 'Internal (SigGen)'   # evaluate before 't' is shadowed by Thread
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
            self.ref_cb.addItem(_internal_sigg_label, None)
            _pref = _win_preferred_hostapi()   # Windows: WASAPI만(중복 호스트API 제거), 그 외 None=전체
            if _pref is not None:
                _diag('audio_hostapi', tab='tf', wasapi_idx=_pref)
            for i, d in enumerate(payload):
                if not _dev_hostapi_ok(d, _pref): continue
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
                    if not _dev_hostapi_ok(d, _pref): continue
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
        _diag('tf_reconfig', analysis=analysis, playing=playing,
              ref=self.ref_cb.currentData(), ref_ch=self.ref_ch_cb.currentData(),
              meas=self.meas_cb.currentData(), meas_ch=self.meas_ch_cb.currentData())
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

    def _on_avg_tb_toggled(self, on):
        """툴바 Σ = 평균 on/off. 켜면 즉시 시작 + AVG 카드 등장 + 마이크 선택 팝업 표시.
        켤 때 아직 아무 마이크도 안 골랐으면 현재 카드 전부 자동 포함 → '평균 켜기'가 바로 동작."""
        self._avg_on = bool(on)
        if self._avg_on:
            self._auto_include_all_mics()
        self._update_avg_card()
        _diag('tf_avg_toggle', on=self._avg_on, mode=self._avg_mode)
        if self._avg_on:
            self._open_avg_popup()
        elif hasattr(self, '_avg_popup'):
            self._avg_popup.hide()
        self._request_avg_render()

    def _auto_include_all_mics(self):
        """툴바 Σ ON 시, 아직 아무 마이크도 선택 안 됐으면 모든 카드를 평균에 자동 포함.
        렌더가 데이터(acc n≥3 / _last_primary_H) 유무로 실제 참여를 게이트하므로, 아직 Start
        안 한 카드를 포함해도 무해(데이터 생기면 자동 합류). 사용자가 이미 고른 게 있으면 존중."""
        cards = list(getattr(self, '_level_cards', []) or [])
        if not cards or any(getattr(c, 'in_average', False) for c in cards):
            return
        for c in cards:
            c.in_average = True
            if hasattr(c, '_avg_chk'):
                c._avg_chk.blockSignals(True); c._avg_chk.setChecked(True); c._avg_chk.blockSignals(False)
            if hasattr(c, '_update_avg_chk_icon'):
                c._update_avg_chk_icon()

    def _on_card_avg_include(self, card_id, included):
        """카드 헤더 Σ 아이콘 토글 → 평균 참여. 마스터가 꺼져 있으면 자동으로 켜서
        per-card Σ 단독으로도 평균이 바로 뜨게(예전엔 시그널 미연결로 아무 반응 없었음)."""
        if included and not getattr(self, '_avg_on', False):
            self._avg_on = True
            if hasattr(self, '_avg_tb_btn'):
                self._avg_tb_btn.blockSignals(True); self._avg_tb_btn.setChecked(True); self._avg_tb_btn.blockSignals(False)
            self._update_avg_card()
        # 팝업이 열려 있으면 체크 상태 동기
        if getattr(self, '_avg_popup', None) is not None and self._avg_popup.isVisible():
            self._rebuild_avg_mic_list()
        self._request_avg_render()

    def _style_avg_card(self):
        if not hasattr(self, '_avg_card'): return
        _bg = '#1E1E22' if is_dark() else '#F3F5FA'
        _bd = '#34343B' if is_dark() else T('border')
        col = self._avg_curve_color()
        if getattr(self, '_avg_card_selected', False):   # 선택 = 색 틴트 채움(마이크 카드와 동일)
            _c = QColor(col); _bd_s = '#4A4A54' if is_dark() else T('accent')
            self._avg_card.setStyleSheet(
                f'QFrame#measCard{{border:1px solid {_bd_s};border-radius:10px;'
                f'background:rgba({_c.red()},{_c.green()},{_c.blue()},20);padding:2px;}}')
        else:
            self._avg_card.setStyleSheet(
                f'QFrame#measCard{{border:1px solid {_bd};border-radius:10px;background:{_bg};padding:2px;}}')
        self._avg_card_name.setStyleSheet(
            f'color:{T("text")};background:transparent;font-size:{FS_BODY}px;font-weight:bold;')
        self._avg_card_cnt.setStyleSheet(
            f'color:{T("text_dim")};background:transparent;font-size:{FS_SM}px;')
        _chk_col = col   # 곡선 색 = 체크박스 색(측정 카드와 동일). 색 변경은 우클릭.
        self._avg_card_chk.setStyleSheet(
            f'QCheckBox::indicator{{width:13px;height:13px;border:1.5px solid {_chk_col};'
            f'border-radius:3px;background:transparent;}}'
            f'QCheckBox::indicator:checked{{background:{_chk_col};image:none;}}')

    def _on_avg_show_toggle(self, on):
        self._avg_show = bool(on)
        self._request_avg_render()

    def _update_avg_card(self):
        if hasattr(self, '_avg_card'):
            self._avg_card.setVisible(bool(self._avg_on))

    def _avg_card_mouse_press(self, e):
        if e.button() == Qt.LeftButton:
            self._select_avg_card()

    def _avg_card_context(self, e):
        from PyQt5.QtWidgets import QMenu
        m = QMenu(self)   # 앱 전역 QMenu 다크 스타일 상속(_global_popup_qss)
        m.addAction(_tx('Change color…'), self._pick_avg_color)
        m.exec_(e.globalPos())

    def _select_avg_card(self):
        """AVG 카드 선택 → 틴트 + 다른 카드 선택 해제 + 평균곡선 맨앞 굵게."""
        self._avg_card_selected = True
        for c in self._level_cards:
            if hasattr(c, 'set_selected'): c.set_selected(False)
        for p in getattr(self, '_extra_pairs', []):
            card = p.get('card')
            if card is not None and hasattr(card, 'set_selected'): card.set_selected(False)
        self._style_avg_card()
        self._request_avg_render()

    def _pick_avg_color(self):
        init = QColor(self._avg_curve_color())
        c = QColorDialog.getColor(init, self, _tx('Average curve color'))
        if c.isValid():
            self._avg_color = c.name()
            self._style_avg_card(); self._request_avg_render()

    def _style_avg_popup(self):
        if not hasattr(self, '_avg_popup'): return
        self._avg_popup.setStyleSheet(
            f'#avgPop{{background:{T("bg2")};border:1px solid {T("border")};border-radius:12px;}}')

    def _rebuild_avg_mic_list(self):
        """팝업 열 때 현재 측정 카드로 마이크 체크리스트 재구성(카드 avg 상태 반영·동기)."""
        if not hasattr(self, '_avg_mic_lay'): return
        lay = self._avg_mic_lay
        while lay.count():
            it = lay.takeAt(0); wdg = it.widget()
            if wdg is not None: wdg.setParent(None)
        entries = []   # (card, num, dev, ch)
        if getattr(self, '_level_cards', None):
            pc = self._level_cards[0]
            dev = self._strip_star(self.meas_cb.currentText()) if hasattr(self, 'meas_cb') else ''
            ch = self.meas_ch_cb.currentText() if hasattr(self, 'meas_ch_cb') else ''
            num = pc._num_label.text() if hasattr(pc, '_num_label') else '1'
            entries.append((pc, num, dev, ch))
        for p in getattr(self, '_extra_pairs', []):
            card = p.get('card')
            if card is None: continue
            dev = self._strip_star(p['meas_cb'].currentText()) if p.get('meas_cb') else ''
            ch = p['meas_ch_cb'].currentText() if p.get('meas_ch_cb') else ''
            num = card._num_label.text() if hasattr(card, '_num_label') else str(p.get('num', ''))
            entries.append((card, num, dev, ch))
        if not entries:
            hint = QLabel(_tx('No measurement cards'))
            hint.setStyleSheet(f'color:{T("text_dim")};background:transparent;font-size:{FS_SM}px;')
            lay.addWidget(hint); return
        for card, num, dev, ch in entries:
            col = getattr(card, '_color', T('accent'))   # 체크박스 = 마이크 카드 색
            chk_ss = (f'QCheckBox::indicator{{width:13px;height:13px;border:1.5px solid {col};'
                      f'border-radius:3px;background:transparent;}}'
                      f'QCheckBox::indicator:checked{{background:{col};image:none;}}'
                      f'QCheckBox{{spacing:0px;}}')
            row = QWidget(); rl = QHBoxLayout(row)
            rl.setContentsMargins(0, 0, 0, 0); rl.setSpacing(8)
            cb = QCheckBox(); cb.setChecked(bool(getattr(card, 'in_average', False)))
            cb.setStyleSheet(chk_ss); cb.setFixedWidth(18); cb.setFocusPolicy(Qt.NoFocus)
            txt = f'{num}   {dev}' + (f'  {ch}' if ch else '')
            lbl = QLabel(txt.strip())
            lbl.setStyleSheet(f'color:{T("text")};background:transparent;font-size:{FS_SM}px;')
            cb.toggled.connect(lambda on, c=card: self._avg_pick_mic(c, on))
            rl.addWidget(cb); rl.addWidget(lbl, 1)
            lay.addWidget(row)

    def _avg_pick_mic(self, card, on):
        card.in_average = bool(on)
        if hasattr(card, '_avg_chk'):
            card._avg_chk.setChecked(bool(on))   # 카드 헤더 avg 토글과 동기
        self._request_avg_render()

    def _open_avg_popup(self):
        """툴바 Σ 버튼 아래로 라이브 평균 팝업 표시(평소 숨김 → 찾아서 켜기)."""
        if not hasattr(self, '_avg_popup'): return
        self._rebuild_avg_mic_list()
        pop = self._avg_popup; pop.adjustSize()
        btn = self._avg_tb_btn
        gp = btn.mapToGlobal(QPoint(0, btn.height() + 5))
        # 오른쪽 화면 밖으로 안 나가게 클램프
        try:
            scr = QApplication.screenAt(gp) or QApplication.primaryScreen()
            avail = scr.availableGeometry()
            x = min(gp.x(), avail.right() - pop.width() - 8)
            x = max(x, avail.left() + 8)
            gp.setX(x)
        except Exception:
            pass
        pop.move(gp); pop.show(); pop.raise_()

    def _request_avg_render(self):
        # 라이브 중이면 다음 렌더 틱의 _render_average가 반영. 정지 상태에서는 렌더 루프가
        # 안 돌아 오버레이가 갱신/삭제되지 않으므로(토글 OFF·마이크 변경이 화면에 안 먹힘),
        # 여기서 마지막 그리드로 직접 재계산. 없으면 오버레이만 지운다.
        if not getattr(self, '_running', False):
            _f = getattr(self, '_last_avg_freqs', None)
            if _f is not None:
                self._render_average(_f, getattr(self, '_last_avg_t_ms', None))
            else:
                for cvs in (getattr(self, 'mag_cvs', None), getattr(self, 'phase_cvs', None),
                            getattr(self, 'ir_cvs', None)):
                    if cvs is not None and hasattr(cvs, 'clear_tf_average'): cvs.clear_tf_average()
        for cvs in (getattr(self, 'mag_cvs', None), getattr(self, 'phase_cvs', None),
                    getattr(self, 'ir_cvs', None)):
            if cvs is not None: cvs.update()

    def _sig_out_ch_changed(self, _=None):
        """출력 채널 콤보 변경: 저장 + 재생 중이면 반영.
        같은 장치 standalone 스트림이 살아있으면 → 재시작 없이 가변 참조만 갱신(무끊김).
        그 외(듀플렉스/정지)는 기존 stop→start 경로."""
        if getattr(self, '_restoring_devices', False):
            self._save_tf_devices(); return
        new_ch1 = self.sig_out_ch_cb.currentData() or 0
        new_ch2 = self.sig_out_ch2_cb.currentData()   # None = Off
        # 무끊김 경로: standalone 출력 스트림이 살아있을 때 (디바이스 전체 채널로 열려있어 어느 채널이든 안전)
        if self._sig_stream is not None and getattr(self, '_sig_out_ch_ref', None) is not None:
            self._sig_out_ch_ref[0] = new_ch1
            self._sig_out_ch_ref[1] = new_ch2
            self._save_tf_devices()
            _diag('sig_out_ch', ch1=new_ch1, ch2=new_ch2, restarted=False, seamless=True)
            return
        sig_was_playing = getattr(self, 'sig_on_btn', None) and self.sig_on_btn.isChecked()
        if sig_was_playing:
            self._stop_sig_gen()
        self._save_tf_devices()
        if sig_was_playing:
            self._start_sig_gen()
        _diag('sig_out_ch', ch1=new_ch1, ch2=new_ch2, restarted=bool(sig_was_playing), seamless=False)

    @staticmethod
    def _strip_star(txt):
        return txt[2:] if txt.startswith('★ ') else txt

    # ── 상태 직렬화 (get_state / apply_state) ─────────────────────────────
    def _select_combo_by_name(self, cb, name):
        """장치 콤보에서 표시텍스트(★ 제거)가 name 과 같은 항목 선택. 성공 True."""
        if not name: return False
        for i in range(cb.count()):
            if self._strip_star(cb.itemText(i)) == name:
                cb.setCurrentIndex(i); return True
        return False

    def _active_gen(self):
        for key, btn in (('pink', self.sig_pink_btn), ('white', self.sig_white_btn),
                         ('sine', self.sig_sine_btn), ('sweep', self.sig_sweep_btn),
                         ('file', self.sig_file_btn)):
            if btn.isChecked(): return key
        return 'none'

    def get_state(self):
        return {
            'engine': self.eng_cb.currentIndex(), 'fft': self.fft_cb.currentIndex(),
            'response': self.avg_cb.currentIndex(), 'smooth': self.sm_cb.currentIndex(),
            'tf_avg_on': self._avg_on, 'tf_avg_color': self._avg_color,
            'tf_avg_primary': (self._level_cards[0].in_average if getattr(self, '_level_cards', None) else False),
            'ir': self.ir_cb.currentIndex(), 'phase': self.phase_cb.currentIndex(),
            'units': self.unit_cb.currentIndex(),
            'gen': self._active_gen(), 'sine_freq': float(self._sine_freq),
            'sweep': [float(self._sweep_f_lo), float(self._sweep_f_hi),
                      float(self._sweep_dur), bool(self._sweep_asc)],
            'level': float(self.sig_lvl_sp.value()),
            'ref_dev': self._strip_star(self.ref_cb.currentText()), 'ref_ch': self.ref_ch_cb.currentData() or 0,
            'meas_dev': self._strip_star(self.meas_cb.currentText()), 'meas_ch': self.meas_ch_cb.currentData() or 0,
            'out_dev': self._strip_star(self.sig_out_cb.currentText()), 'out_ch': self.sig_out_ch_cb.currentData() or 0,
            'out_ch2': self.sig_out_ch2_cb.currentData(),
            'slots': list(self._tf_slot_plot), 'panel': bool(self.rp.isVisible()),
            'extra_pairs': [{
                'meas_device': self._strip_star(p['meas_cb'].currentText()) if p.get('meas_cb') else '',
                'meas_ch': (p['meas_ch_cb'].currentData()
                            if (p.get('meas_ch_cb') and p['meas_ch_cb'].currentData() is not None) else 0),
                'delay_ms': float(p.get('delay_ms', 0.0)),
                'name': p.get('name', ''), 'num': p.get('num', 2),
                'in_average': (p.get('card').in_average if p.get('card') else False),
            } for p in self._extra_pairs],
        }

    def apply_state(self, d):
        def _idx(key, cb):
            try:
                if key in d: cb.setCurrentIndex(int(d[key]))
            except Exception: pass
        _idx('engine', self.eng_cb); _idx('fft', self.fft_cb); _idx('response', self.avg_cb)
        _idx('smooth', self.sm_cb); _idx('ir', self.ir_cb); _idx('phase', self.phase_cb); _idx('units', self.unit_cb)
        self._avg_on = bool(d.get('tf_avg_on', False))
        self._avg_color = d.get('tf_avg_color', None)
        if hasattr(self, '_avg_tb_btn'):
            self._avg_tb_btn.setChecked(self._avg_on)
        self._update_avg_card()
        if hasattr(self, '_avg_card'): self._style_avg_card()
        if self._level_cards and hasattr(self._level_cards[0], '_avg_chk'):
            self._level_cards[0]._avg_chk.setChecked(bool(d.get('tf_avg_primary', False)))
        try:
            g = d.get('gen', 'none')
            btnmap = {'pink': self.sig_pink_btn, 'white': self.sig_white_btn, 'sine': self.sig_sine_btn,
                      'sweep': self.sig_sweep_btn, 'file': self.sig_file_btn}
            # 스윕(1-shot 특수모드)·File(파일 버퍼는 영속 안 됨 → 켜져도 무동작)은 복원 안 함 → 핑크로.
            if g in ('sweep', 'file') or g not in btnmap:
                g = 'pink'
            for _b in btnmap.values(): _b.setChecked(False)   # 상호배타 — 나머지 해제(둘 다 켜짐 버그 방지)
            btnmap[g].setChecked(True)
        except Exception: pass
        try:
            if 'sine_freq' in d: self._sine_freq = float(d['sine_freq'])
            if 'sweep' in d and len(d['sweep']) == 4:
                self._sweep_f_lo, self._sweep_f_hi, self._sweep_dur, self._sweep_asc = (
                    float(d['sweep'][0]), float(d['sweep'][1]), float(d['sweep'][2]), bool(d['sweep'][3]))
            if 'level' in d: self.sig_lvl_sp.setValue(float(d['level']))
        except Exception: pass
        # 장치/채널 — 이름 매칭되면 적용(없으면 현재 유지). 채널은 device 변경 후 데이터로 매칭.
        for dev_key, cb, ch_key, ch_cb in (
            ('ref_dev', self.ref_cb, 'ref_ch', self.ref_ch_cb),
            ('meas_dev', self.meas_cb, 'meas_ch', self.meas_ch_cb),
            ('out_dev', self.sig_out_cb, 'out_ch', self.sig_out_ch_cb)):
            try:
                if d.get(dev_key) and self._select_combo_by_name(cb, d[dev_key]):
                    for i in range(ch_cb.count()):
                        if ch_cb.itemData(i) == d.get(ch_key):
                            ch_cb.setCurrentIndex(i); break
            except Exception: pass
        try:
            if d.get('out_ch2') is not None:
                for i in range(self.sig_out_ch2_cb.count()):
                    if self.sig_out_ch2_cb.itemData(i) == d['out_ch2']:
                        self.sig_out_ch2_cb.setCurrentIndex(i); break
        except Exception: pass
        try:
            if 'extra_pairs' in d and isinstance(d['extra_pairs'], list):
                self._apply_extra_pairs(d['extra_pairs'])
        except Exception: pass
        try:
            if 'slots' in d:
                for i, name in enumerate(d['slots'][:len(self._tf_slot_plot)]):
                    self._tf_set_slot(i, name) if hasattr(self, '_tf_set_slot') else None
        except Exception: pass
        try:
            if 'panel' in d and bool(d['panel']) != self.rp.isVisible(): self._toggle_tf_panel()
        except Exception: pass

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

    def _persist_tf_db(self):
        """TF Magnitude dB축 수동 고정 상태 저장 (재시작 유지). MainWindow와 _settings 공유."""
        self._settings['tf_db_lock'] = bool(self.mag_cvs._db_lock)
        self._settings['tf_db_top']  = float(self.mag_cvs.db_max)
        self._settings['tf_db_bot']  = float(self.mag_cvs.db_min)
        _save_settings(self._settings)

    def _on_tf_db_change(self):
        self._persist_tf_db(); self._update_tf_db_btn()

    def _tf_db_control(self):
        """툴바 dB 버튼 클릭 → 범위 대화상자 (자동/적용·고정)."""
        c = self.mag_cvs
        r = _ask_db_range(self, c.db_max, c.db_min)
        if r == 'auto':      c._db_autofit()
        elif r is not None:  c._db_apply(r[0], r[1])

    def _update_tf_db_btn(self):
        if not hasattr(self, 'db_btn'): return
        c = self.mag_cvs
        self.db_btn.setText(f'{c.db_max:+g} / {c.db_min:+g}' if c._db_lock else _tx('Auto'))
        if isinstance(self.db_btn, _N2Button):
            self.db_btn.set_active(c._db_lock)
        else:
            self.db_btn.setStyleSheet(_db_ctrl_btn_style(c._db_lock))

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
                'color': p.get('color', ''),
                'in_average': (p.get('card').in_average if p.get('card') else False),
            })
        self._settings['tf_extra_pairs'] = pairs
        self._settings['tf_primary_name'] = getattr(self, '_tf_primary_name', '')
        self._settings['tf_primary_color'] = getattr(self, '_tf_primary_color', '') or ''
        _save_settings(self._settings)

    def _populate_extra_pair(self, pair, entry):
        """추가 카드(pair) 하나에 저장된 장치/채널/딜레이/이름/번호를 채움."""
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
        saved_col = entry.get('color')
        if saved_col:
            pair['color'] = saved_col
            pair['card'].set_color(saved_col)
        if entry.get('in_average'):
            pair['card']._avg_chk.setChecked(True)

    def _restore_tf_extra_pairs(self):
        """시작 시 저장된 추가 카드들을 재생성·복원 (1회). _load_devices 이후 호출."""
        saved = self._settings.get('tf_extra_pairs', [])
        if not saved: return
        self._restoring_devices = True
        try:
            for entry in saved:
                self._tf_add_pair()                 # 카드+pair 생성 (현재 장치 목록 복사)
                self._populate_extra_pair(self._extra_pairs[-1], entry)
        finally:
            self._restoring_devices = False

    def _apply_extra_pairs(self, entries):
        """프리셋/세션 적용: 추가 카드 개수+설정을 entries 에 맞춰 재구성."""
        was_running = self._running
        self._restoring_devices = True
        try:
            while self._extra_pairs:                 # 기존 카드 전부 제거
                self._tf_remove_pair(len(self._extra_pairs) - 1)
            for entry in (entries or []):            # entries 만큼 재생성
                self._tf_add_pair()
                self._populate_extra_pair(self._extra_pairs[-1], entry)
        finally:
            self._restoring_devices = False
        self._save_tf_extra_pairs()                  # 세션 자동기억도 갱신
        if was_running:                              # 실행 중이었으면 한 번만 재시작
            self._stop(); self._start()

    # ── 시작/정지 ────────────────────────────
    def _toggle(self):
        try:
            if self._running: self._stop()
            else: self._start()
        except Exception as e:
            from PyQt5.QtWidgets import QMessageBox
            _BrandBox.warning(self, _tx('Error'), _tx('Audio start failed:\n{e}').format(e=e))

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
                        blocksize=2048, callback=_make_cb('ref', ref_ch),
                        extra_settings=_win_extra_settings())
                    self._mon_ref_stream.start()
        except Exception as e:
            _alog.warning(f'Mon ref stream failed: {e}')
        try:
            if meas_idx is not None:
                nch = meas_ch + 1
                with _no_stderr():
                    self._mon_meas_stream = sd.InputStream(
                        device=meas_idx, channels=nch, samplerate=sr,
                        blocksize=2048, callback=_make_cb('meas', meas_ch),
                        extra_settings=_win_extra_settings())
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

    # ── 입력 레벨 모니터 (분석 중인 카드 있을 때만 meter 표시) ─────────────
    def _stop_input_monitor(self):
        for th in list(getattr(self, '_monitor_threads', {}).values()):
            try: th.chunk_ready.disconnect(); th.error_signal.disconnect()
            except Exception: pass
            try: th.stop()
            except Exception: pass
        self._monitor_threads = {}; self._monitor_chmap = {}

    def _refresh_input_monitor(self):
        """[비활성화] 별도 모니터 입력 스트림은 같은 장치의 출력/분석 스트림과 CoreAudio 충돌을
        일으켜 사용하지 않음. 카드 레벨미터는 그 카드를 Start(분석) 했을 때만 표시 — 제너레이터와 무관."""
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
        card.avg_include_toggled.connect(self._on_card_avg_include)
        card.color_changed.connect(lambda col, c=card: self._on_extra_color_changed(c, col))
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
        _diag('tf_add_pair', count=len(self._extra_pairs))

    def _on_tf_renamed(self, card, txt):
        """카드 이름 변경 — card=None 이면 primary, 아니면 해당 extra pair."""
        if card is None:
            self._tf_primary_name = txt
        else:
            for p in self._extra_pairs:
                if p.get('card') is card: p['name'] = txt; break
        self._save_tf_extra_pairs()

    def _apply_primary_color(self, col, save=True):
        """primary(1번) 곡선 색 적용 — 3캔버스 라이브색 + 카드 헤더 + (옵션)저장."""
        self._tf_primary_color = col or ''
        _lc = col or None   # ''(기본) → None = 캔버스가 T('green') 사용
        for cv in (self.mag_cvs, self.phase_cvs, self.ir_cvs):
            cv._live_color = _lc; cv.update()
        if self._level_cards and col:
            self._level_cards[0].set_color(col)
        if save:
            self._save_tf_extra_pairs()

    def _on_primary_color_changed(self, col):
        """primary 카드 우클릭 → 색 변경. 카드 set_color 는 카드 자체를 이미 갱신했으므로 캔버스만."""
        self._apply_primary_color(col)

    def _on_extra_color_changed(self, card, col):
        """추가 카드 우클릭 → 색 변경. pair 색 갱신 → 다음 렌더가 그 색으로 그림 + 저장."""
        for p in self._extra_pairs:
            if p.get('card') is card:
                p['color'] = col; break
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
        # 브랜드 헤더(팝아웃 타이틀바) 배경/워드마크 — 라이트에서 검게 남던 문제 수정
        if hasattr(self, '_hdr'):
            self._hdr.setStyleSheet(f'#tfBrandHdr{{background:{T("bg2")};}}')
        if hasattr(self, '_hdr_logo'):
            self._hdr_logo.setText(_brand_logo_html('Transfer Function'))
        # TF 툴바 토글 버튼(델타/스테이블/팝아웃) 테마 재적용
        for _btn in (getattr(self, 'delta_btn', None),
                     getattr(self, 'tf_stable_btn', None),
                     getattr(self, '_popout_btn', None)):
            if _btn is not None:
                _btn.setStyleSheet(_popout_toggle_ss())
        if hasattr(self, '_cards_scroll'):
            self._cards_scroll.setStyleSheet(
                f'QScrollArea{{background:transparent;border:none;}}'
                f'QScrollBar:vertical{{width:6px;background:transparent;margin:0;}}'
                f'QScrollBar::handle:vertical{{background:{T("border")};border-radius:3px;min-height:40px;}}'
                f'QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{{height:0;}}')
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
        if getattr(self, '_avg_card_selected', False):   # 마이크 카드 선택 → AVG 카드 선택 해제
            self._avg_card_selected = False
            if hasattr(self, '_avg_card'): self._style_avg_card()
            self._request_avg_render()
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
        _diag('tf_remove_pair', count=len(self._extra_pairs))
        if self._running and not getattr(self, '_restoring_devices', False):
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

    def _resolve_shared_sr(self):
        """TF가 구독할 장치의 SR을 결정 — 공유 엔진이 이미 연 장치면 그 SR을 따르고(합의),
        아니면 장치 네이티브 SR로 맞춘다. Spectrum이 장치를 44100으로 먼저 열었는데 TF가
        48000으로 구독하려다 'one SR per device' 오류가 나던 것을 방지(특히 Windows:
        WASAPI 네이티브 44100). MTW는 SR 변경 시 자동 재생성되고 fft_size는 SR 무관이라 안전."""
        devs = []
        for cb in (getattr(self, 'meas_cb', None), getattr(self, 'ref_cb', None)):
            d = cb.currentData() if cb is not None else None
            if isinstance(d, int) and d >= 0: devs.append(d)
        for pair in getattr(self, '_extra_pairs', []):
            mcb = pair.get('meas_cb')
            d = mcb.currentData() if mcb is not None else None
            if isinstance(d, int) and d >= 0: devs.append(d)
        # 1) 이미 열린 장치의 SR이 있으면 그걸 따른다(먼저 연 탭과 합의)
        for d in devs:
            sr = self._engine.current_sr(d)
            if sr:
                if sr != self.sample_rate:
                    _diag('tf_sr_adopt', dev=d, sr=sr, was=self.sample_rate)
                    self.sample_rate = sr
                return
        # 2) 아니면 첫 후보 장치의 네이티브 SR로 맞춤
        _OK = (44100, 48000, 88200, 96000)
        for d in devs:
            try:    ns = int(sd.query_devices(d)['default_samplerate'])
            except Exception: continue
            sr = ns if ns in _OK else (48000 if ns >= 48000 else 44100)
            if sr != self.sample_rate:
                _diag('tf_sr_native', dev=d, sr=sr, was=self.sample_rate)
                self.sample_rate = sr
            return

    def _start(self):
        self._sweep_freeze = False  # 새 측정 시작 → 라이브 렌더 동결 해제
        self._mtw_live_logged = False  # Start마다 'mtw_live' 1회 재기록(분석 살아남 검증 마커)
        self._resolve_shared_sr()  # 공유 장치 SR 합의(엔진 'one SR per device' 충돌 방지)
        self.mag_cvs.arm_autofit()  # 첫 측정 데이터에 Y축 1회 자동맞춤(더블클릭 없이 바로 보임)
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
                                                    force_latency=('high' if dev == self.sig_out_cb.currentData() else None))
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
                    self.sig_on_btn.setChecked(True); self.sig_on_btn.setText('Stop'); self._style_sig_play(True)
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
                                                    force_latency=('high' if dev == self.sig_out_cb.currentData() else None))
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

            # [DIAG] 멀티카드 분석 경로 셋업 요약 (HW검증: 카드2 미분석 추적)
            try:
                _pairs_dbg = [{'i': _i, 'disp': _p.get('display', False),
                               'mdev': _p['meas_cb'].currentData(), 'mch': _p['meas_ch_cb'].currentData()}
                              for _i, _p in enumerate(self._extra_pairs)]
                _mc_dbg = {_d: [(_r.get('pair_idx') if _r.get('pair_idx') is not None
                                 else f"refonly{_r.get('_ref_only_pair')}") for _r in _rt]
                           for _d, (_, _rt) in self._mc_threads.items()}
                _diag('tf_card_setup', ref=ref_idx, rch=ref_ch,
                      pairs=_pairs_dbg, mc=_mc_dbg,
                      extra_th=[_t != (None, None, None) for _t in self._extra_pair_threads])
            except Exception as _e:
                _alog.debug(f'tf_card_setup diag err: {_e}')

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
        # MTW DSP 워커 정리 — in-flight 계산 대기 후 종료(다음 Start 시 지연 재생성)
        if self._dsp_exec is not None:
            self._dsp_sync()
            try: self._dsp_exec.shutdown(wait=False)
            except Exception: pass
            self._dsp_exec = None; self._dsp_future = None; self._dsp_out = None
            _diag('tf_dsp_worker', state='stop')
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
        rms = float(np.sqrt(np.mean(buf ** 2)))
        if self._tf_engine_mtw:
            # MTW(Internal Loopback/분리 콜백 경로): 시간영역 버퍼만 보관, 콜백 FFT 생략
            with QMutexLocker(self._mutex):
                self._last_ref_buf = buf; self._last_ref_rms = rms
            return
        n = len(buf)
        if not hasattr(self, '_hann_win') or self._hann_win is None or len(self._hann_win) != n:
            self._hann_win = np.hanning(n).astype(np.float32)
        win = self._hann_win
        fft = np.fft.rfft(buf * win).astype(complex)
        with QMutexLocker(self._mutex):
            self._last_ref_fft = fft; self._last_ref_rms = rms

    def _on_meas(self, buf):
        rms = float(np.sqrt(np.mean(buf ** 2)))
        # 분리 콜백 경로(Internal SigGen ref / 다른장치 ref): ref·meas가 캡처 시 정렬 안 됨
        # → 렌더에서 딜레이 정렬 필요. (_on_frame 경로만 True)
        self._primary_upstream_aligned = False
        if self._tf_engine_mtw:
            with QMutexLocker(self._mutex):
                self._last_meas_buf = buf; self._last_meas_rms = rms
        else:
            if not hasattr(self, '_hann_win') or self._hann_win is None or len(self._hann_win) != len(buf):
                self._hann_win = np.hanning(len(buf)).astype(np.float32)
            win = self._hann_win
            fft = np.fft.rfft(buf * win).astype(complex)
            with QMutexLocker(self._mutex):
                self._last_meas_fft = fft; self._last_meas_rms = rms
        # Primary 카드 M 레벨 즉시 업데이트 — 체크박스(가시) ON 이면 표시 (Start/Stop 무관)
        if (self._level_cards and self._level_cards[0].is_graph_visible() and rms > 1e-9):
            self._level_cards[0].set_meas(20 * _math.log10(rms))

    @staticmethod
    def _align_pair(ref, meas, D):
        """시간영역 딜레이 정렬(Smaart 방식). 측정이 ref보다 D샘플 늦음(D>0) → ref를 D 지연
        (앞에 0 채움)시켜 ref/meas를 정렬. D<0(측정이 앞섬)이면 meas를 지연. 길이 유지(엔진/누적
        고정크기) — 최신 윈도우는 실샘플이라 magnitude·coherence가 정렬 기준으로 정확. [DELAY_TIME_ALIGN]"""
        if D > 0:
            ref = np.concatenate([np.zeros(D, dtype=ref.dtype), ref])[:len(ref)]
        elif D < 0:
            meas = np.concatenate([np.zeros(-D, dtype=meas.dtype), meas])[:len(meas)]
        return ref, meas

    def _on_frame(self, ref_buf, meas_buf):
        # TFSyncThread/TFDuplexThread: 두 채널을 동일 콜백에서 수신 → ΔT=0 원자 처리
        n = len(ref_buf)
        rms_r = float(np.sqrt(np.mean(ref_buf ** 2)))
        rms_m = float(np.sqrt(np.mean(meas_buf ** 2)))
        # 딜레이 시간영역 정렬 — magnitude/coherence가 딜레이 적용 즉시 올바른 레벨로(위상만 아니라).
        # delay=0 이면 no-op(기존과 완전 동일). 잔여 sub-sample 위상은 표시단(_render_primary_H)서.
        _D = int(round(self.delay_ms / 1000.0 * self.sample_rate)) if self.delay_ms else 0
        if _D != 0 and abs(_D) < n:
            ref_a, meas_a = self._align_pair(ref_buf, meas_buf, _D)
        else:
            ref_a, meas_a = ref_buf, meas_buf
        self._primary_upstream_aligned = True   # _on_frame 경로: 정수 딜레이 이미 정렬됨
        if self._tf_engine_mtw:
            # MTW: 시간영역 버퍼만 보관 (엔진이 자체 멀티레이트 FFT 수행) — 콜백 FFT 생략
            with QMutexLocker(self._mutex):
                self._last_ref_buf = ref_a; self._last_ref_rms = rms_r
                self._last_meas_buf = meas_a; self._last_meas_rms = rms_m
        else:
            # Hanning window 캐시 — 매 콜백마다 재생성 금지
            if not hasattr(self, '_hann_win') or self._hann_win is None or len(self._hann_win) != n:
                self._hann_win = np.hanning(n).astype(np.float32)
            win = self._hann_win
            fft_r = np.fft.rfft(ref_a * win).astype(complex)
            fft_m = np.fft.rfft(meas_a * win).astype(complex)
            with QMutexLocker(self._mutex):
                self._last_ref_fft = fft_r; self._last_ref_rms = rms_r
                self._last_meas_fft = fft_m; self._last_meas_rms = rms_m
        # Primary 카드 레벨 직접 업데이트 — 체크박스(가시) ON 이면 표시 (Start/Stop 무관)
        if (hasattr(self, '_level_cards') and self._level_cards and self._level_cards[0].is_graph_visible()):
            pc = self._level_cards[0]
            pk_m = float(np.max(np.abs(meas_buf))) if len(meas_buf) else 0.0
            if rms_r > 1e-9: pc.set_ref(20 * _math.log10(rms_r))
            if rms_m > 1e-9: pc.set_meas(20 * _math.log10(rms_m),
                                         20 * _math.log10(pk_m) if pk_m > 1e-9 else -120.0)

    def _update_extra_card(self, pair_idx, ref_buf, meas_buf):
        """Extra 쌍 카드에 RMS 레벨 업데이트 (Qt 메인스레드에서 호출)."""
        pair = self._extra_pairs[pair_idx] if pair_idx < len(self._extra_pairs) else None
        card = pair.get('card') if pair else None
        if card is None or not card.is_graph_visible(): return   # 체크박스 OFF → 레벨 표시 안 함
        rms_r = float(np.sqrt(np.mean(ref_buf ** 2)))
        rms_m = float(np.sqrt(np.mean(meas_buf ** 2)))
        pk_m  = float(np.max(np.abs(meas_buf))) if len(meas_buf) else 0.0
        if rms_r > 1e-9: card.set_ref(20 * _math.log10(rms_r))
        if rms_m > 1e-9: card.set_meas(20 * _math.log10(rms_m),
                                       20 * _math.log10(pk_m) if pk_m > 1e-9 else -120.0)

    def _extra_ffts(self, pair_idx, ref_buf, meas_buf):
        """추가카드 ref/meas 를 카드 딜레이만큼 시간정렬(primary와 동일 _align_pair) 후 FFT.
        magnitude·coherence 가 정렬 기준으로 정확해짐. 딜레이 0이면 no-op. [DELAY_TIME_ALIGN]"""
        n = len(ref_buf)
        dly = (self._extra_pairs[pair_idx].get('delay_ms', 0.0)
               if isinstance(pair_idx, int) and pair_idx < len(self._extra_pairs) else 0.0)
        D = int(round(dly / 1000.0 * self.sample_rate)) if dly else 0
        if D != 0 and abs(D) < n and len(meas_buf) == n:
            ref_buf, meas_buf = self._align_pair(ref_buf, meas_buf, D)
        win = np.hanning(n).astype(np.float32)
        return (np.fft.rfft(ref_buf * win).astype(complex),
                np.fft.rfft(meas_buf * win).astype(complex))

    def _on_extra_frame(self, pair_idx, ref_buf, meas_buf):
        """TFSyncThread (same-device extra pair): ref+meas 원자 처리 → pair 누적."""
        self._update_extra_card(pair_idx, ref_buf, meas_buf)
        fft_r, fft_m = self._extra_ffts(pair_idx, ref_buf, meas_buf)
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
                # [DIAG] throttled: 카드 meas chunk 도달 추적 (HW검증: 카드2 미분석)
                self._dbg_mc_n = getattr(self, '_dbg_mc_n', 0) + 1
                if self._dbg_mc_n % 90 == 0:
                    _mch = r.get('meas_ch'); _rch = r.get('ref_ch')
                    _diag('tf_mc_route', pair=pair_idx, mch=_mch, rch=_rch,
                          keys=sorted(chunk_dict.keys()),
                          meas_in=(_mch in chunk_dict),
                          ref_in=(_rch in chunk_dict if _rch is not None else 'extdev'))

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
                ref_buf_cached = getattr(self, '_extra_ref_buf', {}).get(pair_idx)
                if ref_buf_cached is not None and len(ref_buf_cached) == len(meas_buf):
                    # 시간버퍼 있으면 카드 딜레이만큼 정렬 후 FFT (magnitude 정확)
                    fft_r, fft_m = self._extra_ffts(pair_idx, ref_buf_cached, meas_buf)
                    self._update_extra_card(pair_idx, ref_buf_cached, meas_buf)
                    self._accumulate_extra(pair_idx, fft_r, fft_m)
                else:
                    fft_r = getattr(self, '_extra_ref_fft', {}).get(pair_idx)
                    if fft_r is None: continue
                    win = np.hanning(len(meas_buf)).astype(np.float32)
                    fft_m = np.fft.rfft(meas_buf * win).astype(complex)
                    if len(fft_r) == len(fft_m):
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
        ref_buf = getattr(self, '_extra_ref_buf', {}).get(pair_idx)
        if ref_buf is not None and len(ref_buf) == len(buf):
            # 시간버퍼 있으면 카드 딜레이만큼 정렬 후 FFT (magnitude 정확)
            fft_r, fft_m = self._extra_ffts(pair_idx, ref_buf, buf)
            self._update_extra_card(pair_idx, ref_buf, buf)
            self._accumulate_extra(pair_idx, fft_r, fft_m)
            return
        fft_r = self._extra_ref_fft.get(pair_idx)
        if fft_r is None: return
        n = len(buf)
        win = np.hanning(n).astype(np.float32)
        fft_m = np.fft.rfft(buf * win).astype(complex)
        if len(fft_r) == len(fft_m):
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
        _BrandBox.warning(self, _tx('Audio Error'), _tx('Audio device error:\n{msg}').format(msg=msg))

    def _on_tf_disconnect(self, msg=''):
        """입력 장치(인터페이스) USB 끊김 감지 — 분석 + 제너레이터(출력) 모두 정지.
        출력 스트림을 닫지 않으면 핑크노이즈가 macOS 기본(내장) 출력으로 새므로 함께 정지."""
        if getattr(self, '_tf_disc_handling', False): return
        # 가짜 disconnect 방지: HAL 장치 개수가 안 줄었으면(장치 그대로) 스트림 churn(채널변경/재구성)
        # 오판 → 무시. 실제 제거는 개수 감소로 통과 + CoreAudio 리스너(개수 기반)가 백업.
        try:
            _mw = getattr(self, '_mw', None)
            _cur = _mw._ca_watcher.device_count(); _base = getattr(_mw, '_ca_dev_count', None)
            if _cur is not None and _base is not None and _cur >= _base:
                _alog.info(f'TF disconnect 신호 무시 — 장치 개수 유지({_cur}≥{_base}), 가짜 끊김(스트림 churn)')
                return
        except Exception: pass
        self._tf_disc_handling = True
        _alog.info(f'TF 장치 연결 끊김 감지 → 정지 + 자동 새로고침  msg={msg}')
        self._stop_analysis()   # 분석 스트림 정지 (UI/카드/버튼 리셋 포함)
        self._stop_sig_gen()    # 출력 스트림도 닫음 → 핑크 내장출력 누출 방지
        try:
            self.status_lbl.setText('● Disconnected')
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
        try:
            self._update_rta()
        except Exception as e:
            _alog.error(f'TF _update_rta error: {e}')

    def _rta_subscribe(self):
        """RTA 칸 전용 마이크 구독(공유 엔진) — 제너레이터/측정 Start 없이 입력 스펙트럼만."""
        if self._engine is None or self._rta_sub is not None:
            return
        dev = self.meas_cb.currentData()
        ch = self.meas_ch_cb.currentData() or 0
        if dev is None:
            return
        # 이미 열린 장치면 그 SR을 따른다(Spectrum 등과 'one SR per device' 충돌 방지)
        _sr = self._engine.current_sr(dev) or self.sample_rate
        try:
            self._rta_sub = self._engine.subscribe(dev, [ch], _sr)
            self._rta_ch = ch
            self._rta_avg_buf.clear()
            self._rta_last_chunk = time.monotonic()   # 구독 직후 grace(아직 청크 전이라 watchdog 오판 방지)
            self._rta_sub.chunk_ready.connect(self._on_rta_chunk, Qt.QueuedConnection)
        except Exception as e:
            _alog.warning(f'RTA subscribe 실패: {e}'); self._rta_sub = None

    def _rta_unsubscribe(self):
        if self._rta_sub is not None:
            try: self._rta_sub.chunk_ready.disconnect()
            except Exception: pass
            try: self._rta_sub.close()
            except Exception: pass
            self._rta_sub = None
        self._rta_avg_buf.clear()
        self._rta_pow_smooth = None   # IIR 누적 리셋(다시 켜거나 채널 바뀌면 새로 시작)
        self._rta_pending = None   # 소비자가 stale 데이터로 그리지 않도록
        self.rta_cvs._rta_range_init = False   # 다시 켤 때 자동맞춤 재실행
        self.rta_cvs._idle_hint = True   # RTA 꺼짐 → 빈상태 안내 복귀
        self.rta_cvs.update()

    def _on_rta_chunk(self, d):
        """RTA producer — 청크마다(스펙트럼 _process_audio와 동일 빈도·동일 처리) 옥타브 값을 계산해
        _rta_pending에 적재. 캔버스 decay/peak-hold/repaint는 30fps 고정 타이머 _rta_render_frame가 소비."""
        self._rta_last_chunk = time.monotonic()   # 시그널 도착 = 구독 생존(채널 유무 무관, watchdog용)
        buf = d.get(self._rta_ch)
        if buf is None or len(buf) < 8:
            return
        rc = self.rta_cvs; mw = self.window()
        n_avg = int(getattr(mw, 'avg_count', 16) or 16) if mw is not None else 16
        if self._rta_avg_buf.maxlen != n_avg:
            self._rta_avg_buf = deque(self._rta_avg_buf, maxlen=max(1, n_avg))
        calib = float(getattr(mw, 'calib_offset', 0) or 0) if mw is not None else 0.0
        # 스펙트럼 _process_audio와 동일한 2단 스무딩 — ①파워도메인 IIR(계수 s=Speed의 smoothing)
        # ②FIFO 평균(avg_count). 이전엔 ①이 빠지고 30fps 스로틀이라 같은 Speed라도 RTA가 더 빠르고
        # 거칠게 보였음 → IIR 추가 + 스로틀 제거(매 청크 처리)로 스펙트럼 옥타브와 속도·질감 일치.
        s = float(getattr(mw, 'smoothing', SPEED_LEVELS[2][1])) if mw is not None else SPEED_LEVELS[2][1]
        db = power_spectrum_db(buf)
        pow_raw = 10.0 ** (db / 10.0)
        if self._rta_pow_smooth is None or len(self._rta_pow_smooth) != len(pow_raw):
            self._rta_pow_smooth = pow_raw.copy()
            fft_smooth = db.copy()
        else:
            self._rta_pow_smooth *= s
            self._rta_pow_smooth += pow_raw * (1.0 - s)
            fft_smooth = 10.0 * np.log10(np.maximum(self._rta_pow_smooth, 1e-30))
        self._rta_avg_buf.append(fft_smooth)
        avg = np.mean(self._rta_avg_buf, axis=0) if len(self._rta_avg_buf) > 1 else fft_smooth
        freqs = np.fft.rfftfreq(len(buf), 1.0 / self.sample_rate).astype(np.float32)
        # 옥타브 값만 산출해 적재 — repaint/캔버스 decay는 소비자(_rta_render_frame)에서.
        self._rta_pending = (rc.mode, _octave_bands(freqs, avg + calib, rc.mode), calib)

    def _rta_render_frame(self):
        """RTA consumer — 30fps 고정 타이머가 최신 옥타브값을 꺼내 스무딩/peak-hold/repaint
        (스펙트럼 _render_frame과 동일 패턴). 콜백 지터와 무관한 일정 프레임 → 버벅임 제거."""
        if self._rta_sub is None or self._rta_pending is None:
            return
        rc = self.rta_cvs; mw = self.window()
        if mw is not None and hasattr(mw, 'oct_cvs'):
            oc = mw.oct_cvs   # 속도/피크홀드를 스펙트럼 옥타브와 동일하게(매 프레임 미러)
            rc.alpha = oc.alpha; rc.decay = oc.decay
            rc.peak_hold = oc.peak_hold; rc.peak_hold_frames = oc.peak_hold_frames
        mode, vals, calib = self._rta_pending
        rc.calib_offset = calib
        if mode != rc.mode:
            return
        rc._idle_hint = False        # RTA 데이터 도착 → 빈상태("Press Start") 해제(바 표시).
                                     # rta_cvs 는 스펙트럼 Start와 무관해 여기서 직접 꺼줘야 함(v1.8 누락 수정).
        rc.update_data(mode, vals)   # IIR 스무딩 + peak aging + repaint (일정 30fps cadence)
        if not getattr(rc, '_rta_range_init', False):   # 첫 데이터 1회 자동맞춤
            sm = rc.smooth[rc.mode]; valid = sm[sm > -90]
            if len(valid):
                peak = float(np.max(valid)); span = rc.db_max - rc.db_min
                rc.db_max = int(math.ceil((peak + 12) / 12)) * 12
                rc.db_min = rc.db_max - span; rc._rta_range_init = True

    def _update_rta(self):
        """RTA 구독 생명주기만 관리(계산은 _on_rta_chunk가 청크레이트로). RTA 칸 켜짐=마이크 구독."""
        if 'RTA' not in self._tf_slot_plot:
            if self._rta_sub is not None:
                self._rta_unsubscribe()
            return
        cur_dev = self.meas_cb.currentData()
        cur_ch = self.meas_ch_cb.currentData() or 0
        # RTA 구독은 장치/채널 변경·스트림 재구성·loopback 충돌 등 여러 이유로 조용히 무효화될 수 있다.
        # 원인을 일일이 열거하는 대신 'liveness watchdog'로 통일 처리: 청크가 일정시간 안 오면(stale)
        # 죽은 구독으로 보고 재구독. + 장치/채널 변경은 즉시 따라가도록(정확성), 스트림 소멸도 즉시.
        if self._rta_sub is not None:
            device_changed  = (self._rta_sub.device_idx != cur_dev)
            channel_changed = (self._rta_ch != cur_ch)
            stream_gone = (self._engine is None or
                           self._rta_sub.device_idx not in self._engine.active_devices())
            stale = (time.monotonic() - self._rta_last_chunk > 1.2)   # 1.2초+ 청크 끊김 = 죽은 구독
            if device_changed or channel_changed or stream_gone or stale:
                _diag('rta_resub', dev_chg=device_changed, ch_chg=channel_changed,
                      stream_gone=stream_gone, stale=stale,
                      old_dev=self._rta_sub.device_idx, new_dev=cur_dev,
                      old_ch=self._rta_ch, new_ch=cur_ch)
                self._rta_unsubscribe()
        if self._rta_sub is None:
            self._rta_subscribe()

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
                self._reset_avg(sync=False)   # 렌더 스레드 — 워커 대기로 UI 멈추지 않게 비차단 리셋
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
            ref_b = self._last_ref_buf; meas_b = self._last_meas_buf
            rr = self._last_ref_rms; mr = self._last_meas_rms
            self._last_ref_fft = None; self._last_meas_fft = None
            self._last_ref_buf = None; self._last_meas_buf = None
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
            if rr > 0:
                _rpk = float(np.max(np.abs(ref_b))) if (ref_b is not None and len(ref_b)) else rr
                self._vu_ref.set_rms(20 * math.log10(max(rr, 1e-9)), 20 * math.log10(max(_rpk, 1e-9)))
            if mr > 0 and _pvis:
                _mpk = float(np.max(np.abs(meas_b))) if (meas_b is not None and len(meas_b)) else mr
                self._vu_meas.set_rms(20 * math.log10(max(mr, 1e-9)), 20 * math.log10(max(_mpk, 1e-9)))

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
        # 숨겨진 탭(다른 탭 보는 중)은 무거운 분석/IR/MTW 렌더를 건너뛴다 → 보이는 탭에 GUI 양보.
        # 3탭 동시 Start 시 경합 해소. 팝아웃·분할(동시보기)은 isVisible()=True라 계속 렌더. 측정 적분은 별도 경로라 유지.
        if not self.isVisible(): return
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
        self._last_primary_H = None; self._last_primary_coh = None

        # 딜레이 정렬 — 분리 콜백 경로(Internal SigGen / 다른장치 ref)는 캡처 시 정렬이 안 돼
        # H(f) 위상에 정수 딜레이가 그대로 남는다(_render_primary_H 는 sub-sample 잔여만 제거).
        # → duplex/extra 와 동일하게 여기서 정수 딜레이를 제거해 위상·IR·코히런스를 정렬 기준으로 맞춘다.
        # duplex/sync(_on_frame)는 이미 정렬됐으므로(_primary_upstream_aligned=True) 건너뛴다(이중정렬 방지). [DELAY_TIME_ALIGN]
        _D_primary = int(round(self.delay_ms / 1000.0 * self.sample_rate)) if self.delay_ms else 0
        _need_align = (_D_primary != 0 and not self._primary_upstream_aligned)

        # ── MTW 라이브 엔진 경로 (primary 전용, v1.7) — 시간영역 버퍼를 멀티레이트 분석 ──
        if self._tf_engine_mtw and self._mtw is not None:
            if _need_align and ref_b is not None and meas_b is not None \
                    and len(ref_b) == len(meas_b) and abs(_D_primary) < len(ref_b):
                ref_b, meas_b = self._align_pair(ref_b, meas_b, _D_primary)
            self._render_mtw(ref_b, meas_b, rr, mr, freqs, t_ms, _primary_show)
            self._render_extra_pairs(freqs, t_ms)   # extra 카드는 엔진 무관 — 함께 렌더
            return

        # ── Primary 누적·렌더 (Ref/Meas 데이터 충분할 때만; 없으면 extra 카드만 렌더) ──
        H_raw = None
        primary_ok = (X is not None and Y is not None and len(X) == len(Y)
                      and rr >= 1e-6 and mr >= 1e-6)
        if primary_ok:
            if _need_align:
                # 시간영역 정렬과 등가: ref FFT 를 exp(-jωD) 회전(=ref 를 D 지연) → 크로스스펙트럼
                # 위상에서 정수 딜레이 제거. 부호 무관(D<0 도 동일 식). 창 경계효과는 2차이므로 무시.
                X = X * np.exp(-1j * 2 * np.pi * freqs * (_D_primary / self.sample_rate))
            S_xy = Y * np.conj(X); S_xx = np.abs(X) ** 2; S_yy = np.abs(Y) ** 2
            if self._cross_acc is None:
                self._cross_acc = S_xy.copy(); self._auto_acc_x = S_xx.copy()
                self._auto_acc_y = S_yy.copy(); self._n_avg = 1
            else:
                # 워밍업: 목표 시정수에 ~1초(10프레임) 만에 도달 → Avg 설정이 즉시 체감됨.
                # (1프레임씩 올리면 avg=16은 16초 걸려 그 사이 모든 Avg가 동일하게 보였음)
                self._n_avg = min(self._n_avg + max(1, self._avg_target // 10), self._avg_target)
                α = 1.0 / self._n_avg   # 목표 도달 후 1/target 고정 = 시정수 = Avg초
                # 상승·하강 완전 대칭(Smaart식) — 위/아래 같은 시정수(=Response averaging_sec). fast-release 없음.
                β = 1.0 - α
                self._cross_acc  = β * self._cross_acc  + α * S_xy
                self._auto_acc_x = β * self._auto_acc_x + α * S_xx
                self._auto_acc_y = β * self._auto_acc_y + α * S_yy
            self.avg_lbl.setText(f'Avg: {self._n_avg} / {self._avg_target}')
            if self._n_avg >= 3:   # 초기 3프레임 미만: EMA 수렴 전, 표시 생략
                H_raw = self._cross_acc / np.maximum(self._auto_acc_x, 1e-30)
                gamma2 = np.clip(np.abs(self._cross_acc) ** 2 /
                                 np.maximum(self._auto_acc_x * self._auto_acc_y, 1e-60), 0.0, 1.0)
                # Single·MTW 공통 렌더 테일 (mag/phase/IR + 딜레이 마커)
                self._render_primary_H(H_raw, gamma2, freqs, t_ms, _primary_show)
        else:
            # primary 비활성(카드1 Stop 등) → avg 표시는 활성 extra 카드 기준
            _ns = [a['n'] for a in self._extra_pair_acc if a is not None]
            if _ns:
                self.avg_lbl.setText(f'Avg: {min(max(_ns), self._avg_target)} / {self._avg_target}')

        # 추가 Ref+Meas 쌍 렌더 (primary 유무·엔진 무관) — MTW/레거시 공통
        self._render_extra_pairs(freqs, t_ms)

    def _render_extra_pairs(self, freqs, t_ms):
        """추가 Ref+Meas 쌍(extra 카드) H(f) 계산 + 캔버스 갱신.
        extra 카드는 MTW 엔진과 무관하게 자체 FFT 크로스스펙트럼(_extra_pair_acc)으로
        누적되므로, MTW/Single 어느 엔진이든 이 루프가 실행돼야 그려진다.
        (이전 버그: _render_inner 가 MTW 분기에서 _render_mtw 후 즉시 return →
         이 루프 미실행 → 카드2 분석/곡선 안 뜸. 양쪽 경로에서 호출하도록 분리.)"""
        self._dbg_rend_n = getattr(self, '_dbg_rend_n', 0) + 1
        _rend_log = (self._dbg_rend_n % 30 == 0)
        for i, acc in enumerate(self._extra_pair_acc):
            if _rend_log:
                _p = self._extra_pairs[i] if i < len(self._extra_pairs) else None
                _diag('tf_card_render', i=i, accn=(acc['n'] if acc else None),
                      disp=(_p.get('display') if _p else None),
                      gvis=(_p['card'].is_graph_visible() if _p and _p.get('card') else None))
            if acc is None or acc['n'] < 3: continue
            pair = self._extra_pairs[i] if i < len(self._extra_pairs) else None
            if pair and not pair.get('display', True):
                continue  # 분석 중지 — skip
            if pair and pair.get('card') is not None and not pair['card'].is_graph_visible():
                continue  # 그래프 표시 OFF — 분석은 계속, 곡선만 숨김
            color = (pair.get('color') if pair else None) or _MC_COLORS[i % len(_MC_COLORS)]
            H_ex_raw = acc['cross'] / np.maximum(acc['auto_x'], 1e-30)
            # 코히런스 γ² (primary와 동일 정의) — 커서 리드아웃 %용
            gamma2_ex = np.clip(np.abs(acc['cross']) ** 2 /
                                np.maximum(acc['auto_x'] * acc['auto_y'], 1e-30), 0.0, 1.0)
            # 카드별 독립 딜레이 적용
            pair_delay = 0.0
            if i < len(self._extra_pairs):
                pair_delay = self._extra_pairs[i].get('delay_ms', 0.0)
            # 딜레이는 누적(_extra_ffts)에서 시간영역 정렬로 이미 반영 → 잔여(sub-sample) 위상만. [DELAY_TIME_ALIGN]
            D_ex = int(round(pair_delay / 1000.0 * self.sample_rate)) if pair_delay else 0
            _resid_ex = pair_delay / 1000.0 - D_ex / self.sample_rate
            if _resid_ex != 0.0:
                H_ex_disp = H_ex_raw * np.exp(1j * 2 * np.pi * freqs * _resid_ex)
            else:
                H_ex_disp = H_ex_raw
            f_ex, mag_ex, ph_wrap_ex, ph_unwr_ex, grp_ms_ex = _tf_smooth(freqs, H_ex_disp, self.smooth_bpo)
            coh_ex = np.interp(f_ex, freqs, gamma2_ex).astype(np.float32)   # f_ex 그리드로 코히런스 보간
            # 교차 데이터 같이 전달 → 커서 리드아웃이 1번 카드와 동일(dB+°+%)
            self.mag_cvs.set_tf_extra(i, color, f_ex, mag_ex, phase=ph_wrap_ex, coh=coh_ex)
            self.phase_cvs.set_tf_extra_phase(i, color, f_ex, ph_wrap_ex, ph_unwr_ex, grp_ms_ex, mag=mag_ex)
            # 카드별 IR: H_ex_raw 는 이제 시간정렬됨(임펄스 0ms 중심) → 정렬량 D_ex 되돌려
            # 임펄스를 실제 도착(=딜레이) 위치에 표시. 카드색 마커/센터링은 pair_delay 기준.
            h_ex = np.fft.fftshift(np.fft.irfft(H_ex_raw, n=self.fft_size)).astype(np.float32)
            if D_ex != 0:
                h_ex = np.roll(h_ex, D_ex)
            self.ir_cvs.set_tf_extra(i, color, t_ms, h_ex, delay=pair_delay)
        self._render_average(freqs, t_ms)

    def _avg_curve_color(self):
        # 사용자 지정색 우선, 없으면 다색 개별 위 도드라지는 테마 대응 고대비
        if getattr(self, '_avg_color', None):
            return self._avg_color
        return '#FFFFFF' if is_dark() else '#1A1A1A'

    def _render_average(self, freqs, t_ms):
        """참여 카드(정렬된 표시 H) 수집 → _multimic_average → 3캔버스 AVG 슬롯.
        primary·extra 모두 딜레이 제거된 H_disp를 넘긴다(캡쳐 평균과 동일 전제)."""
        if freqs is not None:                       # 정지 후 재계산에 쓸 마지막 그리드 보관
            self._last_avg_freqs = freqs; self._last_avg_t_ms = t_ms
        if not getattr(self, '_avg_on', False):
            self.mag_cvs.clear_tf_average(); self.phase_cvs.clear_tf_average()
            self.ir_cvs.clear_tf_average()
            self._last_avg_diag = None
            return
        H_list, g_list, d_list = [], [], []
        # primary(카드1) — in_average이고 분석 중이며 이번 프레임 H 저장됐을 때
        pc = self._level_cards[0] if getattr(self, '_level_cards', None) else None
        if (pc is not None and getattr(pc, 'in_average', False)
                and getattr(pc, '_display_on', False)
                and getattr(self, '_last_primary_H', None) is not None):
            H_list.append(self._last_primary_H)
            g_list.append(getattr(self, '_last_primary_coh', None))
            d_list.append(self.delay_ms)
        # extra 카드 — 정렬된 표시 H(H_disp)를 재구성해서 넣는다(_render_extra_pairs와 동일 식)
        for i, acc in enumerate(self._extra_pair_acc):
            if acc is None or acc['n'] < 3: continue
            pair = self._extra_pairs[i] if i < len(self._extra_pairs) else None
            if not pair or not pair.get('display', True): continue
            card = pair.get('card')
            if card is None or not getattr(card, 'in_average', False): continue
            H_raw = acc['cross'] / np.maximum(acc['auto_x'], 1e-30)
            g = np.clip(np.abs(acc['cross']) ** 2 /
                        np.maximum(acc['auto_x'] * acc['auto_y'], 1e-30), 0.0, 1.0)
            pd = pair.get('delay_ms', 0.0)
            D_ex = int(round(pd / 1000.0 * self.sample_rate)) if pd else 0
            _resid = pd / 1000.0 - D_ex / self.sample_rate
            H_disp = H_raw * np.exp(1j * 2 * np.pi * freqs * _resid) if _resid else H_raw
            H_list.append(H_disp); g_list.append(g); d_list.append(pd)
        # [AVG_DIAG] 참여 판정 상세 — 개별 곡선은 뜨는데 AVG만 안 뜰 때 어느 게이트가 막는지 로그.
        # P=primary(in_average/_display_on/_last_primary_H), E#=extra(acc n/display/in_average).
        _roster = []
        _pc_d = self._level_cards[0] if getattr(self, '_level_cards', None) else None
        if _pc_d is not None:
            _roster.append('P(iavg=%s,disp=%s,H=%s)' % (
                getattr(_pc_d, 'in_average', None), getattr(_pc_d, '_display_on', None),
                self._last_primary_H is not None))
        for _di, _da in enumerate(self._extra_pair_acc):
            _dp = self._extra_pairs[_di] if _di < len(self._extra_pairs) else None
            _dc = _dp.get('card') if _dp else None
            _roster.append('E%d(n=%s,disp=%s,iavg=%s)' % (
                _di, ('None' if _da is None else _da.get('n')),
                (_dp.get('display') if _dp else None),
                (getattr(_dc, 'in_average', None) if _dc is not None else None)))
        r = _multimic_average(H_list, g_list, d_list, freqs, self.sample_rate,
                              self.smooth_bpo, mode=self._avg_mode, align=self._avg_align)
        _sig = ((r['n'] if r else 0), self._avg_show, tuple(_roster))
        if getattr(self, '_last_avg_diag', None) != _sig:
            _diag('tf_avg_render', on=True, mode=self._avg_mode,
                  n=(r['n'] if r else 0), show=self._avg_show, mics='|'.join(_roster))
            self._last_avg_diag = _sig
        _n = r['n'] if r else 0
        if hasattr(self, '_avg_card_cnt'):   # AVG 카드 (n) 갱신
            _ct = f'({_n})' if _n else ''
            if self._avg_card_cnt.text() != _ct:
                self._avg_card_cnt.setText(_ct)
        # 유효<2(None)이거나 AVG 카드 ✓ 꺼짐 → 곡선 숨김(카드는 유지)
        if r is None or not getattr(self, '_avg_show', True):
            self.mag_cvs.clear_tf_average(); self.phase_cvs.clear_tf_average()
            self.ir_cvs.clear_tf_average()
            return
        col = self._avg_curve_color()
        _sel = getattr(self, '_avg_card_selected', False)   # 선택 시 굵게(맨앞 강조)
        _wmp = 3.6 if _sel else 2.8; _wir = 3.0 if _sel else 2.2
        self.mag_cvs.set_tf_average(col, r['f'], r['mag'], coh=r['coh'], width=_wmp)
        if r['mode'] == 'complex':
            self.phase_cvs.set_tf_average(col, r['f'], r['ph_wrap'], r['ph_unwr'], r['grp'], width=_wmp)
            if r['h_ir'] is not None:
                self.ir_cvs.set_tf_average(col, t_ms, r['h_ir'], width=_wir)
        else:
            self.phase_cvs.clear_tf_average(); self.ir_cvs.clear_tf_average()

    # ── 딜레이 자동 탐지 (2단계: 2초 측정 후 계산) ──────────────────────
    def _on_sweep_captured(self, ref_arr, meas_arr, start_pos=0):
        """단일 스윕 캡처 완료 → Farina ESS 분석(상승) 또는 Wiener(하강) → 캔버스 → 자동 Stop.

        Farina 역필터는 **해석적으로 생성된 깨끗한 ESS**가 x여야 한다(`_ess_inverse`가
        index 기준으로 envelope를 재계산하므로). 캡처된 ref는 ①루프 임의위상으로 회전돼
        있거나 ②외부 ref면 녹음지연만큼 어긋나 → 역필터 불일치 → THD 폭발(실HW 325%).
        해결: x=재생성 clean ESS, meas는 알려진 캡처 위상(start_pos)으로 de-rotate해
        clean이 sample0에서 f1로 시작하도록 정렬(왕복지연은 Farina n0가 흡수)."""
        self._pm_targ = None; self._pm_done = True   # 라이브 모션 스무딩 비활성(스윕 결과 직접 표시)
        self._sweep_freeze = True                     # 이후 라이브 렌더가 스윕 결과를 덮지 않도록 동결
        self.mag_cvs.arm_autofit()                    # 스윕 결과도 첫 표시에 Y축 자동맞춤
        with QMutexLocker(self._mutex):               # stale 버퍼 비움(다음 렌더 틱 재렌더 방지)
            self._last_ref_fft = None; self._last_meas_fft = None
            self._last_ref_buf = None; self._last_meas_buf = None
        # 스윕(Farina/Wiener)은 왕복지연을 이미 제거 → 측정이 0ms 정렬. 카드 딜레이를 0으로 맞춰야
        # 위상 보정 H_disp=H·exp(jωτ)이 과보정 안 되고 위상·IR이 정상(0ms 중앙) 표시됨. (사용자 지적 2026-06-28)
        # 숨은 툴바 스핀 + 보이는 primary 카드 스핀 둘 다 0으로 동기화. (예전엔 툴바 스핀만 리셋해
        # 카드가 옛 딜레이를 stale 표시 → 이후 재탐색이 같은 값→setValue no-op으로 delay_ms=0에 갇힘). [SWEEP_DELAY_SYNC]
        self.delay_ms = 0.0
        for _sp in (getattr(self, 'delay_spin', None),
                    (self._level_cards[0]._delay_spin if self._level_cards else None)):
            try:
                if _sp is not None:
                    _sp.blockSignals(True); _sp.setValue(0.0); _sp.blockSignals(False)
            except Exception: pass
        n = len(ref_arr)
        sr = self.sample_rate
        f1 = float(self._sweep_f_lo); f2 = float(self._sweep_f_hi)
        T = n / sr
        result_msg = None
        # 상승 스윕 + 유효 대역이면 Farina ESS(선형 TF 무왜곡 + THD/고조파 분리)
        use_farina = bool(self._sweep_asc) and (0 < f1 < f2)
        if use_farina:
            try:
                # x = 재생된 것과 동일한 해석적 clean ESS(상승=_gen_log_sweep 원본)
                x_clean = _gen_log_sweep(n, sr, f1, f2).astype(np.float64)
                # meas를 캡처 위상만큼 되돌려 clean(sample0=f1)에 정렬
                meas_aligned = np.roll(meas_arr.astype(np.float64), int(start_pos))
                res = farina_analyze(meas_aligned, x_clean, sr, T, f1, f2)
                freqs = res["freqs"].astype(np.float32)
                H = res["H"].astype(np.complex64)
                # 핑크(Meas/캡쳐Ref)와 절대 레벨 정확히 맞추기: 같은 캡쳐로 Wiener H(=Meas/Ref, 핑크와
                # 동일 컨벤션·정확한 레벨)를 계산해 그 밴드 중앙값에 Farina H를 스케일. Farina의 정밀
                # 위상/THD는 유지 + 레벨만 핑크 기준으로. (full-array RMS 근사의 ~1.8dB 잔차 제거) [SWEEP_LEVEL_MATCH]
                _REFw = np.fft.rfft(ref_arr.astype(np.float64)); _MICw = np.fft.rfft(meas_arr.astype(np.float64))
                _epsw = float(np.max(np.abs(_REFw)) ** 2) * 1e-6
                _Hw = np.abs((_MICw * np.conj(_REFw)) / (np.abs(_REFw) ** 2 + _epsw))
                _fw = np.fft.rfftfreq(n, 1.0 / sr)
                _bandf = (freqs > max(f1, 100.0)) & (freqs < min(f2, 8000.0))
                _dbg_scale = 1.0; _dbg_farmed = float('nan')
                if np.any(_bandf):
                    _Hw_on = np.interp(freqs[_bandf], _fw, _Hw)
                    _far = np.abs(H[_bandf]).astype(np.float64)
                    _dbg_farmed = 20.0 * np.log10(np.median(_far[_far > 1e-12]) + 1e-30) if np.any(_far > 1e-12) else float('nan')
                    # Robust level-match: ignore crashed/noise-floor bins so the scale (hence the
                    # absolute level) is the SAME for any sweep length. [SWEEP_LEVEL_MATCH]
                    _scale = _wiener_match_scale(_far, _Hw_on)
                    if 1e-6 < _scale < 1e6:
                        H = (H * _scale).astype(np.complex64); _dbg_scale = _scale
                # [SWEEP_LEVEL_DIAG] 1s vs 2s 레벨 차이 추적: 스윕길이(n)별 farina원본·Wiener스케일·최종 대역레벨
                _mid = (freqs > 300) & (freqs < 2000)
                _dbg_final = 20.0 * np.log10(np.median(np.abs(H[_mid])) + 1e-30) if np.any(_mid) else float('nan')
                _diag('sweep_level', n=n, f1=round(f1), f2=round(f2),
                      far_med_db=round(_dbg_farmed, 2), scale_db=round(20*np.log10(_dbg_scale), 2),
                      final_300_2k_db=round(_dbg_final, 2), band_pts=int(_bandf.sum()))
                if self.delay_ms != 0.0:
                    H_disp = H * np.exp(1j * 2 * np.pi * freqs * (self.delay_ms / 1000.0)).astype(np.complex64)
                else:
                    H_disp = H
                f_out, mag_out, ph_wrap, ph_unwr, grp_ms = _tf_smooth(freqs, H_disp, self.smooth_bpo)
                coh_out = np.ones(len(f_out), dtype=np.float32)
                self.phase_cvs.set_data(f_out, ph_wrap, ph_unwr, grp_ms, coh_out, mag_out)
                self.mag_cvs.set_data(f_out, mag_out, coh_out, ph_wrap)
                # 스윕은 왕복지연 제거됨 → IR 0ms중심 그대로, 딜레이=0(위 설정)이라 위상·IR 정상 정렬. [SWEEP_IR_ALIGN]
                self.ir_cvs.set_data(res["t_ms"].astype(np.float32), res["ir"].astype(np.float32))
                self.ir_cvs._delay_ms = self.delay_ms
                self.avg_lbl.setText(f'Farina ✓  THD {res["thd"]:.2f}%  ·  SNR {res["snr_db"]:.0f} dB')
                result_msg = (f'Farina ESS sweep complete\n\nLength: {T*1000:.0f} ms'
                              f'\nTHD: {res["thd"]:.2f} %\nSNR: {res["snr_db"]:.0f} dB')
                _diag('sweep_farina', n=n, thd=round(res["thd"], 3), snr=round(res["snr_db"], 1),
                      harm={k: round(v[0], 1) for k, v in res["harmonics"].items()})
            except Exception as e:
                _alog.warning(f'_on_sweep_captured Farina failed → Wiener fallback: {e}')
                use_farina = False
        if not use_farina:
            REF = np.fft.rfft(ref_arr.astype(np.float64))
            MIC = np.fft.rfft(meas_arr.astype(np.float64))
            eps = float(np.max(np.abs(REF)) ** 2) * 1e-6
            H = ((MIC * np.conj(REF)) / (np.abs(REF) ** 2 + eps)).astype(np.complex64)
            freqs = np.fft.rfftfreq(n, 1.0 / sr).astype(np.float32)
            if self.delay_ms != 0.0:
                H_disp = H * np.exp(1j * 2 * np.pi * freqs * (self.delay_ms / 1000.0)).astype(np.complex64)
            else:
                H_disp = H
            f_out, mag_out, ph_wrap, ph_unwr, grp_ms = _tf_smooth(freqs, H_disp, self.smooth_bpo)
            coh_out = np.ones(len(f_out), dtype=np.float32)
            self.phase_cvs.set_data(f_out, ph_wrap, ph_unwr, grp_ms, coh_out, mag_out)
            self.mag_cvs.set_data(f_out, mag_out, coh_out, ph_wrap)
            h_full = np.fft.fftshift(np.fft.irfft(H, n=n)).astype(np.float32)
            t_ms = (np.arange(n, dtype=np.float32) - n // 2) / sr * 1000.0   # 0ms중심(딜레이=0이라 정렬)
            self.ir_cvs.set_data(t_ms, h_full)
            self.ir_cvs._delay_ms = self.delay_ms
            self.avg_lbl.setText(f'Sweep ✓  {T*1000:.0f} ms')
            result_msg = f'Sweep (Wiener) complete\n\nLength: {T*1000:.0f} ms'

        # 스윕 IR도 핑크처럼 임펄스(+딜레이)를 화면 중앙으로 (IR 정렬 일관성). [SWEEP_IR_ALIGN]
        self._center_ir_on_delay(self.delay_ms)
        # 자동 Stop
        self._stop_sig_gen()
        self.sig_on_btn.setChecked(False)
        self.sig_on_btn.setText('Play'); self._style_sig_play(False)
        _alog.debug(f'_on_sweep_captured: n={n} farina={use_farina}')
        if result_msg:
            _BrandBox.information(self, _tx('Sweep Complete'), result_msg)

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
        base_ms = float(self.delay_ms)   # 누적은 현재 딜레이로 이미 정렬됨 → 잔여+base=참값 [DELAY_FIND_ABS]

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
            d_ms = round(base_ms + float(peak) / sr * 1000.0, 2)   # 잔여 + 현재딜레이 = 참 딜레이
            self._find_result_sig.emit(d_ms)

        threading.Thread(target=_worker, daemon=True).start()

    def _apply_find_result(self, d_ms):
        """백그라운드 계산 완료 후 메인 스레드에서 UI 업데이트."""
        self.find_btn.setEnabled(True); self.find_btn.setText('Find')
        if 0 <= d_ms <= 500:
            if float(self.delay_spin.value()) == float(d_ms):
                self._on_delay_changed(d_ms)   # setValue no-op(같은 값)이어도 적용 보장 [DELAY_FORCE_APPLY]
            else:
                self.delay_spin.setValue(d_ms)   # _on_delay_changed 경유 (self.delay_ms 갱신)
            self.mag_cvs.fit_y()             # Magnitude Y축 자동 맞춤 (뷰는 건드리지 않음)
        else:
            from PyQt5.QtWidgets import QMessageBox
            _BrandBox.information(self, _tx('Delay Finder'), _tx('Detected: {d_ms:.2f} ms\nOut of range — enter manually.').format(d_ms=d_ms))

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
        # primary가 Stop이어도(freqs None) 표시 중인 extra 카드에 데이터 있으면 캡처 허용
        has_extra = any(
            p.get('display', False) and (self.mag_cvs._tf_extra.get(i) or {}).get('f') is not None
            for i, p in enumerate(getattr(self, '_extra_pairs', [])))
        if self.mag_cvs.freqs is None and not has_extra:
            return False
        n = len(self._tf_captures)
        default = f'Capture {n + 1}'
        if prompt:
            base, ok = _text_input_dialog(self, _tx('Capture'), _tx('Name:'), default)
            if not ok: return False
            base = (base or '').strip() or default
        else:
            base = default

        # 안정화 캡쳐 모드 — 평균 수렴 + 코히런스 안정 후 자동 스냅샷
        if (getattr(self, 'tf_stable_btn', None) and self.tf_stable_btn.isChecked()
                and self._running and not getattr(self, '_stabilizing', False)):
            self._begin_stable_capture(base)
            return True
        self._capture_snapshot(base)
        return True

    def _capture_snapshot(self, base):
        """실제 캡쳐 수행 (primary + 표시중 extra 카드)."""
        group = getattr(self, '_current_tf_group', '')
        n = len(self._tf_captures)
        added = 0
        # primary — 표시 중일 때만 (꺼져 있으면 캔버스 데이터가 stale)
        primary_on = bool(self._level_cards) and self._level_cards[0]._display_on   # 카드 없으면(primary 삭제) 캡처 안 함(유령 방지)
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
            _disp = pair.get('display', False)
            ex_m = self.mag_cvs._tf_extra.get(i)
            _hasdata = bool(ex_m and ex_m.get('f') is not None)
            _diag('tf_cap_card', i=i, display=_disp, hasdata=_hasdata)
            if not _disp: continue
            if not _hasdata: continue
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

        _diag('tf_capture_done', base=base, added=added,
              cards=len(getattr(self, '_extra_pairs', [])), total=len(self._tf_captures))
        if added == 0:
            return
        _alog.info(f'TF 캡처 추가  base="{base}"  +{added}  total={len(self._tf_captures)}')
        self._refresh_tf_capture_bar()
        self._save_tf_captures()

    def _refresh_tf_capture_bar(self):
        if callable(getattr(self, '_on_captures_changed', None)):
            self._on_captures_changed()

    def _open_auralize(self):
        """오라리제이션 다이얼로그 — 단일 인스턴스(무한 열림 방지). 있으면 앞으로, 로드한 음악 유지."""
        dlg = getattr(self, '_auralize_dlg', None)
        if dlg is None:
            dlg = self._auralize_dlg = _AuralizeDialog(self, self)
        else:
            dlg._populate_ir_sources(); dlg._refresh_ir_state()   # 그새 재측정/새 캡처 반영
        dlg.show(); dlg.raise_(); dlg.activateWindow()

    def _sync_freq_zoom(self, lo, hi):
        """매그·위상 주파수축 줌 연동 — 한쪽 조작이 양쪽 f_lo/f_hi를 같이 갱신."""
        self.mag_cvs.set_freq_zoom(lo, hi)
        self.phase_cvs.set_freq_zoom(lo, hi)
        _diag('tf_fzoom', lo=round(self.mag_cvs.f_lo, 1), hi=round(self.mag_cvs.f_hi, 1))

    def _recapture_tf(self, idx):
        """기존 TF 캡쳐 idx 를 현재 라이브로 제자리 덮어쓰기 (색/이름/그룹 유지).
        meta['source'] 에 따라 primary / extra 카드 데이터로 mag·phase·ir 동시 갱신."""
        if not (0 <= idx < len(self._tf_captures)): return False
        if self.mag_cvs.freqs is None: return False
        meta = self._tf_captures[idx]
        src = meta.get('source', 'primary')
        ok = False
        if src == 'primary':
            primary_on = bool(self._level_cards) and self._level_cards[0]._display_on   # 카드 없으면(primary 삭제) 캡처 안 함(유령 방지)
            if not primary_on: return False
            ok = self.mag_cvs.recapture_live(idx)
            self.phase_cvs.recapture_live(idx)
            self.ir_cvs.recapture_live(idx, delay=self.delay_ms)
        elif src.startswith('card'):
            try:
                i = int(src[4:])
            except ValueError:
                return False
            ex_m = self.mag_cvs._tf_extra.get(i)
            if not ex_m or ex_m.get('f') is None: return False
            ex_p = self.phase_cvs._tf_extra_phase.get(i)
            pairs = getattr(self, '_extra_pairs', [])
            pair = pairs[i] if i < len(pairs) else {}
            ex_delay = pair.get('delay_ms', 0.0)
            ok = self.mag_cvs.recapture_data(idx, ex_m.get('f'), ex_m.get('mag'))
            self.phase_cvs.recapture_data(
                idx, (ex_p or ex_m).get('f'),
                ex_p.get('ph_wrap') if ex_p else None,
                ex_p.get('ph_unwr') if ex_p else None,
                ex_p.get('grp_ms') if ex_p else None)
            ex_ir = self.ir_cvs._tf_extra.get(i)
            if ex_ir and ex_ir.get('t') is not None and ex_ir.get('h') is not None:
                self.ir_cvs.recapture_data(idx, ex_ir.get('t'), ex_ir.get('h'),
                                           ex_ir.get('etc_db'), delay=ex_delay)
            else:
                self.ir_cvs.recapture_data(idx, None, None, delay=ex_delay)
        if ok:
            _alog.info(f'TF 리캡쳐  idx={idx}  label="{meta.get("label","")}"  src={src}')
            self._refresh_tf_capture_bar()
            self._save_tf_captures()
        return ok

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
                self.avg_lbl.setText('Low coherence — captured as-is')
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
            _BrandBox.information(self, _tx('Delta'), _tx('First, set one capture as the reference (R).'))
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
            _BrandBox.information(self, _tx('Export'), _tx('No TF captures to export.'))
            return
        # 폴더 선택 다이얼로그 — accept 버튼을 '내보내기'로 (macOS 기본 'Open' 대신 명확하게)
        dlg = QFileDialog(self, 'Select Export Folder')
        dlg.setFileMode(QFileDialog.Directory)
        dlg.setOption(QFileDialog.ShowDirsOnly, True)
        dlg.setLabelText(QFileDialog.Accept, 'Export')
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
            _BrandBox.information(self, _tx('Export'),
                                    _tx('Export complete:\n{csv_path}\n+ Mag/Phase/IR PNG').format(csv_path=csv_path))
        except Exception as e:
            _alog.warning(f'TF Export 실패: {e}')
            _BrandBox.warning(self, _tx('Export'), _tx('Export failed:\n{e}').format(e=e))

    def _import_tf_captures(self):
        """익스포트한 CSV(capture,freq_hz,mag_db,phase_deg,coherence)를 불러와 캡쳐로 복원.

        Mag/Phase/Coherence는 그대로, IR은 크기+위상에서 역FFT로 재구성(_ir_from_mag_phase).
        반환: True(1개 이상 추가) / False.
        """
        from PyQt5.QtWidgets import QFileDialog
        import csv as _csv, collections
        path, _ = QFileDialog.getOpenFileName(self, _tx('Select TF capture CSV'), '', 'CSV (*.csv)')
        if not path:
            return False
        try:
            with open(path, newline='', encoding='utf-8') as f:
                rows = list(_csv.reader(f))
            if not rows or rows[0][:2] != ['capture', 'freq_hz']:
                _BrandBox.warning(self, _tx('Import TF captures (CSV)'), _tx('No valid captures in file.'))
                return False
            # 라벨별 그룹핑(등장 순서 유지)
            groups = collections.OrderedDict()
            for r in rows[1:]:
                if len(r) < 3:
                    continue
                groups.setdefault(r[0], []).append(r)
            added = 0
            def _num(s):                                 # 잘못된 값은 None (행 통째로 버리지 않음)
                try: return float(s)
                except (ValueError, TypeError): return None
            for label, grp in groups.items():
                rows = []
                has_ph = False
                for r in grp:
                    try:
                        fv = float(r[1]); mv = float(r[2])
                    except (ValueError, IndexError):
                        continue                          # 주파수/크기 불량 행만 스킵
                    pv = _num(r[3]) if len(r) > 3 else None
                    cv = _num(r[4]) if len(r) > 4 else None
                    if pv is not None: has_ph = True
                    rows.append((fv, mv, pv if pv is not None else 0.0,
                                 cv if cv is not None else np.nan))
                if len(rows) < 2:
                    continue
                rows.sort(key=lambda t: t[0])             # 주파수 오름차순(np.interp/gradient 전제)
                arr = np.array(rows, dtype=np.float64)
                keep = np.concatenate(([True], np.diff(arr[:, 0]) > 0))  # 중복주파수 제거(gradient div0 방지)
                arr = arr[keep]
                if len(arr) < 2:
                    continue
                f_hz = arr[:, 0].astype(np.float32)
                mag = arr[:, 1].astype(np.float32)
                ph_deg = arr[:, 2]
                phw = ph_deg.astype(np.float32)
                phu = np.degrees(np.unwrap(np.radians(ph_deg))).astype(np.float32)
                # 그룹딜레이(ms) = -dφ/dω = -(dφ_deg/df)/360*1000
                with np.errstate(all='ignore'):
                    grp_ms = (-(np.gradient(phu, f_hz) / 360.0) * 1000.0).astype(np.float32)
                coh_a = arr[:, 3].astype(np.float32)
                if np.all(np.isnan(coh_a)):
                    coh_a = None
                color = _auto_capture_color(len(self._tf_captures))
                self.mag_cvs.add_capture_data(label, color, f_hz, mag, coh_a)
                # Phase/IR — 위상 있을 때만 복원, 없으면 None(가짜 0° 곡선 방지)
                if has_ph:
                    self.phase_cvs.add_capture_data(label, color, f_hz, phw, phu, grp_ms, coh_a)
                    t_ms, h = _ir_from_mag_phase(f_hz, mag.astype(np.float64), ph_deg)
                    self.ir_cvs.add_capture_data(label, color, t_ms, h, None, delay=0.0)
                else:
                    self.phase_cvs.add_capture_data(label, color, f_hz, None, None, None, coh_a)
                    self.ir_cvs.add_capture_empty(label, color, delay=0.0)
                self._tf_captures.append({'color': color, 'label': label,
                                          'group': '', 'source': 'import'})
                added += 1
            if added == 0:
                _BrandBox.warning(self, _tx('Import TF captures (CSV)'), _tx('No valid captures in file.'))
                return False
            _alog.info(f'TF Import 완료  file={path}  +{added}')
            self._refresh_tf_capture_bar()
            self._save_tf_captures()
            _BrandBox.information(self, _tx('Import TF captures (CSV)'),
                                  _tx('Import complete: {n} capture(s)\nIR reconstructed from magnitude + phase.').format(n=added))
            return True
        except Exception as e:
            _alog.warning(f'TF Import 실패: {e}')
            _BrandBox.warning(self, _tx('Import TF captures (CSV)'), _tx('Import failed:\n{e}').format(e=e))
            return False

    def _do_tf_average(self):
        if not self._tf_captures:
            from PyQt5.QtWidgets import QMessageBox
            _BrandBox.information(self, _tx('TF Average'), _tx('No TF captures available.'))
            return
        dlg = _TFAverageDialog(self._tf_captures, self)
        if dlg.exec_() != QDialog.Accepted:
            return
        sel_idxs = dlg.selected_indices()
        if len(sel_idxs) < 2:
            from PyQt5.QtWidgets import QMessageBox
            _BrandBox.information(self, _tx('TF Average'), _tx('Select 2 or more captures.'))
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
        # 누적(EMA)은 렌더 주기마다 1회 일어나므로 평균 프레임 수 = 평균초 / 렌더주기.
        # (기존엔 fft_size//4 hop 가정 → MTW 같은 큰 fft에서 평균이 과소 → 너무 빠르고 튐)
        self._avg_target = max(2, int(self.averaging_sec * 1000.0 / TF_RENDER_MS))
        # MTW 엔진 내부 EMA도 동일 시정수로 — 렌더 주기 바뀌어도 평균초가 실시간 평균초와 일치
        if self._mtw is not None:
            self._mtw.avg_target = self._avg_target

    def _reset_avg(self, sync=True):
        with QMutexLocker(self._mutex):
            self._cross_acc = None; self._auto_acc_x = None; self._auto_acc_y = None; self._n_avg = 0
        self._extra_pair_acc = [None] * len(self._extra_pairs)
        self._mtw_H_lin = None
        self._pm_prev = None; self._pm_targ = None; self._pm_done = True   # 모션 스무딩 버퍼 비움
        if self._mtw is not None:
            self._dsp_gen += 1      # 진행 중 워커 결과를 stale로 만들어 폐기(gen 불일치)
            self._dsp_out = None
            if sync:
                self._dsp_sync()    # 정지/엔진변경 등(렌더 밖) — 즉시 확정 리셋(블로킹 허용)
                self._mtw.reset()
                self._mtw_reset_pending = False   # 확정 리셋했으니 예약 취소(중복 방지)
            else:
                # 렌더 루프(xrun) 안 — GUI 스레드를 워커 완료까지 막지 않도록 리셋을 예약.
                # 다음 렌더 틱의 워커 idle 지점에서 안전하게 _mtw.reset() (아래 submit 직전).
                self._mtw_reset_pending = True

    def _render_primary_H(self, H_raw, gamma2, freqs, t_ms, primary_show):
        """primary H(f)[선형 freqs 그리드] → mag/phase/IR 캔버스. Single·MTW 공통 렌더 테일.
        IR은 raw H로 생성(임펄스가 실제 도착=딜레이 위치) + 딜레이 마커 = Single과 동일 거동."""
        # 딜레이는 콜백(_on_frame)에서 시간영역 정렬(정수 D 샘플)로 이미 반영됨 → magnitude·coherence가
        # 정렬 기준으로 즉시 올바르게 잡힘(Smaart 방식). 여기선 잔여(sub-sample) 위상만 보정. [DELAY_TIME_ALIGN]
        D_al = int(round(self.delay_ms / 1000.0 * self.sample_rate)) if self.delay_ms else 0
        _resid = self.delay_ms / 1000.0 - D_al / self.sample_rate
        if _resid != 0.0:
            H_disp = H_raw * np.exp(1j * 2 * np.pi * freqs * _resid)
        else:
            H_disp = H_raw
        self._last_primary_H = H_disp        # 정렬된 표시 H (라이브 평균 수집용)
        self._last_primary_coh = gamma2
        f_out, mag_out, ph_wrap, ph_unwr, grp_ms = _tf_smooth(freqs, H_disp, self.smooth_bpo)
        # 코히런스 1/3 oct 스무딩 (Single과 동일)
        mask = (freqs >= 18) & (freqs <= 22000)
        f_m = freqs[mask]; g_m = np.clip(gamma2[mask], 0.0, 1.0)
        if len(f_m) > 1:
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
        if primary_show:
            # Live IR: H_raw 는 이제 시간정렬된 값(임펄스가 0ms 중심) → 정렬량 D_al 만큼 되돌려
            # 임펄스를 실제 도착(=딜레이) 위치에 표시(기존 거동 유지).
            h_full = np.fft.fftshift(np.fft.irfft(H_raw, n=self.fft_size)).astype(np.float32)
            if D_al != 0:
                h_full = np.roll(h_full, D_al)
            # 캔버스에 직접 set_data 하지 않고 "목표 곡선"으로 저장 → 30fps 보간 타이머가
            # 10fps 갱신 사이를 부드럽게 그려준다(데이터 속도/평균은 불변, 모션만 매끈).
            self._pm_push_target(f_out, mag_out, coh_out, ph_wrap, ph_unwr, grp_ms, t_ms, h_full)

    # ── primary 곡선 모션 스무딩 (10fps 누적 → 30fps 보간 페인트) ──────────
    def _pm_push_target(self, f, mag, coh, pw, pu, gm, t_ms, h):
        """새 목표 곡선 도착(10fps). 이전 목표→prev로 옮기고 보간 시작."""
        # 스윕 결과 표시 중이면 라이브 갱신 차단(stale 버퍼 재렌더가 farina IR을 덮는 것 방지).
        # 다음 Start(_start_sig_gen)에서 해제.
        if getattr(self, '_sweep_freeze', False):
            return
        self._pm_prev = self._pm_targ
        self._pm_targ = {'f': f, 'mag': mag, 'coh': coh, 'pw': pw, 'pu': pu,
                         'gm': gm, 't_ms': t_ms, 'h': h}
        self._pm_t0 = time.monotonic(); self._pm_done = False

    @staticmethod
    def _pm_lerp(a, b, fr):
        """길이 같을 때만 선형보간, 아니면 목표값 그대로(스무딩/FFT 변경 시 스냅)."""
        if a is None or b is None or len(a) != len(b):
            return b
        return a + (b - a) * fr

    @staticmethod
    def _pm_lerp_ang(a, b, fr):
        """wrapped 위상(±180°) 전용 — 최단각 경로 보간 후 [-180,180]로 재랩.
        직선보간하면 ±180 경계를 0으로 쓸고 지나가 세로선 artifact 발생 → 방지."""
        if a is None or b is None or len(a) != len(b):
            return b
        d = (b - a + 180.0) % 360.0 - 180.0      # 델타를 [-180,180]로
        return (a + d * fr + 180.0) % 360.0 - 180.0

    def _pm_smooth_paint(self):
        """30fps: prev→targ 보간값을 캔버스에 push. frac 1 도달 후엔 idle(반복 페인트 방지)."""
        t = self._pm_targ
        if t is None or self._pm_done:
            return
        p = self._pm_prev
        fr = (time.monotonic() - self._pm_t0) / (TF_RENDER_MS / 1000.0)
        if fr >= 1.0:
            fr = 1.0; self._pm_done = True
        L = self._pm_lerp; A = self._pm_lerp_ang
        mag = L(p['mag'], t['mag'], fr) if p else t['mag']
        coh = L(p['coh'], t['coh'], fr) if p else t['coh']
        pw  = A(p['pw'],  t['pw'],  fr) if p else t['pw']   # wrapped 위상=최단각 보간(artifact 방지)
        pu  = L(p['pu'],  t['pu'],  fr) if p else t['pu']
        gm  = L(p['gm'],  t['gm'],  fr) if p else t['gm']
        h   = L(p['h'],   t['h'],   fr) if p else t['h']
        self.phase_cvs.set_data(t['f'], pw, pu, gm, coh, mag)
        self.mag_cvs.set_data(t['f'], mag, coh, pw)
        self.ir_cvs.set_data(t['t_ms'], h)
        self.ir_cvs._delay_ms = self.delay_ms

    def _render_mtw(self, ref_b, meas_b, rr, mr, freqs, t_ms, primary_show):
        """MTW 라이브 렌더 — 멀티레이트 엔진 결과(로그그리드 H)를 Single과 동일한 선형
        freqs 그리드로 보간 → 공통 렌더 테일(_render_primary_H)로 Single과 완전 동일 거동."""
        if ref_b is None or meas_b is None or rr < 1e-6 or mr < 1e-6:
            return
        # 워커 지연 생성 (MTW 렌더 시작 시 1회) — 무거운 멀티레이트 FFT를 GUI 밖에서.
        # hasattr 게이트: 실제 TF 창만 워커, 테스트 Stub 등은 동기 폴백.
        _use_worker = hasattr(self, '_dsp_exec')
        if _use_worker and self._dsp_exec is None:
            try:
                from concurrent.futures import ThreadPoolExecutor
                self._dsp_exec = ThreadPoolExecutor(max_workers=1, thread_name_prefix='tf-dsp')
                _diag('tf_dsp_worker', state='start')
            except Exception as e:
                _diag('tf_dsp_worker', state='fail', err=str(e)); self._dsp_exec = None
        if _use_worker and self._dsp_exec is not None:
            # 비동기: 워커 유휴면 최신 버퍼로 새 계산 제출(논블로킹), 화면엔 직전 결과 표시.
            # → 무거운 MTW FFT가 GUI 스레드 밖에서 돌아 Spectrum FFT와 병렬(numpy GIL 해제).
            fut = self._dsp_future
            if fut is None or fut.done():
                # 워커가 idle인 이 시점이 _mtw를 만질 유일한 안전 지점 → 예약된 비차단 리셋 실행.
                if self._mtw_reset_pending:
                    try: self._mtw.reset()
                    except Exception: pass
                    self._dsp_out = None          # 워커 완료 확정 → 혹시 남은 stale 결과 제거
                    self._mtw_reset_pending = False
                self._dsp_future = self._dsp_exec.submit(
                    self._mtw_compute_task, ref_b, meas_b, self.sample_rate, self._dsp_gen)
            res = self._dsp_out
            if res is None:
                self.avg_lbl.setText('Adaptive…'); return
        else:
            # 동기 폴백(워커 불가) — 기존 동작 그대로
            if self._mtw.sr != self.sample_rate:                 # SR 변경 추종
                self._mtw = MTWEngine(self.sample_rate, n_fft=self._mtw.n_fft, n_stages=self._mtw.n_stages)
            if len(ref_b) < self._mtw.master_len:                # 마스터 버퍼 아직 미충전
                self.avg_lbl.setText('Adaptive…'); return
            self._mtw.push(ref_b, meas_b)
            res = self._mtw.result()
            if res is None:
                return
        f_m, H_m, coh_m = res
        if not getattr(self, '_mtw_live_logged', False):
            self._mtw_live_logged = True
            _diag('mtw_live', stages=self._mtw.n_stages, n_fft=self._mtw.n_fft,
                  pts=len(f_m), coh_med=round(float(np.median(coh_m)), 3))
        f_m = f_m.astype(np.float32)
        # 로그그리드 H/coh → 선형 freqs 그리드 보간 (Single과 동일한 입력 형태로 변환)
        H_raw = (np.interp(freqs, f_m, H_m.real)
                 + 1j * np.interp(freqs, f_m, H_m.imag)).astype(np.complex64)
        gamma2 = np.clip(np.interp(freqs, f_m, coh_m), 0.0, 1.0).astype(np.float32)
        self._mtw_H_lin = H_raw      # 영속 보관 (딜레이 파인더가 매 프레임 비워지는 버퍼 대신 사용)
        self.avg_lbl.setText('Adaptive')
        self._render_primary_H(H_raw, gamma2, freqs, t_ms, primary_show)

    def _mtw_compute_task(self, ref_b, meas_b, sr, gen):
        """워커 스레드 — MTW 멀티레이트 FFT(무거움)만 수행. ⚠️위젯 절대 접근 금지(numpy만).
        _mtw는 이 워커가 전담 사용하고, 드문 reset/engine 변경은 GUI가 _dsp_sync로 직렬화한다.
        gen = 제출 시점 세대. 계산 중 리셋(gen 증가)되면 결과를 버려 오염 프레임 표시를 막는다."""
        try:
            m = self._mtw
            if m is None:
                return
            if m.sr != sr:                      # SR 변경 추종(워커 안에서 재생성)
                m = MTWEngine(sr, n_fft=m.n_fft, n_stages=m.n_stages); self._mtw = m
            if len(ref_b) < m.master_len:        # 마스터 버퍼 미충전
                return
            m.push(ref_b, meas_b)
            r = m.result()
            if r is not None and gen == self._dsp_gen:   # 리셋 이후 stale 결과 폐기
                self._dsp_out = r                # 참조 대입은 GIL-원자적 → GUI가 안전하게 읽음
        except Exception as e:
            try: _diag('tf_dsp_err', err=str(e))
            except Exception: pass

    def _dsp_sync(self):
        """진행 중 워커 계산이 끝나길 잠깐 대기 — 드문 reset/engine 변경/정지에서 _mtw를
        직접 만지기 전에 호출해 동시접근(레이스)을 막는다. per-frame 아님 → 비용 무시."""
        fut = getattr(self, '_dsp_future', None)
        if fut is not None:
            try: fut.result(timeout=1.0)
            except Exception: pass
            self._dsp_future = None

    def _engine_changed(self, idx):
        """라이브 엔진 전환: 0=Single FFT(기본), 1=MTW. fft_size 조정 후 분석 재시작."""
        mtw = (idx == 1)
        self._dsp_sync()                # 워커가 _mtw 쓰는 중이면 끝나길 대기(아래서 _mtw 재구성/None)
        self._dsp_out = None
        self._tf_engine_mtw = mtw
        self._mtw_live_logged = False   # 엔진 전환마다 첫 라이브결과 마커 1회 재기록
        if mtw:
            if self._mtw is None or self._mtw.sr != self.sample_rate:
                self._mtw = MTWEngine(self.sample_rate, n_fft=4096, n_stages=5)
            self.fft_size = self._mtw.master_len    # 마스터 롤링버퍼 길이로 소스 구성
            if hasattr(self, 'fft_cb'): self.fft_cb.setEnabled(False)
        else:
            self._mtw = None
            if hasattr(self, 'fft_cb'):
                self.fft_size = TF_FFT_SIZES[self.fft_cb.currentIndex()]
                self.fft_cb.setEnabled(True)
        self._recalc_target(); self._reset_avg()
        self.ir_cvs.clear(); self._sync_ir_delay_marker()
        _diag('tf_engine', mtw=mtw, fft_size=self.fft_size)
        if self._running:
            self._stop(); self._start()

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
        # 스윕 1-shot 캡쳐가 duplex(입출력 같은 장치)로 진행 중이면 별도 분석 입력 스트림을 열지
        # 않는다 — 같은 장치에 2 스트림 → CoreAudio 충돌. 스윕은 duplex가 캡쳐/분석을 전담하고,
        # 캡쳐 완료(auto-stop)로 duplex가 닫힌 뒤 핑크 재생 시 이 경로가 분석을 시작한다. [PLAY_AUTOSTART_CARD]
        _sweep_armed = (self._duplex_thread is not None and self._duplex_thread.isRunning()
                        and self._duplex_thread._sc_armed[0])
        primary_active = (not getattr(self, '_primary_deleted', False) and
                          bool(self._level_cards) and self._level_cards[0]._display_on)
        extra_active = any(p.get('display', False) for p in self._extra_pairs)
        _diag('start_pairs', primary=bool(primary_active), extra=bool(extra_active),
              running=bool(self._running), sweep_armed=bool(_sweep_armed))
        if _sweep_armed:
            return
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

    def _on_ref_vu(self, db, peak_db=None):
        """공유 레퍼런스 VU 바 + 레벨 레이블 업데이트."""
        if hasattr(self, '_ref_vu_bar'):
            self._ref_vu_bar.set_rms(db, peak_db)
        if hasattr(self, '_ref_db_lbl'):
            c = T('red') if db > METER_RED_DB else T('yellow') if db > METER_YELLOW_DB else T('text_dim')
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
        # 제너레이터가 켜져 있으면: 외부 Ref + duplex 모드는 standalone 으로 먼저 전환
        # (TFDuplexThread가 M4 입력 점유 중 → _start()가 같은 장치에 MC 열면 CoreAudio 충돌)
        if self.sig_on_btn.isChecked():
            ref_idx = self.ref_cb.currentData()
            if (ref_idx is not None and
                    self._duplex_thread and self._duplex_thread.isRunning()):
                self._start_sig_gen()   # duplex → standalone OutputStream으로 전환
        # 입력 분석 스트림 (재)시작 — **제너레이터 ON/OFF 무관**. 카드 Start = 레벨미터 동작.
        # settle 지연(_delayed_restart) 으로 입력 스트림 close↔open 맞물림(첫 스트림 데이터 못받음/
        # 라이브 제너레이터 출력 글리치)을 회피. 제너레이터 꺼져 있으면 글리치 우려는 없지만 동일 경로로 일원화.
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

    def _primary_delay_cross_auto(self):
        """딜레이 파인더용 primary cross/auto_x 스펙트럼.
        Single=콜백 누적 스펙트럼, MTW=영속 보관 중인 선형그리드 H(_mtw_H_lin) 사용.
        반환 (cross, auto_x) 또는 (None, None). 워커는 H=cross/auto 로 IR 피크를 찾으므로
        MTW는 cross=H, auto_x=1 로 주면 H=H 가 되어 동일 로직 재사용."""
        if self._tf_engine_mtw:
            H = self._mtw_H_lin
            if H is None: return None, None
            H = H.copy()
            return H, np.ones(len(H), dtype=np.float32)
        with QMutexLocker(self._mutex):
            cross  = self._cross_acc.copy()  if self._cross_acc  is not None else None
            auto_x = self._auto_acc_x.copy() if self._auto_acc_x is not None else None
        return cross, auto_x

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
                _BrandBox.warning(self, 'Auto Find Delay',
                    _tx('Ref and Meas are on different devices.\n\nDifferent audio interfaces have separate hardware clocks,\nso automatic delay detection may be inaccurate.\n\nEnter the delay value manually,\nor sync clocks via Word Clock / ADAT.'))
                return
        if pair_idx is None:
            cross, auto_x = self._primary_delay_cross_auto()
        else:
            with QMutexLocker(self._mutex):
                if pair_idx >= len(self._extra_pair_acc): return
                acc = self._extra_pair_acc[pair_idx]
                if acc is None: return
                cross  = acc['cross'].copy()
                auto_x = acc['auto_x'].copy()
        if cross is None or auto_x is None: return
        fft_size = self.fft_size; sr = self.sample_rate
        # ⭐현재 적용 중인 딜레이(base). 누적 스펙트럼은 이 딜레이로 이미 시간정렬돼 있어(_align_pair)
        # IR 피크는 "잔여(참값−base)"만 보인다 → 찾은 잔여에 base 를 더해야 참 딜레이가 나온다.
        # (v1.9 _align_pair 도입 전엔 누적이 미정렬이라 base=0로 맞았음. 정렬 도입 후 회귀했던 부분.) [DELAY_FIND_ABS]
        if pair_idx is None:
            base_ms = float(self.delay_ms)
        else:
            base_ms = float(self._extra_pairs[pair_idx].get('delay_ms', 0.0)) \
                      if pair_idx < len(self._extra_pairs) else 0.0

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
            d_ms = round(base_ms + float(peak) / sr * 1000.0, 2)   # 잔여 + 현재딜레이 = 참 딜레이
            self._find_pair_result_sig.emit(pair_idx if pair_idx is not None else -1, d_ms)

        threading.Thread(target=_worker, daemon=True).start()

    def _apply_find_pair_result(self, pair_idx_enc, d_ms):
        """백그라운드 계산 완료 → 해당 카드 delay_spin 업데이트."""
        pair_idx = None if pair_idx_enc == -1 else pair_idx_enc
        if pair_idx is None:
            # Primary 카드 — 카드의 _delay_spin을 직접 설정 (툴바 hidden spin 아님)
            if self._level_cards and hasattr(self._level_cards[0], '_delay_spin'):
                _sp = self._level_cards[0]._delay_spin
                # 찾은 값이 현재 표시값과 같으면 setValue가 valueChanged를 안 쏨(no-op) → _on_delay_changed
                # 미호출로 delay_ms 미갱신(특히 스윕 후 delay_ms=0인데 카드가 같은 값 표시 시). 강제 적용. [DELAY_FORCE_APPLY]
                if float(_sp.value()) == float(d_ms):
                    self._on_delay_changed(d_ms)
                else:
                    _sp.setValue(d_ms)   # valueChanged → _on_delay_changed → self.delay_ms 갱신
        else:
            if pair_idx < len(self._extra_pairs):
                card = self._extra_pairs[pair_idx].get('card')
                if card and hasattr(card, 'set_delay'):
                    _chg = (float(d_ms) != float(self._extra_pairs[pair_idx].get('delay_ms', 0.0)))
                    card.set_delay(d_ms)   # 스핀 표시 갱신 (시그널 차단됨)
                    self._extra_pairs[pair_idx]['delay_ms'] = d_ms
                    self._save_tf_extra_pairs()
                    # set_delay가 blockSignals(True)라 _on_extra_delay_changed가 안 불림 →
                    # 여기서 직접 누적 재시드해야 새 D로 정렬된 올바른 레벨로 즉시 스냅(콤필터 크롤 방지). [DELAY_SNAP]
                    if _chg and pair_idx < len(self._extra_pair_acc):
                        self._extra_pair_acc[pair_idx] = None
                    # raw H IR: 마커가 d_ms 로 이동. 이 카드가 front 면 뷰도 센터링.
                    if getattr(self, '_front_pair', None) == pair_idx:
                        self._center_ir_on_delay(d_ms)
                    else:
                        self.ir_cvs._cache = None; self.ir_cvs.update()

    def _on_extra_delay_changed(self, idx, v):
        """Extra pair delay_spin 변경 → pair dict 동기화 + 마커/센터 갱신.
        그 카드가 front 면 뷰를 그 딜레이 위치로 센터링(아니면 마커만 다음 렌더에서 갱신)."""
        if 0 <= idx < len(self._extra_pairs):
            _chg = (v != self._extra_pairs[idx].get('delay_ms', 0.0))
            self._extra_pairs[idx]['delay_ms'] = v
            self._save_tf_extra_pairs()
            # 딜레이 변경 → 그 카드 누적 재시드 → 정렬된 올바른 레벨로 즉시 스냅. [DELAY_SNAP]
            if _chg and idx < len(self._extra_pair_acc):
                self._extra_pair_acc[idx] = None
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
        # Response(평균 시정수)만 바꾸고 누적은 유지 → 곡선이 그 자리에서 즉시 전환(재수렴/쓸어내림 없음).
        # (_reset_avg 를 호출하면 평균을 버리고 다시 쌓아 "위→아래 내려옴" 처럼 보였음)
        self.averaging_sec = TF_AVG_SEC[idx]; self._recalc_target()

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
        _changed = (v != self.delay_ms)
        self.delay_ms = v
        self.ir_cvs._delay_ms = v
        # 딜레이 변경 순간 평균 재시드 → magnitude가 (정렬된) 올바른 레벨로 즉시 스냅(Smaart처럼).
        # 정렬(_align_pair) 덕에 첫 프레임이 이미 정렬 기준이라 예전 "위→아래 크롤" 없음. [DELAY_SNAP]
        if _changed and self._running:
            self._reset_avg()
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

    def _unit_changed(self, idx):
        """딜레이 표시 단위 토글 (ms / both / m). 전역값만 바꾸고 새로고침 — 표시코드 불변."""
        set_delay_unit(('ms', 'both', 'm')[idx])
        self._refresh_delay_unit()

    def _refresh_delay_unit(self):
        """단위 변경 후 표시 갱신 — 내부 저장(ms)은 불변. IR 캔버스 + 카드 m-라벨만."""
        if hasattr(self, 'ir_cvs'): self.ir_cvs.update()
        for c in getattr(self, '_level_cards', []):
            if hasattr(c, '_update_m_lbl'): c._update_m_lbl()

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

    def _style_sig_play(self, playing):
        """Play/Stop 버튼 — direction C 회색 채움 필 + 재생=액센트▶ / 정지중=레드■ 아이콘.
        (기존 _apply_txn 틴트 대체 — N2 결 유지)."""
        _b = getattr(self, 'sig_on_btn', None)
        if _b is None: return
        if playing:
            _bg, _bg_h = '#3A2A2C', '#453032'
            _b.setIcon(_icon('stop', 14, color=T('red')))
        else:
            _bg, _bg_h = ('#3A3A42', '#44444C') if is_dark() else (T('bg3'), T('panel'))
            _b.setIcon(_icon('play', 14, color=T('accent')))
        _b.setStyleSheet(
            f'QPushButton{{background:{_bg};color:{T("text")};border:none;border-radius:8px;'
            f'padding:5px;font-size:12px;font-weight:bold;}}'
            f'QPushButton:hover{{background:{_bg_h};}}')

    def _restyle_sig_gen_theme(self):
        """테마 토글(다크↔라이트) 시 TF 신호발생기/측정 패널 N2 컨트롤 재스타일."""
        _bd = '#34343B' if is_dark() else T('border')
        _bd_h = '#4A4A54' if is_dark() else '#B7B7C0'
        if hasattr(self, '_sig_type_cell'):
            self._sig_type_cell.setStyleSheet(
                f'#sigTypeCell{{border:1px solid {_bd};background:transparent;border-radius:8px;}}'
                f'#sigTypeCell:hover{{border-color:{_bd_h};}}')
            self._sig_type_txt.setStyleSheet(f'color:{T("text")};background:transparent;')
            self._sig_type_chev.setStyleSheet(f'color:{T("text_dim")};background:transparent;')
            self._update_sig_type_label()
        for cb in (getattr(self, 'sig_out_cb', None), getattr(self, 'sig_out_ch_cb', None), getattr(self, 'sig_out_ch2_cb', None)):
            if cb is not None:
                cb._flat_border = _bd; cb.update()
        if hasattr(self, '_ref_sec'):
            _rbg = '#1E1E22' if is_dark() else '#F3F5FA'
            self._ref_sec.setStyleSheet(f'QFrame#refCard{{border:1px solid {_bd};border-radius:10px;background:{_rbg};padding:2px;}}')
        if hasattr(self, '_ref_db_lbl'):
            self._ref_db_lbl.setStyleSheet(f'color:{T("accent")};background:transparent;')
        _rflat = (f'QComboBox{{background:transparent;color:{T("text")};border:1px solid {_bd};'
                  f'border-radius:8px;padding:1px 8px;font-size:{FS_SM}px;min-height:22px;}}'
                  f'QComboBox::drop-down{{width:0;border:none;}}QComboBox::down-arrow{{width:0;height:0;image:none;}}')
        for cb in (getattr(self, 'ref_cb', None), getattr(self, 'ref_ch_cb', None)):
            if cb is not None:
                cb.setStyleSheet(_rflat); cb._flat_border = _bd; cb.update()
        for c in getattr(self, '_level_cards', []):
            try: c.restyle()
            except Exception: pass
        # 캡스 그룹 헤더 라벨(SIGNAL GENERATOR/MEASUREMENT/AVERAGE) 색 재적용
        if hasattr(self, 'rp'):
            for _hl in self.rp.findChildren(QLabel, 'n2GroupHdr'):
                _hl.setStyleSheet(f'color:{T("text")};background:transparent;')
        # AVERAGE 팝업 N2 컨트롤(토글/세그먼트) 재스타일 + 카드별 avg 토글(레벨카드+추가카드) 재적용
        if hasattr(self, '_avg_card'):
            self._style_avg_card()
        if hasattr(self, '_avg_popup'):
            self._style_avg_popup()
            for _b in self._avg_popup.findChildren(QWidget):
                if hasattr(_b, 'restyle') and _b is not self._avg_popup:
                    try: _b.restyle()
                    except Exception: pass
            for _hl in self._avg_popup.findChildren(QLabel, 'n2GroupHdr'):
                _hl.setStyleSheet(f'color:{T("text")};background:transparent;')
        for c in (self._level_cards + [p.get('card') for p in getattr(self, '_extra_pairs', []) if p.get('card')]):
            if hasattr(c, '_avg_chk'):
                c._update_avg_chk_icon()

    def _update_sig_type_label(self):
        """타입 드롭다운 셀의 아이콘+이름을 현재 선택된 신호 타입으로 갱신."""
        if not hasattr(self, '_sig_type_txt'): return
        if self.sig_sine_btn.isChecked():
            ic, txt = 'activity', self.sig_sine_btn.text()          # 'Sine 1k'
        elif self.sig_sweep_btn.isChecked():
            ic, txt = 'spline', 'Sweep'
        elif self.sig_file_btn.isChecked():
            _ft = self.sig_file_btn.text().strip()
            ic, txt = 'folder', (_ft if _ft and _ft != 'File…' else 'File')
        elif self.sig_white_btn.isChecked():
            ic, txt = 'waves', 'White'
        else:
            ic, txt = 'waves', 'Pink'
        self._sig_type_ic.setPixmap(_icon_pm(ic, 15, _n2_icon_color()))
        self._sig_type_txt.setText(txt)

    def _toggle_sig_gen(self, checked):
        if checked:
            self._on_gen_started()
            # Play = 측정: 활성 카드가 하나도 없으면 primary 카드를 자동 Start (사용자 결정 2026-07-02).
            # 스윕이 카드 Start 게이트를 우회해 카드는 Stopped인데 분석·표시되던 것(Bug1) + 그 상태로
            # 스윕→핑크 전환 시 카드가 Stopped라 핑크가 (간헐적으로) 측정 안 되던 것(Bug2)을 함께 해소.
            # (분석 스트림 자체는 아래 _start_active_pairs 가 시작; 여기선 카드 상태만 켬.) [PLAY_AUTOSTART_CARD]
            _any_active = ((bool(self._level_cards) and self._level_cards[0]._display_on) or
                           any(p.get('display', False) for p in getattr(self, '_extra_pairs', [])))
            if (not _any_active and self._level_cards and
                    not getattr(self, '_primary_deleted', False)):
                self._level_cards[0].set_running(True)   # 카드 UI=▶, _display_on=True
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
                self.sig_on_btn.setText('Play'); self._style_sig_play(False);
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
            self.sig_on_btn.setText('Play'); self._style_sig_play(False)
        from PyQt5.QtWidgets import QFileDialog, QMessageBox
        path, _ = QFileDialog.getOpenFileName(
            self, 'Select Audio File', '',
            'Audio Files (*.wav *.flac *.aiff *.aif *.ogg *.mp3 *.m4a *.caf);;All Files (*)')
        if not path:
            self.sig_file_btn.setChecked(False)
            if not self.sig_white_btn.isChecked() and not self.sig_sweep_btn.isChecked() \
               and not self.sig_sine_btn.isChecked():
                self.sig_pink_btn.setChecked(True)
            return
        self._load_audio_file(path)

    def _load_audio_file(self, path):
        """경로의 오디오 파일을 측정 버퍼로 로드 (파일선택·드래그드롭 공용). True=성공."""
        from PyQt5.QtWidgets import QMessageBox
        import os
        data = None; sr = None
        try:
            import soundfile as sf
            data, sr = sf.read(path, dtype='float32', always_2d=False)
        except ImportError:
            # soundfile 없음 → scipy로 WAV만 지원
            if os.path.splitext(path)[1].lower() not in ('.wav',):
                _BrandBox.warning(self, _tx('File Error'),
                    _tx('Non-WAV formats require the soundfile package.\nInstall and restart:\n  pip install soundfile'))
                self.sig_file_btn.setChecked(False); return False
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
                _BrandBox.warning(self, _tx('File Error'), _tx('WAV read failed:\n{e2}').format(e2=e2))
                self.sig_file_btn.setChecked(False); return False
        except Exception as e:
            _BrandBox.warning(self, _tx('File Error'), _tx('Cannot read file:\n{e}').format(e=e))
            self.sig_file_btn.setChecked(False); return False
        if data.ndim == 2:
            data = data.mean(axis=1)      # 스테레오 → 모노 믹스다운
        if sr != self.sample_rate:        # 샘플레이트 변환 (선형 보간)
            n_new = max(1, int(len(data) * self.sample_rate / sr))
            data = np.interp(np.linspace(0, len(data)-1, n_new),
                             np.arange(len(data)), data).astype(np.float32)
        pk = float(np.max(np.abs(data)))
        if pk > 1e-6: data = (data / pk * 0.9).astype(np.float32)  # 피크 정규화
        self._audio_file_buf = data
        fname = os.path.basename(path)
        self.sig_file_btn.setText(f'{fname[:12]}{"…" if len(fname)>12 else ""}')  # folder 아이콘 유지
        self.sig_file_btn.setChecked(True)
        self.sig_pink_btn.setChecked(False); self.sig_white_btn.setChecked(False)
        self.sig_sine_btn.setChecked(False); self.sig_sweep_btn.setChecked(False)
        self._update_sig_type_label()
        return True

    # ── 드래그&드롭: 오디오 파일을 창에 떨궈서 File 측정 신호로 로드 ──
    _DND_AUDIO_EXT = ('.wav', '.flac', '.aiff', '.aif', '.ogg', '.mp3', '.m4a', '.caf')

    def _dnd_audio_path(self, event):
        """드롭 이벤트에서 지원 오디오 파일 로컬 경로 1개를 추출, 없으면 None."""
        md = event.mimeData()
        if not md.hasUrls():
            return None
        import os
        for url in md.urls():
            if not url.isLocalFile():
                continue
            p = url.toLocalFile()
            if os.path.splitext(p)[1].lower() in self._DND_AUDIO_EXT:
                return p
        return None

    def dragEnterEvent(self, event):
        if self._dnd_audio_path(event) is not None:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if self._dnd_audio_path(event) is not None:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        path = self._dnd_audio_path(event)
        if path is None:
            event.ignore(); return
        event.acceptProposedAction()
        # 신호 스트림이 열려 있으면 완전 종료 후 버튼 리셋 (_pick_audio_file과 동일 패턴)
        if (self._duplex_thread is not None and self._duplex_thread.isRunning()) or \
                (self._sig_stream is not None):
            self._stop_sig_gen()
            self.sig_on_btn.setChecked(False)
            self.sig_on_btn.setText('Play'); self._style_sig_play(False)
        if self._load_audio_file(path):
            # sig_file_btn 텍스트가 파일명으로 바뀌어 피드백됨. 상태줄에도 잠깐 표기.
            if hasattr(self, 'status_lbl'):
                self.status_lbl.setText('● File loaded')
                QTimer.singleShot(1400, lambda: self.status_lbl.setText(
                    '● Running' if self._running else '● Standby'))

    def _start_sig_gen(self):
        _alog.debug(f'_start_sig_gen() called  sig_stream={self._sig_stream}  duplex={self._duplex_thread}')
        # [DIAG] 스윕→핑크 등 소스 전환 재생 디버그: 진입 시점 상태(이전 스윕 잔여/스트림 생존)
        _src = ('file' if self.sig_file_btn.isChecked() else 'white' if self.sig_white_btn.isChecked()
                else 'sine' if self.sig_sine_btn.isChecked() else 'sweep' if self.sig_sweep_btn.isChecked() else 'pink')
        _diag('sig_start', src=_src, sweep_freeze=getattr(self, '_sweep_freeze', False),
              duplex_alive=(self._duplex_thread is not None and self._duplex_thread.isRunning()),
              sig_stream=(self._sig_stream is not None))
        self._sweep_freeze = False    # 새 측정 시작 → 라이브 렌더 동결 해제(이전 스윕 결과 표시 종료)
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
        elif self.sig_sine_btn.isChecked():
            # 사인파: 정수 사이클로 버퍼를 만들어 루프 이음새 클릭 제거
            _n_sine = self.sample_rate * 10
            _f0 = max(10.0, float(self._sine_freq))
            _k = max(1, int(round(_f0 * _n_sine / self.sample_rate)))   # 버퍼 내 정수 사이클 수
            _f_act = _k * self.sample_rate / _n_sine                    # 실제 주파수(요청값과 <0.05Hz 차)
            _t = np.arange(_n_sine, dtype=np.float64)
            self._pink_buf = np.sin(2*np.pi*_f_act*_t/self.sample_rate).astype(np.float32)
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
            self.sig_on_btn.setChecked(True); self.sig_on_btn.setText('Stop'); self._style_sig_play(True)
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
                _BrandBox.warning(self, _tx('Signal Generator'), _tx('Select a Measurement device first.'))
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
                _BrandBox.information(self, _tx('Sweep 1-Shot Measurement'),
                    _tx('Sweep 1-shot IR measurement is only supported\nwhen the input (Measurement) and output (Signal Out)\nare on the same device.\n\nUse an external audio interface to route\nboth input and output through the same device.'))
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
                self.sig_on_btn.setChecked(True); self.sig_on_btn.setText('Stop'); self._style_sig_play(True)
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
            self._standalone_cb_fired = [False]   # [DIAG] 첫 콜백 수신 — 콜드오픈 콜백 미시작(무음) 추적

            # lvl_r: 뮤터블 컨테이너 — 레벨 변경이 실행 중 스트림에 즉시 반영됨
            lvl_r = [self._sig_level_lin]; self._sig_lvl_ref = lvl_r
            buf_r = self._standalone_buf_r; pos_r = [0]
            out_ch  = self.sig_out_ch_cb.currentData() or 0
            out_ch2 = self.sig_out_ch2_cb.currentData()   # None = Off
            # 무끊김 채널변경: 디바이스 전체 출력채널로 스트림을 열고, 콜백은 가변 참조(_sig_out_ch_ref)로
            # 출력 채널을 고른다 → 같은 장치 내 채널 변경 시 스트림 재오픈 없이 참조만 갱신(끊김 0).
            try: _dev_out_n = int(sd.query_devices(out_dev)['max_output_channels'])
            except Exception: _dev_out_n = 0
            n_ch = max(_dev_out_n, out_ch + 1, (out_ch2 + 1) if out_ch2 is not None else 0)
            self._sig_out_ch_ref = [out_ch, out_ch2]
            _och_ref = self._sig_out_ch_ref
            _blk_size = 2048
            out_blk = np.zeros(_blk_size, dtype=np.float32)  # 콜백 외부에서 사전 할당
            _ir_buf = self._int_ref_buf; _ir_pos = self._int_ref_pos
            _sg_muted = self._standalone_muted
            _sg_xrun  = self._standalone_xrun
            _sg_fired = self._standalone_cb_fired
            _sg_fade_frames = int(self.sample_rate * 0.05)
            _sg_ramp = np.linspace(0.0, 1.0, _sg_fade_frames, dtype=np.float32)
            _sg_fade_pos = self._standalone_fade_pos
            def cb(outdata, frames, ti, status):
                _sg_fired[0] = True   # 플래그 write만(I/O 아님) — GUI 워치독이 미시작 판정
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
                outdata[:] = 0
                _oc = _och_ref[0]; _oc2 = _och_ref[1]   # 가변 참조 — 라이브 채널 변경 즉시 반영
                if _oc is not None and _oc < outdata.shape[1]:
                    outdata[:, _oc] = out_blk[:frames]
                if _oc2 is not None and _oc2 < outdata.shape[1]:
                    outdata[:, _oc2] = out_blk[:frames]
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
                                                            latency='high', callback=cb,
                                                            extra_settings=_win_extra_settings())
                        self._sig_stream.start()
                    try:
                        _alog.info(f'[DIAG] OutputStream started out={out_dev} ch={n_ch} '
                                   f'req(bs={_blk_size},lat=high) actual(bs={self._sig_stream.blocksize},lat={self._sig_stream.latency})')
                    except Exception:
                        _alog.debug(f'  OutputStream started  out={out_dev} sr={self.sample_rate} ch={n_ch}')
                    # [DIAG] 콜드오픈 콜백 미시작(무음) 워치독: 2초 내 첫 콜백 없으면 로그.
                    # 재현 로그로 재오픈 워치독 넣을 경로 확정용(동작 변경 없음, 진단만).
                    def _sig_cb_watchdog(_fired=self._standalone_cb_fired, _od=out_dev):
                        if self._sig_stream is not None and not _fired[0]:
                            _diag('sig_cb_dead', dev=_od)   # ⚠️OutputStream 콜백 2초간 미시작 = 무음 후보
                    QTimer.singleShot(2000, _sig_cb_watchdog)
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
                        _BrandBox.warning(self, _tx('Signal Generator'), _tx('Output device error:\n{e}').format(e=e)); return

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

        self.sig_on_btn.setChecked(True); self.sig_on_btn.setText('Stop'); self._style_sig_play(True)
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
        self.sig_on_btn.setText('Play'); self._style_sig_play(False); self.sig_on_btn.setChecked(False)
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
        self.sig_on_btn.setText('Play'); self._style_sig_play(False); self.sig_on_btn.setChecked(False)
        self.sig_on_btn.setStyleSheet(f'background:{T("panel")};color:{T("text_dim")};'
                                       f'border:1px solid {T("border")};padding:4px;border-radius:{RADIUS_CTRL}px;font-weight:bold;')
        self._stop_input_monitor()   # 제너레이터 정지 → 입력 모니터도 정지 (카드 레벨미터는 분석 시에만)

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
                                        dtype='float32',
                                        extra_settings=_win_extra_settings()) as _s:
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


# Loudness DSP — v2.0 분해: spectra/dsp/loudness.py 로 이동, 여기로 re-import(동작 불변)
from spectra.dsp.loudness import _biquad, _KWeightFilter, LoudnessMeter


# 브랜드 색상 헬퍼 — v2.0 분해: spectra/ui/colors.py 로 이동, re-import
from spectra.ui.colors import _spec_color, _brand_color, _rgba_css, _metric_col


class VectorscopeCanvas(QWidget):
    """L/R Lissajous 벡터스코프 + 위상 상관도 미터."""
    _BUF=4096
    popout_requested = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setMinimumSize(200,200)
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
        _spec_color = _brand_color   # SPECTRA 브랜드 그라디언트로 스코프 재색 (이 메서드 한정)
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        W, H = self.width(), self.height()
        dark = (is_dark())
        def ov(a): return QColor(255, 255, 255, a) if dark else QColor(26, 38, 62, a)
        p.fillRect(0, 0, W, H, QColor(2, 2, 4) if dark else QColor(T('bg')))
        # 하단에 상관(correlation) 바+라벨이 있어 레이더보다 바닥 여유를 더 줌(작은 창 잘림 방지)
        sz = min(W - 92, H - 98); cx = W // 2; cy = 28 + sz // 2
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
        self.setMinimumSize(200,200)
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

    def set_target(self, lufs):
        """타겟 LUFS 변경 — 즉시 재그려서 정지 중에도 타겟 링이 바로 반영(Start 불필요)."""
        self.target = float(lufs); self.update()

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
        # SPECTRA 브랜드 그라디언트로 라우드니스 매핑 (조용=파랑 → 큼=빨강)
        if lufs <= -100: return QColor(0, 0, 0, 0)
        lufs = max(-52.0, min(2.0, lufs))
        t = (lufs - (-52.0)) / (2.0 - (-52.0))
        alpha = int(200 + 55 * t)
        return _brand_color(t, 160, alpha)

    def paintEvent(self, ev):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        W, H = self.width(), self.height()
        dark = (is_dark())
        def ov(a): return QColor(255, 255, 255, a) if dark else QColor(26, 38, 62, a)
        p.fillRect(0, 0, W, H, QColor(1, 1, 3) if dark else QColor(T('bg')))
        _spec_color = _brand_color   # SPECTRA 브랜드 그라디언트로 레이더 재색 (이 메서드 한정)

        # ── Layout ────────────────────────────────────────────────
        PAD_H = 46; PAD_T = 28; PAD_B = 64   # 바닥 라벨 잘림 방지 여유 확대
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
        # 외부 미터를 타겟 중심으로 재배치 — 타겟 LUFS가 12시(상단 중앙)에 오도록.
        M_START_Q = 225.0   # Qt 각도: 7:30 위치 (스케일 시작, 조용한 끝)
        M_SPAN_Q  = 300.0   # 시계방향 300°
        M_SPAN_LU = 54.0    # 보이는 총 범위(LU) — 기존과 동일한 눈금 밀도
        # 상단 중앙(Qt 90°)의 프랙션 = (225-90)/300 = 0.45 → 이 지점 값이 target이 되도록
        _f_top = (M_START_Q - 90.0) / M_SPAN_Q
        M_LO = self.target - _f_top * M_SPAN_LU
        M_HI = M_LO + M_SPAN_LU
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
        # 타겟 중심으로 6 LU 간격 라벨 동적 생성 (타겟이 상단 중앙에 깔끔히 표시)
        _c = round(self.target)
        lbl_vals = []
        v = _c
        while v >= M_LO: lbl_vals.append(v); v -= 6
        v = _c + 6
        while v <= M_HI: lbl_vals.append(v); v += 6
        lbl_vals.sort()
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


class _GradientNumber(QWidget):
    """SPECTRA 브랜드 그라디언트로 그리는 초대형 숫자 (Program Loudness 히어로).
    ★폰트 크기를 '폭'으로만 결정(높이 무관)+상한 → 카드가 아무리 커져도 위젯 높이는 sizeHint
    로 고정되어 늘어나지 않음. 따라서 위/아래 stretch가 빈 공간을 흡수해 sub줄을 절대 안 밀어냄."""
    def __init__(self, size=120, scale=1.0):
        super().__init__()
        self._text = '—'; self._size = size; self._scale = scale
        # 세로 Expanding → 카드가 커지면 위젯도 커져 숫자도 커짐. 폰트는 '실제 높이*0.58'(보수적)
        # 이라 글리프가 위젯 안에 여유롭게 들어가고, 위/아래 stretch가 sub줄 공간을 항상 확보.
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumHeight(56)
    def _fs_paint(self):
        # 위젯 실제 높이에 비례(짧은 카드=작게, 큰 카드=크게) + 폭/상한. 0.56 은 글리프가 위젯
        # 안에 충분히 들어가는 보수값(세로 잘림 방지).
        return max(18, int(min(int(self.height() * 0.56), int(self.width() * 0.26), 160) * self._scale))
    def sizeHint(self):
        return QSize(220, 140)
    def setText(self, t):
        if t != self._text: self._text = t; self.update()
    def text(self): return self._text
    def paintEvent(self, e):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        r = self.rect()
        if self._text in ('—', ''):
            # 빈 상태(미실행): 작고 가는 대시(회색 막대처럼 안 보이게)
            fs = max(18, int(self._fs_paint() * 0.34))
            f = QFont(FONT_NUM, fs); f.setWeight(QFont.Normal); p.setFont(f)
            p.setPen(QColor(T('text_dim')))
        else:
            fs = self._fs_paint()
            f = QFont(FONT_NUM, fs); f.setWeight(QFont.Black); p.setFont(f)
            p.setPen(QPen(QBrush(_spectra_grad_obj(r.left() + r.width() * 0.14,
                                                    r.left() + r.width() * 0.86)), 1))
        p.drawText(r, Qt.AlignCenter, self._text)


class LoudnessHistoryCanvas(QWidget):
    """Short-term 라우드니스 시간 그래프 — 브랜드 그라디언트 채움 + 타겟선."""
    _LO = -42.0; _HI = 0.0
    _WINDOW_S = 60.0      # 레이더와 동일한 60초 윈도우
    _STEP_S   = 0.1       # 0.1초마다 한 점 (600점 = 60초)
    def __init__(self):
        super().__init__()
        self._vals = deque(maxlen=int(self._WINDOW_S / self._STEP_S)); self._target = -23.0
        self._last_t = 0.0
        self.setMinimumHeight(110)
    def set_target(self, t): self._target = float(t); self.update()
    def push(self, v):
        # 오디오 블록마다(~10ms) 들어오지만 0.1초 간격으로만 적재 → 60초 윈도우
        if v <= -100: return
        now = time.monotonic()
        if now - self._last_t < self._STEP_S: return
        self._last_t = now
        self._vals.append(float(v)); self.update()
    def reset(self): self._vals.clear(); self._last_t = 0.0; self.update()
    def paintEvent(self, e):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        dark = (is_dark()); W, H = self.width(), self.height()
        p.fillRect(0, 0, W, H, QColor(8, 8, 10) if dark else QColor(T('bg')))
        pad = 8
        def y(v):
            t = max(0.0, min(1.0, (v - self._LO) / (self._HI - self._LO)))
            return H - pad - (H - 2 * pad) * t
        # label
        p.setPen(QColor(T('text_dim'))); p.setFont(QFont(FONT_NUM, FS_SM))
        p.drawText(10, 16, 'LOUDNESS HISTORY  (short-term)')
        # target dashed line
        ty = y(self._target)
        p.setPen(QPen(QColor(T('green')), 1, Qt.DashLine)); p.drawLine(0, int(ty), W, int(ty))
        vals = list(self._vals)
        if len(vals) < 2:
            # 빈 상태 — 측정 전 휑함 방지 안내 (타겟 점선은 위에 이미 그려짐)
            p.setPen(QColor(T('text_dim'))); p.setFont(QFont(FONT_NUM, FS_BODY))
            # 타겟 점선과 안 겹치게 상단 1/3 위치에 안내
            p.drawText(QRectF(0, H*0.18, W, H*0.30), Qt.AlignCenter,
                       'Start measuring to plot loudness over 60s' if cur_lang() != 'ko'
                       else '측정을 시작하면 최근 60초 라우드니스가 그려집니다')
            return
        # short-term 값은 블록 단위로 갱신돼 그대로 이으면 계단처럼 보인다.
        # 표시용으로만 가벼운 이동평균을 거쳐 단차를 완화한 뒤 곡선으로 그린다.
        n = len(vals)
        if n >= 5:
            k = 4  # ±4 샘플 이동평균(저장값은 그대로, 화면만 부드럽게)
            sm = []
            for i in range(n):
                a = max(0, i - k); b = min(n, i + k + 1)
                sm.append(sum(vals[a:b]) / (b - a))
            vals = sm
        # 점 좌표 산출
        pts = [(W * i / (n - 1), y(v)) for i, v in enumerate(vals)]
        # Catmull-Rom 스플라인 → 베지어로 변환해 부드러운 곡선 생성
        path = QPainterPath(); path.moveTo(*pts[0])
        for i in range(n - 1):
            p0 = pts[i - 1] if i > 0 else pts[0]
            p1 = pts[i]; p2 = pts[i + 1]
            p3 = pts[i + 2] if i + 2 < n else pts[n - 1]
            c1 = (p1[0] + (p2[0] - p0[0]) / 6.0, p1[1] + (p2[1] - p0[1]) / 6.0)
            c2 = (p2[0] - (p3[0] - p1[0]) / 6.0, p2[1] - (p3[1] - p1[1]) / 6.0)
            path.cubicTo(c1[0], c1[1], c2[0], c2[1], p2[0], p2[1])
        g = QLinearGradient(0, H, 0, 0)
        g.setColorAt(0.0, QColor('#1FA2FF')); g.setColorAt(0.5, QColor('#9B5DE5')); g.setColorAt(1.0, QColor('#FF453A'))
        # filled area
        fp = QPainterPath(path); fp.lineTo(W, H); fp.lineTo(0, H); fp.closeSubpath()
        gf = QLinearGradient(0, H, 0, 0)
        c0 = QColor('#1FA2FF'); c0.setAlpha(8); c1 = QColor('#FF453A'); c1.setAlpha(70)
        gf.setColorAt(0.0, c0); gf.setColorAt(1.0, c1)
        p.setBrush(QBrush(gf)); p.setPen(Qt.NoPen); p.drawPath(fp)
        p.setPen(QPen(QBrush(g), 2.0)); p.setBrush(Qt.NoBrush); p.drawPath(path)


class StereoLoudnessPage(QWidget):
    """벡터스코프 + 라우드니스 레이더를 담는 탭 페이지."""
    error_signal = pyqtSignal(str)   # MainWindow가 버튼 리셋에 사용

    def __init__(self):
        super().__init__()
        self._sub=None; self._meter=None; self._running=False
        self._l_ch=0; self._r_ch=1
        self._target=-23.0; self._lu_mode=False; self._unit_lbls={}
        self._build_ui()

    def _build_ui(self):
        # 시안C 카드형 레이아웃: 모든 요소를 둥근 카드에 배치 (검정 배경 위 카드 부유)
        root=QVBoxLayout(self); root.setContentsMargins(12,12,12,12); root.setSpacing(12)
        self.setStyleSheet('StereoLoudnessPage{background:%s;}' % (T('bg') if is_dark() else T('bg')))
        self._vseps = []; self._metric_meta = []

        # ── Row 1: 벡터스코프 | 레이더 | PROGRAM 히어로 ──
        self._vs=VectorscopeCanvas(); self._radar=LoudnessRadarCanvas()
        self._vs.popout_requested.connect(self._popout_vs)
        self._radar.popout_requested.connect(self._popout_radar)
        self._vs_win=None; self._radar_win=None
        self._vs_card,  self._vs_card_l  = self._card(self._vs, pad=8)
        self._radar_card, self._radar_card_l = self._card(self._radar, pad=8)
        self._hero_card, _ = self._card(self._build_hero_panel(), pad=12)
        row1=QHBoxLayout(); row1.setSpacing(12)
        # 스코프/레이더를 자주 보므로 비중을 키움(기존 1:1:2 → 5:5:6) + 행 높이 확대
        row1.addWidget(self._vs_card,5); row1.addWidget(self._radar_card,5); row1.addWidget(self._hero_card,6)
        rw1=QWidget(); rw1.setLayout(row1); rw1.setMinimumHeight(280); rw1.setMaximumHeight(560)
        root.addWidget(rw1,3)   # 창 커지면 스코프/레이더도 커지게(최대 560까지 우선 확장)

        # ── Row 2: 메트릭 카드 6개 ──
        specs=[('M  MOMENTARY','LUFS','_lbl_M',203,158,
                _tx('Momentary loudness (~400ms moving average)\nFastest-responding level indicator — reflects right now.')),
               ('S  SHORT-TERM','LUFS','_lbl_S',224,156,
                _tx('Short-term loudness (3s moving average)\nShows average level over a short window.')),
               ('TRUE PEAK','dBTP','_lbl_TP',4,168,
                _tx('True Peak (4× oversampled — detects inter-sample peaks)\nAbove 0 dBFS risks clipping. Broadcast/streaming typically requires ≤ −1 dBTP.')),
               ('LRA','LU','_lbl_LRA',270,160,
                _tx('Loudness Range (EBU 3342) — difference between quiet and loud sections\nHigher = wider dynamic range. Music: 5–15 LU; drama/ads: narrower.')),
               ('PLR  pk/loud','LU','_lbl_PLR',326,162,
                _tx('Peak-to-Loudness Ratio = True Peak − Integrated\nOverall dynamic headroom. Higher = more dynamic; lower = heavily compressed master.')),
               ('PSR  pk/short','LU','_lbl_PSR',320,162,
                _tx('Peak-to-Short-term Ratio = True Peak − Short-term\nTransient dynamics / limiting severity. Low value = over-limiting.'))]
        row2=QHBoxLayout(); row2.setSpacing(10)
        for title,unit,attr,hue,light,tip in specs:
            row2.addWidget(self._metric_card(title,unit,attr,hue,light,tip),1)
        row2.addWidget(self._build_target_ctrl(),0)
        rw2=QWidget(); rw2.setLayout(row2); rw2.setFixedHeight(74)   # 콘텐츠에 맞춰 타이트(빈 하단 띠 제거)
        root.addWidget(rw2,0)

        # ── Row 3: 히스토리 | 컴플라이언스 ──
        self._hist=LoudnessHistoryCanvas()
        hist_card,_=self._card(self._hist, pad=8)
        row3=QHBoxLayout(); row3.setSpacing(12)
        row3.addWidget(hist_card,2); row3.addWidget(self._build_compliance_card(),1)
        rw3=QWidget(); rw3.setLayout(row3); rw3.setMinimumHeight(150)   # history 최소 보장
        root.addWidget(rw3,2)

        self._disp_timer=QTimer(self)
        self._disp_timer.timeout.connect(self._refresh_display)
        self._disp_timer.start(80)

    # ── 카드 헬퍼 ────────────────────────────────────────────────
    def _card_bg_ss(self, obj='stCard', radius=14):
        """카드 배경 스타일 — 다크 고정 hex / 라이트는 T() 토큰. 테마 토글 시 재적용용."""
        dark=(is_dark())
        return '#%s{background:%s;border:1px solid %s;border-radius:%dpx;}' % (
            obj, ('#141416' if dark else T('panel')),
            ('#2A2A2C' if dark else T('border')), radius)

    def _card(self, inner, pad=8):
        f=QFrame(); f.setObjectName('stCard')
        f.setStyleSheet(self._card_bg_ss('stCard', 14))
        getattr(self, '_card_frames', self.__dict__.setdefault('_card_frames', [])).append((f, 'stCard', 14))
        lay=QVBoxLayout(f); lay.setContentsMargins(pad,pad,pad,pad); lay.setSpacing(0); lay.addWidget(inner)
        return f, lay

    def _metric_card(self, title, unit, attr, hue, light, tip=''):
        col=_metric_col(hue,light)
        f=QFrame(); f.setObjectName('stMc')
        f.setStyleSheet(self._card_bg_ss('stMc', 12))
        getattr(self, '_card_frames', self.__dict__.setdefault('_card_frames', [])).append((f, 'stMc', 12))
        if tip: f.setToolTip(tip)
        h=QHBoxLayout(f); h.setContentsMargins(12,8,10,8); h.setSpacing(9)
        bar=QFrame(); bar.setFixedWidth(4)
        bar.setStyleSheet(f'background:{col};border:none;border-radius:2px;')
        colw=QWidget(); colw.setStyleSheet('background:transparent;')
        v=QVBoxLayout(colw); v.setContentsMargins(0,0,0,0); v.setSpacing(1)
        t=QLabel(title); t.setStyleSheet(f'font-size:{FS_SM}px;color:{self._metric_lbl_col()};letter-spacing:0.5px;background:transparent;')
        valrow=QWidget(); valrow.setStyleSheet('background:transparent;')
        vr=QHBoxLayout(valrow); vr.setContentsMargins(0,0,0,0); vr.setSpacing(3)
        val=QLabel('—'); val.setStyleSheet(f'font-size:{FS_METRIC}px;font-weight:bold;color:{col};background:transparent;')
        u=QLabel(unit); u.setStyleSheet(f'font-size:{FS_XS}px;color:{self._metric_lbl_col()};background:transparent;')
        u.setAlignment(Qt.AlignLeft|Qt.AlignBottom)
        vr.addWidget(val); vr.addWidget(u); vr.addStretch()
        v.addWidget(t); v.addWidget(valrow)
        h.addWidget(bar); h.addWidget(colw,1)
        if tip:
            for x in (colw, t, valrow, val, u, bar): x.setToolTip(tip)
        setattr(self, attr, val); self._unit_lbls[attr]=u
        self._metric_meta.append((attr,hue,light,False,t,u))
        return f

    def _build_compliance_card(self):
        f=QFrame(); f.setObjectName('stCard')
        f.setStyleSheet(self._card_bg_ss('stCard', 14))
        getattr(self, '_card_frames', self.__dict__.setdefault('_card_frames', [])).append((f, 'stCard', 14))
        self._comp_card=f
        v=QVBoxLayout(f); v.setContentsMargins(18,13,18,16); v.setSpacing(11)
        title=QLabel('COMPLIANCE'); title.setAlignment(Qt.AlignHCenter); self._compliance_title = title
        title.setStyleSheet(f'font-size:{FS_SM}px;color:{self._metric_lbl_col()};letter-spacing:1px;background:transparent;')
        v.addWidget(title)
        v.addStretch()

        # ── 상태 원형 배지 — 틴트 채움 + 컬러 링 + 글리프(거대 사각 배너 대체) ──
        self._comp_circle=_ComplianceBadge()
        cc=QHBoxLayout(); cc.addStretch(); cc.addWidget(self._comp_circle); cc.addStretch()
        v.addLayout(cc)

        # ── 상태 문구 + 설명 한 줄(정성 — 수치 아님) ──────────────────
        self._lbl_comp=QLabel('—'); self._lbl_comp.setAlignment(Qt.AlignHCenter)
        v.addWidget(self._lbl_comp)
        self._lbl_comp_sub=QLabel('—'); self._lbl_comp_sub.setAlignment(Qt.AlignHCenter)
        self._lbl_comp_sub.setStyleSheet(f'font-size:{FS_SM}px;color:{self._metric_lbl_col()};background:transparent;')
        v.addWidget(self._lbl_comp_sub)
        v.addStretch()
        self._style_comp_banner(T('text_dim'), '—')
        return f

    def _style_comp_banner(self, col, glyph='—'):
        """상태 원형 배지(틴트 채움+컬러 링+글리프) + 상태 문구 색을 상태색(col)으로 통일."""
        self._comp_circle.set_state(col, glyph)
        self._lbl_comp.setStyleSheet(
            f'font-size:{FS_LG+1}px;font-weight:bold;color:{col};'
            f'letter-spacing:1.5px;background:transparent;')

    def _metric_lbl_col(self):
        return '#E2E4E9' if is_dark() else T('text_dim')

    def _build_hero_panel(self):
        """시안C 히어로 — PROGRAM LOUDNESS. AVG(Integrated) | LIVE(Short-term) 양쪽 동시 표기."""
        w = QWidget(); w.setStyleSheet('background:transparent;')
        vl = QVBoxLayout(w); vl.setContentsMargins(16, 10, 16, 16); vl.setSpacing(4)
        self._hero_live = False   # 구버전 상태 호환(더 이상 토글 안 함 — 양쪽 동시 표시)

        self._lbl_hero_title = QLabel('PROGRAM LOUDNESS'); self._lbl_hero_title.setAlignment(Qt.AlignHCenter)
        self._lbl_hero_title.setStyleSheet(f'font-size:{FS_BODY}px;color:{self._metric_lbl_col()};'
                          f'letter-spacing:2px;background:transparent;')
        vl.addWidget(self._lbl_hero_title)
        vl.addStretch()

        # ── AVG(Integrated) | LIVE(Short-term) 2분할 ──────────────────
        row = QWidget(); row.setStyleSheet('background:transparent;')
        rl = QHBoxLayout(row); rl.setContentsMargins(0, 0, 0, 0); rl.setSpacing(0)

        def _half(cap, tip, scale, primary):
            col = QWidget(); col.setStyleSheet('background:transparent;')
            cv = QVBoxLayout(col); cv.setContentsMargins(0, 0, 0, 0); cv.setSpacing(2)
            # 위계: AVG(주)=액센트 캡션, LIVE(부)=흐린 캡션
            cap_col = T('accent') if primary else T('text_dim')
            cap_lbl = QLabel(cap); cap_lbl.setAlignment(Qt.AlignHCenter); cap_lbl.setToolTip(tip)
            cap_lbl.setStyleSheet(f'font-size:{FS_SM}px;color:{cap_col};'
                                  f'letter-spacing:2px;font-weight:bold;background:transparent;')
            num = _GradientNumber(120, scale=scale)
            sub = QLabel('—'); sub.setAlignment(Qt.AlignHCenter)
            sub.setStyleSheet(f'font-size:{FS_LG}px;color:{T("text_dim")};background:transparent;')
            cv.addWidget(cap_lbl); cv.addWidget(num, 3); cv.addWidget(sub)
            return col, cap_lbl, num, sub

        # AVG·LIVE 동일 크기(좌우 대칭) — 구분은 캡션 색으로만(AVG 액센트 / LIVE 흐림)
        avg_col, self._cap_avg, self._lbl_I, self._sub_avg = _half(
            'AVG', _tx('AVG — Integrated (cumulative average). Broadcast/streaming delivery reference'),
            scale=1.0, primary=True)
        live_col, self._cap_live, self._lbl_live, self._sub_live = _half(
            'LIVE', _tx('LIVE — Real-time (Short-term 3s). For monitoring during work'),
            scale=1.0, primary=False)

        div = QFrame(); div.setFrameShape(QFrame.VLine); div.setFixedWidth(1)
        div.setStyleSheet(f'color:{T("border")};background:transparent;')

        rl.addWidget(avg_col, 1); rl.addWidget(div); rl.addWidget(live_col, 1)
        vl.addWidget(row, 3)
        vl.addSpacing(12)
        # 하위호환: restyle/구코드가 참조하는 sub 핸들 → AVG sub로 매핑
        self._lbl_hero_sub = self._sub_avg
        return w

    def _seg_btn_ss(self, left):
        """히어로 모드 세그먼트 버튼 스타일(좌/우 라운드)."""
        rad = 'border-top-left-radius:6px;border-bottom-left-radius:6px;' if left \
              else 'border-top-right-radius:6px;border-bottom-right-radius:6px;'
        return (f"QPushButton{{background:{T('panel')};color:{T('text_dim')};"
                f"border:1px solid {T('border')};{rad}font-size:11px;font-weight:bold;}}"
                f"QPushButton:checked{{background:rgba(78,125,240,40);color:{T('accent')};"
                f"border:1px solid {T('accent')};}}")

    def _set_hero_mode(self, live):
        # 양쪽(AVG|LIVE) 동시 표기로 바뀌어 토글은 무의미 — 상태 호환만 유지.
        self._hero_live = bool(live)
        self._refresh_display(force=True)

    def loud_get_state(self):
        """페이지 내부 표시 상태(LU 모드 / AVG·LIVE). device·target·L/R 은 MainWindow 소관."""
        return {'lu_mode': bool(self._lu_mode), 'hero_live': bool(self._hero_live)}

    def loud_apply_state(self, d):
        try:
            if 'lu_mode' in d: self._lu_btn.setChecked(bool(d['lu_mode']))   # _on_lu_toggled 반영
        except Exception: pass
        try:
            if 'hero_live' in d: self._set_hero_mode(bool(d['hero_live']))
        except Exception: pass

    def _build_target_ctrl(self):
        """우측 컨트롤 — LU(타겟 상대) 표시 토글. 지표 카드들과 같은 카드 배경으로 묶어 '외톨이' 방지."""
        w = QFrame(); w.setObjectName('stMc'); w.setFixedWidth(64)
        w.setStyleSheet(self._card_bg_ss('stMc', 12))
        getattr(self, '_card_frames', self.__dict__.setdefault('_card_frames', [])).append((w, 'stMc', 12))
        vl = QVBoxLayout(w); vl.setContentsMargins(6, 8, 6, 8); vl.setSpacing(4)
        tl = QLabel('UNITS'); self._units_lbl = tl
        tl.setStyleSheet(f'font-size:{FS_SM}px;color:{self._metric_lbl_col()};'
                         f'letter-spacing:0.5px;background:transparent;')
        tl.setAlignment(Qt.AlignHCenter)
        self._lu_btn = QPushButton('LU'); self._lu_btn.setCheckable(True); self._lu_btn.setFixedSize(54, 24)
        self._lu_btn.setToolTip(_tx('LUFS ↔ LU (show relative value vs target)'))
        self._lu_btn.setStyleSheet(self._lu_btn_ss())
        self._lu_btn.setFocusPolicy(Qt.NoFocus)
        self._lu_btn.toggled.connect(self._on_lu_toggled)
        vl.addWidget(tl); vl.addWidget(self._lu_btn, 0, Qt.AlignHCenter)
        return w

    def _lu_btn_ss(self):
        # N2 — 투명+서브틀 테두리 / 활성=회색 채움(파랑 필 폐지, 세그먼트 트랙과 통일)
        _bd = '#34343B' if is_dark() else T('border')
        _fill, _fg = ('#42424A', '#FFFFFF') if is_dark() else ('#3A3A42', '#FFFFFF')
        _bd_h = '#4A4A54' if is_dark() else '#B7B7C0'
        return (f"QPushButton{{background:transparent;color:{T('text_dim')};border:1px solid {_bd};"
                f"border-radius:7px;font-size:11px;font-weight:bold;}}"
                f"QPushButton:hover{{color:{T('text')};border-color:{_bd_h};}}"
                f"QPushButton:checked{{background:{_fill};color:{_fg};border-color:{_fill};}}")

    def set_target(self, val):
        """상단 툴바 콤보가 호출 — 타겟 동기화 + 편차/표시 즉시 갱신."""
        self._target = float(val)
        self._radar.set_target(self._target)        # ★ 즉시 반영 (Start 불필요)
        if hasattr(self, '_hist'): self._hist.set_target(self._target)
        self._refresh_display(force=True)

    def _on_lu_toggled(self, on):
        self._lu_mode = bool(on)
        unit = 'LU' if on else 'LUFS'
        for attr in ('_lbl_M', '_lbl_S', '_lbl_I'):
            u = self._unit_lbls.get(attr)
            if u is not None:
                u.setText(unit)
        self._refresh_display(force=True)

    def restyle_theme(self):
        """테마 토글(다크↔라이트) 시 카드 메트릭 값색 + 스코프 재적용."""
        _lc = self._metric_lbl_col()
        for attr, hue, light, big, t_lbl, u_lbl in getattr(self, '_metric_meta', []):
            v = getattr(self, attr, None)
            if v is not None:
                v.setStyleSheet(f'font-size:{FS_METRIC}px;font-weight:bold;color:{_metric_col(hue, light)};background:transparent;')
            if t_lbl is not None:
                t_lbl.setStyleSheet(f'font-size:{FS_XS}px;color:{_lc};letter-spacing:0.5px;background:transparent;')
            if u_lbl is not None:
                u_lbl.setStyleSheet(f'font-size:{FS_XS}px;color:{_lc};background:transparent;')
        # ── 카드 배경 프레임 재적용 (PROGRAM/메트릭6/COMPLIANCE 등) — 다크 고정 hex/라이트 T()
        for f, obj, rad in getattr(self, '_card_frames', []):
            try: f.setStyleSheet(self._card_bg_ss(obj, rad))
            except Exception: pass
        # 페이지 배경 + 히어로/컴플라이언스 텍스트 + 세그/LU 버튼
        self.setStyleSheet('StereoLoudnessPage{background:%s;}' % T('bg'))
        if hasattr(self, '_lbl_hero_title'):
            self._lbl_hero_title.setStyleSheet(f'font-size:{FS_BODY}px;color:{_lc};'
                              f'letter-spacing:2px;background:transparent;')
        if hasattr(self, '_compliance_title'):
            self._compliance_title.setStyleSheet(f'font-size:{FS_SM}px;color:{_lc};letter-spacing:1px;background:transparent;')
        if hasattr(self, '_units_lbl'):
            self._units_lbl.setStyleSheet(f'font-size:{FS_SM}px;color:{_lc};letter-spacing:0.5px;background:transparent;')
        if hasattr(self, '_lu_btn'):
            self._lu_btn.setStyleSheet(self._lu_btn_ss())
        for _s in (getattr(self, '_sub_avg', None), getattr(self, '_sub_live', None)):
            if _s is not None:
                _s.setStyleSheet(f'font-size:{FS_LG}px;color:{T("text_dim")};background:transparent;')
        # 캡션 위계 유지: AVG(주)=액센트, LIVE(부)=흐림
        for _c, _col in ((getattr(self, '_cap_avg', None), T('accent')),
                         (getattr(self, '_cap_live', None), T('text_dim'))):
            if _c is not None:
                _c.setStyleSheet(f'font-size:{FS_SM}px;color:{_col};'
                                 f'letter-spacing:2px;font-weight:bold;background:transparent;')
        if hasattr(self, '_comp_circle'):
            self._style_comp_banner(T('text_dim'), self._comp_circle.glyph)
        if hasattr(self, '_lbl_comp_sub'):
            self._lbl_comp_sub.setStyleSheet(f'font-size:{FS_SM}px;color:{_lc};background:transparent;')
        self._refresh_display(force=True)
        if hasattr(self, '_hero_avg_btn'): self._hero_avg_btn.setStyleSheet(self._seg_btn_ss(left=True))
        if hasattr(self, '_hero_live_btn'): self._hero_live_btn.setStyleSheet(self._seg_btn_ss(left=False))
        if hasattr(self, '_lu_btn'):
            self._lu_btn.setStyleSheet(self._lu_btn_ss())
        if hasattr(self, '_lbl_I'): self._lbl_I.update()
        if hasattr(self, '_hist'): self._hist.update()
        if hasattr(self, '_vs'): self._vs.update()
        if hasattr(self, '_radar'): self._radar.update()
        for wn in (getattr(self, '_vs_win', None), getattr(self, '_radar_win', None)):
            if wn is not None: wn.setStyleSheet(f'background:{T("bg")};')

    # ── 팝아웃 ────────────────────────────────────────────────────────
    def _make_popout_win(self, canvas, title):
        # 부모 없는 독립 Qt.Window (Tool 제거) + 네이티브 collectionBehavior(_show_popout_normal에서 적용)
        # → 메인창 최소화에도 살아남고, 메인창 풀스크린 위에도 뜬다 (SPL 미터와 동일 방식).
        win = QWidget(None, Qt.Window)
        win.setWindowTitle(title)
        win.setStyleSheet(f'background:{T("bg")};')
        lay = QVBoxLayout(win); lay.setContentsMargins(0,0,0,0)
        lay.addWidget(canvas)
        # 흰색 네이티브 타이틀바 → 다른 팝업처럼 다크 브랜드 타이틀바(프레임리스+✕+리사이즈 그립)
        _apply_dark_titlebar(win, resizable=True)
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
        _set_float_above_fullscreen(win)   # 풀스크린 위 + 최소화 생존 (show 이후)
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
        self._vs_card_l.removeWidget(self._vs)
        self._vs_win = self._make_popout_win(self._vs, 'Vectorscope')
        def _vs_close(e): self._return_vs(); e.accept()
        self._vs_win.closeEvent = _vs_close
        self._show_popout_normal(self._vs_win)

    def _return_vs(self):
        if self._vs_win: self._vs_win.hide()
        self._vs_card_l.addWidget(self._vs)

    def _popout_radar(self):
        if self._radar_win and self._radar_win.isVisible(): return
        self._radar_card_l.removeWidget(self._radar)
        self._radar_win = self._make_popout_win(self._radar, 'Loudness Radar')
        def _radar_close(e): self._return_radar(); e.accept()
        self._radar_win.closeEvent = _radar_close
        self._show_popout_normal(self._radar_win)

    def _return_radar(self):
        if self._radar_win: self._radar_win.hide()
        self._radar_card_l.addWidget(self._radar)

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
        if hasattr(self, '_hist'): self._hist.reset()

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
        if m.S>-100: self._hist.push(m.S)

    def _on_error(self,msg):
        self.stop()
        _alog.warning(f'StereoAudio 오류: {msg}')
        self.error_signal.emit(msg)

    def _refresh_display(self, force=False):
        m=self._meter
        if m is None: return
        if not self._running and not force: return
        if not force and not self.isVisible(): return  # 숨겨진 탭: 디스플레이 갱신 생략(보이는 탭 양보)
        def fmt(v):
            if v<=-100: return '—'
            return f'{v-self._target:+.1f}' if self._lu_mode else f'{v:.1f}'
        self._lbl_M.setText(fmt(m.M))
        self._lbl_S.setText(fmt(m.S))
        self._lbl_LRA.setText(f'{m.LRA:.1f}' if m.LRA>0 else '—')
        self._lbl_TP.setText(f'{m.peak_hold:.1f}' if m.peak_hold>-100 else '—')
        self._lbl_PLR.setText(f'{m.PLR:.1f}' if m.I>-100 else '—')
        self._lbl_PSR.setText(f'{m.PSR:.1f}' if m.S>-100 else '—')
        # True Peak: -1 dBTP 초과면 빨강 경고
        if m.peak_hold>-100:
            tpc=T('red') if m.peak_hold>-1.0 else _metric_col(4,168)
            self._lbl_TP.setStyleSheet(f'font-size:{FS_METRIC}px;font-weight:bold;color:{tpc};background:transparent;')
        # M 라벨 색상: target=-23 기준
        if m.M>-100:
            c=(T('green') if m.M<-20 else
               T('yellow') if m.M<-16 else T('red'))
            self._lbl_M.setStyleSheet(
                f'font-size:{FS_METRIC}px;font-weight:bold;color:{c};background:transparent;')
        # 히어로 — AVG(Integrated) | LIVE(Short-term) 동시 표기
        def _sub(v, tag):
            return '—' if v<=-100 else f'{tag}   ·   {v-self._target:+.1f} LU'
        self._lbl_I.setText(fmt(m.I));    self._sub_avg.setText(_sub(m.I, 'LUFS'))
        self._lbl_live.setText(fmt(m.S)); self._sub_live.setText(_sub(m.S, 'S'))
        # 컴플라이언스 카드 — 송출 기준값 = Integrated(I). 상태만 표시(수치 X)
        hv = m.I
        if hv>-100:
            dev=hv-self._target
            tp_over = (m.peak_hold>-100) and (m.peak_hold>-1.0)
            tp_ok = (not tp_over)
            if abs(dev)<=1.0 and tp_ok:
                status='PASS'; col=T('green'); glyph='✓'; sub=_tx('Meets target & true-peak')
            else:
                col=(T('yellow') if abs(dev)<=3.0 and tp_ok else T('red')); glyph='✕'
                if abs(dev)>1.0:
                    status='CHECK LOUDNESS'
                    sub=_tx('Loud — pull down') if dev>0 else _tx('Quiet — push up')
                else:
                    status='CHECK TRUE-PEAK'; sub=_tx('True peak over −1 dBTP')
            self._lbl_comp.setText(status); self._lbl_comp_sub.setText(sub)
            self._style_comp_banner(col, glyph)
        else:
            self._lbl_comp.setText('STANDBY'); self._style_comp_banner(T('text_dim'), '—')
            self._lbl_comp_sub.setText(_tx('Waiting for signal'))


class _TFPopoutWindow(QWidget):
    """TF를 별도 창으로 분리(멀티모니터)할 때 쓰는 컨테이너 창.
    창을 닫으면 MainWindow._dock_tf로 메인 탭에 되돌린다.
    ★부모 없는 독립 top-level 창 — macOS에서 부모를 주면 자식 창으로 묶여
    메인 창을 따라 움직이므로(외부 모니터 배치 방해), 부모 대신 _mainwin 참조만 보관."""
    def __init__(self, mainwin):
        super().__init__(None, Qt.Window)
        self._mainwin = mainwin
        self._docking = False
        self.setWindowTitle('SPECTRA — Transfer Function')
        self.setMinimumSize(1020, 570)

    def closeEvent(self, e):
        if not self._docking and self._mainwin is not None:
            self._mainwin._dock_tf(via_close=True)
        super().closeEvent(e)


class _SpectrumPopoutWindow(QWidget):
    """Spectrum을 별도 창으로 분리(멀티모니터). 닫으면 _dock_spec로 메인 탭에 되돌림.
    TF 팝아웃과 동형 — 부모 없는 독립 top-level(메인 안 따라감)."""
    def __init__(self, mainwin):
        super().__init__(None, Qt.Window)
        self._mainwin = mainwin
        self._docking = False
        self.setWindowTitle('SPECTRA — Spectrum')
        self.setMinimumSize(900, 520)

    def closeEvent(self, e):
        if not self._docking and self._mainwin is not None:
            self._mainwin._dock_spec(via_close=True)
        super().closeEvent(e)


class _StereoPopoutWindow(QWidget):
    """Stereo Loudness를 별도 창으로 분리(멀티모니터). 닫으면 _dock_st로 되돌림.
    부모 없는 독립 top-level(메인 안 따라감)."""
    def __init__(self, mainwin):
        super().__init__(None, Qt.Window)
        self._mainwin = mainwin
        self._docking = False
        self.setWindowTitle('SPECTRA — Stereo Loudness')
        self.setMinimumSize(900, 520)

    def closeEvent(self, e):
        if not self._docking and self._mainwin is not None:
            self._mainwin._dock_st(via_close=True)
        super().closeEvent(e)


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
        # CoreAudio 장치변경 리스너 — idle 상태 USB 핫플러그(새 인터페이스 꽂/뽑) 감지
        self._ca_watcher = _CoreAudioDeviceWatcher(self)
        self._ca_dev_count = None   # CoreAudio 장치 개수 기준선 — 감소 시 '장치 제거'로 판정
        self._ca_watcher.changed.connect(self._on_coreaudio_devices_changed)
        QTimer.singleShot(1200, self._ca_watcher.start)   # 창 떠서 안정된 뒤 등록
        QTimer.singleShot(1500, lambda: setattr(self, '_ca_dev_count', self._ca_watcher.device_count()))
        self.db_max=MAX_DB; self.db_range=96; self.db_min=self.db_max-self.db_range; self._db_lock=False
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
        self._spl_source_id = 0         # SPL 미터가 측정할 소스 카드 (0=primary, 그 외 _spec_extra id)
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
        self._tf_popout = None       # TF 별도 창(멀티모니터) — None=도킹 상태
        self._tf_placeholder = None  # 팝아웃 동안 main_stack index1 자리 채움
        self._spec_popout = None     # Spectrum 별도 창 — None=도킹 상태
        self._spec_placeholder = None  # 팝아웃 동안 main_stack index0 자리 채움
        self._st_popout = None       # Stereo 별도 창 — None=도킹 상태
        self._st_placeholder = None  # 팝아웃 동안 main_stack index2 자리 채움
        self._split_on = False       # 동시 보기(2칸 분할, 칸=탭 통째) 모드
        self._split_widget = None
        self._split_prev_tab = 0
        self.spl_meter_win = None
        self.spl_alarm_win = None
        self.show_mode_win = None

        self._disconnected_dev_name = ''   # USB 뽑힌 장치 이름 (Refresh 시 필터링용)
        self._first_device_load = True     # 시작 시 내장 마이크 폴백 여부 판단용

        # 설정 (마이크별 캘리브레이션)
        self._settings = _load_settings()
        self._presets_restoring = False
        self._session_timer = QTimer(self); self._session_timer.setSingleShot(True)
        self._session_timer.timeout.connect(self._save_session)

        self._build_ui()
        self._build_menubar()          # macOS 네이티브 메뉴바 (About/Quit/Help)
        self._load_devices()
        self._restore_spec_sources()   # 저장된 멀티-장치 추가 소스 카드 복원
        self._apply_theme()

        _sc = QShortcut(QKeySequence(Qt.Key_Space), self)
        _sc.setContext(Qt.ApplicationShortcut)
        _sc.activated.connect(self._space_capture)

        # S 키 = Spectrum/Stereo 탭 Start·Stop 토글 (이벤트필터 — 텍스트 입력칸에선 가로채지 않음)
        self._main_key_filter = _MainKeyFilter(self)
        QApplication.instance().installEventFilter(self._main_key_filter)

        QTimer.singleShot(0, self._setup_macos_titlebar)

        self._render_t=QTimer(self); self._render_t.timeout.connect(self._render_frame); self._render_t.start(33)

        # ── 세션 자동기억: preset 관련 컨트롤 시그널 → _mark_session_dirty 배선
        for _cb in (self.sr_cb, self.hold_cb, self.db_cb, self.spd_cb,
                    self._st_target_cb, self._st_l_cb, self._st_r_cb):
            try: _cb.currentIndexChanged.connect(self._mark_session_dirty)
            except Exception: pass
        for _b in (self.peak_btn, self.spectro_btn):
            try: _b.toggled.connect(self._mark_session_dirty)
            except Exception: pass
        try: self._view_seg.changed.connect(lambda *_: self._mark_session_dirty())
        except Exception: pass
        try: self._scale_seg.changed.connect(lambda *_: self._mark_session_dirty())
        except Exception: pass
        for _cb in (self.tf_win.eng_cb, self.tf_win.fft_cb, self.tf_win.avg_cb, self.tf_win.sm_cb,
                    self.tf_win.ir_cb, self.tf_win.phase_cb, self.tf_win.unit_cb):
            try: _cb.currentIndexChanged.connect(self._mark_session_dirty)
            except Exception: pass
        try: self.stereo_page._lu_btn.toggled.connect(self._mark_session_dirty)
        except Exception: pass

        # ── 시작 시 session 복원 (모든 위젯 존재 시점에서 deferred 실행)
        _sess = self._settings.get('session')
        if isinstance(_sess, dict):
            QTimer.singleShot(0, lambda: self._apply_app_state(_sess))

    # ─────────────────────────────────────
    def _setup_macos_titlebar(self):
        """ctypes로 NSFullSizeContentViewWindowMask + titlebarAppearsTransparent 적용.
        콘텐츠 뷰를 네이티브 타이틀바 영역까지 확장하여 hdr 위젯이 타이틀바 행에 렌더된다."""
        if _pl.system() == 'Windows':
            _apply_windows_titlebar_dark(self)   # 윈도우: 네이티브 타이틀바 다크(흰 바 충돌 제거)
            return
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
        self.lang_btn = QPushButton(); self.lang_btn.setIcon(_icon('globe'))
        self.lang_btn.setFixedSize(28, 28)
        self.lang_btn.setToolTip('Language · 언어')   # 언어 무관하게 양쪽 표기
        self.lang_btn.setStyleSheet(ss_btn_neutral() + 'QPushButton{padding:0;}')   # 아이콘 전용 타이트
        self.lang_btn.clicked.connect(self._on_lang_toggle)
        _right_lay.addWidget(self.lang_btn)
        # ── Preset 드롭다운 + Save + 삭제 (Calibration 앞)
        self._preset_cb = RoundComboBox(); self._preset_cb._align_center = True
        self._preset_cb.setFixedHeight(28); self._preset_cb.setMinimumWidth(120); self._preset_cb.setMaximumWidth(180)
        self._preset_cb.setToolTip(_tx('Load preset (applies all 3 tabs at once)'))
        self._preset_cb.currentIndexChanged.connect(self._on_preset_selected)
        _psqss = ss_btn_neutral() + 'QPushButton{padding:0;}'   # 아이콘 전용 — 패딩 제거해 테두리 타이트하게
        self._preset_save_btn = QPushButton(); self._preset_save_btn.setIcon(_icon('save')); self._preset_save_btn.setToolTip(_tx('Save preset'))
        self._preset_save_btn.setFixedSize(28, 28); self._preset_save_btn.setStyleSheet(_psqss); self._preset_save_btn.clicked.connect(self._on_preset_save)
        self._preset_del_btn = QPushButton(); self._preset_del_btn.setIcon(_icon('trash')); self._preset_del_btn.setToolTip(_tx('Delete preset'))
        self._preset_del_btn.setFixedSize(28, 28); self._preset_del_btn.setStyleSheet(_psqss); self._preset_del_btn.clicked.connect(self._on_preset_delete)
        _right_lay.addWidget(self._preset_cb); _right_lay.addWidget(self._preset_save_btn); _right_lay.addWidget(self._preset_del_btn)
        self._refresh_preset_cb()
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

        # N2 탭 — 트랙 없이 아이콘+이름, 활성=액센트 밑줄(툴바 언어와 통일)
        self._main_seg_pill = QWidget(); self._main_seg_pill.setObjectName('mainSegPill')
        self._main_seg_pill.setStyleSheet('#mainSegPill{background:transparent;}')
        tbl=QHBoxLayout(self._main_seg_pill); tbl.setContentsMargins(0,0,0,0); tbl.setSpacing(2)
        self._tab_btns={}
        _tab_defs=[('spectrum','audio-lines','Spectrum'),
                   ('transfer','git-compare','Transfer Function'),  # 기준↔측정 비교 — Smooth(곡선)과 겹침 회피
                   ('stereo','volume2','Stereo Loudness')]              # 음량 — Speed/Response(gauge)와 겹침 회피
        for idx,(key,icn,label) in enumerate(_tab_defs):
            b=_N2Tab(icn, label); b.setChecked(idx==0)
            b.clicked.connect(lambda i=idx: self._switch_tab(i))
            tbl.addWidget(b, 1); self._tab_btns[key]=b
        tbl_outer.addWidget(self._main_seg_pill, 1)
        # 툴바 접기/펴기 토글 — 탭바 우측(툴바를 숨겨도 항상 보이게)
        tbl_outer.addSpacing(8)
        self._toolbar_btn = _ToolbarToggleBtn()
        self._toolbar_btn.clicked.connect(self._toggle_toolbar)
        tbl_outer.addWidget(self._toolbar_btn)
        root.addWidget(self.tab_bar)
        # 탭 ↔ 메뉴(툴바) 구분 — 전체 폭 파란(액센트) 라인
        self.tab_menu_sep = QFrame(); self.tab_menu_sep.setObjectName('tabMenuSep')
        self.tab_menu_sep.setFixedHeight(2)
        root.addWidget(self.tab_menu_sep)

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
        self.dev_btn=QPushButton('Select Device')
        self.dev_btn.setMinimumWidth(100); self.dev_btn.setMaximumWidth(280); self.dev_btn.setFixedHeight(26)
        self.dev_btn.clicked.connect(self._show_device_popup)
        self.in_ch_cb=RoundComboBox(); self.in_ch_cb._align_center=True; self.in_ch_cb._grid_popup=True
        self.in_ch_cb.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.in_ch_cb.setMinimumWidth(50); self.in_ch_cb.setFixedHeight(26)
        self.in_ch_cb.addItem('Ch 1', 0)
        self.in_ch_cb.currentIndexChanged.connect(self._on_input_ch_changed)
        self.mic_st=QLabel()  # 숨김 — 내부 상태 참조용

        # ── Sub-controls stack (46px): 탭별 전용 컨트롤
        self.sub_stack=QStackedWidget(); self.sub_stack.setFixedHeight(46)   # wrapper(46)와 일치 — 탭 전환 시 높이 점프 방지
        self.sub_stack.setObjectName('subStack')

        # Sub-page 0: Spectrum 컨트롤 — N2 리디자인 (테두리리스 + 아이콘 + 모노값 + 단일 액센트)
        sp0=QWidget(); sl0=QHBoxLayout(sp0)
        sl0.setContentsMargins(10,0,10,0); sl0.setSpacing(0)
        _H = 34
        def _dv0():
            sl0.addSpacing(4); sl0.addWidget(_n2_divider()); sl0.addSpacing(4)
        # 드로어(캡쳐) 토글 (좌측) — panel-bottom 아이콘(하단 드로어), 우측 패널 토글과 동일 N2 룩
        self._drawer_btn = _N2IconBtn('panel-left', checkable=True); self._drawer_btn.setFixedHeight(_H)
        self._drawer_btn.setChecked(False)
        self._drawer_btn.setToolTip(_tx('Capture drawer'))
        self._drawer_btn.clicked.connect(self._toggle_capture_drawer)
        sl0.addWidget(self._drawer_btn); _dv0()
        # 전역 Start 버튼 폐지 — 카드별 LED 파워 점(측정 on/off)으로 대체. 버튼 객체는
        # 상태갱신(_refresh_running_ui)·테마·S키 토글 참조용으로만 유지(레이아웃 미추가·숨김).
        self.start_btn=_N2Button('play','Start (S)',accent_icon=True); self.start_btn.setFixedHeight(_H)
        self.start_btn.clicked.connect(self._toggle)
        sl0.addWidget(self.start_btn); self.start_btn.hide()
        # ── 분석/신호: View · +Spectro · Scale(FFT 전용) · SR ──
        self._view_seg = _N2Segmented(
            [('fft','FFT',42),('oct3','1/3',34),('oct12','1/12',42),('oct24','1/24',42)],
            icon_name='audio-lines', height=_H)
        self._view_seg.set_active('oct12')
        self._view_seg.changed.connect(self._set_view)
        sl0.addWidget(self._view_seg)
        # +Spectro 토글
        self.spectro_btn=_N2Toggle('rows-2', text='+Spectro'); self.spectro_btn.setFixedHeight(_H)
        self.spectro_btn.clicked.connect(self._toggle_spectro)
        sl0.addWidget(self.spectro_btn)
        # Scale 세그먼트 — FFT 뷰에서만 표시(옥타브는 로그 밴드라 무관). 앞 구분선도 함께 토글.
        self._scale_sep = _n2_divider()
        sl0.addSpacing(4); sl0.addWidget(self._scale_sep); sl0.addSpacing(4)
        self._scale_seg = _N2Segmented([('log','Log',36),('lin','Lin',36)], height=_H)
        self._scale_seg.set_active('log')
        self._scale_seg.changed.connect(lambda k: self._set_scale(k=='log'))
        sl0.addWidget(self._scale_seg)
        _init_fft = (getattr(self, 'view_mode', 'oct12') == 'fft')   # 기본 oct12 → Scale 숨김
        self._scale_seg.setVisible(_init_fft); self._scale_sep.setVisible(_init_fft)
        # SR (샘플레이트 — 측정 신호/엔진 설정)
        self.sr_cb=_N2Select('waves','SR',mono=True); self.sr_cb.setFixedHeight(_H)
        self.sr_cb.addItems(['44.1 kHz','48 kHz','88.2 kHz','96 kHz']); self.sr_cb.setCurrentIndex(1)
        self.sr_cb.currentIndexChanged.connect(self._sr_changed)
        sl0.addSpacing(4); sl0.addWidget(self.sr_cb); _dv0()
        # ── 레벨축: DB(스케일) · RANGE(dB 범위) ──
        self.spec_db_btn = _N2Button('scale-v','Auto',label='dB'); self.spec_db_btn.setFixedHeight(_H)
        self.spec_db_btn.setToolTip(_tx('dB axis range (click to fix top/bottom)'))
        self.spec_db_btn.clicked.connect(self._spec_db_control)
        sl0.addWidget(self.spec_db_btn); self._update_spec_db_btn()
        self.db_cb=_N2Select('move-vertical','RANGE',mono=True); self.db_cb.setFixedHeight(_H)
        self.db_cb.addItems(['72 dB','96 dB','120 dB']); self.db_cb.setCurrentIndex(1)
        self.db_cb.setToolTip(_tx('Display dB range   ·   Use ↑/↓ keys on the graph to shift up/down'))
        self.db_cb.currentIndexChanged.connect(self._db_changed)
        sl0.addWidget(self.db_cb); _dv0()
        # ── 시간거동: PEAK · HOLD(피크 홀드시간) · SPEED(평균) ──
        self.peak_btn=_N2Toggle('peak-up', text='ON', label='PEAK'); self.peak_btn.setFixedHeight(_H)
        self.peak_btn.setChecked(True)
        self.peak_btn.clicked.connect(self._toggle_peak)
        sl0.addWidget(self.peak_btn)
        self.hold_cb=_N2Select('clock','HOLD',mono=True); self.hold_cb.setFixedHeight(_H)
        self.hold_cb.addItems(['Fast','0.3s','0.5s','1s']); self.hold_cb.setCurrentIndex(3)
        self.hold_cb.currentIndexChanged.connect(self._set_peak_hold_time)
        sl0.addWidget(self.hold_cb)
        self.spd_cb=_N2Select('gauge','SPEED'); self.spd_cb.setFixedHeight(_H)
        self.spd_cb.addItems([lb for lb,*_ in SPEED_LEVELS]); self.spd_cb.setCurrentIndex(self.speed_idx)
        self.spd_cb.currentIndexChanged.connect(self._set_speed)
        sl0.addWidget(self.spd_cb); _dv0()
        # ── 동작: Reset · Capture ──
        rst=_N2Button('refresh','Reset'); rst.setFixedHeight(_H); self._reset_btn = rst
        rst.clicked.connect(self._reset_peak)
        sl0.addWidget(rst)
        self.spec_cap_btn = _N2Button('camera','Capture'); self.spec_cap_btn.setFixedHeight(_H)
        self.spec_cap_btn.setToolTip(_tx('Capture current spectrum   ·   Shortcut: Space'))
        self.spec_cap_btn.clicked.connect(self._do_spec_capture)
        sl0.addWidget(self.spec_cap_btn); _dv0()
        # ── 외형: Color ──
        self.color_btn=_N2Button('palette','Color'); self.color_btn.setFixedHeight(_H)
        self.color_btn.setToolTip(_tx('Change color of the selected source (click a card to select)'))
        self.color_btn.clicked.connect(self._open_color_picker)
        sl0.addWidget(self.color_btn)
        sl0.addStretch()
        # 별도 창 팝아웃 토글 (멀티모니터)
        self._spec_popout_btn = _N2IconBtn('extlink', checkable=True); self._spec_popout_btn.setFixedHeight(_H)
        self._spec_popout_btn.setToolTip(_tx('Pop out to separate window (multi-monitor)'))
        self._spec_popout_btn.clicked.connect(self._toggle_spec_popout)
        sl0.addWidget(self._spec_popout_btn); sl0.addSpacing(4)
        # 우측 패널(LEVEL/INFO/INPUT) 표시/숨김 토글
        self._spec_panel_btn = _N2IconBtn('panel-right', checkable=True); self._spec_panel_btn.setFixedHeight(_H)
        self._spec_panel_btn.setChecked(True)
        self._spec_panel_btn.clicked.connect(self._toggle_spec_panel)
        sl0.addWidget(self._spec_panel_btn)
        # 툴바를 컨테이너로 감싸 sub_stack 페이지로 (TF의 _sp1과 동형 — 팝아웃 시 떼었다 붙임)
        self._sp0 = QWidget(); self._sp0_lay = QHBoxLayout(self._sp0)
        self._sp0_lay.setContentsMargins(0, 0, 0, 0); self._sp0_lay.setSpacing(0)
        self._spec_tb_wrap = self._toolbar_scroll(sp0)
        self._sp0_lay.addWidget(self._spec_tb_wrap)
        self.sub_stack.addWidget(self._sp0)  # index 0

        # Sub-page 1: Transfer 컨트롤 — tf_win.tb가 생성 후 여기로 이동됨
        self._sp1=QWidget(); self._sp1_lay=QHBoxLayout(self._sp1)
        self._sp1_lay.setContentsMargins(0,0,0,0); self._sp1_lay.setSpacing(0)
        self.sub_stack.addWidget(self._sp1)  # index 1

        # Sub-page 2: Stereo & Loudness 컨트롤
        sp2=QWidget(); sl2=QHBoxLayout(sp2)
        sl2.setContentsMargins(10,0,10,0); sl2.setSpacing(0)   # N2
        _H = 34
        def _dv2():
            sl2.addSpacing(4); sl2.addWidget(_n2_divider()); sl2.addSpacing(4)

        # Start/Stop 버튼
        self._st_start_btn=_N2Button('play','Start (S)',accent_icon=True); self._st_start_btn.setFixedHeight(_H)
        self._st_start_btn.setToolTip(_tx('Start / Stop  (S)'))
        self._st_start_btn.clicked.connect(self._st_toggle)
        sl2.addWidget(self._st_start_btn); _dv2()

        # 현재 선택된 디바이스 표시 (아이콘+IN 라벨+장치명, 표시전용)
        _dev_cell = QFrame(); _dev_cell.setFixedHeight(_H); _dev_cell.setStyleSheet('background:transparent;')
        _dh = QHBoxLayout(_dev_cell); _dh.setContentsMargins(10,0,11,0); _dh.setSpacing(7)
        _mic = QLabel(); _mic.setFixedSize(16,16); _mic.setStyleSheet('background:transparent;')
        _mic.setPixmap(_icon_pm('mic',16,_n2_icon_color()))
        _inlb = QLabel('IN'); _inlb.setFont(_n2_caps_font()); _inlb.setStyleSheet(f'color:{T("text_dim")};background:transparent;')
        self._st_dev_lbl=QLabel('—')
        self._st_dev_lbl.setFont(_n2_val_font())
        self._st_dev_lbl.setStyleSheet(self._st_dev_lbl_ss())
        self._st_dev_lbl.setMaximumWidth(240)
        _dh.addWidget(_mic); _dh.addWidget(_inlb); _dh.addWidget(self._st_dev_lbl)
        sl2.addWidget(_dev_cell); _dv2()

        # L / R 채널 선택
        self._st_l_cb=_N2Select(None,'L'); self._st_l_cb.setFixedHeight(_H); self._st_l_cb.addItem('Ch 1',0)
        sl2.addWidget(self._st_l_cb)
        self._st_r_cb=_N2Select(None,'R'); self._st_r_cb.setFixedHeight(_H); self._st_r_cb.addItem('Ch 2',1)
        sl2.addWidget(self._st_r_cb); _dv2()

        # Target LUFS
        self._st_target_cb=_N2Select('target','TARGET'); self._st_target_cb.setFixedHeight(_H)
        for lbl,val in [('EBU R128  −23',-23.0),('Apple Music  −16',-16.0),
                        ('Streaming  −14',-14.0),('−18 LUFS',-18.0),('ATSC A/85  −24',-24.0)]:
            self._st_target_cb.addItem(lbl,val)
        self._st_target_cb.currentIndexChanged.connect(self._on_st_target_changed)
        sl2.addWidget(self._st_target_cb); _dv2()

        # Reset 버튼 (Integrated LUFS / True Peak)
        _rst_int=_N2Button('refresh','Integrated',label='RESET'); _rst_int.setFixedHeight(_H)
        _rst_int.setToolTip(_tx('Reset Integrated LUFS'))
        _rst_int.clicked.connect(lambda: self.stereo_page.reset_integration())
        sl2.addWidget(_rst_int)
        _rst_pk=_N2Button('refresh','True Peak',label='RESET'); _rst_pk.setFixedHeight(_H)
        _rst_pk.setToolTip(_tx('Reset True Peak hold'))
        _rst_pk.clicked.connect(lambda: self.stereo_page.reset_peak())
        sl2.addWidget(_rst_pk)
        sl2.addStretch()
        # 별도 창 팝아웃 토글 (멀티모니터)
        self._st_popout_btn = _N2IconBtn('extlink', checkable=True); self._st_popout_btn.setFixedHeight(_H)
        self._st_popout_btn.setToolTip(_tx('Pop out to separate window (multi-monitor)'))
        self._st_popout_btn.clicked.connect(self._toggle_st_popout)
        sl2.addWidget(self._st_popout_btn)
        # (이전의 '하단 메트릭 바 토글' 버튼 제거 — 라우드니스 재디자인에서 _num_bar 가 사라져
        #  토글이 무동작인 죽은 버튼이었음. Stereo 엔 토글할 우측/하단 패널이 없음.)
        # 툴바를 컨테이너로 감싸 sub_stack 페이지로 (팝아웃 시 떼었다 붙임)
        self._sp2 = QWidget(); self._sp2_lay = QHBoxLayout(self._sp2)
        self._sp2_lay.setContentsMargins(0, 0, 0, 0); self._sp2_lay.setSpacing(0)
        self._st_tb_wrap = self._toolbar_scroll(sp2)
        self._sp2_lay.addWidget(self._st_tb_wrap)
        self.sub_stack.addWidget(self._sp2)   # index 2

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
        self._spec_page0 = page0          # 팝아웃 시 떼었다 붙일 본체
        self.main_stack.addWidget(page0)  # index 0

        # Page 1: Transfer Function (임베드)
        self.tf_win=TransferFunctionWindow(self, self._settings, embedded=True)
        self.tf_win._engine = self.audio_engine   # 공유 엔진 주입 (TF 입력을 Spectrum/Stereo와 같은 스트림 공유)
        self.main_stack.addWidget(self.tf_win)  # index 1
        # tf_win.tb를 sub_stack page 1로 이동 (embedded 모드에서 tf_win은 tb를 root에 추가 안 함)
        self._tf_tb_wrap = self._toolbar_scroll(self.tf_win.tb)  # 팝아웃 시 떼었다 붙임
        self._sp1_lay.addWidget(self._tf_tb_wrap)

        # Page 2: Stereo & Loudness
        self.stereo_page=StereoLoudnessPage()
        self.stereo_page.error_signal.connect(self._on_stereo_error, Qt.QueuedConnection)
        self.main_stack.addWidget(self.stereo_page)  # index 2

        body_w = QWidget()
        body_lay = QHBoxLayout(body_w)
        body_lay.setContentsMargins(0, 0, 0, 0); body_lay.setSpacing(0)
        self._body_lay = body_lay   # 캡처 드로어 복귀용 참조(TF 팝아웃 후 메인으로 되돌릴 때)
        self._drawer_owner = None   # None=메인 / 'tf_popout'=TF 팝아웃 창이 공유 드로어 소유
        self._capture_drawer = _CaptureDrawer()
        self._capture_drawer.delete_requested.connect(self._on_drawer_delete)
        self._capture_drawer.rename_requested.connect(self._on_drawer_rename)
        self._capture_drawer.new_group_req.connect(self._on_drawer_new_group)
        self._capture_drawer.delete_group_req.connect(self._on_drawer_delete_group)
        self._capture_drawer.reorder_requested.connect(self._on_drawer_reorder)
        self._capture_drawer.move_to_group_req.connect(self._on_drawer_move_to_group)
        self._capture_drawer.capture_selected.connect(self._on_drawer_select)
        self._capture_drawer.visibility_changed.connect(self._on_drawer_visibility)
        self._capture_drawer.visibility_all_changed.connect(self._on_drawer_visibility_all)
        self._capture_drawer.group_visibility_changed.connect(self._on_drawer_group_visibility)
        self._capture_drawer.capture_target_changed.connect(self._on_capture_target_changed)
        self._capture_drawer.delete_all_requested.connect(self._on_drawer_delete_all)
        self._capture_drawer.recapture_requested.connect(self._on_drawer_recapture)
        self._capture_drawer.average_requested.connect(self._on_drawer_average)
        self._capture_drawer.reference_changed.connect(self._on_drawer_reference)
        self._capture_drawer.export_requested.connect(self._on_drawer_export)
        self._capture_drawer.import_requested.connect(self._on_drawer_import)
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

        # dB축 수동 고정 복원 (재시작에도 유지)
        if self._settings.get('spec_db_lock'):
            self._db_lock = True
            self.db_max = float(self._settings.get('spec_db_top', self.db_max))
            self.db_min = float(self._settings.get('spec_db_bot', self.db_min))
            self.db_range = self.db_max - self.db_min
            self._pending_auto_fit = False; self._apply_db_range()
        self._update_spec_db_btn()

        # TF 캡처 변경 시 드로어도 갱신
        self.tf_win._on_captures_changed = self._refresh_capture_drawer
        # TF 드로어 토글 버튼 연결
        self.tf_win._drawer_btn.clicked.connect(self._toggle_capture_drawer)
        # TF 별도 창(멀티모니터) 팝아웃 토글 버튼 연결
        self.tf_win._popout_btn.clicked.connect(self._toggle_tf_popout)
        # 이전 세션 캡처 복원
        QTimer.singleShot(0, self._restore_spec_captures)
        QTimer.singleShot(0, self._restore_active_tab)   # 마지막 탭으로 시작(현재 화면=기본화면)

        # ── 푸터
        self.ft=QWidget(); self.ft.setFixedHeight(22)
        fl=QHBoxLayout(self.ft); fl.setContentsMargins(16,0,16,0)
        fl.addWidget(QLabel(f'SPECTRA  |  v{_APP_VERSION}'))
        fl.addStretch()
        jordan_lbl=QLabel('Design by Jordan')
        jordan_lbl.setStyleSheet(f'color:{T("text_dim")};font-size:10px;font-style:italic;')
        fl.addWidget(jordan_lbl)
        root.addWidget(self.ft)

    def _switch_tab(self, i):
        if getattr(self, '_split_on', False):
            self._exit_split()   # 분할 중 탭 클릭 → 분할 해제 후 해당 탭으로
        keys=['spectrum','transfer','stereo']
        for k,b in self._tab_btns.items():
            b.setChecked(k==keys[i])
        self.sub_stack.setCurrentIndex(i)
        self.main_stack.setCurrentIndex(i)
        self.toolbar_wrapper.setFixedHeight(46)
        if getattr(self, '_drawer_owner', None) == 'tf_popout':
            pass   # 공유 드로어가 TF 팝아웃 창에 있음 → 메인 탭 전환이 모드/가시성 건드리지 않음
        else:
            self._capture_drawer.set_active_mode('tf' if i==1 else 'spec')
            # Stereo 탭: 캡처 드로어 비활성화
            if i==2: self._capture_drawer.setVisible(False)
        self._apply_tab_styles()
        # 마지막 탭 기억 → 다음 실행 시 그 탭으로 시작(현재 화면=기본화면)
        if getattr(self, '_tab_restore_done', False):
            self._settings['active_tab'] = int(i); _save_settings(self._settings)

    def _restore_active_tab(self):
        """저장된 마지막 탭으로 시작 — 설정 auto-save와 합쳐 '현재 화면=기본화면'."""
        try: i = int(self._settings.get('active_tab', 0))
        except Exception: i = 0
        if i not in (0, 1, 2): i = 0
        if i != 0:
            self._switch_tab(i)
        self._tab_restore_done = True

    def _apply_tab_styles(self):
        accent=T('accent'); text=T('text'); text_dim=T('text_dim')
        ac = QColor(accent); ar, ag, ab = ac.red(), ac.green(), ac.blue()
        for b in self._tab_btns.values():
            if isinstance(b, _N2Tab):
                b.restyle(); continue     # N2 탭은 setChecked/_sync가 스타일 관리
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
            f'QScrollArea{{background:transparent;border:none;}}'
            f'QScrollBar:horizontal{{height:6px;background:transparent;margin:0;}}'
            f'QScrollBar::handle:horizontal{{background:{T("border")};border-radius:3px;min-width:40px;}}'
            f'QScrollBar::add-line:horizontal,QScrollBar::sub-line:horizontal{{width:0;}}')
        # 자연 폭 미만으로 좁아지면 압축 대신 스크롤 (폴리시 후 최종 sizeHint로 재설정)
        def _set_min():
            content.setMinimumWidth(content.sizeHint().width())
        _set_min(); QTimer.singleShot(0, _set_min)
        return sc

    def _build_info(self):
        panel=QWidget(); panel.setFixedWidth(218)
        panel.setObjectName('infoPanel')
        self._info_panel = panel
        # 개별 섹션 박스 대신 외곽 프레임 1개로 감쌈 (테두리는 외곽만)
        _outer=QVBoxLayout(panel); _outer.setContentsMargins(8,8,8,8); _outer.setSpacing(0)
        _rpframe=QFrame(); _rpframe.setObjectName('rpFrame'); _outer.addWidget(_rpframe)
        layout=QVBoxLayout(_rpframe); layout.setContentsMargins(9,11,9,11); layout.setSpacing(8)

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
        alarm_btn = _SplAlarmBtn()
        alarm_btn.clicked.connect(self._open_spl_alarm)
        hdr_row.addWidget(level_icon); hdr_row.addWidget(level_title)
        hdr_row.addStretch(); hdr_row.addWidget(alarm_btn); hdr_row.addWidget(spl_btn)
        level_lay.addLayout(hdr_row)
        level_lay.addWidget(_sec_hairline()); level_lay.addSpacing(2)

        refs={}
        _soft_a = '#9DB7E0' if is_dark() else '#5A78B0'   # A가중 = 소프트 화이트블루
        _soft_c = '#C98B96' if is_dark() else '#9A5E6A'   # C가중 = 소프트 와인
        broad_col = T('text')                                      # 광대역 값(SPL/Peak/Dom) = 흰색(중성)
        for k,init in [('SPL','—'),('Peak Hold','—'),('Dominant','—')]:
            row=QHBoxLayout()
            kl=QLabel(k); kl.setStyleSheet(ss_text(FS_SM))
            vl=QLabel(init); vl.setStyleSheet(f'font-size:{FS_BODY}px;font-weight:bold;color:{broad_col};')
            vl.setAlignment(Qt.AlignRight)
            row.addWidget(kl); row.addWidget(vl); level_lay.addLayout(row); refs[k]=vl
        dba_row=QHBoxLayout()
        dba_lbl=QLabel('dBA'); dba_lbl.setStyleSheet(ss_text(FS_SM))
        dba_val=QLabel('—'); dba_val.setStyleSheet(f'color:{_soft_a};font-size:{FS_DISP}px;font-weight:bold;')
        dba_val.setAlignment(Qt.AlignRight)
        dba_row.addWidget(dba_lbl); dba_row.addWidget(dba_val); level_lay.addLayout(dba_row)
        dbc_row=QHBoxLayout()
        dbc_lbl=QLabel('dBC'); dbc_lbl.setStyleSheet(ss_text(FS_SM))
        dbc_val=QLabel('—'); dbc_val.setStyleSheet(f'color:{_soft_c};font-size:{FS_DISP}px;font-weight:bold;')
        dbc_val.setAlignment(Qt.AlignRight)
        dbc_row.addWidget(dbc_lbl); dbc_row.addWidget(dbc_val); level_lay.addLayout(dbc_row)
        refs['dBA']=dba_val; refs['dBC']=dbc_val
        laeq_row=QHBoxLayout()
        laeq_lbl=QLabel('LAeq'); laeq_lbl.setStyleSheet(ss_text(FS_SM))
        laeq_val=QLabel('—'); laeq_val.setStyleSheet(f'color:{_soft_a};font-size:{FS_VAL}px;font-weight:bold;')
        laeq_val.setAlignment(Qt.AlignRight)
        laeq_row.addWidget(laeq_lbl); laeq_row.addWidget(laeq_val); level_lay.addLayout(laeq_row)
        lceq_row=QHBoxLayout()
        lceq_lbl=QLabel('LCeq'); lceq_lbl.setStyleSheet(ss_text(FS_SM))
        lceq_val=QLabel('—'); lceq_val.setStyleSheet(f'color:{_soft_c};font-size:{FS_VAL}px;font-weight:bold;')
        lceq_val.setAlignment(Qt.AlignRight)
        lceq_row.addWidget(lceq_lbl); lceq_row.addWidget(lceq_val); level_lay.addLayout(lceq_row)
        refs['LAeq']=laeq_val; refs['LCeq']=lceq_val

        self.i_spl=refs['SPL']; self.i_pk=refs['Peak Hold']
        self.i_dom=refs['Dominant']; self.i_dba=refs['dBA']; self.i_dbc=refs['dBC']
        self.i_laeq=refs['LAeq']; self.i_lceq=refs['LCeq']
        self._i_dba_base=_soft_a; self._i_dbc_base=_soft_c
        self._i_laeq_base=_soft_a; self._i_lceq_base=_soft_c
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
        info_lay.addWidget(_sec_hairline()); info_lay.addSpacing(2)
        labels={}
        for k,v in [('Sample Rate','48 kHz'),('FFT Size','16384'),
                    ('Resolution','11.7 Hz'),('Calibration','0.0 dB'),('Speed','Normal')]:
            row=QHBoxLayout()
            kl=QLabel(k); kl.setStyleSheet(ss_text(FS_SM))
            vl=QLabel(v); vl.setStyleSheet(f'color:{T("text")};background:transparent;')
            vl.setFont(_n2_mono_font(FS_BODY, QFont.DemiBold))   # 세련 — 계측기 모노 숫자
            vl.setAlignment(Qt.AlignRight)
            row.addWidget(kl); row.addWidget(vl); info_lay.addLayout(row); labels[k]=vl
        self.i_sr=labels['Sample Rate']; self.i_fft=labels['FFT Size']
        self.i_res=labels['Resolution']; self.i_calib=labels['Calibration']; self.i_spd=labels['Speed']
        layout.addWidget(info_w)

        # ── INPUT 섹션 (카드 기반) ──
        input_w = QWidget(); input_w.setObjectName('infoBox')
        input_lay = QVBoxLayout(input_w); input_lay.setContentsMargins(2,8,2,8); input_lay.setSpacing(5)
        in_hdr = QHBoxLayout(); in_hdr.setContentsMargins(0,0,0,6); in_hdr.setSpacing(5)
        in_icon = _SidebarIcon('input', T('accent'), 15)
        in_title = QLabel('INPUT')
        in_title.setStyleSheet(ss_text(FS_LG, 'text_dim', True))
        in_hdr.addWidget(in_icon); in_hdr.addWidget(in_title); in_hdr.addStretch()
        input_lay.addLayout(in_hdr)
        input_lay.addWidget(_sec_hairline()); input_lay.addSpacing(2)
        # 카드 컨테이너 — TF식 스크롤 목록 (카드 많아져도 압축/겹침 없이 스크롤)
        self._ch_cards_container = QWidget()
        self._ch_cards_container.setStyleSheet('background:transparent;')
        self._ch_cards_layout = QVBoxLayout(self._ch_cards_container)
        # 카드를 좌우 대칭 인셋 → 패널 안에서 가운데 정렬 (오른쪽 viewportMargin 2 + 여기 4 = 6, 왼쪽 6)
        self._ch_cards_layout.setContentsMargins(1,0,3,0); self._ch_cards_layout.setSpacing(6)
        self._ch_cards_scroll = QScrollArea()
        self._ch_cards_scroll.setWidget(self._ch_cards_container)
        self._ch_cards_scroll.setWidgetResizable(True)
        self._ch_cards_scroll.setFrameShape(QFrame.NoFrame)
        self._ch_cards_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._ch_cards_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        # 뷰포트 우측 인셋(2) + 카드레이아웃 우측(4) = 6px → 스크롤바 공간 확보 + 좌우 대칭(왼쪽도 6)
        self._ch_cards_scroll.setViewportMargins(0,0,2,0)
        self._ch_cards_scroll.setMinimumHeight(120)
        self._ch_cards_scroll.viewport().setStyleSheet('background:transparent;')
        self._ch_cards_scroll.setStyleSheet(
            f'QScrollArea{{background:transparent;border:none;}}'
            f'QScrollBar:vertical{{width:6px;background:transparent;margin:0;}}'
            f'QScrollBar::handle:vertical{{background:{T("border")};border-radius:3px;min-height:40px;}}'
            f'QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{{height:0;}}')
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
        help_btn = self._help_btn = QPushButton('Help')
        help_btn.setFixedHeight(22)
        help_btn.setToolTip(_tx('Open user manual'))
        help_btn.clicked.connect(self._open_manual)
        log_btn = self._log_btn = QPushButton('Log')
        log_btn.setFixedHeight(22)
        log_btn.setToolTip(_tx('Bundle recent logs into a zip file when reporting issues.\nSend that file to the developer. (No personal data or license key included)'))
        log_btn.clicked.connect(self._export_logs)
        lic_btn = self._lic_btn = QPushButton('License')
        lic_btn.setFixedHeight(22)
        lic_btn.setToolTip(_tx('About SPECTRA · License info'))
        lic_btn.clicked.connect(self._show_license_info)
        self._restyle_util_btns()
        util_row.addWidget(help_btn); util_row.addWidget(log_btn); util_row.addWidget(lic_btn)
        layout.addLayout(util_row)

        layout.addStretch(); return panel

    def _restyle_util_btns(self):
        """Log/License 유틸 버튼 — 테마 적응 스타일 (다크↔라이트 토글 시 갱신)."""
        _ss = (f'font-size:{FS_XS}px;color:{T("text_dim")};background:{T("panel")};'
               f'border:1px solid {T("border")};border-radius:{RADIUS_SM}px;padding:1px 6px;')
        for _b in (getattr(self, '_help_btn', None), getattr(self, '_log_btn', None), getattr(self, '_lic_btn', None)):
            if _b is not None: _b.setStyleSheet(_ss)

    def _export_logs(self):
        """최근 로그를 zip 한 파일로 묶어 바탕화면에 저장 + 위치 표시.
        사용자가 그 파일 하나만 첨부해 보내면 됨 (지원/원격 디버깅용)."""
        from PyQt5.QtWidgets import QMessageBox
        import zipfile, glob
        try:
            logs = sorted(glob.glob(os.path.join(_LOG_DIR, 'wsa2_*.log')))[-10:]  # 최근 10세션
            if not logs:
                _BrandBox.information(self, _tx('Send Logs'), _tx('No logs saved yet.'))
                return
            _dest = os.path.join(os.path.expanduser('~'), 'Desktop')
            if not os.path.isdir(_dest): _dest = os.path.expanduser('~')
            out = os.path.join(_dest, f'SPECTRA_logs_{_dt.datetime.now().strftime("%Y%m%d_%H%M%S")}.zip')
            with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
                for lp in logs:
                    z.write(lp, os.path.basename(lp))
            _alog.info(f'로그 내보내기: {out}  ({len(logs)}개)')
            if _pl.system() == 'Windows':
                _sp.Popen(['explorer', '/select,', os.path.normpath(out)])
            else:
                _sp.Popen(['open', '-R', out])
            _BrandBox.information(
                self, _tx('Send Logs'),
                f'Bundled {len(logs)} recent log(s):\n\n{out}\n\n'
                'Send this file to the developer or distributor.\n(No personal data or license key included.)')
        except Exception as e:
            _alog.warning(f'로그 내보내기 실패: {e}')
            _BrandBox.warning(self, _tx('Send Logs Failed'),
                                f'{e}\n\nOpen the log folder manually:\n{_LOG_DIR}')

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
        if is_dark():
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
        drw_alpha = 245 if is_dark() else 255
        self._capture_drawer._panel.setStyleSheet(
            f'#capturePanel {{ background: qlineargradient(x1:0,y1:0,x2:0,y2:1,'
            f'stop:0 rgba({pnR},{pnG},{pnB},{drw_alpha}), stop:1 rgba({b2R},{b2G},{b2B},{drw_alpha}));'
            f'border: 1px solid {border}; border-radius: 8px; }}')
        # update drawer segmented control for current theme
        if is_dark():
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
        # 캡쳐 탭 = 언더라인 스타일(메인 탭바와 통일) — 회색 트랙 제거.
        # 밑줄은 별도 QFrame(글자 폭만큼 일자) — border-bottom의 곡선 렌더 회피.
        self._capture_drawer._seg_pill.setStyleSheet('#segPill{background:transparent;}')
        _dtab_ss = (
            f'QPushButton{{font-size:12px;font-weight:600;border:none;'
            f'background:transparent;color:{seg_unchk_txt};padding:2px 6px 2px 6px;}}'
            f'QPushButton:checked{{color:{T("text")};}}'
            f'QPushButton:hover:!checked{{color:{T("text_dim")};background:transparent;}}')
        self._capture_drawer._spec_tab_btn.setStyleSheet(_dtab_ss)
        self._capture_drawer._tf_tab_btn.setStyleSheet(_dtab_ss)
        for _ul in getattr(self._capture_drawer, '_dtab_uls', {}).values():
            _ul.setStyleSheet(f'background:{T("accent")};border:none;border-radius:1px;')
        # 리스트 영역 배경 = 툴바/패널과 통일(bg2), 순검정(bg) 제거
        _sc_bd = '#2E2E34' if is_dark() else border
        self._capture_drawer._scroll.setStyleSheet(
            f'#capScroll {{ background:{bg2}; border:1px solid {_sc_bd}; border-radius:10px; }}'
            f'QScrollBar:vertical{{width:5px;background:transparent;}}'
            f'QScrollBar::handle:vertical{{background:{scr_hdl};border-radius:2px;}}')
        self._capture_drawer._scroll.viewport().setStyleSheet('background:transparent;border-radius:10px;')
        self._capture_drawer._inner.setStyleSheet('#capInner { background:transparent; }')
        # 헤더 버튼 테마색 + 행/칩 재빌드 (라이트에서 검정 배경 잔재 제거)
        self._capture_drawer._restyle_chrome()
        self._capture_drawer._redraw()
        sep_line = '#4A4A4A' if is_dark() else border
        self.hdr.setStyleSheet(f'#mainHdr {{ background: {bg2}; border: none; }}')
        self.hdr_sep.setStyleSheet(f'#hdrSep {{ background: {_SPECTRA_GRAD_QSS}; border: none; }}')
        self.tab_bar.setStyleSheet(
            f'#mainTabBar {{ background: {bg2}; border: none; }}')   # N2: 하단 보더 제거(가로줄 최소화)
        self._main_seg_pill.setStyleSheet('#mainSegPill{background:transparent;}')
        for b in self._tab_btns.values():
            if isinstance(b, _N2Tab): b.restyle()
            else: b.setStyleSheet(_dtab_ss)
        # toolbar_wrapper: ID selector로 cascade 방지 (자식 위젯 border 미영향)
        self.toolbar_wrapper.setStyleSheet(
            f'#toolbarWrapper {{ background: {bg2}; }}')
        # 탭 ↔ 메뉴 구분: 전체 폭 파란(액센트) 라인
        if hasattr(self, 'tab_menu_sep'):
            self.tab_menu_sep.setStyleSheet(f'#tabMenuSep {{ background: {accent}; border: none; }}')
        # 툴바 하단 구분선 — 큰 틀 구분(회색 하어라인). 툴바↔콘텐츠 분리.
        _tbline = '#54545E' if is_dark() else border
        self.toolbar_underline.setStyleSheet(
            f'#toolbarUnderline {{ background: {_tbline}; border: none; }}')
        if hasattr(self, '_view_seg'):
            self._view_seg.apply_theme(); self._scale_seg.apply_theme()
            # N2 툴바 위젯 인라인 색 재적용 (테마 토글) — start_btn은 실행상태가 관리하므로 제외
            for _wn in ('spectro_btn','peak_btn','sr_cb','hold_cb','db_cb','spd_cb',
                        '_reset_btn','spec_cap_btn','color_btn','spec_db_btn','_spec_popout_btn','_spec_panel_btn'):
                _wr = getattr(self, _wn, None)
                if _wr is not None and hasattr(_wr, 'restyle'):
                    try: _wr.restyle()
                    except Exception: pass
            if isinstance(getattr(self, 'spec_db_btn', None), _N2Button):
                self._update_spec_db_btn()
        # 모든 N2 툴바/컨트롤 위젯 전수 재스타일(개별 나열 누락 방지) — 3탭 툴바.
        # restyle()은 실행상태(play/stop 아이콘)를 보존하므로 트랜스포트 버튼도 안전.
        _n2_conts = []
        for _wn in ('_spec_tb_wrap', '_st_tb_wrap'):
            _wr = getattr(self, _wn, None)
            if _wr is not None and _wr.widget() is not None:
                _n2_conts.append(_wr.widget())
        if getattr(self, 'tf_win', None) is not None and hasattr(self.tf_win, 'tb'):
            _n2_conts.append(self.tf_win.tb)
        for _cont in _n2_conts:
            for _T in (_N2Select, _N2Button, _N2Toggle, _N2IconBtn, _N2Segmented, _N2Tab):
                for _w in _cont.findChildren(_T):
                    if hasattr(_w, 'restyle'):
                        try: _w.restyle()
                        except Exception: pass
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
        # ⚠️_st_l_cb/_st_r_cb/_st_target_cb 는 QComboBox가 아니라 _N2Select(QFrame)라
        #   _cb_ss(QComboBox 규칙)가 안 먹고 오히려 N2 투명배경/hover를 지워 솔리드 박스로 만듦.
        #   위 블랭킷 restyle 루프가 _N2Select.restyle()로 이미 올바르게 처리하므로 여기선 손대지 않음.
        # Spectrum 툴바 콤보도 전역 cascade 대신 _cb_ss 직접 적용 → 3탭 콤보 100% 동일 보장
        for _spc in ('sr_cb', 'hold_cb', 'db_cb', 'spd_cb'):
            _w = getattr(self, _spc, None)
            if _w is not None: _w.setStyleSheet(_cb_ss)
        # Spectrum·Stereo 툴바 버튼도 TF처럼 그라디언트 펜 스타일 — 팝아웃 시 창 bare-bg
        # cascade가 버튼을 평평한 검정으로 덮는 문제 해결(세그먼트 컨트롤은 자체 페인트라 무관).
        _tb_btn_ss = (
            f'QPushButton{{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,'
            f'stop:0 {btn_bg0},stop:1 {btn_bg1});color:{text};border:1px solid {btn_bd};'
            f'border-radius:7px;padding:3px 9px;font-size:11px;}}'
            f'QPushButton:hover{{border:1px solid rgba({ar},{ag},{ab},160);color:{accent};}}')
        # (:checked 규칙은 생략 — Peak/+Spectro 같은 _CheckBtn이 자체 페인트로 선택표시)
        for _wn in ('_spec_tb_wrap', '_st_tb_wrap'):
            _wrap = getattr(self, _wn, None)
            _content = _wrap.widget() if _wrap is not None else None
            if _content is not None:
                _content.setStyleSheet(_tb_btn_ss)
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
            # 우측 패널 콤보(Reference In·Signal Gen Out)는 팝아웃 별도 창에선 전역 QComboBox
            # 스타일을 못 받아 Fusion 기본(화살표·검정)으로 떨어짐 → _cb_ss 직접 적용해 임베드와 통일
            for _cbn in ('fft_cb', 'avg_cb', 'sm_cb', 'ir_cb', 'phase_cb',
                         'ref_cb', 'ref_ch_cb',
                         'sig_out_cb', 'sig_out_ch_cb', 'sig_out_ch2_cb'):
                _cbw = getattr(self.tf_win, _cbn, None)
                if _cbw is None: continue
                if hasattr(_cbw, 'restyle') and not isinstance(_cbw, RoundComboBox):
                    _cbw.restyle()          # N2 위젯은 자체 재스타일
                else:
                    _cbw.setStyleSheet(_cb_ss)
            # Δ·stable 토글 버튼 — 테마 적응(라이트에서 다크박스 방지)
            _tgss = (
                f'QPushButton{{background:{panel};color:{text_dim};border:1px solid {border};'
                f'border-radius:7px;font-size:14px;font-weight:bold;}}'
                f'QPushButton:hover{{border-color:{accent};}}'
                f'QPushButton:checked{{background:{accent};color:#FFFFFF;border:1px solid {accent};}}')
            for _bn in ('delta_btn', 'tf_stable_btn'):
                _b = getattr(self.tf_win, _bn, None)
                if _b is None: continue
                if hasattr(_b, 'restyle') and not hasattr(_b, 'icon'):
                    _b.restyle()
                else:
                    _b.setStyleSheet(_tgss)
            # 아이콘 테마 적응 재생성 (다크↔라이트 토글 시 보이도록) — N2 위젯은 restyle로 처리
            for _bn, _ic, _sz in [('find_btn', 'search', 16), ('delta_btn', 'delta', 16),
                                  ('tf_stable_btn', 'hourglass', 16), ('sig_file_btn', 'folder', 16),
                                  ('_export_btn', 'download', 13)]:
                _b = getattr(self.tf_win, _bn, None)
                if _b is None: continue
                if not hasattr(_b, 'icon'):     # N2 위젯(아이콘 QPushButton 아님)
                    if hasattr(_b, 'restyle'): _b.restyle()
                    continue
                if not _b.icon().isNull(): _b.setIcon(_icon(_ic, _sz))
            # TF 측정 카드 인라인색 재적용 (다크↔라이트 토글 시 카드/콤보/딜레이가 검정으로 남는 문제)
            self.tf_win.restyle_theme()
        # Spectrum 입력 카드 — 인라인-구운 색이 토글에 안 따라옴 → 통째로 재생성
        if hasattr(self, '_rebuild_ch_cards') and hasattr(self, '_ch_cards'):
            self._rebuild_ch_cards()
        self._apply_tab_styles()
        self.logo_lbl.setStyleSheet(
            f'font-family:"{FONT_FAMILY}";font-size:17px;font-weight:700;letter-spacing:5px;color:{text};background:transparent;')
        self.status_lbl.setStyleSheet(
            f'color:{text_dim};font-size:11px;letter-spacing:0.5px;')
        self.mic_st.setStyleSheet(f'color:{text_dim};font-size:10px;')
        if hasattr(self, '_st_dev_lbl'): self._st_dev_lbl.setStyleSheet(self._st_dev_lbl_ss())
        # 시작 버튼
        self._go_style(self.start_btn)
        # ── 상단 헤더 컨트롤 = N2(테두리리스 + hover 배경, 중립 아이콘) — 파란 필/테두리 폐지
        _hov = 'rgba(255,255,255,0.07)' if is_dark() else 'rgba(0,0,0,0.06)'
        _icc = _n2_icon_color()
        # 테마 버튼 (Light/Dark)
        lbl = 'Dark' if (not is_dark()) else 'Light'
        self.theme_btn.setText(lbl)
        self.theme_btn.setIcon(_icon('moon' if (not is_dark()) else 'sun', 15, _icc))
        self.theme_btn.setStyleSheet(
            f'QPushButton{{border:none;background:transparent;color:{text};'
            f'border-radius:8px;padding:3px 10px;font-size:11px;}}'
            f'QPushButton:hover{{background:{_hov};}}')
        # Calibration 버튼
        self.calib_btn.setIcon(_icon('sliders', 15, _icc))
        self.calib_btn.setStyleSheet(
            f'QPushButton{{border:none;background:transparent;color:{text};'
            f'border-radius:8px;padding:3px 10px;font-size:11px;}}'
            f'QPushButton:hover{{background:{_hov};}}')
        # 헤더 아이콘 전용 버튼 (언어/프리셋 저장·삭제)
        _hdr_icon_ss = (
            f'QPushButton{{border:none;background:transparent;border-radius:8px;padding:0;}}'
            f'QPushButton:hover{{background:{_hov};}}')
        if hasattr(self, 'lang_btn'):
            self.lang_btn.setStyleSheet(_hdr_icon_ss); self.lang_btn.setIcon(_icon('globe', 16, _icc))
        if hasattr(self, '_preset_save_btn'):
            self._preset_save_btn.setStyleSheet(_hdr_icon_ss); self._preset_save_btn.setIcon(_icon('save', 15, _icc))
        if hasattr(self, '_preset_del_btn'):
            self._preset_del_btn.setStyleSheet(_hdr_icon_ss); self._preset_del_btn.setIcon(_icon('trash', 15, _icc))
        # Preset 드롭다운 — 테두리리스 N2
        if hasattr(self, '_preset_cb'):
            self._preset_cb.setStyleSheet(
                f'QComboBox{{border:none;background:transparent;color:{text};'
                f'border-radius:8px;padding:2px 10px;font-size:11px;}}'
                f'QComboBox:hover{{background:{_hov};}}'
                f'QComboBox::drop-down{{width:0;border:none;}}'
                f'QComboBox::down-arrow{{width:0;height:0;image:none;}}')
        # 오른쪽 사이드 패널 배경 + 왼쪽 경계선 (셀렉터 지정으로 자식 위젯 미영향)
        if hasattr(self, '_info_panel'):
            _frame_bd = '#3A3A42' if is_dark() else border    # 외곽 프레임 테두리(개별 박스 없음)
            _pan_bd   = '#54545E' if is_dark() else sep_line   # 그래프↔패널 세로 구분선(또렷)
            self._info_panel.setStyleSheet(
                f'#infoPanel {{ background:{bg2}; border-left:2px solid {_pan_bd}; }}'   # 툴바(bg2)와 배경 통일
                f'#rpFrame {{ background:transparent; border:1px solid {_frame_bd}; border-radius:11px; }}'
                # 개별 섹션 박스 테두리 제거 — 하어라인으로만 구분
                f'#levelBox {{ background:transparent; border:none; }}'
                f'#levelBox QLabel {{ background:transparent; border:none; }}'
                f'#infoBox  {{ background:transparent; border:none; }}'
                f'#infoBox QLabel {{ background:transparent; border:none; }}')
            # INFO/LEVEL 값 라벨 색 재적용 — 생성 시 T('text')(다크=흰색)로 굳어 라이트서 안 보이던 문제
            if hasattr(self, 'i_spl'):
                _bcol = T('text')
                for _v in (self.i_spl, self.i_pk, self.i_dom):
                    _v.setStyleSheet(f'color:{_bcol};background:transparent;font-size:{FS_BODY}px;font-weight:bold;')
                for _v in (self.i_sr, self.i_fft, self.i_res, self.i_calib, self.i_spd):
                    _v.setStyleSheet(f'color:{_bcol};background:transparent;')   # 모노 폰트는 setFont로 유지
                self._i_dba_base = '#9DB7E0' if is_dark() else '#5A78B0'
                self._i_dbc_base = '#C98B96' if is_dark() else '#9A5E6A'
                self._i_laeq_base = self._i_dba_base; self._i_lceq_base = self._i_dbc_base
                for _v, _b, _fs in ((self.i_dba, self._i_dba_base, FS_DISP), (self.i_dbc, self._i_dbc_base, FS_DISP),
                                    (self.i_laeq, self._i_laeq_base, FS_VAL), (self.i_lceq, self._i_lceq_base, FS_VAL)):
                    _v.setStyleSheet(f'color:{_b};background:transparent;font-size:{_fs}px;font-weight:bold;')
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
        # Level 스핀박스 + ±버튼 + Play + 그룹박스 (tf_win 소속) — direction C(서브틀 보더)
        if self.tf_win is not None:
            _c_bd = '#34343B' if is_dark() else border
            self.tf_win.sig_lvl_sp.setStyleSheet(
                f'QDoubleSpinBox{{border:1px solid {_c_bd};background:transparent;color:{text};'
                f'border-radius:8px;padding:2px 6px;font-family:Menlo;font-size:12px;font-weight:600;}}'
                f'QDoubleSpinBox::up-button,QDoubleSpinBox::down-button{{width:0;border:none;}}')
            _btn_s = (
                f'QPushButton{{border:1px solid {_c_bd};background:transparent;color:{text_dim};'
                f'border-radius:8px;font-size:16px;font-weight:600;}}'
                f'QPushButton:hover{{color:{text};border-color:#4A4A54;}}')
            self.tf_win.sig_lvl_btn_m.setStyleSheet(_btn_s)
            self.tf_win.sig_lvl_btn_p.setStyleSheet(_btn_s)
            # TF 오른쪽 패널 배경 + 그룹박스 타이틀
            self.tf_win.rp.setStyleSheet(f'background:{bg2};')
            # 그룹박스 테두리 제거 — 캡스 헤더+하어라인(_n2_group_header)이 구분 담당(목업 룩)
            _bss = 'QGroupBox{border:none;margin-top:0;padding:0;background:transparent;}'
            for grp in self.tf_win.rp.findChildren(QGroupBox):
                grp.setStyleSheet(_bss)
            # Play — C 스타일러 (재생상태 유지)
            self.tf_win._style_sig_play(self.tf_win.sig_on_btn.isChecked())
            # 타입 셀·OUT 콤보·Reference·측정 카드 라이트/다크 재스타일
            self.tf_win._restyle_sig_gen_theme()
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
        _spla = getattr(self, 'spl_alarm_win', None)
        if _spla is not None: _spla.restyle_theme()
        # 캡처 드로어 행 재빌드 (테마 전환 시 T() 색상 갱신)
        self._refresh_capture_drawer()
        # 팝아웃 토글 버튼(스펙트럼/스테레오) 테마 재적용
        for _btn in (getattr(self, '_spec_popout_btn', None),
                     getattr(self, '_st_popout_btn', None)):
            if _btn is not None:
                _btn.setStyleSheet(_popout_toggle_ss())
        # 전역 QMenu·QToolTip 다크 스타일(모든 top-level 창) — 우클릭 컨텍스트 메뉴/툴팁이
        # Fusion 기본 밝은색으로 뜨던 것 통일. 팝아웃·다이얼로그까지 커버.
        _app = QApplication.instance()
        if _app is not None:
            _app.setStyleSheet(_global_popup_qss())
        # macOS: NSApp 전체 다크 외형 강제 — 시스템 라이트 모드에서 우클릭 컨텍스트 메뉴가
        # 흰색으로 뜨던 것 해결(창별 setAppearance로는 별도 NSWindow인 팝업 메뉴 미커버).
        _apply_app_dark_appearance()

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
            # 네이티브 전체화면(메뉴바가 커스텀 헤더를 덮음) 대신 최대화 — 메뉴바 아래로 꽉 채움
            if self.isMaximized():
                self.showNormal()
            else:
                self.showMaximized()
            return True
        return super().eventFilter(obj, event)

    def _open_float_popups(self):
        """현재 열려있는 떠다니는 팝업창들(SPL 미터/알람)."""
        return [w for w in (getattr(self, 'spl_meter_win', None),
                            getattr(self, 'spl_alarm_win', None))
                if w is not None and w.isVisible()]

    def _float_sync_attach(self, win):
        """팝업의 풀스크린 자식부착 상태를 '메인 풀스크린 여부 × 같은 화면 여부'에 맞춰 동기화.
        부착이 필요할 때만(=풀스크린 메인과 같은 디스플레이) 자식부착, 그 외엔 분리.
        → 드래그로 외부 모니터로 넘기면 자동 분리(자유 이동), 다시 끌어오면 재부착.
        실제 상태가 바뀔 때만 objc 호출(드래그 중 매 픽셀 호출 방지)."""
        if sys.platform != 'darwin' or not win.isVisible():
            return
        from PyQt5.QtWidgets import QApplication
        try:
            my_scr = QApplication.screenAt(self.geometry().center())
            pscr   = QApplication.screenAt(win.geometry().center())
        except Exception:
            return
        want = bool(self.isFullScreen() and (my_scr is None or pscr is my_scr))
        if want == bool(getattr(win, '_float_attached', False)):
            return
        win._float_attached = want
        if want:
            _set_fullscreen_auxiliary(win)
            _attach_as_child(win, self)
            win.raise_()
        else:
            _detach_as_child(win, self)
            _apply_on_top(win, getattr(win, '_always_top', True))

    def _attach_floats_for_fullscreen(self):
        """메인 풀스크린 진입 — 같은 화면 팝업은 부착(가려짐 방지), 외부 모니터 팝업은 자유 유지."""
        for win in self._open_float_popups():
            self._float_sync_attach(win)

    def _detach_all_floats(self):
        """메인 풀스크린 해제 — 부착된 팝업을 독립창으로 풀어 외부 모니터 이동 가능하게."""
        for win in self._open_float_popups():
            self._float_sync_attach(win)

    def changeEvent(self, e):
        if e.type() == QEvent.WindowStateChange:
            fs = self.isFullScreen()
            if fs != getattr(self, '_was_fullscreen', False):
                self._was_fullscreen = fs
                if fs:
                    # 풀스크린 전환 애니메이션(~0.5s) 끝난 뒤 부착
                    QTimer.singleShot(550, self._attach_floats_for_fullscreen)
                else:
                    self._detach_all_floats()
        super().changeEvent(e)

    def _st_dev_lbl_ss(self):
        # N2 flat 셀 — 투명 배경 + 서브틀 테두리(다른 N2 컨트롤과 통일).
        _bd = '#34343B' if is_dark() else T('border')
        return (f'font-size:{FS_BODY}px;font-weight:600;color:{T("text")};'
                f'background:transparent;border:1px solid {_bd};'
                f'border-radius:8px;padding:2px 8px;')

    def _toggle_theme(self):
        toggle_theme()   # 전역 _theme 토글은 접근자로(모듈 분해 대비 교차모듈 쓰기 제거)
        self._apply_theme()
        _apply_windows_titlebar_dark(self)   # 윈도우: 메인 타이틀바도 새 테마로(맥은 no-op)
        # 열려있는 팝아웃 창들: 컨트롤 스타일시트 + 네이티브 타이틀바 + 브랜드 헤더 재적용
        for _w in (self._tf_popout, self._spec_popout, self._st_popout):
            if _w is not None:
                _w.setStyleSheet(self.styleSheet())   # 메인과 동일 컨트롤 스타일 갱신
                _apply_native_titlebar_dark(_w)
                _bh = getattr(_w, '_brand_hdr', None)   # Spectrum/Stereo 헤더 (TF는 restyle_theme가 처리)
                if _bh is not None:
                    _restyle_brand_header(_bh)

    def _on_lang_toggle(self):
        new = 'en' if cur_lang() == 'ko' else 'ko'   # 실제 반영은 settings 저장 후 재시작
        msg = ('언어를 바꾸려면 앱을 다시 시작합니다. 계속할까요?'
               if new == 'ko' else 'Restart the app to change language. Continue?')
        if _brand_msg(self, _tx('Language'), msg, kind='question', cancel_text=_tx('Cancel')) is not True:
            return
        self._settings['lang'] = new
        _save_settings(self._settings)
        self._restart_app()

    def _restart_app(self):
        import os, sys
        try:
            os.execv(sys.executable, [sys.executable] + sys.argv)
        except Exception as e:
            _alog.error(f'restart failed: {e}')
            _brand_msg(self, _tx('Restart'), _tx('Please restart the app manually.'))

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
        if self._db_lock: return   # dB축 수동 고정 중 → 자동맞춤 무시
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

        def set_channel_live(ch):
            for i in range(self.in_ch_cb.count()):
                if self.in_ch_cb.itemData(i) == ch:
                    self.in_ch_cb.setCurrentIndex(i); break   # → _on_input_ch_changed (재시작+calib로드)

        # 캘리브 창 단독 동작:
        #  · 분석 실행 중이면 in_ch_cb 를 전환(라이브 곡선도 그 채널로) → 메인 경로 사용
        #  · 정지 상태면 분석창/라이브카드는 그대로 두고, 캘리브 전용 경량 스트림으로
        #    레벨(dBFS)만 측정 (Start 안 눌러도 됨)
        was_running = self._spec_running()
        if was_running:
            set_channel = set_channel_live
        else:
            set_channel = self._calib_start_measure
            self._calib_start_measure(active_ch)

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
            # 취소 — 라이브 모드에서 채널이 바뀌었으면 원래 채널로 복원
            if was_running and (self.in_ch_cb.currentData() or 0) != active_ch:
                set_channel_live(active_ch)
        # 캘리브 전용 측정 스트림 정리(정지 상태에서 열었던 경우)
        if not was_running:
            self._calib_stop_measure()

    # ── 캘리브 전용 경량 측정 (분석창/라이브카드 없이 레벨만) ──────────
    def _calib_start_measure(self, ch):
        """정지 상태에서 캘리브 창만으로 측정 — 해당 채널 레벨(dBFS)만 계산.
        _process_audio(캔버스용 _pending) 와 라이브카드는 건드리지 않는다."""
        self._calib_stop_measure()
        idx = self.dev_cb.currentData()
        if idx is None or idx < 0:
            return
        with QMutexLocker(self._mutex):
            self._raw_spl_smooth = -100.0
        self._calib_ch = ch
        try:
            self._calib_sub = self.audio_engine.subscribe(idx, [ch], self.sample_rate)
        except Exception as e:
            self._calib_sub = None
            _alog.warning(f'캘리브 측정 스트림 시작 실패 ch={ch}: {e}')
            return
        self._calib_sub.chunk_ready.connect(self._calib_on_chunk, Qt.QueuedConnection)

    def _calib_on_chunk(self, buf_dict):
        buf = buf_dict.get(self._calib_ch)
        if buf is None and buf_dict:
            buf = next(iter(buf_dict.values()))
        if buf is None or not np.isfinite(buf).all():
            return
        rms = float(np.sqrt(np.mean(buf ** 2)))
        raw_dbfs = 20 * math.log10(max(rms, 1e-10))
        with QMutexLocker(self._mutex):
            va = METER_ATTACK if raw_dbfs > self._raw_spl_smooth else METER_RELEASE
            self._raw_spl_smooth += (raw_dbfs - self._raw_spl_smooth) * va

    def _calib_stop_measure(self):
        sub = getattr(self, '_calib_sub', None)
        if sub is not None:
            try: sub.chunk_ready.disconnect()
            except Exception: pass
            try: sub.close()
            except Exception: pass
        self._calib_sub = None

    # ── SPL 미터 측정 소스 선택 ───────────────────────────
    def _spl_source_list(self):
        """SPL 미터가 고를 수 있는 입력 소스 목록 → [(id, 라벨)]. id 0=primary."""
        pname = (getattr(self, '_spec_primary_name', '') or self.dev_cb.currentText() or 'Input')
        pch = (self.in_ch_cb.currentData() or 0) + 1
        out = [(0, f'1. {pname} · Ch{pch}')]
        for src in self._spec_extra:
            nm = src.get('name', '') or src.get('dev_name', '') or 'Input'
            out.append((src['id'], f'{src.get("num", 2)}. {nm} · Ch{src.get("ch", 0) + 1}'))
        return out

    def _spl_source_calib(self, sid):
        """소스(id)의 캘리브 오프셋 — primary 는 self.calib_offset, 추가 카드는 device:ch 조회."""
        if sid == 0:
            return self.calib_offset
        src = next((s for s in self._spec_extra if s['id'] == sid), None)
        if src is None:
            return self.calib_offset
        calibs = self._settings.get('calibrations', {})
        dev = src.get('dev_name', ''); ch = src.get('ch', 0)
        return float(calibs.get(f'{dev}:{ch}', calibs.get(dev, 0.0)))

    def _set_spl_source(self, sid):
        """SPL 미터 측정 소스 변경 — 라우팅 대상 + 창 calib 갱신."""
        ids = [s[0] for s in self._spl_source_list()]
        self._spl_source_id = sid if sid in ids else 0
        if getattr(self, 'spl_meter_win', None):
            self.spl_meter_win.set_calib_offset(self._spl_source_calib(self._spl_source_id))

    def _spl_inputs(self, buf, sr, calib, cache):
        """선택된 SPL 소스용 Z(cal)/A/C/fs_peak 계산. cache(dict)에 A/C 가중 테이블 보관."""
        db_raw = power_spectrum_db(buf)
        rms = float(np.sqrt(np.mean(buf ** 2)))
        raw_dbfs = 20 * math.log10(max(rms, 1e-10))
        fs_peak = 20 * math.log10(max(float(np.max(np.abs(buf))), 1e-10))
        aw = cache.get('aw'); cw = cache.get('cw')
        if aw is None or len(aw) != len(db_raw):
            freqs = np.fft.rfftfreq(len(buf), 1.0 / sr).astype(np.float32)
            aw = np.array([a_weight_db(f) for f in freqs])
            cw = np.array([c_weight_db(f) for f in freqs])
            cache['aw'] = aw; cache['cw'] = cw
        wa = np.clip(db_raw + aw + calib, -200, 100)
        wc = np.clip(db_raw + cw + calib, -200, 100)
        raw_dba = 10 * math.log10(max(float(np.sum(10 ** (wa / 10))), 1e-10))
        raw_dbc = 10 * math.log10(max(float(np.sum(10 ** (wc / 10))), 1e-10))
        return raw_dbfs + calib, raw_dba, raw_dbc, fs_peak

    def _apply_db_range(self):
        self.fft_cvs.db_max=self.db_max; self.fft_cvs.db_min=self.db_min
        self.oct_cvs.db_max=self.db_max; self.oct_cvs.db_min=self.db_min
        self.spectro_cvs.set_db_range(self.db_min,self.db_max)
        self.fft_cvs._db_lock=self._db_lock; self.oct_cvs._db_lock=self._db_lock   # 잠금 배지 동기
        self.fft_cvs._cache=None; self.oct_cvs._cache=None
        self.fft_cvs.update(); self.oct_cvs.update()

    # ── dB축 수동 고정 (우클릭 메뉴, 더블클릭 자동맞춤은 그대로) ──
    def _spec_db_menu(self, gpos):
        _db_axis_context_menu(self, gpos, self.db_max, self.db_min, self._db_lock,
                              on_apply=self._spec_db_apply, on_autofit=self._spec_db_autofit,
                              on_toggle_lock=self._spec_db_toggle)

    def _spec_db_apply(self, top, bot):
        self.db_max=float(top); self.db_min=float(bot); self.db_range=self.db_max-self.db_min
        self._db_lock=True; self._pending_auto_fit=False; self._apply_db_range(); self._persist_spec_db()

    def _spec_db_autofit(self):
        self._db_lock=False; self._pending_auto_fit=True; self._auto_fit_y_to_data(); self._apply_db_range(); self._persist_spec_db()

    def _spec_db_toggle(self):
        self._db_lock=not self._db_lock
        if not self._db_lock:                    # 해제 → 자동맞춤 재개 (메뉴 'back to auto'와 일치)
            self._pending_auto_fit=True; self._auto_fit_y_to_data()
        self._apply_db_range(); self._persist_spec_db()

    def _persist_spec_db(self):
        self._settings['spec_db_lock'] = bool(self._db_lock)
        self._settings['spec_db_top']  = float(self.db_max)
        self._settings['spec_db_bot']  = float(self.db_min)
        _save_settings(self._settings)
        self._update_spec_db_btn()

    def _spec_db_control(self):
        """툴바 dB 버튼 클릭 → 범위 대화상자 (자동/적용·고정)."""
        r = _ask_db_range(self, self.db_max, self.db_min)
        if r == 'auto':      self._spec_db_autofit()
        elif r is not None:  self._spec_db_apply(r[0], r[1])

    def _update_spec_db_btn(self):
        if not hasattr(self, 'spec_db_btn'): return
        self.spec_db_btn.setText(f'{self.db_max:+g} / {self.db_min:+g}' if self._db_lock else _tx('Auto'))
        if isinstance(self.spec_db_btn, _N2Button):
            self.spec_db_btn.set_active(self._db_lock)   # 잠금 시 값·아이콘 액센트색
        else:
            self.spec_db_btn.setStyleSheet(_db_ctrl_btn_style(self._db_lock))

    def _open_leq(self):
        if self.leq_win is None:
            self.leq_win=LeqWindow(self)
            self.leq_win.setStyleSheet(f'background:{T("bg2")};color:{T("text")};')
        self.leq_win.show(); self.leq_win.raise_()

    def _setup_float_child(self, win, w, h):
        """풀스크린 메인 위 SPL미터/알람: ①FullScreenAuxiliary+addChildWindow로 같은 Space에 정상크기
        부착 ②혹시 크게 떴으면 resize 보정 ③보정 끝나면 투명→표시(검은 풀스크린 플래시 방지)."""
        w = int(w); h = int(h)
        revealed = [False]
        def _reveal():
            if not revealed[0]:
                revealed[0] = True
                try: win.setWindowOpacity(1.0)
                except Exception: pass
        def _fix():
            try:
                _attach_as_child(win, self)   # ★ Aux + 진짜 자식 → 부모 풀스크린 Space 위 정상크기
                if win.width() > w * 1.4 or win.height() > h * 1.4:
                    win.resize(w, h)          # 안전장치: 크게 떴으면 크기 보정
                else:
                    _reveal()                 # 정상 크기 → 표시
            except Exception:
                pass
        for ms in (0, 90, 200, 380, 650):
            QTimer.singleShot(ms, _fix)
        def _safety():
            try:
                if win.width() > w * 1.4 or win.height() > h * 1.4:
                    win.resize(w, h)
            except Exception: pass
            _reveal()
        QTimer.singleShot(850, _safety)   # 최대 850ms: 줄이고 무조건 표시(검은 풀스크린 멈춤 방지)

    def show_float_popup(self, win, w, h, new):
        """★공용: 떠 있는 팝업창을 메인 위(풀스크린 포함)에 정상 크기로 안전하게 띄움.
        다음 버전에서 새 팝업창 만들 때 이 메서드로 열면 macOS 풀스크린 검은화면/Space점프/
        번쩍임 없이 뜬다. 전제: win은 부모=self로 생성됨(super().__init__(self, Qt.Window)).
        new=처음 생성 여부(처음일 때만 보조창 지정·크기 보정 수행). 동작 상세 = 메모리
        project_macos_float_over_fullscreen.
          순서: ①show 前 opacity0 + FullScreenAuxiliary(자동 풀스크린화 차단)
               ②show/raise ③addChildWindow(같은 Space) + 크기 보정 후 표시(_setup_float_child).
        ※메인이 풀스크린일 때만 자식부착 dance. 일반 창모드면 그냥 독립창으로 열어
          외부 모니터로 자유 이동 가능(자식부착하면 부모 Space에 묶여 못 옮김)."""
        fs = self.isFullScreen()
        if new and fs:
            win.setWindowOpacity(0.0)                       # 보정 전 숨김(블랙 플래시 방지)
            win.winId(); _set_fullscreen_auxiliary(win)     # show 前 보조창 지정(핵심 타이밍)
        win.show(); win.raise_()
        if new and fs:
            win._float_attached = True                      # _setup_float_child가 부착함
            self._setup_float_child(win, w, h)
        elif new:
            win._float_attached = False
            win.setWindowOpacity(1.0)                       # 일반 열기: 즉시 표시, 자유 이동

    def _open_spl_meter(self):
        new = self.spl_meter_win is None
        if new:
            self.spl_meter_win = SplMeterWindow(self)
            self.spl_meter_win.set_calib_offset(self._spl_source_calib(self._spl_source_id))
        self.show_float_popup(self.spl_meter_win,
                              self.spl_meter_win._open_w(), self.spl_meter_win._open_h(), new)

    def _open_spl_alarm(self):
        """SPL 임계 알람 — 메인의 자식 창. _process_audio가 직접 급전(SPL 미터와 무관)."""
        new = self.spl_alarm_win is None
        if new:
            self.spl_alarm_win = SplAlarmWindow(self)
            self.spl_alarm_win.set_calib_offset(self.calib_offset)
        self.show_float_popup(self.spl_alarm_win, 210, 150, new)

    def _open_show_mode(self):
        """FOH 글랜스 쇼 모드 — 풀스크린 거대 디스플레이. 토글(열려있으면 닫음).
        _process_audio가 push로 급전. 한계는 SPL 알람 설정 공유."""
        if getattr(self, 'show_mode_win', None) is not None:
            self.show_mode_win.close(); self.show_mode_win = None; return
        self.show_mode_win = ShowModeWindow(self)
        a = self._settings.get('spl_alarm', {})
        self.show_mode_win.set_limit(a.get('limit', 100.0), a.get('amber', 3.0))
        self.show_mode_win.showFullScreen()

    def _open_tf_window(self):
        if self._tf_popout is not None:
            self._tf_popout.raise_(); self._tf_popout.activateWindow()
        else:
            self._switch_tab(1)

    # ── TF 별도 창(멀티모니터) 팝아웃 / 도킹 ──────────────
    def _sync_stack_to_active_tab(self):
        """선택된 탭 버튼(진실 소스)에 맞춰 main/sub 스택 표시를 동기화.
        팝아웃 도킹 후 placeholder 제거로 Qt가 current를 엉뚱한 페이지로 옮기는 것 보정."""
        keys = ['spectrum', 'transfer', 'stereo']
        active = next((i for i, k in enumerate(keys) if self._tab_btns[k].isChecked()), 0)
        self.main_stack.setCurrentIndex(active)
        self.sub_stack.setCurrentIndex(active)

    def _toggle_tf_popout(self):
        if self._tf_popout is not None:
            self._dock_tf()
        else:
            self._popout_tf()

    def _popout_tf(self):
        """TF의 헤더+툴바+본체를 별도 창으로 모아 띄운다(멀티모니터). 오디오는
        공유 엔진이라 reparent해도 끊기지 않는다. 메인 탭 자리엔 플레이스홀더."""
        tf = self.tf_win
        if tf is None or self._tf_popout is not None or self._split_on:
            return
        win = _TFPopoutWindow(self)
        win.setStyleSheet(self.styleSheet())   # 메인 창과 동일한 컨트롤 스타일(버튼/콤보/스핀박스) 통째 적용 → 임베드와 동일 디자인
        lay = QVBoxLayout(win); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(0)
        # 헤더 — 임베드 모드에서 숨겨둔 _hdr을 창에 표시
        tf._hdr.setParent(None); lay.addWidget(tf._hdr); tf._hdr.show()
        # status_lbl은 멀티카드 시작 경로에서 갱신 안 돼 신뢰 불가(임베드에선 숨겨져 무관했음)
        # → 팝아웃 헤더에선 숨김. 실행 상태는 카드 Stop 버튼/Avg 카운터로 충분.
        tf.status_lbl.hide()
        # 툴바 — sub_stack page1에서 떼어 창으로
        self._sp1_lay.removeWidget(self._tf_tb_wrap)
        self._tf_tb_wrap.setParent(None)
        lay.addWidget(self._tf_tb_wrap)
        # 툴바 접기 토글 — tf._hdr 우측에 1회 생성(재팝아웃 중복 방지), _tf_tb_wrap 토글
        if not hasattr(tf, '_hdr_toggle'):
            tf._hdr_toggle = _CollapseBtn()
            tf._hdr.layout().addWidget(tf._hdr_toggle)
            tf._hdr_toggle.toggled.connect(lambda hide: self._tf_tb_wrap.setVisible(not hide))
        tf._hdr_toggle.setChecked(False); self._tf_tb_wrap.setVisible(True)
        # 본체 — main_stack index1에서 떼고 그 자리에 플레이스홀더
        was_tf_tab = (self.main_stack.currentIndex() == 1)
        self.main_stack.removeWidget(tf)
        self._tf_placeholder = self._build_tf_placeholder()
        self.main_stack.insertWidget(1, self._tf_placeholder)
        # 캡처 드로어를 TF 본체 왼쪽에 동반 — 멀티모니터에서 TF 캡처를 팝아웃 창에서 바로 관리.
        # 드로어는 앱 전체 1개(공유)라 옮기면 메인엔 없음 → 메인 탭전환 가드(_drawer_owner)로 충돌 차단.
        _tf_body_row = QWidget()
        _brl = QHBoxLayout(_tf_body_row); _brl.setContentsMargins(0, 0, 0, 0); _brl.setSpacing(0)
        self._capture_drawer.setParent(None)
        self._capture_drawer.set_active_mode('tf')
        self._capture_drawer.setVisible(tf._drawer_btn.isChecked())
        _brl.addWidget(self._capture_drawer, 0)
        _brl.addWidget(tf, 1)
        lay.addWidget(_tf_body_row, 1); tf.show()
        self._drawer_owner = 'tf_popout'
        self._drawer_btn.setEnabled(False)   # 메인(Spectrum) 툴바 드로어 버튼 — 드로어가 TF 팝아웃에 있는 동안 비활성
        _diag('tf_popout_drawer', action='popout', vis=self._capture_drawer.isVisible())
        if was_tf_tab:
            self.main_stack.setCurrentWidget(self._tf_placeholder)
        self._tf_popout = win
        try: tf._popout_btn.setChecked(True)
        except Exception: pass
        win.resize(1100, 640)
        # 위치/크기 복원 — 지난번 둔 자리(그 모니터)에 다시. 독립 창이라 메인 안 따라감.
        placed = False
        geom = self._settings.get('tf_popout_geom')
        if geom and len(geom) == 4:
            from PyQt5.QtCore import QRect
            r = QRect(*geom)
            # 저장된 위치가 현재 연결된 화면 안에 있을 때만 복원(모니터 분리 대비)
            if any(s.availableGeometry().intersects(r) for s in QApplication.screens()):
                win.setGeometry(r); placed = True
        if not placed:
            # 첫 팝아웃 — 보조 모니터 있으면 거기 중앙, 없으면 기본 위치
            screens = QApplication.screens()
            if len(screens) > 1:
                cur = self.screen()
                others = [s for s in screens if s is not cur]
                geo = (others[0] if others else screens[-1]).availableGeometry()
                win.move(geo.center().x() - win.width() // 2,
                         geo.center().y() - win.height() // 2)
        win.show(); win.raise_(); win.activateWindow()
        QTimer.singleShot(0, lambda w=win: _apply_native_titlebar_dark(w))  # Qt 창설정 후 적용

    def _dock_tf(self, via_close=False):
        """별도 창의 TF를 메인 탭으로 되돌린다(팝아웃의 역순)."""
        win = self._tf_popout
        if win is None:
            return
        # 위치/크기 기억 — 다음 팝아웃/재시작 시 그 모니터 그 자리로 복원
        try:
            g = win.geometry()
            self._settings['tf_popout_geom'] = [g.x(), g.y(), g.width(), g.height()]
            _save_settings(self._settings)
        except Exception:
            pass
        self._tf_popout = None          # 재진입 가드 (closeEvent 재귀 차단)
        win._docking = True
        tf = self.tf_win
        # 헤더 — 다시 숨김(임베드 원상태)
        tf.status_lbl.show()
        tf._hdr.setParent(None); tf._hdr.hide()
        # 툴바 — 다시 sub_stack page1로 (접혀있었으면 다시 표시)
        self._tf_tb_wrap.setParent(None); self._tf_tb_wrap.setVisible(True)
        self._sp1_lay.addWidget(self._tf_tb_wrap)
        # 본체 — 플레이스홀더 제거 후 index1 복원
        if self._tf_placeholder is not None:
            self.main_stack.removeWidget(self._tf_placeholder)
            self._tf_placeholder.deleteLater(); self._tf_placeholder = None
        self.main_stack.insertWidget(1, tf)
        try: tf._popout_btn.setChecked(False)
        except Exception: pass
        self._sync_stack_to_active_tab()   # 화면을 현재 탭에 맞춤(인덱스 꼬임 방지)
        # 캡처 드로어 — 메인 창 좌측으로 복귀 + 현재 탭에 맞춰 모드/가시성 복원
        self._capture_drawer.setParent(None)
        self._body_lay.insertWidget(0, self._capture_drawer)
        self._drawer_owner = None
        self._drawer_btn.setEnabled(True)
        _i = self.main_stack.currentIndex()
        self._capture_drawer.set_active_mode('tf' if _i == 1 else 'spec')
        if _i == 2: self._capture_drawer.setVisible(False)
        _diag('tf_popout_drawer', action='dock', tab=_i)
        if not via_close:
            win.close()
        win.deleteLater()

    def _build_tf_placeholder(self):
        ph = QWidget(); ph.setStyleSheet(f'background:{T("bg")};')
        v = QVBoxLayout(ph); v.addStretch()
        lbl = QLabel('Transfer Function is in a separate window.')
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setStyleSheet(f'color:{T("text_dim")};font-size:15px;')
        v.addWidget(lbl)
        btn = QPushButton('  Return to Main'); btn.setIcon(_icon('extlink'))
        btn.setFixedHeight(34); btn.setStyleSheet(_txn_style('accent'))
        btn.clicked.connect(self._dock_tf)
        row = QHBoxLayout(); row.addStretch(); row.addWidget(btn); row.addStretch()
        v.addLayout(row); v.addStretch()
        return ph

    # ── Spectrum 별도 창(멀티모니터) 팝아웃 / 도킹 — TF와 동형 ──────────
    def _toggle_spec_popout(self):
        if self._spec_popout is not None:
            self._dock_spec()
        else:
            self._popout_spec()

    def _popout_spec(self):
        """Spectrum 본체(그래프+정보패널)+툴바를 별도 창으로. 오디오는 공유엔진이라 안 끊김."""
        page = self._spec_page0
        if page is None or self._spec_popout is not None or self._split_on:
            return
        win = _SpectrumPopoutWindow(self)
        win.setStyleSheet(self.styleSheet())   # 메인 창과 동일한 컨트롤 스타일(버튼/콤보/스핀박스) 통째 적용 → 임베드와 동일 디자인
        lay = QVBoxLayout(win); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(0)
        _hdr = _make_brand_header('Spectrum'); win._brand_hdr = _hdr   # 로고+이름(가운데)+접기토글
        lay.addWidget(_hdr)
        # 툴바 — sub_stack page0(_sp0)에서 떼어 창으로
        self._sp0_lay.removeWidget(self._spec_tb_wrap)
        self._spec_tb_wrap.setParent(None)
        lay.addWidget(self._spec_tb_wrap)
        _hdr._toggle_btn.toggled.connect(lambda hide: self._spec_tb_wrap.setVisible(not hide))
        self._drawer_btn.hide()   # 캡처 드로어는 Spectrum 팝아웃을 따라가지 않음 → 툴바 좌측의 무의미한 토글 버튼 숨김
        # 본체 — main_stack index0에서 떼고 그 자리에 플레이스홀더
        was_tab = (self.main_stack.currentIndex() == 0)
        self.main_stack.removeWidget(page)
        self._spec_placeholder = self._build_spec_placeholder()
        self.main_stack.insertWidget(0, self._spec_placeholder)
        lay.addWidget(page, 1); page.show()
        if was_tab:
            self.main_stack.setCurrentWidget(self._spec_placeholder)
        self._spec_popout = win
        try: self._spec_popout_btn.setChecked(True)
        except Exception: pass
        win.resize(1100, 640)
        placed = False
        geom = self._settings.get('spec_popout_geom')
        if geom and len(geom) == 4:
            from PyQt5.QtCore import QRect
            r = QRect(*geom)
            if any(s.availableGeometry().intersects(r) for s in QApplication.screens()):
                win.setGeometry(r); placed = True
        if not placed:
            screens = QApplication.screens()
            if len(screens) > 1:
                cur = self.screen()
                others = [s for s in screens if s is not cur]
                geo = (others[0] if others else screens[-1]).availableGeometry()
                win.move(geo.center().x() - win.width() // 2,
                         geo.center().y() - win.height() // 2)
        win.show(); win.raise_(); win.activateWindow()
        QTimer.singleShot(0, lambda w=win: _apply_native_titlebar_dark(w))  # Qt 창설정 후 적용

    def _dock_spec(self, via_close=False):
        win = self._spec_popout
        if win is None:
            return
        try:
            g = win.geometry()
            self._settings['spec_popout_geom'] = [g.x(), g.y(), g.width(), g.height()]
            _save_settings(self._settings)
        except Exception:
            pass
        self._spec_popout = None
        win._docking = True
        page = self._spec_page0
        # 툴바 — 다시 sub_stack page0로 (접혀있었으면 다시 표시)
        self._spec_tb_wrap.setParent(None); self._spec_tb_wrap.setVisible(True)
        self._sp0_lay.addWidget(self._spec_tb_wrap)
        self._drawer_btn.show()   # 도킹 복귀 → 드로어 토글 버튼 다시 표시
        # 본체 — 플레이스홀더 제거 후 index0 복원
        if self._spec_placeholder is not None:
            self.main_stack.removeWidget(self._spec_placeholder)
            self._spec_placeholder.deleteLater(); self._spec_placeholder = None
        self.main_stack.insertWidget(0, page)
        try: self._spec_popout_btn.setChecked(False)
        except Exception: pass
        self._sync_stack_to_active_tab()   # 화면을 현재 탭에 맞춤(인덱스 꼬임 방지)
        if not via_close:
            win.close()
        win.deleteLater()

    def _build_spec_placeholder(self):
        ph = QWidget(); ph.setStyleSheet(f'background:{T("bg")};')
        v = QVBoxLayout(ph); v.addStretch()
        lbl = QLabel('Spectrum is in a separate window.')
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setStyleSheet(f'color:{T("text_dim")};font-size:15px;')
        v.addWidget(lbl)
        btn = QPushButton('  Return to Main'); btn.setIcon(_icon('extlink'))
        btn.setFixedHeight(34); btn.setStyleSheet(_txn_style('accent'))
        btn.clicked.connect(self._dock_spec)
        row = QHBoxLayout(); row.addStretch(); row.addWidget(btn); row.addStretch()
        v.addLayout(row); v.addStretch()
        return ph

    # ── Stereo 별도 창(멀티모니터) 팝아웃 / 도킹 — TF/Spectrum과 동형 ──────
    def _toggle_st_popout(self):
        if self._st_popout is not None:
            self._dock_st()
        else:
            self._popout_st()

    def _popout_st(self):
        page = self.stereo_page
        if page is None or self._st_popout is not None or self._split_on:
            return
        win = _StereoPopoutWindow(self)
        win.setStyleSheet(self.styleSheet())   # 메인 창과 동일한 컨트롤 스타일(버튼/콤보/스핀박스) 통째 적용 → 임베드와 동일 디자인
        lay = QVBoxLayout(win); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(0)
        _hdr = _make_brand_header('Stereo Loudness'); win._brand_hdr = _hdr   # 로고+이름+접기토글
        lay.addWidget(_hdr)
        # 툴바 — sub_stack page2(_sp2)에서 떼어 창으로
        self._sp2_lay.removeWidget(self._st_tb_wrap)
        self._st_tb_wrap.setParent(None)
        lay.addWidget(self._st_tb_wrap)
        _hdr._toggle_btn.toggled.connect(lambda hide: self._st_tb_wrap.setVisible(not hide))
        # 본체 — main_stack index2에서 떼고 그 자리에 플레이스홀더
        was_tab = (self.main_stack.currentIndex() == 2)
        self.main_stack.removeWidget(page)
        self._st_placeholder = self._build_st_placeholder()
        self.main_stack.insertWidget(2, self._st_placeholder)
        lay.addWidget(page, 1); page.show()
        if was_tab:
            self.main_stack.setCurrentWidget(self._st_placeholder)
        self._st_popout = win
        try: self._st_popout_btn.setChecked(True)
        except Exception: pass
        win.resize(1100, 640)
        placed = False
        geom = self._settings.get('st_popout_geom')
        if geom and len(geom) == 4:
            from PyQt5.QtCore import QRect
            r = QRect(*geom)
            if any(s.availableGeometry().intersects(r) for s in QApplication.screens()):
                win.setGeometry(r); placed = True
        if not placed:
            screens = QApplication.screens()
            if len(screens) > 1:
                cur = self.screen()
                others = [s for s in screens if s is not cur]
                geo = (others[0] if others else screens[-1]).availableGeometry()
                win.move(geo.center().x() - win.width() // 2,
                         geo.center().y() - win.height() // 2)
        win.show(); win.raise_(); win.activateWindow()
        QTimer.singleShot(0, lambda w=win: _apply_native_titlebar_dark(w))  # Qt 창설정 후 적용

    def _dock_st(self, via_close=False):
        win = self._st_popout
        if win is None:
            return
        try:
            g = win.geometry()
            self._settings['st_popout_geom'] = [g.x(), g.y(), g.width(), g.height()]
            _save_settings(self._settings)
        except Exception:
            pass
        self._st_popout = None
        win._docking = True
        page = self.stereo_page
        self._st_tb_wrap.setParent(None); self._st_tb_wrap.setVisible(True)
        self._sp2_lay.addWidget(self._st_tb_wrap)
        if self._st_placeholder is not None:
            self.main_stack.removeWidget(self._st_placeholder)
            self._st_placeholder.deleteLater(); self._st_placeholder = None
        self.main_stack.insertWidget(2, page)
        try: self._st_popout_btn.setChecked(False)
        except Exception: pass
        self._sync_stack_to_active_tab()
        if not via_close:
            win.close()
        win.deleteLater()

    def _build_st_placeholder(self):
        ph = QWidget(); ph.setStyleSheet(f'background:{T("bg")};')
        v = QVBoxLayout(ph); v.addStretch()
        lbl = QLabel('Stereo Loudness is in a separate window.')
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setStyleSheet(f'color:{T("text_dim")};font-size:15px;')
        v.addWidget(lbl)
        btn = QPushButton('  Return to Main'); btn.setIcon(_icon('extlink'))
        btn.setFixedHeight(34); btn.setStyleSheet(_txn_style('accent'))
        btn.clicked.connect(self._dock_st)
        row = QHBoxLayout(); row.addStretch(); row.addWidget(btn); row.addStretch()
        v.addLayout(row); v.addStretch()
        return ph

    # ── STEP 3 (A안): 동시 보기 — 한 창 2칸, 칸마다 '탭 통째'(툴바+사이드바) 선택 ──────
    def _split_tabinfo(self, key):
        """탭 key → (툴바wrap, 본체, 원래 sub 레이아웃, 원래 main_stack 인덱스)."""
        return {
            'Spectrum':          (self._spec_tb_wrap, self._spec_page0, self._sp0_lay, 0),
            'Transfer Function': (self._tf_tb_wrap,   self.tf_win,      self._sp1_lay, 1),
            'Stereo Loudness':   (self._st_tb_wrap,   self.stereo_page, self._sp2_lay, 2),
        }[key]

    def _toggle_split(self):
        if self._split_on:
            self._switch_tab(self._split_prev_tab)   # 분할 해제 + 이전 탭 복원
        else:
            self._enter_split()

    def _enter_split(self):
        """한 창을 2칸으로 — 각 칸은 탭 통째(툴바+그래프+사이드바)라 컨트롤·측정 그대로.
        칸 상단 드롭다운으로 어떤 탭을 볼지 선택. 팝아웃 reparent 방식 재활용."""
        if self._split_on:
            return
        if self._tf_popout is not None: self._dock_tf()
        if self._spec_popout is not None: self._dock_spec()
        if self._st_popout is not None: self._dock_st()
        keys = ['spectrum', 'transfer', 'stereo']
        self._split_prev_tab = next((i for i, k in enumerate(keys) if self._tab_btns[k].isChecked()), 0)
        tabkeys = ['Spectrum', 'Transfer Function', 'Stereo Loudness']
        _combo_ss = ('QComboBox{background:#2C2C2E;color:#E8ECF4;border:1px solid #48484A;'
                     'border-radius:6px;padding:2px 10px;font-size:12px;}'
                     'QComboBox::drop-down{border:none;width:18px;}'
                     'QComboBox QAbstractItemView{background:#2C2C2E;color:#E8ECF4;'
                     'selection-background-color:#4E7DF0;border:1px solid #48484A;}')
        sp = QSplitter(Qt.Vertical); sp.setHandleWidth(7); sp.setStyleSheet(_splitter_qss())
        self._split_panes = [None, None]
        self._split_sel = []; self._split_tb_lay = []; self._split_body_lay = []
        for i in range(2):
            pane = QWidget(); pv = QVBoxLayout(pane); pv.setContentsMargins(0, 0, 0, 0); pv.setSpacing(0)
            selbar = QWidget(); selbar.setFixedHeight(30); selbar.setStyleSheet(f'background:{T("bg2")};')
            slb = QHBoxLayout(selbar); slb.setContentsMargins(8, 2, 8, 2)
            combo = QComboBox(); combo.setStyleSheet(_combo_ss); combo.setFixedHeight(24); combo.setFixedWidth(200)
            for k in tabkeys: combo.addItem(k)
            slb.addWidget(combo); slb.addStretch()
            pv.addWidget(selbar)
            tb_slot = QWidget(); tbl = QVBoxLayout(tb_slot); tbl.setContentsMargins(0, 0, 0, 0); tbl.setSpacing(0)
            pv.addWidget(tb_slot)
            body_slot = QWidget(); bdl = QVBoxLayout(body_slot); bdl.setContentsMargins(0, 0, 0, 0); bdl.setSpacing(0)
            pv.addWidget(body_slot, 1)
            self._split_sel.append(combo); self._split_tb_lay.append(tbl); self._split_body_lay.append(bdl)
            sp.addWidget(pane); sp.setCollapsible(i, False)
        sp.setSizes([500, 500])
        self._split_widget = sp
        self.main_stack.addWidget(sp); self.main_stack.setCurrentWidget(sp)
        defaults = ['Spectrum', 'Transfer Function']
        for i in range(2):
            self._mount_tab(i, defaults[i])
            c = self._split_sel[i]
            c.blockSignals(True); c.setCurrentText(defaults[i]); c.blockSignals(False)
            c.currentTextChanged.connect(lambda key, pi=i: self._set_pane_tab(pi, key))
        self._split_prev_tb_vis = self.toolbar_wrapper.isVisible()
        self.toolbar_wrapper.setVisible(False)
        if hasattr(self, 'toolbar_underline'):
            self.toolbar_underline.setVisible(False)
        for b in self._tab_btns.values():
            b.setChecked(False)
        self._apply_tab_styles()
        self._split_on = True
        if hasattr(self, '_split_act'):
            self._split_act.setText('Exit Split View')

    def _mount_tab(self, pane_idx, key):
        tb, body, sub_lay, _midx = self._split_tabinfo(key)
        sub_lay.removeWidget(tb); tb.setParent(None)
        self._split_tb_lay[pane_idx].addWidget(tb)
        if self.main_stack.indexOf(body) >= 0:
            self.main_stack.removeWidget(body)
        self._split_body_lay[pane_idx].addWidget(body); body.show()
        self._split_panes[pane_idx] = key

    def _restore_tab(self, key):
        tb, body, sub_lay, midx = self._split_tabinfo(key)
        tb.setParent(None); sub_lay.addWidget(tb)
        if self.main_stack.indexOf(body) < 0:
            self.main_stack.insertWidget(midx, body)

    def _set_pane_tab(self, pane_idx, key):
        cur = self._split_panes[pane_idx]
        if key == cur:
            return
        other = self._split_panes[1 - pane_idx]
        if cur is not None:
            self._restore_tab(cur)
        if key == other:
            # 스왑: 상대 칸도 홈으로 보냈다가 cur를 상대 칸에
            if other is not None:
                self._restore_tab(other)
            self._mount_tab(pane_idx, key)
            self._mount_tab(1 - pane_idx, cur)
            sel = self._split_sel[1 - pane_idx]
            sel.blockSignals(True); sel.setCurrentText(cur); sel.blockSignals(False)
        else:
            self._mount_tab(pane_idx, key)

    def _exit_split(self):
        if not self._split_on:
            return
        # 모든 탭을 홈으로 복원(오름차순 main 인덱스 → 위치 정확)
        for key in ('Spectrum', 'Transfer Function', 'Stereo Loudness'):
            self._restore_tab(key)
        sp = self._split_widget
        if sp is not None:
            self.main_stack.removeWidget(sp)
            sp.deleteLater()
        self._split_widget = None
        self._split_panes = [None, None]
        self._split_sel = []; self._split_tb_lay = []; self._split_body_lay = []
        vis = getattr(self, '_split_prev_tb_vis', True)
        self.toolbar_wrapper.setVisible(vis)
        if hasattr(self, 'toolbar_underline'):
            self.toolbar_underline.setVisible(vis)
        self._split_on = False
        if hasattr(self, '_split_act'):
            self._split_act.setText('Split View (2 panes)')

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
        self.dev_btn.setText(name or 'Select Device')

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
            _timed_out_msg = 'Device search timed out'
            t=threading.Thread(target=_query,daemon=True); t.start()
            t.join(timeout=3.0)
            if result.empty():
                self.dev_cb.addItem(_timed_out_msg,-1)
                self.dev_cb.blockSignals(False); return
            status,payload=result.get_nowait()
            if status=='err':
                self.dev_cb.addItem(f'Error: {payload}',-1)
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
            _pref = _win_preferred_hostapi()   # Windows: WASAPI만(중복 호스트API 제거), 그 외 None=전체
            if _pref is not None:
                _diag('audio_hostapi', tab='spectrum', wasapi_idx=_pref, n_total=len(devs))
            for i,d in enumerate(devs):
                if not _dev_hostapi_ok(d, _pref): continue
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
            self.mic_st.setText(f'{self.dev_cb.count()} detected')
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
            self.dev_cb.addItem(f'Error: {e}',-1)
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
        self.stereo_page.set_target(val)   # 타겟 동기화 + 즉시 재그리기(Start 불필요) + 편차 갱신

    def _st_toggle(self):
        if self.stereo_page._running:
            self.stereo_page.stop()
            self._st_start_btn.setText('Start (S)')
            self._go_style(self._st_start_btn)
            _alog.info('Stereo & Loudness 중지')
        else:
            idx=self.dev_cb.currentData()
            if idx is None or idx<0:
                from PyQt5.QtWidgets import QMessageBox
                _BrandBox.warning(self, _tx('No Device'),
                    _tx('Select an input device in the Spectrum tab first.'))
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
                _BrandBox.warning(self, _tx('Device Error'), _tx('Cannot read device info:\n{e}').format(e=e))
                return
            if n_ch<1:
                from PyQt5.QtWidgets import QMessageBox
                _BrandBox.warning(self, _tx('Device Error'), _tx('The selected device has no input channels.'))
                return
            _ld=self._st_l_cb.currentData(); _rd=self._st_r_cb.currentData()   # 0-based 채널 데이터 → 'or'는 Ch1(=0) falsy로 오매핑
            l_ch=min(_ld if _ld is not None else 0, n_ch-1)
            r_ch=min(_rd if _rd is not None else 1, n_ch-1)
            _alog.info(f'Stereo 시작  device="{dev_name}"({idx})  L=ch{l_ch}  R=ch{r_ch}  sr={sr}')
            self.stereo_page.start(idx, sr, l_ch, r_ch, self.audio_engine)
            self._st_start_btn.setText('Stop (S)')
            self._stop_style(self._st_start_btn)

    def _on_stereo_error(self, msg):
        """StereoAudioThread 오류 → 버튼 리셋 + 경고."""
        self._st_start_btn.setText('Start (S)')
        self._go_style(self._st_start_btn)
        _alog.warning(f'Stereo 오류 → UI 리셋: {msg}')
        from PyQt5.QtWidgets import QMessageBox
        _BrandBox.warning(self, _tx('Stereo Input Error'),
            _tx('Cannot open stereo input stream:\n\n{msg}\n\n• Check the input device in the Spectrum tab.\n• Another app may be holding the device.').format(msg=msg))

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
        # primary 입력 채널 변경 → primary 카드만 재시작(개별로 꺼둔 추가 카드는 안 건드림)
        self._rebuild_ch_cards()
        if self._primary_running():
            self._card_stop(0); self._card_start(0)

    def _on_device_changed(self, _):
        name = self.dev_cb.currentText()
        self._update_dev_btn_text()
        _alog.info(f'입력 디바이스 변경  device="{name}"')
        self._settings['last_device'] = name
        _save_settings(self._settings)
        self._update_input_ch_cb()
        ch = self.in_ch_cb.currentData() or 0
        self._load_calib_for_device(name, ch)
        # primary 입력 장치 변경 → primary 카드만 재시작(개별로 꺼둔 추가 카드는 안 건드림)
        self._rebuild_ch_cards()
        if self._primary_running():
            self._card_stop(0); self._card_start(0)
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
        """Spectrum 입력 — primary 또는 추가 카드 중 하나라도 측정 중인지."""
        return self._primary_sub is not None or any(s.get('sub') for s in self._spec_extra)

    def _primary_running(self):
        return self._primary_sub is not None

    def _toggle(self):
        # 툴바 Start = 전부 시작/정지 (카드별 개별 제어는 각 카드 LED 파워 점)
        if self._spec_running(): self._stop()
        else: self._start()

    def _start(self):
        # Start All — primary + 모든 추가 카드 측정 시작
        self._card_start(0)
        for s in list(self._spec_extra):
            if not s.get('sub'): self._card_start(s['id'])

    def _stop(self):
        # Stop All
        for s in list(self._spec_extra):
            if s.get('sub'): self._card_stop(s['id'])
        if self._primary_running(): self._card_stop(0)

    # ── 카드별 Start (측정 on/off) ─────────────────────────────
    def _card_toggle(self, card_id):
        if card_id == 0:
            self._card_stop(0) if self._primary_running() else self._card_start(0)
            return
        s = next((x for x in self._spec_extra if x['id'] == card_id), None)
        if s is None: return
        self._card_stop(card_id) if s.get('sub') else self._card_start(card_id)

    def _card_start(self, card_id):
        first = not self._spec_running()
        if card_id == 0:
            if self._primary_running(): return
            if not self._open_primary_sub(): return
        else:
            s = next((x for x in self._spec_extra if x['id'] == card_id), None)
            if s is None or s.get('sub'): return
            self._open_spec_sub(s)
            if not s.get('sub'): return   # 열기 실패
        if first:   # 첫 소스 시작 → 브랜드 엠프티 스테이트 숨김
            self.fft_cvs._idle_hint = False; self.oct_cvs._idle_hint = False
        _diag('spec_card_start', card=card_id, first=first, any_run=self._spec_running())
        self._refresh_running_ui()

    def _card_stop(self, card_id):
        if card_id == 0:
            self._close_primary_sub()
            if self._primary_card is not None: self._primary_card.reset()
        else:
            s = next((x for x in self._spec_extra if x['id'] == card_id), None)
            if s is None: return
            self._close_spec_sub(s)
            if s.get('card'): s['card'].reset()
            self._clear_extra_curve(card_id)
        if not self._spec_running():
            self._spec_teardown()   # 마지막 소스 정지 → 전역 정리
        _diag('spec_card_stop', card=card_id, any_run=self._spec_running())
        self._refresh_running_ui()

    def _open_primary_sub(self):
        """primary 카드 측정 시작 — SR 자동맞춤 + 스무딩 리셋 + 엔진 구독. 성공 시 True."""
        idx = self.dev_cb.currentData()
        if idx is None or idx < 0: return False
        # USB 재연결 후 macOS device index 재할당 대비 이름으로 재조회 (Windows=WASAPI 한정)
        dev_name = self.dev_cb.currentText()
        _pref = _win_preferred_hostapi()
        try:
            for i, d in enumerate(sd.query_devices()):
                if not _dev_hostapi_ok(d, _pref): continue
                if d['name'] == dev_name and d['max_input_channels'] >= 1:
                    idx = i; break
        except Exception: pass
        _SR_MAP = {44100:0, 48000:1, 88200:2, 96000:3}
        try:
            native_sr = int(sd.query_devices(idx)['default_samplerate'])
            if native_sr in _SR_MAP and native_sr != self.sample_rate:
                self.sample_rate = native_sr
                self.sr_cb.blockSignals(True); self.sr_cb.setCurrentIndex(_SR_MAP[native_sr]); self.sr_cb.blockSignals(False)
                _alog.info(f'SR 자동 조정  device_native={native_sr}')
            elif native_sr not in _SR_MAP:
                fallback = 48000 if native_sr >= 48000 else 44100
                if fallback != self.sample_rate:
                    self.sample_rate = fallback
                    self.sr_cb.blockSignals(True); self.sr_cb.setCurrentIndex(_SR_MAP[fallback]); self.sr_cb.blockSignals(False)
                _alog.info(f'SR 폴백  device_native={native_sr} → app_sr={self.sample_rate}')
        except Exception: pass
        with QMutexLocker(self._mutex):
            self._avg_buf.clear(); self._fft_smooth=None; self._pow_smooth=None
            self._spl_smooth=-100.0; self._pending=None
            self._raw_spl_smooth=-100.0; self._raw_peak_smooth=-100.0
            self._dba_smooth=-100.0; self._dbc_smooth=-100.0
        ch = self.in_ch_cb.currentData() or 0
        try:
            self._primary_sub = self.audio_engine.subscribe(idx, [ch], self.sample_rate)
        except Exception as e:
            self._primary_sub = None
            self._on_audio_error(str(e)); return False
        self._primary_sub.chunk_ready.connect(self._process_audio_multi, Qt.QueuedConnection)
        self._primary_sub.error.connect(self._on_audio_error, Qt.QueuedConnection)
        self._primary_sub.disconnected.connect(self._on_device_disconnected, Qt.QueuedConnection)
        freqs = np.fft.rfftfreq(self.fft_size, 1.0/self.sample_rate)
        self._aw_table = np.array([a_weight_db(f) for f in freqs])
        self._cw_table = np.array([c_weight_db(f) for f in freqs])
        return True

    def _close_primary_sub(self):
        if self._primary_sub is not None:
            try:
                self._primary_sub.chunk_ready.disconnect()
                self._primary_sub.error.disconnect()
                self._primary_sub.disconnected.disconnect()
            except Exception: pass
            try: self._primary_sub.close()
            except Exception: pass
            self._primary_sub = None
        with QMutexLocker(self._mutex):
            self._avg_buf.clear(); self._fft_smooth=None; self._pow_smooth=None
            self._raw_spl_smooth=-100.0; self._raw_peak_smooth=-100.0
            self._dba_smooth=-100.0; self._dbc_smooth=-100.0

    def _refresh_running_ui(self):
        """전역 상태(툴바 버튼·상태라벨·INFO)와 카드별 LED를 현재 실행상태로 동기화."""
        running = self._spec_running()
        self.start_btn.setText('Stop (S)' if running else 'Start (S)')
        (self._stop_style if running else self._go_style)(self.start_btn)
        if running:
            self.status_lbl.setText('● Running'); self.status_lbl.setStyleSheet(f'color:{T("green")};font-size:11px;')
            self.mic_st.setText('Connected'); self.mic_st.setStyleSheet(f'color:{T("green")};font-size:10px;')
            self.i_sr.setText(f'{self.sample_rate/1000:.1f} kHz')
            self.i_fft.setText(str(self.fft_size))
            self.i_res.setText(f'{self.sample_rate/self.fft_size:.1f} Hz')
        else:
            self.status_lbl.setText('● Standby'); self.status_lbl.setStyleSheet(f'color:{T("text_dim")};font-size:11px;')
            self.mic_st.setText('Disconnected'); self.mic_st.setStyleSheet(f'color:{T("text_dim")};font-size:10px;')
        if self._primary_card is not None:
            self._primary_card.set_running(self._primary_running())
        for s in self._spec_extra:
            if s.get('card'): s['card'].set_running(bool(s.get('sub')))

    def _spec_teardown(self):
        """마지막 소스 정지 시 전역 정리 — 캔버스/버퍼/라벨 리셋 + 엠프티 스테이트 복귀."""
        with QMutexLocker(self._mutex):
            self._pending=None
        self.fft_cvs.clear(); self.oct_cvs.clear(); self.spectro_cvs.clear()
        self.fft_cvs.clear_all_channels(); self.oct_cvs.clear_all_channels()
        self.fft_cvs._idle_hint = True; self.oct_cvs._idle_hint = True
        with QMutexLocker(self._mutex):
            self._ch_state.clear(); self._ch_pending_extra.clear()
        self.vu_a.update_level(-100,-100,-100,-100)
        self.i_spl.setText('—'); self.i_pk.setText('—'); self.i_dom.setText('—')
        self.i_dba.setText('—'); self.i_dbc.setText('—')
        self.i_laeq.setText('—'); self.i_lceq.setText('—')
        self._laeq_buf.clear(); self._lceq_buf.clear()

    def _on_audio_error(self,msg):
        self._stop()
        self.status_lbl.setText('● Error')
        self.status_lbl.setStyleSheet(f'color:{T("red")};font-size:11px;')
        self.mic_st.setText('Device error')
        self.mic_st.setStyleSheet(f'color:{T("red")};font-size:10px;')
        from PyQt5.QtWidgets import QMessageBox
        _BrandBox.warning(self, _tx('Audio Error'),
            _tx('Microphone connection failed:\n{msg}\n\nGo to System Settings → Privacy → Microphone and grant access.').format(msg=msg))

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
                _log_audio_devices()   # 재초기화 후 PortAudio가 실제로 보는 장치 목록 (USB 재연결 진단의 핵심)
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

    def _on_coreaudio_devices_changed(self):
        """CoreAudio가 하드웨어 장치 변경을 알림(메인 스레드). 짧게 디바운스 후,
        오디오가 idle이면 중앙 재초기화로 전 탭 장치목록을 갱신한다. 측정 중이면
        기존 끊김 경로(_on_device_disconnected)가 처리하므로 건드리지 않는다."""
        t = getattr(self, '_ca_debounce', None)
        if t is None:
            t = QTimer(self); t.setSingleShot(True)
            t.timeout.connect(self._ca_apply_device_change)
            self._ca_debounce = t
        t.start(700)   # 다중 알림(여러 장치 동시 변경) 합치기

    def _ca_apply_device_change(self):
        if getattr(self, '_reiniting_audio', False):
            self._ca_debounce.start(700); return   # 재초기화 중이면 잠시 뒤 재시도
        # 장치 개수 변화 판정 — 감소=제거(끊김), 증가=추가(무관). 콜백 생존과 무관해 확실.
        prev = getattr(self, '_ca_dev_count', None)
        cur = self._ca_watcher.device_count()
        if cur is not None:
            self._ca_dev_count = cur
        removed = (prev is not None and cur is not None and cur < prev)
        if self._any_audio_active():
            # 오디오 활성이라도 '사용 중 입력 장치가 사라졌는지' 확인(백스톱).
            # ①장치 개수 감소(제거) — 일부 USB는 뽑혀도 콜백을 무음으로 계속 흘려 워치독/콜백age가
            #   못 잡음 → 개수 감소가 확실한 신호. ②콜백 사망(스트림 재오픈 실패=교착) 보조 신호.
            # 무관한 장치 추가(헤드폰 연결 등)는 둘 다 False → 보류 유지(측정 안 끊음, 오판 방지).
            if removed or self._input_stream_dead():
                _alog.info(f'CoreAudio 장치변경 — 사용 중 장치 제거 감지(removed={removed}) → 끊김 복구 강제')
                self.reinit_audio_devices('coreaudio device change (active, device removed)')
                self._begin_replug_watch()
            else:
                _alog.info('CoreAudio 장치변경 — 오디오 활성+장치 유지, 자동 재초기화 보류')
            return
        _alog.info('CoreAudio 장치변경 감지(idle) → 장치목록 갱신')
        self.reinit_audio_devices('coreaudio device change')

    def _input_stream_dead(self):
        """입력을 쓰는 탭(spectrum/TF측정/stereo)이 '활성'이라 주장하는데 실제 입력 스트림이
        죽었는지 판정. True = 사용 중 입력 장치가 사라진 것으로 보임(끊김 복구 필요).
        제너레이터 출력만 켠 경우(입력 미사용)는 오판 방지 위해 건드리지 않는다(False)."""
        tw = self.tf_win
        input_active = (self._spec_running()                    # MainWindow엔 _running 없음 → 스펙트럼만 측정 시 백스톱 죽던 버그
                        or (tw is not None and getattr(tw, '_running', False))
                        or (self.stereo_page is not None and getattr(self.stereo_page, '_running', False)))
        if not input_active:
            return False   # 입력 안 쓰는 활성(출력 전용 등) → 백스톱 대상 아님
        try:
            age = self.audio_engine.freshest_callback_age()
        except Exception:
            age = None
        # 살아있는 입력 스트림이 없거나(None) 모든 콜백이 1.5초+ 멈춤 → 장치 사라진 것으로 판정.
        return (age is None) or (age > 1.5)

    def _device_count(self):
        try: return len(sd.query_devices())
        except Exception: return 0

    def _any_audio_active(self):
        """어느 탭이든 오디오 스트림이 활성인지 — 폴링 재초기화가 사용 중인 측정을 끊지 않도록 게이트.
        ※ RTA 칸의 수동 모니터 구독은 '측정 활성'이 아니므로 active_devices 판정에서 제외한다.
          (RTA만 켠 채 USB를 뽑았다 꽂으면 RTA가 폴백 장치로 재구독돼 active_devices가 비지 않는데,
           이를 활성으로 보면 replug 폴링/리스너가 보류돼 장치가 영영 다시 안 보인다. 측정 중이면
           위의 _running/sig_gen 플래그로 이미 보호되므로 RTA 제외가 측정을 끊지 않는다.)"""
        if self._spec_running(): return True   # spectrum (MainWindow엔 _running 속성 없음)
        tw = self.tf_win
        if tw is not None and (getattr(tw, '_running', False) or
                               (getattr(tw, 'sig_on_btn', None) is not None and tw.sig_on_btn.isChecked())):
            return True
        sp = self.stereo_page
        if sp is not None and getattr(sp, '_running', False): return True
        try:
            rta = getattr(tw, '_rta_sub', None) if tw is not None else None
            rta_dev = rta.device_idx if rta is not None else None
            if any(d != rta_dev for d in self.audio_engine.active_devices()): return True
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
        # 가짜 disconnect 방지: HAL 장치 개수가 안 줄었으면(M4 여전히 존재) 스트림 churn(채널변경/
        # 재구성으로 콜백 1.5s+ 멈춤)에 의한 오판 → 무시. 실제 제거는 개수 감소로 통과하고, 콜백을
        # 무음으로 흘리는 USB는 CoreAudio 리스너(_ca_apply_device_change, 개수 기반)가 잡는다.
        try:
            _cur = self._ca_watcher.device_count(); _base = getattr(self, '_ca_dev_count', None)
            if _cur is not None and _base is not None and _cur >= _base:
                _alog.info(f'스트림 disconnect 신호 무시 — 장치 개수 유지({_cur}≥{_base}), 가짜 끊김(스트림 churn)')
                return
        except Exception: pass
        self._disconnected_dev_name=dev_name   # Refresh 시 이 장치만 접근성 검사
        self._stop()
        self.status_lbl.setText('● Disconnected')
        self.status_lbl.setStyleSheet(f'color:{T("yellow")};font-size:11px;')
        self.mic_st.setText('Disconnected')
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
        self._spec_chunk_n = getattr(self, '_spec_chunk_n', 0) + 1   # 스펙트럼 청크 수신 카운터(멈춤 진단)
        n=len(buf)
        db_raw=power_spectrum_db(buf)     # ★ raw dBFS — 단측 파워 스펙트럼(ENBW 보정)
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
                # 빠른 상승·느린 하강 단일 엔벌로프(파워도메인): 상승 빈=SPEC_ATTACK(빠름),
                # 하강 빈=(1-s) Response 설정 속도. 이동평균·이중평활 없이 한 단계 → 하강 자연스럽게.
                _w=np.where(pow_raw>self._pow_smooth, SPEC_ATTACK, 1.0-s)
                self._pow_smooth+=(pow_raw-self._pow_smooth)*_w
                np.log10(np.maximum(self._pow_smooth,1e-30),out=self._fft_smooth)
                self._fft_smooth*=10.0
            # ★ 캘리브 오프셋은 그래프용 avg에만 더함 (입력 신호 불변)
            avg_cal = self._fft_smooth + self.calib_offset

            # ★ SPL: raw dBFS로 VU 바 높이 계산, cal 값은 숫자 표시에만
            rms=float(np.sqrt(np.mean(buf**2)))
            raw_dbfs=20*math.log10(max(rms,1e-10))   # dBFS (캘리브 전)
            fs_peak=20*math.log10(max(float(np.max(np.abs(buf))),1e-10))  # 풀스케일 디지털 피크(dBFS)

            # SPL 스무딩 (raw 기준)
            # 레벨미터 탄도 = Speed와 독립(항상 실시간). 그래프 곡선 스무딩과 별개.
            va=METER_ATTACK if raw_dbfs>self._raw_spl_smooth else METER_RELEASE
            self._raw_spl_smooth+=(raw_dbfs-self._raw_spl_smooth)*va
            if raw_dbfs>self._raw_peak_smooth: self._raw_peak_smooth=raw_dbfs
            else: self._raw_peak_smooth-=0.25

            # dBA / dBC — 느린 평활 (time constant ~2초)
            dba_db=dbc_db=-100.0
            raw_dba=raw_dbc=-100.0   # 순간(평활 전) A/C 가중 레벨 — SPL Meter Fast/Slow 자체 EMA용
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
        if self.spl_meter_win and self._spl_source_id == 0 and dba_db>-100:
            # Smaart식 확장 지표 — 순간 calibrated Z/A/C + 풀스케일 디지털 피크 (소스=primary일 때만)
            self.spl_meter_win.push_levels(raw_dbfs+self.calib_offset, raw_dba, raw_dbc, fs_peak)
        if self.spl_alarm_win and dba_db>-100:
            # 독립 알람 창 — SPL 미터 유무·소스선택과 무관하게 primary 레벨로 급전
            self.spl_alarm_win.push_levels(raw_dbfs+self.calib_offset, raw_dba, raw_dbc, fs_peak)
        if self.show_mode_win and dba_db>-100:
            # FOH 쇼 모드 — 한계 라이브 동기화 + 헤드라인 지표는 SPL 알람 Metric 가중 따라감
            _a = self._settings.get('spl_alarm', {})
            self.show_mode_win.set_limit(_a.get('limit', 100.0), _a.get('amber', 3.0))
            _mtr = _a.get('metric', 'dba')
            if _mtr in ('lceq', 'dbc', 'dbc_fast', 'peak_c'):
                _sv, _su = raw_dbc, 'dBC'
            elif _mtr in ('spl', 'spl_fast', 'spl_slow', 'peak', 'fs_peak'):
                _sv, _su = raw_dbfs + self.calib_offset, 'dB SPL'
            else:                                   # laeq/dba/dba_fast 등 A가중
                _sv, _su = raw_dba, 'dBA'
            _sm_bands = self.oct_cvs.smooth.get(self.oct_cvs.mode)
            self.show_mode_win.push(_sv, _su, _sm_bands, self.db_min, self.db_max)

    # ── 렌더링 타이머 (30fps)
    def _render_frame(self):
        with QMutexLocker(self._mutex):
            data=self._pending; self._pending=None
            extra_data=dict(self._ch_pending_extra); self._ch_pending_extra.clear()
        # ── 진단 하트비트 (~10s) — 세션 로그에 동작 타임라인 남김(자기검증/사후분석) ──
        _hb = time.time()
        if _hb - getattr(self, '_diag_hb_t', 0.0) >= 10.0:
            self._diag_hb_t = _hb
            try:
                _spl = round(float(data[4]), 1) if data is not None else None
                _diag('hb', view=self.view_mode, run=self._spec_running(),
                      spl=_spl, extra=len(getattr(self, '_spec_extra', [])),
                      tf_cards=len(getattr(getattr(self, 'tf_win', None), '_extra_pairs', [])),
                      show=(getattr(self, 'show_mode_win', None) is not None),
                      chunks=getattr(self, '_spec_chunk_n', 0))
            except Exception:
                _alog.exception('[DIAG] heartbeat')
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
            # primary 카드 레벨 (raw dBFS) — 바=RMS, tick=true peak
            if self._primary_card is not None:
                self._primary_card.update_level(raw_spl, raw_peak)



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
        db_raw = power_spectrum_db(buf)     # 단측 파워 스펙트럼(ENBW 보정) — primary와 동일 정규화
        freqs = np.fft.rfftfreq(n, 1.0 / sr).astype(np.float32)   # 소스 장치 SR 기준
        s = self.smoothing
        pow_raw = 10 ** (db_raw / 10)
        rms = float(np.sqrt(np.mean(buf ** 2)))
        raw_dbfs = 20 * math.log10(max(rms, 1e-10))
        src_calib = self._spl_source_calib(card_id)   # 소스 자기 캘리브(device:ch) — primary calib 아님
        with QMutexLocker(self._mutex):
            state = self._ch_state.setdefault(card_id, {
                'pow_smooth': None, 'fft_smooth': None,
                'avg_buf': deque(maxlen=self.avg_count)
            })
            if state['pow_smooth'] is None or len(state['pow_smooth']) != len(pow_raw):
                state['pow_smooth'] = pow_raw.copy()
                state['fft_smooth'] = db_raw.copy()
            else:
                # primary(_process_audio)와 동일한 단일 비대칭 엔벌로프 — 응답 일치
                _w = np.where(pow_raw > state['pow_smooth'], SPEC_ATTACK, 1.0 - s)
                state['pow_smooth'] += (pow_raw - state['pow_smooth']) * _w
                np.log10(np.maximum(state['pow_smooth'], 1e-30), out=state['fft_smooth'])
                state['fft_smooth'] *= 10.0
            avg_cal = state['fft_smooth'] + src_calib
            self._ch_pending_extra[card_id] = (freqs, avg_cal, raw_dbfs, color)

        # 이 소스가 SPL 미터 측정 대상이면 Z/A/C/fs_peak 계산해 push (뮤텍스 밖)
        if self.spl_meter_win is not None and self._spl_source_id == card_id:
            src = next((s for s in self._spec_extra if s['id'] == card_id), None)
            if src is not None:
                cal = self._spl_source_calib(card_id)
                dbz, dba_i, dbc_i, fsp = self._spl_inputs(buf, sr, cal, src.setdefault('spl_cache', {}))
                if dba_i > -100:
                    self.spl_meter_win.push_levels(dbz, dba_i, dbc_i, fsp)

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
        primary_color = QColor(*bar_top()[:3]).name()   # 현재 그래프 색(사용자 Color 반영)
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
        pc.start_toggled.connect(self._card_toggle)
        pc.color_requested.connect(self._open_color_picker)
        pc.set_running(self._primary_running())
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
            sc.start_toggled.connect(self._card_toggle)
            sc.color_requested.connect(self._open_color_picker)
            sc.set_running(bool(src.get('sub')))
            src['card'] = sc
            # 첫 실행/재구성 시 저장된 가시성을 캔버스 채널에 동기화 (데이터 도착 전이라도)
            _vis = src.get('visible', True)
            self.fft_cvs.set_channel_visible(src['id'], _vis)
            self.oct_cvs.set_channel_visible(src['id'], _vis)
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
        # 새 카드는 정지 상태로 추가 — 카드별 Start(LED)로 사용자가 직접 켬(카드별 제어 일관).
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
        if self._spl_source_id == card_id:   # SPL 측정 소스 삭제 → primary 로 복귀
            self._set_spl_source(0)
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
        if src.get('sub'): self._open_spec_sub(src)   # 그 카드가 측정 중일 때만 재구독
        self._save_spec_sources()

    def _on_spec_ch_changed(self, card_id):
        src = next((s for s in self._spec_extra if s['id'] == card_id), None)
        if src is None or src.get('card') is None: return
        src['ch'] = src['card'].channel()
        self._clear_extra_curve(card_id)
        if src.get('sub'): self._open_spec_sub(src)   # 그 카드가 측정 중일 때만 재구독
        self._save_spec_sources()

    def _on_spec_visibility(self, card_id, visible):
        src = next((s for s in self._spec_extra if s['id'] == card_id), None)
        if src is not None: src['visible'] = visible
        # 데이터 도착 전에도 유지되는 가시성 맵에 기록(곡선 재생성돼도 숨김 유지)
        self.fft_cvs.set_channel_visible(card_id, visible)
        self.oct_cvs.set_channel_visible(card_id, visible)
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
             'num': s.get('num', 2), 'color': s.get('color', '')}
            for s in self._spec_extra]
        self._settings['spec_primary_name'] = getattr(self, '_spec_primary_name', '')
        _save_settings(self._settings)
        # 세션(마지막 사용값)에도 반영 — 안 하면 시작 시 세션 복원이 spec_sources를 덮어써
        # 삭제한 소스 카드가 되살아남(복원 중엔 _presets_restoring 가드로 무시됨).
        self._mark_session_dirty()

    def _restore_spec_sources(self):
        self._spec_primary_name = self._settings.get('spec_primary_name', '')
        saved = self._settings.get('spec_sources', [])
        if not saved: return
        self._restoring_spec = True
        try:
            for entry in saved:
                cid = self._spec_next_id; self._spec_next_id += 1
                num = entry.get('num') or self._spec_smallest_unused_num()
                color = entry.get('color') or _MC_COLORS[(num - 2) % len(_MC_COLORS)]
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
        _is_fft = (m == 'fft')
        self._scale_seg.setVisible(_is_fft)     # Log/Lin은 FFT에서만
        if hasattr(self, '_scale_sep'): self._scale_sep.setVisible(_is_fft)
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

    # ── Spectrum 상태 직렬화 (presets / auto-remember) ─────────────────
    def spec_get_state(self):
        try: scale = self._scale_seg.active() or 'log'
        except Exception: scale = 'log'
        return {
            'view': getattr(self, 'view_mode', 'oct12'),
            'scale': scale,
            'sr': self.sr_cb.currentIndex(),
            'peak': self.peak_btn.isChecked(), 'hold': self.hold_cb.currentIndex(),
            'db': self.db_cb.currentIndex(), 'speed': self.spd_cb.currentIndex(),
            'spectro': self.spectro_btn.isChecked(),
            'dev': self.dev_cb.currentText() if hasattr(self, 'dev_cb') else '',
            'ch': self.in_ch_cb.currentData() if hasattr(self, 'in_ch_cb') else 0,
            'sources': [{'dev_name': s.get('dev_name', ''), 'ch': s.get('ch', 0),
                         'visible': s.get('visible', True), 'name': s.get('name', ''),
                         'num': s.get('num', 2)}
                        for s in getattr(self, '_spec_extra', [])],
        }

    def spec_apply_state(self, d):
        try:
            if 'view' in d:
                self._set_view(
                    {'fft':'fft','oct3':'oct3','oct12':'oct12','oct24':'oct24'}.get(d['view'], 'oct12'))
        except Exception: pass
        try:
            if 'scale' in d: self._set_scale(d['scale'] == 'log')
        except Exception: pass
        for key, cb in (('sr', self.sr_cb), ('hold', self.hold_cb),
                        ('db', self.db_cb), ('speed', self.spd_cb)):
            try:
                if key in d:
                    if key == 'db':
                        # db_cb 복원이 _db_changed를 쏘면 방금 복원한 dB 수동고정 범위를
                        # 프리셋 span으로 덮어씀 → 복원 중엔 시그널 차단(표시 인덱스만 설정).
                        cb.blockSignals(True); cb.setCurrentIndex(int(d[key])); cb.blockSignals(False)
                    else:
                        cb.setCurrentIndex(int(d[key]))
            except Exception: pass
        try:
            if 'peak' in d and bool(d['peak']) != self.peak_btn.isChecked(): self.peak_btn.click()
        except Exception: pass
        try:
            if 'spectro' in d and bool(d['spectro']) != self.spectro_btn.isChecked(): self.spectro_btn.click()
        except Exception: pass
        try:
            if d.get('dev'):
                for i in range(self.dev_cb.count()):
                    if self.dev_cb.itemText(i) == d['dev']:
                        self.dev_cb.setCurrentIndex(i); break
                if 'ch' in d:
                    for i in range(self.in_ch_cb.count()):
                        if self.in_ch_cb.itemData(i) == d['ch']:
                            self.in_ch_cb.setCurrentIndex(i); break
        except Exception: pass
        try:
            if 'sources' in d and isinstance(d['sources'], list):
                self._apply_spec_sources(d['sources'])
        except Exception as e: _alog.warning(f'apply spec sources 실패: {e}')

    def _apply_spec_sources(self, entries):
        """프리셋/세션 적용: 스펙트럼 추가 소스 카드를 entries 에 맞춰 재구성."""
        if self._spl_source_id != 0:
            self._set_spl_source(0)          # SPL 소스가 추가카드면 primary 로 복귀
        self._restoring_spec = True
        try:
            for src in list(self._spec_extra):   # 기존 소스 정리
                self._close_spec_sub(src)
                self._clear_extra_curve(src['id'])
            self._spec_extra = []
            self._spec_front_id = 0
            self.fft_cvs._front_id = 0; self.oct_cvs._front_id = 0
            for entry in (entries or []):        # entries 만큼 재생성 (_restore_spec_sources 와 동일 형식)
                cid = self._spec_next_id; self._spec_next_id += 1
                num = entry.get('num') or self._spec_smallest_unused_num()
                color = entry.get('color') or _MC_COLORS[(num - 2) % len(_MC_COLORS)]
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
        if self._spec_running():
            for src in self._spec_extra: self._open_spec_sub(src)
        self._save_spec_sources()

    # ── 앱 전체 상태 직렬화 + 세션 자동기억 ───────────────────────────────
    def _loud_get_full(self):
        """Stereo 페이지 상태 + MainWindow 툴바의 target/L/R 콤보 인덱스."""
        st = self.stereo_page.loud_get_state()
        try: st['target'] = self._st_target_cb.currentIndex()
        except Exception: pass
        try: st['l'] = self._st_l_cb.currentIndex(); st['r'] = self._st_r_cb.currentIndex()
        except Exception: pass
        return st

    def _loud_apply_full(self, d):
        for key, cb in (('target', getattr(self, '_st_target_cb', None)),
                        ('l', getattr(self, '_st_l_cb', None)), ('r', getattr(self, '_st_r_cb', None))):
            try:
                if cb is not None and key in d: cb.setCurrentIndex(int(d[key]))
            except Exception: pass
        self.stereo_page.loud_apply_state(d)

    def _collect_app_state(self):
        return {'tf': self.tf_win.get_state(), 'spec': self.spec_get_state(), 'loud': self._loud_get_full()}

    def _apply_app_state(self, st):
        self._presets_restoring = True
        try:
            for key, fn in (('tf', lambda d: self.tf_win.apply_state(d)),
                            ('spec', self.spec_apply_state), ('loud', self._loud_apply_full)):
                try:
                    if isinstance(st.get(key), dict): fn(st[key])
                except Exception as e: _alog.warning(f'apply_app_state {key} 실패: {e}')
        finally:
            self._presets_restoring = False

    # ── Preset 핸들러 ──────────────────────────────────────────────────────────
    def _refresh_preset_cb(self):
        self._preset_cb.blockSignals(True)
        self._preset_cb.clear(); self._preset_cb.addItem('— Preset —')
        for name in sorted(self._settings.get('presets', {}).keys()):
            self._preset_cb.addItem(name)
        self._preset_cb.setCurrentIndex(0)
        self._preset_cb.blockSignals(False)

    def _on_preset_selected(self, idx):
        if idx <= 0: return
        name = self._preset_cb.currentText()
        st = self._settings.get('presets', {}).get(name)
        if isinstance(st, dict):
            self._apply_app_state(st)
            _diag('preset_load', name=name, tf_cards=len(getattr(self.tf_win, '_extra_pairs', [])),
                  spec_src=len(getattr(self, '_spec_extra', [])))

    def _on_preset_save(self):
        name, ok = _text_input_dialog(self, _tx('Save Preset'), _tx('Name:'))
        name = (name or '').strip()
        if not ok or not name: return
        presets = self._settings.setdefault('presets', {})
        if name in presets:
            if not _brand_msg(self, _tx('Overwrite'), _tx('Overwrite preset "{name}"?').format(name=name),
                              kind='question', ok_text=_tx('Overwrite'), cancel_text=_tx('Cancel')):
                return
        presets[name] = self._collect_app_state()
        _save_settings(self._settings); self._refresh_preset_cb()
        idx = self._preset_cb.findText(name)
        if idx > 0:
            self._preset_cb.blockSignals(True)
            self._preset_cb.setCurrentIndex(idx)
            self._preset_cb.blockSignals(False)
        _diag('preset_save', name=name, tf_cards=len(getattr(self.tf_win, '_extra_pairs', [])),
              spec_src=len(getattr(self, '_spec_extra', [])))

    def _on_preset_delete(self):
        name = self._preset_cb.currentText()
        presets = self._settings.get('presets', {})
        if self._preset_cb.currentIndex() <= 0 or name not in presets: return
        if not _brand_msg(self, _tx('Delete'), _tx('Delete preset "{name}"?').format(name=name),
                          kind='question', ok_text=_tx('Delete'), cancel_text=_tx('Cancel'), danger=True):
            return
        presets.pop(name, None); _save_settings(self._settings); self._refresh_preset_cb()
        _diag('preset_delete', name=name)

    def _mark_session_dirty(self, *a):
        if self._presets_restoring: return
        self._session_timer.start(800)   # 0.8s 디바운스

    def _save_session(self):
        try:
            self._settings['session'] = self._collect_app_state()
            _save_settings(self._settings)
            _diag('session_saved')
        except Exception as e:
            _alog.warning(f'_save_session 실패: {e}')

    def _toggle_peak(self):
        self.peak_hold=self.peak_btn.isChecked()
        self.peak_btn.setText('ON' if self.peak_hold else 'OFF')
        self.fft_cvs.set_peak_hold(self.peak_hold)
        self.oct_cvs.set_peak_hold(self.peak_hold)

    def _reset_peak(self):
        self.fft_cvs.reset_peak(); self.oct_cvs.reset_peak()

    def _flash_toast(self, text='✓ Captured', ms=1100):
        """화면 상단 중앙에 잠깐 뜨는 안내(토스트) — 캡쳐 등 즉각 피드백."""
        from PyQt5.QtCore import QTimer
        lbl = getattr(self, '_toast_lbl', None)
        if lbl is None:
            lbl = self._toast_lbl = QLabel(self)
            lbl.setAlignment(Qt.AlignCenter)
            self._toast_timer = QTimer(self); self._toast_timer.setSingleShot(True)
            self._toast_timer.timeout.connect(lbl.hide)
        a = QColor(T('accent')); ar, ag, ab = a.red(), a.green(), a.blue()
        lbl.setStyleSheet(f'background:rgba({ar},{ag},{ab},235);color:#FFFFFF;font-size:13px;'
                          f'font-weight:700;padding:8px 20px;border-radius:9px;')
        lbl.setText(text); lbl.adjustSize()
        lbl.move(max(0, (self.width() - lbl.width()) // 2), 165)
        lbl.show(); lbl.raise_()
        self._toast_timer.start(ms)

    def _space_capture(self):
        idx = self.main_stack.currentIndex()
        if idx == 2:
            return  # Stereo Loudness 탭에서는 스페이스바 무시
        if idx == 1:
            if self.tf_win._do_tf_capture(prompt=True):  # 스페이스바 = 이름 입력 후 캡쳐 (스펙트럼과 동일)
                self._flash_toast()
        else:
            self._do_spec_capture()

    def _do_spec_capture(self):
        n = len(self.fft_cvs._captures) + len(self.oct_cvs._captures)
        default = f'Capture {n + 1}'
        label, ok = _text_input_dialog(self, _tx('Capture'), _tx('Name:'), default)
        if not ok: return
        label = label.strip() or default
        color = _auto_capture_color(n)
        group = self._current_spec_group
        m = self.view_mode
        # primary — 표시 중일 때만 (TF 캡쳐와 동일 정책)
        added = 0
        if self.fft_cvs._primary_visible:
            if m == 'fft':
                self.fft_cvs.add_capture(label, color, group)
            else:
                self.oct_cvs.add_capture(label, color, group)
            added += 1
        # 표시 중인 추가 소스 카드 각각 — TF 멀티카드 캡쳐와 동일하게 소스별로 1개씩
        for src in self._spec_extra:
            cid = src['id']
            if not src.get('visible', True): continue
            card_no = src.get('num', 2)
            ex_label = f'{label} · Card{card_no}'
            ex_color = src.get('color') or _auto_capture_color(n + added)
            if m == 'fft':
                ch = self.fft_cvs._ch_curves.get(cid)
                if ch and ch.get('ds_f') is not None:
                    self.fft_cvs.add_capture_data(ex_label, ex_color, ch['ds_f'], ch['ds_avg'], group)
                    added += 1
            else:
                ch = self.oct_cvs._ch_oct.get(cid)
                if ch and ch.get('values') is not None:
                    self.oct_cvs.add_capture_data(ex_label, ex_color, ch['values'], self.view_mode, group)
                    added += 1
        if added == 0: return
        _alog.info(f'스펙트럼 캡처 추가  label="{label}"  mode={m}  +{added}  total={n+added}')
        _diag('spec_capture', mode=m, added=added)
        self._refresh_spec_capture_bar()
        self._save_spec_captures()
        self._flash_toast()

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

    def _on_drawer_visibility_all(self, mode, visible):
        """현재 탭 전체 캡쳐 일괄 표시/숨김."""
        self._apply_caps_visibility(mode, visible, group=None)

    def _on_drawer_group_visibility(self, mode, gname, visible):
        """한 그룹의 캡쳐만 일괄 표시/숨김."""
        self._apply_caps_visibility(mode, visible, group=gname)

    def _apply_caps_visibility(self, mode, visible, group=None):
        """일괄 가시성 적용 — group=None 이면 전체, 아니면 해당 그룹만.
        개별 토글(_on_drawer_visibility)과 동일하게 캔버스별 _captures 동기화 + 재페인트."""
        def _match(c):
            return group is None or c.get('group', '') == group
        if mode == 'spec':
            for cvs in (self.fft_cvs, self.oct_cvs):
                changed = False
                for c in cvs._captures:
                    if _match(c):
                        c['visible'] = visible; changed = True
                if changed:
                    cvs._cap_pix = None; cvs.update()
        elif mode == 'tf' and hasattr(self, 'tf_win') and self.tf_win is not None:
            tf = self.tf_win
            idxs = [i for i, c in enumerate(tf._tf_captures) if _match(c)]
            for i in idxs:
                tf._tf_captures[i]['visible'] = visible
            for cvs in (tf.mag_cvs, tf.phase_cvs, tf.ir_cvs):
                for i in idxs:
                    if 0 <= i < len(cvs._captures):
                        cvs._captures[i]['visible'] = visible
                cvs._cap_pix = None; cvs.update()
        self._refresh_capture_drawer()

    def _on_drawer_average(self, mode):
        if mode == 'tf' and hasattr(self, 'tf_win') and self.tf_win is not None:
            self.tf_win._do_tf_average()

    def _on_drawer_recapture(self, mode, idx):
        """기존 캡쳐 idx 를 현재 라이브로 제자리 덮어쓰기 (색/이름/그룹 유지)."""
        if mode == 'spec':
            fft_n = len(self.fft_cvs._captures)
            if idx < fft_n:
                ok = self.fft_cvs.recapture(idx)
            else:
                ok = self.oct_cvs.recapture(idx - fft_n)
            if ok:
                self._refresh_capture_drawer()
                self._save_spec_captures()
                self._flash_toast()
        elif mode == 'tf' and hasattr(self, 'tf_win') and self.tf_win is not None:
            if self.tf_win._recapture_tf(idx):
                self._refresh_capture_drawer()
                self._flash_toast()

    def _recapture_selected(self):
        """R 단축키 — 현재 탭에서 선택(없으면 마지막) 캡쳐를 제자리 다시 캡쳐."""
        mode = self._capture_drawer._panel_tab
        caps = self._capture_drawer._spec_caps if mode == 'spec' else self._capture_drawer._tf_caps
        if not caps: return
        idx = self._capture_drawer._sel.get(mode)
        if idx is None or not (0 <= idx < len(caps)):
            idx = len(caps) - 1
        self._on_drawer_recapture(mode, idx)

    def _on_drawer_reference(self, mode, idx):
        if mode == 'tf' and hasattr(self, 'tf_win') and self.tf_win is not None:
            self.tf_win._on_set_reference(idx)

    def _on_drawer_export(self, mode):
        if mode == 'tf' and hasattr(self, 'tf_win') and self.tf_win is not None:
            self.tf_win._export_tf_captures()

    def _on_drawer_import(self, mode):
        if mode == 'tf' and hasattr(self, 'tf_win') and self.tf_win is not None:
            if self.tf_win._import_tf_captures():
                self._refresh_capture_drawer()

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

    def _on_capture_target_changed(self, mode, gname):
        """캡쳐 패널에서 새 캡쳐가 들어갈 타겟 그룹 변경 ('' = 미지정)."""
        if mode == 'spec':
            self._current_spec_group = gname
        elif hasattr(self, 'tf_win') and self.tf_win is not None:
            self.tf_win._current_tf_group = gname
        self._capture_drawer.set_capture_target(mode, gname)
        self._refresh_capture_drawer()

    def _on_drawer_delete_all(self, mode):
        """우클릭 Delete All — 현재 탭(Spectrum/TF)의 모든 캡쳐 삭제 (확인 후)."""
        from PyQt5.QtWidgets import QMessageBox
        if mode == 'spec':
            n = len(self.fft_cvs._captures) + len(self.oct_cvs._captures)
        elif hasattr(self, 'tf_win') and self.tf_win is not None:
            n = len(self.tf_win._tf_captures)
        else:
            return
        if n == 0:
            return
        if not _brand_msg(self, 'Delete All', _tx('Delete all {n} captures?').format(n=n),
                          kind='warn', ok_text=_tx('Delete'), cancel_text=_tx('Cancel'), danger=True):
            return
        if mode == 'spec':
            for cvs in (self.fft_cvs, self.oct_cvs):
                cvs._captures.clear(); cvs._front_idx = None; cvs._cap_pix = None; cvs.update()
            self._refresh_spec_capture_bar(); self._save_spec_captures()
            _alog.info('스펙트럼 캡처 전체 삭제')
        else:
            tf = self.tf_win
            tf._tf_captures.clear()
            for cvs in (tf.mag_cvs, tf.phase_cvs, tf.ir_cvs):
                cvs._captures.clear(); cvs._front_idx = None; cvs._cap_pix = None; cvs.update()
            try: tf._on_set_reference(-1)   # Δ 비교 기준 해제
            except Exception: pass
            tf._refresh_tf_capture_bar(); tf._save_tf_captures()
            _alog.info('TF 캡처 전체 삭제')

    def _on_drawer_new_group(self, mode):
        name, ok = _text_input_dialog(self, _tx('New Group'), _tx('Group name:'))
        if not ok or not name.strip(): return
        name = name.strip()
        # 새 그룹을 만들면 그 그룹을 캡쳐 타겟으로 지정 (활성 표시)
        self._on_capture_target_changed(mode, name)

    def _on_drawer_delete_group(self, mode, gname):
        if mode == 'spec':
            self.fft_cvs._captures = [c for c in self.fft_cvs._captures if c.get('group','') != gname]
            self.oct_cvs._captures = [c for c in self.oct_cvs._captures if c.get('group','') != gname]
            self.fft_cvs._cap_pix = None; self.fft_cvs.update()
            self.oct_cvs._cap_pix = None; self.oct_cvs.update()
            if getattr(self, '_current_spec_group', '') == gname:
                self._current_spec_group = ''
            self._capture_drawer.set_capture_target('spec', self._current_spec_group)
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
            self._capture_drawer.set_capture_target('tf', getattr(tf, '_current_tf_group', ''))
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
        # SPL 미터는 선택된 소스 기준 calib — 소스가 primary일 때만 primary calib 반영
        if hasattr(self, 'spl_meter_win') and self.spl_meter_win and getattr(self, '_spl_source_id', 0) == 0:
            self.spl_meter_win.set_calib_offset(offset)
        if getattr(self, 'spl_alarm_win', None):
            self.spl_alarm_win.set_calib_offset(offset)   # 독립 알람은 항상 primary calib
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

    def _open_color_picker(self, card_id=None):
        # 카드 색을 바꾼다 — primary는 그래프 그라디언트+카드, 추가 카드는 그 소스 곡선+카드.
        # card_id 지정(우클릭 메뉴)이면 그 카드, 아니면 선택(front) 카드(툴바 Color).
        fid = card_id if card_id is not None else getattr(self, '_spec_front_id', 0)
        if fid == 0:
            _cc = bar_custom_color()
            init = QColor(*_cc) if _cc else QColor(*bar_top()[:3])
            color = QColorDialog.getColor(init, self, 'Select color — Source 1')
            if not color.isValid(): return
            set_bar_custom_color((color.red(), color.green(), color.blue()))
            self.fft_cvs._cache = None; self.oct_cvs._cache = None
            self.fft_cvs.update(); self.oct_cvs.update()
            if self._primary_card is not None:
                self._primary_card.set_color(color.name())
        else:
            src = next((s for s in self._spec_extra if s['id'] == fid), None)
            if src is None: return
            init = QColor(src.get('color', '#00D4FF'))
            color = QColorDialog.getColor(init, self, 'Select color — this source')
            if not color.isValid(): return
            src['color'] = color.name()
            if src.get('card'): src['card'].set_color(color.name())
            self._clear_extra_curve(fid)   # 새 색으로 다시 그려짐
            self.fft_cvs.set_channel_visible(fid, src.get('visible', True))
            self.oct_cvs.set_channel_visible(fid, src.get('visible', True))
            self._save_spec_sources()

    def _build_menubar(self):
        """macOS 네이티브 메뉴바. About/Quit은 role로 macOS '앱 메뉴'에 자동 배치되고
        Help 메뉴에 설명서·로그. (Windows에선 Help 메뉴에 모두 표시 — 창 상단 메뉴)."""
        from PyQt5.QtWidgets import QAction
        mb = self.menuBar()
        view_menu = mb.addMenu('View')
        spl_act = QAction('SPL Meter', self)
        spl_act.triggered.connect(self._open_spl_meter); view_menu.addAction(spl_act)
        alarm_act = QAction('SPL Alarm', self)
        alarm_act.triggered.connect(self._open_spl_alarm); view_menu.addAction(alarm_act)
        # [v1.7 보류] FOH 글랜스 쇼 모드 — 코드(ShowModeWindow/_open_show_mode/_process_audio 급전)는
        # 보존하되 진입점(메뉴+단축키)만 숨김. v1.7에서 재개 시 아래 3줄 복구하면 즉시 활성화.
        #   show_act = QAction('Show Mode (Full Screen)', self)
        #   show_act.setShortcut('Ctrl+Shift+F')   # macOS에선 Cmd+Shift+F
        #   show_act.triggered.connect(self._open_show_mode); view_menu.addAction(show_act)
        view_menu.addSeparator()
        spec_pop_act = QAction('Spectrum in Separate Window', self)
        spec_pop_act.setShortcut('Ctrl+Shift+S')   # macOS에선 Cmd+Shift+S로 매핑
        spec_pop_act.triggered.connect(self._toggle_spec_popout); view_menu.addAction(spec_pop_act)
        tf_pop_act = QAction('Transfer Function in Separate Window', self)
        tf_pop_act.setShortcut('Ctrl+Shift+T')   # macOS에선 Cmd+Shift+T로 매핑
        tf_pop_act.triggered.connect(self._toggle_tf_popout); view_menu.addAction(tf_pop_act)
        st_pop_act = QAction('Stereo Loudness in Separate Window', self)
        st_pop_act.setShortcut('Ctrl+Shift+L')   # macOS에선 Cmd+Shift+L로 매핑
        st_pop_act.triggered.connect(self._toggle_st_popout); view_menu.addAction(st_pop_act)
        # (Split View(2칸 분할) 메뉴 제거 — 사용자가 안 씀. _toggle_split 구현은 휴면 상태로 남김.)
        help_menu = mb.addMenu('Help')
        about_act = QAction('About SPECTRA', self); about_act.setMenuRole(QAction.AboutRole)
        about_act.triggered.connect(self._show_license_info); help_menu.addAction(about_act)
        man_act = QAction('Manual', self); man_act.setShortcut('Ctrl+?')
        man_act.triggered.connect(self._open_manual); help_menu.addAction(man_act)
        sc_act = QAction('Keyboard Shortcuts', self); sc_act.setShortcut('?')
        sc_act.triggered.connect(self._show_shortcuts); help_menu.addAction(sc_act)
        rn_act = QAction('Release Notes', self)
        rn_act.triggered.connect(self._show_release_notes); help_menu.addAction(rn_act)
        log_act = QAction('Open Log Folder', self)
        log_act.triggered.connect(lambda: (os.startfile(_LOG_DIR) if _pl.system() == 'Windows'
                                           else _sp.Popen(['open', _LOG_DIR])))
        help_menu.addAction(log_act)
        quit_act = QAction('Quit SPECTRA', self); quit_act.setMenuRole(QAction.QuitRole)
        quit_act.setShortcut('Ctrl+Q'); quit_act.triggered.connect(self.close)
        help_menu.addAction(quit_act)

    def _show_shortcuts(self):
        ShortcutsDialog(self).exec()

    def _open_manual(self):
        """우측 하단 Help 버튼 — 사용 설명서(MANUAL.html)를 기본 브라우저로 연다.
        번들(.app/.exe)에선 _MEIPASS, 소스 실행 시엔 스크립트 폴더에서 찾는다."""
        from PyQt5.QtGui import QDesktopServices
        from PyQt5.QtCore import QUrl
        base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(base, 'MANUAL.html')
        if os.path.exists(path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        else:
            _BrandBox.information(self, 'SPECTRA', _tx('User manual (MANUAL.html) not found.'))

    def _show_release_notes(self):
        """릴리즈 노트 — RELEASE_NOTES.md를 브랜드 창에 렌더해 표시."""
        from PyQt5.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QTextBrowser, QFrame, QPushButton
        base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(base, 'RELEASE_NOTES.md')
        try:
            md = open(path, encoding='utf-8').read()
        except Exception:
            md = '# Release Notes\n\nRELEASE_NOTES.md 파일을 찾을 수 없습니다.'
        dlg = QDialog(self); dlg.setWindowTitle('Release Notes'); _apply_dark_titlebar(dlg, resizable=True)
        dlg.resize(560, 660)
        dlg.setStyleSheet(f'background:{T("bg2")};color:{T("text")};')
        lay = QVBoxLayout(dlg); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(0)
        lay.addWidget(_grad_topline())
        tb = QTextBrowser(); tb.setOpenExternalLinks(True)
        tb.setStyleSheet(
            f'QTextBrowser{{background:{T("bg")};color:{T("text")};border:none;padding:16px;font-size:13px;}}'
            f'QScrollBar:vertical{{width:6px;background:transparent;}}'
            f'QScrollBar::handle:vertical{{background:{T("border")};border-radius:3px;}}')
        tb.setHtml(_md_to_html(md))
        lay.addWidget(tb, 1)
        btn_row = QHBoxLayout(); btn_row.setContentsMargins(12, 8, 12, 12); btn_row.addStretch()
        close = QPushButton('Close'); close.setStyleSheet(ss_btn_primary())
        close.clicked.connect(dlg.accept); btn_row.addWidget(close)
        lay.addLayout(btn_row)
        dlg.exec_()

    def _show_license_info(self):
        from PyQt5.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame
        mid = _get_machine_id()
        key = load_license() or '(none)'
        valid, _r = verify_license(key) if key != '(none)' else (False, '')
        status = 'Activated' if valid else 'Not activated'
        status_col = T('green') if valid else T('text_dim')

        dlg = QDialog(self); dlg.setWindowTitle('About SPECTRA')
        _apply_dark_titlebar(dlg)
        dlg.setStyleSheet(f'QDialog{{background:{T("bg2")};}}')
        root = QVBoxLayout(dlg); root.setContentsMargins(30, 24, 30, 22); root.setSpacing(0)

        # ── 브랜드 헤더: 마크 + 워드마크 ──
        hdr = QHBoxLayout(); hdr.setSpacing(13)
        mark = QLabel(); mark.setPixmap(_spectra_mark(42)); mark.setStyleSheet('background:transparent;')
        hdr.addWidget(mark)
        wm = QVBoxLayout(); wm.setSpacing(1)
        name = QLabel('SPECTRA')
        name.setStyleSheet(f'font-size:24px;font-weight:700;letter-spacing:5px;color:{T("text")};background:transparent;')
        sub = QLabel('Spectrum Analyzer')
        sub.setStyleSheet(f'font-size:11px;color:{T("text_dim")};letter-spacing:1px;background:transparent;')
        wm.addWidget(name); wm.addWidget(sub)
        hdr.addLayout(wm); hdr.addStretch()
        root.addLayout(hdr)
        root.addSpacing(6)
        sep = QFrame(); sep.setFixedHeight(3); sep.setObjectName('aboutSep')
        sep.setStyleSheet(f'#aboutSep{{background:{_SPECTRA_GRAD_QSS};border:none;border-radius:1px;}}')
        root.addWidget(sep)
        root.addSpacing(13)
        ver = QLabel(f'Version {_APP_VERSION}    ·    by WAYAUDIO')
        ver.setStyleSheet(f'font-size:12px;font-weight:600;color:{T("text_dim")};background:transparent;')
        root.addWidget(ver)
        root.addSpacing(16)

        def _row(label, value, vcol=None):
            r = QHBoxLayout(); r.setSpacing(8)
            l = QLabel(label); l.setFixedWidth(92)
            l.setStyleSheet(f'font-size:11px;color:{T("text_dim")};background:transparent;')
            v = QLabel(value); v.setStyleSheet(f'font-size:11px;color:{vcol or T("text")};background:transparent;')
            v.setTextInteractionFlags(Qt.TextSelectableByMouse); v.setWordWrap(True)
            r.addWidget(l, 0, Qt.AlignTop); r.addWidget(v, 1)
            root.addLayout(r); root.addSpacing(7)
        _row('License', status, status_col)
        _row('Machine ID', mid)
        _row('Serial', f'{key[:24]}…' if key != '(none)' else '(none)')
        _row('Log', _LOG_DIR)

        root.addSpacing(12)
        btns = QHBoxLayout(); btns.addStretch()
        copy_btn = QPushButton('Copy Machine ID'); copy_btn.setStyleSheet(ss_btn_neutral())
        copy_btn.clicked.connect(lambda: QApplication.clipboard().setText(mid))
        close_btn = QPushButton('Close'); close_btn.setStyleSheet(ss_btn_primary())
        close_btn.clicked.connect(dlg.accept)
        btns.addWidget(copy_btn); btns.addWidget(close_btn)
        root.addLayout(btns)

        dlg.setFixedWidth(430)
        dlg.exec_()

    def closeEvent(self,e):
        self._render_t.stop()
        self.stereo_page.stop()
        self._stop()
        # 부모 없는 독립 창(SPL 미터 + 라우드니스/벡터스코프 + TF 팝아웃) → 메인 종료 시 직접 닫아 고아 방지
        for _wn in (getattr(self, 'spl_meter_win', None),
                    getattr(self, 'spl_alarm_win', None),
                    getattr(self, 'show_mode_win', None),
                    getattr(self, '_tf_popout', None),
                    getattr(self, '_spec_popout', None),
                    getattr(self, '_st_popout', None),
                    getattr(self.stereo_page, '_vs_win', None),
                    getattr(self.stereo_page, '_radar_win', None)):
            if _wn is not None:
                try: _wn.close()
                except Exception: pass
        # 보류된 TF 캡쳐 저장 flush — 종료 시 동기 저장(앱 종료 중이라 글리치 무관)
        try:
            tw = self.tf_win
            if tw is not None:
                tw._flush_tf_captures(sync=True)
        except Exception as ex:
            _alog.warning(f'close flush 실패: {ex}')
        e.accept()


# ═══════════════════════════════════════════════════════════════════
#  원격 지원용 진단 로깅 — 사용자가 보낸 로그만으로 환경/오디오를 파악
#  (개인정보·라이선스 키는 절대 기록하지 않음. 머신ID는 라이선스 대조용)
# ═══════════════════════════════════════════════════════════════════
def _log_startup_diagnostics(app=None):
    """앱 시작 시 사용자 환경(빌드형태·RAM·오디오 라이브러리·화면·라이선스 상태)을 로그에 남김."""
    try:
        _form = '번들앱(설치본)' if getattr(sys, 'frozen', False) else '소스실행'
        _alog.info(f'실행형태: {_form}   머신ID: {_get_machine_id()}')
    except Exception as e:
        _alog.warning(f'[diag] 머신ID 실패: {e}')
    try:
        _sys = _pl.system()
        if _sys == 'Darwin':
            _ram = int(_sp.check_output(['sysctl', '-n', 'hw.memsize'], text=True).strip())
            _alog.info(f'RAM: {_ram / 1024**3:.1f} GB')
        elif _sys == 'Windows':
            class _MEMSTAT(_ctypes.Structure):
                _fields_ = [('dwLength', _ctypes.c_ulong), ('dwMemoryLoad', _ctypes.c_ulong),
                            ('ullTotalPhys', _ctypes.c_ulonglong), ('ullAvailPhys', _ctypes.c_ulonglong),
                            ('ullTotalPageFile', _ctypes.c_ulonglong), ('ullAvailPageFile', _ctypes.c_ulonglong),
                            ('ullTotalVirtual', _ctypes.c_ulonglong), ('ullAvailVirtual', _ctypes.c_ulonglong),
                            ('ullAvailExtendedVirtual', _ctypes.c_ulonglong)]
            _ms = _MEMSTAT(); _ms.dwLength = _ctypes.sizeof(_MEMSTAT)
            _ctypes.windll.kernel32.GlobalMemoryStatusEx(_ctypes.byref(_ms))
            _alog.info(f'RAM: {_ms.ullTotalPhys / 1024**3:.1f} GB')
    except Exception as e:
        _alog.warning(f'[diag] RAM 실패: {e}')
    try:
        _pa = sd.get_portaudio_version()
        _pa_s = _pa[1] if isinstance(_pa, (tuple, list)) and len(_pa) > 1 else _pa
        _alog.info(f'오디오: sounddevice {getattr(sd, "__version__", "?")}  |  {_pa_s}')
    except Exception as e:
        _alog.warning(f'[diag] 오디오 라이브러리 버전 실패: {e}')
    try:
        if app is not None:
            for _i, _scr in enumerate(app.screens()):
                _g = _scr.geometry()
                _alog.info(f'화면{_i}: {_g.width()}x{_g.height()} @{_scr.devicePixelRatio():.1f}x  ({_scr.name()})')
    except Exception as e:
        _alog.warning(f'[diag] 화면 정보 실패: {e}')
    try:
        _alog.info(f'라이선스 상태: {"유효" if check_license_at_startup() else "없음/무효"}')  # 키 자체는 기록 안 함
    except Exception as e:
        _alog.warning(f'[diag] 라이선스 상태 실패: {e}')

def _log_audio_devices():
    """오디오 장치 전체 목록 — 오디오 문제(장치 안 잡힘/채널/샘플레이트) 진단의 핵심."""
    try:
        _alog.info('───── 오디오 장치 목록 ─────')
        try:    _has = sd.query_hostapis()
        except Exception: _has = []
        try:    _din, _dout = sd.default.device
        except Exception: _din = _dout = -1
        for _i, _d in enumerate(sd.query_devices()):
            _ha = _has[_d['hostapi']]['name'] if 0 <= _d['hostapi'] < len(_has) else '?'
            _tags = []
            if _i == _din:  _tags.append('기본입력')
            if _i == _dout: _tags.append('기본출력')
            _t = ('  *' + ','.join(_tags)) if _tags else ''
            _alog.info(f"  [{_i:2d}] in={_d['max_input_channels']} out={_d['max_output_channels']} "
                       f"sr={int(_d['default_samplerate'])} ({_ha})  {_d['name']}{_t}")
        _alog.info('────────────────────────────')
    except Exception as e:
        _alog.warning(f'[diag] 오디오 장치 목록 실패: {e}')


if __name__=='__main__':
    from PyQt5.QtGui import QPixmap

    # ── macOS Monterey+ Retina / High-DPI 지원
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps,   True)

    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    app.setApplicationName('SPECTRA')
    app.setApplicationDisplayName('SPECTRA')   # macOS 앱메뉴(About/Hide/Quit)·작업표시줄 표기
    app.setOrganizationName('WAYAUDIO')
    # 앱 전체 글꼴 — 가족만 교체(크기는 위젯별 stylesheet/기본 유지) → 레이아웃 영향 최소
    _appf = app.font(); _appf.setFamily(FONT_FAMILY); app.setFont(_appf)

    # ── 세션 시작 로그 헤더
    _alog.info('=' * 60)
    _alog.info(f'SPECTRA v{_APP_VERSION}  시작  {_dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    _alog.info(f'OS: {_pl.platform()}')
    _alog.info(f'Machine: {_pl.machine()}  Processor: {_pl.processor()}')
    _alog.info(f'Python: {_pl.python_version()}')
    _alog.info(f'Log: {_LOG_PATH}')
    _log_startup_diagnostics(app)   # 실행형태·머신ID·RAM·오디오라이브러리·화면·라이선스
    _log_audio_devices()            # 오디오 장치 전체 목록 (지원 디버깅 핵심)
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
    # 렌더형 브랜드 스플래시 우선 — 버전(_APP_VERSION) 자동 반영(정적 png는 버전이 굳어 안 따라옴).
    # 렌더 실패 시에만 splash.png 폴백.
    try:
        splash = QSplashScreen(_make_splash_pixmap(), Qt.WindowStaysOnTopHint)
        splash.show()
        app.processEvents()
    except Exception:
        splash = None
        splash_img = _res('splash.png')
        if os.path.exists(splash_img):
            pix = QPixmap(splash_img)
            dpr = app.devicePixelRatio()
            if dpr > 1.0:
                pix = pix.scaled(int(pix.width() * dpr), int(pix.height() * dpr),
                                 Qt.KeepAspectRatio, Qt.SmoothTransformation)
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

    rc = app.exec()
    # ── 종료 처리
    # PyQt5/sip는 파이썬 인터프리터 종료(Py_FinalizeEx) 단계에서 남은 Qt 객체를
    # 임의 순서로 파괴하다가 이미 해제된 타입을 참조해 SIGSEGV("예기치 않게 종료됨")를
    # 일으키는 알려진 버그가 있다. 오디오 스트림 정리는 aboutToQuit(=_emergency_cleanup)에서
    # 이미 끝났으므로, 로그만 flush한 뒤 파이썬 finalization을 건너뛰고 즉시 종료한다.
    try:
        _emergency_cleanup()
        logging.shutdown()
        sys.stdout.flush(); sys.stderr.flush()
    except Exception:
        pass
    os._exit(rc)
