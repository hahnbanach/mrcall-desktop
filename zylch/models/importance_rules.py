"""
Importance Rules Model

Configurable rules for determining contact importance based on metadata.
Rules are evaluated in priority order and influence AI triage decisions.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
import re
import logging

logger = logging.getLogger(__name__)


@dataclass
class ImportanceRule:
    """
    Represents a single importance rule for contact classification.

    Attributes:
        name: Unique identifier for the rule (e.g., "professional_customers")
        condition: Safe expression to evaluate (e.g., "contact.template == 'professional'")
        importance: Priority level - "high", "normal", or "low"
        reason: Human-readable explanation for the rule
        priority: Evaluation order (higher = evaluated first)
        enabled: Whether the rule is active
    """
    name: str
    condition: str
    importance: str  # "high", "normal", "low"
    reason: str
    priority: int = 0
    enabled: bool = True
    id: Optional[str] = None
    owner_id: Optional[str] = None
    account_id: Optional[str] = None
    created_at: Optional[str] = None

    def evaluate(self, contact: dict) -> Optional[str]:
        """
        Evaluate this rule against a contact dict.

        Args:
            contact: Dictionary containing contact metadata

        Returns:
            The importance level if condition matches, None otherwise
        """
        if not self.enabled:
            return None

        try:
            if safe_eval_condition(self.condition, contact):
                return self.importance
        except Exception as e:
            logger.warning(f"Rule '{self.name}' evaluation failed: {e}")
            return None

        return None

    def to_dict(self) -> Dict[str, Any]:
        """Convert rule to dictionary for storage."""
        return {
            'id': self.id,
            'owner_id': self.owner_id,
            'account_id': self.account_id,
            'name': self.name,
            'condition': self.condition,
            'importance': self.importance,
            'reason': self.reason,
            'priority': self.priority,
            'enabled': self.enabled,
            'created_at': self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'ImportanceRule':
        """Create ImportanceRule from dictionary."""
        return cls(
            id=data.get('id'),
            owner_id=data.get('owner_id'),
            account_id=data.get('account_id'),
            name=data.get('name', ''),
            condition=data.get('condition', ''),
            importance=data.get('importance', 'normal'),
            reason=data.get('reason', ''),
            priority=data.get('priority', 0),
            enabled=data.get('enabled', True),
            created_at=data.get('created_at'),
        )


def evaluate_rules(rules: List[ImportanceRule], contact: dict) -> Dict[str, Any]:
    """
    Evaluate all rules in priority order and return first match.

    Args:
        rules: List of ImportanceRule objects, will be sorted by priority
        contact: Dictionary containing contact metadata

    Returns:
        Dict with keys:
            - importance: "high", "normal", or "low"
            - reason: Explanation string
            - rule: Name of matched rule or None
    """
    # Sort by priority (descending) so higher priority rules are evaluated first
    sorted_rules = sorted(rules, key=lambda r: r.priority, reverse=True)

    for rule in sorted_rules:
        result = rule.evaluate(contact)
        if result:
            return {
                "importance": result,
                "reason": rule.reason,
                "rule": rule.name,
            }

    # No rules matched - return default
    return {
        "importance": "normal",
        "reason": "No importance rules matched",
        "rule": None,
    }


def safe_eval_condition(condition: str, contact: dict) -> bool:
    """
    Safely evaluate a condition string against a contact dict.

    This uses pattern matching instead of Python's eval() for security.

    Supported expressions:
        - contact.field == 'value'
        - contact.field != 'value'
        - contact.field in ['a', 'b', 'c']
        - 'value' in contact.field
        - contact.field is None
        - contact.field is not None
        - contact.field >= number
        - contact.field <= number
        - contact.field > number
        - contact.field < number

    Args:
        condition: The condition string to evaluate
        contact: Dictionary containing contact metadata

    Returns:
        Boolean result of the condition evaluation

    Raises:
        ValueError: If the condition format is not supported
    """
    condition = condition.strip()

    # Pattern: contact.field == 'value'
    match = re.match(r"contact\.(\w+)\s*==\s*['\"](.+?)['\"]", condition)
    if match:
        field_name = match.group(1)
        expected_value = match.group(2)
        actual_value = contact.get(field_name)
        return actual_value == expected_value

    # Pattern: contact.field != 'value'
    match = re.match(r"contact\.(\w+)\s*!=\s*['\"](.+?)['\"]", condition)
    if match:
        field_name = match.group(1)
        expected_value = match.group(2)
        actual_value = contact.get(field_name)
        return actual_value != expected_value

    # Pattern: contact.field in ['a', 'b', 'c']
    match = re.match(r"contact\.(\w+)\s+in\s+\[(.+?)\]", condition)
    if match:
        field_name = match.group(1)
        values_str = match.group(2)
        # Parse the list values
        values = [v.strip().strip("'\"") for v in values_str.split(',')]
        actual_value = contact.get(field_name)
        return actual_value in values

    # Pattern: contact.field not in ['a', 'b', 'c']
    match = re.match(r"contact\.(\w+)\s+not\s+in\s+\[(.+?)\]", condition)
    if match:
        field_name = match.group(1)
        values_str = match.group(2)
        # Parse the list values
        values = [v.strip().strip("'\"") for v in values_str.split(',')]
        actual_value = contact.get(field_name)
        return actual_value not in values

    # Pattern: 'value' in contact.field
    match = re.match(r"['\"](.+?)['\"]\s+in\s+contact\.(\w+)", condition)
    if match:
        search_value = match.group(1)
        field_name = match.group(2)
        actual_value = contact.get(field_name)
        if actual_value is None:
            return False
        if isinstance(actual_value, str):
            return search_value in actual_value
        if isinstance(actual_value, (list, tuple)):
            return search_value in actual_value
        return False

    # Pattern: contact.field is None
    match = re.match(r"contact\.(\w+)\s+is\s+None", condition)
    if match:
        field_name = match.group(1)
        return contact.get(field_name) is None

    # Pattern: contact.field is not None
    match = re.match(r"contact\.(\w+)\s+is\s+not\s+None", condition)
    if match:
        field_name = match.group(1)
        return contact.get(field_name) is not None

    # Pattern: contact.field >= number
    match = re.match(r"contact\.(\w+)\s*>=\s*(\d+(?:\.\d+)?)", condition)
    if match:
        field_name = match.group(1)
        threshold = float(match.group(2))
        actual_value = contact.get(field_name)
        if actual_value is None:
            return False
        try:
            return float(actual_value) >= threshold
        except (ValueError, TypeError):
            return False

    # Pattern: contact.field <= number
    match = re.match(r"contact\.(\w+)\s*<=\s*(\d+(?:\.\d+)?)", condition)
    if match:
        field_name = match.group(1)
        threshold = float(match.group(2))
        actual_value = contact.get(field_name)
        if actual_value is None:
            return False
        try:
            return float(actual_value) <= threshold
        except (ValueError, TypeError):
            return False

    # Pattern: contact.field > number
    match = re.match(r"contact\.(\w+)\s*>\s*(\d+(?:\.\d+)?)", condition)
    if match:
        field_name = match.group(1)
        threshold = float(match.group(2))
        actual_value = contact.get(field_name)
        if actual_value is None:
            return False
        try:
            return float(actual_value) > threshold
        except (ValueError, TypeError):
            return False

    # Pattern: contact.field < number
    match = re.match(r"contact\.(\w+)\s*<\s*(\d+(?:\.\d+)?)", condition)
    if match:
        field_name = match.group(1)
        threshold = float(match.group(2))
        actual_value = contact.get(field_name)
        if actual_value is None:
            return False
        try:
            return float(actual_value) < threshold
        except (ValueError, TypeError):
            return False

    # Pattern: contact.field == True / == False (boolean)
    match = re.match(r"contact\.(\w+)\s*==\s*(True|False)", condition)
    if match:
        field_name = match.group(1)
        expected_bool = match.group(2) == 'True'
        actual_value = contact.get(field_name)
        return actual_value == expected_bool

    # Pattern: contact.field == number (numeric equality)
    match = re.match(r"contact\.(\w+)\s*==\s*(\d+(?:\.\d+)?)", condition)
    if match:
        field_name = match.group(1)
        expected_value = float(match.group(2))
        actual_value = contact.get(field_name)
        if actual_value is None:
            return False
        try:
            return float(actual_value) == expected_value
        except (ValueError, TypeError):
            return False

    # Pattern: contact.field (truthy check)
    match = re.match(r"^contact\.(\w+)$", condition)
    if match:
        field_name = match.group(1)
        return bool(contact.get(field_name))

    # Pattern: not contact.field (falsy check)
    match = re.match(r"^not\s+contact\.(\w+)$", condition)
    if match:
        field_name = match.group(1)
        return not bool(contact.get(field_name))

    raise ValueError(f"Unsupported condition format: {condition}")
