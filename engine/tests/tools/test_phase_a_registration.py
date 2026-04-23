"""Phase A registration smoke test.

Asserts the four new Tool subclasses (download_attachment, read_document,
run_python, update_memory) are discoverable and carry the expected schema
shape. Does not attempt a full ToolFactory.create_all_tools() run because
that requires IMAP / Supabase / Anthropic creds — we verify structural
registration via direct instantiation and the factory import surface.
"""

import pytest

from zylch.tools.download_attachment_tool import DownloadAttachmentTool
from zylch.tools.read_document_tool import ReadDocumentTool
from zylch.tools.run_python_tool import RunPythonTool
from zylch.tools.update_memory_tool import UpdateMemoryTool

EXPECTED = {
    "download_attachment",
    "read_document",
    "run_python",
    "update_memory",
}


def test_tool_names_match():
    dl = DownloadAttachmentTool(storage=object())
    rd = ReadDocumentTool()
    rp = RunPythonTool()
    um = UpdateMemoryTool()

    names = {dl.name, rd.name, rp.name, um.name}
    assert names == EXPECTED


def test_download_attachment_schema():
    dl = DownloadAttachmentTool(storage=object())
    schema = dl.get_schema()
    assert schema["name"] == "download_attachment"
    props = schema["input_schema"]["properties"]
    assert "email_id" in props
    assert schema["input_schema"]["required"] == ["email_id"]


def test_read_document_schema():
    rd = ReadDocumentTool()
    schema = rd.get_schema()
    assert schema["name"] == "read_document"
    props = schema["input_schema"]["properties"]
    assert "filename" in props
    assert schema["input_schema"]["required"] == ["filename"]


def test_run_python_schema_has_both_required_fields():
    rp = RunPythonTool()
    schema = rp.get_schema()
    assert schema["name"] == "run_python"
    assert set(schema["input_schema"]["required"]) == {"code", "description"}


def test_update_memory_schema():
    um = UpdateMemoryTool()
    schema = um.get_schema()
    assert schema["name"] == "update_memory"
    assert set(schema["input_schema"]["required"]) == {"query", "new_content"}


def test_factory_imports_new_tools():
    """Factory module should expose the new classes via import."""
    from zylch.tools.factory import (
        DownloadAttachmentTool as F_DL,
        ReadDocumentTool as F_RD,
        RunPythonTool as F_RP,
        UpdateMemoryTool as F_UM,
    )

    assert F_DL is DownloadAttachmentTool
    assert F_RD is ReadDocumentTool
    assert F_RP is RunPythonTool
    assert F_UM is UpdateMemoryTool


def test_approval_tools_canonical():
    from zylch.services.task_executor import APPROVAL_TOOLS

    assert APPROVAL_TOOLS == {
        "send_draft",
        "send_whatsapp_message",
        "send_sms",
        "update_memory",
        "run_python",
    }


@pytest.mark.asyncio
async def test_read_document_smoke(tmp_path):
    f = tmp_path / "phase_a.txt"
    f.write_text("ciao Phase A")
    rd = ReadDocumentTool()
    r = await rd.execute(filename=str(f))
    assert r.status.value == "success"
    assert r.data["text"] == "ciao Phase A"
