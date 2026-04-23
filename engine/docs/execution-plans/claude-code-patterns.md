# Claude Code Architectural Patterns for Zylch
status: active

## Goal
Apply 4 patterns from Claude Code's architecture to improve Zylch's cost, speed, UX.

## Steps
- [x] Prompt caching — trained prompts as Anthropic cached system prompts
- [x] Parallel LLM — asyncio.Semaphore(5) + gather in memory/task workers
- [x] Dream system — `zylch dream` with 3-gate trigger and 4-phase consolidation
- [x] Telegram proactive digest — APScheduler 8am/8pm task summaries
- [ ] End-to-end test: `zylch process` with prompt caching on real data
- [ ] End-to-end test: `zylch dream` gate checks and prune
- [ ] End-to-end test: Telegram digest delivery

## Decisions Made
- aisuite dropped entirely (httpx<0.28 conflict with neonize) — direct Anthropic/OpenAI SDK
- Legacy prompts with `{from_email}` format placeholders fall back to non-cached mode
- Dream uses file lock (not DB lock) for simplicity
- Digest schedule hardcoded to 8am/8pm (configurable later via .env)
- Process pipeline default changed from 30 to 7 days
- WhatsApp contacts derived from messages (neonize has no get_all_contacts API)

## Open Questions
- Should dream auto-run after `zylch sync` if gates pass?
- Should digest frequency be configurable via TELEGRAM_DIGEST_HOURS env var?
- Memory worker parallel: is 5 concurrent the right default for Anthropic rate limits?
