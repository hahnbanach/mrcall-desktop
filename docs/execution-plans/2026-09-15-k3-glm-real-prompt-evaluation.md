---
status: completed
---
# K3 / GLM real-prompt comparison

Brief: [intent and limits](../briefs/2026-09-15-k3-glm-real-prompt-evaluation.md).

- [x] Independent brief review approved.
- [x] Review this plan and private source-grounded cases before paid calls.
- [x] Capture three short threads, trained prompts, actual request construction,
  parser expectations and reference facts/tasks without writing production data.
- [x] Run identical K3/GLM requests through the engine adapter in one isolated
  USD1 ledger; preserve original ordering/owner context and uncertain holds.
- [x] Independently grade anonymous outputs against preregistered expectations;
  report semantic and parser outcomes separately, actual cost and limitations.
- [x] Save a sanitized result report, review docs, commit/push task artifacts.

No automated inference retries. On incompatibility, diagnose with free metadata
first; any deliberate further attempt remains inside the same allowance. No
public raw mail, prompts, identifiers or outputs. No claim of representative
quality from short selected threads, and no production model changes or backlog
resumption. Provider availability is constrained by existing caps rather than
silently raising tariffs. Existing production reservations remain untouched.

Preflight: six actual requests (three memory + three task), original output
limits1024/500 and task tool schema preserved. Conservative aggregate upper
bound for all twelve calls is USD0.619367 (K3 0.508736; GLM 0.110631), below
the common USD1 allowance. Actual input includes owner rules and retrieval
context, around34k tokens per model by rough character estimate; no prompt was
truncated to meet a target input size. Current date is frozen once across
candidates using the engine datetime formatter.

The CTO also permits prompt improvements: baseline first, then a small justified
candidate tested against the same cases within this same allowance. No automatic
production application or resumption follows from a small-sample result.

## Prompt correction milestone

The output-blind memory candidate was independently approved: reconcile FACT
instructions with the sectioned parser contract and remove an unrelated example
containing unsupported invented facts. Owner rules, self-notion, messages, task
requests and output limits remain unchanged. The generic future-training fix also
required `facts_store.parse_value` to stop at exact section headers, preserving
legacy flat and multiline values. This is protocol parsing, not semantic labeling.
Implementation review approved; an independent run of 49 focused tests passed.
Stored production prompts remain unchanged.

K3's final baseline task and GLM's first task returned HTTP429. Free key metadata
showed sufficient allowance. No failed request was repeated; only previously
unattempted cases continued, retaining uncertain reservations in the same ledger.
The candidate uses six additional memory requests, no duplicate task calls, the
same frozen date, and the same USD1 ledger. Provider429 is an availability failure,
not a semantic quality verdict; no budget holds were manually released.

Final experiment: 18 attempts, 12 returned/parser-accepted, 6 semantically
acceptable in blinded review. USD0.090729 settled and USD0.297063 reserved.
The candidate did not improve observed semantic outcomes and was not promoted.
See [results](../evaluations/2026-09-15-real-engine-prompts.md).

Independent final end-to-end review APPROVED: counts, budget, source behavior,
limits and unchanged production state reconcile. Focused verification: 49 passed
with 13 warnings; new work-trace links resolve; diff check passes.
