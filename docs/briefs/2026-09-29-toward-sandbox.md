# Toward a sandbox: hosted engines that cannot read each other

<!-- doc-scope:start -->
Scope: isolating the profiles that share one hosted engine host from each
other, and keeping the model's own code away from a profile's secrets. This is
a security brief: threat model, intent, scope, constraints and acceptance
criteria. It is not an implementation plan, a provisioning brief or an
operations runbook; those are named under "Out" with their own owners.
<!-- doc-scope:end -->

## Threat model

One crafted inbound email or WhatsApp message, received by any hosted
profile, read by that profile's agent. Also: one authenticated customer who
changes their own Settings. Neither attacker has a shell on the host. The
boundary this brief builds must hold *before* data reaches the model context:
every tool result is sent to the LLM provider, so reading another profile's
file **is** the exfiltration, with no send and no approval involved. Approval
dialogs protect a company from its own agent, not one company from another,
and are not counted as a boundary here. This matches the incidents of
2025–2026 (zero-click exfiltration through a crafted email in Copilot;
link-preview exfiltration and a mail-archive breach in OpenClaw): the
mail-ingesting agent is the attack surface.

## Problem and evidence

The hosted path (`docs/remote-backend.md`, section B) runs every profile's
daemon as the one service user `mrcalld`, which owns the engine checkout, the
venv and every profile under `/home/mrcalld/.zylch/profiles/<uid>/`. Firebase
token verification (`token.uid == OWNER_ID`) separates *clients* over the
network; nothing separates *daemons* on the host. Verified against source on
2026-09-29 by two independent reviews:

- **Read, by injection.** `read_document` accepts any absolute path
  (`engine/zylch/tools/read_document_tool.py:156-158`) and is not in
  `APPROVAL_TOOLS` (`engine/zylch/services/task_executor.py:51-71`). Profile
  A's agent can read profile B's `.env` (IMAP password, API keys,
  `MEMORY_KEY`).
- **Read, by the customer.** `DOCUMENT_PATHS` and `DOWNLOADS_DIR` are
  ordinary Settings keys (`engine/zylch/services/settings_schema.py:445-462`)
  written by `settings.update` over the WebSocket. Customer A sets
  `DOCUMENT_PATHS=/home/mrcalld/.zylch/profiles` and `read_document("*.env")`
  globs every tenant's secrets. No injection needed.
- **Write, by injection, unapproved.** `fetch_attachments` saves each
  attachment at `os.path.join(save_dir, filename)` with the sender's filename,
  never reduced to a basename (`engine/zylch/email/imap_client.py:1424-1434`);
  `download_attachment` is not approval-gated and takes a model-supplied
  `target_dir`. An attachment named `/home/mrcalld/.zylch/profiles/<B>/.env`
  overwrites B's credentials; one named after a module in the editable engine
  checkout runs attacker code in every daemon at the next restart.
- **Model code.** `run_python` (`engine/zylch/tools/run_python_tool.py:76-83`,
  duplicated in `engine/zylch/services/solve_tools.py:264-292`) runs the
  model's code as `mrcalld` with the inherited environment, into which the
  profile `.env` was loaded (`engine/zylch/cli/profiles.py:129`). It is
  approval-gated (`task_executor.py:70`), but the user is shown code they
  cannot judge, and there is no network, filesystem or resource limit beyond a
  60 s timeout. The prompt calls it "a sandbox"
  (`engine/zylch/services/solve_constants.py:75`).
- **Shared writable code.** The daemon identity owns the engine checkout and
  venv (`update-daemons.sh` pulls as `mrcalld`), so any code execution as that
  identity is persistent and host-wide.
- **Shared scratch and store.** `/tmp/zylch` is shared by every profile. The
  company memory store is `~/.zylch/memory/<MEMORY_KEY>.db`
  (`engine/zylch/memory/store.py:76`): the file name is the capability key,
  in a directory every daemon can list.
- **One key, soft fallback.** One `ENCRYPTION_KEY` in `/etc/mrcalld/env`
  serves every profile (`engine/scripts/systemd/zylch-server@.service:25`);
  `engine/zylch/utils/encryption.py` falls back to the profile `.env` and then
  to passthrough, so a missing key stores tokens in clear without failing.

`docs/remote-backend.md` states both "single-operator trust; hostile
multi-tenancy would need per-tenant isolation" and "this host is multi-tenant".
The second is the fact: four Café124 profiles and several others share the box,
and hosting by us is to become the normal path for new customers, with the
Electron app as the only client (agreed with the CTO on 2026-09-29). Its "≤1
WhatsApp profile per host" caveat is stale: the session store is per profile
(`engine/zylch/services/process_pipeline.py:760`).

External context (not verifiable from this repo; sources in the review record
of 2026-09-29): Meta's Muse isolates each user in a VM with the agent in an
unprivileged cell, credentials in a separate host service and all egress
through a gatekeeper, and still calls prompt injection an open problem;
OpenClaw shipped sandboxing off by default and had exfiltration and breach
incidents; Claude Code's sandbox denies the agent writes to the files it loads
code from and states that in-process tools are not covered by the command
sandbox. Lessons adopted: an OS boundary before the model context, read-only
code, model code refused rather than trusted to a default-off sandbox, every
tool enumerated rather than one.

## Intent

1. A company's data on a hosted engine is neither readable nor writable by
   any other company's daemon on the same host, enforced by the operating
   system, not by tool prompts, Settings or approval dialogs.
2. Self-serve sign-up (its own brief) opens only after 1 is deployed; until
   then provisioning stays operator-assisted on a vetted host.
3. Code the model writes either runs with no inherited environment, no network
   and no view of the profile, or does not run. Approval is not a substitute.
4. Engine code on a host is owned by a deploy identity that no daemon runs
   as, and is read-only to every daemon.
5. The hardened service definition is what a dedicated VM or a
   customer-premises install runs later: one company on the same unit files,
   no separate engine code path.

## Scope

**In.**

- **Hotfix, first and independent of the rest.** In `serve` mode: the search
  set of every path-taking tool is the profile directory and its downloads
  directory only; `DOCUMENT_PATHS` and `DOWNLOADS_DIR` are ignored (or refused
  by `settings.update`); the absolute-path shortcut is removed; every
  attachment filename is reduced to its basename before saving and
  `target_dir` outside the profile is refused; the scratch directory is per
  profile; `run_python` is refused. On the local (stdio) engine the default
  folders (`~/Documents`, `~/Downloads`, `~/gdrive-shared`, `DOCUMENT_PATHS`)
  keep working; only the absolute-path shortcut and the attachment basename
  rule apply everywhere. The "sandbox" wording leaves the prompt. The plan
  enumerates every tool and RPC method that takes a path, a file id, a
  destination or a URL, with the two reviews' lists as its starting point.
- **Per-profile OS identity on the shared host.** Each `zylch-server@<uid>`
  daemon runs as its own Unix user with write access to its profile, its
  runtime socket directory and its company store only, a private `/tmp`, no
  capabilities, and no view of other profiles or of the host. The engine
  checkout and venv are owned by a deploy identity and mounted read-only to
  daemons. The company store is owned by a per-company group in a directory
  whose mode the plan verifies; its file name is derived from the key rather
  than being the key; existing stores are renamed and
  `memory.join`/`store_exists` lookups follow without listing the directory.
  Each profile has its own `ENCRYPTION_KEY`, stored outside the
  model-reachable tree (e.g. `/etc/mrcalld/keys/<uid>`), readable by that
  profile's user only and included in the operator's backup set; existing
  `OAuthToken` rows are re-encrypted from the shared key to the profile key,
  with the shared key kept until rollback is no longer needed; in `serve`
  mode the `.env` and passthrough fallbacks are removed and a missing key is
  a unit failure. Creating users, groups, keys and socket directories needs
  root: a small, allowlisted, root-owned helper does it, invoked by the
  reconcile path and later by provisiond; provisiond itself does not run as
  root. The host scripts (`update-daemons.sh`, `join-company.sh`) follow the
  new identity model. The six live profiles are migrated with a runbook and a
  rollback.
- **Egress.** Each daemon's outbound network is limited to the mail, WhatsApp,
  StarChat and LLM-provider endpoints its profile is configured for, and the
  limit is observable on the host. This does not replace intent 1; it bounds
  what a compromised daemon can do with its *own* data.
- **Tenant offboarding.** Deleting a profile removes its directory, key,
  user and daemon, and deletes its owned rule rows (`template:<owner>`,
  `prefs:<owner>`) from the company store. Company-family rows
  (`user:<key>`, `facts:<key>`) stay with the company and keep their
  provenance, as `engine/zylch/memory/scope.py` defines them; removing one of
  Café124's profiles must not strip facts the other three rely on. When the
  departing profile is the company's last key holder, the store itself is
  deleted.
- **Docs.** `docs/remote-backend.md` (multi-tenancy statement, WhatsApp
  caveat, identity model, helper) and `AGENTS.md` where the hosting model
  changes.

**Out.**

- **Self-serve provisioning** (real entitlement, a company-membership source
  that is not an operator-edited file, the app calling provisiond, the Google
  Calendar OAuth callback served by the app instead of the engine's loopback
  listener at `engine/zylch/tools/google/calendar_oauth.py:61-62`). Own brief,
  once StarChat's entitlement and membership answer is known. It is gated on
  this brief's identity milestone and uses the root helper defined here.
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
  Muse-style, and injected facts persisting in the shared company memory
  (`update_memory` is approval-gated; a colleague's approval of a poisoned
  fact is a company-internal problem). Both protect a company from its own
  agent. Parked; the "approval isolation" deferral in
  `docs/active-context.md` stands.
- The native engine in the Mac and Windows installers: `run_python` is
  disabled or behind an explicit advanced setting; a local Linux VM is the
  supported self-host for advanced users. Thin clients stay parked.

## Constraints

- Firebase ID tokens stay in memory; `MEMORY_KEY` is never logged and
  `memory.join` stays its only write path; profiles stay keyed by Firebase
  UID. No JSON-RPC contract change; a Settings key ignored in `serve` mode is
  reported as such by `settings.get`, not silently dropped.
- Live customers are on the host: every step is applied to a scratch profile
  first, has a rollback, and is deployed with the operator present. Sharing
  one store across several Unix users must keep SQLite's `-wal`/`-shm`
  ownership consistent (the trap `docs/remote-backend.md` documents).
- The reverse proxy must still reach each daemon's socket after the runtime
  directory is no longer owned by one user.
- The hotfix must not change the local engine's behaviour beyond the
  absolute-path shortcut and the attachment basename rule.
- No paid LLM calls in verification; no real mail sent; the attachment test
  uses a locally constructed message.

## Material assumptions

- Hosting by us is the normal path and Electron the client for everyone.
- Existing customers tolerate a short, announced restart per profile.
- The host distribution allows per-profile Unix users and the needed systemd
  features (the plan verifies the version).
- No current hosted customer flow depends on `run_python`, on absolute
  document paths or on `DOCUMENT_PATHS`; the tool logs do not record paths,
  so the operator confirms this with the four Café124 users before the
  hotfix is deployed.

## Acceptance criteria

1. **Cross-tenant read closed, three ways.** With profile A's daemon running
   as its own user: `read_document` with B's `.env` absolute path is refused;
   A's `settings.update` of `DOCUMENT_PATHS` to the profiles root is ignored
   and `read_document("*.env")` finds nothing outside A; `open()` of B's file
   from a shell as A's user is denied by the OS. Before the OS change, the
   hotfix alone makes the first two hold.
2. **Cross-tenant write closed.** A locally constructed message with an
   attachment named with an absolute path and one with `../` components lands
   under A's downloads directory as its basename; `download_attachment` with a
   `target_dir` outside A is refused; as A's user, a write into the engine
   checkout and into B's profile is denied by the OS.
3. **Model code cannot reach secrets.** `run_python` is refused in `serve`
   mode. On the local engine, `~/Documents` and `DOCUMENT_PATHS` still resolve.
4. **Store sharing survives identity separation.** Two daemons under two Unix
   users write to the same company store concurrently with no
   `readonly database` error; a third user cannot open it or list the store
   directory; `memory.join` finds the renamed store.
5. **Keys separated and mandatory.** Each live profile decrypts its
   `OAuthToken` rows with its own key after migration; A's user cannot read
   B's key; a daemon started without its key fails instead of storing in
   clear.
6. **Egress bounded and visible.** From A's daemon, a connection to an
   address outside its configured endpoints is refused, and the allowed set
   is readable on the host for that unit.
7. **Offboarding leaves nothing of the profile.** After deleting a scratch
   profile that shares a store with another, no file or user on the host
   belongs to that uid, its owned rule rows are gone, and the other profile's
   company facts are intact.
8. **Docs reconciled.** `docs/remote-backend.md` and `AGENTS.md` describe the
   identity model and the helper; the stale WhatsApp caveat is gone.

Verification is against real daemons on scratch profiles, not only unit
tests; each criterion names the command or RPC that proved it.

## Sequencing intent for the plan

The hotfix ships first and alone, and it is not done until criteria 1 (first
two clauses), 2 (first two clauses) and 3 hold: closing one read path is not
closing the tenant boundary. Per-profile identity, read-only code and egress
follow as one systemd change, one migration at a time. Self-serve
provisioning is built in parallel under its own brief and opens only after
identity is deployed. Parked items are recorded in the plan, not dropped.
