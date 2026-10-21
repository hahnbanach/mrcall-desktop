"""Complete bounded Sent components, cached only for their exact scoped identity."""

import threading
import time
from dataclasses import dataclass, field
from contextlib import ExitStack

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
        found, observed = client.folder_headers(
            folder,
            deadline=deadline,
            criteria=query,
            max_messages=mail.MAX_MESSAGES,
            byte_budget=byte_budget,
        )
        if observed != state:
            raise AssignmentError("Sent identity changed during component search")
        searched.update(batch)
        observed_uids.update(found)
        if len(observed_uids) > mail.MAX_MESSAGES:
            raise AssignmentError("Sent component exceeds message bounds")
        for uid, header in found.items():
            mid = header["message_id"]
            raw = (
                (header.get("references") or "") + " " + (header.get("in_reply_to") or "")
            ).split()
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


def candidates(actor, current, known, root, *, deadline):
    """Fresh complete Sent membership; never publish another owner's mail content."""
    from . import task_assignment_evidence as evidence

    scope = mail.mailbox_digest(actor)
    result = []
    for box in mail.configured(actor, current):
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
                    headers = _component_headers(
                        client, entry.folder, scoped, root, state, deadline
                    )
                    entry.headers, entry.state, entry.component_key = headers, state, component_key
                aliases = set(current["members"][actor.uid])
                related = []
                scoped = [row for row in known if row["mailbox_id"] == box.id]
                ancestry = {row["message_id_header"]: row for row in scoped}
                if len(ancestry) != len(scoped):
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
                    if (
                        component_ids & set((raw_refs + " " + raw_reply).split())
                        or mid in component_ids
                    ):
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
                    for parent in (
                        (header.get("references") or "") + " " + (header.get("in_reply_to") or "")
                    ).split():
                        if parent in ancestry and parent not in proof_ids:
                            proof_ids.add(parent)
                            pending.append(parent)
                graph = mail.Ancestry(
                    root,
                    {mid: ancestry[mid] for mid in proof_ids if mid in ancestry},
                    deadline=deadline,
                )
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
                fresh, observed = (
                    client.folder_headers(
                        entry.folder,
                        deadline=deadline,
                        uids=related,
                        max_messages=max(state.exists, mail.MAX_MESSAGES),
                    )
                    if related
                    else ({}, entry.state)
                )
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
                    matches = [
                        row for row in scoped if row["message_id_header"] == header["message_id"]
                    ]
                    if len(matches) != 1:
                        result.append(
                            {
                                "complete": False,
                                "judgement": "UNKNOWN",
                                "reason": "SENT_REPLY_NOT_SYNCED",
                                "source": None,
                            }
                        )
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
