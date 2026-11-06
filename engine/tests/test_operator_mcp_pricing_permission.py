import copy
from dataclasses import replace
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from engine.tests.test_operator_mcp_issuer import IssuerTests
from engine.tests.test_operator_mcp_instruction_auth import InstructionPolicyTests
from zylch.operator_mcp.auth import GrantVerifier
from zylch.operator_mcp import policy
from zylch.operator_mcp.permissions import BASE_SCOPES, PRICING_SCOPE, SCOPES, enabled_scopes


class PricingPermissionTests(unittest.TestCase):
    def test_explicit_flag_and_strict_policy(self):
        self.assertNotIn(PRICING_SCOPE, enabled_scopes())
        self.assertEqual(enabled_scopes(pricing_enabled=True), BASE_SCOPES | {PRICING_SCOPE})
        fixture = InstructionPolicyTests(); fixture.setUp()
        for flag in (False, True, None, 1, 'true'):
            for broker in (False, True):
                value = copy.deepcopy(fixture.broker if broker else fixture.profile)
                row = value['profiles'][0] if broker else value
                row['pricing_enabled'] = flag
                if type(flag) is bool:
                    self.assertEqual(fixture.load(value, broker), value)
                else:
                    with self.assertRaises(policy.PolicyError):
                        fixture.load(value, broker)
        broker = copy.deepcopy(fixture.broker); broker['profiles'][0]['pricing_enabled'] = True
        with patch.object(policy, 'load_broker_config', return_value=broker), patch.object(policy.trust, 'load', return_value={}), patch.object(policy.trust, 'member'):
            resolved = policy.broker_policy('/etc/mrcalld/test.json')(fixture.row['resource'])
        self.assertTrue(resolved.pricing_enabled)
        self.assertIn(PRICING_SCOPE, resolved.allowed_scopes)

    def test_new_consent_does_not_upgrade_old_grant_and_revocation(self):
        fixture = IssuerTests()
        async def pair(client, scopes):
            req = await fixture.start(client, scope=' '.join(sorted(scopes)))
            self.assertEqual((await fixture.approve(req)).status_code, 200)
            done = await fixture.http.get('/pending/' + req + '/complete')
            code = parse_qs(urlsplit(done.json()['redirect_uri']).query)['code'][0]
            result = await fixture.exchange(client, code)
            self.assertEqual(result.status_code, 200, result.text)
            return result.json()
        async def exercise():
            old_client = await fixture.register(scope=' '.join(BASE_SCOPES))
            old = await pair(old_client, BASE_SCOPES)
            before = (await fixture.introspect(old['access_token'])).json()
            fixture.policy = replace(fixture.policy, pricing_enabled=True, allowed_scopes=BASE_SCOPES | {PRICING_SCOPE})
            self.assertEqual((await fixture.introspect(old['access_token'])).json(), before)
            upgraded = await fixture.http.post('/token', data={'grant_type':'refresh_token','client_id':old_client['client_id'],'refresh_token':old['refresh_token'],'scope':' '.join(BASE_SCOPES | {PRICING_SCOPE})})
            self.assertEqual(upgraded.status_code, 400)
            client = await fixture.register(scope=' '.join(BASE_SCOPES | {PRICING_SCOPE}))
            new = await pair(client, BASE_SCOPES | {PRICING_SCOPE})
            claims = (await fixture.introspect(new['access_token'])).json()
            self.assertIn('pricing', claims['source_classes'])
            kwargs = dict(issuer=fixture.issuer.issuer,introspection_url=fixture.issuer.issuer+'/introspect', service_client_id=fixture.policy.service_client_id,service_client_secret=fixture.policy.service_secret,resource=fixture.policy.resource,profile_uid='owner',company_ref='company',allowed_client_ids={client['client_id']},http_client=fixture.http)
            denied = GrantVerifier(**kwargs)
            self.assertIsNone(await denied.verify_token(new['access_token']))
            verifier = GrantVerifier(**kwargs, pricing_enabled=True)
            self.assertIsNotNone(await verifier.verify_token(new['access_token']))
            for delta in [dict(source_classes=['mail','drafts']), dict(scope=' '.join(BASE_SCOPES)), dict(company_ref='foreign'), dict(profile_uid='foreign')]:
                with self.assertRaises(ValueError): verifier.grant({**claims, **delta})
            fixture.policy = replace(fixture.policy, pricing_enabled=False, allowed_scopes=BASE_SCOPES)
            self.assertIsNone(await verifier.verify_token(new['access_token']))
            self.assertTrue((await fixture.introspect(old['access_token'])).json()['active'])
        fixture.run_case(exercise)
