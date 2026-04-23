"""Digest builder for proactive notifications.

Generates summary messages for Telegram (or other push channels).
Returns None when there's nothing to report.
"""

import logging

logger = logging.getLogger(__name__)


def build_digest(owner_id: str, store) -> str | None:
    """Build a digest message with actionable insights.

    Args:
        owner_id: Profile owner ID
        store: Storage instance

    Returns:
        Markdown-formatted digest, or None if nothing to report.
    """
    tasks = store.get_task_items(
        owner_id,
        action_required=True,
    )
    unprocessed = len(
        store.get_unprocessed_emails(owner_id),
    )

    # Nothing to say
    if not tasks and not unprocessed:
        return None

    lines = []

    # Task summary by urgency
    if tasks:
        urgency_map = {}
        for t in tasks:
            u = t.get("urgency", "MEDIUM")
            urgency_map.setdefault(u, []).append(t)

        lines.append("*Action items:*")
        for urgency in ["CRITICAL", "HIGH", "MEDIUM", "LOW"]:
            items = urgency_map.get(urgency, [])
            if not items:
                continue
            icon = {
                "CRITICAL": "🔴",
                "HIGH": "🟠",
                "MEDIUM": "🟡",
                "LOW": "🟢",
            }.get(urgency, "⚪")
            for t in items[:3]:  # Max 3 per urgency
                action = t.get(
                    "suggested_action",
                    "Review",
                )
                contact = t.get("contact_name") or t.get(
                    "contact_email",
                    "",
                )
                lines.append(
                    f"{icon} {action}" + (f" ({contact})" if contact else ""),
                )
        if len(tasks) > 9:
            lines.append(
                f"  _...and {len(tasks) - 9} more_",
            )

    # Unprocessed items
    if unprocessed > 0:
        lines.append(
            f"\n_{unprocessed} emails pending analysis._" f" Run `/process` to update.",
        )

    if not lines:
        return None

    return "\n".join(lines)
