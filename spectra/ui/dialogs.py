"""다이얼로그 — 설정/파인더/브랜드 다이얼로그 (v2.0 분해, 동작 0 변경)."""
import sys
from PyQt5.QtWidgets import (QDialog, QDialogButtonBox, QDoubleSpinBox, QFrame, QHBoxLayout,
    QLabel, QPushButton, QRadioButton, QSpinBox, QVBoxLayout, QWidget,
    QAbstractItemView, QApplication, QComboBox, QGridLayout, QGroupBox, QLineEdit, QScrollArea, QMessageBox,
    QCheckBox, QFileDialog, QProgressBar)
from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal, QMutexLocker, QPointF
from PyQt5.QtGui import QColor, QPainter, QPen, QPixmap, QPolygonF
from spectra.core.config import T, is_dark, fmt_delay, sound_speed, set_sound_speed
from spectra.core.i18n import _tx
from spectra.core.logging_diag import _alog
from spectra.core.license import _get_machine_id, save_license, verify_license
from spectra.dsp.tf import _hilbert_env
from spectra.ui.colors import BAR_PRESETS
from spectra.ui.tokens import _qfont, ss_btn_neutral, ss_btn_primary, ss_btn_danger, ss_dialog_btns, ss_spin, FS_LG, FONT_FAMILY
from spectra.ui.widgets import _apply_dark_titlebar, _grad_topline, hsep, _dialog_brand_header, _icon, RoundComboBox


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


class DelayFinderDialog(QDialog):
    _result_sig = pyqtSignal(float)

    def __init__(self, tw, parent=None):
        super().__init__(parent)
        self._tw = tw
        self._speed_ms = sound_speed()   # 전역 음속 단일 소스 미러
        self._measured_ms = None
        self._tick_count = 0
        self._prog_timer = None
        self.setWindowTitle(_tx('Delay Finder')); _apply_dark_titlebar(self)
        self.setFixedWidth(460)   # 높이는 브랜드 헤더 포함해 콘텐츠에 맞춰 자동
        self.setStyleSheet(f'background:{T("bg2")};color:{T("text")};')
        self._build_ui()
        self._result_sig.connect(self._on_result)
        self._start_find()

    def _build_ui(self):
        _outer = QVBoxLayout(self); _outer.setSpacing(0); _outer.setContentsMargins(0, 0, 0, 0)
        _outer.addWidget(_dialog_brand_header(_tx('Delay Finder')))
        lay = QVBoxLayout(); lay.setContentsMargins(16,14,16,14); lay.setSpacing(8)
        _outer.addLayout(lay)

        # Progress bar
        self._progress = QProgressBar()
        self._progress.setRange(0, 100); self._progress.setValue(0)
        self._progress.setFixedHeight(16); self._progress.setTextVisible(False)
        self._progress.setStyleSheet(
            f'QProgressBar{{background:{T("panel")};border:1px solid {T("border")};border-radius:4px;}}'
            f'QProgressBar::chunk{{background:{T("accent")};border-radius:3px;}}')
        lay.addWidget(self._progress)

        # FFT info row + ETC checkbox
        info_row = QHBoxLayout(); info_row.setSpacing(10)
        self._fft_lbl = QLabel(_tx('FFT Size: —'))
        self._fft_lbl.setStyleSheet(f'color:{T("text_dim")};font-size:11px;')
        info_row.addWidget(self._fft_lbl, 1)
        self._etc_chk = QCheckBox('ETC')
        self._etc_chk.setStyleSheet(f'color:{T("text")};font-size:11px;')
        self._etc_chk.stateChanged.connect(self._on_etc_changed)
        info_row.addWidget(self._etc_chk)
        lay.addLayout(info_row)

        # Delay readout grid
        grid = QGridLayout(); grid.setSpacing(6)
        hdr_style  = f'color:{T("text_dim")};font-size:10px;font-weight:bold;'
        val_style  = f'color:{T("text")};font-size:11px;font-weight:bold;'
        dlta_style = f'color:{T("green")};font-size:11px;font-weight:bold;'
        lbl_style  = f'color:{T("text")};font-size:11px;'
        for col, txt in enumerate(['', 'ms', 'ft', 'm']):
            lbl = QLabel(txt); lbl.setAlignment(Qt.AlignCenter); lbl.setStyleSheet(hdr_style)
            grid.addWidget(lbl, 0, col)
        rows_def = [
            ('Measured Delay',         '_meas_ms',   '_meas_ft',   '_meas_m',   False),
            ('Current Delay Setting',  '_cur_ms',    '_cur_ft',    '_cur_m',    False),
            ('Delta Delay',            '_delta_ms',  '_delta_ft',  '_delta_m',  True),
        ]
        for r, (name, ms_attr, ft_attr, m_attr, is_delta) in enumerate(rows_def, start=1):
            vstyle = dlta_style if is_delta else val_style
            nl = QLabel(name); nl.setStyleSheet(lbl_style); grid.addWidget(nl, r, 0)
            for c, attr in enumerate([ms_attr, ft_attr, m_attr], start=1):
                lbl = QLabel('—'); lbl.setAlignment(Qt.AlignCenter); lbl.setStyleSheet(vstyle)
                setattr(self, attr + '_lbl', lbl); grid.addWidget(lbl, r, c)
        sep = QFrame(); sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f'color:{T("border")};'); lay.addWidget(sep)
        lay.addLayout(grid)

        lay.addStretch()

        # Buttons
        btn_row = QHBoxLayout(); btn_row.setSpacing(6)
        btn_style = ss_btn_neutral()   # 다이얼로그 버튼 통일
        self.insert_btn   = QPushButton(_tx('Insert'));     self.insert_btn.setEnabled(False)
        self.find_btn     = QPushButton(_tx('Find Delay'))
        self.advanced_btn = QPushButton(_tx('Advanced'))
        self.cancel_btn   = QPushButton(_tx('Cancel'))
        for b in (self.insert_btn, self.find_btn, self.advanced_btn, self.cancel_btn):
            b.setStyleSheet(btn_style); btn_row.addWidget(b)
        self.find_btn.setStyleSheet(ss_btn_primary())   # 주동작 강조
        self.insert_btn.clicked.connect(self._on_insert)
        self.find_btn.clicked.connect(self._on_find_delay)
        self.advanced_btn.clicked.connect(self._on_advanced)
        self.cancel_btn.clicked.connect(self.reject)
        lay.addLayout(btn_row)

        self._refresh_fft_label()

    def _refresh_fft_label(self):
        tw = self._tw
        fs = tw.fft_size; sr = tw.sample_rate
        size_k = fs // 1024
        dur_ms = round(fs / sr * 1000.0, 1)
        n_avg = tw._n_avg
        self._fft_lbl.setText(f'FFT Size: {size_k}k / {dur_ms}ms  (Avg: {n_avg})')

    def _start_find(self):
        if not self._tw._running:
            from PyQt5.QtWidgets import QMessageBox
            _BrandBox.information(self, _tx('Delay Finder'), _tx('Press Start first, then use this once signal is present.'))
            return
        self._tick_count = 0
        self._progress.setValue(0)
        self.find_btn.setEnabled(False)
        self.insert_btn.setEnabled(False)
        if self._prog_timer is not None:
            self._prog_timer.stop()
        self._prog_timer = QTimer(self)
        self._prog_timer.timeout.connect(self._tick)
        self._prog_timer.start(100)

    def _tick(self):
        self._tick_count += 1
        self._progress.setValue(min(self._tick_count * 5, 100))
        self._refresh_fft_label()
        if self._tick_count >= 20:
            self._prog_timer.stop()
            self._do_compute()

    def _do_compute(self):
        import threading
        from PyQt5.QtWidgets import QMessageBox
        tw = self._tw
        with QMutexLocker(tw._mutex):
            cross  = tw._cross_acc.copy()  if tw._cross_acc  is not None else None
            auto_x = tw._auto_acc_x.copy() if tw._auto_acc_x is not None else None
        if cross is None or auto_x is None:
            self.find_btn.setEnabled(True)
            sig_on = (tw._duplex_thread is not None and tw._duplex_thread.isRunning() and not tw._duplex_thread._muted) or \
                     (tw._sig_stream is not None)
            if not sig_on:
                _BrandBox.information(self, _tx('Delay Finder'),
                    _tx('No signal detected.\nTurn on Play (signal generator) and try again.'))
            else:
                _BrandBox.information(self, _tx('Delay Finder'),
                    _tx('Not enough data yet.\nCheck that signal is present and try again.'))
            return
        fft_size = tw.fft_size; sr = tw.sample_rate

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
            d_ms = round(float(peak) / sr * 1000.0, 2)
            self._result_sig.emit(d_ms)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_result(self, d_ms):
        self.find_btn.setEnabled(True)
        self._measured_ms = d_ms
        m_factor  = self._speed_ms / 1000.0
        ft_factor = m_factor * 3.28084
        cur_ms = self._tw.delay_spin.value()
        delta_ms = d_ms - cur_ms
        self._meas_ms_lbl.setText(f'{d_ms:.2f}')
        self._meas_ft_lbl.setText(f'{d_ms * ft_factor:.2f}')
        self._meas_m_lbl.setText(f'{d_ms * m_factor:.2f}')
        self._cur_ms_lbl.setText(f'{cur_ms:.2f}')
        self._cur_ft_lbl.setText(f'{cur_ms * ft_factor:.2f}')
        self._cur_m_lbl.setText(f'{cur_ms * m_factor:.2f}')
        self._delta_ms_lbl.setText(f'{delta_ms:+.2f}')
        self._delta_ft_lbl.setText(f'{delta_ms * ft_factor:+.2f}')
        self._delta_m_lbl.setText(f'{delta_ms * m_factor:+.2f}')
        self.insert_btn.setEnabled(True)
        self._refresh_fft_label()

    def _on_insert(self):
        if self._measured_ms is not None:
            d_ms = self._measured_ms
            self._tw.delay_spin.setValue(d_ms)
            self._tw.mag_cvs.fit_y()   # 보정 IR: 뷰는 건드리지 않음 (다른 카드 불변)
        self.accept()

    def _on_find_delay(self):
        self._start_find()

    def _on_advanced(self):
        dlg = _DelayAdvancedDialog(self, self._speed_ms)
        if dlg.exec_() == QDialog.Accepted:
            set_sound_speed(dlg.speed())     # 전역 단일 소스 갱신 → IR 마커/커서 m 환산 일치
            self._speed_ms = sound_speed()
            if self._measured_ms is not None:
                self._on_result(self._measured_ms)

    def _on_etc_changed(self, state):
        mode = 1 if state == Qt.Checked else 0
        self._tw.ir_cvs.set_mode(mode)

    def closeEvent(self, e):
        if self._prog_timer is not None and self._prog_timer.isActive():
            self._prog_timer.stop()
        super().closeEvent(e)


class AllDelayFinderDialog(QDialog):
    """L키: 활성화된 모든 카드 딜레이를 동시에 찾아 표시."""
    _results_sig = pyqtSignal(list)   # [(label, pair_idx_enc, d_ms), ...]

    def __init__(self, tw, parent=None):
        super().__init__(parent)
        self._tw = tw
        self._results = []
        self._tick_count = 0
        self._prog_timer = None
        self.setWindowTitle(_tx('Delay Finder') + ' — All Channels'); _apply_dark_titlebar(self)
        self.setFixedWidth(500)
        self.setStyleSheet(f'background:{T("bg2")};color:{T("text")};')
        self._build_ui()
        self._results_sig.connect(self._on_results)
        self._start_find()

    def _build_ui(self):
        import math as _math2
        _outer = QVBoxLayout(self); _outer.setSpacing(0); _outer.setContentsMargins(0, 0, 0, 0)
        _outer.addWidget(_dialog_brand_header(_tx('Delay Finder')))
        lay = QVBoxLayout(); lay.setContentsMargins(16,14,16,14); lay.setSpacing(8)
        _outer.addLayout(lay)

        self._progress = QProgressBar()
        self._progress.setRange(0,100); self._progress.setValue(0)
        self._progress.setFixedHeight(14); self._progress.setTextVisible(False)
        self._progress.setStyleSheet(
            f'QProgressBar{{background:{T("panel")};border:1px solid {T("border")};border-radius:4px;}}'
            f'QProgressBar::chunk{{background:{T("accent")};border-radius:3px;}}')
        lay.addWidget(self._progress)

        # 결과 테이블 헤더
        hdr_style = f'color:{T("text_dim")};font-size:10px;font-weight:bold;'
        val_style = f'color:{T("text")};font-size:11px;'
        g = QGridLayout(); g.setSpacing(5)
        for col, txt in enumerate(['Card', 'Measured', 'Current', 'Delta']):
            l = QLabel(txt); l.setAlignment(Qt.AlignCenter); l.setStyleSheet(hdr_style)
            g.addWidget(l, 0, col)
        sep = QFrame(); sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f'color:{T("border")};')
        g.addWidget(sep, 1, 0, 1, 4)
        self._grid = g; self._grid_row_offset = 2
        self._row_widgets = []   # [(card_lbl, meas_lbl, cur_lbl, delta_lbl)]
        lay.addLayout(g)
        lay.addStretch()

        btn_row = QHBoxLayout(); btn_row.setSpacing(6)
        btn_s = ss_btn_neutral()   # 다이얼로그 버튼 통일
        self._insert_btn = QPushButton(_tx('Insert All (Enter)')); self._insert_btn.setEnabled(False)
        self._find_btn   = QPushButton(_tx('Find Again (L)'))
        self._cancel_btn = QPushButton(_tx('Cancel'))
        for b in (self._insert_btn, self._find_btn, self._cancel_btn):
            b.setStyleSheet(btn_s)
            b.setAutoDefault(False); b.setDefault(False)   # Enter는 keyPressEvent에서 처리(항상 적용)
            btn_row.addWidget(b)
        self._find_btn.setStyleSheet(ss_btn_primary())   # 주동작 강조
        self._insert_btn.clicked.connect(self._on_insert_all)
        self._find_btn.clicked.connect(self._start_find)
        self._cancel_btn.clicked.connect(self.reject)
        lay.addLayout(btn_row)

    def _start_find(self):
        if not self._tw._running:
            from PyQt5.QtWidgets import QMessageBox
            _BrandBox.information(self, _tx('Delay Finder'),
                _tx('Press Start first, then use this once signal is present.'))
            return
        self._results = []
        self._insert_btn.setEnabled(False)
        self._tick_count = 0; self._progress.setValue(0)
        # 행 초기화
        for ws in self._row_widgets:
            for w in ws: w.setText('—')
        if self._prog_timer: self._prog_timer.stop()
        self._prog_timer = QTimer(self)
        self._prog_timer.timeout.connect(self._tick)
        self._prog_timer.start(100)

    def _tick(self):
        self._tick_count += 1
        self._progress.setValue(min(self._tick_count * 5, 100))
        if self._tick_count >= 20:
            self._prog_timer.stop(); self._do_compute()

    def _do_compute(self):
        import threading, math as _m
        tw = self._tw
        # 활성화된 pair 수집
        pairs = []
        if not getattr(tw, '_primary_deleted', False):
            if tw._level_cards and tw._level_cards[0]._display_on:
                pairs.append((-1, 'Card 1', None, None))  # (enc, label, cross, auto_x)
        for i, pair in enumerate(tw._extra_pairs):
            if not pair.get('display', False): continue
            p_meas_idx = pair['meas_cb'].currentData()
            ref_idx = tw.ref_cb.currentData()
            if p_meas_idx is not None and ref_idx is not None and p_meas_idx != ref_idx:
                pairs.append((i, f'Card {i+2}', 'cross_device', None))
                continue
            cb = pair.get('meas_cb')
            dev_txt = cb.currentText() if cb else '?'
            ch_cb = pair.get('meas_ch_cb')
            ch_txt = ch_cb.currentText() if ch_cb else '?'
            pairs.append((i, f'Card {i+2}', None, None))

        # 기존 행 재사용 또는 추가
        val_style = f'color:{T("text")};font-size:11px;'
        dim_style = f'color:{T("text_dim")};font-size:11px;'
        while len(self._row_widgets) < len(pairs):
            r = self._grid_row_offset + len(self._row_widgets)
            ws = []
            for c in range(4):
                l = QLabel('—'); l.setAlignment(Qt.AlignCenter); l.setStyleSheet(val_style)
                self._grid.addWidget(l, r, c); ws.append(l)
            self._row_widgets.append(ws)

        # 라벨 설정
        for idx, (enc, label, cross_flag, _) in enumerate(pairs):
            if idx < len(self._row_widgets):
                self._row_widgets[idx][0].setText(label)

        # 누적값 수집 — primary는 헬퍼로(Single=누적, MTW=버퍼 산출). 자체 락 사용.
        prim_cross, prim_auto = tw._primary_delay_cross_auto()
        tasks = []
        with QMutexLocker(tw._mutex):
            for enc, label, cross_flag, _ in pairs:
                if cross_flag == 'cross_device':
                    tasks.append((enc, label, None, None, 0.0))
                    continue
                if enc == -1:
                    cross, auto_x = prim_cross, prim_auto
                    base_ms = float(tw.delay_ms)
                else:
                    acc = tw._extra_pair_acc[enc] if enc < len(tw._extra_pair_acc) else None
                    cross = acc['cross'].copy() if acc else None
                    auto_x = acc['auto_x'].copy() if acc else None
                    base_ms = float(tw._extra_pairs[enc].get('delay_ms', 0.0)) \
                              if enc < len(tw._extra_pairs) else 0.0
                # 누적은 현재 딜레이로 이미 정렬됨 → 잔여+base=참값 [DELAY_FIND_ABS]
                tasks.append((enc, label, cross, auto_x, base_ms))

        fft_size = tw.fft_size; sr = tw.sample_rate

        def _worker():
            out = []
            for enc, label, cross, auto_x, base_ms in tasks:
                if cross is None:
                    out.append((label, enc, None)); continue
                H = cross / np.maximum(auto_x, 1e-30)
                h = np.fft.irfft(H, n=fft_size)
                env = _hilbert_env(h)
                peak = int(np.argmax(env))
                if 0 < peak < len(env) - 1:
                    y0, y1, y2 = float(env[peak-1]), float(env[peak]), float(env[peak+1])
                    denom = 2*(2*y1 - y0 - y2)
                    if denom > 0: peak += (y2 - y0) / denom
                if peak > fft_size // 2: peak -= fft_size
                d_ms = round(base_ms + float(peak) / sr * 1000.0, 2)   # 잔여+현재딜레이=참 딜레이
                out.append((label, enc, d_ms))
            self._results_sig.emit(out)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_results(self, results):
        self._results = results
        tw = self._tw
        val_s  = f'color:{T("text")};font-size:11px;'
        g_s    = f'color:{T("green")};font-size:11px;font-weight:bold;'
        dim_s  = f'color:{T("text_dim")};font-size:11px;'
        any_valid = False
        for idx, (label, enc, d_ms) in enumerate(results):
            if idx >= len(self._row_widgets): break
            ws = self._row_widgets[idx]
            if d_ms is None:
                ws[1].setText('N/A'); ws[1].setStyleSheet(dim_s)
                ws[2].setText('—');   ws[3].setText('—')
                continue
            # current delay
            if enc == -1:
                cur = tw.delay_ms
            else:
                cur = tw._extra_pairs[enc].get('delay_ms', 0.0) if enc < len(tw._extra_pairs) else 0.0
            delta = d_ms - cur
            ws[1].setText(fmt_delay(d_ms)); ws[1].setStyleSheet(val_s)
            ws[2].setText(fmt_delay(cur));  ws[2].setStyleSheet(val_s)
            ws[3].setText(fmt_delay(delta, sign=True))
            ws[3].setStyleSheet(g_s if abs(delta) < 1.0 else val_s)
            any_valid = True
        self._insert_btn.setEnabled(any_valid)
        self.adjustSize()

    def _on_insert_all(self):
        tw = self._tw
        for label, enc, d_ms in self._results:
            if d_ms is None: continue
            if enc == -1:
                if tw._level_cards and hasattr(tw._level_cards[0], '_delay_spin'):
                    tw._level_cards[0]._delay_spin.setValue(d_ms)
            else:
                if enc < len(tw._extra_pairs):
                    card = tw._extra_pairs[enc].get('card')
                    if card and hasattr(card, 'set_delay'):
                        card.set_delay(d_ms)
                        tw._extra_pairs[enc]['delay_ms'] = d_ms
        self.accept()

    def keyPressEvent(self, e):
        # L = 다시 탐색,  Enter = 딜레이값 적용(Insert All)
        k = e.key()
        if k == Qt.Key_L:
            self._start_find(); e.accept(); return
        if k in (Qt.Key_Return, Qt.Key_Enter):
            if self._insert_btn.isEnabled():
                self._on_insert_all()
            e.accept(); return
        super().keyPressEvent(e)   # Esc 등 기본 동작 유지

    def closeEvent(self, e):
        if self._prog_timer and self._prog_timer.isActive():
            self._prog_timer.stop()
        super().closeEvent(e)


class _AuralizeDialog(QDialog):
    """오라리제이션 — 측정한 IR로 '그 자리 소리'를 헤드폰으로 듣기.

    아무 음악 파일을 측정 IR과 컨볼루션해 재생. 원음(Dry) vs 공간(Room) A/B.
    ⚠️헤드폰/노트북 출력으로 들을 것(측정한 PA로 내보내면 룸이 두 번 걸림).
    측정 엔진과 격리(자체 sd.play).
    """
    def __init__(self, tf_win, parent=None):
        super().__init__(parent)
        self._tf = tf_win
        self._music = None          # 모노 float32, tf.sample_rate
        self._music_sr = None       # _music이 리샘플된 SR (장치 SR 바뀌면 재리샘플 판정)
        self._wet = None            # 컨볼루션 결과 캐시
        self._wet_sig = None        # _wet가 어느 IR로 빌드됐는지(재측정 stale 방지)
        self._conv = None; self._pending_play = False
        self._music_name = ''
        self.setWindowTitle(_tx('Auralization'))
        _apply_dark_titlebar(self)
        self.setStyleSheet(f'background:{T("bg2")};color:{T("text")};')
        self.setMinimumWidth(340)
        _dim = T('text_dim'); _bd = T('border')

        outer = QVBoxLayout(self); outer.setSpacing(0); outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(_grad_topline())               # SPECTRA 브랜드 헤어라인(정적)
        body = QWidget(); lay = QVBoxLayout(body); lay.setSpacing(10); lay.setContentsMargins(16, 14, 16, 16)
        outer.addWidget(body)

        hint = QLabel(_tx('Hear music through the measured space.  Use headphones.'))
        hint.setStyleSheet(f'color:{_dim};font-size:11px;background:transparent;'); hint.setWordWrap(True)
        lay.addWidget(hint)

        # 측정한 방(IR) 미리보기 + 소스 선택(라이브/캡처) — 시그니처(진짜 측정 데이터)
        caprow = QHBoxLayout(); caprow.setSpacing(8)
        cap = QLabel(_tx('MEASURED ROOM'))
        cap.setStyleSheet(f'color:{_dim};font-size:9px;font-weight:bold;letter-spacing:1px;background:transparent;')
        self._ir_cb = RoundComboBox(); self._ir_cb.setFixedHeight(24); self._ir_cb.setMinimumWidth(140)
        self._populate_ir_sources()
        self._ir_cb.currentIndexChanged.connect(self._on_ir_src_changed)
        caprow.addWidget(cap); caprow.addStretch(); caprow.addWidget(self._ir_cb)
        lay.addLayout(caprow)
        self._ir_view = QLabel(); self._ir_view.setFixedHeight(54)
        self._ir_view.setStyleSheet(f'background:{T("bg")};border:1px solid {_bd};border-radius:6px;')
        lay.addWidget(self._ir_view)

        row1 = QHBoxLayout(); row1.setSpacing(8)
        self._load_btn = QPushButton(_tx('Load music…')); self._load_btn.setStyleSheet(ss_btn_neutral())
        self._load_btn.clicked.connect(self._load_music)
        self._music_lbl = QLabel(_tx('no file')); self._music_lbl.setStyleSheet(f'color:{_dim};font-size:11px;background:transparent;')
        row1.addWidget(self._load_btn); row1.addWidget(self._music_lbl, 1)
        lay.addLayout(row1)

        row2 = QHBoxLayout(); row2.setSpacing(8)
        _ol = QLabel(_tx('Output')); _ol.setStyleSheet(f'color:{_dim};font-size:11px;background:transparent;'); _ol.setFixedWidth(46)
        self._out_cb = RoundComboBox(); self._populate_outputs()
        row2.addWidget(_ol); row2.addWidget(self._out_cb, 1)
        lay.addLayout(row2)

        lay.addSpacing(2); lay.addWidget(hsep())
        row3 = QHBoxLayout(); row3.setSpacing(8)
        self._dry_btn = QPushButton('  ' + _tx('Dry'));  self._dry_btn.setIcon(_icon('play', 13, color='#FFFFFF'))
        self._room_btn = QPushButton('  ' + _tx('Room')); self._room_btn.setIcon(_icon('play', 13, color='#FFFFFF'))
        self._stop_btn = QPushButton(''); self._stop_btn.setIcon(_icon('stop', 15, color=T('red'))); self._stop_btn.setFixedWidth(46)
        self._stop_btn.setToolTip(_tx('Stop playback'))
        self._stop_btn.setStyleSheet(ss_btn_neutral())
        self._dry_btn.clicked.connect(lambda: self._play('dry'))
        self._room_btn.clicked.connect(lambda: self._play('room'))
        self._stop_btn.clicked.connect(self._stop)
        row3.addWidget(self._dry_btn, 1); row3.addWidget(self._room_btn, 1); row3.addWidget(self._stop_btn)
        lay.addLayout(row3)
        # 재생 중인 쪽만 파란불 — 재생 끝나면 폴 타이머가 자동으로 끔
        self._playing = None; self._set_active(None)
        self._poll_t = QTimer(self); self._poll_t.setInterval(200); self._poll_t.timeout.connect(self._poll_playing)

        self._refresh_ir_state()
        self._set_playable(False)

    def _set_active(self, which):
        """재생 중인 버튼만 파란불(primary), 나머지는 중립."""
        self._playing = which
        self._dry_btn.setStyleSheet(ss_btn_primary() if which == 'dry' else ss_btn_neutral())
        self._room_btn.setStyleSheet(ss_btn_primary() if which == 'room' else ss_btn_neutral())

    def _poll_playing(self):
        try:
            st = sd.get_stream(); active = st is not None and st.active
        except Exception:
            active = False
        if not active:
            self._poll_t.stop(); self._set_active(None)

    def _render_ir_view(self):
        """측정 IR을 앱 IR 캔버스 스타일(얇은 청록 트레이스)로 그려 넣기 — 방의 지문."""
        w_, h_ = 306, 54
        pm = QPixmap(w_, h_); pm.fill(QColor(T('bg')))
        p = QPainter(pm); p.setRenderHint(QPainter.Antialiasing, True)
        p.setPen(QPen(QColor(T('border')), 1)); p.drawLine(8, h_ // 2, w_ - 8, h_ // 2)
        ir, _ = self._current_ir()
        if ir is not None and len(ir) > 4:
            h = np.asarray(ir, dtype=float)
            pk = int(np.argmax(np.abs(h)))
            b = min(len(h), pk + int(0.05 * self._sr()))
            seg = h[max(0, pk - 16):b]
            if len(seg) >= 2:
                seg = seg / (np.max(np.abs(seg)) or 1.0)
                n = len(seg); xs = 8 + np.arange(n) / max(n - 1, 1) * (w_ - 16)
                ys = h_ / 2 - seg * (h_ / 2) * 0.82
                p.setPen(QPen(QColor('#2DD4BF'), 1.6)); p.setBrush(Qt.NoBrush)   # 앱 IR 색(teal)
                p.drawPolyline(QPolygonF([QPointF(float(x), float(y)) for x, y in zip(xs, ys)]))
        else:
            p.setPen(QColor(T('text_dim'))); p.setFont(_qfont(11))
            p.drawText(pm.rect(), Qt.AlignCenter, _tx('measure first (TF / sweep)'))
        p.end()
        self._ir_view.setPixmap(pm)

    def _populate_outputs(self):
        self._out_cb.clear()
        try:
            devs = sd.query_devices()
            default_out = sd.default.device[1] if sd.default.device else -1
        except Exception:
            devs = []; default_out = -1
        sel = 0
        for i, d in enumerate(devs):
            if int(d.get('max_output_channels', 0)) > 0:
                self._out_cb.addItem(d['name'], i)
                if i == default_out:
                    sel = self._out_cb.count() - 1
        if self._out_cb.count() == 0:
            self._out_cb.addItem(_tx('(default)'), None)
        self._out_cb.setCurrentIndex(sel)

    def _populate_ir_sources(self):
        """IR 소스 목록 — 라이브 측정 + IR 있는 캡처들(캡처 데이터도 들을 수 있게)."""
        self._ir_cb.blockSignals(True)
        self._ir_cb.clear()
        ir = getattr(self._tf, 'ir_cvs', None)
        if ir is not None and getattr(ir, 'h_raw', None) is not None and len(ir.h_raw) > 4:
            self._ir_cb.addItem(_tx('Live'), ('live', -1))
        for i, c in enumerate(getattr(ir, '_captures', []) if ir else []):
            if c.get('h') is not None and len(c['h']) > 4:
                self._ir_cb.addItem(c.get('label', f'Capture {i+1}'), ('cap', i))
        if self._ir_cb.count() == 0:
            self._ir_cb.addItem(_tx('— none —'), (None, -1))
        self._ir_cb.blockSignals(False)

    def _on_ir_src_changed(self, *_):
        self._wet = None                # 소스 바뀌면 컨볼루션 캐시 무효화
        self._refresh_ir_state()
        self._set_playable()

    def _current_ir(self):
        """선택된 IR(h) — 드롭다운(라이브/캡처)."""
        ir = getattr(self._tf, 'ir_cvs', None)
        if ir is None: return None, ''
        data = self._ir_cb.currentData() if hasattr(self, '_ir_cb') else ('live', -1)
        if not data: return None, ''
        kind, idx = data
        if kind == 'live' and getattr(ir, 'h_raw', None) is not None and len(ir.h_raw) > 4:
            return np.asarray(ir.h_raw, dtype=np.float32), _tx('Live')
        if kind == 'cap':
            caps = getattr(ir, '_captures', [])
            if 0 <= idx < len(caps) and caps[idx].get('h') is not None:
                return np.asarray(caps[idx]['h'], dtype=np.float32), caps[idx].get('label', 'capture')
        return None, ''

    def _refresh_ir_state(self):
        ir, name = self._current_ir()
        self._has_ir = ir is not None
        self._render_ir_view()

    def _set_playable(self, on=True):
        has_music = self._music is not None
        self._dry_btn.setEnabled(has_music)
        self._room_btn.setEnabled(has_music and self._has_ir)

    def _sr(self):
        return int(getattr(self._tf, 'sample_rate', 48000) or 48000)

    def _load_music(self):
        from PyQt5.QtWidgets import QFileDialog
        import os
        path, _ = QFileDialog.getOpenFileName(
            self, _tx('Select music file'), '',
            'Audio (*.wav *.flac *.aiff *.aif *.ogg *.mp3 *.m4a *.caf);;All Files (*)')
        if not path:
            return
        data = sr = None
        try:
            import soundfile as sf
            data, sr = sf.read(path, dtype='float32', always_2d=False)
        except ImportError:
            try:
                from scipy.io import wavfile as wf
                sr, raw = wf.read(path)
                data = raw.astype(np.float32) / (32768.0 if raw.dtype == np.int16 else 1.0)
            except Exception as e:
                _BrandBox.warning(self, _tx('Auralization'), _tx('Cannot read file:\n{e}').format(e=e)); return
        except Exception as e:
            _BrandBox.warning(self, _tx('Auralization'), _tx('Cannot read file:\n{e}').format(e=e)); return
        if data.ndim == 2:
            data = data.mean(axis=1)
        srr = self._sr()
        if sr != srr:
            n_new = max(1, int(len(data) * srr / sr))
            data = np.interp(np.linspace(0, len(data)-1, n_new), np.arange(len(data)), data)
        data = np.asarray(data, dtype=np.float32)
        pk = float(np.max(np.abs(data))) if len(data) else 0.0
        if pk > 1e-6: data = (data / pk * 0.9).astype(np.float32)
        self._music = data; self._music_sr = srr; self._wet = None; self._wet_sig = None
        self._music_name = os.path.basename(path)
        self._music_lbl.setText(self._music_name[:22] + ('…' if len(self._music_name) > 22 else ''))
        self._refresh_ir_state()
        self._set_playable(True)

    @staticmethod
    def _ir_sig(ir):
        # IR 식별 시그니처 — 재측정(Live IR 교체) 감지해 stale wet 캐시 무효화.
        # ⚠️캡처는 SR 미저장 → 다른 SR로 측정된 옛 캡처는 타이밍 어긋날 수 있음
        #   (현 세션 캡처·Live IR은 항상 현재 SR이라 정상).
        return (len(ir), round(float(ir.sum()), 5), round(float(np.abs(ir).max()), 5))

    def _ensure_music_sr(self):
        """재생 직전, TF 장치 SR이 로드 시점과 달라졌으면 음악을 현재 SR로 재리샘플.
        (SR 바뀐 뒤 옛 SR 버퍼를 그대로 재생하면 피치가 틀어지고 Room 컨볼루션도 오염됨.)"""
        if self._music is None: return
        cur = self._sr(); old = getattr(self, '_music_sr', None)
        if old and old != cur and len(self._music) > 1:
            n_new = max(1, int(len(self._music) * cur / old))
            self._music = np.interp(np.linspace(0, len(self._music)-1, n_new),
                                    np.arange(len(self._music)), self._music).astype(np.float32)
            self._music_sr = cur
            self._wet = None; self._wet_sig = None   # 옛 SR 컨볼루션 캐시 무효화

    def _play(self, which):
        self._ensure_music_sr()
        if which == 'dry':
            self._pending_play = False
            self._set_active('dry'); self._start_playback(self._music); return
        ir, _ = self._current_ir()
        if ir is None or self._music is None: return
        sig = self._ir_sig(ir)
        if self._wet is not None and self._wet_sig == sig:   # 유효 캐시 → 즉시 재생
            self._pending_play = False
            self._set_active('room'); self._start_playback(self._wet); return
        if self._conv is not None and self._conv.isRunning(): return
        # 캐시 없음/stale → 백그라운드 컨볼루션 후 재생 (긴 곡에서 UI 프리즈 방지)
        self._pending_play = True
        self._room_btn.setEnabled(False); self._room_btn.setText('  …')
        self._conv = _ConvWorker(self._music, ir, sig)
        self._conv.done.connect(self._on_conv_done)
        self._conv.start()

    def _on_conv_done(self, wet):
        cur, _ = self._current_ir()
        cur_sig = self._ir_sig(cur) if cur is not None else None
        self._wet = wet; self._wet_sig = getattr(self._conv, 'sig', None)
        self._room_btn.setText('  ' + _tx('Room')); self._set_playable()
        if self._pending_play and cur_sig == self._wet_sig:  # 대기 중 소스 안 바뀌었으면 재생
            self._pending_play = False
            self._set_active('room'); self._start_playback(wet)

    def _start_playback(self, buf):
        if buf is None: return
        if buf.dtype != np.float32: buf = buf.astype(np.float32)
        stereo = np.column_stack([buf, buf])                 # 양 귀로 (buf는 이미 float32)
        dev = self._out_cb.currentData()
        try:
            sd.stop(); sd.play(stereo, self._sr(), device=dev)
            self._poll_t.start()                             # 재생 끝나면 불 자동 끔
        except Exception as e:
            self._set_active(None)
            _BrandBox.warning(self, _tx('Auralization'), _tx('Playback failed:\n{e}').format(e=e))

    def _stop(self):
        self._pending_play = False
        self._poll_t.stop(); self._set_active(None)
        try: sd.stop()
        except Exception: pass

    def closeEvent(self, e):
        self._stop()
        if self._conv is not None and self._conv.isRunning():
            self._conv.wait(2000)
        super().closeEvent(e)


class ColorPickerDialog(QDialog):
    preset_chosen = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_tx('Bar Color'))
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
            border_css = f'2px solid {T("text")}' if selected else f'1px solid {brd}'
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
