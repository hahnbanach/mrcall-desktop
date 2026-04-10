"""Tool executors for the agentic task solve loop.

Each function takes args dict + context, returns a string result.
Read-only tools auto-execute; write tools need user approval
(handled by the caller in task_interactive.py).
"""

import logging
from typing import Dict

logger = logging.getLogger(__name__)


def execute_tool(
    name: str, args: Dict, store, owner_id: str,
) -> str:
    """Dispatch tool by name."""
    dispatch = {
        "search_emails": _search_emails,
        "search_memory": _search_memory,
        "update_memory": _update_memory,
        "draft_email": _draft_email,
        "run_python": _run_python,
        "send_email": _send_email,
        "download_attachment": _download_attachment,
        "read_document": _read_document,
        "web_search": _web_search,
        "send_whatsapp": _send_whatsapp,
        "send_sms": _send_sms,
    }
    fn = dispatch.get(name)
    if not fn:
        return f"Unknown tool: {name}"
    if fn in (_search_emails, _search_memory,
              _download_attachment, _send_sms,
              _update_memory):
        return fn(args, store, owner_id)
    return fn(args)


# ─── Read-only tools ─────────────────────────────────


def _search_emails(
    args: Dict, store, owner_id: str,
) -> str:
    """Search email archive."""
    query = args.get("query", "")
    limit = args.get("limit", 5)
    if not query:
        return "No query provided"

    try:
        from zylch.tools.email_archive import (
            EmailArchiveManager,
        )

        archive = EmailArchiveManager(
            gmail_client=None,
            owner_id=owner_id,
            supabase_storage=store,
        )
        results = archive.search_messages(
            query=query, limit=limit,
        )
        if not results:
            return f"No emails found for '{query}'"

        lines = [f"Found {len(results)} emails:"]
        for r in results:
            lines.append(
                f"- From: {r.get('from_email', '')}"
                f" | Subject: {r.get('subject', '')}"
                f" | Date: {r.get('date', '')}",
            )
            body = (
                r.get("body_plain", "")
                or r.get("snippet", "")
            )
            if body:
                lines.append(f"  {body}")
        return "\n".join(lines)
    except Exception as e:
        return f"Search failed: {e}"


def _search_memory(
    args: Dict, store, owner_id: str,
) -> str:
    """Search contact memory blobs."""
    query = args.get("query", "")
    if not query:
        return "No query provided"

    try:
        from zylch.memory import (
            EmbeddingEngine,
            HybridSearchEngine,
            MemoryConfig,
        )
        from zylch.storage.database import get_session

        config = MemoryConfig()
        engine = EmbeddingEngine(config)
        search = HybridSearchEngine(get_session, engine)

        results = search.search(
            owner_id=owner_id, query=query, limit=3,
        )
        if not results:
            return f"No memory found for '{query}'"

        lines = [f"Found {len(results)} memory entries:"]
        for r in results:
            content = (
                r.content if hasattr(r, "content")
                else r.get("content", "") if isinstance(r, dict)
                else str(r)
            )
            ns = (
                r.namespace if hasattr(r, "namespace")
                else ""
            )
            if ns:
                lines.append(f"--- [{ns}]")
            else:
                lines.append("---")
            lines.append(content)
        return "\n".join(lines)
    except Exception as e:
        return f"Memory search failed: {e}"


def _update_memory(
    args: Dict, store, owner_id: str,
) -> str:
    """Update a memory blob by searching and replacing content."""
    query = args.get("query", "")
    new_content = args.get("new_content", "")
    if not query or not new_content:
        return "Missing query or new_content"

    try:
        from zylch.memory import (
            EmbeddingEngine,
            HybridSearchEngine,
            MemoryConfig,
        )
        from zylch.memory.blob_storage import BlobStorage
        from zylch.storage.database import get_session

        config = MemoryConfig()
        engine = EmbeddingEngine(config)
        search = HybridSearchEngine(get_session, engine)
        blob_store = BlobStorage(get_session, engine)

        results = search.search(
            owner_id=owner_id, query=query, limit=1,
        )
        if not results:
            return f"No memory entry found for '{query}'"

        r = results[0]
        blob_id = (
            r.blob_id if hasattr(r, "blob_id")
            else r.get("blob_id", "")
        )
        old_content = (
            r.content if hasattr(r, "content")
            else r.get("content", "")
        )

        blob_store.update_blob(
            blob_id=blob_id,
            owner_id=owner_id,
            content=new_content,
            event_description="Manual correction via CLI",
        )

        return (
            f"Memory updated.\n"
            f"Was: {old_content[:100]}...\n"
            f"Now: {new_content[:100]}..."
        )
    except Exception as e:
        return f"Update failed: {e}"


def _download_attachment(
    args: Dict, store, owner_id: str,
) -> str:
    """Download attachments from an email."""
    import os

    email_id = args.get("email_id", "")
    if not email_id:
        return "No email_id provided"

    email = store.get_email_by_id(owner_id, email_id)
    if not email:
        return f"Email {email_id} not found"

    message_id = email.get("message_id", email_id)

    try:
        from zylch.email.imap_client import IMAPClient

        client = IMAPClient(
            email_addr=os.environ.get("EMAIL_ADDRESS", ""),
            password=os.environ.get("EMAIL_PASSWORD", ""),
            imap_host=os.environ.get("IMAP_HOST") or None,
        )
        attachments = client.fetch_attachments(message_id)
        if not attachments:
            return "No attachments found in this email"

        lines = [
            f"Downloaded {len(attachments)} attachment(s):",
        ]
        for a in attachments:
            lines.append(
                f"- {a['filename']} ({a['content_type']},"
                f" {a['size']} bytes) → {a['path']}",
            )
        return "\n".join(lines)
    except Exception as e:
        return f"Download failed: {e}"


# ─── Composing / drafting ────────────────────────────


def _draft_email(args: Dict) -> str:
    """Format a draft email for display."""
    to = args.get("to", "")
    subject = args.get("subject", "")
    body = args.get("body", "")
    return (
        f"DRAFT EMAIL:\n"
        f"To: {to}\n"
        f"Subject: {subject}\n\n"
        f"{body}"
    )


# ─── Code execution ─────────────────────────────────


def _run_python(args: Dict) -> str:
    """Execute Python code in subprocess with timeout."""
    import os
    import subprocess
    import tempfile

    code = args.get("code", "")
    if not code.strip():
        return "No code provided"

    output_dir = "/tmp/zylch"
    os.makedirs(output_dir, exist_ok=True)

    # Script temp file in /tmp (not /tmp/zylch) to avoid
    # showing up when user code scans the output directory
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py",
        delete=False,
    ) as f:
        f.write(code)
        script_path = f.name

    try:
        result = subprocess.run(
            ["python", script_path],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=output_dir,
        )
        parts = []
        if result.stdout.strip():
            parts.append(result.stdout.strip())
        if result.stderr.strip():
            parts.append(f"STDERR:\n{result.stderr.strip()}")
        if result.returncode != 0:
            parts.append(f"Exit code: {result.returncode}")
        return "\n".join(parts) if parts else "OK (no output)"
    except subprocess.TimeoutExpired:
        return "Timed out (60s limit)"
    except Exception as e:
        return f"Execution failed: {e}"
    finally:
        try:
            os.unlink(script_path)
        except OSError:
            pass


# ─── Send actions (need approval) ────────────────────


def _send_email(args: Dict) -> str:
    """Send email via SMTP."""
    import os

    to = args.get("to", "")
    subject = args.get("subject", "")
    body = args.get("body", "")
    in_reply_to = args.get("in_reply_to")

    if not to or not body:
        return "Missing 'to' or 'body'"

    try:
        from zylch.email.imap_client import IMAPClient

        client = IMAPClient(
            email_addr=os.environ.get("EMAIL_ADDRESS", ""),
            password=os.environ.get("EMAIL_PASSWORD", ""),
            imap_host=os.environ.get("IMAP_HOST") or None,
            smtp_host=os.environ.get("SMTP_HOST") or None,
        )
        result = client.send_message(
            to=to, subject=subject, body=body,
            in_reply_to=in_reply_to,
        )
        return (
            f"Email sent to {to}"
            f" (ID: {result.get('id', 'unknown')})"
        )
    except Exception as e:
        return f"Send failed: {e}"


def _send_whatsapp(args: Dict) -> str:
    """Send WhatsApp message via neonize."""
    import time

    phone = args.get("phone_number", "")
    message = args.get("message", "")
    if not phone or not message:
        return "Missing phone_number or message"

    try:
        from neonize.utils import build_jid

        from zylch.whatsapp.client import WhatsAppClient

        wa = WhatsAppClient()
        if not wa.has_session():
            return "WhatsApp not connected. Run zylch init."

        wa.connect(blocking=False)
        for _ in range(20):
            if wa.is_connected():
                break
            time.sleep(0.5)
        else:
            return "WhatsApp connection timeout"

        number = phone.lstrip("+")
        jid = build_jid(number)
        result = wa.send_message(jid, message)
        return f"WhatsApp sent to {phone}" if result else "Send failed"
    except ImportError:
        return "neonize not installed"
    except Exception as e:
        return f"WhatsApp failed: {e}"


def _send_sms(
    args: Dict, store, owner_id: str,
) -> str:
    """Send SMS via MrCall/StarChat."""
    phone = args.get("phone_number", "")
    message = args.get("message", "")
    if not phone or not message:
        return "Missing phone_number or message"

    try:
        creds = store.get_provider_credentials(
            owner_id, "mrcall",
        )
        if not creds or not creds.get("access_token"):
            return "MrCall not connected. Run zylch init."

        import httpx

        from zylch.config import settings

        url = (
            f"{settings.mrcall_base_url.rstrip('/')}"
            f"/mrcall/v1/sms/send"
        )
        response = httpx.post(
            url,
            headers={
                "auth": creds["access_token"],
                "Content-Type": "application/json",
            },
            json={"to": phone, "text": message},
            timeout=30,
        )
        response.raise_for_status()
        return f"SMS sent to {phone}"
    except Exception as e:
        return f"SMS failed: {e}"


# ─── Document reading ────────────────────────────────


def _read_document(args: Dict) -> str:
    """Read a file from user's document folders."""
    import glob
    import os

    filename = args.get("filename", "")
    if not filename:
        return "No filename provided"

    doc_paths = os.environ.get("DOCUMENT_PATHS", "")
    if not doc_paths:
        return (
            "No document folders configured."
            " Add DOCUMENT_PATHS to your profile .env"
        )

    paths = [
        os.path.expanduser(p.strip())
        for p in doc_paths.split(",")
        if p.strip()
    ]

    found = []
    for base in paths:
        pattern = os.path.join(base, "**", f"*{filename}*")
        found.extend(glob.glob(pattern, recursive=True))

    if not found:
        return (
            f"No file matching '{filename}' in:"
            f" {', '.join(paths)}"
        )

    path = found[0]
    ext = os.path.splitext(path)[1].lower()

    if ext == ".pdf":
        return (
            f"Found PDF: {path}\n"
            f"Use run_python to read it with pypdf."
        )
    elif ext in (".txt", ".md", ".csv", ".json", ".xml"):
        try:
            with open(path, "r", errors="replace") as f:
                content = f.read(10000)
            return f"File: {path}\n\n{content}"
        except Exception as e:
            return f"Could not read {path}: {e}"
    else:
        return (
            f"Found: {path} ({ext})\n"
            f"Use run_python to process this file."
        )


# ─── Web search ──────────────────────────────────────


def _web_search(args: Dict) -> str:
    """Search the web."""
    import os

    query = args.get("query", "")
    if not query:
        return "No query provided"

    try:
        from zylch.llm.client import LLMClient

        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        provider = os.environ.get(
            "SYSTEM_LLM_PROVIDER", "anthropic",
        )
        if not api_key:
            return "No API key for web search"

        # Use Sonnet for web search (cheaper, fast enough)
        model = "claude-sonnet-4-20250514"
        client = LLMClient(
            api_key=api_key, provider=provider,
            model=model,
        )
        response = client.create_message_sync(
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Search the web and answer: {query}"
                    ),
                },
            ],
            max_tokens=1000,
        )
        return response.content[0].text.strip()
    except Exception as e:
        return f"Web search failed: {e}"
