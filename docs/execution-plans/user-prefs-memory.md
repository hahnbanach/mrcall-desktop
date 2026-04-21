# User Preferences Memory (feedback-type blobs)

status: active
created: 2026-04-21
owner: next session (fresh context recommended)

## Goal

Give Zylch's chat LLM a way to persist *user preferences and working rules*
that it learns in conversation — the equivalent of Claude Code's `feedback_*`
memory type. Today the only place such rules live is the single
`USER_NOTES` env string (manual edit). A blob-per-preference lets the LLM
add, update, and retrieve them autonomously, and lets the user inspect
them.

Out of scope: contact/entity blobs (already working), USER_SECRET_INSTRUCTIONS
(already injected), any rework of the memory worker.

## Why this is worth doing

- Today the LLM cannot remember "scrivi ai fornitori in italiano", "non
  rifiutare mai riunioni venerdì", "usa sempre il Lei con clienti nuovi"
  across sessions unless the user manually edits USER_NOTES.
- The infrastructure already exists: `create_memory(content, namespace)`
  was added in commit `0b9e4e8`. We just need a namespace convention + a
  read path that feeds the cached system prompt.

## What to build

1. **Namespace convention**: `prefs:<owner_id>`
   Sibling to `user:<owner_id>` (auto-extracted contacts). No schema
   change — `blobs` already has a `namespace` column.

2. **Write path**: already there. LLM calls
   `create_memory(content="<preference>", namespace="prefs:<owner_id>")`
   or `update_memory(blob_id=..., new_content=...)` after
   `search_local_memory`. No new tool.

3. **Read path** (new):
   - In `zylch/services/solve_constants.py::get_personal_data_section()`,
     after reading USER_NOTES, query all blobs with
     `namespace == f"prefs:{owner_id}"` and concatenate their `content`
     under a `## Learned preferences` header.
   - Keep the order deterministic (sort by blob `created_at` asc) so the
     prompt cache isn't invalidated by reshuffling.
   - Hard cap: if the section exceeds ~2000 tokens, log a warning and
     truncate to the newest N — but this is defensive, not expected in
     practice.

4. **System prompt** (zylch/assistant/prompts.py): append to the existing
   "SAVING / CORRECTING memory" section a sub-rule for preferences.
   Paste this verbatim as a starting point, then tune:

   ```
   **When to save a PREFERENCE (namespace="prefs:<owner_id>")**
   Save a blob in the prefs namespace ONLY when:
   - The user corrects your approach ("no, non così", "stop doing X",
     "sempre/mai X"), OR
   - The user confirms a non-obvious choice you made ("sì, bene così",
     "perfetto, continua così") — these quieter signals matter too.
   And the rule is applicable to FUTURE conversations, not just this one.

   DO NOT save as preference:
   - Facts about a contact → use the default "user:<owner_id>" namespace
   - Something already covered by CLAUDE.md / system-rules.md / USER_NOTES
   - Ephemeral task state → that belongs in the current chat, not memory
   - Information derivable from the codebase or git history

   Each preference blob MUST include a one-line **Why:** explaining the
   reason or the incident that produced it — so at edge cases you can
   judge instead of applying blindly.

   Before creating a new preference, search_local_memory for similar
   existing prefs — update the existing one instead of creating a
   near-duplicate.
   ```

5. **CLI inspection** (optional, small): `zylch -p <profile> prefs list`
   prints all `prefs:<owner>` blobs with their `blob_id` so the user can
   audit / delete via existing tooling. Skip if out of scope for first pass.

## Tests (MANDATORY before claiming done)

End-to-end via the **Electron chat** — the real product surface. No
Python-level shortcuts count as "tested" here (memory:
`feedback_test_before_speak.md`).

1. Launch zylch-desktop on the user's Mac, open a chat.
2. Say: "da ora in poi scrivi sempre ai clienti in italiano, anche se
   mi scrivono in inglese".
3. Verify: LLM calls `search_local_memory`, sees no match, calls
   `create_memory(content="...", namespace="prefs:<owner>")`.
4. Close the chat, open a new one in the same profile.
5. Say: "scrivi una mail a acme@example.com ringraziando per la call".
6. Verify: LLM drafts in Italian without being asked, because the pref
   is in the cached system block.
7. Negative test: say "elenca le tasks aperte". Verify LLM does NOT
   save anything to prefs — that's a question, not a preference.
8. Dedup test: after step 3, say again "ricordati di scrivere in
   italiano ai clienti". Verify LLM updates the existing blob instead
   of creating a second one.

## Decisions Made

- **Namespace category shorthand**: the LLM passes `namespace="prefs"`
  (or `"user"`) — a bare category, no colon. `create_memory` auto-scopes
  it to `f"{category}:{owner_id}"`. Reason: the LLM doesn't know the
  owner_id, and the plan's literal `"prefs:<owner_id>"` format was a
  template, not a string.
- **Fully-qualified namespaces still accepted**: any namespace containing
  `:` is stored verbatim (back-compat for existing callers / tests).
- **owner_id threading**: `get_personal_data_section(owner_id=None)` got
  an optional param. Callers that have an owner in scope pass it
  (`assistant/core.py` via `context["user_id"]`, `task_interactive`,
  `task_creation` worker, `rpc.tasks_solve`). `cli/chat.py` path already
  had a broken `_get_personal_data_section` import (dead code) — not
  fixed here, out of scope.
- **Ordering**: prefs sorted `created_at ASC`, so the prompt stays
  byte-stable and the cache doesn't churn.
- **Soft cap**: 8000 chars (~2000 tokens). On exceed: keep newest,
  `logger.warning`. Defensive — not expected in normal use.
- **Section placement**: `## Learned preferences` is appended AFTER
  USER NOTES / SECRET INSTRUCTIONS inside the cached system block.
  User's manual notes vs. learned prefs remain visually distinct.
- **Scope**: owner-only (not per-assistant) per the plan's default.
- **CLI `zylch prefs list`**: skipped per plan ("skip if out of scope
  for first pass"). Existing `search_local_memory` already returns prefs
  with their `blob_id`, so inspection / deletion is already reachable.

## Status

IMPLEMENTED 2026-04-21. Python side only. End-to-end Electron test
(steps 1–8 in "Tests") was NOT run by the executor — the user is on
macOS and the Electron shell is not reachable from this Linux dev
host. User needs to validate via zylch-desktop before closing the
plan (feedback_test_before_speak.md).

## Open Questions

- Should preferences be owner-scoped only, or also assistant-scoped
  (one profile runs multiple assistants)? Default: owner-scoped for now,
  revisit if needed.
- Where does the section live in the prompt relative to USER_NOTES —
  before, after, or merged? Suggestion: after, with its own header, so
  user can distinguish manual notes from learned prefs.

## Anti-goals

- Do NOT add hardcoded classification rules ("if message matches regex
  → save as pref"). The LLM decides.
- Do NOT build a separate `save_preference` tool. `create_memory` with
  a namespace argument is sufficient.
- Do NOT scope-creep into a whole "feedback dashboard". CLI list is the
  ceiling for UX in this plan.
