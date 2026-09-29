# Toward a sandbox: hosted engines that cannot read each other

<!-- doc-scope:start -->
Scope: isolating the profiles that share one hosted engine host from each
other, and keeping the model's own code away from a profile's secrets. This is
a security brief: intent, scope, constraints and acceptance criteria. It is not
an implementation plan, a provisioning brief or an operations runbook; those
are named under "Out" with their own owners.
<!-- doc-scope:end -->

## Problem and evidence

The hosted path (`docs/remote-backend.md`, section B) runs every profile's
daemon as the one service user `mrcalld`, which owns the engine checkout and
every profile under `/home/mrcalld/.zylch/profiles/<uid>/`. Firebase token
verification (`token.uid == OWNER_ID`) separates *clients* over the network;
nothing separates *daemons* on the host. Verified against source on
2026-09-29:

- `read_document` accepts any absolute path
  (`engine/zylch/tools/read_document_tool.py:156-158`) and is not in
  `APPROVAL_TOOLS` (`engine/zylch/services/task_executor.py:51-71`). A
  prompt-injected email can make profile A's agent read profile B's `.env`
  (IMAP password, API keys, `MEMORY_KEY`) with no user approval.
- `run_python` (`engine/zylch/tools/run_python_tool.py:76-83`, duplicated in
  `engine/zylch/services/solve_tools.py:264-292`) runs the model's code as
  `mrcalld` with the inherited environment; the engine loads the profile
  `.env` into it with `load_dotenv(..., override=True)`
  (`engine/zylch/cli/profiles.py:129`). It is approval-gated
  (`task_executor.py:70`), but approval shows the user code they cannot judge,
  and it has no network, filesystem or resource limit beyond a 60 s timeout.
  The model prompt calls it "a sandbox" (`engine/zylch/services/solve_constants.py:75`).
- `/tmp/zylch` is a scratch directory shared by every profile on the host
  (`run_python`, `download_attachment`, `read_document` search paths).
- The company memory store is `~/.zylch/memory/<MEMORY_KEY>.db`
  (`engine/zylch/memory/store.py:76`): the file name is the capability key, in
  a directory every daemon can list.
- One `ENCRYPTION_KEY` in `/etc/mrcalld/env` serves every profile
  (`engine/scripts/systemd/zylch-server@.service:25`).

`docs/remote-backend.md` states both "single-operator trust; hostile
multi-tenancy would need per-tenant isolation" and "this host is multi-tenant".
The second is the fact: four Café124 profiles and several others share the box,
and hosting by us is to become the normal path for new customers, with the
Electron app as the only client (agreed with the CTO on 2026-09-29). The
document's "≤1 WhatsApp profile per host" caveat is stale: the session store is
per profile (`engine/zylch/services/process_pipeline.py:760`).

External context, not verifiable from this repo: Meta's Muse (September 2026)
runs one VM per user with the agent in an unprivileged cell and credentials and
network egress held by a separate host-side service. We adopt the shape — an OS
boundary the model cannot cross, secrets outside the model's reach — not its
mechanisms.

## Intent

1. A company's data on a hosted engine is unreadable by any other company's
   daemon on the same host, enforced by the operating system, not by tool
   prompts or approval dialogs.
2. Self-serve sign-up (its own brief) opens only after 1 is deployed; until
   then provisioning stays operator-assisted on a vetted host.
3. Code the model writes either runs with no inherited environment, no network
   and no view of the profile, or does not run. Approval is not a substitute.
4. The hardened service definition is what a dedicated VM or a
   customer-premises install runs later: one company on the same unit files,
   no separate engine code path.

## Scope

**In.**

- **Hotfix, first and independent of the rest.** Remove the absolute-path
  shortcut from `read_document` and confine every path-taking tool to the
  profile directory plus its document folders; the default folders the local
  engine searches today (`~/Documents`, `~/Downloads`, `~/gdrive-shared`,
  `DOCUMENT_PATHS`) stay on the stdio engine. Replace the shared `/tmp/zylch`
  with a per-profile scratch directory. Refuse `run_python` in `serve` mode.
  Remove the "sandbox" wording from the prompt.
- **Per-profile OS identity on the shared host.** Each `zylch-server@<uid>`
  daemon runs as its own Unix user with write access to its profile and its
  company store only, no capabilities, and no view of other profiles or of
  the host. The company store is owned by a per-company group. Its file name
  is derived from the key rather than being the key; existing stores are
  renamed and `memory.join`/`store_exists` lookups follow. Each profile has
  its own `ENCRYPTION_KEY`, stored outside the model-reachable tree
  (e.g. `/etc/mrcalld/keys/<uid>`), readable by that profile's user only and
  included in the operator's backup set; existing `OAuthToken` rows are
  re-encrypted from the shared key to the profile key, with the shared key
  kept until rollback is no longer needed. The host scripts
  (`update-daemons.sh`, `join-company.sh`) and provisiond follow the new
  identity model. The six live profiles are migrated with a runbook and a
  rollback.
- **Tenant offboarding.** Deleting a profile removes its directory, key and
  daemon, and deletes its owned rule rows (`template:<owner>`,
  `prefs:<owner>`) from the company store. Company-family rows
  (`user:<key>`, `facts:<key>`) stay with the company and keep their
  provenance, as `engine/zylch/memory/scope.py` defines them; removing one of
  Café124's profiles must not strip facts the other three rely on. When the
  departing profile is the company's last key holder, the store itself is
  deleted.
- **Docs.** `docs/remote-backend.md` (multi-tenancy statement, WhatsApp
  caveat, identity model) and `AGENTS.md` where the hosting model changes.

**Out.**

- **Self-serve provisioning** (real entitlement, a company-membership source
  that is not an operator-edited file, the app calling provisiond, the Google
  Calendar OAuth callback served by the app instead of the engine's loopback
  listener at `engine/zylch/tools/google/calendar_oauth.py:61-62`). Own brief,
  once StarChat's entitlement and membership answer is known. It is gated on
  this brief's identity milestone.
- **Operational floor** (off-host backup, rehearsed restore, pinned reversible
  rollout instead of `git pull` on the live host, alerting on failed units).
  An operations runbook, due before the first customer outside Café124.
- **Data-processor obligations** (DPA, data location, retention). Owner: the
  CTO; the offboarding item above is the engineering half.
- **A real sandbox for `run_python` on hosts.** Only if the tool is wanted
  there again; the property is fixed by intent 3, the mechanism by the plan.
- **One VM per company as the default unit.** Right offering later; the fleet
  tooling (host directory, updates across N machines) does not exist. Parked.
- **Separating outbound sends and real credentials from the LLM process,**
  Muse-style. Protects a company from its own agent, not from other
  companies. Parked; the "approval isolation" deferral in
  `docs/active-context.md` stands.
- The native engine in the Mac and Windows installers: `run_python` is
  disabled or behind an explicit advanced setting; a local Linux VM is the
  supported self-host for advanced users. Thin clients stay parked.

## Constraints

- Firebase ID tokens stay in memory; `MEMORY_KEY` is never logged and
  `memory.join` stays its only write path; profiles stay keyed by Firebase
  UID. No JSON-RPC contract change.
- Live customers are on the host: every step is applied to a scratch profile
  first, has a rollback, and is deployed with the operator present. Sharing
  one store across several Unix users must keep SQLite's `-wal`/`-shm`
  ownership consistent (the trap `docs/remote-backend.md` documents).
- The hotfix must not change the local engine's behaviour beyond the
  absolute-path shortcut and the scratch directory.
- No paid LLM calls in verification; no real mail sent.

## Material assumptions

- Hosting by us is the normal path and Electron the client for everyone.
- Existing customers tolerate a short, announced restart per profile.
- The host distribution allows per-profile Unix users and the needed systemd
  features (the plan verifies the version).
- No current hosted customer flow depends on `run_python` or on absolute
  document paths; the operator confirms this against the profiles' logs
  before the hotfix is deployed.

## Acceptance criteria

1. **Cross-tenant read closed.** With profile A's daemon running as its own
   user, `read_document` with the absolute path of profile B's `.env` is
   refused, and `open()` of that file from a shell as A's user is denied by
   the OS. Before the OS change, the hotfix alone makes the tool refuse it.
2. **Model code cannot reach secrets.** `run_python` is refused in `serve`
   mode. On the local engine, `~/Documents` and `DOCUMENT_PATHS` still resolve.
3. **Store sharing survives identity separation.** Two daemons under two Unix
   users write to the same company store concurrently with no
   `readonly database` error; a third user cannot open it; `memory.join` finds
   the renamed store.
4. **Keys separated.** Each live profile decrypts its `OAuthToken` rows with
   its own key after migration; profile A's user cannot read profile B's key.
5. **Offboarding leaves nothing of the profile.** After deleting a scratch
   profile that shares a store with another, no file on the host belongs to
   that uid, its owned rule rows are gone, and the other profile's company
   facts are intact.
6. **Docs reconciled.** `docs/remote-backend.md` and `AGENTS.md` describe the
   identity model; the stale WhatsApp caveat is gone.

Verification is against real daemons on scratch profiles, not only unit
tests; each criterion names the command or RPC that proved it.

## Sequencing intent for the plan

The hotfix ships first and alone. Per-profile identity follows, one migration
at a time. Self-serve provisioning is built in parallel under its own brief
and opens only after identity is deployed. Parked items are recorded in the
plan, not dropped.
