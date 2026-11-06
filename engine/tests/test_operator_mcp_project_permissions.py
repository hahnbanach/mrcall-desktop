import copy
from dataclasses import replace
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from engine.tests import test_operator_mcp_issuer as issuer_fixture
from engine.tests import test_operator_mcp_instruction_auth as policy_fixture
from zylch.operator_mcp.auth import GrantVerifier
from zylch.operator_mcp import policy
from zylch.operator_mcp.permissions import BASE_SCOPES, enabled_scopes, dependencies_satisfied

READ='projects.read'
WRITE='projects.write'

class ProjectPermissions(unittest.TestCase):
    def test_explicit_configuration_and_dependency(self):
        self.assertEqual(enabled_scopes(projects_enabled=True),BASE_SCOPES|{READ,WRITE})
        self.assertNotIn(READ,enabled_scopes())
        self.assertFalse(dependencies_satisfied({'operator.read',WRITE}))
        self.assertTrue(dependencies_satisfied({'operator.read',READ}))
        fixture=policy_fixture.InstructionPolicyTests();fixture.setUp()
        for broker in (False,True):
            for flag in (False,True,None,1,'true'):
                value=copy.deepcopy(fixture.broker if broker else fixture.profile)
                row=value['profiles'][0] if broker else value;row['projects_enabled']=flag
                if type(flag) is bool:self.assertEqual(fixture.load(value,broker),value)
                else:
                    with self.assertRaises(policy.PolicyError):fixture.load(value,broker)
        value=copy.deepcopy(fixture.broker);value['profiles'][0]['projects_enabled']=True
        with patch.object(policy,'load_broker_config',return_value=value),patch.object(policy.trust,'load',return_value={}),patch.object(policy.trust,'member'):
            resolved=policy.broker_policy('/etc/test')(fixture.row['resource'])
        self.assertTrue(resolved.projects_enabled)
        self.assertTrue({READ,WRITE}<=resolved.allowed_scopes)

    def test_new_grants_read_only_write_revocation_and_legacy_preservation(self):
        fixture=issuer_fixture.IssuerTests()
        async def pair(client,scopes):
            request=await fixture.start(client,scope=' '.join(sorted(scopes)))
            self.assertEqual((await fixture.approve(request)).status_code,200)
            complete=await fixture.http.get('/pending/'+request+'/complete')
            code=parse_qs(urlsplit(complete.json()['redirect_uri']).query)['code'][0]
            result=await fixture.exchange(client,code);self.assertEqual(result.status_code,200,result.text)
            return result.json()
        async def exercise():
            old_client=await fixture.register(scope=' '.join(BASE_SCOPES));old=await pair(old_client,BASE_SCOPES)
            before=(await fixture.introspect(old['access_token'])).json()
            fixture.policy=replace(fixture.policy,projects_enabled=True,allowed_scopes=BASE_SCOPES|{READ,WRITE})
            self.assertEqual((await fixture.introspect(old['access_token'])).json(),before)
            upgrade=await fixture.http.post('/token',data={'grant_type':'refresh_token','client_id':old_client['client_id'],'refresh_token':old['refresh_token'],'scope':' '.join(BASE_SCOPES|{READ})})
            self.assertEqual(upgrade.status_code,400)
            for scopes in (BASE_SCOPES|{READ},BASE_SCOPES|{READ,WRITE}):
                client=await fixture.register(scope=' '.join(scopes));new=await pair(client,scopes)
                claims=(await fixture.introspect(new['access_token'])).json()
                self.assertIn('projects',claims['source_classes'])
                kwargs=dict(issuer=fixture.issuer.issuer,introspection_url=fixture.issuer.issuer+'/introspect',service_client_id=fixture.policy.service_client_id,service_client_secret=fixture.policy.service_secret,resource=fixture.policy.resource,profile_uid='owner',company_ref='company',allowed_client_ids={client['client_id']},http_client=fixture.http)
                self.assertIsNone(await GrantVerifier(**kwargs).verify_token(new['access_token']))
                verifier=GrantVerifier(**kwargs,projects_enabled=True)
                self.assertIsNotNone(await verifier.verify_token(new['access_token']))
                for delta in [dict(source_classes=['mail','drafts']),dict(scope=' '.join(BASE_SCOPES)),dict(company_ref='foreign'),dict(scope='operator.read projects.write')]:
                    with self.assertRaises(ValueError):verifier.grant({**claims,**delta})
                fixture.policy=replace(fixture.policy,projects_enabled=False,allowed_scopes=BASE_SCOPES)
                self.assertIsNone(await verifier.verify_token(new['access_token']))
                self.assertTrue((await fixture.introspect(old['access_token'])).json()['active'])
                fixture.policy=replace(fixture.policy,projects_enabled=True,allowed_scopes=BASE_SCOPES|{READ,WRITE})
        fixture.run_case(exercise)
