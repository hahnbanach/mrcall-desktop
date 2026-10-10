"""Lossless joins are unavailable for stores containing assignment authority."""

from sqlalchemy import inspect, select

from zylch.storage.assigned_task_models import AssignedTask, AssignedTaskEvent, AssignedTaskReceipt


def refusal_connection(conn) -> str | None:
    models = (AssignedTask, AssignedTaskEvent, AssignedTaskReceipt)
    try:
        schema = inspect(conn)
        names = set(schema.get_table_names())
        present = [model for model in models if model.__tablename__ in names]
        if present and len(present) != len(models):
            return "Company join refused: assignment schema is incomplete"
        for model in present:
            required = {column.name for column in model.__table__.columns}
            actual = {column["name"] for column in schema.get_columns(model.__tablename__)}
            if not required <= actual:
                return "Company join refused: assignment schema is incomplete"
            if conn.execute(select(model.__table__).limit(1)).first():
                return "Company join refused: assignment history requires a lossless merge"
    except Exception:
        return "Company join refused: assignment history could not be verified"
    return None


def refusal(engine) -> str | None:
    if engine is None:
        return None
    try:
        with engine.connect() as conn:
            return refusal_connection(conn)
    except Exception:
        return "Company join refused: assignment history could not be verified"
