#!/usr/bin/env python3
# ═══════════════════════════════════════════════════
#  WAYAUDIO Spectrum Analyzer  v3.0
#  ✅ FFT 버벅임 수정 (포인트 다운샘플링)
#  ✅ 마이크 캘리브레이션 (94/114dB @ 1kHz)
#  ✅ dBA / dBC 실시간 레벨
#  ✅ LEQ A/C 시간 평균 (5~60분)
#  ✅ 친근한 디자인 + 야외 라이트 테마
# ═══════════════════════════════════════════════════
import sys, math, time, json, os, logging
import numpy as np
import sounddevice as sd
from collections import deque

# ── 오디오 진단 로그 (~/Desktop/wsa2_audio.log)
_LOG_PATH = os.path.expanduser('~/Desktop/wsa2_audio.log')
logging.basicConfig(filename=_LOG_PATH, level=logging.DEBUG,
                    format='%(asctime)s.%(msecs)03d %(message)s',
                    datefmt='%H:%M:%S', filemode='w')
_alog = logging.getLogger('wsa2')

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QVBoxLayout, QHBoxLayout, QComboBox,
    QPushButton, QLabel, QSizePolicy, QFrame,
    QGroupBox, QDialog, QSpinBox, QDoubleSpinBox,
    QFormLayout, QDialogButtonBox, QScrollArea,
    QSplashScreen, QSplitter, QStackedWidget, QColorDialog
)
from PyQt5.QtCore  import Qt, QTimer, pyqtSignal, QThread, QMutex, QMutexLocker, QPoint
from PyQt5.QtGui   import (
    QPainter, QColor, QPen, QFont,
    QLinearGradient, QBrush, QPainterPath,
    QRadialGradient, QPalette
)

# ───────────────────────────────────────────
#  상수
# ───────────────────────────────────────────
MAX_DB = 0
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
_SETTINGS_PATH = os.path.expanduser('~/Library/Application Support/WSA2/settings.json')

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
        'bg':       '#0a0c10',
        'bg2':      '#0f1318',
        'bg3':      '#141820',
        'panel':    '#12151c',
        'border':   '#252a35',
        'text':     '#dce6f0',
        'text_dim': '#6a8898',
        'accent':   '#00e5ff',
        'accent2':  '#ff6b35',
        'green':    '#39ff14',
        'yellow':   '#ffcc00',
        'red':      '#ff3333',
        'grid':     '#1a2030',
        'spec_fill_top': (0,229,255,130),
        'spec_fill_bot': (0,229,255,5),
        'spec_line':     '#00e5ff',
        'peak_line':     '#ff6b35',
    },
    'light': {
        'bg':       '#f0f4f8',
        'bg2':      '#ffffff',
        'bg3':      '#e8edf2',
        'panel':    '#dde4ec',
        'border':   '#b0c0d0',
        'text':     '#1a2535',
        'text_dim': '#5a6878',
        'accent':   '#0066cc',
        'accent2':  '#e05500',
        'green':    '#008800',
        'yellow':   '#bb8800',
        'red':      '#cc0000',
        'grid':     '#c0ccd8',
        'spec_fill_top': (0,102,204,100),
        'spec_fill_bot': (0,102,204,5),
        'spec_line':     '#0066cc',
        'peak_line':     '#e05500',
    }
}
_theme = 'dark'
def T(key): return THEMES[_theme][key]

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

# ── RTA Comparison Mode 채널 색상
CH_A_FILL_TOP = (0, 229, 255, 110)
CH_A_FILL_BOT = (0, 229, 255, 5)
CH_A_LINE     = '#00e5ff'
CH_B_FILL_TOP = (255, 140, 40, 80)
CH_B_FILL_BOT = (255, 140, 40, 0)
CH_B_LINE     = '#ff8c28'
CH_B_PEAK     = '#ffdd55'
DIFF_LINE     = '#cc44ff'

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
def draw_info_box(p, W, freq_str, db_str):
    p.setFont(QFont('Arial', 16, QFont.Bold))
    fw = p.fontMetrics().horizontalAdvance(freq_str)
    p.setFont(QFont('Arial', 13, QFont.Bold))
    dw = p.fontMetrics().horizontalAdvance(db_str)
    bw = max(fw,dw)+40; bh=66
    bx = W//2-bw//2; by=14
    for off,alp in [(5,15),(3,30),(2,50)]:
        p.setPen(QPen(QColor(T('accent')).darker(80) if _theme=='light' else QColor(0,229,255,alp), off*2))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(bx-off,by-off,bw+off*2,bh+off*2,10,10)
    p.setPen(QPen(QColor(T('accent')),2))
    p.setBrush(QBrush(QColor(T('bg2')).darker(110) if _theme=='light' else QColor(0,0,0,230)))
    p.drawRoundedRect(bx,by,bw,bh,8,8)
    p.setFont(QFont('Arial',17,QFont.Bold)); p.setPen(QColor(T('accent')))
    p.drawText(bx,by+4,bw,30,Qt.AlignHCenter|Qt.AlignVCenter,freq_str)
    p.setPen(QPen(QColor(T('border')),1))
    p.drawLine(bx+12,by+36,bx+bw-12,by+36)
    p.setFont(QFont('Arial',14,QFont.Bold)); p.setPen(QColor(T('accent2')))
    p.drawText(bx,by+36,bw,28,Qt.AlignHCenter|Qt.AlignVCenter,db_str)

# ───────────────────────────────────────────
#  오디오 스레드
# ───────────────────────────────────────────
class AudioThread(QThread):
    chunk_ready  = pyqtSignal(object)
    error_signal = pyqtSignal(str)
    def __init__(self, device_idx, sample_rate, fft_size, channel=0):
        super().__init__()
        self.device_idx=device_idx; self.sample_rate=sample_rate
        self.fft_size=fft_size; self.running=False; self.channel=channel
    def run(self):
        self.running=True
        buf=np.zeros(self.fft_size,dtype=np.float32)
        ch_idx=self.channel; n_ch=ch_idx+1
        def cb(indata,frames,ti,status):
            if not self.running: return
            try:
                src_ch=min(ch_idx, indata.shape[1]-1)
                chunk=indata[:,src_ch].astype(np.float32); n=min(len(chunk),len(buf))
                buf[:-n]=buf[n:]; buf[-n:]=chunk[:n]
                self.chunk_ready.emit(buf.copy())
            except Exception: pass
        blocksize=min(self.fft_size//4, 2048)
        try:
            with sd.InputStream(device=self.device_idx,samplerate=self.sample_rate,
                                channels=n_ch,blocksize=blocksize,
                                callback=cb,latency='high',dtype='float32'):
                while self.running: self.msleep(10)
        except Exception as e:
            self.error_signal.emit(str(e))
    def stop(self):
        self.running=False
        self.wait(4000)   # give PortAudio time to flush cleanly on macOS


class TFSyncThread(QThread):
    """Ref와 Meas가 같은 장치의 다른 채널일 때 단일 InputStream으로 샘플 동기화.
    두 채널을 동일 콜백에서 읽어 타이밍 오프셋을 완전히 제거.
    frame_ready(ref_buf, meas_buf)로 두 버퍼를 원자적으로 전달."""
    frame_ready  = pyqtSignal(object, object)   # (ref_buf, meas_buf) — 단일 이벤트
    error_signal = pyqtSignal(str)

    def __init__(self, device_idx, sample_rate, fft_size, ref_ch, meas_ch):
        super().__init__()
        self.device_idx = device_idx
        self.sample_rate = sample_rate; self.fft_size = fft_size
        self.ref_ch = ref_ch; self.meas_ch = meas_ch
        self.running = False

    def run(self):
        self.running = True
        blocksize = min(self.fft_size // 4, 2048)
        n_ch = max(self.ref_ch, self.meas_ch) + 1
        ref_buf  = np.zeros(self.fft_size, dtype=np.float32)
        meas_buf = np.zeros(self.fft_size, dtype=np.float32)
        r_ch = self.ref_ch; m_ch = self.meas_ch

        def cb(indata, frames, ti, status):
            if not self.running: return
            nc = indata.shape[1]
            rc = min(r_ch, nc - 1); mc = min(m_ch, nc - 1)
            ref_buf[:-frames]  = ref_buf[frames:];  ref_buf[-frames:]  = indata[:frames, rc]
            meas_buf[:-frames] = meas_buf[frames:]; meas_buf[-frames:] = indata[:frames, mc]
            self.frame_ready.emit(ref_buf.copy(), meas_buf.copy())

        try:
            with sd.InputStream(device=self.device_idx, samplerate=self.sample_rate,
                                channels=n_ch, blocksize=blocksize,
                                callback=cb, latency='high', dtype='float32'):
                while self.running: self.msleep(10)
        except Exception as e:
            self.error_signal.emit(str(e))

    def stop(self):
        self.running = False; self.wait(4000)


# ───────────────────────────────────────────
#  FFT 캔버스 — ★ 다운샘플링으로 포인트 수 제한
# ───────────────────────────────────────────
class FFTCanvas(QWidget):
    PAD_L=54; PAD_R=10; PAD_T=12; PAD_B=28
    MAX_POINTS=600   # ★ 화면 너비보다 많은 포인트는 낭비

    def __init__(self):
        super().__init__()
        self.setMinimumSize(300,150)
        self.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Expanding)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WA_OpaquePaintEvent,True)
        self.db_min=-96; self.db_max=MAX_DB
        self.freqs=None; self.avg=None; self.peak=None
        self.peak_hold=True; self.scale_log=True
        self.sample_rate=48000; self.fft_size=16384
        self._mx=-1; self._my=-1
        self.peak_hold_frames=0
        self.peak_decay_rate_pk=1.0
        self._peak_age=None; self._peak_age_b=None
        self._cache=None
        # ★ 다운샘플된 포인트 캐시
        self._ds_f=None; self._ds_avg=None; self._ds_pk=None
        # ── 채널 B (비교 모드)
        self.compare_mode=False
        self.peak_b=None
        self._ds_f_b=None; self._ds_avg_b=None; self._ds_pk_b=None
        self.show_diff=False; self._ds_diff=None

    def clear(self):
        self.freqs=None; self.avg=None; self.peak=None
        self._peak_age=None; self._peak_age_b=None
        self._ds_f=None; self._ds_avg=None; self._ds_pk=None
        self._ds_f_b=None; self._ds_avg_b=None; self._ds_pk_b=None
        self._ds_diff=None; self.peak_b=None
        self.update()

    def resizeEvent(self,e): self._cache=None; self.update()

    def _build_cache(self,W,H):
        from PyQt5.QtGui import QPixmap
        px=QPixmap(W,H); px.fill(QColor(T('bg')))
        p=QPainter(px)
        pl=self.PAD_L; pr=self.PAD_R; pt=self.PAD_T; pb=self.PAD_B
        dh=H-pt-pb; uw=W-pl-pr; ny=min(self.sample_rate/2,20000)
        # dB 그리드
        p.setFont(QFont('Arial',9))
        for db in range(int(self.db_min),int(self.db_max)+1,12):
            y=pt+db_to_y(db,dh,self.db_min,self.db_max)
            if not pt<=y<=H-pb: continue
            is0=(db==0)
            p.setPen(QPen(QColor(T('accent')),1.5 if is0 else 0.7,Qt.SolidLine))
            p.drawLine(pl,y,W-pr,y)
            p.setPen(QColor(T('text_dim')))
            p.drawText(2,y+4,f'{db:+d}')
        # 주파수 수직선 + 레이블
        p.setFont(QFont('Arial',10,QFont.Bold))
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
            p.setPen(QColor(T('text'))); p.drawText(tx,H-5,txt)
        p.end(); self._cache=px

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

    def set_data_b(self,freqs,avg):
        if self.peak_hold:
            if self.peak_b is None or len(self.peak_b)!=len(avg):
                self.peak_b=avg.copy(); self._peak_age_b=np.zeros(len(avg),dtype=np.int32)
            else:
                self._update_peak(self.peak_b, self._peak_age_b, avg)
        ny=self.sample_rate/2
        mask=(freqs>=20)&(freqs<=ny)
        f_sel=freqs[mask]; a_sel=avg[mask]
        if len(f_sel)>self.MAX_POINTS:
            log_f=np.logspace(math.log10(20),math.log10(ny),self.MAX_POINTS)
            a_ds=np.interp(log_f,f_sel,a_sel)
            self._ds_f_b=log_f; self._ds_avg_b=a_ds
            if self.peak_b is not None:
                p_sel=self.peak_b[mask]
                self._ds_pk_b=np.interp(log_f,f_sel,p_sel)
        else:
            self._ds_f_b=f_sel; self._ds_avg_b=a_sel
            self._ds_pk_b=self.peak_b[mask] if self.peak_b is not None else None
        if self.show_diff and self._ds_f is not None and self._ds_avg is not None and self._ds_f_b is not None:
            b_on_a=np.interp(self._ds_f,self._ds_f_b,self._ds_avg_b)
            self._ds_diff=self._ds_avg-b_on_a
        self.update()

    def reset_peak(self):
        self.peak=None; self._ds_pk=None; self._peak_age=None
        self.peak_b=None; self._ds_pk_b=None; self._peak_age_b=None
    def set_peak_hold(self,v):
        self.peak_hold=v
        if not v: self.reset_peak()
    def set_peak_hold_time(self,rate): self.peak_decay_rate_pk=rate
    def set_db_range(self,lo,hi): self._cache=None; self.db_min=lo; self.db_max=hi; self.update()
    def mouseMoveEvent(self,e): self._mx=e.x(); self._my=e.y(); self.update()
    def leaveEvent(self,e): self._mx=-1; self.update()
    def mouseDoubleClickEvent(self,e):
        if e.x()<self.PAD_L and self._ds_avg is not None and len(self._ds_avg)>0:
            valid=self._ds_avg[self._ds_avg>-90]
            if len(valid)==0: return
            peak=float(np.max(valid)); span=self.db_max-self.db_min
            self.db_max=int(math.ceil((peak+12)/12))*12
            self.db_min=self.db_max-span; self.update()
    def wheelEvent(self,e):
        delta=e.angleDelta().y()
        mods=e.modifiers()
        step=1
        if mods & Qt.ControlModifier:  # Ctrl+휠 = 줌
            span=self.db_max-self.db_min
            span=max(20,min(160,span+(-step if delta>0 else step)*2))
            mid=(self.db_max+self.db_min)/2
            self.db_min=mid-span/2; self.db_max=mid+span/2
        else:                          # 휠 = 스크롤
            shift=step if delta<0 else -step
            self.db_min+=shift; self.db_max+=shift
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

        # ★ 빠른 경로 계산 (벡터화)
        if self.scale_log:
            xs = pl + (np.log10(np.maximum(f_arr,1)/20)/math.log10(ny/20))*uw
        else:
            xs = pl + (f_arr/ny)*uw
        ys = pt + np.clip(((self.db_max-a_arr)/(self.db_max-self.db_min)*dh).astype(int),0,dh)

        # 채우기 (채널 A)
        if self.compare_mode:
            top_col=QColor(*CH_A_FILL_TOP); bot_col=QColor(*CH_A_FILL_BOT)
            line_col=QColor(CH_A_LINE); pk_col=QColor(T('peak_line'))
        else:
            top_col=QColor(*bar_top()); bot_col=QColor(*bar_bot())
            line_col=QColor(T('spec_line')); pk_col=QColor(T('peak_line'))

        path=QPainterPath()
        path.moveTo(float(xs[0]),float(H-pb))
        for x,y in zip(xs,ys): path.lineTo(float(x),float(y))
        path.lineTo(float(xs[-1]),float(H-pb)); path.closeSubpath()
        p.fillPath(path,QBrush(top_col))

        # 스펙트럼 선 A
        stroke=QPainterPath()
        stroke.moveTo(float(xs[0]),float(ys[0]))
        for x,y in zip(xs[1:],ys[1:]): stroke.lineTo(float(x),float(y))
        p.setPen(QPen(line_col,2.0)); p.drawPath(stroke)

        # 피크 홀드 A — 메인 그래프보다 1.5dB 이상 높을 때만 표시
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

        # ── 채널 B 오버레이 (compare_mode)
        if self.compare_mode and self._ds_f_b is not None and self._ds_avg_b is not None and len(self._ds_f_b)>=2:
            f_b=self._ds_f_b; a_b=self._ds_avg_b
            if self.scale_log:
                xs_b=pl+(np.log10(np.maximum(f_b,1)/20)/math.log10(ny/20))*uw
            else:
                xs_b=pl+(f_b/ny)*uw
            ys_b=pt+np.clip(((self.db_max-a_b)/(self.db_max-self.db_min)*dh).astype(int),0,dh)

            path_b=QPainterPath()
            path_b.moveTo(float(xs_b[0]),float(H-pb))
            for x,y in zip(xs_b,ys_b): path_b.lineTo(float(x),float(y))
            path_b.lineTo(float(xs_b[-1]),float(H-pb)); path_b.closeSubpath()
            p.fillPath(path_b,QBrush(QColor(*CH_B_FILL_TOP)))

            stroke_b=QPainterPath()
            stroke_b.moveTo(float(xs_b[0]),float(ys_b[0]))
            for x,y in zip(xs_b[1:],ys_b[1:]): stroke_b.lineTo(float(x),float(y))
            p.setPen(QPen(QColor(CH_B_LINE),2.0)); p.drawPath(stroke_b)

            if self.peak_hold and self._ds_pk_b is not None:
                py_b=pt+np.clip(((self.db_max-self._ds_pk_b)/(self.db_max-self.db_min)*dh).astype(int),0,dh)
                vis_b=self._ds_pk_b>self._ds_avg_b+1.5
                if vis_b.any():
                    pk_b=QPainterPath(); in_seg_b=False
                    for i in range(len(xs_b)):
                        if vis_b[i]:
                            if not in_seg_b: pk_b.moveTo(float(xs_b[i]),float(py_b[i])); in_seg_b=True
                            else: pk_b.lineTo(float(xs_b[i]),float(py_b[i]))
                        else: in_seg_b=False
                    p.setPen(QPen(QColor(CH_B_PEAK),2.0)); p.drawPath(pk_b)

            # diff 곡선
            if self.show_diff and self._ds_diff is not None and len(self._ds_diff)==len(f_arr):
                zero_y=pt+db_to_y(0,dh,self.db_min,self.db_max)
                ys_d=pt+np.clip(((self.db_max-self._ds_diff)/(self.db_max-self.db_min)*dh).astype(int),0,dh)
                diff_p=QPainterPath()
                diff_p.moveTo(float(xs[0]),float(ys_d[0]))
                for x,y in zip(xs[1:],ys_d[1:]): diff_p.lineTo(float(x),float(y))
                p.setPen(QPen(QColor(DIFF_LINE),2.0,Qt.DashLine)); p.drawPath(diff_p)
                p.setPen(QPen(QColor(DIFF_LINE).lighter(130),1,Qt.DotLine))
                p.drawLine(pl,zero_y,W-pr,zero_y)

            # 범례 칩
            cx_leg=W-pr-80; cy_leg=H-pb-18
            p.fillRect(cx_leg,cy_leg,18,6,QColor(CH_A_LINE))
            p.setFont(QFont('Arial',9,QFont.Bold)); p.setPen(QColor(CH_A_LINE))
            p.drawText(cx_leg+20,cy_leg+7,'A')
            p.fillRect(cx_leg+34,cy_leg,18,6,QColor(CH_B_LINE))
            p.setPen(QColor(CH_B_LINE)); p.drawText(cx_leg+54,cy_leg+7,'B')

        # 커서
        if pl<=self._mx<=W-pr:
            cx,cy=self._mx,self._my
            p.setPen(QPen(QColor(T('accent')).lighter(80) if _theme=='light' else QColor(0,229,255,70),
                         1,Qt.DashLine))
            p.drawLine(cx,pt,cx,H-pb); p.drawLine(pl,cy,W-pr,cy)
            freq=x_to_freq(cx,pl,uw,ny) if self.scale_log else (cx-pl)/uw*ny
            fs=f'{freq/1000:.2f} kHz' if freq>=1000 else f'{freq:.0f} Hz'
            idx=int(np.clip(np.argmin(np.abs(f_arr-freq)),0,len(a_arr)-1))
            db=float(a_arr[idx])
            if self.compare_mode and self._ds_f_b is not None and self._ds_avg_b is not None:
                idx_b=int(np.clip(np.argmin(np.abs(self._ds_f_b-freq)),0,len(self._ds_avg_b)-1))
                db_b=float(self._ds_avg_b[idx_b])
                draw_info_box(p,W,fs,f'A: {db:.1f}  B: {db_b:.1f} dB')
            else:
                draw_info_box(p,W,fs,f'{db:.1f} dB')
        p.end()

# ───────────────────────────────────────────
#  옥타브 캔버스
# ───────────────────────────────────────────
class OctaveCanvas(QWidget):
    PAD_L=54; PAD_R=10; PAD_T=12; PAD_B=28
    def __init__(self):
        super().__init__()
        self.setMinimumSize(300,150)
        self.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Expanding)
        self.setMouseTracking(True); self.setAttribute(Qt.WA_OpaquePaintEvent,True)
        self.mode='oct3'
        self.smooth={k:np.full(len(v),-96.0) for k,v in BANDS.items()}
        self.peaks ={k:np.full(len(v),-96.0) for k,v in BANDS.items()}
        self.db_min=-96; self.db_max=MAX_DB
        self.peak_hold=True; self.alpha=1.0-SPEED_LEVELS[2][1]; self.decay=0.08
        self.peak_hold_frames=0
        self.peak_decay_rate_pk=1.0
        self._peak_age ={k:np.zeros(len(v),dtype=np.int32) for k,v in BANDS.items()}
        self._peak_age_b={k:np.zeros(len(v),dtype=np.int32) for k,v in BANDS.items()}
        self._cache=None
        self._mx=-1; self._my=-1
        # ── 채널 B
        self.compare_mode=False
        self.smooth_b={k:np.full(len(v),-96.0) for k,v in BANDS.items()}
        self.peaks_b ={k:np.full(len(v),-96.0) for k,v in BANDS.items()}
    def set_mode(self,m):
        self._cache=None
        self.mode=m; self.peaks[m][:]=self.db_min; self.peaks_b[m][:]=self.db_min
        self._peak_age[m][:]=0; self._peak_age_b[m][:]=0; self.update()
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
    def update_data_b(self,mode,values):
        if mode!=self.mode: return
        sm=self.smooth_b[mode]; pk=self.peaks_b[mode]
        vals=np.array(values,dtype=np.float64)
        sm+=(vals-sm)*self.alpha
        if self.peak_hold:
            age=self._peak_age_b[mode]
            mask=sm>pk; pk[mask]=sm[mask]; age[mask]=0; age[~mask]+=1
            pk[age>self.peak_hold_frames]-=self.peak_decay_rate_pk
            np.maximum(pk, self.db_min, out=pk)
        self.update()
    def clear(self):
        for k in self.smooth: self.smooth[k][:]=self.db_min
        for k in self.peaks:  self.peaks[k][:]=self.db_min
        for k in self.smooth_b: self.smooth_b[k][:]=self.db_min
        for k in self.peaks_b:  self.peaks_b[k][:]=self.db_min
        self.update()

    def resizeEvent(self,e): self._cache=None; self.update()

    def _build_cache(self,W,H):
        from PyQt5.QtGui import QPixmap
        px=QPixmap(W,H); px.fill(QColor(T('bg')))
        p=QPainter(px)
        pl=self.PAD_L; pr=self.PAD_R; pt=self.PAD_T; pb=self.PAD_B
        dh=H-pt-pb; uw=W-pl-pr; ny=20000
        p.setFont(QFont('Arial',9))
        for db in range(int(self.db_min),int(self.db_max)+1,12):
            y=pt+db_to_y(db,dh,self.db_min,self.db_max)
            if not pt<=y<=H-pb: continue
            is0=(db==0)
            p.setPen(QPen(QColor(T('accent')),1.5 if is0 else 0.7,Qt.SolidLine))
            p.drawLine(pl,y,W-pr,y)
            p.setPen(QColor(T('text_dim'))); p.drawText(2,y+4,f'{db:+d}')
        p.setFont(QFont('Arial',10,QFont.Bold)); last_x=-999
        for f in FREQ_MARKS:
            if f<20 or f>ny: continue
            fx=freq_to_x(f,pl,uw,ny)
            if not pl<=fx<=W-pr: continue
            p.setPen(QPen(QColor(T('grid')),1,Qt.SolidLine))
            p.drawLine(int(fx),pt,int(fx),H-pb)
            if fx-last_x<36: continue
            last_x=fx
            lf=int(f) if f==int(f) else f
            txt=f'{int(f//1000)}k' if f>=1000 else str(lf)
            tw=p.fontMetrics().horizontalAdvance(txt)
            tx=max(pl,min(int(fx-tw/2),W-pr-tw))
            p.setPen(QColor(T('text'))); p.drawText(tx,H-5,txt)
        p.end(); self._cache=px

    def reset_peak(self):
        for k in self.peaks: self.peaks[k][:]=self.db_min; self._peak_age[k][:]=0
        for k in self.peaks_b: self.peaks_b[k][:]=self.db_min; self._peak_age_b[k][:]=0
    def set_peak_hold(self,v):
        self.peak_hold=v
        if not v: self.reset_peak()
    def set_peak_hold_time(self,rate): self.peak_decay_rate_pk=rate
    def set_db_range(self,lo,hi): self._cache=None; self.db_min=lo; self.db_max=hi; self.update()
    def set_speed(self,a,d): self.alpha=a; self.decay=d
    def mouseMoveEvent(self,e): self._mx=e.x(); self._my=e.y(); self.update()
    def leaveEvent(self,e): self._mx=-1; self.update()
    def mouseDoubleClickEvent(self,e):
        if e.x()<self.PAD_L:
            sm=self.smooth[self.mode]; valid=sm[sm>-90]
            if len(valid)==0: return
            peak=float(np.max(valid)); span=self.db_max-self.db_min
            self.db_max=int(math.ceil((peak+12)/12))*12
            self.db_min=self.db_max-span; self.update()
    def wheelEvent(self,e):
        delta=e.angleDelta().y()
        mods=e.modifiers()
        step=1
        if mods & Qt.ControlModifier:
            span=self.db_max-self.db_min
            span=max(20,min(160,span+(-step if delta>0 else step)*2))
            mid=(self.db_max+self.db_min)/2
            self.db_min=mid-span/2; self.db_max=mid+span/2
        else:
            shift=step if delta<0 else -step
            self.db_min+=shift; self.db_max+=shift
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
        bands=BANDS[self.mode]; sm=self.smooth[self.mode]; pk=self.peaks[self.mode]
        sm_b=self.smooth_b[self.mode]; pk_b=self.peaks_b[self.mode]
        n=len(bands)
        if n==0 or db_range<=0: p.end(); return
        bar_w=uw/n
        gap_r=0.06 if self.mode=='oct24' else 0.08 if self.mode=='oct12' else 0.12
        gap=max(1.0,bar_w*gap_r)
        col_a=QColor(*bar_top()); col_b=QColor(*CH_B_FILL_TOP[:3],160)
        for i in range(n):
            db=float(np.clip(sm[i],self.db_min,self.db_max))
            lp=(db-self.db_min)/db_range; bh=max(2,int(lp*dh))
            if self.compare_mode:
                slot_inner=bar_w-gap
                half_w=max(1,int((slot_inner-1)/2))
                bx_a=int(pl+i*bar_w+gap/2); by_a=pt+dh-bh
                p.fillRect(bx_a,by_a,half_w,bh,col_a)
                if self.peak_hold and pk[i]>sm[i]+1.5 and pk[i]>self.db_min+2:
                    lp2=float(np.clip((pk[i]-self.db_min)/db_range,0,1))
                    py2=pt+dh-max(2,int(lp2*dh))
                    p.fillRect(bx_a,py2-1,half_w,2,QColor(T('peak_line')))
                db_b=float(np.clip(sm_b[i],self.db_min,self.db_max))
                lp_b=(db_b-self.db_min)/db_range; bh_b=max(2,int(lp_b*dh))
                bx_b=bx_a+half_w+1; by_b=pt+dh-bh_b
                p.fillRect(bx_b,by_b,half_w,bh_b,col_b)
                if self.peak_hold and pk_b[i]>sm_b[i]+1.5 and pk_b[i]>self.db_min+2:
                    lp2b=float(np.clip((pk_b[i]-self.db_min)/db_range,0,1))
                    py2b=pt+dh-max(2,int(lp2b*dh))
                    p.fillRect(bx_b,py2b-1,half_w,2,QColor(CH_B_PEAK))
            else:
                bx=int(pl+i*bar_w+gap/2); bw=max(1,int(bar_w-gap)); by=pt+dh-bh
                p.fillRect(bx,by,bw,bh,col_a)
                if self.peak_hold and pk[i]>sm[i]+1.5 and pk[i]>self.db_min+2:
                    lp2=float(np.clip((pk[i]-self.db_min)/db_range,0,1))
                    py2=pt+dh-max(2,int(lp2*dh))
                    p.fillRect(bx,py2-1,bw,2,QColor(T('peak_line')))
        if pl<=self._mx<=W-pr:
            cx,cy=self._mx,self._my
            bi=max(0,min(int((cx-pl)/bar_w),n-1)); fc=bands[bi]
            db2=float(sm[bi])
            bx2=int(pl+bi*bar_w+gap/2); bw2=max(1,int(bar_w-gap))
            p.setPen(QPen(QColor(T('accent')),2))
            p.setBrush(QBrush(QColor(T('accent')).lighter(200) if _theme=='light' else QColor(0,229,255,12)))
            p.drawRect(bx2,pt,bw2,dh)
            fs=f'{fc/1000:.2f} kHz' if fc>=1000 else f'{fc:.0f} Hz'
            if self.compare_mode:
                db2_b=float(sm_b[bi])
                draw_info_box(p,W,fs,f'A:{db2:.1f}  B:{db2_b:.1f} dB')
            else:
                draw_info_box(p,W,fs,f'{db2:.1f} dB')
        p.end()

# ───────────────────────────────────────────
#  VU 미터
# ───────────────────────────────────────────
class VUMeter(QWidget):
    """
    ★ VU 미터는 항상 raw dBFS 기준으로 표시
       캘리브레이션 오프셋은 그래프/수치에만 적용되고 VU 게인에는 영향 없음
    """
    def __init__(self):
        super().__init__()
        self.setFixedWidth(68); self.setAttribute(Qt.WA_OpaquePaintEvent,True)
        self.raw_spl  = -100.0   # dBFS (캘리브 오프셋 미적용)
        self.raw_peak = -100.0   # dBFS
        self.cal_spl  = -100.0   # dBSPL (캘리브 오프셋 적용, 숫자 표시용)
        self.cal_peak = -100.0

    def update_level(self, raw_spl, raw_peak, cal_spl, cal_peak):
        self.raw_spl  = raw_spl;  self.raw_peak  = raw_peak
        self.cal_spl  = cal_spl;  self.cal_peak  = cal_peak
        self.update()

    def paintEvent(self,ev):
        p=QPainter(self); W,H=self.width(),self.height()
        p.fillRect(0,0,W,H,QColor(T('bg2')))
        DB_MIN, DB_RANGE = -60, 60

        # Title: Input / Meter (two lines)
        p.setFont(QFont('Arial',7,QFont.Bold)); p.setPen(QColor(T('text_dim')))
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
        p.setFont(QFont('Arial',10,QFont.Bold))
        c=T('red') if self.raw_spl>-6 else T('yellow') if self.raw_spl>-18 else T('accent')
        p.setPen(QColor(c)); p.drawText(0,y0,W,16,Qt.AlignHCenter,f'{self.cal_spl:.1f}')
        p.setFont(QFont('Arial',8)); p.setPen(QColor(T('text_dim')))
        p.drawText(0,y0+16,W,12,Qt.AlignHCenter,'dB')
        p.setFont(QFont('Arial',8,QFont.Bold)); p.setPen(QColor(T('text_dim')))
        p.drawText(0,y0+32,W,12,Qt.AlignHCenter,'PEAK')
        p.setFont(QFont('Arial',9,QFont.Bold)); p.setPen(QColor(T('yellow')))
        p.drawText(0,y0+46,W,14,Qt.AlignHCenter,f'{self.cal_peak:.1f}')
        p.setFont(QFont('Arial',8,QFont.Bold)); p.setPen(QColor(T('text_dim')))
        p.drawText(0,y0+64,W,12,Qt.AlignHCenter,'CLIP')
        p.fillRect(W//2-13,y0+78,26,12,QColor(T('red') if self.raw_spl>-3 else T('border')))
        p.end()

# ───────────────────────────────────────────
#  캘리브레이션 다이얼로그
# ───────────────────────────────────────────
class CalibDialog(QDialog):
    def __init__(self, current_offset, current_spl_func, parent=None):
        super().__init__(parent)
        self.setWindowTitle('🎙 마이크 캘리브레이션')
        self.setMinimumWidth(420)
        self.setStyleSheet(f'background:{T("bg2")};color:{T("text")};')
        self._get_spl = current_spl_func
        self._measuring = False
        self._meas_samples = []
        layout = QVBoxLayout(self); layout.setSpacing(12); layout.setContentsMargins(16,12,16,12)

        # ── 순서 안내
        steps = QLabel(
            '① 칼리브레이터를 마이크에 연결하세요\n'
            '② 칼리브레이터의 기준값(94 or 114 dBSPL)을 선택하세요\n'
            '③ 칼리브레이터를 켜고 [🎤 레벨 측정] 버튼을 누르세요\n'
            '④ [📐 오프셋 계산] → [OK]'
        )
        steps.setStyleSheet(f'color:{T("text_dim")};font-size:11px;'
                            f'background:{T("panel")};border-radius:8px;padding:10px;')
        steps.setWordWrap(True); layout.addWidget(steps)

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
                border:1px solid {T('accent')}; selection-background-color:rgba(0,150,255,80);
            }}
        """)
        ref_row.addWidget(self.ref_cb); ref_row.addStretch()
        layout.addLayout(ref_row)

        # ── 측정 영역
        meas_box = QGroupBox('현재 마이크 레벨 측정')
        meas_box.setStyleSheet(f'QGroupBox{{border:1px solid {T("border")};border-radius:8px;'
                                f'margin-top:8px;color:{T("text_dim")};font-size:10px;}}'
                                f'QGroupBox::title{{subcontrol-origin:margin;left:10px;}}')
        mb = QVBoxLayout(meas_box); mb.setAlignment(Qt.AlignCenter)

        self.meas_display = QLabel('— dBFS')
        self.meas_display.setStyleSheet(f'color:{T("accent")};font-size:26px;font-weight:bold;font-family:Arial;')
        self.meas_display.setAlignment(Qt.AlignCenter)
        mb.addWidget(self.meas_display)

        self.meas_btn = QPushButton('🎤 레벨 측정 시작  (3초)')
        self.meas_btn.setStyleSheet(f'background:rgba(0,229,255,25);color:{T("accent")};'
                                     f'border:1px solid {T("accent")};padding:6px;border-radius:8px;font-size:12px;')
        self.meas_btn.clicked.connect(self._start_measure)
        mb.addWidget(self.meas_btn)

        # 직접 입력 (스피너 버튼 없음, 가운데 정렬)
        manual_row = QHBoxLayout(); manual_row.addStretch()
        manual_row.addWidget(QLabel('직접 입력(dBFS):'))
        self.meas_spin = QDoubleSpinBox()
        self.meas_spin.setRange(-120, 0); self.meas_spin.setDecimals(1)
        self.meas_spin.setSingleStep(0.1); self.meas_spin.setValue(-26.0)
        self.meas_spin.setStyleSheet(f"""
            QDoubleSpinBox {{
                background:{T("panel")}; color:{T("text")};
                border:1px solid {T("border")}; padding:3px 8px;
                border-radius:6px; min-width:80px;
            }}
            QDoubleSpinBox::up-button   {{ width:0; border:none; }}
            QDoubleSpinBox::down-button {{ width:0; border:none; }}
        """)
        manual_row.addWidget(self.meas_spin); manual_row.addStretch()
        mb.addLayout(manual_row)
        layout.addWidget(meas_box)

        # ── 오프셋 자동 계산
        calc_btn = QPushButton('📐 오프셋 자동 계산')
        calc_btn.setStyleSheet(f'background:rgba(57,255,20,20);color:{T("green")};'
                                f'border:1px solid rgba(57,255,20,100);padding:7px;'
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
        self.offset_spin.setValue(current_offset)
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
        rst.clicked.connect(lambda: (self.offset_spin.setValue(0), self.result_lbl.setText('초기화됨')))
        off_row.addWidget(rst); off_row.addStretch()
        layout.addLayout(off_row)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.setStyleSheet(f'color:{T("text")};')
        btns.accepted.connect(self.accept); btns.rejected.connect(self.reject)
        btns.rejected.connect(lambda: self._meas_timer.stop() if hasattr(self,'_meas_timer') else None)
        layout.addWidget(btns)

        # 측정 타이머
        self._meas_timer = QTimer(self)
        self._meas_timer.timeout.connect(self._sample_level)
        self._meas_count = 0

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
            self.meas_display.setText(f'{avg:.1f} dBFS  ✅')
            self.meas_display.setStyleSheet(f'color:{T("green")};font-size:26px;font-weight:bold;font-family:Arial;')
            self.meas_btn.setText('🎤 레벨 측정 시작  (3초)')
            self.meas_btn.setStyleSheet(f'background:rgba(0,229,255,25);color:{T("accent")};'
                                         f'border:1px solid {T("accent")};padding:6px;border-radius:5px;font-size:12px;')
            self._auto_calc()

    def _auto_calc(self):
        ref_val = 94.0 if self.ref_cb.currentIndex()==0 else 114.0
        meas    = self.meas_spin.value()
        offset  = ref_val - meas
        self.offset_spin.setValue(round(offset, 1))
        self.result_lbl.setText(f'오프셋  {offset:+.1f} dB  →  {meas:.1f} + {offset:.1f} = {ref_val:.0f} dBSPL ✅')

    def get_offset(self): return self.offset_spin.value()

# ───────────────────────────────────────────
#  LEQ 팝업 창
# ───────────────────────────────────────────
class LeqWindow(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent, Qt.Window)
        self.setWindowTitle('📊 Time Average Level (LEQ)')
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
        self.leq_start_btn = QPushButton('▶  Start')
        self.leq_start_btn.setStyleSheet(f'background:rgba(57,255,20,25);color:{T("green")};border:1px solid rgba(57,255,20,100);padding:4px 10px;border-radius:8px;')
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
            val = QLabel('—'); val.setStyleSheet(f'color:{color};font-size:22px;font-weight:bold;font-family:Arial;')
            val.setAlignment(Qt.AlignRight)
            row.addWidget(lbl); row.addWidget(val)
            return row, val

        r1,self.leq_a_lbl   = big_val_row('LEQ(A)', T('accent'))
        r2,self.leq_c_lbl   = big_val_row('LEQ(C)', T('accent2'))
        r3,self.inst_a_lbl  = big_val_row('dBA', T('green'))
        r4,self.inst_c_lbl  = big_val_row('dBC', '#88aacc')
        for r in [r1,r2,r3,r4]: rg_layout.addLayout(r)
        layout.addWidget(result_group)

        # 리셋
        rst = QPushButton('🔄 Reset')
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
            self.leq_start_btn.setText('■  Stop')
            self.leq_start_btn.setStyleSheet(f'background:rgba(255,51,51,25);color:{T("red")};border:1px solid rgba(255,51,51,100);padding:4px 10px;border-radius:8px;')
        else:
            self.leq_start_btn.setText('▶  Start')
            self.leq_start_btn.setStyleSheet(f'background:rgba(57,255,20,25);color:{T("green")};border:1px solid rgba(57,255,20,100);padding:4px 10px;border-radius:8px;')

    def _reset_leq(self):
        self._running=False; self._leq_a_buf.clear(); self._leq_c_buf.clear()
        self._start_time=None
        for lbl in [self.leq_a_lbl,self.leq_c_lbl,self.inst_a_lbl,self.inst_c_lbl]:
            lbl.setText('—')
        self.progress_lbl.setText('Standby')
        self.leq_start_btn.setText('▶  Start')
        self.leq_start_btn.setStyleSheet(f'background:rgba(57,255,20,25);color:{T("green")};border:1px solid rgba(57,255,20,100);padding:4px 10px;border-radius:8px;')

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
                self.leq_start_btn.setText('▶  Start')
                self.progress_lbl.setText(f'✅ Done  LEQ(A)={leq_a:.1f}  LEQ(C)={leq_c:.1f}')

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
                f'  background:{"rgba(0,150,255,70)" if selected else "transparent"};'
                f'  color:{T("accent") if selected else T("text")};'
                f'  border:none; border-radius:7px;'
                f'  padding:6px 16px; font-size:11px; font-weight:{"bold" if selected else "normal"};'
                f'  text-align:left; min-height:26px;'
                f'}}'
                f'QPushButton:hover {{ background:rgba(0,150,255,30); color:{T("text")}; }}'
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


class RoundComboBox(QComboBox):
    def showPopup(self):
        popup = DropdownPopup(self)
        popup.item_selected.connect(self.setCurrentIndex)
        popup.adjustSize()
        w = max(self.width(), popup.sizeHint().width())
        ph = popup.sizeHint().height()
        popup.resize(w, ph)
        # 화면 아래 공간이 부족하면 위로, 충분하면 아래로
        global_top = self.mapToGlobal(QPoint(0, 0))
        screen_bottom = QApplication.primaryScreen().availableGeometry().bottom()
        if global_top.y() + self.height() + ph + 4 > screen_bottom:
            pos = self.mapToGlobal(QPoint(0, -ph - 2))   # 위로 열림
        else:
            pos = self.mapToGlobal(QPoint(0, self.height() + 2))  # 아래로 열림
        popup.move(pos)
        popup.show()

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
    """mag(dB)와 phase(deg) 를 분리 스무딩 → complex 벡터 상쇄 없음 (Smaart 방식)."""
    mask = (freqs >= 18) & (freqs <= 22000)
    f = freqs[mask]; H = H_complex[mask]
    if len(f) < 2:
        z = np.zeros(max(len(f), 1))
        return f[:1], z[:1], z[:1], z[:1], z[:1]
    f_min = max(float(f[0]), 20.0); f_max = min(float(f[-1]), 20000.0)
    f_out = np.logspace(np.log10(f_min), np.log10(f_max), 1200)
    mag_raw = 20 * np.log10(np.maximum(np.abs(H), 1e-10))
    ph_raw  = np.unwrap(np.angle(H)) * 180.0 / np.pi
    if bpo == 0:
        mag_db  = np.interp(f_out, f, mag_raw)
        ph_unwr = np.interp(f_out, f, ph_raw)
    else:
        # 삼각 창 = 직사각형 창 2회 통과 (각 반폭 2^(0.25/bpo))
        half2 = 2 ** (0.25 / bpo)
        mag_db  = _smooth_real(_smooth_real(mag_raw, f, f_out, half2), f_out, f_out, half2)
        ph_unwr = _smooth_real(_smooth_real(ph_raw,  f, f_out, half2), f_out, f_out, half2)
    ph_wrap = (ph_unwr + 180.0) % 360.0 - 180.0
    ph_rad  = ph_unwr * (np.pi / 180.0)
    grp_ms  = -np.gradient(ph_rad, 2 * np.pi * f_out) * 1000.0
    return f_out, mag_db, ph_wrap, ph_unwr, grp_ms

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
    PAD_L=60; PAD_R=15; PAD_T=10; PAD_B=6
    def __init__(self):
        super().__init__()
        self.setMinimumSize(400,110); self.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Expanding)
        self.setMouseTracking(True); self.setAttribute(Qt.WA_OpaquePaintEvent,True)
        self.freqs=None; self.ph_wrap=None; self.ph_unwr=None; self.grp_ms=None
        self.coherence=None; self.coh_blank=0.0
        self.phase_mode=0
        self.ph_min=-150.0; self.ph_max=150.0  # Smaart 기본값: -150~150° (중심 0°)
        self._mx=-1; self._cache=None

    def set_data(self,f,pw,pu,gm,coh=None):
        self.freqs=f; self.ph_wrap=pw; self.ph_unwr=pu; self.grp_ms=gm
        self.coherence=coh
        self.update()  # 배경 캐시 유지 — 커브만 갱신

    def clear(self):
        self.freqs=self.ph_wrap=self.ph_unwr=self.grp_ms=None; self._cache=None; self.update()

    def set_mode(self,idx):
        self.phase_mode=idx
        if idx==0:   self.ph_min,self.ph_max=-150.0,150.0   # Smaart 기본: -150~150° (중심 0°)
        elif idx==1: self.ph_min,self.ph_max=-540.0,540.0
        else:        self.ph_min,self.ph_max=-2.0,30.0
        self._cache=None; self.update()

    def mouseMoveEvent(self,e): self._mx=e.x(); self.update()
    def leaveEvent(self,e): self._mx=-1; self.update()
    def resizeEvent(self,e): self._cache=None; self.update()

    def mouseDoubleClickEvent(self,e):
        if self.phase_mode==0:   self.ph_min,self.ph_max=-150.0,150.0
        elif self.phase_mode==1: self.ph_min,self.ph_max=-540.0,540.0
        else:                    self.ph_min,self.ph_max=-2.0,30.0
        self._cache=None; self.update()

    def wheelEvent(self,e):
        step=1 if e.angleDelta().y()<0 else -1
        if self.phase_mode==0:
            # Wrapped: 30° 단위 pan, 360° 주기 루프 (끝에서 처음으로)
            span=self.ph_max-self.ph_min
            mid=(self.ph_min+self.ph_max)/2+step*30.0
            mid=((mid+180.0)%360.0)-180.0   # -180~180 순환
            self.ph_min=mid-span/2; self.ph_max=mid+span/2
        elif e.modifiers()&Qt.ControlModifier:
            if self.phase_mode==2:
                span=max(4.0,(self.ph_max-self.ph_min)+step*2.0)
            else:
                span=max(60.0,(self.ph_max-self.ph_min)+step*60.0)
                span=min(span,2160.0)   # 최대 ±1080° (6바퀴)
            mid=(self.ph_max+self.ph_min)/2
            self.ph_min=mid-span/2; self.ph_max=mid+span/2
        else:
            d=(self.ph_max-self.ph_min)*0.05*step
            self.ph_min+=d; self.ph_max+=d
            if self.phase_mode==1:   # Unwrapped: 팬 범위 제한
                span=self.ph_max-self.ph_min
                self.ph_min=max(-3600.0,min(self.ph_min,3600.0-span))
                self.ph_max=self.ph_min+span
        self._cache=None; self.update()

    def _build_cache(self,W,H):
        from PyQt5.QtGui import QPixmap
        px=QPixmap(W,H); px.fill(QColor(T('bg')))
        p=QPainter(px)
        p.setRenderHint(QPainter.Antialiasing, True)
        pl=self.PAD_L; pr=self.PAD_R; pt=self.PAD_T; pb=self.PAD_B
        dh=H-pt-pb; uw=W-pl-pr; ny=20000
        rng=self.ph_max-self.ph_min if self.ph_max!=self.ph_min else 1.0
        is_grp=(self.phase_mode==2); unit=' ms' if is_grp else '°'
        p.setFont(QFont('Arial',9))
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
            p.setPen(QPen(QColor(T('accent')),1.5 if is0 else 0.7,Qt.SolidLine if is0 else Qt.DotLine))
            p.drawLine(pl,y,W-pr,y)
            p.setPen(QColor(T('text_dim')))
            lbl=f'{deg}{unit}' if is_grp else f'{int(deg)}°'
            p.drawText(2,y+4,lbl)
        p.setFont(QFont('Arial',9,QFont.Bold)); last_lx=-999
        for f in FREQ_MARKS:
            if f<20 or f>ny: continue
            fx=freq_to_x(f,pl,uw,ny)
            if not pl<=fx<=W-pr: continue
            p.setPen(QPen(QColor(T('grid')),1)); p.drawLine(int(fx),pt,int(fx),H-pb)
            if fx-last_lx<36: continue
            last_lx=fx
            txt=f'{int(f//1000)}k' if f>=1000 else str(int(f))
            tw=p.fontMetrics().horizontalAdvance(txt)
            p.setPen(QColor(T('text_dim'))); p.drawText(max(pl,min(int(fx-tw/2),W-pr-tw)),H-1,txt)
        mode_lbl=['Phase  Wrapped','Phase  Unwrapped','Group Delay'][self.phase_mode]
        p.setFont(QFont('Arial',8,QFont.Bold)); p.setPen(QColor(T('text_dim')))
        p.drawText(pl+4,pt+12,mode_lbl)
        p.end(); self._cache=px

    def _draw_curve(self, p, W, H):
        if self.freqs is None: return
        data=[self.ph_wrap,self.ph_unwr,self.grp_ms][self.phase_mode]
        if data is None: return
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
        coh=self.coherence; cb=self.coh_blank
        path=QPainterPath(); path.moveTo(float(xs[0]),float(ys[0]))
        is_wrap=(self.phase_mode==0); in_path=True
        for i in range(1,len(xs)):
            coh_ok=(coh is None or cb<=0.0 or float(coh[i])>=cb)
            if (is_wrap and abs(data_plot[i]-data_plot[i-1])>270.0) or not coh_ok:
                path.moveTo(float(xs[i]),float(ys[i])); in_path=coh_ok
            elif in_path:
                path.lineTo(float(xs[i]),float(ys[i]))
            else:
                path.moveTo(float(xs[i]),float(ys[i])); in_path=True
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setPen(QPen(QColor('#39ff14'),2.0)); p.setBrush(Qt.NoBrush); p.drawPath(path)

    def paintEvent(self,ev):
        W=self.width(); H=self.height()
        if self._cache is None or self._cache.size()!=self.size():
            self._build_cache(W,H)
        p=QPainter(self); p.drawPixmap(0,0,self._cache)
        self._draw_curve(p,W,H)
        pl=self.PAD_L; pr=self.PAD_R; pt=self.PAD_T; pb=self.PAD_B; uw=W-pl-pr; ny=20000
        if pl<=self._mx<=W-pr and self.freqs is not None:
            data=[self.ph_wrap,self.ph_unwr,self.grp_ms][self.phase_mode]
            if data is not None:
                is_grp=(self.phase_mode==2); unit=' ms' if is_grp else '°'
                cx=self._mx
                p.setPen(QPen(QColor(0,229,255,60),1,Qt.DashLine)); p.drawLine(cx,pt,cx,H-pb)
                freq=x_to_freq(cx,pl,uw,ny)
                idx=int(np.clip(np.argmin(np.abs(self.freqs-freq)),0,len(data)-1))
                fs=f'{freq/1000:.2f}kHz' if freq>=1000 else f'{freq:.0f}Hz'
                if is_grp:
                    vs=f'{data[idx]:.2f}{unit}'
                elif self.phase_mode==0:
                    mid=(self.ph_min+self.ph_max)/2
                    val=data[idx]-360.0*round((data[idx]-mid)/360.0)
                    vs=f'{int(val)}°'
                else:
                    vs=f'{data[idx]:+.1f}{unit}'
                draw_info_box(p,W,fs,vs)
        p.end()

# ───────────────────────────────────────────
#  TF Magnitude + Coherence Canvas
# ───────────────────────────────────────────
class TFMagCanvas(QWidget):
    PAD_L=60; PAD_R=15; PAD_T=10; PAD_B=28
    _COH_COLOR=(255,107,53)
    def __init__(self):
        super().__init__()
        self.setMinimumSize(400,110); self.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Expanding)
        self.setMouseTracking(True); self.setAttribute(Qt.WA_OpaquePaintEvent,True)
        self.setFocusPolicy(Qt.ClickFocus)
        self.freqs=None; self.mag=None; self.coh=None
        self.db_min=-15.0; self.db_max=15.0
        self.coh_blank=0.5
        self._mx=-1; self._cache=None

    def set_data(self,f,m,coh=None):
        self.freqs=f; self.mag=m; self.coh=coh; self._cache=None; self.update()

    def clear(self): self.freqs=self.mag=self.coh=None; self._cache=None; self.update()
    def mouseMoveEvent(self,e): self._mx=e.x(); self.update()
    def leaveEvent(self,e): self._mx=-1; self.update()
    def resizeEvent(self,e): self._cache=None; self.update()

    def mouseDoubleClickEvent(self,e):
        if self.mag is not None and len(self.mag) > 0:
            lo = float(np.nanmin(self.mag)); hi = float(np.nanmax(self.mag))
            pad = max((hi - lo) * 0.15, 3.0)
            self.db_min = lo - pad; self.db_max = hi + pad
            self._cache=None; self.update()

    def mousePressEvent(self,e):
        self.setFocus(); super().mousePressEvent(e)

    def keyPressEvent(self,e):
        if e.key()==Qt.Key_Up:
            self.db_min+=1; self.db_max+=1; self._cache=None; self.update()
        elif e.key()==Qt.Key_Down:
            self.db_min-=1; self.db_max-=1; self._cache=None; self.update()
        else:
            super().keyPressEvent(e)

    def wheelEvent(self,e):
        step=1 if e.angleDelta().y()<0 else -1
        if e.modifiers()&Qt.ControlModifier:
            span=max(6,min(120,(self.db_max-self.db_min)+step*3))
            mid=(self.db_max+self.db_min)/2
            self.db_min=mid-span/2; self.db_max=mid+span/2
        else:
            self.db_min+=step; self.db_max+=step
        self._cache=None; self.update()

    def _build_cache(self,W,H):
        from PyQt5.QtGui import QPixmap
        px=QPixmap(W,H); px.fill(QColor(T('bg')))
        p=QPainter(px)
        p.setRenderHint(QPainter.Antialiasing, True)
        pl=self.PAD_L; pr=self.PAD_R; pt=self.PAD_T; pb=self.PAD_B
        dh=H-pt-pb; uw=W-pl-pr; ny=20000
        rng=self.db_max-self.db_min if self.db_max!=self.db_min else 1.0
        step_db=3 if rng<=24 else 6 if rng<=48 else 12
        p.setFont(QFont('Arial',9))
        for db in range(int(self.db_min)-step_db,int(self.db_max)+step_db+1,step_db):
            if db<self.db_min or db>self.db_max: continue
            y=int(pt+(self.db_max-db)/rng*dh)
            if not pt<=y<=H-pb: continue
            is0=(db==0)
            p.setPen(QPen(QColor(T('accent')),1.5 if is0 else 0.7,Qt.SolidLine if is0 else Qt.DotLine))
            p.drawLine(pl,y,W-pr,y)
            p.setPen(QColor(T('text_dim'))); p.drawText(2,y+4,f'{db:+d}')
        p.setFont(QFont('Arial',9,QFont.Bold)); last_lx=-999
        for f in FREQ_MARKS:
            if f<20 or f>ny: continue
            fx=freq_to_x(f,pl,uw,ny)
            if not pl<=fx<=W-pr: continue
            p.setPen(QPen(QColor(T('grid')),1)); p.drawLine(int(fx),pt,int(fx),H-pb)
            if fx-last_lx<36: continue
            last_lx=fx
            txt=f'{int(f//1000)}k' if f>=1000 else str(int(f))
            tw=p.fontMetrics().horizontalAdvance(txt)
            p.setPen(QColor(T('text'))); p.drawText(max(pl,min(int(fx-tw/2),W-pr-tw)),H-5,txt)
        p.setFont(QFont('Arial',8,QFont.Bold)); p.setPen(QColor(T('text_dim')))
        p.drawText(pl+4,pt+12,'Magnitude  +  Coherence')
        if self.freqs is not None and self.mag is not None and len(self.freqs)>=2:
            f_arr=self.freqs; m_arr=self.mag
            xs=(pl+(np.log10(np.maximum(f_arr,1)/20)/math.log10(ny/20))*uw).astype(float)
            ys_m=(pt+np.clip((self.db_max-m_arr)/rng*dh,0,dh)).astype(float)
            if self.coh is not None and len(self.coh)==len(f_arr):
                cr,cg,cb_=self._COH_COLOR
                for i in range(len(xs)-1):
                    cv=float(self.coh[i])
                    alpha=255 if cv>=self.coh_blank else int(30+225*(cv/max(self.coh_blank,0.01)))
                    c=QColor(T('accent')); c.setAlpha(alpha)
                    p.setPen(QPen(c,2.0)); p.drawLine(int(xs[i]),int(ys_m[i]),int(xs[i+1]),int(ys_m[i+1]))
            else:
                path=QPainterPath(); path.moveTo(xs[0],ys_m[0])
                for x,y in zip(xs[1:],ys_m[1:]): path.lineTo(x,y)
                p.setPen(QPen(QColor(T('accent')),2.0)); p.setBrush(Qt.NoBrush); p.drawPath(path)
            if self.coh is not None and len(self.coh)==len(f_arr):
                coh_h=dh*0.25; cr,cg,cb_=self._COH_COLOR
                ys_c=(pt+np.clip((1.0-self.coh)*coh_h,0,coh_h)).astype(float)
                path2=QPainterPath(); path2.moveTo(xs[0],ys_c[0])
                for x,y in zip(xs[1:],ys_c[1:]): path2.lineTo(x,y)
                p.setPen(QPen(QColor(cr,cg,cb_,210),1.4)); p.setBrush(Qt.NoBrush); p.drawPath(path2)
                p.setFont(QFont('Arial',7)); p.setPen(QColor(cr,cg,cb_,180))
                p.drawText(pl+4,int(pt+coh_h+3),'γ²')
        p.end(); self._cache=px

    def paintEvent(self,ev):
        W=self.width(); H=self.height()
        if self._cache is None or self._cache.size()!=self.size():
            self._build_cache(W,H)
        p=QPainter(self); p.drawPixmap(0,0,self._cache)
        pl=self.PAD_L; pr=self.PAD_R; pt=self.PAD_T; pb=self.PAD_B; uw=W-pl-pr; ny=20000
        if pl<=self._mx<=W-pr and self.freqs is not None and self.mag is not None:
            cx=self._mx
            p.setPen(QPen(QColor(0,229,255,60),1,Qt.DashLine)); p.drawLine(cx,pt,cx,H-pb)
            freq=x_to_freq(cx,pl,uw,ny)
            idx=int(np.clip(np.argmin(np.abs(self.freqs-freq)),0,len(self.mag)-1))
            fs=f'{freq/1000:.2f}kHz' if freq>=1000 else f'{freq:.0f}Hz'
            vs=f'{self.mag[idx]:+.1f} dB'
            if self.coh is not None and len(self.coh)==len(self.freqs):
                vs+=f'  γ²={self.coh[idx]:.2f}'
            draw_info_box(p,W,fs,vs)
        p.end()

# ───────────────────────────────────────────
#  소형 VU 미터 (TF 창 전용)
# ───────────────────────────────────────────
class _MiniVU(QWidget):
    def __init__(self):
        super().__init__(); self.setFixedSize(72,82)
        self._db=-80.0; self._pk=-80.0; self._pk_hold=0

    def set_rms(self,db):
        self._db=db; self._pk_hold+=1
        if db>self._pk or self._pk_hold>40: self._pk=db; self._pk_hold=0
        self.update()

    def paintEvent(self,ev):
        p=QPainter(self); W=self.width(); H=self.height()
        p.fillRect(0,0,W,H,QColor(T('bg')))
        DB_MIN=-60.0; DB_MAX=0.0; rng=DB_MAX-DB_MIN
        bx=10; bw=W-20; by=4; bh=H-22
        p.setPen(Qt.NoPen); p.setBrush(QBrush(QColor(T('bg2'))))
        p.drawRoundedRect(bx,by,bw,bh,3,3)
        fill=max(0.0,min(1.0,(self._db-DB_MIN)/rng))
        fh=int(bh*fill)
        if fh>0:
            fy=by+bh-fh
            c=T('red') if self._db>-6 else T('yellow') if self._db>-18 else T('accent')
            g=QLinearGradient(0,fy,0,by+bh)
            g.setColorAt(0,QColor(T('accent'))); g.setColorAt(1,QColor(c))
            p.setBrush(QBrush(g)); p.drawRect(bx,fy,bw,fh)
        pk=max(0.0,min(1.0,(self._pk-DB_MIN)/rng))
        py_=int(by+bh*(1.0-pk))
        p.setPen(QPen(QColor(T('yellow')),1)); p.drawLine(bx,py_,bx+bw,py_)
        c2=T('red') if self._db>-6 else T('yellow') if self._db>-18 else T('accent')
        p.setFont(QFont('Arial',9,QFont.Bold)); p.setPen(QColor(c2))
        p.drawText(0,H-18,W,14,Qt.AlignHCenter,f'{self._db:.0f}')
        p.setFont(QFont('Arial',7)); p.setPen(QColor(T('text_dim')))
        p.drawText(0,H-5,W,12,Qt.AlignHCenter,'dBFS')
        p.end()

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
    PAD_L = 60; PAD_R = 15; PAD_T = 10; PAD_B = 20

    def __init__(self):
        super().__init__()
        self.setMinimumSize(400, 80)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMouseTracking(True); self.setAttribute(Qt.WA_OpaquePaintEvent, True)
        self.t_ms = None; self.etc_db = None; self.h_raw = None
        self.peak_ms = 0.0
        self.t_min = 0.0; self.t_max = 30.0
        self.db_min = -60.0; self.db_max = 0.0
        self.ir_mode = 0   # 0=Lin  1=ETC  2=Log
        self._mx = -1
        self._cache = None

    def set_data(self, t_ms, h):
        self.t_ms = t_ms
        self.h_raw = h.copy()
        etc = _hilbert_env(h)
        peak_val = max(float(np.max(etc)), 1e-10)
        pk_idx = int(np.argmax(etc))
        self.peak_ms = float(t_ms[pk_idx])
        self.etc_db = 20 * np.log10(np.maximum(etc / peak_val, 1e-10))
        # peak 가 뷰 중앙 60% 범위를 벗어나면 자동 재조정 (딜레이 적용 시 음수 허용)
        span = max(self.t_max - self.t_min, 10.0)
        rel = (self.peak_ms - self.t_min) / span   # 0=왼쪽끝, 1=오른쪽끝
        if not (0.2 <= rel <= 0.8):
            half = span / 2.0
            self.t_min = self.peak_ms - half
            self.t_max = self.t_min + span
        self._cache = None; self.update()

    def set_mode(self, idx): self.ir_mode = idx; self._cache = None; self.update()

    def clear(self):
        self.t_ms = self.etc_db = self.h_raw = None; self._cache = None; self.update()

    def mouseMoveEvent(self, e): self._mx = e.x(); self.update()
    def leaveEvent(self, e): self._mx = -1; self.update()
    def resizeEvent(self, ev): self._cache = None; self.update()

    def wheelEvent(self, e):
        step = 1 if e.angleDelta().y() < 0 else -1
        span = max(self.t_max - self.t_min, 1.0)
        if e.modifiers() & Qt.ControlModifier:
            span = max(5.0, span + step * span * 0.12)
            mid = (self.t_max + self.t_min) / 2
            self.t_min = max(0.0, mid - span / 2)
            self.t_max = self.t_min + span
        else:
            d = span * 0.06 * step
            self.t_min = max(0.0, self.t_min + d)
            self.t_max = self.t_min + span
        self._cache = None; self.update()

    def _build_cache(self, W, H):
        from PyQt5.QtGui import QPixmap
        pix = QPixmap(W, H); pix.fill(QColor(T('bg')))
        p = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing, True)
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
                p.setPen(QColor(T('text_dim'))); p.setFont(QFont('Arial', 9))
                lbl = f'{t:.0f}ms'; tw = p.fontMetrics().horizontalAdvance(lbl)
                p.drawText(x - tw // 2, H - 2, lbl)
            t += step_ms

        if self.ir_mode == 0:  # ── Lin ───────────────────────────────────
            p.setFont(QFont('Arial', 9))
            for amp in [1.0, 0.5, 0.0, -0.5, -1.0]:
                y = int(pt + (1.0 - amp) / 2.0 * dh)
                if not pt <= y <= H - pb: continue
                is0 = (amp == 0.0)
                p.setPen(QPen(QColor(T('accent')), 1.5 if is0 else 0.7,
                             Qt.SolidLine if is0 else Qt.DotLine))
                p.drawLine(pl, y, W - pr, y)
                p.setPen(QColor(T('text_dim'))); p.drawText(2, y + 4, f'{amp:+.1f}')
            p.setFont(QFont('Arial', 9, QFont.Bold)); p.setPen(QColor(T('text_dim')))
            p.drawText(pl + 4, pt + 12, 'Live IR  (Linear)')
            if self.t_ms is not None and self.h_raw is not None and len(self.t_ms) >= 2:
                peak_lin = max(float(np.max(np.abs(self.h_raw))), 1e-10)
                t_arr = self.t_ms; h_norm = self.h_raw / peak_lin
                mask = (t_arr >= self.t_min) & (t_arr <= self.t_max)
                if np.any(mask):
                    t_v = t_arr[mask]; h_v = h_norm[mask]
                    if len(t_v) > 1200:
                        ids = np.linspace(0, len(t_v) - 1, 1200, dtype=int)
                        t_v = t_v[ids]; h_v = h_v[ids]
                    xs = (pl + (t_v - self.t_min) / t_range * uw).astype(float)
                    ys = (pt + np.clip((1.0 - h_v) / 2.0 * dh, 0, dh)).astype(float)
                    lpath = QPainterPath(); lpath.moveTo(xs[0], ys[0])
                    for x, y in zip(xs[1:], ys[1:]): lpath.lineTo(x, y)
                    lc = QColor(T('accent')); lc.setAlpha(230)
                    p.setPen(QPen(lc, 2.0)); p.setBrush(Qt.NoBrush); p.drawPath(lpath)
                if self.t_min <= self.peak_ms <= self.t_max:
                    pkx = int(pl + (self.peak_ms - self.t_min) / t_range * uw)
                    p.setPen(QPen(QColor(T('accent2')), 2.0, Qt.DashLine))
                    p.drawLine(pkx, pt, pkx, H - pb)
                    p.setFont(QFont('Arial', 8, QFont.Bold)); p.setPen(QColor(T('accent2')))
                    p.drawText(pkx + 4, pt + 12, f'▶ {self.peak_ms:.1f} ms')

        else:  # ── ETC (1) or Log (2) ─────────────────────────────────────
            db_range = max(self.db_max - self.db_min, 1.0)
            p.setFont(QFont('Arial', 8))
            for db in range(int(self.db_min), int(self.db_max) + 1, 10):
                if not self.db_min <= db <= self.db_max: continue
                y = int(pt + (self.db_max - db) / db_range * dh)
                if not pt <= y <= H - pb: continue
                is0 = (db == 0)
                p.setPen(QPen(QColor(T('accent')), 1.3 if is0 else 0.6,
                             Qt.SolidLine if is0 else Qt.DotLine))
                p.drawLine(pl, y, W - pr, y)
                p.setPen(QColor(T('text_dim'))); p.drawText(2, y + 4, f'{db:+d}')
            lbl_text = 'Live IR  (ETC)' if self.ir_mode == 1 else 'Live IR  (Log)'
            p.setFont(QFont('Arial', 8, QFont.Bold)); p.setPen(QColor(T('text_dim')))
            p.drawText(pl + 4, pt + 12, lbl_text)

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
                        if len(t_v) > 600:
                            ids = np.linspace(0, len(t_v) - 1, 600, dtype=int)
                            t_v = t_v[ids]; db_v = db_v[ids]
                        xs = (pl + (t_v - self.t_min) / t_range * uw).astype(float)
                        ys = (pt + np.clip((self.db_max - db_v) / db_range * dh, 0, dh)).astype(float)
                        if self.ir_mode == 1:  # ETC — fill + line
                            fp = QPainterPath()
                            fp.moveTo(xs[0], float(H - pb)); fp.lineTo(xs[0], ys[0])
                            for x, y in zip(xs[1:], ys[1:]): fp.lineTo(x, y)
                            fp.lineTo(xs[-1], float(H - pb)); fp.closeSubpath()
                            g = QLinearGradient(0, pt, 0, H - pb)
                            ac = QColor(T('accent')); ac.setAlpha(55)
                            ac2 = QColor(T('accent')); ac2.setAlpha(5)
                            g.setColorAt(0, ac); g.setColorAt(1, ac2)
                            p.setBrush(QBrush(g)); p.setPen(Qt.NoPen); p.drawPath(fp)
                            lp = QPainterPath(); lp.moveTo(xs[0], ys[0])
                            for x, y in zip(xs[1:], ys[1:]): lp.lineTo(x, y)
                            lc = QColor(T('accent')); lc.setAlpha(230)
                            p.setPen(QPen(lc, 1.6)); p.setBrush(Qt.NoBrush); p.drawPath(lp)
                        else:  # Log — line only
                            lp = QPainterPath(); lp.moveTo(xs[0], ys[0])
                            for x, y in zip(xs[1:], ys[1:]): lp.lineTo(x, y)
                            lc = QColor(T('accent')); lc.setAlpha(200)
                            p.setPen(QPen(lc, 1.2)); p.setBrush(Qt.NoBrush); p.drawPath(lp)
                    if self.t_min <= self.peak_ms <= self.t_max:
                        pkx = int(pl + (self.peak_ms - self.t_min) / t_range * uw)
                        p.setPen(QPen(QColor(T('accent2')), 2.0, Qt.DashLine))
                        p.drawLine(pkx, pt, pkx, H - pb)
                        p.setFont(QFont('Arial', 8, QFont.Bold)); p.setPen(QColor(T('accent2')))
                        p.drawText(pkx + 4, pt + 12, f'▶ {self.peak_ms:.1f} ms')
        p.end()
        self._cache = pix

    def paintEvent(self, ev):
        W = self.width(); H = self.height()
        if self._cache is None or self._cache.size() != self.size():
            self._build_cache(W, H)
        p = QPainter(self); p.drawPixmap(0, 0, self._cache)
        pl = self.PAD_L; pr = self.PAD_R; pt = self.PAD_T; pb = self.PAD_B; uw = W - pl - pr
        if pl <= self._mx <= W - pr and self.t_ms is not None:
            cx = self._mx; t_range = max(self.t_max - self.t_min, 1.0)
            p.setPen(QPen(QColor(0, 229, 255, 60), 1, Qt.DashLine))
            p.drawLine(cx, pt, cx, H - pb)
            t_cur = self.t_min + (cx - pl) / uw * t_range
            t_arr = self.t_ms
            if self.ir_mode == 0 and self.h_raw is not None:
                pk = max(float(np.max(np.abs(self.h_raw))), 1e-10)
                idx = int(np.clip(np.argmin(np.abs(t_arr - t_cur)), 0, len(self.h_raw) - 1))
                draw_info_box(p, W, f'{t_cur:.1f} ms', f'{self.h_raw[idx]/pk:+.3f}')
            elif self.ir_mode == 1 and self.etc_db is not None:
                idx = int(np.clip(np.argmin(np.abs(t_arr - t_cur)), 0, len(self.etc_db) - 1))
                draw_info_box(p, W, f'{t_cur:.1f} ms', f'{self.etc_db[idx]:+.1f} dB')
            elif self.ir_mode == 2 and self.h_raw is not None:
                pk = max(float(np.max(np.abs(self.h_raw))), 1e-10)
                idx = int(np.clip(np.argmin(np.abs(t_arr - t_cur)), 0, len(self.h_raw) - 1))
                db_val = 20 * math.log10(max(abs(float(self.h_raw[idx])) / pk, 1e-10))
                draw_info_box(p, W, f'{t_cur:.1f} ms', f'{db_val:+.1f} dB')
        p.end()


# ───────────────────────────────────────────
#  Internal Loopback 전용 Duplex 스트림 스레드
# ───────────────────────────────────────────
class TFDuplexThread(QThread):
    """출력(핑크노이즈)과 입력(마이크)을 단일 CoreAudio Duplex 스트림으로 처리.
    별도 스트림 2개로 인한 xrun/드롭아웃을 원천 제거."""
    frame_ready  = pyqtSignal(object, object)   # (ref_buf, meas_buf) — 단일 이벤트
    error_signal = pyqtSignal(str)

    def __init__(self, in_dev, out_dev, sample_rate, fft_size, pink_buf, sig_level, n_out=2):
        super().__init__()
        self.in_dev = in_dev; self.out_dev = out_dev
        self.sample_rate = sample_rate; self.fft_size = fft_size
        self.pink_buf = pink_buf; self.sig_level = sig_level
        self.n_out = n_out; self.running = False

    def run(self):
        self.running = True
        blocksize = min(self.fft_size // 4, 2048)
        ref_buf  = np.zeros(self.fft_size, dtype=np.float32)
        meas_buf = np.zeros(self.fft_size, dtype=np.float32)
        out_blk  = np.zeros(blocksize, dtype=np.float32)   # 사전 할당 — 콜백 내 메모리 할당 금지
        pos_r = [0]
        pb = self.pink_buf; pn = len(pb); lvl = self.sig_level

        def cb(indata, outdata, frames, ti, status):
            if status: _alog.warning(f'TFDuplex xrun/status: {status}')
            if not self.running: return
            pp = pos_r[0]; rem = frames; op = 0
            while rem > 0:
                av = pn - pp; tk = min(rem, av)
                out_blk[op:op+tk] = pb[pp:pp+tk] * lvl; op += tk; pp = (pp+tk) % pn; rem -= tk
            pos_r[0] = pp
            for ch in range(outdata.shape[1]): outdata[:frames, ch] = out_blk[:frames]
            ref_buf[:-frames]  = ref_buf[frames:];  ref_buf[-frames:]  = out_blk[:frames]
            meas_buf[:-frames] = meas_buf[frames:]; meas_buf[-frames:] = indata[:frames, 0]
            self.frame_ready.emit(ref_buf.copy(), meas_buf.copy())

        _alog.debug(f'TFDuplexThread.run() opening sd.Stream  in={self.in_dev} out={self.out_dev} sr={self.sample_rate} bs={blocksize}')
        try:
            with sd.Stream(device=(self.in_dev, self.out_dev),
                           samplerate=self.sample_rate,
                           channels=(1, self.n_out),
                           blocksize=blocksize, dtype='float32',
                           callback=cb, latency='high') as stream:
                _alog.debug(f'TFDuplexThread sd.Stream opened OK  latency={stream.latency}')
                while self.running: self.msleep(10)
        except Exception as e:
            _alog.error(f'TFDuplexThread sd.Stream FAILED: {e}')
            self.error_signal.emit(str(e))

    def stop(self):
        self.running = False; self.wait(4000)


# ───────────────────────────────────────────
#  Transfer Function 창
# ───────────────────────────────────────────
class TransferFunctionWindow(QWidget):
    _find_result_sig = pyqtSignal(float)   # 백그라운드 xcorr 결과 → 메인 스레드

    def __init__(self, parent=None, settings=None, embedded=False):
        if embedded:
            super().__init__(parent)
        else:
            super().__init__(parent, Qt.Window)
            self.setWindowTitle('WAYAUDIO — Transfer Function')
            self.setMinimumSize(1020, 570)
        self._settings = settings or {}
        self.sample_rate = 48000; self.fft_size = 16384
        self.smooth_bpo = 3; self.averaging_sec = 2.0
        self.delay_ms = 0.0; self.phase_mode = 0; self.coh_blank = 0.5
        self._mutex = QMutex()
        self._ref_thread = None; self._meas_thread = None; self._sync_thread = None
        self._last_ref_fft = None; self._last_meas_fft = None
        self._last_ref_rms = 0.0; self._last_meas_rms = 0.0
        self._cross_acc = None; self._auto_acc_x = None
        self._auto_acc_y = None; self._n_avg = 0
        self._avg_target = 23; self._running = False
        self._sig_stream = None; self._duplex_thread = None; self._sig_lvl_ref = None
        import threading as _thr
        self._int_ref_buf = np.zeros(131072, dtype=np.float32)  # 32768×4, 순환 버퍼
        self._int_ref_pos = [0]   # 뮤터블 컨테이너, SigGen 콜백과 공유
        self._int_ref_lock = _thr.Lock()
        self._pink_buf = _gen_pink_noise(self.sample_rate * 2)
        self._sig_level_lin = 10 ** (-20 / 20)
        self._build_ui(); self._load_devices()
        self._find_result_sig.connect(self._apply_find_result)
        self._timer = QTimer(self); self._timer.timeout.connect(self._render); self._timer.start(60)

    # ── UI ──────────────────────────────────
    def _build_ui(self):
        from PyQt5.QtWidgets import QDoubleSpinBox, QSlider
        root = QVBoxLayout(self); root.setSpacing(0); root.setContentsMargins(0,0,0,0)

        # 헤더
        hdr = QWidget(); hdr.setFixedHeight(40)
        hdr.setStyleSheet(f'background:{T("bg2")};')
        hl = QHBoxLayout(hdr); hl.setContentsMargins(16,0,16,0)
        logo = QLabel()
        logo.setTextFormat(Qt.RichText)
        logo.setText(f'<span style="font-size:14px;font-weight:700;color:{T("accent")};'
                     f'letter-spacing:2px;">WAYAUDIO</span>'
                     f'&nbsp;&nbsp;<span style="font-size:11px;color:{T("text_dim")};">'
                     f'Transfer Function</span>')
        hl.addWidget(logo); hl.addStretch()
        self.status_lbl = QLabel('● Standby')
        self.status_lbl.setStyleSheet(f'color:{T("text_dim")};font-size:11px;')
        hl.addWidget(self.status_lbl)
        self.avg_lbl = QLabel('')
        self.avg_lbl.setStyleSheet(f'color:{T("text_dim")};font-size:10px;margin-left:14px;')
        hl.addWidget(self.avg_lbl)
        root.addWidget(hdr)

        # 바디 (캔버스 + 우측 패널)
        body = QWidget(); bl = QHBoxLayout(body); bl.setSpacing(0); bl.setContentsMargins(0,0,0,0)

        cvs_w = QSplitter(Qt.Vertical)
        cvs_w.setHandleWidth(5)
        cvs_w.setStyleSheet(
            'QSplitter::handle{background:#2a2a2a;border-top:1px solid #444;}'
            'QSplitter::handle:hover{background:#3a3a3a;}'
        )
        self.ir_cvs = TFIRCanvas()
        self.phase_cvs = TFPhaseCanvas(); self.mag_cvs = TFMagCanvas()
        cvs_w.addWidget(self.ir_cvs)
        cvs_w.addWidget(self.phase_cvs); cvs_w.addWidget(self.mag_cvs)
        cvs_w.setCollapsible(0, False); cvs_w.setCollapsible(1, False); cvs_w.setCollapsible(2, False)
        cvs_w.setSizes([200, 200, 300])
        bl.addWidget(cvs_w, 1)

        # 우측 패널
        bss = (f'QGroupBox{{border:1px solid {T("border")};border-radius:6px;margin-top:8px;'
               f'font-size:9px;color:{T("text_dim")};padding-top:4px;}}'
               f'QGroupBox::title{{subcontrol-origin:margin;left:8px;padding:0 4px;}}')
        rp = QWidget(); rp.setFixedWidth(192)
        rp.setStyleSheet(f'background:{T("bg2")};border-left:1px solid {T("border")};')
        rl = QVBoxLayout(rp); rl.setContentsMargins(10,10,10,10); rl.setSpacing(8)

        # 신호 발생기
        sg = QGroupBox('Signal Generator'); sg.setStyleSheet(bss)
        sgl = QVBoxLayout(sg); sgl.setSpacing(5); sgl.setContentsMargins(8,14,8,8)
        tr = QHBoxLayout(); tr.setSpacing(4)
        self.sig_pink_btn = QPushButton('Pink'); self.sig_pink_btn.setCheckable(True)
        self.sig_pink_btn.setChecked(True); self.sig_pink_btn.setFixedWidth(54)
        self.sig_white_btn = QPushButton('White'); self.sig_white_btn.setCheckable(True)
        self.sig_white_btn.setFixedWidth(54)
        self.sig_pink_btn.clicked.connect(lambda: (self.sig_pink_btn.setChecked(True), self.sig_white_btn.setChecked(False)))
        self.sig_white_btn.clicked.connect(lambda: (self.sig_white_btn.setChecked(True), self.sig_pink_btn.setChecked(False)))
        tr.addWidget(self.sig_pink_btn); tr.addWidget(self.sig_white_btn); tr.addStretch(); sgl.addLayout(tr)
        lr = QHBoxLayout()
        lr.addWidget(QLabel('Level:'))
        self.sig_lvl_cb = RoundComboBox()
        self.sig_lvl_cb.addItems(['-40','-30','-20','-10','-6','-3 dBFS'])
        self.sig_lvl_cb.setCurrentIndex(2); self.sig_lvl_cb.currentIndexChanged.connect(self._sig_level_changed)
        lr.addWidget(self.sig_lvl_cb); sgl.addLayout(lr)
        or_ = QHBoxLayout()
        or_.addWidget(QLabel('Out:'))
        self.sig_out_cb = RoundComboBox(); self.sig_out_cb.setMinimumWidth(110)
        or_.addWidget(self.sig_out_cb); sgl.addLayout(or_)
        self.sig_on_btn = QPushButton('▶  Play'); self.sig_on_btn.setCheckable(True)
        self.sig_on_btn.setStyleSheet(f'background:{T("panel")};color:{T("text_dim")};'
                                       f'border:1px solid {T("border")};padding:4px;border-radius:6px;font-weight:bold;')
        self.sig_on_btn.clicked.connect(self._toggle_sig_gen); sgl.addWidget(self.sig_on_btn)
        rl.addWidget(sg)

        # 입력 장치
        dv = QGroupBox('Input Devices'); dv.setStyleSheet(bss)
        dvl = QVBoxLayout(dv); dvl.setSpacing(4); dvl.setContentsMargins(8,14,8,8)
        dvl.addWidget(QLabel('📥 Reference:'))
        self.ref_cb = RoundComboBox(); self.ref_cb.setMinimumWidth(130)
        self.ref_ch_cb = RoundComboBox(); self.ref_ch_cb.setMinimumWidth(44)
        rr_ = QHBoxLayout(); rr_.setSpacing(4)
        rr_.addWidget(self.ref_cb, 1); rr_.addWidget(self.ref_ch_cb); dvl.addLayout(rr_)
        dvl.addWidget(QLabel('📤 Measurement:'))
        self.meas_cb = RoundComboBox(); self.meas_cb.setMinimumWidth(130)
        self.meas_ch_cb = RoundComboBox(); self.meas_ch_cb.setMinimumWidth(44)
        mr_ = QHBoxLayout(); mr_.setSpacing(4)
        mr_.addWidget(self.meas_cb, 1); mr_.addWidget(self.meas_ch_cb); dvl.addLayout(mr_)
        self.ref_cb.currentIndexChanged.connect(self._ref_device_changed)
        self.meas_cb.currentIndexChanged.connect(self._meas_device_changed)
        rl.addWidget(dv)

        # VU 미터
        vu = QGroupBox('Input Levels'); vu.setStyleSheet(bss)
        vul = QHBoxLayout(vu); vul.setContentsMargins(8,14,8,8); vul.setSpacing(6)
        self._vu_ref = _MiniVU(); self._vu_meas = _MiniVU()
        for label, w in [('Ref', self._vu_ref), ('Meas', self._vu_meas)]:
            col = QVBoxLayout(); lbl_ = QLabel(label)
            lbl_.setStyleSheet(f'color:{T("text_dim")};font-size:9px;')
            col.addWidget(lbl_, 0, Qt.AlignHCenter); col.addWidget(w); vul.addLayout(col)
        rl.addWidget(vu)
        rl.addStretch(); bl.addWidget(rp)
        root.addWidget(body, 1)

        # 하단 툴바
        tb = QWidget(); tb.setFixedHeight(40)
        tb.setStyleSheet(f'background:{T("bg2")};border-top:1px solid {T("border")};')
        tl = QHBoxLayout(tb); tl.setContentsMargins(12,3,12,3); tl.setSpacing(5)

        def _vs():
            f=QFrame(); f.setFrameShape(QFrame.VLine); f.setStyleSheet(f'color:{T("border")};'); return f
        def _lb(t):
            l=QLabel(t); l.setStyleSheet(f'color:{T("text_dim")};font-size:11px;'); return l

        self.start_btn = QPushButton('▶  Start'); self.start_btn.setFixedWidth(82)
        self.start_btn.setStyleSheet(f'background:rgba(57,255,20,25);color:{T("green")};'
                                      f'border:1px solid rgba(57,255,20,100);padding:3px 10px;border-radius:6px;font-weight:bold;')
        self.start_btn.clicked.connect(self._toggle); tl.addWidget(self.start_btn)
        rst = QPushButton('↺ Reset'); rst.setFixedWidth(62); rst.clicked.connect(self._reset_avg)
        tl.addWidget(rst); tl.addWidget(_vs())

        tl.addWidget(_lb('FFT:'))
        self.fft_cb = RoundComboBox(); self.fft_cb.addItems(TF_FFT_LABELS); self.fft_cb.setCurrentIndex(2)
        self.fft_cb.setSizeAdjustPolicy(QComboBox.AdjustToContents); self.fft_cb.setMinimumWidth(50)
        self.fft_cb.currentIndexChanged.connect(self._fft_changed); tl.addWidget(self.fft_cb); tl.addWidget(_vs())

        tl.addWidget(_lb('Avg:'))
        self.avg_cb = RoundComboBox()
        self.avg_cb.addItems([f'{s}s' if s!=int(s) else f'{int(s)}s' for s in TF_AVG_SEC])
        self.avg_cb.setCurrentIndex(2)
        self.avg_cb.setSizeAdjustPolicy(QComboBox.AdjustToContents); self.avg_cb.setMinimumWidth(46)
        self.avg_cb.currentIndexChanged.connect(self._avg_changed); tl.addWidget(self.avg_cb); tl.addWidget(_vs())

        tl.addWidget(_lb('Smooth:'))
        self.sm_cb = RoundComboBox(); self.sm_cb.addItems(TF_SMOOTH_LABELS); self.sm_cb.setCurrentIndex(5)
        self.sm_cb.setSizeAdjustPolicy(QComboBox.AdjustToContents); self.sm_cb.setMinimumWidth(66)
        self.sm_cb.currentIndexChanged.connect(self._smooth_changed); tl.addWidget(self.sm_cb); tl.addWidget(_vs())

        tl.addWidget(_lb('Delay:'))
        self.delay_spin = QDoubleSpinBox()
        self.delay_spin.setRange(-2000,2000); self.delay_spin.setDecimals(2)
        self.delay_spin.setSingleStep(0.5); self.delay_spin.setValue(0.0)
        self.delay_spin.setSuffix(' ms'); self.delay_spin.setFixedWidth(90)
        self.delay_spin.setButtonSymbols(QDoubleSpinBox.NoButtons)
        self.delay_spin.setStyleSheet(f'background:{T("panel")};color:{T("text")};'
                                       f'border:1px solid {T("border")};border-radius:6px;padding:2px 4px;font-size:11px;')
        self.delay_spin.valueChanged.connect(self._on_delay_changed)
        tl.addWidget(self.delay_spin)
        self.find_btn = QPushButton('🔍 Find'); self.find_btn.setFixedWidth(62)
        self.find_btn.clicked.connect(self._find_delay); tl.addWidget(self.find_btn); tl.addWidget(_vs())

        tl.addWidget(_lb('IR:'))
        self.ir_cb = RoundComboBox(); self.ir_cb.addItems(TF_IR_MODES); self.ir_cb.setCurrentIndex(0)
        self.ir_cb.setSizeAdjustPolicy(QComboBox.AdjustToContents); self.ir_cb.setMinimumWidth(54)
        self.ir_cb.currentIndexChanged.connect(self._ir_mode_changed)
        tl.addWidget(self.ir_cb); tl.addWidget(_vs())

        tl.addWidget(_lb('Phase:'))
        self.phase_cb = RoundComboBox(); self.phase_cb.addItems(TF_PHASE_MODES)
        self.phase_cb.setSizeAdjustPolicy(QComboBox.AdjustToContents); self.phase_cb.setMinimumWidth(88)
        self.phase_cb.currentIndexChanged.connect(self._phase_mode_changed)
        tl.addWidget(self.phase_cb); tl.addWidget(_vs())

        tl.addWidget(_lb('Coh:'))
        self.coh_slider = QSlider(Qt.Horizontal); self.coh_slider.setRange(0,100)
        self.coh_slider.setValue(50); self.coh_slider.setFixedWidth(80)
        self.coh_slider.setStyleSheet(
            f'QSlider::groove:horizontal{{height:4px;background:{T("border")};border-radius:2px;}}'
            f'QSlider::handle:horizontal{{background:{T("accent")};width:12px;height:12px;margin:-4px 0;border-radius:6px;}}'
            f'QSlider::sub-page:horizontal{{background:{T("accent")};border-radius:2px;}}')
        self.coh_lbl = QLabel('50%'); self.coh_lbl.setStyleSheet(f'color:{T("text_dim")};font-size:10px;min-width:28px;')
        self.coh_slider.valueChanged.connect(self._coh_blank_changed)
        tl.addWidget(self.coh_slider); tl.addWidget(self.coh_lbl)
        tl.addStretch(); root.addWidget(tb)

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
        self.ref_cb.clear(); self.meas_cb.clear(); self.sig_out_cb.clear()
        self.ref_cb.addItem('⚡ Internal (SigGen)', None)
        for i, d in enumerate(payload):
            tag = '[외장] ' if any(k in d['name'].lower() for k in ext) else ''
            if d['max_input_channels'] >= 1:
                self.ref_cb.addItem(f'{tag}{d["name"]}', i)
                self.meas_cb.addItem(f'{tag}{d["name"]}', i)
            if d['max_output_channels'] >= 1:
                self.sig_out_cb.addItem(f'{tag}{d["name"]}', i)
        if self.meas_cb.count() > 1: self.meas_cb.setCurrentIndex(1)
        self._ref_device_changed(self.ref_cb.currentIndex())
        self._meas_device_changed(self.meas_cb.currentIndex())

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
        self._update_ch_cb(self.ref_ch_cb, self.ref_cb.currentData())

    def _meas_device_changed(self, _=None):
        self._update_ch_cb(self.meas_ch_cb, self.meas_cb.currentData())

    # ── 시작/정지 ────────────────────────────
    def _toggle(self):
        if self._running: self._stop()
        else: self._start()

    def _start(self):
        ref_idx = self.ref_cb.currentData(); meas_idx = self.meas_cb.currentData()
        _alog.debug(f'_start()  ref_idx={ref_idx} meas_idx={meas_idx} sig_stream={self._sig_stream}')
        if meas_idx is None: return
        self._reset_avg(); self._recalc_target()
        if ref_idx is None:
            _alog.debug(f'  mode=Internal Loopback  duplex={self._duplex_thread}  sig={self._sig_stream}')
            if self._duplex_thread is not None:
                # 같은 장치 TFDuplexThread 실행 중 → 스트림 재시작 없음 (zero gap)
                _alog.debug('  TFDuplexThread running → zero gap Start')
            elif self._sig_stream is not None:
                # 다른 장치 standalone OutputStream 실행 중 → meas InputStream만 추가
                _alog.debug(f'  Standalone OutputStream running → opening meas AudioThread device={meas_idx}')
                meas_ch = self.meas_ch_cb.currentData() or 0
                self._meas_thread = AudioThread(meas_idx, self.sample_rate, self.fft_size, meas_ch)
                self._meas_thread.chunk_ready.connect(self._on_meas, Qt.QueuedConnection)
                self._meas_thread.error_signal.connect(self._on_err, Qt.QueuedConnection)
                self._meas_thread.start()
            else:
                # SigGen 꺼져 있음 → 사용자가 직접 ▶ Play를 눌러야 함
                _alog.debug('  SigGen not running → Start aborted (user must press Play first)')
                from PyQt5.QtWidgets import QMessageBox
                QMessageBox.information(self, 'Signal Generator',
                    'Signal Generator가 꺼져 있습니다.\n먼저 ▶ Play를 눌러 신호를 시작한 후 ▶ Start를 누르세요.')
                return
        else:
            ref_ch  = self.ref_ch_cb.currentData()  or 0
            meas_ch = self.meas_ch_cb.currentData() or 0
            if ref_idx == meas_idx:
                # 같은 장치, 다른 채널 → 단일 InputStream으로 샘플 동기화 (Smaart 방식)
                self._sync_thread = TFSyncThread(ref_idx, self.sample_rate, self.fft_size, ref_ch, meas_ch)
                self._sync_thread.frame_ready.connect(self._on_frame, Qt.QueuedConnection)
                self._sync_thread.error_signal.connect(self._on_err, Qt.QueuedConnection)
                self._sync_thread.start()
            else:
                # 다른 장치 → 별도 AudioThread 2개
                self._ref_thread = AudioThread(ref_idx, self.sample_rate, self.fft_size, ref_ch)
                self._ref_thread.chunk_ready.connect(self._on_ref, Qt.QueuedConnection)
                self._ref_thread.error_signal.connect(self._on_err, Qt.QueuedConnection)
                self._ref_thread.start()
                self._meas_thread = AudioThread(meas_idx, self.sample_rate, self.fft_size, meas_ch)
                self._meas_thread.chunk_ready.connect(self._on_meas, Qt.QueuedConnection)
                self._meas_thread.error_signal.connect(self._on_err, Qt.QueuedConnection)
                self._meas_thread.start()
        self._running = True
        self.start_btn.setText('■  Stop')
        self.start_btn.setStyleSheet(f'background:rgba(255,51,51,25);color:{T("red")};'
                                      f'border:1px solid rgba(255,51,51,100);padding:3px 10px;border-radius:6px;font-weight:bold;')
        self.status_lbl.setText('● Running')
        self.status_lbl.setStyleSheet(f'color:{T("green")};font-size:11px;')

    def _stop(self):
        # External 모드 AudioThread / TFSyncThread 정리 (Internal 모드에서는 None)
        if self._sync_thread is not None:
            try: self._sync_thread.frame_ready.disconnect(); self._sync_thread.error_signal.disconnect()
            except Exception: pass
            self._sync_thread.stop()
            self._sync_thread = None
        for th in [self._ref_thread, self._meas_thread]:
            if th:
                try: th.chunk_ready.disconnect(); th.error_signal.disconnect()
                except Exception: pass
                th.stop()
        # Internal Loopback: TFDuplexThread는 유지 (SigGen 계속 재생)
        # _stop_sig_gen()에서만 종료됨
        self._ref_thread = self._meas_thread = None; self._running = False
        self.start_btn.setText('▶  Start')
        self.start_btn.setStyleSheet(f'background:rgba(57,255,20,25);color:{T("green")};'
                                      f'border:1px solid rgba(57,255,20,100);padding:3px 10px;border-radius:6px;font-weight:bold;')
        self.status_lbl.setText('● Standby')
        self.status_lbl.setStyleSheet(f'color:{T("text_dim")};font-size:11px;')

    # ── 오디오 콜백 ──────────────────────────
    def _on_ref(self, buf):
        win = np.hanning(len(buf)).astype(np.float32)
        rms = float(np.sqrt(np.mean(buf ** 2)))
        fft = np.fft.rfft(buf * win).astype(complex)
        with QMutexLocker(self._mutex):
            self._last_ref_fft = fft; self._last_ref_rms = rms

    def _on_meas(self, buf):
        win = np.hanning(len(buf)).astype(np.float32)
        rms = float(np.sqrt(np.mean(buf ** 2)))
        fft = np.fft.rfft(buf * win).astype(complex)
        with QMutexLocker(self._mutex):
            self._last_meas_fft = fft; self._last_meas_rms = rms

    def _on_frame(self, ref_buf, meas_buf):
        # TFSyncThread/TFDuplexThread: 두 채널을 동일 콜백에서 수신 → ΔT=0 원자 처리
        win = np.hanning(len(ref_buf)).astype(np.float32)
        rms_r = float(np.sqrt(np.mean(ref_buf ** 2)))
        rms_m = float(np.sqrt(np.mean(meas_buf ** 2)))
        fft_r = np.fft.rfft(ref_buf * win).astype(complex)
        fft_m = np.fft.rfft(meas_buf * win).astype(complex)
        with QMutexLocker(self._mutex):
            self._last_ref_fft = fft_r; self._last_ref_rms = rms_r
            self._last_meas_fft = fft_m; self._last_meas_rms = rms_m

    def _on_err(self, msg):
        self._stop()
        from PyQt5.QtWidgets import QMessageBox
        QMessageBox.warning(self, '오디오 오류', f'오디오 장치 오류:\n{msg}')

    # ── 렌더 루프 ────────────────────────────
    def _render(self):
        # Internal Loopback: SigGen 순환 버퍼에서 Reference 프레임 추출
        if self._running and self.ref_cb.currentData() is None and self._sig_stream is not None:
            with self._int_ref_lock:
                ir_snap = self._int_ref_buf.copy()
                ir_pos  = self._int_ref_pos[0]
            n = len(ir_snap); fs = self.fft_size
            frame = (ir_snap[ir_pos - fs:ir_pos] if ir_pos >= fs
                     else np.concatenate([ir_snap[n - (fs - ir_pos):], ir_snap[:ir_pos]]))
            self._on_ref(frame)
        with QMutexLocker(self._mutex):
            X = self._last_ref_fft; Y = self._last_meas_fft
            rr = self._last_ref_rms; mr = self._last_meas_rms
            self._last_ref_fft = None; self._last_meas_fft = None
        if rr > 0: self._vu_ref.set_rms(20 * math.log10(max(rr, 1e-9)))
        if mr > 0: self._vu_meas.set_rms(20 * math.log10(max(mr, 1e-9)))
        if not self._running: return  # 측정 정지 중 — VU만 업데이트, 누적 없음
        if X is None or Y is None or len(X) != len(Y): return
        if rr < 1e-6: return  # Ref 무음 — 누적 건너뜀
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
        H_raw = self._cross_acc / np.maximum(self._auto_acc_x, 1e-30)
        n_bins = len(X)
        freqs = np.fft.rfftfreq((n_bins - 1) * 2, 1.0 / self.sample_rate)[:n_bins].astype(np.float32)
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
        self.phase_cvs.set_data(f_out, ph_wrap, ph_unwr, grp_ms, coh_out)
        self.mag_cvs.set_data(f_out, mag_out, coh_out)

        # Live IR: raw H IFFT → 물리적 딜레이 위치(118ms)에 피크 표시
        h_full = np.fft.irfft(H_raw, n=self.fft_size).astype(np.float32)
        t_ms = np.arange(self.fft_size, dtype=np.float32) / self.sample_rate * 1000.0
        self.ir_cvs.set_data(t_ms, h_full)

    # ── 딜레이 자동 탐지 (2단계: 2초 측정 후 계산) ──────────────────────
    def _find_delay(self):
        """1단계: 평균 리셋 → 2초 대기 → 2단계에서 계산."""
        if not self._running:
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.information(self, 'Delay Finder', '먼저 ▶ Start를 누르고 신호가 들어오면 사용하세요.')
            return
        self._reset_avg()
        self.find_btn.setEnabled(False)
        self.find_btn.setText('...')
        QTimer.singleShot(2000, self._find_delay_compute)

    def _find_delay_compute(self):
        """2단계: 2초 누적 후 TF IR 피크로 딜레이 계산 (Smaart 방식: H=Sxy/Sxx 정규화)."""
        import threading
        with QMutexLocker(self._mutex):
            cross  = self._cross_acc.copy()  if self._cross_acc  is not None else None
            auto_x = self._auto_acc_x.copy() if self._auto_acc_x is not None else None
        if cross is None or auto_x is None:
            self.find_btn.setEnabled(True); self.find_btn.setText('🔍 Find')
            return
        fft_size = self.fft_size; sr = self.sample_rate

        def _worker():
            # Smaart 방식: H = Sxy/Sxx (TF 정규화) → IFFT → IR 피크
            # 비정규화 cross-correlation은 핑크노이즈 저주파 에너지에 편향됨 → 오차
            H = cross / np.maximum(auto_x, 1e-30)
            h = np.fft.irfft(H, n=fft_size)
            env = _hilbert_env(h)              # 힐버트 포락선으로 더 정확한 피크
            peak = int(np.argmax(env))
            if peak > fft_size // 2: peak -= fft_size
            d_ms = round(peak / sr * 1000.0, 2)
            self._find_result_sig.emit(d_ms)

        threading.Thread(target=_worker, daemon=True).start()

    def _apply_find_result(self, d_ms):
        """백그라운드 계산 완료 후 메인 스레드에서 UI 업데이트."""
        self.find_btn.setEnabled(True); self.find_btn.setText('🔍 Find')
        if 0 <= d_ms <= 500:
            self.delay_spin.setValue(d_ms)
        else:
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.information(self, 'Delay Finder', f'탐지값: {d_ms:.2f} ms\n범위 초과 — 수동으로 입력하세요.')

    # ── 컨트롤 핸들러 ────────────────────────
    def _recalc_target(self):
        self._avg_target = max(2, int(self.averaging_sec * self.sample_rate / (self.fft_size // 4)))

    def _reset_avg(self):
        with QMutexLocker(self._mutex):
            self._cross_acc = None; self._auto_acc_x = None; self._auto_acc_y = None; self._n_avg = 0

    def _fft_changed(self, idx):
        self.fft_size = TF_FFT_SIZES[idx]; self._recalc_target(); self._reset_avg()
        t_max_new = self.fft_size / self.sample_rate * 1000.0
        self.ir_cvs.t_min = 0.0; self.ir_cvs.t_max = min(30.0, t_max_new); self.ir_cvs.clear()
        if self._running: self._stop(); self._start()

    def _avg_changed(self, idx):
        self.averaging_sec = TF_AVG_SEC[idx]; self._recalc_target(); self._reset_avg()

    def _smooth_changed(self, idx):
        self.smooth_bpo = TF_SMOOTH_BPO[idx]; self._reset_avg()

    def _on_delay_changed(self, v):
        self.delay_ms = v
        self._center_ir_on_delay(v)

    def _center_ir_on_delay(self, delay_ms):
        span = max(self.ir_cvs.t_max - self.ir_cvs.t_min, 10.0)
        half = span / 2.0
        # 음수 t_min 허용 — delay 값이 어떤 값이든 정중앙에 표시 (Smaart 방식)
        self.ir_cvs.t_min = delay_ms - half
        self.ir_cvs.t_max = delay_ms + half
        self.ir_cvs._cache = None; self.ir_cvs.update()

    def _ir_mode_changed(self, idx):
        self.ir_cvs.set_mode(idx)

    def _phase_mode_changed(self, idx):
        self.phase_mode = idx; self.phase_cvs.set_mode(idx)

    def _coh_blank_changed(self, val):
        self.coh_blank = val / 100.0
        self.mag_cvs.coh_blank = self.coh_blank
        self.phase_cvs.coh_blank = self.coh_blank
        self.coh_lbl.setText(f'{val}%')
        self.mag_cvs.update()
        self.phase_cvs._cache = None; self.phase_cvs.update()

    def _sig_level_changed(self, idx):
        self._sig_level_lin = 10 ** ([-40,-30,-20,-10,-6,-3][idx] / 20)
        # standalone OutputStream 실행 중이면 레벨 즉시 반영
        if hasattr(self, '_sig_lvl_ref'): self._sig_lvl_ref[0] = self._sig_level_lin

    # ── 신호 발생기 ──────────────────────────
    def _toggle_sig_gen(self, checked):
        if checked: self._start_sig_gen()
        else: self._stop_sig_gen()

    def _start_sig_gen(self):
        _alog.debug(f'_start_sig_gen() called  sig_stream={self._sig_stream}  duplex={self._duplex_thread}')
        self._stop_sig_gen()
        self._pink_buf = (_gen_pink_noise(self.sample_rate*2) if self.sig_pink_btn.isChecked()
                          else (np.random.randn(self.sample_rate*2)*0.5).astype(np.float32))

        meas_idx = self.meas_cb.currentData()
        out_dev  = self.sig_out_cb.currentData()
        mw = self.parent()
        main_at = getattr(mw, 'audio_thread', None)
        _alog.debug(f'  main_audio_thread running={main_at.isRunning() if main_at else False}')

        if self.ref_cb.currentData() is None and meas_idx == out_dev:
            # 같은 장치 (USB 인터페이스): TFDuplexThread — native duplex, xrun 없음
            _alog.debug(f'  Internal+SameDevice → TFDuplexThread  dev={out_dev}')
            if meas_idx is None or out_dev is None:
                from PyQt5.QtWidgets import QMessageBox
                QMessageBox.warning(self, 'Signal Generator', 'Measurement 장치를 먼저 선택하세요.')
                self.sig_on_btn.setChecked(False); return
            try: n_out = max(1, min(int(sd.query_devices(out_dev)['max_output_channels']), 2))
            except Exception: n_out = 2
            self._duplex_thread = TFDuplexThread(
                meas_idx, out_dev, self.sample_rate, self.fft_size,
                self._pink_buf, self._sig_level_lin, n_out)
            self._duplex_thread.frame_ready.connect(self._on_frame, Qt.QueuedConnection)
            self._duplex_thread.error_signal.connect(self._on_err, Qt.QueuedConnection)
            self._duplex_thread.start()
            _alog.debug(f'  TFDuplexThread started')
        else:
            # 다른 장치 or External Ref: standalone OutputStream + 순환 버퍼
            _alog.debug(f'  DiffDevice/External → standalone OutputStream  out={out_dev}')
            if out_dev is None:
                self.sig_on_btn.setChecked(False); return
            # lvl_r: 뮤터블 컨테이너 — 레벨 변경이 실행 중 스트림에 즉시 반영됨
            lvl_r = [self._sig_level_lin]; self._sig_lvl_ref = lvl_r
            buf_r = [self._pink_buf]; pos_r = [0]
            try: n_ch = max(1, int(sd.query_devices(out_dev)['max_output_channels']))
            except Exception: n_ch = 2
            n_ch = min(n_ch, 2)  # 최대 스테레오
            _blk_size = 2048
            out_blk = np.zeros(_blk_size, dtype=np.float32)  # 콜백 외부에서 사전 할당
            _ir_buf = self._int_ref_buf; _ir_lock = self._int_ref_lock; _ir_pos = self._int_ref_pos
            def cb(outdata, frames, ti, status):
                if status: _alog.warning(f'SigGen cb xrun/status: {status}')
                nonlocal out_blk
                if frames > len(out_blk): out_blk = np.zeros(frames, dtype=np.float32)
                lvl=lvl_r[0]; pp=pos_r[0]; b=buf_r[0]; n=len(b); rem=frames; op=0
                while rem>0:
                    av=n-pp; tk=min(rem,av); out_blk[op:op+tk]=b[pp:pp+tk]*lvl; op+=tk; pp=(pp+tk)%n; rem-=tk
                pos_r[0]=pp
                for ch in range(outdata.shape[1]): outdata[:,ch]=out_blk[:frames]
                # 내부 참조 버퍼 업데이트: 논블로킹 — 락 못 얻으면 skip (xrun 방지)
                if _ir_lock.acquire(blocking=False):
                    try:
                        n2=len(_ir_buf); p2=_ir_pos[0]; end=p2+frames
                        if end<=n2: _ir_buf[p2:end]=out_blk[:frames]
                        else:
                            f=n2-p2; _ir_buf[p2:]=out_blk[:f]; _ir_buf[:end-n2]=out_blk[f:frames]
                        _ir_pos[0]=end%n2
                    finally: _ir_lock.release()
            try:
                self._sig_stream = sd.OutputStream(device=out_dev, samplerate=self.sample_rate,
                                                    channels=n_ch, dtype='float32',
                                                    blocksize=_blk_size,
                                                    latency='high', callback=cb)
                self._sig_stream.start()
                _alog.debug(f'  OutputStream started  out={out_dev} sr={self.sample_rate} ch={n_ch}')
            except Exception as e:
                self.sig_on_btn.setChecked(False)
                from PyQt5.QtWidgets import QMessageBox
                QMessageBox.warning(self, 'Signal Generator', f'출력 장치 오류:\n{e}'); return

        self.sig_on_btn.setChecked(True); self.sig_on_btn.setText('■  Stop')
        self.sig_on_btn.setStyleSheet(f'background:rgba(57,255,20,25);color:{T("green")};'
                                       f'border:1px solid rgba(57,255,20,100);padding:4px;border-radius:6px;font-weight:bold;')

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
        self.sig_on_btn.setText('▶  Play'); self.sig_on_btn.setChecked(False)
        self.sig_on_btn.setStyleSheet(f'background:{T("panel")};color:{T("text_dim")};'
                                       f'border:1px solid {T("border")};padding:4px;border-radius:6px;font-weight:bold;')

    def closeEvent(self, e):
        self._timer.stop(); self._stop(); self._stop_sig_gen(); e.accept()
        if hasattr(self.parent(), 'tf_win'): self.parent().tf_win = None

# ───────────────────────────────────────────
#  메인 윈도우
# ───────────────────────────────────────────
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('WAYAUDIO Spectrum Analyzer 2')
        self.setMinimumSize(1100,580)

        self.audio_thread=None; self.sample_rate=48000; self.fft_size=16384
        self.db_max=MAX_DB; self.db_range=96; self.db_min=self.db_max-self.db_range
        self.speed_idx=2; self.smoothing=SPEED_LEVELS[2][1]
        self.peak_hold=True; self.view_mode='fft'; self.avg_count=4
        self.calib_offset=0.0

        self._mutex=QMutex()
        self._fft_smooth=None; self._avg_buf=deque(maxlen=4)
        self._spl_smooth=-100.0
        self._raw_spl_smooth=-100.0; self._raw_peak_smooth=-100.0
        self._dba_smooth=-100.0; self._dbc_smooth=-100.0
        self._pending=None
        self._dba_display_t=0.0

        # A/C 가중치 테이블 (시작 전 미리 계산)
        self._aw_table=None; self._cw_table=None

        # ── 채널 B (비교 모드)
        self.compare_mode=False
        self.audio_thread_b=None
        self.calib_offset_b=0.0
        self._mutex_b=QMutex()
        self._fft_smooth_b=None; self._avg_buf_b=deque(maxlen=4)
        self._raw_spl_smooth_b=-100.0; self._raw_peak_smooth_b=-100.0
        self._dba_smooth_b=-100.0; self._dbc_smooth_b=-100.0
        self._pending_b=None; self._dba_display_t_b=0.0
        self._aw_table_b=None; self._cw_table_b=None

        # LEQ 창 / TF 창
        self.leq_win = None
        self.tf_win = None

        # 설정 (마이크별 캘리브레이션)
        self._settings = _load_settings()

        self._build_ui()
        self._load_devices()
        self._apply_theme()

        self._render_t=QTimer(self); self._render_t.timeout.connect(self._render_frame); self._render_t.start(33)

    # ─────────────────────────────────────
    def _build_ui(self):
        c=QWidget(); self.setCentralWidget(c)
        root=QVBoxLayout(c); root.setSpacing(0); root.setContentsMargins(0,0,0,0)

        # ── Layer 1: 32px 슬림 헤더 (logo | stretch | status | theme | calib)
        self.hdr=QWidget(); self.hdr.setFixedHeight(32)
        hl=QHBoxLayout(self.hdr); hl.setContentsMargins(16,0,16,0); hl.setSpacing(8)
        self.logo_lbl=QLabel(); self.logo_lbl.setTextFormat(Qt.RichText)
        hl.addWidget(self.logo_lbl)
        hl.addStretch()
        self.status_lbl=QLabel('● Standby')
        hl.addWidget(self.status_lbl)
        self.theme_btn=QPushButton('☀ Light Mode')
        self.theme_btn.setFixedWidth(90); self.theme_btn.setFixedHeight(24)
        self.theme_btn.clicked.connect(self._toggle_theme)
        hl.addWidget(self.theme_btn)
        self.calib_btn=QPushButton('🎙 Calibration')
        self.calib_btn.setFixedWidth(100); self.calib_btn.setFixedHeight(24)
        self.calib_btn.clicked.connect(self._open_calib)
        hl.addWidget(self.calib_btn)
        root.addWidget(self.hdr)

        # ── Layer 2: 38px 컨트롤바 (Start | sep | Input Device | Refresh | status)
        self.ctrl_bar=QWidget(); self.ctrl_bar.setFixedHeight(38)
        cl=QHBoxLayout(self.ctrl_bar); cl.setContentsMargins(16,3,16,3); cl.setSpacing(8)
        self.start_btn=QPushButton('▶  Start')
        self.start_btn.setFixedWidth(84); self.start_btn.setFixedHeight(28)
        self.start_btn.clicked.connect(self._toggle)
        cl.addWidget(self.start_btn)
        cl.addSpacing(4); cl.addWidget(self._vsep()); cl.addSpacing(4)
        cl.addWidget(QLabel('🎤 Input Device'))
        self.dev_cb=RoundComboBox(); self.dev_cb.setMinimumWidth(300); self.dev_cb.setMaximumWidth(480)
        cl.addWidget(self.dev_cb)
        rb=QPushButton('↺ Refresh'); rb.setFixedWidth(76); rb.setFixedHeight(28)
        rb.clicked.connect(self._load_devices)
        cl.addWidget(rb)
        self.mic_st=QLabel('Disconnected')
        cl.addWidget(self.mic_st)
        cl.addStretch()
        root.addWidget(self.ctrl_bar)

        # ── Layer 3: 30px 탭바 (Spectrum | Transfer | Compare)
        self.tab_bar=QWidget(); self.tab_bar.setFixedHeight(30)
        tbl=QHBoxLayout(self.tab_bar); tbl.setContentsMargins(8,0,0,0); tbl.setSpacing(0)
        self._tab_btns={}
        for idx,(key,label) in enumerate([('spectrum','📊  Spectrum'),('transfer','⇄  Transfer'),('compare','📈  Compare')]):
            b=QPushButton(label); b.setCheckable(True); b.setChecked(idx==0)
            b.setFixedHeight(30)
            b.clicked.connect(lambda _,i=idx: self._switch_tab(i))
            tbl.addWidget(b); self._tab_btns[key]=b
        tbl.addStretch()
        root.addWidget(self.tab_bar)

        # ── Sub-controls stack (34px): 탭별 전용 컨트롤
        self.sub_stack=QStackedWidget(); self.sub_stack.setFixedHeight(34)

        # Sub-page 0: Spectrum 컨트롤
        sp0=QWidget(); sl0=QHBoxLayout(sp0)
        sl0.setContentsMargins(12,2,12,2); sl0.setSpacing(4)
        sl0.addWidget(self._lbl('View:'))
        self.view_btns={}
        for m,t in [('fft','FFT'),('oct3','⅓ Oct'),('oct12','¹² Oct'),('oct24','²⁴ Oct')]:
            b=QPushButton(t); b.setCheckable(True); b.setChecked(m=='fft')
            b.setFixedWidth(56); b.setFixedHeight(26)
            b.clicked.connect(lambda _,mode=m: self._set_view(mode))
            sl0.addWidget(b); self.view_btns[m]=b
        sl0.addSpacing(3); sl0.addWidget(self._vsep()); sl0.addSpacing(3)
        sl0.addWidget(self._lbl('Scale:'))
        self.log_btn=QPushButton('Log'); self.log_btn.setCheckable(True); self.log_btn.setChecked(True)
        self.lin_btn=QPushButton('Lin'); self.lin_btn.setCheckable(True)
        self.log_btn.setFixedWidth(44); self.lin_btn.setFixedWidth(40)
        self.log_btn.setFixedHeight(26); self.lin_btn.setFixedHeight(26)
        self.log_btn.clicked.connect(lambda: self._set_scale(True))
        self.lin_btn.clicked.connect(lambda: self._set_scale(False))
        sl0.addWidget(self.log_btn); sl0.addWidget(self.lin_btn)
        sl0.addSpacing(3); sl0.addWidget(self._vsep()); sl0.addSpacing(3)
        sl0.addWidget(self._lbl('FFT:'))
        fft_lbl=QLabel('16k'); fft_lbl.setStyleSheet('font-size:11px;font-weight:bold;padding:0 3px;')
        sl0.addWidget(fft_lbl)
        sl0.addSpacing(3); sl0.addWidget(self._vsep()); sl0.addSpacing(3)
        sl0.addWidget(self._lbl('SR:'))
        self.sr_cb=RoundComboBox(); self.sr_cb.addItems(['44.1 kHz','48 kHz'])
        self.sr_cb.setCurrentIndex(1); self.sr_cb.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.sr_cb.setMinimumWidth(68); self.sr_cb.setFixedHeight(26)
        self.sr_cb.currentIndexChanged.connect(self._sr_changed)
        sl0.addWidget(self.sr_cb)
        sl0.addSpacing(3); sl0.addWidget(self._vsep()); sl0.addSpacing(3)
        sl0.addWidget(self._lbl('Avg:'))
        self.avg_cb=RoundComboBox(); self.avg_cb.addItems(['None','4x','8x','16x'])
        self.avg_cb.setCurrentIndex(1); self.avg_cb.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.avg_cb.setMinimumWidth(50); self.avg_cb.setFixedHeight(26)
        self.avg_cb.currentIndexChanged.connect(self._avg_changed)
        sl0.addWidget(self.avg_cb)
        sl0.addSpacing(3); sl0.addWidget(self._vsep()); sl0.addSpacing(3)
        sl0.addWidget(self._lbl('Peak:'))
        self.peak_btn=QPushButton('ON'); self.peak_btn.setCheckable(True); self.peak_btn.setChecked(True)
        self.peak_btn.setFixedWidth(42); self.peak_btn.setFixedHeight(26)
        self.peak_btn.clicked.connect(self._toggle_peak)
        rst=QPushButton('Reset'); rst.setFixedWidth(52); rst.setFixedHeight(26)
        rst.clicked.connect(self._reset_peak)
        sl0.addWidget(self.peak_btn); sl0.addWidget(rst)
        sl0.addSpacing(3)
        sl0.addWidget(self._lbl('Hold:'))
        self.hold_cb=RoundComboBox()
        self.hold_cb.addItems(['1s','2s','3s','5s','10s'])
        self.hold_cb.setCurrentIndex(0)   # 기본값 1s (제일 빠름)
        self.hold_cb.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.hold_cb.setMinimumWidth(50); self.hold_cb.setFixedHeight(26)
        self.hold_cb.currentIndexChanged.connect(self._set_peak_hold_time)
        sl0.addWidget(self.hold_cb)
        sl0.addSpacing(3); sl0.addWidget(self._vsep()); sl0.addSpacing(3)
        sl0.addWidget(self._lbl('dB:'))
        self.db_cb=RoundComboBox(); self.db_cb.addItems(['72 dB','96 dB','120 dB'])
        self.db_cb.setCurrentIndex(1); self.db_cb.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.db_cb.setMinimumWidth(58); self.db_cb.setFixedHeight(26)
        self.db_cb.currentIndexChanged.connect(self._db_changed)
        sl0.addWidget(self.db_cb)
        sl0.addSpacing(3); sl0.addWidget(self._vsep()); sl0.addSpacing(3)
        sl0.addWidget(self._lbl('⚡ Speed:'))
        self.spd_cb=RoundComboBox()
        self.spd_cb.addItems([lb for lb,*_ in SPEED_LEVELS])
        self.spd_cb.setCurrentIndex(self.speed_idx)
        self.spd_cb.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.spd_cb.setMinimumWidth(70); self.spd_cb.setFixedHeight(26)
        self.spd_cb.currentIndexChanged.connect(self._set_speed)
        sl0.addWidget(self.spd_cb)
        sl0.addSpacing(3); sl0.addWidget(self._vsep()); sl0.addSpacing(3)
        self.color_btn=QPushButton('◉ Color')
        self.color_btn.setFixedWidth(66); self.color_btn.setFixedHeight(26)
        self.color_btn.clicked.connect(self._open_color_picker)
        sl0.addWidget(self.color_btn)
        sl0.addStretch()
        self.sub_stack.addWidget(sp0)  # index 0

        # Sub-page 1: Transfer 컨트롤 (TF 위젯이 자체 UI 보유)
        sp1=QWidget(); sl1=QHBoxLayout(sp1)
        sl1.setContentsMargins(16,2,16,2)
        _tf_hint=QLabel('Transfer Function — use controls inside the panel')
        _tf_hint.setStyleSheet('font-size:10px;font-style:italic;')
        sl1.addWidget(_tf_hint); sl1.addStretch()
        self.sub_stack.addWidget(sp1)  # index 1

        # Sub-page 2: Compare 컨트롤
        sp2=QWidget(); sl2=QHBoxLayout(sp2)
        sl2.setContentsMargins(12,2,12,2); sl2.setSpacing(4)
        self.compare_btn=QPushButton('▶◀  Compare')
        self.compare_btn.setCheckable(True); self.compare_btn.setChecked(False)
        self.compare_btn.setFixedWidth(96); self.compare_btn.setFixedHeight(26)
        self.compare_btn.clicked.connect(self._toggle_compare)
        sl2.addWidget(self.compare_btn)
        sl2.addSpacing(3); sl2.addWidget(self._vsep()); sl2.addSpacing(3)
        self._cmp_lbl=QLabel('🎤 Input B:'); self._cmp_lbl.hide()
        sl2.addWidget(self._cmp_lbl)
        self.dev_cb_b=RoundComboBox()
        self.dev_cb_b.setMinimumWidth(280); self.dev_cb_b.setMaximumWidth(440)
        self.dev_cb_b.hide()
        sl2.addWidget(self.dev_cb_b)
        self.calib_btn_b=QPushButton('🎙 Calib B')
        self.calib_btn_b.setFixedWidth(78); self.calib_btn_b.setFixedHeight(26)
        self.calib_btn_b.clicked.connect(self._open_calib_b); self.calib_btn_b.hide()
        sl2.addWidget(self.calib_btn_b)
        sl2.addSpacing(3)
        self.diff_btn=QPushButton('Δ Diff'); self.diff_btn.setCheckable(True)
        self.diff_btn.setFixedWidth(56); self.diff_btn.setFixedHeight(26); self.diff_btn.hide()
        self.diff_btn.clicked.connect(self._toggle_diff)
        sl2.addWidget(self.diff_btn)
        sl2.addSpacing(8)
        self._chip_a=QLabel(); self._chip_a.setFixedSize(20,8)
        self._chip_a.setStyleSheet('background:#00e5ff;border-radius:3px;'); self._chip_a.hide()
        self._lbl_a=QLabel('A')
        self._lbl_a.setStyleSheet('color:#00e5ff;font-weight:bold;font-size:11px;'); self._lbl_a.hide()
        self._chip_b=QLabel(); self._chip_b.setFixedSize(20,8)
        self._chip_b.setStyleSheet('background:#ff8c28;border-radius:3px;'); self._chip_b.hide()
        self._lbl_b=QLabel('B')
        self._lbl_b.setStyleSheet('color:#ff8c28;font-weight:bold;font-size:11px;'); self._lbl_b.hide()
        for w in [self._chip_a,self._lbl_a,self._chip_b,self._lbl_b]: sl2.addWidget(w)
        self._compare_legend_widgets=[self._chip_a,self._lbl_a,self._chip_b,self._lbl_b]
        sl2.addStretch()
        self.sub_stack.addWidget(sp2)  # index 2

        root.addWidget(self.sub_stack)

        # ── 메인 스택: Spectrum(0) | Transfer(1)
        self.main_stack=QStackedWidget()

        # Page 0: Spectrum (VU + 캔버스 + 정보 패널)
        page0=QWidget(); pl0=QHBoxLayout(page0)
        pl0.setSpacing(0); pl0.setContentsMargins(0,0,0,0)
        vu_cont=QWidget(); vc_lay=QVBoxLayout(vu_cont)
        vc_lay.setContentsMargins(0,0,0,0); vc_lay.setSpacing(0)
        self._lbl_vu_a=QLabel('A'); self._lbl_vu_a.setAlignment(Qt.AlignHCenter)
        self._lbl_vu_a.setStyleSheet('color:#00e5ff;font-size:9px;font-weight:bold;')
        self._lbl_vu_a.hide()
        vc_lay.addWidget(self._lbl_vu_a)
        self.vu_a=VUMeter(); vc_lay.addWidget(self.vu_a)
        self._lbl_vu_b=QLabel('B'); self._lbl_vu_b.setAlignment(Qt.AlignHCenter)
        self._lbl_vu_b.setStyleSheet('color:#ff8c28;font-size:9px;font-weight:bold;')
        self._lbl_vu_b.hide()
        vc_lay.addWidget(self._lbl_vu_b)
        self.vu_b=VUMeter(); self.vu_b.hide(); vc_lay.addWidget(self.vu_b)
        pl0.addWidget(vu_cont)
        self.fft_cvs=FFTCanvas()
        self.oct_cvs=OctaveCanvas(); self.oct_cvs.hide()
        stk=QWidget(); sl=QVBoxLayout(stk); sl.setContentsMargins(0,0,0,0); sl.setSpacing(0)
        sl.addWidget(self.fft_cvs); sl.addWidget(self.oct_cvs)
        pl0.addWidget(stk)
        pl0.addWidget(self._build_info())
        self.main_stack.addWidget(page0)  # index 0

        # Page 1: Transfer Function (임베드)
        self.tf_win=TransferFunctionWindow(self, self._settings, embedded=True)
        self.main_stack.addWidget(self.tf_win)  # index 1

        root.addWidget(self.main_stack)

        # ── 푸터
        self.ft=QWidget(); self.ft.setFixedHeight(22)
        fl=QHBoxLayout(self.ft); fl.setContentsMargins(16,0,16,0)
        fl.addWidget(QLabel('WSA Spectrum Analyzer 2  |  v2.0'))
        fl.addStretch()
        jordan_lbl=QLabel('Design by Jordan')
        jordan_lbl.setStyleSheet(f'color:{T("text_dim")};font-size:10px;font-style:italic;')
        fl.addWidget(jordan_lbl)
        root.addWidget(self.ft)

    def _switch_tab(self, i):
        keys=['spectrum','transfer','compare']
        for k,b in self._tab_btns.items():
            b.setChecked(k==keys[i])
        self.sub_stack.setCurrentIndex(i)
        self.main_stack.setCurrentIndex(1 if i==1 else 0)
        self._apply_tab_styles()

    def _apply_tab_styles(self):
        bg=T('bg'); panel=T('panel'); accent=T('accent'); text=T('text'); text_dim=T('text_dim')
        for b in self._tab_btns.values():
            if b.isChecked():
                b.setStyleSheet(
                    f'border:none;border-top:2px solid {accent};background:{panel};'
                    f'color:{text};font-size:11px;font-weight:bold;'
                    f'padding:0 14px;border-radius:0;min-height:28px;')
            else:
                b.setStyleSheet(
                    f'border:none;border-top:2px solid transparent;background:{bg};'
                    f'color:{text_dim};font-size:11px;'
                    f'padding:0 14px;border-radius:0;min-height:28px;')

    def _sep(self):
        w = QWidget(); w.setFixedWidth(6); return w

    def _vsep(self):
        f = QFrame(); f.setFrameShape(QFrame.VLine)
        f.setFixedWidth(1); f.setFixedHeight(22)
        f.setStyleSheet(f'color:{T("border")};background:{T("border")};')
        return f

    def _lbl(self,t):
        l=QLabel(t); l.setStyleSheet('font-size:10px;white-space:nowrap;'); return l

    def _build_info(self):
        panel=QWidget(); panel.setFixedWidth(175)
        layout=QVBoxLayout(panel); layout.setContentsMargins(10,10,10,10); layout.setSpacing(8)

        def sec(title,rows):
            g=QGroupBox(title); gl=QVBoxLayout(g); gl.setSpacing(3); labels={}
            for k,v in rows:
                row=QHBoxLayout()
                kl=QLabel(k); kl.setStyleSheet(f'font-size:9px;font-family:Arial;color:{T("text_dim")};')
                vl=QLabel(v); vl.setStyleSheet(f'font-size:11px;font-family:Arial;font-weight:bold;color:{T("accent")};')
                vl.setAlignment(Qt.AlignRight)
                row.addWidget(kl); row.addWidget(vl); gl.addLayout(row); labels[k]=vl
            return g,labels

        g1,l1=sec('Info',[('Sample Rate','48 kHz'),('FFT Size','16384'),
                          ('Resolution','11.7 Hz'),('Calibration','0.0 dB'),('Speed','Normal')])
        self.i_sr=l1['Sample Rate']; self.i_fft=l1['FFT Size']
        self.i_res=l1['Resolution']; self.i_calib=l1['Calibration']; self.i_spd=l1['Speed']
        layout.addWidget(g1)

        def make_ch_box(ch_label, accent_color):
            box=QGroupBox(ch_label)
            box.setStyleSheet(f'QGroupBox{{border:2px solid {accent_color};border-radius:8px;'
                              f'margin-top:8px;color:{accent_color};font-size:10px;font-weight:bold;}}'
                              f'QGroupBox::title{{subcontrol-origin:margin;left:8px;padding:0 4px;}}')
            bl=QVBoxLayout(box); bl.setSpacing(3)
            refs={}
            for k,init in [('SPL','—'),('Peak Hold','—'),('Dominant','—')]:
                row=QHBoxLayout()
                kl=QLabel(k); kl.setStyleSheet(f'font-size:9px;font-family:Arial;color:{T("text_dim")};')
                vl=QLabel(init); vl.setStyleSheet(f'font-size:11px;font-family:Arial;font-weight:bold;color:{accent_color};')
                vl.setAlignment(Qt.AlignRight)
                row.addWidget(kl); row.addWidget(vl); bl.addLayout(row); refs[k]=vl
            dba_row=QHBoxLayout()
            dba_lbl=QLabel('dBA'); dba_lbl.setStyleSheet(f'color:{T("text_dim")};font-size:9px;')
            dba_val=QLabel('—')
            dba_val.setStyleSheet(f'color:{T("green")};font-size:18px;font-weight:bold;font-family:Arial;')
            dba_val.setAlignment(Qt.AlignRight)
            dba_row.addWidget(dba_lbl); dba_row.addWidget(dba_val); bl.addLayout(dba_row)
            dbc_row=QHBoxLayout()
            dbc_lbl=QLabel('dBC'); dbc_lbl.setStyleSheet(f'color:{T("text_dim")};font-size:9px;')
            dbc_val=QLabel('—')
            dbc_val.setStyleSheet(f'color:{T("accent2")};font-size:18px;font-weight:bold;font-family:Arial;')
            dbc_val.setAlignment(Qt.AlignRight)
            dbc_row.addWidget(dbc_lbl); dbc_row.addWidget(dbc_val); bl.addLayout(dbc_row)
            refs['dBA']=dba_val; refs['dBC']=dbc_val
            return box, refs

        self._ch_a_box, ch_a=make_ch_box('Channel A', T('accent'))
        self.i_spl=ch_a['SPL']; self.i_pk=ch_a['Peak Hold']
        self.i_dom=ch_a['Dominant']; self.i_dba=ch_a['dBA']; self.i_dbc=ch_a['dBC']
        layout.addWidget(self._ch_a_box)

        self._ch_b_box, ch_b=make_ch_box('Channel B', CH_B_LINE)
        self.i_spl_b=ch_b['SPL']; self.i_pk_b=ch_b['Peak Hold']
        self.i_dom_b=ch_b['Dominant']; self.i_dba_b=ch_b['dBA']; self.i_dbc_b=ch_b['dBC']
        self._ch_b_box.hide()
        layout.addWidget(self._ch_b_box)

        # SPL Meter popup button
        leq_btn=QPushButton('📊 Open SPL Meter')
        leq_btn.clicked.connect(self._open_leq)
        leq_btn.setStyleSheet('padding:5px;border-radius:4px;font-size:10px;')
        layout.addWidget(leq_btn)
        layout.addStretch(); return panel

    # ─────────────────────────────────────
    def _apply_theme(self):
        bg=T('bg'); bg2=T('bg2'); bg3=T('bg3'); border=T('border')
        text=T('text'); text_dim=T('text_dim'); accent=T('accent'); panel=T('panel')
        self.setStyleSheet(f"""
            QWidget       {{ background:{bg}; color:{text}; font-family:Arial; }}
            QLabel        {{ color:{text_dim}; font-size:11px; }}
            QComboBox     {{ background:{panel}; color:{text}; border:1px solid {border};
                             border-radius:6px; padding:2px 8px; font-size:11px;
                             min-height:26px; combobox-popup:0; }}
            QComboBox:hover {{ border-color:{accent}; color:{text}; }}
            QComboBox::drop-down {{ width:0; border:none; }}
            QComboBox::down-arrow {{ width:0; height:0; image:none; }}
            QComboBox QAbstractItemView {{ background:{bg2}; color:{text}; border:1px solid {accent};
                             border-radius:6px;
                             selection-background-color:rgba(0,229,255,60);
                             selection-color:{accent}; outline:none; font-size:11px; }}
            QComboBox QAbstractItemView::item {{ padding:5px 10px; min-height:26px;
                             background:{bg2}; color:{text}; border:none; }}
            QComboBox QAbstractItemView::item:hover {{ background:rgba(0,229,255,25); color:{text}; }}
            QComboBox QAbstractItemView::item:selected {{ background:rgba(0,229,255,60); color:{accent}; }}
            QScrollBar:vertical {{ background:{bg2}; width:6px; margin:0; border:none; }}
            QScrollBar::handle:vertical {{ background:{border}; border-radius:3px; min-height:20px; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height:0; }}
            QScrollBar:horizontal {{ background:{bg2}; height:6px; margin:0; border:none; }}
            QScrollBar::handle:horizontal {{ background:{border}; border-radius:3px; min-width:20px; }}
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width:0; }}
            QPushButton   {{ background:{panel}; color:{text}; border:1px solid {border};
                             border-radius:6px; padding:3px 12px; font-size:11px; min-height:26px; }}
            QPushButton:hover   {{ background:rgba(0,229,255,15); border-color:{accent}; color:{accent}; }}
            QPushButton:pressed {{ background:rgba(0,229,255,30); }}
            QPushButton:checked {{ background:rgba(0,229,255,20); color:{accent}; border:1.5px solid {accent}; }}
            QPushButton:disabled {{ color:{text_dim}; background:{bg3}; border-color:{border}; }}
            QGroupBox     {{ border:1px solid {border}; border-radius:6px; margin-top:8px;
                             font-size:9px; color:{text_dim}; padding-top:4px; }}
            QGroupBox::title {{ subcontrol-origin:margin; left:8px; padding:0 4px; color:{text_dim}; }}
            QFrame[frameShape="4"] {{ color:{border}; }}
        """)
        # 헤더/컨트롤바/탭바 스타일
        self.hdr.setStyleSheet(f'background:{bg2};border-bottom:1px solid {border};')
        self.ctrl_bar.setStyleSheet(f'background:{bg3};')
        self.tab_bar.setStyleSheet(f'background:{bg};border-bottom:1px solid {border};')
        self.sub_stack.setStyleSheet(f'background:{bg3};border-bottom:1px solid {border};')
        self._apply_tab_styles()
        self.ft.setStyleSheet(f'background:{bg2};border-top:1px solid {border};')
        self.logo_lbl.setText(
            f'<span style="font-size:14px;font-weight:700;color:{accent};letter-spacing:2px;">WAYAUDIO</span>'
            f'&nbsp;<span style="font-size:10px;color:{text_dim};">Spectrum Analyzer 2</span>'
        )
        self.status_lbl.setStyleSheet(f'color:{text_dim};font-family:Arial;font-size:11px;')
        self.mic_st.setStyleSheet(f'color:{text_dim};font-size:10px;font-family:Arial;')
        # 시작 버튼
        self._go_style(self.start_btn)
        # 테마 버튼
        lbl='🌙 Dark Mode' if _theme=='light' else '☀ Light Mode'
        self.theme_btn.setText(lbl)
        self.theme_btn.setStyleSheet(f'background:{panel};color:{accent};border:1px solid {border};padding:3px 10px;border-radius:4px;')
        self.calib_btn.setStyleSheet(f'background:{panel};color:{text_dim};border:1px solid {border};padding:3px 10px;border-radius:4px;')
        # 캔버스 캐시 무효화 + 리페인트
        self.fft_cvs._cache=None; self.oct_cvs._cache=None
        for w in [self.fft_cvs,self.oct_cvs,self.vu_a,self.vu_b]: w.update()

    def _go_style(self,b):
        b.setStyleSheet(f'background:rgba(57,255,20,25);color:{T("green")};'
                        f'border:1px solid rgba(57,255,20,100);'
                        f'font-weight:700;padding:3px 12px;border-radius:4px;')
    def _stop_style(self,b):
        b.setStyleSheet(f'background:rgba(255,51,51,25);color:{T("red")};'
                        f'border:1px solid rgba(255,51,51,100);'
                        f'font-weight:700;padding:3px 12px;border-radius:4px;')

    def _toggle_theme(self):
        global _theme
        _theme='light' if _theme=='dark' else 'dark'
        self._apply_theme()

    def _auto_range_for_calib(self):
        if self.calib_offset <= 5:
            self.db_max = MAX_DB
        else:
            base_max = MAX_DB + max(0, self.calib_offset)
            new_max  = int(math.ceil(base_max / 12.0)) * 12
            new_max  = max(MAX_DB, min(new_max, 160))
            self.db_max = new_max
        self.db_min = self.db_max - self.db_range
        if not hasattr(self, 'oct_cvs'):
            return
        self._apply_db_range()
        self.oct_cvs.clear()

    def _open_calib(self):
        # 현재 raw SPL(캘리브 오프셋 제외) 반환 콜백
        def get_raw_spl():
            with QMutexLocker(self._mutex):
                return self._raw_spl_smooth
        dlg = CalibDialog(self.calib_offset, get_raw_spl, self)
        if dlg.exec() == QDialog.Accepted:
            self.calib_offset = dlg.get_offset()
            self.i_calib.setText(f'{self.calib_offset:+.1f} dB')
            device_name = self.dev_cb.currentText()
            if 'calibrations' not in self._settings:
                self._settings['calibrations'] = {}
            self._settings['calibrations'][device_name] = self.calib_offset
            _save_settings(self._settings)
            with QMutexLocker(self._mutex):
                self._avg_buf.clear()
                self._fft_smooth = None
            self._auto_range_for_calib()

    def _apply_db_range(self):
        self.fft_cvs.db_max=self.db_max; self.fft_cvs.db_min=self.db_min
        self.oct_cvs.db_max=self.db_max; self.oct_cvs.db_min=self.db_min
        self.fft_cvs.update(); self.oct_cvs.update()

    def _open_leq(self):
        if self.leq_win is None:
            self.leq_win=LeqWindow(self)
            self.leq_win.setStyleSheet(f'background:{T("bg2")};color:{T("text")};')
        self.leq_win.show(); self.leq_win.raise_()

    def _open_tf_window(self):
        self._switch_tab(1)

    # ─────────────────────────────────────
    def _load_devices(self):
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
                self.dev_cb.addItem('장치 검색 시간 초과',-1); return
            status,payload=result.get_nowait()
            if status=='err':
                self.dev_cb.addItem(f'오류: {payload}',-1); return
            devs=payload
            ext=['usb','focusrite','scarlett','steinberg','motu',
                 'behringer','yamaha','audient','apollo','zoom','tascam','rme']
            self.dev_cb_b.clear()
            for i,d in enumerate(devs):
                if d['max_input_channels']<1: continue
                name=d['name']
                tag='[외장] ' if any(k in name.lower() for k in ext) else ''
                self.dev_cb.addItem(f'{tag}{name}',i)
                self.dev_cb_b.addItem(f'{tag}{name}',i)
            self.mic_st.setText(f'{self.dev_cb.count()}개 감지됨')
            # 마지막 사용 장치 복원
            last = self._settings.get('last_device', '')
            for i in range(self.dev_cb.count()):
                if self.dev_cb.itemText(i) == last:
                    self.dev_cb.setCurrentIndex(i); break
        except Exception as e:
            self.dev_cb.addItem(f'오류: {e}',-1)
            self.dev_cb_b.addItem(f'오류: {e}',-1)
        # 현재 장치의 저장된 캘리브레이션 로드
        self._load_calib_for_device(self.dev_cb.currentText())
        # 장치 변경 시 자동 로드
        try: self.dev_cb.currentIndexChanged.disconnect(self._on_device_changed)
        except Exception: pass
        self.dev_cb.currentIndexChanged.connect(self._on_device_changed)
        try: self.dev_cb_b.currentIndexChanged.disconnect(self._on_device_b_changed)
        except Exception: pass
        self.dev_cb_b.currentIndexChanged.connect(self._on_device_b_changed)

    def _on_device_changed(self, _):
        name = self.dev_cb.currentText()
        self._settings['last_device'] = name
        _save_settings(self._settings)
        self._load_calib_for_device(name)

    def _load_calib_for_device(self, device_name):
        calibs = self._settings.get('calibrations', {})
        offset = calibs.get(device_name, 0.0)
        self.calib_offset = offset
        self.i_calib.setText(f'{offset:+.1f} dB')
        with QMutexLocker(self._mutex):
            self._avg_buf.clear(); self._fft_smooth = None
        self._auto_range_for_calib()

    def _toggle(self):
        if self.audio_thread and self.audio_thread.isRunning(): self._stop()
        else: self._start()

    def _start(self):
        idx=self.dev_cb.currentData()
        if idx is None or idx<0: return
        with QMutexLocker(self._mutex):
            self._avg_buf.clear(); self._fft_smooth=None
            self._spl_smooth=-100.0; self._pending=None
            self._raw_spl_smooth  = -100.0
            self._raw_peak_smooth = -100.0
            self._dba_smooth      = -100.0
            self._dbc_smooth      = -100.0
        self.audio_thread=AudioThread(idx,self.sample_rate,self.fft_size)
        self.audio_thread.chunk_ready.connect(self._process_audio, Qt.QueuedConnection)
        self.audio_thread.error_signal.connect(self._on_audio_error, Qt.QueuedConnection)
        self.audio_thread.start()
        self.start_btn.setText('■  Stop'); self._stop_style(self.start_btn)
        self.status_lbl.setText('● Running')
        self.status_lbl.setStyleSheet(f'color:{T("green")};font-family:Arial;font-size:11px;')
        self.mic_st.setText('Connected')
        self.mic_st.setStyleSheet(f'color:{T("green")};font-size:10px;font-family:Arial;')
        self.i_sr.setText(f'{self.sample_rate/1000:.1f} kHz')
        self.i_fft.setText(str(self.fft_size))
        self.i_res.setText(f'{self.sample_rate/self.fft_size:.1f} Hz')
        freqs=np.fft.rfftfreq(self.fft_size,1.0/self.sample_rate)
        self._aw_table=np.array([a_weight_db(f) for f in freqs])
        self._cw_table=np.array([c_weight_db(f) for f in freqs])
        if self.compare_mode: self._start_b()

    def _stop(self):
        if self.compare_mode: self._stop_b()
        if self.audio_thread:
            try:
                self.audio_thread.chunk_ready.disconnect()
                self.audio_thread.error_signal.disconnect()
            except Exception: pass
            self.audio_thread.stop(); self.audio_thread=None
        with QMutexLocker(self._mutex):
            self._pending=None
            self._avg_buf.clear(); self._fft_smooth=None
            self._raw_spl_smooth=-100.0; self._raw_peak_smooth=-100.0
            self._dba_smooth=-100.0; self._dbc_smooth=-100.0
        self.start_btn.setText('▶  Start'); self._go_style(self.start_btn)
        self.status_lbl.setText('● Standby')
        self.status_lbl.setStyleSheet(f'color:{T("text_dim")};font-family:Arial;font-size:11px;')
        self.mic_st.setText('Disconnected')
        self.mic_st.setStyleSheet(f'color:{T("text_dim")};font-size:10px;font-family:Arial;')
        self.fft_cvs.clear(); self.oct_cvs.clear()
        self.vu_a.update_level(-100,-100,-100,-100)
        self.i_spl.setText('—'); self.i_pk.setText('—'); self.i_dom.setText('—')
        self.i_dba.setText('—'); self.i_dbc.setText('—')

    def _start_b(self):
        idx=self.dev_cb_b.currentData()
        if idx is None or idx<0: return
        with QMutexLocker(self._mutex_b):
            self._avg_buf_b.clear(); self._fft_smooth_b=None; self._pending_b=None
            self._raw_spl_smooth_b=-100.0; self._raw_peak_smooth_b=-100.0
            self._dba_smooth_b=-100.0; self._dbc_smooth_b=-100.0
        if self.audio_thread_b:
            try: self.audio_thread_b.chunk_ready.disconnect(); self.audio_thread_b.error_signal.disconnect()
            except Exception: pass
            self.audio_thread_b.stop(); self.audio_thread_b=None
        self.audio_thread_b=AudioThread(idx,self.sample_rate,self.fft_size)
        self.audio_thread_b.chunk_ready.connect(self._process_audio_b, Qt.QueuedConnection)
        self.audio_thread_b.error_signal.connect(self._on_audio_error_b, Qt.QueuedConnection)
        self.audio_thread_b.start()
        freqs=np.fft.rfftfreq(self.fft_size,1.0/self.sample_rate)
        self._aw_table_b=np.array([a_weight_db(f) for f in freqs])
        self._cw_table_b=np.array([c_weight_db(f) for f in freqs])

    def _stop_b(self):
        if self.audio_thread_b:
            try: self.audio_thread_b.chunk_ready.disconnect(); self.audio_thread_b.error_signal.disconnect()
            except Exception: pass
            self.audio_thread_b.stop(); self.audio_thread_b=None
        with QMutexLocker(self._mutex_b):
            self._pending_b=None; self._avg_buf_b.clear(); self._fft_smooth_b=None
            self._raw_spl_smooth_b=-100.0; self._raw_peak_smooth_b=-100.0
            self._dba_smooth_b=-100.0; self._dbc_smooth_b=-100.0
        self.vu_b.update_level(-100,-100,-100,-100)
        self.i_spl_b.setText('—'); self.i_pk_b.setText('—'); self.i_dom_b.setText('—')
        self.i_dba_b.setText('—'); self.i_dbc_b.setText('—')
        self.fft_cvs._ds_f_b=None; self.fft_cvs._ds_avg_b=None
        self.fft_cvs._ds_pk_b=None; self.fft_cvs._ds_diff=None; self.fft_cvs.peak_b=None
        for k in self.oct_cvs.smooth_b: self.oct_cvs.smooth_b[k][:]=self.oct_cvs.db_min
        for k in self.oct_cvs.peaks_b:  self.oct_cvs.peaks_b[k][:]=self.oct_cvs.db_min

    def _on_audio_error(self,msg):
        self._stop()
        self.status_lbl.setText('● 오류')
        self.status_lbl.setStyleSheet(f'color:{T("red")};font-family:Arial;font-size:11px;')
        self.mic_st.setText('장치 오류')
        self.mic_st.setStyleSheet(f'color:{T("red")};font-size:10px;font-family:Arial;')
        from PyQt5.QtWidgets import QMessageBox
        QMessageBox.warning(self,'오디오 오류',
            f'마이크 연결에 실패했습니다:\n{msg}\n\n'
            '시스템 설정 → 개인정보 보호 → 마이크에서 접근을 허용했는지 확인하세요.')

    def _on_audio_error_b(self,msg):
        self._stop_b()
        self.compare_btn.setChecked(False)
        self.compare_mode=False
        self._toggle_compare(False)
        from PyQt5.QtWidgets import QMessageBox
        QMessageBox.warning(self,'오디오 오류 (Input B)',
            f'Input B 마이크 연결에 실패했습니다:\n{msg}\n\n'
            '장치를 확인하고 다시 시도하세요.')

    def _on_device_b_changed(self, _):
        if self.compare_mode and self.audio_thread and self.audio_thread.isRunning():
            self._stop_b(); self._start_b()

    def _toggle_compare(self, checked):
        self.compare_mode=checked
        for w in [self._cmp_lbl,self.dev_cb_b,self.calib_btn_b,self.diff_btn]+self._compare_legend_widgets:
            w.setVisible(checked)
        self._lbl_vu_a.setVisible(checked); self._lbl_vu_b.setVisible(checked)
        self.vu_b.setVisible(checked)
        self._ch_b_box.setVisible(checked)
        self.fft_cvs.compare_mode=checked
        self.oct_cvs.compare_mode=checked
        if checked:
            self.compare_btn.setStyleSheet(
                'background:rgba(255,140,40,35);color:#ff8c28;'
                'border:2px solid rgba(255,140,40,150);'
                'font-weight:700;padding:3px 12px;border-radius:4px;')
            if self.audio_thread and self.audio_thread.isRunning():
                self._start_b()
        else:
            self.compare_btn.setStyleSheet('')
            self._stop_b()
        self.fft_cvs.update(); self.oct_cvs.update()

    def _toggle_diff(self, checked):
        self.fft_cvs.show_diff=checked
        if not checked: self.fft_cvs._ds_diff=None
        self.fft_cvs.update()

    def _open_calib_b(self):
        def get_raw_spl_b():
            with QMutexLocker(self._mutex_b):
                return self._raw_spl_smooth_b
        dlg=CalibDialog(self.calib_offset_b,get_raw_spl_b,self)
        if dlg.exec()==QDialog.Accepted:
            self.calib_offset_b=dlg.get_offset()
            device_name=self.dev_cb_b.currentText()
            if 'calibrations' not in self._settings:
                self._settings['calibrations']={}
            self._settings['calibrations'][device_name]=self.calib_offset_b
            _save_settings(self._settings)
            with QMutexLocker(self._mutex_b):
                self._avg_buf_b.clear(); self._fft_smooth_b=None

    # ── 오디오 처리
    def _process_audio(self,buf):
        if not np.isfinite(buf).all(): return
        n=len(buf)
        win=np.hanning(n).astype(np.float32)
        spec=np.abs(np.fft.rfft(buf*win)); np.maximum(spec,1e-10,out=spec)
        db_raw=20*np.log10(spec/(n/2))   # ★ raw dBFS — buf 실제 크기 기준
        freqs=np.fft.rfftfreq(n,1.0/self.sample_rate).astype(np.float32)

        s=self.smoothing
        with QMutexLocker(self._mutex):
            if self._fft_smooth is None or len(self._fft_smooth)!=len(db_raw):
                self._fft_smooth=db_raw.copy()
                # A/C 가중치 테이블을 실제 buf 크기에 맞게 재계산
                self._aw_table=np.array([a_weight_db(f) for f in freqs])
                self._cw_table=np.array([c_weight_db(f) for f in freqs])
            else:
                self._fft_smooth*=s; self._fft_smooth+=db_raw*(1-s)
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

    # ── 채널 B 오디오 처리
    def _process_audio_b(self,buf):
        if not np.isfinite(buf).all(): return
        n=len(buf)
        win=np.hanning(n).astype(np.float32)
        spec=np.abs(np.fft.rfft(buf*win)); np.maximum(spec,1e-10,out=spec)
        db_raw=20*np.log10(spec/(n/2))
        freqs=np.fft.rfftfreq(n,1.0/self.sample_rate).astype(np.float32)
        s=self.smoothing
        with QMutexLocker(self._mutex_b):
            if self._fft_smooth_b is None or len(self._fft_smooth_b)!=len(db_raw):
                self._fft_smooth_b=db_raw.copy()
                self._aw_table_b=np.array([a_weight_db(f) for f in freqs])
                self._cw_table_b=np.array([c_weight_db(f) for f in freqs])
            else:
                self._fft_smooth_b*=s; self._fft_smooth_b+=db_raw*(1-s)
            self._avg_buf_b.append(self._fft_smooth_b.copy())
            avg_raw_b=np.mean(list(self._avg_buf_b),axis=0)
            avg_cal_b=avg_raw_b+self.calib_offset_b
            rms_b=float(np.sqrt(np.mean(buf**2)))
            raw_dbfs_b=20*math.log10(max(rms_b,1e-10))
            va_b=0.7 if raw_dbfs_b>self._raw_spl_smooth_b else (0.03+self.speed_idx*0.04)
            self._raw_spl_smooth_b+=(raw_dbfs_b-self._raw_spl_smooth_b)*va_b
            if raw_dbfs_b>self._raw_peak_smooth_b: self._raw_peak_smooth_b=raw_dbfs_b
            else: self._raw_peak_smooth_b-=0.25
            dba_db_b=dbc_db_b=-100.0
            if self._aw_table_b is not None and len(self._aw_table_b)==len(db_raw):
                wa_b=db_raw+self._aw_table_b+self.calib_offset_b
                wc_b=db_raw+self._cw_table_b+self.calib_offset_b
                wa_b=np.clip(wa_b,-200,100); wc_b=np.clip(wc_b,-200,100)
                raw_dba_b=10*math.log10(max(float(np.sum(10**(wa_b/10))),1e-10))
                raw_dbc_b=10*math.log10(max(float(np.sum(10**(wc_b/10))),1e-10))
                self._dba_smooth_b+=(raw_dba_b-self._dba_smooth_b)*0.015
                self._dbc_smooth_b+=(raw_dbc_b-self._dbc_smooth_b)*0.015
                dba_db_b=self._dba_smooth_b; dbc_db_b=self._dbc_smooth_b
            self._pending_b=(
                freqs, avg_cal_b,
                self._raw_spl_smooth_b, self._raw_peak_smooth_b,
                self._raw_spl_smooth_b+self.calib_offset_b,
                self._raw_peak_smooth_b+self.calib_offset_b,
                dba_db_b, dbc_db_b
            )

    # ── 렌더링 타이머 (30fps)
    def _render_frame(self):
        with QMutexLocker(self._mutex):
            data=self._pending; self._pending=None
        if data is not None and self.audio_thread is not None:
            freqs,avg_cal,raw_spl,raw_peak,cal_spl,cal_peak,dba,dbc=data
            self.vu_a.update_level(raw_spl,raw_peak,cal_spl,cal_peak)
            self.i_spl.setText(f'{cal_spl:.1f} dB')
            self.i_pk.setText(f'{cal_peak:.1f} dB')
            pi=int(np.argmax(avg_cal)); df=float(freqs[pi])
            self.i_dom.setText(f'{df/1000:.2f}kHz' if df>=1000 else f'{df:.0f}Hz')
            now=time.time()
            if now-self._dba_display_t>=0.5:
                self.i_dba.setText(f'{dba:.1f}')
                self.i_dbc.setText(f'{dbc:.1f}')
                self._dba_display_t=now
            if self.view_mode=='fft': self.fft_cvs.set_data(freqs,avg_cal)
            else: self.oct_cvs.update_data(self.view_mode,self._calc_oct(freqs,avg_cal))

        if self.compare_mode:
            with QMutexLocker(self._mutex_b):
                data_b=self._pending_b; self._pending_b=None
            if data_b is not None and self.audio_thread_b is not None:
                freqs_b,avg_cal_b,raw_spl_b,raw_peak_b,cal_spl_b,cal_peak_b,dba_b,dbc_b=data_b
                self.vu_b.update_level(raw_spl_b,raw_peak_b,cal_spl_b,cal_peak_b)
                self.i_spl_b.setText(f'{cal_spl_b:.1f} dB')
                self.i_pk_b.setText(f'{cal_peak_b:.1f} dB')
                pi_b=int(np.argmax(avg_cal_b)); df_b=float(freqs_b[pi_b])
                self.i_dom_b.setText(f'{df_b/1000:.2f}kHz' if df_b>=1000 else f'{df_b:.0f}Hz')
                now_b=time.time()
                if now_b-self._dba_display_t_b>=0.5:
                    self.i_dba_b.setText(f'{dba_b:.1f}')
                    self.i_dbc_b.setText(f'{dbc_b:.1f}')
                    self._dba_display_t_b=now_b
                if self.view_mode=='fft': self.fft_cvs.set_data_b(freqs_b,avg_cal_b)
                else: self.oct_cvs.update_data_b(self.view_mode,self._calc_oct(freqs_b,avg_cal_b))


    def _calc_oct(self,freqs,db_vals):
        mode=self.view_mode; bands=BANDS[mode]
        bpo=3 if mode=='oct3' else 12 if mode=='oct12' else 24
        half=1/(2*bpo)
        res=[]
        for fc in bands:
            fl,fh=fc/2**half,fc*2**half; mask=(freqs>=fl)&(freqs<=fh)
            if mask.any():
                res.append(float(np.mean(db_vals[mask])))
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
    def _set_view(self,m):
        self.view_mode=m
        for k,b in self.view_btns.items(): b.setChecked(k==m)
        self.log_btn.setEnabled(m=='fft'); self.lin_btn.setEnabled(m=='fft')
        if m=='fft': self.fft_cvs.show(); self.oct_cvs.hide()
        else:        self.fft_cvs.hide(); self.oct_cvs.show(); self.oct_cvs.set_mode(m)

    def _sr_changed(self,idx):
        self.sample_rate=[44100,48000][idx]
        self.i_sr.setText(f'{self.sample_rate/1000:.1f} kHz')
        self.i_res.setText(f'{self.sample_rate/self.fft_size:.1f} Hz')
        if self.audio_thread and self.audio_thread.isRunning(): self._stop(); self._start()

    def _fft_changed(self,idx):
        self.fft_size=[16384][idx]
        with QMutexLocker(self._mutex): self._fft_smooth=None; self._avg_buf.clear()
        self.i_fft.setText(str(self.fft_size))
        self.i_res.setText(f'{self.sample_rate/self.fft_size:.1f} Hz')
        self.fft_cvs.fft_size=self.fft_size
        if self.audio_thread and self.audio_thread.isRunning(): self._stop(); self._start()

    def _set_scale(self,log):
        self.log_btn.setChecked(log); self.lin_btn.setChecked(not log)
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

    def _set_peak_hold_time(self, idx):
        # dB/frame: 30dB 낙하 기준 (1s=빠름 ~ 10s=느림, @~30fps)
        rate = [1.0, 0.5, 0.33, 0.2, 0.1][idx]
        self.fft_cvs.set_peak_hold_time(rate)
        self.oct_cvs.set_peak_hold_time(rate)

    def _db_changed(self,idx):
        self.db_range=[72,96,120][idx]; self.db_min=self.db_max-self.db_range
        self._apply_db_range()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Up:
            self.db_min+=5; self.db_max+=5; self._apply_db_range()
        elif e.key() == Qt.Key_Down:
            self.db_min-=5; self.db_max-=5; self._apply_db_range()
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

    def closeEvent(self,e): self._render_t.stop(); self._stop_b(); self._stop(); e.accept()


if __name__=='__main__':
    from PyQt5.QtGui import QPixmap

    # ── macOS Monterey+ Retina / High-DPI 지원
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps,   True)

    app = QApplication(sys.argv)
    app.setApplicationName('WSA Spectrum Analyzer')

    # ── PyInstaller 번들 내 리소스 경로
    def _res(name):
        base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(base, name)

    splash = None
    splash_img = _res('splash.png')
    if os.path.exists(splash_img):
        pix = QPixmap(splash_img)
        # Retina 디스플레이에서 선명하게 표시
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

    win = MainWindow()
    if splash:
        def _launch():
            win.show()
            splash.close()
        QTimer.singleShot(3000, _launch)
    else:
        win.show()
    sys.exit(app.exec())
