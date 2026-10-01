# Astra re-review: Mario instruction-write permission denial

P1 repair deployed and re-reviewed on 2026-10-01.

## Done
- Verdict: APPROVED
- Changed: none; read-only re-review of the original Astra P1, with this report saved outside the repository.
- Checked surface: complete local permission file and apply/verify/snapshot helpers, approved M7 brief/plan, installed launcher behavior, effective project location, recorded invalid-settings probe, current preservation snapshot and actual Mario preview. The original instruction-write permission gap is closed for all six supported spellings of both raw RPC and compiler commands.
- Verified: independently ran `/home/mal/.local/bin/claude doctor` from Mario’s clone; exit 0. Twelve deny rules, 0600 mode and SHA256 dc0ee279f443831e8b270b5e8daa1f71aaf432311f8c7afa4d5fb32f187b705f match the approved change. `git rev-parse --show-toplevel` returns the Mario clone; `git check-ignore -v .claude/settings.local.json` confirms the existing global exclusion.
- Verified: independently ran `sudo -n python /tmp/mrcall-ai-kit/mario-p1-20261001/snapshot.py`, captured its output without printing private text, and compared parsed JSON to both before/after snapshots: all equal. Actual preview retains exactly Mario mailbox and procedures; six revision-1 documents, services/profile/template/kernel fingerprints, other production state, pauses and cron remain unchanged.
- Relied on: reviewed real-wrapper stub probe and output proving Mario cwd, default settings sources, retained old denials, 24 denied standard forms and 12 unaffected reader forms. Rechecked recorded invalid-local-JSON diagnostic. No broad suite or model invocation was repeated.
- Permission basis: project-local settings load for this project and permission lists merge ([official settings documentation](https://code.claude.com/docs/en/settings)); matching deny rules take precedence over broad allows, with the documented trailing-prefix syntax ([official permissions documentation](https://code.claude.com/docs/en/permissions)). These rules also deny interactive instruction authoring in Mario’s clone, as explicitly accepted by M7; owning 124 authoring is unaffected.
- Unverified: no actual paid/headless model invocation, attempted live instruction write or generated draft; the probe establishes the documented command-enumeration boundary, not an OS sandbox. No scheduled Mario execution is certified; no schedule was added. Separate final integration/documentation review remains the lead’s gate. Earlier handset, latency and rollback-execution limits remain unchanged.
- Evidence: /tmp/mrcall-ai-kit/mario-p1-20261001/astra-rereview.md; verification.json, preservation.json, before.json and after.json in the same directory. Original Astra report remains historical.
