# M10 S7 paid checks, server path, OpenRouter leg (2026-10-12)

Plan `2026-10-02-model-selection-m10`, S7 "Paid, local, after IR4", and IR4
round 1 "Before production (a)". There were two runs. Run 1, at bb8f553, found
a server defect. Run 2, at 5191263 with the fix, settled every call. Total real
provider spend across both runs was about 0.0496 USD: 0.0164 in run 1 and
0.0332 in run 2. No Anthropic direct call was made in either run, because
MNEMONIC_ANTHROPIC_API_KEY is invalid.

# Run 2: fixed server, mrcall-agent 5191263 (main and dev)

## Result: PASS for the OpenRouter leg, with one follow-up finding

All 43 OpenRouter calls settled, including every tool loop's second turn, under
a fresh ledger with a 0.95 cap. The total actual cost was 0.0331632120 USD,
which is also what the ledger committed. All 43 admissions are `settled` with
a `gen-` generation id. The fix works: the id is read from the
`x-generation-id` header.

Follow-up finding, which is not a failure of this run: the status route's
recovery check (`bounded_openrouter.recover_cost`) rejects 42 of the 43
generations with `generation_binding_mismatch`. See "Status lookup" below.

## Setup

- Worktree `wt-agent-genid` at 5191263 (verified with `git rev-parse HEAD`).
  The tree was clean before and after the run.
- Python: `/home/user/venv-agent`.
- A fresh throwaway PostgreSQL 16 cluster ran as `nobody` in
  `/tmp/s7-paid-pg2`, on 127.0.0.1:55433, with database `bounded_test`. It was
  stopped and deleted afterwards. The final row states are in
  `admissions-states2.csv`.
- Model table: read live from the data branch: snapshot 571b55d2, table
  f1847561. The call list and the transports were re-checked on this code and
  match run 1 (`listing2.err`). The same `only.txt` was used.
- A new spend ledger, `spend2.jsonl`, was used. `spend.jsonl` was not reused.

## Commands (from wt-agent-genid, python = /home/user/venv-agent/bin/python)

```
# Dry run: PASS (11 settled, scripted, 0.0392)
env -u BOUNDED_TEST_DATABASE_URL python -m tests.m10_paid_checks.run --spend-ledger s7-paid/dry2.jsonl --report s7-paid/dry2-report.json
# Live run
BOUNDED_TEST_DATABASE_URL=postgresql://postgres@127.0.0.1:55433/bounded_test python -m tests.m10_paid_checks.run   --execute --cap-usd 0.95 --spend-ledger s7-paid/spend2.jsonl --report s7-paid/report2.json --only $(cat s7-paid/only.txt)
# Status lookup, free reads after the run: OpenRouter GET /api/v1/generation for each settled receipt
PYTHONPATH=. python s7-paid/status_check.py <db url> s7-paid/spend2.jsonl   # the server's recover_cost
PYTHONPATH=. python s7-paid/binding_diag.py <db url> s7-paid/spend2.jsonl   # which part of the binding differs
```

## Per call (run 2)

All 43 upstream requests went to `openrouter.ai`, and every answer was HTTP
200. The driver does not query status for a call that settles, so the status
column comes from a separate free lookup of each settled receipt's generation
id, run after the driver finished.

| Call | Proto | Outcome | Max USD | Actual USD | Status lookup (generation id / model / cost) |
|---|---|---|---|---|---|
| v1-k3-with-controls-text | v1 | settled | 0.16866667 | 0.0103285 | id ok; model differs (moonshotai/kimi-k3-20260715); cost ok |
| v1-k3-without-controls-text | v1 | settled | 0.05866667 | 0.00205275 | id ok; model differs (moonshotai/kimi-k3-20260715); cost ok |
| v1-k3-without-controls-forced-t0 | v1 | settled | 0.10266667 | 0.00098838 | id ok; model differs (moonshotai/kimi-k3-20260715); cost ok |
| v1-openrouter-sonnet5-text | v1 | settled | 0.06600000 | 0.002814 | id ok; model differs (anthropic/claude-sonnet-5-20260630); cost ok |
| v1-openrouter-glm52-text | v1 | settled | 0.02933334 | 0.0000447264 | id ok; model differs (z-ai/glm-5.2-20260616); cost differs <1e-9 |
| v2-anthropic/claude-opus-5.5-text | v2 | settled | 0.13200000 | 0.000156 | id ok; model differs (anthropic/claude-opus-5.5-20260921); cost ok |
| v2-anthropic/claude-opus-5.5-tool-loop#1 | v2 | settled | 0.19066667 | 0.003168 | id ok; model differs (anthropic/claude-opus-5.5-20260921); cost ok |
| v2-anthropic/claude-opus-5.5-tool-loop#2 | v2 | settled | 0.22000000 | 0.002544 | id ok; model differs (anthropic/claude-opus-5.5-20260921); cost ok |
| v2-anthropic/claude-sonnet-4.5-text | v2 | settled | 0.08066667 | 0.00012 | id ok; model differs (anthropic/claude-4.5-sonnet-20250929); cost ok |
| v2-anthropic/claude-sonnet-5-text | v2 | settled | 0.06600000 | 0.000074 | id ok; model differs (anthropic/claude-sonnet-5-20260630); cost ok |
| v2-anthropic/claude-sonnet-5.5-text | v2 | settled | 0.06600000 | 0.000088 | id ok; model differs (anthropic/claude-sonnet-5.5-20260928); cost ok |
| v2-anthropic/claude-sonnet-5.5-tool-loop#1 | v2 | settled | 0.09533334 | 0.001584 | id ok; model differs (anthropic/claude-sonnet-5.5-20260928); cost ok |
| v2-anthropic/claude-sonnet-5.5-tool-loop#2 | v2 | settled | 0.11000000 | 0.001262 | id ok; model differs (anthropic/claude-sonnet-5.5-20260928); cost ok |
| v2-deepseek/deepseek-v4-flash-text | v2 | settled | 0.00733334 | 0.000004956 | id ok; model differs (deepseek/deepseek-v4-flash-20260423); cost ok |
| v2-google/gemini-3.8-flash-text | v2 | settled | 0.02933334 | 0.00001425 | id ok; model differs (google/gemini-3.8-flash-20260902); cost ok |
| v2-google/gemini-3.8-flash-tool-loop#1 | v2 | settled | 0.03666667 | 0.000357 | id ok; model differs (google/gemini-3.8-flash-20260902); cost ok |
| v2-google/gemini-3.8-flash-tool-loop#2 | v2 | settled | 0.04400000 | 0.0001335 | id ok; model differs (google/gemini-3.8-flash-20260902); cost ok |
| v2-inception/mercury-2.5-text | v2 | settled | 0.00733334 | 0.00002443 | id ok; model differs (inception/mercury-2.5-20260908); cost ok |
| v2-inclusionai/ling-3.0-flash-text | v2 | settled | 0.00733334 | 7.35E-7 | id ok; model differs (inclusionai/ling-3.0-flash-20260723); cost ok |
| v2-inclusionai/ling-3.0-flash-fin-text | v2 | settled | 0.00733334 | 0.0000014644 | id ok; model differs (inclusionai/ling-3.0-flash-fin-20260827); cost differs <1e-9 |
| v2-inclusionai/ling-3.0-flash-vl-text | v2 | settled | 0.00733334 | 7.322E-7 | id ok; model differs (inclusionai/ling-3.0-flash-vl-20260910); cost differs <1e-9 |
| v2-mistralai/ministral-8b-2512-text | v2 | settled | 0.00733334 | 0.0000021 | id ok; model ok; cost ok |
| v2-moonshotai/kimi-k3-text | v2 | settled | 0.16866667 | 0.0012808 | id ok; model differs (moonshotai/kimi-k3-20260715); cost ok |
| v2-openai/gpt-6-luna-text | v2 | settled | 0.00733334 | 0.0000039 | id ok; model differs (openai/gpt-6-luna-20260922); cost ok |
| v2-openai/gpt-6-sol-text | v2 | settled | 0.06600000 | 0.000078 | id ok; model differs (openai/gpt-6-sol-20260922); cost ok |
| v2-openai/gpt-6.1-sol-text | v2 | settled | 0.06600000 | 0.000078 | id ok; model differs (openai/gpt-6.1-sol-20260929); cost ok |
| v2-openai/gpt-6.1-sol-tool-loop#1 | v2 | settled | 0.09533334 | 0.00037 | id ok; model differs (openai/gpt-6.1-sol-20260929); cost ok |
| v2-openai/gpt-6.1-sol-tool-loop#2 | v2 | settled | 0.11000000 | 0.00036 | id ok; model differs (openai/gpt-6.1-sol-20260929); cost ok |
| v2-qwen/qwen3.8-2.4t-a95b-text | v2 | settled | 0.03666667 | 0.00024 | id ok; model differs (qwen/qwen3.8-2.4t-a95b-20260812); cost ok |
| v2-qwen/qwen3.8-2.4t-a95b-tool-loop#1 | v2 | settled | 0.05133334 | 0.001416 | id ok; model differs (qwen/qwen3.8-2.4t-a95b-20260812); cost ok |
| v2-qwen/qwen3.8-2.4t-a95b-tool-loop#2 | v2 | settled | 0.05866667 | 0.000986 | id ok; model differs (qwen/qwen3.8-2.4t-a95b-20260812); cost ok |
| v2-qwen/qwen3.8-max-0902-text | v2 | settled | 0.03666667 | 0.000246 | id ok; model differs (qwen/qwen3.8-max-20260902); cost ok |
| v2-qwen/qwen3.8-max-0902-tool-loop#1 | v2 | settled | 0.05133334 | 0.000964 | id ok; model differs (qwen/qwen3.8-max-20260902); cost ok |
| v2-qwen/qwen3.8-max-0902-tool-loop#2 | v2 | settled | 0.05866667 | 0.00105 | id ok; model differs (qwen/qwen3.8-max-20260902); cost ok |
| v2-upstage/solar-pro4-text | v2 | settled | 0.00733334 | 0.00011115 | id ok; model differs (upstage/solar-pro4-20260810); cost ok |
| v2-xiaomi/mimo-v2.6-flash-text | v2 | settled | 0.00733334 | 0.00000277 | id ok; model differs (xiaomi/mimo-v2.6-flash-20260921); cost ok |
| v2-xiaomi/mimo-v2.6-pro-text | v2 | settled | 0.00733334 | 0.00002211 | id ok; model differs (xiaomi/mimo-v2.6-pro-20260921); cost ok |
| v2-z-ai/glm-5.3-text | v2 | settled | 0.02200000 | 0.000017 | id ok; model differs (z-ai/glm-5.3-20260816); cost ok |
| v2-z-ai/glm-5.3-tool-loop#1 | v2 | settled | 0.03666667 | 0.000056516 | id ok; model differs (z-ai/glm-5.3-20260816); cost ok |
| v2-z-ai/glm-5.3-tool-loop#2 | v2 | settled | 0.03666667 | 0.000059782 | id ok; model differs (z-ai/glm-5.3-20260816); cost ok |
| v2-z-ai/glm-5.3-flash-text | v2 | settled | 0.00733334 | 0.0000023 | id ok; model differs (z-ai/glm-5.3-flash-20260826); cost ok |
| v2-z-ai/glm-5.3-flash-tool-loop#1 | v2 | settled | 0.00733334 | 0.0000376 | id ok; model differs (z-ai/glm-5.3-flash-20260826); cost ok |
| v2-z-ai/glm-5.3-flash-tool-loop#2 | v2 | settled | 0.00733334 | 0.00001776 | id ok; model differs (z-ai/glm-5.3-flash-20260826); cost ok |

Total actual 0.0331632120 USD; sum of maxima 2.48600017; ledger committed 0.0331632120 of 0.95


## Status lookup: still failing, with a diagnosis

For each settled call, OpenRouter's `/api/v1/generation` was looked up under
the receipt's generation id:

- **Generation id:** it matches for all 43 calls.
- **Cost:** it matches for 40 calls. The other 3 (glm-5.2, ling-3.0-flash-fin,
  ling-3.0-flash-vl) differ by less than 1e-9 USD. The generation record rounds
  `total_cost` to 9 decimal places, while the answer's `usage.cost` carries
  more digits. Settlement uses `usage.cost`, so this is harmless.
- **Model:** it differs for 42 of 43 calls. The generation record names the
  model by OpenRouter's dated or canonical slug, for example
  `moonshotai/kimi-k3-20260715`, `anthropic/claude-4.5-sonnet-20250929` and
  `qwen/qwen3.8-max-20260902`. `recover_cost` requires
  `data.model == metadata.model` exactly, so it raises
  `generation_binding_mismatch` for every model except
  `mistralai/ministral-8b-2512`, whose slug is already dated.

Why it matters: `/status` calls `recover_cost` only for a `dispatched`
OpenRouter row that has a generation id but no cost. That is the path for an
execute that fails after the id is stored. On that path the recovery would
never succeed, and the hold would stay at its maximum.

Run 2's settled calls are not affected. Even the dated-suffix rule of
`response_model_matches` would not cover every slug, for example
`claude-sonnet-4.5` against `claude-4.5-sonnet-20250929`, or
`qwen3.8-max-0902` against `qwen3.8-max-20260902`.

## Not run (run 2)

The Anthropic direct calls were not run, because the key is invalid:

- v1: haiku-forced-tool-t0, sonnet5-direct-text, opus5-direct-text, and
  sonnet5-direct-tool-loop.
- v2: claude-opus-5-5 (text and loop), claude-sonnet-4-5, claude-sonnet-5, and
  claude-sonnet-5-5 (text and loop).

Every OpenRouter call ran.

# Run 1: defect found, mrcall-agent bb8f553

Plan `2026-10-02-model-selection-m10`, S7 "Paid, local, after IR4", and IR4
round 1 "Before production (a)". Driver: mrcall-agent
`tests/m10_paid_checks/run.py` at bb8f553 (mrcall-agent main and dev). The
worktree was left unchanged.

### Result: FAILED, with a server defect found

Every OpenRouter call that goes through OpenRouter's Messages API
(`/api/v1/messages`) fails on the server after the provider answers. The
provider returns HTTP 200 with `usage.cost`, and the server's execute then
returns 502 `bounded_upstream_uncertain_check_status`, so the admission stays
`dispatched` with no evidence stored. Only the K3 chat-completions adapter
call settled.

### Setup

- Python: `/home/user/venv-agent` (it has mrcall-agent's requirements).
- Admission ledger: a throwaway PostgreSQL 16 cluster on 127.0.0.1:55432 with
  database `bounded_test`. It ran in `/tmp/s7-paid-pg`, not under the scratch
  dir: the harness keeps `/tmp/claude-0` at mode 0700, and PostgreSQL will not
  run as root. The cluster was stopped and deleted afterwards. The final row
  states are in `admissions-states.csv`.
- Model table: read live from the data branch (`published_table_read: true`):
  snapshot 571b55d2…, table f1847561….
- Keys came from the environment only. A grep confirmed that no key value
  appears in any output file.

### Commands

```
cd <wt-agent>
# 1. Dry run (scripted providers, in-memory SQLite ledger)
env -u BOUNDED_TEST_DATABASE_URL /home/user/venv-agent/bin/python -m tests.m10_paid_checks.run \
  --spend-ledger s7-paid/dry.jsonl --report s7-paid/dry-report.json
# 2. List the live call names (the driver refuses an unknown --only before any call; nothing dispatched)
BOUNDED_TEST_DATABASE_URL=postgresql://postgres@127.0.0.1:55432/bounded_test /home/user/venv-agent/bin/python \
  -m tests.m10_paid_checks.run --execute --spend-ledger s7-paid/listing-probe.jsonl --only __list_calls__
# 3. Live run, OpenRouter-transport calls only (the list is in only.txt: 5 v1 names and 30 v2 names)
BOUNDED_TEST_DATABASE_URL=postgresql://postgres@127.0.0.1:55432/bounded_test /home/user/venv-agent/bin/python \
  -m tests.m10_paid_checks.run --execute --cap-usd 1.00 --spend-ledger s7-paid/spend.jsonl \
  --report s7-paid/report.json --only $(cat s7-paid/only.txt)
```

Transports were classified read-only from the published snapshot
(`classify.py`, which calls `model_table.refresh()` and `priced(id).transport`).
Every id whose transport is `anthropic` was left out of `--only`.

### Dry run: PASS

11 calls settled. The committed copy was used, so the v2 list held K3 only.
Total 0.0392 of the 1.00 cap, all scripted, and nothing left the process.

### Live run: per call

"Ledger actual" is what the driver's spend ledger records. "Provider cost" is
OpenRouter's `usage.cost` from the 200 answer, as captured by the recorder. All
18 upstream requests went to `openrouter.ai` and all returned HTTP 200.

| Call | Proto | Path | Outcome | Max USD | Ledger actual | Provider cost |
|---|---|---|---|---|---|---|
| v1-k3-with-controls-text | v1 | chat/completions | settled | 0.16866667 | 0.0043715 | 0.0043715 |
| v1-k3-without-controls-text | v1 | messages | 502, dispatched, uncertain | 0.05866667 | null (held at max) | 0.00299625 |
| v1-k3-without-controls-forced-t0 | v1 | messages | 502, uncertain | 0.10266667 | null | 0.0023613 |
| v1-openrouter-sonnet5-text | v1 | messages | 502, uncertain | 0.06600000 | null | 0.001214 |
| v1-openrouter-glm52-text | v1 | messages | 502, uncertain | 0.02933334 | null | 0.0000595 |
| v2-anthropic/claude-opus-5.5-text | v2 | messages | 502, uncertain | 0.13200000 | null | 0.000196 |
| v2-anthropic/claude-opus-5.5-tool-loop#1 | v2 | messages | 502, uncertain (upstream gave tool_use) | 0.19066667 | null | 0.003168 |
| v2-anthropic/claude-opus-5.5-tool-loop#2 | v2 | - | not run (turn 1 failed) | - | - | - |
| v2-anthropic/claude-sonnet-4.5-text | v2 | messages | 502, uncertain | 0.08066667 | null | 0.00012 |
| v2-anthropic/claude-sonnet-5-text | v2 | messages | 502, uncertain | 0.06600000 | null | 0.000074 |
| v2-anthropic/claude-sonnet-5.5-text | v2 | messages | 502, uncertain | 0.06600000 | null | 0.000078 |
| v2-anthropic/claude-sonnet-5.5-tool-loop#1 | v2 | messages | 502, uncertain (upstream gave tool_use) | 0.09533334 | null | 0.001584 |
| v2-anthropic/claude-sonnet-5.5-tool-loop#2 | v2 | - | not run (turn 1 failed) | - | - | - |
| v2-deepseek/deepseek-v4-flash-text | v2 | messages | 502, uncertain | 0.00733334 | null | 0.000005 |
| v2-google/gemini-3.8-flash-text | v2 | messages | 502, uncertain | 0.02933334 | null | 0.0000105 |
| v2-google/gemini-3.8-flash-tool-loop#1 | v2 | messages | 502, uncertain (upstream gave tool_use) | 0.03666667 | null | 0.000147 |
| v2-google/gemini-3.8-flash-tool-loop#2 | v2 | - | not run (turn 1 failed) | - | - | - |
| v2-inception/mercury-2.5-text | v2 | messages | 502, uncertain | 0.00733334 | null | 0.0000264 |
| v2-inclusionai/ling-3.0-flash-text | v2 | messages | 502, uncertain | 0.00733334 | null | 0.0000007 |
| v2-inclusionai/ling-3.0-flash-fin-text | v2 | messages | 502, uncertain | 0.00733334 | null | 0.0000015 |
| v2-inclusionai/ling-3.0-flash-vl-text | v2 | messages | 502, uncertain | 0.00733334 | null | 0.0000007 |
| v2-mistralai/ministral-8b-2512-text | v2 | - | stopped at cap (0.99437157 + 0.00733334 > 1.00) | - | - | - |

For a tool-loop second turn, the driver reports "the first turn gave no tool
call". The actual cause is that turn 1 returned 502, so the driver had no
answer to replay. The recorder shows that the provider did return `tool_use`.

**Spend:** the ledger's committed total is 0.99437157 of the 1.00 cap. That is
the one settled call plus 17 uncertain calls, each held at its maximum. The
provider-reported cost of all 18 dispatched calls is 0.0164 USD.

### Diagnosis

`execute` (`mrcall_agent/api/routes/desktop_bounded_llm.py`) runs these steps
after `upstream()`:

1. Check the model.
2. `openrouter.generation_id(message)`.
3. `store.annotate(... generation_id)`.
4. `accounting()`.

All 17 failing rows still have `receipt` null in the admission ledger, so the
code raised before step 3. The recorder shows that each answer's `model`
equals the requested id, so the model check passed. That leaves
`generation_id()` (`mrcall_agent/services/bounded_openrouter.py:199`). It
requires `id` to start with `gen-`. The K3 adapter path decodes a Chat
Completions answer, which keeps the `gen-` id, and that call settled.

Conclusion (inferred, because the recorder does not capture the answer `id`):
OpenRouter's Messages API is returning ids without the `gen-` prefix. The test
fixtures and the scripted dry-run provider assume `gen-`, which is why the dry
run and the suite pass. Confirming this needs the shape of the `id` (its
prefix only). A recorder that kept the id prefix would capture it at the cost
of one cheap call.

### Not run

- **Anthropic direct calls:** v1-haiku-forced-tool-t0, v1-sonnet5-direct-text,
  v1-opus5-direct-text, v1-sonnet5-direct-tool-loop, and v2 claude-opus-5-5
  (text and loop), claude-sonnet-4-5, claude-sonnet-5, and claude-sonnet-5-5
  (text and loop). They were excluded because MNEMONIC_ANTHROPIC_API_KEY is
  known to be invalid. The driver only checks that the variable is set, so
  `--only` was enough and no flag or patch was needed.
- **Past the cap:** v2 mistralai/ministral-8b-2512, openai/gpt-6-luna,
  openai/gpt-6-sol, openai/gpt-6.1-sol (text and loop),
  qwen/qwen3.8-2.4t-a95b (text and loop), qwen/qwen3.8-max-0902 (text and
  loop), upstage/solar-pro4, xiaomi/mimo-v2.6-flash, xiaomi/mimo-v2.6-pro,
  z-ai/glm-5.3 (text and loop), z-ai/glm-5.3-flash (text and loop), plus
  moonshotai/kimi-k3 v2 text. The driver stopped at the cap because the
  uncertain calls are held at their maxima.
- No call was retried or rerun. `spend.jsonl` is now exhausted against a 1.00
  cap. Running the remaining calls needs a fixed `generation_id` handling and
  a fresh ledger, with a new authorization for that spend. (Run 2 used a fresh
  ledger capped at USD 0.95 under the CTO's standing instruction for this
  milestone to finish within the approved caps without further go for small
  spends; real spend across both runs was about USD 0.05, inside S7's USD 1.)

### Files (s7-paid/)

`dry.out`, `dry.jsonl`, `dry-report.json`, `only.txt`, `live.out`,
`spend.jsonl`, `report.json` (settings and answer metadata only),
`admissions-states.csv`, `classify.py`, `listing.err`

Run 2 files: `dry2.out`, `dry2.jsonl`, `dry2-report.json`, `listing2.err`,
`live2.out`, `spend2.jsonl`, `report2.json`, `admissions-states2.csv`,
`status_check.py`, `status2.tsv`, `binding_diag.py`, `binding2.tsv`,
`table2.md`

# Follow-up: recovery binding fixed (mrcall-agent bdc2666)

The status-recovery finding of run 2 is fixed on mrcall-agent `main` and `dev`
(`bdc2666`, reviewed APPROVED): recovery binds the persisted generation id and
accepts the generation record's model when it equals the requested id or that
id's `canonical_slug` in OpenRouter's public catalogue (read without a key,
3 s bound, cached one hour, a failed or empty read never kept). All 43 live
records of run 2 recover under the rule (fixture
`tests/fixtures/openrouter_generation_models.json`). Production `37f330d` has
both defects; a hotfix carrying both fixes is prepared, unpushed, for the CTO's
go. Rows that ended `dispatched` without a generation id before the fix
(including run 1's 17) cannot be recovered and need manual reconciliation.
