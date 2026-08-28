"""다이얼로그 — 설정/파인더/브랜드 다이얼로그 (v2.0 분해, 동작 0 변경)."""
import sys
from PyQt5.QtWidgets import (QDialog, QDialogButtonBox, QDoubleSpinBox, QFrame, QHBoxLayout,
    QLabel, QPushButton, QRadioButton, QSpinBox, QVBoxLayout, QWidget,
    QAbstractItemView, QApplication, QComboBox, QGridLayout, QGroupBox, QLineEdit, QScrollArea, QMessageBox)
from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal
from PyQt5.QtGui import QColor
from spectra.core.config import T, is_dark
from spectra.core.i18n import _tx
from spectra.core.logging_diag import _alog
from spectra.core.license import _get_machine_id, save_license, verify_license
from spectra.ui.tokens import ss_btn_neutral, ss_btn_primary, ss_btn_danger, ss_dialog_btns, ss_spin, FS_LG, FONT_FAMILY
from spectra.ui.widgets import _apply_dark_titlebar, _grad_topline, hsep, _dialog_brand_header, _icon


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


class ShortcutsDialog(QDialog):
    """키보드 단축키 치트시트 — ? 키 또는 Help 메뉴에서 열림. 키캡 스타일."""
    _GROUPS = [
        ('Global', [
            ('S',      'Start / Stop measurement  (Spectrum · Stereo Loudness)'),
            ('Space',  'New Capture'),
            ('R',      'Recapture selected capture in place'),
            ('?',      'Open this keyboard shortcut help'),
            ('⌘ ?',    'Open manual'),
            ('⌘ Q',    'Quit'),
        ]),
        ('Transfer Function', [
            ('G',         'Toggle signal generator On / Off'),
            ('L',         'Auto-find delays (Find Delays)'),
            ('↑ ↓ ← →',  'IR graph — navigate time / dB axis'),
        ]),
        ('Delay Finder Window', [
            ('L',      'Find again'),
            ('Enter',  'Apply delays (Insert All)'),
        ]),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_tx('Keyboard Shortcuts')); _apply_dark_titlebar(self)
        self.setStyleSheet(f'background:{T("bg2")};color:{T("text")};')
        self.setMinimumWidth(460)
        _outer = QVBoxLayout(self); _outer.setSpacing(0); _outer.setContentsMargins(0, 0, 0, 0)
        _outer.addWidget(_dialog_brand_header(_tx('Keyboard Shortcuts')))
        root = QVBoxLayout(); root.setContentsMargins(24, 18, 24, 18); root.setSpacing(4)
        _outer.addLayout(root)
        for gname, items in self._GROUPS:
            hdr = QLabel(_tx(gname))
            hdr.setStyleSheet(f'color:{T("accent")};font-size:12px;font-weight:bold;'
                              f'padding-top:12px;padding-bottom:2px;')
            root.addWidget(hdr)
            grid = QGridLayout(); grid.setHorizontalSpacing(14); grid.setVerticalSpacing(7)
            grid.setContentsMargins(4, 2, 4, 2)
            for r, (key, desc) in enumerate(items):
                grid.addWidget(self._keycap(key), r, 0, Qt.AlignLeft | Qt.AlignVCenter)
                dl = QLabel(_tx(desc)); dl.setStyleSheet(f'color:{T("text")};font-size:12px;')
                grid.addWidget(dl, r, 1)
            grid.setColumnStretch(1, 1)
            root.addLayout(grid)
        btns = QDialogButtonBox(QDialogButtonBox.Close)
        btns.setStyleSheet(ss_dialog_btns())
        btns.button(QDialogButtonBox.Close).setText(_tx('Close'))
        btns.rejected.connect(self.accept); btns.accepted.connect(self.accept)
        btns.button(QDialogButtonBox.Close).clicked.connect(self.accept)
        root.addSpacing(8); root.addWidget(btns)

    def _keycap(self, text):
        lbl = QLabel(text); lbl.setAlignment(Qt.AlignCenter)
        lbl.setStyleSheet(
            f'background:{T("panel")}; color:{T("accent")}; border:1px solid {T("border")};'
            f'border-radius:6px; padding:3px 9px; font-family:"SF Mono","Courier New",monospace;'
            f'font-size:12px; font-weight:bold;')
        lbl.setMinimumWidth(72)
        return lbl


class _TFAverageDialog(QDialog):
    def __init__(self, captures, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_tx('TF Average')); _apply_dark_titlebar(self)   # 프레임리스 + 다크 타이틀바
        self.setModal(True)
        self.setMinimumWidth(300)
        self.setStyleSheet(f'background:{T("bg2")};color:{T("text")};')
        fg = T('text'); accent = T('accent')

        # 프레임리스 유지 — setWindowFlags 재호출 금지(네이티브 프레임 이중표시 방지)
        outer = QVBoxLayout(self); outer.setSpacing(0); outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(_grad_topline())
        body = QWidget(); lay = QVBoxLayout(body)
        lay.setSpacing(6); lay.setContentsMargins(16, 14, 16, 14)
        outer.addWidget(body)

        hint = QLabel(_tx('Select captures to average'))
        hint.setStyleSheet(f'color:{T("text_dim")};font-size:11px;background:transparent;')
        lay.addWidget(hint)

        # 체크박스 — 테마 적응 (다크/라이트)
        if is_dark():
            _ck_bg, _ck_bd, _ck_on = '#0c0c20', '#5060a0', '#0c1830'
        else:
            _ck_bg, _ck_bd, _ck_on = T('panel'), '#C4CCD8', '#E3ECFF'
        _chk_ss = (
            f'QPushButton{{font-size:13px;font-weight:bold;border:2px solid {_ck_bd};'
            f'border-radius:4px;background:{_ck_bg};color:{accent};padding:0;'
            f'min-width:20px;max-width:20px;min-height:20px;max-height:20px;}}'
            f'QPushButton:checked{{border:2px solid {accent};background:{_ck_on};}}')
        self._checks = []
        for i, cap in enumerate(captures):
            row = QWidget()
            rl = QHBoxLayout(row); rl.setContentsMargins(4, 2, 4, 2); rl.setSpacing(8)
            chk = QPushButton('')
            chk.setCheckable(True); chk.setChecked(False)
            chk.setStyleSheet(_chk_ss)
            chk.toggled.connect(lambda c, b=chk: b.setText('✓' if c else ''))
            dot = QLabel('■')
            dot.setStyleSheet(f'color:{cap.get("color","#fff")};font-size:14px;background:transparent;')
            dot.setFixedWidth(18)
            name = QLabel(cap.get('label', f'Capture {i+1}'))
            name.setStyleSheet(f'color:{fg};font-size:13px;background:transparent;')
            rl.addWidget(chk); rl.addWidget(dot); rl.addWidget(name, 1)
            lay.addWidget(row)
            self._checks.append((i, chk))

        lay.addSpacing(4); lay.addWidget(hsep())
        btn_lay = QHBoxLayout(); btn_lay.setSpacing(8); btn_lay.addStretch()
        self._cancel_btn = QPushButton(_tx('Cancel')); self._cancel_btn.setStyleSheet(ss_btn_neutral())
        self._ok_btn = QPushButton('Average'); self._ok_btn.setStyleSheet(ss_btn_primary())
        self._ok_btn.setDefault(True)
        self._cancel_btn.clicked.connect(self.reject)
        self._ok_btn.clicked.connect(self.accept)
        btn_lay.addWidget(self._cancel_btn)
        btn_lay.addWidget(self._ok_btn)
        lay.addLayout(btn_lay)

    def selected_indices(self):
        return [i for i, chk in self._checks if chk.isChecked()]


class LicenseDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_tx('SPECTRA — License Activation')); _apply_dark_titlebar(self)
        self.setFixedSize(460, 310)   # 고정크기(프레임리스 유지) — setWindowFlags 재호출 금지(이중 타이틀바 방지)
        self._mid = _get_machine_id()
        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self); lay.setSpacing(14); lay.setContentsMargins(24, 20, 24, 20)

        title = QLabel('SPECTRA')
        title.setStyleSheet(f'font-family:"{FONT_FAMILY}";font-size:17px;font-weight:bold;color:#4E7DF0;letter-spacing:4px;')
        lay.addWidget(title)

        # 머신 ID 표시
        mid_box = QFrame(); mid_box.setFrameShape(QFrame.StyledPanel)
        mid_box.setStyleSheet('background:#1C1C1E;border:1px solid #38383A;border-radius:6px;')
        mid_lay = QVBoxLayout(mid_box); mid_lay.setContentsMargins(12,8,12,8); mid_lay.setSpacing(4)
        mid_lbl = QLabel(_tx('Machine ID for this computer (send to developer):'))
        mid_lbl.setStyleSheet('font-size:11px;color:#8E8E93;')
        self._mid_val = QLabel(self._mid)
        self._mid_val.setStyleSheet('font-size:16px;font-weight:bold;color:#FFFFFF;letter-spacing:2px;font-family:"Courier New";')
        self._mid_val.setTextInteractionFlags(Qt.TextSelectableByMouse)
        copy_btn = QPushButton(_tx('Copy Machine ID'))
        copy_btn.setFixedWidth(110)
        copy_btn.setStyleSheet('background:#2C2C2E;color:#4E7DF0;border:1px solid #4E7DF0;border-radius:4px;padding:3px;font-size:10px;')
        copy_btn.clicked.connect(self._copy_mid)
        mid_row = QHBoxLayout(); mid_row.addWidget(self._mid_val); mid_row.addStretch(); mid_row.addWidget(copy_btn)
        mid_lay.addWidget(mid_lbl); mid_lay.addLayout(mid_row)
        lay.addWidget(mid_box)

        # 시리얼 키 입력
        key_lbl = QLabel(_tx('Enter Serial Key:'))
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
        quit_btn = QPushButton(_tx('Quit'))
        quit_btn.setFixedWidth(80)
        quit_btn.clicked.connect(self.reject)
        self._act_btn = QPushButton(_tx('Activate'))
        self._act_btn.setFixedWidth(100)
        self._act_btn.setEnabled(False)
        self._act_btn.setStyleSheet('background:#4E7DF0;color:#FFFFFF;font-weight:bold;border-radius:6px;padding:6px;')
        self._act_btn.clicked.connect(self._activate)
        btn_row.addWidget(quit_btn); btn_row.addStretch(); btn_row.addWidget(self._act_btn)
        lay.addLayout(btn_row)

    def _copy_mid(self):
        QApplication.clipboard().setText(self._mid)
        self._status.setStyleSheet('font-size:11px;color:#33FF66;')
        self._status.setText(_tx('Machine ID copied to clipboard.'))

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
            self._status.setText(_tx('Activation successful!'))
            QTimer.singleShot(800, self.accept)
        else:
            _alog.warning(f'라이선스 활성화 실패  reason={reason}  machine={self._mid}')
            self._status.setStyleSheet('font-size:11px;color:#FF453A;')
            self._status.setText(reason)


class SplAlarmConfigDialog(QDialog):
    """SPL Alarm settings — metric / limit / amber margin / LEQ time."""
    def __init__(self, metrics, leq_labels, cfg, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_tx('SPL Alarm Settings')); _apply_dark_titlebar(self)
        self.setMinimumWidth(320)
        self.setStyleSheet(f'background:{T("bg2")};color:{T("text")};')
        self._metric_ids = list(metrics.keys())

        def cstyle():
            return (f"QComboBox{{background:{T('panel')};color:{T('text')};"
                    f"border:1px solid {T('border')};border-radius:6px;padding:3px 8px;font-size:11px;}}"
                    f"QComboBox QAbstractItemView{{background:{T('bg2')};color:{T('text')};"
                    f"border:1px solid {T('accent')};selection-background-color:rgba(78,125,240,80);}}")

        _outer = QVBoxLayout(self); _outer.setSpacing(0); _outer.setContentsMargins(0, 0, 0, 0)
        _outer.addWidget(_dialog_brand_header(_tx('SPL Alarm Settings')))
        root = QVBoxLayout(); root.setSpacing(12); root.setContentsMargins(18, 16, 18, 16)
        _outer.addLayout(root)

        mrow = QHBoxLayout(); mrow.addStretch(); mrow.addWidget(QLabel('Metric:'))
        self._metric_cb = QComboBox(); self._metric_cb.setStyleSheet(cstyle()); self._metric_cb.setMinimumWidth(150)
        for mid in self._metric_ids:
            self._metric_cb.addItem(metrics[mid])
        cm = cfg.get('metric', 'laeq')
        self._metric_cb.setCurrentIndex(self._metric_ids.index(cm) if cm in self._metric_ids else 0)
        mrow.addWidget(self._metric_cb); mrow.addStretch(); root.addLayout(mrow)

        lrow = QHBoxLayout(); lrow.addStretch(); lrow.addWidget(QLabel('Limit:'))
        self._limit_sp = QDoubleSpinBox(); self._limit_sp.setStyleSheet(ss_spin(FS_LG, 6, 80))
        self._limit_sp.setRange(30.0, 160.0); self._limit_sp.setDecimals(1); self._limit_sp.setSingleStep(0.5)
        self._limit_sp.setSuffix(' dB'); self._limit_sp.setValue(float(cfg.get('limit', 100.0)))
        lrow.addWidget(self._limit_sp); lrow.addSpacing(14); lrow.addWidget(QLabel('Amber:'))
        self._amber_sp = QDoubleSpinBox(); self._amber_sp.setStyleSheet(ss_spin(FS_LG, 6, 70))
        self._amber_sp.setRange(0.5, 15.0); self._amber_sp.setDecimals(1); self._amber_sp.setSingleStep(0.5)
        self._amber_sp.setPrefix('-'); self._amber_sp.setSuffix(' dB'); self._amber_sp.setValue(float(cfg.get('amber', 3.0)))
        lrow.addWidget(self._amber_sp); lrow.addStretch(); root.addLayout(lrow)

        qrow = QHBoxLayout(); qrow.addStretch(); qrow.addWidget(QLabel('LEQ time:'))
        self._leq_cb = QComboBox(); self._leq_cb.setStyleSheet(cstyle()); self._leq_cb.setMinimumWidth(120)
        for lbl in leq_labels:
            self._leq_cb.addItem(lbl)
        self._leq_cb.setCurrentIndex(max(0, min(self._leq_cb.count() - 1, int(cfg.get('leq_idx', 3)))))
        qrow.addWidget(self._leq_cb); qrow.addStretch(); root.addLayout(qrow)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.setStyleSheet(ss_dialog_btns())
        btns.accepted.connect(self.accept); btns.rejected.connect(self.reject)
        root.addWidget(btns)

    def get_cfg(self):
        return {
            'metric': self._metric_ids[self._metric_cb.currentIndex()],
            'limit':  float(self._limit_sp.value()),
            'amber':  float(self._amber_sp.value()),
            'leq_idx': self._leq_cb.currentIndex(),
        }


class SplLayoutDialog(QDialog):
    """SPL Meter 레이아웃 편집 — 행/열 개수 + 칸별 지표 지정."""
    def __init__(self, rows, cols, cells, metrics, leq_labels=None, leq_idx=0, parent=None,
                 sources=None, source_id=0):
        super().__init__(parent)
        self.setWindowTitle(_tx('SPL Settings')); _apply_dark_titlebar(self)
        self.setMinimumWidth(360)
        self.setStyleSheet(f'background:{T("bg2")};color:{T("text")};')
        self._metrics = metrics                 # id -> (title, color)
        self._cells = list(cells)               # 현재 지정값 (재구성 시 보존)
        self._combos = []                       # 현재 그리드의 QComboBox 목록
        self._ids = [None] + list(metrics.keys())   # 콤보 인덱스 ↔ 지표 id
        self._src_ids = [s[0] for s in (sources or [])]   # 소스 콤보 인덱스 ↔ 카드 id

        _outer = QVBoxLayout(self); _outer.setSpacing(0); _outer.setContentsMargins(0, 0, 0, 0)
        _outer.addWidget(_dialog_brand_header(_tx('SPL Settings')))
        root = QVBoxLayout(); root.setSpacing(12); root.setContentsMargins(18, 16, 18, 16)
        _outer.addLayout(root)

        # ── 측정 소스(어느 입력 카드를 SPL 미터로 측정할지)
        self._src_cb = None
        if sources:
            src_row = QHBoxLayout(); src_row.addStretch()
            src_row.addWidget(QLabel(_tx('Source:')))
            self._src_cb = QComboBox(); self._src_cb.setStyleSheet(self._combo_style())
            self._src_cb.setMinimumWidth(200)
            for _sid, lbl in sources:
                self._src_cb.addItem(lbl)
            cur = self._src_ids.index(source_id) if source_id in self._src_ids else 0
            self._src_cb.setCurrentIndex(cur)
            src_row.addWidget(self._src_cb); src_row.addStretch()
            root.addLayout(src_row)

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
        rc_row.addWidget(QLabel(_tx('Rows:')))
        self._row_sp = QSpinBox(); self._row_sp.setRange(1, 4); self._row_sp.setValue(rows)
        rc_row.addWidget(self._row_sp)
        rc_row.addSpacing(14)
        rc_row.addWidget(QLabel(_tx('Cols:')))
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
            cb.addItem(_tx('— None'))
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

    def get_source_id(self):
        """선택된 측정 소스 카드 id (셀렉터 없으면 0=primary)."""
        if self._src_cb is None or not self._src_ids:
            return 0
        i = self._src_cb.currentIndex()
        return self._src_ids[i] if 0 <= i < len(self._src_ids) else 0


class CalibDialog(QDialog):
    def __init__(self, device_name, n_channels, offsets, active_ch,
                 current_spl_func, set_channel_func, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_tx('Mic Calibration')); _apply_dark_titlebar(self)
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
        # ── 최상위: 브랜드 헤더(풀폭) + 본문 컨테이너. `layout`은 본문 컨테이너 레이아웃으로 유지.
        _outer = QVBoxLayout(self); _outer.setSpacing(0); _outer.setContentsMargins(0, 0, 0, 0)
        _outer.addWidget(_dialog_brand_header(_tx('Mic Calibration')))
        layout = QVBoxLayout(); layout.setSpacing(12); layout.setContentsMargins(18, 16, 18, 16)
        _outer.addLayout(layout)

        # ── 순서 안내
        steps = QLabel(
            _tx('① Connect the calibrator to your mic\n'
              '② [Select] the channel to calibrate from the list\n'
              '③ Pick reference (94 or 114 dBSPL) -> [Measure Level]\n'
              '④ [Auto Offset] -> repeat for other channels -> [OK]')
        )
        steps.setStyleSheet(f'color:{T("text_dim")};font-size:11px;'
                            f'background:{T("panel")};border-radius:8px;padding:10px;')
        steps.setWordWrap(True); layout.addWidget(steps)

        # ── 채널 목록 테이블 (B안): 채널 / 현재 오프셋 / 선택
        if self._n_ch > 1:
            ch_hdr = QLabel(_tx('Channels  ·  {dev}').format(dev=device_name))
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
                sel = QPushButton(_tx('Select'))
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
        ref_row.addWidget(QLabel(_tx('Calibrator reference:')))
        self.ref_cb = QComboBox()
        self.ref_cb.addItems([_tx('94 dBSPL  (standard)'), _tx('114 dBSPL  (high-level)')])
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

        self.meas_btn = QPushButton(_tx('Measure Level  (3s)')); self.meas_btn.setIcon(_icon('mic', 14, color=T('accent')))
        self.meas_btn.setStyleSheet(f'background:rgba(78,125,240,25);color:{T("accent")};'
                                     f'border:1px solid {T("accent")};padding:6px;border-radius:8px;font-size:12px;')
        self.meas_btn.clicked.connect(self._start_measure)
        mb.addWidget(self.meas_btn)

        # 직접 입력 (스피너 버튼 없음, 가운데 정렬)
        manual_row = QHBoxLayout(); manual_row.addStretch()
        manual_row.addWidget(QLabel(_tx('Manual (dBFS):')))
        self.meas_spin = QDoubleSpinBox()
        self.meas_spin.setRange(-120, 0); self.meas_spin.setDecimals(1)
        self.meas_spin.setSingleStep(0.1); self.meas_spin.setValue(-26.0)
        self.meas_spin.setStyleSheet(ss_spin())
        manual_row.addWidget(self.meas_spin); manual_row.addStretch()
        mb.addLayout(manual_row)
        layout.addWidget(meas_box)

        # ── 오프셋 자동 계산
        calc_btn = QPushButton(_tx('Auto Calculate Offset'))
        calc_btn.setStyleSheet(f'background:rgba(48,209,88,20);color:{T("green")};'
                                f'border:1px solid rgba(48,209,88,100);padding:7px;'
                                f'border-radius:8px;font-size:13px;font-weight:bold;')
        calc_btn.clicked.connect(self._auto_calc); layout.addWidget(calc_btn)

        self.result_lbl = QLabel('')
        self.result_lbl.setStyleSheet(f'color:{T("green")};font-size:13px;font-weight:bold;')
        self.result_lbl.setAlignment(Qt.AlignCenter); layout.addWidget(self.result_lbl)

        # ── 최종 오프셋 (가운데 정렬, 스피너 버튼 없음)
        off_row = QHBoxLayout(); off_row.addStretch()
        off_row.addWidget(QLabel(_tx('Applied offset (dB):')))
        self.offset_spin = QDoubleSpinBox()
        self.offset_spin.setRange(-30, 200)
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
        rst = QPushButton(_tx('Reset'))
        rst.setStyleSheet(f'background:{T("panel")};color:{T("text_dim")};'
                          f'border:1px solid {T("border")};padding:4px 12px;border-radius:8px;')
        rst.clicked.connect(lambda: (self.offset_spin.setValue(0), self.result_lbl.setText(_tx('Ch {n} reset').format(n=self._cur_ch+1))))
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
        return _tx('Ch {n} Level').format(n=self._cur_ch+1) if self._n_ch > 1 else _tx('Current Mic Level')

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
        self.result_lbl.setText(_tx('Ch {n} selected — measure or enter offset').format(n=ch+1))
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
                w['btn'].setText(_tx('● Selected'))
                w['btn'].setStyleSheet(f'background:rgba(78,125,240,35);color:{T("accent")};'
                                       f'border:1px solid {T("accent")};border-radius:7px;padding:3px;font-size:11px;')
            else:
                w['btn'].setText(_tx('Select'))
                w['btn'].setStyleSheet(f'background:{T("bg2")};color:{T("text_dim")};'
                                       f'border:1px solid {T("border")};border-radius:7px;padding:3px;font-size:11px;')

    def _start_measure(self):
        if self._measuring: return
        self._measuring = True; self._meas_samples = []; self._meas_count = 0
        self.meas_btn.setText(_tx('Measuring... (3s)'))
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
            self.meas_btn.setText(_tx('Measure Level  (3s)')); self.meas_btn.setIcon(_icon('mic', 14, color=T('accent')))
            self.meas_btn.setStyleSheet(f'background:rgba(78,125,240,25);color:{T("accent")};'
                                         f'border:1px solid {T("accent")};padding:6px;border-radius:5px;font-size:12px;')
            self._auto_calc()

    def _auto_calc(self):
        ref_val = 94.0 if self.ref_cb.currentIndex()==0 else 114.0
        meas    = self.meas_spin.value()
        offset  = ref_val - meas
        self.offset_spin.setValue(round(offset, 1))   # → _on_offset_edited 가 _offsets 기록
        self.result_lbl.setText(_tx('Ch {n}  offset {off:+.1f} dB  ->  {meas:.1f} + {off:.1f} = {ref:.0f} dBSPL ✓').format(n=self._cur_ch+1, off=offset, meas=meas, ref=ref_val))

    def get_all_offsets(self):
        """{ch:int -> offset:float} — 이번 세션에서 설정/변경된 모든 채널."""
        return dict(self._offsets)

    def get_current_channel(self):
        return self._cur_ch


def _brand_msg(parent, title, text, kind='info', ok_text='OK', cancel_text=None, danger=False):
    """SPECTRA 브랜드 메시지/확인 다이얼로그 (시스템 QMessageBox 대체).
    kind: 'info'(파랑 i) / 'warn'(주황 △!) / 'question'(파랑 ?). 상단 그라디언트 라인 + 라인 아이콘.
    cancel_text 지정 시 확인/취소 2버튼(확인=True), 아니면 OK 1버튼. danger=True면 주동작 빨강.
    반환: True(확인/OK) / False(취소)."""
    dlg = QDialog(parent)
    dlg.setWindowTitle(title); _apply_dark_titlebar(dlg)
    dlg.setMinimumWidth(360); dlg.setMaximumWidth(540)
    dlg.setStyleSheet(f'background:{T("bg2")};color:{T("text")};')
    lay = QVBoxLayout(dlg); lay.setSpacing(0); lay.setContentsMargins(0, 0, 0, 0)
    lay.addWidget(_grad_topline())
    body = QWidget(); bl = QVBoxLayout(body)
    bl.setContentsMargins(20, 18, 20, 16); bl.setSpacing(18)
    row = QHBoxLayout(); row.setSpacing(14)
    _ic_name, _ic_col = {'info': ('info', T('accent')),
                         'warn': ('alert-triangle', '#FF9F0A'),
                         'question': ('help-circle', T('accent'))}.get(kind, ('info', T('accent')))
    ic = QLabel(); ic.setPixmap(_icon(_ic_name, 30, color=_ic_col).pixmap(30, 30))
    ic.setFixedWidth(34); ic.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
    row.addWidget(ic, 0, Qt.AlignTop)
    msg = QLabel(text); msg.setWordWrap(True)
    msg.setStyleSheet(f'color:{T("text")};font-size:13px;font-weight:600;background:transparent;')
    row.addWidget(msg, 1)
    bl.addLayout(row)
    btn_row = QHBoxLayout(); btn_row.setSpacing(8); btn_row.addStretch()
    if cancel_text:
        cb = QPushButton(cancel_text); cb.setStyleSheet(ss_btn_neutral())
        cb.clicked.connect(dlg.reject); btn_row.addWidget(cb)
    ob = QPushButton(ok_text)
    ob.setStyleSheet(ss_btn_danger() if danger else ss_btn_primary())
    ob.setDefault(True); ob.clicked.connect(dlg.accept); btn_row.addWidget(ob)
    bl.addLayout(btn_row)
    lay.addWidget(body)
    return dlg.exec_() == QDialog.Accepted


class _BrandBox:
    """QMessageBox 드롭인 대체 — 브랜드 다이얼로그로 표시 (information/warning)."""
    @staticmethod
    def information(parent, title, text):
        _brand_msg(parent, title, text, kind='info')
    @staticmethod
    def warning(parent, title, text):
        _brand_msg(parent, title, text, kind='warn')


class _ConvWorker(QThread):
    """음악 × IR 컨볼루션을 백그라운드에서 (긴 곡에서 UI 프리즈 방지)."""
    done = pyqtSignal(object)
    def __init__(self, music, ir, sig):
        super().__init__(); self._m = music; self._ir = ir; self.sig = sig
    def run(self):
        try:
            from scipy.signal import fftconvolve
            wet = fftconvolve(self._m, self._ir)
        except Exception:
            wet = np.convolve(self._m, self._ir)
        pk = float(np.max(np.abs(wet))) if len(wet) else 0.0
        if pk > 1e-6: wet = wet / pk * 0.9
        self.done.emit(wet.astype(np.float32))
