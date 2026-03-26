# -*- mode: python ; coding: utf-8 -*-
import os
import shutil

project_root = os.path.abspath('.')
resources_dir = os.path.join(project_root, 'app_resources')
icon_file = os.path.join(resources_dir, 'menubar_icon.icns')

binaries = []
for binary_name in ('ffmpeg', 'ffprobe'):
    binary_path = shutil.which(binary_name)
    if binary_path:
        binaries.append((binary_path, 'bin'))

datas = []
for filename in ('menubar_icon.icns', 'menubar_icon_source.png'):
    full = os.path.join(resources_dir, filename)
    if os.path.exists(full):
        datas.append((full, 'app_resources'))

block_cipher = None

a = Analysis(
    ['app.py'],
    pathex=[project_root],
    binaries=binaries,
    datas=datas,
    hiddenimports=['AppKit', 'Foundation', 'PyObjCTools', 'objc', 'certifi'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Fast Catch',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    argv_emulation=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name='Fast Catch',
)
app = BUNDLE(
    coll,
    name='Fast Catch.app',
    icon=icon_file if os.path.exists(icon_file) else None,
    bundle_identifier='com.fastcatch.macos',
    info_plist={
        'CFBundleName': 'Fast Catch',
        'CFBundleDisplayName': 'Fast Catch',
        'CFBundleShortVersionString': '0.1',
        'CFBundleVersion': '0.1',
        'NSHighResolutionCapable': True,
        'LSMinimumSystemVersion': '12.0',
    },
)
