# Harness Backlog — Cross-cutting

Cross-cutting enforcement gaps that span engine ↔ app. Engine-only and
app-only gaps live in `engine/docs/harness-backlog.md` and (when it
materialises) `app/docs/harness-backlog.md`.

## Open

- [ ] **No contract test for IPC method/payload changes.**
  Discovered: 2026-05-02
  Impact: a server-side method rename or payload shape change must be
  manually mirrored in `app/src/preload/index.ts` + `app/src/renderer/src/types.ts`.
  TypeScript catches signature mismatches inside the renderer (which is
  why `tasks.complete(task_id, note?)` was caught at typecheck this
  session) — but it does NOT catch cases where the engine and the
  preload disagree, because the preload is the only declaration of the
  surface seen by the typechecker. There is no end-to-end check that
  the JSON the renderer sends matches what the server accepts.
  Recommendation: a small Python+TS shared schema (e.g. JSON Schema
  generated from one side and consumed by the other), or at minimum a
  pytest that spins up the sidecar in-process and round-trips a
  representative payload per method.

- [ ] **No CI for `engine/make lint` and `app/npm run typecheck`.**
  Discovered: 2026-05-02
  Impact: lint/typecheck violations slip through until the next
  session's manual run. Tonight a Black-reformat issue and a TS
  arity error were both caught only because /doc-startsession ran
  the smoke check.
  Recommendation: GitHub Actions workflow that runs both on PRs.

- [ ] **No CI for `pytest` on engine.**
  Discovered: 2026-05-02
  Impact: 3 tests in `tests/workers/test_task_worker_bugs.py` were
  silently broken on HEAD before this session — `git stash` confirmed
  pre-existing failure. Without CI, a "14/14 green" claim in
  active-context.md can age into a lie.
  Recommendation: GitHub Actions step `cd engine && venv/bin/python
  -m pytest tests/workers tests/services -q`. The `tests/` directory
  as a whole is stale (separate engine harness gap), but the two
  curated dirs above are the live test set.

## Resolved

(none yet)
