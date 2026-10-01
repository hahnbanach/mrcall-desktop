# Desktop main rebase reconciliation

## Intent

Complete the interrupted rebase of local `main` onto fetched `origin/main`,
commit the conflict resolutions, and push the integrated branch. The operator
explicitly authorized resolution, commits and publication on October 1.

## Scope and constraints

- Original local tip: `88ba04f`; fetched rebase target: `19639d2`.
- The current stop is `b4e868c`, with one documentation conflict in
  `engine/docs/active-context.md`. Thirty-two commits have been replayed;
  sixteen commands follow the conflicted commit.
- Preserve both independent workstreams: mnemonic memory and production voice.
  Keep source changes from both histories; investigate any later code conflict
  before resolving it. Do not change runtime or deployment configuration.
- Preserve untracked files byte-for-byte and the existing stash. Stage only
  explicitly reviewed files; do not publish local scratch or credentials.
- Use a regular fast-forward push. If the remote advances, reconcile it before
  publication; never force-push.

## Acceptance

- Rebase metadata and unresolved index entries are absent; `main` is checked out.
- Both original histories' substantive changes survive the integration.
- Conflict markers are absent; the documentation mechanical gate and focused
  tests of the integrated voice and memory boundaries pass.
- Untracked-file hashes and the pre-existing stash remain unchanged.
- A separate final review approves the integration before publication, and
  remote `main` is verified equal to the final local commit.

## Recovery and assumptions

`recovery/main-before-rebase-20261001` preserves the original local tip.
Untracked files, hashes, current patches and rebase state are backed up outside
the repository at `/home/mal/.local/state/desktop-rebase-20261001-xqgwcfdp/`.
Existing feature behavior and previous deployment acceptance are outside this
reconciliation; local tests will not establish live service health.
