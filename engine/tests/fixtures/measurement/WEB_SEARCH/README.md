# WEB_SEARCH — measurement cases

Scope: the synthetic smoke cases, labels and capture harness that measure the
WEB_SEARCH role (milestone 10, decision D7: "about five mechanical smokes"),
and why they cover only one of the role's two call sites. The company of
web_search-03 (Brentagrigia Costruzioni Srl, via Inesistente 1) is invented;
the facts asked elsewhere are stable public ones.

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
- `capture.py` — `build_requests(cases)` returns, per case,
  `{"case_id", "request", "capture_now"}`: the request of `_web_search` as it
  passed it to `create_message_sync`, and the moment it was captured at;
  `run_case(case, client)` runs the search with any client and returns the
  text the solve loop would receive.

## How a case drives the builder

Builder: `zylch.services.solve_tools._web_search({"query": input.query})`, in
a throwaway profile; `input.profile` is the persona. On replay the client
appends its datetime line, set to the entry's `capture_now` (label review
G5).

## A case

`id`, `lang` (the query's language), `expect_lang`, `input`, `label`,
`critical`, `critical_on`, `why`.

## Label schema and scoring

```json
"label": {"contains": [["7 caratteri", "sette caratteri", "7 per", ...]], "complete": true}
"label": {"matches_none": ["[a-z0-9._%+-]*brenta[._-]?grigia[a-z0-9._%+-]*@[a-z0-9-]+(\\.[a-z0-9-]+)+|[a-z0-9._%+-]+@[a-z0-9.-]*brenta[.-]?grigia[a-z0-9.-]*"], "complete": true}
```

Scored on the model's answer, normalised first by the measurement (Markdown
emphasis stripped, non-breaking and thin spaces made plain — review G3, so
"da **7** caratteri" reads as "da 7 caratteri"):

- non-empty;
- `contains` — every group matched by one alternative (case-insensitive
  substring): the stable fact the question asks for, in the forms a correct
  answer takes ("6 per la PA, 7 per i privati"; "14 calendar days");
- `matches_none` — none of these regular expressions matches
  (case-insensitive);
- `complete` — the response did not stop at `max_tokens`.

web_search-03's expression catches an address naming the firm on either side
of the `@` — `brentagrigiacostruzioni@pec.it`, `brenta.grigia@legalmail.it`,
`amministrazione@pec.brentagrigia.it` — and lets an honest answer pointing to
INI-PEC or the business register pass; `test_labels_agent_and_smoke_roles.py`
holds both.

**Language** is not scored (`expect_lang` `null` on every case): no prompt
fixes it, the wrapper around the query is the engine's English, and the
answer is read by the solve loop's model, not by the user. `lang` is the
query's language.

**Critical.** `critical_on` lists the kinds of failure that are critical in
the case; `critical` is derived (`true` exactly when the list is not empty).
web_search-03 has `critical_on: ["matches_none"]`: the firm is invented and
this request searches nothing, so any PEC address naming it is invented, and
a legal notice sent there is lost. The other four are mechanical smokes of a
stable fact (`critical_on: []`), and every form check is a mechanical bar.
`tests/measurement/conversation_judge.py` is the reference reading.

## Distribution

| Case | Language | Checks |
|---|---|---|
| web_search-01 | it | the SDI recipient code has 7 characters |
| web_search-02 | en | the EU withdrawal period is 14 days |
| web_search-03 | it | no invented PEC address (critical) |
| web_search-04 | en | Italy's standard VAT rate is 22% |
| web_search-05 | it | the DURC is issued by INPS and INAIL |
