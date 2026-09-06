"""스테레오 캔버스 — 벡터스코프·라우드니스 레이더/히스토리 + 그라디언트 숫자.

v2.0 분해: wayaudo2.py에서 이동(동작 0 변경).
"""
import math, time
from collections import deque
import numpy as np
from PyQt5.QtGui import (QBrush, QColor, QConicalGradient, QFont, QLinearGradient,
                         QPainter, QPainterPath, QPen, QPolygon, QRadialGradient)
from PyQt5.QtCore import Qt, QPoint, QRect, QRectF, QSize, QTimer, pyqtSignal
from PyQt5.QtWidgets import QSizePolicy, QWidget
from spectra.core.config import T, is_dark
from spectra.core.i18n import cur_lang
from spectra.ui.tokens import CF_ANNO, FONT_NUM, FS_BODY, FS_SM, _qfont
from spectra.ui.colors import _brand_color, _spectra_grad_obj


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
            # [PERF] 버킷별 QPolygon을 한 번만 만들어 두 패스가 공유한다 — 예전엔 동일한 점
            # 리스트를 패스마다 새로 만들어 프레임당 0.70ms를 순수 중복으로 썼다.
            # 좌표는 이미 int32로 스냅됐으므로 점 렌더에 AA는 이득이 없다(1.05ms→0.45ms) → 끈다.
            xl = xi.tolist(); yl = yi.tolist()
            buckets = []
            for b in range(N_BUCK):
                lo = b*bsz; hi = min((b+1)*bsz, N_pts)
                if lo >= hi: buckets.append(None); continue
                buckets.append(QPolygon([QPoint(a, c) for a, c in zip(xl[lo:hi], yl[lo:hi])]))
            _aa_prev = p.testRenderHint(QPainter.Antialiasing)
            p.setRenderHint(QPainter.Antialiasing, False)
            # Pass 1 — glow (wide, semi-transparent)
            for b in range(N_BUCK):
                pts = buckets[b]
                if pts is None: continue
                col = _spec_color(b / N_BUCK, 140, int(10 + b/N_BUCK * 38))
                p.setPen(QPen(col, 4.5)); p.drawPoints(pts)
            # Pass 2 — crisp
            for b in range(N_BUCK):
                pts = buckets[b]
                if pts is None: continue
                frac = b / N_BUCK
                col = _spec_color(frac, int(155 + frac*20), int(12 + frac*228))
                pw = 2.8 if frac > 0.85 else 1.8 if frac > 0.62 else 1.2
                p.setPen(QPen(col, pw)); p.drawPoints(pts)
            p.setRenderHint(QPainter.Antialiasing, _aa_prev)   # 이후 팁/링/라벨은 AA 복원
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
