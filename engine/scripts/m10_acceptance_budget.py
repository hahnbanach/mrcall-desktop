"""Temporary four-ledger acceptance guard; never initializes product databases.

Trusted maintenance must exclude whole-database rollback, alternate hosts and
privileged removal of every effective reservation-insert guard (including
reservation capture), even while unrelated usage/audit objects remain. Copies are not paid execution targets. The
SQL guard covers ordinary writers, concurrency, restarts, aging and midnight.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
from contextlib import contextmanager

_SPEC = importlib.util.spec_from_file_location(
    "m10_acceptance_budget_sql", Path(__file__).with_name("m10_acceptance_budget_sql.py")
)
_SQL = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_SQL)
PREFIX = _SQL.PREFIX
LIMIT = 5_000_000


class Refused(RuntimeError):
    """The temporary guard cannot be safely changed or resumed."""


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def load_manifest(path):
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise Refused("Duplicate manifest key")
            value[key] = item
        return value

    try:
        return validate_manifest(json.loads(Path(path).read_text(), object_pairs_hook=pairs))
    except (OSError, ValueError, TypeError) as exc:
        raise Refused("Manifest is unavailable or malformed") from exc


def validate_manifest(manifest):
    if not isinstance(manifest, dict) or set(manifest) != {"run_id", "allocations"}:
        raise Refused("Unsupported manifest shape")
    if not isinstance(manifest["run_id"], str) or not manifest["run_id"].strip():
        raise Refused("Missing run identity")
    allocations = manifest["allocations"]
    if not isinstance(allocations, list) or len(allocations) != 4:
        raise Refused("Exactly four fixed allocations are required")
    ids, paths, inodes, total = set(), set(), set(), 0
    for row in allocations:
        if not isinstance(row, dict) or set(row) != {
            "allocation_id",
            "path",
            "owner_id",
            "micro_usd",
            "device",
            "inode",
        }:
            raise Refused("Unsupported allocation shape")
        for key in ("allocation_id", "path", "owner_id"):
            if not isinstance(row[key], str) or not row[key].strip():
                raise Refused("Missing allocation identity")
        if any(type(row[key]) is not int or row[key] < 0 for key in ("device", "inode")):
            raise Refused("Invalid database identity")
        if type(row["micro_usd"]) is not int or not 0 < row["micro_usd"] <= LIMIT:
            raise Refused("Invalid allocation amount")
        if not Path(row["path"]).is_absolute():
            raise Refused("Database path must be absolute")
        identity = row["device"], row["inode"]
        if row["allocation_id"] in ids or row["path"] in paths or identity in inodes:
            raise Refused("Duplicate allocation or database identity")
        ids.add(row["allocation_id"])
        paths.add(row["path"])
        inodes.add(identity)
        total += row["micro_usd"]
    if total > LIMIT:
        raise Refused("Manifest exceeds additional USD5 ceiling")
    return manifest


def target(manifest, allocation_id):
    validate_manifest(manifest)
    matches = [r for r in manifest["allocations"] if r["allocation_id"] == allocation_id]
    if len(matches) != 1:
        raise Refused("Unknown allocation")
    row = matches[0]
    path = Path(row["path"])
    try:
        stat = path.stat()
        if str(path.resolve(strict=True)) != row["path"] or not path.is_file():
            raise Refused("Database path changed or is an alias")
    except OSError as exc:
        raise Refused("Existing database required") from exc
    if (stat.st_dev, stat.st_ino) != (row["device"], row["inode"]):
        raise Refused("Database identity changed")
    return row


@contextmanager
def connection(row, write=False):
    mode = "rw" if write else "ro"
    uri = Path(row["path"]).as_uri() + "?mode=" + mode
    conn = sqlite3.connect(uri, uri=True, timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("BEGIN IMMEDIATE" if write else "BEGIN")
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def product_schema(conn):
    result = {}
    for name, columns in _SQL.COLUMNS.items():
        actual = conn.execute(f'PRAGMA table_info("{name}")').fetchall()
        if set(r["name"] for r in actual) != set(columns):
            raise Refused("Unsupported or missing ledger schema: " + name)
        for column in actual:
            key = column["name"]
            if key in {"id", "reservation_id"}:
                expected_type = "VARCHAR(36)"
            elif key in {"created_at", "settled_at", "ts"}:
                expected_type = "DATETIME"
            elif key in {"quote", "receipt"}:
                expected_type = "JSON"
            elif key == "est_cost_usd":
                expected_type = "FLOAT"
            elif key.endswith("tokens") or key == "reserved_micro_usd":
                expected_type = "INTEGER"
            else:
                expected_type = "TEXT"
            if column["type"].upper() != expected_type:
                raise Refused("Unsupported ledger column type: " + name + "." + key)
        sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (name,)
        ).fetchone()
        if sql is None:
            raise Refused("Missing ledger table")
        result[name] = sql[0]
    return result


def owned(conn):
    return {
        r["name"]: (r["type"], r["sql"])
        for r in conn.execute(
            "SELECT name,type,sql FROM sqlite_master WHERE substr(name,1,?)=?",
            (len(PREFIX), PREFIX),
        )
    }


def baseline(conn):
    result = {}
    for suffix, table, columns in (
        ("reservations", "llm_reservations", _SQL.RESERVATION),
        ("usage", "llm_usage", _SQL.USAGE),
    ):
        rows = conn.execute(
            f"SELECT id,{_SQL.projection(columns)} AS original FROM {table} ORDER BY id"
        ).fetchall()
        if any(not isinstance(r["id"], str) or not r["id"] for r in rows):
            raise Refused("Ledger contains invalid row identities")
        result[suffix] = [tuple(row) for row in rows]
    return result


def retained_baseline(conn):
    return {
        suffix: [
            tuple(r)
            for r in conn.execute(
                f"SELECT id,original FROM {PREFIX}{suffix} WHERE baseline=1 ORDER BY id"
            )
        ]
        for suffix in ("reservations", "usage")
    }


def validate_active(conn, manifest, row):
    expected = _SQL.objects(row["path"], row["owner_id"], row["micro_usd"])
    actual = owned(conn)
    if actual != expected:
        raise Refused("Acceptance guard/schema objects differ or are missing")
    state = conn.execute(f"SELECT * FROM {PREFIX}state").fetchall()
    schema = product_schema(conn)
    if len(state) != 1 or tuple(state[0]) != (
        canonical(manifest),
        row["allocation_id"],
        canonical(schema),
        digest(retained_baseline(conn)),
    ):
        raise Refused("Acceptance baseline/manifest/schema identity differs")
    records = {
        r[0]: (r[1], r[2]) for r in conn.execute(f"SELECT name,kind,sql FROM {PREFIX}objects")
    }
    wanted = expected | {name: ("table", sql) for name, sql in schema.items()}
    if records != wanted:
        raise Refused("Acceptance schema-binding records differ")
    if conn.execute(f"SELECT invalid FROM {PREFIX}integrity").fetchone()[0]:
        raise Refused("Acceptance ledger integrity invalid")
    return status_row(conn, row)


def status_row(conn, row):
    totals = conn.execute(f"SELECT committed FROM {PREFIX}totals").fetchone()[0]
    historical_holds = [
        r[0]
        for r in conn.execute(
            f"SELECT r.reserved_micro_usd FROM llm_reservations r JOIN {PREFIX}reservations a ON a.id=r.id WHERE a.baseline=1 AND r.settled_at IS NULL"
        )
    ]
    valid_holds = [value for value in historical_holds if type(value) is int and value >= 0]
    old_holds = (len(historical_holds), sum(valid_holds))
    historical_invalid = conn.execute(
        f"SELECT COUNT(*) FROM {PREFIX}costs WHERE historical=1 AND micros IS NULL"
    ).fetchone()[0]
    old_costs = conn.execute(
        f"SELECT COALESCE(SUM(micros),0) FROM {PREFIX}costs WHERE historical=1"
    ).fetchone()[0]
    pricing_fault = bool(
        conn.execute(
            f"SELECT EXISTS(SELECT 1 FROM llm_reservations r JOIN {PREFIX}costs c ON c.id=r.id WHERE c.historical=0 AND round(c.est_cost_usd*1000000)>r.reserved_micro_usd)"
        ).fetchone()[0]
    )
    return {
        "allocation_id": row["allocation_id"],
        "allocation_micro_usd": row["micro_usd"],
        "additional_committed_micro_usd": totals,
        "remaining_micro_usd": 0 if pricing_fault else max(0, row["micro_usd"] - totals),
        "pricing_fault": pricing_fault,
        "historical_open_count": old_holds[0],
        "historical_open_max_micro_usd": old_holds[1],
        "historical_recorded_micro_usd": old_costs,
        "historical_invalid_usage_rows": historical_invalid,
        "historical_invalid_reservation_rows": len(historical_holds) - len(valid_holds),
    }


def inspect(manifest, allocation_id):
    row = target(manifest, allocation_id)
    with connection(row) as conn:
        schema = product_schema(conn)
        if owned(conn):
            event_table = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE name=?", (PREFIX + "events",)
            ).fetchone()
            if (
                event_table
                and conn.execute(
                    f"SELECT 1 FROM {PREFIX}events WHERE event='deactivated'"
                ).fetchone()
            ):
                expected = _SQL.objects(row["path"], row["owner_id"], row["micro_usd"])
                retained = {
                    name: value
                    for name, value in expected.items()
                    if not (
                        value[0] == "trigger"
                        and any(" ON " + table + " " in value[1] for table in _SQL.COLUMNS)
                    )
                }
                if owned(conn) != retained:
                    raise Refused("Deactivated audit/schema objects differ")
                frozen = conn.execute(
                    f"SELECT manifest,allocation,baseline_hash FROM {PREFIX}state"
                ).fetchall()
                if len(frozen) != 1 or tuple(frozen[0]) != (
                    canonical(manifest),
                    allocation_id,
                    digest(retained_baseline(conn)),
                ):
                    raise Refused("Deactivated allocation identity differs")
                return {
                    "active": False,
                    "audit_retained": True,
                    "allocation_id": allocation_id,
                    "reactivation_allowed": False,
                }
            return validate_active(conn, manifest, row) | {"active": True}
        return {
            "active": False,
            "schema_sha256": digest(schema),
            "baseline_sha256": digest(baseline(conn)),
        }


def activate(manifest, allocation_id, *, apply=False):
    if not apply:
        return inspect(manifest, allocation_id) | {"applied": False}
    row = target(manifest, allocation_id)
    with connection(row, write=True) as conn:
        if owned(conn):
            if (
                conn.execute(f"SELECT 1 FROM sqlite_master WHERE name='{PREFIX}events'").fetchone()
                and conn.execute(
                    f"SELECT 1 FROM {PREFIX}events WHERE event='deactivated'"
                ).fetchone()
            ):
                raise Refused("Deactivated allocation cannot reset or reactivate")
            return validate_active(conn, manifest, row) | {"active": True, "resumed": True}
        schema = product_schema(conn)
        frozen = baseline(conn)
        objects = _SQL.objects(row["path"], row["owner_id"], row["micro_usd"])
        for kind, sql in objects.values():
            if kind == "table":
                conn.execute(sql)
        conn.execute(
            f"INSERT INTO {PREFIX}state VALUES(?,?,?,?)",
            (canonical(manifest), allocation_id, canonical(schema), digest(frozen)),
        )
        for suffix, rows in frozen.items():
            conn.executemany(f"INSERT INTO {PREFIX}{suffix} VALUES(?,?,1)", rows)
        conn.execute(f"INSERT INTO {PREFIX}events(event) VALUES('activated')")
        bindings = objects | {name: ("table", sql) for name, sql in schema.items()}
        conn.executemany(
            f"INSERT INTO {PREFIX}objects VALUES(?,?,?)",
            [(name, kind, sql) for name, (kind, sql) in bindings.items()],
        )
        for kind, sql in objects.values():
            if kind != "table":
                conn.execute(sql)
        return validate_active(conn, manifest, row) | {"active": True, "resumed": False}


def deactivate(manifest, allocation_id, *, apply=False, intake_stopped=False):
    row = target(manifest, allocation_id)
    if not apply:
        return inspect(manifest, allocation_id) | {"applied": False}
    if not intake_stopped:
        raise Refused("Stop and drain paid intake before exact guard removal")
    with connection(row, write=True) as conn:
        state = validate_active(conn, manifest, row)
        conn.execute(f"INSERT INTO {PREFIX}events(event) VALUES('deactivated')")
        removed = []
        for record in conn.execute(
            "SELECT name,tbl_name FROM sqlite_master WHERE type='trigger'"
        ).fetchall():
            if record["name"].startswith(PREFIX) and record["tbl_name"] in _SQL.COLUMNS:
                conn.execute('DROP TRIGGER "' + record["name"] + '"')
                removed.append(record["name"])
        return state | {"active": False, "removed_triggers": removed, "audit_retained": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("inspect", "activate", "status", "deactivate"))
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--allocation", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--intake-stopped", action="store_true")
    args = parser.parse_args()
    manifest = load_manifest(args.manifest)
    if args.operation in ("inspect", "status"):
        result = inspect(manifest, args.allocation)
    elif args.operation == "activate":
        result = activate(manifest, args.allocation, apply=args.apply)
    else:
        result = deactivate(
            manifest, args.allocation, apply=args.apply, intake_stopped=args.intake_stopped
        )
    print(canonical(result))


if __name__ == "__main__":
    main()
