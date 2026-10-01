# Mnemonic corpus — live run, 2026-10-01

Arm `anthropic-byok`, model `claude-haiku-4-5`, prompt version `9d4a1fdfe1f5`, extraction prompt `352eaba92e38`, MNEMONIC_MAX_TOKENS 2048, cap USD 10.00, engine `88e2370e6`, kernel not used, embedder EmbeddingEngine.

| case | class | verdict | outcomes | cost USD | calls | ms | intent |
|---|---|---|---|---|---|---|---|
| unrelated_same_name_people | automatic_observation | pass | committed | 0.0053 | 2 | 6713 | e272d005 |
| shared_switchboard | automatic_observation | pass | committed, review_needed | 0.0085 | 3 | 7177 | fca63c3a |
| corroborated_same_person | automatic_observation | pass | committed | 0.0058 | 2 | 5524 | d7f3623c |
| planned_not_completed | automatic_observation | noncritical | pending | 0.0010 | 1 | 2713 | 0c35319f |
| contradictory_legacy_fact_rule | automatic_observation | noncritical | pending | 0.0009 | 1 | 2507 | 884077ac |
| multi_entity_source | automatic_observation | pass | committed, review_needed | 0.0091 | 3 | 7519 | 6320ec2b |
| customer_forwarding_number_correction | verified_human_correction | noncritical | committed | 0.0039 | 1 | 2800 | b5b2c3fa |
| customer_price_correction | verified_human_correction | critical_failure | committed | 0.0038 | 1 | 3452 | e67aed0b |
| global_opening_hours | verified_human_correction | noncritical | committed | 0.0034 | 1 | 2345 | 049de106 |
| account_feedback | verified_human_correction | noncritical | committed | 0.0034 | 1 | 2570 | 2ab1df1a |

## Noncritical disagreements (listed, no score)

- planned_not_completed: no commit and no allowed outcome: 
- contradictory_legacy_fact_rule: no commit and no allowed outcome: 
- customer_forwarding_number_correction: must_preserve missing: correction
- customer_price_correction: must_preserve missing: ottobre
- customer_price_correction: must_preserve missing: concordato
- global_opening_hours: must_preserve missing: chiusi
- global_opening_hours: must_preserve missing: sabato
- account_feedback: must_preserve missing: punti esclamativi
- account_feedback: must_preserve missing: prossimo passo

## Checks

- canary: `{"verdict": "refused", "validator": "accepted", "calls": 1, "cost_usd": 0.00286}`
- budget_refusal: `{"outcome": "retryable_failure", "reason": "paid decision unavailable: AI paused: daily budget $0.00; used or reserved $0.05. This request needs up to $0.04. Daily usage resets at 2026-10-02T00:00:00Z; unresolved calls remain reserved.", "allowance_untouched": true, "open_holds": 0, "wire_calls": "live", "calls": 0, "cost_usd": 0.0}`
- unpriced_refusal: `{"outcome": "retryable_failure", "reason": "paid decision unavailable: AI paused: model pricing is not configured for this model.", "message_matches": true, "label": "fail-closed behaviour, not semantic health", "calls": 0, "cost_usd": 0.0}`
- truncation_refusal: `{"override": 16, "restored": true, "outcome": "review_needed", "attempts": 1, "calls": 3, "cost_usd": 0.008123}`

The canary is `merge_gate_selfcheck` called directly inside an explicit preparation run of the profile: `merge_canary_policy` and `record_merge_canary` are not exercised and the verdict is not persisted to worker state. A check may have run more than once on this profile (a retried check is a new `check:*` intent); the manifest's intents list shows every attempt, and the check entry above is the last one.

## Cost

Settled USD 0.0766, held USD 0.0000, open intents USD 0.0000, cap USD 10.00.

## Limits

The unpriced refusal is fail-closed behaviour, not semantic health. Live run on the arm above; every cost is the profile ledger's. Totals rewritten 1 time(s) from the profile ledger after the corpus (record-only mode); the rows are the original run's.

Of the USD 0.0766 settled, USD 0.0560 is attributable to the corpus and check intents above; the remaining USD 0.0206 is the 3 untagged calls of the sidecar approval fixture (`app/scripts/test-sidecar.mjs`, one turn on the same profile before the final ledger read), folded in by the record-only rewrite. The kernel line above reads "not used" because the corpus runs no kernel command; the committed line originally read `unavailab`, the first nine characters of the runner's "unavailable" sentinel, corrected with the runner on 2026-10-01.

**The critical failure (AC 5 not met).** `customer_price_correction` is a `critical_failure`: the role CREATEd a new Boreale COMPANY blob (`5762b8e8…`) and left the seeded required target (`42a35975…`) untouched. The final reviewer's probe showed that `wiring.candidates_for` returns the seeded legacy blob first (source: cosine) for that event, so the role was shown it and chose CREATE over UPDATE on a headerless legacy candidate (`mnemonic_cases.candidate_content` keeps legacy rows headerless by design; `corpus_live_env.py:214-229`). This is model behaviour on the `claude-haiku-4-5` arm, correctly flagged by the harness, not a seeding defect. The rollout's step-1 exit condition ("every critical case passes") is therefore not reached by this run. Open decision for the CTO, not taken here: accept the finding against a legacy-shaped candidate and proceed, or hold.

**Per-round fields not captured (AC 4 partly met).** D4 asks for the proposal of each round, the validator result and reasons per round, the number of rounds, the retained version and the latency per round. Every `.jsonl` row has `proposal` null: the journal prunes the payload at terminal states (`zylch/memory/mnemonic/journal.py:409-411`) and the runner reads only the journal afterwards (`corpus_live_record.py:60-84`), so only the terminal outcome, the terminal reason, `attempts` and the per-case latency survive. The run was not repeated for them; for the one critical case the reviewer's probe above is the per-round evidence this record has.

**The two pending automatic cases.** `planned_not_completed` and `contradictory_legacy_fact_rule` carry reason "" and `attempts` 0: the retryable-failure reason exists only in the worker log and is not captured. The engine settles a zero-entity extraction as `skipped` (`ingestion.py:349-353`), but a parent stays `pending` with no child when `_extract` raised, returned as `RETRYABLE_FAILURE` without a receipt (`ingestion.py:342-345`); the worker raises on any answer that is neither bare `SKIP` nor an `#IDENTIFIERS` block (`workers/memory.py:705-749`, e.g. "SKIP — nothing durable"). A deterministic answer shape is therefore re-paid on every run, `attempts` stays 0 and no reason reaches the journal. Known issue, recorded in the M9 build plan.

**The must_preserve misses are one finding.** The judge is a case-insensitive substring by design. The seven misses above are the role translating every Italian correction into English (e.g. "The company is closed every Saturday", "avoid exclamation marks") and writing "corrected" where the expectation holds "correction". The brief's section 9 asked for original-language corrections; this is a semantic finding on the arm, listed for review without a score.
