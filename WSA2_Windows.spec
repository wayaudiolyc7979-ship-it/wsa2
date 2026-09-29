# -*- mode: python ; coding: utf-8 -*-
# WSA2 Windows (x64) 빌드 spec — Windows에서 PyInstaller로 실행
import os
from PyInstaller.utils.hooks import collect_data_files

a = Analysis(
    ['wayaudo2.py'],
    pathex=[],
    binaries=[],
    # _sounddevice_data: ASIO 포함 PortAudio DLL(libportaudio64bit-asio.dll)을 확실히 번들 [WIN_ASIO]
    datas=[('splash.png', '.'), ('MANUAL.html', '.'), ('RELEASE_NOTES.md', '.'), ('docs/img', 'docs/img')]
          + collect_data_files('_sounddevice_data'),
    hiddenimports=[
        'soundfile', '_soundfile', 'cffi', '_cffi_backend',
        'scipy', 'scipy.io', 'scipy.io.wavfile', 'scipy.signal',
        'scipy.fft', 'scipy.fftpack',
        'PyQt5', 'PyQt5.QtCore', 'PyQt5.QtGui', 'PyQt5.QtWidgets', 'PyQt5.QtSvg', 'PyQt5.sip',
        'ed25519_min',
        'numpy', 'numpy.core', 'numpy.fft',
        'collections', 'collections.abc',
        'importlib.resources', 'importlib.metadata',
    ],
    hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'PIL', 'lxml', 'IPython', 'jupyter'],
    noarchive=False, optimize=0,
)
pyz = PYZ(a.pure)

# onedir — dist/SPECTRA/ 폴더(SPECTRA.exe + _internal\)로 배포.
#   installer/SPECTRA.iss(Inno Setup)가 이 폴더를 Program Files 에 설치한다.
#   onefile(실행 시 %TEMP% 압축해제)에서 onedir로 바꿔 즉시 실행·백신/OneDrive 안정성 확보. [WIN_ONEDIR]
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,                # 바이너리/데이터는 COLLECT 로 폴더에 배치
    name='SPECTRA',                       # 사용자에게 보이는 exe명 (브랜딩). 내부 식별자 WSA2와 무관
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
    # 평소 창 모드(console=False). WSA2_BUILD_CONSOLE=1 이면 콘솔 디버그 빌드 —
    #   터미널에서 실행 시 시작 초기 import/DLL 오류를 화면에 출력(로그 생성 전 크래시 진단용). [WIN_DEBUG]
    console=(os.environ.get('WSA2_BUILD_CONSOLE') == '1'),
    icon='icon.ico' if os.path.exists('icon.ico') else None,
    version_file='version_info.txt' if os.path.exists('version_info.txt') else None,
)
coll = COLLECT(
    exe, a.binaries, a.datas,
    strip=False, upx=False, upx_exclude=[],
    name='SPECTRA',                       # → dist/SPECTRA/
)
