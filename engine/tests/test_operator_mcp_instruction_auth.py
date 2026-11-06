import copy
from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from engine.tests import test_operator_mcp_issuer as issuer_tests
from zylch.operator_mcp import policy
from zylch.operator_mcp.auth import GrantVerifier
from zylch.operator_mcp.issuer import BrokerError
from zylch.operator_mcp.permissions import BASE_SCOPES, INSTRUCTION_SCOPE, SCOPES as ALL_SCOPES

SCOPES = BASE_SCOPES | {INSTRUCTION_SCOPE}


class InstructionIssuerTests(issuer_tests.IssuerTests):
    def enable(self):
        self.policy = replace(self.policy, instructions_enabled=True, allowed_scopes=SCOPES)

    async def instruction_pair(self, client):
        request_id = await self.start(client, scope=' '.join(sorted(SCOPES)))
        self.assertEqual((await self.approve(request_id)).status_code, 200)
        done = await self.http.get('/pending/' + request_id + '/complete')
        code = parse_qs(urlsplit(done.json()['redirect_uri']).query)['code'][0]
        response = await self.exchange(client, code)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def resource_verifier(self, client, enabled):
        return GrantVerifier(issuer=self.issuer.issuer, introspection_url=self.issuer.issuer + '/introspect',
            service_client_id=self.policy.service_client_id, service_client_secret=self.policy.service_secret,
            resource=self.policy.resource, profile_uid='owner', company_ref='company',
            allowed_client_ids={client['client_id']}, http_client=self.http, instructions_enabled=enabled)

    def test_new_registration_default_does_not_upgrade_existing_client_or_grant(self):
        async def exercise():
            fresh = await self.register()
            self.assertEqual(set(fresh['scope'].split()), ALL_SCOPES)
            client = await self.register(scope=' '.join(sorted(BASE_SCOPES)))
            self.assertEqual(set(client['scope'].split()), BASE_SCOPES)
            pair = (await self.exchange(client, await self.code(client))).json()
            before = (await self.introspect(pair['access_token'])).json()
            grant = self.store.get('grants', before['grant_id'])
            self.assertEqual(grant['authority'], {'profile_uid': 'owner', 'company_ref': 'company', 'mailbox_ids': ['mailbox']})
            self.enable()
            after = (await self.introspect(pair['access_token'])).json()
            self.assertEqual(before, after)
            self.assertEqual(set(self.store.get('clients', client['client_id'])['scope'].split()), BASE_SCOPES)
            self.assertNotIn('instruction_paths', after)
            metadata = (await self.http.get('/.well-known/oauth-authorization-server')).json()
            self.assertEqual(set(metadata['scopes_supported']), ALL_SCOPES)
            response = await self.http.post('/token', data={'grant_type': 'refresh_token',
                'client_id': client['client_id'], 'refresh_token': pair['refresh_token'], 'scope': ' '.join(SCOPES)})
            self.assertEqual(response.status_code, 400)
        self.run_case(exercise)

    def test_four_scope_claims_narrowing_and_verifier_opt_in(self):
        async def exercise():
            self.enable()
            client = await self.register(scope=' '.join(sorted(SCOPES)))
            pair = await self.instruction_pair(client)
            claims = (await self.introspect(pair['access_token'])).json()
            expected = frozenset({'procedures.md', 'mail/owner@example.test.md'})
            self.assertEqual(set(claims['instruction_paths']), expected)
            self.assertIn('instructions', claims['source_classes'])
            self.assertIsNone(await self.resource_verifier(client, False).verify_token(pair['access_token']))
            access = await self.resource_verifier(client, True).verify_token(pair['access_token'])
            self.assertIsNotNone(access)
            self.assertEqual(self.resource_verifier(client, True).grant(access.claims).instruction_paths, expected)
            narrowed = await self.http.post('/token', data={'grant_type': 'refresh_token',
                'client_id': client['client_id'], 'refresh_token': pair['refresh_token'], 'scope': ' '.join(BASE_SCOPES)})
            self.assertEqual(narrowed.status_code, 200, narrowed.text)
            narrow = narrowed.json()
            claims = (await self.introspect(narrow['access_token'])).json()
            self.assertNotIn('instruction_paths', claims)
            self.assertNotIn('instructions', claims['source_classes'])
            self.assertIsNotNone(await self.resource_verifier(client, False).verify_token(narrow['access_token']))
            refused = await self.http.post('/token', data={'grant_type': 'refresh_token',
                'client_id': client['client_id'], 'refresh_token': narrow['refresh_token'], 'scope': ' '.join(SCOPES)})
            self.assertEqual(refused.status_code, 400)
        self.run_case(exercise)

    def test_policy_disable_or_identity_change_invalidates_only_new_authority(self):
        async def exercise():
            self.enable()
            client = await self.register(scope=' '.join(sorted(SCOPES)))
            old = (await self.exchange(client, await self.code(client))).json()
            new = await self.instruction_pair(client)
            self.policy = replace(self.policy, email='changed@example.test')
            self.assertFalse((await self.introspect(new['access_token'])).json()['active'])
            self.assertTrue((await self.introspect(old['access_token'])).json()['active'])
            self.policy = replace(self.policy, email='owner@example.test', instructions_enabled=False, allowed_scopes=BASE_SCOPES)
            self.assertFalse((await self.introspect(new['access_token'])).json()['active'])
            self.assertTrue((await self.introspect(old['access_token'])).json()['active'])
            refreshed = await self.http.post('/token', data={'grant_type': 'refresh_token',
                'client_id': client['client_id'], 'refresh_token': new['refresh_token']})
            self.assertEqual(refreshed.status_code, 400)
        self.run_case(exercise)

    def test_instruction_claim_dependencies_and_exact_path_shapes(self):
        async def exercise():
            self.enable()
            client = await self.register(scope=' '.join(sorted(SCOPES)))
            pair = await self.instruction_pair(client)
            claims = (await self.introspect(pair['access_token'])).json()
            verifier = self.resource_verifier(client, True)
            for changes in [dict(instruction_paths=[]), dict(instruction_paths=['procedures.md']),
                            dict(instruction_paths=['procedures.md', 'phone.md']),
                            dict(instruction_paths=['procedures.md', 'mail/Owner@example.test.md']),
                            dict(instruction_paths=['procedures.md', 'mail/../bad.md']),
                            dict(instruction_paths=['procedures.md', 'mail/a@example.test.md', 'mail/b@example.test.md']),
                            dict(instruction_paths=['procedures.md', 'procedures.md']),
                            dict(instruction_paths='procedures.md'),
                            dict(source_classes=['mail', 'drafts']),
                            dict(scope='operator.read instructions.read'),
                            dict(scope='operator.read email.read draft.read'),
                            dict(source_classes=['mail', 'drafts', 'instructions', 'phone'])]:
                with self.subTest(changes=changes), self.assertRaises(ValueError):
                    verifier.grant({**claims, **changes})
            old = {**claims, 'scope': 'operator.read email.read draft.read', 'source_classes': ['mail', 'drafts']}
            old.pop('instruction_paths')
            self.assertEqual(verifier.grant(old).instruction_paths, frozenset())
            denied = await self.http.post('/introspect', auth=('wrong', 'service-secret-canary'),
                data={'token': pair['access_token'], 'resource': self.policy.resource})
            self.assertEqual(denied.status_code, 401)
        self.run_case(exercise)

    def test_scope_requires_policy_opt_in_and_mail_permission(self):
        async def exercise():
            self.assertEqual(self.policy.allowed_scopes, BASE_SCOPES)
            for candidate in [self.policy, replace(self.policy, allowed_scopes=SCOPES)]:
                self.policy = candidate
                with self.assertRaises(BrokerError):
                    self.issuer._scope(SCOPES, candidate)
            self.enable()
            with self.assertRaises(BrokerError):
                self.issuer._scope({'operator.read', INSTRUCTION_SCOPE}, self.policy)
        self.run_case(exercise)


class InstructionPolicyTests(unittest.TestCase):
    def setUp(self):
        self.row = dict(profile_uid='owner', email='owner@example.test', company_ref='company',
            resource='https://desktop.example.test/operator/owner/mcp', mailbox_ids=['mailbox'],
            service_client_id='service', service_secret='s' * 32)
        self.profile = dict(self.row, version=1, issuer='https://desktop.example.test',
            socket_path='/run/mrcalld/owner/operator-mcp.sock')
        self.broker = dict(version=1, issuer='https://desktop.example.test', firebase_project='firebase-project',
            native_callbacks=[{'host': '127.0.0.1', 'path': '/callback'}], profiles=[dict(self.row, enabled=True)])

    def load(self, value, broker):
        with patch.object(policy.trust, 'protected_read', return_value=json.dumps(value).encode()), \
             patch.object(Path, 'stat', return_value=SimpleNamespace(st_mode=0o100640, st_uid=0, st_nlink=1)):
            return (policy.load_broker_config if broker else policy.load_profile_config)('/etc/mrcalld/test.json')

    def test_optional_flag_exact_bool_and_unchanged_defaults(self):
        self.assertEqual(self.load(self.profile, False), self.profile)
        self.assertEqual(self.load(self.broker, True), self.broker)
        for flag in (True, False):
            profile = dict(self.profile, instructions_enabled=flag)
            broker = copy.deepcopy(self.broker)
            broker['profiles'][0]['instructions_enabled'] = flag
            self.assertEqual(self.load(profile, False), profile)
            self.assertEqual(self.load(broker, True), broker)
        for value in (None, 0, 1, 'true', [], {}):
            profile = dict(self.profile, instructions_enabled=value)
            broker = copy.deepcopy(self.broker)
            broker['profiles'][0]['instructions_enabled'] = value
            for document, is_broker in ((profile, False), (broker, True)):
                with self.subTest(value=value), self.assertRaises(policy.PolicyError):
                    self.load(document, is_broker)
        with self.assertRaises(policy.PolicyError):
            self.load(dict(self.profile, instructions_enabled=True, extra=True), False)

    def test_profile_binding_carries_only_protected_flag(self):
        from engine.tests import test_operator_mcp_policy as fixtures
        case = fixtures.PolicyTests()
        case.setUp()
        self.assertFalse(case.binding().instructions_enabled)
        case.config['instructions_enabled'] = True
        self.assertTrue(case.binding().instructions_enabled)
        case.config['instructions_enabled'] = 1
        with self.assertRaises(policy.PolicyError):
            case.binding()

    def test_current_protected_opt_in_controls_allowed_scopes(self):
        for flag in (None, False, True):
            broker = copy.deepcopy(self.broker)
            if flag is not None:
                broker['profiles'][0]['instructions_enabled'] = flag
            with patch.object(policy, 'load_broker_config', return_value=broker), \
                 patch.object(policy.trust, 'load', return_value={}), patch.object(policy.trust, 'member'):
                resolved = policy.broker_policy('/etc/mrcalld/test.json')(self.row['resource'])
            self.assertEqual(resolved.instructions_enabled, flag is True)
            self.assertEqual(resolved.allowed_scopes, SCOPES if flag is True else BASE_SCOPES)

    def test_verifier_rejects_nonboolean_flag(self):
        for flag in (None, 0, 1, 'true'):
            with self.assertRaises(ValueError):
                GrantVerifier(issuer='https://auth.example.test', introspection_url='https://auth.example.test/introspect',
                    service_client_id='service', service_client_secret='secret', resource=self.row['resource'],
                    profile_uid='owner', company_ref='company', allowed_client_ids={'client'}, instructions_enabled=flag)
