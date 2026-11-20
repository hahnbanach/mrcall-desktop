"""Extend the existing durable journal without losing pending operations."""

from .draft_operation_models import DraftOperation
from .migrations import MigrationStep


def apply(conn):
    sql = conn.exec_driver_sql(
        "SELECT sql FROM sqlite_master WHERE name='draft_provider_operations'"
    ).scalar()
    if sql is None:
        DraftOperation.__table__.create(conn)
    elif "'send'" not in sql:
        conn.exec_driver_sql("UPDATE draft_provider_operations SET version=version WHERE 0")
        conn.exec_driver_sql(
            "ALTER TABLE draft_provider_operations RENAME TO draft_provider_operations_old"
        )
        conn.exec_driver_sql("DROP INDEX uq_draft_operation_active_root")
        DraftOperation.__table__.create(conn)
        columns = ", ".join(column.name for column in DraftOperation.__table__.columns)
        conn.exec_driver_sql(
            f"INSERT INTO draft_provider_operations ({columns}) SELECT {columns} FROM draft_provider_operations_old"
        )
        conn.exec_driver_sql("DROP TABLE draft_provider_operations_old")


STEP = MigrationStep(
    id="0008_exact_operator_send",
    apply=apply,
    destructive=True,
    description="retain provider journal while admitting exact send operations",
)
