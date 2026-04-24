# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ['wayaudo2.py'],
    pathex=[],
    binaries=[],
    datas=[('splash.png', '.')],
    hiddenimports=['importlib.resources', 'importlib.metadata', 'pkg_resources.py2_warn'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['scipy'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='WSA2',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='WSA2',
)

app = BUNDLE(
    coll,
    name='WSA2.app',
    icon='icon.icns',
    bundle_identifier='com.wayaudio.wsa2',
    info_plist={
        'NSMicrophoneUsageDescription': 'WSA2 needs microphone access for spectrum analysis.',
        'NSHighResolutionCapable': True,
        'CFBundleShortVersionString': '2.0',
        'CFBundleName': 'WSA2',
        'CFBundleDisplayName': 'WAYAUDIO Spectrum Analyzer 2',
    },
)
