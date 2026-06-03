"""Tests for category-gated business facts.

The headline guarantee is "all and ONLY": a request about white-label
production must never pull private-label facts (they embed almost
identically — exact category membership is what keeps them apart).
DB/embedding paths are monkeypatched out; this checks the logic.
"""

from __future__ import annotations

import zylch.services.facts_store as fs
import zylch.services.solve_tools as st
import zylch.workers.memory as mw

# ─── pure parsers ─────────────────────────────────────


def test_parse_fields_and_format():
    content = "Category: white-label\nKey: Minimum order\nValue: 500 units"
    assert fs.parse_category(content) == "white-label"
    assert fs.parse_key(content) == "Minimum order"
    assert fs.parse_value(content) == "500 units"
    assert fs.format_fact("A", "B", "C") == "Category: A\nKey: B\nC"


def test_parse_value_multiline():
    content = "Category: x\nKey: y\nValue: line1\nline2"
    assert fs.parse_value(content) == "line1\nline2"


# ─── all-and-only retrieval (the cafe-124 guarantee) ──


_BLOBS = [
    {"blob_id": "1", "content": "Category: white-label\nKey: MOQ\n500 units"},
    {"blob_id": "2", "content": "Category: private-label\nKey: MOQ\n100 units"},
    {"blob_id": "3", "content": "Category: white-label\nKey: Lead time\n6 weeks"},
]


def test_get_by_category_is_exact_all_and_only(monkeypatch):
    monkeypatch.setattr(fs, "_all_fact_blobs", lambda owner_id: _BLOBS)
    got = fs.get_facts_by_category("o", "white-label")
    assert {g["blob_id"] for g in got} == {"1", "3"}  # all white-label
    assert "2" not in {g["blob_id"] for g in got}  # and only — no private-label


def test_get_by_category_case_insensitive(monkeypatch):
    monkeypatch.setattr(fs, "_all_fact_blobs", lambda owner_id: _BLOBS)
    assert len(fs.get_facts_by_category("o", "WHITE-LABEL")) == 2


def test_list_categories_counts(monkeypatch):
    monkeypatch.setattr(fs, "_all_fact_blobs", lambda owner_id: _BLOBS)
    cats = {c["category"]: c["count"] for c in fs.list_categories("o")}
    assert cats == {"white-label": 2, "private-label": 1}


# ─── solver tool dispatch ─────────────────────────────


def test_tool_list_fact_categories(monkeypatch):
    monkeypatch.setattr(fs, "list_categories", lambda o: [{"category": "white-label", "count": 2}])
    out = st.execute_tool("list_fact_categories", {}, None, "o")
    assert "white-label" in out and "2 fact" in out


def test_tool_get_facts_by_category(monkeypatch):
    monkeypatch.setattr(
        fs,
        "get_facts_by_category",
        lambda o, c: [
            {"blob_id": "1", "key": "MOQ", "content": "Category: white-label\nKey: MOQ\n500 units"}
        ],
    )
    out = st.execute_tool("get_facts_by_category", {"category": "white-label"}, None, "o")
    assert "500 units" in out


def test_tool_get_facts_requires_category():
    assert "No category" in st.execute_tool("get_facts_by_category", {}, None, "o")


# ─── worker FACT routing ──────────────────────────────


def test_entity_type_detection():
    assert mw._entity_type("Entity type: FACT\nCategory: x") == "FACT"
    assert mw._entity_type("#IDENTIFIERS\nEntity type: PERSON\nName: A") == "PERSON"
    assert mw._entity_type("no type here") == ""


def test_fact_entity_routes_to_upsert(monkeypatch):
    calls = []
    monkeypatch.setattr(
        fs, "upsert_fact", lambda o, cat, k, v: calls.append((o, cat, k, v)) or "blob-x"
    )

    class _W:
        owner_id = "o1"

    mw.MemoryWorker._upsert_fact_entity(
        _W(),
        "Entity type: FACT\nCategory: white-label\nKey: MOQ\nValue: 500 units",
    )
    assert calls == [("o1", "white-label", "MOQ", "500 units")]
