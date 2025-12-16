# Zylch Test Suite

## Overview

This test suite validates the Von Neumann Memory Architecture implementation in Zylch, ensuring proper data flow from email ingestion through Memory Agent to CRM Agent and Avatar generation.

## Test Structure

```
tests/
├── conftest.py                        # Shared fixtures
├── integration/
│   └── test_von_neumann_flow.py      # Integration tests
├── e2e/
│   └── test_sync.py                  # End-to-end tests
└── README.md                          # This file
```

## Test Categories

### Integration Tests (`tests/integration/test_von_neumann_flow.py`)

Tests the complete Von Neumann pipeline with all components:

1. **test_full_pipeline** - Complete data flow: Email → Memory Agent → identifier_map → CRM Agent → Avatar
2. **test_memory_to_avatar_flow** - Data flow from Memory Agent output to CRM Agent input
3. **test_identifier_deduplication** - Duplicate identifier handling
4. **test_avatar_computation_triggers** - Avatar queue and trigger system
5. **test_timestamp_consistency** - Timestamp consistency across layers
6. **test_multi_contact_flow** - Multiple contacts with data isolation

### E2E Tests (`tests/e2e/test_sync.py`)

End-to-end tests simulating real-world sync scenarios:

1. **test_sync_creates_memory_and_avatars** - Full sync pipeline with 5 varied emails
2. **test_incremental_sync_performance** - Incremental sync performance
3. **test_sync_with_duplicate_emails** - Duplicate email handling
4. **test_sync_with_errors** - Error recovery
5. **test_avatar_queue_processing** - Avatar computation queue
6. **test_memory_consistency_under_load** - Consistency under concurrent updates
7. **test_email_to_identifier_mapping** - Email archive to identifier_map integration
8. **test_identifier_to_avatar_flow** - identifier_map to avatars integration

## Prerequisites

1. **Supabase Configuration**: Set environment variables:
   ```bash
   export SUPABASE_URL="your-supabase-url"
   export SUPABASE_SERVICE_ROLE_KEY="your-service-role-key"
   ```

2. **Database Tables**: Ensure these tables exist in Supabase:
   - `emails` - Email archive
   - `identifier_map` - Contact identifiers (email, phone, LinkedIn)
   - `avatars` - Computed contact avatars
   - `avatar_compute_queue` - Avatar computation queue

3. **Python Dependencies**:
   ```bash
   pip install pytest pytest-asyncio
   ```

## Running Tests

### Run All Tests
```bash
# From project root
pytest tests/integration/ tests/e2e/
```

### Run Integration Tests Only
```bash
pytest tests/integration/test_von_neumann_flow.py
```

### Run E2E Tests Only
```bash
pytest tests/e2e/test_sync.py
```

### Run Specific Test
```bash
pytest tests/integration/test_von_neumann_flow.py::TestVonNeumannFlow::test_full_pipeline
```

### Run with Verbose Output
```bash
pytest tests/ -v
```

### Run with Print Statements
```bash
pytest tests/ -s
```

## Test Data

Tests use a dedicated test owner: `test_owner_von_neumann`

### Cleanup

Tests automatically clean up after themselves (optional). To manually clean up test data:

```python
from zylch.storage.supabase_client import SupabaseStorage

storage = SupabaseStorage.get_instance()
test_owner_id = "test_owner_von_neumann"

# Clean up emails
storage.client.table('emails').delete().eq('owner_id', test_owner_id).execute()

# Clean up avatars
storage.client.table('avatars').delete().eq('owner_id', test_owner_id).execute()

# Clean up identifiers
storage.client.table('identifier_map').delete().eq('owner_id', test_owner_id).execute()
```

## Test Fixtures

### Shared Fixtures (from `conftest.py`)

- **storage** - SupabaseStorage instance
- **test_owner_id** - Test user ID (`test_owner_von_neumann`)
- **test_email_data** - Factory for creating test emails
- **test_contact_data** - Sample contact data (5 contacts)
- **sample_emails_with_contact_info** - 5 pre-configured test emails
- **mock_gmail_client** - Mock Gmail client
- **mock_anthropic_client** - Mock Anthropic client

## Performance Expectations

### Integration Tests
- Each test: < 5 seconds
- Total suite: < 30 seconds

### E2E Tests
- test_sync_creates_memory_and_avatars: < 20 seconds
- test_incremental_sync_performance: < 10 seconds
- test_memory_consistency_under_load: < 15 seconds
- Total suite: < 60 seconds

## CI/CD Integration

### GitHub Actions Example
```yaml
name: Test Von Neumann Flow

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      - run: pip install -r requirements.txt
      - run: pytest tests/integration/ tests/e2e/ -v
        env:
          SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
          SUPABASE_SERVICE_ROLE_KEY: ${{ secrets.SUPABASE_SERVICE_ROLE_KEY }}
```

## Troubleshooting

### "Supabase not configured" Error
Set environment variables:
```bash
export SUPABASE_URL="your-url"
export SUPABASE_SERVICE_ROLE_KEY="your-key"
```

### "No module named 'pytest'" Error
Install pytest:
```bash
pip install pytest pytest-asyncio
```

### Tests Timeout
Increase timeout for async tests:
```python
@pytest.mark.asyncio(timeout=60)
async def test_long_running():
    ...
```

### Database Connection Issues
Check Supabase service is running and credentials are correct:
```python
from zylch.storage.supabase_client import SupabaseStorage
storage = SupabaseStorage.get_instance()
# Should not raise exception
```

## Architecture Validation

These tests validate the Von Neumann Memory Architecture:

```
┌─────────────────────────────────────────────────────────┐
│                         I/O                              │
│        (Email, Calendar, WhatsApp, Phone Calls)         │
└──────────────────────────┬──────────────────────────────┘
                           │
                           ▼
                    ┌─────────────┐
                    │   MEMORY    │  ← Tests verify writes
                    │    AGENT    │
                    └──────┬──────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────┐
│                      MEMORY                               │
│            (mass storage - the past)                      │
│  • identifier_map table                                  │
│  • contact_id linkage                                    │
└──────────────────────────┬───────────────────────────────┘
                           │
                           ▼
                    ┌─────────────┐
                    │     CRM     │  ← Tests verify reads
                    │    AGENT    │
                    └──────┬──────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────┐
│              WORKING MEMORY / CRM                         │
│              (registers - the present)                    │
│  • avatars table                                         │
│  • computed state                                        │
└──────────────────────────────────────────────────────────┘
```

## Contributing

When adding new tests:

1. **Integration tests** - Test data flow between components
2. **E2E tests** - Test complete user workflows
3. **Use fixtures** - Reuse test data from conftest.py
4. **Document** - Add docstrings explaining what's tested
5. **Performance** - Keep tests fast (< 5s per test)

## Related Documentation

- `/docs/architecture/VON_NEUMANN_MEMORY.md` - Architecture overview
- `/docs/architecture/SWARM_INSTRUCTIONS.md` - Agent implementation
- `.claude/ARCHITECTURE.md` - System architecture
