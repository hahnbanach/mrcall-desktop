# StarChat OAuth Token Endpoint Route Ordering Bug

**Date:** 2025-12-28
**Reporter:** Zylch Integration Team
**Severity:** Critical (blocks OAuth Authorization Code flow)
**Affected Endpoint:** `POST /oauth/token`

---

## Executive Summary

The `/oauth/token` endpoint fails to process `authorization_code` grant requests because Akka HTTP's route combinator tries to decode the request body using the wrong case class. The `client_credentials` grant route (which requires `targetOwner`) is evaluated before the `authorization_code` grant route, causing valid authorization code exchange requests to fail with a JSON decoding error.

---

## Problem Description

### Observed Behavior

When a third-party client (Zylch) attempts to exchange an authorization code for tokens, the request fails with:

```
HTTP 400 Bad Request
The request content was malformed:
DecodingFailure at .targetOwner: Missing required field
```

### Expected Behavior

The endpoint should successfully decode the request as `OAuthAuthorizationCodeTokenRequest` and return access/refresh tokens.

### Request Being Sent

```json
{
  "grantType": "authorization_code",
  "code": "HcMSns}4|)Detk=+PWI+Ekq}(Yi1j=pb",
  "redirectUri": "http://localhost:8766/callback",
  "clientId": "partner_e2e68f877b0722f7",
  "clientSecret": "***REMOVED***",
  "codeVerifier": "xhGyx5BVyyMe-oDVKaQoN2WNnLGh_rF4Nwd5MBSpMNQ_CrSqSyizE3PZ-69O-Z289VvjbNaWrtunqas5aPdaZEgUHzNp5HHdH5QNZ70_IdM64-GqUrUNNXnhNkUXPNvK"
}
```

This request conforms exactly to the `OAuthAuthorizationCodeTokenRequest` case class defined in `OAuthAuthorizationCode.scala:121-134`.

---

## Root Cause Analysis

### Two Routes, Same Path

StarChat defines two separate routes for the `/oauth/token` endpoint:

1. **`oauthTokenRoute`** (line 76-110 in `OAuthTokenResource.scala`)
   - Path: `POST /oauth/token`
   - Request body: `OAuthTokenRequest` (requires `targetOwner`)
   - Purpose: `client_credentials` grant type

2. **`oauthAuthorizationCodeTokenRoute`** (line 412-470 in `OAuthTokenResource.scala`)
   - Path: `POST /oauth/token`
   - Request body: `OAuthAuthorizationCodeTokenRequest` (does NOT require `targetOwner`)
   - Purpose: `authorization_code` grant type

### Route Combination Order

In `OAuthTokenResource.scala:987-1004`, the routes are combined using Akka HTTP's `~` combinator:

```scala
object OAuthTokenResource extends Directives {
  def routes(resource: OAuthTokenResource): Route = {
    // Public token endpoints (client_credentials flow)
    resource.oauthTokenRoute ~                        // ← LINE 990 - FIRST
      resource.oauthIntrospectRoute ~
      resource.oauthRevokeRoute ~
      // Authorization code flow endpoints
      resource.oauthAuthorizeRoute ~
      resource.oauthAuthorizeApproveRoute ~
      resource.oauthAuthorizationCodeTokenRoute ~     // ← LINE 996 - SECOND
      // User delegation endpoints
      resource.oauthCreateDelegationRoute ~
      // ... rest
  }
}
```

### Why This Fails

Akka HTTP's `~` combinator evaluates routes **in order**. When a `POST /oauth/token` request arrives:

1. Akka matches the path against `oauthTokenRoute` (line 990) — **path matches**
2. Akka attempts to decode the JSON body as `OAuthTokenRequest`
3. `OAuthTokenRequest` requires `targetOwner` (see `OAuthTokenRequest.scala:18`)
4. The request doesn't have `targetOwner` → **JSON decoding fails**
5. Akka returns `400 Bad Request` with the decoding error
6. **`oauthAuthorizationCodeTokenRoute` is never tried**

The key insight is that JSON decoding failure is treated as a **completed response**, not a route rejection. Therefore, the `~` combinator does not fall through to try the next route.

---

## Case Class Definitions

### OAuthTokenRequest (for client_credentials)

**File:** `OAuthTokenRequest.scala:10-21`

```scala
case class OAuthTokenRequest(
  @Schema(requiredMode = RequiredMode.REQUIRED) grantType: String,
  @Schema(requiredMode = RequiredMode.REQUIRED) clientId: String,
  @Schema(requiredMode = RequiredMode.REQUIRED) clientSecret: String,
  @Schema(requiredMode = RequiredMode.REQUIRED) targetOwner: String,  // ← REQUIRED
  @Schema(requiredMode = RequiredMode.NOT_REQUIRED) scope: Option[String] = None
)
```

### OAuthAuthorizationCodeTokenRequest (for authorization_code)

**File:** `OAuthAuthorizationCode.scala:121-134`

```scala
case class OAuthAuthorizationCodeTokenRequest(
  @Schema(requiredMode = RequiredMode.REQUIRED) grantType: String,
  @Schema(requiredMode = RequiredMode.REQUIRED) code: String,
  @Schema(requiredMode = RequiredMode.REQUIRED) clientId: String,
  @Schema(requiredMode = RequiredMode.REQUIRED) clientSecret: String,
  @Schema(requiredMode = RequiredMode.REQUIRED) redirectUri: String,
  @Schema(requiredMode = RequiredMode.NOT_REQUIRED) codeVerifier: Option[String] = None
  // ← NO targetOwner field
)
```

---

## Proposed Solutions

### Solution 1: Reorder Routes (Quick Fix)

Change the route order so `oauthAuthorizationCodeTokenRoute` is evaluated **before** `oauthTokenRoute`.

**File:** `OAuthTokenResource.scala`, modify the `routes()` method:

```scala
object OAuthTokenResource extends Directives {
  def routes(resource: OAuthTokenResource): Route = {
    // Authorization code flow endpoints FIRST (more specific)
    resource.oauthAuthorizationCodeTokenRoute ~     // ← MOVED UP
      resource.oauthAuthorizeRoute ~
      resource.oauthAuthorizeApproveRoute ~
    // Public token endpoints (client_credentials flow)
      resource.oauthTokenRoute ~                     // ← MOVED DOWN
      resource.oauthIntrospectRoute ~
      resource.oauthRevokeRoute ~
      // User delegation endpoints
      resource.oauthCreateDelegationRoute ~
      resource.oauthRevokeDelegationRoute ~
      resource.oauthListDelegationsRoute ~
      // Admin client management endpoints
      resource.oauthRegisterClientRoute ~
      resource.oauthListClientsRoute ~
      resource.oauthUpdateClientRoute ~
      resource.oauthDeleteClientRoute
  }
}
```

**Why this works:**
- `OAuthAuthorizationCodeTokenRequest` has `code` and `redirectUri` fields that `OAuthTokenRequest` doesn't have
- `OAuthTokenRequest` has `targetOwner` that `OAuthAuthorizationCodeTokenRequest` doesn't have
- By trying the authorization_code route first, requests with `code` will decode successfully
- Requests with `targetOwner` (client_credentials) will fail the first route's decode and fall through to the second

**Caveat:** This relies on decode failures being treated as rejections. Need to verify Akka HTTP's behavior.

### Solution 2: Discriminate by grantType Before Decoding (Recommended)

Create a single unified route that inspects the `grantType` field before attempting to decode the full body.

```scala
def unifiedOAuthTokenRoute: Route =
  path("oauth" / "token") {
    post {
      entity(as[JsValue]) { json =>
        val grantType = (json \ "grantType").asOpt[String]
        grantType match {
          case Some("authorization_code") =>
            json.validate[OAuthAuthorizationCodeTokenRequest] match {
              case JsSuccess(request, _) =>
                onComplete(oauthService.exchangeAuthorizationCode(request)) { ... }
              case JsError(errors) =>
                complete(StatusCodes.BadRequest, OAuthErrorResponse("invalid_request", ...))
            }
          case Some("client_credentials") =>
            json.validate[OAuthTokenRequest] match {
              case JsSuccess(request, _) =>
                onComplete(oauthService.issueToken(request)) { ... }
              case JsError(errors) =>
                complete(StatusCodes.BadRequest, OAuthErrorResponse("invalid_request", ...))
            }
          case Some("refresh_token") =>
            // Handle refresh token grant
          case _ =>
            complete(StatusCodes.BadRequest, OAuthErrorResponse(
              "unsupported_grant_type",
              s"Grant type '$grantType' is not supported".some
            ))
        }
      }
    }
  }
```

**Advantages:**
- Single route, no ordering issues
- Explicit grant type handling
- Better error messages (e.g., "unsupported_grant_type" instead of JSON decode errors)
- Follows OAuth 2.0 RFC 6749 error response conventions
- Easier to add new grant types in the future

### Solution 3: Use Different Paths (Alternative)

Define separate endpoints for each grant type:

- `POST /oauth/token` → client_credentials only
- `POST /oauth/token/code` → authorization_code exchange
- `POST /oauth/token/refresh` → refresh_token grant

**Advantages:**
- Clear separation of concerns
- No ambiguity in request decoding

**Disadvantages:**
- Deviates from OAuth 2.0 RFC 6749 which uses a single `/token` endpoint
- Requires client changes

---

## Impact Assessment

### Affected Functionality
- All third-party integrations using the Authorization Code flow with PKCE
- Specifically: Zylch's `/connect mrcall` OAuth flow

### Not Affected
- Client Credentials flow (works because it matches the first route)
- Refresh Token flow (if using a separate route)
- User authentication via Firebase

---

## Testing Recommendations

After applying the fix, verify:

1. **Authorization Code Exchange:**
   ```bash
   curl -X POST https://api.mrcall.ai/oauth/token \
     -H "Content-Type: application/json" \
     -d '{
       "grantType": "authorization_code",
       "code": "<auth_code>",
       "redirectUri": "http://localhost:8766/callback",
       "clientId": "partner_xxx",
       "clientSecret": "secret",
       "codeVerifier": "<pkce_verifier>"
     }'
   ```
   Expected: 200 OK with `accessToken`, `refreshToken`, `expiresIn`

2. **Client Credentials (regression test):**
   ```bash
   curl -X POST https://api.mrcall.ai/oauth/token \
     -H "Content-Type: application/json" \
     -d '{
       "grantType": "client_credentials",
       "clientId": "partner_xxx",
       "clientSecret": "secret",
       "targetOwner": "<firebase_uid>"
     }'
   ```
   Expected: 200 OK with `accessToken`, `expiresIn`

3. **Invalid Grant Type:**
   ```bash
   curl -X POST https://api.mrcall.ai/oauth/token \
     -H "Content-Type: application/json" \
     -d '{"grantType": "invalid"}'
   ```
   Expected: 400 with `{"error": "unsupported_grant_type"}`

---

## References

- **OAuth 2.0 RFC 6749:** https://datatracker.ietf.org/doc/html/rfc6749#section-4.1.3
- **PKCE RFC 7636:** https://datatracker.ietf.org/doc/html/rfc7636
- **Akka HTTP Route Composition:** https://doc.akka.io/docs/akka-http/current/routing-dsl/routes.html

---

## Contact

For questions about this issue, contact the Zylch integration team.
