---
status: approved
date: 2026-10-08
---

# Remove the Qonto engine bootstrap credential source — brief

<!-- doc-scope:start -->
Scope: product and contract brief for removing the "engine bootstrap"
credential source from the native Qonto connection: the Desktop card, the
engine, their shared RPC contract, tests and documentation. It changes no bank
connection, hosted profile, profile file or release.
<!-- doc-scope:end -->

## Intent

Qonto credentials reach the engine in one way: the user types the organization
API login and key in the Settings card and presses Test. The second source,
credentials looked up in the engine profile's `.env`, is removed from the
card, the engine and the contract.

The CTO decided this on 2026-10-08. The `.env` lines were test scaffolding,
nobody connects a bank account by editing a profile `.env`, and the approved
[Qonto brief](2026-10-04-qonto-connection.md) specifies typed credentials
only. The bootstrap source exists because the
[Qonto plan](../execution-plans/2026-10-04-qonto-connection.md) added a
"Credential bootstrap contract" around lines already present in one profile.

## Existing boundary

Verified on `main` at `434f325`.

- **Card.** `app/src/renderer/src/components/QontoCard.tsx` shows
  "Engine bootstrap: <status>" when `qonto.status` carries `bootstrap`, and
  always shows a "Use engine bootstrap" checkbox. Ticked, it hides the login
  and key fields and sends `credential_source: "bootstrap"` to Test and Save.
  Unticked, it sends `credential_source: "input"` with `login` and `api_key`.
- **Engine.** `engine/zylch/qonto/bootstrap.py` looks up `QONTO_API_LOGIN` and
  `QONTO_API_KEY` in the active profile `.env`, or in the file named by
  `QONTO_BOOTSTRAP_ENV_FILE` on a local engine that is not serving. It reads
  and format-checks them on every `qonto.status`, `qonto.disconnect` and
  `qonto.delete_imported_data` to report availability. It sends them to Qonto
  only when Test or Save asks for the bootstrap source. Disconnect and
  imported-data deletion also report `bootstrap_retained: true`. The same
  module holds the credential value type and the format validation that the
  provider, secrets and challenge modules import.
- **Process environment.** Profile activation loads the whole profile `.env`
  into the engine process environment, independently of the bootstrap module.
- **Contract.** `qonto.test` and `qonto.connect` declare
  `credential_source="input"` as an optional parameter, and the dispatcher
  refuses any undeclared parameter. `docs/qonto-ipc.md`, the preload types
  and the generated `docs/rpc-contract-inventory.json` describe both sources.
- **Guards.** Every `QONTO_*` profile key is refused by the Settings and
  onboarding allow-lists, `settings.get_secret` and provisioning payloads
  (`engine/zylch/services/credential_policy.py`, `app/src/main/profileFS.ts`,
  `app/src/main/provisionClient.ts`,
  `app/src/renderer/src/lib/profileSchema.ts`); `rpc/dispatch.py` redacts the
  credential arguments in request-parameter logs.
- **Field state.** Desktop `v0.1.56` is published and has no auto-update. It
  renders the checkbox unconditionally and the availability line only when
  status carries `bootstrap`. Hosted engines run pinned releases that include
  the bootstrap source. A saved connection uses the engine's own encrypted
  credential copy, never the `.env` lines. Profile `.env` files and a
  developer's ignored `.env.qonto` can still contain `QONTO_API_LOGIN` and
  `QONTO_API_KEY`.

## What changes

1. **Card.** No availability line, no checkbox and no bootstrap wording in any
   state. Test needs both typed fields. The messages that mention bootstrap
   (`login_required`, the disconnect notice, the footer sentence) describe
   typed credentials only.
2. **Engine.** No engine code looks up `QONTO_API_LOGIN`, `QONTO_API_KEY` or
   `QONTO_BOOTSTRAP_ENV_FILE` by name, and no Qonto request carries a
   credential that did not arrive as an RPC argument or come from the
   encrypted stored copy. The bootstrap module, the developer override and
   their two error outcomes are gone; the credential value type and format
   validation stay, unchanged in behavior, in a module named for what they
   are. `qonto.status`, `qonto.disconnect` and `qonto.delete_imported_data`
   results carry neither `bootstrap` nor `bootstrap_retained`.
3. **Contract.** `docs/qonto-ipc.md`, the preload and renderer types and the
   regenerated inventory describe one credential source.
4. **Documentation and examples.** The engine and app Qonto pages state the
   single source; `engine/docs/examples/.env.qonto.example` is removed; the
   Qonto plan's contract section states the present contract.

## Constraints

- **Published Desktop keeps working against a newer engine.** `v0.1.56`
  sends `credential_source: "input"` with typed credentials; the engine keeps
  accepting that request unchanged, with the parameter still declared and
  optional. A request with `credential_source: "bootstrap"` is refused where
  the credential source is parsed, after the unchanged authority checks, with
  no credential lookup outside the request and before any provider request.
  The refusal is the existing safe outcome `credentials_required`, which that
  card renders as "Enter your Qonto organization API login and key, then
  Test." Any other value keeps the existing `invalid_credentials` refusal.
- **A newer Desktop keeps working against an older engine.** The card keeps
  sending `credential_source: "input"` with `login` and `api_key`, identical
  to what `v0.1.56` sends and accepted by every engine release since the
  Qonto integration. It ignores `bootstrap` fields in results and never sends
  the bootstrap source.
- **The `QONTO_*` guards stay exactly as they are.** Leftover
  `QONTO_API_LOGIN` and `QONTO_API_KEY` lines exist in the field, so they must
  remain unreadable through Settings, `settings.get_secret`,
  request-parameter logs and provisioning.
- **`.env.qonto` stays ignored** by the generic `.env.*` rules, because such
  a file can hold real credentials in a worktree. The two negation lines that
  track the removed example are removed with it.
- **No stored data changes and no migration.** Saved connections keep
  working. The provider adapter, sync, reads, managed chat, tasks and
  publication are untouched.
- **Typed-credential validation is unchanged**, including the combined
  `login:key` form and `login_required` for a key without a login.
- **No live system is touched.** No hosted profile, `.env` file, unit, egress
  policy, release tag or installer changes. The engine never erases or
  rewrites a profile `.env`.

## Acceptance

- **Card, through the existing fixture journeys.** No bootstrap text or
  checkbox in any state, including when a fixture engine still returns
  `bootstrap` fields. Typed test, edit, retest, save, restart, sync,
  disconnect and delete journeys pass. Test stays disabled until both fields
  are filled. The host-switch and UID-switch late-reply journeys, which today
  press Test through the bootstrap checkbox, stay and run with typed
  credentials. The fixture call log shows that the credential fields of Test
  and Save are exactly `login`, `api_key` and `credential_source: "input"`.
- **Engine, through real dispatch.** Typed-credential Test and Save pass with
  the parameter omitted and with `credential_source: "input"`. With valid
  `QONTO_API_LOGIN` and `QONTO_API_KEY` present in the profile `.env` and
  `QONTO_BOOTSTRAP_ENV_FILE` set, `credential_source: "bootstrap"` is refused
  with `credentials_required` on both methods and the provider fixture
  receives no request. Any other `credential_source` value is refused with
  `invalid_credentials`. `qonto.status`, `qonto.disconnect` and
  `qonto.delete_imported_data` results contain no bootstrap key.
- **Saved connections.** A connection saved by the engine at the base commit
  of this work in a disposable engine home still reports connected, syncs
  and reads when the changed engine opens the same engine home and profile
  directory with the same signed-in UID and company memory.
- **No lookup remains.** No file under `engine/zylch` or `app/src` contains
  `QONTO_API_LOGIN`, `QONTO_API_KEY` or `QONTO_BOOTSTRAP_ENV_FILE`. Elsewhere
  the names remain only in the guard tests, the refusal regression test,
  `docs/active-context-archive.md`, the Qonto plan and this work trace.
- **Guards.** The existing tests that refuse `QONTO_*` keys in allow-lists,
  `settings.get_secret` and provisioning pass unchanged.
- **Contract.** `docs/qonto-ipc.md` matches the code. `npm run inventory:rpc`,
  run with `CS_KERNEL_ROOT` at the kernel revision that reproduces the base
  inventory byte for byte (cs-kernel `eb6dc1a` at `434f325`), changes nothing
  under `kernel_calls` and leaves a clean `git diff` once its output is
  committed. `npm run test:rpc-contracts`, run as the CI workflow runs it,
  and the engine contract-boundary tests pass, with any failure that predates
  this work reproduced on the base commit.
- **Documentation.** The mechanical gate is clean and the semantic check of
  the affected documents passes.

## Consequences to accept

- **Every Test takes typed credentials.** That covers a first connection, a
  reconnection after a disconnect or a provider authentication failure, a
  change of the selected accounts, and rebinding after a company join or a
  host change. The credentials are typed in the Desktop card connected to
  that engine, or carried by an authenticated RPC call.
- **Leftover lines stay loaded.** On a profile that keeps the two lines, each
  engine start still loads both values into its process environment, with
  nothing using them. Deleting the lines is the remedy and is operator work.
- **An installed `v0.1.56` keeps its bootstrap wording** until the next
  Desktop release. Against a newer engine with the box ticked, the refusal
  asks for fields that stay hidden until the box is unticked.
- **Hosted update order.** The installed-Desktop Qonto journey is an open
  acceptance item of the Qonto plan, and it becomes the reconnection path. A
  hosted engine that holds a Qonto connection, today the support profile
  only, receives this change only after one typed connection from an
  installed Desktop has passed.
- No script, runbook or operator kernel code uses the bootstrap source.

## Out of scope

- Deleting `QONTO_API_LOGIN` and `QONTO_API_KEY` lines from a profile `.env`
  or from a developer's `.env.qonto`. Those are operator-owned files.
- A hosted engine update and a new Desktop release. The change reaches users
  with the next release and the next hosted update.
- Any Qonto behavior other than the credential source, and Qonto-side key
  rotation.

## Decisions for the plan

1. The module that holds the credential value type and validation after the
   bootstrap module is deleted.
2. How the active Qonto plan's "Credential bootstrap contract" section is
   reconciled without rewriting its work trace.
3. The split into milestones, given that engine results and card types change
   together.
4. How the saved-connection check obtains a profile written by the base
   engine.
