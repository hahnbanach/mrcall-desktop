"""Synthetic contract example; optionally test the real cross-repo artifact.

This is not a distributed procedure copy. Standalone engine CI must exercise the
contract even without StarChat checked out. Cross-repo verification explicitly
selects the canonical resource with MRCALL_PROCEDURE_SOURCE.
"""

import json
import os
from pathlib import Path


def artifact_bytes():
    path = os.environ.get("MRCALL_PROCEDURE_SOURCE")
    if path:
        return Path(path).read_bytes()
    return json.dumps(
        {
            "version": 1,
            "id": "synthetic-contract",
            "instructions": "Choose an allowed read, then finish with its supported outcome.",
            "operations": ["order.exists", "memory.recall"],
            "completion": "order",
            "messages": {
                "order_exists": "An order exists.",
                "no_order": "No order exists.",
                "need_identification": "Please identify the customer.",
                "unavailable": "I cannot verify this now.",
                "memory_found": "Approved company facts:",
            },
        }
    ).encode()
