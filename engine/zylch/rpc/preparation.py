"""Preparation controls: free sync remains the separate sync.run method."""

import asyncio

from zylch.cli.utils import get_owner_id
from zylch.services import preparation


async def preparation_status(params, notify):
    """preparation.status() -> preparation state or result."""
    owner = get_owner_id()
    result = preparation.status(owner)
    from zylch.storage.database import get_engine

    # Count checkpoint slots, not messages: email memory and task are two units.
    counts = {}
    with get_engine().connect() as conn:
        tables = {
            r[0] for r in conn.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'")
        }
        for table in ("emails", "whatsapp_messages", "calendar_events", "mrcall_conversations"):
            if table not in tables:
                continue
            columns = {r[1] for r in conn.exec_driver_sql(f"PRAGMA table_info({table})")}
            for column in ("memory_processed_at", "task_processed_at"):
                if column not in columns:
                    continue
                pending, complete = conn.exec_driver_sql(
                    f"SELECT count(*)-count({column}),count({column}) FROM {table} WHERE owner_id=?",
                    (owner,),
                ).one()
                counts[f"{table}:{column}"] = {"pending": pending, "completed": complete}
    result["pending"] = sum(c["pending"] for c in counts.values())
    result["checkpoints_completed"] = sum(c["completed"] for c in counts.values())
    result["channels"] = counts
    result["unit"] = "source-stage attempts"
    return result


async def preparation_pause(params, notify):
    """preparation.pause() -> preparation state or result."""
    preparation.pause(get_owner_id())
    return await preparation_status({}, notify)


async def preparation_resume(params, notify):
    """preparation.resume() -> preparation state or result."""
    from zylch.services.process_pipeline import handle_process
    from zylch.tools.config import ToolConfig

    owner = get_owner_id()
    errors = []

    def progress(pct, message, eta=None):
        notify("preparation.progress", {"pct": pct, "message": message})

    summary = await asyncio.to_thread(
        asyncio.run,
        handle_process(
            ["--resume", "--analyze-only"],
            ToolConfig(),
            owner,
            progress=progress,
            errors_out=errors,
        ),
    )
    result = await preparation_status({}, notify)
    result["success"] = not errors
    result["summary"] = summary
    result["errors"] = [{"stage": e["stage"], "detail": str(e["error"])} for e in errors]
    return result


async def preparation_reset_failures(params, notify):
    """preparation.reset_failures(stage, source) -> preparation state or result."""
    stage, source = params.get("stage"), params.get("source")
    if not isinstance(stage, str) or not isinstance(source, str) or not stage or not source:
        raise ValueError("A stage and source ID are required to reset this item's failure history.")
    return preparation.reset_failure(get_owner_id(), stage, source)


METHODS = {
    "preparation.status": preparation_status,
    "preparation.pause": preparation_pause,
    "preparation.resume": preparation_resume,
    "preparation.reset_failures": preparation_reset_failures,
}
