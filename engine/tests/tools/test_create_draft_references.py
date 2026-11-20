"""`create_draft` takes a References chain as the archive stores it: folded over lines."""

from __future__ import annotations

import asyncio
import json
import sqlite3

import pytest

from zylch.storage import database as dbm
from zylch.tools.base import ToolStatus

OWNER = "owner@company.test"
IDS = ["<first@client.test>", "<second@company.test>", "<third@client.test>"]


@pytest.fixture
def tool(tmp_path, monkeypatch):
    db_path = str(tmp_path / "zylch.db")
    monkeypatch.setenv("ZYLCH_DB_PATH", db_path)
    monkeypatch.setenv("EMAIL_ADDRESS", OWNER)
    dbm.dispose_engine()
    dbm.init_db()
    from zylch.storage.storage import Storage
    from zylch.tools.gmail_tools import CreateDraftTool

    yield CreateDraftTool(Storage(), OWNER), db_path
    dbm.dispose_engine()


def create(tool, references, **overrides):
    args = {"to": "customer@client.test", "subject": "Re: order", "body": "On its way.",
            "in_reply_to": IDS[-1], "references": references, "thread_id": IDS[0]}
    args.update(overrides)
    return asyncio.run(tool.execute(**args))


def stored(db_path):
    conn = sqlite3.connect(db_path)
    try:
        return [json.loads(row[0]) for row in conn.execute('SELECT "references" FROM drafts')]
    finally:
        conn.close()


@pytest.mark.parametrize("separator", [" ", "\n", "\r\n ", "\n\t", " \n "])
def test_a_folded_chain_gives_the_same_draft_as_a_chain_on_one_line(tool, separator):
    draft, db_path = tool
    result = create(draft, separator.join(IDS))
    assert result.status is ToolStatus.SUCCESS, result.error
    assert stored(db_path) == [IDS]


def test_a_line_break_inside_the_reply_target_is_still_refused(tool):
    draft, db_path = tool
    result = create(draft, " ".join(IDS), in_reply_to="<third@client.test>\nBcc: other@client.test")
    assert result.status is ToolStatus.ERROR
    assert stored(db_path) == []


def test_no_identifier_of_a_folded_chain_carries_a_line_break(tool):
    draft, db_path = tool
    result = create(draft, "<first@client.test>\r\nBcc: other@client.test\r\n<third@client.test>")
    assert result.status is ToolStatus.SUCCESS, result.error
    (chain,) = stored(db_path)
    assert all("\n" not in item and "\r" not in item for item in chain)
