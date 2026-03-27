# Harness Backlog

Enforcement gaps, missing tooling, and documentation needs discovered during development.

- [ ] No automated tests for MrCall agent (mrcall_agent.py, mrcall_context.py, mrcall_templates.py)
  Discovered: 2026-03-26
  Impact: Regressions in prompt building, tool selection, or variable fetching go undetected

- [ ] No integration test for SSE streaming endpoint (/api/chat/message/stream)
  Discovered: 2026-03-26
  Impact: Stream format changes break dashboard without warning

- [ ] No lint rule enforcing `verify=settings.starchat_verify_ssl` on httpx clients
  Discovered: 2026-03-26 (SSL errors on test env due to missing verify parameter)
  Impact: New httpx clients silently fail on test environment with self-signed certs

- [ ] Git branch topology alignment needed (main, dev, production diverged)
  Discovered: 2026-03-26
  Impact: Commits land on wrong branch, deploys miss changes, merge confusion
