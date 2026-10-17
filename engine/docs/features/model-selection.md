# Model selection by requirements

Scope: how the engine chooses the model each paid call runs, where its prices
and request metadata come from, how the model table is measured, published and
refreshed, and the tests that keep a model name from becoming a default again.
Milestone 10, with feature branch `model-selection-m10a` preserved in the local
effective-runtime integration candidate. The brief and the plan are in
hb: `docs/briefs/2026-10-01-model-selection-by-requirements.md` and
`docs/execution-plans/2026-10-02-model-selection-m10.md`. The published
contract (schemas, gates, credits protocol) is
[`zylch/llm/roles/contract/`](../../zylch/llm/roles/contract/README.md).

## Selection boundary

Each call site names a **role**; a role declares a rule and an index. The
resolver combines requirements, OpenRouter's catalogue and measurements into
the published **model table**. No model is a default in code. Haiku is excluded
from rankings and measurement arms; an explicit saved custom choice remains
priced. Historical quality findings and their limits belong to the
[measurement record](../../../docs/evaluations/2026-10-11-role-measurement.md).

## The requirements

`zylch/llm/roles/requirements.json` holds choices, never a model list:

- `common`: tool support, a 200,000-token context, no `:free` or `:batch`
  variant, an `intelligence` score.
- `presets`: a ceiling in USD per million **output** tokens: `economy` 10,
  `balanced` 20. `custom` has no ceiling and no table column.
- `excluded_families`: `anthropic` + `haiku`, matched on the catalogue id,
  its `canonical_slug` and an alias's target. Aliases (`~` ids) and entries
  with an announced `expiration_date` are excluded too.
- `margin` (1.25), `provider_policy` (admitted quantizations, 8-bit and up
  plus `unknown`; K3 pinned to its `digitalocean` endpoint),
  `excluded_endpoint_variants` (`flex`), and the measurement `reference`
  (K3, the production model).
- `roles`: sixteen, one per kind of paid call site (`MNEMONIC`,
  `MEMORY_EXTRACT`, `MEMORY_MERGE`, `TASK_DETECTION`, `REANALYZE`, `DEDUP`,
  `REPLY_NEED`, `INTENT`, `CHAT`, `TASK_SOLVE`, `TRAIN`, `COMPACTION`,
  `SYNC_ANALYSIS`, `WEB_SEARCH`, `CORRECTION_LEARNING`, `NARRATION`), each
  with a `rule` and an `index`. `MNEMONIC` and `MEMORY_MERGE` maximise
  `intelligence`, `CHAT` and `TASK_SOLVE` maximise `agentic`, the rest
  satisfice `intelligence`. No floor is typed: thresholds come from the
  measurement.

## The resolver

`engine/scripts/resolve_models.py` (I/O, flags, report) and the pure
`zylch/llm/roles/` modules (`candidates.py`, `impute.py`, `resolver.py`,
`snapshot.py`, `gates.py`), ported from `mrcall-ai-kit` (`c88b024`, MIT).

- **Sources.** OpenRouter's catalogue (`/models`), the endpoints of every
  entry a role may rank (`/models/<id>/endpoints`) and the benchmarks
  (`/benchmarks`, with `OPENROUTER_API_KEY` from the environment only, never
  printed): Artificial Analysis's `intelligence`, `coding` and `agentic`
  indices.
- **Pool.** The screen keeps a candidate with tools, the context, a fixed
  price and at least one up endpoint admitted by the provider policy within
  its price × the margin. A missing index is imputed from intelligence (a
  regression on the same read, minus one residual standard deviation) and
  marked `imputed`; a model with no record is listed, never scored by name.
- **Rankings.** Per preset and role, up to five entries, best first; the
  first is the pick. A `maximise` role ranks the models that passed its
  measurement by its index (a tie to the cheaper). A `satisfice` role ranks,
  cheapest first, the models at or above its measured threshold, or, when it
  is `measured_only`, the models that passed. A model measured as failing a
  role is never ranked for it. A second ranking, `anthropic_ranking`, applies
  the same rule to the candidates with a direct Anthropic id and may be empty.
- **Ceiling raise.** A run by hand may report a ceiling raised so that every
  role ranks a model; a raised ceiling is never published.
- **Degrade, never guess.** A source that cannot be read or a role with no
  candidate at any price exits 1 and writes nothing; a malformed
  `requirements.json` or `measured.json` exits 2.

```bash
python scripts/resolve_models.py                # print the screen, scores and rankings
python scripts/resolve_models.py --apply        # write snapshot.json; table.json only when measured.json covers every role
python scripts/resolve_models.py --check        # exit 1 when the decision record (ceilings, rankings in order) would change
python scripts/resolve_models.py --bootstrap    # print the measurement's arms as JSON
python scripts/resolve_models.py --save DIR     # keep what was read
python scripts/resolve_models.py --fixture DIR  # read saved payloads, no network, no key
```

## The table, the snapshot and where they come from

- **`table.json`**, the decision record: per preset its ceiling, per role a
  `ranking` and an `anthropic_ranking` of `{id, direct_id}`. No price, score
  or metadata, so a price refresh moves no record.
- **`snapshot.json`**: every catalogue entry's price, request metadata
  (reasoning, parameters, `forced_tool`, structured outputs, context,
  expiry) and admitted endpoints, plus the direct Anthropic ids and the
  provider policy.
- **Static gates** (`roles/gates.py`, the same rules on the billing server):
  the schema; a non-empty `ranking` for every preset and role (an empty
  `anthropic_ranking` is allowed); no alias, excluded family or announced
  expiry ranked; every ranked id priced positively within its ceiling;
  versions matching their content.
- **Published** on the orphan branch `model-table` under `v1/`: `table.json`,
  `snapshot.json`, `measured.json`, `ledger.json` and `results.json`, read at
  `https://raw.githubusercontent.com/hahnbanach/mrcall-desktop/model-table/v1/<file>`.
  Engines and the billing server read only `table.json` and `snapshot.json`;
  the other three are the daily job's own records. `results.json` holds each
  measurement result the job has paid for and not yet published in
  `measured.json`, keyed by model, role, case-set hash and prompt hash
  (`scripts/model_table_results.py`). It also holds the smokes' outcomes, keyed
  by model and the fingerprint of its request metadata, and the measurements
  stopped at their time limit (`scripts/model_table_outcomes.py`). Each entry
  is pushed when its check ends.
  The first publish is `8087fbf2`: table version `304ab3b7…` (file sha256
  `9d40bbf3…`), snapshot `b3196ae2…` read 2026-10-10T12:01:52Z.
- **Build copies** `roles/table.json` and `roles/snapshot.json`, written by
  `resolve_models.py --apply` and refreshed from the data branch by
  `release.yml`. A copy refreshed from the data branch names the data
  branch's `measured.json` in its `measured_sha256`, not the committed
  `roles/measured.json` (the one-off measurement); nothing at run time reads
  it, but a hand `resolve_models.py --apply` resolves from the committed file
  and so from the older measurement.
- **Run time** (`roles/distribution.py`): the engine downloads both files when
  a profile is activated and every 24 hours (ETag), re-checks them with the
  gates and caches them in `<profile>/model-table/`, never in a directory
  shared between profiles. A blocked, failed or failing download falls back,
  file by file, to the last good copy, then to the build copy. The engine
  never refuses a copy for its age; only the release gate does.

## Prices

`zylch/llm/roles/prices.py` is the one price source. It reads the snapshot
layers `roles/catalogue.py` holds (the downloaded copy, the one before it,
then the build copy) at every call:

- On OpenRouter a catalogue id is priced at its reference price. That is the
  model-level catalogue price whenever at least half its eligible endpoints
  are priced within it × the margin. Otherwise it is the lower median of its
  eligible endpoints by Artificial Analysis's blended price
  (3 × input + output) / 4. A variable price stays unpriced.
- On the direct transport a direct id is priced at its `anthropic` endpoint's
  price (Anthropic's list price). A dated id `<alias>-YYYYMMDD` is priced as
  its alias, and a response naming `<requested>-YYYYMMDD` settles as the
  requested id.

`budget_pricing.PRICES`, `openrouter_pricing.RATES` / `LABELS` and `usage.py`'s
estimate are views over it ([spending protection](daily-llm-budget.md)). An
OpenRouter request is reserved and capped (`max_price`) at the price × the
margin. K3 uses its pinned endpoint's price × the margin, or its reference
price × the margin on a day that endpoint is down. The provider object
carries the admitted quantizations and `only` the admitted endpoints;
fallbacks stay within them, and K3 never falls back. A refused call (429,
402 or another status proving no work) releases its hold; a 5xx keeps it.
The direct transport reserves at the list price, without the margin.

Every id the snapshot prices is priced, so a model a profile saved keeps
running when a successor appears. Haiku 4.5 is a priced choice a `custom`
profile may name; it is never a default, a ranked model or an arm. An id no
snapshot layer prices is refused before dispatch ("model pricing is not
configured", "OpenRouter model has no verified price ceiling").

## How `resolve_model` decides

`zylch/llm/model_policy.py`, in order:

1. An explicit `model=` argument.
2. The saved `MODEL_<ROLE>`, under **every** preset.
3. The preset (unset means `custom`):
   - `economy` / `balanced`, by the saved provider:
     - `openrouter`: the first `ranking` entry's catalogue id.
     - `anthropic` (a personal key): the first `anthropic_ranking` entry's
       direct id. An empty Anthropic ranking pauses the role (`RolePaused`).
     - `mrcall` (credits): `roles/served.py` reads the billing server's
       `GET /capabilities?protocol=mrcall-bounded-v2` (5 s timeout, cached one
       hour) and runs the first ranked id it serves: the direct id when the
       server lists it as Anthropic's, else the catalogue id. None served
       pauses the role. A v1 answer pauses with "update the billing server".
       A malformed answer is the explicit `MALFORMED` error.
   - `custom`: the provider's base key (`ANTHROPIC_MODEL`, `OPENROUTER_MODEL`,
     `MRCALL_CREDITS_MODEL`), else `DEFAULT_MODEL`; with neither, the role
     resolves under `economy`.

A call with no role resolves as `CHAT`. Call sites use
`routed_model("MODEL_<ROLE>")`; the fourteen probes that only ask whether AI
can run call `llm_available()`. There is no fallback model and no preset
escalation.

**Pauses** (`zylch/llm/role_pause.py`). A paused role's message names the
role, the preset and a remedy. For a role Settings offers a field for
(`TASK_DETECTION`, `REANALYZE`, `DEDUP`, `MEMORY_EXTRACT`, `MEMORY_MERGE`) the
remedy is that field. For any other role it is the custom preset with a
default model the billing choice can run, or another billing choice. The
pause surfaces in `usage.today` (`model_policy.paused`), in a narration reply
(`paused`), and as a memory-stage warning in the update result while the
other stages run.

**Fingerprint.** `policy_fingerprint` covers the model each role resolves to,
computed without network (credits from the cached served set). A table
refresh that changes a model this profile runs aborts runs in progress like a
settings change; a price refresh or a reorder that changes none does not.

**Settings and `llm.models`.** Model choices are the models the table in force
ranks (both rankings, every preset and role): direct ids on a personal
Anthropic key, catalogue ids on OpenRouter, the server's v2 list on credits.
No excluded family is offered; a saved value stays listed and runs. Labels
are derived from the id (`z-ai/glm-5.3-flash` reads "GLM 5.3 Flash (Z.ai)",
`zylch/llm/roles/__init__.py`). The preset help says the presets are price
ceilings and names no model.

## The one request shape

`zylch/llm/request_shape.py` gives every request one shape on every transport,
from the snapshot's metadata, never from the model's name: no sampling field;
`tool_choice` never forced (`any` / `tool` sent as `auto`); reasoning at the
lowest published effort, never `disabled` where efforts are published;
`strict` on closed tool schemas when supported; 1024 tokens of headroom
whenever the model may reason. K3 keeps its adapter. Reasoning blocks are
parsed, admitted and replayed unchanged within a tool loop, and stripped where
history is rewritten. 10a's per-prefix request rules are deleted.

## The measurement

`zylch/llm/roles/measured.json` is written only by `scripts/derive_thresholds.py
--plan` from records committed in `tests/fixtures/measurement/records/2026-10-11/`
(the run selection in `plan.json` and `exclusions.json`, built by
`scripts/measurement_plan.py`). A test requires the committed file byte for
byte. The method is in `tests/fixtures/measurement/README.md`; the run, its
spend and per-role results are in the
[record](../../../docs/evaluations/2026-10-11-role-measurement.md).

- An arm passes when it is complete, meets every mechanical bar, has no
  critical failure and scores at least p − se of the reference **from its
  own run**.
- A reference case that misses a bar and its label is credited to its run's
  yardstick (an accepted deviation from D7). The reference's own result
  keeps the failure.
- Every satisfice role is `measured_only`: index scores and results disagree,
  so only measured, passing models rank.
- Spend: USD 14.15 settled, 15.03 counting the aborted attempt, of the USD 20
  cap.

## The daily job and the release gate

`engine/scripts/model_table_job.py`, run by
`.github/workflows/model-resolution.yml` daily at 05:17 UTC and on dispatch
(GitHub runs both only from the default branch), with the repository secret
`OPENROUTER_API_KEY`:

- resolves against the published record and checks each changed pick or
  ranking order: a cached result by (model, role, case-set hash, prompt
  hash), else a smoke admitted at USD 0.20 (expected at most 0.05) and the
  role's measurement (at most USD 2), judged against the reference's recorded
  result;
- keeps an incumbent pick unless a challenger beats it, and replaces a pick
  that fails a gate with the first ranked model with a passing result;
- treats unmeasured pool models as challengers; the first run's backlog is
  about 128 entrant smokes, so it is worked through over months;
- stays within USD 10 a month, kept in `ledger.json`. Before each paid check
  the run reserves what it has spent plus that check's bound, and pushes the
  reservation. After the check it pushes the call, the reservation lowered
  to what it spent, and the check's results (`results.json`) in one commit.
  Nothing is retried;
- stops at a deadline (`--deadline-minutes`; the workflow passes 90 under its
  120-minute timeout). No check starts whose time limit would end after the
  deadline. A smoke's limit is its worst case under the engine's HTTP
  timeouts: 7 min, or 21 on the K3 path. A measurement is stopped at 10 min,
  a memory corpus run at 20. Later checks are deferred unpaid and reported;
  the run still decides, publishes and settles. Every check ends by the
  deadline; a stopped one is killed 30 s later; then the decisions and one
  push. With the runner's setup that stays well under 120;
- stops a measurement at its limit: interrupted, so it deletes its key file,
  then killed. A harness measurement is charged what its ledger recorded.
  A corpus run that wrote no record is charged its settled cases plus each
  open case at its bound, from `profile/corpus-intents.jsonl`; only when that
  journal is unreadable is it charged the whole USD 2. A measurement stopped
  at its limit is not tried again for 14 days, unless the role's case-set or
  prompt hash or the model's request metadata changes. A stop that freezes
  its role (on the reference, or on a model the role's re-measurement needs)
  is flagged in the report. If the job is killed outright, its measurement
  process dies with it (Linux: `PR_SET_PDEATHSIG`); any key file left is
  deleted by the next run's sweep;
- smokes a model once a week at most. A smoke's outcome stands 7 days while
  the model's request metadata (`reasoning`, `parameters`, `forced_tool`) is
  unchanged. A passed model is not smoked again: a measurement the deadline
  deferred follows it the next day. A failed model stays out of the
  rankings until it passes a smoke. It is not smoked again for 7 days; after
  that it is smoked before anything of it counts, so neither a published
  entry nor an old passing measurement brings it back. A change to its
  metadata clears the failure, and the changed model is smoked like any
  other. An outcome is kept only for a model the snapshot holds (a
  fingerprint), and only if the smoke sent a call. An uncertain entrant smoke (no settled answer, or an error) is
  not retried, but a smoke the publication waits for (a ranked model whose
  metadata changed) is retried by every run. No smoke is sent twice in a
  run, and one that sent nothing is not kept;
- runs alone on its data checkout: an exclusive `flock` for the whole run,
  and a second run is refused. A commit left unpushed is pushed by the next
  push, or the push fails and the run reports it;
- survives a hard kill: the branch keeps every paid result and an honest
  bound of the spend, the recorded calls plus one check's bound. The next
  run takes the results free of charge. It settles the open reservation at
  its reserved amount, marked `recovered`, before reserving anything. Under
  the monthly cap that amount counts as spent, once. An interrupted run
  (SIGINT, SIGTERM or SIGHUP, as a cancelled workflow sends) stops its measurement
  process and may settle itself, counting a check in flight at its bound.
  Otherwise the next run recovers it;
- publishes, or exits 1 and leaves the last record in force; a price-only
  change updates `snapshot.json` alone, and a raised ceiling is never
  published.

`release.yml` fetches `v1/table.json` and `v1/snapshot.json` into the build
copies and refuses (`scripts/model_table_release.py --max-age-days 14`) a
copy that fails the gates or whose snapshot was read more than 14 days ago.

## The boundaries

- `tests/llm/test_model_name_boundary.py` scans `zylch/` for model names
  (`claude-`, every vendor prefix in the catalogue fixture, `gpt-`, dated
  ids). Each occurrence must match a row of
  `tests/fixtures/llm/model_name_inventory.json`. The data files
  `requirements.json`, `snapshot.json`, `measured.json`, `table.json` and
  `contract/` are allowed whole. Adding a row is a reviewed change.
- `tests/llm/test_role_inventory.py` freezes every client construction per
  file and the fourteen probes.
- `tests/llm/test_request_scan.py` is an AST scan that fails on a caller
  passing sampling fields or a forced `tool_choice`.
- `tests/llm/test_model_table.py` ties the fixture table to its capture and
  both tables to the gates and the requirements in force.

These guard against accidents, not evasion: a name built by concatenation,
read from outside `zylch/` or placed on a comment-only line, or a request
built from a splatted dict, is not seen.

## Runtime and acceptance boundary

The [current-main candidate](../../../docs/execution-plans/2026-10-17-m10-current-main-integration.md)
preserves installed runtime protections alongside M10 and separates OpenRouter
input fit from monetary byte bounds. A saved custom/role override still wins;
installing M10 does not switch such a profile to the measured picks. The
[replacement evaluation](../../../docs/evaluations/2026-10-17-m10-current-main-artifact.md)
records installed source/resource proof and mandatory real-read/server/CI/paid
gates; the earlier readiness record retains its free distribution matrix and
saved-policy forecasts. The wheel explicitly includes requirements/table/snapshot
JSON and validation schemas. Installed metadata and schema loading must pass
without a source checkout; Python-module parity alone is insufficient. No local
scripted answer certifies company facts or deployment readiness.

## Known limits

- The measurement ran through OpenRouter only. The direct-Anthropic and
  credits transports are unmeasured.
- Small synthetic case sets (5 to 16 per role), answered once; Opus's and
  Sonnet's agentic scores are imputed.
- K3, the reference, fails REANALYZE, REPLY_NEED and TASK_SOLVE.
- The memory corpus's 16-token truncation check did not bind on OpenRouter
  for seven of nine arms. "SKIP + reason" and prose extraction answers stay
  pending and are re-paid.
- Empty Anthropic rankings: the first table (the build copy) had none for
  `NARRATION` under both presets and for `MNEMONIC`, `MEMORY_EXTRACT` and
  `MEMORY_MERGE` under `economy`; the table published 2026-10-12 (`f1847561`)
  leaves only `NARRATION` under `economy` empty. A personal Anthropic key
  pauses on an empty one, including a legacy profile with no saved preset or
  base model (it resolves under `economy`).
- A credits profile pauses with "update the billing server" until the billing
  server answers protocol v2.
- A legacy profile with no saved preset or base model resolves under
  `economy`. On `main` such a profile ran `claude-haiku-4-5` or GLM 5.2; it
  now runs the table's measured picks, which on an Anthropic key are Sonnet 5 /
  5.5 (about twice Haiku's price per call; Haiku was rejected as a product
  choice on 2026-10-01). Spend stays bounded by the daily budget.
- Egress: hosted tenant policies already allow `raw.githubusercontent.com`
  (sandbox plan R4); the billing server's deployment needs it too, or it
  serves the table baked into its image while engines download the daily
  one, and a credits role whose ranking shares no model with the server's
  list pauses.
