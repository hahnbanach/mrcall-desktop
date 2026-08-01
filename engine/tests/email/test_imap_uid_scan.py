"""IMAPClient's UID layer: folder discovery, EXAMINE, SEARCH, FETCH.

The old scan path had one shape of bug three times over: a protocol
failure came back as an empty list. These tests pin the opposite
contract — failures raise or are reported — and lock the response
parsing against the shapes imaplib actually produces.
"""

from datetime import datetime, timezone

import pytest

from tests.email.fake_imap import FakeFolder, build_raw_message, make_client
from zylch.email.imap_client import (
    IMAPFolderError,
    IMAPSearchError,
    format_imap_date,
)


def _folders():
    inbox = FakeFolder(uidvalidity=101)
    inbox.add(10, build_raw_message("<a@example.com>", subject="First"))
    inbox.add(11, build_raw_message("<b@example.com>", subject="Second"))

    sent = FakeFolder(uidvalidity=202)
    sent.add(5, build_raw_message("<sent@example.com>", subject="Our reply"))

    archive = FakeFolder(uidvalidity=303)
    archive.add(90, build_raw_message("<a@example.com>", subject="First"))
    archive.add(91, build_raw_message("<archived@example.com>", subject="Filtered away"))

    return {
        "INBOX": inbox,
        '"[Gmail]/Sent Mail"': sent,
        '"[Gmail]/All Mail"': archive,
    }


# --- folder discovery ------------------------------------------------


def test_sync_folders_covers_inbox_sent_and_archive():
    """Archive is not optional: on Gmail, archiving only drops a label.

    A message filtered or archived out of INBOX is still live mail. The
    old INBOX+Sent scope made it permanently invisible to the archive.
    """
    client = make_client(_folders())
    assert client.sync_folders() == [
        "INBOX",
        '"[Gmail]/Sent Mail"',
        '"[Gmail]/All Mail"',
    ]


def test_sync_folders_never_returns_duplicates():
    folders = _folders()
    # A provider whose Sent folder IS the archive folder.
    client = make_client(folders)
    client._find_sent_folder = lambda: '"[Gmail]/All Mail"'
    assert client.sync_folders() == ["INBOX", '"[Gmail]/All Mail"']


def test_sync_folders_survives_missing_archive():
    client = make_client({"INBOX": FakeFolder()})
    assert client.sync_folders() == ["INBOX"]


# --- EXAMINE ---------------------------------------------------------


def test_examine_folder_reports_uid_state_read_only():
    client = make_client(_folders())
    state = client.examine_folder("INBOX")

    assert state.uidvalidity == 101
    assert state.uidnext == 12
    assert state.exists == 2
    assert ("SELECT", "INBOX", True) in client._conn.commands, "EXAMINE must be read-only"


def test_examine_folder_raises_when_the_folder_cannot_be_selected():
    folders = _folders()
    folders["INBOX"].select_fails = True
    client = make_client(folders)

    with pytest.raises(IMAPFolderError):
        client.examine_folder("INBOX")


def test_examine_folder_raises_without_uidvalidity():
    """No UIDVALIDITY means no anchor: refuse rather than sync blind."""
    client = make_client(_folders())
    original = client._conn.select

    def select_without_codes(mailbox="INBOX", readonly=False):
        status, data = original(mailbox, readonly)
        client._conn._pending_codes.pop("UIDVALIDITY", None)
        return status, data

    client._conn.select = select_without_codes
    with pytest.raises(IMAPFolderError):
        client.examine_folder("INBOX")


# --- SEARCH ----------------------------------------------------------


def test_uid_search_returns_sorted_uids():
    client = make_client(_folders())
    assert client.uid_search("INBOX", "ALL") == [10, 11]


def test_failed_search_raises_instead_of_looking_empty():
    """The defect in one line: `status != OK` used to return [].

    An empty mailbox and a broken SEARCH must never be the same value —
    that is what let a broken scan advance the sync floor.
    """
    folders = _folders()
    folders["INBOX"].search_fails = True
    client = make_client(folders)

    with pytest.raises(IMAPSearchError):
        client.uid_search("INBOX", "ALL")


def test_uid_range_search_honours_the_lower_bound():
    client = make_client(_folders())
    assert client.uid_search("INBOX", "(UID 11:*)") == [11]


def test_uid_range_above_the_top_still_returns_the_highest_uid():
    """IMAP's `n:*` quirk — the cursor logic has to survive it."""
    client = make_client(_folders())
    assert client.uid_search("INBOX", "(UID 999:*)") == [11]


# --- scan (search + Message-ID resolution) ---------------------------


def test_scan_folder_resolves_message_ids():
    client = make_client(_folders())
    scan = client.scan_folder("INBOX", lambda state: "ALL")

    assert scan.uids == [10, 11]
    assert scan.message_ids == {10: "<a@example.com>", 11: "<b@example.com>"}
    assert scan.unresolved_uids == []
    assert scan.state.uidvalidity == 101


def test_scan_folder_criteria_builder_sees_folder_state():
    client = make_client(_folders())
    seen = {}

    def builder(state):
        seen["uidvalidity"] = state.uidvalidity
        return "(UID 11:*)"

    scan = client.scan_folder("INBOX", builder)
    assert seen["uidvalidity"] == 101
    assert scan.uids == [11]


def test_scan_folder_reports_unresolvable_uids(caplog):
    """A UID whose identity we cannot establish is reported, not dropped."""
    folders = _folders()
    folders["INBOX"].fetch_errors = {11}
    client = make_client(folders)

    with caplog.at_level("ERROR"):
        scan = client.scan_folder("INBOX", lambda state: "ALL")

    assert scan.unresolved_uids == [11]
    assert any("could not resolve Message-ID" in r.message for r in caplog.records)


def test_scan_folder_tolerates_a_uid_expunged_mid_run(caplog):
    """Expunged between SEARCH and FETCH is a no-op, not a failure."""
    folders = _folders()
    folders["INBOX"].expunged = {11}
    client = make_client(folders)

    with caplog.at_level("WARNING"):
        scan = client.scan_folder("INBOX", lambda state: "ALL")

    assert scan.unresolved_uids == []
    assert scan.message_ids[11] == ""
    assert any("expunged since SEARCH" in r.message for r in caplog.records)


# --- FETCH -----------------------------------------------------------


def test_message_id_survives_header_folding():
    """A folded Message-ID must not read as "this message has none".

    Long IDs (Exchange emits 90+ characters) legitimately arrive folded
    onto a continuation line. Reading them line-by-line would classify
    the message as un-deduplicable and skip it.
    """
    from zylch.email.imap_client import _extract_message_id_header

    folded = b"Message-ID:\r\n <!&!AAAAAAAAAAAYAAAAAAAAAMkzaDU1OJBIsb1cRg@example.com>\r\n\r\n"
    assert (
        _extract_message_id_header(folded)
        == "<!&!AAAAAAAAAAAYAAAAAAAAAMkzaDU1OJBIsb1cRg@example.com>"
    )
    assert _extract_message_id_header(b"From: x@y\r\n\r\n") == ""


def test_fetch_messages_by_uid_parses_and_peeks():
    client = make_client(_folders())
    messages, failed = client.fetch_messages_by_uid("INBOX", [10, 11])

    assert failed == []
    assert messages[10]["message_id"] == "<a@example.com>"
    assert messages[10]["subject"] == "First"
    assert messages[10]["from_email"] == "sender@example.com"
    assert "Body text" in messages[10]["body_plain"]

    fetch_items = [c[3] for c in client._conn.commands if c[0] == "UID" and c[1] == "FETCH"]
    assert all("BODY.PEEK" in item for item in fetch_items)
    assert not any("RFC822" in item for item in fetch_items)


def test_fetch_messages_by_uid_counts_failures(caplog):
    """Per-message failures are counted and named, never skipped silently."""
    folders = _folders()
    folders["INBOX"].fetch_errors = {11}
    client = make_client(folders)

    with caplog.at_level("ERROR"):
        messages, failed = client.fetch_messages_by_uid("INBOX", [10, 11])

    assert failed == [11]
    assert set(messages) == {10}
    assert any("1/2 message fetch(es) FAILED" in r.message for r in caplog.records)


def test_no_mailbox_mutation_commands_are_ever_issued():
    """Read-only in the strong sense: no STORE / MOVE / COPY / EXPUNGE."""
    client = make_client(_folders())
    client.scan_folder("INBOX", lambda state: "ALL")
    client.fetch_messages_by_uid("INBOX", [10])

    issued = {c[1].upper() for c in client._conn.commands if c[0] == "UID"}
    assert issued <= {"SEARCH", "FETCH"}
    assert all(cmd[2] is True for cmd in client._conn.commands if cmd[0] == "SELECT")


# --- date formatting -------------------------------------------------


def test_format_imap_date_is_locale_independent():
    """`strftime("%b")` under it_IT emits "ago" for August; servers reject it."""
    assert format_imap_date(datetime(2026, 8, 1, tzinfo=timezone.utc)) == "01-Aug-2026"
    assert format_imap_date(datetime(2026, 7, 29, tzinfo=timezone.utc)) == "29-Jul-2026"
    assert format_imap_date(datetime(2026, 12, 9, tzinfo=timezone.utc)) == "09-Dec-2026"
