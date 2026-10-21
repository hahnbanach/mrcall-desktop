# M10 company-memory integrated candidate

> Historical acceptance record, qualified on 2026-10-16. The initial package
> captures are frozen bases, not the complete effective V4/V8 runtimes. Both
> earlier wheels omit runtime model JSON and cannot authorize an installation.
> Current preservation, replacement artifact and rollout gates belong to the
> [effective-runtime integration](../execution-plans/2026-10-16-m10-current-runtime-integration.md).
> Original evidence and approvals remain retained; dated statements below describe
> that earlier candidate, not current deployment readiness.

Scope: local M3 evidence and the remaining deployment gates of the
[readiness plan](../execution-plans/2026-10-15-m10-memory-production-readiness.md).
The original M10 conditional approval and measurements remain historical evidence.
This candidate adds the separately approved runtime-preservation and admission
changes. It has not been deployed, committed or pushed.

## Candidate identity and local evidence

Worktree: `/home/mal/worktrees/mrcall-desktop-m10-memory-readiness`, branch
`prepare/m10-memory-readiness-20261015`, base HEAD
`5877822203ccb3e1d53951ead331574bff38fbb6`. HEAD does not contain the dirty
candidate. Private receipts live under
`/tmp/mrcall-ai-kit/m10-memory-readiness-20261015/`.

- [M1 preservation](2026-10-15-m10-runtime-preservation.md) has independent
  APPROVED review. It freezes 348 production and 334 Mario source modules,
  dispositions every installed difference, and retains the optional MCP,
  exact-draft, origin, assignment, email-only and Qonto boundaries. Its isolated
  sensitive suite passes 416 tests; the additional 144 and 26-test receipts
  overlap and must not be summed as unique coverage.
- A later whole-registry check found `sync.run` had no parameter declaration
  in the restored wrapper. The M1 repair declares its actual optional
  `days_back`/`scope` parameters and preserves cancellation behavior. Its
  26 registry plus ten email-only cases pass (**36 passed**); unknown keys
  now refuse through real dispatch. Earlier functional receipts are retained,
  not described as reruns after this declaration repair.
- [M2 admission](2026-10-15-m10-admission.md) has independent APPROVED rereview.
  The original combined receipt is 359 passed/one skipped. The formerly skipped
  cross-repository test now passes all four cases against an immutable
  `89deceb` server archive and disposable PostgreSQL, with external connections
  blocked. The original failure and fixture repair remain in the evidence.
- `m3-free-e2e/matrix.json` and `run.log`: the unchanged M10 free harness exits
  zero on this combined candidate: **52 cells, 832 role resolutions, zero
  mismatches, failed checks or crashes**. It exercises real profile activation,
  distribution and resolution against downloaded, blocked/build, cached and
  simulated successor tables. Every cell has a zero daily budget. No paid leg
  was requested; no scratch credential file remains.
- `m3-local-rpc/check.sh` and its final test log: **52 passed, 31 warnings in
  28.73s**, including nine new real RPC-to-tool-loop cases plus existing
  read-only, prompt/cutoff, turn-prefix and offload checks. Actual direct
  Anthropic SDK, OpenRouter Messages and pinned K3 Chat adapters use scripted
  HTTP responses with external sockets/DNS blocked. Four individually bounded
  tool results exceed 200 KB combined and remain byte-identical through the
  next request, below the assistant prompt limit. Holds cover evidence and
  settle exactly. Hostile retrieved text leads to scripted mutation attempts;
  real policy refuses them before approval/execution and complete protected
  profile/company snapshots remain unchanged. Empty results, retrieval errors
  and cutoff followed by exact narrowing stay distinguishable. These are
  path/accounting checks, not factual model-quality results.

The revised M1 `r2/wheels/` scratch wheel is `zylch-0.1.52-py3-none-any.whl`, SHA256
`c4b208fb408fb65f92f889c0caeb1670ab39e5bb0342e2a678de7647adafcc71`.
Its installed module paths match candidate bytes. This is a locally built
artifact, not a published Desktop release or a fresh production installation.
`m3-source-identity/manifest.json` binds the source/resources/tests and packaging
files, including untracked additions, to SHA256; `source.diff` retains the
tracked binary diff. Documentation is independently bound by completion
snapshots. The new RPC test SHA256 is
`b03ecec670f9a4686b41136881cff2f5b5c45a1055a2aed6c54169fcbd82c3e2`.
Whole-tree lint remains a pre-existing failure: 65 files would be reformatted
(71 at baseline); Ruff retains four old unused imports in the untouched
`task_assignment_draft_policy.py` (five diagnostics at baseline). Touched-file
lint is required separately; no whole-tree cleanup is included.

## Saved profiles and candidate role forecast

`profile-settings-whitelist.json`, `preparation-state-readonly.json` and
`profile-resolution-forecast.json` are read-only receipts from the two actual
profiles. Only settings names/values relevant to policy, credential presence,
hashes and resolved roles are exported. Credential values stay in the source
process. File hashes match before/after each read; no profile is activated.

| Profile | Saved policy | Candidate behavior |
|---|---|---|
| Production | OpenRouter, custom K3, six explicit K3 role overrides, USD20/day | All sixteen roles retain K3; pinned Chat transport; no role pauses. |
| Mario | Anthropic, economy, no role overrides, USD15/day | MNEMONIC, MEMORY_EXTRACT and MEMORY_MERGE use `claude-sonnet-5`; twelve other roles use `claude-sonnet-5-5`; NARRATION pauses. CHAT uses direct `claude-sonnet-5-5`. |

Both saved configurations enable automatic update every five minutes, with
batch size 25; raw persisted preparation rows are unpaused and not running at
the read. This is not authority to start preparation. Preserve these settings
and independently control any authorized canary's workload. No model/preset,
budget, pause or company membership was changed. Mario's current USD15 budget
supersedes the older USD5 note for this profile only.

Both profiles currently have no model-table cache. Candidate build and frozen
published layers resolve the same models. A cached-layer simulation also agrees;
the separate free harness establishes actual download/cache control flow.
The forecast fingerprints include actual saved values and candidate resolutions;
they are not measurements of the old daemon's in-memory client fingerprint.
Rates and per-role override/table provenance are in the private JSON. K3 holds
use its pinned endpoint ceilings; direct calls use snapshot list prices. Rates
alone do not predict workload spending.

Frozen data branch: `4bbbdf89cb2af76a6f57b509165bf9225c24f84b`.
Table file SHA256 `f7ae36f0630b1f5998a7b20023afb7209e5100f3651dbf43e5911d3e99dd02a8`;
snapshot SHA256 `59515434dab36b68a4647cad0d993e9e74ea2038a65b2dfced6c7a473ce3df01`.
Without a republish, the build-age gate expires at 2026-10-26T17:43:41Z.

## Incident acceptance inputs

`incident-cases.json` binds five questions to seven independently read source
inputs, their dates, authority and SHA256. Sensitive originals remain outside
the repository. Reads used the declared company mailboxes, read-only SQL,
`cs drive cat` and `cs project show/history`; no excluded personal assistant
memory or memory-write route was used.

| Case | Verified input and required distinction | Real-answer status |
|---|---|---|
| Production process | Ivan's original 4 October email: cold extraction, two filtration stages and gentle pasteurisation of filled cans; no invented treatment figures. | Pending on both profiles. |
| Filing date | Original receipt 25 July 2025 conflicts with the Drive summary's 24 July. Preserve the conflict and prefer the receipt for its filing date. | Pending on both profiles. |
| Grant and claim scope | Summary claims an Italian grant; the 14 October adviser email discusses an international search opinion and distinguishes claims 1–20 from 21–22. Neither a receipt nor this opinion establishes grant. Missing grant evidence does not prove no grant exists. | Pending on both profiles. |
| Certification | The 14 September original says the company and filler lack kosher certificates; ingredient certification in another thread has a different scope. Do not project a dated statement into a complete current audit. | Pending on both profiles. |
| Current offer | Pricing status revision 29, 14 October, restricts purchased-extract products to tests; revision 21, 5 October, costs those products. Internal proposals do not authorize customer offers. | Pending on both profiles. |

The exact 5 October business-plan reference in the original incident was not
independently rebound. The temporal commercial case instead uses two verified
revisions of the same project. The Drive company summary itself contains the
grant/date claims: these findings do not attribute every error to generation.
This selective corpus does not certify stored-memory completeness or truth.
All five cases require repeated authenticated ordinary `cs ask` responses on
the actual selected transports, compared against these originals. A precise
refusal remains a failed ordinary read, even when its diagnostics are useful.

## Deployment prerequisites verified read-only

`deployment-prerequisites.json` records exact read commands/results and limits.
GitHub lacks the `OPENROUTER_API_KEY` repository secret; `model-table` has no
active branch protection/rules. The only recorded model-resolution CI runs are
failures, with no successful proof run on the intended source. The local
checkout has no broken `remote.origin.pushurl` override to remove.

Billing `origin/main` and `origin/dev` contain `89deceb`; production still runs
`registry.gitlab.com/hahnbanach/mrcall-agent:prod-37f330d0`. Read-only Kubernetes
inspection binds its ready pod to digest
`sha256:e003f252bff70ba636e40b4caf132c56bf921e70f52643113f59d83de34a2079`.
The target is context
`starchat-production-cluster-1eccbf09-bd86-4d09-85c7-d569b2f71310`, namespace
`starchat-production`, deployment/container `mrcall-agent`. No rollout ran.

`89deceb` includes both generation-ID and recovery fixes, but retains the
OpenRouter/K3 byte-context gate and independently builds the upstream wire.
Credits compatibility therefore also needs equivalent admission and explicit
compression disabling on the server. Existing `89deceb` promotion alone cannot
establish successful large credits reads. The old unpushed hotfix branch is
absent locally. Original 17 stuck paid-check rows belonged to a disposable
database that was deleted; actual production liabilities need their own
read-only inventory and evidence-based reconciliation, never a blanket reset.

## Staged installation and rollback boundary

`unit-identity-readonly.json` binds the existing unit fragments/drop-ins to
hashes without exporting secret environment values. `deployment-proposal/`
contains two proposed new drop-ins and `proposal.json` with exact switch, health
and removal/restart rollback command strings. Their proposed separate release is
`/home/mrcalld/releases/m10-memory-readiness-c4b208fb408f`; it does not exist.
No proposed file was installed and no command string executed. The installed
tenant helper rejects the existing production late override and its interpreter
declaration differs from the final live override. Generic reconciliation is
therefore outside this proposal; all existing drop-ins remain intact.

The lead owns execution preparation and acceptance. These steps are a concrete
ordering constraint, not authorization to perform them:

1. Finish the reviewed source identity, the missing server admission/compression
   candidate, and its protocol/recovery checks. Repair repository secret and
   protected data publication under scoped authority; run CI with its paid and
   publishing effects bounded, then remove the temporary push trigger.
2. Bind an immutable server image to the reviewed server commit and fresh table,
   verify its `raw.githubusercontent.com` egress and test protocol/receipt paths.
   The observed old image digest above is the server rollback target. Use the
   repository's production pipeline; do not substitute a floating tag or deploy
   only the engine while its credits contract is incompatible.
3. Build a separate engine release directory from the retained wheel and source
   manifest. Preserve the exact `cs.operator_read` dependency contract from M1;
   distribution version 0.51.0 alone is insufficient. Install dependencies only
   into that new release, then import/check all modules and both CLI listeners.
4. Before opening copied stores with the candidate, rehearse its additive
   schema/enrollment changes on protected copies. Document the old-build read
   path and compatible reversal; do not downgrade migrated stores blindly.
   No live store copy/migration or schema reversal has been executed here.
5. For production, retain user `mc-18f855d535e9`, profile
   `Gn9IcuWzYyY7DBMHkVUGB7bIiTp2`, its Unix socket and existing voice/operator
   config paths. Old interpreter/source is
   `/home/mrcalld/releases/operator-context-readonly-1aa6464a3705/venv/`.
   Preserve both `--voice-config` and `--operator-config`; a generic overlay
   replacement would omit installed behavior.
6. For Mario, retain user `mc-b75843f3770f`, profile
   `C06xHKoRcfdz94FaLPKuJuo0xVo1`, its ordinary Unix socket and no optional
   voice/MCP listener. Old launcher is
   `/home/mrcalld/mrcall-desktop/engine/venv/bin/zylch`; actual old source is
   `/home/mrcalld/releases/operator-deadline-r8-C06xHKoRcfdz94FaLPKuJuo0xVo1-d160ab7af25a/engine`
   through PYTHONPATH. Reverting the launcher alone would not restore source.
7. Retain both exact unit/drop-in configurations before any switch. Only after
   scoped authorization switch the selected units to the new immutable release,
   keeping other engines untouched. Recheck process source, capabilities,
   auth/read-only boundaries, all five real-answer cases, ledger/budget controls
   and required two-clone operational acceptance. Stop/revert on failed reads,
   identity mismatch, boundary regression or uncontrolled workload/cost. Restore
   both old launch configuration and old source binding; schema compatibility
   remains a prerequisite, not an assumed rollback guarantee.

Acceptance of the observed NARRATION pause and the consequences of retaining
custom K3 overrides are explicit rollout decisions; source acceptance does not
authorize changing either profile.

Missing direct-Anthropic/Firebase credentials, bounded paid checks, actual
ordinary-read quality, two-clone operations, migration rehearsal and authorized
canary remain owned deployment gates. The original M10 trial merge is historical; a merge of these dirty candidate
bytes with then-current main still needs its own exact integration check.
No new provider spending, draft/send,
service change, merge, push or deployment follows from local source acceptance.
