# MrPark Quick Start Guide

## What is MrPark?

MrPark is a **single-agent AI assistant** for sales professionals that helps with:
- 📧 Email intelligence (read, draft, send)
- 👥 Contact enrichment (Gmail history, web search)
- 📅 Task scheduling (Google Calendar)
- 📬 Mass campaigns (SendGrid email, Vonage SMS)
- ☎️ Outbound calls (MrCall integration)

**Key principle: Human-in-the-loop** - MrPark assists, you decide.

## Installation

```bash
# Clone and enter directory
cd /Users/mal/starchat/mrpark

# Run automated setup
bash setup.sh

# Activate virtual environment
source venv/bin/activate
```

## Configuration

### 1. Edit .env File

The `.env` file is already created with credentials from mcp-gateway. Key settings:

```bash
# Required
ANTHROPIC_API_KEY=sk-ant-api03-...  # Already set ✅
STARCHAT_USERNAME=admin              # Already set ✅
STARCHAT_PASSWORD=ujoy4ZaiNieNeng6   # Already set ✅

# Optional (for full functionality)
SENDGRID_API_KEY=your_key_here
VONAGE_API_KEY=your_key_here
VONAGE_API_SECRET=your_secret_here
```

### 2. Gmail OAuth Setup (Optional)

For Gmail integration, you need OAuth credentials from Google Cloud Console:

1. Go to: https://console.cloud.google.com/
2. Create project or select existing
3. Enable Gmail API
4. Create OAuth 2.0 credentials (Desktop app)
5. Download JSON and save as: `credentials/gmail_oauth.json`

**First run will open browser for authentication.**

## Usage

### Test Basic Functionality

```bash
source venv/bin/activate
python test_basic.py
```

Expected output:
```
✅ Configuration loading
✅ JSON cache working
✅ StarChat client initialized
✅ Model selector working
```

### Run Interactive CLI

```bash
source venv/bin/activate
python -m mrpark.cli.main
```

### Example Interactions

```
You: /business fd81e076-9287-362e-8fa5-8ee51b2cdebf
[Selects MrCall assistant for saving contacts]

You: puoi cercare i contatti nel business per favore?
MrPark: Found 127 total contacts: customer=45, lead=32, prospect=28, unknown=22

You: who is john.doe@example.com?
MrPark: [Searches StarChat, Gmail history, enriches contact]

You: draft email to jane@example.com about project update
MrPark: [Generates draft with context, shows for approval]

You: /clear
[Clears conversation history]

You: /quit
[Exits]
```

### CLI Commands

- `/help` - Show help message
- `/clear` - Clear conversation history
- `/history` - Show conversation history
- `/memory` - Manage behavioral memory (see below)
- `/quit` - Exit MrPark

### Memory System (ReasoningBank)

MrPark learns from your corrections using a two-tier memory system:

**Quick Examples:**
```bash
# List all memories
/memory --list

# Add personal correction
/memory --add "Used tu instead of lei" "Always use lei with Luisa" formality studioped.boni@gmail.com

# Add global meta-rule
/memory --add --global "Didn't check past style" "Always check past emails for tu/lei" context

# Show statistics
/memory --stats --all

# Get help
/memory --help
```

For complete guide, see `MEMORY_USAGE.md`

## Architecture

### Single-Agent Design

```
User Input
    ↓
MrParkAgent (Claude Sonnet 4.5)
    ↓
Tools (via native function calling):
  - query_contacts
  - update_contact
  - enrich_contact
  - (future: email drafting, calendar, campaigns)
    ↓
Human Approval
    ↓
Action Execution
```

### Model Selection (Automatic)

- **Haiku** (claude-3-5-haiku): Classification, simple queries (~$0.92/1K emails)
- **Sonnet** (claude-sonnet-4-5): Email drafting, enrichment (~$7/1K emails)
- **Opus** (claude-opus-4): Executive communications only (<5% volume)

Model selection happens automatically based on your message content.

## Project Structure

```
mrpark/
├── mrpark/                  # Main package
│   ├── agent/              # Agent core + model selection
│   ├── tools/              # All tools (contacts, gmail, sendgrid, vonage)
│   ├── cache/              # JSON cache for enrichment
│   ├── cli/                # Interactive CLI
│   └── config.py           # Configuration management
├── tests/                   # Test suite
├── credentials/            # OAuth tokens (gitignored)
├── cache/                  # Cached contact data (gitignored)
├── data/                   # Campaign templates (gitignored)
├── .env                    # Configuration (gitignored)
└── pyproject.toml          # Dependencies
```

## What Works Right Now (Phase 1)

✅ **Core Infrastructure**
- Configuration loading from .env
- JSON cache with 30-day TTL
- StarChat client (BasicAuth)
- Model selection (Haiku/Sonnet/Opus)

✅ **Agent**
- Anthropic SDK integration
- Native function calling
- Conversation history
- Tool execution loop

✅ **Tools (Basic)**
- query_contacts - Search StarChat contacts
- update_contact - Update contact variables
- enrich_contact - Enrich from Gmail + cache
- list_all_contacts - **NEW** - List all contacts for a business

✅ **Clients**
- Gmail (OAuth, search, send, drafts)
- SendGrid (mass email)
- Vonage (SMS campaigns)
- StarChat (contacts)

## Known Limitations (Current Phase)

⚠️ **StarChat Contact API**: May need Firebase realm configuration for production
⚠️ **Gmail OAuth**: Requires manual Google Cloud Console setup
⚠️ **Web Search**: Not yet implemented (needed for contact enrichment)
⚠️ **Calendar**: Not yet implemented (Phase 3)
⚠️ **Campaign Management**: Not yet implemented (Phase 5)

## Troubleshooting

### "ANTHROPIC_API_KEY not set"
- Check `.env` file exists
- Check `ANTHROPIC_API_KEY=` has value
- Restart after editing .env

### "Gmail credentials not found"
- Skip Gmail features for now, or
- Follow Gmail OAuth setup above

### "StarChat 404/405 error"
- This is expected in development
- Contact operations need proper realm configuration
- Non-critical for basic testing

### Import errors
- Run: `source venv/bin/activate`
- Run: `pip install -e .`

## Next Steps

### Immediate (Phase 1 completion)
1. ✅ **Test agent conversation** - Chat with MrPark in CLI
2. 🔲 Configure StarChat realm properly
3. 🔲 Add web search for enrichment
4. 🔲 Set up Gmail OAuth

### Phase 2 (Enrichment & Classification)
- Contact classification logic
- Priority scoring
- Humanized descriptions
- Email exchange history tracking

### Phase 3 (Email Drafting & Calendar)
- Google Calendar integration
- Email draft generation
- Daily digest
- Task scheduling

### Phase 4+ (Advanced Features)
- Multi-account Gmail
- Mass email campaigns
- Campaign automation (email open → call)
- CRM integration

## Development

### Run Tests

```bash
source venv/bin/activate
pytest tests/
```

### Add New Tool

1. Create tool in `mrpark/tools/your_tool.py`
2. Inherit from `Tool` base class
3. Implement `execute()` and `get_schema()`
4. Register in `mrpark/cli/main.py`

### Debug

```bash
# Enable debug logging
export LOG_LEVEL=DEBUG
python -m mrpark.cli.main
```

## Resources

- **Spec**: `MRPARK_SPEC.md` - Complete implementation specification
- **Status**: `IMPLEMENTATION_STATUS.md` - Current progress tracking
- **Memory System**: `REASONING_BANK_DESIGN.md` - Memory architecture
- **Memory Usage**: `MEMORY_USAGE.md` - CLI commands and workflows
- **Tasks**: `TASK_MANAGEMENT.md` - Person-centric task system
- **API Catalog**: `../STARCHAT_COMPLETE_API_CATALOG.md` - StarChat API reference
- **Anthropic Docs**: https://docs.anthropic.com/

## Support

For issues or questions:
1. Check `IMPLEMENTATION_STATUS.md` for known issues
2. Review logs for error messages
3. Consult `MRPARK_SPEC.md` for architecture details

---

**Current Status: Phase 1 Foundation - 80% Complete** 🎉

Core architecture implemented. Agent is conversational and ready for tool development.
