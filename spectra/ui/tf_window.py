"""Transfer Function 탭 — 공유 Reference + 멀티 Measurement 카드, Mag/Phase/IR.

v2.0 분해: wayaudo2.py에서 이동(동작 0 변경). embedded 탭/standalone 겸용.
TF 생태계(듀플렉스·키필터·제너레이터·캡쳐)를 통째 이관.
"""
import math, os, time, threading, datetime, collections, random
import math as _math
from collections import deque
from contextlib import contextmanager
import random
import numpy as np
import sounddevice as sd
import soundfile as sf
from PyQt5.QtGui import QColor, QFont
from PyQt5.QtCore import (Qt, QEvent, QMutex, QMutexLocker, QObject, QPoint, QThread,
                          QTimer, pyqtSignal)
from PyQt5.QtWidgets import (QAbstractItemView, QAbstractSpinBox, QApplication, QCheckBox,
                             QColorDialog, QComboBox, QDialog, QDoubleSpinBox, QFileDialog,
                             QFrame, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMenu,
                             QPlainTextEdit, QPushButton, QScrollArea, QTextEdit, QVBoxLayout,
                             QWidget)
from spectra.audio.engine import (_EngineChannelSource, _EngineMultiSource, _EngineSyncSource,
                                  _dev_hostapi_ok, _win_extra_settings, _win_preferred_hostapi)
from spectra.audio.watchdog import StreamStalled, begin_no_sleep, classify_stall, end_no_sleep
from spectra.core.config import (SPEED_LEVELS, T, _CAPTURES_TF_LOCK, _load_tf_captures_file,
                                 _save_tf_captures_file, _save_settings, delay_unit, is_dark,
                                 set_delay_unit)
from spectra.core.i18n import _tx
from spectra.core.logging_diag import _alog, _diag, _no_stderr
from spectra.dsp.farina import _wiener_match_scale, farina_analyze
from spectra.dsp.tf import MTWEngine, _hilbert_env, _multimic_average, _tf_smooth
from spectra.dsp.weighting import _octave_bands, power_spectrum_db
from spectra.ui.canvas_spectrum import OctaveCanvas
from spectra.ui.canvas_tf import TFIRCanvas, TFMagCanvas, TFPhaseCanvas, _ask_db_range
from spectra.ui.colors import _MC_COLORS, _spectra_mark
from spectra.ui.dialogs import (AllDelayFinderDialog, DelayFinderDialog, SineConfigDialog,
                                SweepConfigDialog, _AuralizeDialog, _BrandBox, _TFAverageDialog)
from spectra.ui.draw import METER_RED_DB, METER_YELLOW_DB
from spectra.ui.icons import (_icon, _icon_pm, _n2_divider, _n2_group_header, _n2_icon_color)
from spectra.ui.spl import _apply_txn
from spectra.ui.tokens import (FONT_NUM, FS_BODY, FS_SM, FS_XS, RADIUS_CTRL, _n2_caps_font, _n2_mono_font,
                               _n2_val_font, ss_btn_neutral, ss_btn_primary, ss_input, ss_text)
from spectra.ui.widgets import (RoundComboBox, _BrandHeaderBar, _CardSplitter, _CheckBtn,
                                _DashedAddButton, _HorizBarVU, _MeasCard, _N2Button, _N2IconBtn,
                                _N2Select, _VUProxy, _apply_dark_titlebar, _brand_logo_html, hsep)


# TF 윈도우 전용 상수 (클러스터 밖 미사용)
TF_SMOOTH_BPO    = [0, 48, 24, 12, 6, 3, 1]
TF_SMOOTH_LABELS = ['None', '1/48', '1/24', '1/12', '1/6', '1/3', '1/1 Oct']
TF_AVG_SEC       = [0.5, 1, 2, 4, 8]
TF_AVG_LABELS    = ['Fast', 'Quick', 'Normal', 'Smooth', 'Stable']
TF_FFT_SIZES     = [4096, 8192, 16384, 32768]
TF_FFT_LABELS    = ['4K', '8K', '16K', '32K']
TF_RENDER_MS     = 100
TF_PHASE_MODES   = ['Wrapped', 'Unwrapped', 'Group Delay']
TF_IR_MODES      = ['Lin', 'ETC', 'Log']


# (import 시 로그셋업·excepthook·로그정리 실행 — 종전과 동일 시점)


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



def _sep_line_color():
    return '#4A4A4A' if is_dark() else T('border')


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

_capture_palette_cache = None


def _capture_palette(count=48, avoid=()):
    """캡쳐 색 팔레트 — 라이브 카드 색(_MC_COLORS)과도, 서로와도 최대한 멀리 떨어지게.
    최원점(farthest-point) 선택: 색공간(hue+채도+밝기) 후보 중 '이미 뽑힌 색 + 라이브 색'과
    RGB 거리가 가장 먼 색을 차례로 고른다. 라이브 색을 시드로 넣어 캡쳐가 라이브를 회피.
    채도/밝기 하한을 둬 다크·라이트 양 테마에서 모두 잘 보이게. 1회 계산 후 캐시(결정론적).
    color 그룹만으론 hue 공간이 부족해 22개+에서 비슷해지던 문제 해결.
    avoid: 사용자가 화면에서 실제로 쓰는 라이브 색(스펙트럼 바 색·추가 카드·TF 카드 등).
    _MC_COLORS 기본 팔레트뿐 아니라 이 색들까지 시드에 넣어 캡쳐가 회피한다.
    avoid가 있으면 세션마다 바뀔 수 있어 캐시하지 않고 매번 계산(수백×후보, 벡터화라 저렴)."""
    global _capture_palette_cache
    if not avoid and _capture_palette_cache is not None and len(_capture_palette_cache) >= count:
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
    seed = list(_MC_COLORS) + [c for c in avoid if c]
    live = np.asarray([[QColor(c).red(), QColor(c).green(), QColor(c).blue()]
                       for c in seed], dtype=np.float64)
    # 벡터화 farthest-point: 라이브 시드까지 최소거리²에서 시작 → 매 단계 argmax 선택 후 선택색 거리로 갱신
    min_d = ((cand[:, None, :] - live[None, :, :]) ** 2).sum(-1).min(axis=1)
    out = []
    for _ in range(count):
        i = int(np.argmax(min_d))
        out.append(cand_name[i])
        min_d = np.minimum(min_d, ((cand - cand[i]) ** 2).sum(-1))
    if not avoid:
        _capture_palette_cache = out
    return out


def _auto_capture_color(n, avoid=()):
    """캡쳐 색 — 라이브 카드·다른 캡쳐와 최대한 구분되는 팔레트의 n번째(초과 시 순환).
    avoid: 회피할 라이브 색 목록(_capture_palette 참고)."""
    pal = _capture_palette(avoid=avoid)
    return pal[n % len(pal)]



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
        _dead_reopens = 0   # 연속 실패 재오픈 — 콜백 재개 시 리셋
        begin_no_sleep()    # 측정 중 idle 시스템 절전 차단(콜백 정지 트리거 제거)
        try:
            while self.running:   # 같은 config 재오픈 루프 (running-stall 복구)
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
                            _wd_got[0] = False
                            _wd_last[0] = time.monotonic()
                            _open_t = time.monotonic()          # [DIAG] 오픈 시각 — 첫 콜백 지연/미시작 계측
                            _first_logged = False
                            while self.running:
                                self.msleep(10)
                                # [DIAG] AUHAL 콜백 시작 진단: 인터페이스 콜드오픈 시 스트림은 열려도 콜백이
                                # 스케줄 안 되는 레이스(하드웨어 미터도 무음) 추적.
                                if _wd_got[0] and not _first_logged:
                                    _first_logged = True
                                    _dead_reopens = 0   # 콜백 정상 재개 → 예산 회복
                                    _diag('tf_duplex_first_cb', dev=self.out_dev,
                                          dt_ms=round((time.monotonic() - _open_t) * 1000))
                                # 스타트업 죽음: 열렸는데 첫 콜백 2초 미수신 → 같은 config 재오픈
                                if (not _wd_got[0]) and time.monotonic() - _open_t > 2.0:
                                    _diag('tf_duplex_cb_dead', dev=self.out_dev, in_dev=self.in_dev,
                                          bs=blocksize)   # ⚠️콜백 2초간 미시작 = 무음 원인 후보
                                    raise StreamStalled()
                                # running-stall: 콜백 흐르다 2초 멈춤(절전/App Nap/글리치) →
                                # 물리적 제거로 단정 말고 같은 장치 재오픈. [찾기: CB_STALL]
                                if _wd_got[0] and time.monotonic() - _wd_last[0] > 2.0:
                                    _diag('tf_duplex_cb_stall', dev=self.out_dev, in_dev=self.in_dev,
                                          age_ms=round((time.monotonic() - _wd_last[0]) * 1000))
                                    raise StreamStalled()
                            self.msleep(80)
                    return  # running False → 정상 종료
                except StreamStalled:
                    self._active_stream = None
                    if not self.running: return
                    _dead_reopens += 1
                    if classify_stall(_dead_reopens) == 'disconnect':
                        _diag('tf_duplex_stall_giveup', dev=self.out_dev, in_dev=self.in_dev)
                        self.disconnected_signal.emit('device removed (stall)'); return  # '(stall)'=6회 소진 확정 → UI 개수가드 우회 복구
                    self.msleep(150); continue   # 같은 config 재오픈
        except Exception as e:
            _alog.error(f'TFDuplexThread sd.Stream FAILED: {e}')
            self.error_signal.emit(str(e))
        finally:
            self._active_stream = None
            end_no_sleep()

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
            # ★ TF 창이 '활성'일 때만 처리한다. 이 필터는 앱 전역에 설치돼 있고 유일한 조건이
            #   isVisible()인데, TF를 팝아웃하거나 분할 보기로 두면 그 값이 항상 참이라
            #   Spectrum 팝아웃·Stereo 창·SPL 미터에서 타이핑해도 G가 눌려 **PA로 핑크노이즈가
            #   나갔다**(공연 중이면 사고). L(전체 딜레이 찾기)도 마찬가지.
            _w = self._tf.window()
            if _w is not None and not _w.isActiveWindow():
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
        # settings가 dict면(빈 dict 포함) 그 참조를 그대로 공유 — 예전 `settings or {}`는 첫 실행 시
        # _load_settings()가 빈 {}(falsy)를 주면 TF가 별개 dict를 만들어 메인과 갈라져, 서로의
        # 첫 세션 키를 저장 때 덮어쓰던 버그. 참조 공유로 두 창이 항상 같은 dict를 본다.
        self._hann_cache = {}          # 길이 → Hanning 창 (아래 _hann() 캐시)
        self._settings = settings if isinstance(settings, dict) else {}
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
        # 코히런스 블랭킹 on/off → 저장 + 재시작 복원 (기본 ON) [COH_BLANK]
        self.mag_cvs._on_coh_blank_change = self._on_tf_coh_blank_change
        self.mag_cvs._coh_blank_on = bool(self._settings.get('tf_coh_blank', True))
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
            f'QDoubleSpinBox{{{_c_cell}padding:2px 4px;font-family:{FONT_NUM};font-size:12px;}}')
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

    def _on_tf_coh_blank_change(self, on):
        """코히런스 블랭킹 on/off → 설정 저장(재시작 복원용). [COH_BLANK]"""
        self._settings['tf_coh_blank'] = bool(on)
        _save_settings(self._settings)

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
        # ★ 저장된 장치/채널이 지금 없으면 콤보의 기본 선택(엉뚱한 입력)에 조용히 물린다.
        #   못 찾았음을 로그로 남겨 '왜 다른 마이크가 측정되지' 를 추적 가능하게 한다.
        #   (ref/meas/out 복원 경로는 _select_combo_by_name 반환값으로 이미 이렇게 처리한다.)
        dev_name = entry.get('meas_device', '')
        _dev_ok = False
        for i in range(mcb.count()):
            if self._strip_star(mcb.itemText(i)) == dev_name:
                mcb.setCurrentIndex(i); _dev_ok = True; break
        saved_ch = entry.get('meas_ch', 0)
        _ch_ok = False
        for i in range(mch.count()):
            if mch.itemData(i) == saved_ch:
                mch.setCurrentIndex(i); _ch_ok = True; break
        if not _dev_ok or not _ch_ok:
            _alog.warning(f'TF 카드 복원 — 저장된 입력을 못 찾음 (device="{dev_name}" found={_dev_ok}, '
                          f'ch={saved_ch} found={_ch_ok}) → 현재 선택으로 대체됨')
            _diag('tf_card_restore_miss', dev=dev_name, dev_ok=_dev_ok, ch=saved_ch, ch_ok=_ch_ok)
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
        # ★ 인덱스를 키로 쓰는 레퍼런스 캐시도 함께 재정렬 — pop으로 뒤 인덱스가 당겨지는데
        #   이 dict를 그대로 두면 재사용된 인덱스가 '삭제된 쌍의 레퍼런스'를 읽어 조용히
        #   잘못된 TF(크기·위상)가 나온다. 해당 키 제거 + 뒤 키 한 칸씩 당김.
        for _d in (getattr(self, '_extra_ref_fft', None), getattr(self, '_extra_ref_buf', None)):
            if not _d: continue
            _d.pop(idx, None)
            for _k in sorted(k for k in list(_d) if isinstance(k, int) and k > idx):
                _d[_k - 1] = _d.pop(_k)
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

    def _resolve_mw(self):
        """MainWindow 안정 해석 — 팝아웃/분할 후에도 유효.
        self.window()는 팝아웃 시 _TFPopoutWindow(순수 QWidget)를 반환해 MainWindow의 속성이
        전부 사라진다. 생성 시점에 잡아둔 _mw가 reparent와 무관하게 불변이므로 그쪽을 우선."""
        mw = getattr(self, '_mw', None)
        if mw is not None and hasattr(mw, 'oct_cvs'):
            return mw
        w = self.window()
        return w if (w is not None and hasattr(w, 'oct_cvs')) else mw or w

    def _hann(self, n):
        """길이별 Hanning 창 캐시.

        [PERF] primary 경로만 창을 캐시하고 추가카드·스윕 경로는 매 청크마다
        np.hanning(16384).astype(float32)을 새로 만들었다. 카드 4개면 초당 100~200MB를
        할당·해제해 힙이 파편화되고 macOS에선 누수처럼 보였다. 길이는 몇 종류뿐이라 dict로 충분."""
        w = self._hann_cache.get(n)
        if w is None:
            w = np.hanning(n).astype(np.float32)
            self._hann_cache[n] = w
        return w

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
        win = self._hann(n)
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
            win = self._hann(len(buf))
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
            win = self._hann(n)
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
        win = self._hann(n)
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
                    win = self._hann(len(ref_buf))
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
                    win = self._hann(len(meas_buf))
                    fft_m = np.fft.rfft(meas_buf * win).astype(complex)
                    if len(fft_r) == len(fft_m):
                        self._accumulate_extra(pair_idx, fft_r, fft_m)
                continue
            r['callback'](ref_buf, meas_buf)

    def _on_extra_ref(self, pair_idx, buf):
        """AudioThread ref 콜백 (diff-device extra pair)."""
        n = len(buf)
        win = self._hann(n)
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
        win = self._hann(n)
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
        # '(stall)' 마커 = 엔진이 6회 재오픈까지 소진한 확정 죽음(장치는 열거 유지, 개수 안 줆).
        # 개수 가드로 무시하면 안 됨 → stop-먼저 경로(_after_tf_disconnect: 스냅샷이 비어 복구 실패)를
        # 건너뛰고 스냅샷-후-정지하는 reinit_audio_devices로 직행해 같은 장치 자동복구를 태운다.
        if isinstance(msg, str) and '(stall)' in msg:
            # ★ self.window()가 아니라 self._mw — 팝아웃 시 TF는 _TFPopoutWindow(순수 QWidget,
            #   reinit_audio_devices 없음)로 reparent돼 window()로는 MainWindow를 못 잡고
            #   분기가 통째로 no-op이 된다(입력은 죽고 제너레이터만 계속 나가던 버그).
            mw = getattr(self, '_mw', None)
            if mw is None or not hasattr(mw, '_stall_recover'):
                mw = self.window()
            if mw is not None and hasattr(mw, '_stall_recover'):
                mw._stall_recover('TF')   # 공용 경로(에피소드 디바운스 포함)
            else:
                # MainWindow를 못 잡는 예외 상황 — 최소한 측정/제너레이터는 멈춰 무한 방치 방지
                _alog.warning('TF stall — MainWindow 참조 실패, 로컬 정지만 수행')
                _diag('tf_stall_recover', dev=getattr(self, 'device_idx', -1), local_only=True)
                try: self._stop_analysis(); self._stop_sig_gen()
                except Exception: pass
                try: self._load_devices()
                except Exception: pass
            return
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
        mw = self._resolve_mw()
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
        if getattr(self, '_rta_stale_n', 0):      # 청크가 오면 백오프/파킹 상태 해제
            self._rta_stale_n = 0; self._rta_parked = False
        buf = d.get(self._rta_ch)
        if buf is None or len(buf) < 8:
            return
        # ★ self.window()가 아니라 _mw 우선 — 팝아웃되면 window()는 _TFPopoutWindow(순수 QWidget)라
        #   avg_count/calib_offset/oct_cvs가 전부 없어 getattr 기본값으로 조용히 떨어졌다
        #   (RTA가 SPL 캘리브 오프셋을 통째로 잃고, 평균 16·속도 기본값으로 되돌아감).
        rc = self.rta_cvs; mw = self._resolve_mw()
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
        # 뮤텍스 불필요: 생산자(_on_rta_chunk)·소비자(_rta_render_frame)가 모두 GUI 스레드(청크는
        # Qt.QueuedConnection)라 동시 접근이 없고, 튜플 단일 참조 대입은 GIL 하에서 원자적.
        # ※ 이 연결을 Direct로 바꾸면 QMutex로 보호해야 함(메인 _pending 패턴 참고).
        self._rta_pending = (rc.mode, _octave_bands(freqs, avg + calib, rc.mode), calib)

    def _rta_render_frame(self):
        """RTA consumer — 30fps 고정 타이머가 최신 옥타브값을 꺼내 스무딩/peak-hold/repaint
        (스펙트럼 _render_frame과 동일 패턴). 콜백 지터와 무관한 일정 프레임 → 버벅임 제거."""
        if self._rta_sub is None or self._rta_pending is None:
            return
        rc = self.rta_cvs; mw = self._resolve_mw()
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
            # 백오프: 청크가 '영영' 안 오는 조건(무신호 채널·듀플렉스가 장치 점유 등)에서 1.2초마다
            # 재구독을 무한 반복하면 매 사이클이 _close_thread()의 wait(3000)로 GUI를 최대 3초 묶는다
            # (시간당 ~3000회). 연속 실패가 쌓이면 간격을 늘리고(1.2→10초), 10회면 파킹한다.
            _n = getattr(self, '_rta_stale_n', 0)
            stale = (time.monotonic() - self._rta_last_chunk > (1.2 if _n < 3 else 10.0))
            if device_changed or channel_changed:
                self._rta_stale_n = 0; self._rta_parked = False   # 사용자 변경 = 정상 추종
            elif stale:
                self._rta_stale_n = _n + 1
            if device_changed or channel_changed or stream_gone or stale:
                _diag('rta_resub', dev_chg=device_changed, ch_chg=channel_changed,
                      stream_gone=stream_gone, stale=stale, stale_n=getattr(self, '_rta_stale_n', 0),
                      old_dev=self._rta_sub.device_idx, new_dev=cur_dev,
                      old_ch=self._rta_ch, new_ch=cur_ch)
                self._rta_unsubscribe()
        if self._rta_sub is None:
            if getattr(self, '_rta_parked', False):
                # 파킹 해제는 사용자가 장치/채널을 바꿨을 때만 — 그 전엔 재구독 시도 자체를 안 한다.
                if (cur_dev, cur_ch) != getattr(self, '_rta_park_key', None):
                    self._rta_parked = False; self._rta_stale_n = 0
                else:
                    return
            elif getattr(self, '_rta_stale_n', 0) > 10:
                self._rta_parked = True; self._rta_park_key = (cur_dev, cur_ch)
                _alog.warning('RTA 청크 미도착 10회 연속 — 재구독 중단(파킹). 장치/채널 변경 시 재개')
                _diag('rta_park', dev=cur_dev, ch=cur_ch)
                self.rta_cvs._idle_hint = True; self.rta_cvs.update()
                return
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
        # ★ 비동기 저장 — 캡쳐가 쌓이면 전체 재직렬화가 O(n²)로 커져(캡쳐 50개=53MB, 실측 2.1초;
        #   100개=4.2초) 동기 저장은 GUI를 통째로 그만큼 얼렸다. 오디오가 idle이라 글리치 걱정이
        #   없는 시점이므로 백그라운드 스레드로 돌린다(_save_tf_captures_file은 tmp+os.replace
        #   원자 저장이라 중간에 끊겨도 파일은 온전. spec 캡처와는 파일이 달라 경쟁도 없다).
        #   ※ json.dumps는 GIL을 놓지 않아 '백그라운드'라도 직렬화 동안 GUI가 멈춘다 —
        #     캡처 수가 많을 때의 근본 해법은 곡선을 base64 float32로 담는 것(남은작업.md C-2).
        self._flush_tf_captures(sync=False)

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
            th = threading.Thread(target=self._serialize_save_tf_captures,
                                  args=(metas, mag_caps, phase_caps, ir_caps), daemon=True)
            self._caps_save_thread = th      # 종료 시 완료를 기다리기 위한 핸들
            th.start()

    def _wait_caps_saved(self, timeout=5.0):
        """종료 경로용 — 진행 중인 백그라운드 캡쳐 저장이 끝날 때까지 잠깐 기다린다.
        (os._exit로 즉시 종료하므로 기다리지 않으면 마지막 저장이 잘릴 수 있다.)"""
        th = getattr(self, '_caps_save_thread', None)
        if th is not None and th.is_alive():
            try: th.join(timeout)
            except Exception: pass

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
            # TF 캡처는 자기 파일만 쓴다 — spec 캡처와 파일이 갈라져 서로를 재직렬화하지 않는다.
            with _CAPTURES_TF_LOCK:
                _save_tf_captures_file({'tf': tf_list})
        except Exception as e:
            _alog.warning(f'TF 캡처 저장 실패: {e}')

    def _restore_tf_captures(self):
        data = _load_tf_captures_file()   # 분리된 TF 파일(이관 전이면 레거시에서 승계)
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

    def _live_avoid_colors(self):
        """캡쳐 색이 회피할 현재 라이브 색 = 카드 색 전부(primary=초록 포함) + extra pair 색."""
        avoid = [getattr(c, '_color', None) for c in getattr(self, '_level_cards', [])]
        avoid += [p.get('color') for p in getattr(self, '_extra_pairs', [])]
        return [c for c in avoid if c]

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
        avoid = self._live_avoid_colors()
        # primary — 표시 중일 때만 (꺼져 있으면 캔버스 데이터가 stale)
        primary_on = bool(self._level_cards) and self._level_cards[0]._display_on   # 카드 없으면(primary 삭제) 캡처 안 함(유령 방지)
        if primary_on:
            color = _auto_capture_color(n, avoid=avoid)
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
            # ★ _set_playable()까지 불러야 한다 — 예전엔 빠져 있어, 측정 전에 한 번 열어
            #   Room이 비활성된 상태로 닫으면 이후 측정을 마치고 다시 열어도 계속 비활성이었다
            #   (_populate_ir_sources가 blockSignals로 채워 _on_ir_src_changed도 안 돌기 때문).
            dlg._populate_ir_sources(); dlg._refresh_ir_state(); dlg._set_playable()
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
                color = _auto_capture_color(len(self._tf_captures), avoid=self._live_avoid_colors())
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
        color = _auto_capture_color(n, avoid=self._live_avoid_colors())
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
        _dead_reopens = 0   # 연속 실패 재오픈 — 콜백 재개 시 리셋(장시간 세션 소진 방지)
        begin_no_sleep()    # 측정 중 idle 시스템 절전 차단(콜백 정지 트리거 제거)
        try:
            for round_n in range(2):
                for bs in (blocksize, 0):
                    while self.running:   # 같은 config 재오픈 루프 (running-stall 복구)
                        try:
                            with _no_stderr():
                                with sd.InputStream(device=self.device_idx, samplerate=self.sample_rate,
                                                    channels=n_ch, blocksize=bs,
                                                    callback=cb, latency='high', dtype='float32',
                                                    extra_settings=_win_extra_settings()) as _s:
                                    self._active_stream = _s
                                    _got_cb[0] = False
                                    _last_cb[0] = time.monotonic(); _open_t = time.monotonic()
                                    try:
                                        while self.running:
                                            self.msleep(10)
                                            if _got_cb[0] and _dead_reopens:
                                                _dead_reopens = 0   # 콜백 정상 재개 → 예산 회복
                                            # 스타트업 죽음: 열렸는데 첫 콜백 2초 미수신 → 같은 config 재오픈
                                            if (not _got_cb[0]) and time.monotonic() - _open_t > 2.0:
                                                _diag('tf_sync_cb_dead', dev=self.device_idx, bs=bs)
                                                raise StreamStalled()
                                            # running-stall: 콜백 흐르다 2초 멈춤(절전/App Nap/글리치) →
                                            # 물리적 제거로 단정 말고 같은 장치 재오픈. [찾기: CB_STALL]
                                            if _got_cb[0] and time.monotonic() - _last_cb[0] > 2.0:
                                                _diag('tf_sync_cb_stall', dev=self.device_idx,
                                                      age_ms=round((time.monotonic() - _last_cb[0]) * 1000))
                                                raise StreamStalled()
                                    finally:
                                        self._active_stream = None
                            return  # running False → 정상 종료
                        except StreamStalled:
                            if not self.running: return
                            _dead_reopens += 1
                            if classify_stall(_dead_reopens) == 'disconnect':
                                _diag('tf_sync_stall_giveup', dev=self.device_idx)
                                self.disconnected_signal.emit('device removed (stall)'); return  # '(stall)'=6회 소진 확정 → UI 개수가드 우회 복구
                            self.msleep(150); continue   # 같은 config 재오픈
                        except Exception as e:
                            last_err = e
                            if not self.running: return
                            break   # open 실패 → 다음 bs
                if round_n == 0:
                    for _ in range(15):   # AUHAL 해제 대기 (running 반응형)
                        if not self.running: return
                        self.msleep(100)
            if last_err: self.error_signal.emit(str(last_err))
        finally:
            end_no_sleep()

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
