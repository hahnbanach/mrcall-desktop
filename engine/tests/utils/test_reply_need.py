"""What `zylch.utils.reply_need` may and may not say.

The tests are written around ONE property: no failure, no ambiguity and no
structural doubt may ever produce "no reply needed". Nearly every case below is
a way of breaking the classifier and checking that it breaks LOUD — because the
quiet failure is a customer who never hears back, and nothing downstream would
report it.

The real closing courtesies used as fixtures are the shapes measured on the
live queue this module was built for (a bare "ok", a thank-you with a clinic
signature under it, a reply whose client wrapped its "Il giorno … ha scritto:"
attribution across two lines).
"""

import pytest

from zylch.utils import reply_need
from zylch.utils.reply_need import Verdict, screen, visible_text


def _msg(body="ok", **over):
    m = {
        "body_plain": body,
        "subject": "Re: something",
        "is_user_sent": False,
        "is_auto_reply": False,
        "has_attachments": False,
        "attachment_filenames": [],
    }
    m.update(over)
    return m


# ─── the screen can only ever say "needs a reply" ─────────────────────


def test_screen_never_returns_a_no_reply_verdict():
    """Structural exhaustion: whatever the screen answers, it is never silence.

    This is the module's central safety claim, so it is asserted over a spread
    of shapes rather than argued in a comment.
    """
    bodies = ["", "ok", "grazie mille", "x" * 5000, "come va?", "http://x.test"]
    for body in bodies:
        for answered in (True, False):
            for auto in (True, False):
                for att in (True, False):
                    v = screen(_msg(body, is_auto_reply=auto, has_attachments=att), answered)
                    assert v is None or v.needs_reply is True


def test_unanswered_thread_is_never_a_courtesy():
    """A bare 'ok' on a thread nobody of ours ever answered is the queue."""
    v = screen(_msg("ok"), answered_before=False)
    assert v == Verdict(True, reply_need.R_NO_PRIOR_ANSWER, "screen")


def test_attachment_needs_a_reply():
    v = screen(_msg("ok grazie", has_attachments=True), answered_before=True)
    assert v.needs_reply and v.reason == reply_need.R_ATTACHMENT


def test_attachment_known_only_by_filename_still_counts():
    v = screen(_msg("ok", attachment_filenames=["offerta.pdf"]), answered_before=True)
    assert v.needs_reply and v.reason == reply_need.R_ATTACHMENT


def test_body_we_cannot_read_needs_a_reply():
    """HTML-only mail, a failed body sync, a body that is nothing but a trailer."""
    v = screen(_msg(""), answered_before=True)
    assert v.needs_reply and v.reason == reply_need.R_EMPTY_BODY


def test_long_message_is_never_judged_as_a_courtesy():
    v = screen(_msg("a" * (reply_need.MAX_COURTESY_CHARS + 1)), answered_before=True)
    assert v.needs_reply and v.reason == reply_need.R_TOO_LONG


@pytest.mark.parametrize("mark", ["?", "？", "¿", "؟"])
def test_question_mark_in_any_script_needs_a_reply(mark):
    v = screen(_msg(f"grazie, tutto a posto{mark}"), answered_before=True)
    assert v.needs_reply and v.reason == reply_need.R_QUESTION


def test_latin_semicolon_is_not_treated_as_a_question():
    """U+003B is punctuation, not the Greek question mark — it must not trip."""
    assert screen(_msg("ok; grazie"), answered_before=True) is None


def test_link_needs_a_reply():
    v = screen(_msg("ok grazie, vedi www.example.test"), answered_before=True)
    assert v.needs_reply and v.reason == reply_need.R_LINK


def test_our_own_message_is_refused_rather_than_answered():
    v = screen(_msg("grazie", is_user_sent=True), answered_before=True)
    assert v.needs_reply and v.reason == reply_need.R_FROM_US


def test_engine_flagged_automatic_is_not_re_judged_here():
    v = screen(_msg("Sono fuori ufficio", is_auto_reply=True), answered_before=True)
    assert v.needs_reply and v.reason == reply_need.R_AUTOMATIC


def test_courtesy_shaped_message_is_handed_to_the_adjudicator():
    assert screen(_msg("Va bene, la ringrazio tanto"), answered_before=True) is None


# ─── visible_text ─────────────────────────────────────────────────────


def test_wrapped_reply_attribution_is_dropped():
    """The two-line "Il giorno … ha scritto:" form `strip_quoted` leaves behind."""
    body = (
        "Va bene, la ringrazio tanto\n\n"
        "Il giorno mer 26 ago 2026 alle ore 09:06 MrCall <support@example.test>\n"
        "ha scritto:\n"
        "> Buongiorno, abbiamo fatto le modifiche\n"
    )
    assert visible_text(body) == "Va bene, la ringrazio tanto"


def test_signature_is_kept_not_stripped():
    """A postscript under a signature is a request; guessing where the signature
    ends would lose it, so signatures stay in and merely count as length."""
    body = "ok grazie\n\nDott. Cinzia Camorali\nVia Emilia Ovest 73\n43126 Parma"
    assert "43126 Parma" in visible_text(body)


def test_visible_text_of_empty_body():
    assert visible_text("") == ""
    assert visible_text(None) == ""


# ─── the adjudicator degrades to "needs a reply", never to silence ────


@pytest.mark.asyncio
async def test_no_llm_transport_degrades_to_needs_reply(monkeypatch):
    import zylch.llm as llm_mod

    monkeypatch.setattr(llm_mod, "try_make_llm_client", lambda model=None: None)
    out = await reply_need.adjudicate([_msg("ok"), _msg("grazie")])
    assert [v.needs_reply for v in out] == [True, True]
    assert all(v.reason == reply_need.R_NO_LLM and v.decided_by == "degraded" for v in out)


@pytest.mark.asyncio
async def test_llm_exception_degrades_to_needs_reply(monkeypatch):
    """The spend cap has surfaced as an HTTP 400 where a response was expected."""

    class Boom:
        async def create_message(self, **kwargs):
            raise RuntimeError("400 Bad Request: daily budget exceeded")

    import zylch.llm as llm_mod

    monkeypatch.setattr(llm_mod, "try_make_llm_client", lambda model=None: Boom())
    out = await reply_need.adjudicate([_msg("ok")])
    assert out == [Verdict(True, reply_need.R_LLM_FAILED, "degraded")]


class _Block:
    def __init__(self, payload):
        self.type = "tool_use"
        self.name = "reply_need_decision"
        self.input = payload


class _Resp:
    def __init__(self, payload):
        self.content = [_Block(payload)]


def _client_returning(payload, seen=None):
    class C:
        async def create_message(self, **kwargs):
            if seen is not None:
                seen.append(kwargs)
            return _Resp(payload)

    return C()


@pytest.mark.asyncio
async def test_missing_verdict_for_an_index_degrades_that_message(monkeypatch):
    """A partial answer must not leave a message silently unclassified."""
    import zylch.llm as llm_mod

    payload = {"verdicts": [{"index": 0, "needs_reply": False, "reason": "thanks"}]}
    monkeypatch.setattr(llm_mod, "try_make_llm_client", lambda model=None: _client_returning(payload))
    out = await reply_need.adjudicate([_msg("ok"), _msg("grazie")])
    assert out[0].needs_reply is False
    assert out[1] == Verdict(True, reply_need.R_LLM_INCOMPLETE, "degraded")


@pytest.mark.asyncio
async def test_non_boolean_verdict_is_not_read_as_false(monkeypatch):
    """A string "false" is not a verdict — it must not silence anybody."""
    import zylch.llm as llm_mod

    payload = {"verdicts": [{"index": 0, "needs_reply": "false"}]}
    monkeypatch.setattr(llm_mod, "try_make_llm_client", lambda model=None: _client_returning(payload))
    out = await reply_need.adjudicate([_msg("ok")])
    assert out == [Verdict(True, reply_need.R_LLM_INCOMPLETE, "degraded")]


@pytest.mark.asyncio
async def test_answer_without_a_tool_block_degrades(monkeypatch):
    import zylch.llm as llm_mod

    class NoTool:
        async def create_message(self, **kwargs):
            class R:
                content = []

            return R()

    monkeypatch.setattr(llm_mod, "try_make_llm_client", lambda model=None: NoTool())
    out = await reply_need.adjudicate([_msg("ok")])
    assert out == [Verdict(True, reply_need.R_LLM_INCOMPLETE, "degraded")]


@pytest.mark.asyncio
async def test_courtesy_verdict_carries_the_model_reason(monkeypatch):
    import zylch.llm as llm_mod

    payload = {"verdicts": [{"index": 0, "needs_reply": False, "reason": "pure thanks"}]}
    monkeypatch.setattr(llm_mod, "try_make_llm_client", lambda model=None: _client_returning(payload))
    out = await reply_need.adjudicate([_msg("Va bene, la ringrazio tanto")])
    assert out[0].needs_reply is False
    assert out[0].decided_by == "llm"
    assert out[0].reason.startswith(reply_need.R_COURTESY)
    assert "pure thanks" in out[0].reason


@pytest.mark.asyncio
async def test_adjudication_is_one_batched_call_at_temperature_zero(monkeypatch):
    """N messages must not become N requests, and the verdict must not wander."""
    import zylch.llm as llm_mod

    seen = []
    payload = {"verdicts": [{"index": i, "needs_reply": False} for i in range(3)]}
    monkeypatch.setattr(
        llm_mod, "try_make_llm_client", lambda model=None: _client_returning(payload, seen)
    )
    await reply_need.adjudicate([_msg("ok"), _msg("grazie"), _msg("perfetto")])
    assert len(seen) == 1
    assert seen[0]["temperature"] == 0
    assert seen[0]["tool_choice"]["name"] == "reply_need_decision"


@pytest.mark.asyncio
async def test_batches_are_bounded(monkeypatch):
    """Past MAX_BATCH the request is split rather than growing without limit."""
    import zylch.llm as llm_mod

    seen = []

    class C:
        async def create_message(self, **kwargs):
            seen.append(kwargs)
            return _Resp({"verdicts": []})

    monkeypatch.setattr(llm_mod, "try_make_llm_client", lambda model=None: C())
    n = reply_need.MAX_BATCH + 1
    out = await reply_need.adjudicate([_msg("ok")] * n)
    assert len(seen) == 2
    assert len(out) == n
    assert all(v.needs_reply for v in out)  # empty verdict lists degrade


@pytest.mark.asyncio
async def test_empty_input_makes_no_call(monkeypatch):
    import zylch.llm as llm_mod

    def boom(model=None):
        raise AssertionError("no client should be built for an empty batch")

    monkeypatch.setattr(llm_mod, "try_make_llm_client", boom)
    assert await reply_need.adjudicate([]) == []


# ─── classify: screen first, model only for the residue ───────────────


@pytest.mark.asyncio
async def test_classify_only_asks_about_what_the_screen_could_not_decide(monkeypatch):
    import zylch.llm as llm_mod

    seen = []
    payload = {"verdicts": [{"index": 0, "needs_reply": False, "reason": "thanks"}]}
    monkeypatch.setattr(
        llm_mod, "try_make_llm_client", lambda model=None: _client_returning(payload, seen)
    )
    candidates = [
        _msg("Il preventivo mi arriva quando?", answered_before=True),  # question
        _msg("grazie mille", answered_before=True),  # residue
        _msg("ok", answered_before=False),  # never answered
    ]
    out = await reply_need.classify(candidates)
    assert [v.needs_reply for v in out] == [True, False, True]
    assert [v.decided_by for v in out] == ["screen", "llm", "screen"]
    # One request, carrying exactly the one message the screen could not decide.
    assert len(seen) == 1
    body = seen[0]["messages"][0]["content"]
    assert "grazie mille" in body
    assert "Il preventivo" not in body


@pytest.mark.asyncio
async def test_classify_of_an_all_screened_batch_makes_no_call(monkeypatch):
    import zylch.llm as llm_mod

    def boom(model=None):
        raise AssertionError("nothing survived the screen; no call is due")

    monkeypatch.setattr(llm_mod, "try_make_llm_client", boom)
    out = await reply_need.classify([_msg("ok", answered_before=False)])
    assert out[0].needs_reply is True
