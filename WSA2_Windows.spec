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
# [WIN_MSVCP] PyQt5 휠은 구버전 MSVC 런타임(msvcp140.dll 14.26)을 Qt5\bin 에 싣고 오고, 번들에서는 이 DLL 이
#   프로세스에 먼저 올라간다. 최신 MSVC 로 빌드된 ASIO 드라이버(예: Focusrite USB ASIO)가 그 구버전에 묶이면
#   드라이버 초기화 중 MSVCP140.dll 접근 위반(0xc0000005)으로 앱이 창도 로그도 없이 죽는다(인터페이스 연결 시).
#   → 번들의 MSVC 런타임을 빌드 머신 System32 의 최신본으로 교체하고 _internal 루트에도 둔다(런타임은 하위 호환).
_MSVC_RT = ('msvcp140.dll', 'msvcp140_1.dll', 'msvcp140_2.dll', 'vcruntime140.dll', 'vcruntime140_1.dll')
_MSVC_MIN = (14, 40)   # std::mutex 레이아웃이 바뀐 버전 — 이보다 낮으면 최신 드라이버와 충돌

def _dll_version(path):
    import pefile
    pe = pefile.PE(path, fast_load=True)
    pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_RESOURCE']])
    ffi = pe.VS_FIXEDFILEINFO[0]
    pe.close()
    return (ffi.FileVersionMS >> 16, ffi.FileVersionMS & 0xFFFF, ffi.FileVersionLS >> 16, ffi.FileVersionLS & 0xFFFF)

def _fresh_msvc_runtime(binaries):
    sysdir = os.path.join(os.environ.get('SystemRoot', r'C:\Windows'), 'System32')
    fresh = {n: os.path.join(sysdir, n) for n in _MSVC_RT if os.path.exists(os.path.join(sysdir, n))}
    if 'msvcp140.dll' not in fresh or _dll_version(fresh['msvcp140.dll'])[:2] < _MSVC_MIN:
        raise SystemExit('[WIN_MSVCP] 빌드 머신의 System32\\msvcp140.dll 이 없거나 %d.%d 미만 — '
                         '최신 VC++ 재배포 패키지를 설치한 뒤 다시 빌드하세요.' % _MSVC_MIN)
    out, at_root = [], set()
    for dest, src, typ in binaries:
        base = os.path.basename(dest).lower()
        if base in fresh and _dll_version(fresh[base]) > _dll_version(src):
            src = fresh[base]
        if base in fresh and os.path.dirname(dest) == '':
            at_root.add(base)
        out.append((dest, src, typ))
    out += [(n, p, 'BINARY') for n, p in fresh.items() if n not in at_root]
    return out

a.binaries = _fresh_msvc_runtime(a.binaries)

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
