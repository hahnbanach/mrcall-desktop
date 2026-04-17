"""Interactive task review — CLI wrapper around TaskExecutor.

/tasks interactive → shows each task, user picks:
  1. skip    — next task
  2. done    — mark completed
  3. solve   — LLM proposes solution with tool access
  4. instruct — user gives instructions, LLM executes with tools

Tool configs, prompt, and task-context builder live in
`solve_constants.py`. The agent loop itself lives in
`task_executor.py`. This file contains only the Click-based
terminal UI that consumes executor events.
"""

import asyncio
import json
import logging
from typing import Dict, List

import click
from rich.console import Console
from rich.markdown import Markdown

from zylch.services.solve_constants import (
    SOLVE_SYSTEM_PROMPT,
    SOLVE_TOOLS,
    build_task_context,
    get_personal_data_section,
)
from zylch.services.task_executor import TaskExecutor

logger = logging.getLogger(__name__)
console = Console()


def run_interactive_tasks(
    owner_id: str,
    store,
    api_key: str,
    provider: str,
    user_email: str,
):
    """Walk through active tasks interactively."""
    tasks = store.get_task_items(owner_id, action_required=True)
    # Filter out skipped tasks (sources.skipped_at set).
    tasks = [t for t in tasks if not (t.get("sources") or {}).get("skipped_at")]
    if not tasks:
        console.print("No tasks needing action.")
        return

    console.print(
        f"\n[bold cyan]Interactive Task Review" f" ({len(tasks)} tasks)[/bold cyan]\n",
    )

    for i, task in enumerate(tasks, 1):
        _show_task(i, len(tasks), task)
        choice = _prompt_choice()

        if choice == "1":
            continue
        elif choice == "2":
            store.complete_task_item(owner_id, task["id"])
            console.print("  [green]Marked as done.[/green]")
        elif choice == "3":
            _solve_task(task, store, owner_id, api_key, provider, user_email)
        elif choice == "4":
            _instruct_task(
                task,
                store,
                owner_id,
                api_key,
                provider,
                user_email,
            )
        elif choice == "e":
            break

        console.print()

    console.print("[bold]Review complete.[/bold]")


def _show_task(idx: int, total: int, task: Dict):
    urgency = task.get("urgency", "MEDIUM").upper()
    icon = {
        "CRITICAL": "[red]CRITICAL[/red]",
        "HIGH": "[yellow]HIGH[/yellow]",
        "MEDIUM": "MEDIUM",
        "LOW": "[dim]LOW[/dim]",
    }.get(urgency, urgency)

    contact = task.get("contact_name") or task.get("contact_email", "Unknown")
    action = task.get("suggested_action", "")
    reason = task.get("reason", "")

    console.print(f"[bold]Task {idx}/{total}[/bold] ({icon})")
    console.print(f"  [bold]{contact}[/bold]")
    console.print(f"  {action}")
    if reason:
        console.print(f"  [dim]{reason}[/dim]")


def _prompt_choice() -> str:
    console.print()
    console.print("  [bold]1)[/bold] Skip — analyze later")
    console.print("  [bold]2)[/bold] Close it — already done")
    console.print("  [bold]3)[/bold] I trust you — solve it!")
    console.print("  [bold]4)[/bold] Let's discuss that")
    console.print("  [bold]e)[/bold] Exit and let's chat")
    console.print()
    while True:
        choice = (
            click.prompt(
                "  >",
                type=str,
                default="1",
            )
            .strip()
            .lower()
        )
        if choice in ("1", "2", "3", "4", "e"):
            return choice
        console.print("  [red]Invalid choice[/red]")


def _cli_run_executor(executor: TaskExecutor) -> List[Dict]:
    """Consume executor events synchronously with click.confirm approvals."""

    async def _drive() -> List[Dict]:
        agen = executor.run()
        async for event in agen:
            et = event["type"]
            if et == "thinking":
                text = event["text"]
                console.print()
                console.print(Markdown(text))
            elif et == "tool_call_pending":
                name = event["name"]
                console.print(
                    f"  [cyan]> {name}"
                    f"({json.dumps(event['input'], default=str)[:80]})"
                    f"[/cyan]",
                )
                console.print()
                console.print(Markdown(event["preview"]))
                ok = click.confirm("\n  Execute?", default=True)
                await executor.approve(event["tool_use_id"], ok)
            elif et == "tool_result":
                out = event["output"]
                name = event["name"]
                if event.get("approved"):
                    # Short for write-tools (already previewed)
                    if len(out) > 400:
                        console.print(
                            f"  [green]{out[:400]}...[/green]",
                        )
                    else:
                        console.print(f"  [green]{out}[/green]")
                else:
                    preview = out[:200] + ("..." if len(out) > 200 else "")
                    console.print(f"  [dim]{name}: {preview}[/dim]")
            elif et == "done":
                return event["result"]["messages"]
            elif et == "error":
                console.print(f"  [red]Error: {event['message']}[/red]")
                return executor.messages
        return executor.messages

    return asyncio.run(_drive())


def _solve_task(
    task: Dict,
    store,
    owner_id: str,
    api_key: str,
    provider: str,
    user_email: str,
):
    """Agentic solve: LLM uses tools to research and propose."""
    from zylch.llm.client import LLMClient

    context = build_task_context(task, store, owner_id)
    user_name = user_email.split("@")[0] if user_email else "the user"
    client = LLMClient(api_key=api_key, provider=provider)
    system = SOLVE_SYSTEM_PROMPT.format(
        user_name=user_name,
        personal_data_section=get_personal_data_section(),
    )

    messages = [
        {
            "role": "user",
            "content": (
                f"Solve this task. Use tools to research if needed, then"
                f" propose a concrete solution.\n\n{context}"
            ),
        }
    ]

    console.print("\n  [dim]Working...[/dim]")
    executor = TaskExecutor(
        client,
        system,
        messages,
        store,
        owner_id,
        SOLVE_TOOLS,
    )
    messages = _cli_run_executor(executor)

    console.print()
    _post_solve_menu(task, store, owner_id, client, system, messages)


def _instruct_task(
    task: Dict,
    store,
    owner_id: str,
    api_key: str,
    provider: str,
    user_email: str,
):
    from zylch.llm.client import LLMClient

    context = build_task_context(task, store, owner_id)
    user_name = user_email.split("@")[0] if user_email else "the user"

    console.print(
        "\n  What would you like to do? (type, empty line to send)",
    )
    lines = []
    while True:
        try:
            line = input("  > ")
        except (EOFError, KeyboardInterrupt):
            break
        if not line:
            break
        lines.append(line)
    instructions = "\n".join(lines)
    if not instructions.strip():
        return

    client = LLMClient(api_key=api_key, provider=provider)
    system = SOLVE_SYSTEM_PROMPT.format(
        user_name=user_name,
        personal_data_section=get_personal_data_section(),
    )

    messages = [
        {
            "role": "user",
            "content": (
                f"Task context:\n\n{context}\n\n"
                f"User instructions: {instructions}\n\n"
                f"Use tools as needed to fulfill these instructions."
            ),
        }
    ]

    console.print("\n  [dim]Working...[/dim]")
    executor = TaskExecutor(
        client,
        system,
        messages,
        store,
        owner_id,
        SOLVE_TOOLS,
    )
    messages = _cli_run_executor(executor)

    console.print()
    _post_solve_menu(task, store, owner_id, client, system, messages)


def _post_solve_menu(
    task: Dict,
    store,
    owner_id: str,
    client,
    system: str,
    messages: List[Dict],
):
    while True:
        console.print(
            "\n  [bold]d)[/bold] Done"
            "   [bold]b)[/bold] Back to task"
            "   or type to continue (empty line to send)",
        )
        lines = []
        while True:
            try:
                line = input("  > ")
            except (EOFError, KeyboardInterrupt):
                break
            if not line and lines:
                break
            if not line and not lines:
                break
            lines.append(line)

        choice = "\n".join(lines).strip()
        if not choice:
            choice = "b"

        lower = choice.lower()
        if lower == "d":
            store.complete_task_item(owner_id, task["id"])
            console.print("  [green]Task marked as done.[/green]")
            break
        elif lower == "b":
            break
        else:
            messages.append({"role": "user", "content": choice})
            console.print("\n  [dim]Thinking...[/dim]")
            executor = TaskExecutor(
                client,
                system,
                messages,
                store,
                owner_id,
                SOLVE_TOOLS,
            )
            messages = _cli_run_executor(executor)
