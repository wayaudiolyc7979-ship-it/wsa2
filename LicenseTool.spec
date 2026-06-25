# -*- mode: python ; coding: utf-8 -*-
import os

SITE = os.path.expanduser('~/Library/Python/3.9/lib/python/site-packages')

a = Analysis(
    ['wsa2_license_tool.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        'PyQt5', 'PyQt5.QtCore', 'PyQt5.QtGui', 'PyQt5.QtWidgets', 'PyQt5.sip',
        'json', 'hmac', 'hashlib', 'base64', 'datetime',
        'importlib.resources', 'importlib.metadata',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['numpy', 'scipy', 'sounddevice', 'soundfile', 'tkinter',
              'matplotlib', 'PIL', 'lxml'],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name='SPECTRA License Tool',
    debug=False, strip=False, upx=True,
    console=False, argv_emulation=False,
    target_arch='arm64',
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe, a.binaries, a.zipfiles, a.datas,
    strip=False, upx=True,
    name='SPECTRA License Tool',
)

app = BUNDLE(
    coll,
    name='SPECTRA License Tool.app',
    icon='icon.icns',
    bundle_identifier='com.wayaudio.spectra.licensetool',
    info_plist={
        'CFBundleShortVersionString': '1.0',
        'CFBundleVersion': '1.0.0',
        'CFBundleName': 'SPECTRA License Tool',
        'CFBundleDisplayName': 'SPECTRA 라이선스 키 생성기',
        'NSHighResolutionCapable': True,
        'LSMinimumSystemVersion': '12.0',
        'NSRequiresAquaSystemAppearance': False,
    },
)
