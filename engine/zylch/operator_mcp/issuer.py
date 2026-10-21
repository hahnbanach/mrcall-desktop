"""MrCall consent and durable authority behind the maintained SDK OAuth routes."""

from dataclasses import dataclass, field
import hashlib
import json
import re
import secrets
import time
from urllib.parse import urlencode, urlsplit

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizeError,
    RefreshToken,
    RegistrationError,
    TokenError,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

from .auth import secure_url
from .broker_store import StorageError

SCOPES = frozenset({"operator.read", "email.read", "draft.read"})


@dataclass(frozen=True)
class ProfilePolicy:
    profile_uid: str
    email: str
    company_ref: str
    resource: str
    mailbox_ids: frozenset[str]
    service_client_id: str
    service_secret: str = field(repr=False)
    allowed_scopes: frozenset[str] = SCOPES
    enabled: bool = True


class GrantCode(AuthorizationCode):
    grant_id: str


class GrantRefresh(RefreshToken):
    grant_id: str


class BrokerError(ValueError):
    pass


class DesktopGrantIssuer:
    def __init__(self, store, *, issuer, policy_resolver, native_callbacks, clock=time.time):
        secure_url(issuer)
        callbacks = frozenset(native_callbacks)
        if not callbacks or any(
            host not in {"localhost", "127.0.0.1", "::1"} or not path.startswith("/")
            for host, path in callbacks
        ):
            raise ValueError("invalid_callback_configuration")
        self.store = store
        self.issuer = issuer.rstrip("/")
        self.policy_resolver = policy_resolver
        self.callbacks = callbacks
        self.clock = clock

    def policy(self, resource):
        try:
            policy = self.policy_resolver(resource)
        except Exception:
            raise BrokerError("policy_unavailable") from None
        if (
            not isinstance(policy, ProfilePolicy)
            or policy.enabled is not True
            or policy.resource != resource
            or not policy.profile_uid
            or not policy.company_ref
            or not policy.email
            or not isinstance(policy.allowed_scopes, frozenset)
            or not policy.allowed_scopes <= SCOPES
            or "operator.read" not in policy.allowed_scopes
            or not isinstance(policy.mailbox_ids, frozenset)
            or any(not isinstance(i, str) or not i for i in policy.mailbox_ids)
            or not isinstance(policy.service_client_id, str)
            or not policy.service_client_id
            or not isinstance(policy.service_secret, str)
            or len(policy.service_secret) < 16
        ):
            raise BrokerError("resource_unavailable")
        return policy

    def redirect_allowed(self, uri):
        try:
            parsed = urlsplit(str(uri))
            return (
                parsed.scheme == "http"
                and (parsed.hostname, parsed.path) in self.callbacks
                and parsed.port is not None
                and 0 < parsed.port < 65536
                and not parsed.username
                and not parsed.password
                and not parsed.query
                and not parsed.fragment
            )
        except ValueError:
            return False

    async def get_client(self, client_id):
        row = self.store.get("clients", client_id)
        return OAuthClientInformationFull.model_validate(row) if row else None

    async def register_client(self, client_info):
        if (
            client_info.token_endpoint_auth_method != "none"
            or client_info.client_secret is not None
            or set(client_info.grant_types) != {"authorization_code", "refresh_token"}
            or client_info.response_types != ["code"]
            or not client_info.redirect_uris
            or len(client_info.redirect_uris) > 4
            or any(not self.redirect_allowed(u) for u in client_info.redirect_uris)
            or client_info.jwks_uri is not None
            or client_info.jwks is not None
            or len(client_info.client_name or "") > 100
            or not set((client_info.scope or "").split()) <= SCOPES
        ):
            raise RegistrationError(
                error="invalid_client_metadata",
                error_description="Unsupported native client metadata",
            )
        with self.store.transaction() as connection:
            if self.store.count("clients", connection=connection) >= 1000:
                raise RegistrationError(
                    error="invalid_client_metadata",
                    error_description="Client registry capacity reached",
                )
            self.store.put(
                "clients",
                client_info.client_id,
                client_info.model_dump(mode="json"),
                connection=connection,
            )

    def _scope(self, scopes, policy):
        scopes = frozenset(scopes)
        if (
            not scopes <= policy.allowed_scopes
            or "operator.read" not in scopes
            or "draft.read" in scopes
            and "email.read" not in scopes
            or "email.read" in scopes
            and len(policy.mailbox_ids) != 1
        ):
            raise BrokerError("scope_unavailable")
        return sorted(scopes)

    @staticmethod
    def _authority(policy, scopes):
        return {
            "profile_uid": policy.profile_uid,
            "company_ref": policy.company_ref,
            "mailbox_ids": sorted(policy.mailbox_ids) if "email.read" in scopes else [],
        }

    async def authorize(self, client, params):
        try:
            policy = self.policy(params.resource)
            scopes = self._scope(params.scopes or [], policy)
            if (
                not self.redirect_allowed(params.redirect_uri)
                or not re.fullmatch(r"[A-Za-z0-9_-]{43}", params.code_challenge)
                or len(params.state or "") > 512
            ):
                raise BrokerError("authorization_request_refused")
            requested = urlsplit(str(params.redirect_uri))
            if not any(
                (urlsplit(str(u)).hostname, urlsplit(str(u)).path)
                == (requested.hostname, requested.path)
                for u in client.redirect_uris
            ):
                raise BrokerError("authorization_request_refused")
            request_id = secrets.token_urlsafe(32)
            payload = {
                "request_id": request_id,
                "client_id": client.client_id,
                "resource": params.resource,
                "scopes": scopes,
                "redirect_uri": str(params.redirect_uri),
                "redirect_uri_provided_explicitly": params.redirect_uri_provided_explicitly,
                "code_challenge": params.code_challenge,
                "state": params.state,
                "authority": self._authority(policy, scopes),
            }
            payload["payload_sha256"] = hashlib.sha256(
                json.dumps(payload, sort_keys=True).encode()
            ).hexdigest()
            payload.update(status="pending", expires_at=int(self.clock()) + 600)
            with self.store.transaction() as connection:
                if self.store.count("pending", connection=connection) >= 10000:
                    raise BrokerError("authorization_capacity_reached")
                self.store.put("pending", request_id, payload, connection=connection)
            return self.issuer + "/pending/" + request_id
        except (BrokerError, StorageError):
            raise AuthorizeError(
                error="access_denied", error_description="Authorization request unavailable"
            ) from None

    def _request(self, request_id, connection=None):
        row = self.store.get("pending", request_id, connection=connection)
        if not row or row["expires_at"] <= self.clock():
            raise BrokerError("request_unavailable")
        policy = self.policy(row["resource"])
        self._scope(row["scopes"], policy)
        if row["authority"] != self._authority(policy, row["scopes"]):
            raise BrokerError("request_authority_changed")
        return row, policy

    def pending(self, subject):
        out = []
        for row in self.store.list("pending"):
            if (
                row.get("status") != "pending"
                or row.get("authority", {}).get("profile_uid") != subject
            ):
                continue
            try:
                current, policy = self._request(row["request_id"])
            except BrokerError:
                continue
            client = self.store.get("clients", current["client_id"])
            out.append(
                {
                    "request_id": current["request_id"],
                    "payload_sha256": current["payload_sha256"],
                    "client_id": current["client_id"],
                    "client_name": (client or {}).get("client_name"),
                    "resource": current["resource"],
                    "scopes": current["scopes"],
                    "profile_uid": policy.profile_uid,
                    "email": policy.email,
                    "mailbox_ids": sorted(policy.mailbox_ids),
                    "company_ref": policy.company_ref,
                    "redirect_uri": current["redirect_uri"],
                    "expires_at": current["expires_at"],
                }
            )
        return out

    def approve(self, request_id, subject, expected_sha256, *, reject=False):
        with self.store.transaction() as connection:
            row, policy = self._request(request_id, connection)
            if policy.profile_uid != subject or row["payload_sha256"] != expected_sha256:
                raise BrokerError("request_owner_or_revision_mismatch")
            if row["status"] != "pending":
                raise BrokerError("request_already_resolved")
            row["status"] = "rejected" if reject else "approved"
            if not reject:
                grant_id = secrets.token_urlsafe(32)
                grant = {
                    "grant_id": grant_id,
                    "subject": subject,
                    "resource": row["resource"],
                    "client_id": row["client_id"],
                    "scopes": row["scopes"],
                    "authority": row["authority"],
                    "active": True,
                    "expires_at": int(self.clock()) + 30 * 86400,
                }
                self.store.put("grants", grant_id, grant, connection=connection)
                row["grant_id"] = grant_id
            self.store.update("pending", request_id, row, connection=connection)
        return {"status": row["status"], "request_id": request_id}

    def _grant(self, grant_id, connection=None):
        row = self.store.get("grants", grant_id, connection=connection)
        if not row or row.get("active") is not True or row["expires_at"] <= self.clock():
            raise BrokerError("grant_unavailable")
        policy = self.policy(row["resource"])
        self._scope(row["scopes"], policy)
        if row["subject"] != policy.profile_uid or row["authority"] != self._authority(
            policy, row["scopes"]
        ):
            raise BrokerError("grant_authority_changed")
        return row, policy

    def completion(self, request_id):
        with self.store.transaction() as connection:
            row, _ = self._request(request_id, connection)
            if row["status"] == "pending":
                return None
            if row["status"] == "rejected":
                values = {"error": "access_denied", "state": row["state"]}
            elif row["status"] == "approved":
                grant, _ = self._grant(row["grant_id"], connection)
                raw = secrets.token_urlsafe(32)
                code = {
                    key: row[key]
                    for key in (
                        "client_id",
                        "scopes",
                        "redirect_uri",
                        "redirect_uri_provided_explicitly",
                        "code_challenge",
                        "resource",
                    )
                }
                code.update(
                    expires_at=int(self.clock()) + 300,
                    subject=grant["subject"],
                    grant_id=grant["grant_id"],
                )
                self.store.put("codes", raw, code, connection=connection)
                values = {"code": raw, "state": row["state"]}
            else:
                raise BrokerError("request_already_completed")
            row["status"] = "completed"
            self.store.update("pending", request_id, row, connection=connection)
        return (
            row["redirect_uri"]
            + "?"
            + urlencode({k: v for k, v in values.items() if v is not None})
        )

    async def load_authorization_code(self, client, authorization_code):
        row = self.store.get("codes", authorization_code)
        if not row or row["client_id"] != client.client_id:
            return None
        try:
            self._grant(row["grant_id"])
            return GrantCode(code=authorization_code, **row)
        except (BrokerError, StorageError):
            return None

    def _tokens(self, grant, scopes, connection):
        access, refresh = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        data = {
            "grant_id": grant["grant_id"],
            "client_id": grant["client_id"],
            "resource": grant["resource"],
            "scopes": sorted(scopes),
            "subject": grant["subject"],
        }
        self.store.put(
            "access", access, {**data, "expires_at": int(self.clock()) + 300}, connection=connection
        )
        self.store.put(
            "refresh", refresh, {**data, "expires_at": grant["expires_at"]}, connection=connection
        )
        return OAuthToken(
            access_token=access,
            refresh_token=refresh,
            expires_in=300,
            scope=" ".join(sorted(scopes)),
        )

    async def exchange_authorization_code(self, client, authorization_code):
        try:
            with self.store.transaction() as connection:
                row = self.store.consume("codes", authorization_code.code, connection=connection)
                if (
                    not row
                    or row["client_id"] != client.client_id
                    or row["expires_at"] <= self.clock()
                ):
                    raise BrokerError("code_unavailable")
                grant, _ = self._grant(row["grant_id"], connection)
                return self._tokens(grant, row["scopes"], connection)
        except (BrokerError, StorageError):
            raise TokenError(
                error="invalid_grant", error_description="Authorization code unavailable"
            ) from None

    def revoke(self, grant_id, subject=None, connection=None):
        if connection is None:
            with self.store.transaction() as connection:
                return self.revoke(grant_id, subject, connection)
        row = self.store.get("grants", grant_id, connection=connection)
        if not row or subject is not None and row["subject"] != subject:
            raise BrokerError("grant_unavailable")
        row["active"] = False
        self.store.update("grants", grant_id, row, connection=connection)

    async def load_refresh_token(self, client, refresh_token):
        row = self.store.get("refresh", refresh_token, include_consumed=True)
        if not row or row["client_id"] != client.client_id:
            return None
        if row.pop("_consumed", False):
            self.revoke(row["grant_id"])
            return None
        try:
            self._grant(row["grant_id"])
            return GrantRefresh(token=refresh_token, **row)
        except (BrokerError, StorageError):
            return None

    async def exchange_refresh_token(self, client, refresh_token, scopes):
        replay = False
        try:
            with self.store.transaction() as connection:
                row = self.store.get(
                    "refresh", refresh_token.token, include_consumed=True, connection=connection
                )
                if not row or row["client_id"] != client.client_id:
                    raise BrokerError("refresh_unavailable")
                if row.get("_consumed"):
                    self.revoke(row["grant_id"], connection=connection)
                    replay = True
                else:
                    self.store.consume("refresh", refresh_token.token, connection=connection)
                    grant, policy = self._grant(row["grant_id"], connection)
                    scope = self._scope(scopes, policy)
                    if not set(scope) <= set(row["scopes"]) or row["expires_at"] <= self.clock():
                        raise BrokerError("scope_unavailable")
                    result = self._tokens(grant, scope, connection)
            if replay:
                raise BrokerError("refresh_replayed")
            return result
        except (BrokerError, StorageError):
            raise TokenError(
                error="invalid_grant", error_description="Refresh token unavailable"
            ) from None

    async def load_access_token(self, token):
        row = self.store.get("access", token)
        if not row or row["expires_at"] <= self.clock():
            return None
        try:
            grant, _ = self._grant(row["grant_id"])
        except (BrokerError, StorageError):
            return None
        return AccessToken(
            token=token,
            client_id=row["client_id"],
            scopes=row["scopes"],
            expires_at=row["expires_at"],
            resource=row["resource"],
            subject=grant["subject"],
            claims={"grant_id": grant["grant_id"]},
        )

    async def revoke_token(self, token):
        namespace = "refresh" if isinstance(token, RefreshToken) else "access"
        row = self.store.get(namespace, token.token, include_consumed=True)
        if row:
            self.revoke(row["grant_id"])

    def approved_clients(self, resource):
        policy = self.policy(resource)
        clients = set()
        for row in self.store.list("grants"):
            if row.get("resource") != resource:
                continue
            try:
                current, _ = self._grant(row["grant_id"])
            except BrokerError:
                continue
            client = self.store.get("clients", current["client_id"])
            if client and client.get("client_id") == current["client_id"]:
                clients.add(current["client_id"])
        if len(clients) > 1000:
            raise BrokerError("registry_unavailable")
        return {
            "resource": resource,
            "profile_uid": policy.profile_uid,
            "company_ref": policy.company_ref,
            "client_ids": sorted(clients),
        }

    async def introspection(self, token, resource):
        access = await self.load_access_token(token)
        if access is None or access.resource != resource:
            return {"active": False}
        grant, _ = self._grant(access.claims["grant_id"])
        source_classes = (["mail"] if "email.read" in access.scopes else []) + (
            ["drafts"] if "draft.read" in access.scopes else []
        )
        return {
            "active": True,
            "iss": self.issuer,
            "sub": grant["subject"],
            **grant["authority"],
            "client_id": grant["client_id"],
            "resource": resource,
            "grant_id": grant["grant_id"],
            "scope": " ".join(access.scopes),
            "source_classes": source_classes,
            "exp": access.expires_at,
        }
