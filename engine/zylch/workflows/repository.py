"""Serialized additive schema and profile-only transactions."""

from contextlib import contextmanager
from collections.abc import Iterator

from sqlalchemy import Connection, Engine, inspect
from sqlalchemy.orm import Session

from zylch.qonto.logging import private_scope
from zylch.storage.database import get_engine
from zylch.storage.migrations import MigrationStep, backup_sqlite, run_migrations
from zylch.workflows.errors import WorkflowError
from zylch.workflows.identity import Identity, check_same, current_identity
from zylch.workflows.models import Base, TABLES


def _backup_before_install(engine: Engine) -> None:
    names = set(inspect(engine).get_table_names())
    if "workflow_documents" not in names and names - {"schema_version"}:
        backup_sqlite(str(engine.url.database), "workflow-private-v1")


def _install(conn: Connection) -> None:
    Base.metadata.create_all(conn, tables=TABLES)


STEP = MigrationStep(
    "0006_workflow_private", _install, description="private workflow evidence and runs"
)


def ensure_tables(identity: Identity | None = None) -> None:
    identity = identity or current_identity()
    with private_scope():
        check_same(identity)
        engine = get_engine()
        run_migrations(
            engine,
            str(engine.url.database),
            ensure=(_backup_before_install,),
            steps=(STEP,),
        )
        check_same(identity)


@contextmanager
def profile_transaction(identity: Identity | None = None) -> Iterator[Session]:
    identity = identity or current_identity()
    with private_scope():
        try:
            ensure_tables(identity)
            with Session(get_engine(), expire_on_commit=False) as session:
                with session.begin():
                    session.connection().exec_driver_sql("BEGIN IMMEDIATE")
                    check_same(identity)
                    yield session
                    check_same(identity)
        except WorkflowError:
            raise
        except Exception:
            raise WorkflowError("operation_failed") from None
