# CLAUDE.md

Zylch Desktop — Electron + React frontend that embeds the Python sidecar (`zylch`) over JSON-RPC on stdio. Runs on macOS (arm64 + x64) and Windows (x64). All user data lives under `~/.zylch/profiles/<email>/` — nothing syncs to a cloud.

## Sibling repos

- **`../zylch-standalone/`** — the Python CLI + sidecar (the engine). The desktop app calls this binary as a subprocess. Authoritative architecture: `docs/active-context.md`, `docs/ARCHITECTURE.md`. Repo: `malemi/zylch`.
- **`../zylch-website/`** — marketing site at https://zylchai.com. Download buttons there point at this repo's GitHub releases.

## Layout

```
src/
  main/        Electron main process (window, sidecar lifecycle, IPC)
  preload/     Context-bridge between main and renderer
  renderer/    React UI — views: chat, tasks, emails, settings, onboarding wizard
bin/           Prebuilt zylch sidecar binary (downloaded by CI from malemi/zylch releases)
out/           electron-vite build output
dist/          electron-builder installer output (DMG / EXE)
scripts/       Test helpers (e.g. test-onboarding.mjs)
```

## Local dev

```bash
npm ci
# Dev needs a zylch sidecar somewhere. Default expectation:
#   ~/private/zylch-standalone/venv/bin/zylch
# Override with ZYLCH_BINARY=/path/to/zylch.
npm run dev
```

For a packaged build:

```bash
mkdir -p bin
gh release download --repo malemi/zylch --pattern zylch-macos-arm64 \
  --output bin/zylch && chmod +x bin/zylch
npm run dist:mac      # → dist/*.dmg
npm run dist:win      # → dist/*.exe (on Windows, or via Wine elsewhere)
```

## Distribution

`.github/workflows/release.yml` fires on tag push (`v*`) or manual dispatch. It pulls the matching sidecar binary from `malemi/zylch` releases, runs electron-builder, and attaches the installers to a GitHub Release on `malemi/zylch-desktop`.

| Platform | Asset |
|----------|-------|
| macOS Apple Silicon | `Zylch-<ver>-arm64.dmg` |
| macOS Intel (x64) | `Zylch-<ver>.dmg` |
| Windows x64 | `Zylch-Setup-<ver>.exe` |

**Installers are not code-signed.** macOS Gatekeeper and Windows SmartScreen will warn on first launch — `README.md` documents the bypass for testers, and the website's `download.html` repeats the same steps.

## Architecture notes

- **Sidecar-first.** The renderer never imports zylch logic — it sends JSON-RPC requests through preload → main → sidecar stdio. If you need a new feature, add an RPC method on the Python side first, then expose it through preload.
- **Profile-aware.** Each Electron window owns one profile (one email). The sidecar acquires an fcntl lock on the profile dir; if you see "profile already in use", another window or CLI invocation has it open.
- **No telemetry.** No analytics SDK, no error reporter. If you find yourself reaching for one, talk to the user first.

## Memory discipline

Claude Code keeps a per-user, per-machine memory at `~/.claude/projects/<encoded-path>/memory/`. **It is not in git, not shared with the team, not portable.** This `CLAUDE.md` and any future `docs/` here are the source of truth.

- **Project knowledge → this file (or a `docs/` doc, if it grows).** Build pipeline, IPC shape, packaging quirks: check them in.
- **Engine facts → `../zylch-standalone/docs/`.** Don't restate them here; link.
- **Personal notes → CC memory.** Your own preferences, working-style feedback. That's fine.
- **Before quoting CC memory**, verify against the current state of the repo. Memory can be stale; the repo cannot.
