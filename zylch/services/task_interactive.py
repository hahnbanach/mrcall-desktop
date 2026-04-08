"""Interactive task review — walk through tasks one by one.

/tasks interactive → shows each task, user picks:
  1. skip    — next task
  2. done    — mark completed
  3. solve   — LLM proposes solution with tool access
  4. instruct — user gives instructions, LLM executes with tools
"""

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional

import click
from rich.console import Console
from rich.markdown import Markdown

logger = logging.getLogger(__name__)
console = Console()

SOLVE_SYSTEM_PROMPT = """You are a sales assistant helping {user_name} handle tasks.
{personal_data_section}
AVAILABLE TOOLS:
- search_memory: Search contact knowledge from ALL channels (email, WhatsApp, phone). ALWAYS start here.
- search_emails: Find specific emails by keyword.
- download_attachment: Save email attachments to /tmp/zylch/attachments/.
- read_document: Read files from user's document folders.
- web_search: Search the web for info (PEC, company data, regulations).
- draft_email: Compose an email draft (user reviews before sending).
- send_email: Send email via SMTP (user approves first).
- send_whatsapp: Send WhatsApp message (user approves first).
- send_sms: Send SMS via MrCall (user approves first).
- run_python: Execute Python code for file processing (PDF, Excel, etc.). Output to /tmp/zylch/. User approves first.

RULES:
- ALWAYS start with search_memory — it has cross-channel knowledge.
- Use the user's personal data above when filling forms or drafting documents.
- For actions (send, run_python): the user will review and approve.
- Be specific and concrete. Use names, reference content, draft actual messages.
- For PDFs: download_attachment → run_python to read/fill."""

# Tools available during solve — read-only execute automatically,
# write tools (draft, send) shown to user for approval.
SOLVE_TOOLS = [
    {
        "name": "search_emails",
        "description": (
            "Search the user's email archive."
            " Returns matching emails."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results (default 5)",
                    "default": 5,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "search_memory",
        "description": (
            "Search contact memory for info about a person"
            " or company."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "Name, email, or topic to search"
                    ),
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "draft_email",
        "description": (
            "Draft an email reply. The user will review"
            " before sending."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "to": {
                    "type": "string",
                    "description": "Recipient email",
                },
                "subject": {
                    "type": "string",
                    "description": "Email subject",
                },
                "body": {
                    "type": "string",
                    "description": "Email body text",
                },
            },
            "required": ["to", "subject", "body"],
        },
    },
    {
        "name": "run_python",
        "description": (
            "Execute Python code in a subprocess."
            " Use for: PDF processing, file manipulation,"
            " data transformation, calculations."
            " The user will review the code before execution."
            " Output files go to /tmp/zylch/."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "Python code to execute",
                },
                "description": {
                    "type": "string",
                    "description": (
                        "Brief description of what the"
                        " code does"
                    ),
                },
            },
            "required": ["code", "description"],
        },
    },
    {
        "name": "send_email",
        "description": (
            "Send an email via SMTP. User approves before sending."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "to": {
                    "type": "string",
                    "description": "Recipient email",
                },
                "subject": {
                    "type": "string",
                    "description": "Email subject",
                },
                "body": {
                    "type": "string",
                    "description": "Email body text",
                },
                "in_reply_to": {
                    "type": "string",
                    "description": "Message-ID to reply to (for threading)",
                },
            },
            "required": ["to", "subject", "body"],
        },
    },
    {
        "name": "download_attachment",
        "description": (
            "Download attachments from an email."
            " Saves to /tmp/zylch/attachments/."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "email_id": {
                    "type": "string",
                    "description": "Email Message-ID",
                },
            },
            "required": ["email_id"],
        },
    },
    {
        "name": "read_document",
        "description": (
            "Read a file from the user's document folders."
            " Searches by filename across all registered paths."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": (
                        "Filename or partial name to search"
                    ),
                },
            },
            "required": ["filename"],
        },
    },
    {
        "name": "web_search",
        "description": (
            "Search the web for information."
            " Use for: PEC addresses, company info,"
            " regulations, contact details."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "send_whatsapp",
        "description": (
            "Send a WhatsApp message."
            " User approves before sending."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "phone_number": {
                    "type": "string",
                    "description": (
                        "Phone with country code: +393281234567"
                    ),
                },
                "message": {
                    "type": "string",
                    "description": "Message text",
                },
            },
            "required": ["phone_number", "message"],
        },
    },
    {
        "name": "send_sms",
        "description": (
            "Send an SMS via MrCall/StarChat."
            " User approves before sending."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "phone_number": {
                    "type": "string",
                    "description": (
                        "Phone with country code: +393281234567"
                    ),
                },
                "message": {
                    "type": "string",
                    "description": "SMS text",
                },
            },
            "required": ["phone_number", "message"],
        },
    },
]

# Tools that need user approval before executing
APPROVAL_TOOLS = {
    "draft_email", "run_python",
    "send_email", "send_whatsapp", "send_sms",
}


def run_interactive_tasks(
    owner_id: str, store, api_key: str,
    provider: str, user_email: str,
):
    """Walk through active tasks interactively."""
    tasks = store.get_task_items(
        owner_id, action_required=True,
    )
    if not tasks:
        console.print("No tasks needing action.")
        return

    console.print(
        f"\n[bold cyan]Interactive Task Review"
        f" ({len(tasks)} tasks)[/bold cyan]\n",
    )

    for i, task in enumerate(tasks, 1):
        _show_task(i, len(tasks), task)
        choice = _prompt_choice()

        if choice == "1":  # skip
            continue
        elif choice == "2":  # done
            store.complete_task_item(owner_id, task["id"])
            console.print("  [green]Marked as done.[/green]")
        elif choice == "3":  # solve
            _solve_task(
                task, store, owner_id,
                api_key, provider, user_email,
            )
        elif choice == "4":  # instruct
            _instruct_task(
                task, store, owner_id,
                api_key, provider, user_email,
            )
        elif choice == "q":
            break

        console.print()

    console.print("[bold]Review complete.[/bold]")


def _show_task(idx: int, total: int, task: Dict):
    """Display a single task."""
    urgency = task.get("urgency", "MEDIUM").upper()
    icon = {
        "CRITICAL": "[red]CRITICAL[/red]",
        "HIGH": "[yellow]HIGH[/yellow]",
        "MEDIUM": "MEDIUM",
        "LOW": "[dim]LOW[/dim]",
    }.get(urgency, urgency)

    contact = (
        task.get("contact_name")
        or task.get("contact_email", "Unknown")
    )
    action = task.get("suggested_action", "")
    reason = task.get("reason", "")

    console.print(f"[bold]Task {idx}/{total}[/bold] ({icon})")
    console.print(f"  [bold]{contact}[/bold]")
    console.print(f"  {action}")
    if reason:
        console.print(f"  [dim]{reason}[/dim]")


def _prompt_choice() -> str:
    """Prompt user for action on current task."""
    console.print()
    console.print(
        "  1) skip   2) done   3) solve"
        "   4) instruct   q) quit",
    )
    while True:
        choice = click.prompt(
            "  Choice", type=str, default="1",
        ).strip().lower()
        if choice in ("1", "2", "3", "4", "q"):
            return choice
        console.print("  [red]Invalid choice[/red]")


def _build_task_context(
    task: Dict, store, owner_id: str,
) -> str:
    """Build full context for LLM from task data."""
    parts = []

    parts.append(
        f"TASK: {task.get('suggested_action', '')}",
    )
    parts.append(f"URGENCY: {task.get('urgency', '')}")
    parts.append(f"REASON: {task.get('reason', '')}")
    parts.append(
        f"CONTACT: {task.get('contact_name', '')}"
        f" ({task.get('contact_email', '')})",
    )

    # Original email
    event_id = task.get("event_id")
    if event_id:
        email = store.get_email_by_id(owner_id, event_id)
        if email:
            parts.append("\n--- ORIGINAL EMAIL ---")
            parts.append(
                f"From: {email.get('from_email', '')}",
            )
            parts.append(
                f"Subject: {email.get('subject', '')}",
            )
            parts.append(f"Date: {email.get('date', '')}")
            body = (
                email.get("body_plain", "")
                or email.get("snippet", "")
            )
            if body:
                parts.append(f"\n{body[:3000]}")

    # Contact memory blob
    sources = task.get("sources", {})
    blob_ids = sources.get("blobs", [])
    if blob_ids:
        try:
            from zylch.storage.database import get_session
            from zylch.storage.models import Blob

            with get_session() as session:
                for bid in blob_ids[:2]:
                    blob = (
                        session.query(Blob)
                        .filter_by(
                            id=str(bid), owner_id=owner_id,
                        )
                        .first()
                    )
                    if blob and blob.content:
                        parts.append(
                            "\n--- CONTACT MEMORY ---",
                        )
                        parts.append(blob.content)
        except Exception as e:
            logger.warning(f"Could not load blob: {e}")

    return "\n".join(parts)


# ─── Helpers ─────────────────────────────────────────


def _get_personal_data_section() -> str:
    """Build personal data section for system prompt."""
    import os

    fields = {
        "USER_FULL_NAME": "Name",
        "USER_PHONE": "Phone",
        "USER_CODICE_FISCALE": "Codice Fiscale",
        "USER_DATE_OF_BIRTH": "Date of Birth",
        "USER_ADDRESS": "Address",
        "USER_IBAN": "IBAN",
        "USER_COMPANY": "Company",
        "USER_VAT_NUMBER": "VAT/P.IVA",
    }
    data = []
    for key, label in fields.items():
        val = os.environ.get(key, "")
        if val:
            data.append(f"- {label}: {val}")

    if not data:
        return ""
    return (
        "\nUSER PERSONAL DATA:\n"
        + "\n".join(data)
        + "\n"
    )


# ─── Tool execution ──────────────────────────────────

# Tool executors live in solve_tools.py
from zylch.services.solve_tools import (
    execute_tool as _execute_tool,
)


def _format_approval_preview(
    tool_name: str, args: Dict,
) -> str:
    """Format a preview for approval before execution."""
    if tool_name == "send_email":
        return (
            f"**Send Email**\n"
            f"To: {args.get('to', '')}\n"
            f"Subject: {args.get('subject', '')}\n\n"
            f"{args.get('body', '')}"
        )
    elif tool_name == "draft_email":
        return (
            f"**Draft Email**\n"
            f"To: {args.get('to', '')}\n"
            f"Subject: {args.get('subject', '')}\n\n"
            f"{args.get('body', '')}"
        )
    elif tool_name == "send_whatsapp":
        return (
            f"**Send WhatsApp**\n"
            f"To: {args.get('phone_number', '')}\n\n"
            f"{args.get('message', '')}"
        )
    elif tool_name == "send_sms":
        return (
            f"**Send SMS**\n"
            f"To: {args.get('phone_number', '')}\n\n"
            f"{args.get('message', '')}"
        )
    elif tool_name == "run_python":
        return (
            f"**Run Python**\n"
            f"_{args.get('description', '')}_\n\n"
            f"```python\n{args.get('code', '')}\n```"
        )
    return json.dumps(args, indent=2, default=str)


# ─── Agentic solve loop ──────────────────────────────


def _run_agent_loop(
    client, system: str, messages: List[Dict],
    store, owner_id: str,
    max_turns: int = 10,
) -> List[Dict]:
    """Run tool_use loop until LLM stops calling tools.

    Read-only tools execute automatically.
    Write tools show output and ask for approval.

    Returns updated messages list.
    """
    for turn in range(max_turns):
        response = client.create_message_sync(
            system=system,
            messages=messages,
            tools=SOLVE_TOOLS,
            max_tokens=2000,
        )

        # Check if LLM wants to use tools
        if response.stop_reason != "tool_use":
            # Final text response
            text = ""
            for block in response.content:
                if hasattr(block, "text"):
                    text += block.text
            if text:
                messages.append(
                    {"role": "assistant", "content": text},
                )
                console.print()
                console.print(Markdown(text))
            break

        # Process tool calls
        tool_results = []
        assistant_content = []

        for block in response.content:
            if hasattr(block, "type"):
                if block.type == "text" and block.text:
                    console.print(
                        f"\n  [dim]{block.text}[/dim]",
                    )
                    assistant_content.append(
                        {
                            "type": "text",
                            "text": block.text,
                        },
                    )
                elif block.type == "tool_use":
                    tool_name = block.name
                    tool_input = block.input
                    tool_id = block.id

                    assistant_content.append(
                        {
                            "type": "tool_use",
                            "id": tool_id,
                            "name": tool_name,
                            "input": tool_input,
                        },
                    )

                    console.print(
                        f"  [cyan]> {tool_name}"
                        f"({json.dumps(tool_input, default=str)[:80]})"
                        f"[/cyan]",
                    )

                    # Approval gate BEFORE execution
                    if tool_name in APPROVAL_TOOLS:
                        # Show preview of what will happen
                        preview = _format_approval_preview(
                            tool_name, tool_input,
                        )
                        console.print()
                        console.print(Markdown(preview))
                        if not click.confirm(
                            "\n  Execute?",
                            default=True,
                        ):
                            result = (
                                "User declined this action."
                            )
                            tool_results.append(
                                {
                                    "type": "tool_result",
                                    "tool_use_id": tool_id,
                                    "content": result,
                                },
                            )
                            continue

                    # Execute tool
                    result = _execute_tool(
                        tool_name, tool_input,
                        store, owner_id,
                    )

                    if tool_name in APPROVAL_TOOLS:
                        console.print(
                            f"  [green]{result}[/green]",
                        )
                    else:
                        preview = result[:200]
                        if len(result) > 200:
                            preview += "..."
                        console.print(
                            f"  [dim]{preview}[/dim]",
                        )

                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": tool_id,
                            "content": result,
                        },
                    )

        # Add to message history
        messages.append(
            {"role": "assistant", "content": assistant_content},
        )
        messages.append(
            {"role": "user", "content": tool_results},
        )

    return messages


def _solve_task(
    task: Dict, store, owner_id: str,
    api_key: str, provider: str, user_email: str,
):
    """Agentic solve: LLM uses tools to research and propose."""
    from zylch.llm.client import LLMClient

    context = _build_task_context(task, store, owner_id)
    user_name = (
        user_email.split("@")[0] if user_email else "the user"
    )

    client = LLMClient(api_key=api_key, provider=provider)
    system = SOLVE_SYSTEM_PROMPT.format(
        user_name=user_name,
        personal_data_section=_get_personal_data_section(),
    )

    messages = [
        {
            "role": "user",
            "content": (
                f"Solve this task. Use tools to research"
                f" if needed, then propose a concrete"
                f" solution.\n\n{context}"
            ),
        },
    ]

    console.print("\n  [dim]Working...[/dim]")
    messages = _run_agent_loop(
        client, system, messages, store, owner_id,
    )

    console.print()
    _post_solve_menu(task, store, owner_id, client,
                     system, messages)


def _instruct_task(
    task: Dict, store, owner_id: str,
    api_key: str, provider: str, user_email: str,
):
    """User gives instructions, LLM executes with tools."""
    from zylch.llm.client import LLMClient

    context = _build_task_context(task, store, owner_id)
    user_name = (
        user_email.split("@")[0] if user_email else "the user"
    )

    instructions = click.prompt(
        "\n  Your instructions", type=str,
    )

    client = LLMClient(api_key=api_key, provider=provider)
    system = SOLVE_SYSTEM_PROMPT.format(
        user_name=user_name,
        personal_data_section=_get_personal_data_section(),
    )

    messages = [
        {
            "role": "user",
            "content": (
                f"Task context:\n\n{context}\n\n"
                f"User instructions: {instructions}\n\n"
                f"Use tools as needed to fulfill these"
                f" instructions."
            ),
        },
    ]

    console.print("\n  [dim]Working...[/dim]")
    messages = _run_agent_loop(
        client, system, messages, store, owner_id,
    )

    console.print()
    _post_solve_menu(task, store, owner_id, client,
                     system, messages)


def _post_solve_menu(
    task: Dict, store, owner_id: str,
    client, system: str, messages: List[Dict],
):
    """After solve: continue conversation, mark done, or go back."""
    while True:
        console.print(
            "\n  d) done   b) back to task   or type to continue conversation",
        )
        choice = click.prompt(
            "  >", type=str, default="d",
        ).strip()

        lower = choice.lower()
        if lower == "d":
            store.complete_task_item(owner_id, task["id"])
            console.print(
                "  [green]Task marked as done.[/green]",
            )
            break
        elif lower == "b":
            break
        else:
            # Anything else = continue the conversation
            messages.append(
                {"role": "user", "content": choice},
            )
            console.print("\n  [dim]Thinking...[/dim]")
            messages = _run_agent_loop(
                client, system, messages,
                store, owner_id,
            )
