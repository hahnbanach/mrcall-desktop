"""A measured role's authored case set: its ``cases.json`` and the cases trimmed into reserve.

IR2's spend rule may reduce the cases a role is measured on
(``scripts/trim_measurement_cases.py``): the cases it does not measure move
from ``<ROLE>/cases.json`` to ``<ROLE>/reserve.json``, so the one-off
measurement and the daily job read the same, smaller ``cases.json`` (and its
``requests.json``, captured from it). The **authored** set is both files
together, in the order the cases were written: what the label review covered
and what the case files' own tests hold — schema, numbering, labels, balance,
synthetic data. A capture, a replay and a hash read ``cases.json`` alone.

``reserve.json`` is ``{"schema": 1, "role", "rule", "kept", "order": [every
authored id, in authored order], "cases": [each reserve case, as it was
written in cases.json]}``; there is none while every case is measured.
"""

from __future__ import annotations

import json
from pathlib import Path

RESERVE = "reserve.json"


def load_reserve(role_dir: Path) -> dict | None:
    """The role's ``reserve.json``, or None when every authored case is measured."""
    path = Path(role_dir) / RESERVE
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def authored_document(role_dir: Path) -> dict:
    """The role's ``cases.json`` document with its reserve cases back in authored order.

    Raises ``ValueError`` when the two files do not make up the authored order
    the reserve records (a case written into ``cases.json`` after a trim:
    restore the reserve first).
    """
    document = json.loads((Path(role_dir) / "cases.json").read_text(encoding="utf-8"))
    reserve = load_reserve(role_dir)
    if reserve is None:
        return document
    cases = document["cases"] + reserve["cases"]
    order = {case_id: n for n, case_id in enumerate(reserve["order"])}
    if sorted(order) != sorted(case["id"] for case in cases) or len(order) != len(cases):
        raise ValueError(f"{role_dir}: cases.json and {RESERVE} are not the order it records")
    return {**document, "cases": sorted(cases, key=lambda case: order[case["id"]])}
