# Reconstructing management accounts

Use this workflow when accounting ledgers are unavailable or incomplete, or when independently comparing underlying records with an accountant's statements. Adapt it to the entity, reporting basis, jurisdiction, and available evidence. Bank services such as Qonto and commerce platforms such as Shopify are examples of sources, not requirements.

## Scope and source coverage

Establish the reporting period, timezone, currency, legal entity, account scope, and exact extraction cutoff. Distinguish the date of an invoice, delivery or service, payment, and bank settlement. For YTD comparisons, use corresponding cutoffs and consistent recognition policies; label a reconstructed historical comparison as a proxy if historical statuses are unavailable.

Inventory available sources: issued and supplier invoices, credit notes, bank accounts, processor records, online orders, foreign invoices received by email, payroll, asset schedules, financing agreements, prior statements, and opening balances. Discover authorized access in the current environment rather than assuming a particular connector exists. Do not expand access to other entities or mailboxes to improve completeness.

For API exports, retain pagination and date-window coverage, status filters, account identifiers, extraction times, counts, and totals. Check boundary dates and timezone conversions. Pending, declined, and completed transactions need distinct treatment. Do not combine overlapping exports without deduplication. A missing interval is a coverage problem to investigate, not evidence of zero activity.

Keep original documents and a source manifest where storage is authorized. Preserve stable source IDs and hashes; redact secrets and expiring signed URLs. Every material calculation or correction should point to a document, transaction, or explicit assumption.

## Material quantity coverage

Build a source-linked coverage register for material quantities requested or needed for the stated analysis. For each quantity record its meaning, evidence IDs, period/currency, calculation artifact, result or unknown status, and material exclusions. Match the categories to the actual request and available evidence; do not force invoice tax or gross categories onto an unrelated ledger report.

When invoice evidence supplies net, VAT or sales tax, and gross amounts, calculate and present signed issued-document totals, supplier-document totals and their respective net, tax and gross differences as distinct quantities. Use the existing bounded calculation operations and retain their inputs/results as artifacts for every reported material quantity. If a component is absent, mark it unknown or ask a material question rather than inventing it. Tax arithmetic does not establish tax payable or recoverable; net differences do not establish profit.

Keep invoice-document amounts distinct from settlement and banking coverage. Reconcile paid and unpaid items, customer receipts and supplier payments in separate calculations. An unpaid invoice remains part of the supported invoice amount even when no payment appears. Bank credits/payments retain bank or settlement labels and cannot fill an invoice-gross coverage item. Gross invoice differences do not establish actual cash flow or a bank balance; unknown opening balances and reconciliation remain visible.

Before finalizing, compare the coverage register with the request and source fields. Present every supported material quantity with its original meaning and retained calculation reference; label unsupported quantities and unresolved treatments explicitly. A mathematically correct bank subtotal does not compensate for an omitted invoice subtotal.

## Evidence and deduplication

Check the original invoice when OCR or provider metadata is implausible, inconsistent, or material. Inspect currency, taxable amount, VAT or sales tax, non-taxable charges, total, and payable balance. A second-currency equivalent printed on an invoice is not an additional cost or the invoice's original currency.

Distinguish invoices, orders, proformas, statements of account, deposits, balances, and credit notes. A statement of account is not another invoice. References to a proforma in a final invoice do not make that final invoice a proforma. Treat a document as a credit note only when its actual content supports that classification.

Deduplicate exact files by hash and economic documents by issuer, invoice number, date, and currency, then resolve revised versions by content. Distinct advance and balance invoices may both be valid; determine whether the final invoice already includes or deducts the advance before summing them. Provider fields may contain only the remaining payable amount rather than the invoice's full value.

Maintain a decision register with source ID, document identity, original amount and currency, selected treatment, period, category, matched payments, corrections, and reason for exclusion or provisional inclusion. Do not silently overwrite raw evidence with corrected values.

## Revenue and online sales

Reconcile invoiced sales and commerce orders before adding channels. Processor payouts and bank credits are collections, often net of fees and refunds; they are not additional revenue. Check refunds, cancellations, tax, shipping, fulfillment, deposits, and gift cards or other liabilities when present.

Detect overlap between an invoice and an online order using explicit order-to-invoice references or corroborating amounts, currency, timing and other supplied fields. Use customer or issuer identity only when the originals actually supply it; otherwise record that identity as unknown. An explicit document relationship can support overlap exclusion without proving a party identity. Similar amounts alone are insufficient. Separate the observed source facts and references from the deduplication conclusion, and record confirmed overlaps separately from provisional matches.

Apply the chosen recognition policy to delivery or service evidence. Deposits and unfulfilled orders may require deferral; invoice date or a paid status alone does not prove earned revenue. Where delivery evidence is absent, disclose the treatment and its effect rather than asserting certainty. Collections of prior-period receivables remain current cash receipts without becoming current revenue.

## Expenses, assets, and financing

Use invoices and service periods for expense recognition, separating recoverable tax where supported. A withholding reduces settlement to the supplier, not the underlying expense. Consider non-recoverable tax, contributions, and non-taxable charges according to the applicable treatment; the honorarium or taxable base alone may understate cost.

Match bank payments against included documents before using unmatched operating payments as a fallback. Explain whether each fallback uses documented net cost, a plausible tax allocation, or gross payment because tax evidence is missing. Avoid counting the invoice and its payment twice. An unpaid invoice can still be a current-period cost; payment of a prior-period bill does not make it a current-period cost.

Separate operating costs, capital additions, prepayments, customer advances, tax settlements, owner contributions and withdrawals, debt proceeds and repayments, and internal transfers. An installment may contain principal and interest; leave the split unresolved when supporting evidence is absent. Do not treat borrowing or shareholder financing as revenue.

For materials and production, distinguish purchases from consumption and cost of goods sold. Do not label a margin as gross profit when inventory movements or production allocation are missing. Use supported opening inventory and measured closing inventory; unknown closing stock is not a factual zero.

Capitalization requires evidence of the asset and applicable recognition criteria; label uncertain classification as provisional. Compute depreciation and amortization from available schedules and in-service dates. A prorated prior-year charge can be a disclosed scenario, not a validated current-year charge.

Use explicit assumptions for material recurring costs when useful to the requested approximation. State the covered interval, calculation, evidence, uncertainty, and effect if the assumption is removed. Keep estimates separate from documented amounts. Isolate personal or unrelated-entity expenses and mixed-period documents rather than automatically charging them to the current entity and period.

## Reconciliation and limits

For each bank account, check opening balance plus included signed movements equals closing balance. Verify running balances when supplied. Reconcile aggregate cash across accounts and eliminate internal transfers from consolidated cash flows. Treat physical cash as absent only when evidence or the operator supports that assumption.

Build receivable and payable roll-forwards from supported opening balances, invoices, credits, and settlements when possible. Current provider statuses are useful evidence, but a list of unpaid invoices is not automatically a complete control account. Keep unresolved differences visible; do not invent a liability or equity entry to force agreement.

Compare the independent reconstruction with the accountant's reported lines using a bridge for channel coverage, duplication, timing, tax treatment, inventory, capitalization, depreciation, financing, and other material differences. Agreement on revenue does not validate independently missing costs or net profit. Preserve version and date differences between official documents rather than silently choosing one.

If inventory, depreciation, interest, or tax remains unquantified, name the subtotal precisely, for example “provisional operating result before inventory movements and depreciation.” Leave statutory net income unavailable. Provide a partial balance sheet if opening balances or equity are incomplete; do not manufacture totals. A bank movement summary can use direct cash categories even when an indirect cash flow statement cannot be supported.

## Deliverables and checks

Produce a concise report and calculation register, with a numeric spreadsheet or machine-readable tables when useful. Include source coverage, excluded items, material corrections, estimates, unresolved amounts, and sensitivity to major assumptions. Separate observed facts, estimated amounts, and scenarios.

Retain reproducible calculations that work from saved inputs without credentials or fresh network calls where practical. Check arithmetic, duplicate decisions, source totals, bank reconciliation, and material document corrections. Validate representative material figures against originals, not merely against the same transformed table that produced the report.

Store company evidence and results in the project's authorized records, never in this reusable skill. When saving to a shared project or external store is authorized, read back the saved files or compare manifests and hashes. Report the actual cutoff and practical limitations alongside the result.
