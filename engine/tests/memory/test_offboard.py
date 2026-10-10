"""Plan M2.8: offboarding removes only the profile's own rule rows."""

from __future__ import annotations

import os

import pytest

from zylch.memory import offboard
from zylch.memory.company_key import current_company_key
from zylch.storage import database as dbm
from zylch.storage.models import Blob


@pytest.fixture
def store_with_two_owners(company_db, tmp_path):
    key = current_company_key()
    engine = dbm.current_memory_engine()
    assert engine is not None and key
    from sqlalchemy.orm import sessionmaker

    with sessionmaker(bind=engine)() as s:
        s.add_all(
            [
                Blob(owner_id="a@x", company_key=key, namespace="user:" + key, content="fact by a"),
                Blob(owner_id="a@x", company_key=key, namespace="facts:" + key, content="fact2 by a"),
                Blob(owner_id="a@x", company_key=key, namespace="template:a@x", content="rule of a"),
                Blob(owner_id="a@x", company_key=key, namespace="prefs:a@x", content="pref of a"),
                Blob(owner_id="b@x", company_key=key, namespace="template:b@x", content="rule of b"),
                Blob(owner_id="b@x", company_key=key, namespace="user:" + key, content="fact by b"),
            ]
        )
        s.commit()
    return key, engine


def _contents(engine):
    from sqlalchemy.orm import sessionmaker

    with sessionmaker(bind=engine)() as s:
        return sorted(row.content for row in s.query(Blob).all())


def test_only_owned_rule_rows_go(store_with_two_owners):
    key, engine = store_with_two_owners
    removed = offboard.delete_owned_rules("a@x")
    assert removed == 2
    assert _contents(engine) == ["fact by a", "fact by b", "fact2 by a", "rule of b"]


def test_last_holder_deletes_the_file(store_with_two_owners):
    key, engine = store_with_two_owners
    path = offboard.delete_store(key)
    assert path and not os.path.exists(path)
    assert dbm.current_memory_engine() is None


def test_not_last_holder_keeps_company_rows_even_when_alone_in_rows(company_db):
    """The helper's group-membership fact wins over row presence: a second
    member that has not written yet must not cost the leaver's facts."""
    from sqlalchemy.orm import sessionmaker

    key = current_company_key()
    engine = dbm.current_memory_engine()
    with sessionmaker(bind=engine)() as s:
        s.add_all(
            [
                Blob(owner_id="a@x", company_key=key, namespace="user:" + key, content="fact by a"),
                Blob(owner_id="a@x", company_key=key, namespace="prefs:a@x", content="pref of a"),
            ]
        )
        s.commit()
    assert offboard.delete_owned_rules("a@x", last_holder=False) == 1
    assert _contents(engine) == ["fact by a"]
    assert offboard.delete_owned_rules("a@x", last_holder=True) == 1
    assert _contents(engine) == []


def test_rules_of_both_account_identities_go(company_db):
    """A profile names its account by email and by Firebase uid; rules written
    under either are this account's, another account's rules stay."""
    from sqlalchemy.orm import sessionmaker

    key = current_company_key()
    engine = dbm.current_memory_engine()
    with sessionmaker(bind=engine)() as s:
        s.add_all(
            [
                Blob(owner_id="a@x", company_key=key, namespace="prefs:a@x", content="pref by email"),
                Blob(owner_id="uidA", company_key=key, namespace="template:uidA", content="rule by uid"),
                Blob(owner_id="uidA", company_key=key, namespace="user:" + key, content="fact by uid"),
                Blob(owner_id="b@x", company_key=key, namespace="prefs:b@x", content="pref of b"),
            ]
        )
        s.commit()
    assert offboard.delete_account_rules({"a@x", "uidA"}) == 2
    assert _contents(engine) == ["fact by uid", "pref of b"]


@pytest.mark.parametrize("owners", ["a@x", set(), {" "}, {"a@x", "local-user"}, {"owner_default"}])
def test_identities_are_a_collection_of_real_accounts(company_db, owners):
    with pytest.raises((TypeError, ValueError)):
        offboard.delete_account_rules(owners)


def test_last_holder_with_two_identities_removes_their_rows(company_db):
    from sqlalchemy.orm import sessionmaker

    key = current_company_key()
    engine = dbm.current_memory_engine()
    with sessionmaker(bind=engine)() as s:
        s.add_all(
            [
                Blob(owner_id="a@x", company_key=key, namespace="prefs:a@x", content="pref by email"),
                Blob(owner_id="uidA", company_key=key, namespace="user:" + key, content="fact by uid"),
            ]
        )
        s.commit()
    assert offboard.delete_account_rules({"a@x", "uidA"}, last_holder=True) == 2
    assert _contents(engine) == []


def test_offboard_cli_uses_both_identities_and_refuses_with_none(company_db, monkeypatch):
    from click.testing import CliRunner

    from zylch.cli import main as cli_main
    from zylch.cli.tenant_commands import memory_offboard

    seen = []
    monkeypatch.setattr(cli_main, "_configure_logging", lambda: None)
    monkeypatch.setattr(cli_main, "_setup_profile", lambda name, lock=True: "p")
    monkeypatch.setattr(offboard, "delete_account_rules",
                        lambda owners, last_holder=False: seen.append(sorted(owners)) or 0)
    monkeypatch.setenv("OWNER_ID", "uidA")
    monkeypatch.setenv("EMAIL_ADDRESS", "a@x")
    result = CliRunner().invoke(memory_offboard, ["--yes"], obj={"profile": "p"})
    assert result.exit_code == 0, result.output
    assert seen == [["a@x", "uidA"]]
    monkeypatch.delenv("EMAIL_ADDRESS")
    result = CliRunner().invoke(memory_offboard, ["--yes"], obj={"profile": "p"})
    assert result.exit_code == 0, result.output
    assert seen[-1] == ["uidA"]  # a profile without an email still leaves by its uid
    monkeypatch.delenv("OWNER_ID")
    result = CliRunner().invoke(memory_offboard, ["--yes"], obj={"profile": "p"})
    assert result.exit_code == 2 and "refused" in result.output
    assert len(seen) == 2  # the refusal deleted nothing
