# Stripe account connection

<!-- doc-scope:start -->
Scope: engine-owned Stripe lifecycle, fixed EUR Payment Links, private credentials, RPC evidence
and the limits of local acceptance. Desktop configuration uses the same RPCs.
<!-- doc-scope:end -->

The authenticated `stripe` RPC namespace connects one restricted test or live
account key per verified profile. `system.capabilities.stripe = 1` advertises it.
A Qonto account connection is unnecessary. Immutable Firebase UID, selected
profile/database, private installation identity and current company memory must
agree. Missing identity, expired sessions, company joins and unsafe private files
fail closed. Hosted identity uses `STRIPE_HOST_ID_FILE` outside the transferable
profile, with the existing `QONTO_HOST_ID_FILE` accepted as an installation-only
fallback. A hosted service needs a persistent service-owned private directory
(mode 0700); the engine creates the installation file privately (mode 0600).
The company binding has a separate Stripe namespace.

`stripe.test(api_key)` probes `/v1/account`, customers, payment intents, charges,
invoices and subscriptions. All six endpoints must be readable. A restricted key
needs account identity and read access to every named resource; successful probes
establish available reads, not the absence of other permissions on the key.
Restricted-key permission labels and real-account acceptance still require a
configured provider account. Unrestricted secret, publishable and organization
keys are rejected. Test does not persist credentials.

Test returns `account: {id,name}`, `mode`, resource `capabilities`, `company_name`,
`challenge_id` and numeric Unix-seconds `expires_at`. Save calls
`stripe.connect(api_key, challenge_id, authority_confirmed=true)`. It consumes the
10-minute challenge bound to the exact key digest, account, mode, generation,
Firebase session instance, profile, installation and company, then re-probes.
Status returns safe metadata; disconnect erases the saved key and advances the
generation. Local state is private encrypted profile configuration in
`stripe.connection`, with its separate private Fernet key `stripe.key`; hosted
state uses the injected `ENCRYPTION_KEY`. No credential appears in settings or
read responses. Private atomic replacement and process locks serialize state.
An unreadable envelope fails closed. Disconnect does not revoke Stripe's key.

The read adapter sends only GET requests to `https://api.stripe.com`, with redirects
disabled, a 15-second timeout, one bounded 429 retry and the pinned
`Stripe-Version: 2026-02-25.clover`. This supported version was checked against
[Stripe's versioning reference](https://docs.stripe.com/api/versioning?lang=dotnet).
Hosted tenant egress additionally needs the explicit `api.stripe.com` TCP 443
endpoint. Connection RPCs do not alter firewall policy; hosted deployment must
permit that endpoint before testing.

`stripe.customers`, `payments`, `invoices` and `subscriptions` return one bounded
page (`limit` 1–50, optional `starting_after`). Customers accept exact `email`;
the other lists accept `customer`. Subscriptions request `status=all` so canceled
records are included. Payments lists payment intents; `latest_charge` connects
related charge evidence. `stripe.detail(resource,id)` accepts only customers,
payment_intents, charges, invoices or subscriptions. No generic URL, connected
account or owner override exists. Every read rechecks provider account identity;
results and delayed responses are fenced against session and connection changes.
Rejected authentication or permissions revoke the stored connection.

Results carry account ID, mode, generation, UTC retrieval time, bounded coverage,
minimal scalar data and list cursors. Money stays integer Stripe minor units with
its original currency; no decimal conversion or cross-currency sum is performed.
Payment intents and charges must not be counted twice. Resource status meanings
remain distinct. Provider metadata, descriptions, addresses and payment secrets
are excluded. Customer name/email may repeat: callers must disambiguate returned
IDs. Failures return constant safe errors rather than empty-success evidence.

These explicit RPC/CLI reads do not create model calls, finance history, imports,
tasks, mail or shared memory. Invoking the kernel skill can expose returned
financial evidence to that agent's selected model and transcript; it has no
Desktop managed-history guarantee. Disconnect cannot retract earlier disclosure.
The fixture suite exercises real dispatch and HTTP request construction, private
restart persistence, identity fences, revocation and minimal money projection.
It does not prove a real Stripe account, packaged Electron or hosted transport.

## Explicit fixed EUR Payment Links

`system.capabilities.stripe_payment_links = 1` advertises
`stripe.payment_link_create(amount_minor, label, request_id)`. It accepts integer
EUR cents (1–99999999), a nonempty human-supplied label up to 200 characters and
a stable opaque request identifier of 16–128 letters, digits, underscores or
hyphens. No currency, customer, recurring or arbitrary provider fields are accepted.
The caller must have an explicit interactive human request; owner authentication
alone cannot distinguish a human from automation. Kernel headless CLI guards and
cron denies enforce the scheduled command boundary; other clients retain their
own authorization responsibilities.

Creation posts only to `/v1/prices` (EUR amount and inline Product name) and
`/v1/payment_links` (that Price, quantity one). The restricted key additionally
needs Write for Prices, Products and Payment Links; connection read probes stay
unchanged. A permission failure names the missing resource category safely.
The engine returns a minimal Stripe link/price ID and `https://buy.stripe.com`
URL with request, amount, account, mode, generation and retrieval provenance.
Custom checkout domains are outside this initial URL contract. A link is reusable
for one-time purchases; creation itself does not charge or send to a customer.

Each profile stores encrypted private `stripe.payment-link.<request-hash>`
operation state. Deterministic stage-specific Stripe idempotency keys and saved
Price/result state resume identical requests. A changed payload or connection
binding refuses reuse; unresolved operations older than 23 hours refuse further
creation. Keep the same request identifier after a timeout; never replace an
uncertain request automatically. Provider objects may exist after an interrupted
write, so a binding failure does not claim rollback. Authority/session/generation
fences apply before each write and after responses, including cached results.
Short private file locks protect journal changes; asynchronous locks serialize
local operations without holding a synchronous file lock over HTTP awaits.

Dispatcher/HTTP fixture tests cover exact EUR3500 forms, encrypted state,
local concurrency, partial recovery, conflicts, stale retries and identity
changes. Live Stripe permissions, cross-process/crash durability and installed
activation are separate acceptance; no real object is created by those fixtures.
