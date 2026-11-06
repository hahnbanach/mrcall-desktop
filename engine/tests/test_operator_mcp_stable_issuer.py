"""Stable delegated authority on existing OAuth credentials."""

from dataclasses import replace

from tests.test_operator_mcp_issuer import IssuerTests as BaseIssuerTests
from zylch.operator_mcp.issuer import BrokerError
from zylch.operator_mcp.permissions import SCOPES


class StableIssuerTests(BaseIssuerTests):
    async def pair(self):
        client = await self.register()
        pair = (await self.exchange(client, await self.code(client))).json()
        grant_id = (await self.introspect(pair['access_token'])).json()['grant_id']
        return client, pair, grant_id

    def enable(self):
        self.policy = replace(self.policy, operator_enabled=True, allowed_scopes=SCOPES)

    async def refresh(self, client, pair, scope=None):
        data = {'grant_type': 'refresh_token', 'client_id': client['client_id'],
                'refresh_token': pair['refresh_token']}
        if scope is not None:
            data['scope'] = scope
        return await self.http.post('/token', data=data)

    def test_owner_upgrade_same_credentials_and_refresh_chain(self):
        async def exercise():
            client, pair, grant_id = await self.pair()
            grant = self.store.get('grants', grant_id)
            access = self.store.get('access', pair['access_token'])
            refresh = self.store.get('refresh', pair['refresh_token'])
            self.enable()
            self.assertNotIn('pricing.use', (await self.introspect(pair['access_token'])).json()['scope'])
            digest = self.issuer.grant_sha256(grant)
            upgraded = self.issuer.upgrade_operator_access(grant_id, 'owner', digest)
            self.assertEqual({k: v for k, v in upgraded.items() if k != 'operator_delegation'}, grant)
            self.assertEqual(self.store.get('access', pair['access_token']), access)
            self.assertEqual(self.store.get('refresh', pair['refresh_token']), refresh)
            self.assertEqual(self.issuer.upgrade_operator_access(grant_id, 'owner', digest), upgraded)
            self.assertIn('pricing.use', (await self.introspect(pair['access_token'])).json()['scope'])
            refreshed = await self.refresh(client, pair)
            self.assertEqual(refreshed.status_code, 200, refreshed.text)
            self.assertIn('projects.write', (await self.introspect(refreshed.json()['access_token'])).json()['scope'])
            narrowed = await self.refresh(client, refreshed.json(), 'operator.read')
            self.assertEqual(narrowed.status_code, 200, narrowed.text)
            self.assertEqual((await self.introspect(narrowed.json()['access_token'])).json()['scope'], 'operator.read')
            again = await self.refresh(client, narrowed.json())
            self.assertEqual((await self.introspect(again.json()['access_token'])).json()['scope'], 'operator.read')
        self.run_case(exercise)

    def test_upgrade_owner_cas_expiry_revocation_and_company(self):
        async def exercise():
            _, pair, grant_id = await self.pair()
            grant = self.store.get('grants', grant_id)
            digest = self.issuer.grant_sha256(grant)
            self.enable()
            for subject, sha in [('other', digest), ('owner', 'bad')]:
                with self.assertRaises(BrokerError):
                    self.issuer.upgrade_operator_access(grant_id, subject, sha)
            self.assertEqual(self.store.get('grants', grant_id), grant)
            self.issuer.upgrade_operator_access(grant_id, 'owner', digest)
            self.policy = replace(self.policy, company_ref='wrong')
            self.assertFalse((await self.introspect(pair['access_token'])).json()['active'])
            with self.assertRaises(BrokerError):
                self.issuer.upgrade_operator_access(grant_id, 'owner', digest)
            self.policy = replace(self.policy, company_ref='company')
            self.issuer.revoke(grant_id)
            with self.assertRaises(BrokerError):
                self.issuer.upgrade_operator_access(grant_id, 'owner', digest)
            self.assertFalse((await self.introspect(pair['access_token'])).json()['active'])
        self.run_case(exercise)

    def test_full_new_grant_and_feature_addition_without_reauthorization(self):
        async def exercise():
            self.enable()
            self.policy = replace(self.policy, allowed_scopes=SCOPES - {'pricing.use'})
            client = await self.register()
            request_id = await self.start(client, scope='operator.read operator.use')
            self.assertEqual((await self.approve(request_id)).status_code, 200)
            from urllib.parse import parse_qs, urlsplit
            done = await self.http.get('/pending/' + request_id + '/complete')
            code = parse_qs(urlsplit(done.json()['redirect_uri']).query)['code'][0]
            pair = (await self.exchange(client, code)).json()
            self.assertEqual(set(pair['scope'].split()), {'operator.read', 'operator.use'})
            self.assertNotIn('pricing.use', (await self.introspect(pair['access_token'])).json()['scope'])
            self.enable()
            self.assertIn('pricing.use', (await self.introspect(pair['access_token'])).json()['scope'])
            refreshed = await self.refresh(client, pair)
            self.assertEqual(refreshed.status_code, 200, refreshed.text)
            self.assertIn('pricing.use', (await self.introspect(refreshed.json()['access_token'])).json()['scope'])
        self.run_case(exercise)

    def test_legacy_reader_and_preexisting_narrow_access_stay_narrow(self):
        async def exercise():
            client, pair, grant_id = await self.pair()
            narrow = (await self.refresh(client, pair, 'operator.read')).json()
            grant = self.store.get('grants', grant_id)
            self.enable()
            self.assertEqual((await self.introspect(narrow['access_token'])).json()['scope'], 'operator.read')
            self.issuer.upgrade_operator_access(grant_id, 'owner', self.issuer.grant_sha256(grant))
            self.assertEqual((await self.introspect(narrow['access_token'])).json()['scope'], 'operator.read')
            refused = await self.refresh(client, narrow, 'operator.read email.read')
            self.assertEqual(refused.status_code, 400)
            reader = await self.register()
            request_id = await self.start(reader, scope='operator.read')
            await self.approve(request_id)
            from urllib.parse import parse_qs, urlsplit
            done = await self.http.get('/pending/' + request_id + '/complete')
            code = parse_qs(urlsplit(done.json()['redirect_uri']).query)['code'][0]
            reader_pair = (await self.exchange(reader, code)).json()
            self.assertEqual((await self.introspect(reader_pair['access_token'])).json()['scope'], 'operator.read')
        self.run_case(exercise)

    def test_expired_grant_cannot_be_upgraded(self):
        async def exercise():
            _, _, grant_id = await self.pair()
            grant = self.store.get('grants', grant_id)
            self.enable()
            self.now = grant['expires_at']
            with self.assertRaises(BrokerError):
                self.issuer.upgrade_operator_access(grant_id, 'owner', self.issuer.grant_sha256(grant))
            self.assertEqual(self.store.get('grants', grant_id), grant)
        self.run_case(exercise)
