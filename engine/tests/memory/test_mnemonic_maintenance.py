"""The maintenance routes stay mechanical: they retain, they stay in scope, they refuse a tamper (AC8).

Against a real profile and a real company store booted through ``init_db``:

- ``scripts/compact_learned_prefs.py`` — a dry run writes nothing; ``--apply``
  drops the booted profile's exact duplicates and strictly contained rules
  through the retaining drop, in one transaction with one mutation-sequence
  bump, never touches another account's rules and never relocates an
  entity-shaped rule; ``--llm`` only reports;
- ``memory/rebuilds.py`` — the identifier reindex indexes exactly the
  ``#IDENTIFIERS`` entries of PERSON and COMPANY rows; the source-link rebuild
  leaves an ambiguous calendar summary unlinked; the digest guard rolls a
  tampered rebuild back;
- an owner's delete of a blob a pending operation targets leaves that
  operation to fail its compare-and-set and write nothing.
"""

from __future__ import annotations

import importlib.util
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from zylch.memory import rebuilds
from zylch.memory.blob_storage import BlobStorage
from zylch.memory.blob_versions import MAINTENANCE
from zylch.memory.mnemonic import journal
from zylch.memory.mnemonic.commit import submit
from zylch.storage import database as dbm
from zylch.storage.database import get_session
from zylch.storage.models import Blob, CalendarBlob, CalendarEvent, Email, EmailBlob, PersonIdentifier

from . import seeding
from .join_env import rows, store_digest
from .mnemonic_env import COMPANY_A, OWNER_A, boot, clear_process_state, stub_embedder
from .test_mnemonic_commit import asked_to_update, build_context, client, event, update_decision

ENGINE_ROOT = Path(__file__).resolve().parents[2]
EMAIL_A = f"{OWNER_A}@company.test"
COLLEAGUE = "uid-owner-c"
RULE = "Always sign replies with the warehouse number and the order reference."
LONGER = RULE + " Copy the logistics desk on every reply about a delivery."
STYLE = "#IDENTIFIERS\nEntity type: STYLE\nName: Formal voice\n#ABOUT\nOpens with 'Gentile'."
LUCA = (
    "#IDENTIFIERS\nEntity type: PERSON\nName: Luca Bianchi\nEmail: luca@alpha.example\n"
    "Phone: +390212345678\n#ABOUT\nPurchasing; writes from marta@beta.example too."
)
VOICE = "#IDENTIFIERS\nEntity type: STYLE\nName: Terse\nEmail: style@alpha.example\n#ABOUT\nShort."


def compaction():
    path = ENGINE_ROOT / "scripts" / "compact_learned_prefs.py"
    spec = importlib.util.spec_from_file_location("compact_learned_prefs", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def world(tmp_path, monkeypatch, embedder):
    """A colleague's rules, then the booted profile's own, on one company store."""
    stub_embedder(monkeypatch, embedder)
    boot(monkeypatch, tmp_path, COLLEAGUE, COMPANY_A)
    theirs = BlobStorage(get_session, embedder)
    colleague = [seeding.store_blob(theirs, COLLEAGUE, f"template:{COLLEAGUE}", RULE, "seed") for _ in range(2)]
    boot(monkeypatch, tmp_path, OWNER_A, COMPANY_A)
    storage = BlobStorage(get_session, embedder)
    rule = seeding.store_blob(storage, OWNER_A, f"template:{OWNER_A}", RULE, "seed")
    copy = seeding.store_blob(storage, OWNER_A, f"template:{OWNER_A}", "  always SIGN replies with the warehouse number and the order reference. ", "seed")
    longer = seeding.store_blob(storage, OWNER_A, f"prefs:{OWNER_A}", LONGER, "seed")
    style = seeding.store_blob(storage, OWNER_A, f"template:{OWNER_A}", STYLE, "seed")
    yield SimpleNamespace(
        storage=storage, embedder=embedder, colleague=[c["id"] for c in colleague],
        rule=rule["id"], copy=copy["id"], longer=longer["id"], style=style["id"],
    )
    dbm.dispose_engine()
    clear_process_state()


def namespace_of(blob_id):
    found = rows(COMPANY_A, "SELECT namespace FROM blobs WHERE id = ?", [blob_id])
    return found[0][0] if found else None


def blob_rows():
    """Every blob row and every retained version, as the store holds them."""
    return (
        rows(COMPANY_A, "SELECT id, owner_id, namespace, content, updated_at FROM blobs ORDER BY id"),
        rows(COMPANY_A, "SELECT id, blob_id, reason, content FROM blob_versions ORDER BY id"),
    )


def mutation_seq():
    return rows(COMPANY_A, "SELECT mutation_seq FROM memory_meta")[0][0]


# ─── The rule compaction ──────────────────────────────────────────────


def test_a_dry_run_reports_and_writes_nothing(world, capsys):
    before = store_digest(COMPANY_A)

    stats = compaction().run([OWNER_A, EMAIL_A], apply=False, storage=world.storage)

    assert stats["deduped"] == 1 and stats["superseded"] == 1 and stats["relocate_review"] == 1
    assert stats["dropped"] == 0
    assert store_digest(COMPANY_A) == before
    printed = capsys.readouterr().out
    assert f"REVIEW {world.style}" in printed and "a move is the owner's decision" in printed


def test_apply_drops_only_its_own_duplicates_retains_each_text_and_bumps_once(world):
    sequence = mutation_seq()
    texts = {bid: rows(COMPANY_A, "SELECT content FROM blobs WHERE id = ?", [bid])[0][0] for bid in (world.copy, world.rule)}

    stats = compaction().run([OWNER_A, EMAIL_A], apply=True, storage=world.storage)

    assert stats["dropped"] == 2
    assert namespace_of(world.copy) is None and namespace_of(world.rule) is None
    assert namespace_of(world.longer) == f"prefs:{OWNER_A}"
    for bid, text in texts.items():
        assert rows(COMPANY_A, "SELECT reason, content FROM blob_versions WHERE blob_id = ?", [bid]) == [
            (MAINTENANCE, text)
        ]
    assert mutation_seq() == sequence + 1
    assert namespace_of(world.style) == f"template:{OWNER_A}"
    assert [namespace_of(bid) for bid in world.colleague] == [f"template:{COLLEAGUE}"] * 2
    assert compaction().run([OWNER_A, EMAIL_A], apply=True, storage=world.storage)["dropped"] == 0


def test_the_llm_pass_reports_and_drops_nothing(world, monkeypatch, capsys):
    module = compaction()
    monkeypatch.setattr(
        module, "_llm_filter",
        lambda rows_: [{"index": i, "is_operating_rule": False, "why": "narration"} for i in range(len(rows_))],
    )

    stats = module.run([OWNER_A], apply=True, storage=world.storage, use_llm=True)

    assert stats["llm_flagged"] == 1 and stats["dropped"] == 2
    assert namespace_of(world.longer) == f"prefs:{OWNER_A}"
    assert namespace_of(world.style) == f"template:{OWNER_A}"
    assert "reported only" in capsys.readouterr().out


# ─── The rebuilds ─────────────────────────────────────────────────────


def identifiers():
    with get_session() as session:
        return sorted((str(r.blob_id), r.kind, r.value) for r in session.query(PersonIdentifier))


def test_the_reindex_indexes_exactly_the_identifiers_of_people_and_companies(world):
    luca = seeding.store_blob(world.storage, OWNER_A, f"user:{COMPANY_A}", LUCA, "seed")
    seeding.store_blob(world.storage, OWNER_A, f"user:{COMPANY_A}", VOICE, "seed")
    before = store_digest(COMPANY_A)

    dry = rebuilds.reindex_identifiers(EMAIL_A)

    assert dry == {"entities": 1, "missing": 2, "indexed": 0}
    assert store_digest(COMPANY_A) == before
    sequence = mutation_seq()
    assert rebuilds.reindex_identifiers(EMAIL_A, apply=True)["indexed"] == 2
    assert identifiers() == sorted([
        (luca["id"], "email", "luca@alpha.example"), (luca["id"], "phone", "+390212345678"),
    ])
    assert mutation_seq() == sequence + 1
    assert rebuilds.reindex_identifiers(EMAIL_A, apply=True) == {"entities": 1, "missing": 0, "indexed": 0}


def test_a_rebuild_that_changes_a_blob_is_rolled_back(world, monkeypatch):
    from zylch.memory import associations

    seeding.store_blob(world.storage, OWNER_A, f"user:{COMPANY_A}", LUCA, "seed")
    real = associations.add_identifiers

    def tampering(session, **kwargs):
        session.query(Blob).filter(Blob.id == world.longer).update({"content": "rewritten"})
        return real(session, **kwargs)

    monkeypatch.setattr(associations, "add_identifiers", tampering)
    before = store_digest(COMPANY_A)

    with pytest.raises(rebuilds.RebuildTampered):
        rebuilds.reindex_identifiers(EMAIL_A, apply=True)

    assert store_digest(COMPANY_A) == before and identifiers() == []


def test_the_link_rebuild_leaves_an_ambiguous_calendar_summary_unlinked(world):
    with get_session() as session:
        session.add(Email(id="mail-1", owner_id=EMAIL_A, gmail_id="g-1", thread_id="t", subject="x",
                          from_email="luca@alpha.example", date=datetime(2026, 9, 8)))
        for eid, summary in (("ev-1", "Standup"), ("ev-2", "Standup"), ("ev-3", "Quarterly review")):
            session.add(CalendarEvent(id=eid, owner_id=EMAIL_A, google_event_id=eid, summary=summary))
        session.commit()
    mail = seeding.store_blob(world.storage, OWNER_A, f"user:{COMPANY_A}", LUCA, "Extracted from email mail-1 (x)")
    standup = seeding.store_blob(world.storage, OWNER_A, f"user:{COMPANY_A}", VOICE,
                                 "Extracted from calendar event 'Standup' (2026-09-08)")
    review = seeding.store_blob(world.storage, OWNER_A, f"user:{COMPANY_A}", STYLE,
                                "Extracted from calendar event 'Quarterly review' (2026-09-08)")
    blobs_before = blob_rows()

    assert rebuilds.rebuild_source_links() == {"email": 1, "calendar": 1, "ambiguous": 1}

    with get_session() as session:
        assert [(r.email_id, r.blob_id) for r in session.query(EmailBlob)] == [("mail-1", mail["id"])]
        assert [(r.event_id, r.blob_id) for r in session.query(CalendarBlob)] == [("ev-3", review["id"])]
    assert standup["id"] not in {r[0] for r in rows(COMPANY_A, "SELECT blob_id FROM calendar_blobs")}
    assert blob_rows() == blobs_before


# ─── An owner's delete under a pending operation ──────────────────────


def test_an_owner_delete_under_a_pending_operation_fails_its_compare_and_set(world):
    context = build_context(OWNER_A, world.embedder)
    target = seeding.store_blob(context.storage, OWNER_A, f"user:{COMPANY_A}", LUCA, "seed")
    pending = event(event_id="evt-pending")
    assert journal.open_operation(pending).state == journal.PENDING
    assert context.storage.delete_blob(target["id"], OWNER_A)
    before = blob_rows()

    result = submit(
        pending,
        client=client(*[update_decision(target["id"], target["updated_at"]) for _ in range(3)]),
        context=context,
        requested=asked_to_update(target["id"]),
    )

    assert result.outcome == "review_needed"
    assert blob_rows() == before and namespace_of(target["id"]) is None
    assert rows(COMPANY_A, "SELECT COUNT(*) FROM blob_versions WHERE blob_id = ?", [target["id"]]) == [(0,)]
    assert journal.read("evt-pending", owner_id=OWNER_A, company_key=COMPANY_A)["state"] == journal.REVIEW


# ─── The two entry points, booted as an operator runs them ───────────


def test_the_script_and_the_cli_boot_the_profile_and_default_to_a_dry_run(world, tmp_path, monkeypatch, capsys):
    from click.testing import CliRunner

    from zylch.storage.storage import Storage

    from .test_cli_memory import _cli_for

    seeding.store_blob(world.storage, OWNER_A, f"user:{COMPANY_A}", LUCA, "seed")
    cli = _cli_for(monkeypatch, tmp_path, f"profile-{OWNER_A}")
    before = store_digest(COMPANY_A)

    assert compaction().main(["--profile", f"profile-{OWNER_A}"]) == 0
    assert "[DRY RUN]" in capsys.readouterr().out
    dbm.dispose_engine()
    Storage._instance = None
    out = CliRunner().invoke(cli, ["-p", f"profile-{OWNER_A}", "memory-reindex-identifiers"])

    assert out.exit_code == 0, out.output
    assert "entities: 1  missing: 2  indexed: 0  (dry run" in out.output
    assert store_digest(COMPANY_A) == before


def test_compaction_never_touches_the_profiles_company_memory(world):
    """``owner_id`` is provenance: an entity or fact this profile wrote is company memory, not a rule."""
    entity = seeding.store_blob(world.storage, OWNER_A, f"user:{COMPANY_A}", RULE, "seed")
    twin = seeding.store_blob(world.storage, OWNER_A, f"user:{COMPANY_A}", RULE.upper(), "seed")
    fact = seeding.store_blob(world.storage, OWNER_A, f"facts:{COMPANY_A}", RULE, "seed")

    compaction().run([OWNER_A, EMAIL_A], apply=True, storage=world.storage)

    assert [namespace_of(b["id"]) for b in (entity, twin, fact)] == [
        f"user:{COMPANY_A}", f"user:{COMPANY_A}", f"facts:{COMPANY_A}"
    ]


def test_a_link_rebuild_that_changes_a_blob_is_rolled_back(world, monkeypatch):
    from sqlalchemy.orm import Session

    with get_session() as session:
        session.add(Email(id="mail-1", owner_id=EMAIL_A, gmail_id="g-1", thread_id="t", subject="x",
                          from_email="luca@alpha.example", date=datetime(2026, 9, 8)))
        session.commit()
    seeding.store_blob(world.storage, OWNER_A, f"user:{COMPANY_A}", LUCA, "Extracted from email mail-1 (x)")
    real = Session.merge

    def tampering(self, instance, *args, **kwargs):
        self.query(Blob).filter(Blob.id == world.longer).update({"content": "rewritten"})
        return real(self, instance, *args, **kwargs)

    monkeypatch.setattr(Session, "merge", tampering)
    before = blob_rows()

    assert rebuilds.rebuild_source_links()["failed"] == 1

    assert blob_rows() == before and rows(COMPANY_A, "SELECT COUNT(*) FROM email_blobs") == [(0,)]
