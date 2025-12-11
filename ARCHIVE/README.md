# Archived Documentation

This directory contains historical documentation that has been superseded by newer versions or consolidated into the main documentation structure.

## Purpose

Documentation here is **archived, not deleted** to preserve project history and allow reference to previous implementations or decisions.

## Directory Structure

```
ARCHIVE/
├── README.md (this file)
├── OLD/ - Deprecated feature documentation
├── completion-reports/ - Historical completion reports
└── spec/ - Original specifications (pre-consolidation)
```

## What's Archived

### OLD/ - Deprecated Documentation
- **Email Archive System docs** - Superseded by `docs/features/email-archive.md`
- **CLI Archive Commands** - Integrated into `docs/guides/cli-commands.md`
- **Chat API docs** - Superseded by `docs/api/chat-api.md`
- **Testing guides** - Moved to `docs/development/TESTING.md`
- **Completion reports** - Historical project completion documentation

### completion-reports/ - Historical Reports
- Sprint completion reports
- Feature completion documentation
- Historical development milestones

### spec/ - Original Specifications
- **ZYLCH_SPEC.md** - Original comprehensive specification (consolidated into current docs)
  - Architecture details → `docs/architecture/overview.md`
  - Data model → `docs/architecture/data-model.md`
  - Feature details → Individual feature documentation files

## When to Use Archived Documentation

✅ **Use archived docs when:**
- Investigating historical decisions or architecture
- Understanding why certain approaches were chosen/rejected
- Researching previous implementations
- Tracing the evolution of a feature

❌ **Don't use archived docs for:**
- Current development work (use `docs/` instead)
- API integration (use `docs/api/` instead)
- Feature implementation (use `docs/features/` instead)
- Production deployment (use `docs/guides/deployment.md`)

## Current Documentation

For up-to-date documentation, see:
- **Features**: `docs/features/` - Current feature documentation
- **Guides**: `docs/guides/` - Setup and user guides
- **API**: `docs/api/` - API reference documentation
- **Architecture**: `docs/architecture/` - System design and architecture
- **Development**: `docs/development/` - Development guidelines and testing

## Archive Policy

Documents are archived when:
1. A feature is completely rewritten with new documentation
2. Documentation is consolidated from multiple sources into one
3. Information becomes outdated but has historical value
4. Implementation approach changes fundamentally

**Note**: We never delete documentation - we archive it. This preserves institutional knowledge and allows future developers to understand the project's evolution.

---

**Last Updated**: December 2025
