import unittest
from dataclasses import replace


from zylch.operator_mcp.permissions import (
    BASE_SCOPES, DRAFT_SCOPE, PROPOSAL_SCOPE, enabled_scopes,
    dependencies_satisfied, SCOPES as ALL_SCOPES, RULE_WRITE_SCOPE,
)


SCOPES = ALL_SCOPES - {RULE_WRITE_SCOPE, 'pricing.use', 'projects.read', 'projects.write', 'operator.use'}


class EffectPermissionsTests(unittest.TestCase):
    def test_independent_opt_ins_default_to_existing_reads(self):
        self.assertEqual(enabled_scopes(), BASE_SCOPES)
        rules = enabled_scopes(instructions_enabled=True, proposals_enabled=True)
        self.assertIn(PROPOSAL_SCOPE, rules)
        self.assertNotIn(DRAFT_SCOPE, rules)
        drafts = enabled_scopes(instructions_enabled=True, draft_enabled=True)
        self.assertIn(DRAFT_SCOPE, drafts)
        self.assertNotIn(PROPOSAL_SCOPE, drafts)

    def test_effect_scopes_require_their_authorized_context(self):
        for scopes in ({'operator.read', DRAFT_SCOPE},
                       {'operator.read', PROPOSAL_SCOPE},
                       {'operator.read', 'email.read', 'instructions.read', DRAFT_SCOPE}):
            self.assertFalse(dependencies_satisfied(scopes))
        self.assertTrue(dependencies_satisfied(enabled_scopes(
            instructions_enabled=True, draft_enabled=True, proposals_enabled=True)))

    def test_invalid_opt_ins_do_not_silently_enable_effects(self):
        for values in ({'draft_enabled': True}, {'proposals_enabled': True},
                       {'instructions_enabled': 1}, {'draft_enabled': 'true'}):
            with self.assertRaises(ValueError):
                enabled_scopes(**values)


class EffectIssuerTests(unittest.TestCase):
    def test_six_scope_consent_and_revocation_preserve_old_grants(self):
        from engine.tests.test_operator_mcp_instruction_auth import InstructionIssuerTests
        fixture = InstructionIssuerTests()

        async def exercise():
            old_client = await fixture.register(scope=' '.join(sorted(BASE_SCOPES)))
            old = (await fixture.exchange(old_client, await fixture.code(old_client))).json()
            before = (await fixture.introspect(old['access_token'])).json()
            fixture.policy = replace(fixture.policy, instructions_enabled=True,
                draft_enabled=True, proposals_enabled=True, allowed_scopes=SCOPES)
            client = await fixture.register(scope=' '.join(sorted(SCOPES)))
            # The helper requests four historical read scopes; request all six here.
            from urllib.parse import parse_qs, urlsplit
            request = await fixture.start(client, scope=' '.join(sorted(SCOPES)))
            self.assertEqual((await fixture.approve(request)).status_code, 200)
            completion = await fixture.http.get('/pending/' + request + '/complete')
            code = parse_qs(urlsplit(completion.json()['redirect_uri']).query)['code'][0]
            pair = (await fixture.exchange(client, code)).json()
            claims = (await fixture.introspect(pair['access_token'])).json()
            self.assertEqual(set(claims['scope'].split()), SCOPES)
            self.assertEqual((await fixture.introspect(old['access_token'])).json(), before)
            from zylch.operator_mcp.auth import GrantVerifier
            verifier = GrantVerifier(issuer=fixture.issuer.issuer,
                introspection_url=fixture.issuer.issuer + '/introspect',
                service_client_id=fixture.policy.service_client_id,
                service_client_secret=fixture.policy.service_secret,
                resource=fixture.policy.resource, profile_uid='owner', company_ref='company',
                allowed_client_ids={client['client_id']}, http_client=fixture.http,
                instructions_enabled=True, draft_enabled=True, proposals_enabled=True)
            self.assertIsNotNone(await verifier.verify_token(pair['access_token']))
            fixture.policy = replace(fixture.policy, draft_enabled=False,
                allowed_scopes=SCOPES - {DRAFT_SCOPE})
            self.assertFalse((await fixture.introspect(pair['access_token'])).json()['active'])
            self.assertTrue((await fixture.introspect(old['access_token'])).json()['active'])

        fixture.run_case(exercise)
