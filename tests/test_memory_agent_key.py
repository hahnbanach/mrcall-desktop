import pytest
from unittest.mock import MagicMock
from zylch.agents.memory_agent import MemoryWorker

# Override fixtures to avoid skipping due to missing Supabase config
@pytest.fixture
def storage():
    return MagicMock()

@pytest.fixture(autouse=True)
def cleanup_test_data():
    yield

class TestMemoryWorkerKey:
    def test_get_extraction_prompt_uses_correct_key(self):
        # Mock dependencies
        mock_storage = MagicMock()
        mock_storage.get_agent_prompt.return_value = "Test Prompt"
        
        # Instantiate worker
        # We need to mock other init calls
        with pytest.MonkeyPatch.context() as m:
            # Mock MemoryConfig and EmbeddingEngine to avoid real initialization
            m.setattr("zylch.agents.memory_agent.MemoryConfig", MagicMock())
            m.setattr("zylch.agents.memory_agent.EmbeddingEngine", MagicMock())
            m.setattr("zylch.agents.memory_agent.BlobStorage", MagicMock())
            m.setattr("zylch.agents.memory_agent.HybridSearchEngine", MagicMock())
            m.setattr("zylch.agents.memory_agent.LLMMergeService", MagicMock())
            m.setattr("zylch.agents.memory_agent.LLMClient", MagicMock())

            worker = MemoryWorker(
                storage=mock_storage,
                owner_id="test_owner",
                api_key="test_key",
                provider="anthropic"
            )
            
            # Access the prompt
            worker._get_extraction_prompt()
            
            # Verify the key used
            # This should be 'memory_email', but currently it is 'email'
            # So if we assert 'memory_email', the test should fail
            mock_storage.get_agent_prompt.assert_called_with("test_owner", "memory_email")
