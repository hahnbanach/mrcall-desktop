"""A paused role surfaces explicitly, the same way on both billing choices (milestone 10, S6).

The plan's rule: an empty Anthropic ranking for a role makes a
personal-Anthropic-key profile pause on that role with an explicit message,
as an unserved credits role does; every other profile is unaffected. The
first published table leaves NARRATION without an Anthropic model under both
presets and MNEMONIC, MEMORY_MERGE and MEMORY_EXTRACT under economy; the table
here empties the same rankings of the fixture table. Each place a paused role
used to fail silently or as an unexplained error now says which role paused
and why (`zylch/llm/role_pause.py`):

- `narration.summarize` / `narration.predict` reply ``paused`` with the message;
- the update pipeline's memory stage records one warning per paused memory
  role, logs it once without a traceback, and the other stages run;
- `usage.today`'s model policy (the Settings card) reads the role as null and
  gives its reason under ``paused``.

Storage is a temporary SQLite file; no model is called.
"""

from __future__ import annotations

import copy
import logging
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from zylch.llm import model_policy, role_pause
from zylch.llm.roles import table
from zylch.llm.roles.table import RolePaused

from . import model_table_fixture as fixture

OWNER = "o-role-pause"
# The rankings the first published table leaves without an Anthropic model.
EMPTY = {
    "economy": ("NARRATION", "MNEMONIC", "MEMORY_MERGE", "MEMORY_EXTRACT"),
    "balanced": ("NARRATION",),
}


@pytest.fixture(autouse=True)
def first_table_gaps():
    """The fixture table with the first published table's empty Anthropic rankings."""
    doc = copy.deepcopy(fixture.doc("table.json"))
    for preset, roles in EMPTY.items():
        for role in roles:
            doc["presets"][preset]["roles"][role]["anthropic_ranking"] = []
    table.set_table(doc)
    role_pause._seen.clear()
    yield
    role_pause._seen.clear()


@pytest.fixture
def profile(monkeypatch):
    """Save `values` as the profile the engine reads (the process environment)."""
    for key in ("ZYLCH_PROFILE_DIR", "LLM_PROVIDER", "LLM_MODEL_PRESET", *model_policy.ROLES):
        monkeypatch.delenv(key, raising=False)

    def save(**values):
        for key, value in values.items():
            monkeypatch.setenv(key, value)

    return save


def anthropic(profile, preset):
    profile(LLM_PROVIDER="anthropic", LLM_MODEL_PRESET=preset, ANTHROPIC_API_KEY="sk-synthetic")


def credits_serving_nothing(profile, preset, **saved):
    profile(LLM_PROVIDER="mrcall", LLM_MODEL_PRESET=preset, **saved)
    fixture.serve([])


# ── narration ──────────────────────────────────────────────


async def _narrate(kind):
    from zylch.rpc import methods

    if kind == "summarize":
        params = {"lines": ["INFO fetching the inbox for the user"], "context": ""}
        return await methods.narration_summarize(params, lambda *a: None)
    return await methods.narration_predict({"message": "scrivi a Mario"}, lambda *a: None)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["summarize", "predict"])
@pytest.mark.parametrize("preset", ["economy", "balanced"])
async def test_narration_on_a_personal_anthropic_key_says_the_role_paused(
    profile, preset, kind, caplog
):
    anthropic(profile, preset)
    with caplog.at_level(logging.DEBUG, logger="zylch.llm.role_pause"):
        first, again = await _narrate(kind), await _narrate(kind)
    assert (
        first
        == again
        == {
            "text": "",
            # Settings has no NARRATION field: the remedy is the custom preset.
            "paused": (
                "AI paused: no Anthropic model for role NARRATION: none of the models ranked for it "
                f"under the {preset} preset is an Anthropic model, so a personal Anthropic "
                "key cannot run it. In Settings, choose the custom preset with an Anthropic "
                "model as the default model, or another billing choice."
            ),
        }
    )
    assert "no Anthropic model for role NARRATION: " in first["paused"]
    # Logged once as a warning, then at debug level: no flood on every call.
    pauses = [r for r in caplog.records if "role NARRATION" in r.getMessage()]
    assert [r.levelno for r in pauses] == [logging.WARNING, logging.DEBUG]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["summarize", "predict"])
async def test_narration_on_credits_pauses_in_the_same_shape(profile, kind):
    credits_serving_nothing(profile, "balanced")
    reply = await _narrate(kind)
    assert set(reply) == {"text", "paused"} and reply["text"] == ""
    assert reply["paused"].startswith("AI paused: no model served for role NARRATION: ")
    assert reply["paused"].endswith(
        "In Settings, choose the custom preset with a model the billing server serves as the "
        "default model, or another billing choice."
    )


def test_only_the_personal_anthropic_key_pauses_narration(profile):
    for provider in ("openrouter", "mrcall"):
        values = {"LLM_PROVIDER": provider, "LLM_MODEL_PRESET": "economy"}
        fixture.serve(fixture.everything())
        assert model_policy.resolve_model("MODEL_NARRATION", values=values)
    values = {"LLM_PROVIDER": "anthropic", "LLM_MODEL_PRESET": "economy"}
    with pytest.raises(RolePaused):
        model_policy.resolve_model("MODEL_NARRATION", values=values)
    # An explicit choice for the role still runs on the personal key.
    values["MODEL_NARRATION"] = "claude-sonnet-5"
    assert model_policy.resolve_model("MODEL_NARRATION", values=values) == "claude-sonnet-5"


# ── the update pipeline's memory stage ─────────────────────


@pytest.fixture
def pending_memory(tmp_path, monkeypatch):
    """A profile with one WhatsApp message awaiting memory extraction."""
    from zylch.storage import database
    from zylch.storage.database import get_session
    from zylch.storage.models import WhatsAppMessage

    monkeypatch.setenv("ZYLCH_DB_PATH", str(tmp_path / "pipeline.db"))
    monkeypatch.setenv("EMAIL_ADDRESS", "support@mrcall.ai")
    database.dispose_engine()
    database.init_db()
    with get_session() as session:
        mid = str(uuid.uuid4())
        session.add(
            WhatsAppMessage(
                id=mid,
                owner_id=OWNER,
                message_id=mid,
                chat_jid="391112223334@s.whatsapp.net",
                sender_jid="391112223334@s.whatsapp.net",
                text="hi",
                timestamp=datetime.now(UTC),
                is_from_me=False,
                is_group=False,
            )
        )
    yield
    database.dispose_engine()


async def _update():
    """One update: the memory stage resolves its roles as the worker does; no model runs."""
    from zylch.llm import routed_model
    from zylch.services import process_pipeline as pp

    async def memory(owner_id, store):
        for role in role_pause.MEMORY_ROLES:  # what MemoryWorker() resolves first
            routed_model(role)
        return 1, 1

    probe = AsyncMock()
    probe.check_transport = AsyncMock(return_value=None)
    errors, tasks = [], AsyncMock(return_value="detection ran")
    with (
        patch.object(pp, "_run_sync", AsyncMock(return_value={"success": True, "new_messages": 0})),
        patch.object(pp, "_run_whatsapp_sync", return_value={"skipped": True, "reason": "test"}),
        patch("zylch.llm.client.make_llm_client", lambda *a, **k: probe),
        patch.object(pp, "_run_memory", memory),
        patch.object(pp, "_run_tasks", tasks),
        patch("zylch.services.command_handlers.handle_tasks", AsyncMock(return_value="no tasks")),
    ):
        await pp.handle_process([], None, OWNER, errors_out=errors)
    return errors, tasks


def _memory(errors):
    return [e for e in errors if e["stage"] == "memory"]


@pytest.mark.asyncio
async def test_an_economy_anthropic_key_records_each_paused_memory_role_and_runs_the_rest(
    pending_memory, profile, caplog
):
    from zylch.services.error_messages import humanize_entry

    anthropic(profile, "economy")
    with caplog.at_level(logging.DEBUG):
        errors, tasks = await _update()
        tasks.assert_awaited_once()  # the other stages ran
        memory = _memory(errors)
        assert [str(e["error"]) for e in memory] == [
            f"AI paused: no Anthropic model for role {role}: none of the models ranked for it "
            "under the economy preset is an Anthropic model, so a personal Anthropic key "
            "cannot run it. Choose a model for it in Settings."  # both have a Settings field
            for role in ("MEMORY_MERGE", "MEMORY_EXTRACT")
        ]
        assert all(isinstance(e["error"], RolePaused) for e in memory)
        for entry in map(humanize_entry, memory):
            assert entry["severity"] == "warning" and entry["kind"] == "model_paused"
            assert entry["action"] == "Choose a model for it in Settings."
        # Never an error with a traceback; each pause a warning the first time only.
        assert not [r for r in caplog.records if r.levelno >= logging.ERROR]
        caplog.clear()
        again, _ = await _update()
        assert [str(e["error"]) for e in _memory(again)] == [str(e["error"]) for e in memory]
        assert not [
            r
            for r in caplog.records
            if "role MEMORY_" in r.getMessage() and r.levelno >= logging.WARNING
        ]


@pytest.mark.asyncio
async def test_balanced_on_an_anthropic_key_and_other_providers_do_not_pause_memory(
    pending_memory, profile
):
    anthropic(profile, "balanced")
    errors, _ = await _update()
    assert _memory(errors) == []
    profile(LLM_PROVIDER="openrouter", LLM_MODEL_PRESET="economy", OPENROUTER_API_KEY="sk-or")
    errors, _ = await _update()
    assert _memory(errors) == []


@pytest.mark.asyncio
async def test_credits_record_an_unserved_memory_role_in_the_same_shape(pending_memory, profile):
    from zylch.services.error_messages import humanize_entry

    credits_serving_nothing(profile, "economy", MODEL_SYNC_ANALYSIS="claude-sonnet-5")
    errors, tasks = await _update()
    tasks.assert_awaited_once()
    memory = _memory(errors)
    assert [str(e["error"]) for e in memory] == [
        f"AI paused: no model served for role {role}: the MrCall billing server serves none "
        "of the models ranked for it under the economy preset. Choose a model for it in "
        "Settings."
        for role in ("MEMORY_MERGE", "MEMORY_EXTRACT")
    ]
    assert {humanize_entry(e)["kind"] for e in memory} == {"model_paused"}


# ── usage.today: the effective models Settings reads ───────


@pytest.mark.parametrize("preset", ["economy", "balanced"])
def test_the_settings_snapshot_reads_a_paused_role_as_null_with_its_reason(profile, preset):
    anthropic(profile, preset)
    snapshot = model_policy.policy_snapshot()
    body = table.document()["presets"][preset]["roles"]  # the fixture's own gap included
    paused = {f"MODEL_{role}" for role in body if not body[role]["anthropic_ranking"]}
    assert paused >= {f"MODEL_{role}" for role in EMPTY[preset]}
    assert set(snapshot["paused"]) == paused
    for role in model_policy.ROLES:
        if role in paused:
            assert snapshot["roles"][role] is None
            name = role.removeprefix("MODEL_")
            reason = table.anthropic_pause(name, preset)
            assert snapshot["paused"][role] == reason
        else:
            assert snapshot["roles"][role]


def test_the_settings_snapshot_gives_an_unserved_credits_role_its_reason(profile):
    credits_serving_nothing(profile, "balanced")
    snapshot = model_policy.policy_snapshot()
    assert set(snapshot["paused"]) == set(model_policy.ROLES)
    assert snapshot["paused"]["MODEL_NARRATION"].startswith(
        "AI paused: no model served for role NARRATION: "
    )


def test_a_profile_that_pauses_nothing_reports_no_pause(profile):
    profile(LLM_PROVIDER="openrouter", LLM_MODEL_PRESET="economy", OPENROUTER_API_KEY="sk-or")
    assert model_policy.policy_snapshot()["paused"] == {}


# ── the remedy names what Settings actually offers ─────────


def test_the_roles_with_a_settings_field_are_the_settings_schema_s():
    from zylch.services.settings_schema import SETTINGS_SCHEMA

    fields = {f["key"] for f in SETTINGS_SCHEMA if f["type"] == "model"}
    assert {f"MODEL_{role}" for role in table.SETTINGS_ROLES} == fields


@pytest.mark.parametrize("preset", ["economy", "balanced"])
def test_each_paused_role_names_a_remedy_the_user_can_follow(profile, preset):
    """A role Settings has a field for: choose a model for it there. Any other
    role (NARRATION, MNEMONIC, ...): the custom preset with a model the billing
    choice runs as the default, or another billing choice."""
    anthropic(profile, preset)
    for role, message in model_policy.policy_snapshot()["paused"].items():
        if role.removeprefix("MODEL_") in table.SETTINGS_ROLES:
            assert message.endswith(" Choose a model for it in Settings."), role
        else:
            assert message.endswith(
                " In Settings, choose the custom preset with an Anthropic model as the default "
                "model, or another billing choice."
            ), role
    credits_serving_nothing(profile, preset)
    for role, message in model_policy.policy_snapshot()["paused"].items():
        overridable = role.removeprefix("MODEL_") in table.SETTINGS_ROLES
        assert message.endswith(
            " Choose a model for it in Settings."
            if overridable
            else " In Settings, choose the custom preset with a model the billing server serves "
            "as the default model, or another billing choice."
        ), role


def test_the_update_card_action_is_the_pause_s_own_remedy():
    from zylch.services.error_messages import humanize_error

    pause = RolePaused(
        table.anthropic_pause("MNEMONIC", "economy"),
        "MNEMONIC",
        "economy",
        table.remedy("MNEMONIC", "an Anthropic model"),
    )
    action = humanize_error(pause, "memory")["action"]
    assert action == (
        "In Settings, choose the custom preset with an Anthropic model as the default model, "
        "or another billing choice."
    )
