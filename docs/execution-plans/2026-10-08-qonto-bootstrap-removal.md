---
status: active
date: 2026-10-08
brief: ../briefs/2026-10-08-qonto-bootstrap-removal.md
---

# Remove the Qonto engine bootstrap credential source — execution plan

<!-- doc-scope:start -->
Scope: decisions, milestones, ownership, verification and rollback for
removing the Qonto bootstrap credential source from source. No hosted update,
profile file, release tag or installer is part of it.
<!-- doc-scope:end -->

The [brief](../briefs/2026-10-08-qonto-bootstrap-removal.md) passed its gate
on 2026-10-08. The base is `main` at `434f325`; `app/` and the Qonto engine
tree at that commit are byte-identical to tag `v0.1.56`. Work happens on
branch `chore/remove-qonto-bootstrap`, in its own worktree.

## Decisions

**D1 — Credential module.** `engine/zylch/qonto/credentials.py` holds
`Credentials`, `credentials(login, key)` and `request_credentials(params)`.
The first two move unchanged. `request_credentials` reads `credential_source`
with default `input`: `bootstrap` raises `QontoError("credentials_required")`
whatever else the request carries, any other value than `input` raises
`invalid_credentials`, and `input` validates the request's `login` and
`api_key` as today. `engine/zylch/qonto/bootstrap.py` is deleted;
`challenges.py`, `provider.py`, `secrets.py` and `connection.py` import from
the new module. `errors.py` loses `bootstrap_unavailable` and
`bootstrap_override_disabled`.

**D2 — Results and signatures.** `connection.status()` and
`connection.disconnect()` stop building `bootstrap` and `bootstrap_retained`;
`delete_imported_data` inherits that. `rpc/qonto.py` keeps the declared
signatures of `qonto.test` and `qonto.connect` unchanged, including
`credential_source="input"`, and rewords the return clauses of `qonto.status`
and `qonto.disconnect`. The order of checks in `test` and `connect` does not
change: the source is refused where it is parsed today, after the authority
checks and before the provider probe and the challenge.

**D3 — Card, types and fixture.** `QontoCard.tsx` drops the `bootstrap`
state, the availability line, the checkbox and the bootstrap wording in the
`login_required` message, the disconnect notice and the footer. Test and
Save send `{credential_source: 'input', login, api_key}`. `finance.ts` and
`preload/index.ts` narrow `credential_source` to `'input'` and remove
`bootstrap` and `bootstrap_retained` from result types; the preload edit
keeps its line count. The fixture bridge `scripts/fixtures-qonto-rpc.ts`
answers `credential_source: 'bootstrap'` with `credentials_required`, as the
engine does, and gains a switch that makes status, disconnect and delete
return the legacy `bootstrap` fields.

**D4 — The Qonto plan.** Its work trace stays verbatim. Two present-state
notes are added to it. A bullet in "Delivery state" and a paragraph at the
top of "Credential bootstrap contract" state the contract on `main`:
credentials arrive only as typed request arguments, and the retired
`bootstrap` value is refused. The bullet also carries the hosted update
order, next to the installed-Desktop acceptance item that plan owns. The
paragraph scopes the bullets under it to Desktop `v0.1.56` and the hosted
pinned releases, which still carry the bootstrap source, and records that
leftover credential lines stay loaded in a profile's process environment
until an operator deletes them.

**D5 — Saved-connection check.** The fixture sidecar
`python -m tests.qonto.ui_sidecar <root>` runs a real engine on a disposable
engine home with an in-process provider fixture and a signed fixture session.
Launched from an export of the base commit, with the worktree interpreter,
it tests, connects and syncs with typed credentials, and its `qonto.status`
carries `bootstrap`. Launched from the changed tree on the same root, its
`qonto.status` is connected at the same generation and carries no
`bootstrap`; `qonto.sync`, `qonto.accounts` and `qonto.transactions` answer.
The two status results prove which engine ran. The driver script and its
transcript are evidence outside the repository. The check depends on M1
only and runs there.

**D6 — Cross-version journeys.** `scripts/test-qonto-native-browser.mjs`
drives actual Settings and preload against real Python dispatch.
*Published app against the changed engine:* at the M1 commit the branch's
`app/` is still byte-identical to `v0.1.56`, so that script run on the branch
is this pair. *Changed app against the base engine:* a scratch tree holding a
real copy of the changed `app/` directory and, beside it, an `engine` link to
an export of the base commit runs the changed script, with
`MRCALL_FIXTURE_PYTHON` naming the worktree interpreter. The fixture-bridge
script `test-qonto-browser.mjs` never reaches the engine and is no evidence
for either pair.

**D7 — Inventory.** `npm run inventory:rpc` runs with `CS_KERNEL_ROOT` at an
export of cs-kernel `eb6dc1a`. Before any change, that command reproduces the
committed `docs/rpc-contract-inventory.json` byte for byte. After the change
the diff is limited to `source_sha256.preload`, `source_sha256.finance` and
the Qonto records under `engine`, `preload_calls` and `renderer_linkage`;
nothing changes under `kernel_calls`. The inventory is regenerated in M1 for
the two engine records, in M2, and on the final tree in M3 with
`git diff --exit-code`. After any merge of `main` the reproduction check is
repeated against the new base, and an inventory conflict is resolved by
regenerating. `npm run test:rpc-contracts` keeps running against the kernel
revision pinned in `.github/workflows/rpc-contracts.yml`.

## M1 — Engine and shared contract

**Dependencies:** this plan approved. **Owner:** engine specialist.

- Code per D1 and D2.
- `tests/qonto/test_secrets.py`: the format-validation test keeps its cases
  under a name without "bootstrap". The two bootstrap tests are replaced by
  one regression through real dispatch. Valid `QONTO_API_LOGIN` and
  `QONTO_API_KEY` values sit in the profile `.env` and in the process
  environment, as profile activation leaves them, and
  `QONTO_BOOTSTRAP_ENV_FILE` names a second valid file. Then: `qonto.status`
  has no `bootstrap` key; `qonto.test`, and `qonto.connect` with its four
  required parameters and confirmed authority, answer `credentials_required`
  for `credential_source="bootstrap"`; `qonto.connect` without confirmed
  authority still answers `authority_required`; the provider fixture records
  no request; an existing connection stays connected after the refused
  request; another source value answers `invalid_credentials`; typed Test
  and Save pass with the parameter omitted and with `"input"`;
  `qonto.disconnect` and `qonto.delete_imported_data` results carry neither
  key; both files are byte-identical afterwards.
- A static test in `test_secrets.py` asserts that no `*.py` file under
  `engine/zylch` contains the exact names `QONTO_API_LOGIN`, `QONTO_API_KEY`
  or `QONTO_BOOTSTRAP_ENV_FILE`. It reads source files only, because ignored
  bytecode of the deleted module keeps the names in a used checkout. The
  lowercase redaction entries of `rpc/dispatch.py` are a guard and stay.
- `test_provider.py` imports from the new module. `conftest.py` and
  `ui_sidecar.py` lose their `QONTO_BOOTSTRAP_ENV_FILE` lines. The guard
  list in `test_schema.py`, `credential_policy.py` and `rpc/dispatch.py` are
  not edited.
- Documents: `docs/qonto-ipc.md` (method table and credential paragraph) and
  `engine/docs/features/qonto.md` ("Credentials and authority", "Disconnect
  and deletion") state one source, the refusal of the retired value and the
  leftover-line fact, without any of the three names.
  `engine/docs/examples/.env.qonto.example` and the two negation lines in
  `.gitignore` and `engine/.gitignore` are removed.
- Inventory regenerated per D7 for the two engine return clauses.

**Verification:** from `engine/`, the full `tests/qonto` suite, the three
contract files of the RPC workflow, and
`tests/memory/test_mnemonic_inventory.py` with
`tests/memory/test_mnemonic_write_boundary.py`; Ruff and Black on the touched
files; `npm run test:rpc-contracts`; the unchanged app's
`scripts/test-qonto-native-browser.mjs` on the branch (D6, first pair); the
saved-connection check (D5); `git diff --stat origin/main...HEAD` empty for
`credential_policy.py`, `rpc/dispatch.py`, `test_schema.py`,
`app/src/main/profileFS.ts`, `app/src/main/provisionClient.ts` and
`app/src/renderer/src/lib/profileSchema.ts`;
`git check-ignore .env.qonto engine/.env.qonto` names both.

**Gate:** a fresh adversarial integration reviewer and the IPC contract
reviewer, both before M2 starts. The IPC reviewer judges M1 against the
published client: runtime tolerance of the card for results without the two
fields, plus the published-app journey. Declared client types align in M2.
If a file under `engine/zylch` changes after this gate, the saved-connection
check and the published-app journey run again.

## M2 — Desktop card, types, fixture and inventory

**Dependencies:** M1 approved. **Owner:** app specialist.

- Code per D3.
- `scripts/test-qonto.mjs`: the bootstrap journey goes. The host-switch and
  UID-switch late-reply journeys stay. Each types both fields again, asserts
  that the Test button is enabled, and asserts `fixture.pending('qonto.test')`
  before the switch. New assertions: no bootstrap text and no unlabeled
  checkbox in the card when idle, tested, connected and disconnected, also
  with the fixture's legacy-fields switch on; Test disabled until both
  fields are filled; in the fixture call log every `qonto.test` and
  `qonto.connect` call carries non-empty `login` and `api_key`,
  `credential_source: "input"` and no other credential field.
- `scripts/test-qonto-credentials.mjs` keeps its guard assertions and adds a
  scan asserting that no file under `app/src` contains the three names.
- `app/docs/qonto.md` states the single source.
- Inventory regenerated per D7.

**Verification:** `npm run typecheck`, `npm run build`, the six Qonto
scripts, `npm run test:rpc-contracts`, `npm run test:auth`,
`npm run test:onboarding`; the D7 reproduction check and diff scope; the
changed app against the base engine (D6, second pair); the same guard-file
and ignore checks as M1.

**Gate:** a fresh adversarial integration reviewer and the IPC contract
reviewer.

## M3 — Final evidence, reconciliation and delivery

**Dependencies:** M2 approved. **Owner:** lead; a verification worker runs
the checks.

1. One rerun of the whole surface on the final tree: engine `tests/qonto`,
   the contract files and the two memory-boundary files; the app commands of
   M2; the inventory with `git diff --exit-code`.
2. `git grep -l` for the three names returns exactly
   `engine/tests/qonto/test_schema.py`, `engine/tests/qonto/test_secrets.py`,
   `app/scripts/test-qonto-credentials.mjs`, `docs/active-context-archive.md`,
   the Qonto plan, the brief and this plan. The brief and this plan are
   committed before the check, which lists tracked files only, and the check
   runs once more after step 3.
3. Reconciliation: the two notes of D4; the index entry in `docs/README.md`;
   the Qonto item under "Unresolved" in `docs/active-context.md` gains the
   update order: until one typed connection from an installed Desktop passes,
   no hosted engine that holds a Qonto connection takes a source revision
   without the bootstrap credential source; this plan's evidence; then the
   closure workflow with its mechanical gate and semantic check.
4. A separate fresh adversarial final review through the final-user path,
   and a second independent adversarial review on a different model.
5. Delivery: fetch; if `main` moved, merge it into the branch and rerun the
   checks its changes touch; a merge that conflicts in a file this work
   changed returns to the final reviewer. Push the branch; open a pull
   request whose commit list equals `git log origin/main..HEAD`. Its
   workflows are green, or a failure is reproduced on `origin/main`, before
   the merge. Merge with a merge commit and confirm `origin/main` contains
   the commits.

## Risk and rollback

- The change is source-only and touches no stored data. Rollback is a
  reviewed revert of the merge commit.
- No hosted engine, profile `.env`, unit, egress policy, tag or installer is
  touched. The hosted update order is recorded in the cross-cutting living
  snapshot, where the owner of a hosted update starts.
- Other sessions push to `main`. The branch is refreshed before delivery,
  never rebased after review, and never force-pushed.
- The "Mnemonic kernel journey" workflow needs the kernel as a sibling
  checkout and is verified on the pull request.
- An installed `v0.1.56` with its box ticked against a changed engine gets a
  refusal that asks for fields hidden until the box is unticked. The brief
  accepts this.

## Evidence

Brief gate: APPROVED on the third pass. Plan gate: APPROVED on the second
pass; its five closing notes were written into this plan after the verdict
(static scan over `*.py`, three-dot guard diff, grep after the trace is
committed, reruns after a late engine change, update order in the Qonto
plan).

**M1 (2026-10-09).** Integration review and IPC contract review: both
APPROVED on the first pass, with notes applied before the commit: two
document precisions and four regression cases (identity checks before the
refusal on both methods, a serving engine, a reopened disconnected profile,
logs with leftover lines present).

- Engine `tests/qonto`: 425 passed before the added cases; the changed file
  `test_secrets.py` then 31 passed. Contract files 39 passed; memory-boundary
  files 27 passed. Ruff and Black clean on the touched files.
- Saved connection (D5): 22 of 22 checks; the base engine's status carries
  `bootstrap`, the changed engine's does not, same root, same generation;
  sync, accounts and transactions answer.
- Published app against the changed engine (D6): the unchanged app's native
  journey passes. With the retired box ticked the published card shows
  "Enter your Qonto organization API login and key, then Test." and offers
  no Save.
- Inventory: two `declared_return` lines changed; a regeneration with
  cs-kernel `eb6dc1a` reproduces the file byte for byte.
- Mutation probes by the reviewer: 25 of 28 in-memory mutants killed by the
  first five regressions; the order mutant is now covered by the identity
  cases, and the two discarded-lookup mutants by the static scan.
- Pre-existing and untouched: whole-package `make lint` fails identically on
  the base; `tests/server/test_qonto_egress_policy.py` errors at setup under
  pytest on the base and passes under `unittest`.

**M2 (2026-10-09).** Integration review and IPC contract review: both
APPROVED on the first pass. Notes applied before the commit: the fixture
comment names what it mirrors, the late-reply helper asserts that Test is
disabled while a Test is pending, and two document sentences are tightened.

- Card: no bootstrap state, line, checkbox or wording; the diff against the
  published card is six hunks, all bootstrap code. In a real browser, through
  the actual preload and real Python dispatch, the changed card and the
  published card post identical Test and Save bodies.
- Changed app against the base engine (D6): the native journey passes on a
  real copy of the changed `app/` beside the base engine, whose status still
  carries `bootstrap`; the card shows no bootstrap UI and "Qonto
  disconnected.".
- Fixture journeys: 29 guarded mutants of the card, the fixture and the
  script each fail on the intended assertion, among them a stale Test reply
  accepted after a host switch, a UID switch and a sign-out.
- Inventory: six changed lines, namely the two source hashes, the preload
  record of `qonto.status` and the three renderer-linkage signatures;
  `engine` and `kernel_calls` unchanged, no line number moved, regeneration
  byte-identical.
- App commands: typecheck, build, the six Qonto scripts,
  `test:rpc-contracts`, `test:auth` and `test:onboarding` pass.

**Host incident during M2.** An unguarded mutation run of
`app/scripts/test-qonto.mjs` exhausted host memory around 12:35-12:52 UTC:
a failing `assert.equal(<react-test-renderer instance>, undefined)` never
reports on Node 22 and allocates without bound. No hosted unit restarted.
The eighteen assertions of that form in three scripts are converted in a
separate commit, and a guarded failing run now reports its message at
140 MB. The remaining gap is logged in `docs/harness-backlog.md`.

**Findings outside this plan**, logged in `docs/harness-backlog.md`: no
workflow runs the Qonto suites; the RPC contract check ignores result
shapes and inventory currency; two Qonto client result types differ from
the engine; `qonto.test` returns account balances before authority is
confirmed.

**M3 (2026-10-09).** One rerun of the whole surface on `28166c2`, one
process at a time under a heap cap. The commits after `28166c2` change
Markdown only.

- Engine: `tests/qonto` 435 passed, which is the 425 of M1 plus the ten
  cases of the four added tests; the three contract files 39 passed; the
  two memory-boundary files 27 passed.
- App: typecheck, build, `test-qonto.mjs`, `test-qonto-credentials.mjs`,
  `test-qonto-history.mjs`, `test-qonto-auth-lifecycle.mjs`,
  `test-mailboxes-ui.mjs`, `test-qonto-browser.mjs`,
  `test-qonto-native-browser.mjs`, `test:rpc-contracts`, `test:auth` and
  `test:onboarding` exit 0.
- Inventory: a regeneration with kernel `eb6dc1a` leaves the committed
  file unchanged.
- The three names: `git grep -l` returns exactly the seven files of step
  2, before and after the reconciliation edits.
- Reconciliation: the two notes of D4, the index entry, the update order
  under "Unresolved", the credential source in the three living snapshots,
  and six entries in `docs/harness-backlog.md`. The app snapshot also
  stops saying that the published installer lacks Qonto.
- No engine file changed after the M1 gate, so D5 and the published-app
  journey of M1 stand without a rerun.
- Not verified by any journey: a packaged Electron build and the Electron
  main transport, the WebSocket transport, a real Qonto connection through
  the changed card, and live hosted state.
- The final-review verdicts and the closure result are in the commit that
  completes this plan and in the pull request.
