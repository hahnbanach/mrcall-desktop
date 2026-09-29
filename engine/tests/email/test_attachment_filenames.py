"""Brief 2026-09-29-toward-sandbox, criterion 2 (first clause): a sender's
attachment filename can never place a file outside the save folder, in
any mode. Built from a local message; no IMAP involved."""

from __future__ import annotations

from email.message import EmailMessage

from zylch.email.imap_client import save_attachments


def _message(*names: str) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = "att"
    msg.set_content("body")
    for n in names:
        msg.add_attachment(b"payload", maintype="application", subtype="octet-stream", filename=n)
    return msg


def test_traversal_names_land_as_basenames(tmp_path):
    save = tmp_path / "downloads"
    sibling_env = tmp_path / "other" / ".env"
    sibling_env.parent.mkdir()
    sibling_env.write_text("SECRET")

    saved = save_attachments(
        _message(str(sibling_env), "../../x", ".env", "sub/dir.pdf"), str(save)
    )

    # Two attachments named `.env` collapse onto one file inside `downloads/`;
    # that is harmless, the profile's own `.env` is not in this folder.
    assert sorted(a["filename"] for a in saved) == [".env", ".env", "dir.pdf", "x"]
    assert sorted(f.name for f in save.iterdir()) == [".env", "dir.pdf", "x"]
    for a in saved:
        assert a["path"].startswith(str(save.resolve()))
    assert sibling_env.read_text() == "SECRET"
    assert not (tmp_path / "x").exists()


def test_empty_and_dot_names_get_an_index(tmp_path):
    saved = save_attachments(_message("", ".."), str(tmp_path))
    assert [a["filename"] for a in saved] == ["attachment_0", "attachment_1"]


def test_non_ascii_name_is_preserved(tmp_path):
    saved = save_attachments(_message("fattura né.pdf"), str(tmp_path))
    assert saved[0]["filename"] == "fattura né.pdf"
