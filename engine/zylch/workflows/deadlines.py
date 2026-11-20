from datetime import date
from importlib import import_module
from typing import Any

from .errors import WorkflowError

calculate = import_module("zylch.workflows.bundles.cs-legal-research.scripts.count_days").calculate


def calculate_deadline(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        if not isinstance(payload, dict) or set(payload) - {
            "trigger",
            "days",
            "include_trigger",
            "excluded_intervals",
            "expiry_holidays",
            "expiry_weekdays",
        }:
            raise ValueError
        if type(payload.get("days")) is not int or not 1 <= payload["days"] <= 36600:
            raise ValueError
        if type(payload.get("include_trigger", False)) is not bool:
            raise ValueError

        def parse(value: Any) -> date:
            if not isinstance(value, str) or len(value) != 10:
                raise ValueError
            return date.fromisoformat(value)

        lists = [
            payload.get(key, [])
            for key in ("excluded_intervals", "expiry_holidays", "expiry_weekdays")
        ]
        if any(not isinstance(value, list) or len(value) > 100 for value in lists):
            raise ValueError
        intervals, holidays, weekdays = lists
        if len(intervals) > 100 or len(weekdays) > 7:
            raise ValueError
        if any(not isinstance(pair, list) or len(pair) != 2 for pair in intervals):
            raise ValueError
        if any(type(day) is not int or day not in range(7) for day in weekdays):
            raise ValueError
        return calculate(
            parse(payload["trigger"]),
            payload["days"],
            payload.get("include_trigger", False),
            [(parse(a), parse(b)) for a, b in intervals],
            set(map(parse, holidays)),
            set(weekdays),
        )
    except (ValueError, OverflowError, KeyError, TypeError):
        raise WorkflowError("invalid_deadline_inputs") from None
