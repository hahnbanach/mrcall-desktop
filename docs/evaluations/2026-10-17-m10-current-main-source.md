# Current main integration — source evidence

The following M1 observations describe the reviewed pre-commit state. The actual
published merge and CI evidence appear in Delivery below.

## Composition

The accepted ordinary-preservation parent is ce86428d. The pending merge parent
is exact main955138f7, retaining Stripe Settings/UI and its source/tests/docs.
Eight explicit conflicts are resolved; the composed M10 dispatch and registry
remain byte-identical to the accepted engine, with one Stripe registry block.
All376 product Python modules and seven assets match wheel2514cb98 exactly.
No semantic engine change is introduced. Candidate packaging changes only the
version to0.1.57.dev1+m10.20261017.1; dependencies/entrypoints/resources match.
App version0.1.57-stripe.3 and its lockfile match upstream; dependencies do not
change. StripeCard, Stripe types, browser fixture and app Stripe contract match
main byte-for-byte. Preload/types/Settings retain existing M10 behavior and add
the upstream Stripe wiring. Main ancestry will be established by the merge commit;
MERGE_HEAD currently binds955138f7, not a completed commit or publication.

## Actual checks and failure disposition

The pre-edit M10 Stripe baseline passes48 cases in24.33s. Combined upstream/M10
Stripe tests pass61 cases in29.11s with zero failures/errors/skips. The shared
fixture retains M10's company-bound scripted native-RPC helpers and imports
upstream's disposable Qonto env; its existing cleanup contract remains. All
upstream cases and assertions are retained. Two standalone egress-policy unittest
cases pass; this avoids the known unrelated root pytest autouse-fixture issue
without skipping either policy case.

Both actual TypeScript projects pass with no emit and private build-info paths;
the model-name boundary passes. Existing app dependencies are used through an
owned ignored symlink, with matching dependency requirements and no install or
upgrade. An initial missing ignored oauthSecrets.ts causes typecheck failure;
the existing standard postinstall script copies the committed example exactly.
No actual secret or tracked-source repair is used. The failed receipt remains.

Actual Chromium executes the upstream StripeCard/auth/preload fixture, including
startup repair, cached replay, identity/memory errors, timeout/retry, pending
reconnect, key clearing and context fences. External browser requests are aborted;
provider/RPC dispatch is a fixture, not real Stripe or funding acceptance. The
first launch fails because the long private TMPDIR exceeds Unix socket limits.
The unchanged script passes with a short owned private temp directory; both
receipts remain. No paid/provider call occurs.

## Evidence and remaining gates

Private evidence is under
/home/mal/worktrees/.evidence/m10-execution-20261016/live-acceptance-20261017/current-main-integration/:
M1-source-proof.json, merge-start.json, merge-resolutions.json,
upstream-document-preservation.json, baseline/M1 Stripe command/JUnit/logs,
standalone egress logs, TypeScript/model/browser command receipts, retained
failures and approved brief/R2 plan snapshots. Upstream archive contributions and
its current-state paragraph are retained verbatim as dated quoted history;
the accepted prior archive remains an exact suffix.

Fresh M1 approval is required before metadata-only artifact work. Existing source
171/native84+84 and SDK/receipt/voice/MCP/Stripe/copied-boot evidence applies only
to exact unchanged inputs. No live handoff, full ordinary success, four-target
guard activation, paid/factual/clone/canary/rollback or main/tag/fleet acceptance
follows. Feature publication and actual nonpaid CI must precede final completion;
all inherited dependency/SDK/live-Stripe/style qualifications remain.

## Delivery

Source merge82c5c8ae38d550e77c4b6e548044505fa416e442 has accepted parent
ce86428d and exact main955138f7 as its two parents. Normal fast-forward
publication updates model-selection-m10a; main is unchanged and PR19 stays draft.
All six actual push/PR checks pass at that source head.

- [Memory write boundary (pull_request)](https://github.com/hahnbanach/mrcall-desktop/actions/runs/39023221493) — success.
- [RPC parameter and task contracts (pull_request)](https://github.com/hahnbanach/mrcall-desktop/actions/runs/39023221521) — success.
- [Mnemonic kernel journey (pull_request)](https://github.com/hahnbanach/mrcall-desktop/actions/runs/39023221467) — success.
- [Mnemonic kernel journey (push)](https://github.com/hahnbanach/mrcall-desktop/actions/runs/39023217727) — success.
- [RPC parameter and task contracts (push)](https://github.com/hahnbanach/mrcall-desktop/actions/runs/39023217670) — success.
- [Memory write boundary (push)](https://github.com/hahnbanach/mrcall-desktop/actions/runs/39023217672) — success.

Private ci-proof.json and source-publication.json retain exact head/parent and
run bindings. No paid model-table run is repeated. M1 approval preceded the
metadata-only artifact; publication and these CI results precede final closure.
