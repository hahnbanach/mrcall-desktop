# Correction: business truth, input support and task decisions

Current selected-case interpretation: [complete 60-case / 240-output source review](2026-09-16-reviewed-model-comparison.md).
Historical tables in the linked original reports remain unchanged. Unselected
historical outputs and GLM are not newly regraded.

Status: this intermediate correction is superseded by the
[disputed-case review](2026-09-16-disputed-case-review.md). Its previous claims of
two proven arrival errors and one paired loss are withdrawn. The linked selected
review covers all 180 reasoning outputs and 60 matching historical Opus outputs.
The entire earlier 360-output study is not newly regraded.

The failure examples and model-selection recommendation published with the
[reasoning comparison](2026-09-16-k3-reasoning-quality.md) were overstated. Two
claimed inventions are correct company facts confirmed by the CTO, and the
payment example does not show a different or incorrect operational decision.
Review also found instructions already supplied to the models that the graders
had overlooked or interpreted too restrictively. The correction applies to all
three arms and the [earlier model comparison](2026-09-15-controlled-model-quality.md).

## What was wrong

1. **Ambient shelf life.** Café124's standard product has a 12-month ambient shelf
   life. The captured learned FAQ already states pasteurization and 12-month
   shelf life; the CTO confirms ambient storage. Calling the model's statement
   an invented company capability was wrong. This confirmation does not establish
   every custom formulation, nitro process or certification.
2. **Packaging and scope.** Cans-only cold-brew production and no glass are true
   company facts. A reply stating that scope is not a fabricated limitation.
   Known product scope and the validity of a particular recipe remain separate.
3. **Payment.** In the private order case `t-6f4f1b16445f-task`, the source says
   the field `Metodo di` / `elaborazione dei pagamenti`, followed by
   a blank line and `shopify_payments`. Maximum K3 adds
   `Payment confirmed via shopify_payments`. The source does not establish
   completed payment, but it also does not establish nonpayment. Both variants
   correctly choose `action_required: false`, `task_action: none`. Neither asks
   to ship, collect money or reply. The explanation is unverified; no operational
   failure or financial loss is demonstrated.
4. **Existing FAQ and instruction precedence.** The model's Ethiopia/white-label
   versus other-coffee/private-label distinction follows its supplied FAQ. The
   FAQ's association of 200ml and 250ml with different offers does not establish
   an exclusive prohibition, especially given overriding owner notes listing
   250ml and 200ml products. A missing catalog confirmation is uncertainty, not
   proof that a format or recipe is unavailable.

The initial grading conflated absence of corroboration with factual falsity and,
in some cases, an explanatory overstatement with a wrong business action.
Additional agent review and passing code tests did not prevent these mistakes.
This is a grading defect, not evidence that the models changed their answers.

## What the models actually received

The 20 arrival replays were deliberately cold-start: no retrieved company-memory
snippets, existing tasks or calendar context. They still received the complete
saved trained task prompt and standing owner instructions, including learned
product facts. All 40 heldout task requests in the earlier experiment included
retrieved company-memory snippets; some also included existing task context.

For the payment case, the retrieved memory concerns an unrelated prospect's
bounced outreach email. It provides no order-payment evidence. The system's
example category `PAGAMENTO CONFERMATO` is not a status for this specific order.
The full private case record retains source mail/date/order details and exact
outputs, so the finding can be reviewed without reconstructing a vague summary.

The correct statement is therefore neither "the model could not know this" nor
"it must have read it from the blobs." Information supplied in learned policies,
retrieved snippets and new CTO evidence is identified separately. A cold-start
replay does not measure the complete live memory-enabled product.

## Revised labels and interpretation

Corrections preserve the original labels, frozen inputs and raw outputs. There
were no new model calls. All affected arms/models receive the same treatment:

- CTO-confirmed company facts no longer carry false-fact penalties.
- Conclusions supported by the full supplied FAQ are evaluated against that FAQ.
- Unsupported but uncontradicted business claims remain explicitly uncertain.
- Correct no-action decisions with uncertain payment/shipment explanations are
  distinguished from wrong task decisions. Their whole-response grade is
  indeterminate, with source-grounding concerns retained separately.
- Explicit policy violations, missed pending actions, source-contradicted
  workflow instructions and independent output-contract failures remain findings.
  Durable memory extraction has a separate requirement to ground stored facts.

The intermediate numerical revision is retained in the reports' archived tables,
not asserted here as a validated count of business errors. Subsequent full-thread
review withdraws the claimed SCASO and label-route operational failures, and the
one-loss conclusion derived from the latter. Costs, token counts, parser outcomes
and tool-call coverage are unchanged. No replacement semantic scores are claimed.

The original categorical quality recommendation is withdrawn. No model is
promoted or rejected solely on the repaired scores. Independent confirmation
requires a company-validated reference for product scope, format availability,
prices and workflow, explicit policy precedence, and representative retrieval.
The present outputs can help repair that evaluation; they cannot serve as a
fresh confirmation of the grading rules developed after inspecting them.

## Evidence and verification

The private evidence roots retain original/revised grades and sequential
adjudications under `cto-correction-20260916/`. Earlier targeted audits scanned all 180 new and 360 earlier main grades for
specific affected criteria. That is not an exhaustive full-input business-truth
regrading of every response; subsequent case review exposed further mistakes. The optional
older candidate/repetition judgments remain exploratory historical evidence.

Independent arithmetic review reproduces revised main tables and paired
comparisons directly from canonical grades. Private case records preserve input
hashes, exact outputs, source-grounding concerns and unknown business facts.
Original statements in the conversation transcript remain append-only, followed
by corrections; they are not silently rewritten.
