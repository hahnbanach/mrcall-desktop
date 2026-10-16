"""Temporary exact control CAS under an externally established maintenance lease.

The operator must exclude ALL daemon/settings writers and scoped cron. A file
lock constrains this helper only; it never establishes that external exclusion.
This tool never starts/stops a service or resumes preparation. On failure retain
that maintenance pause; the protected journal supports exact same-run recovery.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(name + ".py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


files = _load("m10_acceptance_budget_controls_files")
sql = _load("m10_acceptance_budget_controls_sql")
Refused = files.Refused


def process_start(pid: int) -> str | None:
    try:
        return Path(f"/proc/{pid}/stat").read_text().rsplit(") ", 1)[1].split()[19]
    except (FileNotFoundError, ProcessLookupError):
        return None


def validate_lease(lease: dict, paths: set[str]) -> None:
    if not isinstance(lease, dict) or not lease.get("run_id"):
        raise Refused("Explicit maintenance lease required")
    holder = lease.get("holder", {})
    if (
        type(holder.get("pid")) is not int
        or holder["pid"] <= 0
        or not isinstance(holder.get("start"), str)
        or not holder["start"]
        or process_start(holder["pid"]) != holder["start"]
    ):
        raise Refused("Maintenance lease holder is unavailable")
    if not paths <= set(lease.get("paths", [])):
        raise Refused("Maintenance lease does not own every target")
    for condition in (
        "daemons_stopped",
        "settings_writers_drained",
        "scoped_cron_paused",
        "all_writer_sources_excluded",
    ):
        if lease.get(condition) is not True:
            raise Refused("Maintenance exclusion unproved: " + condition)
    if not all(
        isinstance(lease.get("evidence", {}).get(key), str) and lease["evidence"][key]
        for key in ("daemon_stop", "settings_drain", "cron_pause")
    ):
        raise Refused("Maintenance evidence references required")
    if not isinstance(lease.get("writers"), list):
        raise Refused("Explicit stopped-writer inventory required")
    for writer in lease["writers"]:
        if type(writer.get("pid")) is not int or process_start(writer["pid"]) is not None:
            raise Refused("Known daemon/settings writer is not stopped and reaped")


def db_identity(path: str) -> dict:
    target = Path(path)
    if not target.is_absolute() or target.resolve() != target:
        raise Refused("Database must use its canonical existing path")
    info = target.stat()
    if not stat.S_ISREG(info.st_mode):
        raise Refused("Database must be regular")
    return dict(
        device=info.st_dev,
        inode=info.st_ino,
        uid=info.st_uid,
        gid=info.st_gid,
        mode=stat.S_IMODE(info.st_mode),
    )


def read_private(path: Path) -> bytes:
    info = path.lstat()
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.geteuid()
        or stat.S_IMODE(info.st_mode) != 0o600
    ):
        raise Refused("Private control evidence mode/owner changed")
    return path.read_bytes()


def encoded(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def expected_pause(before: dict, owner: str) -> dict:
    row = before["row"]
    if row is None:
        row = dict(
            owner=owner,
            paused=0,
            run_id=None,
            running=0,
            attempted=0,
            completed=0,
            failed=0,
            item_limit=25,
            stop_reason="",
            pid=None,
            started=None,
        )
    return dict(
        schema=before["schema"] or sql.SCHEMA, row=row | {"paused": 1, "stop_reason": sql.MARKER}
    )


def load(directory: Path) -> tuple[dict, bytes, dict]:
    info = directory.lstat()
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.geteuid()
        or stat.S_IMODE(info.st_mode) != 0o700
    ):
        raise Refused("Control evidence directory is not private")
    record = json.loads(read_private(directory / "journal.json"))
    content = read_private(directory / "env.before")
    preparation = read_private(directory / "preparation.before.json")
    if (
        files.digest(content) != record["env_backup_sha256"]
        or files.digest(preparation) != record["preparation_backup_sha256"]
    ):
        raise Refused("Original control evidence changed")
    if db_identity(record["database"]) != record["database_identity"]:
        raise Refused("Database identity/mode/owner changed")
    if record["phase"] not in {
        "captured",
        "env_paused",
        "paused",
        "admitting",
        "admitted",
        "preparation_restored",
        "restored",
    }:
        raise Refused("Unknown control recovery phase")
    return record, content, json.loads(preparation)


def save(directory: Path, record: dict, phase: str) -> None:
    record["phase"] = phase
    files.private_write(directory / "journal.json", encoded(record))


@contextmanager
def owned(directory: Path):
    info = directory.lstat()
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.geteuid()
        or stat.S_IMODE(info.st_mode) != 0o700
    ):
        raise Refused("Control directory ownership/mode changed")
    fd = os.open(directory / "helper.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise Refused("Another helper operation owns this control journal") from exc
        yield
    finally:
        os.close(fd)


def summary(record: dict) -> dict:
    return dict(
        run_id=record["run_id"],
        phase=record["phase"],
        env_before_sha256=record["env_before"]["sha256"],
        env_paused_sha256=record["env_paused"]["sha256"],
        maintenance_must_remain_held=True,
        service_restart_required=True,
        preparation_resume_called=False,
    )


def capture(
    directory: str, env_path: str, database: str, owner: str, lease: dict, *, apply: bool = False
) -> dict:
    validate_lease(lease, {env_path, database})
    if not isinstance(owner, str) or not owner.strip():
        raise Refused("Exact preparation owner identity required")
    identity = db_identity(database)
    before, content = files.snapshot(env_path)
    paused = files.paused_content(content)
    with sql.transaction(database) as conn:
        preparation = sql.snapshot(conn, owner)
    if preparation["row"] and preparation["row"]["running"]:
        raise Refused("Preparation must be stopped and drained before capture")
    record = dict(
        run_id=lease["run_id"],
        phase="captured",
        env_path=env_path,
        database=database,
        database_identity=identity,
        owner=owner,
        env_before=before,
        env_paused=before | {"present": True, "sha256": files.digest(paused)},
        env_admitted=before
        | {"present": True, "sha256": files.digest(files.admitted_content(content))},
        env_backup_sha256=files.digest(content),
        preparation_backup_sha256=files.digest(encoded(preparation)),
    )
    if not apply:
        return summary(record) | {"applied": False}
    path = Path(directory)
    path.mkdir(mode=0o700)
    files.private_write(path / "env.before", content, exclusive=True)
    files.private_write(path / "preparation.before.json", encoded(preparation), exclusive=True)
    files.private_write(path / "journal.json", encoded(record), exclusive=True)
    return summary(record)


def pause(directory: str, lease: dict, *, apply: bool = False) -> dict:
    path = Path(directory)
    with owned(path):
        record, content, before = load(path)
        validate_lease(lease, {record["env_path"], record["database"]})
        if lease["run_id"] != record["run_id"] or record["phase"] in {
            "preparation_restored",
            "restored",
        }:
            raise Refused("Control run cannot be reset or reassigned")
        current = files.snapshot(record["env_path"])[0]
        if current not in (record["env_before"], record["env_paused"], record["env_admitted"]):
            raise Refused("Saved settings drift; retain external maintenance pause")
        with sql.transaction(record["database"]) as conn:
            state = sql.snapshot(conn, record["owner"])
        target = expected_pause(before, record["owner"])
        if state not in (before, target):
            raise Refused("Preparation drift; retain external maintenance pause")
        if not apply:
            return summary(record) | {"applied": False}
        if current != record["env_paused"]:
            files.replace(
                record["env_path"],
                current,
                files.paused_content(content),
                record["env_before"],
            )
        save(path, record, "env_paused")
        if state != target:
            result = sql.pause(record["database"], record["owner"], before)
            if result != target:
                raise Refused("Preparation pause verification failed; retain maintenance")
        save(path, record, "paused")
        return summary(record)


def admit(directory: str, lease: dict, manifest: dict, *, apply: bool = False) -> dict:
    path = Path(directory)
    with owned(path):
        record, content, before = load(path)
        validate_lease(lease, {record["env_path"], record["database"]})
        if lease["run_id"] != record["run_id"] or record["phase"] not in {
            "paused",
            "admitting",
            "admitted",
        }:
            raise Refused("Admission requires this run's exact owned pause")
        if not files.original_budget_enabled(content):
            raise Refused("Original saved budget is paused; no paid admission")
        guard = _load("m10_acceptance_budget")
        try:
            guard.validate_manifest(manifest)
            for allocation in manifest["allocations"]:
                status = guard.inspect(manifest, allocation["allocation_id"])
                if (
                    not status["active"]
                    or status["remaining_micro_usd"] <= 0
                    or status["pricing_fault"]
                ):
                    raise Refused("Every fixed allocation must be active and accountable")
            selected = [
                allocation
                for allocation in manifest["allocations"]
                if allocation["path"] == record["database"]
                and allocation["owner_id"] == record["owner"]
            ]
            if len(selected) != 1:
                raise Refused("Active manifest does not bind these controls")
        except guard.Refused as exc:
            raise Refused("Exact active allocation validation failed") from exc
        current = files.snapshot(record["env_path"])[0]
        allowed = (
            (record["env_paused"], record["env_admitted"])
            if record["phase"] == "admitting"
            else (
                (record["env_admitted"],)
                if record["phase"] == "admitted"
                else (record["env_paused"],)
            )
        )
        if current not in allowed:
            raise Refused("Acceptance saved controls drift; retain maintenance")
        with sql.transaction(record["database"]) as conn:
            if sql.snapshot(conn, record["owner"]) != expected_pause(before, record["owner"]):
                raise Refused("Preparation must retain its exact owned pause")
        if not apply:
            return summary(record) | {"applied": False}
        save(path, record, "admitting")
        if current != record["env_admitted"]:
            files.replace(
                record["env_path"], current, files.admitted_content(content), record["env_before"]
            )
        save(path, record, "admitted")
        return summary(record)


def preparation_restored(current: dict, before: dict) -> bool:
    if current["schema"] != before["schema"]:
        return False
    if before["row"] is None:
        return current["row"] is None
    return current["row"] is not None and all(
        current["row"][key] == before["row"][key] for key in sql.COLUMNS if key not in sql.STATS
    )


def restore(directory: str, lease: dict, *, apply: bool = False) -> dict:
    path = Path(directory)
    with owned(path):
        record, content, before = load(path)
        validate_lease(lease, {record["env_path"], record["database"]})
        if lease["run_id"] != record["run_id"]:
            raise Refused("Control run identity changed")
        if record["phase"] == "captured":
            raise Refused("No owned pause to restore")
        if record["phase"] in {"admitting", "admitted"}:
            raise Refused("Pause owned paid intake before restoration")
        current_env = files.snapshot(record["env_path"])[0]
        if record["phase"] == "restored":
            files.exact(record["env_path"], record["env_before"])
            with sql.transaction(record["database"]) as conn:
                if not preparation_restored(sql.snapshot(conn, record["owner"]), before):
                    raise Refused("Restored preparation controls drifted; no overwrite")
            return summary(record)
        if current_env not in (record["env_paused"], record["env_before"]):
            raise Refused("Restore settings drift; retain external maintenance pause")
        with sql.transaction(record["database"]) as conn:
            current = sql.snapshot(conn, record["owner"])
        already = preparation_restored(current, before)
        if not apply:
            return summary(record) | {"applied": False}
        if not already:
            sql.restore(
                record["database"], record["owner"], before, expected_pause(before, record["owner"])
            )
        save(path, record, "preparation_restored")
        if current_env != record["env_before"]:
            files.replace(
                record["env_path"],
                record["env_paused"],
                content if record["env_before"]["present"] else None,
                record["env_before"],
            )
        save(path, record, "restored")
        return summary(record)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("capture", "pause", "admit", "restore", "status"))
    parser.add_argument("--directory", required=True)
    parser.add_argument("--lease")
    parser.add_argument("--env-path")
    parser.add_argument("--database")
    parser.add_argument("--owner")
    parser.add_argument("--manifest")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.operation == "status":
        result = summary(load(Path(args.directory))[0])
    else:
        if not args.lease:
            parser.error("--lease is required for target operations")
        lease = json.loads(read_private(Path(args.lease)))
        if args.operation == "capture":
            if not all((args.env_path, args.database, args.owner)):
                parser.error("capture requires --env-path, --database and --owner")
            result = capture(
                args.directory, args.env_path, args.database, args.owner, lease, apply=args.apply
            )
        elif args.operation == "admit":
            if not args.manifest:
                parser.error("admit requires --manifest")
            result = admit(
                args.directory,
                lease,
                json.loads(read_private(Path(args.manifest))),
                apply=args.apply,
            )
        else:
            result = globals()[args.operation](args.directory, lease, apply=args.apply)
    print(encoded(result).decode())


if __name__ == "__main__":
    main()
