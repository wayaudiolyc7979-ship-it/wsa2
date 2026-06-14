#!/usr/bin/env python3
"""WSA2 라이선스 키 생성 도구 (개발자 전용)"""

import sys, os, hmac, hashlib, base64, json, datetime, platform
import ed25519_min as _ed

# ── 레거시 HMAC SECRET (v1.0 발급 키 검증용) ──────────────────────
_SECRET = b'W4y4ud10_WSA2_Lic_\xde\xad\xbe\xef\x01\x23\x45\x67'
# ── Ed25519 마스터 개인키 (신규 키 서명용) ──
_PRIV = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'license_ed25519_private.key')
def _load_seed():
    if not os.path.exists(_PRIV):
        raise FileNotFoundError(f'개인키 없음: {_PRIV} (마스터 키 파일을 이 경로에 두세요)')
    return bytes.fromhex(open(_PRIV).read().strip())

if platform.system() == 'Windows':
    _RECORDS_DIR = os.path.join(os.environ.get('APPDATA', os.path.expanduser('~')), 'WAYAUDIO')
else:
    _RECORDS_DIR = os.path.expanduser('~/Library/Application Support/WAYAUDIO')
_RECORDS_PATH = os.path.join(_RECORDS_DIR, 'issued_keys.json')

# ─────────────────────────────────────────────────────────────────────────────
#  라이선스 로직
# ─────────────────────────────────────────────────────────────────────────────
def generate_key(machine_id: str, expiry_year: int = 0) -> str:
    """신규 = Ed25519 비대칭 서명."""
    mid = machine_id.upper().strip()[:12].ljust(12, '0')
    payload = f'{mid}:{expiry_year:04d}'.encode()
    seed = _load_seed()
    sig = _ed.sign(payload, seed, _ed.public_key(seed))
    b32 = base64.b32encode(b'\x01' + payload + sig).decode().rstrip('=')
    return '-'.join(b32[i:i+5] for i in range(0, len(b32), 5))

def _check_payload(payload, machine_id):
    key_mid, expiry_str = payload.decode().split(':')[:2]
    if key_mid != machine_id.upper()[:12]:
        return False, '머신 ID 불일치'
    expiry = int(expiry_str)
    if expiry > 0 and datetime.date.today().year > expiry:
        return False, f'{expiry}년 만료'
    return True, '유효'

def verify_key(key: str, machine_id: str) -> tuple:
    """듀얼: 신규 Ed25519 → 레거시 HMAC."""
    clean = key.upper().replace('-', '').replace(' ', '')
    try:
        data = base64.b32decode(clean + '=' * ((8 - len(clean) % 8) % 8))
    except Exception as e:
        return False, f'형식 오류: {e}'
    # 신규 Ed25519
    if len(data) >= 65 and data[0] == 1:
        try:
            payload, sig = data[1:-64], data[-64:]
            if _ed.verify(sig, payload, _ed.public_key(_load_seed())):
                return _check_payload(payload, machine_id)
        except Exception:
            pass
    # 레거시 HMAC
    try:
        sig, payload = data[:10], data[10:]
        expected = hmac.new(_SECRET, payload, hashlib.sha256).digest()[:10]
        if not hmac.compare_digest(sig, expected):
            return False, '서명 불일치'
        return _check_payload(payload, machine_id)
    except Exception as e:
        return False, f'형식 오류: {e}'

def load_records():
    try:
        with open(_RECORDS_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return []

def save_record(record: dict):
    os.makedirs(os.path.dirname(_RECORDS_PATH), exist_ok=True)
    records = load_records()
    records.append(record)
    with open(_RECORDS_PATH, 'w', encoding='utf-8') as f:
        json.dump(records, f, ensure_ascii=False, indent=2)


# ─────────────────────────────────────────────────────────────────────────────
#  GUI
# ─────────────────────────────────────────────────────────────────────────────
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QSpinBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QFrame, QMessageBox, QFileDialog,
    QGroupBox, QSplitter, QAbstractItemView, QSizePolicy
)
from PyQt5.QtCore import Qt, QSize
from PyQt5.QtGui  import QFont, QColor, QPalette, QClipboard, QIcon

# ── 다크 팔레트 ───────────────────────────────────────────────────────────────
BG      = '#0d0d1a'
BG2     = '#13131f'
BG3     = '#1a1a2e'
ACCENT  = '#00d4aa'
ACCENT2 = '#ff6b35'
TEXT    = '#e8e8f0'
DIM     = '#666680'
BORDER  = '#2a2a3e'

SS_BASE = f"""
QWidget        {{ background:{BG}; color:{TEXT}; font-family:'SF Pro Display','Helvetica Neue',sans-serif; }}
QGroupBox      {{ border:1px solid {BORDER}; border-radius:8px; margin-top:10px; font-size:12px; color:{DIM}; padding:6px; }}
QGroupBox::title {{ subcontrol-origin:margin; left:10px; color:{ACCENT}; font-weight:bold; }}
QLineEdit      {{ background:{BG3}; border:1px solid {BORDER}; border-radius:6px; padding:6px 10px;
                  color:{TEXT}; font-size:13px; selection-background-color:{ACCENT}; }}
QLineEdit:focus {{ border:1px solid {ACCENT}; }}
QSpinBox       {{ background:{BG3}; border:1px solid {BORDER}; border-radius:6px; padding:4px 8px;
                  color:{TEXT}; font-size:13px; }}
QSpinBox::up-button, QSpinBox::down-button {{ width:18px; background:{BG3}; border:none; }}
QPushButton    {{ background:{BG3}; color:{TEXT}; border:1px solid {BORDER}; border-radius:6px;
                  padding:7px 16px; font-size:12px; }}
QPushButton:hover   {{ background:{ACCENT}; color:#000; border-color:{ACCENT}; }}
QPushButton:pressed {{ background:#009f80; color:#000; }}
QPushButton:disabled {{ color:{DIM}; border-color:{BORDER}; background:{BG2}; }}
QTableWidget   {{ background:{BG2}; border:1px solid {BORDER}; border-radius:6px;
                  gridline-color:{BORDER}; font-size:11px; }}
QTableWidget::item {{ padding:4px 8px; border:none; }}
QTableWidget::item:selected {{ background:rgba(0,212,170,30); color:{TEXT}; }}
QHeaderView::section {{ background:{BG3}; color:{DIM}; border:none; border-bottom:1px solid {BORDER};
                         padding:6px 8px; font-size:11px; font-weight:bold; }}
QScrollBar:vertical {{ background:{BG2}; width:8px; border-radius:4px; }}
QScrollBar::handle:vertical {{ background:{BORDER}; border-radius:4px; min-height:30px; }}
QLabel {{ background:transparent; }}
"""

class KeyDisplay(QFrame):
    """생성된 키를 강조 표시하는 위젯."""
    def __init__(self):
        super().__init__()
        self.setFrameShape(QFrame.StyledPanel)
        self.setStyleSheet(f'background:{BG3};border:2px solid {BORDER};border-radius:10px;padding:4px;')
        lay = QVBoxLayout(self); lay.setContentsMargins(16,14,16,14); lay.setSpacing(6)

        hdr = QLabel('생성된 시리얼 키')
        hdr.setStyleSheet(f'font-size:11px;color:{DIM};font-weight:bold;')
        lay.addWidget(hdr)

        self._lbl = QLabel('—')
        self._lbl.setStyleSheet(
            f'font-size:18px;font-family:monospace;font-weight:bold;color:{ACCENT};'
            f'letter-spacing:1px;')
        self._lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._lbl.setWordWrap(True)
        lay.addWidget(self._lbl)

        btn_row = QHBoxLayout()
        self._copy_btn = QPushButton('클립보드 복사')
        self._copy_btn.setEnabled(False)
        self._copy_btn.setStyleSheet(
            f'background:{ACCENT};color:#000;font-weight:bold;border-radius:6px;padding:6px 18px;')
        self._copy_btn.clicked.connect(self._copy)
        self._status = QLabel('')
        self._status.setStyleSheet(f'font-size:11px;color:{ACCENT};')
        btn_row.addWidget(self._copy_btn); btn_row.addWidget(self._status); btn_row.addStretch()
        lay.addLayout(btn_row)

        self._key = ''

    def set_key(self, key: str):
        self._key = key
        self._lbl.setText(key)
        self._copy_btn.setEnabled(bool(key))
        self._status.setText('')
        self.setStyleSheet(
            f'background:{BG3};border:2px solid {ACCENT};border-radius:10px;padding:4px;')

    def clear(self):
        self._key = ''
        self._lbl.setText('—')
        self._copy_btn.setEnabled(False)
        self.setStyleSheet(
            f'background:{BG3};border:2px solid {BORDER};border-radius:10px;padding:4px;')

    def _copy(self):
        if self._key:
            QApplication.clipboard().setText(self._key)
            self._status.setText('복사됨!')


class LicenseTool(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('WSA2 라이선스 키 생성기  [개발자 전용]')
        self.setMinimumSize(820, 680)
        self.resize(920, 720)
        self._build_ui()
        self._refresh_table()

    # ── UI 구성 ──────────────────────────────────────────────────────────────
    def _build_ui(self):
        root = QWidget(); self.setCentralWidget(root)
        main = QVBoxLayout(root); main.setContentsMargins(20,20,20,20); main.setSpacing(16)

        # 타이틀
        title = QLabel('WSA2  License Key Generator')
        title.setStyleSheet(f'font-size:20px;font-weight:bold;color:{ACCENT};letter-spacing:1px;')
        sub = QLabel('개발자 전용 도구 — 외부 유출 금지')
        sub.setStyleSheet(f'font-size:11px;color:{ACCENT2};')
        main.addWidget(title); main.addWidget(sub)

        sep = QFrame(); sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f'background:{BORDER};max-height:1px;')
        main.addWidget(sep)

        # ── 발급 폼 ──
        form_grp = QGroupBox('새 라이선스 발급')
        form_lay = QVBoxLayout(form_grp); form_lay.setSpacing(12)

        # 머신 ID
        mid_row = QHBoxLayout()
        mid_lbl = QLabel('머신 ID:')
        mid_lbl.setFixedWidth(90)
        mid_lbl.setStyleSheet(f'font-size:12px;color:{DIM};')
        self._mid_edit = QLineEdit()
        self._mid_edit.setPlaceholderText('사용자 앱의 머신 ID 12자리  (예: 8BDFC136A562)')
        self._mid_edit.setMaxLength(12)
        self._mid_edit.textChanged.connect(self._on_input_changed)
        mid_clear = QPushButton('지우기')
        mid_clear.setFixedWidth(70)
        mid_clear.clicked.connect(lambda: self._mid_edit.clear())
        mid_row.addWidget(mid_lbl); mid_row.addWidget(self._mid_edit, 1); mid_row.addWidget(mid_clear)
        form_lay.addLayout(mid_row)

        # 고객 이름
        name_row = QHBoxLayout()
        name_lbl = QLabel('고객 이름:')
        name_lbl.setFixedWidth(90)
        name_lbl.setStyleSheet(f'font-size:12px;color:{DIM};')
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText('기록용 (선택사항)')
        name_row.addWidget(name_lbl); name_row.addWidget(self._name_edit, 1)
        form_lay.addLayout(name_row)

        # 만료 연도
        exp_row = QHBoxLayout()
        exp_lbl = QLabel('만료 연도:')
        exp_lbl.setFixedWidth(90)
        exp_lbl.setStyleSheet(f'font-size:12px;color:{DIM};')
        self._exp_spin = QSpinBox()
        self._exp_spin.setRange(0, 2099)
        self._exp_spin.setValue(0)
        self._exp_spin.setSpecialValueText('영구 (만료 없음)')
        self._exp_spin.setFixedWidth(180)
        exp_note = QLabel('0 = 영구  |  연도 입력 시 해당 연도 12월 31일까지')
        exp_note.setStyleSheet(f'font-size:11px;color:{DIM};')
        exp_row.addWidget(exp_lbl); exp_row.addWidget(self._exp_spin); exp_row.addWidget(exp_note); exp_row.addStretch()
        form_lay.addLayout(exp_row)

        # 생성 버튼
        gen_row = QHBoxLayout()
        self._gen_btn = QPushButton('  키 생성')
        self._gen_btn.setFixedHeight(36)
        self._gen_btn.setEnabled(False)
        self._gen_btn.setStyleSheet(
            f'background:{ACCENT};color:#000;font-weight:bold;font-size:13px;'
            f'border-radius:8px;padding:0 24px;')
        self._gen_btn.clicked.connect(self._generate)
        gen_row.addStretch(); gen_row.addWidget(self._gen_btn)
        form_lay.addLayout(gen_row)

        main.addWidget(form_grp)

        # ── 결과 표시 ──
        self._key_display = KeyDisplay()
        main.addWidget(self._key_display)

        # ── 발급 기록 ──
        rec_grp = QGroupBox('발급 기록')
        rec_lay = QVBoxLayout(rec_grp); rec_lay.setSpacing(8)

        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(['발급일', '고객 이름', '머신 ID', '만료', '시리얼 키'])
        self._table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self._table.setColumnWidth(0, 130)
        self._table.setColumnWidth(2, 130)
        self._table.setColumnWidth(3, 80)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.setStyleSheet(
            self._table.styleSheet() +
            f'QTableWidget::item:alternate{{background:{BG3};}}')
        self._table.doubleClicked.connect(self._copy_selected_key)
        rec_lay.addWidget(self._table)

        tbl_btn_row = QHBoxLayout()
        copy_sel_btn = QPushButton('선택 키 복사')
        copy_sel_btn.setFixedWidth(110)
        copy_sel_btn.clicked.connect(self._copy_selected_key)
        export_btn = QPushButton('CSV 내보내기')
        export_btn.setFixedWidth(110)
        export_btn.clicked.connect(self._export_csv)
        del_btn = QPushButton('선택 삭제')
        del_btn.setFixedWidth(90)
        del_btn.setStyleSheet(f'color:{ACCENT2};border-color:{ACCENT2};')
        del_btn.clicked.connect(self._delete_selected)
        tbl_btn_row.addWidget(copy_sel_btn); tbl_btn_row.addWidget(export_btn)
        tbl_btn_row.addStretch(); tbl_btn_row.addWidget(del_btn)
        rec_lay.addLayout(tbl_btn_row)

        main.addWidget(rec_grp)

    # ── 이벤트 ───────────────────────────────────────────────────────────────
    def _on_input_changed(self):
        mid = self._mid_edit.text().strip()
        ok = len(mid) >= 8
        self._gen_btn.setEnabled(ok)
        if ok:
            self._mid_edit.setStyleSheet(
                f'background:{BG3};border:1px solid {ACCENT};border-radius:6px;'
                f'padding:6px 10px;color:{TEXT};font-size:13px;')
        else:
            self._mid_edit.setStyleSheet('')

    def _generate(self):
        mid = self._mid_edit.text().strip().upper()
        expiry = self._exp_spin.value()
        name = self._name_edit.text().strip() or '(이름 없음)'

        key = generate_key(mid, expiry)
        self._key_display.set_key(key)

        # 기록 저장
        record = {
            'issued_at': datetime.datetime.now().isoformat(timespec='seconds'),
            'name':      name,
            'machine_id': mid,
            'expiry_year': expiry,
            'key':        key
        }
        save_record(record)
        self._refresh_table()

        # 이름 초기화 (머신 ID는 유지)
        self._name_edit.clear()

    def _refresh_table(self):
        records = load_records()
        self._table.setRowCount(len(records))
        for r, rec in enumerate(reversed(records)):
            expiry_str = '영구' if rec.get('expiry_year', 0) == 0 else str(rec['expiry_year'])
            items = [
                rec.get('issued_at', '')[:10],
                rec.get('name', ''),
                rec.get('machine_id', ''),
                expiry_str,
                rec.get('key', ''),
            ]
            for c, val in enumerate(items):
                item = QTableWidgetItem(val)
                if c == 4:
                    item.setFont(QFont('Courier New', 10))
                    item.setForeground(QColor(ACCENT))
                self._table.setItem(r, c, item)

    def _copy_selected_key(self):
        row = self._table.currentRow()
        if row < 0:
            return
        key_item = self._table.item(row, 4)
        if key_item:
            QApplication.clipboard().setText(key_item.text())
            self.statusBar().showMessage('키가 클립보드에 복사됐습니다.', 2000)

    def _export_csv(self):
        path, _ = QFileDialog.getSaveFileName(
            self, 'CSV 저장', os.path.expanduser('~/Desktop/wsa2_licenses.csv'),
            'CSV Files (*.csv)')
        if not path:
            return
        records = load_records()
        with open(path, 'w', encoding='utf-8-sig') as f:
            f.write('발급일,고객 이름,머신 ID,만료 연도,시리얼 키\n')
            for rec in records:
                row = [
                    rec.get('issued_at','')[:10],
                    rec.get('name',''),
                    rec.get('machine_id',''),
                    str(rec.get('expiry_year', 0)),
                    rec.get('key',''),
                ]
                f.write(','.join(f'"{v}"' for v in row) + '\n')
        self.statusBar().showMessage(f'CSV 저장됨: {path}', 3000)

    def _delete_selected(self):
        row = self._table.currentRow()
        if row < 0:
            return
        key_item = self._table.item(row, 4)
        if not key_item:
            return
        target_key = key_item.text()
        reply = QMessageBox.question(
            self, '삭제 확인',
            f'이 키를 기록에서 삭제하시겠습니까?\n(키 자체는 여전히 작동합니다)\n\n{target_key[:40]}…',
            QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            records = [r for r in load_records() if r.get('key') != target_key]
            os.makedirs(os.path.dirname(_RECORDS_PATH), exist_ok=True)
            with open(_RECORDS_PATH, 'w', encoding='utf-8') as f:
                json.dump(records, f, ensure_ascii=False, indent=2)
            self._refresh_table()


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    app.setStyleSheet(SS_BASE)

    # 팔레트 설정
    pal = QPalette()
    pal.setColor(QPalette.Window,          QColor(BG))
    pal.setColor(QPalette.WindowText,      QColor(TEXT))
    pal.setColor(QPalette.Base,            QColor(BG3))
    pal.setColor(QPalette.AlternateBase,   QColor(BG2))
    pal.setColor(QPalette.Text,            QColor(TEXT))
    pal.setColor(QPalette.Button,          QColor(BG3))
    pal.setColor(QPalette.ButtonText,      QColor(TEXT))
    pal.setColor(QPalette.Highlight,       QColor(ACCENT))
    pal.setColor(QPalette.HighlightedText, QColor('#000000'))
    app.setPalette(pal)

    win = LicenseTool()
    win.show()
    sys.exit(app.exec())
