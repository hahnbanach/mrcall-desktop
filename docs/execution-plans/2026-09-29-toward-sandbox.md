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

## Remaining work (index, as of 2026-10-02 after `35f8840`)

This is the entry point for any session picking this up. Each item names:
- **where it runs:** *cloud* is a session on this repository with no host
  access; *scratch* is the Remote Control session on the scratch VM; *VPS*
  is the Remote Control session on desktop.mrcall.ai;
- **when it may start;**
- **when it is done.**

Git is the only channel between sessions. Every session records its
result in this plan and pushes to `main`. Rules that hold for every item:
- never print `MEMORY_KEY`, `ENCRYPTION_KEY`, tokens or voice-file values;
- stop and roll back on a host, daemon, store or app anomaly;
- a defect in your own check script is fixed and the check re-run (the
  stop rule in the "VPS rollout" record).

State: five profiles, production@ included, run as their own users. Ivan
(`ZwpLepFDghWhQEBO4WJRIFcEr7p1`) and Riccardo
(`YZNI2ZLDjFOxcvF0zmptW3vRZxV2`) are still `mrcalld` on the shared key,
excluded by the CTO. All four company stores have derived names. M3 has
not started.

1. **R1 — 2b for Ivan and Riccardo.** *VPS.*
   - *Starts:* when the CTO says.
   - *Procedure:* exactly the repaired sequence in "M2 record — VPS
     rollout", "Published repair and resumed 2b":
     1. a read-only rekey dry run as the daemon identity;
     2. backup;
     3. `create` → rekey with verify → verify-only → `create` → start;
     4. acceptance.

     Their app acceptance has no Firebase row to use (recorded there): the
     daemon-identity `memory-status` plus a clean start are the evidence
     unless the CTO provides a sign-in.
   - *Afterwards:* `gpasswd -d mrcalld mc-c-7aaa48b3ef85`. Café124 then
     has no `mrcalld` holder.
   - *Done:* the helper table lists all seven uids.
2. **R2 — Helper hardening.** *cloud* for the code, then *scratch* for the
   probe with two independent reviews.
   - *Starts:* any time.
   - *Must finish:* before self-serve provisioning opens (Parked).
   - *Scope:* the "Open, not changed here" list of "M2 record —
     tenant-exec probe":
     - refuse any applied drop-in that sorts after `tenant.conf`, or lives
       outside the instance's `/etc` directory;
     - `delete` refuses a uid that is not a Firebase UID (`<uid>.sock`,
       `reconcile.lock`);
     - the two voice-file forms the check and systemd read differently;
     - `save_prev` runs after the trap is armed;
     - refuse a `zylch` whose shebang is not its own venv's python, and
       an empty or comment-only voice file;
     - `unmigrate` restores the recorded profile-directory mode.
   - *Done:* both reviews APPROVED on the scratch record; merged; the VPS
     installs it through the next reconcile, and every migrated unit
     re-applies as `ready`.
   - *R_2 record (2026-10-02):* existing approved brief and R2 scope/plan
     re-reviewed independently: A (mechanisms) APPROVED; B (conformance)
     APPROVED. Implementation by this worktree's primary agent; both will
     separately review the resulting code and scratch evidence.
     Sequence: implement the six guards; exercise hostile and accepted
     controls on scratch, including partial-backup failure and mode
     round-trip; review/fix/re-review; merge; record VPS reconcile evidence.
     Refusals must preserve existing unit/voice state. Legacy migrations
     without a recorded original mode must not invent one. Restore the
     installed helper and test fixtures on an anomaly; do not change R4's
     firewall/resolver state. No secret or voice value in evidence.
   - *Machine coordination:* scratch VM presa da R_2 dalle
     2026-10-02T17:30:52Z. Reservation is effective only after push and a
     refreshed check that R_4 is not using the machine.
3. **R3 — Close the rollback window.** *VPS.*
   - *Starts:* seven days after the last 2b with no rollback, and not
     before R1.
   - *Removes:*
     - the root-only `/root/backup-2a-*`, `/root/backup-2b-*`,
       `/root/prod-2b/migration/` and `/root/k3-pins-backup/`;
     - the old-key copies (with `shred -u`).

     The record of what existed stays here.
   - *The shared key:* `ENCRYPTION_KEY` in `/etc/mrcalld/env` stays as
     long as any unit runs as `mrcalld`, or provisiond creates new
     profiles under the template before `create`. Establish which from
     the code before removing it, and record the answer.
   - *Done:* recorded here.
4. **R4 — M3, egress bound per daemon** (section below). *scratch* first,
   then *VPS* one profile at a time, each watched over a full mail sync
   cycle.
   - *Starts:* any time on scratch. On the VPS only after a mechanism
     record on scratch, with two independent reviews, covering every
     line of the M3 verification.
   - *Done:* all migrated tenants have their per-user set; criterion 6 is
     recorded.
5. **R5 — M4 and the final review** (sections below). *cloud*.
   - *Starts:* after R1–R4.
   - *Done:* the final end-to-end review is recorded for all eight
     criteria, and this plan's `status` is `completed`.

R1, R2 and R4 are independent of each other. R3 waits for R1, and R5
waits for all of them.

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
each — post-gate record). **production@ is migrated through an operator
declaration**, not by editing its drop-ins: its own `ExecStart` also
starts voice with `--voice-config`, which the standard command omits.
The live command is in [the VPS preflight](#m2-record--vps-preflight-and-proposed-café124-window-2026-10-02);
the declaration, what the scratch VM proved of it and the steps added to
its 2b are in the [tenant-exec probe](#m2-record--tenant-exec-probe-2026-10-02).
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

*2b, per profile U, after its company's 2a (one per day as planned;
the [CTO decision](#m2-decision--compressed-rollout-2026-10-02-cto) puts
them in one window, each accepted before the next; what the helper of
`0dc122d` additionally refuses for any unit, and the drop-in check before
each 2b, are under "For every 2b" in the
[tenant-exec probe](#m2-record--tenant-exec-probe-2026-10-02)):* steps 1–6 of the
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
  drop-in; anything else `create` refuses and says why — except for a
  unit with a declaration in `/etc/mrcalld/tenant-exec/<uid>`
  ([tenant-exec probe](#m2-record--tenant-exec-probe-2026-10-02)).
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

- **production@ cannot be migrated with this helper** (`267e365`;
  superseded by the declaration of the [tenant-exec probe](#m2-record--tenant-exec-probe-2026-10-02)).
  Its drop-in sets
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
  the REV-0 build; on `267e365` only its refusal, FINAL-5 — since
  exercised through the declaration, tenant-exec probe TE-F1, TE-RB,
  TE-F4); a start of
  the template unit after a stopped first migration (FINAL-5 shows the
  leftovers gone and `User=mrcalld`, not a bind).
- `docs/remote-backend.md` on main (mnemonic upgrade, "the per-unit pin")
  proposes a second checkout with its own venv selected by a drop-in that
  resets `ExecStart=`. A unit pinned that way is refused by `create`, like
  production@: pin by `PYTHONPATH`, or declare its interpreter
  (tenant-exec probe).
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

**production@ command classification — helper extension required**
(since written and probed: [tenant-exec probe](#m2-record--tenant-exec-probe-2026-10-02)).
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
   tenant-exec fixes (`5ee01d4`: the bootstrap ran from `499ca09` with
   that helper — VPS rollout record below; `0dc122d` reaches the host
   with the first reconcile after the tenant-exec record is on main),
   the VPS operator runs
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

#### Resume from `aa57697`, clarified stop rule (2026-10-02)

The CTO authorized resuming the same compressed window, now including
production's final 2b. The stop rule distinguishes a broken operator check
(import, arguments, parsing) from a real host/daemon/store/app anomaly:
repair and repeat the same check for the former; stop with the prescribed
company/profile rollback for the latter. The earlier attempt remains
historical above. No production test call is authorized; voice acceptance
uses `calls_available`.

**Bootstrap, 13:53 UTC.** The corrected guarded runner was installed
under `/root/m2-rollout-20261002/`; its original failed copy was retained.
Exactly one further reconcile pulled the service checkout to `aa57697`
and restarted the seven unmigrated daemons. `Result=success`,
`ExecMainStatus=0`; both the unit and tagged `zylch-reconcile` journal
show updater exit 0 and seven profiles, `code_changed=1`. Installed helper
SHA256 is `a90d1bc081978c4716d20d3ecd1f6cd7f5caa78d78283843ae21647e6c2a9eae`,
matching the checkout, with silent `cmp`. Generated explicit log paths,
both logrotate debug checks, seven active `mrcalld` units and empty tenant
list passed. Authenticated provisiond status GET passed on the Unix socket
and public HTTPS (200, `active`); unauthenticated GETs returned 401.
Tokens stayed in memory. Production's ledger had ten closed and zero
unresolved calls; local/public health returned 200 with
`calls_available=true`, unsigned callbacks 401/401/400.

The first immediate post-restart health request raced listener startup.
The check gained a bounded readiness wait; the same health/ledger/callback
check passed without another reconcile. This was not recorded as a daemon
failure or used to waive a persistently unavailable listener.

**K3, 13:57–13:58 UTC.** The `90-daily-budget.conf` PYTHONPATH drop-ins of
`C06xHKoRcfdz94FaLPKuJuo0xVo1`, `YZNI2ZLDjFOxcvF0zmptW3vRZxV2` and
`ZwpLepFDghWhQEBO4WJRIFcEr7p1` were moved intact into root-only
`/root/k3-pins-backup/<uid>/`, never deleted. After daemon reload and each
restart: active `mrcalld`, `NRestarts=0`, live `/proc` command from the
checkout, no release PYTHONPATH, same-environment `zylch.__file__` from
`/home/mrcalld/mrcall-desktop/engine/zylch/__init__.py`, no startup errors.
Backup hashes match the original files. Production retained its three
drop-ins and `mrcall-voice-cafe124-phone-md-5ebe3fa` pin. Its exact-source,
AST-extracted path functions were probed with synthetic files under its
actual interpreter: derived present resolves to derived in serving mode;
legacy is used only when derived is absent. Its `home.py` exists.

**Authenticated-client prerequisite.** The actual app
`WebSocketRpcClient`, transpiled from repository source, made two real
Firebase-authenticated opens with a forced reconnect and successful mail
and `memory.status` reads for support, Mario, production, Hxi… and x59….
This is headless app transport evidence, not a renderer/GUI observation.
YZNI… and Zwp… have no local/server descriptor or stored Firebase row:
read-only queries as their daemon identity found zero OAuth rows. Their
daemons and memory are healthy; no authenticated request was attempted or
rejected. The initial checker label `HOST/APP ANOMALY` overstated this
missing-evidence condition and was corrected. The CTO subsequently
excluded Riccardo (`YZNI…`) and Ivan (`Zwp…`) from 2b for now. All-company
2a was still accepted with memory checks as the daemon identity; their
identity remains `mrcalld`. Production stays last among the selected profiles.

**2a, 14:07–14:08 UTC.** All four companies were relocated under the root
process's inherited fd 9 on `reconcile.lock`. Each company's full holder
set was stopped before the root-only backup, ownership record and
no-open-store-descriptor check. The maintenance CLI ran as `mrcalld`
with umask 007, then the installed helper's `store`, then all holders
restarted. The resulting company groups are:

| Company group | Holders | Accepted UTC |
|---|---|---|
| `mc-c-556508c0bf3f` | `9nXeYF8OXPetUFsSP4zDC3F2i673` | 14:07:20 |
| `mc-c-6bf6c0996296` | `x59G6SnymAN2lkFny0JDGJgdFz33` | 14:07:32 |
| `mc-c-ca1cdaf60f12` | `HxiZhWEBoRUarPzqX8eRWP21FuJ3` | 14:07:50 |
| `mc-c-7aaa48b3ef85` (Café124) | C06…, Gn9… (production), YZNI…, Zwp… | 14:08:17 |

Café124's four holders were stopped together at 14:07:51 UTC, including
production; its acceptance finished within the ten-minute decision limit.
All seven resolved the derived name and reported memory available; legacy
stores were absent. Database/WAL/SHM files have their company group and
0660 mode. Actual app-client mail/memory checks passed for the five
credentialed profiles. Production's original drop-in hashes, pinned
release, ten-closed/zero-unresolved ledger and local/public health/auth
baseline remain unchanged.

The first support-store attempt at 14:04 UTC was unnecessarily rolled
back because the check searched for `available: True` instead of parsing
CLI whitespace (`available:    True`). Its actual memory and app checks
were healthy. The parser was corrected, the same status check passed,
and 2a was repeated from the verified legacy state with a separate backup;
all four company acceptances above then passed. Original and retry backups
are retained. No key or legacy capability-bearing filename was printed.

Root-only resumed evidence is in
`/root/m2-rollout-20261002/resume-rollout.log`; runners and per-company
`/root/backup-2a-<group>-20261002-resume-retry1/` backups are retained.
The narrow reviewed resume brief/plan are under
`/tmp/mrcall-ai-kit/sandbox-resume/`. Independent 2a review also compared
SQLite integrity and backup counts: all four copies/live stores are valid;
Café124's stopped backup already held 1,468 blobs, matching immediate
acceptance. Subsequent automatic consolidation removed 19 live rows with
19 committed operations, aliases to live keepers and preserved original
content in `blob_versions`; that change was not relocation loss.

**First 2b attempt: support, 14:14 UTC.** The embedding cache was warmed
as `mrcalld` (dimension 384) and checkout readability passed. Under fd 9,
`9nXeYF8OXPetUFsSP4zDC3F2i673` was stopped and backed up root-only;
first `create` made its tenant/key/drop-in. Root `rekey --verify` exited
2 after rewriting two rows, reporting seven Google Calendar inner-field
failures (`access_token`, `refresh_token`, `scope`, `expires_in`,
`token_type`, `email`, `id_token`). The inverse rekey also exited 2 on
those fields. With that UID still stopped, the original database and
its recorded WAL/SHM were restored from the pre-create archive, failed
versions retained root-only, and `unmigrate` was run for that UID only.
Its original profile-directory mode was restored. It returned active as
`mrcalld`, with successful authenticated app mail/memory reconnect and
zero new startup error lines. No other profile entered 2b; all four
company stores remain derived and the helper table returned empty.
Production retained its pin and healthy voice baseline. The new tenant
user/key remain, as the helper's rollback contract permits.

**Repair decision after recovery.** The CTO asked to fix the blocker and
continue, rather than end the work at rollback. Read-only independent
verification proved recovery credentials byte-identical to the original
backup. Both the original Google Calendar outer JSON and its seven
`encrypted:`-tagged payloads were plaintext; none was Fernet-shaped.
The old source key matched the shared host key (boolean comparison only).
The legacy credential writer prefixes `encrypt()` even when local
no-key encryption returns plaintext; the current reader supports that
encoding, but the rekey walker incorrectly assumes every tagged payload
is Fernet. Wrong-key/corrupt ciphertext must continue to fail.

The reviewed repair brief/plan under the same scratch directory add a
minimal rekey compatibility fix, regression and backup-copy forward/
verify/idempotence/reverse proof before deployment. Support is retried
first, then the remaining selected ordinary profiles, production last
through the exact tenant-exec runbook. Ivan and Riccardo remain excluded.
Results of that repair and continuation follow here.

**Published repair and resumed 2b.** Commit `926ef84` adds the narrow
legacy tagged-plaintext compatibility path. Fernet-shaped payloads that
cannot decrypt still fail, including truncated ciphertext; verification
is unchanged. The focused suite passed 15 tests and the complete storage
suite passed 131 tests. A disposable copy of support's original backup
passed forward rekey (two rows, zero failures), verify, idempotence,
reverse rekey and verify, with decoded credentials preserved. Fresh
milestone and separate final repair reviews approved it before push and
deployment. The service checkout was pulled to `926ef84` under fd 9;
the helper still matches silently. That CLI-only deployment did not run
another reconcile or restart daemons.

The revised runner now tests all credential rows, read-only as the
current daemon identity, through the corrected pure rekey walker before
stopping a profile. Each selected ordinary 2b retains its own root-only
`/root/backup-2b-<uid>-20261002-repaired/` archive and old key. The sequence
is first `create`, root forward rekey with verification, verify-only,
second `create`, start and acceptance, all under root fd 9. Accepted
profiles stay migrated while the next is processed. The rollback window
and backups remain open.

| Ordinary profile | Accepted UTC | Daemon identity | Rekey verification |
|---|---|---|---|
| support@, `9nXeYF8OXPetUFsSP4zDC3F2i673` | 14:29:35 | `mc-16d5836d57be` | 2 rows, zero failures, twice |
| Mario Café124, `C06xHKoRcfdz94FaLPKuJuo0xVo1` | 14:34:06 | `mc-b75843f3770f` | 1 row, zero failures, twice |
| Mario Gmail, `HxiZhWEBoRUarPzqX8eRWP21FuJ3` | 14:42:34 | `mc-0c008879b605` | 2 rows, zero failures, twice |
| Mario MrCall, `x59G6SnymAN2lkFny0JDGJgdFz33` | 14:45:31 | `mc-fd58d04802f1` | 1 row, zero failures, twice |

For these acceptances the actual authenticated app transport opened twice
with a forced reconnect; both mail and memory RPCs succeeded. Each tenant
also passed `memory-status`, refusal of another profile's environment/key,
profile ownership, company-store sidecar permissions, unchanged operator
drop-ins and zero new startup error lines. Each of the three singleton
companies has no remaining `mrcalld` holder, so that user's membership in
its company group was removed after acceptance review. Café124 retains `mrcalld` membership
for the excluded Ivan/Riccardo daemons. The GUI was not exercised.

**Production, exact tenant-exec runbook.** Fresh preparation review caught
and repaired errors in the acceptance runner before deployment: operational
voice/filesystem failures now enter recovery; stop and backup preparation
are protected; all post-start subprocess and HTTP operations share a
270-second deadline, leaving 30 seconds before the five-minute decision
boundary. Read-only company inventory happens before the stop. These
were check-script defects, not host failures.

The required release credential scan covered 8.7 GB of preserved releases.
An initial 180-second probe budget was too short; the same ASCII patterns
were rerun with the C locale and a longer pre-stop budget. The complete
`grep -rIlE` returned 0 with 68 filenames, comprising 12 distinct file
contents. Every hit was opened privately: synthetic test fixtures, PEM
format markers/comments, public case/license identifiers, a documentation
placeholder and a package checksum; none was a credential. The five
`find ... -name '.env*' ! -name '.env.example'` hits were identical public
`.env.example.j2` templates with empty or unexpanded secret fields. Exact
full-content hashes and classifications are root-only under `/root/prod-2b/`.
The initial classifier's refusal of public test fixtures was corrected;
classification resumed from the fresh, complete root-only scan evidence,
checking every hit again against its approved content hash. Unknown or
changed matching content is refused. A separate preparation review approved
the classification before `chmod -R go=rX /home/mrcalld/releases`.

Pre-checks 1–6 passed, recorded from **15:02:05 UTC**, before the declaration:

- Helper SHA and silent checkout comparison passed; systemd 255 prints
  the expected one-environment-file-per-line format.
- Root-only `/root/prod-2b/` holds the original unit/show, all three
  operator drop-ins and hashes, profile mode `0770`, and environment
  **names**. Effective original files are exactly the shared file and
  `/etc/mrcalld/voice-cafe124.env`; all drop-in paths/order passed.
- Absolute voice executable:
  `/home/mrcalld/releases/mrcall-voice-cafe124-phone-md-5ebe3fa/venv/bin/zylch`.
  Its shebang and complete interpreter chain passed. The real release has
  `home.py` and its exact extracted path functions choose the derived store
  when present, with legacy fallback. No real SQLite store was opened by
  that root path probe.
- Voice file root-owned, regular and not a link; CR, trailing-backslash,
  off-allowlist and odd-quote counts zero. `grep -vE` used the helper's
  actual `VOICE_ALLOWED` pattern; no nonmatching variable name existed.
  `/etc/mrcalld` is `0755`, so `o+x` was already present.
- Read-only ledger as `mrcalld`: ten closed calls, zero unresolved.
  Local/public health 200, `calls_available=true`; unsigned answer/event/live
  401/401/400 on both paths. Last company-notes preparation status:
  `supported`, with company knowledge enabled.

The exact two bare declaration lines were then written `0600 root:root`
to `/etc/mrcalld/tenant-exec/Gn9IcuWzYyY7DBMHkVUGB7bIiTp2`:
the absolute `INTERPRETER` above and
`VOICE_CONFIG=/etc/mrcalld/voice-cafe124.env`. Operator drop-ins were not
edited. Immediately before stopping, the voice baseline was repeated with
no call in flight. Under root fd 9, the stopped profile was backed up in
`/root/prod-2b/migration/`, then `create` → root rekey (one row, zero failures)
→ verify-only (one row, zero failures) → `create` → start ran successfully.
Before start, the effective command used the same voice executable, tenant
`<uid>/ws.sock` and `<uid>.voice.env`; `User=mc-18f855d535e9`,
`ProtectHome=tmpfs`, with only the voice copy then the tenant key file.

**Production accepted at 15:02:37 UTC, 12.77 seconds after start.**
The daemon was active with `NRestarts=0`; port 8787 belonged to its main
PID 3642907. Local/public health and unsigned callbacks matched baseline;
the ledger was read as the tenant in `mode=ro`, still ten closed and zero
unresolved. No baseline environment name was lost; only `MEMORY_DB_DIR`,
`PYTHONDONTWRITEBYTECODE`, `ZYLCH_HOME` were added. The unchanged release pin
was visible inside the mount namespace. New journal/profile-log error
matches were zero, and company-notes status remained `supported`. The
actual authenticated app client connected and reconnected, read mail and
available company memory (1,397 blobs at acceptance); tenant CLI confirmed
1,397 blobs and 197 facts. Derived store and sidecars retained `0660` with
the company group; no legacy store was recreated. All three original
drop-in hashes matched. No rollback trigger fired and no test call was
made: voice acceptance is explicitly on `calls_available`.

**Final runtime acceptance, 15:04 UTC.** All seven daemons are active with
zero restarts: five `mc-…` identities and the two excluded `mrcalld`
identities. Every profile's daemon-identity `memory-status` is available;
all four company stores remain derived with group-writable sidecars and
no recreated legacy. All six nonproduction profiles have no `PYTHONPATH`
pin. The helper table contains exactly the five selected UIDs; helper
comparison remains silent. Generated logrotate has one shared stanza for
the two excluded profiles and one stanza per migrated user. Both per-file
and global `logrotate -d` exit 0 without errors or duplicate entries;
no actual rotation was run. Cross-profile environment/key reads are denied
for all five tenants, production included. Provisiond remains active and
the voice baseline passes again as the tenant. Authenticated provisiond
socket/public GET acceptance is recorded in the completed bootstrap above.

The explicitly requested main pull and K3 unpinning also put M5–M9
mnemonic source in the checkout imported by six nonproduction daemons:
`19639d2` is an ancestor of deployed `926ef84`. Production voice retains
its older release. This is verified source presence, not a new mnemonic
product/corpus acceptance; AC 5 and the separate rollout gates remain open.

The selected rollout is complete; **M2 remains partial** because Ivan
(`ZwpLepFDghWhQEBO4WJRIFcEr7p1`) and Riccardo
(`YZNI2ZLDjFOxcvF0zmptW3vRZxV2`) were explicitly excluded from 2b.
Self-serve provisioning stays closed. Their pins were removed and their
company's all-holder 2a completed before that exclusion; neither entered
identity migration. Shared-key/profile/store backups and the production
declaration remain in place for the rollback window. M3 is unexecuted.
No secret values or key-bearing legacy filenames are in this record.

Fresh individual acceptance reviews approved all five selected identities;
a separate final end-to-end review approved the runtime evidence and the
narrow publication diff. Mechanical documentation checks are clean,
`git diff --check` passes, and both rekey files pass Black. The remaining
test diff only formats three assertions; its AST is unchanged. Real
secret-value and JWT comparisons against the intended diff found zero
matches. The global documentation baseline and unrelated work are untouched.

### M2 record — tenant-exec probe (2026-10-02)

Same scratch VM (root disk 63 % before, 71 % after the fake release; swap
1 GB, as found — it had already been shrunk). Subject: the operator
declaration `/etc/mrcalld/tenant-exec/<uid>` (`read_tenant_exec`, commits
`b6d098f`, `5ee01d4` on main), with which `create` migrates a unit that
runs its own interpreter and the production voice listener. Log:
`/root/m2-probe.log` on the VM from `## TE-0`, scripts
`/root/m2-probes/a0…a13-te-*.sh`. The helper changed three times during
the probe and the battery was repeated on each build: the log's notes say
which blocks are superseded, and only the sections named below are
cited.

**The stand-in for production@.** Profile `scrP1…1`, built as production@
is today: created and seeded by `mrcalld` under the shared key, a holder
of company A's already relocated store (A1 migrated and running beside
it), and three operator drop-ins with the preflight's names. The
preflight records only the names of `90-…` and `95-…` and the command of
`99-…`; their contents here are the probe's assumption, taken from the
voice plan's description: `90-…` and `95-…` pin the older release, `95-…`
and `99-…` each reset `ExecStart`, `99-…` pins `PYTHONPATH` to the voice
release, loads the voice file as an `EnvironmentFile` and runs `<release>/venv/bin/zylch -p
<uid> serve --unix /run/mrcalld/<uid>.sock --voice-config
/etc/mrcalld/voice-fake.env`. The release
`/home/mrcalld/releases/mrcall-voice-fake-499ca09` is main `499ca09b`'s
engine tree with its own venv (`pip install -e`, plus `aiohttp`, whose
install is the one command of this probe that was not logged); its
`zylch` is pip's console script, shebang `<release>/venv/bin/python3.11`,
a link to `/usr/bin/python3.11`. The voice file is `0640 root:mrcalld`
and holds fifteen fake variables, all inside the allowlist: the fourteen
`load_production_config` reads and the probe's stub switch.

*What is fake, and what that leaves uncovered.* The engine is main's, not
the voice-line release `5ebe3fa` production@ runs (that commit is not on
origin). The listener is the real one — real configuration loader, real
ledger `voice-production.db` in the profile, real aiohttp application on
`127.0.0.1:8787` — except for **one probe-only change in the fake
release**: `prepare_carrier` returns at once when
`VOICE_PROBE_STUB_ADMISSION=1`. The stub skips the **whole** of
preparation, the local half included: reading the profile's voice
binding and agent configuration from `zylch.db` (`snapshot_for_call`),
the ledger limits, and the remote verification of the business. Without
it the unit does not start: the log shows "admission unavailable during
preparation" and a `failed` unit (TE-2b), not which step failed — the
scratch profile has no voice binding, so it may well be the local one.
With the stub `/healthz` answers `calls_available: false`, for the same
unrecorded reason.

**Not covered here**; the runbook below has a check on production@ for
each, except that the release's own tables rest on the start-time
self-check, `calls_available` and the journal:

- preparation as the tenant inside the sandbox — the voice binding and
  agent configuration read under `HOME=<profile>`, then StarChat,
  Firebase, Vonage and OpenAI reachability: `calls_available: true`;
- a call;
- `VOICE_COMPANY_KNOWLEDGE_ENABLED=1` (its privacy check on the profile
  was run by hand as the tenant in the daemon's mount namespace and
  passes — TE-K; the rest needs the remote business);
- the public tunnel, and a signed carrier or OpenAI callback (unsigned,
  `/vonage/answer`, `/vonage/event` and `/openai/live` answer 401/401/400
  on the migrated unit — TE-VON; main's listener serves all three);
- the release `5ebe3fa` itself: any path it writes outside the profile
  and the company store (the sandbox is `ProtectSystem=strict`,
  `ProtectHome=tmpfs`, `PrivateTmp`), and tables only it knows — here
  `rekey` and the release are the same code, on the VPS the checkout's
  `rekey` rewrites a database the release wrote;
- what the real unit loses from its environment: `tenant.conf` resets
  `EnvironmentFile=` and moves `HOME` to the profile, and here the shared
  env file and the drop-ins were the probe's own;
- the mode of `/etc/mrcalld` on the VPS (`0755` here; the tenant must
  traverse it);
- an authenticated app session (Caddy 401 only, as in every scratch
  pass).

**Defects found in main's helper (`5ee01d4`, sha256 `594b7375…`) and
fixed.** 15–18 by the probe, 19–24 by review A on `5ab4576`
(`/root/te-reviewA.log`), each reproduced on the VM before the fix
(numbering continues):

15. **The shebang check followed the link and judged only its target**
    (TE-D15). A console script whose python is a link from a `/home` path
    the sandbox hides (`#!/home/mrcalld/venv-elsewhere/bin/python →
    /usr/bin/python3.11`) was accepted; the migrated unit died with
    `203/EXEC … No such file or directory`. Now every name on the way
    must be in `/usr` (or `/bin`, `/sbin`, `/lib*`, `/etc/alternatives`),
    the releases or the checkout, with no link among the directories
    under the release trees and no `..` (`sandbox_sees`, `ba669ed`).
16. **A declaration with a misspelt key was a valid empty declaration**
    (TE-D16). It switched off the refusal of operator `ExecStart`
    drop-ins and the unit migrated onto the standard command line (not
    started here): no `--voice-config`, nothing in the output. A
    declaration now holds only `INTERPRETER=` and `VOICE_CONFIG=` lines
    and comments, each key at most once, at least one of them
    (`ba669ed`), and no quote — `VOICE_CONFIG=""` was the same hole
    (review A; `0dc122d`).
17. **`INTERPRETER` naming a directory** was refused by a failing
    `head(1)`, exit 1 and no `[tenant]` error; now a named refusal
    (`ba669ed`).
18. **A refused `create` deleted the voice copy a migrated unit still
    loads** (TE-D18 on `ba636e8a…`). With the declaration moved away —
    by hand, or found so by the nightly reconcile's `create` — the copy
    was removed first and the `ExecStart` refusal came after;
    `tenant.conf` still named the copy and the next restart failed with
    "Failed to load environment files". The stale copy is now removed
    only after `tenant.conf` has been rewritten and verified (`5ab4576`).
19. **A carriage return went through the voice allowlist** (A-T1).
    `VOICE_X=1\rHOME=/tmp/evil\rPYTHONPATH=…\rLD_PRELOAD=…` is one
    allowed line to `grep` and four assignments to systemd: `create`
    exited 0 and the migrated unit's environment had `HOME`,
    `ZYLCH_HOME`, `PYTHONPATH` and `LD_PRELOAD` from the file
    (`ENCRYPTION_KEY` did not win: the key file is read last). A
    trailing backslash, an open quote, `export KEY=` and an indented or
    form-fed key were also read differently by the two (A-T2). The file
    is root's, so this was a broken guard, not a tenant's way in. Now
    each of those is refused, and the **copy** is what is checked, then
    renamed into place (`0dc122d`).
20. **A drop-in sorting after `tenant.conf`, or one under `/run`,
    overrode identity and sandbox while `create` said "ready"** (A-T3):
    `User=mrcalld`, `ProtectHome=no`, the shared key file after the
    per-profile one. Only a late `ExecStart` was caught. Step 6b now
    also requires the effective `User`, `ProtectHome=tmpfs` and exactly
    the voice copy then the key file as `EnvironmentFiles` (`0dc122d`).
    `User` and `ProtectHome` are probed (TE-N7, TE-M); the
    `EnvironmentFiles` comparison is a backstop no probe reaches, because
    a drop-in that loads another file is refused earlier by defect 21's
    check.
    Older than tenant-exec; production@'s `90-/95-/99-` sort before
    `tenant.conf`.
21. **An operator `EnvironmentFile` other than the voice file was
    dropped without a word** (A-T10): `tenant.conf` resets the list.
    `create` now refuses a drop-in that loads one and says to move the
    variables to `Environment=` lines (`0dc122d`). This also holds for a
    declaration without `VOICE_CONFIG` while `99-…` still loads the
    voice file (TE-V).
22. **A refusal on a migrated profile came after `tenant.conf` and the
    copy had been rewritten** (A-T6): the unit would restart onto files
    nobody accepted. `create` now keeps the previous two and puts them
    back on any refusal (`0dc122d`). TE-M7 is the case that shows it: the
    declaration cut to `VOICE_CONFIG` only and the voice file edited, so
    both files change, then a pin step 6c refuses — the helper prints
    "wrote …/tenant.conf", then the error, and afterwards `tenant.conf`,
    the copy, their owners and modes, the effective command and the pid
    are those of before, with no temporary file left. Of TE-M's six
    refusals on the running migrated unit (all identical before and
    after), M2 restores a replaced copy; M1, M3 and M5 are refused before
    `tenant.conf` is written (M3 and M5 after the copy was installed
    again with the same content), and in M3b and M4 the new `tenant.conf`
    equals the old one, so the helper leaves the file: it replaces it,
    and prints "wrote", only when the content differs. Review A's second
    pass repeated it at six points of
    `create` and with thirty runs killed by a signal (B-R3, B-R3b in its
    log).
23. **Accepted interpreters that cannot run** (A-T4): an `env` shebang,
    a `/bin/sh` trampoline, a file with no shebang, the venv's `pip`.
    `INTERPRETER` must now be a file named `zylch` whose shebang is a
    `python*` the sandbox sees (`0dc122d`).
24. **`<uid>.voice.env` was a valid uid** (A-T5): `delete` of it removed
    `<uid>`'s voice copy. Refused in `check_uid`. And **a first `create`
    ran under a running unmigrated daemon** (A-T7), replacing its live
    socket by the link and re-owning its tree: it now refuses a unit
    that is not stopped (`0dc122d`; the runbook always stopped it).

Final code: **`0dc122d`** on `claude/m2-scratch-probe` (= main `499ca09b`
+ `ba669ed`, `5ab4576`, `0dc122d`: the helper only), helper sha256
**`a90d1bc0…`**, installed on the VM by `update-daemons.sh` from origin
(TE-FINAL2-0, with the migrated declared unit running: `create`
re-applied, hash equal to the checkout's). **Every result below is from
that helper**: TE-FINAL2-0, TE-M, the TE-D18, TE-V and TE-DEL after it,
the last "FINAL RUN" block (TE-2a … TE-N9, TE-F1 … TE-F4), the last
TE-K, TE-M7, TE-O0 … TE-O4 and TE-VON; the log's notes say which earlier
blocks are superseded.
It is **not on main** until this record's gate passes; main's helper
until then is `594b7375…`, and that is the one the VPS installed at its
bootstrap from `499ca09` (VPS rollout record above): the build with
defects 15–24.

**Before migration** (TE-2a): the unit runs as `mrcalld` on the flat
socket from the release venv; `:8787` is bound by its main pid, `/healthz`
200, an unsigned `POST /openai/live` 400, Caddy 401, the release's
marker in the journal.

**Refusals** (TE-N0…N7, 83 cases). Each `create` exits 2 with a named
error, and after each: no `tenant.conf`, no tmpfiles fragment, no voice
copy, no run dir, no table row, every file of the profile still
`mrcalld`'s, the effective `ExecStart` the baseline one. In the 79 that
are refused before `tenant.conf` is written the unmigrated unit was
running, and **the running process is untouched** (same pid, `:8787`
still bound); the last four are refused after it is written, so the unit
was stopped for them as the runbook has it, and the undo removes what
was written. Two of the after-lines differ by the probe's own doing (the
log's closing note): one shows the `EnvironmentFile` line the probe had
added to the operator's `90-…`, the other the probe's late `ExecStart`
drop-in still in place when the line was printed.
The user, its membership of the company group and the key file a refused
first `create` made stay (as in defect 13). The cases:

- *no declaration* (1) — the operator `ExecStart` drop-ins are refused
  as before;
- *voice file* (20) — outside the allowlist: `HOME=`, `ENCRYPTION_KEY=`,
  `PYTHONPATH=`, `LD_PRELOAD=`, an indented `ZYLCH_HOME=`, `export
  MEMORY_DB_DIR=`, lower case, `VOICEX=`, `XVOICE_A=`, a bad line in the
  middle; read differently by systemd: carriage returns inside a line,
  CRLF throughout, a quoted two-line value, an open quote running on to
  an allowed line, a backslash continuation before a bad line and
  before an allowed one, a comment ending in a backslash, `export
  VOICE_E=`, a form feed before the key, a space before `=`;
- *`INTERPRETER` or `VOICE_CONFIG` systemd would split or expand* (10) —
  a space, a tab, `%i`, `%%`, `${X}` inside the path, a relative path
  (`$HOME/…` is refused as not absolute);
- *links* (8) — a link to the script, a linked directory on the way, the
  venv's `python3.11`, `..`, `/./`, `//`, a linked voice file, a linked
  declaration;
- *outside the bound trees or not a runnable `zylch`* (18) — `/opt/…`,
  `/usr/bin/python3.11`, the venv's `pip`, a real script in
  `/home/mrcalld/releases-b`, an absent path, a directory; a `zylch`
  whose shebang is in `/opt`, hidden under `/home`, through a linked
  directory, through two hops, through a relative `../` link, missing,
  relative, with `..`, `env`, `/bin/sh`, absent altogether; a `0700`
  script;
- *ownership and kind* (9) — declaration owned by `mrcalld`, modes
  `0660 0666 0602 0620 0755`; voice file owned by `mrcalld`, missing, a
  directory;
- *a declaration that does not say what it means* (11) — misspelt keys,
  empty, comment only, a third key, a key twice, an empty value, an
  indented key, CRLF line ends, a directory, `VOICE_CONFIG=""`, a quoted
  `INTERPRETER`;
- *a valid declaration, something else in the way* (6) — the unit still
  running; an operator `EnvironmentFile` other than the voice file; and,
  unit stopped: a later drop-in with `User=mrcalld`, one under `/run`
  with `ProtectHome=no`, a later `ExecStart`, a later pin outside the
  trees.

A uid ending in `.voice.env` is refused by `create` and `delete`. After
the last case the unit is started and comes up as before (TE-N9).

**Forward** (TE-F1; runbook 2b unchanged, the declaration written first;
`/etc/mrcalld/tenant-exec` deliberately created `0700`):

- `systemctl show -p ExecStart` is exactly one command, `<release>/venv/bin/zylch
  -p <uid> serve --unix /run/mrcalld/<uid>/ws.sock --voice-config
  /etc/mrcalld/tenant-exec/<uid>.voice.env`; `EnvironmentFiles` are the
  voice copy, then the per-profile key; the shared `/etc/mrcalld/env` and
  the operator's voice file are no longer loaded. The three operator
  drop-ins are byte-identical and still applied before `tenant.conf`.
- The copy is `0640 root:<tenant>`, identical to the operator's file;
  the directory is `0711 root`; the declaration `0600 root`. The tenant
  reads its copy and cannot list the directory, read the declaration or
  read the operator's file; another tenant (A1's user), `mrcalld` and
  `caddy` cannot read the copy.
- `rekey --verify` 2/2; started: active as `mc-cae1364247ca`, 0 restarts,
  0 "self-check failed"; socket `<uid>/ws.sock` `0660 <tenant>:caddy`
  behind the flat-name link, Caddy 401.
- **`:8787` is bound by the unit's main pid inside the sandbox**,
  `/healthz` 200, unsigned `POST /openai/live` 400, unsigned `POST
  /vonage/answer` and `/vonage/event` 401 (TE-VON, on TE-F4's process;
  not probed before migration or after rollback); the journal has the
  release's marker and "production runtime module=<release>/…"; the
  process environment carries the release `PYTHONPATH`, the 15 voice
  variables, the operator's `LLM_DAILY_BUDGET_PROBE` from `90-…`, and an
  `ENCRYPTION_KEY` whose hash is the per-profile key's, not the shared
  one's. `voice-production.db` (made by the unmigrated listener) is the
  tenant's after `create`.
- In the daemon's mount namespace the release script, its python and the
  voice copy exist; A1's profile does not; as the tenant there, the copy
  is readable, the operator's voice file and the key file are not, and a
  write into the release is `Read-only file system`.
- Outside the unit, as the runbook's step 7 does it (`sudo -u <tenant>`,
  the checkout's `zylch`): `memory-status` `available: True`. A1 stays
  active; the logrotate stanza is the tenant's and `logrotate -d` reports
  0 errors.

**Re-apply and change** (TE-F2, TE-F3, TE-M, TE-V, TE-D18): `create` on
the running unit and a full `update-daemons.sh` with no new commit leave
pid and `tenant.conf` unchanged. A reconcile that pulls new code restarts
the unit like every other daemon (TE-FINAL2-0), **and with it the voice
listener**: a deploy to main is a short voice outage for production@, as
it is today for its app socket. An edit of the operator's voice file
reaches the unit by `create` then restart; a bad edit is refused, the old
copy and the running process stay. With the declaration moved away,
`create` refuses, the copy and `tenant.conf` stay and the unit restarts
(TE-D18). Applied by `create` and not started: a declaration with only
`VOICE_CONFIG` gives the checkout's `zylch` with `--voice-config`; one
with only `INTERPRETER` is refused while `99-…` loads the voice file
(defect 21); both back gives a byte-identical `tenant.conf`.

**Rollback** (TE-RB): stop, `rekey` back (2/2), `unmigrate`, start.
`tenant.conf`, the fragment, the run dir, the link, the voice copy and
the table row go, and the logrotate stanza returns to `mrcalld`; the three
drop-ins are byte-identical to the copies taken before,
the effective `ExecStart` is the baseline line, `EnvironmentFiles` are
again the shared key and the operator's voice file (untouched,
`0640 root:mrcalld`). The unit runs as `mrcalld` on the flat socket with
`:8787`, `/healthz` 200, unsigned `POST /openai/live` 400, Caddy 401, the
shared key in its environment; every file is `mrcalld`'s,
`voice-production.db` included. The declaration, the user and the key
file stay, and the second forward (TE-F4) repeats TE-F1's results with
them. One difference from the record taken before: the profile directory
is `0700`, not `0770` (`create` sets it, `unmigrate` does not put it
back; `getent group mrcalld` has no member besides the user itself —
checked on the VM, not in the log — and the unit runs). The rollback is
therefore not mode-for-mode until the operator restores it.

**Delete** (TE-DEL): the declaration, the voice copy, the drop-in
directory, profile, key, fragment, run dir, link, user and table row are
gone; no unowned file is left; company A's store stays (A1 and A2 hold
the key) and A1 keeps running. The operator's own voice file is not the
helper's and stays.

**For every 2b, not only production@'s.** With this helper `create`
also refuses, for any unit: a first migration while the unit is not
stopped (the runbook's step 2 comes before step 4, so nothing changes in
the order); a drop-in that loads an `EnvironmentFile` other than a
declared unit's voice file (move its variables to `Environment=` lines
first); a result whose `User`, `ProtectHome` or environment files are
not `tenant.conf`'s. Before each 2b, `systemctl show -p DropInPaths
zylch-server@U` lists only files of
`/etc/systemd/system/zylch-server@U.service.d/` that sort before
`tenant.conf`: a later drop-in can change what `create` does not verify
(review A, under "Open"). On an ordinary scratch profile with no
declaration and no pin (TE-O0 … TE-O4): `create` under the running
unmigrated unit is refused and the unit, its socket and its files are
untouched (the user and key file it makes stay, as for any refused first
`create`); the runbook's forward, a re-apply on the running unit, the
rollback, a second forward and `delete` go as before. The three already
migrated scratch tenants were re-applied by the reconcile with no
`FAILED` line (TE-FINAL2-0, TE-F2 — their own `ready` lines are filtered
out of that output) and by `create` directly in review A's B-R4 (`ready`
for each). The helper check of production@'s pre-check 1 below holds
for every 2b: until a reconcile after this record is on main, the VPS
runs `594b7375…`, which refuses neither a dropped `EnvironmentFile` nor
a `create` under a running unit (defects 21, 24).

**Runbook, added for production@'s 2b** (it is the last one). `U` is its
uid, `R` its release directory, `VF=/etc/mrcalld/voice-cafe124.env`.

*On the VPS, before the window — any failed line means no declaration is
written:*

1. **The helper.** `sha256sum /usr/local/sbin/mrcall-tenant` starts
   `a90d1bc0` and `cmp` with the checkout's
   `engine/scripts/server/tenant-helper.sh` is silent. A helper installed
   by hand is replaced by the next reconcile: it must come from main,
   with the first reconcile after this record is there (the nightly one,
   or an explicit `systemctl start zylch-reconcile.service`) — which
   restarts every daemon, production@'s voice listener included.
   `systemctl --version` (249 on the VM), and `systemctl show -p
   EnvironmentFiles --value zylch-server@U` prints one `<path>
   (ignore_errors=…)` per line: step 6b reads that form, and on a systemd
   that prints another every `create` on the host is refused (nothing is
   changed by a refusal) until the helper is adapted.
2. **The unit as it is**, kept under `/root/prod-2b/`: `systemctl cat
   zylch-server@U`; `systemctl show zylch-server@U -p ExecStart -p
   EnvironmentFiles -p DropInPaths`; copies and `sha256sum` of every
   drop-in; `stat -c '%U:%G %a %n'` of the profile directory;
   `tr '\0' '\n' < /proc/<pid>/environ | cut -d= -f1 | sort` (names
   only). `EnvironmentFiles` must be exactly `/etc/mrcalld/env` and
   `VF`: any other file is refused by `create` — move its variables to
   `Environment=` lines in that drop-in first (a change to the running
   unit: its own restart, before the window). `DropInPaths` lists only
   files in `/etc/systemd/system/zylch-server@U.service.d/`, each with a
   name that sorts before `tenant.conf` (digits do): `create` verifies
   only the command, `User`, `ProtectHome` and the environment files of
   the result, and a later drop-in, one under `/run` or one of the
   template's could change anything else (review A).
3. **The interpreter.** `head -1 R/venv/bin/zylch` is `#!R/venv/bin/python…`;
   `namei -l` of that path shows every hop under `/usr`, `/bin`, `/sbin`,
   `/lib*`, `/etc/alternatives`, the releases or the checkout, and no
   linked directory under `R`. `readlink -f` is not enough: it shows only
   the last target, which is defect 15.
4. **The release.** `R/engine/zylch/home.py` exists and
   `R/engine/zylch/memory/store.py` has the dual-name lookup (the
   preflight found it). If either is missing: no 2b for production@.
   `chmod -R go=rX /home/mrcalld/releases` makes every release readable
   by every tenant, so first: `grep -rIlE -e 'sk-[A-Za-z0-9_-]{20,}' -e
   'BEGIN [A-Z ]*PRIVATE KEY' /home/mrcalld/releases` and `find
   /home/mrcalld/releases -name '.env*' ! -name '.env.example'` — every
   hit is opened and is not a credential (a bare `sk-` matches ordinary
   words in a venv).
5. **The voice file.** Root-owned, not a link; `grep -c $'\r' VF` → 0;
   `grep -cE '\\$' VF` → 0; `grep -cvE
   '^([[:space:]]*(#.*)?|(VOICE_[A-Z0-9_]*|OPENAI_[A-Z0-9_]*|VONAGE_[A-Z0-9_]*|FIREBASE_WEB_API_KEY)=.*)$'
   VF` → 0; no line other than a comment with an odd number of `"` or
   of `'`. `stat -c %a
   /etc/mrcalld` has the `o+x` bit.
6. **The voice baseline**, as the VPS rollout record above took it on
   2026-10-02 around the bootstrap: production's ledger read as `mrcalld`
   with SQLite `mode=ro` — no unresolved call; `/healthz` locally and
   through the public endpoint, 200 with `calls_available=true`; unsigned
   `POST` to `/vonage/answer`, `/vonage/event` and `/openai/live` → 401,
   401, 400 on both paths (the same three answers the migrated scratch
   unit gives locally, TE-VON); the last "company notes preparation
   status=" line of the journal or the profile's `zylch.log` if
   `VOICE_COMPANY_KNOWLEDGE_ENABLED=1`.

*The declaration:* `/etc/mrcalld/tenant-exec/U`, `0600 root`, two bare
lines and nothing else — `INTERPRETER=R/venv/bin/zylch` and
`VOICE_CONFIG=/etc/mrcalld/voice-cafe124.env`. The operator's drop-ins
are not edited.

*2b steps 1–6 unchanged* (the unit is stopped before the first
`create`, which now refuses otherwise; no call in flight at the stop). A
refused first `create` changes nothing: start the unit as it is, fix,
try again. After the second `create`, before the start: `systemctl show
zylch-server@U -p ExecStart -p User -p ProtectHome -p EnvironmentFiles`
shows one command with `R/venv/bin/zylch`, `U/ws.sock` and
`--voice-config /etc/mrcalld/tenant-exec/U.voice.env`; the `mc-…` user;
`tmpfs`; the voice copy then the key file and nothing else.

*Step 7, added — each is a rollback trigger, decided within **five
minutes** of the start:*

- the unit is `active` with `NRestarts=0` and no "self-check failed" (a
  failed admission at start takes the whole unit down, app socket
  included);
- `ss -ltnp 'sport = :8787'` names the unit's main pid;
- `/healthz` says **`calls_available: true`** locally and through the
  tunnel — the first time preparation runs as the tenant inside the
  sandbox, and the one result the VM could not give;
- the unsigned callbacks answer as in the baseline;
- the names in `/proc/<pid>/environ` are the baseline's, minus nothing
  but what `tenant.conf` replaces (`HOME` changes value) and plus
  `ZYLCH_HOME`, `MEMORY_DB_DIR`, `PYTHONDONTWRITEBYTECODE`: a lost name
  is explained or it is a rollback;
- the pinned-profile check of the post-gate record (`nsenter -t <pid>
  -m -- test -e <PYTHONPATH>/zylch/__init__.py`);
- no `Read-only file system`, `Permission denied`, decrypt or
  `InvalidToken` line in the journal and the profile's `zylch.log` since
  the start (a path the release writes outside the profile; a row the
  checkout's `rekey` did not know);
- the "company notes preparation status=" line as in the baseline, when
  enabled;
- the customer's app reconnects — the authenticated check of every 2b.

A call is checked by a call: a test call to the production number with
its ledger row closed. The operators decide whether to make it before
they leave the window; without it, voice is accepted on
`calls_available` alone.

*Afterwards:* a change to the voice file is `mrcall-tenant create U`
then a restart, never an edit of the copy. **The declaration is not
removed while the unit is migrated** — `create` then refuses (the unit
keeps running on what it has) and the reconcile reports it every night.

*Rollback:* as for any profile (stop, `rekey` back, `unmigrate`, start),
then `chmod` the profile directory back to the recorded mode, compare the
drop-ins with `/root/prod-2b/`, and repeat the baseline of point 6. The
declaration stays for the next attempt.

**Open, not changed here.**

- `unmigrate` leaves the profile directory `0700` (above).
- A declared unit depends on the operator's voice file staying where the
  declaration says: if it is removed, `create` fails in the reconcile
  (stderr only, as recorded for any refused `create`) and the unit keeps
  running on its last copy.
- Nothing ties the declared `INTERPRETER`'s release to the `PYTHONPATH`
  pin in `99-…` (review A, from the code): the runbook's point 2 and the
  pinned-profile check are what show they agree.
- The operator's own voice file stays `0640 root:mrcalld`, readable by
  the deploy identity as before; tightening it would break the rollback.
- Voice-file lines the helper now refuses although both readers agree on
  them (a quoted value holding an apostrophe, a key with a space before
  `=`; in the declaration, a comment with an apostrophe): the operator
  rewrites the line.
- Review A's second pass on `0dc122d`, reproduced on the VM, not changed
  (the gate closed on that commit; the first three are covered for
  production@ by a runbook line above, the last two are reached by no
  command of the runbook):
  - the voice check and systemd still disagree on two forms — a quote
    reopened right after a closing one (`VOICE_T1="'"'`), and a
    form-feed "comment" holding a quote (a vertical tab is the same case
    from the code; its log shows the form feed). Either makes
    systemd swallow the following lines into one value: allowed variables
    are lost from the unit's environment, none outside the allowlist can
    arrive (a key starts only after a line end, and a carriage return is
    refused). The engine reads the file itself, and step 7 compares the
    environment names. The commit message of `0dc122d` says more than
    this ("reads the same to the check and to systemd");
  - step 6b checks the command, `User`, `ProtectHome` and the
    environment files; a drop-in that sorts after `tenant.conf` can still
    set `Group`, `SupplementaryGroups`, `Environment=`, `ProtectSystem`,
    `BindPaths`, `NoNewPrivileges`, `CapabilityBoundingSet`,
    `ExecStartPre` or `UnsetEnvironment`, and `create` says "ready".
    Root-written and older than tenant-exec. The fix is one rule: refuse
    any applied drop-in that sorts after `tenant.conf` or lives outside
    the instance's `/etc` directory;
  - accepted by `create` (B-R6, B-R1; not started there — that the unit
    then cannot start is from the code): a `zylch` whose shebang is the
    system python rather than its own venv's; an empty or comment-only
    voice file (the engine refuses "voice is disabled");
  - `save_prev` runs before the trap is armed: a failing `cp` there
    leaves a root-only `/etc/mrcalld/.create-prev.*` holding a voice copy
    (from the code);
  - `delete <uid>.sock` and `delete reconcile.lock` are valid uids and
    remove another unit's socket or the lock file (from the code; older
    than tenant-exec, same class as defect 24).
- The fake release, the scratch profile `scrP1…1` (migrated, running)
  and `/etc/mrcalld/voice-fake.env` are still on the VM.

**Gate.** Two independent reviews of the probe, the helper and this
record, each continued over the fixes. A (adversarial, host scripts; its
own probes on the VM, `/root/te-reviewA.log`) REVISE on `5ab4576` —
defects 19–24, no check of the installed helper, the dropped
`EnvironmentFile` — → **APPROVED at `0dc122d`** (the helper; the runbook
as of `2df77fa`, which has only gained pre-checks since), with the
follow-ups listed under "Open", none of which it judges a blocker for
production@. Its log holds its probes, not its verdicts: those are as
relayed by the lead.
B (evidence conformance, runbook) REVISE on the first draft — claims
wider than the log, an incomplete "not covered" list, a runbook with no
helper check and no executable rollback trigger — and on two revisions
(`2df77fa`, `ba08649`) — a credential scan that could not pass, the
restore shown by no case (hence TE-M7), the carrier routes (an error of
B's own first pass, corrected by TE-VON), sections of the log the record
did not name — → **APPROVED at `997aa65`**, this record included; the
wording of this paragraph about B, and of the next one, is B's.

Both verdicts are on helper `0dc122d` and on what the scratch VM can
show. **production@ can be migrated with this helper, by the runbook
above.** What the VM could not show — the list under "Not covered here",
first of all preparation as the tenant inside the sandbox on the release
it really runs — is decided on the VPS by step 7: `calls_available:
true` within five minutes of the start and its other triggers, or the
rollback. A real call is shown only by the test call the operators may
make; without it, voice is accepted on `calls_available` alone.

**After the gate.** Merged to main as `2e22bea`, a fast-forward over the
VPS rollout record (`b29242d`). The VM's checkout was put back on main
and `update-daemons.sh` pulled it (TE-MAIN): the helper it installed from
main is `a90d1bc0…`, the four scratch tenants were re-applied `ready` and
restarted with the code change, and the declared unit is active as its
tenant with `:8787` up. Nothing was done on the VPS from this session: it
keeps `594b7375…` until its next reconcile pulls main.

## M3 — Egress bound per daemon

### R_4 execution record — 2026-10-02

scratch VM presa da R_4 dalle 17:30:55 UTC (2026-10-02).
**rilasciata** on resumption: refreshed main contains R_2's earlier
17:30:52 UTC reservation. R_4 has made no host mutation or network probe;
only read PID 1's command, executable availability and systemd's running
state. R_4 defers all further host checks until R_2 releases the machine.
Lease publication precedes any host probe. After push, fetch main again and
check R2's record for a competing lease; if occupied, do no host work until
its release. This record is the only plan section edited by R_4.

Scope and acceptance remain the approved sandbox brief, criterion 6, and
the M3 verification below. R_4 is not done until the scratch evidence has
two independent APPROVED reviews and every migrated VPS tenant has its set
and a full accepted mail sync cycle. Unavailable service credentials or host
access are recorded as missing evidence, never replaced by synthetic success.

### Approved M3 outline

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
  before each (the cadence is superseded by the
  [CTO decision](#m2-decision--compressed-rollout-2026-10-02-cto): one
  window, each profile accepted before the next).
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
