# -*- mode: python ; coding: utf-8 -*-
import os

SITE = os.path.expanduser('~/Library/Python/3.9/lib/python/site-packages')

a = Analysis(
    ['wayaudo2.py'],
    pathex=[],
    binaries=[
        # PortAudio (universal2) — sounddevice 런타임
        (os.path.join(SITE, '_sounddevice_data/portaudio-binaries/libportaudio.dylib'),
         '_sounddevice_data/portaudio-binaries'),
        # libsndfile (arm64) — soundfile 런타임
        (os.path.join(SITE, '_soundfile_data/libsndfile_arm64.dylib'),
         '_soundfile_data'),
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
        'PyQt5', 'PyQt5.QtCore', 'PyQt5.QtGui', 'PyQt5.QtWidgets', 'PyQt5.QtSvg',
        'PyQt5.sip',
        'ed25519_min',
        'numpy', 'numpy.core', 'numpy.fft',
        'collections', 'collections.abc',
        'importlib.resources', 'importlib.metadata',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'PIL', 'lxml', 'IPython', 'jupyter',
              'pkg_resources', 'setuptools', 'pip'],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='SPECTRA',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=['libportaudio.dylib', 'libsndfile_arm64.dylib'],
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch='arm64',
    codesign_identity=None,
    entitlements_file='entitlements.plist',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=['libportaudio.dylib', 'libsndfile_arm64.dylib'],
    name='SPECTRA',
)

app = BUNDLE(
    coll,
    name='SPECTRA.app',
    icon='icon.icns',
    bundle_identifier='com.wayaudio.wsa2',
    info_plist={
        'NSMicrophoneUsageDescription':
            'SPECTRA uses the microphone for real-time spectrum and impulse response analysis.',
        'NSAudioInputUsageDescription':
            'SPECTRA uses audio input for acoustic measurement.',
        'NSHighResolutionCapable': True,
        'LSMinimumSystemVersion': '12.0',
        'CFBundleShortVersionString': '1.7',
        'CFBundleVersion': '1.7.0',
        'CFBundleName': 'SPECTRA',
        'CFBundleDisplayName': 'SPECTRA',
        'CFBundleExecutable': 'SPECTRA',
        'NSRequiresAquaSystemAppearance': False,
        'NSSupportsAutomaticGraphicsSwitching': True,
    },
)
