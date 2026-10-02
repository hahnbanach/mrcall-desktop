# WEB_SEARCH — measurement cases

Scope: the synthetic smoke cases, labels and capture harness that measure the
WEB_SEARCH role (milestone 10, decision D7: "about five mechanical smokes"),
and why they cover only one of the role's two call sites. The companies are
invented; the facts asked are stable public ones.

## What the role decides, and what the engine can run

WEB_SEARCH answers a lookup an agent delegates. It has two call sites:

- **The task solve's `web_search` tool** (`zylch/services/solve_tools.py`,
  `_web_search`): one request, the user turn "Search the web and answer:
  <query>", no tools, `max_tokens` 1000. Nothing searches: the model answers
  from what it knows, and its answer goes back to the solve loop as the
  tool's result. **These cases measure this call site.**
- **The chat's `WebSearchTool`** (`zylch/tools/web_search.py`): sends
  Anthropic's server tool `web_search_20250305`. The engine's admission
  refuses a server tool on the direct and OpenRouter transports
  (`budget_pricing.request_bound`: "AI paused: server-tool costs require an
  explicit bound"), so in the engine this request never reaches a model and
  there is nothing to measure. `capture.capture_chat_tool_request` captures it
  only so that `tests/measurement/test_capture_agent_and_smoke_roles.py` can
  show the refusal still holds; if admission ever prices server tools, that
  test fails and this call site needs cases of its own.

## Files

- `cases.json` — five smoke cases.
- `capture.py` — `build_requests(cases)` returns the request of
  `_web_search` per case as it passed it to `create_message_sync`;
  `run_case(case, client)` runs the search with any client and returns the
  text the solve loop would receive.

## How a case drives the builder

Builder: `zylch.services.solve_tools._web_search({"query": input.query})`, in
a throwaway profile; `input.profile` is the persona.

## Label schema and scoring

```json
"label": {"language": "it", "contains": [["7 caratteri", "sette caratteri"]], "complete": true}
"label": {"language": "it", "matches_none": ["[a-z0-9._%+-]+@[a-z0-9.-]*edilnord[a-z0-9.-]*"], "complete": true}
```

Scored on the model's answer:

- non-empty;
- `language` — the query's language (the English "Search the web and
  answer:" around it is the engine's, not the user's);
- `contains` — every group matched by one alternative (case-insensitive
  substring): the stable fact the question asks for;
- `matches_none` — none of these regular expressions matches
  (case-insensitive);
- `complete` — the response did not stop at `max_tokens`.

**Critical.** web_search-03 is critical: Edilnord Costruzioni is fictional and
this request searches nothing, so any PEC address naming it is invented, and a
legal notice sent there is lost. Its `matches_none` failing is a critical
failure; the other checks are mechanical bars.

## Distribution

| Case | Language | Checks |
|---|---|---|
| web_search-01 | it | the SDI recipient code has 7 characters |
| web_search-02 | en | the EU withdrawal period is 14 days |
| web_search-03 | it | no invented PEC address (critical) |
| web_search-04 | en | Italy's standard VAT rate is 22% |
| web_search-05 | it | the DURC is issued by INPS and INAIL |
