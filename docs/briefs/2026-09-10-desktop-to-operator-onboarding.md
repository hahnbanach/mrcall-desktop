# From desktop setup to a working company operator

<!-- doc-scope:start -->
Scope: proposed product journey across desktop configuration, the remote engine,
and a cs-kernel clone; separates today's entry path from future personal-account
delegation and an embedded agent interface. This is a brief, not shipped behavior
or an approved implementation plan.
<!-- doc-scope:end -->

## Intent

A colleague should be able to configure an engine through MrCall Desktop, create
a company operator workspace from cs-kernel, and work in that workspace through
Codex or Claude Code without Mario repairing configuration between steps.

The immediate product is a guided path to that existing operator experience.
Rebuilding the desktop's mail, chat, WhatsApp, or task views is not part of it.
Eventually the desktop can expose the same agent workspace through its own UI.

## Product decisions from the operator

- **Version one augments an existing coding agent.** Users pay OpenAI or
  Anthropic directly for their Codex or Claude Code access. MrCall provides
  the engine service and its own metered model calls; its credits do not pay
  for the external workspace agent. Two billing paths are accepted for this
  version, not an onboarding defect to eliminate now.
- **Later product direction:** add other model options on the engine and
  replace the external coding-agent interface with a product chat. That chat
  must retain the workspace operator's procedures and tools, rather than
  expose only the current engine chat. Runtime and billing integration for
  that later experience remain to be designed.
- Desktop owns access and configuration now; an interface to the workspace agent
  is a later step. An engine `chat.send` client alone is not that interface.
- Engine owns mailboxes, sync, memory, message judgments, and channel actions.
- The operator based on cs-kernel owns procedures, campaigns, coordination, and
  approval requests. Company-specific content remains in its workspace.
- The target collaboration model is personal sign-in with explicitly selected
  sending identities, rather than colleagues sharing a mailbox login.
- The broad security review is explicitly deferred. This brief does not reopen
  the administrative-key or cron-sandbox work or weaken existing safeguards.
- The user reports a successful fresh-account setup. Treat that as evidence;
  do not claim onboarding is universally broken from a static code review.

## Existing pieces and the exact uncertainty

Source review on 2026-09-10; deployed state has not been inspected.

| Transition | Existing implementation | What still needs proving |
|---|---|---|
| Sign in and configure | Firebase gate and `app/src/renderer/src/views/Onboarding.tsx` create a local UID-keyed profile | Fresh installed-app path, including partial-failure recovery |
| Activate remote engine | `provision:start` in `app/src/main/index.ts`, `ProvisionStatus.tsx`, and `engine/zylch/provisiond/handler.py` | A genuinely new UID on the current deployed service |
| Choose remote endpoint | Backend settings select transport; `backend:testConnection` authenticates and calls `account.who_am_i` | Selected app endpoint and clone endpoint agree after a change |
| Hand over access | `app/src/main/csDescriptor.ts` writes the existing version-1 descriptor | A descriptor's existence does not prove a daemon or mailbox is ready |
| Create clone | cs-kernel `cs/project_init.py` discovers descriptors, prefills identity, retrieves mailbox credentials, stamps templates, and offers installation | A user completes creation and installation without manually repairing identifiers or paths |
| Log in and work | cs-kernel `cs/login.py` proves the engine identity; canonical skills drive the agent workspace | The first useful read and draft work against that same configured engine |

Entering `wss://desktop.mrcall.ai` selects a host; it does not itself create a
remote profile. The app already has a separate Activate action. Current source
requires an operator-maintained UID-to-company mapping before provisioning a new
remote profile and returns 403 for an unmapped UID. An already-active profile is
handled separately. Which prerequisites/version applied to the user's successful
trial is unknown; reproduce and trace it before changing the flow.

Local mode deserves an explicit check: its descriptor points to the vendor
daemon even though the app uses a local stdio engine. The immediate guided path
must finish against one verified remote engine, not silently configure one
engine and hand the clone credentials for another.

## Intended journey

1. **Enter and choose the company.** Sign in, then establish which company and
   mailbox this setup serves. For the first delivery use the current supported
   profile identity; do not present mailbox-owner authentication as personal
   delegation. Preserve this distinction in setup text and verification.
2. **Connect the mailbox and configure the assistant.** Capture connection and
   billing settings once. Verify reading; configure the sender and voice. Any
   live send check uses a designated test recipient and explicit authorization.
3. **Establish company memory.** Create the intended store or join the existing
   company through the supported path, with a recognizable preview. Prove the
   remote engine holds the intended membership; a local key alone is insufficient.
4. **Activate and prove the remote engine.** Provision when needed, show progress
   and actionable failures, authenticate against the selected endpoint, complete
   a bounded first sync/analysis, and prove memory retrieval. A running process
   or open socket is not the completion condition.
5. **Create the operator workspace.** Reuse cs-kernel's stamping/install path and
   the existing descriptor, with explicit company and profile selection if
   several exist. Do not invent a second manifest generator in the desktop.
   The initial target is the same computer as desktop sign-in; a different
   computer needs a separate access-handover design.
6. **Open the workspace agent.** Start the user's installed Codex or Claude Code
   in that workspace, load its canonical instructions, and prove identity,
   configuration, a recent message, and company-memory retrieval. Agent-runtime
   installation/authentication is a distinct prerequisite from engine billing;
   setup must expose it rather than imply the desktop login supplies both.
7. **Do useful work.** Ask what needs attention, inspect its source, prepare one
   grounded reply, and leave it ready for explicit approval. Close the desktop
   and confirm the clone still works and the remote engine continues scheduled
   processing through an authentication refresh cycle.

Each failed transition must name the unfinished step and offer a retry that
preserves completed work. Do not restart account creation after a later failure.

## Personal identity and sending identity

Target model: the authenticated person, the company workspace, the mailbox used
to send, and the displayed name/signature are distinct.

“Send as Giada <configured mailbox>” can select an authorized sender identity;
it must not change who is recorded as requesting or approving the action. If
Mario acts, the operation remains attributable to Mario even when the approved
From name or signature is Giada. Natural-language wording selects an existing
identity; it does not grant permission or create mailbox credentials.

This is not supported by the current `token.sub == OWNER_ID` model alone. A
separate delegation brief must specify the personal-to-mailbox relationship,
provenance, and compatibility with existing profiles before implementing it.
Do not migrate existing colleagues or require this redesign to prove steps 1–7
with today's supported profile identity. The resulting first delivery must not
claim personal-account collaboration is complete.

## Acceptance criteria for the first delivery

- A colleague starting with no local app profile or operator workspace reaches
  step 7 using the guided procedure without an undocumented host operation.
- Exercise both a new remote profile and a new local installation connecting to
  an existing remote profile; record which one each test actually covers.
- If a host mapping is required, it is an explicit supported setup step with
  ownership and feedback. Automatic company creation/invites need their own
  design; never bypass the current mapping check with a shared fallback key.
- App verification, descriptor, manifest, and authenticated clone agree on the
  remote endpoint and profile. No manual Firebase-UID editing is needed.
- A recent test message is visible and yields a grounded draft. Preparation
  sends nothing; an actual send is a separately authorized test.
- The configured remote company memory is demonstrated from the clone. Joining
  a colleague's existing memory is tested separately from minting a new store.
- A failed provision, stale descriptor, unavailable agent runtime, and a
  connection loss each produce an actionable state and a repeatable recovery.
- Desktop closure does not stop clone access or scheduled engine work; record
  the billing mode and verify its refresh behavior rather than assume parity.
- No clone creation or credential-handling step writes secrets into git or logs.

## Scope and sequence

First: reproduce the reported successful setup, document the actual transitions,
and close only the gaps needed for the same-machine desktop-to-clone journey.
Use the current installed agents; no new agent-runtime integration is required.

Later: personal-account delegation, then an embedded interface to the same
operator workspace. Persistence, reconnection, and ownership of a hosted
workspace belong to that later design. Do not duplicate its workflows inside
the engine chat or revive the desktop's channel views as a prerequisite.

Excluded: broad security audit, campaign redesign, moving all clone state to a
server, changing model vendors, release/deployment, or modifying existing clones.

The separately scoped [approval isolation brief](2026-09-10-chat-approval-isolation.md)
records a concrete existing bug. It is not a dependency for documenting or
proving the current desktop-to-clone setup path.

## Next engineering gate

Implementation was requested on 2026-09-10 in two isolated worktrees. The first
delivery is the bounded UX slice below. Deployments, sends, clone upgrades, and
changes to the current authentication model remain outside it.

## First implementation slice

- A default Setup hub connects configuration, remote activation/connection,
  preparation, and the same-machine workspace handoff. Existing channel views
  remain available; no new chat runtime is built.
- Preparation uses existing actions and adds additive, owner-scoped processed
  message evidence to `setup.state`; missing evidence on old engines is shown
  as unverified, not ready. A shared memory's blob count alone is not proof
  that this profile's mailbox was analyzed.
- Handoff exposes descriptor metadata and a correctly quoted `cs init
  --descriptor PATH` command without exposing its contents. It requires the
  matching updated kernel installed separately; an unpublished worktree is not
  advertised as a publicly released installer. The local delivery runbook
  includes exact source-install steps for these two worktrees.
- cs-kernel accepts that explicit descriptor, threads its identity outside
  serialized template data, uses the selected engine's mailbox configuration,
  and reports creation, installation, login, and readiness as separate outcomes.
  Failed installation must not return a completed-success result.
- `cs setup` provides a repeatable, non-business-mutating readiness report with
  JSON output: workspace, expected engine identity, mailbox configuration,
  preparation, memory, and installed external-agent executable. Agent executable
  presence is not proof of agent login or payment. Ordinary authentication may
  refresh its existing local token cache.
- Prove the integrated flow with isolated synthetic profiles/workspaces and
  offline/local protocol fixtures. Do not contact a real mailbox or call a
  billed model. Live sign-in, hosted provisioning, long-running refresh, and
  packaged macOS/Windows validation remain explicitly unverified until run.
- The host company mapping requirement remains enforced and visible with a
  support/retry path. This delivery does not silently mint a default shared key
  or claim unrestricted self-service provisioning.
