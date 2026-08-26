"""Does this message need a reply from us? — the engine's judgement, per message.

WHY THIS EXISTS. A customer whose problem we already solved writes back "Va
bene, la ringrazio tanto". Nothing is owed. Every consumer of the mailbox still
showed that thread as something to look at, because the only question anyone
could answer deterministically was *"is there a message from us after theirs"*,
and the answer is no. So a queue of eleven real jobs arrived with twenty-two
closing courtesies stapled to it, and a list an operator must eyeball in full is
a list he stops eyeballing.

Nothing else in the engine answers this. `auto_reply_detector` answers a
different and narrower question — *was this written by a machine* — from RFC-3834
headers and two body sentinels for our own templates. A human being polite has no
headers. The task ledger cannot answer it either: absence of a task means "not
analysed", not "resolved" (measured — one open task overlapped a fifteen-row
queue). This module is the missing judgement, and it lives here because the
engine owns the mail and its classification; a consumer that re-derived it would
be a second source of truth that drifts from this one.

THE ASYMMETRY IS THE WHOLE DESIGN, AND IT IS DELIBERATE. The two errors are not
comparable:

  * calling a real request "no reply needed" SILENCES a customer. Nothing
    downstream catches it — the row simply stops being shown, and the only
    person who would notice is the customer who never heard back. Unrecoverable.
  * calling a thank-you "needs a reply" costs one line on a list and one glance.

So every ambiguity, every parse failure, every missing verdict, every exception,
every message we cannot fully see resolves to NEEDS A REPLY. There is no code
path in this module on which an error produces silence. Read that as a rule
rather than as caution: a future edit that adds an early `return
Verdict(needs_reply=False, …)` on a failure branch is a bug even if the tests
pass, because the tests cannot fail for a customer nobody answered.

TWO STAGES, AND THE FIRST ONE CAN ONLY SAY YES.

`screen()` is deterministic, offline and free. It looks only at structure —
never at what the message means — and it can return exactly one thing: NEEDS A
REPLY, with a reason. When it has nothing to say it returns None, which means
"courtesy-SHAPED, ask the adjudicator", never "no reply needed". That inversion
is what keeps the cheap layer safe: no arrangement of its rules can silence
anybody, so it can be tuned freely.

`adjudicate()` is one batched LLM call over the residue. It is where the actual
judgement happens, and it is an LLM on purpose:

  * The judgement is semantic and multilingual. These customers write Italian,
    Spanish, French and English, and "mandami il contratto" is five words with no
    question mark — structurally identical to "grazie mille", semantically its
    opposite. No deterministic rule separates those two without a per-language
    lexicon, and a lexicon has only bad failure modes: as a deny-list it
    misfires on "grazie, ma il problema persiste"; as an allow-list it is either
    too narrow to help or wide enough to swallow a request. An unlisted language
    would get a confident wrong answer from either.
  * Determinism is preserved where determinism matters. Discovery — *which*
    conversations exist and whether anybody wrote back — stays header-derived and
    reproducible. The model only re-LABELS a message already found, it never
    enumerates, and both labels stay visible to the operator. Temperature is 0.
  * Spend is bounded before the call, not after: the screen removes everything
    long, attached, questioned or unanswered, and what is left is a handful of
    two-line messages in one request.

The LLM path fails to NEEDS A REPLY, always and everywhere: no transport
configured, spend cap reached, HTTP 400 handed back as a response, provider
overloaded, malformed tool input, a verdict missing for one of the messages we
asked about. This is not hypothetical — the engine's own LLM spend cap has
returned a 400 *as the chat response* before, and a classifier that read that as
"nothing to do here" would have quietly emptied the queue.

WHAT THIS MODULE NEVER DOES: delete, hide, archive, close or otherwise dispose
of anything. It returns a verdict and a reason. Every consumer is expected to
keep showing the message — in its own section, with the reason — the same way an
out-of-band `handled` record is shown rather than applied silently, and a NEW
inbound message is simply a new message, judged on its own and never covered by
the verdict on the previous one.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)

#: Visible body length, in characters, above which we refuse to judge and say a
#: reply is needed. A closing courtesy plus a corporate signature block fits
#: comfortably (the longest real one measured was 182 characters); beyond this
#: the message is prose, and prose gets read by a person. It is a narrowness
#: rule first and a spend bound second.
MAX_COURTESY_CHARS = 600

#: How many messages one adjudication request may carry. Past this the batch is
#: split, so a big sweep cannot build a single unbounded prompt.
MAX_BATCH = 40

#: Question marks across the scripts our customers actually write in. A question
#: is a request by definition, so this is a pure early-out — it can only ever add
#: rows to the queue. The Greek question mark (U+037E, which looks like a
#: semicolon) is deliberately absent: ordinary Latin punctuation would trip it on
#: every second message, and the adjudicator handles Greek meaning anyway.
_QUESTION_MARKS = ("?", "？", "¿", "؟")

#: Anything that reads as a link. A link is a new thing for somebody to look at,
#: which is a new request however politely it is phrased.
_URL_RE = re.compile(r"(https?://|www\.)", re.IGNORECASE)

#: The "> On <date> <person> wrote:" attribution some clients wrap across two or
#: three lines, which `strip_quoted` (single-line patterns) leaves behind. Only
#: the trailing verb is matched, in the handful of languages whose spelling we
#: have actually seen, because a miss here is harmless: the quoted trailer is
#: then counted as body, the message reads as long, and it needs a reply. This
#: list is a length heuristic, never a semantic one — nothing in this module
#: decides meaning from a word list.
_REPLY_INTRO_RE = re.compile(
    r"(wrote|ha scritto|scrisse|escribi\w*|a écrit|schrieb|escreveu|napisał\w*)\s*:\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Verdict:
    """One message's answer, plus why and who decided it.

    `reason` is a stable short code (see the `R_` constants) so a consumer can
    render it in its own language without parsing prose. `decided_by` separates
    "the model looked at this" from "we could not ask, so we said yes", which is
    the difference an operator needs when a row he expected to be quiet is loud.
    """

    needs_reply: bool
    reason: str
    decided_by: str  # "screen" | "llm" | "degraded"


# Reason codes. Every one of them except CLOSING_COURTESY means "needs a reply".
R_NO_PRIOR_ANSWER = "no_prior_answer"
R_ATTACHMENT = "attachment"
R_EMPTY_BODY = "empty_body"
R_TOO_LONG = "too_long"
R_QUESTION = "question_mark"
R_LINK = "link"
R_FROM_US = "outbound"
R_AUTOMATIC = "automatic"
R_LLM_ASK = "llm_says_reply"
R_COURTESY = "closing_courtesy"
R_NO_LLM = "no_llm_transport"
R_LLM_FAILED = "llm_call_failed"
R_LLM_INCOMPLETE = "llm_verdict_missing"


def visible_text(body: str) -> str:
    """The part of `body` the sender actually typed, best effort.

    `strip_quoted` has already removed `>` lines and cut at the single-line
    attribution markers by the time a body reaches us; this additionally drops
    the wrapped "Il giorno … ha scritto:" form some clients emit, which would
    otherwise make a two-word thank-you look like a three-hundred-character mail.
    Signatures are NOT stripped: no rule separates a signature from a postscript,
    and a wrongly-stripped postscript is a lost request. They are left in, they
    count towards the length bound, and the adjudicator is told to ignore them.
    """
    if not body:
        return ""
    lines = body.splitlines()
    for i, line in enumerate(lines):
        window = " ".join(x.strip() for x in lines[i : i + 3]).strip()
        if _REPLY_INTRO_RE.search(line.strip()) or _REPLY_INTRO_RE.search(window):
            lines = lines[:i]
            break
    return "\n".join(lines).strip()


def screen(
    message: Dict[str, Any],
    answered_before: bool,
) -> Optional[Verdict]:
    """Structure-only pre-pass. `Verdict(needs_reply=True, …)` or None.

    None means "this is courtesy-SHAPED — ask the adjudicator". It never means
    "no reply needed": this function has no branch that can return
    `needs_reply=False`, which is what makes it safe to extend.

    `answered_before` is the thread precondition: a real message of OURS, not an
    autoresponder, earlier in this conversation. Without it there is no completed
    exchange to close, so even a bare "ok" is somebody acknowledging a request
    that nobody has answered — that is the queue, not a courtesy.
    """
    if message.get("is_user_sent"):
        # Ours. Not a question about whether WE owe an answer at all; callers
        # should not pass these, and a caller that does gets a loud, safe answer.
        return Verdict(True, R_FROM_US, "screen")
    if message.get("is_auto_reply"):
        # Already the engine's own, older judgement — a different question, with
        # its own consumer. Not this module's to re-answer or to override.
        return Verdict(True, R_AUTOMATIC, "screen")
    if not answered_before:
        return Verdict(True, R_NO_PRIOR_ANSWER, "screen")
    if message.get("has_attachments") or message.get("attachment_filenames"):
        return Verdict(True, R_ATTACHMENT, "screen")
    text = visible_text(message.get("body_plain") or "")
    if not text:
        # We cannot see what they wrote — an HTML-only mail, a body that failed
        # to sync, a message that is nothing but a quoted trailer. Never silence
        # what you could not read.
        return Verdict(True, R_EMPTY_BODY, "screen")
    if len(text) > MAX_COURTESY_CHARS:
        return Verdict(True, R_TOO_LONG, "screen")
    if any(q in text for q in _QUESTION_MARKS):
        return Verdict(True, R_QUESTION, "screen")
    if _URL_RE.search(text):
        return Verdict(True, R_LINK, "screen")
    return None


REPLY_NEED_TOOL = {
    "name": "reply_need_decision",
    "description": (
        "Report, for every message you were given, whether our side still owes "
        "a reply. Emit exactly one verdict per index, and never omit an index."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "verdicts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "index": {
                            "type": "integer",
                            "description": "The index printed with the message.",
                        },
                        "needs_reply": {
                            "type": "boolean",
                            "description": (
                                "true when the message asks for anything, "
                                "reports anything, or leaves anything open; "
                                "false ONLY for a pure closing courtesy."
                            ),
                        },
                        "reason": {
                            "type": "string",
                            "description": "A few words, in English, saying why.",
                        },
                    },
                    "required": ["index", "needs_reply"],
                },
            }
        },
        "required": ["verdicts"],
    },
}

_SYSTEM = (
    "You decide whether a customer-service mailbox still owes a reply to a "
    "message. Every message you are given arrives on a thread where our side "
    "has ALREADY answered — the customer has written back after our answer.\n"
    "\n"
    "Answer needs_reply = false ONLY when the message is a pure closing "
    "courtesy: it thanks us, acknowledges, agrees, confirms receipt, or says "
    "goodbye, and it asks for nothing, reports nothing, and leaves nothing "
    "open. Everything else is needs_reply = true, including: any question; any "
    "request or instruction, however short or polite; a problem that is still "
    "not solved; dissatisfaction or complaint; a date, time or appointment we "
    "would have to act on or confirm; new facts or corrections we would have to "
    "process; a promise that we will hear more, where the ball is with us.\n"
    "\n"
    "Messages arrive in many languages. Judge what the message MEANS, never "
    "which words it contains: politeness words can wrap a request, and a bare "
    "'ok' can be a complete close. Ignore signature blocks, job titles, "
    "addresses, phone numbers, legal footers and privacy disclaimers — they are "
    "not content and they never make a message need a reply.\n"
    "\n"
    "The two mistakes are not equal. Marking a real request as needing no reply "
    "silences a customer and nobody downstream will catch it. Marking a "
    "thank-you as needing a reply costs one line on a list. When you hesitate, "
    "even slightly, answer needs_reply = true.\n"
    "\n"
    "Emit the reply_need_decision tool call exactly once, with one verdict per "
    "index you were given."
)


def _render(messages: Sequence[Dict[str, Any]]) -> str:
    """The user turn: one numbered block per message, subject + visible body."""
    blocks: List[str] = []
    for i, m in enumerate(messages):
        subject = (m.get("subject") or "").strip() or "(no subject)"
        text = visible_text(m.get("body_plain") or "")
        blocks.append(f"--- MESSAGE {i} ---\nSubject: {subject}\nBody:\n{text}")
    return (
        "Decide needs_reply for each message below.\n\n"
        + "\n\n".join(blocks)
        + "\n\nEmit reply_need_decision with one verdict per index 0.."
        + str(len(messages) - 1)
        + "."
    )


async def adjudicate(messages: Sequence[Dict[str, Any]]) -> List[Verdict]:
    """One verdict per message, in the same order. Never raises.

    Batched: the whole residue goes in one request, because the per-message
    judgement needs no per-message context beyond the message itself, and N
    round trips would put an LLM call on a loop that used to be a SQLite read.

    Every failure mode lands on `needs_reply=True`:
      * no LLM transport configured at all;
      * the call raising — including the spend cap, which has surfaced as an
        HTTP 400 handed back where a response was expected;
      * no tool_use block in the answer;
      * a verdict missing, duplicated or not a boolean for some index.
    """
    if not messages:
        return []
    if len(messages) > MAX_BATCH:
        out: List[Verdict] = []
        for i in range(0, len(messages), MAX_BATCH):
            out.extend(await adjudicate(messages[i : i + MAX_BATCH]))
        return out

    from zylch.llm import routed_model, try_make_llm_client
    from zylch.llm.usage import call_site

    client = try_make_llm_client(model=routed_model("MODEL_REPLY_NEED"))
    if client is None:
        logger.warning(
            "[reply-need] no LLM transport configured — %d message(s) reported "
            "as needing a reply",
            len(messages),
        )
        return [Verdict(True, R_NO_LLM, "degraded") for _ in messages]

    system = [
        {
            "type": "text",
            "text": _SYSTEM,
            "cache_control": {"type": "ephemeral"},
        }
    ]
    try:
        with call_site("reply-need"):
            resp = await client.create_message(
                system=system,
                messages=[{"role": "user", "content": _render(messages)}],
                max_tokens=2000,
                temperature=0,
                tools=[REPLY_NEED_TOOL],
                tool_choice={"type": "tool", "name": "reply_need_decision"},
            )
    except Exception as e:  # noqa: BLE001 — degradation is the contract
        logger.warning(
            "[reply-need] LLM call failed (%s: %s) — %d message(s) reported as "
            "needing a reply",
            type(e).__name__,
            e,
            len(messages),
        )
        return [Verdict(True, R_LLM_FAILED, "degraded") for _ in messages]

    raw: Dict[str, Any] = {}
    for block in resp.content:
        if (
            getattr(block, "type", None) == "tool_use"
            and getattr(block, "name", None) == "reply_need_decision"
        ):
            raw = dict(block.input or {})
            break

    by_index: Dict[int, Verdict] = {}
    for item in raw.get("verdicts") or []:
        if not isinstance(item, dict):
            continue
        idx = item.get("index")
        needs = item.get("needs_reply")
        if not isinstance(idx, int) or not isinstance(needs, bool):
            # A string "false" is not a verdict. Anything we cannot read as a
            # boolean is dropped here and picked up by the missing-index rule
            # below, which says a reply is needed.
            continue
        if idx in by_index:
            continue  # first verdict wins; a duplicate index is not a signal
        reason = str(item.get("reason") or "").strip()
        by_index[idx] = Verdict(
            bool(needs),
            (R_LLM_ASK if needs else R_COURTESY) + (f": {reason}" if reason else ""),
            "llm",
        )

    out = []
    for i in range(len(messages)):
        v = by_index.get(i)
        if v is None:
            logger.warning("[reply-need] no verdict for index %d — reporting as open", i)
            v = Verdict(True, R_LLM_INCOMPLETE, "degraded")
        out.append(v)
    return out


async def classify(
    candidates: Sequence[Dict[str, Any]],
) -> List[Verdict]:
    """`screen()` everything, then adjudicate only what survives. Never raises.

    Each candidate is a message dict (as `emails.list_by_thread` renders one)
    carrying an extra `answered_before: bool` — whether a real, non-automatic
    message of ours precedes it in its conversation.
    """
    verdicts: List[Optional[Verdict]] = []
    residue: List[Dict[str, Any]] = []
    residue_at: List[int] = []
    for i, m in enumerate(candidates):
        v = screen(m, bool(m.get("answered_before")))
        verdicts.append(v)
        if v is None:
            residue.append(m)
            residue_at.append(i)
    if residue:
        for pos, v in zip(residue_at, await adjudicate(residue)):
            verdicts[pos] = v
    # No `None` can survive: `screen` returned one only where `adjudicate` has
    # now filled it, and `adjudicate` returns exactly one verdict per input.
    return [v if v is not None else Verdict(True, R_LLM_INCOMPLETE, "degraded") for v in verdicts]
