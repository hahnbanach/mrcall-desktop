"""SDK OAuth protocol, durable consent and introspection source checks."""

import asyncio
import base64
import hashlib
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx

from zylch.operator_mcp.auth import GrantVerifier
from zylch.operator_mcp.broker_store import BrokerStore
from zylch.operator_mcp.grant_api import create_issuer_app
from zylch.operator_mcp.issuer import DesktopGrantIssuer, ProfilePolicy


class IssuerTests(unittest.TestCase):
    def run_case(self, exercise):
        async def run():
            with tempfile.TemporaryDirectory() as directory:
                self.path = Path(directory) / 'issuer.db'
                self.now = int(time.time())
                self.policy = ProfilePolicy('owner', 'owner@example.test', 'company',
                    'https://engine.example.test/mcp', frozenset({'mailbox'}),
                    'profile-service', 'service-secret-canary')
                self.store = BrokerStore(self.path)
                self.issuer = self.make_issuer()
                self.http = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.make_app()),
                    base_url='https://auth.example.test')
                try:
                    await exercise()
                finally:
                    await self.http.aclose()
        asyncio.run(run())

    def make_issuer(self):
        return DesktopGrantIssuer(self.store, issuer='https://auth.example.test',
            policy_resolver=lambda resource: self.policy if resource == self.policy.resource else None,
            native_callbacks={('127.0.0.1', '/callback')}, clock=lambda: self.now)

    def make_app(self):
        async def owner(token):
            if token == 'test-desktop-owner-token':
                return {'sub': 'owner', 'exp': int(time.time()) + 120}
            if token == 'test-other-owner-token':
                return {'sub': 'other', 'exp': int(time.time()) + 120}
            raise ValueError('provider-secret-canary')
        return create_issuer_app(self.issuer, owner_verifier=owner)

    async def register(self, **changes):
        metadata = {'redirect_uris': ['http://127.0.0.1:49152/callback'],
                    'client_name': 'Native test client', 'token_endpoint_auth_method': 'none',
                    'grant_types': ['authorization_code', 'refresh_token'], 'response_types': ['code']}
        response = await self.http.post('/register', json={**metadata, **changes})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    async def start(self, client, **changes):
        self.verifier = 'a' * 43
        challenge = base64.urlsafe_b64encode(hashlib.sha256(self.verifier.encode()).digest()).decode().rstrip('=')
        params = {'response_type': 'code', 'client_id': client['client_id'],
                  'redirect_uri': client['redirect_uris'][0], 'resource': self.policy.resource,
                  'scope': 'operator.read email.read draft.read', 'state': 'native-state',
                  'code_challenge': challenge, 'code_challenge_method': 'S256'}
        response = await self.http.get('/authorize', params={**params, **changes})
        self.assertEqual(response.status_code, 302, response.text)
        self.assertIn('/pending/', response.headers['location'])
        return response.headers['location'].rsplit('/', 1)[1]

    async def approve(self, request_id, owner='test-desktop-owner-token'):
        response = await self.http.get('/desktop/grants/pending', headers={'Authorization': 'Bearer ' + owner})
        rows = response.json()['requests']
        row = next(row for row in rows if row['request_id'] == request_id)
        return await self.http.post('/desktop/grants/decide',
            headers={'Authorization': 'Bearer ' + owner},
            json={'request_id': request_id, 'payload_sha256': row['payload_sha256'], 'decision': 'approve'})

    async def code(self, client):
        request_id = await self.start(client)
        pending = await self.http.get('/pending/' + request_id + '/complete')
        self.assertEqual(pending.status_code, 202)
        self.assertEqual((await self.approve(request_id)).status_code, 200)
        done = await self.http.get('/pending/' + request_id + '/complete')
        values = parse_qs(urlsplit(done.json()['redirect_uri']).query)
        self.assertEqual(values['state'], ['native-state'])
        self.assertEqual((await self.http.get('/pending/' + request_id + '/complete')).status_code, 404)
        return values['code'][0]

    async def exchange(self, client, code, **changes):
        return await self.http.post('/token', data={'grant_type': 'authorization_code',
            'client_id': client['client_id'], 'code': code, 'code_verifier': self.verifier,
            'redirect_uri': client['redirect_uris'][0], **changes})

    async def introspect(self, access, **changes):
        return await self.http.post('/introspect', auth=('profile-service', 'service-secret-canary'),
            data={'token': access, 'resource': self.policy.resource, **changes})

    def test_discovery_matches_public_client_authentication(self):
        async def exercise():
            response = await self.http.get('/.well-known/oauth-authorization-server')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers['cache-control'], 'no-store')
            metadata = response.json()
            self.assertEqual(metadata['token_endpoint_auth_methods_supported'], ['none'])
            self.assertEqual(metadata['revocation_endpoint_auth_methods_supported'], ['none'])
            self.assertEqual(metadata['code_challenge_methods_supported'], ['S256'])
            client = await self.register()
            self.assertEqual(client['token_endpoint_auth_method'], 'none')
        self.run_case(exercise)

    def test_sdk_oauth_consent_refresh_replay_and_restart(self):
        self.run_case(self.exercise_sdk_oauth_consent_refresh_replay_and_restart)

    async def exercise_sdk_oauth_consent_refresh_replay_and_restart(self):
        metadata = (await self.http.get('/.well-known/oauth-authorization-server')).json()
        self.assertEqual(metadata['code_challenge_methods_supported'], ['S256'])
        client = await self.register()
        code = await self.code(client)
        token = await self.exchange(client, code)
        self.assertEqual(token.status_code, 200, token.text)
        pair = token.json()
        self.assertEqual((await self.exchange(client, code)).status_code, 400)
        active = (await self.introspect(pair['access_token'])).json()
        self.assertTrue(active['active'])
        self.assertEqual(active['profile_uid'], 'owner')
        self.assertEqual(active['source_classes'], ['mail', 'drafts'])
        self.store = BrokerStore(self.path)
        self.issuer = self.make_issuer()
        await self.http.aclose()
        self.http = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.make_app()), base_url='https://auth.example.test')
        self.assertTrue((await self.introspect(pair['access_token'])).json()['active'])
        refreshed = await self.http.post('/token', data={'grant_type': 'refresh_token',
            'client_id': client['client_id'], 'refresh_token': pair['refresh_token']})
        self.assertEqual(refreshed.status_code, 200, refreshed.text)
        new = refreshed.json()
        self.assertNotEqual(new['refresh_token'], pair['refresh_token'])
        replay = await self.http.post('/token', data={'grant_type': 'refresh_token',
            'client_id': client['client_id'], 'refresh_token': pair['refresh_token'],
            'resource': 'https://wrong.example.test/mcp'})
        self.assertEqual(replay.status_code, 400)
        self.assertFalse((await self.introspect(new['access_token'])).json()['active'])
        durable = self.path.read_bytes()
        for secret in (code, pair['access_token'], pair['refresh_token'], new['access_token']):
            self.assertNotIn(secret.encode(), durable)

    def test_wrong_redirect_pkce_resource_and_scope(self):
        self.run_case(self.exercise_wrong_redirect_pkce_resource_and_scope)

    async def exercise_wrong_redirect_pkce_resource_and_scope(self):
        for redirect in ('https://attacker.example/callback', 'http://127.0.0.1:49152/wrong',
                         'http://localhost:49152/callback', 'http://127.0.0.1:49152/callback?secret=x'):
            response = await self.http.post('/register', json={'redirect_uris': [redirect],
                'token_endpoint_auth_method': 'none', 'grant_types': ['authorization_code', 'refresh_token'], 'response_types': ['code']})
            self.assertEqual(response.status_code, 400)
        client = await self.register()
        code = await self.code(client)
        self.assertEqual((await self.exchange(client, code, code_verifier='b' * 43)).status_code, 400)
        self.assertEqual((await self.exchange(client, code, resource='https://wrong.example.test/mcp')).status_code, 400)
        self.assertEqual((await self.exchange(client, code, scope='operator.read send')).status_code, 400)
        self.assertEqual((await self.exchange(client, code)).status_code, 200)

    def test_desktop_owner_revision_reject_and_revocation(self):
        self.run_case(self.exercise_desktop_owner_revision_reject_and_revocation)

    async def exercise_desktop_owner_revision_reject_and_revocation(self):
        client = await self.register()
        request_id = await self.start(client)
        owner_headers = {'Authorization': 'Bearer test-desktop-owner-token'}
        request = (await self.http.get('/desktop/grants/pending', headers=owner_headers)).json()['requests'][0]
        for headers, sha in (({'Authorization': 'Bearer test-other-owner-token'}, request['payload_sha256']),
                             (owner_headers, 'wrong-revision'), ({'Authorization': 'Bearer test-opaque-mcp-token'}, request['payload_sha256'])):
            response = await self.http.post('/desktop/grants/decide', headers=headers,
                json={'request_id': request_id, 'payload_sha256': sha, 'decision': 'approve'})
            self.assertEqual(response.status_code, 403)
            self.assertNotIn('provider-secret-canary', response.text)
        rejected = await self.http.post('/desktop/grants/decide', headers=owner_headers,
            json={'request_id': request_id, 'payload_sha256': request['payload_sha256'], 'decision': 'reject'})
        self.assertEqual(rejected.status_code, 200)
        done = await self.http.get('/pending/' + request_id + '/complete')
        self.assertEqual(parse_qs(urlsplit(done.json()['redirect_uri']).query)['error'], ['access_denied'])
        code = await self.code(client)
        pair = (await self.exchange(client, code)).json()
        grant_id = (await self.introspect(pair['access_token'])).json()['grant_id']
        refused = await self.http.post('/desktop/grants/revoke', headers={'Authorization': 'Bearer test-other-owner-token'}, json={'grant_id': grant_id})
        self.assertEqual(refused.status_code, 403)
        self.assertTrue((await self.introspect(pair['access_token'])).json()['active'])
        self.assertEqual((await self.http.post('/desktop/grants/revoke', headers=owner_headers, json={'grant_id': grant_id})).status_code, 200)
        self.assertFalse((await self.introspect(pair['access_token'])).json()['active'])

    def test_expiry_policy_change_and_service_identity(self):
        self.run_case(self.exercise_expiry_policy_change_and_service_identity)

    async def exercise_expiry_policy_change_and_service_identity(self):
        client = await self.register()
        code = await self.code(client)
        pair = (await self.exchange(client, code)).json()
        denied = await self.http.post('/introspect', auth=('other-profile-service', 'service-secret-canary'),
            data={'token': pair['access_token'], 'resource': self.policy.resource})
        self.assertEqual(denied.status_code, 401)
        self.now += 301
        self.assertFalse((await self.introspect(pair['access_token'])).json()['active'])
        self.now -= 301
        self.policy = replace(self.policy, company_ref='changed-company')
        self.assertFalse((await self.introspect(pair['access_token'])).json()['active'])
        self.policy = replace(self.policy, enabled=False)
        self.assertEqual((await self.introspect(pair['access_token'])).status_code, 401)

    def test_issuer_claims_are_accepted_by_resource_verifier(self):
        self.run_case(self.exercise_issuer_claims_are_accepted_by_resource_verifier)

    def test_dynamic_approved_client_registry(self):
        self.run_case(self.exercise_dynamic_approved_client_registry)

    async def exercise_dynamic_approved_client_registry(self):
        client = await self.register()
        async def registry():
            return await self.http.post('/clients/approved',
                auth=('profile-service', 'service-secret-canary'), data={'resource': self.policy.resource})
        self.assertEqual((await registry()).json()['client_ids'], [])
        pair = (await self.exchange(client, await self.code(client))).json()
        self.assertEqual((await registry()).json()['client_ids'], [client['client_id']])
        verifier = GrantVerifier(issuer=self.issuer.issuer,
            introspection_url=self.issuer.issuer + '/introspect',
            client_registry_url=self.issuer.issuer + '/clients/approved',
            service_client_id=self.policy.service_client_id, service_client_secret=self.policy.service_secret,
            resource=self.policy.resource, profile_uid='owner', company_ref='company', http_client=self.http)
        access = await verifier.verify_token(pair['access_token'])
        self.assertIsNotNone(access)
        self.assertEqual(verifier.grant(access.claims).client_id, client['client_id'])
        self.assertEqual((await self.http.post('/clients/approved', auth=('wrong', 'wrong'),
            data={'resource': self.policy.resource})).status_code, 401)
        grant_id = (await self.introspect(pair['access_token'])).json()['grant_id']
        self.issuer.revoke(grant_id)
        self.assertEqual((await registry()).json()['client_ids'], [])
        self.assertIsNone(await verifier.verify_token(pair['access_token']))

    def test_concurrent_code_and_refresh_exchanges(self):
        self.run_case(self.exercise_concurrent_code_and_refresh_exchanges)

    async def exercise_concurrent_code_and_refresh_exchanges(self):
        client = await self.register()
        code = await self.code(client)
        results = await asyncio.gather(self.exchange(client, code), self.exchange(client, code))
        self.assertEqual(sorted(r.status_code for r in results), [200, 400])
        pair = next(r.json() for r in results if r.status_code == 200)
        request = {'grant_type': 'refresh_token', 'client_id': client['client_id'],
                   'refresh_token': pair['refresh_token']}
        refreshed = await asyncio.gather(self.http.post('/token', data=request), self.http.post('/token', data=request))
        self.assertEqual(sorted(r.status_code for r in refreshed), [200, 400])
        first = next(r.json() for r in refreshed if r.status_code == 200)
        self.assertFalse((await self.introspect(first['access_token'])).json()['active'])

    async def exercise_issuer_claims_are_accepted_by_resource_verifier(self):
        client = await self.register()
        pair = (await self.exchange(client, await self.code(client))).json()
        verifier = GrantVerifier(issuer=self.issuer.issuer, introspection_url=self.issuer.issuer + '/introspect',
            service_client_id=self.policy.service_client_id, service_client_secret=self.policy.service_secret,
            resource=self.policy.resource, profile_uid='owner', company_ref='company',
            allowed_client_ids={client['client_id']}, http_client=self.http)
        access = await verifier.verify_token(pair['access_token'])
        self.assertIsNotNone(access)
        self.assertEqual(access.subject, 'owner')
        self.assertEqual(verifier.grant(access.claims).mailbox_ids, frozenset({'mailbox'}))


if __name__ == '__main__':
    unittest.main()
