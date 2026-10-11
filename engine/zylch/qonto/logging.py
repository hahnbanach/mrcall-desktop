"""Metadata-only logging throughout an engine-managed financial chat scope."""

import logging
import re
from contextvars import ContextVar
from contextlib import contextmanager
from functools import wraps

_progress = ContextVar("finance_progress", default=None)
_private = ContextVar("finance_private_logs", default=False)
_safe_event = ContextVar("finance_safe_log", default=None)

_installed = False


def install():
    global _installed
    if _installed:
        return
    previous = logging.getLogRecordFactory()

    def record_factory(*args, **kwargs):
        record = previous(*args, **kwargs)
        from zylch.qonto import history

        if _private.get() or history.is_managed():
            event = _safe_event.get()
            if event is None:
                record.msg = "[finance] logger=%s level=%s event=processing"
                record.args = (record.name, record.levelname)
            else:
                record.msg = "[finance] tool=%s status=%s step=%d count=%d"
                record.args = event
            record.exc_info = None
            record.exc_text = None
            record.stack_info = None
        return record

    logging.setLogRecordFactory(record_factory)
    _installed = True


def tool_event(logger, *, name, status, step, count=0, registered=False):
    safe_name = name if registered and re.fullmatch(r"[a-z_]{1,64}", name) else "unknown_tool"
    callback = _progress.get()
    if callback is not None:
        callback({"tool": safe_name, "status": status, "step": step, "count": count})
    token = _safe_event.set((safe_name, status, step, count))
    try:
        logger.info("[finance] tool event")
    finally:
        _safe_event.reset(token)


@contextmanager
def private_scope():
    install()
    token = _private.set(True)
    try:
        yield
    finally:
        _private.reset(token)


def private_rpc(handler):
    @wraps(handler)
    async def wrapped(params, notify):
        with private_scope():
            return await handler(params, notify)

    return wrapped


@contextmanager
def progress_scope(callback):
    token = _progress.set(callback)
    try:
        yield
    finally:
        _progress.reset(token)
