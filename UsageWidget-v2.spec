# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_all

try:
    import tkinter  # noqa: F401
except ImportError as error:
    raise SystemExit(
        "tkinter is required to build Usage Widget v2 (Display options / Details UI)."
    ) from error

datas = [('config.example.yaml', '.')]
binaries = []
hiddenimports = []
collected_tk = False

for pkg in ("tkinter", "_tkinter"):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
        if d or b or h:
            collected_tk = True
    except Exception as error:
        print(f"WARNING: collect_all({pkg!r}) failed: {error}")

if not collected_tk:
    print(
        "WARNING: collect_all(tkinter) returned no extras; "
        "relying on PyInstaller Tcl/Tk hooks (hook-_tkinter)."
    )

a = Analysis(
    ['widget.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='UsageWidget-v2',
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
    version='version_info.txt',
    icon=['icon.ico'],
)
