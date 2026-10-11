# From desktop setup to a working company operator

<!-- doc-scope:start -->
Scope: product journey across Desktop configuration, a cs-kernel operator workspace and external AI clients; owns the proposed remote MCP architecture, authority, data, cost and lifecycle requirements. The original coding-agent delivery remains distinct from the unimplemented remote extension. This brief describes intent, not shipped remote behavior or an approved remote implementation plan.
<!-- doc-scope:end -->

## Intent

The remote product target is: configure the company through Desktop, then connect
ChatGPT or Claude using an independently authenticated AI account to the selected
MrCall profile and company. Read authorized company data and prepare a draft from
an exact source message, including from a phone while Desktop is closed. The
daemon is released only for Linux. Desktop remains the configuration and draft
review interface. The coding-agent journey below is the original delivered slice,
not a prerequisite requiring every remote user to install a coding agent.

## Remote MCP design decisions — unimplemented extension

The [data flows](../operator-data-flows.md) explain this design. None of the
following requirements is an assertion that the remote service exists.

### Service and identity boundary

- Each profile's Linux engine process hosts its own Streamable HTTP MCP endpoint
  behind Caddy, under the same Unix user and sandbox as that engine. Its MCP
  adapter dispatches through the engine's policy-enforced methods internally.
  There is no central adapter impersonating users, minting Firebase tokens or
  crossing profile Unix sockets. Desktop's Firebase WSS boundary stays separate.
- A centrally hosted MrCall authorization service owns the private grant store,
  client registrations, consent and the shared MCP quota ledger. Firebase proves the person's identity; the
  service separately checks profile access, company membership and company policy.
  Signing into ChatGPT or Claude establishes none of these rights.
- A grant binds subject UID, selected profile, one space_id, verified client,
  permitted data classes and scopes to that profile's canonical MCP resource URL.
  Authorization and token requests carry that resource. The profile engine
  rejects wrong issuer/resource/profile/company even when a token is otherwise valid.
- First-party-supported Claude/ChatGPT clients and exact registered redirect URIs
  are allowlisted. No unrestricted DCR. Provider registration details must be
  verified before implementation; consent names come from trusted registration.
  Invalid clients or redirects are rejected before any redirect or code issuance.
- The authorization service is deployed separately from tenant engines, with
  protected persistent grant storage. Engines may reach only its required HTTPS
  introspection and quota endpoints through their outbound allowlist. Introspection reads
  committed current grants/policy, never a stale replica. Registration, backups,
  service credentials and operational deployment belong to implementation gates.

### Consent, revocation and permissions

- Use opaque access tokens, authenticated introspection at each request admission
  and immediately before releasing business results. No positive grant cache in
  the initial implementation. An unavailable service fails closed for MCP only;
  Desktop and scheduled engine work retain their independent authentication.
- Revocation acknowledgement means subsequent admissions are refused. Work
  already admitted may have produced a draft or cost; revocation does not roll it
  back or retract content already delivered. A failed return-time check withholds
  the result and leaves an uncertain operation inspectable in Desktop.
- Refresh rotates refresh tokens and rechecks membership, client, grant and
  company policy. Access tokens expire after five minutes as a secondary bound;
  expiration is not the mechanism providing acknowledged grant revocation.
- Desktop logout and closing a conversation do not revoke remote grants. Explicit
  grant revocation, removal of company membership, company connector disable,
  password reset and sign-out-everywhere invalidate affected grants. Firebase
  session revocation alone is insufficient: security events must invalidate the
  central grant store before the product can claim this behavior.
- Grants expire after 90 days without admitted use. Desktop Settings shows the
  verified client, profile/company, scopes, data classes, last use and individual
  revoke action. The company admin can disable connectors and revoke company grants.
- Scope `operator.read` covers context and the six read tools; `operator.ask`
  permits paid read-only engine questions; `operator.draft` permits reply preparation.
  Budget is a separate bound. A paid read is not a draft permission. Consent names
  the company and data classes; the same user needs a separate grant for another company.

### Data, budget and audit

- Effective access is the intersection of profile rights, current company policy,
  grant scopes and approved source classes. Ordinary business mail/tasks and
  explicitly permitted project/procedure documents may be selected. Finance/Qonto
  and PEC content and their derived tasks are excluded by default. Unknown origin
  is denied; text redaction is not source classification. Mixed-source answers and
  derived memory must preserve provenance or remain unavailable to the connector.
- Company admins decide whether these classes may be exposed to the third-party
  AI provider; individuals can narrow that choice, never widen it. Disabling a
  class affects existing grants and results. Publication requires an explicit data
  disclosure and review of the applicable contractual/privacy terms; this brief
  makes no legal-compliance claim and prescribes no unsupported DPA wording.
- Paid calls reserve cost in the engine before dispatch. The MCP pool is bounded
  separately from the daemon's reserved share of the total profile budget, with
  per-grant cost and request limits and a company aggregate ceiling. Concurrency,
  retries, read-only calls and draft calls cannot bypass reservation. A company
  counter local to one profile is insufficient: the central quota ledger
  atomically reserves the grant, MCP-profile and company limits across profiles.
  Its authenticated service caller is restricted to the engine's own profile.
  A quota-service failure refuses paid MCP work. There is no automatic
  fallback to the daemon allocation. Quota sizes are visible configuration and
  must be fixed before beta. Exhaustion reports `budget_exhausted`; rate refusal
  reports `rate_limited`. Admission or quota refusal incurs no model request.
  Unsettled reservations remain held until idempotent recovery settles actual cost.
- Minimal audit records capture time, grant/client, profile/company, tool, outcome,
  source references, request correlation and charged cost. Do not log tokens, full
  mail, prompts or returned documents. A profile user sees their own activity;
  company admins see grant/governance metadata without inheriting private mail
  contents. Retention and access limits must be fixed before beta.

### Procedures and draft authority

- The remote operator's canonical procedures are revisioned engine-owned
  `operator-instructions` project records. Local files are working copies for this
  mode, never a competing authority. Existing clone/local-candidate canonical-file
  behavior is not silently migrated. A server-side operator compiler produces
  derived procedure/phone/mailbox documents from an atomic canonical revision.
  Shared procedures and private profile mailbox identity retain distinct write
  permissions; company membership alone cannot rewrite another profile's identity.
- Save uses the revision originally loaded by the editor, reports conflicts and
  presents changes for explicit merge/reload. It never fetches the latest revision
  merely to overwrite somebody else's changes. Remote `operator_context` reads the
  authorized canonical revision and its derived-publication state.
- Before remote draft preparation, the engine contract must accept a native,
  profile/grant-bound idempotency key and return the exact draft ID and revision
  caused by that turn. Same-key/different-payload conflicts are refused; concurrent
  equal requests have one outcome. A lost response can be resolved by engine
  operation lookup without generating another draft. Draft persistence and the
  operation outcome must be recoverable across crashes. No before/after list diff
  is accepted as causal attribution. The current candidate's limitation remains
  until this contract is implemented and verified.
- Read exact versions supported by `system.capabilities` and refuse unsupported
  policy contracts; do not guess compatibility. Engine enforcement applies to
  connector dispatch as well as other entry points. Error codes are structured
  MCP tool errors; admission/authentication errors retain their HTTP semantics.
- This MCP surface exposes no send, approval-to-send, arbitrary filesystem or
  shell tool. Draft sending stays in the separately authorized Desktop workflow.
  Tool annotations describe effects but cannot enforce confirmation or permission.

### Threat model and delivery boundary

| Threat | Required boundary and remaining limit |
|---|---|
| Attacker-controlled email or document | Treat content as untrusted data, never a permission grant. Enforce source/data scopes in the engine. A draft still requires human review. |
| AI client follows injected instructions | Restrict every read and mutation independently. No-send limits action damage but does not prevent disclosure through read results. |
| Stolen MCP token | Profile resource binding, active-grant checks, rotation and revocation bound exposure; allowed data can still be read before revocation. |
| Compromised user computer | Local descriptors/session access may be stolen; local generation checks cannot defend against the same user's compromise. Remote grant revocation is a separate control. |
| Compromised central authorization service | It can issue profile authority; tenant isolation does not eliminate this trust root. Protect and audit its administration and credentials. |

The local STDIO candidate is a Claude Desktop preview, with real installation
acceptance still unverified. It is not the mobile product, and a ChatGPT ZIP has
no verified consumer. ChatGPT's supported remote or Secure MCP Tunnel connection
is a distinct transport requiring its own configuration and acceptance. Token
caching and persistent WSS are possible local optimizations, not a measured
latency fix or an equivalent substitute for per-call identity/company checks.

Remote beta depends on read access, company policy and audit first; then isolated
paid asks and native draft identity/idempotency. Broader self-service provisioning,
filesystem extensions, embedded product chat and sending through MCP are excluded.
The existing completed delivery plan remains historical; its remote sequence is
planning input, not authorization to implement, deploy or migrate profiles.

## Original coding-agent delivery

The following sections retain the original delivery contract; they do not override
the remote extension above or claim its requirements are implemented.

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
