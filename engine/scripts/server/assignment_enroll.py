#!/usr/bin/env python3
"""Root-only ordered enrollment. No tenant RPC and no enrollment downgrade."""

import argparse
import json
import os
import tempfile
from pathlib import Path
from sqlalchemy import create_engine, select, update
from zylch.services import task_assignment_enrollment as enrollment
from zylch.services import task_assignment_trust as trust
from zylch.services.task_assignment_types import AssignmentError
from zylch.storage.models import ProjectSpace


def install(store, space_id, source):
    if os.geteuid() != 0:
        raise AssignmentError("Independent root operator required for enrollment")
    store = Path(store)
    if not store.is_file() or store.is_symlink():
        raise AssignmentError("Existing company database required")
    raw = trust.protected_read(Path(source))
    document = trust.parse(raw, space_id)
    engine = create_engine(f"sqlite:///{store.absolute()}")
    try:
        with engine.begin() as conn:
            conn.execute(update(ProjectSpace).values(space_id=ProjectSpace.space_id))
            if conn.execute(select(ProjectSpace.space_id)).scalar_one() != space_id:
                raise AssignmentError("Enrollment company mismatch")
            enrollment.enroll_locked(conn, space_id)
        # The durable managed latch commits BEFORE any trust publication.
        with engine.begin() as conn:
            conn.execute(update(ProjectSpace).values(space_id=ProjectSpace.space_id))
            enrollment.require_managed(conn, space_id)
            directory = trust.TRUST_DIRECTORY
            directory.mkdir(mode=0o755, parents=True, exist_ok=True)
            # Safe inspection validates the complete path and any existing file.
            trust.probe(space_id)
            fd, temporary = tempfile.mkstemp(prefix=".enroll-", dir=directory)
            try:
                os.fchmod(fd, 0o644)
                with os.fdopen(fd, "wb") as stream:
                    stream.write(json.dumps(document, sort_keys=True).encode())
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, directory / f"{space_id}.json")
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
    finally:
        engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", required=True)
    parser.add_argument("--space-id", required=True)
    parser.add_argument("--trust-json", required=True)
    args = parser.parse_args()
    install(args.store, args.space_id, args.trust_json)


if __name__ == "__main__":
    main()
