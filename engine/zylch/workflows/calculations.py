import json
import re
from typing import Any
from decimal import Decimal, InvalidOperation, localcontext

from .errors import WorkflowError

_AMOUNT = re.compile(r"-?(?:0|[1-9][0-9]{0,17})(?:\.[0-9]{1,8})?\Z")
_TREATMENTS = {"observed", "estimate", "scenario", "exclude", "overlap"}


def _amount(value: Any) -> Decimal:
    if not isinstance(value, str) or not _AMOUNT.fullmatch(value):
        raise ValueError
    return Decimal(value)


def _text(value: Any) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 2000:
        raise ValueError
    return value


def _rows(rows: Any) -> list[dict[str, Any]]:
    if not isinstance(rows, list) or len(rows) > 10000:
        raise ValueError
    identities = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) - {
            "id",
            "source_ids",
            "identity",
            "amount",
            "currency",
            "period",
            "category",
            "treatment",
            "reason",
            "related_ids",
        }:
            raise ValueError
        _text(row["id"])
        _text(row["identity"])
        _text(row["currency"])
        _text(row["period"])
        _text(row["category"])
        _amount(row["amount"])
        if row["id"] in identities:
            raise ValueError
        identities.add(row["id"])
        sources = row["source_ids"]
        if (
            not isinstance(sources, list)
            or not 1 <= len(sources) <= 100
            or any(not isinstance(s, str) for s in sources)
        ):
            raise ValueError
        for source in sources:
            _text(source)
        if row["treatment"] not in _TREATMENTS:
            raise ValueError
        if row["treatment"] != "observed":
            _text(row["reason"])
        related = row.get("related_ids", [])
        if not isinstance(related, list) or len(related) > 100:
            raise ValueError
        for identifier in related:
            _text(identifier)
        if row["treatment"] == "overlap" and not related:
            raise ValueError
    economic = set()
    for row in rows:
        if any(
            identifier not in identities or identifier == row["id"]
            for identifier in row.get("related_ids", [])
        ):
            raise ValueError
        if row["treatment"] in {"observed", "estimate", "scenario"}:
            key = (
                row["identity"],
                row["currency"],
                row["period"],
                row["category"],
                row["treatment"],
            )
            if key in economic:
                raise ValueError
            economic.add(key)
    return rows


def _totals(rows: list[dict[str, Any]], group_by: list[str]) -> list[dict[str, str]]:
    totals = {}
    for row in rows:
        if row["treatment"] in {"exclude", "overlap"}:
            continue
        key = tuple(row[field] for field in group_by)
        totals[key] = totals.get(key, Decimal(0)) + _amount(row["amount"])
    return [
        {**dict(zip(group_by, key)), "amount": str(value)} for key, value in sorted(totals.items())
    ]


def calculate(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        if not isinstance(payload, dict):
            raise ValueError
        snapshot = json.loads(json.dumps(payload, allow_nan=False))
        with localcontext() as context:
            context.prec = 60
            result = _calculate(snapshot)
        return {"schema_version": 1, "inputs": snapshot, "result": result}
    except (ValueError, TypeError, KeyError, InvalidOperation, ZeroDivisionError, OverflowError):
        raise WorkflowError("invalid_calculation_inputs") from None


def _calculate(payload: dict[str, Any]) -> dict[str, Any]:
    operation = payload["operation"]
    if operation in {"sum", "group", "reconcile", "roll_forward"}:
        allowed = {"operation", "rows", "group_by", "opening", "closing"}
        if set(payload) - allowed:
            raise ValueError
        rows = _rows(payload["rows"])
        if operation in {"sum", "group"}:
            group_by = payload.get("group_by", [])
            if (
                not isinstance(group_by, list)
                or len(set(group_by)) != len(group_by)
                or any(field not in {"period", "category", "currency"} for field in group_by)
            ):
                raise ValueError
            fields = ["currency", "treatment"] + [
                field for field in group_by if field != "currency"
            ]
            return {
                "totals": _totals(rows, fields),
                "excluded_ids": [r["id"] for r in rows if r["treatment"] in {"exclude", "overlap"}],
            }
        if len({r["currency"] for r in rows}) > 1 or any(
            r["treatment"] in {"estimate", "scenario"} for r in rows
        ):
            raise ValueError
        movements = sum(
            (_amount(r["amount"]) for r in rows if r["treatment"] == "observed"), Decimal(0)
        )
        opening = payload.get("opening")
        closing = payload.get("closing")
        expected = None if opening is None else _amount(opening) + movements
        difference = None if expected is None or closing is None else _amount(closing) - expected
        return {
            "status": (
                "incomplete"
                if difference is None
                else "reconciled" if difference == 0 else "difference"
            ),
            "movements": str(movements),
            "expected_closing": None if expected is None else str(expected),
            "difference": None if difference is None else str(difference),
            "missing": [key for key in ("opening", "closing") if payload.get(key) is None],
        }
    if operation == "variance":
        if set(payload) != {"operation", "current", "prior"}:
            raise ValueError
        current, prior = _amount(payload["current"]), _amount(payload["prior"])
        return {
            "absolute": str(current - prior),
            "percentage": None if prior == 0 else str((current - prior) / abs(prior) * 100),
            "percentage_status": "undefined_zero_base" if prior == 0 else "defined",
        }
    if operation in {"add", "subtract", "multiply", "divide", "ratio"}:
        if set(payload) != {"operation", "left", "right"}:
            raise ValueError
        left, right = _amount(payload["left"]), _amount(payload["right"])
        if operation in {"divide", "ratio"} and right == 0:
            return {"amount": None, "status": "undefined_zero_base"}
        amount = {
            "add": lambda: left + right,
            "subtract": lambda: left - right,
            "multiply": lambda: left * right,
            "divide": lambda: left / right,
            "ratio": lambda: left / right,
        }[operation]()
        return {"amount": str(amount), "status": "defined"}
    raise ValueError
