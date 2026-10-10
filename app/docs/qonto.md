# Qonto in Desktop

<!-- doc-scope:start -->
Scope: Desktop Settings, private source review and managed-chat interaction for
the native Qonto engine source, including source-fixture verification limits.
<!-- doc-scope:end -->

Settings contains a Qonto card for the selected local or hosted engine. Enter
the organization API login and key; the card has no other credential source,
and Test stays disabled until both fields are filled.
Test shows the legal company and accounts. Select an account subset and confirm
authority before Save connects and starts initial source sync. A provider API
key may allow writes; this integration exposes bank reads only.

Credential fields clear after Test. A short-lived request-only copy supports
Save and clears on edit, expiry, error, sign-out or engine/profile change.
Settings never reads back the saved credential. Old engines show an update
message; incomplete or stale confirmation cannot save a connection. Confirmation
uses the MrCall company label returned with the engine's tested challenge.
Company joins clear credentials, accounts, consents and previews, invalidate
pending replies and block actions during cutover. Fresh memory checks reject
stale Save requests even when the profile and engine stay unchanged.

Explicit logout invalidates finance views before the engine or Firebase reply:
credentials, tested consent, source details and publication previews clear even
when Firebase logout fails. Revoked sessions cannot start new finance actions;
late responses stay discarded after a subsequent login with the same UID.
Workspace hides until an active authenticated session resumes.

The card shows connection, selected-account count and coverage, plus explicit
manual sync and one-batch finance preparation. Preparation preserves the saved
pause and does not enable recurring work. Preview displays the exact minimal
company-use/currency fact, current and future company-key audience, possible
LLM processing and historical retention. Publication requires its confirmation.

Tasks offers a Qonto channel and Review source. Evidence comes from the bounded
`qonto.transaction` RPC; bank narratives are untrusted text. Pin, close and
reopen use existing authorized task actions. An unavailable source has no email
fallback. Delete imported data preserves user-edited private task shells and
historical published facts; disconnect separately removes the application
credential copy. Reconnecting takes a typed login and key and a new Test, as
every connection does.

Choosing Qonto starts a separately labelled empty chat. Client transcripts are
display-only; subsequent turns use the engine's exact history handle/revision.
Changing account, transport or company invalidates finance context and late replies.
Company transitions block finance chat start/send and discard delayed answers
and history bindings. Ordinary chat delivery retains its existing behavior.
Model processing can send authorized financial evidence to the selected LLM.

The native browser fixture exercises actual Settings, Tasks and preload methods
through a local bridge to real Python dispatch and disposable SQLite. It verifies
process restart, source review, task actions, a settled priced publication,
receipt replay, disconnect and deletion. Electron IPC is shimmed; Qonto HTTP,
Firebase certificates and the paid provider are local fixtures. These checks
do not establish packaged Electron/main transport, a real bank connection or
provider-UI equivalence. The [delivery plan](../../docs/execution-plans/2026-10-04-qonto-connection.md)
owns review and live acceptance state.

Run `scripts/test-qonto.mjs`, `test-qonto-credentials.mjs`,
`test-qonto-history.mjs`, `test-qonto-auth-lifecycle.mjs`, `test-qonto-browser.mjs` and
`test-qonto-native-browser.mjs` with their fixture dependencies available.
Engine behavior: [Qonto](../../engine/docs/features/qonto.md).
Shared contracts: [Qonto IPC](../../docs/qonto-ipc.md).
