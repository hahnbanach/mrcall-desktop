# Desktop to operator: development acceptance guide

<!-- doc-scope:start -->
Scope: the current source-only setup journey, reproducible developer entry points,
and verification limits. Product intent lives in the paired brief; protocol
fields live in ipc-contract.md. This is not a production deployment runbook.
<!-- doc-scope:end -->

## What the user does

1. Sign in to Desktop and open **Setup**. Configure the mailbox and engine LLM
   billing in Settings. MrCall credits pay for engine model calls; Codex or
   Claude Code is currently paid separately. The engine uses a saved Anthropic
   API key for direct billing; without that key, the signed-in session uses
   MrCall credits. After changing the billing choice, click **Save** before
   preparing data. A pending choice does not change the engine's billing.
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
Opening Setup does not start paid preparation work. **Check connection** verifies
the already selected connection without restarting it. **Top up credits** opens
the MrCall dashboard; it does not require an Anthropic API key.

## Source workspaces

Use your local `mrcall-desktop` and `cs-kernel` checkouts on the Mac (or Linux).
Their directory names and locations do not matter. In each repository, select
and update the development branch:

```bash
git fetch origin
git switch feat/operator-setup-ux
git pull --ff-only
```

The changes are unreleased. The generated `requirements.txt`
still pins the existing release, which lacks the new commands. For this
acceptance pass, install the source explicitly; do not accept the wizard's
pinned-install offer. No existing operational clone needs to change.

### Desktop

Open a terminal in the root of your local `mrcall-desktop` checkout:

```bash
cd app
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

### Kernel (macOS or Linux)

Install `uv` through your normal development environment first. Open a second
terminal in the root of your local `cs-kernel` checkout, on the branch selected
above. These variables capture its actual path and create a temporary CLI
environment; keep using this terminal for the remaining commands.

```bash
CS_KERNEL_SOURCE="$(pwd -P)"
CS_SETUP_ENV="$(mktemp -d "${TMPDIR:-/tmp}/mrcall-operator-cli.XXXXXX")"
uv venv "$CS_SETUP_ENV"
uv pip install --python "$CS_SETUP_ENV/bin/python" "$CS_KERNEL_SOURCE"
```

Set `CS_DESCRIPTOR` to the descriptor path displayed by Desktop (the path from
its **Copy workspace command**, not the entire command). Replace this placeholder:

```bash
CS_DESCRIPTOR='/paste/the/path/shown/by/Desktop/cs-descriptor.json'
```

Create the operator workspace alongside the source checkout. The wizard chooses
its directory name from your company slug:

```bash
cd ..
"$CS_SETUP_ENV/bin/cs" init --descriptor "$CS_DESCRIPTOR"
```

**Decline the wizard's install prompt** for this unreleased development pass.
Then `cd` into the newly created directory shown by the wizard and run:

```bash
uv venv .venv
uv pip install --python .venv/bin/python "$CS_KERNEL_SOURCE"
.venv/bin/cs login --descriptor "$CS_DESCRIPTOR"
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
The browser scripts print the screenshot directory on your own machine.

These checks do not prove live Firebase refresh, production company activation,
mailbox credentials, public-tag installation, model billing, or packaged
macOS/Windows behavior. No production deployment or account mutation was used.
