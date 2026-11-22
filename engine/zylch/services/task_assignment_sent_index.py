"""Complete bounded Sent components, cached only for their exact scoped identity."""

import ctypes
import os
import sqlite3
import stat
import struct
import sys
import threading
import time
from collections import Counter
from pathlib import Path
from dataclasses import dataclass, field
from contextlib import ExitStack, contextmanager

from zylch.email import mailboxes
from . import task_assignment_mail as mail
from .task_assignment_types import AssignmentError


@dataclass
class Entry:
    lock: threading.RLock = field(default_factory=threading.RLock)
    folder: str = ""
    state: object = None
    headers: dict = field(default_factory=dict)
    component_key: object = None

    def invalidate(self):
        self.state = None
        self.headers = {}
        self.folder = ""
        self.component_key = None


_entries = {}
_entries_lock = threading.RLock()


def clear():
    with _entries_lock:
        for entry in _entries.values():
            with entry.lock:
                entry.invalidate()
        _entries.clear()


def _acquire(lock, deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0 or not lock.acquire(timeout=remaining):
        raise AssignmentError("Sent observation deadline exceeded")


def _entry(actor, box, scope, deadline):
    key = (actor.uid, actor.binding, box.id, scope)
    _acquire(_entries_lock, deadline)
    try:
        # Do not detach or tear down an entry still being used by another read.
        for old in list(_entries):
            if old != key and old[0] == actor.uid and old[2] == box.id:
                entry = _entries[old]
                _acquire(entry.lock, deadline)
                try:
                    entry.invalidate()
                    del _entries[old]
                finally:
                    entry.lock.release()
        if key not in _entries:
            if len(_entries) >= 64:
                for old, entry in list(_entries.items()):
                    if time.monotonic() >= deadline:
                        raise AssignmentError("Sent observation deadline exceeded")
                    if entry.lock.acquire(blocking=False):
                        try:
                            entry.invalidate()
                            del _entries[old]
                        finally:
                            entry.lock.release()
                        break
                else:
                    raise AssignmentError("Sent observation cache exceeds bounds")
            _entries[key] = Entry()
        return _entries[key]
    finally:
        _entries_lock.release()


def _component_headers(client, folder, scoped, root, state, deadline):
    keys = {root}
    for row in scoped:
        keys.add(mail.thread(row["message_id_header"]))
        keys.update(mail.references(row.get("references") or ""))
        keys.update(mail.references(row.get("in_reply_to") or ""))
    searched, observed_uids, headers = set(), set(), {}
    query_bytes, requests = 0, 0
    byte_budget = [32 * 1024 * 1024]
    while keys - searched:
        if time.monotonic() >= deadline:
            raise AssignmentError("Sent observation deadline exceeded")
        if len(keys) > mail.MAX_MESSAGES:
            raise AssignmentError("Sent component exceeds identity bounds")
        batch, terms, length = [], [], 2
        for key in sorted(keys - searched):
            quoted = key.replace("\\", "\\\\").replace('"', '\\"')
            term = f'(OR HEADER Message-ID "{quoted}" OR HEADER References "{quoted}" HEADER In-Reply-To "{quoted}")'
            if batch and (len(batch) >= 32 or length + len(term) + 5 > 16384):
                break
            batch.append(key)
            terms.append(term)
            length += len(term) + 5
        query = terms[-1]
        for term in reversed(terms[:-1]):
            query = "OR " + term + " " + query
        query = "(" + query + ")"
        query_bytes += len(query)
        requests += 1
        if requests > 128 or query_bytes > 4 * 1024 * 1024:
            raise AssignmentError("Sent component exceeds query bounds")
        found, observed = client.folder_headers(folder, deadline=deadline, criteria=query,
                                                max_messages=mail.MAX_MESSAGES,
                                                byte_budget=byte_budget)
        if observed != state:
            raise AssignmentError("Sent identity changed during component search")
        searched.update(batch)
        observed_uids.update(found)
        if len(observed_uids) > mail.MAX_MESSAGES:
            raise AssignmentError("Sent component exceeds message bounds")
        for uid, header in found.items():
            mid = header["message_id"]
            raw = ((header.get("references") or "") + " " + (header.get("in_reply_to") or "")).split()
            if mid not in keys and not keys.intersection(raw):
                continue
            mail.thread(mid)
            refs = mail.references(header.get("references") or "")
            reply = mail.references(header.get("in_reply_to") or "")
            if uid in headers:
                before = {k: v for k, v in headers[uid].items() if k != "flags"}
                after = {k: v for k, v in header.items() if k != "flags"}
                if before != after:
                    raise AssignmentError("Sent message identity changed")
            headers[uid] = header
            keys.update([mid, *refs, *reply])
    if client.examine_existing(folder, deadline=deadline) != state:
        raise AssignmentError("Sent identity changed during component search")
    return headers




def _archive_namespace_unchanged(notification, watched, until):
    consumed = 0
    try:
        while consumed < 65536 and time.monotonic() < until:
            try:
                raw = os.read(notification, min(4096, 65536 - consumed))
            except BlockingIOError:
                return time.monotonic() < until
            if not raw:
                return False
            consumed += len(raw)
            offset = 0
            while offset < len(raw):
                if len(raw) - offset < 16:
                    return False
                watch, mask, _, length = struct.unpack_from("=iIII", raw, offset)
                end = offset + 16 + length
                if end > len(raw) or mask & 0xEC00 or watch not in watched:
                    return False
                name = raw[offset + 16:end].split(b"\0", 1)[0]
                if mask & 0x3C0 and name in watched[watch]:
                    return False
                offset = end
        return False
    except OSError:
        return False


@contextmanager
def _archive_binding(database, until):
    notification = None
    descriptors = []
    try:
        path = Path(database)
        if (not sys.platform.startswith("linux") or not path.is_absolute()
                or path.parts[0] != "/" or len(path.parts) < 2 or ".." in path.parts):
            raise OSError("Unsupported archive binding")
        library = ctypes.CDLL(None, use_errno=True)
        initialize = library.inotify_init1
        initialize.argtypes, initialize.restype = [ctypes.c_int], ctypes.c_int
        add = library.inotify_add_watch
        add.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_uint32]
        add.restype = ctypes.c_int
        notification = initialize(os.O_NONBLOCK | os.O_CLOEXEC)
        if notification < 0:
            notification = None
            raise OSError("Archive namespace observation unavailable")
        flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW
        current = os.open("/", flags | os.O_DIRECTORY)
        descriptors.append(current)
        watched = {}
        for position, name in enumerate(path.parts[1:], start=1):
            if time.monotonic() >= until:
                raise OSError("Archive observation deadline exceeded")
            watch = add(notification, os.fsencode(f"/proc/self/fd/{current}"), 0x01002FC0)
            if watch < 0:
                raise OSError("Archive namespace observation unavailable")
            watched.setdefault(watch, set()).add(os.fsencode(name))
            current = os.open(name, flags | (os.O_DIRECTORY if position < len(path.parts) - 1 else os.O_NONBLOCK),
                              dir_fd=current)
            descriptors.append(current)
        if not stat.S_ISREG(os.fstat(current).st_mode):
            raise OSError("Archive binding is not a regular file")
        if not _archive_namespace_unchanged(notification, watched, until):
            raise OSError("Archive namespace changed during acquisition")
        yield f"file:/proc/self/fd/{current}?mode=ro", notification, watched
    finally:
        for descriptor in reversed(descriptors):
            try:
                os.close(descriptor)
            except OSError:
                pass
        if notification is not None:
            try:
                os.close(notification)
            except OSError:
                pass


def _archive_matches(actor, box, mid, deadline):
    from zylch.storage import database as db

    engine = db._engine
    until = min(deadline, time.monotonic() + 0.05)
    try:
        if engine is None or engine.url.get_backend_name() != "sqlite":
            return None
        database = engine.url.database
        if not database or database == ":memory:":
            return None
        with ExitStack() as resources:
            address, notification, watched = resources.enter_context(_archive_binding(database, until))
            remaining = until - time.monotonic()
            if remaining <= 0 or db._engine is not engine:
                return None
            connection = sqlite3.connect(address, uri=True, timeout=min(0.05, remaining))
            resources.callback(connection.close)
            connection.execute("PRAGMA query_only=ON")
            connection.set_progress_handler(
                lambda: int(time.monotonic() >= until or db._engine is not engine), 100
            )
            if (db._engine is not engine
                    or not _archive_namespace_unchanged(notification, watched, until)):
                return None
            found = connection.execute(
                "SELECT id FROM emails WHERE owner_id = ? AND mailbox_id = ? "
                "AND message_id_header = ? LIMIT 2", (actor.mailbox, box.id, mid)
            ).fetchall()
            if (db._engine is not engine
                    or not _archive_namespace_unchanged(notification, watched, until)):
                return None
            if time.monotonic() >= until:
                return None
            return len(found)
    except Exception:
        return None


def _correspondence(actor, box, root, scoped, mid, count, deadline, folder, state, uid=None):
    try:
        from zylch import observability_producers as diagnostics

        if diagnostics.store().owner_uid != actor.uid:
            return
        count = min(2, count)
        archive = _archive_matches(actor, box, mid, deadline) if count == 0 else None
        command = ("matched" if count == 1 else "scoped_multiple" if count == 2 else
                   "archive_unknown" if archive is None else "archive_absent" if archive == 0 else
                   "archive_present_unscoped" if archive == 1 else "archive_multiple_unscoped")
        metadata = {
            "command": "assignment.sent_correspondence." + command,
            "method": "tasks.assignment.project", "root_id": root,
            "request_revision": mail.digest({"actor_uid": actor.uid, "mailbox_id": box.id,
                                             "root": root, "known": mail.row_digest(scoped)}),
            "provider_id": mail.digest({"actor_uid": actor.uid, "mailbox_id": box.id,
                                        "folder": folder, "uidvalidity": state.uidvalidity,
                                        "uid": uid, "message_id": mid}),
            "error_file": "services/task_assignment_sent_index.py",
            "error_line": sys._getframe(1).f_lineno,
            "count": count, "available": count == 1 or archive is not None,
        }
        if archive is not None:
            metadata["pending_count"] = archive
        diagnostics.observe("authority", "result" if count == 1 else "failed",
                            reason="none" if count == 1 else "incomplete-input", **metadata)
    except Exception:
        pass


def candidates(actor, current, known, root, *, deadline, mailbox_scope=None):
    """Fresh complete Sent membership; never publish another owner's mail content."""
    from . import task_assignment_evidence as evidence

    scope = mail.mailbox_digest(actor)
    result = []
    for box in mail.evidence_boxes(actor, current, root, mailbox_scope):
        entry = _entry(actor, box, scope, deadline)
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not entry.lock.acquire(timeout=max(0, remaining)):
            raise AssignmentError("Sent observation deadline exceeded")
        readers = ExitStack()
        try:
            client = readers.enter_context(evidence.provider_client(actor, box, root, deadline))
            with client.provider_deadline(deadline):
                if not entry.folder:
                    entry.folder = client._find_sent_folder()
                if not entry.folder:
                    raise AssignmentError("Actual Sent folder unavailable")
                state = client.examine_existing(entry.folder, deadline=deadline)
                scoped = [row for row in known if row["mailbox_id"] == box.id]
                component_key = (root, mail.row_digest(scoped))
                if state != entry.state or component_key != entry.component_key:
                    entry.headers = {}
                    entry.state = None
                    entry.component_key = None
                    headers = _component_headers(client, entry.folder, scoped, root, state, deadline)
                    entry.headers, entry.state, entry.component_key = headers, state, component_key
                aliases = set(current["members"][actor.uid])
                related = []
                scoped = [row for row in known if row["mailbox_id"] == box.id]
                ancestry = {row["message_id_header"]: row for row in scoped}
                if len(ancestry) != len(scoped):
                    duplicate = next(mid for mid, count in Counter(
                        row["message_id_header"] for row in scoped
                    ).items() if count > 1)
                    _correspondence(actor, box, root, scoped, duplicate, 2, deadline,
                                    entry.folder, state)
                    raise AssignmentError("Ambiguous scoped RFC identity")
                provider_ids = set()
                duplicate_ids = set()
                for header in entry.headers.values():
                    mid = header["message_id"]
                    if mid in provider_ids:
                        duplicate_ids.add(mid)
                    provider_ids.add(mid)
                    ancestry[mid] = {**header, "mailbox_id": box.id}
                # Only purported exact-root ancestry can hold this thread. A
                # malformed unrelated historical message is not a global veto.
                children = {}
                component_ids = {root}
                for row in scoped:
                    component_ids.add(row["message_id_header"])
                    component_ids.update(mail.references(row.get("references") or ""))
                    component_ids.update(mail.references(row.get("in_reply_to") or ""))
                relevant_ids = set(component_ids)
                for header in [*ancestry.values(), *entry.headers.values()]:
                    mid = header.get("message_id") or header.get("message_id_header")
                    raw_refs = header.get("references") or ""
                    raw_reply = header.get("in_reply_to") or ""
                    if (component_ids & set((raw_refs + " " + raw_reply).split())
                            or mid in component_ids):
                        relevant_ids.add(mid)
                    for parent in (raw_refs + " " + raw_reply).split():
                        children.setdefault(parent, set()).add(mid)
                pending = list(relevant_ids)
                while pending:
                    for child in children.get(pending.pop(), ()):
                        if child not in relevant_ids:
                            relevant_ids.add(child)
                            pending.append(child)
                proof_ids = set(relevant_ids)
                pending = list(proof_ids)
                while pending:
                    header = ancestry.get(pending.pop())
                    if header is None:
                        continue
                    for parent in ((header.get("references") or "") + " " + (header.get("in_reply_to") or "")).split():
                        if parent in ancestry and parent not in proof_ids:
                            proof_ids.add(parent)
                            pending.append(parent)
                graph = mail.Ancestry(root, {mid: ancestry[mid] for mid in proof_ids if mid in ancestry}, deadline=deadline)
                if duplicate_ids & relevant_ids:
                    raise AssignmentError("Ambiguous Sent RFC identity")
                for uid, header in entry.headers.items():
                    if header["message_id"] not in relevant_ids:
                        continue
                    if time.monotonic() >= deadline:
                        raise AssignmentError("Sent observation deadline exceeded")
                    if not mail.addresses(header["from_email"]) <= aliases:
                        continue
                    if header["message_id"] == root:
                        continue
                    if mail.belongs({**header, "mailbox_id": box.id}, root, graph):
                        related.append(uid)
                if len(related) > 20:
                    raise AssignmentError("Reply candidates exceed bounds")
                fresh, observed = (client.folder_headers(entry.folder, deadline=deadline, uids=related, max_messages=max(state.exists, mail.MAX_MESSAGES))
                                   if related else ({}, entry.state))
                if observed != entry.state:
                    raise AssignmentError("Sent identity changed during observation")
                for uid in related:
                    header = fresh[uid]
                    if header != entry.headers[uid]:
                        # Flags may change; immutable identity/header bytes may not.
                        old = {k: v for k, v in entry.headers[uid].items() if k != "flags"}
                        now = {k: v for k, v in header.items() if k != "flags"}
                        if old != now:
                            raise AssignmentError("Sent message identity changed")
                    if "\\Draft" in header["flags"]:
                        continue
                    matches = [row for row in scoped if row["message_id_header"] == header["message_id"]]
                    _correspondence(actor, box, root, scoped, header["message_id"],
                                    len(matches), deadline, entry.folder, state, uid)
                    if len(matches) != 1:
                        result.append({"complete": False, "judgement": "UNKNOWN",
                                       "reason": "SENT_REPLY_NOT_SYNCED", "source": None})
                    else:
                        result.append({"source_id": matches[0]["id"]})
                if client.examine_existing(entry.folder, deadline=deadline) != entry.state:
                    raise AssignmentError("Sent identity changed during observation")
        except Exception:
            entry.invalidate()
            raise
        finally:
            try:
                readers.close()
            finally:
                entry.lock.release()
    if mail.mailbox_digest(actor) != scope:
        raise AssignmentError("Mailbox scope changed during observation")
    return result
