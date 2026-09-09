"""M2 — one memory store per company, several profiles on it.

Criteria proven here (numbers from the brief):

- C1   a fact learned from profile A's mailbox reaches profile B's agent
- C4   two REAL processes writing the same entity converge: no lost update
- C6   a blob merged away by one account leaves no dangling ledger id
- C8   a per-account reset under a shared store leaves company rows
- C9   two real processes booting on one company store; the split step is
       crash-atomic (kill between copy and drop, re-run converges)
- C12  a typed unknown key opens nothing and creates nothing on disk
- C14  the company self-notion is injected for every sharing profile
- C16  the boot backfill runs across the two files, per profile
- C17  the sweep runs once per company: the loser says so
- the vector index of one process sees another process's write
"""

from __future__ import annotations

import asyncio
from datetime import datetime
import json
import os
import sqlite3
import subprocess
import sys
import textwrap
from unittest.mock import MagicMock

import pytest
from sqlalchemy import text

from zylch.memory.blob_storage import BlobStorage
from zylch.memory.company_key import current_company_key, entity_namespace, mint_key
from zylch.memory.hybrid_search import HybridSearchEngine
from zylch.memory.store import MemoryUnavailable, memory_db_path, set_self_notion
from zylch.storage import database as dbm
from zylch.storage.database import get_session
from zylch.storage.migrations import applied_step_ids
from zylch.storage.step_memory_split import STEP_ID as SPLIT, copy_if_absent

PERSON = (
    "#IDENTIFIERS\nName: Giulia Verdi\nEmail: giulia@cliente.test\n"
    "#ABOUT\nRuns procurement for the Milan warehouse and negotiates pallet pricing.\n"
    "#HISTORY\n- agreed a payment plan in March"
)


# ─── booting profiles ────────────────────────────────────────


def _write_env(pdir, email, key, source):
    lines = [f"EMAIL_ADDRESS={email}", "ANTHROPIC_API_KEY=sk-ant-test"]
    if key:
        lines += [f"MEMORY_KEY={key}", f"MEMORY_KEY_SOURCE={source}"]
    (pdir / ".env").write_text("\n".join(lines) + "\n")


def _boot(monkeypatch, tmp_path, name, key, source):
    """Boot profile ``name`` in this process (the previous one is disposed)."""
    pdir = tmp_path / name
    pdir.mkdir(exist_ok=True)
    _write_env(pdir, f"{name}@company.test", key, source)
    monkeypatch.setenv("ZYLCH_PROFILE_DIR", str(pdir))
    monkeypatch.setenv("ZYLCH_DB_PATH", str(pdir / "zylch.db"))
    monkeypatch.setenv("EMAIL_ADDRESS", f"{name}@company.test")
    monkeypatch.setenv("MEMORY_KEY", key or "")
    monkeypatch.setenv("MEMORY_KEY_SOURCE", source or "")
    dbm.dispose_engine()
    dbm.init_db()
    return f"{name}@company.test"


@pytest.fixture
def stub_embedder(monkeypatch, embedder):
    import zylch.memory as memory_pkg
    import zylch.memory.embeddings as emb_mod

    monkeypatch.setattr(memory_pkg, "EmbeddingEngine", lambda *a, **k: embedder)
    monkeypatch.setattr(emb_mod, "EmbeddingEngine", lambda *a, **k: embedder)
    return embedder


def _legacy_profile_db(path: str, owner: str, n_blobs: int = 2) -> None:
    """A pre-split zylch.db: memory tables inside, no company_key column."""
    c = sqlite3.connect(path)
    c.executescript("""
        CREATE TABLE blobs (id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, namespace TEXT NOT NULL,
            content TEXT NOT NULL, embedding BLOB, events JSON, created_at DATETIME, updated_at DATETIME);
        CREATE TABLE blob_sentences (id TEXT PRIMARY KEY, blob_id TEXT NOT NULL REFERENCES blobs(id) ON DELETE CASCADE,
            owner_id TEXT NOT NULL, sentence_text TEXT NOT NULL, embedding BLOB NOT NULL, created_at DATETIME);
        """)
    for i in range(n_blobs):
        c.execute(
            "INSERT INTO blobs VALUES (?,?,?,?,X'00','[]',NULL,NULL)",
            (f"b{i}", owner, f"user:{owner}", f"#IDENTIFIERS\nName: P{i}\n#ABOUT\nlegacy {i}"),
        )
        c.execute(
            "INSERT INTO blob_sentences VALUES (?,?,?,?,X'00',NULL)",
            (f"s{i}", f"b{i}", owner, f"legacy {i}"),
        )
    c.commit()
    c.close()


def _profile_tables(db_path):
    c = sqlite3.connect(db_path)
    try:
        return {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        c.close()


def _store_count(key, sql):
    c = sqlite3.connect(memory_db_path(key))
    try:
        return c.execute(sql).fetchone()[0]
    finally:
        c.close()


# ─── the split itself (C9 for the company store) ─────────────


def test_split_moves_rows_out_of_the_profile_and_second_boot_is_a_noop(monkeypatch, tmp_path):
    pdir = tmp_path / "a"
    pdir.mkdir()
    _legacy_profile_db(str(pdir / "zylch.db"), "a@company.test")
    owner = _boot(monkeypatch, tmp_path, "a", key=None, source=None)  # MEMORY_KEY unset: mints
    key = current_company_key()
    assert key and os.path.isfile(memory_db_path(key))

    assert "blobs" not in _profile_tables(str(pdir / "zylch.db"))  # dropped, not frozen
    assert _store_count(key, "SELECT COUNT(*) FROM blobs") == 2
    assert _store_count(key, "SELECT COUNT(*) FROM blob_sentences") == 2
    assert _store_count(key, f"SELECT COUNT(*) FROM blobs WHERE namespace = 'user:{key}'") == 2
    assert _store_count(key, "SELECT COUNT(*) FROM memory_meta") == 1
    assert SPLIT in applied_step_ids(dbm.get_engine())

    with get_session() as s:  # binds: the ORM reads the store transparently
        from zylch.storage.models import Blob

        assert s.query(Blob).count() == 2 and s.query(Blob).first().owner_id == owner

    before = os.listdir(pdir / "backups")
    dbm.dispose_engine()
    dbm.init_db()
    assert _store_count(key, "SELECT COUNT(*) FROM blobs") == 2
    assert os.listdir(pdir / "backups") == before


def test_crash_between_copy_and_drop_converges_on_rerun(monkeypatch, tmp_path):
    """Simulate the crash: rows already copied into the store, tables not yet
    dropped, step not recorded. The re-run must not collide on the UUID PKs."""
    pdir = tmp_path / "a"
    pdir.mkdir()
    _legacy_profile_db(str(pdir / "zylch.db"), "a@company.test")
    key = mint_key()
    _write_env(pdir, "a@company.test", key, "mint")
    for k, v in {
        "ZYLCH_PROFILE_DIR": str(pdir),
        "ZYLCH_DB_PATH": str(pdir / "zylch.db"),
        "EMAIL_ADDRESS": "a@company.test",
        "MEMORY_KEY": key,
        "MEMORY_KEY_SOURCE": "mint",
    }.items():
        monkeypatch.setenv(k, v)
    dbm.dispose_engine()
    # half the step by hand: create the store and copy, drop nothing
    from zylch.memory.store import open_memory_engine, prepare_store

    store = open_memory_engine(key, create=True)
    prepare_store(store, key, created_by="mint")
    with dbm.get_engine().begin() as conn:
        conn.exec_driver_sql("ALTER TABLE blobs ADD COLUMN company_key TEXT")
        conn.exec_driver_sql("ALTER TABLE blob_sentences ADD COLUMN company_key TEXT")
        conn.exec_driver_sql("UPDATE blobs SET company_key = ?", (key,))
        conn.exec_driver_sql("UPDATE blob_sentences SET company_key = ?", (key,))
        copy_if_absent(conn, store)
    store.dispose()
    assert _store_count(key, "SELECT COUNT(*) FROM blobs") == 2

    dbm.dispose_engine()
    dbm.init_db()  # the "re-run"
    assert _store_count(key, "SELECT COUNT(*) FROM blobs") == 2  # not 4, no IntegrityError
    assert "blobs" not in _profile_tables(str(pdir / "zylch.db"))
    assert SPLIT in applied_step_ids(dbm.get_engine())


# ─── C1: sharing ─────────────────────────────────────────────


def test_fact_from_a_reaches_b(monkeypatch, tmp_path, stub_embedder):
    a = _boot(monkeypatch, tmp_path, "a", key=None, source=None)
    key = current_company_key()
    from zylch.services import facts_store

    facts_store.upsert_fact(a, "pricing", "MOQ", "500 units")
    BlobStorage(get_session, stub_embedder).store_blob(
        a, entity_namespace(key), PERSON, "extracted"
    )

    b = _boot(monkeypatch, tmp_path, "b", key=key, source="join")  # typed key, store exists
    assert dbm.memory_unavailable_reason() is None
    assert [f["content"] for f in facts_store.get_facts_by_category(b, "pricing")] == [
        "Category: pricing\nKey: MOQ\n500 units"
    ]
    hits = HybridSearchEngine(get_session, stub_embedder).search(
        b, "pallet procurement warehouse", limit=3
    )
    assert hits and "Giulia Verdi" in hits[0].content and hits[0].semantic_score > 0


# ─── C12 at the store layer ──────────────────────────────────


def test_typed_unknown_key_opens_nothing_and_creates_nothing(monkeypatch, tmp_path, stub_embedder):
    ghost = mint_key()
    _boot(monkeypatch, tmp_path, "a", key=ghost, source="join")
    assert dbm.memory_unavailable_reason()
    assert not os.path.exists(memory_db_path(ghost))
    with pytest.raises(MemoryUnavailable):
        BlobStorage(get_session, stub_embedder).list_blobs("a@company.test")
    # mail-side storage still works: memory being disabled is not an outage
    with get_session() as s:
        from zylch.storage.models import Email

        assert s.query(Email).count() == 0


# ─── C8 under the split ──────────────────────────────────────


def test_per_account_reset_under_shared_store_keeps_company_rows(
    monkeypatch, tmp_path, stub_embedder
):
    a = _boot(monkeypatch, tmp_path, "a", key=None, source=None)
    key = current_company_key()
    store = BlobStorage(get_session, stub_embedder)
    a_entity = store.store_blob(a, entity_namespace(key), PERSON, "x")["id"]
    b = _boot(monkeypatch, tmp_path, "b", key=key, source="join")
    store = BlobStorage(get_session, stub_embedder)
    store.store_blob(b, f"template:{b}", "B's rule", "x")
    b_entity = store.store_blob(b, entity_namespace(key), PERSON.replace("Giulia", "Marco"), "x")[
        "id"
    ]
    assert store.delete_all_blobs(b) == 1  # the rule only
    assert store.get_blob(a_entity, b) and store.get_blob(b_entity, b)


# ─── C6: aliases resolve stale ledger ids ────────────────────


def test_alias_resolves_a_merged_away_id_in_the_task_ledger(monkeypatch, tmp_path):
    a = _boot(monkeypatch, tmp_path, "a", key=None, source=None)
    from zylch.storage.models import BlobAlias, TaskItem
    from zylch.storage.storage import Storage

    with get_session() as s:
        s.add(BlobAlias(merged_id="old-blob", keeper_id="keeper-blob"))
        s.add(
            TaskItem(
                owner_id=a,
                event_id="evt-1",
                contact_email="x@y.test",
                action_required=True,
                sources={"blobs": ["old-blob"]},
                event_type="email",
            )
        )
    found = Storage.get_instance().get_open_tasks_by_blobs(a, ["keeper-blob"])
    assert len(found) == 1
    assert len(Storage.get_instance().get_open_tasks_by_blobs(a, ["old-blob"])) == 1


# ─── the solve agent's task context hydrates through the wall and aliases ──


def test_task_context_hydrates_another_accounts_entity_and_aliases(
    monkeypatch, tmp_path, stub_embedder
):
    a = _boot(monkeypatch, tmp_path, "a", key=None, source=None)
    key = current_company_key()
    keeper = BlobStorage(get_session, stub_embedder).store_blob(
        a, entity_namespace(key), PERSON, "x"
    )["id"]
    from zylch.services.solve_constants import build_task_context
    from zylch.storage.models import BlobAlias

    with get_session() as s:
        s.add(BlobAlias(merged_id="gone-blob", keeper_id=keeper))
    b = _boot(monkeypatch, tmp_path, "b", key=key, source="join")
    # B's task ledger names an id that A's sweep merged away
    ctx = build_task_context(
        {"sources": {"blobs": ["gone-blob"]}}, [], b
    )  # (task, store, owner_id)
    assert "CONTACT MEMORY" in ctx and "Giulia Verdi" in ctx


def test_join_of_own_key_attaches_a_store_that_appeared_later(monkeypatch, tmp_path, stub_embedder):
    """A typed key with no store: memory unavailable, nothing created. The
    colleague mints that key later. The running daemon joins its own key
    and is attached — no restart."""
    from zylch.memory.join import join
    from zylch.memory.store import open_memory_engine, prepare_store

    key = mint_key()
    b = _boot(monkeypatch, tmp_path, "b", key=key, source="join")
    assert dbm.memory_unavailable_reason()
    store = open_memory_engine(key, create=True)  # the colleague's mint
    prepare_store(store, key, created_by="mint")
    store.dispose()
    out = join(key)
    assert out["ok"] and out.get("already") and out.get("attached")
    assert dbm.memory_unavailable_reason() is None
    assert BlobStorage(get_session, stub_embedder).list_blobs(b) == []


@pytest.mark.asyncio
async def test_worker_spends_no_llm_call_while_memory_is_unavailable(monkeypatch, tmp_path):
    from zylch.storage.storage import Storage
    from zylch.workers.memory import MemoryWorker

    _boot(monkeypatch, tmp_path, "b", key=mint_key(), source="join")
    assert dbm.memory_unavailable_reason()
    w = MemoryWorker.__new__(MemoryWorker)
    w.owner_id = "b@company.test"
    w.storage = Storage.get_instance()
    w.client = MagicMock()
    ok = await w.process_email(
        {"id": "m1", "from_email": "x@y.test", "subject": "s", "body_plain": "b"}
    )
    assert ok is False and not w.client.create_message.called and not w.client.method_calls


# ─── C14: one self-notion for everyone ───────────────────────


def test_self_notion_is_injected_for_every_profile(monkeypatch, tmp_path):
    _boot(monkeypatch, tmp_path, "a", key=None, source=None)
    key = current_company_key()
    set_self_notion(dbm.current_memory_engine(), "Café 124, Milan — roasting and wholesale")
    from zylch.workers.memory import MemoryWorker

    for name in ("a", "b"):
        _boot(monkeypatch, tmp_path, name, key=key, source="join" if name == "b" else "mint")
        w = MemoryWorker.__new__(MemoryWorker)
        w.owner_id = f"{name}@company.test"
        w.storage = MagicMock()
        w.storage.get_agent_prompt.return_value = (
            "BASE PROMPT\n- USER_COMPANY: whatever this profile inferred"
        )
        w._custom_prompt_loaded = False
        prompt = w._get_extraction_prompt()
        assert "COMPANY SELF-NOTION" in prompt and "Café 124, Milan" in prompt


# ─── C17: one sweep per company ──────────────────────────────


def test_sweep_is_skipped_while_another_engine_holds_it(monkeypatch, tmp_path):
    a = _boot(monkeypatch, tmp_path, "a", key=None, source=None)
    from zylch.memory.llm_merge import reconsolidate_now
    from zylch.storage.migrations import db_file_lock

    with db_file_lock(memory_db_path(current_company_key()), suffix=".sweep.lock"):
        # force: the change-gating (tested elsewhere) must not short-circuit
        # before the lock, which is what this proves
        summary = asyncio.run(reconsolidate_now(a, force=True))
    assert summary["skipped"] is True and summary["reason"] == "another engine is sweeping"


# ─── C16: the backfill across two files ──────────────────────


def test_backfill_links_this_profiles_mail_to_company_blobs(monkeypatch, tmp_path, stub_embedder):
    a = _boot(monkeypatch, tmp_path, "a", key=None, source=None)
    key = current_company_key()
    from zylch.storage.models import Email, EmailBlob

    with get_session() as s:
        s.add(
            Email(
                id="mail-1",
                owner_id=a,
                gmail_id="g-1",
                thread_id="t",
                subject="x",
                from_email="g@c.test",
                date=datetime(2026, 9, 8),
            )
        )
    BlobStorage(get_session, stub_embedder).store_blob(
        a, entity_namespace(key), PERSON, "Extracted from email mail-1 (2026-09-08)"
    )
    with get_session() as s:
        s.query(EmailBlob).delete()  # pretend the index was never written
    # Through a REAL second boot, not by calling the backfill directly: the
    # backfill reads Blob from the store and Email from the profile, and it
    # must find the store attached when it runs (it did not, once).
    dbm.dispose_engine()
    dbm.init_db()
    with get_session() as s:
        row = s.query(EmailBlob).one()
        assert row.email_id == "mail-1" and row.owner_id == a and row.company_key == key


# ─── Two real processes ──────────────────────────────────────

_BOOT = textwrap.dedent("""
    import json, os, sys
    pdir, key = sys.argv[1], sys.argv[2]
    os.makedirs(pdir, exist_ok=True)
    open(os.path.join(pdir, ".env"), "w").write(
        f"EMAIL_ADDRESS={os.path.basename(pdir)}@c.test\\nMEMORY_KEY={key}\\nMEMORY_KEY_SOURCE=provision\\n")
    os.environ.update({"ZYLCH_PROFILE_DIR": pdir, "ZYLCH_DB_PATH": os.path.join(pdir, "zylch.db"),
        "EMAIL_ADDRESS": f"{os.path.basename(pdir)}@c.test", "MEMORY_KEY": key, "MEMORY_KEY_SOURCE": "provision"})
    from zylch.storage import database as dbm
    dbm.init_db()
    from zylch.storage.migrations import applied_step_ids
    print(json.dumps({"pid": os.getpid(), "steps": sorted(applied_step_ids(dbm.get_engine())),
                      "memory": dbm.memory_unavailable_reason()}))
    """)

_CAS_WRITER = textwrap.dedent("""
    import json, os, sys, time
    import numpy as np
    pdir, key, blob_id, marker, hold = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], float(sys.argv[5])
    os.environ.update({"ZYLCH_PROFILE_DIR": pdir, "ZYLCH_DB_PATH": os.path.join(pdir, "zylch.db"),
        "EMAIL_ADDRESS": "w@c.test", "MEMORY_KEY": key, "MEMORY_KEY_SOURCE": "join"})
    from zylch.storage import database as dbm
    dbm.init_db()
    from zylch.storage.database import get_session
    from zylch.memory.blob_storage import BlobStorage
    class E:
        def encode(self, t):
            if isinstance(t, str): return np.ones(8, dtype=np.float32)
            return np.ones((len(t), 8), dtype=np.float32)
    bs = BlobStorage(get_session, E())
    attempts = 0
    for attempt in range(5):
        cur = bs.get_blob(blob_id, "w@c.test")
        time.sleep(hold)  # the "LLM merge": long enough for the other writer to interleave
        merged = cur["content"] + "\\n- " + marker
        out = bs.update_blob(blob_id, "w@c.test", merged, "cas", expected_updated_at=cur["updated_at"])
        attempts += 1
        if not out.get("conflict"):
            break
    print(json.dumps({"attempts": attempts, "conflicted": attempts > 1}))
    """)

_INSERTER = textwrap.dedent("""
    import os, sys
    import numpy as np
    pdir, key = sys.argv[1], sys.argv[2]
    os.environ.update({"ZYLCH_PROFILE_DIR": pdir, "ZYLCH_DB_PATH": os.path.join(pdir, "zylch.db"),
        "EMAIL_ADDRESS": "w@c.test", "MEMORY_KEY": key, "MEMORY_KEY_SOURCE": "join"})
    from zylch.storage import database as dbm
    dbm.init_db()
    from zylch.storage.database import get_session
    from zylch.memory.blob_storage import BlobStorage
    import hashlib, re
    class E:
        def _one(self, text):
            v = np.zeros(384, dtype=np.float32)
            for tok in re.findall(r"[a-z0-9@.+]+", text.lower()):
                v[int(hashlib.md5(tok.encode()).hexdigest(), 16) % 384] += 1.0
            return v
        def encode(self, t):
            return self._one(t) if isinstance(t, str) else np.array([self._one(x) for x in t])
    BlobStorage(get_session, E()).store_blob("w@c.test", f"user:{key}", "#IDENTIFIERS\\nName: Late Arrival\\n#ABOUT\\nzeta", "x")
    print("inserted")
    """)


def _run(script, *args, env_extra=None, timeout=120):
    env = dict(os.environ)
    env.update(env_extra or {})
    p = subprocess.run(
        [sys.executable, "-c", script, *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=timeout,
    )
    assert p.returncode == 0, p.stderr
    return p.stdout.strip().splitlines()[-1]


def test_two_processes_boot_on_one_company_store(tmp_path, monkeypatch):
    key = mint_key()
    monkeypatch.setenv("MEMORY_DB_DIR", str(tmp_path / "memory"))
    procs = [
        subprocess.Popen(
            [sys.executable, "-c", _BOOT, str(tmp_path / f"p{i}"), key],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=dict(os.environ),
        )
        for i in range(2)
    ]
    outs = []
    for p in procs:
        out, err = p.communicate(timeout=120)
        assert p.returncode == 0, err
        outs.append(json.loads(out.strip().splitlines()[-1]))
    assert all(o["memory"] is None for o in outs), outs
    assert all(SPLIT in o["steps"] for o in outs)
    assert _store_count(key, "SELECT COUNT(*) FROM memory_meta") == 1  # created once, not twice
    assert len([f for f in os.listdir(tmp_path / "memory") if f.endswith(".db")]) == 1


def test_two_processes_writing_one_entity_converge_without_lost_update(
    monkeypatch, tmp_path, stub_embedder
):
    a = _boot(monkeypatch, tmp_path, "a", key=None, source=None)
    key = current_company_key()
    blob_id = BlobStorage(get_session, stub_embedder).store_blob(
        a, entity_namespace(key), PERSON, "x"
    )["id"]
    env = {"MEMORY_DB_DIR": os.environ["MEMORY_DB_DIR"]}
    pw = str(tmp_path / "writer")
    os.makedirs(pw, exist_ok=True)
    (tmp_path / "writer" / ".env").write_text(
        f"EMAIL_ADDRESS=w@c.test\nMEMORY_KEY={key}\nMEMORY_KEY_SOURCE=join\n"
    )
    procs = [
        subprocess.Popen(
            [sys.executable, "-c", _CAS_WRITER, pw, key, blob_id, marker, hold],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env={**os.environ, **env},
        )
        for marker, hold in (("first writer", "1.0"), ("second writer", "1.5"))
    ]
    results = []
    for p in procs:
        out, err = p.communicate(timeout=120)
        assert p.returncode == 0, err
        results.append(json.loads(out.strip().splitlines()[-1]))
    content = BlobStorage(get_session, stub_embedder).get_blob(blob_id, a)["content"]
    assert "first writer" in content and "second writer" in content, content
    assert any(r["conflicted"] for r in results), results  # the race was real and detected


def test_index_of_one_process_sees_another_processs_write(monkeypatch, tmp_path, stub_embedder):
    a = _boot(monkeypatch, tmp_path, "a", key=None, source=None)
    key = current_company_key()
    search = HybridSearchEngine(get_session, stub_embedder)
    assert search.search(a, "zeta", limit=3) == []  # index loaded, empty
    pw = str(tmp_path / "writer")
    os.makedirs(pw, exist_ok=True)
    _run(_INSERTER, pw, key, env_extra={"MEMORY_DB_DIR": os.environ["MEMORY_DB_DIR"]})
    hits = search.search(a, "zeta", limit=3)  # no invalidate_cache() call
    assert [h.content.split("\n")[1] for h in hits] == ["Name: Late Arrival"]


# ─── C10 shape: nothing returns a path ───────────────────────


def test_no_memory_rpc_returns_a_filesystem_path(monkeypatch, tmp_path):
    _boot(monkeypatch, tmp_path, "a", key=None, source=None)
    from zylch.rpc.memory_join import memory_join, memory_join_preview, memory_status

    async def _all():
        return [
            await memory_status({}, lambda *a: None),
            await memory_join_preview({"key": current_company_key()}, lambda *a: None),
            await memory_join({"key": "nope"}, lambda *a: None),
        ]

    for payload in asyncio.run(_all()):
        blob = json.dumps(payload)
        assert str(tmp_path) not in blob and ".db" not in blob, blob
    _ = text
