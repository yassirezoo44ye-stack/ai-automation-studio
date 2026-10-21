# PyInstaller spec file for flow-agent.exe (Windows tray application)
# Build with: py -3.11 agent/build/build.py

block_cipher = None

a = Analysis(
    ['../../agent/__main__.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        'win32crypt',
        'pystray',
        'PIL._imaging',
        'websockets',
        'aiohttp',
        'agent.core.controller',
        'agent.windows.input',
        'agent.security.credentials',
        'winreg',
        'aiohttp.resolver',
        'aiohttp.connector',
    ],
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
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='flow-agent',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
