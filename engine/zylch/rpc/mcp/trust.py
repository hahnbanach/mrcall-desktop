import json
import os
import stat
import time
from pathlib import Path


def registered(path: str | Path | None, uid: str, session_id: str, *, hosted: bool = False) -> bool:
    if path is None:
        return False
    try:
        candidate = Path(path).absolute()
        if any(part.is_symlink() for part in (candidate, *candidate.parents)):
            return False
        descriptor = os.open(candidate, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            info = os.fstat(descriptor)
            owner = 0 if hosted else os.getuid()
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != owner
                or info.st_mode & (0o037 if hosted else 0o077)
                or info.st_size > 65536
            ):
                return False
            if hosted:
                from zylch.workflows.identity import current_identity

                profile = current_identity().profile_dir.resolve()
                if candidate.is_relative_to(profile):
                    return False
                for parent in candidate.parents:
                    metadata = parent.stat()
                    if metadata.st_uid != 0 or metadata.st_mode & 0o022:
                        return False
            data = json.loads(os.read(descriptor, 65537))
        finally:
            os.close(descriptor)
        records = data.get("registrations") if isinstance(data, dict) else None
        if not isinstance(records, list) or len(records) > 128:
            return False
        return any(
            isinstance(item, dict)
            and item.get("uid") == uid
            and item.get("session_id") == session_id
            and type(item.get("expires_at")) in (int, float)
            and time.time() < item["expires_at"] <= time.time() + 1800
            and item.get("purpose") in {"native_acceptance", "accepted"}
            for item in records
        )
    except Exception:
        return False
