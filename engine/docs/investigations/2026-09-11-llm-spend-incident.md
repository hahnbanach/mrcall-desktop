# Overnight LLM spend: production evidence

Read-only investigation on 2026-09-11. Times are UTC. Account A and B below
are the two newly connected company mailboxes identified by the operator.
Customer addresses, identifiers, message contents, capability keys, and credentials
are deliberately excluded from this source-repository report.

## Finding

The incident was caused primarily by excessive identity-comparison calls during
initial mailbox memory extraction, using the configured `claude-opus-5` through
direct Anthropic credentials. It was not primarily repeated mailbox downloads,
CAS retries, or the periodic duplicate sweep.

The engine already had a configured $5 daily limit for both affected profiles.
The deployed guard checked spending once before starting the pipeline, rather
than before every provider request. A long initial backlog could therefore run
past the limit until the entire stage completed. Interactive calls also explicitly
bypassed that guard. These are enforcement defects, not missing user configuration.

## Recorded successful calls

The profile SQLite `llm_usage` ledgers contain:

| Evidence | Account A | Account B |
|---|---:|---:|
| First imported email row | Sep 9 11:11:59 | Sep 9 11:03:26 |
| Emails imported on Sep 9 | 741 | 2,240 |
| First successful LLM call | Sep 9 14:28:20 | Sep 9 14:37:58 |
| Last successful call in incident | Sep 10 09:14:34 | Sep 10 09:14:34 |
| Successful calls | 28,401 | 30,785 |
| Ledger estimated USD | 152.47525125 | 132.199546 |
| `memory.extract` calls | 710 | 283 |
| `memory.extract` estimated USD | 28.19393925 | 10.31058 |
| `memory.merge` calls | 27,680 | 30,493 |
| `memory.merge` estimated USD | 123.929485 | 121.679814 |

All these calls record transport `direct` and model `claude-opus-5`.
The combined estimate is $284.67479725, with approximately 86.3% attributed to
`memory.merge`. These are the engine's historical estimates, **not provider
invoice reconciliation**. They use the engine's then-current price table and
only successfully recorded responses; they cannot establish the exact charged
amount or credit top-up transactions reported by the operator.

The newly imported rows and first-use ledger dates support the initial-backlog
hypothesis. The incident spans about 19 hours, including the night of Sep 9–10;
it should not be described as a $200 invoice proven by these tables.

## Why the merge stage multiplied calls

At the incident source revision, `MemoryWorker.process_email` passes the email
sender into every entity upsert. `_upsert_entity` appends this source identifier
even when an extracted entity already identifies somebody else. The identifier
index then returns every blob sharing **any** identifier. The identifier-derived
candidate list is unbounded; the separate cosine search's `limit=3` does not
limit it. The merge model correctly refuses most unrelated candidate pairs,
but every refusal is a paid request.

Aggregated production file logs, without exposing message or entity content:

| Evidence | Account A | Account B |
|---|---:|---:|
| Identifier-only merge attempts | 26,956 | 30,189 |
| Identifier plus cosine attempts | 644 | 274 |
| Cosine-only attempts | 90 | 35 |
| Identifier lookups with hits | 965 | 459 |
| Mean identifier candidate count | 49.25 | 90.95 |
| Maximum identifier candidate count | 261 | 237 |
| Source identifier injections logged | 724 | 437 |
| `INSERT` merge refusals logged | 26,976 | 30,198 |
| Accepted `MERGE` results logged | 709 | 299 |
| CAS conflict retry messages | 0 | 1 |
| Unique email processing IDs | 745 | 2,243 |
| Total email processing attempts | 751 | 2,246 |

Decision-log counts include canaries and can differ slightly from ledger rows
because these are separate observations. They demonstrate high refusal rates
and negligible email replay/CAS contribution, without claiming one-to-one
transactional equivalence. The live shared identifier index independently has
one email identifier attached to 242 distinct blobs (778 blobs total at audit).

The source identifier injection was introduced by `ebb1c7f` (2026-07-31).
Shared company memory later made candidate identity quality even more important.
The observed data establishes amplification from identifier candidates; it does
not require claiming that every high-fanout identifier is erroneous.

## A second defect: failed extraction marked complete

`_extract_entities` catches most provider errors and returns an empty list.
`process_email` treats an empty list as a successful semantic “nothing to store”
result and marks the message processed. Insufficient credit is not one of the
few exceptions rethrown by the old implementation.

Logs identify 1,962 unique message processing IDs with extraction errors for
Account B and 40 for Account A. Most Account B errors occurred after the first
credit-low response at Sep 10 09:14:34; processing continued until 09:25:18.
A follow-up correlation of each error to the following explicit empty-extraction
log and a read-only checkpoint query found all 1,962 / 40 IDs still marked memory
processed. Of those, 1,612 / 40 also had task checkpoints. These remain recovery
candidates: validate successful later processing before any repair, and do not
reset the independent task checkpoint automatically. This investigation made no checkpoint changes or paid replay calls.

## Other active exposure at discovery

All seven hosted profile services were active. A third company profile still
made successful direct Opus calls on Sep 11 and had already exceeded its own
configured $5 limit. The two new profiles had no successful calls on Sep 11;
they repeatedly received insufficient-credit responses. The engine auto-update
loop was enabled, at five-minute intervals. A daemon restart alone would resume
that loop, so it is not a spending pause.

The investigator reported the exact four company units to the main operator
for reversible containment. This document records discovery, not a claim that
containment or the implementation fixes were performed by this investigation.

## Required corrective behavior

1. Enforce account spending before **every** provider request with atomic
   reservation and settlement, including concurrent calls and interactive RPCs.
   Fail closed when metering cannot establish remaining budget.
2. Preserve the configured $5 limits. Clearly distinguish an estimate-based
   engine guard from provider-level payment authorization.
3. Stop attaching a message sender's identity to every unrelated extracted
   entity. Bound and rank comparison candidates; retain LLM semantic judgment.
4. Rebuild only invalid identifier associations with an auditable recovery
   procedure; a code fix alone does not remove already polluted index entries.
5. Propagate extraction/provider failure without marking a message successfully
   processed. Recover only verified failed checkpoints after containment.
6. Select cheaper validated models explicitly for repetitive semantic work;
   prevent accidental inheritance of the account's most expensive default.

## Reproducibility and limits

Sources: read-only SQLite queries of `llm_usage` and aggregate email timestamps,
allowlisted profile settings, `systemctl show/is-active`, aggregate extraction
of rotated profile `zylch.log*`, and deployed-source control flow. Databases were
opened read-only under the owning service user. No session transcripts, paid
LLM calls, email contents, outbound messages, or provider invoices were used.

Relevant source entry points: `zylch/services/process_pipeline.py`,
`zylch/llm/usage.py`, `zylch/workers/memory.py`, and
`zylch/rpc/server_ws.py`. The findings describe the pre-fix implementation;
subsequent remediation should be tracked by the development execution plan.
