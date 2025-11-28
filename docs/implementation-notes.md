# Zylch Implementation Notes

## Recent Changes (2025-11-27)

### Multi-Tenant Single-Assistant Constraint (v0.2.0)

**Objective**: Allow only ONE Zylch assistant per owner to avoid StarChat modifications while maintaining multi-tenant architecture for future expansion.

**Implementation**:
- `AssistantManager.create_assistant()` validates and blocks multiple assistants per owner
- Auto-creation of `default_assistant` on first CLI startup in `zylch/cli/main.py`
- Added `owner_id` and `zylch_assistant_id` to `ToolConfig` for multi-tenant support
- Namespace structure maintained: `{owner}:{assistant}:{contact}` for future multi-assistant support

**Files Modified**:
- `zylch/services/assistant_manager.py` - validation logic
- `zylch/cli/main.py` - auto-creation on initialize
- `zylch/tools/config.py` - added multi-tenant fields
- `docs/features/multi-tenant-architecture.md` - comprehensive documentation
- `README.md` - updated with multi-tenant feature
- `CHANGELOG.md` - release notes

**Key Decision**: Temporary single-assistant limitation allows forward progress without StarChat database changes. Architecture supports future multi-assistant expansion.

---

### Contact Enrichment Performance Fix

**Problem**: Web search during contact enrichment took 10+ minutes, executed automatically even when not needed.

**Solution**: Changed web search from automatic to explicit opt-in only.

**Implementation**:
- Modified `zylch/agent/prompts.py:170`
- Prompt instruction: "**Web search**: ONLY if user EXPLICITLY asks (e.g., 'cerca sul web', 'search web for...'). NEVER search web automatically."
- Gmail search remains automatic when cache is empty/stale
- Preserves 30-day cache first check

**Result**: Contact enrichment completes in seconds instead of 10+ minutes when web search not needed.

---

### Contact Dual-Save Clarification

**Problem**: Users confused about where enriched contacts are saved. LLM asked "save to StarChat?" without mentioning ZylchMemory.

**Solution**: Clarified that `save_contact` saves to BOTH locations automatically.

**Implementation**:
1. **Tool Description** (`zylch/tools/factory.py:1516`):
   ```python
   description="Save enriched contact data to BOTH StarChat (structured contact) AND ZylchMemory (semantic person-centric namespace). Single call saves to both locations."
   ```

2. **Prompt Instructions** (`zylch/agent/prompts.py:175-176`):
   ```
   - **When asking to save**: Explain that `save_contact` saves BOTH to StarChat (structured data) AND ZylchMemory (semantic person-centric namespace)
   - When user approves, call `save_contact` which automatically saves to both locations
   ```

3. **Implementation** (already present at `zylch/tools/factory.py:1624-1663`):
   - Saves to StarChat: structured contact with variables
   - Saves to ZylchMemory: semantic summary with namespace `{owner}:{assistant}:{contact_id}`, category `"person"`, confidence `0.9`
   - Non-fatal error handling for ZylchMemory save

**Result**: LLM now clearly communicates dual-save when asking permission. Users understand contact data is stored in both StarChat (for CRM operations) and ZylchMemory (for semantic search).

---

## Architecture Principles

### Person-Centric Memory
- All contact data stored with namespace: `{owner}:{assistant}:{contact_id}`
- Category: `"person"` for contact profiles
- Enables semantic search across all contact information
- Complements StarChat's structured CRM data

### Single-Assistant Mode (v0.2.0)
- Temporary constraint: one assistant per owner
- Simplifies development without StarChat changes
- Full namespace structure maintained for future expansion
- Auto-creation ensures seamless user experience

### Contact Enrichment Strategy
1. Check ZylchMemory cache (30-day TTL) - FIRST
2. Check StarChat contacts - if cache miss
3. Search Gmail history - if contact unknown/stale
4. Web search - ONLY on explicit user request
5. Save to both StarChat + ZylchMemory - single operation

---

## Development Notes

### Multi-Tenant Testing
- Test with different `OWNER_ID` values in `.env`
- Verify namespace isolation: `{owner}:{assistant}:{contact}`
- Check assistant auto-creation on first CLI run
- Validate single-assistant constraint blocking

### Contact Enrichment Testing
- Test without web search request (should be fast)
- Test with "cerca sul web" (should execute web search)
- Verify dual-save to StarChat + ZylchMemory
- Check ZylchMemory namespace: `/memory --list --namespace owner_id:assistant_id:contact_id`

### Performance Optimization
- Web search opt-in: Reduces enrichment time from 10+ minutes to seconds
- Cache-first strategy: 30-day TTL minimizes API calls
- HNSW vector search: O(log n) semantic memory retrieval
- Dual-save non-fatal: StarChat save succeeds even if ZylchMemory fails

---

## Future Enhancements

### Multi-Assistant Support (v0.3.0+)
When StarChat database supports multiple assistants per owner:
1. Remove single-assistant validation in `AssistantManager`
2. Add assistant selection UI/CLI commands
3. Update documentation to remove constraint warning
4. Namespace structure already supports: `{owner}:{assistant}:{contact}`

### Contact Intelligence
- Semantic search across contact history
- Relationship strength scoring from email patterns
- Automatic follow-up suggestions based on interaction gaps
- Cross-contact pattern recognition (common companies, referrals)

---

*Last Updated: 2025-11-27*
