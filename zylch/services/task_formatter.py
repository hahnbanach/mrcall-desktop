"""Shared task formatting utilities for /tasks command.

Provides formatting for both:
- Legacy avatar-based tasks (format_task_list)
- New LLM-analyzed tasks (format_task_items)
"""

from typing import List, Dict, Any, Set
from ..config import settings


def get_my_emails() -> Set[str]:
    """Get set of user's own email addresses (lowercase)."""
    return set(e.strip().lower() for e in settings.my_emails.split(',') if e.strip())


def is_own_email(avatar: Dict[str, Any], my_emails: Set[str]) -> bool:
    """Check if avatar belongs to user's own email.

    Args:
        avatar: Avatar dict from Supabase
        my_emails: Set of user's email addresses (lowercase)

    Returns:
        True if avatar is for user's own email
    """
    # Check contact_email field
    if avatar.get('contact_email', '').lower() in my_emails:
        return True
    # Check identifiers.emails array
    identifiers = avatar.get('identifiers') or {}
    avatar_emails = identifiers.get('emails') or []
    for email in avatar_emails:
        if email.lower() in my_emails:
            return True
    return False


def filter_own_emails(avatars: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Filter out user's own emails from avatar list.

    Args:
        avatars: List of avatar dicts from Supabase

    Returns:
        Filtered list excluding user's own emails
    """
    my_emails = get_my_emails()
    return [a for a in avatars if not is_own_email(a, my_emails)]


def _get_read_indicator(avatar: Dict[str, Any]) -> str:
    """Generate read tracking indicator for an avatar.

    Args:
        avatar: Avatar dict with read_tracking field

    Returns:
        Formatted indicator string (e.g., " 📧❌ (unread 5d)") or empty string
    """
    from datetime import datetime, timezone

    read_tracking = avatar.get('read_tracking', {})
    if not read_tracking:
        return ""

    last_unread = read_tracking.get('last_unread_email')
    last_read = read_tracking.get('last_read_date')

    # Priority 1: Show unread indicator
    if last_unread:
        days_unread = int(last_unread.get('days_since_sent', 0))
        return f" 📧❌ (unread {days_unread}d)"

    # Priority 2: Show read but no response indicator (3+ days)
    if last_read:
        try:
            # Parse ISO timestamp
            if isinstance(last_read, str):
                last_read_dt = datetime.fromisoformat(last_read.replace('Z', '+00:00'))
            else:
                last_read_dt = last_read

            days_since_read = (datetime.now(timezone.utc) - last_read_dt).days
            if days_since_read >= 3:
                return f" 📧✓ (read {days_since_read}d ago)"
        except (ValueError, TypeError, AttributeError):
            # Silently ignore parsing errors
            pass

    return ""


def format_task_list(avatars: List[Dict[str, Any]], include_stale_warning: bool = False) -> str:
    """Format avatars as numbered task list.

    Args:
        avatars: List of avatar dicts (already filtered)
        include_stale_warning: Whether to check and warn about stale avatars

    Returns:
        Formatted markdown string
    """
    from datetime import datetime, timezone

    if not avatars:
        return "✨ **No open tasks!** All caught up.\n\nℹ️ Run `/sync` to fetch and analyze new emails."

    # Group by priority
    high = [a for a in avatars if a.get('relationship_score', 0) >= 7]
    medium = [a for a in avatars if 4 <= a.get('relationship_score', 0) < 7]
    low = [a for a in avatars if a.get('relationship_score', 0) < 4]

    # Check avatar freshness if requested
    stale_avatars = 0
    if include_stale_warning:
        for avatar in avatars:
            last_computed = avatar.get('last_computed')
            if last_computed:
                computed_dt = datetime.fromisoformat(last_computed.replace('Z', '+00:00'))
                age_days = (datetime.now(timezone.utc) - computed_dt).days
                if age_days > 7:
                    stale_avatars += 1

    lines = ["## 📋 Open Tasks\n"]
    task_num = 1  # Running counter for task numbers

    if high:
        lines.append("### 🔥 High Priority")
        for a in high:
            name = a.get('display_name') or a.get('contact_email', 'Unknown')
            action = a.get('suggested_action', 'Follow up')
            score = a.get('relationship_score', 0)

            # Get read tracking indicator
            read_indicator = _get_read_indicator(a)

            lines.append(f"{task_num}. **{name}** (score {score}): {action}{read_indicator}")
            task_num += 1
        lines.append("")

    if medium:
        lines.append("### 📌 Medium Priority")
        for a in medium:
            name = a.get('display_name') or a.get('contact_email', 'Unknown')
            action = a.get('suggested_action', 'Review')
            score = a.get('relationship_score', 0)

            # Get read tracking indicator
            read_indicator = _get_read_indicator(a)

            lines.append(f"{task_num}. **{name}** (score {score}): {action}{read_indicator}")
            task_num += 1
        lines.append("")

    if low:
        lines.append("### 📝 Low Priority")
        for a in low[:10]:  # Limit to 10
            name = a.get('display_name') or a.get('contact_email', 'Unknown')
            action = a.get('suggested_action', 'Review')

            # Get read tracking indicator
            read_indicator = _get_read_indicator(a)

            lines.append(f"{task_num}. {name}: {action}{read_indicator}")
            task_num += 1
        if len(low) > 10:
            lines.append(f"   ... and {len(low) - 10} more")

    lines.append(f"\n**Total: {len(avatars)} open tasks**")

    if stale_avatars > 0:
        lines.append(f"\n⚠️ {stale_avatars} avatars are >7 days old. Run `/sync` to refresh.")

    lines.append("\n💡 Say \"more on #3\" or \"draft reply for #5\" to act on a task")

    return "\n".join(lines)


def format_task_items(tasks: List[Dict[str, Any]]) -> str:
    """Format LLM-analyzed task items as numbered list.

    Args:
        tasks: List of task item dicts from task_items table

    Returns:
        Formatted markdown string
    """
    if not tasks:
        return "✨ **No action needed!** All caught up."

    # Group by urgency
    high = [t for t in tasks if t.get('urgency') == 'high']
    medium = [t for t in tasks if t.get('urgency') == 'medium']
    low = [t for t in tasks if t.get('urgency') == 'low']

    # Icon mapping for event types
    icon_map = {
        'email': '📧',
        'calendar': '📅',
        'mrcall': '📞'
    }

    lines = ["## 📋 Action Required\n"]
    task_num = 1

    if high:
        lines.append("### 🔥 Urgent")
        for t in high:
            icon = icon_map.get(t.get('event_type'), '📌')
            name = t.get('contact_name') or t.get('contact_email', 'Unknown')
            action = t.get('suggested_action', 'Review')
            reason = t.get('reason', '')

            line = f"{task_num}. {icon} **{name}**: {action}"
            if reason:
                line += f"\n   _({reason})_"
            lines.append(line)
            task_num += 1
        lines.append("")

    if medium:
        lines.append("### 📌 Should Do")
        for t in medium:
            icon = icon_map.get(t.get('event_type'), '📌')
            name = t.get('contact_name') or t.get('contact_email', 'Unknown')
            action = t.get('suggested_action', 'Review')

            lines.append(f"{task_num}. {icon} **{name}**: {action}")
            task_num += 1
        lines.append("")

    if low:
        lines.append("### 📝 Nice To Do")
        for t in low[:10]:  # Limit to 10
            icon = icon_map.get(t.get('event_type'), '📌')
            name = t.get('contact_name') or t.get('contact_email', 'Unknown')
            action = t.get('suggested_action', 'Review')

            lines.append(f"{task_num}. {icon} {name}: {action}")
            task_num += 1
        if len(low) > 10:
            lines.append(f"   ... and {len(low) - 10} more")

    lines.append(f"\n**Total: {len(tasks)} items need attention**")
    lines.append("\n💡 Say \"more on #3\" or \"draft reply for #5\" to act on a task")

    return "\n".join(lines)
