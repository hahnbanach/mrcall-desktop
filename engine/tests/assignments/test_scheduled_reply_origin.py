import asyncio
from email import message_from_bytes
from email.policy import default
from types import SimpleNamespace

import pytest

from mail_fixture import MailFixture
from zylch.email.imap_client import IMAPClient
from zylch.services import task_assignment_evidence as evidence
from zylch.storage import database as db
from zylch.storage.models import Email
from zylch.storage.storage import Storage
from zylch.tools.base import ToolStatus
from zylch.tools.gmail_tools import SendDraftTool

R5_ROOT = "<179192977573.2387051.2113276377374779398@operator-test.mrcall.ai>"
R5_SENT = "<179193074778.2222777.13408948990133512826@mrcall.ai>"
OWNER = "alice@example.test"


@pytest.fixture
def sent_journey(env, monkeypatch, tmp_path):
    mail = MailFixture(monkeypatch)
    with db.get_session() as session:
        session.query(Email).delete()
    mail.messages = {"INBOX": {}, '"Archive"': {}, '"Sent"': {}}
    mail.root_id = mail.add(R5_ROOT, "customer@example.test", OWNER)
    captured = []

    class SMTP:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def ehlo(self):
            pass

        def starttls(self):
            pass

        def login(self, *args):
            pass

        def save(self, raw):
            captured.append(message_from_bytes(raw, policy=default))
            mail.messages['"Sent"'][mail.next_uid] = raw
            mail.next_uid += 1

        def sendmail(self, sender, recipients, raw):
            self.save(raw.encode())

        def send_message(self, message, sender, recipients):
            self.save(message.as_bytes())

    monkeypatch.setattr("zylch.email.imap_client.smtplib.SMTP", SMTP)
    monkeypatch.setattr("zylch.email.imap_client.make_msgid", lambda **kwargs: R5_SENT)
    monkeypatch.setattr("zylch.api.token_storage.get_email", lambda owner: OWNER)
    store = Storage()

    def send(attachment=False, normalized=False):
        paths = []
        if attachment:
            path = tmp_path / "fixture.txt"
            path.write_text("Disposable attachment")
            paths.append(str(path))
        draft = store.create_draft(
            owner_id=OWNER,
            to="customer@example.test",
            subject="Re: operational test",
            body="The requested result is 238.",
            in_reply_to=R5_ROOT,
            references=[R5_ROOT],
            thread_id=R5_ROOT,
            attachment_paths=paths,
        )
        if normalized:
            from zylch.storage.models import Draft

            with db.get_session() as session:
                row = session.query(Draft).filter(Draft.id == draft["id"]).one()
                row.references = [R5_ROOT.replace("<", "&lt;").replace(">", "&gt;"), "invalid"]
        result = asyncio.run(
            SendDraftTool(IMAPClient(OWNER, "fixture"), store, OWNER).execute(draft_id=draft["id"])
        )
        if normalized and result.status == ToolStatus.ERROR:
            import inspect

            assert "guarded_send" in inspect.getsource(SendDraftTool.execute)
            assert "Exact RFC thread root Message-ID required" in result.error
            assert not captured
            assert store.get_draft(OWNER, draft["id"])["status"] == "draft"
            return None, None
        assert result.status == ToolStatus.SUCCESS, result.error
        assert len(captured) == 1
        with db.get_session() as session:
            row = session.query(Email).filter(Email.message_id_header == R5_SENT).one()
            stored = row.to_dict()
        return stored, captured[0]

    return SimpleNamespace(
        send=send, mail=mail, captured=captured, store=store, tmp_path=tmp_path, SMTP=SMTP
    )


@pytest.mark.parametrize("attachment", [False, True])
@pytest.mark.parametrize("normalized", [False, True])
def test_actual_send_persists_emitted_references(sent_journey, attachment, normalized):
    stored, emitted = sent_journey.send(attachment, normalized)
    if stored is None:
        assert normalized is True
        return
    assert str(emitted["References"]) == R5_ROOT
    assert stored["references"] == str(emitted["References"])
    assert stored["in_reply_to"] == str(emitted["In-Reply-To"]).strip() == R5_ROOT
    assert emitted["Auto-Submitted"] is None
    actual = evidence.reply(stored["id"], R5_ROOT)
    assert actual["complete"] is True
    assert actual["judgement"] == "NONAUTOMATIC_MEMBER_REPLY_CANDIDATE"
    assert actual["reason"] == "NEEDS_HUMAN_VERIFICATION"


@pytest.mark.parametrize("failure", ["missing_provider", "foreign_owner", "wrong_provider_target"])
def test_real_provider_and_owner_negatives(sent_journey, failure):
    stored, emitted = sent_journey.send()
    if failure == "missing_provider":
        sent_journey.mail.messages['"Sent"'].clear()
    elif failure == "foreign_owner":
        with db.get_session() as session:
            session.query(Email).filter(
                Email.id == stored["id"]
            ).one().owner_id = "bob@example.test"
    else:
        emitted.replace_header("In-Reply-To", "<absent@example.test>")
        uid = next(iter(sent_journey.mail.messages['"Sent"']))
        sent_journey.mail.messages['"Sent"'][uid] = emitted.as_bytes()
    actual = evidence.reply(stored["id"], R5_ROOT)
    assert actual["complete"] is False
    assert actual["judgement"] == "UNKNOWN"


@pytest.mark.parametrize("target_fault", [None, "missing", "changed"])
def test_inherited_references_require_independent_live_target(sent_journey, target_fault):
    stored, emitted = sent_journey.send()
    with db.get_session() as session:
        session.query(Email).filter(Email.id == stored["id"]).one().references = None
    assert str(emitted["References"]) == R5_ROOT
    actual = evidence.reply(stored["id"], R5_ROOT)
    assert actual["complete"] and actual["judgement"] == "NONAUTOMATIC_MEMBER_REPLY_CANDIDATE"
    assert actual["source"]["target_header_digest"]
    with db.get_session() as session:
        assert session.query(Email).filter(Email.id == stored["id"]).one().references is None
    if target_fault is not None:
        archive = sent_journey.mail.messages['"Archive"']
        if target_fault == "missing":
            archive.clear()
        else:
            uid = next(iter(archive))
            target = message_from_bytes(archive[uid])
            target.replace_header("From", "foreign@example.test")
            archive[uid] = target.as_bytes()
        refused = evidence.reply(stored["id"], R5_ROOT)
        assert not refused["complete"] and refused["judgement"] == "UNKNOWN"


def test_existing_sent_rows_are_not_backfilled(sent_journey):
    from datetime import datetime, timezone

    stored, emitted = sent_journey.send()
    with db.get_session() as session:
        session.query(Email).filter(Email.id == stored["id"]).one().references = None
    duplicate = sent_journey.store.insert_sent_email(
        OWNER,
        R5_ROOT,
        R5_SENT,
        OWNER,
        "customer@example.test",
        None,
        "Re: operational test",
        "The requested result is 238.",
        datetime.now(timezone.utc),
        in_reply_to=R5_ROOT,
        references=R5_ROOT,
    )
    assert duplicate["id"] == stored["id"]
    assert duplicate["references"] is None
    assert len(sent_journey.captured) == 1


def _origin_draft(journey, *, attachment=False, label="current", root=R5_ROOT):
    paths = []
    if attachment:
        path = journey.tmp_path / "origin-attachment.txt"
        path.write_text("Attachment fixture")
        paths = [str(path)]
    return journey.store.create_draft(
        owner_id=OWNER,
        to="customer@example.test",
        subject="Re: operator origin",
        body="Answer " + label,
        in_reply_to=root,
        references=[root],
        thread_id=root,
        attachment_paths=paths,
    )


def _scripted_chat(monkeypatch, journey, draft, *, outcome="send", barrier=None):
    from zylch.assistant.core import ZylchAIAgent
    from zylch.services.chat_service import ChatService

    calls = []
    agent = object.__new__(ZylchAIAgent)
    agent.tool_map = {
        "send_draft": SendDraftTool(IMAPClient(OWNER, "fixture"), journey.store, OWNER)
    }

    async def process(self, **kwargs):
        calls.append(kwargs["user_message"])
        if barrier is not None:
            await barrier.wait()
        if outcome == "raise":
            raise RuntimeError("Scripted provider error")
        if outcome == "draft-only":
            return {"response": "Draft only"}
        selected = draft[kwargs["user_message"]] if "id" not in draft else draft
        approved, edited = await kwargs["approval_callback"](
            kwargs["user_message"],
            "send_draft",
            {"draft_id": selected["id"]},
        )
        if not approved:
            return {"response": "Denied"}
        result = await agent._call_tool("send_draft", edited or {"draft_id": selected["id"]})
        return {"response": result.error or result.message, "status": result.status.value}

    monkeypatch.setattr(ChatService, "process_message", process)
    monkeypatch.setattr("zylch.rpc.methods._owner_id", lambda: OWNER)
    return calls


async def _chat_call(params, *, approve=True, dispatch=False):
    from zylch.rpc import methods

    pending = []

    def notify(method, value):
        if method == "chat.pending_approval":
            pending.append(
                asyncio.create_task(
                    methods.chat_approve(
                        {
                            "tool_use_id": value["tool_use_id"],
                            "mode": "once" if approve else "deny",
                        },
                        lambda *args: None,
                    )
                )
            )

    if dispatch:
        import json
        from zylch.rpc.dispatch import dispatch_raw

        result = await dispatch_raw(
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "chat.send", "params": params}), notify
        )
        assert "error" not in result, result
        result = result["result"]
    else:
        result = await methods.chat_send(params, notify)
    if pending:
        await asyncio.gather(*pending)
    return result


def _origin_params(label="scheduled"):
    return {
        "message": label,
        "conversation_id": label,
        "operator_origin": "scheduled_operator",
        "operator_origin_version": 1,
    }


@pytest.mark.parametrize("attachment", [False, True])
def test_marked_current_request_emits_automatic_real_reply(
    env, sent_journey, monkeypatch, attachment
):
    draft = _origin_draft(sent_journey, attachment=attachment)
    _scripted_chat(monkeypatch, sent_journey, draft)
    result = asyncio.run(_chat_call(_origin_params()))
    assert result["status"] == "success"
    emitted = sent_journey.captured[0]
    assert emitted["Auto-Submitted"] == "auto-replied"
    with db.get_session() as session:
        row = session.query(Email).filter(Email.message_id_header == R5_SENT).one()
        stored = row.to_dict()
    assert stored["references"] == str(emitted["References"])
    actual = evidence.reply(stored["id"], R5_ROOT)
    assert actual["complete"] is True and actual["judgement"] == "AUTOMATIC"
    from zylch.services.task_assignment_projection import project

    projection = project(R5_ROOT)
    assert projection["complete"] is True and projection["hold_auto_reply"] is False


def test_capability_strict_integer(env):
    from zylch.rpc.methods import system_capabilities

    actual = asyncio.run(system_capabilities({}, lambda *args: None))
    assert type(actual["operator_reply_provenance"]) is int
    assert actual["operator_reply_provenance"] == 1


@pytest.mark.parametrize(
    "fields",
    [
        {"operator_origin": "scheduled_operator"},
        {"operator_origin_version": 1},
        {"operator_origin": None, "operator_origin_version": 1},
        {"operator_origin": "scheduled_operator", "operator_origin_version": True},
        {"operator_origin": "scheduled_operator", "operator_origin_version": "1"},
        {"operator_origin": "scheduled_operator", "operator_origin_version": 2},
        {"operator_origin": "manual", "operator_origin_version": 1},
        {"operator_origin": True, "operator_origin_version": 1},
    ],
)
def test_bad_origin_refused_before_service(env, sent_journey, monkeypatch, fields):
    from zylch.rpc.methods import chat_send
    from zylch.services.chat_service import ChatService

    monkeypatch.setattr(ChatService, "__init__", lambda self: pytest.fail("Service constructed"))
    with pytest.raises(ValueError):
        asyncio.run(chat_send({"message": "invalid", **fields}, lambda *args: None))
    assert not sent_journey.captured


@pytest.mark.parametrize("state", ["assigned", "pending-human", "manual-unknown"])
def test_marked_intent_never_overrides_real_authority(env, sent_journey, monkeypatch, state):
    draft = _origin_draft(sent_journey)
    if state == "assigned":
        from zylch.rpc import task_assignments

        intent = asyncio.run(
            task_assignments.preview(
                {
                    "operation": "assign",
                    "thread_key": R5_ROOT,
                    "expected_revision": 0,
                    "assignee_uid": "bob",
                },
                lambda *a: None,
            )
        )
        asyncio.run(
            task_assignments.commit({"intent": intent, "grant": env.sign(intent)}, lambda *a: None)
        )
    else:
        sent_journey.send()
        if state == "manual-unknown":
            with db.get_session() as session:
                session.query(Email).filter(
                    Email.message_id_header == R5_SENT
                ).one().references = None
            sent_journey.mail.messages['"Archive"'].clear()
        sent_journey.captured.clear()
    if state == "manual-unknown":
        from zylch.services.task_assignment_projection import project

        assert project(R5_ROOT)["state"] == "unknown"
    _scripted_chat(monkeypatch, sent_journey, draft)
    result = asyncio.run(_chat_call(_origin_params()))
    assert result["status"] == "error"
    assert not sent_journey.captured
    assert sent_journey.store.get_draft(OWNER, draft["id"])["status"] == "draft"


@pytest.mark.parametrize("drift", ["original", "claimed-headers"])
def test_real_admission_and_claim_snapshot_reject_drift(env, sent_journey, monkeypatch, drift):
    draft = _origin_draft(sent_journey)
    if drift == "original":
        from zylch.rpc import task_assignments

        original = task_assignments.project

        async def changed(params, notify):
            result = await original(params, notify)
            with db.get_session() as session:
                session.query(Email).filter(
                    Email.id == sent_journey.mail.root_id
                ).one().from_email = "changed@example.test"
            return result

        monkeypatch.setattr(task_assignments, "project", changed)
    else:
        original = sent_journey.store.claim_draft_for_send

        def changed(owner, draft_id):
            result = original(owner, draft_id)
            from zylch.storage.models import Draft

            with db.get_session() as session:
                session.query(Draft).filter(Draft.id == draft_id).one().references = [
                    "<changed@example.test>"
                ]
            return result

        monkeypatch.setattr(sent_journey.store, "claim_draft_for_send", changed)
    _scripted_chat(monkeypatch, sent_journey, draft)
    result = asyncio.run(_chat_call(_origin_params()))
    assert result["status"] == "error" and not sent_journey.captured
    assert sent_journey.store.get_draft(OWNER, draft["id"])["status"] == "draft"


@pytest.mark.parametrize(
    "change",
    [
        {"version": True},
        {"actor_uid": "bob"},
        {"source_owner_uid": "bob"},
        {"space_id": "wrong"},
        {"thread_key": "<wrong@example.test>"},
        {"current_message_ids": []},
        {"complete": 1},
        {"hold_auto_reply": 0},
    ],
)
def test_typed_projection_refusal_preserves_no_effect(env, sent_journey, monkeypatch, change):
    draft = _origin_draft(sent_journey)
    from zylch.rpc import task_assignments

    original = task_assignments.project

    async def malformed(params, notify):
        return {**await original(params, notify), **change}

    monkeypatch.setattr(task_assignments, "project", malformed)
    _scripted_chat(monkeypatch, sent_journey, draft)
    result = asyncio.run(_chat_call(_origin_params()))
    assert result["status"] == "error" and not sent_journey.captured
    assert sent_journey.store.get_draft(OWNER, draft["id"])["status"] == "draft"


def test_rpc_dispatch_and_real_approval_denial(env, sent_journey, monkeypatch):
    draft = _origin_draft(sent_journey)
    _scripted_chat(monkeypatch, sent_journey, draft)
    assert (
        asyncio.run(_chat_call(_origin_params(), approve=False, dispatch=True))["response"]
        == "Denied"
    )
    assert not sent_journey.captured
    assert asyncio.run(_chat_call(_origin_params(), dispatch=True))["status"] == "success"
    assert sent_journey.captured[0]["Auto-Submitted"] == "auto-replied"


def test_read_only_permission_still_refuses_marked_send(env, sent_journey, monkeypatch):
    draft = _origin_draft(sent_journey)
    _scripted_chat(monkeypatch, sent_journey, draft)
    from zylch.services.request_policy import READ_ONLY_POLICY, READ_ONLY_POLICY_VERSION

    params = {
        **_origin_params(),
        "mutation_policy": READ_ONLY_POLICY,
        "policy_version": READ_ONLY_POLICY_VERSION,
    }
    assert asyncio.run(_chat_call(params))["status"] == "error"
    assert not sent_journey.captured


def test_ambient_scope_does_not_mark_direct_transport(env, sent_journey):
    from zylch.services import operator_reply_origin as origin
    from zylch.rpc.methods import _admit_operator_reply

    with origin.scope(lambda owner, draft: _admit_operator_reply(owner, draft, lambda *a: None)):
        IMAPClient(OWNER, "fixture").send_message(
            to="customer@example.test",
            subject="Direct",
            body="Manual",
            in_reply_to=R5_ROOT,
            references=R5_ROOT,
        )
    assert sent_journey.captured[0]["Auto-Submitted"] is None
    assert origin._request.get() is None and origin._send.get() is None


def test_draft_only_request_does_not_mark_delayed_human_send(env, sent_journey, monkeypatch):
    draft = _origin_draft(sent_journey)
    _scripted_chat(monkeypatch, sent_journey, draft, outcome="draft-only")
    assert asyncio.run(_chat_call(_origin_params()))["response"] == "Draft only"
    _scripted_chat(monkeypatch, sent_journey, draft)
    assert (
        asyncio.run(_chat_call({"message": "human", "conversation_id": "human"}))["status"]
        == "success"
    )
    assert sent_journey.captured[0]["Auto-Submitted"] is None
    from zylch.services.task_assignment_projection import project

    assert project(R5_ROOT)["hold_auto_reply"] is True


@pytest.mark.parametrize("failure", ["provider-error", "cancel", "smtp-refusal", "smtp-unknown"])
def test_request_and_handoff_reset_after_failure(env, sent_journey, monkeypatch, failure):
    from zylch.services import operator_reply_origin as origin
    from zylch.services.chat_service import ChatService
    from zylch.rpc import methods

    draft = _origin_draft(sent_journey)
    _scripted_chat(
        monkeypatch, sent_journey, draft, outcome="raise" if failure == "provider-error" else "send"
    )
    handles, handed = [], []
    original = ChatService.process_message

    async def observed(self, **kwargs):
        handles.append(origin._request.get())
        try:
            return await original(self, **kwargs)
        finally:
            handed.append(origin._send.get())

    monkeypatch.setattr(ChatService, "process_message", observed)
    if failure.startswith("smtp-"):
        import smtplib

        def refused(*args):
            if failure == "smtp-unknown":
                raise ConnectionResetError("Disposable uncertain delivery fixture")
            raise smtplib.SMTPRecipientsRefused(
                {"customer@example.test": (550, b"fixture refusal")}
            )

        monkeypatch.setattr(sent_journey.SMTP, "sendmail", refused)
    if failure == "cancel":

        async def canceled():
            request = asyncio.create_task(methods.chat_send(_origin_params(), lambda *a: None))
            while not methods._pending_approvals:
                await asyncio.sleep(0.001)
            request.cancel()
            with pytest.raises(asyncio.CancelledError):
                await request

        asyncio.run(canceled())
    elif failure == "provider-error":
        with pytest.raises(RuntimeError):
            asyncio.run(_chat_call(_origin_params()))
    else:
        assert asyncio.run(_chat_call(_origin_params()))["status"] == "error"
    assert handles and handles[0]["active"] is False and handed == [None]
    assert origin._request.get() is None and origin._send.get() is None
    assert not sent_journey.captured
    expected = "sending" if failure == "smtp-unknown" else "draft"
    assert sent_journey.store.get_draft(OWNER, draft["id"])["status"] == expected


def test_concurrent_marked_and_manual_requests_remain_isolated(env, sent_journey, monkeypatch):
    import itertools

    second = "<independent-manual@example.test>"
    sent_journey.mail.add(second, "customer@example.test", OWNER)
    scheduled = _origin_draft(sent_journey)
    manual = _origin_draft(sent_journey, root=second, label="manual")
    ids = itertools.count()
    monkeypatch.setattr(
        "zylch.email.imap_client.make_msgid",
        lambda **kwargs: f"<concurrent-{next(ids)}@example.test>",
    )
    barrier = asyncio.Event()
    calls = _scripted_chat(
        monkeypatch, sent_journey, {"scheduled": scheduled, "manual": manual}, barrier=barrier
    )

    async def concurrent():
        a = asyncio.create_task(_chat_call(_origin_params()))
        b = asyncio.create_task(_chat_call({"message": "manual", "conversation_id": "manual"}))
        while len(calls) < 2:
            await asyncio.sleep(0.001)
        barrier.set()
        return await asyncio.gather(a, b)

    assert all(value["status"] == "success" for value in asyncio.run(concurrent()))
    actual = {
        str(message["In-Reply-To"]).strip(): message["Auto-Submitted"]
        for message in sent_journey.captured
    }
    assert actual == {R5_ROOT: "auto-replied", second: None}


def test_origin_callback_precedes_claim_and_claimed_segment_has_no_await(
    env, sent_journey, monkeypatch
):
    import ast
    import inspect
    import textwrap

    draft = _origin_draft(sent_journey)
    from zylch.rpc import task_assignments

    projected = []
    original = task_assignments.project

    async def observed(params, notify):
        result = await original(params, notify)
        projected.append(result)
        return result

    monkeypatch.setattr(task_assignments, "project", observed)
    claim = sent_journey.store.claim_draft_for_send

    def claimed(owner, draft_id):
        assert len(projected) == 1 and projected[0]["hold_auto_reply"] is False
        return claim(owner, draft_id)

    monkeypatch.setattr(sent_journey.store, "claim_draft_for_send", claimed)
    _scripted_chat(monkeypatch, sent_journey, draft)
    assert asyncio.run(_chat_call(_origin_params()))["status"] == "success"
    tree = ast.parse(textwrap.dedent(inspect.getsource(SendDraftTool.execute)))
    function = tree.body[0]
    claim_line = next(
        node.lineno
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "claim_draft_for_send"
    )
    assert all(
        node.lineno < claim_line for node in ast.walk(function) if isinstance(node, ast.Await)
    )


def test_marked_standalone_send_remains_unmarked(env, sent_journey, monkeypatch):
    draft = sent_journey.store.create_draft(
        owner_id=OWNER, to="customer@example.test", subject="New", body="Standalone"
    )
    _scripted_chat(monkeypatch, sent_journey, draft)
    assert asyncio.run(_chat_call(_origin_params()))["status"] == "success"
    assert sent_journey.captured[0]["Auto-Submitted"] is None


@pytest.mark.parametrize("target", ["covered", "new"])
def test_real_closed_assignment_allows_only_new_inbound(env, sent_journey, monkeypatch, target):
    from zylch.rpc import task_assignments as rpc

    original = _origin_draft(sent_journey)
    intent = asyncio.run(
        rpc.preview(
            {
                "operation": "assign",
                "thread_key": R5_ROOT,
                "expected_revision": 0,
                "assignee_uid": "bob",
            },
            lambda *a: None,
        )
    )
    asyncio.run(rpc.commit({"intent": intent, "grant": env.sign(intent)}, lambda *a: None))
    intent = asyncio.run(
        rpc.preview(
            {
                "operation": "close",
                "thread_key": R5_ROOT,
                "expected_revision": 1,
                "reason": "Handled",
                "handled_ref": "fixture-handled",
            },
            lambda *a: None,
        )
    )
    asyncio.run(rpc.commit({"intent": intent, "grant": env.sign(intent)}, lambda *a: None))
    child = "<new-inbound@example.test>"
    child_id = sent_journey.mail.add(child, "customer@example.test", OWNER, reply=R5_ROOT)
    with db.get_session() as session:
        row = session.query(Email).filter(Email.id == child_id).one()
        row.references, row.thread_id = R5_ROOT, R5_ROOT
    archive = sent_journey.mail.messages['"Archive"']
    uid = max(archive)
    message = message_from_bytes(archive[uid])
    message.replace_header("References", R5_ROOT)
    archive[uid] = message.as_bytes()
    draft = (
        original
        if target == "covered"
        else sent_journey.store.create_draft(
            owner_id=OWNER,
            to="customer@example.test",
            subject="Re: new",
            body="New work",
            in_reply_to=child,
            references=[R5_ROOT, child],
            thread_id=R5_ROOT,
        )
    )
    _scripted_chat(monkeypatch, sent_journey, draft)
    result = asyncio.run(_chat_call(_origin_params()))
    assert result["status"] == ("error" if target == "covered" else "success")
    assert len(sent_journey.captured) == (0 if target == "covered" else 1)
