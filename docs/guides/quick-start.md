# Zylch AI Quick Start Guide

## What is Zylch AI?

Zylch AI is a **single-agent AI assistant** for sales professionals that helps with:
- 📧 Email intelligence (read, draft, send)
- 👥 Contact enrichment (Gmail history, web search)
- 📅 Task scheduling (Google Calendar)
- 📬 Mass campaigns (SendGrid email, Vonage SMS)
- ☎️ Outbound calls (MrCall integration)

**Key principle: Human-in-the-loop** - Zylch AI assists, you decide.

## Installation

```bash
# Clone and enter directory
cd /Users/mal/starchat/zylch

# Run automated setup
bash setup.sh

# Activate virtual environment
source venv/bin/activate
```

## Configuration

### 1. Edit .env File

The `.env` file contains system configuration. Key settings:

```bash
# System configuration
STARCHAT_USERNAME=admin              # StarChat integration
STARCHAT_PASSWORD=xxx                # StarChat integration
SUPABASE_URL=https://xxx.supabase.co # Required for storage
SUPABASE_SERVICE_ROLE_KEY=xxx        # Required for storage

# User credentials are NOT in .env (BYOK model)
# Users connect services via CLI or web dashboard:
#   /connect anthropic  - Anthropic API key
#   /connect vonage     - Vonage SMS credentials
#   /connect pipedrive  - Pipedrive CRM token
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
python -m zylch.cli.main
```

### Example Interactions

```
You: /business fd81e076-9287-362e-8fa5-8ee51b2cdebf
[Selects MrCall assistant for saving contacts]

You: puoi cercare i contatti nel business per favore?
Zylch AI: Found 127 total contacts: customer=45, lead=32, prospect=28, unknown=22

You: who is john.doe@example.com?
Zylch AI: [Searches StarChat, Gmail history, enriches contact]

You: draft email to jane@example.com about project update
Zylch AI: [Generates draft with context, shows for approval]

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
- `/quit` - Exit Zylch AI

### Memory System (ZylchMemory)

Zylch AI learns from your corrections using a semantic memory system with vector-based search:

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
Zylch AIAgent (Claude Sonnet 4.5)
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
zylch/
├── zylch/                  # Main package
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

## What Works Now

✅ **Core Infrastructure**
- Configuration loading from .env
- Multi-tenant architecture with Firebase Auth
- Email archive with SQLite + FTS5 full-text search
- Model selection (Haiku/Sonnet/Opus tiering)

✅ **Agent System**
- ZylchAIAgent with Claude API and 30+ tools
- Native function calling with tool orchestration
- Behavioral memory with semantic search (ZylchMemory)
- Person-centric relationship intelligence

✅ **Email Intelligence**
- Gmail OAuth (read, send, drafts)
- Microsoft Outlook integration (Graph API)
- Two-tier caching: Archive (permanent) + Intelligence (30-day)
- Thread analysis, task detection, gap analysis
- AI-generated email detection

✅ **Calendar**
- Google Calendar integration with Meet links
- Outlook Calendar integration
- Email-to-event with automatic invites

✅ **Integrations**
- StarChat/MrCall (contacts, telephony)
- SendGrid (email campaigns)
- Vonage (SMS)
- Pipedrive CRM (optional)

✅ **Web Dashboard**
- Vue 3 + TypeScript + Tailwind CSS
- Firebase authentication (Google, Microsoft)
- Full feature parity with CLI
- BYOK (Bring Your Own Key) for Anthropic API

✅ **Automation**
- Triggered instructions system
- Webhook server (StarChat, SendGrid, Vonage)
- APScheduler for reminders

## Current Limitations

⚠️ **Single-Assistant Mode**: One assistant per owner (v0.2.0 - architecture ready for multi-assistant)
⚠️ **Local SQLite**: Supabase migration planned for production scaling
⚠️ **WhatsApp Integration**: Pending StarChat REST API endpoint

## Troubleshooting

### "Anthropic API key not configured"
- Run `/connect anthropic` in CLI or use web dashboard
- Enter your Anthropic API key (BYOK model)
- Key is stored encrypted in Supabase per-user

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

### Production Deployment
- [ ] Deploy backend to Railway
- [ ] Deploy frontend to Vercel
- [ ] Configure production domains (api.zylchai.com, app.zylchai.com)

### Phase H: Billing (Stripe)
- [ ] Set up Stripe subscription billing
- [ ] Implement pricing tiers (Starter $29, Pro $79, Business $199)
- [ ] Add feature gating based on subscription

### Phase I: Supabase Migration
- [ ] Migrate from SQLite to Supabase Postgres
- [ ] Enable Row-Level Security for multi-tenant
- [ ] Migrate vector search to pg_vector

### Phase J: Scaling
- [ ] Add Upstash Redis for rate limiting
- [ ] Set up Sentry for error tracking
- [ ] Load testing and performance optimization

## Development

### Run Tests

```bash
source venv/bin/activate
pytest tests/
```

### Add New Tool

1. Create tool in `zylch/tools/your_tool.py`
2. Inherit from `Tool` base class
3. Implement `execute()` and `get_schema()`
4. Register in `zylch/cli/main.py`

### Debug

```bash
# Enable debug logging
export LOG_LEVEL=DEBUG
python -m zylch.cli.main
```

## Resources

- **Architecture**: `.claude/ARCHITECTURE.md` - System design and key decisions
- **Development Plan**: `.claude/DEVELOPMENT_PLAN.md` - Current roadmap
- **API Reference**: `docs/api/API_REFERENCE.md` - Complete REST API documentation
- **Multi-Tenant**: `docs/features/multi-tenant-architecture.md` - Multi-tenant guide
- **Memory System**: `zylch_memory/ZYLCH_MEMORY_ARCHITECTURE.md` - Memory architecture
- **Anthropic Docs**: https://docs.anthropic.com/

## Support

For issues or questions:
1. Check `.claude/DEVELOPMENT_PLAN.md` for current status
2. Review logs for error messages
3. Consult `.claude/ARCHITECTURE.md` for design decisions

---

**Current Status: Phases A-G Complete** 🎉

Core agent, multi-tenant architecture, webhook server, and web dashboard are fully implemented. Ready for production deployment and billing integration.
