# A flat private reply decision with bounded internal explanation

## Intent and unchanged product scope

The November 23 [mailbox brief](2026-11-23-mailbox-drafts.md) and governing HB
mailbox delivery remain binding. The engine prepares one mailbox draft or
performs the authorized direct send, preserves legitimate internal review,
checks conversation/Sent/drafts before generation and never retries an
uncertain transmission. Existing IMAP/SMTP app passwords remain the transport.
This candidate changes the private model response representation, not public
MCP/RPC fields, sender authority, saved models, pricing policy or spending caps.

## Evidence and its limit

The installed nested format produces terminal reviews on the controlled Café
case, including an assessment with no substantive rationale. Diagnosis finds
the correct source and evidence in the saved request; no local forced branch
or canned response is demonstrated. The original provider-side cause is unknown.

The separately reviewed flat diagnostic completes through the actual budgeted
client in the normal service context. It returns a complete flat object with
`decision=draft`, an empty missing-facts array and a nonempty explanation of that
draft decision. An independent model review confirms that the body acknowledges
the controlled original in Italian, contains the exact reference and correct
total, follows the published signature and contains no unrelated identity or
customer material. The body is 187 UTF-8 bytes, SHA-256
`99ae8f9e0883b2ac8b5aa8b219de27f2095894cfd40e0bf14627567e3d448043`.

The diagnostic decoder requires empty `reason` for drafts and therefore records
this response as `invalid`/`unusable_output`. That result remains unchanged.
The proposed candidate gives `reason` an explicit meaning as an internal
explanation of either decision. It does not alter the observed response to make
the old test pass. There is no nested provider outcome in this experiment, so
neither format advantage nor causality is established. No installed preparation
has passed from this evidence alone.

## Proposed private contract

Use one closed top-level object with four required fields:

| Field | Meaning |
| --- | --- |
| `decision` | Exactly `draft` or `needs_review`; this field selects the outcome. |
| `body` | Plain-text outgoing content for a draft; empty for internal review. |
| `reason` | Bounded internal explanation; never appended to outgoing content. |
| `missing_facts` | Genuine missing facts for review; empty for a draft. |

Request the strict provider JSON schema on every supported route. Retain the
existing capability checks, fixed provider selection, disabled fallback and
pricing admission. Explain the field meanings in the normal generation prompt.
No JSON-object downgrade or alternate provider is introduced.

For `draft`, require a nonblank plain-text body and an empty missing-facts list.
An empty or nonempty explanation is permitted within the existing reason byte
limit. A nonempty explanation must be nonblank. Return only the body to the
existing mailbox persistence path; discard the auxiliary explanation rather
than storing or sending it as reply content.

For `needs_review`, require an empty body, the existing nonblank bounded reason
and the existing bounded genuine-facts list, including zero facts for a policy
escalation. Return the existing `ReviewRequired` result. Retain its public and
stored representation so old operations recover unchanged.

Reject unknown or duplicate fields, unknown decisions, incorrect types,
contradictory fields, malformed or incomplete output, tools and provider refusal
before mailbox effects. In particular, a draft with missing facts or a review
with outgoing body is refused. Do not classify explanation prose through
patterns, suppress review phrases, force an acknowledgment or inject a fixture
answer. The model supplies the actual body.

## Acceptance before release

- Fresh framing and execution-plan reviews precede source changes.
- Focused actual caller tests cover valid draft with empty and nonempty internal
  explanation, legitimate review, policy-only review, contradictory fields,
  malformed/duplicate/extra fields, incomplete output and refusal in both
  draft and direct-send modes. Adverse cases cause zero mailbox effects.
- A source review approves the exact candidate and unchanged recovery,
  accounting, authority and mailbox boundaries. Build one immutable artifact,
  review its fleet transaction and verify all seven actual running packages.
- Through installed public MCP, prepare the exact controlled original with
  current genuine evidence, read the mailbox body, approve its semantics and
  repeat the same request. One draft, one settled generation and unchanged
  historical identities remain required. A separately reviewed exact fixture
  renewal sends no second original message.
- Recheck installed send-path behavior on an eligible controlled source through
  the normal MrCall launcher, with exactly one received/Sent reply and no draft.
  Preserve the completed older source and all prior ordinary evidence.
- Complete current MCP/Desktop recovery, documentation criticism, separate final
  review and the ordinary public release procedure. Literal Gmail actions stay
  explicit parent acceptance; the diagnostic is not a substitute.

Old generation IDs, reviews, reservations, usage, canonical mailbox receipts,
accepted aliases and failed diagnostic intents remain intact. No migration,
database restore, saved-model change, recurring schedule resumption or broader
model-quality claim belongs to this candidate.
