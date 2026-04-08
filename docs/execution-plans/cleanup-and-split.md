# Code Cleanup and File Splitting
status: active

## Goal
Bring all files under 500-line guideline, delete dead code, fix lint.

## Steps
- [ ] Delete `zylch/intelligence/` (empty)
- [ ] Delete `zylch/webhook/` (empty)
- [ ] Investigate `zylch/ml/anonymizer.py` — delete if unused
- [ ] Investigate `zylch/router/intent_classifier.py` — delete if unused
- [ ] Investigate `zylch/assistant/` — delete if unused
- [ ] Split `command_handlers.py` (5137 → multiple modules by domain)
- [ ] Split `gmail_tools.py` (988 → search/draft/send)
- [ ] Run `black zylch/` and `ruff check --fix zylch/`
- [ ] Rewrite or delete stale `tests/` directory

## Decisions Made
- aisuite dropped in favor of direct Anthropic/OpenAI SDK calls (httpx conflict with neonize)

## Open Questions
- Should `command_handlers.py` split by domain (email, mrcall, agent, memory) or by pattern (handlers, helpers)?
