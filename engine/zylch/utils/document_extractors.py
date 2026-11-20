"""Pure office-document text extraction shared by document readers."""

import logging
from typing import List

logger = logging.getLogger("zylch.tools.read_document_tool")


# Plain-text extensions we can read directly.
TEXT_EXTS = (".txt", ".md", ".csv", ".json", ".xml", ".log", ".yaml", ".yml")


def _extract_pdf_text(path: str) -> str:
    """Return the full text of a PDF, page by page, via pypdf.

    Raises ImportError if pypdf is not installed; the caller falls back
    to the legacy "use run_python" hint in that case.
    """
    from pypdf import PdfReader  # local import — keeps tool importable without pypdf

    reader = PdfReader(path)
    parts: List[str] = []
    for idx, page in enumerate(reader.pages, start=1):
        try:
            page_text = page.extract_text() or ""
        except Exception as e:
            logger.warning(f"[read_document] pypdf page {idx} extract failed: {e}")
            page_text = ""
        parts.append(f"--- page {idx} ---\n{page_text}")
    return "\n\n".join(parts)


def _extract_docx_text(path: str) -> str:
    """Return the text of a .docx file (paragraphs + table cells)."""
    from docx import Document  # local import — keeps tool importable without python-docx

    doc = Document(path)
    out: List[str] = []
    for para in doc.paragraphs:
        if para.text:
            out.append(para.text)
    for table in doc.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells]
            if any(cells):
                out.append("\t".join(cells))
    return "\n".join(out)


def _extract_xlsx_text(path: str) -> str:
    """Return the contents of an .xlsx workbook, sheet by sheet, as TSV-ish blocks."""
    from openpyxl import load_workbook  # local import — keeps tool importable without openpyxl

    wb = load_workbook(path, data_only=True, read_only=True)
    sections: List[str] = []
    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        rows: List[str] = []
        for row in ws.iter_rows(values_only=True):
            if not row:
                continue
            cells = ["" if v is None else str(v) for v in row]
            if any(c.strip() for c in cells):
                rows.append("\t".join(cells))
        sections.append(f"--- sheet: {sheet_name} ---\n" + "\n".join(rows))
    return "\n\n".join(sections)
