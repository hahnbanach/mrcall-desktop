"""Fixed private-byte extraction wrapper for the constrained document worker."""

import io
from pathlib import Path
import os
import sys
import zipfile

MAX_DOCUMENT_BYTES = 16 * 1024 * 1024
MAX_TEXT_CHARACTERS = 2 * 1024 * 1024


class PrivateDiagnostics:
    def warning(self, *args: object, **kwargs: object) -> None:
        error = sys.exception()
        if isinstance(error, (MemoryError, RecursionError)):
            raise error


def extract(data: bytes, suffix: str) -> tuple[str, list[str]]:
    from zylch.utils import document_extractors as readers

    readers.logger = PrivateDiagnostics()
    limitations = ["Digital signatures have not been verified."]
    if suffix in readers.TEXT_EXTS:
        try:
            value = data.decode("utf-8")
        except UnicodeError:
            return "", limitations + ["Text encoding is unsupported; original bytes are retained."]
    elif suffix in {".pdf", ".docx", ".xlsx", ".xlsm"}:
        if suffix != ".pdf":
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                if sum(item.file_size for item in archive.infolist()) > MAX_DOCUMENT_BYTES:
                    return "", limitations + ["Extraction exceeds the document expansion limit."]
        else:
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(data))
            if len(reader.pages) > 512:
                return "", limitations + ["Extraction exceeds the PDF page limit."]
            if not any((page.extract_text() or "").strip() for page in reader.pages):
                return "", limitations + ["Scanned or unreadable PDF; OCR was not performed."]
        helper = {
            ".pdf": readers._extract_pdf_text,
            ".docx": readers._extract_docx_text,
            ".xlsx": readers._extract_xlsx_text,
            ".xlsm": readers._extract_xlsx_text,
        }[suffix]
        path = Path("original" + suffix)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(data)
            value = helper(str(path))
        finally:
            path.unlink(missing_ok=True)
    else:
        return "", limitations + ["Unsupported format; original bytes are retained."]
    if len(value) > MAX_TEXT_CHARACTERS:
        return "", limitations + ["Extraction exceeds the text limit; original bytes are retained."]
    if not value.strip():
        limitations.append("No readable text was extracted.")
    return value, limitations
