# OpenRouter model comparison — 2026-09-13

Twelve synthetic requests, one per model/case, identical prompts and 4,096-token
output limits, thinking disabled. All responses completed. The reviewer graded
anonymous candidates before receiving the mapping or costs. This is a small
smoke comparison, not production quality certification.

| Model | Blind candidate | Semantic cases passed | Actual provider cost (USD) | Total seconds |
|---|---|---|---|---|
| Claude Opus 5 | D | 3/3, with caveats | 0.109285 | 45.35 |
| Claude Sonnet 5 | B | 3/3, with caveats | 0.026144 | 25.43 |
| Claude Haiku 4.5 | A | 1/3 | 0.011516 | 22.03 |
| Kimi K3 | C | 3/3, with caveats | 0.01431915 | 16.55 |

Costs are OpenRouter response `usage.cost`, excluding MrCall markup. Timing is
one sequential run, not a latency distribution. Haiku's consequential mistakes
support refusing an automatic downgrade; this sample does not establish an
Opus replacement. Saved production model choices remain unchanged and the four
incident accounts remain paused. K3's lower observed cost here includes output
length and routing, not just its advertised token rate.

The isolated USD1 ledger also includes earlier attempts: an Anthropic low-credit
failure, an OpenRouter Sonnet unsupported-parameter failure, and a pilot where
Opus extraction reached the 1,800-token output limit. Those pilot outputs are
excluded from the fair comparison. After the comparison, the ledger recorded
USD0.242826 spent and USD0.171170 unresolved holds; no limit or hold was reset.
Sonnet's incompatible default sampling field was fixed and independently
reviewed before rerunning all models with the same larger limit.

Synthetic inputs and anonymous outputs are in
[comparison-cases.json](comparison-cases.json). No customer mailbox content,
credentials or Firebase tokens are included.

## Production credit acceptance

A separate GLM request with a 32-token cap returned `OK`. Its verified
OpenRouter cost was USD0.00000941192; the quote-bound markup was1.5 and the
StarChat unit worth USD0.011. The receipt charged
`ceil(cost × 1.5 / 0.011) = 1` credit, and balance moved4→3. Two subsequent
free receipt-status reads returned the same settled receipt; balance stayed3.
Whole-credit rounding dominates this tiny request. Fractional aggregation is
not implemented, so this is not a claim of an effective1.5× price for every call.

The final isolated ledger records USD0.253826 spent and USD0.171170 held,
leaving USD0.575004 under the shared USD1 limit. Personal-key entry in the
packaged GUI remains the user's manual acceptance step.

## Independent blinded grading

Reviewed only `comparison-cases.json`; no model mapping or prices were viewed. Four anonymous candidates, three supplied synthetic cases each, one response per case. All supplied responses ended with `end_turn`.

## Rubric

A major error changes an actionable date, entity identity, financial commitment, or owner/action state. A minor error adds unsupported peripheral detail, weakens source attribution, or makes an imprecise representation while preserving the operative decision. A semantic pass requires the expected operative facts and no major error; “pass with caveats” is not a claim of production readiness. Formatting is reported separately. Counts group repeated statements of the same error together.

The extraction prompt does **not** state a year or current date. Its expected answer also does not require a calendar date for Monday. Therefore adding a year/date is assessed as unsupported detail; candidates must not be ranked on an assumed extraction-year ground truth. The task prompt explicitly supplies 2026-09-13, so Monday is September 14 and Tuesday is September 15 there.

| Candidate | Distinct people / shared relay | Corrected commitments | Tasks / waiting / cancellation |
|---|---|---|---|
| A | Pass | **Fail: 1 major, 2 minor groups** | **Fail: 2 major, 2 minor groups** |
| B | Pass | Pass with caveats: 2 minor groups | Pass |
| C | Pass | Pass with caveat: 1 minor group | Pass with caveat: 1 minor group |
| D | Pass | Pass with caveats: 3 minor groups | Pass with caveat: 1 minor group |

## Evidence

**Identity case:** all four return exactly `INSERT`. None combines the two people or assigns their shared relay address to either. This one explicit negative example does not establish merge quality on ambiguous or positive matches.

**A, extraction:** preserves the corrected 60 adults + 8 children, 12 vegetarian adults, unapproved quote, unexecuted payment and distinct Lucas. However, project status says “awaiting final pricing and director approval”: it promotes approval required only above EUR2,400 into an unconditional pending requirement, despite retaining the correct conditional in another field (major contradiction). Minor groups: adds “Monday 15 September 2026,” an unsupported year and internally incorrect weekday/date; invents an earlier portal-referent assertion and attribution to September 10.

**A, tasks:** incorrectly sets the venue's Monday arrival to September 15, contradicting the explicitly supplied calendar and compressing the dependency into the quote's Tuesday deadline (major). Lists awaiting Luca and the blocked quote under `active_actions`, despite supplying blocking/conditional labels and a separate waiting list (major classification inconsistency). Minor groups: invents an original “Friday Sep 13” and attributes its supersession to Sep12 rather than Sep13; creates a cancelled “Use v1 quote as approval basis” task that was never requested. Correctly cancels the van and identifies the immediate allergy response.

**B, extraction:** preserves all operative facts and conditionality. Minor groups: adds ambiguous “Monday (Sep 14 or 15)” and an unsupported event year; represents the finance department as a separate company and omits Venue from the company list, although its Luca affiliation remains clear. Task answer correctly separates the allergy response, external venue dependency, conditional Tuesday quote, cancelled van and obsolete Friday deadline; no major or minor semantic error identified there.

**C, extraction:** preserves the operative facts, including no spending commitment and only conditional director approval. Adds “Monday, September 15” without a supplied year/date basis (minor unsupported detail; not scored as a major calendar error). Task answer correctly distinguishes the blocked quote and cancelled van. It converts “can do immediately” into a hard-looking `due: 2026-09-13` rather than recording urgency without a formal deadline (minor).

**D, extraction:** preserves all operative facts and conditions. Minor groups: invents an earlier implicit portal-referent assertion; labels an unnamed finance function as a person; supplies a 2026 event date, while appropriately acknowledging year uncertainty in `unresolved` (its explanation refers to a current date not supplied in this extraction prompt). Task answer preserves the correct dates and conditions, but assigns Luca to the client side without supporting information (minor). Its allergy due field explicitly says there is no formal deadline, so it does not make C's deadline assertion.

## Limits and conclusion

B, C and D preserve the operative decisions in these three cases; A has consequential errors in two. B is the cleanest task response here, but the sample does not establish an overall winner among B/C/D, equivalence, or a reliable error rate. Some differences are verbosity and representation, not quality.

A/B/C wrap JSON answers in Markdown fences; D emits raw JSON. This is a separate integration consideration if the consuming parser requires raw JSON. No exact output schema was supplied beyond top-level names, so extra conditional/superseded sections are not penalized as schema failures.

Only the merge case uses the production prompt. Extraction and task prompts are simplified synthetic prompts, and their examples spell out the intended distinctions clearly. There are no long mailbox threads, tools, multilingual variants, repeated trials, positive merges or adversarial ambiguities. These observations can justify rejecting a blind default downgrade; they cannot certify a replacement model for production memory/task work.
