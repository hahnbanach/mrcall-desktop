"""What `emails.needs_reply` hands the caller, and what it refuses to invent.

The handler's own job is small and entirely about picking the right message out
of a conversation: the newest one that is NOT ours, and whether a real answer of
ours precedes it. Both are preconditions for the verdict, and both fail in the
direction that keeps a customer visible — so the tests here mostly prove
absences: a thread the engine never synced is absent from the answer rather than
reported as settled, a thread of nothing but our own mail is absent too, and our
own autoresponder does not count as the answer that makes a courtesy possible.

The judgement itself is `zylch.utils.reply_need`'s and is tested there; it is
stubbed here so these stay storage-shaped rather than model-shaped.
"""

from __future__ import annotations

import asyncio

import pytest

from zylch.rpc import reply_queries
from zylch.utils.reply_need import Verdict

OWNER = "owner-uid"
US = "support@example.test"


def _notify(*_a, **_k):
    return None


class _Store:
    def __init__(self, threads):
        self._threads = threads

    def get_thread_emails(self, owner_id, thread_id):
        rows = self._threads.get(thread_id)
        if rows is None:
            return []
        if rows == "boom":
            raise RuntimeError("archive unreadable")
        # The real rows are handed out as-is, not copied, so a handler that
        # scribbled on them would be caught by `test_the_handler_writes_nothing`.
        return rows


@pytest.fixture
def wired(monkeypatch):
    """Patch the handler's three lookups; the caller supplies the threads."""
    captured = {"candidates": None}

    def _install(threads, verdicts=None, provider="imap"):
        store = _Store(threads)
        monkeypatch.setattr("zylch.storage.storage.Storage.get_instance", lambda: store)
        monkeypatch.setattr("zylch.cli.utils.get_owner_id", lambda: OWNER)
        monkeypatch.setattr("zylch.api.token_storage.get_provider", lambda _o: provider)
        monkeypatch.setattr("zylch.api.token_storage.get_email", lambda _o: US)

        async def _classify(candidates):
            captured["candidates"] = list(candidates)
            if verdicts is not None:
                return list(verdicts)
            return [Verdict(True, "stub", "screen") for _ in candidates]

        monkeypatch.setattr("zylch.utils.reply_need.classify", _classify)
        return captured

    return _install


def _call(params):
    return asyncio.run(reply_queries.emails_needs_reply(params, _notify))


def _mail(frm, date, body="ok", **over):
    row = {
        "id": f"{frm}-{date}",
        "from_email": frm,
        "date": date,
        "subject": "Re: something",
        "body_plain": body,
        "is_auto_reply": False,
        "has_attachments": False,
        "attachment_filenames": [],
    }
    row.update(over)
    return row


# ─── the shape of the request ─────────────────────────────────────────


def test_thread_ids_is_required():
    with pytest.raises(ValueError):
        _call({})


def test_thread_ids_must_be_a_list():
    with pytest.raises(ValueError):
        _call({"thread_ids": "t1"})


def test_empty_list_is_an_empty_answer_not_an_error():
    assert _call({"thread_ids": []}) == {"threads": {}, "asked": 0, "note": None}


def test_an_unbounded_batch_is_refused(wired):
    wired({})
    with pytest.raises(ValueError):
        _call({"thread_ids": [f"t{i}" for i in range(reply_queries.MAX_THREADS + 1)]})


def test_duplicate_thread_ids_are_asked_about_once(wired):
    captured = wired({"t1": [_mail(US, "2026-08-01T09:00:00"), _mail("c@x.test", "2026-08-01T10:00:00")]})
    res = _call({"thread_ids": ["t1", "t1", " t1 "]})
    assert len(captured["candidates"]) == 1
    assert list(res["threads"]) == ["t1"]


def test_a_provider_without_a_thread_reader_is_refused_loudly(wired):
    """Never answer 'nothing needs a reply' for a mailbox we cannot read."""
    wired({}, provider="google")
    with pytest.raises(ValueError):
        _call({"thread_ids": ["t1"]})


# ─── which message gets judged ────────────────────────────────────────


def test_the_newest_inbound_message_is_the_one_judged(wired):
    captured = wired(
        {
            "t1": [
                _mail("c@x.test", "2026-08-01T08:00:00", "il sistema non funziona"),
                _mail(US, "2026-08-01T09:00:00", "risolto"),
                _mail("c@x.test", "2026-08-01T10:00:00", "grazie mille"),
            ]
        }
    )
    _call({"thread_ids": ["t1"]})
    assert captured["candidates"][0]["body_plain"] == "grazie mille"
    assert captured["candidates"][0]["answered_before"] is True


def test_a_thread_we_never_answered_is_flagged_as_such(wired):
    captured = wired({"t1": [_mail("c@x.test", "2026-08-01T08:00:00", "aiuto")]})
    _call({"thread_ids": ["t1"]})
    assert captured["candidates"][0]["answered_before"] is False


def test_our_own_autoresponder_is_not_the_answer(wired):
    """Seventeen seconds after their mail, in Sent, and it answers nothing —
    the incident this whole area exists for."""
    captured = wired(
        {
            "t1": [
                _mail("c@x.test", "2026-06-15T18:06:33", "quattro domande"),
                _mail(US, "2026-06-15T18:06:50", "Auto-replay", is_auto_reply=True),
                _mail("c@x.test", "2026-06-20T10:00:00", "ok"),
            ]
        }
    )
    _call({"thread_ids": ["t1"]})
    assert captured["candidates"][0]["answered_before"] is False


def test_a_later_message_of_ours_does_not_hide_the_inbound(wired):
    """This method answers about a MESSAGE. Whether we since replied is the
    caller's question, and it is settled against Sent, not against this archive."""
    captured = wired(
        {
            "t1": [
                _mail(US, "2026-08-01T09:00:00"),
                _mail("c@x.test", "2026-08-01T10:00:00", "grazie"),
                _mail(US, "2026-08-01T11:00:00", "di nulla"),
            ]
        }
    )
    _call({"thread_ids": ["t1"]})
    assert captured["candidates"][0]["body_plain"] == "grazie"


def test_attachment_metadata_reaches_the_classifier(wired):
    captured = wired(
        {
            "t1": [
                _mail(US, "2026-08-01T09:00:00"),
                _mail(
                    "c@x.test",
                    "2026-08-01T10:00:00",
                    "ok grazie",
                    attachment_filenames=["contratto.pdf"],
                ),
            ]
        }
    )
    _call({"thread_ids": ["t1"]})
    assert captured["candidates"][0]["has_attachments"] is True


# ─── what is absent from the answer ───────────────────────────────────


def test_a_thread_the_engine_never_synced_is_absent_not_settled(wired):
    wired({"t1": [_mail(US, "2026-08-01T09:00:00"), _mail("c@x.test", "2026-08-01T10:00:00")]})
    res = _call({"thread_ids": ["t1", "unknown-thread"]})
    assert "unknown-thread" not in res["threads"]
    assert "t1" in res["threads"]


def test_a_thread_of_only_our_own_mail_is_absent(wired):
    wired({"t1": [_mail(US, "2026-08-01T09:00:00")]})
    res = _call({"thread_ids": ["t1"]})
    assert res["threads"] == {}
    assert res["asked"] == 0


def test_an_unreadable_thread_is_noted_and_does_not_sink_the_batch(wired):
    wired(
        {
            "bad": "boom",
            "t1": [_mail(US, "2026-08-01T09:00:00"), _mail("c@x.test", "2026-08-01T10:00:00")],
        }
    )
    res = _call({"thread_ids": ["bad", "t1"]})
    assert "t1" in res["threads"]
    assert res["note"] and "unreadable" in res["note"]


# ─── what the answer carries ──────────────────────────────────────────


def test_the_verdict_and_its_reason_are_returned_per_thread(wired):
    wired(
        {"t1": [_mail(US, "2026-08-01T09:00:00"), _mail("c@x.test", "2026-08-01T10:00:00", "grazie")]},
        verdicts=[Verdict(False, "closing_courtesy: pure thanks", "llm")],
    )
    res = _call({"thread_ids": ["t1"]})
    row = res["threads"]["t1"]
    assert row["needs_reply"] is False
    assert row["reason"] == "closing_courtesy: pure thanks"
    assert row["decided_by"] == "llm"
    assert row["from_email"] == "c@x.test"
    assert row["date"] == "2026-08-01T10:00:00"


def test_a_degraded_verdict_is_announced_not_just_survived(wired):
    """The safe answer looks exactly like a normal one; only the note says
    that nothing was actually judged."""
    wired(
        {"t1": [_mail(US, "2026-08-01T09:00:00"), _mail("c@x.test", "2026-08-01T10:00:00")]},
        verdicts=[Verdict(True, "llm_call_failed", "degraded")],
    )
    res = _call({"thread_ids": ["t1"]})
    assert res["threads"]["t1"]["needs_reply"] is True
    assert res["note"] and "degraded" in res["note"] and "llm_call_failed" in res["note"]


def test_the_handler_writes_nothing(wired):
    """A verdict is a reading. Nothing here archives, closes or marks read."""
    threads = {
        "t1": [_mail(US, "2026-08-01T09:00:00"), _mail("c@x.test", "2026-08-01T10:00:00")]
    }
    before = [dict(r) for r in threads["t1"]]
    wired(threads)
    _call({"thread_ids": ["t1"]})
    assert threads["t1"] == before
