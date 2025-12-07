"""Test script for Zylch skill system - Phase A."""

import asyncio
import sys
from pathlib import Path

import pytest

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from zylch.skills.base import BaseSkill, SkillContext, SkillResult
from zylch.skills.registry import registry
from zylch.skills.email_triage import EmailTriageSkill
from zylch.skills.draft_composer import DraftComposerSkill
from zylch.skills.cross_channel import CrossChannelOrchestratorSkill
from zylch.router.intent_classifier import IntentRouter


class SkillSystemTestSkill(BaseSkill):
    """Simple test skill for validation."""

    def __init__(self):
        super().__init__(
            skill_name="test_skill",
            description="A simple test skill"
        )

    async def execute(self, context: SkillContext):
        """Simple execution that returns params."""
        return {
            "message": "Test skill executed successfully",
            "params": context.params
        }


@pytest.mark.asyncio
async def test_base_skill():
    """Test basic skill execution."""
    print("\n=== Test 1: Base Skill ===")

    skill = SkillSystemTestSkill()
    context = SkillContext(
        user_id="test_user",
        intent="test intent",
        params={"test_param": "test_value"}
    )

    result = await skill.activate(context)

    assert result.success, "Skill execution should succeed"
    assert result.skill_name == "test_skill", "Skill name should match"
    assert result.data["message"] == "Test skill executed successfully"

    print("✅ Base skill test passed")
    return True


@pytest.mark.asyncio
async def test_registry():
    """Test skill registry."""
    print("\n=== Test 2: Skill Registry ===")

    # Clear registry first
    registry._skills = {}

    # Register test skill
    test_skill = SkillSystemTestSkill()
    registry.register_skill(test_skill)

    # Verify registration
    assert registry.has_skill("test_skill"), "Skill should be registered"
    assert len(registry.get_skill_names()) == 1, "Should have 1 skill"

    # Retrieve skill
    retrieved = registry.get_skill("test_skill")
    assert retrieved.skill_name == "test_skill", "Retrieved skill should match"

    # List skills
    skills = registry.list_skills()
    assert len(skills) == 1, "Should list 1 skill"
    assert skills[0]["name"] == "test_skill", "Skill info should match"

    print("✅ Registry test passed")
    return True


@pytest.mark.asyncio
async def test_email_triage():
    """Test email triage skill (without actual email data)."""
    print("\n=== Test 3: Email Triage Skill ===")

    skill = EmailTriageSkill()
    context = SkillContext(
        user_id="test_user",
        intent="find emails from luisa",
        params={"contact": "luisa", "days_back": 30}
    )

    result = await skill.activate(context)

    # Should succeed even without cache (returns empty results)
    assert result.success, "Email triage should handle missing cache gracefully"
    assert "threads" in result.data, "Should return threads key"
    assert "count" in result.data, "Should return count key"

    print("✅ Email triage test passed")
    return True


@pytest.mark.asyncio
async def test_pattern_store():
    """Test pattern service with ZylchMemory."""
    print("\n=== Test 4: Pattern Service (ZylchMemory) ===")

    from zylch.services.pattern_service import PatternService

    # Create test db
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    service = PatternService(db_path=db_path)

    # Store a pattern
    pattern_id = service.store_pattern(
        skill="test_skill",
        intent="test intent",
        context={"test": "context"},
        action={"test": "action"},
        outcome="success",
        user_id="test_user"
    )

    assert pattern_id is not None, "Pattern should be stored"

    # Retrieve patterns using semantic search
    patterns = service.retrieve_similar_patterns(
        intent="test intent",
        skill="test_skill",
        user_id="test_user",
        limit=5
    )

    assert len(patterns) >= 1, "Should retrieve stored pattern"
    assert patterns[0]["skill"] == "test_skill", "Pattern should match"

    # Update confidence (Bayesian learning)
    service.update_pattern_confidence(pattern_id, success=True)

    # Clean up
    import os
    os.unlink(db_path)

    print("✅ Pattern service test passed")
    return True


@pytest.mark.asyncio
async def test_full_system():
    """Test full skill system integration."""
    print("\n=== Test 5: Full System Integration ===")

    # Clear and setup registry
    registry._skills = {}
    registry.register_skill(EmailTriageSkill())
    registry.register_skill(DraftComposerSkill())
    registry.register_skill(CrossChannelOrchestratorSkill(registry))

    # Verify all skills registered
    assert len(registry.get_skill_names()) == 3, "Should have 3 skills"

    # Create router (will fail without API key, but we can test structure)
    try:
        router = IntentRouter(registry)
        print("✅ Router initialized")
    except Exception as e:
        print(f"⚠️  Router initialization warning (expected without API key): {e}")

    # Test skill retrieval
    email_skill = registry.get_skill("email_triage")
    assert email_skill is not None, "Should retrieve email_triage skill"

    draft_skill = registry.get_skill("draft_composer")
    assert draft_skill is not None, "Should retrieve draft_composer skill"

    orchestrator = registry.get_skill("cross_channel_orchestrator")
    assert orchestrator is not None, "Should retrieve orchestrator skill"

    print("✅ Full system integration test passed")
    return True


async def main():
    """Run all tests."""
    print("🚀 Starting Zylch Skill System Tests (Phase A)")
    print("=" * 60)

    tests = [
        ("Base Skill", test_base_skill),
        ("Skill Registry", test_registry),
        ("Email Triage Skill", test_email_triage),
        ("Pattern Store", test_pattern_store),
        ("Full System Integration", test_full_system),
    ]

    passed = 0
    failed = 0

    for test_name, test_func in tests:
        try:
            result = await test_func()
            if result:
                passed += 1
        except Exception as e:
            print(f"❌ {test_name} failed: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print("\n" + "=" * 60)
    print(f"📊 Test Results: {passed} passed, {failed} failed")

    if failed == 0:
        print("🎉 All tests passed!")
        return 0
    else:
        print("⚠️  Some tests failed")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
