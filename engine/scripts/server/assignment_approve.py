#!/usr/bin/env python3
"""Host operator: review one exported assignment intent and emit its exact grant."""

import argparse
import json
import os
import sys

from zylch.services.task_assignment_approval import sign
from zylch.services.task_assignment_types import AssignmentError, canonical, validate_intent


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("intent", help="JSON intent exported by tasks.assignment.preview")
    args = parser.parse_args()
    try:
        if os.geteuid() != 0:
            raise AssignmentError("Assignment approval requires the independent host operator")
        with open(args.intent, "rb") as stream:
            raw = stream.read(131073)
        if len(raw) > 131072:
            raise AssignmentError("Assignment payload is too large")
        intent = validate_intent(json.loads(raw))
        print(json.dumps(intent, indent=2, sort_keys=True), file=sys.stderr)
        print("Type APPROVE to sign this exact operation: ", end="", file=sys.stderr, flush=True)
        if sys.stdin.readline().strip() != "APPROVE":
            raise AssignmentError("Assignment approval cancelled")
        print(canonical(sign(intent)).decode("ascii"))
        return 0
    except (AssignmentError, ValueError, OSError):
        print(
            "Assignment approval refused; check intent, operator authority and protected configuration.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
