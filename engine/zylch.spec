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
    # Collect neonize WITHOUT importing it. `collect_data_files` and
    # `collect_dynamic_libs` both run the package through PyInstaller's
    # isolated subprocess (`import_library`), and importing neonize's
    # compiled Go binding there is what kills the Windows build. Three
    # separate runs died at exactly `import_library('neonize.utils')`
    # with three different crash codes — 0xC0000005, 0xC0000409, and a
    # Cygwin TP_NUM_C_BUFS abort — which is what an unstable native load
    # looks like, not a packaging mistake. e251c4d removed
    # `collect_submodules` but left these two, so the import stayed.
    #
    # `find_spec` locates the package from the filesystem without
    # executing it, and the files are then globbed directly. The bundled
    # set is the same one the helpers would have produced.
    import importlib.util as _ilu

    _spec = _ilu.find_spec('neonize')
    if _spec is None or not _spec.submodule_search_locations:
        raise SystemExit('zylch.spec: neonize not found; cannot build the sidecar')
    _neo = _spec.submodule_search_locations[0]
    for _root, _dirs, _files in os.walk(_neo):
        _rel = os.path.relpath(_root, os.path.dirname(_neo))
        for _f in _files:
            _src = os.path.join(_root, _f)
            if _f.endswith(('.dll', '.pyd')):
                binaries.append((_src, _rel))
            elif not _f.endswith(('.pyc',)):
                datas.append((_src, _rel))
    # NOT hiddenimports: naming them would put neonize back in the module
    # graph, and `get_collected_packages()` feeds every Package node to the
    # isolated importer above. The files shipped by the walk land next to the
    # executable, where PyInstaller puts sys._MEIPASS on sys.path, so
    # `import neonize` resolves at run time from those files.
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
#
# NOT ON WINDOWS. ctranslate2's Windows wheel bundles the Intel oneAPI/MKL
# runtime — a very large, densely cross-linked set of DLLs. PyInstaller's
# `Looking for dynamic libraries` phase walks every collected binary with
# pefile to resolve its imports, and on that DLL set the walk does not
# finish inside any CI budget we are willing to pay: the v0.1.51-win run
# sat silent in that phase for 41 minutes until the job backstop killed it,
# and the interrupt was reported by `forrtl`, the Intel Fortran runtime.
# Dropping these three removes the MKL mountain from the scan.
#
# What Windows loses: WhatsApp voice notes are not transcribed. Nothing
# else — `zylch/whatsapp/transcription.py` imports faster_whisper lazily
# inside `_get_model()` and its caller already treats ImportError as
# "skip transcription" (line 102), so the feature degrades instead of
# breaking. `av` has no direct importer in zylch; it comes in only as
# faster_whisper's audio decoder, so it leaves with it.
#
# fastembed and onnxruntime above deliberately STAY on Windows: they are
# the semantic memory (`zylch/memory/embeddings.py`), not an optional
# feature, and onnxruntime ships its own small BLAS rather than MKL.
if sys.platform != 'win32':
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
    # Windows only. `find_binary_dependencies` imports EVERY collected package
    # into ONE isolated child process, in sequence, to harvest the DLL
    # directories each registers. By the time that child reaches neonize it is
    # already carrying numpy, onnxruntime, cryptography, lxml and tokenizers,
    # and loading the Go runtime on top of that is what kills it — the three
    # observed signatures (0xC0000005, 0xC0000409, Cygwin TP_NUM_C_BUFS) are
    # resource exhaustion in that child, not a defect in neonize. So: shrink
    # what the child has to carry, and keep neonize out of the list entirely.
    #
    # faster_whisper/ctranslate2/av are droppable on Windows — they serve only
    # WhatsApp voice-note transcription, imported lazily, and the caller
    # already treats ImportError as "skip transcription".
    excludes=(['faster_whisper', 'ctranslate2', 'av', 'neonize'] if sys.platform == 'win32' else []),
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
