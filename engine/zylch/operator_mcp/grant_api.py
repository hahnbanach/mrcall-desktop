"""Bounded Desktop consent and service introspection around SDK OAuth routes."""

import asyncio
import base64
import hmac
import inspect
import json
import time

from mcp.server.auth.routes import create_auth_routes
from mcp.server.auth.settings import ClientRegistrationOptions, RevocationOptions
from mcp.server.transport_security import RequestBodyLimitMiddleware
from pydantic import AnyHttpUrl
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route

from .broker_store import StorageError
from .issuer import BrokerError, SCOPES


class FirebaseOwnerVerifier:
    def __init__(self, project_id):
        if not isinstance(project_id, str) or not project_id:
            raise ValueError("Firebase project required")
        self.project_id = project_id

    async def __call__(self, token):
        from zylch.rpc.firebase_auth import verify_firebase_id_token

        return await asyncio.to_thread(verify_firebase_id_token, token, self.project_id)


class TokenResourceGuard(BaseHTTPMiddleware):
    def __init__(self, app, issuer):
        super().__init__(app)
        self.issuer = issuer

    async def dispatch(self, request, call_next):
        if request.method == "POST" and request.url.path == "/token":
            try:
                await request.body()
                form = await request.form()
                if any(len(form.getlist(k)) > 1 for k in form):
                    raise BrokerError("ambiguous_token_request")
                namespace = "codes" if form.get("grant_type") == "authorization_code" else "refresh"
                value = form.get("code") if namespace == "codes" else form.get("refresh_token")
                row = (
                    self.issuer.store.get(namespace, value, include_consumed=True)
                    if isinstance(value, str)
                    else None
                )
                # A consumed refresh must reach the authenticated SDK provider
                # so replay revokes its family, even with a changed resource.
                replay = namespace == "refresh" and row and row.get("_consumed")
                if (
                    row
                    and not replay
                    and form.get("resource") is not None
                    and form["resource"] != row["resource"]
                ):
                    raise BrokerError("token_resource_mismatch")
                if row and namespace == "codes" and form.get("scope") is not None:
                    if set(str(form["scope"]).split()) != set(row["scopes"]):
                        raise BrokerError("token_scope_mismatch")
            except (BrokerError, StorageError, ValueError):
                return JSONResponse(
                    {"error": "invalid_request"},
                    status_code=400,
                    headers={"Cache-Control": "no-store"},
                )
        return await call_next(request)


def create_issuer_app(issuer, *, owner_verifier):
    async def owner(request):
        auth = request.headers.get("authorization", "")
        scheme, _, token = auth.partition(" ")
        if (
            scheme.lower() != "bearer"
            or not 16 <= len(token) <= 8192
            or any(c.isspace() for c in token)
        ):
            raise BrokerError("owner_authentication_required")
        try:
            claims = owner_verifier(token)
            if inspect.isawaitable(claims):
                claims = await claims
            subject, expiry = claims.get("sub"), claims.get("exp")
            if (
                not isinstance(subject, str)
                or not subject
                or len(subject) > 128
                or type(expiry) is not int
                or expiry <= time.time()
            ):
                raise ValueError()
            return subject
        except Exception:
            raise BrokerError("owner_authentication_refused") from None

    def outcome(value, status=200):
        return JSONResponse(value, status_code=status, headers={"Cache-Control": "no-store"})

    async def pending(request):
        try:
            return outcome({"requests": issuer.pending(await owner(request))})
        except (BrokerError, StorageError):
            return outcome({"error": "owner_request_refused"}, 401)

    async def grants(request):
        try:
            subject = await owner(request)
            keys = {"grant_id", "resource", "client_id", "scopes", "active", "expires_at"}
            rows = [
                {k: v for k, v in row.items() if k in keys}
                for row in issuer.store.list("grants")
                if row.get("subject") == subject
            ]
            return outcome({"grants": rows})
        except (BrokerError, StorageError):
            return outcome({"error": "owner_request_refused"}, 401)

    async def strict_json(request, allowed):
        if (
            request.headers.get("content-type", "").split(";")[0].strip().lower()
            != "application/json"
        ):
            raise BrokerError("invalid_request")
        value = await request.json()
        if (
            not isinstance(value, dict)
            or set(value) != allowed
            or any(not isinstance(v, str) or not v or len(v) > 256 for v in value.values())
        ):
            raise BrokerError("invalid_request")
        return value

    async def decide(request):
        try:
            subject = await owner(request)
            body = await strict_json(request, {"request_id", "payload_sha256", "decision"})
            if body["decision"] not in {"approve", "reject"}:
                raise BrokerError("invalid_decision")
            return outcome(
                issuer.approve(
                    body["request_id"],
                    subject,
                    body["payload_sha256"],
                    reject=body["decision"] == "reject",
                )
            )
        except (BrokerError, StorageError, ValueError):
            return outcome({"error": "grant_decision_refused"}, 403)

    async def revoke(request):
        try:
            subject = await owner(request)
            body = await strict_json(request, {"grant_id"})
            issuer.revoke(body["grant_id"], subject)
            return outcome({"revoked": True})
        except (BrokerError, StorageError, ValueError):
            return outcome({"error": "grant_revocation_refused"}, 403)

    async def service_request(request, allowed):
        auth = request.headers.get("authorization", "")
        scheme, _, raw = auth.partition(" ")
        if scheme.lower() != "basic" or len(raw) > 16384:
            raise BrokerError("service_authentication_required")
        decoded = base64.b64decode(raw, validate=True).decode()
        service, separator, secret = decoded.partition(":")
        if not separator:
            raise BrokerError("service_authentication_required")
        form = await request.form()
        if set(form) - allowed or any(len(form.getlist(k)) != 1 for k in form):
            raise BrokerError("invalid_service_request")
        policy = issuer.policy(form.get("resource"))
        if not hmac.compare_digest(service, policy.service_client_id) or not hmac.compare_digest(
            secret, policy.service_secret
        ):
            raise BrokerError("service_authentication_refused")
        return form, policy

    async def approved_clients(request):
        try:
            _, policy = await service_request(request, {"resource"})
            return outcome(issuer.approved_clients(policy.resource))
        except (BrokerError, StorageError, ValueError, UnicodeError, TypeError):
            return outcome({"error": "registry_refused"}, 401)

    async def introspect(request):
        try:
            form, policy = await service_request(request, {"token", "token_type_hint", "resource"})
            if not isinstance(form.get("token"), str) or len(form["token"]) > 8192:
                raise BrokerError("invalid_introspection")
            return outcome(await issuer.introspection(form["token"], policy.resource))
        except (BrokerError, StorageError, ValueError, UnicodeError, TypeError):
            return outcome({"error": "introspection_refused"}, 401)

    async def waiting(request):
        try:
            request_id = request.path_params["request_id"]
            issuer._request(request_id)
            encoded = json.dumps("/pending/" + request_id + "/complete")
            page = '<!doctype html><meta charset="utf-8"><title>MrCall connection</title>'
            page += '<h1>Confirm this connection in MrCall Desktop</h1><p id="status">Waiting for your decision in Desktop.</p>'
            page += (
                "<script>const endpoint="
                + encoded
                + ';const timer=setInterval(async()=>{try{const r=await fetch(endpoint,{cache:"no-store"});'
            )
            page += "if(r.status===202)return;const v=await r.json();clearInterval(timer);if(v.redirect_uri)location.assign(v.redirect_uri);"
            page += 'else document.getElementById("status").textContent="Connection unavailable. Start a new connection request.";'
            page += '}catch{clearInterval(timer);document.getElementById("status").textContent="Connection interrupted. Retry the connection.";}},2000);</script>'
            return HTMLResponse(
                page,
                headers={
                    "Cache-Control": "no-store",
                    "Referrer-Policy": "no-referrer",
                    "X-Content-Type-Options": "nosniff",
                },
            )
        except (BrokerError, StorageError):
            return HTMLResponse("<p>Connection request unavailable.</p>", status_code=404)

    async def completion(request):
        try:
            redirect = issuer.completion(request.path_params["request_id"])
            return outcome({"redirect_uri": redirect}, 200 if redirect else 202)
        except (BrokerError, StorageError):
            return outcome({"error": "request_unavailable"}, 404)

    routes = create_auth_routes(
        issuer,
        AnyHttpUrl(issuer.issuer),
        client_registration_options=ClientRegistrationOptions(
            enabled=True, valid_scopes=sorted(SCOPES), default_scopes=sorted(SCOPES)
        ),
        revocation_options=RevocationOptions(enabled=True),
    )
    routes += [
        Route("/desktop/grants/pending", pending, methods=["GET"]),
        Route("/desktop/grants", grants, methods=["GET"]),
        Route("/desktop/grants/decide", decide, methods=["POST"]),
        Route("/desktop/grants/revoke", revoke, methods=["POST"]),
        Route("/introspect", introspect, methods=["POST"]),
        Route("/clients/approved", approved_clients, methods=["POST"]),
        Route("/pending/{request_id}", waiting, methods=["GET"]),
        Route("/pending/{request_id}/complete", completion, methods=["GET"]),
    ]
    app = Starlette(routes=routes)
    app.add_middleware(TokenResourceGuard, issuer=issuer)
    return RequestBodyLimitMiddleware(app, 65536)
