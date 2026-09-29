---
status: planned
---

# Toward a sandbox: execution plan

<!-- doc-scope:start -->
Scope: milestones, ownership, verification and rollback for the approved
isolation brief. Mechanisms are chosen here; properties come from the brief.
<!-- doc-scope:end -->

Brief: [threat model, intent and acceptance](../briefs/2026-09-29-toward-sandbox.md).
Approved 2026-09-29 by two independent brief reviews (the second with external
research and tool enumeration; it overturned the first's approval on two HIGH
findings, both verified against source).

## Ground truth the plan builds on

- There is no "serve mode" flag today. `zylch serve` (`engine/zylch/cli/main.py:434`)
  activates the profile like every other command; nothing downstream can tell a
  daemon from a laptop sidecar. M1 introduces one.
- Path-taking tools, enumerated: `read_document` (absolute-path shortcut and
  `_collect_search_paths`, `engine/zylch/tools/read_document_tool.py:86-127,156-158`);
  `download_attachment` (`_resolve_target_dir`, `:22-48`, model-supplied
  `target_dir`) which calls `IMAPClient.fetch_attachments`
  (`engine/zylch/email/imap_client.py:1424-1434`, unsanitised filename);
  `run_python` (two copies, `engine/zylch/tools/run_python_tool.py:76-83`,
  `engine/zylch/services/solve_tools.py:264-292`, shared `/tmp/zylch`).
  WhatsApp media is returned as bytes (`engine/zylch/whatsapp/client.py:293`),
  not written by the model; Google tools take no path. Model-supplied URLs:
  none outside `web_search` (provider side). The only engine-side outbound
  fetches are the Firebase certificate URL (`engine/zylch/rpc/firebase_auth.py:66`)
  and the configured providers.
- `DOCUMENT_PATHS`, `DOWNLOADS_DIR` are Settings keys (`engine/zylch/services/settings_schema.py:445-462`)
  written by `settings.update` (`engine/zylch/rpc/methods.py:2206`) and read
  from `os.environ` by the two tools.
- `encryption.py:_get_fernet` (`engine/zylch/utils/encryption.py:40-75`)
  reads `ENCRYPTION_KEY` from the environment, then the profile `.env`, then
  disables encryption with a warning.
- Host: `zylch-server@.service` runs as `mrcalld` with
  `EnvironmentFile=-/etc/mrcalld/env`; `/run/mrcalld` is `2750 mrcalld:caddy`
  (tmpfiles); `update-daemons.sh` (root; pulls as `mrcalld`) is run by the
  reconcile path/timer (`engine/scripts/server/README-reconcile.md`);
  `zylch-provisiond.service` runs as `mrcalld`; `join-company.sh` uses
  `sudo -u mrcalld` and globs `$MEMORY/$key.db`.
- Six live profiles on the host; four are one company (Café124). Pinned
  release `8d83193` per `docs/active-context.md`.

## M1 — Hotfix: close the tenant boundary in code

Owner: python-engine-specialist. Independent of everything after it; ships
alone. Done only when brief criteria 1 (first two clauses), 2 (first two
clauses) and 3 hold.

1. **Serve flag.** `zylch serve` sets `ZYLCH_SERVE=1` in the process
   environment after `activate_profile`; a `zylch.runtime.is_serving()` helper
   reads it. Nothing else reads the variable directly.
2. **Downloads subdirectory.** `_resolve_target_dir` returns
   `<ZYLCH_PROFILE_DIR>/downloads` when serving, ignoring `DOWNLOADS_DIR` and
   the `target_dir` argument unless the argument resolves (after `realpath`)
   inside that subdirectory; otherwise the tool returns an error naming the
   allowed root. Off serve, current behaviour is kept, but `target_dir` is
   still resolved and refused if it lands on the profile root or on `.env`,
   `zylch.db`, `whatsapp.db` anywhere.
3. **Attachment basename.** `fetch_attachments` reduces every filename to
   `os.path.basename` after header decoding, rejects empty or dot-only
   results with the `attachment_<n>` fallback, and `realpath`-checks the
   final path against `save_dir`. Applies everywhere, not only when serving.
4. **Search set.** `_collect_search_paths` returns
   `[<profile>/downloads, <profile scratch>]` when serving and ignores
   `DOCUMENT_PATHS`; the absolute-path shortcut is removed on both modes and
   replaced by "absolute path accepted only if inside the search set". The
   profile root is not in the search set (it holds `.env`).
5. **Scratch.** `/tmp/zylch` becomes `<ZYLCH_PROFILE_DIR>/scratch` when
   serving (`run_python` output dir, attachment fallback dir, `read_document`
   search). Local mode keeps `/tmp/zylch`.
6. **`run_python` refused when serving** in both copies, with an error the
   model can read ("not available on hosted engines"); the two copies are
   unified behind one function so the refusal and the scratch path live once.
   `solve_constants.py:75` loses "in a sandbox".
7. **Settings honesty.** `settings.get` marks `DOCUMENT_PATHS` and
   `DOWNLOADS_DIR` as `ignored: true` with a reason when serving;
   `settings.update` accepts them (no contract change) and the app shows the
   flag. Additive field; documented in `docs/ipc-contract.md`.

Verification (offline, in `engine/`): new tests under `tests/tools/` and
`tests/email/` — absolute path to a sibling profile `.env` refused; a
`DOCUMENT_PATHS` pointing at the profiles root yields no hit outside the
profile; a locally built `email.message` with attachments named
`/etc/passwd`, `../../x`, `.env` lands as `passwd`, `x`, `attachment_<n>`
under `downloads/`; `target_dir=<profile root>` refused; `run_python` refused
with `ZYLCH_SERVE=1` and working without it; existing `tests/tools`,
`tests/email`, `tests/rpc` green; `ruff` clean. Live, on a scratch profile on
the host before touching customers: the same four probes through `cs chat`
against the scratch daemon, plus a real self-sent mail with a traversal
filename (to the scratch mailbox, not a customer's).

Deploy: copy the reviewed files into the service checkout as
`docs/execution-plans/2026-09-17-mrcall-outbound.md` M2 did (backup dir,
byte-compare, one unit at a time, Café124 last), then commit and pin. Rollback
is the backup dir plus a unit restart. Assumption check first: ask the four
Café124 users whether they use `run_python` or absolute document paths; the
tool logs do not record paths.

Integration review before M2 starts.

## M2 — Per-profile OS identity and read-only code

Owner: python-engine-specialist with release-engineer for the units and
scripts. One systemd change, applied one profile at a time.

1. **Deploy identity.** `mrcalld` keeps the checkout and venv and becomes the
   deploy identity only: no daemon runs as it after M2. `update-daemons.sh`
   still pulls as `mrcalld`.
2. **Unit template.** `zylch-server@.service` gains `User=zylch-%i`,
   `Group=zylch-%i`, `SupplementaryGroups=` the company group (from the
   profile's key, see 5), `ProtectSystem=strict`, `ProtectHome=yes`,
   `PrivateTmp=yes`, `NoNewPrivileges=yes`, `CapabilityBoundingSet=`,
   `RestrictSUIDSGID=yes`, `ReadOnlyPaths=/home/mrcalld/mrcall-desktop`,
   `ReadWritePaths=` the profile dir and the company store dir,
   `RuntimeDirectory=mrcalld/%i` with `RuntimeDirectoryMode=2750` and group
   `caddy` so the socket stays reachable by the proxy (constraint: Caddy must
   still connect; the `path_regexp` route gains the extra directory level),
   `EnvironmentFile=/etc/mrcalld/keys/%i` (no `-`: missing key is a unit
   failure). `Environment=HOME=` the profile dir; `ZYLCH_PROFILE_DIR` and
   `MEMORY_DB_DIR` set explicitly so nothing resolves through `~`.
3. **Root helper.** `engine/scripts/server/tenant-helper.sh`, root-owned,
   mode 750, with an allowlisted verb set: `create <uid>` (user, group,
   membership in the company group, key file generated with
   `Fernet.generate_key()`, `chown` of the profile dir, downloads/scratch
   subdirs), `delete <uid>`, `join <uid> <company-group>`. Invoked by
   `update-daemons.sh` (already root) for discovered profiles without a user;
   later by provisiond through a sudoers rule limited to this script.
   provisiond itself stays `mrcalld`.
4. **Encryption.** `_get_fernet` refuses the `.env` and passthrough fallbacks
   when serving: no `ENCRYPTION_KEY` in the environment means the daemon
   exits at start with a named error. Local mode keeps today's behaviour.
   A `zylch -p <uid> rekey --from-env-key` command decrypts every
   `OAuthToken` row with the old key and re-encrypts with the profile key,
   idempotent, run by the migration runbook while the unit is stopped; the
   shared `/etc/mrcalld/env` key stays on disk until the runbook's rollback
   window closes.
5. **Store rename and mode.** `memory/store.py` derives the file name as
   `sha256(key)[:32].db`; `memory_dir()` is created `2770 mrcalld:<company>`
   per company subdirectory (`<MEMORY_DB_DIR>/<company-group>/`), never
   listed by `store_exists`, `memory.join` or `join-company.sh table` (which
   derives the name the same way through `zylch memory-status`). Migration
   renames each existing store while its daemons are stopped. The two-user
   WAL test precedes Café124: two scratch daemons under two users write the
   same store concurrently, `-wal`/`-shm` stay group-writable, a third user
   is refused.
6. **Scripts.** `update-daemons.sh` calls the helper for new profiles and
   never `chown -R`s a profile to `mrcalld` again; `join-company.sh` runs the
   join as the profile's user and updates group membership through the
   helper.
7. **Offboarding.** `tenant-helper.sh delete <uid>` stops the unit, runs
   `zylch -p <uid> memory-offboard` (deletes the profile's owned rule rows,
   `blob_owned_rules` in `scope.py`; deletes the store only when the profile
   was the company's last key holder, checked through the company group's
   membership), removes the profile dir, key file, user and group membership.
8. **Runbook** `docs/remote-backend.md` gains the migration sequence per
   profile (stop, helper create, rekey, store rename if first of its company,
   start, verify) and the rollback (stop, restore ownership from the recorded
   `stat` output, restore old unit, start).

Verification: unit tests for the store name derivation, the rekey command
(round-trip on a fixture DB), the offboarding row selection and the encryption
refusal; `systemd-analyze verify` and `security` on the rendered unit; on the
host, two scratch profiles in one company plus one in another: brief criteria
1 (all clauses), 2 (all clauses), 4, 5, 7 executed as named commands and
recorded here. Then Café124's four, one per day, each verified against
criterion 1 clause three before the next.

Integration review before M3.

## M3 — Egress bound per daemon

Owner: release-engineer. Own migration step with its own rollback, after M2
is stable on all six profiles.

1. Enumerate endpoints from code and configuration: IMAP/SMTP hosts per
   profile `.env`, WhatsApp (`web.whatsapp.com`, `*.whatsapp.net`), StarChat
   and `MRCALL_PROXY_URL`, Anthropic, OpenRouter, Google certificate and
   OAuth hosts, Pipedrive when configured.
2. Mechanism: a host-local allowlisting forward proxy (name-based; IP rules do
   not fit mail hosts) with one allowlist file per unit under
   `/etc/mrcalld/egress/<uid>`, generated from the profile `.env` by the
   helper; daemons get `HTTPS_PROXY`/`HTTP_PROXY`, and for IMAP/SMTP/WhatsApp
   (not HTTP) `IPAddressDeny=any` plus `IPAddressAllow=` for the resolved
   hosts refreshed by a timer, accepting that this part is IP-based.
   The allowlist file is the observable set (brief criterion 6).
3. Rollout one profile at a time with mail sync watched for one full cycle
   before the next; rollback removes the proxy variables and the IP rules for
   that unit only.

Verification: from a scratch daemon, `curl` to an outside host fails, IMAP
sync completes, a WhatsApp message arrives, an LLM call succeeds; criterion 6
recorded.

## M4 — Docs and plan reconciliation

Owner: primary session. `docs/remote-backend.md` (multi-tenancy statement,
identity model, helper, egress, migration runbook; remove the WhatsApp
caveat), `AGENTS.md` hosting paragraph, `docs/ipc-contract.md` (settings
`ignored` field), `docs/active-context.md`, this plan's status. Criterion 8.

## Final review

After M1–M4 each pass integration review: one separate end-to-end review
through the user path — a signed-in desktop client on a hosted profile reads
mail, downloads an attachment, searches a document, and a second client on a
sibling profile cannot see any of it — with the recorded evidence for all
eight criteria.

## Risks and rollback

- **Live customers.** Every host step runs on scratch profiles first, then
  Café124 one per day, operator present, backup and `stat` record before.
- **Caddy reachability** after `RuntimeDirectory` changes: tested on the
  scratch unit with the route change before any customer unit.
- **Encryption refusal** taking a customer down: the rekey is verified with
  `zylch -p <uid> memory-status` and one decrypted token read while stopped,
  before the unit starts under the new key.
- **Egress allowlist wrong**: M3 is separate and per unit; mail sync is the
  canary.
- **Local engine regression** from M1: CI `tests/tools`, `tests/email`
  and the app's offline browser checks must stay green; the only local
  changes are the basename rule and the profile-root refusal.

## Parked (from the brief, recorded here)

Self-serve provisioning (own brief; uses the helper from M2.3); operations
floor (backup/restore, pinned rollout, alerting); data-processor obligations
(CTO); bubblewrap for `run_python` on hosts; VM per company; send/credential
separation and shared-memory poisoning; native Mac/Windows engine hardening.
