from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import stat
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import Column, Float, Integer, MetaData, String, Table, Text, insert, select, update

from zylch.services import operator_instructions as instructions
from zylch.services import project_store as projects

_SEAL = object()
_SCHEMA = MetaData()
PROPOSALS = Table(
    "operator_rule_proposals", _SCHEMA,
    Column("id", String, primary_key=True), Column("profile_uid", String, nullable=False),
    Column("space_id", String, nullable=False), Column("mailbox", String, nullable=False),
    Column("client_id", String, nullable=False), Column("grant_id", String, nullable=False),
    Column("path", String, nullable=False), Column("content", Text, nullable=False),
    Column("base_revision", Integer, nullable=False), Column("digest", String, nullable=False),
    Column("state", String, nullable=False), Column("created_at", Float, nullable=False),
    Column("expires_at", Float, nullable=False), Column("published_revision", Integer),
    Column("published_sha256", String),
)
MANAGED = Table(
    "operator_instruction_management", _SCHEMA,
    Column("space_id", String, primary_key=True), Column("mode", String, nullable=False),
    Column("import_digest", String, nullable=False), Column("imported_at", Float, nullable=False),
    Column("profile_uid", String, nullable=False),
)
_PROOF_PATH: str | None = None
MAX_BYTES = 65536
PROPOSAL_TTL = 86400
PROOF_TTL = 900


@dataclass(frozen=True)
class ActorBinding:
    profile_uid: str
    company_space: str
    mailbox: str
    client_id: str
    grant_id: str
    _seal: object = field(repr=False, compare=False, default=None)


@dataclass(frozen=True)
class HumanBinding(ActorBinding):
    pass


def trusted_mcp_binding(*, profile_uid: str, company_space: str, mailbox: str,
                        client_id: str, grant_id: str) -> ActorBinding:
    return ActorBinding(profile_uid, company_space, instructions.normalize_mailbox(mailbox),
                        client_id, grant_id, _SEAL)


def trusted_native_binding(*, profile_uid: str, company_space: str, mailbox: str) -> HumanBinding:
    return HumanBinding(profile_uid, company_space, instructions.normalize_mailbox(mailbox),
                        "desktop", "native-owner", _SEAL)


def configure_import_proof(path: str | None) -> None:
    global _PROOF_PATH
    if path is not None and (not isinstance(path, str) or not os.path.isabs(path)):
        projects.invalid("Invalid protected import proof configuration")
    _PROOF_PATH = path


def _check(actor: ActorBinding, *, human: bool = False) -> None:
    if (not isinstance(actor, ActorBinding) or actor._seal is not _SEAL
            or (human and type(actor) is not HumanBinding)):
        raise projects.ProjectError(-32045, "Verified native owner confirmation is required")
    if (not all(isinstance(v, str) and v for v in (
            actor.profile_uid, actor.company_space, actor.mailbox, actor.client_id, actor.grant_id))
            or actor.profile_uid != os.environ.get("OWNER_ID")
            or actor.mailbox != instructions.own_mailbox()):
        raise projects.ProjectError(-32045, "Current profile binding has changed")
    instructions.mail_path(actor.mailbox)


def _path(target: str, actor: ActorBinding) -> str:
    if target not in (instructions.PROCEDURES, instructions.mail_path(actor.mailbox)):
        projects.invalid("Only company procedures and this mailbox identity are supported")
    return target


def _content(content: Any) -> bytes:
    if not isinstance(content, str):
        projects.invalid("Instruction content must be UTF8 text")
    try:
        raw = content.encode("utf-8", errors="strict")
    except UnicodeError:
        projects.invalid("Instruction content must be UTF8 text")
    if not raw or len(raw) > MAX_BYTES:
        projects.invalid("Instruction content must contain 1 to 65536 bytes")
    return raw


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True).encode("utf-8")).hexdigest()


def _schema(conn: Any) -> None:
    _SCHEMA.create_all(conn)


def managed_in_transaction(conn: Any, space_id: str) -> bool:
    from sqlalchemy import inspect
    if not inspect(conn).has_table(MANAGED.name):
        return False
    return conn.execute(select(MANAGED.c.mode).where(MANAGED.c.space_id == space_id)).scalar_one_or_none() == "managed"


def _view(row: Any) -> dict[str, Any]:
    return {key: row[key] for key in PROPOSALS.c.keys()}


def _expire(conn: Any, now: float) -> None:
    conn.execute(update(PROPOSALS).where(PROPOSALS.c.state == "pending",
                 PROPOSALS.c.expires_at <= now).values(state="expired"))


def _owned(conn: Any, proposal_id: str, actor: ActorBinding) -> Any:
    if not isinstance(proposal_id, str) or not re.fullmatch(
            r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", proposal_id):
        projects.invalid("Invalid rule proposal identity")
    row = conn.execute(select(PROPOSALS).where(PROPOSALS.c.id == proposal_id,
        PROPOSALS.c.space_id == actor.company_space, PROPOSALS.c.profile_uid == actor.profile_uid,
        PROPOSALS.c.mailbox == actor.mailbox)).mappings().one_or_none()
    if row is None:
        raise projects.ProjectError(-32044, "Rule proposal does not exist for this profile")
    if not isinstance(actor, HumanBinding) and (row["client_id"] != actor.client_id or row["grant_id"] != actor.grant_id):
        raise projects.ProjectError(-32045, "Rule proposal belongs to a different connector grant")
    return row


def propose(target: str, content: str, base_revision: int, actor_binding: ActorBinding) -> dict[str, Any]:
    actor = actor_binding
    _check(actor)
    path = _path(target, actor)
    raw = _content(content)
    projects.integer(base_revision)
    payload = dict(profile_uid=actor.profile_uid, space_id=actor.company_space, mailbox=actor.mailbox,
        client_id=actor.client_id, grant_id=actor.grant_id, path=path, content=raw.decode("utf-8"),
        base_revision=base_revision)
    digest = _digest(payload)
    with projects.connection(actor.company_space, write=True) as (conn, _space):
        _schema(conn)
        now = time.time()
        _expire(conn, now)
        old = conn.execute(select(PROPOSALS).where(PROPOSALS.c.digest == digest,
            PROPOSALS.c.state.in_(("pending", "confirmed")))).mappings().first()
        if old is not None:
            return _view(old)
        row = dict(**payload, id=str(uuid.uuid4()), digest=digest, state="pending", created_at=now,
                   expires_at=now + PROPOSAL_TTL, published_revision=None, published_sha256=None)
        conn.execute(insert(PROPOSALS).values(**row))
        return _view(row)


def status(proposal_id: str, actor_binding: ActorBinding) -> dict[str, Any]:
    _check(actor_binding)
    with projects.connection(actor_binding.company_space, write=True) as (conn, _space):
        _schema(conn)
        _expire(conn, time.time())
        return _view(_owned(conn, proposal_id, actor_binding))


def list_pending(actor_binding: ActorBinding) -> dict[str, Any]:
    _check(actor_binding, human=True)
    with projects.connection(actor_binding.company_space, write=True) as (conn, _space):
        _schema(conn)
        _expire(conn, time.time())
        rows = conn.execute(select(PROPOSALS).where(PROPOSALS.c.space_id == actor_binding.company_space,
            PROPOSALS.c.profile_uid == actor_binding.profile_uid, PROPOSALS.c.mailbox == actor_binding.mailbox,
            PROPOSALS.c.state == "pending").order_by(PROPOSALS.c.created_at).limit(100)).mappings()
        return {"items": [_view(row) for row in rows]}


def decide(proposal_id: str, expected_digest: str, decision: str,
           human_binding: HumanBinding) -> dict[str, Any]:
    actor = human_binding
    _check(actor, human=True)
    if decision not in ("confirm", "reject"):
        projects.invalid("Decision must be confirm or reject")
    with projects.connection(actor.company_space, write=True) as (conn, space):
        _schema(conn)
        _expire(conn, time.time())
        row = _owned(conn, proposal_id, actor)
        if row["digest"] != expected_digest:
            raise projects.ProjectError(-32040, "Rule proposal digest changed")
        if row["state"] != "pending":
            return _view(row)
        _path(row["path"], actor)
        if decision == "reject":
            conn.execute(update(PROPOSALS).where(PROPOSALS.c.id == proposal_id).values(state="rejected"))
        else:
            if not managed_in_transaction(conn, space):
                raise projects.ProjectError(-32046, "Explicit Desktop canonical import is required")
            instructions.authorize(row["path"])
            old = projects.current(conn, instructions.PROJECT, row["path"])
            if (old["revision"] if old else 0) != row["base_revision"]:
                conn.execute(update(PROPOSALS).where(PROPOSALS.c.id == proposal_id).values(state="conflict"))
            else:
                saved = projects.write_in_transaction(conn, space, instructions.PROJECT, row["path"],
                    row["content"].encode("utf-8"), row["base_revision"], actor.mailbox)
                actual = projects.current(conn, instructions.PROJECT, row["path"])
                if (actual is None or actual["revision"] != saved["revision"]
                        or actual["sha256"] != hashlib.sha256(row["content"].encode("utf-8")).hexdigest()):
                    raise projects.ProjectError(-32046, "Published rule readback failed")
                conn.execute(update(PROPOSALS).where(PROPOSALS.c.id == proposal_id).values(
                    state="confirmed", published_revision=actual["revision"], published_sha256=actual["sha256"]))
        return _view(_owned(conn, proposal_id, actor))


def _proof(actor: HumanBinding) -> tuple[dict[str, Any], str]:
    if not _PROOF_PATH:
        raise projects.ProjectError(-32046, "Protected canonical import proof is not configured")
    try:
        fd = os.open(_PROOF_PATH, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if info.st_uid != 0 or info.st_mode & 0o027 or not stat.S_ISREG(info.st_mode) or info.st_size > 3 * 1024 * 1024:
                raise ValueError()
            raw = stream.read(3 * 1024 * 1024 + 1)
        proof = json.loads(raw)
        now = time.time()
        if (not isinstance(proof, dict) or set(proof) != {"version", "profile_uid", "space_id", "mailbox",
            "created_at", "expires_at", "source_files", "documents", "compiler", "compiler_sha256", "compiled_paths"} or proof["version"] != 2
            or proof["profile_uid"] != actor.profile_uid or proof["space_id"] != actor.company_space
            or proof["mailbox"] != actor.mailbox
            or type(proof["created_at"]) not in (int, float) or type(proof["expires_at"]) not in (int, float)
            or not 0 <= now - proof["created_at"] <= PROOF_TTL
            or not now < proof["expires_at"] <= proof["created_at"] + PROOF_TTL
            or not isinstance(proof["source_files"], dict) or not proof["source_files"]
            or len(proof["source_files"]) > 100):
            raise ValueError()
        for path, sha in proof["source_files"].items():
            projects.validate_path(path)
            if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{64}", sha):
                raise ValueError()
        from cs.operator_import import COMPILER, compiler_sha256

        if (proof["compiler"] != COMPILER or proof["compiler_sha256"] != compiler_sha256()
                or "manifest.toml" not in proof["source_files"]):
            raise ValueError()
        docs = proof["documents"]
        if (not isinstance(docs, list) or not 1 <= len(docs) <= 32
                or proof["compiled_paths"] != sorted({d["path"] for d in docs})
                or len(proof["compiled_paths"]) != len(docs)):
            raise ValueError()
        for doc in docs:
            if set(doc) != {"path", "content_base64", "sha256", "base_revision", "base_sha256"}:
                raise ValueError()
            instructions.validate_instruction_path(doc["path"])
            raw_doc = projects.decode(doc["content_base64"])
            _content(raw_doc.decode("utf-8", errors="strict"))
            projects.integer(doc["base_revision"], 1)
            if hashlib.sha256(raw_doc).hexdigest() != doc["sha256"] or doc["base_sha256"] != doc["sha256"]:
                raise ValueError()
        return proof, hashlib.sha256(raw).hexdigest()
    except (OSError, ValueError, TypeError, KeyError, UnicodeError, projects.ProjectError):
        raise projects.ProjectError(-32046, "Protected canonical import proof is missing, stale or invalid") from None


def _reviewed_snapshot(conn: Any, actor: HumanBinding, docs: list[dict[str, Any]]) -> dict[str, Any]:
    # Renewable host attestations and UI lease times are not reviewed rule text.
    # Keep consent bound to the complete semantic snapshot and its exact owner.
    semantic = dict(profile_uid=actor.profile_uid, space_id=actor.company_space,
                    mailbox=actor.mailbox, documents=docs)
    return dict(**semantic, digest=_digest(semantic), expires_at=time.time() + PROOF_TTL,
                mode="managed" if managed_in_transaction(conn, actor.company_space) else "legacy")


def _published_preview(conn: Any, actor: HumanBinding) -> dict[str, Any]:
    paths = sorted(conn.execute(select(projects.D.c.path).where(
        projects.D.c.project == instructions.PROJECT)).scalars())
    if not 1 <= len(paths) <= 32:
        raise projects.ProjectError(-32046, "Complete published instructions are unavailable")
    docs = []
    for path in paths:
        instructions.validate_instruction_path(path)
        row = projects.current(conn, instructions.PROJECT, path)
        if row is None:
            raise projects.ProjectError(-32040, "Published instructions changed")
        projects.integer(row["revision"], 1)
        raw = bytes(row["content"])
        try:
            text = raw.decode("utf-8", errors="strict")
        except UnicodeError:
            raise projects.ProjectError(-32046, "Published instruction encoding is invalid") from None
        _content(text)
        if hashlib.sha256(raw).hexdigest() != row["sha256"]:
            raise projects.ProjectError(-32046, "Published instruction integrity check failed")
        docs.append(dict(path=path, revision=row["revision"], sha256=row["sha256"], content=text))
    return _reviewed_snapshot(conn, actor, docs)


def _import_preview(conn: Any, actor: HumanBinding) -> dict[str, Any]:
    proof, proof_sha = _proof(actor)
    published_paths = set(conn.execute(select(projects.D.c.path).where(
        projects.D.c.project == instructions.PROJECT)).scalars())
    if published_paths != set(proof["compiled_paths"]):
        raise projects.ProjectError(-32040, "Complete published instruction path set changed")
    docs = []
    for doc in sorted(proof["documents"], key=lambda item: item["path"]):
        row = projects.current(conn, instructions.PROJECT, doc["path"])
        if (row is None or row["revision"] != doc["base_revision"] or row["sha256"] != doc["base_sha256"]
                or bytes(row["content"]) != base64.b64decode(doc["content_base64"], validate=True)):
            raise projects.ProjectError(-32040, "Complete compiler snapshot differs from published instructions")
        docs.append(dict(path=doc["path"], revision=row["revision"], sha256=row["sha256"],
                         content=bytes(row["content"]).decode("utf-8")))
    return dict(**_reviewed_snapshot(conn, actor, docs), proof_sha256=proof_sha)


def preview_import(human_binding: HumanBinding) -> dict[str, Any]:
    _check(human_binding, human=True)
    if not instructions.is_minter():
        raise projects.ProjectError(-32045, "Company owner is required for canonical import")
    with projects.connection(human_binding.company_space) as (conn, _space):
        return _published_preview(conn, human_binding)


def confirm_import(expected_digest: str, human_binding: HumanBinding) -> dict[str, Any]:
    _check(human_binding, human=True)
    if not instructions.is_minter():
        raise projects.ProjectError(-32045, "Company owner is required for canonical import")
    with projects.connection(human_binding.company_space, write=True) as (conn, space):
        _schema(conn)
        preview = _import_preview(conn, human_binding)
        if preview["digest"] != expected_digest:
            raise projects.ProjectError(-32040, "Canonical import preview changed")
        if not managed_in_transaction(conn, space):
            conn.execute(insert(MANAGED).values(space_id=space, mode="managed", import_digest=expected_digest,
                         imported_at=time.time(), profile_uid=human_binding.profile_uid))
        return dict(preview, mode="managed")
