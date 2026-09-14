# Desktop to operator: setup guide

<!-- doc-scope:start -->
Scope: the Desktop setup journey, released-kernel installation, developer checks,
and verification limits. Product intent lives in the paired brief; protocol
fields live in ipc-contract.md. This is not a production deployment runbook.
<!-- doc-scope:end -->

## AI execution and controls

There are three AI paths, even when the user sees one workspace:

| Path | Runs where | Model and payment | Scope of stop/cap |
|---|---|---|---|
| Interactive or headless operator | Coding-agent process in the cs-kernel clone; cron wrapper launches `claude -p "/cs-operator"` | Agent runtime settings/auth, independent of Desktop | Clone `CS_PAUSE` prevents subsequent guarded ticks, not an already-running process |
| Engine API work | Local sidecar or remote engine daemon | Desktop Settings / active engine profile; personal Anthropic/OpenRouter key or MrCall credits | `LLM_DAILY_BUDGET_USD` caps that profile's engine requests; preparation pause stops its processing flow |
| Direct kernel classifier | `cs` provider client in the clone, e.g. send guard | Clone/provider environment and role models | Outside engine budget; `CS_LLM_ROUTE=engine` does not disable the direct send guard |

Claude headless is the operator, not the engine's inference transport. A tick
can use Claude for reasoning and still incur separate engine API charges when
it requests generation. Draft-only work may spend tokens. An unattended engine
(`serve`) is also called headless, but does not mean a Claude Code subprocess.
Engine settings neither choose Claude's model nor determine its billing mode;
check the Claude process login/environment rather than assuming subscription.

The engine pause and the clone pause must be checked separately. Neither says
that all AI work or every running process is stopped. The kernel owns the
wrapper and direct classifier controls; see its
[operator runtime guide](https://github.com/malemi/cs-kernel/blob/main/docs/operator-runtime.md).

## What the user does

1. Sign in to Desktop and open **Setup**. Configure the mailbox and engine LLM
   billing in Settings. Explicit `LLM_PROVIDER` selects Anthropic/OpenRouter
   personal-key billing or MrCall credits for engine calls. Agent-host usage
   and direct kernel classifiers are separate. Only legacy profiles without
   an explicit provider infer billing from the saved Anthropic key. After changing the billing choice, click **Save** before
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
   descriptor, using kernel v0.44.0 as described below. The descriptor remains
   outside the workspace; do not copy its contents into chat or tracked files.
5. Complete the wizard, accept its installation and login offers, and run `cs setup`.
   Resolve the checklist's next actions. Then open Codex or Claude Code in the
   generated workspace. Executable detection does not prove agent login.

Setup and Settings remain accessible during engine failures. After switching
engines, discard unsaved settings explicitly before loading the new backend.
Opening Setup does not start paid preparation work. **Check connection** verifies
the already selected connection without restarting it. **Top up credits** opens
the MrCall dashboard; it does not require an Anthropic API key.

## Install the operator workspace

Desktop v0.1.47 includes the Setup interface. Its development-kernel banner is
older wording: kernel v0.44.0 supplies the required commands through the normal
release installation below. The guide link in that Desktop version still opens
this section. No Desktop rebuild is needed to use the released kernel.

### Kernel (macOS or Linux)

Install Python 3.11 or newer, Git and `uv` first. Open a terminal in the directory
where you want the new company workspace to be created. A kernel source checkout
is not required.

Set `CS_DESCRIPTOR` to the descriptor path displayed by Desktop (the path from
its **Copy workspace command**, not the entire command). Replace this placeholder:

```bash
CS_DESCRIPTOR='/paste/the/path/shown/by/Desktop/cs-descriptor.json'
```

Run the wizard directly from the release tag. This bootstrap works without a
previously installed `cs` command:

```bash
uvx --from "cs-kernel @ git+https://github.com/malemi/cs-kernel@v0.44.0" cs init --descriptor "$CS_DESCRIPTOR"
```

The wizard selects the exact desktop profile, reads available mailbox connection
settings and asks you to confirm anything missing. Choose the workspace directory
and confirm the settings. Answer **y** to **Install the project now**: it creates
that workspace's `.venv` and installs the generated release pin. Then answer
**y** to **Connect this workspace to the engine now**: it stores the selected
session and requires the engine to confirm the expected account.

Change into the newly created directory shown by the wizard. Use quotes if its
path contains spaces. Then run:

```bash
source .venv/bin/activate
cs setup
# Optional: the same report as machine-readable data
cs setup --json
```

A nonzero setup result means a prerequisite is missing or unverified; follow
its next action and rerun. The check uses bounded reads and may refresh the
local login cache, but starts no sync, training, generation or send. Launch
`codex` or `claude` yourself in this directory after its separate sign-in.

If you declined installation, or it failed, enter the generated workspace and
finish the same release installation:

```bash
test -d .venv || uv venv .venv
uv pip install --python .venv/bin/python -r requirements.txt
source .venv/bin/activate
cs login --descriptor "$CS_DESCRIPTOR"
cs setup
```

If installation succeeded but login was declined or failed, keep the existing
`.venv`, activate it and retry only `cs login --descriptor "$CS_DESCRIPTOR"`,
then `cs setup`. Creating a new workspace does not upgrade any existing one.

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
macOS/Windows behavior. These development tests used no production account mutations. Release and
hosted-engine rollout status is recorded in the delivery plan.
