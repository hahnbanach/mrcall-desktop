# Disputed case review: business truth and task decisions

Current selected-case interpretation: [complete 60-case / 240-output source review](2026-09-16-reviewed-model-comparison.md).
Unselected historical outputs and GLM are not newly regraded.

Status: disputed-case detail supporting the complete selected-case review above. This note supersedes
categorical semantic conclusions in the [reasoning study](2026-09-16-k3-reasoning-quality.md),
[earlier comparison](2026-09-15-controlled-model-quality.md) and
[intermediate correction](2026-09-16-grading-correction.md). Their numerical tables
remain historical grading snapshots, not counts of proven decision errors.
No replacement scores, equivalence claim or production recommendation follow.

## Equal criteria for Opus and K3

A supplied fact, an independently established company fact, an unsupported
explanation and a wrong task decision are different findings. Uncorroborated does
not mean false. A prior AI-written reply is not authoritative business truth.
A proposed draft is not an executed email, payment or shipment. These distinctions
apply equally to historical Opus and all K3 arms; neither model is the oracle.

Reviewers initially missed relevant learned FAQ and overriding owner instructions,
then repeated those mistakes during correction. They also read an earlier message
without adequately considering the customer's later reply. These are evaluation
errors, not merely new facts supplied after a sound initial review.

## Payment notification

The source states:

```text
Metodo di
elaborazione dei pagamenti

shopify_payments
```

Maximum K3 states:

> Payment confirmed via shopify_payments

Historical Opus explains:

> order notifications are system noise, not correspondence requiring a reply.

Both return `action_required: false` and `task_action: none`. Other K3 outputs
also choose no action. The source identifies a processor, not independently
verified settlement. Neither nonpayment nor an instruction to ship, collect money
or reply is established. K3's payment explanation is unverified; the operational
no-action decision follows the notification policy. The unrelated retrieved
prospect memory and the generic `PAGAMENTO CONFERMATO` example do not establish
this order's payment status. This is not a demonstrated financial or task failure.
The same rule applies to an unsupported paid-status claim from any other model.

## Dominique: printing and applying labels

At 10:04 on June 15, the owner offers supplier-side labels on a best-effort
schedule and alternatively proposes local application in Paris:

> avoiding any potential delays related to label production and application on our side

At 10:09, the customer changes the relevant constraints:

> We already have artwork and would prefer it to be printed on the cans before shipping, so it's less work for our team

She also asks who must add mandatory information:

> Or would our design need to update the file to include all this information?

Historical Opus proposes:

> Reply to Dominique confirming whether pre-printed/labelled cans before shipping are feasible

Maximum K3 proposes:

> Yes, if we receive the final artwork promptly we can print the labels and apply them to the cans here before shipping

It adds:

> That remains the fastest route for your July 7 deadline.

and:

> Once we have the final file we will confirm the exact shipping schedule.

Both create a high-priority reply task. Opus leaves feasibility and responsibility
for confirmation; K3 supplies conditional answers, assigns mandatory-text work to
the designer and asserts relative speed. The earlier owner statement concerned
potential delays, not a universal speed ranking after learning that artwork was
ready. The latest preference also includes reducing the customer's work.

The actual fastest route and division of artwork responsibility are not established
by this record. K3's answers are not verified, but neither is their falsity. It
does not guarantee a shipment date. **The claimed proven workflow reversal and
consequential K3 loss against Opus are withdrawn.** Factual adequacy remains
indeterminate; this does not certify the proposed draft as correct.

## SCASO: suspicious buyer versus verified fraud

At 10:29 on September 1, the earlier reply offers the wholesale portal and says:

> Je transmets donc votre demande à Ivan

At 11:42, the correspondent supplies named coffee products, including:

> Specialty Coffee: Arabica from El Salvador - VPS

The prior reply may itself be AI-generated. Its willingness to discuss payment
terms, and the correspondent's knowledge of products, do not authenticate a buyer.

Historical Opus returns no action and says:

> Nessuna azione: non rispondere, classico schema di frode B2B con pagamento differito

Maximum K3 also returns no action and says:

> Ignore the follow-up and do not open or process the attached "documents"; no task created.

Both explanations treat the inquiry as a scam and characterize the requested
coffee as outside the company's offer. Authenticity and product availability
must be checked independently; suspicion does not prove a catalogue mismatch.

Retrospective public-source research found documented historical company use of
`@scaso.fr` in a [French government recall record](https://rappel.conso.gouv.fr/document/e16b0ca9-6bdf-4d19-9bf7-36ae33de9959/Interne/ListeDesProduits).
The exact sender domain, `scaso.online`, has a secondary report of IPQS phishing
flags on [ScamAdviser](https://www.scamadviser.com/check-website/scaso.online).
That service also displays inconsistent relative-age information and a separate
safe classification; its score is not authoritative authentication evidence.
No company or authority warning specifically confirming this alias as an
impersonation was found in the bounded search. No independent human verification
of this sender was found in the reviewed business evidence.

There is concrete reason for suspicion, but neither fraud nor legitimacy is
established. Public research was not part of either model's captured input.
**The claimed proven operational error is withdrawn for both Opus and K3.**
Whether ignoring this buyer was commercially correct remains indeterminate.

A separate archived internal email on September 2, from the production account
to the founders, forwards this exact inquiry and states:

> questo è ovviamente truffa e basta, lo blocco

This corroborates the later recorded intention to block the contact. It is later
than the arrival-test cutoff and was not supplied in that test. Shared-account
provenance does not establish human rather than assistant authorship, and the
note does not prove either fraud or that blocking was executed. It further
undermines treating non-engagement as a demonstrated business-decision error.
No attachments were opened and nobody was contacted during the review.

## Later authority: cappuccino and shelf life

The CTO confirms that the standard product has 12-month ambient shelf life and
that manufacturing is cans-only cold brew, without glass. The captured learned
FAQ already supplied pasteurization and 12-month shelf life; the later confirmation
establishes ambient storage. Earlier penalties against Opus or K3 for these true
company facts were wrong. Manufacturing scope does not automatically establish
that the company cannot resell other coffee products.

A cappuccino-flavour request does not by itself establish a milk ingredient.
Later source recovery found the CTO's internal instruction at 09:09 on September
7, after the replay cutoff:

> Ragazzi, a questo dico che non facciamo cappuccino.

This exact-project instruction strongly corroborates declining the project as
an intended business decision, retrospectively. It was **not in the captured
model input**. A later sent reply calls the project milk-based, but neither reply
establishes the customer's actual ingredients. Thus the refusal has later owner
authority while an assertion about milk remains a separate factual uncertainty.
The private source audit preserves the dated original message and body hash;
generated memory is not treated as independent confirmation.

These facts do not establish every custom formulation, certification, package
format or production schedule. Further authoritative clarification must be
recorded separately from what the model actually received at inference time.

## Evidence boundary and remaining work

Private case cards and complete captured requests retain source hashes, exact
outputs and identity mappings under
`~/.local/share/mrcall/evaluations/2026-09-16-k3-reasoning/evidence-repair/`.
The Dominique and SCASO comparisons verify matching system, messages, tools,
tool choice and temperature across the historical and current requests; transport,
reasoning and serving time still differ. The source audit records URLs, retrieval
date, short excerpts and limitations. This note publishes only the narrow excerpts
needed to explain the disputed judgments, without contact addresses or order data.

Raw responses, numeric snapshot tables, accounting, token counts and parser
observations are unchanged. The linked selected-case review covers all 240 selected outputs; the entire
earlier 360-output study is not newly regraded. Neither the old semantic totals
nor their intermediate revisions support categorical model rankings or counts
of proven business-decision errors. Withdrawing these
examples does not imply that every output is correct.
