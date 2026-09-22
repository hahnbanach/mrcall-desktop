# Outbound calls through MrCall

<!-- doc-scope:start -->
Scope: Desktop's outbound call submission contract, authentication, approval and result limits.
<!-- doc-scope:end -->

`initiate_call` is registered for chat independently of the disabled legacy StarChat client. At execution it creates a StarChat client from the current in-memory Firebase session and closes that client afterward. It is in the canonical `APPROVAL_TOOLS` set: no approval callback or a declined approval means no call. Read-only `cs ask` does not grant it. An interactive authorized operator can use `cs chat --allow initiate_call` for a concrete call.

Every request needs `phone_number` in international format and an explicit `business_id` naming the **calling** assistant. The destination's assistant is not the caller. Session selection is not substituted at execution because it can change while approval is pending.

The request matches the dashboard:

```text
POST /mrcall/v1/{realm}/atom/{business_id}/outbound
auth: <current Firebase token>
Content-Type: application/json

{"toNumber": "390289040671"}
```

Formatting separators and an initial plus are removed; national leading zeros are retained. Malformed input, leading-zero national input and the dashboard's blocked Italian destination prefixes are refused before HTTP. The caller must supply the country code; digit syntax alone cannot distinguish every national number from an international one. The API uses the caller assistant's saved configuration. Per-call purpose, caller ID, contact or variable overrides are not supported by this contract and the legacy client arguments reject them.

A successful HTTP response yields `status=submitted`, HTTP status and the provider response. It does not establish connection, audio quality, conversation completion or customer-line forwarding. No fabricated call ID is returned. Transport failures report an unknown outcome and prohibit automatic retry because the call may already have started. HTTP or explicit provider failures are not reported as success.

This tool does not retrieve the call transcript or supply a diagnostic conversation script. A caller must obtain independent call evidence before claiming that the assistant works.
