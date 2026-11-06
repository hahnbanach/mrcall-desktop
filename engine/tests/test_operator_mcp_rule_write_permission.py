import copy
from dataclasses import replace
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from tests.test_operator_mcp_issuer import IssuerTests
from tests.test_operator_mcp_instruction_auth import InstructionPolicyTests
from zylch.operator_mcp.auth import GrantVerifier
from zylch.operator_mcp import policy
from zylch.operator_mcp.permissions import (
    BASE_SCOPES, RULE_WRITE_SCOPE, SCOPES as ALL_SCOPES, dependencies_satisfied, enabled_scopes,
)


SCOPES = ALL_SCOPES - {'pricing.use', 'projects.read', 'projects.write', 'operator.use'}

class RuleWritePermissionsTests(unittest.TestCase):
    def test_separate_false_default_and_required_read_dependency(self):
        old = enabled_scopes(instructions_enabled=True, draft_enabled=True, proposals_enabled=True)
        self.assertEqual(old, SCOPES - {RULE_WRITE_SCOPE})
        self.assertNotIn(RULE_WRITE_SCOPE, enabled_scopes())
        self.assertEqual(enabled_scopes(instructions_enabled=True, rules_write_enabled=True),
                         BASE_SCOPES | {'instructions.read', RULE_WRITE_SCOPE})
        self.assertFalse(dependencies_satisfied({'operator.read', RULE_WRITE_SCOPE}))
        for flags in ({'rules_write_enabled': True}, {'rules_write_enabled': 1},
                      {'rules_write_enabled': 'true'}, {'rules_write_enabled': None}):
            with self.assertRaises(ValueError):
                enabled_scopes(**flags)

    def test_broker_and_profile_strict_opt_in(self):
        fixture = InstructionPolicyTests()
        fixture.setUp()
        for flag in (False, True, None, 1, 'true'):
            for broker in (False, True):
                value = copy.deepcopy(fixture.broker if broker else fixture.profile)
                row = value['profiles'][0] if broker else value
                row.update(instructions_enabled=True, rules_write_enabled=flag)
                if type(flag) is bool:
                    self.assertEqual(fixture.load(value, broker), value)
                else:
                    with self.assertRaises(policy.PolicyError):
                        fixture.load(value, broker)
        broker = copy.deepcopy(fixture.broker)
        broker['profiles'][0].update(instructions_enabled=True, rules_write_enabled=True)
        with patch.object(policy, 'load_broker_config', return_value=broker), \
             patch.object(policy.trust, 'load', return_value={}), patch.object(policy.trust, 'member'):
            resolved = policy.broker_policy('/etc/mrcalld/test.json')(fixture.row['resource'])
        self.assertTrue(resolved.rules_write_enabled)
        self.assertIn(RULE_WRITE_SCOPE, resolved.allowed_scopes)

    def test_seven_scope_roundtrip_old_six_scope_grant_and_refresh_no_upgrade(self):
        fixture = IssuerTests()

        async def pair(client, scopes):
            request = await fixture.start(client, scope=' '.join(sorted(scopes)))
            self.assertEqual((await fixture.approve(request)).status_code, 200)
            completion = await fixture.http.get('/pending/' + request + '/complete')
            code = parse_qs(urlsplit(completion.json()['redirect_uri']).query)['code'][0]
            result = await fixture.exchange(client, code)
            self.assertEqual(result.status_code, 200, result.text)
            return result.json()

        def verifier(client, enabled):
            return GrantVerifier(issuer=fixture.issuer.issuer,
                introspection_url=fixture.issuer.issuer + '/introspect',
                service_client_id=fixture.policy.service_client_id,
                service_client_secret=fixture.policy.service_secret,
                resource=fixture.policy.resource, profile_uid='owner', company_ref='company',
                allowed_client_ids={client['client_id']}, http_client=fixture.http,
                instructions_enabled=True, draft_enabled=True, proposals_enabled=True,
                rules_write_enabled=enabled)

        async def exercise():
            old_scopes = SCOPES - {RULE_WRITE_SCOPE}
            fixture.policy = replace(fixture.policy, instructions_enabled=True, draft_enabled=True,
                proposals_enabled=True, allowed_scopes=old_scopes)
            client = await fixture.register(scope=' '.join(sorted(SCOPES)))
            old = await pair(client, old_scopes)
            before = (await fixture.introspect(old['access_token'])).json()
            fixture.policy = replace(fixture.policy, rules_write_enabled=True, allowed_scopes=SCOPES)
            self.assertEqual((await fixture.introspect(old['access_token'])).json(), before)
            refused = await fixture.http.post('/token', data={'grant_type': 'refresh_token',
                'client_id': client['client_id'], 'refresh_token': old['refresh_token'],
                'scope': ' '.join(sorted(SCOPES))})
            self.assertEqual(refused.status_code, 400)
            new = await pair(client, SCOPES)
            claims = (await fixture.introspect(new['access_token'])).json()
            self.assertEqual(set(claims['scope'].split()), SCOPES)
            self.assertEqual(set(claims['instruction_paths']),
                             {'procedures.md', 'mail/owner@example.test.md'})
            self.assertIsNone(await verifier(client, False).verify_token(new['access_token']))
            self.assertIsNotNone(await verifier(client, True).verify_token(new['access_token']))
            self.assertNotIn(RULE_WRITE_SCOPE, verifier(client, True).grant(before).scopes)
            invalid = {**claims, 'scope': 'operator.read email.read instructions.write'}
            with self.assertRaises(ValueError):
                verifier(client, True).grant(invalid)
            fixture.policy = replace(fixture.policy, rules_write_enabled=False, allowed_scopes=old_scopes)
            self.assertFalse((await fixture.introspect(new['access_token'])).json()['active'])
            self.assertTrue((await fixture.introspect(old['access_token'])).json()['active'])

        fixture.run_case(exercise)
