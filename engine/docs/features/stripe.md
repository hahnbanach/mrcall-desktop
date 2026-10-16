# Private Stripe connection and reads

Scope: the native `stripe.*` RPC lifecycle and bounded private Stripe evidence.
These are preserved current-runtime capabilities in the local M10 successor;
source or synthetic installed proof does not establish live provider acceptance.
No payment mutation or automatic company-memory import is provided here.

## Connection and consent

`system.capabilities` advertises `stripe:1`. The dispatcher registers nine
methods from `rpc/stripe.py` and refuses duplicate registrations:

| Method | Contract |
|---|---|
| `stripe.status` | Safe connection/account/mode/generation metadata. |
| `stripe.test` | Probe a restricted API key and return account, capabilities and an expiring consent challenge. |
| `stripe.connect` | Consume that exact challenge with `authority_confirmed=true`, re-probe and save the encrypted connection. |
| `stripe.disconnect` | Remove the saved credential, advance generation and invalidate challenges. |
| `stripe.customers` | Bounded customer page, optional exact email filter. |
| `stripe.payments` | Bounded payment-intent page, optional customer filter. |
| `stripe.invoices` | Bounded invoice page, optional customer filter. |
| `stripe.subscriptions` | Bounded subscription page, optional customer filter. |
| `stripe.detail` | One exact supported resource and validated identifier. |

Only restricted `rk_test_` or `rk_live_` keys with the validated shape are
accepted. Test probes the account and supported resources. The challenge expires
after 600 seconds and binds the exact key digest, verified session, UID/profile,
host/company identity, connection generation and observed account/mode/capabilities.
It is single-use; changed or stale identity/result refuses connection.
The displayed company name is a bounded, capability-redacted label, not authority.

Hosted calls require the selected immutable UID/profile, matching unexpired
verified Firebase session, bound company store/key and a stable host identity
outside the profile. A pending company join or active join fence refuses. The
hosted identity file is selected by `STRIPE_HOST_ID_FILE`, falling back to the
existing `QONTO_HOST_ID_FILE`; a Qonto connection is not required.

## Storage and revocation

`stripe.connection` is a private encrypted profile file. Hosted encryption uses
the configured `ENCRYPTION_KEY`; local operation uses private `stripe.key`.
Private file/lock helpers and atomic replacement preserve the scoped lifecycle.
Secrets stay out of RPC logs/errors and public connection metadata. Disconnect
replaces saved content with a disconnected generation; it does not revoke the
upstream Stripe API key or delete historical backups.

Reads bind the same actor/session/generation before and after provider awaits.
Each read rechecks the Stripe account. Disconnect, changed credentials/account,
expired session or changed company/host refuses delivery. Authentication or
permission failures revoke the current saved generation. No operation changes
an external Stripe object.

## Bounded evidence

The transport sends GET only to `https://api.stripe.com/v1/`, fixes the API
version and refuses redirects. One 429 response may retry once after 0.2 seconds;
other errors map to safe fixed outcomes. Responses above 2 MB refuse.

List limits are 1–50, default 25, with validated `starting_after` cursors. Detail
supports customers, payment_intents, charges, invoices and subscriptions.
Resource prefixes, live/test mode, types, amounts, currencies, page bounds,
customer binding and returned IDs are validated. Only allowlisted scalar fields
and selected linked IDs are returned. Responses carry account/mode/generation,
retrieval time and explicit `bounded_page` or `single_record` coverage; a page is
not a complete financial statement or a proof that no other records exist.

Preservation acceptance uses scripted HTTP and disposable encrypted files. Live
Stripe access, actual production file compatibility, user-interface flow and
company/funding conclusions require their own evidence; none follows from RPC
discovery or a passing source suite.
