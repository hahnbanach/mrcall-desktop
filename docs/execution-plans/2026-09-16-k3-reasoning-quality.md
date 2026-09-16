---
status: completed
---
# K3 reasoning experiment delivery

Brief: [reasoning quality](../briefs/2026-09-16-k3-reasoning-quality.md).

1. Confirm historical wire behavior and current provider contract from source,
   archived response metadata and official documentation. Record free wallet
   balance separately from a key's daily spending limit.
2. Review the design before paid dispatch. Freeze seed 20260916, four episodes
   from each of the five original held-out strata, both roles, and all 20 arrival
   tasks. Freeze all three arms, source/rubric hashes and deterministic interleaved
   order before seeing new responses. Historical Opus grades include the
   2026-09-16 storage-assertion correction.
3. Implement an evaluation-only opt-in transport and runner integration. Validate
   exact K3 thinking/effort shapes, preserve full ceiling reservations, retain
   raw responses and thinking-token counts, reject unknown features before HTTP,
   and preserve no-retry durable intents. Unit tests and independent review gate
   paid calls. Production runtime defaults are not modified.
4. Preselect one memory and one positive-task max-effort cell as compatibility
   probes. They count within the 180-cell matrix, never as extra independent
   evidence. Verify provider identity, outgoing controls, reported thinking
   tokens, forced-tool behavior, cost settlement and token limit before the main
   run. A failed or truncated model answer remains the first observed answer.
   At most these two cells may execute before account replenishment.
5. Execute remaining cells at global concurrency one with fixed provider and
   unchanged price ceilings. A USD10 dedicated ledger includes every dispatch
   and uncertain hold, with no rollover reset. Three consecutive availability
   failures stop dispatch. Do not recharge accounts automatically.
6. Prepare blinded packs masking arm/provider/cost/effort and private thinking.
   Grade only final text/tools against unchanged source and owner rules. Separate
   semantic, contract, completion and parser outcomes. No successful-answer
   retries; missing outputs remain in the planned denominator.
7. Independently review paired pass/fail transitions, consequential error classes,
   reasoning/output token use, latency and actual costs per role/cohort. Compare
   disabled-large to disabled-original (ceiling effect) and max-large to
   disabled-large (reasoning effect). Report Opus as historical context, not a
   contemporaneous provider-controlled arm. Do not choose defaults solely from
   aggregate pass counts or claim generalization on the reused diagnostic corpus.
8. Publish a sanitized report and code, archive raw evidence privately, reconcile
   living docs, run relevant tests and documentation checks, commit and push.
   Any deployment or new-data confirmation is a separate scope; no mailbox
   processing or outgoing business actions occur in this experiment.

## Evidence

Historical K3 arrival wire hashes reconstruct exactly with thinking disabled.
All 20 selected arrival outputs report zero thinking tokens; 18 used DigitalOcean
and two Makora. Free provider metadata advertises adaptive reasoning/effort and
forced tools on DigitalOcean; exact combination requires the compatibility gate.
The initial account balance was approximately USD0.88 despite a USD20 remaining
key limit; the subsequent replenishment is recorded below.


## Reviewed execution freeze

Design and implementation reviews approve the three-arm experiment and isolated
transport. The frozen selection contains 60 role requests across 37 distinct
business clusters (20 base episodes and 20 arrivals, three overlapping).
The two compatibility cells and 178 remaining cells are disjoint. All arms use
one parser/adapter revision and current guarded tool-completion normalization;
historical Opus comparisons concern semantic quality only.

The summed worst-case reservations are USD31.452015, not predicted spending;
only one request is active, with maximum single reservation USD0.339069.
Historical same-input disabled cost is USD1.002288. A forecast of three such
passes plus 3,000–6,000 extra thinking tokens per maximum-effort call yields
USD5.40–7.79. The USD10 hard ceiling wins over coverage: any unexecuted cells
remain explicitly missing. Confirmed account funding is approximately USD20.88.
Exact adaptive/max controls and reported thinking tokens establish requested
configuration and active reasoning; without provider effort echo, the actual
internal maximum cannot independently be certified.


## Reviewed wire-protocol repair

Both initial Messages compatibility attempts return HTTP404 before provider
selection: the fixed endpoint passes price/routing filters but fails parameter
filtering for adaptive thinking/output_config. These failures remain recorded,
with USD0.358544 conservatively held; no model response is available to grade.

Use the documented Chat Completions reasoning controls in a second explicit
compatibility phase: `reasoning: {effort: max}` or `{enabled: false}`. All three
comparison arms share this protocol, same DigitalOcean provider and price caps.
Keep input text/tool schemas/forced name/clocks intact through deterministic
format translation. Price the translated wire conservatively, preserve original
responses and reasoning usage, and do not weaken parameter enforcement.

Exactly the same two preselected compatibility cases receive one attempt under
this changed protocol. They remain part of the 180-cell matrix; the two earlier
parameter rejections are separate operational attempts. No semantic response is
retried. Freeze v2 manifests and source hashes before dispatch; review transport,
unit tests and request bindings again. The same USD10 ledger retains all earlier
holds. Maximum internal effort remains a requested setting, not independently
observable; active reasoning must be corroborated by reported thinking tokens.


Reasoning comparison HTTP calls use a 600-second timeout setting: the 8192-token shared
ceiling can take longer than the ordinary 180-second timeout at this provider's
throughput. This evaluation-only HTTP timeout setting applies identically to all arms and
has no production effect; a timeout retains its reservation without retry.


## Funded main-run scheduling amendment

After successful compatibility and independent review, the remaining comparison
may run at global/per-model concurrency three. The replenished account has about
USD20.88, the independent local experiment cap remains USD10, and atomic admission
bounds three simultaneous reservations to at most USD1.026087 at the measured
maximum request bound. This changes scheduling only, not frozen input, arm order,
provider, controls or retry policy. Durable intents and the availability circuit
remain active. Report actual start/completion order and costs rather than assuming
that cache effects or latencies are independent of serving order.

## Completion evidence

All 180 Chat cells returned and were graded once, with no response replacements.
The final report separates semantic, contract and parser outcomes by cohort and
includes paired transitions, actual receipts, cache effects, latency and the
historical Opus sensitivity. A blind cross-group consistency review adjudicates
one unresolved milk-policy premise; before/after judgments are preserved.
Independent accounting review reproduces all nine result rows and nine paired
contrasts, exact historical subsets, provider/control bindings and all costs.

The final ledger records USD3.219159 settled plus USD0.358544 retained holds,
within the USD10 ceiling. All 60 maximum-effort responses report reasoning use;
the 120 disabled responses report zero. No production configuration is promoted.
All 330 relevant LLM/evaluation/worker tests pass, and changed Python passes Ruff.
The documentation mechanical gate passes with existing advisory backlog only.
Final semantic review checks the result report and living snapshots against the
code and archived evidence. Production profiles, services and prompts are unchanged.

Evidence and reproduction scripts are archived privately under
`~/.local/share/mrcall/evaluations/2026-09-16-k3-reasoning/`; the sanitized
[result report](../evaluations/2026-09-16-k3-reasoning-quality.md) is versioned.
