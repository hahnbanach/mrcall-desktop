---
status: active
---

# Toward a sandbox: execution plan

<!-- doc-scope:start -->
Scope: milestones, ownership, verification and rollback for the approved
isolation brief. Mechanisms are chosen here; properties come from the brief.
<!-- doc-scope:end -->

Brief: [threat model, intent and acceptance](../briefs/2026-09-29-toward-sandbox.md),
approved 2026-09-29 by two independent reviews. This plan was revised once on
two independent plan reviews (conformance; adversarial mechanisms), whose
findings are folded in below.

## Facts the brief does not state

- There is no serve flag: `zylch serve` (`engine/zylch/cli/main.py:434`)
  activates the profile like any command. Profile resolution is
  `~/.zylch/profiles` computed at import (`engine/zylch/cli/profiles.py:16-17`),
  with no environment override; `whatsapp.db`, the fastembed cache and
  `memory_dir()` also resolve through `~`.
- Path-taking code, enumerated: `read_document` and `download_attachment`
  exist twice — the tool classes (`engine/zylch/tools/`) and the solve copies
  (`engine/zylch/services/solve_tools.py:209-245,616-650`) used by the task
  executor; `run_python` twice likewise. `fetch_attachments`
  (`engine/zylch/email/imap_client.py:1424-1434`) writes the sender's
  filename. `read_document` also has a relative-path fallback
  (`read_document_tool.py:181`, cwd `/home/mrcalld`). `send_email` takes
  `attachment_paths` normalised to any absolute path
  (`engine/zylch/tools/gmail_tools.py:102-110`, opened at
  `imap_client.py:1612`): a model-supplied read path that is approval-gated,
  which the brief does not count. WhatsApp media is returned as bytes;
  Google tools take no path; no model-supplied URL is fetched engine-side.
- `decrypt` fails open (`engine/zylch/utils/encryption.py:129-135`);
  provider credentials are an outer Fernet blob whose JSON carries inner
  `encrypted:` fields; nothing in the company store is encrypted.
- `open_company_store` creates a store when the key source is vouched
  (`engine/zylch/storage/database.py:151-154`): a daemon that cannot find its
  store under a new name would silently start an empty one.
- Host: units and tmpfiles as `docs/remote-backend.md` B.1 installs them;
  `update-daemons.sh` restarts every daemon when the checkout changes and is
  run by the reconcile path/timer; `zylch-provisiond.service` runs as
  `mrcalld`. Seven live daemons, four of them one company (Café124). The
  four Café124 daemons run pinned releases: their drop-ins set `PYTHONPATH`
  (and, for production@, `ExecStart`) to a directory under
  `/home/mrcalld/releases`. The other three run the service checkout, which
  the nightly `zylch-reconcile.timer` pulls from origin/main, restarting
  every daemon on any new commit.

## M1 — Hotfix: close the tenant boundary in code

Owner: python-engine-specialist. Ships alone. Done only when brief criteria 1
(first two clauses), 2 (first two clauses) and 3 hold.

1. **Serve flag.** `zylch serve` sets a module variable
   (`zylch.runtime.serving = True`) *before* `activate_profile`;
   `is_serving()` reads the variable, never the environment.
   `settings.update` refuses `ZYLCH_*` keys.
2. **One confinement, four callers.** A `zylch.tools.paths` module owns:
   `downloads_dir()` (`<profile>/downloads` when serving, else today's
   resolution), `scratch_dir()` (`<profile>/scratch` when serving, else
   `/tmp/zylch`), `search_paths()` (when serving: downloads and scratch only,
   `DOCUMENT_PATHS` ignored; else today's defaults), `confine(path, root)`
   (`realpath` of the final *file*, must be inside `root`, else a named
   error). The tool classes and the solve copies of `read_document` and
   `download_attachment` all call it, and `send_email` confines every
   `attachment_paths` entry into the search set; the two `run_python` copies
   become one function. The absolute-path shortcut and the relative-path fallback are
   replaced by "accepted only if inside the search set", in both modes.
3. **Attachment basename** in `fetch_attachments`, after header decoding
   (`sub/dir.pdf` becomes `dir.pdf`; non-ASCII is preserved), empty or
   dot-only names get `attachment_<n>`, then `confine` against `save_dir`.
   Everywhere, not only when serving.
4. **`target_dir`** must `confine` into `downloads_dir()` when serving. Off
   serve, a deliberate extension beyond the brief's local change set: the
   profile root and `.env`, `zylch.db`, `whatsapp.db` are refused as targets
   anywhere. Named here so the integration reviewer measures against it.
5. **`run_python` refused when serving** with an error the model can read;
   `solve_constants.py:75` loses "in a sandbox", and every prompt string that
   names `/tmp/zylch/attachments` (`solve_constants.py:64,147,218`,
   `run_python_tool.py:36`) says "the downloads folder" instead, so the model
   does not pass a path that is refused.
6. **Settings honesty.** `settings.get` gains a top-level sibling
   `ignored: {KEY: reason}` next to `values` when serving; `values` keeps its
   `Record<string,string>` shape, so existing readers (`Settings.tsx:76-80`)
   are untouched. Documented in `docs/ipc-contract.md` as additive. App
   display of the flag is a later app change, not part of M1.

Verification (offline, `engine/`): tests under `tests/tools/` and
`tests/email/` — sibling-profile `.env` by absolute path refused through
both the tool class and the solve copy; `DOCUMENT_PATHS` at the profiles root
yields nothing outside the profile; `send_email` with a sibling-profile
`.env` in `attachment_paths` refused before any SMTP call; a locally built
message with attachments
named `/etc/passwd`, `../../x`, `.env`, `sub/dir.pdf` lands as `passwd`, `x`,
`.env`, `dir.pdf` under `downloads/` (a dotfile name stays itself inside
`downloads/`, never the profile root; only empty or dot-only names become
`attachment_<n>`); `target_dir=<profile root>`
refused; `run_python` refused with the flag and working without; `ZYLCH_SERVE`
refused by `settings.update`; existing `tests/tools`, `tests/email`,
`tests/rpc` green; `ruff` clean. Live on a scratch profile: the same probes
through `cs chat`, plus one self-sent mail to the scratch mailbox with a
traversal filename.

Deploy as `2026-09-17-mrcall-outbound.md` M2 did (backup dir, byte-compare,
one unit at a time, Café124 last); rollback is the backup plus a restart.
Before deploy the operator asks the four Café124 users whether they rely on
`run_python` or absolute document paths (logs do not record paths).

Integration review before M2.

### M1 record (2026-09-29)

Implemented on `claude/muse-architecture-comparison-i8x8g1` (`db23a28`,
`c0fa401`). `zylch.runtime` holds the serve flag; `zylch.utils.safe_paths`
(confine, basename) is dependency-free so `zylch.email` can use it, and
`zylch.tools.paths` owns the folder policy for the tool classes, the solve
copies and the draft tools' attachment paths; `zylch.tools.python_exec` is
the single `run_python`. `save_attachments()` was extracted from
`fetch_attachments` so the basename rule is testable from a local message.
Two local changes beyond the DoD list, deliberate: the solve copies now
honour `target_dir` and use the same downloads folder and search set as
the tool classes (plan §M1.2 unification; `read_document` still searches
the old `/tmp/zylch*` locations locally), and `test_phase_a_registration`'s
smoke test sets `DOCUMENT_PATHS` because the absolute-path shortcut is gone.
Verification: 31 new tests (`tests/tools/test_path_confinement.py`,
`tests/email/test_attachment_filenames.py`,
`tests/rpc/test_settings_hosted_ignored.py`), including a `glob` `..`
traversal that really reaches the sibling file and is refused by
`confine`, and a non-dotfile secret (glob's `*` never matches `.env`, so a
dotfile-only test is vacuous). `tests/tools tests/email tests/rpc
tests/services` + the CI memory-boundary gate: 606 passed; the two
failures (`test_contract_boundaries`, `test_memory_readonly`) reproduce on
the parent commit and are not M1's. Integration review: REVISE on three
small items (unused import, hosted prompt wording, the vacuous dotfile
test), repaired; APPROVED at `c0fa401` with no bypass found. "Ruff clean"
for M1 means the F-family/E9 check on the touched files: the venv's ruff
reports hundreds of pre-existing findings in `imap_client.py` that M1 did
not add. Left for later:
`settings_schema` help text for `DOWNLOADS_DIR` still says `~/Downloads`
(app-side display change, parked with the `ignored` flag);
`fetch_attachments`' default `save_dir` string is unused by both callers.
Live probe on a scratch host (2026-09-29, this session's Linux container,
root, no systemd): the real `zylch -p scratchA serve --unix` daemon with a
sibling `scratchB` holding secrets; only Firebase token verification was
replaced (no real token available). Over the WebSocket as A's client:
`settings.get` carries `ignored` for `DOCUMENT_PATHS`/`DOWNLOADS_DIR`;
`settings.update DOCUMENT_PATHS=<profiles root>` is accepted and stored,
the second `settings.get` still marks it ignored; `ZYLCH_SERVE` refused as
unknown; B's token on A's socket gets 403. Inside the daemon process,
through `ZylchAIAgent._execute_tools` with an approving callback (the
model's exact path): `read_document` on B's `.env` and `secrets.txt` by
absolute path refused ("outside the allowed folders"), by name and by
`sub/../../../scratchB/...` not found, A's own download read;
`run_python` refused after approval; `resolve_download_target` refuses
B, A's root, `~`, `/tmp` and accepts `downloads/sub`. B's files unchanged
after the run. Not probed live: `download_attachment` end to end (needs an
IMAP mailbox; covered by `save_attachments` tests on a local message).
Deployed 2026-09-30 to all seven daemons.
- The three unpinned ones run the service checkout at `ee4df02`: M1, the M2
  host-independent code, the logrotate stanza with `su` and the WhatsApp fix
  below.
- The four Café124 daemons get M1 as backports onto the code they already
  ran: `hotfix/m1-wa-on-k3` (`f342c5c` = 8d83193 + M1 + the WhatsApp fix) for
  C06xH, YZNI2 and ZwpLe, and `hotfix/m1-wa-on-voice` (`53df502` = voice
  release 8fb21d3 + the same) for production@. The voice-line base is not on
  origin, so `53df502` exists only in the host's development repository.
- Each backport is a read-only tree `/home/mrcalld/releases/<release>-m1-<sha>`
  selected by the `Environment=PYTHONPATH=` line of the unit's pinning
  drop-in. Units were switched one at a time by a script that verifies and
  rolls back; for production@ it is gated on the call ledger and never
  restarts with a call in flight.
- Integration review of both backports and of the switch: APPROVED.
  Rollback: `/etc/mrcalld/rollback-toward-sandbox-20260930/ROLLBACK.txt`.
- Post-switch evidence per unit: the process `PYTHONPATH` and the import
  resolve to the release, `serving JSON-RPC` with no error, socket
  `660 mrcalld:caddy`, Caddy 401 without a token. production@ also answers
  `/healthz` `calls_available: true` locally and through the tunnel, and
  unsigned Vonage answer/event and OpenAI webhooks get 401/401/400. A host
  probe of each release with the unit's own interpreter passed 17/17.
- The Café124 users were not asked about `run_python` or absolute paths:
  DEBUG engine logs record every tool input (`full_input=`), and the four
  profiles' full history has no `run_python` call and no absolute read path
  outside the tool's own download folder.
- Extension beyond the enumeration above: `_download_audio` named WhatsApp
  voice notes `wa_media/<message id>.ogg` with the sender-chosen id. The id
  now names the file only when it matches `[A-Za-z0-9_-]{1,128}`, otherwise
  `wa_<sha256[:32]>`, and the path is confined to `wa_media` in every mode
  (`ee4df02`). Production had no unsafe id among 22,464 stored messages.

## M2 — Per-profile OS identity and read-only code

Owner: python-engine-specialist (engine changes) and release-engineer (units,
helper, runbook). Two separate host operations: **2a** store rename per
company, all its daemons stopped together; **2b** identity, one profile at a
time. Sign-up (own brief) opens only after 2b is deployed on all six.

1. **Profiles root override.** `ZYLCH_HOME` honoured by `profiles.py`,
   `cli/utils.py`, `config.py`, `memory/store.py`, the WhatsApp paths and the
   embeddings cache, so nothing resolves through `~`. The unit sets
   `ZYLCH_HOME=/home/mrcalld/.zylch` and `HOME=<profile dir>` (writable,
   private). Verified with `systemd-run` on the scratch unit first.
2. **Names.** Unix user `mc-<sha256(uid)[:12]>`, company group
   `mc-c-<sha256(key)[:12]>`, store file `<sha256(key)[:32]>.db` under
   `<MEMORY_DB_DIR>/mc-c-<sha256(key)[:12]>/`: all lowercase, under 32
   chars, and none reversible to the uid or the key (the key never appears
   in `/etc/group`, `ps` or `ls`). `zylch memory-status` prints the derived
   names; `join-company.sh table` reports file size only and never opens a
   store as `mrcalld`.
3. **Unit template + drop-in.** The template keeps what is common:
   `ProtectSystem=strict`, `ProtectHome=tmpfs`,
   `BindReadOnlyPaths=/home/mrcalld/mrcall-desktop`, `PrivateTmp=yes`,
   `NoNewPrivileges=yes`, `CapabilityBoundingSet=`, `RestrictSUIDSGID=yes`,
   `PYTHONDONTWRITEBYTECODE=1`, `EnvironmentFile=/etc/mrcalld/keys/%i`
   (root-only 0400, read by systemd before dropping privileges; no `-`, so a
   missing key fails the unit), `ExecStart` with socket
   `/run/mrcalld/%i/ws.sock` and `ReadWritePaths=/run/mrcalld/%i` — under
   `ProtectSystem=strict` `/run` is read-only and the bind would fail with
   EROFS; `ExecStopPost` removes the new path. Per-instance values a
   template cannot derive go in a helper-written drop-in
   `zylch-server@<uid>.service.d/tenant.conf`: `User=`, `Group=`,
   `SupplementaryGroups=<company group>`, and the profile dir and the
   company store dir under both `BindPaths=` and `ReadWritePaths=`, so
   writability does not rest on mount ordering. A tmpfiles fragment per uid,
   `d /run/mrcalld/<uid> 2750 <user> caddy`, keeps the socket reachable, and
   the parent `/run/mrcalld` becomes `0751 mrcalld caddy` so a tenant user
   can traverse it (today's `2750` would refuse);
   Caddy's `path_regexp` maps `/ws/<uid>` to `/run/mrcalld/<uid>/ws.sock`.
   `systemctl --version` is recorded in the runbook (nested
   `RuntimeDirectory` not used; `RestrictSUIDSGID` needs v242+).
4. **Root helper** `engine/scripts/server/tenant-helper.sh`, installed by
   `update-daemons.sh` to `/usr/local/sbin/mrcall-tenant` with
   `install -m 750` (as it installs units today); the checkout copy is never
   executed and the sudoers rule names the installed path only — the checkout
   is `mrcalld`-writable and a rule on it would be a root escalation from the
   network-facing provisiond. Verbs `create <uid>`, `join <uid>
   <company-group>`, `unjoin <uid> <company-group>`, `delete <uid>`,
   validating `<uid>` with the same regex as `provisiond/handler.py:105`
   and rejecting `.`/`..`; idempotent, so a reconcile trigger on a
   half-written profile converges. `create` makes the user, key file
   (`Fernet.generate_key()`), drop-in, tmpfiles fragment, downloads/scratch
   subdirs, `chown` of the profile tree, and — from the profile's
   `MEMORY_KEY` — the company group and its store directory
   (`2770 mrcalld:<group>`) when absent, because a sandboxed daemon cannot
   create them (`store.py:123` makes `0700` under a read-only parent) and a
   new customer would otherwise start with memory unavailable; it records
   uid→user in a root-only table used by `delete`. Invoked by `update-daemons.sh` (root) for
   discovered profiles without a user; later by provisiond through a sudoers
   rule limited to this script. provisiond stays `mrcalld`, which becomes the
   deploy identity only.
5. **Dual-name store, then rename (2a).** `store.py` opens the legacy
   `<key>.db` when the derived name is absent and never creates while the
   legacy exists; this ships before any rename. Local engines keep the
   legacy name indefinitely, by design; inside the sandbox `profiles/` holds
   only the bound uid, so `select_profile` always receives `-p` (the unit
   does). Then, per company, all its
   daemons stopped in one window: rename the store into its subdirectory,
   set the directory `2770 mrcalld:<group>`, start all. Rollback is the
   reverse rename in the same all-stopped window. Café124's four units go
   together, a few minutes. Runtime `memory.join` returns "operator action"
   when serving; `join-company.sh` is the only hosted join path: stop,
   helper `join` adds the *new* company group while keeping the old (the join
   reads the source store and `join_recover` reopens it afterwards,
   `engine/zylch/memory/join_recover.py:262-268`), run the join as the tenant
   user (`sudo -u <user>`, never `mrcalld` or root, so the store's
   `-wal`/`-shm` keep tenant ownership), start, and only after `finish` does
   helper `unjoin` remove the old group. Group membership and `.env` key
   therefore have one writer; `memory-status` cross-checks them, tolerating
   the interim two-group state, and the runbook runs it after every join.
   For the tenant user to reach the store outside the unit sandbox,
   `/home/mrcalld`, `.zylch`, `.zylch/memory` and `.zylch/profiles` are
   `0711` (traverse, no list).
6. **Encryption (2b).** `_get_fernet` refuses the `.env` and passthrough
   fallbacks when serving: no `ENCRYPTION_KEY` in the environment exits at
   start with a named error. `zylch -p <uid> rekey --from <oldkey-file> --to
   <newkey-file>` constructs two `Fernet` instances directly, and for each
   provider row (`firebase` refresh token, `google_calendar`, any other via
   `save_provider_credentials`) first tries the new key (already done → skip,
   so it is idempotent), else decrypts outer and inner `encrypted:` fields
   with the old key and re-encrypts with the new; `--verify` decrypts every
   row under the new key and fails loudly on any miss; `--from`/`--to`
   swapped is the rollback. Run while the unit is stopped and before the
   helper's `chown` (M2.7), and the runbook `stat`s `zylch.db-wal`/`-shm`
   afterwards: the sidecars must end up owned by the unit user. Plaintext
   rows from hosts that ran without a key (`is_encrypted()` false,
   `encryption.py:150`) are encrypted with the new key and counted by
   `--verify`. When serving, `decrypt` raises instead of returning
   ciphertext, so a wrong or rotated key file fails loudly rather than
   yielding garbage refresh tokens; because storage callers catch and return
   `None` (`engine/zylch/storage/storage.py:2424-2427`), the daemon also
   runs a one-row decrypt self-check at start and fails the unit on a miss. The shared `/etc/mrcalld/env` key stays
   until every profile's rollback window has closed.
7. **Identity migration (2b), one profile per day.** Stop, `stat -c` record
   of the tree, `rekey --verify` (root), *then* helper `create` — the
   `chown` comes last so the `-wal`/`-shm` files root's open left behind are
   re-owned, otherwise the daemon hits the `readonly database` trap
   `docs/remote-backend.md` records — start, then check: criterion 1 clause
   three, criterion 5, and `-wal`/`-shm` owner equals the unit user for
   `zylch.db` and the company store. Rollback: stop, `rekey` back, remove
   drop-in and fragment, restore ownership from the record including
   `-wal`/`-shm`, start under the old template.
8. **Offboarding.** `tenant-helper.sh delete <uid>`: stop, `zylch -p <uid>
   memory-offboard` run as the profile user (`sudo -u`), never as root, so
   the company store's `-wal`/`-shm` keep the group ownership the other
   members need (deletes the profile's `blob_owned_rules` rows; deletes the
   store only when the profile's group has no other member, after the
   `memory-status` cross-check), then remove profile dir, key, drop-in,
   fragment, user, table row.
9. **Scripts.** `update-daemons.sh` calls the helper for new profiles and no
   longer `chown -R`s to `mrcalld`; `join-company.sh` as in 5, passing
   `ZYLCH_HOME` and `MEMORY_DB_DIR` on its `sudo -u <tenant> env` line, since
   outside the unit nothing else sets them.

Verification: unit tests for name derivation, dual-name open (legacy present
→ opened, never created), `rekey` round trip on a fixture DB including nested
fields and the idempotence case, offboarding row selection, encryption
refusal; `systemd-analyze verify` and `security` on template plus drop-in;
`systemd-run` start of the scratch unit under `ProtectHome=tmpfs` proving
the venv and profile are visible; on the host, two scratch profiles in one
company plus one in another: brief criteria 1 (all clauses), 2 (all
clauses), 4 (two users writing concurrently, `-wal`/`-shm` group-writable,
third user refused, `memory.join` finds the renamed store), 5, 7, and Caddy
reaching the new socket path. Then 2a for Café124, then 2b one per day.

Integration review before M3.

### M2 record — host-independent part (2026-09-29)

Implemented on `claude/muse-architecture-comparison-i8x8g1` (`ecde110`,
`3ce1928`, `d15137d`) from a container without systemd, so everything that
needs a real host is listed at the end. Engine: `zylch.home.zylch_home()`
(`ZYLCH_HOME`) behind every former `~/.zylch` resolution;
`zylch.memory.tenant_names` (user `mc-<sha256(uid)[:12]>`, group
`mc-c-<sha256(key)[:12]>`, store `<sha256(key)[:32]>.db`); `store.py`
dual-name rule (derived if present, else legacy if present; a new store is
derived only when serving — local engines keep the legacy name by design),
`relocate_store` moving `.db`, sidecars and the three lock files, refusing
when both exist; `memory.join` RPC returns `operator_action` when serving;
hosted encryption refuses the `.env` and passthrough fallbacks, `decrypt`
raises for a value that looks encrypted, `serve` pins the unit's
`ENCRYPTION_KEY` over any `.env` one and runs a start-time self-check over
every `oauth_tokens` row (a deliberate tightening: `Storage.get_instance()`
is now fatal before `serve_ws`, where warm-up was best-effort);
`zylch rekey --from-key-file --to-key-file [--verify|--verify-only]`
(two `Fernet` instances, idempotent, nested `encrypted:` fields, plaintext
rows encrypted, bare-string outer preserved, swap the files to roll back);
`zylch memory-offboard` delegating to the owner's reset (owned rule rows
only on a shared store) with `--last-holder` deleting the file;
`zylch memory-names` (derived names; the legacy path is never printed
because it is the key) and `zylch memory-relocate-store` (2a). Deviations
from the plan text: names come from `memory-names`, not `memory-status`;
the group/`.env` cross-check is host-side work.

Host artifacts (not yet executed anywhere): `tenant-helper.sh`, installed
by `update-daemons.sh` to `/usr/local/sbin/mrcall-tenant`, verbs
`create|join|unjoin|delete|names|list`; the unit template is
**transitional** (unchanged behaviour for an unmigrated instance) and the
helper's per-instance drop-in carries the whole per-tenant set: identity,
data-root environment, key file (`EnvironmentFile=` reset, no `-`),
`ProtectSystem=strict`, `ProtectHome=tmpfs` with `BindReadOnlyPaths` for
the checkout and the pre-warmed embedding cache, `BindPaths`/`ReadWritePaths`
for the profile, the company store dir and `/run/mrcalld/<uid>`, the
socket at `/run/mrcalld/<uid>/ws.sock`. `update-daemons.sh` re-applies
`create` only for uids in the root-only tenants table, so a pull never
migrates a running customer; migration is the operator's explicit `create`.
Caddy tries the new socket path then the flat one during the window
(superseded by the scratch VM record below: one static upstream plus a
flat-name link).
`/run/mrcalld` is `2751` (setgid kept for provisiond's flat socket). Every
tenant run outside the unit goes through `umask 007`. `create` refuses
while the company's legacy store exists (2a first). `delete` derives
last-holder from group membership and removes the empty group and dir.
logrotate keeps `su mrcalld mrcalld` (the VPS session's `068b520`): the
unmigrated profile dirs are `0770 mrcalld`, and root's logrotate skips
their logs without it — which means the shared stanza cannot rotate a
*migrated* profile's log; a per-tenant stanza (or a `su` per profile) is a
host item for 2b, listed below. provisiond's status treats the drop-in as
proof a migrated profile exists.

Reviews: A (plan conformance + Python) REVISE → APPROVED at `3ce1928`
(legacy path echoed; `.env` key beating the unit's; bare-string rekey;
lock files; leftovers — all repaired). B (host scripts, adversarial)
REVISE at `ecde110` with a CRITICAL — the first version ran `create` for
every profile on every reconcile under a template that dropped `User=`,
which would have migrated and broken all six customers on the first
automatic pull — plus setgid loss on `/run/mrcalld`, `sudo` umask making
stores read-only for the other group members, 2b-before-2a forking the
store, the embedding cache unwritable in the sandbox, tenants table
truncation, operator-asserted last-holder, provisiond/logrotate blind to
tenant-owned dirs; all repaired at `d15137d`. B's second pass found the
Caddy `first` policy failing over only with passive health checks
(without `fail_duration` the reload would have 502'd every unmigrated
customer), the bound embedding cache unreadable and unwarmed, one bad
tenant row aborting the whole reconcile, the offboard predicate chosen by
row presence instead of the helper's membership fact, the runbook window
exposed to the reconcile timer, and no rollback verb; repaired (health
checks, `chmod -R go=rX` on the cache + warm-up step, continue on failure,
`sole_holder` selector on `delete_all_blobs`, reconcile lock held by
`join-company.sh` and the runbook, `MRCALL_JOIN_KEY` 2a guard on join,
symlink guard on subdirs, provisiond 409 on a drop-in, `mrcall-tenant
unmigrate`). B: APPROVED at `54c503f` for the artifacts as code; the
scratch-unit probe stays the gate before any customer.
Verification here: 24 new tests (`tests/memory/test_tenant_store_names.py`,
`tests/storage/test_rekey_and_encryption.py`, `tests/memory/test_offboard.py`),
the writer-inventory and retention guards updated for the offboard call
site, full regression 1391 passed (the two known pre-existing failures
only), `systemd-analyze verify` on the rendered drop-in (only the absent
binary reported) and `security` exposure 4.4.

**Left for the host session (VM scratch first):** unit start under the
drop-in (`systemd-run` proof), Caddy reaching the new socket, the two-user
WAL test on one store, criteria 1 (all clauses), 2, 4, 5, 7; log rotation
for a migrated profile (the shared stanza's `su mrcalld` cannot write into a
tenant-owned dir); on every host, `/etc/systemd`, `/etc/systemd/system`,
`systemd-networkd.service.d` and `/etc/qemu` at `0755` before any tenant
user exists (the provider image ships them `0777`, which lets any local user
plant a unit drop-in that root runs; done on desktop.mrcall.ai); then 2a for
Café124 in one all-stopped window, then 2b one profile per day. Runbook
M2.7 as the scripts now are, per profile U, after its company's 2a:
0. once per host: warm the embedding cache as `mrcalld`
   (`ZYLCH_HOME=/home/mrcalld/.zylch`, `umask 022`, one embedding), and
   confirm `find /home/mrcalld/mrcall-desktop ! -perm -o+r` is empty;
1. `exec 9>/run/mrcalld/reconcile.lock; flock 9` — held until step 7;
2. `systemctl stop zylch-server@U`; `stat -c '%U:%G %a %n'` record of the
   tree and the company store; backup;
3. `grep '^ENCRYPTION_KEY=' /etc/mrcalld/env > /root/oldkey.U; chmod 0400`;
4. `mrcall-tenant create U` (mints `/etc/mrcalld/keys/U`, writes drop-in
   and fragment, first chown);
5. as root: `env HOME=/home/mrcalld/.zylch/profiles/U
   ZYLCH_HOME=/home/mrcalld/.zylch MEMORY_DB_DIR=/home/mrcalld/.zylch/memory
   $VENV/bin/zylch -p U rekey --from-key-file /root/oldkey.U
   --to-key-file /etc/mrcalld/keys/U --verify`;
6. `mrcall-tenant create U` again (idempotent; re-owns `profile.lock`,
   `zylch.db-wal/-shm`, `zylch.log` root created); `stat` shows `mc-…` on
   every file under the profile and on the store's sidecars;
7. `systemctl start`; release the lock; `memory-status` as the tenant;
   criteria 1/5; `wss://…/ws/U` through Caddy.
Rollback (same lock): stop; `rekey` with the two files swapped (root);
`mrcall-tenant unmigrate U` (`tenant.conf`, fragment, run dir, ownership
back to `mrcalld`, table row; keeps user, key file and the operator's own
drop-ins); start under the
transitional template, whose flat socket Caddy still serves.
Scratch-unit probe list, before any customer: unit start under the
drop-in; Caddy reaching `/run/mrcalld/<uid>/ws.sock`; fastembed loading
from the read-only cache without writing; the two-user WAL test.

### M2 record — scratch VM probe (2026-09-30)

Host: Ubuntu 22.04.5, systemd 249, Caddy 2.11.4, 2 vCPU / 2 GB, root, no
customers. B.1 as written, with these deviations: the distro ships Python
3.10 and the engine needs ≥3.11, so the venv is built with `python3.11`
from the deadsnakes PPA (3.11.16) — **check the VPS's `python3 --version`
before any venv rebuild there**; Caddy serves `http://localhost:8080`, not
the real hostname; the VM checkout follows a local bundle of branch
`claude/m2-scratch-probe` (no GitHub credentials on the VM); provisiond and
the `zylch-reconcile.path`/`.timer` units were **not** installed, so the
reconcile lock against the path unit and provisiond's socket and 409
behaviour under `/run/mrcalld 2751` were not exercised. Scratch profiles
were built as production has them (created and seeded by `mrcalld` under
the shared `/etc/mrcalld/env` key, legacy `<key>.db` stores, a second
profile joined to the first as `mrcalld`, started by `update-daemons.sh`
on the transitional template): company A `scrA1…1`+`scrA2…2`
(`mc-c-9ebd4ee0176e`), company B `scrB1…1` (`mc-c-c90a4f1c7b19`), company D
`scrD1…1`+`scrD2…2` (`mc-c-2734b77bf2a1`, the mixed-state company), and
`scrC1…1` (own company, joined to A, deleted). Command log with outputs:
`/root/m2-probe.log` on the VM (a few set-up commands were not tee'd; the
record says which).

**Defects found and fixed on the branch** (1, 2 and 6 would each have taken
Café124 down or lost its memory):

1. **Caddy dual upstream shared its health state across uids**
   (`657deae`, `6e28123`). Passive health is keyed by the templated
   upstream: one unauthenticated request to `/ws/<missing uid>` gave live
   A1 and B1 503. A `file` matcher does not match a Unix socket. Now: Caddy
   keeps the pre-M2 single static upstream `/run/mrcalld/{uid}.sock`, and
   the tenant's tmpfiles fragment adds `L+ /run/mrcalld/<uid>.sock ->
   <uid>/ws.sock`; `unmigrate`/`delete` remove it; `check_uid` refuses
   `provisiond`. **The installed Caddyfile needs no change for M2** — keep
   the pre-M2 rule (do not install the dual-upstream version of `54c503f`).
2. **Relocated store unreadable by tenants** (`657deae`, `30f2eef`): 2a
   moves `0640 mrcalld:mrcalld` files into the setgid dir, whose group does
   not reach existing files; the first tenant daemon died with EACCES on
   `.db.migrate.lock`. Now the 2a verb `mrcall-tenant store` chgrps them to
   the company group with `g+rw` **as `mrcalld`** (owned regular files with
   one link only — review A showed a root chgrp in a tenant-writable dir
   could be raced onto `/etc/passwd`), and puts `mrcalld` in the group so
   an unmigrated daemon can write sidecars a tenant created. Only `store`
   adds `mrcalld`; the reconcile no longer re-adds it (R8).
3. **Tenant CLI outside the unit could not resolve `-p`** (`2a8e805`,
   `30f2eef`): `profiles/` is traverse-only for tenants, so
   `join-company.sh` and the offboard in `delete` died with EACCES.
   `select_profile` now lists first and, only on `PermissionError`, checks
   an explicit name directly (exact on the case-sensitive host; a
   case-insensitive local disk always lists). Tests in
   `tests/utils/test_select_profile_unlistable.py`.
4. **`delete` continued after a failed offboard** (`2a8e805`, `30f2eef`).
   It now holds the reconcile lock, writes a root `.deleting` marker that
   `update-daemons.sh` skips, and stops before deleting anything.
5. **2a had no rollback, and orphan stores had no disposition**
   (`30f2eef`): verbs `mrcall-tenant unstore <uid>` and
   `mrcall-tenant orphans [--archive]`.
6. **`delete` decided "last holder" from group membership only**
   (`30f2eef`): an unmigrated profile runs as `mrcalld` and is in no
   group, so deleting a migrated Café124 profile mid-migration would have
   deleted the store the other three use. It now also requires that no
   other profile's `.env` holds the key (D6).

**Results.** Unless marked, on final code `30f2eef`. Results obtained on
earlier commits are marked with the commit and why they still hold.

- **Unit start under the drop-in, without the probe harness** (R1, R5,
  D5): tenants active as `mc-<sha12(uid)>`, socket
  `srw-rw---- <tenant> caddy` in `/run/mrcalld/<uid>/`,
  `systemd-analyze verify` clean, `security` 4.4. Reboot simulated
  (`rm -rf /run/mrcalld; systemd-tmpfiles --create`; start): dirs and links
  recreated, all 401 (on `6e28123`; later commits do not touch tmpfiles).
  `update-daemons.sh` with three tenants in the table and one unmigrated
  profile re-applies `create`, restarts nothing, keeps users (R5 redo).
- **Caddy** (P1 on `6e28123`, unchanged since): migrated uids 401 without
  a token, 403 with another uid's token, a missing uid 502 with no effect
  on the others; after the rollback, the unmigrated flat socket 401.
- **fastembed** (P2 on `6e28123`; later fixes do not touch the cache or
  the drop-in): as A1 in its sandbox the model loaded from the read-only
  bound cache (dim 384); files newer than a marker: 0.
- **Criterion 1** (on `6e28123`; the later `select_profile` change only
  adds a fallback on `PermissionError`, which the daemon never hits since
  its sandbox lists its own profile): `read_document` of B's `.env` by
  absolute path refused ("outside the allowed folders"); `*.env`,
  `sub/../../../<B>/.env`, `../.env` not found; in A's sandbox `profiles/`
  lists only A and `memory/` only A's group dir; over WS `settings.update
  DOCUMENT_PATHS=<profiles root>` is stored and `settings.get` lists it in
  `ignored`, `search_paths()` stays A's downloads and scratch; B's search
  set is B's own; from a host shell as A's user `cat` of B's `.env`,
  `zylch.db`, key file, `/etc/mrcalld/env`, and `ls profiles/`, all
  `Permission denied` (again on final code in D5).
- **Criterion 2** (on `6e28123`, same reasoning): attachments `/etc/passwd`,
  `../../x`, `.env`, `sub/dir.pdf`, `<B>/.env` in a locally built message,
  through `save_attachments`, land as `passwd`, `x`, `.env`, `dir.pdf` in
  A's `downloads/`; A's `.env` unchanged; `resolve_download_target` (the
  function `download_attachment` calls for `target_dir`; the RPC path
  itself needs an IMAP mailbox) refuses A's root, B's root, `/tmp`, the
  checkout; checkout writes EROFS in the sandbox and `Permission denied`
  from a host shell as A's user, likewise B's profile.
- **Criterion 4.** A1 and A2, both migrated (on `6e28123`), 150
  `projects.create` each concurrently: 300 seen by both, 0
  `readonly`/`locked` lines. **Mixed state, Café124's four days** (D4,
  final code): D1 migrated, D2 still `mrcalld`; both stopped, sidecars
  removed (none open — a probe-only step, never on a live store), the
  tenant daemon started first so it created `-wal`/`-shm`
  (`0660 mc-15e7bf74266b:mc-c-2734b77bf2a1`), then the `mrcalld` daemon; 150
  writes each concurrently, 300 seen by both, 0 error lines. Third user:
  B's user cannot list A's store dir or `memory/`, `sqlite3` refused.
  B's daemon `memory.join_preview(A's key)` → `exists: false`,
  `memory.join` → `operator_action`. `join-company.sh C1 <A's key> --yes`
  as C1's tenant found the renamed store, `unjoin` dropped the old group, C1
  saw A's 300 projects (final C7 run, `2a8e805`; `30f2eef` did not touch
  `join`/`unjoin`/`create`'s store handling beyond moving the chgrp out).
- **Criterion 5** (on `6e28123`; `rekey`/key handling untouched since, and
  every later migration — C1, D1 — repeated `rekey --verify` 2/2):
  in-sandbox `verify` under its own key 2 ok 0 failed for A1, A2, B1;
  key files `0400 root`, A's user `cat` of B's key denied; B started without
  its key file → "Failed to load environment files", never active; with
  A's key → "encryption self-check failed: a stored credential does not
  decrypt under this key", never serving.
- **Criterion 7** (final C7 run, `2a8e805`; re-confirmed for the lock,
  marker and last-holder in D6 on `30f2eef`): C1 and A1 each wrote a
  company fact, a `template:` and a `prefs:` row into A's store;
  `mrcall-tenant delete C1` removed C1's 2 rule rows, kept C1's fact and all
  of A1's rows; afterwards no user, profile dir, key, drop-in, fragment, run
  dir, link, table row or unowned file on the host. D6: with D1's `.env`
  unreadable the offboard failed, `delete` stopped, profile and `.deleting`
  kept, unit disabled, a reconcile skipped it; after the fix `delete` ran,
  and because D2 (unmigrated) still holds the key the store was **kept**
  and D2 kept serving 300 projects. **Exception, stated:** the store of the
  company C1 had *left* by joining A stayed behind (by design of join);
  `orphans --archive` (D7) moved it and two pre-join legacy `<key>.db`
  files to `/root/mrcall-orphan-stores/<ts>/` (root 0700) and dropped the
  empty groups; the memory root then holds no key-named file.
- **Rollbacks.** 2b: `rekey` back + `unmigrate` on A1 (before the fixes)
  and B1 (R3, `6e28123`) — daemon back as `mrcalld` on the flat socket,
  link gone, Caddy 401 — then B1 re-migrated with the kept user and key
  (R4). 2a: `unstore` (D2, final code) — store back to its legacy name,
  group and dir removed, both daemons active on `legacy`, data intact.
- **Early C1 failures in the log** (09:26, 09:28): the probe's 2b script
  sourced its helper by a relative path, so step 5 (`rekey`) never ran and
  the unit started under the new key with rows still under the shared one;
  it refused to serve with "encryption self-check failed" — criterion 5's
  behaviour, not a defect. The script was fixed and every later run shows
  `rewritten: 2 … verify: 2`.
- **Probe harness limits.** Authenticated WebSocket results used a
  probe-only drop-in (`zz-probe.conf`, removed afterwards) whose one change
  replaces Google's signing certs with a local key, so a locally signed
  token for the profile's uid passes the real `uid == OWNER_ID` gate; the
  authenticated path on production is proven only by a real client
  reconnecting (runbook step 7). In-sandbox probes ran through
  `systemd-run` with the non-empty, non-Exec lines of the unit's
  `tenant.conf` — the tenant's identity and whole sandbox, but not the
  template's own lines (`Restart`, `StartLimit*`, which do not change
  access). A `.env`-named attachment keeps its name inside `downloads/`;
  the brief's criterion holds, M1's test text said `attachment_<n>`.
- Engine tests: 1148 passed; the 3 failures (`test_contract_boundaries`,
  `test_memory_readonly`, and
  `test_local_document_paths_at_profiles_root_does_find_the_file`, whose
  glob order differs on this filesystem) fail identically on `main`.

**Runbook M2 as proven here** (supersedes the lists above).
`VENV=/home/mrcalld/mrcall-desktop/engine/venv`, `Z=/home/mrcalld/.zylch`.
Run everything from a **root shell** (`sudo -i`): the helper reuses the
reconcile lock the shell holds (fd 9), and `sudo` would close that
descriptor, so `sudo mrcall-tenant …` from a lock-holding user shell hangs.

*Once per host, before anything:* after the branch is deployed,
`systemctl is-active zylch-provisiond` and a `GET /api/provision/status`
for an unmigrated uid answering as before (not exercised on the VM); the
installed Caddyfile keeps the pre-M2
single upstream; `python3 --version` ≥ 3.11 in the venv; warm the
embedding cache as `mrcalld` (`sudo -u mrcalld env HOME=/home/mrcalld
ZYLCH_HOME=$Z bash -c 'umask 022; $VENV/bin/python -c "from
zylch.memory.config import MemoryConfig; from zylch.memory.embeddings
import get_shared_engine; get_shared_engine(MemoryConfig())"'`) **before
the first `create`** (create's `chmod -R go=rX` on the cache is what makes
the 0600 file huggingface writes readable; a cold cache cannot be filled
from inside the sandbox — second pass P2); `find
/home/mrcalld/mrcall-desktop ! -perm -o+r ! -path '*/__pycache__*'` is
empty (D5: 0); `chmod -R go=rX /home/mrcalld/releases` (the pinned
Café124 trees; `create` refuses a PYTHONPATH its tenant cannot read —
second pass PIN-1/2), and every pin names the real path of its tree: no
symbolic link, no `..`, set with `Environment=PYTHONPATH=` in a drop-in,
no trailing slash, never through an `EnvironmentFile` (`create` refuses
each — post-gate record). **production@ requires a helper extension before
its 2b:** its own `ExecStart` also starts voice with `--voice-config`,
which the helper's command omits. The live command and configuration
requirements are recorded in [the VPS preflight](#m2-record--vps-preflight-and-proposed-café124-window-2026-10-02).
Re-read `systemctl cat zylch-server@<uid>` before its 2b.

*2a, per company, one window (Café124: its four daemons):*
Before the window, verify that **every effective pinned release**, as well
as the maintenance CLI, supports the dual-name store lookup. Updating the
service checkout alone does not update a pinned release. The October 2
VPS preflight below finds this prerequisite missing in three Café124
releases; no store relocation is authorized until it is closed and the
operators choose the window.

1. `exec 9>/run/mrcalld/reconcile.lock; flock 9`;
2. `systemctl stop` every daemon of the company;
3. `install -d -m 0700 /root/backup-2a-<co>; cp -a $Z/memory/<key>.db*
   /root/backup-2a-<co>/` (the key comes from `join-company.sh table`);
4. `sudo -u mrcalld env HOME=/home/mrcalld bash -c 'cd /home/mrcalld &&
   umask 007 && $VENV/bin/zylch -p <one uid> memory-relocate-store'`;
5. `mrcall-tenant store <that uid>`;
6. `systemctl start` every daemon of the company; release the lock
   (`exec 9>&-`);
7. per uid: `sudo -u mrcalld env HOME=/home/mrcalld $VENV/bin/zylch -p
   <uid> memory-names` shows `store in use: derived`; each daemon active;
   the company's users see their memory.
Rollback, in the same window (lock held, all stopped): `mrcall-tenant
unstore <uid>` (it does not take the lock itself); start all; release the
lock; `memory-names` shows `legacy`. Afterwards `mrcall-tenant orphans` (listing
only) and, once the backup window has passed, `--archive`.

*2b, per profile U, one per day, after its company's 2a:* steps 1–6 of the
list above, unchanged (the step 0 check as above). Step 7, exactly:
- `systemctl start zylch-server@U`; release the lock;
- `systemctl is-active zylch-server@U` and `journalctl -u
  zylch-server@U --since -2min | grep -c 'self-check failed'` → `active`, 0
  (the start-time decrypt self-check is criterion 5 on the live rows);
- `curl -s -o /dev/null -w '%{http_code}' -H 'Connection: Upgrade' -H
  'Upgrade: websocket' -H 'Sec-WebSocket-Version: 13' -H
  'Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==' https://<host>/ws/U` → 401;
- as the tenant: `sudo -u <mc-user> env HOME=$Z/profiles/U ZYLCH_HOME=$Z
  MEMORY_DB_DIR=$Z/memory bash -c 'umask 007; exec $VENV/bin/zylch -p U
  memory-status'` → `available: True`;
- `sudo -u <mc-user> cat $Z/profiles/<another uid>/.env` and
  `/etc/mrcalld/keys/<another uid>` → `Permission denied` (criterion 1/5);
- `stat -c '%U:%G %a %n' $Z/profiles/U/zylch.db* $Z/memory/<group>/*.db-wal
  $Z/memory/<group>/*.db-shm`: the profile's files owned by the tenant; the
  store's sidecars `0660` with the company group (their owner is whichever
  daemon opened the store first, which is fine);
- the customer's app reconnects and shows mail — the only real
  authenticated check;
- never run `rekey --verify-only` or any `zylch` command as root while the
  unit runs (root-owned `-wal`/`-shm`).
2b rollback as above (stop; `rekey` with the files swapped, as root;
`mrcall-tenant unmigrate U`; start). `unmigrate` removes `tenant.conf`
only: a pinning drop-in stays, and after the start the pinned unit's
`PYTHONPATH` is checked as in step 7 (the helper of `e76da7f` and before
removed the whole drop-in directory — post-gate record). A drop-in that
was edited for the migration is put back from the operator's copy before
the start. When the company's last profile is
migrated: `gpasswd -d mrcalld <group>` (R8: the reconcile does not re-add
it). When the rollback window closes (the plan keeps the shared key until
then): `shred -u /root/oldkey.U /root/stat.U`, remove `/root/backup.U.tgz`
and `/root/backup-2a-<co>`.

*Offboarding:* `mrcall-tenant delete U` only (lock, marker, offboard as
the tenant, last holder derived from group members **and** other
profiles' keys); if it stops on an offboard error, fix and re-run.

**Gate.** Two independent reviews on the scratch evidence and the host
mechanisms: A (adversarial, host scripts) REVISE ×2 → APPROVED at
`8169522`; B (evidence conformance, runbook) REVISE ×2 → APPROVED at
`44133f7` (`8169522` only adds the lock reuse A asked for, probed in D8/D9).
That verdict predates main's record of the pinned Café124 units; the
second pass below found and fixed two more defects (pinned releases,
log rotation) and carries its own gate.

**Still open, not blocking Café124** (review A): `mrcalld` owns
`/run/mrcalld`, the company store dirs and `reconcile.lock`; after the
last migration those parents should move to root ownership so a
compromised provisiond cannot swap links or stores. Provisiond and the
reconcile path unit are to be exercised on the VPS itself.

### M2 record — second scratch pass on main `1c4e2cb` (2026-10-01)

Same VM, **wiped first** (units, drop-ins, tmpfiles, `/etc/mrcalld`, the
`mc-*` users and groups, `mrcalld` and `/home/mrcalld`, Caddy config;
python3.11 and Caddy packages kept). B.1 run literally from main
`1c4e2cb` (only deviation: `python3.11`); three profiles built as
production has them (`mrcalld`, shared key, legacy stores, A2 joined A1),
and **A1 pinned like Café124**: a read-only release tree
`/home/mrcalld/releases/mrcall-desktop-pin-1c4e2cb` selected by an
`override.conf` with `Environment=PYTHONPATH=…/engine`, whose
`zylch/__init__.py` prints `PINNED-RELEASE-MARKER` to the journal at import.
Log: `/root/m2-probe-2026-10-01.log` on the VM.

*Phase 1, main as is.* The two blocking defects of the first pass are
still on main: Caddy's dual upstream — after one request for a missing
uid, A1 and B1 503 until `fail_duration` (M-1); 2a by the plan's text then
`create` — B1 dies on `PermissionError … .db.migrate.lock` (M-2). Rollback
with main's verbs works (M-3). Main must not be deployed for M2 as is.

*Phase 2, `claude/m2-scratch-probe` merged with main (`227fe07`), then
these fixes:*

7. **A pinned unit silently stops being pinned once migrated**
   (`4257253`). `ProtectHome=tmpfs` hides `/home/mrcalld/releases`; Python
   skips the missing `PYTHONPATH` entry and imports the checkout. Recorded:
   the migrated A1 process carries the `PYTHONPATH`, the release dir does
   not exist in its namespace, 0 marker lines from its pid. Now
   `tenant.conf` binds `-/home/mrcalld/releases` read-only, and `create`
   refuses (before any chown; a first migration falls back to the
   template) a `PYTHONPATH` outside the checkout and releases or one the
   tenant cannot read, and any other drop-in that sets `ExecStart` (it
   would win or lose against `tenant.conf` by file name). Recorded:
   PIN-1 refusal on the 0750 tree; PIN-2 after `chmod -R go=rX` the
   migrated A1 logs the marker, sees the release read-only (EROFS on
   write); PIN-3 an `ExecStart` drop-in refused, A2 left on the template as
   `mrcalld`; PIN-4 a `PYTHONPATH` outside the trees refused, nothing
   chown'ed. A1 stayed pinned through the probe wrapper, the real unit, a
   reboot and a reconcile. (On `e76da7f` both refusals could still be
   walked around, and a rollback lost the pin: post-gate record below.)
8. **Log rotation of a migrated profile** (`4257253`, `e76da7f`). Main's
   glob stanza with `su mrcalld`: "stat … Permission denied" for the
   migrated log, rc=1 (LR-1) — every night, and the log never rotates. A
   second stanza for the same file is a "duplicate log entry" error in
   either order. Now the helper generates `/etc/logrotate.d/mrcalld`
   (text fixed in the root-owned helper, never read from the checkout):
   the unmigrated profiles' logs in one stanza as `mrcalld`, one stanza
   per tenant with `su <user> <user>`; regenerated by `create`,
   `unmigrate`, `delete` and `update-daemons.sh`; the static file is gone.
   Recorded: `logrotate -d` 0 errors; forced runs of the file and of the
   system's own `logrotate.service` (result `success`) rotated every log
   as its owner (LR-2b); `unmigrate` moves a profile back under
   `mrcalld`, `create` back to its own stanza, `delete` drops it (R-2,
   R-3, LR-4).

Results on `e76da7f` (the final code is `267e365`, post-gate record
below), real units unless marked:

- **create + unit start under the drop-in:** A1 (pinned), A2, B1 active as
  `mc-<sha12(uid)>` (R-1); `systemd-analyze security` 4.4; reboot
  simulation and reconcile with three tenants restart nothing (R-4).
- **Caddy, single upstream + flat-name link** (P1): a missing uid 502,
  A1/A2/B1 401 right after; a stopped migrated unit (dangling link) 502
  with A1 still 401; restarted 401. Main's dual upstream: M-1 above.
- **fastembed** (P2): with step 0 skipped the tenant cannot load the model
  ("Could not load model … from any source") — the cache must be warm
  before; after step 0 and `create` the model loads from the read-only
  bind, 0 files newer than the marker, no permission warning (P2b).
- **Two-user WAL test** (C4, probe wrapper): A1 and A2 150
  `projects.create` each concurrently, 300 seen by both, 0
  `readonly`/`locked` lines, sidecars `0660 … mc-c-1709443c14c4`.
- **Criteria 1, 2, 4, 5, 7** re-run as in the first pass, same results:
  battery (C1, C2, C4, C5) and C7 (C1 joined to A with `join-company.sh` as
  its tenant; `delete` removed its 2 rule rows, kept its company fact and
  A1's rows; nothing of C1 left on the host).
- **rekey --verify and unmigrate** (R-2/R-3): B1 rolled back to `mrcalld`
  on the flat socket, Caddy 401, then re-migrated; B1 was also migrated and
  rolled back once with main's verbs (M-2/M-3) and re-migrated with the
  kept user and key.
- `/etc/systemd`, `/etc/systemd/system`, `/etc/qemu` are `0755` on this
  VM (the provider image item is host-specific).
- Orphans after the pass (a pre-join legacy store, C's joined-away dir)
  archived with `orphans --archive`.

### M2 record — post-gate probes and reviews of `4257253`, `e76da7f` (2026-10-02)

The two commits above were made after the gate and had no review. Same
VM (resized to 8 GB + 4 GB swap — operator note, not in the log),
installation and scratch profiles of 2026-10-01 kept; one or two daemons
running at a time, all three only during the reconciles (DEP-4, FINAL-0).
Log: `/root/m2-probe.log` on the VM, scripts in `/root/m2-probes/`. It
holds every command with its output, except the `override.conf` rewrites
of REV-2, REV-3, REV-7 (first case) and REV-8 (FINAL-1 repeats each case with its setup
logged) and one `orphans --archive` (noted in the log). The log corrects
itself where a probe proved nothing (LR-4, LR-4b, FIX-6, REV-5 second and
third command, REV-6, DEP-0..3); those are not cited below.

Final code: **`267e365`** (`f6f5301`, `0eae166`, `267e365` on top of
`e76da7f`). The helper under test is identified by hash at P0
(`e76da7f`), FIX-0 (`f6f5301`), REV-0 (a working-tree build, not kept:
`0eae166` differs from it by the trap's fragment removal), REV-8
(byte-identical to `267e365`), DEP-4 (`0eae166`) and FINAL-0 (`267e365`,
deployed by `update-daemons.sh` from origin). **FINAL-1..6 repeat every refusal
and the pinned start on the committed final helper.**

*What was asked of the two commits, on `e76da7f` as committed:*

- **A pinned profile migrated with `create` imports its release**
  (PIN-A0, PIN-A3, PIN-A4): A1 rolled back, started as `mrcalld`, migrated
  again by the runbook. The unit's main process logs the marker of the
  pinned tree's `zylch/__init__.py`, which prints its own `__file__`
  (`/home/mrcalld/releases/mrcall-desktop-pin-1c4e2cb/engine/zylch/__init__.py`),
  attributed to the main pid; an `ExecStartPre` in the same unit prints
  the same `zylch.__file__` under the tenant uid. Control (REF-0): the
  unpinned B1 prints the checkout path. Decrypt self-check 0, Caddy 401.
  Again on `267e365`: FINAL-6.
- **`create` refuses** a `PYTHONPATH` outside the bound trees (REF-1, a
  readable tree in `/opt`) and another drop-in that sets `ExecStart`
  (REF-2), on a first migration — unit left on the template as `mrcalld`,
  nothing chown'ed, no table row, logrotate file unchanged — and on a
  migrated profile, whose `tenant.conf` stays (REF-3).
- **Generated logrotate file** with A1 migrated and B1 not, both running:
  `logrotate -d` on the file and on `/etc/logrotate.conf` 0 errors, no
  "duplicate log entry" (LR-2); `logrotate -f` rc=0, each log rotated and
  truncated by its owner, daemons still serving (LR-3); the nightly
  `logrotate.service`, forced, under its own sandbox with non-empty logs:
  result `success`, both logs rotated (LR-5). Regenerated by `unmigrate`
  (LR-U, FIX-6b: B1 back under `su mrcalld`), by `create`, and by `delete`
  of an unmigrated and of a migrated throwaway profile (LR-D1, LR-D2).
  Rotation is by size: `size 50M` overrides `daily`, as in the static
  file it replaces.

*Defects the probes and the two reviews found; each shown failing on the
code named, fixed, and probed again* (numbering continues):

9. **Rollback un-pinned a pinned unit** (`e76da7f` and every earlier
   helper; PIN-A1/A2). `unmigrate` removed the whole drop-in directory,
   the operator's `override.conf` included: the rolled-back A1 ran the
   checkout with nothing in the journal. It now removes `tenant.conf`
   and the directory only when empty (`f6f5301`; FIX-4, FIX-6b).
10. **The `PYTHONPATH` refusal tested a prefix** (`e76da7f`; EDGE-1,
    EDGE-2). `releases/../releases-b/engine` and a link inside `releases`
    pointing out of it were accepted, and the migrated daemon imported the
    checkout. Two repairs were not enough, each shown by review A:
    resolving the path first (`f6f5301`) accepts `/home/mrcalld/current ->
    releases/<tree>`, which resolves into the tree and does not exist in
    the sandbox (REV-2: checkout imported); comparing with the lexically
    normalised path (`0eae166`) accepts a `..` hop through a directory
    the sandbox lacks (REV-7). `267e365` accepts a pin only when the path
    and its `zylch/__init__.py` **equal their own real path as written**,
    inside the checkout or `releases`, absolute, readable by the tenant:
    no link (one inside `releases` included), no `..`, no trailing slash
    (REV-8, FINAL-1; accepted forms FINAL-4).
11. **A pin could arrive where the check did not look** (`e76da7f`;
    EDGE-5). `PYTHONPATH` in an `EnvironmentFile` is invisible to
    `systemctl show -p Environment`; named by the template or by a drop-in
    that sorts before `tenant.conf`, it is also dropped by `tenant.conf`'s
    reset of the list (REV-4: accepted by `f6f5301`). The template and
    every drop-in are now read before `tenant.conf` is written, and an
    `EnvironmentFile` that sets `PYTHONPATH` is refused; so is one named
    with a specifier (`%i`), which the helper cannot follow, and a
    trailing space no longer hides the file (REV-7: both accepted by
    `0eae166`; REV-8, FINAL-2). A quoted `PYTHONPATH` entry is refused
    rather than skipped.
12. **The `ExecStart` refusal read one directory and one spelling**
    (`e76da7f`; EDGE-3, EDGE-4). `ExecStart = …` and a drop-in of the
    template (`zylch-server@.service.d`) were accepted and replaced
    `tenant.conf`'s command line. Now every path in `DropInPaths` is read
    (FIX-2, FIX-3, FINAL-3). A second check on the effective `ExecStart`
    is a backstop no probe reaches: nothing gets past the file check.
13. **A first migration stopped half-way kept `tenant.conf`** (review A).
    The fallback to the template ran only on the helper's own refusals.
    An EXIT trap, armed from the write of `tenant.conf` to the chown, now
    removes `tenant.conf`, the tmpfiles fragment, the run dir and the
    flat-name link (the template's daemon binds that name). FINAL-5, on a
    virgin profile: three refusals, a failing `systemd-tmpfiles` (rc=73)
    and a stop after the run dir existed each leave no drop-in, fragment,
    run dir or link, the profile `mrcalld`'s, no table row. The user and
    key file a stopped first `create` made stay; the next one reuses them
    (REV-5: "created user" and "minted key file" printed once).
14. **logrotate temp file** (review A): written to `/etc/logrotate.d/`,
    where logrotate would read a leftover `.tmp` as a second
    configuration (its include rule; reproduced by the reviewer outside
    the host, not in the log). Now under `/etc/mrcalld/` (REV-5b, DEP-4:
    no `.tmp` in either directory after a regeneration).

*Deploy path.* On `0eae166` (DEP-4, DEP-5): `update-daemons.sh` pulled
the commit from origin, installed the helper (hash equal to the
commit's), re-applied `create` to the three migrated units, regenerated
the logrotate file, started all three — active as their tenant users,
Caddy 401, A1's main process on the pinned release; a second run
restarted nothing. On `267e365` (FINAL-0): the same pull, install,
`create` ×3 and regeneration, the units stopped at once; A1 alone is
then started and checked (FINAL-6). `create` on a running migrated unit
keeps its pid (REV-1, DEP-5, FINAL-6).

**Runbook, added to "Runbook M2 as proven"** (its text above is updated):

- *Before 2b of a pinned profile:* `systemctl cat zylch-server@U`. The pin
  is one `Environment=PYTHONPATH=<real path of the tree>/engine` line in a
  drop-in; anything else `create` refuses and says why.
- *2b step 7, for a pinned profile:* the process's `PYTHONPATH` (`tr '\0'
  '\n' < /proc/<pid>/environ`) is the release **and** `nsenter -t <pid>
  -m -- test -e <PYTHONPATH>/zylch/__init__.py` succeeds — the tree
  exists in the daemon's own mount namespace (FINAL-6: rc 0, and 1 for a
  path that is not bound); the environment alone proved nothing in
  defect 7. Then `logrotate -d /etc/logrotate.conf 2>&1 | grep -ciE
  'error|duplicate'` → 0.
- *Rollback of a pinned profile:* nothing to re-create; the same check
  after the start.

**Open.**

- **production@ cannot be migrated with this helper.** Its drop-in sets
  `ExecStart` to a path under `releases`, and `create` refuses any
  `ExecStart` outside `tenant.conf`. On the scratch VM a unit whose own
  `ExecStart` was the standard command line migrated once those lines
  were removed and only the `PYTHONPATH` pin kept, and rolled back with
  the kept copy restored (PROD-1..4). The October 2 VPS preflight below
  establishes that production@ additionally starts voice: its release
  venv command carries `--voice-config /etc/mrcalld/voice-cafe124.env`,
  and its drop-in loads that file as an `EnvironmentFile`. A PYTHONPATH-only
  conversion is insufficient; an explicit, root-controlled helper
  extension must preserve that behavior and pass VM forward/rollback
  probes before its 2b. It is the last of the Café124
  2b's; the other three pin by `PYTHONPATH` only. Until it is migrated,
  `mrcalld` stays in Café124's company group, so every unmigrated daemon
  can still read and write that store: the `gpasswd -d mrcalld <group>`
  step is not reached.
- A refused `create` in the reconcile (3a) is a line on stderr; 3b then
  restarts that already migrated unit as it is (from the code, review A;
  not probed, not changed here).
- A table row whose user was removed by hand gives logrotate "unknown
  user" for that stanza every night (review A, reproduced outside the
  host; no helper verb produces that state).
- Review A's notes on `267e365`, not changed (the gate closed on that
  commit): `EnvironmentFile=\` continued on the next line is not followed
  by the helper's reader, so a pin named that way is the one exception to
  defect 11 (closes by refusing a value that does not start with `/`);
  a symlinked `scratch` with no `downloads` leaves a root-owned
  `downloads/` behind the refusal; a `create` that dies between the chown
  and the table row leaves a tenant-owned profile the undo does not know.
- Not exercised on the committed final helper: the effective-`ExecStart`
  backstop (by no probe at all); a `zylch/__init__.py` that is itself a
  link; the production@-like forward path and rollback (PROD-1..4 ran on
  the REV-0 build; on `267e365` only its refusal, FINAL-5); a start of
  the template unit after a stopped first migration (FINAL-5 shows the
  leftovers gone and `User=mrcalld`, not a bind).
- `docs/remote-backend.md` on main (mnemonic upgrade, "the per-unit pin")
  proposes a second checkout with its own venv selected by a drop-in that
  resets `ExecStart=`. A unit pinned that way is refused by `create`, like
  production@: pin by `PYTHONPATH`, or extend the helper first.
- The scratch VM's root disk is at 97 % (the 4 GB swap file): clear space
  before the next session there.

**Gate (post-gate commits).** Two independent reviews of `4257253`,
`e76da7f` and the probes, continued over the fixes: A (adversarial, host
scripts) REVISE on `f6f5301` (defects 10 and 11, second halves; 13; 14;
the production@ step) and on `0eae166` (the `..` hop, the specifier) →
**APPROVED at `267e365`**; B (evidence conformance, runbook) REVISE on
`f6f5301` (the record still described `e76da7f`; the production@ step;
claims wider than the probes) and on `0eae166` (refusals not run on the
committed hash; `..`) → **APPROVED at `267e365`**, this record included.
Both judge "production@ open" an acceptable resolution for this gate, not
a blocker; it blocks production@'s own 2b.

Merged with main `e1e5f79` afterwards (no conflict; main does not touch
the host scripts). On the merged tree, with the VM's engine interpreter:
the test files the merge touches plus the tenant, rekey, offboard and
provisiond ones — 392 passed, 19 skipped, 1 failed
(`test_contract_boundaries`, `llm.models`), which fails identically on
main `e1e5f79`. The full suite was not run (it was OOM-killed on this VM
on 2026-10-01).

### M2 record — VPS preflight and proposed Café124 window (2026-10-02)

Scope: read-only checks on `desktop.mrcall.ai` from main `a554f5e`.
No helper deployment, drop-in edit, daemon restart,
store relocation or profile identity migration was performed. The existing
brief and plan are the work trace for this follow-up. Secret-free probe
output is in `/tmp/mrcall-ai-kit/sandbox-preflight/` on the VPS; tokens,
credentials and the memory capability key are excluded.

**production@ command classification — helper extension required.**
`systemctl cat zylch-server@Gn9IcuWzYyY7DBMHkVUGB7bIiTp2` and
`systemctl show … -p ExecStart -p EnvironmentFiles -p DropInPaths`
show three operator drop-ins: `90-daily-budget.conf`,
`95-evolution-pilot.conf`, `99-cafe124-voice.conf`. The last overrides
the earlier pilot command. Its effective command is:

```text
/home/mrcalld/releases/mrcall-voice-cafe124-phone-md-5ebe3fa/venv/bin/zylch -p Gn9IcuWzYyY7DBMHkVUGB7bIiTp2 serve --unix /run/mrcalld/Gn9IcuWzYyY7DBMHkVUGB7bIiTp2.sock --voice-config /etc/mrcalld/voice-cafe124.env
```

The same drop-in pins `PYTHONPATH` to that release's `engine` and loads
`EnvironmentFile=/etc/mrcalld/voice-cafe124.env`, currently
`0640 root:mrcalld`. This is more than release selection: `serve` uses
`--voice-config` to construct the production voice listener on port 8787.
Main's reviewed helper, awaiting installation, writes only
`serve --unix <uid>/ws.sock`, resets `EnvironmentFile` to the tenant key,
and refuses the operator `ExecStart` assignments in both the pilot and
voice drop-ins. The older installed helper lacks that refusal and must
not be used to attempt this migration. Removing those
assignments would lose the voice listener; keeping only `PYTHONPATH`
does not preserve the command.

Before production's own 2b, extend the helper through a separately
reviewed change and VM forward/rollback probe. It must preserve the
required interpreter/dependencies and voice argument, use the tenant
socket, and make the voice configuration readable to the tenant without
exposing it to sibling users. Review the voice environment-file ordering
against the mandatory per-profile encryption key. Preserve/restore both
operator command drop-ins and the release pin on rollback; test voice
health/callback authentication and the app as well as the socket. No
conversion or helper extension is implemented here. Production stays
last in 2b; `mrcalld` stays in the company group until then.

**Provisiond — current-host checks passed, repeat after reconcile.**
`systemctl is-active zylch-provisiond` → `active`; the process runs as
`mrcalld`. `/run/mrcalld` is `2751 mrcalld:caddy` and
`provisiond.sock` is `0660 mrcalld:caddy`. `GET /api/provision/status`
without a bearer returns `401 {"error":"unauthorized"}` both directly
on the socket and through `https://desktop.mrcall.ai`. With a real
Firebase ID token for the unmigrated production UID, both paths return
`200 {"state":"active"}`. The token was refreshed from the existing
local descriptor and held only in memory. Its `PROVISIONING` marker was
absent before the GET, so the status request removed no marker. No
provisioning POST or 409 probe was performed. These checks precede the
new helper's installation and do not certify that future state.

**Readiness found on the effective releases.** Comparing profile keys in
memory confirms exactly the four UIDs below share company group
`mc-c-7aaa48b3ef85`; the capability itself was not printed. The legacy
store exists and the derived store does not. All seven daemon units are
active as `mrcalld`, and the installed helper's `list` is empty.

| Café124 UID | Effective release under `/home/mrcalld/releases/` | Store lookup |
|---|---|---|
| `C06xHKoRcfdz94FaLPKuJuo0xVo1` | `mrcall-desktop-k3-8d83193-m1-bbde719` | legacy only |
| `YZNI2ZLDjFOxcvF0zmptW3vRZxV2` | `mrcall-desktop-k3-8d83193-m1-f342c5c` | legacy only |
| `ZwpLepFDghWhQEBO4WJRIFcEr7p1` | `mrcall-desktop-k3-8d83193-m1-f342c5c` | legacy only |
| `Gn9IcuWzYyY7DBMHkVUGB7bIiTp2` (production@) | `mrcall-voice-cafe124-phone-md-5ebe3fa` | derived then legacy |

Evidence: the three K3 trees' `zylch/memory/store.py:memory_db_path`
unconditionally returns the legacy filename; production's function checks
`derived_memory_db_path`, then `legacy_memory_db_path`. **2a is not ready:**
first backport and verify dual-name resolution on each effective K3
release, keeping the existing release behavior and rollback pins. Do this
as future reviewed preparation; do not rename the shared store first or
assume tonight's service-checkout pull updates the pins. No database was
opened by the preflight, and no backport was made here.

**October 3 morning verification — pending.** At this preflight the service
checkout is still `e1e5f79`; the installed helper hash differs from main's,
and `/etc/logrotate.d/mrcalld` still has the old glob stanza with
`su mrcalld mrcalld`. Today's `logrotate -d /etc/logrotate.d/mrcalld`
exits 0; it does not validate tomorrow's generated file. The next
`zylch-reconcile.timer` activation is **2026-10-03 00:00 UTC**.

**First-pull bootstrap blocker:** the VPS's `e1e5f79` updater still runs
`install -m 644 "$LOGROTATE_SRC" "$LOGROTATE_DST"` before installing the
helper. Its `git pull` will delete that static source file (removed by
`4257253`, included in `a554f5e`). The reconcile wrapper invokes this
updater directly; neither script re-executes the new version after the
pull. From those scripts, the first run is expected to exit on the
missing static file before installing the new helper or regenerating
logrotate. An isolated reproduction with copies of both full updater
versions, a real Git pull and `install`, and stubbed sudo/systemd commands
confirmed exit 1 (`cannot stat …/engine/scripts/logrotate.d/mrcalld`)
and no helper installation; a second invocation of the new on-disk
updater exited 0 and generated the synthetic logrotate file. This tests
the bootstrap mechanism, not tomorrow's live outcome; evidence is
`reconcile-bootstrap-verify.log` in the preflight directory.
A current checkout SHA alone will therefore not prove a
successful deployment. This needs a separately reviewed deployment
follow-up; no updater change or manual reconcile was performed here.
The checks below must diagnose that transition, not assume the nightly
upgrade succeeded.

After the timer, the morning operator/session must record:

```bash
sudo git -C /home/mrcalld/mrcall-desktop log -1 --oneline
sudo systemctl show zylch-reconcile.service -p Result -p ExecMainStatus
sudo journalctl -u zylch-reconcile.service --since '2026-10-03 00:00 UTC' --no-pager
sudo cmp /usr/local/sbin/mrcall-tenant /home/mrcalld/mrcall-desktop/engine/scripts/server/tenant-helper.sh
sudo cat /etc/logrotate.d/mrcalld
sudo logrotate -d /etc/logrotate.d/mrcalld
sudo logrotate -d /etc/logrotate.conf
sudo systemctl is-active zylch-provisiond
```

Acceptance after the bootstrap blocker is resolved: successful reconcile,
helper byte-identical to the pulled
checkout, generated explicit log paths for the seven unmigrated profiles
in the `su mrcalld mrcalld` stanza, no old overlapping glob, dry runs exit
0 with no errors/duplicates. Re-run the authenticated provisiond GET as
above; all seven profiles must still be active as `mrcalld` and the helper
table empty. This is a pending handoff, not a completed check or a newly
scheduled job. No forced rotation or manual reconcile is requested.

**Proposed 2a window — not booked, not authorized, not executed.** Candidate:
**Monday 2026-10-05, 04:00–04:30 UTC (06:00–06:30 Europe/Rome)**, after
the October 3 checks and the three K3 release prerequisites pass. The
operators choose the actual date/time and confirm that it is outside
Café124's required service hours; this candidate establishes no
availability. Reserve 30 minutes; target a few minutes of outage, with
a rollback decision within 10 minutes of the stop. Required presence:
the named root-shell executor, the CTO who controls go/no-go, and a
Café124 representative who can reconnect an authenticated app and check
voice service. Assign names and confirm attendance before booking; no
messages or calendar invitations were sent.

Execution checklist for that future window only:

1. Re-read units and effective pins; confirm all four releases support
   both store names, no extra company holder appeared, and the backup
   destination has space. Stop/coordinate external company writers and
   operator CLI sessions. Confirm no call is in flight from the voice
   ledger and arrange with the operator that no new call enters during
   the outage. If those conditions or attendance fail, defer the window.
2. From a root shell, hold fd 9 on `reconcile.lock` throughout the stop,
   backup, relocation and acceptance/rollback. This serializes timer/path
   reconcile; avoid midnight and do not close fd 9 through `sudo` on the
   helper. Stop **all four listed daemon units together**, confirm each
   inactive and no remaining process holds the shared store; no rename
   while any writer remains.
3. Follow proven 2a steps 3–5: root-only backup of the store, sidecars and
   lock files plus ownership record; `memory-relocate-store` as `mrcalld`
   using the updated maintenance CLI; installed `mrcall-tenant store`.
   Keep the key and legacy filenames out of command logs. No `create`,
   rekey or identity change in this window.
4. Start **all four** with their existing drop-ins/interpreters. Before
   releasing the lock, verify each unit active, each pinned release
   unchanged, derived-store use from all four effective release contexts,
   no recreated legacy store or readonly/locked errors, and company
   memory plus app reconnect visible to the attending user. Production
   voice health and unsigned callback authentication must match the
   pre-window baseline. Release the lock only after acceptance.
5. On failure or the 10-minute decision limit, keep the lock, stop all
   four again, and run proven `mrcall-tenant unstore` rollback; start all
   four with the retained pins, verify legacy use, memory/app/voice, then
   release the lock. Keep the backup until the rollback window closes.

This 2a proposal leaves every profile as `mrcalld`. Separate 2b windows
remain one profile per day, production last after its helper gate. The
operators decide the window; this session publishes the plan and stops.

### M2 decision — compressed rollout (2026-10-02, CTO)

The CTO decided to migrate as soon as possible. The hosted profiles belong
to the CTO and a few friends, not to production customers. That
**supersedes** three parts of the proposal above: the
one-profile-per-day cadence, the Monday window, and the requirement for a
Café124 representative and service-hours booking. Everything else stands:
the reconcile lock, backups, the stop-all-holders rule, rekey `--verify`
before start, and rollback by `unstore` / `unmigrate`.

1. **Bootstrap now, not at midnight.** Once `main` carries the bootstrap
   stub (`engine/scripts/logrotate.d/mrcalld`, commit `b6d098f`) and the
   tenant-exec fixes (`5ee01d4`), the VPS operator runs
   `systemctl start zylch-reconcile.service` twice. That is the timer's
   own path, and it takes the reconcile lock. The first run is the old
   on-disk updater, which the stub lets succeed; the second is the new
   one. Then the operator records the October 3 checklist above. The
   00:00 UTC run becomes a repeat.
2. **K3 pins removed.** The three K3 releases
   (`mrcall-desktop-k3-8d83193-m1-*`) do not look up both store names, and
   `main` carries their content. Their PYTHONPATH drop-ins are moved aside
   (backed up under `/root/`, never deleted), so the units run the service
   checkout. To revert, restore the drop-in, `daemon-reload` and restart.
3. **One window, same day.** Run 2a for every company (Café124: all four
   holders stopped together), then 2b for every profile except
   production@. Each profile is accepted (active as its `mc-…` user,
   rekey verified, app reconnects, memory visible) before the next
   starts. A failure stops the window at that profile and rolls it back;
   the profiles already accepted stay migrated.
4. **production@ last.** Its migration goes through the operator
   declaration in `/etc/mrcalld/tenant-exec/<uid>`:
   - `INTERPRETER` names the voice release's `zylch`.
   - `VOICE_CONFIG` names `/etc/mrcalld/voice-cafe124.env`.

   It goes ahead only after the scratch VM has proven the declaration
   forward and back: create, the effective ExecStart, the voice copy
   readable by the tenant, a refused off-allowlist line, and `unmigrate`.
   Two reviewers must pass that probe. Its other drop-ins keep their
   current content.

### M2 record — VPS rollout (2026-10-02)

Executed under the CTO's compressed-rollout decision and explicit
immediate-window instruction, from `main` **`499ca09`**. The earlier
Monday proposal, per-day cadence and attendance requirement did not
apply. This attempt **stopped at its first anomaly during the bootstrap
verification**, before K3 unpinning or any 2a/2b operation.

**Bootstrap completed.** The two explicit
`systemctl start zylch-reconcile.service` invocations began at
**11:50:45 UTC** and **11:51:12 UTC**. After each, `systemctl show`
returned `Result=success`, `ExecMainStatus=0`; the unit journal was
read. The first run used the old updater, pulled `e1e5f79` → `499ca09`,
installed the bootstrap logrotate stub and new helper, and restarted all
seven daemons. Its captured journal reports updater exit 0 and
`done. (7 profiles; code_changed=1 dry_run=0 prune=0)`. The second run
used the new on-disk updater. The immediately captured second journal
contains successful service completion but lacks the updater's detailed
summary; an additional tagged-journal check was attempted below.

Before and after each run, production's ledger was read as `mrcalld`
with SQLite `mode=ro`: ten closed calls and zero unresolved calls.
Local and public `/healthz` returned HTTP 200,
`runtime=engine_listener`, `calls_available=true`. Unsigned
`/vonage/answer`, `/vonage/event`, `/openai/live` returned 401, 401,
400 respectively on both paths. No paid call was made. Production's
three operator drop-ins remain byte-identical to the pre-window record;
its restart was part of the explicitly authorized reconcile, not an
identity migration.

The post-bootstrap checks actually run and passed:

- Service checkout: `499ca09`; installed helper byte-identical to
  `engine/scripts/server/tenant-helper.sh` (`cmp` exit 0).
- `cat /etc/logrotate.d/mrcalld`: generated explicit paths for the seven
  unmigrated profiles, one `su mrcalld mrcalld` stanza, no old glob.
- `logrotate -d /etc/logrotate.d/mrcalld` and
  `logrotate -d /etc/logrotate.conf`: exit 0, no configuration errors or
  duplicate log entries. Only the normal debug-mode warning and
  `size`-overrides-`daily` note; no rotation was executed.
- All seven daemon units active as `mrcalld`; installed helper `list`
  empty; `systemctl is-active zylch-provisiond` → `active`.

**First anomaly and stop.** The lead's supplemental
`provision-check.py` exited 1 with
`STOP AT FIRST ANOMALY: IndexError: list index out of range`. It imports
the bootstrap runner to reuse safe logging. That runner's top-level
dispatch reads `sys.argv[1]` without an `if __name__ == '__main__'`
guard; the supplemental process had no mode argument, so importing it
triggered the runner before the follow-up journal or authenticated GET
could execute. This is a probe implementation failure, not evidence of
a daemon or provisiond failure. The lead stopped runtime work rather
than bypassing the failed check. The scratch copy of the runner now has
the `__main__` guard; compilation and an isolated dispatch test pass.
The installed root runner remains the failed version as evidence: no
production probe was retried and the rollout did not resume.
The supplemental tagged-journal check
and authenticated provisiond GET remain unverified for this attempt;
the October 2 preflight's earlier authenticated result is not reused as
post-bootstrap proof.

**State at stop.** A read-only state check still shows all seven units
active as `mrcalld`, zero tenant-table rows and production's three
operator drop-in hashes unchanged. The three K3 pins remain in place.
No drop-in was moved to `/root/k3-pins-backup/`, no company-store
relocation or `store`/`unstore` ran, and no profile `create`, rekey or
`unmigrate` ran. Therefore no company/profile rollback was necessary.
Production was not migrated. Steps 2–5 of the instruction, including
the read-only voice allowlist/path checks scheduled as step 5, were
not executed after the stop. No key, credential or token value was
printed or written into this record.

Evidence: root-only `/root/m2-rollout-20261002/` holds the runner,
supplemental probe, sanitized `rollout.log`, baseline and anomaly record.
The narrow delivery brief/plan are under
`/tmp/mrcall-ai-kit/sandbox-rollout/`; the existing isolation brief and
this plan remain the repository work trace. The next attempt must install
the corrected scratch runner and re-establish bootstrap acceptance
before proceeding in the same authorized order. This record does not
claim completion of M2 or waive the first-anomaly stop rule.

## M3 — Egress bound per daemon

Owner: release-engineer. After M2 is stable on all six; own rollback.

1. Enumerate from code and configuration: IMAP/SMTP hosts per profile,
   WhatsApp, StarChat and `MRCALL_PROXY_URL`, Anthropic, OpenRouter, Google
   (`www.googleapis.com`, `securetoken.googleapis.com`, OAuth hosts, the
   certificate URL), `huggingface.co` (fastembed model), Pipedrive when
   configured.
2. Mechanism: nftables rules keyed on `meta skuid <tenant user>` with a
   DNS-fed set (dnsmasq `nftset`) per tenant, so the allowed names follow
   every resolver answer — `imaplib`, `smtplib` and neonize's Go client read
   no proxy variable, so a proxy alone cannot cover them. The per-tenant set
   is the observable allow list (`nft list set`). httpx clients keep
   `trust_env` where it is set; `openai_voice.py:250` and
   `smoke_transport.py:83` are audited for the same behaviour. Daemons
   resolve through the local dnsmasq (host `/etc/resolv.conf` at
   `127.0.0.1`, `skuid → 127.0.0.1:53` allowed); dnsmasq 2.87+ built with
   nftset is recorded in the runbook.
3. Rollout one profile at a time, mail sync watched for one full cycle
   before the next; rollback deletes that tenant's rules only.

Verification on a scratch daemon: outbound to a host not in the set refused,
IMAP sync completes, a WhatsApp message arrives, an LLM call succeeds, a
Firebase token verification succeeds; criterion 6 recorded.

## M4 — Docs and reconciliation

Owner: primary session. `docs/remote-backend.md` (multi-tenancy statement,
identity model, names, helper, egress, runbook; WhatsApp caveat removed),
`AGENTS.md`, `docs/ipc-contract.md` (`ignored` sibling), `docs/active-context.md`,
this plan's status. Criterion 8.

## Final review

After M1–M4 pass integration review: one separate end-to-end review through
the user path — a signed-in client on a hosted profile reads mail, downloads
an attachment, searches a document; a client on a sibling profile cannot see
any of it — with recorded evidence for all eight criteria.

## Risks and rollback

- **Live customers.** Scratch first; Café124 store rename in one all-stopped
  window; identity one per day, operator present, `stat` record and backup
  before each.
- **Store fork.** Dual-name code ships before any rename; a restart of an
  unmigrated daemon opens the legacy store, never an empty one.
- **Token lockout.** `rekey --verify` before the unit starts; the reverse
  `rekey` is the rollback; the shared key is kept.
- **Unit does not start.** `ProtectHome=tmpfs` + bind paths proven with
  `systemd-run` on the scratch unit before any customer unit.
- **Caddy reachability.** New socket path and tmpfiles fragment tested on
  the scratch unit with the route change first.
- **Egress wrong.** M3 is separate and per tenant; mail sync is the canary.
- **Local engine regression.** CI `tests/tools`, `tests/email` and the app's
  offline browser checks stay green; the only local changes are the basename
  rule, the search-set rule and the named `target_dir` extension.

## Parked (from the brief)

Self-serve provisioning (own brief; opens only after M2b on all six profiles,
uses the helper); operations floor; data-processor obligations (CTO);
bubblewrap for hosted `run_python`; VM per company; send/credential
separation and shared-memory poisoning; native Mac/Windows engine hardening;
app display of the `ignored` settings flag.
