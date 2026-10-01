# Telephone company notes: the source is `phone.md`, not `USER_NOTES`

For the voice-knowledge session (Café 124 company-notes conversion).

## What changed on 2026-09-30

`USER_NOTES` is retired from the engine (cs-kernel `v0.49.0`, engine
`origin/main` `706fe2a`). The operator's standing instructions live in the
clone's `company/` files and are stored in the engine as revisioned documents
of the reserved company project `operator-instructions`:

| Path | Content | Reader |
| --- | --- | --- |
| `procedures.md` | company-wide support procedures and product facts (the clone's `company/customer-service-playbook.md`) | prompt section builder, every profile of the company |
| `mail/<mailbox>.md` | that mailbox's voice, signature, language rule | prompt section builder, that profile only |
| `phone.md` | the telephone-notes source — today the same bytes as `procedures.md` | the company-notes conversion (`services/voice/company_notes.py` `_source`, via `operator_instructions.phone_source()`) |

Only `instructions.store` writes them (`projects.write` refuses the slug); the
clone's `cs instructions --commit` is the only caller. Contract:
`engine/docs/features/project-memory.md` § Standing operator instructions.
Café 124's documents are stored (space `4af9d1c4…`, all revision 1): `phone.md`
is 5,534 B, sha256 `cf61cd70…` — the playbook text: Chi siamo, quando
declinare, titolarità/escalation, divieti operativi, Prodotto, Private/White
label, Procedure ricorrenti, cosa non è posta. The voice/signature/format
sections of the old `USER_NOTES` are NOT in it (they are `mail/<mailbox>.md`),
which is what the converter's prompt excluded anyway.

## What this means for the conversion

- The digestion stays. Its source changes: `_source()` reads `phone.md` from
  the bound company store (the tree on local `main` already does this since
  `f8c1301`; `source_revision` is part of the cache key). Nothing reads
  `USER_NOTES` any more; the profile `.env` line is inert and will be dropped.
- The paid conversions cached against the `USER_NOTES` digest will not match
  the `phone.md` digest. One new conversion per source revision is expected.
- `production@` (`Gn9IcuWz…`) still runs `releases/mrcall-voice-cafe124-c3f95bb`,
  built as base `64d7cc5` + `cafe124-company-notes-v8.patch` with
  `source_reader: unchanged production USER_NOTES contract from base`. That
  release has no `operator_instructions.py`, reads `USER_NOTES`, and lacks
  the M1 instruction RPCs. Read-only verification on October 1 corrects the
  earlier import-path observation: the `c3f95bb-m1-53df502/engine` tree now
  exists and is the running process's PYTHONPATH. It contains the prior
  confinement overlay and the reviewed voice code, but still no M1.
  The working `docs/active-context.md` already names `c3f95bb`.
- The next voice release must be built on a base that contains M1:
  `origin/main` ≥ `706fe2a` (the rebased M1 commits `333c0c0`, `c50ff00`,
  `4d2f444`, `706fe2a`), or local `main` rebased onto it. Local `main` carries
  cherry-pick copies of the same commits (`f8c1301`, `95e2340`), so pushing it
  needs a merge with `origin/main` first. The release manifest's
  `source_reader` must then say `phone.md` through `operator_instructions`.
- Before restarting `production@` on the new release, run the check in the
  meta-repo plan (`~/hb/docs/execution-plans/2026-09-30-retire-user-notes.md`,
  "Open item"): from `/home/mal/124/124-cs`, `cs instructions` prints every
  document `unchanged` and `projects.history` shows revision 1 only. After the
  restart, `cs rpc instructions.preview` from `124-cs` must return
  `mail/production@cafe124.it.md` + `procedures.md`, and the company-notes
  conversion must run from `phone.md` revision 1. Then lift `CS_PAUSE` on
  `124-cs` and `mario124-cs`.
- A rule stated to the operator on 124 goes into `company/customer-service-playbook.md`
  and, after `cs instructions --commit`, into `procedures.md` AND `phone.md`
  as a new revision: the telephone facts follow the same file as the mail
  procedures, with no separate editing path.

## Delivery boundary and acceptance

The authorized change is the production voice source migration, including one
new budgeted conversion using the saved memory-extraction role, targeted
activation, read-only instruction checks and lifting the two named clone
pauses after their applicable checks pass. Preserve GPT-Live as the sole
telephone model, exact production binding, revision-6 voice/greeting,
headless authentication, previous confinement protections and call archives.
Do not change company documents, add local call/spend/duration caps, run a
phone call, load the operator's personal profile, send transcripts to StarChat
or use `update-daemons.sh`. Work on main; no new branch or worktree.

Acceptance requires a release based on the reviewed M1 lineage, a manifest
naming `phone.md` through `operator_instructions`, unchanged compiled documents
and revision-1 history before restart, independently reviewed current-source
notes, a working production `instructions.preview` with the exact mailbox and
procedures documents, and actual imported-release/health/binding checks. Check
Mario's clone's effective instruction reader before resuming it; restoring
scheduled work must not conceal an unmigrated reader. Preserve a concrete
rollback for the current release, configuration, private notes and clone pause
state. The earlier USER_NOTES-based handset acceptance is historical evidence;
it does not certify the new source conversion or close the knowledge plan's
remaining spoken-detail and quantitative-latency gates.
