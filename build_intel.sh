#!/bin/bash
# WSA2 Intel Mac (x86_64) 빌드 — 전용 x86_64 venv 사용 (arm64 의존성 오염 방지)
# Apple Silicon에서 Rosetta2(x86_64)로 자동 재실행. 사용법: bash build_intel.sh
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"; cd "$SCRIPT_DIR"

ARCH=$(uname -m)
echo "=== WSA2 Intel(x86_64) 빌드 ===  현재: $ARCH"
if [ "$ARCH" = "arm64" ]; then
    echo "Apple Silicon 감지 → Rosetta2(x86_64)로 재실행..."
    exec arch -x86_64 /bin/bash "$0" "$@"
fi

# 여기부터 x86_64 모드 (Rosetta)
# PyInstaller가 부르는 lipo/xcrun 등은 CLT에 x86_64 슬라이스가 없어 Rosetta에서 실패한다.
# → arm64 강제 래퍼를 만들어 PATH 앞에 둔다 (재부팅으로 /tmp 날아가도 매 빌드 자동 재생성).
ARM64_TOOLS="/tmp/arm64_tools"
mkdir -p "$ARM64_TOOLS"
for t in lipo codesign strip install_name_tool otool xcrun; do
    printf '#!/bin/bash\nexec arch -arm64 /usr/bin/%s "$@"\n' "$t" > "$ARM64_TOOLS/$t"
    chmod +x "$ARM64_TOOLS/$t"
done
export PATH="$ARM64_TOOLS:$PATH"

VENV="/tmp/spectra_intel_venv"
PY="arch -x86_64 $VENV/bin/python"
if [ ! -d "$VENV" ]; then
    echo "x86_64 전용 venv 생성: $VENV"
    arch -x86_64 python3 -m venv "$VENV"
fi
echo "x86_64 의존성 설치/확인 중... (최초엔 수 분 소요)"
$PY -m pip install --upgrade pip --quiet
# ⚠️ 구형 macOS 호환(Ventura 13 이하): numpy>=2.3 / scipy>=1.14 의 x86_64 휠은 minos=14.0(Sonoma)라
#    dyld가 로드 거부 → 앱이 "열렸다 즉시 종료". numpy 2.2.6 은 10_9·14_0 두 휠이 있어 macOS 26 에선
#    pip 가 14_0 을 골라버림 → 반드시 macosx_10_9 휠을 명시 다운로드해 강제 설치한다.
#    (scipy 1.13.1 은 10_9 휠만 존재.) 버전 변경 시 빌드 후 `vtool -show-build` 로 minos<=13 재검증 필수.
LOWDIR=/tmp/spectra_low_wheels
rm -rf "$LOWDIR"; mkdir -p "$LOWDIR"
$PY -m pip download --no-deps --only-binary=:all: \
    --platform macosx_10_9_x86_64 --python-version 311 --abi cp311 \
    -d "$LOWDIR" "numpy==2.2.6" "scipy==1.13.1"
$PY -m pip install --force-reinstall --no-deps "$LOWDIR"/*.whl
$PY -m pip install PyQt5 sounddevice soundfile pyinstaller --quiet

SITE=$($PY -c "import site; print(site.getsitepackages()[0])")
echo "site-packages: $SITE"
NPSO=$(ls "$SITE"/numpy/_core/_multiarray_umath.cpython-*.so 2>/dev/null | head -1)
echo "numpy .so arch: $(file "$NPSO" 2>/dev/null | grep -oE 'x86_64|arm64' | head -1)"

# libsndfile / portaudio dylib 자동 탐지 (x86_64)
SND_DYLIB=$(ls "$SITE"/_soundfile_data/libsndfile*.dylib 2>/dev/null | head -1)
PA_DYLIB=$(ls "$SITE"/_sounddevice_data/portaudio-binaries/libportaudio*.dylib 2>/dev/null | head -1)
echo "libsndfile: $SND_DYLIB"
echo "portaudio:  $PA_DYLIB"

cat > WSA2_Intel.spec << SPEC
# -*- mode: python ; coding: utf-8 -*-
import os
SITE = r'$SITE'
a = Analysis(
    ['wayaudo2.py'],
    pathex=[],
    binaries=[
        (r'$PA_DYLIB', '_sounddevice_data/portaudio-binaries'),
        (r'$SND_DYLIB', '_soundfile_data'),
    ],
    datas=[
        ('splash.png', '.'),
        ('MANUAL.html', '.'),
        ('RELEASE_NOTES.md', '.'),
        ('docs/img', 'docs/img'),
        (os.path.join(SITE, 'soundfile.py'), '.'),
        (os.path.join(SITE, '_soundfile.py'), '.'),
        (os.path.join(SITE, '_soundfile_data'), '_soundfile_data'),
    ],
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
exe = EXE(pyz, a.scripts, [],
    exclude_binaries=True, name='SPECTRA',
    debug=False, strip=False, upx=False, console=False,
    argv_emulation=False, target_arch='x86_64',
    codesign_identity=None, entitlements_file='entitlements.plist',
)
coll = COLLECT(exe, a.binaries, a.zipfiles, a.datas,
    strip=False, upx=False, name='SPECTRA_Intel',
)
app = BUNDLE(coll,
    name='SPECTRA.app', icon='icon.icns',
    bundle_identifier='com.wayaudio.wsa2',
    info_plist={
        'NSMicrophoneUsageDescription': 'SPECTRA uses the microphone for acoustic analysis.',
        'NSAudioInputUsageDescription': 'SPECTRA uses audio input for acoustic measurement.',
        'NSHighResolutionCapable': True,
        'LSMinimumSystemVersion': '10.15',
        'CFBundleShortVersionString': '2.0.2',
        'CFBundleVersion': '2.0.2',
        'CFBundleName': 'SPECTRA',
        'CFBundleDisplayName': 'SPECTRA',
        'CFBundleExecutable': 'SPECTRA',
        'NSRequiresAquaSystemAppearance': False,
    },
)
SPEC

echo "PyInstaller(x86_64) 빌드 시작..."
$PY -m PyInstaller WSA2_Intel.spec --clean --noconfirm

# 코드서명 (SPECTRA_SIGN_ID 설정 시)
bash sign_app.sh dist/SPECTRA.app

echo "브랜드 DMG 생성 중..."
bash make_dmg.sh dist/SPECTRA.app "SPECTRA Installer (Intel)" dist/SPECTRA_Intel.dmg

# 노타라이즈 + staple (자격 설정 시)
bash notarize_dmg.sh dist/SPECTRA_Intel.dmg
# ── fallback (브랜드 실패 시 plain): ──
# rm -rf /tmp/WSA2_intel_dmg && mkdir -p /tmp/WSA2_intel_dmg
# cp -R dist/SPECTRA.app /tmp/WSA2_intel_dmg/; ln -sf /Applications /tmp/WSA2_intel_dmg/Applications
# hdiutil create -volname "SPECTRA Installer (Intel)" -srcfolder /tmp/WSA2_intel_dmg -ov -format UDZO -fs HFS+ dist/SPECTRA_Intel.dmg

echo ""
echo "=== Intel 빌드 완료 ==="
echo "Intel DMG: dist/SPECTRA_Intel.dmg"
echo "앱 크기: $(du -sh dist/SPECTRA.app | cut -f1)"
