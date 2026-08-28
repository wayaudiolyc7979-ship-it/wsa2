"""메인 윈도우(앱 루트) — Spectrum 탭 본체 + 3탭 컨테이너 + 팝아웃/분할 + 진입 초기화.

v2.0 분해: wayaudo2.py에서 이동. MainWindow가 앱 셸. 버전 문자열은 wayaudo2가
모듈 전역 APP_VERSION 에 주입(_APP_VERSION은 bump_version.sh 대상이라 wayaudo 유지).
"""
import sys, os, math, time, threading, ctypes
import datetime as _dt
import subprocess as _sp, platform as _pl
from collections import deque
import numpy as np
import sounddevice as sd
from PyQt5.QtGui import QColor, QCursor, QDesktopServices, QFont, QKeySequence
from PyQt5.QtCore import (Qt, QEvent, QMutex, QMutexLocker, QObject, QPoint, QRect,
                          QTimer, QUrl)
from PyQt5.QtWidgets import (QAction, QApplication, QColorDialog, QComboBox, QDialog, QFrame,
                             QMainWindow,
                             QGroupBox, QHBoxLayout, QLabel, QPushButton, QScrollArea, QShortcut,
                             QSizePolicy, QSplitter, QStackedWidget, QTextBrowser, QVBoxLayout,
                             QWidget)
from spectra.audio.engine import (AudioEngine, _CoreAudioDeviceWatcher, _dev_hostapi_ok,
                                  _win_preferred_hostapi)
from spectra.core.config import (MAX_DB, SPEC_ATTACK, SPEED_LEVELS, T, _CAPTURES_LOCK,
                                 _load_captures_file, _load_settings, _save_captures_file,
                                 _save_settings, is_dark, toggle_theme)
from spectra.core.i18n import _tx, cur_lang
from spectra.core.license import _get_machine_id, load_license, verify_license
from spectra.core.logging_diag import _LOG_DIR, _alog, _diag
from spectra.dsp.weighting import BANDS, a_weight_db, c_weight_db, power_spectrum_db
from spectra.ui.canvas_spectrum import FFTCanvas, OctaveCanvas, SpectrogramCanvas
from spectra.ui.canvas_tf import _ask_db_range, _db_axis_context_menu
from spectra.ui.capture_drawer import _CaptureDrawer
from spectra.ui.colors import (_MC_COLORS, _SPECTRA_GRAD_QSS, _spectra_mark, bar_custom_color,
                               bar_top, set_bar_custom_color)
from spectra.ui.dialogs import CalibDialog, ShortcutsDialog, _BrandBox, _brand_msg
from spectra.ui.draw import METER_ATTACK, METER_RELEASE
from spectra.ui.icons import _icon, _icon_pm, _n2_divider, _n2_icon_color
from spectra.ui.spl import (LeqWindow, ShowModeWindow, SplAlarmWindow, SplMeterWindow,
                            _apply_on_top, _apply_txn, _txn_style)
from spectra.ui.stereo_page import StereoLoudnessPage, _StereoPopoutWindow
from spectra.ui.tf_window import (TransferFunctionWindow, _auto_capture_color, _db_ctrl_btn_style,
                                  _popout_toggle_ss, _sep_line_color, _shortcut_should_yield,
                                  _text_input_dialog)
from spectra.ui.tokens import (FONT_FAMILY, FS_BODY, FS_DISP, FS_LG, FS_SM, FS_VAL, FS_XS,
                               RADIUS_CTRL, RADIUS_SM, _n2_caps_font, _n2_mono_font, _n2_val_font,
                               ss_btn_neutral, ss_btn_primary, ss_text)
from spectra.ui.widgets import (DeviceCardPopup, RoundComboBox, VUMeter, _CollapseBtn,
                                _DashedAddButton, _N2Button, _N2IconBtn, _N2Segmented, _N2Select,
                                _N2Tab, _N2Toggle, _SidebarIcon, _SpecCard, _SplAlarmBtn,
                                _SplMeterBtn, _ToolbarToggleBtn, _apply_app_dark_appearance,
                                _apply_dark_titlebar, _apply_native_titlebar_dark,
                                _apply_windows_titlebar_dark, _grad_topline, _make_brand_header,
                                _restyle_brand_header, _sec_hairline)

APP_VERSION = ''   # wayaudo2.py 진입 시 _APP_VERSION 주입(About/푸터 표기용)


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
# _TFTitleHotspot — v2.0 분해: spectra/ui/tf_window.py, re-import


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


# _StereoPopoutWindow — v2.0 분해: spectra/ui/stereo_page.py, re-import


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
        fl.addWidget(QLabel(f'SPECTRA  |  v{APP_VERSION}'))
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
        # FOH 글랜스 쇼 모드 — 풀스크린 거대 SPL+스펙트럼(v2.0 재개, 2026-08-29).
        show_act = QAction('Show Mode (Full Screen)', self)
        show_act.setShortcut('Ctrl+Shift+F')   # macOS에선 Cmd+Shift+F
        show_act.triggered.connect(self._open_show_mode); view_menu.addAction(show_act)
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
        ver = QLabel(f'Version {APP_VERSION}    ·    by WAYAUDIO')
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
