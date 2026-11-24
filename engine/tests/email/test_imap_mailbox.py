"""Exercise the real adapter against complete stateful IMAP responses."""

from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from types import SimpleNamespace

import pytest

from zylch.email.imap_mailbox import IMAPMailbox
from zylch.email.mailbox_errors import MailboxProviderError

OWNER = "owner@example.test"


def mime(mid="<one@example.test>", *, to="peer@example.test", body="Current body", multipart=False):
    message = EmailMessage()
    message["From"], message["To"], message["Subject"], message["Message-ID"] = OWNER, to, "Fixture", mid
    message.set_content(body)
    if multipart:
        message.add_alternative("<p>Current body</p>", subtype="html")
    return message.as_bytes(policy=policy.SMTP)


class Wire:
    capabilities = (b"UIDPLUS", b"MOVE", b"X-GM-EXT-1")

    def __init__(self):
        self.rows = {name: {} for name in ("Drafts", "Sent", "Trash", "All")}
        self.validity = {name: str(index + 7) for index, name in enumerate(self.rows)}
        self.next_uid = 1
        self.untagged_responses = {}
        self.moves = self.appends = 0
        self.wrong_uid = self.bad_copyuid = self.drop_move = self.no_copyuid = self.reject_append = False

    def add(self, raw, folder="Drafts", *, labels=(), thread="77"):
        uid = str(self.next_uid)
        self.next_uid += 1
        self.rows[folder][uid] = {"raw": raw, "gid": str(int(uid) + 1000), "labels": labels, "thread": thread}
        return uid

    def list(self):
        return "OK", [f'(\\{name}) "/" "{name}"'.encode() for name in self.rows]

    def select(self, folder, readonly=False):
        self.folder = folder.strip('"')
        self.untagged_responses["UIDVALIDITY"] = [self.validity[self.folder].encode()]
        return "OK", []

    def uid(self, command, *args):
        rows = self.rows[self.folder]
        if command == "SEARCH":
            criteria = args[1:]
            selected = list(rows)
            if criteria[0] == "UID":
                selected = [uid for uid in selected if uid == criteria[1]]
            elif criteria[0] == "HEADER":
                wanted = criteria[2].strip('"')
                selected = [uid for uid in selected if str(BytesParser().parsebytes(rows[uid]["raw"]).get(criteria[1]) or "") == wanted]
            elif criteria[0] == "X-GM-MSGID":
                selected = [uid for uid in selected if rows[uid]["gid"] == criteria[1]]
            elif criteria[0] == "X-GM-THRID":
                selected = [uid for uid in selected if rows[uid]["thread"] == criteria[1]]
            elif str(criteria[0]).startswith("(OR"):
                pass
            else:
                assert criteria == ("ALL",)
            return "OK", [" ".join(selected).encode()]
        if command == "FETCH":
            uid = str(args[0])
            value = rows[uid]
            raw = value["raw"]
            labels = " ".join("\\" + label for label in value["labels"])
            actual = "99999" if self.wrong_uid else uid
            prefix = f'1 (UID {actual} FLAGS () RFC822.SIZE {len(raw)} X-GM-MSGID {value["gid"]} X-GM-THRID {value["thread"]} X-GM-LABELS ({labels}) BODY[] {{{len(raw)}}}'
            return "OK", [(prefix.encode(), raw), b")"]
        assert command == "MOVE"
        self.moves += 1
        uid = str(args[0])
        value = rows.pop(uid, None)
        if value is None or self.drop_move:
            return "OK", [b"No matching message"]
        destination = args[1].strip('"')
        new_uid = self.add(value["raw"], destination)
        self.rows[destination][new_uid]["gid"] = value["gid"]
        if self.no_copyuid:
            return "OK", [b"Moved"]
        mapped = "99999" if self.bad_copyuid else new_uid
        return "OK", [f'[COPYUID {self.validity[destination]} {uid} {mapped}] moved'.encode()]

    def append(self, folder, flags, date, raw):
        self.appends += 1
        if self.reject_append:
            return "NO", [b"Rejected"]
        name = folder.strip('"')
        uid = self.add(raw, name)
        return "OK", [f'[APPENDUID {self.validity[name]} {uid}] appended'.encode()]


def provider(wire, owner=OWNER, host="imap.example.test"):
    client = SimpleNamespace(email_addr=owner, imap_host=host, imap_port=993,
        smtp_host="smtp.example.test", smtp_port=587, password="fixture-only",
        _ensure_connected=lambda: wire, disconnect=lambda: None)
    return IMAPMailbox(owner, client=client, mailbox_id="primary")


def test_unflagged_multipart_draft_is_current_and_trashes_recoverably():
    wire = Wire()
    raw = mime(multipart=True)
    wire.add(raw)
    mailbox = provider(wire)
    draft, = mailbox.list_drafts()
    assert draft["raw"] == raw and "DRAFT" in draft["labels"]
    assert not draft["flags"]
    proof = mailbox.trash_draft(draft["id"], expected_identity=draft["identity"])
    assert proof["ok"] and wire.moves == 1
    assert mailbox.get_draft(draft["id"]) is None
    assert mailbox.get_message(draft["message_id"])["raw"] == raw
    assert mailbox.recover_trash(draft["identity"])["ok"]
    assert mailbox.retire_sent_draft(draft["id"], expected_identity=draft["identity"])["state"] == "absent"
    assert wire.moves == 1


@pytest.mark.parametrize("change", ["owner", "server", "uidvalidity"])
def test_handle_never_rebinds_another_owner_server_or_namespace(change):
    wire = Wire()
    wire.add(mime())
    draft, = provider(wire).list_drafts()
    mailbox = provider(wire, owner="other@example.test" if change == "owner" else OWNER,
                       host="other.example.test" if change == "server" else "imap.example.test")
    if change == "uidvalidity":
        wire.validity["Drafts"] = "999"
    with pytest.raises(MailboxProviderError):
        mailbox.trash_draft(draft["id"])
    assert wire.moves == 0 and len(wire.rows["Drafts"]) == 1


def test_external_replacement_requires_fresh_handle_and_never_reattaches():
    wire = Wire()
    old_uid = wire.add(mime())
    mailbox = provider(wire)
    original, = mailbox.list_drafts()
    del wire.rows["Drafts"][old_uid]
    wire.add(mime("<external@example.test>", to="edited@example.test", body="Saved externally"))
    assert mailbox.get_draft(original["id"]) is None
    fresh, = mailbox.list_drafts()
    assert fresh["id"] != original["id"]
    assert b"Saved externally" in fresh["raw"]
    with pytest.raises(MailboxProviderError, match="named_draft_not_found"):
        mailbox.send_draft(original["id"], mime("<send@example.test>"))


def test_replacement_moves_first_and_returns_new_exact_handle():
    wire = Wire()
    wire.add(mime())
    mailbox = provider(wire)
    original, = mailbox.list_drafts()
    result = mailbox.update_draft(original["id"], mime("<update@example.test>", body="Updated"), expected_identity=original["identity"])
    assert result["id"] != original["id"]
    assert wire.moves == wire.appends == 1
    assert len(wire.rows["Drafts"]) == len(wire.rows["Trash"]) == 1
    assert mailbox.get_draft(original["id"]) is None
    assert b"Updated" in result["raw"]


def test_reused_message_id_refuses_before_move_or_append():
    wire = Wire()
    wire.add(mime())
    mailbox = provider(wire)
    original, = mailbox.list_drafts()
    with pytest.raises(MailboxProviderError, match="message_id_reused") as failure:
        mailbox.update_draft(original["id"], mime(body="Changed"))
    assert failure.value.non_dispatch
    assert wire.moves == wire.appends == 0


def test_append_refusal_after_move_is_uncertain_partial_replacement():
    wire = Wire()
    wire.add(mime())
    mailbox = provider(wire)
    original, = mailbox.list_drafts()
    wire.reject_append = True
    with pytest.raises(MailboxProviderError, match="append_refused") as failure:
        mailbox.update_draft(original["id"], mime("<update@example.test>"))
    assert not failure.value.non_dispatch
    assert failure.value.progress["old_draft_retired"]
    assert len(wire.rows["Drafts"]) == 0 and len(wire.rows["Trash"]) == 1
    assert wire.appends == 1


@pytest.mark.parametrize("mode", ["lost_without_effect", "wrong_copyuid", "no_copyuid_but_proven"])
def test_move_acknowledgement_requires_positive_exact_outcome(mode):
    wire = Wire()
    wire.add(mime())
    mailbox = provider(wire)
    draft, = mailbox.list_drafts()
    wire.drop_move = mode == "lost_without_effect"
    wire.bad_copyuid = mode == "wrong_copyuid"
    wire.no_copyuid = mode == "no_copyuid_but_proven"
    if mode == "no_copyuid_but_proven":
        assert mailbox.trash_draft(draft["id"])["ok"]
    else:
        with pytest.raises(MailboxProviderError):
            mailbox.trash_draft(draft["id"])
    assert wire.moves == 1


def test_partial_inventory_is_failure_not_empty():
    wire = Wire()
    wire.add(mime())
    wire.wrong_uid = True
    with pytest.raises(MailboxProviderError, match="inventory_incomplete"):
        provider(wire).list_drafts()


def test_send_rechecks_snapshot_and_never_retires_before_sent(monkeypatch):
    from zylch.email import imap_mailbox_smtp
    wire = Wire()
    wire.add(mime())
    mailbox = provider(wire)
    draft, = mailbox.list_drafts()
    calls = []
    monkeypatch.setattr(imap_mailbox_smtp, "send_raw", lambda client, raw: calls.append(raw) or {"acknowledged": True})
    mailbox.send_draft(draft["id"], mime("<sending@example.test>"), expected_identity=draft["identity"])
    assert len(calls) == 1 and wire.moves == 0 and len(wire.rows["Drafts"]) == 1
    with pytest.raises(MailboxProviderError, match="changed_before_send"):
        mailbox.send_draft(draft["id"], mime("<sending2@example.test>", body="Private stale body"))
    assert len(calls) == 1


def test_sent_exact_id_and_conversation_complete_header_matching():
    wire = Wire()
    source = mime("<source@example.test>")
    reply = EmailMessage()
    reply["From"], reply["To"], reply["Subject"] = OWNER, "peer@example.test", "Re: Fixture"
    reply["Message-ID"], reply["In-Reply-To"] = "<reply@example.test>", "<source@example.test>"
    reply.set_content("Answer")
    wire.add(source, "All")
    wire.add(reply.as_bytes(policy=policy.SMTP), "All", labels=("Sent",))
    wire.add(mime("<unrelated@example.test>"), "All", thread="88")
    # A newer customer message can belong to Gmail's current thread without
    # repeating the selected source in References. It must not be omitted.
    wire.add(mime("<newer@example.test>"), "All")
    wire.add(reply.as_bytes(policy=policy.SMTP), "Sent")
    mailbox = provider(wire)
    assert len(mailbox.sent("<reply@example.test>")) == 1
    rows = mailbox.conversation("<source@example.test>")
    assert len(rows) == 3 and any("SENT" in row["labels"] for row in rows)


def test_default_factory_uses_existing_password_and_dedicated_locked_clients(monkeypatch):
    from zylch.email import mailboxes
    from zylch.email.imap_client import IMAPClient
    mailbox = SimpleNamespace(id="primary", address=OWNER, is_primary=True,
        imap_host="imap.example.test", imap_port=993, smtp_host="smtp.example.test", smtp_port=587)
    monkeypatch.setenv("EMAIL_PASSWORD", "fixture-only")
    monkeypatch.setattr(mailboxes, "primary", lambda owner: mailbox)
    def connection(client):
        if client._conn is None:
            client._conn = Wire()
        return client._conn
    monkeypatch.setattr(IMAPClient, "_ensure_connected", connection)
    first, second = IMAPMailbox(OWNER), IMAPMailbox(OWNER)
    try:
        assert first.client is not second.client and first.conn is not second.conn
        assert first.client.password == "fixture-only"
        assert first.client._imap_lock._is_owned() and second.client._imap_lock._is_owned()
        first.conn.add(mime())
        assert len(first.list_drafts()) == 1 and second.list_drafts() == []
        first.close()
        assert first.client._conn is None and second.client._conn is second.conn
        assert second.list_drafts() == []
    finally:
        first.close()
        second.close()


def test_alternate_token_encoding_cannot_admit_an_alias_of_a_uid():
    import base64
    import json
    wire = Wire()
    wire.add(mime())
    mailbox = provider(wire)
    draft, = mailbox.list_drafts()
    raw = base64.urlsafe_b64decode(draft["id"] + "=" * (-len(draft["id"]) % 4))
    alias = base64.urlsafe_b64encode(json.dumps(json.loads(raw), indent=2).encode()).rstrip(b"=").decode()
    with pytest.raises(MailboxProviderError, match="identity_invalid"):
        mailbox.trash_draft(alias)
    assert wire.moves == 0


def test_snapshot_mismatch_prevents_retiring_a_changed_named_message():
    wire = Wire()
    uid = wire.add(mime())
    mailbox = provider(wire)
    draft, = mailbox.list_drafts()
    wire.rows["Drafts"][uid]["raw"] = mime(body="Unexpected replacement under same UID")
    with pytest.raises(MailboxProviderError, match="identity_changed"):
        mailbox.retire_sent_draft(draft["id"], expected_identity=draft["identity"])
    assert wire.moves == 0


class LabelsWire(Wire):
    """Keep the complete FETCH exchange and vary only the label-list grammar."""

    def __init__(self, label_list):
        super().__init__()
        self.label_list = label_list

    def uid(self, command, *args):
        status, data = super().uid(command, *args)
        if command == "FETCH" and data and isinstance(data[0], tuple):
            metadata, raw = data[0]
            metadata = metadata.replace(b"X-GM-LABELS ()", b"X-GM-LABELS " + self.label_list)
            data = [(metadata, raw), *data[1:]]
        return status, data


@pytest.mark.parametrize("label,normalized", [
    (b"Sent", "SENT"), (b"Draft", "DRAFT"), (b"Drafts", "DRAFT"),
    (b"Trash", "TRASH"), (b"Spam", "SPAM"),
])
@pytest.mark.parametrize("quoted", [False, True])
def test_reserved_gmail_labels_accept_astring_atoms_and_quoted_strings(label, normalized, quoted):
    encoded = b'"\\\\' + label + b'"' if quoted else b"\\" + label
    wire = LabelsWire(b"(" + encoded + b")")
    wire.add(mime(), "All")
    row, = provider(wire).conversation("<one@example.test>")
    assert row["labels"] == ["ALL", normalized]


def test_label_parser_preserves_quoted_escapes_and_ignores_custom_label_text():
    wire = LabelsWire(br'("Sent" "team (\\Sent)" "quote\" and slash\\" "X-GM-LABELS (\\Sent)" "{5}")')
    wire.add(mime(), "All")
    row, = provider(wire).conversation("<one@example.test>")
    assert row["labels"] == ["ALL"]


@pytest.mark.parametrize("label_list", [
    b"NIL", b'("unterminated)', br'("bad\escape")', b"((\\Sent))",
    b'("\\\\Sent""other")', b"(\\Sent", b"(\\Sent))", b"({5})",
    b'(\\Sent) X-GM-LABELS (\\Trash)', b'("line\rbreak")', b"(unquoted*label)",
    b"(" + b"a" * 65536 + b")", b"(" * 10 + b"\\Sent" + b")" * 10,
])
def test_incomplete_or_malformed_label_inventory_refuses_eligibility(label_list):
    wire = LabelsWire(label_list)
    wire.add(mime(), "All")
    with pytest.raises(MailboxProviderError, match="imap_inventory_incomplete"):
        provider(wire).conversation("<one@example.test>")


def test_label_field_after_body_literal_is_observed_and_other_fields_are_not_labels():
    class SuffixLabelsWire(Wire):
        def uid(self, command, *args):
            status, data = super().uid(command, *args)
            if command == "FETCH" and data and isinstance(data[0], tuple):
                metadata, raw = data[0]
                metadata = metadata.replace(b" X-GM-LABELS ()", b"")
                return status, [(metadata, raw), br' X-CUSTOM "X-GM-LABELS (\\Trash)" X-GM-LABELS ("\\Sent"))']
            return status, data
    wire = SuffixLabelsWire()
    wire.add(mime(), "All")
    row, = provider(wire).conversation("<one@example.test>")
    assert row["labels"] == ["ALL", "SENT"]
