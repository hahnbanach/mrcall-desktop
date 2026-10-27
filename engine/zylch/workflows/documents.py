"""Bounded opaque document transfer and immutable private artifacts."""

import base64
import hashlib
import io
import re
import secrets
import tempfile
import time
import zipfile
from functools import wraps
from contextlib import contextmanager
from pathlib import Path
from collections.abc import Callable, Iterator
from typing import Any, ParamSpec, TypeVar, TYPE_CHECKING

from sqlalchemy.orm import Session

from sqlalchemy import func

from zylch.qonto.logging import private_scope
from zylch.workflows.document_async import (
    upload_chunk_async as upload_chunk_async,
    finish_upload_async as finish_upload_async,
)
from zylch.workflows.errors import WorkflowError
from zylch.workflows.identity import Identity, check_same, current_identity
from zylch.workflows.models import WorkflowArtifact, WorkflowDocument, WorkflowRun
from zylch.workflows.repository import ensure_tables, profile_transaction

if TYPE_CHECKING:
    from zylch.qonto.repository import Binding

P = ParamSpec("P")
R = TypeVar("R")
Record = WorkflowDocument | WorkflowRun | WorkflowArtifact
T = TypeVar("T", WorkflowDocument, WorkflowRun, WorkflowArtifact)

MAX_DOCUMENT_BYTES = 16 * 1024 * 1024
MAX_CHUNK_BYTES = 256 * 1024
MAX_PROFILE_BYTES = 128 * 1024 * 1024
MAX_DOCUMENTS = 128
MAX_TEXT_CHARACTERS = 2 * 1024 * 1024
MAX_TEXT_PAGE = 32000
MAX_PDF_PAGES = 512
BANK_FIELDS = ("uid", "host_id", "company_scope", "generation", "dataset_id", "organization_id")


def boundary(function: Callable[P, R]) -> Callable[P, R]:
    @wraps(function)
    def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
        with private_scope():
            try:
                return function(*args, **kwargs)
            except WorkflowError:
                raise
            except Exception:
                raise WorkflowError("operation_failed") from None

    return wrapped


def _name(name: str) -> str:
    if (
        not isinstance(name, str)
        or not 1 <= len(name) <= 255
        or name in {".", ".."}
        or "/" in name
        or "\\" in name
        or ":" in name
        or any(ord(char) < 32 for char in name)
    ):
        raise WorkflowError("invalid_input")
    return name


def _page(offset: int, limit: int, maximum: int) -> None:
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= maximum:
        raise WorkflowError("invalid_input")


def _owned(
    session: Session, model: type[T], identifier: str, identity: Identity, outcome: str
) -> T:
    if not isinstance(identifier, str) or not re.fullmatch(r"[A-Za-z0-9_-]{20,64}", identifier):
        raise WorkflowError(outcome)
    row = session.get(model, identifier)
    if row is None or row.uid != identity.uid:
        raise WorkflowError(outcome)
    return row


def _reject(data: bytes | str) -> None:
    from zylch.qonto.history import reject_known_evidence

    values = []
    if isinstance(data, bytes):
        values.append(base64.b64encode(data).decode("ascii"))
        try:
            values.append(data.decode("utf-8"))
        except UnicodeError:
            pass
    else:
        values.append(data)
    try:
        reject_known_evidence(values)
    except Exception:
        raise WorkflowError("bank_evidence_refused") from None


def _quota(session: Session, uid: str, size: int, document: bool = False) -> None:
    documents = session.query(WorkflowDocument).filter_by(uid=uid)
    total = documents.with_entities(func.coalesce(func.sum(WorkflowDocument.size), 0)).scalar()
    total += (
        session.query(func.coalesce(func.sum(WorkflowArtifact.size), 0)).filter_by(uid=uid).scalar()
    )
    if total + size > MAX_PROFILE_BYTES or (document and documents.count() >= MAX_DOCUMENTS):
        raise WorkflowError("quota_exceeded")


def _metadata(row: WorkflowDocument) -> dict[str, Any]:
    return {
        "document_id": row.id,
        "name": row.name,
        "size": row.size,
        "sha256": row.sha256,
        "state": row.state,
        "duplicate_of": row.duplicate_of,
        "provenance": row.provenance,
        "limitations": row.limitations,
        "text_length": len(row.text),
    }


@boundary
def prepare_upload(name: str, size: int, sha256: str) -> dict[str, Any]:
    name = _name(name)
    if type(size) is not int or not 0 <= size <= MAX_DOCUMENT_BYTES:
        raise WorkflowError("quota_exceeded")
    if not isinstance(sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", sha256):
        raise WorkflowError("invalid_input")
    identity = current_identity()
    with profile_transaction(identity) as session:
        _quota(session, identity.uid, size, document=True)
        row = WorkflowDocument(
            id=secrets.token_urlsafe(24),
            uid=identity.uid,
            name=name,
            size=size,
            sha256=sha256,
            state="uploading",
            original=b"",
            text="",
            limitations=[],
            provenance={"kind": "user_upload", "original_name": name},
            created_at=time.time(),
        )
        session.add(row)
        session.flush()
        return _metadata(row)


@boundary
def upload_chunk(document_id: str, offset: int, content_base64: str) -> dict[str, Any]:
    if (
        not isinstance(content_base64, str)
        or len(content_base64) > ((MAX_CHUNK_BYTES + 2) // 3) * 4
    ):
        raise WorkflowError("upload_invalid")
    try:
        content = base64.b64decode(content_base64, validate=True)
    except Exception:
        raise WorkflowError("upload_invalid") from None
    if not content or len(content) > MAX_CHUNK_BYTES or type(offset) is not int:
        raise WorkflowError("upload_invalid")
    identity = current_identity()
    with profile_transaction(identity) as session:
        row = _owned(session, WorkflowDocument, document_id, identity, "document_unavailable")
        if (
            row.state != "uploading"
            or offset != len(row.original)
            or offset + len(content) > row.size
        ):
            raise WorkflowError("upload_invalid")
        combined = row.original + content
        _reject(combined)
        row.original = combined
        return {"document_id": row.id, "received": len(combined)}


def _extract(data: bytes, name: str, profile: Path) -> tuple[str, list[str]]:
    from zylch.tools import read_document_tool as readers

    extension = Path(name).suffix.lower()
    limitations = ["Digital signatures have not been verified."]
    if extension in readers.TEXT_EXTS:
        try:
            text = data.decode("utf-8")
        except UnicodeError:
            return "", limitations + ["Text encoding is unsupported; original bytes are retained."]
    elif extension in {".pdf", ".docx", ".xlsx", ".xlsm"}:
        if extension != ".pdf":
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                if sum(item.file_size for item in archive.infolist()) > MAX_DOCUMENT_BYTES:
                    return "", limitations + ["Extraction exceeds the document expansion limit."]
        else:
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(data))
            if len(reader.pages) > MAX_PDF_PAGES:
                return "", limitations + ["Extraction exceeds the PDF page limit."]
            if not any((page.extract_text() or "").strip() for page in reader.pages):
                return "", limitations + ["Scanned or unreadable PDF; OCR was not performed."]
        helper = {
            ".pdf": readers._extract_pdf_text,
            ".docx": readers._extract_docx_text,
            ".xlsx": readers._extract_xlsx_text,
            ".xlsm": readers._extract_xlsx_text,
        }[extension]
        scratch_root = profile / "scratch"
        from zylch.utils.safe_paths import confine

        if scratch_root.is_symlink():
            raise WorkflowError("operation_failed")
        confine(str(scratch_root), [str(profile)])
        scratch_root.mkdir(mode=0o700, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="workflow-", dir=scratch_root) as scratch:
            path = Path(scratch) / ("original" + extension)
            path.write_bytes(data)
            text = helper(str(path))
    else:
        return "", limitations + ["Unsupported format; original bytes are retained."]
    if len(text) > MAX_TEXT_CHARACTERS:
        return "", limitations + ["Extraction exceeds the text limit; original bytes are retained."]
    if not text.strip():
        limitations.append("No readable text was extracted.")
    return text, limitations


@boundary
def finish_upload(document_id: str) -> dict[str, Any]:
    identity = current_identity()
    with profile_transaction(identity) as session:
        row = _owned(session, WorkflowDocument, document_id, identity, "document_unavailable")
        if row.state == "ready":
            return _metadata(row)
        if len(row.original) != row.size or hashlib.sha256(row.original).hexdigest() != row.sha256:
            raise WorkflowError("upload_invalid")
        _reject(row.original)
        try:
            text, limitations = _extract(row.original, row.name, identity.profile_dir)
        except Exception:
            text, limitations = "", [
                "Extraction failed; original bytes are retained.",
                "Digital signatures have not been verified.",
            ]
        _reject(text)
        duplicate = (
            session.query(WorkflowDocument)
            .filter_by(uid=identity.uid, sha256=row.sha256, state="ready")
            .first()
        )
        row.duplicate_of = duplicate.id if duplicate else None
        row.text, row.limitations, row.state = text, limitations, "ready"
        return _metadata(row)


@boundary
def read_document(document_id: str, offset: int = 0, limit: int = MAX_TEXT_PAGE) -> dict[str, Any]:
    _page(offset, limit, MAX_TEXT_PAGE)
    identity = current_identity()
    with profile_transaction(identity) as session:
        row = _owned(session, WorkflowDocument, document_id, identity, "document_unavailable")
        if row.state != "ready":
            raise WorkflowError("document_unavailable")
        text = row.text[offset : offset + limit]
        return {
            **_metadata(row),
            "text": text,
            "offset": offset,
            "next_offset": offset + len(text) if offset + len(text) < len(row.text) else None,
        }


@boundary
def download_document(
    document_id: str, offset: int = 0, limit: int = MAX_CHUNK_BYTES
) -> dict[str, Any]:
    _page(offset, limit, MAX_CHUNK_BYTES)
    identity = current_identity()
    with profile_transaction(identity) as session:
        row = _owned(session, WorkflowDocument, document_id, identity, "document_unavailable")
        if row.state != "ready":
            raise WorkflowError("document_unavailable")
        return {**_metadata(row), **_download(row.original, offset, limit)}


def _download(data: bytes, offset: int, limit: int) -> dict[str, Any]:
    part = data[offset : offset + limit]
    return {
        "content_base64": base64.b64encode(part).decode("ascii"),
        "offset": offset,
        "next_offset": offset + len(part) if offset + len(part) < len(data) else None,
    }


def binding_record(binding: "Binding") -> dict[str, Any]:
    return {key: getattr(binding, key) for key in BANK_FIELDS}


@contextmanager
def _artifact_transaction(identity: Identity, bank_binding: "Binding | None") -> Iterator[Session]:
    if bank_binding is None:
        with profile_transaction(identity) as session:
            yield session
    else:
        from zylch.qonto.history import require_managed
        from zylch.qonto.guard import commit_guard

        managed = require_managed()
        if managed.authority.uid != identity.uid or managed.binding != bank_binding:
            raise WorkflowError("binding_changed")
        ensure_tables(identity)
        with commit_guard(managed.authority, managed.binding) as session:
            check_same(identity)
            yield session
            check_same(identity)


@boundary
def store_artifact(
    identity: Identity, run_id: str, name: str, data: bytes, bank_binding: "Binding | None" = None
) -> dict[str, Any]:
    check_same(identity)
    name = _name(name)
    if not isinstance(data, bytes) or len(data) > MAX_DOCUMENT_BYTES:
        raise WorkflowError("quota_exceeded")
    binding = binding_record(bank_binding) if bank_binding is not None else None
    if bank_binding is None:
        _reject(data)
    with _artifact_transaction(identity, bank_binding) as session:
        run = _owned(session, WorkflowRun, run_id, identity, "artifact_unavailable")
        if run.bank_binding != binding:
            raise WorkflowError("binding_changed")
        _quota(session, identity.uid, len(data))
        row = WorkflowArtifact(
            id=secrets.token_urlsafe(24),
            uid=identity.uid,
            run_id=run.id,
            name=name,
            original=data,
            size=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
            provenance={
                "kind": "managed_bank_output" if binding else "workflow_output",
                "run_id": run.id,
            },
            bank_binding=binding,
            created_at=time.time(),
        )
        session.add(row)
        if bank_binding is not None:
            from zylch.qonto.history_receipts import retain

            retain(session, bank_binding, base64.b64encode(data).decode("ascii"), text=True)
            try:
                decoded = data.decode("utf-8")
            except UnicodeError:
                decoded = None
            if decoded is not None:
                retain(session, bank_binding, decoded, text=True)
        session.flush()
        run.artifact_ids = [*(run.artifact_ids or []), row.id]
        return {
            "artifact_id": row.id,
            "name": row.name,
            "size": row.size,
            "sha256": row.sha256,
            "provenance": row.provenance,
        }


async def get_artifact(
    artifact_id: str, offset: int = 0, limit: int = MAX_CHUNK_BYTES
) -> dict[str, Any]:
    with private_scope():
        try:
            _page(offset, limit, MAX_CHUNK_BYTES)
            identity = current_identity()
            with profile_transaction(identity) as session:
                row = _owned(
                    session, WorkflowArtifact, artifact_id, identity, "artifact_unavailable"
                )
            if row.bank_binding is not None:
                from zylch.qonto.reads import authorize
                from zylch.qonto.guard import commit_guard

                authority, binding = await authorize()
                if authority.uid != identity.uid or binding_record(binding) != row.bank_binding:
                    raise WorkflowError("binding_changed")
                with commit_guard(authority, binding):
                    check_same(identity)
                    result = _download(row.original, offset, limit)
            else:
                check_same(identity)
                result = _download(row.original, offset, limit)
            return {
                "artifact_id": row.id,
                "name": row.name,
                "size": row.size,
                "sha256": row.sha256,
                "provenance": row.provenance,
                **result,
            }
        except WorkflowError:
            raise
        except Exception:
            raise WorkflowError("artifact_unavailable") from None
