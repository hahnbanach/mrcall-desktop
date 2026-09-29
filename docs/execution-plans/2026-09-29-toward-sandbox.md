---
status: approved
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
  `mrcalld`. Six live profiles, four of them one company (Café124). Pinned
  release `8d83193`.

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
`attachment_<n>`, `dir.pdf` under `downloads/`; `target_dir=<profile root>`
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
Deploy to the VPS is still to do.

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
Caddy tries the new socket path then the flat one during the window.
`/run/mrcalld` is `2751` (setgid kept for provisiond's flat socket). Every
tenant run outside the unit goes through `umask 007`. `create` refuses
while the company's legacy store exists (2a first). `delete` derives
last-holder from group membership and removes the empty group and dir.
logrotate no longer uses `su`; provisiond's status treats the drop-in as
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
unmigrate`).
Verification here: 24 new tests (`tests/memory/test_tenant_store_names.py`,
`tests/storage/test_rekey_and_encryption.py`, `tests/memory/test_offboard.py`),
the writer-inventory and retention guards updated for the offboard call
site, full regression 1391 passed (the two known pre-existing failures
only), `systemd-analyze verify` on the rendered drop-in (only the absent
binary reported) and `security` exposure 4.4.

**Left for the host session (VM scratch first):** unit start under the
drop-in (`systemd-run` proof), Caddy reaching the new socket, the two-user
WAL test on one store, criteria 1 (all clauses), 2, 4, 5, 7; then 2a for
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
`mrcall-tenant unmigrate U` (drop-in, fragment, run dir, ownership back
to `mrcalld`, table row; keeps user and key file); start under the
transitional template, whose flat socket Caddy still serves.
Scratch-unit probe list, before any customer: unit start under the
drop-in; Caddy reaching `/run/mrcalld/<uid>/ws.sock`; fastembed loading
from the read-only cache without writing; the two-user WAL test.

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
