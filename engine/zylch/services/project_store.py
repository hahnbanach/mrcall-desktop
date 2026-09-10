"""Byte-preserving, revisioned documents in the currently bound company store."""

import base64
import binascii
import hashlib
import re
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any, NoReturn

from sqlalchemy import Connection, Engine, and_, func, insert, select, update

from zylch.storage.models import ProjectDocument, ProjectRevision, ProjectSpace

D = ProjectDocument.__table__
R = ProjectRevision.__table__
S = ProjectSpace.__table__
META_COLUMNS = tuple(c for c in R.c if c.name != "content")
MAX_BYTES = 4 * 1024 * 1024


class ProjectError(Exception):
    """Public safe protocol error: messages never contain input or SQL values."""

    def __init__(self, code: int, message: str) -> None:
        self.code = code
        super().__init__(message)


def invalid(message: str = "Invalid project parameters") -> NoReturn:
    raise ProjectError(-32602, message)


def validate_project(project: Any) -> str:
    if not isinstance(project, str) or not re.fullmatch(
        r"[a-z0-9](?:[a-z0-9-]{0,98}[a-z0-9])?", project
    ):
        invalid("Project must be a lowercase ASCII slug of at most 100 characters")
    return project


def validate_path(path: Any) -> str:
    if not isinstance(path, str):
        invalid("Invalid relative document path")
    try:
        size = len(path.encode("utf-8"))
    except UnicodeError:
        invalid("Invalid relative document path")
    if (
        not path
        or size > 512
        or "\\" in path
        or ":" in path
        or any(ord(c) < 32 for c in path)
        or any(p in ("", ".", "..") for p in path.split("/"))
    ):
        invalid("Invalid relative document path")
    return path


def decode(content: Any) -> bytes:
    if not isinstance(content, str) or len(content) > 4 * ((MAX_BYTES + 2) // 3):
        invalid("Document exceeds 4 MiB or has invalid base64")
    try:
        raw = base64.b64decode(content, validate=True)
    except (ValueError, binascii.Error):
        invalid("Invalid base64 document")
    if len(raw) > MAX_BYTES:
        invalid("Document exceeds 4 MiB")
    return raw


def integer(value: Any, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        invalid("Invalid integer parameter")
    return value


def page(limit: int = 50, offset: int = 0) -> tuple[int, int]:
    integer(limit, 1)
    integer(offset)
    if limit > 100:
        invalid("Page limit exceeds 100")
    return limit, offset


def ensure_space(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(insert(S).prefix_with("OR IGNORE").values(id=1, space_id=str(uuid.uuid4())))


@contextmanager
def connection(
    expected_space: str | None = None, write: bool = False
) -> Iterator[tuple[Connection, str]]:
    from zylch.storage.database import current_memory_engine

    engine = current_memory_engine()
    if engine is None:
        raise ProjectError(-32043, "Company memory is unavailable")
    with engine.begin() as conn:
        if write:
            # First statement takes SQLite's writer lock, before any CAS read.
            conn.execute(update(S).where(S.c.id == 1).values(space_id=S.c.space_id))
        space = conn.execute(select(S.c.space_id).where(S.c.id == 1)).scalar_one()
        if expected_space is not None and expected_space != space:
            raise ProjectError(-32041, "Working copy belongs to a different company space")
        yield conn, space


def key(project: str, path: str, table: Any = D) -> Any:
    return and_(table.c.project == project, table.c.path == path)


def metadata(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        name: row[name]
        for name in ("project", "path", "revision", "sha256", "size", "author_uid", "created_at")
    }


def current(conn: Connection, project: str, path: str) -> Mapping[str, Any] | None:
    rev = conn.execute(select(D.c.revision).where(key(project, path))).scalar_one_or_none()
    if rev is None:
        return None
    return (
        conn.execute(select(R).where(key(project, path, R), R.c.revision == rev)).mappings().one()
    )


def append(
    conn: Connection, project: str, path: str, raw: bytes, revision: int, author: str
) -> dict[str, Any]:
    values = {
        "project": project,
        "path": path,
        "revision": revision,
        "content": raw,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "size": len(raw),
        "author_uid": author,
        "created_at": datetime.now(UTC).isoformat(),
    }
    conn.execute(insert(R).values(**values))
    if revision == 1:
        conn.execute(insert(D).values(project=project, path=path, revision=1))
    else:
        conn.execute(update(D).where(key(project, path)).values(revision=revision))
    return metadata(values)


def write(
    space_id: str, project: str, path: str, content_base64: str, expected_revision: int, author: str
) -> dict[str, Any]:
    validate_project(project)
    validate_path(path)
    integer(expected_revision)
    if not isinstance(space_id, str) or not space_id:
        invalid("Missing company space identity")
    raw = decode(content_base64)
    with connection(space_id, write=True) as (conn, space):
        old = current(conn, project, path)
        if old is not None and bytes(old["content"]) == raw:
            return {"space_id": space, **metadata(old)}
        if (old["revision"] if old else 0) != expected_revision:
            raise ProjectError(
                -32040, "Document revision conflict; read current revision before retrying"
            )
        return {
            "space_id": space,
            **append(conn, project, path, raw, expected_revision + 1, author),
        }


def create(space_id: str, project: str, files: dict[str, str], author: str) -> dict[str, Any]:
    validate_project(project)
    if not isinstance(space_id, str) or not space_id:
        invalid("Missing company space identity")
    if not isinstance(files, dict) or not 1 <= len(files) <= 16:
        invalid("Scaffold must contain 1 to 16 files")
    decoded = {validate_path(path): decode(content) for path, content in files.items()}
    if sum(map(len, decoded.values())) > 1024 * 1024:
        invalid("Scaffold exceeds 1 MiB")
    with connection(space_id, write=True) as (conn, space):
        if conn.execute(select(D.c.path).where(D.c.project == project).limit(1)).first():
            raise ProjectError(-32040, "Project already exists")
        out = [append(conn, project, path, raw, 1, author) for path, raw in sorted(decoded.items())]
        return {"space_id": space, "project": project, "files": out}


def read(project: str, path: str, revision: int | None = None) -> dict[str, Any]:
    validate_project(project)
    validate_path(path)
    if revision is not None:
        integer(revision, 1)
    with connection() as (conn, space):
        row = (
            current(conn, project, path)
            if revision is None
            else conn.execute(select(R).where(key(project, path, R), R.c.revision == revision))
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise ProjectError(-32044, "Project document or revision does not exist")
        return {
            "space_id": space,
            **metadata(row),
            "content_base64": base64.b64encode(row["content"]).decode("ascii"),
        }


def listing(
    project: str | None = None, path: str | None = None, limit: int = 50, offset: int = 0
) -> dict[str, Any]:
    limit, offset = page(limit, offset)
    if project is not None:
        validate_project(project)
    if path is not None:
        validate_path(path)
    with connection() as (conn, space):
        if project is None:
            query = select(D.c.project, func.count().label("file_count")).group_by(D.c.project)
            total = conn.execute(select(func.count()).select_from(query.subquery())).scalar_one()
            rows = conn.execute(query.order_by(D.c.project).limit(limit).offset(offset)).mappings()
            items = [dict(row) for row in rows]
        else:
            if not conn.execute(select(D.c.path).where(D.c.project == project).limit(1)).first():
                raise ProjectError(-32044, "Project does not exist")
            if path is not None:
                if (
                    conn.execute(
                        select(D.c.revision).where(key(project, path))
                    ).scalar_one_or_none()
                    is None
                ):
                    raise ProjectError(-32044, "Project document does not exist")
                query = select(*META_COLUMNS).where(key(project, path, R))
                ordering = (R.c.revision.desc(),)
            else:
                query = (
                    select(*META_COLUMNS)
                    .join(
                        D,
                        and_(
                            D.c.project == R.c.project,
                            D.c.path == R.c.path,
                            D.c.revision == R.c.revision,
                        ),
                    )
                    .where(R.c.project == project)
                )
                ordering = (R.c.path,)
            total = conn.execute(select(func.count()).select_from(query.subquery())).scalar_one()
            items = [
                metadata(row)
                for row in conn.execute(
                    query.order_by(*ordering).limit(limit).offset(offset)
                ).mappings()
            ]
        return {"space_id": space, "items": items, "total": total, "limit": limit, "offset": offset}
