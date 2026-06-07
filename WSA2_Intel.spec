# -*- mode: python ; coding: utf-8 -*-
import os

SITE = '/private/tmp/intel_venv/lib/python3.9/site-packages'

a = Analysis(
    ['wayaudo2.py'],
    pathex=[],
    binaries=[
        (os.path.join(SITE, '_sounddevice_data/portaudio-binaries/libportaudio.dylib'),
         '_sounddevice_data/portaudio-binaries'),
        (os.path.join(SITE, '_soundfile_data/libsndfile_x86_64.dylib'),
         '_soundfile_data'),
    ],
    datas=[
        ('splash.png', '.'),
        (os.path.join(SITE, 'soundfile.py'), '.'),
        (os.path.join(SITE, '_soundfile.py'), '.'),
        (os.path.join(SITE, '_soundfile_data'), '_soundfile_data'),
    ],
    hiddenimports=[
        'soundfile', '_soundfile', 'cffi', '_cffi_backend',
        'scipy', 'scipy.io', 'scipy.io.wavfile', 'scipy.signal',
        'scipy.fft', 'scipy.fftpack',
        'PyQt5', 'PyQt5.QtCore', 'PyQt5.QtGui', 'PyQt5.QtWidgets', 'PyQt5.sip',
        'numpy', 'numpy.core', 'numpy.fft',
        'collections', 'collections.abc',
        'importlib.resources', 'importlib.metadata',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'PIL', 'lxml', 'IPython', 'jupyter'],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name='WSA2',
    debug=False, strip=False, upx=True,
    upx_exclude=['libportaudio.dylib', 'libsndfile_x86_64.dylib'],
    console=False, argv_emulation=False,
    target_arch='x86_64',
    codesign_identity=None,
    entitlements_file='entitlements.plist',
)

coll = COLLECT(
    exe, a.binaries, a.zipfiles, a.datas,
    strip=False, upx=True,
    upx_exclude=['libportaudio.dylib', 'libsndfile_x86_64.dylib'],
    name='WSA2_Intel',
)

app = BUNDLE(
    coll,
    name='WSA2_Intel.app',
    icon='icon.icns',
    bundle_identifier='com.wayaudio.wsa2',
    info_plist={
        'NSMicrophoneUsageDescription':
            'WSA2 uses the microphone for real-time spectrum and impulse response analysis.',
        'NSAudioInputUsageDescription':
            'WSA2 uses audio input for acoustic measurement.',
        'NSHighResolutionCapable': True,
        'LSMinimumSystemVersion': '10.15',
        'CFBundleShortVersionString': '2.1',
        'CFBundleVersion': '2.1.0',
        'CFBundleName': 'WSA2',
        'CFBundleDisplayName': 'WAYAUDIO Spectrum Analyzer 2',
        'CFBundleExecutable': 'WSA2',
        'NSRequiresAquaSystemAppearance': False,
        'NSSupportsAutomaticGraphicsSwitching': True,
    },
)
