---
description: Pre-release sanity check for the Electron build (engine bundling, signing, notarization, IPC contract).
---
Run before tagging a release or pushing to `main` with intent to publish. Six gates; report each as PASS / FAIL / SKIP. Do not auto-fix — surface findings to the user.

## Gate 1 — Versioning

- [ ] `app/package.json` `version` matches the intended release tag.
- [ ] `engine/pyproject.toml` `version` is in sync with `app/package.json` if they are released together (current convention).
- [ ] `engine/CHANGELOG.md` has an entry for the new version with the user-visible changes.
- [ ] No uncommitted changes (`git status` clean).

## Gate 2 — Engine sidecar build

- [ ] `engine/zylch.spec` is current (matches `engine/zylch/` entry point).
- [ ] If the release workflow rebuilds the sidecar into `app/bin/`, that path is in `app/.gitignore` (or otherwise excluded) so the binary isn't committed by accident.
- [ ] The bundled sidecar starts cleanly: spawn it manually with `--help` or equivalent and confirm it does not crash on missing optional deps.

## Gate 3 — IPC contract

- [ ] No JSON-RPC method name, payload shape, or error envelope changed since the last release without a corresponding update on **both** sides (`engine/zylch/**` server and `app/src/main/**` client).
- [ ] If the contract changed, a doc update lives in `docs/` (the cross-cutting IPC contract belongs to the monorepo, not a single side).
- [ ] No new method depends on a sidecar profile that the onboarding wizard cannot create.

## Gate 4 — Code signing & notarization (macOS)

- [ ] `electron-builder.yml` (or `package.json` build config) wires notarization through the `afterSign` hook (per fix in `2b8d98e`), **not** `mac.notarize`.
- [ ] Notarytool credentials validate before build (per `53f6945`). Do not skip; do not `--no-verify`.
- [ ] Hardened runtime entitlements are present and minimal — no `com.apple.security.cs.disable-library-validation` unless documented.
- [ ] DMG opens, app launches without Gatekeeper warnings on a clean macOS user account.

## Gate 5 — Sidecar runtime

- [ ] `app/src/main/` defaults sidecar `cwd` to `homedir()` (per fix in `77ed260`), not a dev-local path. Confirm this in the packaged build, not just dev mode.
- [ ] Profile dir `~/.zylch/profiles/<email>/` is created on first run, with the correct permissions (`0700` recommended for the dir).
- [ ] First-run onboarding wizard works end-to-end on a clean machine — `app/scripts/test-onboarding.mjs` if applicable, plus a real manual run.

## Gate 6 — Naming-rename status

- [ ] No new `zylch` strings were introduced in **user-visible** copy (window title, menu items, error messages, marketing strings).
- [ ] Internal identifiers (`zylch` package, `zylch` CLI binary, `~/.zylch/`, `ZYLCH_*` env vars) are unchanged — they are intentional until the dedicated rename PR lands.

## Final smoke

- [ ] On macOS arm64: `cd app && npm run dist:mac` produces a signed, notarized DMG; install and run.
- [ ] On Windows x64 (if releasing for Windows): `cd app && npm run dist:win` produces an installer; run on a clean Windows VM.
- [ ] Running app shows correct version in About dialog.
- [ ] Quit the app and confirm the sidecar process actually terminates (no orphaned `zylch` process in `ps`).

## Output

```
Release checklist for vX.Y.Z:
  Gate 1 versioning:     PASS
  Gate 2 sidecar build:  FAIL — engine/CHANGELOG.md missing entry
  Gate 3 IPC contract:   PASS
  Gate 4 signing/notar:  SKIP — Windows-only release
  Gate 5 runtime:        PASS
  Gate 6 naming sweep:   PASS

Blocking failures: 1. Fix Gate 2 before tagging.
```
