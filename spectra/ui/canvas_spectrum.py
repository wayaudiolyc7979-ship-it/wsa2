"""스펙트럼 캔버스 — FFT/옥타브/스펙트로그램(메인 Spectrum 탭 3뷰).

v2.0 분해: wayaudo2.py에서 이동(동작 0 변경).
"""
import math, time, threading
import numpy as np
from PyQt5.QtGui import (QBrush, QColor, QImage, QPainter, QPainterPath, QPen,
                         QPixmap, QPolygon, QPolygonF)
from PyQt5.QtCore import Qt, QPoint, QPointF, QSize, pyqtSignal
from PyQt5.QtWidgets import QSizePolicy, QWidget
from spectra.core.config import T, is_dark, MAX_DB, SPEC_ATTACK, SPEED_LEVELS, FREQ_MARKS
from spectra.dsp.weighting import BANDS, thd_from_spectrum
from spectra.ui.tokens import CF_ANNO, CF_GRID, CF_MODE, CF_TINY, _qfont
from spectra.ui.colors import _spectra_grad_brush, _spectra_grad_pen, _vbar_gradient, bar_top
from spectra.ui.draw import (freq_to_x, x_to_freq, db_to_y, draw_info_box, draw_dom_badge,
                             freq_to_note, _focused_capture_visible, _draw_idle_hint,
                             _draw_tf_sel_border)

# 커서 리드아웃/도미넌트 배지 값 평활 [RDOUT] — 시정수(초). 값↑=더 느림/차분, ↓=더 즉각.
# ★시간기반: 페인트가 몇 fps든 체감 속도 일정(프레임당 계수는 페인트율 빠르면 더 빨리 수렴하는 버그).
_RDOUT_TAU = 2.5

def _smooth_dom(cv, f, db):
    """도미넌트 배지(최대 주파수+레벨) 평활 — argmax가 프레임마다 튀어 배지가 깜빡임.
    주파수가 크게(>~1/7oct) 바뀌면 다른 봉우리로 점프 → 스냅, 작은 흔들림은 시간기반 EMA로 느리게.
    반환 (f_smooth, db_smooth). cv._dom_f/_dom_db/_dom_t 상태 사용."""
    now = time.time()
    if cv._dom_f is None or abs(math.log2(max(f, 1e-9) / max(cv._dom_f, 1e-9))) > 0.10:
        cv._dom_f = f; cv._dom_db = db; cv._dom_t = now
    else:
        dt = now - cv._dom_t if 0.0 < now - cv._dom_t < 1.0 else 0.033
        cv._dom_t = now; a = 1.0 - math.exp(-dt / _RDOUT_TAU)
        cv._dom_f *= (f / cv._dom_f) ** a                # 주파수는 로그(기하) 보간
        cv._dom_db += (db - cv._dom_db) * a
    return cv._dom_f, cv._dom_db

def _smooth_readout(cv, freq, db, thd):
    """커서 리드아웃(dB·THD%) 값 평활 — 매 프레임 raw면 너무 빨리 튀어 안 읽힘.
    커서 주파수가 바뀌면(>~1/33oct) 새 위치 값으로 즉시 스냅, 그 안에선 시간기반 EMA로 느리게.
    반환 (db_smooth, thd_smooth|None). cv._rd_db/_rd_thd/_rd_f/_rd_t 상태 사용."""
    now = time.time()
    if cv._rd_f is None or abs(math.log2(max(freq, 1e-9) / max(cv._rd_f, 1e-9))) > 0.03:
        cv._rd_db = db; cv._rd_thd = thd; cv._rd_t = now          # 커서 이동 → 새 위치 값으로 스냅
    else:
        dt = now - cv._rd_t if 0.0 < now - cv._rd_t < 1.0 else 0.033
        cv._rd_t = now
        a = 1.0 - math.exp(-dt / _RDOUT_TAU)                       # 페인트율 무관 체감 일정
        cv._rd_db += (db - cv._rd_db) * a
        cv._rd_thd = (None if thd is None else
                      thd if cv._rd_thd is None else cv._rd_thd + (thd - cv._rd_thd) * a)
    cv._rd_f = freq
    return cv._rd_db, cv._rd_thd


class FFTCanvas(QWidget):
    PAD_L=40; PAD_R=10; PAD_T=12; PAD_B=28
    _DB_LOCKABLE=True   # dB축 수동 고정 아이콘 표시
    MAX_POINTS=600   # primary 곡선 포인트 수
    MAX_POINTS_EXTRA=600   # 추가 곡선 포인트 수 (원복: primary 와 동일)
    _idle_hint=True   # 시작 전 브랜드 엠프티 스테이트 표시
    _cap_built = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setMinimumSize(300,150)
        self.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Expanding)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WA_OpaquePaintEvent,True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.db_min=-96; self.db_max=MAX_DB; self._db_lock=False
        self.freqs=None; self.avg=None; self.peak=None
        self.peak_hold=True; self.scale_log=True
        self.sample_rate=48000; self.fft_size=16384
        self._show_thd=False              # 커서 THD 표시(우클릭 'Show THD'로 토글) [THD]
        self._rd_db=None; self._rd_thd=None; self._rd_f=None; self._rd_t=0.0   # 리드아웃 값 평활(시간기반) [RDOUT]
        self._dom_f=None; self._dom_db=None; self._dom_t=0.0   # 도미넌트 배지 평활 [RDOUT]
        self._mx=-1; self._my=-1
        self.peak_hold_frames=30         # 기본 1초 홀드 (30fps 기준)
        self.peak_decay_rate_pk=20.0/30.0  # 20 dB/s 고정 낙하
        self._peak_age=None
        self._cache=None
        self._grad_fill_pix=None; self._grad_fill_key=None   # 그라디언트 채움 캐시(픽셀별 계산 회피)
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
        self._ch_visible = {}  # {card_id: bool} — 데이터 도착 전에도 유지되는 채널 가시성(소스 카드와 동기화)
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
        self._ch_curves[ch_idx] = {'color': color, 'ds_f': ds_f, 'ds_avg': ds_avg,
                                   'visible': self._ch_visible.get(ch_idx, True)}
        self.update()

    def set_channel_visible(self, ch_idx, vis):
        """채널 가시성 — 데이터 도착 전에도 유지(소스 카드 체크박스와 동기화)."""
        self._ch_visible[ch_idx] = vis
        if ch_idx in self._ch_curves:
            self._ch_curves[ch_idx]['visible'] = vis
        self.update()

    def clear_channel(self, ch_idx):
        self._ch_curves.pop(ch_idx, None); self._ch_visible.pop(ch_idx, None); self.update()

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

    def _draw_cap_curve(self, p, cap, W, H, emph=False):
        # 단일 캡쳐 곡선 — 베이스(dimmed)·front 오버레이(emph=밝고 굵게) 공용
        ny=min(self.sample_rate/2, 20000)
        pl=self.PAD_L; pr=self.PAD_R; pt=self.PAD_T; pb=self.PAD_B
        dh=H-pt-pb; uw=W-pl-pr
        max_pts = max(int(uw) * 2, 512)
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

    def _build_cap_img(self, W, H, caps, front):
        # 베이스 이미지 = 보이는 캡쳐 전부 dimmed. front 강조는 paintEvent 오버레이라 여기선 안 그림.
        from PyQt5.QtGui import QImage
        img=QImage(W,H,QImage.Format_ARGB32_Premultiplied); img.fill(0)
        p=QPainter(img); p.setRenderHint(QPainter.Antialiasing,True)
        for cap in caps:
            if not cap.get('visible', True): continue
            self._draw_cap_curve(p, cap, W, H, emph=False)
        p.end()
        return img

    def _cap_base_key(self, n=None):
        ny=min(self.sample_rate/2, 20000)
        if n is None: n=len(self._captures)
        return (self.width(), self.height(), self.db_max, self.db_min, self.scale_log, int(ny), n)

    def _append_cap_incr(self, cap):
        # 베이스 캐시 유효 시 새 캡쳐 1개만 dimmed로 얹기(O(1)). 무효면 다음 paint에서 전체 rebuild.
        if self._cap_pix is not None and self._cap_pix_key==self._cap_base_key(len(self._captures)-1) and cap.get('visible', True):
            p=QPainter(self._cap_pix); p.setRenderHint(QPainter.Antialiasing,True)
            self._draw_cap_curve(p, cap, self._cap_pix.width(), self._cap_pix.height(), emph=False)
            p.end()
            self._cap_pix_key=self._cap_base_key()   # 새 count 반영 → 재빌드 안 함
        else:
            self._cap_pix=None

    def _build_cap_pix(self, W, H):
        img = self._build_cap_img(W, H, list(self._captures), self._front_idx)
        self._cap_pix = QPixmap.fromImage(img)
        self._cap_pix_key = self._cap_base_key()

    def add_capture(self, label, color, group=''):
        if self._ds_f is None or self._ds_avg is None: return False   # 호출부가 성공여부로 카운트
        cap={'f': self._ds_f.copy(), 'db': self._ds_avg.copy(),
             'color': color, 'label': label, 'group': group}
        self._captures.append(cap)
        self._append_cap_incr(cap)          # O(1) 증분 — 전체 재빌드 안 함
        self._last_cap_t=time.monotonic(); self.update()
        return True

    def add_capture_data(self, label, color, f, db, group=''):
        """추가 소스 곡선을 캡쳐 (멀티 소스 일괄 캡쳐용)."""
        if f is None or db is None: return
        cap={'f': np.asarray(f, dtype=np.float64).copy(), 'db': np.asarray(db, dtype=np.float64).copy(),
             'color': color, 'label': label, 'group': group}
        self._captures.append(cap)
        self._append_cap_incr(cap)
        self._last_cap_t=time.monotonic(); self.update()

    def recapture(self, idx):
        """기존 캡쳐 idx 의 곡선만 현재 라이브값으로 덮어쓰기 (색/이름/그룹/가시성 유지)."""
        if self._ds_f is None or self._ds_avg is None: return False
        if not (0 <= idx < len(self._captures)): return False
        c = self._captures[idx]
        c['f'] = self._ds_f.copy(); c['db'] = self._ds_avg.copy()
        self._cap_pix=None; self._last_cap_t=time.monotonic(); self.update()
        return True

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
            self.update()   # front=paintEvent 오버레이 → 베이스 재빌드 불필요

    def _grad_fill_pixmap(self, W, H, x0, x1, alpha):
        """브랜드 그라디언트 채움용 캐시 픽스맵 — 픽셀별 그라디언트 계산을 1회로(크기/색 동일 시 재사용)."""
        key=(W, H, x0, x1, alpha)
        if self._grad_fill_key != key or self._grad_fill_pix is None:
            pm=QPixmap(W, H); pm.fill(Qt.transparent)
            gp=QPainter(pm); gp.fillRect(0, 0, W, H, _spectra_grad_brush(x0, x1, alpha)); gp.end()
            self._grad_fill_pix=pm; self._grad_fill_key=key
        return self._grad_fill_pix

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
            # 선 AA OFF — Retina 전체화면 성능(float 좌표라 계단현상은 없음)
            for cid, ch_data in sorted(self._ch_curves.items(), key=lambda kv: kv[0]==self._front_id):
                if not ch_data.get('visible', True): continue
                f_c=ch_data['ds_f']; a_c=ch_data['ds_avg']
                if f_c is None or len(f_c)<2: continue
                xc=pl+(np.log10(np.maximum(f_c,1)/20)/math.log10(ny/20))*uw if self.scale_log else pl+(f_c/ny)*uw
                yc=pt+np.clip((self.db_max-a_c)/(self.db_max-self.db_min)*dh,0,dh)
                sc=QPainterPath(); sc.moveTo(float(xc[0]),float(yc[0]))
                for x,y in zip(xc[1:],yc[1:]): sc.lineTo(float(x),float(y))
                p.setPen(QPen(_ch_col(ch_data['color']),1.8)); p.drawPath(sc)
            return
        if self.scale_log:
            xs=pl+(np.log10(np.maximum(f_arr,1)/20)/math.log10(ny/20))*uw
        else:
            xs=pl+(f_arr/ny)*uw
        ys=pt+np.clip((self.db_max-a_arr)/(self.db_max-self.db_min)*dh,0,dh)
        if self.clipping:
            top_col=QColor(T('red')); line_col=QColor(T('red')); pk_col=QColor(T('red'))
        else:
            top_col=QColor(*bar_top()); line_col=QColor(T('spec_line')); pk_col=QColor(T('peak_line'))
            top_col.setAlpha(50)   # 그라디언트 선이 주인공 — 채움은 연하게(은은한 배경)
        if dim:   # 캡쳐 포커스 시 라이브 채움/선 흐리게
            top_col.setAlpha(28); line_col.setAlpha(70); pk_col.setAlpha(70)
        if self.clipping:
            # 클리핑: 전체 빨강 채움 경고 (드물어서 비용 무관)
            path=QPainterPath()
            path.moveTo(float(xs[0]),float(H-pb))
            for x,y in zip(xs,ys): path.lineTo(float(x),float(y))
            path.lineTo(float(xs[-1]),float(H-pb)); path.closeSubpath()
            p.fillPath(path,QBrush(top_col))
        else:
            # 글로우 밴드: 선 아래 일정 높이(BAND)만 그라디언트 채움 → 채운 면적이 음량과 무관하게 일정
            #   = 전체화면/큰소리에서도 안 무거움. 캐시 그라디언트 픽스맵을 밴드 모양으로 잘라 blit.
            BAND = 72.0
            bot = np.minimum(ys + BAND, float(H-pb))
            bandpath = QPainterPath()
            bandpath.moveTo(float(xs[0]), float(ys[0]))
            for x,y in zip(xs, ys): bandpath.lineTo(float(x), float(y))
            for x,y in zip(xs[::-1], bot[::-1]): bandpath.lineTo(float(x), float(y))
            bandpath.closeSubpath()
            _gpm=self._grad_fill_pixmap(W, H, pl, W-pr, 18 if dim else 60)
            p.save(); p.setClipPath(bandpath); p.drawPixmap(0,0,_gpm); p.restore()
        # 선 AA OFF — Retina 전체화면 성능 (float 좌표라 계단현상 없음, 채움/선 모두 AA 미사용)
        stroke=QPainterPath()
        stroke.moveTo(float(xs[0]),float(ys[0]))
        for x,y in zip(xs[1:],ys[1:]): stroke.lineTo(float(x),float(y))
        if self.clipping:
            p.setPen(QPen(line_col,2.0))   # 클리핑: 전체 빨강 경고 유지(브랜드 그라디언트 미적용)
        else:
            p.setPen(_spectra_grad_pen(pl, pl+uw, 2.2, 70 if dim else 255))   # SPECTRA 그라디언트 곡선
        p.drawPath(stroke)
        if self.peak_hold and self._ds_pk is not None:
            py_arr=pt+np.clip((self.db_max-self._ds_pk)/(self.db_max-self.db_min)*dh,0,dh)
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
            yc = pt + np.clip((self.db_max - a_c) / (self.db_max - self.db_min) * dh, 0, dh)
            sc = QPainterPath()
            sc.moveTo(float(xc[0]), float(yc[0]))
            for x, y in zip(xc[1:], yc[1:]): sc.lineTo(float(x), float(y))
            p.setPen(QPen(_ch_col(ch_data['color']), 1.8)); p.drawPath(sc)
        # front 가 primary 면 primary 라인을 맨 위에 다시 (그라디언트 유지).
        # 단 채널 오버레이가 있을 때만 — 채널이 없으면 메인 곡선이 이미 맨 위라 중복(전체화면 버벅임 방지).
        if self._front_id == 0 and self._ch_curves:
            if self.clipping:
                p.setPen(QPen(line_col, 2.4))
            else:
                p.setPen(_spectra_grad_pen(pl, pl+uw, 2.4, 70 if dim else 255))
            p.drawPath(stroke)

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
        _lg=p.fontMetrics().height()+2; _last_ly=None   # 짧은(분할) 뷰서 라벨 겹침 방지(그리드는 유지)
        for db in range(int(self.db_min),int(self.db_max)+1,12):
            y=pt+db_to_y(db,dh,self.db_min,self.db_max)
            if not pt<=y<=H-pb: continue
            is0=(db==0)
            p.setPen(QPen(QColor(T('grid_ref')),1.5 if is0 else 0.7,Qt.SolidLine))
            p.drawLine(pl,y,W-pr,y)
            if _last_ly is None or abs(y-_last_ly)>=_lg:
                p.setPen(QColor(T('graph_txt')))
                p.drawText(2,y-10,pl-12,20,Qt.AlignRight|Qt.AlignVCenter,str(db)); _last_ly=y
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
        if e.x()<self.PAD_L:
            _w=self.window()
            if hasattr(_w,'_spec_db_autofit'):   # 창 상태(db_max/min·_pending_auto_fit·persist)까지 일원화
                _w._spec_db_autofit(); return
            # 폴백(팝아웃 등 창 핸들러 없음) — 캔버스 로컬 자동맞춤
            if self._ds_avg is None or len(self._ds_avg)==0: return
            valid=self._ds_avg[self._ds_avg>-90]
            if len(valid)==0: return
            self._db_lock=False
            peak=float(np.max(valid)); span=self.db_max-self.db_min
            self.db_max=int(math.ceil((peak+12)/12))*12
            self.db_min=self.db_max-span; self._cache=None; self.update()
    def contextMenuEvent(self,e):
        _w=self.window()
        if hasattr(_w,'_spec_db_menu'): _w._spec_db_menu(e.globalPos())
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
            if self._idle_hint: _draw_idle_hint(p, pl, pt, uw, dh)
            p.end(); return
        f_arr=self._ds_f; a_arr=self._ds_avg
        if a_arr is None or len(a_arr)!=len(f_arr):
            p.end(); return

        # E 포커스: 캡쳐 선택 → 라이브 흐리게 + 선택 캡쳐 밝게(위) / 라이브 포커스 → 캡쳐 흐리게 + 라이브(위)
        # 단 포커스된 캡쳐가 '보이는' 상태일 때만 — 숨긴 캡쳐가 포커스면 라이브를 흐리게 두지 않음
        _cap_focus = _focused_capture_visible(self)
        def _draw_caps():
            if not self._captures: return
            _cap_key=self._cap_base_key()   # 개수 포함 7-튜플 — 증분 경로와 일치(다른 캔버스와 동일)
            if self._cap_pix is None or self._cap_pix_key!=_cap_key:
                self._trigger_cap_build(W, H, _cap_key)
            if self._cap_pix is not None:
                p.drawPixmap(0,0,self._cap_pix)
            fi=self._front_idx
            if fi is not None and 0<=fi<len(self._captures) and self._captures[fi].get('visible',True):
                self._draw_cap_curve(p, self._captures[fi], W, H, emph=True)   # 선택 캡쳐 강조(재빌드 없이)
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
        dom_f, dom_db = _smooth_dom(self, dom_f, dom_db)   # [RDOUT] 배지 평활(느리게)
        dom_fs=f'{dom_f/1000:.2f} kHz' if dom_f>=1000 else f'{dom_f:.0f} Hz'
        unit='dBSPL' if self.calib_offset else 'dB'
        draw_dom_badge(p, W-pr, pt, dom_fs, dom_db, unit)

        # 커서 — 포커스된 캡쳐가 있으면 그 값을, 없으면 라이브 값을 읽음
        if pl<=self._mx<=W-pr:
            cx=self._mx
            _cf=f_arr; _ca=a_arr; _cap_col=None
            if _focused_capture_visible(self):
                _cap=self._captures[self._front_idx]
                _cf=_cap.get('f'); _ca=_cap.get('db'); _cap_col=_cap.get('color')
            if _cf is not None and _ca is not None and len(_cf)>0:
                freq=x_to_freq(cx,pl,uw,ny) if self.scale_log else (cx-pl)/uw*ny
                fs=f'{freq/1000:.2f} kHz' if freq>=1000 else f'{freq:.0f} Hz'
                fs=f'{fs}   {freq_to_note(freq)}'
                idx=int(np.clip(np.argmin(np.abs(_cf-freq)),0,len(_ca)-1))
                db=float(_ca[idx])
                _thd_val=None                          # [THD] 커서=기본파 가정. 표시 db와 같은 소스로
                if self._show_thd:                     # 계산(캡쳐 포커스면 캡쳐, 아니면 라이브 — 값 불일치 방지)
                    _r=thd_from_spectrum(_cf, _ca, freq)
                    if _r is not None: _thd_val=_r[0]
                db, _thd_v = _smooth_readout(self, freq, db, _thd_val)   # [RDOUT] 값 평활(느리게)
                _thd_str=f'THD {_thd_v:.2f}%' if _thd_v is not None else None
                # 가로선은 마우스 Y가 아니라 곡선 값 위치에 (매그니튜드 방식) — 평활된 값 사용
                cy=int(pt+np.clip((self.db_max-db)/(self.db_max-self.db_min)*(H-pt-pb),0,H-pt-pb))
                p.setPen(QPen(QColor(T('accent')).lighter(80) if (not is_dark()) else QColor(T('accent')),
                             1,Qt.DashLine))
                p.drawLine(cx,pt,cx,H-pb); p.drawLine(pl,cy,W-pr,cy)
                draw_info_box(p,W,fs,f'{db:.1f} {unit}', pk_str=_thd_str, cx=cx, x_lo=pl, x_hi=W-pr, top=pt,
                              val_color=_cap_col or QColor(*bar_top()[:3]))
        p.end()

# ───────────────────────────────────────────
#  옥타브 캔버스
# ───────────────────────────────────────────


class OctaveCanvas(QWidget):
    PAD_L=40; PAD_R=10; PAD_T=12; PAD_B=28
    _DB_LOCKABLE=True   # dB축 수동 고정 아이콘 표시
    _idle_hint=True   # 시작 전 브랜드 엠프티 스테이트 표시
    _cap_built = pyqtSignal()
    def __init__(self):
        super().__init__()
        self.setMinimumSize(300,150)
        self.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Expanding)
        self.setMouseTracking(True); self.setAttribute(Qt.WA_OpaquePaintEvent,True)
        self.setFocusPolicy(Qt.StrongFocus)
        self._show_thd=False              # 커서 THD 표시(우클릭 'Show THD'로 토글) [THD]
        self._rd_db=None; self._rd_thd=None; self._rd_f=None; self._rd_t=0.0   # 리드아웃 값 평활(시간기반) [RDOUT]
        self._dom_f=None; self._dom_db=None; self._dom_t=0.0   # 도미넌트 배지 평활 [RDOUT]
        self.mode='oct3'
        self.title_text=''   # 설정 시 좌상단 제목 표시(TF의 RTA 칸용; Spectrum 옥타브는 빈값)
        self.smooth={k:np.full(len(v),-96.0) for k,v in BANDS.items()}
        self.peaks ={k:np.full(len(v),-96.0) for k,v in BANDS.items()}
        self.db_min=-96; self.db_max=MAX_DB; self._db_lock=False
        self.peak_hold=True; self.alpha=1.0-SPEED_LEVELS[2][1]; self.decay=0.08
        self.attack=SPEC_ATTACK   # 상승(어택) 계수 — self.alpha(하강/릴리즈)보다 빠름
        self.peak_hold_frames=30           # 기본 1초 홀드 (30fps)
        self.peak_decay_rate_pk=20.0/30.0  # 20 dB/s 고정 낙하
        self._peak_age ={k:np.zeros(len(v),dtype=np.int32) for k,v in BANDS.items()}
        self._cache=None
        self._mx=-1; self._my=-1
        self._ch_oct={}   # {card_id: {'color','values'(oct band dB array),'visible'}} — 멀티-소스 막대 오버레이
        self._ch_visible={}  # {card_id: bool} — 데이터 도착 전에도 유지되는 채널 가시성
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

    def _draw_cap_curve(self, p, cap, W, H, emph=False):
        # 단일 옥타브 캡쳐 막대 — 베이스(옅은 채움+외곽선)·front 오버레이(emph=솔리드 그라디언트) 공용
        if cap['mode']!=self.mode: return
        pl=self.PAD_L; pr=self.PAD_R; pt=self.PAD_T; pb=self.PAD_B
        dh=H-pt-pb; uw=W-pl-pr
        db_range=max(self.db_max-self.db_min,1)
        bands=BANDS[self.mode]; n=len(bands)
        bar_w=uw/n if n else 1
        gap_r=0.06 if self.mode=='oct24' else 0.08 if self.mode=='oct12' else 0.12
        gap=max(1.0,bar_w*gap_r)
        cv=cap['values']; qc=QColor(cap['color'])
        if emph:
            cbrush, ccap = _vbar_gradient(qc)   # 캡쳐 front 막대도 라이브와 같은 입체 그라디언트
            for i in range(n):
                db=float(np.clip(cv[i],self.db_min,self.db_max))
                bh=max(2,int((db-self.db_min)/db_range*dh))
                bx=int(pl+i*bar_w+gap/2); bw=max(1,int(bar_w-gap)); by=pt+dh-bh
                p.fillRect(bx,by,bw,bh,cbrush)
                if bh>5: p.fillRect(bx,by,bw,1,ccap)
        else:
            qf=QColor(qc); qf.setAlpha(26); qe=QColor(qc); qe.setAlpha(110)
            for i in range(n):
                db=float(np.clip(cv[i],self.db_min,self.db_max))
                bh=max(2,int((db-self.db_min)/db_range*dh))
                bx=int(pl+i*bar_w+gap/2); bw=max(1,int(bar_w-gap)); by=pt+dh-bh
                p.fillRect(bx,by,bw,bh,qf)
                p.setPen(QPen(qe,1)); p.drawRect(bx,by,bw-1,bh-1)

    def _build_cap_img(self, W, H, caps, front):
        # 베이스 = 보이는 캡쳐 전부 dimmed. front 강조는 paintEvent 오버레이.
        from PyQt5.QtGui import QImage
        img=QImage(W,H,QImage.Format_ARGB32_Premultiplied); img.fill(0)
        p=QPainter(img)
        for cap in caps:
            if not cap.get('visible', True): continue
            self._draw_cap_curve(p, cap, W, H, emph=False)
        p.end()
        return img

    def _cap_base_key(self, ncap=None):
        bands=BANDS[self.mode]; n=len(bands)
        pl=self.PAD_L; pr=self.PAD_R; uw=self.width()-pl-pr
        bar_w=uw/n if n else 1
        gap_r=0.06 if self.mode=='oct24' else 0.08 if self.mode=='oct12' else 0.12
        gap=max(1.0,bar_w*gap_r)
        if ncap is None: ncap=len(self._captures)
        return (self.width(),self.height(),self.db_max,self.db_min,self.mode,round(bar_w*1000),round(gap*1000),ncap)

    def _append_cap_incr(self, cap):
        # 베이스 유효 시 새 캡쳐 1개만 dimmed로 얹기(O(1)). 무효면 다음 paint에서 전체 rebuild.
        if self._cap_pix is not None and self._cap_pix_key==self._cap_base_key(len(self._captures)-1) and cap.get('visible', True):
            p=QPainter(self._cap_pix)
            self._draw_cap_curve(p, cap, self._cap_pix.width(), self._cap_pix.height(), emph=False)
            p.end()
            self._cap_pix_key=self._cap_base_key()   # 새 count 반영 → 재빌드 안 함
        else:
            self._cap_pix=None

    def _build_cap_pix(self, W, H):
        img = self._build_cap_img(W, H, list(self._captures), self._front_idx)
        self._cap_pix = QPixmap.fromImage(img)
        self._cap_pix_key = self._cap_base_key()

    def add_capture(self, label, color, group=''):
        # 라이브 데이터 없을 때(시작 전/Stop 후) 캡쳐 금지 — FFTCanvas의 `_ds_f is None` 가드와 동치.
        # 없으면 −96dB 바닥 배열이 '정상 캡쳐'로 저장돼 재시작 후에도 유령 곡선이 남는다.
        if self._idle_hint: return False
        cap={'values': self.smooth[self.mode].copy(),
             'mode': self.mode, 'color': color, 'label': label, 'group': group}
        self._captures.append(cap)
        self._append_cap_incr(cap)
        self._last_cap_t=time.monotonic(); self.update()
        return True

    def add_capture_data(self, label, color, values, mode=None, group=''):
        """추가 소스 옥타브 곡선을 캡쳐 (멀티 소스 일괄 캡쳐용)."""
        if values is None: return
        cap={'values': np.asarray(values, dtype=np.float64).copy(),
             'mode': mode or self.mode, 'color': color, 'label': label, 'group': group}
        self._captures.append(cap)
        self._append_cap_incr(cap)
        self._last_cap_t=time.monotonic(); self.update()

    def recapture(self, idx):
        """기존 옥타브 캡쳐 idx 를 현재 라이브값으로 덮어쓰기 (색/이름/그룹/가시성 유지)."""
        # ★ 라이브 데이터 없으면 덮어쓰지 않는다(FFTCanvas.recapture와 동일 정책).
        #   없으면 Stop 상태에서 Recapture(R) 한 번에 멀쩡한 캡쳐가 −96dB 평평한 선으로
        #   파괴되고 그대로 디스크에 저장돼 재시작 후에도 복구 불가였다.
        if self._idle_hint: return False
        if not (0 <= idx < len(self._captures)): return False
        c = self._captures[idx]
        c['values'] = self.smooth[self.mode].copy(); c['mode'] = self.mode
        self._cap_pix=None; self._last_cap_t=time.monotonic(); self.update()
        return True

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
            self.update()   # front=paintEvent 오버레이 → 베이스 재빌드 불필요

    def _draw_live(self, p, W, H, dim=False):
        if self._idle_hint: return   # 시작 전 빈 상태 — 바닥(floor) 막대/선 안 그림(초록 바닥선 제거)
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
        # 막대 세로 그라디언트(위 밝게→아래 어둡게) + 상단 sheen 캡 — 입체 프리미엄 룩, 색 의미(클리핑=빨강) 유지.
        _bar_brush, cap_col = _vbar_gradient(col)
        for i in range(n):
            db=float(np.clip(sm[i],self.db_min,self.db_max))
            lp=(db-self.db_min)/db_range; bh=max(2,int(lp*dh))
            bx=int(pl+i*bar_w+gap/2); bw=max(1,int(bar_w-gap)); by=pt+dh-bh
            p.fillRect(bx,by,bw,bh,_bar_brush)
            if bh>5: p.fillRect(bx,by,bw,1,cap_col)   # 상단 sheen 하이라이트
            if self.peak_hold and pk[i]>sm[i]+1.5 and pk[i]>self.db_min+2:
                lp2=float(np.clip((pk[i]-self.db_min)/db_range,0,1))
                py2=pt+dh-max(2,int(lp2*dh))
                p.fillRect(bx,py2-1,bw,2,pk_col)

    # ── 멀티-소스 라인 오버레이 (추가 장치/채널 카드) ──
    def set_channel_oct(self, cid, color, values):
        vals = np.asarray(values, dtype=np.float64)
        # primary 막대(update_data)와 동일한 캔버스 ballistic(alpha IIR)을 추가 소스에도 적용.
        # 안 하면 primary만 캔버스 평활이 한 번 더 들어가 같은 마이크라도 추가 카드가
        # 어택에서 먼저 튀어오름(응답 속도 불일치).
        # ballistic은 소스단(_process_extra_source)에서 적용 — 여기선 그대로 표시
        # (primary 막대와 동일 위치/계수라 응답 일치)
        self._ch_oct[cid] = {'color': color, 'values': vals,
                             'visible': self._ch_visible.get(cid, True)}
        self.update()
    def set_channel_visible(self, cid, vis):
        self._ch_visible[cid] = vis
        if cid in self._ch_oct:
            self._ch_oct[cid]['visible'] = vis
        self.update()
    def clear_channel(self, cid):
        self._ch_oct.pop(cid, None); self._ch_visible.pop(cid, None); self.update()
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
        # ballistic(빠른 상승·느린 하강)은 소스단(_process_audio/_process_extra_source)에서
        # 단일 적용 → 캔버스는 그대로 표시(이중 평활 제거로 하강이 자연스러움)
        sm[:]=vals
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
        _lg=p.fontMetrics().height()+2; _last_ly=None   # 짧은(분할) 뷰서 라벨 겹침 방지(그리드는 유지)
        for db in range(int(self.db_min),int(self.db_max)+1,12):
            y=pt+db_to_y(db,dh,self.db_min,self.db_max)
            if not pt<=y<=H-pb: continue
            is0=(db==0)
            p.setPen(QPen(QColor(T('grid_ref')),1.5 if is0 else 0.7,Qt.SolidLine))
            p.drawLine(pl,y,W-pr,y)
            if _last_ly is None or abs(y-_last_ly)>=_lg:
                p.setPen(QColor(T('graph_txt')))
                p.drawText(2,y-10,pl-12,20,Qt.AlignRight|Qt.AlignVCenter,str(db)); _last_ly=y
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
            _w=self.window()
            if hasattr(_w,'_spec_db_autofit'):   # 창 상태까지 일원화 (FFT 캔버스와 동일)
                _w._spec_db_autofit(); return
            sm=self.smooth[self.mode]; valid=sm[sm>-90]
            if len(valid)==0: return
            self._db_lock=False
            peak=float(np.max(valid)); span=self.db_max-self.db_min
            self.db_max=int(math.ceil((peak+12)/12))*12
            self.db_min=self.db_max-span; self._cache=None; self.update()
    def contextMenuEvent(self,e):
        _w=self.window()
        if hasattr(_w,'_spec_db_menu'): _w._spec_db_menu(e.globalPos())
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
        _cap_focus = _focused_capture_visible(self)
        def _draw_src_bars(ch, dim=False):
            vals = ch['values']
            if vals is None or len(vals) != n: return
            qc = QColor(ch['color'])
            if dim: qc.setAlpha(50)
            sbrush, scap = _vbar_gradient(qc)   # 추가 소스 막대도 같은 입체 그라디언트
            for i in range(n):
                db = float(np.clip(vals[i], self.db_min, self.db_max))
                bh = max(2, int((db - self.db_min) / db_range * dh))
                bx = int(pl + i * bar_w + gap / 2); bw = max(1, int(bar_w - gap)); by = pt + dh - bh
                p.fillRect(bx, by, bw, bh, sbrush)
                if bh > 5: p.fillRect(bx, by, bw, 1, scap)
        def _draw_caps():
            if not self._captures: return
            _cap_key=self._cap_base_key()
            if self._cap_pix is None or self._cap_pix_key!=_cap_key:
                self._trigger_cap_build(W, H, _cap_key)
            if self._cap_pix is not None:
                p.drawPixmap(0,0,self._cap_pix)
            fi=self._front_idx
            if fi is not None and 0<=fi<len(self._captures) and self._captures[fi].get('visible',True):
                self._draw_cap_curve(p, self._captures[fi], W, H, emph=True)   # 선택 캡쳐 강조(재빌드 없이)
        def _draw_all_live(dim):
            self._draw_live(p, W, H, dim=dim)
            if self._ch_oct:
                for cid, ch in sorted(self._ch_oct.items(), key=lambda kv: kv[0]==self._front_id):
                    if not ch.get('visible', True): continue
                    _draw_src_bars(ch, dim=dim)
            # front가 primary면 primary 막대를 맨 위에 다시 — 단 채널 오버레이가 있을 때만.
            # 채널이 없으면 이미 맨 위라 같은 막대를 두 번 래스터화하는 순수 낭비였다
            # (1/24 옥타브 실측: 페인트 3.38ms 중 1.43ms = 42%). FFT 캔버스와 동일한 가드.
            if self._front_id == 0 and self._ch_oct:
                self._draw_live(p, W, H, dim=dim)
        if _cap_focus:
            _draw_all_live(dim=True)    # 라이브 흐리게(아래)
            _draw_caps()                # 선택 캡쳐 솔리드(위)
        else:
            _draw_caps()                # 캡쳐 흐리게(아래)
            _draw_all_live(dim=False)   # 라이브 솔리드(위)

        self._draw_grid_lines(p, W, H)

        # 우상단 고정 배지: 현재 평균 스펙트럼 최대 주파수 (40 Hz 이상만 탐색)
        unit='dBSPL' if self.calib_offset else 'dB'
        if not self._idle_hint:   # 시작 전 빈 상태에선 바닥값 도미넌트 배지 숨김
            valid_mask=[i for i,f in enumerate(bands) if f>=40]
            if valid_mask:
                sub=np.array([sm[i] for i in valid_mask])
                dom_idx=valid_mask[int(np.argmax(sub))]
            else:
                dom_idx=int(np.argmax(sm))
            dom_f=float(bands[dom_idx]); dom_db=float(sm[dom_idx])
            dom_f, dom_db = _smooth_dom(self, dom_f, dom_db)   # [RDOUT] 배지 평활(느리게)
            dom_fs=f'{dom_f/1000:.2f} kHz' if dom_f>=1000 else f'{dom_f:.0f} Hz'
            draw_dom_badge(p, W-pr, pt, dom_fs, dom_db, unit)
        if self.title_text:
            p.setFont(_qfont(CF_MODE, True)); p.setPen(QColor(T('graph_txt')))
            p.drawText(pl+4, pt+13, self.title_text)

        if pl<=self._mx<=W-pr:
            cx,cy=self._mx,self._my
            bi=max(0,min(int((cx-pl)/bar_w),n-1)); fc=bands[bi]
            db2=float(sm[bi]); _cap_col=None; _thd_src=sm   # THD도 표시값과 같은 소스로
            if _focused_capture_visible(self):   # 포커스된 캡쳐(같은 모드) 값 우선
                _cv=self._captures[self._front_idx].get('values')
                if _cv is not None and len(_cv)==n:
                    db2=float(_cv[bi]); _cap_col=self._captures[self._front_idx].get('color'); _thd_src=_cv
            bx2=int(pl+bi*bar_w+gap/2); bw2=max(1,int(bar_w-gap))
            p.setPen(QPen(QColor(T('accent')),2))
            p.setBrush(QBrush(QColor(T('accent')).lighter(200) if (not is_dark()) else QColor(78,125,240,12)))
            p.drawRect(bx2,pt,bw2,dh)
            fs=f'{fc/1000:.2f} kHz' if fc>=1000 else f'{fc:.0f} Hz'
            fs=f'{fs}   {freq_to_note(fc)}'
            _thd_val=None                          # [THD] RTA 밴드 데이터(커서=기본파). 배음 탐색창을
            if self._show_thd:                     # 밴드간격 절반+로 넓혀 k·f0가 밴드중심 아닐 때도 포착
                _wv = 0.6*math.log2(bands[1]/bands[0]) if len(bands) > 1 else 0.04
                _r=thd_from_spectrum(bands, _thd_src, fc, win_oct=_wv)
                if _r is not None: _thd_val=_r[0]
            db2, _thd_v = _smooth_readout(self, fc, db2, _thd_val)   # [RDOUT] 값 평활(느리게)
            _thd_str=f'THD {_thd_v:.2f}%' if _thd_v is not None else None
            draw_info_box(p,W,fs,f'{db2:.1f} {unit}', pk_str=_thd_str, cx=cx, x_lo=pl, x_hi=W-pr, top=pt,
                          val_color=_cap_col or QColor(*bar_top()[:3]))
        if self._idle_hint:
            _draw_idle_hint(p, pl, pt, W-pl-pr, dh)
        _draw_tf_sel_border(self, p)   # TF의 RTA 칸 선택 시 파란 테두리(Spectrum 탭에선 무효)
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
        self.db_min=-96; self.db_max=MAX_DB; self._db_lock=False
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
            _xh = QColor(20,33,58,120) if (not is_dark()) else QColor(255,255,255,100)
            p.setPen(QPen(_xh,1,Qt.DashLine))
            p.drawLine(cx,pt,cx,H-pb)
            # horizontal line (only inside data area)
            if pt<=cy<=H-pb:
                p.drawLine(pl,cy,W-pr,cy)

            # Frequency at cursor X
            freq=x_to_freq(cx,pl,dw,20000) if self.scale_log else (cx-pl)/dw*20000
            fs=f'{freq/1000:.2f} kHz' if freq>=1000 else f'{freq:.0f} Hz'
            fs=f'{fs}   {freq_to_note(freq)}'

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
                    draw_info_box(p,W,fs,db_str+t_str, cx=cx, x_lo=pl, x_hi=pl+dw, top=pt)
                    # small time label beside cursor Y
                    t_lbl=f'{t_ago:.1f}s'
                    p.setFont(_qfont(CF_ANNO))
                    p.setPen(QColor(20,33,58,200) if (not is_dark()) else QColor(255,255,255,160))
                    p.drawText(pl+4,cy-3,t_lbl)
                else:
                    draw_info_box(p,W,fs,'', cx=cx, x_lo=pl, x_hi=pl+dw, top=pt)
            else:
                draw_info_box(p,W,fs,'', cx=cx, x_lo=pl, x_hi=pl+dw, top=pt)
        p.end()

