# -*- mode: python ; coding: utf-8 -*-
import os
import sys
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_dynamic_libs

datas = []
binaries = []
hiddenimports = ['zylch.cli.main']
tmp_ret = collect_all('zylch')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('fastembed')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

# ─── neonize (WhatsApp / whatsmeow bindings) — Windows needs a special path ──
# `collect_all('neonize')` calls collect_submodules(), which IMPORTS every
# submodule it finds inside an isolated PyInstaller subprocess to enumerate
# them. Importing anything under `neonize` (even just `import neonize`)
# transitively runs `neonize/_binder.py`, which loads the package's compiled
# Go shared library via `ctypes.CDLL(...)` and immediately calls into it
# (`gocode.GetVersion()`). On windows-latest that ctypes call inside the
# isolated subprocess dies with an access violation (exit 3221225477 =
# 0xC0000005), which kills PyInstaller's build — see the `continue-on-error`
# comment on the `build-engine` job in .github/workflows/release.yml.
#
# Fix, Windows-only: skip collect_submodules() entirely. Pull datas/binaries
# with the same two helper calls collect_all() itself would use internally
# (so the actual bundled files are unchanged), and hand-write hiddenimports
# from the neonize modules our own code imports (`grep -rn "from neonize" zylch/`
# turned up only neonize.client, neonize.events, neonize.utils — no dynamic
# imports anywhere in neonize itself, so PyInstaller's normal static bytecode
# scan of client.py/events.py's own imports already reaches every proto/utils
# submodule those need; nothing here is walked/imported by PyInstaller, so
# nothing can crash the isolated subprocess).
#
# macOS/Linux are untouched — they still take the original collect_all()
# path PyInstaller has always used there, so this is a no-op on darwin.
if sys.platform == 'win32':
    datas += collect_data_files('neonize', include_py_files=True)
    binaries += collect_dynamic_libs('neonize')
    hiddenimports += ['neonize.client', 'neonize.events', 'neonize.utils']
else:
    tmp_ret = collect_all('neonize')
    datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

tmp_ret = collect_all('onnxruntime')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

# ─── faster-whisper voice-note transcription ─────────────────────────
# On-device speech-to-text for WhatsApp voice notes. PyInstaller does NOT
# auto-collect these native shared libs reliably, so collect_all each:
#   - faster_whisper: pure-Python, but its datas include the bundled
#     Silero VAD asset (assets/silero_vad_v6.onnx), run through the
#     onnxruntime collected above.
#   - ctranslate2: the inference runtime — ships libctranslate2 (.dylib /
#     .so / .dll) as a native binary.
#   - av (PyAV): bundles ffmpeg shared libs (libavcodec/libavformat/
#     libswresample/...) used to decode ogg/opus voice notes.
# The whisper MODEL (~250MB) is NOT bundled — it downloads to the HF cache
# at first transcription. Only code + native libs ship in the installer.
tmp_ret = collect_all('faster_whisper')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('ctranslate2')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('av')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


# ─── libmagic bundling ───────────────────────────────────────────────
# python-magic (transitively imported by neonize) loads libmagic via
# ctypes. Without bundling, end-users would need to `brew install
# libmagic` themselves — unacceptable for a DMG install. Find the
# system libmagic at build time and ship the dylib + the magic.mgc
# database alongside the executable. The runtime hook below points
# $MAGIC at the bundled magic.mgc so libmagic doesn't try the
# Homebrew path that doesn't exist on the user's machine.

def _find_first(*paths):
    for p in paths:
        if p and os.path.exists(p):
            return p
    return None


if sys.platform == 'darwin':
    # Homebrew Apple Silicon (default in CI on macOS-14 runners) +
    # Intel + manual installs. Stop at the first match.
    libmagic = _find_first(
        '/opt/homebrew/lib/libmagic.dylib',
        '/usr/local/lib/libmagic.dylib',
        '/opt/local/lib/libmagic.dylib',  # MacPorts, just in case
    )
    if libmagic is None:
        raise SystemExit(
            'libmagic.dylib not found. CI: ensure `brew install libmagic` '
            'ran before pyinstaller. Local: brew install libmagic.'
        )
    binaries.append((libmagic, '.'))
    # Compiled magic database — required for libmagic to identify any
    # files. Also follow the dylib that's loaded so we pick the matching
    # `share/misc/magic.mgc` from the same brew prefix.
    prefix = os.path.dirname(os.path.dirname(libmagic))
    mgc = _find_first(
        os.path.join(prefix, 'share', 'misc', 'magic.mgc'),
        '/opt/homebrew/share/misc/magic.mgc',
        '/usr/local/share/misc/magic.mgc',
        '/opt/local/share/misc/magic.mgc',
    )
    if mgc:
        # Land in <bundle>/share/misc/magic.mgc — runtime hook reads it.
        datas.append((mgc, os.path.join('share', 'misc')))

elif sys.platform.startswith('linux'):
    libmagic = _find_first(
        '/usr/lib/x86_64-linux-gnu/libmagic.so.1',
        '/usr/lib/aarch64-linux-gnu/libmagic.so.1',
        '/usr/lib64/libmagic.so.1',
        '/usr/lib/libmagic.so.1',
    )
    if libmagic is not None:
        binaries.append((libmagic, '.'))
    # On Linux libmagic typically picks up /usr/share/misc/magic.mgc at
    # runtime via its compile-time path; bundle it anyway for portability.
    mgc = _find_first(
        '/usr/share/misc/magic.mgc',
        '/usr/share/file/magic.mgc',
    )
    if mgc:
        datas.append((mgc, os.path.join('share', 'misc')))

# Windows: python-magic-bin (declared in pyproject.toml under sys_platform
# == 'win32') ships its own libmagic. PyInstaller's collect_all on neonize
# already picks it up.


a = Analysis(
    ['zylch/cli/main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    # Runs before any user code: sets $MAGIC to point at the bundled
    # magic.mgc so libmagic doesn't try a build-time path that doesn't
    # exist on the user's machine.
    runtime_hooks=['pyinstaller_runtime_hook.py'],
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
    name='zylch',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
