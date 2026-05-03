# CLAUDE.md

MrCall Desktop — Electron + React frontend that embeds the Python sidecar (`zylch`) over JSON-RPC on stdio. Runs on macOS arm64 (Apple Silicon) and Windows x64; macOS Intel x64 is opt-in (paid runner). All user data lives under `~/.zylch/profiles/<email>/` — nothing syncs to a cloud.

## Sibling code in this monorepo

- **`../engine/`** — the Python CLI + sidecar that this app embeds. Built into `bin/` by the release workflow. Internal package name and CLI binary are still `zylch` (legacy); user-visible branding is "MrCall Desktop".
- Wider context: `~/hb/mrcall-desktop/CLAUDE.md` and the `~/hb/` meta-repo for sibling services (`mrcall-agent`, `starchat`, `mrcall-dashboard`, `mrcall-website`).

## Layout

```
src/
  main/        Electron main process (window, sidecar lifecycle, IPC)
  preload/     Context-bridge between main and renderer
  renderer/    React UI — views: chat, tasks, emails, settings, onboarding wizard
bin/           Prebuilt zylch sidecar binary (built by the release workflow from ../engine/)
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

For a packaged build (Mac):

```bash
# Build the sidecar from the engine subdir, then bundle it into bin/.
cd ../engine && pip install -e . pyinstaller && pyinstaller --noconfirm zylch.spec
cp dist/zylch ../app/bin/zylch && chmod +x ../app/bin/zylch
cd ../app
npm run dist:mac      # → dist/*.dmg
```

Windows requires running on Windows (or `windows-latest` in CI); cross-build via Wine is fragile.

## Distribution

`.github/workflows/release.yml` (in the repo root, not `app/`) drives every install:

- **Tag push `v*`** → builds macOS arm64 + Windows x64. Installers attached to a GitHub Release.
- **Tag push `v*-intel`** (e.g. `v0.1.25-intel`) → also builds macOS Intel x64 on `macos-13-large` (paid larger runner; "Larger runners" must be enabled in repo settings).
- **`workflow_dispatch`** with input `include_intel: true|false` → manual build with the same toggle, artifacts only (no Release attached).

The workflow builds the sidecar in `engine/` via PyInstaller in the same run and downloads it into `app/bin/` before electron-builder runs. No external sidecar repo to fetch from anymore.

| Platform | Asset (controlled by `build.artifactName` in `package.json`) |
|----------|-------|
| macOS Apple Silicon | `MrCall Desktop-<ver>-arm64.dmg` |
| macOS Intel (x64) — opt-in | `MrCall Desktop-<ver>-x64.dmg` |
| Windows x64 | `MrCall Desktop-Setup-<ver>-x64.exe` (NSIS) |

**Installers are not code-signed.** macOS Gatekeeper and Windows SmartScreen will warn on first launch — `README.md` documents the bypass for testers, and the marketing site (`mrcall-website`) needs the same instructions in its download page.

## Architecture notes

- **Sidecar-first.** The renderer never imports zylch logic — it sends JSON-RPC requests through preload → main → sidecar stdio. If you need a new feature, add an RPC method on the Python side first, then expose it through preload.
- **Profile-aware.** Each Electron window owns one profile (one email). The sidecar acquires an fcntl lock on the profile dir; if you see "profile already in use", another window or CLI invocation has it open.
- **No telemetry.** No analytics SDK, no error reporter. If you find yourself reaching for one, talk to the user first.

## Settings — LLM billing mode (since 2026-05)

`views/Settings.tsx` carries an `LLMProviderCard` at the top of the LLM
group: a radio toggle between **BYOK** (`anthropic` / `openai`) and **Use
MrCall credits** (`mrcall`). Picking MrCall credits requires a live
Firebase signin; the card is disabled with an explanatory hint
otherwise.

When MrCall credits is selected, the card calls `window.zylch.account.balance()`
on mount and on every `window` focus event (so a top-up done in another
tab updates the displayed balance once the user comes back). The
underlying RPC binding lives at `app/src/preload/index.ts` with a 15 s
timeout; it returns the proxy's payload verbatim
(`balance_credits`, `balance_micro_usd`, `balance_usd`,
`granularity_micro_usd?`, `estimate_messages_remaining?`) or
`{error: 'auth_expired'}` on a 401 (renderer should refresh + retry).

The "Top up" button uses `shell.openExternal('https://dashboard.mrcall.ai/plan')` —
no business_id in the URL; the dashboard resolves the active business
from the user's Firebase auth state. The Anthropic key lives server-side
on `mrcall-agent`; the desktop never holds it. Cross-cutting context in
[`../CLAUDE.md`](../CLAUDE.md), engine plumbing in
[`../engine/CLAUDE.md`](../engine/CLAUDE.md).

## Naming and branding

- **User-visible**: "MrCall Desktop" everywhere — window title, sidebar, onboarding, README, asset names. `appId` is `ai.mrcall.desktop`.
- **Internal (engine)**: still `zylch` — Python package, CLI binary `zylch`, env vars `ZYLCH_*`, data dir `~/.zylch/profiles/`. A separate execution plan (Level 3) will rename the engine; until then, those identifiers stay so engine behaviour matches user-visible documentation only at the brand layer.

## Memory discipline

Claude Code keeps a per-user, per-machine memory at `~/.claude/projects/<encoded-path>/memory/`. **It is not in git, not shared with the team, not portable.** This `CLAUDE.md` and [`docs/`](docs/) here are the source of truth.

- **Project knowledge → this file or a doc under [`docs/`](docs/).** Build pipeline, IPC client shape, packaging quirks, electron-builder, sidecar lifecycle from the Electron side: check them in. Use `docs/active-context.md` for what is in flight, `docs/ARCHITECTURE.md` for boundaries, `docs/CONVENTIONS.md` for app code style.
- **Engine facts → [`../engine/docs/`](../engine/docs/).** Don't restate them here; link.
- **Cross-cutting facts (IPC contract, release pipeline, brand/rename) → [`../docs/`](../docs/).**
- **Personal notes → CC memory.** Your own preferences, working-style feedback. That's fine.
- **Before quoting CC memory**, verify against the current state of the repo. Memory can be stale; the repo cannot.
