11#!/usr/bin/env python3
# ═══════════════════════════════════════════════════
#  SPECTRA — Spectrum Analyzer  (by WAYAUDIO)  v2.0.2
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

# _no_stderr — v2.0 분해: spectra/ui/tf_window.py, re-import
from spectra.ui.tf_window import _no_stderr
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
_APP_VERSION = '2.0.2'

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
from spectra.core.config import (_APP_SUPPORT, _SETTINGS_PATH, _CAPTURES_PATH, _CAPTURES_TF_PATH,
                                 _CAPTURES_LOCK, _CAPTURES_TF_LOCK,
                                 _load_settings, _save_settings, _load_captures_file, _save_captures_file,
                                 _load_tf_captures_file, _save_tf_captures_file)

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

# _popout_toggle_ss — v2.0 분해: spectra/ui/tf_window.py, re-import
from spectra.ui.tf_window import _popout_toggle_ss
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
# _set_float_above_fullscreen — v2.0 분해: spectra/ui/stereo_page.py, re-import
from spectra.ui.stereo_page import _set_float_above_fullscreen
# _set_fullscreen_auxiliary — v2.0 분해: spectra/ui/main_window.py, re-import
from spectra.ui.main_window import _set_fullscreen_auxiliary
# _attach_as_child — v2.0 분해: spectra/ui/main_window.py, re-import
from spectra.ui.main_window import _attach_as_child
# _detach_as_child — v2.0 분해: spectra/ui/main_window.py, re-import
from spectra.ui.main_window import _detach_as_child
from spectra.ui.spl import (_apply_on_top)
# _fourcc — v2.0 분해: spectra/audio/engine.py, re-import
from spectra.audio.engine import _fourcc
# _CoreAudioDeviceWatcher — v2.0 분해: spectra/audio/engine.py, re-import
from spectra.audio.engine import _CoreAudioDeviceWatcher
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
# _db_ctrl_btn_style — v2.0 분해: spectra/ui/tf_window.py, re-import
from spectra.ui.tf_window import _db_ctrl_btn_style
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


# _sep_line_color — v2.0 분해: spectra/ui/tf_window.py, re-import
from spectra.ui.tf_window import _sep_line_color
# _splitter_qss — v2.0 분해: spectra/ui/main_window.py, re-import
from spectra.ui.main_window import _splitter_qss
from spectra.ui.draw import _tf_card_palette, _tf_gutter, _paint_tf_card


from PyQt5.QtWidgets import QSplitterHandle

# 스플리터 — v2.0 분해: spectra/ui/widgets.py, re-import
from spectra.ui.widgets import _GradSplitterHandle, _CardSplitter
# _VScrollArea — v2.0 분해: spectra/ui/tf_window.py, re-import
from spectra.ui.tf_window import _VScrollArea
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
# _capture_palette — v2.0 분해: spectra/ui/tf_window.py, re-import
from spectra.ui.tf_window import _capture_palette
# _auto_capture_color — v2.0 분해: spectra/ui/tf_window.py, re-import
from spectra.ui.tf_window import _auto_capture_color
from spectra.ui.canvas_tf import _catmull_seg
# 죽은콜백 예외 — v2.0 분해: spectra/audio/engine.py 내부(엔진 전용)


# (오디오 엔진 클래스는 위에서 spectra.audio.engine 로 일괄 re-import됨)


# TFSyncThread — v2.0 분해: spectra/ui/tf_window.py, re-import
from spectra.ui.tf_window import TFSyncThread
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
# _text_input_dialog — v2.0 분해: spectra/ui/tf_window.py, re-import
from spectra.ui.tf_window import _text_input_dialog
from spectra.ui.dialogs import _brand_msg, _BrandBox
# _md_to_html — v2.0 분해: spectra/ui/main_window.py, re-import
from spectra.ui.main_window import _md_to_html
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
# _global_popup_qss — v2.0 분해: spectra/ui/main_window.py, re-import
from spectra.ui.main_window import _global_popup_qss
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
# _cap_dot_pm — v2.0 분해: spectra/ui/capture_drawer.py, re-import
from spectra.ui.capture_drawer import _cap_dot_pm
from spectra.ui.icons import _led_power_pm
# _DragGrip — v2.0 분해: spectra/ui/capture_drawer.py, re-import
from spectra.ui.capture_drawer import _DragGrip
# _CaptureDrawer — v2.0 분해: spectra/ui/capture_drawer.py, re-import
from spectra.ui.capture_drawer import _CaptureDrawer
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
# TF 윈도우 상수 9종 — v2.0 분해: spectra/ui/tf_window.py 내부

# TF 스무딩/멀티마이크 평균 — v2.0 분해: spectra/dsp/tf.py 로 이동, re-import(동작 불변)
from spectra.dsp.tf import _smooth_real, _tf_smooth, _multimic_average

# _gen_log_sweep — v2.0 분해: spectra/ui/tf_window.py, re-import
from spectra.ui.tf_window import _gen_log_sweep
# _gen_pink_noise — v2.0 분해: spectra/ui/tf_window.py, re-import
from spectra.ui.tf_window import _gen_pink_noise
from spectra.dsp.tf import MTWEngine


# Farina ESS DSP — v2.0 분해: spectra/dsp/farina.py 로 이동, 여기로 re-import(동작 불변)
from spectra.dsp.farina import (_gen_ess, _ess_inverse, _fft_convolve,
                                _band_taper, _wiener_match_scale, farina_analyze)


# _TF_SEL_GRAD_STOPS — v2.0 분해: spectra/ui/colors.py, re-import
from spectra.ui.colors import _TF_SEL_GRAD_STOPS

# _draw_tf_sel_border — v2.0 분해: spectra/ui/draw.py, re-import
from spectra.ui.draw import _draw_tf_sel_border
# TF 주파수줌 한계 상수 — v2.0 분해: spectra/ui/canvas_tf.py 내부

# _fz_clamp — v2.0 분해: spectra/ui/canvas_tf.py, re-import (_FZ_MIN_DECADES=골든테스트가 참조)
from spectra.ui.canvas_tf import _fz_clamp, _FZ_MIN_DECADES
# _TFFreqZoomMixin — v2.0 분해: spectra/ui/canvas_tf.py, re-import
from spectra.ui.canvas_tf import _TFFreqZoomMixin
# TFPhaseCanvas — v2.0 분해: spectra/ui/canvas_tf.py, re-import
from spectra.ui.canvas_tf import TFPhaseCanvas
# TFMagCanvas — v2.0 분해: spectra/ui/canvas_tf.py, re-import
from spectra.ui.canvas_tf import TFMagCanvas
# _SignalIcon — v2.0: 미사용(구 TF 장치선택 UI 잔재) 제거(2026-08-29)
# _device_section_label — v2.0: 미사용(구 TF 장치선택 UI 잔재) 제거(2026-08-29)
from spectra.ui.widgets import _MiniVU
# ───────────────────────────────────────────
#  Smaart 방식 Input Levels 카드 위젯
# ───────────────────────────────────────────
# _HorizBarVU — v2.0 분해: spectra/ui/widgets.py, re-import
from spectra.ui.widgets import _HorizBarVU
# _DashedAddButton — v2.0 분해: spectra/ui/widgets.py 로 이동, re-import
from spectra.ui.widgets import _DashedAddButton
# _ColorSwatch — v2.0: 미사용(구 TF 장치선택 UI 잔재) 제거(2026-08-29)
from spectra.ui.widgets import _MeasCard, _PairLevelCard
# _VUProxy — v2.0 분해: spectra/ui/widgets.py, re-import
from spectra.ui.widgets import _VUProxy
# ───────────────────────────────────────────
#  Live IR 헬퍼 & 캔버스
# ───────────────────────────────────────────
# _hilbert_env — v2.0 분해: spectra/dsp/tf.py, re-import
from spectra.dsp.tf import _hilbert_env
# _ir_from_mag_phase — v2.0 분해: spectra/ui/tf_window.py, re-import
from spectra.ui.tf_window import _ir_from_mag_phase
from spectra.ui.canvas_tf import TFIRCanvas
# TFDuplexThread — v2.0 분해: spectra/ui/tf_window.py, re-import
from spectra.ui.tf_window import TFDuplexThread
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
# _shortcut_should_yield — v2.0 분해: spectra/ui/tf_window.py, re-import
from spectra.ui.tf_window import _shortcut_should_yield
# _TFKeyFilter — v2.0 분해: spectra/ui/tf_window.py, re-import
from spectra.ui.tf_window import _TFKeyFilter
# _MainKeyFilter — v2.0 분해: spectra/ui/main_window.py, re-import
from spectra.ui.main_window import _MainKeyFilter
from spectra.ui.tf_window import _TFTitleHotspot
from spectra.ui.dialogs import _ConvWorker
# _AuralizeDialog — v2.0 분해: spectra/ui/dialogs.py, re-import
from spectra.ui.dialogs import _AuralizeDialog
# TransferFunctionWindow — v2.0 분해: spectra/ui/tf_window.py, re-import
from spectra.ui.tf_window import TransferFunctionWindow
from spectra.ui.stereo_page import _CanvasKeyRouter
# StereoAudioThread — v2.0 분해: spectra/ui/stereo_page.py, re-import
from spectra.ui.stereo_page import StereoAudioThread
from spectra.dsp.loudness import _biquad, _KWeightFilter, LoudnessMeter


# 브랜드 색상 헬퍼 — v2.0 분해: spectra/ui/colors.py 로 이동, re-import
from spectra.ui.colors import _spec_color, _brand_color, _rgba_css, _metric_col


# VectorscopeCanvas — v2.0 분해: spectra/ui/canvas_stereo.py, re-import
from spectra.ui.canvas_stereo import VectorscopeCanvas
# LoudnessRadarCanvas — v2.0 분해: spectra/ui/canvas_stereo.py, re-import
from spectra.ui.canvas_stereo import LoudnessRadarCanvas
# _GradientNumber — v2.0 분해: spectra/ui/canvas_stereo.py, re-import
from spectra.ui.canvas_stereo import _GradientNumber
# LoudnessHistoryCanvas — v2.0 분해: spectra/ui/canvas_stereo.py, re-import
from spectra.ui.canvas_stereo import LoudnessHistoryCanvas
# StereoLoudnessPage — v2.0 분해: spectra/ui/stereo_page.py, re-import
from spectra.ui.stereo_page import StereoLoudnessPage
# _TFPopoutWindow — v2.0 분해: spectra/ui/main_window.py, re-import
from spectra.ui.main_window import _TFPopoutWindow
# _SpectrumPopoutWindow — v2.0 분해: spectra/ui/main_window.py, re-import
from spectra.ui.main_window import _SpectrumPopoutWindow
from spectra.ui.stereo_page import _StereoPopoutWindow
# MainWindow — v2.0 분해: spectra/ui/main_window.py, re-import (+버전 주입)
import spectra.ui.main_window as _main_window_mod
_main_window_mod.APP_VERSION = _APP_VERSION   # About/푸터 표기용(bump 대상은 wayaudo _APP_VERSION 유지)
from spectra.ui.main_window import MainWindow
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

# _log_audio_devices — v2.0 분해: spectra/ui/main_window.py, re-import
from spectra.ui.main_window import _log_audio_devices
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
