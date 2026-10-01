"""The model-name boundary (milestone 10a, brief D6): no model is named outside a reviewed manifest.

Milestone 10 moves the choice of model from names written in code to
requirements resolved into a table (``zylch/llm/roles/``). That move is only
real if a name cannot creep back as a default, so this file freezes where a
model name may occur under ``zylch/``, as the memory write boundary
(``tests/memory/test_mnemonic_write_boundary.py``) freezes who may write
company memory:

- every occurrence of a model name (``model_inventory_scan.MODEL_NAME``:
  ``claude-``, the OpenRouter vendor prefixes, ``gpt-``, dated snapshot ids)
  on a non-comment line must be covered by a row of
  ``tests/fixtures/llm/model_name_inventory.json`` with the same file and
  literal — or lie in one of the two files allowed whole by exact path, the
  role files the resolver reads and writes (``requirements.json``,
  ``resolved.json``); the resolver's code beside them is held to rows like any
  other file, docstrings included. Rows match by ``(file, literal)`` with multiplicity; their line is
  informational, so an edit elsewhere in a file does not break the test, but
  a second copy of an allowed name in the same file does;
- every row must be exercised: its literal still occurs in its file as often
  as the manifest says. A retired name forces its row's deletion, so the
  manifest never keeps an allowance nothing uses.

Each row carries the purpose that justifies it (``default``, ``adapter``,
``price``, ``snapshot``, ``placeholder``, ``label``, ``doc``). The ``default``
rows are today's names and are expected to go as the roster lands; the
``adapter`` and ``snapshot`` rows are the per-model protocol rules the brief
keeps. The voice module and ``openai_voice`` are out of scope by rule: listed
with purpose ``voice``, never scanned. Adding a row is a reviewed change.

The vendor prefixes are every ``<vendor>/`` of the OpenRouter catalogue
fixture the resolver reads (``tests/fixtures/llm/resolver/models.json``),
plus the seven the engine named before it, so a refreshed fixture with a new
vendor extends the guard by itself.

Known limits — this guards against accidents, not deliberate evasion:

- matching is by ``(file, literal, count)``: a row's purpose is not bound to
  its line, so a ``doc`` name moved into code in the same file, or a retired
  default replaced by the same name elsewhere in the file, still passes;
- the scan is case-sensitive and textual: ``CLAUDE-HAIKU-4-5``, a name built
  by string concatenation or formatting (``"claude-" + "haiku-4-5"``), read
  from an environment variable or a file outside ``zylch/``, or under a
  vendor neither known nor in the fixture, is not seen;
- a comment-only line is skipped, so a name there is invisible, which is
  harmless only because a comment cannot choose a model.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from .model_inventory_scan import (
    KNOWN_VENDORS,
    MODEL_NAME,
    catalogue_vendors,
    model_name_pattern,
    model_names,
    text_files,
)

ENGINE_ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ENGINE_ROOT / "tests" / "fixtures" / "llm" / "model_name_inventory.json"
PURPOSES = frozenset(
    {"default", "adapter", "price", "snapshot", "placeholder", "label", "doc", "voice"}
)
# The two files the brief allows whole: the requirements and the resolved table.
ROLE_FILES = ("zylch/llm/roles/requirements.json", "zylch/llm/roles/resolved.json")
# Out of scope by rule; their rows are listed with purpose ``voice``.
VOICE = ("zylch/services/voice/", "zylch/llm/openai_voice.py")


def _manifest() -> dict:
    return json.loads(MANIFEST.read_text())


def _out_of_scope(rel: str, manifest: dict) -> bool:
    return rel.startswith(tuple(manifest["out_of_scope"]))


def _occurrences(manifest: dict) -> list[tuple[str, int, str]]:
    """``(file, line, literal)`` for every model name in scope under ``zylch/``."""
    found: list[tuple[str, int, str]] = []
    for path in text_files(ENGINE_ROOT / manifest["scope"]):
        rel = path.relative_to(ENGINE_ROOT).as_posix()
        if _out_of_scope(rel, manifest) or rel in manifest["path_allowances"]:
            continue
        found.extend((rel, line, literal) for line, literal in model_names(path))
    return found


def _allowed(manifest: dict) -> Counter:
    return Counter(
        (row["file"], row["literal"])
        for row in manifest["allowances"]
        if not _out_of_scope(row["file"], manifest)
    )


def test_the_manifest_states_the_reviewed_scope():
    manifest = _manifest()
    assert manifest["scope"] == "zylch"
    assert tuple(manifest["path_allowances"]) == ROLE_FILES
    assert tuple(manifest["out_of_scope"]) == VOICE


def test_every_row_names_a_known_purpose_and_voice_rows_only_out_of_scope():
    manifest = _manifest()
    for row in manifest["allowances"]:
        assert row["purpose"] in PURPOSES, row
        assert (row["purpose"] == "voice") == _out_of_scope(row["file"], manifest), row
        assert MODEL_NAME.fullmatch(row["literal"]), f"not a model name by the scanner: {row}"


def test_every_model_name_under_zylch_is_allowed():
    manifest = _manifest()
    allowed = _allowed(manifest)
    occurrences = _occurrences(manifest)
    excess = Counter((rel, literal) for rel, _, literal in occurrences) - allowed
    unlisted = [
        f"{rel}:{line}: {literal!r}"
        for rel, line, literal in occurrences
        if (rel, literal) in excess
    ]
    assert not excess, (
        "model name outside the manifest (tests/fixtures/llm/model_name_inventory.json); "
        "a model is chosen by zylch/llm/roles/, not named in code — "
        f"unallowed occurrences {dict(excess)} among:\n  " + "\n  ".join(unlisted)
    )


def test_every_allowance_is_exercised():
    manifest = _manifest()
    found = Counter((rel, literal) for rel, _, literal in _occurrences(manifest))
    missing = _allowed(manifest) - found
    stale = [
        f"{row['file']}:{row['line']}: {row['literal']!r} ({row['purpose']})"
        for row in manifest["allowances"]
        if (row["file"], row["literal"]) in missing
    ]
    assert not missing, (
        "allowance no longer exercised — the name left its file (or occurs fewer times); "
        f"delete its row from the manifest. Short by {dict(missing)}; rows:\n  "
        + "\n  ".join(stale)
    )


@pytest.mark.parametrize(
    "line, names",
    [
        ('default="claude-haiku-4-6",', ["claude-haiku-4-6"]),
        ('MODEL = "qwen/qwen3.8-max"', ["qwen/qwen3.8-max"]),
        (
            '{"id": "x-ai/grok-4.7", "alt": "google/gemini-3.8-flash"}',
            ["x-ai/grok-4.7", "google/gemini-3.8-flash"],
        ),
        ('f"{base}-20270101"  # snapshot', []),
        ('"claude-sonnet-4-5-20250929"', ["claude-sonnet-4-5-20250929"]),
        ('model="gpt-6-sol"', ["gpt-6-sol"]),
        ('CALLBACK_PATH = "/oauth2/google/callback"', []),
        ('"""Run the bounded GPT-Live SIP test (Google/Microsoft)."""', []),
        ("    # default = 'claude-haiku-4-5'", []),
        ("x = pick()  # was claude-haiku-4-5", ["claude-haiku-4-5"]),
        (
            '"xiaomi/mimo-v2.6-flash", "deepseek/deepseek-v4"',
            ["xiaomi/mimo-v2.6-flash", "deepseek/deepseek-v4"],
        ),
        (
            '"bytedance-seed/seed-2.0", "~anthropic/claude-opus-latest"',
            ["bytedance-seed/seed-2.0", "~anthropic/claude-opus-latest"],
        ),
    ],
)
def test_the_scanner_finds_ids_and_skips_prose_paths_and_comment_lines(tmp_path, line, names):
    path = tmp_path / "probe.py"
    path.write_text(line + "\n")
    assert [literal for _, literal in model_names(path)] == names


def test_every_vendor_of_the_catalogue_fixture_is_guarded():
    vendors = catalogue_vendors()
    assert len(vendors) >= 20, "the catalogue fixture lost its vendors"
    for vendor in sorted(vendors | KNOWN_VENDORS):
        literal = f"{vendor}/some-model-1.0"
        assert MODEL_NAME.fullmatch(literal), f"vendor not matched by the scanner: {vendor}"


def test_a_vendor_added_to_a_refreshed_fixture_extends_the_guard(tmp_path):
    fixture = tmp_path / "models.json"
    fixture.write_text(
        json.dumps({"data": [{"id": "newlab/frontier-9"}, {"id": "openrouter-auto"}]})
    )
    vendors = catalogue_vendors(fixture)
    assert vendors == {"newlab"}
    assert not MODEL_NAME.search('"newlab/frontier-9"')
    assert model_name_pattern(vendors).search('"newlab/frontier-9"').group(0) == "newlab/frontier-9"
