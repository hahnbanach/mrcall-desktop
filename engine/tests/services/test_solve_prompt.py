"""Tests for solve-loop wiring: language directive + approval gate.

These are unit-level sanity checks — they DO NOT validate the live
LLM behaviour. The plan's section C live verification still applies
(npm run dev + click Open on a real task) before claiming the
feature works.
"""

from __future__ import annotations

import os

from zylch.services.solve_constants import (
    SOLVE_TOOLS,
    SOLVE_SYSTEM_PROMPT,
    get_user_language_directive,
)
from zylch.services.task_executor import APPROVAL_TOOLS


# ─── get_user_language_directive ──────────────────────────────


def test_language_directive_pinned_italian(monkeypatch):
    monkeypatch.setenv("USER_LANGUAGE", "it")
    out = get_user_language_directive()
    assert "Italian" in out
    assert "Always reply" in out


def test_language_directive_pinned_english(monkeypatch):
    monkeypatch.setenv("USER_LANGUAGE", "en")
    out = get_user_language_directive()
    assert "English" in out


def test_language_directive_unset_falls_back_to_match(monkeypatch):
    monkeypatch.delenv("USER_LANGUAGE", raising=False)
    out = get_user_language_directive()
    assert "Match the language" in out
    # Default tiebreaker is Italian — the desktop ships to an
    # Italian-first audience and we don't want bilingual flapping.
    assert "Italian" in out


def test_language_directive_unknown_code_falls_back(monkeypatch):
    monkeypatch.setenv("USER_LANGUAGE", "xx")
    out = get_user_language_directive()
    assert "Match the language" in out


def test_language_directive_whitespace_tolerated(monkeypatch):
    monkeypatch.setenv("USER_LANGUAGE", "  IT  ")
    out = get_user_language_directive()
    assert "Italian" in out


# ─── SOLVE_TOOLS ↔ APPROVAL_TOOLS coherence ───────────────────


_WRITE_EFFECT_TOOLS = {
    "send_email",
    "send_whatsapp",
    "send_sms",
    "update_memory",
    "run_python",
}


def test_every_write_tool_in_solve_requires_approval():
    """Any SOLVE_TOOLS entry whose name is in the write-effect set
    MUST also appear in APPROVAL_TOOLS — otherwise tasks.solve would
    fire it without ever surfacing an approval card.
    """
    solve_tool_names = {t["name"] for t in SOLVE_TOOLS}
    write_in_solve = solve_tool_names & _WRITE_EFFECT_TOOLS
    missing = write_in_solve - APPROVAL_TOOLS
    assert not missing, (
        f"SOLVE_TOOLS expose write-effect tools without an approval "
        f"gate: {sorted(missing)}. Add them to APPROVAL_TOOLS in "
        f"engine/zylch/services/task_executor.py."
    )


def test_no_draft_email_in_solve_tools():
    """A.4: draft_email was removed — the model uses send_email and
    the approval card is the single confirmation step. If draft_email
    comes back, update the system prompt accordingly.
    """
    names = {t["name"] for t in SOLVE_TOOLS}
    assert "draft_email" not in names


# ─── System-prompt placeholders ───────────────────────────────


def test_system_prompt_has_required_placeholders():
    """tasks_solve in rpc/methods.py formats these three. If a
    placeholder is removed from the prompt, the .format() call
    crashes with KeyError at runtime — catch it here instead.
    """
    for placeholder in (
        "{user_name}",
        "{personal_data_section}",
        "{user_language_directive}",
    ):
        assert placeholder in SOLVE_SYSTEM_PROMPT, (
            f"SOLVE_SYSTEM_PROMPT missing placeholder {placeholder}; "
            f"tasks_solve will KeyError when formatting."
        )


def test_system_prompt_format_smoke():
    """End-to-end .format() sanity. Mirrors the tasks_solve call
    site so a syntactic regression surfaces here, not at first user
    click.
    """
    os.environ.pop("USER_LANGUAGE", None)
    out = SOLVE_SYSTEM_PROMPT.format(
        user_name="mario",
        personal_data_section="\nUSER PERSONAL DATA:\n- Name: Mario\n",
        user_language_directive=get_user_language_directive(),
    )
    assert "mario" in out
    assert "USER PERSONAL DATA" in out
    assert "RESPONSE LANGUAGE" in out
