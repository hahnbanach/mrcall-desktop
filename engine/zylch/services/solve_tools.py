"""Tool executors for the agentic task solve loop.

Each function takes args dict + context, returns a string result.
Read-only tools auto-execute; write tools need user approval
(handled by the caller in task_interactive.py).
"""

import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)


def execute_tool(
    name: str,
    args: Dict,
    store,
    owner_id: str,
) -> str:
    """Dispatch tool by name."""
    dispatch = {
        "search_emails": _search_emails,
        "search_memory": _search_memory,
        "update_memory": _update_memory,
        "run_python": _run_python,
        "send_email": _send_email,
        "download_attachment": _download_attachment,
        "read_document": _read_document,
        "web_search": _web_search,
        "send_whatsapp": _send_whatsapp,
        "send_sms": _send_sms,
        "list_fact_categories": _list_fact_categories,
        "get_facts_by_category": _get_facts_by_category,
    }
    fn = dispatch.get(name)
    if not fn:
        return f"Unknown tool: {name}"
    # `_send_email` and `_send_whatsapp` need ``store`` + ``owner_id`` to
    # write the just-sent outbound message back into the local DB. Without
    # that the next `tasks.reanalyze` rebuilds the thread history without
    # seeing the user's reply and keeps the task open until the next full
    # ``update.run`` does an IMAP sync of the Sent folder.
    # `_list_fact_categories` / `_get_facts_by_category` likewise read the
    # owner-scoped facts store.
    if fn in (
        _search_emails,
        _search_memory,
        _download_attachment,
        _send_sms,
        _update_memory,
        _send_email,
        _send_whatsapp,
        _list_fact_categories,
        _get_facts_by_category,
    ):
        return fn(args, store, owner_id)
    return fn(args)


# ─── Facts (category-gated, read-only) ───────────────


def _list_fact_categories(args: Dict, store, owner_id: str) -> str:
    """Enumerate the business-fact categories the user has stored."""
    from zylch.services.facts_store import list_categories

    cats = list_categories(owner_id)
    if not cats:
        return "No fact categories stored yet."
    lines = [f"- {c['category']} ({c['count']} fact(s))" for c in cats]
    return (
        "Fact categories (pick the one that fits the request, then call "
        "get_facts_by_category to load ALL and ONLY its facts):\n" + "\n".join(lines)
    )


def _get_facts_by_category(args: Dict, store, owner_id: str) -> str:
    """Return all and only the facts in one category (exact match)."""
    from zylch.services.facts_store import get_facts_by_category

    category = (args.get("category") or "").strip()
    if not category:
        return "No category provided"
    facts = get_facts_by_category(owner_id, category)
    if not facts:
        return (
            f"No facts found in category '{category}'. Call "
            f"list_fact_categories to see the available categories."
        )
    blocks = [f["content"] for f in facts]
    return f"All facts in category '{category}' ({len(facts)}):\n\n" + "\n\n".join(blocks)


# ─── Read-only tools ─────────────────────────────────


def _search_emails(
    args: Dict,
    store,
    owner_id: str,
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
            query=query,
            limit=limit,
        )
        if not results:
            return f"No emails found for '{query}'"

        lines = [f"Found {len(results)} emails:"]
        for r in results:
            email_id = r.get("id", "")
            lines.append(
                f"- ID: {email_id}"
                f" | From: {r.get('from_email', '')}"
                f" | Subject: {r.get('subject', '')}"
                f" | Date: {r.get('date', '')}",
            )
            body = r.get("body_plain", "") or r.get("snippet", "")
            if body:
                lines.append(f"  {body}")
        return "\n".join(lines)
    except Exception as e:
        return f"Search failed: {e}"


def _search_memory(
    args: Dict,
    store,
    owner_id: str,
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
            owner_id=owner_id,
            query=query,
            limit=3,
        )
        if not results:
            return f"No memory found for '{query}'"

        lines = [f"Found {len(results)} memory entries:"]
        for r in results:
            content = (
                r.content
                if hasattr(r, "content")
                else r.get("content", "") if isinstance(r, dict) else str(r)
            )
            ns = r.namespace if hasattr(r, "namespace") else ""
            if ns:
                lines.append(f"--- [{ns}]")
            else:
                lines.append("---")
            lines.append(content)
        return "\n".join(lines)
    except Exception as e:
        return f"Memory search failed: {e}"


def _update_memory(
    args: Dict,
    store,
    owner_id: str,
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
            owner_id=owner_id,
            query=query,
            limit=1,
        )
        if not results:
            return f"No memory entry found for '{query}'"

        r = results[0]
        blob_id = r.blob_id if hasattr(r, "blob_id") else r.get("blob_id", "")
        old_content = r.content if hasattr(r, "content") else r.get("content", "")

        blob_store.update_blob(
            blob_id=blob_id,
            owner_id=owner_id,
            content=new_content,
            event_description="Manual correction via CLI",
        )

        return f"Memory updated.\n" f"Was: {old_content[:100]}...\n" f"Now: {new_content[:100]}..."
    except Exception as e:
        return f"Update failed: {e}"


def _download_attachment(
    args: Dict,
    store,
    owner_id: str,
) -> str:
    """Download attachments from an email."""
    import os

    email_id = args.get("email_id", "")
    if not email_id:
        return "No email_id provided"

    # Try internal UUID first, then fall back to gmail_id
    email = store.get_email_by_supabase_id(owner_id, email_id)
    if not email:
        email = store.get_email_by_id(owner_id, email_id)
    if not email:
        return f"Email {email_id} not found"

    # IMAP attachment fetch keys off the RFC822 Message-ID header. The
    # `emails` table has NO `message_id` column (only `gmail_id` +
    # `message_id_header`), so `email.get("message_id")` is always None —
    # the old `email.get("message_id", email_id)` therefore fell back to
    # the internal UUID and the `HEADER Message-ID "<uuid>"` search never
    # matched (→ "no attachments found"). Mirror the canonical
    # DownloadAttachmentTool's resolution order.
    message_id = email.get("message_id") or email.get("message_id_header") or email_id

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
                f"- {a['filename']} ({a['content_type']}," f" {a['size']} bytes) → {a['path']}",
            )
        return "\n".join(lines)
    except Exception as e:
        return f"Download failed: {e}"


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
        mode="w",
        suffix=".py",
        delete=False,
    ) as f:
        f.write(code)
        script_path = f.name

    try:
        import sys

        python = sys.executable or "python3"
        result = subprocess.run(
            [python, script_path],
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


def _send_email(args: Dict, store, owner_id: str) -> str:
    """Send email via SMTP, then mirror the outbound row into the local DB.

    Without the local mirror, `build_thread_history` (consumed by
    `tasks.reanalyze` AND the memory/task workers) doesn't see the
    user's reply until the next full `update.run` IMAP-syncs the Sent
    folder — so right after a solve sends the answer, reanalyze still
    decides the task is open. Mario reported this: solve sends mail,
    task stays open until a global Update.

    The mirror upserts on ``(owner_id, gmail_id)`` where ``gmail_id`` is
    the RFC 5322 ``Message-ID`` header — the same key the IMAP archive
    uses (``email_archive.py:301``). When IMAP later pulls the same
    message from the Sent folder it lands on the same row and just
    refreshes labels/date.
    """
    import os

    to = args.get("to", "")
    subject = args.get("subject", "")
    body = args.get("body", "")
    in_reply_to = args.get("in_reply_to")

    if not to or not body:
        return "Missing 'to' or 'body'"

    try:
        from zylch.email.imap_client import IMAPClient

        email_addr = os.environ.get("EMAIL_ADDRESS", "")
        client = IMAPClient(
            email_addr=email_addr,
            password=os.environ.get("EMAIL_PASSWORD", ""),
            imap_host=os.environ.get("IMAP_HOST") or None,
            smtp_host=os.environ.get("SMTP_HOST") or None,
        )
        result = client.send_message(
            to=to,
            subject=subject,
            body=body,
            in_reply_to=in_reply_to,
        )
        sent_id = result.get("id") or ""
        # Best-effort local mirror. Never let a storage hiccup turn a
        # successful send into a failure — return the same string we
        # used to return.
        try:
            _mirror_sent_email_locally(
                store=store,
                owner_id=owner_id,
                sent_id=sent_id,
                from_email=email_addr,
                to=to,
                subject=subject,
                body=body,
                in_reply_to=in_reply_to,
            )
        except Exception as e:
            logger.warning(f"[send_email] local mirror failed: {e}", exc_info=True)
        return f"Email sent to {to} (ID: {sent_id or 'unknown'})"
    except Exception as e:
        return f"Send failed: {e}"


def _mirror_sent_email_locally(
    store,
    owner_id: str,
    sent_id: str,
    from_email: str,
    to: str,
    subject: str,
    body: str,
    in_reply_to: Optional[str],
) -> None:
    """Append the outbound email to the ``emails`` table.

    Thread resolution: if ``in_reply_to`` references an email already in
    the local DB, reuse its ``thread_id`` so the new row joins the
    existing conversation. Otherwise the message stands on its own as a
    new thread, keyed on its own Message-ID — matching what IMAP would
    pick if it ever re-pulled the message (``imap_client.py:406``: "use
    References chain or Message-ID").
    """
    from datetime import datetime, timezone

    from zylch.storage.database import get_session
    from zylch.storage.models import Email

    if not sent_id:
        logger.debug("[send_email] no Message-ID returned by SMTP — skipping mirror")
        return

    thread_id = sent_id
    if in_reply_to:
        try:
            with get_session() as session:
                parent = (
                    session.query(Email)
                    .filter(
                        Email.owner_id == owner_id,
                        Email.message_id_header == in_reply_to,
                    )
                    .first()
                )
                if parent and parent.thread_id:
                    thread_id = parent.thread_id
        except Exception as e:
            logger.debug(f"[send_email] parent lookup failed: {e}")

    now = datetime.now(timezone.utc)
    # SQLite stores DateTime as naive UTC; mirror what
    # `parse_email_date_to_utc_naive` produces for inbound rows.
    naive_now = now.replace(tzinfo=None)
    record = {
        "id": sent_id,
        "thread_id": thread_id,
        "from_email": from_email,
        "from_name": "",
        "to_email": to,
        "cc_email": "",
        "subject": subject,
        "date": naive_now,
        "date_timestamp": int(now.timestamp()),
        "snippet": (body or "")[:200],
        "body_plain": body,
        "body_html": "",
        "labels": "",
        "message_id_header": sent_id,
        "in_reply_to": in_reply_to or "",
        "references": in_reply_to or "",
        "has_attachments": False,
        "attachment_filenames": [],
        "is_auto_reply": False,
    }
    store.store_email(owner_id, record)
    logger.info(
        f"[send_email] local mirror upserted: thread_id={thread_id} "
        f"message_id={sent_id}"
    )


def _send_whatsapp(args: Dict, store, owner_id: str) -> str:
    """Send a WhatsApp message and mirror the outbound row locally.

    Two reasons the previous shape was wrong:

    1. **Sound-of-conflict**: it instantiated a brand-new
       ``WhatsAppClient`` and connected, on top of the persistent one
       kept by ``whatsapp_actions._active_client``. WhatsApp enforces
       one session per device, so the existing socket got
       ``<stream:error><conflict type="replaced"/></stream:error>`` and
       died with an EOF on every solve send.
    2. **No local persistence**: nothing called ``store_outgoing``, so
       the sent message vanished from the renderer's thread list until
       the next live-socket echo (``deviceSentMessage``) hit the new
       throwaway client — which by then was already dead.

    Fix: reuse the persistent client when alive (no second socket, so
    no conflict), and call ``WhatsAppSyncService.store_outgoing`` after
    a successful send so the row lives in ``whatsapp_messages``
    immediately.
    """
    phone = args.get("phone_number", "")
    message = args.get("message", "")
    if not phone or not message:
        return "Missing phone_number or message"

    try:
        from neonize.utils import build_jid

        from zylch.whatsapp.client import WhatsAppClient
        from zylch.whatsapp.sync import WhatsAppSyncService
    except ImportError:
        return "neonize not installed"

    # Resolve the canonical chat_jid: prefer the persisted contact row
    # (covers @lid pseudonyms — sending to <phone>@s.whatsapp.net would
    # split the local thread). Falls back to the raw phone JID when no
    # contact match.
    digits = "".join(ch for ch in phone if ch.isdigit())
    if not digits:
        return f"Invalid phone number: {phone}"
    chat_jid = f"{digits}@s.whatsapp.net"
    try:
        from zylch.storage.database import get_session
        from zylch.storage.models import WhatsAppContact

        with get_session() as session:
            row = (
                session.query(WhatsAppContact.jid)
                .filter(
                    WhatsAppContact.owner_id == owner_id,
                    WhatsAppContact.phone_number == f"+{digits}",
                )
                .first()
            )
            if row and row[0]:
                chat_jid = row[0]
    except Exception as e:
        logger.debug(f"[send_whatsapp] chat_jid resolve failed: {e}")

    # Prefer the persistent client to avoid the "session replaced" kick.
    live_client = None
    live_sync = None
    try:
        from zylch.rpc import whatsapp_actions as _wa_actions

        with _wa_actions._state_lock:
            candidate = _wa_actions._active_client
            candidate_sync = _wa_actions._active_sync
        if candidate is not None:
            try:
                socket_up = bool(candidate.is_connected())
                logged_in = bool(candidate.is_logged_in()) if socket_up else False
            except Exception:
                socket_up = False
                logged_in = False
            if socket_up and logged_in:
                live_client = candidate
                live_sync = candidate_sync
    except Exception as e:
        logger.debug(f"[send_whatsapp] live-client check skipped: {e}")

    use_persistent = live_client is not None
    wa = live_client if use_persistent else WhatsAppClient()
    sync_svc = live_sync if live_sync is not None else WhatsAppSyncService(store, owner_id)

    try:
        if not use_persistent:
            if not wa.has_session():
                return "WhatsApp not connected. Run zylch init."
            import time as _time

            wa.connect(blocking=False)
            for _ in range(20):
                if wa.is_connected() and wa.is_logged_in():
                    break
                _time.sleep(0.5)
            else:
                return "WhatsApp connection timeout"

        # Address the JID. For real-phone chats build_jid is correct; for
        # @lid the resolved chat_jid above already carries the right
        # server, so we send via the chat_jid directly.
        if chat_jid.endswith("@s.whatsapp.net"):
            to_jid = build_jid(digits)
        else:
            user, _sep, server = chat_jid.partition("@")
            to_jid = build_jid(user, server)

        result = wa.send_message(to_jid, message)
        if not result:
            return "Send failed"

        # Mirror outgoing into whatsapp_messages so the renderer + the
        # next reanalyze see the user's reply without a full sync.
        msg_id = str(getattr(result, "ID", "") or "")
        if msg_id:
            try:
                from datetime import datetime, timezone

                sync_svc.store_outgoing(
                    chat_jid=chat_jid,
                    text=message,
                    msg_id=msg_id,
                    timestamp=datetime.now(timezone.utc),
                )
            except Exception as e:
                logger.warning(f"[send_whatsapp] store_outgoing failed: {e}")
        return f"WhatsApp sent to {phone}"
    except ImportError:
        return "neonize not installed"
    except Exception as e:
        return f"WhatsApp failed: {e}"


def _send_sms(
    args: Dict,
    store,
    owner_id: str,
) -> str:
    """Send SMS via MrCall/StarChat."""
    phone = args.get("phone_number", "")
    message = args.get("message", "")
    if not phone or not message:
        return "Missing phone_number or message"

    try:
        creds = store.get_provider_credentials(
            owner_id,
            "mrcall",
        )
        if not creds or not creds.get("access_token"):
            return "MrCall not connected. Run zylch init."

        import httpx

        from zylch.config import settings

        url = f"{settings.mrcall_base_url.rstrip('/')}" f"/mrcall/v1/sms/send"
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

    home = os.path.expanduser("~")
    profile_dir = os.environ.get("ZYLCH_PROFILE_DIR", "")
    defaults = [
        os.path.join(home, "gdrive-shared"),
        os.path.join(home, "Documents"),
        os.path.join(home, "Downloads"),
    ]
    if profile_dir:
        defaults.append(profile_dir)
    doc_paths = os.environ.get("DOCUMENT_PATHS", "")
    if doc_paths:
        configured = [os.path.expanduser(p.strip()) for p in doc_paths.split(",") if p.strip()]
        paths = [p for p in configured if os.path.isdir(p)]
        if not paths:
            paths = [p for p in defaults if os.path.isdir(p)]
    else:
        paths = [p for p in defaults if os.path.isdir(p)]
    if not paths:
        return "No document folders found." " Add DOCUMENT_PATHS to your profile .env"

    found = []
    for base in paths:
        pattern = os.path.join(base, "**", f"*{filename}*")
        found.extend(glob.glob(pattern, recursive=True))

    if not found:
        return f"No file matching '{filename}' in:" f" {', '.join(paths)}"

    path = found[0]
    ext = os.path.splitext(path)[1].lower()

    if ext == ".pdf":
        return f"Found PDF: {path}\n" f"Use run_python to read it with pypdf."
    elif ext in (".txt", ".md", ".csv", ".json", ".xml"):
        try:
            with open(path, "r", errors="replace") as f:
                content = f.read(10000)
            return f"File: {path}\n\n{content}"
        except Exception as e:
            return f"Could not read {path}: {e}"
    else:
        return f"Found: {path} ({ext})\n" f"Use run_python to process this file."


# ─── Web search ──────────────────────────────────────


def _web_search(args: Dict) -> str:
    """Search the web."""
    query = args.get("query", "")
    if not query:
        return "No query provided"

    try:
        from zylch.llm import try_make_llm_client

        # Use Sonnet for web search (cheaper, fast enough). Both
        # transports forward the prompt to Anthropic.
        client = try_make_llm_client(model="claude-sonnet-4-20250514")
        if client is None:
            return (
                "No LLM configured for web search. Set ANTHROPIC_API_KEY "
                "in the profile .env, or sign in with Firebase to use "
                "MrCall credits."
            )
        response = client.create_message_sync(
            messages=[
                {
                    "role": "user",
                    "content": (f"Search the web and answer: {query}"),
                },
            ],
            max_tokens=1000,
        )
        return response.content[0].text.strip()
    except Exception as e:
        return f"Web search failed: {e}"
