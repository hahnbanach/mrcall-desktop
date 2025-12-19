# Documentation Standards

## Documentation Philosophy

- **Write for your future self**: Document decisions, not just code
- **Examples over explanations**: Show how, not just what
- **Keep it updated**: Outdated docs are worse than no docs
- **User-focused**: Write from the user's perspective

## Documentation Structure

```
zylch/
├── CLAUDE.md                    # Claude Code instructions (concise)
├── README.md                    # Project overview
├── CHANGELOG.md                 # Version history
├── .claude/                     # Developer guidelines
│   ├── ARCHITECTURE.md          # System design
│   ├── CONVENTIONS.md           # Code standards
│   ├── TESTING.md               # Test strategy
│   └── DOCUMENTATION.md         # This file
├── docs/                        # User-facing documentation
│   ├── README.md                # Documentation index
│   ├── features/                # Feature documentation
│   │   ├── email-archive.md
│   │   ├── relationship-intelligence.md
│   │   ├── task-management.md
│   │   ├── calendar-integration.md
│   │   └── entity-memory-system.md
│   ├── api/                     # API documentation
│   │   └── chat-api.md
│   ├── setup/                   # Setup guides
│   │   ├── quick-start.md
│   │   ├── gmail-oauth.md
│   │   └── email-sending-setup.md
│   ├── admin/                   # Admin documentation
│   │   └── gmail-push-notifications-analysis.md
│   └── archive/                 # Historical docs
│       ├── completion-reports/
│       └── *.md
└── spec/                        # Technical specifications
    ├── ZYLCH_SPEC.md
    ├── ZYLCH_BUSINESS_MODEL.md
    ├── ZYLCH_DEVELOPMENT_PLAN.md
    └── MEMORY_GAP_ANALYSIS.md
```

## Documentation Types

### 1. Developer Guidelines (`.claude/`)

**Audience**: Claude Code, future developers
**Purpose**: Architectural decisions, conventions, patterns
**Location**: `.claude/`

**Contents**:
- System architecture
- Key design decisions
- Code conventions
- Testing strategy

**Format**: Markdown, technical, detailed

### 2. User Documentation (`docs/`)

**Audience**: End users, integrators
**Purpose**: How to use features, APIs
**Location**: `docs/`

**Subdirectories**:
- `features/` - Feature guides
- `api/` - API documentation
- `setup/` - Setup and configuration
- `admin/` - Administrative tasks

**Format**: Markdown, user-friendly, examples

### 3. Technical Specifications (`spec/`)

**Audience**: Architects, designers
**Purpose**: Requirements, design specs
**Location**: `spec/`

**Contents**:
- Business requirements
- System specifications
- Architecture diagrams
- Analysis documents

**Format**: Markdown, formal, comprehensive

### 4. Code Documentation (Docstrings)

**Audience**: Developers using the code
**Purpose**: API reference, inline help
**Location**: In Python files

**Format**: Google-style docstrings

```python
def search_messages(
    query: str,
    limit: int = 10
) -> List[Dict[str, Any]]:
    """Search archived emails using full-text search.

    Args:
        query: Search query string (searches subject, body, from)
        limit: Maximum number of results to return (1-100)

    Returns:
        List of message dictionaries with keys:
        - id: Message ID
        - subject: Email subject
        - from_email: Sender email
        - date: RFC2822 date string
        - body_plain: Plain text body

    Raises:
        ValueError: If query is empty or limit out of range

    Example:
        >>> messages = archive.search_messages("project", limit=5)
        >>> print(messages[0]['subject'])
        "Project Update Q4"
    """
```

## When to Document

### Always Document
- **New features**: Write user docs in `docs/features/`
- **API endpoints**: Document in `docs/api/`
- **Breaking changes**: Update CHANGELOG.md
- **Design decisions**: Add to `.claude/ARCHITECTURE.md`
- **Configuration changes**: Update setup guides

### Sometimes Document
- **Bug fixes**: Add to CHANGELOG if user-visible
- **Refactoring**: Update architecture docs if structure changes
- **Performance improvements**: Note in CHANGELOG if significant

### Don't Document
- **Trivial changes**: Comment typos, formatting
- **WIP features**: Wait until complete
- **Internal implementation details**: Use code comments instead

## Documentation Templates

### Feature Documentation Template

```markdown
# Feature Name

**Status**: Production Ready / Beta / Experimental
**Completed**: Date

## Overview

Brief description (1-2 paragraphs) of what the feature does and why it exists.

## Quick Start

Minimal example to get started in <5 minutes.

## Usage

### Common Use Cases

#### Use Case 1
Code example and explanation

#### Use Case 2
Code example and explanation

## Configuration

Environment variables and settings.

## API Reference

Detailed API documentation (if applicable).

## Examples

### Python Example
...

### CLI Example
...

### cURL Example
...

## Troubleshooting

Common issues and solutions.

## Performance

Benchmarks and optimization tips.

## Known Limitations

Current limitations and workarounds.

## Future Enhancements

Planned improvements (link to issues/TODOs).
```

### API Endpoint Documentation Template

```markdown
## Endpoint Name

**Method**: POST/GET/...
**Path**: `/api/resource/action`

Brief description.

### Request

**Body**:
\```json
{
  "param1": "value",
  "param2": 123
}
\```

**Parameters**:
- `param1` (required): Description
- `param2` (optional): Description (default: value)

### Response

**Success (200)**:
\```json
{
  "success": true,
  "data": {...}
}
\```

**Error (4xx/5xx)**:
\```json
{
  "detail": "Error message"
}
\```

### Example

\```bash
curl -X POST "http://localhost:8000/api/resource/action" \
  -H "Content-Type: application/json" \
  -d '{"param1": "value"}'
\```
```

## Writing Style

### Be Concise
❌ **Bad**: "This function is designed to facilitate the searching of messages that have been archived in the database by accepting a query parameter"

✅ **Good**: "Search archived messages"

### Use Active Voice
❌ **Bad**: "The email is sent by the agent"

✅ **Good**: "The agent sends the email"

### Show, Don't Tell
❌ **Bad**: "You can search emails by calling the search function with a query parameter"

✅ **Good**:
```python
messages = archive.search_messages(query="project", limit=10)
```

### Be Specific
❌ **Bad**: "May take a while"

✅ **Good**: "Takes ~2 minutes for 500 emails (one-time)"

### Use Examples
❌ **Bad**: "Use the format YYYY-MM-DD for dates"

✅ **Good**:
```python
# Format: YYYY-MM-DD
date = "2025-11-23"
```

## Code Comments

### When to Comment

**DO comment**:
- Why (business logic, design decisions)
- Workarounds and hacks
- Complex algorithms
- Non-obvious behavior

```python
# Use delete + create instead of update to preserve threadId
# Gmail API's update() doesn't preserve threadId
self.gmail.drafts().delete(userId='me', id=draft_id).execute()
new_draft = self.gmail.drafts().create(userId='me', body=create_body).execute()
```

**DON'T comment**:
- What (obvious from code)
- Restating function name
- Commented-out code (delete it)

### Comment Style

```python
# Good: Explains WHY
# ALWAYS preserve manually closed threads - user explicitly closed them
if existing and existing.get('manually_closed'):
    logger.debug(f"Preserving manually closed thread: {thread_id}")
    needs_analysis = False

# Bad: Explains WHAT (obvious)
# Check if manually closed
if existing and existing.get('manually_closed'):
    needs_analysis = False
```

## Changelog Maintenance

### CHANGELOG.md Format

```markdown
# Changelog

## [Unreleased]
### Added
- New feature X
### Changed
- Modified behavior of Y
### Fixed
- Bug Z

## [1.2.0] - 2025-11-23
### Added
- Email archive system with incremental sync
- Chat API endpoint for conversational AI
### Changed
- Email sync now uses archive (100x faster)
### Fixed
- Manual thread closure now persists across syncs
```

### When to Update CHANGELOG
- New features (Added)
- Breaking changes (Changed)
- Bug fixes (Fixed)
- Deprecations (Deprecated)
- Removals (Removed)
- Security fixes (Security)

## Documentation Review Checklist

Before committing documentation:

- [ ] **Accurate**: Information is correct and up-to-date
- [ ] **Complete**: All necessary information included
- [ ] **Clear**: Easy to understand for target audience
- [ ] **Examples**: Code examples work as shown
- [ ] **Links**: All internal links work
- [ ] **Spelling**: No typos or grammar errors
- [ ] **Formatting**: Markdown renders correctly
- [ ] **Organized**: In correct location and category

## Documentation Tools

### Markdown Linting
```bash
# Install markdownlint
npm install -g markdownlint-cli

# Check docs
markdownlint docs/**/*.md
```

### Link Checking
```bash
# Install markdown-link-check
npm install -g markdown-link-check

# Check links
markdown-link-check docs/**/*.md
```

### API Documentation
FastAPI auto-generates API docs:
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

## Claude-Flow Memory

Store critical information in claude-flow memory:

```python
# Store in "zylch" namespace
/memory --store architecture_decision "Two-tier email caching: Archive (permanent) + Intelligence (30-day analyzed)"
/memory --store important_pattern "Person-centric task detection aggregates threads by contact"
/memory --store configuration "Manual closure flag: manually_closed=True prevents re-analysis"
```

### What to Store in Memory
- **Architectural decisions**: Why we chose X over Y
- **Important patterns**: Key implementation details
- **Configuration gotchas**: Non-obvious settings
- **Known issues**: Current limitations

### What NOT to Store
- Implementation details (use code comments)
- User-facing docs (use markdown files)
- Temporary information

## Summary

- **User docs** → `docs/` (features, API, setup)
- **Developer docs** → `.claude/` (architecture, conventions)
- **Specs** → `spec/` (requirements, analysis)
- **Code docs** → Docstrings (API reference)
- **Critical info** → Claude-flow memory (decisions, patterns)

**Golden rule**: Document decisions, not code. The code shows WHAT, docs explain WHY.
