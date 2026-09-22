# Restore MrCall outbound calls from Desktop

<!-- doc-scope:start -->
Scope: intent and acceptance for restoring the existing outbound-call tool through the dashboard's StarChat API.
<!-- doc-scope:end -->

The operator wants Giada to call a customer's MrCall assistant through MrCall itself. The dashboard already posts `{"toNumber":"39..."}` to `/mrcall/v1/{realm}/atom/{businessId}/outbound` with Firebase authentication. Desktop's existing tool uses another contract and is never registered because its legacy client is disabled.

Restore the tool using the current Firebase session and the dashboard contract. Add `initiate_call` to the canonical approval list: a missing or declining approval callback must refuse before dispatch. Use an explicitly supplied calling assistant ID in every request, never infer the customer's target assistant as the caller. Validate the destination before dispatch, and distinguish an accepted request from an answered or successful diagnostic call. Do not invent support for per-call conversation instructions or a call identifier that the API does not return. Do not change StarChat, assistant configuration, schedules, or unrelated profiles. No automatic Git commits.

Acceptance: focused tests prove registration, current-session authentication, exact realm/path/body, destination validation, client cleanup, honest response handling, and approval denial before dispatch. Determine the deployed support profile's calling assistant and report any live-test prerequisites. A live test, if the existing authorized path permits it, targets only Litio's MrCall number +390289040671; it never calls their business line or sends email. Deployment must be scoped to the support engine with rollback evidence, preserving the service user's authoritative profile.
