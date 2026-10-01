# Model selection by requirements

Scope: how the engine chooses the model each paid call runs, where its prices
come from, and the tests that keep a model name from becoming a default again.
Milestone 10a, on branch `model-selection-m10a`. The brief and the build plan
are in hb: `docs/briefs/2026-10-01-model-selection-by-requirements.md` and
`docs/execution-plans/2026-10-01-model-selection-m10a.md`.

## Why

Milestone 9's paid corpus run used `claude-haiku-4-5` because that was the
engine's default everywhere: three settings defaults in `config.py`, the
`economy` preset, two hand-written price catalogues, the `llm.models` answer,
the Settings schema and two app strings. The run failed one critical case and
translated every Italian correction into English, and the CTO rejected the arm:
Haiku is not a default or an arm anywhere. The cause was general, not
Haiku-specific: model names were fixed in code, prices were copied by hand, and
nobody revisited the choice when a model aged. Now each call site names a
**role**; a role declares requirements; a resolver turns them into a committed
table, the one source for the model and its price.

## The roster and the two rules

`zylch/llm/roles/requirements.json` holds:

- `common`: what every candidate must meet: tool support, a 200,000-token
  context, no `:free` or `:batch` variant, no catalogue id starting with an
  `excluded_prefixes` entry (`anthropic/claude-haiku` today), and a score on
  every `required_scores` index (`intelligence`).
- `presets`: a price ceiling in USD per million **output** tokens:
  `economy` 10, `balanced` 20. `custom` has no ceiling and no table column.
- `roles`: sixteen roles, one per kind of paid call site (`MNEMONIC`,
  `MEMORY_EXTRACT`, `MEMORY_MERGE`, `TASK_DETECTION`, `REANALYZE`, `DEDUP`,
  `REPLY_NEED`, `INTENT`, `CHAT`, `TASK_SOLVE`, `TRAIN`, `COMPACTION`,
  `SYNC_ANALYSIS`, `WEB_SEARCH`, `CORRECTION_LEARNING`, `NARRATION`), each with
  a `rule`, an `index` (`intelligence`, `coding`, `agentic`) and, for
  `satisfice`, a `floor`.
- `allowlist`, `mrcall_served` and `request_rules` (below).

The two rules, as in `mrcall-ai-kit`:

- **maximise**: the highest score on the role's index among candidates at or
  under the ceiling; a tie goes to the cheaper model.
- **satisfice**: the cheapest candidate at or under the ceiling that clears the
  floor; a tie goes to the higher score. When nothing clears the floor, the
  role takes the highest score under the ceiling and the row is marked
  `below_floor`.

The starting numbers are maximise on intelligence for `MNEMONIC` and
`MEMORY_MERGE`, maximise on agentic for `CHAT` and `TASK_SOLVE`, and satisfice
on intelligence for the rest, with floors of 40, 35 or 30. The plan's
roster table lists the rule, floor and call sites of each role. These are
proposals: the CTO sets the ceilings and floors.

## The resolver

`engine/scripts/resolve_models.py` (I/O, flags, report) and the pure
`zylch/llm/roles/resolver.py` are ported from `mrcall-ai-kit`'s
`resolve-models.py` (MIT, `c88b024`); standard library only.

**Sources.** OpenRouter's catalogue (`/api/v1/models`, public: prices, context
length, supported parameters, `canonical_slug`) and its benchmarks
(`/api/v1/benchmarks`, key required: the Artificial Analysis
`intelligence_index`, `coding_index`, `agentic_index`, keyed by
`model_permaslug`). The resolver joins them on `canonical_slug`. If a slug's
benchmark records disagree, that slug gets no score and the report lists it.

**Candidates.** The kit's filter (variant, tools, context, a fixed output
price, the required scores) plus the engine's prefix exclusion. For each role,
only candidates scored on that role's index count. A model without an agentic
score is therefore never a `CHAT` candidate.

**Billed versus catalogue price.** If an allowlist row bills a candidate
above its catalogue output price (K3: 13.28 billed against 10 listed), the
candidate is compared at the billed price, the price the engine reserves at.
The catalogue pair is kept in the row as `catalogue_price`.

**The ceiling raise.** If a role has no candidate under a preset's ceiling,
that preset's ceiling rises to the lowest price at which every role has one,
and the table records it as `raised_to`.

**Three columns per preset and role:**
- The main pick: `catalogue_id`, plus `direct_id` when the model is
  Anthropic's (`anthropic/claude-sonnet-5.5` becomes `claude-sonnet-5-5`),
  the scores, the price pair and `below_floor`.
- `anthropic_fallback`: the same rule over the `anthropic/*` subset only,
  bounded by the same ceiling and raising it the same way
  (`anthropic_raised_to`). This is what a BYOK-Anthropic profile runs when the
  main pick is not Anthropic's.
- `mrcall`: the same rule over the models the MrCall credits server serves
  (`mrcall_served`), raising as `mrcall_raised_to`. Its `id` is the one sent to
  the server: the direct id for an Anthropic model, the catalogue id for K3.
  It is null when no served model fits at any price, and such a role pauses on
  credits instead of guessing.

**Degrade, never guess.** The script exits 1 and leaves `resolved.json`
untouched in each of these cases: a source cannot be read (a missing fixture
file, no key, an HTTP error, a paged or short catalogue, benchmarks shorter
than their count), a role has no candidate at any price, or the main or
fallback pool has no candidate scored on a role's index. A malformed
`requirements.json` exits 2.

### Running it

From `engine/`, with `OPENROUTER_API_KEY` in the environment, the only place
the script reads it (never argv or a file; never printed).

```bash
python scripts/resolve_models.py                  # report + diff against the committed table
python scripts/resolve_models.py --apply          # also write zylch/llm/roles/resolved.json
python scripts/resolve_models.py --check          # exit 1 when the committed table has drifted
python scripts/resolve_models.py --save DIR       # keep what was read (models.json, benchmarks.json, read-at.txt)
python scripts/resolve_models.py --fixture DIR    # read those files instead of the network, no key needed
```

`--apply` and `--check` exclude each other; `--check` ignores the `as_of`
stamps. A changed table is reviewed like code. The committed one came from
`tests/fixtures/llm/resolver/`, the catalogue read on 2026-10-01.
`tests/llm/test_resolved_table.py` fails when the table no longer follows from
that fixture and `requirements.json` (a hand edit, a floor changed without
`--apply`).

## The table is the one model and price source

`zylch/llm/roles/resolved.json` is generated; nobody edits it by hand.
`zylch/llm/roles/table.py` reads it to answer which model a role runs.
`zylch/llm/roles/prices.py` reads it, together with the allowlist, to answer
what that model costs. `budget_pricing.PRICES`, `openrouter_pricing.RATES` and
`usage.py`'s estimate all read `prices.py`
([spending protection](daily-llm-budget.md)).

**The allowlist** prices every model billed before the table existed, at the
rate it was billed at, so the upgrade moves no profile's price: the eleven
direct Anthropic ids, and on OpenRouter `moonshotai/kimi-k3`, `z-ai/glm-5.2`,
`anthropic/claude-sonnet-5`, `anthropic/claude-opus-5` and
`anthropic/claude-haiku-4.5`. Haiku 4.5, direct and on OpenRouter, is on the
allowlist only as a priced choice a `custom` profile may name. It is never a
default or an arm: the prefix exclusion keeps it out of every pool. When an id
is in both sources, the allowlist's billed price wins, so a resolver run can
never move the rate an existing profile is held and capped at. A model in
neither source is refused before dispatch with the existing messages ("model
pricing is not configured", "OpenRouter model has no verified price ceiling").

**How `resolve_model` decides** (`zylch/llm/model_policy.py`), in order:

1. An explicit `model=` argument.
2. The saved `MODEL_<ROLE>` key, under **every** preset. Explicit role
   overrides stay active, as Settings promises.
3. The preset (unset means `custom`):
   - `economy` / `balanced`: the table's row for that role, in the saved
     provider's column. `anthropic` gets the direct id, or the
     `anthropic_fallback`'s when the pick is not Anthropic's. `openrouter`
     gets the catalogue id. `mrcall` gets the `mrcall` id, or the call pauses
     with "this role has no model the MrCall credits server serves" when that
     id is null.
   - `custom`: the provider's base key (`ANTHROPIC_MODEL`, `OPENROUTER_MODEL`,
     `MRCALL_CREDITS_MODEL`), else `DEFAULT_MODEL`. With neither saved, the
     role resolves under `economy`, so no profile is left without a model.

A call with no role resolves as `CHAT`. Call sites use
`routed_model("MODEL_<ROLE>")` (`zylch/llm/__init__.py`), which never returns
None. The fourteen **probes** that built a client only to ask whether AI can
run call `llm_available()` instead: the saved provider and its credential
only, no model, no client, and unreadable settings read as unavailable.

**Settings and labels.** The Settings schema's model choices, suggested value
and preset help, and the labels `llm.models` returns, come from the table and
the allowlist through `zylch/llm/roles/__init__.py`; a label is derived from
the id itself (`z-ai/glm-5.3-flash` reads "GLM 5.3 Flash (Z.ai)"). The five
existing role fields stay; new roles are overridable through the profile
`.env` only.

## Request rules

Some current models refuse request shapes that older call sites send.
`requirements.json`'s `request_rules` records, per model-id prefix (direct and
OpenRouter forms; the longest prefix wins), what each model refuses, from
Anthropic's model reference as of 2026-10-01.
`zylch/llm/roles/request_rules.py` applies them:

- **Sampling** (`temperature`, `top_p`, `top_k`). Opus 4.7 and later, Sonnet 5,
  Opus 5.5, Fable 5 and Fable 5.1 refuse any sampling field, so it is dropped. Sonnet
  5.5 direct drops only a non-default value; its OpenRouter id drops all of
  them.
- **Forced `tool_choice`** (`any` / `tool`). Opus 5.5, Sonnet 5.5 and Fable 5.1
  refuse it, so it is downgraded to `auto`.
- **Default thinking.** Sonnet 5 and Opus 5 think when `thinking` is omitted.
  On a short request (`max_tokens` ≤ 1024) or a forced tool, the rule adds the
  field that turns thinking off (`disabled`; `between_tools` for Sonnet 5.5).
  Opus 5.5 cannot turn thinking off, and a transport's `disabled` is removed
  for it.

The rules are applied after the budget reservation on the direct
(`sdk_request.py`) and OpenRouter (`openrouter_client.py`) transports; a rule
only removes or relaxes a field, so the reserved bound still holds. On credits
they are applied before the quote, so quote, reservation and executed body are
one request, and they add no `thinking` field there: the server quotes the
exact body it runs, and a field it may not accept is its contract to change.
A model with no rule is sent unchanged.

## The two boundaries

- `tests/llm/test_model_name_boundary.py` scans `zylch/` for model names:
  `claude-`, every vendor prefix in the OpenRouter catalogue fixture plus the
  engine's earlier seven, `gpt-`, and dated snapshot ids. Each occurrence must
  be covered by a row of `tests/fixtures/llm/model_name_inventory.json` with
  the same file and literal. Each row carries a purpose: `adapter`,
  `snapshot`, `price`, `placeholder`, `label` or `doc`. Every row must be
  exercised. Only `requirements.json` and `resolved.json` are allowed whole.
  Adding a row is a reviewed change.
- `tests/llm/test_role_inventory.py` finds every `make_llm_client` /
  `try_make_llm_client` / `LLMClient(...)` construction, including aliases. It
  classifies each as a caller, a caller with a model, or a probe, and freezes
  the counts per file in `tests/fixtures/llm/role_inventory.json`. It also
  checks that each `routed_model("MODEL_…")` carries its row's role and that
  there are fourteen probes.

What they do not catch: both guard against accidents, not evasion. The name
scan is textual and case-sensitive. It does not see a name built by
concatenation, read from the environment or a file outside `zylch/`, written
in another case, or placed on a comment-only line. Rows match by file, literal
and count, not by line, so a `doc` name moved into code in the same file still
passes. The inventory does not see a builder reached through `getattr`,
`functools.partial`, a container, a parameter or a re-export under a new name.

## The CI drift job

`.github/workflows/model-resolution.yml` runs on manual dispatch and weekly
(Mondays 06:17 UTC). It runs `resolve_models.py --check` against the live
sources with `OPENROUTER_API_KEY` from the repository secret, fails when the
committed table would change (or when the secret is missing), and uploads the
report as an artifact. A red run is answered by `--apply` by hand and a
reviewed commit; drift is never applied unreviewed. The secret is the CTO's
action; until it exists, `test_resolved_table.py` is the guard.

## Known limits

- `mrcall_served` is a client-side copy of the credits server's catalogue as
  of 2026-10-01 (the direct ids of the old price table plus K3). It is an
  assumption about the server, not read from it. A quote whose model differs
  from the request is still refused client-side, so a substitution cannot be
  silent.
- On credits, narration (40 and 60 output tokens) and intent run with Sonnet
  5's default thinking, because that path adds no `thinking` field. Narration
  may come back empty. 10b or a server change will show whether it does.
- Whether OpenRouter passes `between_tools` through for
  `anthropic/claude-sonnet-5.5` is unverified until 10b's paid run.
- No pick is measured on the engine's workloads yet; 10b runs the memory
  corpus once on the `economy` `MNEMONIC` pick through OpenRouter.
