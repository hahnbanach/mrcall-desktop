import base64
import json
from email.message import EmailMessage

import httpx
import pytest

from zylch.email.gmail_mailbox import GmailError, GmailMailbox

OWNER = "owner@example.test"
SOURCE = "<source@example.test>"


def raw(message_id=SOURCE, body="Synthetic body", recipient="test@example.test"):
    message = EmailMessage()
    message["Message-ID"] = message_id
    message["From"] = OWNER
    message["To"] = recipient
    message.set_content(body)
    return message.as_bytes()


def message(identifier="m1", *, thread="thread1", labels=None, payload=None):
    return {"id": identifier, "threadId": thread, "labelIds": ["DRAFT"] if labels is None else labels,
            "raw": base64.urlsafe_b64encode(payload or raw()).decode()}


def draft(identifier="d1", **kwargs):
    return {"id": identifier, "message": message(**kwargs)}


class Auth:
    def verify(self):
        return {"email": OWNER}

    def access_token(self):
        return "private-test-token"


def mailbox(handler, auth=None):
    return GmailMailbox(OWNER, auth=auth or Auth(), http_client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_paginated_drafts_fetch_current_replacements_with_complete_raw():
    calls = []

    def handler(request):
        calls.append(request)
        assert request.headers["Authorization"] == "Bearer private-test-token"
        if request.url.path.endswith("/drafts"):
            if "pageToken" not in request.url.params:
                return httpx.Response(200, json={"drafts": [{"id": "d1"}], "nextPageToken": "next"})
            assert request.url.params["pageToken"] == "next"
            return httpx.Response(200, json={"drafts": [{"id": "d2"}]})
        identifier = request.url.path.rsplit("/", 1)[1]
        return httpx.Response(200, json={
            "id": identifier, "message": message("m" + identifier[-1], payload=raw(body="Saved provider revision"))})

    rows = mailbox(handler).list_drafts()
    assert [r["id"] for r in rows] == ["d1", "d2"]
    assert all(b"Saved provider revision" in r["raw"] for r in rows)
    assert rows[0]["message_id"] == "m1"
    assert all(r.url.params.get("format") == "raw" for r in calls if "/drafts/" in r.url.path)


@pytest.mark.parametrize("result", [
    {"drafts": [{"id": "d1"}, {"id": "d1"}]},
    {"drafts": "invalid"}, {"drafts": [{"id": ""}]},
    {"nextPageToken": ""}, {"nextPageToken": 123},
])
def test_malformed_draft_inventory_refuses(result):
    with pytest.raises(GmailError, match="gmail_inventory_incomplete"):
        mailbox(lambda r: httpx.Response(200, json=result)).list_drafts()


def test_repeated_pagination_refuses_instead_of_silently_truncating():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"nextPageToken": "same"})

    with pytest.raises(GmailError, match="gmail_inventory_incomplete"):
        mailbox(handler).list_drafts()
    assert len(calls) == 2


def test_missing_draft_returns_none_but_changed_inventory_refuses():
    assert mailbox(lambda r: httpx.Response(404, json={})).get_draft("d1") is None

    def handler(request):
        return httpx.Response(200, json={"drafts": [{"id": "d1"}]}) if request.url.path.endswith("/drafts") else httpx.Response(404)

    with pytest.raises(GmailError, match="gmail_inventory_changed"):
        mailbox(handler).list_drafts()


@pytest.mark.parametrize("labels", [["SENT"], ["TRASH", "DRAFT"]])
def test_externally_sent_or_trashed_item_is_not_a_draft(labels):
    assert mailbox(lambda r: httpx.Response(200, json=draft(labels=labels))).get_draft("d1") is None


def test_non_draft_identity_is_refused():
    with pytest.raises(GmailError, match="gmail_item_not_draft"):
        mailbox(lambda r: httpx.Response(200, json=draft(labels=["INBOX"]))).get_draft("d1")


def test_create_and_update_wire_shapes_preserve_native_thread_identity():
    calls = []
    payload = raw()

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=draft())

    client = mailbox(handler)
    assert client.create_draft(payload, "thread1")["id"] == "d1"
    assert client.update_draft("d1", payload, "thread1")["id"] == "d1"
    mutations = [r for r in calls if r.method != "GET"]
    assert [r.method for r in mutations] == ["POST", "PUT"]
    for request in mutations:
        body = json.loads(request.content)
        assert body["message"]["threadId"] == "thread1"
        assert base64.urlsafe_b64decode(body["message"]["raw"] + "==") == payload
    assert mutations[0].url.path.endswith("/drafts")
    assert mutations[1].url.path.endswith("/drafts/d1")


def test_send_named_draft_uses_latest_raw_and_direct_send_creates_no_draft():
    calls = []
    edited = raw("<claimed@example.test>", "Saved edit", "edited@example.test")

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"id": "sent1", "threadId": "thread1"})

    client = mailbox(handler)
    assert client.send_draft("d1", edited)["acknowledged"] is True
    assert client.send_message(edited)["message_id"] == "sent1"
    first = json.loads(calls[0].content)
    assert calls[0].url.path.endswith("/drafts/send") and first["id"] == "d1"
    assert base64.urlsafe_b64decode(first["message"]["raw"] + "==") == edited
    assert calls[1].url.path.endswith("/messages/send")
    assert len(calls) == 2


@pytest.mark.parametrize("status", [401, 403, 404, 429, 500])
def test_mutation_http_errors_are_never_retried_or_expose_provider_text(status, caplog):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, json={"error": "private-test-token SECRET message text"})

    with pytest.raises(GmailError) as error:
        mailbox(handler).send_draft("d1", raw())
    assert len(calls) == 1 and error.value.http_status == status
    assert error.value.non_dispatch is (status in {401, 403, 404, 429})
    assert "SECRET" not in str(error.value) + caplog.text
    assert "private-test-token" not in str(error.value) + caplog.text


def test_lost_dispatch_acknowledgement_is_not_repeated(caplog):
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("SECRET raw response", request=request)

    with pytest.raises(GmailError, match="gmail_provider_unavailable"):
        mailbox(handler).send_message(raw())
    assert len(calls) == 1 and "SECRET" not in caplog.text


def test_post_success_then_readback_auth_failure_remains_uncertain():
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"id": "d1"}) if request.method == "POST" else httpx.Response(401)
    with pytest.raises(GmailError) as failure:
        mailbox(handler).create_draft(raw())
    assert [request.method for request in calls] == ["POST", "GET"]
    assert failure.value.non_dispatch is False


def test_trash_uses_message_trash_and_independently_verifies_absence_and_trash():
    calls = []
    dispatched = False

    def handler(request):
        nonlocal dispatched
        calls.append(request)
        if request.method == "POST":
            assert request.url.path.endswith("/messages/m1/trash")
            dispatched = True
            return httpx.Response(200, json={"id": "m1"})
        if request.url.path.endswith("/messages/m1"):
            return httpx.Response(200, json=message(labels=["TRASH"]))
        return httpx.Response(404) if dispatched else httpx.Response(200, json=draft())

    result = mailbox(handler).trash_draft("d1")
    assert result["verified"] is True
    assert [r.method for r in calls] == ["GET", "POST", "GET", "GET"]
    assert not any(r.method == "DELETE" for r in calls)


def test_trash_missing_draft_causes_no_mutation():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(404)

    with pytest.raises(GmailError, match="gmail_draft_not_found"):
        mailbox(handler).trash_draft("d1")
    assert len(calls) == 1 and calls[0].method == "GET"


def test_trash_response_without_independent_provider_confirmation_refuses():
    def handler(request):
        if request.url.path.endswith("/trash"):
            return httpx.Response(200, json={"id": "m1"})
        if "/messages/" in request.url.path:
            return httpx.Response(200, json=message())
        return httpx.Response(200, json=draft())

    with pytest.raises(GmailError, match="gmail_trash_unconfirmed"):
        mailbox(handler).trash_draft("d1")


def test_sent_search_is_paginated_label_restricted_and_exact_rfc_verified():
    calls = []

    def handler(request):
        calls.append(request)
        if request.url.path.endswith("/messages"):
            assert request.url.params["labelIds"] == "SENT"
            assert request.url.params["q"] == "rfc822msgid:" + SOURCE
            if "pageToken" not in request.url.params:
                return httpx.Response(200, json={"messages": [{"id": "m1"}], "nextPageToken": "next"})
            return httpx.Response(200, json={"messages": [{"id": "m2"}, {"id": "m3"}]})
        identifier = request.url.path.rsplit("/", 1)[1]
        labels = ["SENT"] if identifier != "m3" else ["DRAFT"]
        content = raw() if identifier != "m2" else raw("<other@example.test>")
        return httpx.Response(200, json=message(identifier, labels=labels, payload=content))

    rows = mailbox(handler).sent(SOURCE)
    assert [r["id"] for r in rows] == ["m1"]
    assert len(calls) == 5
    assert mailbox(lambda r: httpx.Response(200, json={})).sent(SOURCE) == []


def test_find_drafts_uses_rfc_header_without_append():
    calls = []

    def handler(request):
        calls.append(request)
        if request.url.path.endswith("/drafts"):
            assert request.url.params["q"] == "rfc822msgid:" + SOURCE
            return httpx.Response(200, json={"drafts": [{"id": "d1"}, {"id": "d2"}]})
        identifier = request.url.path.rsplit("/", 1)[1]
        return httpx.Response(200, json=draft(identifier, payload=raw() if identifier == "d1" else raw("<other@example.test>")))

    assert [r["id"] for r in mailbox(handler).find_drafts(SOURCE)] == ["d1"]
    assert all(r.method == "GET" for r in calls)


def test_wrong_authenticated_mailbox_is_refused_before_read():
    class Other(Auth):
        def verify(self):
            return {"email": "other@example.test"}

    with pytest.raises(GmailError, match="gmail_mailbox_mismatch"):
        mailbox(lambda r: pytest.fail("provider mutation on wrong owner"), auth=Other())


def test_conversation_reads_live_thread_sent_and_drafts_then_rechecks_completeness():
    calls = []
    listing = {"id": "thread1", "historyId": "h1", "messages": [{"id": "m1"}, {"id": "m2"}]}

    def handler(request):
        calls.append(request)
        if request.url.path.endswith("/messages"):
            return httpx.Response(200, json={"messages": [{"id": "m1"}]})
        if "/threads/" in request.url.path:
            assert request.url.params["format"] == "minimal"
            return httpx.Response(200, json=listing)
        identifier = request.url.path.rsplit("/", 1)[1]
        return httpx.Response(200, json=message(identifier, labels=["INBOX"] if identifier == "m1" else ["SENT"],
                                             payload=raw() if identifier == "m1" else raw("<reply@example.test>")))

    rows = mailbox(handler).conversation(SOURCE)
    assert [r["labels"] for r in rows] == [["INBOX"], ["SENT"]]
    assert sum("/threads/" in r.url.path for r in calls) == 2


def test_thread_changed_during_provider_reads_refuses():
    thread_calls = 0

    def handler(request):
        nonlocal thread_calls
        if request.url.path.endswith("/messages"):
            return httpx.Response(200, json={"messages": [{"id": "m1"}]})
        if "/threads/" in request.url.path:
            thread_calls += 1
            return httpx.Response(200, json={"id": "thread1", "historyId": str(thread_calls), "messages": [{"id": "m1"}]})
        return httpx.Response(200, json=message(labels=["INBOX"]))

    with pytest.raises(GmailError, match="gmail_thread_changed"):
        mailbox(handler).conversation(SOURCE)


@pytest.mark.parametrize("bad", ["../drafts", "d1?token=SECRET", "d1\r\n"])
def test_invalid_native_ids_never_reach_provider(bad):
    with pytest.raises(GmailError, match="gmail_identity_invalid"):
        mailbox(lambda r: pytest.fail("bad id dispatched")).get_draft(bad)
