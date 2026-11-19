"""Delegated company-rule authoring, revision history and atomic change receipts.

This is client-grant authority, never evidence of an individual human decision.
Only existing canonical documents in an explicitly managed company are writable.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from typing import Any

from sqlalchemy import Column, MetaData, String, Table, Text, UniqueConstraint, insert, inspect, select

from zylch.services import operator_instructions as instructions
from zylch.services import operator_rule_proposals as bindings
from zylch.services import project_store as projects

_SCHEMA = MetaData()
CHANGES = Table(
    "operator_rule_changes", _SCHEMA,
    Column("id", String, primary_key=True),
    *(Column(name, String, nullable=False) for name in
      ("profile_uid", "space_id", "mailbox", "client_id", "grant_id", "request_key", "digest")),
    Column("receipt", Text, nullable=False),
    UniqueConstraint("profile_uid", "space_id", "mailbox", "client_id", "grant_id", "request_key"),
)
MAX_DOCUMENTS = 32
MAX_READ_BYTES = 262144


def _path(target: str) -> str:
    instructions.authorize(target)
    return target


def _managed(conn: Any, space: str) -> None:
    if not bindings.managed_in_transaction(conn, space):
        raise projects.ProjectError(-32046, "Canonical company rule setup is required before chat authoring")


def _row(conn: Any, path: str, revision: int | None = None) -> Any:
    current = projects.current(conn, instructions.PROJECT, path)
    if current is None:
        raise projects.ProjectError(-32044, "Existing canonical rule document is required")
    if revision is None:
        return current
    row = conn.execute(select(projects.R).where(
        projects.key(instructions.PROJECT, path, projects.R),
        projects.R.c.revision == revision)).mappings().one_or_none()
    if row is None:
        raise projects.ProjectError(-32044, "Rule revision does not exist")
    return row


def _document(row: Any) -> dict[str, Any]:
    projects.integer(row["revision"], 1)
    raw = bytes(row["content"])
    try:
        content = raw.decode("utf-8", errors="strict")
    except UnicodeError:
        raise projects.ProjectError(-32046, "Rule document encoding is invalid") from None
    bindings._content(content)
    if len(raw) != row["size"] or hashlib.sha256(raw).hexdigest() != row["sha256"]:
        raise projects.ProjectError(-32046, "Rule document integrity check failed")
    return {**projects.metadata(row), "content": content}


def read_rules(actor_binding: bindings.ActorBinding, path: str | None = None,
               revision: int | None = None) -> dict[str, Any]:
    actor = actor_binding
    bindings._check(actor)
    if revision is not None:
        projects.integer(revision, 1)
        if path is None:
            projects.invalid("A historic revision requires one document path")
    if path is not None:
        _path(path)
    with projects.connection(actor.company_space) as (conn, space):
        _managed(conn, space)
        if path is None:
            paths = conn.execute(select(projects.D.c.path).where(
                projects.D.c.project == instructions.PROJECT).order_by(projects.D.c.path)
                .limit(MAX_DOCUMENTS + 1)).scalars().all()
            if len(paths) > MAX_DOCUMENTS:
                raise projects.ProjectError(-32046, "Canonical rule set exceeds the bounded read limit")
            allowed = []
            for item in paths:
                instructions.validate_instruction_path(item)
                if instructions.is_minter() or item == instructions.mail_path(actor.mailbox):
                    allowed.append(item)
            paths = allowed
        else:
            paths = [path]
        docs = [_document(_row(conn, item, revision)) for item in paths]
        if sum(doc["size"] for doc in docs) > MAX_READ_BYTES:
            raise projects.ProjectError(-32046, "Rule text exceeds the bounded read limit; select one path")
        return {"space_id": space, "authority": "managed", "documents": docs}


def rule_history(target: str, limit: int, actor_binding: bindings.ActorBinding) -> dict[str, Any]:
    bindings._check(actor_binding)
    _path(target)
    projects.integer(limit, 1)
    if limit > 50:
        projects.invalid("Rule history limit must be 1 to 50")
    with projects.connection(actor_binding.company_space) as (conn, space):
        _managed(conn, space)
        current = _document(_row(conn, target))
        rows = conn.execute(select(projects.R).where(projects.key(
            instructions.PROJECT, target, projects.R)).order_by(projects.R.c.revision.desc())
            .limit(limit)).mappings().all()
        items = [{key: value for key, value in _document(row).items() if key != "content"}
                 for row in rows]
        return {"space_id": space, "path": target, "current_revision": current["revision"],
                "items": items, "limit": limit}


def _request_key(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{15,127}", value):
        projects.invalid("Request key must contain 16 to 128 ASCII identifier characters")
    return value


def _caller(actor: bindings.ActorBinding) -> Any:
    return ((CHANGES.c.profile_uid == actor.profile_uid) & (CHANGES.c.space_id == actor.company_space)
            & (CHANGES.c.mailbox == actor.mailbox) & (CHANGES.c.client_id == actor.client_id)
            & (CHANGES.c.grant_id == actor.grant_id))


def rule_change_status(actor_binding: bindings.ActorBinding, operation_id: str | None = None,
                       request_key: str | None = None) -> dict[str, Any]:
    bindings._check(actor_binding)
    if (operation_id is None) == (request_key is None):
        projects.invalid("Provide exactly one operation ID or request key")
    if request_key is not None:
        _request_key(request_key)
    if operation_id is not None and (not isinstance(operation_id, str) or not re.fullmatch(
            r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", operation_id)):
        projects.invalid("Invalid rule change identity")
    with projects.connection(actor_binding.company_space) as (conn, space):
        _managed(conn, space)
        row = None
        if inspect(conn).has_table(CHANGES.name):
            predicate = CHANGES.c.id == operation_id if operation_id else CHANGES.c.request_key == request_key
            row = conn.execute(select(CHANGES).where(_caller(actor_binding), predicate)).mappings().one_or_none()
        if row is None:
            raise projects.ProjectError(-32044, "Rule change does not exist for this connector grant")
        receipt = json.loads(row["receipt"])
        _path(receipt["target"])
        return receipt


def _change(request_key: str, target: str, base_revision: int, actor: bindings.ActorBinding,
            *, content: str | None = None, source_revision: int | None = None) -> dict[str, Any]:
    bindings._check(actor)
    _request_key(request_key)
    _path(target)
    projects.integer(base_revision, 1)
    if source_revision is not None:
        projects.integer(source_revision, 1)
    kind = "restore" if source_revision is not None else "save"
    raw = bindings._content(content) if kind == "save" else None
    payload = dict(target=target, kind=kind, base_revision=base_revision,
                   source_revision=source_revision, content=content)
    digest = bindings._digest(payload)
    with projects.connection(actor.company_space, write=True) as (conn, space):
        _managed(conn, space)
        current = _document(_row(conn, target))
        _SCHEMA.create_all(conn)
        previous = conn.execute(select(CHANGES).where(_caller(actor),
            CHANGES.c.request_key == request_key)).mappings().one_or_none()
        if previous is not None:
            if previous["digest"] != digest:
                raise projects.ProjectError(-32040, "Request key already belongs to a different rule change")
            return json.loads(previous["receipt"])
        if kind == "restore":
            raw = _document(_row(conn, target, source_revision))["content"].encode("utf-8")
        receipt = dict(operation_id=str(uuid.uuid4()), request_key=request_key, kind=kind,
                       target=target, base_revision=base_revision, source_revision=source_revision,
                       created_at=time.time(), authority="delegated_client_grant")
        if current["revision"] != base_revision:
            receipt.update(state="conflict", revision=current["revision"], sha256=current["sha256"])
        else:
            saved = projects.write_in_transaction(conn, space, instructions.PROJECT, target,
                                                  raw, base_revision, actor.mailbox)
            actual = _document(_row(conn, target))
            if (actual["revision"] != saved["revision"] or actual["sha256"] != hashlib.sha256(raw).hexdigest()
                    or actual["content"].encode("utf-8") != raw):
                raise projects.ProjectError(-32046, "Published rule readback failed")
            receipt.update(state="saved" if actual["revision"] != base_revision else "unchanged",
                           revision=actual["revision"], sha256=actual["sha256"])
        conn.execute(insert(CHANGES).values(id=receipt["operation_id"], profile_uid=actor.profile_uid,
            space_id=space, mailbox=actor.mailbox, client_id=actor.client_id, grant_id=actor.grant_id,
            request_key=request_key, digest=digest, receipt=json.dumps(receipt, sort_keys=True)))
        return receipt


def save_rule(request_key: str, target: str, content: str, base_revision: int,
              actor_binding: bindings.ActorBinding) -> dict[str, Any]:
    return _change(request_key, target, base_revision, actor_binding, content=content)


def restore_rule(request_key: str, target: str, source_revision: int, base_revision: int,
                 actor_binding: bindings.ActorBinding) -> dict[str, Any]:
    return _change(request_key, target, base_revision, actor_binding, source_revision=source_revision)
