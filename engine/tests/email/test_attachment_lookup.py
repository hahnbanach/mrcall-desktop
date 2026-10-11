"""Simulated IMAP protocol, real MIME parsing and saved binary assertions."""

import asyncio
from email.message import EmailMessage
from pathlib import Path

import pytest

from zylch.email.imap_client import IMAPClient, IMAPError

MID = "<attachment@fixture.test>"
PAYLOAD = b"recorded audio fixture\x00\x01"


class Server:
    def __init__(self, folder="Other folder", attachment=True):
        self.target = folder
        msg = EmailMessage()
        msg["Message-ID"] = MID
        msg.set_content("fixture body")
        if attachment:
            msg.add_attachment(PAYLOAD, maintype="audio", subtype="mpeg", filename="recording.mp3")
        self.raw = msg.as_bytes()
        self.selected = None
        self.commands = []
        self.bad_search = self.bad_fetch = False

    def noop(self):
        return "OK", []

    def list(self):
        return "OK", [
            b'(\\HasNoChildren) "/" "INBOX"',
            b'(\\All) "/" "All Mail"',
            b'(\\Sent) "/" "Sent Mail"',
            b'(\\Noselect) "/" "Container"',
            b'() "/" "Other folder"',
        ]

    def select(self, folder, readonly=False):
        self.commands.append(("select", folder, readonly))
        self.selected = folder.strip('"')
        return "OK", [b"1"]

    def search(self, charset, criteria):
        self.commands.append(("search", self.selected))
        if self.bad_search:
            return "NO", []
        return "OK", [b"1" if self.selected == self.target and MID in criteria else b""]

    def uid(self, command, *args):
        self.commands.append(("uid", command))
        if command == "SEARCH":
            return self.search(*args)
        assert command == "FETCH"
        return self.fetch(*args)

    def fetch(self, number, items):
        self.commands.append(("fetch", items))
        return ("NO", []) if self.bad_fetch else ("OK", [(b"1 (BODY[] {1}", self.raw), b")"])


def client(server):
    c = IMAPClient("owner@fixture.test", "synthetic")
    c._conn = server
    return c


def test_other_folder_saved_without_marking_read(tmp_path):
    server = Server()
    saved = client(server).fetch_attachments(MID, str(tmp_path))
    assert len(saved) == 1 and saved[0]["size"] == len(PAYLOAD)
    assert Path(saved[0]["path"]).read_bytes() == PAYLOAD
    assert all(cmd[2] for cmd in server.commands if cmd[0] == "select")
    assert [cmd for cmd in server.commands if cmd[0] == "fetch"] == [("fetch", "(BODY.PEEK[])")]
    assert "Container" not in [cmd[1].strip('"') for cmd in server.commands if cmd[0] == "select"]


def test_verified_empty_distinct_from_missing_message(tmp_path):
    assert (
        client(Server(folder="INBOX", attachment=False)).fetch_attachments(MID, str(tmp_path)) == []
    )
    with pytest.raises(IMAPError, match="Message not found.*attachments not checked"):
        client(Server(folder="Absent")).fetch_attachments(MID, str(tmp_path))
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("failure", ["bad_search", "bad_fetch"])
def test_protocol_failures_never_claim_no_attachments(tmp_path, failure):
    server = Server()
    setattr(server, failure, True)
    with pytest.raises(IMAPError, match="Attachment lookup"):
        client(server).fetch_attachments(MID, str(tmp_path))
    assert list(tmp_path.iterdir()) == []


def test_missing_message_is_tool_error(tmp_path, monkeypatch):
    from zylch.tools.base import ToolStatus
    from zylch.tools.download_attachment_tool import DownloadAttachmentTool

    class Store:
        def get_email_by_supabase_id(self, owner, identifier):
            return {"message_id_header": MID}

    monkeypatch.setattr(
        "zylch.email.mailboxes.client_for_row", lambda *_: client(Server(folder="Absent"))
    )
    monkeypatch.setattr(
        "zylch.tools.download_attachment_tool.resolve_download_target", lambda _: str(tmp_path)
    )
    result = asyncio.run(
        DownloadAttachmentTool(Store(), owner_id="owner@fixture.test").execute(email_id="id")
    )
    assert result.status == ToolStatus.ERROR
    assert "attachments not checked" in result.error
    assert result.data is None


def test_fetched_identity_mismatch_never_saves_or_claims_empty(tmp_path):
    server = Server()
    server.raw = server.raw.replace(MID.encode(), b"<other@fixture.test>")
    with pytest.raises(IMAPError, match="identity mismatch"):
        client(server).fetch_attachments(MID, str(tmp_path))
    assert list(tmp_path.iterdir()) == []


def test_file_write_failure_is_not_hidden_as_lookup_failure(tmp_path, monkeypatch):
    def fail(*args):
        raise PermissionError("synthetic write refusal")

    monkeypatch.setattr("zylch.email.imap_client.save_attachments", fail)
    with pytest.raises(PermissionError):
        client(Server()).fetch_attachments(MID, str(tmp_path))
