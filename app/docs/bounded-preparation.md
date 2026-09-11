# Preparation controls

The Prepare data view separates downloading messages (`sync.run`, no paid AI)
from analyzing one batch (`preparation.resume`). The engine trains missing
assistant guidance within the bounded run. Optional manual regeneration is
available only when preparation status is known and analysis is not paused.

The preparation panel displays pending processing steps, current/last batch
attempts and completions, failed items, retry waits and the persisted stop
reason. Memory and task analysis are separate steps; ancillary training and
maintenance calls also consume the shared allowance. The daily dollar budget
still governs every provider request. See the
[engine contract](../../engine/docs/features/bounded-preparation.md).

Pause stops admission of further work; already dispatched requests can finish.
Analyze next batch does not enable recurring analysis. Recurring updates now
require an explicit saved enable value, and the app checks bounded preparation
support before any automatic update. An older engine cannot silently fall back
to an unbounded update through these controls.

Status refreshes every five seconds, on window focus and on explicit Refresh.
Action errors remain visible through successful background refreshes. Profile
connection changes clear old account state and invalidate outstanding responses.
Unknown preparation support disables analysis and manual retraining, while sync
remains a separate operation.

Validation: `npm run typecheck`, `npm run build`, and actual React component
journeys against fake RPCs:

```sh
npm install --prefix /tmp/mrcall-preparation-ui-tests react@18.3.1 react-test-renderer@18.3.1
node app/scripts/test-preparation.mjs
```

Run the script from the repository root after installing the app's existing
TypeScript dependency. `MRCALL_UI_TEST_DEPS` can select another directory for
test-only React packages. Tests cover unsupported engines, bounded action,
persistent errors, pause during a run, and late replies after account changes.
They invoke neither customer analysis nor paid providers.
