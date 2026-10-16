"""Persistent SQL admission objects for the temporary acceptance run."""

PREFIX = "_m10_acceptance_"
RESERVATION = (
    "id",
    "owner_id",
    "created_at",
    "model",
    "transport",
    "call_site",
    "reserved_micro_usd",
)
USAGE = (
    "id",
    "owner_id",
    "ts",
    "call_site",
    "transport",
    "model",
    "input_tokens",
    "output_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
    "est_cost_usd",
)
AUTH = ("reservation_id", "quote", "receipt")
COLUMNS = {
    "llm_reservations": RESERVATION + ("settled_at",),
    "llm_usage": USAGE,
    "llm_billing_authorizations": AUTH,
}


def literal(value):
    return "'" + str(value).replace("'", "''") + "'"


def projection(columns, alias=""):
    return "json_array(" + ",".join(f'{alias}"{key}"' for key in columns) + ")"


def micros(value):
    """Round conservatively without a connection-local function.

    In the supported USD0..1,000,000 range, scaling a binary64 value by
    1,000,000 has error far below one micro-USD (largest product: 10**12;
    binary64 spacing: 2**-13). Decimal(str(value)) has the same sub-unit
    error bound. Floor plus two therefore covers both errors and the final
    ceiling. Exact zero stays zero; invalid/overflowing values stay unknown.
    """
    return (
        f"CASE WHEN typeof({value}) IN ('integer','real') AND {value}>=0 "
        f"AND {value}<=1000000 THEN CAST({value}*1000000 AS INTEGER)"
        f"+CASE WHEN {value}=0 THEN 0 ELSE 2 END ELSE NULL END"
    )


def schema():
    return {
        "state": "CREATE TABLE _m10_acceptance_state (manifest TEXT NOT NULL, allocation TEXT NOT NULL, schema_json TEXT NOT NULL, baseline_hash TEXT NOT NULL)",
        "objects": "CREATE TABLE _m10_acceptance_objects (name TEXT PRIMARY KEY, kind TEXT NOT NULL, sql TEXT NOT NULL)",
        "reservations": "CREATE TABLE _m10_acceptance_reservations (id TEXT PRIMARY KEY, original TEXT NOT NULL, baseline INTEGER NOT NULL CHECK(baseline IN (0,1)))",
        "usage": "CREATE TABLE _m10_acceptance_usage (id TEXT PRIMARY KEY, original TEXT NOT NULL, baseline INTEGER NOT NULL CHECK(baseline IN (0,1)))",
        "events": "CREATE TABLE _m10_acceptance_events (event TEXT PRIMARY KEY CHECK(event IN ('activated','deactivated')), created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)",
    }


def frozen_schema_admission():
    bindings = {
        PREFIX + "objects": ("table", schema()["objects"]),
    }
    for operation in ("INSERT", "UPDATE", "DELETE"):
        name = PREFIX + "objects_" + operation.lower()
        reason = (
            "acceptance identity is frozen"
            if operation == "INSERT"
            else "acceptance evidence is immutable"
        )
        bindings[name] = (
            "trigger",
            f"CREATE TRIGGER {name} BEFORE {operation} ON {PREFIX}objects BEGIN SELECT RAISE(ABORT,'{reason}'); END",
        )
    checks = [
        f"NOT EXISTS(SELECT 1 FROM main.sqlite_master WHERE name={literal(name)} AND type={literal(kind)} AND sql={literal(sql)})"
        for name, (kind, sql) in bindings.items()
    ]
    checks.append(
        f"EXISTS(SELECT 1 FROM main.{PREFIX}objects o LEFT JOIN main.sqlite_master s ON s.name=o.name WHERE s.sql IS NOT o.sql OR s.type IS NOT o.kind)"
    )
    return (
        f"SELECT CASE WHEN {' OR '.join(checks)} "
        "THEN RAISE(ABORT,'acceptance frozen schema refused') END;"
    )


def admission(owner, allocation, *, inserted=False):
    duplicate = "" if inserted else "OR EXISTS(SELECT 1 FROM llm_reservations WHERE id=NEW.id)"
    ceiling = str(allocation) if inserted else f"{allocation}-NEW.reserved_micro_usd"
    return frozen_schema_admission() + (
        f"SELECT CASE WHEN (SELECT invalid FROM {PREFIX}integrity) "
        f"OR typeof(NEW.reserved_micro_usd)!='integer' OR NEW.reserved_micro_usd<0 "
        f"OR typeof(NEW.id)!='text' OR length(NEW.id)=0 "
        f"OR NEW.owner_id IS NOT {literal(owner)} OR NEW.settled_at IS NOT NULL "
        f"{duplicate} OR EXISTS(SELECT 1 FROM llm_usage WHERE id=NEW.id) "
        f"OR EXISTS(SELECT 1 FROM llm_reservations r JOIN {PREFIX}costs c ON c.id=r.id "
        f"WHERE c.historical=0 AND round(c.est_cost_usd*1000000)>r.reserved_micro_usd) "
        f"OR NEW.reserved_micro_usd>{allocation} "
        f"OR (SELECT committed FROM {PREFIX}totals)>{ceiling} "
        "THEN RAISE(ABORT,'acceptance allocation or integrity refused') END;"
    )


def objects(path, owner, allocation):
    result = {}

    def add(name, kind, sql):
        result[PREFIX + name] = (kind, sql)

    for name, sql in schema().items():
        add(name, "table", sql)
    for suffix in ("state", "objects", "reservations", "usage", "events"):
        for operation in ("UPDATE", "DELETE"):
            name = f"{suffix}_{operation.lower()}"
            add(
                name,
                "trigger",
                f"CREATE TRIGGER {PREFIX}{name} BEFORE {operation} ON {PREFIX}{suffix} BEGIN SELECT RAISE(ABORT,'acceptance evidence is immutable'); END",
            )
    for suffix in ("state", "objects"):
        name = f"{suffix}_insert"
        add(
            name,
            "trigger",
            f"CREATE TRIGGER {PREFIX}{name} BEFORE INSERT ON {PREFIX}{suffix} BEGIN SELECT RAISE(ABORT,'acceptance identity is frozen'); END",
        )
    add(
        "events_insert",
        "trigger",
        f"CREATE TRIGGER {PREFIX}events_insert BEFORE INSERT ON {PREFIX}events WHEN NEW.event!='deactivated' OR EXISTS(SELECT 1 FROM {PREFIX}events WHERE event='deactivated') BEGIN SELECT RAISE(ABORT,'acceptance run cannot reset'); END",
    )
    for suffix, table, columns in (
        ("reservations", "llm_reservations", RESERVATION),
        ("usage", "llm_usage", USAGE),
    ):
        add(
            f"{suffix}_insert",
            "trigger",
            f"CREATE TRIGGER {PREFIX}{suffix}_insert BEFORE INSERT ON {PREFIX}{suffix} WHEN NEW.baseline!=0 OR NOT EXISTS(SELECT 1 FROM {table} WHERE id=NEW.id AND {projection(columns)} IS NEW.original) BEGIN SELECT RAISE(ABORT,'acceptance audit identity mismatch'); END",
        )
        capture_guard = (
            admission(owner, allocation, inserted=True) if suffix == "reservations" else ""
        )
        add(
            f"{suffix}_capture",
            "trigger",
            f"CREATE TRIGGER {PREFIX}{suffix}_capture AFTER INSERT ON {table} BEGIN INSERT INTO {PREFIX}{suffix} VALUES(NEW.id,{projection(columns, 'NEW.')},0); {capture_guard} END",
        )
        add(
            f"{suffix}_no_delete",
            "trigger",
            f"CREATE TRIGGER {PREFIX}{suffix}_no_delete BEFORE DELETE ON {table} BEGIN SELECT RAISE(ABORT,'acceptance ledger deletion refused'); END",
        )
    add(
        "usage_no_replace",
        "trigger",
        f"CREATE TRIGGER {PREFIX}usage_no_replace BEFORE INSERT ON llm_usage WHEN typeof(NEW.id)!='text' OR length(NEW.id)=0 OR EXISTS(SELECT 1 FROM llm_usage WHERE id=NEW.id) BEGIN SELECT RAISE(ABORT,'acceptance usage replacement refused'); END",
    )
    add(
        "authorization_no_replace",
        "trigger",
        f"CREATE TRIGGER {PREFIX}authorization_no_replace BEFORE INSERT ON llm_billing_authorizations WHEN EXISTS(SELECT 1 FROM llm_billing_authorizations WHERE reservation_id=NEW.reservation_id) BEGIN SELECT RAISE(ABORT,'acceptance authorization replacement refused'); END",
    )
    add(
        "usage_no_update",
        "trigger",
        f"CREATE TRIGGER {PREFIX}usage_no_update BEFORE UPDATE ON llm_usage BEGIN SELECT RAISE(ABORT,'acceptance usage is immutable'); END",
    )
    same = " AND ".join(f"NEW.{key} IS OLD.{key}" for key in RESERVATION)
    receipt = " AND ".join(
        f"u.{key} IS NEW.{key}" for key in ("owner_id", "model", "transport", "call_site")
    )
    add(
        "reservation_update",
        "trigger",
        f"CREATE TRIGGER {PREFIX}reservation_update BEFORE UPDATE ON llm_reservations WHEN NOT ({same}) OR OLD.settled_at IS NOT NULL OR NEW.settled_at IS NULL OR NOT EXISTS(SELECT 1 FROM llm_usage u WHERE u.id=NEW.id AND {receipt} AND typeof(u.est_cost_usd) IN ('real','integer') AND u.est_cost_usd>=0 AND u.est_cost_usd<1e999) BEGIN SELECT RAISE(ABORT,'acceptance settlement mismatch'); END",
    )
    add(
        "authorization_update",
        "trigger",
        f"CREATE TRIGGER {PREFIX}authorization_update BEFORE UPDATE ON llm_billing_authorizations WHEN NEW.reservation_id IS NOT OLD.reservation_id OR NEW.quote IS NOT OLD.quote OR OLD.receipt IS NOT NULL BEGIN SELECT RAISE(ABORT,'acceptance quote is immutable'); END",
    )
    add(
        "authorization_delete",
        "trigger",
        f"CREATE TRIGGER {PREFIX}authorization_delete BEFORE DELETE ON llm_billing_authorizations BEGIN SELECT RAISE(ABORT,'acceptance authorization deletion refused'); END",
    )
    bound = " AND ".join(
        f"u.{key} IS r.{key}" for key in ("owner_id", "model", "transport", "call_site")
    )
    add(
        "costs",
        "view",
        f"CREATE VIEW {PREFIX}costs AS SELECT u.*, {micros('u.est_cost_usd')} AS micros, CASE WHEN a.baseline=1 OR (b.baseline=1 AND {bound}) THEN 1 ELSE 0 END AS historical FROM llm_usage u JOIN {PREFIX}usage a ON a.id=u.id LEFT JOIN llm_reservations r ON r.id=u.id LEFT JOIN {PREFIX}reservations b ON b.id=r.id",
    )
    checks = []
    for suffix, table, columns in (
        ("reservations", "llm_reservations", RESERVATION),
        ("usage", "llm_usage", USAGE),
    ):
        checks.append(
            f"EXISTS(SELECT 1 FROM {table} p LEFT JOIN {PREFIX}{suffix} a ON a.id=p.id WHERE a.id IS NULL OR a.original IS NOT {projection(columns, 'p.')})"
        )
        checks.append(
            f"EXISTS(SELECT 1 FROM {PREFIX}{suffix} a LEFT JOIN {table} p ON p.id=a.id WHERE p.id IS NULL)"
        )
    checks.extend(
        [
            f"EXISTS(SELECT 1 FROM {PREFIX}objects o LEFT JOIN sqlite_master s ON s.name=o.name WHERE s.sql IS NOT o.sql OR s.type IS NOT o.kind)",
            f"(SELECT count(*) FROM {PREFIX}state)!=1",
            f"NOT EXISTS(SELECT 1 FROM {PREFIX}events WHERE event='activated')",
            f"(SELECT file FROM pragma_database_list WHERE name='main') IS NOT {literal(path)}",
            f"EXISTS(SELECT 1 FROM {PREFIX}costs WHERE historical=0 AND micros IS NULL)",
            f"EXISTS(SELECT 1 FROM llm_usage u JOIN llm_reservations r ON r.id=u.id WHERE NOT ({bound}))",
            f"EXISTS(SELECT 1 FROM llm_reservations r JOIN {PREFIX}reservations a ON a.id=r.id WHERE a.baseline=0 AND (typeof(r.reserved_micro_usd)!='integer' OR r.reserved_micro_usd<0 OR r.owner_id IS NOT {literal(owner)} OR (r.settled_at IS NOT NULL AND NOT EXISTS(SELECT 1 FROM llm_usage u WHERE u.id=r.id))))",
        ]
    )
    add(
        "integrity",
        "view",
        f"CREATE VIEW {PREFIX}integrity AS SELECT ({' OR '.join(checks)}) AS invalid",
    )
    add(
        "totals",
        "view",
        f"CREATE VIEW {PREFIX}totals AS SELECT COALESCE((SELECT SUM(micros) FROM {PREFIX}costs WHERE historical=0),0) + COALESCE((SELECT SUM(r.reserved_micro_usd) FROM llm_reservations r JOIN {PREFIX}reservations a ON a.id=r.id WHERE a.baseline=0 AND r.settled_at IS NULL),0) AS committed",
    )
    for suffix in ("admit_a", "admit_b"):
        add(
            suffix,
            "trigger",
            f"CREATE TRIGGER {PREFIX}{suffix} BEFORE INSERT ON llm_reservations BEGIN {admission(owner, allocation)} END",
        )
    return result
