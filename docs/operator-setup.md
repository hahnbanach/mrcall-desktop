# Desktop to operator: development acceptance guide

<!-- doc-scope:start -->
Scope: the current source-only setup journey, reproducible developer entry points,
and verification limits. Product intent lives in the paired brief; protocol
fields live in ipc-contract.md. This is not a production deployment runbook.
<!-- doc-scope:end -->

## What the user does

1. Sign in to Desktop and open **Setup**. Configure the mailbox and engine LLM
   billing in Settings. MrCall credits pay for engine model calls; Codex or
   Claude Code is currently paid separately.
2. Activate or check the remote engine. Existing activation is checked rather
   than started again. Select the verified remote engine explicitly. A host
   company-membership refusal needs host-side account activation; changing the
   URL does not repair it.
3. Open **Prepare data**, configure/train the required prompts and run mailbox
   preparation. Setup distinguishes unknown evidence, empty mailboxes, partial
   processing and completed memory processing. These counts do not certify
   task detection or the quality of replies.
4. Copy the workspace command. Run it on the machine containing the Desktop
   descriptor, using the development kernel below. The descriptor remains
   outside the workspace; do not copy its contents into chat or tracked files.
5. Complete the wizard, install the changed kernel, log in, and run `cs setup`.
   Resolve the checklist's next actions. Then open Codex or Claude Code in the
   generated workspace. Executable detection does not prove agent login.

Setup and Settings remain accessible during engine failures. After switching
engines, discard unsaved settings explicitly before loading the new backend.
Opening Setup does not start paid preparation work.

## Source workspaces

Both repositories use branch `feat/operator-setup-ux`:

- Desktop: `/home/mal/worktrees/mrcall-desktop-operator-setup`
- Kernel: `/home/mal/worktrees/cs-kernel-operator-setup`

The changes are unreleased. The generated `requirements.txt`
still pins the existing release, which lacks the new commands. For this
acceptance pass, install the source explicitly; do not accept the wizard's
pinned-install offer. No existing operational clone needs to change.

### Desktop

From the Desktop worktree's `app/` directory:

```bash
npm ci
npm run typecheck
npm run build
npm run dev
```

`npm ci` runs the existing OAuth setup helper. Packaged Google sign-in needs the
normal OAuth build configuration; an empty example is sufficient for build
checks, not for proving Google sign-in. Local engine development also needs the
engine dependencies and the existing `ZYLCH_BINARY` configuration described in
[app guidance](../app/CLAUDE.md). The setup-evidence fields require this engine
source; an older remote engine correctly reports unverified evidence.

### Kernel (POSIX development example)

Install `uv` through your normal development environment first. Bootstrap the
new CLI in its own environment:

```bash
uv venv /tmp/mrcall-operator-cli
uv pip install --python /tmp/mrcall-operator-cli/bin/python /home/mal/worktrees/cs-kernel-operator-setup
/tmp/mrcall-operator-cli/bin/cs init --descriptor '/absolute/path/from/Desktop/cs-descriptor.json'
```

Use the actual descriptor path shown by Desktop. Decline the wizard's install
prompt for this unreleased development pass. In the newly generated workspace:

```bash
uv venv .venv
uv pip install --python .venv/bin/python /home/mal/worktrees/cs-kernel-operator-setup
.venv/bin/cs login --descriptor '/absolute/path/from/Desktop/cs-descriptor.json'
.venv/bin/cs setup
.venv/bin/cs setup --json
source .venv/bin/activate
```

A nonzero setup result means a prerequisite is missing or unverified; follow
its next action and rerun. The check uses bounded reads and may refresh the
local login cache, but starts no sync, training, generation or send. Launch
`codex` or `claude` yourself in this directory after its separate sign-in.

## Verification and limits

The delivery checks cover TypeScript/build, existing onboarding, redacted
handoff and shell quoting, owner-scoped engine evidence, the complete kernel
suite, and a generated workspace installed from the changed source against a
controlled local WebSocket engine. Browser fixtures mount the real Setup and
Settings components with synthetic bridges and block external requests.

Offline browser checks from `app/` (Playwright must be available):

```bash
node scripts/test-workspace-status.mjs
node scripts/test-setup.mjs
node scripts/check-setup-browser.mjs
node scripts/test-settings-recovery.mjs
```

Set `MRCALL_PLAYWRIGHT_MODULE` to an externally installed Playwright module if
needed and `MRCALL_BROWSER_BINARY` to a Chromium executable if not managed by
Playwright. `MRCALL_SETUP_ARTIFACTS` optionally chooses Setup screenshot output.
Current screenshots are in `/tmp/mrcall-operator-setup-artifacts/`.

These checks do not prove live Firebase refresh, production company activation,
mailbox credentials, public-tag installation, model billing, or packaged
macOS/Windows behavior. No production deployment or account mutation was used.
