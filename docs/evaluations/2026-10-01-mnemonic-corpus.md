# Mnemonic corpus — live run, 2026-10-01

Arm `anthropic-byok`, model `claude-haiku-4-5`, prompt version `9d4a1fdfe1f5`, extraction prompt `352eaba92e38`, MNEMONIC_MAX_TOKENS 2048, cap USD 10.00, engine `88e2370e6`, kernel `unavailab`, embedder EmbeddingEngine.

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
