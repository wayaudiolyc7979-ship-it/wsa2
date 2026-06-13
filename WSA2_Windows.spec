# -*- mode: python ; coding: utf-8 -*-
# WSA2 Windows (x64) 빌드 spec — Windows에서 PyInstaller로 실행
import os

a = Analysis(
    ['wayaudo2.py'],
    pathex=[],
    binaries=[],
    datas=[('splash.png', '.')],
    hiddenimports=[
        'soundfile', '_soundfile', 'cffi', '_cffi_backend',
        'scipy', 'scipy.io', 'scipy.io.wavfile', 'scipy.signal',
        'scipy.fft', 'scipy.fftpack',
        'PyQt5', 'PyQt5.QtCore', 'PyQt5.QtGui', 'PyQt5.QtWidgets', 'PyQt5.QtSvg', 'PyQt5.sip',
        'numpy', 'numpy.core', 'numpy.fft',
        'collections', 'collections.abc',
        'importlib.resources', 'importlib.metadata',
    ],
    hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'PIL', 'lxml', 'IPython', 'jupyter'],
    noarchive=False, optimize=0,
)
pyz = PYZ(a.pure)

# onefile — 단일 WSA2.exe 로 배포 (PyQt5/numpy/scipy 자동 수집은 PyInstaller hook 사용)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name='WSA2',
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
    runtime_tmpdir=None, console=False,
    icon='icon.ico' if os.path.exists('icon.ico') else None,
    version_file=None,
)
