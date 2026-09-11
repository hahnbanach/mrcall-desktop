"""Durable admission for bounded preparation; no message content is stored here."""

import contextvars
import functools
import inspect
import os
import time
import uuid
from contextlib import contextmanager

from zylch.llm.budget import BudgetError

_current = contextvars.ContextVar("preparation_run", default=None)
_in_item = contextvars.ContextVar("preparation_item", default=False)


class PreparationStopped(BudgetError):
    """Preparation is paused or its shared item allowance is exhausted."""

    code = -32020


@contextmanager
def _db():
    from zylch.storage.database import get_engine

    with get_engine().connect() as conn:
        conn.exec_driver_sql("BEGIN IMMEDIATE")
        conn.exec_driver_sql("""CREATE TABLE IF NOT EXISTS preparation_state (
            owner TEXT PRIMARY KEY, paused INTEGER NOT NULL DEFAULT 0,
            run_id TEXT, running INTEGER NOT NULL DEFAULT 0, attempted INTEGER NOT NULL DEFAULT 0,
            completed INTEGER NOT NULL DEFAULT 0, failed INTEGER NOT NULL DEFAULT 0,
            item_limit INTEGER NOT NULL DEFAULT 25, stop_reason TEXT NOT NULL DEFAULT '',
            pid INTEGER, started REAL)""")
        conn.exec_driver_sql("""CREATE TABLE IF NOT EXISTS preparation_attempts (
            owner TEXT NOT NULL, stage TEXT NOT NULL, source TEXT NOT NULL,
            failures INTEGER NOT NULL DEFAULT 0, retry_at REAL NOT NULL DEFAULT 0,
            inflight INTEGER NOT NULL DEFAULT 0, run_id TEXT,
            PRIMARY KEY(owner, stage, source))""")
        columns = {r[1] for r in conn.exec_driver_sql("PRAGMA table_info(preparation_attempts)")}
        if "dispatched" not in columns:
            conn.exec_driver_sql(
                "ALTER TABLE preparation_attempts ADD COLUMN dispatched INTEGER NOT NULL DEFAULT 0"
            )
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise


def _account(owner):
    return os.environ.get("OWNER_ID") or owner


def _ensure(conn, owner):
    conn.exec_driver_sql("INSERT OR IGNORE INTO preparation_state(owner) VALUES (?)", (owner,))


def batch_limit():
    from dotenv import dotenv_values

    directory = os.environ.get("ZYLCH_PROFILE_DIR")
    raw = (dotenv_values(os.path.join(directory, ".env")) if directory else os.environ).get(
        "PREPARATION_BATCH_SIZE", "25"
    )
    try:
        value = int(raw)
    except (ValueError, TypeError):
        raise PreparationStopped("Invalid preparation batch size; choose 1–100 items.") from None
    if not 1 <= value <= 100:
        raise PreparationStopped("Invalid preparation batch size; choose 1–100 items.")
    return value


def _alive(pid):
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


@contextmanager
def preparation_run(owner, *, explicit=False):
    """Admit one run across processes. Explicit run does not clear saved pause."""
    owner = _account(owner)
    if _current.get():
        if _current.get()[0] != owner:
            raise PreparationStopped("Preparation owner cannot change during a run.")
        yield
        return
    run_id = uuid.uuid4().hex
    with _db() as conn:
        _ensure(conn, owner)
        row = (
            conn.exec_driver_sql("SELECT * FROM preparation_state WHERE owner=?", (owner,))
            .mappings()
            .one()
        )
        if row["running"] and _alive(row["pid"]):
            raise PreparationStopped("Preparation is already running.")
        if row["paused"] and not explicit:
            raise PreparationStopped("Preparation is paused. Resume starts one bounded run.")
        # An interrupted item may already have incurred cost. Count it as an
        # unsuccessful attempt; never erase it by restarting the daemon.
        conn.exec_driver_sql(
            """UPDATE preparation_attempts SET failures=failures+1,
            retry_at=?, inflight=0 WHERE owner=? AND inflight=1""",
            (time.time() + 60, owner),
        )
        conn.exec_driver_sql(
            """UPDATE preparation_state SET run_id=?, running=1,
            attempted=0, completed=0, failed=0, item_limit=?, stop_reason='', pid=?, started=?
            WHERE owner=?""",
            (run_id, batch_limit(), os.getpid(), time.time(), owner),
        )
    token = _current.set((owner, run_id))
    try:
        yield
    except BaseException as exc:
        with _db() as conn:
            conn.exec_driver_sql(
                "UPDATE preparation_state SET stop_reason=? WHERE owner=? AND run_id=?",
                (
                    str(exc)
                    if isinstance(exc, PreparationStopped)
                    else "Run interrupted; incomplete items remain pending.",
                    owner,
                    run_id,
                ),
            )
        raise
    finally:
        _current.reset(token)
        with _db() as conn:
            unfinished = conn.exec_driver_sql(
                "SELECT count(*) FROM preparation_attempts WHERE owner=? AND run_id=? AND inflight=1",
                (owner, run_id),
            ).scalar_one()
            conn.exec_driver_sql(
                "UPDATE preparation_attempts SET inflight=0,failures=failures+1,retry_at=? WHERE owner=? AND run_id=? AND inflight=1",
                (time.time() + 60, owner, run_id),
            )
            conn.exec_driver_sql(
                "UPDATE preparation_state SET failed=failed+? WHERE owner=? AND run_id=?",
                (unfinished, owner, run_id),
            )
            conn.exec_driver_sql(
                """UPDATE preparation_state SET running=0,
                stop_reason=CASE WHEN stop_reason='' THEN 'Batch finished; resume to analyze more.' ELSE stop_reason END
                WHERE owner=? AND run_id=?""",
                (owner, run_id),
            )


def pause(owner):
    owner = _account(owner)
    with _db() as conn:
        _ensure(conn, owner)
        conn.exec_driver_sql(
            "UPDATE preparation_state SET paused=1, stop_reason='Paused by user.' WHERE owner=?",
            (owner,),
        )


def check_dispatch(*, count_auxiliary=True):
    """Called immediately before central LLM reservation, including ancillary work."""
    active = _current.get()
    if not active:
        from zylch.llm.usage import current_call_site

        site = current_call_site()
        if site.startswith(("memory.", "task.", "dedup.", "f4.", "train.")) or site in {
            "canary",
            "preflight",
        }:
            raise PreparationStopped("Use bounded preparation to run paid analysis or maintenance.")
        return
    owner, run_id = active
    with _db() as conn:
        row = (
            conn.exec_driver_sql(
                "SELECT run_id, running, stop_reason, attempted, item_limit FROM preparation_state WHERE owner=?",
                (owner,),
            )
            .mappings()
            .one()
        )
        if row["run_id"] != run_id or not row["running"]:
            raise PreparationStopped("Preparation paused; already dispatched requests may finish.")
        if row["stop_reason"]:
            raise PreparationStopped(row["stop_reason"])
        if count_auxiliary and not _in_item.get():
            if row["attempted"] >= row["item_limit"]:
                raise PreparationStopped("Batch limit reached; resume starts another bounded run.")
            conn.exec_driver_sql(
                "UPDATE preparation_state SET attempted=attempted+1 WHERE owner=?", (owner,)
            )


def _admit(owner, stage, source):
    owner = _account(owner)
    active = _current.get()
    if not active:
        return None
    check_dispatch(count_auxiliary=False)
    run_id = active[1]
    with _db() as conn:
        state = (
            conn.exec_driver_sql("SELECT * FROM preparation_state WHERE owner=?", (owner,))
            .mappings()
            .one()
        )
        if state["run_id"] != run_id:
            raise PreparationStopped("Preparation paused.")
        item = (
            conn.exec_driver_sql(
                "SELECT * FROM preparation_attempts WHERE owner=? AND stage=? AND source=?",
                (owner, stage, source),
            )
            .mappings()
            .first()
        )
        if item and (item["failures"] >= 3 or item["retry_at"] > time.time() or item["inflight"]):
            return False
        if state["attempted"] >= state["item_limit"]:
            return False
        conn.exec_driver_sql(
            "INSERT OR IGNORE INTO preparation_attempts(owner,stage,source) VALUES (?,?,?)",
            (owner, stage, source),
        )
        conn.exec_driver_sql(
            "UPDATE preparation_attempts SET inflight=1,dispatched=0,run_id=? WHERE owner=? AND stage=? AND source=?",
            (run_id, owner, stage, source),
        )
        conn.exec_driver_sql(
            "UPDATE preparation_state SET attempted=attempted+1 WHERE owner=?", (owner,)
        )
    return run_id


def _finish(owner, stage, source, run_id, result, *, refused=False):
    owner = _account(owner)
    if not run_id:
        return
    with _db() as conn:
        if refused:
            dispatched = conn.exec_driver_sql(
                "SELECT dispatched FROM preparation_attempts WHERE owner=? AND stage=? AND source=? AND run_id=?",
                (owner, stage, source, run_id),
            ).scalar_one()
            refused = not dispatched
        if result:
            conn.exec_driver_sql(
                "UPDATE preparation_attempts SET failures=0,retry_at=0 WHERE owner=? AND stage=? AND source=? AND run_id=?",
                (owner, stage, source, run_id),
            )
        if refused or result:
            conn.exec_driver_sql(
                "UPDATE preparation_attempts SET inflight=0 WHERE owner=? AND stage=? AND source=? AND run_id=?",
                (owner, stage, source, run_id),
            )
        else:
            conn.exec_driver_sql(
                """UPDATE preparation_attempts SET inflight=0,
                failures=failures+1,retry_at=? + 60 * (failures+1)
                WHERE owner=? AND stage=? AND source=? AND run_id=?""",
                (time.time(), owner, stage, source, run_id),
            )
        field = "completed" if result else "failed"
        if not refused:
            conn.exec_driver_sql(
                f"UPDATE preparation_state SET {field}={field}+1 WHERE owner=?", (owner,)
            )


def bounded_item(stage=None):
    """Decorate memory bool processors or the task dict processor."""

    def decorate(fn):
        @functools.wraps(fn)
        async def wrapped(self, *args, **kwargs):
            if stage is None:
                kind = args[0] if args else kwargs["event_type"]
                data = args[1] if len(args) > 1 else kwargs["event_data"]
                key = "task:" + kind
            else:
                data = args[0] if args else next(iter(kwargs.values()))
                key = stage
            source = str(data.get("id") or "")
            if not source:
                raise PreparationStopped("Source ID missing; cannot safely track retries.")
            admitted = _admit(self.owner_id, key, source)
            if admitted is False:
                return None
            item_token = _in_item.set((_account(self.owner_id), key, source, admitted))
            try:
                result = await fn(self, *args, **kwargs)
            except BudgetError:
                _finish(self.owner_id, key, source, admitted, False, refused=True)
                if admitted:
                    with _db() as conn:
                        conn.exec_driver_sql(
                            "UPDATE preparation_state SET stop_reason='AI budget or billing unavailable; review spending status before resuming.' WHERE owner=? AND run_id=?",
                            (_account(self.owner_id), admitted),
                        )
                raise
            except BaseException:
                _finish(self.owner_id, key, source, admitted, False)
                raise
            finally:
                _in_item.reset(item_token)
            # A task decision is not durable until its caller writes the
            # resulting task mutation and processing checkpoint.
            if stage is not None or not result:
                _finish(self.owner_id, key, source, admitted, result)
            return result

        return wrapped

    return decorate


def status(owner):
    owner = _account(owner)
    with _db() as conn:
        _ensure(conn, owner)
        row = dict(
            conn.exec_driver_sql(
                "SELECT paused,running,attempted,completed,failed,item_limit AS 'limit',stop_reason,pid FROM preparation_state WHERE owner=?",
                (owner,),
            )
            .mappings()
            .one()
        )
        row["suspended"] = conn.exec_driver_sql(
            "SELECT count(*) FROM preparation_attempts WHERE owner=? AND failures>=3", (owner,)
        ).scalar_one()
        row["retry_waiting"] = conn.exec_driver_sql(
            "SELECT count(*) FROM preparation_attempts WHERE owner=? AND failures<3 AND retry_at>?",
            (owner, time.time()),
        ).scalar_one()
    if row["running"] and not _alive(row["pid"]):
        row["running"] = False
        row["stop_reason"] = "Previous run was interrupted; incomplete items remain pending."
    row.pop("pid")
    with _db() as conn:
        row["failed_items"] = [
            dict(item)
            for item in conn.exec_driver_sql(
                "SELECT stage,source,failures AS attempts,retry_at FROM preparation_attempts WHERE owner=? AND failures>0 ORDER BY failures DESC,stage,source LIMIT 100",
                (owner,),
            ).mappings()
        ]
    row["paused"] = bool(row["paused"])
    row["running"] = bool(row["running"])
    row["next_run_limit"] = batch_limit()
    if not row["running"]:
        row["limit"] = row["next_run_limit"]
    if row["attempted"] >= row["limit"] and not row["running"]:
        row["stop_reason"] = "Batch limit reached; resume starts another bounded run."
    return row


def reset_failure(owner, stage, source):
    owner = _account(owner)
    with _db() as conn:
        count = conn.exec_driver_sql(
            "DELETE FROM preparation_attempts WHERE owner=? AND stage=? AND source=? AND inflight=0",
            (owner, stage, source),
        ).rowcount
    return {"reset": bool(count)}


def bounded_operation(owner_from):
    """Give alternate worker/maintenance entrypoints the same admission scope."""

    def decorate(fn):
        @functools.wraps(fn)
        async def wrapped(*args, **kwargs):
            with preparation_run(owner_from(*args, **kwargs)):
                return await fn(*args, **kwargs)

        return wrapped

    return decorate


def record_dispatch():
    """Durably mark incurred/ambiguous work before the upstream HTTP dispatch."""
    active = _current.get()
    if not active:
        return
    owner, run_id = active
    with _db() as conn:
        row = (
            conn.exec_driver_sql(
                "SELECT run_id,running,stop_reason FROM preparation_state WHERE owner=?", (owner,)
            )
            .mappings()
            .one()
        )
        if row["run_id"] != run_id or not row["running"] or row["stop_reason"]:
            raise PreparationStopped("Preparation paused before dispatch; reservation retained.")
        item = _in_item.get()
        if item and item[3]:
            _, stage, source, _ = item
            conn.exec_driver_sql(
                "UPDATE preparation_attempts SET dispatched=1 WHERE owner=? AND stage=? AND source=? AND run_id=?",
                (owner, stage, source, run_id),
            )


def task_checkpoint(stage):
    """Complete an admitted task item only after the real storage write commits."""

    def decorate(fn):
        signature = inspect.signature(fn)

        @functools.wraps(fn)
        def wrapped(self, *args, **kwargs):
            bound = signature.bind(self, *args, **kwargs)
            sources = list(bound.arguments.values())[2]
            result = fn(self, *args, **kwargs)
            active = _current.get()
            if active:
                owner, run_id = active
                ids = sources if isinstance(sources, (list, tuple)) else [sources]
                for source in ids:
                    with _db() as conn:
                        changed = conn.exec_driver_sql(
                            "UPDATE preparation_attempts SET inflight=0,failures=0,retry_at=0 WHERE owner=? AND stage=? AND source=? AND run_id=? AND inflight=1",
                            (owner, stage, str(source), run_id),
                        ).rowcount
                        if changed:
                            conn.exec_driver_sql(
                                "UPDATE preparation_state SET completed=completed+1 WHERE owner=? AND run_id=?",
                                (owner, run_id),
                            )
            return result

        return wrapped

    return decorate
