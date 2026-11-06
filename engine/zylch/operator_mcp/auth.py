"""Per-admission introspection for the official MCP SDK resource boundary."""

import time
from urllib.parse import urlsplit

import httpx
from mcp.server.auth.provider import AccessToken, TokenVerifier

from cs.operator_read import ReadGrant

from .permissions import BASE_SCOPES, INSTRUCTION_SCOPE, INSTRUCTION_SOURCE, PRICING_SCOPE, PRICING_SOURCE, PROJECT_READ_SCOPE, PROJECT_WRITE_SCOPE, PROJECT_SOURCE, enabled_scopes, dependencies_satisfied


def secure_url(value):
    parsed = urlsplit(value)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or
            parsed.password or parsed.query or parsed.fragment):
        raise ValueError('invalid_authorization_configuration')
    return parsed


class GrantVerifier(TokenVerifier):
    def __init__(self, *, issuer, introspection_url, service_client_id,
                 service_client_secret, resource, profile_uid, company_ref,
                 allowed_client_ids=None, client_registry_url=None, http_client=None, clock=time.time,
                 instructions_enabled=False, draft_enabled=False, proposals_enabled=False, rules_write_enabled=False, pricing_enabled=False, projects_enabled=False, operator_enabled=False):
        if type(instructions_enabled) is not bool:
            raise ValueError('invalid_authorization_configuration')
        self.allowed_scopes = enabled_scopes(instructions_enabled=instructions_enabled, draft_enabled=draft_enabled, proposals_enabled=proposals_enabled, rules_write_enabled=rules_write_enabled, pricing_enabled=pricing_enabled, projects_enabled=projects_enabled, operator_enabled=operator_enabled)
        origin, endpoint = secure_url(issuer), secure_url(introspection_url)
        secure_url(resource)
        if origin.netloc != endpoint.netloc:
            raise ValueError('invalid_authorization_configuration')
        strings = (issuer, service_client_id, service_client_secret, resource, profile_uid, company_ref)
        if any(not isinstance(s, str) or not s or len(s) > 4096 for s in strings):
            raise ValueError('invalid_authorization_configuration')
        clients = frozenset(allowed_client_ids or ())
        if client_registry_url:
            registry = secure_url(client_registry_url)
            if clients or registry.netloc != origin.netloc:
                raise ValueError('invalid_authorization_configuration')
        elif not clients:
            raise ValueError('invalid_authorization_configuration')
        if any(not isinstance(c, str) or not c for c in clients):
            raise ValueError('invalid_authorization_configuration')
        self.issuer = issuer
        self.endpoint = introspection_url
        self.service_client_id = service_client_id
        self.service_client_secret = service_client_secret
        self.resource = resource
        self.profile_uid = profile_uid
        self.company_ref = company_ref
        self.clients = clients
        self.registry_url = client_registry_url
        self.http_client = http_client
        self.clock = clock

    def grant(self, payload):
        if not isinstance(payload, dict) or payload.get('active') is not True:
            raise ValueError('grant_refused')
        for key in ('sub', 'profile_uid', 'company_ref', 'client_id', 'resource', 'grant_id', 'iss'):
            value = payload.get(key)
            if not isinstance(value, str) or not value or len(value) > 2048 or '\x00' in value:
                raise ValueError('grant_refused')
        expiry = payload.get('exp')
        now = self.clock()
        if type(expiry) is not int or not now < expiry <= now + 300:
            raise ValueError('grant_refused')
        clients = self.clients
        if self.registry_url:
            values = payload.get('approved_client_ids')
            if (not isinstance(values, list) or len(values) > 1000 or
                    any(not isinstance(v, str) or not v or len(v) > 256 for v in values)):
                raise ValueError('grant_refused')
            clients = frozenset(values)
            if len(clients) != len(values):
                raise ValueError('grant_refused')
        if (payload['iss'] != self.issuer or payload['resource'] != self.resource or
                payload['sub'] != self.profile_uid or payload['profile_uid'] != self.profile_uid or
                payload['company_ref'] != self.company_ref or payload['client_id'] not in clients):
            raise ValueError('grant_refused')
        scope = payload.get('scope')
        if not isinstance(scope, str) or len(scope) > 2048:
            raise ValueError('grant_refused')
        scopes = frozenset(scope.split())
        if 'operator.read' not in scopes or not scopes <= self.allowed_scopes or not dependencies_satisfied(scopes):
            raise ValueError('grant_refused')
        sets = {}
        for key in ('source_classes', 'mailbox_ids'):
            values = payload.get(key)
            if (not isinstance(values, list) or len(values) > 16 or
                    any(not isinstance(v, str) or not v or len(v) > 256 or '\x00' in v for v in values)):
                raise ValueError('grant_refused')
            sets[key] = frozenset(values)
            if len(sets[key]) != len(values):
                raise ValueError('grant_refused')
        if not sets['source_classes'] <= {'mail', 'drafts', INSTRUCTION_SOURCE, PRICING_SOURCE, PROJECT_SOURCE}:
            raise ValueError('grant_refused')
        if ('email.read' in scopes and ('mail' not in sets['source_classes'] or len(sets['mailbox_ids']) != 1) or
                'draft.read' in scopes and not ('email.read' in scopes and 'drafts' in sets['source_classes'])):
            raise ValueError('grant_refused')
        if (PRICING_SCOPE in scopes) != (PRICING_SOURCE in sets['source_classes']):
            raise ValueError('grant_refused')
        if (PROJECT_READ_SCOPE in scopes) != (PROJECT_SOURCE in sets['source_classes']):
            raise ValueError('grant_refused')
        paths = payload.get('instruction_paths', [])
        if (not isinstance(paths, list) or len(paths) > 2 or
                any(not isinstance(p, str) or not p or len(p) > 256 for p in paths) or
                len(set(paths)) != len(paths)):
            raise ValueError('grant_refused')
        if INSTRUCTION_SCOPE in scopes:
            from zylch.services.operator_instructions import PROCEDURES, mail_path
            mail = [p for p in paths if p.startswith('mail/') and p.endswith('.md')]
            try:
                canonical_mail = mail_path(mail[0][5:-3]) if len(mail) == 1 else None
            except Exception:
                raise ValueError('grant_refused') from None
            if ('email.read' not in scopes or INSTRUCTION_SOURCE not in sets['source_classes'] or
                    len(paths) != 2 or PROCEDURES not in paths or len(mail) != 1 or
                    canonical_mail != mail[0]):
                raise ValueError('grant_refused')
        elif paths or INSTRUCTION_SOURCE in sets['source_classes']:
            raise ValueError('grant_refused')
        return ReadGrant(payload['sub'], payload['profile_uid'], payload['company_ref'],
                         payload['client_id'], payload['resource'], expiry, scopes,
                         sets['source_classes'], sets['mailbox_ids'], payload['grant_id'], frozenset(paths))

    async def _service_json(self, client, endpoint, data):
        async with client.stream('POST', endpoint, data=data,
                                 auth=(self.service_client_id, self.service_client_secret),
                                 timeout=5, follow_redirects=False) as response:
            if response.status_code != 200:
                return None
            content = bytearray()
            async for part in response.aiter_bytes(chunk_size=4096):
                content.extend(part)
                if len(content) > 65536:
                    return None
            import json
            return json.loads(content)

    async def _introspect(self, client, token):
        payload = await self._service_json(client, self.endpoint,
            {'token': token, 'token_type_hint': 'access_token', 'resource': self.resource})
        if self.registry_url:
            registry = await self._service_json(client, self.registry_url, {'resource': self.resource})
            if (not isinstance(registry, dict) or registry.get('resource') != self.resource or
                    registry.get('profile_uid') != self.profile_uid or registry.get('company_ref') != self.company_ref or
                    not isinstance(payload, dict)):
                return None
            payload['approved_client_ids'] = registry.get('client_ids')
        return payload

    async def verify_token(self, token):
        if not isinstance(token, str) or not 16 <= len(token) <= 8192 or any(c.isspace() for c in token):
            return None
        try:
            if self.http_client is None:
                async with httpx.AsyncClient(trust_env=False) as client:
                    payload = await self._introspect(client, token)
            else:
                payload = await self._introspect(self.http_client, token)
            grant = self.grant(payload)
        except Exception:
            return None
        claims = {key: payload[key] for key in ('active', 'sub', 'profile_uid', 'company_ref',
                  'client_id', 'resource', 'grant_id', 'iss', 'exp', 'scope', 'source_classes', 'mailbox_ids')}
        if 'instruction_paths' in payload:
            claims['instruction_paths'] = payload['instruction_paths']
        if self.registry_url:
            claims['approved_client_ids'] = payload['approved_client_ids']
        return AccessToken(token=token, client_id=grant.client_id, scopes=sorted(grant.scopes),
                           expires_at=grant.expires_at, resource=grant.resource,
                           subject=grant.subject, claims=claims)
