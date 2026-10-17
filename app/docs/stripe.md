# Stripe in Desktop

<!-- doc-scope:start -->
Scope: native Stripe Settings configuration and renderer/preload verification boundaries.
<!-- doc-scope:end -->

Settings includes a Stripe card for the selected local or hosted engine. Enter a
restricted `rk_test_` or `rk_live_` account key and Test. Review the provider account,
environment, available read capabilities and MrCall company, then Save to connect.
Enter and Test a new key to replace a connection. Disconnect removes
the engine's saved copy; provider-side revocation remains a separate Stripe action.

The card reads no saved secret. Input clears when testing starts; the request-only
copy survives only for the expiring tested Save. Edits, expiry, request errors,
authentication invalidation, transport changes, company transitions and changed
connection generations invalidate the tested state. Same-UID session invalidation
discards delayed responses. Older engines display an explicit update message.
All calls use the existing authenticated preload RPC bridge.

Read-only operator lookups may disclose selected evidence to the invoking agent,
its configured model and transcript. This connection creates no Stripe chat,
finance tasks or automatic shared-memory publication. Disconnect cannot retract
previously disclosed agent output.

`node scripts/test-stripe-browser.mjs` exercises the real StripeCard and preload
bridge in Chromium with fixture IPC/provider dispatch. Configure
`MRCALL_PLAYWRIGHT_MODULE` and `MRCALL_BROWSER_BINARY` for existing local browser
dependencies. The fixture verifies Test/Save/disconnect, key clearing,
expiry, generation, company, transport and session invalidation, delayed replies
and old-engine behavior. It does not establish packaged Electron transport,
authenticated hosted operation or a real Stripe account connection.
