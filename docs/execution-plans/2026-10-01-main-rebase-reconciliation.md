---
status: active
---

# Desktop main rebase reconciliation

Brief: [intent and acceptance](../briefs/2026-10-01-main-rebase-reconciliation.md).
Brief gate: fresh reviewer APPROVED on October 1.

## M1 — Complete the interrupted rebase

Owner: lead session. Preserve the existing recovery branch and external backup.
Resolve the current documentation conflict by keeping both independent tasks
in `Next`, with distinct numbering. Continue with the existing commit messages.
Inspect each further stop; preserve independent additions and avoid whole-file
ours/theirs substitutions. Investigate any code overlap before resolution.
Verify no rebase metadata, unresolved index entries or conflict markers remain;
compare original-local and remote changes against the integrated result.
A fresh milestone reviewer must approve before M2.

M1 result: rebase completed at `33e157e`, with 49 commits ahead of the fetched
target. Conflicts were resolved at `b4e868c`, `f8c1301`, `5ff9fe1` and `d85c866`.
The wizard retains the remote's tested environment-preservation helper; project
memory documents both the local phone reader and the remote's join writer.
Voice implementation/tests and instruction implementation match `88ba04f`
exactly; the setup wizard matches `19639d2` exactly. Nine original untracked-file
hashes and the original stash match; no rebase or unresolved index remains.
Range comparison and integration diffs are retained in the external backup.
M1 gate: fresh reviewer APPROVED; independent checks confirm tree preservation,
combined CLI/dependency changes and all conflict resolutions.

## M2 — Verify and reconcile documentation

Owner: lead session. Run the focused voice tests plus mnemonic join/maintenance
and operator-instruction tests appropriate to the integrated histories. Repair
only documentation mechanical violations that prevent the integration gate;
the initial check reports a broken rollout link, a three-line index excess,
an invalid plan status and baseline hashes rewritten by rebase.
Align living snapshots and next actions with the actual integrated history,
without declaring untested deployments. Advance rewritten baselines to an
existing reconciled source commit and record actual verification.
Compare all original untracked-file hashes and the existing stash hash
`2868bf63bfc58c62aea313cc6d9d7d1657f2030d`. Commit only reviewed tracked changes
and these two reconciliation trace files. A fresh milestone review must approve.

M2 evidence:

- `engine/venv/bin/python -m pytest -q --disable-warnings` on voice plus the
  mnemonic join guards, cutover, crashes and maintenance suites: 397 passed,
  1 skipped (kernel voice journey requires its external interpreter),
  2734 warnings, 157.02 seconds.
- Wizard environment preservation and instruction RPC suites: 9 passed,
  13 warnings, 1.13 seconds.
- Documentation gate: MECHANICAL GATE CLEAN; `git diff --check` passes for
  reconciliation edits and for integrated files except the original stored
  patch artifacts, which are retained byte-for-byte.
- Original archive and workspace hashes match 9/9; the original stash remains
  unchanged. All 49 local-only and 156 remote-only modified paths survived M1
  exactly. M2 intentionally changes the documented index, rollout reference
  and living snapshots only; no runtime code changes follow M1.
- M9 is present in the integrated source; its deployment remains unverified.
  The referenced external rollout document is absent, so the guide points to
  the existing harness design plan and explicitly leaves live rollout gated.

M2 gate: fresh reviewer APPROVED. The reviewer independently verified the
documentation gate, ancestry, original archive/workspace hashes, stash and
absence of rebase metadata, and accepted the recorded focused test results.

## Final review and publication

A separate fresh final reviewer checks both milestone verdicts, integration
evidence, documentation gate, preservation and the final diff. Record the
completed plan and final approval, then publish by regular push to `origin/main`.
If fetched `origin/main` has advanced, integrate and review the additional
changes before pushing. Verify remote `main` equals local `HEAD`; leave all
original untracked files and stash intact.

## Risk and recovery

Subsequent replayed commits may produce additional conflicts or resurrect stale
documentation. Scope checks to the two integrated histories and preserve
production gates. The recovery branch preserves the original local history;
the external archive preserves untracked files and the interrupted state.
Do not abort or reset in a way that overwrites untracked work. A failed test or
review is repaired before publication; no force-push is authorized or needed.
