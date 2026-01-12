import pytest
from unittest.mock import Mock, MagicMock
from zylch.agents.memory_agent_email_trainer import EmailMemoryAgentTrainer

# Override fixtures to avoid skipping due to missing Supabase config
@pytest.fixture
def storage():
    return MagicMock()

@pytest.fixture(autouse=True)
def cleanup_test_data():
    yield

class TestEmailMemoryAgentTrainer:
    def test_format_email_samples_truncation(self):
        # Mock dependencies
        mock_storage = MagicMock()
        
        # Initialize trainer
        trainer = EmailMemoryAgentTrainer(
            storage=mock_storage,
            owner_id="test_owner",
            api_key="test_key",
            user_email="test@example.com",
            provider="anthropic"
        )
        
        # Create a thread with a very long email body
        long_body = "a" * 15000
        threads = [
            {
                "emails": [
                    {
                        "subject": "Long Thread",
                        "from_email": "sender@example.com",
                        "date": "2025-01-01",
                        "body_plain": long_body
                    }
                ]
            }
        ]
        
        # Call _format_email_samples
        samples = trainer._format_email_samples(threads)
        
        # Verify truncation
        assert "...(truncated)" in samples
        
        # The body part in the sample should be 12000 chars + "...(truncated)"
        # Note: The sample string includes "Body: ", newlines, etc.
        # So we check if the long sequence of 'a's is truncated.
        
        # 12000 'a's should be present
        assert "a" * 12000 in samples
        
        # 12001 'a's should NOT be present (because it's truncated)
        assert "a" * 12001 not in samples

    def test_format_email_samples_no_truncation(self):
        # Mock dependencies
        mock_storage = MagicMock()
        
        # Initialize trainer
        trainer = EmailMemoryAgentTrainer(
            storage=mock_storage,
            owner_id="test_owner",
            api_key="test_key",
            user_email="test@example.com",
            provider="anthropic"
        )
        
        # Create a thread with a short email body
        short_body = "Short body"
        threads = [
            {
                "emails": [
                    {
                        "subject": "Short Thread",
                        "from_email": "sender@example.com",
                        "date": "2025-01-01",
                        "body_plain": short_body
                    }
                ]
            }
        ]
        
        # Call _format_email_samples
        samples = trainer._format_email_samples(threads)
        
        # Verify NO truncation
        assert "...(truncated)" not in samples
        assert "Short body" in samples

if __name__ == "__main__":
    pytest.main([__file__])