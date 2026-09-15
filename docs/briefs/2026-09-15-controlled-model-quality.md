# Controlled engine quality comparison with an Opus reference

The prior three-thread evaluation lacked an equal-input Opus control and could
not answer the CTO's question: can engine cost fall while retaining the quality
observed with Opus? Complete that comparison before recommending configuration.
An earlier synthetic result is not a production-quality reference, and a small
failure fraction is not an estimated mailbox-wide error rate.

Scope: run Opus on the already frozen real requests; independently preregister a
50-thread stratified set of distinct real threads covering identities, commitments, noise,
corrections and task lifecycle. Compare original prompts across Opus, K3 and GLM
on identical inputs using the actual adapter/parser. Diagnose the provider errors
without hiding failed attempts or conflating transport failure with reasoning.
If fixing a prompt, use development cases only, freeze the candidate and test on
held-out cases, with Opus included. Retain raw evidence privately and provide
aggregate role-level quality, availability, costs, and a concrete go/no-go outcome.

Constraints: total scratch allowance at most USD20 INCLUDING the previous
experiment's settled usage and outstanding reservations; keep its existing ledger,
never release unknown holds to make room. The expanded allowance belongs only to
this explicitly requested completion; no production budget/key/model changes,
no mailbox actions or backlog resumption. Keys remain in process memory. No
automatic inference retries or unbounded prompt search. A failed response remains
in the denominator; output truncation is a completion failure, never a model win.

Quality: source evidence and owner instructions define truth, never another
model's answer or previously generated memory. Use independent blinded grading,
explicit consequential versus minor errors, per-role denominators, and individual
paired comparisons. Opus is a comparator, not an oracle. No zero-error/equivalence
claim from this sample. A final recommendation must say exactly which role/model
is or is not supported by the evidence and what remains untested, without making
the CTO extract limitations by questioning the report.

The CTO explicitly rejects a three-case experiment as inadequate. The matrix
must include 50 distinct threads (memory and task roles each), with a fixed
development/held-out split and a preselected repeated subset. Sample size is
reported at the independent-thread level; paired roles/repeats do not inflate it.
Even 50 threads cannot establish near-zero rare-error rates. Do not claim
mailbox-wide representativeness from deliberately stratified selection.
