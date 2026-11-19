# One build for every hosted engine

## Intent

Every engine unit on the hosted machine runs the same `zylch` package, built
from one commit and one tag, in the same Python environment. A change to the
hosted engine is then written once and reaches every unit with one rollout.

## What runs on 2026-11-19

Seven units run four packages. The hash is the SHA-256 of the sorted
per-file SHA-256 list of the package tree, bytecode excluded.

| Units | Package | Files | Hash prefix | In git |
| --- | --- | --- | --- | --- |
| MrCall support, MrCall second account | `hosted-engine-0.1.57.dev2-00fdc039d4e3` | 453 | `ebc6f4e499138a55` | tag `hosted-engine-0.1.57.dev2`, identical |
| Café 124 production, with the telephone listener and the operator MCP listener | `interactive-reply-124-helper-226c0048ed8d3fea` | 474 | `c69795f09869ff05` | no: 4 code files are in no commit, 13 come from side branches |
| three Café 124 staff units | `logging-health-<tenant>-4688b958ffa0` | 355 | `5b29a5d147f36f64` | no: 10 files are in no commit |
| personal mailbox unit | `stripe-<owner>-7b55d976db7b` | 332 | `8b9f9139823bd773` | no: 2 files are in no commit |

`main` has 373 package files and runs on no unit. The base checkout
`/home/mrcalld/mrcall-desktop` follows `main` every night through
`zylch-reconcile.timer`, and every unit loads another package through a
drop-in.

The units also run three dependency sets: the base environment with 75
distributions, the support release with those plus the `aiohttp` family, and
the Café 124 environment with 110 distributions, 47 of them at newer versions
(`anthropic` 1.8.0 against 0.105.2, `sqlalchemy` 2.1.1 against 2.0.50,
`openai` 3.19.0 against 2.41.0).

## Scope

1. **Source.** The united package is the release line plus what the Café 124
   package adds. Both descend from the same uncommitted source and share 426
   identical files. Branch `release/hosted-engine-20261118` carries it.
2. **Release.** One root-owned directory under `/home/mrcalld/releases`: a
   copy of the Café 124 environment with `zylch` replaced by the wheel built
   from the tag.
3. **Rollout.** One unit at a time, each with one final drop-in and its own
   rollback.

Out of scope, each its own workstream:

- Joining `main` and the hosted line. The hosted line's tree was replaced by
  the production runtime in commit `0cf4790c`, so its git ancestry does not
  describe its content. A mechanical merge either deletes from `main` the
  contextual email guard with its enrollment and the typed Qonto credentials,
  which no unit ever ran, or activates them on production stores that were
  never enrolled.
- Collapsing each unit's drop-in stack into the documented form, a
  `tenant-exec` declaration plus operator drop-ins that sort before
  `tenant.conf`, so that the nightly reconcile stops exiting 3.
- The operator kernel and the clones.

## How the united package is composed

Per file, against the release tip:

- Eight files where the Café 124 version is the release version plus
  additions take the Café 124 version: `assistant/core.py`, `cli/main.py`,
  `llm/budget.py`, `llm/k3_reasoning.py`, `llm/openrouter_pricing.py`,
  `rpc/dispatch.py`, `services/project_store.py`, `storage/storage.py`.
- Nine files where the release version is the newer one stay:
  `email/imap_client.py`, `llm/client.py`, `qonto/history_receipts.py`,
  `qonto/sync.py`, `qonto/sync_store.py`, `rpc/qonto.py`, `rpc/setup.py`,
  `services/process_pipeline.py`, `services/task_assignment_evidence.py`.
- Six files carry both sides:
  - `rpc/server_ws.py` keeps the mail loop and gains the document dispatch,
    the owner request context and the operator listener.
  - `rpc/methods.py`, `rpc/stripe.py`, `stripe/errors.py` and
    `stripe/provider.py` keep the Stripe portal link and gain the payment
    link.
  - `services/operator_instructions.py` keeps the release line's `_authority`,
    which refuses a malformed management marker with error -32043, and takes
    the Café 124 `store`, which refuses a managed store.
- 25 files exist only in the Café 124 package and are added: `operator_mcp/`,
  `rpc/native_owner_context.py`, `rpc/operator_operations.py`, the
  `services/operator_reply_*` and `services/operator_rule_*` modules,
  `stripe/payment_links.py`.
- Four files exist only on the release line and stay: three `qonto/` modules
  and `stripe/portal.py`.

The two older packages add nothing. Each of their 13 uncommitted files is a
committed version from the history of the two lines plus a small patch. Of
those patches, 11 lines are absent from the united file, and each is an
earlier form of a line the united file holds. The evidence folder lists them
in `older-packages-uncommitted-lines-missing-from-united.txt` and holds the
full comparison in `older-packages-vs-united.diff`.

## What changes for a unit

For the two MrCall units:

- Every tool result the chat model reads is compact JSON with non-ASCII
  characters kept (`assistant/core.py`). The model's input text and its token
  count change.
- The request-size check of the OpenRouter and K3 transports estimates tokens
  from bytes (`llm/k3_reasoning.py`, `llm/openrouter_pricing.py`). A request
  the release version refused as too large can pass.
- Six methods are registered: `operator.rules.list`, `.decide`,
  `.import_preview`, `.import_confirm`, `operator.operations.list` and
  `.recover`. Each requires the owner's authenticated WebSocket session.
- Every WebSocket request runs inside the owner request context
  (`rpc/server_ws.py`, `rpc/native_owner_context.py`). A session whose token
  identity is not the profile's owner gets no answer; the WebSocket gate
  already refuses such a session.
- `emails.list_by_thread` rows gain `message_id_header`.
- `instructions.store`, which the kernel's `cs instructions` command calls,
  refuses a managed instruction store with error -32046. Both MrCall engines
  answer `authority: legacy` to `instructions.preview` on 2026-11-19
  (`rollout/instruction-authority.txt` in the evidence folder), so nothing is
  refused today.
- `system.capabilities` gains `stripe_payment_links`, and
  `stripe.payment_link_create` exists.
- The operator reply hooks in `storage/storage.py` and `llm/budget.py` return
  at once outside an operator reply operation. The operator MCP listener
  starts only with `--operator-config`. The operator rule and reply modules
  create their tables on first use, which no MrCall caller triggers.

For the Café 124 production unit:

- It gains the IMAP connection reuse of the assignment projection, the Qonto
  history range, the Stripe portal link and the strict `_authority` check.
- The finance evidence check of every model request is the one support runs
  (`llm/client.py`, `qonto/public_definitions.py`, `qonto/owner_content.py`):
  it rechecks before dispatch, and a session authenticated as the profile's
  owner may reuse that profile's own finance content. The Café 124 package
  refuses such a request by text similarity. The unit's store holds a Qonto
  connection, two accounts and 385 evidence receipts, so the rule applies to
  real data. 26 cases of the release tag's Qonto tests pin the older rule:
  they pass on the Café 124 package and fail on the support package and on
  the united one. No test covers `qonto/owner_content.py`.
- `system.capabilities` gains `stripe_payment_method_links`, which the
  kernel's `cs-stripe` skill reads before it asks for a portal link.
- It gains the mail loop's code. Its drop-in sets
  `MAIL_SYNC_INTERVAL_MINUTES=0`: the unit already fetches mail every five
  minutes through its auto-update loop, and its telephone listener shares the
  process.

For the three Café 124 staff units and the personal mailbox unit:

- They move forward by about 100 files and run the store steps their package
  never had.
- They gain the mail loop: an IMAP fetch and local embeddings every ten
  minutes, with no language model call.

For every unit:

- Each Stripe link feature still needs its own write permission on the
  tenant's restricted key.
- Every unit except Café 124 production changes dependency set.

## Constraints

- A live profile store or company store is opened only as the daemon's own
  user. A rehearsal runs on a copy made through the SQLite backup API.
- No secret is printed or recorded. A unit's environment file and
  `tenant.conf` are not read.
- A release directory is root-owned and holds no bytecode.
- One unit at a time. The Café 124 production unit keeps `--voice-config` and
  `--operator-config`.
- A rollback is the removal of the unit's new drop-in and a restart.

## Acceptance

Tests:

- Two scratch test trees run one directory at a time: `main`'s tests with the
  hosted line's twelve own test files added, and the release tag's own tests.
  The tag's tree needs one shim: its automatic fixture skips when
  `zylch.llm.roles`, which the line no longer ships, is absent.
- Each package runs in the environment it runs in production: the united
  package and the Café 124 package in a copy of the Café 124 environment with
  pytest added, the release package in the older dependency set.
- No case that passes on the release package or on the Café 124 package fails
  on the united package.
- Every module of the united package imports under the release environment's
  interpreter.

Store:

- A rehearsal on a copy of each distinct store generation applies the store
  steps once and nothing on the second start.

Every unit, after its switch:

- It is active and loads the release's package.
- `system.capabilities` answers every key it answered before.
- It logs its mail loop line and no error record through one operator tick.
  A unit no clone drives is observed for two hours instead.
- The package inventory shows the hash of the tag's tree.

The Café 124 production unit, in addition:

- Its telephone listener answers `calls_available: true` on
  `http://127.0.0.1:8787/healthz` at the check that immediately precedes the
  restart. That value is false while a call or a pending call exists.
- After the restart it listens again on `127.0.0.1:8787`, on its WebSocket
  socket and on its operator MCP socket, answers `calls_available: true`,
  and logs `[voice] production runtime` and the MCP session manager's start.
- No tick of the Café 124 clone runs at the switch, and the next scheduled
  one ends as its ticks of the same day ended before.
- `https://desktop.mrcall.ai/operator/<uid>/mcp` answers 401 without a token
  and both OAuth metadata documents answer 200.
- Its command line, drop-in names, sizes and modification times are recorded
  before the switch, so that a rollback is compared with them.

Not covered by these checks: a telephone call answered on the new package,
and an existing Codex connection used after the switch. Both need a person.

## Assumptions

- A file whose content is in the history of the release line is superseded by
  the tip of that line.
- The Café 124 environment is the common one because it is a superset, and
  because the unit with the telephone listener then changes least.
