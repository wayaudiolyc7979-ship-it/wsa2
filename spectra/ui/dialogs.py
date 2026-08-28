"""다이얼로그 — 설정/파인더/브랜드 다이얼로그 (v2.0 분해, 동작 0 변경)."""
from PyQt5.QtWidgets import (QDialog, QDialogButtonBox, QDoubleSpinBox, QFrame, QHBoxLayout,
    QLabel, QPushButton, QRadioButton, QSpinBox, QVBoxLayout, QWidget)
from spectra.core.config import T, is_dark
from spectra.core.i18n import _tx
from spectra.ui.tokens import ss_btn_neutral, ss_btn_primary, ss_dialog_btns
from spectra.ui.widgets import _apply_dark_titlebar, _grad_topline, hsep


class _DelayAdvancedDialog(QDialog):
    def __init__(self, parent=None, speed_ms=343.0):
        super().__init__(parent)
        self.setWindowTitle(_tx('Advanced Settings')); _apply_dark_titlebar(self)
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
        self.setWindowTitle(_tx('Sweep Settings')); _apply_dark_titlebar(self)
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
        _outer = QVBoxLayout(self); _outer.setSpacing(0); _outer.setContentsMargins(0, 0, 0, 0)
        _outer.addWidget(_grad_topline())
        lay = QVBoxLayout(); lay.setSpacing(12); lay.setContentsMargins(18, 16, 18, 16)
        _outer.addLayout(lay)

        # 제목
        title = QLabel(_tx('Sweep Configuration'))
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
        dir_lbl = QLabel(_tx('Direction')); dir_lbl.setFixedWidth(100)
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
        ok_btn = QPushButton(_tx('Apply'))
        ok_btn.setStyleSheet(ss_btn_primary())
        cancel_btn = QPushButton(_tx('Cancel'))
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


class SineConfigDialog(QDialog):
    """사인파 신호 설정 팝업 (주파수) — SPECTRA 브랜드 (상단 그라디언트 라인)."""
    def __init__(self, parent, freq=1000.0):
        super().__init__(parent)
        self.setWindowTitle(_tx('Sine Settings')); _apply_dark_titlebar(self)
        self.setModal(True)
        self.setFixedWidth(300)
        tx = T('text'); td = T('text_dim'); bd = T('border')
        self.setStyleSheet(
            f'QDialog{{background:{T("bg2")};color:{tx};}}'
            f'QLabel{{color:{tx};font-size:12px;background:transparent;}}'
            f'QDoubleSpinBox{{background:{T("panel")};color:{tx};'
            f'border:1px solid {bd};border-radius:6px;padding:3px 8px;font-size:12px;}}'
            f'QDoubleSpinBox::up-button,QDoubleSpinBox::down-button{{width:0;border:none;}}'
        )
        # 프레임리스 유지 — 상단 SPECTRA 그라디언트 라인
        outer = QVBoxLayout(self); outer.setSpacing(0); outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(_grad_topline())
        body = QWidget(); lay = QVBoxLayout(body)
        lay.setSpacing(12); lay.setContentsMargins(18, 16, 18, 16)
        outer.addWidget(body)

        title = QLabel(_tx('Sine Configuration'))
        title.setStyleSheet(f'color:{tx};font-size:13px;font-weight:bold;background:transparent;')
        lay.addWidget(title)

        row = QHBoxLayout(); row.setSpacing(8)
        flbl = QLabel(_tx('Frequency')); flbl.setFixedWidth(100)
        flbl.setStyleSheet(f'color:{td};font-size:11px;background:transparent;')
        self._freq_spin = QDoubleSpinBox()
        self._freq_spin.setRange(10.0, 24000.0); self._freq_spin.setDecimals(1)
        self._freq_spin.setValue(freq); self._freq_spin.setSuffix('  Hz')
        self._freq_spin.setSingleStep(10); self._freq_spin.setAlignment(Qt.AlignCenter)
        row.addWidget(flbl); row.addWidget(self._freq_spin, 1)
        lay.addLayout(row)

        lay.addSpacing(2); lay.addWidget(hsep())
        btn_h = QHBoxLayout(); btn_h.setSpacing(8); btn_h.addStretch()
        cancel_btn = QPushButton(_tx('Cancel')); cancel_btn.setStyleSheet(ss_btn_neutral())
        ok_btn = QPushButton(_tx('Apply')); ok_btn.setStyleSheet(ss_btn_primary())
        ok_btn.setDefault(True)
        cancel_btn.clicked.connect(self.reject)
        ok_btn.clicked.connect(self.accept)
        btn_h.addWidget(cancel_btn); btn_h.addWidget(ok_btn)
        lay.addLayout(btn_h)

    @property
    def freq(self): return max(10.0, min(24000.0, self._freq_spin.value()))
