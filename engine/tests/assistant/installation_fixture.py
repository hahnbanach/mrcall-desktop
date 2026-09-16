"""Synthetic CI metadata; optionally consume StarChat's exact cross-repo fixture.

There is no production installation copy in this repository. Cross-repo checks
set MRCALL_INSTALLATION_SOURCE and MRCALL_PROCEDURE_SOURCE together; forgetting
one must fail rather than silently pairing unrelated revisions.
"""

import hashlib
import json
import os
from pathlib import Path

from tests.assistant.procedure_fixture import artifact_bytes


def installation_bytes():
    path = os.environ.get("MRCALL_INSTALLATION_SOURCE")
    if path:
        if not os.environ.get("MRCALL_PROCEDURE_SOURCE"):
            raise ValueError("cross-repo installation fixture requires procedure source")
        return Path(path).read_bytes()
    return json.dumps(
        {
            "version": 1,
            "id": "synthetic-installation",
            "business_id": "synthetic-business",
            "procedure_revision": hashlib.sha256(artifact_bytes()).hexdigest(),
            "connection_ref": "synthetic-connection",
            "authority_ref": "synthetic-authority",
        }
    ).encode()
