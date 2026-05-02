# Cleanup: dead `MrCallConfiguratorTrainer` references

status: planned · 2026-05-02 · single PR

## Why this exists

After the Firebase-signin landing on `main` (commits `25e668b..7bfcd93`),
the engine is left in a state where several files reference
configurator symbols that are not present in this checkout — and never
were. They survive only because the reachable code paths short-circuit
to "MrCall is not available" instead of crashing.

Commit `d62506c` proved the four imported sibling modules
(`variable_utils`, `llm_helper`, `config_tools`,
`feature_context_tool`) have never been tracked in this repo:

```
git log --all --diff-filter=A -- \
    'engine/zylch/tools/mrcall/variable_utils.py' \
    'engine/zylch/tools/mrcall/llm_helper.py' \
    'engine/zylch/tools/mrcall/config_tools.py' \
    'engine/zylch/tools/mrcall/feature_context_tool.py'
# (empty)
```

The matching trainers (`MrCallConfiguratorTrainer`, `MrCallAgentTrainer`)
were also never present. `engine/zylch/agents/trainers/__init__.py`
already comments their imports out with a `"loaded lazily"` note that
never panned out.

The reachable callers that depend on these ghosts:

- `engine/zylch/services/command_handlers.py` — 16+ refs to
  `MrCallConfiguratorTrainer`, plus an inline `from zylch.tools.mrcall.llm_helper
  import modify_variables_with_llm`. Powers the `/mrcall config`,
  `/mrcall train`, and `/mrcall feature` slash commands; all currently
  short-circuit with `"MrCall is not available."`.
- `engine/zylch/tools/factory.py:_create_mrcall_tools` (~lines 460-510) —
  the `if starchat:` branch builds a tool tuple from
  `GetAssistantCatalogTool`, `ConfigureAssistantTool`,
  `GetMrCallFeatureContextTool`. Whole branch is dead; the surrounding
  code already handles the absence.
- `engine/tests/test_mrcall_integration.py` — every test imports
  symbols that have never existed in this repo:
  `MRCALL_ADMIN_NAMESPACE`, `extract_variables`,
  `validate_variable_preservation`, `validate_no_placeholders`,
  `GetAssistantCatalogTool`, `ConfigureAssistantTool`,
  `SaveMrCallAdminRuleTool`. Pytest-collection-only red.

A reader who lands on this code today cannot tell whether the
configurator is "WIP that lost a commit" or "abandoned feature".

## Decision required: delete vs implement

**Recommendation: DELETE.**

1. Verified-never-functional: the dependencies were never tracked.
2. Source-of-truth lives elsewhere: the platform configurator with the
   same name, fully implemented, sits at
   `~/hb/mrcall-agent/mrcall_agent/agents/trainers/mrcall_configurator.py`
   (1572 lines, the FEATURES dict at the top). That is the production
   version; the desktop's copy was always a stub.
3. Product direction has moved: post-Firebase-signin the desktop's
   MrCall integration is *consumer*, not *configurator*. It reads
   businesses / calls via StarChat using the user's Firebase JWT (see
   `mrcall.list_my_businesses` RPC and the Phase-3 integration in
   `engine/zylch/tools/starchat_firebase.py`). A heavy local
   "configurator" is no longer the right product surface — point
   users to the dashboard for that.

If we ever change our minds and want a desktop configurator, copying
~1500 lines from `mrcall-agent` + adapting to BYOK LLM + writing the
four missing helper modules is a *project*, not a fix. Don't smuggle
it in here.

## Files to touch (delete path)

Use `grep` over symbols (not line numbers — the file shifts under
edits). The current state was captured by these searches:

```
grep -rn 'MrCallConfiguratorTrainer\|MrCallAgentTrainer\|GetAssistantCatalogTool\|ConfigureAssistantTool\|GetMrCallFeatureContextTool\|VARIABLE_TO_FEATURE\|modify_variables_with_llm\|modify_prompt_with_llm\|extract_variables\|validate_variable_preservation\|create_variable_preservation_instructions\|format_variable_changes\|MRCALL_ADMIN_NAMESPACE\|SaveMrCallAdminRuleTool\|validate_no_placeholders' engine/zylch engine/tests --include='*.py'
```

### `engine/zylch/services/command_handlers.py`

Three concerns to pull out cleanly:

- `/mrcall config` slash command (handler + helpers) — drop the trainer
  imports, replace the body with a single message:
  `"Configure your MrCall assistant from the dashboard at https://dashboard.mrcall.ai"`.
- `/mrcall train` (`_handle_mrcall_train`) — same, message-only.
- `/mrcall feature` switch — delete or stub.
- The 20-line module-level docstring describing the "layered training"
  architecture is no longer accurate — rewrite as a one-paragraph
  pointer to the dashboard.

Keep `/mrcall connect` (uses `oauth.py`, which IS real) untouched.

### `engine/zylch/tools/factory.py`

`_create_mrcall_tools`: delete the `if starchat:` branch entirely.
The function already returns an empty tuple in the `else` path; that's
the new singular behaviour.

### `engine/zylch/agents/trainers/__init__.py`

Lines 13-15 (the commented-out `# from .mrcall import …` and
`# from .mrcall_configurator import …`): delete. Leave a one-line
comment explaining the trainers belong to the platform, not the
desktop.

### `engine/zylch/tools/mrcall/__init__.py`

The post-`d62506c` docstring still says `"The matching trainer
(MrCallConfiguratorTrainer) is …"`. Trim it to just describe the
`oauth.py` re-export and stop. No other change to this file.

### `engine/tests/test_mrcall_integration.py`

Delete the file. Every test imports a never-existent symbol; nothing
exercises the live `oauth.py`. (If the appetite for tests grows, write
new ones in a separate PR that target what `oauth.py` actually does.)

### Anywhere else?

```
git grep -l 'MrCallConfiguratorTrainer\|GetAssistantCatalogTool\|ConfigureAssistantTool\|GetMrCallFeatureContextTool'
```

should return only the four files above (plus this brief). If it
doesn't, sweep them too.

## Verification (the way the user runs it)

1. Imports clean:
   ```
   PYTHONPATH=/home/mal/hb/mrcall-desktop/engine \
     /home/mal/private/zylch-standalone/venv/bin/python -c \
     "import zylch.tools.mrcall; from zylch.rpc.methods import METHODS; print(len(METHODS))"
   # expect: 33  (preserved from this session)
   ```
2. Pytest cleanly collects (no broken imports during collection):
   ```
   cd engine && pytest --collect-only 2>&1 | tail -5
   ```
3. Live REPL (this is the "test the way the user runs it" check):
   ```
   zylch -p <profile> repl
   /mrcall config
   /mrcall train
   ```
   Both should print the new "configure from the dashboard" message
   and return cleanly. No traceback.
4. The desktop app still boots, `account.who_am_i` still answers,
   and `mrcall.list_my_businesses` still returns the business list
   when signed in. (Smoke run — don't be thorough; the dead code
   is in unrelated handlers.)

## Acceptance

- `git grep MrCallConfiguratorTrainer engine/` → 0 hits.
- `git grep MrCallAgentTrainer engine/` → 0 hits.
- `git grep 'from zylch.tools.mrcall import' engine/` → only `oauth`
  imports remain.
- `git grep 'from zylch.tools.mrcall\.' engine/` → only `oauth`-prefixed.
- `pytest --collect-only` runs clean.
- Verification commands #1, #2, #3 above all pass.

## Out of scope (do NOT bundle)

- Any **new** feature. Pure cleanup.
- The CLI MrCall PKCE flow on `:19274` (`zylch init`) — that calls
  `from zylch.tools.mrcall.oauth import run_oauth_flow`. `oauth.py` is
  real and untouched by this PR.
- Renaming `zylch` → `mrcall` in env vars / data dir / CLI binary —
  that's its own dedicated execution plan
  (`docs/execution-plans/release-and-rename-l2.md`).
- Wiring `engine/zylch/tools/calendar_sync.py` to the new
  `provider='google_calendar'` OAuth tokens — separate work; see
  active-context for that thread.

## Pointers

- Audit trail of why these files are missing: commit `d62506c` body.
- Latest cross-cutting context: `~/hb/docs/active-context.md`
  2026-05-02 entry.
- Reference platform configurator (do NOT copy without an explicit
  decision): `~/hb/mrcall-agent/mrcall_agent/agents/trainers/mrcall_configurator.py:865`.
- Default Google calendar id is `primary`; constant in
  `engine/zylch/tools/google/calendar_oauth.py:DEFAULT_CALENDAR_ID`
  (single user → single account → single calendar = primary; secondary
  calendars are out of scope).

## Suggested commit shape

One commit:

```
chore(engine): delete dead MrCallConfiguratorTrainer references

The desktop's MrCall slash commands and tool factory referenced a
configurator that was never landed in this repo (verified via
git log --all --diff-filter=A — see d62506c). After the Firebase
signin landing the desktop is a CONSUMER of MrCall via StarChat,
not a configurator; the right surface for configuration is the
dashboard.

Deletes:
- /mrcall config, /mrcall train, /mrcall feature handler bodies in
  engine/zylch/services/command_handlers.py — replaced with a single
  "configure from the dashboard" message
- engine/zylch/tools/factory.py:_create_mrcall_tools `if starchat`
  branch
- engine/tests/test_mrcall_integration.py (every test imports a
  never-existent symbol)
- comments in engine/zylch/agents/trainers/__init__.py and
  engine/zylch/tools/mrcall/__init__.py referring to the missing
  trainers / submodules

If we ever want a local configurator, port from
mrcall-agent/mrcall_agent/agents/trainers/mrcall_configurator.py
in a fresh PR — explicitly out of scope here.
```
