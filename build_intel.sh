#!/bin/bash
# WSA2 Intel Mac 빌드 스크립트
# Intel Mac (x86_64) 또는 Apple Silicon에서 arch -x86_64 모드로 실행
# 사용법: bash build_intel.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== WSA2 Intel Mac 빌드 ==="
ARCH=$(uname -m)
echo "현재 아키텍처: $ARCH"

# Apple Silicon에서 x86_64 모드로 재실행
if [ "$ARCH" = "arm64" ]; then
    echo "Apple Silicon 감지 → Rosetta2 (x86_64 모드)로 재실행..."
    exec arch -x86_64 /bin/bash "$0" "$@"
fi

# x86_64 Python 확인
PY=$(which python3)
if [ -z "$PY" ]; then
    echo "ERROR: python3를 찾을 수 없습니다."
    exit 1
fi

PY_ARCH=$(file "$PY" 2>/dev/null | grep -o "x86_64" || echo "")
echo "Python: $PY ($PY_ARCH)"

# 필요 패키지 설치
echo "패키지 설치 중..."
python3 -m pip install --user PyQt5 numpy scipy sounddevice soundfile pyinstaller --quiet

# spec 파일 생성 (Intel용)
SITE=$(python3 -c "import site; print(site.getusersitepackages())")
echo "site-packages: $SITE"

cat > WSA2_Intel.spec << SPEC
# -*- mode: python ; coding: utf-8 -*-
import os
SITE = '$SITE'
a = Analysis(
    ['wayaudo2.py'],
    pathex=[],
    binaries=[
        (os.path.join(SITE, '_sounddevice_data/portaudio-binaries/libportaudio.dylib'),
         '_sounddevice_data/portaudio-binaries'),
    ],
    datas=[
        ('splash.png', '.'),
        (os.path.join(SITE, 'soundfile.py'), '.'),
        (os.path.join(SITE, '_soundfile.py'), '.'),
    ],
    hiddenimports=[
        'soundfile', '_soundfile', 'cffi', '_cffi_backend',
        'scipy', 'scipy.io', 'scipy.io.wavfile', 'scipy.signal',
        'scipy.fft', 'scipy.fftpack',
        'PyQt5', 'PyQt5.QtCore', 'PyQt5.QtGui', 'PyQt5.QtWidgets',
        'PyQt5.sip', 'numpy', 'numpy.core', 'numpy.fft',
        'importlib.resources', 'importlib.metadata',
    ],
    hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'PIL', 'lxml', 'IPython'],
    noarchive=False, optimize=0,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [],
    exclude_binaries=True, name='WSA2',
    debug=False, strip=False, upx=True, console=False,
    argv_emulation=False, target_arch='x86_64',
    codesign_identity=None, entitlements_file='entitlements.plist',
)
coll = COLLECT(exe, a.binaries, a.zipfiles, a.datas,
    strip=False, upx=True, name='WSA2',
)
app = BUNDLE(coll,
    name='WSA2.app', icon='icon.icns',
    bundle_identifier='com.wayaudio.wsa2',
    info_plist={
        'NSMicrophoneUsageDescription': 'WSA2 uses the microphone for acoustic analysis.',
        'NSAudioInputUsageDescription': 'WSA2 uses audio input for acoustic measurement.',
        'NSHighResolutionCapable': True,
        'LSMinimumSystemVersion': '10.15',
        'CFBundleShortVersionString': '1.6',
        'CFBundleVersion': '1.6.0',
        'CFBundleName': 'WSA2',
        'CFBundleDisplayName': 'WAYAUDIO Spectrum Analyzer 2',
        'NSRequiresAquaSystemAppearance': False,
    },
)
SPEC

echo "PyInstaller 빌드 시작..."
python3 -m PyInstaller WSA2_Intel.spec --clean

# DMG 생성
echo "DMG 생성 중..."
mkdir -p /tmp/WSA2_intel_dmg
cp -R dist/WSA2.app /tmp/WSA2_intel_dmg/
ln -sf /Applications /tmp/WSA2_intel_dmg/Applications
hdiutil create -volname "WSA2 Installer (Intel)" \
    -srcfolder /tmp/WSA2_intel_dmg \
    -ov -format UDZO -fs HFS+ \
    dist/WSA2_Intel.dmg

echo ""
echo "=== 빌드 완료 ==="
echo "Intel DMG: dist/WSA2_Intel.dmg"
echo "앱 크기: $(du -sh dist/WSA2.app | cut -f1)"
