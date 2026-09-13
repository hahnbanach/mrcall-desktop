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

## Payment and model selection

Settings separates the billing provider from the model controls. MrCall credit
users see models discovered from their billing server and need no personal key.
Anthropic/OpenRouter BYOK users enter a key saved through the engine settings RPC,
so a remote engine receives its own profile `.env` update. Switching billing
preserves both keys. The UI only shows the key field for the selected BYOK provider.

The default and five job model selectors use the chosen billing catalog. Saved
values unavailable in that catalog remain visible and are never replaced silently.
When a preset controls the default, the UI names its effective model and labels
the stored custom model inactive. Choosing a default changes policy to custom;
saved job overrides remain active. Overrides live under a collapsed Advanced
section, with a visible warning whenever saved overrides take priority.
The daily spending card continues to show the currently saved effective models.
Pending model selections take effect only on Save. Disconnect/account changes
invalidate in-flight catalog responses; reload settings before selecting again.
