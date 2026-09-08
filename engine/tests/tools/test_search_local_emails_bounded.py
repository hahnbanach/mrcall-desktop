"""One page of `search_local_emails` is bounded no matter how the mailbox grows.

On the IMAP sync path the `snippet` column holds the whole body
(`zylch/email/imap_client.py`), and this tool used to return it per match,
twice — in the message and again in `data.matches`. A hundred matches of
12 KB became a 1.1 MB tool result, and the second LLM call of the turn was
rejected at more than twice the model window, while the compose step,
which matches little, kept succeeding. Incident:
`~/hb/docs/known-issues/2026-09-08-engine-chat-prompt-unbounded.md`.

A match is now a locator plus a bounded preview; the full text is one
`read_email` call away; the page size is clamped and says so; a further
page is announced with its offset.
"""

from __future__ import annotations

import asyncio

from zylch.assistant.core import ZylchAIAgent
from zylch.tools import local_email_search_tool as mod
from zylch.tools.local_email_search_tool import SearchLocalEmailsTool

OWNER = "owner@example.com"
BODY_CHARS = 12_000


class _Storage:
    """Stands in for `Storage.search_emails_flat`, honouring limit/offset."""

    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def search_emails_flat(self, owner_id, user_email, query, folder="all", limit=50, offset=0):
        self.calls.append({"limit": limit, "offset": offset})
        return self.rows[offset : offset + limit]


def _row(i: int, body: str):
    return {
        "id": f"id-{i}",
        "thread_id": f"<thread-{i}@example.com>",
        "date": "2026-09-03T10:00:00",
        "from_email": "customer@example.com",
        "from_name": "A Customer",
        "to_email": OWNER,
        "cc_email": "",
        "subject": f"Quote request {i}",
        "snippet": body,
        "has_attachments": False,
        "is_user_sent": False,
    }


def _tool(rows):
    tool = SearchLocalEmailsTool(_Storage(rows), owner_id=OWNER)
    tool._user_email = lambda oid: OWNER
    return tool


def _formatted(result) -> str:
    agent = ZylchAIAgent.__new__(ZylchAIAgent)
    return agent._format_tool_result(result)


def _run(coro):
    return asyncio.run(coro)


def test_a_page_of_whole_body_matches_is_bounded():
    body = ("private label pricing " * 600)[:BODY_CHARS]
    rows = [_row(i, body) for i in range(98)]
    tool = _tool(rows)

    result = _run(tool.execute(query="private label", limit=100))

    assert result.data["count"] == mod.MAX_MATCHES
    assert f"limit 100 clamped to {mod.MAX_MATCHES}" in result.message.splitlines()[0]
    text = _formatted(result)
    assert len(text) < 60_000, f"a page is still {len(text)} chars"
    for match in result.data["matches"]:
        assert "snippet" not in match and "preview" not in match
        assert match["body_chars"] == BODY_CHARS
        assert f"read_email id={match['id']} for the full text]" in result.message
    previews = [line for line in result.message.splitlines() if "read_email id=" in line]
    assert len(previews) == mod.MAX_MATCHES
    assert all(len(line) < mod.PREVIEW_CHARS + 120 for line in previews)


def test_next_page_is_announced_with_its_offset():
    rows = [_row(i, "short body") for i in range(98)]
    tool = _tool(rows)

    first = _run(tool.execute(query="short", limit=50))
    assert first.data["count"] == 50
    assert first.data["next_offset"] == 50
    assert "offset=50" in first.message.splitlines()[-1]
    # One extra row is asked for so a next page is known, never guessed.
    assert tool.storage.calls[-1] == {"limit": 51, "offset": 0}

    second = _run(tool.execute(query="short", limit=50, offset=50))
    assert second.data["count"] == 48
    assert second.data["next_offset"] is None
    assert "offset=" not in second.message.splitlines()[-1]


def test_a_short_body_is_shown_whole_and_unmarked():
    tool = _tool([_row(1, "Hello there,\n\nthe price is 1.20 per can.")])

    result = _run(tool.execute(query="price", limit=10))

    assert result.message.splitlines()[-1].strip() == "Hello there, the price is 1.20 per can."
    assert "read_email" not in result.message
    assert "clamped" not in result.message


def test_empty_result_guidance_is_unchanged():
    tool = _tool([])

    result = _run(tool.execute(query="nobody", limit=10))

    assert result.data == {"matches": [], "count": 0, "query": "nobody", "folder": "all"}
    assert result.message.startswith("No local emails match `nobody` (folder=all).")
    for step in ("DROP ONE TOKEN", "VARY ONE LETTER", "SWITCH SURFACE"):
        assert step in result.message
