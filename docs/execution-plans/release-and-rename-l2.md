---
status: in-progress
created: 2026-04-27
---

# Release pipeline + Rename Level 2 (Zylch → MrCall Desktop, user-visible only)

## Goal

Two coordinated changes shipped on the same PR:

1. **Tag-driven release matrix.** Tag `v*` produces installers for
   macOS arm64 + Windows x64 by default. Tag `v*-intel` additionally
   builds macOS Intel x64 on `macos-13-large` (paid). Manual
   `workflow_dispatch` exposes the same Intel toggle as a boolean
   input.
2. **Rename Level 2.** User-visible strings flip from "Zylch" to
   "MrCall Desktop" in the Electron app — package metadata, window
   titles, headers, toasts, README. The engine (`zylch` Python
   package, CLI binary, env vars, `~/.zylch/profiles/` data dir) is
   **not** renamed: that's Level 3, scheduled separately.

## Scope decisions

| Decision | Value | Rationale |
|----------|-------|-----------|
| `productName` | `MrCall Desktop` | Distinguishes from the platform service ("MrCall" the phone product) and matches the first line of `app/CLAUDE.md`. |
| `appId` | `ai.mrcall.desktop` | Aligned with the `mrcall.ai` domain. |
| Tag suffix for Intel | `-intel` | Looks like a SemVer prerelease, but we explicitly force `prerelease: false` on the GitHub Release. |
| Intel runner | `macos-13-large` (paid) | Free `macos-13` queues for hours; large pool is short-queued. ≈ $2.50/build. |
| `~/.zylch/` data dir | Unchanged | Engine still emits `zylch` paths internally; matches reality. Level 3 will migrate. |
| Existing `Zylch 0.1.24` installs | Coexist with new app | New `appId` ⇒ macOS / Windows treat the new build as a different app. Acceptable for the 2-3 testers; flagged in PR description. |

## Workflow design (`.github/workflows/release.yml`)

```
push tag v*            ──┐
workflow_dispatch ──┐   │
  inputs:           │   ▼
    include_intel:  ├──> setup (ubuntu-latest)
      bool          │       └─ emit engine_matrix + app_matrix as JSON
                    │          based on `endsWith(ref_name, '-intel')`
                    │          OR `inputs.include_intel == true`
                    │
                    ▼
build-engine (matrix from setup.outputs.engine_matrix)
  - macos-14            arm64    (always)
  - windows-latest      x64      (always)
  - macos-13-large      x64      (only if Intel requested)
  └─ artifact: sidecar-<plat>-<arch>

build-app (matrix from setup.outputs.app_matrix; needs build-engine)
  - same matrix; downloads matching sidecar artifact, runs electron-builder
  └─ artifact: installers-<plat>-<arch>

release (only on tag push; needs build-app)
  - download all installer artifacts
  - softprops/action-gh-release@v2 with prerelease: false
  - attaches whatever was built (2 or 3 installers)
```

## Rename Level 2 — file-by-file

### Package metadata
- `app/package.json`:
  - `name`: `zylch-desktop` → `mrcall-desktop`
  - `productName`: `Zylch` → `MrCall Desktop`
  - `appId`: `com.zylch.desktop` → `ai.mrcall.desktop`
  - Add `build.artifactName: "${productName}-${version}-${arch}.${ext}"` for explicit naming.

### App UI strings (user-visible only)
- `app/src/renderer/index.html` — `<title>` tag
- `app/src/renderer/src/App.tsx` — window-title formatter, sidebar header, "Create profile" tooltip
- `app/src/renderer/src/views/Onboarding.tsx` — welcome heading
- `app/src/renderer/src/views/Email.tsx` — delete tooltip
- `app/src/renderer/src/views/Workspace.tsx` — empty-state copy
- `app/src/renderer/src/views/Settings.tsx` — restart toast
- `app/src/main/sidecar.ts` — profile-lock error message + hint
- `app/src/main/profileFS.ts` — `.env` header comment

### Docs
- `app/CLAUDE.md` — Distribution section: replace `malemi/zylch-desktop` / `malemi/zylch` references with `hahnbanach/mrcall-desktop` and "the workflow builds the sidecar from `engine/` in this repo".
- `app/README.md` — top brand line, Releases URL, asset names in download table, install-time strings, dev-build instructions (sidecar comes from `engine/`, not `malemi/zylch`).

### Explicitly NOT touched (engine-internal, would belong to Level 3)
- `window.zylch` API namespace in `preload/index.ts` and references
- `ZylchAPI`, `ZylchTask` TypeScript types
- `~/.zylch/profiles/` paths (engine data dir is real)
- `ZYLCH_BINARY`, `ZYLCH_CWD`, `ZYLCH_PROFILE` env vars (engine contract)
- `zylch:conversations:` localStorage key (would invalidate existing user state)
- `bin/zylch` / `bin/zylch.exe` extra-resource path (binary still emits as `zylch`)
- `Run \`zylch init\` first` / "running zylch CLI" — these reference the actual binary
- `errors.ts` substring match `'is already in use by another Zylch'` — matches engine output verbatim; cannot drift from engine until engine is renamed
- Code comments referencing Python paths `zylch/services/...`

## Side-effects and follow-ups

- **`mrcall-website` download buttons** point at the old asset filenames. Out of scope here; flag in PR. Update when the first `v0.1.25*` release lands.
- **Existing testers** with `Zylch 0.1.24` installed will get a separate "MrCall Desktop" app on next install. Document in release notes.
- **Larger runners on the repo**: `macos-13-large` requires "Larger runners" enabled in repo / org Settings → Actions → Runners. Verify before tagging `*-intel`.
- **Level 3 (engine rename)** to be planned separately: `zylch` Python package + CLI binary + env vars + data dir + migration logic for existing profiles.

## Steps

1. Branch `ci/tag-trigger-intel-and-rename-l2` from `main`.
2. Commit 1 — plan doc (this file).
3. Commit 2 — workflow rewrite with dynamic matrix + Intel toggle.
4. Commit 3 — rename Level 2 across `app/`.
5. Push branch, open PR with description listing side-effects.
6. After merge: dispatch a workflow run with `include_intel: false` to validate end-to-end. Then tag `v0.1.25` for the first release.
