"""캡쳐 드로어 — 스펙트럼 탭 우측 캡쳐 목록 패널 + 드래그 그립.

v2.0 분해: wayaudo2.py에서 이동(동작 0 변경).
"""
from PyQt5.QtGui import QColor, QFont, QFontMetrics, QIcon, QPainter, QPixmap
from PyQt5.QtCore import Qt, QPoint, QRectF, QSize, QTimer, pyqtSignal
from PyQt5.QtWidgets import (QFrame, QHBoxLayout, QLabel, QMenu, QPushButton,
                             QScrollArea, QVBoxLayout, QWidget)
from spectra.core.config import T, is_dark
from spectra.core.i18n import _tx
from spectra.ui.icons import _icon, _wave_toggle_icon
from spectra.ui.tokens import FONT_FAMILY, _n2_mono_font
from spectra.ui.tf_window import _text_input_dialog


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
