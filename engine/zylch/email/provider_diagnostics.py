"""Bounded, payload-free native provider transitions; diagnostic failure grants no authority."""

import functools
import imaplib
import ssl
import threading
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar

_CURRENT = ContextVar("provider_diagnostic_observation", default=None)
_LIMIT = 2048


def current():
    return _CURRENT.get()


class Recorder:
    def __init__(self, root, deadline=None):
        from zylch.observability import current_context
        self.context = current_context()
        self.root, self.deadline = root, deadline
        self.started = time.monotonic()
        self.lock = threading.RLock()
        self.sequence = self.operations = self.generation = 0
        self.connections = {}
        self.active = {}
        self.records = []
        self.total = 0
        self.overflow = False
        self.first_fault = None

    def attach(self, connection):
        with self.lock:
            if connection is not None and connection not in self.connections:
                if len(self.connections) >= _LIMIT:
                    self.overflow = True
                    return (None, None)
                self.generation += 1
                self.connections[connection] = (uuid.uuid4().hex, self.generation)
            return self.connections.get(connection, (None, None))

    def progress(self, connection, value):
        if not value:
            return
        with self.lock:
            frame = self.active.get(connection)
            if frame is not None:
                frame["progress"] = min(2147483647, frame["progress"] + 1)
                frame["last"] = self.offset()
                self.overflow |= frame["progress"] == 2147483647

    def offset(self):
        value = max(0, (time.monotonic() - self.started) * 1000)
        self.overflow |= value > 3600000
        return min(3600000, value)

    def snapshot(self, client, connection, operation, phase, *, frame=None, cause="none", target=None):
        with self.lock:
            self.sequence += 1
            self.overflow |= self.sequence > 2147483647
            identity = self.connections.get(connection, (None, None))
            sock = getattr(connection, "sock", None)
            state, timeout, tls = "absent", None, "absent"
            if sock is not None:
                try:
                    state = "open" if sock.fileno() >= 0 else "closed"
                    seconds = sock.gettimeout()
                    timeout = None if seconds is None else min(3600000, max(0, seconds * 1000))
                    tls = "established" if isinstance(sock, ssl.SSLSocket) and state == "open" else "closed" if state == "closed" else "unknown"
                except (OSError, ValueError, AttributeError):
                    state, tls = "unknown", "unknown"
            pin = getattr(client, "_projection_connection", None)
            pinned = pin["connection"] if isinstance(pin, dict) and "connection" in pin else None
            active_connection = getattr(client, "_conn", None) or getattr(client, "_deadline_connection", None)
            deadline_connection = getattr(client, "_deadline_connection", None)
            reference = target if target is not None else self.connections.get(deadline_connection)
            current_identity = self.connections.get(active_connection)
            deadline_match = None if reference is None or reference[0] is None or current_identity is None else reference == current_identity
            native_state = getattr(connection, "state", "DISCONNECTED")
            if native_state not in {"DISCONNECTED", "NONAUTH", "AUTH", "SELECTED", "LOGOUT"}:
                native_state = "UNKNOWN"
            pending = getattr(connection, "tagged_commands", None)
            tags = min(65535, len(pending)) if isinstance(pending, dict) else None
            now = self.offset()
            value = {
                "version": 1, "connection_id": identity[0], "generation": identity[1],
                "sequence": min(2147483647, self.sequence),
                "operation_id": frame["id"] if frame else None,
                "operation": operation, "phase": phase, "command": frame["command"] if frame else None,
                "socket_state": state, "imap_state": native_state, "tls_state": tls,
                "pin_match": None if pinned is None or connection is None else pinned is connection,
                "deadline_match": deadline_match, "pending_tags": tags,
                "pending_commands": 1 if frame is not None else 0,
                "offset_ms": now, "duration_ms": min(3600000, max(0, now - frame["started"])) if frame and phase != "enter" else None,
                "remaining_ms": None if self.deadline is None else min(3600000, max(0, (self.deadline - time.monotonic()) * 1000)),
                "socket_timeout_ms": timeout, "cause": cause, "overflow": self.overflow,
                "inbound_progress_count": frame["progress"] if frame else None,
                "last_inbound_progress_offset_ms": frame["last"] if frame else None,
            }
            from zylch.observability_provider import validate
            return validate(value)

    def record(self, client, connection, operation, phase, **kwargs):
        try:
            with self.lock:
                terminal = phase in {"failed", "fired", "joined"}
                if self.total >= _LIMIT - (0 if terminal else 8):
                    if not self.overflow and self.total < _LIMIT:
                        self.overflow = True
                        overflow = self.snapshot(client, connection, "observation", "failed", cause="unknown")
                        self.records.append(overflow)
                        self.total += 1
                    self.overflow = True
                    return None
                value = self.snapshot(client, connection, operation, phase, **kwargs)
                self.records.append(value)
                self.total += 1
                if phase == "failed" and self.first_fault is None:
                    self.first_fault = dict(value)
                return value
        except Exception:
            self.overflow = True
            return None

    @contextmanager
    def operation(self, client, connection, operation, command=None):
        with self.lock:
            self.attach(connection)
            self.operations += 1
            frame = {"id": min(2147483647, self.operations), "started": self.offset(), "progress": 0, "last": None, "command": command}
            previous = self.active.get(connection)
            self.active[connection] = frame
        self.record(client, connection, operation, "enter", frame=frame)
        try:
            yield
        except BaseException as error:
            cause = "deadline" if self.deadline is not None and time.monotonic() >= self.deadline else "socket_error" if isinstance(error, OSError) else "protocol_error" if isinstance(error, imaplib.IMAP4.error) else "unknown"
            self.record(client, connection, operation, "failed", frame=frame, cause=cause)
            raise
        else:
            self.record(client, connection, operation, "exit", frame=frame, cause="normal")
        finally:
            with self.lock:
                if previous is None:
                    self.active.pop(connection, None)
                else:
                    self.active[connection] = previous

    def timer(self, client, action):
        connection = client._conn or client._deadline_connection
        target = self.connections.get(connection, (None, None))
        self.record(client, connection, "timer", "armed", target=target)
        def fire():
            active_connection = client._conn or client._deadline_connection
            frame = self.active.get(active_connection)
            self.record(client, active_connection, "timer", "fired", frame=frame, cause="deadline", target=target)
            action()
        return fire, target

    def flush(self):
        try:
            from zylch.observability import context
            from zylch.observability_producers import observe
            with self.lock:
                records, self.records = self.records, []
            with context(self.context):
                for value in records:
                    observe("acquisition", "failed" if value["phase"] == "failed" else "running", reason="timeout" if value["cause"] == "deadline" else "unknown" if value["phase"] == "failed" else "none", method="tasks.assignment.project", command="assignment.provider.transition", root_id=self.root, provider_diagnostic=value)
        except Exception:
            self.overflow = True


def _operation(command):
    return {"CAPABILITY": "connect", "LOGIN": "login", "EXAMINE": "examine", "SELECT": "examine", "UID_SEARCH": "search", "UID_FETCH": "fetch"}.get(command, "unknown")


def factory(base, client, recorder):
    class DiagnosticIMAP(base):
        def __init__(self, *args, **kwargs):
            recorder.attach(self)
            with recorder.operation(client, self, "connect"):
                super().__init__(*args, **kwargs)

        def _simple_command(self, name, *args):
            command = str(name).upper()
            if command == "UID":
                verb = str(args[0]).upper() if args else ""
                command = "UID_" + verb if verb in {"SEARCH", "FETCH"} else "OTHER"
            elif command not in {"CAPABILITY", "LOGIN", "EXAMINE", "SELECT", "NOOP"}:
                command = "OTHER"
            with recorder.operation(client, self, _operation(command), command):
                return super()._simple_command(name, *args)

        def shutdown(self):
            with recorder.operation(client, self, "dispose"):
                return super().shutdown()

        def read(self, *args, **kwargs):
            value = super().read(*args, **kwargs)
            try:
                recorder.progress(self, value)
            except Exception:
                recorder.overflow = True
            return value

        def readline(self, *args, **kwargs):
            value = super().readline(*args, **kwargs)
            try:
                recorder.progress(self, value)
            except Exception:
                recorder.overflow = True
            return value
    return DiagnosticIMAP


@contextmanager
def scope(root, deadline=None):
    active = current()
    if active is not None:
        if active.deadline is None:
            active.deadline = deadline
        yield active
        return
    recorder = Recorder(root, deadline)
    token = _CURRENT.set(recorder)
    try:
        yield recorder
    finally:
        recorder.flush()
        _CURRENT.reset(token)


def projection(function):
    @functools.wraps(function)
    def wrapped(root, *args, **kwargs):
        with scope(root):
            return function(root, *args, **kwargs)
    return wrapped


@contextmanager
def operation(client, connection, name):
    recorder = getattr(client, "_provider_diagnostic", None)
    if recorder is None:
        yield
    else:
        with recorder.operation(client, connection, name):
            yield


def client_operation(name):
    def decorate(function):
        @functools.wraps(function)
        def wrapped(client, *args, **kwargs):
            connection = client._conn or client._deadline_connection
            with operation(client, connection, name):
                return function(client, *args, **kwargs)
        return wrapped
    return decorate
