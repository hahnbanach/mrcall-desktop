"""Tests for importance rules model and safe evaluation."""

import pytest
from zylch.models.importance_rules import (
    ImportanceRule,
    evaluate_rules,
    safe_eval_condition,
)


class TestImportanceRule:
    """Tests for ImportanceRule dataclass."""

    def test_basic_rule_creation(self):
        """Test creating a basic importance rule."""
        rule = ImportanceRule(
            name="professional_customers",
            condition="contact.template == 'professional'",
            importance="high",
            reason="Professional tier paying customer"
        )
        assert rule.name == "professional_customers"
        assert rule.importance == "high"
        assert rule.priority == 0  # default
        assert rule.enabled is True  # default

    def test_rule_with_priority(self):
        """Test rule with custom priority."""
        rule = ImportanceRule(
            name="vip",
            condition="contact.tier == 'enterprise'",
            importance="high",
            reason="Enterprise customer",
            priority=100
        )
        assert rule.priority == 100

    def test_rule_to_dict(self):
        """Test serialization to dict."""
        rule = ImportanceRule(
            name="test_rule",
            condition="contact.active == True",
            importance="normal",
            reason="Active user",
            priority=50,
            enabled=False
        )
        d = rule.to_dict()
        assert d["name"] == "test_rule"
        assert d["condition"] == "contact.active == True"
        assert d["importance"] == "normal"
        assert d["reason"] == "Active user"
        assert d["priority"] == 50
        assert d["enabled"] is False

    def test_rule_from_dict(self):
        """Test deserialization from dict."""
        data = {
            "name": "from_db",
            "condition": "contact.type == 'customer'",
            "importance": "high",
            "reason": "Customer contact",
            "priority": 25,
            "enabled": True
        }
        rule = ImportanceRule.from_dict(data)
        assert rule.name == "from_db"
        assert rule.importance == "high"
        assert rule.priority == 25

    def test_rule_from_dict_with_defaults(self):
        """Test deserialization with missing optional fields."""
        data = {
            "name": "minimal",
            "condition": "contact.email is not None",
            "importance": "low",
            "reason": "Has email"
        }
        rule = ImportanceRule.from_dict(data)
        assert rule.priority == 0  # default
        assert rule.enabled is True  # default


class TestSafeEvalCondition:
    """Tests for safe_eval_condition function."""

    def test_equality_string(self):
        """Test string equality comparison."""
        contact = {"template": "professional"}
        assert safe_eval_condition("contact.template == 'professional'", contact) is True
        assert safe_eval_condition("contact.template == 'free'", contact) is False

    def test_equality_number(self):
        """Test numeric equality comparison."""
        contact = {"plan_id": 42}
        assert safe_eval_condition("contact.plan_id == 42", contact) is True
        assert safe_eval_condition("contact.plan_id == 99", contact) is False

    def test_inequality(self):
        """Test inequality comparison."""
        contact = {"tier": "basic"}
        assert safe_eval_condition("contact.tier != 'enterprise'", contact) is True
        assert safe_eval_condition("contact.tier != 'basic'", contact) is False

    def test_in_list(self):
        """Test membership in list."""
        contact = {"status": "active"}
        assert safe_eval_condition("contact.status in ['active', 'trial']", contact) is True
        assert safe_eval_condition("contact.status in ['suspended', 'deleted']", contact) is False

    def test_not_in_list(self):
        """Test non-membership in list."""
        contact = {"role": "admin"}
        assert safe_eval_condition("contact.role not in ['guest', 'viewer']", contact) is True
        assert safe_eval_condition("contact.role not in ['admin', 'owner']", contact) is False

    def test_is_none(self):
        """Test None comparison."""
        contact = {"email": "test@example.com", "phone": None}
        assert safe_eval_condition("contact.phone is None", contact) is True
        assert safe_eval_condition("contact.email is None", contact) is False

    def test_is_not_none(self):
        """Test not None comparison."""
        contact = {"email": "test@example.com", "phone": None}
        assert safe_eval_condition("contact.email is not None", contact) is True
        assert safe_eval_condition("contact.phone is not None", contact) is False

    def test_greater_than(self):
        """Test greater than comparison."""
        contact = {"score": 85}
        assert safe_eval_condition("contact.score > 80", contact) is True
        assert safe_eval_condition("contact.score > 90", contact) is False

    def test_greater_equal(self):
        """Test greater than or equal comparison."""
        contact = {"score": 80}
        assert safe_eval_condition("contact.score >= 80", contact) is True
        assert safe_eval_condition("contact.score >= 81", contact) is False

    def test_less_than(self):
        """Test less than comparison."""
        contact = {"age": 25}
        assert safe_eval_condition("contact.age < 30", contact) is True
        assert safe_eval_condition("contact.age < 20", contact) is False

    def test_less_equal(self):
        """Test less than or equal comparison."""
        contact = {"age": 30}
        assert safe_eval_condition("contact.age <= 30", contact) is True
        assert safe_eval_condition("contact.age <= 29", contact) is False

    def test_boolean_true(self):
        """Test boolean True comparison."""
        contact = {"active": True}
        assert safe_eval_condition("contact.active == True", contact) is True
        assert safe_eval_condition("contact.active == False", contact) is False

    def test_boolean_false(self):
        """Test boolean False comparison."""
        contact = {"suspended": False}
        assert safe_eval_condition("contact.suspended == False", contact) is True
        assert safe_eval_condition("contact.suspended == True", contact) is False

    def test_missing_field(self):
        """Test condition with missing field returns False."""
        contact = {"name": "Test"}
        assert safe_eval_condition("contact.nonexistent == 'value'", contact) is False

    def test_empty_contact(self):
        """Test condition with empty contact returns False."""
        contact = {}
        assert safe_eval_condition("contact.template == 'pro'", contact) is False

    def test_invalid_condition_format(self):
        """Test that invalid condition format raises ValueError."""
        contact = {"name": "Test"}
        with pytest.raises(ValueError, match="Unsupported condition format"):
            safe_eval_condition("SELECT * FROM users", contact)

    def test_code_injection_attempt(self):
        """Test that code injection attempts are rejected."""
        contact = {"name": "Test"}
        # These should all raise ValueError due to invalid format
        with pytest.raises(ValueError):
            safe_eval_condition("__import__('os').system('ls')", contact)
        with pytest.raises(ValueError):
            safe_eval_condition("contact.name; os.system('ls')", contact)

    def test_nested_field_not_supported(self):
        """Test that deeply nested fields raise ValueError."""
        contact = {"metadata": {"type": "premium"}}
        # Nested access like contact.metadata.type is not supported
        # Should raise ValueError for unsupported format
        with pytest.raises(ValueError, match="Unsupported condition format"):
            safe_eval_condition("contact.metadata.type == 'premium'", contact)


class TestImportanceRuleEvaluate:
    """Tests for ImportanceRule.evaluate() method."""

    def test_evaluate_matching_rule(self):
        """Test rule evaluation when condition matches."""
        rule = ImportanceRule(
            name="pro_rule",
            condition="contact.template == 'professional'",
            importance="high",
            reason="Pro customer"
        )
        contact = {"template": "professional"}
        result = rule.evaluate(contact)
        assert result == "high"

    def test_evaluate_non_matching_rule(self):
        """Test rule evaluation when condition doesn't match."""
        rule = ImportanceRule(
            name="pro_rule",
            condition="contact.template == 'professional'",
            importance="high",
            reason="Pro customer"
        )
        contact = {"template": "free"}
        result = rule.evaluate(contact)
        assert result is None

    def test_evaluate_disabled_rule(self):
        """Test that disabled rules always return None."""
        rule = ImportanceRule(
            name="disabled_rule",
            condition="contact.template == 'professional'",
            importance="high",
            reason="Pro customer",
            enabled=False
        )
        contact = {"template": "professional"}
        result = rule.evaluate(contact)
        assert result is None


class TestEvaluateRules:
    """Tests for evaluate_rules function."""

    def test_first_matching_rule_wins(self):
        """Test that first matching rule (by priority) determines importance."""
        rules = [
            ImportanceRule(
                name="enterprise",
                condition="contact.tier == 'enterprise'",
                importance="high",
                reason="Enterprise",
                priority=100
            ),
            ImportanceRule(
                name="pro",
                condition="contact.tier == 'pro'",
                importance="normal",
                reason="Pro",
                priority=50
            ),
        ]
        contact = {"tier": "enterprise"}
        result = evaluate_rules(rules, contact)
        assert result["importance"] == "high"
        assert result["rule"] == "enterprise"

    def test_priority_ordering(self):
        """Test that higher priority rules are evaluated first."""
        rules = [
            ImportanceRule(
                name="low_priority",
                condition="contact.has_paid == True",
                importance="normal",
                reason="Paid user",
                priority=10
            ),
            ImportanceRule(
                name="high_priority",
                condition="contact.has_paid == True",
                importance="high",
                reason="VIP",
                priority=100
            ),
        ]
        contact = {"has_paid": True}
        result = evaluate_rules(rules, contact)
        # Higher priority rule should match first
        assert result["rule"] == "high_priority"
        assert result["importance"] == "high"

    def test_no_matching_rules(self):
        """Test default importance when no rules match."""
        rules = [
            ImportanceRule(
                name="enterprise",
                condition="contact.tier == 'enterprise'",
                importance="high",
                reason="Enterprise",
                priority=100
            ),
        ]
        contact = {"tier": "free"}
        result = evaluate_rules(rules, contact)
        assert result["importance"] == "normal"  # default
        assert result["rule"] is None
        assert "No importance rules matched" in result["reason"]

    def test_empty_rules_list(self):
        """Test default importance with empty rules list."""
        result = evaluate_rules([], {"tier": "any"})
        assert result["importance"] == "normal"
        assert result["rule"] is None

    def test_disabled_rules_skipped(self):
        """Test that disabled rules are skipped in evaluation."""
        rules = [
            ImportanceRule(
                name="disabled_high",
                condition="contact.tier == 'pro'",
                importance="high",
                reason="Pro",
                priority=100,
                enabled=False  # disabled
            ),
            ImportanceRule(
                name="enabled_low",
                condition="contact.tier == 'pro'",
                importance="low",
                reason="Low priority",
                priority=50,
                enabled=True
            ),
        ]
        contact = {"tier": "pro"}
        result = evaluate_rules(rules, contact)
        # Should skip disabled rule and match enabled one
        assert result["rule"] == "enabled_low"
        assert result["importance"] == "low"


class TestRealWorldScenarios:
    """Test real-world usage scenarios."""

    def test_mrcall_professional_customer(self):
        """Test MrCall professional tier customer detection."""
        rules = [
            ImportanceRule(
                name="professional_customers",
                condition="contact.template == 'professional'",
                importance="high",
                reason="Professional tier paying customer"
            ),
            ImportanceRule(
                name="enterprise_customers",
                condition="contact.template == 'enterprise'",
                importance="high",
                reason="Enterprise tier customer - top priority",
                priority=10
            ),
            ImportanceRule(
                name="free_tier",
                condition="contact.template == 'free'",
                importance="low",
                reason="Free tier user"
            ),
        ]

        # Test professional customer
        pro_contact = {"template": "professional", "email": "pro@company.com"}
        result = evaluate_rules(rules, pro_contact)
        assert result["importance"] == "high"
        assert "professional" in result["reason"].lower()

        # Test free user
        free_contact = {"template": "free", "email": "free@gmail.com"}
        result = evaluate_rules(rules, free_contact)
        assert result["importance"] == "low"

        # Test unknown tier (no match)
        unknown = {"template": "trial", "email": "trial@test.com"}
        result = evaluate_rules(rules, unknown)
        assert result["importance"] == "normal"  # default
